import unittest
import shutil
from pathlib import Path
from unittest.mock import Mock, patch

from app.orchestrator.automation_context import AutomationContext
from app.orchestrator.main_orchestrator import MainOrchestrator
from app.orchestrator.semantic_planner_adapter import SemanticPlannerAdapter
from app.orchestrator.task_planner import TaskPlanner
from app.orchestrator.tool_registry import ToolRegistry
from app.services import automation_service as automation_module
from app.services.automation_service import AutomationService
from app.tools.base import ToolContext
from app.tools.file_tool import FileTool


def _exploding_planner_factory():
    raise AssertionError("SmartAutomationPlanner should not be constructed while semantic planning is disabled.")


class _FakeSemanticPlanResult:
    def as_dict(self):
        return {"phase": "4a_dormant"}


class _FakeSmartAutomationPlanner:
    def __init__(self):
        self.calls = []

    def plan(self, text, context=None, dry_run=True):
        self.calls.append({"text": text, "context": context, "dry_run": dry_run})
        return _FakeSemanticPlanResult()


class _FakeTool:
    def __init__(self, name, handler):
        self.name = name
        self.handler = handler
        self.calls = []

    def can_handle(self, intent):
        return True

    def execute(self, context, **kwargs):
        self.calls.append(context)
        return self.handler(context)


