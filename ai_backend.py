"""
Alliance Terminal Version 3 — AI Backend
OpenVINO GenAI LLM pipeline with NPU-first routing.
"""

import json
import os
import sys
import threading
import logging
import re
import ctypes
from pathlib import Path
import yaml
import openvino_genai as ov_genai
from openvino_genai import StructuredOutputConfig

log = logging.getLogger("normandy.ai")

SCRIPT_DIR = Path(__file__).parent
CONFIG_PATH = SCRIPT_DIR / "config.json"
PROMPTS_PATH = SCRIPT_DIR / "prompts.yaml"

# ── Register CUDA 12 runtime DLLs for llama.cpp (Windows only) ──────────────
# The pre-compiled cu124 wheel needs cublas, cusparse, etc. DLLs at load time.
# These are installed via pip (nvidia-cublas-cu12, etc.) into site-packages/nvidia/.
# We register their directories so Windows can find them without polluting PATH.
if sys.platform == "win32" and hasattr(os, "add_dll_directory"):
    _site_packages = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
    if _site_packages.exists():
        for _pkg_dir in _site_packages.iterdir():
            _bin_dir = _pkg_dir / "bin"
            _lib_dir = _pkg_dir / "lib"
            if _bin_dir.is_dir():
                os.add_dll_directory(str(_bin_dir))
            if _lib_dir.is_dir():
                os.add_dll_directory(str(_lib_dir))


