from __future__ import annotations

import logging
from typing import Any

from app.utils.runtime_observability import log_boundary
from app.services.command_risk_service import CommandRiskService
from app.tools.base import ToolContext, ToolRisk

logger = logging.getLogger(__name__)


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
        planned_action = str(context.payload.get("action") or "").strip()
        if planned_action:
            args = dict(context.payload.get("args") or {})
            if planned_action == "send_message":
                result = self.automation_bridge._send_whatsapp_message(args)
                log_boundary(logger, "TOOL", name="WhatsAppTool", action=planned_action, delegate="legacy_delegate", status="success" if result.get("success") else "failed", target=args.get("contact") or args.get("recipient") or "")
                return result
            if planned_action in {"start_voice_call", "start_video_call"}:
                payload = dict(args)
                payload.setdefault("mode", "video" if planned_action == "start_video_call" else "voice")
                result = self.automation_bridge._start_whatsapp_call(payload)
                log_boundary(logger, "TOOL", name="WhatsAppTool", action=planned_action, delegate="legacy_delegate", status="success" if result.get("success") else "failed", target=payload.get("contact") or payload.get("recipient") or "")
                return result
            if planned_action == "end_call":
                result = self.automation_bridge._end_whatsapp_call()
                log_boundary(logger, "TOOL", name="WhatsAppTool", action=planned_action, delegate="legacy_delegate", status="success" if result.get("success") else "failed", target="")
                return result
            if planned_action == "open":
                result = self.automation_bridge._open_whatsapp_desktop_or_web()
                log_boundary(logger, "TOOL", name="WhatsAppTool", action=planned_action, delegate="legacy_delegate", status="success" if result.get("success") else "failed", target="whatsapp")
                return result

        # Compatibility bridge for the first extraction pass. The parsing and
        # pending-state behavior stay on AutomationService until all
        # characterization tests are green through this tool boundary.
        result = self.automation_bridge._execute_whatsapp_command_legacy(context.command)
        if isinstance(result, dict) and isinstance(result.get("pending"), dict):
            action = str(result.get("action") or "")
            if action == "send_message_pending":
                self.automation_bridge._pending_mark_action = {"kind": "send_message", "payload": dict(result["pending"])}
            elif action in {"whatsapp_call_pending", "multi_action"}:
                self.automation_bridge._pending_mark_action = {"kind": "whatsapp_call", "payload": dict(result["pending"])}
        if isinstance(result, dict):
            log_boundary(logger, "TOOL", name="WhatsAppTool", action=str(result.get("action") or "legacy_command"), delegate="legacy_delegate", status="success" if result.get("success") else "blocked" if result.get("pending") else "failed", target=result.get("contact") or result.get("recipient") or "")
        return result
