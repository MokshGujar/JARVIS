import logging
import re
import time
import uuid
from pathlib import Path
from typing import Callable, Dict, Iterable

from config import BASE_DIR
from app.orchestrator.automation_context import AutomationContext
from app.services.browser_control_service import BrowserControlService
from app.services.computer_control_service import ComputerControlService
from app.services.computer_settings_service import ComputerSettingsService
from app.services.contact_match_service import ContactCandidate, ContactMatchService
from app.services.contact_resolution_service import ContactResolutionService
from app.services.game_service import GameService
from app.services.message_action_service import MessageActionService
from app.services.automation_context_builder import AutomationContextBuilder
from app.services.automation_response_formatter import AutomationFacadeResponseFormatter
from app.services.automation_path_aliases import build_user_path_aliases
from app.services.pending_confirmation_service import PendingConfirmationService
from app.tools.app_browser_domain_helper import AutomationAppBrowserCompatibility
from app.tools.automation_facade_router import AutomationFacadeRouter
from app.tools.file_domain_helper import AutomationFileCompatibility
from app.tools.system_domain_helper import AutomationSystemCompatibility
from app.tools.whatsapp_domain_helper import AutomationWhatsAppCompatibility
from app.services.safe_command_info_service import SafeCommandInfoService
from app.services.youtube_tools_service import YouTubeToolsService
from app.services.whatsapp_desktop_automation import WhatsAppDesktopAutomation
from app.connectors.browser_connector import BrowserConnector
from app.connectors.local_app_connector import LocalAppConnector
from app.connectors.local_files_connector import LocalFilesConnector
from app.connectors.youtube_connector import YouTubeConnector
from app.orchestrator.main_orchestrator import MainOrchestrator
from app.orchestrator.tool_registry import ToolRegistry

try:
    from send2trash import send2trash
    SEND2TRASH_IMPORT_ERROR = None
except Exception as exc:
    send2trash = None
    SEND2TRASH_IMPORT_ERROR = exc


logger = logging.getLogger("J.A.R.V.I.S")


