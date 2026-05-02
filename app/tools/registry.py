from __future__ import annotations

from typing import Iterable

from app.tools.base import AutomationTool


def _normalize_tool_name(name: str) -> str:
    return " ".join(str(name or "").strip().lower().split())


class ToolRegistry:
    def __init__(self, tools: Iterable[AutomationTool] | None = None) -> None:
        self._tools: dict[str, AutomationTool] = {}
        self._name_index: dict[str, str] = {}
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
