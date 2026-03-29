"""
Alliance Terminal Version 3 — Custom Painted Widgets
All performance-sensitive widgets implemented with QPainter + property-driven animations.
Fonts: Orbitron (headings/badges) · Montserrat (body) · Consolas (mono/numbers).
"""

import time
from typing import List, Optional

from PyQt6.QtWidgets import (QWidget, QLabel, QHBoxLayout, QVBoxLayout,
                              QPushButton, QFrame, QSizePolicy, QStackedWidget,
                              QScrollArea)
from PyQt6.QtCore import (Qt, QTimer, QPropertyAnimation, QEasingCurve,
                           QRect, pyqtSignal)
from PyQt6.QtGui import (QPainter, QPen, QBrush, QColor, QFont,
                          QLinearGradient, QPainterPath, QCursor)

from .theme import *


# ══════════════════════════════════════════════════════════════════════════════
# CLOCK WIDGET
# ══════════════════════════════════════════════════════════════════════════════

class ClockWidget(QWidget):
    """Digital clock — large Orbitron digits, repaints once per second."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(80)
        self.setMaximumHeight(90)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update)
        self._timer.start(1000)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        w, h = self.width(), self.height()

        # Time
        now      = time.localtime()
        time_str = time.strftime("%H:%M:%S", now)
        date_str = time.strftime("%A  %d %b %Y", now).upper()

        tf = font_orbitron(30, QFont.Weight.Bold)
        p.setFont(tf)
        p.setPen(CYAN)
        p.drawText(QRect(0, 0, w, 56), Qt.AlignmentFlag.AlignCenter, time_str)

        df = font_body(10)
        p.setFont(df)
        p.setPen(TEXT_DIM)
        p.drawText(QRect(0, 56, w, 24), Qt.AlignmentFlag.AlignCenter, date_str)

        p.end()


# ══════════════════════════════════════════════════════════════════════════════
# RAM SPARKLINE
# ══════════════════════════════════════════════════════════════════════════════

class SparklineWidget(QWidget):
    """Live RAM history sparkline — repaints only when data changes."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(40)
        self._history: List[float] = []
        self._max_pts = 30

    def push(self, value: float):
        self._history.append(max(0.0, min(100.0, value)))
        if len(self._history) > self._max_pts:
            self._history.pop(0)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        # Background
        p.fillRect(0, 0, w, h, QColor(4, 12, 24))

        hist = self._history
        if len(hist) < 2:
            p.end()
            return

        step = w / max(self._max_pts - 1, 1)
        pts  = []
        for i, v in enumerate(hist):
            x = i * step
            y = h - (v / 100.0) * (h - 4) - 2
            pts.append((x, y))

        # Fill area
        path = QPainterPath()
        path.moveTo(pts[0][0], h)
        for x, y in pts:
            path.lineTo(x, y)
        path.lineTo(pts[-1][0], h)
        path.closeSubpath()
        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0, QColor(0, 229, 255, 55))
        grad.setColorAt(1, QColor(0, 229, 255, 0))
        p.fillPath(path, grad)

        # Line
        p.setPen(QPen(CYAN, 1.5))
        path2 = QPainterPath()
        path2.moveTo(*pts[0])
        for x, y in pts[1:]:
            path2.lineTo(x, y)
        p.drawPath(path2)

        # Faint grid
        p.setPen(QPen(QColor(0, 180, 255, 12), 0.5))
        for frac in (0.25, 0.5, 0.75):
            yp = int(h * frac)
            p.drawLine(0, yp, w, yp)

        p.end()


# ══════════════════════════════════════════════════════════════════════════════
# ENERGY BAR
# ══════════════════════════════════════════════════════════════════════════════

