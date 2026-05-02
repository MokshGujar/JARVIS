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

    def test_call_staging_sets_pending_action_without_step_up(self):
        service = AutomationService()
        service.set_whatsapp_contacts_provider(lambda: [ContactCandidate(display_name="Rahul", contact_id="r1")])

        result = service.execute("call Rahul on WhatsApp")

        self.assertFalse(result["success"])
        self.assertEqual(result["action"], "whatsapp_call_pending")
        self.assertEqual(service._pending_mark_action["kind"], "whatsapp_call")
        self.assertEqual(service._pending_mark_action["payload"]["contact"], "Rahul")
        self.assertFalse(result["requires_step_up"])

    def test_message_staging_sets_pending_action_without_step_up(self):
        service = AutomationService()
        service.set_whatsapp_contacts_provider(lambda: [ContactCandidate(display_name="Aman", contact_id="a1")])

        result = service.execute("message Aman hello")

        self.assertFalse(result["success"])
        self.assertEqual(result["action"], "send_message_pending")
        self.assertEqual(service._pending_mark_action["kind"], "send_message")
        self.assertEqual(service._pending_mark_action["payload"]["receiver"], "Aman")
        self.assertEqual(service._pending_mark_action["payload"]["message"], "hello")

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

    def test_cancel_pending_call_clears_confirmation(self):
        service = AutomationService()
        service.set_whatsapp_contacts_provider(lambda: [ContactCandidate(display_name="Suhani", contact_id="s1")])
        service.execute("call Suhani on WhatsApp")

        result = service.execute("no")

        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "confirmation_cancelled")
        self.assertIsNone(service._pending_mark_action)

    def test_verified_call_start_returns_calling_status(self):
        service = AutomationService()
        service.whatsapp_desktop = Mock()
        service.whatsapp_desktop.start_call.return_value = {"success": True, "status": "whatsapp_calling", "message": "started"}

        result = service._start_whatsapp_call({"contact": "Hetanshi India", "phone_number": "+919999999999", "mode": "voice"})

        self.assertTrue(result["success"])
        self.assertEqual(result["message"], "Calling Hetanshi India...")
        self.assertEqual(result["actions"][0]["status"], "whatsapp_calling")

    def test_selector_failure_fails_closed(self):
        service = AutomationService()
        service._open_app_target = Mock(return_value={"success": True, "action": "open", "message": "Opening WhatsApp."})
        service._click_verified_whatsapp_call_button = Mock(return_value=False)

        result = service._start_whatsapp_call({"contact": "Suhani", "mode": "voice"})

        self.assertFalse(result["success"])
        self.assertEqual(result["actions"][0]["status"], "whatsapp_desktop_unverified")
        self.assertIn("did not start the call", result["message"])

    def test_confirmation_text_does_not_require_fresh_step_up(self):
        service = AutomationService()
        service.set_whatsapp_contacts_provider(lambda: [ContactCandidate(display_name="Rahul", contact_id="r1")])
        service.execute("call Rahul on WhatsApp")

        auth_text = service.pending_authorization_text("yes")
        risk = CommandRiskService().classify(auth_text, command_action="automation")

        self.assertIn("voice call Rahul on whatsapp", auth_text)
        self.assertFalse(risk.step_up_required)


if __name__ == "__main__":
    unittest.main()
