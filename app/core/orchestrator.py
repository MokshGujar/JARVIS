from __future__ import annotations

import time
from typing import Any, Dict, Iterator, Optional

from app.core.context_builder import ContextBuilder
from app.core.contracts import AssistantContext, AssistantRequest, CapabilityResult, StreamItem
from app.services.chat_service import CAMERA_BYPASS_TOKEN, _save_camera_image
from app.services.decision_types import CATEGORY_CAMERA, CATEGORY_GENERAL, CATEGORY_MIXED, CATEGORY_REALTIME, CATEGORY_TASK, HEAVY_INTENTS
from app.services.task_executor import TaskResponse
from config import FACE_STEP_UP_FOR_TOOLS_ENABLED


class AssistantOrchestrator:
    def __init__(
        self,
        *,
        conversation_service,
        intent_router,
        knowledge_capability,
        automation_capability=None,
        phone_bridge_capability=None,
        reminder_capability=None,
        research_capability=None,
        vision_capability=None,
        wake_on_lan_capability=None,
        memory_capability=None,
        face_identity_service=None,
        command_risk_service=None,
        step_up_auth_service=None,
        task_executor=None,
        task_manager=None,
    ) -> None:
        self.conversation_service = conversation_service
        self.intent_router = intent_router
        self.knowledge_capability = knowledge_capability
        self.automation_capability = automation_capability
        self.phone_bridge_capability = phone_bridge_capability
        self.reminder_capability = reminder_capability
        self.research_capability = research_capability
        self.vision_capability = vision_capability
        self.wake_on_lan_capability = wake_on_lan_capability
        self.memory_capability = memory_capability
        self.face_identity_service = face_identity_service
        self.command_risk_service = command_risk_service
        self.step_up_auth_service = step_up_auth_service
        self.task_executor = task_executor
        self.task_manager = task_manager
        self.context_builder = ContextBuilder(conversation_service, memory_capability)

    def build_context(self, request: AssistantRequest) -> AssistantContext:
        return self.context_builder.build(request)

    def get_or_create_session(self, session_id: Optional[str] = None) -> str:
        return self.conversation_service.get_or_create_session(session_id)

    def save_session(self, session_id: str, *, log_timing: bool = True) -> None:
        self.conversation_service.save_chat_session(session_id, log_timing=log_timing)

    def validate_session_id(self, session_id: str) -> bool:
        return self.conversation_service.validate_session_id(session_id)

    def get_chat_history(self, session_id: str):
        return self.conversation_service.get_chat_history(session_id)

    def handle_chat(self, request: AssistantRequest, *, mode: str) -> tuple[str, str]:
        context = self.build_context(request)
        if mode == "realtime":
            result = self.knowledge_capability.answer_realtime(context)
        else:
            result = self.knowledge_capability.answer_general(context)
        self.save_session(context.session_id)
        return context.session_id, result.text

    def stream_chat(self, request: AssistantRequest, *, mode: str) -> tuple[str, Iterator[StreamItem]]:
        context = self.build_context(request)
        if mode == "realtime":
            return context.session_id, self.knowledge_capability.stream_realtime(context)
        return context.session_id, self.knowledge_capability.stream_general(context)

    def route_fast(self, message: str, *, imgbase64: Optional[str] = None):
        return self.intent_router.route_fast(message, imgbase64=imgbase64)

    def execute_fast_route(self, session_id: str, request: AssistantRequest, route) -> tuple[str, dict | None]:
        command_text = request.message
        enforce_step_up = True
        if (route.intent or "").strip().lower() == "automation" and self.automation_capability:
            service = getattr(self.automation_capability, "automation_service", None)
            pending_text = service.pending_authorization_text(request.message) if service else None
            if pending_text:
                command_text = pending_text
            elif service and service.stages_high_risk_confirmation(request.message):
                enforce_step_up = False
        guard = self._authorize_command(
            command_text,
            command_action=route.intent or "instant",
            face_session_id=request.face_session_id,
            step_up_token=request.step_up_token,
            enforce_step_up=enforce_step_up,
        )
        if guard:
            return guard
        intent = (route.intent or "").strip().lower()
        context = AssistantContext(
            session_id=session_id,
            message=request.message,
            input_source=request.input_source,
            imgbase64=request.imgbase64,
            voice_audio_base64=request.voice_audio_base64,
            face_session_id=request.face_session_id,
            step_up_token=request.step_up_token,
            chat_history=self.conversation_service.format_history_for_llm(session_id),
        )

        if intent == "wake_on_lan" and self.wake_on_lan_capability:
            result = self.wake_on_lan_capability.execute(context)
            return result.text, result.actions

        if intent == "reminder" and self.reminder_capability:
            result = self.reminder_capability.execute(context)
            return result.text, result.actions

        if intent == "phone" and self.phone_bridge_capability:
            result = self.phone_bridge_capability.execute(context)
            return result.text, result.actions

        if intent == "automation" and self.automation_capability:
            result = self.automation_capability.execute(context)
            return result.text, result.actions

        if intent in {"open", "play", "google search", "youtube search"} and self.task_executor:
            response = self.task_executor.execute(
                route.payload.get("intents", []),
                self.conversation_service.format_history_for_llm(session_id),
            )
            return response.text or "Done.", self._task_actions_from_response(response)

        return "Done.", None

    def record_fast_response(self, session_id: str, user_message: str, response_text: str) -> None:
        self.conversation_service.add_message(session_id, "user", user_message)
        self.conversation_service.add_message(session_id, "assistant", response_text)
        self.save_session(session_id)

    def stream_assistant_llm(self, request: AssistantRequest) -> tuple[str, Iterator[StreamItem]]:
        context = self.build_context(request)
        return context.session_id, self._stream_assistant_context(context)

    def _stream_assistant_context(self, context: AssistantContext) -> Iterator[StreamItem]:
        t0_jarvis = time.perf_counter()
        self.conversation_service.add_message(context.session_id, "user", context.message)
        self.conversation_service.add_message(context.session_id, "assistant", "")
        yield {"activity": {"event": "query_detected", "message": context.message}}

        if self.wake_on_lan_capability and self.wake_on_lan_capability.looks_like_request(context.message):
            yield from self._yield_capability_result(context, self.wake_on_lan_capability.execute(context))
            return

        instant_text = self.conversation_service._instant_local_answer(context.message)
        if instant_text:
            self.conversation_service.sessions[context.session_id][-1].content = instant_text
            yield {"activity": {"event": "routing", "route": "local"}}
            yield {"activity": {"event": "streaming_started", "route": "local"}}
            yield instant_text
            self.save_session(context.session_id)
            return

        if self.reminder_capability and self.reminder_capability.looks_like_request(context.message):
            guard = self._authorize_command(context.message, command_action="reminder", face_session_id=context.face_session_id, step_up_token=context.step_up_token)
            if guard:
                yield from self._yield_capability_result(context, self._guard_result(*guard))
                return
            yield from self._yield_capability_result(context, self.reminder_capability.execute(context))
            return

        if self.research_capability and self.research_capability.looks_like_request(context.message):
            yield from self._yield_capability_result(context, self.research_capability.execute(context))
            return

        if self.phone_bridge_capability and self.phone_bridge_capability.looks_like_request(context.message):
            guard = self._authorize_command(context.message, command_action="phone", face_session_id=context.face_session_id, step_up_token=context.step_up_token)
            if guard:
                yield from self._yield_capability_result(context, self._guard_result(*guard))
                return
            yield from self._yield_capability_result(context, self.phone_bridge_capability.execute(context))
            return

        if self.automation_capability:
            service = getattr(self.automation_capability, "automation_service", None)
            if service and hasattr(service, "_load_session_pending_state"):
                service._load_session_pending_state(context.session_id)

        if self.automation_capability and self.automation_capability.handles_followup():
            service = getattr(self.automation_capability, "automation_service", None)
            auth_text = service.pending_authorization_text(context.message) if service else None
            guard = self._authorize_command(auth_text or context.message, command_action="automation", face_session_id=context.face_session_id, step_up_token=context.step_up_token)
            if guard:
                yield from self._yield_capability_result(context, self._guard_result(*guard))
                return
            yield from self._yield_capability_result(context, self.automation_capability.execute(context))
            return

        if (
            self.automation_capability
            and self.automation_capability.looks_like_request(context.message, session_id=context.session_id)
            and not self.conversation_service._looks_like_mixed_action_and_chat(context.message)
        ):
            service = getattr(self.automation_capability, "automation_service", None)
            enforce_step_up = not (service and service.stages_high_risk_confirmation(context.message))
            guard = self._authorize_command(context.message, command_action="automation", face_session_id=context.face_session_id, step_up_token=context.step_up_token, enforce_step_up=enforce_step_up)
            if guard:
                yield from self._yield_capability_result(context, self._guard_result(*guard))
                return
            yield from self._yield_capability_result(context, self.automation_capability.execute(context))
            return

        if context.imgbase64 and CAMERA_BYPASS_TOKEN in (context.message or ""):
            yield {"activity": {"event": "decision", "query_type": "camera", "reasoning": "Image attached", "elapsed_ms": 0}}
            yield {"activity": {"event": "routing", "route": "vision"}}
            yield {"activity": {"event": "vision_analyzing", "message": "Analyzing image..."}}
            yield {"activity": {"event": "streaming_started", "route": "vision"}}
            prompt = (context.message or "").replace(CAMERA_BYPASS_TOKEN, "").strip() or "What do you see in this image?"
            if self.conversation_service.sessions[context.session_id]:
                self.conversation_service.sessions[context.session_id][-2].content = prompt
            _save_camera_image(context.imgbase64, context.session_id)
            result = self.vision_capability.describe_image(context, prompt)
            self.conversation_service.sessions[context.session_id][-1].content = result.text
            yield result.text
            self.save_session(context.session_id)
            return

        category, primary_method, primary_elapsed_ms = self.intent_router.classify_primary(context)
        yield {
            "activity": {
                "event": "decision",
                "query_type": category,
                "reasoning": primary_method.capitalize(),
                "elapsed_ms": primary_elapsed_ms,
            }
        }

        if category == CATEGORY_CAMERA:
            yield {"activity": {"event": "routing", "route": "camera"}}
            if context.imgbase64:
                yield {"activity": {"event": "vision_analyzing", "message": "Analyzing image..."}}
                yield {"activity": {"event": "streaming_started", "route": "vision"}}
                _save_camera_image(context.imgbase64, context.session_id)
                result = self.vision_capability.describe_image(context, context.message)
                self.conversation_service.sessions[context.session_id][-1].content = result.text
                yield result.text
            else:
                text = "Let me take a look..."
                yield {"actions": {"wopens": [], "plays": [], "images": [], "contents": [], "googlesearches": [], "youtubesearches": [], "cam": {"action": "open_and_capture", "resend_message": context.message}}}
                yield {"activity": {"event": "actions_emitted", "message": "camera (auto-capture)"}}
                self.conversation_service.sessions[context.session_id][-1].content = text
                yield text
            self.save_session(context.session_id)
            return

        if category in (CATEGORY_TASK, CATEGORY_MIXED):
            yield from self._stream_task_route(context, category)
            return

        use_realtime = category == CATEGORY_REALTIME
        route_name = "realtime" if use_realtime else "general"
        yield {"activity": {"event": "routing", "route": route_name}}
        yield {"activity": {"event": "streaming_started", "route": route_name}}
        stream_iter = (
            self.knowledge_capability.stream_realtime(context)
            if use_realtime
            else self.knowledge_capability.stream_general(context)
        )
        yield from stream_iter
        elapsed_jarvis = time.perf_counter() - t0_jarvis
        _ = elapsed_jarvis

    def _stream_task_route(self, context: AssistantContext, category: str) -> Iterator[StreamItem]:
        yield {"activity": {"event": "routing", "route": "task" if category == CATEGORY_TASK else "mixed"}}
        task_types, _task_method, _task_elapsed_ms = self.intent_router.classify_task(context)
        task_name = ", ".join(task_types[:3]) if task_types else "task"
        yield {"activity": {"event": "intent_classified", "intent": task_name}}
        intents = self.intent_router.extract_task_payloads(context, task_types)
        instant_intents = [(t, p) for t, p in intents if t not in HEAVY_INTENTS]
        heavy_intents = [(t, p) for t, p in intents if t in HEAVY_INTENTS]
        instant_response = TaskResponse()

        if self.task_executor and instant_intents:
            guard = self._authorize_command(context.message, command_action="task", face_session_id=context.face_session_id, step_up_token=context.step_up_token)
            if guard:
                text, actions = guard
                self.conversation_service.sessions[context.session_id][-1].content = text
                yield {"activity": {"event": "auth_required", "message": text}}
                if actions:
                    yield {"actions": actions}
                yield text
                self.save_session(context.session_id)
                return
            yield {"activity": {"event": "tasks_executing", "message": "Running instant tasks..."}}
            instant_response = self.task_executor.execute(instant_intents, context.chat_history)
            yield {"activity": {"event": "tasks_completed", "message": "Instant tasks done"}}
            if instant_response.wopens or instant_response.plays or instant_response.googlesearches or instant_response.youtubesearches or instant_response.cam:
                actions = {
                    "wopens": instant_response.wopens,
                    "plays": instant_response.plays,
                    "images": [],
                    "contents": [],
                    "googlesearches": instant_response.googlesearches,
                    "youtubesearches": instant_response.youtubesearches,
                    "cam": instant_response.cam,
                }
                yield {"activity": {"event": "actions_emitted", "message": "actions"}}
                yield {"actions": actions}

        bg_task_ids = []
        if self.task_manager and heavy_intents:
            guard = self._authorize_command(context.message, command_action="task", face_session_id=context.face_session_id, step_up_token=context.step_up_token)
            if guard:
                text, actions = guard
                self.conversation_service.sessions[context.session_id][-1].content = text
                yield {"activity": {"event": "auth_required", "message": text}}
                if actions:
                    yield {"actions": actions}
                yield text
                self.save_session(context.session_id)
                return
            yield {"activity": {"event": "tasks_executing", "message": "Dispatching background tasks..."}}
            for intent_type, payload in heavy_intents:
                task_id = self.task_manager.submit(intent_type, payload, context.chat_history)
                bg_task_ids.append({"task_id": task_id, "type": intent_type, "label": payload.get("prompt") or payload.get("message", "")[:100]})
            yield {"activity": {"event": "background_dispatched", "message": f"{len(bg_task_ids)} task(s) in background"}}
        elif not self.task_manager and heavy_intents and self.task_executor:
            yield {"activity": {"event": "tasks_executing", "message": f"Running {task_name}..."}}
            sync_response = self.task_executor.execute(heavy_intents, context.chat_history)
            yield {"activity": {"event": "tasks_completed", "message": "Tasks completed"}}
            if sync_response.images or sync_response.contents:
                yield {"actions": {"wopens": [], "plays": [], "images": sync_response.images, "contents": sync_response.contents, "googlesearches": [], "youtubesearches": [], "cam": None}}
            instant_response.text = instant_response.text or sync_response.text

        if category == CATEGORY_MIXED:
            yield {"activity": {"event": "streaming_started", "route": "mixed"}}
            stream_iter = self.knowledge_capability.stream_realtime(context)
            yield from stream_iter
            if bg_task_ids:
                yield {"background_tasks": bg_task_ids}
            return

        text_parts = []
        if instant_response.text:
            text_parts.append(instant_response.text)
        if bg_task_ids:
            bg_labels = []
            for bt in bg_task_ids:
                if bt["type"] == "generate_image":
                    bg_labels.append("image generation")
                elif bt["type"] == "content":
                    bg_labels.append("content writing")
                else:
                    bg_labels.append(bt["type"])
            text_parts.append(f"I'm working on the {', '.join(bg_labels)} in the background. I'll open it for you when it's ready.")
        text = "Could you clarify what you'd like me to do?" if not text_parts and not bg_task_ids and not intents else " ".join(text_parts) if text_parts else "Done."
        self.conversation_service.sessions[context.session_id][-1].content = text
        yield text
        if bg_task_ids:
            yield {"background_tasks": bg_task_ids}
        self.save_session(context.session_id)

    def _yield_capability_result(self, context: AssistantContext, result: CapabilityResult) -> Iterator[StreamItem]:
        for event in result.events:
            yield event
        self.conversation_service.sessions[context.session_id][-1].content = result.text
        if result.actions:
            yield {"actions": result.actions}
        yield result.text
        if result.background_tasks:
            yield {"background_tasks": result.background_tasks}
        self.save_session(context.session_id)

    def _authorize_command(
        self,
        command_text: str,
        *,
        command_action: str,
        face_session_id: str | None,
        step_up_token: str | None,
        enforce_step_up: bool = True,
    ) -> tuple[str, dict | None] | None:
        if not self.command_risk_service or not self.face_identity_service:
            return None
        risk = self.command_risk_service.classify(command_text, command_action=command_action)
        if command_action in {"automation", "task", "phone", "reminder", "instant"} and not FACE_STEP_UP_FOR_TOOLS_ENABLED:
            return None
        if not self.face_identity_service.validate_session(face_session_id):
            return (
                "Face verification is required before I can run that command.",
                {
                    "auth": {
                        "face_verification_required": True,
                        "step_up_required": risk.step_up_required,
                        "risk": risk.as_dict(),
                    }
                },
            )
        if not risk.step_up_required or not enforce_step_up:
            return None
        if not self.step_up_auth_service:
            return (
                "Fresh face verification is required for that command, but step-up auth is unavailable.",
                {"auth": {"step_up_required": True, "risk": risk.as_dict(), "reason": "step_up_unavailable"}},
            )
        ok, reason = self.step_up_auth_service.consume(
            token=step_up_token,
            face_session_id=face_session_id,
            risk=risk,
        )
        if ok:
            return None
        return (
            "Fresh live face verification is required before I can run that high-risk command.",
            {"auth": {"step_up_required": True, "risk": risk.as_dict(), "reason": reason}},
        )

    def _guard_result(self, text: str, actions: dict | None) -> CapabilityResult:
        return CapabilityResult(
            text=text,
            route="auth",
            actions=actions,
            events=[{"activity": {"event": "auth_required", "message": text}}],
        )

    def _task_actions_from_response(self, response: TaskResponse) -> dict:
        return {
            "wopens": response.wopens,
            "plays": response.plays,
            "images": response.images,
            "contents": response.contents,
            "googlesearches": response.googlesearches,
            "youtubesearches": response.youtubesearches,
            "cam": response.cam,
        }
