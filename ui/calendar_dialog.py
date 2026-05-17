"""
Alliance Terminal Version 3 — Calendar Week View Dialog
7-column popup showing 2 past + today + 4 future days.
Each column: wake-to-sleep timeline with meals, events, and free-time gaps.
"""

from datetime import date, timedelta, datetime

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QWidget, QFrame, QSizePolicy
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPainter, QPainterPath, QColor, QFont

from .theme import (
    C_BG, C_PANEL, C_BORDER, C_BORDER_LIT, C_CYAN, C_CYAN_DIM,
    C_GREEN, C_GOLD, C_RED, C_TEXT, C_TEXT_BRIGHT, C_TEXT_DIM,
    S_MONTSERRAT, S_ORBITRON,
    font_orbitron, font_body, font_mono,
)


# ── Event type color mapping ─────────────────────────────────────────────────

_TYPE_COLORS = {
    "biological": "#607d8b",
    "wake":       "#607d8b",
    "sleep":      "#455a64",
    "meal":       "#f2a900",
    "task":       "#00e5ff",
    "free":       "transparent",
}

_TYPE_TEXT_COLORS = {
    "biological": "#90a4ae",
    "wake":       "#90a4ae",
    "sleep":      "#78909c",
    "meal":       "#f2a900",
    "task":       "#c8ddf0",
    "free":       "#37474f",
}

DAY_NAMES = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]


# ══════════════════════════════════════════════════════════════════════════════
# COMPACT EVENT ROW — one entry inside a day column
# ══════════════════════════════════════════════════════════════════════════════

