from __future__ import annotations

import secrets
import time
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LauncherBootstrapExchange:
    ok: bool
    face_session_id: str = ""
    reason: str = ""


class LauncherBootstrapService:
    """Short-lived one-time handoff tokens for the startup launcher."""

    def __init__(self, *, ttl_seconds: int = 30) -> None:
        self.ttl_seconds = max(5, int(ttl_seconds))
        self._tokens: dict[str, dict] = {}

    def create(self, face_session_id: str) -> dict:
        session_id = str(face_session_id or "").strip()
        if not session_id:
            return {
                "created": False,
                "reason": "missing_face_session",
                "launcher_bootstrap_token": "",
                "expires_in_seconds": 0,
            }

        self._prune_expired()
        token = secrets.token_urlsafe(32)
        self._tokens[token] = {
            "face_session_id": session_id,
            "expires_at": time.time() + self.ttl_seconds,
            "consumed": False,
            "created_at": time.time(),
        }
        return {
            "created": True,
            "reason": "created",
            "launcher_bootstrap_token": token,
            "expires_in_seconds": self.ttl_seconds,
        }

    def exchange(self, token: str) -> LauncherBootstrapExchange:
        value = str(token or "").strip()
        if not value:
            return LauncherBootstrapExchange(False, reason="missing_bootstrap_token")

        record = self._tokens.get(value)
        if not record:
            return LauncherBootstrapExchange(False, reason="bootstrap_token_unknown")

        if record.get("consumed"):
            self._tokens.pop(value, None)
            return LauncherBootstrapExchange(False, reason="bootstrap_token_reused")

        if float(record.get("expires_at") or 0) < time.time():
            self._tokens.pop(value, None)
            return LauncherBootstrapExchange(False, reason="bootstrap_token_expired")

        record["consumed"] = True
        face_session_id = str(record.get("face_session_id") or "")
        self._tokens.pop(value, None)
        return LauncherBootstrapExchange(True, face_session_id=face_session_id, reason="exchanged")

    def invalidate_all(self) -> None:
        self._tokens.clear()

    def _prune_expired(self) -> None:
        now = time.time()
        for token, record in list(self._tokens.items()):
            if float(record.get("expires_at") or 0) < now:
                self._tokens.pop(token, None)
