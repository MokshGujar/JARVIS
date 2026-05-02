from __future__ import annotations

from typing import Any, Protocol

from app.adapters.providers.summary_provider import SummaryProviderUnavailable, build_summary_provider, summary_provider_readiness
from app.tools.base import BaseTool, ToolContext, ToolResult, ToolSpec


class Summarizer(Protocol):
    def summarize(self, text: str, mode: str = "summary") -> str:
        ...


class SummaryTool(BaseTool):
    name = "summary"
    spec = ToolSpec(
        name="summary",
        description="Summarize text passed from planned tool steps.",
        category="research",
        safety_level="LOW",
        supported_intents=["summary", "summarize", "extract_key_points", "make_notes"],
        metadata={
            "supported_actions": ["summarize", "extract_key_points", "make_notes"],
            "current_status": "thin_wrapper",
        },
    )

    def __init__(self, summarizer: Summarizer | None = None, *, max_input_chars: int = 32000) -> None:
        self.summarizer = summarizer if summarizer is not None else build_summary_provider()
        self.max_input_chars = max_input_chars

    def execute(self, context: ToolContext, **kwargs: Any) -> dict[str, Any]:
        action = str(context.payload.get("action") or context.intent or "summarize").strip().lower()
        if action not in {"summarize", "summary", "extract_key_points", "make_notes"}:
            return ToolResult(
                success=False,
                message=f"Summary tool does not support action {action}.",
                tool_name=self.name,
                error="unsupported_action",
                data={"action": action or "unsupported"},
            ).as_dict()

        args = dict(context.payload.get("args") or {})
        content = str(args.get("content") or args.get("text") or context.payload.get("content") or context.command or "").strip()
        if not content:
            return ToolResult(
                success=False,
                message="There is no content to summarize.",
                tool_name=self.name,
                error="empty_content",
                data={"action": "summarize", "input_length": 0, "output_length": 0},
            ).as_dict()

        if len(content) > self.max_input_chars:
            return ToolResult(
                success=False,
                message="That content is too long to summarize safely in one step.",
                tool_name=self.name,
                error="content_too_long",
                data={"action": "summarize", "input_length": len(content), "output_length": 0},
            ).as_dict()

        if self.summarizer is None:
            return ToolResult(
                success=False,
                message="Summary tool is wired, but no summarizer provider is configured.",
                tool_name=self.name,
                error="summarizer_unavailable",
                data={
                    "action": "summarize",
                    "input_length": len(content),
                    "output_length": 0,
                    "provider_readiness": summary_provider_readiness().as_dict(),
                },
            ).as_dict()

        try:
            mode = self._mode_for_action(action)
            summary = str(self._summarize(content, mode=mode) or "").strip()
        except SummaryProviderUnavailable:
            return ToolResult(
                success=False,
                message="Summary tool is wired, but no summarizer provider is configured.",
                tool_name=self.name,
                error="summarizer_unavailable",
                data={
                    "action": "summarize",
                    "input_length": len(content),
                    "output_length": 0,
                    "provider_readiness": summary_provider_readiness().as_dict(),
                },
            ).as_dict()
        except Exception as exc:
            return ToolResult(
                success=False,
                message=f"Summary failed: {exc}",
                tool_name=self.name,
                error="summary_failed",
                data={"action": "summarize", "input_length": len(content), "output_length": 0},
            ).as_dict()

        if not summary:
            return ToolResult(
                success=False,
                message="Summary provider returned an empty result.",
                tool_name=self.name,
                error="empty_summary",
                data={"action": "summarize", "input_length": len(content), "output_length": 0},
            ).as_dict()

        return ToolResult(
            success=True,
            message=summary,
            tool_name=self.name,
            data={
                "action": "summarize",
                "summary": summary,
                "input_length": len(content),
                "output_length": len(summary),
            },
        ).as_dict()

    @staticmethod
    def _mode_for_action(action: str) -> str:
        if action == "extract_key_points":
            return "key_points"
        if action == "make_notes":
            return "notes"
        return "summary"

    def _summarize(self, content: str, *, mode: str) -> str:
        try:
            return self.summarizer.summarize(content, mode=mode)
        except TypeError:
            return self.summarizer.summarize(content)
