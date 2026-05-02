import json
import logging
import re
from datetime import datetime, timedelta
from typing import Dict
from uuid import uuid4

from config import REMINDERS_DATA_DIR
from app.utils.atomic_io import write_json_atomic

logger = logging.getLogger("J.A.R.V.I.S")


class ReminderService:
    def __init__(self):
        self._store_path = REMINDERS_DATA_DIR / "reminders.json"

    def looks_like_reminder_request(self, command: str) -> bool:
        text = (command or "").strip().lower()
        return bool(
            re.search(r"\b(remind me|set (?:a )?reminder)\b", text)
            and re.search(r"\b(in|at|on|tomorrow|today)\b", text)
        )

    def create_reminder(self, command: str) -> Dict[str, str | bool]:
        parsed = self._parse_reminder(command)
        if not parsed:
            return {
                "success": False,
                "action": "reminder",
                "message": "Tell me the reminder message and when to remind you, like 'remind me to call mom at 9 pm tomorrow'.",
            }

        reminders = self._load_reminders()
        reminder = {
            "id": str(uuid4()),
            "message": parsed["message"],
            "scheduled_for": parsed["scheduled_for"],
            "due_at": parsed["due_at"],
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "source_text": command.strip(),
            "delivered": False,
        }
        reminders.append(reminder)
        self._save_reminders(reminders)
        logger.info("[REMINDER] Saved reminder for %s", parsed["scheduled_for"])
        return {
            "success": True,
            "action": "reminder",
            "message": f"Reminder set for {parsed['scheduled_for']}: {parsed['message']}.",
        }

    def _parse_reminder(self, command: str) -> dict | None:
        text = re.sub(r"\s+", " ", (command or "").strip())
        if not text:
            return None

        now = datetime.now()
        relative_patterns = [
            r"^(?:remind me|set (?:a )?reminder)\s+in\s+(?P<amount>\d+)\s+(?P<unit>minutes?|mins?|hours?|hrs?|days?)\s+to\s+(?P<message>.+)$",
            r"^(?:remind me|set (?:a )?reminder)\s+to\s+(?P<message>.+?)\s+in\s+(?P<amount>\d+)\s+(?P<unit>minutes?|mins?|hours?|hrs?|days?)$",
        ]
        for pattern in relative_patterns:
            match = re.match(pattern, text, flags=re.IGNORECASE)
            if not match:
                continue
            amount = int(match.group("amount"))
            unit = match.group("unit").lower()
            if amount <= 0:
                return None
            if unit.startswith(("min", "mins")):
                due_at = now + timedelta(minutes=amount)
            elif unit.startswith(("hour", "hr")):
                due_at = now + timedelta(hours=amount)
            else:
                due_at = now + timedelta(days=amount)
            message = match.group("message").strip().rstrip(".!?")
            if message:
                return self._build_parse_result(message, due_at)

        patterns = [
            r"^(?:remind me|set (?:a )?reminder)\s+(?P<date>tomorrow|today)\s+at\s+(?P<time>.+?)\s+to\s+(?P<message>.+)$",
            r"^(?:set (?:a )?reminder) for (?P<time>.+?) (?P<date>today|tomorrow) to (?P<message>.+)$",
            r"^(?:set (?:a )?reminder) for (?P<time>.+?) on (?P<date>.+?) to (?P<message>.+)$",
            r"^(?:remind me|set (?:a )?reminder) to (?P<message>.+?) at (?P<time>.+?) on (?P<date>.+)$",
            r"^(?:remind me|set (?:a )?reminder) to (?P<message>.+?) on (?P<date>.+?) at (?P<time>.+)$",
            r"^(?:remind me|set (?:a )?reminder) to (?P<message>.+?) at (?P<time>.+?) (?P<date>tomorrow|today)$",
            r"^(?:remind me|set (?:a )?reminder) to (?P<message>.+?) at (?P<time>.+)$",
        ]
        for pattern in patterns:
            match = re.match(pattern, text, flags=re.IGNORECASE)
            if not match:
                continue
            message = (match.groupdict().get("message") or "").strip().rstrip(".!?")
            time_text = (match.groupdict().get("time") or "").strip().rstrip(".!?")
            date_text = (match.groupdict().get("date") or "today").strip().rstrip(".!?")
            if time_text.lower().endswith(f" {date_text.lower()}"):
                time_text = time_text[: -(len(date_text) + 1)].strip()
            due_at = self._parse_due_at(date_text, time_text, now)
            if message and due_at:
                return self._build_parse_result(message, due_at)
        return None

    def _build_parse_result(self, message: str, due_at: datetime) -> dict:
        return {
            "message": message,
            "scheduled_for": due_at.strftime("%Y-%m-%d %I:%M %p").lstrip("0"),
            "due_at": due_at.isoformat(timespec="seconds"),
        }

    def _parse_due_at(self, date_text: str, time_text: str, now: datetime) -> datetime | None:
        parsed_time = self._parse_time(time_text)
        if not parsed_time:
            return None
        hour, minute = parsed_time
        date_lower = (date_text or "today").strip().lower()

        if date_lower == "today":
            due_date = now.date()
        elif date_lower == "tomorrow":
            due_date = (now + timedelta(days=1)).date()
        else:
            iso_match = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", date_lower)
            if not iso_match:
                return None
            try:
                due_date = datetime(
                    int(iso_match.group(1)),
                    int(iso_match.group(2)),
                    int(iso_match.group(3)),
                ).date()
            except ValueError:
                return None

        due_at = datetime.combine(due_date, datetime.min.time()).replace(hour=hour, minute=minute)
        if date_lower == "today" and due_at <= now:
            due_at += timedelta(days=1)
        return due_at

    def get_due_reminders(self) -> list[dict]:
        reminders = self._load_reminders()
        due = []
        now = datetime.now()

        for reminder in reminders:
            if reminder.get("delivered"):
                continue
            due_at_text = str(reminder.get("due_at", "")).strip()
            if due_at_text:
                try:
                    if datetime.fromisoformat(due_at_text) <= now:
                        reminder["delivered"] = True
                        due.append(reminder)
                    continue
                except ValueError:
                    pass

            scheduled_text = str(reminder.get("scheduled_for", "")).strip().lower()
            if not scheduled_text:
                continue

            if "today" in scheduled_text and self._time_has_passed(scheduled_text, now):
                reminder["delivered"] = True
                due.append(reminder)
            elif "tomorrow" in scheduled_text:
                continue

        if due:
            self._save_reminders(reminders)
        return due

    def _time_has_passed(self, scheduled_text: str, now: datetime) -> bool:
        match = re.search(r"at\s+(.+)$", scheduled_text)
        if not match:
            return False
        time_text = match.group(1).strip().lower()
        parsed = self._parse_time(time_text)
        if not parsed:
            return False
        due_hour, due_minute = parsed
        return (now.hour, now.minute) >= (due_hour, due_minute)

    def _parse_time(self, value: str) -> tuple[int, int] | None:
        match = re.match(r"^(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<suffix>am|pm)?$", value, flags=re.IGNORECASE)
        if not match:
            return None
        hour = int(match.group("hour"))
        minute = int(match.group("minute") or 0)
        suffix = (match.group("suffix") or "").lower()
        if suffix == "pm" and hour < 12:
            hour += 12
        if suffix == "am" and hour == 12:
            hour = 0
        if hour > 23 or minute > 59:
            return None
        return hour, minute

    def _load_reminders(self) -> list[dict]:
        if not self._store_path.exists():
            return []
        try:
            return json.loads(self._store_path.read_text(encoding="utf-8"))
        except Exception:
            return []

    def _save_reminders(self, reminders: list[dict]) -> None:
        write_json_atomic(self._store_path, reminders, indent=2, ensure_ascii=False)
