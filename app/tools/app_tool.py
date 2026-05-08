from __future__ import annotations

import logging
from typing import Any

from app.utils.runtime_observability import log_boundary
from app.services.automation_response import normalize_automation_response
from app.services.command_risk_service import CommandRiskService
from app.tools.base import BaseTool, ToolContext, ToolRisk, ToolSpec
from app.tools.compatibility_runners import AppCompatibilityRunner

logger = logging.getLogger(__name__)


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
        self.automation_bridge = getattr(automation_bridge, "app_browser_domain", automation_bridge)
        self.risk_service = risk_service or CommandRiskService()

    def classify_risk(self, command: str) -> ToolRisk:
        risk = self.risk_service.classify(command, command_action="automation")
        return ToolRisk(level=risk.risk_level, step_up_required=risk.step_up_required, reasons=list(risk.reasons))

    def execute(self, context: ToolContext, **kwargs: Any) -> dict[str, Any] | None:
        planned_action = str(context.payload.get("action") or "").strip()
        action_name = planned_action or "legacy_command"
        if planned_action:
            args = dict(context.payload.get("args") or {})
            command = self._planned_command(planned_action, args)
            if command is None:
                return None
            if self.automation_bridge:
                result = AppCompatibilityRunner(self.automation_bridge).execute(command)
                if result is None:
                    return None
                normalized = normalize_automation_response(result)
                normalized["tool_name"] = self.name
                log_boundary(logger, "TOOL", name="AppTool", action=action_name, delegate="app_compatibility_runner", status="success" if normalized.get("success") else "failed", target=command)
                return normalized
            result = {"success": False, "action": planned_action, "message": "App tool is not wired yet."}
            log_boundary(logger, "TOOL", name="AppTool", action=action_name, delegate="app_compatibility_runner", status="failed", target="")
            return result

        if self.automation_bridge:
            result = AppCompatibilityRunner(self.automation_bridge).execute(context.command)
            if result is None:
                return None
            normalized = normalize_automation_response(result)
            normalized["tool_name"] = self.name
            log_boundary(logger, "TOOL", name="AppTool", action=action_name, delegate="app_compatibility_runner", status="success" if normalized.get("success") else "failed", target=context.command)
            return normalized
        result = {"success": False, "action": "unsupported", "message": "App tool is not wired yet."}
        log_boundary(logger, "TOOL", name="AppTool", action=action_name, delegate="app_compatibility_runner", status="failed", target="")
        return result

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
