from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass(frozen=True, slots=True)
class RealWorldCommandCase:
    id: int
    command: str
    group: str
    expected_route: str
    expected_tool: str
    policy_decision: str
    direct_execution_allowed: bool
    clarification_required: bool
    support_status: str
    blocker: str
    test_status: str

    def as_dict(self) -> dict:
        return asdict(self)


def get_real_world_command_suite() -> tuple[RealWorldCommandCase, ...]:
    return REAL_WORLD_COMMAND_SUITE


def get_real_world_command_suite_dicts() -> list[dict]:
    return [item.as_dict() for item in REAL_WORLD_COMMAND_SUITE]


def _case(
    id: int,
    command: str,
    group: str,
    route: str,
    tool: str,
    policy: str,
    direct: bool,
    clarify: bool,
    status: str,
    blocker: str = "",
    test_status: str = "covered",
) -> RealWorldCommandCase:
    return RealWorldCommandCase(
        id=id,
        command=command,
        group=group,
        expected_route=route,
        expected_tool=tool,
        policy_decision=policy,
        direct_execution_allowed=direct,
        clarification_required=clarify,
        support_status=status,
        blocker=blocker,
        test_status=test_status,
    )


REAL_WORLD_COMMAND_SUITE: tuple[RealWorldCommandCase, ...] = (
    _case(1, "Hello Jarvis", "A. Core/voice/chat", "local", "chat_service", "ALLOW", True, False, "supported now"),
    _case(2, "What can you do?", "A. Core/voice/chat", "capability_summary", "CapabilitySummaryService", "ALLOW", True, False, "supported after this phase"),
    _case(3, "Stop listening", "A. Core/voice/chat", "voice_control", "frontend_phone_voice", "ALLOW", True, False, "metadata/planned", "browser/app control path is UI-side"),
    _case(4, "Cancel that", "A. Core/voice/chat", "pending_action", "pending_confirmation", "ALLOW", True, False, "supported now"),
    _case(5, "Repeat that", "A. Core/voice/chat", "chat", "conversation_service", "ALLOW", True, False, "not implemented", "no deterministic repeat-last-response route"),
    _case(6, "Give me a short answer", "A. Core/voice/chat", "chat", "conversation_service", "ALLOW", True, False, "supported now"),
    _case(7, "Continue", "A. Core/voice/chat", "chat", "conversation_service", "ALLOW", True, False, "supported now"),
    _case(8, "Explain this simply", "A. Core/voice/chat", "chat", "conversation_service", "ALLOW", True, False, "supported now"),
    _case(9, "Search my laptop for resume", "B. Local laptop/files", "automation", "file", "ALLOW", True, False, "supported now"),
    _case(10, "Can you search a file for me?", "B. Local laptop/files", "capability_summary", "CapabilitySummaryService", "ALLOW", True, False, "supported after this phase"),
    _case(11, "Search a file", "B. Local laptop/files", "automation", "file", "CLARIFY", False, True, "supported now"),
    _case(12, "Find files about Jarvis", "B. Local laptop/files", "automation", "file", "ALLOW", True, False, "supported now"),
    _case(13, "Find recently modified files", "B. Local laptop/files", "automation", "file", "ALLOW", True, False, "supported now"),
    _case(14, "List files on Desktop", "B. Local laptop/files", "automation", "file", "ALLOW", True, False, "supported now"),
    _case(15, "Read it", "B. Local laptop/files", "automation_followup", "file", "ALLOW", True, True, "supported now"),
    _case(16, "Open the second one", "B. Local laptop/files", "automation_followup", "file/app", "ALLOW", True, True, "supported now"),
    _case(17, "Show me its path", "B. Local laptop/files", "automation_followup", "file", "ALLOW", True, True, "supported now"),
    _case(18, "Summarize it", "B. Local laptop/files", "automation_followup", "summary", "ALLOW", True, True, "supported now"),
    _case(19, "Create file on desktop named semantictest and write hello", "B. Local laptop/files", "automation", "file", "ALLOW", True, False, "supported now"),
    _case(20, "Put world in it", "B. Local laptop/files", "automation_followup", "file", "CONFIRM", False, True, "supported now"),
    _case(21, "Delete it", "B. Local laptop/files", "automation_followup", "file", "STEP_UP", False, True, "blocked for safety", "file delete requires confirmation and voice permission"),
    _case(22, "Open calculator", "C. Apps/browser/system", "automation", "app", "ALLOW", True, False, "supported now"),
    _case(23, "Open Chrome", "C. Apps/browser/system", "automation", "app", "ALLOW", True, False, "supported now"),
    _case(24, "Open WhatsApp", "C. Apps/browser/system", "automation", "whatsapp/app", "ALLOW", True, False, "supported now"),
    _case(25, "Search Google for cats", "C. Apps/browser/system", "automation", "browser", "ALLOW", True, False, "supported now"),
    _case(26, "Search Google for files", "C. Apps/browser/system", "automation", "browser", "ALLOW", True, False, "supported now"),
    _case(27, "Show system status", "C. Apps/browser/system", "automation", "system", "ALLOW", True, False, "supported now"),
    _case(28, "Volume up", "C. Apps/browser/system", "automation", "system", "ALLOW", True, False, "supported now"),
    _case(29, "Take screenshot", "C. Apps/browser/system", "automation", "system", "ALLOW", True, False, "supported now"),
    _case(30, "Shutdown computer", "C. Apps/browser/system", "automation", "system", "STEP_UP", False, False, "blocked for safety", "power action requires protected authorization"),
    _case(31, "Open WhatsApp chat with Hetanshi India", "D. Contacts/WhatsApp/Gmail", "automation", "whatsapp", "ALLOW", True, False, "supported now"),
    _case(32, "Send WhatsApp message to Hetanshi India saying hello", "D. Contacts/WhatsApp/Gmail", "automation", "whatsapp", "ALLOW", True, False, "supported now"),
    _case(33, "Call Hetanshi India on WhatsApp", "D. Contacts/WhatsApp/Gmail", "automation", "whatsapp", "ALLOW", True, False, "supported now"),
    _case(34, "Make WhatsApp video call to Hetanshi India", "D. Contacts/WhatsApp/Gmail", "automation", "whatsapp", "ALLOW", True, False, "supported now"),
    _case(35, "Hitanchi India should ask \"Did you mean Hetanshi India?\"", "D. Contacts/WhatsApp/Gmail", "contact_clarification", "contact", "CLARIFY", False, True, "supported now"),
    _case(36, "Send email to [email] saying hello", "D. Contacts/WhatsApp/Gmail", "automation", "gmail", "DENY", False, False, "external setup required", "Gmail connector is not configured"),
    _case(37, "Draft email to [email] saying hello", "D. Contacts/WhatsApp/Gmail", "automation", "gmail", "DENY", False, False, "external setup required", "Gmail connector is not configured"),
    _case(38, "Show unread Gmail count", "D. Contacts/WhatsApp/Gmail", "automation", "gmail", "DENY", False, False, "external setup required", "Gmail connector is not configured"),
    _case(39, "Search Gmail for emails from [email]", "D. Contacts/WhatsApp/Gmail", "automation", "gmail", "DENY", False, False, "external setup required", "Gmail connector is not configured"),
    _case(40, "Sync phone contacts", "E. Phone/app", "phone_bridge", "PhoneCommandService", "ALLOW", True, False, "supported now"),
    _case(41, "Show incoming caller", "E. Phone/app", "phone_bridge", "CallerLookupService", "ALLOW", True, False, "supported now"),
    _case(42, "Acknowledge phone pending action", "E. Phone/app", "phone_bridge", "PhoneCommandService", "ALLOW", True, False, "supported now"),
    _case(43, "Background listening without beep", "E. Phone/app", "android_service", "BackgroundVoiceService", "ALLOW", True, False, "supported after this phase"),
    _case(44, "App-side no-speech handling", "E. Phone/app", "stt", "STTTool", "ALLOW", True, False, "supported now"),
    _case(45, "App-side final TTS once", "E. Phone/app", "voice_stream", "Android stream consumer", "ALLOW", True, False, "supported now"),
    _case(46, "Remind me to drink water at 6 PM", "F. Reminders/tasks/research/vision", "reminder", "ReminderTool", "ALLOW", True, False, "supported after this phase"),
    _case(47, "Show due reminders", "F. Reminders/tasks/research/vision", "notification_center", "NotificationCenterService", "ALLOW", True, False, "supported after this phase"),
    _case(48, "Prepare daily briefing", "F. Reminders/tasks/research/vision", "agent_workflow", "LangGraph/agents", "DENY", False, False, "metadata/planned", "deferred until LangGraph/agent phases"),
    _case(49, "Research latest AI news", "F. Reminders/tasks/research/vision", "realtime", "ResearchToolsService", "ALLOW", True, False, "external setup required", "requires realtime/search provider"),
    _case(50, "Describe this image", "F. Reminders/tasks/research/vision", "vision", "VisionService", "ALLOW", True, False, "supported now", "requires image input"),
    _case(51, "Create an agent that tracks AI news", "G. Agents/developer/security", "agent", "agent_builder", "DENY", False, True, "metadata/planned", "self-created agents deferred"),
    _case(52, "List my agents", "G. Agents/developer/security", "agent", "agent_registry", "DENY", False, False, "metadata/planned", "self-created agents deferred"),
    _case(53, "Propose terminal command but do not run it", "G. Agents/developer/security", "developer", "terminal", "DENY", False, False, "metadata/planned", "terminal is proposal-only and developer phase deferred"),
    _case(54, "Explain this code", "G. Agents/developer/security", "chat", "conversation_service", "ALLOW", True, False, "supported now"),
    _case(55, "Search project code for AutomationService", "G. Agents/developer/security", "developer", "code_search", "DENY", False, False, "metadata/planned", "developer mode deferred"),
    _case(56, "Refuse unsafe command", "G. Agents/developer/security", "policy", "PolicyEngine", "DENY", False, False, "supported now"),
)
