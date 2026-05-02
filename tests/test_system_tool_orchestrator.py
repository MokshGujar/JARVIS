import unittest
from unittest.mock import Mock

from app.orchestrator.intent_router import IntentRouter
from app.orchestrator.main_orchestrator import MainOrchestrator
from app.orchestrator.scenario_policy import ScenarioPolicy
from app.orchestrator.tool_registry import ToolRegistry
from app.services.automation_service import AutomationService
from app.tools.base import ToolContext
from app.tools.system_tool import SystemTool


class SystemToolOrchestratorTests(unittest.TestCase):
    def test_default_automation_registry_registers_system_tool(self):
        service = AutomationService()
        registry = service._build_automation_tool_registry()

        system_tool = registry.by_name("system")

        self.assertIsInstance(system_tool, SystemTool)
        self.assertIs(registry.by_intent("volume_up"), system_tool)
        self.assertIs(registry.by_intent("shutdown_system"), system_tool)

    def test_intent_router_maps_system_commands_to_system_tool(self):
        router = IntentRouter()
        cases = {
            "increase volume": "volume_up",
            "decrease volume": "volume_down",
            "mute volume": "mute_volume",
            "take screenshot": "screenshot",
            "lock my laptop": "lock_system",
            "shutdown laptop": "shutdown_system",
            "restart laptop": "restart_system",
            "system info": "safe_system_info",
        }

        for command, operation in cases.items():
            with self.subTest(command=command):
                route = router.route(command)
                self.assertIsNotNone(route)
                self.assertEqual(route.tool_name, "system")
                self.assertEqual(route.category, "system")
                self.assertEqual(route.operation, operation)

    def test_scenario_policy_gates_system_power_actions(self):
        router = IntentRouter()
        policy = ScenarioPolicy()

        volume_policy = policy.evaluate(router.route("increase volume"))
        screenshot_policy = policy.evaluate(router.route("take screenshot"))
        lock_policy = policy.evaluate(router.route("lock my laptop"))
        shutdown_policy = policy.evaluate(router.route("shutdown laptop"))
        restart_policy = policy.evaluate(router.route("restart laptop"))

        self.assertEqual(volume_policy.safety_level, "LOW")
        self.assertFalse(volume_policy.requires_confirmation)
        self.assertEqual(screenshot_policy.safety_level, "LOW")
        self.assertEqual(lock_policy.safety_level, "HIGH")
        self.assertTrue(lock_policy.requires_confirmation)
        self.assertFalse(lock_policy.requires_face_step_up)
        self.assertEqual(shutdown_policy.safety_level, "CRITICAL")
        self.assertTrue(shutdown_policy.requires_confirmation)
        self.assertFalse(shutdown_policy.requires_face_step_up)
        self.assertTrue(shutdown_policy.requires_voice_permission)
        self.assertEqual(restart_policy.safety_level, "CRITICAL")
        self.assertTrue(restart_policy.requires_confirmation)
        self.assertFalse(restart_policy.requires_face_step_up)
        self.assertTrue(restart_policy.requires_voice_permission)

    def test_system_tool_delegates_to_legacy_system_bridge(self):
        bridge = Mock()
        bridge._execute_system_command_legacy.return_value = {
            "success": True,
            "action": "system",
            "message": "Done volume up.",
        }
        tool = SystemTool(bridge)

        result = tool.execute(ToolContext(command="volume up", intent="volume_up"))

        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "system")
        bridge._execute_system_command_legacy.assert_called_once_with("volume up")

    def test_main_orchestrator_selects_system_tool_and_allows_low_actions(self):
        bridge = Mock()
        bridge._execute_system_command_legacy.return_value = {
            "success": True,
            "action": "computer_control",
            "message": "Screenshot saved",
        }
        orchestrator = MainOrchestrator(registry=ToolRegistry([SystemTool(bridge)]), enforce_policy=True)

        result = orchestrator.execute_text("take screenshot")

        self.assertTrue(result["success"])
        self.assertEqual(result["selected_tool"], "system")
        self.assertEqual(result["scenario"], "system.screenshot")
        self.assertEqual(result["policy"]["safety_level"], "LOW")
        bridge._execute_system_command_legacy.assert_called_once_with("take screenshot")

    def test_lock_system_is_blocked_without_confirmation(self):
        bridge = Mock()
        bridge._execute_system_command_legacy.return_value = {
            "success": True,
            "action": "computer_settings",
            "message": "Locked the screen.",
        }
        orchestrator = MainOrchestrator(registry=ToolRegistry([SystemTool(bridge)]), enforce_policy=True)

        blocked = orchestrator.execute_text("lock my laptop")
        allowed = orchestrator.execute(ToolContext(command="lock my laptop", confirmation_state={"confirmed": True}))

        self.assertEqual(blocked["action"], "confirmation_required")
        self.assertFalse(blocked["requires_face_step_up"])
        self.assertTrue(allowed["success"])
        bridge._execute_system_command_legacy.assert_called_once_with("lock my laptop")

    def test_shutdown_system_requires_confirmation_and_voice_permission(self):
        bridge = Mock()
        bridge._execute_system_command_legacy.return_value = {
            "success": True,
            "action": "computer_settings",
            "message": "Shutting down.",
        }
        orchestrator = MainOrchestrator(registry=ToolRegistry([SystemTool(bridge)]), enforce_policy=True)

        needs_confirmation = orchestrator.execute_text("shutdown laptop")
        needs_voice_permission = orchestrator.execute(ToolContext(command="shutdown laptop", confirmation_state={"confirmed": True}))
        allowed = orchestrator.execute(
            ToolContext(
                command="shutdown laptop",
                confirmation_state={"confirmed": True},
                security_state={"voice_permission_granted": True},
            )
        )

        self.assertEqual(needs_confirmation["action"], "confirmation_required")
        self.assertFalse(needs_confirmation["requires_face_step_up"])
        self.assertTrue(needs_confirmation["requires_voice_permission"])
        self.assertEqual(needs_voice_permission["action"], "auth_required")
        self.assertFalse(needs_voice_permission["requires_face_step_up"])
        self.assertTrue(needs_voice_permission["auth"]["voice_permission_required"])
        self.assertTrue(allowed["success"])
        bridge._execute_system_command_legacy.assert_called_once_with("shutdown laptop")

    def test_restart_system_requires_confirmation_and_voice_permission(self):
        bridge = Mock()
        bridge._execute_system_command_legacy.return_value = {
            "success": True,
            "action": "computer_settings",
            "message": "Restarting.",
        }
        orchestrator = MainOrchestrator(registry=ToolRegistry([SystemTool(bridge)]), enforce_policy=True)

        needs_confirmation = orchestrator.execute_text("restart laptop")
        needs_voice_permission = orchestrator.execute(ToolContext(command="restart laptop", confirmation_state={"confirmed": True}))

        self.assertEqual(needs_confirmation["action"], "confirmation_required")
        self.assertFalse(needs_confirmation["requires_face_step_up"])
        self.assertTrue(needs_confirmation["requires_voice_permission"])
        self.assertEqual(needs_voice_permission["action"], "auth_required")
        self.assertFalse(needs_voice_permission["requires_face_step_up"])
        bridge._execute_system_command_legacy.assert_not_called()


if __name__ == "__main__":
    unittest.main()
