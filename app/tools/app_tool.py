from __future__ import annotations

from typing import Any

from app.services.automation_response import normalize_automation_response
from app.services.command_risk_service import CommandRiskService
from app.tools.base import BaseTool, ToolContext, ToolRisk, ToolSpec


class AppTool(BaseTool):
    name = "app"
    spec = ToolSpec(
        name="app",
        description="Open, close, and focus local applications through the Jarvis compatibility facade.",
        category="app",
        safety_level="HIGH",
        supported_intents=["app", "app_open", "app_close", "app_focus", "app_launcher", "open_app", "close_app"],
        metadata={"extraction_phase": "legacy_bridge"},
    )

    def __init__(self, automation_bridge: Any | None = None, *, risk_service: CommandRiskService | None = None) -> None:
        self.automation_bridge = automation_bridge
        self.risk_service = risk_service or CommandRiskService()

    def classify_risk(self, command: str) -> ToolRisk:
        risk = self.risk_service.classify(command, command_action="automation")
        return ToolRisk(level=risk.risk_level, step_up_required=risk.step_up_required, reasons=list(risk.reasons))

    def execute(self, context: ToolContext, **kwargs: Any) -> dict[str, Any] | None:
        planned_action = str(context.payload.get("action") or "").strip()
        if planned_action:
            args = dict(context.payload.get("args") or {})
            command = self._planned_command(planned_action, args)
            if command is None:
                return None
            if self.automation_bridge and hasattr(self.automation_bridge, "_execute_app_launcher_command_legacy"):
                result = self.automation_bridge._execute_app_launcher_command_legacy(command)
                if result is None:
                    return None
                normalized = normalize_automation_response(result)
                normalized["tool_name"] = self.name
                return normalized
            return {"success": False, "action": planned_action, "message": "App tool is not wired yet."}

        if self.automation_bridge and hasattr(self.automation_bridge, "_execute_app_launcher_command_legacy"):
            result = self.automation_bridge._execute_app_launcher_command_legacy(context.command)
            if result is None:
                return None
            normalized = normalize_automation_response(result)
            normalized["tool_name"] = self.name
            return normalized
        return {"success": False, "action": "unsupported", "message": "App tool is not wired yet."}

    @staticmethod
    def _planned_command(action: str, args: dict[str, Any]) -> str | None:
        app_name = str(args.get("app") or args.get("target") or "").strip()
        if not app_name:
            return None
        if action in {"open", "app_open"}:
            return f"open {app_name}"
        if action in {"close", "app_close"}:
            return f"close {app_name}"
        if action in {"focus", "app_focus"}:
            return f"focus {app_name}"
        return None
