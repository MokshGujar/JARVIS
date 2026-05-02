from __future__ import annotations

from app.services.command_risk_service import CommandRiskService
from app.tools.base import ToolContext, ToolRisk


class ContentTool:
    name = "content"

    def __init__(self, *, risk_service: CommandRiskService | None = None) -> None:
        self.risk_service = risk_service or CommandRiskService()

    def can_handle(self, intent: str) -> bool:
        return str(intent or "").strip().lower() in {"content", "generate_image", "write_content"}

    def classify_risk(self, command: str) -> ToolRisk:
        risk = self.risk_service.classify(command, command_action="task")
        return ToolRisk(level=risk.risk_level, step_up_required=risk.step_up_required, reasons=list(risk.reasons))

    def execute(self, context: ToolContext) -> dict:
        return {"success": False, "action": "unsupported", "message": "Content tool is not wired yet."}
