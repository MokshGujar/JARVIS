from __future__ import annotations

from typing import Any

from app.services.whatsapp_desktop_automation import WhatsAppDesktopAutomation


class WhatsAppDesktopConnector:
    def __init__(self, automation: Any | None = None) -> None:
        self.automation = automation or WhatsAppDesktopAutomation()

    def open(self) -> dict[str, Any]:
        return self.automation.open()

    def send_message(self, phone_number: str, message: str) -> dict[str, Any]:
        return self.automation.send_message(phone_number, message)

    def start_call(self, phone_number: str, mode: str) -> dict[str, Any]:
        return self.automation.start_call(phone_number, mode)

    def end_call(self) -> dict[str, Any]:
        return self.automation.end_call()

    def click_call_button(self, mode: str) -> bool:
        return bool(self.automation.click_call_button(mode))
