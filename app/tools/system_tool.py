from __future__ import annotations

from typing import Any

from app.services.command_risk_service import CommandRiskService
from app.tools.base import BaseTool, ToolContext, ToolRisk, ToolSpec


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
        if self.automation_bridge and hasattr(self.automation_bridge, "_execute_system_command_legacy"):
            return self.automation_bridge._execute_system_command_legacy(context.command)
        return {"success": False, "action": "unsupported", "message": "System tool is not wired yet."}