class EnergyBar(QWidget):
    """Segmented animated energy / mood bar."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(14)
        self._target  = 100
        self._current = 100.0
        self._anim_t  = QTimer(self)
        self._anim_t.timeout.connect(self._tick)

    def set_value(self, value: int):
        self._target = max(0, min(100, value))
        self._anim_t.start(16)

    def _tick(self):
        diff = self._target - self._current
        if abs(diff) < 0.5:
            self._current = float(self._target)
            self._anim_t.stop()
        else:
            self._current += diff * 0.12
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        v = self._current / 100.0

        # Track
        p.setBrush(QBrush(QColor(10, 24, 40)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(0, 0, w, h, 3, 3)

        if v > 0:
            col   = GREEN if v > 0.6 else GOLD if v > 0.3 else RED
            dim   = QColor(col.red() // 4, col.green() // 4, col.blue() // 4)
            fw    = max(6, int(w * v))
            grad  = QLinearGradient(0, 0, fw, 0)
            grad.setColorAt(0, dim)
            grad.setColorAt(1, col)
            p.setBrush(QBrush(grad))
            p.drawRoundedRect(0, 0, fw, h, 3, 3)

        # Segments
        p.setPen(QPen(QColor(2, 6, 17), 1))
        segs = 20
        for i in range(1, segs):
            x = int(w * i / segs)
            p.drawLine(x, 0, x, h)

        # Border
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(BORDER, 1))
        p.drawRoundedRect(0, 0, w - 1, h - 1, 3, 3)
        p.end()


# ══════════════════════════════════════════════════════════════════════════════
# SCI-FI PANEL FRAME  (rounded corners + corner accents)
# ══════════════════════════════════════════════════════════════════════════════

class SciPanel(QFrame):
    """QFrame with rounded corners and sci-fi corner accent glyphs."""

    RADIUS = 8

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h, r = self.width(), self.height(), self.RADIUS

        # Background
        path = QPainterPath()
        path.addRoundedRect(0, 0, w, h, r, r)
        p.fillPath(path, PANEL)

        # Border
        p.setPen(QPen(BORDER, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

        # Corner accent lines (inside the round corners)
        al = 14
        p.setPen(QPen(CYAN, 2))
        # TL
        p.drawLine(r, 1,       r + al, 1)
        p.drawLine(1, r,       1,      r + al)
        # TR
        p.drawLine(w - r - al, 1,   w - r, 1)
        p.drawLine(w - 1, r,   w - 1, r + al)
        # BL
        p.drawLine(1, h - r,   1,     h - r - al)
        p.drawLine(r, h - 1,   r + al, h - 1)
        # BR
        p.drawLine(w - 1, h - r, w - 1, h - r - al)
        p.drawLine(w - r - al, h - 1, w - r, h - 1)

        p.end()


# ══════════════════════════════════════════════════════════════════════════════
# SECTION HEADER
# ══════════════════════════════════════════════════════════════════════════════

class SectionHeader(QLabel):
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setFont(font_orbitron(8, QFont.Weight.Bold))
        self.setStyleSheet(f"""
            QLabel {{
                color: {C_CYAN_DIM};
                letter-spacing: 3px;
                padding: 5px 0 3px 0;
                border-bottom: 1px solid {C_BORDER};
                background: transparent;
            }}
        """)


# ══════════════════════════════════════════════════════════════════════════════
# DIAGNOSTIC ROW
# ══════════════════════════════════════════════════════════════════════════════

class DiagRow(QWidget):
    def __init__(self, label: str, value_id: str = "", parent=None):
        super().__init__(parent)
        self.setMaximumHeight(22)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 1, 0, 1)
        lay.setSpacing(6)

        lbl = QLabel(label)
        lbl.setFont(font_orbitron(8))
        lbl.setStyleSheet(f"color: {C_TEXT_DIM}; letter-spacing: 2px; background: transparent;")
        lbl.setFixedWidth(62)
        lay.addWidget(lbl)

        self.value_lbl = QLabel("—")
        self.value_lbl.setFont(font_mono(10))
        self.value_lbl.setStyleSheet(f"color: {C_CYAN}; background: transparent;")
        self.value_lbl.setObjectName(value_id)
        lay.addWidget(self.value_lbl, 1)

    def set_value(self, text: str, color: str = C_CYAN):
        self.value_lbl.setText(text)
        self.value_lbl.setStyleSheet(f"color: {color}; background: transparent;")


# ══════════════════════════════════════════════════════════════════════════════
# TAB STRIP
# ══════════════════════════════════════════════════════════════════════════════

class TabStrip(QWidget):
    """Mass Effect–style tab bar — Orbitron labels, animated bottom-border indicator."""

    tab_changed = pyqtSignal(int)

    def __init__(self, tabs: List[str], parent=None):
        super().__init__(parent)
        self.setFixedHeight(36)
        self._active = 0

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._btns = []
        for i, name in enumerate(tabs):
            btn = QPushButton(f"◈  {name}")
            btn.setFont(font_orbitron(8, QFont.Weight.Bold))
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn.setCheckable(True)
            btn.setChecked(i == 0)
            btn.setFixedHeight(34)
            idx = i
            btn.clicked.connect(lambda _=False, x=idx: self._on_tab(x))
            self._btns.append(btn)
            lay.addWidget(btn)

        self._refresh()

    def _on_tab(self, idx: int):
        self._active = idx
        self.tab_changed.emit(idx)
        self._refresh()

    def _refresh(self):
        for i, btn in enumerate(self._btns):
            if i == self._active:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: rgba(0,229,255,0.10);
                        color: {C_CYAN};
                        border: none;
                        border-bottom: 2px solid {C_CYAN};
                        padding: 0 10px;
                        font-family: Orbitron;
                        font-size: 8px;
                        letter-spacing: 2px;
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: transparent;
                        color: {C_TEXT_DIM};
                        border: none;
                        border-bottom: 2px solid {C_BORDER};
                        padding: 0 10px;
                        font-family: Orbitron;
                        font-size: 8px;
                        letter-spacing: 2px;
                    }}
                    QPushButton:hover {{
                        color: {C_TEXT};
                        background: rgba(0,229,255,0.05);
                    }}
                """)

    def set_active(self, idx: int):
        self._on_tab(idx)


