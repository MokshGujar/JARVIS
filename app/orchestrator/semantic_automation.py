from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class _StringEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class AutomationDomain(_StringEnum):
    APP_CONTROL = "app_control"
    VISIBLE_UI = "visible_ui"
    FILE = "file"
    BROWSER = "browser"
    NOTE_DOCUMENT = "note_document"
    CLIPBOARD = "clipboard"
    COMMUNICATION = "communication"
    REMINDER = "reminder"
    SYSTEM = "system"
    MEDIA = "media"
    RESEARCH = "research"
    DEVELOPER = "developer"
    WINDOW_WORKSPACE = "window_workspace"
    SCREENSHOT_VISION = "screenshot_vision"
    MULTI_APP_WORKFLOW = "multi_app_workflow"
    CONTROL_RECOVERY = "control_recovery"


class AutomationMode(_StringEnum):
    DIRECT_TOOL = "direct_tool"
    VISIBLE_UI = "visible_ui"
    VISIBLE_BROWSER = "visible_browser"
    BACKGROUND_RESEARCH = "background_research"
    DRAFT = "draft"
    CONFIRMED_EXECUTION = "confirmed_execution"
    OBSERVATION = "observation"
    RECOVERY = "recovery"
    DRY_RUN = "dry_run"


class SemanticAutomationIntent(_StringEnum):
    OPEN_APP = "OPEN_APP"
    FOCUS_APP = "FOCUS_APP"
    SWITCH_APP = "SWITCH_APP"
    READ_ACTIVE_WINDOW = "READ_ACTIVE_WINDOW"
    WRITE_NOTE = "WRITE_NOTE"
    APPEND_TO_NOTE = "APPEND_TO_NOTE"
    CREATE_FILE = "CREATE_FILE"
    WRITE_FILE = "WRITE_FILE"
    APPEND_FILE = "APPEND_FILE"
    SAVE_CONTENT = "SAVE_CONTENT"
    SAVE_CONTENT_AS_FILE = "SAVE_CONTENT_AS_FILE"
    SEARCH_WEB = "SEARCH_WEB"
    SEARCH_VISIBLE_BROWSER = "SEARCH_VISIBLE_BROWSER"
    OPEN_WEBSITE = "OPEN_WEBSITE"
    SELECT_ADDRESS_BAR = "SELECT_ADDRESS_BAR"
    REPLACE_ADDRESS_OR_SEARCH = "REPLACE_ADDRESS_OR_SEARCH"
    SUBMIT_SEARCH = "SUBMIT_SEARCH"
    COPY_SELECTION = "COPY_SELECTION"
    PASTE_TEXT = "PASTE_TEXT"
    CLEAR_FIELD = "CLEAR_FIELD"
    REPLACE_TEXT = "REPLACE_TEXT"
    PRESS_SAFE_KEY = "PRESS_SAFE_KEY"
    UNDO_SAFE = "UNDO_SAFE"
    REDO_SAFE = "REDO_SAFE"
    STOP_CURRENT = "STOP_CURRENT"
    WAIT = "WAIT"
    CONTINUE_PENDING = "CONTINUE_PENDING"
    DRAFT_MESSAGE = "DRAFT_MESSAGE"
    SEND_MESSAGE = "SEND_MESSAGE"
    SEND_MESSAGE_AFTER_CONFIRMATION = "SEND_MESSAGE_AFTER_CONFIRMATION"
    START_CALL = "START_CALL"
    CREATE_REMINDER = "CREATE_REMINDER"
    TAKE_SCREENSHOT = "TAKE_SCREENSHOT"
    READ_SCREEN_OR_WINDOW = "READ_SCREEN_OR_WINDOW"
    EXPLAIN_ERROR_ON_SCREEN = "EXPLAIN_ERROR_ON_SCREEN"
    STOP_CURRENT_ACTION = "STOP_CURRENT_ACTION"
    RETRY_LAST_FAILED_SAFE = "RETRY_LAST_FAILED_SAFE"
    CANCEL_PENDING_CONFIRMATION = "CANCEL_PENDING_CONFIRMATION"
    DRY_RUN_PLAN = "DRY_RUN_PLAN"
    EXPLAIN_PENDING_PLAN = "EXPLAIN_PENDING_PLAN"
    SYSTEM_STATUS = "SYSTEM_STATUS"
    CLOSE_WINDOW = "CLOSE_WINDOW"
    CALL_CONTACT = "CALL_CONTACT"
    CLICK_TEXT = "CLICK_TEXT"
    SUBMIT_FORM = "SUBMIT_FORM"
    OPEN_NEW_TAB = "OPEN_NEW_TAB"
    BROWSER_BACK = "BROWSER_BACK"
    BROWSER_FORWARD = "BROWSER_FORWARD"
    REFRESH = "REFRESH"
    CLOSE_CURRENT_TAB = "CLOSE_CURRENT_TAB"
    QUICK_OPEN = "QUICK_OPEN"
    COMMAND_PALETTE = "COMMAND_PALETTE"
    TYPE_IN_ACTIVE_FIELD = "TYPE_IN_ACTIVE_FIELD"
    OPEN_FILE = "OPEN_FILE"
    SEARCH_FILES = "SEARCH_FILES"
    COPY_PATH = "COPY_PATH"
    DELETE_FILE = "DELETE_FILE"
    RENAME_FILE = "RENAME_FILE"
    MOVE_FILE = "MOVE_FILE"
    PLAY_MEDIA = "PLAY_MEDIA"
    PAUSE_MEDIA = "PAUSE_MEDIA"
    NEXT_MEDIA = "NEXT_MEDIA"
    EXPLAIN_COMMAND = "EXPLAIN_COMMAND"
    PROPOSE_TERMINAL_COMMAND = "PROPOSE_TERMINAL_COMMAND"


class VerificationStatus(_StringEnum):
    VERIFIED = "verified"
    LIKELY_SUCCESS = "likely_success"
    PARTIAL = "partial"
    BLOCKED = "blocked"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class SemanticAutomationAction:
    intent: SemanticAutomationIntent
    domain: AutomationDomain
    mode: AutomationMode
    target: str | None = None
    content: str | None = None
    app: str | None = None
    file_path: str | None = None
    query: str | None = None
    url: str | None = None
    recipient: str | None = None
    requires_context: bool = False
    missing_fields: list[str] = field(default_factory=list)
    safety_level: str = "LOW"
    preferred_tool: str | None = None
    fallback_tool: str | None = None
    verification_strategy: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent.value,
            "domain": self.domain.value,
            "mode": self.mode.value,
            "target": self.target,
            "content": self.content,
            "app": self.app,
            "file_path": self.file_path,
            "query": self.query,
            "url": self.url,
            "recipient": self.recipient,
            "requires_context": self.requires_context,
            "missing_fields": list(self.missing_fields),
            "safety_level": self.safety_level,
            "preferred_tool": self.preferred_tool,
            "fallback_tool": self.fallback_tool,
            "verification_strategy": self.verification_strategy,
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class SemanticActionPlan:
    original_text: str
    actions: list[SemanticAutomationAction] = field(default_factory=list)
    mode: AutomationMode | None = None
    requires_confirmation: bool = False
    missing_fields: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "original_text": self.original_text,
            "actions": [action.as_dict() for action in self.actions],
            "mode": self.mode.value if self.mode else None,
            "requires_confirmation": self.requires_confirmation,
            "missing_fields": list(self.missing_fields),
            "metadata": dict(self.metadata),
        }
