from __future__ import annotations

import logging
from typing import Iterable

from app.policy.models import RoutingMode, ToolMetadata, ToolRiskLevel, ToolStatus
from app.utils.runtime_observability import log_boundary
from app.tools.base import AutomationTool

logger = logging.getLogger(__name__)


def _normalize_tool_name(name: str) -> str:
    return " ".join(str(name or "").strip().lower().split())


class ToolRegistry:
    def __init__(self, tools: Iterable[AutomationTool] | None = None) -> None:
        self._tools: dict[str, AutomationTool] = {}
        self._name_index: dict[str, str] = {}
        self._metadata: dict[str, ToolMetadata] = {}
        for tool in tools or []:
            self.register(tool)

    def register(self, tool: AutomationTool) -> AutomationTool:
        name = str(getattr(tool, "name", "")).strip()
        normalized_name = _normalize_tool_name(name)
        if not name:
            raise ValueError("Tool must expose a non-empty name.")
        if normalized_name in self._name_index:
            raise ValueError(f"Tool already registered: {name}")
        self._tools[name] = tool
        self._name_index[normalized_name] = name
        self._metadata[name] = self._metadata_from_tool(tool)
        return tool

    def get(self, name: str) -> AutomationTool:
        normalized_name = _normalize_tool_name(name)
        registered_name = self._name_index.get(normalized_name)
        if registered_name is None:
            raise KeyError(f"Tool is not registered: {name}")
        return self._tools[registered_name]

    def contains(self, name: str) -> bool:
        return _normalize_tool_name(name) in self._name_index

    def select(self, intent: str) -> AutomationTool | None:
        for tool in self._tools.values():
            if tool.can_handle(intent):
                return tool
        return None

    def all(self) -> tuple[AutomationTool, ...]:
        return tuple(self._tools.values())

    def keys(self) -> tuple[str, ...]:
        return tuple(self._tools.keys())

    def items(self) -> tuple[tuple[str, AutomationTool], ...]:
        return tuple(self._tools.items())

    def metadata_for(self, name: str) -> ToolMetadata:
        registered_name = self._name_index.get(_normalize_tool_name(name))
        if registered_name is None:
            log_boundary(logger, "TOOL_REGISTRY", tool=name, action="", status="missing")
            raise KeyError(f"Tool metadata is not registered: {name}")
        metadata = self._metadata[registered_name]
        status = "resolved"
        if metadata.status == ToolStatus.DISABLED or metadata.routing_mode == RoutingMode.DISABLED:
            status = "disabled"
        elif metadata.status == ToolStatus.PLANNED:
            status = "unsupported"
        elif metadata.routing_mode in {RoutingMode.METADATA_ONLY, RoutingMode.HIDDEN}:
            status = "invalid_metadata"
        log_boundary(logger, "TOOL_REGISTRY", tool=registered_name, action="", status=status)
        return metadata

    def is_live_active(self, name: str, action: str) -> bool:
        return self.metadata_for(name).allows_execution(action)

    @staticmethod
    def _metadata_from_tool(tool: AutomationTool) -> ToolMetadata:
        name = str(getattr(tool, "name", "")).strip()
        try:
            from app.tools.tool_inventory import get_tool_inventory_record

            record = get_tool_inventory_record(name)
            if record is not None:
                return record.as_tool_metadata()
        except Exception:
            pass

        spec = getattr(tool, "spec", None)
        category = str(getattr(spec, "category", "automation") or "automation")
        status = _coerce_tool_status(getattr(spec, "status", "LIVE"))
        routing_mode = _coerce_routing_mode(getattr(spec, "routing_mode", "ACTIVE"))
        risk_level = _coerce_risk_level(getattr(spec, "safety_level", "LOW"))
        allowed_actions = _coerce_string_iterable(getattr(spec, "allowed_actions", []))
        safe_partial_actions = _coerce_string_iterable(getattr(spec, "safe_partial_actions", []))
        return ToolMetadata(
            name=name,
            category=category,
            status=status,
            routing_mode=routing_mode,
            risk_level=risk_level,
            requires_confirmation=bool(getattr(spec, "requires_confirmation", False)),
            requires_step_up=bool(getattr(spec, "requires_step_up", False) or getattr(spec, "requires_face_step_up", False)),
            supports_dry_run=bool(getattr(spec, "supports_dry_run", False)),
            adapter_provider=getattr(spec, "adapter_provider", None),
            allowed_actions=allowed_actions,
            safe_partial_actions=safe_partial_actions,
        )


def _coerce_tool_status(value: object) -> ToolStatus:
    normalized = str(value or "").strip().upper()
    if normalized in ToolStatus.__members__:
        return ToolStatus[normalized]
    if normalized in {item.value for item in ToolStatus}:
        return ToolStatus(normalized)
    return ToolStatus.LIVE


def _coerce_routing_mode(value: object) -> RoutingMode:
    normalized = str(value or "").strip().upper()
    if normalized in RoutingMode.__members__:
        return RoutingMode[normalized]
    if normalized in {item.value for item in RoutingMode}:
        return RoutingMode(normalized)
    return RoutingMode.ACTIVE


def _coerce_risk_level(value: object) -> ToolRiskLevel:
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
