from __future__ import annotations

import hashlib
import logging
from typing import Callable, Iterable

from app.services.contact_match_service import ContactCandidate, ContactMatchService

logger = logging.getLogger("J.A.R.V.I.S")


class ContactResolutionService:
    def __init__(
        self,
        *,
        contacts_provider: Callable[[], Iterable[ContactCandidate]] | None = None,
        contact_match_service: ContactMatchService | None = None,
    ) -> None:
        self.contacts_provider = contacts_provider
        self.contact_match_service = contact_match_service or ContactMatchService()

    def resolve(self, query: str, *, source: str = "contact", required_channel: str = "") -> dict:
        contact_query = str(query or "").strip()
        contacts = self._load_contacts()
        ranked = self.contact_match_service.rank_contacts(contact_query, contacts)
        decision = self.contact_match_service.decide(contact_query, ranked)
        status = self._canonical_status(decision.status)
        selected = decision.candidates[0] if status == "matched" and decision.candidates else None
        missing_channels: list[str] = []
        if selected is not None and required_channel:
            if required_channel in {"whatsapp", "phone", "sms"} and not selected.phone_number:
                missing_channels.append("phone")
            if required_channel in {"gmail", "email"} and not selected.email_address:
                missing_channels.append("email")
            if missing_channels:
                status = "missing_channel"
        candidate_payloads = [self._candidate_payload(candidate) for candidate in decision.candidates]
        logger.info(
            "[CONTACT_RESOLVE] source=%s status=%s candidate_count=%d contact_hash=%s",
            source,
            status,
            len(candidate_payloads),
            self._contact_hash(selected.display_name if selected else contact_query),
        )
        if selected is not None and status == "matched":
            logger.info(
                "[CONTACT_SELECTED] source=%s contact_hash=%s confidence=%.2f",
                source,
                self._contact_hash(selected.display_name),
                float(selected.score or 0.0),
            )
        return {
            "success": status == "matched",
            "action": "contact_resolution",
            "status": status,
            "match_status": decision.status,
            "query": decision.query,
            "message": decision.message,
            "selected_contact": self._candidate_payload(selected) if selected is not None else None,
            "candidates": candidate_payloads,
            "candidate_count": len(candidate_payloads),
            "missing_channels": missing_channels,
            "contact_hash": self._contact_hash(selected.display_name if selected else contact_query),
        }

    def _load_contacts(self) -> list[ContactCandidate]:
        if not self.contacts_provider:
            return []
        try:
            raw_contacts = list(self.contacts_provider() or [])
        except Exception:
            return []
        contacts: list[ContactCandidate] = []
        for item in raw_contacts:
            if isinstance(item, ContactCandidate):
                contacts.append(item)
            elif isinstance(item, dict):
                contacts.append(ContactCandidate(**item))
        return contacts

    @staticmethod
    def _canonical_status(status: str) -> str:
        if status == "auto_call":
            return "matched"
        if status == "confirm_contact":
            return "weak_match"
        if status == "clarify":
            return "ambiguous"
        return "not_found"

    @staticmethod
    def _candidate_payload(candidate: ContactCandidate | None) -> dict:
        if candidate is None:
            return {}
        return {
            "contact_id": candidate.contact_id,
            "display_name": candidate.display_name,
            "phone_number": candidate.phone_number,
            "email_address": candidate.email_address,
            "aliases": list(candidate.aliases),
            "favorite": candidate.favorite,
            "recent": candidate.recent,
            "frequent": candidate.frequent,
            "score": candidate.score,
            "reason": candidate.reason,
        }

    @staticmethod
    def _contact_hash(value: str) -> str:
        normalized = " ".join(str(value or "").strip().lower().split())
        if not normalized:
            return ""
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
