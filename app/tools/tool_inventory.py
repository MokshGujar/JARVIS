from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from app.orchestrator.tool_registry import ToolRegistry
from app.tools.base import AutomationTool, BaseTool, ToolContext, ToolResult, ToolRisk, ToolSpec
from app.tools.app_interaction_tool import AppInteractionTool
from app.tools.stt_tool import STTTool
from app.tools.summary_tool import SummaryTool


VALID_TOOL_CATEGORIES = {
    "file",
    "app",
    "browser",
    "system",
    "communication",
    "contact",
    "phone",
    "voice",
    "security",
    "memory",
    "reminder",
    "research",
    "media",
    "ui_automation",
    "device",
    "network",
    "developer",
    "domain",
}

VALID_TOOL_STATUSES = {"live_routed", "thin_wrapper", "metadata_only", "disabled"}


@dataclass(frozen=True, slots=True)
class ToolInventoryRecord:
    name: str
    category: str
    description: str
    supported_intents: tuple[str, ...] = field(default_factory=tuple)
    supported_actions: tuple[str, ...] = field(default_factory=tuple)
    safety_level: str = "LOW"
    requires_confirmation: bool = False
    requires_face_step_up: bool = False
    requires_voice_permission: bool = False
    current_status: str = "metadata_only"
    legacy_delegate: str | None = None
    target_connector: str | None = None
    target_adapter: str | None = None
    target_provider: str | None = None
    target_repository: str | None = None
    action_safety: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    protected_actions: tuple[str, ...] = field(default_factory=tuple)
    planned_phase: str = "future"
    test_requirements: tuple[str, ...] = field(default_factory=tuple)

    def as_tool_spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.name,
            description=self.description,
            category=self.category,
            safety_level=self.safety_level,
            requires_confirmation=self.requires_confirmation,
            requires_face_step_up=self.requires_face_step_up,
            requires_voice_permission=self.requires_voice_permission,
            supported_intents=list(self.supported_intents),
            metadata={
                "requires_voice_permission": self.requires_voice_permission,
                "supported_actions": list(self.supported_actions),
                "current_status": self.current_status,
                "status": self.current_status,
                "legacy_delegate": self.legacy_delegate,
                "target_connector": self.target_connector,
                "target_adapter": self.target_adapter,
                "target_provider": self.target_provider,
                "target_repository": self.target_repository,
                "action_safety": dict(self.action_safety),
                "protected_actions": list(self.protected_actions),
                "planned_phase": self.planned_phase,
                "test_requirements": list(self.test_requirements),
            },
        )


class MetadataTool(BaseTool):
    def __init__(self, record: ToolInventoryRecord) -> None:
        self.record = record
        self.name = record.name
        self.spec = record.as_tool_spec()

    def classify_risk(self, command: str) -> ToolRisk:
        return ToolRisk(
            level=self.record.safety_level,
            step_up_required=self.record.requires_face_step_up,
            reasons=[self.record.current_status],
        )

    def execute(self, context: ToolContext, **kwargs) -> dict:
        requested_action = self._requested_action(context)
        message = f"The {self.name} tool is not implemented yet."
        return ToolResult(
            success=False,
            message=message,
            tool_name=self.name,
            error="not_implemented",
            safety_level=self.record.safety_level,
            requires_confirmation=self.record.requires_confirmation,
            requires_voice_permission=self.record.requires_voice_permission,
            data={
                "action": "not_implemented",
                "tool": self.name,
                "tool_name": self.name,
                "requested_action": requested_action,
                "status": self.record.current_status,
                "supported_actions": list(self.record.supported_actions),
            },
        ).as_dict()

    @staticmethod
    def _requested_action(context: ToolContext) -> str:
        payload = dict(getattr(context, "payload", {}) or {})
        return str(payload.get("action") or context.intent or "unknown").strip() or "unknown"


class DisabledTool(MetadataTool):
    def execute(self, context: ToolContext, **kwargs) -> dict:
        requested_action = self._requested_action(context)
        message = f"The {self.name} tool is disabled."
        return ToolResult(
            success=False,
            message=message,
            tool_name=self.name,
            error="tool_disabled",
            safety_level=self.record.safety_level,
            requires_confirmation=self.record.requires_confirmation,
            requires_voice_permission=self.record.requires_voice_permission,
            data={
                "action": "disabled",
                "tool": self.name,
                "tool_name": self.name,
                "requested_action": requested_action,
                "status": self.record.current_status,
                "supported_actions": list(self.record.supported_actions),
            },
        ).as_dict()


