from __future__ import annotations

import time
from typing import Any

try:
    from pywinauto import Desktop
    from pywinauto import keyboard

    PYWINAUTO_IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - covered through unavailable adapter tests
    Desktop = None
    keyboard = None
    PYWINAUTO_IMPORT_ERROR = exc


class PywinautoAdapter:
    """Thin pywinauto boundary used by AppInteractionTool.

    The tool owns safety policy and semantic action mapping; this adapter only
    exposes low-level desktop primitives and returns clean result dictionaries.
    """

    MODIFIER_KEYS = {"ctrl", "control", "alt", "shift", "win", "windows"}
    KEY_ALIASES = {
        "ctrl": "^",
        "control": "^",
        "alt": "%",
        "shift": "+",
        "win": "{VK_LWIN}",
        "windows": "{VK_LWIN}",
        "enter": "{ENTER}",
        "backspace": "{BACKSPACE}",
        "delete": "{DELETE}",
        "tab": "{TAB}",
        "esc": "{ESC}",
        "escape": "{ESC}",
        "left": "{LEFT}",
        "right": "{RIGHT}",
        "up": "{UP}",
        "down": "{DOWN}",
        "f5": "{F5}",
    }

    def __init__(self, *, backend: str = "uia", type_delay_ms: int = 10) -> None:
        self.backend = backend or "uia"
        self.type_delay_ms = max(0, int(type_delay_ms or 0))

    def is_available(self) -> bool:
        return Desktop is not None and keyboard is not None

    def get_active_window(self) -> dict[str, Any]:
        if not self.is_available():
            return self._unavailable("get_active_window")
        try:
            window = Desktop(backend=self.backend).get_active()
            title = self._window_title(window)
            return {"success": True, "action": "get_active_window", "window": window, "title": title}
        except Exception as exc:
            return {"success": False, "action": "get_active_window", "message": f"Could not read the active window: {exc}"}

    def read_window_title(self) -> dict[str, Any]:
        active = self.get_active_window()
        if not bool(active.get("success")):
            return active
        return {
            "success": True,
            "action": "read_window_title",
            "message": str(active.get("title") or ""),
            "title": str(active.get("title") or ""),
        }

    def focus_window(self, title: str) -> dict[str, Any]:
        if not self.is_available():
            return self._unavailable("focus_window")
        target = str(title or "").strip()
        if not target:
            return {"success": False, "action": "focus_window", "message": "Tell me which window to focus."}
        try:
            window = Desktop(backend=self.backend).window(title_re=f".*{target}.*")
            window.set_focus()
            return {"success": True, "action": "focus_window", "message": f"Focused {target}.", "title": self._window_title(window)}
        except Exception as exc:
            return {"success": False, "action": "focus_window", "message": f"Could not focus {target}: {exc}"}

    def type_text(self, text: str) -> dict[str, Any]:
        if not self.is_available():
            return self._unavailable("type_text")
        value = str(text or "")
        if not value:
            return {"success": False, "action": "type_text", "message": "Tell me what to type."}
        try:
            keyboard.send_keys(value, with_spaces=True, pause=self.type_delay_ms / 1000.0)
            return {"success": True, "action": "type_text", "message": "Typed into the active window."}
        except Exception as exc:
            return {"success": False, "action": "type_text", "message": f"Could not type into the active window: {exc}"}

    def press_key(self, key: str) -> dict[str, Any]:
        if not self.is_available():
            return self._unavailable("press_key")
        clean_key = str(key or "").strip().lower()
        if not clean_key:
            return {"success": False, "action": "press_key", "message": "Tell me which key to press."}
        try:
            keyboard.send_keys(self._format_key(clean_key))
            return {"success": True, "action": "press_key", "message": f"Pressed {clean_key}."}
        except Exception as exc:
            return {"success": False, "action": "press_key", "message": f"Could not press {clean_key}: {exc}"}

    def press_hotkey(self, keys: list[str] | tuple[str, ...]) -> dict[str, Any]:
        if not self.is_available():
            return self._unavailable("press_hotkey")
        clean_keys = [str(key).strip().lower() for key in keys if str(key).strip()]
        if not clean_keys:
            return {"success": False, "action": "press_hotkey", "message": "Tell me which keys to press."}
        try:
            keyboard.send_keys(self._format_hotkey(clean_keys))
            return {"success": True, "action": "press_hotkey", "message": f"Pressed {'+'.join(clean_keys)}."}
        except Exception as exc:
            return {"success": False, "action": "press_hotkey", "message": f"Could not press {'+'.join(clean_keys)}: {exc}"}

    def click_text(self, text: str) -> dict[str, Any]:
        if not self.is_available():
            return self._unavailable("click_text")
        target = str(text or "").strip()
        if not target:
            return {"success": False, "action": "click_text", "message": "Tell me what to click."}
        try:
            active = Desktop(backend=self.backend).get_active()
            control = active.child_window(title=target)
            if not control.exists(timeout=1):
                return {"success": False, "action": "click_text", "message": f"I could not confidently find {target}."}
            control.click_input()
            return {"success": True, "action": "click_text", "message": f"Clicked {target}."}
        except Exception as exc:
            return {"success": False, "action": "click_text", "message": f"Could not click {target}: {exc}"}

    def click_coordinates(self, x: int, y: int) -> dict[str, Any]:
        if not self.is_available():
            return self._unavailable("click_coordinates")
        try:
            active = Desktop(backend=self.backend).get_active()
            active.click_input(coords=(int(x), int(y)))
            return {"success": True, "action": "click_coordinates", "message": "Clicked coordinates."}
        except Exception as exc:
            return {"success": False, "action": "click_coordinates", "message": f"Could not click coordinates: {exc}"}

    def verify_text_present(self, text: str) -> dict[str, Any]:
        if not self.is_available():
            return self._unavailable("verify_text_present")
        target = str(text or "").strip()
        if not target:
            return {"success": False, "action": "verify_text_present", "message": "Tell me what text to verify."}
        try:
            active = Desktop(backend=self.backend).get_active()
            found = active.child_window(title=target).exists(timeout=1)
            return {
                "success": bool(found),
                "action": "verify_text_present",
                "message": "Text found." if found else "Text was not found.",
                "verified_text": target if found else None,
            }
        except Exception as exc:
            return {"success": False, "action": "verify_text_present", "message": f"Could not verify text: {exc}"}

    @staticmethod
    def _window_title(window: Any) -> str:
        try:
            title = window.window_text()
            return str(title or "")
        except Exception:
            return ""

    def _format_key(self, key: str) -> str:
        normalized = str(key or "").strip().lower()
        if normalized in self.KEY_ALIASES:
            return self.KEY_ALIASES[normalized]
        if len(normalized) == 1:
            return normalized
        return "{" + normalized.upper() + "}"

    def _format_hotkey(self, keys: list[str]) -> str:
        modifiers = "".join(self.KEY_ALIASES[key] for key in keys[:-1] if key in self.MODIFIER_KEYS and key in self.KEY_ALIASES)
        last = keys[-1]
        if last in self.MODIFIER_KEYS:
            return "".join(self._format_key(key) for key in keys)
        return f"{modifiers}{self._format_key(last)}"

    @staticmethod
    def _unavailable(action: str) -> dict[str, Any]:
        return {
            "success": False,
            "action": action,
            "message": f"Desktop interaction is unavailable because pywinauto is missing: {PYWINAUTO_IMPORT_ERROR}",
            "error": "pywinauto_unavailable",
        }
