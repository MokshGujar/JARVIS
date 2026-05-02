import unittest
from unittest.mock import patch

import app.main as main_module
from app.models import ChatRequest
from app.services.acknowledgement_service import AcknowledgementService, DynamicPhraseGenerator
from app.services.automation_service import AutomationService
from app.services.fast_intent_router_service import FastIntentRouterService
from app.services.interrupt_manager import InterruptManager
from app.services.latency_metrics_service import LatencyTracker


class FakePhoneService:
    def looks_like_call_method_followup(self, message):
        return message.strip().lower() in {"normal", "whatsapp"}

    def looks_like_message_channel_followup(self, message):
        return message.strip().lower() in {"sms"}

    def looks_like_answer_request(self, message):
        return "answer" in message.lower()

    def looks_like_reject_request(self, message):
        return "reject" in message.lower()

    def looks_like_place_call_request(self, message):
        return message.lower().startswith("call ")

    def looks_like_message_request(self, message):
        return message.lower().startswith("message ")


class FakeResearchService:
    def looks_like_research_request(self, message):
        return "research" in message.lower()


class FakeAutomationService:
    APP_ALIASES = {}
    AMBIGUOUS_OPEN_TARGETS = {}
    DIRECT_OPEN_COMMANDS = {}
    DIRECT_OPEN_URIS = {}

    def __init__(self):
        self.delete_pending = False

    def has_pending_delete_confirmation(self):
        return self.delete_pending

    def has_pending_mark_confirmation(self):
        return False

    def has_pending_open_clarification(self):
        return False

    def has_pending_browser_search(self):
        return False

    def has_pending_create_file_location(self):
        return False

    def looks_like_automation_request(self, message):
        return message.lower() in {
            "lock screen",
            "volume up",
            "delete file notes.txt",
            "current time",
            "current date",
            "what time is it",
            "what date is it",
        }


class FakeInterruptToken:
    cancelled = False


class FakeRoute:
    def __init__(self, *, route_type="instant", intent="open", confidence=0.9, sensitive=False):
        self.type = route_type
        self.intent = intent
        self.confidence = confidence
        self.sensitive = sensitive
        self.elapsed_ms = 5
        self.payload = {}


