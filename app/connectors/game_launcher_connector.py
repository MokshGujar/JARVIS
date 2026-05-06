from __future__ import annotations

import subprocess
import webbrowser
from pathlib import Path
from typing import Dict
from urllib.parse import quote_plus


class GameLauncherConnector:
    """Connector boundary for game launcher/store opening."""

    def open_steam_downloads(self, *, updates: bool = False) -> Dict[str, str | bool]:
        webbrowser.open("steam://open/downloads")
        message = "Opened Steam downloads so you can check updates." if updates else "Opened Steam downloads."
        return {"success": True, "action": "game", "message": message}

    def open_steam(self) -> Dict[str, str | bool]:
        webbrowser.open("steam://open/main")
        return {"success": True, "action": "game", "message": "Opened Steam."}

    def open_steam_store_search(self, target: str) -> Dict[str, str | bool]:
        webbrowser.open(f"https://store.steampowered.com/search/?term={quote_plus(target or '')}")
        return {"success": True, "action": "game", "message": f"Opened the Steam store search for {target}. Review it before installing."}

    def open_epic_launcher(self) -> Dict[str, str | bool]:
        candidates = (
            Path(r"C:\Program Files (x86)\Epic Games\Launcher\Portal\Binaries\Win64\EpicGamesLauncher.exe"),
            Path(r"C:\Program Files\Epic Games\Launcher\Portal\Binaries\Win64\EpicGamesLauncher.exe"),
        )
        for candidate in candidates:
            if candidate.exists():
                subprocess.Popen([str(candidate)])
                return {"success": True, "action": "game", "message": "Opening Epic Games Launcher."}
        webbrowser.open("https://store.epicgames.com/")
        return {"success": True, "action": "game", "message": "Opening Epic Games Launcher."}
