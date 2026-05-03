from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.orchestrator.action_plan import ActionPlan, ActionStep
from app.orchestrator.automation_context import AutomationContext
from app.orchestrator.intent_router import RouteDecision
from app.orchestrator.scenario_policy import ScenarioPolicy
from app.orchestrator.semantic_automation import (
    AutomationDomain,
    AutomationMode,
    SemanticActionPlan,
    SemanticAutomationAction,
    SemanticAutomationIntent,
)
from app.orchestrator.stt_automation_normalization import normalize_automation_command


@dataclass(slots=True)
class SmartAutomationPlanResult:
    original_text: str
    corrected_text: str
    corrections_applied: list[str] = field(default_factory=list)
    domain: AutomationDomain | None = None
    mode: AutomationMode | None = None
    semantic_actions: list[SemanticAutomationAction] = field(default_factory=list)
    semantic_plan: SemanticActionPlan | None = None
    action_plan: ActionPlan | None = None
    missing_fields: list[str] = field(default_factory=list)
    follow_up_question: str | None = None
    requires_confirmation: bool = False
    safety_level: str = "LOW"
    dry_run: bool = True
    executable: bool = False
    execution_deferred: bool = True
    duplicate_risk: bool = False
    idempotent_hint: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "original_text": self.original_text,
            "corrected_text": self.corrected_text,
            "corrections_applied": list(self.corrections_applied),
            "domain": self.domain.value if self.domain else None,
            "mode": self.mode.value if self.mode else None,
            "semantic_actions": [action.as_dict() for action in self.semantic_actions],
            "semantic_plan": self.semantic_plan.as_dict() if self.semantic_plan else None,
            "action_plan": self.action_plan.as_dict() if self.action_plan else None,
            "missing_fields": list(self.missing_fields),
            "follow_up_question": self.follow_up_question,
            "requires_confirmation": self.requires_confirmation,
            "safety_level": self.safety_level,
            "dry_run": self.dry_run,
            "executable": self.executable,
            "execution_deferred": self.execution_deferred,
            "duplicate_risk": self.duplicate_risk,
            "idempotent_hint": self.idempotent_hint,
            "metadata": dict(self.metadata),
        }


