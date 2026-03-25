"""
Alliance Terminal — Robust Priority Constraint Engine
Pure Python constraint solver, biological anchoring, sleep debt calculation, and priority bin-packing.
"""

import json
import logging
import re
from datetime import date, datetime, timedelta
from pathlib import Path

log = logging.getLogger("normandy.mood")

SCRIPT_DIR = Path(__file__).parent
SCHEDULE_PATH = SCRIPT_DIR / "schedule_history.json"

# Time-of-day mood predictions with Mass Effect flavor
MOOD_TABLE = [
    (5, 8, "REVEILLE", "Groggy but rising. Cortisol levels normalizing.", "#00ccff"),
    (8, 12, "COMBAT READY", "Sharp and combat-ready. Peak cognitive function detected.", "#00ff88"),
    (12, 14, "REFUEL WINDOW", "Midday refuel window.", "#f2a900"),
    (14, 17, "PEAK OPS", "Afternoon operations phase.", "#00ff88"),
    (17, 20, "WIND DOWN", "Wind-down phase approaching.", "#f2a900"),
    (20, 23, "RECOVERY", "Recovery mode active. Low-intensity activities only.", "#00ccff"),
    (23, 5, "SLEEP CRITICAL", "Sleep cycle is CRITICAL. Every hour of lost sleep degrades performance by 15%.", "#ff0033")
]

