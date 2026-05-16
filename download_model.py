"""
Mass Effect Alliance OS — Model Download & Export Script
Dual-Engine variant: Exports OpenVINO or directly downloads GGUF.
"""

import json
import sys
import os
import subprocess
from pathlib import Path
from huggingface_hub import snapshot_download, hf_hub_download
from PyQt6.QtCore import QThread, pyqtSignal

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "config.json"

class ModelRequisitionWorker(QThread):
    """
    Background worker for AI core requisitioning.
    Emits progress updates (0-100) and completion/error signals.
    """
    progress = pyqtSignal(int)
    status = pyqtSignal(str)
    finished = pyqtSignal(bool, str)

    def __init__(self, model_key, parent=None):
        super().__init__(parent)
        self.model_key = model_key

    def run(self):
        try:
            with open(CONFIG_PATH, "r") as f:
                config = json.load(f)

            model_info = config["models"][self.model_key]
            target_path = SCRIPT_DIR / model_info["path"]

            self.status.emit(f"Initializing requisition of {model_info['display_name']}...")
            
            # Simple progress simulation or wrapping snapshot_download if possible
            # Note: snapshot_download doesn't have a direct 'pct' callback for everything, 
            # but we can track files or just emit 'In Progress'. 
            # For now, we'll use a simple wrapper.
            
            requisition_model_core(model_info, str(target_path), self.progress.emit)

            # Update config
            config["active_model"] = self.model_key
            with open(CONFIG_PATH, "w") as f:
                json.dump(config, f, indent=2)

            self.finished.emit(True, "Core successfully secured.")
        except Exception as e:
            self.finished.emit(False, str(e))

def requisition_model_core(model_info, target_path, progress_cb=None):
    """Programmatic core of the download logic."""
    hf_id = model_info["hf_model_id"]
    engine = model_info.get("engine", "openvino")

    if engine == "openvino":
        # Note: snapshot_download is blocking. 
        # For a better UI feel, we might want to use a custom loop, but standard hub download is safer.
        if progress_cb: progress_cb(20)
        snapshot_download(repo_id=hf_id, local_dir=target_path)
        if progress_cb: progress_cb(100)
    else:
        # Placeholder for GGUF/llama.cpp
        hf_hub_download(repo_id=hf_id, filename=model_info["hf_gguf_file"], local_dir=target_path)
        if progress_cb: progress_cb(100)

def print_header():
    print("=====================================================")
    print("     ALLIANCE TERMINAL V3 — ARMORY (Model Downloader)   ")
    print("=====================================================")

def load_config():
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)

def process_model(model_info, target_path):
    hf_id = model_info["hf_model_id"]
    engine = model_info.get("engine", "openvino")

    if engine == "llama.cpp":
        gguf_file = model_info.get("hf_gguf_file")
        print(f"[*] Engine: LLAMA.CPP | Requisitioning {gguf_file} from {hf_id}...")
        hf_hub_download(
            repo_id=hf_id, 
            filename=gguf_file, 
            local_dir=str(SCRIPT_DIR / "model"),
            local_dir_use_symlinks=False
        )
        print("\n[OK] GGUF core secured.")

    elif engine == "openvino":
        if "-ov" in hf_id.lower() or hf_id.startswith("OpenVINO/"):
            print(f"[*] Engine: OPENVINO | Pre-compiled blueprint detected. Requisitioning...")
            snapshot_download(repo_id=hf_id, local_dir=target_path)
        else:
            print(f"[*] Engine: OPENVINO | Compiling raw model to INT4 OpenVINO format...")
            optimum_cli_path = str(Path(sys.executable).parent / "optimum-cli.exe")
            cmd = [
                optimum_cli_path, "export", "openvino", 
                "--model", hf_id, 
                "--task", "text-generation-with-past",
                "--weight-format", "int4", 
                "--trust-remote-code",
                target_path
            ]
            subprocess.run(cmd, check=True)
        print("\n[OK] OpenVINO core compiled and secured.")

def main():
    print_header()
    config = load_config()
    
    models = config.get("models", {})
    model_keys = list(models.keys())
    
    print("\nAVAILABLE AI CORES:")
    for idx, key in enumerate(model_keys):
        m = models[key]
        engine = m.get('engine', 'openvino').upper()
        device = m.get('target_device', 'NPU')
        tier = "dGPU" if device == "GPU" else device

        # Check if model already exists
        model_path = SCRIPT_DIR / m.get("path", "")
        if m.get("engine") == "llama.cpp":
            exists = model_path.exists() and model_path.is_file()
        else:
            exists = model_path.exists() and model_path.is_dir() and any(model_path.iterdir())
        status = "[DOWNLOADED]" if exists else "[NOT FOUND]"

        print(f"  [{idx + 1}] {m['display_name']}")
        print(f"       Engine: {engine} | Silicon: {tier} | {status}")
        
    choice = input("\nEnter the number of the model to requisition (or 'q' to quit): ")
    if choice.lower() == 'q': return
        
    try:
        idx = int(choice) - 1
        selected_key = model_keys[idx]
        selected_model = models[selected_key]
    except (ValueError, IndexError):
        print("[ERROR] Invalid selection.")
        return

    target_path = str(SCRIPT_DIR / selected_model["path"])
    
    print("\n=====================================================")
    print(f" [PHASE 1] PROCESSING MAIN CORE: {selected_model['hf_model_id']}")
    print(f" Engine: {selected_model.get('engine', 'openvino').upper()}")
    print("=====================================================\n")
    
    try:
        # Check if the file/folder already exists
        if selected_model.get("engine") == "llama.cpp":
            # GGUF models are single files
            if os.path.exists(target_path) and os.path.isfile(target_path):
                print("[OK] GGUF Core already exists on disk. Skipping download.")
            else:
                process_model(selected_model, target_path)
        else:
            # OpenVINO models are directories
            if os.path.exists(target_path) and os.path.isdir(target_path) and os.listdir(target_path):
                print("[OK] Main Core already exists on disk. Skipping download.")
            else:
                process_model(selected_model, target_path)

        # Only set as active_model if it's an NPU model (power manager handles GPU selection)
        if selected_model.get("target_device", "NPU") != "GPU":
            config["active_model"] = selected_key
            with open(CONFIG_PATH, "w") as f:
                json.dump(config, f, indent=2)
            print(f"\n[SUCCESS] '{selected_key}' is locked in as the active NPU model.")
        else:
            # For GPU models, update gpu_model in config
            config["gpu_model"] = selected_key
            with open(CONFIG_PATH, "w") as f:
                json.dump(config, f, indent=2)
            print(f"\n[SUCCESS] '{selected_key}' is available as the dGPU model.")
            print("[INFO] This model will activate automatically when AC power is detected.")
        
    except Exception as e:
        print(f"\n[ERROR] Operation failed: {e}")

if __name__ == "__main__":
    main()