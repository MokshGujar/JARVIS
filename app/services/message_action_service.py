from __future__ import annotations

from typing import Dict

from app.connectors.message_action_connector import MessageActionConnector


class MessageActionService:
    """Compatibility facade for non-WhatsApp UI messaging actions.

    Canonical owner: WhatsAppTool for WhatsApp; future MessageTool for other apps.
    This facade remains for older imports/tests and delegates to MessageActionConnector;
    it is not the canonical execution boundary.
    """

    def __init__(self, connector: MessageActionConnector | None = None) -> None:
        self.connector = connector or MessageActionConnector()

    def available(self) -> bool:
        return self.connector.available()

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
        return self.connector.send(pending)

    def _normalize_whatsapp_phone(self, receiver: str) -> str:
        return self.connector._normalize_whatsapp_phone(receiver)
