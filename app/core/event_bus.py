from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable


SENSITIVE_KEYS = {
    "access_token",
    "api_key",
    "authorization",
    "cookie",
    "embedding",
    "embeddings",
    "password",
    "private_message_text",
    "refresh_token",
    "secret",
    "set-cookie",
    "step_up_token",
    "token",
}


class EventName:
    TOOL_SELECTED = "tool_selected"
    TOOL_STARTED = "tool_started"
    TOOL_SUCCESS = "tool_success"
    TOOL_FAILED = "tool_failed"
    STEP_UP_REQUIRED = "step_up_required"
    STEP_UP_FAILED = "step_up_failed"
    STEP_UP_SUCCESS = "step_up_success"


@dataclass(frozen=True, slots=True)
class Event:
    name: str
    timestamp: float
    payload: dict[str, Any] = field(default_factory=dict)


Subscriber = Callable[[Event], None]


class EventBus:
    def __init__(self, *, record_history: bool = False, max_history: int = 500) -> None:
        self._subscribers: dict[str, list[Subscriber]] = {}
        self._lock = threading.RLock()
        self._record_history = record_history
        self._max_history = max_history
        self._history: list[Event] = []

    def subscribe(self, event_name: str, subscriber: Subscriber) -> None:
        with self._lock:
            self._subscribers.setdefault(event_name, []).append(subscriber)

    def unsubscribe(self, event_name: str, subscriber: Subscriber) -> None:
        with self._lock:
            subscribers = self._subscribers.get(event_name, [])
            self._subscribers[event_name] = [item for item in subscribers if item is not subscriber]

    def publish(self, event_name: str, payload: dict[str, Any] | None = None) -> Event:
        event = Event(
            name=str(event_name or "").strip(),
            timestamp=time.time(),
            payload=sanitize_event_payload(payload or {}),
        )
        with self._lock:
            subscribers = [
                *self._subscribers.get(event.name, []),
                *self._subscribers.get("*", []),
            ]
            if self._record_history:
                self._history.append(event)
                if len(self._history) > self._max_history:
                    self._history = self._history[-self._max_history :]
        for subscriber in subscribers:
            subscriber(event)
        return event

    def history(self) -> list[Event]:
        with self._lock:
            return list(self._history)


def sanitize_event_payload(payload: Any) -> Any:
    if isinstance(payload, dict):
        sanitized: dict[str, Any] = {}
        for key, value in payload.items():
            key_text = str(key)
            if _is_sensitive_key(key_text):
                sanitized[key_text] = "[redacted]"
            else:
                sanitized[key_text] = sanitize_event_payload(value)
        return sanitized
    if isinstance(payload, list):
        return [sanitize_event_payload(item) for item in payload]
    return payload


def _is_sensitive_key(key: str) -> bool:
    lowered = str(key or "").strip().lower()
    normalized = lowered.replace("-", "_")
    if lowered in SENSITIVE_KEYS or normalized in SENSITIVE_KEYS:
        return True
    return normalized.endswith("_token") or normalized.endswith("_secret") or normalized.endswith("_password")
