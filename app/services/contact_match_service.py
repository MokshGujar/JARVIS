from __future__ import annotations

import difflib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from config import PHONE_BRIDGE_DIR


@dataclass
class ContactCandidate:
    contact_id: str = ""
    display_name: str = ""
    phone_number: str = ""
    aliases: List[str] = field(default_factory=list)
    favorite: bool = False
    recent: bool = False
    frequent: bool = False
    score: float = 0.0
    reason: str = ""


@dataclass
class ParsedCallIntent:
    contact_name: str
    call_method: str = ""


@dataclass
class MatchDecision:
    status: str
    query: str
    candidates: List[ContactCandidate]
    message: str = ""


class ContactMatchService:
    HIGH_CONFIDENCE = 0.88
    MEDIUM_CONFIDENCE = 0.65
    MIN_AUTO_CALL_QUERY_LEN = 4
    MIN_AUTO_CALL_GAP = 0.08
    PHONE_BACKED_CLOSE_GAP = 0.03

    _CALL_FILLERS = {
        "please",
        "pls",
        "bro",
        "sir",
        "now",
        "quickly",
        "the",
        "my",
        "to",
    }

    _ALIASES = {
        "mom": ["mother", "maa", "mummy", "mumma"],
        "dad": ["father", "papa", "daddy"],
        "bro": ["brother", "bhai"],
        "sis": ["sister", "didi"],
    }

    def __init__(self) -> None:
        self._pending_clarifications: Dict[str, Dict[str, Any]] = {}
        self._aliases_path = PHONE_BRIDGE_DIR / "contact_aliases.json"
        self._external_aliases: Dict[str, List[str]] = {}
        self._aliases_loaded_at = 0.0

    def normalize_command_text(self, message: str) -> str:
        text = (message or "").strip().lower()
        text = re.sub(r"\b(jarvis|hey jarvis|hello jarvis)\b", " ", text)
        text = re.sub(r"[^a-z0-9+\s]", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def parse_call_intent(self, message: str) -> Optional[ParsedCallIntent]:
        text = self.normalize_command_text(message)
        if not text:
            return None

        method = ""
        if re.search(r"\b(whatsapp|wa)\b", text):
            method = "whatsapp"
            text = re.sub(r"\b(whatsapp|wa)\b", " ", text)
        elif re.search(r"\b(normal|normally|regular|phone)\b", text):
            method = "normal"

        patterns = (
            r"^(?:call|dial|phone)\s+(.+?)$",
            r"^(.+?)\s+(?:ko\s+)?(?:call|dial|phone)\s*(?:karo|kar do|please)?$",
            r"^(?:call|dial|phone)\s+(?:to\s+)?(.+?)\s+(?:on|via|through|using)\s+.+$",
        )
        contact_name = ""
        for pattern in patterns:
            match = re.match(pattern, text.strip())
            if match:
                contact_name = match.group(1)
                break

        if not contact_name:
            return None

        contact_name = re.sub(r"\b(call|dial|phone|on|via|through|using|normal|normally|regular)\b", " ", contact_name)
        contact_name = " ".join(
            token
            for token in contact_name.split()
            if token not in self._CALL_FILLERS
        ).strip()
        if not contact_name:
            return None

        return ParsedCallIntent(contact_name=contact_name, call_method=method)

    def rank_contacts(self, query: str, contacts: Iterable[ContactCandidate]) -> List[ContactCandidate]:
        normalized_query = self._normalize_name(query)
        normalized_query_sorted = self._token_sort(normalized_query)
        ranked: List[ContactCandidate] = []
        for contact in contacts:
            names = [contact.display_name, *contact.aliases, *self._aliases_for(contact.display_name)]
            best_score = 0.0
            best_reason = ""
            for name in names:
                score, reason = self._score_name(normalized_query, self._normalize_name(name), normalized_query_sorted)
                if score > best_score:
                    best_score = score
                    best_reason = reason

            if best_score <= 0:
                continue

            boost = 0.0
            boost_reasons = []
            if contact.favorite:
                boost += 0.03
                boost_reasons.append("favorite")
            if contact.frequent:
                boost += 0.04
                boost_reasons.append("frequent")
            if contact.recent:
                boost += 0.04
                boost_reasons.append("recent")
            if contact.phone_number and best_reason != "exact":
                boost += 0.02
                boost_reasons.append("phone")

            item = ContactCandidate(**{**contact.__dict__})
            item.score = min(1.0, best_score + boost)
            item.reason = "+".join([best_reason, *boost_reasons]).strip("+")
            ranked.append(item)

        return sorted(
            ranked,
            key=lambda item: (
                item.score,
                bool(item.phone_number),
                item.favorite,
                item.frequent,
                item.recent,
                item.display_name.lower(),
            ),
            reverse=True,
        )

    def decide(self, query: str, candidates: List[ContactCandidate]) -> MatchDecision:
        if not candidates:
            return MatchDecision("not_found", query, [], f"I couldn't find {query} in your contacts.")

        top = candidates[0]
        second = candidates[1] if len(candidates) > 1 else None
        gap = top.score - second.score if second else 1.0
        short_query = len(self._normalize_name(query).replace(" ", "")) <= 3

        exact_top = self._candidate_reason(top) == "exact"
        if top.score >= self.HIGH_CONFIDENCE and exact_top and gap >= self.MIN_AUTO_CALL_GAP:
            return MatchDecision("auto_call", query, [top])

        if top.score >= self.HIGH_CONFIDENCE and not short_query and gap >= self.MIN_AUTO_CALL_GAP:
            return MatchDecision("confirm_contact", query, [top], f"I found {top.display_name}. Did you mean {top.display_name}?")

        if top.score >= self.MEDIUM_CONFIDENCE:
            return MatchDecision("clarify", query, candidates[:3], self._build_clarification(candidates[:3]))

        return MatchDecision("not_found", query, candidates[:3], f"I couldn't confidently match {query}.")

    def save_clarification(self, key: str, candidates: List[ContactCandidate], call_method: str = "", ttl_seconds: int = 20) -> None:
        self._pending_clarifications[key] = {
            "candidates": candidates,
            "call_method": call_method,
            "expires_at": time.time() + ttl_seconds,
            "failed": False,
        }

    def resolve_clarification(self, key: str, reply: str) -> Optional[ContactCandidate]:
        pending = self._pending_clarifications.get(key)
        if not pending or time.time() > float(pending.get("expires_at", 0)):
            self._pending_clarifications.pop(key, None)
            return None

        text = self.normalize_command_text(reply)
        if text in {"cancel", "stop", "never mind", "no"}:
            self._pending_clarifications.pop(key, None)
            return None

        candidates: List[ContactCandidate] = pending.get("candidates", [])
        ordinal = {
            "first": 0,
            "first one": 0,
            "one": 0,
            "1": 0,
            "second": 1,
            "second one": 1,
            "two": 1,
            "2": 1,
            "third": 2,
            "third one": 2,
            "three": 2,
            "3": 2,
            "last": len(candidates) - 1,
            "last one": len(candidates) - 1,
        }.get(text)
        if ordinal is not None and 0 <= ordinal < len(candidates):
            self._pending_clarifications.pop(key, None)
            return candidates[ordinal]

        ranked = self.rank_contacts(text, candidates)
        if ranked and ranked[0].score >= self.MEDIUM_CONFIDENCE:
            self._pending_clarifications.pop(key, None)
            return ranked[0]

        if pending.get("failed"):
            self._pending_clarifications.pop(key, None)
        else:
            pending["failed"] = True
        return None

    def _score_name(self, query: str, name: str, query_sorted: str | None = None) -> tuple[float, str]:
        if not query or not name:
            return 0.0, ""
        if query == name:
            return 1.0, "exact"
        if self._token_sort(query) == self._token_sort(name):
            return 0.99, "exact"
        alias_score = self._alias_score(query, name)
        if alias_score:
            return alias_score, "alias"
        if name.startswith(query):
            return (0.94 if len(query) >= 4 else 0.72), "prefix"
        if query.startswith(name) and len(name) >= 4:
            return 0.82, "reverse_prefix"
        fuzzy = difflib.SequenceMatcher(None, query, name).ratio()
        edit = self._edit_similarity(query, name)
        token_sort = difflib.SequenceMatcher(None, query_sorted or self._token_sort(query), self._token_sort(name)).ratio()
        token_set = self._token_set_ratio(query, name)
        fuzzy_score = max(fuzzy, edit, token_sort, token_set)
        phonetic = 0.9 if self._phonetic_key(query) == self._phonetic_key(name) else 0.0
        if phonetic >= fuzzy_score and phonetic:
            return phonetic, "phonetic"
        if fuzzy_score:
            return fuzzy_score, "fuzzy"
        return 0.0, ""

    def _alias_score(self, query: str, name: str) -> float:
        alias_groups = {**self._ALIASES, **self._load_external_aliases()}
        for canonical, aliases in alias_groups.items():
            family = {canonical, *aliases}
            if query in family and name in family:
                return 0.92
        return 0.0

    def _aliases_for(self, display_name: str) -> List[str]:
        normalized = self._normalize_name(display_name)
        aliases = self._load_external_aliases()
        if normalized in aliases:
            return aliases[normalized]
        for canonical, family in aliases.items():
            if normalized in family:
                return [canonical, *family]
        return []

    def _load_external_aliases(self) -> Dict[str, List[str]]:
        now = time.time()
        if now - self._aliases_loaded_at < 5:
            return self._external_aliases
        self._aliases_loaded_at = now
        if not self._aliases_path.exists():
            self._external_aliases = {}
            return self._external_aliases
        try:
            raw = json.loads(self._aliases_path.read_text(encoding="utf-8"))
            aliases: Dict[str, List[str]] = {}
            if isinstance(raw, dict):
                for key, values in raw.items():
                    normalized_key = self._normalize_name(str(key))
                    if not normalized_key:
                        continue
                    if isinstance(values, str):
                        values = [values]
                    aliases[normalized_key] = [
                        self._normalize_name(str(value))
                        for value in values
                        if self._normalize_name(str(value))
                    ]
            self._external_aliases = aliases
        except Exception:
            self._external_aliases = {}
        return self._external_aliases

    def _normalize_name(self, value: str) -> str:
        return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", (value or "").lower())).strip()

    def _candidate_reason(self, candidate: ContactCandidate) -> str:
        return (candidate.reason or "").split("+", 1)[0].strip()

    def _token_sort(self, value: str) -> str:
        tokens = [token for token in self._normalize_name(value).split() if token]
        return " ".join(sorted(tokens))

    def _token_set_ratio(self, query: str, name: str) -> float:
        query_tokens = set(self._normalize_name(query).split())
        name_tokens = set(self._normalize_name(name).split())
        if not query_tokens or not name_tokens:
            return 0.0
        intersection = query_tokens & name_tokens
        if not intersection:
            return 0.0
        if query_tokens <= name_tokens or name_tokens <= query_tokens:
            return 0.93
        overlap = (2 * len(intersection)) / (len(query_tokens) + len(name_tokens))
        return min(0.92, overlap)

    def _edit_similarity(self, a: str, b: str) -> float:
        if a == b:
            return 1.0
        if not a or not b:
            return 0.0
        previous = list(range(len(b) + 1))
        for i, char_a in enumerate(a, start=1):
            current = [i]
            for j, char_b in enumerate(b, start=1):
                cost = 0 if char_a == char_b else 1
                current.append(min(
                    current[j - 1] + 1,
                    previous[j] + 1,
                    previous[j - 1] + cost,
                ))
            previous = current
        distance = previous[-1]
        width = max(len(a), len(b), 1)
        return max(0.0, 1.0 - (distance / width))

    def _phonetic_key(self, value: str) -> str:
        text = self._normalize_name(value).replace(" ", "")
        text = re.sub(r"(sh|ch|ck|kh)", "k", text)
        text = re.sub(r"[aeiou]+", "", text)
        text = re.sub(r"(.)\1+", r"\1", text)
        return text[:8]

    def _build_clarification(self, candidates: List[ContactCandidate]) -> str:
        names = [candidate.display_name for candidate in candidates if candidate.display_name]
        if not names:
            return "Which contact did you mean?"
        if len(names) == 1:
            return f"Did you mean {names[0]}?"
        return f"Did you mean {', '.join(names[:-1])}, or {names[-1]}?"
