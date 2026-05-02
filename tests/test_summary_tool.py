import unittest
from unittest.mock import patch

from app.orchestrator.tool_registry import ToolRegistry
from app.tools.base import ToolContext
from app.tools.summary_tool import SummaryTool
from app.tools.tool_inventory import build_readiness_tool_registry, get_tool_inventory_record


class FakeSummarizer:
    def __init__(self, response="short summary", *, fail=False):
        self.response = response
        self.fail = fail
        self.calls = []

    def summarize(self, text):
        self.calls.append(text)
        if self.fail:
            raise RuntimeError("provider offline")
        return self.response


class SummaryToolTests(unittest.TestCase):
    def test_summary_tool_is_registered_and_discoverable_by_name(self):
        tool = SummaryTool(FakeSummarizer())
        registry = ToolRegistry([tool])

        self.assertIs(registry.by_name("summary"), tool)
        self.assertIs(registry.by_intent("summarize"), tool)

    def test_readiness_registry_uses_summary_tool(self):
        with patch("app.tools.summary_tool.build_summary_provider"):
            registry = build_readiness_tool_registry()

        self.assertIsInstance(registry.by_name("summary"), SummaryTool)

    def test_summary_tool_summarizes_content_with_fake_provider(self):
        fake = FakeSummarizer("hello summary")
        tool = SummaryTool(fake)

        result = tool.execute(
            ToolContext(
                command="summarize",
                intent="summarize",
                payload={"action": "summarize", "args": {"content": "hello world"}},
            )
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["tool_name"], "summary")
        self.assertEqual(result["summary"], "hello summary")
        self.assertEqual(result["data"]["summary"], "hello summary")
        self.assertEqual(result["input_length"], len("hello world"))
        self.assertEqual(result["output_length"], len("hello summary"))
        self.assertEqual(fake.calls, ["hello world"])

    def test_summary_tool_rejects_empty_content_cleanly(self):
        tool = SummaryTool(FakeSummarizer())

        result = tool.execute(ToolContext(command="", intent="summarize", payload={"action": "summarize", "args": {"content": ""}}))

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "empty_content")
        self.assertEqual(result["tool_name"], "summary")

    def test_summary_tool_returns_clean_failure_without_provider(self):
        with patch("app.tools.summary_tool.build_summary_provider") as builder:
            builder.return_value = None
            tool = SummaryTool()

        result = tool.execute(ToolContext(command="summarize", intent="summarize", payload={"action": "summarize", "args": {"content": "hello"}}))

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "summarizer_unavailable")
        self.assertNotEqual(result["action"], "tool_not_found")

    def test_summary_tool_returns_clean_failure_if_provider_fails(self):
        tool = SummaryTool(FakeSummarizer(fail=True))

        result = tool.execute(ToolContext(command="summarize", intent="summarize", payload={"action": "summarize", "args": {"content": "hello"}}))

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "summary_failed")
        self.assertIn("provider offline", result["message"])

    def test_tool_inventory_marks_summary_as_thin_wrapper(self):
        record = get_tool_inventory_record("summary")

        self.assertEqual(record.current_status, "thin_wrapper")
        self.assertEqual(record.safety_level, "LOW")
        self.assertIn("summarize", record.supported_actions)


if __name__ == "__main__":
    unittest.main()
