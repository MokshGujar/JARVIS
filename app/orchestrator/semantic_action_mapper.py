from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PureWindowsPath
from typing import Any

from app.orchestrator.action_plan import ActionPlan, ActionStep
from app.orchestrator.automation_context import AutomationContext
from app.orchestrator.intent_router import RouteDecision
from app.orchestrator.scenario_policy import ScenarioPolicy
from app.orchestrator.semantic_automation import SemanticAutomationAction, SemanticAutomationIntent


BLOCKED_INTENTS = {
    SemanticAutomationIntent.DELETE_FILE,
    SemanticAutomationIntent.SEND_MESSAGE_AFTER_CONFIRMATION,
    SemanticAutomationIntent.CALL_CONTACT,
    SemanticAutomationIntent.CLICK_TEXT,
    SemanticAutomationIntent.SUBMIT_FORM,
    SemanticAutomationIntent.CLOSE_WINDOW,
}

MUTATING_INTENTS = {
    SemanticAutomationIntent.CREATE_FILE,
    SemanticAutomationIntent.WRITE_FILE,
    SemanticAutomationIntent.APPEND_FILE,
    SemanticAutomationIntent.SAVE_CONTENT_AS_FILE,
    SemanticAutomationIntent.WRITE_NOTE,
    SemanticAutomationIntent.APPEND_TO_NOTE,
    SemanticAutomationIntent.REPLACE_ADDRESS_OR_SEARCH,
    SemanticAutomationIntent.CLEAR_FIELD,
    SemanticAutomationIntent.PASTE_TEXT,
    SemanticAutomationIntent.PRESS_SAFE_KEY,
}


@dataclass(slots=True)
class SemanticMappingResult:
    plan: ActionPlan | None = None
    response: dict[str, Any] | None = None
    fingerprints: list[Any] = field(default_factory=list)


