from __future__ import annotations

import logging
from typing import Any

from app.orchestrator.action_plan import ActionPlan, ActionStep
from app.orchestrator.intent_router import IntentRouter, RouteDecision
from app.utils.runtime_observability import log_boundary
from app.orchestrator.scenario_policy import ScenarioPolicy
from app.orchestrator.semantic_planner_adapter import SemanticPlannerAdapter
from app.orchestrator.task_planner import TaskPlanner
from app.orchestrator.tool_executor import ToolExecutor
from app.orchestrator.tool_registry import ToolRegistry
from app.tools.base import ToolContext

logger = logging.getLogger(__name__)


class MainOrchestrator:
    def __init__(
        self,
        *,
        registry: ToolRegistry,
        intent_router: IntentRouter | None = None,
        scenario_policy: ScenarioPolicy | None = None,
        task_planner: TaskPlanner | None = None,
        semantic_adapter: SemanticPlannerAdapter | None = None,
        tool_executor: ToolExecutor | None = None,
        enforce_policy: bool = True,
    ) -> None:
        self.registry = registry
        self.intent_router = intent_router or IntentRouter()
        self.scenario_policy = scenario_policy or ScenarioPolicy()
        self.semantic_adapter = semantic_adapter or SemanticPlannerAdapter()
        self.task_planner = task_planner or TaskPlanner(
            scenario_policy=self.scenario_policy,
            semantic_adapter=self.semantic_adapter,
        )
        self.tool_executor = tool_executor
        self.enforce_policy = enforce_policy

    def route(self, user_text: str) -> RouteDecision | None:
        return self.intent_router.route(user_text)

    def execute(self, context: ToolContext) -> dict[str, Any] | None:
        automation_context = self._automation_context(context)
        log_boundary(logger, "ORCHESTRATOR", command=context.command, route="start", domain="", intent=context.intent, tool="", action="", status="planned")
        confirmation_response = self.semantic_adapter.try_confirmation_response(
            context.command,
            context=automation_context,
            execute_confirmed_plan=lambda plan: self._execute_confirmed_plan(plan, context),
        )
        if confirmation_response is not None:
            return confirmation_response

        dry_run_response = self.semantic_adapter.try_dry_run_response(
            context.command,
            context=automation_context,
        )
        if dry_run_response is not None:
            return dry_run_response

        route = self.route(context.command)
        if route is not None and (
            route.tool_name == "whatsapp"
            or (route.tool_name == "file" and route.operation == "search_files")
        ):
            return self._execute_route(route, context)

        semantic_result = self.semantic_adapter.try_live_result(
            context.command,
            context=automation_context,
            scenario_policy=self.scenario_policy,
        )
        if isinstance(semantic_result, dict):
            return semantic_result
        if semantic_result is not None:
            executor = self.tool_executor or ToolExecutor(
                registry=self.registry,
                scenario_policy=self.scenario_policy,
                enforce_policy=self.enforce_policy,
            )
            return executor.execute(semantic_result, context)

        plan = self.task_planner.plan(context.command)
        if plan.is_multistep:
            executor = self.tool_executor or ToolExecutor(
                registry=self.registry,
                scenario_policy=self.scenario_policy,
                enforce_policy=self.enforce_policy,
            )
            return executor.execute(plan, context)

        route = route or self.route(context.command)
        if route is None:
            log_boundary(logger, "ORCHESTRATOR", command=context.command, route="none", domain="", intent="", tool="", action="", status="blocked")
            return None

        return self._execute_route(route, context)

    def _execute_route(self, route: RouteDecision, context: ToolContext) -> dict[str, Any]:
        log_boundary(
            logger,
            "ORCHESTRATOR",
            command=context.command,
            route=route.scenario,
            domain=route.category,
            intent=route.intent,
            tool=route.tool_name,
            action=route.operation,
            status="executing",
        )
        if not self.registry.contains(route.tool_name) and self.registry.by_intent(route.intent) is None:
            log_boundary(logger, "ORCHESTRATOR", command=context.command, route=route.scenario, domain=route.category, intent=route.intent, tool=route.tool_name, action=route.operation, status="blocked")
            return {
                "success": False,
                "action": "tool_not_found",
                "message": f"No tool is registered for {route.intent}.",
                "route": route,
            }

        plan = ActionPlan(
            original_text=context.command,
            steps=[
                ActionStep(
                    step_id="step1",
                    tool_name=route.tool_name,
                    intent=route.intent,
                    action=route.operation,
                    args=dict(route.parameters),
                )
            ],
            is_multistep=False,
        )
        executor = self.tool_executor or ToolExecutor(
            registry=self.registry,
            scenario_policy=self.scenario_policy,
            enforce_policy=self.enforce_policy,
        )
        result = executor.execute(plan, context)
        if isinstance(result, dict):
            result.setdefault("selected_tool", route.tool_name)
            result.setdefault("scenario", route.scenario)
            log_boundary(logger, "ORCHESTRATOR", command=context.command, route=route.scenario, domain=route.category, intent=route.intent, tool=route.tool_name, action=route.operation, status="complete" if result.get("success") else "blocked")
        return result

    def execute_text(self, user_text: str, **context_kwargs: Any) -> dict[str, Any] | None:
        return self.execute(ToolContext(command=user_text, **context_kwargs))

    def _execute_confirmed_plan(self, plan: Any, context: ToolContext) -> dict[str, Any]:
        executor = self.tool_executor or ToolExecutor(
            registry=self.registry,
            scenario_policy=self.scenario_policy,
            enforce_policy=self.enforce_policy,
        )
        confirmed_context = ToolContext(
            command=context.command,
            intent=context.intent,
            session_id=context.session_id,
            face_session_id=context.face_session_id,
            step_up_token=context.step_up_token,
            payload=dict(context.payload),
            source=context.source,
            user_id=context.user_id,
            security_state=dict(context.security_state),
            confirmation_state={**dict(context.confirmation_state), "confirmed": True},
            request_id=context.request_id,
            metadata=dict(context.metadata),
        )
        return executor.execute(plan, confirmed_context)

    @staticmethod
    def _automation_context(context: ToolContext) -> Any | None:
        payload_context = context.payload.get("automation_context")
        if payload_context is not None:
            return payload_context
        return context.metadata.get("automation_context")