def _defaults_for_safety(level: str) -> tuple[bool, bool]:
    normalized = str(level or "LOW").upper()
    if normalized == "CRITICAL":
        return True, False
    if normalized == "HIGH":
        return True, False
    return False, False


def _record(
    name: str,
    category: str,
    description: str,
    *,
    supported_intents: Iterable[str] = (),
    supported_actions: Iterable[str] = (),
    safety_level: str = "LOW",
    requires_confirmation: bool | None = None,
    requires_face_step_up: bool | None = None,
    requires_voice_permission: bool = False,
    current_status: str = "metadata_only",
    legacy_delegate: str | None = None,
    target_connector: str | None = None,
    target_adapter: str | None = None,
    target_provider: str | None = None,
    target_repository: str | None = None,
    action_safety: Iterable[tuple[str, str]] = (),
    protected_actions: Iterable[str] = (),
    planned_phase: str = "future",
    test_requirements: Iterable[str] = (),
) -> ToolInventoryRecord:
    default_confirmation, default_step_up = _defaults_for_safety(safety_level)
    return ToolInventoryRecord(
        name=name,
        category=category,
        description=description,
        supported_intents=tuple(supported_intents),
        supported_actions=tuple(supported_actions),
        safety_level=safety_level,
        requires_confirmation=default_confirmation if requires_confirmation is None else requires_confirmation,
        requires_face_step_up=default_step_up if requires_face_step_up is None else requires_face_step_up,
        requires_voice_permission=requires_voice_permission,
        current_status=current_status,
        legacy_delegate=legacy_delegate,
        target_connector=target_connector,
        target_adapter=target_adapter,
        target_provider=target_provider,
        target_repository=target_repository,
        action_safety=tuple((str(action).strip().lower(), str(level).upper()) for action, level in action_safety),
        protected_actions=tuple(str(action).strip().lower() for action in protected_actions if str(action).strip()),
        planned_phase=planned_phase,
        test_requirements=tuple(test_requirements),
    )


