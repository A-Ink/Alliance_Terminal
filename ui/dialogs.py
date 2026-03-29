"""
Alliance Terminal Version 3 — Tactical Popup Dialogs
Three sci-fi styled dialogs: Model Switcher, Device Toggle, and Help/Manual.
All dialogs inherit the Alliance Terminal dark aesthetic.
"""

import json
import subprocess
import sys
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QWidget, QFrame, QSizePolicy, QButtonGroup
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QPainter, QPainterPath, QColor, QFont

from .theme import (
    C_BG, C_PANEL, C_BORDER, C_BORDER_LIT, C_CYAN, C_CYAN_DIM,
    C_GREEN, C_GOLD, C_RED, C_TEXT, C_TEXT_BRIGHT, C_TEXT_DIM,
    S_MONTSERRAT, S_ORBITRON,
    font_orbitron, font_body,
    BG, PANEL, BORDER, CYAN,
)

_CONFIG_PATH = Path(__file__).parent.parent / "config.json"
_MODEL_DIR   = Path(__file__).parent.parent / "model"

# ── Descriptions for each model (supplemental, since config.json is minimal) ──
_MODEL_DESCRIPTIONS = {
    "qwen-2.5-7b":  "A well-rounded 7B general-purpose model. Excellent for scheduling, tasking, and day-to-day assist commands. Optimised for balanced speed and intelligence on Intel NPU.",
    "qwen-3-8b":    "Upgraded reasoning core with improved chain-of-thought depth. Best for complex planning, multi-step analysis, and nuanced decision support. Slightly slower on first inference.",
    "phi-4-mini":   "Lightweight speed core. Fastest response times, minimal VRAM footprint. Ideal for quick queries, reminders, and simple tasking when battery efficiency is critical.",
    "mistral-7b":   "High-precision execution core tuned for precise, structured outputs. Optimal for technical questions and rigorous schedule management with minimal hallucination.",
}


# ══════════════════════════════════════════════════════════════════════════════
# BASE DIALOG — sci-fi aesthetic shared by all dialogs
# ══════════════════════════════════════════════════════════════════════════════

class _BaseDialog(QDialog):
    """Dark sci-fi base dialog with rounded corners and glowing cyan border."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Dialog |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setModal(True)

        # Root layout with margins for the border shadow
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Inner container (painted with rounded background)
        self._inner = QWidget()
        self._inner.setObjectName("dialogInner")
        self._inner.setStyleSheet(f"""
            QWidget#dialogInner {{
                background: {C_BG};
                border: 1px solid {C_BORDER_LIT};
                border-radius: 10px;
            }}
            QLabel {{ background: transparent; }}
            QPushButton {{
                background: transparent; color: {C_CYAN};
                border: 1px solid {C_BORDER_LIT}; border-radius: 4px;
                padding: 6px 14px;
                font-family: {S_ORBITRON}; font-size: 9px;
                letter-spacing: 1.5px;
            }}
            QPushButton:hover {{
                background: rgba(0,229,255,0.14); border-color: {C_CYAN};
                color: {C_TEXT_BRIGHT};
            }}
            QPushButton:pressed {{ background: rgba(0,229,255,0.28); }}
        """)
        root.addWidget(self._inner)

        inner_lay = QVBoxLayout(self._inner)
        inner_lay.setContentsMargins(0, 0, 0, 0)
        inner_lay.setSpacing(0)

        # ── Title bar ──
        tbar = QWidget()
        tbar.setFixedHeight(44)
        tbar.setStyleSheet(f"background: {C_PANEL}; border-radius: 10px; border-bottom-left-radius: 0; border-bottom-right-radius: 0;")
        tb_lay = QHBoxLayout(tbar)
        tb_lay.setContentsMargins(16, 0, 8, 0)

        t_lbl = QLabel(title)
        t_lbl.setFont(font_orbitron(10, QFont.Weight.Bold))
        t_lbl.setStyleSheet(f"color: {C_CYAN}; letter-spacing: 4px; background: transparent;")
        tb_lay.addWidget(t_lbl, 1)

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(28, 28)
        close_btn.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {C_TEXT_DIM}; border: none; font-size: 13px; }}
            QPushButton:hover {{ color: {C_RED}; background: rgba(255,50,50,0.18); border-radius: 4px; }}
        """)
        close_btn.clicked.connect(self.close)
        tb_lay.addWidget(close_btn)
        inner_lay.addWidget(tbar)

        # Divider
        div = QFrame()
        div.setFrameShape(QFrame.Shape.HLine)
        div.setStyleSheet(f"background: {C_BORDER_LIT}; max-height: 1px;")
        inner_lay.addWidget(div)

        # Content area — subclasses add their widgets here
        self._content = QWidget()
        self._content.setStyleSheet("background: transparent;")
        self._content_lay = QVBoxLayout(self._content)
        self._content_lay.setContentsMargins(20, 16, 20, 20)
        self._content_lay.setSpacing(12)
        inner_lay.addWidget(self._content, 1)

        self._drag_pos = None

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(0, 0, self.width(), self.height(), 10, 10)
        p.fillPath(path, BG)
        p.setPen(QColor(0, 200, 224, 180))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        p.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_pos and event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        super().mouseReleaseEvent(event)


