from __future__ import annotations

from typing import Any

from app.services.command_risk_service import CommandRiskService
from app.tools.base import ToolContext, ToolRisk


class ContactsTool:
    name = "contacts"

    def __init__(self, contact_resolution_service: Any | None = None, *, risk_service: CommandRiskService | None = None) -> None:
        self.contact_resolution_service = contact_resolution_service
        self.risk_service = risk_service or CommandRiskService()

    def can_handle(self, intent: str) -> bool:
        return str(intent or "").strip().lower() in {"contacts", "contact_resolution"}

    def classify_risk(self, command: str) -> ToolRisk:
        risk = self.risk_service.classify(command, command_action="contacts")
        return ToolRisk(level=risk.risk_level, step_up_required=risk.step_up_required, reasons=list(risk.reasons))

    def execute(self, context: ToolContext) -> dict:
        if not self.contact_resolution_service:
            return {"success": False, "action": "unsupported", "message": "Contacts tool is not wired yet."}
        query = str(context.payload.get("query") or context.command or "").strip()
        return self.contact_resolution_service.resolve(query)
