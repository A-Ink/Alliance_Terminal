# ALLIANCE TERMINAL VERSION 3

> "I am Normandy, your tactical operations butler. My utility is at your disposal, Commander."

**Alliance Terminal Version 3** is a privacy-focused, zero-cloud AI assistant with a **tiered intelligence architecture**. It dynamically switches between an **NPU** (low-power triage) and a **dGPU** (deep reasoning) based on your laptop's power state. Built as a biologically aware scheduling coach, it manages your daily operations with the formal precision of an English Butler.

---

## Deployment Protocol (Quick Start)

### 1. Requirements
*   **Operating System**: Windows 11.
*   **Hardware**: 16GB+ RAM. Recommended: **Intel Core Ultra** (for NPU) + **NVIDIA RTX dGPU** (for deep reasoning).
*   **Python**: v3.12.
*   **CUDA Toolkit**: v12.6 (for dGPU support — **do not use CUDA 13.x**, it has compatibility issues).

### 2. Installation

Open a PowerShell terminal in the project root:

1.  **Initialize Environment**: Creates venv, installs dependencies, and optionally sets up CUDA/llama-cpp-python.
    ```powershell
    ./setup.ps1
    ```
    The setup script will:
    - Create a Python 3.12 virtual environment
    - Install core dependencies (OpenVINO, PyQt6, ChromaDB)
    - Detect CUDA/Vulkan and offer GPU backend installation
    - Option `[P]` installs a pre-built llama-cpp-python wheel (no compilation needed)

2.  **Download AI Models**: Download the NPU and dGPU model files.
    ```powershell
    python download_model.py
    ```

3.  **Launch Terminal**:
    ```powershell
    python main.py
    ```

---

## Architecture

### Tiered Intelligence System

| Tier | Hardware | Model | When Active | Purpose |
|------|----------|-------|-------------|---------|
| **NPU** | Intel Core Ultra NPU | Qwen 2.5 7B (OpenVINO) | On battery | Fast triage, JSON extraction, simple tasks |
| **dGPU** | NVIDIA RTX (CUDA) | Gemma 4 27B / Qwen 3 27B (GGUF) | On AC power | Deep reasoning, schedule analysis, complex queries |

The **Pipeline Orchestrator** handles seamless hot-swapping between tiers when power state changes. A status bar at the top shows the active tier in real-time.

### Phase 1: Core Intelligence
- OpenVINO NPU backend with hardware-specific model caching
- llama.cpp dGPU backend with CUDA acceleration
- Structured JSON intent extraction from natural language
- Streaming token output with live UI updates

### Phase 2: Fast-Paths & Deferral
- **Python Fast-Path**: Regex parser catches common commands ("remind me to X at Y") and bypasses the AI entirely for near-zero latency
- **Deep Thought Deferral**: When the NPU is unsure (< 90% confidence), it flags `requires_deep_thought: true`. The prompt is queued and processed when the dGPU comes online
- **Persistent Queue**: Deferred prompts survive app restarts via `schedule.json`

### Phase 3: UI Transparency & Proactive Gathering
- **Pipeline Status Bar**: Live indicator showing NPU Active / dGPU Active / Swapping
- **Schedule Sanity Checker**: On dGPU boot, validates meal ordering, sleep/wake coherence, and event overlaps — prompts the user to fix anomalies
- **User State Micro-Interactions**: Proactively asks about sleep quality, energy levels, and daily goals to build context
- **GPU Context Payload**: Rich biological + schedule context injected into dGPU prompts for personalized recommendations

---

## Core Features

### Local-Silicon Intelligence (Privacy First)
Unlike cloud-based assistants, the Terminal runs **100% locally**. No recordings or schedule data ever leave your machine.

### Biological Cognitive Engine
Calculates your **Operative Status (Energy Score)** in real-time based on:
*   **Circadian Decay**: Linear energy decline from wake to sleep
*   **Sleep Debt**: Penalties for falling below your baseline
*   **Food Comas**: Post-prandial lethargy windows following meals
*   **Cognitive Load**: High-intensity tasks drain energy faster

### Permanent Dossier Memory
Powered by **ChromaDB**, the Terminal maintains a "Commander Dossier" — your preferences, biographical details, and past facts. These are injected into AI context for personalized long-term recall.

### Mathematical Operations Timeline
A live, 36-hour window into your schedule:
*   **12h Past / 24h Future**: See where your time went and where it's going
*   **Free Time Gaps**: Automatically identifies and displays gaps between events
*   **Active Event Glow**: Current active events pulse emerald green

### Schedule Sanity Checking
On dGPU boot, the system validates:
*   Breakfast is after wake time
*   Meal ordering is correct (Breakfast < Lunch < Dinner)
*   No activities during sleep windows
*   No overlapping events
*   No excessively long events (> 8 hours for non-sleep)

---

## Tactical Interface

The title bar contains three action buttons:

*   **MODEL**: Switch between different AI cores on the fly
*   **DEVICE**: Toggle which hardware handles AI processing
*   **HELP**: Access the tactical manual with scheduling engine documentation

Side panels collapse inward using the `«` and `»` buttons.

---

## File Architecture

### Backend Core
*   [main.py](main.py) — Entry point. Main-thread hardware init, power monitoring, orchestrator setup.
*   [ai_backend.py](ai_backend.py) — OpenVINO + llama.cpp dual backend. Streaming, JSON extraction, model management.
*   [logic_engine.py](logic_engine.py) — Scheduling engine: ripple rescheduling, priority gravity, biological anchors, sanity checking.
*   [memory_manager.py](memory_manager.py) — ChromaDB vector storage for user-fact persistence.
*   [power_manager.py](power_manager.py) — Power state monitoring + Pipeline Orchestrator for tier swapping.
*   [fast_path.py](fast_path.py) — Regex-based command interceptor for zero-latency common operations.

### UI Subsystem
*   [ui/window.py](ui/window.py) — Frameless resizable window, pipeline status bar, swap callbacks.
*   [ui/panels.py](ui/panels.py) — Three-column layout (Left: Dossier/Tasks; Center: Chat; Right: Status/Ops).
*   [ui/dialogs.py](ui/dialogs.py) — Popup system for model management and documentation.
*   [ui/widgets.py](ui/widgets.py) — Custom-painted components (Energy Bar, Schedule Rows, Tab Strips).
*   [ui/theme.py](ui/theme.py) — Design system: Orbitron + Montserrat typography with font hinting.

### Configuration
*   [config.json](config.json) — Model paths, GPU model key, hardware settings.
*   [prompts.yaml](prompts.yaml) — Tiered prompt system (NPU vs GPU), model-specific hints.
*   [schedule.json](schedule.json) — Persistent state: schedules, tasks, reminders, user state, deferral queue.

---

## Credits & Inspiration
*   **Aesthetics**: Inspired by the *Mass Effect* Alliance Terminal interface.
*   **AI Cores**: OpenVINO (NPU) + llama.cpp (dGPU).
*   **Developer**: Ashok Iynkaran and lots of AI coding agents.
