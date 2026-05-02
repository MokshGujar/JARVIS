from __future__ import annotations

from app.tools.base import ToolContext


class BrowserAgent:
    def __init__(self, browser_tool) -> None:
        self.browser_tool = browser_tool

    def execute(self, context: ToolContext):
        return self.browser_tool.execute(context)
