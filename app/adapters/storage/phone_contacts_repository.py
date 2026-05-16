from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.services.contact_match_service import ContactCandidate
from app.utils.atomic_io import write_json_atomic
from config import PHONE_BRIDGE_DIR


class FilePhoneContactsRepository:
    def __init__(self, contacts_path: Optional[Path] = None) -> None:
        self.contacts_path = contacts_path or (PHONE_BRIDGE_DIR / "contacts_snapshot.json")

    def sync_contacts(self, device_id: str, contacts: List[Dict[str, Any]]) -> int:
        device_id = (device_id or "").strip()
        normalized_contacts = self._normalize_contacts(contacts)
        payload = self._load_snapshot()
        devices = dict(payload.get("devices") or {})
        devices[device_id or "default"] = {
            "device_id": device_id,
            "contacts": normalized_contacts,
            "synced_at": time.time(),
        }
        write_json_atomic(self.contacts_path, {"devices": devices}, indent=2, ensure_ascii=False)
        return len(normalized_contacts)

    def list_contacts(self, device_id: Optional[str] = None) -> List[ContactCandidate]:
        payload = self._load_snapshot()
        devices = dict(payload.get("devices") or {})
        selected: Dict[str, Any] | None = None
        if device_id and device_id in devices:
            selected = devices[device_id]
        elif devices:
            selected = max(devices.values(), key=lambda item: float(item.get("synced_at", 0.0)))
        if not selected:
            return []

        contacts: List[ContactCandidate] = []
        for raw in selected.get("contacts") or []:
            if not isinstance(raw, dict):
                continue
            contacts.append(
                ContactCandidate(
                    contact_id=str(raw.get("contact_id") or ""),
                    display_name=str(raw.get("display_name") or ""),
                    phone_number=str(raw.get("phone_number") or ""),
                    email_address=str(raw.get("email_address") or ""),
                    aliases=list(raw.get("aliases") or []),
                    favorite=bool(raw.get("favorite", False)),
                    recent=bool(raw.get("recent", False)),
                    frequent=bool(raw.get("frequent", False)),
                )
            )
        return contacts

    def _load_snapshot(self) -> Dict[str, Any]:
        if not self.contacts_path.exists():
            return {"devices": {}}
        try:
            raw = json.loads(self.contacts_path.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {"devices": {}}
        except Exception:
            return {"devices": {}}

    @staticmethod
    def _normalize_contacts(contacts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        normalized_contacts: List[Dict[str, Any]] = []
        seen = set()
        for raw in contacts or []:
            if not isinstance(raw, dict):
                continue
            display_name = str(raw.get("display_name") or raw.get("displayName") or "").strip()
            phone_number = str(raw.get("phone_number") or raw.get("phoneNumber") or "").strip()
            email_address = str(raw.get("email_address") or raw.get("emailAddress") or raw.get("email") or "").strip()
            contact_id = str(raw.get("contact_id") or raw.get("contactId") or "").strip()
            if not display_name and not phone_number and not email_address:
                continue
            key = (contact_id or phone_number or email_address or display_name).lower()
            if key in seen:
                continue
            seen.add(key)
            aliases = raw.get("aliases") or []
            if not isinstance(aliases, list):
                aliases = []
            normalized_contacts.append(
                {
                    "contact_id": contact_id,
                    "display_name": display_name or phone_number,
                    "phone_number": phone_number,
                    "email_address": email_address,
                    "aliases": [str(alias).strip() for alias in aliases if str(alias).strip()],
                    "favorite": bool(raw.get("favorite", False)),
                    "recent": bool(raw.get("recent", False)),
                    "frequent": bool(raw.get("frequent", False)),
                }
            )
        return normalized_contacts
