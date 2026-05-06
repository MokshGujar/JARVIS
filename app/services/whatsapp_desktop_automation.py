from __future__ import annotations

from typing import Any

from app.adapters.whatsapp.desktop_adapter import WhatsAppDesktopAdapter, WhatsAppDesktopResult


class WhatsAppDesktopAutomation:
    """Compatibility facade for WhatsApp Desktop automation.

    Canonical owner: WhatsAppTool.
    This facade remains for older imports/connectors and delegates to WhatsAppDesktopAdapter;
    it is not the canonical execution boundary.
    """

    def __init__(self, adapter: WhatsAppDesktopAdapter | None = None) -> None:
        self.adapter = adapter or WhatsAppDesktopAdapter()

    def build_send_uri(self, phone_number: str, message: str = "") -> str:
        return self.adapter.build_send_uri(phone_number, message)

    def open(self) -> dict[str, Any]:
        return self.adapter.open()

    def open_chat(self, phone_number: str, message: str = "") -> dict[str, Any]:
        return self.adapter.open_chat(phone_number, message)

    def send_message(self, phone_number: str, message: str) -> dict[str, Any]:
        return self.adapter.send_message(phone_number, message)

    def start_call(self, phone_number: str, mode: str) -> dict[str, Any]:
        return self.adapter.start_call(phone_number, mode)

    def end_call(self) -> dict[str, Any]:
        return self.adapter.end_call()

    def focus_window(self, timeout_seconds: int = 8) -> dict[str, Any]:
        return self.adapter.focus_window(timeout_seconds)

    def verify_chat_open(self, timeout_seconds: int = 5) -> bool:
        return self.adapter.verify_chat_open(timeout_seconds)

    def verify_send_control(self, timeout_seconds: int = 5) -> bool:
        return self.adapter.verify_send_control(timeout_seconds)

    def click_call_button(self, mode: str) -> bool:
        return self.adapter.click_call_button(mode)

    def verify_active_call(self, timeout_seconds: int = 8) -> bool:
        return self.adapter.verify_active_call(timeout_seconds)

    def click_end_call_button(self) -> bool:
        return self.adapter.click_end_call_button()
