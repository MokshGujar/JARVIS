from __future__ import annotations

from typing import Dict, Optional

from app.adapters.ui.pyautogui_adapter import PyAutoGUIAdapter


class ComputerControlService:
    """Compatibility facade for computer control.

    Canonical owner: SystemTool/AppInteractionTool.
    This facade remains for older imports/tests and delegates to the UI adapter;
    it is not the canonical execution boundary.
    """

    def __init__(self, adapter: PyAutoGUIAdapter | None = None) -> None:
        self.adapter = adapter or PyAutoGUIAdapter()

    def available(self) -> bool:
        return self.adapter.available()

    def type_text(self, text: str, *, clear_first: bool = False, press_enter: bool = False) -> Dict[str, str | bool]:
        return self.adapter.type_text(text, clear_first=clear_first, press_enter=press_enter)

    def hotkey(self, keys: list[str]) -> Dict[str, str | bool]:
        return self.adapter.hotkey(keys)

    def press(self, key: str) -> Dict[str, str | bool]:
        return self.adapter.press(key)

    def click(self, x: Optional[int] = None, y: Optional[int] = None, *, button: str = "left", clicks: int = 1) -> Dict[str, str | bool]:
        return self.adapter.click(x, y, button=button, clicks=clicks)

    def scroll(self, direction: str = "down", amount: int = 3) -> Dict[str, str | bool]:
        return self.adapter.scroll(direction, amount)

    def screenshot(self, path: str | None = None) -> Dict[str, str | bool]:
        return self.adapter.screenshot(path)

    def clipboard_copy(self) -> Dict[str, str | bool]:
        return self.adapter.clipboard_copy()

    def paste_text(self, text: str) -> Dict[str, str | bool]:
        return self.adapter.paste_text(text)

    def focus_window(self, title: str) -> Dict[str, str | bool]:
        return self.adapter.focus_window(title)
