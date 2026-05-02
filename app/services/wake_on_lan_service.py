from __future__ import annotations

import logging
import re
import socket

from config import WOL_BROADCAST_IP, WOL_MAC_ADDRESS, WOL_PORT

logger = logging.getLogger("J.A.R.V.I.S")


class WakeOnLanService:
    def __init__(
        self,
        mac_address: str | None = None,
        broadcast_ip: str | None = None,
        port: int | None = None,
    ):
        self.mac_address = WOL_MAC_ADDRESS if mac_address is None else mac_address.strip()
        self.broadcast_ip = WOL_BROADCAST_IP if broadcast_ip is None else broadcast_ip.strip()
        self.port = WOL_PORT if port is None else port

    def is_configured(self) -> bool:
        return bool(self.mac_address)

    def status(self) -> dict[str, str | bool | int]:
        return {
            "configured": self.is_configured(),
            "broadcast_ip": self.broadcast_ip,
            "port": self.port,
        }

    def looks_like_wake_request(self, message: str) -> bool:
        text = re.sub(r"\s+", " ", (message or "").strip().lower())
        if not text:
            return False

        patterns = (
            r"\b(turn on|wake|power on|start)\s+(my\s+)?(laptop|pc|computer)\b",
            r"\bwake up\s+(my\s+)?(laptop|pc|computer)\b",
        )
        return any(re.search(pattern, text) for pattern in patterns)

    def wake_laptop(self) -> dict[str, str | bool]:
        if not self.is_configured():
            return {
                "success": False,
                "action": "wake_laptop",
                "message": "Wake-on-LAN is not configured yet. Add WOL_MAC_ADDRESS in your .env first.",
            }

        try:
            packet = self._build_magic_packet(self.mac_address)
        except ValueError as exc:
            return {
                "success": False,
                "action": "wake_laptop",
                "message": str(exc),
            }

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                sock.sendto(packet, (self.broadcast_ip, self.port))

            logger.info("[WOL] Magic packet sent to configured MAC via %s:%d", self.broadcast_ip, self.port)
            return {
                "success": True,
                "action": "wake_laptop",
                "message": "Wake-on-LAN packet sent.",
            }
        except Exception as exc:
            logger.error("[WOL] Failed to send magic packet: %s", exc, exc_info=True)
            return {
                "success": False,
                "action": "wake_laptop",
                "message": f"Could not send the Wake-on-LAN packet: {exc}",
            }

    def _build_magic_packet(self, mac_address: str) -> bytes:
        cleaned = re.sub(r"[^0-9A-Fa-f]", "", mac_address)
        if len(cleaned) != 12:
            raise ValueError("WOL_MAC_ADDRESS must be a 12-hex-digit MAC address.")

        mac_bytes = bytes.fromhex(cleaned)
        return b"\xff" * 6 + mac_bytes * 16
