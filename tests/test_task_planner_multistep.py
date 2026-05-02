import unittest

from app.orchestrator.task_planner import TaskPlanner
from app.orchestrator.tool_registry import ToolRegistry
from app.tools.app_tool import AppTool
from app.tools.app_interaction_tool import AppInteractionTool
from app.tools.browser_tool import BrowserTool
from app.tools.file_tool import FileTool
from app.tools.summary_tool import SummaryTool
from app.tools.system_tool import SystemTool
from unittest.mock import Mock


class TaskPlannerMultistepTests(unittest.TestCase):
    def setUp(self):
        self.planner = TaskPlanner()

    def test_task_planner_detects_single_step_command(self):
        plan = self.planner.plan("read file notes.txt")

        self.assertFalse(plan.is_multistep)
        self.assertEqual(plan.steps, [])

    def test_task_planner_converts_create_file_and_write_pattern(self):
        plan = self.planner.plan("create a file on my desktop named test_jarvis and write hello world")

        self.assertTrue(plan.is_multistep)
        self.assertEqual([step.action for step in plan.steps], ["resolve_path", "create_file", "write_file", "verify_exists"])
        self.assertEqual([step.tool_name for step in plan.steps], ["file", "file", "file", "file"])
        self.assertEqual(plan.steps[1].args["filename"], "test_jarvis.txt")
        self.assertEqual(plan.steps[2].args["path"], "{step2.path}")
        self.assertEqual(plan.steps[2].args["content"], "hello world")
        self.assertFalse(plan.steps[2].args["overwrite"])
        self.assertEqual(plan.steps[3].depends_on, ["step2", "step3"])
        self.assertEqual(plan.steps[1].safety_level, "MEDIUM")
        self.assertFalse(plan.requires_face_step_up)
        self.assertFalse(plan.requires_voice_permission)

    def test_task_planner_strips_trailing_target_reference_phrases(self):
        cases = {
            "create a file on my desktop named test jarvis and write hello in it": "hello",
            "create a file on my desktop named test jarvis and write hello into it": "hello",
            "create a file on my desktop named test jarvis and put hello in it": "hello",
            "create a file on my desktop named test jarvis and add hello to it": "hello",
            "create a file on my desktop named test jarvis and write hello world in the file": "hello world",
            "create a file on my desktop named test jarvis and write hello world": "hello world",
            "create a file on my desktop named test jarvis and write 'hello in it' in the file": "hello in it",
        }
        for command, expected in cases.items():
            with self.subTest(command=command):
                plan = self.planner.plan(command)
                self.assertEqual(plan.steps[2].args["content"], expected)

    def test_task_planner_converts_create_folder_pattern(self):
        plan = self.planner.plan("create a folder on my desktop named demo_folder")

        self.assertTrue(plan.is_multistep)
        self.assertEqual([step.action for step in plan.steps], ["resolve_path", "create_folder", "verify_exists"])
        self.assertEqual(plan.steps[1].args, {"parent": "{step1.path}", "name": "demo_folder"})
        self.assertEqual(plan.steps[2].depends_on, ["step2"])

    def test_task_planner_converts_open_and_search_pattern(self):
        plan = self.planner.plan("open chrome and search for python docs")

        self.assertTrue(plan.is_multistep)
        self.assertEqual([(step.tool_name, step.action) for step in plan.steps], [("app", "open"), ("browser", "search")])
        self.assertEqual(plan.steps[0].args["app"], "chrome")
        self.assertEqual(plan.steps[1].args["query"], "python docs")
        self.assertEqual(plan.steps[1].depends_on, ["step1"])

    def test_task_planner_converts_open_and_type_pattern_with_intentional_missing_tool(self):
        plan = self.planner.plan("open notepad and type hello")

        self.assertTrue(plan.is_multistep)
        self.assertEqual([(step.tool_name, step.action) for step in plan.steps], [("app", "open"), ("app_interaction", "type_text")])
        self.assertEqual(plan.steps[1].args["text"], "hello")

    def test_task_planner_converts_read_and_summarize_pattern_with_intentional_missing_tool(self):
        plan = self.planner.plan("read file notes.txt and summarize it")

        self.assertTrue(plan.is_multistep)
        self.assertEqual([(step.tool_name, step.action) for step in plan.steps], [("file", "read_file"), ("summary", "summarize")])
        self.assertEqual(plan.steps[1].args["content"], "{step1.content}")

    def test_action_plan_preserves_order_and_computes_plan_safety_flags(self):
        plan = self.planner.plan("create a file on my desktop named test_jarvis and write hello world")

        self.assertEqual([step.step_id for step in plan.steps], ["step1", "step2", "step3", "step4"])
        self.assertFalse(plan.requires_confirmation)
        self.assertFalse(plan.requires_face_step_up)

    def test_executable_tool_names_match_registry_names_and_future_tools_are_explicit(self):
        registry = ToolRegistry([FileTool(Mock()), AppTool(Mock()), AppInteractionTool(adapter=Mock()), BrowserTool(automation_bridge=Mock()), SystemTool(Mock()), SummaryTool(Mock())])
        executable_names = set(registry.keys())
        intentionally_missing = set()

        commands = [
            "create a file on my desktop named test_jarvis and write hello world",
            "create a folder on my desktop named demo_folder",
            "open chrome and search for python docs",
            "open notepad and type hello",
            "read file notes.txt and summarize it",
        ]
        for command in commands:
            with self.subTest(command=command):
                plan = self.planner.plan(command)
                for step in plan.steps:
                    self.assertIn(step.tool_name, executable_names | intentionally_missing)

    def test_pattern_roadmap_document_exists_with_required_groups(self):
        roadmap = __import__("pathlib").Path("reports/task_planner_pattern_roadmap.md")

        self.assertTrue(roadmap.exists())
        text = roadmap.read_text(encoding="utf-8")
        for heading in (
            "File",
            "App/Window",
            "Browser",
            "System",
            "WhatsApp/Message",
            "Voice/Audio",
            "Memory/Reminder",
            "Research/Summary",
            "Contact/Phone",
            "Clipboard/Keyboard/Mouse",
            "Vision/Screen",
            "Device/Network",
            "Developer/Project",
        ):
            with self.subTest(heading=heading):
                self.assertIn(f"## {heading}", text)


if __name__ == "__main__":
    unittest.main()
