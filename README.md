# Alliance Terminal v2

A privacy-focused, locally hosted AI assistant tailored as a proactive, biologically aware scheduling coach. Styled around the *Mass Effect* universe, it embodies the professional, formal persona of an English Butler (Normandy Terminal), optimizing your calendar natively on edge hardware.

---

## 💻 Core Purpose: "Extraction-First" Modeling

The Alliance Terminal solves the "hallucination problem" of small language models (SLMs) by fundamentally restricting the AI's role. We decoupled scheduling logic from the LLM and passed it into a strict mathematical Python constraint engine.

- **The AI's Role**: Inference and Extraction. It identifies intent, simplifies task names, and extracts raw temporal data (start/end times, durations).
- **The Python Engine**: Logic and Execution. `mood_engine.py` handles the 24-hour math, conflict resolution, priority bin-packing, and "past-time" checks.

---

## 🧠 System Architecture

The architecture is optimized for **Intel Core Ultra** (Meteor Lake/Lunar Lake) silicon, maximizing performance while remaining battery-conscious.

### 1. NPU-First Pipeline (OpenVINO GenAI)
The primary engine uses **OpenVINO GenAI** 2025.x to route 7B/8B parameter models strictly to the **NPU**. This minimizes CPU/GPU overhead and enables sub-10s cold starts via specialized hardware graph caching (`model_cache`).

### 2. Hybrid Entity Extraction
We use `StructuredOutputConfig` (xgrammar) to enforce a strict JSON schema. The AI cannot hallucinate formatting; it *must* emit a response and a list of structured entities:
```json
{
  "response": "Certainly, Commander...",
  "entities": [
    { "label": "Tactics Briefing", "action": "create", "start_time": "14:00", "duration": 60 }
  ],
  "facts": []
}
```

### 3. Vulkan GGUF Fallback
For massive models or devices without an NPU, the terminal supports the **Vulkan Engine** via `llama-cpp-python`. This provides high-speed inference on Intel Arc and integrated GPUs across different architectures.

---

## ⚙️ Installation & Setup

### Requirements
- **OS**: Windows 11
- **Hardware**: Intel Core Ultra (for NPU) or Arc/iGPU (for Vulkan).
- **Python**: 3.11 (Recommended)

### Boot Sequence
1. **Interactive Setup**
   Run the automated deployment script to initialize the virtual environment and choose your engine:
   ```powershell
   ./setup.ps1
   ```
2. **Deploy AI Cores**
   Acquire and optimize the models (INT4 quantization + OpenVINO graph build):
   ```powershell
   python download_model.py
   ```
3. **Launch Terminal**
   Start the Normandy UI and AI backend:
   ```powershell
   python main.py
   ```

---

## 🛠️ Performance Tuning
- **Model Caching**: On the first run, the NPU/Vulkan graph is compiled and stored in `model_cache/`. Subsequent boots will skip compilation, moving from ~45s to <10s load times.
- **Resource Monitor**: The UI provides real-time telemetry of System RAM and App-specific memory usage.
- **Thermal Awareness**: The AI is programmed to suggest breaks and monitor "Biological Meal Anchors" to ensure the Commander remains at peak N6/N7 readiness.
