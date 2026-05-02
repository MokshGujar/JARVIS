from __future__ import annotations

from dataclasses import dataclass, field

from app.orchestrator.intent_router import RouteDecision


@dataclass(slots=True)
class PolicyDecision:
    safety_level: str
    requires_confirmation: bool = False
    requires_face_step_up: bool = False
    requires_voice_permission: bool = False
    reasons: list[str] = field(default_factory=list)


class ScenarioPolicy:
    LOW_FILE_OPERATIONS = {"list", "read", "search", "path", "resolve_path", "verify_exists", "read_file", "list_files", "search_files"}
    MEDIUM_FILE_OPERATIONS = {"create", "rename", "move", "update", "create_file", "write_file", "append_file", "create_folder", "rename_file", "move_file"}
    CRITICAL_FILE_OPERATIONS = {"delete", "delete_file", "delete_folder"}

    def evaluate(self, route: RouteDecision) -> PolicyDecision:
        if route.category == "file":
            operation = route.operation
            if operation in self.CRITICAL_FILE_OPERATIONS:
                return PolicyDecision(
                    safety_level="CRITICAL",
                    requires_confirmation=True,
                    requires_face_step_up=False,
                    requires_voice_permission=True,
                    reasons=["destructive_file_operation"],
                )
            if operation in self.MEDIUM_FILE_OPERATIONS:
                return PolicyDecision(
                    safety_level="MEDIUM",
                    requires_confirmation=False,
                    requires_face_step_up=False,
                    reasons=["file_mutation"],
                )
            return PolicyDecision(safety_level="LOW", reasons=["file_read_only"])

        if route.category == "communication":
            operation = str(route.operation or "").strip().lower()
            inventory_decision = self._inventory_default(route)
            if inventory_decision is not None and "action_safety" in inventory_decision.reasons:
                return inventory_decision
            protected = operation in {"send_message", "confirm_send", "call", "start_voice_call", "start_video_call", "video_call"}
            return PolicyDecision(
                safety_level="HIGH",
                requires_confirmation=True,
                requires_voice_permission=protected,
                reasons=["external_communication"],
            )
        if route.category == "browser":
            if route.operation == "form_submit":
                return PolicyDecision(
                    safety_level="CRITICAL",
                    requires_confirmation=True,
                    requires_voice_permission=True,
                    reasons=["browser_form_submit"],
                )
            if route.operation == "form_input":
                return PolicyDecision(safety_level="HIGH", requires_confirmation=True, reasons=["browser_form_or_click"])
            return PolicyDecision(safety_level="LOW", reasons=["browser_navigation"])
        if route.category == "system" and route.operation in {"shutdown", "restart", "shutdown_system", "restart_system"}:
            return PolicyDecision(
                safety_level="CRITICAL",
                requires_confirmation=True,
                requires_voice_permission=True,
                reasons=["power_action"],
            )
        if route.category == "system" and route.operation in {"lock_system", "sleep_system"}:
            return PolicyDecision(safety_level="HIGH", requires_confirmation=True, reasons=["lock_system"])
        if route.category == "system":
            return PolicyDecision(safety_level="LOW", reasons=["local_system_control"])
        if route.category == "app":
            close_risk = route.operation == "close"
            return PolicyDecision(safety_level="HIGH" if close_risk else "LOW", requires_confirmation=close_risk, reasons=["app_control"])
        inventory_decision = self._inventory_default(route)
        if inventory_decision is not None:
            return inventory_decision
        return PolicyDecision(safety_level="LOW", reasons=[route.category or "unknown"])

    def _inventory_default(self, route: RouteDecision) -> PolicyDecision | None:
        try:
            from app.tools.tool_inventory import get_tool_inventory_record
        except Exception:
            return None

        record = get_tool_inventory_record(route.tool_name)
        if record is None:
            return None
        operation = str(route.operation or "").strip().lower()
        action_safety = dict(record.action_safety)
        has_action_override = operation in action_safety
        safety_level = str(action_safety.get(operation) or record.safety_level or "LOW").upper()
        requires_confirmation = safety_level in {"HIGH", "CRITICAL"} if has_action_override else bool(record.requires_confirmation)
        if safety_level in {"HIGH", "CRITICAL"}:
            requires_confirmation = True
        protected = operation in set(record.protected_actions)
        return PolicyDecision(
            safety_level=safety_level,
            requires_confirmation=requires_confirmation,
            requires_face_step_up=False,
            requires_voice_permission=protected or (record.requires_voice_permission and safety_level in {"HIGH", "CRITICAL"}),
            reasons=[f"inventory:{record.name}", record.current_status] + (["action_safety"] if has_action_override else []),
        )
