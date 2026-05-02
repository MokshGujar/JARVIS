from pathlib import Path
from typing import Callable, Dict, Optional


DELETE_RECYCLE_UNAVAILABLE_MESSAGE = (
    "Deletion is unavailable because Send2Trash is not installed. "
    "Install Send2Trash so Jarvis can move items to the Recycle Bin "
    "instead of deleting them permanently."
)


def move_to_recycle_bin(
    target: Path,
    *,
    send_to_trash: Optional[Callable[[str], None]],
    is_protected_path: Callable[[Path], bool],
    display_target_name: Callable[[Path], str],
) -> Dict[str, str | bool]:
    if is_protected_path(target):
        return {
            "success": False,
            "action": "delete",
            "message": "That location is protected. Jarvis cannot delete from Windows or critical system folders.",
        }

    if send_to_trash is None:
        return {
            "success": False,
            "action": "delete",
            "message": DELETE_RECYCLE_UNAVAILABLE_MESSAGE,
        }

    try:
        send_to_trash(str(target))
    except Exception as exc:
        return {
            "success": False,
            "action": "delete",
            "message": f"Could not delete {display_target_name(target)}: {exc}",
        }

    return {
        "success": True,
        "action": "delete",
        "message": f"{display_target_name(target)} moved to the Recycle Bin from {target}.",
    }
