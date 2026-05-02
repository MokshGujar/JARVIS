from __future__ import annotations

from typing import Iterable

from app.tools.base import AutomationTool
from app.tools.registry import ToolRegistry as BaseToolRegistry


class ToolRegistry(BaseToolRegistry):
    def __init__(self, tools: Iterable[AutomationTool] | None = None) -> None:
        super().__init__(tools)

    def by_name(self, name: str) -> AutomationTool:
        return self.get(name)

    def by_category(self, category: str) -> tuple[AutomationTool, ...]:
        normalized = str(category or "").strip().lower()
        return tuple(
            tool
            for tool in self.all()
            if str(getattr(getattr(tool, "spec", None), "category", "") or "").strip().lower() == normalized
        )

    def by_intent(self, intent: str) -> AutomationTool | None:
        return self.select(intent)

    def by_scenario(self, scenario: str) -> AutomationTool | None:
        return self.select(scenario)