class RealtimeAssistantServiceTests(unittest.TestCase):
    def test_fast_router_routes_instant_and_skips_research_vision_mixed(self):
        router = FastIntentRouterService(
            phone_command_service=FakePhoneService(),
            automation_service=FakeAutomationService(),
            research_tools_service=FakeResearchService(),
        )

        self.assertEqual(router.route("open YouTube").type, "instant")
        self.assertEqual(router.route("call Shakti").intent, "phone")
        self.assertTrue(router.route("call Shakti").sensitive)
        self.assertEqual(router.route("research AI agents").type, "llm")
        self.assertEqual(router.route("open YouTube and tell me who is Elon Musk").type, "llm")
        self.assertEqual(router.route("what is this", imgbase64="abc").type, "llm")
        self.assertTrue(router.route("research AI agents").requires_llm)

    def test_fast_router_respects_pending_destructive_clarification(self):
        automation = FakeAutomationService()
        automation.delete_pending = True
        router = FastIntentRouterService(
            phone_command_service=FakePhoneService(),
            automation_service=automation,
        )

        route = router.route("yes")

        self.assertEqual(route.type, "instant")
        self.assertEqual(route.intent, "automation")
        self.assertTrue(route.sensitive)
        self.assertTrue(route.safe_to_execute)
        self.assertTrue(route.requires_face_auth)
        self.assertEqual(route.reason, "delete_confirmation")

    def test_fast_router_adds_route_metadata_for_safe_and_sensitive_commands(self):
        router = FastIntentRouterService(
            phone_command_service=FakePhoneService(),
            automation_service=FakeAutomationService(),
        )

        open_route = router.route("open YouTube")
        self.assertEqual(open_route.intent, "automation")
        self.assertFalse(open_route.requires_llm)
        self.assertTrue(open_route.safe_to_execute)
        self.assertFalse(open_route.requires_face_auth)

        call_route = router.route("call Shakti")
        self.assertEqual(call_route.intent, "phone")
        self.assertFalse(call_route.requires_llm)
        self.assertTrue(call_route.safe_to_execute)
        self.assertTrue(call_route.requires_face_auth)

    def test_fast_router_prioritizes_whatsapp_automation_over_phone_bridge(self):
        router = FastIntentRouterService(
            phone_command_service=FakePhoneService(),
            automation_service=AutomationService(),
        )

        for command in ("Call Suhani on WhatsApp.", "tell jarvis to call Rahul", "video call Priya"):
            with self.subTest(command=command):
                route = router.route(command)
                self.assertEqual(route.type, "instant")
                self.assertEqual(route.intent, "automation")
                self.assertEqual(route.reason, "whatsapp_communication")
                self.assertFalse(route.requires_face_auth)

    def test_fast_router_routes_time_date_and_explicit_searches_deterministically(self):
        router = FastIntentRouterService(
            phone_command_service=FakePhoneService(),
            automation_service=FakeAutomationService(),
        )

        time_route = router.route("what time is it")
        self.assertEqual(time_route.type, "instant")
        self.assertEqual(time_route.intent, "automation")
        self.assertEqual(time_route.reason, "simple_system_query")

        date_route = router.route("current date")
        self.assertEqual(date_route.type, "instant")
        self.assertEqual(date_route.intent, "automation")
        self.assertEqual(date_route.reason, "simple_system_query")

        google_route = router.route("google cats")
        self.assertEqual(google_route.type, "instant")
        self.assertEqual(google_route.intent, "automation")
        self.assertTrue(google_route.safe_to_execute)

        youtube_route = router.route("youtube lo-fi beats")
        self.assertEqual(youtube_route.type, "instant")
        self.assertEqual(youtube_route.intent, "automation")
        self.assertTrue(youtube_route.safe_to_execute)

    def test_fast_router_keeps_ambiguous_free_form_search_for_llm(self):
        router = FastIntentRouterService(
            phone_command_service=FakePhoneService(),
            automation_service=FakeAutomationService(),
        )

        route = router.route("search for AI agents")

        self.assertEqual(route.type, "llm")
        self.assertTrue(route.requires_llm)

    def test_acknowledgement_service_and_dynamic_phrase_no_recent_repeat(self):
        generator = DynamicPhraseGenerator(["One", "Two", "Three", "Four"], avoid_last=3)
        seen = [generator.next_phrase() for _ in range(4)]

        self.assertEqual(len(set(seen[:4])), 4)

        service = AcknowledgementService(generator)
        route = type("Route", (), {"intent": "open", "payload": {"target": "YouTube"}, "confidence": 0.9})()
        self.assertEqual(service.build_ack(route), "Opening YouTube...")

    def test_acknowledgement_service_uses_message_for_phone_target(self):
        service = AcknowledgementService(DynamicPhraseGenerator(["One"]))
        route = type("Route", (), {"intent": "phone", "payload": {"phone_intent": "call"}, "confidence": 0.9})()
        self.assertEqual(service.build_ack(route, message="call Shakti"), "Calling Shakti...")

    def test_jarvis_pipeline_emits_ack_before_deterministic_execution(self):
        request = ChatRequest(message="open youtube", input_source="text")
        route = FakeRoute(route_type="instant", intent="open", sensitive=False)

        with (
            patch.object(main_module, "fast_intent_router_service", type("Router", (), {"route": lambda *args, **kwargs: route})()),
            patch.object(main_module, "acknowledgement_service", type("Ack", (), {"build_ack": lambda *args, **kwargs: "Opening YouTube..."})()),
            patch.object(main_module, "_execute_fast_route", return_value=("Opened YouTube.", None)) as execute_mock,
            patch.object(main_module, "_record_fast_response"),
        ):
            events = list(
                main_module._jarvis_realtime_pipeline(
                    "session-1",
                    request,
                    FakeInterruptToken(),
                    LatencyTracker(),
                )
            )

        ack_index = next(i for i, item in enumerate(events) if isinstance(item, dict) and "ack" in item)
        execute_index = next(
            i for i, item in enumerate(events)
            if isinstance(item, dict) and item.get("activity", {}).get("event") == "tasks_executing"
        )
        self.assertLess(ack_index, execute_index)
        self.assertEqual(events[ack_index]["ack"]["text"], "Opening YouTube...")
        execute_mock.assert_called_once()

    def test_interrupt_manager_marks_active_token_cancelled(self):
        manager = InterruptManager()
        token = manager.start("session-1", "req-1")

        self.assertFalse(token.cancelled)
        self.assertTrue(manager.interrupt("session-1", "req-1"))
        self.assertTrue(token.cancelled)


if __name__ == "__main__":
    unittest.main()
