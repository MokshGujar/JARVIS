import logging
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

import requests

from app.services.groq_service import escape_curly_braces
from app.services.realtime_service import RealtimeGroqService
from config import (
    ABSTRACT_PHONE_API_KEY,
    CALLER_LOOKUP_PROVIDER,
    CALLER_LOOKUP_TIMEOUT_SECONDS,
    NEUTRINO_API_KEY,
    NEUTRINO_USER_ID,
    NUMVERIFY_API_KEY,
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN,
)

logger = logging.getLogger("J.A.R.V.I.S")

CALLER_LOOKUP_ADDENDUM = """
You are handling a phone caller lookup request.

Rules:
- Use only the public search results provided above.
- Do not invent identity details, addresses, emails, or private facts.
- If the number appears to be spam, scam, telemarketing, business, or user-reported, say that clearly.
- If the caller cannot be confidently identified, say that the public web results are inconclusive.
- Keep the answer concise and practical.
- Mention that the result is based on public information only.
"""


@dataclass
class CallerIdentityResult:
    display_name: str = ""
    normalized_number: str = ""
    carrier: str = ""
    line_type: str = ""
    country: str = ""
    location: str = ""
    spam_risk: str = ""
    confidence: float = 0.0
    source: str = "none"

    def compact_metadata(self) -> Dict[str, Any]:
        return {
            key: value
            for key, value in asdict(self).items()
            if value not in ("", None)
        }


class PhoneIdentityProvider:
    source = "none"

    def lookup(self, normalized_number: str) -> Optional[CallerIdentityResult]:
        raise NotImplementedError


