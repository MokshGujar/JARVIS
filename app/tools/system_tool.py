from __future__ import annotations

import logging
from typing import Any

from app.utils.runtime_observability import log_boundary
from app.services.command_risk_service import CommandRiskService
from app.tools.base import BaseTool, ToolContext, ToolRisk, ToolSpec

logger = logging.getLogger(__name__)


class SystemTool(BaseTool):
    name = "system"
    spec = ToolSpec(
        name="system",
        description="Local system controls through the Jarvis compatibility facade.",
        category="system",
        safety_level="CRITICAL",
        supported_intents=[
            "system",
            "computer_control",
            "settings",
            "volume_up",
            "volume_down",
            "mute_volume",
            "volume_change",
            "brightness_change",
            "lock_system",
            "shutdown_system",
            "restart_system",
            "sleep_system",
            "shutdown",
            "restart",
            "screenshot",
            "show_desktop",
            "safe_system_info",
            "window_control",
        ],
        metadata={"extraction_phase": "legacy_bridge"},
    )

    def __init__(self, automation_bridge: Any | None = None, *, risk_service: CommandRiskService | None = None) -> None:
        self.automation_bridge = automation_bridge
        self.risk_service = risk_service or CommandRiskService()

    def can_handle(self, intent: str) -> bool:
        return super().can_handle(intent)

    def classify_risk(self, command: str) -> ToolRisk:
        risk = self.risk_service.classify(command, command_action="automation")
        return ToolRisk(level=risk.risk_level, step_up_required=risk.step_up_required, reasons=list(risk.reasons))

    def execute(self, context: ToolContext) -> dict[str, Any]:
        action_name = str(context.payload.get("action") or context.intent or "legacy_command")
        if self.automation_bridge and hasattr(self.automation_bridge, "_execute_system_command_legacy"):
            result = self.automation_bridge._execute_system_command_legacy(context.command)
            if isinstance(result, dict):
                log_boundary(logger, "TOOL", name="SystemTool", action=action_name, delegate="legacy_delegate", status="success" if result.get("success") else "failed", target=context.command)
            return result
        result = {"success": False, "action": "unsupported", "message": "System tool is not wired yet."}
        log_boundary(logger, "TOOL", name="SystemTool", action=action_name, delegate="legacy_delegate", status="failed", target="")
        return result
