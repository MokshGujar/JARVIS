from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class RouteDecision:
    scenario: str
    intent: str
    tool_name: str
    category: str
    operation: str = ""
    confidence: float = 1.0
    parameters: dict[str, Any] = field(default_factory=dict)


class IntentRouter:
    FILE_PATTERNS = (
        ("list", re.compile(r"^(?:list|show)(?:\s+me)?\s+(?:the\s+)?files\b", re.I)),
        ("search_files", re.compile(r"^(?:search\s+(?:my\s+)?files?|search\s+local\s+files?|look\s+in\s+my\s+files?|find\s+files?|find\s+file)\b", re.I)),
        ("search_files", re.compile(r"^find\s+", re.I)),
        ("read", re.compile(r"^(?:read|show|display)(?:\s+me)?\s+(?:the\s+)?(?:file|text\s+file)\b", re.I)),
        ("create", re.compile(r"^(?:create|make)(?:\s+a)?(?:\s+new)?\s+(?:file|folder|directory)\b", re.I)),
        ("rename", re.compile(r"^rename(?:\s+the)?\s+(?:(?:file|folder|directory)\s+)?", re.I)),
        ("move", re.compile(r"^move(?:\s+the)?\s+(?:(?:file|folder|directory)\s+)?", re.I)),
        ("delete", re.compile(r"^(?:delete|remove)(?:\s+the)?\s+(?:file|folder|directory)\b", re.I)),
        ("path", re.compile(r"^(?:where\s+is|show\s+(?:me\s+)?(?:the\s+)?full\s+path|copy\s+(?:the\s+)?path)\b", re.I)),
    )
    WHATSAPP_RE = re.compile(r"\bwhatsapp\b|\b(?:message|text|video\s+call|voice\s+call|call)\s+.+", re.I)
    BROWSER_PATTERNS = (
        ("browser_search", "search", re.compile(r"^(?:browser search|search browser|search in browser|google search|search google for|search web for|search internet for|search online for|search about)\s+.+", re.I)),
        ("browser_search", "search", re.compile(r"^(?:search\s+(?:the\s+)?(?:web|internet|online)\s+for)\s+.+", re.I)),
        ("browser_search", "search", re.compile(r"^search\s+.+\s+on\s+google[.!?]*$", re.I)),
        ("browser_youtube_search", "youtube_search", re.compile(r"^(?:youtube search|search youtube for)\s+.+", re.I)),
        ("browser_youtube_play", "youtube_play", re.compile(r"^play\s+.+\s+(?:on|in)\s+youtube[.!?]*$", re.I)),
        ("browser_open_url", "open_url", re.compile(r"^(?:open url|go to|browser open|browser go to)\s+.+", re.I)),
        ("browser_open_url", "open_url", re.compile(r"^open\s+(?:https?://\S+|www\.\S+|\S+\.\S+)[.!?]*$", re.I)),
        ("browser_open_site", "open_site", re.compile(r"^open\s+(?:youtube|google|gmail|github|stack overflow|stackoverflow)[.!?]*$", re.I)),
        ("browser_navigation", "navigation", re.compile(r"^(?:get page text|read page text|browser get text|browser scroll|scroll browser|close browser|browser close|incognito)\b", re.I)),
        ("browser_form_input", "form_input", re.compile(r"^(?:click browser|browser click|smart click|type in browser|browser type|smart type in browser|fill form)\b", re.I)),
    )
    APP_RE = re.compile(r"^(?P<operation>open|launch|start|close|kill|focus|switch to)\s+", re.I)
    SYSTEM_PATTERNS = (
        ("volume_up", re.compile(r"^(?:volume up|increase volume|turn volume up)\b", re.I)),
        ("volume_down", re.compile(r"^(?:volume down|decrease volume|turn volume down)\b", re.I)),
        ("mute_volume", re.compile(r"^(?:mute|mute volume|unmute|unmute volume)\b", re.I)),
        ("brightness_change", re.compile(r"^(?:brightness up|brightness down|increase brightness|decrease brightness)\b", re.I)),
        ("screenshot", re.compile(r"^(?:take screenshot|screenshot)\b", re.I)),
        ("show_desktop", re.compile(r"^show(?:\s+the)?\s+desktop\b", re.I)),
        ("lock_system", re.compile(r"^lock(?:\s+(?:my\s+)?(?:laptop|computer|screen|system))?\b", re.I)),
        ("shutdown_system", re.compile(r"^(?:shutdown|shut down)(?:\s+(?:my\s+)?(?:laptop|computer|system))?\b", re.I)),
        ("restart_system", re.compile(r"^(?:restart|reboot)(?:\s+(?:my\s+)?(?:laptop|computer|system))?\b", re.I)),
        ("sleep_system", re.compile(r"^(?:sleep|hibernate)(?:\s+(?:my\s+)?(?:laptop|computer|system))?\b", re.I)),
        ("safe_system_info", re.compile(r"^(?:show disk space|disk space|battery status|system info|show system status|give me system status|give me system updates|system update|system report|system health|show computer status|show pc status)\b", re.I)),
        ("window_control", re.compile(r"^(?:hotkey|press|show desktop|switch window|minimize|fullscreen|close current window)\b", re.I)),
    )
    MEMORY_RE = re.compile(r"\b(remember|what did i say earlier|recall|memory)\b", re.I)

    def route(self, text: str) -> RouteDecision | None:
        command = str(text or "").strip()
        if not command:
            return None

        for operation, pattern in self.FILE_PATTERNS:
            if pattern.search(command):
                parameters = self._file_parameters(operation, command)
                return RouteDecision(
                    scenario=f"file.{operation}",
                    intent="file",
                    tool_name="file",
                    category="file",
                    operation=operation,
                    parameters=parameters,
                )

        for intent, operation, pattern in self.BROWSER_PATTERNS:
            if pattern.search(command):
                parameters = self._browser_parameters(operation, command)
                return RouteDecision(
                    scenario=f"browser.{operation}",
                    intent=intent,
                    tool_name="browser",
                    category="browser",
                    operation=operation,
                    parameters=parameters,
                )
        if self.WHATSAPP_RE.search(command):
            operation = self._whatsapp_operation(command)
            return RouteDecision(
                scenario=f"whatsapp.{operation}",
                intent="whatsapp",
                tool_name="whatsapp",
                category="communication",
                operation=operation,
            )
        for operation, pattern in self.SYSTEM_PATTERNS:
            if pattern.search(command):
                return RouteDecision(
                    scenario=f"system.{operation}",
                    intent=operation,
                    tool_name="system",
                    category="system",
                    operation=operation,
                )
        app_match = self.APP_RE.search(command)
        if app_match:
            operation = app_match.group("operation").lower()
            if operation in {"open", "launch", "start"}:
                intent = "app_open"
                app_operation = "open"
            elif operation in {"focus", "switch to"}:
                intent = "app_focus"
                app_operation = "focus"
            else:
                intent = "app_close"
                app_operation = "close"
            return RouteDecision(
                scenario=f"app.{app_operation}",
                intent=intent,
                tool_name="app",
                category="app",
                operation=app_operation,
            )
        if self.MEMORY_RE.search(command):
            return RouteDecision("memory.context", "memory", "memory", "memory")
        return None

    @staticmethod
    def _file_parameters(operation: str, command: str) -> dict[str, Any]:
        if operation != "search_files":
            return {}
        text = str(command or "").strip().strip(".!?")
        patterns = (
            r"^search\s+(?:my\s+)?files?\s+for\s+(?P<query>.+)$",
            r"^search\s+local\s+files?\s+for\s+(?P<query>.+)$",
            r"^look\s+in\s+my\s+files?\s+for\s+(?P<query>.+)$",
            r"^find\s+files?\s+(?:about|for|named|called)?\s*(?P<query>.+)$",
            r"^find\s+file\s+(?:about|for|named|called)?\s*(?P<query>.+)$",
        )
        for pattern in patterns:
            match = re.match(pattern, text, flags=re.I)
            if match:
                query = (match.group("query") or "").strip()
                if query:
                    return {"query": query}
        return {}

    @staticmethod
    def _browser_parameters(operation: str, command: str) -> dict[str, Any]:
        if operation != "search":
            return {}
        text = str(command or "").strip().strip(".!?")
        patterns = (
            r"^(?:google search|search google for|search web for|search internet for|search online for|search about)\s+(?P<query>.+)$",
            r"^search\s+(?P<query>.+?)\s+on\s+google$",
            r"^search\s+(?:the\s+)?(?:web|internet|online)\s+for\s+(?P<query>.+)$",
        )
        for pattern in patterns:
            match = re.match(pattern, text, flags=re.I)
            if match:
                query = (match.group("query") or "").strip()
                if query:
                    return {"query": IntentRouter._normalize_browser_query(query)}
        return {}

    @staticmethod
    def _normalize_browser_query(value: str) -> str:
        query = re.sub(r"\s+", " ", str(value or "").strip()).strip(" .!?")
        previous = None
        while query and query.lower() != previous:
            previous = query.lower()
            query = re.sub(
                r"^(?:search\s+google\s+for|google\s+for|search\s+(?:the\s+)?(?:web|internet|online)\s+for|search\s+about)\s+",
                "",
                query,
                flags=re.I,
            ).strip(" .!?")
        return query

    @staticmethod
    def _whatsapp_operation(command: str) -> str:
        lowered = str(command or "").strip().lower()
        if re.search(r"\b(?:end|hang up|disconnect)\b.*\bcall\b", lowered):
            return "end_call"
        if re.search(r"\b(?:search\s+contact|whatsapp\s+search)\b", lowered):
            return "search_contact"
        if re.search(r"\b(?:send|message|text)\b", lowered):
            return "prepare_message"
        if re.search(r"\b(?:video\s+call|voice\s+call|call)\b", lowered):
            return "prepare_call"
        if re.match(r"^(?:open\s+)?whatsapp(?:\s+(?:web|desktop))?[.!?]*$", lowered) or lowered.startswith("open whatsapp"):
            return "open"
        return "open"
