from __future__ import annotations

from app.core.contracts import AssistantContext, AssistantRequest


class ContextBuilder:
    def __init__(self, conversation_service, memory_capability=None) -> None:
        self.conversation_service = conversation_service
        self.memory_capability = memory_capability

    def build(self, request: AssistantRequest) -> AssistantContext:
        session_id = self.conversation_service.get_or_create_session(request.session_id)
        chat_history = self.conversation_service.format_history_for_llm(session_id, exclude_last=False)
        memory_parts = self.memory_capability.build_prompt_parts(request.message) if self.memory_capability else []
        return AssistantContext(
            session_id=session_id,
            message=request.message,
            chat_history=chat_history,
            imgbase64=request.imgbase64,
            input_source=request.input_source,
            voice_audio_base64=request.voice_audio_base64,
            face_session_id=request.face_session_id,
            step_up_token=request.step_up_token,
            memory_parts=memory_parts,
        )
