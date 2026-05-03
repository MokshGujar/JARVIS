from __future__ import annotations

import re
from pathlib import Path
from typing import Any


CANONICAL_ACTION_TYPES = {
    "open_url",
    "open_content",
    "open_image",
    "play_media",
    "download_file",
    "show_status",
    "show_task_result",
}


def _as_text(value: Any, fallback: str = "") -> str:
    text = "" if value is None else str(value)
    return text if text else fallback


def _coerce_action(item: Any) -> dict[str, Any] | None:
    if isinstance(item, str):
        return {"type": "open_url", "url": item, "internal_browser": True}
    if not isinstance(item, dict):
        return None

    action_type = item.get("type") or item.get("action")
    if action_type in CANONICAL_ACTION_TYPES:
        action = dict(item)
        action["type"] = action_type
        action.pop("action", None)
        return action

    if item.get("url"):
        return {
            "type": "open_url",
            "url": item.get("url"),
            "title": item.get("title") or item.get("label"),
            "internal_browser": bool(item.get("internal_browser", True)),
        }
    if item.get("text") or item.get("body"):
        return {
            "type": "open_content",
            "title": item.get("title") or "Content ready.",
            "text": item.get("text") or item.get("body") or "",
        }
    return None


def _legacy_bucket_actions(result: dict[str, Any]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []

    for key in ("wopens", "googlesearches", "youtubesearches"):
        for url in result.get(key) or []:
            if url:
                actions.append({"type": "open_url", "url": url, "internal_browser": True})

    for url in result.get("plays") or []:
        if url:
            actions.append({"type": "play_media", "url": url, "internal_browser": True})

    for image in result.get("images") or []:
        if isinstance(image, str):
            actions.append({"type": "open_image", "url": image, "title": "Image ready."})
        elif isinstance(image, dict):
            actions.append(
                {
                    "type": "open_image",
                    "url": image.get("url"),
                    "title": image.get("title") or image.get("prompt") or "Image ready.",
                }
            )

    for content in result.get("contents") or []:
        if isinstance(content, str):
            actions.append({"type": "open_content", "title": "Content ready.", "text": content})
        elif isinstance(content, dict):
            actions.append(
                {
                    "type": "open_content",
                    "title": content.get("title") or content.get("prompt") or "Content ready.",
                    "text": content.get("text") or content.get("body") or "",
                }
            )

    if isinstance(result.get("cam"), dict):
        actions.append({"type": "show_status", "status": "camera", "message": "Camera action requested.", "cam": result["cam"]})

    return [action for action in actions if action.get("type")]


class AutomationResponseFormatter:
    """Short, voice-friendly messages for automation results."""

    MAX_SPOKEN_CHARS = 180

    def format(self, result: dict[str, Any]) -> str | None:
        if not isinstance(result, dict):
            return None
        if result.get("debug"):
            return None
        if result.get("is_multistep"):
            return self._format_multistep(result)
        return self._format_single(result)

    def _format_multistep(self, result: dict[str, Any]) -> str | None:
        steps = [item for item in result.get("step_results") or [] if isinstance(item, dict)]
        actions = [str(item.get("planned_action") or item.get("action") or "") for item in steps]
        if {"create_file", "write_file"}.issubset(set(actions)):
            created = self._step(steps, "create_file")
            wrote = self._step(steps, "write_file")
            verified = self._step(steps, "verify_exists")
            file_name = self._file_label((created or {}).get("path") or (created or {}).get("data", {}).get("path"))
            location = self._parent_label((created or {}).get("path") or (created or {}).get("data", {}).get("path"))
            content = self._short_content((wrote or {}).get("content") or (wrote or {}).get("data", {}).get("content"))
            if result.get("success"):
                if content:
                    return self._trim(f"Done, I created {file_name} on your {location} and wrote {content}.")
                return self._trim(f"Done, I created {file_name} on your {location}.")
            if created and created.get("success") and wrote and not wrote.get("success"):
                return "I created the file, but I couldn't write the text into it."
            if created and created.get("success") and verified and not verified.get("success"):
                return "I created the file, but I couldn't verify the final contents."
        if "create_file" in actions and result.get("success"):
            created = self._step(steps, "create_file")
            file_name = self._file_label((created or {}).get("path") or (created or {}).get("data", {}).get("path"))
            location = self._parent_label((created or {}).get("path") or (created or {}).get("data", {}).get("path"))
            return self._trim(f"Done, I created {file_name} on your {location}.")
        return None

    def _format_single(self, result: dict[str, Any]) -> str | None:
        action = str(result.get("action") or "").strip().lower()
        message = str(result.get("message") or "").strip()
        if action in {
            "semantic_confirmation_required",
            "semantic_confirmation_updated",
            "semantic_confirmation_cancelled",
            "semantic_confirmation_expired",
            "semantic_confirmation_accepted_disabled",
            "semantic_confirmation_none",
            "semantic_confirmation_update_needed",
            "semantic_clarification_required",
            "duplicate_semantic_action",
            "duplicate_confirmation_cancelled",
        }:
            return self._trim(self._sanitize_message(message or self._semantic_fallback(action)))
        if action in {"semantic_action_blocked", "unsupported_semantic_action"}:
            return self._trim(self._sanitize_message(message or "I can't safely run that yet."))
        if action in {"tool_not_found"}:
            return "That tool is not available right now."
        if action in {"dependency_failed"}:
            return "I started that, but a required step did not finish."
        if action in {"confirmation_required", "auth_required"}:
            if action == "auth_required":
                return "I need voice permission before I can do that."
            return "Please confirm before I continue."
        if action in {"create_file_location_needed"}:
            return self._trim(message) if message else "Where should I save it?"
        lowered_message = message.lower()
        if (
            not result.get("success")
            and "file" in lowered_message
            and "don't know which file" not in lowered_message
            and re.search(r"\b(?:tell me|what should)\b.*\bfile name\b", lowered_message)
        ):
            return "What should I name the file?"
        if action in {"google_search", "youtube_search"}:
            query = self._query_from_message(message)
            browser = self._browser_from_message(message)
            if query and browser:
                return self._trim(f"Done, searching for {query} in {browser}.")
            if query:
                return self._trim(f"Done, searching for {query}.")
        if action in {"open", "app_open", "focus", "app_focus"} and result.get("success"):
            target = self._target_from_open_message(message)
            if target:
                return self._trim(f"Done, I opened {target}.")
        if action in {"volume_up", "volume_down", "mute", "unmute", "screenshot", "computer_control", "system"} and result.get("success"):
            return self._trim(message or "Done.")
        if action in {"search"} and "what should i search" in message.lower():
            return "What should I search for?"
        if message and self._looks_internal(message):
            return "I couldn't complete that action."
        return None

    @staticmethod
    def _step(steps: list[dict[str, Any]], action: str) -> dict[str, Any] | None:
        for step in steps:
            if step.get("planned_action") == action or step.get("action") == action:
                return step
        return None

    @staticmethod
    def _file_label(path_value: Any) -> str:
        if not path_value:
            return "the file"
        name = Path(str(path_value)).stem or Path(str(path_value)).name
        return re.sub(r"[_-]+", " ", name).strip() or "the file"

    @staticmethod
    def _parent_label(path_value: Any) -> str:
        if not path_value:
            return "selected folder"
        parent = Path(str(path_value)).parent.name or "selected folder"
        return re.sub(r"[_-]+", " ", parent).strip()

    @staticmethod
    def _short_content(value: Any) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        if not text:
            return ""
        return text if len(text) <= 48 else f"{text[:45].rstrip()}..."

    @staticmethod
    def _query_from_message(message: str) -> str:
        match = re.search(r"searching\s+(?:google|youtube)\s+for\s+(.+?)(?:\s+in\s+.+)?[.!?]*$", message, re.I)
        return (match.group(1).strip() if match else "").rstrip(".!?")

    @staticmethod
    def _browser_from_message(message: str) -> str:
        match = re.search(r"\s+in\s+(.+?)[.!?]*$", message, re.I)
        return (match.group(1).strip() if match else "").rstrip(".!?")

    @staticmethod
    def _target_from_open_message(message: str) -> str:
        match = re.search(r"opening\s+(.+?)[.!?]*$", message, re.I)
        return (match.group(1).strip() if match else "").rstrip(".!?")

    def _trim(self, message: str) -> str:
        text = re.sub(r"\s+", " ", str(message or "")).strip()
        return text if len(text) <= self.MAX_SPOKEN_CHARS else f"{text[: self.MAX_SPOKEN_CHARS - 3].rstrip()}..."

    @staticmethod
    def _semantic_fallback(action: str) -> str:
        return {
            "semantic_confirmation_required": "I need confirmation before doing that.",
            "semantic_confirmation_updated": "Updated. Should I continue?",
            "semantic_confirmation_cancelled": "Cancelled. I did not run it.",
            "semantic_confirmation_expired": "That confirmation expired. I did not run it.",
            "semantic_confirmation_accepted_disabled": "I have confirmation, but this action is not enabled yet.",
            "semantic_confirmation_none": "Nothing is waiting for confirmation.",
            "semantic_clarification_required": "Did you mean put world in it?",
            "duplicate_semantic_action": "This looks like the same action again. Should I repeat it?",
            "duplicate_confirmation_cancelled": "Cancelled. I did not repeat it.",
        }.get(action, "I can't safely run that yet.")

    @staticmethod
    def _looks_internal(message: str) -> bool:
        return bool(
            "ToolResult(" in message
            or "Traceback" in message
            or re.search(r"\b[A-Z][A-Z0-9]+_[A-Z0-9_]+\b", message)
            or re.search(r"confirmation_id\s*=", message)
            or re.search(r"^\s*[\{\[]", message)
        )

    def _sanitize_message(self, message: str) -> str:
        text = str(message or "")
        if self._looks_internal(text):
            return "I couldn't complete that action."
        text = re.sub(r"\bconfirmation_id\s*=\s*[\w:-]+", "", text)
        text = re.sub(r"\bconfirm-[a-f0-9]{8,}\b", "", text)
        text = re.sub(r"\b[A-Z][A-Z0-9]+_[A-Z0-9_]+\b", "that action", text)
        return re.sub(r"\s+", " ", text).strip()


AUTOMATION_RESPONSE_FORMATTER = AutomationResponseFormatter()


def normalize_automation_response(result: Any) -> dict[str, Any]:
    """Return the canonical automation response while preserving legacy message."""
    if not isinstance(result, dict):
        result = {"success": False, "action": "unsupported", "message": _as_text(result, "Automation failed.")}

    success = bool(result.get("success", False))
    action_name = _as_text(result.get("action"), "automation")
    message = _as_text(result.get("message"), _as_text(result.get("display_text"), "Done." if success else "Automation failed."))
    display_text = _as_text(result.get("display_text"), message)
    if "spoken_text" in result:
        raw_spoken = result.get("spoken_text")
        spoken_text = "" if raw_spoken is None else str(raw_spoken)
    else:
        spoken_text = display_text

    formatted = AUTOMATION_RESPONSE_FORMATTER.format(result)
    if formatted:
        message = formatted
        display_text = formatted
        spoken_text = formatted

    raw_actions = result.get("actions")
    actions: list[dict[str, Any]] = []
    if isinstance(raw_actions, list):
        actions.extend(action for action in (_coerce_action(item) for item in raw_actions) if action)
    elif isinstance(raw_actions, dict):
        actions.extend(_legacy_bucket_actions(raw_actions))
        if raw_actions.get("auth"):
            actions.append({"type": "show_status", "status": "auth", "message": message, "auth": raw_actions["auth"]})

    actions.extend(_legacy_bucket_actions(result))

    if not actions and display_text:
        actions.append(
            {
                "type": "show_status",
                "status": "success" if success else "error",
                "message": display_text,
                "action": action_name,
            }
        )

    normalized = dict(result)
    normalized.update(
        {
            "success": success,
            "route": result.get("route") or "automation",
            "action": action_name,
            "spoken_text": spoken_text,
            "display_text": display_text,
            "message": message,
            "actions": actions,
            "events": list(result.get("events") or []),
            "requires_step_up": bool(result.get("requires_step_up", False)),
            "error": result.get("error"),
        }
    )
    return normalized
