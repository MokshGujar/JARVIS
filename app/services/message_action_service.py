from __future__ import annotations

import time
import webbrowser
import re
from typing import Dict
from urllib.parse import quote

try:
    import pyautogui
    PYAUTOGUI_IMPORT_ERROR = None
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.08
except Exception as exc:  # pragma: no cover
    pyautogui = None
    PYAUTOGUI_IMPORT_ERROR = exc


class MessageActionService:
    """UI-based messaging actions. Sending is performed only after confirmation."""

    def available(self) -> bool:
        return pyautogui is not None

    def prepare(self, platform: str, receiver: str, message: str) -> Dict[str, str | bool | dict]:
        platform = (platform or "whatsapp").strip().lower()
        receiver = (receiver or "").strip()
        message = (message or "").strip()
        if not receiver or not message:
            return {"success": False, "action": "send_message_pending", "message": "Tell me the receiver and the message text."}
        return {
            "success": False,
            "action": "send_message_pending",
            "message": f"Ready to send this via {platform} to {receiver}: \"{message}\". Say yes to send or no to cancel.",
            "pending": {"platform": platform, "receiver": receiver, "message": message},
        }

    def send(self, pending: dict) -> Dict[str, str | bool]:
        if not self.available():
            return {"success": False, "action": "send_message_sent", "message": f"Message sending is unavailable. Import error: {PYAUTOGUI_IMPORT_ERROR}"}
        platform = (pending.get("platform") or "whatsapp").lower()
        receiver = pending.get("receiver") or ""
        message = pending.get("message") or ""
        try:
            if "whatsapp" in platform:
                phone_number = self._normalize_whatsapp_phone(receiver)
                if not phone_number:
                    return {
                        "success": False,
                        "action": "send_message_sent",
                        "message": (
                            "WhatsApp Web auto-send needs an explicit phone number. "
                            "Named WhatsApp contacts are handled through the Android phone companion."
                        ),
                    }
                url = f"https://web.whatsapp.com/send?phone={phone_number}&text={quote(message)}"
                webbrowser.open(url)
                time.sleep(3.0)
                pyautogui.press("enter")
                return {"success": True, "action": "send_message_sent", "message": f"Sent the WhatsApp message to {receiver}."}
            if "telegram" in platform:
                pyautogui.press("win")
                time.sleep(0.4)
                pyautogui.write("Telegram", interval=0.04)
                pyautogui.press("enter")
                time.sleep(1.5)
                pyautogui.hotkey("ctrl", "f")
                pyautogui.write(receiver, interval=0.04)
                pyautogui.press("enter")
                time.sleep(0.8)
                pyautogui.write(message, interval=0.03)
                pyautogui.press("enter")
                return {"success": True, "action": "send_message_sent", "message": f"Sent the Telegram message to {receiver}."}
            if "instagram" in platform or "insta" in platform:
                webbrowser.open("https://www.instagram.com/direct/new/")
                return {"success": True, "action": "send_message_sent", "message": "Opened Instagram DMs. Please choose the recipient and send manually."}
            return {"success": False, "action": "send_message_sent", "message": f"Sending via {platform} is not supported yet."}
        except Exception as exc:
            return {"success": False, "action": "send_message_sent", "message": f"Could not send the message: {exc}"}

    def _normalize_whatsapp_phone(self, receiver: str) -> str:
        receiver = (receiver or "").strip()
        digits = re.sub(r"\D", "", receiver)
        if not digits:
            return ""
        if len(digits) < 8:
            return ""
        if not re.search(r"\d", receiver):
            return ""
        return digits