class SemanticPlannerOrchestratorIntegrationTests(unittest.TestCase):
    def test_disabled_semantic_flags_do_not_construct_smart_planner(self):
        for smart_enabled, semantic_enabled in ((False, False), (False, True), (True, False)):
            with self.subTest(smart_enabled=smart_enabled, semantic_enabled=semantic_enabled):
                adapter = SemanticPlannerAdapter(
                    smart_automation_enabled=smart_enabled,
                    semantic_planner_enabled=semantic_enabled,
                    planner_factory=_exploding_planner_factory,
                )
                planner = TaskPlanner(semantic_adapter=adapter)

                plan = planner.plan("open chrome and search for python docs")

                self.assertTrue(plan.is_multistep)
                self.assertEqual([(step.tool_name, step.action) for step in plan.steps], [("app", "open"), ("browser", "search")])
                self.assertIsNone(adapter.last_semantic_result)

    def test_enabled_phase_4b_dry_run_adapter_classifies_but_returns_no_executable_plan(self):
        fake_planner = _FakeSmartAutomationPlanner()
        adapter = SemanticPlannerAdapter(
            smart_automation_enabled=True,
            semantic_planner_enabled=True,
            dry_run_enabled=True,
            planner_factory=lambda: fake_planner,
        )

        result = adapter.try_dry_run_response("plan: search Python docs")

        self.assertIsNotNone(result)
        self.assertTrue(result["dry_run"])
        self.assertFalse(result["executable"])
        self.assertEqual(fake_planner.calls, [{"text": "search Python docs", "context": None, "dry_run": True}])
        self.assertIsInstance(adapter.last_semantic_result, _FakeSemanticPlanResult)

    def test_legacy_single_step_result_is_identical_with_disabled_adapter(self):
        def run_with(adapter=None):
            tool = Mock()
            tool.name = "file"
            tool.execute.return_value = {"success": True, "action": "read_file", "message": "notes.txt:\nhello"}
            orchestrator = MainOrchestrator(
                registry=ToolRegistry([tool]),
                semantic_adapter=adapter,
                enforce_policy=False,
            )
            result = orchestrator.execute_text("read file notes.txt", session_id="s1")
            return result, tool

        disabled_adapter = SemanticPlannerAdapter(
            smart_automation_enabled=True,
            semantic_planner_enabled=False,
            planner_factory=_exploding_planner_factory,
        )

        baseline, baseline_tool = run_with()
        with_adapter, adapter_tool = run_with(disabled_adapter)

        self.assertEqual(with_adapter, baseline)
        self.assertEqual(baseline_tool.execute.call_count, 1)
        self.assertEqual(adapter_tool.execute.call_count, 1)
        self.assertEqual(adapter_tool.execute.call_args.args[0].intent, "file")

    def test_legacy_multistep_planning_remains_unchanged_with_disabled_adapter(self):
        adapter = SemanticPlannerAdapter(
            smart_automation_enabled=True,
            semantic_planner_enabled=False,
            planner_factory=_exploding_planner_factory,
        )
        plan = TaskPlanner(semantic_adapter=adapter).plan("open chrome and search for python docs")

        self.assertTrue(plan.is_multistep)
        self.assertEqual([(step.tool_name, step.intent, step.action) for step in plan.steps], [("app", "app_open", "open"), ("browser", "browser_search", "search")])
        self.assertEqual(plan.steps[0].args, {"app": "chrome"})
        self.assertEqual(plan.steps[1].args, {"query": "python docs"})

    def test_main_orchestrator_threads_disabled_adapter_without_changing_route_order(self):
        adapter = SemanticPlannerAdapter(
            smart_automation_enabled=True,
            semantic_planner_enabled=False,
            planner_factory=_exploding_planner_factory,
        )
        tool = Mock()
        tool.name = "file"
        tool.execute.return_value = {"success": True, "action": "read_file", "message": "notes.txt:\nhello"}
        orchestrator = MainOrchestrator(registry=ToolRegistry([tool]), semantic_adapter=adapter, enforce_policy=False)

        result = orchestrator.execute(ToolContext(command="read file notes.txt", session_id="s1"))

        self.assertTrue(result["success"])
        self.assertEqual(result["selected_tool"], "file")
        self.assertEqual(result["scenario"], "file.read")
        self.assertEqual(result["policy"]["safety_level"], "LOW")
        tool.execute.assert_called_once()

    def test_automation_service_has_no_live_semantic_planner_state_in_phase_4a(self):
        service = AutomationService()

        self.assertFalse(hasattr(service, "smart_automation_planner"))
        self.assertFalse(hasattr(service, "semantic_planner_adapter"))

    def test_plan_open_chrome_search_returns_dry_run_response_without_tool_executor(self):
        tool_executor = Mock()
        tool_executor.execute.side_effect = AssertionError("ToolExecutor must not run dry-run plans.")
        orchestrator = MainOrchestrator(
            registry=ToolRegistry(),
            semantic_adapter=SemanticPlannerAdapter(smart_automation_enabled=True, semantic_planner_enabled=True, dry_run_enabled=True),
            tool_executor=tool_executor,
            enforce_policy=False,
        )

        result = orchestrator.execute_text("plan: open Chrome and search Python docs")

        self.assertTrue(result["success"])
        self.assertTrue(result["dry_run"])
        self.assertFalse(result["executable"])
        self.assertIn("Open or focus Chrome", result["display_text"])
        self.assertIn("Select the address or search bar", result["display_text"])
        self.assertIn("Type python docs", result["display_text"])
        self.assertIn("No actions were run", result["display_text"])
        tool_executor.execute.assert_not_called()

    def test_dry_run_file_creation_explains_steps_and_does_not_execute_file_tool(self):
        file_tool = Mock()
        file_tool.name = "file"
        file_tool.execute.side_effect = AssertionError("FileTool must not run dry-run plans.")
        orchestrator = MainOrchestrator(
            registry=ToolRegistry([file_tool]),
            semantic_adapter=SemanticPlannerAdapter(smart_automation_enabled=True, semantic_planner_enabled=True, dry_run_enabled=True),
            enforce_policy=False,
        )

        result = orchestrator.execute_text("dry run create a file on Desktop named notes and write hello")

        self.assertTrue(result["success"])
        self.assertIn("Create notes.txt on your Desktop", result["display_text"])
        self.assertIn("Write hello into it", result["display_text"])
        self.assertIn("Verify the file was created", result["display_text"])
        self.assertIn("No actions were run", result["display_text"])
        file_tool.execute.assert_not_called()

    def test_dry_run_risky_delete_mentions_confirmation_and_executes_nothing(self):
        file_tool = Mock()
        file_tool.name = "file"
        context = AutomationContext(session_id="s1", last_created_file_path="notes.txt")
        orchestrator = MainOrchestrator(
            registry=ToolRegistry([file_tool]),
            semantic_adapter=SemanticPlannerAdapter(smart_automation_enabled=True, semantic_planner_enabled=True, dry_run_enabled=True),
            enforce_policy=True,
        )

        result = orchestrator.execute(
            ToolContext(
                command="tell me what you would do before deleting that file",
                payload={"automation_context": context},
            )
        )

        self.assertTrue(result["requires_confirmation"])
        self.assertEqual(result["safety_level"], "CRITICAL")
        self.assertIn("confirmation", result["display_text"].lower())
        self.assertIn("deleting notes.txt", result["display_text"])
        self.assertIn("No actions were run", result["display_text"])
        file_tool.execute.assert_not_called()

    def test_dry_run_missing_file_context_asks_one_short_followup(self):
        result = MainOrchestrator(
            registry=ToolRegistry(),
            semantic_adapter=SemanticPlannerAdapter(smart_automation_enabled=True, semantic_planner_enabled=True, dry_run_enabled=True),
            enforce_policy=False,
        ).execute_text("what will you do before deleting that file")

        self.assertFalse(result["success"])
        self.assertEqual(result["missing_fields"], ["file"])
        self.assertIn("which file", result["display_text"].lower())
        self.assertIn("No actions were run", result["display_text"])

    def test_dry_run_send_it_without_draft_asks_which_message(self):
        result = MainOrchestrator(
            registry=ToolRegistry(),
            semantic_adapter=SemanticPlannerAdapter(smart_automation_enabled=True, semantic_planner_enabled=True, dry_run_enabled=True),
            enforce_policy=False,
        ).execute_text("what will you do before sending it?")

        self.assertFalse(result["success"])
        self.assertEqual(result["missing_fields"], ["message_draft"])
        self.assertIn("which message", result["display_text"].lower())
        self.assertIn("No actions were run", result["display_text"])

    def test_dry_run_does_not_call_app_interaction_or_message_tools(self):
        tools = []
        for name in ("app", "app_interaction", "browser", "file", "whatsapp"):
            tool = Mock()
            tool.name = name
            tool.execute.side_effect = AssertionError(f"{name} must not run dry-run plans.")
            tools.append(tool)
        orchestrator = MainOrchestrator(
            registry=ToolRegistry(tools),
            semantic_adapter=SemanticPlannerAdapter(smart_automation_enabled=True, semantic_planner_enabled=True, dry_run_enabled=True),
            enforce_policy=False,
        )

        result = orchestrator.execute_text("show me the plan for opening Chrome and searching Python docs")

        self.assertTrue(result["dry_run"])
        self.assertIn("No actions were run", result["display_text"])
        for tool in tools:
            tool.execute.assert_not_called()

    def test_normal_open_chrome_search_still_uses_legacy_multistep_and_not_semantic_planner(self):
        fake_planner = _FakeSmartAutomationPlanner()
        app_tool = Mock()
        app_tool.name = "app"
        app_tool.execute.return_value = {"success": True, "action": "open", "message": "Opening Chrome."}
        browser_tool = Mock()
        browser_tool.name = "browser"
        browser_tool.execute.return_value = {"success": True, "action": "search", "message": "Searching Google for python docs."}
        orchestrator = MainOrchestrator(
            registry=ToolRegistry([app_tool, browser_tool]),
            semantic_adapter=SemanticPlannerAdapter(
                smart_automation_enabled=True,
                semantic_planner_enabled=True,
                safe_execution_enabled=False,
                dry_run_enabled=True,
                planner_factory=lambda: fake_planner,
            ),
            enforce_policy=False,
        )

        result = orchestrator.execute_text("open Chrome and search for python docs")

        self.assertTrue(result["success"])
        self.assertTrue(result["is_multistep"])
        self.assertNotIn("dry_run", result)
        self.assertEqual(fake_planner.calls, [])
        app_tool.execute.assert_called_once()
        browser_tool.execute.assert_called_once()

    def test_normal_read_file_still_uses_legacy_router_and_not_semantic_planner(self):
        fake_planner = _FakeSmartAutomationPlanner()
        file_tool = Mock()
        file_tool.name = "file"
        file_tool.execute.return_value = {"success": True, "action": "read_file", "message": "notes.txt:\nhello"}
        orchestrator = MainOrchestrator(
            registry=ToolRegistry([file_tool]),
            semantic_adapter=SemanticPlannerAdapter(
                smart_automation_enabled=True,
                semantic_planner_enabled=True,
                safe_execution_enabled=False,
                dry_run_enabled=True,
                planner_factory=lambda: fake_planner,
            ),
            enforce_policy=False,
        )

        result = orchestrator.execute_text("read file notes.txt")

        self.assertTrue(result["success"])
        self.assertEqual(result["selected_tool"], "file")
        self.assertEqual(result["scenario"], "file.read")
        self.assertEqual(fake_planner.calls, [])
        file_tool.execute.assert_called_once()

    def test_disabled_dry_run_flag_returns_unavailable_without_semantic_planner(self):
        adapter = SemanticPlannerAdapter(
            smart_automation_enabled=True,
            semantic_planner_enabled=True,
            dry_run_enabled=False,
            planner_factory=_exploding_planner_factory,
        )

        result = MainOrchestrator(registry=ToolRegistry(), semantic_adapter=adapter, enforce_policy=False).execute_text(
            "plan: open Chrome and search Python docs"
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["action"], "semantic_dry_run_unavailable")
        self.assertIn("unavailable", result["message"])
        self.assertIn("No actions were run", result["message"])

    def test_do_it_after_dry_run_plan_does_not_execute_phase_4b_plan(self):
        from app.orchestrator import semantic_planner_adapter as adapter_module

        with (
            patch.object(adapter_module, "SMART_AUTOMATION_ENABLED", True),
            patch.object(adapter_module, "SEMANTIC_PLANNER_ENABLED", True),
            patch.object(adapter_module, "AUTOMATION_DRY_RUN_ENABLED", True),
        ):
            service = AutomationService()
            planned = service.execute("plan: open Chrome and search Python docs")
            confirmed = service.execute("do it")

        self.assertTrue(planned["dry_run"])
        self.assertFalse(confirmed["success"])
        self.assertEqual(confirmed["action"], "dry_run_not_executable")
        self.assertFalse(confirmed["executable"])
        self.assertIn("not executable yet", confirmed["message"])
        self.assertIn("No actions were run", confirmed["message"])

    def test_default_safe_execution_disabled_preserves_legacy_and_does_not_call_semantic_planner(self):
        fake_planner = _FakeSmartAutomationPlanner()
        app_tool = Mock()
        app_tool.name = "app"
        app_tool.execute.return_value = {"success": True, "action": "open", "message": "Opening Chrome."}
        browser_tool = Mock()
        browser_tool.name = "browser"
        browser_tool.execute.return_value = {"success": True, "action": "search", "message": "Searching Google for python docs."}

        result = MainOrchestrator(
            registry=ToolRegistry([app_tool, browser_tool]),
            semantic_adapter=SemanticPlannerAdapter(
                smart_automation_enabled=True,
                semantic_planner_enabled=True,
                safe_execution_enabled=False,
                planner_factory=lambda: fake_planner,
            ),
            enforce_policy=False,
        ).execute_text("open Chrome and search for python docs")

        self.assertTrue(result["success"])
        self.assertEqual(fake_planner.calls, [])
        app_tool.execute.assert_called_once()
        browser_tool.execute.assert_called_once()

    def test_safe_semantic_file_create_write_executes_through_tool_executor_and_updates_context(self):
        root = Path(__file__).resolve().parent / "_tmp" / "semantic_file_create_write"
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
                result = MainOrchestrator(
                    registry=ToolRegistry([FileTool(AutomationService())]),
                    semantic_adapter=SemanticPlannerAdapter(
                        smart_automation_enabled=True,
                        semantic_planner_enabled=True,
                        safe_execution_enabled=True,
                    ),
                    enforce_policy=True,
                ).execute(ToolContext(command="create a file on desktop named notes and write hello", payload={"automation_context": context}))

                target = desktop / "notes.txt"
                self.assertTrue(result["success"])
                self.assertTrue(result["semantic_execution"])
                self.assertEqual(target.read_text(encoding="utf-8"), "hello")
                self.assertEqual(context.last_created_file_path, str(target))
                self.assertEqual(context.last_edited_file_path, str(target))
                self.assertEqual(context.last_content, "hello")
        finally:
            if root.exists():
                shutil.rmtree(root)

    def test_followup_put_hello_in_it_uses_last_created_file_path(self):
        root = Path(__file__).resolve().parent / "_tmp" / "semantic_put_in_it"
        if root.exists():
            shutil.rmtree(root)
        desktop = root / "Desktop"
        desktop.mkdir(parents=True)
        target = desktop / "test.txt"
        target.touch()
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
                context = AutomationContext(session_id="s1", last_created_file_path=str(target))
                result = MainOrchestrator(
                    registry=ToolRegistry([FileTool(AutomationService())]),
                    semantic_adapter=SemanticPlannerAdapter(
                        smart_automation_enabled=True,
                        semantic_planner_enabled=True,
                        safe_execution_enabled=True,
                    ),
                    enforce_policy=True,
                ).execute(ToolContext(command="put hello in it", payload={"automation_context": context}))

                self.assertTrue(result["success"])
                self.assertEqual(target.read_text(encoding="utf-8"), "hello")
                self.assertEqual(context.last_edited_file_path, str(target))
        finally:
            if root.exists():
                shutil.rmtree(root)

    def test_followup_put_world_in_it_missing_context_asks_file_and_skips_legacy(self):
        file_tool = _FakeTool("file", lambda context: {"success": True, "action": "append_file", "message": "should not run"})

        result = MainOrchestrator(
            registry=ToolRegistry([file_tool]),
            semantic_adapter=SemanticPlannerAdapter(
                smart_automation_enabled=True,
                semantic_planner_enabled=True,
                safe_execution_enabled=True,
            ),
            enforce_policy=True,
        ).execute(ToolContext(command="put World in it", payload={"automation_context": AutomationContext(session_id="s1")}))

        self.assertFalse(result["success"])
        self.assertEqual(result["action"], "semantic_followup_required")
        self.assertEqual(result["follow_up_question"], "Which file should I use?")
        self.assertEqual(len(file_tool.calls), 0)

    def test_safe_semantic_browser_visible_search_uses_mocked_tools(self):
        app_tool = _FakeTool("app", lambda context: {"success": True, "action": "open", "message": "Opening Chrome."})
        ui_tool = _FakeTool(
            "app_interaction",
            lambda context: {"success": True, "action": context.payload["action"], "message": "ok", "data": {"verification_status": "likely_success"}},
        )
        context = AutomationContext(session_id="s1")

        result = MainOrchestrator(
            registry=ToolRegistry([app_tool, ui_tool]),
            semantic_adapter=SemanticPlannerAdapter(smart_automation_enabled=True, semantic_planner_enabled=True, safe_execution_enabled=True),
            enforce_policy=True,
        ).execute(ToolContext(command="open Chrome and search Python docs", payload={"automation_context": context}))

        self.assertTrue(result["success"])
        self.assertEqual([call.payload["action"] for call in app_tool.calls + ui_tool.calls], ["open", "select_address_bar", "replace_current_field", "submit_current_field"])
        self.assertEqual(ui_tool.calls[1].payload["args"]["text"], "python docs")
        self.assertEqual(context.active_app, "chrome")
        self.assertEqual(context.last_browser_query, "python docs")

    def test_app_open_failure_prevents_semantic_typing(self):
        app_tool = _FakeTool("app", lambda context: {"success": False, "action": "open", "message": "Could not open Notepad."})
        ui_tool = _FakeTool("app_interaction", lambda context: {"success": True, "action": context.payload["action"], "message": "should not run"})

        result = MainOrchestrator(
            registry=ToolRegistry([app_tool, ui_tool]),
            semantic_adapter=SemanticPlannerAdapter(smart_automation_enabled=True, semantic_planner_enabled=True, safe_execution_enabled=True),
            enforce_policy=True,
        ).execute_text("open Notepad and type hello")

        self.assertFalse(result["success"])
        self.assertEqual(result["failed_tool_name"], "app")
        self.assertEqual(len(app_tool.calls), 1)
        self.assertEqual(len(ui_tool.calls), 0)
        self.assertNotIn("Done", result["message"])

    def test_replace_that_uses_last_browser_query_and_updates_context(self):
        browser_tool = _FakeTool(
            "browser",
            lambda context: {
                "success": True,
                "action": "search",
                "message": "Searching Google for ai news.",
                "query": context.payload["args"]["query"],
            },
        )
        context = AutomationContext(session_id="s1", last_browser_query="Python docs", active_app="chrome")

        result = MainOrchestrator(
            registry=ToolRegistry([browser_tool]),
            semantic_adapter=SemanticPlannerAdapter(smart_automation_enabled=True, semantic_planner_enabled=True, safe_execution_enabled=True),
            enforce_policy=True,
        ).execute(ToolContext(command="replace that with AI news", payload={"automation_context": context}))

        self.assertTrue(result["success"])
        self.assertEqual(browser_tool.calls[0].payload["args"]["query"], "ai news")
        self.assertEqual(context.last_browser_query, "ai news")

    def test_missing_semantic_query_asks_one_question_and_executes_nothing(self):
        browser_tool = _FakeTool("browser", lambda context: {"success": True, "action": "search", "message": "should not run"})

        result = MainOrchestrator(
            registry=ToolRegistry([browser_tool]),
            semantic_adapter=SemanticPlannerAdapter(smart_automation_enabled=True, semantic_planner_enabled=True, safe_execution_enabled=True),
            enforce_policy=True,
        ).execute_text("search this")

        self.assertFalse(result["success"])
        self.assertEqual(result["action"], "semantic_followup_required")
        self.assertEqual(result["follow_up_question"], "What should I search?")
        self.assertEqual(len(browser_tool.calls), 0)

    def test_risky_semantic_actions_are_blocked_even_when_policy_not_enforced(self):
        for command, setup_context in (
            ("delete it", AutomationContext(session_id="s1", last_created_file_path="notes.txt")),
            ("send it now", AutomationContext(session_id="s1", current_message_draft={"recipient": "Rahul", "content": "hello"})),
            ("call Rahul", AutomationContext(session_id="s1")),
            ("submit the form", AutomationContext(session_id="s1")),
            ("click delete", AutomationContext(session_id="s1")),
        ):
            risky_tool = _FakeTool("file", lambda context: {"success": True, "action": "danger", "message": "should not run"})
            with self.subTest(command=command):
                result = MainOrchestrator(
                    registry=ToolRegistry([risky_tool]),
                    semantic_adapter=SemanticPlannerAdapter(smart_automation_enabled=True, semantic_planner_enabled=True, safe_execution_enabled=True),
                    enforce_policy=False,
                ).execute(ToolContext(command=command, payload={"automation_context": setup_context}))

                self.assertFalse(result["success"])
                self.assertIn(result["action"], {"semantic_confirmation_required", "semantic_followup_required"})
                self.assertEqual(len(risky_tool.calls), 0)

    def test_semantic_claimed_unmappable_command_does_not_fall_through_to_legacy(self):
        system_tool = _FakeTool("system", lambda context: {"success": True, "action": "screenshot", "message": "should not run"})

        result = MainOrchestrator(
            registry=ToolRegistry([system_tool]),
            semantic_adapter=SemanticPlannerAdapter(smart_automation_enabled=True, semantic_planner_enabled=True, safe_execution_enabled=True),
            enforce_policy=False,
        ).execute_text("take a screenshot")

        self.assertFalse(result["success"])
        self.assertEqual(result["action"], "unsupported_semantic_action")
        self.assertEqual(len(system_tool.calls), 0)

    def test_duplicate_semantic_mutating_action_is_blocked(self):
        root = Path(__file__).resolve().parent / "_tmp" / "semantic_duplicate_write"
        if root.exists():
            shutil.rmtree(root)
        desktop = root / "Desktop"
        desktop.mkdir(parents=True)
        target = desktop / "test.txt"
        target.touch()
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
                context = AutomationContext(session_id="s1", last_created_file_path=str(target))
                orchestrator = MainOrchestrator(
                    registry=ToolRegistry([FileTool(AutomationService())]),
                    semantic_adapter=SemanticPlannerAdapter(
                        smart_automation_enabled=True,
                        semantic_planner_enabled=True,
                        safe_execution_enabled=True,
                    ),
                    enforce_policy=True,
                )

                first = orchestrator.execute(ToolContext(command="put hello in it", payload={"automation_context": context}))
                second = orchestrator.execute(ToolContext(command="put hello in it", payload={"automation_context": context}))

                self.assertTrue(first["success"])
                self.assertFalse(second["success"])
                self.assertEqual(second["action"], "duplicate_semantic_action")
                self.assertIn("same action", second["message"])
        finally:
            if root.exists():
                shutil.rmtree(root)

    def test_semantic_context_redacts_sensitive_content(self):
        ui_tool = _FakeTool("app_interaction", lambda context: {"success": True, "action": "append_text", "message": "typed"})
        context = AutomationContext(session_id="s1", active_app="notepad", current_document_context={"app": "notepad"})

        result = MainOrchestrator(
            registry=ToolRegistry([ui_tool]),
            semantic_adapter=SemanticPlannerAdapter(smart_automation_enabled=True, semantic_planner_enabled=True, safe_execution_enabled=True),
            enforce_policy=True,
        ).execute(ToolContext(command="add password: hunter2", payload={"automation_context": context}))

        self.assertTrue(result["success"])
        self.assertIn("[REDACTED]", context.last_content)

    def test_automation_service_uses_session_context_for_safe_semantic_execution_when_enabled(self):
        from app.orchestrator import semantic_planner_adapter as adapter_module

        root = Path(__file__).resolve().parent / "_tmp" / "semantic_service_context"
        if root.exists():
            shutil.rmtree(root)
        desktop = root / "Desktop"
        desktop.mkdir(parents=True)
        try:
            with (
                patch.object(adapter_module, "SMART_AUTOMATION_ENABLED", True),
                patch.object(adapter_module, "SEMANTIC_PLANNER_ENABLED", True),
                patch.object(adapter_module, "SEMANTIC_SAFE_EXECUTION_ENABLED", True),
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
                service = AutomationService()
                created = service.execute("create a file on desktop named service_notes and write hello", session_id="s1")
                followup = service.execute("put World in it", session_id="s1")
                context = service._automation_context_store.get("s1")

                self.assertTrue(created["success"])
                self.assertTrue(created["semantic_execution"])
                self.assertTrue(followup["success"])
                self.assertTrue(followup["semantic_execution"])
                self.assertEqual((desktop / "service_notes.txt").read_text(encoding="utf-8"), "helloWorld")
                self.assertEqual(context.last_content, "World")
                self.assertEqual(context.last_created_file_path, str(desktop / "service_notes.txt"))
                self.assertEqual(context.last_edited_file_path, str(desktop / "service_notes.txt"))
        finally:
            if root.exists():
                shutil.rmtree(root)


if __name__ == "__main__":
    unittest.main()
