from __future__ import annotations

import time
from typing import Any


class ContextMemory:
    def __init__(self, *, default_ttl_seconds: int = 300) -> None:
        self.default_ttl_seconds = default_ttl_seconds
        self._sessions: dict[str, dict[str, dict[str, Any]]] = {}

    def remember(self, session_id: str, key: str, value: Any, *, ttl_seconds: int | None = None) -> None:
        sid = str(session_id or "default")
        expires_at = time.time() + float(ttl_seconds or self.default_ttl_seconds)
        self._sessions.setdefault(sid, {})[str(key)] = {"value": value, "expires_at": expires_at}

    def recall(self, session_id: str, key: str, default: Any = None) -> Any:
        sid = str(session_id or "default")
        item = self._sessions.get(sid, {}).get(str(key))
        if not item:
            return default
        if float(item.get("expires_at", 0.0)) <= time.time():
            self._sessions.get(sid, {}).pop(str(key), None)
            return default
        return item.get("value")

    def clear_session(self, session_id: str) -> None:
        self._sessions.pop(str(session_id or "default"), None)
