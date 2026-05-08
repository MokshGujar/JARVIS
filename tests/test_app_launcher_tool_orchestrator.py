import unittest
from unittest.mock import Mock, patch

from app.orchestrator.intent_router import IntentRouter
from app.orchestrator.main_orchestrator import MainOrchestrator
from app.orchestrator.scenario_policy import ScenarioPolicy
from app.orchestrator.tool_registry import ToolRegistry
from app.tools.app_launcher_tool import AppLauncherTool
from app.tools.app_tool import AppTool
from app.tools.base import ToolContext


class AppLauncherToolOrchestratorTests(unittest.TestCase):
    def test_registry_registers_app_and_app_launcher_tools(self):
        app = AppTool(Mock())
        launcher = AppLauncherTool(Mock())
        registry = ToolRegistry([app, launcher])

        self.assertIs(registry.by_name("app"), app)
        self.assertIs(registry.by_name("app_launcher"), launcher)
        self.assertIs(registry.by_intent("app_open"), app)
        self.assertEqual(registry.by_category("app"), (app, launcher))

    def test_intent_router_maps_app_commands(self):
        router = IntentRouter()

        cases = {
            "open chrome": ("app_open", "open"),
            "launch notepad": ("app_open", "open"),
            "focus chrome": ("app_focus", "focus"),
            "close notepad": ("app_close", "close"),
        }
        for command, expected in cases.items():
            with self.subTest(command=command):
                route = router.route(command)
                self.assertIsNotNone(route)
                self.assertEqual(route.tool_name, "app")
                self.assertEqual((route.intent, route.operation), expected)

    def test_app_policy_open_low_close_high(self):
        router = IntentRouter()
        policy = ScenarioPolicy()

        open_policy = policy.evaluate(router.route("open chrome"))
        close_policy = policy.evaluate(router.route("close notepad"))

        self.assertEqual(open_policy.safety_level, "LOW")
        self.assertFalse(open_policy.requires_confirmation)
        self.assertEqual(close_policy.safety_level, "HIGH")
        self.assertTrue(close_policy.requires_confirmation)

    def test_main_orchestrator_selects_app_tool(self):
        bridge = Mock()
        orchestrator = MainOrchestrator(registry=ToolRegistry([AppTool(bridge), AppLauncherTool(bridge)]), enforce_policy=False)

        with patch("app.tools.compatibility_runners.AppCompatibilityRunner.execute", return_value={"success": True, "action": "open", "message": "Opening chrome."}) as runner:
            result = orchestrator.execute_text("open chrome")

        self.assertTrue(result["success"])
        self.assertEqual(result["selected_tool"], "app")
        self.assertEqual(result["scenario"], "app.open")
        runner.assert_called_once()
        self.assertEqual(runner.call_args.args[0], "open chrome")

    def test_app_launcher_tool_delegates_to_app_compatibility_runner(self):
        bridge = Mock()
        tool = AppLauncherTool(bridge)

        with patch("app.tools.compatibility_runners.AppCompatibilityRunner.execute", return_value={"success": True, "action": "open", "message": "Opening notepad."}) as runner:
            result = tool.execute(ToolContext(command="open notepad", intent="app_open"))

        self.assertTrue(result["success"])
        self.assertEqual(result["tool_name"], "app_launcher")
        runner.assert_called_once()
        self.assertEqual(runner.call_args.args[0], "open notepad")

    def test_app_close_blocked_without_confirmation(self):
        bridge = Mock()
        orchestrator = MainOrchestrator(registry=ToolRegistry([AppTool(bridge)]), enforce_policy=True)

        with patch("app.tools.compatibility_runners.AppCompatibilityRunner.execute", return_value={"success": True, "action": "close", "message": "Closing notepad."}) as runner:
            blocked = orchestrator.execute_text("close notepad")
            allowed = orchestrator.execute(ToolContext(command="close notepad", confirmation_state={"confirmed": True}))

        self.assertEqual(blocked["action"], "confirmation_required")
        self.assertFalse(blocked["requires_face_step_up"])
        self.assertTrue(allowed["success"])
        self.assertEqual(runner.call_count, 1)


if __name__ == "__main__":
    unittest.main()
