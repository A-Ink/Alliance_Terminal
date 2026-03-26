"""
Alliance Terminal — AI Backend
OpenVINO GenAI LLM pipeline with NPU-first routing.
"""

import json
import os
import threading
import logging
import re
from pathlib import Path
import yaml
import openvino_genai as ov_genai
from openvino_genai import StructuredOutputConfig

log = logging.getLogger("normandy.ai")

SCRIPT_DIR = Path(__file__).parent
CONFIG_PATH = SCRIPT_DIR / "config.json"
PROMPTS_PATH = SCRIPT_DIR / "prompts.yaml"


class AIBackend:
    """Manages the OpenVINO GenAI LLM pipeline with config-driven model loading."""

    # JSON Schema for Extraction-First AI (Aligned with Logic Layer Pydantic models)
    EXTRACTION_SCHEMA = {
        "type": "object",
        "properties": {
            "response": { "type": "string", "description": "Conversational reply as Normandy (Formal Butler)." },
            "entities": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "action": { "type": "string", "enum": ["create", "modify", "delete"] },
                        "intent_type": { "type": "string", "enum": ["fixed_event", "floating_task", "status_update"] },
                        "event_name": { "type": "string", "description": "Simplified, professional task name." },
                        "start_time_reference": { "type": "string", "description": "Time string if mentioned (e.g. '09:00', '14:30' or 'now')." },
                        "end_time_reference": { "type": "string", "description": "Time string if mentioned (e.g. '12:00')." },
                        "duration_minutes": { "type": "integer", "description": "Total duration in minutes." },
                        "deadline": { "type": "string", "description": "ISO format deadline if mentioned." },
                        "priority": { "type": "integer", "description": "Priority score 1-10." }
                    },
                    "required": ["intent_type", "event_name"]
                }
            },
            "facts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "fact": { "type": "string", "description": "Extracted user preference or info." },
                        "category": { "type": "string" }
                    },
                    "required": ["fact"]
                }
            }
        },
        "required": ["response", "entities", "facts"],
        "additionalProperties": False,
        "items_required": ["action", "intent_type", "event_name"] # Internal hint for schema enforcement if supported
    }

    # Updating schema to make action required within entities
    EXTRACTION_SCHEMA["properties"]["entities"]["items"]["required"] = ["action", "intent_type", "event_name"]

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
        
        # Load Tailored System Prompt (Combined with Default Instructions)
        self.prompts = self._load_prompts()
        default_prompt = self.prompts.get("default", "")
        model_flavor = self.prompts.get(self.active_model_key, "")
        
        # Combine default core instructions with model-specific persona/flavor
        self.system_prompt = f"{default_prompt}\n\n[CORE PERSONA & MODEL HINTS]\n{model_flavor}"
        
        if not default_prompt:
             log.warning(f"No default system prompt found. AI may behave unexpectedly.")

        # Initialization is handled explicitly by main.py boot sequence
        # threading.Thread(target=self.initialize, daemon=True).start()

    def _load_config(self) -> dict:
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, "r") as f:
                return json.load(f)
        return {"models": {}}

    def _load_prompts(self) -> dict:
        if PROMPTS_PATH.exists():
            try:
                with open(PROMPTS_PATH, "r") as f:
                    return yaml.safe_load(f)
            except Exception as e:
                log.error(f"Failed to load prompts.yaml: {e}")
        return {}

    def initialize(self):
        log.info(f"====== INITIATING AI CORE BOOT ======")
        log.info(f"Core: {self.display_name}")
        log.info(f"Engine: {self.engine_type.upper()} | Target Silicon: {self.target_device}")

        if self.engine_type == "openvino":
            try:
                
                # Use absolute path for caching to ensure it hits the model_cache folder
                abs_cache_path = str(SCRIPT_DIR / self.cache_dir)
                log.info(f"Setting cache directory to: {abs_cache_path}")
                
                # Force environment variable and explicit all-caps CACHE_DIR key
                os.environ["OV_GENAI_CACHE_DIR"] = abs_cache_path
                
                # NPU-specific optimizations and context limits
                ov_config = {"CACHE_DIR": abs_cache_path}
                
                if self.target_device == "NPU":
                    # Map context_size to MAX_PROMPT_LEN for NPU
                    ctx_size = self.model_info.get("context_size", 1024)
                    max_tokens = self.model_info.get("max_tokens", 1024)
                    
                    ov_config["MAX_PROMPT_LEN"] = int(ctx_size)
                    ov_config["PER_DEVICE_MAX_TOKENS"] = int(max_tokens)
                    log.info(f"NPU optimized: MAX_PROMPT_LEN={ctx_size}, MAX_TOKENS={max_tokens}")
                
                self.pipe = ov_genai.LLMPipeline(self.model_path, self.target_device, **ov_config)
                
                self.is_loaded = True
                log.info(f"[SUCCESS] OpenVINO hardware graph mapped to {self.target_device}")
            except Exception as e:
                log.error(f"[FATAL] OpenVINO failed on {self.target_device}: {e}")

        elif self.engine_type == "llama.cpp":
            try:
                from llama_cpp import Llama
            
                # Extract Device ID (GPU.1 -> 1) to ensure we hit the iGPU, not the dGPU.
                vk_device = "1" 
                if "." in self.target_device:
                    vk_device = self.target_device.split(".")[1]
            
                os.environ["GGML_VK_VISIBLE_DEVICES"] = vk_device
                log.info(f"Hardware API locked to physical device ID: {vk_device}")
            
                # Advanced Initialization Parameters
                use_mmap = self.model_info.get("use_mmap", not self.model_info.get("no_mmap", False))
                ctx_size = self.model_info.get("context_size", 4096)
                
                self.pipe = Llama(
                    model_path=self.model_path,
                    n_gpu_layers=-1, 
                    n_ctx=ctx_size,      
                    use_mmap=use_mmap,
                    verbose=True    
                )
                self.is_loaded = True
                log.info(f"[SUCCESS] Llama.cpp Vulkan bridge established on Device {vk_device}")
            except Exception as e:
                log.error(f"[FATAL] Llama.cpp initialization failed: {e}")
                self.is_loaded = False

    def _generate_sync(self, user_message: str, rag_context: str = "", stream_callback=None):
        """Unified Generator handling both OpenVINO and Llama.cpp logic."""
        with self._lock:
            if not self.is_loaded:
                log.error("Attempted generation while core was offline.")
                return "[ERROR] AI Core offline. Check logs.", [], []

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
                    full_prompt = f"<|system|>{self.system_prompt}\n{context_block}<|end|>\n<|user|>{user_message}<|end|>\n<|assistant|>"
                    
                    # LOG TELEMETRY
                    log.info(f"System Message Size: {len(self.system_prompt)} chars")
                    log.info(f"Context Block Size: {len(context_block)} chars")
                    log.info(f"Total Prompt String Size: {len(full_prompt)} chars")
                    
                    def ov_streamer(subword: str) -> ov_genai.StreamingStatus:
                        nonlocal raw_text
                        raw_text += subword
                        if stream_callback: stream_callback(subword)
                        return ov_genai.StreamingStatus.RUNNING

                    # Use GenerationConfig object instead of dict (Required in 2025.4.1+)
                    ov_config = ov_genai.GenerationConfig()
                    ov_config.max_new_tokens = max_tokens
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
                    
                    self.pipe.generate(
                        full_prompt, 
                        streamer=ov_streamer,
                        generation_config=ov_config,
                        structured_output_config=so_config
                    )

                elif self.engine_type == "llama.cpp":
                    # --- LLAMA.CPP GENERATION LOGIC ---
                    messages = [
                        {"role": "system", "content": self.system_prompt + context_block},
                        {"role": "user", "content": user_message}
                    ]
                    
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
                    
                    for chunk in response:
                        delta = chunk['choices'][0].get('delta', {})
                        if 'content' in delta:
                            token = delta['content']
                            raw_text += token
                            if stream_callback: stream_callback(token)
                            
            except Exception as e:
                log.error(f"Generation aborted: {e}")
                return f"[CRITICAL FAILURE] {e}", [], []

            log.info("Generation complete. Parsing outputs...")
            response_text, facts, schedule_updates = self._post_process(raw_text)
            return response_text, facts, schedule_updates

    def _post_process(self, raw_text: str):
        """Standardized JSON parsing with extraction-first schema."""
        print("\n" + "="*60)
        print(" [AI CORE] RAW OUTPUT RECEIVED ".center(60, "="))
        print(raw_text)
        print("="*60)

        try:
            # Check for obvious truncation (missing ending braces)
            if not raw_text.strip().endswith("}"):
                log.warning("Detected potentially truncated AI response. Attempting recovery...")
                # Basic recovery: try to close the JSON if it looks like it was cut off
                if raw_text.count("{") > raw_text.count("}"):
                    # Very crude recovery for single-object or array-of-objects truncation
                    if raw_text.strip().endswith(",") or raw_text.strip().endswith("[") or raw_text.strip().endswith("{"):
                        pass # Too broken to auto-fix reliably without a real parser
                    else:
                        pass 

            # The engine now GUARANTEES valid JSON matching the schema (unless truncated)
            data = json.loads(raw_text)
            
            response_text = data.get("response", "Processing complete.")
            facts = data.get("facts", [])
            entities = data.get("entities", [])
            
            # Print formatted summary for terminal troubleshooting
            print(f"\n[RESPONSE] >> {response_text}")
            
            if facts:
                print("\n[EXTRACTED FACTS]")
                for f in facts:
                    print(f" • {f.get('fact')} ({f.get('category', 'General')})")
            
            if entities:
                print("\n[SCHEDULE UPDATES]")
                for e in entities:
                    print(f" • {e.get('action', 'update').upper()}: {e.get('event_name')} @ {e.get('start_time_reference', 'floating')}")
            
            print("="*60 + "\n")

            # Map entities to schedule_updates for the UI / Logic Layer
            schedule_updates = []
            for ent in entities:
                ent["type"] = "schedule" # Bridge
                # Rename/Map fields if logic_engine bridge expects specific keys
                schedule_updates.append(ent)
                
            # Clean up response text for HTML
            clean_text = response_text.replace("\n", "<br>")
            
            return clean_text, facts, schedule_updates
            
        except Exception as e:
            log.error(f"Post-process failure: {e}")
            print(f"\n[CRITICAL ERROR] Failed to parse AI output: {e}")
            print("="*60 + "\n")
            # Fallback to legacy extraction if something went horribly wrong
            return f"[ERROR] Output extraction failed: {e}", [], []

    def get_device_info(self) -> dict:
        return {
            "model": self.model_name,
            "device": self.device_used,
        }
