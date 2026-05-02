from __future__ import annotations


class OrchestratorAgent:
    def __init__(self, tool_registry=None, security_agent=None) -> None:
        self.tool_registry = tool_registry
        self.security_agent = security_agent

    def select_tool(self, intent: str):
        if not self.tool_registry:
            return None
        return self.tool_registry.select(intent)
