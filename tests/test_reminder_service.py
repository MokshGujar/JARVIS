import json
import shutil
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from app.services.reminder_service import ReminderService


class ReminderServiceTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parent / "_tmp" / "reminder_service"
        if self.root.exists():
            shutil.rmtree(self.root)
        self.root.mkdir(parents=True)
        self.service = ReminderService()
        self.service._store_path = self.root / "reminders.json"

    def tearDown(self):
        if self.root.exists():
            shutil.rmtree(self.root)

    def test_relative_minutes_reminder_is_saved_with_due_at(self):
        result = self.service.create_reminder("remind me in 20 minutes to check the oven")

        self.assertTrue(result["success"])
        reminders = json.loads(self.service._store_path.read_text(encoding="utf-8"))
        self.assertEqual(reminders[0]["message"], "check the oven")
        self.assertIn("due_at", reminders[0])

    def test_tomorrow_absolute_reminder_parses(self):
        result = self.service.create_reminder("remind me tomorrow at 9 AM to call mom")

        self.assertTrue(result["success"])
        reminders = json.loads(self.service._store_path.read_text(encoding="utf-8"))
        self.assertEqual(reminders[0]["message"], "call mom")

    def test_invalid_time_is_rejected(self):
        result = self.service.create_reminder("remind me to call mom at 25:99")

        self.assertFalse(result["success"])
        self.assertFalse(self.service._store_path.exists())

    def test_due_reminders_mark_due_at_entries_delivered(self):
        due_at = (datetime.now() - timedelta(minutes=1)).isoformat(timespec="seconds")
        self.service._save_reminders(
            [
                {
                    "id": "r1",
                    "message": "stand up",
                    "scheduled_for": "past",
                    "due_at": due_at,
                    "delivered": False,
                }
            ]
        )

        due = self.service.get_due_reminders()

        self.assertEqual(len(due), 1)
        self.assertEqual(due[0]["message"], "stand up")
        stored = json.loads(self.service._store_path.read_text(encoding="utf-8"))
        self.assertTrue(stored[0]["delivered"])


if __name__ == "__main__":
    unittest.main()
