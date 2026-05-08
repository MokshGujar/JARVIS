from __future__ import annotations

import re
from typing import Any

from app.connectors.browser_connector import BrowserConnector
from app.orchestrator.action_plan import ActionPlan, ActionStep
from app.orchestrator.tool_executor import ToolExecutor
from app.orchestrator.tool_registry import ToolRegistry
from app.tools.base import ToolContext


class AppCompatibilityRunner:
    def __init__(self, bridge: Any) -> None:
        self.bridge = bridge

    def execute(self, command: str) -> dict[str, Any] | None:
        bridge = self.bridge
        normalized_text = bridge._normalize_spoken_command(command)
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
            return bridge._open_and_type(app_target, content, press_enter=verb == "paste")

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
                return bridge._youtube_search(query, browser=browser)
            return bridge._google_search(query, browser=browser)

        open_site_match = re.match(
            r"^(?:open|launch|start)\s+(?P<browser>chrome|edge|microsoft edge)\s+and\s+open\s+(?P<site>youtube|google|gmail|https?://\S+|www\.\S+|\S+\.\S+)[.!?]*$",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if open_site_match:
            browser = open_site_match.group("browser").strip()
            site = open_site_match.group("site").strip()
            url = bridge._resolve_web_target(site) or site
            try:
                bridge._open_url(url, browser=browser)
                return {
                    "success": True,
                    "action": "open",
                    "message": f"Opening {bridge._normalize_target(site)} in {bridge._normalize_target(browser)}.",
                }
            except Exception as exc:
                return {"success": False, "action": "open", "message": f"I could not open {site} in {browser}: {exc}"}

        multi_action_commands = bridge._split_compound_commands(normalized_text)
        if len(multi_action_commands) > 1:
            return bridge._execute_multi_action_commands(multi_action_commands)

        if lowered.startswith(bridge.OPEN_PREFIXES):
            target = re.sub(r"^(open|launch|start)\s+", "", normalized_text, flags=re.IGNORECASE).strip()
            return bridge._open_target(target)

        if lowered.startswith(bridge.CLOSE_PREFIXES):
            target = re.sub(r"^(close|kill)\s+", "", normalized_text, flags=re.IGNORECASE).strip()
            return bridge._close_target(target)

        return None


class SystemCompatibilityRunner:
    def __init__(self, bridge: Any) -> None:
        self.bridge = bridge

    def execute(self, command: str) -> dict[str, Any] | None:
        bridge = self.bridge
        normalized_text = bridge._normalize_spoken_command(command)
        lowered = normalized_text.lower()

        if bridge._looks_like_local_system_status(lowered):
            return bridge.safe_command_info_service.execute("systeminfo")

        if bridge._looks_like_safe_command_info(lowered):
            return bridge.safe_command_info_service.execute(normalized_text)

        system_alias = bridge._match_system_command(lowered)
        if system_alias:
            return bridge._system_command(system_alias)

        control_result = bridge._execute_computer_control(normalized_text)
        if control_result is not None:
            return control_result

        if bridge._looks_like_extended_setting(lowered):
            return bridge.computer_settings_service.execute(bridge._normalize_extended_setting(lowered))

        return None


class FileCompatibilityRunner:
    def __init__(self, bridge: Any) -> None:
        self.bridge = bridge

    def execute(self, command: str, context: ToolContext | None = None) -> dict[str, Any] | None:
        bridge = self.bridge
        normalized_text = bridge._normalize_spoken_command(command)

        path_request_match = re.match(
            r"^(?:where\s+is\s+(?:it|that|that\s+file|the\s+file)|show\s+(?:me\s+)?(?:the\s+)?full\s+path|copy\s+(?:the\s+)?path)[.!?]*$",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if path_request_match:
            return bridge._show_last_file_path()

        list_match = re.match(
            r"^(?:list|show)(?:\s+me)?\s+(?:the\s+)?files(?:\s+(?:in|on|inside|under)\s+(.+?))?[.!?]*$",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if list_match:
            return bridge._list_files((list_match.group(1) or "downloads").strip())

        search_files_match = re.match(
            r"^(?:search\s+(?:my\s+)?files?|search\s+local\s+files?|look\s+in\s+my\s+files?)(?:\s+for\s+(.+?))?[.!?]*$",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if search_files_match:
            query = (search_files_match.group(1) or "").strip()
            if not query:
                return {
                    "success": False,
                    "action": "search_files",
                    "status": "clarification_required",
                    "message": "What file name or content should I search for?",
                    "requires_followup": True,
                    "missing_query": True,
                }
            return bridge._find_files(query, "home")

        read_match = re.match(
            r"^(?:read|show|display)(?:\s+me)?\s+(?:the\s+)?(?:file|text\s+file)\s+(.+?)[.!?]*$",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if read_match:
            return bridge._read_file(read_match.group(1).strip())

        find_match = re.match(
            r"^find\s+(?P<query>.+?)(?:\s+(?:in|inside|under|on)\s+(?P<location>.+?))?[.!?]*$",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if find_match:
            query = find_match.group("query").strip()
            location = (find_match.group("location") or "home").strip()
            if re.search(r"\b(files?|pdfs?|documents?|images?|photos?|videos?|music)\b", query, flags=re.IGNORECASE):
                return bridge._find_files(query, location)

        largest_match = re.match(
            r"^(?:show\s+)?(?:the\s+)?(?:largest|biggest)\s+files(?:\s+(?:in|on|inside|under)\s+(.+?))?[.!?]*$",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if largest_match:
            return bridge._largest_files((largest_match.group(1) or "home").strip())

        organize_match = re.match(
            r"^(?:(?:preview\s+)?organize|organize\s+preview)(?:\s+(?:the\s+)?(?:folder|directory))?(?:\s+(?:in|on|inside|under)\s+(.+?))?[.!?]*$",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if organize_match:
            return bridge._organize_folder_preview((organize_match.group(1) or "downloads").strip())

        show_match = re.match(
            r"^(?:show me|display)\s+(?P<target>(?:that|the)\s+(?:file|folder|directory|item)|.+?)[.!?]*$",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if show_match:
            return bridge._open_target(show_match.group("target").strip())

        create_folder_match = re.match(
            r"^(?:create|make)(?:\s+a)?(?:\s+new)?\s+(?:folder|directory)(?:\s+called)?\s+(.+?)[.!?]*$",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if create_folder_match:
            return bridge._create_folder(create_folder_match.group(1).strip())

        create_and_write_match = re.match(
            r"^(?:create|make)(?:\s+a)?(?:\s+new)?\s+file(?:\s+called)?\s+(?P<target>.+?)\s+and\s+in\s+(?:that|the)\s+file\s+(?:add|write|append|put|insert)\s+(?P<content>[\s\S]+?)[.!?]*$",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if create_and_write_match:
            target = create_and_write_match.group("target").strip()
            content = create_and_write_match.group("content").strip().rstrip(".!?")
            return bridge._create_file_or_ask_for_location(target, content)

        create_match = re.match(
            r"^(?:create|make)(?:\s+a)?(?:\s+new)?\s+file(?:\s+called)?\s+(.+?)(?:(?:\s+with\s+content|\s+and\s+write|\s+and\s+add)\s+([\s\S]+))?[.!?]*$",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if create_match:
            target = create_match.group(1).strip()
            content = (create_match.group(2) or "").strip().rstrip(".!?")
            return bridge._create_file_or_ask_for_location(target, content)

        create_in_folder_match = re.match(
            r"^(?:in\s+)?(?P<folder>(?:that|the)\s+folder|.+?)\s+(?:add|create|make)\s+(?:a\s+)?file(?:\s+called)?\s+(?P<name>.+?)(?:\s+and\s+in\s+(?:that|the)\s+file\s+(?:add|write|append|put|insert)\s+(?P<content>.+))?[.!?]*$",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if create_in_folder_match:
            folder = create_in_folder_match.group("folder").strip()
            name = create_in_folder_match.group("name").strip()
            content = (create_in_folder_match.group("content") or "").strip().rstrip(".!?")
            return bridge._create_file_in_folder(folder, name, content)

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
            return bridge._update_file("that file", content, append=append)

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
            return bridge._update_file(target, content, append=append)

        delete_match = re.match(r"^(?:delete|remove)(?:\s+the)?\s+file\s+(.+?)[.!?]*$", normalized_text, flags=re.IGNORECASE)
        if delete_match:
            return bridge._delete_file(delete_match.group(1).strip())

        delete_folder_match = re.match(
            r"^(?:delete|remove)(?:\s+the)?\s+(?:folder|directory)\s+(.+?)[.!?]*$",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if delete_folder_match:
            return bridge._delete_folder(delete_folder_match.group(1).strip())

        rename_match = re.match(
            r"^rename(?:\s+the)?\s+(?:(file|folder|directory)\s+)?(.+?)\s+to\s+(.+?)[.!?]*$",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if rename_match:
            target_kind = (rename_match.group(1) or "").strip().lower()
            source = rename_match.group(2).strip()
            new_name = rename_match.group(3).strip()
            return bridge._rename_target(source, new_name, target_kind=target_kind)

        move_match = re.match(
            r"^move(?:\s+the)?\s+(?:(file|folder|directory)\s+)?(.+?)\s+(?:to|into)\s+(.+?)[.!?]*$",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if move_match:
            target_kind = (move_match.group(1) or "").strip().lower()
            source = move_match.group(2).strip()
            destination = move_match.group(3).strip()
            return bridge._move_target(source, destination, target_kind=target_kind)

        return None


class BrowserCompatibilityRunner:
    def __init__(self, bridge: Any) -> None:
        self.bridge = bridge

    def execute_control(self, command: str) -> dict[str, Any] | None:
        bridge = self.bridge
        from app.tools.browser_tool import BrowserTool

        executor = ToolExecutor(registry=ToolRegistry([BrowserTool(BrowserConnector(bridge.browser_control_service))]), enforce_policy=True)
        return executor.execute(
            ActionPlan(
                original_text=command,
                steps=[ActionStep("step1", "browser", "browser", "navigation", {})],
                is_multistep=False,
            ),
            ToolContext(
                command=command,
                intent="browser",
                session_id=bridge._active_session_id,
                request_id=bridge._active_turn_id,
                payload={"turn_id": bridge._active_turn_id} if bridge._active_turn_id else {},
            ),
        )

    def execute(self, command: str, context: ToolContext | None = None) -> dict[str, Any] | None:
        bridge = self.bridge
        normalized_text = bridge._normalize_spoken_command(command)
        lowered = normalized_text.lower()

        if bridge._looks_like_browser_control(lowered):
            control_result = self.execute_control(normalized_text)
            if control_result is not None:
                return control_result

        google_search_match = re.match(
            r"^(?:google search|search google for|search web for|search internet for|search online for|search about)\s+(.+?)(?:\s+on\s+google)?[.!?]*$|^search\s+(.+?)\s+on\s+google[.!?]*$",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if google_search_match:
            query_text = google_search_match.group(1) or google_search_match.group(2) or ""
            query = bridge._normalize_browser_search_query(query_text.strip())
            query = re.sub(r"\s+on\s+google$", "", query, flags=re.IGNORECASE).strip()
            return bridge._google_search(query)

        youtube_search_match = re.match(r"^(?:youtube search|search youtube for)\s+(.+?)[.!?]*$", normalized_text, flags=re.IGNORECASE)
        if youtube_search_match:
            return bridge._youtube_search(youtube_search_match.group(1).strip())

        youtube_play_match = re.match(r"^play\s+(.+?)\s+(?:on|in)\s+youtube[.!?]*$", normalized_text, flags=re.IGNORECASE)
        if youtube_play_match:
            return bridge._play_media(youtube_play_match.group(1).strip())

        open_match = re.match(r"^(?:open|launch|start)\s+(.+?)[.!?]*$", normalized_text, flags=re.IGNORECASE)
        if open_match:
            return bridge._open_target(open_match.group(1).strip())

        return None


class WhatsAppCompatibilityRunner:
    def __init__(self, bridge: Any) -> None:
        self.bridge = bridge

    def execute(self, command: str) -> dict[str, Any] | None:
        bridge = self.bridge
        text = bridge._normalize_spoken_command(command)
        lowered = text.lower().strip()

        if re.match(r"^open\s+whatsapp\s+web[.!?]*$", lowered) or lowered == "whatsapp web":
            return bridge._open_whatsapp_web()

        if re.match(r"^open\s+whatsapp(?:\s+desktop)?[.!?]*$", lowered) or lowered == "whatsapp desktop":
            return bridge._open_whatsapp_desktop_or_web()

        open_chat_intent = bridge._extract_whatsapp_open_chat_intent(text)
        if open_chat_intent is not None:
            contact = str(open_chat_intent.get("contact") or "").strip()
            if bridge._is_ambiguous_communication_contact(contact):
                return bridge._whatsapp_contact_required_result("open_chat")
            return bridge._prepare_whatsapp_open_chat(contact)

        open_call_match = re.match(
            r"^open\s+whatsapp(?:\s+(?:desktop|web))?\s+and\s+(?P<mode>video\s+call|voice\s+call|call)\s+(?P<contact>.+?)[.!?]*$",
            text,
            flags=re.IGNORECASE,
        )
        if open_call_match:
            opened = bridge._open_whatsapp_desktop_or_web()
            if not opened.get("success"):
                return opened
            mode = "video" if "video" in open_call_match.group("mode").lower() else "voice"
            contact = bridge._clean_whatsapp_contact(open_call_match.group("contact"))
            if bridge._is_ambiguous_communication_contact(contact):
                prompt = bridge._whatsapp_contact_required_result("whatsapp_call", {"mode": mode})
                prompt["actions"] = list(opened.get("actions") or []) + list(prompt.get("actions") or [])
                return prompt
            pending = bridge._prepare_whatsapp_call_confirmation(mode, contact)
            if pending.get("action") == "whatsapp_call_pending":
                return {
                    **pending,
                    "action": "multi_action",
                    "message": f"{opened.get('message')} {pending.get('message')}",
                    "display_text": f"{opened.get('message')} {pending.get('message')}",
                    "actions": list(opened.get("actions") or []) + list(pending.get("actions") or []),
                    "pending": pending.get("pending"),
                }
            if isinstance(pending, dict):
                pending["actions"] = list(opened.get("actions") or []) + list(pending.get("actions") or [])
            return pending

        match = re.match(r"^(?:search\s+contact\s+in\s+whatsapp|whatsapp\s+search)\s+(.+?)[.!?]*$", text, flags=re.IGNORECASE)
        if match:
            contact = match.group(1).strip()
            opened = bridge._open_whatsapp_desktop_or_web()
            if not opened.get("success"):
                return opened
            return bridge._status_result(
                "whatsapp_search_contact",
                f"WhatsApp is open. Search for {contact} manually if the desktop search box is not focused.",
                success=False,
                status="needs_manual_verification",
            )

        call_intent = bridge._extract_whatsapp_call_intent(text)
        if call_intent is not None:
            mode = str(call_intent.get("mode") or "voice")
            contact = str(call_intent.get("contact") or "").strip()
            if bridge._is_ambiguous_communication_contact(contact):
                return bridge._whatsapp_contact_required_result("whatsapp_call", {"mode": mode})
            return bridge._prepare_whatsapp_call_confirmation(mode, contact)

        message_intent = bridge._extract_whatsapp_message_intent(text)
        if message_intent is not None:
            receiver = str(message_intent.get("receiver") or "").strip()
            message = str(message_intent.get("message") or "").strip()
            receiver, message = bridge._repair_whatsapp_message_contact(receiver, message)
            if bridge._is_ambiguous_communication_contact(receiver):
                return bridge._whatsapp_contact_required_result("send_message", {"platform": "whatsapp", "message": message})
            if not message:
                bridge._pending_whatsapp_clarification = {
                    "kind": "send_message_text",
                    "payload": {"platform": "whatsapp", "receiver": receiver},
                }
                prompt = f"What should I say to {receiver} on WhatsApp?"
                return bridge._status_result(
                    "whatsapp_message_text_required",
                    prompt,
                    success=False,
                    status="whatsapp_message_text_required",
                )
            return bridge._prepare_whatsapp_message_confirmation(receiver, message)

        if re.match(r"^(?:end|hang up|disconnect)(?:\s+the)?\s+(?:whatsapp\s+)?call[.!?]*$", lowered):
            return bridge._end_whatsapp_call()

        return None
