from __future__ import annotations

import os
import re
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any

try:
    import pyautogui
    PYAUTOGUI_IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover
    pyautogui = None
    PYAUTOGUI_IMPORT_ERROR = exc

try:
    import pygetwindow
    PYGETWINDOW_IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover
    pygetwindow = None
    PYGETWINDOW_IMPORT_ERROR = exc

try:
    from pywinauto import Desktop
    PYWINAUTO_IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover
    Desktop = None
    PYWINAUTO_IMPORT_ERROR = exc


@dataclass(slots=True)
class WhatsAppDesktopResult:
    success: bool
    status: str
    message: str
    details: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "status": self.status,
            "message": self.message,
            "details": self.details or {},
        }


class WhatsAppDesktopAutomation:
    WINDOW_RE = re.compile(r"(whatsapp)", re.IGNORECASE)

    def build_send_uri(self, phone_number: str, message: str = "") -> str:
        phone = self._normalize_phone(phone_number)
        encoded = urllib.parse.quote(message or "")
        return f"whatsapp://send?phone={phone}&text={encoded}"

    def open(self) -> dict[str, Any]:
        try:
            os.startfile("whatsapp://")  # type: ignore[attr-defined]
        except Exception as exc:
            return WhatsAppDesktopResult(False, "whatsapp_desktop_unavailable", f"WhatsApp Desktop could not be launched: {exc}").as_dict()
        return self.focus_window(timeout_seconds=8)

    def open_chat(self, phone_number: str, message: str = "") -> dict[str, Any]:
        phone = self._normalize_phone(phone_number)
        if not phone:
            return WhatsAppDesktopResult(False, "whatsapp_missing_phone", "The contact has no phone number for WhatsApp Desktop.").as_dict()
        uri = self.build_send_uri(phone, message)
        try:
            os.startfile(uri)  # type: ignore[attr-defined]
        except Exception as exc:
            return WhatsAppDesktopResult(False, "whatsapp_desktop_unavailable", f"WhatsApp Desktop deep link failed: {exc}", {"uri": uri}).as_dict()
        focused = self.focus_window(timeout_seconds=10)
        if not focused.get("success"):
            return focused
        if not self.verify_chat_open(timeout_seconds=8):
            return WhatsAppDesktopResult(False, "whatsapp_chat_unverified", "WhatsApp opened, but Jarvis could not verify the target chat.").as_dict()
        return WhatsAppDesktopResult(True, "whatsapp_chat_open", "WhatsApp target chat is open.", {"uri": uri}).as_dict()

    def send_message(self, phone_number: str, message: str) -> dict[str, Any]:
        opened = self.open_chat(phone_number, message)
        if not opened.get("success"):
            return opened
        if not self.verify_send_control(timeout_seconds=5):
            return WhatsAppDesktopResult(False, "whatsapp_send_unverified", "Jarvis could not verify the WhatsApp send control. I did not send the message.").as_dict()
        if pyautogui is None:
            return WhatsAppDesktopResult(False, "whatsapp_ui_unavailable", f"pyautogui is unavailable: {PYAUTOGUI_IMPORT_ERROR}").as_dict()
        pyautogui.press("enter")
        time.sleep(0.7)
        if not self.verify_chat_open(timeout_seconds=3):
            return WhatsAppDesktopResult(False, "whatsapp_send_unverified", "Jarvis could not verify WhatsApp after pressing send.").as_dict()
        return WhatsAppDesktopResult(True, "whatsapp_message_sent", "WhatsApp message sent.").as_dict()

    def start_call(self, phone_number: str, mode: str) -> dict[str, Any]:
        opened = self.open_chat(phone_number, "")
        if not opened.get("success"):
            return opened
        mode = "video" if str(mode).lower() == "video" else "voice"
        if not self.click_call_button(mode):
            return WhatsAppDesktopResult(False, "whatsapp_desktop_unverified", f"Jarvis could not verify the WhatsApp {mode} call button. I did not start the call.").as_dict()
        if not self.verify_active_call(timeout_seconds=10):
            return WhatsAppDesktopResult(False, "whatsapp_call_unverified", "Jarvis clicked the call control, but could not verify that the call UI appeared.").as_dict()
        return WhatsAppDesktopResult(True, "whatsapp_calling", "WhatsApp call started.").as_dict()

    def end_call(self) -> dict[str, Any]:
        focused = self.focus_window(timeout_seconds=5)
        if not focused.get("success"):
            return focused
        if not self.verify_active_call(timeout_seconds=2):
            return WhatsAppDesktopResult(False, "whatsapp_end_call_unverified", "Jarvis could not verify an active WhatsApp call. I did not click anything.").as_dict()
        if not self.click_end_call_button():
            return WhatsAppDesktopResult(False, "whatsapp_end_call_unverified", "Jarvis could not verify the WhatsApp end-call button. I did not click anything.").as_dict()
        return WhatsAppDesktopResult(True, "whatsapp_call_ended", "Ended the WhatsApp call.").as_dict()

    def focus_window(self, timeout_seconds: int = 8) -> dict[str, Any]:
        deadline = time.time() + timeout_seconds
        last_error = ""
        while time.time() <= deadline:
            try:
                window = self._find_window()
                if window is not None:
                    try:
                        window.activate()
                    except Exception:
                        pass
                    return WhatsAppDesktopResult(True, "whatsapp_window_focused", "WhatsApp Desktop is focused.").as_dict()
            except Exception as exc:
                last_error = str(exc)
            time.sleep(0.3)
        return WhatsAppDesktopResult(False, "whatsapp_window_unverified", f"Jarvis could not verify a WhatsApp Desktop window. {last_error}".strip()).as_dict()

    def verify_chat_open(self, timeout_seconds: int = 5) -> bool:
        return self._window_exists(timeout_seconds)

    def verify_send_control(self, timeout_seconds: int = 5) -> bool:
        if Desktop is None:
            return False
        deadline = time.time() + timeout_seconds
        while time.time() <= deadline:
            try:
                app_window = Desktop(backend="uia").window(title_re=".*WhatsApp.*")
                controls = app_window.descendants()
                labels = " ".join(str(getattr(control, "window_text", lambda: "")()) for control in controls[:200]).lower()
                if "send" in labels or "message" in labels:
                    return True
            except Exception:
                if self._window_exists(1):
                    return True
            time.sleep(0.25)
        return False

    def click_call_button(self, mode: str) -> bool:
        if Desktop is None:
            return False
        keywords = ("video",) if mode == "video" else ("voice", "audio", "call")
        try:
            app_window = Desktop(backend="uia").window(title_re=".*WhatsApp.*")
            for control in app_window.descendants():
                text = str(getattr(control, "window_text", lambda: "")()).lower()
                automation_id = str(getattr(control, "automation_id", lambda: "")()).lower()
                combined = f"{text} {automation_id}"
                if any(keyword in combined for keyword in keywords) and "call" in combined:
                    control.click_input()
                    return True
        except Exception:
            return False
        return False

    def verify_active_call(self, timeout_seconds: int = 8) -> bool:
        if Desktop is None:
            return False
        deadline = time.time() + timeout_seconds
        while time.time() <= deadline:
            try:
                app_window = Desktop(backend="uia").window(title_re=".*WhatsApp.*")
                labels = " ".join(str(getattr(control, "window_text", lambda: "")()) for control in app_window.descendants()[:240]).lower()
                if "end call" in labels or "calling" in labels or "ringing" in labels:
                    return True
            except Exception:
                pass
            time.sleep(0.4)
        return False

    def click_end_call_button(self) -> bool:
        if Desktop is None:
            return False
        try:
            app_window = Desktop(backend="uia").window(title_re=".*WhatsApp.*")
            for control in app_window.descendants():
                text = str(getattr(control, "window_text", lambda: "")()).lower()
                automation_id = str(getattr(control, "automation_id", lambda: "")()).lower()
                if "end call" in f"{text} {automation_id}" or "hang up" in f"{text} {automation_id}":
                    control.click_input()
                    return True
        except Exception:
            return False
        return False

    def _find_window(self):
        if pygetwindow is None:
            return None
        for window in pygetwindow.getAllWindows():
            title = getattr(window, "title", "") or ""
            if self.WINDOW_RE.search(title):
                return window
        return None

    def _window_exists(self, timeout_seconds: int) -> bool:
        deadline = time.time() + timeout_seconds
        while time.time() <= deadline:
            if self._find_window() is not None:
                return True
            time.sleep(0.25)
        return False

    def _normalize_phone(self, value: str) -> str:
        text = (value or "").strip()
        if not text:
            return ""
        if text.startswith("+"):
            return "+" + re.sub(r"\D", "", text[1:])
        return re.sub(r"\D", "", text)
