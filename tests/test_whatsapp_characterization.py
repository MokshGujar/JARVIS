import unittest
from unittest.mock import Mock

from app.services.automation_service import AutomationService
from app.services.command_risk_service import CommandRiskService
from app.services.contact_match_service import ContactCandidate


class WhatsAppCharacterizationTests(unittest.TestCase):
    def test_open_whatsapp_desktop_success_shape(self):
        service = AutomationService()
        service.whatsapp_desktop = Mock()
        service.whatsapp_desktop.open.return_value = {"success": True, "message": "opened"}

        result = service.execute("open WhatsApp")

        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "open_whatsapp")
        self.assertEqual(result["message"], "Opening WhatsApp Desktop.")
        self.assertEqual(result["actions"][0]["status"], "whatsapp")

    def test_open_whatsapp_desktop_falls_back_to_logged_in_web(self):
        service = AutomationService()
        service.whatsapp_desktop = Mock()
        service.whatsapp_desktop.open.return_value = {"success": False, "message": "desktop unavailable"}
        service.browser_control_service = Mock()
        service.browser_control_service.execute.side_effect = [
            {"success": True, "message": "Opened: https://web.whatsapp.com"},
            {"success": True, "message": "logged_in"},
        ]

        result = service.execute("open WhatsApp")

        self.assertTrue(result["success"])
        self.assertEqual(result["message"], "WhatsApp Desktop was unavailable, so I opened WhatsApp Web.")
        self.assertEqual(result["actions"][0]["status"], "whatsapp_web")

    def test_logged_out_whatsapp_web_fails_closed(self):
        service = AutomationService()
        service.browser_control_service = Mock()
        service.browser_control_service.execute.side_effect = [
            {"success": True, "message": "Opened: https://web.whatsapp.com"},
            {"success": True, "message": "not_logged_in"},
        ]

        result = service.execute("open WhatsApp web")

        self.assertFalse(result["success"])
        self.assertEqual(result["action"], "open_whatsapp_web")
        self.assertEqual(result["actions"][0]["status"], "whatsapp_login_required")
        self.assertIn("not logged in", result["message"].lower())

    def test_call_with_contact_missing_phone_asks_without_step_up(self):
        service = AutomationService()
        service.set_whatsapp_contacts_provider(lambda: [ContactCandidate(display_name="Rahul", contact_id="r1")])

        result = service.execute("call Rahul on WhatsApp")

        self.assertFalse(result["success"])
        self.assertEqual(result["action"], "whatsapp_missing_phone")
        self.assertIsNone(service._pending_mark_action)
        self.assertFalse(result["requires_step_up"])

    def test_message_with_contact_missing_phone_asks_without_step_up(self):
        service = AutomationService()
        service.set_whatsapp_contacts_provider(lambda: [ContactCandidate(display_name="Aman", contact_id="a1")])

        result = service.execute("message Aman hello")

        self.assertFalse(result["success"])
        self.assertEqual(result["action"], "whatsapp_missing_phone")
        self.assertIsNone(service._pending_mark_action)

    def test_fuzzy_contact_confirmation_precedes_action_confirmation(self):
        service = AutomationService()
        service.set_whatsapp_contacts_provider(
            lambda: [ContactCandidate(display_name="Hetanshi India", contact_id="h1", phone_number="+919999999999")]
        )

        result = service.execute("call hitanshi india")

        self.assertEqual(result["action"], "whatsapp_contact_fuzzy")
        self.assertEqual(result["message"], "I found Hetanshi India. Did you mean Hetanshi India?")
        self.assertIsNone(service._pending_mark_action)
        self.assertIsNotNone(service._pending_whatsapp_clarification)

    def test_stt_variant_requires_contact_confirmation_before_whatsapp_send(self):
        service = AutomationService()
        service.whatsapp_desktop = Mock()
        service.set_whatsapp_contacts_provider(
            lambda: [ContactCandidate(display_name="Hetanshi India", contact_id="h1", phone_number="+919999999999")]
        )

        result = service.execute("Send WhatsApp message to Hitanchi India saying hello")

        self.assertFalse(result["success"])
        self.assertEqual(result["action"], "whatsapp_contact_fuzzy")
        self.assertIn("Did you mean Hetanshi India", result["message"])
        service.whatsapp_desktop.send_message.assert_not_called()

    def test_multiple_matches_ask_which_contact(self):
        service = AutomationService()
        service.set_whatsapp_contacts_provider(
            lambda: [
                ContactCandidate(display_name="Suhani School", contact_id="s1"),
                ContactCandidate(display_name="Suhani Home", contact_id="s2"),
            ]
        )

        result = service.execute("call Suhani on WhatsApp")

        self.assertEqual(result["action"], "whatsapp_contact_ambiguous")
        self.assertIn("Which Suhani", result["message"])
        self.assertIsNone(service._pending_mark_action)

    def test_no_contact_match_fails_clearly(self):
        service = AutomationService()
        service.set_whatsapp_contacts_provider(lambda: [])

        result = service.execute("call Suhani on WhatsApp")

        self.assertEqual(result["action"], "whatsapp_contact_not_found")
        self.assertIn("couldn't find", result["message"].lower())
        self.assertIsNone(service._pending_mark_action)

    def test_cancel_without_pending_call_does_not_execute(self):
        service = AutomationService()
        service.set_whatsapp_contacts_provider(lambda: [ContactCandidate(display_name="Suhani", contact_id="s1")])
        service.execute("call Suhani on WhatsApp")

        result = service.execute("no")

        self.assertFalse(result["success"])
        self.assertIsNone(service._pending_mark_action)

    def test_verified_call_start_returns_calling_status(self):
        service = AutomationService()
        service.whatsapp_desktop = Mock()
        service.whatsapp_desktop.start_call.return_value = {"success": True, "status": "whatsapp_calling", "message": "started"}

        result = service.whatsapp_domain._start_whatsapp_call({"contact": "Hetanshi India", "phone_number": "+919999999999", "mode": "voice"})

        self.assertTrue(result["success"])
        self.assertEqual(result["message"], "Calling Hetanshi India...")
        self.assertEqual(result["actions"][0]["status"], "whatsapp_calling")

    def test_clear_whatsapp_send_executes_directly_after_policy_allow(self):
        service = AutomationService()
        service.whatsapp_desktop = Mock()
        service.whatsapp_desktop.send_message.return_value = {"success": True, "status": "whatsapp_message_sent", "message": "sent"}
        service.set_whatsapp_contacts_provider(lambda: [
            ContactCandidate(display_name="Hetanshi India", contact_id="h1", phone_number="+919999999999")
        ])

        result = service.execute("Send WhatsApp message to Hetanshi India saying hello")

        self.assertTrue(result["success"])
        self.assertEqual(result["direct_policy"]["decision"], "ALLOW")
        self.assertEqual(result["direct_policy"]["reason"], "explicit_user_command_confident_contact")
        service.whatsapp_desktop.send_message.assert_called_once_with("+919999999999", "hello")
        self.assertIsNone(service._pending_mark_action)

    def test_clear_whatsapp_call_executes_directly_after_policy_allow(self):
        service = AutomationService()
        service.whatsapp_desktop = Mock()
        service.whatsapp_desktop.start_call.return_value = {"success": True, "status": "whatsapp_calling", "message": "started"}
        service.set_whatsapp_contacts_provider(lambda: [
            ContactCandidate(display_name="Hetanshi India", contact_id="h1", phone_number="+919999999999")
        ])

        result = service.execute("Call Hetanshi India on WhatsApp")

        self.assertTrue(result["success"])
        self.assertEqual(result["direct_policy"]["decision"], "ALLOW")
        self.assertEqual(result["direct_policy"]["reason"], "explicit_user_command_confident_contact")
        service.whatsapp_desktop.start_call.assert_called_once_with("+919999999999", "voice")
        self.assertIsNone(service._pending_mark_action)

    def test_selector_failure_fails_closed(self):
        service = AutomationService()
        service.app_browser_domain._open_app_target = Mock(return_value={"success": True, "action": "open", "message": "Opening WhatsApp."})
        service.whatsapp_domain._click_verified_whatsapp_call_button = Mock(return_value=False)

        result = service.whatsapp_domain._start_whatsapp_call({"contact": "Suhani", "mode": "voice"})

        self.assertFalse(result["success"])
        self.assertEqual(result["actions"][0]["status"], "whatsapp_desktop_unverified")
        self.assertIn("did not start the call", result["message"])

    def test_missing_phone_does_not_stage_confirmation_text(self):
        service = AutomationService()
        service.set_whatsapp_contacts_provider(lambda: [ContactCandidate(display_name="Rahul", contact_id="r1")])
        service.execute("call Rahul on WhatsApp")

        auth_text = service.pending_authorization_text("yes")

        self.assertIsNone(auth_text)


if __name__ == "__main__":
    unittest.main()

