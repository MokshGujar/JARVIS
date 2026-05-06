from __future__ import annotations

import ctypes
import platform
import subprocess
from typing import Dict

from app.adapters.ui.pyautogui_adapter import PyAutoGUIAdapter


class LocalSystemAdapter:
    """Adapter boundary for OS UI settings and shell-backed system helpers."""

    def __init__(self, computer_control: object | None = None) -> None:
        self.computer_control = computer_control or PyAutoGUIAdapter()
        self._os = platform.system()

    def can_handle(self, command: str) -> bool:
        return self._normalize(command) in self._command_map()

    def execute(self, command: str) -> Dict[str, str | bool]:
        key = self._normalize(command)
        mapped = self._command_map().get(key)
        if not mapped:
            return {"success": False, "action": "computer_settings", "message": "That computer setting is not supported."}
        if mapped["type"] == "hotkey":
            return self.computer_control.hotkey(mapped["keys"])
        if mapped["type"] == "press":
            return self.computer_control.press(mapped["key"])
        if mapped["type"] == "subprocess":
            try:
                subprocess.Popen(mapped["cmd"])
                return {"success": True, "action": "computer_settings", "message": f"Opened {key}."}
            except Exception as exc:
                return {"success": False, "action": "computer_settings", "message": f"Could not run {key}: {exc}"}
        if mapped["type"] == "lock":
            return self._lock_screen()
        return {"success": False, "action": "computer_settings", "message": "That computer setting is not supported."}

    def _normalize(self, command: str) -> str:
        return " ".join((command or "").strip().lower().split()).strip(" .!?")

    def _command_map(self) -> dict[str, dict]:
        if self._os == "Darwin":
            mod = "command"
            return {
                "copy": {"type": "hotkey", "keys": [mod, "c"]},
                "paste": {"type": "hotkey", "keys": [mod, "v"]},
                "cut": {"type": "hotkey", "keys": [mod, "x"]},
                "undo": {"type": "hotkey", "keys": [mod, "z"]},
                "redo": {"type": "hotkey", "keys": [mod, "shift", "z"]},
                "refresh": {"type": "hotkey", "keys": [mod, "r"]},
                "new tab": {"type": "hotkey", "keys": [mod, "t"]},
                "close tab": {"type": "hotkey", "keys": [mod, "w"]},
                "close window": {"type": "hotkey", "keys": [mod, "w"]},
                "full screen": {"type": "hotkey", "keys": ["ctrl", mod, "f"]},
                "fullscreen": {"type": "hotkey", "keys": ["ctrl", mod, "f"]},
                "switch window": {"type": "hotkey", "keys": [mod, "tab"]},
            }
        return {
            "copy": {"type": "hotkey", "keys": ["ctrl", "c"]},
            "paste": {"type": "hotkey", "keys": ["ctrl", "v"]},
            "cut": {"type": "hotkey", "keys": ["ctrl", "x"]},
            "undo": {"type": "hotkey", "keys": ["ctrl", "z"]},
            "redo": {"type": "hotkey", "keys": ["ctrl", "y"]},
            "select all": {"type": "hotkey", "keys": ["ctrl", "a"]},
            "save": {"type": "hotkey", "keys": ["ctrl", "s"]},
            "save file": {"type": "hotkey", "keys": ["ctrl", "s"]},
            "refresh": {"type": "press", "key": "f5"},
            "reload": {"type": "press", "key": "f5"},
            "new tab": {"type": "hotkey", "keys": ["ctrl", "t"]},
            "close tab": {"type": "hotkey", "keys": ["ctrl", "w"]},
            "next tab": {"type": "hotkey", "keys": ["ctrl", "tab"]},
            "previous tab": {"type": "hotkey", "keys": ["ctrl", "shift", "tab"]},
            "go back": {"type": "hotkey", "keys": ["alt", "left"]},
            "go forward": {"type": "hotkey", "keys": ["alt", "right"]},
            "close window": {"type": "hotkey", "keys": ["alt", "f4"]},
            "close current window": {"type": "hotkey", "keys": ["alt", "f4"]},
            "minimize window": {"type": "hotkey", "keys": ["win", "down"]},
            "maximize window": {"type": "hotkey", "keys": ["win", "up"]},
            "full screen": {"type": "press", "key": "f11"},
            "fullscreen": {"type": "press", "key": "f11"},
            "show desktop": {"type": "hotkey", "keys": ["win", "d"]},
            "switch window": {"type": "hotkey", "keys": ["alt", "tab"]},
            "task manager": {"type": "hotkey", "keys": ["ctrl", "shift", "esc"]},
            "open task manager": {"type": "hotkey", "keys": ["ctrl", "shift", "esc"]},
            "file explorer": {"type": "subprocess", "cmd": ["explorer.exe"]},
            "open file explorer": {"type": "subprocess", "cmd": ["explorer.exe"]},
            "settings": {"type": "subprocess", "cmd": ["cmd", "/c", "start", "ms-settings:"]},
            "lock screen": {"type": "lock"},
            "volume up": {"type": "press", "key": "volumeup"},
            "volume down": {"type": "press", "key": "volumedown"},
            "mute": {"type": "press", "key": "volumemute"},
            "unmute": {"type": "press", "key": "volumemute"},
        }

    def _lock_screen(self) -> Dict[str, str | bool]:
        if self._os != "Windows":
            return {"success": False, "action": "computer_settings", "message": "Lock screen is only supported on Windows right now."}
        try:
            ctypes.windll.user32.LockWorkStation()
            return {"success": True, "action": "computer_settings", "message": "Locked the screen."}
        except Exception as exc:
            return {"success": False, "action": "computer_settings", "message": f"Could not lock the screen: {exc}"}
