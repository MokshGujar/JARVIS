import shutil
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.orchestrator.automation_context import AutomationContext
from app.orchestrator.main_orchestrator import MainOrchestrator
from app.orchestrator.semantic_planner_adapter import SemanticPlannerAdapter
from app.orchestrator.smart_automation_planner import SmartAutomationPlanner
from app.orchestrator.tool_registry import ToolRegistry
from app.services import automation_service as automation_module
from app.services.automation_service import AutomationService
from app.tools.app_tool import AppTool
from app.tools.base import ToolContext
from app.tools.file_tool import FileTool


def _planner():
    return SmartAutomationPlanner()


def _semantic_orchestrator(service):
    return MainOrchestrator(
        registry=ToolRegistry([FileTool(service)]),
        semantic_adapter=SemanticPlannerAdapter(
            smart_automation_enabled=True,
            semantic_planner_enabled=True,
            safe_execution_enabled=True,
        ),
        enforce_policy=True,
    )


class SemanticClaimReliabilityTests(unittest.TestCase):
    def test_natural_file_create_write_variants_are_claimed(self):
        commands = [
            "create a file on my desktop named semantic test and write hello",
            "create a file on desktop named semantic test and write hello",
            "create a file named semantic test and write hello",
            "create a file called semantic test and write hello",
            "make a file on desktop called semantic test with hello in it",
            "make a text file named semantic test and put hello in it",
            "save hello as semantic test on desktop",
            "Jarvis create a file on my desktop named semantic test and write hello in it",
            "please create a file on my desktop named semantic test and write hello",
            "can you create a file on desktop named semantic test and write hello",
        ]

        for command in commands:
            with self.subTest(command=command):
                result = _planner().plan(command, context=AutomationContext(session_id="s1"), dry_run=False)
                intents = [action.intent.value for action in result.semantic_actions]

                self.assertTrue(intents, command)
                self.assertIn(intents[0], {"CREATE_FILE", "SAVE_CONTENT_AS_FILE"})
                self.assertTrue(any(action.file_path == "desktop/semantic test.txt" for action in result.semantic_actions))
                self.assertTrue(any(action.content == "hello" for action in result.semantic_actions))

    def test_wake_word_and_fillers_are_removed_before_claim(self):
        result = _planner().plan("Javis please can you create a file on my desktop named semantic test and write hello", context=AutomationContext(session_id="s1"), dry_run=False)

        self.assertEqual([action.intent.value for action in result.semantic_actions], ["CREATE_FILE", "WRITE_FILE"])
        self.assertIn("wake_word_removed", result.corrections_applied)
        self.assertIn("filler_removed", result.corrections_applied)

    def test_bare_search_files_claims_file_search_not_browser_search(self):
        result = _planner().plan("Search files", context=AutomationContext(session_id="s1"), dry_run=False)

        self.assertEqual(result.domain.value, "file")
        self.assertEqual([action.intent.value for action in result.semantic_actions], ["SEARCH_FILES"])
        self.assertEqual(result.semantic_actions[0].preferred_tool, "file")
        self.assertEqual(result.missing_fields, ["file_search_query"])
        self.assertEqual(result.follow_up_question, "What file name or content should I search for?")

    def test_explicit_web_file_searches_claim_browser_search(self):
        for command in ("Search Google for files", "Search web for files"):
            with self.subTest(command=command):
                result = _planner().plan(command, context=AutomationContext(session_id="s1"), dry_run=False)

                self.assertEqual(result.domain.value, "browser")
                self.assertEqual([action.intent.value for action in result.semantic_actions], ["SEARCH_WEB"])
                self.assertEqual(result.semantic_actions[0].preferred_tool, "browser")
                self.assertEqual(result.semantic_actions[0].query, "files")

    def test_trailing_wake_word_open_calculator_is_semantic_open_app_claim(self):
        result = _planner().plan("open calculator Jarvis", context=AutomationContext(session_id="s1"), dry_run=False)

        self.assertEqual(result.corrected_text, "open calculator")
        self.assertEqual([action.intent.value for action in result.semantic_actions], ["OPEN_APP"])
        self.assertEqual(result.semantic_actions[0].app, "calculator")

    def test_semantic_open_calculator_does_not_send_jarvis_to_legacy_app_opener(self):
        bridge = Mock()
        with patch(
            "app.tools.compatibility_runners.AppCompatibilityRunner.execute",
            return_value={"success": True, "action": "open", "message": "Opening Calculator."},
        ) as runner:
            result = MainOrchestrator(
                registry=ToolRegistry([AppTool(bridge)]),
                semantic_adapter=SemanticPlannerAdapter(
                    smart_automation_enabled=True,
                    semantic_planner_enabled=True,
                    safe_execution_enabled=True,
                ),
                enforce_policy=True,
            ).execute(ToolContext(command="open calculator Jarvis", payload={"automation_context": AutomationContext(session_id="s1")}))

        self.assertTrue(result["success"])
        runner.assert_called_once()
        self.assertEqual(runner.call_args.args[0], "open calculator")
        self.assertNotIn("calculator jarvis", runner.call_args.args[0].lower())

    def test_file_create_write_executes_semantic_file_tool_and_updates_context(self):
        root = Path(__file__).resolve().parent / "_tmp" / "semantic_claim_create"
        if root.exists():
            shutil.rmtree(root)
        desktop = root / "Desktop"
        desktop.mkdir(parents=True)
        try:
            with (
                patch.object(automation_module, "BASE_DIR", root),
                patch.object(
                    AutomationService,
                    "USER_PATH_ALIASES",
                    {
                        "desktop": desktop,
                        "documents": root / "Documents",
                        "downloads": root / "Downloads",
                        "home": root,
                        "music": root / "Music",
                        "pictures": root / "Pictures",
                        "videos": root / "Videos",
                    },
                ),
            ):
                context = AutomationContext(session_id="s1")
                service = AutomationService()
                result = _semantic_orchestrator(service).execute(
                    ToolContext(
                        command="create a file on my desktop named semantic test and write hello",
                        payload={"automation_context": context},
                    )
                )
                target = desktop / "semantic test.txt"

                self.assertTrue(result["success"])
                self.assertEqual(target.read_text(encoding="utf-8"), "hello")
                self.assertEqual(context.last_created_file_path, str(target))
                self.assertEqual(context.last_edited_file_path, str(target))
                self.assertEqual(context.last_content, "hello")
                self.assertEqual(context.last_tool_used, "file")
        finally:
            if root.exists():
                shutil.rmtree(root)

    def test_followup_uses_last_created_file_path_and_missing_context_asks(self):
        context = AutomationContext(session_id="s1", last_created_file_path=r"C:\Users\Moksh\Desktop\semantic test.txt")

        for command in ("put world in it", "add world to it", "write world in it", "append world", "put world in semantic test"):
            with self.subTest(command=command):
                result = _planner().plan(command, context=context, dry_run=False)
                action = result.semantic_actions[0]
                self.assertEqual(action.intent.value, "APPEND_FILE")
                self.assertEqual(action.file_path, context.last_created_file_path)
                self.assertEqual(action.content, "world")

        missing = _planner().plan("put world in it", context=AutomationContext(session_id="empty"), dry_run=False)
        self.assertEqual(missing.missing_fields, ["file"])
        self.assertEqual(missing.follow_up_question, "Which file should I use?")

    def test_uncertain_port_waldenet_clarifies_and_does_not_claim_content_task(self):
        adapter = SemanticPlannerAdapter(
            smart_automation_enabled=True,
            semantic_planner_enabled=True,
            safe_execution_enabled=True,
        )

        result = adapter.try_live_result("Port Waldenet", context=AutomationContext(session_id="s1"))

        self.assertEqual(result["action"], "semantic_clarification_required")
        self.assertEqual(result["message"], "Did you mean put world in it?")

    def test_claim_diagnostics_are_emitted(self):
        adapter = SemanticPlannerAdapter(
            smart_automation_enabled=True,
            semantic_planner_enabled=True,
            safe_execution_enabled=True,
        )

        with self.assertLogs("app.orchestrator.semantic_planner_adapter", level="INFO") as logs:
            adapter.try_live_result("Jarvis create a file on my desktop named semantic test and write hello", context=AutomationContext(session_id="s1"))

        output = "\n".join(logs.output)
        self.assertIn("[SEMANTIC-CLAIM]", output)
        self.assertIn("wake_word_removed=true", output)
        self.assertIn("claimed=true", output)
        self.assertIn("final_route=semantic_safe_execution", output)


if __name__ == "__main__":
    unittest.main()
