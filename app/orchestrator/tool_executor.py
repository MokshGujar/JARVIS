from __future__ import annotations

import logging
import re
from typing import Any

from app.orchestrator.action_plan import ActionPlan, ActionStep
from app.orchestrator.automation_context import ActionFingerprint
from app.orchestrator.intent_router import RouteDecision
from app.orchestrator.scenario_policy import ScenarioPolicy
from app.orchestrator.tool_registry import ToolRegistry
from app.policy.models import PolicyDecision as CorePolicyDecision
from app.policy.models import PolicyDecisionType, ToolMetadata
from app.policy.policy_engine import PolicyEngine
from app.services.automation_response import AUTOMATION_RESPONSE_FORMATTER
from app.state import RuntimeStateStore, get_runtime_state_store
from app.tools.base import ToolContext, ToolResult, normalize_tool_result

logger = logging.getLogger(__name__)


class ToolExecutor:
    def __init__(
        self,
        *,
        registry: ToolRegistry,
        scenario_policy: ScenarioPolicy | None = None,
        policy_engine: PolicyEngine | None = None,
        audit_store: RuntimeStateStore | None = None,
        enforce_policy: bool = True,
    ) -> None:
        self.registry = registry
        self.scenario_policy = scenario_policy or ScenarioPolicy()
        self.policy_engine = policy_engine or PolicyEngine()
        self.audit_store = audit_store or get_runtime_state_store()
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

            try:
                tool = self.registry.by_name(step.tool_name)
            except KeyError:
                message = f"No tool is registered for planned step {step.step_id}: {step.tool_name}."
                logger.debug("Missing tool for step %s: %s", step.step_id, step.tool_name)
                audit_id = self._record_audit(
                    context,
                    step,
                    plan=plan,
                    policy_decision=PolicyDecisionType.DENY.value,
                    execution_result="tool_not_found",
                    error="tool_not_found",
                )
                return self._final_result(
                    plan,
                    success=False,
                    action="tool_not_found",
                    message=message,
                    step_results=step_results,
                    failed_step=step,
                    extra={"missing_tool": step.tool_name, "partial_success": bool(step_results), "audit_id": audit_id},
                )

            metadata = self._metadata_for_step(step)
            if metadata is None:
                message = f"No executable metadata is registered for planned step {step.step_id}: {step.tool_name}."
                audit_id = self._record_audit(
                    context,
                    step,
                    plan=plan,
                    policy_decision=PolicyDecisionType.DENY.value,
                    execution_result="missing_tool_metadata",
                    error="missing_tool_metadata",
                )
                return self._final_result(
                    plan,
                    success=False,
                    action="tool_metadata_missing",
                    message=message,
                    step_results=step_results,
                    failed_step=step,
                    extra={"missing_tool": step.tool_name, "partial_success": bool(step_results), "audit_id": audit_id},
                )

            resolved_args = self._resolve_args(step.args, step_outputs)
            policy_args = self._policy_args(tool, step.action, resolved_args, context)
            policy_decision = self.policy_engine.evaluate(step.tool_name, step.action, policy_args, context, metadata=metadata)
            if self.enforce_policy:
                self._record_policy_decision(policy_decision, metadata)
            policy_block = self._policy_block(step, context, policy_decision, metadata, plan)
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

            logger.debug("Step started: %s %s.%s", step.step_id, step.tool_name, step.action)
            tool_payload = {
                **context.payload,
                "planned_step": step.as_dict(),
                "step_id": step.step_id,
                "step_outputs": step_outputs,
            }
            if step.args or plan.is_multistep or plan.metadata:
                tool_payload["action"] = step.action
                tool_payload["args"] = resolved_args
            tool_context = ToolContext(
                command=context.command,
                intent=step.intent,
                session_id=context.session_id,
                face_session_id=context.face_session_id,
                step_up_token=context.step_up_token,
                payload=tool_payload,
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
            result["tool_metadata"] = metadata.as_dict()
            result["policy"] = {
                **policy_decision.as_dict(),
                "safety_level": step.safety_level,
                "requires_face_step_up": step.requires_face_step_up,
                "requires_voice_permission": step.requires_voice_permission,
            }
            result["audit_id"] = (
                self._record_execution(context, step, plan=plan, result=result, policy_decision=policy_decision)
                if self.enforce_policy
                else None
            )
            step_results.append(result)
            step_outputs[step.step_id] = result
            self._update_automation_context(plan, context, step, result)

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
        final_result = self._final_result(
            plan,
            success=True,
            action="multi_step",
            message=message,
            step_results=step_results,
        )
        self._record_successful_fingerprints(plan, context, final_result)
        return final_result

    def _policy_block(
        self,
        step: ActionStep,
        context: ToolContext,
        decision: CorePolicyDecision,
        metadata: ToolMetadata,
        plan: ActionPlan,
    ) -> dict[str, Any] | None:
        step.safety_level = decision.risk_level.value
        step.requires_confirmation = decision.requires_confirmation
        step.requires_face_step_up = False
        step.requires_voice_permission = decision.requires_step_up
        if not self.enforce_policy:
            return None

        confirmed = bool(context.confirmation_state.get("confirmed") or context.payload.get("confirmed"))
        step_up_verified = self._step_up_verified(context)
        if decision.decision == PolicyDecisionType.DENY:
            unavailable = decision.reason in {
                "tool_disabled",
                "tool_planned",
                "tool_metadata_only",
                "tool_hidden",
                "partial_tool_action_not_safe",
                "tool_action_not_allowed",
            }
            protected_path = decision.reason == "protected_path_denied"
            audit_id = self._record_audit(
                context,
                step,
                plan=plan,
                policy_decision=decision.decision.value,
                execution_result="denied",
                error=decision.reason,
                metadata={"tool_metadata": metadata.as_dict(), "policy": decision.as_dict()},
            )
            return ToolResult(
                success=False,
                tool_name=step.tool_name,
                message=(
                    "That tool is not available yet."
                    if unavailable
                    else "That location is protected."
                    if protected_path
                    else f"I can't run that action: {decision.reason}."
                ),
                requires_followup=False,
                requires_confirmation=False,
                requires_face_step_up=False,
                data={
                    "action": "tool_unavailable" if unavailable else "policy_denied",
                    "scenario": f"{step.tool_name}.{step.action}",
                    "policy": decision.as_dict(),
                    "tool_metadata": metadata.as_dict(),
                    "audit_id": audit_id,
                    "error": "unavailable" if unavailable else "policy_denied",
                },
            ).as_dict()

        if decision.requires_confirmation and not confirmed:
            confirmation_id = self._create_confirmation(context, step, plan, decision, metadata)
            audit_id = self._record_audit(
                context,
                step,
                plan=plan,
                policy_decision=decision.decision.value,
                execution_result="confirmation_required",
                metadata={"tool_metadata": metadata.as_dict(), "policy": decision.as_dict(), "confirmation_id": confirmation_id},
            )
            return ToolResult(
                success=False,
                tool_name=step.tool_name,
                message="Confirmation is required before I can run that action.",
                requires_followup=True,
                requires_confirmation=True,
                requires_face_step_up=False,
                data={
                    "action": "confirmation_required",
                    "scenario": f"{step.tool_name}.{step.action}",
                    "requires_step_up": decision.requires_step_up,
                    "requires_voice_permission": decision.requires_step_up,
                    "requires_face_step_up": False,
                    "policy": decision.as_dict(),
                    "tool_metadata": metadata.as_dict(),
                    "audit_id": audit_id,
                    "confirmation_id": confirmation_id,
                },
            ).as_dict()

        if decision.requires_step_up and not step_up_verified:
            audit_id = self._record_audit(
                context,
                step,
                plan=plan,
                policy_decision=decision.decision.value,
                execution_result="step_up_required",
                metadata={"tool_metadata": metadata.as_dict(), "policy": decision.as_dict()},
            )
            return ToolResult(
                success=False,
                tool_name=step.tool_name,
                message="Step-up authentication is required before I can run that protected action.",
                requires_followup=True,
                requires_confirmation=False,
                requires_face_step_up=False,
                data={
                    "action": "auth_required",
                    "scenario": f"{step.tool_name}.{step.action}",
                    "auth": {"step_up_required": True, "voice_permission_required": True, "protected_action": True},
                    "requires_step_up": True,
                    "requires_voice_permission": True,
                    "requires_face_step_up": False,
                    "policy": decision.as_dict(),
                    "tool_metadata": metadata.as_dict(),
                    "audit_id": audit_id,
                },
            ).as_dict()

        return None

    def _metadata_for_step(self, step: ActionStep) -> ToolMetadata | None:
        try:
            return self.registry.metadata_for(step.tool_name)
        except Exception:
            return None

    @staticmethod
    def _policy_args(tool: Any, action: str, resolved_args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        args = dict(resolved_args or {})
        provider = getattr(tool, "policy_args", None)
        if callable(provider):
            try:
                provided = provider(action, args, context)
            except TypeError:
                provided = provider(action, args)
            if isinstance(provided, dict):
                args.update(provided)
        return args

    @staticmethod
    def _step_up_verified(context: ToolContext) -> bool:
        return bool(
            context.security_state.get("step_up_verified")
            or context.security_state.get("face_step_up_verified")
            or context.security_state.get("voice_permission_granted")
            or context.payload.get("step_up_verified")
            or context.payload.get("face_step_up_verified")
            or context.payload.get("voice_permission_granted")
            or context.step_up_token
        )

    def _record_policy_decision(self, decision: CorePolicyDecision, metadata: ToolMetadata) -> int | None:
        try:
            return self.audit_store.record_policy_decision(
                session_id=decision.session_id,
                turn_id=decision.turn_id,
                tool_name=decision.tool_name,
                action=decision.action,
                decision=decision.decision.value,
                risk_level=decision.risk_level.value,
                requires_confirmation=decision.requires_confirmation,
                requires_step_up=decision.requires_step_up,
                reason=decision.reason,
                metadata={"tool_metadata": metadata.as_dict(), **dict(decision.metadata or {})},
            )
        except Exception:
            logger.debug("Could not record policy decision", exc_info=True)
            return None

    def _create_confirmation(
        self,
        context: ToolContext,
        step: ActionStep,
        plan: ActionPlan,
        decision: CorePolicyDecision,
        metadata: ToolMetadata,
    ) -> str | None:
        try:
            return self.audit_store.create_pending_confirmation(
                session_id=context.session_id,
                turn_id=self._turn_id(context),
                tool_name=step.tool_name,
                action=step.action,
                metadata={
                    "plan": plan.as_dict(),
                    "policy": decision.as_dict(),
                    "tool_metadata": metadata.as_dict(),
                    "args": dict(step.args or {}),
                },
            )
        except Exception:
            logger.debug("Could not create pending confirmation", exc_info=True)
            return None

    def _record_execution(
        self,
        context: ToolContext,
        step: ActionStep,
        *,
        plan: ActionPlan,
        result: dict[str, Any],
        policy_decision: CorePolicyDecision,
    ) -> int | None:
        try:
            execution_id = self.audit_store.record_execution_event(
                session_id=context.session_id,
                turn_id=self._turn_id(context),
                tool_name=step.tool_name,
                action=step.action,
                result=str(result.get("action") or step.action),
                ok=bool(result.get("success")),
                error=result.get("error"),
                metadata={"result": result},
            )
            return self._record_audit(
                context,
                step,
                plan=plan,
                policy_decision=policy_decision.decision.value,
                execution_result=str(result.get("action") or step.action),
                error=result.get("error"),
                metadata={"execution_event_id": execution_id, "result": result, "policy": policy_decision.as_dict()},
            )
        except Exception:
            logger.debug("Could not record execution event", exc_info=True)
            return None

    def _record_audit(
        self,
        context: ToolContext,
        step: ActionStep,
        *,
        plan: ActionPlan,
        policy_decision: str,
        execution_result: str,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int | None:
        try:
            return self.audit_store.record_audit_event(
                session_id=context.session_id,
                turn_id=self._turn_id(context),
                event_type="tool_execution",
                intent_action=f"{step.tool_name}.{step.action}",
                plan_summary=self._plan_summary(plan),
                policy_decision=policy_decision,
                tool_name=step.tool_name,
                execution_result=execution_result,
                error=error,
                metadata=metadata or {},
            )
        except Exception:
            logger.debug("Could not record audit event", exc_info=True)
            return None

    @staticmethod
    def _turn_id(context: ToolContext) -> str | None:
        return context.request_id or context.metadata.get("turn_id") or context.payload.get("turn_id")

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

    @staticmethod
    def _plan_summary(plan: ActionPlan) -> str:
        parts = [f"{step.tool_name}.{step.action}" for step in plan.steps]
        return " -> ".join(parts) if parts else str(plan.original_text or "")

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
        if plan.metadata:
            result["metadata"] = dict(plan.metadata)
            if plan.metadata.get("semantic_execution"):
                result["semantic_execution"] = True
                result["semantic_actions"] = list(plan.metadata.get("semantic_actions") or [])
        if not plan.is_multistep and len(step_results) == 1 and success:
            single = dict(step_results[0])
            single.setdefault("plan", plan.as_dict())
            single.setdefault("steps", [step.as_dict() for step in plan.steps])
            return single
        return result

    def _update_automation_context(self, plan: ActionPlan, context: ToolContext, step: ActionStep, result: dict[str, Any]) -> None:
        if not plan.metadata.get("semantic_execution"):
            return
        automation_context = self._automation_context(context)
        if automation_context is None:
            return
        semantic_by_step = dict(plan.metadata.get("semantic_step_actions") or {})
        semantic_action = semantic_by_step.get(step.step_id)
        if isinstance(semantic_action, dict):
            self._update_context_from_semantic_payload(automation_context, semantic_action)
        automation_context.update_from_tool_result(result)

    def _record_successful_fingerprints(self, plan: ActionPlan, context: ToolContext, result: dict[str, Any]) -> None:
        if not result.get("success"):
            return
        automation_context = self._automation_context(context)
        if automation_context is None:
            return
        for item in plan.metadata.get("fingerprints") or []:
            if not isinstance(item, dict) or not item.get("mutating"):
                continue
            try:
                fingerprint = ActionFingerprint(
                    request_id=item.get("request_id"),
                    action_id=str(item.get("action_id") or ""),
                    original_user_text=str(item.get("original_user_text") or ""),
                    corrected_text=str(item.get("corrected_text") or ""),
                    semantic_action=str(item.get("semantic_action") or ""),
                    target=item.get("target"),
                    content_hash=item.get("content_hash"),
                    tool_plan_hash=item.get("tool_plan_hash"),
                    timestamp=float(item.get("timestamp") or 0),
                    mutating=True,
                )
                automation_context.record_fingerprint(fingerprint)
            except Exception:
                logger.debug("Could not record semantic fingerprint: %s", item, exc_info=True)

    @staticmethod
    def _automation_context(context: ToolContext) -> Any | None:
        payload_context = context.payload.get("automation_context")
        if payload_context is not None:
            return payload_context
        return context.metadata.get("automation_context")

    @staticmethod
    def _update_context_from_semantic_payload(automation_context: Any, action: dict[str, Any]) -> None:
        intent = str(action.get("intent") or "")
        automation_context.last_semantic_intent = intent or automation_context.last_semantic_intent
        automation_context.last_semantic_target = action.get("target") or automation_context.last_semantic_target
        content = action.get("content")
        if content is not None:
            automation_context.last_content = automation_context.redact_sensitive_text(str(content))
            if intent in {"WRITE_NOTE", "APPEND_TO_NOTE"}:
                automation_context.last_typed_text = automation_context.redact_sensitive_text(str(content))
        app = action.get("app")
        if app:
            automation_context.previous_active_app = automation_context.active_app
            automation_context.active_app = str(app)
            automation_context.last_opened_app = str(app)
            automation_context.last_focused_app = str(app)
        file_path = action.get("file_path")
        if file_path:
            automation_context.last_file_path = str(file_path)
        query = action.get("query")
        if query:
            automation_context.last_browser_query = str(query)
            automation_context.current_browser_context = {"query": str(query)}
        url = action.get("url")
        if url:
            automation_context.last_opened_url = str(url)
        automation_context.touch()
