from __future__ import annotations

import random
import re
from collections import deque


class DynamicPhraseGenerator:
    def __init__(self, phrases=None, avoid_last: int = 3) -> None:
        self.phrases = list(
            phrases
            or (
                "One moment...",
                "Just a second...",
                "Let me check...",
                "I'm on it...",
                "Hang on...",
            )
        )
        self.recent = deque(maxlen=max(1, avoid_last))

    def next_phrase(self) -> str:
        choices = [phrase for phrase in self.phrases if phrase not in self.recent]
        if not choices:
            choices = self.phrases[:]
        phrase = random.choice(choices)
        self.recent.append(phrase)
        return phrase


class AcknowledgementService:
    def __init__(self, phrase_generator: DynamicPhraseGenerator | None = None) -> None:
        self.phrase_generator = phrase_generator or DynamicPhraseGenerator()

    def build_ack(self, route, *, message: str = "") -> str:
        intent = getattr(route, "intent", "") or ""
        payload = getattr(route, "payload", {}) or {}
        target = str(payload.get("target") or "").strip()
        phone_intent = str(payload.get("phone_intent") or "").strip()

        if intent == "phone":
            target = target or self._extract_phone_target(message, phone_intent)
            if phone_intent == "message":
                return f"Drafting a message to {target}..." if target else "Drafting that..."
            if target:
                return f"Calling {target}..."
            return "Sending that to your phone..."

        if intent == "open":
            return f"Opening {target}..." if target else "Opening that..."

        if intent == "play":
            return f"Playing {target}..." if target else "Playing that..."

        if intent in {"google search", "youtube search"}:
            return "Searching..."

        if intent == "automation":
            return "On it..."

        if intent == "reminder":
            return "Setting that up..."

        if intent == "wake_on_lan":
            return "Waking it up..."

        return self.phrase_generator.next_phrase()

    def _extract_phone_target(self, message: str, phone_intent: str) -> str:
        text = (message or "").strip()
        if not text:
            return ""

        if phone_intent == "message":
            patterns = (
                r"^(?:send\s+)?(?:a\s+)?(?:message|text|sms|whatsapp)\s+(?:to\s+)?(?P<target>.+?)(?:\s+(?:saying|that says|saying that|about)\b.*)?$",
            )
        else:
            patterns = (
                r"^(?:call|dial|phone)\s+(?P<target>.+?)(?:\s+(?:on|via)\s+whatsapp)?$",
                r"^(?:whatsapp\s+call|call\s+on\s+whatsapp)\s+(?P<target>.+)$",
            )

        for pattern in patterns:
            match = re.match(pattern, text, flags=re.IGNORECASE)
            if match:
                return match.group("target").strip(" .!?")

        return ""
