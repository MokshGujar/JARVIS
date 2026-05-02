from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Union


StreamItem = Union[str, Dict[str, Any]]


@dataclass(slots=True)
class AssistantRequest:
    message: str
    session_id: Optional[str] = None
    imgbase64: Optional[str] = None
    input_source: str = "text"
    voice_audio_base64: Optional[str] = None
    face_session_id: Optional[str] = None
    step_up_token: Optional[str] = None
    client_request_id: Optional[str] = None


@dataclass(slots=True)
class AssistantContext:
    session_id: str
    message: str
    chat_history: List[tuple[str, str]] = field(default_factory=list)
    imgbase64: Optional[str] = None
    input_source: str = "text"
    voice_audio_base64: Optional[str] = None
    face_session_id: Optional[str] = None
    step_up_token: Optional[str] = None
    memory_parts: List[str] = field(default_factory=list)


@dataclass(slots=True)
class ExecutionPlan:
    route: str
    mode: str = "stream"
    requires_face_auth: bool = False
    sensitive: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CapabilityResult:
    text: str = ""
    route: str = ""
    actions: Optional[Dict[str, Any]] = None
    events: List[Dict[str, Any]] = field(default_factory=list)
    background_tasks: List[Dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class PhoneAction:
    action_id: str
    action_type: str
    device_id: str
    status: str = "pending"
    phone_number: Optional[str] = None
    contact_name: Optional[str] = None
    call_method: Optional[str] = None
    contact_id: Optional[str] = None
    match_confidence: Optional[float] = None
    match_reason: Optional[str] = None
    channel: Optional[str] = None
    message_body: Optional[str] = None
    requires_verified_speaker: bool = True
    verification_status: Optional[str] = "required"
    clarification_candidates: Optional[List[Dict[str, Any]]] = None
    message: str = ""
    created_at: float = 0.0
    completed_at: Optional[float] = None


@dataclass(slots=True)
class IncomingCallRequest:
    phone_number: str
    caller_name_hint: Optional[str] = None
    device_id: str = ""
    speak_result: bool = True
    call_direction: str = "incoming"


class AssistantStream:
    def __init__(self, items: Iterator[StreamItem]) -> None:
        self.items = items
