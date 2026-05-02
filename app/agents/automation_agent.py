from __future__ import annotations

from app.tools.base import ToolContext


class AutomationAgent:
    def __init__(self, tool_registry) -> None:
        self.tool_registry = tool_registry

    def execute(self, intent: str, context: ToolContext):
        tool = self.tool_registry.select(intent)
        if not tool:
            return {"success": False, "action": "unsupported", "message": "No tool can handle that automation request."}
        return tool.execute(context)
