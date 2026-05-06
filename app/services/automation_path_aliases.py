from __future__ import annotations

import os
from pathlib import Path

try:
    import winreg
except Exception:
    winreg = None


def read_windows_shell_folder(value_name: str, default: Path) -> Path:
    if winreg is None:
        return default
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
        ) as key:
            value, _ = winreg.QueryValueEx(key, value_name)
            expanded = os.path.expandvars(str(value))
            candidate = Path(expanded)
            if candidate.exists():
                return candidate
    except Exception:
        pass
    return default


def build_user_path_aliases() -> dict[str, Path]:
    home = Path.home()
    onedrive = home / "OneDrive"
    return {
        "desktop": read_windows_shell_folder("Desktop", onedrive / "Desktop" if (onedrive / "Desktop").exists() else home / "Desktop"),
        "documents": read_windows_shell_folder("Personal", onedrive / "Documents" if (onedrive / "Documents").exists() else home / "Documents"),
        "downloads": read_windows_shell_folder("{374DE290-123F-4565-9164-39C4925E467B}", home / "Downloads"),
        "home": home,
        "music": read_windows_shell_folder("My Music", onedrive / "Music" if (onedrive / "Music").exists() else home / "Music"),
        "pictures": read_windows_shell_folder("My Pictures", onedrive / "Pictures" if (onedrive / "Pictures").exists() else home / "Pictures"),
        "videos": read_windows_shell_folder("My Video", onedrive / "Videos" if (onedrive / "Videos").exists() else home / "Videos"),
    }
