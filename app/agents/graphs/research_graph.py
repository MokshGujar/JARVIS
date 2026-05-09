from __future__ import annotations

from app.agents.langgraph_state import LangGraphState, ToolRequest


def build_research_state(topic: str) -> LangGraphState:
    state = LangGraphState(user_request=topic, workflow="research")
    state.tool_requests.append(
        ToolRequest(
            tool_name="research",
            action="answer_with_sources",
            args={"query": topic},
            intent="research",
            reason="research_graph_query",
        )
    )
    state.tool_requests.append(
        ToolRequest(
            tool_name="summary",
            action="summarize",
            args={"source": "{step1.message}"},
            intent="summary",
            reason="research_graph_summary",
        )
    )
    return state
