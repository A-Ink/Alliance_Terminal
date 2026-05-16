"""
Alliance Terminal — Power Management & Pipeline Orchestration
Zero-overhead AC/Battery detection via Win32 API + safe model hot-swapping.

Architecture:
  PowerMonitor   — Polls power state via ctypes, emits signal on change (debounced)
  PipelineOrchestrator — Coordinates NPU ↔ dGPU swap lifecycle with graceful abort
"""

import ctypes
import ctypes.wintypes
import gc
import logging
import threading
import time

from PyQt6.QtCore import QObject, QTimer, pyqtSignal, QThread

log = logging.getLogger("normandy.power")


# ═══════════════════════════════════════════════════════════════════════════════
#  Win32 SYSTEM_POWER_STATUS Struct
# ═══════════════════════════════════════════════════════════════════════════════

class SYSTEM_POWER_STATUS(ctypes.Structure):
    """
    Win32 SYSTEM_POWER_STATUS structure.
    https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-system_power_status
    """
    _fields_ = [
        ("ACLineStatus",        ctypes.c_byte),   # 0=Offline, 1=Online, 255=Unknown
        ("BatteryFlag",         ctypes.c_byte),
        ("BatteryLifePercent",  ctypes.c_byte),   # 0-100 or 255 if unknown
        ("SystemStatusFlag",    ctypes.c_byte),
        ("BatteryLifeTime",     ctypes.wintypes.DWORD),
        ("BatteryFullLifeTime", ctypes.wintypes.DWORD),
    ]


def _get_power_status() -> SYSTEM_POWER_STATUS:
    """Call GetSystemPowerStatus via ctypes. Returns the raw struct."""
    status = SYSTEM_POWER_STATUS()
    result = ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status))
    if not result:
        log.error("[POWER] GetSystemPowerStatus call failed (returned 0).")
    return status


def is_on_ac_power() -> bool:
    """
    Quick static check: is the system currently on AC power?
    Returns True if plugged in, False if on battery.
    Falls back to True (assume plugged in) if the API call fails.
    """
    try:
        status = _get_power_status()
        # ACLineStatus: 0 = Offline (battery), 1 = Online (AC), 255 = Unknown
        if status.ACLineStatus == 1:
            return True
        elif status.ACLineStatus == 0:
            return False
        else:
            log.warning("[POWER] ACLineStatus is Unknown (255). Assuming AC power.")
            return True
    except Exception as e:
        log.error(f"[POWER] Failed to query power status: {e}. Assuming AC power.")
        return True


# ═══════════════════════════════════════════════════════════════════════════════
#  PowerMonitor — QObject with QTimer-based polling
# ═══════════════════════════════════════════════════════════════════════════════

