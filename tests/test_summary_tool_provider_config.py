import os
import unittest
from unittest.mock import patch

from app.adapters.providers.fake_summary_provider import FakeSummaryProvider
from app.tools.base import ToolContext
from app.tools.summary_tool import SummaryTool


class RecordingProvider:
    def __init__(self, response="ok"):
        self.response = response
        self.calls = []

    def summarize(self, text, mode="summary"):
        self.calls.append({"text": text, "mode": mode})
        return self.response


class SummaryToolProviderConfigTests(unittest.TestCase):
    def test_summary_tool_maps_summarize_to_summary_mode(self):
        provider = RecordingProvider("summary")
        tool = SummaryTool(provider)

        result = tool.execute(ToolContext(command="", intent="summarize", payload={"action": "summarize", "args": {"content": "hello"}}))

        self.assertTrue(result["success"])
        self.assertEqual(provider.calls, [{"text": "hello", "mode": "summary"}])

    def test_summary_tool_maps_extract_key_points_to_key_points_mode(self):
        provider = RecordingProvider("points")
        tool = SummaryTool(provider)

        result = tool.execute(ToolContext(command="", intent="extract_key_points", payload={"action": "extract_key_points", "args": {"content": "hello"}}))

        self.assertTrue(result["success"])
        self.assertEqual(provider.calls, [{"text": "hello", "mode": "key_points"}])

    def test_summary_tool_maps_make_notes_to_notes_mode(self):
        provider = RecordingProvider("notes")
        tool = SummaryTool(provider)

        result = tool.execute(ToolContext(command="", intent="make_notes", payload={"action": "make_notes", "args": {"content": "hello"}}))

        self.assertTrue(result["success"])
        self.assertEqual(provider.calls, [{"text": "hello", "mode": "notes"}])

    def test_summary_tool_rejects_very_long_content_without_provider_call(self):
        provider = RecordingProvider("should not run")
        tool = SummaryTool(provider, max_input_chars=5)

        result = tool.execute(ToolContext(command="", intent="summarize", payload={"action": "summarize", "args": {"content": "too long"}}))

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "content_too_long")
        self.assertEqual(provider.calls, [])

    def test_summary_tool_default_config_does_not_require_api_key(self):
        with patch.dict(os.environ, {"SUMMARY_PROVIDER": "none"}, clear=False):
            tool = SummaryTool()
            result = tool.execute(ToolContext(command="", intent="summarize", payload={"action": "summarize", "args": {"content": "hello"}}))

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "summarizer_unavailable")
        self.assertEqual(result["provider_readiness"]["provider_name"], "none")
        self.assertFalse(result["provider_readiness"]["live_call_required"])

    def test_summary_tool_can_use_configured_fake_provider_without_network(self):
        with (
            patch.dict(os.environ, {"SUMMARY_PROVIDER": "fake"}, clear=False),
            patch("app.tools.summary_tool.build_summary_provider", return_value=FakeSummaryProvider("configured fake")) as builder,
        ):
            tool = SummaryTool()
            result = tool.execute(ToolContext(command="", intent="summarize", payload={"action": "summarize", "args": {"content": "hello"}}))

        self.assertTrue(result["success"])
        self.assertEqual(result["summary"], "configured fake")
        builder.assert_called_once()


if __name__ == "__main__":
    unittest.main()
