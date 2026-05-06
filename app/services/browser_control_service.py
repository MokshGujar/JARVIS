from __future__ import annotations

from concurrent.futures import TimeoutError as FutureTimeout
from typing import Dict

from app.adapters.browser.browser_runtime_adapter import BrowserRuntimeAdapter


class BrowserControlService:
    """Compatibility facade for browser runtime control.

    Canonical owner: BrowserTool.
    This facade remains for older imports/tests and delegates to BrowserRuntimeAdapter;
    it is not the canonical execution boundary.
    """

    def __init__(self, adapter: BrowserRuntimeAdapter | None = None) -> None:
        self.adapter = adapter or BrowserRuntimeAdapter()

    @property
    def _thread(self):
        return self.adapter._thread

    @_thread.setter
    def _thread(self, value):
        self.adapter._thread = value

    def available(self) -> bool:
        return self.adapter.available()

    def execute(self, action: str, **params) -> Dict[str, str | bool]:
        return self.adapter.execute(action, **params)
