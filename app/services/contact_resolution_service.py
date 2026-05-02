from __future__ import annotations

from typing import Callable, Iterable

from app.services.contact_match_service import ContactCandidate, ContactMatchService


class ContactResolutionService:
    def __init__(
        self,
        *,
        contacts_provider: Callable[[], Iterable[ContactCandidate]] | None = None,
        contact_match_service: ContactMatchService | None = None,
    ) -> None:
        self.contacts_provider = contacts_provider
        self.contact_match_service = contact_match_service or ContactMatchService()

    def resolve(self, query: str) -> dict:
        contact_query = str(query or "").strip()
        contacts = self._load_contacts()
        ranked = self.contact_match_service.rank_contacts(contact_query, contacts)
        decision = self.contact_match_service.decide(contact_query, ranked)
        return {
            "success": decision.status in {"auto_call", "confirm_contact", "clarify"},
            "action": "contact_resolution",
            "status": decision.status,
            "query": decision.query,
            "message": decision.message,
            "candidates": [candidate.__dict__ for candidate in decision.candidates],
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
