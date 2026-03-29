"""
Alliance Terminal — Panel Layouts
Left (tabbed Codex/Tasks/Reminders), Center (Chat), Right (Mood + Schedule).
Fonts: Orbitron headings · Montserrat body · Consolas mono.
"""

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                              QPushButton, QScrollArea, QFrame, QTextEdit,
                              QSizePolicy, QStackedWidget, QTextBrowser)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QPainter, QColor, QFont, QPainterPath, QPen, QCursor

from .theme import *
from .widgets import (ClockWidget, SparklineWidget, EnergyBar, SciPanel,
                       SectionHeader, DiagRow, TabStrip,
                       TaskItem, ReminderItem, ScheduleEntry, ChatBubble,
                       ThinkingDots)


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _scroll_area(widget: QWidget) -> QScrollArea:
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setWidget(widget)
    sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    sa.setFrameShape(QFrame.Shape.NoFrame)
    sa.setStyleSheet("background: transparent; border: none;")
    widget.setStyleSheet("background: transparent;")
    return sa

def _empty_state(text: str, icon: str = "◈") -> QLabel:
    lbl = QLabel(f"{icon}  {text}")
    lbl.setFont(font_body(11))
    lbl.setStyleSheet(f"color: {C_TEXT_DIM}; padding: 24px 12px;")
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl.setWordWrap(True)
    return lbl


# ══════════════════════════════════════════════════════════════════════════════
# LEFT PANEL — Clock · Diagnostics · Tabs (Codex / Tasks / Reminders)
# ══════════════════════════════════════════════════════════════════════════════