# ══════════════════════════════════════════════════════════════════════════════
# MODEL SWITCHER DIALOG
# ══════════════════════════════════════════════════════════════════════════════

class ModelSwitcherDialog(_BaseDialog):
    """Tactical core selection — lists all models from config.json with load/download options."""

    model_selected = pyqtSignal(str)  # emits model key when user clicks LOAD CORE

    def __init__(self, parent=None):
        super().__init__("◈  TACTICAL CORE SELECTION", parent)
        self.setMinimumWidth(640)
        self.setMinimumHeight(400)

        try:
            with open(_CONFIG_PATH, "r") as f:
                self._cfg = json.load(f)
        except Exception:
            self._cfg = {}

        active_key = self._cfg.get("active_model", "")
        models     = self._cfg.get("models", {})

        # Subtitle
        sub = QLabel("Select an AI tactical core to load. Download cores that are not yet installed.")
        sub.setFont(font_body(10))
        sub.setStyleSheet(f"color: {C_TEXT_DIM}; background: transparent;")
        sub.setWordWrap(True)
        self._content_lay.addWidget(sub)

        # Scroll area for model cards
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("background: transparent; border: none;")
        cards_w = QWidget()
        cards_w.setStyleSheet("background: transparent;")
        cards_lay = QVBoxLayout(cards_w)
        cards_lay.setContentsMargins(0, 0, 4, 0)
        cards_lay.setSpacing(10)
        scroll.setWidget(cards_w)
        self._content_lay.addWidget(scroll, 1)

        for key, info in models.items():
            self._add_model_card(cards_lay, key, info, key == active_key)

        cards_lay.addStretch()

    def _model_is_downloaded(self, info: dict) -> bool:
        model_path = Path(__file__).parent.parent / info.get("path", "").lstrip("./")
        return model_path.exists() and any(model_path.iterdir()) if model_path.exists() else False

    def _add_model_card(self, lay, key: str, info: dict, is_active: bool):
        downloaded = self._model_is_downloaded(info)
        border_col = C_CYAN if is_active else C_BORDER
        bg_col     = "rgba(0,229,255,0.06)" if is_active else f"{C_PANEL}"

        card = QWidget()
        card.setStyleSheet(f"""
            QWidget {{
                background: {bg_col};
                border: 1px solid {border_col};
                border-radius: 6px;
            }}
            QLabel {{ background: transparent; }}
        """)
        card_lay = QHBoxLayout(card)
        card_lay.setContentsMargins(14, 12, 14, 12)
        card_lay.setSpacing(12)

        # Left: info
        info_col = QVBoxLayout()
        info_col.setSpacing(4)

        name_lbl = QLabel(info.get("display_name", key).upper())
        name_lbl.setFont(font_orbitron(10, QFont.Weight.Bold))
        name_lbl.setStyleSheet(f"color: {C_CYAN if is_active else C_TEXT_BRIGHT}; background: transparent;")
        info_col.addWidget(name_lbl)

        meta = f"{info.get('engine','').upper()}  ·  {info.get('target_device','?')}  ·  ctx {info.get('context_size','?')} tok  ·  max {info.get('max_tokens','?')} tok out"
        meta_lbl = QLabel(meta)
        meta_lbl.setFont(font_body(9))
        meta_lbl.setStyleSheet(f"color: {C_TEXT_DIM}; background: transparent;")
        info_col.addWidget(meta_lbl)

        desc_lbl = QLabel(_MODEL_DESCRIPTIONS.get(key, info.get("hf_model_id", "")))
        desc_lbl.setFont(font_body(10))
        desc_lbl.setStyleSheet(f"color: {C_TEXT}; background: transparent;")
        desc_lbl.setWordWrap(True)
        info_col.addWidget(desc_lbl)

        card_lay.addLayout(info_col, 1)

        # Right: buttons
        btn_col = QVBoxLayout()
        btn_col.setSpacing(6)
        btn_col.setAlignment(Qt.AlignmentFlag.AlignCenter)

        if is_active:
            status_lbl = QLabel("● ACTIVE")
            status_lbl.setFont(font_orbitron(8, QFont.Weight.Bold))
            status_lbl.setStyleSheet(f"color: {C_GREEN}; letter-spacing: 2px; background: transparent;")
            status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            btn_col.addWidget(status_lbl)
        else:
            load_btn = QPushButton("LOAD CORE")
            load_btn.setFixedWidth(110)
            if not downloaded:
                load_btn.setEnabled(False)
                load_btn.setStyleSheet(f"""
                    QPushButton {{background: transparent; color: {C_TEXT_DIM};
                                  border: 1px solid {C_BORDER}; border-radius: 4px;
                                  padding: 6px 10px; font-family: {S_ORBITRON}; font-size: 8px;}}
                """)
            load_btn.clicked.connect(lambda _, k=key: self._on_load(k))
            btn_col.addWidget(load_btn)

        if not downloaded:
            dl_btn = QPushButton("⬇  DOWNLOAD")
            dl_btn.setFixedWidth(110)
            dl_btn.setStyleSheet(f"""
                QPushButton {{background: rgba(242,169,0,0.10); color: {C_GOLD};
                              border: 1px solid {C_GOLD}; border-radius: 4px;
                              padding: 6px 10px; font-family: {S_ORBITRON}; font-size: 8px;}}
                QPushButton:hover {{background: rgba(242,169,0,0.20);}}
            """)
            dl_btn.clicked.connect(lambda _, k=key, i=info: self._on_download(k, i))
            btn_col.addWidget(dl_btn)
        else:
            avail_lbl = QLabel("✓ INSTALLED")
            avail_lbl.setFont(font_orbitron(7))
            avail_lbl.setStyleSheet(f"color: {C_GREEN}; letter-spacing: 1px; background: transparent;")
            avail_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            btn_col.addWidget(avail_lbl)

        card_lay.addLayout(btn_col)
        lay.addWidget(card)

    def _on_load(self, key: str):
        try:
            with open(_CONFIG_PATH, "r") as f:
                cfg = json.load(f)
            cfg["active_model"] = key
            with open(_CONFIG_PATH, "w") as f:
                json.dump(cfg, f, indent=2)
        except Exception:
            pass
        self.model_selected.emit(key)
        self.close()

    def _on_download(self, key: str, info: dict):
        hf_id = info.get("hf_model_id", "")
        target = info.get("path", f"./model/{key}").lstrip("./")
        script = Path(__file__).parent.parent / "download_model.py"
        if script.exists():
            subprocess.Popen([sys.executable, str(script), "--model", hf_id, "--output", target])
        self.close()


