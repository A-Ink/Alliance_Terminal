"""
Alliance Terminal — Advanced Logic & Cognitive Engine
Implements biological constraints, ripple rescheduling (eviction/re-packing), 
deadline gravity, and cognitive load balancing.
"""

import json
import logging
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Any, Literal, Tuple
from pydantic import BaseModel, Field

log = logging.getLogger("normandy.logic")

# Configuration & Paths
SCRIPT_DIR = Path(__file__).parent
SCHEDULE_PATH = SCRIPT_DIR / "schedule.json"

# --- PYDANTIC SCHEMAS (Extraction Layer Interface) ---

class UserIntent(BaseModel):
    action: Literal["create", "modify", "delete"] = Field("create", description="Operation to perform.")
    intent_type: Literal["fixed_event", "floating_task", "status_update"] = Field(
        description="'fixed_event' for rigid times. 'floating_task' for flexible chores. 'status_update' for sleep/wake/energy."
    )
    event_name: str
    start_time_reference: Optional[str] = Field(None, description="e.g., 'now', '9am', '14:00'.")
    end_time_reference: Optional[str] = Field(None, description="e.g., '11pm'.")
    duration_minutes: Optional[int] = Field(None, description="Inferred duration.")
    priority: int = Field(5, ge=1, le=10, description="Priority scale 1-10.")
    deadline: Optional[str] = Field(None, description="ISO format deadline string.")
    date_reference: Optional[str] = Field(None, description="e.g., 'today', 'tomorrow'. Specific dates also supported.")
    auto_schedule: bool = Field(
        False,
        description="If True, engine picks the next valid slot (energy/gaps); do not rely on start_time_reference for placement.",
    )

class ParsedInput(BaseModel):
    intents: List[UserIntent]

# --- CORE LOGIC ENGINE ---

