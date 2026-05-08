from __future__ import annotations

import logging
import os
import re
import time
import urllib.parse
from pathlib import Path
from typing import Callable, Dict, Iterable

from config import BASE_DIR as CONFIG_BASE_DIR
from app.orchestrator.action_plan import ActionPlan, ActionStep
from app.orchestrator.tool_executor import ToolExecutor
from app.tools.automation_domain_helper import ServiceBackedDomainHelper
from app.services.contact_match_service import ContactCandidate, ContactMatchService
from app.services.message_action_service import MessageActionService
from app.tools.base import ToolContext

try:
    from send2trash import send2trash
    SEND2TRASH_IMPORT_ERROR = None
except Exception as exc:
    send2trash = None
    SEND2TRASH_IMPORT_ERROR = exc


logger = logging.getLogger("J.A.R.V.I.S")


def _runtime_base_dir() -> Path:
    try:
        from app.services import automation_service as automation_module

        return automation_module.BASE_DIR
    except Exception:
        return CONFIG_BASE_DIR



class AutomationAppBrowserCompatibility(ServiceBackedDomainHelper):

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
                    self.local_app_connector.open_web_target(web_target)
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
                    self.local_app_connector.open_path(file_system_target)
                    self._remember_target(file_system_target)
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
                    self.local_app_connector.open_app_candidate(candidate)
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
                    self.local_app_connector.close_app_candidate(candidate)
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

            query = self._normalize_browser_search_query(target)
            if not query:
                return {"success": False, "action": "google_search", "message": "Tell me what you want me to search on Google."}
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


    @staticmethod
    def _normalize_browser_search_query(target: str) -> str:
            query = re.sub(r"\s+", " ", str(target or "").strip()).strip(" .!?")
            previous = None
            while query and query.lower() != previous:
                previous = query.lower()
                query = re.sub(
                    r"^(?:search\s+google\s+for|google\s+for|search\s+(?:the\s+)?(?:web|internet|online)\s+for|search\s+about)\s+",
                    "",
                    query,
                    flags=re.IGNORECASE,
                ).strip(" .!?")
            return query


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
            try:
                if delay_before > 0:
                    time.sleep(delay_before)
                self._prepare_typing_surface(focus_target)
                result = self.computer_control_service.type_text(payload, clear_first=False, press_enter=press_enter)
                if not bool(result.get("success")):
                    return {"success": False, "action": "type", "message": str(result.get("message") or "Typing is unavailable.")}
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
            normalized_target = self._normalize_target(target).lower()
            if normalized_target in {"chrome", "google chrome", "edge", "microsoft edge"}:
                time.sleep(0.15)
                self.computer_control_service.hotkey(["ctrl", "l"])
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
                    self.local_app_connector.open_path(file_system_target)
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
                    self.local_app_connector.open_app_candidate(candidate)
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
            normalized_browser = self._normalize_target(browser).lower() if browser else None
            self.local_app_connector.open_url(url, browser=normalized_browser)


    def _resolve_browser_process_name(self, browser: str) -> str | None:
            mapping = {
                "chrome": "chrome.exe",
                "google chrome": "chrome.exe",
                "edge": "msedge.exe",
                "microsoft edge": "msedge.exe",
            }
            return mapping.get(browser)


    def _is_process_running(self, executable_name: str) -> bool:
            return self.local_app_connector.is_process_running(executable_name)


    def _resolve_browser_executable(self, browser: str) -> str | None:
            return self.local_app_connector.resolve_browser_executable(browser)


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
            return self.local_app_connector.direct_open_fallback(
                target,
                direct_open_uris=self.DIRECT_OPEN_URIS,
                direct_open_commands=self.DIRECT_OPEN_COMMANDS,
            )


    def _direct_close_fallback(self, target: str) -> Dict[str, str | bool] | None:
            return self.local_app_connector.direct_close_fallback(target, direct_close_executables=self.DIRECT_CLOSE_EXECUTABLES)


    def _appopener_unavailable(self, action: str) -> Dict[str, str | bool]:
            return self.local_app_connector.appopener_unavailable(action)


