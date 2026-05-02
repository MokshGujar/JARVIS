from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.contracts import PhoneAction
from app.utils.atomic_io import write_json_atomic
from config import DEFAULT_PHONE_DEVICE_ID, PHONE_BRIDGE_DIR


class FilePhoneBridgeRepository:
    def __init__(
        self,
        actions_path: Optional[Path] = None,
        devices_path: Optional[Path] = None,
        ttl_seconds: int = 90,
    ) -> None:
        self.actions_path = actions_path or (PHONE_BRIDGE_DIR / "pending_actions.json")
        self.devices_path = devices_path or (PHONE_BRIDGE_DIR / "devices.json")
        self.ttl_seconds = ttl_seconds

    def note_device_seen(self, device_id: str) -> None:
        device_id = (device_id or "").strip()
        if not device_id:
            return
        devices = self._load_devices()
        devices["last_seen_device_id"] = device_id
        devices["last_seen_at"] = time.time()
        self._save_devices(devices)

    def resolve_device_id(self, explicit_device_id: Optional[str]) -> str:
        if explicit_device_id and explicit_device_id.strip():
            return explicit_device_id.strip()
        if DEFAULT_PHONE_DEVICE_ID:
            return DEFAULT_PHONE_DEVICE_ID
        devices = self._load_devices()
        return str(devices.get("last_seen_device_id", "")).strip()

    def queue_action(self, action: PhoneAction) -> None:
        actions = self._load_actions()
        actions.append(self._to_payload(action))
        self._save_actions(actions)

    def list_pending_actions(self, device_id: str, phone_number: Optional[str] = None) -> List[Dict[str, Any]]:
        self.expire_old_actions()
        device_id = (device_id or "").strip()
        if not device_id:
            return []
        normalized_phone = (phone_number or "").strip()
        matches: List[Dict[str, Any]] = []
        for action in self._load_actions():
            if action.get("status") != "pending":
                continue
            if action.get("device_id") != device_id:
                continue
            action_phone = (action.get("phone_number") or "").strip()
            if action_phone and normalized_phone and action_phone != normalized_phone:
                continue
            matches.append(action)
        return matches

    def acknowledge_action(
        self,
        action_id: str,
        status: str = "completed",
        device_id: Optional[str] = None,
        phone_number: Optional[str] = None,
    ) -> bool:
        updated = False
        actions = self._load_actions()
        for action in actions:
            if action.get("action_id") != action_id:
                continue
            if device_id and action.get("device_id") != device_id:
                continue
            if phone_number and action.get("phone_number") and action.get("phone_number") != phone_number:
                continue
            action["status"] = status
            action["completed_at"] = time.time()
            updated = True
            break
        if updated:
            self._save_actions(actions)
        return updated

    def get_device_status(self) -> Dict[str, Any]:
        devices = self._load_devices()
        return {
            "default_device_id": DEFAULT_PHONE_DEVICE_ID or None,
            "last_seen_device_id": devices.get("last_seen_device_id"),
            "last_seen_at": devices.get("last_seen_at"),
            "has_known_device": bool(self.resolve_device_id(None)),
        }

    def expire_old_actions(self) -> None:
        now = time.time()
        actions = self._load_actions()
        changed = False
        for action in actions:
            if action.get("status") != "pending":
                continue
            created_at = float(action.get("created_at", now))
            if now - created_at > self.ttl_seconds:
                action["status"] = "expired"
                action["completed_at"] = now
                changed = True
        if changed:
            self._save_actions(actions)

    def _load_actions(self) -> List[Dict[str, Any]]:
        if not self.actions_path.exists():
            return []
        try:
            return json.loads(self.actions_path.read_text(encoding="utf-8"))
        except Exception:
            return []

    def _save_actions(self, actions: List[Dict[str, Any]]) -> None:
        write_json_atomic(self.actions_path, actions, indent=2, ensure_ascii=False)

    def _load_devices(self) -> Dict[str, Any]:
        if not self.devices_path.exists():
            return {}
        try:
            return json.loads(self.devices_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_devices(self, devices: Dict[str, Any]) -> None:
        write_json_atomic(self.devices_path, devices, indent=2, ensure_ascii=False)

    def _to_payload(self, action: PhoneAction) -> Dict[str, Any]:
        return {
            "action_id": action.action_id,
            "action_type": action.action_type,
            "status": action.status,
            "device_id": action.device_id,
            "phone_number": action.phone_number,
            "contact_name": action.contact_name,
            "call_method": action.call_method,
            "contact_id": action.contact_id,
            "match_confidence": action.match_confidence,
            "match_reason": action.match_reason,
            "channel": action.channel,
            "message_body": action.message_body,
            "requires_verified_speaker": action.requires_verified_speaker,
            "verification_status": action.verification_status,
            "clarification_candidates": action.clarification_candidates,
            "message": action.message,
            "created_at": action.created_at,
            "completed_at": action.completed_at,
        }

