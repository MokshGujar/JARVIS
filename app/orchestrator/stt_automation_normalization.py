from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class AutomationCommandNormalizationResult:
    original_text: str
    corrected_text: str
    corrections_applied: list[str] = field(default_factory=list)
    confidence: float = 1.0
    reason: str = ""
    suggested_correction: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "original_text": self.original_text,
            "corrected_text": self.corrected_text,
            "corrections_applied": list(self.corrections_applied),
            "confidence": self.confidence,
            "reason": self.reason,
            "suggested_correction": self.suggested_correction,
        }


def normalize_automation_command(text: str, context: Any = None) -> AutomationCommandNormalizationResult:
    original = str(text or "")
    corrected = original
    corrections: list[str] = []
    tokens = _context_tokens(context)
    lowered = original.lower().strip()

    corrected, wake_removed = _strip_wake_words(corrected)
    if wake_removed:
        corrections.append("wake_word_removed")
    corrected, filler_removed = _strip_request_fillers(corrected)
    if filler_removed:
        corrections.append("filler_removed")
    lowered = corrected.lower().strip()

    if _looks_like_file_edit_context(lowered, tokens):
        updated = re.sub(r"^\s*i'?ll\s+(put\b.+)$", r"\1", corrected, flags=re.I)
        if updated != corrected:
            corrected = updated
            lowered = corrected.lower().strip()
            corrections.append("remove_future_filler_file_context")

        updated = re.sub(r"^\s*port\s+(.+?\s+in\s+it)[.!?]*$", r"put \1", corrected, flags=re.I)
        if updated != corrected:
            corrected = updated
            lowered = corrected.lower().strip()
            corrections.append("port_to_put_file_context")

        updated = re.sub(r"\bwald\b", "world", corrected, flags=re.I)
        if updated != corrected and re.search(r"\b(?:put|write|add|append)\b.+\bin\s+it\b", updated, re.I):
            corrected = updated
            lowered = corrected.lower().strip()
            corrections.append("wald_to_world_file_context")

    uncertain = _uncertain_file_followup(lowered, tokens)
    if uncertain:
        return AutomationCommandNormalizationResult(
            original_text=original,
            corrected_text=corrected,
            corrections_applied=corrections,
            confidence=0.55,
            reason="uncertain_file_followup",
            suggested_correction="put world in it",
        )

    if _automation_context(tokens) and re.fullmatch(r"safe\s+it[.!?]*", lowered):
        corrected = re.sub(r"\bsafe\s+it\b", "save it", corrected, flags=re.I)
        corrections.append("safe_it_to_save_it")
    elif _ui_or_clipboard_context(tokens) and re.fullmatch(r"past\s+it[.!?]*", lowered):
        corrected = re.sub(r"\bpast\s+it\b", "paste it", corrected, flags=re.I)
        corrections.append("past_it_to_paste_it")
    elif _note_or_file_context(tokens) and re.match(r"^right\s+.+", lowered):
        corrected = re.sub(r"^right\b", "write", corrected, flags=re.I)
        corrections.append("right_to_write")
    elif _app_context(tokens) and re.fullmatch(r"open\s+crumb[.!?]*", lowered):
        corrected = re.sub(r"\bcrumb\b", "Chrome", corrected, flags=re.I)
        corrections.append("crumb_to_chrome")

    if corrections:
        return AutomationCommandNormalizationResult(
            original_text=original,
            corrected_text=corrected,
            corrections_applied=corrections,
            confidence=0.92,
            reason="automation_context_correction",
        )

    suggestion = None
    confidence = 1.0
    reason = "unchanged"
    if re.fullmatch(r"open\s+crumb[.!?]*", lowered):
        suggestion = re.sub(r"\bcrumb\b", "Chrome", original, flags=re.I)
        confidence = 0.55
        reason = "uncertain_app_name"

    return AutomationCommandNormalizationResult(
        original_text=original,
        corrected_text=original,
        corrections_applied=[],
        confidence=confidence,
        reason=reason,
        suggested_correction=suggestion,
    )


