"""
Alliance Terminal — Main Entry Point
pywebview shell with Python↔JS API bridge, boot sequence, and proactive reminders.
"""

import json
import logging
import os
import sys
import threading
import time
from pathlib import Path
from datetime import date

import psutil
import webview

os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = "--proxy-server='direct://' --proxy-bypass-list=*"

# Ensure we can import from project root
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from ai_backend import AIBackend
from memory_manager import MemoryManager
from logic_engine import LogicEngine

# ---- Logging ----
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("normandy.main")

# ---- Globals ----
ai = AIBackend()
memory = MemoryManager()
logic = LogicEngine()
window = None
REMINDER_INTERVAL_SEC = 900  # 15 minutes


def _js_escape(s: str) -> str:
    """Escape a string for safe injection into a JS single-quoted literal."""
    return str(s).replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")


class Api:
    """
    Python↔JS bridge. All methods are callable from JavaScript as:
        window.pywebview.api.method_name(args)
    """

    def trigger_boot(self):
        """Trigger the async boot sequence from JS."""
        def delayed_boot():
            import time
            import traceback # <--- ADD THIS
            
            # Wait 0.2s for the JS bridge to stabilize (down from 1.0s)
            time.sleep(0.2) 
            
            try:
                initialize_backend()
            except Exception as e:
                # THIS WILL CATCH THE INVISIBLE CRASH
                log.error("=========================================")
                log.error(f"FATAL BOOT CRASH: {e}")
                log.error(traceback.format_exc())
                log.error("=========================================")
                
        # Target delayed_boot
        thread = threading.Thread(target=delayed_boot, daemon=True)
        thread.start()

    def send_message(self, text: str) -> dict:
        """Send user message to LLM, return response + extracted facts."""
        # Check for delete command
        try:
            # 1. THIS MUST BE AT THE VERY TOP OF THE TRY BLOCK
            if text.strip().lower().startswith("/forget"):
                target = text.strip()[7:].strip() 
                if memory.delete_fact(target):
                    return {"response": f"[DATA PURGED] {target}", "facts_saved": True, "schedule_updated": False}
                else:
                    return {"response": f"[FILE NOT FOUND] {target}", "facts_saved": False, "schedule_updated": False}

            # Get RAG context and Schedule Context
            relevant_facts = memory.query_relevant(text, n=5)
            codex_text = "\n".join(f"• {f}" for f in relevant_facts)
            schedule_text = logic.get_context_for_ai()
            
            # Combine them for the AI
            rag_context = f"{schedule_text}\n\n[DOSSIER FACTS]\n{codex_text}"

            def stream_callback(token):
                if window:
                    escaped = _js_escape(token.replace('\n', '<br>'))
                    try:
                        window.evaluate_js(f"if(window.streamToken) window.streamToken('{escaped}');")
                    except Exception:
                        pass

            # Synchronous generation with the new callback
            print("\n" + ">"*60)
            print(f" [USER MESSAGE] >> {text}")
            print(">"*60)

            response_html, facts, schedule_updates = ai._generate_sync(
                text, rag_context, stream_callback=stream_callback
            )

            # Save facts automatically
            facts_saved = False
            for fact_cmd in facts:
                memory.save_fact(fact_cmd.get("fact", ""), fact_cmd.get("category", "General Intel"))
                facts_saved = True

            # Process schedule updates (Routing JSON dicts)
            schedule_updated = False
            for cmd in schedule_updates:
                success = logic.execute_schedule_command(cmd)
                if success:
                    schedule_updated = True

            return {
                "response": response_html,
                "facts_saved": facts_saved,
                "schedule_updated": schedule_updated,
            }
        except Exception as e:
            log.error(f"send_message error: {e}")
            return {"error": str(e), "response": None,
                    "facts_saved": False, "schedule_updated": False}

    def get_dossier(self) -> str:
        """Get formatted HTML dossier (codex-style) from ChromaDB."""
        try:
            return memory.get_dossier_html()
        except Exception as e:
            log.error(f"get_dossier error: {e}")
            return ""

    def get_mood(self) -> str:
        """Get current mood prediction HTML."""
        try:
            return logic.get_mood_html()
        except Exception as e:
            log.error(f"get_mood error: {e}")
            return ""

    def get_schedule(self) -> str:
        """Get daily schedule HTML (merged defaults + user overrides)."""
        try:
            return logic.get_schedule_html()
        except Exception as e:
            log.error(f"get_schedule error: {e}")
            return ""

    def get_system_stats(self) -> dict:
        """Get system and app RAM usage."""
        try:
            vm = psutil.virtual_memory()
            proc = psutil.Process(os.getpid())
            app_bytes = proc.memory_info().rss
            app_mb = round(app_bytes / (1024 * 1024), 1)
            app_percent = round(app_bytes / vm.total * 100, 1)

            return {
                "system_percent": vm.percent,
                "app_mb": app_mb,
                "app_percent": app_percent,
            }
        except Exception as e:
            log.error(f"get_system_stats error: {e}")
            return {}

    def get_device_info(self) -> dict:
        """Get active model and device info."""
        try:
            return ai.get_device_info()
        except Exception:
            return {"model": "Loading...", "device": "..."}

    def save_memory(self, fact: str) -> bool:
        """Manually save a fact to the dossier."""
        try:
            memory.save_fact(fact)
            return True
        except Exception as e:
            log.error(f"save_memory error: {e}")
            return False

    def minimize_window(self):
        """Minimize the application window."""
        global window
        if window:
            window.minimize()

    def close_window(self):
        """Close the application."""
        global window
        if window:
            window.destroy()


