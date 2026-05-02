from __future__ import annotations

from typing import Any

from app.core.event_bus import EventBus, EventName
from app.services.command_risk_service import CommandRiskResult, CommandRiskService
from app.tools.base import ToolContext, normalize_tool_result


class SecureExecutionService:
    def __init__(
        self,
        *,
        command_risk_service: CommandRiskService,
        face_identity_service: Any | None = None,
        step_up_auth_service: Any | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self.command_risk_service = command_risk_service
        self.face_identity_service = face_identity_service
        self.step_up_auth_service = step_up_auth_service
        self.event_bus = event_bus

    def secure_execute(self, tool: Any, context: ToolContext) -> dict[str, Any]:
        risk = self._classify(tool, context)
        self._emit(EventName.TOOL_SELECTED, {"tool": getattr(tool, "name", ""), "risk": risk.as_dict()})

        if not risk.step_up_required:
            return self._execute(tool, context, risk)

        if not self.face_identity_service or not self._validate_face_session(context.face_session_id):
            self._emit(EventName.STEP_UP_REQUIRED, {"reason": "face_session_required", "risk": risk.as_dict()})
            return {
                "success": False,
                "action": "auth_required",
                "message": "Face verification is required before I can run that command.",
                "auth": {
                    "face_verification_required": True,
                    "step_up_required": risk.step_up_required,
                    "risk": risk.as_dict(),
                },
            }

        if not self.step_up_auth_service:
            self._emit(EventName.STEP_UP_FAILED, {"reason": "step_up_unavailable", "risk": risk.as_dict()})
            return {
                "success": False,
                "action": "auth_required",
                "message": "Fresh face verification is required for that command, but step-up auth is unavailable.",
                "auth": {"step_up_required": True, "risk": risk.as_dict(), "reason": "step_up_unavailable"},
            }

        try:
            ok, reason = self.step_up_auth_service.consume(
                token=context.step_up_token,
                face_session_id=context.face_session_id,
                risk=risk,
            )
        except Exception:
            ok, reason = False, "step_up_consume_failed"
        if not ok:
            self._emit(EventName.STEP_UP_REQUIRED, {"reason": reason, "risk": risk.as_dict()})
            return {
                "success": False,
                "action": "auth_required",
                "message": "Fresh live face verification is required before I can run that high-risk command.",
                "auth": {"step_up_required": True, "risk": risk.as_dict(), "reason": reason},
            }

        self._emit(EventName.STEP_UP_SUCCESS, {"risk": risk.as_dict()})
        return self._execute(tool, context, risk)

    def _classify(self, tool: Any, context: ToolContext) -> CommandRiskResult:
        if hasattr(tool, "classify_risk"):
            tool_risk = tool.classify_risk(context.command)
            if hasattr(tool_risk, "level"):
                return CommandRiskResult(
                    command_text=context.command,
                    command_action=context.intent or getattr(tool, "name", "") or "automation",
                    risk_level=str(tool_risk.level),
                    step_up_required=bool(tool_risk.step_up_required),
                    reasons=list(getattr(tool_risk, "reasons", [])),
                )
        return self.command_risk_service.classify(
            context.command,
            command_action=context.intent or getattr(tool, "name", "") or "automation",
        )

    def _execute(self, tool: Any, context: ToolContext, risk: CommandRiskResult) -> dict[str, Any]:
        tool_name = str(getattr(tool, "name", "") or "automation")
        self._emit(EventName.TOOL_STARTED, {"tool": tool_name, "risk": risk.as_dict()})
        try:
            result = normalize_tool_result(tool.execute(context), default_action=tool_name)
        except Exception as exc:
            result = {
                "success": False,
                "action": tool_name,
                "message": f"Tool execution failed: {exc}",
            }
        self._emit(
            EventName.TOOL_SUCCESS if bool(result.get("success")) else EventName.TOOL_FAILED,
            {"tool": tool_name, "action": result.get("action"), "message": result.get("message")},
        )
        return result

    def _emit(self, event_name: str, payload: dict[str, Any]) -> None:
        if self.event_bus:
            self.event_bus.publish(event_name, payload)

    def _validate_face_session(self, face_session_id: str | None) -> bool:
        try:
            return bool(self.face_identity_service.validate_session(face_session_id))
        except Exception:
            return False
