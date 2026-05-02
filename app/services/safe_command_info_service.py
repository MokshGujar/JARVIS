from __future__ import annotations

import platform
import subprocess
from pathlib import Path
from typing import Dict


class SafeCommandInfoService:
    """Hardcoded, non-generative system information commands."""

    WINDOWS_COMMANDS = [
        (("disk space", "disk usage", "storage", "free space", "c drive space"), ["wmic", "logicaldisk", "get", "caption,freespace,size", "/format:list"]),
        (("running processes", "list processes", "show processes", "active processes", "tasklist"), ["tasklist", "/fo", "table"]),
        (("ip address", "my ip", "network info", "ipconfig"), ["ipconfig", "/all"]),
        (("ping", "internet connection", "connected to internet"), ["ping", "-n", "4", "google.com"]),
        (("wifi networks", "available wifi", "wireless networks"), ["netsh", "wlan", "show", "networks"]),
        (("system info", "computer info", "hardware info", "pc info", "specs"), ["systeminfo"]),
        (("cpu usage", "processor usage"), ["wmic", "cpu", "get", "loadpercentage"]),
        (("memory usage", "ram usage"), ["wmic", "OS", "get", "FreePhysicalMemory,TotalVisibleMemorySize", "/Value"]),
        (("windows version", "os version"), ["cmd", "/c", "ver"]),
        (("battery", "battery level", "power status"), ["powershell", "-NoProfile", "-Command", "(Get-WmiObject -Class Win32_Battery).EstimatedChargeRemaining"]),
        (("current time", "what time", "system time"), ["cmd", "/c", "time", "/t"]),
        (("current date", "what date", "system date"), ["cmd", "/c", "date", "/t"]),
        (("desktop files", "files on desktop"), ["cmd", "/c", "dir", str(Path.home() / "Desktop")]),
        (("downloads", "files in downloads"), ["cmd", "/c", "dir", str(Path.home() / "Downloads")]),
    ]

    BLOCKED_WORDS = {
        "shutdown", "restart", "format", "diskpart", "reg delete", "bcdedit",
        "taskkill", "stop-process", "rm -rf", "del /", "rmdir /s",
    }

    def can_handle(self, command: str) -> bool:
        lowered = self._normalize(command)
        return self._match(lowered) is not None or lowered.startswith("run command ") or lowered.startswith("cmd ")

    def execute(self, command: str) -> Dict[str, str | bool]:
        lowered = self._normalize(command)
        if any(word in lowered for word in self.BLOCKED_WORDS):
            return {"success": False, "action": "safe_command_info", "message": "That command is blocked. I only run safe built-in system information commands."}

        matched = self._match(lowered)
        if matched is None:
            return {"success": False, "action": "safe_command_info", "message": "I only run hardcoded safe system information commands, not generated shell commands."}

        if platform.system() != "Windows":
            return {"success": False, "action": "safe_command_info", "message": "Safe command info is currently implemented for Windows."}

        try:
            result = subprocess.run(matched, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)
            output = (result.stdout or result.stderr or "Command executed with no output.").strip()
            return {"success": True, "action": "safe_command_info", "message": output[:3000]}
        except Exception as exc:
            return {"success": False, "action": "safe_command_info", "message": f"Could not run safe command: {exc}"}

    def _normalize(self, command: str) -> str:
        return " ".join((command or "").strip().lower().split()).strip(" .!?")

    def _match(self, lowered: str) -> list[str] | None:
        for keywords, command in self.WINDOWS_COMMANDS:
            if any(keyword in lowered for keyword in keywords):
                return command
        return None

