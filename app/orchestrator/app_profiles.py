from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.orchestrator.semantic_automation import SemanticAutomationIntent


@dataclass(frozen=True, slots=True)
class AppProfileAction:
    semantic_intent: SemanticAutomationIntent
    tool_name: str
    tool_actions: tuple[str, ...] = field(default_factory=tuple)
    safety_level: str = "LOW"
    requires_confirmation: bool = False
    notes: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AppProfile:
    canonical_name: str
    aliases: tuple[str, ...]
    category: str
    actions: dict[SemanticAutomationIntent, AppProfileAction]
    cautious: bool = False
    notes: str = ""

    def action_for(self, intent: SemanticAutomationIntent) -> AppProfileAction | None:
        return self.actions.get(intent)


def _action(
    intent: SemanticAutomationIntent,
    tool_name: str,
    tool_actions: tuple[str, ...],
    *,
    safety_level: str = "LOW",
    requires_confirmation: bool = False,
    notes: str = "",
    metadata: dict[str, Any] | None = None,
) -> AppProfileAction:
    return AppProfileAction(
        semantic_intent=intent,
        tool_name=tool_name,
        tool_actions=tool_actions,
        safety_level=safety_level,
        requires_confirmation=requires_confirmation,
        notes=notes,
        metadata=dict(metadata or {}),
    )


def _browser_profile(name: str, aliases: tuple[str, ...]) -> AppProfile:
    return AppProfile(
        canonical_name=name,
        aliases=aliases,
        category="browser",
        actions={
            SemanticAutomationIntent.SEARCH_VISIBLE_BROWSER: _action(
                SemanticAutomationIntent.SEARCH_VISIBLE_BROWSER,
                "app_interaction",
                ("select_address_bar", "replace_current_field", "submit_current_field"),
                notes="Visible browser search uses the address bar, then submits.",
            ),
            SemanticAutomationIntent.OPEN_NEW_TAB: _action(SemanticAutomationIntent.OPEN_NEW_TAB, "app_interaction", ("open_new_tab",)),
            SemanticAutomationIntent.BROWSER_BACK: _action(SemanticAutomationIntent.BROWSER_BACK, "app_interaction", ("browser_back",)),
            SemanticAutomationIntent.BROWSER_FORWARD: _action(SemanticAutomationIntent.BROWSER_FORWARD, "app_interaction", ("browser_forward",)),
            SemanticAutomationIntent.REFRESH: _action(SemanticAutomationIntent.REFRESH, "app_interaction", ("refresh",)),
            SemanticAutomationIntent.CLOSE_CURRENT_TAB: _action(
                SemanticAutomationIntent.CLOSE_CURRENT_TAB,
                "app_interaction",
                ("close_current_tab",),
                safety_level="HIGH",
                requires_confirmation=True,
                notes="Closing a tab may lose unsaved form state.",
            ),
        },
    )


GENERIC_CAUTIOUS_PROFILE = AppProfile(
    canonical_name="generic",
    aliases=(),
    category="unknown",
    cautious=True,
    notes="Unknown apps use generic visible UI behavior with extra caution.",
    actions={
        SemanticAutomationIntent.TYPE_IN_ACTIVE_FIELD: _action(
            SemanticAutomationIntent.TYPE_IN_ACTIVE_FIELD,
            "app_interaction",
            ("type_into_active_field",),
            safety_level="MEDIUM",
            notes="Only type when active focus is verified.",
        )
    },
)


