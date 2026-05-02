import asyncio
import time
import unittest
from unittest.mock import patch

import app.main as main_module
from app.models import ChatRequest
from app.services.latency_metrics_service import LatencyTracker


class FakeInterruptToken:
    cancelled = False


class FakeRoute:
    def __init__(self, *, route_type="llm", intent="chat", confidence=0.4, sensitive=False):
        self.type = route_type
        self.intent = intent
        self.confidence = confidence
        self.sensitive = sensitive
        self.elapsed_ms = 5
        self.payload = {}


class FakeChatService:
    def get_or_create_session(self, session_id):
        return session_id or "session-1"


class FakeInterruptManager:
    def start(self, session_id, client_request_id):
        return FakeInterruptToken()


class RealtimeLatencyPhase3Tests(unittest.TestCase):
    def test_latency_tracker_final_snapshot_adds_response_complete(self):
        metrics = LatencyTracker()

        snapshot = metrics.snapshot(final=True)

        self.assertIn("response_complete", snapshot)
        self.assertIn("total_ms", snapshot)

    def test_jarvis_pipeline_quick_llm_route_skips_thinking_and_marks_first_token(self):
        request = ChatRequest(message="tell me something", input_source="text")
        route = FakeRoute()

        with (
            patch.object(main_module, "fast_intent_router_service", type("Router", (), {"route": lambda *args, **kwargs: route})()),
            patch.object(main_module, "acknowledgement_service", type("Ack", (), {
                "build_ack": lambda *args, **kwargs: "Let me check...",
                "phrase_generator": type("Phrase", (), {"next_phrase": lambda self: "Thinking..."})(),
            })()),
            patch.object(main_module, "chat_service", type("Chat", (), {
                "process_jarvis_message_stream": lambda *args, **kwargs: iter(["Hello there."])
            })()),
        ):
            events = list(
                main_module._jarvis_realtime_pipeline(
                    "session-1",
                    request,
                    FakeInterruptToken(),
                    LatencyTracker(),
                )
            )

        self.assertFalse(any(item.get("activity", {}).get("event") == "thinking" for item in events if isinstance(item, dict)))
        metrics_events = [item["metrics"] for item in events if isinstance(item, dict) and "metrics" in item]
        self.assertTrue(any("first_token" in payload for payload in metrics_events))
        self.assertTrue(any("first_chunk_ms" in payload for payload in metrics_events))

    def test_jarvis_pipeline_slow_llm_route_emits_delayed_thinking_then_stop(self):
        request = ChatRequest(message="tell me something", input_source="text")
        route = FakeRoute()

        def delayed_stream(*args, **kwargs):
            time.sleep(0.45)
            yield "Hello there."

        with (
            patch.object(main_module, "fast_intent_router_service", type("Router", (), {"route": lambda *args, **kwargs: route})()),
            patch.object(main_module, "acknowledgement_service", type("Ack", (), {
                "build_ack": lambda *args, **kwargs: "Let me check...",
                "phrase_generator": type("Phrase", (), {"next_phrase": lambda self: "Thinking..."})(),
            })()),
            patch.object(main_module, "chat_service", type("Chat", (), {
                "process_jarvis_message_stream": delayed_stream
            })()),
        ):
            events = list(
                main_module._jarvis_realtime_pipeline(
                    "session-1",
                    request,
                    FakeInterruptToken(),
                    LatencyTracker(),
                )
            )

        thinking_events = [item["activity"] for item in events if isinstance(item, dict) and "activity" in item and item["activity"].get("event") == "thinking"]
        self.assertEqual(thinking_events[0]["state"], "start")
        self.assertEqual(thinking_events[1]["state"], "stop")

    def test_jarvis_pipeline_warns_for_first_token_only_once(self):
        request = ChatRequest(message="tell me something", input_source="text")
        route = FakeRoute()

        with (
            patch.object(main_module, "fast_intent_router_service", type("Router", (), {"route": lambda *args, **kwargs: route})()),
            patch.object(main_module, "acknowledgement_service", type("Ack", (), {
                "build_ack": lambda *args, **kwargs: "Let me check...",
                "phrase_generator": type("Phrase", (), {"next_phrase": lambda self: "Thinking..."})(),
            })()),
            patch.object(main_module, "chat_service", type("Chat", (), {
                "process_jarvis_message_stream": lambda *args, **kwargs: iter(["Hello", " there", "."])
            })()),
            patch.object(main_module, "_warn_latency_budget") as warn_mock,
        ):
            list(
                main_module._jarvis_realtime_pipeline(
                    "session-1",
                    request,
                    FakeInterruptToken(),
                    LatencyTracker(),
                )
            )

        first_token_calls = [call for call in warn_mock.call_args_list if call.args and call.args[0] == "first_token"]
        self.assertEqual(len(first_token_calls), 1)

    def test_chat_jarvis_stream_marks_speech_end_at_request_entry(self):
        request = ChatRequest(message="hello", session_id="session-1", input_source="text")
        captured = {}

        def fake_stream_generator(session_id, chunk_iter, is_realtime, tts_enabled=False, interrupt_token=None, metrics=None):
            captured["metrics"] = metrics.snapshot()
            return iter(())

        with (
            patch.object(main_module, "chat_service", FakeChatService()),
            patch.object(main_module, "fast_intent_router_service", object()),
            patch.object(main_module, "acknowledgement_service", object()),
            patch.object(main_module, "interrupt_manager", FakeInterruptManager()),
            patch.object(main_module, "_stream_generator", fake_stream_generator),
        ):
            asyncio.run(main_module.chat_jarvis_stream(request))

        self.assertIn("speech_end", captured["metrics"])


if __name__ == "__main__":
    unittest.main()
