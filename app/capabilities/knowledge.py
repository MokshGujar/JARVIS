from __future__ import annotations

from typing import Iterator

from app.core.contracts import AssistantContext, CapabilityResult, StreamItem


class KnowledgeCapability:
    def __init__(self, conversation_service) -> None:
        self.conversation_service = conversation_service

    def answer_general(self, context: AssistantContext) -> CapabilityResult:
        text = self.conversation_service.process_message(context.session_id, context.message)
        return CapabilityResult(text=text, route="general")

    def answer_realtime(self, context: AssistantContext) -> CapabilityResult:
        text = self.conversation_service.process_realtime_message(context.session_id, context.message)
        return CapabilityResult(text=text, route="realtime")

    def stream_general(self, context: AssistantContext) -> Iterator[StreamItem]:
        yield from self.conversation_service.process_message_stream(context.session_id, context.message)

    def stream_realtime(self, context: AssistantContext) -> Iterator[StreamItem]:
        yield from self.conversation_service.process_realtime_message_stream(context.session_id, context.message)

