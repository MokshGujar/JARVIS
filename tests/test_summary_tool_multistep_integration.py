import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from app.orchestrator.main_orchestrator import MainOrchestrator
from app.orchestrator.tool_registry import ToolRegistry
from app.services import automation_service as automation_module
from app.services.automation_service import AutomationService
from app.tools.file_tool import FileTool
from app.tools.summary_tool import SummaryTool
from app.tools.tool_inventory import build_readiness_tool_registry


class FakeSummarizer:
    def __init__(self, response="summary ok", *, fail=False):
        self.response = response
        self.fail = fail
        self.calls = []

    def summarize(self, text):
        self.calls.append(text)
        if self.fail:
            raise RuntimeError("summary unavailable")
        return self.response


class SummaryToolMultistepIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parent / "_tmp" / "summary_multistep"
        if self.root.exists():
            shutil.rmtree(self.root)
        self.root.mkdir(parents=True)
        self.desktop = self.root / "Desktop"
        self.documents = self.root / "Documents"
        self.downloads = self.root / "Downloads"
        for folder in (self.desktop, self.documents, self.downloads):
            folder.mkdir()
        self.aliases = {
            "desktop": self.desktop,
            "documents": self.documents,
            "downloads": self.downloads,
            "home": self.root,
            "music": self.root / "Music",
            "pictures": self.root / "Pictures",
            "videos": self.root / "Videos",
        }

    def tearDown(self):
        if self.root.exists():
            shutil.rmtree(self.root)

    def _service(self):
        return AutomationService()

    def test_read_file_and_summarize_executes_summary_tool_with_fake_provider(self):
        notes = self.root / "notes.txt"
        notes.write_text("Jarvis created a test note. It contains useful details.", encoding="utf-8")
        fake = FakeSummarizer("Jarvis note summary.")

        with (
            patch.object(automation_module, "BASE_DIR", self.root),
            patch.object(AutomationService, "USER_PATH_ALIASES", self.aliases),
        ):
            service = self._service()
            orchestrator = MainOrchestrator(
                registry=ToolRegistry([FileTool(service), SummaryTool(fake)]),
                enforce_policy=False,
            )
            result = orchestrator.execute_text("read file notes.txt and summarize it")

        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "multi_step")
        self.assertEqual([step["planned_action"] for step in result["step_results"]], ["read_file", "summarize"])
        self.assertEqual(result["step_results"][1]["summary"], "Jarvis note summary.")
        self.assertIn("Jarvis created a test note", fake.calls[0])

    def test_read_file_and_summarize_no_longer_returns_tool_not_found_for_summary(self):
        notes = self.root / "notes.txt"
        notes.write_text("hello world", encoding="utf-8")

        with (
            patch.object(automation_module, "BASE_DIR", self.root),
            patch.object(AutomationService, "USER_PATH_ALIASES", self.aliases),
        ):
            service = self._service()
            with patch("app.tools.summary_tool.build_summary_provider") as builder:
                builder.return_value = None
                result = service.execute("read file notes.txt and summarize it")

        self.assertFalse(result["success"])
        self.assertTrue(result["partial_success"])
        self.assertEqual(result["failed_tool_name"], "summary")
        self.assertEqual(result["step_results"][1]["error"], "summarizer_unavailable")
        self.assertNotEqual(result["action"], "tool_not_found")

    def test_file_result_is_preserved_if_summary_provider_fails(self):
        notes = self.root / "notes.txt"
        notes.write_text("content to summarize", encoding="utf-8")
        fake = FakeSummarizer(fail=True)

        with (
            patch.object(automation_module, "BASE_DIR", self.root),
            patch.object(AutomationService, "USER_PATH_ALIASES", self.aliases),
        ):
            service = self._service()
            orchestrator = MainOrchestrator(
                registry=ToolRegistry([FileTool(service), SummaryTool(fake)]),
                enforce_policy=False,
            )
            result = orchestrator.execute_text("read file notes.txt and summarize it")

        self.assertFalse(result["success"])
        self.assertTrue(result["partial_success"])
        self.assertEqual(result["step_results"][0]["action"], "read_file")
        self.assertTrue(result["step_results"][0]["success"])
        self.assertEqual(result["step_results"][1]["error"], "summary_failed")

    def test_summary_step_does_not_execute_if_file_read_fails(self):
        fake = FakeSummarizer("should not run")

        with (
            patch.object(automation_module, "BASE_DIR", self.root),
            patch.object(AutomationService, "USER_PATH_ALIASES", self.aliases),
        ):
            service = self._service()
            orchestrator = MainOrchestrator(
                registry=ToolRegistry([FileTool(service), SummaryTool(fake)]),
                enforce_policy=False,
            )
            result = orchestrator.execute_text("read file missing.txt and summarize it")

        self.assertFalse(result["success"])
        self.assertEqual(result["failed_step_id"], "step1")
        self.assertEqual(len(result["step_results"]), 1)
        self.assertEqual(fake.calls, [])

    def test_other_metadata_only_tools_still_return_not_implemented(self):
        registry = build_readiness_tool_registry()

        result = registry.by_name("clipboard").execute(
            __import__("app.tools.base", fromlist=["ToolContext"]).ToolContext(
                command="read clipboard",
                intent="clipboard",
            )
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "not_implemented")


if __name__ == "__main__":
    unittest.main()
