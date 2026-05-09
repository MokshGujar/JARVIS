import shutil
from pathlib import Path

from app.orchestrator.action_plan import ActionPlan, ActionStep
from app.orchestrator.tool_executor import ToolExecutor
from app.state.runtime_state import RuntimeStateStore
from app.tools.base import ToolContext
from app.tools.reminder_tool import ReminderTool
from app.tools.tool_inventory import build_readiness_tool_registry, get_tool_inventory, get_tool_inventory_record


class FakeReminderService:
    def __init__(self):
        self.created = []

    def create_reminder(self, command):
        self.created.append(command)
        return {"success": True, "action": "reminder", "message": "Reminder set."}

    def get_due_reminders(self):
        return [{"message": "drink water"}]


ROOT = Path(__file__).resolve().parent / "_tmp" / "tool_promotion"


def runtime_store(name):
    root = ROOT / name
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    return RuntimeStateStore(root / "runtime.sqlite3")


def test_promoted_reminder_tool_routes_through_tool_executor():
    reminder = ReminderTool(FakeReminderService())
    registry = build_readiness_tool_registry([reminder])
    executor = ToolExecutor(registry=registry, audit_store=runtime_store("reminder_create"))
    plan = ActionPlan(
        "remind me to drink water at 6 PM",
        [ActionStep("step1", "reminder", "reminder", "create", {"command": "remind me to drink water at 6 PM"})],
    )

    result = executor.execute(plan, ToolContext(command="remind me to drink water at 6 PM"))

    assert result["success"] is True
    assert result["selected_tool"] == "reminder"
    assert result["policy"]["decision"] == "ALLOW"
    assert reminder.reminder_service.created == ["remind me to drink water at 6 PM"]


def test_partial_reminder_tool_blocks_unpromoted_actions():
    registry = build_readiness_tool_registry([ReminderTool(FakeReminderService())])
    executor = ToolExecutor(registry=registry, audit_store=runtime_store("reminder_cancel"))
    plan = ActionPlan("cancel reminder", [ActionStep("step1", "reminder", "reminder", "cancel", {})])

    result = executor.execute(plan, ToolContext(command="cancel reminder"))

    assert result["success"] is False
    assert result["action"] == "tool_unavailable"
    assert result["failed_tool_name"] == "reminder"


def test_terminal_and_code_tools_remain_proposal_only():
    terminal = get_tool_inventory_record("terminal")
    code_edit = get_tool_inventory_record("code_edit")

    assert terminal.current_status == "metadata_only"
    assert "run_command" in terminal.protected_actions
    assert code_edit.current_status == "metadata_only"
    assert "apply_patch" in code_edit.protected_actions


def test_high_risk_tools_have_policy_metadata():
    for record in get_tool_inventory():
        if record.safety_level not in {"HIGH", "CRITICAL"}:
            continue
        assert record.supported_actions
        assert record.protected_actions or record.action_safety or record.requires_confirmation
