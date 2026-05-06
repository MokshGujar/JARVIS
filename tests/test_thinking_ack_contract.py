import asyncio
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import app.main as main_module
from app.models import ChatRequest
from app.services.acknowledgement_service import AcknowledgementService
from app.services.interrupt_manager import InterruptToken
from app.services.latency_metrics_service import LatencyTracker


class FakeRoute:
    type = "llm"
    intent = "chat"
    confidence = 1.0
    elapsed_ms = 1
    payload = {}


async def _collect_stream(response):
    return [chunk async for chunk in response.body_iterator]


class FakeCommunicate:
    last_call = None

    def __init__(self, *, text, voice, rate, volume, pitch):
        FakeCommunicate.last_call = {"text": text, "voice": voice, "rate": rate, "volume": volume, "pitch": pitch}

    async def stream(self):
        yield {"type": "audio", "data": b"audio"}


class ThinkingAckContractTests(unittest.TestCase):
    def setUp(self):
        main_module._thinking_ack_store.clear()
        main_module._turn_voice_state.clear()
        main_module._thinking_tts_cache.clear()

    def test_realtime_thinking_activity_contains_canonical_ack(self):
        request = ChatRequest(message="tell me something", turn_id="turn-ack", client_request_id="turn-ack")

        def delayed_stream(*args, **kwargs):
            time.sleep(0.45)
            yield "Final."

        with (
            patch.object(main_module, "fast_intent_router_service", type("Router", (), {"route": lambda *args, **kwargs: FakeRoute()})()),
            patch.object(main_module, "acknowledgement_service", AcknowledgementService()),
            patch.object(main_module, "chat_service", type("Chat", (), {"process_jarvis_message_stream": delayed_stream})()),
        ):
            events = list(main_module._jarvis_realtime_pipeline("s", request, InterruptToken("s", "turn-ack"), LatencyTracker()))

        starts = [event["activity"] for event in events if isinstance(event, dict) and event.get("activity", {}).get("event") == "thinking" and event["activity"].get("state") == "start"]
        self.assertEqual(len(starts), 1)
        ack = starts[0]["ack"]
        self.assertEqual(starts[0]["message"], ack["text"])
        self.assertEqual(ack["text"], ack["tts_text"])
        self.assertEqual(ack["turn_id"], "turn-ack")
        self.assertIn("text_hash", ack)

    def test_thinking_tts_speaks_registered_ack_text(self):
        ack = AcknowledgementService().build_thinking_ack(turn_id="turn-tts", text="Let me take a look.")
        main_module._register_thinking_ack(ack)

        with patch.object(main_module.edge_tts, "Communicate", FakeCommunicate):
            response = asyncio.run(main_module.thinking_text_to_speech(SimpleNamespace(turn_id="turn-tts", request_id="turn-tts", text_hash=ack["text_hash"])))
            chunks = asyncio.run(_collect_stream(response))

        self.assertEqual(chunks, [b"audio"])
        self.assertEqual(FakeCommunicate.last_call["text"], "Let me take a look.")
        self.assertEqual(response.headers["X-Jarvis-Thinking-Hash"], ack["text_hash"])

    def test_duplicate_thinking_tts_request_is_skipped(self):
        ack = AcknowledgementService().build_thinking_ack(turn_id="turn-once", text="Sure.")
        main_module._register_thinking_ack(ack)

        with patch.object(main_module.edge_tts, "Communicate", FakeCommunicate):
            first = asyncio.run(main_module.thinking_text_to_speech(SimpleNamespace(turn_id="turn-once", request_id="turn-once", text_hash=ack["text_hash"])))
            asyncio.run(_collect_stream(first))
            second = asyncio.run(main_module.thinking_text_to_speech(SimpleNamespace(turn_id="turn-once", request_id="turn-once", text_hash=ack["text_hash"])))
            chunks = asyncio.run(_collect_stream(second))

        self.assertEqual(chunks, [])
        self.assertEqual(second.headers["X-Jarvis-Thinking-Status"], "skipped")
        self.assertEqual(second.headers["X-Jarvis-Thinking-Skip-Reason"], "duplicate")

    def test_final_started_skips_thinking_tts(self):
        ack = AcknowledgementService().build_thinking_ack(turn_id="turn-final", text="One moment.")
        main_module._register_thinking_ack(ack)
        main_module._mark_turn_voice_state("turn-final", final_started=True)

        response = asyncio.run(main_module.thinking_text_to_speech(SimpleNamespace(turn_id="turn-final", request_id="turn-final", text_hash=ack["text_hash"])))
        chunks = asyncio.run(_collect_stream(response))

        self.assertEqual(chunks, [])
        self.assertEqual(response.headers["X-Jarvis-Thinking-Skip-Reason"], "final_response_started")


if __name__ == "__main__":
    unittest.main()
