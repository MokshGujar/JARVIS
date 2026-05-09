from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from config import JARVIS_AGENT_MODE, JARVIS_DEVELOPER_MODE, JARVIS_SECURITY_MODE


class SecurityMode(str, Enum):
    SAFE = "safe"
    TRUSTED = "trusted"
    DEVELOPER = "developer"
    AGENT = "agent"

    @classmethod
    def from_value(cls, value: str | None) -> "SecurityMode":
        normalized = str(value or "").strip().lower()
        for mode in cls:
            if normalized == mode.value:
                return mode
        return cls.SAFE


@dataclass(frozen=True, slots=True)
class SecurityModeDecision:
    mode: SecurityMode
    allowed: bool
    requires_confirmation: bool
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "allowed": self.allowed,
            "requires_confirmation": self.requires_confirmation,
            "reason": self.reason,
        }


class SecurityModeService:
    def __init__(self, mode: SecurityMode | str | None = None) -> None:
        self.mode = mode if isinstance(mode, SecurityMode) else SecurityMode.from_value(mode or JARVIS_SECURITY_MODE)

    @property
    def developer_mode_enabled(self) -> bool:
        return bool(JARVIS_DEVELOPER_MODE) or self.mode == SecurityMode.DEVELOPER

    @property
    def agent_mode_enabled(self) -> bool:
        return bool(JARVIS_AGENT_MODE) or self.mode == SecurityMode.AGENT

    def communication_decision(self, *, exact_recipient: bool, fresh_user_command: bool, source: str = "user") -> SecurityModeDecision:
        if self.mode == SecurityMode.SAFE:
            return SecurityModeDecision(self.mode, False, True, "safe_mode_requires_confirmation_for_communication")
        if str(source or "").lower() in {"agent", "background", "scheduled", "recovered"}:
            return SecurityModeDecision(self.mode, False, True, "background_communication_requires_confirmation")
        if self.mode in {SecurityMode.TRUSTED, SecurityMode.DEVELOPER} and exact_recipient and fresh_user_command:
            return SecurityModeDecision(self.mode, True, False, "trusted_exact_fresh_communication_allowed")
        if self.mode == SecurityMode.AGENT:
            return SecurityModeDecision(self.mode, False, True, "agent_mode_needs_explicit_communication_scope")
        return SecurityModeDecision(self.mode, False, True, "communication_requires_confirmation")

    def terminal_decision(self, command: str) -> SecurityModeDecision:
        lowered = str(command or "").strip().lower()
        destructive = any(token in lowered for token in ("rm -rf", "del /", "format", "shutdown", "restart", "git reset --hard"))
        if destructive:
            return SecurityModeDecision(self.mode, False, True, "destructive_terminal_command_blocked")
        if self.developer_mode_enabled:
            return SecurityModeDecision(self.mode, False, True, "terminal_requires_explicit_permission")
        return SecurityModeDecision(self.mode, False, False, "terminal_proposal_only")

    def agent_tool_decision(self, *, tool_name: str, allowed_tools: list[str] | tuple[str, ...]) -> SecurityModeDecision:
        normalized_allowed = {str(item).strip().lower() for item in allowed_tools}
        normalized_tool = str(tool_name or "").strip().lower()
        if not self.agent_mode_enabled:
            return SecurityModeDecision(self.mode, False, True, "agent_mode_disabled")
        if normalized_tool not in normalized_allowed:
            return SecurityModeDecision(self.mode, False, True, "agent_tool_not_allowed")
        return SecurityModeDecision(self.mode, True, False, "agent_tool_allowed")
