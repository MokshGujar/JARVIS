import unittest
from unittest.mock import Mock

from app.orchestrator.main_orchestrator import MainOrchestrator
from app.orchestrator.semantic_planner_adapter import SemanticPlannerAdapter
from app.orchestrator.task_planner import TaskPlanner
from app.orchestrator.tool_registry import ToolRegistry
from app.services.automation_service import AutomationService
from app.tools.base import ToolContext


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

    def test_enabled_phase_4a_adapter_classifies_but_returns_no_executable_plan(self):
        fake_planner = _FakeSmartAutomationPlanner()
        adapter = SemanticPlannerAdapter(
            smart_automation_enabled=True,
            semantic_planner_enabled=True,
            planner_factory=lambda: fake_planner,
        )

        plan = adapter.try_plan_action("search Python docs")

        self.assertIsNone(plan)
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


if __name__ == "__main__":
    unittest.main()
