"""
Alliance Terminal Version 3 — Main Entry Point (PyQt6 Native UI)

Critical: OpenVINO NPU backend MUST be initialized on the main thread before the
Qt event loop starts. Any attempt to call ov_genai.LLMPipeline() from a QThread
causes a Windows access violation (NPU driver restriction).

Architecture:
  1. Backends init (main thread, blocking)
  2. QApplication + window creation
  3. app.exec() — event loop (pure UI from here)
"""

import sys
import os
from pathlib import Path

# ── CUDA 12 DLL Registration (MUST happen before any llama_cpp import) ──────
# The pre-compiled cu124 llama-cpp-python wheel needs cublas, cusparse, etc.
# These are installed via pip (nvidia-cublas-cu12, etc.) into site-packages/nvidia/.
# We prepend their bin dirs to PATH so Windows finds them at DLL load time.
if sys.platform == "win32":
    _nvidia_dir = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
    if _nvidia_dir.exists():
        _cuda_paths = []
        for _pkg in _nvidia_dir.iterdir():
            _bin = _pkg / "bin"
            if _bin.is_dir():
                _cuda_paths.append(str(_bin))
        if _cuda_paths:
            os.environ["PATH"] = os.pathsep.join(_cuda_paths) + os.pathsep + os.environ.get("PATH", "")

import logging
import json

# Note: PyQt6 and UI imports are intentionally moved inside main() 
# to ensure DLL isolation for the NPU backend.

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# Ensure project root is on path for normal runs
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("normandy.main")


def _init_backends():
    """
    Initialize all heavy backends ON THE MAIN THREAD before Qt's event loop.
    Returns (ai, memory, logic, boot_log) where boot_log is a list of (text, kind) tuples.
    """
    from ai_backend import AIBackend
    from memory_manager import MemoryManager
    from logic_engine import LogicEngine
    from datetime import date

    boot_log = []

    def record(text, kind="info"):
        safe = text.encode("utf-8", errors="replace").decode("utf-8")
        print(f"  [{kind.upper():5s}] {safe}", flush=True)
        boot_log.append((text, kind))

    record("[BOOT] Alliance Terminal v3.0 -- Boot Sequence Initiated", "info")
    record("[SYS ] Native PyQt6 renderer .............. ONLINE", "ok")

    # ── AI backend ──
    record("[AI  ] Constructing AI backend...", "info")
    ai = AIBackend()

    record("[AI  ] Loading inference pipeline (main thread, NPU-safe)...", "info")
    try:
        ai.initialize()   # Must be main thread for NPU driver
        record(f"[AI  ] Model: {ai.model_name}", "ok")
        record(f"[AI  ] Device: {ai.device_used} ............... ACTIVE", "ok")
    except Exception as e:
        record(f"[AI  ] Pipeline failed: {e}", "warn")
        record("[AI  ] Offline mode -- chat disabled.", "warn")

    # ── Memory ──
    record("[MEM ] Initializing memory core...", "info")
    memory = MemoryManager()
    try:
        memory.initialize()
        count = 0
        try:
            count = memory.collection.count() if memory.collection else 0
        except Exception:
            pass
        record(f"[MEM ] Memory core ............... ONLINE ({count} facts)", "ok")
    except Exception as e:
        record(f"[MEM ] Memory init failed: {e}", "warn")

    # ── Logic ──
    logic = LogicEngine()
    today_str = date.today().isoformat()
    override_count = len(logic.schedule_db.get(today_str, []))
    record("[LOGIC] Zero-wake logic engine ........... ONLINE", "ok")
    if override_count > 0:
        record(f"[LOGIC] Loaded {override_count} schedule entries", "info")

    record("[DIAG] System diagnostics ............... ONLINE", "ok")
    record("[REM ] Proactive reminder system ........ ARMED", "ok")
    record("[BOOT] All systems initialized. Welcome aboard.", "ok")

    return ai, memory, logic, boot_log


