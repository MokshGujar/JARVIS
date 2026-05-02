from __future__ import annotations

import hashlib
import secrets
import time
import logging
from collections import defaultdict, deque
from typing import Any, Callable

from config import (
    BASE_DIR,
    FACE_AUTH_LOCK_FAILURE_COUNT,
    FACE_AUTH_LOCK_SECONDS,
    FACE_AUTH_MAX_ATTEMPTS_PER_MIN,
    FACE_AUTH_SESSION_TTL_SECONDS,
    FACE_IDENTITY_BACKEND,
    FACE_IDENTITY_MAX_STORED_SAMPLES,
    FACE_IDENTITY_PREFERRED_SAMPLES,
    FACE_IDENTITY_REQUIRED_SAMPLES,
    FACE_IDENTITY_UNCERTAIN_THRESHOLD,
    FACE_IDENTITY_VERIFIED_THRESHOLD,
    FACE_LIVENESS_ENABLED,
    FACE_LIVENESS_REQUIRE_FOR_NORMAL_AUTH,
)
from app.adapters.face.face_detector import FaceDetector
from app.adapters.face.face_embedder import FaceEmbedder
from app.adapters.face.face_liveness import LivenessResult
from app.adapters.face.face_preprocessor import FacePreprocessor
from app.adapters.face.face_quality import FaceQualityValidator
from app.adapters.face.face_recognition_backend import InsightFaceRecognitionBackend, UnavailableFaceRecognitionBackend
from app.core.face_profile_store import FaceProfileStore
from app.core.face_vectors import cosine_similarity, normalize_embedding
from app.services.liveness_service import LivenessService

logger = logging.getLogger(__name__)


class AttemptLimiter:
    def __init__(self, *, max_per_minute: int, lock_failure_count: int, lock_seconds: int) -> None:
        self.max_per_minute = max_per_minute
        self.lock_failure_count = lock_failure_count
        self.lock_seconds = lock_seconds
        self._attempts: dict[str, deque[float]] = defaultdict(deque)
        self._failures: dict[str, int] = defaultdict(int)
        self._locked_until: dict[str, float] = {}

    def check(self, key: str) -> tuple[bool, str, int]:
        now = time.time()
        locked_until = self._locked_until.get(key, 0.0)
        if locked_until > now:
            return False, "locked", int(locked_until - now)
        attempts = self._attempts[key]
        while attempts and now - attempts[0] > 60:
            attempts.popleft()
        if len(attempts) >= self.max_per_minute:
            return False, "rate_limited", 60
        attempts.append(now)
        return True, "ok", 0

    def record_success(self, key: str) -> None:
        self._failures[key] = 0
        self._locked_until.pop(key, None)

    def record_failure(self, key: str) -> None:
        self._failures[key] += 1
        if self._failures[key] >= self.lock_failure_count:
            self._locked_until[key] = time.time() + self.lock_seconds
            self._failures[key] = 0


