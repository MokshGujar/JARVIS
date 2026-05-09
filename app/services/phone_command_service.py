from __future__ import annotations

import logging
import json
import re
import time
import uuid
from typing import Any, Dict, List, Optional

from app.adapters.storage.phone_bridge_repository import FilePhoneBridgeRepository
from app.core.contracts import PhoneAction
from app.services.contact_resolution_service import ContactResolutionService
from app.services.contact_match_service import ContactCandidate
from app.services.contact_match_service import ContactMatchService
from app.utils.atomic_io import write_json_atomic
from config import PHONE_BRIDGE_DIR

logger = logging.getLogger("J.A.R.V.I.S")


class PhoneCommandService:
    def __init__(self, repository: Optional[FilePhoneBridgeRepository] = None):
        self._repository = repository or FilePhoneBridgeRepository(
            actions_path=PHONE_BRIDGE_DIR / "pending_actions.json",
            devices_path=PHONE_BRIDGE_DIR / "devices.json",
            ttl_seconds=90,
        )
        self._contacts_path = PHONE_BRIDGE_DIR / "contacts_snapshot.json"
        self._pending_call_choice: Dict[str, Any] | None = None
        self._pending_message_choice: Dict[str, Any] | None = None
        self._contact_match_service = ContactMatchService()

    @property
    def _actions_path(self):
        return self._repository.actions_path

    @_actions_path.setter
    def _actions_path(self, value):
        self._repository.actions_path = value

    @property
    def _devices_path(self):
        return self._repository.devices_path

    @_devices_path.setter
    def _devices_path(self, value):
        self._repository.devices_path = value

    @property
    def _contacts_snapshot_path(self):
        return self._contacts_path

    @_contacts_snapshot_path.setter
    def _contacts_snapshot_path(self, value):
        self._contacts_path = value

    def note_device_seen(self, device_id: str) -> None:
        self._repository.note_device_seen(device_id)

    def sync_contacts(self, device_id: str, contacts: List[Dict[str, Any]]) -> Dict[str, Any]:
        device_id = (device_id or "").strip()
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
            normalized_contacts.append({
                "contact_id": contact_id,
                "display_name": display_name or phone_number,
                "phone_number": phone_number,
                "email_address": email_address,
                "aliases": [str(alias).strip() for alias in aliases if str(alias).strip()],
                "favorite": bool(raw.get("favorite", False)),
                "recent": bool(raw.get("recent", False)),
                "frequent": bool(raw.get("frequent", False)),
            })

        payload = self._load_contacts_snapshot()
        devices = dict(payload.get("devices") or {})
        devices[device_id or "default"] = {
            "device_id": device_id,
            "contacts": normalized_contacts,
            "synced_at": time.time(),
        }
        write_json_atomic(self._contacts_path, {"devices": devices}, indent=2, ensure_ascii=False)
        if device_id:
            self.note_device_seen(device_id)
        return {"success": True, "action": "sync_contacts", "count": len(normalized_contacts)}

    def list_synced_contacts(self, device_id: Optional[str] = None) -> List[ContactCandidate]:
        payload = self._load_contacts_snapshot()
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
            contacts.append(ContactCandidate(
                contact_id=str(raw.get("contact_id") or ""),
                display_name=str(raw.get("display_name") or ""),
                phone_number=str(raw.get("phone_number") or ""),
                email_address=str(raw.get("email_address") or ""),
                aliases=list(raw.get("aliases") or []),
                favorite=bool(raw.get("favorite", False)),
                recent=bool(raw.get("recent", False)),
                frequent=bool(raw.get("frequent", False)),
            ))
        return contacts

    def _load_contacts_snapshot(self) -> Dict[str, Any]:
        if not self._contacts_path.exists():
            return {"devices": {}}
        try:
            raw = json.loads(self._contacts_path.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {"devices": {}}
        except Exception:
            return {"devices": {}}

    def looks_like_answer_request(self, message: str) -> bool:
        text = self._normalize_command_text(message)
        phrases = (
            "answer",
            "answer it",
            "answer now",
            "answer the call",
            "answer the phone",
            "answer my phone",
            "pick up",
            "pick it up",
            "pick up the call",
            "pick up the phone",
            "pick up my phone",
            "take the call",
            "take it",
            "accept the call",
            "accept it",
        )
        return any(phrase in text for phrase in phrases)

    def looks_like_reject_request(self, message: str) -> bool:
        text = self._normalize_command_text(message)
        phrases = (
            "reject",
            "reject it",
            "decline",
            "decline it",
            "decline the call",
            "decline the phone",
            "reject the call",
            "reject the phone",
            "cut it",
            "cut the call",
            "hang up",
            "hang up the call",
            "hang up the phone",
            "disconnect the call",
            "ignore the call",
            "ignore it",
        )
        return any(phrase in text for phrase in phrases)

    def looks_like_place_call_request(self, message: str) -> bool:
        text = self._normalize_command_text(message)
        return bool(
            text.startswith(("call ", "dial ", "phone "))
            or text.startswith("whatsapp call ")
            or text.startswith("call on whatsapp ")
        )

    def looks_like_message_request(self, message: str) -> bool:
        text = self._normalize_command_text(message)
        return bool(
            text.startswith(("message ", "text ", "sms ", "whatsapp "))
            or text.startswith("send message ")
            or text.startswith("send sms ")
            or text.startswith("send whatsapp ")
        )

    def looks_like_call_method_followup(self, message: str) -> bool:
        text = self._normalize_command_text(message)
        return text in {
            "normal",
            "normally",
            "phone",
            "phone call",
            "regular",
            "regular call",
            "default",
            "default one",
            "whatsapp",
            "whatsapp call",
            "wa",
        }

    def looks_like_message_channel_followup(self, message: str) -> bool:
        text = self._normalize_command_text(message)
        return text in {
            "sms",
            "text",
            "text message",
            "message",
            "whatsapp",
            "wa",
        }

    def handle_place_call_request(
        self,
        message: str,
        device_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        parsed_intent = self._contact_match_service.parse_call_intent(message)
        parsed = (
            {
                "contact_name": parsed_intent.contact_name,
                "call_method": parsed_intent.call_method,
            }
            if parsed_intent
            else self._parse_place_call_request(message)
        )
        if not parsed:
            return {
                "success": False,
                "action": "place_call",
                "message": "Tell me who you want to call, like 'call mom' or 'call mom on WhatsApp'.",
            }

        contact_name = parsed["contact_name"]
        call_method = parsed.get("call_method")
        if not contact_name:
            return {
                "success": False,
                "action": "place_call",
                "message": "Tell me which contact you want to call.",
            }

        if not call_method:
            self._pending_call_choice = {
                "contact_name": contact_name,
                "device_id": device_id,
                "created_at": time.time(),
            }
            return {
                "success": False,
                "action": "place_call",
                "message": f"Should I call {contact_name} normally or on WhatsApp?",
            }

        self._pending_call_choice = None
        return self.queue_place_call(
            contact_name=contact_name,
            call_method=call_method,
            device_id=device_id,
        )

    def handle_call_method_followup(self, message: str) -> Optional[Dict[str, Any]]:
        text = self._normalize_command_text(message)
        if not self._pending_call_choice:
            return None

        if time.time() - float(self._pending_call_choice.get("created_at", 0)) > 60:
            self._pending_call_choice = None
            return None

        method = None
        if "whatsapp" in text or text == "wa":
            method = "whatsapp"
        elif "normal" in text or "phone" in text or "regular" in text or "default" in text:
            method = "normal"

        if not method:
            return None

        pending = dict(self._pending_call_choice)
        self._pending_call_choice = None
        return self.queue_place_call(
            contact_name=str(pending.get("contact_name", "")),
            call_method=method,
            device_id=pending.get("device_id"),
        )

    def handle_message_channel_followup(self, message: str) -> Optional[Dict[str, Any]]:
        text = self._normalize_command_text(message)
        if not self._pending_message_choice:
            return None

        if time.time() - float(self._pending_message_choice.get("created_at", 0)) > 60:
            self._pending_message_choice = None
            return None

        channel = None
        if "whatsapp" in text or text == "wa":
            channel = "whatsapp"
        elif text in {"sms", "text", "text message", "message"}:
            channel = "sms"

        if not channel:
            return None

        pending = dict(self._pending_message_choice)
        self._pending_message_choice = None
        return self.queue_draft_message(
            contact_name=str(pending.get("contact_name", "")),
            message_body=str(pending.get("message_body", "")),
            channel=channel,
            device_id=pending.get("device_id"),
        )

    def handle_message_request(
        self,
        message: str,
        device_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        parsed = self._parse_message_request(message)
        if not parsed:
            return {
                "success": False,
                "action": "draft_message",
                "message": "Tell me who to message and what to say, like 'WhatsApp mom I am leaving now'.",
            }

        contact_name = parsed.get("contact_name", "").strip()
        message_body = parsed.get("message_body", "").strip()
        channel = parsed.get("channel", "").strip()

        if not contact_name:
            return {
                "success": False,
                "action": "draft_message",
                "message": "Tell me which contact to message.",
            }
        if not message_body:
            return {
                "success": False,
                "action": "draft_message",
                "message": f"What should I say to {contact_name}?",
            }

        if not channel:
            self._pending_message_choice = {
                "contact_name": contact_name,
                "message_body": message_body,
                "device_id": device_id,
                "created_at": time.time(),
            }
            return {
                "success": False,
                "action": "draft_message",
                "message": f"Should I draft that to {contact_name} on SMS or WhatsApp?",
            }

        return self.queue_draft_message(
            contact_name=contact_name,
            message_body=message_body,
            channel=channel,
            device_id=device_id,
        )

    def route_phone_request(
        self,
        message: str,
        device_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        if self.looks_like_answer_request(message):
            return self.queue_answer_call(device_id=device_id)
        if self.looks_like_reject_request(message):
            return self.queue_reject_call(device_id=device_id)

        followup = self.handle_call_method_followup(message)
        if followup:
            return followup

        message_channel_followup = self.handle_message_channel_followup(message)
        if message_channel_followup:
            return message_channel_followup

        if self.looks_like_place_call_request(message):
            return self.handle_place_call_request(message, device_id=device_id)

        if self.looks_like_message_request(message):
            return self.handle_message_request(message, device_id=device_id)

        return None

    def queue_answer_call(self, device_id: Optional[str] = None, phone_number: Optional[str] = None) -> Dict[str, Any]:
        return self._queue_action(
            action_type="answer_call",
            message="Answer the active incoming call.",
            device_id=device_id,
            phone_number=phone_number,
        )

    def queue_reject_call(self, device_id: Optional[str] = None, phone_number: Optional[str] = None) -> Dict[str, Any]:
        return self._queue_action(
            action_type="reject_call",
            message="Reject the active incoming call.",
            device_id=device_id,
            phone_number=phone_number,
        )

    def queue_place_call(
        self,
        contact_name: str,
        call_method: str,
        device_id: Optional[str] = None,
        phone_number: Optional[str] = None,
        contact_id: Optional[str] = None,
        match_confidence: Optional[float] = None,
        match_reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        method = "whatsapp" if str(call_method).strip().lower() == "whatsapp" else "normal"
        resolution = self._resolve_contact_for_channel(
            contact_name,
            required_channel="whatsapp" if method == "whatsapp" else "phone",
            device_id=device_id,
        )
        if resolution and not resolution.get("success"):
            return resolution
        if resolution:
            selected = dict(resolution.get("selected_contact") or {})
            contact_name = str(selected.get("display_name") or contact_name).strip()
            phone_number = phone_number or str(selected.get("phone_number") or "").strip() or None
            contact_id = contact_id or str(selected.get("contact_id") or "").strip() or None
            match_confidence = match_confidence if match_confidence is not None else selected.get("score")
            match_reason = match_reason or str(selected.get("reason") or "").strip() or None
        message = (
            f"Open WhatsApp call flow for {contact_name}."
            if method == "whatsapp"
            else f"Call {contact_name} using the phone dialer."
        )
        return self._queue_action(
            action_type="place_call",
            message=message,
            device_id=device_id,
            phone_number=phone_number,
            contact_name=contact_name,
            call_method=method,
            contact_id=contact_id,
            match_confidence=match_confidence,
            match_reason=match_reason,
            requires_verified_speaker=True,
            verification_status="required",
        )

    def queue_draft_message(
        self,
        contact_name: str,
        message_body: str,
        channel: str,
        device_id: Optional[str] = None,
        phone_number: Optional[str] = None,
        contact_id: Optional[str] = None,
        match_confidence: Optional[float] = None,
        match_reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        normalized_channel = "whatsapp" if str(channel).strip().lower() in {"whatsapp", "wa"} else "sms"
        resolution = self._resolve_contact_for_channel(
            contact_name,
            required_channel="whatsapp" if normalized_channel == "whatsapp" else "sms",
            device_id=device_id,
        )
        if resolution and not resolution.get("success"):
            return resolution
        if resolution:
            selected = dict(resolution.get("selected_contact") or {})
            contact_name = str(selected.get("display_name") or contact_name).strip()
            phone_number = phone_number or str(selected.get("phone_number") or "").strip() or None
            contact_id = contact_id or str(selected.get("contact_id") or "").strip() or None
            match_confidence = match_confidence if match_confidence is not None else selected.get("score")
            match_reason = match_reason or str(selected.get("reason") or "").strip() or None
        return self._queue_action(
            action_type="draft_message",
            message=(
                f"Draft a WhatsApp message to {contact_name}."
                if normalized_channel == "whatsapp"
                else f"Draft an SMS message to {contact_name}."
            ),
            device_id=device_id,
            phone_number=phone_number,
            contact_name=contact_name,
            contact_id=contact_id,
            match_confidence=match_confidence,
            match_reason=match_reason,
            channel=normalized_channel,
            message_body=message_body,
            requires_verified_speaker=True,
            verification_status="required",
        )

    def _resolve_contact_for_channel(
        self,
        contact_name: str,
        *,
        required_channel: str,
        device_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        contacts = self.list_synced_contacts(device_id=device_id)
        if not contacts:
            return None

        resolver = ContactResolutionService(
            contacts_provider=lambda: contacts,
            contact_match_service=self._contact_match_service,
        )
        resolved = resolver.resolve(
            contact_name,
            source="phone_bridge",
            required_channel=required_channel,
        )
        status = str(resolved.get("status") or "").strip()
        if status == "matched":
            return resolved

        action = "phone_contact_clarification_required"
        message = str(resolved.get("message") or "").strip()
        if status == "missing_channel":
            message = f"I found {contact_name}, but that contact has no phone number."
            action = "phone_contact_missing_phone"
        elif status == "not_found":
            message = f"I couldn't find {contact_name} in your phone contacts. Sync phone contacts or type the phone number."
        elif not message:
            message = "Which phone contact did you mean?"
        return {
            "success": False,
            "action": action,
            "status": "clarification_required" if status in {"weak_match", "ambiguous"} else status,
            "message": message,
            "requires_followup": status in {"weak_match", "ambiguous"},
            "candidates": list(resolved.get("candidates") or []),
            "selected_contact": dict(resolved.get("selected_contact") or {}),
        }

    def _queue_action(
        self,
        action_type: str,
        message: str,
        device_id: Optional[str] = None,
        phone_number: Optional[str] = None,
        contact_name: Optional[str] = None,
        call_method: Optional[str] = None,
        contact_id: Optional[str] = None,
        match_confidence: Optional[float] = None,
        match_reason: Optional[str] = None,
        channel: Optional[str] = None,
        message_body: Optional[str] = None,
        requires_verified_speaker: bool = True,
        verification_status: Optional[str] = "required",
        clarification_candidates: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        target_device = self._repository.resolve_device_id(device_id)
        if not target_device:
            return {
                "success": False,
                "action": action_type,
                "message": "I do not know which phone to control yet. Let the Android companion contact Jarvis once first.",
            }

        action = PhoneAction(
            action_id=str(uuid.uuid4()),
            action_type=action_type,
            status="pending",
            device_id=target_device,
            phone_number=(phone_number or "").strip() or None,
            contact_name=(contact_name or "").strip() or None,
            call_method=(call_method or "").strip() or None,
            contact_id=(contact_id or "").strip() or None,
            match_confidence=match_confidence,
            match_reason=(match_reason or "").strip() or None,
            channel=(channel or "").strip() or None,
            message_body=(message_body or "").strip() or None,
            requires_verified_speaker=bool(requires_verified_speaker),
            verification_status=(verification_status or "").strip() or None,
            clarification_candidates=clarification_candidates,
            message=message,
            created_at=time.time(),
        )
        self._repository.queue_action(action)
        logger.info("[PHONE] Queued %s for device %s", action_type, target_device)
        return {
            "success": True,
            "action": action_type,
            "message": (
                f"Calling {contact_name} on WhatsApp."
                if action_type == "place_call" and call_method == "whatsapp"
                else f"Calling {contact_name}."
                if action_type == "place_call" and contact_name
                else f"Drafting a {channel or 'message'} to {contact_name}."
                if action_type == "draft_message" and contact_name
                else "Queued a phone command for your Android companion."
            ),
            "device_id": target_device,
            "action_id": action.action_id,
        }

    def get_pending_actions(self, device_id: str, phone_number: Optional[str] = None) -> List[Dict[str, Any]]:
        return self._repository.list_pending_actions(device_id=device_id, phone_number=phone_number)

    def acknowledge_action(
        self,
        action_id: str,
        status: str = "completed",
        device_id: Optional[str] = None,
        phone_number: Optional[str] = None,
    ) -> bool:
        return self._repository.acknowledge_action(
            action_id=action_id,
            status=status,
            device_id=device_id,
            phone_number=phone_number,
        )

    def _resolve_device_id(self, explicit_device_id: Optional[str]) -> str:
        return self._repository.resolve_device_id(explicit_device_id)

    def _expire_old_actions(self) -> None:
        self._repository.expire_old_actions()

    def _load_actions(self) -> List[Dict[str, Any]]:
        return self._repository._load_actions()

    def _save_actions(self, actions: List[Dict[str, Any]]) -> None:
        self._repository._save_actions(actions)

    def _load_devices(self) -> Dict[str, Any]:
        return self._repository._load_devices()

    def _save_devices(self, devices: Dict[str, Any]) -> None:
        self._repository._save_devices(devices)

    def get_device_status(self) -> Dict[str, Any]:
        return self._repository.get_device_status()

    def _normalize_command_text(self, message: str) -> str:
        text = (message or "").strip().lower()
        text = text.replace("jarvis", " ")
        text = re.sub(r"^[^a-z0-9]+", " ", text)
        text = re.sub(
            r"^\s*(?:uh|um|hey|hi|hello|please|can you|could you|would you|will you|do you|"
            r"can u|could u|would u|will u)\b",
            " ",
            text,
        )
        text = re.sub(
            r"\b(?:please|for me|right now|now)\b",
            " ",
            text,
        )
        text = " ".join(text.split())
        return text

    def _parse_place_call_request(self, message: str) -> Optional[Dict[str, str]]:
        text = self._normalize_command_text(message)
        if not text:
            return None

        method = None
        if "whatsapp" in text or text.startswith("whatsapp call ") or text.startswith("wa call "):
            method = "whatsapp"
            text = re.sub(r"\b(whatsapp|wa)\b", " ", text).strip()
        elif any(token in text for token in (" normal", " regular", " phone ", " normally")):
            method = "normal"
            text = re.sub(r"\b(normal|normally|regular|phone)\b", " ", text).strip()

        text = re.sub(r"^(call|dial|phone)\s+", "", text).strip()
        text = re.sub(r"\b(on|via|through|using|with)\b", " ", text).strip()
        text = re.sub(r"\b(call|please|to)\b", " ", text).strip()
        text = " ".join(text.split()).strip(" .!?")
        if not text:
            return None

        return {
            "contact_name": text,
            "call_method": method or "",
        }

    def _parse_message_request(self, message: str) -> Optional[Dict[str, str]]:
        text = self._normalize_command_text(message)
        if not text:
            return None

        channel = ""
        if re.search(r"\b(whatsapp|wa)\b", text):
            channel = "whatsapp"
            text = re.sub(r"\b(whatsapp|wa)\b", " ", text).strip()
        elif re.search(r"\b(sms|text)\b", text):
            channel = "sms"
            text = re.sub(r"\b(sms|text)\b", " ", text).strip()

        text = re.sub(r"^(send\s+)?(message|msg|text|sms)\s+", "", text).strip()
        text = re.sub(r"\b(to|on|via|through|using)\b", " ", text).strip()
        text = re.sub(r"\s+", " ", text).strip(" .!?")
        if not text:
            return None

        separators = (
            r"\s+(?:saying|that|ki|bolna|bolo)\s+",
            r"\s*:\s*",
            r"\s+-\s+",
        )
        contact_name = ""
        message_body = ""
        for separator in separators:
            parts = re.split(separator, text, maxsplit=1)
            if len(parts) == 2:
                contact_name, message_body = parts[0].strip(), parts[1].strip()
                break

        if not contact_name:
            tokens = text.split()
            if len(tokens) == 1:
                contact_name = tokens[0]
                message_body = ""
            elif len(tokens) >= 2:
                if tokens[0] in {"to", "for"}:
                    tokens = tokens[1:]
                if not tokens:
                    return None
                if len(tokens) == 1:
                    contact_name = tokens[0]
                    message_body = ""
                else:
                    contact_name = tokens[0]
                    message_body = " ".join(tokens[1:])

        contact_name = " ".join(
            token
            for token in contact_name.split()
            if token not in {"please", "pls", "bro", "sir", "my", "contact"}
        ).strip()
        message_body = message_body.strip(" .")
        if not contact_name:
            return None

        return {
            "contact_name": contact_name,
            "message_body": message_body,
            "channel": channel,
        }
