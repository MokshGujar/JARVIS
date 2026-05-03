import shutil
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

from app.adapters.providers.nemo_parakeet_provider import NemoParakeetProvider


class NemoParakeetProviderTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parent / "_tmp" / "nemo_parakeet"
        if self.root.exists():
            shutil.rmtree(self.root)
        self.root.mkdir(parents=True)
        self.audio = self.root / "audio.wav"
        self.audio.write_bytes(b"audio")
        self.m4a = self.root / "audio.m4a"
        self.m4a.write_bytes(b"audio")

    def tearDown(self):
        if self.root.exists():
            shutil.rmtree(self.root)

    def test_missing_nemo_dependency_returns_dependency_missing(self):
        with patch.object(NemoParakeetProvider, "_nemo_available", return_value=False):
            provider = NemoParakeetProvider({"provider": "nemo_parakeet"}, cuda_checker=lambda: True)
            result = provider.transcribe_file(str(self.audio))

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "stt_dependency_missing")

    def test_readiness_does_not_load_model(self):
        factory = Mock()
        provider = NemoParakeetProvider({"provider": "nemo_parakeet"}, model_factory=factory, cuda_checker=lambda: True)
        with (
            patch("importlib.util.find_spec", return_value=object()),
            patch("app.adapters.providers.stt_provider.torch_cuda_available", return_value=True),
        ):
            readiness = provider.readiness()

        self.assertEqual(readiness["provider_name"], "nemo_parakeet")
        self.assertTrue(readiness["available"])
        self.assertEqual(readiness["reason"], "cuda_available")
        factory.assert_not_called()

    def test_lazy_model_loading_is_mocked_and_cached(self):
        model = Mock()
        model.transcribe.return_value = ["hello from parakeet"]
        model.to.return_value = model
        model.half.return_value = model
        factory = Mock(return_value=model)
        provider = NemoParakeetProvider({"provider": "nemo_parakeet", "parakeet_device": "cuda"}, model_factory=factory, cuda_checker=lambda: True)

        factory.assert_not_called()
        first = provider.transcribe_file(str(self.audio))
        second = provider.transcribe_file(str(self.audio))

        self.assertTrue(first["success"])
        self.assertTrue(second["success"])
        self.assertEqual(first["text"], "hello from parakeet")
        factory.assert_called_once_with(model_name="nvidia/parakeet-tdt-0.6b-v2", map_location="cuda")
        self.assertEqual(model.transcribe.call_count, 2)
        self.assertFalse(first["cache_hit"])
        self.assertTrue(second["cache_hit"])
        self.assertTrue(second["model_loaded"])

    def test_transcribe_file_returns_structured_transcript(self):
        model = Mock()
        model.transcribe.return_value = [{"text": "  hello   world  ", "duration": 2.0, "segments": [{"start": 0, "end": 1, "text": "hello"}]}]
        provider = NemoParakeetProvider({"provider": "nemo_parakeet", "parakeet_device": "cpu", "parakeet_language": "en"}, model_factory=Mock(return_value=model))

        result = provider.transcribe_file(str(self.audio))

        self.assertTrue(result["success"])
        self.assertEqual(result["text"], "hello world")
        self.assertEqual(result["provider"], "nemo_parakeet")
        self.assertEqual(result["backend"], "nemo")
        self.assertEqual(result["model"], "nvidia/parakeet-tdt-0.6b-v2")
        self.assertEqual(result["device"], "cpu")
        self.assertEqual(result["language"], "en")
        self.assertEqual(result["duration"], 2.0)
        self.assertEqual(result["segments"], [{"start": 0.0, "end": 1.0, "text": "hello"}])
        self.assertEqual(result["timestamps"], result["segments"])
        self.assertEqual(result["raw_result_type"], "list[dict]")

    def test_transcribe_file_extracts_text_from_hypothesis_text(self):
        class Hypothesis:
            text = "hello from hypothesis"

        model = Mock()
        model.transcribe.return_value = [Hypothesis()]
        provider = NemoParakeetProvider({"provider": "nemo_parakeet", "parakeet_device": "cpu"}, model_factory=Mock(return_value=model))

        result = provider.transcribe_file(str(self.audio))

        self.assertTrue(result["success"])
        self.assertEqual(result["text"], "hello from hypothesis")
        self.assertNotIn("Hypothesis", result["text"])
        self.assertEqual(result["raw_result_type"], "list[Hypothesis]")

    def test_transcribe_file_extracts_text_from_list_string(self):
        model = Mock()
        model.transcribe.return_value = ["hello from string"]
        provider = NemoParakeetProvider({"provider": "nemo_parakeet", "parakeet_device": "cpu"}, model_factory=Mock(return_value=model))

        result = provider.transcribe_file(str(self.audio))

        self.assertTrue(result["success"])
        self.assertEqual(result["text"], "hello from string")
        self.assertEqual(result["raw_result_type"], "list[str]")

    def test_unsupported_m4a_returns_unsupported_audio_format_when_wav_required(self):
        factory = Mock()
        provider = NemoParakeetProvider({"provider": "nemo_parakeet", "parakeet_device": "cpu", "parakeet_require_wav": True}, model_factory=factory)

        result = provider.transcribe_file(str(self.m4a))

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "unsupported_audio_format")
        factory.assert_not_called()

    def test_transcribe_bytes_writes_temp_file_and_cleans_it_up(self):
        seen_paths = []

        class Model:
            def transcribe(self, paths):
                seen_paths.append(Path(paths[0]))
                return ["bytes transcript"]

        provider = NemoParakeetProvider({"provider": "nemo_parakeet", "parakeet_device": "cpu"}, model_factory=Mock(return_value=Model()))

        result = provider.transcribe_bytes(b"abc", filename="clip.wav")

        self.assertTrue(result["success"])
        self.assertEqual(result["text"], "bytes transcript")
        self.assertTrue(seen_paths)
        self.assertFalse(seen_paths[0].exists())

    def test_missing_file_returns_audio_file_not_found(self):
        provider = NemoParakeetProvider({"provider": "nemo_parakeet"}, model_factory=Mock(), cuda_checker=lambda: True)

        result = provider.transcribe_file(str(self.root / "missing.wav"))

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "audio_file_not_found")

    def test_file_too_large_returns_audio_file_too_large(self):
        provider = NemoParakeetProvider({"provider": "nemo_parakeet", "parakeet_max_audio_mb": 0}, model_factory=Mock(), cuda_checker=lambda: True)

        result = provider.transcribe_file(str(self.audio))

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "audio_file_too_large")

    def test_model_load_failure_returns_model_load_failed(self):
        provider = NemoParakeetProvider({"provider": "nemo_parakeet"}, model_factory=Mock(side_effect=RuntimeError("load failed")), cuda_checker=lambda: True)

        result = provider.transcribe_file(str(self.audio))

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "stt_model_load_failed")

    def test_concurrent_first_transcriptions_load_model_once(self):
        model = Mock()
        model.transcribe.return_value = ["hello concurrent"]

        def factory(**kwargs):
            time.sleep(0.05)
            return model

        factory_mock = Mock(side_effect=factory)
        provider = NemoParakeetProvider({"provider": "nemo_parakeet", "parakeet_device": "cpu"}, model_factory=factory_mock)

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: provider.transcribe_file(str(self.audio)), range(2)))

        self.assertTrue(all(result["success"] for result in results))
        factory_mock.assert_called_once()
        self.assertEqual(model.transcribe.call_count, 2)

    def test_model_load_failure_does_not_block_later_retry(self):
        model = Mock()
        model.transcribe.return_value = ["retry ok"]
        factory = Mock(side_effect=[RuntimeError("load failed"), model])
        provider = NemoParakeetProvider({"provider": "nemo_parakeet", "parakeet_device": "cpu"}, model_factory=factory)

        first = provider.transcribe_file(str(self.audio))
        second = provider.transcribe_file(str(self.audio))

        self.assertFalse(first["success"])
        self.assertEqual(first["error"], "stt_model_load_failed")
        self.assertTrue(second["success"])
        self.assertEqual(factory.call_count, 2)

    def test_transcription_failure_returns_transcription_failed(self):
        model = Mock()
        model.transcribe.side_effect = RuntimeError("bad audio")
        provider = NemoParakeetProvider({"provider": "nemo_parakeet"}, model_factory=Mock(return_value=model), cuda_checker=lambda: True)

        result = provider.transcribe_file(str(self.audio))

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "transcription_failed")

    def test_empty_transcript_returns_empty_transcript(self):
        model = Mock()
        model.transcribe.return_value = [""]
        provider = NemoParakeetProvider({"provider": "nemo_parakeet", "parakeet_device": "cpu"}, model_factory=Mock(return_value=model))

        result = provider.transcribe_file(str(self.audio))

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "empty_transcript")

    def test_post_processing_normalizes_whitespace_when_enabled(self):
        model = Mock()
        model.transcribe.return_value = ["  hello\t\tJarvis\n\nnow  "]
        provider = NemoParakeetProvider(
            {"provider": "nemo_parakeet", "parakeet_device": "cpu", "parakeet_post_processing_enabled": True},
            model_factory=Mock(return_value=model),
        )

        result = provider.transcribe_file(str(self.audio))

        self.assertTrue(result["success"])
        self.assertEqual(result["text"], "hello Jarvis now")
        self.assertTrue(result["post_processing_used"])

    def test_domain_correction_applies_only_when_enabled_and_configured(self):
        model = Mock()
        model.transcribe.return_value = ["Hello Jaris and Javas"]
        config = {
            "provider": "nemo_parakeet",
            "parakeet_device": "cpu",
            "parakeet_domain_correction_enabled": True,
            "parakeet_domain_corrections": {"Jaris": "Jarvis"},
        }
        provider = NemoParakeetProvider(config, model_factory=Mock(return_value=model))

        result = provider.transcribe_file(str(self.audio))

        self.assertTrue(result["success"])
        self.assertEqual(result["text"], "Hello Jarvis and Javas")
        self.assertEqual(result["corrections_applied"], [{"from": "Jaris", "to": "Jarvis"}])

    def test_default_assistant_name_corrections_are_conservative(self):
        cases = ("Jarris", "Javi", "Javis", "Jaris", "Javas", "Jervis", "Javier", "Jawis", "Jais", "Jarwis", "Jarvish")
        for wrong in cases:
            with self.subTest(wrong=wrong):
                model = Mock()
                model.transcribe.return_value = [f"Hello, {wrong}."]
                provider = NemoParakeetProvider({"provider": "nemo_parakeet", "parakeet_device": "cpu"}, model_factory=Mock(return_value=model))

                result = provider.transcribe_file(str(self.audio))

                self.assertTrue(result["success"])
                self.assertEqual(result["text"], "Hello, Jarvis.")
                self.assertEqual(result["original_text"], f"Hello, {wrong}.")
                self.assertEqual(result["corrected_text"], "Hello, Jarvis.")
                self.assertTrue(result["domain_correction_used"])

    def test_domain_correction_can_be_disabled(self):
        model = Mock()
        model.transcribe.return_value = ["Hello Javier"]
        provider = NemoParakeetProvider(
            {
                "provider": "nemo_parakeet",
                "parakeet_device": "cpu",
                "parakeet_domain_correction_enabled": False,
                "parakeet_domain_corrections": {"Javier": "Jarvis"},
            },
            model_factory=Mock(return_value=model),
        )

        result = provider.transcribe_file(str(self.audio))

        self.assertTrue(result["success"])
        self.assertEqual(result["text"], "Hello Javier")
        self.assertEqual(result["corrections_applied"], [])

    def test_domain_correction_leaves_unrelated_words_unchanged(self):
        model = Mock()
        model.transcribe.return_value = ["Javison wrote a script"]
        provider = NemoParakeetProvider({"provider": "nemo_parakeet", "parakeet_device": "cpu"}, model_factory=Mock(return_value=model))

        result = provider.transcribe_file(str(self.audio))

        self.assertTrue(result["success"])
        self.assertEqual(result["text"], "Javison wrote a script")
        self.assertEqual(result["corrections_applied"], [])

    def test_cuda_unavailable_returns_clean_error(self):
        provider = NemoParakeetProvider({"provider": "nemo_parakeet", "parakeet_device": "cuda"}, model_factory=Mock(), cuda_checker=lambda: False)

        result = provider.transcribe_file(str(self.audio))

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "cuda_unavailable")


if __name__ == "__main__":
    unittest.main()
