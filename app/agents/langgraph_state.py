from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass(frozen=True, slots=True)
class ToolRequest:
    tool_name: str
    action: str
    args: dict[str, Any] = field(default_factory=dict)
    intent: str = ""
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class LangGraphState:
    user_request: str
    workflow: str
    tool_requests: list[ToolRequest] = field(default_factory=list)
    results: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "user_request": self.user_request,
            "workflow": self.workflow,
            "tool_requests": [request.as_dict() for request in self.tool_requests],
            "results": [dict(result) for result in self.results],
            "error": self.error,
        }