class LogicEngine:
    def __init__(self, state_file: str = "schedule.json"):
        self.state_file = Path(SCRIPT_DIR / state_file)
        self.schedule_db: Dict[str, List[Dict[str, Any]]] = {}
        self.tasks_db: List[Dict[str, Any]] = []          # NEW: flexible tasks
        self.reminders_db: List[Dict[str, Any]] = []      # NEW: user reminders
        self.overflow_queue: List[Dict[str, Any]] = []
        self.pending_deep_thought_queue: List[Dict[str, Any]] = []  # Deferral queue for dGPU
        self.user_state: Dict[str, Any] = {                         # Proactive micro-interaction state
            "sleep_quality": None,
            "energy_level": None,
            "mood": None,
            "goals_today": [],
            "last_meal": None,
            "collected_at": None,
        }
        self.user_energy: int = 100
        self._suppress_anchors = False                    # NEW: avoid re-injection during shifts
        self._last_proactive_time: float = 0.0            # NEW: proactive cooldown tracking
        self._load_state()

    def _load_state(self):
        """Loads persistent JSON state."""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r') as f:
                    data = json.load(f)
                    if isinstance(data, dict) and "schedules" in data:
                        self.schedule_db  = data["schedules"]
                        self.user_energy  = data.get("user_energy", 100)
                        self.tasks_db     = data.get("tasks", [])
                        self.reminders_db = data.get("reminders", [])
                        self.pending_deep_thought_queue = data.get("pending_deep_thought_queue", [])
                        self.user_state = data.get("user_state", self.user_state)
                    else:
                        self.schedule_db  = data
                        self.user_energy  = 100
            except (json.JSONDecodeError, IOError):
                self.schedule_db = {}
        else:
            self.schedule_db = {}

    def _save_state(self):
        """Saves current state to disk."""
        data = {
            "schedules":  self.schedule_db,
            "user_energy": self.user_energy,
            "tasks":      self.tasks_db,
            "reminders":  self.reminders_db,
            "pending_deep_thought_queue": self.pending_deep_thought_queue,
            "user_state":  self.user_state,
        }
        with open(self.state_file, 'w') as f:
            json.dump(data, f, indent=2)

    # ── Deferral Queue (Phase 2) ──────────────────────────────────────────────

    def enqueue_deferred(self, user_prompt: str, rag_context: str = ""):
        """
        Save a prompt to the deferral queue for later dGPU processing.
        Called when the NPU sets requires_deep_thought: true.
        """
        entry = {
            "prompt": user_prompt,
            "rag_context": rag_context,
            "queued_at": datetime.now().isoformat(),
        }
        self.pending_deep_thought_queue.append(entry)
        self._save_state()
        log.info(f"[DEFER] Queued prompt for dGPU processing: '{user_prompt[:60]}...'")

    def drain_deferred_queue(self) -> List[Dict[str, Any]]:
        """
        Retrieve and clear all pending deferred prompts.
        Called by the orchestrator when AC power is restored and dGPU is ready.
        """
        items = list(self.pending_deep_thought_queue)
        self.pending_deep_thought_queue.clear()
        self._save_state()
        if items:
            log.info(f"[DEFER] Drained {len(items)} deferred prompt(s) for dGPU processing.")
        return items

    @property
    def has_deferred_prompts(self) -> bool:
        return len(self.pending_deep_thought_queue) > 0

    # ── User State Updates (Phase 3) ──────────────────────────────────────────

    def update_user_state(self, **kwargs):
        """Update user_state fields from micro-interaction responses."""
        for key, value in kwargs.items():
            if key in self.user_state and value is not None:
                self.user_state[key] = value
        self.user_state["collected_at"] = datetime.now().isoformat()
        self._save_state()
        log.info(f"[STATE] User state updated: {kwargs}")

    # ── Schedule Sanity Checker (Phase 3) ─────────────────────────────────────

    def validate_schedule_sanity(self, date_str: str) -> List[str]:
        """
        Validate today's schedule for biological and temporal coherence.
        Returns a list of human-readable warning strings (empty = all OK).
        Only runs on dGPU boot or AC power restore.
        """
        day_tasks = self.schedule_db.get(date_str, [])
        if not day_tasks:
            return []

        warnings: List[str] = []
        valid_tasks = [t for t in day_tasks if "start_time" in t]
        sorted_tasks = sorted(valid_tasks, key=lambda t: self._time_to_minutes(t["start_time"]))

        # Extract key biological anchors
        wake_ev = next((t for t in sorted_tasks if "wake" in t.get("activity", "").lower()), None)
        sleep_ev = next((t for t in sorted_tasks if t.get("type") == "sleep"), None)
        breakfast = next((t for t in sorted_tasks if "breakfast" in t.get("activity", "").lower()), None)
        lunch = next((t for t in sorted_tasks if "lunch" in t.get("activity", "").lower()), None)
        dinner = next((t for t in sorted_tasks if "dinner" in t.get("activity", "").lower()), None)

        wake_m = self._time_to_minutes(wake_ev["start_time"]) if wake_ev else None
        sleep_m = self._time_to_minutes(sleep_ev["start_time"]) if sleep_ev else None
        breakfast_m = self._time_to_minutes(breakfast["start_time"]) if breakfast else None
        lunch_m = self._time_to_minutes(lunch["start_time"]) if lunch else None
        dinner_m = self._time_to_minutes(dinner["start_time"]) if dinner else None

        # 1. Breakfast before wake time
        if wake_m is not None and breakfast_m is not None:
            if breakfast_m < wake_m:
                warnings.append(
                    f"Breakfast ({breakfast['start_time']}) is scheduled before wake time "
                    f"({wake_ev['start_time']}). This is physically impossible."
                )

        # 2. Meal ordering: Breakfast < Lunch < Dinner
        if breakfast_m is not None and lunch_m is not None and lunch_m <= breakfast_m:
            warnings.append(
                f"Lunch ({lunch['start_time']}) is scheduled at or before Breakfast "
                f"({breakfast['start_time']}). Meals are out of order."
            )
        if lunch_m is not None and dinner_m is not None and dinner_m <= lunch_m:
            warnings.append(
                f"Dinner ({dinner['start_time']}) is scheduled at or before Lunch "
                f"({lunch['start_time']}). Meals are out of order."
            )
        if breakfast_m is not None and dinner_m is not None and dinner_m <= breakfast_m:
            warnings.append(
                f"Dinner ({dinner['start_time']}) is scheduled at or before Breakfast "
                f"({breakfast['start_time']}). Extreme meal ordering issue."
            )

        # 3. Activities during sleep window
        if sleep_m is not None and wake_m is not None:
            # Normal case: sleep at night, wake in morning (sleep_m > wake_m means cross-midnight)
            for t in sorted_tasks:
                if t.get("type") in ("sleep", "biological"):
                    continue  # Skip sleep/wake anchors themselves
                t_m = self._time_to_minutes(t["start_time"])
                # Cross-midnight sleep: e.g. sleep at 23:00, wake at 08:00
                if sleep_m > wake_m:
                    # Sleep window: sleep_m..midnight..wake_m
                    if t_m >= sleep_m or t_m < wake_m:
                        warnings.append(
                            f"'{t['activity']}' at {t['start_time']} is scheduled during "
                            f"the sleep window ({sleep_ev['start_time']}–{wake_ev['start_time']})."
                        )
                else:
                    # Same-day: sleep_m < wake_m (unusual but handle it)
                    if sleep_m < t_m < wake_m:
                        warnings.append(
                            f"'{t['activity']}' at {t['start_time']} is scheduled during "
                            f"the sleep window ({sleep_ev['start_time']}–{wake_ev['start_time']})."
                        )

        # 4. Unrealistic wake time (before 4am unless user is a night worker)
        if wake_m is not None and wake_m < 240 and wake_m > 0:  # 0:01 to 3:59
            warnings.append(
                f"Wake time is set to {wake_ev['start_time']} which is unusually early. "
                f"Please confirm this is correct."
            )

        # 5. Overlapping events (non-sleep, non-biological)
        active_tasks = [t for t in sorted_tasks if t.get("type") not in ("sleep", "biological")]
        for i in range(len(active_tasks) - 1):
            a = active_tasks[i]
            b = active_tasks[i + 1]
            a_start = self._time_to_minutes(a["start_time"])
            a_end = a_start + a.get("duration", 0)
            b_start = self._time_to_minutes(b["start_time"])
            if b_start < a_end:
                warnings.append(
                    f"'{a['activity']}' ({a['start_time']}–{a_end // 60:02d}:{a_end % 60:02d}) "
                    f"overlaps with '{b['activity']}' at {b['start_time']}."
                )

        # 6. Excessively long events (> 8 hours for non-sleep)
        for t in sorted_tasks:
            dur = t.get("duration", 0)
            if dur > 480 and t.get("type") != "sleep":
                warnings.append(
                    f"'{t['activity']}' has a duration of {dur} minutes ({dur // 60}h {dur % 60}m). "
                    f"This seems unusually long."
                )

        if warnings:
            log.info(f"[SANITY] {len(warnings)} anomaly(s) found for {date_str}")
        return warnings

    # ── GPU Context Payload (Phase 3) ─────────────────────────────────────────

    def get_gpu_context_payload(self) -> str:
        """
        Assemble a rich context payload for the dGPU that includes:
        - User state (sleep quality, energy, mood, goals)
        - Full schedule with biological annotations
        - Sanity warnings
        - Sleep debt
        """
        now = datetime.now()
        today_str = now.date().isoformat()
        self._init_day(today_str)

        lines = [
            f"SYSTEM TIME: {now.strftime('%H:%M')}",
            f"SYSTEM DATE: {today_str}",
            "",
            "[GPU CONTEXT — DEEP ANALYSIS PAYLOAD]",
        ]

        # User state
        us = self.user_state
        state_items = []
        if us.get("sleep_quality"):
            state_items.append(f"Sleep quality: {us['sleep_quality']}")
        if us.get("energy_level") is not None:
            state_items.append(f"Energy level: {us['energy_level']}/10")
        if us.get("mood"):
            state_items.append(f"Mood: {us['mood']}")
        if us.get("goals_today"):
            state_items.append(f"Goals: {', '.join(us['goals_today'])}")
        if us.get("last_meal"):
            state_items.append(f"Last meal: {us['last_meal']}")

        if state_items:
            lines.append("\n[USER STATE — Collected via micro-interactions]")
            for item in state_items:
                lines.append(f"  - {item}")
        else:
            lines.append("\n[USER STATE] No user state data collected yet.")

        # Sleep debt
        debt_mins = self._calculate_sleep_debt(today_str)
        if debt_mins > 0:
            lines.append(f"\n[BIOMEDICAL] SLEEP DEBT: {debt_mins}m deficit.")

        # Sanity warnings
        sanity = self.validate_schedule_sanity(today_str)
        if sanity:
            lines.append("\n[SCHEDULE ANOMALIES — Requires Commander Confirmation]")
            for w in sanity:
                lines.append(f"  ⚠ {w}")

        # Full schedule
        lines.append("\n[TODAY'S OPERATIONS SCHEDULE]")
        day_tasks = self.schedule_db.get(today_str, [])
        valid_tasks = [t for t in day_tasks if "start_time" in t]
        for t in sorted(valid_tasks, key=lambda x: x['start_time']):
            status = " [DONE]" if t.get('completed') else ""
            ph = " [UNCONFIRMED]" if t.get('is_placeholder') else ""
            lines.append(
                f"  - {t['start_time']} ({t.get('duration', '?')}m) "
                f"[P{t.get('priority', 5)}] [{t.get('type', 'task')}]: "
                f"{t['activity']}{status}{ph}"
            )

        # Pending tasks
        if self.tasks_db:
            active_tasks = [t for t in self.tasks_db if not t.get("completed")]
            if active_tasks:
                lines.append("\n[PENDING TASKS]")
                for t in active_tasks:
                    lines.append(
                        f"  - {t.get('name', '?')} [P{t.get('priority', 5)}] "
                        f"Deadline: {t.get('deadline', 'none')}"
                    )

        return "\n".join(lines)

    def _calculate_current_energy(self) -> Dict[str, Any]:
        """
        Synthesizes energy score (clamped 15-100) from biological factors.
        ONLY considers PAST events — future schedule does not affect current fatigue.

        Factors:
          1. Circadian decay (time awake since wake anchor)
          2. Sleep debt penalty (-5 per hour of deficit)
          3. Sleep consistency (wake time variance over past 3 days)
          4. Mental work drain (study, classes, exams, coding, socializing)
          5. Recovery boosts (recreational activities, snacks, naps)
          6. Post-lunch circadian dip (13:00-15:30)
          7. Post-meal metabolic dip
        """
        now = datetime.now()
        today_str = now.date().isoformat()
        day_tasks = self.schedule_db.get(today_str, [])
        now_m = now.hour * 60 + now.minute
        penalties = []

        # ── 1. Base Circadian Decay (time-since-wake) ──
        wake = next((t for t in day_tasks if "wake" in t.get('activity', '').lower()), None)
        sleep = next((t for t in day_tasks if t.get('type') == 'sleep'), None)

        wake_m = self._time_to_minutes(wake['start_time']) if wake else 420
        sleep_m = self._time_to_minutes(sleep['start_time']) if sleep else 1380

        if sleep_m <= wake_m:
            sleep_m += 1440  # Cross-midnight
        total_awake = max(sleep_m - wake_m, 60)

        calc_now_m = now_m + 1440 if now_m < wake_m and now.hour < 5 else now_m
        current_awake = calc_now_m - wake_m

        if current_awake < 0:
            score = 100.0
        elif current_awake >= total_awake:
            score = 15.0
        else:
            score = 100.0 - (current_awake / total_awake) * 85.0

        # ── 2. Sleep Debt Penalty (-5 per hour of deficit) ──
        debt_mins = self._calculate_sleep_debt(today_str)
        if debt_mins > 0:
            debt_penalty = round((debt_mins / 60) * 5, 1)
            score -= debt_penalty
            if debt_penalty > 0:
                penalties.append(f"Sleep Debt: -{debt_penalty}")

        # ── 3. Sleep Consistency (wake time variance over past 3 days) ──
        from datetime import timedelta as _td
        wake_times_m = []
        for d_offset in range(0, 4):
            d_str = (now.date() - _td(days=d_offset)).isoformat()
            d_tasks = self.schedule_db.get(d_str, [])
            w_ev = next((t for t in d_tasks if "wake" in t.get('activity', '').lower()), None)
            if w_ev and "start_time" in w_ev:
                wake_times_m.append(self._time_to_minutes(w_ev['start_time']))
        if len(wake_times_m) >= 3:
            avg_wake = sum(wake_times_m) / len(wake_times_m)
            variance = sum(abs(w - avg_wake) for w in wake_times_m) / len(wake_times_m)
            if variance > 90:  # > 1.5 hours average deviation
                pen = min(15, round(variance / 10))
                score -= pen
                penalties.append(f"Irregular Sleep: -{pen}")

        # ── Activity classification keywords ──
        DRAIN_KEYWORDS = [
            "study", "exam", "code", "coding", "math", "logic", "analysis",
            "project", "writing", "research", "lecture", "seminar", "class",
            "tutorial", "lab", "assignment", "homework", "revision",
            "meeting", "interview", "presentation", "social", "call",
            "group", "discussion", "conference",
        ]
        RECOVERY_KEYWORDS = [
            "game", "gaming", "play", "read", "reading", "book", "music",
            "listen", "walk", "exercise", "workout", "yoga", "meditat",
            "relax", "break", "rest", "tv", "watch", "movie", "netflix",
            "youtube", "chill", "hobby",
        ]

        # ── 4. Mental Work Drain (ONLY past/completed activities) ──
        drain = 0.0
        for t in day_tasks:
            if "start_time" not in t:
                continue
            st = self._time_to_minutes(t['start_time'])
            end_m = st + t.get('duration', 0)
            # Only count tasks that have STARTED (not future ones)
            if st >= now_m:
                continue
            # Calculate actual elapsed time (not full duration if still ongoing)
            actual_duration = min(t.get('duration', 0), now_m - st)
            activity = t.get('activity', '').lower()
            if any(k in activity for k in DRAIN_KEYWORDS):
                task_drain = round((actual_duration / 60) * 12, 1)
                drain += task_drain

        if drain > 0:
            score -= drain
            penalties.append(f"Mental Load: -{drain}")

        # ── 5. Recovery Boosts (ONLY past/completed activities) ──
        recovery = 0.0
        for t in day_tasks:
            if "start_time" not in t:
                continue
            st = self._time_to_minutes(t['start_time'])
            end_m = st + t.get('duration', 0)
            # Only count completed recreational blocks
            if end_m > now_m:
                continue
            activity = t.get('activity', '').lower()
            if any(k in activity for k in RECOVERY_KEYWORDS):
                boost = round((t.get('duration', 0) / 60) * 8, 1)
                recovery += boost
            elif "snack" in activity:
                recovery += 12
            elif "powernap" in activity or "nap" in activity:
                recovery += 25

        if recovery > 0:
            score += recovery
            penalties.append(f"Recovery: +{recovery}")

        # ── 6. Post-Lunch Circadian Dip (13:00-15:30) ──
        if 780 <= now_m <= 930:  # 13:00-15:30
            dip = 8
            score -= dip
            penalties.append(f"Afternoon Dip: -{dip}")

        # ── 7. Post-Meal Metabolic Dip ──
        for t in day_tasks:
            if t.get('type') != "meal":
                continue
            act = t.get('activity', '').lower()
            meal_start = self._time_to_minutes(t['start_time'])
            meal_end = meal_start + t.get('duration', 0)
            # Only apply if meal has ENDED
            if meal_end > now_m:
                continue
            if "lunch" in act and now_m < meal_end + 90:
                score -= 15
                penalties.append("Post-Lunch Dip: -15")
            elif "dinner" in act and now_m < meal_end + 60:
                score -= 8
                penalties.append("Post-Dinner Dip: -8")

        # Clamp and round
        score = round(max(15.0, min(100.0, score)), 1)

        # Status label
        if score >= 80:
            status = "EXCELLENT"
        elif score >= 55:
            status = "NOMINAL"
        elif score >= 35:
            status = "DEGRADED"
        elif score >= 20:
            status = "CRITICAL"
        else:
            status = "EXHAUSTED"

        return {"score": score, "status": status, "penalties": penalties}

    def adjust_sleep_if_awake(self) -> bool:
        """
        Shifts Sleep time to 10 mins from now if the user interacts with the terminal during scheduled Sleep.
        Bypasses AI to prevent infinite hallucination loops.
        """
        now = datetime.now()
        target_date = now.date().isoformat()
        now_m = now.hour * 60 + now.minute
        
        # Pull today's Wake anchor to find our morning chronological limit
        day_tasks = self.schedule_db.get(target_date, [])
        wake_ev = next((t for t in day_tasks if "wake" in t.get("activity", "").lower()), None)
        wake_m = self._time_to_minutes(wake_ev['start_time']) if wake_ev else 420
        
        # Crucial Fix: If it is currently Before Wake (e.g. 03:00 AM), our "Active" sleep period actually started YESTERDAY
        sleep_date = target_date
        if now_m < wake_m:
            sleep_date = (now - timedelta(days=1)).date().isoformat()
            
        sleep_tasks = self.schedule_db.get(sleep_date, [])
        sleep_ev = next((t for t in sleep_tasks if "sleep" in t.get("activity", "").lower()), None)
        
        if not sleep_ev: return False
        
        sleep_m = self._time_to_minutes(sleep_ev['start_time'])
        
        is_awake = False
        is_awake = False
        is_early_riser = False
        
        # Chrono-Boundary checks
        if now_m < wake_m: 
            if (wake_m - now_m) <= 120:
                is_early_riser = True
            else:
                is_awake = True
        elif now_m >= sleep_m and sleep_m >= wake_m: # E.g. 23:30, Sleep is 23:00
            is_awake = True

        if is_early_riser:
            log.info(f"Early Riser Intercept: Commander active at {now.strftime('%H:%M')}. Shifting Wake back to now.")
            if wake_ev:
                wake_ev['start_time'] = now.strftime('%H:%M')
                wake_ev['is_placeholder'] = False # Marked visually confirmed
                
            if sleep_ev:
                # Shrink yesterday's sleep duration
                new_dur = max(60, (now_m if now_m >= sleep_m else now_m + 1440) - sleep_m)
                sleep_ev['duration'] = new_dur
                sleep_ev['is_placeholder'] = False
                
            self._save_state()
            return True

        if is_awake:
            # Shift sleep block forward by 10m
            new_m = now_m + 10
            sh, sm = (new_m // 60) % 24, new_m % 60
            
            # Use strict mod physics for safe time representations
            log.info(f"Night Owl Intercept: Commander active at {now.strftime('%H:%M')}. Shifting Sleep to {sh:02d}:{sm:02d}.")
            
            # Mutate inline to avoid _force_slot recursive bounding logic
            sleep_ev['start_time'] = f"{sh:02d}:{sm:02d}"
            
            # Recalculate duration so they don't oversleep past Wake
            wake_abs = wake_m if wake_m >= new_m else wake_m + 1440
            new_dur = max(60, wake_abs - new_m)
            sleep_ev['duration'] = new_dur
            
            self._save_state()
            return True
            
        return False

    def _init_day(self, target_date: str):
        """Ensures a date entry exists and runs daily biological checks."""
        if self._suppress_anchors:
            return
            
        if hasattr(self, "_in_init_lock") and self._in_init_lock == target_date:
            return
        
        if target_date not in self.schedule_db:
            self.schedule_db[target_date] = []
            
        self._in_init_lock = target_date
        try:
            self._inject_daily_biological_anchors(target_date)
        finally:
            self._in_init_lock = None

    def _inject_daily_biological_anchors(self, target_date: str):
        """Ensures Sleep, Wake, and Meals exist. Re-injects placeholders if missing."""
        tasks = self.schedule_db.get(target_date, [])
        
        # Sequence definition
        placeholders = [
            ("Wake (Biological Anchor)", "07:00", 15, 8, "biological"),
            ("Sleep", "23:00", 420, 9, "sleep"),
            ("Breakfast", "08:30", 45, 8, "meal"),
            ("Lunch", "13:00", 60, 8, "meal"),
            ("Dinner", "19:00", 60, 8, "meal"),
            ("Snack", "16:00", 15, 4, "meal")
        ]
        
        for name, start, dur, pri, t_type in placeholders:
            match = False
            for t in tasks:
                act = t.get('activity', '').lower()
                c_type = t.get('type')
                
                # Strict matching: Don't let random tasks override biological needs
                if c_type == t_type:
                    if t_type == "meal" and name.lower() in act:
                        match = True
                        break
                    elif t_type in ["sleep", "biological"] and (name.lower() in act or c_type == t_type):
                        match = True
                        break
            
            if not match:
                log.info(f"Injecting persistent placeholder for {name} on {target_date}")
                self._force_slot(target_date, start, dur, name, pri, t_type)

                # Find the newly added task and flag it as an auto-placeholder 
                # (so proactive triggers know we can override it later)
                for t in self.schedule_db[target_date]:
                    if t.get('activity') == name:
                        t['is_placeholder'] = True

        
    def _align_biological_anchors(self, target_date: str, pending_intent: Optional[UserIntent] = None):
        """Re-calculates Wake and Breakfast based on the first P9 commitment of the day."""
        if target_date not in self.schedule_db: return

        # 1. Find the Anchor Objects (Fetch fresh from DB)
        sleep = next((t for t in self.schedule_db[target_date] if "sleep" in t['activity'].lower()), None)
        wake = next((t for t in self.schedule_db[target_date] if "wake" in t['activity'].lower()), None)
        breakfast = next((t for t in self.schedule_db[target_date] if "breakfast" in t['activity'].lower()), None)
        
        if not sleep: return # Can't align without sleep
        
        # 2. Find the first P9 (Non-Biological) after Sleep
        sm = self._time_to_minutes(sleep['start_time'])
        first_p9_m = 1440
        
        # Check Existing Tasks
        for t in sorted(self.schedule_db[target_date], key=lambda x: x['start_time']):
            pri = self._apply_deadline_gravity(t.get('priority', 5), t.get('deadline'))
            tm = self._time_to_minutes(t['start_time'])
            if pri >= 9 and tm > sm and t != sleep:
                first_p9_m = tm
                break
        
        # Check Pending Intent (Proactive Alignment)
        if pending_intent and pending_intent.priority >= 9:
            int_m = self._time_to_minutes(pending_intent.start_time_reference)
            if int_m > sm:
                first_p9_m = min(first_p9_m, int_m)
        
        # 3. Re-calculate Wake (Target 7h Rest, but capped by first P9 - 1h)
        target_wake_m = sm + 420
        wake_limit_m = first_p9_m - 60
        final_wake_m = min(target_wake_m, wake_limit_m)
        
        # Safety: minimum 1h sleep
        if final_wake_m <= sm: final_wake_m = sm + 60
        
        # Update Sleep Duration
        sleep['duration'] = final_wake_m - sm
        log.info(f"Alignment: Sleep [{sleep['start_time']}] dur set to {sleep['duration']}m")
        
        # 4. Standardize/Update Wake Anchor
        wh, wm = (final_wake_m // 60) % 24, (final_wake_m % 60)
        new_wake_str = f"{wh:02d}:{wm:02d}"
        if wake:
            wake['start_time'] = new_wake_str
            wake['duration'] = 15
            log.info(f"Alignment: Wake moved to {new_wake_str}")
        else:
             self._force_slot(target_date, new_wake_str, 15, "Wake (Biological Anchor)", 8, "biological")

        # 5. Morning Routine (Breakfast)
        if breakfast:
            # If there's a 1hr gap, put breakfast in it
            if first_p9_m - final_wake_m >= 60:
                bm = final_wake_m + 15
                bh, bmm = (bm // 60) % 24, (bm % 60)
                breakfast['start_time'] = f"{bh:02d}:{bmm:02d}"
                breakfast['duration'] = 30
            else:
                # No gap? Let the Meal Sequence logic move it after Wake or where it fits
                pass
        
        # Check Sleep Debt
        debt_mins = self._calculate_sleep_debt(target_date)
        if debt_mins > 0:
            log.info(f"Sleep debt detected: {debt_mins}m. Injecting recovery protocol.")
            # Auto-inject a Powernap in the afternoon (14:00 - 16:00 window)
            self.queue_flexible(target_date, "Powernap (Sleep Recovery)", 45, 9, "afternoon")

    def _calculate_sleep_debt(self, target_date: str) -> int:
        """Calculates yesterday's sleep deficit below a 7-hour threshold."""
        yest = (date.fromisoformat(target_date) - timedelta(days=1)).isoformat()
        if yest not in self.schedule_db:
            return 0
        
        # Filter activities that contain "sleep"
        sleep_events = [t for t in self.schedule_db[yest] if "sleep" in t["activity"].lower()]
        total_sleep = sum(t["duration"] for t in sleep_events)
        
        threshold = 7 * 60 # 420 minutes
        return max(0, threshold - total_sleep) if total_sleep > 0 else 0

    def _resolve_target_date_from_intent(self, intent: UserIntent) -> str:
        """Map date_reference (today|tomorrow|yesterday|ISO) to YYYY-MM-DD. Defaults to today."""
        target_date = date.today().isoformat()
        if not intent.date_reference:
            return target_date
        ref = intent.date_reference.lower().strip()
        if "tomorrow" in ref:
            return (date.today() + timedelta(days=1)).isoformat()
        if "today" in ref:
            return date.today().isoformat()
        if "yesterday" in ref:
            return (date.today() - timedelta(days=1)).isoformat()
        try:
            return date.fromisoformat(intent.date_reference.strip()).isoformat()
        except ValueError:
            return target_date

    def _sleep_consistency_context_lines(self) -> List[str]:
        """Bedtime / wake-time spread over the last 7 days for lifestyle messaging."""
        bed_minutes: List[int] = []
        wake_minutes: List[int] = []
        for i in range(7):
            d_str = (date.today() - timedelta(days=i)).isoformat()
            day = self.schedule_db.get(d_str, [])
            sleep_ev = next((t for t in day if "sleep" in t.get("activity", "").lower()), None)
            wake_ev = next((t for t in day if "wake" in t.get("activity", "").lower()), None)
            if sleep_ev and sleep_ev.get("start_time"):
                bed_minutes.append(self._time_to_minutes(sleep_ev["start_time"]))
            if wake_ev and wake_ev.get("start_time"):
                wake_minutes.append(self._time_to_minutes(wake_ev["start_time"]))
        lines: List[str] = []
        if len(bed_minutes) < 2 and len(wake_minutes) < 2:
            return lines

        def spread(vals: List[int]) -> Optional[int]:
            if len(vals) < 2:
                return None
            return max(vals) - min(vals)

        bs = spread(bed_minutes)
        ws = spread(wake_minutes)
        parts = []
        if bs is not None:
            parts.append(f"bedtime spread ~{bs}m across logged days")
        if ws is not None:
            parts.append(f"wake-time spread ~{ws}m across logged days")
        if parts:
            lines.append("[SLEEP CONSISTENCY — last 7 days]")
            lines.append(
                "; ".join(parts)
                + ". Irregular schedules reduce sleep quality even when duration is adequate."
            )
        return lines

    def _inject_sleep_debt_recovery_if_needed(self, target_date: str) -> None:
        """Queue recovery nap when yesterday's sleep was below threshold (no anchor realignment)."""
        debt_mins = self._calculate_sleep_debt(target_date)
        if debt_mins > 0:
            log.info(f"Sleep debt detected: {debt_mins}m. Injecting recovery protocol.")
            self.queue_flexible(target_date, "Powernap (Sleep Recovery)", 45, 9, "afternoon")

    def get_context_for_ai(self) -> str:
        """Injects hardware time, biological constraints, and pending verification into the AI context."""
        now = datetime.now()
        today_str = now.date().isoformat()
        self._init_day(today_str)
        
        debt_mins = self._calculate_sleep_debt(today_str)
        context = [
            f"SYSTEM TIME: {now.strftime('%H:%M')}",
            f"SYSTEM DATE: {today_str}",
        ]
        
        if debt_mins > 0:
            context.append(f"[BIOMEDICAL ALERT] CRITICAL SLEEP DEBT: {debt_mins}m deficit. Focus degraded.")

        for line in self._sleep_consistency_context_lines():
            context.append(line)
        
        # --- PENDING VERIFICATION (ZOMBIE TASKS) ---
        zombies = []
        now_m = now.hour * 60 + now.minute
        # Check today and yesterday for uncompleted tasks that have passed
        for d_str in [ (now - timedelta(days=1)).date().isoformat(), today_str ]:
            for t in self.schedule_db.get(d_str, []):
                # ONLY verify actual 'task' types, skip anchors/meals
                if t.get('completed') or t.get('type') != 'task': continue
                h, m = map(int, t['start_time'].split(':'))
                end_m = h * 60 + m + t['duration']
                # If task ended > 5 mins ago and not completed
                if (d_str < today_str) or (end_m < now_m - 5):
                    zombies.append(f"{t['activity']} (scheduled {t['start_time']})")
        
        if zombies:
            context.append("\n[URGENT: PENDING VERIFICATION]")
            context.append("The following tasks have passed their scheduled time. ASK THE COMMANDER IF THEY WERE COMPLETED:")
            for z in zombies: context.append(f" - {z}")

        # Current Schedule Overview
        context.append("\n[CURRENT OPERATIONS SCHEDULE]")
        day_tasks = self.schedule_db.get(today_str, [])
        valid_tasks = [t for t in day_tasks if "start_time" in t]
        for t in sorted(valid_tasks, key=lambda x: x['start_time']):
            pri = self._apply_deadline_gravity(t.get('priority', 5), t.get('deadline'))
            status = " [DONE]" if t.get('completed') else ""
            context.append(f"- {t['start_time']} ({t['duration']}m) [P{pri}]: {t['activity']}{status}")
            
        if self.overflow_queue:
            context.append("\n[OVERFLOW QUEUE - HIGH PRIORITY PENDING]")
            for o in self.overflow_queue:
                p = self._apply_deadline_gravity(o['priority'], o.get('deadline'))
                context.append(f"- {o['activity']} ({o['duration']}m) [P{p}]")
                
        return "\n".join(context)

    def process_parsed_input(self, data: ParsedInput):
        """Route Pydantic intents to specific execution logic, prioritizing deletions."""
        # ACTION PRIORITY: delete (0), modify (1), create (2)
        # This ensures we clean the old state before adding new slots for "shifts"
        priority_map = {"delete": 0, "modify": 1, "create": 2}
        sorted_intents = sorted(data.intents, key=lambda x: priority_map.get(x.action, 2))
        
        # 1. Initialize days for all intents
        target_dates = {self._resolve_target_date_from_intent(intent) for intent in data.intents}
        
        for d in target_dates:
            self._init_day(d)

        self._suppress_anchors = True
        try:
            for intent in sorted_intents:
                target_date = self._resolve_target_date_from_intent(intent)
                self._execute_intent(intent, target_date=target_date)
        finally:
            self._suppress_anchors = False

        self._save_state()

    def _time_to_minutes(self, hhmm: Optional[str]) -> int:
        """Converts HH:MM string to absolute minutes from midnight."""
        if not hhmm or ":" not in hhmm: return 0
        try:
            h, m = map(int, hhmm.split(':'))
            return h * 60 + m
        except Exception:
            return 0

    def calculate_dynamic_wake_time(self, target_date: str) -> str:
        """Helper to find the earliest fixed event and subtract 1 hour."""
        tasks = self.schedule_db.get(target_date, [])
        if not tasks:
            return "08:00"
        
        fixed_times = []
        for t in tasks:
            h, m = map(int, t['start_time'].split(':'))
            fixed_times.append(h * 60 + m)
            
        if not fixed_times:
             return "08:00"
             
        earliest_m = min(fixed_times)
        wake_m = max(0, earliest_m - 60)
        return f"{wake_m // 60:02d}:{wake_m % 60:02d}"

    def execute_schedule_command(self, cmd: dict) -> bool:
        """Legacy-to-Logic bridge for commands from AIBackend."""
        try:
            # Handle both old and new field names for robustness
            auto_sched = bool(cmd.get("auto_schedule"))
            if auto_sched:
                inferred_type = "floating_task"
                start_ref = "now"
            else:
                inferred_type = cmd.get("intent_type") or (
                    "fixed_event" if cmd.get("start_time") or cmd.get("start_time_reference") else "floating_task"
                )
                start_ref = cmd.get("start_time_reference", cmd.get("start_time"))
            intent = UserIntent(
                action=cmd.get("action", "create"),
                intent_type=inferred_type,
                event_name=str(cmd.get("event_name", cmd.get("label", cmd.get("activity", "Unknown Operation")))),
                start_time_reference=start_ref,
                end_time_reference=cmd.get("end_time_reference", cmd.get("end_time")),
                duration_minutes=int(cmd.get("duration_minutes", cmd.get("duration", 0))) or None,
                priority=int(cmd.get("priority", 5)),
                deadline=cmd.get("deadline"),
                date_reference=cmd.get("date_reference"),
                auto_schedule=auto_sched,
            )
            target_date = self._resolve_target_date_from_intent(intent)
            self._init_day(target_date)
            self._suppress_anchors = True
            try:
                success = self._execute_intent(intent, target_date=target_date)
                if success:
                    self._save_state()
                return success
            finally:
                self._suppress_anchors = False
        except Exception as e:
            log.error(f"Error in execute_schedule_command bridge: {e}")
            return False

    def _parse_time_reference(self, ref: str, base_time: Optional[str] = None, target_date: Optional[str] = None) -> Optional[str]:
        """Parses keywords, absolute times, and relative or hybrid offsets (19:30 +1h)."""
        if not ref: return None
        ref = ref.lower().strip().replace('.', ':')

        # 1. Handle Sequential Anchors ("after math class")
        if ref.startswith("after "):
            event_query = ref[6:].strip()
            # Use provided target_date or default to today
            d_str = target_date or date.today().isoformat()
            tasks = self.schedule_db.get(d_str, [])
            
            # Find the target event (Fuzzy match)
            target = next((t for t in tasks if event_query in t['activity'].lower() or t['activity'].lower() in event_query), None)
            
            if target:
                # Calculate end time: start_time + duration
                sm = self._time_to_minutes(target['start_time'])
                em = sm + target['duration']
                em %= 1440
                res = f"{em // 60:02d}:{em % 60:02d}"
                log.info(f"Sequential Resolve: '{ref}' on {d_str} -> {res} (after {target['activity']})")
                return res
            else:
                log.warning(f"Sequential Resolve Failed: Could not find '{event_query}' on {d_str}. Defaulting to current time.")
                return datetime.now().strftime("%H:%M")
        
        # 1. Handle Hybrid/Relative Offsets
        if '+' in ref or '-' in ref:
            try:
                # Find the first operator to split on
                op_idx = ref.find('+') if '+' in ref else ref.find('-')
                if op_idx == 0: # Pure relative (+1h)
                    sign = 1 if ref.startswith('+') else -1
                    val_str = ref[1:].strip()
                    bh, bm = (map(int, base_time.split(':')) if base_time else (datetime.now().hour, datetime.now().minute))
                else: # Hybrid (19:30 +1h)
                    base_candidate = ref[:op_idx].strip()
                    delta_candidate = ref[op_idx:].strip()
                    # Resolve base part first
                    resolved_base = self._parse_time_reference(base_candidate, base_time=base_time, target_date=target_date)
                    if not resolved_base: return None
                    return self._parse_time_reference(delta_candidate, base_time=resolved_base, target_date=target_date)

                # Parse delta (e.g., 1h, 30m, 90)
                delta_mins = 0
                if 'h' in val_str:
                    delta_mins = int(float(val_str.replace('h', '')) * 60)
                elif 'm' in val_str:
                    delta_mins = int(val_str.replace('m', ''))
                else:
                    delta_mins = int(val_str)
                
                total_mins = bh * 60 + bm + (sign * delta_mins)
                total_mins %= (24 * 60)
                return f"{total_mins // 60:02d}:{total_mins % 60:02d}"
            except Exception as e:
                log.warning(f"Failed to parse relative/hybrid offset '{ref}': {e}")
                return None

        # 2. Strict Keyword Mapping
        mapping = {
            "midnight": "00:00",
            "noon": "12:00",
            "midday": "12:00",
            "morning": "09:00",
            "afternoon": "13:00",
            "evening": "18:00",
            "tonight": "21:00",
            "night": "22:00",
            "now": datetime.now().strftime("%H:%M")
        }
        if ref in mapping:
            return mapping[ref]
        
        # 2. Waterfall Parser (AM/PM and 24h)
        formats = [
            ("%H:%M", None),        # 20:30
            ("%H%M",  4),           # 2030 (only try if exactly 4 chars)
            ("%I:%M%p", None),      # 8:30pm
            ("%I:%M %p", None),     # 8:30 pm
            ("%I.%M%p", None),      # 8.30pm
            ("%I.%M %p", None),     # 8.30 pm
            ("%H.%M", None),        # 20.30
            ("%I%p",  None),        # 8pm
            ("%I %p", None),        # 8 pm
            ("%H",    None),        # 20  (bare hour)
        ]
        
        # Clean string for strptime: remove dots/spaces if needed, but waterfall handles most
        clean_ref = ref.replace(' ', '').replace('am', 'AM').replace('pm', 'PM')
        # Some formats need the space back if it was like '8 pm'
        # We'll just try both compressed and original
        for r in [clean_ref, ref.upper()]:
            for fmt, req_len in formats:
                if req_len is not None and len(r) != req_len:
                    continue
                try:
                    dt = datetime.strptime(r, fmt)
                    return dt.strftime("%H:%M")
                except ValueError:
                    continue
                    
        return None

    def _execute_intent(self, intent: UserIntent, target_date: Optional[str] = None) -> bool:
        """Internal executor for a single UserIntent."""
        now = datetime.now()
        name = intent.event_name.lower()
        
        # 1. DATE INFERENCE — batch (process_parsed_input) and AI bridge pass target_date;
        #    otherwise resolve from intent.date_reference.
        if not target_date:
            target_date = self._resolve_target_date_from_intent(intent)
        self._init_day(target_date)

        # Engine-placed tasks: never let the LLM pick the clock time; queue_flexible uses energy + gaps.
        if intent.auto_schedule:
            intent.intent_type = "floating_task"
            intent.start_time_reference = "now"

        # 2. CONTROLLED DELETIONS/MODIFICATIONS (Context-Aware Base Time)
        base_time_for_delta = None
        preserved_type = "task"
        found_original = False
        if intent.action in ["delete", "modify"]:
            search_dates = [target_date] if intent.date_reference else [date.today().isoformat(), (date.today() + timedelta(days=1)).isoformat()]
            
            for d_str in search_dates:
                tasks = self.schedule_db.get(d_str, [])
                new_tasks = []
                for t in tasks:
                    if intent.event_name.lower() in t['activity'].lower() or t['activity'].lower() in intent.event_name.lower():
                        if not found_original:
                            base_time_for_delta = t.get('start_time')
                            preserved_type = t.get('type', 'task')
                            found_original = True
                        continue # Target found, effectively deleting it
                    new_tasks.append(t)
                
                if len(new_tasks) < len(tasks):
                    self.schedule_db[d_str] = new_tasks
                    log.info(f"Removed '{intent.event_name}' from {d_str} for processing.")
            
            if found_original and intent.action == "delete":
                return True
            
        # 3. TIME PARSING (Relative-Aware) — skip when auto_schedule (keep "now" as window keyword for queue_flexible)
        if intent.start_time_reference and not intent.auto_schedule:
            s_ref = intent.start_time_reference.lower().strip()
            # If AI put a date keyword in the time field, move it
            if s_ref in ["today", "tomorrow"] and not intent.date_reference:
                intent.date_reference = s_ref
                # Re-run date inference if needed? 
                # (Simple: just update target_date if it was tomorrow)
                if s_ref == "tomorrow": target_date = (date.today() + timedelta(days=1)).isoformat()
                intent.start_time_reference = None
                log.info(f"Auto-corrected date keyword '{s_ref}' from time field.")
            else:
                # Use base_time_for_delta if it's a modify action and we found a task
                parsed = self._parse_time_reference(intent.start_time_reference, base_time=base_time_for_delta, target_date=target_date)
                if parsed:
                    intent.start_time_reference = parsed

        # 3. IDEMPOTENT DEDUPLICATION & DELETION
        # If action is 'create', we check if a similar task already exists.
        # If so, we treat it as an OVERWRITE (modify) to prevent duplicates.
        # Note: We do NOT wipe base_time_for_delta here as it may be needed for relative shifts.
        found_duplicate = False
        
        # Determine search range: Use explicit date if provided, otherwise check today/tomorrow
        if intent.date_reference:
            search_dates = [target_date]
        else:
            search_dates = [date.today().isoformat(), (date.today() + timedelta(days=1)).isoformat()]

        for d_str in search_dates:
            tasks = self.schedule_db.get(d_str, [])
            if not tasks: continue
            
            new_tasks = []
            for t in tasks:
                act = t['activity'].lower()
                match = False
                
                # Fuzzy name match
                if name in act or act in name:
                    match = True
                
                # BIOLOGICAL COMPANION DEDUPLICATION
                # Prevent duplicate Sleeps or Wakes, but DO NOT delete Wake when Sleep is updated!
                if t.get('type') in ["sleep", "biological"]:
                    if ("sleep" in name or "bedtime" in name) and "sleep" in act:
                        match = True
                    elif "wake" in name and "wake" in act:
                        match = True
                elif t.get('type') == 'meal':
                    # Block duplicate main meals (Breakfast, Lunch, Dinner)
                    for meal_name in ["breakfast", "lunch", "dinner"]:
                        if meal_name in name and meal_name in act:
                            match = True
                            
                if match:
                    if not found_duplicate:
                        if not base_time_for_delta: # Only set if not already set by modify block
                            base_time_for_delta = t.get('start_time')
                        preserved_type = t.get('type', 'task')
                        log.info(f"Deduplication: Detected existing '{t['activity']}' on {d_str}. Overwriting.")
                        found_duplicate = True
                    continue # Exclude from new_tasks
                new_tasks.append(t)
            
            if len(new_tasks) < len(tasks):
                self.schedule_db[d_str] = new_tasks
            
        # 3.5 HALLUCINATION GUARD (create-overwrite fixed times only; floating/engine placement bypasses)
        # EXCEPTION: Biological anchors, explicit range/duration, meals/bio/sleep slot types.
        if (
            (found_duplicate or found_original)
            and intent.action == "create"
            and intent.start_time_reference
            and intent.intent_type == "fixed_event"
        ):
            is_bio = any(b in name for b in ["sleep", "wake", "bedtime"])
            is_explicit = intent.end_time_reference is not None or intent.duration_minutes is not None
            is_meal_or_anchor = preserved_type in ("meal", "biological", "sleep")
            
            if not is_bio and not is_explicit and not is_meal_or_anchor:
                it_m = self._time_to_minutes(intent.start_time_reference)
                bt_m = self._time_to_minutes(base_time_for_delta)
                # Handle wrap-around (1440m)
                diff = abs(it_m - bt_m)
                if diff > 720: diff = abs(1440 - diff)
                
                if diff > 90:
                    log.warning(f"Hallucination Guard: Overriding hallucinated shift ({intent.start_time_reference}) for {intent.event_name} to preserve existing {base_time_for_delta}.")
                    intent.start_time_reference = base_time_for_delta
        
        if (found_duplicate or found_original) and intent.action == "delete":
            return True
        
        # 4. TIME PARSING (Relative-Aware)
            
        # --- PRIORITY HIERARCHY / FLEXIBILITY RULES ---

        # --- GLOBAL BIOLOGICAL INTERCEPT ---
        if "sleep" in name or "bedtime" in name:
            # Resolve Sleep Start Time
            sleep_start_str = self._parse_time_reference(intent.start_time_reference or "23:00", target_date=target_date)
            if not sleep_start_str: sleep_start_str = "23:00"
            
            # Triggers automatic realignment
            res = self._force_slot(target_date, sleep_start_str, 420, "Sleep", 9, "sleep")
            self._align_biological_anchors(target_date)
            return res

        # --- AUTO-DURATION CALCULATOR ---
        if intent.start_time_reference and intent.end_time_reference:
            s_str = self._parse_time_reference(intent.start_time_reference, target_date=target_date)
            e_str = self._parse_time_reference(intent.end_time_reference, target_date=target_date)
            if s_str and e_str:
                sm = self._time_to_minutes(s_str)
                em = self._time_to_minutes(e_str)
                # Handle wraps (e.g. 10pm to 1am)
                if em < sm: em += 1440
                intent.duration_minutes = em - sm
                log.info(f"Calculated duration for '{intent.event_name}': {intent.duration_minutes}m ({s_str} to {e_str})")

        # --- PRIORITY HEURISTICS ---
        school_ks = ["class", "lecture", "exam", "school", "uni", "seminar", "project"]
        if any(k in name for k in school_ks):
            intent.priority = max(intent.priority, 9)
        
        meal_ks = ["lunch", "dinner", "breakfast", "meal", "snack"]
        if any(k in name for k in meal_ks):
            intent.priority = max(intent.priority, 8)

        # LLM-supplied clock times can be in the past; never place NEW fixed tasks earlier than now today.
        if (
            intent.intent_type == "fixed_event"
            and intent.start_time_reference
            and target_date == date.today().isoformat()
            and not intent.auto_schedule
            and not (found_duplicate or found_original)
        ):
            now_m = now.hour * 60 + now.minute
            slot_m = self._time_to_minutes(intent.start_time_reference)
            if slot_m < now_m:
                log.warning(
                    f"Requested slot {intent.start_time_reference} is in the past for today; "
                    f"using engine placement for '{intent.event_name}'."
                )
                return self.queue_flexible(
                    target_date,
                    intent.event_name,
                    intent.duration_minutes or 60,
                    intent.priority,
                    "now",
                    intent.deadline or "",
                )

        if intent.intent_type == "fixed_event":
            # Proactive Alignment for P9+ Fixed Events (like exams/classes)
            if intent.priority >= 9:
                self._align_biological_anchors(target_date, pending_intent=intent)
                
            res = self._force_slot(
                target_date, 
                intent.start_time_reference or "12:00", 
                intent.duration_minutes or 60,
                intent.event_name,
                intent.priority,
                preserved_type,  # Use the type we found (e.g. 'meal')
                intent.deadline or ""
            )
            
            # Final alignment check
            self._align_biological_anchors(target_date)
            return res
        elif intent.intent_type == "floating_task":
            return self.queue_flexible(
                target_date,
                intent.event_name,
                intent.duration_minutes or 60,
                intent.priority,
                intent.start_time_reference or "now",
                intent.deadline or ""
            )
        elif intent.intent_type == "status_update":
            name = intent.event_name.lower()
            current_data = self._calculate_current_energy()
            # Calculate current total PENALTY (Sleep debt + Drain + Coma - Recovery)
            # This is (Base - CurrentScore)
            current_penalty = self.user_energy - current_data['score']
            
            if any(k in name for k in ["tired", "exhausted", "fatigue", "drained", "coma"]):
                # Target: 30% Final. Base must be 30 + current_penalty
                self.user_energy = 30 + current_penalty
                log.info(f"Commander reported fatigue. Base adjusted to {self.user_energy} to reach 30% target.")
                return True
            if any(k in name for k in ["energized", "alert", "great", "ready"]):
                # Target: 100% Final. Base must be 100 + current_penalty
                self.user_energy = 100 + current_penalty
                log.info(f"Commander reported high energy. Base adjusted to {self.user_energy} to reach 100% target.")
                return True
            
            # TASK COMPLETION HANDLER
            if any(k in name for k in ["finished", "completed", "done", "mission success"]):
                # Clean name: remove "done with", "finished", etc.
                target = name
                for k in ["done with ", "finished ", "completed ", "mission success "]:
                    target = target.replace(k, "")
                target = target.strip()
                
                for d_str in [target_date, (now - timedelta(days=1)).date().isoformat()]:
                    for t in self.schedule_db.get(d_str, []):
                        if target in t['activity'].lower() or t['activity'].lower() in target:
                            t['completed'] = True
                            log.info(f"VERIFIED: '{t['activity']}' marked COMPLETED.")
                            return True
        return False

    def check_reminders(self) -> List[str]:
        """Checks for upcoming tasks and returns HTML reminder strings."""
        now = datetime.now()
        reminders = []
        today_str = now.date().isoformat()
        day_tasks = self.schedule_db.get(today_str, [])
        now_m = now.hour * 60 + now.minute
        
        for t in day_tasks:
            if "start_time" not in t:
                continue
            h, m = map(int, t['start_time'].split(':'))
            sm = h * 60 + m
            diff = sm - now_m
            
            # Use task name + time for uniqueness
            key = f"{t['start_time']}_{t['activity']}"
            if 0 < diff <= 15: # Reminder within 15 mins
                reminders.append(
                    f"Heads up — <b>{t['activity']}</b> begins at <b>{t['start_time']}</b>. "
                    f"That's in {diff} minutes."
                )
        return reminders

    def check_proactive_triggers(self, dossier_count: int) -> Optional[str]:
        """Examines the schedule and dossier to proactively ask the user questions."""
        import time
        now_ts = time.time()
        
        # 30-minute global cooldown for proactive triggers
        if now_ts - self._last_proactive_time < 1800:
            return None

        # 1. Missing intelligence data
        if dossier_count == 0:
            self._last_proactive_time = now_ts
            return "The Commander's dossier is currently empty. Introduce yourself and ask them 2 quick questions to learn their daily routine or goals so you can assist them better."

        now = datetime.now()
        today_str = now.date().isoformat()
        day_tasks = self.schedule_db.get(today_str, [])
        now_m = now.hour * 60 + now.minute

        # 2. Micro-interaction: Sleep quality (after wake detection, if not collected)
        if self.user_state.get("sleep_quality") is None:
            wake_ev = next((t for t in day_tasks if "wake" in t.get("activity", "").lower()), None)
            if wake_ev and not wake_ev.get("is_placeholder"):
                # Wake was logged — ask about sleep quality
                wake_m = self._time_to_minutes(wake_ev["start_time"])
                if now_m > wake_m + 15:  # 15 mins after wake
                    self._last_proactive_time = now_ts
                    return "The Commander has woken up but hasn't reported sleep quality. Ask briefly: 'How did you sleep, Commander? Quick rating — good, okay, or rough?'"

        # 3. Micro-interaction: Energy level (2 hours after wake, if not collected)
        if self.user_state.get("energy_level") is None:
            wake_ev = next((t for t in day_tasks if "wake" in t.get("activity", "").lower()), None)
            if wake_ev and not wake_ev.get("is_placeholder"):
                wake_m = self._time_to_minutes(wake_ev["start_time"])
                if now_m > wake_m + 120:  # 2 hours after wake
                    self._last_proactive_time = now_ts
                    return "Ask the Commander about their current energy level on a scale of 1–10 so you can optimize their schedule placement."

        # 4. Unconfirmed Biological Anchors
        wake_ev = next((t for t in day_tasks if "wake" in t.get("activity", "").lower()), None)
        if wake_ev and wake_ev.get("is_placeholder") and now.hour >= 9:
            self._last_proactive_time = now_ts
            return "The current wake time anchor is a system default. Proactively ask the Commander what time they woke up today so you can accurately calibrate the energy simulator."

        b_ev = next((t for t in day_tasks if "breakfast" in t.get("activity", "").lower()), None)
        if b_ev and b_ev.get("is_placeholder") and now.hour >= 10:
            self._last_proactive_time = now_ts
            return "The Commander has not logged their Breakfast time. Proactively ask them what they had for breakfast to activate the morning metabolism model."

        l_ev = next((t for t in day_tasks if "lunch" in t.get("activity", "").lower()), None)
        if l_ev and l_ev.get("is_placeholder") and now.hour >= 14:
            self._last_proactive_time = now_ts
            return "The Commander has not logged their Lunch time. Proactively ask them if they have eaten lunch yet to calculate afternoon food comas."

        d_ev = next((t for t in day_tasks if "dinner" in t.get("activity", "").lower()), None)
        if d_ev and d_ev.get("is_placeholder") and now.hour >= 20:
            self._last_proactive_time = now_ts
            return "The Commander has not logged their Dinner time. Proactively ask them if they have eaten dinner yet to calculate late-night digestion."

        # 5. Micro-interaction: Goals for today (if empty and morning)
        if not self.user_state.get("goals_today") and 8 <= now.hour <= 11:
            self._last_proactive_time = now_ts
            return "Ask the Commander: 'Any key objectives for today, Commander? I can prioritize your schedule around them.'"

        # 6. Follow-up on recently ended events
        for t in day_tasks:
            if t.get('completed') or "start_time" not in t:
                continue
            h, m = map(int, t['start_time'].split(':'))
            sm = h * 60 + m
            em = sm + t.get('duration', 60)
            
            # If the event ended exactly between 5 and 35 mins ago, ask about it
            if 5 < (now_m - em) <= 35:
                # Don't ask about sleep/meals generally, just tasks
                if t.get('type') not in ['meal', 'sleep', 'biological']:
                    self._last_proactive_time = now_ts
                    return f"The scheduled task '{t['activity']}' recently ended. Proactively ask the Commander how it went and if they finished it."

        return None

    def get_mood(self) -> dict:
        """Predicts agent 'mood' based on time of day."""
        h = datetime.now().hour
        # Simplified Mass Effect style mood table
        table = [
            (5, 8, "REVEILLE", "Rising phase. Cortisol levels normalizing.", "#00ccff"),
            (8, 12, "COMBAT READY", "Peak cognitive function detected.", "#00ff88"),
            (12, 14, "REFUEL WINDOW", "Midday maintenance.", "#f2a900"),
            (14, 18, "PEAK OPS", "High-intensity operations active.", "#00ff88"),
            (18, 22, "WIND DOWN", "Recovery cycle approaching.", "#f2a900"),
            (22, 5, "RECOVERY", "Sleep critical for combat effectiveness.", "#ff0033")
        ]
        for s, e, l, d, c in table:
            if s <= h < e if s < e else (h >= s or h < e):
                return {"label": l, "description": d, "color": c}
        return {"label": "NOMINAL", "description": "Systems stable.", "color": "#00ccff"}

    def get_mood_html(self) -> str:
        """Returns HTML-formatted mood and energy status for UI injection."""
        h = datetime.now().hour
        energy_data = self._calculate_current_energy()
        
        # Base Mood Predictor
        table = [
            (5, 8, "REVEILLE", "Rising phase. Cortisol levels normalizing.", "#00ccff"),
            (8, 12, "COMBAT READY", "Peak cognitive function detected.", "#00ff88"),
            (12, 14, "REFUEL WINDOW", "Midday maintenance.", "#f2a900"),
            (14, 18, "PEAK OPS", "High-intensity operations active.", "#00ff88"),
            (18, 22, "WIND DOWN", "Recovery cycle approaching.", "#f2a900"),
            (22, 5, "RECOVERY", "Sleep critical for combat effectiveness.", "#ff0033")
        ]
        
        mood_label, mood_desc, mood_color = "NOMINAL", "Systems stable.", "#00ccff"
        for s, e, l, d, c in table:
            if s <= h < e if s < e else (h >= s or h < e):
                mood_label, mood_desc, mood_color = l, d, c
                break
        
        # Override mood color if energy is critical
        if energy_data['score'] < 30:
            mood_color = "#ff4400"
            mood_label = "FATIGUE WARNING"

        penalty_html = "".join([f"<div style='font-size: 8px; color: #ff6666;'>• {p}</div>" for p in energy_data['penalties']])
        
        return (
            f"<div style='padding: 10px; border-left: 3px solid {mood_color}; background: rgba(0,40,80,0.15);'>"
            f"<div style='display: flex; justify-content: space-between; align-items: flex-start;'>"
            f"  <div style='font-family: Orbitron, sans-serif; font-size: 11px; color: {mood_color}; letter-spacing: 2px;'>"
            f"    STATUS: {mood_label}</div>"
            f"  <div style='font-family: Orbitron, sans-serif; font-size: 10px; color: #e0f0ff;'>"
            f"    ENERGY: {energy_data['score']}%</div>"
            f"</div>"
            f"<div style='height: 3px; background: #112233; margin: 6px 0;'>"
            f"  <div style='width: {energy_data['score']}%; height: 100%; background: {mood_color};'></div>"
            f"</div>"
            f"<div style='font-family: Montserrat, sans-serif; font-size: 11px; color: #c0d0e0; font-weight: 300;'>"
            f"{mood_desc}</div>"
            f"<div style='margin-top: 8px;'>{penalty_html}</div>"
            f"<div style='font-family: Orbitron, sans-serif; font-size: 9px; color: #445566; margin-top: 8px; font-weight: bold;'>"
            f"BIOMETRIC STATE: {energy_data['status']}</div></div>"
        )

    def get_schedule_html(self) -> str:
        """HTML rendering of current schedule for rolling 36h window."""
        now = datetime.now()
        start_win = now - timedelta(hours=12)
        end_win = now + timedelta(hours=24)
        
        dates = [(now + timedelta(days=i)).date().isoformat() for i in [-1, 0, 1]]
        all_tasks = []
        
        for d_str in dates:
            day_tasks = self.schedule_db.get(d_str, [])
            for t in day_tasks:
                if "start_time" not in t: continue
                h, m = map(int, t['start_time'].split(':'))
                dt = datetime.fromisoformat(d_str).replace(hour=h, minute=m)
                
                if start_win <= dt <= end_win:
                    t_copy = t.copy()
                    t_copy['_abs_dt'] = dt
                    all_tasks.append(t_copy)
                    
        # --- WINDOW EXPANSION ---
        if not all_tasks:
            # If 36h window is empty, show all future events
            for d_str, day_tasks in self.schedule_db.items():
                for t in day_tasks:
                    if "start_time" not in t: continue
                    h, m = map(int, t['start_time'].split(':'))
                    dt = datetime.fromisoformat(d_str).replace(hour=h, minute=m)
                    if dt >= now:
                        t_copy = t.copy()
                        t_copy['_abs_dt'] = dt
                        all_tasks.append(t_copy)

        if not all_tasks:
            return "<div style='color: #4a5568; padding: 10px;'>[NO OPERATIONS SCHEDULED]</div>"
            
        parts = []
        for t in sorted(all_tasks, key=lambda x: x['_abs_dt']):
            dt = t['_abs_dt']
            is_active = dt <= now < dt + timedelta(minutes=t['duration'])
            curr_class = " current" if is_active else ""
            task_type = t.get('type', 'task')
            time_opacity = "opacity: 0.4;" if task_type in ["sleep", "biological", "meal"] else ""
            pri_color = "var(--orange-n7)" if t.get('priority', 5) >= 8 else "var(--text-dim)"
            
            parts.append(
                f"<div class='schedule-entry{curr_class} {task_type}'>"
                f"<span style='color: var(--cyan-bright); {time_opacity} font-family: Orbitron, monospace; font-size: 13px; letter-spacing: 1px; font-weight: bold;'>{t['start_time']}</span> "
                f"<span class='schedule-task'>{t['activity']}</span> "
                f"<span style='color: {pri_color}; font-size: 0.8em;'>({t['duration']}m)</span>"
                f"</div>"
            )
        return "".join(parts)

    def _apply_deadline_gravity(self, base_priority: int, deadline: Optional[str]) -> int:
        """Scales priority aggressively as the deadline approaches."""
        if not deadline:
            return base_priority
        try:
            dl_dt = datetime.fromisoformat(deadline)
            now = datetime.now()
            hours_left = (dl_dt - now).total_seconds() / 3600
            
            if hours_left <= 0: return 10
            if hours_left < 3: return 10 # Final stretch
            if hours_left < 6: return max(9, base_priority + 4)
            if hours_left < 12: return min(10, base_priority + 3)
            if hours_left < 24: return min(10, base_priority + 2)
            if hours_left < 48: return min(10, base_priority + 1)
        except Exception:
            pass
        return base_priority
    def _chrono_sort_key(self, task: dict) -> int:
        if 'start_time' not in task: return 0
        h, m = map(int, task['start_time'].split(':'))
        tm = h * 60 + m
        # Late night sleep visually and computationally wrapped to bottom
        if "sleep" in task.get('activity', '').lower() and tm < 300:
            tm += 1440
        return tm

    def _force_slot(self, target_date: str, start_time: str, duration: int, activity: str, priority: int, t_type: str = "task", deadline: str = "") -> bool:
        """The Ripple Rescheduler: Evicts lower-priority overlaps and re-queues them."""
        self._init_day(target_date)
        
        # Calculate numeric time frames
        h, m = map(int, start_time.split(':'))
        new_start = h * 60 + m
        if "sleep" in activity.lower() and new_start < 300: # Late night wraps to end of day
            new_start += 1440
        new_end = new_start + duration
        
        # Absolute biological and meal sequence guard
        w_start, w_end = self._apply_sequence_constraints(target_date, activity, 0, 2800)
        if new_start < w_start or new_end > w_end:
            log.warning(f"Sequence Violation: '{activity}' @ {start_time} violates biological bounds ({w_start} - {w_end}). Rejected.")
            return False
        
        effective_priority = self._apply_deadline_gravity(priority, deadline)
        
        survivors = []
        evicted = []
        
        # Check overlaps
        for task in self.schedule_db[target_date]:
            th, tm = map(int, task['start_time'].split(':'))
            ts = th * 60 + tm
            te = ts + task['duration']
            
            if not (new_end <= ts or new_start >= te):
                # --- DYNAMIC ANCHOR SHIFTING ---
                # If a new task hits a biological anchor, we shift the anchor instead of evicting it
                if "biological anchor" in task['activity'].lower() or task['type'] in ["sleep", "biological"]:
                    if "wake" in task['activity'].lower() and new_start <= ts + 30:
                        # Shift Wake earlier to accommodate the new early task
                        log.info(f"Shifting Wake earlier for '{activity}'")
                        task['start_time'] = f"{max(0, new_start - 45)//60:02d}:{max(0, new_start - 45)%60:02d}"
                        survivors.append(task)
                        continue
                    
                    if "sleep" in task['activity'].lower() and new_end > ts and new_start > 1020: # 17:00 (5pm)
                        # Shift Sleep later if the activity ends after bedtime (Only for evening tasks)
                        log.info(f"Shifting Sleep later for evening activity '{activity}'")
                        new_sleep_start = new_end + 15
                        
                        # Handle Rollover
                        final_h, final_m = (new_sleep_start // 60), (new_sleep_start % 60)
                        final_date = target_date
                        if final_h >= 24:
                            final_h -= 24
                            final_date = (date.fromisoformat(target_date) + timedelta(days=1)).isoformat()
                            self._init_day(final_date) # Ensure tomorrow exists
                        
                        task['start_time'] = f"{final_h:02d}:{final_m:02d}"
                        
                        # If date changed, move the task to the new day's list
                        if final_date != target_date:
                            self.schedule_db[final_date].append(task)
                            self.schedule_db[final_date].sort(key=self._chrono_sort_key)
                            continue # Don't add to survivors for the CURRENT date
                        
                        survivors.append(task)
                        continue

                # Overlap detected
                task_pri = self._apply_deadline_gravity(task['priority'], task.get('deadline'))

                if task_pri < effective_priority:
                    log.warning(f"Evicting '{task['activity']}' for higher priority '{activity}'")
                    evicted.append(task)
                else:
                    log.error(f"Cannot slot '{activity}': Blocked by higher priority '{task['activity']}'")
                    return False
            else:
                survivors.append(task)
        
        # Add new task
        survivors.append({
            "start_time": f"{h:02d}:{m:02d}",
            "duration": duration,
            "activity": activity,
            "priority": priority,
            "type": t_type,
            "deadline": deadline,
            "completed": False # New flag
        })
        
        # Re-sort and save (Using mod 1440 chronological wrap)
        survivors.sort(key=self._chrono_sort_key)
        self.schedule_db[target_date] = survivors
        
        # Attempt to re-pack evicted tasks
        for item in evicted:
            self.queue_flexible(target_date, item['activity'], item['duration'], item['priority'], "now", item.get('deadline'))
            
        return True

    def _apply_sequence_constraints(self, target_date: str, activity: str, w_start: int, w_end: int) -> Tuple[int, int]:
        """Ensures Wake < Breakfast < Lunch < Dinner < Sleep sequence is strictly upheld. Caps standard tasks directly between Wake and Sleep."""
        name = activity.lower()
        order = {"wake": 0, "breakfast": 1, "lunch": 2, "dinner": 3, "bedtime": 4, "sleep": 4}
        
        day_tasks = self.schedule_db.get(target_date, [])
        
        # 1. Base boundaries: NOTHING can happen between Sleep and Wake
        wake = next((t for t in day_tasks if "wake" in t['activity'].lower()), None)
        sleep = next((t for t in day_tasks if "sleep" in t['activity'].lower()), None)
        
        if wake and "wake" not in name:
            wake_m = self._time_to_minutes(wake['start_time'])
            w_start = max(w_start, wake_m)
            
        if sleep and "sleep" not in name and "bedtime" not in name:
            sleep_m = self._time_to_minutes(sleep['start_time'])
            if sleep_m < 300: sleep_m += 1440
            w_end = min(w_end, sleep_m)
            
        # 2. Meal Specific Boundaries (Hierarchical constraints inside the base boundary)
        if not any(m in name for m in order):
            return w_start, w_end
            
        current_idx = next(idx for m, idx in order.items() if m in name)
        
        # Find existing biological events on this date
        meals = []
        for t in day_tasks:
            act = t['activity'].lower()
            if any(m in act for m in order):
                idx = next(idx for m, idx in order.items() if m in act)
                # Skip the one we are currently trying to schedule/re-schedule
                if name in act or act in name: continue
                
                m_start = self._time_to_minutes(t['start_time'])
                if "sleep" in act and m_start < 300: # Push 2am sleep to the end
                    m_start += 1440
                meals.append({"idx": idx, "start": m_start, "end": m_start + t['duration']})
        
        # Apply constraints based on relative order
        for m in meals:
            if m['idx'] < current_idx:
                # Predecessors must occur BEFORE us
                w_start = max(w_start, m['end'])
            if m['idx'] > current_idx:
                # Successors must occur AFTER us
                w_end = min(w_end, m['start'])
                
        return w_start, w_end

    def queue_flexible(self, target_date: str, activity: str, duration: int, priority: int, window: str = "now", deadline: str = "") -> bool:
        """The Gap Finder with Energy-Aware Overrides."""
        self._init_day(target_date)
        now = datetime.now()
        
        energy_data = self._calculate_current_energy()
        
        # ENERGY OVERRIDE: If energy is critical (<40), ensure 30m buffer before any non-rest task
        buffer = 0
        if energy_data['score'] < 40 and "rest" not in activity.lower():
            log.info(f"Low energy protocol: Injecting buffer for '{activity}'.")
            buffer = 30

        # Define search window
        w_start, w_end = 0, 23 * 60 + 59
        window = window.lower()
        if "morning" in window: w_start, w_end = 6 * 60, 12 * 60
        elif "afternoon" in window: w_start, w_end = 12 * 60, 18 * 00
        elif "evening" in window: w_start, w_end = 18 * 00, 23 * 59
        elif "now" in window and target_date == now.date().isoformat():
            w_start = now.hour * 60 + now.minute + 1
            # MEAL SEQUENCE PROTECTION: Ensure Breakfast < Lunch < Dinner
            w_start, w_end = self._apply_sequence_constraints(target_date, activity, w_start, w_end)
        elif ":" in window: # Specific time like "00:00"
            wh, wm = map(int, window.split(':'))
            w_start = wh * 60 + wm
            
            # --- HIGH PRIORITY OVERRIDE ---
            # If a specific time is requested and priority is P9+, we try to FORCE the slot
            # instead of skipping past existing blocks. This enables "pushing" behavior.
            if priority >= 9:
                log.info(f"Priority Override: Attempting to force slot at {window} for '{activity}'")
                if self._force_slot(target_date, window, duration, activity, priority, "task", deadline):
                    return True
            
        # Get existing blocks
        blocks = []
        for t in self.schedule_db[target_date]:
            th, tm = map(int, t['start_time'].split(':'))
            ts = th * 60 + tm
            blocks.append((ts, ts + t['duration'], t['priority']))
        blocks.sort()
        
        # Linear search for first gap
        cursor = w_start + buffer
        while cursor + duration <= w_end:
            # --- Cognitive Load Check ---
            # If 4 straight hours of P8+ work exist, enforce 15m buffer
            if self._is_cognitive_overloaded(target_date, cursor) and priority >= 8:
                log.info(f"Cognitive load exceeds threshold. Adding 15m buffer before '{activity}'.")
                cursor += 15
                continue
                
            collision = False
            for bs, be, bp in blocks:
                if not (cursor + duration <= bs or cursor >= be):
                    collision = True
                    cursor = be + buffer
                    break
            
            if not collision:
                # Slot found!
                h, m = cursor // 60, cursor % 60
                return self._force_slot(target_date, f"{h:02d}:{m:02d}", duration, activity, priority, "task", deadline)
            
        # No gap today? Try tomorrow.
        tomorrow = (date.fromisoformat(target_date) + timedelta(days=1)).isoformat()
        if target_date != tomorrow and "tomorrow" not in window: # Avoid infinite loop
             log.info(f"No gap for '{activity}' today. Attempting tomorrow...")
             return self.queue_flexible(tomorrow, activity, duration, priority, "morning", deadline)
             
        # Finally relegate to overflow
        log.warning(f"Relegating '{activity}' to overflow queue.")
        self.overflow_queue.append({
            "activity": activity, "duration": duration, "priority": priority, "deadline": deadline
        })
        return False

    def _is_cognitive_overloaded(self, target_date: str, start_min: int) -> bool:
        """Heuristic: Checks if the previous 4 hours contain >240m of P8+ activity."""
        window_start = int(max(0, start_min - 240))
        high_intensity_mins = 0
        
        for t in self.schedule_db.get(target_date, []):
            th, tm = map(int, t['start_time'].split(':'))
            ts = int(th * 60 + tm)
            te = int(ts + int(t['duration']))
            
            # Check if task is P8+ and overlaps with the 4-hour window
            if int(t['priority']) >= 8:
                overlap_s = int(max(window_start, ts))
                overlap_e = int(min(start_min, te))
                if overlap_s < overlap_e:
                    high_intensity_mins += int(overlap_e - overlap_s)
                    
        return high_intensity_mins >= 240

    # ═══════════════════════════════════════════════════════════════════════
    # NEW: TASK MANAGEMENT
    # ═══════════════════════════════════════════════════════════════════════

    def execute_task_command(self, cmd: dict) -> bool:
        """Handle task create/complete/delete from AI output."""
        import uuid
        from datetime import date as _date
        action    = cmd.get("action", "create")
        task_name = cmd.get("task_name", "Unknown Task")
        today     = _date.today().isoformat()

        if action == "create":
            task_id = str(uuid.uuid4())[:8]
            task = {
                "id":              task_id,
                "name":            task_name,
                "duration":        cmd.get("duration_minutes") or 60,
                "priority":        int(cmd.get("priority", 5)),
                "deadline":        cmd.get("deadline") or "",
                "completed":       False,
                "auto_schedule":   cmd.get("auto_schedule", True),
                "date":            today,
            }
            # Avoid duplication
            names = [t["name"].lower() for t in self.tasks_db]
            if task_name.lower() not in names:
                self.tasks_db.append(task)
                log.info(f"Task created: {task_name} (P{task['priority']})")
                # Auto-schedule if requested
                if task.get("auto_schedule"):
                    self._init_day(today)
                    self.queue_flexible(today, task_name, task["duration"], task["priority"], "now", task["deadline"])
                self._save_state()
                return True
            return False

        elif action == "complete":
            for t in self.tasks_db:
                if task_name.lower() in t["name"].lower() or t["name"].lower() in task_name.lower():
                    t["completed"] = True
                    log.info(f"Task completed: {t['name']}")
                    self._save_state()
                    return True
            return False

        elif action == "delete":
            before = len(self.tasks_db)
            self.tasks_db = [t for t in self.tasks_db
                             if task_name.lower() not in t["name"].lower()]
            if len(self.tasks_db) < before:
                self._save_state()
                return True
            return False

        return False

    def mark_task_complete(self, task_id: str):
        """Mark a task complete by ID (called from UI checkbox)."""
        from datetime import date, datetime
        target_name = None
        for t in self.tasks_db:
            if t.get("id") == task_id:
                t["completed"] = True
                t["completed_at"] = datetime.now().isoformat()
                target_name = t.get("name")
                log.info(f"Task {task_id} marked complete via UI")
                break

        # Remove from active schedule so it visually disappears
        if target_name:
            today_str = date.today().isoformat()
            sched = self.schedule_db.get(today_str, [])
            new_sched = [ev for ev in sched if ev.get("activity") != target_name]
            if len(new_sched) < len(sched):
                log.info(f"Scrubbed completed task '{target_name}' from timeline.")
                self.schedule_db[today_str] = new_sched

        self._save_state()

    def unmark_task_complete(self, task_id: str):
        """Unmark a task complete by ID and dynamically re-inject into schedule."""
        from datetime import date
        target = None
        for t in self.tasks_db:
            if t.get("id") == task_id:
                t["completed"] = False
                target = t
                log.info(f"Task {task_id} unmarked complete via UI")
                break

        if target:
            today_str = date.today().isoformat()
            self._init_day(today_str)
            # Route back into the Ripple Rescheduler for automatic gap filling
            self.queue_flexible(
                target_date=today_str,
                activity=target.get("name", "Unknown Task"),
                duration=target.get("duration", 60),
                priority=target.get("priority", 5),
                window="now",
                deadline=target.get("deadline", "")
            )

        self._save_state()

    def delete_task(self, task_id: str):
        """Delete a task by ID (called from UI delete button)."""
        self.tasks_db = [t for t in self.tasks_db if t.get("id") != task_id]
        self._save_state()

    def get_tasks_json(self) -> list:
        """Return tasks for the UI (pending first, then completed)."""
        pending   = [t for t in self.tasks_db if not t.get("completed")]
        completed = [t for t in self.tasks_db if t.get("completed")]
        # Sort pending by priority descending
        pending.sort(key=lambda x: x.get("priority", 5), reverse=True)
        return pending + completed

    # ═══════════════════════════════════════════════════════════════════════
    # NEW: REMINDER MANAGEMENT
    # ═══════════════════════════════════════════════════════════════════════

    def execute_reminder_command(self, cmd: dict) -> bool:
        """Handle reminder create/dismiss from AI output."""
        import uuid
        from datetime import date as _date
        action = cmd.get("action", "create")
        text   = cmd.get("reminder_text", "")

        if action == "create":
            r_id   = str(uuid.uuid4())[:8]
            remind_at = cmd.get("remind_at") or ""
            date_ref  = cmd.get("date_reference", "today")
            if date_ref == "tomorrow":
                from datetime import timedelta
                r_date = (_date.today() + timedelta(days=1)).isoformat()
            else:
                r_date = _date.today().isoformat()

            reminder = {
                "id":           r_id,
                "text":         text,
                "reminder_text": text,
                "remind_at":    remind_at,
                "date":         r_date,
                "dismissed":    False,
            }
            self.reminders_db.append(reminder)
            log.info(f"Reminder created: '{text}' @ {remind_at}")
            self._save_state()
            return True

        elif action == "dismiss":
            for r in self.reminders_db:
                if text.lower() in r["text"].lower() or r["text"].lower() in text.lower():
                    r["dismissed"] = True
                    self._save_state()
                    return True
            return False

        return False

    def dismiss_reminder(self, reminder_id: str):
        """Dismiss a reminder by ID (called from UI)."""
        for r in self.reminders_db:
            if r.get("id") == reminder_id:
                r["dismissed"] = True
                break
        self._save_state()

    def get_reminders_json(self) -> list:
        """Return active (non-dismissed) reminders for UI."""
        return [r for r in self.reminders_db if not r.get("dismissed")]

    # ═══════════════════════════════════════════════════════════════════════
    # EXPIRED ITEM CLEANUP — Runs after sanity checks
    # ═══════════════════════════════════════════════════════════════════════

    # Transient reminder keywords — these are auto-removable after expiry
    _TRANSIENT_KEYWORDS = [
        "take", "drink", "eat", "call", "check", "pick up", "submit",
        "charge", "pack", "bring", "buy", "pay", "send", "text", "reply",
    ]

    def cleanup_expired_items(self) -> dict:
        """
        Clean up expired reminders and completed tasks.

        Returns a dict with:
          - 'auto_removed_reminders': list of auto-removed transient reminders
          - 'ask_user_reminders': list of important reminders that need user confirmation
          - 'auto_removed_tasks': list of auto-removed completed tasks
        """
        from datetime import date as _date, datetime as _dt, timedelta as _td
        today = _date.today()
        now = _dt.now()
        result = {
            "auto_removed_reminders": [],
            "ask_user_reminders": [],
            "auto_removed_tasks": [],
        }

        # ── 1. Expired Reminders ──
        active_reminders = [r for r in self.reminders_db if not r.get("dismissed")]
        for r in active_reminders:
            r_date_str = r.get("date", "")
            if not r_date_str:
                continue
            try:
                r_date = _date.fromisoformat(r_date_str)
            except (ValueError, TypeError):
                continue

            if r_date >= today:
                continue  # Not expired yet

            text = (r.get("text") or r.get("reminder_text", "")).lower()

            # Check if this is a transient reminder (auto-removable)
            is_transient = any(kw in text for kw in self._TRANSIENT_KEYWORDS)

            if is_transient:
                r["dismissed"] = True
                result["auto_removed_reminders"].append(r.get("text", r.get("reminder_text", "")))
                log.info(f"[CLEANUP] Auto-removed transient reminder: '{text}'")
            else:
                # Important reminder — queue for AI to ask user
                result["ask_user_reminders"].append(r.get("text", r.get("reminder_text", "")))

        # ── 2. Completed Tasks (older than 24 hours) ──
        for t in list(self.tasks_db):
            if not t.get("completed"):
                continue

            # Check completion timestamp if available, otherwise check creation
            completed_at = t.get("completed_at")
            created_at = t.get("created_at")
            ref_time = completed_at or created_at

            if ref_time:
                try:
                    ref_dt = _dt.fromisoformat(ref_time)
                    if (now - ref_dt) < _td(hours=24):
                        continue  # Too recent, keep it visible
                except (ValueError, TypeError):
                    pass

            # Remove completed task
            task_name = t.get("name", "Unknown")
            self.tasks_db.remove(t)
            result["auto_removed_tasks"].append(task_name)
            log.info(f"[CLEANUP] Auto-removed completed task: '{task_name}'")

        if result["auto_removed_reminders"] or result["auto_removed_tasks"]:
            self._save_state()

        return result

    # ═══════════════════════════════════════════════════════════════════════
    # NEW: SLEEP/WAKE UPDATE HANDLER
    # ═══════════════════════════════════════════════════════════════════════

    def process_sleep_wake_update(self, update: dict) -> bool:
        """
        Dedicated handler for sleep/wake time reports.
        Updates biological anchors and recalculates energy.
        """
        from datetime import date as _date, timedelta as _td
        if not update:
            return False

        date_ref  = update.get("date_reference", "today")
        sleep_str = update.get("sleep_time") or ""
        wake_str  = update.get("wake_time") or ""

        if date_ref == "yesterday":
            target_date = (_date.today() - _td(days=1)).isoformat()
        else:
            target_date = _date.today().isoformat()

        self._init_day(target_date)
        changed = False

        if sleep_str:
            parsed = self._parse_time_reference(sleep_str)
            if parsed:
                sleep_event = next(
                    (t for t in self.schedule_db.get(target_date, [])
                     if "sleep" in t["activity"].lower()), None
                )
                if sleep_event:
                    old = sleep_event["start_time"]
                    sleep_event["start_time"] = parsed
                    log.info(f"Sleep time updated: {old} → {parsed} on {target_date}")
                else:
                    self._force_slot(target_date, parsed, 420, "Sleep", 9, "sleep")
                    log.info(f"Sleep anchor injected at {parsed} on {target_date}")
                changed = True

        if wake_str:
            dt_now = datetime.now()
            # If wake_str == "now", use actual current time
            if wake_str.lower() in ("now", "just now"):
                wake_str = dt_now.strftime("%H:%M")
            parsed = self._parse_time_reference(wake_str)
            if parsed:
                wake_event = next(
                    (t for t in self.schedule_db.get(target_date, [])
                     if "wake" in t["activity"].lower()), None
                )
                if wake_event:
                    old = wake_event["start_time"]
                    wake_event["start_time"] = parsed
                    log.info(f"Wake time updated: {old} → {parsed} on {target_date}")
                else:
                    self._force_slot(target_date, parsed, 15, "Wake (Biological Anchor)", 8, "biological")
                    log.info(f"Wake anchor injected at {parsed} on {target_date}")
                changed = True

        if changed:
            # Recalculate sleep duration if we have both anchors
            tasks = self.schedule_db.get(target_date, [])
            sleep_ev = next((t for t in tasks if "sleep" in t["activity"].lower()), None)
            wake_ev  = next((t for t in tasks if "wake"  in t["activity"].lower()), None)
            if sleep_ev and wake_ev:
                s_m = self._time_to_minutes(sleep_ev["start_time"])
                w_m = self._time_to_minutes(wake_ev["start_time"])
                if w_m < s_m:   # crosses midnight
                    w_m += 1440
                sleep_ev["duration"] = max(30, w_m - s_m)
                log.info(f"Sleep duration recalculated: {sleep_ev['duration']}m")

            # Do not call _align_biological_anchors here — it would overwrite user-reported wake/sleep.
            self._inject_sleep_debt_recovery_if_needed(target_date)
            # Recompute energy penalty based on new debt
            debt = self._calculate_sleep_debt(target_date)
            debt_penalty = int((debt / 60) * 5)
            self.user_energy = max(0, 100 - debt_penalty)
            log.info(f"Energy recalculated after wake update: {self.user_energy} (debt={debt}m)")
            self._save_state()

        return changed

    # ═══════════════════════════════════════════════════════════════════════
    # NEW: UI OUTPUT METHODS
    # ═══════════════════════════════════════════════════════════════════════

    def get_mood_dict(self) -> dict:
        """Returns mood + energy as a dict for the native UI (not HTML)."""
        h = datetime.now().hour
        energy_data = self._calculate_current_energy()

        table = [
            (5,  8,  "REVEILLE",     "Rising phase. Cortisol levels normalizing.",  "#00ccff"),
            (8,  12, "COMBAT READY", "Peak cognitive function detected.",            "#00ff88"),
            (12, 14, "REFUEL WINDOW","Midday maintenance.",                          "#f2a900"),
            (14, 18, "PEAK OPS",     "High-intensity operations active.",            "#00ff88"),
            (18, 22, "WIND DOWN",    "Recovery cycle approaching.",                  "#f2a900"),
            (22, 5,  "RECOVERY",     "Sleep critical for combat effectiveness.",     "#ff0033"),
        ]
        mood_label, mood_desc, mood_color = "NOMINAL", "Systems stable.", "#00ccff"
        for s, e, l, d, c in table:
            if (s <= h < e) if s < e else (h >= s or h < e):
                mood_label, mood_desc, mood_color = l, d, c
                break

        if energy_data["score"] < 30:
            mood_color = "#ff4400"
            mood_label = "FATIGUE WARNING"

        return {
            "label":       mood_label,
            "description": mood_desc,
            "color":       mood_color,
            "score":       energy_data["score"],
            "status":      energy_data["status"],
            "penalties":   energy_data["penalties"],
        }

    def get_schedule_tasks(self) -> list:
        """Returns a 36-hour window of schedule tasks (12h past, 24h future) with free-time blocks."""
        from datetime import datetime as _dt, timedelta as _td
        now       = _dt.now()
        start_win = now - _td(hours=12)
        end_win   = now + _td(hours=24)

        dates = [(now + _td(days=i)).date().isoformat() for i in [-1, 0, 1, 2]]
        result = []
        for d_str in dates:
            for t in self.schedule_db.get(d_str, []):
                if "start_time" not in t:
                    continue
                try:
                    h, m = map(int, t["start_time"].split(":"))
                except ValueError:
                    continue
                dt = _dt.fromisoformat(d_str).replace(hour=h, minute=m)
                if start_win <= dt <= end_win:
                    t_copy = t.copy()
                    t_copy["_dt"] = dt.isoformat()
                    result.append(t_copy)

        result.sort(key=lambda x: x["_dt"])

        # ── Inject FREE TIME blocks between events ──
        MIN_GAP = 10  # minutes — only show gaps larger than this
        enriched = []
        for i, task in enumerate(result):
            enriched.append(task)
            if i < len(result) - 1:
                t_end_m  = _dt.fromisoformat(task["_dt"]) + _td(minutes=task.get("duration", 0))
                t_next   = _dt.fromisoformat(result[i + 1]["_dt"])
                gap_mins = int((t_next - t_end_m).total_seconds() / 60)
                if gap_mins >= MIN_GAP:
                    free_block = {
                        "activity":   "FREE TIME",
                        "type":       "free",
                        "start_time": t_end_m.strftime("%H:%M"),
                        "duration":   gap_mins,
                        "priority":   0,
                        "_dt":        t_end_m.isoformat(),
                    }
                    enriched.append(free_block)

        return enriched

    def get_week_schedule(self) -> dict:
        """
        Returns 7 days of schedule data: 2 past + today + 4 future.
        Each day includes default biological anchors and free-time gaps.

        Returns:
            {date_str: [event_dicts]} where each event has:
                activity, start_time, duration, priority, type
        """
        from datetime import datetime as _dt, date as _date, timedelta as _td

        today = _date.today()
        days = [today + _td(days=i) for i in range(-2, 5)]  # 7 days

        # --- Estimate typical wake/sleep from recent data ---
        def _get_anchor_time(date_str: str, keyword: str) -> str | None:
            for ev in self.schedule_db.get(date_str, []):
                if keyword in ev.get("activity", "").lower():
                    return ev.get("start_time")
            return None

        # Scan last 7 days for typical wake/sleep times
        wake_samples, sleep_samples = [], []
        for i in range(-7, 1):
            d = (today + _td(days=i)).isoformat()
            w = _get_anchor_time(d, "wake")
            s = _get_anchor_time(d, "sleep")
            if w:
                wake_samples.append(w)
            if s:
                sleep_samples.append(s)

        def _avg_time(samples: list, fallback: str, min_hour: int = 0, max_hour: int = 23) -> str:
            """Average HH:MM samples, filtering outliers outside [min_hour, max_hour]."""
            if not samples:
                return fallback
            valid = []
            for s in samples:
                try:
                    h, m = map(int, s.split(":"))
                    if min_hour <= h <= max_hour:
                        valid.append(h * 60 + m)
                except (ValueError, AttributeError):
                    pass
            if not valid:
                return fallback
            avg = sum(valid) // len(valid)
            return f"{avg // 60:02d}:{avg % 60:02d}"

        # Filter: wake should be 5-12, sleep should be 21-03
        default_wake  = _avg_time(wake_samples, "07:00", min_hour=5, max_hour=12)
        default_sleep = _avg_time(sleep_samples, "23:00", min_hour=21, max_hour=23)

        # --- Build each day ---
        result = {}
        for day in days:
            day_str = day.isoformat()
            raw_events = list(self.schedule_db.get(day_str, []))

            # Get this day's actual wake/sleep or use defaults
            day_wake  = _get_anchor_time(day_str, "wake") or default_wake
            day_sleep = _get_anchor_time(day_str, "sleep") or default_sleep

            # --- Inject default biological anchors if missing ---
            has_wake  = any("wake" in e.get("activity", "").lower() for e in raw_events)
            has_sleep = any("sleep" in e.get("activity", "").lower() for e in raw_events)
            has_breakfast = any("breakfast" in e.get("activity", "").lower() for e in raw_events)
            has_lunch = any("lunch" in e.get("activity", "").lower() for e in raw_events)
            has_dinner = any("dinner" in e.get("activity", "").lower() for e in raw_events)

            if not has_wake:
                raw_events.append({
                    "start_time": day_wake, "duration": 15,
                    "activity": "Wake", "priority": 8,
                    "type": "biological", "projected": True
                })

            if not has_breakfast:
                # Breakfast 45min after wake
                try:
                    wh, wm = map(int, day_wake.split(":"))
                    bm = wh * 60 + wm + 45
                    b_time = f"{bm // 60:02d}:{bm % 60:02d}"
                except (ValueError, AttributeError):
                    b_time = "08:00"
                raw_events.append({
                    "start_time": b_time, "duration": 30,
                    "activity": "Breakfast", "priority": 7,
                    "type": "meal", "projected": True
                })

            if not has_lunch:
                raw_events.append({
                    "start_time": "12:30", "duration": 45,
                    "activity": "Lunch", "priority": 7,
                    "type": "meal", "projected": True
                })

            if not has_dinner:
                raw_events.append({
                    "start_time": "20:00", "duration": 45,
                    "activity": "Dinner", "priority": 7,
                    "type": "meal", "projected": True
                })

            if not has_sleep:
                raw_events.append({
                    "start_time": day_sleep, "duration": 420,
                    "activity": "Sleep", "priority": 9,
                    "type": "sleep", "projected": True
                })

            # --- Sort by start_time ---
            def _sort_key(ev):
                try:
                    h, m = map(int, ev["start_time"].split(":"))
                    return h * 60 + m
                except (ValueError, KeyError):
                    return 9999

            raw_events.sort(key=_sort_key)

            # --- Filter to wake–sleep window ---
            try:
                wake_m  = int(day_wake.split(":")[0]) * 60 + int(day_wake.split(":")[1])
                sleep_m = int(day_sleep.split(":")[0]) * 60 + int(day_sleep.split(":")[1])
            except (ValueError, AttributeError):
                wake_m, sleep_m = 420, 1380  # 7:00–23:00

            filtered = []
            for ev in raw_events:
                try:
                    h, m = map(int, ev["start_time"].split(":"))
                    ev_m = h * 60 + m
                except (ValueError, KeyError):
                    continue
                # Include events in the wake–sleep window (or sleep itself)
                if ev_m >= wake_m or ev.get("type") == "sleep":
                    filtered.append(ev)

            # --- Inject free-time gaps ---
            MIN_GAP = 15  # Only show gaps >= 15 minutes
            enriched = []
            for i, ev in enumerate(filtered):
                enriched.append(ev)
                if i < len(filtered) - 1:
                    try:
                        h1, m1 = map(int, ev["start_time"].split(":"))
                        end_m = h1 * 60 + m1 + ev.get("duration", 0)
                        h2, m2 = map(int, filtered[i + 1]["start_time"].split(":"))
                        next_m = h2 * 60 + m2
                        gap = next_m - end_m
                        if gap >= MIN_GAP:
                            gap_h, gap_min = end_m // 60, end_m % 60
                            enriched.append({
                                "start_time": f"{gap_h:02d}:{gap_min:02d}",
                                "duration": gap,
                                "activity": "",
                                "type": "free",
                                "priority": 0,
                            })
                    except (ValueError, KeyError):
                        pass

            result[day_str] = enriched

        return result

# --- MODULE TEST / USAGE EXAMPLES ---
if __name__ == "__main__":
    engine = LogicEngine()
    
    # Mock some Test Data Context for the User intents
    test_input = ParsedInput(intents=[
        # P9 Flexible Afternoon (120m)
        UserIntent(intent_type="floating_task", event_name="Study for Physics/Math Mid-terms", duration_minutes=120, priority=9, start_time_reference="afternoon"),
        
        # P8 Hard Slot (60m at 14:00)
        UserIntent(intent_type="fixed_event", event_name="Baggage Scanner YOLO project group meeting", start_time_reference="14:00", duration_minutes=60, priority=8),
        
        # P5 Flexible Evening (180m block)
        UserIntent(intent_type="floating_task", event_name="Blender animation rendering", duration_minutes=180, priority=5, start_time_reference="evening"),
        
        # P2 Flexible Evening (90m)
        UserIntent(intent_type="floating_task", event_name="Play Mass Effect", duration_minutes=90, priority=2, start_time_reference="evening")
    ])
    
    print("--- BOOTING LOGIC LAYER ---")
    engine.process_parsed_input(test_input)
    print(engine.get_context_for_ai())