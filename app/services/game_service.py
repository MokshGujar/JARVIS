from __future__ import annotations

import re
from pathlib import Path
from typing import Dict

from app.connectors.game_launcher_connector import GameLauncherConnector

try:
    import psutil
    PSUTIL_IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover
    psutil = None
    PSUTIL_IMPORT_ERROR = exc

try:
    import winreg
except Exception:  # pragma: no cover
    winreg = None


class GameService:
    """Steam/Epic helpers adapted without generated commands or Gemini."""

    SENSITIVE_WORDS = ("install", "download", "schedule", "cancel schedule", "shutdown after")

    def __init__(self, launcher: GameLauncherConnector | None = None) -> None:
        self.launcher = launcher or GameLauncherConnector()

    def can_handle(self, command: str) -> bool:
        lowered = self._normalize(command)
        patterns = (
            r"^(?:open|launch|start)\s+(?:steam|epic|epic games|epic games launcher)$",
            r"^(?:steam|epic|epic games|game|games)\s+(?:status|running)$",
            r"^(?:is\s+)?(?:steam|epic|epic games)\s+running$",
            r"^(?:list|show)\s+(?:installed\s+)?games$",
            r"^(?:list|show)\s+(?:my\s+)?(?:steam\s+)?(?:installed\s+)?games$",
            r"^(?:steam|game|games)\s+download\s+status$",
            r"^(?:open\s+)?(?:steam\s+)?downloads$",
            r"^(?:update|check\s+updates?\s+for|check)\s+(?:steam\s+)?games$",
            r"^(?:install|download)\s+.+\s+(?:on|from)\s+(?:steam|epic|epic games)$",
            r"^schedule\s+.+\s+(?:on|from)\s+(?:steam|epic|epic games)$",
            r"^cancel\s+scheduled?\s+(?:game|steam|epic).*$",
            r"^shutdown\s+after\s+.*(?:game|steam|download).*$",
        )
        return any(re.match(pattern, lowered) for pattern in patterns)

    def prepare_sensitive(self, command: str) -> Dict[str, str | bool | dict] | None:
        lowered = self._normalize(command)
        if not self.can_handle(lowered):
            return None
        if "download status" in lowered or re.search(r"\bdownloads?\b", lowered):
            return None
        if not any(word in lowered for word in self.SENSITIVE_WORDS):
            return None

        if "shutdown after" in lowered:
            return self._pending("shutdown_after_download", "", "Shut down after the current game download finishes")
        if "cancel schedule" in lowered or "cancel scheduled" in lowered:
            return self._pending("cancel_schedule", "", "Cancel the scheduled game download action")
        if "schedule" in lowered:
            target = self._extract_game_name(lowered) or "game update"
            return self._pending("schedule", target, f"Schedule game action for {target}")
        if "install" in lowered or "download" in lowered:
            target = self._extract_game_name(lowered)
            if not target:
                return {
                    "success": False,
                    "action": "game_confirmation",
                    "message": "Tell me which game to install or download.",
                }
            return self._pending("install", target, f"Open the store page for {target}")
        return None

    def execute(self, command: str) -> Dict[str, str | bool]:
        lowered = self._normalize(command)
        if "status" in lowered or "running" in lowered:
            return self.status()
        if "download status" in lowered or "downloads" in lowered:
            return self.launcher.open_steam_downloads()
        if "list" in lowered or "installed" in lowered:
            return self.list_installed_games()
        if "update" in lowered:
            return self.launcher.open_steam_downloads(updates=True)
        if "steam" in lowered:
            return self.launcher.open_steam()
        if "epic" in lowered:
            return self.launcher.open_epic_launcher()
        return {"success": False, "action": "game", "message": "Game support covers Steam/Epic status, lists, updates, install confirmations, and download status."}

    def confirm(self, pending: dict) -> Dict[str, str | bool]:
        action = pending.get("action")
        target = pending.get("target") or ""
        if action == "install":
            return self.launcher.open_steam_store_search(target)
        if action == "schedule":
            return {"success": True, "action": "game", "message": f"Scheduled game action noted for {target}. Jarvis does not auto-install without you confirming at install time."}
        if action == "cancel_schedule":
            return {"success": True, "action": "game", "message": "Cancelled the scheduled game action."}
        if action == "shutdown_after_download":
            return {"success": False, "action": "game", "message": "Shutdown-after-download is recognized, but automatic shutdown is disabled for safety."}
        return {"success": False, "action": "game", "message": "No game action is waiting for confirmation."}

    def status(self) -> Dict[str, str | bool]:
        if psutil is None:
            return {"success": False, "action": "game", "message": f"Game status is unavailable. Import error: {PSUTIL_IMPORT_ERROR}"}
        processes = {proc.info["name"].lower() for proc in psutil.process_iter(["name"]) if proc.info.get("name")}
        steam = any("steam" in name for name in processes)
        epic = any("epicgameslauncher" in name or "epicwebhelper" in name for name in processes)
        return {
            "success": True,
            "action": "game",
            "message": f"Steam: {'running' if steam else 'not running'}. Epic Games: {'running' if epic else 'not running'}.",
        }

    def list_installed_games(self) -> Dict[str, str | bool]:
        libraries = self._steam_libraries()
        games = []
        for library in libraries:
            for manifest in library.glob("steamapps/appmanifest_*.acf"):
                text = manifest.read_text(encoding="utf-8", errors="ignore")
                match = re.search(r'"name"\s+"([^"]+)"', text)
                if match:
                    games.append(match.group(1))
        if not games:
            return {"success": False, "action": "game", "message": "I could not find installed Steam games on this machine."}
        shown = "\n".join(f"- {name}" for name in sorted(set(games))[:50])
        return {"success": True, "action": "game", "message": shown}

    def _pending(self, action: str, target: str, label: str) -> Dict[str, str | bool | dict]:
        return {
            "success": False,
            "action": "game_confirmation",
            "message": f"{label}. Say yes to continue or no to cancel.",
            "pending": {"action": action, "target": target},
        }

    def _extract_game_name(self, lowered: str) -> str:
        cleaned = re.sub(r"\b(?:can you|please|on steam|from steam|on epic|from epic|game|games|install|download|schedule|update|for me)\b", " ", lowered)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" .!?")
        return cleaned

    def _steam_libraries(self) -> list[Path]:
        root = self._steam_root()
        if root is None:
            return []
        libraries = [root]
        vdf = root / "steamapps" / "libraryfolders.vdf"
        if vdf.exists():
            text = vdf.read_text(encoding="utf-8", errors="ignore")
            for raw_path in re.findall(r'"path"\s+"([^"]+)"', text):
                candidate = Path(raw_path.replace("\\\\", "\\"))
                if candidate.exists():
                    libraries.append(candidate)
        return libraries

    def _steam_root(self) -> Path | None:
        if winreg is not None:
            for hive, key_path in (
                (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
                (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Valve\Steam"),
            ):
                try:
                    with winreg.OpenKey(hive, key_path) as key:
                        value, _ = winreg.QueryValueEx(key, "SteamPath")
                        path = Path(str(value))
                        if path.exists():
                            return path
                except Exception:
                    pass
        for candidate in (
            Path(r"C:\Program Files (x86)\Steam"),
            Path(r"C:\Program Files\Steam"),
        ):
            if candidate.exists():
                return candidate
        return None

    def _normalize(self, command: str) -> str:
        return " ".join((command or "").strip().lower().split()).strip(" .!?")
