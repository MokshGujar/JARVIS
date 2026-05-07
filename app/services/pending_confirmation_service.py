from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


class PendingConfirmationService:
    """Session-scoped pending confirmation state for AutomationService."""

    def __init__(self) -> None:
        self.session_state: dict[str, dict[str, Any]] = {}
        self.emitted_prompt_ids: set[str] = set()

    def load_into(self, service: Any, session_id: str) -> None:
        state = self.session_state.get(session_id) or {}
        service._pending_delete_target = state.get("delete_target")
        service._pending_open_target = state.get("open_target")
        service._pending_browser_search = state.get("browser_search")
        service._pending_create_file = state.get("create_file")
        service._pending_incomplete_command = state.get("incomplete_command")
        service._pending_mark_action = state.get("mark_action")
        service._pending_whatsapp_clarification = state.get("whatsapp_clarification")
        service._pending_dry_run_plan = state.get("dry_run_plan")

    def save_from(self, service: Any, session_id: str) -> None:
        state = {
            "delete_target": service._pending_delete_target,
            "open_target": service._pending_open_target,
            "browser_search": service._pending_browser_search,
            "create_file": service._pending_create_file,
            "incomplete_command": service._pending_incomplete_command,
            "mark_action": service._pending_mark_action,
            "whatsapp_clarification": service._pending_whatsapp_clarification,
            "dry_run_plan": service._pending_dry_run_plan,
        }
        if any(value is not None for value in state.values()):
            self.session_state[session_id] = state
        else:
            self.session_state.pop(session_id, None)

    def confirmation_scope_key(self, pending_action_id: str, session_id: str | None) -> str:
        return f"{session_id or '__default__'}:{pending_action_id}"

    def pending_action_id(self, kind: str, payload: object) -> str:
        clean_payload = self._sanitize(payload)
        raw = json.dumps({"kind": kind, "payload": clean_payload}, sort_keys=True, default=str)
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
        return f"{kind}:{digest}"

    def active_pending_confirmation_id(self, service: Any) -> str | None:
        if service._pending_mark_action is not None:
            pending = service._pending_mark_action
            return self.pending_action_id(str(pending.get("kind") or "mark"), dict(pending.get("payload") or {}))
        if service._pending_delete_target is not None:
            return self.pending_action_id("delete", {"target": service._pending_delete_target})
        return None

    def active_confirmation_prompt_keys(self, service: Any, session_id: str | None) -> set[str]:
        pending_action_id = self.active_pending_confirmation_id(service)
        if not pending_action_id:
            return set()
        return {self.confirmation_scope_key(pending_action_id, session_id)}

    def clear_stale_confirmation_prompts(self, previous_keys: set[str], current_keys: set[str]) -> None:
        for key in previous_keys - current_keys:
            self.emitted_prompt_ids.discard(key)

    def dedupe_confirmation_prompt(self, service: Any, result: dict[str, object], *, session_id: str | None) -> dict[str, object]:
        pending_action_id = self.active_pending_confirmation_id(service)
        if not pending_action_id:
            return result

        scoped_key = self.confirmation_scope_key(pending_action_id, session_id)
        prompt_already_emitted = scoped_key in self.emitted_prompt_ids
        result["pending_action_id"] = pending_action_id
        if isinstance(result.get("pending"), dict):
            result["pending"] = {**dict(result["pending"]), "pending_action_id": pending_action_id}

        for action in result.get("actions") or []:
            if isinstance(action, dict) and action.get("type") == "show_status":
                action["pending_action_id"] = pending_action_id

        if prompt_already_emitted and self.is_repeat_confirmation_prompt_result(result):
            message = "Waiting for your confirmation."
            result["message"] = message
            result["display_text"] = message
            result["spoken_text"] = ""
            for action in result.get("actions") or []:
                if isinstance(action, dict) and action.get("type") == "show_status":
                    action["message"] = message
            return result

        if self.is_confirmation_prompt_result(result):
            self.emitted_prompt_ids.add(scoped_key)
            result.setdefault("spoken_text", str(result.get("message") or ""))
        return result

    def is_repeat_confirmation_prompt_result(self, result: dict[str, object]) -> bool:
        action = str(result.get("action") or "")
        if action == "multi_action":
            return False
        return self.is_confirmation_prompt_result(result)

    @staticmethod
    def is_confirmation_prompt_result(result: dict[str, object]) -> bool:
        if result.get("pending_action_id"):
            return True
        action = str(result.get("action") or "")
        message = str(result.get("message") or "")
        if action in {"whatsapp_call_pending", "send_message_pending", "game_confirmation", "delete_file", "delete_folder", "delete", "confirmation"}:
            return bool(
                re.search(r"\bsay yes\b|\breply yes\b|\bplease reply yes\b|\bno to cancel\b|\bconfirm\b", message, re.I)
            )
        return False

    def _sanitize(self, value: object) -> object:
        if isinstance(value, dict):
            return {str(key): self._sanitize(val) for key, val in sorted(value.items()) if key != "expires_at"}
        if isinstance(value, (list, tuple, set)):
            return [self._sanitize(item) for item in value]
        if isinstance(value, Path):
            return str(value)
        return value
