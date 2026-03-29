"""
Alliance Terminal Version 3 — Background Workers (QThread)
All heavy work runs inside a single QThread per worker to avoid nested-thread crashes.
"""

import time
import logging
from PyQt6.QtCore import QThread, pyqtSignal

log = logging.getLogger("normandy.workers")


class AiWorker(QThread):
    """Runs AI generation in a background thread, emitting tokens as they arrive."""

    token_streamed   = pyqtSignal(str)
    generation_done  = pyqtSignal(dict)
    generation_error = pyqtSignal(str)

    def __init__(self, ai, memory, logic, text: str, parent=None):
        super().__init__(parent)
        self._ai     = ai
        self._memory = memory
        self._logic  = logic
        self._text   = text

    def run(self):
        try:
            relevant_facts = self._memory.query_relevant(self._text, n=5)
            codex_text     = "\n".join(f"• {f}" for f in relevant_facts)
            schedule_text  = self._logic.get_context_for_ai()
            rag_context    = f"{schedule_text}\n\n[DOSSIER FACTS]\n{codex_text}"

            def stream_cb(token: str):
                self.token_streamed.emit(token.replace('\n', '<br>'))

            response_html, facts, schedule_updates, tasks_updates, reminders_updates, sleep_wake = \
                self._ai._generate_sync(self._text, rag_context, stream_callback=stream_cb)

            facts_saved = False
            for fc in facts:
                self._memory.save_fact(fc.get("fact", ""), fc.get("category", "General Intel"))
                facts_saved = True

            if sleep_wake:
                self._logic.process_sleep_wake_update(sleep_wake)

            schedule_updated = False
            for cmd in schedule_updates:
                if self._logic.execute_schedule_command(cmd):
                    schedule_updated = True

            tasks_updated = False
            for t in tasks_updates:
                if self._logic.execute_task_command(t):
                    tasks_updated = True

            reminders_updated = False
            for r in reminders_updates:
                if self._logic.execute_reminder_command(r):
                    reminders_updated = True

            self.generation_done.emit({
                "response":           response_html,
                "facts_saved":        facts_saved,
                "schedule_updated":   schedule_updated or bool(sleep_wake),
                "tasks_updated":      tasks_updated,
                "reminders_updated":  reminders_updated,
            })

        except Exception as e:
            log.error(f"AiWorker error: {e}", exc_info=True)
            self.generation_error.emit(str(e))


class DiagnosticsWorker(QThread):
    """Polls RAM stats every N seconds and emits the result."""

    stats_ready = pyqtSignal(dict)

    def __init__(self, interval_sec: int = 5, parent=None):
        super().__init__(parent)
        self._interval = interval_sec
        self._running  = True

    def run(self):
        import psutil
        import os
        while self._running:
            try:
                vm        = psutil.virtual_memory()
                proc      = psutil.Process(os.getpid())
                app_bytes = proc.memory_info().rss
                app_mb    = round(app_bytes / (1024 * 1024), 1)
                app_pct   = round(app_bytes / vm.total * 100, 1)
                self.stats_ready.emit({
                    "system_percent": vm.percent,
                    "app_mb":         app_mb,
                    "app_percent":    app_pct,
                })
            except Exception as e:
                log.warning(f"Diagnostics poll error: {e}")
            # Use a short-sleep loop so we can stop cleanly
            for _ in range(self._interval * 10):
                if not self._running:
                    return
                time.sleep(0.1)

    def stop(self):
        self._running = False


class ReminderWorker(QThread):
    """Checks for proactive reminders periodically."""

    reminder_ready = pyqtSignal(str)

    def __init__(self, logic, interval_sec: int = 900, parent=None):
        super().__init__(parent)
        self._logic    = logic
        self._interval = interval_sec
        self._running  = True

    def run(self):
        # Wait 2 minutes before first proactive check
        for _ in range(120 * 10):
            if not self._running:
                return
            time.sleep(0.1)

        while self._running:
            try:
                for html in self._logic.check_reminders():
                    self.reminder_ready.emit(html)
            except Exception as e:
                log.warning(f"Reminder check error: {e}")
            for _ in range(self._interval * 10):
                if not self._running:
                    return
                time.sleep(0.1)

    def stop(self):
        self._running = False


class BootWorker(QThread):
    """
    Cosmetic boot replay worker.
    The actual backends were initialized on the main thread before Qt started.
    This worker just replays the pre-recorded log lines with drama delays.
    """

    log_line  = pyqtSignal(str, str)   # (text, type: info|ok|warn|error)
    boot_done = pyqtSignal()

    def __init__(self, boot_log: list, parent=None):
        super().__init__(parent)
        # boot_log is a list of (text, kind) tuples from main.py's _init_backends()
        self._boot_log = boot_log

    def run(self):
        # Replay each line with a small delay for visual effect
        for text, kind in self._boot_log:
            self.log_line.emit(text, kind)
            time.sleep(0.06)
        time.sleep(0.4)
        self.boot_done.emit()
