import shutil
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.services import automation_service as automation_module
from app.services.automation_service import AutomationService


class AutomationServiceFileCreationTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parent / "_tmp" / "automation_service"
        if self.root.exists():
            shutil.rmtree(self.root)
        self.root.mkdir(parents=True)
        self.desktop = self.root / "Desktop"
        self.desktop.mkdir()
        self.patcher_base = patch.object(automation_module, "BASE_DIR", self.root)
        self.patcher_aliases = patch.object(
            AutomationService,
            "USER_PATH_ALIASES",
            {
                "desktop": self.desktop,
                "documents": self.root / "Documents",
                "downloads": self.root / "Downloads",
                "home": self.root,
                "music": self.root / "Music",
                "pictures": self.root / "Pictures",
                "videos": self.root / "Videos",
            },
        )
        self.patcher_base.start()
        self.patcher_aliases.start()
        self.service = AutomationService()

    def tearDown(self):
        self.patcher_aliases.stop()
        self.patcher_base.stop()
        if self.root.exists():
            shutil.rmtree(self.root)

    def test_create_file_without_location_asks_where_to_save(self):
        result = self.service.execute(
            "Create a file called test Jarvis and in that file add hello. This is written by Jarvis."
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["action"], "create_file_location_needed")
        self.assertEqual(result["message"], "Where should I save test Jarvis?")
        self.assertFalse((self.root / "test Jarvis").exists())

    def test_location_followup_creates_file_and_remembers_that_file(self):
        self.service.execute(
            "Create a file called test Jarvis and in that file add hello. This is written by Jarvis."
        )

        created = self.service.execute("Desktop")
        path = self.desktop / "test Jarvis"

        self.assertTrue(created["success"])
        self.assertEqual(path.read_text(encoding="utf-8"), "hello. This is written by Jarvis")
        self.assertEqual(created["message"], "Created test Jarvis in Desktop.")
        self.assertNotIn(str(path), created["message"])

        updated = self.service.execute("in that file add second line")
        self.assertTrue(updated["success"])
        self.assertEqual(path.read_text(encoding="utf-8"), "hello. This is written by Jarvis\nsecond line")

        full_path = self.service.execute("where is it")
        self.assertTrue(full_path["success"])
        self.assertIn(str(path), full_path["message"])

    def test_protected_location_followup_is_rejected(self):
        self.service.execute("Create a file called notes and in that file add hello.")

        result = self.service.execute(r"C:\Windows")

        self.assertFalse(result["success"])
        self.assertIn("protected", result["message"].lower())

    def test_create_file_with_content_still_asks_for_location(self):
        result = self.service.execute("create file notes with content hello")

        self.assertFalse(result["success"])
        self.assertEqual(result["message"], "Where should I save notes?")

    def test_delete_without_send2trash_does_not_permanently_delete(self):
        path = self.desktop / "do-not-delete.txt"
        path.write_text("keep me", encoding="utf-8")

        first = self.service.execute(f"delete file {path}")
        self.assertFalse(first["success"])

        with patch.object(automation_module, "send2trash", None):
            confirmed = self.service.execute("yes")

        self.assertFalse(confirmed["success"])
        self.assertIn("Send2Trash", confirmed["message"])
        self.assertTrue(path.exists())

    def test_mark_style_system_commands_use_safe_hotkeys(self):
        fake_keyboard = Mock()

        with patch.object(automation_module, "keyboard", fake_keyboard):
            result = self.service.execute("show desktop")

        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "system")
        fake_keyboard.press_and_release.assert_called_once_with("windows+d")

    def test_dangerous_system_commands_are_blocked(self):
        result = self.service.execute("shutdown the computer")

        self.assertFalse(result["success"])
        self.assertEqual(result["action"], "blocked")
        self.assertIn("blocked", result["message"].lower())

    def test_file_listing_read_find_largest_and_organize_preview(self):
        docs = self.root / "Documents"
        downloads = self.root / "Downloads"
        docs.mkdir()
        downloads.mkdir()
        report = docs / "report.pdf"
        note = docs / "note.txt"
        photo = downloads / "photo.jpg"
        report.write_bytes(b"x" * 2048)
        note.write_text("hello from note", encoding="utf-8")
        photo.write_bytes(b"y" * 100)

        listed = self.service.execute("list files in documents")
        self.assertTrue(listed["success"])
        self.assertIn("report.pdf", listed["message"])

        read = self.service.execute(f"read file {note}")
        self.assertTrue(read["success"])
        self.assertIn("hello from note", read["message"])

        found = self.service.execute("find PDFs in documents")
        self.assertTrue(found["success"])
        self.assertIn("report.pdf", found["message"])

        largest = self.service.execute("show largest files in documents")
        self.assertTrue(largest["success"])
        self.assertIn("report.pdf", largest["message"])

        preview = self.service.execute("organize folder in downloads")
        self.assertTrue(preview["success"])
        self.assertIn("Images: 1", preview["message"])
        self.assertTrue(photo.exists())


if __name__ == "__main__":
    unittest.main()
