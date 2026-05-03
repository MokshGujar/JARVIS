import unittest
from unittest.mock import Mock, patch

from app.services.automation_response import normalize_automation_response
from app.services import browser_control_service as browser_module
from app.services.browser_control_service import BrowserControlService
from app.services.automation_service import AutomationService
from app.services.command_risk_service import CommandRiskService
from app.services.contact_match_service import ContactCandidate
from app.services.fast_intent_router_service import FastIntentRouterService
from app.services.task_executor import TaskExecutor
from app.services.whatsapp_desktop_automation import WhatsAppDesktopAutomation


class AutomationReliabilityTests(unittest.TestCase):
    def test_normalized_schema_preserves_message_and_adds_status_action(self):
        result = normalize_automation_response({"success": True, "action": "open", "message": "Opened."})

        self.assertTrue(result["success"])
        self.assertEqual(result["route"], "automation")
        self.assertEqual(result["spoken_text"], "Opened.")
        self.assertEqual(result["display_text"], "Opened.")
        self.assertEqual(result["message"], "Opened.")
        self.assertEqual(result["actions"][0]["type"], "show_status")

    def test_fast_router_keeps_open_play_search_on_automation_route(self):
        automation = Mock()
        router = FastIntentRouterService(automation_service=automation)

        for command in ("open youtube", "play lofi", "google search AI news", "youtube search lofi"):
            route = router.route(command)
            self.assertEqual(route.intent, "automation", command)
            self.assertTrue(route.safe_to_execute)

    def test_task_executor_forwards_automation_like_intents(self):
        automation = Mock()
        automation.execute.return_value = {"success": True, "message": "Automation ran.", "spoken_text": "Automation ran."}
        executor = TaskExecutor(automation_service=automation)

        response = executor.execute([("open", {"message": "open calculator"})])

        self.assertEqual(response.text, "Automation ran.")
        automation.execute.assert_called_once_with("open calculator")
        self.assertEqual(response.wopens, [])

    def test_low_risk_open_whatsapp_does_not_require_step_up(self):
        risk = CommandRiskService().classify("open whatsapp", command_action="automation")

        self.assertFalse(risk.step_up_required)

    def test_send_whatsapp_requires_confirmation_but_not_step_up(self):
        risk = CommandRiskService().classify("send whatsapp message to Alex saying hello", command_action="automation")

        self.assertFalse(risk.step_up_required)
        self.assertEqual(risk.reasons, [])

    def test_delete_filename_requires_step_up(self):
        risk = CommandRiskService().classify("delete notes.txt", command_action="automation")

        self.assertTrue(risk.step_up_required)
        self.assertIn("delete_files", risk.reasons)

    def test_browser_get_text_does_not_require_step_up(self):
        risk = CommandRiskService().classify("browser get text", command_action="automation")

        self.assertFalse(risk.step_up_required)

    def test_automation_semantic_probe_preserves_legacy_when_safe_execution_disabled(self):
        from app.orchestrator import semantic_planner_adapter as adapter_module

        service = AutomationService()
        with patch.object(adapter_module, "SEMANTIC_SAFE_EXECUTION_ENABLED", False):
            self.assertFalse(service.looks_like_semantic_request("put World in it", session_id="s1"))

    def test_open_chrome_followup_reuses_pending_browser_context(self):
        service = AutomationService()
        first = service._finalize_open_result("chrome", {"success": True, "action": "open", "message": "Opening Chrome."})
        service._open_url = Mock()
        second = service.execute("python docs")

        self.assertTrue(first["success"])
        self.assertEqual(second["action"], "google_search")
        self.assertIn("python docs", second["message"])
        service._open_url.assert_called_once()
        self.assertEqual(service._open_url.call_args.kwargs["browser"], "chrome")
        self.assertIsNone(service._pending_browser_search)

    def test_pending_browser_search_expires_cleanly(self):
        service = AutomationService()
        service._pending_browser_search = {
            "type": "browser_search",
            "browser": "chrome",
            "display_name": "Chrome",
            "created_at": 0,
            "expires_at": 1,
            "session_id": "browser-test",
        }

        with patch("app.services.automation_service.time.time", return_value=99):
            result = service._handle_browser_search_followup("python docs")

        self.assertFalse(result["success"])
        self.assertEqual(result["action"], "search")
        self.assertIsNone(service._pending_browser_search)

    def test_pending_browser_search_ignores_simple_non_query_followup(self):
        service = AutomationService()
        service._pending_browser_search = {
            "type": "browser_search",
            "browser": "chrome",
            "display_name": "Chrome",
            "created_at": 1,
            "expires_at": 1000,
            "session_id": "browser-test",
        }

        with patch("app.services.automation_service.time.time", return_value=100):
            result = service._handle_browser_search_followup("thanks")

        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "search")
        self.assertIn("ready", result["message"].lower())

    def test_incomplete_file_name_asks_for_followup(self):
        service = AutomationService()

        result = service.execute("create a file on my desktop named")

        self.assertFalse(result["success"])
        self.assertEqual(result["message"], "What should I name it?")
        self.assertIsNotNone(service._pending_incomplete_command)

    def test_incomplete_file_content_asks_for_followup(self):
        service = AutomationService()

        result = service.execute("create a file on my desktop named test Jarvis and write")

        self.assertFalse(result["success"])
        self.assertEqual(result["message"], "What should I write in it?")
        self.assertIsNotNone(service._pending_incomplete_command)

    def test_incomplete_browser_search_asks_for_followup(self):
        service = AutomationService()

        result = service.execute("open Chrome and search for")

        self.assertFalse(result["success"])
        self.assertEqual(result["message"], "What should I search for?")
        self.assertIsNotNone(service._pending_incomplete_command)

    def test_incomplete_browser_search_followup_completes_action(self):
        service = AutomationService()
        service._open_url = Mock()

        first = service.execute("open Chrome and search for")
        second = service.execute("Python docs")

        self.assertEqual(first["message"], "What should I search for?")
        self.assertEqual(second["action"], "google_search")
        self.assertIn("Python docs", second["message"])
        service._open_url.assert_called_once()
        self.assertIsNone(service._pending_incomplete_command)

    def test_stale_incomplete_pending_action_expires(self):
        service = AutomationService()
        service._pending_incomplete_command = {
            "kind": "browser_search",
            "template": "open Chrome and search for {answer}",
            "created_at": 1,
            "expires_at": 2,
        }

        with patch("app.services.automation_service.time.time", return_value=99):
            result = service.execute("Python docs")

        self.assertFalse(result["success"])
        self.assertIsNone(service._pending_incomplete_command)

    def test_unrelated_incomplete_followup_does_not_execute_stale_action(self):
        service = AutomationService()
        service._pending_incomplete_command = {
            "kind": "browser_search",
            "template": "open Chrome and search for {answer}",
            "created_at": 1,
            "expires_at": 1000,
        }
        service._open_url = Mock()

        with patch("app.services.automation_service.time.time", return_value=100):
            result = service.execute("thanks")

        self.assertEqual(result["action"], "clarification_cancelled")
        service._open_url.assert_not_called()

    def test_end_call_is_low_risk_scoped_action(self):
        risk = CommandRiskService().classify("end call", command_action="automation")

        self.assertFalse(risk.step_up_required)

    def test_whatsapp_desktop_unverified_does_not_fake_send_success(self):
        service = AutomationService()
        service._open_app_target = Mock(return_value={"success": True, "action": "open", "message": "Opening WhatsApp."})

        result = service._send_whatsapp_message({"receiver": "Alex", "message": "hello"})

        self.assertFalse(result["success"])
        self.assertEqual(result["actions"][0]["type"], "show_status")
        self.assertIn("did not send", result["message"].lower())

    def test_whatsapp_web_fallback_only_reports_success_when_logged_in(self):
        service = AutomationService()
        fake_browser = Mock()
        fake_browser.execute.side_effect = [
            {"success": True, "action": "browser_control", "message": "Opened: https://web.whatsapp.com"},
            {"success": True, "action": "browser_control", "message": "not_logged_in"},
        ]
        service.browser_control_service = fake_browser

        result = service._open_whatsapp_web()

        self.assertFalse(result["success"])
        self.assertIn("not logged in", result["message"].lower())

    def test_pending_confirmation_uses_original_high_risk_text(self):
        service = AutomationService()
        service._pending_mark_action = {
            "kind": "send_message",
            "payload": {"platform": "whatsapp", "receiver": "Alex", "message": "hello"},
        }

        auth_text = service.pending_authorization_text("yes")

        self.assertIn("send whatsapp message", auth_text)
        self.assertIn("Alex", auth_text)

    def test_open_whatsapp_and_call_someone_opens_then_asks_for_contact_without_step_up(self):
        service = AutomationService()
        service._open_whatsapp_desktop_or_web = Mock(return_value={
            "success": True,
            "action": "open_whatsapp",
            "message": "Opening WhatsApp Desktop.",
            "actions": [{"type": "show_status", "status": "whatsapp", "message": "Opening WhatsApp Desktop."}],
        })

        result = service.execute("open WhatsApp and call someone")

        service._open_whatsapp_desktop_or_web.assert_called_once()
        self.assertFalse(result["success"])
        self.assertEqual(result["message"], "Who should I call on WhatsApp?")
        self.assertEqual(result["spoken_text"], "Who should I call on WhatsApp?")
        self.assertIsNone(service._pending_mark_action)
        self.assertEqual(service._pending_whatsapp_clarification["kind"], "whatsapp_call")
        self.assertTrue(any(action.get("status") == "whatsapp_contact_required" for action in result["actions"]))
        self.assertFalse(result["requires_step_up"])

    def test_open_whatsapp_and_call_named_contact_stages_confirmation_without_step_up(self):
        service = AutomationService()
        service._open_whatsapp_desktop_or_web = Mock(return_value={
            "success": True,
            "action": "open_whatsapp",
            "message": "Opening WhatsApp Desktop.",
            "actions": [{"type": "show_status", "status": "whatsapp", "message": "Opening WhatsApp Desktop."}],
        })

        result = service.execute("open WhatsApp and call Hitanshi India")

        self.assertEqual(result["action"], "multi_action")
        self.assertIn("Ready to call Hitanshi India on WhatsApp", result["message"])
        self.assertEqual(service._pending_mark_action["kind"], "whatsapp_call")
        self.assertEqual(service._pending_mark_action["payload"]["contact"], "Hitanshi India")
        self.assertTrue(any(action.get("status") == "whatsapp_call_pending" for action in result["actions"]))
        self.assertFalse(result["requires_step_up"])

    def test_call_someone_asks_for_contact_and_never_uses_appopener(self):
        service = AutomationService()
        service._appopener_available = True

        with patch("app.services.automation_service.appopener_open") as mocked_open:
            result = service.execute("call someone")

        mocked_open.assert_not_called()
        self.assertFalse(result["success"])
        self.assertEqual(result["message"], "Who should I call on WhatsApp?")
        self.assertEqual(service._pending_whatsapp_clarification["kind"], "whatsapp_call")
        self.assertIsNone(service._pending_mark_action)

    def test_whatsapp_contact_followup_turns_clarification_into_call_confirmation(self):
        service = AutomationService()
        first = service.execute("call someone")
        second = service.execute("Rahul")

        self.assertEqual(first["message"], "Who should I call on WhatsApp?")
        self.assertFalse(second["success"])
        self.assertEqual(second["action"], "whatsapp_call_pending")
        self.assertIn("Rahul", second["message"])
        self.assertEqual(service._pending_mark_action["kind"], "whatsapp_call")
        self.assertEqual(service._pending_mark_action["payload"]["contact"], "Rahul")
        self.assertIsNone(service._pending_whatsapp_clarification)
        self.assertFalse(second["requires_step_up"])

    def test_whatsapp_call_with_contact_stages_confirmation_without_step_up(self):
        service = AutomationService()

        result = service.execute("call Rahul on WhatsApp")
        auth_text = service.pending_authorization_text("yes")
        risk = CommandRiskService().classify(auth_text, command_action="automation")

        self.assertFalse(result["success"])
        self.assertEqual(result["action"], "whatsapp_call_pending")
        self.assertEqual(service._pending_mark_action["payload"]["contact"], "Rahul")
        self.assertFalse(result["requires_step_up"])
        self.assertIn("call Rahul on whatsapp", auth_text)
        self.assertFalse(risk.step_up_required)

    def test_tell_jarvis_to_call_suhani_routes_as_whatsapp_confirmation(self):
        service = AutomationService()
        service.set_whatsapp_contacts_provider(lambda: [ContactCandidate(display_name="Suhani", contact_id="s1")])

        result = service.execute("tell jarvis to call Suhani")

        self.assertFalse(result["success"])
        self.assertEqual(result["action"], "whatsapp_call_pending")
        self.assertEqual(result["message"], "Ready to call Suhani on WhatsApp. Say yes to continue or no to cancel.")
        self.assertEqual(service._pending_mark_action["payload"]["contact"], "Suhani")
        self.assertEqual(service._pending_mark_action["payload"]["contact_id"], "s1")
        self.assertFalse(result["requires_step_up"])

    def test_generic_whatsapp_contact_parsing_is_not_name_specific(self):
        contacts = [
            ContactCandidate(display_name="Rahul", contact_id="c1"),
            ContactCandidate(display_name="Mom", contact_id="c2", aliases=["mother"]),
            ContactCandidate(display_name="Neha", contact_id="c3"),
            ContactCandidate(display_name="Priya", contact_id="c4"),
            ContactCandidate(display_name="Aman", contact_id="c5"),
        ]
        cases = [
            ("tell jarvis to call Rahul", "whatsapp_call_pending", "Rahul", "voice"),
            ("tell jarvis to call Mom", "whatsapp_call_pending", "Mom", "voice"),
            ("call Neha on WhatsApp", "whatsapp_call_pending", "Neha", "voice"),
            ("video call Priya", "whatsapp_call_pending", "Priya", "video"),
        ]

        for command, action, contact, mode in cases:
            with self.subTest(command=command):
                service = AutomationService()
                service.set_whatsapp_contacts_provider(lambda contacts=contacts: contacts)
                result = service.execute(command)
                self.assertEqual(result["action"], action)
                self.assertEqual(service._pending_mark_action["payload"]["contact"], contact)
                self.assertEqual(service._pending_mark_action["payload"]["mode"], mode)
                self.assertIn(contact, result["message"])

        service = AutomationService()
        service.set_whatsapp_contacts_provider(lambda: contacts)
        result = service.execute("message Aman hello")
        self.assertEqual(result["action"], "send_message_pending")
        self.assertEqual(service._pending_mark_action["kind"], "send_message")
        self.assertEqual(service._pending_mark_action["payload"]["receiver"], "Aman")
        self.assertEqual(service._pending_mark_action["payload"]["message"], "hello")

    def test_whatsapp_call_multiple_contact_matches_asks_which_contact(self):
        service = AutomationService()
        service.set_whatsapp_contacts_provider(lambda: [
            ContactCandidate(display_name="Suhani School", contact_id="s1"),
            ContactCandidate(display_name="Suhani Home", contact_id="s2"),
        ])

        result = service.execute("call Suhani on WhatsApp")

        self.assertFalse(result["success"])
        self.assertEqual(result["action"], "whatsapp_contact_ambiguous")
        self.assertIn("Which Suhani", result["message"])
        self.assertIsNotNone(service._pending_whatsapp_clarification)
        self.assertIsNone(service._pending_mark_action)

    def test_whatsapp_call_no_contact_match_does_not_stage_call(self):
        service = AutomationService()
        service.set_whatsapp_contacts_provider(lambda: [])

        result = service.execute("call Suhani on WhatsApp")

        self.assertFalse(result["success"])
        self.assertEqual(result["action"], "whatsapp_contact_not_found")
        self.assertIn("couldn't find", result["message"].lower())
        self.assertIsNone(service._pending_mark_action)

    def test_whatsapp_call_typo_asks_did_you_mean_before_action_confirmation(self):
        service = AutomationService()
        service.whatsapp_desktop = Mock()
        service.set_whatsapp_contacts_provider(lambda: [
            ContactCandidate(display_name="Hetanshi India", contact_id="h1", phone_number="+919999999999"),
        ])

        result = service.execute("call hitanshi india")

        self.assertFalse(result["success"])
        self.assertEqual(result["action"], "whatsapp_contact_fuzzy")
        self.assertEqual(result["message"], "I found Hetanshi India. Did you mean Hetanshi India?")
        self.assertIsNotNone(service._pending_whatsapp_clarification)
        self.assertIsNone(service._pending_mark_action)
        service.whatsapp_desktop.start_call.assert_not_called()

    def test_whatsapp_contact_confirmation_creates_action_confirmation(self):
        service = AutomationService()
        service.set_whatsapp_contacts_provider(lambda: [
            ContactCandidate(display_name="Hetanshi India", contact_id="h1", phone_number="+919999999999"),
        ])

        first = service.execute("call hitanshi india")
        second = service.execute("yes")

        self.assertEqual(first["action"], "whatsapp_contact_fuzzy")
        self.assertEqual(second["action"], "whatsapp_call_pending")
        self.assertEqual(service._pending_mark_action["kind"], "whatsapp_call")
        self.assertEqual(service._pending_mark_action["payload"]["contact"], "Hetanshi India")
        self.assertEqual(service._pending_mark_action["payload"]["phone_number"], "+919999999999")
        self.assertFalse(second["requires_step_up"])

    def test_whatsapp_action_confirmation_text_does_not_require_fresh_step_up(self):
        service = AutomationService()
        service.set_whatsapp_contacts_provider(lambda: [
            ContactCandidate(display_name="Hetanshi India", contact_id="h1", phone_number="+919999999999"),
        ])
        service.execute("call hitanshi india")
        service.execute("yes")

        auth_text = service.pending_authorization_text("yes")
        risk = CommandRiskService().classify(auth_text, command_action="automation")

        self.assertIn("voice call Hetanshi India on whatsapp", auth_text)
        self.assertFalse(risk.step_up_required)

    def test_confirmation_prompt_spoken_once_per_pending_action_id(self):
        service = AutomationService()
        service.set_whatsapp_contacts_provider(lambda: [ContactCandidate(display_name="Suhani", contact_id="s1")])

        first = service.execute("call Suhani on WhatsApp")
        duplicate = service.execute("maybe")

        self.assertEqual(first["action"], "whatsapp_call_pending")
        self.assertIn("Say yes to continue or no to cancel", first["spoken_text"])
        self.assertEqual(first["pending_action_id"], duplicate["pending_action_id"])
        self.assertNotIn("Say yes to continue or no to cancel", duplicate["message"])
        self.assertEqual(duplicate["spoken_text"], "")

    def test_new_pending_action_gets_prompt_after_cancel_clears_prompt_state(self):
        service = AutomationService()
        service.set_whatsapp_contacts_provider(lambda: [ContactCandidate(display_name="Suhani", contact_id="s1")])

        first = service.execute("call Suhani on WhatsApp")
        cancelled = service.execute("no")
        second = service.execute("call Suhani on WhatsApp")

        self.assertEqual(cancelled["action"], "confirmation_cancelled")
        self.assertEqual(first["pending_action_id"], second["pending_action_id"])
        self.assertIn("Say yes to continue or no to cancel", second["spoken_text"])

    def test_duplicate_confirmation_stream_result_has_no_spoken_text(self):
        from app.capabilities.automation import AutomationCapability
        from app.core.contracts import AssistantContext

        service = AutomationService()
        service.set_whatsapp_contacts_provider(lambda: [ContactCandidate(display_name="Suhani", contact_id="s1")])
        capability = AutomationCapability(service)
        context = AssistantContext(session_id="session-1", message="call Suhani on WhatsApp")
        first = capability.execute(context)
        duplicate_context = AssistantContext(session_id="session-1", message="maybe")
        duplicate = capability.execute(duplicate_context)

        self.assertIn("Say yes to continue or no to cancel", first.text)
        self.assertEqual(duplicate.text, "")

    def test_whatsapp_message_typo_repairs_multi_word_contact_and_waits(self):
        service = AutomationService()
        service.whatsapp_desktop = Mock()
        service.set_whatsapp_contacts_provider(lambda: [
            ContactCandidate(display_name="Hetanshi India", contact_id="h1", phone_number="+919999999999"),
        ])

        result = service.execute("message hitanshi india hello")

        self.assertEqual(result["action"], "whatsapp_contact_fuzzy")
        self.assertIn("Hetanshi India", result["message"])
        self.assertIsNone(service._pending_mark_action)
        service.whatsapp_desktop.send_message.assert_not_called()

    def test_whatsapp_message_contact_confirmation_preserves_message_text(self):
        service = AutomationService()
        service.set_whatsapp_contacts_provider(lambda: [
            ContactCandidate(display_name="Hetanshi India", contact_id="h1", phone_number="+919999999999"),
        ])

        service.execute("message hitanshi india hello")
        result = service.execute("yes")

        self.assertEqual(result["action"], "send_message_pending")
        self.assertEqual(service._pending_mark_action["payload"]["receiver"], "Hetanshi India")
        self.assertEqual(service._pending_mark_action["payload"]["message"], "hello")
        self.assertEqual(service._pending_mark_action["payload"]["phone_number"], "+919999999999")

    def test_whatsapp_call_confirmation_cancel_clears_pending_call(self):
        service = AutomationService()
        service.set_whatsapp_contacts_provider(lambda: [ContactCandidate(display_name="Suhani", contact_id="s1")])
        service.execute("call Suhani on WhatsApp")

        result = service.execute("no")

        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "confirmation_cancelled")
        self.assertIsNone(service._pending_mark_action)

    def test_whatsapp_call_ui_selector_failure_fails_closed(self):
        service = AutomationService()
        service._open_app_target = Mock(return_value={"success": True, "action": "open", "message": "Opening WhatsApp."})
        service._click_verified_whatsapp_call_button = Mock(return_value=False)

        result = service._start_whatsapp_call({"contact": "Suhani", "mode": "voice"})

        self.assertFalse(result["success"])
        self.assertEqual(result["actions"][0]["status"], "whatsapp_desktop_unverified")
        self.assertIn("did not start the call", result["message"])

    def test_whatsapp_call_verified_start_returns_calling_hud_status(self):
        service = AutomationService()
        service._open_app_target = Mock(return_value={"success": True, "action": "open", "message": "Opening WhatsApp."})
        service._click_verified_whatsapp_call_button = Mock(return_value=True)

        result = service._start_whatsapp_call({"contact": "Suhani", "mode": "voice"})

        self.assertTrue(result["success"])
        self.assertEqual(result["message"], "Calling Suhani...")
        self.assertEqual(result["actions"][0]["status"], "whatsapp_calling")

    def test_whatsapp_desktop_uri_launch_mocked_for_verified_call(self):
        service = AutomationService()
        service.whatsapp_desktop = Mock()
        service.whatsapp_desktop.start_call.return_value = {"success": True, "status": "whatsapp_calling", "message": "WhatsApp call started."}

        result = service._start_whatsapp_call({"contact": "Hetanshi India", "phone_number": "+919999999999", "mode": "voice"})

        self.assertTrue(result["success"])
        service.whatsapp_desktop.start_call.assert_called_once_with("+919999999999", "voice")
        self.assertEqual(result["actions"][0]["status"], "whatsapp_calling")

    def test_whatsapp_desktop_call_ui_not_verified_fails_closed(self):
        service = AutomationService()
        service.whatsapp_desktop = Mock()
        service.whatsapp_desktop.start_call.return_value = {
            "success": False,
            "status": "whatsapp_call_unverified",
            "message": "Jarvis clicked the call control, but could not verify that the call UI appeared.",
        }

        result = service._start_whatsapp_call({"contact": "Hetanshi India", "phone_number": "+919999999999", "mode": "voice"})

        self.assertFalse(result["success"])
        self.assertEqual(result["actions"][0]["status"], "whatsapp_call_unverified")
        self.assertIn("could not verify", result["message"])

    def test_whatsapp_desktop_send_mocked_and_verified(self):
        service = AutomationService()
        service.whatsapp_desktop = Mock()
        service.whatsapp_desktop.send_message.return_value = {"success": True, "status": "whatsapp_message_sent", "message": "WhatsApp message sent."}

        result = service._send_whatsapp_message({"receiver": "Hetanshi India", "phone_number": "+919999999999", "message": "hello"})

        self.assertTrue(result["success"])
        service.whatsapp_desktop.send_message.assert_called_once_with("+919999999999", "hello")
        self.assertEqual(result["actions"][0]["status"], "whatsapp_message_sent")

    def test_whatsapp_desktop_send_unverified_fails_closed(self):
        service = AutomationService()
        service.whatsapp_desktop = Mock()
        service.whatsapp_desktop.send_message.return_value = {
            "success": False,
            "status": "whatsapp_send_unverified",
            "message": "Jarvis could not verify the WhatsApp send control. I did not send the message.",
        }

        result = service._send_whatsapp_message({"receiver": "Hetanshi India", "phone_number": "+919999999999", "message": "hello"})

        self.assertFalse(result["success"])
        self.assertEqual(result["actions"][0]["status"], "whatsapp_send_unverified")
        self.assertIn("did not send", result["message"])

    def test_whatsapp_desktop_builds_safe_send_uri(self):
        uri = WhatsAppDesktopAutomation().build_send_uri("+91 99999 99999", "hello there")

        self.assertEqual(uri, "whatsapp://send?phone=+919999999999&text=hello%20there")

    def test_ambiguous_whatsapp_placeholders_request_contact(self):
        service = AutomationService()

        for command in (
            "call somebody",
            "call him",
            "call her",
            "call them",
            "message someone",
            "send message to someone",
        ):
            with self.subTest(command=command):
                service._pending_whatsapp_clarification = None
                result = service.execute(command)
                self.assertFalse(result["success"])
                self.assertEqual(result["actions"][0]["status"], "whatsapp_contact_required")
                self.assertIsNotNone(service._pending_whatsapp_clarification)

    def test_browser_control_reports_playwright_install_guidance_when_unavailable(self):
        with patch.object(browser_module, "async_playwright", None), patch.object(browser_module, "PLAYWRIGHT_IMPORT_ERROR", "missing"):
            result = BrowserControlService().execute("search", query="python docs")

        self.assertFalse(result["success"])
        self.assertIn("python -m playwright install chromium", result["message"])

    def test_pending_create_file_state_is_session_scoped(self):
        service = AutomationService()
        first = service.execute("create file notes with content hello", session_id="a")
        second = service.execute("Desktop", session_id="b")

        self.assertFalse(first["success"])
        self.assertFalse(second["success"])
        self.assertIn("unsupported", second["action"])


if __name__ == "__main__":
    unittest.main()
