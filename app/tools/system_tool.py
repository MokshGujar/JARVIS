from __future__ import annotations

import logging
from typing import Any

from app.utils.runtime_observability import log_boundary
from app.services.command_risk_service import CommandRiskService
from app.tools.base import BaseTool, ToolContext, ToolRisk, ToolSpec
from app.tools.compatibility_runners import SystemCompatibilityRunner

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
        self.automation_bridge = getattr(automation_bridge, "system_domain", automation_bridge)
        self.risk_service = risk_service or CommandRiskService()

    def can_handle(self, intent: str) -> bool:
        return super().can_handle(intent)

    def classify_risk(self, command: str) -> ToolRisk:
        risk = self.risk_service.classify(command, command_action="automation")
        return ToolRisk(level=risk.risk_level, step_up_required=risk.step_up_required, reasons=list(risk.reasons))

    def execute(self, context: ToolContext) -> dict[str, Any]:
        planned_step = context.payload.get("planned_step") if isinstance(context.payload.get("planned_step"), dict) else {}
        planned_action = str(context.payload.get("action") or planned_step.get("action") or "").strip()
        action_name = planned_action or str(context.intent or "legacy_command")
        if planned_action == "safe_system_info" and self.automation_bridge:
            result = self._execute_safe_system_info(context.command)
            if result is not None:
                log_boundary(logger, "TOOL", name="SystemTool", action=action_name, delegate="native", status="success" if result.get("success") else "failed", target=context.command)
                return result
        if self.automation_bridge:
            result = SystemCompatibilityRunner(self.automation_bridge).execute(context.command)
            if isinstance(result, dict):
                log_boundary(logger, "TOOL", name="SystemTool", action=action_name, delegate="system_compatibility_runner", status="success" if result.get("success") else "failed", target=context.command)
            return result
        result = {"success": False, "action": "unsupported", "message": "System tool is not wired yet."}
        log_boundary(logger, "TOOL", name="SystemTool", action=action_name, delegate="system_compatibility_runner", status="failed", target="")
        return result

    def _execute_safe_system_info(self, command: str) -> dict[str, Any] | None:
        bridge = self.automation_bridge
        normalized_text = bridge._normalize_spoken_command(command)
        lowered = normalized_text.lower()
        if bridge._looks_like_local_system_status(lowered):
            return bridge.safe_command_info_service.execute("systeminfo")
        if bridge._looks_like_safe_command_info(lowered):
            return bridge.safe_command_info_service.execute(normalized_text)
        return None
