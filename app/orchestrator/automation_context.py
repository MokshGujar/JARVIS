from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from config import (
    AUTOMATION_CONTEXT_REDACT_SENSITIVE,
    AUTOMATION_CONTEXT_TTL_SECONDS,
    AUTOMATION_DUPLICATE_WINDOW_SECONDS,
)
from app.orchestrator.semantic_automation import SemanticAutomationAction, SemanticAutomationIntent


SENSITIVE_PATTERNS = (
    re.compile(r"\b(?:password|passcode|otp|api\s*key|access\s*token|secret|private\s*key)\b\s*[:=]?\s*\S+", re.I),
    re.compile(r"\b(?:sk|pk|ghp|xoxb|xoxp|ya29)\-[A-Za-z0-9_\-]{12,}\b"),
    re.compile(r"-----BEGIN\s+(?:RSA\s+|OPENSSH\s+|EC\s+)?PRIVATE\s+KEY-----[\s\S]*?-----END\s+(?:RSA\s+|OPENSSH\s+|EC\s+)?PRIVATE\s+KEY-----", re.I),
    re.compile(r"\b\d{4,8}\b(?=.*\b(?:otp|code|verification)\b)", re.I),
)

YES_CONFIRMATIONS = {"yes", "y", "do it", "confirm", "send it", "delete it", "go ahead", "proceed"}
NO_CONFIRMATIONS = {"no", "n", "cancel", "don't", "dont", "do not", "never mind", "stop"}
NON_MUTATING_INTENTS = {
    "READ_ACTIVE_WINDOW",
    "SEARCH_WEB",
    "READ_SCREEN_OR_WINDOW",
    "EXPLAIN_ERROR_ON_SCREEN",
}


@dataclass(slots=True)
class PendingConfirmation:
    confirmation_id: str
    semantic_action: str
    tool_plan: dict[str, Any] = field(default_factory=dict)
    action: str = ""
    target: str | None = None
    content: str | None = None
    recipient: str | None = None
    safety_level: str = "LOW"
    requires_voice_permission: bool = False
    created_at: float = field(default_factory=time.time)
    expires_at: float = 0.0
    status: str = "pending"

    def is_expired(self, now: float | None = None) -> bool:
        current = time.time() if now is None else now
        return bool(self.expires_at and current >= self.expires_at)

    def as_dict(self) -> dict[str, Any]:
        return {
            "confirmation_id": self.confirmation_id,
            "semantic_action": self.semantic_action,
            "tool_plan": dict(self.tool_plan),
            "action": self.action,
            "target": self.target,
            "content": self.content,
            "recipient": self.recipient,
            "safety_level": self.safety_level,
            "requires_voice_permission": self.requires_voice_permission,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "status": self.status,
        }


@dataclass(slots=True)
class ConfirmationResolution:
    status: str
    confirmation: PendingConfirmation | None = None
    message: str = ""


@dataclass(slots=True)
class ActionFingerprint:
    request_id: str | None
    action_id: str
    original_user_text: str
    corrected_text: str
    semantic_action: str
    target: str | None
    content_hash: str | None
    tool_plan_hash: str | None
    timestamp: float
    mutating: bool = True

    def comparable_key(self) -> tuple[Any, ...]:
        if self.request_id:
            return ("request", self.request_id)
        return (self.semantic_action, self.target, self.content_hash, self.tool_plan_hash)

    def as_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "action_id": self.action_id,
            "original_user_text": self.original_user_text,
            "corrected_text": self.corrected_text,
            "semantic_action": self.semantic_action,
            "target": self.target,
            "content_hash": self.content_hash,
            "tool_plan_hash": self.tool_plan_hash,
            "timestamp": self.timestamp,
            "mutating": self.mutating,
        }


