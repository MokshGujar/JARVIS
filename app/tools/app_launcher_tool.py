from __future__ import annotations

from typing import Any

from app.services.automation_response import normalize_automation_response
from app.services.command_risk_service import CommandRiskService
from app.tools.base import BaseTool, ToolContext, ToolRisk, ToolSpec
from app.tools.compatibility_runners import AppCompatibilityRunner


class AppLauncherTool(BaseTool):
    name = "app_launcher"
    spec = ToolSpec(
        name="app_launcher",
        description="Application launch and close compatibility tool.",
        category="app",
        safety_level="HIGH",
        supported_intents=["app_launcher", "app", "app_open", "app_close", "app_focus", "open_app", "close_app"],
        metadata={"compatibility_alias": "app"},
    )

    def __init__(self, automation_bridge: Any | None = None, *, risk_service: CommandRiskService | None = None) -> None:
        self.automation_bridge = getattr(automation_bridge, "app_browser_domain", automation_bridge)
        self.risk_service = risk_service or CommandRiskService()

    def can_handle(self, intent: str) -> bool:
        return super().can_handle(intent)

    def classify_risk(self, command: str) -> ToolRisk:
        risk = self.risk_service.classify(command, command_action="automation")
        return ToolRisk(level=risk.risk_level, step_up_required=risk.step_up_required, reasons=list(risk.reasons))

    def execute(self, context: ToolContext) -> dict[str, Any]:
        if self.automation_bridge:
            result = AppCompatibilityRunner(self.automation_bridge).execute(context.command)
            if result is None:
                return None
            normalized = normalize_automation_response(result)
            normalized["tool_name"] = self.name
            return normalized
        return {"success": False, "action": "unsupported", "message": "App launcher tool is not wired yet."}