# ══════════════════════════════════════════════════════════════════════════════
# DEVICE TOGGLE DIALOG
# ══════════════════════════════════════════════════════════════════════════════

class DeviceToggleDialog(_BaseDialog):
    """Switch target silicon between NPU and iGPU."""

    device_changed = pyqtSignal(str)  # emits "NPU" or "GPU"

    DEVICES = [
        ("NPU",  "Intel Neural Processing Unit — highest efficiency, lowest power. Optimal for sustained AI inference on battery."),
        ("GPU",  "Intel Integrated GPU — higher throughput, more VRAM headroom. Better for longer context and reasoning models."),
        ("CPU",  "Host CPU fallback — universal compatibility, slowest inference. Use only when NPU/GPU are unavailable."),
    ]

    def __init__(self, parent=None):
        super().__init__("⬡  SILICON TARGET SELECTION", parent)
        self.setFixedWidth(520)

        try:
            with open(_CONFIG_PATH, "r") as f:
                cfg = json.load(f)
            self._priority = cfg.get("device_priority", ["NPU", "GPU", "CPU"])
        except Exception:
            self._priority = ["NPU", "GPU", "CPU"]

        self._active = self._priority[0] if self._priority else "NPU"

        sub = QLabel("Select target silicon. Changes take effect on next application restart.")
        sub.setFont(font_body(10))
        sub.setStyleSheet(f"color: {C_TEXT_DIM}; background: transparent;")
        sub.setWordWrap(True)
        self._content_lay.addWidget(sub)

        for dev_key, dev_desc in self.DEVICES:
            self._add_device_row(dev_key, dev_desc)

        # Confirm button
        self._content_lay.addSpacing(8)
        confirm_btn = QPushButton("CONFIRM & SAVE")
        confirm_btn.setFixedHeight(38)
        confirm_btn.setFont(font_orbitron(9, QFont.Weight.Bold))
        confirm_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(0,229,255,0.12); color: {C_CYAN};
                border: 1px solid {C_BORDER_LIT}; border-radius: 5px;
                padding: 8px 20px; letter-spacing: 2px;
            }}
            QPushButton:hover {{
                background: rgba(0,229,255,0.22); color: {C_TEXT_BRIGHT};
                border-color: {C_CYAN};
            }}
        """)
        confirm_btn.clicked.connect(self._on_confirm)
        self._content_lay.addWidget(confirm_btn)

    def _add_device_row(self, key: str, desc: str):
        is_active = (key == self._active)
        border_col = C_CYAN if is_active else C_BORDER
        bg_col     = "rgba(0,229,255,0.07)" if is_active else C_PANEL

        row = QWidget()
        row.setObjectName(f"devrow_{key}")
        row.setStyleSheet(f"""
            QWidget#devrow_{key} {{
                background: {bg_col}; border: 1px solid {border_col}; border-radius: 6px;
            }}
            QLabel {{ background: transparent; }}
        """)
        row_lay = QHBoxLayout(row)
        row_lay.setContentsMargins(14, 12, 14, 12)
        row_lay.setSpacing(12)

        text_col = QVBoxLayout()
        text_col.setSpacing(4)
        name_lbl = QLabel(key)
        name_lbl.setFont(font_orbitron(12, QFont.Weight.Bold))
        name_lbl.setStyleSheet(f"color: {C_CYAN if is_active else C_TEXT_BRIGHT}; background: transparent;")
        text_col.addWidget(name_lbl)

        desc_lbl = QLabel(desc)
        desc_lbl.setFont(font_body(10))
        desc_lbl.setStyleSheet(f"color: {C_TEXT}; background: transparent;")
        desc_lbl.setWordWrap(True)
        text_col.addWidget(desc_lbl)
        row_lay.addLayout(text_col, 1)

        if is_active:
            sel_lbl = QLabel("● SELECTED")
            sel_lbl.setFont(font_orbitron(8, QFont.Weight.Bold))
            sel_lbl.setStyleSheet(f"color: {C_GREEN}; letter-spacing: 2px; background: transparent;")
            row_lay.addWidget(sel_lbl)
        else:
            sel_btn = QPushButton("SELECT")
            sel_btn.setFixedWidth(90)
            sel_btn.clicked.connect(lambda _, k=key: self._on_select(k))
            row_lay.addWidget(sel_btn)

        self._content_lay.addWidget(row)

    def _on_select(self, key: str):
        self._active = key
        # Refresh the dialog by re-populating (remove device rows and re-add)
        # Simpler: just record selection and update config on confirm
        # Update visual without rebuild — just confirm and close
        self._on_confirm()

    def _on_confirm(self):
        try:
            with open(_CONFIG_PATH, "r") as f:
                cfg = json.load(f)
            rest = [d for d in cfg.get("device_priority", ["NPU", "GPU", "CPU"]) if d != self._active]
            cfg["device_priority"] = [self._active] + rest
            with open(_CONFIG_PATH, "w") as f:
                json.dump(cfg, f, indent=2)
        except Exception:
            pass
        self.device_changed.emit(self._active)
        self.close()


# ══════════════════════════════════════════════════════════════════════════════
# HELP / MANUAL DIALOG
# ══════════════════════════════════════════════════════════════════════════════

class HelpDialog(_BaseDialog):
    """Scrollable tactical manual covering all features, logic, and mathematics."""

    def __init__(self, parent=None):
        super().__init__("?  TACTICAL MANUAL  ·  ALLIANCE TERMINAL V3", parent)
        self.setMinimumSize(700, 580)
        self.resize(740, 640)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("background: transparent; border: none;")

        body = QWidget()
        body.setStyleSheet("background: transparent;")
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(0, 0, 8, 0)
        body_lay.setSpacing(16)
        scroll.setWidget(body)
        self._content_lay.addWidget(scroll, 1)

        for section_title, section_blocks in _MANUAL_CONTENT:
            self._add_section(body_lay, section_title, section_blocks)

        body_lay.addStretch()

    def _add_section(self, lay, title: str, blocks: list):
        # Section header
        hdr = QLabel(title)
        hdr.setFont(font_orbitron(9, QFont.Weight.Bold))
        hdr.setStyleSheet(f"""
            color: {C_CYAN}; letter-spacing: 3px; padding: 6px 0 4px 0;
            border-bottom: 1px solid {C_BORDER_LIT}; background: transparent;
        """)
        lay.addWidget(hdr)

        for block_type, content in blocks:
            if block_type == "p":
                lbl = QLabel(content)
                lbl.setFont(font_body(11))
                lbl.setStyleSheet(f"color: {C_TEXT}; background: transparent;")
                lbl.setWordWrap(True)
                lay.addWidget(lbl)
            elif block_type == "h":
                lbl = QLabel(content)
                lbl.setFont(font_orbitron(8, QFont.Weight.Bold))
                lbl.setStyleSheet(f"color: {C_TEXT_BRIGHT}; letter-spacing: 2px; background: transparent; padding-top: 6px;")
                lay.addWidget(lbl)
            elif block_type == "code":
                lbl = QLabel(content)
                lbl.setFont(font_body(10))
                lbl.setStyleSheet(f"""
                    color: {C_GREEN}; background: rgba(0,255,136,0.06);
                    border-left: 2px solid {C_GREEN}; border-radius: 3px;
                    padding: 8px 12px; font-family: {S_MONTSERRAT};
                """)
                lbl.setWordWrap(True)
                lay.addWidget(lbl)


_MANUAL_CONTENT = [
    ("CORE FEATURES", [
        ("h", "Tactical AI Chat"),
        ("p", "Type any natural language command in the COMMAND INPUT box and press Ctrl+Enter or click TRANSMIT. The AI (powered by a local OpenVINO model on your NPU) interprets your intent and responds immediately. All inference runs 100% locally — no cloud connection required."),
        ("h", "Schedule / Operations Timeline"),
        ("p", "The right panel displays your Operations Timeline — a live 36-hour window showing events 12 hours into the past and 24 hours into the future. Active events glow green. Free time gaps are shown as FREE TIME blocks. Events are sorted chronologically and persisted to disk."),
        ("h", "Tasks"),
        ("p", "Tasks are flexible work items without a hard time slot. They appear in the left panel under TASKS. Tell the AI to create a task and it will be tracked with priority and optional deadline. Mark tasks complete by clicking the check button."),
        ("h", "Reminders"),
        ("p", "Reminders are time-based alerts. The system checks for upcoming reminders every 60 seconds and will push an alert into the chat panel automatically. Dismiss them with the ✕ button."),
        ("h", "Commander Dossier (Codex)"),
        ("p", "The Codex tab (left panel) stores facts the AI has learned about you — preferences, important context, biographical details. Facts are stored in a local ChromaDB vector database and are automatically injected into every AI prompt for continuity."),
        ("code", "/forget [fact]  — Deletes a specific fact from the Codex memory.\nExample: /forget my meeting is on Tuesday"),
    ]),
    ("AI LOGIC ENGINE", [
        ("h", "Intent Parsing"),
        ("p", "Every message is processed through a structured JSON intent pipeline. The AI returns a JSON object containing a natural language response plus typed intent arrays: schedule_events, tasks, reminders, facts, and sleep_wake_update."),
        ("h", "Schedule Modification Flow"),
        ("p", "When the AI modifies a schedule event (e.g., 'shift lunch to 1:45pm'), the engine: (1) locates the existing event by name, (2) suppresses biological anchor re-injection via the _suppress_anchors flag, (3) removes the original slot, (4) computes the new absolute time, (5) inserts the updated event, and (6) re-runs biological anchor alignment to verify consistency."),
        ("h", "Biological Anchors"),
        ("p", "Sleep, Wake, Breakfast, Lunch, and Dinner are 'biological anchors' — protected schedule slots that the engine automatically injects each day. They have high priority (8-10) and are re-evaluated on every schedule change to ensure they don't conflict with your work blocks."),
    ]),
    ("SCHEDULE MATHEMATICS", [
        ("h", "Priority Gravity (Deadline Pull)"),
        ("p", "Tasks with deadlines gain effective priority through deadline gravity. As the deadline approaches, the effective priority increases automatically:"),
        ("code", "P_effective = P_base + floor(P_base × (1 - days_remaining / max_horizon))\n\nExample: P7 task due in 1 day (max_horizon=14):\nP_eff = 7 + floor(7 × (1 - 1/14)) = 7 + 6 = 13 → capped at 10"),
        ("h", "Ripple Rescheduling"),
        ("p", "When a new high-priority event is inserted into a slot already occupied by a lower-priority task, the engine evicts the lower task and attempts to find it a new slot. The evicted task is placed in an overflow queue and re-inserted in the first available gap that satisfies its constraints."),
        ("h", "Cognitive Load Balancing"),
        ("p", "The engine tracks total scheduled work minutes per time window. If a proposed slot would cause cognitive overload (too many high-effort tasks back-to-back), the engine delays the task to the next available recovery window."),
        ("h", "Energy-Adaptive Scheduling"),
        ("p", "The system tracks your current energy level (0–100). High-priority cognitive tasks are preferentially scheduled during peak energy windows (morning/early afternoon). Low-energy periods are reserved for lighter tasks or breaks."),
        ("code", "Energy decay model:\nEnergy(t) = max(30, 100 - 2.5 × hours_since_wake)\n\nPeak window: Energy > 70  → 09:00–13:00\nMid window:  Energy 40–70 → 13:00–17:00\nLow window:  Energy < 40  → 17:00+"),
        ("h", "Sleep Debt Recovery"),
        ("p", "If you slept less than your target duration (default 7 hours), the engine calculates sleep debt and may suggest an earlier bedtime or a recovery nap, injected as a biological anchor suggestion."),
    ]),
    ("HARDWARE & MODELS", [
        ("h", "NPU — Neural Processing Unit"),
        ("p", "Your Intel Core Ultra NPU is a dedicated AI accelerator with ~30 TOPS of compute. OpenVINO compiles the model into a hardware graph (blob) optimised specifically for the NPU architecture. The first run after a model change triggers recompilation (30–60s). Subsequent runs load the cached blob instantly."),
        ("h", "iGPU Fallback"),
        ("p", "If the NPU is unavailable or you prefer the GPU backend, set the device priority to GPU in the Device Toggle. The iGPU has more VRAM headroom and may handle larger context windows better at the cost of higher power draw."),
        ("h", "Model Files"),
        ("p", "Models are stored in the ./model/ directory. Each model requires openvino_model.xml, openvino_model.bin, and config.json. The compiled hardware blob cache is stored in %LOCALAPPDATA%\\AllianceTerminalV3\\cache."),
    ]),
]
