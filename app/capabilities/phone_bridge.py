from __future__ import annotations

from app.core.contracts import AssistantContext, CapabilityResult, IncomingCallRequest


class PhoneBridgeCapability:
    def __init__(self, phone_command_service, caller_lookup_service) -> None:
        self.phone_command_service = phone_command_service
        self.caller_lookup_service = caller_lookup_service

    def looks_like_request(self, message: str) -> bool:
        if not self.phone_command_service:
            return False
        return bool(
            self.phone_command_service.looks_like_answer_request(message)
            or self.phone_command_service.looks_like_reject_request(message)
            or self.phone_command_service.looks_like_place_call_request(message)
            or self.phone_command_service.looks_like_message_request(message)
            or self.phone_command_service.looks_like_call_method_followup(message)
            or self.phone_command_service.looks_like_message_channel_followup(message)
        )

    def execute(self, context: AssistantContext) -> CapabilityResult:
        result = self.phone_command_service.route_phone_request(context.message)
        text = str((result or {}).get("message") or "Phone command queued.")
        return CapabilityResult(
            text=text,
            route="phone",
            events=[
                {"activity": {"event": "routing", "route": "phone"}},
                {"activity": {"event": "tasks_executing", "message": "Sending command to your phone..."}},
                {"activity": {"event": "tasks_completed", "message": text}},
            ],
        )

    def handle_incoming_call(self, request: IncomingCallRequest) -> dict:
        self.phone_command_service.note_device_seen(request.device_id)
        if not self.caller_lookup_service:
            raise RuntimeError("Caller lookup service is not initialized")
        return self.caller_lookup_service.build_incoming_call_payload(
            phone_number=request.phone_number,
            caller_name_hint=request.caller_name_hint,
            speak_result=request.speak_result,
            call_direction=request.call_direction,
        )

    def list_pending_actions(self, *, device_id: str, phone_number: str = "") -> dict:
        self.phone_command_service.note_device_seen(device_id)
        return {
            "actions": self.phone_command_service.get_pending_actions(
                device_id=device_id,
                phone_number=phone_number,
            )
        }

    def acknowledge_action(self, *, action_id: str, status: str, device_id: str, phone_number: str) -> bool:
        return self.phone_command_service.acknowledge_action(
            action_id=action_id,
            status=status,
            device_id=device_id or None,
            phone_number=phone_number or None,
        )

