from __future__ import annotations

from app.core.contracts import IncomingCallRequest


class CallerLookupCapability:
    def __init__(self, caller_lookup_service) -> None:
        self.caller_lookup_service = caller_lookup_service

    def handle_incoming_call(self, request: IncomingCallRequest) -> dict:
        return self.caller_lookup_service.build_incoming_call_payload(
            phone_number=request.phone_number,
            caller_name_hint=request.caller_name_hint,
            speak_result=request.speak_result,
            call_direction=request.call_direction,
        )

