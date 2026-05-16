from __future__ import annotations

import logging

from app.policy.models import RoutingMode, ToolMetadata, ToolStatus
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
        return ToolMetadata.from_tool_spec(name=name, spec=spec)
