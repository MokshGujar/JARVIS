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

    def send_email(self, *, to: str, subject: str, body: str) -> dict:
        return self._unavailable("send_email")

    def create_draft(self, *, to: str, subject: str, body: str) -> dict:
        return self._unavailable("draft_email")

    def get_unread_count(self) -> dict:
        return self._unavailable("get_unread_count")

    def search_emails(self, *, query: str) -> dict:
        return self._unavailable("search_emails")

    def read_latest_email(self, *, from_email: str) -> dict:
        return self._unavailable("read_latest_email")

    def reply_latest_email(self, *, from_email: str, body: str) -> dict:
        return self._unavailable("reply_email")

    def _unavailable(self, action: str) -> dict:
        return {
            "success": False,
            "action": "gmail_unavailable",
            "requested_action": action,
            "message": "Gmail connector is not configured.",
            "status": "not_configured",
        }
