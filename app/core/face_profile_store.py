from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from app.utils.atomic_io import write_json_atomic


class FaceProfileStore:
    def __init__(self, data_dir: Path, *, profile_id: str = "owner-default", user_name: str = "Moksh") -> None:
        self.data_dir = data_dir
        self.profile_id = profile_id
        self.user_name = user_name
        self.profile_path = self.data_dir / "profile.json"
        self.history_path = self.data_dir / "verification_history.jsonl"
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def load_profile(self) -> dict[str, Any] | None:
        if not self.profile_path.exists():
            return None
        try:
            payload = json.loads(self.profile_path.read_text(encoding="utf-8"))
        except Exception:
            return None
        return payload if isinstance(payload, dict) else None

    def save_profile(self, profile: dict[str, Any]) -> None:
        now = time.time()
        profile.setdefault("profile_id", self.profile_id)
        profile.setdefault("user_name", self.user_name)
        profile.setdefault("created_at", now)
        profile["updated_at"] = now
        write_json_atomic(self.profile_path, profile, indent=2, ensure_ascii=True)

    def delete_profile(self) -> None:
        if self.profile_path.exists():
            self.profile_path.unlink()

    def profile_exists(self) -> bool:
        return self.load_profile() is not None

    def append_history(self, item: dict[str, Any]) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        with self.history_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(item, ensure_ascii=True) + "\n")
