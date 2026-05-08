from __future__ import annotations

import re
import time
from typing import Dict

from app.connectors.browser_connector import BrowserConnector
from app.orchestrator.action_plan import ActionPlan, ActionStep
from app.orchestrator.automation_context import AutomationContext
from app.orchestrator.main_orchestrator import MainOrchestrator
from app.orchestrator.tool_executor import ToolExecutor
from app.orchestrator.tool_registry import ToolRegistry
from app.tools.app_interaction_tool import AppInteractionTool
from app.tools.app_launcher_tool import AppLauncherTool
from app.tools.app_tool import AppTool
from app.tools.base import ToolContext
from app.tools.browser_tool import BrowserTool
from app.tools.file_tool import FileTool
from app.tools.gmail_tool import GmailTool
from app.tools.summary_tool import SummaryTool
from app.tools.system_tool import SystemTool
from app.tools.whatsapp_tool import WhatsAppTool


class AutomationFacadeRouter:
    def __init__(self, service) -> None:
        object.__setattr__(self, "_service", service)

    def __getattr__(self, name):
        return getattr(self._service, name)

    def __setattr__(self, name, value):
        if name == "_service":
            object.__setattr__(self, name, value)
        else:
            setattr(self._service, name, value)

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
            lowered = self.app_browser_domain._normalize_spoken_command(text).lower().rstrip(".!?")
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
            cleaned = self.app_browser_domain._normalize_spoken_command(text).rstrip(" .!?")
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
            reply = self.app_browser_domain._normalize_spoken_command(text).strip()
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
                return self._execute_facade(reply)
            template = str(pending.get("template") or "")
            if not template or not reply:
                return None
            self._pending_incomplete_command = None
            if pending.get("kind") == "browser_search":
                browser = "chrome" if "chrome" in template.lower() else "edge" if "edge" in template.lower() else None
                return self.app_browser_domain._google_search(reply, browser=browser)
            return self._execute_facade(template.replace("{answer}", reply))

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

    def _handle_subject_context_command(self, command: str) -> Dict[str, object] | None:
            match = re.match(
                r"^(?:change\s+(?:the\s+)?subject\s+to|change\s+(?:the\s+)?topic\s+to|make\s+it\s+about|switch\s+topic\s+to|now\s+about|talk\s+about)\s+(.+?)[.!?]*$",
                command,
                flags=re.IGNORECASE,
            )
            if not match:
                return None
            subject = match.group(1).strip()
            if not subject:
                return {"success": False, "action": "clarification_required", "message": "What subject should I use?"}
            if self._active_automation_context is not None:
                self._active_automation_context.current_subject = subject
                self._active_automation_context.last_explicit_entity = subject
                self._active_automation_context.touch()
            return {"success": True, "action": "subject_updated", "message": f"Okay, I'll keep the subject as {subject}."}

    @staticmethod
    def _looks_like_subject_context_command(lowered: str) -> bool:
            return bool(
                re.match(
                    r"^(?:change\s+(?:the\s+)?subject\s+to|change\s+(?:the\s+)?topic\s+to|make\s+it\s+about|switch\s+topic\s+to|now\s+about|talk\s+about)\s+.+",
                    str(lowered or "").strip(),
                    flags=re.IGNORECASE,
                )
            )

    @staticmethod
    def _looks_like_contextual_browser_followup(lowered: str) -> bool:
            return bool(
                re.match(
                    r"^(?:search\s+about\s+(?:him|her|it|this|that)(?:\s+again)?(?:\s+on\s+google)?|google\s+(?:him|her|it|this|that)|look\s+(?:him|her|it|this|that)\s+up)[.!?]*$",
                    str(lowered or "").strip(),
                    flags=re.IGNORECASE,
                )
            )

    def _rewrite_contextual_followup(self, command: str) -> str | Dict[str, object] | None:
            lowered = command.strip().lower()
            pronoun_match = re.match(
                r"^(?:search\s+about\s+(?P<pronoun>him|her|it|this|that)(?:\s+again)?(?:\s+on\s+google)?|google\s+(?P<google_pronoun>him|her|it|this|that)|look\s+(?P<lookup_pronoun>him|her|it|this|that)\s+up)[.!?]*$",
                lowered,
                flags=re.IGNORECASE,
            )
            if pronoun_match:
                pronoun = pronoun_match.group("pronoun") or pronoun_match.group("google_pronoun") or pronoun_match.group("lookup_pronoun") or ""
                context = self._active_automation_context
                target = None
                if context is not None:
                    target = context.current_subject or context.last_explicit_entity
                    if not target and pronoun in {"it", "this", "that"}:
                        target = context.last_browser_query
                if not target:
                    message = "Who should I search for?" if pronoun in {"him", "her"} else "What should I search for?"
                    return {"success": False, "action": "clarification_required", "status": "clarification_required", "message": message, "requires_followup": True}
                return f"search google for {target}"

            file_followup = re.match(
                r"^(?P<verb>put|append|write|add)\s+(?P<content>.+?)\s+(?:in|to)\s+it[.!?]*$",
                command,
                flags=re.IGNORECASE,
            )
            if file_followup:
                context = self._active_automation_context
                target = (
                    context.last_created_file_path or context.last_file_target or context.last_file_path
                    if context is not None
                    else None
                )
                if not target:
                    return {"success": False, "action": "clarification_required", "message": "Which file should I update?"}
                return f"append {file_followup.group('content').strip()} to it"
            return None

    def _handle_file_selection_followup(self, command: str) -> Dict[str, object] | None:
            text = command.strip()
            reference_pattern = r"(?P<ref>it|that|this|that file|the file|the first one|first one|first|1|the second one|second one|second|2|the third one|third one|third|3|the fourth one|fourth one|fourth|4|the fifth one|fifth one|fifth|5|the last one|last one|last)"

            path_match = re.match(
                rf"^(?:show\s+(?:me\s+)?(?:the\s+)?path\s+(?:of|for)\s+|show\s+(?:me\s+)?(?:the\s+)?full\s+path\s+(?:of|for)\s+|where\s+is\s+){reference_pattern}[.!?]*$",
                text,
                flags=re.IGNORECASE,
            )
            if path_match:
                return self.file_domain._show_selected_file_path(path_match.group("ref"))

            read_match = re.match(rf"^(?:read|show|display)\s+{reference_pattern}[.!?]*$", text, flags=re.IGNORECASE)
            if read_match:
                path = self.file_domain._resolve_recent_file_selection(read_match.group("ref"))
                if path is None:
                    return {"success": False, "action": "read_file", "status": "clarification_required", "requires_followup": True, "message": "Which file should I read?"}
                return self.file_domain._read_file(str(path))

            summarize_match = re.match(rf"^(?:summarize|explain)\s+{reference_pattern}[.!?]*$", text, flags=re.IGNORECASE)
            if summarize_match:
                path = self.file_domain._resolve_recent_file_selection(summarize_match.group("ref"))
                if path is None:
                    return {"success": False, "action": "summarize_file", "status": "clarification_required", "requires_followup": True, "message": "Which file should I summarize?"}
                return self._execute_selected_file_summary(str(path), command)

            open_match = re.match(rf"^open\s+{reference_pattern}[.!?]*$", text, flags=re.IGNORECASE)
            if open_match:
                path = self.file_domain._resolve_recent_file_selection(open_match.group("ref"))
                if path is None:
                    return {"success": False, "action": "open_file", "status": "clarification_required", "requires_followup": True, "message": "Which file should I open?"}
                self.file_domain._remember_target(path)
                return {
                    "success": True,
                    "action": "select_file",
                    "message": f"Selected {path.name}.",
                    "path": str(path),
                    "data": {"path": str(path)},
                }
            return None

    def _execute_selected_file_summary(self, path: str, command: str) -> Dict[str, object]:
            executor = ToolExecutor(registry=self._build_automation_tool_registry(), enforce_policy=True)
            return executor.execute(
                ActionPlan(
                    original_text=command,
                    steps=[
                        ActionStep("step1", "file", "file", "read_file", {"path": path}),
                        ActionStep("step2", "summary", "summary", "summarize", {"content": "{step1.content}"}, depends_on=["step1"]),
                    ],
                    is_multistep=True,
                ),
                ToolContext(
                    command=command,
                    intent="summary",
                    session_id=self._active_session_id,
                    request_id=self._active_turn_id,
                    payload={"turn_id": self._active_turn_id} if self._active_turn_id else {},
                    source=self._active_request_source,
                    security_state={"step_up_verified": self._active_step_up_verified},
                ),
            )

    def _execute_facade(self, command: str) -> Dict[str, str | bool]:
            text = (command or "").strip()
            if not text:
                return {
                    "success": False,
                    "action": "unsupported",
                    "message": "Tell me which app you want to open or close.",
                }

            normalized_text = self.app_browser_domain._normalize_spoken_command(text)
            lowered = normalized_text.lower()

            subject_result = self._handle_subject_context_command(normalized_text)
            if subject_result is not None:
                return subject_result

            followup_result = self._rewrite_contextual_followup(normalized_text)
            if isinstance(followup_result, dict):
                return followup_result
            if isinstance(followup_result, str) and followup_result:
                normalized_text = followup_result
                lowered = normalized_text.lower()

            dry_run_followup = self._handle_pending_dry_run_response(normalized_text)
            if dry_run_followup is not None:
                return dry_run_followup

            if self._pending_mark_action is not None:
                return self.whatsapp_domain._handle_mark_confirmation(text)

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
                return self.file_domain._handle_delete_confirmation(text)

            if self._pending_open_target is not None:
                return self.app_browser_domain._handle_open_clarification(text)

            if self._pending_browser_search is not None:
                return self.app_browser_domain._handle_browser_search_followup(text)

            if self._pending_create_file is not None:
                return self.file_domain._handle_create_file_location_followup(text)

            if self._has_pending_incomplete_command():
                completed = self._handle_incomplete_command_followup(normalized_text)
                if completed is not None:
                    return completed

            if self._pending_whatsapp_clarification is not None:
                return self.whatsapp_domain._handle_whatsapp_clarification_followup(normalized_text)

            file_selection = self._handle_file_selection_followup(normalized_text)
            if file_selection is not None:
                return file_selection

            path_request_match = re.match(
                r"^(?:where\s+is\s+(?:it|that|that\s+file|the\s+file)|show\s+(?:me\s+)?(?:the\s+)?full\s+path|copy\s+(?:the\s+)?path)[.!?]*$",
                normalized_text,
                flags=re.IGNORECASE,
            )
            if path_request_match:
                return self.file_domain._show_last_file_path()

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

            canonical_result = self._execute_canonical_command(normalized_text)
            if canonical_result is not None:
                return canonical_result

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
                return self.file_domain._list_files((list_match.group(1) or "downloads").strip())

            search_files_match = re.match(
                r"^(?:search\s+(?:my\s+)?files?|search\s+local\s+files?|search\s+in\s+files?|look\s+in\s+my\s+files?)(?:\s+for\s+(.+?))?[.!?]*$",
                normalized_text,
                flags=re.IGNORECASE,
            )
            if search_files_match:
                query = (search_files_match.group(1) or "").strip()
                if not query:
                    return {"success": False, "action": "search_files", "status": "clarification_required", "message": "What file name or content should I search for?", "requires_followup": True, "missing_query": True}
                return self.file_domain._find_files(query, "home")

            read_match = re.match(
                r"^(?:read|show|display)(?:\s+me)?\s+(?:the\s+)?(?:file|text\s+file)\s+(.+?)[.!?]*$",
                normalized_text,
                flags=re.IGNORECASE,
            )
            if read_match:
                return self.file_domain._read_file(read_match.group(1).strip())

            find_match = re.match(
                r"^find\s+(?P<query>.+?)(?:\s+(?:in|inside|under|on)\s+(?P<location>.+?))?[.!?]*$",
                normalized_text,
                flags=re.IGNORECASE,
            )
            if find_match:
                query = find_match.group("query").strip()
                location = (find_match.group("location") or "home").strip()
                if re.search(r"\b(files?|pdfs?|documents?|images?|photos?|videos?|music)\b", query, flags=re.IGNORECASE):
                    return self.file_domain._find_files(query, location)

            largest_match = re.match(
                r"^(?:show\s+)?(?:the\s+)?(?:largest|biggest)\s+files(?:\s+(?:in|on|inside|under)\s+(.+?))?[.!?]*$",
                normalized_text,
                flags=re.IGNORECASE,
            )
            if largest_match:
                return self.file_domain._largest_files((largest_match.group(1) or "home").strip())

            organize_match = re.match(
                r"^(?:(?:preview\s+)?organize|organize\s+preview)(?:\s+(?:the\s+)?(?:folder|directory))?(?:\s+(?:in|on|inside|under)\s+(.+?))?[.!?]*$",
                normalized_text,
                flags=re.IGNORECASE,
            )
            if organize_match:
                return self.file_domain._organize_folder_preview((organize_match.group(1) or "downloads").strip())

            show_match = re.match(
                r"^(?:show me|display)\s+(?P<target>(?:that|the)\s+(?:file|folder|directory|item)|.+?)[.!?]*$",
                normalized_text,
                flags=re.IGNORECASE,
            )
            if show_match:
                return self.app_browser_domain._open_target(show_match.group("target").strip())

            open_type_match = re.match(
                r"^(?:open|launch|start)\s+(?P<app>.+?)\s+and\s+(?P<verb>type|write|paste)\s+(?P<content>.+?)[.!?]*$",
                normalized_text,
                flags=re.IGNORECASE,
            )
            if open_type_match:
                app_target = open_type_match.group("app").strip()
                verb = open_type_match.group("verb").strip().lower()
                content = open_type_match.group("content").strip()
                return self.app_browser_domain._open_and_type(app_target, content, press_enter=verb == "paste")

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
                    return self.app_browser_domain._youtube_search(query, browser=browser)
                return self.app_browser_domain._google_search(query, browser=browser)

            open_site_match = re.match(
                r"^(?:open|launch|start)\s+(?P<browser>chrome|edge|microsoft edge)\s+and\s+open\s+(?P<site>youtube|google|gmail|https?://\S+|www\.\S+|\S+\.\S+)[.!?]*$",
                normalized_text,
                flags=re.IGNORECASE,
            )
            if open_site_match:
                browser = open_site_match.group("browser").strip()
                site = open_site_match.group("site").strip()
                url = self.app_browser_domain._resolve_web_target(site) or site
                try:
                    self.app_browser_domain._open_url(url, browser=browser)
                    return {
                        "success": True,
                        "action": "open",
                        "message": f"Opening {self.app_browser_domain._normalize_target(site)} in {self.app_browser_domain._normalize_target(browser)}.",
                    }
                except Exception as exc:
                    return {
                        "success": False,
                        "action": "open",
                    "message": f"I could not open {site} in {browser}: {exc}",
                    }

            multi_action_commands = self.app_browser_domain._split_compound_commands(normalized_text)
            if len(multi_action_commands) > 1:
                return self.app_browser_domain._execute_multi_action_commands(multi_action_commands)

            if lowered.startswith(self.OPEN_PREFIXES):
                target = re.sub(r"^(open|launch|start)\s+", "", normalized_text, flags=re.IGNORECASE).strip()
                return self.app_browser_domain._open_target(target)

            browser_youtube_match = re.match(
                r"^(?:in|on)\s+(chrome|edge|microsoft edge)\s+(?:search|open)\s+youtube(?:\s+for)?\s+(.+?)[.!?]*$",
                normalized_text,
                flags=re.IGNORECASE,
            )
            if browser_youtube_match:
                return self.app_browser_domain._youtube_search(browser_youtube_match.group(2).strip(), browser=browser_youtube_match.group(1).strip())

            browser_google_match = re.match(
                r"^(?:in|on)\s+(chrome|edge|microsoft edge)\s+(?:search|open)\s+google(?:\s+for)?\s+(.+?)[.!?]*$",
                normalized_text,
                flags=re.IGNORECASE,
            )
            if browser_google_match:
                return self.app_browser_domain._google_search(browser_google_match.group(2).strip(), browser=browser_google_match.group(1).strip())

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
                    return self.app_browser_domain._youtube_search(query, browser=browser)
                return self.app_browser_domain._google_search(query, browser=browser)

            if re.match(r"^(?:in|on)\s+chrome\s+(?:search|open)\s+youtube[.!?]*$", lowered):
                return self.app_browser_domain._execute_multi_action_commands(["open chrome", "open youtube"])

            if re.match(r"^(?:in|on)\s+chrome\s+(?:search|open)\s+google[.!?]*$", lowered):
                return self.app_browser_domain._execute_multi_action_commands(["open chrome", "open google"])

            if lowered.startswith(self.CLOSE_PREFIXES):
                target = re.sub(r"^(close|kill)\s+", "", normalized_text, flags=re.IGNORECASE).strip()
                return self.app_browser_domain._close_target(target)

            if lowered.startswith(self.PLAY_PREFIXES):
                target = re.sub(r"^play\s+", "", normalized_text, flags=re.IGNORECASE).strip()
                if re.fullmatch(r"(?:the\s+)?first\s+result", target, flags=re.IGNORECASE):
                    return self.app_browser_domain._play_first_result()
                return self.app_browser_domain._play_media(target)

            if lowered.startswith(self.TYPE_PREFIXES):
                text_to_type = re.sub(r"^(type|paste)\s+", "", normalized_text, flags=re.IGNORECASE).strip()
                return self.app_browser_domain._type_text(text_to_type)

            if lowered.startswith(self.GOOGLE_SEARCH_PREFIXES):
                target = re.sub(r"^(google search|search google for)\s+", "", normalized_text, flags=re.IGNORECASE).strip()
                return self.app_browser_domain._google_search(target)

            if lowered.startswith(self.YOUTUBE_SEARCH_PREFIXES):
                target = re.sub(r"^(youtube search|search youtube for)\s+", "", normalized_text, flags=re.IGNORECASE).strip()
                return self.app_browser_domain._youtube_search(target)

            if lowered in {"mute", "unmute", "volume up", "volume down"}:
                return self.system_domain._system_command(lowered)

            create_folder_match = re.match(
                r"^(?:create|make)(?:\s+a)?(?:\s+new)?\s+(?:folder|directory)(?:\s+called)?\s+(.+?)[.!?]*$",
                normalized_text,
                flags=re.IGNORECASE,
            )
            if create_folder_match:
                return self.file_domain._create_folder(create_folder_match.group(1).strip())

            create_and_write_match = re.match(
                r"^(?:create|make)(?:\s+a)?(?:\s+new)?\s+file(?:\s+called)?\s+(?P<target>.+?)\s+and\s+in\s+(?:that|the)\s+file\s+(?:add|write|append|put|insert)\s+(?P<content>[\s\S]+?)[.!?]*$",
                normalized_text,
                flags=re.IGNORECASE,
            )
            if create_and_write_match:
                target = create_and_write_match.group("target").strip()
                content = create_and_write_match.group("content").strip().rstrip(".!?")
                return self.file_domain._create_file_or_ask_for_location(target, content)

            create_match = re.match(
                r"^(?:create|make)(?:\s+a)?(?:\s+new)?\s+file(?:\s+called)?\s+(.+?)(?:(?:\s+with\s+content|\s+and\s+write|\s+and\s+add)\s+([\s\S]+))?[.!?]*$",
                normalized_text,
                flags=re.IGNORECASE,
            )
            if create_match:
                target = create_match.group(1).strip()
                content = (create_match.group(2) or "").strip().rstrip(".!?")
                return self.file_domain._create_file_or_ask_for_location(target, content)

            create_in_folder_match = re.match(
                r"^(?:in\s+)?(?P<folder>(?:that|the)\s+folder|.+?)\s+(?:add|create|make)\s+(?:a\s+)?file(?:\s+called)?\s+(?P<name>.+?)(?:\s+and\s+in\s+(?:that|the)\s+file\s+(?:add|write|append|put|insert)\s+(?P<content>.+))?[.!?]*$",
                normalized_text,
                flags=re.IGNORECASE,
            )
            if create_in_folder_match:
                folder = create_in_folder_match.group("folder").strip()
                name = create_in_folder_match.group("name").strip()
                content = (create_in_folder_match.group("content") or "").strip().rstrip(".!?")
                return self.file_domain._create_file_in_folder(folder, name, content)

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
                return self.file_domain._update_file("that file", content, append=append)

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
                return self.file_domain._update_file(target, content, append=append)

            delete_match = re.match(
                r"^(?:delete|remove)(?:\s+the)?\s+file\s+(.+?)[.!?]*$",
                normalized_text,
                flags=re.IGNORECASE,
            )
            if delete_match:
                target = delete_match.group(1).strip()
                return self.file_domain._delete_file(target)

            delete_folder_match = re.match(
                r"^(?:delete|remove)(?:\s+the)?\s+(?:folder|directory)\s+(.+?)[.!?]*$",
                normalized_text,
                flags=re.IGNORECASE,
            )
            if delete_folder_match:
                return self.file_domain._delete_folder(delete_folder_match.group(1).strip())

            rename_match = re.match(
                r"^rename(?:\s+the)?\s+(?:(file|folder|directory)\s+)?(.+?)\s+to\s+(.+?)[.!?]*$",
                normalized_text,
                flags=re.IGNORECASE,
            )
            if rename_match:
                target_kind = (rename_match.group(1) or "").strip().lower()
                source = rename_match.group(2).strip()
                new_name = rename_match.group(3).strip()
                return self.file_domain._rename_target(source, new_name, target_kind=target_kind)

            move_match = re.match(
                r"^move(?:\s+the)?\s+(?:(file|folder|directory)\s+)?(.+?)\s+(?:to|into)\s+(.+?)[.!?]*$",
                normalized_text,
                flags=re.IGNORECASE,
            )
            if move_match:
                target_kind = (move_match.group(1) or "").strip().lower()
                source = move_match.group(2).strip()
                destination = move_match.group(3).strip()
                return self.file_domain._move_target(source, destination, target_kind=target_kind)

            return {
                "success": False,
                "action": "unsupported",
                "message": "Automation supports opening and closing apps, play and search commands, system volume controls, and creating, editing, moving, renaming, and deleting files or folders across your laptop except protected system locations.",
            }

    def _build_automation_tool_registry(self) -> ToolRegistry:
            file_tool = FileTool(self.file_domain)
            if not isinstance(getattr(file_tool, "name", None), str) or not str(getattr(file_tool, "name", "")).strip():
                file_tool.name = "file"
            return ToolRegistry(
                [
                    file_tool,
                    BrowserTool(BrowserConnector(self.browser_control_service), automation_bridge=self.app_browser_domain),
                    AppTool(self.app_browser_domain),
                    AppLauncherTool(self.app_browser_domain),
                    AppInteractionTool(),
                    SystemTool(self.system_domain),
                    WhatsAppTool(self.whatsapp_domain),
                    GmailTool(contact_resolution_service=self.contact_resolution_service),
                    SummaryTool(),
                ]
            )

    def _execute_canonical_command(self, command: str) -> Dict[str, object] | None:
            registry = self._build_automation_tool_registry()
            probe_orchestrator = MainOrchestrator(registry=ToolRegistry(), enforce_policy=False)
            route = probe_orchestrator.route(command)
            if route is None:
                return None
            if not registry.contains(route.tool_name) and registry.by_intent(route.intent) is None:
                return None
            payload: dict[str, object] = {"turn_id": self._active_turn_id} if self._active_turn_id else {}
            if self._active_automation_context is not None:
                payload["automation_context"] = self._active_automation_context
            orchestrator = MainOrchestrator(registry=registry, enforce_policy=True)
            result = orchestrator.execute(
                ToolContext(
                    command=command,
                    intent=route.intent,
                    session_id=self._active_session_id,
                    request_id=self._active_turn_id,
                    payload=payload,
                    source=self._active_request_source,
                    security_state={"step_up_verified": self._active_step_up_verified},
                )
            )
            if route.tool_name == "file" and isinstance(result, dict) and result.get("action") == "confirmation_required":
                self._stage_delete_target_for_confirmation(command)
            return result

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
                    source=self._active_request_source,
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
                self._pending_delete_target = self.file_domain._resolve_existing_target(match.group(1).strip(), target_kind=target_kind)
            except ValueError:
                self._pending_delete_target = None

    def _execute_multistep_tool_plan(self, command: str) -> Dict[str, str | bool] | None:
            if self.whatsapp_domain._looks_like_whatsapp_command(str(command or "").strip().lower()):
                return None
            probe_orchestrator = MainOrchestrator(registry=ToolRegistry(), enforce_policy=False)
            route = probe_orchestrator.route(command)
            if route is not None and route.tool_name == "file" and route.operation == "search_files":
                return None
            payload = {"turn_id": self._active_turn_id} if self._active_turn_id else {}
            if self._active_automation_context is not None:
                payload["automation_context"] = self._active_automation_context
            tool_context = ToolContext(
                command=command,
                session_id=self._active_session_id,
                request_id=self._active_turn_id,
                payload=payload,
                source=self._active_request_source,
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
            if self.file_domain._looks_like_explicit_path_request(target):
                return None
            file_name = self.file_domain._clean_file_name(self.file_domain._sanitize_file_reference(target))
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
                if not self.file_domain._looks_like_explicit_path_request(target):
                    return None
                try:
                    path = self.file_domain._resolve_folder_target(target)
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
            if not self.file_domain._looks_like_explicit_path_request(target):
                return None
            try:
                path = self.file_domain._resolve_file_target(target)
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
                    source=self._active_request_source,
                    security_state={"step_up_verified": self._active_step_up_verified},
                ),
            )

    def _looks_like_mark_request(self, lowered: str) -> bool:
            if self.whatsapp_domain._looks_like_whatsapp_command(lowered):
                return True
            if self.whatsapp_domain._looks_like_send_message(lowered):
                return True
            if self.system_domain._looks_like_browser_control(lowered):
                return True
            if self.system_domain._looks_like_computer_control(lowered):
                return True
            if self.system_domain._looks_like_youtube_tool(lowered):
                return True
            if self.game_service.can_handle(lowered):
                return True
            if self.system_domain._looks_like_safe_command_info(lowered):
                return True
            return self.system_domain._looks_like_extended_setting(lowered)

    def _execute_mark_request(self, command: str) -> Dict[str, str | bool] | None:
            lowered = command.lower()

            whatsapp_result = self.whatsapp_domain._execute_whatsapp_command(command)
            if whatsapp_result is not None:
                pending = whatsapp_result.get("pending") if isinstance(whatsapp_result, dict) else None
                if pending:
                    kind = "send_message" if whatsapp_result.get("action") == "send_message_pending" else "whatsapp_call"
                    self._pending_mark_action = {"kind": kind, "payload": pending}
                return whatsapp_result

            message_result = self.whatsapp_domain._prepare_message_action(command)
            if message_result is not None:
                pending = message_result.get("pending")
                if pending:
                    self._pending_mark_action = {"kind": "send_message", "payload": pending}
                return message_result

            youtube_result = self.system_domain._execute_youtube_tool(command)
            if youtube_result is not None:
                return youtube_result

            browser_result = self.system_domain._execute_browser_control(command)
            if browser_result is not None:
                return browser_result

            control_result = self.system_domain._execute_computer_control(command)
            if control_result is not None:
                return control_result

            if self.system_domain._looks_like_extended_setting(lowered):
                return self.computer_settings_service.execute(self.system_domain._normalize_extended_setting(lowered))

            if self.system_domain._looks_like_safe_command_info(lowered):
                return self.safe_command_info_service.execute(command)

            if self.game_service.can_handle(command):
                return self.game_service.execute(command)

            return None