# ══════════════════════════════════════════════════════════════════════════════
# TASK ITEM
# ══════════════════════════════════════════════════════════════════════════════

class TaskItem(QWidget):
    completed_signal = pyqtSignal(str)
    deleted_signal   = pyqtSignal(str)

    def __init__(self, task: dict, parent=None):
        super().__init__(parent)
        self._id   = task.get("id", "")
        self._done = task.get("completed", False)
        self.setMaximumHeight(44)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(8)

        # Checkbox button
        self._chk = QPushButton("✓" if self._done else "○")
        self._chk.setFixedSize(22, 22)
        self._chk.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._chk.clicked.connect(self._on_check)
        self._update_chk_style()
        lay.addWidget(self._chk)

        # Name
        name = task.get("name", task.get("task_name", "Unknown Task"))
        self._name = QLabel(name)
        self._name.setFont(font_body(11))
        col = C_TEXT_DIM if self._done else C_TEXT_BRIGHT
        self._name.setStyleSheet(f"color: {col}; background: transparent;")
        self._name.setWordWrap(False)
        lay.addWidget(self._name, 1)

        # Priority badge
        pr = task.get("priority", 5)
        pc = priority_color(pr)
        pb = QLabel(f"P{pr}")
        pb.setFont(font_orbitron(8, QFont.Weight.Bold))
        pb.setStyleSheet(f"""
            color: {pc}; padding: 2px 5px;
            border: 1px solid {pc}; border-radius: 3px;
            background: transparent;
        """)
        pb.setFixedWidth(28)
        pb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(pb)

        # Deadline badge
        dl = task.get("deadline", "")
        if dl:
            dl_lbl = QLabel(f"⚑ {dl[:10]}")
            dl_lbl.setFont(font_mono(9))
            dl_lbl.setStyleSheet(f"color: {C_GOLD}; background: transparent; padding: 0 4px;")
            lay.addWidget(dl_lbl)

        # Delete button
        del_btn = QPushButton("✕")
        del_btn.setFixedSize(20, 20)
        del_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        del_btn.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {C_TEXT_DIM};
                           border: none; font-size: 10px; }}
            QPushButton:hover {{ color: {C_RED}; }}
        """)
        del_btn.clicked.connect(lambda: self.deleted_signal.emit(self._id))
        lay.addWidget(del_btn)

        self.setStyleSheet(f"border-bottom: 1px solid {C_BORDER};")

    def _update_chk_style(self):
        if self._done:
            self._chk.setStyleSheet(f"""
                QPushButton {{ background: transparent; color: {C_GREEN};
                               border: 1px solid {C_GREEN}; border-radius: 3px; font-size: 12px; }}
            """)
        else:
            self._chk.setStyleSheet(f"""
                QPushButton {{ background: transparent; color: {C_TEXT_DIM};
                               border: 1px solid {C_BORDER}; border-radius: 3px; font-size: 12px; }}
                QPushButton:hover {{ border-color: {C_CYAN}; color: {C_CYAN}; }}
            """)

    def _on_check(self):
        self._done = not self._done
        self._chk.setText("✓" if self._done else "○")
        self._update_chk_style()
        col = C_TEXT_DIM if self._done else C_TEXT_BRIGHT
        self._name.setStyleSheet(f"color: {col}; background: transparent;")
        if self._done:
            self.completed_signal.emit(self._id)


# ══════════════════════════════════════════════════════════════════════════════
# REMINDER ITEM
# ══════════════════════════════════════════════════════════════════════════════

class ReminderItem(QWidget):
    dismissed_signal = pyqtSignal(str)

    def __init__(self, reminder: dict, parent=None):
        super().__init__(parent)
        self._id = reminder.get("id", "")
        self.setMaximumHeight(50)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 5, 6, 5)
        lay.setSpacing(8)

        # Time badge
        at = reminder.get("remind_at", "")
        t_lbl = QLabel(at or "—:——")
        t_lbl.setFont(font_orbitron(10, QFont.Weight.Bold))
        t_lbl.setStyleSheet(f"""
            color: {C_GOLD}; border: 1px solid {C_GOLD}; border-radius: 3px;
            padding: 2px 6px; background: transparent; min-width: 44px;
        """)
        t_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(t_lbl)

        # Text
        txt = reminder.get("reminder_text", reminder.get("text", ""))
        t_body = QLabel(txt)
        t_body.setFont(font_body(11))
        t_body.setStyleSheet(f"color: {C_TEXT}; background: transparent;")
        t_body.setWordWrap(True)
        lay.addWidget(t_body, 1)

        # Dismiss button
        dis = QPushButton("✕")
        dis.setFixedSize(20, 20)
        dis.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        dis.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {C_TEXT_DIM}; border: none; font-size: 10px; }}
            QPushButton:hover {{ color: {C_GOLD}; }}
        """)
        dis.clicked.connect(lambda: self.dismissed_signal.emit(self._id))
        lay.addWidget(dis)

        self.setStyleSheet(f"border-bottom: 1px solid {C_BORDER};")


