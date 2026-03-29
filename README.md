# ◈ ALLIANCE TERMINAL VERSION 3

> "I am Normandy, your tactical operations butler. My utility is at your disposal, Commander."

**Alliance Terminal Version 3** is a privacy-focused, locally hosted AI assistant designed as a proactive, biologically aware scheduling coach. Optimized for Intel Core Ultra (NPU) and modern edge hardware, it functions as a formal English Butler providing strategic oversight of your daily operations.

---

## ⚡ Deployment Protocol (Setup from Scratch)

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
2.  **Requisition AI Cores**: Download and export the base model (**Qwen 2.5 7B**) into an OpenVINO-optimized format. This script handles the hardware-specific graph compilation.
    ```powershell
    python download_model.py
    ```
3.  **Launch Interface**: Activate the terminal.
    ```powershell
    python main.py
    ```

---

## 🧠 Core Capabilities

### 1. NPU-Accelerated Intelligence
Unlike standard AI assistants that rely on cloud APIs, the Terminal runs entirely on **Local Silicon**.
*   **OpenVINO GenAI**: Low-latency inference using the Intel NPU.
*   **Structured Extraction**: The AI doesn't just "chat"—it extracts JSON schemas for tasks, reminders, and facts with 98% accuracy.
*   **Zero-Wake Privacy**: No data leaves your machine. Your schedule and conversations are yours alone.

### 2. Biological Cognitive Engine
The Terminal is "Biologically Aware." It calculates your **Operative Status (Energy Score)** in real-time based on:
*   **Sleep Debt**: Penalties (-5% per hour) for falling below your 7h baseline.
*   **Cognitive Load**: High-intensity tasks (Code, Study, Meetings) drain energy faster than chores.
*   **Post-Prandial Lethargy**: Automatic 90-minute "Food Coma" penalties following Lunch or Dinner.
*   **Recovery Loops**: Biometric restoration via completed Powernaps (+30%) or Snacks (+15%).

### 3. Dossier Memory (RAG)
Powered by **ChromaDB**, the Terminal maintains a "Commander Dossier." It automatically extracts durable facts (e.g., "User is a morning person," "User studies Computer Science") from conversation and injects them into the AI's context for perfect long-term recall.

---

## 📁 Codebase Map (File Functions)

### ◈ Root Backend
*   [main.py](file:///c:/Users/ashok/Documents/Github%20Projects/Assistant%20v2/main.py): Entry point. Handles **Main Thread Initialization** (required for NPU stability) and orchestrates the backend boot sequence.
*   [ai_backend.py](file:///c:/Users/ashok/Documents/Github%20Projects/Assistant%20v2/ai_backend.py): The interface for OpenVINO. Handles prompt templating, token streaming, and structured JSON parsing.
*   [logic_engine.py](file:///c:/Users/ashok/Documents/Github%20Projects/Assistant%20v2/logic_engine.py): The "Brain." Contains the scheduling algorithms, energy calculations, and biological constraint enforcement.
*   [memory_manager.py](file:///c:/Users/ashok/Documents/Github%20Projects/Assistant%20v2/memory_manager.py): Manages the local vector database (ChromaDB) for user fact storage and retrieval.
*   [prompts.yaml](file:///c:/Users/ashok/Documents/Github%20Projects/Assistant%20v2/prompts.yaml): Centralized operational manifest defining the personality and extraction rules for the AI.

### ◈ UI Subsystem (PyQt6)
*   [ui/window.py](file:///c:/Users/ashok/Documents/Github%20Projects/Assistant%20v2/ui/window.py): Main resizable, frameless window container. Manages global states (Online/Processing) and hit-tests.
*   [ui/panels.py](file:///c:/Users/ashok/Documents/Github%20Projects/Assistant%20v2/ui/panels.py): Defines the three-column layout (Left: Dossier/Tasks; Center: Comms; Right: Status/Ops).
*   [ui/widgets.py](file:///c:/Users/ashok/Documents/Github%20Projects/Assistant%20v2/ui/widgets.py): Custom-painted components (Energy bars, Sparklines, Sci-fi panels) using QPainter for high performance.
*   [ui/theme.py](file:///c:/Users/ashok/Documents/Github%20Projects/Assistant%20v2/ui/theme.py): Global design system (colors, fonts, and QSS stylesheets).
*   [ui/workers.py](file:///c:/Users/ashok/Documents/Github%20Projects/Assistant%20v2/ui/workers.py): Thread management for AI generation, RAM diagnostics, and reminder alerts.

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

## ◈ Credits
*   **Aesthetics**: Inspired by the *Mass Effect* Alliance Terminal Version 3 interface.
*   **AI Core**: Optimized OpenVINO implementation of Qwen 2.5 and other OpenVINO AI models.
*   **Developer**: Ashok Iynkaran.

*"Commander, your status is nominal. I await your next instruction."*
