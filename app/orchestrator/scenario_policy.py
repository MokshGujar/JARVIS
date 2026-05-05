from __future__ import annotations

from dataclasses import dataclass, field

from app.orchestrator.intent_router import RouteDecision
from app.policy.policy_engine import PolicyEngine
from app.tools.tool_inventory import get_tool_inventory_record


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

    def __init__(self, policy_engine: PolicyEngine | None = None) -> None:
        self.policy_engine = policy_engine or PolicyEngine()

    def evaluate(self, route: RouteDecision) -> PolicyDecision:
        core_decision = self.policy_engine.evaluate(
            route.tool_name,
            route.operation,
            route.parameters,
            context=None,
        )
        requires_voice_permission = core_decision.requires_step_up
        record = get_tool_inventory_record(route.tool_name)
        if record is not None and str(route.operation or "").strip().lower() in set(record.protected_actions):
            requires_voice_permission = True
        return PolicyDecision(
            safety_level=core_decision.risk_level.value,
            requires_confirmation=core_decision.requires_confirmation,
            requires_face_step_up=core_decision.requires_step_up,
            requires_voice_permission=requires_voice_permission,
            reasons=[core_decision.reason, core_decision.decision.value],
        )

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
