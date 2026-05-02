from __future__ import annotations

import logging
import re
from typing import Any

from app.orchestrator.action_plan import ActionPlan, ActionStep
from app.orchestrator.intent_router import RouteDecision
from app.orchestrator.scenario_policy import ScenarioPolicy
from app.orchestrator.tool_registry import ToolRegistry
from app.services.automation_response import AUTOMATION_RESPONSE_FORMATTER
from app.tools.base import ToolContext, ToolResult, normalize_tool_result

logger = logging.getLogger(__name__)


class ToolExecutor:
    def __init__(
        self,
        *,
        registry: ToolRegistry,
        scenario_policy: ScenarioPolicy | None = None,
        enforce_policy: bool = True,
    ) -> None:
        self.registry = registry
        self.scenario_policy = scenario_policy or ScenarioPolicy()
        self.enforce_policy = enforce_policy

    def execute(self, plan: ActionPlan, context: ToolContext) -> dict[str, Any]:
        logger.debug("Executing action plan for %r: %s", plan.original_text, plan.as_dict())
        step_results: list[dict[str, Any]] = []
        step_outputs: dict[str, dict[str, Any]] = {}

        for step in plan.steps:
            dependency_failure = self._dependency_failure(step, step_outputs)
            if dependency_failure is not None:
                logger.debug("Dependency failed for step %s: %s", step.step_id, dependency_failure)
                return self._final_result(
                    plan,
                    success=False,
                    action="dependency_failed",
                    message=dependency_failure,
                    step_results=step_results,
                    failed_step=step,
                )

            policy_block = self._policy_block(step, context)
            if policy_block is not None:
                logger.debug("Policy blocked step %s: %s", step.step_id, policy_block)
                return self._final_result(
                    plan,
                    success=False,
                    action=str(policy_block.get("action") or "policy_blocked"),
                    message=str(policy_block.get("message") or "Policy blocked this action."),
                    step_results=step_results,
                    failed_step=step,
                    extra=policy_block,
                )

            try:
                tool = self.registry.by_name(step.tool_name)
            except KeyError:
                message = f"No tool is registered for planned step {step.step_id}: {step.tool_name}."
                logger.debug("Missing tool for step %s: %s", step.step_id, step.tool_name)
                return self._final_result(
                    plan,
                    success=False,
                    action="tool_not_found",
                    message=message,
                    step_results=step_results,
                    failed_step=step,
                    extra={"missing_tool": step.tool_name, "partial_success": bool(step_results)},
                )

            resolved_args = self._resolve_args(step.args, step_outputs)
            logger.debug("Step started: %s %s.%s", step.step_id, step.tool_name, step.action)
            tool_context = ToolContext(
                command=context.command,
                intent=step.intent,
                session_id=context.session_id,
                face_session_id=context.face_session_id,
                step_up_token=context.step_up_token,
                payload={
                    **context.payload,
                    "planned_step": step.as_dict(),
                    "action": step.action,
                    "args": resolved_args,
                    "step_id": step.step_id,
                    "step_outputs": step_outputs,
                },
                source=context.source,
                user_id=context.user_id,
                security_state=dict(context.security_state),
                confirmation_state=dict(context.confirmation_state),
                request_id=context.request_id,
                metadata=dict(context.metadata),
            )

            result = normalize_tool_result(tool.execute(tool_context), default_action=step.action)
            result["step_id"] = step.step_id
            result["selected_tool"] = step.tool_name
            result["planned_action"] = step.action
            result["resolved_args"] = resolved_args
            result["policy"] = {
                "safety_level": step.safety_level,
                "requires_confirmation": step.requires_confirmation,
                "requires_face_step_up": step.requires_face_step_up,
                "requires_voice_permission": step.requires_voice_permission,
            }
            step_results.append(result)
            step_outputs[step.step_id] = result

            if not bool(result.get("success")):
                logger.debug("Step failed: %s %s", step.step_id, result)
                return self._final_result(
                    plan,
                    success=False,
                    action=str(result.get("action") or step.action),
                    message=str(result.get("message") or f"Step {step.step_id} failed."),
                    step_results=step_results,
                    failed_step=step,
                )

            logger.debug("Step completed: %s %s", step.step_id, result)

        message = self._aggregate_success_message(step_results)
        logger.debug("Action plan completed: %s", message)
        return self._final_result(
            plan,
            success=True,
            action="multi_step",
            message=message,
            step_results=step_results,
        )

    def _policy_block(self, step: ActionStep, context: ToolContext) -> dict[str, Any] | None:
        decision = self.scenario_policy.evaluate(self._route_for_step(step))
        step.safety_level = decision.safety_level
        step.requires_confirmation = decision.requires_confirmation
        step.requires_face_step_up = decision.requires_face_step_up
        step.requires_voice_permission = decision.requires_voice_permission
        if not self.enforce_policy:
            return None

        confirmed = bool(context.confirmation_state.get("confirmed") or context.payload.get("confirmed"))
        voice_permission_granted = bool(
            context.security_state.get("voice_permission_granted")
            or context.payload.get("voice_permission_granted")
        )
        if decision.requires_confirmation and not confirmed:
            return ToolResult(
                success=False,
                tool_name=step.tool_name,
                message="Confirmation is required before I can run that action.",
                requires_followup=True,
                requires_confirmation=True,
                requires_face_step_up=decision.requires_face_step_up,
                data={
                    "action": "confirmation_required",
                    "scenario": f"{step.tool_name}.{step.action}",
                    "requires_voice_permission": decision.requires_voice_permission,
                },
            ).as_dict()

        if decision.requires_voice_permission and not voice_permission_granted:
            return ToolResult(
                success=False,
                tool_name=step.tool_name,
                message="Voice permission is required before I can run that protected action.",
                requires_followup=True,
                requires_confirmation=False,
                requires_face_step_up=False,
                data={
                    "action": "auth_required",
                    "scenario": f"{step.tool_name}.{step.action}",
                    "auth": {"voice_permission_required": True, "protected_action": True},
                    "requires_voice_permission": True,
                },
            ).as_dict()

        return None

    def _dependency_failure(self, step: ActionStep, step_outputs: dict[str, dict[str, Any]]) -> str | None:
        for dependency in step.depends_on:
            result = step_outputs.get(dependency)
            if result is None:
                return f"Step {step.step_id} could not run because {dependency} has not completed."
            if not bool(result.get("success")):
                return f"Step {step.step_id} could not run because {dependency} failed."
        return None

    def _resolve_args(self, value: Any, step_outputs: dict[str, dict[str, Any]]) -> Any:
        if isinstance(value, dict):
            return {key: self._resolve_args(item, step_outputs) for key, item in value.items()}
        if isinstance(value, list):
            return [self._resolve_args(item, step_outputs) for item in value]
        if not isinstance(value, str):
            return value

        full_match = re.fullmatch(r"\{(?P<step>step\d+)\.(?P<field>[A-Za-z_][A-Za-z0-9_]*)\}", value)
        if full_match:
            return self._lookup_output(full_match.group("step"), full_match.group("field"), step_outputs)

        def replace(match: re.Match[str]) -> str:
            resolved = self._lookup_output(match.group("step"), match.group("field"), step_outputs)
            return "" if resolved is None else str(resolved)

        return re.sub(r"\{(?P<step>step\d+)\.(?P<field>[A-Za-z_][A-Za-z0-9_]*)\}", replace, value)

    @staticmethod
    def _lookup_output(step_id: str, field: str, step_outputs: dict[str, dict[str, Any]]) -> Any:
        result = step_outputs.get(step_id) or {}
        if field in result:
            return result[field]
        data = result.get("data")
        if isinstance(data, dict):
            return data.get(field)
        return None

    @staticmethod
    def _route_for_step(step: ActionStep) -> RouteDecision:
        return RouteDecision(
            scenario=f"{step.tool_name}.{step.action}",
            intent=step.intent,
            tool_name=step.tool_name,
            category=step.tool_name,
            operation=step.action,
            parameters=dict(step.args),
        )

    @staticmethod
    def _aggregate_success_message(step_results: list[dict[str, Any]]) -> str:
        messages = [str(result.get("message") or "").strip() for result in step_results if str(result.get("message") or "").strip()]
        return " ".join(messages) if messages else "Done."

    def _final_result(
        self,
        plan: ActionPlan,
        *,
        success: bool,
        action: str,
        message: str,
        step_results: list[dict[str, Any]],
        failed_step: ActionStep | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "success": success,
            "action": action,
            "message": message,
            "display_text": message,
            "spoken_text": message,
            "tool_name": "tool_executor",
            "selected_tool": "tool_executor",
            "scenario": "task.multistep",
            "is_multistep": True,
            "plan": plan.as_dict(),
            "steps": [step.as_dict() for step in plan.steps],
            "step_results": list(step_results),
            "requires_confirmation": plan.requires_confirmation,
            "requires_face_step_up": plan.requires_face_step_up,
            "requires_voice_permission": plan.requires_voice_permission,
            "partial_success": bool(step_results) and not success,
        }
        if failed_step is not None:
            result["failed_step_id"] = failed_step.step_id
            result["failed_tool_name"] = failed_step.tool_name
        if extra:
            result.update(extra)
        formatted = AUTOMATION_RESPONSE_FORMATTER.format(result)
        if formatted:
            result["message"] = formatted
            result["display_text"] = formatted
            result["spoken_text"] = formatted
        return result
