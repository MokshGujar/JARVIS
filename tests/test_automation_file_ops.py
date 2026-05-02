import unittest
from pathlib import Path
from unittest.mock import Mock

from app.services.automation_file_ops import (
    DELETE_RECYCLE_UNAVAILABLE_MESSAGE,
    move_to_recycle_bin,
)


class AutomationFileOpsTests(unittest.TestCase):
    def test_move_to_recycle_bin_fails_closed_without_send2trash(self):
        result = move_to_recycle_bin(
            Path("notes.txt"),
            send_to_trash=None,
            is_protected_path=lambda path: False,
            display_target_name=lambda path: path.name,
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["message"], DELETE_RECYCLE_UNAVAILABLE_MESSAGE)

    def test_move_to_recycle_bin_uses_send2trash_callback(self):
        send_to_trash = Mock()
        target = Path("notes.txt")

        result = move_to_recycle_bin(
            target,
            send_to_trash=send_to_trash,
            is_protected_path=lambda path: False,
            display_target_name=lambda path: path.name,
        )

        self.assertTrue(result["success"])
        send_to_trash.assert_called_once_with(str(target))

    def test_move_to_recycle_bin_rejects_protected_path(self):
        send_to_trash = Mock()

        result = move_to_recycle_bin(
            Path("C:/Windows/notepad.exe"),
            send_to_trash=send_to_trash,
            is_protected_path=lambda path: True,
            display_target_name=lambda path: path.name,
        )

        self.assertFalse(result["success"])
        self.assertIn("protected", result["message"].lower())
        send_to_trash.assert_not_called()


if __name__ == "__main__":
    unittest.main()