class MoodEngine:
    def __init__(self, state_file="schedule_history.json"):
        self.state_file = Path(state_file)
        self.schedule_db = {}
        self.overflow_queue = [] # Consent-driven deletion buffer
        self._reminded_items = set()
        self._load_state()

    def _load_state(self):
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r') as f:
                    data = json.load(f)
                    # Core Data Migration Check: Erase old tuple arrays, support new dict-arrays
                    if isinstance(data, dict):
                        is_legacy = False
                        for day in data:
                            if data[day] and isinstance(data[day][0], (list, tuple)):
                                is_legacy = True
                                break
                        if is_legacy:
                            log.warning("Legacy tuple array detected. Wiping for dynamic priority dict migration.")
                            self.schedule_db = {}
                        else:
                            self.schedule_db = data
                    else:
                        self.schedule_db = {}
            except json.JSONDecodeError:
                self.schedule_db = {}
        else:
            self.schedule_db = {}

    def _save_state(self):
        with open(self.state_file, 'w') as f:
            json.dump(self.schedule_db, f, indent=2)

    def _init_day(self, target_date: str):
        if target_date not in self.schedule_db:
            self.schedule_db[target_date] = []
            self._anchor_meals(target_date)
            self._check_sleep_debt(target_date)

    def _anchor_meals(self, target_date: str):
        # Biological Hooks: 5 meals anchored around standard wake time.
        self._force_slot(8, 30, 45, "Breakfast", 8, target_date, "meal")
        self._force_slot(12, 30, 60, "Lunch", 8, target_date, "meal")
        self._force_slot(15, 30, 15, "Snack", 4, target_date, "meal")
        self._force_slot(19, 0, 60, "Dinner", 8, target_date, "meal")
        self._force_slot(22, 0, 15, "Supper", 4, target_date, "meal")

    def _check_sleep_debt(self, target_date: str):
        # Automatically inject Powernap if yesterday's sleep was highly truncated (< 7 hours)
        yest = (date.fromisoformat(target_date) - timedelta(days=1)).isoformat()
        if yest in self.schedule_db:
            sleep_duration = sum(t["duration"] for t in self.schedule_db[yest] if "sleep" in t["activity"].lower())
            if 0 < sleep_duration < (7 * 60):
                log.info(f"Sleep debt detected ({sleep_duration}m). Queuing Powernap.")
                self.queue_flexible("Powernap (Sleep Recovery)", 45, "afternoon", 9, target_date)

    def execute_schedule_command(self, cmd: dict) -> bool:
        """Master router for extracted AI entities (create/modify/delete)."""
        # Map new schema fields to internal terminology
        action = cmd.get("action", "create").lower()
        activity = cmd.get("label", cmd.get("activity", "Unknown Operation"))
        
        target_date = date.today().isoformat()
        if cmd.get("day", "today") == "tomorrow":
            target_date = (date.today() + timedelta(days=1)).isoformat()

        self._init_day(target_date)

        # Extraction-First logic: LLM provides raw data, Python decides the "how"
        duration = cmd.get("duration")
        priority = cmd.get("priority", 5)
        deadline = cmd.get("deadline", None)
        start_time_str = cmd.get("start_time")
        
        if action == "delete":
            # Remove from overflow queue natively if user consents via LLM
            search_act = str(activity).lower() if activity else ""
            self.overflow_queue = [o for o in self.overflow_queue if search_act in str(o.get("activity", "")).lower()]
            return self._delete_task(str(activity) if activity else "Unknown", target_date)
        
        elif action == "modify" or action == "update":
            # Search for existing task to modify
            search_name = str(cmd.get("original_name", activity or "")).lower()
            found = False
            for t in self.schedule_db.get(target_date, []):
                t_act = str(t.get("activity", "")).lower()
                if search_name in t_act or (activity and activity.lower() in t_act):
                    # Preserve old attributes if not provided in new extraction
                    duration = duration if duration is not None else t.get("duration", 60)
                    priority = priority if priority is not None else t.get("priority", 5)
                    start_time_str = start_time_str or f"{t.get('hour', 12):02d}:{t.get('minute', 0):02d}"
                    self._delete_task(str(t.get("activity", "")), target_date)
                    found = True
                    break
            
            if not found:
                log.warning(f"Modification target '{search_name}' not found. Defaulting to 'create'.")

        # Decide between hard-slotted (time provided) or flexible (no time provided)
        final_duration = int(duration) if duration is not None else 60
        final_deadline = str(deadline) if deadline is not None else ""
        final_activity = str(activity) if activity else "Unknown Operation"
        
        if start_time_str:
            h, m = self._parse_time(start_time_str)
            return self._force_slot(h, m, final_duration, final_activity, priority, target_date, "task", final_deadline)
        else:
            # Flexible placement
            return self.queue_flexible(final_activity, final_duration, str(cmd.get("time_window", "now")), priority, target_date, final_deadline)

    def _parse_time(self, t_str: str):
        match = re.search(r'(\d+):(\d+)', str(t_str))
        if match: return int(match.group(1)), int(match.group(2))
        return 12, 0

    def _delete_task(self, name: str, target_date: str):
        if target_date not in self.schedule_db: return False
        b_len = len(self.schedule_db[target_date])
        self.schedule_db[target_date] = [t for t in self.schedule_db[target_date] if name.lower() not in t["activity"].lower()]
        self._save_state()
        return len(self.schedule_db[target_date]) < b_len

    def _force_slot(self, h: int, m: int, dur: int, act: str, pri: int, target_date: str, t_type: str = "task", deadline: str = "") -> bool:
        """Hard locks events, mathematically ripping out lower-priority events to clear space and tracking Overflows."""
        nm = h * 60 + m
        ne = nm + dur

        survivors = []
        for t in self.schedule_db[target_date]:
            sm = t["hour"] * 60 + t["minute"]
            se = sm + t["duration"]
            
            # Check for overlapping frames
            if not (ne <= sm or nm >= se):
                if t["priority"] < pri:
                    log.warning(f"Collision: Evicting {t['activity']} (P{t['priority']}) in favor of {act} (P{pri}). Flagged Overflow.")
                    self.overflow_queue.append(t)
                else:
                    log.error(f"Collision: Cannot slot {act} (P{pri}) over higher importance {t['activity']} (P{t['priority']}). Dropped.")
                    return False # High priority constraint blocks placement entirely
            else:
                survivors.append(t)
        
        survivors.append({
            "hour": h, "minute": m, "duration": dur, "activity": act, 
            "priority": pri, "type": t_type, "deadline": deadline
        })
        # Sort chronologically
        survivors.sort(key=lambda x: x["hour"] * 60 + x["minute"])
        self.schedule_db[target_date] = survivors
        self._save_state()
        return True

    def queue_flexible(self, act: str, dur: int, window: str, pri: int, target_date: str, deadline: str = "") -> bool:
        """Standard Bin Packing Algorithm checking flexible gap potentials."""
        w_start, w_end = 8*60, 22*60
        window = str(window).lower()
        if "morning" in window: w_end = 12*60
        elif "afternoon" in window: w_start, w_end = 12*60, 17*60
        elif "evening" in window: w_start, w_end = 17*60, 22*60
        elif "now" in window and target_date == date.today().isoformat():
            w_start = datetime.now().hour * 60 + datetime.now().minute

        blocks = []
        for t in self.schedule_db[target_date]:
            sm = t["hour"] * 60 + t["minute"]
            se = sm + t["duration"]
            blocks.append((sm, se))
        blocks.sort()

        found = -1
        current = w_start
        while current + dur <= w_end:
            collision = False
            for bs, be in blocks:
                if not (current + dur <= bs or current >= be):
                    collision = True
                    current = be
                    break
            if not collision:
                found = current
                break
        
        if found != -1:
            h, m = found // 60, found % 60
            return self._force_slot(h, m, dur, act, pri, target_date, "task", deadline)
        else:
            log.warning(f"No gap found for flexible schedule. Evicted loosely: {act}")
            self.overflow_queue.append({"activity": act, "duration": dur, "priority": pri})
            return False

    def check_reminders(self) -> list:
        now = datetime.now()
        reminders = []
        todays = self.schedule_db.get(date.today().isoformat(), [])
        now_m = now.hour * 60 + now.minute
        
        for t in todays:
            sm = t["hour"] * 60 + t["minute"]
            
            # Dynamic Priority Scaling based on Deadline Vectors
            if t["deadline"]:
                try:
                    dt = datetime.fromisoformat(t["deadline"])
                    secs = (dt - now).total_seconds()
                    if 0 < secs < 10800: # Final 3 hours!
                        t["priority"] = min(10, t["priority"] + 4) 
                except: pass

            diff = sm - now_m
            ek = f"{t['hour']}:{t['minute']}:{t['activity']}"
            if ek not in self._reminded_items:
                if 0 < diff <= 10:
                    self._reminded_items.add(ek)
                    reminders.append(f"Heads up — <b>{t['activity']}</b> begins at <b>{t['hour']:02d}:{t['minute']:02d}</b>. That's in {diff} minutes.")
        return reminders

    def get_context_for_ai(self) -> str:
        """Injects system conditions directly into the LLM logic layer for persona responses."""
        now = datetime.now()
        h = f"LOCAL SYSTEM TIME: {now.strftime('%H:%M')} | DATE: {now.strftime('%Y-%m-%d')}\n"
        td = date.today().isoformat()
        
        self._init_day(td)

        lines = ["[ACTIVE SCHEDULE]"]
        for t in self.schedule_db.get(td, []):
            dp = f"(Deadline: {t['deadline']})" if t['deadline'] else ""
            lines.append(f"- {t['hour']:02d}:{t['minute']:02d} ({t['duration']}m): {t['activity']} [Pri:{t['priority']}] {dp}")
        
        if self.overflow_queue:
            lines.append("\n[AT RISK OVERFLOW TASKS - AWAITING COMMANDER'S CONSENT TO DELETE]")
            for o in self.overflow_queue:
                lines.append(f"- {o['activity']} ({o.get('duration', 0)}m) [Pri:{o.get('priority', 5)}]")
        
        return h + "\n".join(lines)

    def get_mood(self) -> dict:
        h = datetime.now().hour
        for s, e, l, d, c in MOOD_TABLE:
            if s < e and s <= h < e: return {"label": l, "description": d, "color": c, "hour": h}
            elif s > e and (h >= s or h < e): return {"label": l, "description": d, "color": c, "hour": h}
        return {"label": "NOMINAL", "description": "Systems nominal.", "color": "#00b4ff", "hour": h}

    def get_mood_html(self) -> str:
        mood = self.get_mood()
        time_str = datetime.now().strftime("%H:%M")
        return (
            f"<div style='padding: 10px; margin-bottom: 8px; border-left: 3px solid {mood['color']}; "
            f"background: rgba(0,40,80,0.15);'>"
            f"<div style='font-family: Orbitron, sans-serif; font-size: 11px; color: {mood['color']}; letter-spacing: 2px; margin-bottom: 6px;'>"
            f"STATUS: {mood['label']}</div>"
            f"<div style='font-family: Montserrat, sans-serif; font-size: 12px; color: #c0d0e0; line-height: 1.5;'>"
            f"{mood['description']}</div>"
            f"<div style='font-family: Orbitron, sans-serif; font-size: 9px; color: #445566; margin-top: 6px;'>"
            f"LOCAL TIME: {time_str}</div></div>"
        )

    def get_schedule_html(self) -> str:
        tasks = self.schedule_db.get(date.today().isoformat(), [])
        if not tasks: return "<div class='schedule-entry' style='color: #4a5568;'>[NO OPERATIONS SCHEDULED]</div>"
        
        parts = []
        now = datetime.now()
        now_m = now.hour * 60 + now.minute
        for t in tasks:
            sm = t["hour"] * 60 + t["minute"]
            curr = " current" if sm <= now_m < sm + t["duration"] else ""
            ts = f"[{t['hour']:02d}{t['minute']:02d}]"
            
            # Flag high-priority elements that are near deadline
            pri_color = "#ff4400" if t["priority"] >= 9 else "#4a5568"
            
            parts.append(f"<div class='schedule-entry{curr}'>"
                         f"<span style='color: var(--cyan-bright); margin-right: 8px; font-family: monospace;'>{ts}</span>"
                         f"<span>{t['activity']}</span>"
                         f"<span style='color: {pri_color}; font-size: 0.85em; margin-left: 5px;'>({t['duration']}m)</span>"
                         f"</div>")
        return "".join(parts)