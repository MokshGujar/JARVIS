from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, ClassVar

from app.orchestrator.action_plan import ActionPlan, ActionStep
from app.orchestrator.intent_router import RouteDecision
from app.orchestrator.scenario_policy import ScenarioPolicy
from app.orchestrator.semantic_planner_adapter import SemanticPlannerAdapter

logger = logging.getLogger(__name__)


class TaskPlanner:
    """Deterministic planner for the first supported multi-step patterns."""

    WRITE_CONTENT_SUFFIXES: ClassVar[tuple[str, ...]] = (
        " into the file",
        " inside the file",
        " in the file",
        " to the file",
        " into it",
        " inside it",
        " in it",
        " to it",
    )

    FILE_CREATE_WRITE_RE = re.compile(
        r"^create\s+(?:a\s+)?file\s+(?:on|in)\s+(?:my\s+)?(?P<location>desktop|documents|downloads|home)"
        r"\s+(?:named|called)\s+(?P<name>.+?)\s+and\s+"
        r"(?:(?:in|into)\s+(?:that|the)\s+file\s+)?(?:write|add|put|insert)\s+(?P<content>[\s\S]+?)[.!?]*$",
        re.IGNORECASE,
    )
    FOLDER_CREATE_RE = re.compile(
        r"^create\s+(?:a\s+)?folder\s+(?:on|in)\s+(?:my\s+)?(?P<location>desktop|documents|downloads|home)"
        r"\s+(?:named|called)\s+(?P<name>.+?)[.!?]*$",
        re.IGNORECASE,
    )
    OPEN_AND_SEARCH_RE = re.compile(
        r"^open\s+(?P<app>.+?)\s+and\s+search\s+(?:for\s+)?(?P<query>.+?)(?:\s+on\s+google)?[.!?]*$",
        re.IGNORECASE,
    )
    OPEN_AND_TYPE_RE = re.compile(
        r"^open\s+(?P<app>.+?)\s+and\s+type\s+(?P<text>.+?)[.!?]*$",
        re.IGNORECASE,
    )
    READ_AND_SUMMARIZE_RE = re.compile(
        r"^read\s+file\s+(?P<path>.+?)\s+and\s+summari[sz]e(?:\s+it)?[.!?]*$",
        re.IGNORECASE,
    )

    def __init__(
        self,
        *,
        scenario_policy: ScenarioPolicy | None = None,
        semantic_adapter: SemanticPlannerAdapter | None = None,
    ) -> None:
        self.scenario_policy = scenario_policy or ScenarioPolicy()
        self.semantic_adapter = semantic_adapter

    def plan(self, text: str, context: Any | None = None) -> ActionPlan:
        original_text = str(text or "").strip()
        if not original_text:
            return ActionPlan(original_text=original_text)

        if self.semantic_adapter is not None:
            semantic_plan = self.semantic_adapter.try_plan_action(original_text, context=context)
            if semantic_plan is not None:
                logger.debug("Generated semantic action plan for %r: %s", original_text, semantic_plan.as_dict())
                return semantic_plan

        for builder in (
            self._plan_create_file_and_write,
            self._plan_create_folder,
            self._plan_open_and_search,
            self._plan_open_and_type,
            self._plan_read_and_summarize,
        ):
            plan = builder(original_text)
            if plan is not None:
                logger.debug("Generated action plan for %r: %s", original_text, plan.as_dict())
                return plan

        return ActionPlan(original_text=original_text, is_multistep=False)

    def _plan_create_file_and_write(self, text: str) -> ActionPlan | None:
        match = self.FILE_CREATE_WRITE_RE.match(text)
        if not match:
            return None
        location = self._clean_value(match.group("location"))
        filename = self._ensure_text_extension(self._clean_value(match.group("name")))
        content = self._clean_content(match.group("content"))
        return self._build_plan(
            text,
            [
                ActionStep("step1", "file", "file", "resolve_path", {"location": location}),
                ActionStep(
                    "step2",
                    "file",
                    "file",
                    "create_file",
                    {"parent": "{step1.path}", "filename": filename},
                    depends_on=["step1"],
                ),
                ActionStep(
                    "step3",
                    "file",
                    "file",
                    "write_file",
                    {"path": "{step2.path}", "content": content, "overwrite": False},
                    depends_on=["step2"],
                ),
                ActionStep(
                    "step4",
                    "file",
                    "file",
                    "verify_exists",
                    {"path": "{step2.path}", "expected_content": content},
                    depends_on=["step2", "step3"],
                ),
            ],
        )

    def _plan_create_folder(self, text: str) -> ActionPlan | None:
        match = self.FOLDER_CREATE_RE.match(text)
        if not match:
            return None
        location = self._clean_value(match.group("location"))
        name = self._clean_value(match.group("name"))
        return self._build_plan(
            text,
            [
                ActionStep("step1", "file", "file", "resolve_path", {"location": location}),
                ActionStep(
                    "step2",
                    "file",
                    "file",
                    "create_folder",
                    {"parent": "{step1.path}", "name": name},
                    depends_on=["step1"],
                ),
                ActionStep("step3", "file", "file", "verify_exists", {"path": "{step2.path}"}, depends_on=["step2"]),
            ],
        )

    def _plan_open_and_search(self, text: str) -> ActionPlan | None:
        match = self.OPEN_AND_SEARCH_RE.match(text)
        if not match:
            return None
        app = self._clean_value(match.group("app"))
        query = self._clean_content(match.group("query"))
        return self._build_plan(
            text,
            [
                ActionStep("step1", "app", "app_open", "open", {"app": app}),
                ActionStep("step2", "browser", "browser_search", "search", {"query": query}, depends_on=["step1"]),
            ],
        )

    def _plan_open_and_type(self, text: str) -> ActionPlan | None:
        match = self.OPEN_AND_TYPE_RE.match(text)
        if not match:
            return None
        app = self._clean_value(match.group("app"))
        text_to_type = self._clean_content(match.group("text"))
        return self._build_plan(
            text,
            [
                ActionStep("step1", "app", "app_open", "open", {"app": app}),
                ActionStep(
                    "step2",
                    "app_interaction",
                    "type_text",
                    "type_text",
                    {"text": text_to_type},
                    depends_on=["step1"],
                ),
            ],
        )

    def _plan_read_and_summarize(self, text: str) -> ActionPlan | None:
        match = self.READ_AND_SUMMARIZE_RE.match(text)
        if not match:
            return None
        path_or_name = self._clean_value(match.group("path"))
        return self._build_plan(
            text,
            [
                ActionStep("step1", "file", "file", "read_file", {"path_or_name": path_or_name}),
                ActionStep(
                    "step2",
                    "summary",
                    "summarize",
                    "summarize",
                    {"content": "{step1.content}"},
                    depends_on=["step1"],
                ),
            ],
        )

    def _build_plan(self, original_text: str, steps: list[ActionStep]) -> ActionPlan:
        for step in steps:
            decision = self.scenario_policy.evaluate(self._route_for_step(step))
            step.safety_level = decision.safety_level
            step.requires_confirmation = decision.requires_confirmation
            step.requires_face_step_up = decision.requires_face_step_up
            step.requires_voice_permission = decision.requires_voice_permission

        return ActionPlan(
            original_text=original_text,
            steps=steps,
            is_multistep=True,
            requires_confirmation=any(step.requires_confirmation for step in steps),
            requires_face_step_up=any(step.requires_face_step_up for step in steps),
            requires_voice_permission=any(step.requires_voice_permission for step in steps),
        )

    @staticmethod
    def _route_for_step(step: ActionStep) -> RouteDecision:
        return RouteDecision(
            scenario=f"{step.tool_name}.{step.action}",
            intent=step.intent,
            tool_name=step.tool_name,
            category=step.tool_name,
            operation=step.action,
            parameters=dict(step.args),
        )

    @staticmethod
    def _clean_value(value: str) -> str:
        return re.sub(r"\s+", " ", str(value or "").strip()).strip(" .!?")

    @classmethod
    def _clean_content(cls, value: str) -> str:
        return cls._extract_write_content(value)

    @classmethod
    def _extract_write_content(cls, text: str) -> str:
        raw = str(text or "").strip()
        quoted = re.fullmatch(r"""(['"])(?P<content>[\s\S]*?)\1(?:\s+(?:in|into|inside|to)\s+(?:it|the\s+file))?[.!?]*""", raw)
        if quoted:
            return re.sub(r"\s+", " ", quoted.group("content").strip())

        cleaned = re.sub(r"[.!?]+\s*$", "", raw).strip()
        lowered = cleaned.lower()
        for suffix in cls.WRITE_CONTENT_SUFFIXES:
            if lowered.endswith(suffix):
                cleaned = cleaned[: -len(suffix)].rstrip()
                break
        return re.sub(r"\s+", " ", cleaned).strip()

    @classmethod
    def _ensure_text_extension(cls, filename: str) -> str:
        cleaned = cls._clean_value(filename)
        return cleaned if Path(cleaned).suffix else f"{cleaned}.txt"
