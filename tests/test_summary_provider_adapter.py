import os
import unittest
from unittest.mock import Mock, patch

from app.adapters.providers.fake_summary_provider import FakeSummaryProvider
from app.adapters.providers.summary_provider import (
    DisabledSummaryProvider,
    GroqSummaryProvider,
    SummaryProviderUnavailable,
    build_summary_provider,
    summary_provider_readiness,
)


class SummaryProviderAdapterTests(unittest.TestCase):
    def test_fake_summary_provider_summarizes_and_records_mode(self):
        provider = FakeSummaryProvider("fake output")

        result = provider.summarize("input text", mode="key_points")

        self.assertEqual(result, "fake output")
        self.assertEqual(provider.calls, [{"text": "input text", "mode": "key_points"}])

    def test_disabled_summary_provider_raises_unavailable(self):
        provider = DisabledSummaryProvider()

        with self.assertRaises(SummaryProviderUnavailable):
            provider.summarize("input")

    def test_groq_summary_provider_wraps_existing_groq_service(self):
        groq = Mock()
        groq.get_response.return_value = "groq summary"
        provider = GroqSummaryProvider(groq)

        result = provider.summarize("important text", mode="notes")

        self.assertEqual(result, "groq summary")
        groq.get_response.assert_called_once()
        prompt = groq.get_response.call_args.args[0]
        self.assertIn("important text", prompt)
        self.assertIn("notes", prompt.lower())
        self.assertEqual(groq.get_response.call_args.kwargs["chat_history"], [])

    def test_config_default_uses_disabled_provider_without_api_key(self):
        with patch.dict(os.environ, {"SUMMARY_PROVIDER": ""}, clear=False):
            provider = build_summary_provider(config={"provider": "none"})

        self.assertIsInstance(provider, DisabledSummaryProvider)

    def test_env_fake_provider_selection_does_not_use_network(self):
        with patch.dict(os.environ, {"SUMMARY_PROVIDER": "fake"}, clear=False):
            provider = build_summary_provider()

        self.assertIsInstance(provider, FakeSummaryProvider)
        self.assertEqual(provider.summarize("text"), "Fake summary.")

    def test_env_groq_provider_selection_is_lazy_and_mockable(self):
        fake_provider = FakeSummaryProvider("mock groq")
        with (
            patch.dict(os.environ, {"SUMMARY_PROVIDER": "groq"}, clear=False),
            patch("app.adapters.providers.summary_provider._build_groq_provider", return_value=fake_provider) as builder,
        ):
            provider = build_summary_provider()

        self.assertIs(provider, fake_provider)
        builder.assert_called_once()

    def test_disabled_provider_readiness(self):
        readiness = summary_provider_readiness(config={"provider": "none", "max_input_chars": 123}, env={})

        self.assertEqual(
            readiness.as_dict(),
            {
                "provider_name": "none",
                "configured": False,
                "available": False,
                "reason": "disabled",
                "max_input_chars": 123,
                "live_call_required": False,
            },
        )

    def test_fake_provider_readiness(self):
        readiness = summary_provider_readiness(config={"provider": "none"}, env={"SUMMARY_PROVIDER": "fake"})

        self.assertEqual(readiness.provider_name, "fake")
        self.assertTrue(readiness.configured)
        self.assertTrue(readiness.available)
        self.assertEqual(readiness.reason, "test_or_local_fake")
        self.assertFalse(readiness.live_call_required)

    def test_groq_missing_config_readiness_without_live_call(self):
        with patch("app.adapters.providers.summary_provider._build_groq_provider") as builder:
            readiness = summary_provider_readiness(config={"provider": "groq"}, env={})

        self.assertEqual(readiness.provider_name, "groq")
        self.assertFalse(readiness.configured)
        self.assertFalse(readiness.available)
        self.assertEqual(readiness.reason, "missing_config")
        self.assertFalse(readiness.live_call_required)
        builder.assert_not_called()

    def test_groq_config_present_readiness_without_live_call(self):
        with patch("app.adapters.providers.summary_provider._build_groq_provider") as builder:
            readiness = summary_provider_readiness(config={"provider": "groq"}, env={"GROQ_API_KEY": "secret-key"})

        self.assertEqual(readiness.provider_name, "groq")
        self.assertTrue(readiness.configured)
        self.assertTrue(readiness.available)
        self.assertEqual(readiness.reason, "config_present")
        self.assertFalse(readiness.live_call_required)
        builder.assert_not_called()

    def test_readiness_output_does_not_expose_secrets(self):
        readiness = summary_provider_readiness(config={"provider": "groq"}, env={"GROQ_API_KEY": "secret-key"})
        payload = readiness.as_dict()

        self.assertNotIn("secret-key", str(payload))
        self.assertNotIn("api_key", str(payload).lower())


if __name__ == "__main__":
    unittest.main()
