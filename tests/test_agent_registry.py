import shutil
from pathlib import Path

from app.agents.agent_builder import AgentBuilder
from app.agents.agent_definition import AgentDefinition
from app.agents.agent_registry import AgentRegistry
from app.repositories.agent_repository import AgentRepository


ROOT = Path(__file__).resolve().parent / "_tmp" / "agent_registry"


def registry():
    if ROOT.exists():
        shutil.rmtree(ROOT)
    ROOT.mkdir(parents=True)
    return AgentRegistry(AgentRepository(ROOT / "agents.json"))


def test_approve_save_list_and_delete_agent():
    reg = registry()
    draft = AgentDefinition.from_dict(AgentBuilder().build_draft("Create an agent that tracks AI news")["definition"])

    reg.save_draft(draft)
    assert reg.list()[0].enabled is False
    assert reg.approve("AI news tracker")["success"] is True
    assert reg.get("AI news tracker").enabled is True
    assert reg.delete("AI news tracker") is True
    assert reg.list() == []


def test_disabled_agent_does_not_run():
    reg = registry()
    draft = AgentDefinition.from_dict(AgentBuilder().build_draft("Create an agent that tracks AI news")["definition"])
    reg.save_draft(draft)

    result = reg.run_now("AI news tracker")

    assert result["success"] is False
    assert result["action"] == "agent_disabled"


def test_allowed_tools_are_enforced():
    reg = registry()
    draft = AgentDefinition.from_dict(AgentBuilder().build_draft("Create an agent that tracks AI news")["definition"])
    reg.save_draft(draft)
    reg.approve("AI news tracker")

    denied = reg.run_now("AI news tracker", requested_tool="gmail")
    allowed = reg.run_now("AI news tracker", requested_tool="research")

    assert denied["action"] == "agent_tool_denied"
    assert allowed["action"] == "agent_run_queued"
