from __future__ import annotations

import logging
import os
import re
import time
import urllib.parse
from pathlib import Path
from typing import Callable, Dict, Iterable

from config import BASE_DIR as CONFIG_BASE_DIR
from app.orchestrator.action_plan import ActionPlan, ActionStep
from app.orchestrator.tool_executor import ToolExecutor
from app.tools.automation_domain_helper import ServiceBackedDomainHelper
from app.services.contact_match_service import ContactCandidate, ContactMatchService
from app.services.message_action_service import MessageActionService
from app.tools.base import ToolContext

try:
    from send2trash import send2trash
    SEND2TRASH_IMPORT_ERROR = None
except Exception as exc:
    send2trash = None
    SEND2TRASH_IMPORT_ERROR = exc


logger = logging.getLogger("J.A.R.V.I.S")


def _runtime_base_dir() -> Path:
    try:
        from app.services import automation_service as automation_module

        return automation_module.BASE_DIR
    except Exception:
        return CONFIG_BASE_DIR



class AutomationSystemCompatibility(ServiceBackedDomainHelper):

    def _looks_like_browser_control(self, lowered: str) -> bool:
            return bool(re.match(
                r"^(?:browser|in browser|on browser|playwright|open url|go to|browser search|search browser|"
                r"click browser|browser click|type in browser|browser type|smart type in browser|fill form|"
                r"get page text|read page text|close browser|incognito)\b",
                lowered,
            ))


    def _execute_browser_control(self, command: str) -> Dict[str, str | bool] | None:
            return self._execute_browser_tool(command)


    def _looks_like_computer_control(self, lowered: str) -> bool:
            return bool(re.match(
                r"^(?:smart type|clear field and type|paste|press key|press|hotkey|shortcut|click|double click|"
                r"right click|scroll|take screenshot|screenshot|focus window|clipboard|read clipboard|paste text)\b",
                lowered,
            ))


    def _execute_computer_control(self, command: str) -> Dict[str, str | bool] | None:
            match = re.match(r"^(?:smart type|clear field and type)\s+(.+?)[.!?]*$", command, flags=re.IGNORECASE)
            if match:
                return self.computer_control_service.type_text(match.group(1).strip(), clear_first=True)

            match = re.match(r"^(?:paste text|paste)\s+(.+?)[.!?]*$", command, flags=re.IGNORECASE)
            if match:
                return self.computer_control_service.paste_text(match.group(1).strip())

            match = re.match(r"^(?:press key|press)\s+(.+?)[.!?]*$", command, flags=re.IGNORECASE)
            if match:
                return self.computer_control_service.press(match.group(1).strip())

            match = re.match(r"^(?:hotkey|shortcut)\s+(.+?)[.!?]*$", command, flags=re.IGNORECASE)
            if match:
                keys = [part.strip() for part in re.split(r"\s*\+\s*|\s+and\s+", match.group(1)) if part.strip()]
                return self.computer_control_service.hotkey(keys)

            coord_match = re.match(r"^(?P<button>right\s+click|double\s+click|click)(?:\s+(?P<x>\d+)\s*,?\s+(?P<y>\d+))?[.!?]*$", command, flags=re.IGNORECASE)
            if coord_match:
                button_phrase = coord_match.group("button").lower()
                button = "right" if "right" in button_phrase else "left"
                clicks = 2 if "double" in button_phrase else 1
                x = int(coord_match.group("x")) if coord_match.group("x") else None
                y = int(coord_match.group("y")) if coord_match.group("y") else None
                return self.computer_control_service.click(x, y, button=button, clicks=clicks)

            match = re.match(r"^scroll\s*(up|down)?(?:\s+(\d+))?[.!?]*$", command, flags=re.IGNORECASE)
            if match:
                return self.computer_control_service.scroll(match.group(1) or "down", int(match.group(2) or 3))

            if re.match(r"^(?:take screenshot|screenshot)[.!?]*$", command, flags=re.IGNORECASE):
                return self.computer_control_service.screenshot()

            match = re.match(r"^focus window\s+(.+?)[.!?]*$", command, flags=re.IGNORECASE)
            if match:
                return self.computer_control_service.focus_window(match.group(1).strip())

            if re.match(r"^(?:clipboard|read clipboard)[.!?]*$", command, flags=re.IGNORECASE):
                return self.computer_control_service.clipboard_copy()

            return None


    def _looks_like_youtube_tool(self, lowered: str) -> bool:
            return bool(
                "youtube" in lowered
                and any(token in lowered for token in ("summarize", "summary", "transcript", "metadata", "info", "trending"))
            )


    def _execute_youtube_tool(self, command: str) -> Dict[str, str | bool] | None:
            lowered = command.lower()
            url_match = re.search(r"(https?://\S+|youtu\.be/\S+|youtube\.com/\S+)", command, flags=re.IGNORECASE)
            url = url_match.group(1).strip(" .!?") if url_match else ""
            if "summar" in lowered or "transcript" in lowered:
                if not url and self._last_web_target and "youtu" in self._last_web_target:
                    url = self._last_web_target
                return self.youtube_tools_service.summarize(url)
            if "metadata" in lowered or re.search(r"\binfo\b", lowered):
                if not url and self._last_web_target and "youtu" in self._last_web_target:
                    url = self._last_web_target
                return self.youtube_tools_service.info(url)
            if "trending" in lowered:
                region_match = re.search(r"\b(?:in|for)\s+([a-z]{2})\b", lowered)
                return self.youtube_tools_service.trending((region_match.group(1) if region_match else "US").upper())
            return None


    def _looks_like_extended_setting(self, lowered: str) -> bool:
            normalized = self._normalize_extended_setting(lowered)
            return self.computer_settings_service.can_handle(normalized)


    def _normalize_extended_setting(self, lowered: str) -> str:
            return re.sub(r"^(?:please\s+)?(?:do\s+)?(?:computer\s+)?", "", lowered).strip(" .!?")


    def _looks_like_safe_command_info(self, lowered: str) -> bool:
            explicit = (
                "safe command",
                "run safe command",
                "system info",
                "computer info",
                "hardware info",
                "pc info",
                "disk space",
                "disk usage",
                "storage",
                "free space",
                "running processes",
                "list processes",
                "ip address",
                "network info",
                "wifi networks",
                "cpu usage",
                "memory usage",
                "ram usage",
                "windows version",
                "os version",
                "battery",
                "battery level",
                "current time",
                "current date",
            )
            return any(phrase in lowered for phrase in explicit) or lowered.startswith(("run command ", "cmd "))


    @staticmethod
    def _looks_like_local_system_status(lowered: str) -> bool:
            text = re.sub(r"\s+", " ", str(lowered or "").strip().lower()).strip(" .!?")
            return bool(
                re.match(
                    r"^(?:show system status|give me system status|give me system updates|system update|system report|system health|show computer status|show pc status)$",
                    text,
                )
            )


    def _match_system_command(self, lowered: str) -> str | None:
            text = lowered.strip().rstrip(".!?")
            exact = {
                "mute": "mute",
                "mute system": "mute",
                "mute the system": "mute",
                "unmute": "unmute",
                "unmute system": "unmute",
                "unmute the system": "unmute",
                "volume up": "volume up",
                "turn volume up": "volume up",
                "turn the volume up": "volume up",
                "increase volume": "volume up",
                "volume down": "volume down",
                "turn volume down": "volume down",
                "turn the volume down": "volume down",
                "decrease volume": "volume down",
                "lower volume": "volume down",
                "show desktop": "show desktop",
                "show the desktop": "show desktop",
                "switch window": "switch window",
                "switch windows": "switch window",
                "switch app": "switch window",
                "switch apps": "switch window",
                "next window": "switch window",
                "close this window": "close current window",
                "close current window": "close current window",
                "close the current window": "close current window",
                "minimize window": "minimize window",
                "minimize this window": "minimize window",
                "minimize current window": "minimize window",
                "fullscreen": "fullscreen",
                "full screen": "fullscreen",
                "toggle fullscreen": "fullscreen",
                "open task manager": "task manager",
                "start task manager": "task manager",
                "launch task manager": "task manager",
            }
            if text in exact:
                return exact[text]
            return None


    def _system_command(self, command: str) -> Dict[str, str | bool]:
            keymap = {
                "mute": "volume mute",
                "unmute": "volume mute",
                "volume up": "volume up",
                "volume down": "volume down",
                "show desktop": "windows+d",
                "switch window": "alt+tab",
                "close current window": "alt+f4",
                "minimize window": "windows+down",
                "fullscreen": "f11",
                "task manager": "ctrl+shift+esc",
            }
            hotkey = keymap.get(command)
            if not hotkey:
                return {"success": False, "action": "system", "message": f"I don't know how to run the system command {command}."}

            result = self.computer_control_service.hotkey(hotkey.split("+"))
            if bool(result.get("success")):
                logger.info("[AUTOMATION] Ran system command: %s", command)
                return {"success": True, "action": "system", "message": f"Done {command}."}
            return {
                "success": False,
                "action": "system",
                "message": str(result.get("message") or f"I could not run {command}."),
            }