TOOL_INVENTORY: tuple[ToolInventoryRecord, ...] = (
    _record(
        "file",
        "file",
        "Local file and folder operations.",
        supported_intents=("file", "files", "local_files"),
        supported_actions=("resolve_path", "create_file", "write_file", "append_file", "create_folder", "verify_exists", "read_file", "list_files", "search_files", "rename_file", "move_file", "delete_file", "delete_folder"),
        safety_level="CRITICAL",
        current_status="live_routed",
        legacy_delegate="AutomationService._execute_file_command_legacy",
        target_connector="LocalFilesConnector",
        target_repository="file repository",
        planned_phase="current",
        test_requirements=("characterization", "no_real_destructive_actions", "protected_paths"),
    ),
    _record("app", "app", "Open, focus, and close local applications.", supported_intents=("app", "app_open", "app_close", "app_focus"), supported_actions=("open", "focus", "close"), safety_level="HIGH", current_status="live_routed", legacy_delegate="AutomationService._execute_app_launcher_command_legacy", planned_phase="current", test_requirements=("app_launcher_mocks",)),
    _record("browser", "browser", "Browser search and navigation automation.", supported_intents=("browser", "browser_search", "browser_open_url", "browser_open_site"), supported_actions=("search", "open_url", "open_site", "youtube_search", "youtube_play", "navigation", "form_input", "form_submit"), safety_level="HIGH", current_status="live_routed", legacy_delegate="AutomationService._execute_browser_command_legacy", target_connector="BrowserConnector", planned_phase="current", test_requirements=("browser_mocks", "no_real_form_submit")),
    _record("system", "system", "Local system controls.", supported_intents=("system", "volume_up", "volume_down", "mute_volume", "screenshot", "lock_system", "shutdown_system", "restart_system"), supported_actions=("volume_up", "volume_down", "mute_volume", "screenshot", "safe_system_info", "lock_system", "shutdown_system", "restart_system"), safety_level="CRITICAL", current_status="live_routed", legacy_delegate="AutomationService._execute_system_command_legacy", planned_phase="current", test_requirements=("system_mocks", "no_real_power_actions")),
    _record("whatsapp", "communication", "WhatsApp Desktop/Web messaging and calls.", supported_intents=("whatsapp", "communication"), supported_actions=("open", "search_contact", "send_message", "start_voice_call", "start_video_call", "end_call"), safety_level="HIGH", current_status="metadata_only", legacy_delegate="AutomationService._execute_whatsapp_command_legacy", target_connector="WhatsAppDesktopConnector", action_safety=(("open", "LOW"), ("search_contact", "LOW"), ("send_message", "HIGH"), ("start_voice_call", "HIGH"), ("start_video_call", "HIGH"), ("end_call", "LOW")), protected_actions=("send_message", "start_voice_call", "start_video_call"), planned_phase="communication_extraction", test_requirements=("no_real_send", "no_real_calls", "confirmation_required")),
    _record("message", "communication", "External message preparation and sending.", supported_intents=("message", "send_message", "draft_message"), supported_actions=("prepare_message", "confirm_send", "send_message"), safety_level="HIGH", current_status="metadata_only", legacy_delegate="MessageActionService", action_safety=(("prepare_message", "LOW"), ("confirm_send", "HIGH"), ("send_message", "HIGH")), protected_actions=("confirm_send", "send_message"), planned_phase="communication_extraction", test_requirements=("confirmation_required", "no_real_send")),
    _record("contact", "contact", "Contact lookup and fuzzy resolution.", supported_intents=("contact", "contacts", "contact_resolution"), supported_actions=("resolve", "disambiguate", "alias"), safety_level="LOW", current_status="metadata_only", legacy_delegate="ContactMatchService", planned_phase="contact_memory", test_requirements=("clarification", "ttl")),
    _record("phone", "phone", "Phone command bridge.", supported_intents=("phone", "phone_command"), supported_actions=("call_contact", "end_call", "send_sms", "phone_bridge_status"), safety_level="HIGH", current_status="metadata_only", legacy_delegate="PhoneCommandService", action_safety=(("phone_bridge_status", "LOW"), ("end_call", "LOW"), ("call_contact", "HIGH"), ("send_sms", "HIGH")), protected_actions=("call_contact", "send_sms"), planned_phase="phone_connector", test_requirements=("no_real_call", "confirmation_required")),
    _record("caller_lookup", "phone", "Incoming caller identity and summary lookup.", supported_intents=("caller_lookup",), supported_actions=("lookup", "summarize"), safety_level="LOW", current_status="metadata_only", legacy_delegate="CallerLookupService", planned_phase="phone_connector", test_requirements=("cache", "privacy")),
    _record("stt", "voice", "Speech-to-text capture and transcription.", supported_intents=("stt", "speech_to_text", "transcribe_file", "transcribe_audio_bytes", "readiness"), supported_actions=("transcribe_file", "transcribe_audio_bytes", "readiness", "warmup"), safety_level="LOW", current_status="thin_wrapper", target_provider="NemoParakeetProvider", planned_phase="current", test_requirements=("fake_stt_provider", "no_microphone_required", "no_real_model_in_unit_tests")),
    _record("tts", "voice", "Text-to-speech output.", supported_intents=("tts", "text_to_speech"), supported_actions=("speak", "synthesize", "stop", "readiness", "thinking_audio"), safety_level="LOW", current_status="metadata_only", target_provider="edge_tts", planned_phase="voice_layer", test_requirements=("no_real_audio_required",)),
    _record("voice_identity", "security", "Voice identity workflow bridge for protected-only authorization.", supported_intents=("voice_identity", "face_identity"), supported_actions=("verify", "enroll_status"), safety_level="LOW", current_status="disabled", legacy_delegate="FaceIdentityService", planned_phase="security_readiness", test_requirements=("auth_mocks",)),
    _record("memory", "memory", "Personal and session memory.", supported_intents=("memory", "recall", "remember"), supported_actions=("remember", "recall", "forget", "context"), safety_level="LOW", current_status="metadata_only", legacy_delegate="PersonalMemoryService", target_repository="memory repository", planned_phase="memory_layer", test_requirements=("session_isolation",)),
    _record("reminder", "reminder", "Reminder parsing and scheduling.", supported_intents=("reminder", "create_reminder"), supported_actions=("create", "list", "cancel", "update"), safety_level="MEDIUM", current_status="metadata_only", legacy_delegate="ReminderService", planned_phase="memory_layer", test_requirements=("time_mocks",)),
    _record("task_status", "memory", "Background task status tracking.", supported_intents=("task_status",), supported_actions=("status", "cancel", "list"), safety_level="LOW", current_status="disabled", legacy_delegate="TaskManager", planned_phase="task_layer", test_requirements=("task_mocks",)),
    _record("research", "research", "Search and research workflows.", supported_intents=("research", "realtime_search"), supported_actions=("web_search", "web_fetch", "compare_sources", "answer_with_sources", "summarize_sources"), safety_level="LOW", current_status="metadata_only", legacy_delegate="ResearchToolsService", target_provider="search provider", planned_phase="research_layer", test_requirements=("provider_mocks",)),
    _record("summary", "research", "Summarization over text or tool outputs.", supported_intents=("summary", "summarize"), supported_actions=("summarize", "extract_key_points", "make_notes"), safety_level="LOW", current_status="thin_wrapper", target_adapter="Summarizer provider", planned_phase="current", test_requirements=("fake_summarizer", "no_live_provider_required")),
    _record("youtube", "media", "YouTube transcript and media helpers.", supported_intents=("youtube", "youtube_search", "youtube_summary"), supported_actions=("search", "play", "transcript", "summarize"), safety_level="LOW", current_status="metadata_only", legacy_delegate="YouTubeToolsService", planned_phase="media_layer", test_requirements=("provider_mocks",)),
    _record("vision", "media", "Vision and image description.", supported_intents=("vision", "image_description"), supported_actions=("describe", "inspect", "extract_text"), safety_level="LOW", current_status="metadata_only", legacy_delegate="VisionService", target_adapter="vision provider", planned_phase="vision_layer", test_requirements=("image_mocks",)),
    _record(
        "app_interaction",
        "ui_automation",
        "Typing and interaction inside active apps through an injectable UI adapter.",
        supported_intents=("app_interaction", "type_text", "type_into_active_field", "press_safe_key", "press_key", "press_hotkey"),
        supported_actions=(
            "type_text",
            "type_into_active_field",
            "append_text",
            "press_safe_key",
            "press_key",
            "press_hotkey",
            "select_address_bar",
            "submit_current_field",
            "clear_current_field",
            "replace_current_field",
            "copy_selection",
            "paste_text",
            "select_all",
            "undo",
            "redo",
            "open_new_tab",
            "close_current_tab",
            "browser_back",
            "browser_forward",
            "refresh",
            "click_text",
            "click_coordinates",
            "verify_text_present",
        ),
        safety_level="MEDIUM",
        current_status="thin_wrapper",
        target_adapter="PywinautoAdapter",
        action_safety=(
            ("type_text", "MEDIUM"),
            ("type_into_active_field", "MEDIUM"),
            ("append_text", "MEDIUM"),
            ("press_safe_key", "LOW"),
            ("press_key", "MEDIUM"),
            ("press_hotkey", "MEDIUM"),
            ("select_address_bar", "LOW"),
            ("submit_current_field", "MEDIUM"),
            ("clear_current_field", "MEDIUM"),
            ("replace_current_field", "MEDIUM"),
            ("copy_selection", "LOW"),
            ("paste_text", "MEDIUM"),
            ("select_all", "LOW"),
            ("undo", "MEDIUM"),
            ("redo", "MEDIUM"),
            ("open_new_tab", "LOW"),
            ("close_current_tab", "HIGH"),
            ("browser_back", "LOW"),
            ("browser_forward", "LOW"),
            ("refresh", "LOW"),
            ("click_text", "HIGH"),
            ("click_coordinates", "HIGH"),
            ("verify_text_present", "LOW"),
        ),
        planned_phase="current",
        test_requirements=("no_real_keyboard_mouse", "adapter_mocks", "coordinates_disabled_by_default"),
    ),
    _record("window", "ui_automation", "Window focus, movement, and layout.", supported_intents=("window", "window_control"), supported_actions=("focus", "switch", "minimize", "maximize", "close"), safety_level="HIGH", current_status="metadata_only", target_connector="ComputerControlService", planned_phase="ui_automation_layer", test_requirements=("window_mocks",)),
    _record("keyboard_mouse", "ui_automation", "Keyboard and mouse automation.", supported_intents=("keyboard_mouse", "hotkey", "mouse"), supported_actions=("hotkey", "type", "click", "scroll"), safety_level="HIGH", current_status="metadata_only", target_connector="ComputerControlService", planned_phase="ui_automation_layer", test_requirements=("no_real_keyboard_mouse",)),
    _record("clipboard", "ui_automation", "Clipboard read and write actions.", supported_intents=("clipboard",), supported_actions=("read", "write", "paste"), safety_level="MEDIUM", current_status="metadata_only", target_connector="ComputerControlService", planned_phase="ui_automation_layer", test_requirements=("clipboard_mocks",)),
    _record("screenshot", "ui_automation", "Screenshot capture.", supported_intents=("screenshot",), supported_actions=("capture", "save"), safety_level="LOW", current_status="metadata_only", target_connector="ComputerControlService", planned_phase="vision_layer", test_requirements=("screenshot_mocks",)),
    _record("wake_on_lan", "device", "Wake-on-LAN device command.", supported_intents=("wake_on_lan",), supported_actions=("wake",), safety_level="MEDIUM", current_status="metadata_only", legacy_delegate="WakeOnLanService", target_connector="network device connector", planned_phase="device_layer", test_requirements=("packet_mocks",)),
    _record("network", "network", "Safe network information.", supported_intents=("network",), supported_actions=("status", "ping", "scan_safe"), safety_level="LOW", current_status="metadata_only", target_connector="network connector", planned_phase="device_layer", test_requirements=("network_mocks",)),
    _record("safe_command_info", "system", "Safe read-only command information.", supported_intents=("safe_command_info",), supported_actions=("explain", "lookup"), safety_level="LOW", current_status="metadata_only", legacy_delegate="SafeCommandInfoService", planned_phase="system_tooling", test_requirements=("allowed_map",)),
    _record("project", "developer", "Project inspection and navigation.", supported_intents=("project",), supported_actions=("open", "inspect", "status"), safety_level="LOW", current_status="metadata_only", target_repository="project repository", planned_phase="developer_layer", test_requirements=("repo_mocks",)),
    _record("terminal", "developer", "Terminal command proposal and execution boundary.", supported_intents=("terminal", "shell"), supported_actions=("run_command", "stop_command"), safety_level="CRITICAL", current_status="metadata_only", action_safety=(("run_command", "CRITICAL"), ("stop_command", "CRITICAL"), ("execute", "CRITICAL")), protected_actions=("run_command", "stop_command", "execute"), planned_phase="developer_layer", test_requirements=("no_real_shell", "confirmation_required")),
    _record("code_search", "developer", "Code search and navigation.", supported_intents=("code_search",), supported_actions=("search", "open_result"), safety_level="LOW", current_status="metadata_only", target_repository="project repository", planned_phase="developer_layer", test_requirements=("repo_mocks",)),
    _record("code_edit", "developer", "Code editing and patch application.", supported_intents=("code_edit",), supported_actions=("propose_patch", "apply_patch", "revert_patch"), safety_level="CRITICAL", current_status="metadata_only", action_safety=(("propose_patch", "MEDIUM"), ("apply_patch", "CRITICAL"), ("revert_patch", "CRITICAL")), protected_actions=("apply_patch", "revert_patch"), planned_phase="developer_layer", test_requirements=("no_unconfirmed_edits", "confirmation_required")),
    _record("game", "domain", "Game/store/install command handling.", supported_intents=("game",), supported_actions=("open", "install", "launch"), safety_level="MEDIUM", current_status="metadata_only", legacy_delegate="GameService", planned_phase="domain_layer", test_requirements=("store_mocks",)),
)

TOOL_INVENTORY_BY_NAME = {record.name: record for record in TOOL_INVENTORY}


def get_tool_inventory() -> tuple[ToolInventoryRecord, ...]:
    return TOOL_INVENTORY


def get_tool_inventory_record(name: str) -> ToolInventoryRecord | None:
    return TOOL_INVENTORY_BY_NAME.get(str(name or "").strip().lower())


def build_readiness_tool_registry(live_tools: Iterable[AutomationTool] | None = None) -> ToolRegistry:
    live_by_name = {str(getattr(tool, "name", "")).strip().lower(): tool for tool in live_tools or []}
    tools: list[AutomationTool] = []
    for record in TOOL_INVENTORY:
        if record.name == "summary":
            default_tool: AutomationTool = SummaryTool()
        elif record.name == "stt":
            default_tool = STTTool()
        elif record.name == "app_interaction":
            default_tool = AppInteractionTool()
        elif record.current_status == "disabled":
            default_tool = DisabledTool(record)
        else:
            default_tool = MetadataTool(record)
        tools.append(live_by_name.pop(record.name, default_tool))
    tools.extend(live_by_name.values())
    return ToolRegistry(tools)
