from __future__ import annotations

import re
import time
from typing import Any, Callable

from app.connectors.gmail_connector import GmailConnector
from app.state.runtime_state import RuntimeStateStore, get_runtime_state_store


NOTIFICATION_TYPES = {
    "reminder_due",
    "task_pending",
    "automation_failed",
    "clarification_required",
    "communication_failed",
    "setup_required",
    "agent_report",
    "system_alert",
}


class NotificationCenterService:
    _REQUEST_PATTERNS = (
        re.compile(r"\bwhat needs my attention\b", re.IGNORECASE),
        re.compile(r"\bshow pending actions\b", re.IGNORECASE),
        re.compile(r"\bwhat failed today\b", re.IGNORECASE),
        re.compile(r"\bshow my reminders\b", re.IGNORECASE),
        re.compile(r"\bshow failed actions\b", re.IGNORECASE),
        re.compile(r"\bclear completed notifications\b", re.IGNORECASE),
        re.compile(r"\bshow setup blockers\b", re.IGNORECASE),
    )

    def __init__(
        self,
        *,
        store: RuntimeStateStore | None = None,
        gmail_connector: Any | None = None,
        reminder_service: Any | None = None,
        whatsapp_status_provider: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        self.store = store or get_runtime_state_store()
        self.gmail_connector = gmail_connector or GmailConnector()
        self.reminder_service = reminder_service
        self.whatsapp_status_provider = whatsapp_status_provider

    def looks_like_request(self, message: str) -> bool:
        text = " ".join(str(message or "").strip().lower().split())
        return bool(text and any(pattern.search(text) for pattern in self._REQUEST_PATTERNS))

    def handle_request(self, message: str) -> dict[str, Any]:
        text = " ".join(str(message or "").strip().lower().split())
        if "clear completed notifications" in text:
            count = self.clear_completed()
            return self._response(f"Cleared {count} completed or stale notification(s).", action="clear_completed")
        if "setup blocker" in text:
            blockers = self.setup_blockers()
            return self._response(self._format_items(blockers, empty="No setup blockers found."), action="show_setup_blockers", items=blockers)
        if "reminders" in text:
            reminders = self.due_reminder_notifications()
            return self._response(self._format_items(reminders, empty="No due reminders right now."), action="show_reminders", items=reminders)
        if "failed" in text:
            failures = self.list_notifications(statuses=("failed", "stale"), notification_types=("automation_failed", "communication_failed"))
            return self._response(self._format_items(failures, empty="No failed actions found."), action="show_failed_actions", items=failures)

        items = self.attention_items()
        return self._response(self._format_items(items, empty="Nothing needs your attention right now."), action="show_attention", items=items)

    def add_notification(
        self,
        notification_type: str,
        *,
        title: str,
        message: str,
        status: str = "pending",
        source: str = "",
        metadata: dict[str, Any] | None = None,
        expires_at: float | None = None,
    ) -> str:
        kind = str(notification_type or "").strip()
        if kind not in NOTIFICATION_TYPES:
            raise ValueError(f"unsupported notification type: {kind}")
        return self.store.add_notification(
            notification_type=kind,
            title=self._redact(title),
            message=self._redact(message),
            status=status,
            source=source,
            metadata=self._redact_metadata(metadata or {}),
            expires_at=expires_at,
        )

    def add_failed_action(self, *, title: str, message: str, source: str = "", metadata: dict[str, Any] | None = None) -> str:
        return self.add_notification(
            "automation_failed",
            title=title,
            message=message,
            status="failed",
            source=source,
            metadata=metadata,
        )

    def list_notifications(
        self,
        *,
        statuses: tuple[str, ...] = ("pending", "failed", "stale"),
        notification_types: tuple[str, ...] | None = None,
    ) -> list[dict[str, Any]]:
        return self.store.list_notifications(statuses=statuses, notification_types=notification_types)

    def clear_completed(self) -> int:
        return self.store.clear_notifications(statuses=("completed", "stale", "cleared"))

    def attention_items(self) -> list[dict[str, Any]]:
        items = self.list_notifications(statuses=("pending", "failed", "stale"))
        return [*self.setup_blockers(), *items]

    def due_reminder_notifications(self) -> list[dict[str, Any]]:
        if not self.reminder_service:
            return []
        try:
            reminders = self.reminder_service.get_due_reminders()
        except Exception:
            return []
        items = []
        for reminder in reminders:
            message = str(reminder.get("message") or "Reminder due").strip()
            items.append({
                "notification_type": "reminder_due",
                "status": "pending",
                "title": "Reminder due",
                "message": self._redact(message),
                "source": "reminder_service",
                "metadata": {"reminder_id": str(reminder.get("id") or "")},
            })
        return items

    def setup_blockers(self) -> list[dict[str, Any]]:
        blockers: list[dict[str, Any]] = []
        gmail_status = self._gmail_status()
        if not gmail_status.get("available"):
            blockers.append({
                "notification_type": "setup_required",
                "status": "pending",
                "title": "Gmail setup required",
                "message": str(gmail_status.get("message") or "Connect Gmail OAuth before using Gmail actions."),
                "source": "gmail",
                "metadata": {"status": gmail_status.get("status") or "not_configured"},
            })

        if self.whatsapp_status_provider:
            try:
                whatsapp_status = self.whatsapp_status_provider() or {}
            except Exception:
                whatsapp_status = {"available": False, "status": "unknown", "message": "WhatsApp status could not be checked."}
            if not bool(whatsapp_status.get("available", True)):
                blockers.append({
                    "notification_type": "setup_required",
                    "status": "pending",
                    "title": "WhatsApp setup required",
                    "message": str(whatsapp_status.get("message") or "Open WhatsApp and sign in before retrying."),
                    "source": "whatsapp",
                    "metadata": {"status": whatsapp_status.get("status") or "setup_required"},
                })
        return blockers

    def _gmail_status(self) -> dict[str, Any]:
        try:
            status = self.gmail_connector.status()
        except Exception:
            status = {"available": False, "status": "unknown", "message": "Gmail status could not be checked."}
        return {
            "available": bool(status.get("available")),
            "status": str(status.get("status") or "unknown"),
            "message": str(status.get("message") or "Gmail is not configured."),
        }

    @staticmethod
    def _format_items(items: list[dict[str, Any]], *, empty: str) -> str:
        if not items:
            return empty
        lines = []
        for item in items[:8]:
            title = str(item.get("title") or item.get("notification_type") or "Notification").strip()
            message = str(item.get("message") or "").strip()
            lines.append(f"{title}: {message}" if message else title)
        return "\n".join(lines)

    @staticmethod
    def _response(message: str, *, action: str, items: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        return {
            "success": True,
            "action": action,
            "message": message,
            "items": items or [],
        }

    @classmethod
    def _redact(cls, value: str) -> str:
        text = str(value or "")
        text = re.sub(r"[\w.\-+]+@[\w.\-]+\.\w+", "[email]", text)
        text = re.sub(r"\+?\d[\d\s().-]{6,}\d", "[phone]", text)
        return text.strip()

    @classmethod
    def _redact_metadata(cls, metadata: dict[str, Any]) -> dict[str, Any]:
        redacted: dict[str, Any] = {}
        for key, value in metadata.items():
            if isinstance(value, str):
                redacted[key] = cls._redact(value)
            elif isinstance(value, (int, float, bool)) or value is None:
                redacted[key] = value
            else:
                redacted[key] = str(type(value).__name__)
        redacted.setdefault("redacted_at", int(time.time()))
        return redacted