class LeftPanel(QWidget):
    task_complete    = pyqtSignal(str)
    task_delete      = pyqtSignal(str)
    reminder_dismiss = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(220)
        self.setMaximumWidth(310)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # ── Clock ──
        self._clock = ClockWidget()
        root.addWidget(self._clock)

        # ── Diagnostics card ──
        diag_panel = SciPanel()
        dp_lay = QVBoxLayout(diag_panel)
        dp_lay.setContentsMargins(10, 8, 10, 8)
        dp_lay.setSpacing(2)

        diag_hdr = QLabel("SYS DIAGNOSTICS")
        diag_hdr.setFont(font_orbitron(7, QFont.Weight.Bold))
        diag_hdr.setStyleSheet(f"color: {C_CYAN_DIM}; letter-spacing: 2px; background: transparent;")
        dp_lay.addWidget(diag_hdr)

        self._row_sys  = DiagRow("SYS RAM")
        self._row_app  = DiagRow("APP RAM")
        self._row_model = DiagRow("MODEL")
        self._row_dev   = DiagRow("DEVICE")
        dp_lay.addWidget(self._row_sys)
        dp_lay.addWidget(self._row_app)
        dp_lay.addWidget(self._row_model)
        dp_lay.addWidget(self._row_dev)

        self._spark = SparklineWidget()
        dp_lay.addWidget(self._spark)

        root.addWidget(diag_panel)

        # ── Tab strip ──
        self._tabs = TabStrip(["CODEX", "TASKS", "REMINDERS"])
        self._tabs.tab_changed.connect(self._on_tab)
        root.addWidget(self._tabs)

        # ── Stacked pages ──
        self._stack = QStackedWidget()
        self._stack.setStyleSheet("background: transparent;")

        # Page 0: Codex
        self._codex_container = QWidget()
        self._codex_container.setStyleSheet("background: transparent;")
        self._codex_lay = QVBoxLayout(self._codex_container)
        self._codex_lay.setContentsMargins(0, 4, 0, 0)
        self._codex_lay.setSpacing(4)

        self._codex_browser = QTextBrowser()
        self._codex_browser.setOpenExternalLinks(False)
        self._codex_browser.setFont(font_body(10))
        self._codex_browser.setStyleSheet(f"""
            QTextBrowser {{
                background: transparent;
                color: {C_TEXT};
                border: none;
                padding: 4px;
                font-family: Montserrat, "Segoe UI";
                font-size: 11px;
            }}
        """)
        self._codex_lay.addWidget(self._codex_browser)
        self._stack.addWidget(self._codex_container)

        # Page 1: Tasks
        self._tasks_page = QWidget()
        self._tasks_page.setStyleSheet("background: transparent;")
        self._tasks_lay = QVBoxLayout(self._tasks_page)
        self._tasks_lay.setContentsMargins(0, 4, 0, 0)
        self._tasks_lay.setSpacing(2)
        self._tasks_lay.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._stack.addWidget(_scroll_area(self._tasks_page))

        # Page 2: Reminders
        self._rems_page = QWidget()
        self._rems_page.setStyleSheet("background: transparent;")
        self._rems_lay = QVBoxLayout(self._rems_page)
        self._rems_lay.setContentsMargins(0, 4, 0, 0)
        self._rems_lay.setSpacing(2)
        self._rems_lay.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._stack.addWidget(_scroll_area(self._rems_page))

        root.addWidget(self._stack, 1)

    def _on_tab(self, idx: int):
        # Stack index: 0=codex, 1=tasks(inside scroll), 2=rems(inside scroll)
        self._stack.setCurrentIndex(idx)

    def switch_to_tab(self, name: str):
        mapping = {"CODEX": 0, "TASKS": 1, "REMINDERS": 2}
        idx = mapping.get(name.upper(), 0)
        self._tabs.set_active(idx)

    # ── Diagnostics updates ──

    def update_diagnostics(self, stats: dict):
        sys_pct = stats.get("system_percent", 0)
        col_s   = C_GREEN if sys_pct < 60 else C_GOLD if sys_pct < 85 else C_RED
        self._row_sys.set_value(f"{sys_pct:.1f}%", col_s)
        self._row_app.set_value(f"{stats.get('app_mb', 0):.0f} MB  ({stats.get('app_percent', 0):.1f}%)")
        self._spark.push(sys_pct)

    def update_device_info(self, info: dict):
        self._row_model.set_value(info.get("model", "–"))
        self._row_dev.set_value(info.get("device", "–"))

    # ── Data updates ──

    def update_codex(self, html_or_text: str):
        if "<" in html_or_text and ">" in html_or_text:
            self._codex_browser.setHtml(html_or_text)
        else:
            self._codex_browser.setPlainText(html_or_text)

    def update_tasks(self, tasks: list):
        # Clear old widgets
        while self._tasks_lay.count():
            item = self._tasks_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not tasks:
            self._tasks_lay.addWidget(_empty_state("No active missions", "◈"))
            return

        for t in tasks:
            item = TaskItem(t)
            item.completed_signal.connect(self.task_complete)
            item.deleted_signal.connect(self.task_delete)
            self._tasks_lay.addWidget(item)

        self._tasks_lay.addStretch()

    def update_reminders(self, reminders: list):
        while self._rems_lay.count():
            item = self._rems_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not reminders:
            self._rems_lay.addWidget(_empty_state("No active reminders", "⏱"))
            return

        for r in reminders:
            item = ReminderItem(r)
            item.dismissed_signal.connect(self.reminder_dismiss)
            self._rems_lay.addWidget(item)

        self._rems_lay.addStretch()


# ══════════════════════════════════════════════════════════════════════════════
# CHAT PANEL — Command input, streaming response, history
# ══════════════════════════════════════════════════════════════════════════════

