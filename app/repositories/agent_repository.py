from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from app.agents.agent_definition import AgentDefinition
from app.utils.atomic_io import write_json_atomic
from config import AGENT_TASKS_DIR


class AgentRepository:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else AGENT_TASKS_DIR / "agent_definitions.json"

    def list(self) -> list[AgentDefinition]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return []
        if not isinstance(raw, list):
            return []
        return [AgentDefinition.from_dict(item) for item in raw if isinstance(item, dict)]

    def save_all(self, definitions: Iterable[AgentDefinition]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(self.path, [definition.as_dict() for definition in definitions], indent=2, ensure_ascii=False)

    def upsert(self, definition: AgentDefinition) -> AgentDefinition:
        definitions = [item for item in self.list() if item.name.lower() != definition.name.lower()]
        definitions.append(definition)
        self.save_all(definitions)
        return definition

    def delete(self, name: str) -> bool:
        definitions = self.list()
        kept = [item for item in definitions if item.name.lower() != str(name or "").strip().lower()]
        if len(kept) == len(definitions):
            return False
        self.save_all(kept)
        return True
