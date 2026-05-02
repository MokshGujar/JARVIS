import shutil
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.orchestrator.action_plan import ActionPlan, ActionStep
from app.orchestrator.tool_executor import ToolExecutor
from app.orchestrator.tool_registry import ToolRegistry
from app.services import automation_service as automation_module
from app.services.automation_service import AutomationService
from app.tools.base import ToolContext, ToolResult
from app.tools.file_tool import FileTool


class FakeTool:
    def __init__(self, name, handler):
        self.name = name
        self.handler = handler
        self.calls = []

    def can_handle(self, intent):
        return True

    def execute(self, context, **kwargs):
        self.calls.append(context)
        return self.handler(context)


class ToolExecutorMultistepTests(unittest.TestCase):
    def test_tool_executor_executes_fake_tools_in_order(self):
        calls = []
        tool = FakeTool("fake", lambda context: calls.append(context.payload["action"]) or {"success": True, "action": context.payload["action"], "message": "ok"})
        executor = ToolExecutor(registry=ToolRegistry([tool]), enforce_policy=True)
        plan = ActionPlan(
            "do things",
            [
                ActionStep("step1", "fake", "fake", "first"),
                ActionStep("step2", "fake", "fake", "second", depends_on=["step1"]),
            ],
            is_multistep=True,
        )

        result = executor.execute(plan, ToolContext(command="do things"))

        self.assertTrue(result["success"])
        self.assertEqual(calls, ["first", "second"])
        self.assertEqual([item["step_id"] for item in result["step_results"]], ["step1", "step2"])

    def test_tool_executor_passes_step_output_into_later_step(self):
        def handler(context):
            if context.payload["action"] == "make_path":
                return {"success": True, "action": "make_path", "message": "path", "path": "C:/tmp/demo.txt"}
            return {
                "success": True,
                "action": "use_path",
                "message": "used",
                "received": context.payload["args"]["path"],
            }

        tool = FakeTool("fake", handler)
        executor = ToolExecutor(registry=ToolRegistry([tool]), enforce_policy=True)
        plan = ActionPlan(
            "use path",
            [
                ActionStep("step1", "fake", "fake", "make_path"),
                ActionStep("step2", "fake", "fake", "use_path", {"path": "{step1.path}"}, depends_on=["step1"]),
            ],
            is_multistep=True,
        )

        result = executor.execute(plan, ToolContext(command="use path"))

        self.assertTrue(result["success"])
        self.assertEqual(result["step_results"][1]["resolved_args"]["path"], "C:/tmp/demo.txt")
        self.assertEqual(result["step_results"][1]["received"], "C:/tmp/demo.txt")

    def test_tool_executor_resolves_placeholders_from_tool_result_data(self):
        def handler(context):
            if context.payload["action"] == "first":
                return ToolResult(True, "ok", data={"path": "C:/tmp/from-data.txt"}, tool_name="fake")
            return {"success": True, "action": "second", "message": context.payload["args"]["path"]}

        tool = FakeTool("fake", handler)
        executor = ToolExecutor(registry=ToolRegistry([tool]), enforce_policy=True)
        plan = ActionPlan(
            "resolve",
            [
                ActionStep("step1", "fake", "fake", "first"),
                ActionStep("step2", "fake", "fake", "second", {"path": "{step1.path}"}, depends_on=["step1"]),
            ],
            is_multistep=True,
        )

        result = executor.execute(plan, ToolContext(command="resolve"))

        self.assertTrue(result["success"])
        self.assertEqual(result["step_results"][1]["message"], "C:/tmp/from-data.txt")

    def test_tool_executor_stops_if_dependency_fails(self):
        def handler(context):
            if context.payload["action"] == "first":
                return {"success": False, "action": "first", "message": "failed"}
            return {"success": True, "action": "second", "message": "should not run"}

        tool = FakeTool("fake", handler)
        executor = ToolExecutor(registry=ToolRegistry([tool]), enforce_policy=True)
        plan = ActionPlan(
            "fail",
            [
                ActionStep("step1", "fake", "fake", "first"),
                ActionStep("step2", "fake", "fake", "second", depends_on=["step1"]),
            ],
            is_multistep=True,
        )

        result = executor.execute(plan, ToolContext(command="fail"))

        self.assertFalse(result["success"])
        self.assertEqual(result["action"], "first")
        self.assertEqual(len(tool.calls), 1)

    def test_tool_executor_returns_partial_success_when_later_tool_is_missing(self):
        tool = FakeTool("app", lambda context: {"success": True, "action": "open", "message": "Opening notepad."})
        executor = ToolExecutor(registry=ToolRegistry([tool]), enforce_policy=True)
        plan = ActionPlan(
            "open notepad and type hello",
            [
                ActionStep("step1", "app", "app_open", "open", {"app": "notepad"}),
                ActionStep("step2", "app_interaction", "type_text", "type_text", {"text": "hello"}, depends_on=["step1"]),
            ],
            is_multistep=True,
        )

        result = executor.execute(plan, ToolContext(command="open notepad and type hello"))

        self.assertFalse(result["success"])
        self.assertTrue(result["partial_success"])
        self.assertEqual(result["action"], "tool_not_found")
        self.assertEqual(result["missing_tool"], "app_interaction")
        self.assertEqual(len(result["step_results"]), 1)

    def test_tool_executor_uses_strict_tool_name_lookup_without_intent_fallback(self):
        tool = FakeTool("file", lambda context: {"success": True, "action": "read_file", "message": "should not run"})
        executor = ToolExecutor(registry=ToolRegistry([tool]), enforce_policy=True)
        plan = ActionPlan(
            "bad tool name",
            [ActionStep("step1", "FileTool", "file", "read_file", {"path_or_name": "notes.txt"})],
            is_multistep=True,
        )

        result = executor.execute(plan, ToolContext(command="bad tool name"))

        self.assertFalse(result["success"])
        self.assertEqual(result["action"], "tool_not_found")
        self.assertEqual(len(tool.calls), 0)

    def test_tool_executor_blocks_high_step_without_confirmation(self):
        tool = FakeTool("app", lambda context: {"success": True, "action": "close", "message": "closed"})
        executor = ToolExecutor(registry=ToolRegistry([tool]), enforce_policy=True)
        plan = ActionPlan("close notepad", [ActionStep("step1", "app", "app_close", "close")], is_multistep=True)

        result = executor.execute(plan, ToolContext(command="close notepad"))

        self.assertFalse(result["success"])
        self.assertEqual(result["action"], "confirmation_required")
        self.assertEqual(len(tool.calls), 0)

    def test_tool_executor_blocks_critical_step_without_confirmation(self):
        tool = FakeTool("file", lambda context: {"success": True, "action": "delete_file", "message": "deleted"})
        executor = ToolExecutor(registry=ToolRegistry([tool]), enforce_policy=True)
        plan = ActionPlan("delete file notes.txt", [ActionStep("step1", "file", "file", "delete_file")], is_multistep=True)

        result = executor.execute(plan, ToolContext(command="delete file notes.txt"))

        self.assertFalse(result["success"])
        self.assertEqual(result["action"], "confirmation_required")
        self.assertFalse(result["requires_face_step_up"])
        self.assertTrue(result["requires_voice_permission"])
        self.assertEqual(len(tool.calls), 0)

    def test_tool_executor_blocks_critical_step_without_voice_permission(self):
        tool = FakeTool("file", lambda context: {"success": True, "action": "delete_file", "message": "deleted"})
        executor = ToolExecutor(registry=ToolRegistry([tool]), enforce_policy=True)
        plan = ActionPlan("delete file notes.txt", [ActionStep("step1", "file", "file", "delete_file")], is_multistep=True)

        result = executor.execute(plan, ToolContext(command="delete file notes.txt", confirmation_state={"confirmed": True}))

        self.assertFalse(result["success"])
        self.assertEqual(result["action"], "auth_required")
        self.assertFalse(result["requires_face_step_up"])
        self.assertTrue(result["requires_voice_permission"])
        self.assertTrue(result["auth"]["voice_permission_required"])
        self.assertEqual(len(tool.calls), 0)

    def test_tool_executor_allows_protected_step_with_voice_permission(self):
        tool = FakeTool("file", lambda context: {"success": True, "action": "delete_file", "message": "deleted"})
        executor = ToolExecutor(registry=ToolRegistry([tool]), enforce_policy=True)
        plan = ActionPlan("delete file notes.txt", [ActionStep("step1", "file", "file", "delete_file")], is_multistep=True)

        result = executor.execute(
            plan,
            ToolContext(
                command="delete file notes.txt",
                confirmation_state={"confirmed": True},
                security_state={"voice_permission_granted": True},
            ),
        )

        self.assertTrue(result["success"])
        self.assertEqual(len(tool.calls), 1)

    def test_file_tool_create_write_flow_uses_temp_desktop(self):
        root = Path(__file__).resolve().parent / "_tmp" / "tool_executor_file_flow"
        if root.exists():
            shutil.rmtree(root)
        desktop = root / "Desktop"
        documents = root / "Documents"
        downloads = root / "Downloads"
        for folder in (desktop, documents, downloads):
            folder.mkdir(parents=True)

        with (
            patch.object(automation_module, "BASE_DIR", root),
            patch.object(
                AutomationService,
                "USER_PATH_ALIASES",
                {
                    "desktop": desktop,
                    "documents": documents,
                    "downloads": downloads,
                    "home": root,
                    "music": root / "Music",
                    "pictures": root / "Pictures",
                    "videos": root / "Videos",
                },
            ),
        ):
            service = AutomationService()
            executor = ToolExecutor(registry=ToolRegistry([FileTool(service)]), enforce_policy=True)
            plan = ActionPlan(
                "create file",
                [
                    ActionStep("step1", "file", "file", "resolve_path", {"location": "desktop"}),
                    ActionStep("step2", "file", "file", "create_file", {"parent": "{step1.path}", "filename": "test_jarvis.txt"}, depends_on=["step1"]),
                    ActionStep(
                        "step3",
                        "file",
                        "file",
                        "write_file",
                        {"path": "{step2.path}", "content": "hello world", "overwrite": False},
                        depends_on=["step2"],
                    ),
                    ActionStep(
                        "step4",
                        "file",
                        "file",
                        "verify_exists",
                        {"path": "{step2.path}", "expected_content": "hello world"},
                        depends_on=["step2", "step3"],
                    ),
                ],
                is_multistep=True,
            )

            result = executor.execute(plan, ToolContext(command="create file"))

            self.assertTrue(result["success"])
            self.assertEqual((desktop / "test_jarvis.txt").read_text(encoding="utf-8"), "hello world")
        if root.exists():
            shutil.rmtree(root)

    def test_file_tool_create_file_refuses_existing_file_and_write_refuses_non_empty_without_overwrite(self):
        root = Path(__file__).resolve().parent / "_tmp" / "tool_executor_refuse_overwrite"
        if root.exists():
            shutil.rmtree(root)
        desktop = root / "Desktop"
        desktop.mkdir(parents=True)
        existing = desktop / "notes.txt"
        existing.write_text("old", encoding="utf-8")

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
            service = AutomationService()
            tool = FileTool(service)
            create_result = tool.execute(
                ToolContext(command="planned", intent="file", payload={"action": "create_file", "args": {"parent": str(desktop), "filename": "notes.txt"}})
            )
            write_result = tool.execute(
                ToolContext(
                    command="planned",
                    intent="file",
                    payload={"action": "write_file", "args": {"path": str(existing), "content": "new", "overwrite": False}},
                )
            )

            self.assertFalse(create_result["success"])
            self.assertFalse(write_result["success"])
            self.assertEqual(existing.read_text(encoding="utf-8"), "old")
        if root.exists():
            shutil.rmtree(root)

    def test_automation_service_multistep_file_request_uses_tmp_desktop(self):
        root = Path(__file__).resolve().parent / "_tmp" / "automation_multistep"
        if root.exists():
            shutil.rmtree(root)
        desktop = root / "Desktop"
        documents = root / "Documents"
        downloads = root / "Downloads"
        for folder in (desktop, documents, downloads):
            folder.mkdir(parents=True)

        with (
            patch.object(automation_module, "BASE_DIR", root),
            patch.object(
                AutomationService,
                "USER_PATH_ALIASES",
                {
                    "desktop": desktop,
                    "documents": documents,
                    "downloads": downloads,
                    "home": root,
                    "music": root / "Music",
                    "pictures": root / "Pictures",
                    "videos": root / "Videos",
                },
            ),
        ):
            service = AutomationService()
            result = service.execute("create a file on my desktop named test_jarvis and write hello in it")

            self.assertTrue(result["success"])
            self.assertTrue(result["is_multistep"])
            self.assertEqual(result["scenario"], "task.multistep")
            self.assertEqual((desktop / "test_jarvis.txt").read_text(encoding="utf-8"), "hello")
            self.assertEqual([item["planned_action"] for item in result["step_results"]], ["resolve_path", "create_file", "write_file", "verify_exists"])
        if root.exists():
            shutil.rmtree(root)

    def test_automation_service_multistep_file_request_reports_write_failure(self):
        root = Path(__file__).resolve().parent / "_tmp" / "automation_multistep_write_failure"
        if root.exists():
            shutil.rmtree(root)
        desktop = root / "Desktop"
        desktop.mkdir(parents=True)
        existing = desktop / "test_jarvis.txt"
        existing.write_text("existing", encoding="utf-8")

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
            service = AutomationService()
            result = service.execute("create a file on my desktop named test_jarvis and write hello world")

            self.assertFalse(result["success"])
            self.assertTrue(result["partial_success"])
            self.assertNotEqual(result["action"], "multi_step")
        if root.exists():
            shutil.rmtree(root)


if __name__ == "__main__":
    unittest.main()
