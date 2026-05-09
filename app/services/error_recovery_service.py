from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any
import re


@dataclass(frozen=True, slots=True)
class RecoveryMessage:
    code: str
    what_failed: str
    why: str
    next_step: str
    retry_possible: bool = True

    @property
    def message(self) -> str:
        retry = " You can retry after that." if self.retry_possible else ""
        return f"{self.what_failed} {self.why} {self.next_step}{retry}".strip()

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["message"] = self.message
        return payload


class ErrorRecoveryService:
    def recover(self, code: str, *, target: str = "", detail: str = "") -> RecoveryMessage:
        normalized = str(code or "").strip().lower()
        safe_target = _redact(target)
        safe_detail = _redact(detail)
        if normalized == "contact_not_found":
            return RecoveryMessage("contact_not_found", f"I couldn't find {safe_target or 'that contact'} in contacts.", "The contact resolver has no confident match.", "Sync phone contacts or type the number/email.")
        if normalized == "gmail_not_configured":
            return RecoveryMessage("gmail_not_configured", "Gmail is not configured.", "The Gmail connector is fail-closed.", "Connect Gmail OAuth first.")
        if normalized == "whatsapp_selector_missing":
            return RecoveryMessage("whatsapp_selector_missing", "WhatsApp opened, but I could not find the message box.", safe_detail or "The UI selector was not available.", "Open the chat once and try again.")
        if normalized == "file_query_missing":
            return RecoveryMessage("file_query_missing", "I can search your laptop, but I need a filename or keyword.", "No searchable query was provided.", "Tell me what to search for.")
        if normalized == "ambiguous_file":
            return RecoveryMessage("ambiguous_file", "I found multiple matching files.", safe_detail or "There is not enough context to choose one.", "Tell me which result to use.")
        if normalized == "ambiguous_contact":
            return RecoveryMessage("ambiguous_contact", "I found multiple matching contacts.", safe_detail or "There is not enough confidence to choose one.", "Confirm the exact contact.")
        if normalized == "protected_destructive_action":
            return RecoveryMessage("protected_destructive_action", "This action is protected because it can delete or damage data.", "Policy requires confirmation and protected authorization.", "Confirm only if you really want to continue.", retry_possible=False)
        if normalized == "unsupported_document_type":
            return RecoveryMessage("unsupported_document_type", "I cannot read that document type yet.", safe_detail or "The optional parser is unavailable.", "Install the required parser or convert the file to TXT/MD/CSV.")
        return RecoveryMessage(normalized or "unknown_error", "That action failed.", safe_detail or "The tool returned an error.", "Try again or ask for setup blockers.")


def _redact(value: str) -> str:
    text = str(value or "")
    text = re.sub(r"[\w.\-+]+@[\w.\-]+\.\w+", "[email]", text)
    text = re.sub(r"\+?\d[\d\s().-]{6,}\d", "[phone]", text)
    return text.strip()
