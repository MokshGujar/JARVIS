from __future__ import annotations

import hashlib
import secrets
import time
import logging
from typing import Any

from config import (
    FACE_AUTH_LOCK_FAILURE_COUNT,
    FACE_AUTH_LOCK_SECONDS,
    FACE_LIVENESS_REQUIRE_FOR_STEP_UP,
    FACE_LIVENESS_STEP_UP_TOKEN_TTL_SECONDS,
    FACE_STEP_UP_MAX_ATTEMPTS_PER_MIN,
)
from app.services.command_risk_service import CommandRiskResult, CommandRiskService
from app.services.face_identity_service import AttemptLimiter, FaceIdentityService

logger = logging.getLogger(__name__)


class StepUpAuthService:
    def __init__(
        self,
        *,
        face_identity_service: FaceIdentityService,
        command_risk_service: CommandRiskService,
        token_ttl_seconds: int = FACE_LIVENESS_STEP_UP_TOKEN_TTL_SECONDS,
    ) -> None:
        self.face_identity_service = face_identity_service
        self.command_risk_service = command_risk_service
        self.token_ttl_seconds = token_ttl_seconds
        self._pending: dict[str, dict[str, Any]] = {}
        self._tokens: dict[str, dict[str, Any]] = {}
        self._limiter = AttemptLimiter(
            max_per_minute=FACE_STEP_UP_MAX_ATTEMPTS_PER_MIN,
            lock_failure_count=FACE_AUTH_LOCK_FAILURE_COUNT,
            lock_seconds=FACE_AUTH_LOCK_SECONDS,
        )

    def start(self, *, face_session_id: str, command_text: str, command_action: str = "") -> dict[str, Any]:
        risk = self.command_risk_service.classify(command_text, command_action=command_action)
        if not risk.step_up_required:
            return {"step_up_required": False, "risk": risk.as_dict()}
        if not self.face_identity_service.validate_session(face_session_id):
            return {"step_up_required": True, "started": False, "reason": "face_session_required", "risk": risk.as_dict()}
        challenge_id = secrets.token_urlsafe(24)
        self._pending[challenge_id] = {
            "face_session_id": face_session_id,
            "risk": risk.as_dict(),
            "command_hash": risk.command_hash(),
            "created_at": time.time(),
        }
        return {"step_up_required": True, "started": True, "challenge_id": challenge_id, "risk": risk.as_dict()}

    def verify(
        self,
        *,
        challenge_id: str,
        face_session_id: str,
        command_text: str,
        command_action: str,
        frames: list[str],
        client_id: str = "default",
    ) -> dict[str, Any]:
        allowed, limiter_reason, retry_after = self._limiter.check(client_id)
        if not allowed:
            return {"verified": False, "status": "rejected", "reason": limiter_reason, "retry_after_seconds": retry_after, "token_issued": False}
        pending = self._pending.get(challenge_id)
        risk = self.command_risk_service.classify(command_text, command_action=command_action)
        if not pending:
            self._limiter.record_failure(client_id)
            return {"verified": False, "status": "rejected", "reason": "challenge_not_found", "token_issued": False, "risk": risk.as_dict()}
        if pending.get("face_session_id") != face_session_id or pending.get("command_hash") != risk.command_hash():
            self._limiter.record_failure(client_id)
            return {"verified": False, "status": "rejected", "reason": "challenge_mismatch", "token_issued": False, "risk": risk.as_dict()}
        if not self.face_identity_service.validate_session(face_session_id):
            self._limiter.record_failure(client_id)
            return {"verified": False, "status": "rejected", "reason": "face_session_expired", "token_issued": False, "risk": risk.as_dict()}

        verification = self.face_identity_service.verify_frames(
            frames,
            client_id=f"stepup:{client_id}",
            issue_session=False,
            require_liveness=FACE_LIVENESS_REQUIRE_FOR_STEP_UP,
        )
        if verification.get("status") != "verified":
            self._limiter.record_failure(client_id)
            logger.info(
                "step_up denied action=%s risk=%s reason=%s live=%s similarity=%s",
                risk.command_action,
                risk.risk_level,
                verification.get("reason"),
                verification.get("liveness", {}).get("is_live"),
                verification.get("cosine_similarity"),
            )
            return {**verification, "token_issued": False, "risk": risk.as_dict(), "step_up_decision": "rejected"}

        self._limiter.record_success(client_id)
        token = secrets.token_urlsafe(32)
        self._tokens[token] = {
            "face_session_id": face_session_id,
            "command_hash": risk.command_hash(),
            "command_action": risk.command_action,
            "risk": risk.as_dict(),
            "issued_at": time.time(),
            "expires_at": time.time() + self.token_ttl_seconds,
            "consumed": False,
        }
        self._pending.pop(challenge_id, None)
        logger.info(
            "step_up verified action=%s risk=%s similarity=%.4f token_issued=true",
            risk.command_action,
            risk.risk_level,
            float(verification.get("cosine_similarity", 0.0)),
        )
        return {**verification, "step_up_token": token, "token_issued": True, "risk": risk.as_dict(), "step_up_decision": "verified"}

    def consume(self, *, token: str | None, face_session_id: str | None, risk: CommandRiskResult) -> tuple[bool, str]:
        if not token:
            return False, "step_up_token_required"
        payload = self._tokens.get(token)
        if not payload:
            return False, "step_up_token_not_found"
        if payload.get("consumed"):
            return False, "step_up_token_reused"
        if float(payload.get("expires_at", 0.0)) <= time.time():
            self._tokens.pop(token, None)
            return False, "step_up_token_expired"
        if payload.get("face_session_id") != face_session_id:
            return False, "step_up_session_mismatch"
        if payload.get("command_hash") != risk.command_hash():
            return False, "step_up_command_mismatch"
        payload["consumed"] = True
        return True, "ok"

    def invalidate_all(self) -> None:
        self._pending.clear()
        self._tokens.clear()
