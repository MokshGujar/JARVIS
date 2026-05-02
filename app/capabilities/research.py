from __future__ import annotations

from app.core.contracts import AssistantContext, CapabilityResult


class ResearchCapability:
    def __init__(self, research_tools_service) -> None:
        self.research_tools_service = research_tools_service

    def looks_like_request(self, message: str) -> bool:
        return bool(self.research_tools_service and self.research_tools_service.looks_like_research_request(message))

    def execute(self, context: AssistantContext) -> CapabilityResult:
        result = self.research_tools_service.handle_request(
            context.message,
            chat_history=context.chat_history,
        )
        text = str(result.get("message", "Research request handled."))
        return CapabilityResult(
            text=text,
            route="research",
            events=[
                {"activity": {"event": "routing", "route": "research"}},
                {"activity": {"event": "tasks_executing", "message": "Looking that up..."}},
                {"activity": {"event": "tasks_completed", "message": text}},
            ],
        )

