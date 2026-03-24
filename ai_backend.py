"""
Alliance Terminal — AI Backend
OpenVINO GenAI LLM pipeline with NPU-first routing.
"""

import json
import threading
import logging
import re
from pathlib import Path
import yaml
from transformers import TextIteratorStreamer
import openvino_genai as ov_genai

log = logging.getLogger("normandy.ai")

SCRIPT_DIR = Path(__file__).parent
CONFIG_PATH = SCRIPT_DIR / "config.json"
PROMPTS_PATH = SCRIPT_DIR / "prompts.yaml"


class AIBackend:
    """Manages the OpenVINO GenAI LLM pipeline with config-driven model loading."""

    def __init__(self):
        self.config = self._load_config()
        self.active_model_key = self.config.get("active_model", "")
        self.model_info = self.config.get("models", {}).get(self.active_model_key, {})
        
        self.display_name = self.model_info.get("display_name", "Unknown Core")
        self.model_path = str(SCRIPT_DIR / self.model_info.get("path", ""))
        self.engine_type = self.model_info.get("engine", "openvino")
        self.target_device = self.model_info.get("target_device", "NPU")
        
        # State Tracking for UI
        self.model_name = self.display_name
        self.device_used = self.target_device
        self.pipe = None
        self.is_loaded = False
        self._lock = threading.Lock()
        
        # Load Tailored System Prompt
        self.prompts = self._load_prompts()
        self.system_prompt = self.prompts.get(self.active_model_key, self.prompts.get("default", ""))
        
        if not self.system_prompt:
             log.warning(f"No system prompt found for {self.active_model_key}. AI may behave unexpectedly.")

        threading.Thread(target=self.initialize, daemon=True).start()

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
                import openvino_genai as ov_genai
                self.pipe = ov_genai.LLMPipeline(self.model_path, self.target_device)
                self.is_loaded = True
                log.info(f"[SUCCESS] OpenVINO hardware graph mapped to {self.target_device}")
            except Exception as e:
                log.error(f"[FATAL] OpenVINO failed on {self.target_device}: {e}")

        elif self.engine_type == "llama.cpp":
            try:
                import os
                
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
            
            # Advanced Penalties
            presence_penalty = self.model_info.get("presence_penalty", 0.0)
            frequency_penalty = self.model_info.get("frequency_penalty", 0.0)
            repeat_penalty = self.model_info.get("repeat_penalty", 1.1)
            logit_bias = self.model_info.get("logit_bias", None)
            raw_text = ""
            
            log.info(f"Generating via {self.engine_type.upper()} on {self.target_device}...")

            try:
                if self.engine_type == "openvino":
                    # --- OPENVINO GENERATION LOGIC ---
                    full_prompt = f"<|system|>{self.system_prompt}\n{context_block}<|end|>\n<|user|>{user_message}<|end|>\n<|assistant|>"
                    
                    def ov_streamer(subword: str) -> bool:
                        nonlocal raw_text
                        raw_text += subword
                        if stream_callback: stream_callback(subword)
                        return False 

                    config = {
                        "max_new_tokens": max_tokens,
                        "do_sample": temp > 0,
                        "temperature": temp,
                        "top_p": top_p,
                        "top_k": top_k,
                        "presence_penalty": presence_penalty,
                        "frequency_penalty": frequency_penalty,
                        "repetition_penalty": repeat_penalty # OpenVINO uses competition naming
                    }
                    self.pipe.generate(
                        full_prompt, 
                        streamer=ov_streamer,
                        **config
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
        facts = []
        schedule_updates = []
        
        # FIND ALL JSON BLOCKS (even those possibly truncated)
        # We look for the last valid-looking block as it's the most likely intended output
        json_blocks = re.findall(r'```json\n(.*?)(?:\n```|$)', raw_text, re.DOTALL | re.IGNORECASE)

        for block in json_blocks:
            try:
                block = block.strip()
                if not block: continue
                
                # RECOVERY: If block is missing closing braces due to truncation
                open_braces = block.count('{')
                close_braces = block.count('}')
                if open_braces > close_braces:
                    block += '}' * (open_braces - close_braces)
                
                # RECOVERY: If block is missing closing brackets due to truncation
                open_brackets = block.count('[')
                close_brackets = block.count(']')
                if open_brackets > close_brackets:
                    block += ']' * (open_brackets - close_brackets)
                    # And maybe one more brace if it was inside a list
                    if block.count('{') > block.count('}'):
                         block += '}'

                data = json.loads(block)
                intents = data.get("intents", data.get("commands", []))
                
                for intent in intents:
                    if intent.get("type") == "schedule":
                        intent["action"] = intent.get("action", "add_flexible")
                        intent["activity"] = str(intent.get("activity", "Undefined Operation"))
                        
                        try:
                            intent["duration"] = int(intent.get("duration", 60))
                        except (ValueError, TypeError):
                            intent["duration"] = 60
                            
                        try:
                            intent["priority"] = int(intent.get("priority", 5))
                        except (ValueError, TypeError):
                            intent["priority"] = 5
                            
                        schedule_updates.append(intent)
                    elif intent.get("type") == "memory":
                        facts.append(intent)
            except json.JSONDecodeError:
                # Attempt one last "brute force" extraction of the last object if it's messy
                try:
                    last_brace = block.rfind('}')
                    if last_brace != -1:
                        data = json.loads(block[:last_brace+1])
                        # Reuse the logic if successful
                        continue 
                except:
                    log.warning("AI hallucinated invalid JSON structure. Block ignored.")

        clean_text = re.sub(r'```json\n.*?\n```', '', raw_text, flags=re.DOTALL | re.IGNORECASE)
        clean_text = re.sub(r'<thought>.*?</thought>', '', clean_text, flags=re.DOTALL | re.IGNORECASE)
        clean_lines = [line.strip() for line in clean_text.split('\n') if line.strip()]
        return "<br>".join(clean_lines), facts, schedule_updates

    def get_device_info(self) -> dict:
        return {
            "model": self.model_name,
            "device": self.device_used,
        }
