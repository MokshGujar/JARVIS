from __future__ import annotations


class FakeSummaryProvider:
    def __init__(self, response: str = "Fake summary.") -> None:
        self.response = response
        self.calls: list[dict[str, str]] = []

    def summarize(self, text: str, mode: str = "summary") -> str:
        self.calls.append({"text": text, "mode": mode})
        return self.response
