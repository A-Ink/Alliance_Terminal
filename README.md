# ◈ ALLIANCE TERMINAL VERSION 3

> "I am Normandy, your tactical operations butler. My utility is at your disposal, Commander."

**Alliance Terminal Version 3** is a privacy-focused, zero-cloud AI assistant. Optimized for **Intel Core Ultra (NPU)**, it functions as a biologically aware scheduling coach, managing your daily operations with the formal precision of an English Butler.

---

## ⚡ Deployment Protocol (Quick Start)

### 1. Requirements
*   **Operating System**: Windows 11 (Windows 10 may require manual pathing).
*   **Hardware**: 16GB+ RAM. Recommended: **Intel Core Ultra** (for NPU) or **Intel Arc** (for iGPU/Vulkan).
*   **Python**: v3.11 or v3.12 (Managed via setup script).

### 2. Implementation Steps
Open a PowerShell terminal in the project root:

1.  **Initialize Environment**: Run the automated setup to create the virtual environment and install optimized dependencies (OpenVINO, PyQt6, ChromaDB).
    ```powershell
    ./setup.ps1
    ```
2.  **Requisition AI Cores**: Download the base models. This handles hardware-specific graph compilation for your NPU.
    ```powershell
    python download_model.py
    ```
3.  **Launch Interface**: Activate the terminal.
    ```powershell
    python main.py
    ```

---

## 🧠 Core Features

### 1. Local-Silicon Intelligence (Privacy First)
Unlike cloud-based assistants (Siri, Alexa), the Terminal runs **100% locally**. No recordings or schedule data ever leave your machine.
*   **Hardware Acceleration**: Uses the Intel NPU for low-latency, battery-efficient inference.
*   **Structured Intent**: The AI extracts complex schedules, tasks, and reminders directly from your natural language input.

### 2. Biological Cognitive Engine
The Terminal is "Biologically Aware"—it understands that you aren't a machine. It calculates your **Operative Status (Energy Score)** in real-time based on:
*   **Sleep Debt**: Penalties for falling below your baseline.
*   **Food Comas**: Automatic "Post-Prandial Lethargy" windows following meals.
*   **Cognitive Load**: High-intensity tasks drain energy faster than simple chores.

### 3. Permanent Dossier Memory
Powered by **ChromaDB**, the Terminal maintains a "Commander Dossier." It remembers your preferences, biographical details, and past conversations, injecting them into its local memory for perfect long-term recall.

### 4. Mathematical Operations Timeline
A live, 36-hour window into your life.
*   **12h Past / 24h Future**: See exactly where your time went and where it’s going.
*   **Free Time Gaps**: Automatically identifies and displays gaps in your schedule.
*   **Tactical Glow**: Current active events glow emerald green with a pulsing indicator.

---

## 🕹 Tactical Interface Overview

The Version 3 interface features a revamped Title Bar with three primary tactical controls:

*   **◈ MODEL**: Switch between different AI cores (Qwen, Phi, Mistral) on the fly.
*   **⬡ NPU/iGPU**: Toggle which piece of hardware handles the AI processing (NPU for efficiency, iGPU for power).
*   **? MANUAL**: Access the full tactical manual, including the mathematics behind the scheduling engine.

> [!TIP]
> **Inward Compression**: Toggle the side panels using the ◀ and ▶ buttons. The panels now collapse *inward*, ensuring your central command console (Chat Panel) remains a constant, stable size.

---

## 📁 Architectural Specifications (For Developers)

### ◈ The Backend Core
*   [main.py](main.py): Entry point. Orchestrates the **Main Thread Hardware Initialization** (critical for NPU DLL stability).
*   [ai_backend.py](ai_backend.py): The OpenVINO bridge. Manages streaming, hardware-specific blob caching, and JSON intent extraction.
*   [logic_engine.py](logic_engine.py): The "Logic Layer." Implements ripple rescheduling, priority gravity, and biological anchor enforcement.
*   [memory_manager.py](memory_manager.py): Manages the local vector storage (ChromaDB) for user-fact persistence.

### ◈ The UI Subsystem
*   [ui/window.py](ui/window.py): Frameless, resizable window with custom hit-testing and inward panel logic.
*   [ui/panels.py](ui/panels.py): Defines the three-column layout (Left: Dossier/Tasks; Center: Comms; Right: Status/Ops).
*   [ui/dialogs.py](ui/dialogs.py): **[NEW]** Tactical popup system for model management and technical documentation.
*   [ui/widgets.py](ui/widgets.py): Custom-painted components (Energy Bar, pulsing Schedule Rows) using high-performance QPainter overrides.
*   [ui/theme.py](ui/theme.py): Centralized design system using a strict **Orbitron + Montserrat** typography stack with cross-platform fallbacks.

---

## 🛠 Operation Logic

### Temporal Shifting
The Terminal supports complex time-math natively. You can tell the AI:
*   *"Shift my 2pm meeting by +1h"*
*   *"I'll do the grocery run after lunch"*
*   *"Schedule a study block for 90 minutes after my nap"*

The `LogicEngine` calculates the final timestamps before updating the database, preventing common AI "hallucinations" regarding clock arithmetic.

### Biological Anchors
The schedule is built around **Anchors** (Sleep, Wake, Meals, Exercise). These are high-priority blocks that the `LogicEngine` will attempt to preserve. If a shift causes you to miss a meal or stay awake too late, the **Operative Status** will drop into the red, and Normandy will issue a formal warning.

---

## ◈ Credits & Inspiration
*   **Aesthetics**: Inspired by the *Mass Effect* Alliance Terminal interface.
*   **AI Core**: Optimized OpenVINO AI models.
*   **Developer**: Ashok Iynkaran and lots of AI coding agents.