class PowerMonitor(QObject):
    """
    Monitors AC/Battery state changes using a QTimer (runs on Qt event loop,
    zero threading overhead). Emits `power_changed(bool)` only when state
    actually transitions, with a debounce window to prevent flapping.

    Signals:
        power_changed(bool is_ac)  — True = plugged in, False = battery
    """

    power_changed = pyqtSignal(bool)

    # Polling interval (ms) — 5 seconds is a good balance
    POLL_INTERVAL_MS = 5000
    # Debounce: require stable state for this many consecutive polls before emitting
    DEBOUNCE_COUNT = 2  # 2 polls × 5s = 10 seconds of stable state

    def __init__(self, parent=None):
        super().__init__(parent)

        # Current known state (None = not yet determined)
        self._current_ac: bool | None = None
        # Candidate state for debounce
        self._candidate_ac: bool | None = None
        self._candidate_count: int = 0

        self._timer = QTimer(self)
        self._timer.setInterval(self.POLL_INTERVAL_MS)
        self._timer.timeout.connect(self._poll)

    def start(self):
        """Begin polling. Call after QApplication is running."""
        initial = is_on_ac_power()
        self._current_ac = initial
        log.info(f"[POWER] PowerMonitor started. Initial state: {'AC' if initial else 'BATTERY'}")
        self._timer.start()

    def stop(self):
        """Stop polling."""
        self._timer.stop()
        log.info("[POWER] PowerMonitor stopped.")

    @property
    def is_ac(self) -> bool:
        """Current power state (True = AC, False = Battery)."""
        if self._current_ac is None:
            return is_on_ac_power()
        return self._current_ac

    def _poll(self):
        """Called every POLL_INTERVAL_MS by QTimer. Debounces state changes."""
        try:
            new_state = is_on_ac_power()

            if new_state == self._current_ac:
                # No change — reset debounce
                self._candidate_ac = None
                self._candidate_count = 0
                return

            # State differs from current — track candidate
            if new_state == self._candidate_ac:
                self._candidate_count += 1
            else:
                # New candidate, start counting
                self._candidate_ac = new_state
                self._candidate_count = 1

            if self._candidate_count >= self.DEBOUNCE_COUNT:
                # Stable new state confirmed
                old_state = self._current_ac
                self._current_ac = new_state
                self._candidate_ac = None
                self._candidate_count = 0

                state_str = "AC POWER" if new_state else "BATTERY"
                old_str = "AC POWER" if old_state else "BATTERY"
                log.info(f"[POWER] ⚡ State changed: {old_str} → {state_str}")
                self.power_changed.emit(new_state)
            else:
                remaining = self.DEBOUNCE_COUNT - self._candidate_count
                log.info(
                    f"[POWER] Candidate state change detected "
                    f"({'AC' if new_state else 'BATTERY'}), "
                    f"debouncing... ({remaining} more polls needed)"
                )

        except Exception as e:
            log.error(f"[POWER] Poll error: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
#  SwapWorker — Background thread for GPU model loading (non-blocking)
# ═══════════════════════════════════════════════════════════════════════════════

class _SwapWorker(QThread):
    """
    Loads a model in a background thread. Used for dGPU loading since
    llama.cpp does NOT require main-thread init (unlike NPU/OpenVINO).
    """

    swap_progress = pyqtSignal(str)
    swap_finished = pyqtSignal(bool, str)  # (success, message)

    def __init__(self, ai_backend, model_key: str, parent=None):
        super().__init__(parent)
        self._ai = ai_backend
        self._model_key = model_key

    def run(self):
        try:
            self.swap_progress.emit("Unloading current pipeline...")
            self._ai.unload()

            self.swap_progress.emit("Forcing memory reclaim...")
            gc.collect()
            time.sleep(0.5)  # Brief pause for OS memory release

            self.swap_progress.emit(f"Loading {self._model_key} pipeline...")
            self._ai.reload(self._model_key)

            if self._ai.is_loaded:
                self.swap_finished.emit(
                    True,
                    f"Pipeline loaded: {self._ai.model_name} on {self._ai.device_used}"
                )
            else:
                self.swap_finished.emit(False, "Pipeline failed to initialize (is_loaded=False)")

        except Exception as e:
            log.error(f"[SWAP] SwapWorker encountered error: {e}", exc_info=True)
            self.swap_finished.emit(False, str(e))


# ═══════════════════════════════════════════════════════════════════════════════
#  PipelineOrchestrator — Coordinates model swapping
# ═══════════════════════════════════════════════════════════════════════════════

class PipelineOrchestrator(QObject):
    """
    Coordinates safe hot-swapping between NPU and dGPU pipelines.

    Key responsibilities:
    - Swaps are sequential: unload old → gc.collect → load new
    - NPU reload is marshalled to main thread (driver requirement)
    - dGPU load runs in a background QThread
    - Generation can be aborted mid-stream via threading.Event
    - All failures fall back gracefully to NPU
    - On AC restore: drains deferred deep-thought queue through dGPU

    Signals:
        swap_started(str status_text)
        swap_progress(str status_text)
        swap_complete(str device_name)
        swap_failed(str error_text)
        deferred_ready(list[dict])  — emitted when deferred prompts are ready for dGPU
    """

    swap_started  = pyqtSignal(str)
    swap_progress = pyqtSignal(str)
    swap_complete = pyqtSignal(str)
    swap_failed   = pyqtSignal(str)
    deferred_ready = pyqtSignal(list)  # list of {prompt, rag_context, queued_at}

    def __init__(self, ai_backend, config: dict, logic_engine=None, parent=None):
        super().__init__(parent)
        self._ai = ai_backend
        self._config = config
        self._logic = logic_engine  # For deferral queue access
        self._swap_worker: _SwapWorker | None = None
        self._swapping = False

        # The abort event is shared with AIBackend for mid-generation interrupts
        self._abort_event = ai_backend._abort_event

        # Track which tier is active
        self._active_tier: str = "npu"  # "npu" or "gpu"

    @property
    def is_swapping(self) -> bool:
        return self._swapping

    @property
    def active_tier(self) -> str:
        return self._active_tier

    def abort_generation(self):
        """
        Signal the active generation to stop immediately.
        The streaming callback checks this event every token.
        """
        if self._abort_event:
            log.info("[ORCHESTRATOR] Abort signal sent to active generation.")
            self._abort_event.set()

    def swap_to_gpu(self):
        """
        Initiate swap from NPU → dGPU.
        Runs in a background thread since llama.cpp doesn't require main thread.
        """
        if self._swapping:
            log.warning("[ORCHESTRATOR] Swap already in progress. Ignoring request.")
            return

        gpu_model_key = self._config.get("gpu_model", "")
        if not gpu_model_key:
            log.error("[ORCHESTRATOR] No 'gpu_model' key defined in config.json.")
            self.swap_failed.emit("No GPU model configured")
            return

        gpu_model_info = self._config.get("models", {}).get(gpu_model_key, {})
        if not gpu_model_info:
            log.error(f"[ORCHESTRATOR] GPU model '{gpu_model_key}' not found in config models.")
            self.swap_failed.emit(f"GPU model '{gpu_model_key}' not found in config")
            return

        # Check if the model file exists on disk
        from pathlib import Path
        model_path = Path(gpu_model_info.get("path", ""))
        if not model_path.is_absolute():
            from ai_backend import SCRIPT_DIR
            model_path = SCRIPT_DIR / gpu_model_info.get("path", "")

        if not model_path.exists():
            log.error(
                f"[ORCHESTRATOR] GPU model file not found at: {model_path}. "
                f"Run 'python download_model.py' to download it."
            )
            self.swap_failed.emit(
                f"GPU model file not found. Run download_model.py to download it."
            )
            return

        log.info(f"[ORCHESTRATOR] Initiating swap: NPU → dGPU ({gpu_model_key})")
        self._swapping = True
        self.swap_started.emit(f"Core Transfer: Loading {gpu_model_info.get('display_name', gpu_model_key)}...")

        # Abort any active generation first
        self.abort_generation()
        time.sleep(0.1)  # Brief pause for abort to propagate

        # Launch background swap worker
        self._swap_worker = _SwapWorker(self._ai, gpu_model_key, parent=self)
        self._swap_worker.swap_progress.connect(self._on_swap_progress)
        self._swap_worker.swap_finished.connect(self._on_gpu_swap_finished)
        self._swap_worker.start()

    def swap_to_npu(self):
        """
        Initiate swap from dGPU → NPU.
        MUST be called from the main thread (NPU driver requirement).
        Uses QTimer.singleShot(0, ...) if called from another thread.
        """
        if self._swapping:
            log.warning("[ORCHESTRATOR] Swap already in progress. Ignoring request.")
            return

        npu_model_key = self._config.get("npu_model", "")
        if not npu_model_key:
            log.error("[ORCHESTRATOR] No 'npu_model' key defined in config.json.")
            self.swap_failed.emit("No NPU model configured")
            return

        log.info(f"[ORCHESTRATOR] Initiating swap: dGPU → NPU ({npu_model_key})")
        self._swapping = True
        self.swap_started.emit("Core Transfer: Returning to NPU...")

        # Abort any active generation first
        self.abort_generation()

        # NPU MUST be initialized on the main thread.
        # QTimer.singleShot(0, ...) ensures this runs on the Qt event loop (main thread).
        QTimer.singleShot(0, lambda: self._do_npu_swap(npu_model_key))

    def _do_npu_swap(self, npu_model_key: str):
        """
        Executes NPU reload ON THE MAIN THREAD.
        This will briefly freeze the UI (~1-2s with cache, up to 10s without).
        """
        try:
            self._on_swap_progress("Unloading dGPU pipeline...")
            self._ai.unload()

            self._on_swap_progress("Forcing memory reclaim...")
            gc.collect()

            self._on_swap_progress(f"Loading NPU pipeline ({npu_model_key})...")
            self._ai.reload(npu_model_key)

            if self._ai.is_loaded:
                self._active_tier = "npu"
                self._swapping = False
                device_str = f"{self._ai.model_name} on {self._ai.device_used}"
                log.info(f"[ORCHESTRATOR] NPU swap complete: {device_str}")
                self.swap_complete.emit(device_str)
            else:
                self._swapping = False
                log.error("[ORCHESTRATOR] NPU pipeline failed to load.")
                self.swap_failed.emit("NPU pipeline failed to initialize")

        except Exception as e:
            self._swapping = False
            log.error(f"[ORCHESTRATOR] NPU swap failed: {e}", exc_info=True)
            self.swap_failed.emit(f"NPU swap error: {e}")

    def _on_swap_progress(self, text: str):
        log.info(f"[ORCHESTRATOR] {text}")
        self.swap_progress.emit(text)

    def _on_gpu_swap_finished(self, success: bool, message: str):
        """Callback from the background SwapWorker."""
        self._swapping = False
        self._swap_worker = None

        if success:
            self._active_tier = "gpu"
            log.info(f"[ORCHESTRATOR] dGPU swap complete: {message}")
            self.swap_complete.emit(message)

            # Drain deferred queue now that dGPU is ready
            self._drain_deferred_queue()
        else:
            log.error(f"[ORCHESTRATOR] dGPU swap failed: {message}")
            log.info("[ORCHESTRATOR] Attempting NPU fallback...")
            self.swap_failed.emit(f"dGPU failed: {message}. Falling back to NPU...")
            # Attempt NPU fallback (on main thread via QTimer)
            npu_key = self._config.get("npu_model", "")
            if npu_key:
                QTimer.singleShot(100, lambda: self._do_npu_swap(npu_key))

    def _drain_deferred_queue(self):
        """Check for deferred prompts and emit them for processing."""
        if self._logic and self._logic.has_deferred_prompts:
            items = self._logic.drain_deferred_queue()
            if items:
                log.info(f"[ORCHESTRATOR] Emitting {len(items)} deferred prompt(s) for dGPU processing.")
                self.deferred_ready.emit(items)

    def handle_power_change(self, is_ac: bool):
        """
        Called by PowerMonitor.power_changed signal.
        Routes to the appropriate swap direction.
        """
        if is_ac:
            if self._active_tier == "gpu":
                log.info("[ORCHESTRATOR] Already on dGPU, no swap needed.")
                return
            log.info("[ORCHESTRATOR] AC power detected → swapping to dGPU")
            self.swap_to_gpu()
        else:
            if self._active_tier == "npu":
                log.info("[ORCHESTRATOR] Already on NPU, no swap needed.")
                return
            log.info("[ORCHESTRATOR] Battery detected → aborting dGPU, swapping to NPU")
            self.swap_to_npu()

