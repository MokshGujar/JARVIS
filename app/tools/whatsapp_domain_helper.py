from __future__ import annotations

import logging
import os
import re
import time
import urllib.parse
import hashlib
from pathlib import Path
from typing import Callable, Dict, Iterable

from config import BASE_DIR as CONFIG_BASE_DIR
from app.orchestrator.action_plan import ActionPlan, ActionStep
from app.orchestrator.tool_executor import ToolExecutor
from app.tools.automation_domain_helper import ServiceBackedDomainHelper
from app.services.contact_match_service import ContactCandidate, ContactMatchService
from app.services.message_action_service import MessageActionService
from app.tools.base import ToolContext

try:
    from send2trash import send2trash
    SEND2TRASH_IMPORT_ERROR = None
except Exception as exc:
    send2trash = None
    SEND2TRASH_IMPORT_ERROR = exc


logger = logging.getLogger("J.A.R.V.I.S")


def _runtime_base_dir() -> Path:
    try:
        from app.services import automation_service as automation_module

        return automation_module.BASE_DIR
    except Exception:
        return CONFIG_BASE_DIR



class AutomationWhatsAppCompatibility(ServiceBackedDomainHelper):

    def _handle_mark_confirmation(self, command: str) -> Dict[str, str | bool]:
            pending = self._pending_mark_action
            reply = self._normalize_spoken_command(command).lower()
            if not pending:
                return {"success": False, "action": "confirmation", "message": "No action is waiting for confirmation."}
            payload_for_expiry = dict(pending.get("payload") or {})
            expires_at = float(payload_for_expiry.get("expires_at") or 0.0)
            if expires_at and time.time() > expires_at:
                self._pending_mark_action = None
                return {"success": False, "action": "confirmation_expired", "message": "That WhatsApp confirmation expired."}

            if reply in {"no", "n", "cancel"}:
                self._pending_mark_action = None
                return {"success": True, "action": "confirmation_cancelled", "message": "Cancelled."}

            if reply not in {"yes", "y", "go ahead", "confirm", "delete it"}:
                return {"success": False, "action": "confirmation", "message": "Say yes to continue or no to cancel."}

            self._pending_mark_action = None
            if pending.get("kind") == "send_message":
                payload = dict(pending.get("payload") or {})
                if str(payload.get("platform") or "").lower() == "whatsapp":
                    return self._execute_confirmed_whatsapp_action("send_message", payload)
                return self.message_action_service.send(payload)
            if pending.get("kind") == "whatsapp_call":
                payload = dict(pending.get("payload") or {})
                action = "start_video_call" if str(payload.get("mode") or "voice").lower() == "video" else "start_voice_call"
                return self._execute_confirmed_whatsapp_action(action, payload)
            if pending.get("kind") == "game":
                return self.game_service.confirm(dict(pending.get("payload") or {}))
            return {"success": False, "action": "confirmation", "message": "That confirmation type is not supported."}


    def _execute_confirmed_whatsapp_action(self, action: str, payload: dict[str, object]) -> Dict[str, object]:
            executor = ToolExecutor(registry=self._build_automation_tool_registry(), enforce_policy=True)
            return executor.execute(
                ActionPlan(
                    original_text=self._whatsapp_pending_command(action, payload),
                    steps=[
                        ActionStep(
                            step_id="step1",
                            tool_name="whatsapp",
                            intent="whatsapp",
                            action=action,
                            args=dict(payload),
                        )
                    ],
                    is_multistep=False,
                ),
                ToolContext(
                    command=self._whatsapp_pending_command(action, payload),
                    intent="whatsapp",
                    session_id=self._active_session_id,
                    request_id=self._active_turn_id,
                    payload={"turn_id": self._active_turn_id} if self._active_turn_id else {},
                    source=self._active_request_source,
                    confirmation_state={"confirmed": True},
                    security_state={"step_up_verified": self._active_step_up_verified},
                ),
            )


    @staticmethod
    def _whatsapp_pending_command(action: str, payload: dict[str, object]) -> str:
            if action == "send_message":
                return f"send whatsapp message to {payload.get('receiver') or 'contact'}"
            if action == "open_chat":
                return f"open whatsapp chat with {payload.get('contact') or 'contact'}"
            if action == "start_video_call":
                return f"video call {payload.get('contact') or 'contact'} on whatsapp"
            return f"voice call {payload.get('contact') or 'contact'} on whatsapp"


    def _looks_like_whatsapp_command(self, lowered: str) -> bool:
            return bool(
                lowered.startswith(("open whatsapp", "whatsapp web", "whatsapp desktop", "search contact in whatsapp", "end call"))
                or self._extract_whatsapp_open_chat_intent(lowered) is not None
                or self._extract_whatsapp_call_intent(lowered) is not None
                or self._extract_whatsapp_message_intent(lowered) is not None
            )


    def _execute_whatsapp_command(self, command: str) -> Dict[str, object] | None:
            from app.tools.whatsapp_tool import WhatsAppTool

            return WhatsAppTool(self).execute(ToolContext(command=command, intent="whatsapp"))


    def _extract_whatsapp_call_intent(self, command: str) -> dict[str, str] | None:
            text = self._normalize_spoken_command(command).strip()
            patterns = (
                r"^(?:make\s+(?:a\s+)?)(?:whatsapp\s+)?(?P<mode>video\s+call|voice\s+call|call)\s+to\s+(?P<contact>.+?)(?:\s+(?:on|via|using)\s+whatsapp)?[.!?]*$",
                r"^(?:tell\s+jarvis\s+to\s+)(?:whatsapp\s+)?(?P<mode>video\s+call|voice\s+call|call)\s+(?P<contact>.+?)(?:\s+(?:on|via|using)\s+whatsapp)?[.!?]*$",
                r"^(?:whatsapp\s+)?(?P<mode>video\s+call|voice\s+call|call)\s+(?P<contact>.+?)(?:\s+(?:on|via|using)\s+whatsapp)?[.!?]*$",
                r"^(?P<mode>video\s+call|voice\s+call|call)\s+(?P<contact>.+?)\s+(?:on|via|using)\s+whatsapp[.!?]*$",
            )
            for pattern in patterns:
                match = re.match(pattern, text, flags=re.IGNORECASE)
                if match:
                    mode = "video" if "video" in match.group("mode").lower() else "voice"
                    contact = self._clean_whatsapp_contact(match.group("contact"))
                    return {"mode": mode, "contact": contact}
            return None


    def _extract_whatsapp_open_chat_intent(self, command: str) -> dict[str, str] | None:
            text = self._normalize_spoken_command(command).strip()
            patterns = (
                r"^open\s+whatsapp\s+chat\s+with\s+(?P<contact>.+?)[.!?]*$",
                r"^open\s+chat\s+with\s+(?P<contact>.+?)\s+(?:on|via|using)\s+whatsapp[.!?]*$",
            )
            for pattern in patterns:
                match = re.match(pattern, text, flags=re.IGNORECASE)
                if match:
                    return {"contact": self._clean_whatsapp_contact(match.group("contact"))}
            return None


    def _extract_whatsapp_message_intent(self, command: str) -> dict[str, str] | None:
            text = self._normalize_spoken_command(command).strip()
            patterns = (
                r"^(?:send\s+(?:a\s+)?(?:whatsapp\s+)?(?:message|text)\s+to|whatsapp\s+message\s+to|message\s+on\s+whatsapp\s+to)\s+(?P<receiver>.+?)(?:\s+(?:saying|that says|text|message)\s+(?P<message>.+?))?[.!?]*$",
                r"^(?:message|text)\s+(?P<receiver>[A-Za-z][A-Za-z0-9_ .'’-]*?)\s+(?P<message>.+?)[.!?]*$",
                r"^(?:message|text)\s+(?P<receiver>.+?)(?:\s+(?:on|via|using)\s+whatsapp)?(?:\s+(?:saying|that says|text|message)\s+(?P<message>.+?))?[.!?]*$",
            )
            for pattern in patterns:
                match = re.match(pattern, text, flags=re.IGNORECASE)
                if match:
                    receiver = self._clean_whatsapp_contact(match.group("receiver"))
                    message = (match.group("message") or "").strip().rstrip(".!?")
                    return {"receiver": receiver, "message": message}
            return None


    def _clean_whatsapp_contact(self, value: str) -> str:
            contact = (value or "").strip().strip(" ,;.!?")
            contact = re.sub(r"\s+(?:on|via|using)\s+whatsapp$", "", contact, flags=re.IGNORECASE).strip()
            return contact


    def _repair_whatsapp_message_contact(self, receiver: str, message: str) -> tuple[str, str]:
            if self._whatsapp_contacts_provider is None or not receiver or not message:
                return receiver, message
            words = message.split()
            best_receiver = receiver
            best_message = message
            best_score = 0.0
            for count in range(1, min(4, len(words)) + 1):
                candidate_receiver = " ".join([receiver, *words[:count]]).strip()
                candidate_message = " ".join(words[count:]).strip()
                if not candidate_message:
                    continue
                decision = self._resolve_whatsapp_contact(candidate_receiver)
                contact = dict(decision.get("contact") or {}) if decision.get("status") in {"auto_call", "confirm_contact"} else {}
                score = float(contact.get("score") or 0.0)
                if score > best_score:
                    best_score = score
                    best_receiver = candidate_receiver
                    best_message = candidate_message
            if best_score >= self.contact_match_service.HIGH_CONFIDENCE:
                return best_receiver, best_message
            return receiver, message


    def _is_ambiguous_communication_contact(self, value: str) -> bool:
            contact = self._normalize_spoken_command(value).lower().strip(" ,;.!?")
            contact = re.sub(r"^(?:a|the)\s+", "", contact)
            return contact in {
                "someone",
                "somebody",
                "anyone",
                "anybody",
                "person",
                "him",
                "her",
                "them",
                "that person",
                "this person",
            }


    def _whatsapp_contact_required_result(self, kind: str, payload: dict[str, object] | None = None) -> Dict[str, object]:
            payload = dict(payload or {})
            self._pending_whatsapp_clarification = {"kind": kind, "payload": payload}
            is_message = kind in {"send_message", "send_message_text"}
            prompt = "Who should I message on WhatsApp?" if is_message else "Which WhatsApp chat should I open?" if kind == "open_chat" else "Who should I call on WhatsApp?"
            return self._status_result(
                "whatsapp_contact_required",
                prompt,
                success=False,
                status="whatsapp_contact_required",
            )


    def _whatsapp_call_pending_result(self, mode: str, contact: str) -> Dict[str, object]:
            message = f"Ready to call {contact} on WhatsApp. Say yes to continue or no to cancel."
            return {
                "success": False,
                "action": "whatsapp_call_pending",
                "message": message,
                "pending": {"mode": mode, "contact": contact},
                "requires_step_up": False,
                "actions": [{"type": "show_status", "status": "whatsapp_call_pending", "message": message}],
            }


    def _whatsapp_message_pending_result(self, contact: dict[str, object], message_text: str, fallback_receiver: str) -> Dict[str, object]:
            display_name = str(contact.get("display_name") or fallback_receiver).strip()
            message = f"Ready to send this via whatsapp to {display_name}: \"{message_text}\". Say yes to send or no to cancel."
            return {
                "success": False,
                "action": "send_message_pending",
                "message": message,
                "pending": {
                    "platform": "whatsapp",
                    "receiver": display_name,
                    "message": message_text,
                    "contact_id": str(contact.get("contact_id") or "").strip(),
                    "phone_number": str(contact.get("phone_number") or "").strip(),
                    "match_confidence": contact.get("score"),
                    "match_reason": str(contact.get("reason") or "").strip(),
                    "risk_level": "HIGH_RISK",
                    "expires_at": time.time() + 90,
                },
                "requires_step_up": False,
                "actions": [{"type": "show_status", "status": "whatsapp_message_pending", "message": message}],
            }


    def _prepare_whatsapp_call_confirmation(self, mode: str, query: str) -> Dict[str, object]:
            decision = self._resolve_whatsapp_contact(query)
            if decision["status"] == "not_found":
                return self._status_result(
                    "whatsapp_contact_not_found",
                    str(decision["message"]),
                    success=False,
                    status="whatsapp_contact_not_found",
                )
            if decision["status"] == "clarify":
                candidates = list(decision.get("candidates") or [])
                self._pending_whatsapp_clarification = {
                    "kind": "whatsapp_call",
                    "payload": {
                        "mode": mode,
                        "query": query,
                        "candidates": candidates,
                        "message": str(decision["message"]),
                    },
                }
                return self._status_result(
                    "whatsapp_contact_ambiguous",
                    str(decision["message"]),
                    success=False,
                    status="whatsapp_contact_required",
                )
            if decision["status"] == "missing_channel":
                contact = dict(decision.get("contact") or {})
                display_name = str(contact.get("display_name") or query).strip()
                return self._status_result(
                    "whatsapp_missing_phone",
                    f"I found {display_name}, but that contact has no phone number for WhatsApp.",
                    success=False,
                    status="whatsapp_missing_phone",
                )
            if decision["status"] == "confirm_contact":
                contact = dict(decision["contact"])
                message = str(decision.get("message") or f"I found {contact.get('display_name')}. Did you mean {contact.get('display_name')}?")
                self._pending_whatsapp_clarification = {
                    "kind": "pending_whatsapp_contact_resolution",
                    "payload": {
                        "original_user_input": query,
                        "intended_action": "call" if mode == "voice" else "video_call",
                        "raw_contact_text": query,
                        "fuzzy_candidates": [contact],
                        "selected_contact": contact,
                        "mode": mode,
                    },
                }
                return self._status_result(
                    "whatsapp_contact_fuzzy",
                    message,
                    success=False,
                    status="whatsapp_contact_fuzzy",
                )

            contact = dict(decision["contact"])
            display_name = str(contact.get("display_name") or query).strip()
            payload = {
                "mode": mode,
                "contact": display_name,
                "contact_id": str(contact.get("contact_id") or "").strip(),
                "phone_number": str(contact.get("phone_number") or "").strip(),
                "match_confidence": contact.get("score"),
                "match_reason": str(contact.get("reason") or "").strip(),
                "contact_hash": self._safe_contact_hash(display_name),
                "direct_user_requested": True,
                "recipient_confident": True,
                "fresh_user_command": True,
                "user_initiated": self._active_request_source in {"user", "text", "voice"},
                "single_recipient": True,
                "bulk": False,
                "risk_level": "HIGH_RISK",
                "expires_at": time.time() + 90,
            }
            return self._execute_direct_whatsapp_action("start_video_call" if mode == "video" else "start_voice_call", payload)


    def _prepare_whatsapp_message_confirmation(self, receiver_query: str, message_text: str) -> Dict[str, object]:
            if self._whatsapp_contacts_provider is None and not isinstance(self.message_action_service, MessageActionService):
                return self.message_action_service.prepare("whatsapp", receiver_query, message_text)
            decision = self._resolve_whatsapp_contact(receiver_query)
            if decision["status"] == "not_found":
                return self._status_result(
                    "whatsapp_contact_not_found",
                    str(decision["message"]),
                    success=False,
                    status="whatsapp_contact_not_found",
                )
            if decision["status"] == "clarify":
                candidates = list(decision.get("candidates") or [])
                self._pending_whatsapp_clarification = {
                    "kind": "pending_whatsapp_contact_resolution",
                    "payload": {
                        "original_user_input": receiver_query,
                        "intended_action": "message",
                        "raw_contact_text": receiver_query,
                        "fuzzy_candidates": candidates,
                        "message_text": message_text,
                        "message": str(decision["message"]),
                    },
                }
                return self._status_result(
                    "whatsapp_contact_ambiguous",
                    str(decision["message"]),
                    success=False,
                    status="whatsapp_contact_required",
                )
            if decision["status"] == "missing_channel":
                contact = dict(decision.get("contact") or {})
                display_name = str(contact.get("display_name") or receiver_query).strip()
                return self._status_result(
                    "whatsapp_missing_phone",
                    f"I found {display_name}, but that contact has no phone number for WhatsApp.",
                    success=False,
                    status="whatsapp_missing_phone",
                )
            if decision["status"] == "confirm_contact":
                contact = dict(decision["contact"])
                message = str(decision.get("message") or f"I found {contact.get('display_name')}. Did you mean {contact.get('display_name')}?")
                self._pending_whatsapp_clarification = {
                    "kind": "pending_whatsapp_contact_resolution",
                    "payload": {
                        "original_user_input": receiver_query,
                        "intended_action": "message",
                        "raw_contact_text": receiver_query,
                        "fuzzy_candidates": [contact],
                        "selected_contact": contact,
                        "message_text": message_text,
                    },
                }
                return self._status_result(
                    "whatsapp_contact_fuzzy",
                    message,
                    success=False,
                    status="whatsapp_contact_fuzzy",
                )

            contact = dict(decision["contact"])
            display_name = str(contact.get("display_name") or receiver_query).strip()
            payload = {
                "platform": "whatsapp",
                "receiver": display_name,
                "message": message_text,
                "contact_id": str(contact.get("contact_id") or "").strip(),
                "phone_number": str(contact.get("phone_number") or "").strip(),
                "match_confidence": contact.get("score"),
                "match_reason": str(contact.get("reason") or "").strip(),
                "contact_hash": self._safe_contact_hash(display_name),
                "direct_user_requested": True,
                "recipient_confident": True,
                "fresh_user_command": True,
                "user_initiated": self._active_request_source in {"user", "text", "voice"},
                "single_recipient": True,
                "bulk": False,
                "risk_level": "HIGH_RISK",
                "expires_at": time.time() + 90,
            }
            return self._execute_direct_whatsapp_action("send_message", payload)


    def _prepare_whatsapp_open_chat(self, query: str) -> Dict[str, object]:
            decision = self._resolve_whatsapp_contact(query)
            if decision["status"] == "not_found":
                return self._status_result("whatsapp_contact_not_found", str(decision["message"]), success=False, status="whatsapp_contact_not_found")
            if decision["status"] == "clarify":
                return self._status_result("whatsapp_contact_ambiguous", str(decision["message"]), success=False, status="whatsapp_contact_required")
            if decision["status"] == "confirm_contact":
                contact = dict(decision["contact"])
                return self._status_result(
                    "whatsapp_contact_fuzzy",
                    str(decision.get("message") or f"I found {contact.get('display_name')}. Did you mean {contact.get('display_name')}?"),
                    success=False,
                    status="whatsapp_contact_fuzzy",
                )
            contact = dict(decision["contact"])
            display_name = str(contact.get("display_name") or query).strip()
            payload = {
                "contact": display_name,
                "phone_number": str(contact.get("phone_number") or "").strip(),
                "contact_id": str(contact.get("contact_id") or "").strip(),
                "match_confidence": contact.get("score"),
                "match_reason": str(contact.get("reason") or "").strip(),
                "contact_hash": self._safe_contact_hash(display_name),
                "direct_user_requested": True,
                "recipient_confident": True,
                "fresh_user_command": True,
                "user_initiated": self._active_request_source in {"user", "text", "voice"},
                "single_recipient": True,
                "bulk": False,
            }
            return self._execute_direct_whatsapp_action("open_chat", payload)


    def _execute_direct_whatsapp_action(self, action: str, payload: dict[str, object]) -> Dict[str, object]:
            logger.info(
                "[MANUAL_LIVE_VALIDATION] mode=enabled action=whatsapp status=ready reason=fresh_explicit_user_command"
                if self._active_request_source in {"user", "text", "voice"}
                else "[MANUAL_LIVE_VALIDATION] mode=disabled action=whatsapp status=blocked reason=non_user_source"
            )
            executor = ToolExecutor(registry=self._build_automation_tool_registry(), enforce_policy=True)
            command = self._whatsapp_pending_command(action, payload)
            result = executor.execute(
                ActionPlan(
                    original_text=command,
                    steps=[
                        ActionStep(
                            step_id="step1",
                            tool_name="whatsapp",
                            intent="whatsapp",
                            action=action,
                            args=dict(payload),
                        )
                    ],
                    is_multistep=False,
                ),
                ToolContext(
                    command=command,
                    intent="whatsapp",
                    session_id=self._active_session_id,
                    request_id=self._active_turn_id,
                    payload={"turn_id": self._active_turn_id} if self._active_turn_id else {},
                    source=self._active_request_source,
                    security_state={"step_up_verified": self._active_step_up_verified},
                ),
            )
            if isinstance(result, dict) and isinstance(result.get("policy"), dict):
                result["direct_policy"] = dict(result["policy"])
            return result


    def _resolve_whatsapp_contact(self, query: str) -> dict[str, object]:
            contact_query = self._clean_whatsapp_contact(query)
            contacts = self._load_whatsapp_contacts()
            if contacts is None:
                return {
                    "status": "not_found",
                    "message": "I need synced contacts before I can confidently use that WhatsApp contact.",
                }
            resolved = self.contact_resolution_service.resolve(contact_query, source="whatsapp", required_channel="whatsapp")
            status = str(resolved.get("status") or "")
            if status == "matched":
                return {"status": "auto_call", "contact": dict(resolved.get("selected_contact") or {})}
            if status == "weak_match":
                candidates = list(resolved.get("candidates") or [])
                candidate = dict(candidates[0]) if candidates else {}
                return {
                    "status": "confirm_contact",
                    "contact": candidate,
                    "message": resolved.get("message") or f"I found {candidate.get('display_name')}. Did you mean {candidate.get('display_name')}?",
                }
            if status in {"ambiguous", "missing_channel"}:
                candidates = list(resolved.get("candidates") or [])
                if status == "missing_channel":
                    return {
                        "status": "missing_channel",
                        "message": resolved.get("message") or "That contact is missing a WhatsApp phone number.",
                        "contact": dict(resolved.get("selected_contact") or {}),
                    }
                return {
                    "status": "clarify",
                    "message": self._build_whatsapp_contact_clarification(contact_query, candidates),
                    "candidates": candidates,
                }
            return {
                "status": "not_found",
                "message": resolved.get("message") or f"I couldn't find {contact_query} in your contacts.",
            }


    def _load_whatsapp_contacts(self) -> list[ContactCandidate] | None:
            if self._whatsapp_contacts_provider is None:
                return None
            try:
                contacts = list(self._whatsapp_contacts_provider() or [])
            except Exception:
                return []
            normalized: list[ContactCandidate] = []
            for item in contacts:
                if isinstance(item, ContactCandidate):
                    normalized.append(item)
                elif isinstance(item, dict):
                    normalized.append(ContactCandidate(**item))
            return normalized


    def _contact_candidate_payload(self, candidate: ContactCandidate) -> dict[str, object]:
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
    def _safe_contact_hash(value: str) -> str:
            normalized = " ".join(str(value or "").strip().lower().split())
            return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16] if normalized else ""


    def _build_whatsapp_contact_clarification(self, query: str, candidates: list[dict[str, object]]) -> str:
            names = [str(candidate.get("display_name") or "").strip() for candidate in candidates if str(candidate.get("display_name") or "").strip()]
            if not names:
                return f"Which {query} should I call on WhatsApp?"
            if len(names) == 1:
                return f"Did you mean {names[0]}?"
            return f"Which {query} should I call on WhatsApp: {', '.join(names[:-1])}, or {names[-1]}?"


    def _resolve_pending_whatsapp_candidate(self, reply: str, candidates_payload: list[dict[str, object]]) -> dict[str, object] | None:
            candidates = [
                ContactCandidate(
                    contact_id=str(candidate.get("contact_id") or ""),
                    display_name=str(candidate.get("display_name") or ""),
                    phone_number=str(candidate.get("phone_number") or ""),
                    aliases=list(candidate.get("aliases") or []),
                    favorite=bool(candidate.get("favorite", False)),
                    recent=bool(candidate.get("recent", False)),
                    frequent=bool(candidate.get("frequent", False)),
                    score=float(candidate.get("score") or 0.0),
                    reason=str(candidate.get("reason") or ""),
                )
                for candidate in candidates_payload
            ]
            key = "automation_whatsapp"
            self.contact_match_service.save_clarification(key, candidates, call_method="whatsapp", ttl_seconds=60)
            resolved = self.contact_match_service.resolve_clarification(key, reply)
            return self._contact_candidate_payload(resolved) if resolved else None


    def _stage_resolved_whatsapp_action(self, payload: dict[str, object], resolved: dict[str, object]) -> Dict[str, object]:
            intended_action = str(payload.get("intended_action") or "").strip()
            if intended_action in {"call", "video_call"}:
                mode = "video" if intended_action == "video_call" else str(payload.get("mode") or "voice")
                mode = "video" if mode == "video" else "voice"
                display_name = str(resolved.get("display_name") or payload.get("raw_contact_text") or "").strip()
                result = self._whatsapp_call_pending_result(mode, display_name)
                result["pending"] = {
                    "mode": mode,
                    "contact": display_name,
                    "contact_id": str(resolved.get("contact_id") or ""),
                    "phone_number": str(resolved.get("phone_number") or ""),
                    "match_confidence": resolved.get("score"),
                    "match_reason": str(resolved.get("reason") or ""),
                    "risk_level": "HIGH_RISK",
                    "expires_at": time.time() + 90,
                }
                self._pending_mark_action = {"kind": "whatsapp_call", "payload": dict(result["pending"])}
                return result

            if intended_action == "message":
                message_text = str(payload.get("message_text") or "").strip()
                if not message_text:
                    self._pending_whatsapp_clarification = {
                        "kind": "send_message_text",
                        "payload": {"platform": "whatsapp", "receiver": str(resolved.get("display_name") or "")},
                    }
                    return self._status_result(
                        "whatsapp_message_text_required",
                        f"What should I say to {resolved.get('display_name')} on WhatsApp?",
                        success=False,
                        status="whatsapp_message_text_required",
                    )
                result = self._whatsapp_message_pending_result(resolved, message_text, str(payload.get("raw_contact_text") or ""))
                self._pending_mark_action = {"kind": "send_message", "payload": dict(result.get("pending") or {})}
                return result

            return {"success": False, "action": "unsupported", "message": "That WhatsApp contact confirmation expired."}


    def _handle_whatsapp_clarification_followup(self, command: str) -> Dict[str, object]:
            pending = self._pending_whatsapp_clarification or {}
            reply = self._normalize_spoken_command(command).strip()
            lowered = reply.lower()
            if lowered in {"no", "n", "cancel", "stop", "never mind", "nevermind"}:
                self._pending_whatsapp_clarification = None
                return {"success": True, "action": "confirmation_cancelled", "message": "Cancelled."}

            kind = str(pending.get("kind") or "")
            payload = dict(pending.get("payload") or {})

            if kind == "pending_whatsapp_contact_resolution":
                candidates = list(payload.get("fuzzy_candidates") or [])
                selected = dict(payload.get("selected_contact") or {}) if isinstance(payload.get("selected_contact"), dict) else {}
                resolved = None
                if selected and lowered in {"yes", "y", "confirm", "go ahead"}:
                    resolved = selected
                elif candidates:
                    resolved = self._resolve_pending_whatsapp_candidate(reply, candidates)

                if not resolved:
                    self._pending_whatsapp_clarification = pending
                    return self._status_result(
                        "whatsapp_contact_ambiguous",
                        str(payload.get("message") or "Which contact did you mean?"),
                        success=False,
                        status="whatsapp_contact_required",
                    )

                original = str(payload.get("raw_contact_text") or payload.get("original_user_input") or "").strip()
                display = str(dict(resolved).get("display_name") or "").strip()
                if original and display and original.lower() != display.lower():
                    try:
                        self.contact_match_service.save_confirmed_alias(display, original)
                    except Exception:
                        logger.debug("Could not persist confirmed contact alias", exc_info=True)
                self._pending_whatsapp_clarification = None
                return self._stage_resolved_whatsapp_action(payload, resolved)

            if kind == "send_message_text":
                self._pending_whatsapp_clarification = None
                receiver = str(payload.get("receiver") or "").strip()
                message_result = self._prepare_whatsapp_message_confirmation(receiver, reply)
                message_pending = message_result.get("pending") if isinstance(message_result, dict) else None
                if message_pending:
                    self._pending_mark_action = {"kind": "send_message", "payload": message_pending}
                return message_result

            contact = self._clean_whatsapp_contact(reply)
            if not contact or self._is_ambiguous_communication_contact(contact) or self.looks_like_confirmation_response(contact):
                return self._whatsapp_contact_required_result(kind, payload)

            self._pending_whatsapp_clarification = None
            if kind == "whatsapp_call":
                candidates = list(payload.get("candidates") or [])
                if candidates:
                    resolved = self._resolve_pending_whatsapp_candidate(contact, candidates)
                    if not resolved:
                        return self._status_result(
                            "whatsapp_contact_ambiguous",
                            str(payload.get("message") or "Which contact should I call on WhatsApp?"),
                            success=False,
                            status="whatsapp_contact_required",
                        )
                    mode = str(payload.get("mode") or "voice")
                    display_name = str(resolved.get("display_name") or contact).strip()
                    result = self._whatsapp_call_pending_result(mode, display_name)
                    result["pending"] = {
                        "mode": mode,
                        "contact": display_name,
                        "contact_id": str(resolved.get("contact_id") or ""),
                        "phone_number": str(resolved.get("phone_number") or ""),
                        "match_confidence": resolved.get("score"),
                        "match_reason": str(resolved.get("reason") or ""),
                    }
                else:
                    result = self._prepare_whatsapp_call_confirmation(str(payload.get("mode") or "voice"), contact)
                if dict(result.get("pending") or {}):
                    self._pending_mark_action = {"kind": "whatsapp_call", "payload": dict(result.get("pending") or {})}
                return result
            if kind == "send_message":
                message = str(payload.get("message") or "").strip()
                if not message:
                    self._pending_whatsapp_clarification = {
                        "kind": "send_message_text",
                        "payload": {"platform": "whatsapp", "receiver": contact},
                    }
                    return self._status_result(
                        "whatsapp_message_text_required",
                        f"What should I say to {contact} on WhatsApp?",
                        success=False,
                        status="whatsapp_message_text_required",
                    )
                message_result = self._prepare_whatsapp_message_confirmation(contact, message)
                message_pending = message_result.get("pending") if isinstance(message_result, dict) else None
                if message_pending:
                    self._pending_mark_action = {"kind": "send_message", "payload": message_pending}
                return message_result

            self._pending_whatsapp_clarification = None
            return {"success": False, "action": "unsupported", "message": "That WhatsApp clarification expired."}


    def _status_result(self, action: str, message: str, *, success: bool = False, status: str = "status") -> Dict[str, object]:
            return {
                "success": success,
                "action": action,
                "message": message,
                "display_text": message,
                "actions": [{"type": "show_status", "status": status, "message": message, "action": action}],
            }


    def _looks_like_send_message(self, lowered: str) -> bool:
            return bool(re.search(r"\b(?:send|message|text)\b.*\b(?:whatsapp|telegram|instagram|insta)\b", lowered))


    def _prepare_message_action(self, command: str) -> Dict[str, str | bool] | None:
            patterns = [
                r"^(?:send\s+(?:a\s+)?(?:message|text)\s+)?(?:on\s+)?(?P<platform>whatsapp|telegram|instagram|insta)(?:\s+message)?\s+to\s+(?P<receiver>.+?)\s+(?:saying|that says|message|text)\s+(?P<message>.+?)[.!?]*$",
                r"^send\s+(?:a\s+)?(?P<platform>whatsapp|telegram|instagram|insta)(?:\s+message)?\s+to\s+(?P<receiver>.+?)\s+(?:saying|that says|message|text)\s+(?P<message>.+?)[.!?]*$",
            ]
            for pattern in patterns:
                match = re.match(pattern, command, flags=re.IGNORECASE)
                if match:
                    platform = match.group("platform").strip()
                    receiver = match.group("receiver").strip()
                    message = match.group("message").strip().rstrip(".!?")
                    return self.message_action_service.prepare(platform, receiver, message)
            return None


    def _open_whatsapp_desktop_or_web(self) -> Dict[str, object]:
            desktop_result = self.whatsapp_desktop.open()
            if bool(desktop_result.get("success")):
                message = "Opening WhatsApp Desktop."
                return {
                    "success": True,
                    "action": "open_whatsapp",
                    "message": message,
                    "display_text": message,
                    "actions": [{"type": "show_status", "status": "whatsapp", "message": message}],
                }

            web_result = self._open_whatsapp_web()
            if bool(web_result.get("success")):
                web_result["message"] = "WhatsApp Desktop was unavailable, so I opened WhatsApp Web."
                web_result["display_text"] = web_result["message"]
                web_result["actions"] = [{"type": "show_status", "status": "whatsapp_web", "message": web_result["message"]}]
                return web_result

            return self._status_result(
                "open_whatsapp",
                f"WhatsApp Desktop could not be verified and WhatsApp Web fallback is unavailable. Desktop: {desktop_result.get('message')} Web: {web_result.get('message')}",
                success=False,
                status="whatsapp_unavailable",
            )


    def _open_whatsapp_web(self) -> Dict[str, object]:
            result = self.browser_control_service.execute("go_to", url="https://web.whatsapp.com", timeout=20)
            if not bool(result.get("success")):
                return self._status_result("open_whatsapp_web", str(result.get("message") or "Could not open WhatsApp Web."), success=False, status="whatsapp_web_unavailable")
            logged_in = self.browser_control_service.execute("whatsapp_logged_in", timeout=12)
            login_state = str(logged_in.get("message") or "")
            if login_state == "not_logged_in":
                return self._status_result(
                    "open_whatsapp_web",
                    "WhatsApp Web is open, but it is not logged in. Link a device before Jarvis can automate WhatsApp Web.",
                    success=False,
                    status="whatsapp_login_required",
                )
            message = "WhatsApp Web is open."
            return {
                "success": True,
                "action": "open_whatsapp_web",
                "message": message,
                "display_text": message,
                "actions": [{"type": "show_status", "status": "whatsapp_web", "message": message}],
            }


    def _send_whatsapp_message(self, payload: dict) -> Dict[str, object]:
            receiver = str(payload.get("receiver") or "").strip()
            message_body = str(payload.get("message") or "").strip()
            if not receiver or not message_body:
                return self._status_result("send_whatsapp_message", "Tell me the WhatsApp contact and message text.", success=False, status="whatsapp_missing_details")
            phone_number = str(payload.get("phone_number") or "").strip()
            if not phone_number and self._whatsapp_contacts_provider is not None:
                return self._status_result(
                    "send_whatsapp_message",
                    f"I found {receiver}, but the contact has no phone number for WhatsApp Desktop. I did not send the message.",
                    success=False,
                    status="whatsapp_missing_phone",
                )

            if phone_number:
                desktop = self.whatsapp_desktop.send_message(phone_number, message_body)
                if bool(desktop.get("success")):
                    return self._status_result(
                        "send_whatsapp_message",
                        f"Sent the WhatsApp message to {receiver}.",
                        success=True,
                        status="whatsapp_message_sent",
                    )
                if str(desktop.get("status") or "") != "whatsapp_desktop_unavailable":
                    return self._status_result(
                        "send_whatsapp_message",
                        str(desktop.get("message") or "Jarvis could not verify WhatsApp Desktop. I did not send the message."),
                        success=False,
                        status=str(desktop.get("status") or "whatsapp_desktop_unverified"),
                    )

            desktop = self._open_app_target("whatsapp", "WhatsApp Desktop", suppress_browser_prompt=True)
            if bool(desktop.get("success")):
                return self._status_result(
                    "send_whatsapp_message",
                    "WhatsApp Desktop opened, but Jarvis could not verify the recipient/message send state. I did not send the message.",
                    success=False,
                    status="whatsapp_desktop_unverified",
                )

            web = self._open_whatsapp_web()
            if not bool(web.get("success")):
                return web

            return self._status_result(
                "send_whatsapp_message",
                "WhatsApp Web fallback is available, but Jarvis could not verify a safe send selector. I did not send the message.",
                success=False,
                status="whatsapp_send_unverified",
            )


    def _open_whatsapp_chat(self, payload: dict) -> Dict[str, object]:
            contact = str(payload.get("contact") or payload.get("receiver") or "").strip()
            if not contact:
                return self._status_result("open_whatsapp_chat", "Tell me which WhatsApp contact to open.", success=False, status="whatsapp_missing_contact")
            phone_number = str(payload.get("phone_number") or "").strip()
            if not phone_number:
                return self._status_result(
                    "open_whatsapp_chat",
                    f"I found {contact}, but the contact has no phone number for WhatsApp Desktop. I did not open the chat.",
                    success=False,
                    status="whatsapp_missing_phone",
                )
            desktop = self.whatsapp_desktop.open_chat(phone_number, "")
            if bool(desktop.get("success")):
                return self._status_result(
                    "open_whatsapp_chat",
                    f"Opened WhatsApp chat with {contact}.",
                    success=True,
                    status="whatsapp_chat_open",
                )
            if str(desktop.get("status") or "") != "whatsapp_desktop_unavailable":
                return self._status_result(
                    "open_whatsapp_chat",
                    str(desktop.get("message") or "Jarvis could not verify the WhatsApp chat. I did not continue."),
                    success=False,
                    status=str(desktop.get("status") or "whatsapp_chat_unverified"),
                )
            web = self._open_whatsapp_web()
            if not bool(web.get("success")):
                return web
            return self._status_result(
                "open_whatsapp_chat",
                f"WhatsApp Web is open, but Jarvis could not verify the chat for {contact}.",
                success=False,
                status="whatsapp_chat_unverified",
            )


    def _start_whatsapp_call(self, payload: dict) -> Dict[str, object]:
            contact = str(payload.get("contact") or "").strip()
            mode = "video" if str(payload.get("mode") or "").lower() == "video" else "voice"
            if not contact:
                return self._status_result("whatsapp_call", "Tell me which WhatsApp contact to call.", success=False, status="whatsapp_missing_contact")
            phone_number = str(payload.get("phone_number") or "").strip()
            if not phone_number and self._whatsapp_contacts_provider is not None:
                return self._status_result(
                    "whatsapp_call",
                    f"I found {contact}, but the contact has no phone number for WhatsApp Desktop. I did not start the call.",
                    success=False,
                    status="whatsapp_missing_phone",
                )

            if phone_number:
                desktop_result = self.whatsapp_desktop.start_call(phone_number, mode)
                if bool(desktop_result.get("success")):
                    self._active_whatsapp_call = {"contact": contact, "mode": mode, "started_at": time.time(), "phone_number": phone_number}
                    return self._status_result(
                        "whatsapp_call",
                        f"Calling {contact}...",
                        success=True,
                        status="whatsapp_calling",
                    )
                if str(desktop_result.get("status") or "") != "whatsapp_desktop_unavailable":
                    return self._status_result(
                        "whatsapp_call",
                        str(desktop_result.get("message") or f"Jarvis could not verify the {mode} call UI for {contact}. I did not start the call."),
                        success=False,
                        status=str(desktop_result.get("status") or "whatsapp_desktop_unverified"),
                    )

            desktop = self._open_app_target("whatsapp", "WhatsApp Desktop", suppress_browser_prompt=True)
            if bool(desktop.get("success")):
                if self._click_verified_whatsapp_call_button(contact, mode):
                    self._active_whatsapp_call = {"contact": contact, "mode": mode, "started_at": time.time()}
                    return self._status_result(
                        "whatsapp_call",
                        f"Calling {contact}...",
                        success=True,
                        status="whatsapp_calling",
                    )
                return self._status_result(
                    "whatsapp_call",
                    f"WhatsApp Desktop opened, but Jarvis could not verify the {mode} call button for {contact}. I did not start the call.",
                    success=False,
                    status="whatsapp_desktop_unverified",
                )

            web = self._open_whatsapp_web()
            if not bool(web.get("success")):
                return web

            return self._status_result(
                "whatsapp_call",
                f"WhatsApp Web fallback is available, but Jarvis could not verify the {mode} call selector for {contact}. I did not start the call.",
                success=False,
                status="whatsapp_call_unverified",
            )


    def _click_verified_whatsapp_call_button(self, contact: str, mode: str) -> bool:
            return bool(self.whatsapp_desktop.click_call_button(mode))


    def _end_whatsapp_call(self) -> Dict[str, object]:
            desktop_result = self.whatsapp_desktop.end_call()
            if bool(desktop_result.get("success")):
                self._active_whatsapp_call = None
                return self._status_result(
                    "end_whatsapp_call",
                    "Ended the WhatsApp call.",
                    success=True,
                    status="whatsapp_call_ended",
                )
            if str(desktop_result.get("status") or "") != "whatsapp_desktop_unavailable":
                return self._status_result(
                    "end_whatsapp_call",
                    str(desktop_result.get("message") or "Jarvis could not verify an active WhatsApp call. I did not click anything."),
                    success=False,
                    status=str(desktop_result.get("status") or "whatsapp_end_call_unverified"),
                )
            web = self._open_whatsapp_web()
            if not bool(web.get("success")):
                return web
            return self._status_result(
                "end_whatsapp_call",
                "WhatsApp Web is open, but Jarvis could not verify an active call end button. I did not click anything.",
                success=False,
                status="whatsapp_end_call_unverified",
            )


