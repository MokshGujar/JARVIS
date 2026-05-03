from __future__ import annotations

import re
import time
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePath
from typing import TYPE_CHECKING, Any

from config import (
    AUTOMATION_CONTEXT_TTL_SECONDS,
    AUTOMATION_DRY_RUN_ENABLED,
    AUTOMATION_DUPLICATE_PROTECTION_ENABLED,
    SEMANTIC_PLANNER_ENABLED,
    SEMANTIC_SAFE_EXECUTION_ENABLED,
    SMART_AUTOMATION_ENABLED,
)
from app.orchestrator.action_plan import ActionPlan, ActionStep
from app.orchestrator.automation_context import NO_CONFIRMATIONS, YES_CONFIRMATIONS
from app.orchestrator.semantic_action_mapper import MUTATING_INTENTS, SemanticActionMapper
from app.orchestrator.semantic_automation import SemanticAutomationIntent

if TYPE_CHECKING:
    from app.orchestrator.automation_context import AutomationContext
    from app.orchestrator.smart_automation_planner import SmartAutomationPlanner
    from app.orchestrator.semantic_automation import SemanticAutomationAction

logger = logging.getLogger(__name__)

STAGED_CONFIRMATION_INTENTS = {
    SemanticAutomationIntent.DELETE_FILE,
    SemanticAutomationIntent.DRAFT_MESSAGE,
    SemanticAutomationIntent.SEND_MESSAGE_AFTER_CONFIRMATION,
    SemanticAutomationIntent.CALL_CONTACT,
    SemanticAutomationIntent.CLICK_TEXT,
    SemanticAutomationIntent.CLICK_COORDINATES,
    SemanticAutomationIntent.SUBMIT_FORM,
    SemanticAutomationIntent.PAYMENT_OR_PURCHASE_SUBMIT,
    SemanticAutomationIntent.LOGIN_SUBMIT,
    SemanticAutomationIntent.CLOSE_WINDOW,
    SemanticAutomationIntent.RUN_TERMINAL_COMMAND,
    SemanticAutomationIntent.APPLY_CODE_EDIT,
    SemanticAutomationIntent.SHUTDOWN_SYSTEM,
    SemanticAutomationIntent.RESTART_SYSTEM,
}
GENERIC_CONFIRMATION_REPLIES = {"yes", "y", "yes do it", "do it", "confirm", "go ahead", "proceed", "no", "n", "cancel", "cancel that", "stop", "never mind"}

@dataclass(slots=True)
class DryRunRequest:
    original_text: str
    plan_text: str
    trigger: str


def is_explicit_dry_run_request(text: str) -> bool:
    return _parse_dry_run_request(text) is not None


