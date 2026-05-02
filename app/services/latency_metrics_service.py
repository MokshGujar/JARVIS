from __future__ import annotations

import time
from typing import Dict


class LatencyTracker:
    def __init__(self) -> None:
        self.started_at = time.perf_counter()
        self.values: Dict[str, int] = {}

    def mark(self, key: str) -> int:
        elapsed = int((time.perf_counter() - self.started_at) * 1000)
        self.values[key] = elapsed
        return elapsed

    def mark_once(self, key: str) -> int:
        if key in self.values:
            return self.values[key]
        return self.mark(key)

    def set(self, key: str, value_ms: int | float | None) -> None:
        if value_ms is None:
            return
        self.values[key] = int(value_ms)

    def get(self, key: str) -> int | None:
        return self.values.get(key)

    def snapshot(self, *, final: bool = False) -> dict:
        if final:
            elapsed = self.mark_once("response_complete")
            self.values["total_ms"] = elapsed
        return dict(self.values)
