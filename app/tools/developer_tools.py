from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.tools.base import BaseTool, ToolContext, ToolResult, ToolRisk, ToolSpec


DESTRUCTIVE_TERMINAL_PATTERNS = (
    re.compile(r"\brm\s+-rf\b", re.IGNORECASE),
    re.compile(r"\bdel\s+/[sq]\b", re.IGNORECASE),
    re.compile(r"\bformat\b", re.IGNORECASE),
    re.compile(r"\bgit\s+reset\s+--hard\b", re.IGNORECASE),
    re.compile(r"\bshutdown\b", re.IGNORECASE),
)


class CodeSearchTool(BaseTool):
    name = "code_search"

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root or Path.cwd()).resolve()
        self.spec = ToolSpec(
            name=self.name,
            description="Read-only project code search.",
            category="developer",
            risk_level="LOW",
            safety_level="LOW",
            status="PARTIAL",
            routing_mode="ACTIVE",
            allowed_actions=["search"],
            safe_partial_actions=["search"],
            supported_intents=["code_search"],
        )

    def classify_risk(self, command: str) -> ToolRisk:
        return ToolRisk(level="LOW", reasons=["read_only_code_search"])

    def execute(self, context: ToolContext, **kwargs: Any) -> dict[str, Any]:
        args = dict(context.payload.get("args") or {})
        query = str(args.get("query") or context.command or "").strip()
        if not query:
            return ToolResult(False, "Tell me what code text to search for.", tool_name=self.name, error="query_required", data={"action": "search"}).as_dict()
        matches = []
        for path in self.root.rglob("*.py"):
            if "__pycache__" in path.parts or ".git" in path.parts:
                continue
            try:
                for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1):
                    if query.lower() in line.lower():
                        matches.append({"path": str(path.relative_to(self.root)), "line": lineno, "preview": line.strip()[:160]})
                        break
            except Exception:
                continue
            if len(matches) >= 20:
                break
        return ToolResult(True, f"Found {len(matches)} code file(s).", tool_name=self.name, data={"action": "search", "matches": matches}).as_dict()


class DeveloperCommandProposalTool(BaseTool):
    name = "developer_command_proposal"

    def __init__(self) -> None:
        self.spec = ToolSpec(
            name=self.name,
            description="Proposes terminal commands without executing them.",
            category="developer",
            risk_level="LOW",
            safety_level="LOW",
            status="PARTIAL",
            routing_mode="ACTIVE",
            allowed_actions=["propose"],
            safe_partial_actions=["propose"],
            supported_intents=["terminal", "developer"],
        )

    def classify_risk(self, command: str) -> ToolRisk:
        return ToolRisk(level="LOW", reasons=["proposal_only"])

    def execute(self, context: ToolContext, **kwargs: Any) -> dict[str, Any]:
        args = dict(context.payload.get("args") or {})
        command = str(args.get("command") or context.command or "").strip()
        blocked = _is_destructive(command)
        return ToolResult(
            success=not blocked,
            tool_name=self.name,
            message="I can propose that command, but I will not run it." if not blocked else "I will not propose a destructive command.",
            error="destructive_command_blocked" if blocked else None,
            data={"action": "propose", "command": "" if blocked else command, "executes": False},
        ).as_dict()


class TestRunnerTool(BaseTool):
    __test__ = False
    name = "test_runner"

    def __init__(self) -> None:
        self.spec = ToolSpec(
            name=self.name,
            description="Permission-gated test command proposal.",
            category="developer",
            risk_level="MEDIUM",
            safety_level="MEDIUM",
            status="PARTIAL",
            routing_mode="ACTIVE",
            allowed_actions=["propose_test_run"],
            safe_partial_actions=["propose_test_run"],
            supported_intents=["test_runner"],
        )

    def classify_risk(self, command: str) -> ToolRisk:
        return ToolRisk(level="MEDIUM", reasons=["requires_permission"])

    def execute(self, context: ToolContext, **kwargs: Any) -> dict[str, Any]:
        args = dict(context.payload.get("args") or {})
        command = str(args.get("command") or context.command or "").strip()
        if _is_destructive(command):
            return ToolResult(False, "That test command is blocked because it contains a destructive operation.", tool_name=self.name, error="destructive_command_blocked", data={"action": "propose_test_run", "executes": False}).as_dict()
        return ToolResult(
            False,
            "Test execution requires explicit permission.",
            tool_name=self.name,
            error="permission_required",
            requires_followup=True,
            data={"action": "propose_test_run", "command": command, "executes": False},
        ).as_dict()


def _is_destructive(command: str) -> bool:
    return any(pattern.search(command or "") for pattern in DESTRUCTIVE_TERMINAL_PATTERNS)
