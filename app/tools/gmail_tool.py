from __future__ import annotations

import hashlib
import logging
from typing import Any

from app.connectors.gmail_connector import GmailConnector
from app.orchestrator.action_plan import ActionPlan, ActionStep
from app.orchestrator.tool_executor import ToolExecutor
from app.orchestrator.tool_registry import ToolRegistry
from app.services.command_risk_service import CommandRiskService
from app.services.contact_resolution_service import ContactResolutionService
from app.tools.base import ToolContext, ToolRisk
from app.tools.email_command_parser import EmailCommand, EmailCommandParser

logger = logging.getLogger("J.A.R.V.I.S")


class GmailTool:
    name = "gmail"

    def __init__(
        self,
        connector: Any | None = None,
        *,
        contact_resolution_service: ContactResolutionService | None = None,
        parser: EmailCommandParser | None = None,
        risk_service: CommandRiskService | None = None,
    ) -> None:
        self.connector = connector or GmailConnector()
        self.contact_resolution_service = contact_resolution_service
        self.parser = parser or EmailCommandParser()
        self.risk_service = risk_service or CommandRiskService()

    def can_handle(self, intent: str) -> bool:
        return str(intent or "").strip().lower() in {"gmail", "email", "mail", "communication"}

    def classify_risk(self, command: str) -> ToolRisk:
        risk = self.risk_service.classify(command, command_action="gmail")
        return ToolRisk(level=risk.risk_level, step_up_required=risk.step_up_required, reasons=list(risk.reasons))

    def policy_args(self, action: str, args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        parsed = self._parsed(context, action, args)
        recipient = str(args.get("recipient") or parsed.recipient).strip()
        body = str(args.get("body") or parsed.body).strip()
        explicit_email = self.parser.explicit_email(recipient)
        resolved = self._resolve_recipient(recipient, required_channel="email") if recipient and not explicit_email else {}
        selected = dict(resolved.get("selected_contact") or {})
        email_address = str(args.get("email_address") or explicit_email or selected.get("email_address") or "").strip()
        return {
            "user_initiated": str(context.source or "").lower() in {"user", "text", "voice"},
            "fresh_user_command": bool(args.get("fresh_user_command", True)) and not bool(context.metadata.get("recovered_pending") or context.payload.get("recovered_pending")),
            "direct_user_requested": bool(args.get("direct_user_requested", True)),
            "single_recipient": bool(email_address) and "," not in recipient and ";" not in recipient,
            "recipient_confident": bool(args.get("recipient_confident")) or bool(explicit_email) or resolved.get("status") == "matched",
            "explicit_email": bool(explicit_email),
            "has_body": bool(body) or parsed.action in {"get_unread_count", "search_emails", "read_latest_email"},
            "bulk": False,
        }

    def execute(self, context: ToolContext) -> dict[str, Any]:
        action = str(context.payload.get("action") or "").strip()
        args = dict(context.payload.get("args") or {})
        parsed = self._parsed(context, action, args)
        action = action or parsed.action
        logger.info(
            "[GMAIL_PARSE] action=%s recipient_hash=%s has_body=%s",
            action,
            self._hash(args.get("recipient") or parsed.recipient),
            bool(args.get("body") or parsed.body),
        )

        if action in {"send_email", "draft_email", "reply_email", "search_emails", "read_latest_email"}:
            if str(args.get("email_address") or "").strip():
                recipient_email = str(args.get("email_address") or "").strip()
            else:
                recipient_result = self._recipient_payload(args.get("recipient") or parsed.recipient, required_channel="email")
                if not recipient_result.get("success"):
                    return recipient_result
                recipient_email = str(recipient_result["email_address"])
        else:
            recipient_email = ""

        if action == "prepare_email":
            return self._prepare_email_action(context, parsed)

        status = self.connector.status() if hasattr(self.connector, "status") else {"available": bool(self.connector.available())}
        if not bool(status.get("available")):
            logger.info("[GMAIL_EXEC] action=%s status=unavailable reason=connector_not_configured", action)
            return {
                "success": False,
                "action": "gmail_unavailable",
                "message": str(status.get("message") or "Gmail is not configured. Connect Gmail before using email actions."),
                "status": str(status.get("status") or "not_configured"),
            }

        body = str(args.get("body") or parsed.body).strip()
        subject = str(args.get("subject") or parsed.subject or "Message from Jarvis").strip()
        try:
            logger.info("[GMAIL_EXEC] action=%s status=started reason=connector_available", action)
            if action == "send_email":
                if not body:
                    return self._clarify("gmail_body_required", "What should I say in the email?")
                result = self.connector.send_email(to=recipient_email, subject=subject, body=body)
            elif action == "draft_email":
                if not body:
                    return self._clarify("gmail_body_required", "What should I put in the draft?")
                result = self.connector.create_draft(to=recipient_email, subject=subject, body=body)
            elif action == "get_unread_count":
                result = self.connector.get_unread_count()
            elif action == "search_emails":
                result = self.connector.search_emails(query=f"from:{recipient_email}")
            elif action == "read_latest_email":
                result = self.connector.read_latest_email(from_email=recipient_email)
            elif action == "reply_email":
                if not body:
                    return self._clarify("gmail_body_required", "What should I say in the reply?")
                result = self.connector.reply_latest_email(from_email=recipient_email, body=body)
            else:
                return {"success": False, "action": "unsupported", "message": "That Gmail action is not supported yet."}
        except Exception:
            logger.info("[GMAIL_EXEC] action=%s status=failed reason=connector_error", action)
            return {"success": False, "action": "gmail_failed", "message": "Gmail failed while running that action."}

        ok = bool(result.get("success")) if isinstance(result, dict) else False
        logger.info("[GMAIL_EXEC] action=%s status=%s reason=connector_result", action, "success" if ok else "failed")
        return dict(result) if isinstance(result, dict) else {"success": False, "action": action, "message": "Gmail returned an invalid response."}

    def _prepare_email_action(self, context: ToolContext, parsed: EmailCommand) -> dict[str, Any]:
        if parsed.action == "get_unread_count":
            return self._execute_resolved_action(context, parsed, {})
        recipient_result = self._recipient_payload(parsed.recipient, required_channel="email")
        if not recipient_result.get("success"):
            return recipient_result
        args = {
            "recipient": parsed.recipient,
            "email_address": str(recipient_result["email_address"]),
            "body": parsed.body,
            "subject": parsed.subject or "Message from Jarvis",
            "direct_user_requested": True,
            "recipient_confident": True,
            "fresh_user_command": True,
            "single_recipient": True,
            "bulk": False,
        }
        if parsed.action in {"send_email", "draft_email", "reply_email"} and not parsed.body.strip():
            return self._clarify("gmail_body_required", "What should I say in the email?")
        return self._execute_resolved_action(context, parsed, args)

    def _execute_resolved_action(self, context: ToolContext, parsed: EmailCommand, args: dict[str, Any]) -> dict[str, Any]:
        logger.info(
            "[MANUAL_LIVE_VALIDATION] mode=%s action=gmail status=ready reason=fresh_explicit_user_command",
            "enabled" if str(context.source or "").lower() in {"user", "text", "voice"} else "disabled",
        )
        executor = ToolExecutor(registry=ToolRegistry([self]), enforce_policy=True)
        result = executor.execute(
            ActionPlan(
                original_text=context.command,
                steps=[
                    ActionStep(
                        step_id="step1",
                        tool_name="gmail",
                        intent="gmail",
                        action=parsed.action,
                        args=args,
                    )
                ],
                is_multistep=False,
            ),
            ToolContext(
                command=context.command,
                intent="gmail",
                session_id=context.session_id,
                request_id=context.request_id,
                payload={"turn_id": context.request_id} if context.request_id else {},
                source=context.source,
                security_state=dict(context.security_state),
            ),
        )
        if isinstance(result, dict) and isinstance(result.get("policy"), dict):
            result["direct_policy"] = dict(result["policy"])
        return result

    def _parsed(self, context: ToolContext, action: str, args: dict[str, Any]) -> EmailCommand:
        parsed = self.parser.parse(context.command) or EmailCommand(action or "unsupported")
        return EmailCommand(
            action or parsed.action,
            recipient=str(args.get("recipient") or parsed.recipient),
            body=str(args.get("body") or parsed.body),
            subject=str(args.get("subject") or parsed.subject),
            query=str(args.get("query") or parsed.query),
        )

    def _recipient_payload(self, recipient: str, *, required_channel: str) -> dict[str, Any]:
        explicit = self.parser.explicit_email(recipient)
        if explicit:
            logger.info("[GMAIL_CONTACT] status=matched candidate_count=1")
            return {"success": True, "email_address": explicit, "display_name": explicit, "contact_hash": self._hash(explicit)}
        resolved = self._resolve_recipient(recipient, required_channel=required_channel)
        logger.info("[GMAIL_CONTACT] status=%s candidate_count=%s", resolved.get("status"), resolved.get("candidate_count", 0))
        status = resolved.get("status")
        if status == "matched":
            selected = dict(resolved.get("selected_contact") or {})
            email_address = str(selected.get("email_address") or "").strip()
            if email_address:
                return {"success": True, "email_address": email_address, "display_name": selected.get("display_name"), "contact_hash": resolved.get("contact_hash")}
        if status == "missing_channel":
            return self._clarify("gmail_email_missing", f"I found {recipient}, but that contact has no email address.")
        if status == "ambiguous":
            return self._clarify("gmail_contact_ambiguous", str(resolved.get("message") or "Which contact did you mean?"))
        if status == "weak_match":
            return self._clarify("gmail_contact_weak_match", str(resolved.get("message") or "Please confirm the exact contact."))
        return self._clarify("gmail_contact_not_found", f"I could not find an email address for {recipient}.")

    def _resolve_recipient(self, recipient: str, *, required_channel: str) -> dict[str, Any]:
        if not self.contact_resolution_service:
            return {"status": "not_found", "candidate_count": 0}
        return self.contact_resolution_service.resolve(recipient, source="gmail", required_channel=required_channel)

    @staticmethod
    def _clarify(action: str, message: str) -> dict[str, Any]:
        return {"success": False, "action": action, "message": message, "requires_followup": True, "status": "clarification_required"}

    @staticmethod
    def _hash(value: object) -> str:
        normalized = " ".join(str(value or "").strip().lower().split())
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16] if normalized else ""
