from __future__ import annotations

import time
from typing import Any


class ClarificationService:
    @staticmethod
    def build(
        clarification_type: str,
        message: str,
        *,
        candidates: list[dict[str, Any]] | None = None,
        session_id: str | None = None,
        ttl_seconds: int = 90,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "success": False,
            "action": "clarification_required",
            "status": "clarification_required",
            "requires_followup": True,
            "clarification_type": str(clarification_type or "clarification").strip() or "clarification",
            "message": str(message or "Please clarify.").strip() or "Please clarify.",
            "expires_at": time.time() + max(1, int(ttl_seconds)),
        }
        if candidates is not None:
            payload["candidates"] = list(candidates)
        if session_id:
            payload["session_id"] = session_id
        if metadata:
            payload["metadata"] = dict(metadata)
        return payload
