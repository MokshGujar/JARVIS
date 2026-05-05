from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
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
