from __future__ import annotations


class GmailConnector:
    def available(self) -> bool:
        return False

    def status(self) -> dict:
        return {
            "available": False,
            "status": "not_configured",
            "message": "Gmail connector is not configured.",
        }
