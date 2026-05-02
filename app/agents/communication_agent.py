from __future__ import annotations

from app.tools.base import ToolContext


class CommunicationAgent:
    def __init__(self, whatsapp_tool) -> None:
        self.whatsapp_tool = whatsapp_tool

    def execute_whatsapp(self, context: ToolContext):
        return self.whatsapp_tool.execute(context)