class AppBooter:
    """Manages the staggered boot sequence and core requisitioning."""
    def __init__(self, boot_overlay):
        self.boot = boot_overlay
        from ai_backend import AIBackend
        self.ai = AIBackend()
        self.memory = None
        self.logic = None
        self.worker = None

    def start(self):
        """Phase 1: Verify AI Core."""
        if not self.ai.is_core_available():
            self.boot.show_core_selection(self.ai.available_models, recommended_key="qwen-2.5-7b")
            self.boot.core_selected.connect(self._start_requisition)
            self.boot.requisition_cancelled.connect(self._proceed_offline)
        else:
            self._finish_boot()

    def _start_requisition(self, model_key):
        """Phase 1b: Requisition selected core."""
        self.worker = ModelRequisitionWorker(model_key)
        self.worker.progress.connect(lambda p: self.boot.set_requisition_progress(p, f"Securing AI Core: {model_key}..."))
        self.worker.status.connect(lambda s: self.boot.append_line(f"[SYS] {s}"))
        self.worker.finished.connect(self._on_requisition_finished)
        self.worker.start()

    def _on_requisition_finished(self, success, msg):
        if success:
            self.boot.append_line("[OK] AI Core requisition successful.", "ok")
            self._finish_boot()
        else:
            self.boot.append_line(f"[ERR] Requisition failed: {msg}", "error")
            self._proceed_offline()

    def _proceed_offline(self):
        self.boot.append_line("[WARN] AI Core unavailable. Operating in offline mode.", "warn")
        self._finish_boot()

    def _finish_boot(self):
        """Phase 2: Final Backend Init (Main Thread)."""
        # Ensure we are on main thread for NPU init
        try:
            from ai_backend import AIBackend
            from memory_manager import MemoryManager
            from logic_engine import LogicEngine
            from datetime import date

            self.boot.append_line("[SYS] Initializing tactical overlays...")
            
            # Re-init AI backend if needed
            self.ai.initialize()
            self.boot.append_line(f"[OK] AI Core initialized ({self.ai.device_used})", "ok")

            self.memory = MemoryManager()
            self.memory.initialize()
            self.boot.append_line("[OK] Memory core synchronized", "ok")

            self.logic = LogicEngine()
            self.boot.append_line("[OK] Logic engine online", "ok")
            
            # Transition to main window
            self.boot.append_line("[OK] Boot sequence complete. Welcome back, Commander.", "ok")
            QTimer.singleShot(1000, self._launch_terminal)
            
        except Exception as e:
            self.boot.append_line(f"[ERR] Critical init failure: {e}", "error")
            QTimer.singleShot(3000, QCoreApplication.quit)

    def _launch_terminal(self):
        from ui.window import AllianceTerminal
        self.window = AllianceTerminal(self.ai, self.memory, self.logic, boot_log=[])
        self.boot.fade_out()
        self.window.show()


def main():
    print("\n=== ALLIANCE TERMINAL V3 ALPHA ===", flush=True)

    # --- PHASE 0: POWER STATE CHECK ---
    # Determine which AI tier to initialize based on AC/battery state.
    # This MUST happen before DLL loading to avoid conflicts.
    from power_manager import is_on_ac_power
    import json

    on_ac = is_on_ac_power()
    power_str = "AC POWER" if on_ac else "BATTERY"
    print(f"  [POWER] Detected: {power_str}", flush=True)

    # Read config to determine which model to use per power state
    config_path = SCRIPT_DIR / "config.json"
    try:
        with open(config_path, "r") as f:
            config = json.load(f)
    except Exception as e:
        print(f"  [ERROR] Failed to read config.json: {e}", flush=True)
        config = {}

    if on_ac:
        gpu_model_key = config.get("gpu_model", "")
        gpu_model_info = config.get("models", {}).get(gpu_model_key, {})
        gpu_model_path = SCRIPT_DIR / gpu_model_info.get("path", "")

        if gpu_model_key and gpu_model_info and gpu_model_path.exists():
            # dGPU model is available — use it
            config["active_model"] = gpu_model_key
            print(f"  [POWER] AC detected → Loading dGPU model: {gpu_model_key}", flush=True)
        else:
            # dGPU model not downloaded yet — fall back to NPU
            npu_key = config.get("npu_model", config.get("active_model", ""))
            config["active_model"] = npu_key
            if gpu_model_key:
                print(f"  [POWER] AC detected but dGPU model '{gpu_model_key}' not found on disk.", flush=True)
                print(f"  [POWER] Run 'python download_model.py' to download it. Falling back to NPU.", flush=True)
            else:
                print(f"  [POWER] No gpu_model configured. Using NPU.", flush=True)
    else:
        npu_key = config.get("npu_model", config.get("active_model", ""))
        config["active_model"] = npu_key
        print(f"  [POWER] Battery detected → Loading NPU model: {npu_key}", flush=True)

    # Write the active_model back so AIBackend picks it up
    try:
        with open(config_path, "w") as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        print(f"  [WARN] Could not write active_model to config.json: {e}", flush=True)

    # --- PHASE 1: HARDWARE INIT (STRICT DLL ISOLATION) ---
    # We initialize the AI core BEFORE any PyQt6 libraries are loaded.
    ai, memory, logic, boot_log = _init_backends()

    # --- PHASE 2: UI INIT ---
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import QTimer, Qt
    from ui.theme import load_fonts, global_stylesheet
    from ui.window import AllianceTerminal
    from power_manager import PowerMonitor, PipelineOrchestrator
    
    app = QApplication(sys.argv)
    app.setApplicationName("Alliance Terminal Version 3")
    app.setOrganizationName("N7")

    load_fonts()
    app.setStyleSheet(global_stylesheet())

    # --- PHASE 3: POWER MONITOR & PIPELINE ORCHESTRATOR ---
    power_monitor = PowerMonitor()
    orchestrator = PipelineOrchestrator(ai, config, logic_engine=logic)

    # Set initial tier based on what we actually loaded
    if on_ac and ai.engine_type == "llama.cpp":
        orchestrator._active_tier = "gpu"
    else:
        orchestrator._active_tier = "npu"

    # Wire power state changes to the orchestrator
    power_monitor.power_changed.connect(orchestrator.handle_power_change)

    # Create main window with pre-initialized backends + orchestrator
    window = AllianceTerminal(ai, memory, logic, boot_log=boot_log,
                               power_monitor=power_monitor,
                               orchestrator=orchestrator)
    window.show()

    # Start power monitoring after the window is visible
    power_monitor.start()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()