class SemanticActionMapper:
    def __init__(self, *, scenario_policy: ScenarioPolicy | None = None) -> None:
        self.scenario_policy = scenario_policy or ScenarioPolicy()

    def map_actions(
        self,
        *,
        original_text: str,
        corrected_text: str,
        actions: list[SemanticAutomationAction],
        context: AutomationContext | None = None,
        fingerprints: list[Any] | None = None,
    ) -> SemanticMappingResult:
        steps: list[ActionStep] = []
        semantic_by_step: dict[str, dict[str, Any]] = {}

        for action in actions:
            blocked = self._blocked_action_response(action)
            if blocked is not None:
                return SemanticMappingResult(response=blocked)

            mapped = self._steps_for_action(action, steps, context=context)
            if isinstance(mapped, dict):
                return SemanticMappingResult(response=mapped)
            for step in mapped:
                self._apply_policy(step)
                if step.safety_level in {"HIGH", "CRITICAL"} or step.requires_confirmation:
                    return SemanticMappingResult(response=self._policy_block_response(action, step))
                steps.append(step)
                semantic_by_step[step.step_id] = action.as_dict()

        if not steps:
            return SemanticMappingResult(response=_response("unsupported_semantic_action", "I can't safely run that semantic action yet."))

        plan = ActionPlan(
            original_text=corrected_text or original_text,
            steps=steps,
            is_multistep=True,
            requires_confirmation=any(step.requires_confirmation for step in steps),
            requires_face_step_up=any(step.requires_face_step_up for step in steps),
            requires_voice_permission=any(step.requires_voice_permission for step in steps),
            metadata={
                "semantic_execution": True,
                "original_text": original_text,
                "corrected_text": corrected_text,
                "semantic_actions": [action.as_dict() for action in actions],
                "semantic_step_actions": semantic_by_step,
                "fingerprints": [item.as_dict() for item in fingerprints or []],
            },
        )
        return SemanticMappingResult(plan=plan, fingerprints=list(fingerprints or []))

    def _steps_for_action(
        self,
        action: SemanticAutomationAction,
        current_steps: list[ActionStep],
        *,
        context: AutomationContext | None,
    ) -> list[ActionStep] | dict[str, Any]:
        intent = action.intent

        if intent == SemanticAutomationIntent.OPEN_APP:
            app = action.app or action.target
            if not app:
                return _missing("app", "Which app should I use?")
            return [self._step(current_steps, "app", "app_open", "open", {"app": app})]

        if intent in {SemanticAutomationIntent.FOCUS_APP, SemanticAutomationIntent.SWITCH_APP}:
            app = action.app or action.target
            if not app:
                return _missing("app", "Which app should I use?")
            return [self._step(current_steps, "app", "app_focus", "focus", {"app": app})]

        if intent == SemanticAutomationIntent.SEARCH_WEB:
            if not action.query:
                return _missing("search_query", "What should I search?")
            return [self._step(current_steps, "browser", "browser_search", "search", {"query": action.query})]

        if intent == SemanticAutomationIntent.SEARCH_VISIBLE_BROWSER:
            if not action.query:
                return _missing("search_query", "What should I search?")
            app = action.app or (context.active_app if context and context.active_app in {"chrome", "edge"} else None)
            return self._visible_search_steps(action.query, app=app, current_steps=current_steps)

        if intent == SemanticAutomationIntent.REPLACE_ADDRESS_OR_SEARCH:
            if not action.query:
                return _missing("search_query", "What should I search?")
            return [self._step(current_steps, "browser", "browser_search", "search", {"query": action.query})]

        if intent == SemanticAutomationIntent.CREATE_FILE:
            split = _split_file_path(action.file_path)
            if split is None:
                return _missing("location", "Where should I save it?")
            parent, filename = split
            return [self._step(current_steps, "file", "file", "create_file", {"parent": parent, "filename": filename})]

        if intent == SemanticAutomationIntent.WRITE_FILE:
            if not action.file_path:
                return _missing("file", "Which file should I use?")
            if action.content is None:
                return _missing("content", "What should I write?")
            path = self._created_path_for(action.file_path, current_steps) or action.file_path
            write = self._step(current_steps, "file", "file", "write_file", {"path": path, "content": action.content, "overwrite": False})
            if isinstance(path, str) and path.startswith("{"):
                verify = self._step(
                    current_steps + [write],
                    "file",
                    "file",
                    "verify_exists",
                    {"path": path, "expected_content": action.content},
                    depends_on=[write.step_id],
                )
                return [write, verify]
            return [write]

        if intent == SemanticAutomationIntent.APPEND_FILE:
            if not action.file_path:
                return _missing("file", "Which file should I use?")
            if action.content is None:
                return _missing("content", "What should I write?")
            return [self._step(current_steps, "file", "file", "append_file", {"path": action.file_path, "content": action.content})]

        if intent == SemanticAutomationIntent.SAVE_CONTENT_AS_FILE:
            if action.content is None:
                return _missing("content", "What should I save?")
            split = _split_file_path(action.file_path)
            if split is None:
                return _missing("location", "Where should I save it?")
            parent, filename = split
            create = self._step(current_steps, "file", "file", "create_file", {"parent": parent, "filename": filename})
            write = self._step(
                current_steps + [create],
                "file",
                "file",
                "write_file",
                {"path": f"{{{create.step_id}.path}}", "content": action.content, "overwrite": False},
                depends_on=[create.step_id],
            )
            return [create, write]

        if intent == SemanticAutomationIntent.WRITE_NOTE:
            content = action.content
            if content is None:
                return _missing("content", "What should I write?")
            app = action.app or "notepad"
            open_step = self._step(current_steps, "app", "app_open", "open", {"app": app})
            type_step = self._step(
                current_steps + [open_step],
                "app_interaction",
                "type_into_active_field",
                "type_into_active_field",
                {"text": content},
                depends_on=[open_step.step_id],
            )
            return [open_step, type_step]

        if intent == SemanticAutomationIntent.APPEND_TO_NOTE:
            if action.content is None:
                return _missing("content", "What should I write?")
            if not (context and (context.current_document_context or context.active_app)):
                return _missing("document_context", "Which note should I use?")
            return [self._step(current_steps, "app_interaction", "append_text", "append_text", {"text": action.content})]

        if intent == SemanticAutomationIntent.CLEAR_FIELD:
            return [self._step(current_steps, "app_interaction", "clear_current_field", "clear_current_field")]

        if intent == SemanticAutomationIntent.COPY_SELECTION:
            return [self._step(current_steps, "app_interaction", "copy_selection", "copy_selection")]

        if intent == SemanticAutomationIntent.PASTE_TEXT:
            if action.content is None and not (context and context.last_content):
                return _missing("content", "What should I paste?")
            return [self._step(current_steps, "app_interaction", "paste_text", "paste_text", {"text": action.content or context.last_content})]

        if intent == SemanticAutomationIntent.PRESS_SAFE_KEY:
            key = str(action.metadata.get("key") or action.target or "").strip().lower()
            if not key:
                return _missing("key", "Which key should I press?")
            return [self._step(current_steps, "app_interaction", "press_safe_key", "press_safe_key", {"key": key})]

        if intent == SemanticAutomationIntent.READ_ACTIVE_WINDOW:
            return [self._step(current_steps, "app_interaction", "read_window_title", "read_window_title")]

        return _response("unsupported_semantic_action", "I can't safely run that semantic action yet.")

    def _visible_search_steps(self, query: str, *, app: str | None, current_steps: list[ActionStep]) -> list[ActionStep]:
        steps: list[ActionStep] = []
        if app:
            steps.append(self._step(current_steps + steps, "app", "app_open", "open", {"app": app}))
        select = self._step(
            current_steps + steps,
            "app_interaction",
            "select_address_bar",
            "select_address_bar",
            depends_on=[steps[-1].step_id] if steps else [],
        )
        replace = self._step(
            current_steps + steps + [select],
            "app_interaction",
            "replace_current_field",
            "replace_current_field",
            {"text": query},
            depends_on=[select.step_id],
        )
        submit = self._step(
            current_steps + steps + [select, replace],
            "app_interaction",
            "submit_current_field",
            "submit_current_field",
            depends_on=[replace.step_id],
        )
        return steps + [select, replace, submit]

    def _step(
        self,
        existing: list[ActionStep],
        tool_name: str,
        intent: str,
        action: str,
        args: dict[str, Any] | None = None,
        *,
        depends_on: list[str] | None = None,
    ) -> ActionStep:
        return ActionStep(
            step_id=f"step{len(existing) + 1}",
            tool_name=tool_name,
            intent=intent,
            action=action,
            args=dict(args or {}),
            depends_on=list(depends_on or []),
        )

    def _apply_policy(self, step: ActionStep) -> None:
        decision = self.scenario_policy.evaluate(
            RouteDecision(
                scenario=f"{step.tool_name}.{step.action}",
                intent=step.intent,
                tool_name=step.tool_name,
                category=step.tool_name,
                operation=step.action,
                parameters=dict(step.args),
            )
        )
        step.safety_level = decision.safety_level
        step.requires_confirmation = decision.requires_confirmation
        step.requires_face_step_up = decision.requires_face_step_up
        step.requires_voice_permission = decision.requires_voice_permission

    def _blocked_action_response(self, action: SemanticAutomationAction) -> dict[str, Any] | None:
        if action.intent in BLOCKED_INTENTS or str(action.safety_level or "").upper() in {"HIGH", "CRITICAL"}:
            return _response(
                "semantic_action_blocked",
                _blocked_message(action),
                requires_confirmation=True,
                safety_level=str(action.safety_level or "HIGH").upper(),
            )
        return None

    @staticmethod
    def _policy_block_response(action: SemanticAutomationAction, step: ActionStep) -> dict[str, Any]:
        return _response(
            "semantic_action_blocked",
            _blocked_message(action),
            requires_confirmation=step.requires_confirmation,
            safety_level=step.safety_level,
        )

    @staticmethod
    def _created_path_for(file_path: str, current_steps: list[ActionStep]) -> str | None:
        file_name = _split_file_path(file_path)
        if file_name is None:
            return None
        _, filename = file_name
        for step in reversed(current_steps):
            if step.action == "create_file" and step.args.get("filename") == filename:
                return f"{{{step.step_id}.path}}"
        return None


