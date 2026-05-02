from __future__ import annotations

from app.core.contracts import AssistantContext, CapabilityResult
from app.services.automation_response import normalize_automation_response


class AutomationCapability:
    def __init__(self, automation_service) -> None:
        self.automation_service = automation_service

    def handles_followup(self) -> bool:
        if not self.automation_service:
            return False
        return (
            self.automation_service.has_pending_open_clarification()
            or self.automation_service.has_pending_browser_search()
            or self.automation_service.has_pending_create_file_location()
            or self.automation_service.has_pending_delete_confirmation()
            or self.automation_service.has_pending_mark_confirmation()
            or self.automation_service.has_pending_whatsapp_clarification()
        )

    def looks_like_request(self, message: str) -> bool:
        return bool(self.automation_service and self.automation_service.looks_like_automation_request(message))

    def execute(self, context: AssistantContext) -> CapabilityResult:
        result = normalize_automation_response(self.automation_service.execute(context.message, session_id=context.session_id))
        if "spoken_text" in result:
            text = str(result.get("spoken_text") or "")
        else:
            text = str(result.get("message") or "Done.")
        display_text = str(result.get("display_text") or text)
        return CapabilityResult(
            text=text,
            route="automation",
            actions=result.get("actions") or [],
            events=[
                {"activity": {"event": "routing", "route": "automation"}},
                {"activity": {"event": "tasks_executing", "message": "Running desktop automation..."}},
                {"activity": {"event": "tasks_completed", "message": display_text}},
                *list(result.get("events") or []),
            ],
        )
