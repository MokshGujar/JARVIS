from __future__ import annotations

import logging
import re
from typing import Any

from app.utils.runtime_observability import log_boundary
from app.services.command_risk_service import CommandRiskService
from app.tools.base import ToolContext, ToolRisk
from app.tools.compatibility_runners import WhatsAppCompatibilityRunner

logger = logging.getLogger(__name__)


class WhatsAppTool:
    name = "whatsapp"

    def __init__(self, automation_bridge: Any, *, risk_service: CommandRiskService | None = None) -> None:
        self.automation_bridge = getattr(automation_bridge, "whatsapp_domain", automation_bridge)
        self.risk_service = risk_service or CommandRiskService()

    def can_handle(self, intent: str) -> bool:
        return str(intent or "").strip().lower() in {"whatsapp", "communication"}

    def classify_risk(self, command: str) -> ToolRisk:
        risk = self.risk_service.classify(command, command_action="automation")
        return ToolRisk(level=risk.risk_level, step_up_required=risk.step_up_required, reasons=list(risk.reasons))

    def policy_args(self, action: str, args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        recipient = str(args.get("receiver") or args.get("contact") or args.get("recipient") or "").strip()
        message = str(args.get("message") or "").strip()
        return {
            "user_initiated": str(context.source or "").lower() in {"user", "text", "voice"},
            "fresh_user_command": not bool(context.metadata.get("recovered_pending") or context.payload.get("recovered_pending")),
            "direct_user_requested": bool(args.get("direct_user_requested")),
            "single_recipient": bool(recipient) and not re.search(r"[,;]|\band\b", recipient, flags=re.IGNORECASE),
            "recipient_confident": bool(args.get("recipient_confident")),
            "has_body": bool(message),
            "bulk": bool(args.get("bulk")),
        }

    def execute(self, context: ToolContext) -> dict[str, Any] | None:
        planned_action = str(context.payload.get("action") or "").strip()
        if planned_action:
            args = dict(context.payload.get("args") or {})
            if planned_action in {"prepare_message", "prepare_call", "open_chat"} and not args:
                result = WhatsAppCompatibilityRunner(self.automation_bridge).execute(context.command)
                if isinstance(result, dict):
                    log_boundary(logger, "TOOL", name="WhatsAppTool", action=str(result.get("action") or planned_action), delegate="whatsapp_compatibility_runner", status="success" if result.get("success") else "blocked" if result.get("pending") else "failed", contact_hash=result.get("contact_hash") or "")
                return result
            if planned_action == "send_message":
                result = self.automation_bridge._send_whatsapp_message(args)
                log_boundary(logger, "TOOL", name="WhatsAppTool", action=planned_action, delegate="whatsapp_bridge_method", status="success" if result.get("success") else "failed", contact_hash=args.get("contact_hash") or "")
                return result
            if planned_action == "open_chat":
                result = self.automation_bridge._open_whatsapp_chat(args)
                log_boundary(logger, "TOOL", name="WhatsAppTool", action=planned_action, delegate="whatsapp_bridge_method", status="success" if result.get("success") else "failed", contact_hash=args.get("contact_hash") or "")
                return result
            if planned_action in {"start_voice_call", "start_video_call"}:
                payload = dict(args)
                payload.setdefault("mode", "video" if planned_action == "start_video_call" else "voice")
                result = self.automation_bridge._start_whatsapp_call(payload)
                log_boundary(logger, "TOOL", name="WhatsAppTool", action=planned_action, delegate="whatsapp_bridge_method", status="success" if result.get("success") else "failed", contact_hash=payload.get("contact_hash") or "")
                return result
            if planned_action == "end_call":
                result = self.automation_bridge._end_whatsapp_call()
                log_boundary(logger, "TOOL", name="WhatsAppTool", action=planned_action, delegate="whatsapp_bridge_method", status="success" if result.get("success") else "failed", target="")
                return result
            if planned_action == "open":
                result = self.automation_bridge._open_whatsapp_desktop_or_web()
                log_boundary(logger, "TOOL", name="WhatsAppTool", action=planned_action, delegate="whatsapp_bridge_method", status="success" if result.get("success") else "failed", target="whatsapp")
                return result

        result = WhatsAppCompatibilityRunner(self.automation_bridge).execute(context.command)
        if isinstance(result, dict) and isinstance(result.get("pending"), dict):
            action = str(result.get("action") or "")
            if action == "send_message_pending":
                self.automation_bridge._pending_mark_action = {"kind": "send_message", "payload": dict(result["pending"])}
            elif action in {"whatsapp_call_pending", "multi_action"}:
                self.automation_bridge._pending_mark_action = {"kind": "whatsapp_call", "payload": dict(result["pending"])}
        if isinstance(result, dict):
            log_boundary(logger, "TOOL", name="WhatsAppTool", action=str(result.get("action") or "compatibility_command"), delegate="whatsapp_compatibility_runner", status="success" if result.get("success") else "blocked" if result.get("pending") else "failed", contact_hash=result.get("contact_hash") or "")
        return result
