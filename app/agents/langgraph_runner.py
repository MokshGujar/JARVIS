from __future__ import annotations

import importlib.util
from typing import Any

from app.agents.langgraph_state import LangGraphState, ToolRequest
from app.orchestrator.action_plan import ActionPlan, ActionStep
from app.orchestrator.tool_executor import ToolExecutor
from app.tools.base import ToolContext
from config import JARVIS_ENABLE_LANGGRAPH_AGENTS


SIMPLE_COMMAND_PREFIXES = (
    "open ",
    "launch ",
    "volume ",
    "search google ",
    "search google for ",
    "send whatsapp ",
    "call ",
    "send email ",
)


class LangGraphRunner:
    def __init__(self, *, enabled: bool | None = None, tool_executor: ToolExecutor | None = None) -> None:
        self.enabled = bool(JARVIS_ENABLE_LANGGRAPH_AGENTS) if enabled is None else bool(enabled)
        self.tool_executor = tool_executor
        self.dependency_available = importlib.util.find_spec("langgraph") is not None

    def should_route(self, command: str) -> bool:
        if not self.enabled:
            return False
        lowered = str(command or "").strip().lower()
        if not lowered or lowered.startswith(SIMPLE_COMMAND_PREFIXES):
            return False
        return any(phrase in lowered for phrase in ("daily briefing", "research", "report", "summarize files", "agent"))

    def run(self, state: LangGraphState, *, context: ToolContext | None = None) -> dict[str, Any]:
        if not self.enabled:
            return {"success": False, "action": "langgraph_disabled", "message": "LangGraph agents are disabled."}
        if not self.dependency_available:
            return {"success": False, "action": "langgraph_unavailable", "message": "LangGraph is not installed."}
        if self.tool_executor is None:
            return {"success": False, "action": "langgraph_no_executor", "message": "No ToolExecutor is configured for LangGraph."}

        results = []
        for request in state.tool_requests:
            results.append(self.execute_tool_request(request, context=context or ToolContext(command=state.user_request)))
        return {"success": all(bool(item.get("success")) for item in results), "action": "langgraph_run", "message": "Workflow handled.", "results": results}

    def execute_tool_request(self, request: ToolRequest, *, context: ToolContext) -> dict[str, Any]:
        if self.tool_executor is None:
            return {"success": False, "action": "tool_executor_missing", "message": "ToolExecutor is required."}
        plan = ActionPlan(
            original_text=context.command,
            steps=[
                ActionStep(
                    step_id="step1",
                    tool_name=request.tool_name,
                    intent=request.intent or request.tool_name,
                    action=request.action,
                    args=dict(request.args),
                )
            ],
        )
        return self.tool_executor.execute(plan, context)
