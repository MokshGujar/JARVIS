from __future__ import annotations

from app.core.contracts import AssistantContext, CapabilityResult


class WakeOnLanCapability:
    def __init__(self, wake_on_lan_service) -> None:
        self.wake_on_lan_service = wake_on_lan_service

    def looks_like_request(self, message: str) -> bool:
        return bool(self.wake_on_lan_service and self.wake_on_lan_service.looks_like_wake_request(message))

    def execute(self, context: AssistantContext) -> CapabilityResult:
        result = self.wake_on_lan_service.wake_laptop()
        text = str(result.get("message", "Wake-on-LAN request handled."))
        return CapabilityResult(
            text=text,
            route="wake_on_lan",
            events=[
                {"activity": {"event": "routing", "route": "wake_on_lan"}},
                {"activity": {"event": "tasks_executing", "message": "Sending Wake-on-LAN packet..."}},
                {"activity": {"event": "tasks_completed", "message": text}},
            ],
        )

