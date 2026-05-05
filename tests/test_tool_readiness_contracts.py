import unittest
from unittest.mock import Mock

from app.orchestrator.action_plan import ActionPlan, ActionStep
from app.orchestrator.intent_router import RouteDecision
from app.orchestrator.scenario_policy import ScenarioPolicy
from app.orchestrator.task_planner import TaskPlanner
from app.orchestrator.tool_executor import ToolExecutor
from app.tools.app_tool import AppTool
from app.tools.app_interaction_tool import AppInteractionTool
from app.tools.base import ToolContext, ToolResult, normalize_tool_result
from app.tools.browser_tool import BrowserTool
from app.tools.file_tool import FileTool
from app.tools.system_tool import SystemTool
from app.tools.summary_tool import SummaryTool
from app.tools.tool_inventory import DisabledTool, MetadataTool, build_readiness_tool_registry, get_tool_inventory, get_tool_inventory_record


class ToolReadinessContractTests(unittest.TestCase):
    def test_every_inventory_tool_is_discoverable_by_name_in_readiness_registry(self):
        registry = build_readiness_tool_registry()

        for record in get_tool_inventory():
            with self.subTest(tool=record.name):
                self.assertTrue(registry.contains(record.name))
                self.assertEqual(registry.by_name(record.name).name, record.name)

    def test_live_routed_tools_can_be_overridden_with_real_tool_instances(self):
        live_tools = [FileTool(Mock()), AppTool(Mock()), BrowserTool(automation_bridge=Mock()), SystemTool(Mock())]
        registry = build_readiness_tool_registry(live_tools)

        for tool in live_tools:
            with self.subTest(tool=tool.name):
                self.assertIs(registry.by_name(tool.name), tool)

    def test_live_routed_tool_records_exist_in_registry(self):
        registry = build_readiness_tool_registry([FileTool(Mock()), AppTool(Mock()), BrowserTool(automation_bridge=Mock()), SystemTool(Mock())])

        for name in ("file", "app", "browser", "system"):
            with self.subTest(tool=name):
                self.assertEqual(get_tool_inventory_record(name).current_status, "live_routed")
                self.assertTrue(registry.contains(name))

    def test_app_interaction_readiness_registry_uses_real_boundary_tool(self):
        registry = build_readiness_tool_registry()

        self.assertEqual(get_tool_inventory_record("app_interaction").current_status, "thin_wrapper")
        self.assertIsInstance(registry.by_name("app_interaction"), AppInteractionTool)

    def test_metadata_only_tools_return_clean_not_implemented(self):
        registry = build_readiness_tool_registry()

        for name in ("terminal", "message"):
            with self.subTest(tool=name):
                tool = registry.by_name(name)
                self.assertIsInstance(tool, MetadataTool)
                result = tool.execute(ToolContext(command="planned", intent=name, payload={"action": "demo_action"}))
                self.assertFalse(result["success"])
                self.assertEqual(result["tool_name"], name)
                self.assertEqual(result["error"], "not_implemented")
                self.assertEqual(result["action"], "not_implemented")
                self.assertEqual(result["data"]["tool_name"], name)
                self.assertEqual(result["data"]["requested_action"], "demo_action")
                self.assertIn("not implemented", result["message"])
                self.assertIn("safety_level", result)
                self.assertIn("requires_confirmation", result)
                self.assertIn("requires_voice_permission", result)

        self.assertIsInstance(registry.by_name("summary"), SummaryTool)

    def test_disabled_tools_return_clean_disabled_result(self):
        registry = build_readiness_tool_registry()

        for name in ("voice_identity", "task_status"):
            with self.subTest(tool=name):
                tool = registry.by_name(name)
                self.assertIsInstance(tool, DisabledTool)
                result = tool.execute(ToolContext(command="planned", intent=name, payload={"action": "status"}))
                self.assertFalse(result["success"])
                self.assertEqual(result["tool_name"], name)
                self.assertEqual(result["error"], "tool_disabled")
                self.assertEqual(result["action"], "disabled")
                self.assertEqual(result["data"]["tool_name"], name)
                self.assertEqual(result["data"]["requested_action"], "status")

    def test_inventory_policy_defaults_gate_high_and_critical_tools(self):
        policy = ScenarioPolicy()

        high = policy.evaluate(RouteDecision("keyboard_mouse.click", "keyboard_mouse", "keyboard_mouse", "ui_automation", "click"))
        critical = policy.evaluate(RouteDecision("terminal.execute", "terminal", "terminal", "developer", "execute"))

        self.assertEqual(high.safety_level, "HIGH")
        self.assertTrue(high.requires_confirmation)
        self.assertFalse(high.requires_face_step_up)
        self.assertEqual(critical.safety_level, "CRITICAL")
        self.assertTrue(critical.requires_confirmation)
        self.assertFalse(critical.requires_face_step_up)
        self.assertTrue(critical.requires_voice_permission)

    def test_tool_policy_does_not_require_face_step_up_by_default(self):
        policy = ScenarioPolicy()

        delete_file = policy.evaluate(RouteDecision("file.delete_file", "file", "file", "file", "delete_file"))
        send_message = policy.evaluate(RouteDecision("message.send", "message", "message", "communication", "send_message"))

        self.assertFalse(delete_file.requires_face_step_up)
        self.assertFalse(send_message.requires_face_step_up)

    def test_inventory_policy_uses_action_level_safety_before_tool_default(self):
        policy = ScenarioPolicy()

        prepare = policy.evaluate(RouteDecision("message.prepare", "message", "message", "communication", "prepare_message"))
        send = policy.evaluate(RouteDecision("message.send", "message", "message", "communication", "send_message"))
        propose_patch = policy.evaluate(RouteDecision("code_edit.propose", "code_edit", "code_edit", "developer", "propose_patch"))
        apply_patch = policy.evaluate(RouteDecision("code_edit.apply", "code_edit", "code_edit", "developer", "apply_patch"))

        self.assertEqual(prepare.safety_level, "LOW")
        self.assertFalse(prepare.requires_confirmation)
        self.assertFalse(prepare.requires_voice_permission)
        self.assertTrue(send.requires_voice_permission)
        self.assertEqual(propose_patch.safety_level, "MEDIUM")
        self.assertFalse(propose_patch.requires_voice_permission)
        self.assertEqual(apply_patch.safety_level, "CRITICAL")
        self.assertTrue(apply_patch.requires_voice_permission)

    def test_tool_result_normalization_adds_required_contract_fields(self):
        dict_result = normalize_tool_result({"success": True, "message": "ok"}, default_action="demo")
        object_result = normalize_tool_result(
            ToolResult(
                True,
                "done",
                tool_name="demo_tool",
                data={"action": "object_demo", "value": 1},
                safety_level="MEDIUM",
                requires_confirmation=True,
                requires_voice_permission=True,
            )
        )

        for result in (dict_result, object_result):
            with self.subTest(action=result["action"]):
                self.assertIn("success", result)
                self.assertIn("action", result)
                self.assertIn("message", result)
                self.assertIn("error", result)
                self.assertIn("data", result)
                self.assertIn("safety_level", result)
                self.assertIn("requires_confirmation", result)
                self.assertIn("requires_voice_permission", result)
        self.assertEqual(dict_result["action"], "demo")
        self.assertIsNone(dict_result["error"])
        self.assertEqual(object_result["action"], "object_demo")
        self.assertEqual(object_result["value"], 1)

    def test_tool_executor_can_encounter_metadata_tool_without_crashing(self):
        registry = build_readiness_tool_registry()
        executor = ToolExecutor(registry=registry, enforce_policy=True)
        plan = ActionPlan(
            "read clipboard",
            [
                ActionStep("step1", "clipboard", "clipboard", "read", {}),
            ],
            is_multistep=True,
        )

        result = executor.execute(plan, ToolContext(command="read clipboard"))

        self.assertFalse(result["success"])
        self.assertEqual(result["action"], "tool_unavailable")
        self.assertEqual(result["failed_tool_name"], "clipboard")
        self.assertIn("not available", result["message"].lower())
        self.assertEqual(result["step_results"], [])

    def test_tool_executor_preserves_previous_results_before_metadata_tool_failure(self):
        class FakeApp:
            name = "app"

            def can_handle(self, intent):
                return True

            def execute(self, context, **kwargs):
                return {"success": True, "action": "open", "message": "Opening notepad."}

        registry = build_readiness_tool_registry([FakeApp()])
        executor = ToolExecutor(registry=registry, enforce_policy=True)
        plan = ActionPlan(
            "open notepad and read clipboard",
            [
                ActionStep("step1", "app", "app_open", "open", {"app": "notepad"}),
                ActionStep("step2", "clipboard", "clipboard", "read", {}, depends_on=["step1"]),
            ],
            is_multistep=True,
        )

        result = executor.execute(plan, ToolContext(command="open notepad and read clipboard"))

        self.assertFalse(result["success"])
        self.assertTrue(result["partial_success"])
        self.assertEqual(result["action"], "tool_unavailable")
        self.assertIn("not available", result["message"].lower())
        self.assertEqual(len(result["step_results"]), 1)
        self.assertEqual(result["step_results"][0]["action"], "open")

    def test_task_planner_first_five_patterns_remain_supported(self):
        planner = TaskPlanner()
        commands = [
            "create a file on my desktop named test_jarvis and write hello world",
            "create a folder on my desktop named demo_folder",
            "open chrome and search for python docs",
            "open notepad and type hello",
            "read file notes.txt and summarize it",
        ]

        for command in commands:
            with self.subTest(command=command):
                self.assertTrue(planner.plan(command).is_multistep)


if __name__ == "__main__":
    unittest.main()
