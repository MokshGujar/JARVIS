from __future__ import annotations

from app.agents.langgraph_state import LangGraphState, ToolRequest


def build_file_report_state(query: str) -> LangGraphState:
    state = LangGraphState(user_request=query, workflow="file_report")
    state.tool_requests.append(
        ToolRequest(
            tool_name="file",
            action="search_files",
            args={"query": query},
            intent="file",
            reason="file_report_find_files",
        )
    )
    state.tool_requests.append(
        ToolRequest(
            tool_name="summary",
            action="summarize",
            args={"source": "{step1.message}"},
            intent="summary",
            reason="file_report_summary",
        )
    )
    return state
