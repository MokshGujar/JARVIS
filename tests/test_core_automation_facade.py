import unittest
from unittest.mock import Mock, patch

from app.services.automation_service import AutomationService


class CoreAutomationFacadeTests(unittest.TestCase):
    def test_execute_app_command_uses_main_orchestrator_and_app_tool(self):
        service = AutomationService()
        with patch.object(service, "_execute_app_launcher_command_legacy", return_value={"success": True, "action": "open", "message": "Opening chrome."}) as legacy:
            result = service.execute("open chrome", session_id="s1", turn_id="t1")

        self.assertTrue(result["success"])
        self.assertEqual(result["selected_tool"], "app")
        self.assertEqual(result["policy"]["decision"], "ALLOW")
        self.assertIsNotNone(result.get("audit_id"))
        legacy.assert_called_once()

    def test_execute_browser_search_uses_main_orchestrator_and_browser_tool(self):
        service = AutomationService()
        service._open_url = Mock()

        result = service.execute("search google for cats", session_id="s1", turn_id="t2")

        self.assertTrue(result["success"])
        self.assertEqual(result["selected_tool"], "browser")
        self.assertEqual(result["policy"]["decision"], "ALLOW")
        self.assertEqual(result["action"], "google_search")
        service._open_url.assert_called_once()

    def test_execute_delete_file_requires_policy_before_legacy_delete(self):
        service = AutomationService()
        with patch.object(service, "_delete_file", side_effect=AssertionError("direct delete bypass")):
            result = service.execute("delete file notes.txt", session_id="s1", turn_id="t3")

        self.assertEqual(result["action"], "confirmation_required")
        self.assertEqual(result["selected_tool"], "file")
        self.assertEqual(result["policy"]["decision"], "STEP_UP")
        self.assertTrue(result["requires_voice_permission"])

    def test_execute_whatsapp_staging_uses_main_orchestrator_and_whatsapp_tool(self):
        service = AutomationService()

        result = service.execute("message Aman hello", session_id="s1", turn_id="t4")

        self.assertFalse(result["success"])
        self.assertEqual(result["selected_tool"], "whatsapp")
        self.assertEqual(result["policy"]["decision"], "ALLOW")
        self.assertEqual(result["action"], "send_message_pending")
        self.assertEqual(service._pending_mark_action["kind"], "send_message")

    def test_confirmed_whatsapp_send_replays_through_executor_policy(self):
        service = AutomationService()
        service.execute("message Aman hello", session_id="s1", turn_id="t5")

        with patch.object(service, "_send_whatsapp_message", return_value={"success": True, "action": "send_message", "message": "Sent."}) as send:
            result = service.execute("yes", session_id="s1", turn_id="t6")

        self.assertTrue(result["success"])
        self.assertEqual(result["selected_tool"], "whatsapp")
        self.assertEqual(result["policy"]["decision"], "CONFIRM")
        self.assertEqual(result["planned_action"], "send_message")
        send.assert_called_once()

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