class SmartAutomationPlanner:
    """Dry-run semantic planner.

    This class describes what would be done later. It does not execute tools and
    is intentionally not wired into live orchestration in this phase.
    """

    RISKY_INTENTS = {
        SemanticAutomationIntent.DELETE_FILE,
        SemanticAutomationIntent.CLICK_TEXT,
        SemanticAutomationIntent.CLICK_COORDINATES,
        SemanticAutomationIntent.SUBMIT_FORM,
        SemanticAutomationIntent.PAYMENT_OR_PURCHASE_SUBMIT,
        SemanticAutomationIntent.LOGIN_SUBMIT,
        SemanticAutomationIntent.SEND_MESSAGE_AFTER_CONFIRMATION,
        SemanticAutomationIntent.CALL_CONTACT,
        SemanticAutomationIntent.CLOSE_WINDOW,
        SemanticAutomationIntent.RUN_TERMINAL_COMMAND,
        SemanticAutomationIntent.APPLY_CODE_EDIT,
        SemanticAutomationIntent.SHUTDOWN_SYSTEM,
        SemanticAutomationIntent.RESTART_SYSTEM,
    }
    CRITICAL_INTENTS = {
        SemanticAutomationIntent.DELETE_FILE,
        SemanticAutomationIntent.RUN_TERMINAL_COMMAND,
        SemanticAutomationIntent.APPLY_CODE_EDIT,
        SemanticAutomationIntent.SHUTDOWN_SYSTEM,
        SemanticAutomationIntent.RESTART_SYSTEM,
        SemanticAutomationIntent.PAYMENT_OR_PURCHASE_SUBMIT,
        SemanticAutomationIntent.LOGIN_SUBMIT,
    }
    NON_MUTATING_INTENTS = {
        SemanticAutomationIntent.SEARCH_WEB,
        SemanticAutomationIntent.READ_ACTIVE_WINDOW,
        SemanticAutomationIntent.READ_SCREEN_OR_WINDOW,
        SemanticAutomationIntent.SYSTEM_STATUS,
        SemanticAutomationIntent.EXPLAIN_PENDING_PLAN,
        SemanticAutomationIntent.DRY_RUN_PLAN,
    }

    def __init__(self, *, scenario_policy: ScenarioPolicy | None = None) -> None:
        self.scenario_policy = scenario_policy or ScenarioPolicy()

    def plan(self, text: str, context: AutomationContext | None = None, dry_run: bool = True) -> SmartAutomationPlanResult:
        original_text = str(text or "").strip()
        normalization = normalize_automation_command(original_text, context=context)
        corrected_text = normalization.corrected_text.strip()
        actions = self.extract_semantic_action(corrected_text, context=context)
        domain = actions[0].domain if actions else self.classify_domain(corrected_text, context=context)
        mode = actions[0].mode if actions else self.classify_mode(corrected_text, context=context)
        semantic_plan = SemanticActionPlan(
            original_text=original_text,
            actions=actions,
            mode=mode,
            requires_confirmation=any(action.intent in self.RISKY_INTENTS for action in actions),
            missing_fields=self._collect_missing_fields(actions),
            metadata={"corrected_text": corrected_text, "dry_run": True},
        )
        action_plan = self.build_dry_run_plan(actions, context=context)
        missing_fields = self._collect_missing_fields(actions)
        follow_up = self._follow_up_for(missing_fields)
        requires_confirmation = any(action.intent in self.RISKY_INTENTS or action.safety_level in {"HIGH", "CRITICAL"} for action in actions)
        safety_level = self._max_safety([action.safety_level for action in actions])
        duplicate_risk = self._duplicate_risk(actions, original_text=original_text, corrected_text=corrected_text, context=context)
        idempotent_hint = self._idempotent_hint(actions, context=context)

        return SmartAutomationPlanResult(
            original_text=original_text,
            corrected_text=corrected_text,
            corrections_applied=list(normalization.corrections_applied),
            domain=domain,
            mode=mode,
            semantic_actions=actions,
            semantic_plan=semantic_plan,
            action_plan=action_plan,
            missing_fields=missing_fields,
            follow_up_question=follow_up,
            requires_confirmation=requires_confirmation,
            safety_level=safety_level,
            dry_run=bool(dry_run),
            executable=False,
            execution_deferred=True,
            duplicate_risk=duplicate_risk,
            idempotent_hint=idempotent_hint,
            metadata={
                "normalization_reason": normalization.reason,
                "normalization_confidence": normalization.confidence,
                "suggested_correction": normalization.suggested_correction,
                "planner_phase": "dry_run_only",
            },
        )

    def classify_domain(self, text: str, context: AutomationContext | None = None) -> AutomationDomain:
        lowered = self._clean(text)
        if re.search(r"\b(message|tell|send|call|whatsapp)\b", lowered):
            return AutomationDomain.COMMUNICATION
        if re.search(r"\b(file|folder|desktop|documents|delete it|rename|move)\b", lowered):
            return AutomationDomain.FILE
        if re.search(r"\b(search|google|look up|chrome|edge|website|tab|go back|refresh)\b", lowered):
            return AutomationDomain.BROWSER
        if re.search(r"\b(notepad|note|grocery list|write|add bring|save it)\b", lowered):
            return AutomationDomain.NOTE_DOCUMENT
        if re.search(r"\b(window|switch|vs code|vscode)\b", lowered):
            return AutomationDomain.WINDOW_WORKSPACE
        if re.search(r"\b(stop|wait|continue|undo|try again)\b", lowered):
            return AutomationDomain.CONTROL_RECOVERY
        if re.search(r"\b(screenshot|looking at|screen)\b", lowered):
            return AutomationDomain.SCREENSHOT_VISION
        if re.search(r"\b(battery|shutdown|restart)\b", lowered):
            return AutomationDomain.SYSTEM
        if re.search(r"\b(latest|research|news)\b", lowered):
            return AutomationDomain.RESEARCH
        if context and context.current_document_context:
            return AutomationDomain.NOTE_DOCUMENT
        return AutomationDomain.VISIBLE_UI

    def classify_mode(self, text: str, context: AutomationContext | None = None) -> AutomationMode:
        lowered = self._clean(text)
        if re.search(r"\b(plan this|don't run|dont run|what will you do)\b", lowered):
            return AutomationMode.DRY_RUN
        if re.search(r"\b(try again|fix that|undo that)\b", lowered):
            return AutomationMode.RECOVERY
        if re.search(r"\b(what am i looking at|what window am i on|read this error)\b", lowered):
            return AutomationMode.OBSERVATION
        if re.search(r"\b(send it|send it now|delete it|click delete|submit the form|close this window|call .+)\b", lowered):
            return AutomationMode.CONFIRMED_EXECUTION
        if re.search(r"\b(draft|tell .+)\b", lowered):
            return AutomationMode.DRAFT
        if re.search(r"\b(open (?:chrome|edge).+search|open a new tab)\b", lowered):
            return AutomationMode.VISIBLE_BROWSER
        if re.search(r"\b(open notepad|in notepad|type .+ active window|select the address bar|clear the search box)\b", lowered):
            return AutomationMode.VISIBLE_UI
        if re.search(r"\b(latest|research|find .+news)\b", lowered):
            return AutomationMode.BACKGROUND_RESEARCH
        return AutomationMode.DIRECT_TOOL

    def extract_semantic_action(self, text: str, context: AutomationContext | None = None) -> list[SemanticAutomationAction]:
        cleaned = self._clean(text)
        handlers = (
            self._plan_dry_run_request,
            self._plan_control_request,
            self._plan_observation_request,
            self._plan_communication_request,
            self._plan_file_request,
            self._plan_note_request,
            self._plan_browser_request,
            self._plan_app_window_request,
            self._plan_system_request,
        )
        for handler in handlers:
            actions = handler(cleaned, text, context)
            if actions:
                return actions
        return []

    def build_dry_run_plan(self, action: SemanticAutomationAction | list[SemanticAutomationAction], context: AutomationContext | None = None) -> ActionPlan:
        actions = [action] if isinstance(action, SemanticAutomationAction) else list(action)
        steps: list[ActionStep] = []
        for action_index, semantic_action in enumerate(actions, start=1):
            for tool_action in self._tool_steps_for(semantic_action):
                step = ActionStep(
                    step_id=f"step{len(steps) + 1}",
                    tool_name=tool_action["tool_name"],
                    intent=tool_action["intent"],
                    action=tool_action["action"],
                    args=dict(tool_action.get("args") or {}),
                    safety_level=semantic_action.safety_level,
                    requires_confirmation=semantic_action.intent in self.RISKY_INTENTS,
                )
                decision = self.scenario_policy.evaluate(self._route_for_step(step))
                step.safety_level = self._max_safety([step.safety_level, decision.safety_level])
                step.requires_confirmation = bool(step.requires_confirmation or decision.requires_confirmation)
                step.requires_voice_permission = decision.requires_voice_permission
                steps.append(step)
        return ActionPlan(
            original_text="dry_run",
            steps=steps,
            is_multistep=len(steps) > 1,
            requires_confirmation=any(step.requires_confirmation for step in steps),
            requires_voice_permission=any(step.requires_voice_permission for step in steps),
        )

    def _plan_browser_request(self, cleaned: str, original: str, context: AutomationContext | None) -> list[SemanticAutomationAction]:
        new_tab = re.match(r"^open a new tab and search (?P<query>.+)$", cleaned)
        if new_tab:
            query = self._strip_filler(new_tab.group("query"))
            return [
                self._action(SemanticAutomationIntent.OPEN_NEW_TAB, AutomationDomain.BROWSER, AutomationMode.VISIBLE_BROWSER, preferred_tool="app_interaction", safety_level="LOW"),
                self._action(SemanticAutomationIntent.SEARCH_VISIBLE_BROWSER, AutomationDomain.BROWSER, AutomationMode.VISIBLE_BROWSER, query=query, preferred_tool="app_interaction"),
            ]

        visible = re.match(r"^open (?P<app>chrome|edge|google chrome|microsoft edge) and search(?: for)? (?P<query>.+)$", cleaned)
        if visible:
            return [
                self._action(
                    SemanticAutomationIntent.SEARCH_VISIBLE_BROWSER,
                    AutomationDomain.BROWSER,
                    AutomationMode.VISIBLE_BROWSER,
                    app=visible.group("app"),
                    query=self._strip_filler(visible.group("query")),
                    preferred_tool="app_interaction",
                    fallback_tool="browser",
                )
            ]

        search_this = re.match(r"^(?:search this|google this|look up this)(?: on google)?$", cleaned)
        if search_this:
            query = context.last_content if context else None
            return [
                self._action(
                    SemanticAutomationIntent.SEARCH_WEB,
                    AutomationDomain.BROWSER,
                    AutomationMode.DIRECT_TOOL,
                    query=query,
                    preferred_tool="browser",
                    missing_fields=[] if query else ["search_query"],
                )
            ]

        search = re.match(r"^(?:search|google|look up)(?: for)? (?P<query>.+?)(?: on google)?$", cleaned)
        if search:
            return [
                self._action(
                    SemanticAutomationIntent.SEARCH_WEB,
                    AutomationDomain.BROWSER,
                    AutomationMode.DIRECT_TOOL,
                    query=self._strip_filler(search.group("query")),
                    preferred_tool="browser",
                    fallback_tool="app_interaction",
                )
            ]

        replace = re.match(r"^(?:replace that|search this instead|replace the current search)(?: with|:)? (?P<query>.+)$", cleaned)
        if replace:
            missing = [] if context and context.last_browser_query else ["reference"]
            return [
                self._action(
                    SemanticAutomationIntent.REPLACE_ADDRESS_OR_SEARCH,
                    AutomationDomain.BROWSER,
                    AutomationMode.VISIBLE_BROWSER if context and context.active_app in {"chrome", "edge"} else AutomationMode.DIRECT_TOOL,
                    target=context.last_browser_query if context else None,
                    query=self._strip_filler(replace.group("query")),
                    preferred_tool="browser" if context and context.last_browser_query else "app_interaction",
                    missing_fields=missing,
                    requires_context=True,
                )
            ]

        if cleaned == "clear the search box":
            return [self._action(SemanticAutomationIntent.CLEAR_FIELD, AutomationDomain.BROWSER, AutomationMode.VISIBLE_UI, preferred_tool="app_interaction")]
        if cleaned == "go back":
            missing = [] if context and (context.last_browser or context.last_browser_query or context.active_app in {"chrome", "edge"}) else ["browser_context"]
            return [self._action(SemanticAutomationIntent.BROWSER_BACK, AutomationDomain.BROWSER, AutomationMode.VISIBLE_BROWSER, preferred_tool="app_interaction", missing_fields=missing)]
        if cleaned == "refresh this":
            missing = [] if context and (context.last_browser or context.last_opened_url or context.active_app in {"chrome", "edge"}) else ["browser_context"]
            return [self._action(SemanticAutomationIntent.REFRESH, AutomationDomain.BROWSER, AutomationMode.VISIBLE_BROWSER, preferred_tool="app_interaction", missing_fields=missing)]
        return []

    def _plan_file_request(self, cleaned: str, original: str, context: AutomationContext | None) -> list[SemanticAutomationAction]:
        save_content = re.match(
            r"^save (?P<content>.+?) as (?P<name>.+?)(?: on (?P<location>(?:my )?desktop|documents|downloads|home))?$",
            cleaned,
        )
        if save_content:
            location = self._normalize_location(save_content.group("location"))
            name = save_content.group("name")
            content = self._strip_filler(save_content.group("content"))
            return [
                self._action(
                    SemanticAutomationIntent.SAVE_CONTENT_AS_FILE,
                    AutomationDomain.FILE,
                    AutomationMode.DIRECT_TOOL,
                    target=name,
                    content=content,
                    file_path=self._compose_file_path(location, name, default_location="desktop"),
                    preferred_tool="file",
                )
            ]

        create_write = re.match(
            r"^(?:create|make) (?:a )?(?:text )?file(?: on (?P<location>(?:my )?desktop|documents|downloads|home))? (?:named|name|called) (?P<name>.+?) (?:and (?:write|put) (?P<content>.+?)(?: in it)?|with (?P<with_content>.+?) in it)$",
            cleaned,
        )
        if create_write:
            location = self._normalize_location(create_write.group("location"))
            path = self._compose_file_path(location, create_write.group("name"), default_location="desktop")
            content = self._strip_filler(create_write.group("content") or create_write.group("with_content"))
            return [
                self._action(SemanticAutomationIntent.CREATE_FILE, AutomationDomain.FILE, AutomationMode.DIRECT_TOOL, file_path=path, target=create_write.group("name"), preferred_tool="file"),
                self._action(SemanticAutomationIntent.WRITE_FILE, AutomationDomain.FILE, AutomationMode.DIRECT_TOOL, file_path=path, content=content, preferred_tool="file"),
            ]

        create = re.match(r"^(?:create|make) (?:a )?(?:text )?file(?: on (?P<location>(?:my )?desktop|documents|downloads|home))? (?:named|name|called) (?P<name>.+)$", cleaned)
        if create:
            location = self._normalize_location(create.group("location"))
            name = create.group("name")
            if re.search(r"\band\s+in\s+(?:that|the)\s+file\s+(?:add|write|append|put|insert)\b", name):
                return []
            return [
                self._action(
                    SemanticAutomationIntent.CREATE_FILE,
                    AutomationDomain.FILE,
                    AutomationMode.DIRECT_TOOL,
                    file_path=self._compose_file_path(location, name),
                    target=name,
                    preferred_tool="file",
                )
            ]

        followup = re.match(
            r"^(?:(?P<verb>put|write|add|append)\s+)(?P<content>.+?)(?:\s+(?:in|to)\s+(?P<target>it|the file|that file|.+))?$",
            cleaned,
        )
        if followup and self._looks_like_file_followup(followup, context):
            content = self._strip_filler(followup.group("content"))
            target_text = self._strip_filler(followup.group("target") or "it")
            path = self._resolve_file_followup_target(target_text, context)
            original_followup = re.match(
                r"^(?:(?:put|write|add|append)\s+)(?P<content>.+?)(?:\s+(?:in|to)\s+(?:it|the file|that file|.+))?$",
                original.strip(),
                flags=re.I,
            )
            if original_followup and content.lower() in {"world", "word"}:
                content = self._strip_filler(original_followup.group("content"))
            if content.lower() == "a word":
                content = "word"
            if content.lower() == "this" and context and context.last_content:
                content = context.last_content
            return [
                self._action(
                    SemanticAutomationIntent.APPEND_FILE,
                    AutomationDomain.FILE,
                    AutomationMode.DIRECT_TOOL,
                    file_path=path,
                    content=content,
                    preferred_tool="file",
                    requires_context=True,
                    missing_fields=[] if path else ["file"],
                )
            ]

        if cleaned in {"put this in a file", "save this in a file"}:
            content = context.last_content if context else None
            return [
                self._action(
                    SemanticAutomationIntent.SAVE_CONTENT_AS_FILE,
                    AutomationDomain.FILE,
                    AutomationMode.DIRECT_TOOL,
                    content=content,
                    preferred_tool="file",
                    requires_context=True,
                    missing_fields=[] if content else ["content"],
                )
            ]

        save_as = re.match(r"^save (?:this|it) as (?P<name>.+?)(?: on (?P<location>desktop|documents|downloads|home))?$", cleaned)
        if save_as:
            content = context.last_content if context else None
            missing = []
            if not content:
                missing.append("content")
            return [
                self._action(
                    SemanticAutomationIntent.SAVE_CONTENT_AS_FILE,
                    AutomationDomain.FILE,
                    AutomationMode.DIRECT_TOOL,
                    target=save_as.group("name"),
                    content=content,
                    file_path=self._compose_file_path(save_as.group("location"), save_as.group("name")) if save_as.group("location") else None,
                    preferred_tool="file",
                    requires_context=True,
                    missing_fields=missing,
                )
            ]

        add_file = re.match(r"^add this to (?:that file|it|the file)$", cleaned)
        if add_file:
            content = context.last_content if context else None
            path = context.resolve_reference("that file") if context else None
            missing = []
            if not content:
                missing.append("content")
            if not path:
                missing.append("file")
            return [self._action(SemanticAutomationIntent.APPEND_FILE, AutomationDomain.FILE, AutomationMode.DIRECT_TOOL, file_path=path, content=content, preferred_tool="file", missing_fields=missing, requires_context=True)]

        if cleaned == "open the file i just created":
            path = context.last_created_file_path if context else None
            return [self._action(SemanticAutomationIntent.OPEN_FILE, AutomationDomain.FILE, AutomationMode.DIRECT_TOOL, file_path=path, preferred_tool="file", requires_context=True, missing_fields=[] if path else ["file"])]

        if cleaned == "delete it":
            target = context.resolve_reference("it") if context else None
            return [
                self._action(
                    SemanticAutomationIntent.DELETE_FILE,
                    AutomationDomain.FILE,
                    AutomationMode.CONFIRMED_EXECUTION,
                    target=target,
                    file_path=target if isinstance(target, str) else None,
                    preferred_tool="file",
                    requires_context=True,
                    missing_fields=[] if target else ["file"],
                    safety_level="CRITICAL",
                )
            ]
        return []

    def _plan_note_request(self, cleaned: str, original: str, context: AutomationContext | None) -> list[SemanticAutomationAction]:
        visible_write = re.match(r"^(?:open notepad and type|write) (?P<content>.+?)(?: in notepad)?$", cleaned)
        if visible_write and ("notepad" in cleaned or cleaned.startswith("open notepad")):
            return [
                self._action(SemanticAutomationIntent.WRITE_NOTE, AutomationDomain.NOTE_DOCUMENT, AutomationMode.VISIBLE_UI, app="notepad", content=self._strip_filler(visible_write.group("content")), preferred_tool="app_interaction")
            ]
        if cleaned == "make a grocery list":
            return [self._action(SemanticAutomationIntent.WRITE_NOTE, AutomationDomain.NOTE_DOCUMENT, AutomationMode.VISIBLE_UI, content="Grocery list", preferred_tool="app_interaction", missing_fields=[])]
        add_note = re.match(r"^add (?P<content>.+)$", cleaned)
        if add_note and context and context.current_document_context:
            return [
                self._action(SemanticAutomationIntent.APPEND_TO_NOTE, AutomationDomain.NOTE_DOCUMENT, AutomationMode.VISIBLE_UI, content=self._strip_filler(add_note.group("content")), preferred_tool="app_interaction", requires_context=True)
            ]
        if cleaned.startswith("save it as "):
            return self._plan_file_request(cleaned, original, context)
        return []

    def _plan_app_window_request(self, cleaned: str, original: str, context: AutomationContext | None) -> list[SemanticAutomationAction]:
        open_app = re.match(r"^open (?P<app>chrome|notepad|calculator|spotify|whatsapp|vs code|vscode)$", cleaned)
        if open_app:
            app = open_app.group("app")
            return [self._action(SemanticAutomationIntent.OPEN_APP, AutomationDomain.APP_CONTROL, AutomationMode.DIRECT_TOOL, app=app, target=app, preferred_tool="app")]
        switch = re.match(r"^(?:switch to|focus) (?P<app>.+)$", cleaned)
        if switch:
            app = switch.group("app")
            return [self._action(SemanticAutomationIntent.FOCUS_APP, AutomationDomain.WINDOW_WORKSPACE, AutomationMode.VISIBLE_UI, app=app, target=app, preferred_tool="app")]
        if cleaned == "switch back":
            app = context.previous_active_app if context else None
            return [self._action(SemanticAutomationIntent.SWITCH_APP, AutomationDomain.WINDOW_WORKSPACE, AutomationMode.VISIBLE_UI, app=app, target=app, preferred_tool="app", requires_context=True, missing_fields=[] if app else ["previous_app"])]
        if cleaned == "close this window":
            target = context.active_window_title if context else None
            return [self._action(SemanticAutomationIntent.CLOSE_WINDOW, AutomationDomain.WINDOW_WORKSPACE, AutomationMode.CONFIRMED_EXECUTION, target=target, preferred_tool="window", requires_context=True, missing_fields=[] if target else ["window"], safety_level="HIGH")]
        return []

    def _plan_communication_request(self, cleaned: str, original: str, context: AutomationContext | None) -> list[SemanticAutomationAction]:
        send_direct = re.match(r"^(?:send (?:this|message)|send a message) to (?P<recipient>.+?)(?::| saying )\s*(?P<content>.+)$", cleaned)
        if send_direct:
            return [
                self._action(
                    SemanticAutomationIntent.SEND_MESSAGE_AFTER_CONFIRMATION,
                    AutomationDomain.COMMUNICATION,
                    AutomationMode.CONFIRMED_EXECUTION,
                    recipient=self._title_name(send_direct.group("recipient")),
                    target=self._title_name(send_direct.group("recipient")),
                    content=self._strip_filler(send_direct.group("content")),
                    preferred_tool="message",
                    safety_level="HIGH",
                )
            ]
        draft = re.match(r"^(?:draft a message to|tell) (?P<recipient>.+?) (?:saying )?(?P<content>.+)$", cleaned)
        if draft:
            return [
                self._action(
                    SemanticAutomationIntent.DRAFT_MESSAGE,
                    AutomationDomain.COMMUNICATION,
                    AutomationMode.DRAFT,
                    recipient=self._title_name(draft.group("recipient")),
                    content=self._strip_filler(draft.group("content")),
                    preferred_tool="message",
                    safety_level="LOW",
                )
            ]
        if cleaned in {"send it now", "send it"}:
            draft_context = context.current_message_draft if context else None
            return [
                self._action(
                    SemanticAutomationIntent.SEND_MESSAGE_AFTER_CONFIRMATION,
                    AutomationDomain.COMMUNICATION,
                    AutomationMode.CONFIRMED_EXECUTION,
                    recipient=(draft_context or {}).get("recipient") if isinstance(draft_context, dict) else None,
                    content=(draft_context or {}).get("content") if isinstance(draft_context, dict) else None,
                    target=(draft_context or {}).get("recipient") if isinstance(draft_context, dict) else None,
                    preferred_tool="message",
                    requires_context=True,
                    missing_fields=[] if draft_context else ["message_draft"],
                    safety_level="HIGH",
                )
            ]
        if cleaned in {"don't send it", "dont send it", "do not send it"}:
            return [self._action(SemanticAutomationIntent.CANCEL_PENDING_CONFIRMATION, AutomationDomain.COMMUNICATION, AutomationMode.CONFIRMED_EXECUTION, preferred_tool="message")]
        call = re.match(r"^call (?P<recipient>.+)$", cleaned)
        if call:
            return [self._action(SemanticAutomationIntent.CALL_CONTACT, AutomationDomain.COMMUNICATION, AutomationMode.CONFIRMED_EXECUTION, recipient=self._title_name(call.group("recipient")), preferred_tool="phone", safety_level="HIGH")]
        return []

    def _plan_control_request(self, cleaned: str, original: str, context: AutomationContext | None) -> list[SemanticAutomationAction]:
        if cleaned == "stop":
            return [self._action(SemanticAutomationIntent.STOP_CURRENT_ACTION, AutomationDomain.CONTROL_RECOVERY, AutomationMode.RECOVERY, preferred_tool="tts")]
        if cleaned == "wait":
            return [self._action(SemanticAutomationIntent.WAIT, AutomationDomain.CONTROL_RECOVERY, AutomationMode.RECOVERY)]
        if cleaned == "continue":
            return [self._action(SemanticAutomationIntent.CONTINUE_PENDING, AutomationDomain.CONTROL_RECOVERY, AutomationMode.RECOVERY, missing_fields=[] if context and context.current_pending_action else ["pending_action"])]
        if cleaned == "try again":
            return [self._action(SemanticAutomationIntent.RETRY_LAST_FAILED_SAFE, AutomationDomain.CONTROL_RECOVERY, AutomationMode.RECOVERY, requires_context=True, missing_fields=[] if context and context.last_failed_action else ["failed_action"])]
        if cleaned == "undo that":
            can_undo = bool(context and (context.last_typed_text or context.last_successful_action or context.current_document_context))
            return [self._action(SemanticAutomationIntent.UNDO_SAFE, AutomationDomain.CONTROL_RECOVERY, AutomationMode.RECOVERY, preferred_tool="app_interaction", requires_context=True, missing_fields=[] if can_undo else ["undo_context"])]
        if cleaned == "click delete":
            return [
                self._action(
                    SemanticAutomationIntent.CLICK_TEXT,
                    AutomationDomain.VISIBLE_UI,
                    AutomationMode.CONFIRMED_EXECUTION,
                    target="delete",
                    preferred_tool="app_interaction",
                    safety_level="HIGH",
                )
            ]
        coordinates = re.match(r"^click (?:coordinates?|at) (?P<x>-?\d+)[,\s]+(?P<y>-?\d+)$", cleaned)
        if coordinates:
            return [
                self._action(
                    SemanticAutomationIntent.CLICK_COORDINATES,
                    AutomationDomain.VISIBLE_UI,
                    AutomationMode.CONFIRMED_EXECUTION,
                    target=f"{coordinates.group('x')},{coordinates.group('y')}",
                    preferred_tool="app_interaction",
                    safety_level="HIGH",
                )
            ]
        if cleaned == "submit the form":
            return [
                self._action(
                    SemanticAutomationIntent.SUBMIT_FORM,
                    AutomationDomain.BROWSER,
                    AutomationMode.CONFIRMED_EXECUTION,
                    target="form",
                    preferred_tool="browser",
                    safety_level="CRITICAL",
                )
            ]
        if re.search(r"\b(?:submit|confirm|complete)\b.*\b(?:purchase|payment|checkout|order)\b", cleaned):
            return [
                self._action(
                    SemanticAutomationIntent.PAYMENT_OR_PURCHASE_SUBMIT,
                    AutomationDomain.BROWSER,
                    AutomationMode.CONFIRMED_EXECUTION,
                    target="payment",
                    preferred_tool="browser",
                    safety_level="CRITICAL",
                )
            ]
        if re.search(r"\b(?:submit|confirm|complete)\b.*\blogin\b|\blogin submit\b", cleaned):
            return [
                self._action(
                    SemanticAutomationIntent.LOGIN_SUBMIT,
                    AutomationDomain.BROWSER,
                    AutomationMode.CONFIRMED_EXECUTION,
                    target="login",
                    preferred_tool="browser",
                    safety_level="CRITICAL",
                )
            ]
        return []

    def _plan_observation_request(self, cleaned: str, original: str, context: AutomationContext | None) -> list[SemanticAutomationAction]:
        if cleaned in {"what window am i on", "what window am i in"}:
            return [self._action(SemanticAutomationIntent.READ_ACTIVE_WINDOW, AutomationDomain.WINDOW_WORKSPACE, AutomationMode.OBSERVATION, preferred_tool="app_interaction")]
        if cleaned in {"what am i looking at", "read this error"}:
            return [self._action(SemanticAutomationIntent.READ_SCREEN_OR_WINDOW, AutomationDomain.SCREENSHOT_VISION, AutomationMode.OBSERVATION, preferred_tool="vision")]
        return []

    def _plan_system_request(self, cleaned: str, original: str, context: AutomationContext | None) -> list[SemanticAutomationAction]:
        if cleaned == "take a screenshot":
            return [self._action(SemanticAutomationIntent.TAKE_SCREENSHOT, AutomationDomain.SCREENSHOT_VISION, AutomationMode.OBSERVATION, preferred_tool="screenshot")]
        if cleaned == "check battery":
            return [self._action(SemanticAutomationIntent.SYSTEM_STATUS, AutomationDomain.SYSTEM, AutomationMode.DIRECT_TOOL, target="battery", preferred_tool="system")]
        if re.match(r"^(?:shutdown|shut down|power off)(?:\s+(?:the\s+)?(?:computer|laptop|pc))?$", cleaned):
            return [self._action(SemanticAutomationIntent.SHUTDOWN_SYSTEM, AutomationDomain.SYSTEM, AutomationMode.CONFIRMED_EXECUTION, target="system", preferred_tool="system", safety_level="CRITICAL")]
        if re.match(r"^(?:restart|reboot)(?:\s+(?:the\s+)?(?:computer|laptop|pc))?$", cleaned):
            return [self._action(SemanticAutomationIntent.RESTART_SYSTEM, AutomationDomain.SYSTEM, AutomationMode.CONFIRMED_EXECUTION, target="system", preferred_tool="system", safety_level="CRITICAL")]
        terminal = re.match(r"^(?:run|execute)(?:\s+(?:terminal|shell|command))?\s+(?P<command>.+)$", cleaned)
        if terminal and re.search(r"\b(?:terminal|shell|command|powershell|cmd|python|npm|git)\b", cleaned):
            return [self._action(SemanticAutomationIntent.RUN_TERMINAL_COMMAND, AutomationDomain.DEVELOPER, AutomationMode.CONFIRMED_EXECUTION, target=terminal.group("command"), content=terminal.group("command"), preferred_tool="terminal", safety_level="CRITICAL")]
        if re.match(r"^(?:apply|make)\s+(?:the\s+)?code edit\b", cleaned):
            return [self._action(SemanticAutomationIntent.APPLY_CODE_EDIT, AutomationDomain.DEVELOPER, AutomationMode.CONFIRMED_EXECUTION, target="code edit", preferred_tool="code_edit", safety_level="CRITICAL")]
        return []

    def _plan_dry_run_request(self, cleaned: str, original: str, context: AutomationContext | None) -> list[SemanticAutomationAction]:
        if cleaned in {"plan this but don't run it", "plan this but dont run it"}:
            return [self._action(SemanticAutomationIntent.DRY_RUN_PLAN, AutomationDomain.CONTROL_RECOVERY, AutomationMode.DRY_RUN)]
        if cleaned in {"what will you do before doing it", "what will you do before you do it"}:
            return [self._action(SemanticAutomationIntent.EXPLAIN_PENDING_PLAN, AutomationDomain.CONTROL_RECOVERY, AutomationMode.DRY_RUN)]
        return []

    def _tool_steps_for(self, action: SemanticAutomationAction) -> list[dict[str, Any]]:
        args = {key: value for key, value in {
            "target": action.target,
            "text": action.content,
            "content": action.content,
            "app": action.app,
            "path": action.file_path,
            "query": action.query,
            "url": action.url,
            "recipient": action.recipient,
        }.items() if value is not None}
        mapping: dict[SemanticAutomationIntent, list[tuple[str, str, str]]] = {
            SemanticAutomationIntent.SEARCH_WEB: [("browser", "browser_search", "search")],
            SemanticAutomationIntent.SEARCH_VISIBLE_BROWSER: [("app", "app_open", "open"), ("app_interaction", "select_address_bar", "select_address_bar"), ("app_interaction", "replace_current_field", "replace_current_field"), ("app_interaction", "submit_current_field", "submit_current_field")],
            SemanticAutomationIntent.OPEN_NEW_TAB: [("app_interaction", "open_new_tab", "open_new_tab")],
            SemanticAutomationIntent.REPLACE_ADDRESS_OR_SEARCH: [("browser", "browser_search", "search")],
            SemanticAutomationIntent.CLEAR_FIELD: [("app_interaction", "clear_current_field", "clear_current_field")],
            SemanticAutomationIntent.BROWSER_BACK: [("app_interaction", "browser_back", "browser_back")],
            SemanticAutomationIntent.REFRESH: [("app_interaction", "refresh", "refresh")],
            SemanticAutomationIntent.CREATE_FILE: [("file", "file", "create_file")],
            SemanticAutomationIntent.WRITE_FILE: [("file", "file", "write_file")],
            SemanticAutomationIntent.APPEND_FILE: [("file", "file", "append_file")],
            SemanticAutomationIntent.SAVE_CONTENT_AS_FILE: [("file", "file", "write_file")],
            SemanticAutomationIntent.OPEN_FILE: [("file", "file", "open_file")],
            SemanticAutomationIntent.DELETE_FILE: [("file", "file", "delete_file")],
            SemanticAutomationIntent.WRITE_NOTE: [("app", "app_open", "open"), ("app_interaction", "type_into_active_field", "type_into_active_field")],
            SemanticAutomationIntent.APPEND_TO_NOTE: [("app_interaction", "append_text", "append_text")],
            SemanticAutomationIntent.OPEN_APP: [("app", "app_open", "open")],
            SemanticAutomationIntent.FOCUS_APP: [("app", "app_focus", "focus")],
            SemanticAutomationIntent.SWITCH_APP: [("app", "app_focus", "focus")],
            SemanticAutomationIntent.READ_ACTIVE_WINDOW: [("app_interaction", "read_window_title", "read_window_title")],
            SemanticAutomationIntent.CLOSE_WINDOW: [("window", "window_control", "close")],
            SemanticAutomationIntent.DRAFT_MESSAGE: [("message", "draft_message", "prepare_message")],
            SemanticAutomationIntent.SEND_MESSAGE_AFTER_CONFIRMATION: [("message", "send_message", "send_message")],
            SemanticAutomationIntent.CALL_CONTACT: [("phone", "phone", "call_contact")],
            SemanticAutomationIntent.STOP_CURRENT_ACTION: [("tts", "tts", "stop")],
            SemanticAutomationIntent.UNDO_SAFE: [("app_interaction", "undo", "undo")],
            SemanticAutomationIntent.TAKE_SCREENSHOT: [("screenshot", "screenshot", "capture")],
            SemanticAutomationIntent.SYSTEM_STATUS: [("system", "system", "safe_system_info")],
            SemanticAutomationIntent.CLICK_TEXT: [("app_interaction", "click_text", "click_text")],
            SemanticAutomationIntent.CLICK_COORDINATES: [("app_interaction", "click_coordinates", "click_coordinates")],
            SemanticAutomationIntent.SUBMIT_FORM: [("browser", "browser_form_input", "form_submit")],
            SemanticAutomationIntent.PAYMENT_OR_PURCHASE_SUBMIT: [("browser", "browser_form_input", "form_submit")],
            SemanticAutomationIntent.LOGIN_SUBMIT: [("browser", "browser_form_input", "form_submit")],
            SemanticAutomationIntent.RUN_TERMINAL_COMMAND: [("terminal", "terminal", "run_command")],
            SemanticAutomationIntent.APPLY_CODE_EDIT: [("code_edit", "code_edit", "apply_patch")],
            SemanticAutomationIntent.SHUTDOWN_SYSTEM: [("system", "system", "shutdown_system")],
            SemanticAutomationIntent.RESTART_SYSTEM: [("system", "system", "restart_system")],
        }
        return [{"tool_name": tool, "intent": intent, "action": step_action, "args": args} for tool, intent, step_action in mapping.get(action.intent, [])]

    def _action(
        self,
        intent: SemanticAutomationIntent,
        domain: AutomationDomain,
        mode: AutomationMode,
        *,
        target: str | None = None,
        content: str | None = None,
        app: str | None = None,
        file_path: str | None = None,
        query: str | None = None,
        url: str | None = None,
        recipient: str | None = None,
        requires_context: bool = False,
        missing_fields: list[str] | None = None,
        safety_level: str | None = None,
        preferred_tool: str | None = None,
        fallback_tool: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SemanticAutomationAction:
        level = safety_level or ("CRITICAL" if intent in self.CRITICAL_INTENTS else "HIGH" if intent in self.RISKY_INTENTS else "LOW")
        return SemanticAutomationAction(
            intent=intent,
            domain=domain,
            mode=mode,
            target=target,
            content=content,
            app=app,
            file_path=file_path,
            query=query,
            url=url,
            recipient=recipient,
            requires_context=requires_context,
            missing_fields=list(missing_fields or []),
            safety_level=level,
            preferred_tool=preferred_tool,
            fallback_tool=fallback_tool,
            verification_strategy="dry_run_only",
            metadata=dict(metadata or {}),
        )

    def _duplicate_risk(self, actions: list[SemanticAutomationAction], *, original_text: str, corrected_text: str, context: AutomationContext | None) -> bool:
        if context is None:
            return False
        for action in actions:
            mutating = action.intent.value not in {item.value for item in self.NON_MUTATING_INTENTS}
            fingerprint = context.create_fingerprint(
                original_user_text=original_text,
                corrected_text=corrected_text,
                semantic_action=action.intent.value,
                target=action.target or action.file_path or action.recipient or action.app,
                content=action.content,
                tool_plan={"intent": action.intent.value, "preferred_tool": action.preferred_tool},
                mutating=mutating,
            )
            if context.is_duplicate(fingerprint):
                return True
        return False

    @staticmethod
    def _idempotent_hint(actions: list[SemanticAutomationAction], context: AutomationContext | None) -> str | None:
        for action in actions:
            if action.intent == SemanticAutomationIntent.OPEN_APP:
                return "focus_existing_app_if_open"
        return None

    @staticmethod
    def _follow_up_for(missing_fields: list[str]) -> str | None:
        if not missing_fields:
            return None
        field = missing_fields[0]
        return {
            "content": "What should I write?",
            "file_name": "What should I name it?",
            "location": "Where should I save it?",
            "search_query": "What should I search?",
            "recipient": "Who should I send it to?",
            "message_draft": "Should I send it now?",
            "file": "Which file should I use?",
            "reference": "What should I replace?",
            "browser_context": "Which browser should I use?",
            "undo_context": "What should I undo?",
            "failed_action": "What should I try again?",
        }.get(field, f"What {field.replace('_', ' ')} should I use?")

    @staticmethod
    def _collect_missing_fields(actions: list[SemanticAutomationAction]) -> list[str]:
        fields: list[str] = []
        for action in actions:
            for field in action.missing_fields:
                if field not in fields:
                    fields.append(field)
        return fields

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
    def _max_safety(levels: list[str]) -> str:
        order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
        normalized = [str(level or "LOW").upper() for level in levels]
        return max(normalized or ["LOW"], key=lambda level: order.get(level, 0))

    @staticmethod
    def _clean(text: str) -> str:
        return re.sub(r"\s+", " ", str(text or "").strip().lower()).strip(" .!?")

    @staticmethod
    def _strip_filler(value: str) -> str:
        return re.sub(r"\s+", " ", str(value or "").strip()).strip(" .!?")

    @staticmethod
    def _title_name(value: str) -> str:
        return " ".join(part.capitalize() for part in re.sub(r"\s+", " ", str(value or "").strip()).split())

    @staticmethod
    def _compose_file_path(location: str | None, name: str | None, *, default_location: str | None = None) -> str | None:
        clean_name = re.sub(r"\s+", " ", str(name or "").strip()).strip(" .!?")
        if not clean_name:
            return None
        filename = clean_name if "." in clean_name else f"{clean_name}.txt"
        location_value = SmartAutomationPlanner._normalize_location(location) or SmartAutomationPlanner._normalize_location(default_location)
        if not location_value:
            return filename
        return f"{location_value}/{filename}"

    @staticmethod
    def _normalize_location(location: str | None) -> str | None:
        value = re.sub(r"\s+", " ", str(location or "").strip().lower()).strip(" .!?")
        if value.startswith("my "):
            value = value[3:]
        return value or None

    @staticmethod
    def _looks_like_file_followup(match: re.Match[str], context: AutomationContext | None) -> bool:
        target = str(match.group("target") or "").strip().lower()
        verb = str(match.group("verb") or "").strip().lower()
        if target in {"it", "the file", "that file"}:
            return True
        if target and context and (context.last_created_file_path or context.last_edited_file_path or context.last_file_path):
            return True
        return verb == "append" and bool(context and (context.last_created_file_path or context.last_edited_file_path or context.last_file_path))

    @staticmethod
    def _resolve_file_followup_target(target_text: str, context: AutomationContext | None) -> str | None:
        if context is None:
            return None
        target = re.sub(r"\s+", " ", str(target_text or "").strip().lower()).strip(" .!?")
        if target in {"", "it", "the file", "that file", "same file"}:
            value = context.last_created_file_path or context.last_edited_file_path or context.last_file_path
            return str(value) if isinstance(value, str) and value else None
        candidates = [context.last_created_file_path, context.last_edited_file_path, context.last_file_path]
        for candidate in candidates:
            if not candidate:
                continue
            stem = re.sub(r"[_-]+", " ", str(candidate).replace("\\", "/").rsplit("/", 1)[-1].rsplit(".", 1)[0].lower())
            if target == stem or target in stem:
                return str(candidate)
        return None
