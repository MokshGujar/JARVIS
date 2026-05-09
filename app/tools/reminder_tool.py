from __future__ import annotations

from typing import Any

from app.services.reminder_service import ReminderService
from app.tools.base import BaseTool, ToolContext, ToolResult, ToolRisk, ToolSpec


class ReminderTool(BaseTool):
    name = "reminder"

    def __init__(self, reminder_service: Any | None = None) -> None:
        self.reminder_service = reminder_service or ReminderService()
        self.spec = ToolSpec(
            name=self.name,
            description="Reminder parsing and due-reminder listing through the reminder service.",
            category="reminder",
            risk_level="MEDIUM",
            safety_level="MEDIUM",
            status="PARTIAL",
            routing_mode="ACTIVE",
            allowed_actions=["create", "list", "cancel", "update"],
            safe_partial_actions=["create", "list"],
            supported_intents=["reminder", "create_reminder"],
            adapter_provider="ReminderService",
            metadata={
                "current_status": "thin_wrapper",
                "supported_actions": ["create", "list", "cancel", "update"],
                "safe_partial_actions": ["create", "list"],
            },
        )

    def classify_risk(self, command: str) -> ToolRisk:
        return ToolRisk(level="MEDIUM", step_up_required=False, reasons=["reminder_tool"])

    def execute(self, context: ToolContext, **kwargs: Any) -> dict[str, Any]:
        payload = dict(context.payload or {})
        args = dict(payload.get("args") or {})
        action = str(payload.get("action") or context.intent or "create").strip().lower()
        if action in {"create", "create_reminder", "reminder"}:
            command = str(args.get("command") or context.command or "").strip()
            result = self.reminder_service.create_reminder(command)
            return self._result(result, action="create")

        if action in {"list", "show", "show_due", "due"}:
            reminders = list(self.reminder_service.get_due_reminders())
            if not reminders:
                return ToolResult(
                    success=True,
                    tool_name=self.name,
                    message="No due reminders right now.",
                    safety_level="LOW",
                    data={"action": "list", "reminders": []},
                ).as_dict()
            message = "\n".join(str(item.get("message") or "Reminder due") for item in reminders)
            return ToolResult(
                success=True,
                tool_name=self.name,
                message=message,
                safety_level="LOW",
                data={"action": "list", "reminders": reminders},
            ).as_dict()

        return ToolResult(
            success=False,
            tool_name=self.name,
            message="That reminder action is not available yet.",
            error="not_implemented",
            safety_level="MEDIUM",
            data={"action": action, "supported_actions": ["create", "list"]},
        ).as_dict()

    def _result(self, result: dict[str, Any], *, action: str) -> dict[str, Any]:
        ok = bool(result.get("success")) if isinstance(result, dict) else False
        message = str((result or {}).get("message") or "Reminder request handled.")
        return ToolResult(
            success=ok,
            tool_name=self.name,
            message=message,
            error=None if ok else str((result or {}).get("error") or "reminder_failed"),
            safety_level="MEDIUM",
            data={"action": action, **dict(result or {})},
        ).as_dict()