def _context_tokens(context: Any) -> set[str]:
    if context is None:
        return set()
    if isinstance(context, str):
        return {part for part in re.split(r"[^a-z0-9_]+", context.lower()) if part}
    if isinstance(context, (list, tuple, set)):
        return {str(item).strip().lower() for item in context if str(item).strip()}
    if isinstance(context, dict):
        values = set()
        for key, value in context.items():
            values.add(str(key).strip().lower())
            if isinstance(value, str):
                values.update(part for part in re.split(r"[^a-z0-9_]+", value.lower()) if part)
        return values

    values = set()
    for attr in ("active_app", "current_field_type", "last_semantic_intent", "pending_action_type"):
        value = getattr(context, attr, None)
        if value:
            values.update(part for part in re.split(r"[^a-z0-9_]+", str(value).lower()) if part)
    if getattr(context, "last_file_path", None) or getattr(context, "last_created_file_path", None):
        values.add("file")
    if getattr(context, "current_document_context", None):
        values.add("note")
        values.add("document")
    if getattr(context, "current_message_draft", None):
        values.add("communication")
    return values


def _automation_context(tokens: set[str]) -> bool:
    return bool(tokens & {"automation", "file", "note", "document", "ui", "clipboard", "browser", "app", "save_content"})


def _ui_or_clipboard_context(tokens: set[str]) -> bool:
    return bool(tokens & {"ui", "visible_ui", "clipboard", "paste", "editor", "browser", "field"})


def _note_or_file_context(tokens: set[str]) -> bool:
    return bool(tokens & {"note", "document", "file", "editor", "write_note", "save_content"})


def _app_context(tokens: set[str]) -> bool:
    return bool(tokens & {"app", "app_control", "browser", "chrome", "open_app"})


def _strip_wake_words(text: str) -> tuple[str, bool]:
    original = str(text or "")
    variants = r"(?:jarvis|javis|jawis|jais|jarwis|jarvish|jarris|jaris|jervis|javi|javier)"
    updated = re.sub(rf"^\s*(?:hello|hey|hi)?\s*{variants}\b[,\s]*", "", original, flags=re.I)
    updated = re.sub(rf"^\s*(?:hello|hey|hi)\s+{variants}\b[,\s]*", "", updated, flags=re.I)
    if _allows_trailing_wake_word_strip(updated):
        updated = re.sub(rf"[\s,]+{variants}[.!?]*\s*$", "", updated, flags=re.I)
    return updated, updated != original


def _allows_trailing_wake_word_strip(text: str) -> bool:
    cleaned = re.sub(r"\s+", " ", str(text or "").strip()).strip(" .!?")
    if not cleaned:
        return False
    command_prefixes = (
        "open",
        "launch",
        "start",
        "close",
        "focus",
        "switch to",
        "search",
        "google",
        "look up",
        "create",
        "make",
        "save",
        "put",
        "write",
        "add",
        "append",
        "delete",
        "remove",
        "read",
        "list",
        "show",
        "check",
        "take",
    )
    return cleaned.lower().startswith(command_prefixes)


def _strip_request_fillers(text: str) -> tuple[str, bool]:
    original = str(text or "")
    updated = original
    changed = False
    patterns = (
        r"^\s*(?:uh|um|okay|ok|now|bro)[,\s]+",
        r"^\s*(?:please\s+)?(?:can|could)\s+you\s+",
        r"^\s*please\s+",
        r"^\s*(?:okay|ok|now|bro)[,\s]+",
    )
    while True:
        before = updated
        for pattern in patterns:
            updated = re.sub(pattern, "", updated, flags=re.I)
        if updated == before:
            break
        changed = True
    return updated, changed


def _looks_like_file_edit_context(lowered: str, tokens: set[str]) -> bool:
    if _note_or_file_context(tokens):
        return True
    return bool(re.search(r"\b(?:put|port|write|add|append|create|make|save)\b", lowered) and re.search(r"\b(?:file|it|desktop|documents)\b", lowered))


def _uncertain_file_followup(lowered: str, tokens: set[str]) -> bool:
    cleaned = re.sub(r"\s+", " ", lowered).strip(" .!?")
    if cleaned == "port waldenet":
        return True
    if re.match(r"^i'?ll put wald in it$", cleaned):
        return not _note_or_file_context(tokens)
    return False