class AutomationService:
    OPEN_PREFIXES = ("open ", "launch ", "start ")
    CLOSE_PREFIXES = ("close ", "kill ")
    PLAY_PREFIXES = ("play ",)
    TYPE_PREFIXES = ("type ", "paste ")
    GOOGLE_SEARCH_PREFIXES = ("google search ", "search google for ")
    YOUTUBE_SEARCH_PREFIXES = ("youtube search ", "search youtube for ")
    CREATE_FILE_PREFIXES = ("create file ", "make file ")
    CREATE_FOLDER_PREFIXES = ("create folder ", "make folder ", "create directory ", "make directory ")
    UPDATE_FILE_VERBS = ("add", "write", "append", "put", "insert")
    DELETE_FILE_PREFIXES = ("delete file ", "remove file ")
    DELETE_FOLDER_PREFIXES = ("delete folder ", "remove folder ", "delete directory ", "remove directory ")
    MOVE_PREFIXES = ("move ",)
    RENAME_PREFIXES = ("rename ",)

    APP_ALIASES = {
        "calc": "calculator",
        "calculator": "calculator",
        "cmd": "command prompt",
        "command prompt": "command prompt",
        "chrome": "google chrome",
        "edge": "microsoft edge",
        "efootball": "efootball",
        "e football": "efootball",
        "football": "efootball",
        "explorer": "file explorer",
        "file explorer": "file explorer",
        "google chrome": "google chrome",
        "notepad": "notepad",
        "paint": "paint",
        "spotify": "spotify",
        "terminal": "windows terminal",
        "visual studio code": "visual studio code",
        "vscode": "visual studio code",
        "vs code": "visual studio code",
        "whatsapp": "whatsapp",
        "whats app": "whatsapp",
        "telegram": "telegram",
        "steam": "steam",
        "epic games": "epic games launcher",
        "epic games launcher": "epic games launcher",
        "word": "microsoft word",
        "ms word": "microsoft word",
        "excel": "microsoft excel",
        "powerpoint": "microsoft powerpoint",
        "outlook": "microsoft outlook",
        "settings app": "settings",
        "snipping tool": "snipping tool",
        "windows terminal": "windows terminal",
    }

    WEB_ALIASES = {
        "youtube": "https://www.youtube.com",
        "google": "https://www.google.com",
        "gmail": "https://mail.google.com",
        "chrome": "https://www.google.com/chrome/",
        "google chrome": "https://www.google.com/chrome/",
        "edge": "https://www.microsoft.com/edge",
        "microsoft edge": "https://www.microsoft.com/edge",
        "spotify": "https://open.spotify.com",
        "whatsapp": "https://web.whatsapp.com",
        "discord": "https://discord.com/app",
        "notion": "https://www.notion.so",
        "figma": "https://www.figma.com",
        "canva": "https://www.canva.com",
    }

    AMBIGUOUS_OPEN_TARGETS = {
        "chrome": {
            "app_target": "chrome",
            "website_url": "https://www.google.com/chrome/",
            "website_name": "the Chrome website",
            "app_name": "the Chrome app",
        },
        "google chrome": {
            "app_target": "google chrome",
            "website_url": "https://www.google.com/chrome/",
            "website_name": "the Chrome website",
            "app_name": "the Chrome app",
        },
        "edge": {
            "app_target": "edge",
            "website_url": "https://www.microsoft.com/edge",
            "website_name": "the Edge website",
            "app_name": "the Edge app",
        },
        "microsoft edge": {
            "app_target": "microsoft edge",
            "website_url": "https://www.microsoft.com/edge",
            "website_name": "the Edge website",
            "app_name": "the Edge app",
        },
        "spotify": {
            "app_target": "spotify",
            "website_url": "https://open.spotify.com",
            "website_name": "Spotify Web",
            "app_name": "the Spotify app",
        },
        "whatsapp": {
            "app_target": "whatsapp",
            "website_url": "https://web.whatsapp.com",
            "website_name": "WhatsApp Web",
            "app_name": "the WhatsApp app",
        },
        "discord": {
            "app_target": "discord",
            "website_url": "https://discord.com/app",
            "website_name": "Discord Web",
            "app_name": "the Discord app",
        },
        "notion": {
            "app_target": "notion",
            "website_url": "https://www.notion.so",
            "website_name": "the Notion website",
            "app_name": "the Notion app",
        },
        "figma": {
            "app_target": "figma",
            "website_url": "https://www.figma.com",
            "website_name": "the Figma website",
            "app_name": "the Figma app",
        },
        "canva": {
            "app_target": "canva",
            "website_url": "https://www.canva.com",
            "website_name": "the Canva website",
            "app_name": "the Canva app",
        },
    }

    DIRECT_OPEN_URIS = {
        "edge": "microsoft-edge:",
        "microsoft edge": "microsoft-edge:",
        "spotify": "spotify:",
        "settings": "ms-settings:",
        "settings app": "ms-settings:",
        "windows settings": "ms-settings:",
    }

    DIRECT_CLOSE_EXECUTABLES = {
        "chrome": "chrome.exe",
        "google chrome": "chrome.exe",
        "edge": "msedge.exe",
        "microsoft edge": "msedge.exe",
        "spotify": "spotify.exe",
        "file explorer": "explorer.exe",
        "explorer": "explorer.exe",
    }

    DIRECT_OPEN_COMMANDS = {
        "chrome": ["chrome"],
        "google chrome": ["chrome"],
        "file explorer": ["explorer.exe"],
        "explorer": ["explorer.exe"],
        "notepad": ["notepad.exe"],
        "paint": ["mspaint.exe"],
        "spotify": ["spotify"],
        "calculator": ["calc.exe"],
        "task manager": ["taskmgr.exe"],
        "snipping tool": ["snippingtool.exe"],
    }

    DANGEROUS_COMMAND_RE = re.compile(
        r"\b("
        r"shutdown|shut\s+down|restart|reboot|power\s+off|format|diskpart|"
        r"regedit|registry|delete\s+system|remove\s+system|rm\s+-rf|"
        r"taskkill|kill\s+process|stop\s+process|disable\s+defender|"
        r"turn\s+off\s+defender|bcdedit|cipher|takeown|icacls"
        r")\b",
        re.IGNORECASE,
    )

    PROTECTED_PATH_PREFIXES = tuple(
        Path(path)
        for path in (
            r"C:\Windows",
            r"C:\Program Files",
            r"C:\Program Files (x86)",
            r"C:\ProgramData",
            r"C:\Recovery",
            r"C:\System Volume Information",
            r"C:\$Recycle.Bin",
            r"C:\PerfLogs",
        )
    )

    PROTECTED_PATH_PATTERNS = (
        re.compile(r"^[a-z]:\\users\\[^\\]+\\appdata(?:\\|$)", re.IGNORECASE),
        re.compile(r"^[a-z]:\\users\\public(?:\\|$)", re.IGNORECASE),
        re.compile(r"^[a-z]:\\\$windows\.\~bt(?:\\|$)", re.IGNORECASE),
        re.compile(r"^[a-z]:\\\$windows\.\~ws(?:\\|$)", re.IGNORECASE),
    )

    PROTECTED_APP_KEYWORDS = {
        "cmd",
        "command prompt",
        "powershell",
        "windows powershell",
        "terminal",
        "windows terminal",
        "regedit",
        "registry editor",
        "task manager",
        "services",
        "service manager",
        "device manager",
        "control panel",
        "settings",
        "system settings",
        "windows security",
        "defender",
        "local security policy",
        "group policy",
    }

    USER_PATH_ALIASES = build_user_path_aliases()

    def __init__(self, groq_service=None):
        self._pending_delete_target: Path | None = None
        self._pending_open_target: dict | None = None
        self._pending_browser_search: dict | None = None
        self._pending_create_file: dict | None = None
        self._pending_incomplete_command: dict | None = None
        self._pending_mark_action: dict | None = None
        self._pending_whatsapp_clarification: dict | None = None
        self._pending_dry_run_plan: dict | None = None
        self._pending_confirmation_service = PendingConfirmationService()
        self._context_builder = AutomationContextBuilder()
        self._response_formatter = AutomationFacadeResponseFormatter()
        self._session_pending_state = self._pending_confirmation_service.session_state
        self._automation_context_store = self._context_builder.store
        self._active_automation_context: AutomationContext | None = None
        self._confirmation_prompt_emitted_ids = self._pending_confirmation_service.emitted_prompt_ids
        self._last_browser_choice: str | None = None
        self._browser_session_id = f"browser-{uuid.uuid4().hex[:10]}"
        self._last_file_target: Path | None = None
        self._last_folder_target: Path | None = None
        self._last_file_search_results: list[dict] = []
        self._last_selected_file_path: Path | None = None
        self._last_web_target: str | None = None
        self._last_youtube_query: str | None = None
        self._last_google_query: str | None = None
        self.file_domain = AutomationFileCompatibility(self)
        self.app_browser_domain = AutomationAppBrowserCompatibility(self)
        self.system_domain = AutomationSystemCompatibility(self)
        self.whatsapp_domain = AutomationWhatsAppCompatibility(self)
        self._facade_router = AutomationFacadeRouter(self)
        self.computer_control_service = ComputerControlService()
        self.computer_settings_service = ComputerSettingsService(self.computer_control_service)
        self.browser_control_service = BrowserControlService()
        self.local_app_connector = LocalAppConnector(self.browser_control_service)
        self.local_files_connector = LocalFilesConnector()
        self._appopener_available = self.local_app_connector.appopener_available
        self.contact_match_service = ContactMatchService()
        self._whatsapp_contacts_provider: Callable[[], Iterable[ContactCandidate]] | None = None
        self.contact_resolution_service = ContactResolutionService(
            contacts_provider=lambda: self._load_communication_contacts(),
            contact_match_service=self.contact_match_service,
        )
        self._active_whatsapp_call: dict | None = None
        self.whatsapp_desktop = WhatsAppDesktopAutomation()
        self.youtube_tools_service = YouTubeToolsService(
            groq_service=groq_service,
            youtube_connector=YouTubeConnector(BrowserConnector(self.browser_control_service)),
        )
        self.game_service = GameService()
        self.safe_command_info_service = SafeCommandInfoService()
        self.message_action_service = MessageActionService()
        self._active_session_id: str | None = None
        self._active_turn_id: str | None = None
        self._active_request_source = "user"
        self._active_step_up_verified = False

    def has_pending_delete_confirmation(self) -> bool:
        return self._pending_delete_target is not None

    def has_pending_open_clarification(self) -> bool:
        return self._pending_open_target is not None

    def has_pending_browser_search(self) -> bool:
        if self._pending_browser_search is None:
            return False
        expires_at = float(self._pending_browser_search.get("expires_at") or 0)
        if expires_at and time.time() > expires_at:
            self._pending_browser_search = None
            return False
        return True

    def has_pending_create_file_location(self) -> bool:
        return self._pending_create_file is not None

    def has_pending_mark_confirmation(self) -> bool:
        return self._pending_mark_action is not None

    def has_pending_whatsapp_clarification(self) -> bool:
        return self._pending_whatsapp_clarification is not None

    def set_whatsapp_contacts_provider(self, provider: Callable[[], Iterable[ContactCandidate]] | None) -> None:
        self._whatsapp_contacts_provider = provider

    def _load_communication_contacts(self) -> Iterable[ContactCandidate]:
        if self._whatsapp_contacts_provider is None:
            return []
        return list(self._whatsapp_contacts_provider() or [])

    def looks_like_confirmation_response(self, command: str) -> bool:
        text = self.app_browser_domain._normalize_spoken_command(command).lower()
        return text in {"yes", "y", "no", "n", "delete it", "go ahead", "cancel", "confirm"}

    def stages_high_risk_confirmation(self, command: str) -> bool:
        text = self.app_browser_domain._normalize_spoken_command(command).lower()
        if re.match(r"^(?:delete|remove)(?:\s+the)?\s+(?:file|folder|directory)\s+.+", text):
            return True
        if self.whatsapp_domain._looks_like_send_message(text):
            return True
        if self.whatsapp_domain._extract_whatsapp_call_intent(text) is not None:
            return True
        for part in self.app_browser_domain._split_compound_commands(text):
            if part != text and self.whatsapp_domain._extract_whatsapp_call_intent(part) is not None:
                return True
        return False

    def pending_authorization_text(self, confirmation: str) -> str | None:
        reply = self.app_browser_domain._normalize_spoken_command(confirmation).lower()
        if reply not in {"yes", "y", "go ahead", "confirm", "delete it", "do it", "proceed"}:
            return None
        if self._pending_delete_target is not None:
            return f"delete {self._pending_delete_target}"
        if self._pending_mark_action is not None:
            pending = self._pending_mark_action
            payload = dict(pending.get("payload") or {})
            if pending.get("kind") == "send_message":
                return (
                    f"send {payload.get('platform', 'message')} message "
                    f"to {payload.get('receiver', '')} saying {payload.get('message', '')}"
                ).strip()
            if pending.get("kind") == "whatsapp_call":
                return f"{payload.get('mode', 'voice')} call {payload.get('contact', '')} on whatsapp".strip()
            if pending.get("kind") == "game":
                return str(payload.get("description") or payload.get("action") or "game action")
        return None

    def looks_like_open_clarification_response(self, command: str) -> bool:
        text = self.app_browser_domain._normalize_spoken_command(command).lower()
        return any(
            phrase in text
            for phrase in (
                "app",
                "application",
                "desktop app",
                "desktop",
                "website",
                "web site",
                "site",
                "web app",
                "the app",
                "the website",
            )
        )

    def looks_like_automation_request(self, command: str) -> bool:
        lowered = self.app_browser_domain._normalize_spoken_command(command).lower()
        if not lowered:
            return False

        if self.DANGEROUS_COMMAND_RE.search(lowered):
            return True

        if self.has_pending_mark_confirmation() and self.looks_like_confirmation_response(command):
            return True

        if self.has_pending_whatsapp_clarification():
            return True

        if self.has_pending_delete_confirmation() and self.looks_like_confirmation_response(command):
            return True

        if self.has_pending_open_clarification() and self.looks_like_open_clarification_response(command):
            return True

        if self.has_pending_browser_search():
            return True

        if self.has_pending_create_file_location():
            return True

        if self._has_pending_incomplete_command():
            return True

        if self._has_pending_dry_run_plan() and lowered in {"yes", "y", "do it", "confirm", "go ahead", "proceed", "no", "n", "cancel", "stop"}:
            return True

        if self._looks_like_subject_context_command(lowered):
            return True

        if self._looks_like_contextual_browser_followup(lowered):
            return True

        if re.match(
            r"^(?:can\s+you\s+)?(?:please\s+)?search\s+(?:a\s+)?file(?:\s+for\s+me)?[.!?]*$|"
            r"^(?:search\s+(?:my\s+)?files?|search\s+local\s+files?|search\s+in\s+files?|"
            r"look\s+in\s+my\s+files?|look\s+for\s+(?:a\s+)?file|search\s+(?:my\s+)?(?:laptop|computer|pc)|"
            r"search\s+(?:desktop|documents|downloads|home)|find\s+(?:recent|recently|latest|newest|large|largest|biggest)|"
            r"find\s+.+?\s+on\s+(?:my\s+)?(?:laptop|computer|pc))\b",
            lowered,
        ):
            return True

        if (self._last_file_search_results or self._last_file_target is not None) and re.match(
            r"^(?:open|read|show|display|summarize|explain|where\s+is|show\s+(?:me\s+)?(?:the\s+)?path).*\b(?:it|that|this|first|second|third|fourth|fifth|last|\d)\b[.!?]*$",
            lowered,
        ):
            return True

        if re.match(
            r"^(?:where\s+is\s+(?:it|that|that\s+file|the\s+file)|show\s+(?:me\s+)?(?:the\s+)?full\s+path|copy\s+(?:the\s+)?path)[.!?]*$",
            lowered,
        ):
            return self._last_file_target is not None

        if lowered.startswith(
            self.OPEN_PREFIXES
            + self.CLOSE_PREFIXES
            + self.PLAY_PREFIXES
            + self.TYPE_PREFIXES
            + self.GOOGLE_SEARCH_PREFIXES
            + self.YOUTUBE_SEARCH_PREFIXES
            + self.CREATE_FILE_PREFIXES
            + self.DELETE_FILE_PREFIXES
            + self.CREATE_FOLDER_PREFIXES
            + self.DELETE_FOLDER_PREFIXES
            + self.MOVE_PREFIXES
            + self.RENAME_PREFIXES
        ):
            return True

        if lowered in {"mute", "unmute", "volume up", "volume down"} or self.system_domain._looks_like_local_system_status(lowered):
            return True

        if self._looks_like_mark_request(lowered):
            return True

        if re.search(r"\b(?:gmail|email|mail)\b", lowered) and re.search(r"\b(?:send|draft|compose|write|reply|search|read|unread)\b", lowered):
            return True

        if re.match(r"^(?:show me|display|open)\s+(?:that|the)\s+(?:file|folder|directory|item)\b", lowered):
            return True

        if re.match(r"^(?:in\s+)?(?:that|the)\s+folder\b.*\b(?:add|create|make)\s+(?:a\s+)?file\b", lowered):
            return True

        return bool(re.match(
            r"^(?:open|launch|start|close|kill|play|type|paste|create|make|"
            r"delete|remove|move|rename|google search|youtube search|search google|"
            r"search youtube|search web|search about|system status|system update|system report|system health|"
            r"mute|unmute|volume up|volume down|turn volume|"
            r"show desktop|switch window|switch app|next window|close this window|"
            r"close current window|minimize|fullscreen|full screen|list files|"
            r"show files|read file|find files|find pdf|find pdfs|search a file|search files|search my files|search my laptop|search local files|show largest|"
            r"largest files|organize folder|preview organize)\b",
            lowered,
        ))

    def looks_like_semantic_request(self, command: str, *, session_id: str | None = None) -> bool:
        context = self._automation_context_for(session_id)
        if self._looks_like_semantic_confirmation_turn(command, context=context):
            return True
        if self.whatsapp_domain._looks_like_whatsapp_command(str(command or "").strip().lower()):
            logger.info("[SEMANTIC] fallback=legacy reason=existing_whatsapp_router")
            return False
        probe_orchestrator = MainOrchestrator(registry=ToolRegistry(), enforce_policy=False)
        adapter = probe_orchestrator.semantic_adapter
        if not adapter.enabled or not adapter.safe_execution_enabled:
            logger.info("[SEMANTIC] fallback=legacy reason=no_semantic_claim")
            return False
        result = adapter.peek_live_claim(command, context=context)
        if result is None:
            logger.info("[SEMANTIC] fallback=legacy reason=no_semantic_claim")
            return False
        actions = list(getattr(result, "semantic_actions", []) or [])
        intent = actions[0].intent.value if actions else "unknown"
        missing_fields = list(getattr(result, "missing_fields", []) or [])
        context_label = self._semantic_context_label(actions[0] if actions else None, context)
        if missing_fields:
            logger.info("[SEMANTIC] blocked reason=missing_context")
        else:
            logger.info("[SEMANTIC] claimed=true intent=%s context=%s", intent, context_label)
        return True

    @staticmethod
    def _looks_like_semantic_confirmation_turn(command: str, *, context: AutomationContext | None) -> bool:
        pending = context.last_confirmation_request if context is not None else None
        lowered = re.sub(r"\s+", " ", str(command or "").strip().lower()).strip(" .!?")
        if pending is not None and pending.status == "pending":
            return bool(
                lowered in {
                    "yes",
                    "y",
                    "yes do it",
                    "do it",
                    "confirm",
                    "send it",
                    "now send it",
                    "delete it",
                    "close it",
                    "run it",
                    "go ahead",
                    "proceed",
                    "no",
                    "n",
                    "cancel",
                    "cancel that",
                    "stop",
                    "never mind",
                    "don't",
                    "dont",
                    "don't send",
                    "dont send",
                    "don't delete",
                    "dont delete",
                }
                or lowered.startswith("change ")
                or "other one" in lowered
            )
        return lowered in {"yes", "y", "yes do it", "do it", "confirm", "go ahead", "proceed", "no", "n", "cancel", "cancel that"}

    def execute(
        self,
        command: str,
        *,
        session_id: str | None = None,
        turn_id: str | None = None,
        step_up_verified: bool = False,
        source: str = "user",
    ) -> Dict[str, object]:
        if not str(command or "").strip():
            return {
                "success": False,
                "action": "empty_transcript",
                "message": "",
                "display_text": "",
                "spoken_text": "",
            }
        if session_id:
            self._load_session_pending_state(session_id)
        request_context = self._context_builder.build(command, session_id=session_id, turn_id=turn_id)
        previous_context = self._active_automation_context
        previous_session_id = self._active_session_id
        previous_turn_id = self._active_turn_id
        previous_request_source = self._active_request_source
        previous_step_up_verified = self._active_step_up_verified
        self._active_automation_context = request_context.automation_context
        self._active_session_id = session_id
        self._active_turn_id = turn_id
        self._active_request_source = str(source or "user").strip().lower() or "user"
        self._active_step_up_verified = bool(step_up_verified)
        try:
            previous_confirmation_keys = self._active_confirmation_prompt_keys(session_id)
            result = self._response_formatter.normalize(self._execute_facade(request_context.command))
            current_confirmation_keys = self._active_confirmation_prompt_keys(session_id)
            self._clear_stale_confirmation_prompts(previous_confirmation_keys, current_confirmation_keys)
            result = self._dedupe_confirmation_prompt(result, session_id=session_id)
            if session_id:
                self._save_session_pending_state(session_id)
            return result
        finally:
            self._active_automation_context = previous_context
            self._active_session_id = previous_session_id
            self._active_turn_id = previous_turn_id
            self._active_request_source = previous_request_source
            self._active_step_up_verified = previous_step_up_verified

    def _automation_context_for(self, session_id: str | None) -> AutomationContext | None:
        return self._context_builder.get_context(session_id)

    def _load_session_pending_state(self, session_id: str) -> None:
        self._pending_confirmation_service.load_into(self, session_id)

    def _save_session_pending_state(self, session_id: str) -> None:
        self._pending_confirmation_service.save_from(self, session_id)

    def _confirmation_scope_key(self, pending_action_id: str, session_id: str | None) -> str:
        return self._pending_confirmation_service.confirmation_scope_key(pending_action_id, session_id)

    def _pending_action_id(self, kind: str, payload: object) -> str:
        return self._pending_confirmation_service.pending_action_id(kind, payload)

    def _active_pending_confirmation_id(self) -> str | None:
        return self._pending_confirmation_service.active_pending_confirmation_id(self)

    def _active_confirmation_prompt_keys(self, session_id: str | None) -> set[str]:
        return self._pending_confirmation_service.active_confirmation_prompt_keys(self, session_id)

    def _clear_stale_confirmation_prompts(self, previous_keys: set[str], current_keys: set[str]) -> None:
        self._pending_confirmation_service.clear_stale_confirmation_prompts(previous_keys, current_keys)

    def _dedupe_confirmation_prompt(self, result: dict[str, object], *, session_id: str | None) -> dict[str, object]:
        return self._pending_confirmation_service.dedupe_confirmation_prompt(self, result, session_id=session_id)

    def _is_repeat_confirmation_prompt_result(self, result: dict[str, object]) -> bool:
        return self._pending_confirmation_service.is_repeat_confirmation_prompt_result(result)

    def _is_confirmation_prompt_result(self, result: dict[str, object]) -> bool:
        return self._pending_confirmation_service.is_confirmation_prompt_result(result)

    def _has_pending_incomplete_command(self):
        return self._facade_router._has_pending_incomplete_command()

    def _has_pending_dry_run_plan(self):
        return self._facade_router._has_pending_dry_run_plan()

    def _handle_pending_dry_run_response(self, text):
        return self._facade_router._handle_pending_dry_run_response(text)

    def _stage_incomplete_command(self, kind, template, prompt):
        return self._facade_router._stage_incomplete_command(kind, template, prompt)

    def _detect_incomplete_command(self, text):
        return self._facade_router._detect_incomplete_command(text)

    def _handle_incomplete_command_followup(self, text):
        return self._facade_router._handle_incomplete_command_followup(text)

    def _looks_like_new_automation_command(self, lowered):
        return self._facade_router._looks_like_new_automation_command(lowered)

    def _handle_subject_context_command(self, command):
        return self._facade_router._handle_subject_context_command(command)

    def _looks_like_subject_context_command(self, lowered):
        return self._facade_router._looks_like_subject_context_command(lowered)

    def _looks_like_contextual_browser_followup(self, lowered):
        return self._facade_router._looks_like_contextual_browser_followup(lowered)

    def _rewrite_contextual_followup(self, command):
        return self._facade_router._rewrite_contextual_followup(command)

    def _execute_facade(self, command):
        return self._facade_router._execute_facade(command)

    def _build_automation_tool_registry(self):
        return self._facade_router._build_automation_tool_registry()

    def _execute_canonical_command(self, command):
        return self._facade_router._execute_canonical_command(command)

    def _execute_tool_with_orchestrator(self, command, *, expected_tool):
        return self._facade_router._execute_tool_with_orchestrator(command, expected_tool=expected_tool)

    def _stage_delete_target_for_confirmation(self, command):
        return self._facade_router._stage_delete_target_for_confirmation(command)

    def _execute_multistep_tool_plan(self, command):
        return self._facade_router._execute_multistep_tool_plan(command)

    def _semantic_context_label(self, action, context):
        return self._facade_router._semantic_context_label(action, context)

    def _execute_file_tool(self, command):
        return self._facade_router._execute_file_tool(command)

    def _execute_browser_tool(self, command):
        return self._facade_router._execute_browser_tool(command)

    def _execute_app_tool(self, command):
        return self._facade_router._execute_app_tool(command)

    def _execute_system_tool(self, command):
        return self._facade_router._execute_system_tool(command)

    def _preflight_create_file_location(self, command):
        return self._facade_router._preflight_create_file_location(command)

    def _execute_create_plan_if_safe_scoped(self, command):
        return self._facade_router._execute_create_plan_if_safe_scoped(command)

    def _execute_planned_file_steps(self, command, steps):
        return self._facade_router._execute_planned_file_steps(command, steps)

    def _looks_like_mark_request(self, lowered):
        return self._facade_router._looks_like_mark_request(lowered)

    def _execute_mark_request(self, command):
        return self._facade_router._execute_mark_request(command)

    def diagnostics(self) -> Dict[str, str | bool]:
        return {
            "appopener_available": self._appopener_available,
            "appopener_error": "" if self.local_app_connector.appopener_error is None else str(self.local_app_connector.appopener_error),
            "send2trash_available": send2trash is not None,
            "send2trash_error": "" if SEND2TRASH_IMPORT_ERROR is None else str(SEND2TRASH_IMPORT_ERROR),
        }

