import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from app.orchestrator.automation_context import AutomationContext
from app.orchestrator.main_orchestrator import MainOrchestrator
from app.orchestrator.semantic_planner_adapter import SemanticPlannerAdapter
from app.orchestrator.tool_registry import ToolRegistry
from app.services import automation_service as automation_module
from app.services.automation_service import AutomationService
from app.tools.base import ToolContext
from app.tools.file_tool import FileTool


class _FakeTool:
    def __init__(self, name="file"):
        self.name = name
        self.calls = []

    def can_handle(self, intent):
        return True

    def execute(self, context, **kwargs):
        self.calls.append(context)
        return {"success": True, "action": "danger", "message": "should not run"}


def _semantic_orchestrator(registry):
    return MainOrchestrator(
        registry=registry,
        semantic_adapter=SemanticPlannerAdapter(
            smart_automation_enabled=True,
            semantic_planner_enabled=True,
            safe_execution_enabled=True,
        ),
        enforce_policy=True,
    )


class SemanticConfirmationFlowTests(unittest.TestCase):
    def test_risky_delete_creates_pending_confirmation_and_does_not_execute(self):
        context = AutomationContext(session_id="s1", last_created_file_path=r"C:\Users\Moksh\Desktop\meeting note.txt")
        tool = _FakeTool("file")

        result = _semantic_orchestrator(ToolRegistry([tool])).execute(ToolContext(command="delete it", payload={"automation_context": context}))

        self.assertFalse(result["success"])
        self.assertEqual(result["action"], "semantic_confirmation_required")
        self.assertIn("Should I delete it?", result["message"])
        self.assertIsNotNone(context.last_confirmation_request)
        self.assertEqual(context.last_confirmation_request.action, "delete_file")
        self.assertEqual(len(tool.calls), 0)

    def test_yes_accepts_risky_confirmation_but_execution_stays_disabled(self):
        context = AutomationContext(session_id="s1", last_created_file_path="meeting note.txt")
        tool = _FakeTool("file")
        orchestrator = _semantic_orchestrator(ToolRegistry([tool]))

        orchestrator.execute(ToolContext(command="delete it", payload={"automation_context": context}))
        accepted = orchestrator.execute(ToolContext(command="yes", payload={"automation_context": context}))

        self.assertFalse(accepted["success"])
        self.assertEqual(accepted["action"], "semantic_confirmation_accepted_disabled")
        self.assertIn("deleting files is not enabled", accepted["message"])
        self.assertIsNone(context.last_confirmation_request)
        self.assertEqual(len(tool.calls), 0)

    def test_no_cancels_active_confirmation_and_repeated_yes_is_harmless(self):
        context = AutomationContext(session_id="s1", last_created_file_path="meeting note.txt")
        orchestrator = _semantic_orchestrator(ToolRegistry([_FakeTool("file")]))

        orchestrator.execute(ToolContext(command="delete it", payload={"automation_context": context}))
        cancelled = orchestrator.execute(ToolContext(command="no", payload={"automation_context": context}))
        repeated = orchestrator.execute(ToolContext(command="yes", payload={"automation_context": context}))

        self.assertEqual(cancelled["message"], "Cancelled. I did not delete it.")
        self.assertEqual(repeated["action"], "semantic_confirmation_none")
        self.assertEqual(repeated["message"], "Nothing is waiting for confirmation.")

    def test_expired_confirmation_cannot_execute(self):
        context = AutomationContext(session_id="s1")
        context.set_pending_confirmation(semantic_action="DELETE_FILE", action="delete_file", target="note.txt", ttl_seconds=-1)

        result = _semantic_orchestrator(ToolRegistry([_FakeTool("file")])).execute(ToolContext(command="yes", payload={"automation_context": context}))

        self.assertEqual(result["action"], "semantic_confirmation_expired")
        self.assertIn("expired", result["message"])
        self.assertIsNone(context.last_confirmation_request)

    def test_draft_message_update_recipient_and_content_then_send_is_disabled(self):
        context = AutomationContext(session_id="s1")
        orchestrator = _semantic_orchestrator(ToolRegistry([_FakeTool("message")]))

        draft = orchestrator.execute(ToolContext(command="send this to Rahul: I'll be late", payload={"automation_context": context}))
        recipient = orchestrator.execute(ToolContext(command="Change Rahul to Amit", payload={"automation_context": context}))
        content = orchestrator.execute(ToolContext(command="Change the message to I'll be there soon", payload={"automation_context": context}))
        send = orchestrator.execute(ToolContext(command="Now send it", payload={"automation_context": context}))

        self.assertEqual(draft["action"], "semantic_confirmation_required")
        self.assertEqual(recipient["message"], "I changed the recipient to Amit. Should I send it?")
        self.assertEqual(content["message"], "I changed the message. Should I send it?")
        self.assertFalse(send["success"])
        self.assertIn("actual sending is not enabled", send["message"])

    def test_ambiguous_delete_other_file_asks_short_followup_and_executes_nothing(self):
        context = AutomationContext(session_id="s1", last_created_file_path="meeting note.txt")
        tool = _FakeTool("file")
        orchestrator = _semantic_orchestrator(ToolRegistry([tool]))

        orchestrator.execute(ToolContext(command="delete it", payload={"automation_context": context}))
        result = orchestrator.execute(ToolContext(command="No, delete the other one", payload={"automation_context": context}))

        self.assertEqual(result["message"], "Which file should I delete?")
        self.assertIsNone(context.last_confirmation_request)
        self.assertEqual(len(tool.calls), 0)

    def test_duplicate_safe_append_requires_confirmation_and_yes_repeats_once(self):
        root = Path(__file__).resolve().parent / "_tmp" / "semantic_duplicate_confirm"
        if root.exists():
            shutil.rmtree(root)
        desktop = root / "Desktop"
        desktop.mkdir(parents=True)
        target = desktop / "todo.txt"
        target.write_text("", encoding="utf-8")
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
                orchestrator = _semantic_orchestrator(ToolRegistry([FileTool(AutomationService())]))

                first = orchestrator.execute(ToolContext(command="put milk in it", payload={"automation_context": context}))
                duplicate = orchestrator.execute(ToolContext(command="put milk in it", payload={"automation_context": context}))
                accepted = orchestrator.execute(ToolContext(command="yes", payload={"automation_context": context}))
                repeated_yes = orchestrator.execute(ToolContext(command="yes", payload={"automation_context": context}))

                self.assertTrue(first["success"])
                self.assertEqual(duplicate["action"], "duplicate_semantic_action")
                self.assertTrue(accepted["success"])
                self.assertEqual(target.read_text(encoding="utf-8"), "milkmilk")
                self.assertEqual(repeated_yes["action"], "semantic_confirmation_none")
        finally:
            if root.exists():
                shutil.rmtree(root)

    def test_duplicate_no_cancels_without_repeat(self):
        context = AutomationContext(session_id="s1")
        confirmation = context.set_pending_confirmation(
            semantic_action="APPEND_FILE",
            action="duplicate_repeat",
            target="todo.txt",
            content="milk",
            tool_plan={"kind": "duplicate_repeat"},
        )

        result = _semantic_orchestrator(ToolRegistry([_FakeTool("file")])).execute(ToolContext(command="no", payload={"automation_context": context}))

        self.assertEqual(result["action"], "duplicate_confirmation_cancelled")
        self.assertEqual(confirmation.status, "cancelled")

    def test_high_risk_terminal_and_coordinate_click_remain_disabled(self):
        for command, expected in (
            ("run terminal command dir", "terminal commands"),
            ("click coordinates 10 20", "clicking there"),
            ("shutdown laptop", "power actions"),
        ):
            with self.subTest(command=command):
                context = AutomationContext(session_id="s1")
                tool = _FakeTool("app_interaction")
                orchestrator = _semantic_orchestrator(ToolRegistry([tool]))

                staged = orchestrator.execute(ToolContext(command=command, payload={"automation_context": context}))
                accepted = orchestrator.execute(ToolContext(command="yes", payload={"automation_context": context}))

                self.assertEqual(staged["action"], "semantic_confirmation_required")
                self.assertIn(expected, accepted["message"])
                self.assertEqual(len(tool.calls), 0)


if __name__ == "__main__":
    unittest.main()
