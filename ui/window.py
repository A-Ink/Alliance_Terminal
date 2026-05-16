"""
Alliance Terminal Version 3 — Main Application Window
Frameless, resizable PyQt6 window with custom title bar.
"""

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                              QPushButton, QSplitter, QSizePolicy, QApplication,
                              QSizeGrip, QStackedWidget)
from PyQt6.QtCore import (Qt, QPoint, QRect, QSize, QTimer, pyqtSignal,
                           QPropertyAnimation, QEasingCurve)
from PyQt6.QtGui import QPainter, QPainterPath, QColor, QCursor, QFont, QBrush

from .theme import *
from .panels import LeftPanel, ChatPanel, RightPanel
from .boot_overlay import BootOverlay
from .workers import AiWorker, DiagnosticsWorker, ReminderWorker, BootWorker
from .dialogs import ModelSwitcherDialog, DeviceToggleDialog, HelpDialog

import logging
from fast_path import try_fast_path
log = logging.getLogger("normandy.window")

RESIZE_MARGIN = 8   # px from window edge for resize detection

# Default panel widths
_W_LEFT  = 260
_W_CHAT  = 700
_W_RIGHT = 280


class TitleBar(QWidget):
    """Custom drag-able title bar with window controls and tactical action buttons."""

    close_clicked    = pyqtSignal()
    minimize_clicked = pyqtSignal()
    toggle_left      = pyqtSignal()
    toggle_right     = pyqtSignal()
    open_models      = pyqtSignal()
    open_device      = pyqtSignal()
    open_help        = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(36)
        self._drag_pos: QPoint | None = None

        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 0, 8, 0)
        lay.setSpacing(4)

        # ── Left panel toggle ──
        self._btn_left = self._ctrl_btn("◀", "Toggle Intel Panel")
        self._btn_left.clicked.connect(self.toggle_left)
        lay.addWidget(self._btn_left)

        # ── Title ──
        self._title = QLabel("◈  ALLIANCE TERMINAL V3  ◈")
        self._title.setFont(font_orbitron(9, QFont.Weight.Bold))
        self._title.setStyleSheet(f"color:{C_CYAN}; letter-spacing:5px; background:transparent;")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._title, 1)

        # ── Tactical action buttons ──
        self._btn_model  = self._action_btn("◈ MODEL",   "Switch AI Core")
        self._btn_device = self._action_btn("⬡ NPU/iGPU", "Switch Target Silicon")
        self._btn_help   = self._action_btn("? MANUAL",  "Open Tactical Manual")
        self._btn_model .clicked.connect(self.open_models)
        self._btn_device.clicked.connect(self.open_device)
        self._btn_help  .clicked.connect(self.open_help)
        for b in (self._btn_model, self._btn_device, self._btn_help):
            lay.addWidget(b)

        lay.addSpacing(6)

        # ── Right panel toggle ──
        self._btn_right = self._ctrl_btn("▶", "Toggle Operations")
        self._btn_right.clicked.connect(self.toggle_right)
        lay.addWidget(self._btn_right)

        lay.addSpacing(4)

        # ── Window controls ──
        for label, signal in [("─", self.minimize_clicked), ("✕", self.close_clicked)]:
            btn = QPushButton(label)
            btn.setFixedSize(28, 24)
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            close_style = f"QPushButton:hover{{background:rgba(255,50,50,0.35); color:white;}}" \
                          if label == "✕" else \
                          f"QPushButton:hover{{background:rgba(0,229,255,0.15);}}"
            btn.setStyleSheet(f"""
                QPushButton{{background:transparent; color:{C_TEXT}; border:none;
                             font-family:{S_MONTSERRAT}; font-size:13px;}}
                {close_style}
            """)
            btn.clicked.connect(signal)
            lay.addWidget(btn)

    def _ctrl_btn(self, text: str, tip: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setFont(font_orbitron(7))
        btn.setFixedSize(28, 24)
        btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn.setToolTip(tip)
        btn.setStyleSheet(f"""
            QPushButton{{background:transparent; color:{C_TEXT_DIM}; border:none; font-family:{S_ORBITRON}; font-size:7px;}}
            QPushButton:hover{{color:{C_CYAN}; background:rgba(0,229,255,0.10);}}
        """)
        return btn

    def _action_btn(self, text: str, tip: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setFont(font_orbitron(7, QFont.Weight.Bold))
        btn.setFixedHeight(24)
        btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn.setToolTip(tip)
        btn.setStyleSheet(f"""
            QPushButton{{
                background: transparent; color: {C_TEXT_DIM};
                border: 1px solid {C_BORDER}; border-radius: 3px;
                padding: 0 8px;
                font-family: {S_ORBITRON}; font-size: 7px; letter-spacing: 1px;
            }}
            QPushButton:hover{{
                color: {C_CYAN}; border-color: {C_BORDER_LIT};
                background: rgba(0,229,255,0.08);
            }}
        """)
        return btn

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.window().pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_pos and event.buttons() == Qt.MouseButton.LeftButton:
            self.window().move(event.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setPen(QColor(0, 180, 200, 120))
        p.drawLine(0, self.height() - 1, self.width(), self.height() - 1)
        p.end()


class AllianceTerminal(QWidget):
    """
    Main application window — frameless, resizable, 3-panel layout.
    """

    def __init__(self, ai, memory, logic, boot_log: list | None = None,
                 power_monitor=None, orchestrator=None):
        super().__init__()
        self._ai       = ai
        self._memory   = memory
        self._logic    = logic
        self._boot_log = boot_log or []
        self._power_monitor = power_monitor
        self._orchestrator  = orchestrator

        self._left_visible  = True
        self._right_visible = True
        self._ai_worker: AiWorker | None = None

        # ── Window flags ──
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMinimumSize(900, 580)
        self.resize(1280, 780)
        self.setWindowTitle("ALLIANCE TERMINAL V3")

        self.setMouseTracking(True)
        self._resize_dir: str | None = None
        self._resize_start_pos: QPoint | None = None
        self._resize_start_geo: QRect | None = None

        # ── Root layout ──
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Title bar ──
        self._titlebar = TitleBar()
        self._titlebar.close_clicked.connect(self.close)
        self._titlebar.minimize_clicked.connect(self.showMinimized)
        self._titlebar.toggle_left.connect(self._toggle_left)
        self._titlebar.toggle_right.connect(self._toggle_right)
        self._titlebar.open_models.connect(self._open_model_switcher)
        self._titlebar.open_device.connect(self._open_device_toggle)
        self._titlebar.open_help.connect(self._open_help)
        root.addWidget(self._titlebar)

        # ── Stacked widget: boot overlay | main content ──
        self._stack = QStackedWidget()
        root.addWidget(self._stack, 1)

        # Boot overlay (page 0)
        self._boot = BootOverlay()
        self._stack.addWidget(self._boot)

        # Main content (page 1)
        content = QWidget()
        content_lay = QHBoxLayout(content)
        content_lay.setContentsMargins(0, 0, 0, 0)
        content_lay.setSpacing(0)

        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setHandleWidth(2)
        self._splitter.setChildrenCollapsible(True)

        self._left_panel  = LeftPanel()
        self._chat_panel  = ChatPanel()
        self._right_panel = RightPanel()

        self._splitter.addWidget(self._left_panel)
        self._splitter.addWidget(self._chat_panel)
        self._splitter.addWidget(self._right_panel)
        self._splitter.setSizes([_W_LEFT, _W_CHAT, _W_RIGHT])
        self._splitter.setStretchFactor(1, 1)

        content_lay.addWidget(self._splitter)
        self._stack.addWidget(content)

        # Show boot overlay first
        self._stack.setCurrentIndex(0)

        # ── Wire panel signals ──
        self._left_panel.task_complete.connect(self._on_task_complete)
        self._left_panel.task_uncomplete.connect(self._on_task_uncomplete)
        self._left_panel.task_delete.connect(self._on_task_delete)
        self._left_panel.reminder_dismiss.connect(self._on_reminder_dismiss)
        self._chat_panel.message_sent.connect(self._on_message_sent)

        # ── Wire orchestrator signals for live swap feedback ──
        if self._orchestrator:
            self._orchestrator.swap_started.connect(self._on_swap_started)
            self._orchestrator.swap_progress.connect(self._on_swap_progress)
            self._orchestrator.swap_complete.connect(self._on_swap_complete)
            self._orchestrator.swap_failed.connect(self._on_swap_failed)
            self._orchestrator.deferred_ready.connect(self._on_deferred_ready)

        # Track last user message for potential deferral
        self._last_user_message: str = ""
        self._last_rag_context: str = ""

        # ── Start boot sequence ──
        QTimer.singleShot(200, self._start_boot)

    # ── Paint (window border) ──────────────────────────────────────────────────

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = 10
        path = QPainterPath()
        path.addRoundedRect(0, 0, self.width(), self.height(), r, r)
        p.fillPath(path, BG)
        p.setPen(QColor(0, 180, 200, 100))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        p.end()

    # ── Boot ──────────────────────────────────────────────────────────────────

    def _start_boot(self):
        self._boot_worker = BootWorker(self._boot_log)
        self._boot_worker.log_line.connect(self._boot.append_line)
        self._boot_worker.boot_done.connect(self._on_boot_done)
        self._boot_worker.start()

    def _on_boot_done(self):
        self._boot.fade_out()
        QTimer.singleShot(800, self._switch_to_main)

    def _switch_to_main(self):
        self._stack.setCurrentIndex(1)
        self._start_diagnostics()
        self._start_reminders()
        self._load_panel_data()

    # ── Diagnostics ───────────────────────────────────────────────────────────

    def _start_diagnostics(self):
        self._diag_worker = DiagnosticsWorker(interval_sec=5)
        self._diag_worker.stats_ready.connect(self._left_panel.update_diagnostics)
        self._diag_worker.start()
        try:
            info = self._ai.get_device_info()
            self._left_panel.update_device_info(info)
        except Exception:
            pass

    def _start_reminders(self):
        self._rem_worker = ReminderWorker(self._logic, self._memory)
        self._rem_worker.reminder_ready.connect(self._chat_panel.append_reminder)
        self._rem_worker.proactive_trigger.connect(self._trigger_proactive_ai)
        self._rem_worker.start()

    def _load_panel_data(self):
        try:
            codex = self._memory.get_dossier_html()
            self._left_panel.update_codex(codex)
        except Exception:
            pass
        self._refresh_mood()
        self._refresh_schedule()
        self._refresh_tasks()
        self._refresh_reminders()

    def _refresh_mood(self):
        try:
            data = self._logic.get_mood_dict()
            self._right_panel.update_mood(data)
        except Exception as e:
            log.warning(f"Mood refresh error: {e}")

    def _refresh_schedule(self):
        try:
            tasks = self._logic.get_schedule_tasks()
            self._right_panel.update_schedule(tasks)
        except Exception as e:
            log.warning(f"Schedule refresh error: {e}")

    def _refresh_tasks(self):
        try:
            tasks = self._logic.get_tasks_json()
            self._left_panel.update_tasks(tasks)
        except Exception as e:
            log.warning(f"Tasks refresh error: {e}")

    def _refresh_reminders(self):
        try:
            rems = self._logic.get_reminders_json()
            self._left_panel.update_reminders(rems)
        except Exception as e:
            log.warning(f"Reminders refresh error: {e}")

    # ── Message handling ──────────────────────────────────────────────────────

    def _on_message_sent(self, text: str):
        if self._ai_worker and self._ai_worker.isRunning():
            return

        # Block messages during model swap
        if self._orchestrator and self._orchestrator.is_swapping:
            self._chat_panel.on_generation_done({
                "response": "<span style='color:#f2a900'>⬡ Core transfer in progress. Please wait...</span>"
            })
            return

        if text.strip().lower().startswith("/forget"):
            target = text.strip()[7:].strip()
            if self._memory.delete_fact(target):
                self._chat_panel.on_generation_done({"response": f"[DATA PURGED] {target}"})
            else:
                self._chat_panel.on_generation_done({"response": f"[FILE NOT FOUND] {target}"})
            return

        # ── Fast-path: regex bypass (no AI call) ──
        fp_result = try_fast_path(text)
        if fp_result:
            log.info(f"[FAST-PATH] Bypassed AI for: '{text[:50]}'")
            self._chat_panel.start_generation(text)

            # Process fast-path arrays through the logic engine
            schedule_updated = False
            for cmd in fp_result.get("schedule_events", []):
                if self._logic.execute_schedule_command(cmd):
                    schedule_updated = True

            tasks_updated = False
            for t in fp_result.get("tasks", []):
                if self._logic.execute_task_command(t):
                    tasks_updated = True

            reminders_updated = False
            for r in fp_result.get("reminders", []):
                if self._logic.execute_reminder_command(r):
                    reminders_updated = True

            self._on_generation_done({
                "response": fp_result["response"],
                "schedule_updated": schedule_updated,
                "tasks_updated": tasks_updated,
                "reminders_updated": reminders_updated,
                "facts_saved": False,
                "requires_deep_thought": False,
            })
            return

        # NATIVE BYPASS: Update the sleep anchor instantly without AI lag
        if self._logic.adjust_sleep_if_awake():
            self._refresh_schedule()

        # Store for potential deferral
        self._last_user_message = text

        self._chat_panel.start_generation(text)

        self._ai_worker = AiWorker(self._ai, self._memory, self._logic, text)
        self._ai_worker.token_streamed.connect(self._chat_panel.on_token)
        self._ai_worker.generation_done.connect(self._on_generation_done)
        self._ai_worker.generation_error.connect(self._chat_panel.on_generation_error)
        self._ai_worker.start()

    def _trigger_proactive_ai(self, system_instruction: str):
        if self._ai_worker and self._ai_worker.isRunning():
            return
            
        # Add visual context for the proactive task
        self._chat_panel.start_proactive_generation()
        
        prompt = f"[SYSTEM PROACTIVE TASK: Omit conversational pleasantries if answering this. {system_instruction}]"
        self._ai_worker = AiWorker(self._ai, self._memory, self._logic, prompt)
        self._ai_worker.token_streamed.connect(self._chat_panel.on_token)
        self._ai_worker.generation_done.connect(self._on_generation_done)
        self._ai_worker.generation_error.connect(self._chat_panel.on_generation_error)
        self._ai_worker.start()

    def _on_generation_done(self, result: dict):
        # ── Deferral intercept: NPU flagged requires_deep_thought ──
        if result.get("requires_deep_thought") and self._orchestrator:
            if self._orchestrator.active_tier == "npu":
                # Enqueue for dGPU processing when AC power restores
                self._logic.enqueue_deferred(
                    self._last_user_message,
                    self._last_rag_context,
                )
                # Show the NPU's quick response + deferral notice
                npu_response = result.get("response", "")
                result["response"] = (
                    f"{npu_response}<br>"
                    f"<span style='color:#f2a900'>⬡ This request has been queued for deep analysis. "
                    f"It will be processed when the dGPU comes online.</span>"
                )

        self._chat_panel.on_generation_done(result)

        if result.get("schedule_updated"):
            self._refresh_mood()
            self._refresh_schedule()
        if result.get("facts_saved"):
            try:
                codex = self._memory.get_dossier_html()
                self._left_panel.update_codex(codex)
            except Exception:
                pass
        if result.get("tasks_updated"):
            self._refresh_tasks()
            self._refresh_schedule()
        if result.get("reminders_updated"):
            self._refresh_reminders()
            self._left_panel.switch_to_tab("REMINDERS")

    # ── Deferred queue processing ─────────────────────────────────────────────

    def _on_deferred_ready(self, deferred_items: list):
        """Process deferred prompts now that dGPU is online."""
        if not deferred_items:
            return
        count = len(deferred_items)
        self._chat_panel.on_generation_done({
            "response": f"<span style='color:#00e5ff'>⬡ Processing {count} deferred prompt(s) via dGPU...</span>"
        })
        # Process one at a time — chain via QTimer to avoid blocking
        self._deferred_queue = list(deferred_items)
        self._process_next_deferred()

    def _process_next_deferred(self):
        """Process the next item from the deferred queue."""
        if not hasattr(self, '_deferred_queue') or not self._deferred_queue:
            return
        if self._ai_worker and self._ai_worker.isRunning():
            # Retry in 2 seconds if AI is busy
            QTimer.singleShot(2000, self._process_next_deferred)
            return

        item = self._deferred_queue.pop(0)
        prompt = item.get("prompt", "")
        rag = item.get("rag_context", "")
        queued_at = item.get("queued_at", "")

        log.info(f"[DEFER] Processing deferred prompt: '{prompt[:50]}...' (queued at {queued_at})")
        self._chat_panel.start_generation(f"[Deferred] {prompt}")

        self._ai_worker = AiWorker(self._ai, self._memory, self._logic, prompt)
        self._ai_worker.token_streamed.connect(self._chat_panel.on_token)
        self._ai_worker.generation_done.connect(self._on_deferred_done)
        self._ai_worker.generation_error.connect(self._chat_panel.on_generation_error)
        self._ai_worker.start()

    def _on_deferred_done(self, result: dict):
        """Handle completion of a deferred prompt."""
        self._on_generation_done(result)
        # Process next deferred item after a brief delay
        if hasattr(self, '_deferred_queue') and self._deferred_queue:
            QTimer.singleShot(500, self._process_next_deferred)

    # ── Pipeline swap UI feedback ─────────────────────────────────────────────

    def _on_swap_started(self, status: str):
        """Called when a model swap begins. Disable input, show status."""
        log.info(f"[UI] Swap started: {status}")
        self._chat_panel.set_input_enabled(False)
        self._chat_panel.on_generation_done({
            "response": f"<span style='color:#f2a900'>⬡ {status}</span>"
        })

    def _on_swap_progress(self, status: str):
        """Called with progress updates during swap."""
        log.info(f"[UI] Swap progress: {status}")

    def _on_swap_complete(self, device_str: str):
        """Called when swap finishes successfully. Re-enable input."""
        log.info(f"[UI] Swap complete: {device_str}")
        self._chat_panel.set_input_enabled(True)
        self._chat_panel.on_generation_done({
            "response": f"<span style='color:#00ff88'>⬡ CORE TRANSFER COMPLETE</span><br>"
                        f"Active: <b>{device_str}</b>"
        })
        # Update device info in left panel
        try:
            info = self._ai.get_device_info()
            self._left_panel.update_device_info(info)
        except Exception:
            pass

    def _on_swap_failed(self, error: str):
        """Called when swap fails. Re-enable input, show error."""
        log.error(f"[UI] Swap failed: {error}")
        self._chat_panel.set_input_enabled(True)
        self._chat_panel.on_generation_done({
            "response": f"<span style='color:#ff4444'>⬡ CORE TRANSFER FAILED</span><br>"
                        f"{error}"
        })

    # ── Panel signals ─────────────────────────────────────────────────────────

    def _on_task_complete(self, task_id: str):
        self._logic.mark_task_complete(task_id)
        self._refresh_tasks()
        self._refresh_schedule()

    def _on_task_uncomplete(self, task_id: str):
        self._logic.unmark_task_complete(task_id)
        self._refresh_tasks()
        self._refresh_schedule()

    def _on_task_delete(self, task_id: str):
        self._logic.delete_task(task_id)
        self._refresh_tasks()

    def _on_reminder_dismiss(self, reminder_id: str):
        self._logic.dismiss_reminder(reminder_id)
        self._refresh_reminders()

    # ── Panel toggles (inward collapse — chat panel stays stable) ─────────────

    def _toggle_left(self):
        self._left_visible = not self._left_visible
        sizes = self._splitter.sizes()
        chat_w = sizes[1]
        if self._left_visible:
            # Restore left panel, take space back from chat
            self._splitter.setSizes([_W_LEFT, max(chat_w - _W_LEFT, 400), sizes[2]])
        else:
            # Collapse left panel inward — give its space back to itself only
            self._splitter.setSizes([0, chat_w, sizes[2]])

    def _toggle_right(self):
        self._right_visible = not self._right_visible
        sizes = self._splitter.sizes()
        chat_w = sizes[1]
        if self._right_visible:
            self._splitter.setSizes([sizes[0], max(chat_w - _W_RIGHT, 400), _W_RIGHT])
        else:
            self._splitter.setSizes([sizes[0], chat_w, 0])

    # ── Dialog openers ────────────────────────────────────────────────────────

    def _open_model_switcher(self):
        dlg = ModelSwitcherDialog(self)
        dlg.model_selected.connect(self._on_model_selected)
        dlg.exec()

    def _on_model_selected(self, key: str):
        # Inform user — full reload requires restart
        self._chat_panel.on_generation_done({
            "response": f"<span style='color:{C_GOLD}'>◈ TACTICAL CORE SWAP</span><br>"
                        f"Core <b>{key}</b> set as active in config.json. "
                        f"<span style='color:{C_TEXT_DIM}'>Restart the terminal for the new core to engage.</span>"
        })

    def _open_device_toggle(self):
        dlg = DeviceToggleDialog(self)
        dlg.device_changed.connect(self._on_device_changed)
        dlg.exec()

    def _on_device_changed(self, device: str):
        self._chat_panel.on_generation_done({
            "response": f"<span style='color:{C_GOLD}'>⬡ SILICON TARGET UPDATED</span><br>"
                        f"Device priority set to <b>{device}</b>. "
                        f"<span style='color:{C_TEXT_DIM}'>Restart the terminal for changes to take effect.</span>"
        })

    def _open_help(self):
        dlg = HelpDialog(self)
        dlg.exec()

    # ── Resize handling (frameless window) ───────────────────────────────────

    def _get_resize_dir(self, pos: QPoint) -> str | None:
        w, h, m = self.width(), self.height(), RESIZE_MARGIN
        x, y = pos.x(), pos.y()
        left   = x <= m
        right  = x >= w - m
        top    = y <= m
        bottom = y >= h - m
        if top    and left:  return "TL"
        if top    and right: return "TR"
        if bottom and left:  return "BL"
        if bottom and right: return "BR"
        if top:   return "T"
        if bottom: return "B"
        if left:  return "L"
        if right: return "R"
        return None

    _CURSORS = {
        "TL": Qt.CursorShape.SizeFDiagCursor,
        "TR": Qt.CursorShape.SizeBDiagCursor,
        "BL": Qt.CursorShape.SizeBDiagCursor,
        "BR": Qt.CursorShape.SizeFDiagCursor,
        "T":  Qt.CursorShape.SizeVerCursor,
        "B":  Qt.CursorShape.SizeVerCursor,
        "L":  Qt.CursorShape.SizeHorCursor,
        "R":  Qt.CursorShape.SizeHorCursor,
    }

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            d = self._get_resize_dir(event.position().toPoint())
            if d:
                self._resize_dir       = d
                self._resize_start_pos = event.globalPosition().toPoint()
                self._resize_start_geo = self.geometry()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()

        if self._resize_dir and event.buttons() == Qt.MouseButton.LeftButton:
            delta = event.globalPosition().toPoint() - self._resize_start_pos
            g     = QRect(self._resize_start_geo)
            dx, dy = delta.x(), delta.y()
            d = self._resize_dir

            if "R" in d: g.setRight(g.right() + dx)
            if "B" in d: g.setBottom(g.bottom() + dy)
            if "L" in d: g.setLeft(g.left() + dx)
            if "T" in d: g.setTop(g.top() + dy)

            min_w, min_h = self.minimumWidth(), self.minimumHeight()
            if g.width() >= min_w and g.height() >= min_h:
                self.setGeometry(g)
            event.accept()
            return

        d = self._get_resize_dir(pos)
        if d:
            self.setCursor(QCursor(self._CURSORS[d]))
        else:
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._resize_dir       = None
        self._resize_start_pos = None
        self._resize_start_geo = None
        super().mouseReleaseEvent(event)