class FaceIdentityService:
    profile_id = "owner-default"
    user_name = "Moksh"

    def __init__(
        self,
        *,
        backend: Any | None = None,
        preprocessor: FacePreprocessor | None = None,
        profile_store: FaceProfileStore | None = None,
        liveness_service: LivenessService | None = None,
        session_ttl_seconds: int = FACE_AUTH_SESSION_TTL_SECONDS,
    ) -> None:
        self.data_dir = BASE_DIR / "database" / "face_identity"
        self.backend = backend or self._build_backend()
        self.preprocessor = preprocessor or FacePreprocessor()
        self.detector = FaceDetector(self.backend)
        self.embedder = FaceEmbedder(self.backend)
        self.quality_validator = FaceQualityValidator()
        self.liveness_service = liveness_service or LivenessService(detector=self.detector, quality_validator=self.quality_validator)
        self.profile_store = profile_store or FaceProfileStore(self.data_dir, profile_id=self.profile_id, user_name=self.user_name)
        self.session_ttl_seconds = session_ttl_seconds
        self._sessions: dict[str, dict[str, Any]] = {}
        self._profile_delete_callbacks: list[Callable[[], None]] = []
        self._limiter = AttemptLimiter(
            max_per_minute=FACE_AUTH_MAX_ATTEMPTS_PER_MIN,
            lock_failure_count=FACE_AUTH_LOCK_FAILURE_COUNT,
            lock_seconds=FACE_AUTH_LOCK_SECONDS,
        )

    def register_profile_delete_callback(self, callback: Callable[[], None]) -> None:
        self._profile_delete_callbacks.append(callback)

    def status(self) -> dict[str, Any]:
        profile = self.profile_store.load_profile() or {}
        backend_status = self.backend.status() if hasattr(self.backend, "status") else {}
        accepted_samples = int(profile.get("accepted_samples", 0))
        required_samples = max(int(profile.get("required_samples", 0) or 0), FACE_IDENTITY_REQUIRED_SAMPLES)
        return {
            "available": bool(backend_status.get("available", False)),
            "backend": backend_status.get("backend", FACE_IDENTITY_BACKEND),
            "model_name": backend_status.get("model_name", ""),
            "embedding_dim": int(profile.get("embedding_dim") or backend_status.get("embedding_dim") or 0),
            "profile_exists": bool(profile),
            "profile_enrolled": self._profile_is_currently_enrolled(profile),
            "profile_id": profile.get("profile_id", self.profile_id),
            "user_name": profile.get("user_name", self.user_name),
            "required_samples": required_samples,
            "preferred_samples": int(profile.get("preferred_samples", FACE_IDENTITY_PREFERRED_SAMPLES)),
            "max_stored_samples": int(profile.get("max_stored_samples", FACE_IDENTITY_MAX_STORED_SAMPLES)),
            "accepted_samples": accepted_samples,
            "threshold_verified": float(profile.get("threshold_verified", FACE_IDENTITY_VERIFIED_THRESHOLD)),
            "threshold_uncertain": float(profile.get("threshold_uncertain", FACE_IDENTITY_UNCERTAIN_THRESHOLD)),
            "liveness_enabled": FACE_LIVENESS_ENABLED,
            "active_sessions": len(self._sessions),
            "backend_reason": backend_status.get("reason", ""),
        }

    def verify_frames(
        self,
        frame_base64_list: list[str],
        *,
        client_id: str = "default",
        issue_session: bool = True,
        require_liveness: bool = FACE_LIVENESS_REQUIRE_FOR_NORMAL_AUTH,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        allowed, limiter_reason, retry_after = self._limiter.check(client_id)
        if not allowed:
            return self._verification_payload(
                "rejected",
                limiter_reason,
                0.0,
                {},
                None,
                retry_after=retry_after,
                request_id=request_id,
            )

        profile = self.profile_store.load_profile()
        if not self._profile_is_currently_enrolled(profile or {}):
            self._limiter.record_failure(client_id)
            return self._verification_payload("rejected", "not_enrolled", 0.0, {}, None, request_id=request_id)

        try:
            frames = self.preprocessor.decode_many(frame_base64_list)
            if not frames:
                raise ValueError("missing_frames")
            liveness, detections_by_frame, quality_by_frame = self.liveness_service.evaluate(frames)
            first_quality = quality_by_frame[0].as_dict() if quality_by_frame else {}
            if require_liveness and not liveness.is_live:
                self._limiter.record_failure(client_id)
                return self._verification_payload(
                    "rejected",
                    f"liveness_{liveness.reason}",
                    0.0,
                    first_quality,
                    liveness,
                    request_id=request_id,
                )
            detections = detections_by_frame[0] if detections_by_frame else []
            if not detections or len(detections) != 1:
                self._limiter.record_failure(client_id)
                return self._verification_payload(
                    "rejected",
                    "face_count_invalid",
                    0.0,
                    first_quality,
                    liveness,
                    request_id=request_id,
                )
            quality = quality_by_frame[0] if quality_by_frame else self.quality_validator.validate(frames[0], detections)
            if not quality.passed:
                self._limiter.record_failure(client_id)
                return self._verification_payload(
                    "rejected",
                    quality.reason,
                    0.0,
                    quality.as_dict(),
                    liveness,
                    request_id=request_id,
                )
            embedding = normalize_embedding(self.embedder.embed(frames[0], detections[0]))
        except Exception as exc:
            self._limiter.record_failure(client_id)
            return self._verification_payload(
                "rejected",
                str(exc) or "face_verify_failed",
                0.0,
                {},
                None,
                request_id=request_id,
            )

        centroid = normalize_embedding(profile.get("centroid_embedding") or [])
        score = cosine_similarity(centroid, embedding)
        verified_threshold = float(profile.get("threshold_verified", FACE_IDENTITY_VERIFIED_THRESHOLD))
        uncertain_threshold = float(profile.get("threshold_uncertain", FACE_IDENTITY_UNCERTAIN_THRESHOLD))
        if score >= verified_threshold:
            status = "verified"
            reason = "verified_match"
        elif score >= uncertain_threshold:
            status = "uncertain"
            reason = "uncertain_match"
        else:
            status = "rejected"
            reason = "rejected_match"

        if status == "verified":
            self._limiter.record_success(client_id)
        else:
            self._limiter.record_failure(client_id)

        session_id = self._issue_session(profile, score) if status == "verified" and issue_session else None
        payload = self._verification_payload(
            status,
            reason,
            score,
            quality.as_dict(),
            liveness,
            session_id=session_id,
            request_id=request_id,
        )
        payload["processing_time_ms"] = int((time.perf_counter() - started) * 1000)
        self._record_history(payload, client_id=client_id, request_id=request_id)
        logger.info(
            "face_verify client=%s status=%s reason=%s similarity=%.4f live=%s liveness_confidence=%.4f",
            client_id,
            status,
            reason,
            score,
            bool(liveness.is_live if liveness else False),
            float(liveness.confidence if liveness else 0.0),
        )
        return payload

    def validate_session(self, session_id: str | None) -> bool:
        if not session_id:
            return False
        payload = self._sessions.get(session_id)
        if not payload:
            return False
        if float(payload.get("expires_at", 0.0)) <= time.time():
            self._sessions.pop(session_id, None)
            return False
        return True

    def delete_profile(self) -> dict[str, Any]:
        self.profile_store.delete_profile()
        self.invalidate_sessions()
        for callback in self._profile_delete_callbacks:
            callback()
        return {"deleted": True, **self.status()}

    def invalidate_sessions(self) -> None:
        self._sessions.clear()

    def _build_backend(self):
        if FACE_IDENTITY_BACKEND == "insightface":
            backend = InsightFaceRecognitionBackend()
            if backend.status().get("available"):
                return backend
            return UnavailableFaceRecognitionBackend(backend.status().get("reason") or "insightface_unavailable")
        return UnavailableFaceRecognitionBackend(f"Face backend '{FACE_IDENTITY_BACKEND}' is not configured.")

    def _profile_is_currently_enrolled(self, profile: dict[str, Any]) -> bool:
        if not profile or not profile.get("is_active") or not profile.get("centroid_embedding"):
            return False
        return int(profile.get("accepted_samples", 0) or 0) >= FACE_IDENTITY_REQUIRED_SAMPLES

    def _issue_session(self, profile: dict[str, Any], score: float) -> str:
        session_id = secrets.token_urlsafe(32)
        now = time.time()
        self._sessions[session_id] = {
            "profile_id": profile.get("profile_id", self.profile_id),
            "issued_at": now,
            "expires_at": now + self.session_ttl_seconds,
            "similarity": float(score),
        }
        return session_id

    def _verification_payload(
        self,
        status: str,
        reason: str,
        similarity: float,
        quality: dict[str, Any],
        liveness: LivenessResult | None,
        *,
        session_id: str | None = None,
        retry_after: int = 0,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        return {
            "verified": status == "verified",
            "allowed": status == "verified",
            "status": status,
            "reason": reason,
            "confidence": float(similarity),
            "cosine_similarity": float(similarity),
            "threshold_verified": FACE_IDENTITY_VERIFIED_THRESHOLD,
            "threshold_uncertain": FACE_IDENTITY_UNCERTAIN_THRESHOLD,
            "quality": quality,
            "liveness": liveness.as_dict() if liveness else {"is_live": False, "confidence": 0.0, "reason": reason, "checks": {}},
            "face_session_id": session_id or "",
            "retry_after_seconds": retry_after,
            "request_id": request_id or "",
        }

    def _record_history(self, payload: dict[str, Any], *, client_id: str, request_id: str | None) -> None:
        self.profile_store.append_history(
            {
                "request_id": request_id or "",
                "client_id_hash": hashlib.sha256(client_id.encode("utf-8")).hexdigest()[:16],
                "status": payload.get("status"),
                "reason": payload.get("reason"),
                "cosine_similarity": payload.get("cosine_similarity"),
                "quality": payload.get("quality", {}),
                "liveness": payload.get("liveness", {}),
                "created_at": time.time(),
            }
        )
