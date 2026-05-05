import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import time
import urllib.parse
import webbrowser
import uuid
from pathlib import Path
from typing import Callable, Dict, Iterable

from config import AUTOMATION_CONTEXT_ENABLED, BASE_DIR
from app.orchestrator.automation_context import AutomationContext, AutomationContextStore
from app.services.browser_control_service import BrowserControlService
from app.services.computer_control_service import ComputerControlService
from app.services.computer_settings_service import ComputerSettingsService
from app.services.contact_match_service import ContactCandidate, ContactMatchService
from app.services.game_service import GameService
from app.services.message_action_service import MessageActionService
from app.services.automation_response import normalize_automation_response
from app.services.safe_command_info_service import SafeCommandInfoService
from app.services.youtube_tools_service import YouTubeToolsService
from app.services.whatsapp_desktop_automation import WhatsAppDesktopAutomation
from app.connectors.browser_connector import BrowserConnector
from app.tools.base import ToolContext
from app.tools.app_tool import AppTool
from app.tools.app_launcher_tool import AppLauncherTool
from app.tools.app_interaction_tool import AppInteractionTool
from app.tools.browser_tool import BrowserTool
from app.tools.file_tool import FileTool
from app.tools.summary_tool import SummaryTool
from app.tools.system_tool import SystemTool
from app.tools.whatsapp_tool import WhatsAppTool
from app.orchestrator.action_plan import ActionPlan, ActionStep
from app.orchestrator.main_orchestrator import MainOrchestrator
from app.orchestrator.tool_executor import ToolExecutor
from app.orchestrator.tool_registry import ToolRegistry

try:
    from send2trash import send2trash
    SEND2TRASH_IMPORT_ERROR = None
except Exception as exc:
    send2trash = None
    SEND2TRASH_IMPORT_ERROR = exc

try:
    from AppOpener import close as appopener_close
    from AppOpener import open as appopener_open
    APP_OPENER_IMPORT_ERROR = None
except Exception as exc:
    appopener_open = None
    appopener_close = None
    APP_OPENER_IMPORT_ERROR = exc

try:
    import keyboard
    KEYBOARD_IMPORT_ERROR = None
except Exception as exc:
    keyboard = None
    KEYBOARD_IMPORT_ERROR = exc

try:
    import winreg
except Exception:
    winreg = None


logger = logging.getLogger("J.A.R.V.I.S")


def _read_windows_shell_folder(value_name: str, default: Path) -> Path:
    if winreg is None:
        return default
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
        ) as key:
            value, _ = winreg.QueryValueEx(key, value_name)
            expanded = os.path.expandvars(str(value))
            candidate = Path(expanded)
            if candidate.exists():
                return candidate
    except Exception:
        pass
    return default


