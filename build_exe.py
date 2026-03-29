import os
import subprocess
import sys
from pathlib import Path

# Increase recursion limit for deep transformers/pydantic hierarchies
sys.setrecursionlimit(5000)

def build():
    print("=== ALLIANCE TERMINAL V3 — FACTORY OVERRIDE (Build Script) ===")
    
    # Ensure pyinstaller is installed
    try:
        import PyInstaller
    except ImportError:
        print("[!] PyInstaller not found. Installing...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    # Base command: using module runner for maximum reliability
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name=AllianceTerminalV3",
        "--onedir",
        "--windowed",
        "--clean",
        "--noconfirm",
        "--noupx",  # Disable UPX to prevent binary corruption with AI libs
        # Main entry
        "main.py",
        # Data files (Source;Dest)
        "--add-data=prompts.yaml;.",
        "--add-data=config.json;.",
        "--add-data=README.md;.",
        "--add-data=ui/fonts;ui/fonts",
        # Collect only the essential AI runtime libraries
        "--collect-all=openvino_genai",
        "--collect-all=openvino_tokenizers",
        "--collect-all=chromadb",
        "--collect-all=pydantic",
        "--collect-all=yaml",
        # HARD EXCLUSIONS: These are huge and not needed for the NPU/ChromaDB runtime.
        # Removing them prevents the recursion stack overflow (0xC0000409).
        "--exclude-module=transformers",
        "--exclude-module=torch",
        "--exclude-module=onnx",
        "--exclude-module=notebook",
        "--exclude-module=tensorboard",
        # Hidden imports
        "--hidden-import=PyQt6.QtCore",
        "--hidden-import=PyQt6.QtGui",
        "--hidden-import=PyQt6.QtWidgets",
        "--hidden-import=openvino_genai",
        "--hidden-import=openvino_tokenizers",
    ]

    print(f"[*] Running build command: {' '.join(cmd)}")
    try:
        subprocess.check_call(cmd)
        
        # POST-BUILD LOGIC: The 'model' folder MUST NOT be bundled for size reasons,
        # but we encourage the user to keep it in the same root as the dist folder.
        print("\n" + "="*60)
        print("[SUCCESS] Build complete. Mission artifacts located in 'dist/AllianceTerminalV3'.")
        print("[DEPLOYMENT TIP]")
        print("  1. Copy the 'model/' folder to 'dist/AllianceTerminalV3/model/' before shipping.")
        print("  2. ZIP the 'dist/AllianceTerminalV3' folder.")
        print("="*60)
    except subprocess.CalledProcessError as e:
        print(f"\n[ERROR] Build failed with exit code {e.returncode}")

if __name__ == "__main__":
    build()