def _split_file_path(path_value: str | None) -> tuple[str, str] | None:
    raw = str(path_value or "").strip()
    if not raw:
        return None
    normalized = raw.replace("\\", "/")
    if "/" not in normalized:
        return None
    parent, filename = normalized.rsplit("/", 1)
    filename = filename.strip()
    parent = parent.strip()
    if not parent or not filename:
        return None
    return parent, PureWindowsPath(filename).name


def _missing(field: str, question: str) -> dict[str, Any]:
    return {
        "success": False,
        "action": "semantic_followup_required",
        "message": question,
        "display_text": question,
        "spoken_text": question,
        "requires_followup": True,
        "missing_fields": [field],
        "follow_up_question": question,
        "semantic_execution": True,
        "executable": False,
    }


def _response(
    action: str,
    message: str,
    *,
    requires_confirmation: bool = False,
    safety_level: str = "LOW",
) -> dict[str, Any]:
    return {
        "success": False,
        "action": action,
        "message": message,
        "display_text": message,
        "spoken_text": message,
        "requires_confirmation": requires_confirmation,
        "safety_level": safety_level,
        "semantic_execution": True,
        "executable": False,
    }


def _blocked_message(action: SemanticAutomationAction) -> str:
    if action.intent == SemanticAutomationIntent.DELETE_FILE:
        return "I need confirmation before deleting that, and semantic delete execution is not enabled yet."
    if action.intent == SemanticAutomationIntent.SEND_MESSAGE_AFTER_CONFIRMATION:
        return "I need confirmation before sending that, and semantic send execution is not enabled yet."
    if action.intent == SemanticAutomationIntent.CALL_CONTACT:
        return "I need confirmation before making that call, and semantic call execution is not enabled yet."
    if action.intent == SemanticAutomationIntent.SUBMIT_FORM:
        return "I can't submit forms through semantic execution yet."
    if action.intent == SemanticAutomationIntent.CLICK_TEXT:
        return "I can't safely click that through semantic execution yet."
    if action.intent == SemanticAutomationIntent.CLOSE_WINDOW:
        return "I need confirmation before closing that window, and semantic close execution is not enabled yet."
    return "I can't safely run that semantic action yet."
