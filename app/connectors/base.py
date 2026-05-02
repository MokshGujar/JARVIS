from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class ConnectorCapability:
    name: str
    description: str = ""
    risk_level: str = "LOW_RISK"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ConnectorStatus:
    connected: bool
    state: str = "unknown"
    message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ConnectorResult:
    success: bool
    status: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "status": self.status,
            "message": self.message,
            **self.data,
        }


@runtime_checkable
class BaseConnector(Protocol):
    connector_id: str
    display_name: str

    def status(self) -> ConnectorStatus:
        ...

    def capabilities(self) -> tuple[ConnectorCapability, ...]:
        ...
