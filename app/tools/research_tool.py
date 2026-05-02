from __future__ import annotations

from typing import Any

from app.services.command_risk_service import CommandRiskService
from app.tools.base import ToolContext, ToolRisk


class ResearchTool:
    name = "research"

    def __init__(self, research_service: Any | None = None, *, risk_service: CommandRiskService | None = None) -> None:
        self.research_service = research_service
        self.risk_service = risk_service or CommandRiskService()

    def can_handle(self, intent: str) -> bool:
        return str(intent or "").strip().lower() in {"research", "realtime_search"}

    def classify_risk(self, command: str) -> ToolRisk:
        risk = self.risk_service.classify(command, command_action="research")
        return ToolRisk(level=risk.risk_level, step_up_required=risk.step_up_required, reasons=list(risk.reasons))

    def execute(self, context: ToolContext) -> dict:
        return {"success": False, "action": "unsupported", "message": "Research tool is not wired yet."}
