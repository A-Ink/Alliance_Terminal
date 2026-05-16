"""
Alliance Terminal — Fast-Path Regex Parser
Intercepts simple, unambiguous commands BEFORE hitting the AI backend.
Returns a fully-formed JSON result dict, or None if no match (falls through to AI).
"""

import re
import logging
from datetime import datetime, date, timedelta

log = logging.getLogger("normandy.fastpath")


def _parse_time(raw: str) -> str | None:
    """Normalize a time string to HH:MM. Returns None if unparseable."""
    raw = raw.strip().lower().replace(".", ":")

    # "3pm", "3:30pm", "15:00", "3:30 pm"
    m = re.match(r"^(\d{1,2}):?(\d{2})?\s*(am|pm)?$", raw)
    if not m:
        return None

    hour = int(m.group(1))
    minute = int(m.group(2) or 0)
    ampm = m.group(3)

    if ampm == "pm" and hour < 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0

    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return f"{hour:02d}:{minute:02d}"
    return None


def _date_ref(raw: str | None) -> str:
    """Parse 'today' / 'tomorrow' or default to 'today'."""
    if raw and "tomorrow" in raw.lower():
        return "tomorrow"
    return "today"


# ── Pattern definitions ─────────────────────────────────────────────────────

# "remind me to call mom at 3pm"
# "remind me at 3pm to call mom"
_REMIND_PATTERNS = [
    re.compile(
        r"^remind\s+me\s+to\s+(.+?)\s+at\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\s*(today|tomorrow)?$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^remind\s+me\s+at\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\s+to\s+(.+?)\s*(today|tomorrow)?$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^set\s+(?:a\s+)?reminder\s+(?:to\s+)?(.+?)\s+at\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\s*(today|tomorrow)?$",
        re.IGNORECASE,
    ),
]

# "add task study for math exam"
# "create task buy groceries"
_TASK_PATTERNS = [
    re.compile(
        r"^(?:add|create|new)\s+task\s+(.+)$",
        re.IGNORECASE,
    ),
]

# "schedule meeting at 2pm" / "schedule meeting at 2pm for 30 minutes"
_SCHED_PATTERNS = [
    re.compile(
        r"^schedule\s+(.+?)\s+at\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)"
        r"(?:\s+for\s+(\d+)\s*(?:min(?:ute)?s?|hrs?|hours?))?"
        r"\s*(today|tomorrow)?$",
        re.IGNORECASE,
    ),
]


def try_fast_path(user_message: str) -> dict | None:
    """
    Attempt to match the user message against known fast-path patterns.
    Returns a fully-formed result dict (same shape as AI output), or None.
    """
    msg = user_message.strip()
    if not msg:
        return None

    # ── Reminders ──────────────────────────────────────────────────────────
    for pat in _REMIND_PATTERNS:
        m = pat.match(msg)
        if m:
            groups = m.groups()
            # Pattern 1 & 3: (text, time, date?)
            # Pattern 2: (time, text, date?)
            if pat == _REMIND_PATTERNS[1]:
                time_raw, text, date_raw = groups
            else:
                text, time_raw, date_raw = groups

            parsed_time = _parse_time(time_raw)
            if not parsed_time:
                return None  # ambiguous time → let AI handle

            date_r = _date_ref(date_raw)
            log.info(f"[FAST-PATH] Matched reminder: '{text}' at {parsed_time} ({date_r})")
            return {
                "response": f"Reminder set: {text.strip()} at {parsed_time}.",
                "schedule_events": [],
                "tasks": [],
                "reminders": [{
                    "action": "create",
                    "reminder_text": text.strip(),
                    "remind_at": parsed_time,
                    "date_reference": date_r,
                }],
                "facts": [],
                "sleep_wake_update": {"sleep_time": None, "wake_time": None},
                "_fast_path": True,
            }

    # ── Tasks ──────────────────────────────────────────────────────────────
    for pat in _TASK_PATTERNS:
        m = pat.match(msg)
        if m:
            task_name = m.group(1).strip()
            if len(task_name) < 2:
                return None

            log.info(f"[FAST-PATH] Matched task: '{task_name}'")
            return {
                "response": f"Task added: {task_name}.",
                "schedule_events": [],
                "tasks": [{
                    "action": "create",
                    "task_name": task_name,
                    "duration_minutes": None,
                    "priority": 5,
                    "deadline": None,
                    "auto_schedule": True,
                }],
                "reminders": [],
                "facts": [],
                "sleep_wake_update": {"sleep_time": None, "wake_time": None},
                "_fast_path": True,
            }

    # ── Schedule Events ────────────────────────────────────────────────────
    for pat in _SCHED_PATTERNS:
        m = pat.match(msg)
        if m:
            event_name = m.group(1).strip()
            time_raw = m.group(2)
            dur_raw = m.group(3)
            date_raw = m.group(4) if len(m.groups()) > 3 else None

            parsed_time = _parse_time(time_raw)
            if not parsed_time:
                return None

            duration = int(dur_raw) if dur_raw else 60
            # Convert hours to minutes if the text said "hrs" or "hours"
            if dur_raw and re.search(r"hrs?|hours?", msg, re.IGNORECASE):
                duration = int(dur_raw) * 60

            date_r = _date_ref(date_raw)
            log.info(f"[FAST-PATH] Matched schedule: '{event_name}' at {parsed_time} for {duration}m")
            return {
                "response": f"Scheduled: {event_name} at {parsed_time} for {duration} minutes.",
                "schedule_events": [{
                    "action": "create",
                    "event_name": event_name,
                    "start_time_reference": parsed_time,
                    "end_time_reference": None,
                    "duration_minutes": duration,
                    "priority": 5,
                    "date_reference": date_r,
                    "auto_schedule": False,
                }],
                "tasks": [],
                "reminders": [],
                "facts": [],
                "sleep_wake_update": {"sleep_time": None, "wake_time": None},
                "_fast_path": True,
            }

    return None
