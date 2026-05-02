from __future__ import annotations


class ContactAgent:
    def __init__(self, contact_resolution_service) -> None:
        self.contact_resolution_service = contact_resolution_service

    def resolve(self, query: str):
        return self.contact_resolution_service.resolve(query)