class TwilioLookupProvider(PhoneIdentityProvider):
    source = "twilio"

    def __init__(self, timeout: float):
        self.timeout = timeout

    def lookup(self, normalized_number: str) -> Optional[CallerIdentityResult]:
        if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
            return None

        url = f"https://lookups.twilio.com/v2/PhoneNumbers/{normalized_number}"
        response = requests.get(
            url,
            params={"Fields": "caller_name,line_type_intelligence"},
            auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        caller_name = data.get("caller_name") or {}
        line_type = data.get("line_type_intelligence") or {}
        display_name = str(caller_name.get("caller_name") or "").strip()

        return CallerIdentityResult(
            display_name=display_name,
            normalized_number=str(data.get("phone_number") or normalized_number),
            carrier=str(line_type.get("carrier_name") or ""),
            line_type=str(line_type.get("type") or ""),
            country=str(data.get("country_code") or ""),
            spam_risk=str(caller_name.get("caller_type") or ""),
            confidence=0.82 if display_name else 0.62,
            source=self.source,
        )


class AbstractLookupProvider(PhoneIdentityProvider):
    source = "abstract"

    def __init__(self, timeout: float):
        self.timeout = timeout

    def lookup(self, normalized_number: str) -> Optional[CallerIdentityResult]:
        if not ABSTRACT_PHONE_API_KEY:
            return None

        response = requests.get(
            "https://phonevalidation.abstractapi.com/v1/",
            params={"api_key": ABSTRACT_PHONE_API_KEY, "phone": normalized_number},
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        if data.get("valid") is False:
            return CallerIdentityResult(
                normalized_number=normalized_number,
                confidence=0.3,
                source=self.source,
            )

        return CallerIdentityResult(
            normalized_number=str(data.get("format", {}).get("international") or normalized_number),
            carrier=str(data.get("carrier") or ""),
            line_type=str(data.get("type") or ""),
            country=str(data.get("country", {}).get("name") or data.get("country", {}).get("code") or ""),
            location=str(data.get("location") or ""),
            confidence=0.58,
            source=self.source,
        )


class NumverifyLookupProvider(PhoneIdentityProvider):
    source = "numverify"

    def __init__(self, timeout: float):
        self.timeout = timeout

    def lookup(self, normalized_number: str) -> Optional[CallerIdentityResult]:
        if not NUMVERIFY_API_KEY:
            return None

        response = requests.get(
            "http://apilayer.net/api/validate",
            params={"access_key": NUMVERIFY_API_KEY, "number": normalized_number, "format": 1},
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        if data.get("valid") is False:
            return CallerIdentityResult(
                normalized_number=normalized_number,
                confidence=0.3,
                source=self.source,
            )

        return CallerIdentityResult(
            normalized_number=str(data.get("international_format") or normalized_number),
            carrier=str(data.get("carrier") or ""),
            line_type=str(data.get("line_type") or ""),
            country=str(data.get("country_name") or data.get("country_code") or ""),
            location=str(data.get("location") or ""),
            confidence=0.55,
            source=self.source,
        )


class NeutrinoLookupProvider(PhoneIdentityProvider):
    source = "neutrino"

    def __init__(self, timeout: float):
        self.timeout = timeout

    def lookup(self, normalized_number: str) -> Optional[CallerIdentityResult]:
        if not NEUTRINO_USER_ID or not NEUTRINO_API_KEY:
            return None

        response = requests.post(
            "https://neutrinoapi.net/phone-validate",
            data={"number": normalized_number},
            headers={"User-ID": NEUTRINO_USER_ID, "API-Key": NEUTRINO_API_KEY},
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        if data.get("valid") is False:
            return CallerIdentityResult(
                normalized_number=normalized_number,
                confidence=0.3,
                source=self.source,
            )

        return CallerIdentityResult(
            normalized_number=str(data.get("international-number") or normalized_number),
            carrier=str(data.get("carrier") or ""),
            line_type=str(data.get("type") or ""),
            country=str(data.get("country") or data.get("country-code") or ""),
            location=str(data.get("location") or ""),
            confidence=0.55,
            source=self.source,
        )


class CallerLookupService:
    _CACHE_TTL_SECONDS = 7 * 24 * 60 * 60

    def __init__(self, realtime_service: RealtimeGroqService):
        self.realtime_service = realtime_service
        self._cache_lock = threading.Lock()
        self._lookup_cache: Dict[str, Dict[str, Any]] = {}
        self._provider = self._build_provider()

    def _build_provider(self) -> Optional[PhoneIdentityProvider]:
        provider = CALLER_LOOKUP_PROVIDER.strip().lower()
        timeout = max(0.5, min(CALLER_LOOKUP_TIMEOUT_SECONDS, 5.0))
        if provider == "twilio":
            return TwilioLookupProvider(timeout)
        if provider == "abstract":
            return AbstractLookupProvider(timeout)
        if provider == "numverify":
            return NumverifyLookupProvider(timeout)
        if provider == "neutrino":
            return NeutrinoLookupProvider(timeout)
        return None

    def extract_phone_number(self, text: str) -> Optional[str]:
        if not text:
            return None

        match = re.search(r"(?<!\w)(\+?\d[\d\s().-]{5,}\d)", text)
        if not match:
            return None

        return match.group(1).strip()

    def normalize_phone_number(self, phone_number: str) -> str:
        if not phone_number:
            raise ValueError("Phone number is required.")

        cleaned = re.sub(r"[^\d+]", "", phone_number.strip())
        if cleaned.count("+") > 1 or ("+" in cleaned and not cleaned.startswith("+")):
            raise ValueError("Invalid phone number format.")

        digits_only = re.sub(r"\D", "", cleaned)
        if len(digits_only) < 7:
            raise ValueError("Phone number looks too short to search.")

        return f"+{digits_only}" if cleaned.startswith("+") else digits_only

    def looks_like_lookup_request(self, message: str) -> bool:
        lowered = (message or "").lower()
        if not self.extract_phone_number(message):
            return False

        keywords = (
            "caller",
            "calling",
            "who is this number",
            "who called",
            "track",
            "lookup",
            "look up",
            "phone number",
            "spam",
            "unknown number",
        )
        return any(keyword in lowered for keyword in keywords)

    def _build_queries(self, normalized_number: str, caller_name: Optional[str] = None) -> List[str]:
        digits_only = re.sub(r"\D", "", normalized_number)
        queries: List[str] = []

        if normalized_number.startswith("+"):
            queries.append(f"\"{normalized_number}\" caller")

        queries.extend(
            [
                f"\"{digits_only}\" caller",
                f"\"{digits_only}\" phone number",
                f"\"{digits_only}\" spam",
                f"\"{digits_only}\" truecaller",
            ]
        )

        if len(digits_only) >= 10:
            queries.append(f"\"{digits_only[-10:]}\" caller")

        if caller_name:
            queries.append(f"\"{caller_name.strip()}\" \"{digits_only}\"")

        deduped: List[str] = []
        seen = set()
        for query in queries:
            if query not in seen:
                seen.add(query)
                deduped.append(query)
        return deduped[:5]

    def _merge_payloads(self, payloads: List[dict]) -> List[dict]:
        merged: List[dict] = []
        seen_keys = set()

        for payload in payloads:
            for result in payload.get("results", []):
                url = (result.get("url") or "").strip()
                dedupe_key = url or (result.get("title", "") + result.get("content", "")[:120])

                if dedupe_key in seen_keys:
                    continue

                seen_keys.add(dedupe_key)
                merged.append(result)

        return merged[:12]

    def _build_context_block(self, normalized_number: str, queries: List[str], payloads: List[dict]) -> str:
        parts = [f"Phone number searched: {normalized_number}"]

        for idx, query in enumerate(queries, 1):
            parts.append(f"\nQuery {idx}: {query}")
            payload = payloads[idx - 1] if idx - 1 < len(payloads) else None
            if not payload:
                parts.append("No public results returned.")
                continue

            answer = (payload.get("answer") or "").strip()
            if answer:
                parts.append(f"Search summary: {answer}")

            for result_idx, result in enumerate(payload.get("results", [])[:5], 1):
                title = result.get("title", "No title")
                content = (result.get("content") or "").strip()
                url = result.get("url", "")
                score = result.get("score", 0)

                parts.append(f"Source {result_idx}: {title} | score={score}")
                if content:
                    parts.append(f"Snippet: {content}")
                if url:
                    parts.append(f"URL: {url}")

        return escape_curly_braces("\n".join(parts))

    def _summarize(self, question: str, normalized_number: str, queries: List[str], payloads: List[dict]) -> str:
        context_block = self._build_context_block(normalized_number, queries, payloads)

        prompt, messages = self.realtime_service._build_prompt_and_messages(
            question=question,
            chat_history=None,
            extra_system_parts=[context_block],
            mode_addendum=CALLER_LOOKUP_ADDENDUM,
        )

        return self.realtime_service._invoke_llm(
            prompt,
            messages,
            question,
            key_start_index=0,
        )

    def lookup_caller(
        self,
        phone_number: str,
        caller_name: Optional[str] = None,
        original_question: Optional[str] = None,
    ) -> Dict[str, Any]:
        normalized_number = self.normalize_phone_number(phone_number)
        cached = self._get_cached_lookup(normalized_number, caller_name=caller_name)
        if cached:
            logger.info("[CALLER] Cache hit | number=%s", normalized_number)
            return cached

        provider_result = self._lookup_provider(normalized_number)
        provider_display = (provider_result.display_name if provider_result else "").strip()
        effective_caller_name = caller_name or provider_display or None

        queries = self._build_queries(normalized_number, caller_name=effective_caller_name)

        payloads: List[dict] = []
        if not provider_result or provider_result.confidence < 0.78:
            for query in queries:
                _, payload = self.realtime_service.search_tavily(query, num_results=5)
                if payload:
                    payloads.append(payload)

        merged_results = self._merge_payloads(payloads)
        summary_question = (
            original_question
            or f"Identify who may be calling from {normalized_number} using public information."
        )

        if provider_result and provider_result.confidence >= 0.78:
            summary = self._summary_from_provider(provider_result)
        elif payloads:
            summary = self._summarize(summary_question, normalized_number, queries, payloads)
            if provider_result:
                metadata = self._summary_from_provider(provider_result)
                summary = f"{metadata} Public web results add: {summary}"
        elif provider_result:
            summary = self._summary_from_provider(provider_result)
        else:
            summary = (
                f"I could not find reliable public web results for {normalized_number}. "
                "This caller lookup is limited to publicly available information."
            )

        result = {
            "phone_number": phone_number,
            "normalized_number": normalized_number,
            "summary": summary,
            "queries": queries,
            "results": merged_results,
            "public_data_only": provider_result is None,
            "source": provider_result.source if provider_result else "public_web",
            "confidence": provider_result.confidence if provider_result else (0.45 if merged_results else 0.2),
            "display_name": provider_result.display_name if provider_result else "",
            "carrier": provider_result.carrier if provider_result else "",
            "line_type": provider_result.line_type if provider_result else "",
            "country": provider_result.country if provider_result else "",
            "location": provider_result.location if provider_result else "",
            "spam_risk": provider_result.spam_risk if provider_result else "",
        }

        self._set_cached_lookup(normalized_number, result, caller_name=caller_name)

        logger.info(
            "[CALLER] Lookup complete | number=%s | queries=%d | results=%d",
            normalized_number,
            len(queries),
            len(merged_results),
        )

        return result

    def _lookup_provider(self, normalized_number: str) -> Optional[CallerIdentityResult]:
        if not self._provider:
            return None
        try:
            result = self._provider.lookup(normalized_number)
            if result:
                logger.info("[CALLER] Provider hit | source=%s | number=%s | confidence=%.2f", result.source, normalized_number, result.confidence)
            return result
        except Exception as exc:
            logger.warning("[CALLER] Provider lookup failed | source=%s | number=%s | error=%s", self._provider.source, normalized_number, exc)
            return None

    def _summary_from_provider(self, result: CallerIdentityResult) -> str:
        subject = result.display_name.strip() or result.normalized_number or "this number"
        parts = [f"{subject} was identified by {result.source}"]
        details = []
        if result.line_type:
            details.append(result.line_type)
        if result.carrier:
            details.append(result.carrier)
        if result.location:
            details.append(result.location)
        if result.country:
            details.append(result.country)
        if details:
            parts.append(f"with metadata: {', '.join(details)}")
        if result.spam_risk:
            parts.append(f"Risk/category: {result.spam_risk}")
        parts.append(f"Confidence: {round(result.confidence * 100)}%.")
        return ". ".join(parts)

    def build_incoming_call_payload(
        self,
        phone_number: str,
        caller_name_hint: Optional[str] = None,
        speak_result: bool = True,
        call_direction: str = "incoming",
    ) -> Dict[str, Any]:
        direction = "outgoing" if (call_direction or "").strip().lower() == "outgoing" else "incoming"
        result = self.lookup_caller(
            phone_number=phone_number,
            caller_name=caller_name_hint,
            original_question=(
                f"Identify the {direction} caller at {phone_number} using public information."
            ),
        )

        summary = (result.get("summary") or "").strip()
        normalized_number = result["normalized_number"]
        results = result.get("results", [])
        direction_label = "Outgoing call" if direction == "outgoing" else "Incoming call"

        if caller_name_hint and caller_name_hint.strip():
            title = f"{direction_label}: {caller_name_hint.strip()}"
            body_prefix = (
                f"Calling {normalized_number}."
                if direction == "outgoing"
                else f"Calling from {normalized_number}."
            )
            body = f"{body_prefix} {summary}".strip()
        else:
            title = f"{direction_label}: {normalized_number}"
            body = summary

        if len(body) > 180:
            body = body[:177].rstrip() + "..."

        speak_text = summary if speak_result else ""

        return {
            "event_id": str(uuid.uuid4()),
            "phone_number": phone_number,
            "normalized_number": normalized_number,
            "summary": summary,
            "call_direction": direction,
            "notification_title": title,
            "notification_body": body,
            "speak_text": speak_text,
            "public_data_only": result.get("public_data_only", True),
            "results": results,
            "source": result.get("source", "public_web"),
            "confidence": result.get("confidence", 0.0),
            "display_name": result.get("display_name", ""),
            "carrier": result.get("carrier", ""),
            "line_type": result.get("line_type", ""),
            "country": result.get("country", ""),
            "location": result.get("location", ""),
            "spam_risk": result.get("spam_risk", ""),
        }

    def _cache_key(self, normalized_number: str, caller_name: Optional[str] = None) -> str:
        safe_name = (caller_name or "").strip().lower()
        return f"{normalized_number}|{safe_name}"

    def _get_cached_lookup(self, normalized_number: str, caller_name: Optional[str] = None) -> Optional[Dict[str, Any]]:
        now = time.time()
        key = self._cache_key(normalized_number, caller_name=caller_name)

        with self._cache_lock:
            expired = [
                cache_key for cache_key, item in self._lookup_cache.items()
                if now - float(item.get("cached_at", 0)) > self._CACHE_TTL_SECONDS
            ]
            for cache_key in expired:
                self._lookup_cache.pop(cache_key, None)

            cached = self._lookup_cache.get(key)
            if not cached:
                return None

            result = dict(cached.get("result", {}))
            if not result:
                return None

            return result

    def _set_cached_lookup(
        self,
        normalized_number: str,
        result: Dict[str, Any],
        caller_name: Optional[str] = None,
    ) -> None:
        key = self._cache_key(normalized_number, caller_name=caller_name)
        with self._cache_lock:
            self._lookup_cache[key] = {
                "cached_at": time.time(),
                "result": dict(result),
            }
