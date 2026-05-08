import unittest
from unittest.mock import Mock, patch

from app.services.automation_service import AutomationService


class CoreAutomationFacadeTests(unittest.TestCase):
    def test_execute_app_command_uses_main_orchestrator_and_app_tool(self):
        service = AutomationService()
        with patch("app.tools.compatibility_runners.AppCompatibilityRunner.execute", return_value={"success": True, "action": "open", "message": "Opening chrome."}) as runner:
            result = service.execute("open chrome", session_id="s1", turn_id="t1")

        self.assertTrue(result["success"])
        self.assertEqual(result["selected_tool"], "app")
        self.assertEqual(result["policy"]["decision"], "ALLOW")
        self.assertIsNotNone(result.get("audit_id"))
        runner.assert_called_once()

    def test_execute_browser_search_uses_main_orchestrator_and_browser_tool(self):
        service = AutomationService()
        service.app_browser_domain._open_url = Mock()

        result = service.execute("search google for cats", session_id="s1", turn_id="t2")

        self.assertTrue(result["success"])
        self.assertEqual(result["selected_tool"], "browser")
        self.assertEqual(result["policy"]["decision"], "ALLOW")
        self.assertEqual(result["action"], "google_search")
        service.app_browser_domain._open_url.assert_called_once()

    def test_execute_delete_file_requires_policy_before_legacy_delete(self):
        service = AutomationService()
        with patch.object(service.file_domain, "_delete_file", side_effect=AssertionError("direct delete bypass")):
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
        self.assertEqual(result["action"], "whatsapp_contact_not_found")
        self.assertIsNone(service._pending_mark_action)

    def test_confirmed_whatsapp_send_replays_through_executor_policy(self):
        service = AutomationService()
        from app.services.contact_match_service import ContactCandidate

        service.set_whatsapp_contacts_provider(lambda: [
            ContactCandidate(display_name="Hetanshi India", contact_id="h1", phone_number="+919999999999")
        ])
        service.execute("message hitanshi india hello", session_id="s1", turn_id="t5")
        staged = service.execute("yes", session_id="s1", turn_id="t6")
        self.assertEqual(staged["action"], "send_message_pending")

        with patch.object(service.whatsapp_domain, "_send_whatsapp_message", return_value={"success": True, "action": "send_message", "message": "Sent."}) as send:
            result = service.execute("yes", session_id="s1", turn_id="t7")

        self.assertTrue(result["success"])
        self.assertEqual(result["selected_tool"], "whatsapp")
        self.assertEqual(result["policy"]["decision"], "CONFIRM")
        self.assertEqual(result["planned_action"], "send_message")
        send.assert_called_once()

    def test_app_flow_delegates_through_executor_path(self):
        service = AutomationService()
        with patch("app.tools.compatibility_runners.AppCompatibilityRunner.execute", return_value={"success": True, "action": "open", "message": "Opening notepad."}) as runner:
            result = service._execute_app_tool("open notepad")

        self.assertTrue(result["success"])
        self.assertEqual(result["selected_tool"], "app")
        self.assertEqual(result["policy"]["decision"], "ALLOW")
        runner.assert_called_once()

    def test_risky_file_delete_does_not_directly_execute_legacy_delete(self):
        service = AutomationService()
        with patch.object(service.file_domain, "_delete_file", side_effect=AssertionError("direct delete bypass")):
            result = service._execute_file_tool("delete file notes.txt")

        self.assertEqual(result["action"], "confirmation_required")
        self.assertEqual(result["policy"]["decision"], "STEP_UP")
        self.assertTrue(result["requires_voice_permission"])
        self.assertFalse(result["requires_face_step_up"])


if __name__ == "__main__":
    unittest.main()

