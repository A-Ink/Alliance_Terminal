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

SCRIPT_DIR = Path(__file__).parent
CONFIG_PATH = SCRIPT_DIR / "config.json"

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
        print(f"  [{idx + 1}] {m['display_name']} ({m.get('engine', 'openvino').upper()})")
        
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
    print("=====================================================\n")
    
    try:
        # Check if the file/folder already exists
        if not os.path.exists(target_path) or (os.path.isdir(target_path) and not os.listdir(target_path)):
            process_model(selected_model, target_path)
        else:
            print("[OK] Main Core already exists on disk. Skipping download.")

        config["active_model"] = selected_key
        with open(CONFIG_PATH, "w") as f:
            json.dump(config, f, indent=2)
            
        print(f"\n[SUCCESS] '{selected_key}' is locked in as the active model.")
        
    except Exception as e:
        print(f"\n[ERROR] Operation failed: {e}")

if __name__ == "__main__":
    main()
    