class _CalendarEventRow(QWidget):
    """Single compact event row for the calendar column."""

    def __init__(self, event: dict, is_now: bool = False, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        ev_type  = event.get("type", "task")
        is_free  = ev_type == "free"
        projected = event.get("projected", False)

        # Determine colors
        accent = _TYPE_COLORS.get(ev_type, "#00e5ff")
        text_c = _TYPE_TEXT_COLORS.get(ev_type, C_TEXT)

        if is_now:
            accent = C_GREEN
            text_c = C_GREEN

        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        lay.setSpacing(4)

        # Time
        time_str = event.get("start_time", "--:--")
        t_lbl = QLabel(time_str)
        t_lbl.setFont(font_mono(8))
        t_lbl.setFixedWidth(34)
        t_col = C_GREEN if is_now else (C_TEXT_DIM if is_free else text_c)
        t_lbl.setStyleSheet(f"color: {t_col}; background: transparent;")
        lay.addWidget(t_lbl)

        # Activity name
        activity = event.get("activity", "")
        if is_free:
            activity = "---"
        elif projected:
            activity = f"{activity}*"

        a_lbl = QLabel(activity)
        a_lbl.setFont(font_body(9))
        a_lbl.setWordWrap(False)
        a_col = "#37474f" if is_free else text_c
        style = f"color: {a_col}; background: transparent;"
        if projected and not is_free:
            style = f"color: {a_col}; background: transparent; font-style: italic;"
        a_lbl.setStyleSheet(style)
        a_lbl.setToolTip(activity)
        lay.addWidget(a_lbl, 1)

        # Duration
        dur = event.get("duration", 0)
        if dur and not is_free:
            d_lbl = QLabel(f"{dur}m")
            d_lbl.setFont(font_mono(7))
            d_lbl.setStyleSheet(f"color: {C_TEXT_DIM}; background: transparent;")
            lay.addWidget(d_lbl)

        # Row background
        if is_now:
            bg = "rgba(0,255,136,0.08)"
        elif is_free:
            bg = "transparent"
        else:
            bg = "transparent"

        border_c = accent if not is_free else "transparent"
        self.setStyleSheet(
            f"background: {bg}; "
            f"border-left: 2px solid {border_c}; "
            f"border-bottom: 1px solid rgba(255,255,255,0.03);"
        )

        height = 22 if is_free else 26
        self.setFixedHeight(height)


# ══════════════════════════════════════════════════════════════════════════════
# DAY COLUMN — one vertical day in the calendar
# ══════════════════════════════════════════════════════════════════════════════

class _DayColumn(QWidget):
    """One day column: header + scrollable event list."""

    def __init__(self, day: date, events: list, is_today: bool = False,
                 is_past: bool = False, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Column header ──
        day_name = DAY_NAMES[day.weekday()]
        day_num  = day.day
        month_s  = day.strftime("%b").upper()

        hdr = QWidget()
        hdr.setFixedHeight(42)
        hdr_lay = QVBoxLayout(hdr)
        hdr_lay.setContentsMargins(4, 4, 4, 2)
        hdr_lay.setSpacing(0)

        # Day name
        name_lbl = QLabel(day_name)
        name_lbl.setFont(font_orbitron(8, QFont.Weight.Bold))
        name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Date
        date_lbl = QLabel(f"{day_num} {month_s}")
        date_lbl.setFont(font_body(8))
        date_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        if is_today:
            name_lbl.setStyleSheet(f"color: {C_CYAN}; background: transparent; letter-spacing: 2px;")
            date_lbl.setStyleSheet(f"color: {C_TEXT_BRIGHT}; background: transparent;")
            hdr.setStyleSheet(f"background: rgba(0,229,255,0.08); border-bottom: 2px solid {C_CYAN};")
        elif is_past:
            name_lbl.setStyleSheet(f"color: {C_TEXT_DIM}; background: transparent; letter-spacing: 2px;")
            date_lbl.setStyleSheet(f"color: #37474f; background: transparent;")
            hdr.setStyleSheet(f"background: transparent; border-bottom: 1px solid {C_BORDER};")
        else:
            name_lbl.setStyleSheet(f"color: {C_TEXT}; background: transparent; letter-spacing: 2px;")
            date_lbl.setStyleSheet(f"color: {C_TEXT_DIM}; background: transparent;")
            hdr.setStyleSheet(f"background: transparent; border-bottom: 1px solid {C_BORDER};")

        hdr_lay.addWidget(name_lbl)
        hdr_lay.addWidget(date_lbl)
        root.addWidget(hdr)

        # ── Event list ──
        scroll_inner = QWidget()
        scroll_inner.setStyleSheet("background: transparent;")
        ev_lay = QVBoxLayout(scroll_inner)
        ev_lay.setContentsMargins(0, 2, 0, 2)
        ev_lay.setSpacing(1)
        ev_lay.setAlignment(Qt.AlignmentFlag.AlignTop)

        now_str = datetime.now().strftime("%H:%M")

        if not events:
            empty = QLabel("No events")
            empty.setFont(font_body(9))
            empty.setStyleSheet(f"color: #37474f; background: transparent; padding: 12px;")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            ev_lay.addWidget(empty)
        else:
            for ev in events:
                # Determine if this is the currently active event
                is_now = False
                if is_today and ev.get("type") != "free":
                    try:
                        start = ev.get("start_time", "00:00")
                        sh, sm = map(int, start.split(":"))
                        start_m = sh * 60 + sm
                        nh, nm = map(int, now_str.split(":"))
                        now_m = nh * 60 + nm
                        dur = ev.get("duration", 0)
                        is_now = start_m <= now_m < start_m + dur
                    except (ValueError, AttributeError):
                        pass

                row = _CalendarEventRow(ev, is_now=is_now)
                ev_lay.addWidget(row)

        ev_lay.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(scroll_inner)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(
            "background: transparent; border: none; "
            "QScrollBar:vertical { width: 4px; background: transparent; } "
            "QScrollBar::handle:vertical { background: #1a3a50; border-radius: 2px; }"
        )
        root.addWidget(scroll, 1)

        # Column border
        opacity = "0.05" if is_past else "0.08"
        self.setStyleSheet(
            f"border-right: 1px solid rgba(255,255,255,{opacity}); background: transparent;"
        )


# ══════════════════════════════════════════════════════════════════════════════
# CALENDAR DIALOG — Main popup
# ══════════════════════════════════════════════════════════════════════════════

class CalendarDialog(QDialog):
    """7-day week view calendar popup."""

    def __init__(self, week_data: dict, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Dialog |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setModal(True)
        self.setMinimumSize(880, 520)
        self.resize(920, 560)

        self._drag_pos = None

        # Root layout
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Inner container
        self._inner = QWidget()
        self._inner.setObjectName("calDialogInner")
        self._inner.setStyleSheet(f"""
            QWidget#calDialogInner {{
                background: {C_BG};
                border: 1px solid {C_BORDER_LIT};
                border-radius: 10px;
            }}
            QLabel {{ background: transparent; }}
        """)
        root.addWidget(self._inner)

        inner_lay = QVBoxLayout(self._inner)
        inner_lay.setContentsMargins(0, 0, 0, 0)
        inner_lay.setSpacing(0)

        # ── Title bar ──
        tbar = QWidget()
        tbar.setFixedHeight(44)
        tbar.setStyleSheet(
            f"background: {C_PANEL}; border-radius: 10px; "
            f"border-bottom-left-radius: 0; border-bottom-right-radius: 0;"
        )
        tb_lay = QHBoxLayout(tbar)
        tb_lay.setContentsMargins(16, 0, 8, 0)

        t_lbl = QLabel("WEEK VIEW")
        t_lbl.setFont(font_orbitron(10, QFont.Weight.Bold))
        t_lbl.setStyleSheet(f"color: {C_CYAN}; letter-spacing: 4px; background: transparent;")
        tb_lay.addWidget(t_lbl, 1)

        # Legend
        legend = QLabel("* = projected")
        legend.setFont(font_body(8))
        legend.setStyleSheet(f"color: {C_TEXT_DIM}; background: transparent; padding-right: 12px;")
        tb_lay.addWidget(legend)

        close_btn = QPushButton("X")
        close_btn.setFixedSize(32, 28)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C_TEXT}; border: none;
                font-family: 'Segoe UI Symbol', {S_MONTSERRAT};
                font-size: 12px; font-weight: bold;
            }}
            QPushButton:hover {{
                color: white; background: rgba(255,50,50,0.35);
                border-radius: 4px;
            }}
        """)
        close_btn.clicked.connect(self.close)
        tb_lay.addWidget(close_btn)
        inner_lay.addWidget(tbar)

        # Divider
        div = QFrame()
        div.setFrameShape(QFrame.Shape.HLine)
        div.setStyleSheet(f"background: {C_BORDER_LIT}; max-height: 1px;")
        inner_lay.addWidget(div)

        # ── 7-column calendar ──
        cal_container = QWidget()
        cal_container.setStyleSheet("background: transparent;")
        cal_lay = QHBoxLayout(cal_container)
        cal_lay.setContentsMargins(8, 8, 8, 8)
        cal_lay.setSpacing(0)

        today = date.today()
        sorted_dates = sorted(week_data.keys())

        for d_str in sorted_dates:
            d = date.fromisoformat(d_str)
            events = week_data[d_str]
            is_today = (d == today)
            is_past  = (d < today)

            col = _DayColumn(d, events, is_today=is_today, is_past=is_past)
            cal_lay.addWidget(col, 1)

        inner_lay.addWidget(cal_container, 1)

    # ── Drag support ──
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_pos and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None

    # ── Rounded background paint ──
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(0.0, 0.0, float(self.width()), float(self.height()), 10.0, 10.0)
        p.fillPath(path, QColor(C_BG))
        p.setPen(QColor(C_BORDER_LIT))
        p.drawPath(path)
        p.end()