def _build_user_path_aliases() -> dict[str, Path]:
    home = Path.home()
    onedrive = home / "OneDrive"
    return {
        "desktop": _read_windows_shell_folder("Desktop", onedrive / "Desktop" if (onedrive / "Desktop").exists() else home / "Desktop"),
        "documents": _read_windows_shell_folder("Personal", onedrive / "Documents" if (onedrive / "Documents").exists() else home / "Documents"),
        "downloads": _read_windows_shell_folder("{374DE290-123F-4565-9164-39C4925E467B}", home / "Downloads"),
        "home": home,
        "music": _read_windows_shell_folder("My Music", onedrive / "Music" if (onedrive / "Music").exists() else home / "Music"),
        "pictures": _read_windows_shell_folder("My Pictures", onedrive / "Pictures" if (onedrive / "Pictures").exists() else home / "Pictures"),
        "videos": _read_windows_shell_folder("My Video", onedrive / "Videos" if (onedrive / "Videos").exists() else home / "Videos"),
    }


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

    USER_PATH_ALIASES = _build_user_path_aliases()

    def __init__(self, groq_service=None):
        self._appopener_available = appopener_open is not None and appopener_close is not None
        self._pending_delete_target: Path | None = None
        self._pending_open_target: dict | None = None
        self._pending_browser_search: dict | None = None
        self._pending_create_file: dict | None = None
        self._pending_incomplete_command: dict | None = None
        self._pending_mark_action: dict | None = None
        self._pending_whatsapp_clarification: dict | None = None
        self._pending_dry_run_plan: dict | None = None
        self._session_pending_state: dict[str, dict] = {}
        self._automation_context_store = AutomationContextStore()
        self._active_automation_context: AutomationContext | None = None
        self._confirmation_prompt_emitted_ids: set[str] = set()
        self._last_browser_choice: str | None = None
        self._browser_session_id = f"browser-{uuid.uuid4().hex[:10]}"
        self._last_file_target: Path | None = None
        self._last_folder_target: Path | None = None
        self._last_web_target: str | None = None
        self._last_youtube_query: str | None = None
        self._last_google_query: str | None = None
        self.computer_control_service = ComputerControlService()
        self.computer_settings_service = ComputerSettingsService(self.computer_control_service)
        self.browser_control_service = BrowserControlService()
        self.contact_match_service = ContactMatchService()
        self._whatsapp_contacts_provider: Callable[[], Iterable[ContactCandidate]] | None = None
        self._active_whatsapp_call: dict | None = None
        self.whatsapp_desktop = WhatsAppDesktopAutomation()
        self.youtube_tools_service = YouTubeToolsService(groq_service=groq_service)
        self.game_service = GameService()
        self.safe_command_info_service = SafeCommandInfoService()
        self.message_action_service = MessageActionService()
        self._active_session_id: str | None = None
        self._active_turn_id: str | None = None
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

    def looks_like_confirmation_response(self, command: str) -> bool:
        text = self._normalize_spoken_command(command).lower()
        return text in {"yes", "y", "no", "n", "delete it", "go ahead", "cancel", "confirm"}

    def stages_high_risk_confirmation(self, command: str) -> bool:
        text = self._normalize_spoken_command(command).lower()
        if re.match(r"^(?:delete|remove)(?:\s+the)?\s+(?:file|folder|directory)\s+.+", text):
            return True
        if self._looks_like_send_message(text):
            return True
        if self._extract_whatsapp_call_intent(text) is not None:
            return True
        for part in self._split_compound_commands(text):
            if part != text and self._extract_whatsapp_call_intent(part) is not None:
                return True
        return False

    def pending_authorization_text(self, confirmation: str) -> str | None:
        reply = self._normalize_spoken_command(confirmation).lower()
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
        text = self._normalize_spoken_command(command).lower()
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
        lowered = self._normalize_spoken_command(command).lower()
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

        if lowered in {"mute", "unmute", "volume up", "volume down"}:
            return True

        if self._looks_like_mark_request(lowered):
            return True

        if re.match(r"^(?:show me|display|open)\s+(?:that|the)\s+(?:file|folder|directory|item)\b", lowered):
            return True

        if re.match(r"^(?:in\s+)?(?:that|the)\s+folder\b.*\b(?:add|create|make)\s+(?:a\s+)?file\b", lowered):
            return True

        return bool(re.match(
            r"^(?:open|launch|start|close|kill|play|type|paste|create|make|"
            r"delete|remove|move|rename|google search|youtube search|search google|"
            r"search youtube|mute|unmute|volume up|volume down|turn volume|"
            r"show desktop|switch window|switch app|next window|close this window|"
            r"close current window|minimize|fullscreen|full screen|list files|"
            r"show files|read file|find files|find pdf|find pdfs|show largest|"
            r"largest files|organize folder|preview organize)\b",
            lowered,
        ))

    def looks_like_semantic_request(self, command: str, *, session_id: str | None = None) -> bool:
        context = self._automation_context_for(session_id)
        if self._looks_like_semantic_confirmation_turn(command, context=context):
            return True
        if self._looks_like_whatsapp_command(str(command or "").strip().lower()):
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
        previous_context = self._active_automation_context
        previous_session_id = self._active_session_id
        previous_turn_id = self._active_turn_id
        previous_step_up_verified = self._active_step_up_verified
        self._active_automation_context = self._automation_context_for(session_id)
        self._active_session_id = session_id
        self._active_turn_id = turn_id
        self._active_step_up_verified = bool(step_up_verified)
        try:
            previous_confirmation_keys = self._active_confirmation_prompt_keys(session_id)
            result = normalize_automation_response(self._execute_legacy(command))
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
            self._active_step_up_verified = previous_step_up_verified

    def _automation_context_for(self, session_id: str | None) -> AutomationContext | None:
        if not AUTOMATION_CONTEXT_ENABLED:
            return None
        return self._automation_context_store.get(session_id or "default")

    def _load_session_pending_state(self, session_id: str) -> None:
        state = self._session_pending_state.get(session_id) or {}
        self._pending_delete_target = state.get("delete_target")
        self._pending_open_target = state.get("open_target")
        self._pending_browser_search = state.get("browser_search")
        self._pending_create_file = state.get("create_file")
        self._pending_incomplete_command = state.get("incomplete_command")
        self._pending_mark_action = state.get("mark_action")
        self._pending_whatsapp_clarification = state.get("whatsapp_clarification")
        self._pending_dry_run_plan = state.get("dry_run_plan")

    def _save_session_pending_state(self, session_id: str) -> None:
        state = {
            "delete_target": self._pending_delete_target,
            "open_target": self._pending_open_target,
            "browser_search": self._pending_browser_search,
            "create_file": self._pending_create_file,
            "incomplete_command": self._pending_incomplete_command,
            "mark_action": self._pending_mark_action,
            "whatsapp_clarification": self._pending_whatsapp_clarification,
            "dry_run_plan": self._pending_dry_run_plan,
        }
        if any(value is not None for value in state.values()):
            self._session_pending_state[session_id] = state
        else:
            self._session_pending_state.pop(session_id, None)

    def _confirmation_scope_key(self, pending_action_id: str, session_id: str | None) -> str:
        return f"{session_id or '__default__'}:{pending_action_id}"

    def _pending_action_id(self, kind: str, payload: object) -> str:
        def sanitize(value: object) -> object:
            if isinstance(value, dict):
                return {str(key): sanitize(val) for key, val in sorted(value.items()) if key != "expires_at"}
            if isinstance(value, (list, tuple, set)):
                return [sanitize(item) for item in value]
            if isinstance(value, Path):
                return str(value)
            return value

        clean_payload = sanitize(payload)
        raw = json.dumps({"kind": kind, "payload": clean_payload}, sort_keys=True, default=str)
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
        return f"{kind}:{digest}"

    def _active_pending_confirmation_id(self) -> str | None:
        if self._pending_mark_action is not None:
            pending = self._pending_mark_action
            return self._pending_action_id(str(pending.get("kind") or "mark"), dict(pending.get("payload") or {}))
        if self._pending_delete_target is not None:
            return self._pending_action_id("delete", {"target": self._pending_delete_target})
        return None

    def _active_confirmation_prompt_keys(self, session_id: str | None) -> set[str]:
        pending_action_id = self._active_pending_confirmation_id()
        if not pending_action_id:
            return set()
        return {self._confirmation_scope_key(pending_action_id, session_id)}

    def _clear_stale_confirmation_prompts(self, previous_keys: set[str], current_keys: set[str]) -> None:
        for key in previous_keys - current_keys:
            self._confirmation_prompt_emitted_ids.discard(key)

    def _dedupe_confirmation_prompt(self, result: dict[str, object], *, session_id: str | None) -> dict[str, object]:
        pending_action_id = self._active_pending_confirmation_id()
        if not pending_action_id:
            return result

        scoped_key = self._confirmation_scope_key(pending_action_id, session_id)
        prompt_already_emitted = scoped_key in self._confirmation_prompt_emitted_ids
        result["pending_action_id"] = pending_action_id
        if isinstance(result.get("pending"), dict):
            result["pending"] = {**dict(result["pending"]), "pending_action_id": pending_action_id}

        for action in result.get("actions") or []:
            if isinstance(action, dict) and action.get("type") == "show_status":
                action["pending_action_id"] = pending_action_id

        if prompt_already_emitted and self._is_repeat_confirmation_prompt_result(result):
            message = "Waiting for your confirmation."
            result["message"] = message
            result["display_text"] = message
            result["spoken_text"] = ""
            for action in result.get("actions") or []:
                if isinstance(action, dict) and action.get("type") == "show_status":
                    action["message"] = message
            return result

        if self._is_confirmation_prompt_result(result):
            self._confirmation_prompt_emitted_ids.add(scoped_key)
            result.setdefault("spoken_text", str(result.get("message") or ""))
        return result

    def _is_repeat_confirmation_prompt_result(self, result: dict[str, object]) -> bool:
        action = str(result.get("action") or "")
        if action == "multi_action":
            return False
        return self._is_confirmation_prompt_result(result)

    def _is_confirmation_prompt_result(self, result: dict[str, object]) -> bool:
        if result.get("pending_action_id"):
            return True
        action = str(result.get("action") or "")
        message = str(result.get("message") or "")
        if action in {"whatsapp_call_pending", "send_message_pending", "game_confirmation", "delete_file", "delete_folder", "delete", "confirmation"}:
            return bool(
                re.search(r"\bsay yes\b|\breply yes\b|\bplease reply yes\b|\bno to cancel\b|\bconfirm\b", message, re.I)
            )
        return False

    def _has_pending_incomplete_command(self) -> bool:
        pending = self._pending_incomplete_command
        if not pending:
            return False
        if time.time() > float(pending.get("expires_at") or 0):
            self._pending_incomplete_command = None
            return False
        return True

    def _has_pending_dry_run_plan(self) -> bool:
        pending = self._pending_dry_run_plan
        if not pending:
            return False
        if time.time() > float(pending.get("expires_at") or 0):
            self._pending_dry_run_plan = None
            return False
        return True

    def _handle_pending_dry_run_response(self, text: str) -> dict[str, object] | None:
        if not self._has_pending_dry_run_plan():
            return None
        lowered = self._normalize_spoken_command(text).lower().rstrip(".!?")
        if lowered in {"no", "n", "cancel", "stop", "never mind"}:
            self._pending_dry_run_plan = None
            return {
                "success": True,
                "action": "dry_run_cancelled",
                "message": "Cancelled the dry-run plan. No actions were run.",
                "dry_run": True,
                "executable": False,
            }
        if lowered in {"yes", "y", "do it", "confirm", "go ahead", "proceed"}:
            self._pending_dry_run_plan = None
            return {
                "success": False,
                "action": "dry_run_not_executable",
                "message": "This dry-run plan is not executable yet. No actions were run.",
                "dry_run": True,
                "execution_deferred": True,
                "executable": False,
            }
        return None

    def _stage_incomplete_command(self, kind: str, template: str, prompt: str) -> dict[str, object]:
        self._pending_incomplete_command = {
            "kind": kind,
            "template": template,
            "created_at": time.time(),
            "expires_at": time.time() + 45,
        }
        return {
            "success": False,
            "action": "clarification_required",
            "message": prompt,
            "requires_followup": True,
        }

    def _detect_incomplete_command(self, text: str) -> dict[str, object] | None:
        cleaned = self._normalize_spoken_command(text).rstrip(" .!?")
        if re.match(r"^create\s+(?:a\s+)?file\s+(?:on|in)\s+(?:my\s+)?(?:desktop|documents|downloads|home)\s+(?:named|called)$", cleaned, re.I):
            return self._stage_incomplete_command("file_name", f"{cleaned} {{answer}}", "What should I name it?")
        match = re.match(
            r"^(create\s+(?:a\s+)?file\s+(?:on|in)\s+(?:my\s+)?(?:desktop|documents|downloads|home)\s+(?:named|called)\s+.+?\s+and\s+(?:write|add|put|insert))$",
            cleaned,
            re.I,
        )
        if match:
            return self._stage_incomplete_command("file_content", f"{match.group(1)} {{answer}}", "What should I write in it?")
        match = re.match(r"^(open\s+(?:chrome|google chrome|edge|microsoft edge)\s+and\s+search(?:\s+for)?)$", cleaned, re.I)
        if match:
            return self._stage_incomplete_command("browser_search", f"{match.group(1)} {{answer}}", "What should I search for?")
        return None

    def _handle_incomplete_command_followup(self, text: str) -> dict[str, object] | None:
        pending = self._pending_incomplete_command
        if not pending:
            return None
        reply = self._normalize_spoken_command(text).strip()
        lowered = reply.lower().rstrip(".!?")
        if lowered in {"cancel", "stop", "never mind", "no", "skip", "nothing", "thanks", "thank you", "ok", "okay"}:
            self._pending_incomplete_command = None
            return {
                "success": False,
                "action": "clarification_cancelled",
                "message": "Okay, I cancelled that.",
            }
        if self._looks_like_new_automation_command(lowered):
            self._pending_incomplete_command = None
            return self._execute_legacy(reply)
        template = str(pending.get("template") or "")
        if not template or not reply:
            return None
        self._pending_incomplete_command = None
        if pending.get("kind") == "browser_search":
            browser = "chrome" if "chrome" in template.lower() else "edge" if "edge" in template.lower() else None
            return self._google_search(reply, browser=browser)
        return self._execute_legacy(template.replace("{answer}", reply))

    def _looks_like_new_automation_command(self, lowered: str) -> bool:
        return lowered.startswith(
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
        )

    def _execute_legacy(self, command: str) -> Dict[str, str | bool]:
        text = (command or "").strip()
        if not text:
            return {
                "success": False,
                "action": "unsupported",
                "message": "Tell me which app you want to open or close.",
            }

        normalized_text = self._normalize_spoken_command(text)
        lowered = normalized_text.lower()

        dry_run_followup = self._handle_pending_dry_run_response(normalized_text)
        if dry_run_followup is not None:
            return dry_run_followup

        if self._pending_mark_action is not None:
            return self._handle_mark_confirmation(text)

        game_confirmation = self.game_service.prepare_sensitive(normalized_text)
        if game_confirmation is not None:
            pending = game_confirmation.get("pending")
            if pending:
                self._pending_mark_action = {"kind": "game", "payload": pending}
            return game_confirmation

        if self.DANGEROUS_COMMAND_RE.search(lowered):
            return {
                "success": False,
                "action": "blocked",
                "message": "That command is blocked because it can change or damage the system. I can help with safe app, window, file, and volume actions instead.",
            }

        if self._pending_delete_target is not None:
            return self._handle_delete_confirmation(text)

        if self._pending_open_target is not None:
            return self._handle_open_clarification(text)

        if self._pending_browser_search is not None:
            return self._handle_browser_search_followup(text)

        if self._pending_create_file is not None:
            return self._handle_create_file_location_followup(text)

        if self._has_pending_incomplete_command():
            completed = self._handle_incomplete_command_followup(normalized_text)
            if completed is not None:
                return completed

        if self._pending_whatsapp_clarification is not None:
            return self._handle_whatsapp_clarification_followup(normalized_text)

        path_request_match = re.match(
            r"^(?:where\s+is\s+(?:it|that|that\s+file|the\s+file)|show\s+(?:me\s+)?(?:the\s+)?full\s+path|copy\s+(?:the\s+)?path)[.!?]*$",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if path_request_match:
            return self._show_last_file_path()

        incomplete = self._detect_incomplete_command(normalized_text)
        if incomplete is not None:
            return incomplete

        create_location_needed = self._preflight_create_file_location(normalized_text)
        if create_location_needed is not None:
            return create_location_needed

        multistep_result = self._execute_multistep_tool_plan(normalized_text)
        if multistep_result is not None:
            return multistep_result

        create_plan_result = self._execute_create_plan_if_safe_scoped(normalized_text)
        if create_plan_result is not None:
            return create_plan_result

        system_result = self._execute_system_tool(normalized_text)
        if system_result is not None:
            return system_result

        mark_result = self._execute_mark_request(normalized_text)
        if mark_result is not None:
            return mark_result

        browser_result = self._execute_browser_tool(normalized_text)
        if browser_result is not None:
            return browser_result

        file_result = self._execute_file_tool(normalized_text)
        if file_result is not None:
            return file_result

        app_result = self._execute_app_tool(normalized_text)
        if app_result is not None:
            return app_result

        list_match = re.match(
            r"^(?:list|show)(?:\s+me)?\s+(?:the\s+)?files(?:\s+(?:in|on|inside|under)\s+(.+?))?[.!?]*$",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if list_match:
            return self._list_files((list_match.group(1) or "downloads").strip())

        read_match = re.match(
            r"^(?:read|show|display)(?:\s+me)?\s+(?:the\s+)?(?:file|text\s+file)\s+(.+?)[.!?]*$",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if read_match:
            return self._read_file(read_match.group(1).strip())

        find_match = re.match(
            r"^find\s+(?P<query>.+?)(?:\s+(?:in|inside|under|on)\s+(?P<location>.+?))?[.!?]*$",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if find_match:
            query = find_match.group("query").strip()
            location = (find_match.group("location") or "home").strip()
            if re.search(r"\b(files?|pdfs?|documents?|images?|photos?|videos?|music)\b", query, flags=re.IGNORECASE):
                return self._find_files(query, location)

        largest_match = re.match(
            r"^(?:show\s+)?(?:the\s+)?(?:largest|biggest)\s+files(?:\s+(?:in|on|inside|under)\s+(.+?))?[.!?]*$",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if largest_match:
            return self._largest_files((largest_match.group(1) or "home").strip())

        organize_match = re.match(
            r"^(?:(?:preview\s+)?organize|organize\s+preview)(?:\s+(?:the\s+)?(?:folder|directory))?(?:\s+(?:in|on|inside|under)\s+(.+?))?[.!?]*$",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if organize_match:
            return self._organize_folder_preview((organize_match.group(1) or "downloads").strip())

        show_match = re.match(
            r"^(?:show me|display)\s+(?P<target>(?:that|the)\s+(?:file|folder|directory|item)|.+?)[.!?]*$",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if show_match:
            return self._open_target(show_match.group("target").strip())

        open_type_match = re.match(
            r"^(?:open|launch|start)\s+(?P<app>.+?)\s+and\s+(?P<verb>type|write|paste)\s+(?P<content>.+?)[.!?]*$",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if open_type_match:
            app_target = open_type_match.group("app").strip()
            verb = open_type_match.group("verb").strip().lower()
            content = open_type_match.group("content").strip()
            return self._open_and_type(app_target, content, press_enter=verb == "paste")

        open_search_match = re.match(
            r"^(?:open|launch|start)\s+(?P<browser>chrome|edge|microsoft edge)\s+and\s+search\s+(?:(?P<engine>youtube|google)\s+for\s+)?(?P<query>.+?)[.!?]*$",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if open_search_match:
            browser = open_search_match.group("browser").strip()
            engine = (open_search_match.group("engine") or "google").strip().lower()
            query = open_search_match.group("query").strip()
            if engine == "youtube":
                return self._youtube_search(query, browser=browser)
            return self._google_search(query, browser=browser)

        open_site_match = re.match(
            r"^(?:open|launch|start)\s+(?P<browser>chrome|edge|microsoft edge)\s+and\s+open\s+(?P<site>youtube|google|gmail|https?://\S+|www\.\S+|\S+\.\S+)[.!?]*$",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if open_site_match:
            browser = open_site_match.group("browser").strip()
            site = open_site_match.group("site").strip()
            url = self._resolve_web_target(site) or site
            try:
                self._open_url(url, browser=browser)
                return {
                    "success": True,
                    "action": "open",
                    "message": f"Opening {self._normalize_target(site)} in {self._normalize_target(browser)}.",
                }
            except Exception as exc:
                return {
                    "success": False,
                    "action": "open",
                "message": f"I could not open {site} in {browser}: {exc}",
                }

        multi_action_commands = self._split_compound_commands(normalized_text)
        if len(multi_action_commands) > 1:
            return self._execute_multi_action_commands(multi_action_commands)

        if lowered.startswith(self.OPEN_PREFIXES):
            target = re.sub(r"^(open|launch|start)\s+", "", normalized_text, flags=re.IGNORECASE).strip()
            return self._open_target(target)

        browser_youtube_match = re.match(
            r"^(?:in|on)\s+(chrome|edge|microsoft edge)\s+(?:search|open)\s+youtube(?:\s+for)?\s+(.+?)[.!?]*$",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if browser_youtube_match:
            return self._youtube_search(browser_youtube_match.group(2).strip(), browser=browser_youtube_match.group(1).strip())

        browser_google_match = re.match(
            r"^(?:in|on)\s+(chrome|edge|microsoft edge)\s+(?:search|open)\s+google(?:\s+for)?\s+(.+?)[.!?]*$",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if browser_google_match:
            return self._google_search(browser_google_match.group(2).strip(), browser=browser_google_match.group(1).strip())

        search_in_browser_match = re.match(
            r"^(?:search\s+)?(youtube|google)\s+for\s+(.+?)\s+(?:in|on)\s+(chrome|edge|microsoft edge)[.!?]*$",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if search_in_browser_match:
            engine = search_in_browser_match.group(1).strip().lower()
            query = search_in_browser_match.group(2).strip()
            browser = search_in_browser_match.group(3).strip()
            if engine == "youtube":
                return self._youtube_search(query, browser=browser)
            return self._google_search(query, browser=browser)

        if re.match(r"^(?:in|on)\s+chrome\s+(?:search|open)\s+youtube[.!?]*$", lowered):
            return self._execute_multi_action_commands(["open chrome", "open youtube"])

        if re.match(r"^(?:in|on)\s+chrome\s+(?:search|open)\s+google[.!?]*$", lowered):
            return self._execute_multi_action_commands(["open chrome", "open google"])

        if lowered.startswith(self.CLOSE_PREFIXES):
            target = re.sub(r"^(close|kill)\s+", "", normalized_text, flags=re.IGNORECASE).strip()
            return self._close_target(target)

        if lowered.startswith(self.PLAY_PREFIXES):
            target = re.sub(r"^play\s+", "", normalized_text, flags=re.IGNORECASE).strip()
            if re.fullmatch(r"(?:the\s+)?first\s+result", target, flags=re.IGNORECASE):
                return self._play_first_result()
            return self._play_media(target)

        if lowered.startswith(self.TYPE_PREFIXES):
            text_to_type = re.sub(r"^(type|paste)\s+", "", normalized_text, flags=re.IGNORECASE).strip()
            return self._type_text(text_to_type)

        if lowered.startswith(self.GOOGLE_SEARCH_PREFIXES):
            target = re.sub(r"^(google search|search google for)\s+", "", normalized_text, flags=re.IGNORECASE).strip()
            return self._google_search(target)

        if lowered.startswith(self.YOUTUBE_SEARCH_PREFIXES):
            target = re.sub(r"^(youtube search|search youtube for)\s+", "", normalized_text, flags=re.IGNORECASE).strip()
            return self._youtube_search(target)

        if lowered in {"mute", "unmute", "volume up", "volume down"}:
            return self._system_command(lowered)

        create_folder_match = re.match(
            r"^(?:create|make)(?:\s+a)?(?:\s+new)?\s+(?:folder|directory)(?:\s+called)?\s+(.+?)[.!?]*$",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if create_folder_match:
            return self._create_folder(create_folder_match.group(1).strip())

        create_and_write_match = re.match(
            r"^(?:create|make)(?:\s+a)?(?:\s+new)?\s+file(?:\s+called)?\s+(?P<target>.+?)\s+and\s+in\s+(?:that|the)\s+file\s+(?:add|write|append|put|insert)\s+(?P<content>[\s\S]+?)[.!?]*$",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if create_and_write_match:
            target = create_and_write_match.group("target").strip()
            content = create_and_write_match.group("content").strip().rstrip(".!?")
            return self._create_file_or_ask_for_location(target, content)

        create_match = re.match(
            r"^(?:create|make)(?:\s+a)?(?:\s+new)?\s+file(?:\s+called)?\s+(.+?)(?:(?:\s+with\s+content|\s+and\s+write|\s+and\s+add)\s+([\s\S]+))?[.!?]*$",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if create_match:
            target = create_match.group(1).strip()
            content = (create_match.group(2) or "").strip().rstrip(".!?")
            return self._create_file_or_ask_for_location(target, content)

        create_in_folder_match = re.match(
            r"^(?:in\s+)?(?P<folder>(?:that|the)\s+folder|.+?)\s+(?:add|create|make)\s+(?:a\s+)?file(?:\s+called)?\s+(?P<name>.+?)(?:\s+and\s+in\s+(?:that|the)\s+file\s+(?:add|write|append|put|insert)\s+(?P<content>.+))?[.!?]*$",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if create_in_folder_match:
            folder = create_in_folder_match.group("folder").strip()
            name = create_in_folder_match.group("name").strip()
            content = (create_in_folder_match.group("content") or "").strip().rstrip(".!?")
            return self._create_file_in_folder(folder, name, content)

        repeated_reference_match = re.match(
            r"^(?:(?:in\s+)?(?:that|the)\s+file\s+)+(?:add|write|append|put|insert)\s+(.+?)[.!?]*$",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if repeated_reference_match:
            verb_match = re.search(r"\b(add|write|append|put|insert)\b", normalized_text, flags=re.IGNORECASE)
            content = repeated_reference_match.group(1).strip().rstrip(".!?")
            verb = (verb_match.group(1) if verb_match else "add").lower()
            append = verb in {"add", "append", "insert", "put"}
            return self._update_file("that file", content, append=append)

        update_patterns = [
            r"^(?:in\s+)?(?P<target>(?:that|the)\s+file|it)\s+(?P<verb>add|write|append|put|insert)\s+(?P<content>.+?)[.!?]*$",
            r"^(?P<verb>add|write|append|put|insert)\s+(?P<content>.+?)\s+(?:to|into|in)\s+(?P<target>(?:that|the)\s+file|it|.+?)[.!?]*$",
        ]
        for pattern in update_patterns:
            update_match = re.match(pattern, normalized_text, flags=re.IGNORECASE)
            if not update_match:
                continue

            target = update_match.group("target").strip()
            content = update_match.group("content").strip().rstrip(".!?")
            verb = update_match.group("verb").strip().lower()
            append = verb in {"add", "append", "insert", "put"}
            return self._update_file(target, content, append=append)

        delete_match = re.match(
            r"^(?:delete|remove)(?:\s+the)?\s+file\s+(.+?)[.!?]*$",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if delete_match:
            target = delete_match.group(1).strip()
            return self._delete_file(target)

        delete_folder_match = re.match(
            r"^(?:delete|remove)(?:\s+the)?\s+(?:folder|directory)\s+(.+?)[.!?]*$",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if delete_folder_match:
            return self._delete_folder(delete_folder_match.group(1).strip())

        rename_match = re.match(
            r"^rename(?:\s+the)?\s+(?:(file|folder|directory)\s+)?(.+?)\s+to\s+(.+?)[.!?]*$",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if rename_match:
            target_kind = (rename_match.group(1) or "").strip().lower()
            source = rename_match.group(2).strip()
            new_name = rename_match.group(3).strip()
            return self._rename_target(source, new_name, target_kind=target_kind)

        move_match = re.match(
            r"^move(?:\s+the)?\s+(?:(file|folder|directory)\s+)?(.+?)\s+(?:to|into)\s+(.+?)[.!?]*$",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if move_match:
            target_kind = (move_match.group(1) or "").strip().lower()
            source = move_match.group(2).strip()
            destination = move_match.group(3).strip()
            return self._move_target(source, destination, target_kind=target_kind)

        return {
            "success": False,
            "action": "unsupported",
            "message": "Automation supports opening and closing apps, play and search commands, system volume controls, and creating, editing, moving, renaming, and deleting files or folders across your laptop except protected system locations.",
        }

    def _build_automation_tool_registry(self) -> ToolRegistry:
        file_tool = FileTool(self)
        if not isinstance(getattr(file_tool, "name", None), str) or not str(getattr(file_tool, "name", "")).strip():
            file_tool.name = "file"
        return ToolRegistry(
            [
                file_tool,
                BrowserTool(BrowserConnector(self.browser_control_service), automation_bridge=self),
                AppTool(self),
                AppLauncherTool(self),
                AppInteractionTool(),
                SystemTool(self),
                SummaryTool(),
            ]
        )

    def _execute_tool_with_orchestrator(self, command: str, *, expected_tool: str) -> Dict[str, str | bool] | None:
        probe_orchestrator = MainOrchestrator(registry=ToolRegistry(), enforce_policy=False)
        route = probe_orchestrator.route(command)
        if route is None or route.tool_name != expected_tool:
            return None
        orchestrator = MainOrchestrator(registry=self._build_automation_tool_registry(), enforce_policy=True)
        result = orchestrator.execute(
            ToolContext(
                command=command,
                intent=route.intent,
                session_id=self._active_session_id,
                request_id=self._active_turn_id,
                payload={"turn_id": self._active_turn_id} if self._active_turn_id else {},
                security_state={"step_up_verified": self._active_step_up_verified},
            )
        )
        if expected_tool == "file" and isinstance(result, dict) and result.get("action") == "confirmation_required":
            self._stage_delete_target_for_confirmation(command)
        return result

    def _stage_delete_target_for_confirmation(self, command: str) -> None:
        match = re.match(r"^(?:delete|remove)(?:\s+the)?\s+(?:file|folder|directory)\s+(.+?)[.!?]*$", command, re.IGNORECASE)
        if not match:
            return
        target_kind = "folder" if re.search(r"\b(?:folder|directory)\b", command, re.IGNORECASE) else "file"
        try:
            self._pending_delete_target = self._resolve_existing_target(match.group(1).strip(), target_kind=target_kind)
        except ValueError:
            self._pending_delete_target = None

    def _execute_multistep_tool_plan(self, command: str) -> Dict[str, str | bool] | None:
        if self._looks_like_whatsapp_command(str(command or "").strip().lower()):
            return None
        probe_orchestrator = MainOrchestrator(registry=ToolRegistry(), enforce_policy=False)
        payload = {"turn_id": self._active_turn_id} if self._active_turn_id else {}
        if self._active_automation_context is not None:
            payload["automation_context"] = self._active_automation_context
        tool_context = ToolContext(
            command=command,
            session_id=self._active_session_id,
            request_id=self._active_turn_id,
            payload=payload,
            security_state={"step_up_verified": self._active_step_up_verified},
        )
        semantic_result = probe_orchestrator.semantic_adapter.try_live_result(
            command,
            context=self._active_automation_context,
            scenario_policy=probe_orchestrator.scenario_policy,
        )
        if isinstance(semantic_result, dict):
            return semantic_result
        if semantic_result is not None:
            orchestrator = MainOrchestrator(registry=self._build_automation_tool_registry(), enforce_policy=True)
            return orchestrator.execute(tool_context)

        plan = probe_orchestrator.task_planner.plan(command)
        if not plan.is_multistep:
            dry_probe = probe_orchestrator.execute(tool_context)
            if isinstance(dry_probe, dict) and dry_probe.get("dry_run"):
                pending = dry_probe.get("pending_dry_run_plan")
                if isinstance(pending, dict):
                    self._pending_dry_run_plan = pending
                return dry_probe
            return None
        orchestrator = MainOrchestrator(registry=self._build_automation_tool_registry(), enforce_policy=True)
        result = orchestrator.execute(tool_context)
        if isinstance(result, dict) and result.get("dry_run"):
            pending = result.get("pending_dry_run_plan")
            if isinstance(pending, dict):
                self._pending_dry_run_plan = pending
        return result

    @staticmethod
    def _semantic_context_label(action, context: AutomationContext | None) -> str:
        if action is None:
            return "none"
        if getattr(action, "file_path", None) and context and getattr(action, "file_path") == context.last_created_file_path:
            return "last_created_file_path"
        if getattr(action, "file_path", None) and context and getattr(action, "file_path") == context.last_edited_file_path:
            return "last_edited_file_path"
        if getattr(action, "file_path", None):
            return "file_path"
        if getattr(action, "requires_context", False):
            return "missing" if getattr(action, "missing_fields", None) else "context"
        return "none"

    def _execute_file_tool(self, command: str) -> Dict[str, str | bool] | None:
        return self._execute_tool_with_orchestrator(command, expected_tool="file")

    def _execute_browser_tool(self, command: str) -> Dict[str, str | bool] | None:
        return self._execute_tool_with_orchestrator(command, expected_tool="browser")

    def _execute_app_tool(self, command: str) -> Dict[str, str | bool] | None:
        return self._execute_tool_with_orchestrator(command, expected_tool="app")

    def _execute_system_tool(self, command: str) -> Dict[str, str | bool] | None:
        return self._execute_tool_with_orchestrator(command, expected_tool="system")

    def _preflight_create_file_location(self, command: str) -> Dict[str, object] | None:
        create_and_write_match = re.match(
            r"^(?:create|make)(?:\s+a)?(?:\s+new)?\s+file(?:\s+called)?\s+(?P<target>.+?)\s+and\s+in\s+(?:that|the)\s+file\s+(?:add|write|append|put|insert)\s+(?P<content>[\s\S]+?)[.!?]*$",
            command,
            flags=re.IGNORECASE,
        )
        create_match = re.match(
            r"^(?:create|make)(?:\s+a)?(?:\s+new)?\s+file(?:\s+called)?\s+(?P<target>.+?)(?:(?:\s+with\s+content|\s+and\s+write|\s+and\s+add)\s+(?P<content>[\s\S]+))?[.!?]*$",
            command,
            flags=re.IGNORECASE,
        )
        match = create_and_write_match or create_match
        if not match:
            return None
        target = str(match.group("target") or "").strip()
        if self._looks_like_explicit_path_request(target):
            return None
        file_name = self._clean_file_name(self._sanitize_file_reference(target))
        if not file_name:
            return None
        content = str(match.groupdict().get("content") or "").strip().rstrip(".!?")
        self._pending_create_file = {"name": file_name, "content": content}
        return {
            "success": False,
            "action": "create_file_location_needed",
            "message": f"Where should I save {file_name}?",
            "requires_followup": True,
        }

    def _execute_create_plan_if_safe_scoped(self, command: str) -> Dict[str, object] | None:
        folder_match = re.match(
            r"^(?:create|make)(?:\s+a)?(?:\s+new)?\s+(?:folder|directory)(?:\s+called)?\s+(?P<target>.+?)[.!?]*$",
            command,
            flags=re.IGNORECASE,
        )
        if folder_match:
            target = folder_match.group("target").strip()
            if not self._looks_like_explicit_path_request(target):
                return None
            try:
                path = self._resolve_folder_target(target)
            except ValueError as exc:
                return {"success": False, "action": "create_folder", "message": str(exc)}
            return self._execute_planned_file_steps(
                command,
                [
                    ActionStep("step1", "file", "file", "create_folder", {"parent": str(path.parent), "name": path.name}),
                ],
            )

        file_match = re.match(
            r"^(?:create|make)(?:\s+a)?(?:\s+new)?\s+file(?:\s+called)?\s+(?P<target>.+?)(?:(?:\s+with\s+content|\s+and\s+write|\s+and\s+add)\s+(?P<content>[\s\S]+))?[.!?]*$",
            command,
            flags=re.IGNORECASE,
        )
        if not file_match:
            return None
        target = file_match.group("target").strip()
        if not self._looks_like_explicit_path_request(target):
            return None
        try:
            path = self._resolve_file_target(target)
        except ValueError as exc:
            return {"success": False, "action": "create_file", "message": str(exc)}
        content = str(file_match.group("content") or "").strip().rstrip(".!?")
        steps = [
            ActionStep("step1", "file", "file", "create_file", {"parent": str(path.parent), "filename": path.name}),
        ]
        if content:
            steps.append(
                ActionStep(
                    "step2",
                    "file",
                    "file",
                    "write_file",
                    {"path": "{step1.path}", "content": content, "overwrite": False},
                    depends_on=["step1"],
                )
            )
            steps.append(
                ActionStep(
                    "step3",
                    "file",
                    "file",
                    "verify_exists",
                    {"path": "{step1.path}", "expected_content": content},
                    depends_on=["step1", "step2"],
                )
            )
        return self._execute_planned_file_steps(command, steps)

    def _execute_planned_file_steps(self, command: str, steps: list[ActionStep]) -> Dict[str, object]:
        executor = ToolExecutor(registry=self._build_automation_tool_registry(), enforce_policy=True)
        return executor.execute(
            ActionPlan(original_text=command, steps=steps, is_multistep=len(steps) > 1),
            ToolContext(
                command=command,
                intent="file",
                session_id=self._active_session_id,
                request_id=self._active_turn_id,
                payload={"turn_id": self._active_turn_id} if self._active_turn_id else {},
                security_state={"step_up_verified": self._active_step_up_verified},
            ),
        )

    def _looks_like_mark_request(self, lowered: str) -> bool:
        if self._looks_like_whatsapp_command(lowered):
            return True
        if self._looks_like_send_message(lowered):
            return True
        if self._looks_like_browser_control(lowered):
            return True
        if self._looks_like_computer_control(lowered):
            return True
        if self._looks_like_youtube_tool(lowered):
            return True
        if self.game_service.can_handle(lowered):
            return True
        if self._looks_like_safe_command_info(lowered):
            return True
        return self._looks_like_extended_setting(lowered)

    def _execute_mark_request(self, command: str) -> Dict[str, str | bool] | None:
        lowered = command.lower()

        whatsapp_result = self._execute_whatsapp_command(command)
        if whatsapp_result is not None:
            pending = whatsapp_result.get("pending") if isinstance(whatsapp_result, dict) else None
            if pending:
                kind = "send_message" if whatsapp_result.get("action") == "send_message_pending" else "whatsapp_call"
                self._pending_mark_action = {"kind": kind, "payload": pending}
            return whatsapp_result

        message_result = self._prepare_message_action(command)
        if message_result is not None:
            pending = message_result.get("pending")
            if pending:
                self._pending_mark_action = {"kind": "send_message", "payload": pending}
            return message_result

        youtube_result = self._execute_youtube_tool(command)
        if youtube_result is not None:
            return youtube_result

        browser_result = self._execute_browser_control(command)
        if browser_result is not None:
            return browser_result

        control_result = self._execute_computer_control(command)
        if control_result is not None:
            return control_result

        if self._looks_like_extended_setting(lowered):
            return self.computer_settings_service.execute(self._normalize_extended_setting(lowered))

        if self._looks_like_safe_command_info(lowered):
            return self.safe_command_info_service.execute(command)

        if self.game_service.can_handle(command):
            return self.game_service.execute(command)

        return None

    def _execute_app_launcher_command_legacy(self, command: str) -> Dict[str, str | bool] | None:
        normalized_text = self._normalize_spoken_command(command)
        lowered = normalized_text.lower()

        open_type_match = re.match(
            r"^(?:open|launch|start)\s+(?P<app>.+?)\s+and\s+(?P<verb>type|write|paste)\s+(?P<content>.+?)[.!?]*$",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if open_type_match:
            app_target = open_type_match.group("app").strip()
            verb = open_type_match.group("verb").strip().lower()
            content = open_type_match.group("content").strip()
            return self._open_and_type(app_target, content, press_enter=verb == "paste")

        open_search_match = re.match(
            r"^(?:open|launch|start)\s+(?P<browser>chrome|edge|microsoft edge)\s+and\s+search\s+(?:(?P<engine>youtube|google)\s+for\s+)?(?P<query>.+?)[.!?]*$",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if open_search_match:
            browser = open_search_match.group("browser").strip()
            engine = (open_search_match.group("engine") or "google").strip().lower()
            query = open_search_match.group("query").strip()
            if engine == "youtube":
                return self._youtube_search(query, browser=browser)
            return self._google_search(query, browser=browser)

        open_site_match = re.match(
            r"^(?:open|launch|start)\s+(?P<browser>chrome|edge|microsoft edge)\s+and\s+open\s+(?P<site>youtube|google|gmail|https?://\S+|www\.\S+|\S+\.\S+)[.!?]*$",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if open_site_match:
            browser = open_site_match.group("browser").strip()
            site = open_site_match.group("site").strip()
            url = self._resolve_web_target(site) or site
            try:
                self._open_url(url, browser=browser)
                return {
                    "success": True,
                    "action": "open",
                    "message": f"Opening {self._normalize_target(site)} in {self._normalize_target(browser)}.",
                }
            except Exception as exc:
                return {
                    "success": False,
                    "action": "open",
                    "message": f"I could not open {site} in {browser}: {exc}",
                }

        multi_action_commands = self._split_compound_commands(normalized_text)
        if len(multi_action_commands) > 1:
            return self._execute_multi_action_commands(multi_action_commands)

        if lowered.startswith(self.OPEN_PREFIXES):
            target = re.sub(r"^(open|launch|start)\s+", "", normalized_text, flags=re.IGNORECASE).strip()
            return self._open_target(target)

        if lowered.startswith(self.CLOSE_PREFIXES):
            target = re.sub(r"^(close|kill)\s+", "", normalized_text, flags=re.IGNORECASE).strip()
            return self._close_target(target)

        return None

    def _execute_system_command_legacy(self, command: str) -> Dict[str, str | bool] | None:
        normalized_text = self._normalize_spoken_command(command)
        lowered = normalized_text.lower()

        system_alias = self._match_system_command(lowered)
        if system_alias:
            return self._system_command(system_alias)

        control_result = self._execute_computer_control(normalized_text)
        if control_result is not None:
            return control_result

        if self._looks_like_extended_setting(lowered):
            return self.computer_settings_service.execute(self._normalize_extended_setting(lowered))

        return None

    def _execute_file_command_legacy(self, command: str, context=None) -> Dict[str, str | bool] | None:
        normalized_text = self._normalize_spoken_command(command)

        path_request_match = re.match(
            r"^(?:where\s+is\s+(?:it|that|that\s+file|the\s+file)|show\s+(?:me\s+)?(?:the\s+)?full\s+path|copy\s+(?:the\s+)?path)[.!?]*$",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if path_request_match:
            return self._show_last_file_path()

        list_match = re.match(
            r"^(?:list|show)(?:\s+me)?\s+(?:the\s+)?files(?:\s+(?:in|on|inside|under)\s+(.+?))?[.!?]*$",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if list_match:
            return self._list_files((list_match.group(1) or "downloads").strip())

        read_match = re.match(
            r"^(?:read|show|display)(?:\s+me)?\s+(?:the\s+)?(?:file|text\s+file)\s+(.+?)[.!?]*$",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if read_match:
            return self._read_file(read_match.group(1).strip())

        find_match = re.match(
            r"^find\s+(?P<query>.+?)(?:\s+(?:in|inside|under|on)\s+(?P<location>.+?))?[.!?]*$",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if find_match:
            query = find_match.group("query").strip()
            location = (find_match.group("location") or "home").strip()
            if re.search(r"\b(files?|pdfs?|documents?|images?|photos?|videos?|music)\b", query, flags=re.IGNORECASE):
                return self._find_files(query, location)

        largest_match = re.match(
            r"^(?:show\s+)?(?:the\s+)?(?:largest|biggest)\s+files(?:\s+(?:in|on|inside|under)\s+(.+?))?[.!?]*$",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if largest_match:
            return self._largest_files((largest_match.group(1) or "home").strip())

        organize_match = re.match(
            r"^(?:(?:preview\s+)?organize|organize\s+preview)(?:\s+(?:the\s+)?(?:folder|directory))?(?:\s+(?:in|on|inside|under)\s+(.+?))?[.!?]*$",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if organize_match:
            return self._organize_folder_preview((organize_match.group(1) or "downloads").strip())

        show_match = re.match(
            r"^(?:show me|display)\s+(?P<target>(?:that|the)\s+(?:file|folder|directory|item)|.+?)[.!?]*$",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if show_match:
            return self._open_target(show_match.group("target").strip())

        create_folder_match = re.match(
            r"^(?:create|make)(?:\s+a)?(?:\s+new)?\s+(?:folder|directory)(?:\s+called)?\s+(.+?)[.!?]*$",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if create_folder_match:
            return self._create_folder(create_folder_match.group(1).strip())

        create_and_write_match = re.match(
            r"^(?:create|make)(?:\s+a)?(?:\s+new)?\s+file(?:\s+called)?\s+(?P<target>.+?)\s+and\s+in\s+(?:that|the)\s+file\s+(?:add|write|append|put|insert)\s+(?P<content>[\s\S]+?)[.!?]*$",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if create_and_write_match:
            target = create_and_write_match.group("target").strip()
            content = create_and_write_match.group("content").strip().rstrip(".!?")
            return self._create_file_or_ask_for_location(target, content)

        create_match = re.match(
            r"^(?:create|make)(?:\s+a)?(?:\s+new)?\s+file(?:\s+called)?\s+(.+?)(?:(?:\s+with\s+content|\s+and\s+write|\s+and\s+add)\s+([\s\S]+))?[.!?]*$",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if create_match:
            target = create_match.group(1).strip()
            content = (create_match.group(2) or "").strip().rstrip(".!?")
            return self._create_file_or_ask_for_location(target, content)

        create_in_folder_match = re.match(
            r"^(?:in\s+)?(?P<folder>(?:that|the)\s+folder|.+?)\s+(?:add|create|make)\s+(?:a\s+)?file(?:\s+called)?\s+(?P<name>.+?)(?:\s+and\s+in\s+(?:that|the)\s+file\s+(?:add|write|append|put|insert)\s+(?P<content>.+))?[.!?]*$",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if create_in_folder_match:
            folder = create_in_folder_match.group("folder").strip()
            name = create_in_folder_match.group("name").strip()
            content = (create_in_folder_match.group("content") or "").strip().rstrip(".!?")
            return self._create_file_in_folder(folder, name, content)

        repeated_reference_match = re.match(
            r"^(?:(?:in\s+)?(?:that|the)\s+file\s+)+(?:add|write|append|put|insert)\s+(.+?)[.!?]*$",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if repeated_reference_match:
            verb_match = re.search(r"\b(add|write|append|put|insert)\b", normalized_text, flags=re.IGNORECASE)
            content = repeated_reference_match.group(1).strip().rstrip(".!?")
            verb = (verb_match.group(1) if verb_match else "add").lower()
            append = verb in {"add", "append", "insert", "put"}
            return self._update_file("that file", content, append=append)

        update_patterns = [
            r"^(?:in\s+)?(?P<target>(?:that|the)\s+file|it)\s+(?P<verb>add|write|append|put|insert)\s+(?P<content>.+?)[.!?]*$",
            r"^(?P<verb>add|write|append|put|insert)\s+(?P<content>.+?)\s+(?:to|into|in)\s+(?P<target>(?:that|the)\s+file|it|.+?)[.!?]*$",
        ]
        for pattern in update_patterns:
            update_match = re.match(pattern, normalized_text, flags=re.IGNORECASE)
            if not update_match:
                continue

            target = update_match.group("target").strip()
            content = update_match.group("content").strip().rstrip(".!?")
            verb = update_match.group("verb").strip().lower()
            append = verb in {"add", "append", "insert", "put"}
            return self._update_file(target, content, append=append)

        delete_match = re.match(
            r"^(?:delete|remove)(?:\s+the)?\s+file\s+(.+?)[.!?]*$",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if delete_match:
            target = delete_match.group(1).strip()
            return self._delete_file(target)

        delete_folder_match = re.match(
            r"^(?:delete|remove)(?:\s+the)?\s+(?:folder|directory)\s+(.+?)[.!?]*$",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if delete_folder_match:
            return self._delete_folder(delete_folder_match.group(1).strip())

        rename_match = re.match(
            r"^rename(?:\s+the)?\s+(?:(file|folder|directory)\s+)?(.+?)\s+to\s+(.+?)[.!?]*$",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if rename_match:
            target_kind = (rename_match.group(1) or "").strip().lower()
            source = rename_match.group(2).strip()
            new_name = rename_match.group(3).strip()
            return self._rename_target(source, new_name, target_kind=target_kind)

        move_match = re.match(
            r"^move(?:\s+the)?\s+(?:(file|folder|directory)\s+)?(.+?)\s+(?:to|into)\s+(.+?)[.!?]*$",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if move_match:
            target_kind = (move_match.group(1) or "").strip().lower()
            source = move_match.group(2).strip()
            destination = move_match.group(3).strip()
            return self._move_target(source, destination, target_kind=target_kind)

        return None

    def _handle_mark_confirmation(self, command: str) -> Dict[str, str | bool]:
        pending = self._pending_mark_action
        reply = self._normalize_spoken_command(command).lower()
        if not pending:
            return {"success": False, "action": "confirmation", "message": "No action is waiting for confirmation."}
        payload_for_expiry = dict(pending.get("payload") or {})
        expires_at = float(payload_for_expiry.get("expires_at") or 0.0)
        if expires_at and time.time() > expires_at:
            self._pending_mark_action = None
            return {"success": False, "action": "confirmation_expired", "message": "That WhatsApp confirmation expired."}

        if reply in {"no", "n", "cancel"}:
            self._pending_mark_action = None
            return {"success": True, "action": "confirmation_cancelled", "message": "Cancelled."}

        if reply not in {"yes", "y", "go ahead", "confirm", "delete it"}:
            return {"success": False, "action": "confirmation", "message": "Say yes to continue or no to cancel."}

        self._pending_mark_action = None
        if pending.get("kind") == "send_message":
            payload = dict(pending.get("payload") or {})
            if str(payload.get("platform") or "").lower() == "whatsapp":
                if not isinstance(self.message_action_service, MessageActionService):
                    return self.message_action_service.send(payload)
                return self._send_whatsapp_message(payload)
            return self.message_action_service.send(payload)
        if pending.get("kind") == "whatsapp_call":
            return self._start_whatsapp_call(dict(pending.get("payload") or {}))
        if pending.get("kind") == "game":
            return self.game_service.confirm(dict(pending.get("payload") or {}))
        return {"success": False, "action": "confirmation", "message": "That confirmation type is not supported."}

    def _looks_like_whatsapp_command(self, lowered: str) -> bool:
        return bool(
            lowered.startswith(("open whatsapp", "whatsapp web", "whatsapp desktop", "search contact in whatsapp", "end call"))
            or self._extract_whatsapp_call_intent(lowered) is not None
            or self._extract_whatsapp_message_intent(lowered) is not None
        )

    def _execute_whatsapp_command(self, command: str) -> Dict[str, object] | None:
        return WhatsAppTool(self).execute(ToolContext(command=command, intent="whatsapp"))

    def _execute_whatsapp_command_legacy(self, command: str) -> Dict[str, object] | None:
        text = self._normalize_spoken_command(command)
        lowered = text.lower().strip()

        if re.match(r"^open\s+whatsapp\s+web[.!?]*$", lowered) or lowered == "whatsapp web":
            return self._open_whatsapp_web()

        if re.match(r"^open\s+whatsapp(?:\s+desktop)?[.!?]*$", lowered) or lowered == "whatsapp desktop":
            return self._open_whatsapp_desktop_or_web()

        match = re.match(r"^(?:search\s+contact\s+in\s+whatsapp|whatsapp\s+search)\s+(.+?)[.!?]*$", text, flags=re.IGNORECASE)
        if match:
            contact = match.group(1).strip()
            opened = self._open_whatsapp_desktop_or_web()
            if not opened.get("success"):
                return opened
            return self._status_result(
                "whatsapp_search_contact",
                f"WhatsApp is open. Search for {contact} manually if the desktop search box is not focused.",
                success=False,
                status="needs_manual_verification",
            )

        call_intent = self._extract_whatsapp_call_intent(text)
        if call_intent is not None:
            mode = str(call_intent.get("mode") or "voice")
            contact = str(call_intent.get("contact") or "").strip()
            if self._is_ambiguous_communication_contact(contact):
                return self._whatsapp_contact_required_result("whatsapp_call", {"mode": mode})
            return self._prepare_whatsapp_call_confirmation(mode, contact)

        message_intent = self._extract_whatsapp_message_intent(text)
        if message_intent is not None:
            receiver = str(message_intent.get("receiver") or "").strip()
            message = str(message_intent.get("message") or "").strip()
            receiver, message = self._repair_whatsapp_message_contact(receiver, message)
            if self._is_ambiguous_communication_contact(receiver):
                return self._whatsapp_contact_required_result(
                    "send_message",
                    {"platform": "whatsapp", "message": message},
                )
            if not message:
                self._pending_whatsapp_clarification = {
                    "kind": "send_message_text",
                    "payload": {"platform": "whatsapp", "receiver": receiver},
                }
                prompt = f"What should I say to {receiver} on WhatsApp?"
                return self._status_result(
                    "whatsapp_message_text_required",
                    prompt,
                    success=False,
                    status="whatsapp_message_text_required",
                )
            return self._prepare_whatsapp_message_confirmation(receiver, message)

        if re.match(r"^(?:end|hang up|disconnect)(?:\s+the)?\s+(?:whatsapp\s+)?call[.!?]*$", lowered):
            return self._end_whatsapp_call()

        return None

    def _extract_whatsapp_call_intent(self, command: str) -> dict[str, str] | None:
        text = self._normalize_spoken_command(command).strip()
        patterns = (
            r"^(?:whatsapp\s+)?(?P<mode>video\s+call|voice\s+call|call)\s+(?P<contact>.+?)(?:\s+(?:on|via|using)\s+whatsapp)?[.!?]*$",
            r"^(?P<mode>video\s+call|voice\s+call|call)\s+(?P<contact>.+?)\s+(?:on|via|using)\s+whatsapp[.!?]*$",
        )
        for pattern in patterns:
            match = re.match(pattern, text, flags=re.IGNORECASE)
            if match:
                mode = "video" if "video" in match.group("mode").lower() else "voice"
                contact = self._clean_whatsapp_contact(match.group("contact"))
                return {"mode": mode, "contact": contact}
        return None

    def _extract_whatsapp_message_intent(self, command: str) -> dict[str, str] | None:
        text = self._normalize_spoken_command(command).strip()
        patterns = (
            r"^(?:send\s+(?:a\s+)?(?:whatsapp\s+)?(?:message|text)\s+to|whatsapp\s+message\s+to|message\s+on\s+whatsapp\s+to)\s+(?P<receiver>.+?)(?:\s+(?:saying|that says|text|message)\s+(?P<message>.+?))?[.!?]*$",
            r"^(?:message|text)\s+(?P<receiver>[A-Za-z][A-Za-z0-9_ .'’-]*?)\s+(?P<message>.+?)[.!?]*$",
            r"^(?:message|text)\s+(?P<receiver>.+?)(?:\s+(?:on|via|using)\s+whatsapp)?(?:\s+(?:saying|that says|text|message)\s+(?P<message>.+?))?[.!?]*$",
        )
        for pattern in patterns:
            match = re.match(pattern, text, flags=re.IGNORECASE)
            if match:
                receiver = self._clean_whatsapp_contact(match.group("receiver"))
                message = (match.group("message") or "").strip().rstrip(".!?")
                return {"receiver": receiver, "message": message}
        return None

    def _clean_whatsapp_contact(self, value: str) -> str:
        contact = (value or "").strip().strip(" ,;.!?")
        contact = re.sub(r"\s+(?:on|via|using)\s+whatsapp$", "", contact, flags=re.IGNORECASE).strip()
        return contact

    def _repair_whatsapp_message_contact(self, receiver: str, message: str) -> tuple[str, str]:
        if self._whatsapp_contacts_provider is None or not receiver or not message:
            return receiver, message
        words = message.split()
        best_receiver = receiver
        best_message = message
        best_score = 0.0
        for count in range(1, min(4, len(words)) + 1):
            candidate_receiver = " ".join([receiver, *words[:count]]).strip()
            candidate_message = " ".join(words[count:]).strip()
            if not candidate_message:
                continue
            decision = self._resolve_whatsapp_contact(candidate_receiver)
            contact = dict(decision.get("contact") or {}) if decision.get("status") in {"auto_call", "confirm_contact"} else {}
            score = float(contact.get("score") or 0.0)
            if score > best_score:
                best_score = score
                best_receiver = candidate_receiver
                best_message = candidate_message
        if best_score >= self.contact_match_service.HIGH_CONFIDENCE:
            return best_receiver, best_message
        return receiver, message

    def _is_ambiguous_communication_contact(self, value: str) -> bool:
        contact = self._normalize_spoken_command(value).lower().strip(" ,;.!?")
        contact = re.sub(r"^(?:a|the)\s+", "", contact)
        return contact in {
            "someone",
            "somebody",
            "anyone",
            "anybody",
            "person",
            "him",
            "her",
            "them",
            "that person",
            "this person",
        }

    def _whatsapp_contact_required_result(self, kind: str, payload: dict[str, object] | None = None) -> Dict[str, object]:
        payload = dict(payload or {})
        self._pending_whatsapp_clarification = {"kind": kind, "payload": payload}
        is_message = kind in {"send_message", "send_message_text"}
        prompt = "Who should I message on WhatsApp?" if is_message else "Who should I call on WhatsApp?"
        return self._status_result(
            "whatsapp_contact_required",
            prompt,
            success=False,
            status="whatsapp_contact_required",
        )

    def _whatsapp_call_pending_result(self, mode: str, contact: str) -> Dict[str, object]:
        message = f"Ready to call {contact} on WhatsApp. Say yes to continue or no to cancel."
        return {
            "success": False,
            "action": "whatsapp_call_pending",
            "message": message,
            "pending": {"mode": mode, "contact": contact},
            "requires_step_up": False,
            "actions": [{"type": "show_status", "status": "whatsapp_call_pending", "message": message}],
        }

    def _whatsapp_message_pending_result(self, contact: dict[str, object], message_text: str, fallback_receiver: str) -> Dict[str, object]:
        display_name = str(contact.get("display_name") or fallback_receiver).strip()
        message = f"Ready to send this via whatsapp to {display_name}: \"{message_text}\". Say yes to send or no to cancel."
        return {
            "success": False,
            "action": "send_message_pending",
            "message": message,
            "pending": {
                "platform": "whatsapp",
                "receiver": display_name,
                "message": message_text,
                "contact_id": str(contact.get("contact_id") or "").strip(),
                "phone_number": str(contact.get("phone_number") or "").strip(),
                "match_confidence": contact.get("score"),
                "match_reason": str(contact.get("reason") or "").strip(),
                "risk_level": "HIGH_RISK",
                "expires_at": time.time() + 90,
            },
            "requires_step_up": False,
            "actions": [{"type": "show_status", "status": "whatsapp_message_pending", "message": message}],
        }

    def _prepare_whatsapp_call_confirmation(self, mode: str, query: str) -> Dict[str, object]:
        decision = self._resolve_whatsapp_contact(query)
        if decision["status"] == "not_found":
            return self._status_result(
                "whatsapp_contact_not_found",
                str(decision["message"]),
                success=False,
                status="whatsapp_contact_not_found",
            )
        if decision["status"] == "clarify":
            candidates = list(decision.get("candidates") or [])
            self._pending_whatsapp_clarification = {
                "kind": "whatsapp_call",
                "payload": {
                    "mode": mode,
                    "query": query,
                    "candidates": candidates,
                    "message": str(decision["message"]),
                },
            }
            return self._status_result(
                "whatsapp_contact_ambiguous",
                str(decision["message"]),
                success=False,
                status="whatsapp_contact_required",
            )
        if decision["status"] == "confirm_contact":
            contact = dict(decision["contact"])
            message = str(decision.get("message") or f"I found {contact.get('display_name')}. Did you mean {contact.get('display_name')}?")
            self._pending_whatsapp_clarification = {
                "kind": "pending_whatsapp_contact_resolution",
                "payload": {
                    "original_user_input": query,
                    "intended_action": "call" if mode == "voice" else "video_call",
                    "raw_contact_text": query,
                    "fuzzy_candidates": [contact],
                    "selected_contact": contact,
                    "mode": mode,
                },
            }
            return self._status_result(
                "whatsapp_contact_fuzzy",
                message,
                success=False,
                status="whatsapp_contact_fuzzy",
            )

        contact = dict(decision["contact"])
        display_name = str(contact.get("display_name") or query).strip()
        pending = {
            "mode": mode,
            "contact": display_name,
            "contact_id": str(contact.get("contact_id") or "").strip(),
            "phone_number": str(contact.get("phone_number") or "").strip(),
            "match_confidence": contact.get("score"),
            "match_reason": str(contact.get("reason") or "").strip(),
            "risk_level": "HIGH_RISK",
            "expires_at": time.time() + 90,
        }
        result = self._whatsapp_call_pending_result(mode, display_name)
        result["pending"] = pending
        return result

    def _prepare_whatsapp_message_confirmation(self, receiver_query: str, message_text: str) -> Dict[str, object]:
        if self._whatsapp_contacts_provider is None and not isinstance(self.message_action_service, MessageActionService):
            return self.message_action_service.prepare("whatsapp", receiver_query, message_text)
        decision = self._resolve_whatsapp_contact(receiver_query)
        if decision["status"] == "not_found":
            return self._status_result(
                "whatsapp_contact_not_found",
                str(decision["message"]),
                success=False,
                status="whatsapp_contact_not_found",
            )
        if decision["status"] == "clarify":
            candidates = list(decision.get("candidates") or [])
            self._pending_whatsapp_clarification = {
                "kind": "pending_whatsapp_contact_resolution",
                "payload": {
                    "original_user_input": receiver_query,
                    "intended_action": "message",
                    "raw_contact_text": receiver_query,
                    "fuzzy_candidates": candidates,
                    "message_text": message_text,
                    "message": str(decision["message"]),
                },
            }
            return self._status_result(
                "whatsapp_contact_ambiguous",
                str(decision["message"]),
                success=False,
                status="whatsapp_contact_required",
            )
        if decision["status"] == "confirm_contact":
            contact = dict(decision["contact"])
            message = str(decision.get("message") or f"I found {contact.get('display_name')}. Did you mean {contact.get('display_name')}?")
            self._pending_whatsapp_clarification = {
                "kind": "pending_whatsapp_contact_resolution",
                "payload": {
                    "original_user_input": receiver_query,
                    "intended_action": "message",
                    "raw_contact_text": receiver_query,
                    "fuzzy_candidates": [contact],
                    "selected_contact": contact,
                    "message_text": message_text,
                },
            }
            return self._status_result(
                "whatsapp_contact_fuzzy",
                message,
                success=False,
                status="whatsapp_contact_fuzzy",
            )

        contact = dict(decision["contact"])
        return self._whatsapp_message_pending_result(contact, message_text, receiver_query)

    def _resolve_whatsapp_contact(self, query: str) -> dict[str, object]:
        contact_query = self._clean_whatsapp_contact(query)
        contacts = self._load_whatsapp_contacts()
        if contacts is None:
            return {
                "status": "auto_call",
                "contact": {
                    "display_name": contact_query,
                    "score": None,
                    "reason": "unindexed_name",
                },
            }
        ranked = self.contact_match_service.rank_contacts(contact_query, contacts)
        decision = self.contact_match_service.decide(contact_query, ranked)
        if decision.status == "auto_call":
            candidate = decision.candidates[0]
            return {"status": "auto_call", "contact": self._contact_candidate_payload(candidate)}
        if decision.status == "confirm_contact":
            candidate = decision.candidates[0]
            return {
                "status": "confirm_contact",
                "contact": self._contact_candidate_payload(candidate),
                "message": decision.message,
            }
        if decision.status == "clarify":
            candidates = [self._contact_candidate_payload(candidate) for candidate in decision.candidates]
            return {
                "status": "clarify",
                "message": self._build_whatsapp_contact_clarification(contact_query, candidates),
                "candidates": candidates,
            }
        return {
            "status": "not_found",
            "message": decision.message or f"I couldn't find {contact_query} in your contacts.",
        }

    def _load_whatsapp_contacts(self) -> list[ContactCandidate] | None:
        if self._whatsapp_contacts_provider is None:
            return None
        try:
            contacts = list(self._whatsapp_contacts_provider() or [])
        except Exception:
            return []
        normalized: list[ContactCandidate] = []
        for item in contacts:
            if isinstance(item, ContactCandidate):
                normalized.append(item)
            elif isinstance(item, dict):
                normalized.append(ContactCandidate(**item))
        return normalized

    def _contact_candidate_payload(self, candidate: ContactCandidate) -> dict[str, object]:
        return {
            "contact_id": candidate.contact_id,
            "display_name": candidate.display_name,
            "phone_number": candidate.phone_number,
            "aliases": list(candidate.aliases),
            "favorite": candidate.favorite,
            "recent": candidate.recent,
            "frequent": candidate.frequent,
            "score": candidate.score,
            "reason": candidate.reason,
        }

    def _build_whatsapp_contact_clarification(self, query: str, candidates: list[dict[str, object]]) -> str:
        names = [str(candidate.get("display_name") or "").strip() for candidate in candidates if str(candidate.get("display_name") or "").strip()]
        if not names:
            return f"Which {query} should I call on WhatsApp?"
        if len(names) == 1:
            return f"Did you mean {names[0]}?"
        return f"Which {query} should I call on WhatsApp: {', '.join(names[:-1])}, or {names[-1]}?"

    def _resolve_pending_whatsapp_candidate(self, reply: str, candidates_payload: list[dict[str, object]]) -> dict[str, object] | None:
        candidates = [
            ContactCandidate(
                contact_id=str(candidate.get("contact_id") or ""),
                display_name=str(candidate.get("display_name") or ""),
                phone_number=str(candidate.get("phone_number") or ""),
                aliases=list(candidate.get("aliases") or []),
                favorite=bool(candidate.get("favorite", False)),
                recent=bool(candidate.get("recent", False)),
                frequent=bool(candidate.get("frequent", False)),
                score=float(candidate.get("score") or 0.0),
                reason=str(candidate.get("reason") or ""),
            )
            for candidate in candidates_payload
        ]
        key = "automation_whatsapp"
        self.contact_match_service.save_clarification(key, candidates, call_method="whatsapp", ttl_seconds=60)
        resolved = self.contact_match_service.resolve_clarification(key, reply)
        return self._contact_candidate_payload(resolved) if resolved else None

    def _stage_resolved_whatsapp_action(self, payload: dict[str, object], resolved: dict[str, object]) -> Dict[str, object]:
        intended_action = str(payload.get("intended_action") or "").strip()
        if intended_action in {"call", "video_call"}:
            mode = "video" if intended_action == "video_call" else str(payload.get("mode") or "voice")
            mode = "video" if mode == "video" else "voice"
            display_name = str(resolved.get("display_name") or payload.get("raw_contact_text") or "").strip()
            result = self._whatsapp_call_pending_result(mode, display_name)
            result["pending"] = {
                "mode": mode,
                "contact": display_name,
                "contact_id": str(resolved.get("contact_id") or ""),
                "phone_number": str(resolved.get("phone_number") or ""),
                "match_confidence": resolved.get("score"),
                "match_reason": str(resolved.get("reason") or ""),
                "risk_level": "HIGH_RISK",
                "expires_at": time.time() + 90,
            }
            self._pending_mark_action = {"kind": "whatsapp_call", "payload": dict(result["pending"])}
            return result

        if intended_action == "message":
            message_text = str(payload.get("message_text") or "").strip()
            if not message_text:
                self._pending_whatsapp_clarification = {
                    "kind": "send_message_text",
                    "payload": {"platform": "whatsapp", "receiver": str(resolved.get("display_name") or "")},
                }
                return self._status_result(
                    "whatsapp_message_text_required",
                    f"What should I say to {resolved.get('display_name')} on WhatsApp?",
                    success=False,
                    status="whatsapp_message_text_required",
                )
            result = self._whatsapp_message_pending_result(resolved, message_text, str(payload.get("raw_contact_text") or ""))
            self._pending_mark_action = {"kind": "send_message", "payload": dict(result.get("pending") or {})}
            return result

        return {"success": False, "action": "unsupported", "message": "That WhatsApp contact confirmation expired."}

    def _handle_whatsapp_clarification_followup(self, command: str) -> Dict[str, object]:
        pending = self._pending_whatsapp_clarification or {}
        reply = self._normalize_spoken_command(command).strip()
        lowered = reply.lower()
        if lowered in {"no", "n", "cancel", "stop", "never mind", "nevermind"}:
            self._pending_whatsapp_clarification = None
            return {"success": True, "action": "confirmation_cancelled", "message": "Cancelled."}

        kind = str(pending.get("kind") or "")
        payload = dict(pending.get("payload") or {})

        if kind == "pending_whatsapp_contact_resolution":
            candidates = list(payload.get("fuzzy_candidates") or [])
            selected = dict(payload.get("selected_contact") or {}) if isinstance(payload.get("selected_contact"), dict) else {}
            resolved = None
            if selected and lowered in {"yes", "y", "confirm", "go ahead"}:
                resolved = selected
            elif candidates:
                resolved = self._resolve_pending_whatsapp_candidate(reply, candidates)

            if not resolved:
                self._pending_whatsapp_clarification = pending
                return self._status_result(
                    "whatsapp_contact_ambiguous",
                    str(payload.get("message") or "Which contact did you mean?"),
                    success=False,
                    status="whatsapp_contact_required",
                )

            self._pending_whatsapp_clarification = None
            return self._stage_resolved_whatsapp_action(payload, resolved)

        if kind == "send_message_text":
            self._pending_whatsapp_clarification = None
            receiver = str(payload.get("receiver") or "").strip()
            message_result = self._prepare_whatsapp_message_confirmation(receiver, reply)
            message_pending = message_result.get("pending") if isinstance(message_result, dict) else None
            if message_pending:
                self._pending_mark_action = {"kind": "send_message", "payload": message_pending}
            return message_result

        contact = self._clean_whatsapp_contact(reply)
        if not contact or self._is_ambiguous_communication_contact(contact) or self.looks_like_confirmation_response(contact):
            return self._whatsapp_contact_required_result(kind, payload)

        self._pending_whatsapp_clarification = None
        if kind == "whatsapp_call":
            candidates = list(payload.get("candidates") or [])
            if candidates:
                resolved = self._resolve_pending_whatsapp_candidate(contact, candidates)
                if not resolved:
                    return self._status_result(
                        "whatsapp_contact_ambiguous",
                        str(payload.get("message") or "Which contact should I call on WhatsApp?"),
                        success=False,
                        status="whatsapp_contact_required",
                    )
                mode = str(payload.get("mode") or "voice")
                display_name = str(resolved.get("display_name") or contact).strip()
                result = self._whatsapp_call_pending_result(mode, display_name)
                result["pending"] = {
                    "mode": mode,
                    "contact": display_name,
                    "contact_id": str(resolved.get("contact_id") or ""),
                    "phone_number": str(resolved.get("phone_number") or ""),
                    "match_confidence": resolved.get("score"),
                    "match_reason": str(resolved.get("reason") or ""),
                }
            else:
                result = self._prepare_whatsapp_call_confirmation(str(payload.get("mode") or "voice"), contact)
            if dict(result.get("pending") or {}):
                self._pending_mark_action = {"kind": "whatsapp_call", "payload": dict(result.get("pending") or {})}
            return result
        if kind == "send_message":
            message = str(payload.get("message") or "").strip()
            if not message:
                self._pending_whatsapp_clarification = {
                    "kind": "send_message_text",
                    "payload": {"platform": "whatsapp", "receiver": contact},
                }
                return self._status_result(
                    "whatsapp_message_text_required",
                    f"What should I say to {contact} on WhatsApp?",
                    success=False,
                    status="whatsapp_message_text_required",
                )
            message_result = self._prepare_whatsapp_message_confirmation(contact, message)
            message_pending = message_result.get("pending") if isinstance(message_result, dict) else None
            if message_pending:
                self._pending_mark_action = {"kind": "send_message", "payload": message_pending}
            return message_result

        self._pending_whatsapp_clarification = None
        return {"success": False, "action": "unsupported", "message": "That WhatsApp clarification expired."}

    def _status_result(self, action: str, message: str, *, success: bool = False, status: str = "status") -> Dict[str, object]:
        return {
            "success": success,
            "action": action,
            "message": message,
            "display_text": message,
            "actions": [{"type": "show_status", "status": status, "message": message, "action": action}],
        }

    def _looks_like_send_message(self, lowered: str) -> bool:
        return bool(re.search(r"\b(?:send|message|text)\b.*\b(?:whatsapp|telegram|instagram|insta)\b", lowered))

    def _prepare_message_action(self, command: str) -> Dict[str, str | bool] | None:
        patterns = [
            r"^(?:send\s+(?:a\s+)?(?:message|text)\s+)?(?:on\s+)?(?P<platform>whatsapp|telegram|instagram|insta)(?:\s+message)?\s+to\s+(?P<receiver>.+?)\s+(?:saying|that says|message|text)\s+(?P<message>.+?)[.!?]*$",
            r"^send\s+(?:a\s+)?(?P<platform>whatsapp|telegram|instagram|insta)(?:\s+message)?\s+to\s+(?P<receiver>.+?)\s+(?:saying|that says|message|text)\s+(?P<message>.+?)[.!?]*$",
        ]
        for pattern in patterns:
            match = re.match(pattern, command, flags=re.IGNORECASE)
            if match:
                platform = match.group("platform").strip()
                receiver = match.group("receiver").strip()
                message = match.group("message").strip().rstrip(".!?")
                return self.message_action_service.prepare(platform, receiver, message)
        return None

    def _looks_like_browser_control(self, lowered: str) -> bool:
        return bool(re.match(
            r"^(?:browser|in browser|on browser|playwright|open url|go to|browser search|search browser|"
            r"click browser|browser click|type in browser|browser type|smart type in browser|fill form|"
            r"get page text|read page text|close browser|incognito)\b",
            lowered,
        ))

    def _execute_browser_control(self, command: str) -> Dict[str, str | bool] | None:
        return self._execute_browser_tool(command)

    def _execute_browser_control_legacy(self, command: str) -> Dict[str, str | bool] | None:
        tool = BrowserTool(BrowserConnector(self.browser_control_service))
        return tool.execute(ToolContext(command=command, intent="browser"))

    def _execute_browser_command_legacy(self, command: str, context=None) -> Dict[str, str | bool] | None:
        normalized_text = self._normalize_spoken_command(command)
        lowered = normalized_text.lower()

        control_result = self._execute_browser_control_legacy(normalized_text)
        if control_result is not None:
            return control_result

        google_search_match = re.match(
            r"^(?:google search|search google for|search)\s+(.+?)(?:\s+on\s+google)?[.!?]*$",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if google_search_match and ("google" in lowered or lowered.startswith("search ")):
            query = google_search_match.group(1).strip()
            query = re.sub(r"\s+on\s+google$", "", query, flags=re.IGNORECASE).strip()
            return self._google_search(query)

        youtube_search_match = re.match(
            r"^(?:youtube search|search youtube for)\s+(.+?)[.!?]*$",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if youtube_search_match:
            return self._youtube_search(youtube_search_match.group(1).strip())

        youtube_play_match = re.match(
            r"^play\s+(.+?)\s+(?:on|in)\s+youtube[.!?]*$",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if youtube_play_match:
            return self._play_media(youtube_play_match.group(1).strip())

        open_match = re.match(
            r"^(?:open|launch|start)\s+(.+?)[.!?]*$",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if open_match:
            return self._open_target(open_match.group(1).strip())

        return None

    def _looks_like_computer_control(self, lowered: str) -> bool:
        return bool(re.match(
            r"^(?:smart type|clear field and type|paste|press key|press|hotkey|shortcut|click|double click|"
            r"right click|scroll|take screenshot|screenshot|focus window|clipboard|read clipboard|paste text)\b",
            lowered,
        ))

    def _execute_computer_control(self, command: str) -> Dict[str, str | bool] | None:
        match = re.match(r"^(?:smart type|clear field and type)\s+(.+?)[.!?]*$", command, flags=re.IGNORECASE)
        if match:
            return self.computer_control_service.type_text(match.group(1).strip(), clear_first=True)

        match = re.match(r"^(?:paste text|paste)\s+(.+?)[.!?]*$", command, flags=re.IGNORECASE)
        if match:
            return self.computer_control_service.paste_text(match.group(1).strip())

        match = re.match(r"^(?:press key|press)\s+(.+?)[.!?]*$", command, flags=re.IGNORECASE)
        if match:
            return self.computer_control_service.press(match.group(1).strip())

        match = re.match(r"^(?:hotkey|shortcut)\s+(.+?)[.!?]*$", command, flags=re.IGNORECASE)
        if match:
            keys = [part.strip() for part in re.split(r"\s*\+\s*|\s+and\s+", match.group(1)) if part.strip()]
            return self.computer_control_service.hotkey(keys)

        coord_match = re.match(r"^(?P<button>right\s+click|double\s+click|click)(?:\s+(?P<x>\d+)\s*,?\s+(?P<y>\d+))?[.!?]*$", command, flags=re.IGNORECASE)
        if coord_match:
            button_phrase = coord_match.group("button").lower()
            button = "right" if "right" in button_phrase else "left"
            clicks = 2 if "double" in button_phrase else 1
            x = int(coord_match.group("x")) if coord_match.group("x") else None
            y = int(coord_match.group("y")) if coord_match.group("y") else None
            return self.computer_control_service.click(x, y, button=button, clicks=clicks)

        match = re.match(r"^scroll\s*(up|down)?(?:\s+(\d+))?[.!?]*$", command, flags=re.IGNORECASE)
        if match:
            return self.computer_control_service.scroll(match.group(1) or "down", int(match.group(2) or 3))

        if re.match(r"^(?:take screenshot|screenshot)[.!?]*$", command, flags=re.IGNORECASE):
            return self.computer_control_service.screenshot()

        match = re.match(r"^focus window\s+(.+?)[.!?]*$", command, flags=re.IGNORECASE)
        if match:
            return self.computer_control_service.focus_window(match.group(1).strip())

        if re.match(r"^(?:clipboard|read clipboard)[.!?]*$", command, flags=re.IGNORECASE):
            return self.computer_control_service.clipboard_copy()

        return None

    def _looks_like_youtube_tool(self, lowered: str) -> bool:
        return bool(
            "youtube" in lowered
            and any(token in lowered for token in ("summarize", "summary", "transcript", "metadata", "info", "trending"))
        )

    def _execute_youtube_tool(self, command: str) -> Dict[str, str | bool] | None:
        lowered = command.lower()
        url_match = re.search(r"(https?://\S+|youtu\.be/\S+|youtube\.com/\S+)", command, flags=re.IGNORECASE)
        url = url_match.group(1).strip(" .!?") if url_match else ""
        if "summar" in lowered or "transcript" in lowered:
            if not url and self._last_web_target and "youtu" in self._last_web_target:
                url = self._last_web_target
            return self.youtube_tools_service.summarize(url)
        if "metadata" in lowered or re.search(r"\binfo\b", lowered):
            if not url and self._last_web_target and "youtu" in self._last_web_target:
                url = self._last_web_target
            return self.youtube_tools_service.info(url)
        if "trending" in lowered:
            region_match = re.search(r"\b(?:in|for)\s+([a-z]{2})\b", lowered)
            return self.youtube_tools_service.trending((region_match.group(1) if region_match else "US").upper())
        return None

    def _looks_like_extended_setting(self, lowered: str) -> bool:
        normalized = self._normalize_extended_setting(lowered)
        return self.computer_settings_service.can_handle(normalized)

    def _normalize_extended_setting(self, lowered: str) -> str:
        return re.sub(r"^(?:please\s+)?(?:do\s+)?(?:computer\s+)?", "", lowered).strip(" .!?")

    def _looks_like_safe_command_info(self, lowered: str) -> bool:
        explicit = (
            "safe command",
            "run safe command",
            "system info",
            "computer info",
            "hardware info",
            "pc info",
            "disk space",
            "disk usage",
            "storage",
            "free space",
            "running processes",
            "list processes",
            "ip address",
            "network info",
            "wifi networks",
            "cpu usage",
            "memory usage",
            "ram usage",
            "windows version",
            "os version",
            "battery",
            "battery level",
            "current time",
            "current date",
        )
        return any(phrase in lowered for phrase in explicit) or lowered.startswith(("run command ", "cmd "))

    def _split_compound_commands(self, command: str) -> list[str]:
        cleaned = self._normalize_spoken_command(command)
        if not cleaned:
            return []

        verb_pattern = r"(?:open|launch|start|close|kill|play|type|paste|google search|youtube search|search google for|search youtube for)"
        repeated = re.findall(rf"(?i)\b{verb_pattern}\b[^,;]*?(?=(?:\b{verb_pattern}\b|$))", cleaned)
        repeated = [part.strip(" ,;") for part in repeated if part.strip(" ,;")]
        if len(repeated) > 1:
            return repeated

        open_match = re.match(r"^(open|launch|start)\s+(.+)$", cleaned, flags=re.IGNORECASE)
        if open_match:
            verb = open_match.group(1).lower()
            remainder = open_match.group(2).strip()
            parts = [p.strip() for p in re.split(r"\s+(?:and|,)\s+", remainder, flags=re.IGNORECASE) if p.strip()]
            if len(parts) > 1:
                normalized_parts = [self._normalize_compound_part(verb, part) for part in parts]
                return normalized_parts

        close_match = re.match(r"^(close|kill)\s+(.+)$", cleaned, flags=re.IGNORECASE)
        if close_match:
            verb = close_match.group(1).lower()
            remainder = close_match.group(2).strip()
            parts = [p.strip() for p in re.split(r"\s+(?:and|,)\s+", remainder, flags=re.IGNORECASE) if p.strip()]
            if len(parts) > 1:
                return [f"{verb} {part}" for part in parts]

        return [cleaned]

    def _normalize_compound_part(self, leading_verb: str, part: str) -> str:
        cleaned = part.strip(" ,;.!?")
        lowered = cleaned.lower()
        if re.fullmatch(r"search youtube", lowered):
            return "open youtube"
        if re.fullmatch(r"search google", lowered):
            return "open google"
        if lowered.startswith("search youtube for "):
            return "youtube search " + cleaned[19:].strip()
        if lowered.startswith("search google for "):
            return "google search " + cleaned[18:].strip()
        if re.match(r"^(?:whatsapp\s+)?(?:call|voice\s+call|video\s+call|message|text|send\s+(?:a\s+)?message|send\s+(?:a\s+)?text)\b", lowered):
            return cleaned
        return f"{leading_verb} {cleaned}"

    def _execute_multi_action_commands(self, commands: list[str]) -> Dict[str, str | bool]:
        results = [self.execute(single) for single in commands]
        successes = [result for result in results if bool(result.get("success"))]
        messages = [str(result.get("message", "")).strip() for result in results if str(result.get("message", "")).strip()]
        actions = []
        for result in results:
            actions.extend(list(result.get("actions") or []))
        clarification = next(
            (
                result
                for result in reversed(results)
                if any(
                    action.get("status") in {"whatsapp_contact_required", "whatsapp_message_text_required"}
                    for action in (result.get("actions") or [])
                    if isinstance(action, dict)
                )
            ),
            None,
        )
        message = str(clarification.get("message") or "") if clarification else " ".join(messages)
        return {
            "success": len(successes) == len(results),
            "action": "multi_action",
            "message": message,
            "display_text": message,
            "spoken_text": message,
            "actions": actions,
        }

    def _open_and_type(self, target: str, content: str, press_enter: bool = False) -> Dict[str, str | bool]:
        open_result = self._open_target(target, suppress_browser_prompt=True)
        if not bool(open_result.get("success")):
            return open_result

        type_result = self._type_text(
            content,
            press_enter=press_enter,
            delay_before=self._recommended_type_delay(target),
            focus_target=target,
        )
        if not bool(type_result.get("success")):
            return {
                "success": False,
                "action": "open_and_type",
                "message": f"{open_result['message']} {type_result['message']}",
            }

        return {
            "success": True,
            "action": "open_and_type",
            "message": f"{open_result['message']} {type_result['message']}",
        }

    def _open_target(self, target: str, suppress_browser_prompt: bool = False) -> Dict[str, str | bool]:
        if not target:
            return {"success": False, "action": "open", "message": "Tell me what app to open."}

        normalized_target = self._normalize_target(target)
        ambiguous_call = self._extract_whatsapp_call_intent(normalized_target)
        if ambiguous_call is not None and self._is_ambiguous_communication_contact(str(ambiguous_call.get("contact") or "")):
            return self._whatsapp_contact_required_result(
                "whatsapp_call",
                {"mode": str(ambiguous_call.get("mode") or "voice")},
            )
        ambiguous_message = self._extract_whatsapp_message_intent(normalized_target)
        if ambiguous_message is not None and self._is_ambiguous_communication_contact(str(ambiguous_message.get("receiver") or "")):
            return self._whatsapp_contact_required_result(
                "send_message",
                {"platform": "whatsapp", "message": str(ambiguous_message.get("message") or "")},
            )
        whatsapp_target = normalized_target.lower()
        if whatsapp_target in {"whatsapp", "whats app", "whatsapp desktop"}:
            return self._open_whatsapp_desktop_or_web()
        if whatsapp_target in {"whatsapp web", "web whatsapp"}:
            return self._open_whatsapp_web()

        explicit_open_choice = self._extract_explicit_open_choice(normalized_target)
        if explicit_open_choice["choice"] and explicit_open_choice["target"]:
            return self._open_explicit_choice(
                explicit_open_choice["target"],
                explicit_open_choice["choice"],
                suppress_browser_prompt=suppress_browser_prompt,
            )

        ambiguous_choice = self._get_ambiguous_open_target(normalized_target)
        if ambiguous_choice:
            self._pending_open_target = ambiguous_choice
            display_name = ambiguous_choice["display_name"]
            return {
                "success": False,
                "action": "open",
                "message": f"Do you want me to open {display_name} as the app or the website?",
            }

        web_target = self._resolve_web_target(normalized_target)
        if web_target:
            try:
                webbrowser.open(web_target)
                logger.info("[AUTOMATION] Opened web target: %s", web_target)
                return {
                    "success": True,
                    "action": "open",
                    "message": f"Opening {normalized_target}.",
                }
            except Exception as exc:
                return {
                    "success": False,
                    "action": "open",
                    "message": f"I could not open {normalized_target}: {exc}",
                }

        file_system_target = self._resolve_openable_path(normalized_target)
        if file_system_target is not None:
            try:
                os.startfile(str(file_system_target))
                self._remember_target(file_system_target)
                logger.info("[AUTOMATION] Opened path: %s", file_system_target)
                return {
                    "success": True,
                    "action": "open",
                    "message": f"Opening {self._display_target_name(file_system_target)}.",
                }
            except Exception as exc:
                return {
                    "success": False,
                    "action": "open",
                    "message": f"I could not open {self._display_target_name(file_system_target)}: {exc}",
                }

        fallback_result = self._direct_open_fallback(normalized_target)
        if fallback_result is not None and bool(fallback_result.get("success")):
            return self._finalize_open_result(
                normalized_target,
                fallback_result,
                suppress_browser_prompt=suppress_browser_prompt,
            )

        if not self._appopener_available:
            if fallback_result is not None:
                return fallback_result
            return self._appopener_unavailable("open")

        if self._is_protected_app(normalized_target):
            return {
                "success": False,
                "action": "open",
                "message": f"Opening {normalized_target} is blocked because it is a protected system app.",
            }
        candidates = self._appopener_candidates(normalized_target)

        for candidate in candidates:
            try:
                appopener_open(candidate, match_closest=True, output=False, throw_error=True)
                logger.info("[AUTOMATION] Opened app via AppOpener: %s", candidate)
                return {
                    "success": True,
                    "action": "open",
                    "message": f"Opening {normalized_target}.",
                }
            except Exception:
                continue

        if fallback_result is not None:
            return fallback_result

        failed_result = {
            "success": False,
            "action": "open",
            "message": f"I could not find an app matching {normalized_target}.",
        }
        self._pending_browser_search = None
        return failed_result

    def _open_whatsapp_desktop_or_web(self) -> Dict[str, object]:
        desktop_result = self.whatsapp_desktop.open()
        if bool(desktop_result.get("success")):
            message = "Opening WhatsApp Desktop."
            return {
                "success": True,
                "action": "open_whatsapp",
                "message": message,
                "display_text": message,
                "actions": [{"type": "show_status", "status": "whatsapp", "message": message}],
            }

        web_result = self._open_whatsapp_web()
        if bool(web_result.get("success")):
            web_result["message"] = "WhatsApp Desktop was unavailable, so I opened WhatsApp Web."
            web_result["display_text"] = web_result["message"]
            web_result["actions"] = [{"type": "show_status", "status": "whatsapp_web", "message": web_result["message"]}]
            return web_result

        return self._status_result(
            "open_whatsapp",
            f"WhatsApp Desktop could not be verified and WhatsApp Web fallback is unavailable. Desktop: {desktop_result.get('message')} Web: {web_result.get('message')}",
            success=False,
            status="whatsapp_unavailable",
        )

    def _open_whatsapp_web(self) -> Dict[str, object]:
        result = self.browser_control_service.execute("go_to", url="https://web.whatsapp.com", timeout=20)
        if not bool(result.get("success")):
            return self._status_result("open_whatsapp_web", str(result.get("message") or "Could not open WhatsApp Web."), success=False, status="whatsapp_web_unavailable")
        logged_in = self.browser_control_service.execute("whatsapp_logged_in", timeout=12)
        login_state = str(logged_in.get("message") or "")
        if login_state == "not_logged_in":
            return self._status_result(
                "open_whatsapp_web",
                "WhatsApp Web is open, but it is not logged in. Link a device before Jarvis can automate WhatsApp Web.",
                success=False,
                status="whatsapp_login_required",
            )
        message = "WhatsApp Web is open."
        return {
            "success": True,
            "action": "open_whatsapp_web",
            "message": message,
            "display_text": message,
            "actions": [{"type": "show_status", "status": "whatsapp_web", "message": message}],
        }

    def _send_whatsapp_message(self, payload: dict) -> Dict[str, object]:
        receiver = str(payload.get("receiver") or "").strip()
        message_body = str(payload.get("message") or "").strip()
        if not receiver or not message_body:
            return self._status_result("send_whatsapp_message", "Tell me the WhatsApp contact and message text.", success=False, status="whatsapp_missing_details")
        phone_number = str(payload.get("phone_number") or "").strip()
        if not phone_number and self._whatsapp_contacts_provider is not None:
            return self._status_result(
                "send_whatsapp_message",
                f"I found {receiver}, but the contact has no phone number for WhatsApp Desktop. I did not send the message.",
                success=False,
                status="whatsapp_missing_phone",
            )

        if phone_number:
            desktop = self.whatsapp_desktop.send_message(phone_number, message_body)
            if bool(desktop.get("success")):
                return self._status_result(
                    "send_whatsapp_message",
                    f"Sent the WhatsApp message to {receiver}.",
                    success=True,
                    status="whatsapp_message_sent",
                )
            if str(desktop.get("status") or "") != "whatsapp_desktop_unavailable":
                return self._status_result(
                    "send_whatsapp_message",
                    str(desktop.get("message") or "Jarvis could not verify WhatsApp Desktop. I did not send the message."),
                    success=False,
                    status=str(desktop.get("status") or "whatsapp_desktop_unverified"),
                )

        desktop = self._open_app_target("whatsapp", "WhatsApp Desktop", suppress_browser_prompt=True)
        if bool(desktop.get("success")):
            return self._status_result(
                "send_whatsapp_message",
                "WhatsApp Desktop opened, but Jarvis could not verify the recipient/message send state. I did not send the message.",
                success=False,
                status="whatsapp_desktop_unverified",
            )

        web = self._open_whatsapp_web()
        if not bool(web.get("success")):
            return web

        return self._status_result(
            "send_whatsapp_message",
            "WhatsApp Web fallback is available, but Jarvis could not verify a safe send selector. I did not send the message.",
            success=False,
            status="whatsapp_send_unverified",
        )

    def _start_whatsapp_call(self, payload: dict) -> Dict[str, object]:
        contact = str(payload.get("contact") or "").strip()
        mode = "video" if str(payload.get("mode") or "").lower() == "video" else "voice"
        if not contact:
            return self._status_result("whatsapp_call", "Tell me which WhatsApp contact to call.", success=False, status="whatsapp_missing_contact")
        phone_number = str(payload.get("phone_number") or "").strip()
        if not phone_number and self._whatsapp_contacts_provider is not None:
            return self._status_result(
                "whatsapp_call",
                f"I found {contact}, but the contact has no phone number for WhatsApp Desktop. I did not start the call.",
                success=False,
                status="whatsapp_missing_phone",
            )

        if phone_number:
            desktop_result = self.whatsapp_desktop.start_call(phone_number, mode)
            if bool(desktop_result.get("success")):
                self._active_whatsapp_call = {"contact": contact, "mode": mode, "started_at": time.time(), "phone_number": phone_number}
                return self._status_result(
                    "whatsapp_call",
                    f"Calling {contact}...",
                    success=True,
                    status="whatsapp_calling",
                )
            if str(desktop_result.get("status") or "") != "whatsapp_desktop_unavailable":
                return self._status_result(
                    "whatsapp_call",
                    str(desktop_result.get("message") or f"Jarvis could not verify the {mode} call UI for {contact}. I did not start the call."),
                    success=False,
                    status=str(desktop_result.get("status") or "whatsapp_desktop_unverified"),
                )

        desktop = self._open_app_target("whatsapp", "WhatsApp Desktop", suppress_browser_prompt=True)
        if bool(desktop.get("success")):
            if self._click_verified_whatsapp_call_button(contact, mode):
                self._active_whatsapp_call = {"contact": contact, "mode": mode, "started_at": time.time()}
                return self._status_result(
                    "whatsapp_call",
                    f"Calling {contact}...",
                    success=True,
                    status="whatsapp_calling",
                )
            return self._status_result(
                "whatsapp_call",
                f"WhatsApp Desktop opened, but Jarvis could not verify the {mode} call button for {contact}. I did not start the call.",
                success=False,
                status="whatsapp_desktop_unverified",
            )

        web = self._open_whatsapp_web()
        if not bool(web.get("success")):
            return web

        return self._status_result(
            "whatsapp_call",
            f"WhatsApp Web fallback is available, but Jarvis could not verify the {mode} call selector for {contact}. I did not start the call.",
            success=False,
            status="whatsapp_call_unverified",
        )

    def _click_verified_whatsapp_call_button(self, contact: str, mode: str) -> bool:
        return bool(self.whatsapp_desktop.click_call_button(mode))

    def _end_whatsapp_call(self) -> Dict[str, object]:
        desktop_result = self.whatsapp_desktop.end_call()
        if bool(desktop_result.get("success")):
            self._active_whatsapp_call = None
            return self._status_result(
                "end_whatsapp_call",
                "Ended the WhatsApp call.",
                success=True,
                status="whatsapp_call_ended",
            )
        if str(desktop_result.get("status") or "") != "whatsapp_desktop_unavailable":
            return self._status_result(
                "end_whatsapp_call",
                str(desktop_result.get("message") or "Jarvis could not verify an active WhatsApp call. I did not click anything."),
                success=False,
                status=str(desktop_result.get("status") or "whatsapp_end_call_unverified"),
            )
        web = self._open_whatsapp_web()
        if not bool(web.get("success")):
            return web
        return self._status_result(
            "end_whatsapp_call",
            "WhatsApp Web is open, but Jarvis could not verify an active call end button. I did not click anything.",
            success=False,
            status="whatsapp_end_call_unverified",
        )

    def _close_target(self, target: str) -> Dict[str, str | bool]:
        if not target:
            return {"success": False, "action": "close", "message": "Tell me what app to close."}

        normalized_target = self._normalize_target(target)
        if normalized_target.lower() in {"website", "site", "web site", "browser tab", "tab"}:
            if self._last_browser_choice:
                normalized_target = self._last_browser_choice
            else:
                return {
                    "success": False,
                    "action": "close",
                    "message": "Tell me which browser app to close, like Chrome or Edge.",
                }
        if self._is_protected_close_target(normalized_target):
            return {
                "success": False,
                "action": "close",
                "message": f"Closing {normalized_target} is blocked because it is a protected shell or system app.",
            }

        fallback_result = self._direct_close_fallback(normalized_target)
        if fallback_result is not None and bool(fallback_result.get("success")):
            return fallback_result

        if not self._appopener_available:
            if fallback_result is not None:
                return fallback_result
            return self._appopener_unavailable("close")

        if self._is_protected_app(normalized_target):
            return {
                "success": False,
                "action": "close",
                "message": f"Closing {normalized_target} is blocked because it is a protected system app.",
            }
        candidates = self._appopener_candidates(normalized_target)

        for candidate in candidates:
            try:
                appopener_close(candidate, match_closest=True, output=False, throw_error=True)
                logger.info("[AUTOMATION] Closed app via AppOpener: %s", candidate)
                return {
                    "success": True,
                    "action": "close",
                    "message": f"Closing {normalized_target}.",
                }
            except Exception:
                continue

        if fallback_result is not None:
            return fallback_result

        return {
            "success": False,
            "action": "close",
            "message": f"I could not find an open app matching {normalized_target}.",
        }

    def _play_media(self, target: str) -> Dict[str, str | bool]:
        if not target:
            return {"success": False, "action": "play", "message": "Tell me what you want me to play."}

        query = target.strip()
        url = f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(query)}"
        try:
            self._open_url(url)
            self._last_web_target = url
            self._last_youtube_query = query
            logger.info("[AUTOMATION] Opened YouTube play search for: %s", query)
            return {"success": True, "action": "play", "message": f"Playing {query}."}
        except Exception as exc:
            return {"success": False, "action": "play", "message": f"I could not play {query}: {exc}"}

    def _play_first_result(self) -> Dict[str, str | bool]:
        if not self._last_youtube_query:
            return {
                "success": False,
                "action": "play",
                "message": "I do not have a recent YouTube search yet. Tell me what you want me to play first.",
            }
        return self._play_media(self._last_youtube_query)

    def _google_search(self, target: str, browser: str | None = None) -> Dict[str, str | bool]:
        if not target:
            return {"success": False, "action": "google_search", "message": "Tell me what you want me to search on Google."}

        query = target.strip()
        url = f"https://www.google.com/search?q={urllib.parse.quote_plus(query)}"
        try:
            self._open_url(url, browser=browser)
            self._last_web_target = url
            self._last_google_query = query
            logger.info("[AUTOMATION] Opened Google search for: %s", query)
            browser_text = f" in {self._normalize_target(browser)}" if browser else ""
            return {"success": True, "action": "google_search", "message": f"Searching Google for {query}{browser_text}."}
        except Exception as exc:
            return {"success": False, "action": "google_search", "message": f"I could not search Google for {query}: {exc}"}

    def _youtube_search(self, target: str, browser: str | None = None) -> Dict[str, str | bool]:
        if not target:
            return {"success": False, "action": "youtube_search", "message": "Tell me what you want me to search on YouTube."}

        query = target.strip()
        url = f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(query)}"
        try:
            self._open_url(url, browser=browser)
            self._last_web_target = url
            self._last_youtube_query = query
            logger.info("[AUTOMATION] Opened YouTube search for: %s", query)
            browser_text = f" in {self._normalize_target(browser)}" if browser else ""
            return {"success": True, "action": "youtube_search", "message": f"Searching YouTube for {query}{browser_text}."}
        except Exception as exc:
            return {"success": False, "action": "youtube_search", "message": f"I could not search YouTube for {query}: {exc}"}

    def _match_system_command(self, lowered: str) -> str | None:
        text = lowered.strip().rstrip(".!?")
        exact = {
            "mute": "mute",
            "mute system": "mute",
            "mute the system": "mute",
            "unmute": "unmute",
            "unmute system": "unmute",
            "unmute the system": "unmute",
            "volume up": "volume up",
            "turn volume up": "volume up",
            "turn the volume up": "volume up",
            "increase volume": "volume up",
            "volume down": "volume down",
            "turn volume down": "volume down",
            "turn the volume down": "volume down",
            "decrease volume": "volume down",
            "lower volume": "volume down",
            "show desktop": "show desktop",
            "show the desktop": "show desktop",
            "switch window": "switch window",
            "switch windows": "switch window",
            "switch app": "switch window",
            "switch apps": "switch window",
            "next window": "switch window",
            "close this window": "close current window",
            "close current window": "close current window",
            "close the current window": "close current window",
            "minimize window": "minimize window",
            "minimize this window": "minimize window",
            "minimize current window": "minimize window",
            "fullscreen": "fullscreen",
            "full screen": "fullscreen",
            "toggle fullscreen": "fullscreen",
            "open task manager": "task manager",
            "start task manager": "task manager",
            "launch task manager": "task manager",
        }
        if text in exact:
            return exact[text]
        return None

    def _system_command(self, command: str) -> Dict[str, str | bool]:
        if keyboard is None:
            return {
                "success": False,
                "action": "system",
                "message": f"Keyboard control is not available on this machine. Import error: {KEYBOARD_IMPORT_ERROR}",
            }

        keymap = {
            "mute": "volume mute",
            "unmute": "volume mute",
            "volume up": "volume up",
            "volume down": "volume down",
            "show desktop": "windows+d",
            "switch window": "alt+tab",
            "close current window": "alt+f4",
            "minimize window": "windows+down",
            "fullscreen": "f11",
            "task manager": "ctrl+shift+esc",
        }
        hotkey = keymap.get(command)
        if not hotkey:
            return {"success": False, "action": "system", "message": f"I don't know how to run the system command {command}."}

        try:
            keyboard.press_and_release(hotkey)
            logger.info("[AUTOMATION] Ran system command: %s", command)
            return {"success": True, "action": "system", "message": f"Done {command}."}
        except Exception as exc:
            return {"success": False, "action": "system", "message": f"I could not run {command}: {exc}"}

    def _type_text(
        self,
        text: str,
        press_enter: bool = False,
        delay_before: float = 0.0,
        focus_target: str = "",
    ) -> Dict[str, str | bool]:
        payload = (text or "").strip()
        if not payload:
            return {
                "success": False,
                "action": "type",
                "message": "Tell me what you want me to type.",
            }
        if keyboard is None:
            return {
                "success": False,
                "action": "type",
                "message": f"Typing is not available on this machine. Import error: {KEYBOARD_IMPORT_ERROR}",
            }
        try:
            if delay_before > 0:
                time.sleep(delay_before)
            self._prepare_typing_surface(focus_target)
            write_delay = 0.004 if len(payload) <= 120 else 0.0025
            keyboard.write(payload, delay=write_delay)
            if press_enter:
                time.sleep(0.08)
                keyboard.press_and_release("enter")
            logger.info("[AUTOMATION] Typed text into active window.")
            return {
                "success": True,
                "action": "type",
                "message": f"Typed {payload}." if not press_enter else f"Typed {payload} and pressed Enter.",
            }
        except Exception as exc:
            return {
                "success": False,
                "action": "type",
                "message": f"I could not type that text: {exc}",
            }

    def _prepare_typing_surface(self, target: str) -> None:
        if keyboard is None:
            return
        normalized_target = self._normalize_target(target).lower()
        if normalized_target in {"chrome", "google chrome", "edge", "microsoft edge"}:
            time.sleep(0.15)
            keyboard.press_and_release("ctrl+l")
            time.sleep(0.12)

    def _recommended_type_delay(self, target: str) -> float:
        normalized_target = self._normalize_target(target).lower()
        if normalized_target in {"chrome", "google chrome", "edge", "microsoft edge"}:
            return 1.45
        if normalized_target in {"notepad", "visual studio code", "vs code", "vscode"}:
            return 1.15
        return 1.0

    def _extract_explicit_open_choice(self, target: str) -> dict[str, str]:
        normalized_target = self._normalize_target(target)
        lowered = normalized_target.lower()
        for suffix, choice in (
            (" website", "website"),
            (" web site", "website"),
            (" site", "website"),
            (" web", "website"),
            (" app", "app"),
            (" application", "app"),
            (" desktop app", "app"),
            (" desktop", "app"),
        ):
            if lowered.endswith(suffix):
                explicit_target = normalized_target[: -len(suffix)].strip()
                return {"choice": choice, "target": explicit_target}
        return {"choice": "", "target": normalized_target}

    def _get_ambiguous_open_target(self, target: str) -> dict | None:
        lowered = self._normalize_target(target).lower()
        config = self.AMBIGUOUS_OPEN_TARGETS.get(lowered)
        if not config:
            return None
        return {
            **config,
            "display_name": lowered if lowered not in {"google chrome", "microsoft edge"} else ("Chrome" if "chrome" in lowered else "Edge"),
        }

    def _open_explicit_choice(self, target: str, choice: str, suppress_browser_prompt: bool = False) -> Dict[str, str | bool]:
        config = self._get_ambiguous_open_target(target)
        if not config:
            if choice == "website":
                url = self._resolve_web_target(target)
                if url:
                    self._open_url(url)
                    return {"success": True, "action": "open", "message": f"Opening {self._normalize_target(target)} as a website."}
            return self._open_target(target, suppress_browser_prompt=suppress_browser_prompt)

        self._pending_open_target = None
        if choice == "website":
            try:
                self._open_url(str(config["website_url"]))
                self._last_web_target = str(config["website_url"])
                return {
                    "success": True,
                    "action": "open",
                    "message": f"Opening {config['website_name']}.",
                }
            except Exception as exc:
                return {
                    "success": False,
                    "action": "open",
                    "message": f"I could not open {config['website_name']}: {exc}",
                }
        return self._open_app_target(
            str(config["app_target"]),
            str(config["app_name"]),
            suppress_browser_prompt=suppress_browser_prompt,
        )

    def _open_app_target(
        self,
        target: str,
        friendly_name: str = "",
        suppress_browser_prompt: bool = False,
    ) -> Dict[str, str | bool]:
        normalized_target = self._normalize_target(target)
        file_system_target = self._resolve_openable_path(normalized_target)
        if file_system_target is not None:
            try:
                os.startfile(str(file_system_target))
                self._remember_target(file_system_target)
                result = {
                    "success": True,
                    "action": "open",
                    "message": f"Opening {self._display_target_name(file_system_target)}.",
                }
                return self._finalize_open_result(
                    normalized_target,
                    result,
                    friendly_name=friendly_name,
                    suppress_browser_prompt=suppress_browser_prompt,
                )
            except Exception as exc:
                return {
                    "success": False,
                    "action": "open",
                    "message": f"I could not open {self._display_target_name(file_system_target)}: {exc}",
                }

        fallback_result = self._direct_open_fallback(normalized_target)
        if fallback_result is not None and bool(fallback_result.get("success")):
            return self._finalize_open_result(
                normalized_target,
                fallback_result,
                friendly_name=friendly_name,
                suppress_browser_prompt=suppress_browser_prompt,
            )

        if not self._appopener_available:
            if fallback_result is not None:
                return fallback_result
            return self._appopener_unavailable("open")

        if self._is_protected_app(normalized_target):
            return {
                "success": False,
                "action": "open",
                "message": f"Opening {normalized_target} is blocked because it is a protected system app.",
            }

        candidates = self._appopener_candidates(normalized_target)
        for candidate in candidates:
            try:
                appopener_open(candidate, match_closest=True, output=False, throw_error=True)
                logger.info("[AUTOMATION] Opened app via AppOpener: %s", candidate)
                label = friendly_name or normalized_target
                result = {
                    "success": True,
                    "action": "open",
                    "message": f"Opening {label}.",
                }
                return self._finalize_open_result(
                    normalized_target,
                    result,
                    friendly_name=friendly_name,
                    suppress_browser_prompt=suppress_browser_prompt,
                )
            except Exception:
                continue

        if fallback_result is not None:
            return fallback_result

        failed_result = {
            "success": False,
            "action": "open",
            "message": f"I could not find an app matching {normalized_target}.",
        }
        self._pending_browser_search = None
        return failed_result

    def _handle_open_clarification(self, command: str) -> Dict[str, str | bool]:
        pending = self._pending_open_target
        reply = self._normalize_spoken_command(command).lower()
        if not pending:
            return {"success": False, "action": "open", "message": "Tell me what you want me to open."}

        if any(token in reply for token in ("app", "application", "desktop")):
            return self._open_explicit_choice(str(pending["app_target"]), "app")

        if any(token in reply for token in ("website", "web site", "site", "web app", " web")):
            return self._open_explicit_choice(str(pending["app_target"]), "website")

        return {
            "success": False,
            "action": "open",
            "message": f"Tell me app or website for {pending['display_name']}.",
        }

    def _handle_browser_search_followup(self, command: str) -> Dict[str, str | bool]:
        pending = self._pending_browser_search
        if not pending or not self.has_pending_browser_search():
            return {"success": False, "action": "search", "message": "Tell me what you want me to search."}

        reply = self._normalize_spoken_command(command)
        lowered = reply.lower().strip()

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
        ) or lowered in {"mute", "unmute", "volume up", "volume down"}:
            self._pending_browser_search = None
            return self.execute(reply)

        if lowered in {"cancel", "never mind", "stop", "no", "skip", "nothing"}:
            self._pending_browser_search = None
            return {
                "success": True,
                "action": "search",
                "message": f"Okay, I opened {pending['display_name']} without searching anything.",
            }
        if lowered in {"thanks", "thank you", "okay", "ok"}:
            self._pending_browser_search = None
            return {
                "success": True,
                "action": "search",
                "message": f"Okay, {pending['display_name']} is ready.",
            }

        self._pending_browser_search = None
        browser = str(pending["browser"])

        youtube_match = re.match(r"^(?:search\s+)?youtube(?:\s+for)?\s+(.+)$", reply, flags=re.IGNORECASE)
        if youtube_match:
            return self._youtube_search(youtube_match.group(1).strip(), browser=browser)

        google_match = re.match(r"^(?:search\s+)?google(?:\s+for)?\s+(.+)$", reply, flags=re.IGNORECASE)
        if google_match:
            return self._google_search(google_match.group(1).strip(), browser=browser)

        cleaned_reply = re.sub(r"^(?:search(?:\s+(?:for|about))?|look up)\s+", "", reply, flags=re.IGNORECASE).strip()
        return self._google_search(cleaned_reply or reply, browser=browser)

    def _finalize_open_result(
        self,
        target: str,
        result: Dict[str, str | bool],
        friendly_name: str = "",
        suppress_browser_prompt: bool = False,
    ) -> Dict[str, str | bool]:
        if not bool(result.get("success")):
            self._pending_browser_search = None
            return result

        normalized_target = self._normalize_target(target).lower()
        if suppress_browser_prompt or normalized_target not in {"chrome", "google chrome", "edge", "microsoft edge"}:
            self._pending_browser_search = None
            return result

        display_name = "Chrome" if "chrome" in normalized_target else "Edge"
        self._last_browser_choice = normalized_target
        self._pending_browser_search = {
            "type": "browser_search",
            "browser": normalized_target,
            "display_name": display_name,
            "created_at": time.time(),
            "expires_at": time.time() + 45,
            "session_id": self._browser_session_id,
        }
        message = str(result.get("message", f"Opening {friendly_name or normalized_target}.")).strip()
        result["message"] = f"{message} What should I search in {display_name}?"
        return result

    def _normalize_target(self, target: str) -> str:
        cleaned = (target or "").strip().strip('"').strip("'")
        cleaned = re.sub(r"\b(show me|for me|please)\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"^(?:a|an|the)\s+", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bapp\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned.rstrip(".!?")

    def describe_recent_target(self, target_kind: str = "") -> Dict[str, str | bool] | None:
        kind = (target_kind or "").strip().lower()
        path: Path | None = None

        if kind in {"file", "that file"}:
            path = self._last_file_target
        elif kind in {"folder", "directory", "that folder"}:
            path = self._last_folder_target
        else:
            path = self._last_file_target or self._last_folder_target

        if path is None:
            return None

        if kind in {"file", "that file"}:
            label = "file"
        elif kind in {"folder", "directory", "that folder"}:
            label = "folder"
        else:
            label = "file" if path.suffix else "folder" if path.exists() and path.is_dir() else "item"
        return {
            "success": True,
            "action": "describe_recent_target",
            "message": f"Your last {label} is at {path}.",
            "path": str(path),
            "target_kind": label,
        }

    def _open_url(self, url: str, browser: str | None = None) -> None:
        normalized_browser = self._normalize_target(browser).lower() if browser else ""
        if normalized_browser:
            executable = self._resolve_browser_executable(normalized_browser)
            if executable:
                try:
                    subprocess.Popen([executable, url])
                    logger.info("[AUTOMATION] Opened URL in native browser %s: %s", normalized_browser, url)
                    return
                except Exception as exc:
                    logger.warning("[AUTOMATION] Native browser launch failed for %s: %s", normalized_browser, exc)
        else:
            try:
                if webbrowser.open(url):
                    logger.info("[AUTOMATION] Opened URL with system browser: %s", url)
                    return
            except Exception as exc:
                logger.warning("[AUTOMATION] System browser open failed: %s", exc)

        result = self.browser_control_service.execute("go_to", url=url)
        if not bool(result.get("success")):
            raise RuntimeError(str(result.get("message") or "Browser control failed."))
        logger.info("[AUTOMATION] BrowserControlService opened URL: %s", url)

    def _resolve_browser_process_name(self, browser: str) -> str | None:
        mapping = {
            "chrome": "chrome.exe",
            "google chrome": "chrome.exe",
            "edge": "msedge.exe",
            "microsoft edge": "msedge.exe",
        }
        return mapping.get(browser)

    def _is_process_running(self, executable_name: str) -> bool:
        if not executable_name:
            return False
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {executable_name}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except Exception:
            return False

        output = f"{result.stdout}\n{result.stderr}".lower()
        return executable_name.lower() in output

    def _resolve_browser_executable(self, browser: str) -> str | None:
        mapping = {
            "chrome": "chrome.exe",
            "google chrome": "chrome.exe",
            "edge": "msedge.exe",
            "microsoft edge": "msedge.exe",
        }
        executable_name = mapping.get(browser)
        if not executable_name:
            return None

        for root in filter(None, [getattr(winreg, "HKEY_CURRENT_USER", None), getattr(winreg, "HKEY_LOCAL_MACHINE", None)]):
            try:
                with winreg.OpenKey(
                    root,
                    rf"Software\Microsoft\Windows\CurrentVersion\App Paths\{executable_name}",
                ) as key:
                    value, _ = winreg.QueryValueEx(key, None)
                    if value:
                        return str(value)
            except Exception:
                continue

        return executable_name

    def _sanitize_file_reference(self, path_text: str) -> str:
        cleaned = (path_text or "").strip().strip('"').strip("'")
        cleaned = re.sub(r"\bin it\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\b(?:uh|um|er|ah)\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"^(?:for me\s+)?(?:please\s+)?", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bdot\s+([a-z0-9]{1,5})\b", r".\1", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned.rstrip(".!?")

    def _normalize_spoken_command(self, text: str) -> str:
        normalized = (text or "").strip()
        normalized = re.sub(r"\b(?:uh|um|er|ah)\b", "", normalized, flags=re.IGNORECASE)
        normalized = re.sub(
            r"^(?:jarvis|hey jarvis|hello jarvis|okay jarvis|ok jarvis|please jarvis)\s*[,:-]?\s*",
            "",
            normalized,
            flags=re.IGNORECASE,
        )
        normalized = re.sub(
            r"^(?:please|just|okay|ok|so|then|now)\s+",
            "",
            normalized,
            flags=re.IGNORECASE,
        )
        normalized = re.sub(
            r"^(?:can you|could you|would you|will you)\s+",
            "",
            normalized,
            flags=re.IGNORECASE,
        )
        normalized = re.sub(
            r"^(?:i want you to|i need you to)\s+",
            "",
            normalized,
            flags=re.IGNORECASE,
        )
        normalized = re.sub(
            r"^(?:tell|ask)\s+(?:jarvis|him|her|it)\s+to\s+",
            "",
            normalized,
            flags=re.IGNORECASE,
        )
        normalized = re.sub(r"\bdot\s+([a-z0-9]{1,5})\b", r".\1", normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"\b(file|folder|directory)\.\s+", r"\1 ", normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"\s*,\s*", " ", normalized)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized

    def _strip_named_prefix(self, value: str) -> str:
        value = re.sub(r"^(?:named|called|name)\s+(?:the\s+)?", "", value, flags=re.IGNORECASE)
        return value.strip()

    def _clean_location_phrase(self, value: str) -> str:
        cleaned = (value or "").strip().strip('"').strip("'")
        cleaned = re.sub(
            r"^(?:the\s+)?(?:folder\s+)?(?:path\s+)?(?:location\s+)?",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            r"^(?:on|in|at|inside|under|from)\s+",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned.rstrip(".!?")

    def _clean_file_name(self, value: str) -> str:
        cleaned = self._strip_named_prefix(value or "")
        cleaned = re.sub(r"^the\s+", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"^(?:the\s+)?(?:file|folder|directory)\s+", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+\.", ".", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned.rstrip(".!?")

    def _looks_like_windows_absolute_path(self, value: str) -> bool:
        return bool(re.match(r'^[A-Za-z]:[\\/]', (value or "").strip()))

    def _combine_location_and_name(self, location_text: str, name_text: str) -> Path:
        location_path = self._resolve_path(self._clean_location_phrase(location_text))
        file_name = self._clean_file_name(name_text)
        return location_path / Path(file_name.replace("/", "\\"))

    def _extract_path_from_sentence(self, text: str) -> Path | None:
        cleaned = self._sanitize_file_reference(text)
        if not cleaned:
            return None

        absolute_match = re.search(r'([A-Za-z]:[\\/][^"\']*)$', cleaned)
        if absolute_match:
            return Path(absolute_match.group(1).strip().replace("/", "\\"))

        patterns = [
            r"^(?P<name>.+?)\s+(?:on|in|at|inside|under|from)\s+(?P<location>.+)$",
            r"^(?:on|in|at|inside|under|from)\s+(?P<location>.+?)\s+(?:named|called|name)\s+(?P<name>.+)$",
            r"^(?P<location>desktop|documents|downloads|pictures|videos|music|home)\s+(?:named|called|name)\s+(?P<name>.+)$",
            r"^(?:named|called|name)\s+(?P<name>.+?)\s+(?:on|in|at|inside|under|from)\s+(?P<location>.+)$",
        ]
        for pattern in patterns:
            match = re.match(pattern, cleaned, flags=re.IGNORECASE)
            if not match:
                continue

            location = match.groupdict().get("location") or ""
            name = match.groupdict().get("name") or ""
            if location and name:
                return self._combine_location_and_name(location, name)

        return None

    def _resolve_user_alias_path(self, path_text: str) -> Path | None:
        cleaned = self._clean_location_phrase(path_text)
        if not cleaned:
            return None

        for alias, base_path in self.USER_PATH_ALIASES.items():
            suffix_pattern = (
                rf"^(?P<name>.+?)\s+(?:on|in|at|inside|under)\s+(?:the\s+)?{alias}(?:\s+folder)?$"
            )
            suffix_match = re.match(suffix_pattern, cleaned, flags=re.IGNORECASE)
            if suffix_match:
                file_name = self._strip_named_prefix(suffix_match.group("name") or "")
                if file_name:
                    return base_path / Path(file_name.replace("/", "\\"))

            pattern = (
                rf"^(?:(?:on|in|at|inside|under)\s+(?:the\s+)?)?{alias}"
                rf"(?:[\\/]|(?:\s+(?:folder\s+)?))?(.*)$"
            )
            match = re.match(pattern, cleaned, flags=re.IGNORECASE)
            if not match:
                continue

            remainder = self._strip_named_prefix(match.group(1) or "")
            if not remainder:
                return base_path

            remainder = remainder.lstrip("\\/ ").replace("/", "\\")
            return base_path / Path(remainder)

        return None

    def _resolve_path(self, path_text: str) -> Path:
        cleaned = self._sanitize_file_reference(path_text)
        extracted_path = self._extract_path_from_sentence(cleaned)
        if extracted_path is not None:
            return extracted_path

        alias_path = self._resolve_user_alias_path(cleaned)
        if alias_path is not None:
            return alias_path

        path_candidate = self._clean_location_phrase(cleaned)
        path = Path(path_candidate.replace("/", "\\"))
        if path.is_absolute() or self._looks_like_windows_absolute_path(path_candidate):
            return path

        return BASE_DIR / path

    def _resolve_file_target(self, path_text: str) -> Path:
        cleaned = self._sanitize_file_reference(path_text)
        lowered = cleaned.lower()

        if lowered in {"that file", "the file", "it"}:
            if self._last_file_target is None:
                raise ValueError("I don't know which file you mean yet. Tell me the file name once first.")
            return self._last_file_target

        return self._resolve_laptop_path(cleaned)

    def _resolve_folder_target(self, path_text: str) -> Path:
        cleaned = self._sanitize_file_reference(path_text)
        lowered = cleaned.lower()

        if lowered in {"that folder", "the folder", "that directory", "the directory", "it"}:
            if self._last_folder_target is None:
                raise ValueError("I don't know which folder you mean yet. Tell me the folder name once first.")
            return self._last_folder_target

        return self._resolve_laptop_path(cleaned)

    def _resolve_existing_target(self, path_text: str, target_kind: str = "") -> Path:
        cleaned = self._sanitize_file_reference(path_text)
        lowered = cleaned.lower()

        if target_kind == "file" and lowered in {"that file", "the file", "it"}:
            if self._last_file_target is None:
                raise ValueError("I don't know which file you mean yet. Tell me the file name once first.")
            return self._last_file_target

        if target_kind in {"folder", "directory"} and lowered in {"that folder", "the folder", "that directory", "the directory", "it"}:
            if self._last_folder_target is None:
                raise ValueError("I don't know which folder you mean yet. Tell me the folder name once first.")
            return self._last_folder_target

        if lowered in {"it", "that", "that item", "the item"}:
            if self._last_file_target is not None and self._last_file_target.exists():
                return self._last_file_target
            if self._last_folder_target is not None and self._last_folder_target.exists():
                return self._last_folder_target
            raise ValueError("I don't know which file or folder you mean yet. Tell me the name once first.")

        path = self._resolve_laptop_path(cleaned)
        if target_kind == "file" and path.exists() and path.is_dir():
            raise ValueError("That is a folder, not a file.")
        if target_kind in {"folder", "directory"} and path.exists() and not path.is_dir():
            raise ValueError("That is a file, not a folder.")
        return path

    def _resolve_laptop_path(self, path_text: str) -> Path:
        path = self._resolve_path(path_text).resolve()
        if self._is_protected_path(path):
            raise ValueError("That location is protected. Jarvis cannot access Windows or critical system folders.")
        return path

    def _create_file_in_folder(self, folder_text: str, name_text: str, content: str) -> Dict[str, str | bool]:
        try:
            folder = self._resolve_folder_target(folder_text)
        except ValueError as exc:
            return {"success": False, "action": "create_file", "message": str(exc)}

        file_name = self._clean_file_name(name_text)
        if not file_name:
            return {"success": False, "action": "create_file", "message": "Tell me the file name you want to use."}

        path = folder / Path(file_name.replace("/", "\\"))
        return self._create_file(str(path), content)

    def _create_file_or_ask_for_location(self, path_text: str, content: str) -> Dict[str, str | bool]:
        cleaned = self._sanitize_file_reference(path_text)
        if not cleaned:
            return {"success": False, "action": "create_file", "message": "Tell me the file name you want to use."}

        if not self._looks_like_explicit_path_request(cleaned):
            file_name = self._clean_file_name(cleaned)
            if not file_name:
                return {"success": False, "action": "create_file", "message": "Tell me the file name you want to use."}
            self._pending_create_file = {
                "name": file_name,
                "content": content or "",
            }
            return {
                "success": False,
                "action": "create_file_location_needed",
                "message": f"Where should I save {file_name}?",
            }

        return self._create_file(cleaned, content)

    def _handle_create_file_location_followup(self, command: str) -> Dict[str, str | bool]:
        pending = self._pending_create_file
        if not pending:
            return {
                "success": False,
                "action": "create_file",
                "message": "I don't have a pending file to save.",
            }

        reply = self._normalize_spoken_command(command)
        lowered = reply.lower().rstrip(".!?")
        if lowered in {"cancel", "stop", "never mind", "no", "skip"}:
            self._pending_create_file = None
            return {
                "success": False,
                "action": "create_file",
                "message": "File creation cancelled.",
            }

        try:
            folder = self._resolve_folder_target(reply)
        except ValueError as exc:
            return {"success": False, "action": "create_file", "message": str(exc)}

        self._pending_create_file = None
        file_name = str(pending.get("name", "")).strip()
        content = str(pending.get("content", ""))
        steps = [
            ActionStep("step1", "file", "file", "create_file", {"parent": str(folder), "filename": file_name}),
        ]
        if content:
            steps.append(
                ActionStep(
                    "step2",
                    "file",
                    "file",
                    "write_file",
                    {"path": "{step1.path}", "content": content, "overwrite": False},
                    depends_on=["step1"],
                )
            )
            steps.append(
                ActionStep(
                    "step3",
                    "file",
                    "file",
                    "verify_exists",
                    {"path": "{step1.path}", "expected_content": content},
                    depends_on=["step1", "step2"],
                )
            )
        target_path = folder / Path(file_name.replace("/", "\\"))
        plan_command = f"create file {target_path}"
        executor = ToolExecutor(registry=self._build_automation_tool_registry(), enforce_policy=True)
        return executor.execute(
            ActionPlan(
                original_text=plan_command,
                steps=steps,
                is_multistep=bool(content),
            ),
            ToolContext(
                command=plan_command,
                intent="file",
                session_id=self._active_session_id,
                request_id=self._active_turn_id,
                payload={"turn_id": self._active_turn_id} if self._active_turn_id else {},
                security_state={"step_up_verified": self._active_step_up_verified},
            ),
        )

    def _resolve_openable_path(self, target: str) -> Path | None:
        cleaned = self._sanitize_file_reference(target)
        lowered = cleaned.lower()

        if lowered in {"that folder", "the folder", "that directory", "the directory"}:
            return self._last_folder_target if self._last_folder_target and self._last_folder_target.exists() else None

        if lowered in {"that file", "the file"}:
            return self._last_file_target if self._last_file_target and self._last_file_target.exists() else None

        if lowered == "it":
            if self._last_folder_target and self._last_folder_target.exists():
                return self._last_folder_target
            if self._last_file_target and self._last_file_target.exists():
                return self._last_file_target
            return None

        if not self._looks_like_explicit_path_request(cleaned):
            return None

        try:
            path = self._resolve_laptop_path(cleaned)
        except ValueError:
            return None

        return path if path.exists() else None

    def _looks_like_explicit_path_request(self, target: str) -> bool:
        cleaned = (target or "").strip().lower()
        if not cleaned:
            return False

        if cleaned.startswith(("on ", "in ", "at ", "inside ", "under ")):
            return True

        if self._looks_like_windows_absolute_path(cleaned):
            return True

        if any(token in cleaned for token in ("\\", "/", ":")):
            return True

        if any(alias in cleaned for alias in self.USER_PATH_ALIASES):
            return True

        if any(keyword in cleaned for keyword in ("folder", "directory", "file")):
            return True

        return False

    def _resolve_web_target(self, target: str) -> str | None:
        cleaned = (target or "").strip()
        if not cleaned:
            return None

        lowered = cleaned.lower()
        if lowered in self.WEB_ALIASES:
            return self.WEB_ALIASES[lowered]

        if re.match(r"^https?://", cleaned, flags=re.IGNORECASE):
            return cleaned

        if re.match(r"^www\.", cleaned, flags=re.IGNORECASE):
            return f"https://{cleaned}"

        domain_match = re.match(r"^[a-z0-9-]+(?:\.[a-z0-9-]+)+(?:/.*)?$", lowered)
        if domain_match:
            return f"https://{cleaned}"

        return None

    def _display_file_name(self, path: Path) -> str:
        return path.name or str(path)

    def _display_target_name(self, path: Path) -> str:
        return path.name or str(path)

    def _display_parent_name(self, path: Path) -> str:
        parent = path.parent
        try:
            resolved_parent = parent.resolve()
            for alias, alias_path in self.USER_PATH_ALIASES.items():
                try:
                    if resolved_parent == alias_path.resolve():
                        return alias.capitalize()
                except Exception:
                    continue
            if resolved_parent == BASE_DIR.resolve():
                return BASE_DIR.name
        except Exception:
            pass
        return parent.name or str(parent)

    def _remember_target(self, path: Path) -> None:
        if path.exists() and path.is_dir():
            self._last_folder_target = path
        else:
            self._last_file_target = path

    def _create_file(self, path_text: str, content: str) -> Dict[str, str | bool]:
        try:
            path = self._resolve_file_target(path_text)
        except ValueError as exc:
            return {"success": False, "action": "create_file", "message": str(exc)}

        if path.exists() and path.is_dir():
            return {
                "success": False,
                "action": "create_file",
                "message": "That path is a folder, not a file.",
            }

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        except Exception as exc:
            return {
                "success": False,
                "action": "create_file",
                "message": f"Could not create {self._display_file_name(path)} at {path}: {exc}",
            }

        self._last_file_target = path
        return {
            "success": True,
            "action": "create_file",
            "message": f"Created {self._display_file_name(path)} in {self._display_parent_name(path)}.",
        }

    def _create_folder(self, path_text: str) -> Dict[str, str | bool]:
        try:
            path = self._resolve_folder_target(path_text)
        except ValueError as exc:
            return {"success": False, "action": "create_folder", "message": str(exc)}

        if path.exists() and not path.is_dir():
            return {
                "success": False,
                "action": "create_folder",
                "message": "That path is a file, not a folder.",
            }

        try:
            path.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            return {
                "success": False,
                "action": "create_folder",
                "message": f"Could not create folder {self._display_target_name(path)} at {path}: {exc}",
            }

        self._last_folder_target = path
        return {
            "success": True,
            "action": "create_folder",
            "message": f"Folder {self._display_target_name(path)} created at {path}.",
        }

    def create_file_with_content(self, path_text: str, content: str) -> Dict[str, str | bool]:
        return self._create_file(path_text, content)

    def _format_size(self, byte_count: int) -> str:
        size = float(max(byte_count, 0))
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if size < 1024 or unit == "TB":
                return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
            size /= 1024
        return f"{size:.1f} TB"

    def _list_files(self, folder_text: str = "downloads", limit: int = 30) -> Dict[str, str | bool]:
        try:
            folder = self._resolve_folder_target(folder_text or "downloads")
        except ValueError as exc:
            return {"success": False, "action": "list_files", "message": str(exc)}

        if not folder.exists():
            return {"success": False, "action": "list_files", "message": f"{self._display_target_name(folder)} does not exist."}
        if not folder.is_dir():
            return {"success": False, "action": "list_files", "message": "That is a file, not a folder."}

        try:
            items = sorted(folder.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except PermissionError:
            return {"success": False, "action": "list_files", "message": f"Permission denied: {folder}."}
        except Exception as exc:
            return {"success": False, "action": "list_files", "message": f"Could not list {folder}: {exc}"}

        visible_items = [item for item in items if not item.name.startswith(".")]
        lines = []
        for item in visible_items[:limit]:
            if item.is_dir():
                lines.append(f"[folder] {item.name}/")
            else:
                try:
                    size = self._format_size(item.stat().st_size)
                except Exception:
                    size = "unknown size"
                lines.append(f"[file] {item.name} ({size})")

        self._last_folder_target = folder
        if not lines:
            message = f"{self._display_target_name(folder)} is empty."
        else:
            suffix = f"\n... and {len(visible_items) - limit} more item(s)." if len(visible_items) > limit else ""
            message = f"Files in {self._display_target_name(folder)}:\n" + "\n".join(lines) + suffix
        return {"success": True, "action": "list_files", "message": message}

    def _read_file(self, path_text: str, max_chars: int = 4000) -> Dict[str, str | bool]:
        try:
            path = self._resolve_existing_target(path_text, target_kind="file")
        except ValueError as exc:
            return {"success": False, "action": "read_file", "message": str(exc)}

        if not path.exists():
            return {"success": False, "action": "read_file", "message": f"{self._display_file_name(path)} does not exist."}
        if not path.is_file():
            return {"success": False, "action": "read_file", "message": "That is a folder, not a file."}
        try:
            if path.stat().st_size > 2_000_000:
                return {"success": False, "action": "read_file", "message": "That file is too large to read safely in chat."}
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            return {"success": False, "action": "read_file", "message": f"Could not read {self._display_file_name(path)}: {exc}"}

        self._last_file_target = path
        if len(content) > max_chars:
            content = content[:max_chars].rstrip() + f"\n\n... truncated at {max_chars} characters."
        return {
            "success": True,
            "action": "read_file",
            "message": f"{self._display_file_name(path)}:\n{content}" if content else f"{self._display_file_name(path)} is empty.",
        }

    def _find_files(self, query_text: str, folder_text: str = "home", limit: int = 20) -> Dict[str, str | bool]:
        try:
            folder = self._resolve_folder_target(folder_text or "home")
        except ValueError as exc:
            return {"success": False, "action": "find_files", "message": str(exc)}

        if not folder.exists():
            return {"success": False, "action": "find_files", "message": f"{self._display_target_name(folder)} does not exist."}
        if not folder.is_dir():
            return {"success": False, "action": "find_files", "message": "That is a file, not a folder."}

        query = self._sanitize_file_reference(query_text).lower()
        extension = ""
        extension_aliases = {
            "pdf": ".pdf",
            "pdfs": ".pdf",
            "document": ".docx",
            "documents": ".docx",
            "word": ".docx",
            "text": ".txt",
            "notes": ".txt",
            "image": ".jpg",
            "images": ".jpg",
            "photo": ".jpg",
            "photos": ".jpg",
            "video": ".mp4",
            "videos": ".mp4",
        }
        for token, ext in extension_aliases.items():
            if re.search(rf"\b{re.escape(token)}\b", query):
                extension = ext
                break
        ext_match = re.search(r"\.([a-z0-9]{1,8})\b", query)
        if ext_match:
            extension = "." + ext_match.group(1)

        name_query = re.sub(
            r"\b(find|files?|all|the|named|called|documents?|pdfs?|images?|photos?|videos?|music|text|notes)\b",
            " ",
            query,
        )
        name_query = re.sub(r"\.[a-z0-9]{1,8}\b", " ", name_query)
        name_query = re.sub(r"\s+", " ", name_query).strip()

        pattern = f"*{extension}" if extension else "*"
        results = []
        scanned = 0
        try:
            for item in folder.rglob(pattern):
                scanned += 1
                if scanned > 8000:
                    break
                if not item.is_file():
                    continue
                if name_query and name_query not in item.name.lower():
                    continue
                try:
                    size = self._format_size(item.stat().st_size)
                except Exception:
                    size = "unknown size"
                results.append(f"{item.name} ({size}) - {item.parent}")
                if len(results) >= limit:
                    break
        except PermissionError:
            return {"success": False, "action": "find_files", "message": f"Permission denied while searching {folder}."}
        except Exception as exc:
            return {"success": False, "action": "find_files", "message": f"Could not search {folder}: {exc}"}

        self._last_folder_target = folder
        if not results:
            return {"success": True, "action": "find_files", "message": f"No matching files found in {self._display_target_name(folder)}."}
        return {"success": True, "action": "find_files", "message": "Found files:\n" + "\n".join(results)}

    def _largest_files(self, folder_text: str = "home", limit: int = 10) -> Dict[str, str | bool]:
        try:
            folder = self._resolve_folder_target(folder_text or "home")
        except ValueError as exc:
            return {"success": False, "action": "largest_files", "message": str(exc)}

        if not folder.exists():
            return {"success": False, "action": "largest_files", "message": f"{self._display_target_name(folder)} does not exist."}
        if not folder.is_dir():
            return {"success": False, "action": "largest_files", "message": "That is a file, not a folder."}

        candidates: list[tuple[int, Path]] = []
        scanned = 0
        try:
            for item in folder.rglob("*"):
                scanned += 1
                if scanned > 8000:
                    break
                if item.is_file():
                    try:
                        candidates.append((item.stat().st_size, item))
                    except Exception:
                        continue
        except PermissionError:
            return {"success": False, "action": "largest_files", "message": f"Permission denied while scanning {folder}."}
        except Exception as exc:
            return {"success": False, "action": "largest_files", "message": f"Could not scan {folder}: {exc}"}

        candidates.sort(reverse=True, key=lambda pair: pair[0])
        lines = [f"{path.name} ({self._format_size(size)}) - {path.parent}" for size, path in candidates[:limit]]
        if not lines:
            return {"success": True, "action": "largest_files", "message": f"No files found in {self._display_target_name(folder)}."}
        return {"success": True, "action": "largest_files", "message": "Largest files:\n" + "\n".join(lines)}

    def _organize_folder_preview(self, folder_text: str = "downloads") -> Dict[str, str | bool]:
        try:
            folder = self._resolve_folder_target(folder_text or "downloads")
        except ValueError as exc:
            return {"success": False, "action": "organize_folder_preview", "message": str(exc)}

        if not folder.exists():
            return {"success": False, "action": "organize_folder_preview", "message": f"{self._display_target_name(folder)} does not exist."}
        if not folder.is_dir():
            return {"success": False, "action": "organize_folder_preview", "message": "That is a file, not a folder."}

        categories = {
            "Images": {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg"},
            "Documents": {".pdf", ".doc", ".docx", ".txt", ".md", ".rtf", ".csv", ".xlsx", ".pptx"},
            "Archives": {".zip", ".rar", ".7z", ".tar", ".gz"},
            "Installers": {".exe", ".msi", ".apk", ".dmg", ".pkg"},
            "Videos": {".mp4", ".mov", ".avi", ".mkv", ".webm"},
            "Audio": {".mp3", ".wav", ".flac", ".m4a", ".ogg"},
        }
        counts = {name: 0 for name in categories}
        counts["Other"] = 0

        try:
            for item in folder.iterdir():
                if not item.is_file():
                    continue
                suffix = item.suffix.lower()
                matched = False
                for category, suffixes in categories.items():
                    if suffix in suffixes:
                        counts[category] += 1
                        matched = True
                        break
                if not matched:
                    counts["Other"] += 1
        except Exception as exc:
            return {"success": False, "action": "organize_folder_preview", "message": f"Could not inspect {folder}: {exc}"}

        lines = [f"{name}: {count}" for name, count in counts.items() if count]
        if not lines:
            message = f"{self._display_target_name(folder)} has no files to organize."
        else:
            message = (
                f"Organization preview for {self._display_target_name(folder)}:\n"
                + "\n".join(lines)
                + "\nNo files were moved."
            )
        self._last_folder_target = folder
        return {"success": True, "action": "organize_folder_preview", "message": message}

    def _update_file(self, path_text: str, content: str, append: bool = True) -> Dict[str, str | bool]:
        if not content:
            return {
                "success": False,
                "action": "update_file",
                "message": "Tell me what text you want me to add.",
            }

        try:
            path = self._resolve_file_target(path_text)
        except ValueError as exc:
            return {"success": False, "action": "update_file", "message": str(exc)}

        if path.exists() and path.is_dir():
            return {
                "success": False,
                "action": "update_file",
                "message": "That is a folder, not a file.",
            }

        path.parent.mkdir(parents=True, exist_ok=True)

        existing = ""
        if path.exists():
            try:
                existing = path.read_text(encoding="utf-8")
            except Exception:
                existing = ""

        if append and existing:
            separator = "" if existing.endswith(("\n", "\r")) else "\n"
            new_content = existing + separator + content
        elif append and not existing:
            new_content = content
        else:
            new_content = content

        try:
            path.write_text(new_content, encoding="utf-8")
        except Exception as exc:
            return {
                "success": False,
                "action": "update_file",
                "message": f"Could not update {self._display_file_name(path)} at {path}: {exc}",
            }

        self._last_file_target = path

        return {
            "success": True,
            "action": "update_file",
            "message": f"Updated {self._display_file_name(path)} in {self._display_parent_name(path)}.",
        }

    def _show_last_file_path(self) -> Dict[str, str | bool]:
        if self._last_file_target is None:
            return {
                "success": False,
                "action": "show_path",
                "message": "I don't know which file you mean yet.",
            }
        return {
            "success": True,
            "action": "show_path",
            "message": f"{self._display_file_name(self._last_file_target)} is at {self._last_file_target}.",
        }

    def _delete_file(self, path_text: str) -> Dict[str, str | bool]:
        try:
            path = self._resolve_existing_target(path_text, target_kind="file")
        except ValueError as exc:
            return {"success": False, "action": "delete_file", "message": str(exc)}

        if not path.exists():
            return {
                "success": False,
                "action": "delete_file",
                "message": f"{self._display_file_name(path)} does not exist.",
            }

        if path.is_dir():
            return {
                "success": False,
                "action": "delete_file",
                "message": "That is a folder, not a file.",
            }

        self._pending_delete_target = path
        return {
            "success": False,
            "action": "delete_file",
            "message": f"Do you want me to delete {self._display_file_name(path)}? Reply yes or no.",
        }

    def _delete_folder(self, path_text: str) -> Dict[str, str | bool]:
        try:
            path = self._resolve_existing_target(path_text, target_kind="folder")
        except ValueError as exc:
            return {"success": False, "action": "delete_folder", "message": str(exc)}

        if not path.exists():
            return {
                "success": False,
                "action": "delete_folder",
                "message": f"{self._display_target_name(path)} does not exist.",
            }

        if not path.is_dir():
            return {
                "success": False,
                "action": "delete_folder",
                "message": "That is a file, not a folder.",
            }

        self._pending_delete_target = path
        self._last_folder_target = path
        return {
            "success": False,
            "action": "delete_folder",
            "message": f"Do you want me to delete folder {self._display_target_name(path)}? Reply yes or no.",
        }

    def _rename_target(self, source_text: str, new_name: str, target_kind: str = "") -> Dict[str, str | bool]:
        try:
            source = self._resolve_existing_target(source_text, target_kind=target_kind)
        except ValueError as exc:
            return {"success": False, "action": "rename", "message": str(exc)}

        if not source.exists():
            return {
                "success": False,
                "action": "rename",
                "message": f"{self._display_target_name(source)} does not exist.",
            }

        clean_name = self._clean_file_name(new_name)
        if not clean_name:
            return {
                "success": False,
                "action": "rename",
                "message": "Tell me the new name you want to use.",
            }

        if "\\" in clean_name or "/" in clean_name:
            return {
                "success": False,
                "action": "rename",
                "message": "For renaming, give me just the new name, not a full path.",
            }

        destination = source.with_name(clean_name)
        if self._is_protected_path(destination):
            return {
                "success": False,
                "action": "rename",
                "message": "That location is protected. Jarvis cannot rename items inside Windows or critical system folders.",
            }

        if destination.exists():
            return {
                "success": False,
                "action": "rename",
                "message": f"{self._display_target_name(destination)} already exists at {destination}.",
            }

        try:
            source.rename(destination)
        except Exception as exc:
            return {
                "success": False,
                "action": "rename",
                "message": f"Could not rename {self._display_target_name(source)}: {exc}",
            }

        self._remember_target(destination)
        return {
            "success": True,
            "action": "rename",
            "message": f"Renamed {self._display_target_name(source)} to {self._display_target_name(destination)}.",
        }

    def _move_target(self, source_text: str, destination_text: str, target_kind: str = "") -> Dict[str, str | bool]:
        try:
            source = self._resolve_existing_target(source_text, target_kind=target_kind)
        except ValueError as exc:
            return {"success": False, "action": "move", "message": str(exc)}

        if not source.exists():
            return {
                "success": False,
                "action": "move",
                "message": f"{self._display_target_name(source)} does not exist.",
            }

        try:
            destination = self._resolve_move_destination(source, destination_text)
        except ValueError as exc:
            return {"success": False, "action": "move", "message": str(exc)}

        if destination.exists():
            return {
                "success": False,
                "action": "move",
                "message": f"{self._display_target_name(destination)} already exists at {destination}.",
            }

        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
        except Exception as exc:
            return {
                "success": False,
                "action": "move",
                "message": f"Could not move {self._display_target_name(source)}: {exc}",
            }

        moved_path = Path(destination)
        self._remember_target(moved_path)
        return {
            "success": True,
            "action": "move",
            "message": f"Moved {self._display_target_name(moved_path)} to {moved_path}.",
        }

    def _resolve_move_destination(self, source: Path, destination_text: str) -> Path:
        cleaned = self._sanitize_file_reference(destination_text)
        if not cleaned:
            raise ValueError("Tell me where you want me to move it.")

        folder_target = self._resolve_folder_phrase(cleaned)
        if folder_target is not None:
            if self._is_protected_path(folder_target):
                raise ValueError("That location is protected. Jarvis cannot access Windows or critical system folders.")
            return folder_target / source.name

        destination = self._resolve_laptop_path(cleaned)
        if destination.exists() and destination.is_dir():
            return destination / source.name

        if cleaned.endswith(("\\", "/")):
            return destination / source.name

        return destination

    def _resolve_folder_phrase(self, path_text: str) -> Path | None:
        raw_cleaned = self._sanitize_file_reference(path_text)
        explicit_folder_match = re.match(
            r"^(?:on|in|at|inside|under)\s+(?:the\s+)?(?:folder|directory)\s+(.+)$|^(?:the\s+)?(?:folder|directory)\s+(.+)$",
            raw_cleaned,
            flags=re.IGNORECASE,
        )
        if explicit_folder_match:
            explicit_value = (explicit_folder_match.group(1) or explicit_folder_match.group(2) or "").strip()
            if explicit_value:
                return self._resolve_path(explicit_value).resolve()

        cleaned = self._clean_location_phrase(path_text)
        if not cleaned:
            return None

        alias_path = self._resolve_user_alias_path(cleaned)
        if alias_path is not None:
            lowered = cleaned.lower()
            if lowered in self.USER_PATH_ALIASES or lowered.startswith("the "):
                return alias_path

        lowered = cleaned.lower()
        if lowered in self.USER_PATH_ALIASES:
            return self.USER_PATH_ALIASES[lowered]

        if self._looks_like_windows_absolute_path(cleaned) and cleaned.endswith(("\\", "/")):
            return Path(cleaned.replace("/", "\\"))

        return None

    def _handle_delete_confirmation(self, command: str) -> Dict[str, str | bool]:
        target = self._pending_delete_target
        response = command.strip().lower().rstrip(".!?")

        if response in {"yes", "y", "delete it", "confirm", "go ahead"}:
            self._pending_delete_target = None
            if not target or not target.exists():
                return {
                    "success": False,
                    "action": "delete",
                    "message": "That item is no longer available to delete.",
                }
            action = "delete_folder" if target.is_dir() else "delete_file"
            plan_command = f"delete {'folder' if target.is_dir() else 'file'} {target}"
            executor = ToolExecutor(registry=self._build_automation_tool_registry(), enforce_policy=True)
            return executor.execute(
                ActionPlan(
                    original_text=plan_command,
                    steps=[
                        ActionStep(
                            step_id="step1",
                            tool_name="file",
                            intent="file",
                            action=action,
                            args={"path": str(target), "confirmed": True},
                        )
                    ],
                    is_multistep=False,
                ),
                ToolContext(
                    command=plan_command,
                    intent="file",
                    session_id=self._active_session_id,
                    request_id=self._active_turn_id,
                    payload={"turn_id": self._active_turn_id} if self._active_turn_id else {},
                    confirmation_state={"confirmed": True},
                    security_state={"step_up_verified": self._active_step_up_verified},
                ),
            )

        if response in {"no", "n", "cancel", "stop", "don't", "do not"}:
            self._pending_delete_target = None
            return {
                "success": False,
                "action": "delete",
                "message": "Deletion cancelled.",
            }

        return {
            "success": False,
            "action": "delete",
            "message": f"Please reply yes or no to confirm deleting {self._display_target_name(target)}.",
        }

    def _is_protected_path(self, path: Path) -> bool:
        try:
            resolved = path.resolve()
        except Exception:
            resolved = path

        resolved_text = str(resolved).lower()
        drive_root_match = re.match(r"^[a-z]:\\?$", resolved_text)
        if drive_root_match:
            return True

        workspace_text = str(BASE_DIR.resolve()).lower()
        if resolved_text.startswith(workspace_text):
            return False

        for prefix in self.PROTECTED_PATH_PREFIXES:
            prefix_text = str(prefix.resolve()).lower()
            if resolved_text == prefix_text or resolved_text.startswith(prefix_text + "\\"):
                return True

        for pattern in self.PROTECTED_PATH_PATTERNS:
            if pattern.match(resolved_text):
                return True

        return False

    def _is_protected_app(self, target: str) -> bool:
        normalized = re.sub(r"\s+", " ", target.strip().lower())
        return normalized in self.PROTECTED_APP_KEYWORDS

    def _is_protected_close_target(self, target: str) -> bool:
        normalized = re.sub(r"\s+", " ", target.strip().lower())
        return normalized in {"file explorer", "explorer"} or self._is_protected_app(normalized)

    def _appopener_candidates(self, target: str) -> list[str]:
        lowered = target.lower()
        candidates = [lowered]

        alias = self.APP_ALIASES.get(lowered)
        if alias and alias not in candidates:
            candidates.append(alias)

        compact = re.sub(r"\s+", " ", lowered).strip()
        if compact and compact not in candidates:
            candidates.append(compact)

        return candidates

    def _direct_open_fallback(self, target: str) -> Dict[str, str | bool] | None:
        normalized = re.sub(r"\s+", " ", (target or "").strip().lower())
        browser_executable = self._resolve_browser_executable(normalized)
        if browser_executable:
            try:
                subprocess.Popen([browser_executable])
                logger.info("[AUTOMATION] Opened browser executable directly: %s", browser_executable)
                return {
                    "success": True,
                    "action": "open",
                    "message": f"Opening {target}.",
                }
            except Exception as exc:
                return {
                    "success": False,
                    "action": "open",
                    "message": f"I could not open {target}: {exc}",
                }

        uri = self.DIRECT_OPEN_URIS.get(normalized)
        if uri:
            try:
                os.startfile(uri)
                logger.info("[AUTOMATION] Opened direct URI target: %s", uri)
                return {
                    "success": True,
                    "action": "open",
                    "message": f"Opening {target}.",
                }
            except Exception as exc:
                return {
                    "success": False,
                    "action": "open",
                    "message": f"I could not open {target}: {exc}",
                }

        command = self.DIRECT_OPEN_COMMANDS.get(normalized)
        if not command:
            return None

        try:
            subprocess.Popen(command)
            logger.info("[AUTOMATION] Opened direct command target: %s", command)
            return {
                "success": True,
                "action": "open",
                "message": f"Opening {target}.",
            }
        except Exception as exc:
            return {
                "success": False,
                "action": "open",
                "message": f"I could not open {target}: {exc}",
            }

    def _direct_close_fallback(self, target: str) -> Dict[str, str | bool] | None:
        normalized = re.sub(r"\s+", " ", (target or "").strip().lower())
        executable = self.DIRECT_CLOSE_EXECUTABLES.get(normalized)
        if not executable:
            return None

        try:
            result = subprocess.run(
                ["taskkill", "/IM", executable, "/F"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                details = (result.stderr or result.stdout or "").strip() or "process not found"
                return {
                    "success": False,
                    "action": "close",
                    "message": f"I could not find an open app matching {target}: {details}",
                }

            logger.info("[AUTOMATION] Closed direct executable target: %s", executable)
            return {
                "success": True,
                "action": "close",
                "message": f"Closing {target}.",
            }
        except Exception as exc:
            return {
                "success": False,
                "action": "close",
                "message": f"I could not close {target}: {exc}",
            }

    def _appopener_unavailable(self, action: str) -> Dict[str, str | bool]:
        message = "AppOpener is not available on this machine."
        if APP_OPENER_IMPORT_ERROR is not None:
            message = f"{message} Import error: {APP_OPENER_IMPORT_ERROR}"

        return {
            "success": False,
            "action": action,
            "message": message,
        }

    def diagnostics(self) -> Dict[str, str | bool]:
        return {
            "appopener_available": self._appopener_available,
            "appopener_error": "" if APP_OPENER_IMPORT_ERROR is None else str(APP_OPENER_IMPORT_ERROR),
            "send2trash_available": send2trash is not None,
            "send2trash_error": "" if SEND2TRASH_IMPORT_ERROR is None else str(SEND2TRASH_IMPORT_ERROR),
        }
