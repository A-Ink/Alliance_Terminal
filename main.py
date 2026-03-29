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
import logging
from pathlib import Path

# Force stdout to UTF-8 for Windows cp1252 terminals
import io
if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'buffer'):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Ensure project root is on path
SCRIPT_DIR = Path(__file__).parent
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


def main():
    print("\n=== ALLIANCE TERMINAL V3 ===", flush=True)
    print("Initializing backends on main thread (NPU requirement)...\n", flush=True)

    # ── Phase 1: Backend init on main thread ──────────────────────────────────
    ai, memory, logic, boot_log = _init_backends()
    print(flush=True)

    # ── Phase 2: Qt Application ──────────────────────────────────────────────
    from PyQt6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    app.setApplicationName("Alliance Terminal Version 3")
    app.setOrganizationName("N7")

    from ui.theme import load_fonts, global_stylesheet
    load_fonts()
    app.setStyleSheet(global_stylesheet())

    # ── Phase 3: Main window (receives pre-loaded backends) ──────────────────
    from ui.window import AllianceTerminal
    window = AllianceTerminal(ai, memory, logic, boot_log=boot_log)
    window.show()

    log.info("Alliance Terminal Version 3 launched.")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