APP_PROFILES: tuple[AppProfile, ...] = (
    _browser_profile("chrome", ("chrome", "google chrome")),
    _browser_profile("edge", ("edge", "microsoft edge", "ms edge")),
    AppProfile(
        canonical_name="notepad",
        aliases=("notepad",),
        category="note_document",
        actions={
            SemanticAutomationIntent.WRITE_NOTE: _action(SemanticAutomationIntent.WRITE_NOTE, "app_interaction", ("type_into_active_field",), safety_level="MEDIUM"),
            SemanticAutomationIntent.APPEND_TO_NOTE: _action(SemanticAutomationIntent.APPEND_TO_NOTE, "app_interaction", ("append_text",), safety_level="MEDIUM"),
            SemanticAutomationIntent.SAVE_CONTENT: _action(
                SemanticAutomationIntent.SAVE_CONTENT,
                "file",
                ("write_file",),
                safety_level="MEDIUM",
                notes="Prefer FileTool when content and path are known; do not blindly press Ctrl+S.",
                metadata={"prefer_file_tool": True, "blind_ctrl_s": False},
            ),
        },
    ),
    AppProfile(
        canonical_name="vs code",
        aliases=("vs code", "vscode", "visual studio code"),
        category="developer",
        actions={
            SemanticAutomationIntent.QUICK_OPEN: _action(SemanticAutomationIntent.QUICK_OPEN, "app_interaction", ("press_hotkey",), metadata={"keys": ("ctrl", "p")}),
            SemanticAutomationIntent.COMMAND_PALETTE: _action(SemanticAutomationIntent.COMMAND_PALETTE, "app_interaction", ("press_hotkey",), metadata={"keys": ("ctrl", "shift", "p")}),
            SemanticAutomationIntent.TYPE_IN_ACTIVE_FIELD: _action(
                SemanticAutomationIntent.TYPE_IN_ACTIVE_FIELD,
                "app_interaction",
                ("type_into_active_field",),
                safety_level="MEDIUM",
                notes="Type only if editor focus is known safe.",
            ),
        },
    ),
    AppProfile(
        canonical_name="file explorer",
        aliases=("file explorer", "explorer", "windows explorer"),
        category="file",
        actions={
            SemanticAutomationIntent.OPEN_FILE: _action(SemanticAutomationIntent.OPEN_FILE, "file", ("open_file",)),
            SemanticAutomationIntent.SEARCH_FILES: _action(SemanticAutomationIntent.SEARCH_FILES, "file", ("search_files",)),
            SemanticAutomationIntent.COPY_PATH: _action(SemanticAutomationIntent.COPY_PATH, "file", ("resolve_path",)),
            SemanticAutomationIntent.DELETE_FILE: _action(SemanticAutomationIntent.DELETE_FILE, "file", ("delete_file",), safety_level="CRITICAL", requires_confirmation=True),
            SemanticAutomationIntent.RENAME_FILE: _action(SemanticAutomationIntent.RENAME_FILE, "file", ("rename_file",), safety_level="MEDIUM", notes="Requires resolved target."),
            SemanticAutomationIntent.MOVE_FILE: _action(SemanticAutomationIntent.MOVE_FILE, "file", ("move_file",), safety_level="MEDIUM", notes="Requires resolved target."),
        },
    ),
    AppProfile(
        canonical_name="whatsapp",
        aliases=("whatsapp", "whats app"),
        category="communication",
        actions={
            SemanticAutomationIntent.DRAFT_MESSAGE: _action(SemanticAutomationIntent.DRAFT_MESSAGE, "message", ("prepare_message",), notes="Draft only by default."),
            SemanticAutomationIntent.SEND_MESSAGE_AFTER_CONFIRMATION: _action(
                SemanticAutomationIntent.SEND_MESSAGE_AFTER_CONFIRMATION,
                "message",
                ("send_message",),
                safety_level="HIGH",
                requires_confirmation=True,
                notes="Sending requires confirmation and protected policy.",
            ),
            SemanticAutomationIntent.START_CALL: _action(
                SemanticAutomationIntent.START_CALL,
                "whatsapp",
                ("start_voice_call",),
                safety_level="HIGH",
                requires_confirmation=True,
                notes="Calls require confirmation.",
            ),
        },
    ),
    AppProfile(
        canonical_name="calculator",
        aliases=("calculator", "calc"),
        category="app_control",
        actions={
            SemanticAutomationIntent.TYPE_IN_ACTIVE_FIELD: _action(
                SemanticAutomationIntent.TYPE_IN_ACTIVE_FIELD,
                "app_interaction",
                ("type_into_active_field",),
                safety_level="LOW",
                notes="Type safe expressions only.",
            )
        },
    ),
    AppProfile(
        canonical_name="spotify",
        aliases=("spotify", "media player", "music"),
        category="media",
        actions={
            SemanticAutomationIntent.PLAY_MEDIA: _action(SemanticAutomationIntent.PLAY_MEDIA, "media", ("play",), notes="Use media/system/browser tools when available."),
            SemanticAutomationIntent.PAUSE_MEDIA: _action(SemanticAutomationIntent.PAUSE_MEDIA, "media", ("pause",)),
            SemanticAutomationIntent.NEXT_MEDIA: _action(SemanticAutomationIntent.NEXT_MEDIA, "media", ("next",)),
        },
    ),
    AppProfile(
        canonical_name="terminal",
        aliases=("terminal", "powershell", "power shell", "windows terminal", "command prompt", "cmd"),
        category="developer",
        actions={
            SemanticAutomationIntent.EXPLAIN_COMMAND: _action(SemanticAutomationIntent.EXPLAIN_COMMAND, "safe_command_info", ("explain",), notes="Explain/propose only by default."),
            SemanticAutomationIntent.PROPOSE_TERMINAL_COMMAND: _action(
                SemanticAutomationIntent.PROPOSE_TERMINAL_COMMAND,
                "terminal",
                ("run_command",),
                safety_level="CRITICAL",
                requires_confirmation=True,
                notes="Execution requires an explicit future terminal phase and confirmation.",
            ),
        },
    ),
)


PROFILE_BY_ALIAS = {
    alias.lower(): profile
    for profile in APP_PROFILES
    for alias in (profile.canonical_name, *profile.aliases)
}


def get_app_profile(app_name: str | None) -> AppProfile:
    normalized = " ".join(str(app_name or "").strip().lower().split())
    return PROFILE_BY_ALIAS.get(normalized, GENERIC_CAUTIOUS_PROFILE)
