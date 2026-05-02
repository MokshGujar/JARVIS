from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class CommandRiskResult:
    command_text: str
    command_action: str
    risk_level: str
    step_up_required: bool
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "command_text": self.command_text,
            "command_action": self.command_action,
            "risk_level": self.risk_level,
            "step_up_required": self.step_up_required,
            "reasons": self.reasons,
            "command_hash": self.command_hash(),
        }

    def command_hash(self) -> str:
        return hashlib.sha256(f"{self.command_action}:{self.command_text}".encode("utf-8")).hexdigest()


class CommandRiskService:
    DELETE_ACTIONS = {"delete", "delete_file", "delete_folder", "remove_file", "remove_folder"}
    DELETE_PATTERN = re.compile(
        r"\b(delete|remove|trash|erase)\b(?:\s+(?:the|a|an))?(?:\s+(?:file|folder|directory))?\b",
        re.I,
    )
    ACTION_WORD_RE = re.compile(r"^\s*(?P<action>[a-zA-Z_ -]+?)(?:\s|$)")

    def classify(self, command_text: str, *, command_action: str = "") -> CommandRiskResult:
        text = (command_text or "").strip()
        action = (command_action or self._infer_action(text)).strip() or "unknown"
        if re.match(r"^\s*(?:end|hang up|disconnect)(?:\s+the)?\s+(?:active\s+)?(?:whatsapp\s+)?call\b", text, re.I):
            return CommandRiskResult(
                command_text=text,
                command_action=action,
                risk_level="LOW_RISK",
                step_up_required=False,
                reasons=[],
            )
        reasons: list[str] = []
        if self._is_destructive_file_deletion(text, action):
            reasons.append("delete_files")
            if action in self.DELETE_ACTIONS:
                reasons.append(action)
        high = bool(reasons)
        return CommandRiskResult(
            command_text=text,
            command_action=action,
            risk_level="HIGH_RISK" if high else "LOW_RISK",
            step_up_required=high,
            reasons=sorted(set(reasons)),
        )

    def _infer_action(self, text: str) -> str:
        match = self.ACTION_WORD_RE.match(text or "")
        return (match.group("action") if match else "unknown").strip().lower().replace(" ", "_")

    def _is_destructive_file_deletion(self, text: str, action: str) -> bool:
        normalized_action = (action or "").strip().lower()
        if normalized_action in self.DELETE_ACTIONS:
            return True
        if normalized_action in {"send_message", "start_call", "voice_call", "video_call", "phone", "phone_control"}:
            return False
        if not self.DELETE_PATTERN.search(text or ""):
            return False
        lowered = (text or "").lower()
        if re.search(r"\b(powershell|terminal|command prompt|cmd|shell|run command|execute command|subprocess)\b", lowered):
            return False
        if re.search(r"\b(?:message|chat|email|sms|whatsapp\s+message|call|contact)\b", lowered):
            return False
        if not re.search(r"\b(file|folder|directory|path|item)\b|[\\/]|[\w -]+\.[a-z0-9]{1,8}\b", lowered):
            return False
        return True
