"""
Alliance Terminal Version 3 — Theme & Styling
Centralized colors, fonts, and QSS stylesheets for the sci-fi dark aesthetic.
Fonts: Orbitron (headings/labels) + Montserrat (body text).
"""

from PyQt6.QtGui import QColor, QFont, QFontDatabase
from pathlib import Path

# ── Color Palette ──────────────────────────────────────────────────────────────
C_BG          = "#020611"
C_PANEL       = "#040f1e"
C_PANEL_ALT   = "#060f20"
C_BORDER      = "#0a2a44"
C_BORDER_LIT  = "#00c8e0"
C_CYAN        = "#00e5ff"
C_CYAN_DIM    = "#006b80"
C_GREEN       = "#00ff88"
C_GREEN_DIM   = "#003322"
C_GOLD        = "#f2a900"
C_RED         = "#ff3344"
C_TEXT        = "#a0c4d8"
C_TEXT_BRIGHT = "#d8eeff"
C_TEXT_DIM    = "#2a4055"
C_CURSOR      = "#00e5ff"

# QColor objects
BG         = QColor(2, 6, 17)
PANEL      = QColor(4, 15, 30, 245)
BORDER     = QColor(10, 42, 68)
BORDER_LIT = QColor(0, 200, 224)
CYAN       = QColor(0, 229, 255)
CYAN_DIM   = QColor(0, 107, 128)
GREEN      = QColor(0, 255, 136)
GOLD       = QColor(242, 169, 0)
RED        = QColor(255, 51, 68)
TEXT       = QColor(160, 196, 216)
TEXT_BRIGHT = QColor(216, 238, 255)
TEXT_DIM   = QColor(42, 64, 85)

# ── Font paths ─────────────────────────────────────────────────────────────────
FONT_DIR = Path(__file__).parent / "fonts"

_fonts_loaded = False

def load_fonts():
    global _fonts_loaded
    if _fonts_loaded:
        return
    if FONT_DIR.exists():
        for ext in ("*.ttf", "*.otf"):
            for f in FONT_DIR.glob(ext):
                QFontDatabase.addApplicationFont(str(f))
    _fonts_loaded = True

# ── Font helpers ───────────────────────────────────────────────────────────────
def font_orbitron(size: int = 12, weight=QFont.Weight.Normal) -> QFont:
    """Orbitron — for headings, labels, badges, anything structural."""
    f = QFont("Orbitron", size)
    f.setWeight(weight)
    f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.2)
    return f

def font_body(size: int = 11) -> QFont:
    """Montserrat — for all body/prose text, chat messages, descriptions."""
    f = QFont("Montserrat", size)
    return f

def font_mono(size: int = 10) -> QFont:
    """Consolas — for timestamps, codes, RAM values."""
    f = QFont("Consolas", size)
    return f

# ── priority color ─────────────────────────────────────────────────────────────
def priority_color(p: int) -> str:
    if p >= 9: return C_RED
    if p >= 7: return C_GOLD
    if p >= 4: return C_CYAN
    return C_TEXT_DIM

# ── Global QSS ─────────────────────────────────────────────────────────────────
def global_stylesheet() -> str:
    return f"""
    /* ══ BASE ══ */
    QWidget {{
        background-color: transparent;
        color: {C_TEXT};
        font-family: "Montserrat", "Segoe UI";
        font-size: 11px;
        border: none;
    }}
    QLabel  {{ background: transparent; }}
    QFrame  {{ background: transparent; }}

    /* ══ SCROLLBARS ══ */
    QScrollBar:vertical {{
        background: transparent;
        width: 5px;
        margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: {C_BORDER_LIT};
        min-height: 24px;
        border-radius: 2px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {C_CYAN}; }}
    QScrollBar::add-line:vertical,
    QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical,
    QScrollBar::sub-page:vertical {{ background: transparent; }}

    QScrollBar:horizontal {{
        background: transparent;
        height: 5px;
    }}
    QScrollBar::handle:horizontal {{
        background: {C_BORDER_LIT};
        min-width: 24px;
        border-radius: 2px;
    }}
    QScrollBar::handle:horizontal:hover {{ background: {C_CYAN}; }}
    QScrollBar::add-line:horizontal,
    QScrollBar::sub-line:horizontal {{ width: 0; }}

    /* ══ SCROLL AREAS ══ */
    QScrollArea, QAbstractScrollArea {{
        border: none;
        background: transparent;
    }}
    QScrollArea > QWidget > QWidget,
    QAbstractScrollArea > QWidget > QWidget {{
        background: transparent;
    }}

    /* ══ TEXT AREAS ══ */
    QTextEdit, QPlainTextEdit {{
        background-color: {C_PANEL};
        color: {C_TEXT_BRIGHT};
        border: 1px solid {C_BORDER};
        border-radius: 6px;
        padding: 8px;
        font-family: "Montserrat", "Segoe UI";
        font-size: 11px;
        selection-background-color: {C_CYAN_DIM};
    }}
    QTextEdit:focus, QPlainTextEdit:focus {{
        border: 1px solid {C_BORDER_LIT};
    }}

    /* ══ BUTTONS ══ */
    QPushButton {{
        background-color: transparent;
        color: {C_CYAN};
        border: 1px solid {C_BORDER_LIT};
        border-radius: 4px;
        padding: 5px 12px;
        font-family: "Montserrat";
        font-size: 11px;
    }}
    QPushButton:hover {{
        background-color: rgba(0, 229, 255, 0.13);
        border-color: {C_CYAN};
        color: {C_TEXT_BRIGHT};
    }}
    QPushButton:pressed {{
        background-color: rgba(0, 229, 255, 0.25);
    }}
    QPushButton:disabled {{
        color: {C_TEXT_DIM};
        border-color: {C_BORDER};
    }}

    /* ══ SPLITTER ══ */
    QSplitter::handle {{
        background-color: {C_BORDER};
    }}
    QSplitter::handle:hover {{ background-color: {C_BORDER_LIT}; }}
    QSplitter::handle:horizontal {{ width: 2px; }}
    QSplitter::handle:vertical   {{ height: 2px; }}

    /* ══ TOOLTIPS ══ */
    QToolTip {{
        background-color: {C_PANEL};
        color: {C_TEXT_BRIGHT};
        border: 1px solid {C_BORDER_LIT};
        border-radius: 4px;
        padding: 5px;
        font-size: 10px;
    }}

    /* ══ STACKED WIDGET ══ */
    QStackedWidget {{ background: transparent; }}
    """
