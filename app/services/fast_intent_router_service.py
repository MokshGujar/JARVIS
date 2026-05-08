from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from app.services.decision_types import (
    INTENT_GOOGLE_SEARCH,
    INTENT_OPEN,
    INTENT_PLAY,
    INTENT_YOUTUBE_SEARCH,
)


@dataclass
class FastIntentRoute:
    type: str
    intent: str = ""
    confidence: float = 0.0
    requires_llm: bool = False
    safe_to_execute: bool = False
    requires_face_auth: bool = False
    payload: Dict[str, Any] = field(default_factory=dict)
    sensitive: bool = False
    reason: str = ""
    elapsed_ms: int = 0


class FastIntentRouterService:
    """Deterministic pre-LLM router for commands that do not need reasoning."""

    _CURRENT_INFO_RE = re.compile(
        r"\b("
        r"latest|current|today|tonight|tomorrow|yesterday|news|weather|score|price|"
        r"stock|crypto|review|reviews|near me|who is|who are|what happened|"
        r"search the web|look it up|research|find out"
        r")\b",
        re.IGNORECASE,
    )
    _QUESTION_RE = re.compile(r"\b(what|why|how|who|when|where|explain|tell me about)\b", re.IGNORECASE)
    _ACTION_RE = re.compile(
        r"\b(open|launch|start|play|call|dial|phone|message|text|sms|whatsapp|email|gmail|mail|"
        r"delete|remove|shutdown|shut down|sleep|lock)\b",
        re.IGNORECASE,
    )
    _DESTRUCTIVE_RE = re.compile(
        r"\b(delete|remove|format|rm\s+-rf|shutdown|shut\s+down|sleep|lock|"
        r"erase|wipe|kill|taskkill|registry|regedit)\b",
        re.IGNORECASE,
    )
    _SYSTEM_SENSITIVE_RE = re.compile(r"\b(shutdown|shut\s+down|sleep|lock(?:\s+screen)?)\b", re.IGNORECASE)
    _TIME_DATE_RE = re.compile(
        r"^(?:what(?:'s| is)?\s+)?(?:the\s+)?(?:current\s+)?(?P<kind>time|date)(?:\s+is\s+it)?$",
        re.IGNORECASE,
    )
    _GOOGLE_SEARCH_RE = re.compile(r"^(?:google|google search|search google for)\s+(.+)$", re.IGNORECASE)
    _YOUTUBE_SEARCH_RE = re.compile(r"^(?:youtube|youtube search|search youtube for)\s+(.+)$", re.IGNORECASE)

    def __init__(
        self,
        *,
        phone_command_service=None,
        automation_service=None,
        wake_on_lan_service=None,
        reminder_service=None,
        research_tools_service=None,
        brain_service=None,
    ) -> None:
        self.phone_command_service = phone_command_service
        self.automation_service = automation_service
        self.wake_on_lan_service = wake_on_lan_service
        self.reminder_service = reminder_service
        self.research_tools_service = research_tools_service
        self.brain_service = brain_service

    def route(self, message: str, *, imgbase64: Optional[str] = None) -> FastIntentRoute:
        start = time.perf_counter()
        text = (message or "").strip()
        lowered = self._normalize(text)

        def done(route: FastIntentRoute) -> FastIntentRoute:
            route.elapsed_ms = int((time.perf_counter() - start) * 1000)
            return route

        if not lowered:
            return done(self._llm_route(intent="empty", reason="empty"))

        if imgbase64:
            return done(self._llm_route(intent="vision", reason="image_input"))

        if self._looks_like_mixed(lowered):
            return done(self._llm_route(intent="mixed", reason="mixed_action_and_question"))

        pending = self._pending_route(text, lowered)
        if pending:
            return done(pending)

        whatsapp_route = self._whatsapp_automation_route(text, lowered)
        if whatsapp_route:
            return done(whatsapp_route)

        if self.automation_service and re.search(r"\b(?:gmail|email|mail)\b", lowered) and re.search(r"\b(?:send|draft|compose|write|reply|search|read|unread)\b", lowered):
            return done(self._instant_route(intent="automation", confidence=0.9, safe_to_execute=True, reason="gmail_communication"))

        phone_route = self._phone_route(text, lowered)
        if phone_route:
            return done(phone_route)

        if self.wake_on_lan_service and self.wake_on_lan_service.looks_like_wake_request(text):
            return done(self._instant_route(intent="wake_on_lan", confidence=0.96, reason="wake_on_lan"))

        if self.reminder_service and self.reminder_service.looks_like_reminder_request(text):
            return done(self._instant_route(intent="reminder", confidence=0.9, reason="reminder"))

        info_route = self._simple_info_route(text, lowered)
        if info_route:
            return done(info_route)

        task_route = self._task_route(text, lowered)
        if task_route:
            return done(task_route)

        if self.automation_service and self.automation_service.looks_like_automation_request(text):
            sensitive = self._is_sensitive_automation(lowered)
            return done(
                self._instant_route(
                    intent="automation",
                    confidence=0.86,
                    safe_to_execute=True,
                    requires_face_auth=sensitive,
                    sensitive=sensitive,
                    reason="automation",
                )
            )

        if self.research_tools_service and self.research_tools_service.looks_like_research_request(text):
            return done(self._llm_route(intent="research", reason="research_tool"))

        if self._CURRENT_INFO_RE.search(lowered):
            return done(self._llm_route(intent="current_info", reason="current_or_research_query"))

        return done(self._llm_route(intent="unknown", reason="no_fast_match"))

    def _pending_route(self, text: str, lowered: str) -> Optional[FastIntentRoute]:
        if self.phone_command_service:
            if self.phone_command_service.looks_like_call_method_followup(text):
                return self._instant_route(
                    intent="phone",
                    confidence=0.94,
                    safe_to_execute=True,
                    requires_face_auth=True,
                    sensitive=True,
                    reason="phone_call_method_followup",
                )
            if self.phone_command_service.looks_like_message_channel_followup(text):
                return self._instant_route(
                    intent="phone",
                    confidence=0.94,
                    safe_to_execute=True,
                    requires_face_auth=True,
                    sensitive=True,
                    reason="phone_message_channel_followup",
                )

        if self.automation_service:
            if self.automation_service.has_pending_delete_confirmation():
                return self._instant_route(
                    intent="automation",
                    confidence=0.95,
                    safe_to_execute=True,
                    requires_face_auth=True,
                    sensitive=True,
                    reason="delete_confirmation",
                )
            if self.automation_service.has_pending_mark_confirmation():
                sensitive = lowered in {"yes", "y", "go ahead", "confirm", "delete it"}
                return self._instant_route(
                    intent="automation",
                    confidence=0.95,
                    safe_to_execute=True,
                    requires_face_auth=sensitive,
                    sensitive=sensitive,
                    reason="automation_confirmation",
                )
            if (
                hasattr(self.automation_service, "has_pending_whatsapp_clarification")
                and self.automation_service.has_pending_whatsapp_clarification()
            ):
                return self._instant_route(
                    intent="automation",
                    confidence=0.95,
                    safe_to_execute=True,
                    requires_face_auth=False,
                    sensitive=False,
                    reason="whatsapp_contact_clarification",
                )
            if self.automation_service.has_pending_open_clarification():
                return self._instant_route(
                    intent="automation",
                    confidence=0.93,
                    safe_to_execute=True,
                    reason="open_clarification",
                )
            if self.automation_service.has_pending_browser_search():
                return self._instant_route(
                    intent="automation",
                    confidence=0.9,
                    safe_to_execute=True,
                    reason="browser_search_followup",
                )
            if self.automation_service.has_pending_create_file_location():
                return self._instant_route(
                    intent="automation",
                    confidence=0.9,
                    safe_to_execute=True,
                    reason="file_location_followup",
                )

        return None

    def _whatsapp_automation_route(self, text: str, lowered: str) -> Optional[FastIntentRoute]:
        if not self.automation_service:
            return None
        if re.search(r"\b(?:normal|regular|phone|dial)\s+(?:call|dial|phone)\b", lowered):
            return None
        if re.match(r"^(?:dial|phone)\b", lowered):
            return None
        if not re.search(r"\b(?:call|voice\s+call|video\s+call|message|text|whatsapp)\b", lowered):
            return None
        try:
            if not self.automation_service.looks_like_automation_request(text):
                return None
        except Exception:
            return None
        return self._instant_route(
            intent="automation",
            confidence=0.93,
            safe_to_execute=True,
            requires_face_auth=False,
            sensitive=False,
            reason="whatsapp_communication",
        )

    def _phone_route(self, text: str, lowered: str) -> Optional[FastIntentRoute]:
        if not self.phone_command_service:
            return None

        if (
            self.phone_command_service.looks_like_answer_request(text)
            or self.phone_command_service.looks_like_reject_request(text)
            or self.phone_command_service.looks_like_place_call_request(text)
            or self.phone_command_service.looks_like_message_request(text)
        ):
            intent = "message" if self.phone_command_service.looks_like_message_request(text) else "call"
            return self._instant_route(
                intent="phone",
                confidence=0.96,
                safe_to_execute=True,
                requires_face_auth=True,
                payload={"phone_intent": intent},
                sensitive=True,
                reason="phone_command",
            )

        return None

    def _simple_info_route(self, text: str, lowered: str) -> Optional[FastIntentRoute]:
        if not self.automation_service:
            return None

        cleaned = lowered.rstrip(" ?!.")
        if cleaned in {
            "time",
            "time now",
            "what time is it",
            "what is the time",
            "current time",
            "date",
            "date today",
            "what date is it",
            "what is the date",
            "current date",
            "today's date",
            "todays date",
        }:
            return self._instant_route(
                intent="automation",
                confidence=0.92,
                safe_to_execute=True,
                reason="simple_system_query",
                payload={"query_kind": "time_date", "target": text},
            )

        match = self._TIME_DATE_RE.match(cleaned)
        if match:
            return self._instant_route(
                intent="automation",
                confidence=0.92,
                safe_to_execute=True,
                reason="simple_system_query",
                payload={"query_kind": match.group("kind").lower(), "target": text},
            )

        return None

    def _task_route(self, text: str, lowered: str) -> Optional[FastIntentRoute]:
        if re.match(r"^(?:open|launch|start)\s+(.+)$", lowered):
            target = re.sub(r"^(?:open|launch|start)\s+", "", text, flags=re.IGNORECASE).strip()
            if self.automation_service:
                return self._instant_route(
                    intent="automation",
                    confidence=0.94,
                    safe_to_execute=True,
                    payload={"target": target, "command": text},
                    reason="open_automation",
                )
            return self._instant_route(
                intent=INTENT_OPEN,
                confidence=0.92,
                safe_to_execute=True,
                payload={"target": target, "intents": [(INTENT_OPEN, {"url": self._resolve_open_target(target), "message": text})]},
                reason="open_command",
            )

        if re.match(r"^play\s+(.+)$", lowered):
            target = re.sub(r"^play\s+", "", text, flags=re.IGNORECASE).strip()
            if self.automation_service:
                return self._instant_route(
                    intent="automation",
                    confidence=0.94,
                    safe_to_execute=True,
                    payload={"target": target, "command": text},
                    reason="play_automation",
                )
            return self._instant_route(
                intent=INTENT_PLAY,
                confidence=0.92,
                safe_to_execute=True,
                payload={"target": target, "intents": [(INTENT_PLAY, {"query": target, "message": text})]},
                reason="play_command",
            )

        google_match = self._GOOGLE_SEARCH_RE.match(text)
        if google_match:
            query = google_match.group(1).strip()
            if self.automation_service:
                return self._instant_route(
                    intent="automation",
                    confidence=0.94,
                    safe_to_execute=True,
                    payload={"target": query, "command": text},
                    reason="google_search_automation",
                )
            return self._instant_route(
                intent=INTENT_GOOGLE_SEARCH,
                confidence=0.9,
                safe_to_execute=True,
                payload={"target": query, "intents": [(INTENT_GOOGLE_SEARCH, {"query": query, "message": text})]},
                reason="google_search_command",
            )

        youtube_match = self._YOUTUBE_SEARCH_RE.match(text)
        if youtube_match:
            query = youtube_match.group(1).strip()
            if self.automation_service:
                return self._instant_route(
                    intent="automation",
                    confidence=0.94,
                    safe_to_execute=True,
                    payload={"target": query, "command": text},
                    reason="youtube_search_automation",
                )
            return self._instant_route(
                intent=INTENT_YOUTUBE_SEARCH,
                confidence=0.9,
                safe_to_execute=True,
                payload={"target": query, "intents": [(INTENT_YOUTUBE_SEARCH, {"query": query, "message": text})]},
                reason="youtube_search_command",
            )

        return None

    def _looks_like_mixed(self, lowered: str) -> bool:
        return bool(self._ACTION_RE.search(lowered) and self._QUESTION_RE.search(lowered))

    def _is_sensitive_automation(self, lowered: str) -> bool:
        return bool(self._DESTRUCTIVE_RE.search(lowered) or self._SYSTEM_SENSITIVE_RE.search(lowered))

    def _resolve_open_target(self, target: str) -> str:
        if self.brain_service:
            try:
                return self.brain_service._resolve_open_query(target)
            except Exception:
                pass

        q = (target or "").strip().lower()
        site_map = {
            "youtube": "https://www.youtube.com",
            "google": "https://www.google.com",
            "gmail": "https://mail.google.com",
            "spotify": "https://open.spotify.com",
            "whatsapp": "https://web.whatsapp.com",
        }
        if q in site_map:
            return site_map[q]
        if q.startswith(("http://", "https://")):
            return q
        if "." in q:
            return f"https://{q}"
        return f"https://www.{q}.com"

    def _normalize(self, value: str) -> str:
        value = (value or "").strip().lower()
        value = re.sub(r"\b(?:hey|hello|hi)\s+jarvis\b", " ", value)
        value = value.replace("jarvis", " ")
        value = re.sub(r"\s+", " ", value)
        return value.strip(" .!?")

    def _instant_route(
        self,
        *,
        intent: str,
        confidence: float,
        reason: str,
        payload: Optional[Dict[str, Any]] = None,
        safe_to_execute: bool = False,
        requires_face_auth: bool = False,
        sensitive: bool = False,
    ) -> FastIntentRoute:
        return FastIntentRoute(
            "instant",
            intent=intent,
            confidence=confidence,
            requires_llm=False,
            safe_to_execute=safe_to_execute,
            requires_face_auth=requires_face_auth,
            payload=payload or {},
            sensitive=sensitive,
            reason=reason,
        )

    def _llm_route(self, *, intent: str, reason: str, confidence: float = 0.0) -> FastIntentRoute:
        return FastIntentRoute(
            "llm",
            intent=intent,
            confidence=confidence,
            requires_llm=True,
            safe_to_execute=False,
            requires_face_auth=False,
            reason=reason,
        )
