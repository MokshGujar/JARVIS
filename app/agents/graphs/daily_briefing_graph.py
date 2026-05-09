from __future__ import annotations

from app.agents.langgraph_state import LangGraphState, ToolRequest


def build_daily_briefing_state(prompt: str = "daily briefing") -> LangGraphState:
    state = LangGraphState(user_request=prompt, workflow="daily_briefing")
    state.tool_requests.append(
        ToolRequest(
            tool_name="reminder",
            action="list",
            args={},
            intent="reminder",
            reason="daily_briefing_due_reminders",
        )
    )
    state.tool_requests.append(
        ToolRequest(
            tool_name="summary",
            action="summarize",
            args={"source": "{step1.message}"},
            intent="summary",
            reason="daily_briefing_summary",
        )
    )
    return state