class AIBackend:
    """Manages the OpenVINO GenAI LLM pipeline with config-driven model loading."""

    # JSON Schema — Split Entity Types (v3.0 — with deferral flag)
    EXTRACTION_SCHEMA = {
        "type": "object",
        "additionalProperties": False,
        "required": ["response", "schedule_events", "tasks", "reminders", "facts", "sleep_wake_update"],
        "properties": {
            "response": {"type": "string"},
            "requires_deep_thought": {
                "type": "boolean",
                "description": "NPU sets true if prompt is too complex for fast inference."
            },
            "schedule_events": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["action", "event_name"],
                    "additionalProperties": False,
                    "properties": {
                        "action":               {"type": "string", "enum": ["create","modify","delete"]},
                        "event_name":           {"type": "string"},
                        "start_time_reference": {"type": "string"},
                        "end_time_reference":   {"type": "string"},
                        "duration_minutes":     {"type": "integer"},
                        "priority":             {"type": "integer"},
                        "deadline":             {"type": "string"},
                        "date_reference":       {"type": "string"},
                        "auto_schedule":        {"type": "boolean", "description": "True: engine picks next valid slot from now (energy, gaps). Do not invent HH:MM."}
                    }
                }
            },
            "tasks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["action", "task_name"],
                    "additionalProperties": False,
                    "properties": {
                        "action":           {"type": "string", "enum": ["create","complete","delete"]},
                        "task_name":        {"type": "string"},
                        "duration_minutes": {"type": "integer"},
                        "priority":         {"type": "integer"},
                        "deadline":         {"type": "string"},
                        "auto_schedule":    {"type": "boolean"}
                    }
                }
            },
            "reminders": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["action", "reminder_text"],
                    "additionalProperties": False,
                    "properties": {
                        "action":        {"type": "string", "enum": ["create","dismiss"]},
                        "reminder_text": {"type": "string"},
                        "remind_at":     {"type": "string"},
                        "date_reference":{"type": "string"}
                    }
                }
            },
            "facts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["fact"],
                    "additionalProperties": False,
                    "properties": {
                        "fact":     {"type": "string"},
                        "category": {"type": "string"}
                    }
                }
            },
            "sleep_wake_update": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "sleep_time":    {"type": "string"},
                    "wake_time":     {"type": "string"},
                    "date_reference":{"type": "string"}
                }
            }
        }
    }

    def __init__(self):
        self.config = self._load_config()
        self.active_model_key = self.config.get("active_model", "")
        self.model_info = self.config.get("models", {}).get(self.active_model_key, {})
        
        self.display_name = self.model_info.get("display_name", "Unknown Core")
        self.model_path = str(SCRIPT_DIR / self.model_info.get("path", ""))
        self.engine_type = self.model_info.get("engine", "openvino")
        self.target_device = self.model_info.get("target_device", "NPU")
        self.cache_dir = self.config.get("cache_dir", "model_cache")
        
        # Ensure cache directory exists
        cache_path = SCRIPT_DIR / self.cache_dir
        if not cache_path.exists():
            os.makedirs(cache_path, exist_ok=True)
        
        # State Tracking for UI
        self.model_name = self.display_name
        self.device_used = self.target_device
        self.pipe = None
        self.is_loaded = False
        self._lock = threading.Lock()
        # Abort event: set by PipelineOrchestrator to interrupt generation mid-stream
        self._abort_event = threading.Event()
        # NPU static pipeline: prompt must fit in MAX_PROMPT_LEN; total_ctx >= prompt + generation
        self._openvino_total_context: int = int(self.model_info.get("context_size", 2048))
        self._openvino_prompt_cap: int = self._openvino_total_context  # tightened in initialize() for NPU
        
        # Load Tailored System Prompt — Tiered: NPU vs dGPU
        self.prompts = self._load_prompts()
        self.system_prompt = self._build_system_prompt()

        # Initialization is handled explicitly by main.py boot sequence
        # threading.Thread(target=self.initialize, daemon=True).start()

    def unload(self):
        """
        Safely tear down the active pipeline and release memory.
        Called by PipelineOrchestrator before loading a new model.
        """
        import gc
        with self._lock:
            log.info("[UNLOAD] Tearing down active AI pipeline...")
            try:
                if self.pipe is not None:
                    del self.pipe
                    self.pipe = None
                    log.info("[UNLOAD] Pipeline object deleted.")
                self.is_loaded = False
                gc.collect()
                log.info("[UNLOAD] gc.collect() complete. Memory released.")
            except Exception as e:
                log.error(f"[UNLOAD] Error during pipeline teardown: {e}")
                self.pipe = None
                self.is_loaded = False

    def reload(self, model_key: str):
        """
        Reload the backend with a different model from config.json.
        Re-reads config, updates all internal state, and calls initialize().

        Args:
            model_key: The key in config.json["models"] to load (e.g., "gemma-4-26b-gpu")
        """
        log.info(f"[RELOAD] Reloading AI backend with model key: '{model_key}'")
        try:
            # Re-read config in case it was modified
            self.config = self._load_config()
            model_info = self.config.get("models", {}).get(model_key)

            if not model_info:
                log.error(f"[RELOAD] Model key '{model_key}' not found in config.json!")
                raise ValueError(f"Unknown model key: {model_key}")

            # Update all internal state
            self.active_model_key = model_key
            self.model_info = model_info
            self.display_name = model_info.get("display_name", "Unknown Core")
            self.model_path = str(SCRIPT_DIR / model_info.get("path", ""))
            self.engine_type = model_info.get("engine", "openvino")
            self.target_device = model_info.get("target_device", "NPU")
            self.model_name = self.display_name
            self.device_used = self.target_device

            # Reset context tracking for the new model
            self._openvino_total_context = int(model_info.get("context_size", 2048))
            self._openvino_prompt_cap = self._openvino_total_context

            # Reload prompts (tier-aware: npu_default vs gpu_default)
            self.prompts = self._load_prompts()
            self.system_prompt = self._build_system_prompt()

            # Clear abort event for the new pipeline
            self._abort_event.clear()

            # Initialize the new pipeline
            log.info(f"[RELOAD] Calling initialize() for {self.display_name} on {self.target_device}...")
            self.initialize()

            if self.is_loaded:
                log.info(f"[RELOAD] ✓ Successfully loaded: {self.display_name} on {self.device_used}")
            else:
                log.error(f"[RELOAD] Pipeline loaded but is_loaded is False. Check initialize() logs.")

        except Exception as e:
            log.error(f"[RELOAD] Failed to reload model '{model_key}': {e}", exc_info=True)
            self.is_loaded = False
            raise

    def _get_win32_short_path(self, path: str) -> str:
        """
        Resolve a Windows path to its 8.3 short name (e.g. GITHU~1).
        This eliminates spaces and character limits for finicky drivers.
        """
        try:
            buf = ctypes.create_unicode_buffer(1024)
            ctypes.windll.kernel32.GetShortPathNameW(path, buf, 1024)
            return buf.value or path  # Fallback to original if shortening fails
        except Exception:
            return path

    def _load_config(self) -> dict:
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, "r") as f:
                return json.load(f)
        return {"models": {}}

    def _load_prompts(self) -> dict:
        if PROMPTS_PATH.exists():
            try:
                with open(PROMPTS_PATH, "r", encoding="utf-8") as f:
                    return yaml.safe_load(f)
            except Exception as e:
                log.error(f"Failed to load prompts.yaml: {e}")
        return {}

    def _build_system_prompt(self) -> str:
        """
        Build the system prompt based on the active engine tier.
        NPU models get the lean npu_default prompt.
        dGPU models get the full gpu_default prompt.
        Model-specific hints are appended as a suffix.
        """
        prompts = self.prompts

        # Select tier-appropriate base prompt
        if self.engine_type == "llama.cpp":
            base_prompt = prompts.get("gpu_default", "")
        elif self.engine_type == "openvino":
            base_prompt = prompts.get("npu_default", "")
        else:
            base_prompt = ""

        # Fall back to legacy 'default' if tier prompt is missing
        if not base_prompt:
            base_prompt = prompts.get("default", "")
            if not base_prompt:
                log.warning("No system prompt found in prompts.yaml. AI may behave unexpectedly.")

        # Append model-specific hints
        model_flavor = prompts.get(self.active_model_key, "")
        if model_flavor:
            return f"{base_prompt}\n\n[MODEL HINTS]\n{model_flavor}"
        return base_prompt

    @property
    def available_models(self):
        """Return all model definitions from config."""
        return self.config.get("models", {})

    def is_core_available(self):
        """Check if the active model core exists on disk."""
        if not self.model_info: return False
        path = Path(self.model_info["path"]).resolve()
        if not path.is_absolute():
            # Fallback to Script Dir
            from download_model import SCRIPT_DIR
            path = SCRIPT_DIR / self.model_info["path"]
            
        return path.exists() and any(path.iterdir())

    def initialize(self):
        log.info(f"====== INITIATING AI CORE BOOT ======")
        log.info(f"Core: {self.display_name}")
        log.info(f"Engine: {self.engine_type.upper()} | Target Silicon: {self.target_device}")

        if self.engine_type == "openvino":
            try:
                
                # Use a space-free system path for the NPU cache to avoid driver-level crashes.
                # Project path: C:\Users\ashok\Documents\Github Projects\... (HAS SPACES)
                # Cache path: %LOCALAPPDATA%\AllianceTerminalV3\cache (SAFE)
                local_app_data = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
                abs_cache_path = os.path.join(local_app_data, "AllianceTerminalV3", "cache")
                log.info(f"Targeting tactical cache at: {abs_cache_path}")
                
                if not os.path.exists(abs_cache_path):
                    os.makedirs(abs_cache_path, exist_ok=True)
                
                # Force environment variable and explicit all-caps CACHE_DIR key
                os.environ["OV_GENAI_CACHE_DIR"] = abs_cache_path
                
                # NPU-specific optimizations and context limits
                ov_config = {"CACHE_DIR": abs_cache_path}
                
                if self.target_device == "NPU":
                    # NPU uses a static prompt buffer: MAX_PROMPT_LEN is the max *prompt* tokens.
                    # Generation (max_new_tokens) uses the same total KV budget — do NOT set
                    # MAX_PROMPT_LEN == full model context while also reserving large max_new_tokens,
                    # or tokenization asserts (e.g. input_ids.get_size()).
                    ctx_size = int(self.model_info.get("context_size", 2048))
                    max_gen_cfg = int(self.model_info.get("max_tokens", 1024))
                    safety = 96
                    # Cap generation so prompt_cap stays sane on small contexts (e.g. phi 1024 ctx)
                    max_gen_effective = min(max_gen_cfg, max(128, ctx_size // 2))
                    prompt_cap = max(512, ctx_size - max_gen_effective - safety)
                    ov_config["MAX_PROMPT_LEN"] = prompt_cap
                    # Documented NPU hint (min decoded length); helps some static shapes
                    ov_config["MIN_RESPONSE_LEN"] = min(max_gen_effective, 512)
                    self._openvino_total_context = ctx_size
                    self._openvino_prompt_cap = prompt_cap
                    log.info(
                        f"NPU optimized: total_ctx={ctx_size}, MAX_PROMPT_LEN={prompt_cap}, "
                        f"max_gen_cap≈{max_gen_effective}, config={ov_config}"
                    )
                # Resolve absolute path and then shorten it for NPU stability (8.3 notation)
                self.pip_path = os.path.abspath(self.model_path)
                short_pip_path = self._get_win32_short_path(self.pip_path)
                
                log.info(f"Targeting logic core: {short_pip_path}")
                if short_pip_path != self.pip_path:
                    log.info("  [INFO] Windows 8.3 Path Aliasing active (Safe Pathing).")
                
                # Check for critical files in the model path (using short path for checks too)
                required_files = ["openvino_model.xml", "openvino_model.bin", "config.json"]
                for f in required_files:
                    fpath = os.path.join(short_pip_path, f)
                    if os.path.exists(fpath):
                        log.info(f"  [FOUND] {f}")
                    else:
                        log.error(f"  [MISSING] {f} - Critical for NPU boot!")
                
                log.info(f"Invoking ov_genai.LLMPipeline constructor on {self.target_device}...")
                log.info("  [NOTE] If this is the first run after a folder rename, re-compilation may take 30-60s.")

                # --- ⚡ NPU BOOTSTRAP WITH SAFE-MODE RETRY ⚡ ---
                try:
                    self.pipe = ov_genai.LLMPipeline(short_pip_path, self.target_device, **ov_config)
                except Exception as e:
                    log.warning(f"[WARN] Primary NPU allocation failed: {e}")
                    log.warning("[RETRY] Attempting 'NPU Safe-Mode' (Reduced Context)...")
                    
                    # Drastically reduce context for emergency boot
                    safe_config = {
                        "CACHE_DIR": abs_cache_path,
                        "MAX_PROMPT_LEN": 768,
                        "MIN_RESPONSE_LEN": 256,
                    }
                    try:
                        self.pipe = ov_genai.LLMPipeline(short_pip_path, self.target_device, **safe_config)
                        log.info("[SUCCESS] NPU Safe-Mode active. Note: Context history is limited.")
                    except Exception as e2:
                        log.error(f"[FATAL] NPU hardware refused all tactical configurations: {e2}")
                        raise e2
                
                self.is_loaded = True
                log.info(f"[SUCCESS] OpenVINO hardware graph mapped to {self.target_device}")
            except Exception as e:
                log.error(f"[FATAL] OpenVINO failed on {self.target_device}: {e}")
                import traceback
                log.error(traceback.format_exc())

        elif self.engine_type == "llama.cpp":
            try:
                from llama_cpp import Llama
            
                # Detect GPU backend: CUDA vs Vulkan
                # CUDA builds don't use GGML_VK_VISIBLE_DEVICES
                is_cuda = False
                try:
                    import llama_cpp
                    # Check if the build supports CUDA by inspecting available symbols
                    # CUDA builds will have ggml_cuda in the binary
                    build_info = getattr(llama_cpp, '__version__', 'unknown')
                    log.info(f"[LLAMA] llama-cpp-python version: {build_info}")
                except Exception:
                    pass

                # For Vulkan builds, set the visible device
                if "." in self.target_device:
                    vk_device = self.target_device.split(".")[1]
                    os.environ["GGML_VK_VISIBLE_DEVICES"] = vk_device
                    log.info(f"[LLAMA] Vulkan device hint: {vk_device}")
                else:
                    log.info(f"[LLAMA] Targeting dGPU (CUDA preferred, Vulkan fallback)")
            
                # Read config-driven parameters
                n_gpu_layers = int(self.model_info.get("n_gpu_layers", -1))
                use_mmap = self.model_info.get("use_mmap", not self.model_info.get("no_mmap", False))
                ctx_size = int(self.model_info.get("context_size", 4096))
                use_flash_attn = bool(self.model_info.get("flash_attn", False))
                
                log.info(f"[LLAMA] Init params: n_gpu_layers={n_gpu_layers}, ctx={ctx_size}, "
                         f"flash_attn={use_flash_attn}, mmap={use_mmap}")
                log.info(f"[LLAMA] Model path: {self.model_path}")

                self.pipe = Llama(
                    model_path=self.model_path,
                    n_gpu_layers=n_gpu_layers,
                    n_ctx=ctx_size,
                    use_mmap=use_mmap,
                    flash_attn=use_flash_attn,
                    verbose=True
                )
                self.is_loaded = True
                log.info(f"[SUCCESS] Llama.cpp pipeline established: "
                         f"{n_gpu_layers} layers offloaded, flash_attn={use_flash_attn}")
            except Exception as e:
                error_msg = str(e)
                log.error(f"[FATAL] Llama.cpp initialization failed: {error_msg}")
                import traceback
                log.error(traceback.format_exc())
                # Provide actionable guidance for common failures
                if "missing tensor" in error_msg or "ssm_conv1d" in error_msg:
                    log.error(
                        "[HINT] This model uses an architecture (MTP/SSM) not supported by your "
                        f"llama-cpp-python version. Rebuild from source with the latest llama.cpp, "
                        f"or use a non-MTP model variant."
                    )
                elif "not found" in error_msg.lower() or "no such file" in error_msg.lower():
                    log.error(f"[HINT] Model file not found at: {self.model_path}")
                self._load_error_msg = error_msg

    @staticmethod
    def _estimate_prompt_tokens(text: str) -> int:
        """Rough upper bound on token count (mixed EN + JSON); avoids NPU context overflow."""
        if not text:
            return 1
        return max(1, (len(text) + 3) // 4)

    def _budget_openvino_prompt(self, user_message: str, rag_context: str) -> tuple[str, int]:
        """
        Fit prompt + max_new_tokens within model context window.
        NPU/OpenVINO assert if prompt_tokens + max_new > context (see input_ids.get_size()).
        On NPU, MAX_PROMPT_LEN may be much smaller than context_size — use self._openvino_prompt_cap.
        """
        total_ctx = int(self.model_info.get("context_size", 2048))
        max_tokens_cfg = int(self.model_info.get("max_tokens", 1024))
        # Hard prompt token budget (must match NPU MAX_PROMPT_LEN set in initialize)
        prompt_cap = int(getattr(self, "_openvino_prompt_cap", total_ctx))
        max_gen_effective = min(max_tokens_cfg, max(128, total_ctx // 2))
        safety = 96  # tokenizer specials + structured JSON schema overhead

        user_message = (user_message or "").strip() or "."
        dossier = rag_context or ""

        def context_block_from(d: str) -> str:
            return f"\n\n[DOSSIER FACTS]\n{d}\n" if d else ""

        def make_full(system_text: str, cb: str) -> str:
            return (
                f"<|system|>{system_text}\n{cb}<|end|>\n"
                f"<|user|>{user_message}<|end|>\n<|assistant|>"
            )

        sys_text = self.system_prompt
        cb = context_block_from(dossier)
        full = make_full(sys_text, cb)

        pt = self._estimate_prompt_tokens(full)

        def cap_max_new() -> int:
            # Total sequence must fit in model context; prompt must fit in NPU prompt buffer
            by_total = max(32, min(max_gen_effective, total_ctx - pt - safety))
            return max(32, min(by_total, total_ctx - pt - safety))

        max_new = cap_max_new()

        iteration = 0
        while (pt > prompt_cap or pt + max_new > total_ctx) and iteration < 48:
            iteration += 1
            if len(dossier) > 400:
                dossier = dossier[: max(200, len(dossier) * 2 // 3)] + "\n[... dossier truncated ...]"
            elif cb:
                cb = ""
                dossier = ""
            elif len(sys_text) > 5000:
                target = max(3500, len(sys_text) * 2 // 3)
                half = target // 2
                sys_text = sys_text[:half] + "\n[... system instructions truncated ...]\n" + sys_text[-half:]
            elif len(sys_text) > 2200:
                target = max(1500, len(sys_text) * 2 // 3)
                half = target // 2
                sys_text = sys_text[:half] + "\n[... system instructions truncated ...]\n" + sys_text[-half:]
            else:
                max_new = max(32, max_new // 2)
            cb = context_block_from(dossier)
            full = make_full(sys_text, cb)
            pt = self._estimate_prompt_tokens(full)
            max_new = cap_max_new()

        max_new = max(32, min(max_new, total_ctx - pt - safety, max_gen_effective))

        # Final hard cap on characters so tokenizer cannot exceed NPU MAX_PROMPT_LEN
        max_chars_budget = max(400, prompt_cap * 3 - 64)
        if len(full) > max_chars_budget:
            # Safely slice from the middle of system text to preserve user_message at the end
            allowed_sys = max(100, max_chars_budget - len(user_message) - len(cb) - 80)
            if len(sys_text) > allowed_sys:
                half = allowed_sys // 2
                sys_text = sys_text[:half] + "\n[... truncated ...]\n" + sys_text[-half:]
                full = make_full(sys_text, cb)
                pt = self._estimate_prompt_tokens(full)
                max_new = max(32, min(max_gen_effective, total_ctx - pt - safety))

        if pt + max_new > total_ctx:
            max_chars = max(400, (total_ctx - max_new - safety) * 3)
            if len(full) > max_chars:
                allowed_sys = max(100, max_chars - len(user_message) - len(cb) - 80)
                if len(sys_text) > allowed_sys:
                    half = allowed_sys // 2
                    sys_text = sys_text[:half] + "\n[... truncated ...]\n" + sys_text[-half:]
                    full = make_full(sys_text, cb)
                    pt = self._estimate_prompt_tokens(full)
                    max_new = max(32, min(max_gen_effective, total_ctx - pt - safety))

        log.info(
            f"OpenVINO context budget: est_prompt_tokens≈{pt}, max_new_tokens={max_new}, "
            f"total_ctx={total_ctx}, prompt_cap={prompt_cap}"
        )
        return full, max_new

    def _generate_sync(self, user_message: str, rag_context: str = "", stream_callback=None):
        """Unified Generator handling both OpenVINO and Llama.cpp logic."""
        with self._lock:
            if not self.is_loaded:
                log.error("Attempted generation while core was offline.")
                return "[ERROR] AI Core offline. Check logs.", [], [], [], [], None, False

            context_block = ""
            if rag_context:
                context_block = f"\n\n[DOSSIER FACTS]\n{rag_context}\n"

            # --- PARAMETER EXTRACTION ---
            temp = self.model_info.get("temperature", 0.3)
            top_p = self.model_info.get("top_p", 0.9)
            top_k = self.model_info.get("top_k", 40)
            max_tokens = self.model_info.get("max_tokens", 2048)
            
            # Advanced Penalties (Unified across engines)
            presence_penalty = self.model_info.get("presence_penalty", 0.0)
            frequency_penalty = self.model_info.get("frequency_penalty", 0.0)
            # Support both naming conventions
            repeat_penalty = self.model_info.get("repetition_penalty", self.model_info.get("repeat_penalty", 1.1))
            logit_bias = self.model_info.get("logit_bias", None)
            raw_text = ""
            
            log.info(f"Generating via {self.engine_type.upper()} on {self.target_device}...")

            try:
                if self.engine_type == "openvino":
                    # --- OPENVINO GENERATION LOGIC ---
                    full_prompt, ov_max_new = self._budget_openvino_prompt(user_message, rag_context)
                    
                    # LOG TELEMETRY
                    log.info(f"System Message Size: {len(self.system_prompt)} chars")
                    log.info(f"RAG / dossier size: {len(rag_context or '')} chars")
                    log.info(f"Total Prompt String Size: {len(full_prompt)} chars")
                    
                    def ov_streamer(subword: str) -> ov_genai.StreamingStatus:
                        nonlocal raw_text
                        # Check abort event every token for graceful mid-generation halt
                        if self._abort_event.is_set():
                            log.info("[ABORT] Generation aborted via abort event (OpenVINO streamer).")
                            return ov_genai.StreamingStatus.STOP
                        raw_text += subword
                        if stream_callback: stream_callback(subword)
                        return ov_genai.StreamingStatus.RUNNING

                    # Use GenerationConfig object instead of dict (Required in 2025.4.1+)
                    ov_config = ov_genai.GenerationConfig()
                    ov_config.max_new_tokens = ov_max_new
                    ov_config.do_sample = temp > 0
                    ov_config.temperature = temp
                    ov_config.top_p = top_p
                    ov_config.top_k = top_k
                    ov_config.presence_penalty = presence_penalty
                    ov_config.frequency_penalty = frequency_penalty
                    ov_config.repetition_penalty = repeat_penalty
                    
                    # Apply Structured Output Config (xgrammar)
                    # Note: In 2025.4+, json_schema is a property, not a callable method.
                    so_config = StructuredOutputConfig()
                    so_config.json_schema = json.dumps(self.EXTRACTION_SCHEMA)

                    try:
                        self.pipe.generate(
                            full_prompt,
                            streamer=ov_streamer,
                            generation_config=ov_config,
                            structured_output_config=so_config,
                        )
                    except Exception as gen_exc:
                        # Some NPU + xgrammar builds fail tokenization; plain generate still works.
                        log.warning(
                            "Structured JSON generation failed (%s); retrying without schema.",
                            gen_exc,
                        )
                        raw_text = ""
                        self.pipe.generate(
                            full_prompt,
                            streamer=ov_streamer,
                            generation_config=ov_config,
                        )

                elif self.engine_type == "llama.cpp":
                    # --- LLAMA.CPP GENERATION LOGIC ---
                    messages = [
                        {"role": "system", "content": self.system_prompt + context_block},
                        {"role": "user", "content": user_message}
                    ]

                    # Config-driven thinking toggle (defaults to False)
                    is_thinking_model = bool(self.model_info.get("enable_thinking", False))

                    response = self.pipe.create_chat_completion(
                        messages=messages,
                        stream=True,
                        temperature=temp,
                        top_p=top_p,
                        top_k=top_k,
                        max_tokens=max_tokens,
                        presence_penalty=presence_penalty,
                        frequency_penalty=frequency_penalty,
                        repeat_penalty=repeat_penalty,
                        logit_bias=logit_bias
                    )

                    # Track thinking state so we don't stream <think> to the UI
                    in_thinking = False
                    for chunk in response:
                        if self._abort_event.is_set():
                            log.info("[ABORT] Generation aborted via abort event (Llama.cpp chunk loop).")
                            break
                        delta = chunk['choices'][0].get('delta', {})
                        if 'content' in delta:
                            token = delta['content']
                            raw_text += token

                            # Suppress thinking tokens from UI stream
                            if is_thinking_model:
                                if '<think>' in token:
                                    in_thinking = True
                                    continue
                                if '</think>' in token:
                                    in_thinking = False
                                    continue
                                if in_thinking:
                                    continue

                            if stream_callback:
                                stream_callback(token)

            except Exception as e:
                log.error(f"Generation aborted: {e}")
                return f"[CRITICAL FAILURE] {e}", [], [], [], [], None, False

            # Strip <think> blocks before post-processing
            import re
            raw_text = re.sub(r'<think>.*?</think>', '', raw_text, flags=re.DOTALL).strip()

            log.info("Generation complete. Parsing outputs...")
            res = self._post_process(raw_text)
            return res

    def _post_process(self, raw_text: str):
        """Parse new split-entity schema. Returns 7-tuple including requires_deep_thought."""
        print("\n" + "="*60)
        print(" [AI CORE] RAW OUTPUT ".center(60, "="))
        print(raw_text)
        print("="*60)

        # ====== JSON REPAIR HEURISTICS ======
        raw_text = raw_text.strip()
        
        if raw_text.startswith("```json"):
            raw_text = raw_text[7:]
        elif raw_text.startswith("```"):
            raw_text = raw_text[3:]
            
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3]
            
        raw_text = raw_text.strip()
        
        # Attempt to auto-wrap missing root-level curly braces
        if raw_text.startswith('"response"'):
            raw_text = "{" + raw_text
            
        # Try to aggressively slice context garbage
        start_idx = raw_text.find('{')
        end_idx = raw_text.rfind('}')
        if start_idx != -1 and end_idx != -1 and end_idx >= start_idx:
            raw_text = raw_text[start_idx:end_idx+1]
            
        try:
            data = json.loads(raw_text)

            response_text       = data.get("response", "Processing complete.")
            facts               = data.get("facts", [])
            schedule_events     = data.get("schedule_events", [])
            tasks               = data.get("tasks", [])
            reminders           = data.get("reminders", [])
            sleep_wake          = data.get("sleep_wake_update", {}) or {}
            requires_deep       = data.get("requires_deep_thought", False)

            # Normalise sleep_wake: discard if both fields are null/empty
            sw_sleep = sleep_wake.get("sleep_time") or ""
            sw_wake  = sleep_wake.get("wake_time") or ""
            
            # AI Hallucination Guard: Sometimes models output '00:00' instead of null
            # Only permit '00:00' if they contextually acknowledged a sleep/wake time AND mentioned the time
            resp_lower = response_text.lower()
            
            has_time = any(k in resp_lower for k in ["00:", "12:00", "12a", "zero", "midnight"])
            
            if sw_sleep in ["00:00", "0:00", "midnight"]:
                has_sleep = any(k in resp_lower for k in ["sleep", "bed", "night"])
                if not (has_time and has_sleep):
                    sw_sleep = ""
                    
            if sw_wake in ["00:00", "0:00", "midnight"]:
                has_wake = any(k in resp_lower for k in ["wake", "up", "morning"])
                if not (has_time and has_wake):
                    sw_wake = ""
            
            sleep_wake = sleep_wake if (sw_sleep or sw_wake) else None

            # Terminal telemetry
            print(f"\n[RESPONSE] >> {response_text}")
            if facts:
                print("\n[FACTS]")
                for f in facts:
                    print(f"  • {f.get('fact')} ({f.get('category','General')})")
            if schedule_events:
                print("\n[SCHEDULE EVENTS]")
                for e in schedule_events:
                    print(f"  • {e.get('action','?').upper()}: {e.get('event_name')} @ {e.get('start_time_reference','?')}")
            if tasks:
                print("\n[TASKS]")
                for t in tasks:
                    print(f"  • {t.get('action','?').upper()}: {t.get('task_name')} P{t.get('priority',5)}")
            if reminders:
                print("\n[REMINDERS]")
                for r in reminders:
                    print(f"  • {r.get('reminder_text')} @ {r.get('remind_at','?')}")
            if sleep_wake:
                print(f"\n[SLEEP/WAKE] sleep={sw_sleep or 'n/a'} wake={sw_wake or 'n/a'}")
            
            # --- HEURISTIC FALLBACK ENGINE ---
            # Quantized NPU models sometimes fail to populate arrays but acknowledge the task in 'response'.
            response_lower = response_text.lower()
            
            # 1. Catch missing Reminders
            if not reminders and "remind" in response_lower:
                time_match = re.search(r'at (\d{1,2}(?::\d{2})?(?:[ap]m)?)', response_lower)
                # Ensure we don't accidentally catch "remind me to..." without a time as a reminder
                # (if no time, it's usually a task)
                if time_match:
                    rem_time = time_match.group(1)
                    log.warning(f"HEURISTIC: Rebuilding missing reminder at {rem_time} from response string.")
                    reminders.append({
                        "action": "create",
                        "reminder_text": "System Auto-Recovered Reminder",
                        "remind_at": rem_time,
                        "date_reference": "today"
                    })
                    response_text += "<br><span style='color:#00e5ff'>[NPU Fallback: Reminder recovered]</span>"

            # 2. Catch missing Tasks / Schedules
            if not tasks and not schedule_events and any(x in response_lower for x in ["schedule", "add", "queue", "task"]):
                time_match = re.search(r'at (\d{1,2}(?::\d{2})?(?:[ap]m)?)', response_lower)
                if time_match:
                    sked_time = time_match.group(1)
                    log.warning(f"HEURISTIC: Rebuilding missing schedule event at {sked_time}.")
                    schedule_events.append({
                        "action": "create",
                        "event_name": "Auto-Recovered Task",
                        "start_time_reference": sked_time,
                        "duration_minutes": 60,
                        "priority": 5,
                        "auto_schedule": False
                    })
                    response_text += "<br><span style='color:#00e5ff'>[NPU Fallback: Schedule recovered]</span>"
                elif "add" in response_lower or "queue" in response_lower or "task" in response_lower:
                    log.warning("HEURISTIC: Rebuilding missing floating task.")
                    tasks.append({
                        "action": "create",
                        "task_name": "Auto-Recovered Floating Task",
                        "duration_minutes": 60,
                        "priority": 5,
                        "auto_schedule": True
                    })
                    response_text += "<br><span style='color:#00e5ff'>[NPU Fallback: Task recovered]</span>"
                    
            print("="*60 + "\n")

            clean_text = response_text.replace("\n", "<br>")
            return clean_text, facts, schedule_events, tasks, reminders, sleep_wake, requires_deep

        except Exception as e:
            log.error(f"Post-process failure: {e}")
            print(f"\n[CRITICAL ERROR] Failed to parse AI output: {e}")
            print("="*60 + "\n")
            return f"[ERROR] Output extraction failed: {e}", [], [], [], [], None, False

    def get_device_info(self) -> dict:
        return {
            "model":  self.model_name,
            "device": self.device_used,
        }
