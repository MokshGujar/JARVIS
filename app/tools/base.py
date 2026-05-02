from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Protocol


ToolRiskLevel = str


@dataclass(slots=True)
class ToolSpec:
    name: str
    description: str = ""
    category: str = "automation"
    risk_level: ToolRiskLevel = "LOW_RISK"
    safety_level: str = "LOW"
    requires_confirmation: bool = False
    requires_face_step_up: bool = False
    requires_voice_permission: bool = False
    supported_intents: list[str] = field(default_factory=list)
    timeout_seconds: float = 30.0
    required_capabilities: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ToolRisk:
    level: ToolRiskLevel = "LOW_RISK"
    step_up_required: bool = False
    reasons: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ToolContext:
    command: str
    intent: str = ""
    session_id: str | None = None
    face_session_id: str | None = None
    step_up_token: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    source: str = "text"
    user_id: str | None = None
    security_state: dict[str, Any] = field(default_factory=dict)
    confirmation_state: dict[str, Any] = field(default_factory=dict)
    request_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def user_text(self) -> str:
        return self.command


@dataclass(slots=True)
class ToolExecutionResult:
    success: bool
    action: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "action": self.action,
            "message": self.message,
            **self.data,
        }


@dataclass(slots=True)
class ToolResult:
    success: bool
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    tool_name: str = ""
    error: str | None = None
    safety_level: str = "LOW"
    requires_followup: bool = False
    requires_confirmation: bool = False
    requires_face_step_up: bool = False
    requires_voice_permission: bool = False

    def as_dict(self) -> dict[str, Any]:
        data = dict(self.data or {})
        action = str(data.get("action") or "unknown")
        result = {
            "success": self.success,
            "action": action,
            "message": self.message,
            "tool_name": self.tool_name,
            "data": data,
            "error": self.error,
            "safety_level": self.safety_level,
            "requires_followup": self.requires_followup,
            "requires_confirmation": self.requires_confirmation,
            "requires_face_step_up": self.requires_face_step_up,
            "requires_voice_permission": self.requires_voice_permission,
        }
        result.update(data)
        result["success"] = self.success
        result["message"] = self.message
        result["tool_name"] = self.tool_name
        result["data"] = data
        result["error"] = self.error
        result["safety_level"] = self.safety_level
        result["requires_confirmation"] = bool(self.requires_confirmation or data.get("requires_confirmation", False))
        result["requires_face_step_up"] = self.requires_face_step_up
        result["requires_voice_permission"] = bool(self.requires_voice_permission or data.get("requires_voice_permission", False))
        return result


class BaseTool(ABC):
    name: str = ""
    spec: ToolSpec = ToolSpec(name="")

    @property
    def description(self) -> str:
        return self.spec.description

    @property
    def category(self) -> str:
        return self.spec.category

    @property
    def supported_intents(self) -> list[str]:
        return list(self.spec.supported_intents)

    @property
    def safety_level(self) -> str:
        return self.spec.safety_level

    @property
    def requires_confirmation(self) -> bool:
        return bool(self.spec.requires_confirmation)

    @property
    def requires_face_step_up(self) -> bool:
        return bool(self.spec.requires_face_step_up)

    @property
    def requires_voice_permission(self) -> bool:
        return bool(self.spec.requires_voice_permission)

    def can_handle(self, intent: str) -> bool:
        normalized = str(intent or "").strip().lower()
        return normalized in {self.name, self.category, *[item.lower() for item in self.supported_intents]}

    def classify_risk(self, command: str) -> ToolRisk:
        return ToolRisk(
            level=self.spec.risk_level,
            step_up_required=self.spec.requires_face_step_up,
            reasons=[self.spec.safety_level.lower()],
        )

    @abstractmethod
    def execute(self, context: ToolContext, **kwargs: Any) -> dict[str, Any] | None:
        ...


def normalize_tool_result(result: Any, *, default_action: str = "unknown") -> dict[str, Any]:
    if isinstance(result, ToolResult):
        normalized = result.as_dict()
        return _with_required_tool_result_fields(normalized, default_action=default_action)
    if isinstance(result, ToolExecutionResult):
        return _with_required_tool_result_fields(result.as_dict(), default_action=default_action)
    if not isinstance(result, dict):
        return _with_required_tool_result_fields({
            "success": False,
            "action": default_action,
            "message": "Tool returned an invalid result.",
        }, default_action=default_action)

    normalized = dict(result)
    normalized["success"] = bool(normalized.get("success", False))
    normalized["action"] = str(normalized.get("action") or default_action)
    normalized["message"] = str(normalized.get("message") or "")
    return _with_required_tool_result_fields(normalized, default_action=default_action)


def _with_required_tool_result_fields(result: dict[str, Any], *, default_action: str) -> dict[str, Any]:
    normalized = dict(result)
    normalized["success"] = bool(normalized.get("success", False))
    normalized["action"] = str(normalized.get("action") or default_action or "unknown")
    normalized["message"] = str(normalized.get("message") or "")
    normalized.setdefault("error", None)
    data = normalized.get("data")
    normalized["data"] = dict(data) if isinstance(data, dict) else {}
    normalized.setdefault("safety_level", "LOW")
    normalized["requires_confirmation"] = bool(normalized.get("requires_confirmation", False))
    normalized["requires_voice_permission"] = bool(normalized.get("requires_voice_permission", False))
    normalized["requires_face_step_up"] = bool(normalized.get("requires_face_step_up", False))
    return normalized


class AutomationTool(Protocol):
    name: str

    def can_handle(self, intent: str) -> bool:
        ...

    def classify_risk(self, command: str) -> ToolRisk:
        ...

    def execute(self, context: ToolContext, **kwargs: Any) -> dict[str, Any] | None:
        ...
