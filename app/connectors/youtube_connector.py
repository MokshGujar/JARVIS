from __future__ import annotations

from typing import Any, Dict


class YouTubeConnector:
    """Connector boundary for YouTube browser actions owned by BrowserTool."""

    def __init__(self, browser_connector: Any | None = None) -> None:
        self.browser_connector = browser_connector

    def play(self, query: str) -> Dict[str, str | bool]:
        query = (query or "").strip()
        if not query:
            return {"success": False, "action": "youtube_tools", "message": "Tell me what to play on YouTube."}
        if self.browser_connector is not None:
            result = self.browser_connector.execute("search", query=query, engine="youtube")
            if isinstance(result, dict):
                return {**result, "action": "youtube_tools", "message": f"Opened YouTube search for {query}." if result.get("success") else result.get("message", "Could not open YouTube.")}
        return {"success": False, "action": "youtube_tools", "message": "YouTube browser connector is unavailable."}
