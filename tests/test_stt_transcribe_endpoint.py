import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

import app.main as main
from app.adapters.providers.stt_provider import STTProviderReadiness


class FakeSTTTool:
    last_context = None
    calls = 0

    def execute(self, context, **kwargs):
        FakeSTTTool.last_context = context
        FakeSTTTool.calls += 1
        return {
            "success": True,
            "text": "create a file on my desktop named test",
            "message": "create a file on my desktop named test",
            "provider": "nemo_parakeet",
            "model": "nvidia/parakeet-tdt-0.6b-v2",
            "device": "cuda",
            "source": "temp.wav",
            "duration": 1.2,
            "segments": [],
            "timestamps": [],
            "raw_result_type": "list",
            "corrections_applied": [],
            "model_loaded": True,
            "model_load_ms": 0,
            "cache_hit": True,
            "transcription_ms": 4,
            "post_processing_ms": 1,
        }


class STTTranscribeEndpointTests(unittest.TestCase):
    def setUp(self):
        for name in ("stt_tool", "stt_provider", "stt_warmup_result"):
            if hasattr(main.app.state, name):
                delattr(main.app.state, name)
        FakeSTTTool.last_context = None
        FakeSTTTool.calls = 0
        self.client = TestClient(main.app)

    def test_stt_transcribe_uses_stt_tool_with_audio_bytes(self):
        tool = FakeSTTTool()
        with patch.object(main, "STTTool", return_value=tool):
            response = self.client.post(
                "/stt/transcribe",
                headers={
                    "Content-Type": "audio/wav",
                    "X-Audio-Filename": "voice.wav",
                },
                content=b"RIFFfakewav",
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["text"], "create a file on my desktop named test")
        self.assertEqual(FakeSTTTool.last_context.payload["action"], "transcribe_audio_bytes")
        self.assertEqual(FakeSTTTool.last_context.payload["args"]["filename"], "voice.wav")
        self.assertEqual(FakeSTTTool.last_context.payload["args"]["audio"], b"RIFFfakewav")
        self.assertTrue(payload["provider_reused"] is False)
        self.assertTrue(payload["model_loaded"])
        self.assertIn("total_ms", payload)
        self.assertEqual(payload["audio_format"], "wav")
        self.assertFalse(payload["ffmpeg_used"])

    def test_stt_transcribe_reuses_app_lifetime_tool_across_requests(self):
        tool = FakeSTTTool()
        with patch.object(main, "STTTool", return_value=tool) as builder:
            first = self.client.post("/stt/transcribe", headers={"Content-Type": "audio/wav", "X-Audio-Filename": "one.wav"}, content=b"RIFFone")
            second = self.client.post("/stt/transcribe", headers={"Content-Type": "audio/wav", "X-Audio-Filename": "two.wav"}, content=b"RIFFtwo")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        builder.assert_called_once()
        self.assertFalse(first.json()["provider_reused"])
        self.assertTrue(second.json()["provider_reused"])
        self.assertIs(main.app.state.stt_tool, tool)

    def test_build_stt_provider_called_once_across_two_requests(self):
        from app.adapters.providers.fake_stt_provider import FakeSTTProvider

        provider = FakeSTTProvider("cached transcript")
        with patch("app.tools.stt_tool.build_stt_provider", return_value=provider) as builder:
            first = self.client.post("/stt/transcribe", headers={"Content-Type": "audio/wav", "X-Audio-Filename": "one.wav"}, content=b"RIFFone")
            second = self.client.post("/stt/transcribe", headers={"Content-Type": "audio/wav", "X-Audio-Filename": "two.wav"}, content=b"RIFFtwo")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        builder.assert_called_once()
        self.assertEqual(len(provider.bytes_calls), 2)

    def test_stt_transcribe_does_not_execute_transcript(self):
        tool = FakeSTTTool()
        with patch.object(main, "STTTool", return_value=tool):
            response = self.client.post(
                "/stt/transcribe",
                headers={"Content-Type": "audio/wav", "X-Audio-Filename": "voice.wav"},
                content=b"RIFFfakewav",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(FakeSTTTool.calls, 1)

    def test_stt_transcribe_blank_transcript_returns_no_speech(self):
        class BlankTool(FakeSTTTool):
            def execute(self, context, **kwargs):
                payload = super().execute(context, **kwargs)
                payload["text"] = "   "
                payload["message"] = ""
                return payload

        with patch.object(main, "STTTool", return_value=BlankTool()):
            response = self.client.post(
                "/stt/transcribe",
                headers={"Content-Type": "audio/wav", "X-Audio-Filename": "voice.wav"},
                content=b"RIFFfakewav",
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "no_speech")
        self.assertFalse(payload["should_chat"])

    def test_stt_transcribe_empty_audio_returns_no_speech(self):
        response = self.client.post(
            "/stt/transcribe",
            headers={"Content-Type": "audio/wav", "X-Audio-Filename": "voice.wav"},
            content=b"",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["success"])
        self.assertEqual(payload["status"], "no_speech")
        self.assertEqual(payload["error"], "no_speech_detected")
        self.assertFalse(payload["should_chat"])
        self.assertFalse(payload["should_play_thinking_tts"])

    def test_stt_transcribe_unsupported_format_fails_cleanly(self):
        with patch.object(main, "_ffmpeg_available", return_value=False):
            response = self.client.post(
                "/stt/transcribe",
                headers={"Content-Type": "audio/webm", "X-Audio-Filename": "voice.webm"},
                content=b"webm-data",
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "unsupported_audio_format")

    def test_stt_transcribe_provider_failure_bubbles_cleanly(self):
        class FailingTool:
            def execute(self, context, **kwargs):
                return {"success": False, "error": "unsupported_audio_format", "message": "bad format"}

        with patch.object(main, "STTTool", return_value=FailingTool()):
            response = self.client.post(
                "/stt/transcribe",
                headers={"Content-Type": "audio/wav", "X-Audio-Filename": "voice.wav"},
                content=b"RIFFfakewav",
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "unsupported_audio_format")

    def test_stt_transcribe_unavailable_provider_returns_readiness_metadata(self):
        class FailingTool:
            def execute(self, context, **kwargs):
                return {
                    "success": False,
                    "error": "stt_provider_unavailable",
                    "message": "disabled",
                    "provider_readiness": {
                        "provider_name": "none",
                        "available": False,
                        "reason": "disabled",
                    },
                }

        with patch.object(main, "STTTool", return_value=FailingTool()):
            response = self.client.post(
                "/stt/transcribe",
                headers={"Content-Type": "audio/wav", "X-Audio-Filename": "voice.wav"},
                content=b"RIFFfakewav",
            )

        self.assertEqual(response.status_code, 400)
        detail = response.json()["detail"]
        self.assertEqual(detail["error"], "stt_provider_unavailable")
        self.assertEqual(detail["provider_name"], "none")
        self.assertFalse(detail["available"])
        self.assertEqual(detail["reason"], "disabled")
        self.assertEqual(detail["capture_mode"], "backend_parakeet")

    def test_health_exposes_safe_stt_runtime_diagnostics(self):
        readiness = STTProviderReadiness(
            provider_name="nemo_parakeet",
            configured=True,
            available=True,
            reason="cuda_available",
            backend="nemo",
            model="nvidia/parakeet-tdt-0.6b-v2",
            device="cuda",
            compute_type="float16",
            live_call_required=False,
        )
        with (
            patch.object(main, "stt_provider_readiness", return_value=readiness),
            patch.object(main, "_ffmpeg_available", return_value=True),
        ):
            response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        stt = response.json()["stt"]
        self.assertEqual(stt["capture_mode"], "backend_parakeet")
        self.assertEqual(stt["provider"], "nemo_parakeet")
        self.assertEqual(stt["provider_name"], "nemo_parakeet")
        self.assertTrue(stt["configured"])
        self.assertTrue(stt["available"])
        self.assertEqual(stt["reason"], "cuda_available")
        self.assertEqual(stt["model"], "nvidia/parakeet-tdt-0.6b-v2")
        self.assertEqual(stt["device"], "cuda")
        self.assertTrue(stt["require_wav"])
        self.assertTrue(stt["ffmpeg_available"])
        self.assertFalse(stt["live_call_required"])
        self.assertFalse(stt["provider_cached"])
        self.assertFalse(stt["model_loaded"])
        self.assertIn("preload_enabled", stt)
        self.assertIn("warmup_on_startup", stt)
        self.assertIn("warmup_error", stt)
        self.assertIn("cache_enabled", stt)
        self.assertIn("domain_correction_enabled", stt)
        self.assertEqual(stt["empty_transcript_behavior"], "short_prompt")
        self.assertEqual(stt["empty_transcript_prompt"], "I didn't catch that.")
        self.assertFalse(stt["empty_transcript_play_tts"])
        self.assertTrue(stt["empty_transcript_reset_mic"])
        semantic = response.json()["semantic"]
        self.assertIn("smart_enabled", semantic)
        self.assertIn("planner_enabled", semantic)
        self.assertIn("safe_execution_enabled", semantic)
        self.assertIn("context_enabled", semantic)
        self.assertIn("duplicate_protection_enabled", semantic)
        self.assertIn("dry_run_enabled", semantic)

    def test_health_does_not_load_parakeet_model(self):
        with (
            patch("importlib.util.find_spec", return_value=object()),
            patch("app.adapters.providers.stt_provider.torch_cuda_available", return_value=True),
            patch("app.adapters.providers.nemo_parakeet_provider.importlib.import_module") as importer,
        ):
            response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        importer.assert_not_called()

    def test_stt_warmup_uses_cached_tool_and_does_not_transcribe_audio(self):
        class WarmupTool:
            def __init__(self):
                self.provider = type("Provider", (), {"provider_name": "nemo_parakeet", "model_loaded": True})()
                self.calls = []

            def execute(self, context, **kwargs):
                self.calls.append(context.payload["action"])
                return {
                    "success": True,
                    "action": "warmup",
                    "provider": "nemo_parakeet",
                    "model": "nvidia/parakeet-tdt-0.6b-v2",
                    "device": "cuda",
                    "model_loaded": True,
                    "model_load_ms": 11,
                    "cache_hit": False,
                    "total_ms": 12,
                }

        tool = WarmupTool()
        with patch.object(main, "STTTool", return_value=tool):
            response = self.client.post("/stt/warmup")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertTrue(payload["model_loaded"])
        self.assertEqual(tool.calls, ["warmup"])

    def test_second_stt_warmup_reports_cache_hit(self):
        class WarmupTool:
            def __init__(self):
                self.provider = type("Provider", (), {"provider_name": "nemo_parakeet", "model_loaded": True})()
                self.calls = 0

            def execute(self, context, **kwargs):
                self.calls += 1
                return {
                    "success": True,
                    "action": "warmup",
                    "provider": "nemo_parakeet",
                    "model": "nvidia/parakeet-tdt-0.6b-v2",
                    "device": "cuda",
                    "model_loaded": True,
                    "model_load_ms": 0 if self.calls > 1 else 10,
                    "cache_hit": self.calls > 1,
                    "total_ms": 1,
                }

        tool = WarmupTool()
        with patch.object(main, "STTTool", return_value=tool):
            first = self.client.post("/stt/warmup")
            second = self.client.post("/stt/warmup")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertFalse(first.json()["cache_hit"])
        self.assertTrue(second.json()["cache_hit"])
        self.assertEqual(tool.calls, 2)

    def test_preload_disabled_builds_provider_without_warmup(self):
        tool = FakeSTTTool()
        tool.execute = Mock(return_value={"success": True, "action": "warmup"})
        with (
            patch.dict("os.environ", {"PARAKEET_PRELOAD_ON_STARTUP": "false", "STT_WARMUP_ON_STARTUP": "false"}, clear=False),
            patch.object(main, "STTTool", return_value=tool),
        ):
            built, _ = main._get_stt_tool(main.app, force_rebuild=True)

        self.assertIs(built, tool)
        tool.execute.assert_not_called()

    def test_preload_enabled_warmup_loads_once_via_cached_tool(self):
        class WarmupTool:
            def __init__(self):
                self.provider = type("Provider", (), {"provider_name": "nemo_parakeet", "model_loaded": True})()
                self.calls = 0

            def execute(self, context, **kwargs):
                self.calls += 1
                return {
                    "success": True,
                    "action": "warmup",
                    "provider": "nemo_parakeet",
                    "model": "nvidia/parakeet-tdt-0.6b-v2",
                    "device": "cuda",
                    "model_loaded": True,
                    "model_load_ms": 5 if self.calls == 1 else 0,
                    "cache_hit": self.calls > 1,
                }

        tool = WarmupTool()
        with (
            patch.dict("os.environ", {"PARAKEET_PRELOAD_ON_STARTUP": "true"}, clear=False),
            patch.object(main, "STTTool", return_value=tool) as builder,
        ):
            first = main._warmup_stt_tool(main.app)
            second = main._warmup_stt_tool(main.app)

        builder.assert_called_once()
        self.assertFalse(first["cache_hit"])
        self.assertTrue(second["cache_hit"])

    def test_startup_warmup_defaults_to_enabled_and_uses_cached_tool(self):
        class WarmupTool:
            def __init__(self):
                self.provider = type("Provider", (), {"provider_name": "nemo_parakeet", "model_loaded": True})()
                self.calls = 0

            def execute(self, context, **kwargs):
                self.calls += 1
                return {
                    "success": True,
                    "action": "warmup",
                    "provider": "nemo_parakeet",
                    "model_loaded": True,
                    "model_load_ms": 7,
                    "cache_hit": False,
                }

        tool = WarmupTool()
        with patch.object(main, "STTTool", return_value=tool) as builder:
            result = main._run_startup_stt_warmup(main.app)

        builder.assert_called_once()
        self.assertTrue(result["success"])
        self.assertTrue(result["preload_enabled"])
        self.assertTrue(result["warmup_on_startup"])
        self.assertTrue(result["model_loaded"])
        self.assertEqual(tool.calls, 1)
        self.assertIs(main.app.state.stt_warmup_result, result)

    def test_startup_warmup_failure_does_not_crash_when_fail_fast_disabled(self):
        class FailingWarmupTool:
            def __init__(self):
                self.provider = type("Provider", (), {"provider_name": "nemo_parakeet", "model_loaded": False})()

            def execute(self, context, **kwargs):
                return {
                    "success": False,
                    "action": "warmup",
                    "error": "stt_model_load_failed",
                    "message": "Could not load Parakeet model.",
                    "model_loaded": False,
                }

        with (
            patch.dict("os.environ", {"STT_FAIL_FAST_ON_WARMUP_ERROR": "false"}, clear=False),
            patch.object(main, "STTTool", return_value=FailingWarmupTool()),
        ):
            result = main._run_startup_stt_warmup(main.app)

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "stt_model_load_failed")
        self.assertEqual(main.app.state.stt_warmup_result["error"], "stt_model_load_failed")

    def test_startup_warmup_failure_raises_when_fail_fast_enabled(self):
        class FailingWarmupTool:
            def __init__(self):
                self.provider = type("Provider", (), {"provider_name": "nemo_parakeet", "model_loaded": False})()

            def execute(self, context, **kwargs):
                return {
                    "success": False,
                    "action": "warmup",
                    "error": "stt_model_load_failed",
                    "message": "Could not load Parakeet model.",
                    "model_loaded": False,
                }

        with (
            patch.dict("os.environ", {"STT_FAIL_FAST_ON_WARMUP_ERROR": "true"}, clear=False),
            patch.object(main, "STTTool", return_value=FailingWarmupTool()),
            self.assertRaises(RuntimeError),
        ):
            main._run_startup_stt_warmup(main.app)

    def test_health_reports_startup_warmup_failure_reason(self):
        main.app.state.stt_warmup_result = {
            "success": False,
            "error": "stt_model_load_failed",
            "message": "Could not load Parakeet model.",
        }
        readiness = STTProviderReadiness(
            provider_name="nemo_parakeet",
            configured=True,
            available=True,
            reason="cuda_available",
            backend="nemo",
            model="nvidia/parakeet-tdt-0.6b-v2",
            device="cuda",
            compute_type="float16",
            live_call_required=False,
        )
        with (
            patch.object(main, "stt_provider_readiness", return_value=readiness),
            patch.object(main, "_ffmpeg_available", return_value=True),
        ):
            response = self.client.get("/health")

        stt = response.json()["stt"]
        self.assertFalse(stt["warmup_success"])
        self.assertEqual(stt["warmup_error"], "stt_model_load_failed")
        self.assertEqual(stt["warmup_reason"], "Could not load Parakeet model.")

    def test_first_transcribe_after_startup_warmup_reports_cache_hit(self):
        tool = FakeSTTTool()
        main.app.state.stt_tool = tool
        main.app.state.stt_provider = type("Provider", (), {"provider_name": "nemo_parakeet", "model_loaded": True})()

        response = self.client.post(
            "/stt/transcribe",
            headers={"Content-Type": "audio/wav", "X-Audio-Filename": "voice.wav"},
            content=b"RIFFfakewav",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["provider_reused"])
        self.assertTrue(payload["cache_hit"])
        self.assertEqual(payload["model_load_ms"], 0)
        self.assertTrue(payload["model_loaded"])


if __name__ == "__main__":
    unittest.main()
