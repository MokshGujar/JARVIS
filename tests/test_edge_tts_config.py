import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

import app.main as main_module


async def _collect_stream(response):
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk)
    return chunks


class FakeCommunicate:
    last_call = None

    def __init__(self, *, text, voice, rate, volume, pitch):
        self.text = text
        self.voice = voice
        self.rate = rate
        self.volume = volume
        self.pitch = pitch
        FakeCommunicate.last_call = {
            "text": text,
            "voice": voice,
            "rate": rate,
            "volume": volume,
            "pitch": pitch,
        }

    async def stream(self):
        yield {"type": "audio", "data": b"audio"}


class EdgeTtsConfigTests(unittest.TestCase):
    def tearDown(self):
        main_module._tts_request_generation = 0
        main_module._last_thinking_phrase = None

    def test_tts_runtime_config_uses_safe_defaults_for_invalid_values(self):
        with (
            patch.object(main_module, "EDGE_TTS_RATE", "fast"),
            patch.object(main_module, "EDGE_TTS_VOLUME", "loud"),
            patch.object(main_module, "EDGE_TTS_PITCH", "high"),
        ):
            config = main_module._tts_runtime_config()

        self.assertEqual(config["provider"], "edge_tts")
        self.assertEqual(config["rate"], "+20%")
        self.assertEqual(config["volume"], "+0%")
        self.assertEqual(config["pitch"], "+0Hz")

    def test_health_exposes_tts_and_stt_runtime_metadata(self):
        payload = asyncio.run(main_module.health())

        self.assertEqual(payload["tts"]["provider"], "edge_tts")
        self.assertIn("voice", payload["tts"])
        self.assertIn("rate", payload["tts"])
        self.assertIn("fast_rate", payload["tts"])
        self.assertIn("volume", payload["tts"])
        self.assertIn("pitch", payload["tts"])
        self.assertIn("thinking_audio", payload["tts"])
        self.assertTrue(payload["tts"]["thinking_audio"]["enabled"])
        self.assertTrue(payload["tts"]["thinking_audio"]["finish_before_final_tts"])
        self.assertFalse(payload["tts"]["thinking_audio"]["stop_on_final_tts"])
        self.assertEqual(payload["tts"]["thinking_audio"]["max_per_request"], 1)
        self.assertGreaterEqual(payload["tts"]["thinking_audio"]["final_tts_wait_timeout_ms"], 250)
        self.assertEqual(payload["tts"]["thinking_audio"]["mode"], "smart")
        self.assertTrue(payload["tts"]["thinking_audio"]["skip_for_fast_semantic"])
        self.assertTrue(payload["tts"]["thinking_audio"]["skip_for_empty_transcript"])
        self.assertTrue(payload["tts"]["thinking_audio"]["skip_for_clarification"])
        self.assertTrue(payload["tts"]["thinking_audio"]["skip_for_confirmation"])
        self.assertTrue(payload["tts"]["thinking_audio"]["skip_for_greeting"])
        self.assertTrue(payload["tts"]["thinking_audio"]["one_per_turn"])
        self.assertTrue(payload["tts"]["thinking_audio"]["voice_audio_single_queue"])
        self.assertFalse(payload["tts"]["thinking_audio"]["voice_audio_allow_overlap"])
        self.assertGreaterEqual(payload["tts"]["thinking_audio"]["min_delay_ms"], 400)
        self.assertIn("min_record_seconds", payload["stt"])
        self.assertIn("end_silence_seconds", payload["stt"])
        self.assertFalse(payload["stt"]["empty_transcript_play_tts"])
        self.assertTrue(payload["stt"]["empty_transcript_reset_mic"])

    def test_tts_endpoint_rejects_empty_text(self):
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(main_module.text_to_speech(SimpleNamespace(text="   ")))

        self.assertEqual(ctx.exception.status_code, 400)

    def test_tts_endpoint_passes_configured_edge_options(self):
        with patch.object(main_module.edge_tts, "Communicate", FakeCommunicate):
            response = asyncio.run(main_module.text_to_speech(SimpleNamespace(text="Hello Jarvis", turn_id="turn-1", request_id="req-1")))
            chunks = asyncio.run(_collect_stream(response))

        self.assertEqual(chunks, [b"audio"])
        self.assertEqual(response.headers["X-Jarvis-Audio-Type"], "final")
        self.assertEqual(response.headers["X-Jarvis-Turn-Id"], "turn-1")
        self.assertEqual(response.headers["X-Jarvis-Request-Id"], "req-1")
        self.assertEqual(response.headers["X-Jarvis-TTS-Text-Length"], str(len("Hello Jarvis")))
        self.assertEqual(FakeCommunicate.last_call["rate"], main_module._tts_runtime_config()["rate"])
        self.assertEqual(FakeCommunicate.last_call["volume"], main_module._tts_runtime_config()["volume"])
        self.assertEqual(FakeCommunicate.last_call["pitch"], main_module._tts_runtime_config()["pitch"])

    def test_tts_natural_normalizer_keeps_dates_without_hard_pause(self):
        self.assertEqual(main_module._normalize_edge_tts_text("1st, May"), "1st May")
        self.assertEqual(main_module._normalize_edge_tts_text("May 1, 2026"), "May 1 2026")

    def test_tts_natural_normalizer_protects_versions_and_files(self):
        text = "Use Python 3.12.1 and open test_jarvis.txt."
        normalized = main_module._normalize_edge_tts_text(text)

        self.assertIn("Python 3.12.1", normalized)
        self.assertIn("test_jarvis.txt", normalized)

    def test_tts_natural_normalizer_protects_times(self):
        normalized = main_module._normalize_edge_tts_text("Your meeting is on 1st, May at 3:30 PM.")

        self.assertIn("1st May", normalized)
        self.assertIn("3:30 PM", normalized)

    def test_tts_natural_normalizer_protects_url_email_and_number_tokens(self):
        text = "Email me@example.com or visit https://example.com/a.b with 1,000 rows."
        normalized = main_module._normalize_edge_tts_text(text)

        self.assertIn("me@example.com", normalized)
        self.assertIn("https://example.com/a.b", normalized)
        self.assertIn("1,000", normalized)

    def test_tts_natural_normalizer_keeps_casual_comma(self):
        self.assertEqual(main_module._normalize_edge_tts_text("hello, how are you?"), "hello, how are you?")

    def test_tts_endpoint_sends_normalized_text_to_edge(self):
        with patch.object(main_module.edge_tts, "Communicate", FakeCommunicate):
            response = asyncio.run(main_module.text_to_speech(SimpleNamespace(text="May 1, 2026")))
            asyncio.run(_collect_stream(response))

        self.assertEqual(FakeCommunicate.last_call["text"], "May 1 2026")

    def test_thinking_tts_uses_configured_phrase_and_rate(self):
        main_module._thinking_tts_cache.clear()
        with (
            patch.object(main_module.edge_tts, "Communicate", FakeCommunicate),
            patch.object(
                main_module,
                "_thinking_audio_runtime_config",
                return_value={
                    "enabled": True,
                    "provider": "edge_tts",
                    "phrases": ["On it."],
                    "randomize": False,
                    "avoid_repeat": True,
                    "last_phrase_memory": True,
                    "max_seconds": 2.0,
                    "rate": "+20%",
                    "volume": "+0%",
                    "finish_before_final_tts": True,
                    "stop_on_final_tts": False,
                    "final_tts_wait_timeout_ms": 2500,
                    "max_per_request": 1,
                    "interruptible": True,
                    "cache_enabled": True,
                    "debug": False,
                },
            ),
        ):
            response = asyncio.run(main_module.thinking_text_to_speech(SimpleNamespace(turn_id="turn-2", request_id="req-2")))
            chunks = asyncio.run(_collect_stream(response))

        self.assertEqual(chunks, [b"audio"])
        self.assertEqual(response.headers["X-Jarvis-Audio-Type"], "thinking")
        self.assertEqual(response.headers["X-Jarvis-Turn-Id"], "turn-2")
        self.assertEqual(response.headers["X-Jarvis-Request-Id"], "req-2")
        self.assertEqual(response.headers["X-Jarvis-Thinking-Phrase"], "On it.")
        self.assertEqual(FakeCommunicate.last_call["text"], "On it.")
        self.assertEqual(FakeCommunicate.last_call["rate"], "+20%")

    def test_thinking_audio_default_phrase_pool_is_varied(self):
        config = main_module._thinking_audio_runtime_config()

        self.assertIn("On it.", config["phrases"])
        self.assertIn("Give me a second.", config["phrases"])
        self.assertNotIn("Working on it.", config["phrases"])
        self.assertTrue(config["randomize"])
        self.assertTrue(config["avoid_repeat"])

    def test_thinking_phrase_randomized_selection_avoids_immediate_repeat(self):
        main_module._last_thinking_phrase = "On it."

        with patch.object(main_module.random, "choice", side_effect=lambda items: items[0]):
            phrase = main_module._select_thinking_phrase(
                ["On it.", "Sure."],
                randomize=True,
                avoid_repeat=True,
                last_phrase_memory=True,
            )

        self.assertEqual(phrase, "Sure.")
        self.assertEqual(main_module._last_thinking_phrase, "Sure.")

    def test_thinking_phrase_deterministic_mode_uses_first_phrase(self):
        phrase = main_module._select_thinking_phrase(
            ["On it.", "Sure."],
            randomize=False,
            avoid_repeat=True,
            last_phrase_memory=True,
        )

        self.assertEqual(phrase, "On it.")

    def test_thinking_tts_generation_failure_does_not_raise(self):
        class FailingCommunicate:
            def __init__(self, *, text, voice, rate, volume, pitch):
                pass

            async def stream(self):
                if False:
                    yield {"type": "audio", "data": b""}
                raise RuntimeError("edge down")

        main_module._thinking_tts_cache.clear()
        with (
            patch.object(main_module.edge_tts, "Communicate", FailingCommunicate),
            patch.object(
                main_module,
                "_thinking_audio_runtime_config",
                return_value={
                    "enabled": True,
                    "provider": "edge_tts",
                    "phrases": ["On it."],
                    "randomize": False,
                    "avoid_repeat": True,
                    "last_phrase_memory": True,
                    "max_seconds": 2.0,
                    "rate": "+20%",
                    "volume": "+0%",
                    "finish_before_final_tts": True,
                    "stop_on_final_tts": False,
                    "final_tts_wait_timeout_ms": 2500,
                    "max_per_request": 1,
                    "interruptible": True,
                    "cache_enabled": False,
                    "debug": False,
                },
            ),
        ):
            response = asyncio.run(main_module.thinking_text_to_speech())
            chunks = asyncio.run(_collect_stream(response))

        self.assertEqual(chunks, [])

    def test_tts_endpoint_rejects_overlap_when_policy_is_reject_new(self):
        with patch.object(
            main_module,
            "_tts_runtime_config",
            return_value={
                "provider": "edge_tts",
                "voice": "en-GB-RyanNeural",
                "rate": "+15%",
                "volume": "+0%",
                "pitch": "+0Hz",
                "no_overlap": True,
                "interrupt_policy": "reject_new",
            },
        ):
            main_module._tts_request_generation = 1
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(main_module.text_to_speech(SimpleNamespace(text="Hello")))

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail, "speech_already_active")

    def test_tts_endpoint_stop_previous_policy_stops_older_stream(self):
        with (
            patch.object(main_module.edge_tts, "Communicate", FakeCommunicate),
            patch.object(
                main_module,
                "_tts_runtime_config",
                return_value={
                    "provider": "edge_tts",
                    "voice": "en-GB-RyanNeural",
                    "rate": "+15%",
                    "volume": "+0%",
                    "pitch": "+0Hz",
                    "no_overlap": True,
                    "interrupt_policy": "stop_previous",
                },
            ),
        ):
            response = asyncio.run(main_module.text_to_speech(SimpleNamespace(text="Hello")))
            main_module._tts_request_generation += 1
            chunks = asyncio.run(_collect_stream(response))

        self.assertEqual(chunks, [])


if __name__ == "__main__":
    unittest.main()
