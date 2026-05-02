from __future__ import annotations

import collections
import json
import logging
import time
from typing import Any, Deque, Dict

from config import OBSERVABILITY_DATA_DIR

logger = logging.getLogger("J.A.R.V.I.S")


class ObservabilityService:
    def __init__(self, max_events: int = 200) -> None:
        self._events: Deque[Dict[str, Any]] = collections.deque(maxlen=max_events)
        self._path = OBSERVABILITY_DATA_DIR / "recent_events.json"

    def record(self, kind: str, payload: Dict[str, Any]) -> None:
        event = {"kind": kind, "payload": payload, "timestamp": time.time()}
        self._events.appendleft(event)
        try:
            self._path.write_text(json.dumps(list(self._events), indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            logger.warning("[OBSERVE] Failed to persist event: %s", exc)

    def record_request(self, method: str, path: str, status_code: int, elapsed_ms: int) -> None:
        self.record(
            "request",
            {
                "method": method,
                "path": path,
                "status_code": status_code,
                "elapsed_ms": elapsed_ms,
            },
        )

    def snapshot(self) -> Dict[str, Any]:
        events = list(self._events)
        if not events and self._path.exists():
            try:
                events = json.loads(self._path.read_text(encoding="utf-8"))
            except Exception:
                events = []
        return {
            "event_count": len(events),
            "recent_requests": [event for event in events if event.get("kind") == "request"][:30],
            "recent_errors": [
                event
                for event in events
                if event.get("payload", {}).get("status_code", 200) >= 400
            ][:20],
        }
