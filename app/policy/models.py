from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from collections.abc import Iterable
from typing import Any


class PolicyDecisionType(str, Enum):
    ALLOW = "ALLOW"
    CONFIRM = "CONFIRM"
    STEP_UP = "STEP_UP"
    DENY = "DENY"


class ToolRiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ToolStatus(str, Enum):
    LIVE = "LIVE"
    PARTIAL = "PARTIAL"
    PLANNED = "PLANNED"
    DISABLED = "DISABLED"


class RoutingMode(str, Enum):
    ACTIVE = "ACTIVE"
    HIDDEN = "HIDDEN"
    METADATA_ONLY = "METADATA_ONLY"
    DISABLED = "DISABLED"


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    decision: PolicyDecisionType
    risk_level: ToolRiskLevel
    requires_confirmation: bool = False
    requires_step_up: bool = False
    reason: str = ""
    tool_name: str = ""
    action: str = ""
    session_id: str | None = None
    turn_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision.value,
            "risk_level": self.risk_level.value,
            "requires_confirmation": self.requires_confirmation,
            "requires_step_up": self.requires_step_up,
            "reason": self.reason,
            "tool_name": self.tool_name,
            "action": self.action,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class ToolMetadata:
    """Canonical executable tool metadata consumed by policy enforcement.

    `requires_step_up` means the protected-action permission gate used by the
    executor. It is intentionally separate from launcher Face Gate state.
    Older tool specs may still expose `requires_face_step_up`; conversion keeps
    that as compatibility input without changing current policy defaults.
    """

    name: str
    category: str
    status: ToolStatus
    routing_mode: RoutingMode
    risk_level: ToolRiskLevel
    requires_confirmation: bool = False
    requires_step_up: bool = False
    supports_dry_run: bool = False
    adapter_provider: str | None = None
    allowed_actions: tuple[str, ...] = field(default_factory=tuple)
    safe_partial_actions: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_values(
        cls,
        *,
        name: str,
        category: str = "automation",
        status: object = ToolStatus.LIVE,
        routing_mode: object = RoutingMode.ACTIVE,
        risk_level: object = ToolRiskLevel.LOW,
        requires_confirmation: bool = False,
        requires_step_up: bool = False,
        supports_dry_run: bool = False,
        adapter_provider: str | None = None,
        allowed_actions: object = (),
        safe_partial_actions: object = (),
    ) -> "ToolMetadata":
        return cls(
            name=str(name or "").strip(),
            category=str(category or "automation"),
            status=_coerce_tool_status(status),
            routing_mode=_coerce_routing_mode(routing_mode),
            risk_level=_coerce_risk_level(risk_level),
            requires_confirmation=bool(requires_confirmation),
            requires_step_up=bool(requires_step_up),
            supports_dry_run=bool(supports_dry_run),
            adapter_provider=adapter_provider,
            allowed_actions=_coerce_string_iterable(allowed_actions),
            safe_partial_actions=_coerce_string_iterable(safe_partial_actions),
        )

    @classmethod
    def from_tool_spec(cls, *, name: str, spec: Any) -> "ToolMetadata":
        requires_step_up = bool(
            getattr(spec, "requires_step_up", False)
            or getattr(spec, "requires_face_step_up", False)
        )
        return cls.from_values(
            name=name,
            category=getattr(spec, "category", "automation"),
            status=getattr(spec, "status", ToolStatus.LIVE),
            routing_mode=getattr(spec, "routing_mode", RoutingMode.ACTIVE),
            risk_level=getattr(spec, "safety_level", ToolRiskLevel.LOW),
            requires_confirmation=bool(getattr(spec, "requires_confirmation", False)),
            requires_step_up=requires_step_up,
            supports_dry_run=bool(getattr(spec, "supports_dry_run", False)),
            adapter_provider=getattr(spec, "adapter_provider", None),
            allowed_actions=getattr(spec, "allowed_actions", ()),
            safe_partial_actions=getattr(spec, "safe_partial_actions", ()),
        )

    def allows_execution(self, action: str) -> bool:
        normalized_action = _normalize_action(action)
        if self.status == ToolStatus.DISABLED or self.routing_mode == RoutingMode.DISABLED:
            return False
        if self.status == ToolStatus.PLANNED or self.routing_mode == RoutingMode.METADATA_ONLY:
            return False
        if self.routing_mode == RoutingMode.HIDDEN:
            return False
        if self.status == ToolStatus.LIVE and self.routing_mode == RoutingMode.ACTIVE:
            return not self.allowed_actions or normalized_action in {_normalize_action(item) for item in self.allowed_actions}
        if self.status == ToolStatus.PARTIAL and self.routing_mode == RoutingMode.ACTIVE:
            return normalized_action in {_normalize_action(item) for item in self.safe_partial_actions}
        return False

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category,
            "status": self.status.value,
            "routing_mode": self.routing_mode.value,
            "risk_level": self.risk_level.value,
            "requires_confirmation": self.requires_confirmation,
            "requires_step_up": self.requires_step_up,
            "supports_dry_run": self.supports_dry_run,
            "adapter_provider": self.adapter_provider,
            "allowed_actions": list(self.allowed_actions),
            "safe_partial_actions": list(self.safe_partial_actions),
        }


@dataclass(frozen=True, slots=True)
class ExecutionRequest:
    session_id: str | None
    turn_id: str | None
    tool_name: str
    action: str
    args: dict[str, Any] = field(default_factory=dict)
    policy_decision: PolicyDecision | None = None
    confirmation_id: str | None = None
    step_up_verified: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "tool_name": self.tool_name,
            "action": self.action,
            "args": dict(self.args),
            "policy_decision": self.policy_decision.as_dict() if self.policy_decision else None,
            "confirmation_id": self.confirmation_id,
            "step_up_verified": self.step_up_verified,
        }


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    ok: bool
    tool_name: str
    action: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    audit_id: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "tool_name": self.tool_name,
            "action": self.action,
            "message": self.message,
            "data": dict(self.data),
            "error": self.error,
            "audit_id": self.audit_id,
        }


def _normalize_action(action: str) -> str:
    return str(action or "").strip().lower()


def _coerce_tool_status(value: object) -> ToolStatus:
    if isinstance(value, ToolStatus):
        return value
    normalized = str(value or "").strip().upper()
    if normalized in ToolStatus.__members__:
        return ToolStatus[normalized]
    if normalized in {item.value for item in ToolStatus}:
        return ToolStatus(normalized)
    return ToolStatus.LIVE


def _coerce_routing_mode(value: object) -> RoutingMode:
    if isinstance(value, RoutingMode):
        return value
    normalized = str(value or "").strip().upper()
    if normalized in RoutingMode.__members__:
        return RoutingMode[normalized]
    if normalized in {item.value for item in RoutingMode}:
        return RoutingMode(normalized)
    return RoutingMode.ACTIVE


def _coerce_risk_level(value: object) -> ToolRiskLevel:
    if isinstance(value, ToolRiskLevel):
        return value
    normalized = str(value or "").strip().upper().replace("_RISK", "")
    if normalized in ToolRiskLevel.__members__:
        return ToolRiskLevel[normalized]
    if normalized in {item.value for item in ToolRiskLevel}:
        return ToolRiskLevel(normalized)
    return ToolRiskLevel.LOW


def _coerce_string_iterable(value: object) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Iterable):
        return ()
    return tuple(str(item).strip().lower() for item in value if str(item).strip())
