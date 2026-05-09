from app.policy.policy_engine import PolicyEngine
from app.policy.security_modes import SecurityMode, SecurityModeService
from app.tools.base import ToolContext


COMM_ARGS = {
    "direct_user_requested": True,
    "user_initiated": True,
    "fresh_user_command": True,
    "bulk": False,
    "single_recipient": True,
    "recipient_confident": True,
    "has_body": True,
}


def test_trusted_mode_direct_communication_allowed_for_exact_recipient():
    engine = PolicyEngine(SecurityModeService(SecurityMode.TRUSTED))

    decision = engine.evaluate("whatsapp", "send_message", COMM_ARGS, ToolContext(command="send whatsapp", source="user"))

    assert decision.decision.value == "ALLOW"
    assert decision.reason == "explicit_user_command_confident_contact"


def test_safe_mode_requires_confirmation_for_communication():
    engine = PolicyEngine(SecurityModeService(SecurityMode.SAFE))

    decision = engine.evaluate("gmail", "send_email", COMM_ARGS, ToolContext(command="send email", source="user"))

    assert decision.decision.value == "CONFIRM"


def test_developer_mode_still_blocks_destructive_shell():
    decision = SecurityModeService(SecurityMode.DEVELOPER).terminal_decision("git reset --hard")

    assert decision.allowed is False
    assert decision.reason == "destructive_terminal_command_blocked"


def test_agent_mode_enforces_allowed_tools():
    service = SecurityModeService(SecurityMode.AGENT)

    denied = service.agent_tool_decision(tool_name="gmail", allowed_tools=["research"])
    allowed = service.agent_tool_decision(tool_name="research", allowed_tools=["research"])

    assert denied.allowed is False
    assert denied.reason == "agent_tool_not_allowed"
    assert allowed.allowed is True


def test_unknown_mode_defaults_safe():
    assert SecurityMode.from_value("surprise") == SecurityMode.SAFE
