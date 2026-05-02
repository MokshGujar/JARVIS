from __future__ import annotations

from app.core.contracts import AssistantContext, CapabilityResult


class ReminderCapability:
    def __init__(self, reminder_service) -> None:
        self.reminder_service = reminder_service

    def looks_like_request(self, message: str) -> bool:
        return bool(self.reminder_service and self.reminder_service.looks_like_reminder_request(message))

    def execute(self, context: AssistantContext) -> CapabilityResult:
        result = self.reminder_service.create_reminder(context.message)
        text = str(result.get("message", "Reminder request handled."))
        return CapabilityResult(
            text=text,
            route="reminder",
            events=[
                {"activity": {"event": "routing", "route": "reminder"}},
                {"activity": {"event": "tasks_executing", "message": "Creating reminder..."}},
                {"activity": {"event": "tasks_completed", "message": text}},
            ],
        )

