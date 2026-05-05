import sqlite3
import unittest
from pathlib import Path

from app.orchestrator.action_plan import ActionPlan, ActionStep
from app.orchestrator.tool_executor import ToolExecutor
from app.orchestrator.tool_registry import ToolRegistry
from app.state.runtime_state import RuntimeStateStore
from app.tools.base import ToolContext
from app.tools.tool_inventory import build_readiness_tool_registry


class FakeTool:
    def __init__(self, name="app"):
        self.name = name
        self.calls = 0

    def can_handle(self, intent):
        return True

    def execute(self, context):
        self.calls += 1
        return {"success": True, "action": "open", "message": "Opened."}


class CoreExecutorEnforcementTests(unittest.TestCase):
    def setUp(self):
        self.db_path = Path("tests/_tmp") / f"core_executor_state_{self._testMethodName}.sqlite3"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if self.db_path.exists():
            self.db_path.unlink()
        self.store = RuntimeStateStore(self.db_path)

    def _executor(self, registry):
        return ToolExecutor(registry=registry, enforce_policy=True, audit_store=self.store)

    def test_rejects_missing_metadata_without_tool_call(self):
        tool = FakeTool("app")
        registry = ToolRegistry([tool])
        registry._metadata.pop("app")
        result = self._executor(registry).execute(
            ActionPlan("open notepad", [ActionStep("step1", "app", "app_open", "open", {})]),
            ToolContext(command="open notepad", session_id="s1", request_id="t1"),
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["action"], "tool_metadata_missing")
        self.assertEqual(tool.calls, 0)

    def test_rejects_planned_and_disabled_tools_before_execute(self):
        registry = build_readiness_tool_registry()

        planned = self._executor(registry).execute(
            ActionPlan("run command", [ActionStep("step1", "terminal", "terminal", "run_command", {})]),
            ToolContext(command="run command", session_id="s1", request_id="t2"),
        )
        disabled = self._executor(registry).execute(
            ActionPlan("verify voice", [ActionStep("step1", "voice_identity", "voice_identity", "verify", {})]),
            ToolContext(command="verify voice", session_id="s1", request_id="t3"),
        )

        self.assertEqual(planned["action"], "tool_unavailable")
        self.assertEqual(disabled["action"], "tool_unavailable")

    def test_confirmation_required_does_not_execute(self):
        tool = FakeTool("file")
        result = self._executor(ToolRegistry([tool])).execute(
            ActionPlan("write file", [ActionStep("step1", "file", "file", "write_file", {"path": "a.txt"})]),
            ToolContext(command="write file", session_id="s1", request_id="t4"),
        )

        self.assertEqual(result["action"], "confirmation_required")
        self.assertEqual(tool.calls, 0)

    def test_allowed_live_tool_executes_and_records_audit(self):
        tool = FakeTool("app")
        result = self._executor(ToolRegistry([tool])).execute(
            ActionPlan("open notepad", [ActionStep("step1", "app", "app_open", "open", {"app": "notepad"})]),
            ToolContext(command="open notepad", session_id="s1", request_id="t5"),
        )

        self.assertTrue(result["success"])
        self.assertEqual(tool.calls, 1)
        self.assertIsNotNone(result.get("audit_id"))
        with sqlite3.connect(self.db_path) as connection:
            audit_count = connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
        self.assertGreaterEqual(audit_count, 1)


if __name__ == "__main__":
    unittest.main()
