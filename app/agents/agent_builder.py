from __future__ import annotations

import re
import time

from app.agents.agent_definition import AgentDefinition


UNSAFE_AGENT_TOOLS = {"terminal", "code_edit", "gmail", "whatsapp", "message", "phone"}


class AgentBuilder:
    def build_draft(self, command: str, *, owner_scope: str = "session") -> dict:
        text = str(command or "").strip()
        lowered = text.lower()
        if any(tool in lowered for tool in ("terminal", "shell", "execute code", "send email", "send whatsapp", "call ")):
            return {
                "success": False,
                "action": "agent_rejected",
                "message": "That agent would need unsafe tools. Draft a read-only agent or explicitly approve a narrower tool scope later.",
            }

        name = self._name_for(lowered)
        purpose = self._purpose_for(text)
        tools = self._tools_for(lowered)
        definition = AgentDefinition(
            name=name,
            purpose=purpose,
            allowed_tools=tools,
            schedule="manual",
            trigger="manual",
            memory_scope="session",
            risk_profile="LOW",
            output_format="summary",
            enabled=False,
            status="draft",
            created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            owner_scope=owner_scope,
        )
        return {
            "success": True,
            "action": "agent_draft_created",
            "message": f"Drafted agent '{definition.name}'. Approval is required before it can run.",
            "definition": definition.as_dict(),
        }

    @staticmethod
    def _name_for(lowered: str) -> str:
        if "ai news" in lowered:
            return "AI news tracker"
        if "file" in lowered:
            return "File monitor"
        if "briefing" in lowered:
            return "Briefing assistant"
        if "memory" in lowered:
            return "Memory summarizer"
        cleaned = re.sub(r"[^a-z0-9 ]", " ", lowered)
        tokens = [token for token in cleaned.split() if token not in {"create", "an", "agent", "that"}]
        return " ".join(tokens[:4]).strip().title() or "Jarvis agent"

    @staticmethod
    def _purpose_for(command: str) -> str:
        return str(command or "").strip() or "Assist with a bounded read-only task."

    @staticmethod
    def _tools_for(lowered: str) -> list[str]:
        if "ai news" in lowered or "research" in lowered:
            return ["research", "summary"]
        if "file" in lowered:
            return ["file", "summary"]
        if "briefing" in lowered:
            return ["reminder", "summary"]
        if "memory" in lowered:
            return ["memory", "summary"]
        return ["summary"]