@dataclass(slots=True)
class AutomationContext:
    session_id: str
    active_app: str | None = None
    active_window_title: str | None = None
    previous_active_app: str | None = None
    last_opened_app: str | None = None
    last_focused_app: str | None = None
    last_semantic_intent: str | None = None
    last_semantic_target: str | None = None
    last_content: str | None = None
    last_typed_text: str | None = None
    last_generated_text: str | None = None
    last_user_dictated_text: str | None = None
    last_assistant_response_text: str | None = None
    last_file_path: str | None = None
    last_created_file_path: str | None = None
    last_edited_file_path: str | None = None
    last_read_file_path: str | None = None
    last_browser: str | None = None
    last_browser_query: str | None = None
    last_opened_url: str | None = None
    last_page_title: str | None = None
    last_search_engine: str | None = None
    current_field_type: str | None = None
    current_document_context: dict[str, Any] | None = None
    current_browser_context: dict[str, Any] | None = None
    current_message_draft: dict[str, Any] | None = None
    current_pending_action: dict[str, Any] | None = None
    pending_action_type: str | None = None
    last_confirmation_request: PendingConfirmation | None = None
    last_confirmation_target: str | None = None
    last_successful_action: dict[str, Any] | None = None
    last_failed_action: dict[str, Any] | None = None
    last_tool_used: str | None = None
    last_plan_summary: str | None = None
    current_user_goal: str | None = None
    recent_action_fingerprints: list[ActionFingerprint] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    expires_at: float = field(default_factory=lambda: time.time() + AUTOMATION_CONTEXT_TTL_SECONDS)

    def touch(self, now: float | None = None) -> None:
        current = time.time() if now is None else now
        self.expires_at = current + AUTOMATION_CONTEXT_TTL_SECONDS

    def is_expired(self, now: float | None = None) -> bool:
        current = time.time() if now is None else now
        return current >= self.expires_at

    def update_from_semantic_action(self, action: SemanticAutomationAction) -> None:
        self.last_semantic_intent = action.intent.value
        self.last_semantic_target = action.target
        if action.content is not None:
            self.last_content = self.redact_sensitive_text(action.content)
        if action.app:
            self.previous_active_app = self.active_app
            self.active_app = action.app
            self.last_focused_app = action.app
        if action.file_path:
            self.last_file_path = action.file_path
        if action.query:
            self.last_browser_query = action.query
        if action.url:
            self.last_opened_url = action.url
        if action.recipient or action.content:
            if action.intent in {SemanticAutomationIntent.DRAFT_MESSAGE, SemanticAutomationIntent.SEND_MESSAGE_AFTER_CONFIRMATION}:
                self.current_message_draft = {
                    "recipient": action.recipient,
                    "content": self.redact_sensitive_text(action.content),
                }
        self.touch()

    def update_from_tool_result(self, result: dict[str, Any]) -> None:
        data = dict(result.get("data") or {}) if isinstance(result, dict) else {}
        success = bool(result.get("success")) if isinstance(result, dict) else False
        action = str(result.get("action") or data.get("action") or "") if isinstance(result, dict) else ""
        tool_name = str(result.get("tool_name") or result.get("selected_tool") or "") if isinstance(result, dict) else ""
        path = result.get("path") or data.get("path") if isinstance(result, dict) else None
        content = result.get("content") or data.get("content") if isinstance(result, dict) else None
        query = result.get("query") or data.get("query") if isinstance(result, dict) else None
        url = result.get("url") or data.get("url") if isinstance(result, dict) else None
        title = result.get("title") or data.get("title") if isinstance(result, dict) else None
        resolved_args = dict(result.get("resolved_args") or {}) if isinstance(result, dict) and isinstance(result.get("resolved_args"), dict) else {}
        if content is None:
            content = resolved_args.get("content") or resolved_args.get("text")
        if query is None:
            query = resolved_args.get("query")
        app = resolved_args.get("app") or resolved_args.get("target")

        self.last_tool_used = tool_name or self.last_tool_used
        if app and action in {"open", "app_open", "focus", "app_focus"}:
            self.previous_active_app = self.active_app
            self.active_app = str(app)
            self.last_opened_app = str(app) if action in {"open", "app_open"} else self.last_opened_app
            self.last_focused_app = str(app)
        if path:
            self.last_file_path = str(path)
            if action == "create_file":
                self.last_created_file_path = str(path)
            if action in {"write_file", "append_file", "move_file", "rename_file"}:
                self.last_edited_file_path = str(path)
            if action == "read_file":
                self.last_read_file_path = str(path)
        if content is not None:
            self.last_content = self.redact_sensitive_text(str(content))
            if action in {"type_text", "type_into_active_field", "append_text", "paste_text"}:
                self.last_typed_text = self.redact_sensitive_text(str(content))
                self.current_document_context = self.current_document_context or {"app": self.active_app}
        if query:
            self.last_browser_query = str(query)
            self.last_search_engine = self.last_search_engine or "google"
            self.current_browser_context = {"query": str(query), "browser": self.active_app or self.last_browser}
        if url:
            self.last_opened_url = str(url)
        if title:
            self.last_page_title = str(title)
            self.active_window_title = str(title)

        payload = dict(result) if isinstance(result, dict) else {}
        if success:
            self.last_successful_action = payload
        else:
            self.last_failed_action = payload
        self.touch()

    def resolve_reference(self, reference: str) -> Any:
        ref = re.sub(r"\s+", " ", str(reference or "").strip().lower())
        if ref in {"it", "this", "that", "last one"}:
            return (
                self.last_created_file_path
                or self.last_edited_file_path
                or self.last_file_path
                or self.current_message_draft
                or self.last_content
                or self.last_semantic_target
            )
        if ref in {"that file", "same file", "the file"}:
            return self.last_edited_file_path or self.last_created_file_path or self.last_file_path
        if ref in {"that search", "the search", "same search"}:
            return self.last_browser_query
        if ref in {"same app", "that app", "the app"}:
            return self.last_focused_app or self.active_app
        if ref in {"same window", "that window", "the window"}:
            return self.active_window_title
        if ref in {"there"}:
            return self.active_window_title or self.active_app
        if ref in {"send it", "message", "draft"}:
            return self.current_message_draft
        if ref in {"save it"}:
            return self.last_content or self.current_document_context
        return None

    def set_pending_action(self, action_type: str, payload: dict[str, Any]) -> None:
        self.pending_action_type = str(action_type or "").strip() or None
        self.current_pending_action = dict(payload or {})
        self.touch()

    def clear_pending_action(self) -> None:
        self.pending_action_type = None
        self.current_pending_action = None
        self.last_confirmation_request = None
        self.last_confirmation_target = None
        self.touch()

    def set_pending_confirmation(
        self,
        *,
        semantic_action: str,
        action: str,
        target: str | None = None,
        content: str | None = None,
        recipient: str | None = None,
        tool_plan: dict[str, Any] | None = None,
        safety_level: str = "HIGH",
        requires_voice_permission: bool = False,
        ttl_seconds: int | float | None = None,
    ) -> PendingConfirmation:
        created_at = time.time()
        ttl = AUTOMATION_CONTEXT_TTL_SECONDS if ttl_seconds is None else float(ttl_seconds)
        confirmation = PendingConfirmation(
            confirmation_id=f"confirm-{uuid.uuid4().hex[:16]}",
            semantic_action=str(semantic_action or ""),
            tool_plan=dict(tool_plan or {}),
            action=str(action or ""),
            target=target,
            content=self.redact_sensitive_text(content),
            recipient=recipient,
            safety_level=safety_level,
            requires_voice_permission=requires_voice_permission,
            created_at=created_at,
            expires_at=created_at + ttl,
        )
        self.last_confirmation_request = confirmation
        self.last_confirmation_target = target or recipient
        self.set_pending_action("confirmation", confirmation.as_dict())
        return confirmation

    def resolve_confirmation_response(self, text: str, *, expected_action: str | None = None) -> ConfirmationResolution:
        reply = re.sub(r"\s+", " ", str(text or "").strip().lower())
        confirmation = self.last_confirmation_request
        if confirmation is None or confirmation.status != "pending":
            return ConfirmationResolution(status="none", message="No pending confirmation.")
        if confirmation.is_expired():
            confirmation.status = "expired"
            self.clear_pending_action()
            return ConfirmationResolution(status="expired", confirmation=confirmation, message="That confirmation expired.")
        if expected_action and expected_action != confirmation.action:
            return ConfirmationResolution(status="unrelated", confirmation=confirmation, message="Confirmation does not match the pending action.")
        if reply in NO_CONFIRMATIONS:
            confirmation.status = "cancelled"
            self.clear_pending_action()
            return ConfirmationResolution(status="cancelled", confirmation=confirmation, message="Cancelled.")
        if reply in YES_CONFIRMATIONS:
            confirmation.status = "confirmed"
            return ConfirmationResolution(status="confirmed", confirmation=confirmation, message="Confirmed.")
        return ConfirmationResolution(status="unknown", confirmation=confirmation, message="That was not a confirmation response.")

    def update_pending_confirmation_from_text(self, text: str) -> bool:
        confirmation = self.last_confirmation_request
        if confirmation is None or confirmation.status != "pending":
            return False
        raw = str(text or "").strip()
        recipient_match = re.match(r"^change\s+(.+?)\s+to\s+(.+?)[.!?]*$", raw, flags=re.I)
        if recipient_match:
            old = recipient_match.group(1).strip()
            new = recipient_match.group(2).strip()
            if confirmation.recipient and confirmation.recipient.lower() == old.lower():
                confirmation.recipient = new
                confirmation.target = new if confirmation.target == old else confirmation.target
                self.current_pending_action = confirmation.as_dict()
                return True
        content_match = re.match(r"^change\s+(?:the\s+)?message\s+to\s+(.+?)[.!?]*$", raw, flags=re.I)
        if content_match:
            confirmation.content = self.redact_sensitive_text(content_match.group(1).strip())
            self.current_pending_action = confirmation.as_dict()
            return True
        return False

    def create_fingerprint(
        self,
        *,
        original_user_text: str,
        semantic_action: str,
        corrected_text: str | None = None,
        target: str | None = None,
        content: str | None = None,
        tool_plan: dict[str, Any] | None = None,
        request_id: str | None = None,
        action_id: str | None = None,
        mutating: bool | None = None,
        timestamp: float | None = None,
    ) -> ActionFingerprint:
        semantic = str(semantic_action or "")
        is_mutating = semantic not in NON_MUTATING_INTENTS if mutating is None else bool(mutating)
        return ActionFingerprint(
            request_id=request_id,
            action_id=action_id or f"action-{uuid.uuid4().hex[:16]}",
            original_user_text=str(original_user_text or ""),
            corrected_text=str(corrected_text if corrected_text is not None else original_user_text or ""),
            semantic_action=semantic,
            target=target,
            content_hash=_stable_hash(content) if content is not None else None,
            tool_plan_hash=_stable_hash(tool_plan) if tool_plan is not None else None,
            timestamp=time.time() if timestamp is None else timestamp,
            mutating=is_mutating,
        )

    def is_duplicate(self, fingerprint: ActionFingerprint, *, now: float | None = None, window_seconds: int | float = AUTOMATION_DUPLICATE_WINDOW_SECONDS) -> bool:
        if not fingerprint.mutating:
            return False
        current = time.time() if now is None else now
        for recent in self.recent_action_fingerprints:
            if not recent.mutating:
                continue
            if current - recent.timestamp > window_seconds:
                continue
            if recent.comparable_key() == fingerprint.comparable_key():
                return True
        return False

    def record_fingerprint(self, fingerprint: ActionFingerprint) -> None:
        self.recent_action_fingerprints.append(fingerprint)
        self.clear_expired_fingerprints(now=fingerprint.timestamp)

    def clear_expired_fingerprints(self, *, now: float | None = None, window_seconds: int | float = AUTOMATION_DUPLICATE_WINDOW_SECONDS) -> None:
        current = time.time() if now is None else now
        self.recent_action_fingerprints = [
            item for item in self.recent_action_fingerprints if current - item.timestamp <= window_seconds
        ]

    def redact_sensitive_text(self, text: str | None) -> str | None:
        if text is None:
            return None
        value = str(text)
        if not AUTOMATION_CONTEXT_REDACT_SENSITIVE:
            return value
        redacted = value
        for pattern in SENSITIVE_PATTERNS:
            redacted = pattern.sub("[REDACTED]", redacted)
        return redacted

    def clear_sensitive_fields(self) -> None:
        self.last_content = self.redact_sensitive_text(self.last_content)
        self.last_typed_text = self.redact_sensitive_text(self.last_typed_text)
        self.last_generated_text = self.redact_sensitive_text(self.last_generated_text)
        self.last_user_dictated_text = self.redact_sensitive_text(self.last_user_dictated_text)
        self.last_assistant_response_text = self.redact_sensitive_text(self.last_assistant_response_text)
        if self.current_message_draft:
            self.current_message_draft = {
                **self.current_message_draft,
                "content": self.redact_sensitive_text(self.current_message_draft.get("content")),
            }


class AutomationContextStore:
    def __init__(self) -> None:
        self._contexts: dict[str, AutomationContext] = {}

    def get(self, session_id: str) -> AutomationContext:
        key = str(session_id or "default")
        context = self._contexts.get(key)
        if context is None or context.is_expired():
            context = AutomationContext(session_id=key)
            self._contexts[key] = context
        return context

    def clear(self, session_id: str) -> None:
        self._contexts.pop(str(session_id or "default"), None)


def _stable_hash(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        raw = value
    else:
        raw = json.dumps(value, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
