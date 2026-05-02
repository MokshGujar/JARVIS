from __future__ import annotations

from typing import Optional

from app.core.contracts import AssistantContext


class IntentRouter:
    def __init__(self, *, fast_router=None, brain_service=None) -> None:
        self.fast_router = fast_router
        self.brain_service = brain_service

    def route_fast(self, message: str, *, imgbase64: Optional[str] = None):
        if not self.fast_router:
            return None
        return self.fast_router.route(message, imgbase64=imgbase64)

    def classify_primary(self, context: AssistantContext) -> tuple[str, str, int]:
        if not self.brain_service:
            return ("general", "default", 0)
        return self.brain_service.classify_primary(
            context.message,
            context.chat_history,
            key_index=0,
        )

    def classify_task(self, context: AssistantContext) -> tuple[list[str], str, int]:
        if not self.brain_service:
            return ([], "default", 0)
        return self.brain_service.classify_task(
            context.message,
            context.chat_history,
            key_index=0,
        )

    def extract_task_payloads(self, context: AssistantContext, task_types: list[str]):
        if not self.brain_service:
            return []
        return self.brain_service.extract_task_payloads(
            context.message,
            task_types,
            context.chat_history,
        )

