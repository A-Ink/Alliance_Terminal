"""
Alliance Terminal — Boot Overlay Widget
Full-screen sci-fi boot sequence with large fonts and fade-out animation.
"""

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                              QScrollArea, QFrame, QSizePolicy)
from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QPainter, QColor, QFont, QLinearGradient, QPainterPath
from .theme import *


class BootOverlay(QWidget):
    """Full-screen boot overlay — large centered layout, staggered log lines, fade-out."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setStyleSheet("background: transparent;")

        root = QVBoxLayout(self)
        root.setContentsMargins(60, 50, 60, 50)
        root.setSpacing(0)
        root.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # ── Centre column ──
        center = QWidget()
        center.setMaximumWidth(680)
        center.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        c_lay = QVBoxLayout(center)
        c_lay.setContentsMargins(0, 0, 0, 0)
        c_lay.setSpacing(10)

        # Main title
        title = QLabel("ALLIANCE TERMINAL")
        title.setFont(font_orbitron(32, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C_CYAN}; letter-spacing: 10px; background: transparent;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        c_lay.addWidget(title)

        # Subtitle
        sub = QLabel("SYSTEMS BOOT  ·  v2.2")
        sub.setFont(font_orbitron(10))
        sub.setStyleSheet(f"color: {C_TEXT_DIM}; letter-spacing: 4px; background: transparent;")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        c_lay.addWidget(sub)

        c_lay.addSpacing(20)

        # Divider
        div = QFrame()
        div.setFrameShape(QFrame.Shape.HLine)
        div.setStyleSheet(f"background: {C_BORDER_LIT}; min-height: 1px; max-height: 1px;")
        c_lay.addWidget(div)

        c_lay.addSpacing(20)

        # Log scroll
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFixedHeight(260)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("background: transparent; border: none;")

        self._log_container = QWidget()
        self._log_container.setStyleSheet("background: transparent;")
        self._log_layout = QVBoxLayout(self._log_container)
        self._log_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._log_layout.setSpacing(4)
        self._log_layout.setContentsMargins(0, 0, 0, 0)
        self._scroll.setWidget(self._log_container)
        c_lay.addWidget(self._scroll)

        c_lay.addSpacing(20)

        # Spinner dots row
        dots_row = QWidget()
        dr_lay = QHBoxLayout(dots_row)
        dr_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dr_lay.setSpacing(12)
        dots_row.setStyleSheet("background: transparent;")
        self._dots = []
        for _ in range(5):
            d = QLabel("◈")
            d.setFont(font_orbitron(14))
            d.setStyleSheet(f"color: {C_TEXT_DIM}; background: transparent;")
            dr_lay.addWidget(d)
            self._dots.append(d)
        c_lay.addWidget(dots_row)

        root.addWidget(center)
        self.layout().setAlignment(center, Qt.AlignmentFlag.AlignHCenter)

        # ── Spinner timer ──
        self._phase = 0
        self._spin_t = QTimer(self)
        self._spin_t.timeout.connect(self._spin)
        self._spin_t.start(200)

        # ── Fade-out animation on windowOpacity ──
        self._fade = QPropertyAnimation(self, b"windowOpacity")
        self._fade.setDuration(800)
        self._fade.setStartValue(1.0)
        self._fade.setEndValue(0.0)
        self._fade.setEasingCurve(QEasingCurve.Type.InQuad)
        self._fade.finished.connect(self.hide)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        r = 10  # Match main window radius
        path = QPainterPath()
        path.addRoundedRect(0, 0, self.width(), self.height(), r, r)
        
        # Fill background
        p.fillPath(path, BG)
        
        # Subtle horizontal scan lines (clipped to path)
        p.setClipPath(path)
        p.setPen(QColor(0, 180, 255, 5))
        for y in range(0, self.height(), 3):
            p.drawLine(0, y, self.width(), y)
            
        # Vignette gradient (darker edges)
        grad = QLinearGradient(0, 0, 0, self.height())
        grad.setColorAt(0.0, QColor(0, 0, 0, 80))
        grad.setColorAt(0.4, QColor(0, 0, 0, 0))
        grad.setColorAt(0.6, QColor(0, 0, 0, 0))
        grad.setColorAt(1.0, QColor(0, 0, 0, 80))
        p.fillPath(path, grad)
        
        p.end()

    def append_line(self, text: str, kind: str = "info"):
        colours = {
            "ok":    C_GREEN,
            "warn":  C_GOLD,
            "error": C_RED,
            "info":  C_TEXT,
        }
        col = colours.get(kind, C_TEXT)

        lbl = QLabel(text)
        lbl.setFont(font_mono(10))
        lbl.setStyleSheet(f"color: {col}; background: transparent; padding: 1px 0;")
        lbl.setWordWrap(False)
        self._log_layout.addWidget(lbl)

        # Auto-scroll after slight delay so the widget has settled
        QTimer.singleShot(30, self._scroll_bottom)

    def _scroll_bottom(self):
        sb = self._scroll.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _spin(self):
        for i, d in enumerate(self._dots):
            dist = abs(i - self._phase % len(self._dots))
            dist = min(dist, len(self._dots) - dist)
            if dist == 0:
                col = C_CYAN
            elif dist == 1:
                col = C_CYAN_DIM
            else:
                col = C_TEXT_DIM
            d.setStyleSheet(f"color: {col}; background: transparent;")
        self._phase += 1

    def fade_out(self):
        self._spin_t.stop()
        self._fade.start()
