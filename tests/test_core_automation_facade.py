import unittest
from unittest.mock import patch

from app.services.automation_service import AutomationService


class CoreAutomationFacadeTests(unittest.TestCase):
    def test_app_flow_delegates_through_executor_path(self):
        service = AutomationService()
        with patch.object(service, "_execute_app_launcher_command_legacy", return_value={"success": True, "action": "open", "message": "Opening notepad."}) as legacy:
            result = service._execute_app_tool("open notepad")

        self.assertTrue(result["success"])
        self.assertEqual(result["selected_tool"], "app")
        self.assertEqual(result["policy"]["decision"], "ALLOW")
        legacy.assert_called_once()

    def test_risky_file_delete_does_not_directly_execute_legacy_delete(self):
        service = AutomationService()
        with patch.object(service, "_delete_file", side_effect=AssertionError("direct delete bypass")):
            result = service._execute_file_tool("delete file notes.txt")

        self.assertEqual(result["action"], "confirmation_required")
        self.assertEqual(result["policy"]["decision"], "STEP_UP")
        self.assertTrue(result["requires_voice_permission"])
        self.assertFalse(result["requires_face_step_up"])


if __name__ == "__main__":
    unittest.main()
