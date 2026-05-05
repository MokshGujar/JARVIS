from __future__ import annotations

from pathlib import Path
from typing import Any

from app.policy.models import PolicyDecision, PolicyDecisionType, RoutingMode, ToolMetadata, ToolRiskLevel, ToolStatus


class PolicyEngine:
    FILE_READ_ACTIONS = {"list", "read", "search", "path", "resolve_path", "verify_exists", "read_file", "list_files", "search_files"}
    FILE_MUTATION_ACTIONS = {
        "create",
        "rename",
        "move",
        "update",
        "create_file",
        "write_file",
        "append_file",
        "create_folder",
        "rename_file",
        "move_file",
    }
    FILE_DELETE_ACTIONS = {"delete", "delete_file"}
    FOLDER_DELETE_ACTIONS = {"delete_folder", "bulk_delete", "delete_tree", "remove_folder", "remove_directory"}
    BROWSER_ALLOW_ACTIONS = {"search", "open_url", "open_site", "youtube_search", "youtube_play", "navigation", "go_to"}
    SYSTEM_READ_ACTIONS = {"status", "safe_system_info", "screenshot", "volume_up", "volume_down", "mute_volume"}
    SYSTEM_STEP_UP_ACTIONS = {"lock", "lock_system", "shutdown", "shutdown_system", "restart", "restart_system", "sleep_system"}
    COMMUNICATION_SEND_ACTIONS = {
        "send",
        "send_message",
        "confirm_send",
        "send_email",
        "send_sms",
        "start_voice_call",
        "start_video_call",
        "call_contact",
    }
    TERMINAL_ACTIONS = {"run", "run_command", "execute", "shell", "stop_command"}
    SENSITIVE_PATH_PARTS = {
        ".ssh",
        ".aws",
        ".azure",
        ".gnupg",
        "windows",
        "system32",
        "program files",
        "program files (x86)",
    }
    SENSITIVE_FILE_NAMES = {".env", "id_rsa", "id_dsa", "credentials", "credentials.json", "secrets.toml"}

    def evaluate(
        self,
        tool_name: str,
        action: str,
        args: dict[str, Any] | None = None,
        context: Any | None = None,
        *,
        metadata: ToolMetadata | None = None,
    ) -> PolicyDecision:
        normalized_tool = _normalize(tool_name)
        normalized_action = _normalize(action)
        args = dict(args or {})
        session_id = _context_value(context, "session_id")
        turn_id = _context_value(context, "turn_id") or _context_value(context, "request_id")

        metadata_block = self._metadata_block(metadata, normalized_action, session_id=session_id, turn_id=turn_id)
        if metadata_block is not None:
            return metadata_block

        if normalized_tool in {"terminal", "shell", "safe_command_info"} or normalized_action in self.TERMINAL_ACTIONS:
            if normalized_tool == "safe_command_info" and normalized_action in {"explain", "lookup"}:
                return self._decision(PolicyDecisionType.ALLOW, ToolRiskLevel.LOW, "read_only_command_info", normalized_tool, normalized_action, session_id, turn_id)
            return self._decision(PolicyDecisionType.DENY, ToolRiskLevel.CRITICAL, "terminal_commands_denied_by_default", normalized_tool, normalized_action, session_id, turn_id)

        if normalized_tool == "file":
            return self._evaluate_file(normalized_tool, normalized_action, args, session_id, turn_id)

        if normalized_tool in {"app", "app_launcher"}:
            if normalized_action in {"open", "app_open", "focus", "app_focus"}:
                return self._decision(PolicyDecisionType.ALLOW, ToolRiskLevel.LOW, "app_open_or_focus", normalized_tool, normalized_action, session_id, turn_id)
            if normalized_action in {"close", "app_close", "kill"}:
                return self._decision(
                    PolicyDecisionType.CONFIRM,
                    ToolRiskLevel.HIGH,
                    "app_close_requires_confirmation",
                    normalized_tool,
                    normalized_action,
                    session_id,
                    turn_id,
                    requires_confirmation=True,
                )
            return self._decision(PolicyDecisionType.ALLOW, ToolRiskLevel.LOW, "app_control_default_allow", normalized_tool, normalized_action, session_id, turn_id)

        if normalized_tool == "browser":
            if normalized_action in self.BROWSER_ALLOW_ACTIONS:
                return self._decision(PolicyDecisionType.ALLOW, ToolRiskLevel.LOW, "browser_navigation_or_search", normalized_tool, normalized_action, session_id, turn_id)
            if normalized_action in {"form_input", "click", "click_text", "click_coordinates"}:
                return self._decision(PolicyDecisionType.CONFIRM, ToolRiskLevel.HIGH, "browser_interaction_requires_confirmation", normalized_tool, normalized_action, session_id, turn_id, requires_confirmation=True)
            if normalized_action in {"form_submit", "submit"}:
                return self._decision(PolicyDecisionType.CONFIRM, ToolRiskLevel.HIGH, "browser_submit_requires_confirmation", normalized_tool, normalized_action, session_id, turn_id, requires_confirmation=True)
            return self._decision(PolicyDecisionType.ALLOW, ToolRiskLevel.LOW, "browser_default_allow", normalized_tool, normalized_action, session_id, turn_id)

        if normalized_tool == "system":
            if normalized_action in self.SYSTEM_READ_ACTIONS:
                return self._decision(PolicyDecisionType.ALLOW, ToolRiskLevel.LOW, "safe_system_action", normalized_tool, normalized_action, session_id, turn_id)
            if normalized_action in self.SYSTEM_STEP_UP_ACTIONS:
                return self._decision(
                    PolicyDecisionType.STEP_UP,
                    ToolRiskLevel.CRITICAL,
                    "system_power_or_lock_requires_step_up",
                    normalized_tool,
                    normalized_action,
                    session_id,
                    turn_id,
                    requires_confirmation=True,
                    requires_step_up=True,
                )
            return self._decision(PolicyDecisionType.DENY, ToolRiskLevel.CRITICAL, "unknown_system_action_denied", normalized_tool, normalized_action, session_id, turn_id)

        if normalized_tool in {"communication", "message", "whatsapp", "phone", "email"} or normalized_action in self.COMMUNICATION_SEND_ACTIONS:
            risk = ToolRiskLevel.HIGH if normalized_action in self.COMMUNICATION_SEND_ACTIONS else ToolRiskLevel.LOW
            decision = PolicyDecisionType.CONFIRM if risk == ToolRiskLevel.HIGH else PolicyDecisionType.ALLOW
            return self._decision(
                decision,
                risk,
                "external_communication" if risk == ToolRiskLevel.HIGH else "communication_readiness",
                normalized_tool,
                normalized_action,
                session_id,
                turn_id,
                requires_confirmation=risk == ToolRiskLevel.HIGH,
            )

        if metadata is not None:
            if metadata.requires_step_up:
                return self._decision(PolicyDecisionType.STEP_UP, metadata.risk_level, "tool_metadata_requires_step_up", normalized_tool, normalized_action, session_id, turn_id, requires_confirmation=metadata.requires_confirmation, requires_step_up=True)
            if metadata.requires_confirmation:
                return self._decision(PolicyDecisionType.CONFIRM, metadata.risk_level, "tool_metadata_requires_confirmation", normalized_tool, normalized_action, session_id, turn_id, requires_confirmation=True)
            return self._decision(PolicyDecisionType.ALLOW, metadata.risk_level, "tool_metadata_allows", normalized_tool, normalized_action, session_id, turn_id)

        return self._decision(PolicyDecisionType.ALLOW, ToolRiskLevel.LOW, "default_low_risk", normalized_tool, normalized_action, session_id, turn_id)

    def _evaluate_file(
        self,
        tool_name: str,
        action: str,
        args: dict[str, Any],
        session_id: str | None,
        turn_id: str | None,
    ) -> PolicyDecision:
        if action in self.FILE_READ_ACTIONS:
            if self._args_reference_sensitive_path(args):
                return self._decision(PolicyDecisionType.CONFIRM, ToolRiskLevel.MEDIUM, "sensitive_file_read_requires_confirmation", tool_name, action, session_id, turn_id, requires_confirmation=True)
            return self._decision(PolicyDecisionType.ALLOW, ToolRiskLevel.LOW, "file_read_only", tool_name, action, session_id, turn_id)
        if action in self.FILE_MUTATION_ACTIONS:
            return self._decision(PolicyDecisionType.CONFIRM, ToolRiskLevel.MEDIUM, "file_mutation_requires_confirmation", tool_name, action, session_id, turn_id, requires_confirmation=True)
        if action in self.FILE_DELETE_ACTIONS:
            return self._decision(PolicyDecisionType.CONFIRM, ToolRiskLevel.CRITICAL, "file_delete_requires_confirmation", tool_name, action, session_id, turn_id, requires_confirmation=True)
        if action in self.FOLDER_DELETE_ACTIONS:
            return self._decision(PolicyDecisionType.STEP_UP, ToolRiskLevel.CRITICAL, "folder_or_bulk_delete_requires_step_up", tool_name, action, session_id, turn_id, requires_confirmation=True, requires_step_up=True)
        return self._decision(PolicyDecisionType.CONFIRM, ToolRiskLevel.MEDIUM, "unknown_file_action_requires_confirmation", tool_name, action, session_id, turn_id, requires_confirmation=True)

    def _metadata_block(
        self,
        metadata: ToolMetadata | None,
        action: str,
        *,
        session_id: str | None,
        turn_id: str | None,
    ) -> PolicyDecision | None:
        if metadata is None:
            return None
        if metadata.status == ToolStatus.DISABLED or metadata.routing_mode == RoutingMode.DISABLED:
            return self._decision(PolicyDecisionType.DENY, metadata.risk_level, "tool_disabled", metadata.name, action, session_id, turn_id)
        if metadata.status == ToolStatus.PLANNED:
            return self._decision(PolicyDecisionType.DENY, metadata.risk_level, "tool_planned", metadata.name, action, session_id, turn_id)
        if metadata.routing_mode == RoutingMode.METADATA_ONLY:
            return self._decision(PolicyDecisionType.DENY, metadata.risk_level, "tool_metadata_only", metadata.name, action, session_id, turn_id)
        if metadata.routing_mode == RoutingMode.HIDDEN:
            return self._decision(PolicyDecisionType.DENY, metadata.risk_level, "tool_hidden", metadata.name, action, session_id, turn_id)
        if metadata.status == ToolStatus.PARTIAL and not metadata.allows_execution(action):
            return self._decision(PolicyDecisionType.DENY, metadata.risk_level, "partial_tool_action_not_safe", metadata.name, action, session_id, turn_id)
        if metadata.allowed_actions and action not in {_normalize(item) for item in metadata.allowed_actions}:
            return self._decision(PolicyDecisionType.DENY, metadata.risk_level, "tool_action_not_allowed", metadata.name, action, session_id, turn_id)
        return None

    def _args_reference_sensitive_path(self, args: dict[str, Any]) -> bool:
        candidates: list[str] = []
        for key in ("path", "path_or_name", "source", "destination", "folder", "location", "parent"):
            value = args.get(key)
            if value is not None:
                candidates.append(str(value))
        for candidate in candidates:
            lowered = candidate.lower()
            name = Path(candidate).name.lower()
            if name in self.SENSITIVE_FILE_NAMES:
                return True
            if any(part in lowered for part in self.SENSITIVE_PATH_PARTS):
                return True
        return False

    @staticmethod
    def _decision(
        decision: PolicyDecisionType,
        risk_level: ToolRiskLevel,
        reason: str,
        tool_name: str,
        action: str,
        session_id: str | None,
        turn_id: str | None,
        *,
        requires_confirmation: bool = False,
        requires_step_up: bool = False,
    ) -> PolicyDecision:
        return PolicyDecision(
            decision=decision,
            risk_level=risk_level,
            requires_confirmation=requires_confirmation,
            requires_step_up=requires_step_up,
            reason=reason,
            tool_name=tool_name,
            action=action,
            session_id=session_id,
            turn_id=turn_id,
        )


def _normalize(value: str) -> str:
    return str(value or "").strip().lower()


def _context_value(context: Any | None, key: str) -> str | None:
    if context is None:
        return None
    value = getattr(context, key, None)
    if value:
        return str(value)
    if isinstance(context, dict):
        value = context.get(key)
        return str(value) if value else None
    metadata = getattr(context, "metadata", None)
    if isinstance(metadata, dict):
        value = metadata.get(key)
        return str(value) if value else None
    payload = getattr(context, "payload", None)
    if isinstance(payload, dict):
        value = payload.get(key)
        return str(value) if value else None
    return None
