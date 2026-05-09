from __future__ import annotations

import re
from typing import Any

from app.connectors.gmail_connector import GmailConnector
from app.tools.tool_inventory import get_tool_inventory, get_tool_inventory_record
from config import (
    FACE_GATE_ENABLED,
    JARVIS_AGENT_MODE,
    JARVIS_DEVELOPER_MODE,
    JARVIS_ENABLE_LANGGRAPH_AGENTS,
)


class CapabilitySummaryService:
    """Deterministic capability answers built from runtime metadata."""

    _GENERAL_PATTERNS = (
        re.compile(r"\bwhat can you do\b", re.IGNORECASE),
        re.compile(r"\bwhat tools do you have\b", re.IGNORECASE),
        re.compile(r"\bwhat is enabled\b", re.IGNORECASE),
        re.compile(r"\bwhat's enabled\b", re.IGNORECASE),
    )
    _LAPTOP_PATTERNS = (
        re.compile(r"\bcan you access my laptop\b", re.IGNORECASE),
        re.compile(r"\bcan you search my laptop\b", re.IGNORECASE),
        re.compile(r"\bcan you search (?:a )?file\b", re.IGNORECASE),
    )
    _EMAIL_PATTERNS = (
        re.compile(r"\bcan you (?:send|use|access).*(?:email|gmail|mail)\b", re.IGNORECASE),
        re.compile(r"\bcan you send email\b", re.IGNORECASE),
    )
    _WHATSAPP_PATTERNS = (
        re.compile(r"\bcan you use whatsapp\b", re.IGNORECASE),
        re.compile(r"\bcan you send whatsapp\b", re.IGNORECASE),
    )
    _TERMINAL_PATTERNS = (
        re.compile(r"\bcan you run terminal commands\b", re.IGNORECASE),
        re.compile(r"\bcan you run (?:shell|cmd|powershell) commands\b", re.IGNORECASE),
        re.compile(r"\bcan you execute code\b", re.IGNORECASE),
    )

    def __init__(
        self,
        *,
        gmail_connector: Any | None = None,
        phone_command_service: Any | None = None,
        reminder_service: Any | None = None,
        research_tools_service: Any | None = None,
        vision_service: Any | None = None,
    ) -> None:
        self.gmail_connector = gmail_connector or GmailConnector()
        self.phone_command_service = phone_command_service
        self.reminder_service = reminder_service
        self.research_tools_service = research_tools_service
        self.vision_service = vision_service

    def looks_like_request(self, message: str) -> bool:
        text = _normalized(message)
        if not text:
            return False
        return any(pattern.search(text) for pattern in (
            *self._GENERAL_PATTERNS,
            *self._LAPTOP_PATTERNS,
            *self._EMAIL_PATTERNS,
            *self._WHATSAPP_PATTERNS,
            *self._TERMINAL_PATTERNS,
        ))

    def answer(self, message: str) -> str:
        text = _normalized(message)
        snapshot = self.snapshot()
        if any(pattern.search(text) for pattern in self._LAPTOP_PATTERNS):
            return self._laptop_answer(snapshot)
        if any(pattern.search(text) for pattern in self._EMAIL_PATTERNS):
            return self._email_answer(snapshot)
        if any(pattern.search(text) for pattern in self._WHATSAPP_PATTERNS):
            return self._whatsapp_answer(snapshot)
        if any(pattern.search(text) for pattern in self._TERMINAL_PATTERNS):
            return self._terminal_answer(snapshot)
        return self._general_answer(snapshot)

    def snapshot(self) -> dict[str, Any]:
        records = {record.name: record for record in get_tool_inventory()}
        gmail_status = self._gmail_status()
        phone_status = self._phone_status()
        return {
            "local_files": _record_available(records.get("file")),
            "apps": _record_available(records.get("app")),
            "browser": _record_available(records.get("browser")),
            "system": _record_available(records.get("system")),
            "whatsapp": _record_available(records.get("whatsapp")),
            "gmail": gmail_status,
            "phone_bridge": phone_status,
            "face_gate": {"enabled": bool(FACE_GATE_ENABLED)},
            "reminders": {"available": bool(self.reminder_service)},
            "research": {"available": bool(self.research_tools_service and _record_available(records.get("research"))["available"])},
            "vision": {"available": bool(self.vision_service and _record_available(records.get("vision"))["available"])},
            "langgraph": {"enabled": bool(JARVIS_ENABLE_LANGGRAPH_AGENTS)},
            "developer_mode": {"enabled": bool(JARVIS_DEVELOPER_MODE)},
            "agent_mode": {"enabled": bool(JARVIS_AGENT_MODE)},
            "terminal": {
                "available": False,
                "status": "proposal_only" if not JARVIS_DEVELOPER_MODE else "policy_gated",
                "developer_mode_enabled": bool(JARVIS_DEVELOPER_MODE),
            },
            "tool_records": {
                name: {
                    "current_status": record.current_status,
                    "status": record.status,
                    "routing_mode": record.routing_mode,
                    "actions": list(record.supported_actions),
                }
                for name, record in records.items()
            },
        }

    def _general_answer(self, snapshot: dict[str, Any]) -> str:
        available: list[str] = []
        if snapshot["local_files"]["available"]:
            available.append("search and read local files")
        if snapshot["apps"]["available"]:
            available.append("open apps")
        if snapshot["browser"]["available"]:
            available.append("control browser searches")
        if snapshot["system"]["available"]:
            available.append("show safe system status")
        if snapshot["reminders"]["available"]:
            available.append("manage reminders")
        if snapshot["whatsapp"]["available"]:
            available.append("use WhatsApp when contacts resolve and policy allows")

        unavailable: list[str] = []
        if not snapshot["gmail"]["available"]:
            unavailable.append("Gmail is not configured")
        unavailable.append(
            "Terminal execution is proposal-only"
            if not snapshot["developer_mode"]["enabled"]
            else "Terminal execution is policy-gated"
        )
        unavailable.append(
            "LangGraph agents are enabled"
            if snapshot["langgraph"]["enabled"]
            else "LangGraph agents are disabled"
        )

        return f"I can {', '.join(available)}. {'; '.join(unavailable)}."

    def _laptop_answer(self, snapshot: dict[str, Any]) -> str:
        parts = []
        if snapshot["local_files"]["available"]:
            parts.append("search and read local laptop files")
        if snapshot["apps"]["available"]:
            parts.append("open local apps")
        if snapshot["browser"]["available"]:
            parts.append("control browser searches")
        if snapshot["system"]["available"]:
            parts.append("show safe system status")
        if not parts:
            return "Laptop access is not enabled right now."
        return f"Yes. I can {', '.join(parts)}. Destructive actions stay protected by policy."

    def _email_answer(self, snapshot: dict[str, Any]) -> str:
        gmail = snapshot["gmail"]
        if not gmail["available"]:
            return "Gmail is unavailable right now: Gmail connector is not configured."
        return "Yes. Gmail is available for unread counts, search, drafts, and policy-gated sends."

    def _whatsapp_answer(self, snapshot: dict[str, Any]) -> str:
        if not snapshot["whatsapp"]["available"]:
            return "WhatsApp is not available as an executable tool right now."
        return "Yes. I can use WhatsApp when the contact resolves clearly; sends and calls remain protected by policy."

    def _terminal_answer(self, snapshot: dict[str, Any]) -> str:
        if snapshot["developer_mode"]["enabled"]:
            return "Terminal commands are policy-gated in Developer Mode, and destructive commands remain blocked."
        return "Terminal execution is proposal-only. Developer Mode is disabled."

    def _gmail_status(self) -> dict[str, Any]:
        try:
            status = self.gmail_connector.status()
        except Exception:
            status = {"available": False, "status": "unknown", "message": "Gmail status could not be checked."}
        return {
            "available": bool(status.get("available")),
            "status": str(status.get("status") or "unknown"),
            "message": str(status.get("message") or ""),
        }

    def _phone_status(self) -> dict[str, Any]:
        if not self.phone_command_service:
            return {"available": False, "status": "not_configured", "has_known_device": False}
        try:
            status = self.phone_command_service.get_device_status()
        except Exception:
            return {"available": False, "status": "unknown", "has_known_device": False}
        has_known_device = bool(status.get("has_known_device"))
        return {
            "available": has_known_device,
            "status": "available" if has_known_device else "setup_required",
            "has_known_device": has_known_device,
        }


def _record_available(record: Any | None) -> dict[str, Any]:
    if record is None:
        return {"available": False, "status": "missing"}
    current_status = str(getattr(record, "current_status", "") or "")
    return {
        "available": current_status in {"live_routed", "thin_wrapper"},
        "status": current_status or "unknown",
    }


def _normalized(message: str) -> str:
    return " ".join(str(message or "").strip().lower().split()).strip(" .!?")