class ChatPanel(QWidget):
    message_sent = pyqtSignal(str)

    COMMANDER = "◈  COMMANDER SHEPARD"
    NORMANDY  = "◈  NORMANDY"
    SYSTEM    = "●  SYSTEM"
    REMINDER  = "⚑  ALERT"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # Chat title bar
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        tl = QLabel("TACTICAL COMMS")
        tl.setFont(font_orbitron(10, QFont.Weight.Bold))
        tl.setStyleSheet(f"color: {C_CYAN}; letter-spacing: 4px; background: transparent;")
        title_row.addWidget(tl)
        title_row.addStretch()
        self._online_badge = QLabel("● ONLINE")
        self._online_badge.setFont(font_orbitron(7))
        self._online_badge.setStyleSheet(f"color: {C_GREEN}; letter-spacing: 2px; background: transparent;")
        title_row.addWidget(self._online_badge)
        root.addLayout(title_row)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"background: {C_BORDER}; max-height: 1px;")
        root.addWidget(sep)

        # ── Scroll area for chat bubbles ──
        self._chat_inner = QWidget()
        self._chat_inner.setStyleSheet("background: transparent;")
        self._chat_inner_lay = QVBoxLayout(self._chat_inner)
        self._chat_inner_lay.setContentsMargins(0, 0, 0, 0)
        self._chat_inner_lay.setSpacing(0)
        self._chat_inner_lay.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._chat_scroll = QScrollArea()
        self._chat_scroll.setWidgetResizable(True)
        self._chat_scroll.setWidget(self._chat_inner)
        self._chat_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._chat_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._chat_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._chat_scroll.setStyleSheet("background: transparent; border: none;")
        root.addWidget(self._chat_scroll, 1)

        # ── Thinking indicator area ──
        self._thinking: ThinkingDots | None = None

        # ── Input area ──
        input_panel = SciPanel()
        ip_lay = QVBoxLayout(input_panel)
        ip_lay.setContentsMargins(10, 8, 10, 8)
        ip_lay.setSpacing(6)

        input_hdr = QHBoxLayout()
        cmd_lbl = QLabel("◈  COMMAND INPUT")
        cmd_lbl.setFont(font_orbitron(8, QFont.Weight.Bold))
        cmd_lbl.setStyleSheet(f"color: {C_CYAN_DIM}; letter-spacing: 2px; background: transparent;")
        input_hdr.addWidget(cmd_lbl)
        input_hdr.addStretch()
        hint = QLabel("/forget [fact]  to purge")
        hint.setFont(font_body(9))
        hint.setStyleSheet(f"color: {C_TEXT_DIM}; background: transparent;")
        input_hdr.addWidget(hint)
        ip_lay.addLayout(input_hdr)

        self._input = QTextEdit()
        self._input.setFont(font_body(12))
        self._input.setPlaceholderText("Transmit command to Normandy...")
        self._input.setFixedHeight(72)
        self._input.setStyleSheet(f"""
            QTextEdit {{
                background-color: rgba(0,8,20,0.85);
                color: {C_TEXT_BRIGHT};
                border: 1px solid {C_BORDER};
                border-radius: 6px;
                padding: 8px;
                font-family: Montserrat;
                font-size: 12px;
            }}
            QTextEdit:focus {{
                border: 1px solid {C_BORDER_LIT};
            }}
        """)
        self._input.installEventFilter(self)
        ip_lay.addWidget(self._input)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch()

        self._clear_btn = QPushButton("CLEAR LOG")
        self._clear_btn.setFont(font_orbitron(8))
        self._clear_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._clear_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C_TEXT_DIM};
                border: 1px solid {C_BORDER}; border-radius: 4px;
                padding: 4px 12px;
            }}
            QPushButton:hover {{ color: {C_TEXT}; border-color: {C_BORDER_LIT}; }}
        """)
        self._clear_btn.clicked.connect(self._clear_log)
        btn_row.addWidget(self._clear_btn)

        self._send_btn = QPushButton("TRANSMIT  ◈")
        self._send_btn.setFont(font_orbitron(9, QFont.Weight.Bold))
        self._send_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._send_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(0,229,255,0.13); color: {C_CYAN};
                border: 1px solid {C_BORDER_LIT}; border-radius: 4px;
                padding: 6px 18px; letter-spacing: 2px;
            }}
            QPushButton:hover {{
                background: rgba(0,229,255,0.22); color: {C_TEXT_BRIGHT};
                border-color: {C_CYAN};
            }}
            QPushButton:pressed {{ background: rgba(0,229,255,0.32); }}
            QPushButton:disabled {{ color: {C_TEXT_DIM}; border-color: {C_BORDER}; background: transparent; }}
        """)
        self._send_btn.clicked.connect(self._send)
        btn_row.addWidget(self._send_btn)

        ip_lay.addLayout(btn_row)
        root.addWidget(input_panel)

        # ── Variables ──
        self._current_bubble: ChatBubble | None = None
        self._busy = False

    # ── Event filter for Ctrl+Enter ──
    def eventFilter(self, obj, event):
        from PyQt6.QtCore import QEvent
        from PyQt6.QtGui import QKeyEvent
        if obj is self._input and event.type() == QEvent.Type.KeyPress:
            ke = event  # type: QKeyEvent
            if ke.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if ke.modifiers() & Qt.KeyboardModifier.ControlModifier:
                    self._send()
                    return True
        return super().eventFilter(obj, event)

    def _send(self):
        text = self._input.toPlainText().strip()
        if not text or self._busy:
            return
        self._input.clear()
        self._add_bubble(self.COMMANDER, text, "commander")
        self.message_sent.emit(text)

    def _add_bubble(self, speaker: str, text: str, msg_type: str = "normandy") -> ChatBubble:
        bubble = ChatBubble(speaker, text, msg_type)
        self._chat_inner_lay.addWidget(bubble)
        bubble.play_entry()
        QTimer.singleShot(250, self._scroll_bottom)
        return bubble

    def _scroll_bottom(self):
        sb = self._chat_scroll.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _clear_log(self):
        while self._chat_inner_lay.count():
            item = self._chat_inner_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    # ── AI lifecycle ──

    def start_generation(self, user_text: str):
        self._busy = True
        self._send_btn.setEnabled(False)
        self._online_badge.setText("● PROCESSING")
        self._online_badge.setStyleSheet(f"color: {C_GOLD}; letter-spacing: 2px; background: transparent;")

        self._thinking = ThinkingDots()
        self._chat_inner_lay.addWidget(self._thinking)
        QTimer.singleShot(100, self._scroll_bottom)

        # Streaming bubble (starts empty)
        self._current_bubble = ChatBubble(self.NORMANDY, "", "normandy")
        self._chat_inner_lay.addWidget(self._current_bubble)
        self._current_bubble.play_entry()

    def on_token(self, token: str):
        if self._current_bubble:
            self._current_bubble.append_html(token)
            self._scroll_bottom()

    def on_generation_done(self, result: dict):
        if self._thinking:
            self._thinking.stop()
            self._thinking.deleteLater()
            self._thinking = None

        response = result.get("response", result) if isinstance(result, dict) else str(result)
        if self._current_bubble:
            self._current_bubble.set_html(response)
        else:
            self._add_bubble(self.NORMANDY, response, "normandy")

        self._current_bubble = None
        self._busy = False
        self._send_btn.setEnabled(True)
        self._online_badge.setText("● ONLINE")
        self._online_badge.setStyleSheet(f"color: {C_GREEN}; letter-spacing: 2px; background: transparent;")
        QTimer.singleShot(200, self._scroll_bottom)

    def on_generation_error(self, error: str):
        if self._thinking:
            self._thinking.stop()
            self._thinking.deleteLater()
            self._thinking = None
        if self._current_bubble:
            self._current_bubble.set_html(f"<span style='color:{C_RED}'>Error: {error}</span>")
            self._current_bubble = None
        self._busy = False
        self._send_btn.setEnabled(True)
        self._online_badge.setText("● ONLINE")
        self._online_badge.setStyleSheet(f"color: {C_GREEN}; letter-spacing: 2px; background: transparent;")

    def append_reminder(self, html: str):
        self._add_bubble(self.REMINDER, html, "reminder")


