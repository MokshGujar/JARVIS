import json
import unittest
from concurrent.futures import Future
from unittest.mock import patch

import app.main as main_module
from app.services.interrupt_manager import InterruptToken
from app.services.latency_metrics_service import LatencyTracker


class FakePool:
    def submit(self, fn, text, voice, rate, volume, pitch):
        future = Future()
        future.set_result(b"audio-bytes")
        return future


class FakeInterruptManager:
    def __init__(self):
        self.finish_calls = 0

    def finish(self, token):
        self.finish_calls += 1


def _decode_events(raw_events):
    decoded = []
    for raw in raw_events:
        if not raw.startswith("data: "):
            continue
        decoded.append(json.loads(raw[6:].strip()))
    return decoded


class RealtimeStreamPhase4Tests(unittest.TestCase):
    def test_stream_generator_tags_all_events_and_audio_generation(self):
        token = InterruptToken(session_id="session-1", client_request_id="req-1")
        manager = FakeInterruptManager()
        chunk_iter = iter([
            {"ack": {"text": "Opening YouTube...", "intent": "open", "confidence": 0.9}},
            {"activity": {"event": "routing", "route": "open"}},
            {"metrics": {"fast_router_ms": 5}},
            "hello world",
        ])

        with (
            patch.object(main_module, "interrupt_manager", manager),
            patch.object(main_module, "_tts_pool", FakePool()),
        ):
            events = _decode_events(
                list(
                    main_module._stream_generator(
                        "session-1",
                        chunk_iter,
                        is_realtime=True,
                        tts_enabled=True,
                        interrupt_token=token,
                        metrics=LatencyTracker(),
                    )
                )
            )

        self.assertTrue(events)
        self.assertTrue(all(event.get("client_request_id") == "req-1" for event in events))
        audio_events = [event for event in events if "audio" in event]
        self.assertTrue(audio_events)
        self.assertTrue(all(event.get("generation_id") == "req-1" for event in audio_events))
        self.assertTrue(any(event.get("done") is True for event in events))
        self.assertEqual(manager.finish_calls, 1)

    def test_stream_generator_finishes_once_when_interrupted(self):
        token = InterruptToken(session_id="session-1", client_request_id="req-2")
        token.cancel()
        manager = FakeInterruptManager()

        with patch.object(main_module, "interrupt_manager", manager):
            events = _decode_events(
                list(
                    main_module._stream_generator(
                        "session-1",
                        iter(["hello"]),
                        is_realtime=True,
                        tts_enabled=False,
                        interrupt_token=token,
                        metrics=LatencyTracker(),
                    )
                )
            )

        self.assertEqual(manager.finish_calls, 1)
        self.assertTrue(any(event.get("activity", {}).get("event") == "interrupted" for event in events))
        self.assertTrue(all(event.get("client_request_id") == "req-2" for event in events))


if __name__ == "__main__":
    unittest.main()
