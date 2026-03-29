"""
Alliance Terminal — Main Application Window
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

import logging
log = logging.getLogger("normandy.window")

RESIZE_MARGIN = 8   # px from window edge for resize detection


class TitleBar(QWidget):
    """Custom drag-able title bar with window controls."""

    close_clicked    = pyqtSignal()
    minimize_clicked = pyqtSignal()
    toggle_left      = pyqtSignal()
    toggle_right     = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(36)
        self._drag_pos: QPoint | None = None

        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 0, 8, 0)
        lay.setSpacing(6)

        # Left toggle
        self._btn_left = self._ctrl_btn("◀", "Toggle Intel Panel")
        self._btn_left.clicked.connect(self.toggle_left)
        lay.addWidget(self._btn_left)

        # Title
        self._title = QLabel("◈  ALLIANCE TERMINAL  ◈")
        self._title.setFont(font_orbitron(9, QFont.Weight.Bold))
        self._title.setStyleSheet(f"color:{C_CYAN}; letter-spacing:5px; background:transparent;")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._title, 1)

        # Status badge
        self._status = QLabel("BOOTING")
        self._status.setFont(font_orbitron(7))
        self._status.setStyleSheet(f"color:{C_GOLD}; letter-spacing:2px; background:transparent;")
        lay.addWidget(self._status)

        # Right toggle
        self._btn_right = self._ctrl_btn("▶", "Toggle Operations")
        self._btn_right.clicked.connect(self.toggle_right)
        lay.addWidget(self._btn_right)

        # Window controls
        for label, signal in [("─", self.minimize_clicked), ("✕", self.close_clicked)]:
            btn = QPushButton(label)
            btn.setFixedSize(28, 24)
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            close_style = f"QPushButton:hover{{background:rgba(255,50,50,0.35); color:white;}}" \
                          if label == "✕" else \
                          f"QPushButton:hover{{background:rgba(0,229,255,0.15);}}"
            btn.setStyleSheet(f"""
                QPushButton{{background:transparent; color:{C_TEXT}; border:none;
                             font-family:Montserrat; font-size:13px;}}
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
            QPushButton{{background:transparent; color:{C_TEXT_DIM}; border:none; font-family:Orbitron; font-size:7px;}}
            QPushButton:hover{{color:{C_CYAN}; background:rgba(0,229,255,0.10);}}
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
        # Background is already drawn by parent (AllianceTerminal)
        # We only draw the separator line at the bottom
        p.setPen(QColor(0, 180, 200, 120))
        p.drawLine(0, self.height() - 1, self.width(), self.height() - 1)
        p.end()

    def set_status(self, text: str, color: str = C_GREEN):
        self._status.setText(text)
        self._status.setStyleSheet(f"color:{color}; letter-spacing:2px; background:transparent;")


class AllianceTerminal(QWidget):
    """
    Main application window — frameless, resizable, 3-panel layout.
    """

    def __init__(self, ai, memory, logic, boot_log: list | None = None):
        super().__init__()
        self._ai       = ai
        self._memory   = memory
        self._logic    = logic
        self._boot_log = boot_log or []

        self._left_visible  = True
        self._right_visible = True
        self._ai_worker: AiWorker | None = None

        # ── Window flags (frameless + resizable via manual hit-test) ──
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMinimumSize(900, 580)
        self.resize(1280, 780)
        self.setWindowTitle("ALLIANCE TERMINAL")

        # Mouse tracking for resize cursors
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
        self._splitter.setChildrenCollapsible(False)

        self._left_panel  = LeftPanel()
        self._chat_panel  = ChatPanel()
        self._right_panel = RightPanel()

        self._splitter.addWidget(self._left_panel)
        self._splitter.addWidget(self._chat_panel)
        self._splitter.addWidget(self._right_panel)
        self._splitter.setSizes([260, 700, 280])
        self._splitter.setStretchFactor(1, 1)

        content_lay.addWidget(self._splitter)
        self._stack.addWidget(content)

        # Show boot overlay first
        self._stack.setCurrentIndex(0)

        # ── Wire panel signals ──
        self._left_panel.task_complete.connect(self._on_task_complete)
        self._left_panel.task_delete.connect(self._on_task_delete)
        self._left_panel.reminder_dismiss.connect(self._on_reminder_dismiss)
        self._chat_panel.message_sent.connect(self._on_message_sent)

        # ── Start boot sequence ──
        QTimer.singleShot(200, self._start_boot)

    # ── Paint (window border) ──────────────────────────────────────────────────

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = 10  # window corner radius
        path = QPainterPath()
        path.addRoundedRect(0, 0, self.width(), self.height(), r, r)
        p.fillPath(path, BG)
        # Border
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
        self._titlebar.set_status("BOOT COMPLETE", C_GREEN)
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
        # Device info (one-shot)
        try:
            info = self._ai.get_device_info()
            self._left_panel.update_device_info(info)
        except Exception:
            pass

    def _start_reminders(self):
        self._rem_worker = ReminderWorker(self._logic)
        self._rem_worker.reminder_ready.connect(self._chat_panel.append_reminder)
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
            return  # busy

        # Handle /forget command
        if text.strip().lower().startswith("/forget"):
            target = text.strip()[7:].strip()
            if self._memory.delete_fact(target):
                self._chat_panel.on_generation_done({"response": f"[DATA PURGED] {target}"})
            else:
                self._chat_panel.on_generation_done({"response": f"[FILE NOT FOUND] {target}"})
            return

        self._chat_panel.start_generation(text)
        self._titlebar.set_status("PROCESSING", C_GOLD)

        self._ai_worker = AiWorker(self._ai, self._memory, self._logic, text)
        self._ai_worker.token_streamed.connect(self._chat_panel.on_token)
        self._ai_worker.generation_done.connect(self._on_generation_done)
        self._ai_worker.generation_error.connect(self._chat_panel.on_generation_error)
        self._ai_worker.start()

    def _on_generation_done(self, result: dict):
        self._chat_panel.on_generation_done(result)
        self._titlebar.set_status("ONLINE", C_GREEN)

        # Refresh whichever panels need updating
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
            self._refresh_schedule()     # auto-scheduled tasks appear here too
        if result.get("reminders_updated"):
            self._refresh_reminders()
            self._left_panel.switch_to_tab("REMINDERS")

    # ── Panel signals ─────────────────────────────────────────────────────────

    def _on_task_complete(self, task_id: str):
        self._logic.mark_task_complete(task_id)
        self._refresh_tasks()
        self._refresh_schedule()

    def _on_task_delete(self, task_id: str):
        self._logic.delete_task(task_id)
        self._refresh_tasks()

    def _on_reminder_dismiss(self, reminder_id: str):
        self._logic.dismiss_reminder(reminder_id)
        self._refresh_reminders()

    # ── Panel toggles ─────────────────────────────────────────────────────────

    def _toggle_left(self):
        self._left_visible = not self._left_visible
        self._left_panel.setVisible(self._left_visible)

    def _toggle_right(self):
        self._right_visible = not self._right_visible
        self._right_panel.setVisible(self._right_visible)

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

        # Update cursor
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