class SemanticPlannerAdapter:
    """Feature-flagged boundary for semantic planning.

    Phase 4B supports explicit dry-run/explain-plan requests only. It never
    returns an executable ActionPlan for normal live routing.
    """

    def __init__(
        self,
        *,
        smart_automation_enabled: bool | None = None,
        semantic_planner_enabled: bool | None = None,
        dry_run_enabled: bool | None = None,
        safe_execution_enabled: bool | None = None,
        duplicate_protection_enabled: bool | None = None,
        planner_factory: Callable[[], SmartAutomationPlanner] | None = None,
    ) -> None:
        self.smart_automation_enabled = SMART_AUTOMATION_ENABLED if smart_automation_enabled is None else bool(smart_automation_enabled)
        self.semantic_planner_enabled = SEMANTIC_PLANNER_ENABLED if semantic_planner_enabled is None else bool(semantic_planner_enabled)
        self.dry_run_enabled = AUTOMATION_DRY_RUN_ENABLED if dry_run_enabled is None else bool(dry_run_enabled)
        self.safe_execution_enabled = SEMANTIC_SAFE_EXECUTION_ENABLED if safe_execution_enabled is None else bool(safe_execution_enabled)
        self.duplicate_protection_enabled = (
            AUTOMATION_DUPLICATE_PROTECTION_ENABLED if duplicate_protection_enabled is None else bool(duplicate_protection_enabled)
        )
        self._planner_factory = planner_factory
        self._planner: SmartAutomationPlanner | None = None
        self.last_semantic_result: Any | None = None

    @property
    def enabled(self) -> bool:
        return self.smart_automation_enabled and self.semantic_planner_enabled

    def try_plan_action(self, text: str, context: AutomationContext | None = None) -> ActionPlan | None:
        return None

    def try_confirmation_response(
        self,
        text: str,
        *,
        context: AutomationContext | None = None,
        execute_confirmed_plan: Callable[[ActionPlan], dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        if context is None:
            return None
        reply = _confirmation_reply(text)
        pending = context.last_confirmation_request

        if pending is not None and pending.status == "pending":
            old_recipient = pending.recipient
            old_content = pending.content
            if context.update_pending_confirmation_from_text(text):
                updated = "message" if pending.content != old_content else "recipient" if pending.recipient != old_recipient else ""
                return _confirmation_updated_response(context.last_confirmation_request, updated=updated)
            if _is_ambiguous_target_change(reply, pending.action):
                context.clear_pending_action()
                question = "Which file should I delete?" if "delete" in pending.action else "Which target should I use?"
                return _response("semantic_confirmation_update_needed", question, requires_followup=True)
            resolution = context.resolve_confirmation_response(text)
            if resolution.status == "unknown":
                return None
            if resolution.status == "expired":
                return _response("semantic_confirmation_expired", "That confirmation expired. I did not run it.")
            if resolution.status == "cancelled":
                return _cancelled_response(resolution.confirmation)
            if resolution.status == "confirmed" and resolution.confirmation is not None:
                confirmation = resolution.confirmation
                if confirmation.action == "duplicate_repeat":
                    plan = _action_plan_from_dict(confirmation.tool_plan.get("plan"))
                    if plan is None or not _plan_is_safe_repeat(plan) or execute_confirmed_plan is None:
                        return _accepted_disabled_response(confirmation)
                    result = dict(execute_confirmed_plan(plan) or {})
                    result["duplicate_confirmation_accepted"] = True
                    result.setdefault("semantic_execution", True)
                    return result
                return _accepted_disabled_response(confirmation)
            return None

        if reply in GENERIC_CONFIRMATION_REPLIES:
            return _response("semantic_confirmation_none", "Nothing is waiting for confirmation.")
        return None

    def peek_live_claim(self, text: str, context: AutomationContext | None = None) -> Any | None:
        if is_explicit_dry_run_request(text) or not self.enabled or not self.safe_execution_enabled:
            return None
        planner = self._get_planner()
        result = planner.plan(text, context=context, dry_run=False)
        actions = list(getattr(result, "semantic_actions", []) or [])
        return result if actions else None

    def try_live_result(self, text: str, context: AutomationContext | None = None, scenario_policy: Any | None = None) -> ActionPlan | dict[str, Any] | None:
        if is_explicit_dry_run_request(text) or not self.enabled or not self.safe_execution_enabled:
            return None

        planner = self._get_planner()
        result = planner.plan(text, context=context, dry_run=False)
        self.last_semantic_result = result
        actions = list(getattr(result, "semantic_actions", []) or [])
        if not actions:
            logger.info("[SEMANTIC] fallback=legacy reason=no_semantic_claim")
            return None

        missing_fields = list(getattr(result, "missing_fields", []) or [])
        if missing_fields:
            logger.info("[SEMANTIC] blocked reason=missing_context")
            return self._missing_fields_response(result)

        confirmation_response = self._stage_confirmation_response(actions, result, context)
        if confirmation_response is not None:
            logger.info("[SEMANTIC] blocked reason=confirmation_required")
            return confirmation_response

        duplicate_response, fingerprints = self._duplicate_response(actions, result, context)
        if duplicate_response is not None:
            return duplicate_response

        mapper = SemanticActionMapper(scenario_policy=scenario_policy)
        mapped = mapper.map_actions(
            original_text=getattr(result, "original_text", text),
            corrected_text=getattr(result, "corrected_text", text),
            actions=actions,
            context=context,
            fingerprints=fingerprints,
        )
        if mapped.response is not None:
            reason = "unsupported"
            if str(mapped.response.get("action") or "") == "semantic_action_blocked":
                reason = "risky"
            logger.info("[SEMANTIC] blocked reason=%s", reason)
            return mapped.response
        context_label = _context_label(actions[0], context)
        logger.info("[SEMANTIC] claimed=true intent=%s context=%s", actions[0].intent.value, context_label)
        return mapped.plan

    def try_dry_run_response(self, text: str, context: AutomationContext | None = None) -> dict[str, Any] | None:
        request = _parse_dry_run_request(text)
        if request is None:
            return None
        if not self.enabled or not self.dry_run_enabled:
            return self._unavailable_response(request)

        if not request.plan_text:
            return self._missing_plan_response(request)

        planner = self._get_planner()
        result = planner.plan(request.plan_text, context=context, dry_run=True)
        self.last_semantic_result = result
        return self._format_dry_run_response(request, result)

    def _get_planner(self) -> SmartAutomationPlanner:
        if self._planner is None:
            if self._planner_factory is not None:
                self._planner = self._planner_factory()
            else:
                from app.orchestrator.smart_automation_planner import SmartAutomationPlanner

                self._planner = SmartAutomationPlanner()
        return self._planner

    def _missing_fields_response(self, result: Any) -> dict[str, Any]:
        question = getattr(result, "follow_up_question", None) or self._missing_context_message(list(getattr(result, "missing_fields", []) or []))
        missing_fields = list(getattr(result, "missing_fields", []) or [])
        return {
            "success": False,
            "action": "semantic_followup_required",
            "message": question,
            "display_text": question,
            "spoken_text": question,
            "requires_followup": True,
            "missing_fields": missing_fields,
            "follow_up_question": question,
            "semantic_execution": True,
            "executable": False,
        }

    def _duplicate_response(self, actions: list[SemanticAutomationAction], result: Any, context: AutomationContext | None) -> tuple[dict[str, Any] | None, list[Any]]:
        if not self.duplicate_protection_enabled or context is None:
            return None, []
        fingerprints: list[Any] = []
        for action in actions:
            mutating = action.intent in MUTATING_INTENTS
            fingerprint = context.create_fingerprint(
                original_user_text=getattr(result, "original_text", ""),
                corrected_text=getattr(result, "corrected_text", None),
                semantic_action=action.intent.value,
                target=action.target or action.file_path or action.recipient or action.app,
                content=action.content,
                tool_plan={"intent": action.intent.value, "preferred_tool": action.preferred_tool},
                mutating=mutating,
            )
            if context.is_duplicate(fingerprint):
                mapper = SemanticActionMapper()
                mapped = mapper.map_actions(
                    original_text=getattr(result, "original_text", ""),
                    corrected_text=getattr(result, "corrected_text", ""),
                    actions=actions,
                    context=context,
                    fingerprints=[fingerprint],
                )
                if mapped.plan is None:
                    return mapped.response, []
                message = "This looks like the same action again. Should I repeat it?"
                context.set_pending_confirmation(
                    semantic_action=action.intent.value,
                    action="duplicate_repeat",
                    target=action.target or action.file_path or action.recipient or action.app,
                    content=action.content,
                    recipient=action.recipient,
                    tool_plan={
                        "kind": "duplicate_repeat",
                        "plan": mapped.plan.as_dict(),
                        "fingerprint": fingerprint.as_dict(),
                    },
                    safety_level=str(action.safety_level or "LOW").upper(),
                    requires_voice_permission=False,
                )
                return {
                    "success": False,
                    "action": "duplicate_semantic_action",
                    "message": message,
                    "display_text": message,
                    "spoken_text": message,
                    "requires_followup": True,
                    "semantic_execution": True,
                    "executable": False,
                    "duplicate_risk": True,
                }, []
            fingerprints.append(fingerprint)
        return None, fingerprints

    def _stage_confirmation_response(self, actions: list[SemanticAutomationAction], result: Any, context: AutomationContext | None) -> dict[str, Any] | None:
        if context is None:
            return None
        risky = [
            action
            for action in actions
            if action.intent in STAGED_CONFIRMATION_INTENTS or str(action.safety_level or "").upper() in {"HIGH", "CRITICAL"}
        ]
        if not risky:
            return None
        action = risky[0]
        action_plan = getattr(result, "action_plan", None)
        requires_voice = bool(
            getattr(action_plan, "requires_voice_permission", False)
            or any(getattr(step, "requires_voice_permission", False) for step in getattr(action_plan, "steps", []) or [])
        )
        if action.intent == SemanticAutomationIntent.DRAFT_MESSAGE:
            semantic_action = SemanticAutomationIntent.SEND_MESSAGE_AFTER_CONFIRMATION.value
            pending_action = "send_message"
            context.current_message_draft = {"recipient": action.recipient, "content": context.redact_sensitive_text(action.content)}
        else:
            semantic_action = action.intent.value
            pending_action = _pending_action_name(action)
        confirmation = context.set_pending_confirmation(
            semantic_action=semantic_action,
            action=pending_action,
            target=action.target or action.file_path or action.recipient or action.app,
            content=action.content,
            recipient=action.recipient,
            tool_plan={
                "kind": "risky_disabled",
                "result": result.as_dict() if hasattr(result, "as_dict") else {},
                "plan": action_plan.as_dict() if action_plan is not None else None,
                "semantic_actions": [item.as_dict() for item in actions],
            },
            safety_level=str(action.safety_level or "HIGH").upper(),
            requires_voice_permission=requires_voice,
        )
        message = _confirmation_prompt(action)
        return {
            "success": False,
            "action": "semantic_confirmation_required",
            "message": message,
            "display_text": message,
            "spoken_text": message,
            "requires_confirmation": True,
            "requires_followup": True,
            "semantic_execution": True,
            "executable": False,
            "safety_level": confirmation.safety_level,
            "requires_voice_permission": requires_voice,
        }

    def _unavailable_response(self, request: DryRunRequest) -> dict[str, Any]:
        message = "Semantic dry-run planning is unavailable right now. No actions were run."
        return {
            "success": False,
            "action": "semantic_dry_run_unavailable",
            "message": message,
            "display_text": message,
            "spoken_text": message,
            "dry_run": True,
            "execution_deferred": True,
            "executable": False,
            "requires_followup": False,
            "original_text": request.original_text,
        }

    def _missing_plan_response(self, request: DryRunRequest) -> dict[str, Any]:
        message = "I need to know what you want me to plan. No actions were run."
        return {
            "success": False,
            "action": "semantic_dry_run",
            "message": message,
            "display_text": message,
            "spoken_text": message,
            "dry_run": True,
            "execution_deferred": True,
            "executable": False,
            "requires_followup": True,
            "missing_fields": ["automation_request"],
            "follow_up_question": "What should I plan?",
            "original_text": request.original_text,
            "planned_text": request.plan_text,
        }

    def _format_dry_run_response(self, request: DryRunRequest, result: Any) -> dict[str, Any]:
        actions = list(getattr(result, "semantic_actions", []) or [])
        action_plan = getattr(result, "action_plan", None)
        missing_fields = list(getattr(result, "missing_fields", []) or [])
        requires_confirmation = bool(getattr(result, "requires_confirmation", False))
        safety_level = str(getattr(result, "safety_level", "LOW") or "LOW")

        if missing_fields:
            display_text = self._missing_context_message(missing_fields)
        else:
            steps = self._describe_actions(actions, action_plan)
            if requires_confirmation and len(steps) == 1:
                display_text = f"I would need your confirmation before {steps[0][0].lower() + steps[0][1:]}"
            elif steps:
                display_text = "I would:\n" + "\n".join(f"{index}. {step}" for index, step in enumerate(steps, start=1))
                if requires_confirmation:
                    display_text += "\nConfirmation would be required before running this."
            elif requires_confirmation:
                display_text = "I would ask for confirmation before running that action."
            else:
                display_text = "I can explain that plan, but I need a more specific automation request."

        display_text = f"{display_text.rstrip()}\n\nNo actions were run."
        spoken_text = self._short_spoken(display_text)
        pending_plan = {
            "dry_run": True,
            "expires_at": time.time() + AUTOMATION_CONTEXT_TTL_SECONDS,
            "semantic_actions": [action.as_dict() for action in actions],
            "user_text": request.original_text,
            "plan_summary": display_text,
            "executable": False,
        }
        return {
            "success": not bool(missing_fields),
            "action": "semantic_dry_run",
            "message": display_text,
            "display_text": display_text,
            "spoken_text": spoken_text,
            "dry_run": True,
            "execution_deferred": True,
            "executable": False,
            "requires_confirmation": requires_confirmation,
            "safety_level": safety_level,
            "missing_fields": missing_fields,
            "follow_up_question": getattr(result, "follow_up_question", None),
            "semantic_actions": [action.as_dict() for action in actions],
            "semantic_plan": result.semantic_plan.as_dict() if getattr(result, "semantic_plan", None) else None,
            "plan": action_plan.as_dict() if action_plan is not None else None,
            "pending_dry_run_plan": pending_plan,
            "original_text": request.original_text,
            "planned_text": request.plan_text,
        }

    def _missing_context_message(self, missing_fields: list[str]) -> str:
        field = missing_fields[0]
        return {
            "message_draft": "I need to know which message you mean first.",
            "file": "Which file should I use?",
            "content": "I need to know what content you mean first.",
            "search_query": "I need to know what to search first.",
            "reference": "I need to know what you want to replace first.",
            "browser_context": "I need to know which browser you mean first.",
        }.get(field, f"I need to know which {field.replace('_', ' ')} you mean first.")

    def _describe_actions(self, actions: list[SemanticAutomationAction], action_plan: ActionPlan | None) -> list[str]:
        from app.orchestrator.semantic_automation import SemanticAutomationIntent

        if len(actions) == 1 and actions[0].intent == SemanticAutomationIntent.SEARCH_VISIBLE_BROWSER:
            action = actions[0]
            query = action.query or "the search"
            app = _title(action.app or "browser")
            return [
                f"Open or focus {app}.",
                "Select the address or search bar.",
                f"Type {query}.",
                "Submit the search.",
            ]

        steps: list[str] = []
        for action in actions:
            if action.intent == SemanticAutomationIntent.OPEN_APP:
                steps.append(f"Open or focus {_title(action.app or action.target or 'the app')}.")
            elif action.intent == SemanticAutomationIntent.FOCUS_APP:
                steps.append(f"Focus {_title(action.app or action.target or 'the app')}.")
            elif action.intent == SemanticAutomationIntent.SEARCH_WEB:
                steps.append(f"Search the web for {action.query}.")
            elif action.intent == SemanticAutomationIntent.CREATE_FILE:
                steps.append(f"Create {_file_label(action.file_path or action.target)}{_location_suffix(action.file_path)}.")
            elif action.intent == SemanticAutomationIntent.WRITE_FILE:
                steps.append(f"Write {action.content or 'the content'} into it.")
            elif action.intent == SemanticAutomationIntent.APPEND_FILE:
                steps.append(f"Add {action.content or 'the content'} to {_file_label(action.file_path or action.target)}.")
            elif action.intent == SemanticAutomationIntent.SAVE_CONTENT_AS_FILE:
                steps.append(f"Save the content as {_file_label(action.file_path or action.target)}.")
            elif action.intent == SemanticAutomationIntent.DELETE_FILE:
                steps.append(f"deleting {_file_label(action.file_path or action.target or 'that file')}.")
            elif action.intent == SemanticAutomationIntent.DRAFT_MESSAGE:
                steps.append(f"Prepare a message to {action.recipient or 'the recipient'}.")
            elif action.intent == SemanticAutomationIntent.SEND_MESSAGE_AFTER_CONFIRMATION:
                steps.append("ask for confirmation, then send the prepared message.")
            elif action.intent == SemanticAutomationIntent.WRITE_NOTE:
                steps.append(f"Open or focus {_title(action.app or 'the note app')} and type {action.content or 'the text'}.")
            elif action.intent == SemanticAutomationIntent.APPEND_TO_NOTE:
                steps.append(f"Add {action.content or 'the text'} to the current note.")

        if _has_intent(actions, SemanticAutomationIntent.CREATE_FILE):
            steps.append("Verify the file was created.")
        if not steps and action_plan is not None:
            steps = [_fallback_step_label(step.action, step.args) for step in action_plan.steps]
        return [step for step in steps if step]

    @staticmethod
    def _short_spoken(display_text: str) -> str:
        text = re.sub(r"\s+", " ", display_text).strip()
        return text if len(text) <= 180 else f"{text[:177].rstrip()}..."


def _parse_dry_run_request(text: str) -> DryRunRequest | None:
    original = str(text or "").strip()
    if not original:
        return None
    cleaned = re.sub(r"\s+", " ", original).strip(" \t\r\n")
    candidate = cleaned.rstrip("?.!")
    patterns: tuple[tuple[str, re.Pattern[str]], ...] = (
        ("plan_colon", re.compile(r"^plan\s*:\s*(?P<subject>.+)$", re.I)),
        ("dry_run_colon", re.compile(r"^dry\s+run\s*:\s*(?P<subject>.+)$", re.I)),
        ("dry_run", re.compile(r"^dry\s+run(?:\s+this)?(?:\s+(?P<subject>.+))?$", re.I)),
        ("plan_no_run", re.compile(r"^plan(?:\s+(?P<subject>.+?))?\s+but\s+don'?t\s+run\s+it$", re.I)),
        ("what_before", re.compile(r"^what\s+will\s+you\s+do\s+before\s+(?P<subject>.+)$", re.I)),
        ("tell_before", re.compile(r"^tell\s+me\s+what\s+you\s+would\s+do\s+before\s+(?P<subject>.+)$", re.I)),
        ("steps_take", re.compile(r"^what\s+steps\s+would\s+you\s+take\s+to\s+(?P<subject>.+)$", re.I)),
        ("explain_plan", re.compile(r"^explain\s+the\s+automation\s+plan(?:\s+for\s+(?P<subject>.+))?$", re.I)),
        ("show_plan", re.compile(r"^show\s+me\s+the\s+plan\s+for\s+(?P<subject>.+)$", re.I)),
    )
    for trigger, pattern in patterns:
        match = pattern.match(candidate)
        if match:
            subject = match.groupdict().get("subject") or ""
            return DryRunRequest(original_text=original, plan_text=_normalize_plan_subject(subject), trigger=trigger)
    return None


def _normalize_plan_subject(subject: str) -> str:
    text = re.sub(r"\s+", " ", str(subject or "").strip()).strip(" .?!:")
    if not text or text == "this":
        return ""
    replacements = (
        (r"^doing it$", ""),
        (r"^opening\b", "open"),
        (r"^creating\b", "create"),
        (r"^saving\b", "save"),
        (r"^sending\b", "send"),
        (r"^deleting\s+(?:that\s+file|the\s+file|it)$", "delete it"),
        (r"^sending\s+it$", "send it"),
        (r"\band\s+searching\b", "and search"),
        (r"\band\s+creating\b", "and create"),
        (r"\band\s+saving\b", "and save"),
    )
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text, flags=re.I)
    return text.strip()


def _title(value: str) -> str:
    return " ".join(part.capitalize() for part in re.sub(r"\s+", " ", str(value or "").strip()).split())


def _file_label(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "the file"
    return PurePath(text).name or text


def _location_suffix(value: Any) -> str:
    text = str(value or "").strip()
    if "/" not in text and "\\" not in text:
        return ""
    parent = PurePath(text).parent.name
    return f" on your {_title(parent)}" if parent else ""


def _has_intent(actions: list[SemanticAutomationAction], intent: Any) -> bool:
    return any(action.intent == intent for action in actions)


def _context_label(action: SemanticAutomationAction, context: AutomationContext | None) -> str:
    if action.file_path and context and action.file_path == context.last_created_file_path:
        return "last_created_file_path"
    if action.file_path and context and action.file_path == context.last_edited_file_path:
        return "last_edited_file_path"
    if action.file_path:
        return "file_path"
    if action.requires_context:
        return "missing" if action.missing_fields else "context"
    return "none"


def _fallback_step_label(action: str, args: dict[str, Any]) -> str:
    labels = {
        "open": f"Open or focus {_title(str(args.get('app') or args.get('target') or 'the app'))}.",
        "search": f"Search for {args.get('query') or 'the query'}.",
        "select_address_bar": "Select the address or search bar.",
        "replace_current_field": f"Type {args.get('query') or args.get('text') or args.get('content') or 'the text'}.",
        "submit_current_field": "Submit the current field.",
        "create_file": f"Create {_file_label(args.get('path') or args.get('filename') or args.get('name'))}.",
        "write_file": f"Write {args.get('content') or 'the content'} into it.",
    }
    return labels.get(str(action or ""), f"Prepare the {str(action or 'automation')} step.")


def _confirmation_reply(text: str) -> str:
    reply = re.sub(r"\s+", " ", str(text or "").strip().lower()).strip(" .!?")
    reply = reply.replace("’", "'")
    if reply.startswith("jarvis "):
        reply = reply[7:].strip()
    return reply


def _is_ambiguous_target_change(reply: str, action: str) -> bool:
    return bool(re.match(r"^no,?\s+(?:delete|send|close|run)\s+(?:the\s+)?other\s+(?:one|file|message|window|command)?$", reply)) or (
        "other one" in reply and any(word in action for word in ("delete", "send", "close", "run"))
    )


def _response(action: str, message: str, *, requires_followup: bool = False, **extra: Any) -> dict[str, Any]:
    payload = {
        "success": False,
        "action": action,
        "message": message,
        "display_text": message,
        "spoken_text": message,
        "semantic_execution": True,
        "executable": False,
    }
    if requires_followup:
        payload["requires_followup"] = True
    payload.update(extra)
    return payload


def _confirmation_updated_response(confirmation: Any | None, *, updated: str = "") -> dict[str, Any]:
    if confirmation is None:
        return _response("semantic_confirmation_updated", "Updated. Should I continue?", requires_followup=True)
    if confirmation.action == "send_message":
        if updated == "message":
            message = "I changed the message. Should I send it?"
        elif confirmation.recipient:
            message = f"I changed the recipient to {confirmation.recipient}. Should I send it?"
        else:
            message = "I changed the message. Should I send it?"
        return _response("semantic_confirmation_updated", message, requires_followup=True)
    label = _target_label(confirmation.target)
    return _response("semantic_confirmation_updated", f"I updated that to {label}. Should I continue?", requires_followup=True)


def _cancelled_response(confirmation: Any | None) -> dict[str, Any]:
    action = str(getattr(confirmation, "action", "") or "")
    if "send" in action:
        return _response("semantic_confirmation_cancelled", "Cancelled. I did not send it.")
    if "delete" in action:
        return _response("semantic_confirmation_cancelled", "Cancelled. I did not delete it.")
    if "duplicate" in action:
        return _response("duplicate_confirmation_cancelled", "Cancelled. I did not repeat it.")
    return _response("semantic_confirmation_cancelled", "Cancelled. I did not run it.")


def _accepted_disabled_response(confirmation: Any) -> dict[str, Any]:
    action = str(getattr(confirmation, "action", "") or "")
    semantic_action = str(getattr(confirmation, "semantic_action", "") or "")
    if "send" in action or "SEND_MESSAGE" in semantic_action:
        message = "I have confirmation, but actual sending is not enabled yet."
    elif "delete" in action or "DELETE_FILE" in semantic_action:
        message = "I have confirmation, but deleting files is not enabled in this phase."
    elif "call" in action or "CALL" in semantic_action:
        message = "I have confirmation, but actual calling is not enabled yet."
    elif "terminal" in action or "RUN_TERMINAL" in semantic_action:
        message = "I can prepare this, but I can't run terminal commands yet."
    elif "code" in action or "CODE_EDIT" in semantic_action:
        message = "I have confirmation, but applying code edits is not enabled in this phase."
    elif "submit" in action or "SUBMIT" in semantic_action or "PAYMENT" in semantic_action or "LOGIN" in semantic_action:
        message = "I have confirmation, but submitting forms is not enabled in this phase."
    elif "click" in action or "CLICK" in semantic_action:
        message = "I have confirmation, but clicking there is not enabled in this phase."
    elif "shutdown" in action or "restart" in action or "SHUTDOWN" in semantic_action or "RESTART" in semantic_action:
        message = "I have confirmation, but power actions are not enabled in this phase."
    else:
        message = "I have confirmation, but this action is not enabled yet."
    return _response("semantic_confirmation_accepted_disabled", message)


def _pending_action_name(action: Any) -> str:
    intent = getattr(action, "intent", None)
    if intent == SemanticAutomationIntent.DELETE_FILE:
        return "delete_file"
    if intent == SemanticAutomationIntent.SEND_MESSAGE_AFTER_CONFIRMATION:
        return "send_message"
    if intent == SemanticAutomationIntent.CALL_CONTACT:
        return "call_contact"
    if intent == SemanticAutomationIntent.CLOSE_WINDOW:
        return "close_window"
    if intent in {SemanticAutomationIntent.SUBMIT_FORM, SemanticAutomationIntent.PAYMENT_OR_PURCHASE_SUBMIT, SemanticAutomationIntent.LOGIN_SUBMIT}:
        return "submit_form"
    if intent in {SemanticAutomationIntent.CLICK_TEXT, SemanticAutomationIntent.CLICK_COORDINATES}:
        return "click"
    if intent == SemanticAutomationIntent.RUN_TERMINAL_COMMAND:
        return "terminal_run"
    if intent == SemanticAutomationIntent.APPLY_CODE_EDIT:
        return "code_edit_apply"
    if intent == SemanticAutomationIntent.SHUTDOWN_SYSTEM:
        return "shutdown_system"
    if intent == SemanticAutomationIntent.RESTART_SYSTEM:
        return "restart_system"
    return str(getattr(intent, "value", intent) or "semantic_action").lower()


def _confirmation_prompt(action: Any) -> str:
    intent = getattr(action, "intent", None)
    target = _target_label(getattr(action, "file_path", None) or getattr(action, "target", None) or getattr(action, "recipient", None))
    if intent == SemanticAutomationIntent.DELETE_FILE:
        return f"I need confirmation before deleting {target}. Should I delete it?"
    if intent in {SemanticAutomationIntent.DRAFT_MESSAGE, SemanticAutomationIntent.SEND_MESSAGE_AFTER_CONFIRMATION}:
        recipient = _target_label(getattr(action, "recipient", None) or "the recipient")
        return f"I drafted the message to {recipient}. Should I send it?"
    if intent == SemanticAutomationIntent.CALL_CONTACT:
        return f"I need confirmation before calling {target}."
    if intent == SemanticAutomationIntent.CLOSE_WINDOW:
        return "I need confirmation before closing this window."
    if intent == SemanticAutomationIntent.RUN_TERMINAL_COMMAND:
        return "I need confirmation before running that command."
    if intent == SemanticAutomationIntent.APPLY_CODE_EDIT:
        return "I need confirmation before applying that code edit."
    if intent in {SemanticAutomationIntent.SUBMIT_FORM, SemanticAutomationIntent.PAYMENT_OR_PURCHASE_SUBMIT, SemanticAutomationIntent.LOGIN_SUBMIT}:
        return "I need confirmation before submitting that."
    if intent in {SemanticAutomationIntent.CLICK_TEXT, SemanticAutomationIntent.CLICK_COORDINATES}:
        return "I need confirmation before clicking that."
    if intent in {SemanticAutomationIntent.SHUTDOWN_SYSTEM, SemanticAutomationIntent.RESTART_SYSTEM}:
        return "I need confirmation before changing power state."
    return "I need confirmation before doing that."


def _target_label(value: Any) -> str:
    if value is None:
        return "that"
    text = str(value).strip()
    if not text:
        return "that"
    if "\\" in text or "/" in text:
        return _file_label(text)
    return text


def _action_plan_from_dict(value: Any) -> ActionPlan | None:
    if not isinstance(value, dict):
        return None
    steps: list[ActionStep] = []
    for item in value.get("steps") or []:
        if not isinstance(item, dict):
            continue
        steps.append(
            ActionStep(
                step_id=str(item.get("step_id") or f"step{len(steps) + 1}"),
                tool_name=str(item.get("tool_name") or ""),
                intent=str(item.get("intent") or ""),
                action=str(item.get("action") or ""),
                args=dict(item.get("args") or {}),
                depends_on=list(item.get("depends_on") or []),
                safety_level=str(item.get("safety_level") or "LOW"),
                requires_confirmation=bool(item.get("requires_confirmation")),
                requires_face_step_up=bool(item.get("requires_face_step_up")),
                requires_voice_permission=bool(item.get("requires_voice_permission")),
                status=str(item.get("status") or "pending"),
            )
        )
    if not steps:
        return None
    return ActionPlan(
        original_text=str(value.get("original_text") or "confirmed duplicate"),
        steps=steps,
        is_multistep=bool(value.get("is_multistep", True)),
        requires_confirmation=bool(value.get("requires_confirmation")),
        requires_face_step_up=bool(value.get("requires_face_step_up")),
        requires_voice_permission=bool(value.get("requires_voice_permission")),
        metadata=dict(value.get("metadata") or {}),
    )


def _plan_is_safe_repeat(plan: ActionPlan) -> bool:
    blocked_actions = {
        "delete_file",
        "send_message",
        "call_contact",
        "form_submit",
        "run_command",
        "apply_patch",
        "click_coordinates",
        "shutdown_system",
        "restart_system",
    }
    for step in plan.steps:
        if str(step.safety_level or "LOW").upper() not in {"LOW", "MEDIUM"}:
            return False
        if step.requires_confirmation or step.requires_face_step_up or step.requires_voice_permission:
            return False
        if step.action in blocked_actions:
            return False
    return True
