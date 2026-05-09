import shutil
from pathlib import Path

from app.tools.base import ToolContext
from app.tools.developer_tools import CodeSearchTool, DeveloperCommandProposalTool, TestRunnerTool


ROOT = Path(__file__).resolve().parent / "_tmp" / "developer_tools"


def reset_root():
    if ROOT.exists():
        shutil.rmtree(ROOT)
    ROOT.mkdir(parents=True)
    return ROOT


def test_code_search_read_only_works():
    root = reset_root()
    (root / "sample.py").write_text("class AutomationService:\n    pass\n", encoding="utf-8")
    tool = CodeSearchTool(root)

    result = tool.execute(ToolContext(command="", intent="code_search", payload={"args": {"query": "AutomationService"}}))

    assert result["success"] is True
    assert result["matches"][0]["path"] == "sample.py"


def test_command_proposal_does_not_execute():
    tool = DeveloperCommandProposalTool()

    result = tool.execute(ToolContext(command="python -m pytest tests/test_phone_command_service.py"))

    assert result["success"] is True
    assert result["executes"] is False


def test_safe_test_command_requires_permission():
    tool = TestRunnerTool()

    result = tool.execute(ToolContext(command="python -m pytest tests/test_phone_command_service.py"))

    assert result["success"] is False
    assert result["error"] == "permission_required"
    assert result["executes"] is False


def test_destructive_command_is_blocked():
    proposal = DeveloperCommandProposalTool().execute(ToolContext(command="git reset --hard"))
    test_run = TestRunnerTool().execute(ToolContext(command="pytest && rm -rf ."))

    assert proposal["error"] == "destructive_command_blocked"
    assert test_run["error"] == "destructive_command_blocked"
