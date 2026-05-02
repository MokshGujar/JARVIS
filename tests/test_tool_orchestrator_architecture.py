import shutil
import unittest
from pathlib import Path
from unittest.mock import Mock

from app.connectors.local_files_connector import LocalFilesConnector
from app.orchestrator.intent_router import IntentRouter
from app.orchestrator.main_orchestrator import MainOrchestrator
from app.orchestrator.scenario_policy import ScenarioPolicy
from app.orchestrator.tool_registry import ToolRegistry
from app.tools.base import ToolContext
from app.tools.app_tool import AppTool
from app.tools.file_tool import FileTool
from app.tools.system_tool import SystemTool


class ToolOrchestratorArchitectureTests(unittest.TestCase):
    def test_orchestrator_tool_registry_lookup_by_name_intent_and_category(self):
        app_tool = AppTool(Mock())
        system_tool = SystemTool(Mock())
        registry = ToolRegistry([app_tool, system_tool])

        self.assertIs(registry.by_name("app"), app_tool)
        self.assertIs(registry.by_intent("app_open"), app_tool)
        self.assertIs(registry.by_intent("volume_change"), system_tool)
        self.assertEqual(registry.by_category("app"), (app_tool,))

    def test_intent_router_maps_major_scenarios_to_tools(self):
        router = IntentRouter()

        cases = {
            "open chrome": "app",
            "browser search python docs": "browser",
            "send WhatsApp message to mom saying hello": "whatsapp",
            "read file notes.txt": "file",
            "delete file notes.txt": "file",
            "volume up": "system",
            "what did I say earlier": "memory",
        }
        for command, tool_name in cases.items():
            with self.subTest(command=command):
                route = router.route(command)
                self.assertIsNotNone(route)
                self.assertEqual(route.tool_name, tool_name)

    def test_scenario_policy_file_safety_levels(self):
        router = IntentRouter()
        policy = ScenarioPolicy()

        read_policy = policy.evaluate(router.route("read file notes.txt"))
        create_policy = policy.evaluate(router.route("create file notes.txt"))
        delete_policy = policy.evaluate(router.route("delete file notes.txt"))

        self.assertEqual(read_policy.safety_level, "LOW")
        self.assertFalse(read_policy.requires_face_step_up)
        self.assertEqual(create_policy.safety_level, "MEDIUM")
        self.assertFalse(create_policy.requires_face_step_up)
        self.assertEqual(delete_policy.safety_level, "CRITICAL")
        self.assertTrue(delete_policy.requires_confirmation)
        self.assertFalse(delete_policy.requires_face_step_up)
        self.assertTrue(delete_policy.requires_voice_permission)

    def test_scenario_policy_app_and_system_safety_levels(self):
        router = IntentRouter()
        policy = ScenarioPolicy()

        open_policy = policy.evaluate(router.route("open notepad"))
        close_policy = policy.evaluate(router.route("close notepad"))
        volume_policy = policy.evaluate(router.route("volume up"))
        lock_policy = policy.evaluate(router.route("lock screen"))
        restart_policy = policy.evaluate(router.route("restart laptop"))

        self.assertEqual(open_policy.safety_level, "LOW")
        self.assertEqual(close_policy.safety_level, "HIGH")
        self.assertTrue(close_policy.requires_confirmation)
        self.assertEqual(volume_policy.safety_level, "LOW")
        self.assertEqual(lock_policy.safety_level, "HIGH")
        self.assertTrue(lock_policy.requires_confirmation)
        self.assertEqual(restart_policy.safety_level, "CRITICAL")
        self.assertFalse(restart_policy.requires_face_step_up)
        self.assertTrue(restart_policy.requires_voice_permission)

    def test_file_tool_groups_operations_and_delegates_to_legacy_bridge(self):
        bridge = Mock()
        bridge._execute_file_command_legacy.return_value = {"success": True, "action": "list_files", "message": "Files in Downloads:"}
        tool = FileTool(bridge)

        self.assertEqual(tool.operation_for("list files in downloads")["group"], "A")
        self.assertEqual(tool.operation_for("read file notes.txt")["group"], "B")
        self.assertEqual(tool.operation_for("create file notes.txt")["group"], "C")
        self.assertEqual(tool.operation_for("rename file a.txt to b.txt")["group"], "D")
        self.assertEqual(tool.operation_for("delete file notes.txt")["group"], "E")

        result = tool.execute(ToolContext(command="list files in downloads", intent="file"))

        self.assertEqual(result["action"], "list_files")
        self.assertEqual(result["tool_name"], "file")
        bridge._execute_file_command_legacy.assert_called_once()

    def test_main_orchestrator_selects_file_tool(self):
        tool = Mock()
        tool.name = "file"
        tool.can_handle.return_value = True
        tool.execute.return_value = {"success": True, "action": "read_file", "message": "notes.txt:\nhello"}
        orchestrator = MainOrchestrator(registry=ToolRegistry([tool]), enforce_policy=False)

        result = orchestrator.execute_text("read file notes.txt", session_id="s1")

        self.assertTrue(result["success"])
        self.assertEqual(result["selected_tool"], "file")
        self.assertEqual(result["scenario"], "file.read")
        tool.execute.assert_called_once()
        self.assertEqual(tool.execute.call_args.args[0].intent, "file")

    def test_main_orchestrator_selects_app_tool(self):
        bridge = Mock()
        bridge._execute_app_launcher_command_legacy.return_value = {"success": True, "action": "open", "message": "Opening notepad."}
        orchestrator = MainOrchestrator(registry=ToolRegistry([AppTool(bridge)]), enforce_policy=False)

        result = orchestrator.execute_text("open notepad")

        self.assertTrue(result["success"])
        self.assertEqual(result["selected_tool"], "app")
        self.assertEqual(result["scenario"], "app.open")
        bridge._execute_app_launcher_command_legacy.assert_called_once()

    def test_main_orchestrator_selects_system_tool(self):
        bridge = Mock()
        bridge._execute_system_command_legacy.return_value = {"success": True, "action": "system", "message": "Done volume up."}
        orchestrator = MainOrchestrator(registry=ToolRegistry([SystemTool(bridge)]), enforce_policy=False)

        result = orchestrator.execute_text("volume up")

        self.assertTrue(result["success"])
        self.assertEqual(result["selected_tool"], "system")
        self.assertEqual(result["scenario"], "system.volume_up")
        bridge._execute_system_command_legacy.assert_called_once()

    def test_main_orchestrator_blocks_delete_without_confirmation_and_then_requires_voice_permission(self):
        tool = Mock()
        tool.name = "file"
        tool.can_handle.return_value = True
        tool.execute.return_value = {"success": True, "action": "delete_file", "message": "Deleted notes.txt."}
        orchestrator = MainOrchestrator(registry=ToolRegistry([tool]), enforce_policy=True)

        needs_confirmation = orchestrator.execute_text("delete file notes.txt")
        needs_step_up = orchestrator.execute(
            ToolContext(command="delete file notes.txt", confirmation_state={"confirmed": True})
        )
        allowed = orchestrator.execute(
            ToolContext(
                command="delete file notes.txt",
                confirmation_state={"confirmed": True},
                security_state={"voice_permission_granted": True},
            )
        )

        self.assertEqual(needs_confirmation["action"], "confirmation_required")
        self.assertFalse(needs_confirmation["requires_face_step_up"])
        self.assertTrue(needs_confirmation["requires_voice_permission"])
        self.assertEqual(needs_step_up["action"], "auth_required")
        self.assertFalse(needs_step_up["requires_face_step_up"])
        self.assertTrue(needs_step_up["auth"]["voice_permission_required"])
        self.assertTrue(allowed["success"])
        self.assertEqual(tool.execute.call_count, 1)

    def test_main_orchestrator_blocks_high_app_close_without_confirmation(self):
        bridge = Mock()
        bridge._execute_app_launcher_command_legacy.return_value = {"success": True, "action": "close", "message": "Closing notepad."}
        orchestrator = MainOrchestrator(registry=ToolRegistry([AppTool(bridge)]), enforce_policy=True)

        blocked = orchestrator.execute_text("close notepad")
        allowed = orchestrator.execute(ToolContext(command="close notepad", confirmation_state={"confirmed": True}))

        self.assertEqual(blocked["action"], "confirmation_required")
        self.assertFalse(blocked["requires_face_step_up"])
        self.assertTrue(allowed["success"])
        self.assertEqual(bridge._execute_app_launcher_command_legacy.call_count, 1)

    def test_main_orchestrator_blocks_critical_restart_without_voice_permission(self):
        bridge = Mock()
        bridge._execute_system_command_legacy.return_value = {"success": True, "action": "system", "message": "Restarting."}
        orchestrator = MainOrchestrator(registry=ToolRegistry([SystemTool(bridge)]), enforce_policy=True)

        blocked = orchestrator.execute(ToolContext(command="restart laptop", confirmation_state={"confirmed": True}))

        self.assertEqual(blocked["action"], "auth_required")
        self.assertFalse(blocked["requires_face_step_up"])
        self.assertTrue(blocked["auth"]["voice_permission_required"])
        bridge._execute_system_command_legacy.assert_not_called()

    def test_local_files_connector_refuses_silent_overwrite(self):
        connector = LocalFilesConnector()
        root = Path(__file__).resolve().parent / "_tmp" / "local_files_connector"
        if root.exists():
            shutil.rmtree(root)
        root.mkdir(parents=True)
        try:
            target = root / "notes.txt"
            target.write_text("old", encoding="utf-8")

            with self.assertRaises(FileExistsError):
                connector.write_text(target, "new")

            self.assertEqual(target.read_text(encoding="utf-8"), "old")
        finally:
            if root.exists():
                shutil.rmtree(root)


if __name__ == "__main__":
    unittest.main()
