from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from config import AUTOMATION_CONTEXT_ENABLED
from app.orchestrator.automation_context import AutomationContext, AutomationContextStore


@dataclass(slots=True)
class AutomationRequestContext:
    session_id: str | None
    turn_id: str | None
    command: str
    automation_context: AutomationContext | None
    payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


class AutomationContextBuilder:
    """Builds the small context object passed into canonical automation routing."""

    def __init__(self, store: AutomationContextStore | None = None, *, enabled: bool | None = None) -> None:
        self.store = store or AutomationContextStore()
        self.enabled = AUTOMATION_CONTEXT_ENABLED if enabled is None else bool(enabled)

    def get_context(self, session_id: str | None) -> AutomationContext | None:
        if not self.enabled:
            return None
        return self.store.get(session_id or "default")

    def build(self, command: str, *, session_id: str | None = None, turn_id: str | None = None) -> AutomationRequestContext:
        context = self.get_context(session_id)
        payload: dict[str, Any] = {"turn_id": turn_id} if turn_id else {}
        metadata: dict[str, Any] = {}
        if context is not None:
            payload["automation_context"] = context
            metadata["automation_context"] = context
            metadata["safe_request"] = {
                "session_id": session_id,
                "turn_id": turn_id,
                "current_subject": context.current_subject,
                "last_explicit_entity": context.last_explicit_entity,
                "last_browser_query": context.last_browser_query,
                "last_file_target": context.last_file_target,
                "last_created_file_path": context.last_created_file_path,
                "last_file_search_results": list(context.last_file_search_results),
                "last_folder_searched": context.last_folder_searched,
                "last_selected_file_path": context.last_selected_file_path,
                "last_contact_name": context.last_contact_name,
                "last_whatsapp_chat": context.last_whatsapp_chat,
                "last_email_recipient": context.last_email_recipient,
                "last_tool_domain": context.last_tool_domain,
                "last_tool_action": context.last_tool_action,
            }
        return AutomationRequestContext(
            session_id=session_id,
            turn_id=turn_id,
            command=str(command or ""),
            automation_context=context,
            payload=payload,
            metadata=metadata,
        )