# ══════════════════════════════════════════════════════════════════════════════
# SCHEDULE ENTRY
# ══════════════════════════════════════════════════════════════════════════════

class ScheduleEntry(QWidget):
    def __init__(self, task: dict, is_active: bool = False, parent=None):
        super().__init__(parent)
        self._active = is_active
        self.setMaximumHeight(40)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 3, 6, 3)
        lay.setSpacing(8)

        # Active indicator dot
        if is_active:
            self._dot = QLabel("◈")
            self._dot.setFont(font_orbitron(9))
            self._dot.setFixedWidth(14)
            self._dot.setStyleSheet(f"color: {C_CYAN}; background: transparent;")
            lay.addWidget(self._dot)
            self._blink_t = QTimer(self)
            self._blink_t.timeout.connect(self._blink)
            self._blink_t.start(700)
            self._blink_state = True
        else:
            sp = QLabel()
            sp.setFixedWidth(14)
            sp.setStyleSheet("background: transparent;")
            lay.addWidget(sp)

        # Time
        t_type = task.get("type", "task")
        dim    = t_type in ("sleep", "biological", "meal", "wake")
        t_lbl  = QLabel(task.get("start_time", "--:--"))
        t_lbl.setFont(font_orbitron(10, QFont.Weight.Bold))
        t_lbl.setStyleSheet(f"color: {C_TEXT_DIM if dim else C_CYAN}; background: transparent; letter-spacing: 1px;")
        t_lbl.setFixedWidth(48)
        lay.addWidget(t_lbl)

        # Activity
        act = task.get("activity", "")
        if task.get("completed"):
            act = f"[DONE] {act}"
        a_lbl = QLabel(act)
        a_lbl.setFont(font_body(11))
        col = C_TEXT_BRIGHT if is_active else (C_TEXT_DIM if task.get("completed") else C_TEXT)
        a_lbl.setStyleSheet(f"color: {col}; background: transparent;")
        lay.addWidget(a_lbl, 1)

        # Duration
        dur   = task.get("duration", 0)
        pr    = task.get("priority", 5)
        d_lbl = QLabel(f"{dur}m")
        d_lbl.setFont(font_mono(9))
        d_lbl.setStyleSheet(f"color: {priority_color(pr)}; background: transparent;")
        lay.addWidget(d_lbl)

        bg = "rgba(0,229,255,0.07)" if is_active else "transparent"
        self.setStyleSheet(f"border-bottom: 1px solid {C_BORDER}; background: {bg};")

    def _blink(self):
        self._blink_state = not self._blink_state
        col = C_CYAN if self._blink_state else C_BG
        self._dot.setStyleSheet(f"color: {col}; background: transparent;")


