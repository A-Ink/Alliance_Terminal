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

class ParsedInput(BaseModel):
    intents: List[UserIntent]

# --- CORE LOGIC ENGINE ---

class LogicEngine:
    def __init__(self, state_file: str = "schedule.json"):
        self.state_file = Path(SCRIPT_DIR / state_file)
        self.schedule_db: Dict[str, List[Dict[str, Any]]] = {}
        self.overflow_queue: List[Dict[str, Any]] = []
        self.user_energy: int = 100  # Volatile base, boosted/cut by logic
        self._load_state()

    def _load_state(self):
        """Loads persistent JSON state."""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r') as f:
                    data = json.load(f)
                    # Support both legacy and new formats
                    if isinstance(data, dict) and "schedules" in data:
                        self.schedule_db = data["schedules"]
                        self.user_energy = data.get("user_energy", 100)
                    else:
                        self.schedule_db = data
                        self.user_energy = 100
            except (json.JSONDecodeError, IOError):
                self.schedule_db = {}
        else:
            self.schedule_db = {}

    def _save_state(self):
        """Saves current state to disk."""
        data = {
            "schedules": self.schedule_db,
            "user_energy": self.user_energy
        }
        with open(self.state_file, 'w') as f:
            json.dump(data, f, indent=2)

    def _calculate_current_energy(self) -> Dict[str, Any]:
        """
        Synthesizes the energy score (0-100) based on biological and cognitive factors.
        """
        now = datetime.now()
        today_str = now.date().isoformat()
        
        score = self.user_energy # Start with user-reported or baseline
        penalties = []
        
        # 1. Sleep Debt Penalty (-5 per hour of debt)
        debt_mins = self._calculate_sleep_debt(today_str)
        if debt_mins > 0:
            debt_penalty = int((debt_mins / 60) * 5)
            score -= debt_penalty
            penalties.append(f"Sleep Debt: -{debt_penalty}")

        # 2. Selective Cognitive/Social Drain
        # Thinking: study, exam, code, math, logic, analysis, project, writing, research
        # Social: meeting, social, party, call, lecture, seminar, class, interview, group
        thinking_k = ["study", "exam", "code", "math", "logic", "analysis", "project", "writing", "research"]
        social_k = ["meeting", "social", "party", "call", "lecture", "seminar", "class", "interview", "group"]
        
        day_tasks = self.schedule_db.get(today_str, [])
        drain = 0
        for t in day_tasks:
            if "start_time" not in t: continue
            h, m = map(int, t['start_time'].split(':'))
            st = h * 60 + m
            # Only count completed or ongoing tasks today
            if st < now.hour * 60 + now.minute:
                activity = t['activity'].lower()
                is_taxing = any(k in activity for k in thinking_k + social_k)
                if is_taxing and t.get('priority', 5) >= 8:
                    # Drain at -10 per hour
                    task_drain = int((t['duration'] / 60) * 10)
                    drain += task_drain
        
        if drain > 0:
            score -= drain
            penalties.append(f"Cognitive/Social Drain: -{drain}")

        # 3. Post-Meal Dip (Food Coma)
        # -25 energy for 90 minutes after "Lunch" or "Dinner"
        for t in day_tasks:
            if t.get('type') == "meal" and ("lunch" in t['activity'].lower() or "dinner" in t['activity'].lower()):
                h, m = map(int, t['start_time'].split(':'))
                meal_end = h * 60 + m + t['duration']
                now_m = now.hour * 60 + now.minute
                if meal_end <= now_m < meal_end + 90:
                    score -= 25
                    penalties.append("Post-Meal Lethargy: -25")
                    break

        # 4. Recovery Boosts (Completed Tasks)
        # Powernap: +30, Snack: +15
        for t in day_tasks:
            if "start_time" not in t: continue
            h, m = map(int, t['start_time'].split(':'))
            st = h * 60 + m
            # Only count completed tasks
            if st + t['duration'] <= now.hour * 60 + now.minute:
                act = t['activity'].lower()
                if "powernap" in act:
                    score += 30
                    penalties.append("Powernap Recovery: +30")
                elif "snack" in act:
                    score += 15
                    penalties.append("Snack Boost: +15")

        score = max(0, min(100, score))
        
        # Status Label
        if score > 80: status = "EXCELLENT"
        elif score > 60: status = "NOMINAL"
        elif score > 40: status = "DEGRADED"
        elif score > 20: status = "CRITICAL"
        else: status = "EXHAUSTED"
        
        return {"score": score, "status": status, "penalties": penalties}

    def _init_day(self, target_date: str):
        """Ensures a date entry exists and runs daily biological checks."""
        if hasattr(self, "_in_init") and self._in_init == target_date:
            return
        
        if target_date not in self.schedule_db:
            self.schedule_db[target_date] = []
            
        self._in_init = target_date
        try:
            self._inject_daily_biological_anchors(target_date)
        finally:
            self._in_init = None

    def _inject_daily_biological_anchors(self, target_date: str):
        """Ensures Sleep, Wake, and Meals exist. Re-injects placeholders if missing."""
        tasks = self.schedule_db.get(target_date, [])
        activities = [t['activity'].lower() for t in tasks]
        
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
            for act in activities:
                # Fuzzy match to detect existing user version
                if name.lower() in act or act in name.lower():
                    match = True
                    break
            
            if not match:
                log.info(f"Injecting persistent placeholder for {name} on {target_date}")
                self._force_slot(target_date, start, dur, name, pri, t_type)
        
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
        
        for intent in sorted_intents:
            self._execute_intent(intent)
        self._save_state()

    def _time_to_minutes(self, hhmm: str) -> int:
        """Converts HH:MM string to absolute minutes from midnight."""
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
            intent = UserIntent(
                action=cmd.get("action", "create"),
                intent_type=cmd.get("intent_type") or ("fixed_event" if cmd.get("start_time") or cmd.get("start_time_reference") else "floating_task"),
                event_name=str(cmd.get("event_name", cmd.get("label", cmd.get("activity", "Unknown Operation")))),
                start_time_reference=cmd.get("start_time_reference", cmd.get("start_time")),
                end_time_reference=cmd.get("end_time_reference", cmd.get("end_time")),
                duration_minutes=int(cmd.get("duration_minutes", cmd.get("duration", 0))) or None,
                priority=int(cmd.get("priority", 5)),
                deadline=cmd.get("deadline")
            )
            success = self._execute_intent(intent)
            if success:
                self._save_state()
            return success
        except Exception as e:
            log.error(f"Error in execute_schedule_command bridge: {e}")
            return False

    def _parse_time_reference(self, ref: str, base_time: Optional[str] = None) -> Optional[str]:
        """Parses keywords, absolute times, and relative or hybrid offsets (19:30 +1h)."""
        if not ref: return None
        ref = ref.lower().strip().replace('.', ':')
        
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
                    resolved_base = self._parse_time_reference(base_candidate, base_time=base_time)
                    if not resolved_base: return None
                    return self._parse_time_reference(delta_candidate, base_time=resolved_base)

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
            "%H:%M",       # 20:30
            "%I:%M%p",      # 8:30pm
            "%I:%M %p",     # 8:30 pm
            "%I%p",         # 8pm
            "%I %p",        # 8 pm
            "%H",           # 20
        ]
        
        # Clean string for strptime: remove dots/spaces if needed, but waterfall handles most
        clean_ref = ref.replace(' ', '').replace('am', 'AM').replace('pm', 'PM')
        # Some formats need the space back if it was like '8 pm'
        # We'll just try both compressed and original
        for r in [clean_ref, ref.upper()]:
            for fmt in formats:
                try:
                    dt = datetime.strptime(r, fmt)
                    return dt.strftime("%H:%M")
                except ValueError:
                    continue
                    
        return None

    def _execute_intent(self, intent: UserIntent) -> bool:
        """Internal executor for a single UserIntent."""
        now = datetime.now()
        target_date = date.today().isoformat()
        name = intent.event_name.lower()
        
        # 1. DATE INFERENCE (Explicit vs Duration-Aware Guessing)
        if intent.date_reference:
            ref = intent.date_reference.lower()
            if "tomorrow" in ref:
                target_date = (date.today() + timedelta(days=1)).isoformat()
            elif "today" in ref:
                target_date = date.today().isoformat()
            else:
                try:
                    target_date = date.fromisoformat(ref).isoformat()
                except ValueError:
                    pass
        
        self._init_day(target_date)

        # 2. CONTROLLED DELETIONS/MODIFICATIONS (Context-Aware Base Time)
        base_time_for_delta = None
        if intent.action in ["delete", "modify"]:
            found = False
            search_dates = [target_date] if intent.date_reference else [date.today().isoformat(), (date.today() + timedelta(days=1)).isoformat()]
            
            for d_str in search_dates:
                tasks = self.schedule_db.get(d_str, [])
                new_tasks = []
                for t in tasks:
                    if intent.event_name.lower() in t['activity'].lower() or t['activity'].lower() in intent.event_name.lower():
                        if not found:
                            base_time_for_delta = t.get('start_time')
                            found = True
                        continue # Target found, effectively deleting it
                    new_tasks.append(t)
                
                if len(new_tasks) < len(tasks):
                    self.schedule_db[d_str] = new_tasks
                    log.info(f"Removed '{intent.event_name}' from {d_str} for processing.")
            
            if found and intent.action == "delete":
                return True
            
        # 3. TIME PARSING (Relative-Aware)
        if intent.start_time_reference:
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
                parsed = self._parse_time_reference(intent.start_time_reference, base_time=base_time_for_delta)
                if parsed:
                    intent.start_time_reference = parsed

        # Duration-aware date fallback (if no explicit date given)
        if not intent.date_reference and intent.start_time_reference and ":" in intent.start_time_reference:
            try:
                h, m = map(int, intent.start_time_reference.split(':'))
                duration = intent.duration_minutes or 60
                # Check if it completely ended in the past
                if h * 60 + m + duration < now.hour * 60 + now.minute:
                    target_date = (date.today() + timedelta(days=1)).isoformat()
                    log.info(f"Target complete past. Shifting '{intent.event_name}' to tomorrow ({target_date}).")
                elif h == 0 and m == 0 and now.hour >= 21:
                    target_date = (date.today() + timedelta(days=1)).isoformat()
            except Exception:
                pass

        self._init_day(target_date)

        # 3. IDEMPOTENT DEDUPLICATION & DELETION
        # If action is 'create', we check if a similar task already exists.
        # If so, we treat it as an OVERWRITE (modify) to prevent duplicates.
        found = False
        base_time_for_delta = None
        
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
                # If we are adding Sleep, we MUST clear any existing Wake anchors too
                if ("sleep" in name or "bedtime" in name) and ("wake" in act):
                    match = True
                
                if match:
                    if not found:
                        base_time_for_delta = t.get('start_time')
                        log.info(f"Deduplication: Detected existing '{t['activity']}' on {d_str}. Overwriting.")
                        found = True
                    continue # Exclude from new_tasks
                new_tasks.append(t)
            
            if len(new_tasks) < len(tasks):
                self.schedule_db[d_str] = new_tasks
            
        # 3.5 HALLUCINATION GUARD: If AI sends action:create for a known task name, 
        # but hallucinations a start time that differs by > 90m, we force-reconcile it.
        # EXCEPTION: Biological anchors (Sleep/Wake) and explicit shifts.
        if found and intent.action == "create" and intent.start_time_reference:
            is_bio = any(b in name for b in ["sleep", "wake", "bedtime"])
            if not is_bio:
                it_m = self._time_to_minutes(intent.start_time_reference)
                bt_m = self._time_to_minutes(base_time_for_delta)
                # Handle wrap-around (1440m)
                diff = abs(it_m - bt_m)
                if diff > 720: diff = abs(1440 - diff)
                
                if diff > 90:
                    log.warning(f"Hallucination Guard: Overriding hallucinated shift ({intent.start_time_reference}) for {intent.event_name} to preserve existing {base_time_for_delta}.")
                    intent.start_time_reference = base_time_for_delta
        
        if found and intent.action == "delete":
            return True
        
        # 4. TIME PARSING (Relative-Aware)
            
        # --- PRIORITY HIERARCHY / FLEXIBILITY RULES ---

        # --- GLOBAL BIOLOGICAL INTERCEPT ---
        if "sleep" in name or "bedtime" in name:
            # Resolve Sleep Start Time
            sleep_start_str = self._parse_time_reference(intent.start_time_reference or "23:00")
            if not sleep_start_str: sleep_start_str = "23:00"
            
            # Triggers automatic realignment
            res = self._force_slot(target_date, sleep_start_str, 420, "Sleep", 9, "sleep")
            self._align_biological_anchors(target_date)
            return res

        # --- AUTO-DURATION CALCULATOR ---
        if intent.start_time_reference and intent.end_time_reference:
            s_str = self._parse_time_reference(intent.start_time_reference)
            e_str = self._parse_time_reference(intent.end_time_reference)
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
                "task",
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

    def _force_slot(self, target_date: str, start_time: str, duration: int, activity: str, priority: int, t_type: str = "task", deadline: str = "") -> bool:
        """The Ripple Rescheduler: Evicts lower-priority overlaps and re-queues them."""
        self._init_day(target_date)
        
        # Calculate numeric time frames
        h, m = map(int, start_time.split(':'))
        new_start = h * 60 + m
        new_end = new_start + duration
        
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
                            self.schedule_db[final_date].sort(key=lambda x: x['start_time'])
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
        
        # Re-sort and save
        survivors.sort(key=lambda x: x['start_time'])
        self.schedule_db[target_date] = survivors
        
        # Attempt to re-pack evicted tasks
        for item in evicted:
            self.queue_flexible(target_date, item['activity'], item['duration'], item['priority'], "now", item.get('deadline'))
            
        return True

    def _apply_meal_sequence_constraints(self, target_date: str, activity: str, w_start: int, w_end: int) -> Tuple[int, int]:
        """Ensures Breakfast < Lunch < Dinner sequence is preserved during shifting."""
        name = activity.lower()
        order = {"breakfast": 0, "lunch": 1, "dinner": 2}
        
        # Snacks, Supper, and others are exempt
        if not any(m in name for m in order):
            return w_start, w_end
            
        current_idx = next(idx for m, idx in order.items() if m in name)
        
        # Find existing meals on this date
        meals = []
        for t in self.schedule_db.get(target_date, []):
            act = t['activity'].lower()
            if any(m in act for m in order):
                idx = next(idx for m, idx in order.items() if m in act)
                # Skip the one we are currently trying to schedule/re-schedule
                if name in act or act in name: continue
                
                m_start = self._time_to_minutes(t['start_time'])
                meals.append({"idx": idx, "start": m_start, "end": m_start + t['duration']})
        
        # Apply constraints based on order
        for m in meals:
            if m['idx'] < current_idx:
                # This is a predecessor (e.g. Lunch checking Breakfast)
                w_start = max(w_start, m['end'])
            if m['idx'] > current_idx:
                # This is a successor (e.g. Lunch checking Dinner)
                w_end = min(w_end, m['start'])
                
        # Final safety: Breakfast/Lunch cannot cross midnight (already handled by w_end usually)
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
            w_start, w_end = self._apply_meal_sequence_constraints(target_date, activity, w_start, w_end)
        elif ":" in window: # Specific time like "00:00"
            wh, wm = map(int, window.split(':'))
            w_start = wh * 60 + wm
            
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