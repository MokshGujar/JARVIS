from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class InterruptToken:
    session_id: str
    client_request_id: str
    created_at: float = field(default_factory=time.time)
    cancelled: bool = False
    reason: str = ""

    def cancel(self, reason: str = "interrupted") -> None:
        self.cancelled = True
        self.reason = reason


class InterruptManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active: Dict[str, InterruptToken] = {}

    def start(self, session_id: str, client_request_id: Optional[str] = None) -> InterruptToken:
        token = InterruptToken(
            session_id=session_id,
            client_request_id=(client_request_id or uuid.uuid4().hex),
        )
        with self._lock:
            old = self._active.get(session_id)
            if old:
                old.cancel("superseded")
            self._active[session_id] = token
        return token

    def interrupt(self, session_id: str, client_request_id: Optional[str] = None) -> bool:
        with self._lock:
            token = self._active.get(session_id)
            if not token:
                return False
            if client_request_id and token.client_request_id != client_request_id:
                return False
            token.cancel()
            return True

    def finish(self, token: InterruptToken) -> None:
        with self._lock:
            current = self._active.get(token.session_id)
            if current is token:
                self._active.pop(token.session_id, None)

    def status(self) -> dict:
        with self._lock:
            return {
                "active_sessions": len(self._active),
                "sessions": list(self._active.keys()),
            }
