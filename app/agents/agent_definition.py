from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass(slots=True)
class AgentDefinition:
    name: str
    purpose: str
    allowed_tools: list[str] = field(default_factory=list)
    schedule: str = ""
    trigger: str = ""
    memory_scope: str = "session"
    approval_requirements: list[str] = field(default_factory=lambda: ["user_approval"])
    risk_profile: str = "LOW"
    output_format: str = "summary"
    enabled: bool = False
    status: str = "draft"
    created_at: str = ""
    last_run_at: str = ""
    owner_scope: str = "session"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AgentDefinition":
        return cls(
            name=str(payload.get("name") or ""),
            purpose=str(payload.get("purpose") or ""),
            allowed_tools=list(payload.get("allowed_tools") or []),
            schedule=str(payload.get("schedule") or ""),
            trigger=str(payload.get("trigger") or ""),
            memory_scope=str(payload.get("memory_scope") or "session"),
            approval_requirements=list(payload.get("approval_requirements") or ["user_approval"]),
            risk_profile=str(payload.get("risk_profile") or "LOW"),
            output_format=str(payload.get("output_format") or "summary"),
            enabled=bool(payload.get("enabled", False)),
            status=str(payload.get("status") or "draft"),
            created_at=str(payload.get("created_at") or ""),
            last_run_at=str(payload.get("last_run_at") or ""),
            owner_scope=str(payload.get("owner_scope") or "session"),
        )

    def can_use_tool(self, tool_name: str) -> bool:
        return str(tool_name or "").strip().lower() in {str(item).strip().lower() for item in self.allowed_tools}
