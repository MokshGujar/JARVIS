import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services import automation_service as automation_module
from app.services.automation_service import AutomationService
from app.services.command_risk_service import CommandRiskService


class FileCharacterizationTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parent / "_tmp" / "file_characterization"
        if self.root.exists():
            shutil.rmtree(self.root)
        self.root.mkdir(parents=True)
        self.desktop = self.root / "Desktop"
        self.documents = self.root / "Documents"
        self.downloads = self.root / "Downloads"
        for folder in (self.desktop, self.documents, self.downloads):
            folder.mkdir()
        self.base_patcher = patch.object(automation_module, "BASE_DIR", self.root)
        self.alias_patcher = patch.object(
            AutomationService,
            "USER_PATH_ALIASES",
            {
                "desktop": self.desktop,
                "documents": self.documents,
                "downloads": self.downloads,
                "home": self.root,
                "music": self.root / "Music",
                "pictures": self.root / "Pictures",
                "videos": self.root / "Videos",
            },
        )
        self.base_patcher.start()
        self.alias_patcher.start()
        self.service = AutomationService()

    def tearDown(self):
        self.alias_patcher.stop()
        self.base_patcher.stop()
        if self.root.exists():
            shutil.rmtree(self.root)

    def test_create_file_on_desktop(self):
        result = self.service.execute("create file test.txt on desktop")

        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "create_file")
        self.assertEqual(result["message"], "Created test.txt in Desktop.")
        self.assertTrue((self.desktop / "test.txt").exists())

    def test_create_folder_in_documents(self):
        result = self.service.execute("create folder ML Projects in documents")

        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "create_folder")
        self.assertTrue((self.documents / "ML Projects").is_dir())
        self.assertIn("Folder ML Projects created", result["message"])

    def test_list_files_in_downloads(self):
        (self.downloads / "one.txt").write_text("one", encoding="utf-8")
        (self.downloads / "folder").mkdir()

        result = self.service.execute("list files in downloads")

        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "list_files")
        self.assertIn("[folder] folder/", result["message"])
        self.assertIn("[file] one.txt", result["message"])

    def test_read_file_by_recent_name(self):
        path = self.root / "test.txt"
        path.write_text("hello", encoding="utf-8")

        result = self.service.execute("read file test.txt")

        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "read_file")
        self.assertIn("test.txt:\nhello", result["message"])

    def test_find_pdfs_in_downloads(self):
        (self.downloads / "paper.pdf").write_bytes(b"pdf")
        (self.downloads / "note.txt").write_text("note", encoding="utf-8")

        result = self.service.execute("find pdfs in downloads")

        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "find_files")
        self.assertIn("paper.pdf", result["message"])
        self.assertNotIn("note.txt", result["message"])

    def test_find_files_named_resume(self):
        (self.root / "resume-final.txt").write_text("resume", encoding="utf-8")

        result = self.service.execute("find files named resume")

        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "find_files")
        self.assertIn("resume-final.txt", result["message"])

    def test_rename_move_and_delete_confirmation_flow_uses_recycle_bin(self):
        source = self.desktop / "test.txt"
        source.write_text("hello", encoding="utf-8")

        renamed = self.service.execute(f"rename file {source} to notes.txt")

        self.assertFalse(renamed["success"])
        self.assertEqual(renamed["action"], "confirmation_required")
        self.assertTrue(renamed["requires_confirmation"])
        self.assertTrue(source.exists())

    def test_existing_destination_blocks_rename_and_move_without_overwrite(self):
        source = self.desktop / "test.txt"
        destination = self.desktop / "notes.txt"
        source.write_text("source", encoding="utf-8")
        destination.write_text("destination", encoding="utf-8")

        renamed = self.service.execute(f"rename file {source} to notes.txt")

        self.assertFalse(renamed["success"])
        self.assertEqual(renamed["action"], "confirmation_required")
        self.assertTrue(renamed["requires_confirmation"])
        self.assertEqual(source.read_text(encoding="utf-8"), "source")
        self.assertEqual(destination.read_text(encoding="utf-8"), "destination")

        other = self.documents / "test.txt"
        other.write_text("other", encoding="utf-8")
        moved = self.service.execute(f"move file {source} to documents")

        self.assertFalse(moved["success"])
        self.assertEqual(moved["action"], "confirmation_required")
        self.assertTrue(moved["requires_confirmation"])
        self.assertTrue(source.exists())

    def test_protected_windows_and_appdata_paths_are_blocked(self):
        for command in (
            r"create file C:\Windows\jarvis.txt",
            r"read file C:\Users\Moksh\AppData\secret.txt",
        ):
            with self.subTest(command=command):
                result = self.service.execute(command)
                self.assertFalse(result["success"])
                self.assertIn("protected", result["message"].lower())

    def test_delete_requires_confirmation_and_risk_service_requires_step_up(self):
        target = self.desktop / "notes.txt"
        target.write_text("hello", encoding="utf-8")

        result = self.service.execute(f"delete file {target}")
        risk = CommandRiskService().classify(f"delete file {target}", command_action="automation")

        self.assertFalse(result["success"])
        self.assertEqual(result["action"], "confirmation_required")
        self.assertTrue(result["requires_confirmation"])
        self.assertTrue(result["requires_voice_permission"])
        self.assertFalse(result["requires_face_step_up"])
        self.assertTrue(risk.step_up_required)

    def test_ambiguous_file_reference_fails_without_wrong_execution(self):
        result = self.service.execute("read file it")

        self.assertFalse(result["success"])
        self.assertEqual(result["action"], "read_file")
        self.assertIn("I don't know which file", result["message"])


if __name__ == "__main__":
    unittest.main()
