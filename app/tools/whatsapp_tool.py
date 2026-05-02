from __future__ import annotations

from typing import Any

from app.services.command_risk_service import CommandRiskService
from app.tools.base import ToolContext, ToolRisk


class WhatsAppTool:
    name = "whatsapp"

    def __init__(self, automation_bridge: Any, *, risk_service: CommandRiskService | None = None) -> None:
        self.automation_bridge = automation_bridge
        self.risk_service = risk_service or CommandRiskService()

    def can_handle(self, intent: str) -> bool:
        return str(intent or "").strip().lower() in {"whatsapp", "communication"}

    def classify_risk(self, command: str) -> ToolRisk:
        risk = self.risk_service.classify(command, command_action="automation")
        return ToolRisk(level=risk.risk_level, step_up_required=risk.step_up_required, reasons=list(risk.reasons))

    def execute(self, context: ToolContext) -> dict[str, Any] | None:
        # Compatibility bridge for the first extraction pass. The parsing and
        # pending-state behavior stay on AutomationService until all
        # characterization tests are green through this tool boundary.
        return self.automation_bridge._execute_whatsapp_command_legacy(context.command)
