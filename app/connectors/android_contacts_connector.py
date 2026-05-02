from __future__ import annotations

from typing import Any


class AndroidContactsConnector:
    def __init__(self, phone_command_service: Any) -> None:
        self.phone_command_service = phone_command_service

    def list_contacts(self, device_id: str | None = None):
        return self.phone_command_service.list_synced_contacts(device_id=device_id)
