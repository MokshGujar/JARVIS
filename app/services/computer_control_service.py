from __future__ import annotations

import platform
import subprocess
import time
from pathlib import Path
from typing import Dict, Optional

try:
    import pyautogui
    PYAUTOGUI_IMPORT_ERROR = None
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.05
except Exception as exc:  # pragma: no cover - exercised by availability tests
    pyautogui = None
    PYAUTOGUI_IMPORT_ERROR = exc

try:
    import pyperclip
    PYPERCLIP_IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover
    pyperclip = None
    PYPERCLIP_IMPORT_ERROR = exc


class ComputerControlService:
    """Safe local keyboard/mouse primitives adapted from Mark-XXXV."""

    def available(self) -> bool:
        return pyautogui is not None

    def _unavailable(self) -> Dict[str, str | bool]:
        return {
            "success": False,
            "action": "computer_control",
            "message": f"Computer control is not available. Import error: {PYAUTOGUI_IMPORT_ERROR}",
        }

    def type_text(self, text: str, *, clear_first: bool = False, press_enter: bool = False) -> Dict[str, str | bool]:
        if not self.available():
            return self._unavailable()
        payload = (text or "").strip()
        if not payload:
            return {"success": False, "action": "computer_control", "message": "Tell me what to type."}
        try:
            time.sleep(0.2)
            if clear_first:
                pyautogui.hotkey("ctrl", "a")
                time.sleep(0.05)
                pyautogui.press("delete")
            if len(payload) > 20 and pyperclip is not None:
                pyperclip.copy(payload)
                time.sleep(0.05)
                pyautogui.hotkey("ctrl", "v")
            else:
                pyautogui.typewrite(payload, interval=0.03)
            if press_enter:
                pyautogui.press("enter")
            return {"success": True, "action": "computer_control", "message": "Typed into the active window."}
        except Exception as exc:
            return {"success": False, "action": "computer_control", "message": f"Could not type: {exc}"}

    def hotkey(self, keys: list[str]) -> Dict[str, str | bool]:
        if not self.available():
            return self._unavailable()
        clean_keys = [str(key).strip().lower() for key in keys if str(key).strip()]
        if not clean_keys:
            return {"success": False, "action": "computer_control", "message": "Tell me which keys to press."}
        try:
            pyautogui.hotkey(*clean_keys)
            return {"success": True, "action": "computer_control", "message": f"Pressed {'+'.join(clean_keys)}."}
        except Exception as exc:
            return {"success": False, "action": "computer_control", "message": f"Could not press keys: {exc}"}

    def press(self, key: str) -> Dict[str, str | bool]:
        if not self.available():
            return self._unavailable()
        key = (key or "enter").strip().lower()
        try:
            pyautogui.press(key)
            return {"success": True, "action": "computer_control", "message": f"Pressed {key}."}
        except Exception as exc:
            return {"success": False, "action": "computer_control", "message": f"Could not press {key}: {exc}"}

    def click(self, x: Optional[int] = None, y: Optional[int] = None, *, button: str = "left", clicks: int = 1) -> Dict[str, str | bool]:
        if not self.available():
            return self._unavailable()
        try:
            if x is not None and y is not None:
                pyautogui.click(int(x), int(y), button=button, clicks=clicks)
            else:
                pyautogui.click(button=button, clicks=clicks)
            return {"success": True, "action": "computer_control", "message": "Clicked."}
        except Exception as exc:
            return {"success": False, "action": "computer_control", "message": f"Could not click: {exc}"}

    def scroll(self, direction: str = "down", amount: int = 3) -> Dict[str, str | bool]:
        if not self.available():
            return self._unavailable()
        direction = (direction or "down").lower()
        clicks = abs(int(amount or 3))
        try:
            pyautogui.scroll(clicks if direction == "up" else -clicks)
            return {"success": True, "action": "computer_control", "message": f"Scrolled {direction}."}
        except Exception as exc:
            return {"success": False, "action": "computer_control", "message": f"Could not scroll: {exc}"}

    def screenshot(self, path: str | None = None) -> Dict[str, str | bool]:
        if not self.available():
            return self._unavailable()
        target = Path(path).expanduser() if path else Path.home() / "Desktop" / "jarvis_screenshot.png"
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            pyautogui.screenshot().save(str(target))
            return {"success": True, "action": "computer_control", "message": f"Screenshot saved: {target}"}
        except Exception as exc:
            return {"success": False, "action": "computer_control", "message": f"Could not take screenshot: {exc}"}

    def clipboard_copy(self) -> Dict[str, str | bool]:
        if pyperclip is None:
            return {"success": False, "action": "computer_control", "message": f"Clipboard is unavailable. Import error: {PYPERCLIP_IMPORT_ERROR}"}
        try:
            return {"success": True, "action": "computer_control", "message": pyperclip.paste()}
        except Exception as exc:
            return {"success": False, "action": "computer_control", "message": f"Could not read clipboard: {exc}"}

    def paste_text(self, text: str) -> Dict[str, str | bool]:
        if pyperclip is None:
            return {"success": False, "action": "computer_control", "message": f"Clipboard is unavailable. Import error: {PYPERCLIP_IMPORT_ERROR}"}
        return self.type_text(text, clear_first=False)

    def focus_window(self, title: str) -> Dict[str, str | bool]:
        title = (title or "").strip()
        if not title:
            return {"success": False, "action": "computer_control", "message": "Tell me which window to focus."}
        if platform.system() != "Windows":
            return {"success": False, "action": "computer_control", "message": "Window focus is only supported on Windows."}
        try:
            script = f'(New-Object -ComObject WScript.Shell).AppActivate("{title}")'
            subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, timeout=5)
            return {"success": True, "action": "computer_control", "message": f"Focused {title}."}
        except Exception as exc:
            return {"success": False, "action": "computer_control", "message": f"Could not focus {title}: {exc}"}

