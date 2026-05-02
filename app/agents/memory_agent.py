from __future__ import annotations


class MemoryAgent:
    def __init__(self, context_memory) -> None:
        self.context_memory = context_memory

    def remember(self, session_id: str, key: str, value, *, ttl_seconds: int | None = None) -> None:
        self.context_memory.remember(session_id, key, value, ttl_seconds=ttl_seconds)

    def recall(self, session_id: str, key: str, default=None):
        return self.context_memory.recall(session_id, key, default=default)
