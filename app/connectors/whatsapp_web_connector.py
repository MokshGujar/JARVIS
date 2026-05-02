from __future__ import annotations

from typing import Any


class WhatsAppWebConnector:
    def __init__(self, browser_control_service: Any) -> None:
        self.browser_control_service = browser_control_service

    def open(self, *, timeout: int = 20) -> dict[str, Any]:
        return self.browser_control_service.execute("go_to", url="https://web.whatsapp.com", timeout=timeout)

    def login_state(self, *, timeout: int = 12) -> dict[str, Any]:
        return self.browser_control_service.execute("whatsapp_logged_in", timeout=timeout)
