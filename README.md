# Alliance Terminal v2

A privacy-focused, locally hosted AI assistant tailored as a proactive, biologically aware scheduling coach. Styled around the *Mass Effect* universe, it optimizes your calendar natively on edge hardware (NPU/GPU) using the professional, formal persona of an English Butler.

---

## ⚡ Quick Start (Windows 11)

1. **Deploy Terminal**
   Run the automated script to set up your environment and dependencies:
   ```powershell
   ./setup.ps1
   ```
2. **Requisition AI Cores**
   Download and optimize the models (Qwen 2.5 7B) for your hardware:
   ```powershell
   python download_model.py
   ```
3. **Launch Interface**
   Start the Normandy UI and AI backend:
   ```powershell
   python main.py
   ```

---

## 🧠 Core Systems & Logic

The Terminal is powered by the **LogicEngine**, a custom biometric synthesis layer that enforces human-centric constraints.

### 1. Biometric Energy Bar (0-100%)
The UI displays a real-time energy score calculated from four primary variables:
- **Sleep Debt**: Penalties (-5% per hour) for falling below 7h of sleep.
- **Cognitive/Social Drain**: High-intensity tasks (Study/Meetings) drain energy at -10% per hour.
- **Food Coma**: Automatic 90-minute lethargy penalty (-25%) following Lunch or Dinner.
- **Recovery Boosts**: Rewards for maintenance. Completing **Snacks** (+15%) or **Powernaps** (+30%) restores energy.

### 2. Temporal Logic Engine
- **Waterfall Parser**: Supports natural language ("8.30pm"), keywords ("noon"), and absolute times ("20:30").
- **Relative Shifts**: Supports hybrid arithmetic like `+1h` or `19:30 + 1h`. Shifting events calculates new times on the backend to prevent AI math hallucinations.
- **Deterministic Action Sorter**: Ensures `delete` and `modify` operations occur before `create` to prevent schedule collisions during re-scheduling.

### 3. NPU-First Pipeline (OpenVINO GenAI)
- **OpenVINO 2026.0**: Optimized for Intel Core Ultra (NPU).
- **Graph Caching**: Pre-compiled hardware graphs enable sub-5s cold starts.
- **Dossier Memory**: ChromaDB RAG storage for persistent Commander context.

---

## ⚙️ Technical Requirements

- **OS**: Windows 11
- **Python**: 3.12 (Managed via `setup.ps1`)
- **Hardware**: Intel Core Ultra (NPU) or Intel Arc/iGPU (Vulkan)
- **Key Dependencies**: `pywebview`, `openvino-genai`, `chromadb`, `pydantic`.