# ══════════════════════════════════════════════════════════════════════════════
# CHAT BUBBLE
# ══════════════════════════════════════════════════════════════════════════════

class ChatBubble(QWidget):
    def __init__(self, speaker: str, text: str, msg_type: str = "normandy", parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._type = msg_type

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 6, 10, 4)
        outer.setSpacing(3)

        # Speaker label — Orbitron
        sp_col = {
            "normandy":  C_CYAN,
            "commander": C_GREEN,
            "system":    C_TEXT_DIM,
            "reminder":  C_GOLD,
            "error":     C_RED,
        }.get(msg_type, C_CYAN)

        sp = QLabel(speaker)
        sp.setFont(font_orbitron(8, QFont.Weight.Bold))
        sp.setStyleSheet(f"color: {sp_col}; letter-spacing: 2px; background: transparent;")
        outer.addWidget(sp)

        # Message — Montserrat
        self.msg_lbl = QLabel()
        self.msg_lbl.setFont(font_body(11))
        self.msg_lbl.setWordWrap(True)
        self.msg_lbl.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse |
            Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        self.msg_lbl.setOpenExternalLinks(False)
        self.msg_lbl.setTextFormat(Qt.TextFormat.RichText)
        self.msg_lbl.setText(text)
        self.msg_lbl.setStyleSheet(f"color: {C_TEXT_BRIGHT}; background: transparent;")
        outer.addWidget(self.msg_lbl)

        # Subtle separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"background: {C_BORDER}; max-height: 1px;")
        outer.addWidget(sep)

        # Entry animation
        self._anim = QPropertyAnimation(self, b"maximumHeight")
        self._anim.setDuration(200)
        self._anim.setStartValue(0)
        self._anim.setEndValue(600)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.setMaximumHeight(0)

    def play_entry(self):
        self._anim.start()

    def append_html(self, html: str):
        self.msg_lbl.setText(self.msg_lbl.text() + html)

    def set_html(self, html: str):
        self.msg_lbl.setText(html)


# ══════════════════════════════════════════════════════════════════════════════
# THINKING INDICATOR
# ══════════════════════════════════════════════════════════════════════════════

class ThinkingDots(QWidget):
    """Three sequential pulsing dots — Mass Effect tactical analysis style."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(30)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 4, 10, 4)
        lay.setSpacing(10)

        lbl = QLabel("TACTICAL ANALYSIS")
        lbl.setFont(font_orbitron(8))
        lbl.setStyleSheet(f"color: {C_TEXT_DIM}; letter-spacing: 2px; background: transparent;")
        lay.addWidget(lbl)

        self._dots = []
        for _ in range(3):
            d = QLabel("◈")
            d.setFont(font_orbitron(11))
            d.setStyleSheet(f"color: {C_TEXT_DIM}; background: transparent;")
            lay.addWidget(d)
            self._dots.append(d)

        lay.addStretch()

        self._phase = 0
        self._t = QTimer(self)
        self._t.timeout.connect(self._tick)
        self._t.start(300)

    def _tick(self):
        for i, d in enumerate(self._dots):
            d.setStyleSheet(
                f"color: {C_CYAN}; background: transparent;" if i == self._phase
                else f"color: {C_TEXT_DIM}; background: transparent;"
            )
        self._phase = (self._phase + 1) % 3

    def stop(self):
        self._t.stop()
