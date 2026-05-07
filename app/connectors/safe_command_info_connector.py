from __future__ import annotations

import platform
import subprocess
from typing import Dict


class SafeCommandInfoConnector:
    """Connector boundary for allowlisted read-only system information commands."""

    SAFE_COMMANDS = {
        "ipconfig": ["ipconfig"],
        "whoami": ["whoami"],
        "hostname": ["hostname"],
        "systeminfo": ["systeminfo"],
        "system info": ["systeminfo"],
        "system status": ["systeminfo"],
        "system update": ["systeminfo"],
        "system updates": ["systeminfo"],
        "system report": ["systeminfo"],
        "system health": ["systeminfo"],
        "computer status": ["systeminfo"],
        "pc status": ["systeminfo"],
        "tasklist": ["tasklist"],
        "disk": ["wmic", "logicaldisk", "get", "caption,freespace,size"],
        "space": ["wmic", "logicaldisk", "get", "caption,freespace,size"],
    }
    BLOCKED_WORDS = (
        "shutdown", "restart", "format", "diskpart", "reg delete", "bcdedit",
        "del ", "erase ", "remove-item", "rm ", "rmdir", "rd ",
    )

    def execute(self, command: str) -> Dict[str, str | bool]:
        normalized = " ".join((command or "").strip().lower().split())
        if not normalized:
            return {"success": False, "action": "safe_command_info", "message": "Tell me which safe command to explain or run."}
        if any(word in normalized for word in self.BLOCKED_WORDS):
            return {"success": False, "action": "safe_command_info", "message": "That command is blocked. I only run safe built-in system information commands."}
        matched = None
        for key, cmd in self.SAFE_COMMANDS.items():
            if normalized == key or normalized.endswith(f" {key}") or key in normalized.split():
                matched = cmd
                break
        if matched is None:
            return {
                "success": False,
                "action": "safe_command_info",
                "message": "I can only run hardcoded safe read-only commands like ipconfig, whoami, hostname, systeminfo, tasklist, and disk space.",
            }
        try:
            result = subprocess.run(matched, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)
            output = (result.stdout or result.stderr or "").strip()
            if not output:
                output = f"{matched[0]} completed with exit code {result.returncode}."
            if len(output) > 3500:
                output = output[:3500] + "\n..."
            return {"success": True, "action": "safe_command_info", "message": output}
        except Exception as exc:
            return {"success": False, "action": "safe_command_info", "message": f"Could not run the safe command on {platform.system()}: {exc}"}
