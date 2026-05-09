from app.agents.agent_builder import AgentBuilder


def test_create_ai_news_agent_draft_requires_approval():
    result = AgentBuilder().build_draft("Create an agent that tracks AI news")

    assert result["success"] is True
    definition = result["definition"]
    assert definition["name"] == "AI news tracker"
    assert definition["enabled"] is False
    assert definition["status"] == "draft"
    assert definition["allowed_tools"] == ["research", "summary"]
    assert "user_approval" in definition["approval_requirements"]


def test_unsafe_agent_with_communication_or_terminal_is_rejected():
    result = AgentBuilder().build_draft("Create an agent that sends WhatsApp updates and runs terminal commands")

    assert result["success"] is False
    assert result["action"] == "agent_rejected"