def _boot_log(text: str, log_type: str = "info"):
    """Send a boot log line to the UI."""
    global window
    if window:
        escaped = _js_escape(text)
        try:
            window.evaluate_js(
                f"window.appendBootLine && window.appendBootLine('{escaped}', '{log_type}');"
            )
        except Exception:
            pass
    # Faster delays for snappier feel
    time.sleep(0.1)


def initialize_backend():
    """Initialize all subsystems with boot status updates to UI."""
    global window

    log.info("=" * 50)
    log.info("  ALLIANCE TERMINAL — Initializing")
    log.info("=" * 50)

    _boot_log("[BOOT] Alliance Terminal v2.1 — Boot Sequence Initiated", "info")
    _boot_log("[SYS ] Starfield renderer ............... ONLINE", "ok")

    # Initialize subsystems in parallel
    threads = []
    
    # AI Initialization
    _boot_log("[AI  ] Loading inference pipeline (Caching Enabled)...", "info")
    def init_ai():
        try:
            ai.initialize()
            _boot_log(f"[AI  ] Model: {ai.model_name}", "ok")
            _boot_log(f"[AI  ] Device: {ai.device_used} .................. ACTIVE", "ok")
        except Exception as e:
            _boot_log(f"[AI  ] Inference pipeline failed: {e}", "error")
    
    ai_thread = threading.Thread(target=init_ai)
    threads.append(ai_thread)
    ai_thread.start()

    # Memory Initialization
    _boot_log("[MEM ] Initializing memory core...", "info")
    def init_mem():
        try:
            memory.initialize()
            count = memory.collection.count() if memory.collection else 0
            _boot_log(f"[MEM ] Memory core ............... ONLINE ({count} facts)", "ok")
        except Exception as e:
            _boot_log(f"[MEM ] Memory init failed: {e}", "warn")
            
    mem_thread = threading.Thread(target=init_mem)
    threads.append(mem_thread)
    mem_thread.start()

    # Initialize logic engine (Synchronous as it is fast)
    _boot_log("[LOGIC] Zero-wake logic engine ............ ONLINE", "ok")
    today_str = date.today().isoformat()
    override_count = len(logic.schedule_db.get(today_str, []))
    if override_count > 0:
        _boot_log(f"[LOGIC] Loaded {override_count} schedule overrides", "info")

    # Wait for completion
    for t in threads:
        t.join()

    # Diagnostics
    _boot_log("[DIAG] System diagnostics ............... ONLINE", "ok")

    # Start reminder thread
    _boot_log("[REM ] Proactive reminder system ........ ARMED", "ok")
    reminder_thread = threading.Thread(target=_reminder_loop, daemon=True)
    reminder_thread.start()

    # Boot complete
    time.sleep(0.5)
    _boot_log("[BOOT] All systems initialized. Welcome aboard.", "ok")
    time.sleep(0.3)

    if window:
        try:
            window.evaluate_js("window.bootComplete && window.bootComplete();")
        except Exception:
            pass


def _reminder_loop():
    """Background loop that checks for proactive reminders every 15 minutes."""
    global window

    # Wait a bit after boot before first check
    time.sleep(60)

    while True:
        try:
            if window:
                reminders = logic.check_reminders()
                for reminder_html in reminders:
                    escaped = _js_escape(reminder_html)
                    try:
                        window.evaluate_js(
                            f"window.appendReminderMessage && "
                            f"window.appendReminderMessage('{escaped}');"
                        )
                    except Exception:
                        pass
        except Exception as e:
            log.error(f"Reminder check error: {e}")

        time.sleep(REMINDER_INTERVAL_SEC)


def main():
    global window

    ui_path = str(SCRIPT_DIR / "ui" / "index.html")

    log.info(f"UI path: {ui_path}")

    api = Api()

    window = webview.create_window(
        title="ALLIANCE TERMINAL",
        url=ui_path,
        js_api=api,
        width=1200,
        height=750,
        min_size=(600, 400),
        frameless=True,
        easy_drag=False,
        resizable=True,
        transparent=False,
        background_color="#020611",
    )

    log.info("Launching Alliance Terminal...")
    webview.start(debug=False, http_server=False)
    log.info("Application closed.")


if __name__ == "__main__":
    main()
