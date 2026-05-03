import os
import unittest
from unittest.mock import patch

from app.adapters.providers.fake_stt_provider import FakeSTTProvider
from app.adapters.providers.nemo_parakeet_provider import NemoParakeetProvider
from app.adapters.providers.stt_provider import DisabledSTTProvider, build_stt_provider, stt_provider_readiness
from app.core.config_loader import ConfigLoader


class STTProviderConfigTests(unittest.TestCase):
    def test_config_loader_has_safe_stt_defaults(self):
        section = ConfigLoader().get_section("stt")

        self.assertEqual(section["provider"], "nemo_parakeet")
        self.assertEqual(section["preferred_local_provider"], "nemo_parakeet")
        self.assertNotIn("legacy_whisper_enabled", section)
        self.assertEqual(section["parakeet_model"], "nvidia/parakeet-tdt-0.6b-v2")
        self.assertEqual(section["parakeet_device"], "cuda")
        self.assertEqual(section["parakeet_compute_type"], "float16")
        self.assertEqual(section["parakeet_model_dir"], "")
        self.assertEqual(section["parakeet_language"], "")
        self.assertEqual(section["parakeet_max_audio_mb"], "")
        self.assertTrue(section["parakeet_require_wav"])
        self.assertTrue(section["parakeet_post_processing_enabled"])
        self.assertTrue(section["parakeet_domain_correction_enabled"])
        self.assertEqual(section["parakeet_domain_corrections"], "Jarris=Jarvis|Javi=Jarvis|Jaris=Jarvis|Javas=Jarvis|Jervis=Jarvis|Javier=Jarvis|Jawis=Jarvis|Jais=Jarvis|Jarwis=Jarvis|Jarvish=Jarvis")
        self.assertFalse(section["parakeet_domain_correction_case_sensitive"])
        self.assertTrue(section["parakeet_domain_correction_word_boundary"])
        self.assertEqual(section["empty_transcript_behavior"], "short_prompt")
        self.assertEqual(section["empty_transcript_prompt"], "I didn't catch that.")
        self.assertTrue(section["provider_cache_enabled"])
        self.assertTrue(section["parakeet_preload_on_startup"])
        self.assertTrue(section["warmup_on_startup"])
        self.assertFalse(section["fail_fast_on_warmup_error"])

    def test_config_loader_exposes_phase2_automation_flags(self):
        section = ConfigLoader().get_section("automation")

        self.assertTrue(section["smart_automation_enabled"])
        self.assertFalse(section["semantic_planner_enabled"])
        self.assertFalse(section["semantic_safe_execution_enabled"])
        self.assertTrue(section["automation_context_enabled"])
        self.assertEqual(section["automation_context_ttl_seconds"], 900)
        self.assertTrue(section["automation_context_redact_sensitive"])
        self.assertTrue(section["automation_dry_run_enabled"])
        self.assertTrue(section["automation_duplicate_protection_enabled"])
        self.assertEqual(section["automation_duplicate_window_seconds"], 5)
        self.assertTrue(section["app_interaction"]["enabled"])
        self.assertTrue(section["app_interaction"]["semantic_actions_enabled"])

    def test_config_loader_exposes_launcher_only_face_gate_defaults(self):
        section = ConfigLoader().get_section("security")

        self.assertTrue(section["face_gate_enabled"])
        self.assertEqual(section["face_gate_scope"], "launcher_only")
        self.assertFalse(section["face_in_app_recognition_enabled"])
        self.assertFalse(section["face_step_up_for_tools_enabled"])
        self.assertFalse(section["face_status_in_app_enabled"])
        self.assertFalse(section["face_verify_in_app_enabled"])

    def test_backend_capture_defaults_to_nemo_parakeet_when_provider_unset(self):
        readiness = stt_provider_readiness(
            config={
                "provider": "auto",
                "preferred_local_provider": "nemo_parakeet",
                "capture_mode": "backend_parakeet",
                "parakeet_device": "cpu",
            },
            env={},
        )

        self.assertEqual(readiness.provider_name, "nemo_parakeet")
        self.assertTrue(readiness.configured)

    def test_browser_legacy_auto_provider_stays_disabled(self):
        readiness = stt_provider_readiness(
            config={"provider": "auto", "capture_mode": "browser_legacy"},
            env={},
        )

        self.assertEqual(readiness.provider_name, "none")
        self.assertFalse(readiness.configured)
        self.assertEqual(readiness.reason, "disabled")

    def test_explicit_none_provider_overrides_backend_capture_default(self):
        readiness = stt_provider_readiness(
            config={"provider": "auto", "capture_mode": "backend_parakeet"},
            env={"STT_PROVIDER": "none", "STT_CAPTURE_MODE": "backend_parakeet"},
        )

        self.assertEqual(readiness.provider_name, "none")
        self.assertFalse(readiness.configured)
        self.assertEqual(readiness.reason, "disabled")

    def test_disabled_provider_readiness(self):
        readiness = stt_provider_readiness(config={"provider": "none"}, env={})

        self.assertEqual(readiness.provider_name, "none")
        self.assertFalse(readiness.configured)
        self.assertFalse(readiness.available)
        self.assertEqual(readiness.reason, "disabled")
        self.assertFalse(readiness.live_call_required)

    def test_fake_provider_readiness(self):
        readiness = stt_provider_readiness(config={"provider": "none"}, env={"STT_PROVIDER": "fake"})

        self.assertEqual(readiness.provider_name, "fake")
        self.assertTrue(readiness.configured)
        self.assertTrue(readiness.available)
        self.assertEqual(readiness.reason, "test_or_local_fake")

    def test_removed_local_whisper_is_unsupported(self):
        readiness = stt_provider_readiness(config={"provider": "local_whisper"}, env={})

        self.assertEqual(readiness.provider_name, "local_whisper")
        self.assertFalse(readiness.configured)
        self.assertFalse(readiness.available)
        self.assertEqual(readiness.reason, "unsupported_stt_provider")

    def test_build_stt_provider_uses_disabled_default(self):
        with patch.dict(os.environ, {"STT_PROVIDER": "none"}, clear=False):
            provider = build_stt_provider()

        self.assertIsInstance(provider, DisabledSTTProvider)

    def test_build_stt_provider_uses_nemo_parakeet_for_backend_capture_default(self):
        with patch.dict(os.environ, {"STT_CAPTURE_MODE": "backend_parakeet"}, clear=True):
            provider = build_stt_provider(
                config={
                    "provider": "auto",
                    "preferred_local_provider": "nemo_parakeet",
                    "capture_mode": "backend_parakeet",
                }
            )

        self.assertIsInstance(provider, NemoParakeetProvider)

    def test_build_stt_provider_uses_fake(self):
        with patch.dict(os.environ, {"STT_PROVIDER": "fake"}, clear=False):
            provider = build_stt_provider()

        self.assertIsInstance(provider, FakeSTTProvider)

    def test_build_stt_provider_does_not_use_removed_local_whisper(self):
        provider = build_stt_provider(config={"provider": "local_whisper"})

        self.assertIsInstance(provider, DisabledSTTProvider)

    def test_build_stt_provider_uses_nemo_parakeet(self):
        provider = build_stt_provider(config={"provider": "nemo_parakeet"})

        self.assertIsInstance(provider, NemoParakeetProvider)

    def test_build_stt_provider_uses_nemo_parakeet_from_env(self):
        with patch.dict(os.environ, {"STT_PROVIDER": "nemo_parakeet"}, clear=True):
            provider = build_stt_provider(config={"provider": "none"})

        self.assertIsInstance(provider, NemoParakeetProvider)

    def test_nemo_parakeet_readiness_dependency_missing(self):
        with patch("importlib.util.find_spec", return_value=None):
            readiness = stt_provider_readiness(config={"provider": "nemo_parakeet"}, env={})

        self.assertEqual(readiness.provider_name, "nemo_parakeet")
        self.assertTrue(readiness.configured)
        self.assertFalse(readiness.available)
        self.assertEqual(readiness.reason, "stt_dependency_missing")
        self.assertEqual(readiness.model, "nvidia/parakeet-tdt-0.6b-v2")

    def test_nemo_parakeet_readiness_cuda_unavailable(self):
        with (
            patch("importlib.util.find_spec", return_value=object()),
            patch("app.adapters.providers.stt_provider.torch_cuda_available", return_value=False),
        ):
            readiness = stt_provider_readiness(config={"provider": "nemo_parakeet", "parakeet_device": "cuda"}, env={})

        self.assertFalse(readiness.available)
        self.assertEqual(readiness.reason, "cuda_unavailable")

    def test_nemo_parakeet_readiness_available_without_model_load(self):
        with (
            patch("importlib.util.find_spec", return_value=object()),
            patch("app.adapters.providers.stt_provider.torch_cuda_available", return_value=True),
            patch("app.adapters.providers.nemo_parakeet_provider.importlib.import_module") as importer,
        ):
            readiness = stt_provider_readiness(config={"provider": "nemo_parakeet", "parakeet_device": "cuda"}, env={})

        self.assertTrue(readiness.available)
        self.assertEqual(readiness.reason, "cuda_available")
        importer.assert_not_called()


if __name__ == "__main__":
    unittest.main()
