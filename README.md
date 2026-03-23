# Alliance Terminal v2

A privacy-focused, locally hosted AI assistant tailored to operate as a proactive, biologically aware scheduling coach. Styled loosely around the *Mass Effect* universe, the AI embodies the hyper-capable, polite persona of an English Butler, optimizing your calendar and tracking your sleep debt natively on edge hardware without sending a single byte of data to the cloud.

---

## 💻 Core Purpose

Modern Small Language Models (SLMs) on edge devices are phenomenal text parsers but incredibly unreliable mathematicians. Asking a 7B parameter AI to calculate calendar arrays across a 24-hour cycle often results in hallucinations (e.g., trying to schedule 25-hour days or dropping crucial tasks).

**The Alliance Terminal** solves this by fundamentally restricting the AI. We decoupled chronological math from the LLM and passed it into a strict mathematical Python constraint engine, allowing the AI to focus entirely on conversational guidance and semantic reasoning.

---

## 🧠 System Architecture & Design Choices

The architecture is built heavily around maximizing performance on Intel Core Ultra (iGPU) architectures while remaining aggressively battery-conscious.

### 1. Hardware Edge-Deployment Pipeline (OpenVINO)
To run a massive 15GB Language Model on a thin laptop, raw tensor processing using `llama.cpp` + Vulkan required unstable Python 3.12 custom wheel compilations. 
Instead, we pivoted the entire application stack to Intel's **OpenVINO** Toolkit. The `download_model.py` module natively ingests the raw `Qwen/Qwen2.5-7B-Instruct` safetensors and compresses them into a hyper-optimized `INT4` mathematical graph. 

Because OpenVINO is strictly tailored by Intel, it flawlessly shifts the 7B parameter model onto the Integrated GPU (`GPU.0`). This bypasses the CPU completely, achieving high token-generation speeds with drastically reduced battery consumption.

### 2. The Hybrid Constraint Solver
We replaced the chatbot's standard chronological awareness with a **Priority Bin-Packing Algorithm** (`mood_engine.py`). 
The AI evaluates your text, checks it against biological constraints, and emits **Semantic Intents** rather than firm schedules:
```json
{
  "intents": [
    { "type": "schedule", "action": "add_flexible", "activity": "Gaming Simulation", "duration": 120, "time_window": "evening", "priority": 3 }
  ]
}
```

The Python Engine then takes this intent and slots it mathematically into the day, avoiding human error entirely.

### 3. Biological Heuristics & Timeline Health
The backend considers holistic human health algorithms natively before attempting to schedule commands:
1. **Sleep Debt Tracking**: Python autonomously scans 24-hour rolling schedule cycles. If your sleep falls below the `7 hour` threshold, Python instantly tags you with "Sleep Debt" and automatically inserts a Priority-9 **Powernap** (or extends your next sleep window) into the calendar.
2. **Biological Meal Anchors**: Based on your wake-time, the Engine mathematically blocks out 3 major meals (Priority 8) and 2 flexible snacks (Priority 4). If your workload overflows the timeline, Python's bin-packing algorithm flags snacks to be quietly dropped.
3. **Deadlines & Dynamic Prioritization**: Every task has a floating priority score (1-10) and an optional deadline. As a deadline approaches the 3-hour mark, Python forcefully multiplies its priority vector, pushing other mundane tasks out of the queue to make room, while prompting the AI to actively flag the deadline to you in the user interface.
4. **Consent-Driven Overflows**: The constraint solver refuses to automatically delete uncompleted user-events. Instead, if a collision occurs, it passes an `[AT RISK OVERFLOW]` flag strictly back into the LLM's background context window. This triggers the AI to pause and politely ask you, in character: *"Commander, your agenda is saturated. May I delete 'Gaming' to ensure you meet your 8-hour sleep requirement?"*

---

## ⚙️ Installation & Boot Sequence

### Requirements
- **OS**: Windows 11
- **Silicon**: Intel Core Ultra (iGPU) or compatible architecture capable of processing OpenVINO pipelines.
- **Python**: `v3.12+`

### Configuration
1. **Clone & Setup Virtual Environment**
   ```bash
   git clone https://github.com/A-Ink/Assistant-v2.git
   cd Assistant-v2
   python -m venv .venv
   .\.venv\Scripts\activate
   ```

2. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```
   *(Note: The terminal requires `openvino`, `openvino-genai`, `transformers`, and `optimum-intel` securely isolated within the virtual environment).*

3. **Deploy the INT4 Core**
   We must transform the base Qwen language model into a format the iGPU can read. 
   Run:
   ```bash
   python download_model.py
   ```
   *This process will download approximately 15GB of raw weights from HuggingFace, apply INT4 quantization, and build the OpenVINO graph structure to your disk. This requires roughly 15-30 minutes pending CPU bandwidth and will require high RAM limits during compression.*

4. **Initialize Terminal UI**
   With the INT4 core established, boot the UI interface and AI backend node by running:
   ```bash
   python main.py
   ```

_The Alliance Terminal will immediately begin tracking your CPU/RAM diagnostics on screen, spin up the Chromium wrapper, and initialize the Qwen Core onto the iGPU backend natively._
