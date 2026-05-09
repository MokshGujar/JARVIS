from __future__ import annotations

import time

from app.agents.agent_definition import AgentDefinition
from app.repositories.agent_repository import AgentRepository


class AgentRegistry:
    def __init__(self, repository: AgentRepository | None = None) -> None:
        self.repository = repository or AgentRepository()

    def save_draft(self, definition: AgentDefinition) -> AgentDefinition:
        definition.enabled = False
        definition.status = "draft"
        return self.repository.upsert(definition)

    def approve(self, name: str) -> dict:
        definition = self.get(name)
        if definition is None:
            return {"success": False, "action": "agent_not_found", "message": "I could not find that agent draft."}
        definition.enabled = True
        definition.status = "enabled"
        self.repository.upsert(definition)
        return {"success": True, "action": "agent_enabled", "message": f"Enabled agent '{definition.name}'."}

    def disable(self, name: str) -> bool:
        definition = self.get(name)
        if definition is None:
            return False
        definition.enabled = False
        definition.status = "disabled"
        self.repository.upsert(definition)
        return True

    def delete(self, name: str) -> bool:
        return self.repository.delete(name)

    def list(self) -> list[AgentDefinition]:
        return self.repository.list()

    def get(self, name: str) -> AgentDefinition | None:
        normalized = str(name or "").strip().lower()
        for definition in self.repository.list():
            if definition.name.lower() == normalized:
                return definition
        return None

    def run_now(self, name: str, *, requested_tool: str | None = None) -> dict:
        definition = self.get(name)
        if definition is None:
            return {"success": False, "action": "agent_not_found", "message": "I could not find that agent."}
        if not definition.enabled:
            return {"success": False, "action": "agent_disabled", "message": "That agent is disabled."}
        if requested_tool and not definition.can_use_tool(requested_tool):
            return {"success": False, "action": "agent_tool_denied", "message": "That agent is not allowed to use that tool."}
        definition.last_run_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.repository.upsert(definition)
        return {"success": True, "action": "agent_run_queued", "message": f"Queued agent '{definition.name}' for a policy-gated run."}
