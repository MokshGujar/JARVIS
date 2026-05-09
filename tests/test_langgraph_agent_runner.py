from app.agents.graphs.research_graph import build_research_state
from app.agents.langgraph_runner import LangGraphRunner
from app.agents.langgraph_state import LangGraphState, ToolRequest
from app.tools.base import ToolContext


class FakeExecutor:
    def __init__(self):
        self.calls = []

    def execute(self, plan, context):
        self.calls.append((plan, context))
        return {"success": True, "action": plan.steps[0].action, "message": "ok"}


def test_feature_flag_disabled_means_no_langgraph_route():
    runner = LangGraphRunner(enabled=False)

    assert runner.should_route("research AI news") is False
    assert runner.run(LangGraphState("research AI news", "research"))["action"] == "langgraph_disabled"


def test_simple_commands_bypass_langgraph_even_when_enabled():
    runner = LangGraphRunner(enabled=True)

    assert runner.should_route("open calculator") is False
    assert runner.should_route("search google for cats") is False


def test_graph_node_builders_emit_tool_requests_only():
    state = build_research_state("latest AI news")

    assert state.workflow == "research"
    assert all(isinstance(request, ToolRequest) for request in state.tool_requests)
    assert state.tool_requests[0].tool_name == "research"


def test_tool_request_goes_through_tool_executor_boundary():
    executor = FakeExecutor()
    runner = LangGraphRunner(enabled=True, tool_executor=executor)
    request = ToolRequest("summary", "summarize", {"text": "hello"}, intent="summary")

    result = runner.execute_tool_request(request, context=ToolContext(command="summarize hello"))

    assert result["success"] is True
    assert executor.calls[0][0].steps[0].tool_name == "summary"


def test_missing_langgraph_dependency_returns_safe_response():
    runner = LangGraphRunner(enabled=True, tool_executor=FakeExecutor())
    runner.dependency_available = False
    state = build_research_state("AI news")

    result = runner.run(state)

    assert result["success"] is False
    assert result["action"] == "langgraph_unavailable"