# ══════════════════════════════════════════════════════════════════════════════
# RIGHT PANEL — Mood/Energy + Schedule
# ══════════════════════════════════════════════════════════════════════════════

class RightPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(220)
        self.setMaximumWidth(310)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # ── Mood card ──
        self._mood_card = SciPanel()
        mc_lay = QVBoxLayout(self._mood_card)
        mc_lay.setContentsMargins(12, 10, 12, 10)
        mc_lay.setSpacing(4)

        mood_hdr = QHBoxLayout()
        mh_lbl = QLabel("OPERATIVE STATUS")
        mh_lbl.setFont(font_orbitron(7, QFont.Weight.Bold))
        mh_lbl.setStyleSheet(f"color: {C_CYAN_DIM}; letter-spacing: 2px; background: transparent;")
        mood_hdr.addWidget(mh_lbl)
        mood_hdr.addStretch()
        mc_lay.addLayout(mood_hdr)

        self._mood_label = QLabel("NOMINAL")
        self._mood_label.setFont(font_orbitron(16, QFont.Weight.Bold))
        self._mood_label.setStyleSheet(f"color: {C_CYAN}; letter-spacing: 5px; background: transparent;")
        mc_lay.addWidget(self._mood_label)

        self._mood_desc = QLabel("Systems stable.")
        self._mood_desc.setFont(font_body(10))
        self._mood_desc.setStyleSheet(f"color: {C_TEXT_DIM}; background: transparent;")
        self._mood_desc.setWordWrap(True)
        mc_lay.addWidget(self._mood_desc)

        mc_lay.addSpacing(5)

        bar_row = QHBoxLayout()
        el = QLabel("ENERGY")
        el.setFont(font_orbitron(7))
        el.setStyleSheet(f"color: {C_TEXT_DIM}; letter-spacing: 2px; background: transparent;")
        bar_row.addWidget(el)
        self._energy_val = QLabel("100%")
        self._energy_val.setFont(font_orbitron(9, QFont.Weight.Bold))
        self._energy_val.setStyleSheet(f"color: {C_GREEN}; background: transparent;")
        bar_row.addWidget(self._energy_val)
        bar_row.addStretch()
        mc_lay.addLayout(bar_row)

        self._ebar = EnergyBar()
        mc_lay.addWidget(self._ebar)
        root.addWidget(self._mood_card)

        # ── Schedule card ──
        sched_card = SciPanel()
        sc_lay = QVBoxLayout(sched_card)
        sc_lay.setContentsMargins(8, 8, 8, 8)
        sc_lay.setSpacing(4)

        sched_hdr = QLabel("OPERATIONS TIMELINE")
        sched_hdr.setFont(font_orbitron(7, QFont.Weight.Bold))
        sched_hdr.setStyleSheet(f"color: {C_CYAN_DIM}; letter-spacing: 2px; background: transparent;")
        sc_lay.addWidget(sched_hdr)

        self._sched_inner = QWidget()
        self._sched_inner.setStyleSheet("background: transparent;")
        self._sched_lay = QVBoxLayout(self._sched_inner)
        self._sched_lay.setContentsMargins(0, 0, 0, 0)
        self._sched_lay.setSpacing(0)
        self._sched_lay.setAlignment(Qt.AlignmentFlag.AlignTop)

        sched_scroll = QScrollArea()
        sched_scroll.setWidgetResizable(True)
        sched_scroll.setWidget(self._sched_inner)
        sched_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sched_scroll.setFrameShape(QFrame.Shape.NoFrame)
        sched_scroll.setStyleSheet("background: transparent; border: none;")
        sc_lay.addWidget(sched_scroll, 1)

        root.addWidget(sched_card, 1)

    def update_mood(self, data: dict):
        col   = data.get("color", C_CYAN)
        label = data.get("label", "NOMINAL")
        desc  = data.get("description", "")
        score = data.get("score", 100)

        self._mood_label.setText(label)
        self._mood_label.setStyleSheet(f"color: {col}; letter-spacing: 5px; background: transparent;")
        self._mood_desc.setText(desc)
        self._ebar.set_value(score)

        e_col = C_GREEN if score > 60 else C_GOLD if score > 30 else C_RED
        self._energy_val.setText(f"{score}%")
        self._energy_val.setStyleSheet(f"color: {e_col}; background: transparent;")

    def update_schedule(self, tasks: list):
        from datetime import datetime
        now_str = datetime.now().strftime("%H:%M")

        while self._sched_lay.count():
            item = self._sched_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not tasks:
            self._sched_lay.addWidget(_empty_state("Schedule clear", "◈"))
            return

        for t in tasks:
            start = t.get("start_time", "00:00")
            is_active = (start <= now_str) and not t.get("completed", False)
            # Only mark as active if within the block duration
            dur = t.get("duration", 60)
            try:
                sh, sm = map(int, start.split(":"))
                nh, nm = map(int, now_str.split(":"))
                start_m = sh * 60 + sm
                now_m   = nh * 60 + nm
                is_active = start_m <= now_m < start_m + dur
            except Exception:
                pass

            entry = ScheduleEntry(t, is_active=is_active)
            self._sched_lay.addWidget(entry)

        self._sched_lay.addStretch()
