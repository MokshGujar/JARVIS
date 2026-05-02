from __future__ import annotations

from typing import Any


class BrowserConnector:
    def __init__(self, browser_control_service: Any) -> None:
        self.browser_control_service = browser_control_service

    def execute(self, action: str, **params) -> dict[str, Any]:
        return self.browser_control_service.execute(action, **params)
