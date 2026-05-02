from __future__ import annotations

import secrets
import time
from typing import Any

from config import (
    FACE_ENROLLMENT_CONSISTENCY_MIN_SAMPLES,
    FACE_ENROLLMENT_FRAME_MAX_WIDTH,
    FACE_ENROLLMENT_MAX_CENTROID_DISTANCE,
    FACE_ENROLLMENT_MAX_MODEL_FRAMES_PER_BATCH,
    FACE_ENROLLMENT_MIN_DIVERSITY_DISTANCE,
    FACE_IDENTITY_BACKEND,
    FACE_IDENTITY_MAX_STORED_SAMPLES,
    FACE_IDENTITY_PREFERRED_SAMPLES,
    FACE_IDENTITY_REQUIRED_SAMPLES,
    FACE_IDENTITY_UNCERTAIN_THRESHOLD,
    FACE_IDENTITY_VERIFIED_THRESHOLD,
)
from app.core.face_vectors import cosine_similarity, mean_embedding, normalize_embedding
from app.services.face_identity_service import FaceIdentityService


class FaceEnrollmentService:
    def __init__(self, face_identity_service: FaceIdentityService) -> None:
        self.face_identity_service = face_identity_service
        self._sessions: dict[str, dict[str, Any]] = {}

    def start(self, *, user_name: str = "Moksh", replace_existing: bool = True) -> dict[str, Any]:
        if replace_existing:
            self.face_identity_service.delete_profile()
        session_id = secrets.token_urlsafe(24)
        self._sessions[session_id] = {
            "user_name": user_name or self.face_identity_service.user_name,
            "sample_embeddings": [],
            "sample_quality": [],
            "rejected_count_total": 0,
            "duplicate_rejection_count": 0,
            "inconsistent_rejection_count": 0,
            "quality_failed_count_total": 0,
            "liveness_failed_count_total": 0,
            "reason_counts_total": {},
            "created_at": time.time(),
        }
        return {
            "enrollment_session_id": session_id,
            "required_samples": FACE_IDENTITY_REQUIRED_SAMPLES,
            "preferred_samples": FACE_IDENTITY_PREFERRED_SAMPLES,
            "max_stored_samples": FACE_IDENTITY_MAX_STORED_SAMPLES,
            "accepted_samples": 0,
            "can_complete": False,
            "can_complete_early": False,
            "auto_complete": False,
            "status": "collecting",
        }

    def add_sample(self, enrollment_session_id: str, frames: list[str]) -> dict[str, Any]:
        payload = self.add_batch(enrollment_session_id, frames)
        payload["accepted"] = payload.get("accepted_count", 0) > 0
        payload["reason"] = "accepted" if payload["accepted"] else payload.get("last_rejection_reason") or "sample_rejected"
        payload["quality"] = payload.get("last_quality", {})
        payload["liveness"] = payload.get("last_liveness", {})
        payload["can_complete_early"] = payload.get("auto_complete", False)
        return payload

    def add_batch(self, enrollment_session_id: str, frames: list[str]) -> dict[str, Any]:
        session = self._sessions.get(enrollment_session_id)
        if not session:
            return self._batch_response(
                None,
                accepted_count=0,
                rejected_count=len(frames or []),
                duplicate_count=0,
                quality_failed_count=0,
                inconsistent_count=0,
                liveness_failed_count=0,
                last_rejection_reason="enrollment_session_not_found",
                guidance="Start a fresh enrollment session",
            )
        if len(session["sample_embeddings"]) >= FACE_IDENTITY_MAX_STORED_SAMPLES:
            return self._batch_response(
                session,
                accepted_count=0,
                rejected_count=len(frames or []),
                duplicate_count=0,
                quality_failed_count=0,
                inconsistent_count=0,
                liveness_failed_count=0,
                last_rejection_reason="max_samples_reached",
                guidance="Enough samples captured",
            )

        frame_results = self._extract_batch_frame_results(frames)
        accepted_count = 0
        rejected_count = 0
        duplicate_count = 0
        quality_failed_count = 0
        inconsistent_count = 0
        liveness_failed_count = 0
        reason_counts: dict[str, int] = {}
        last_quality: dict[str, Any] = {}
        last_liveness: dict[str, Any] = {}
        last_rejection_reason = ""
        min_distance_to_existing_sample: float | None = None
        last_centroid_distance: float | None = None

        for result in frame_results:
            last_quality = result.get("quality", last_quality)
            last_liveness = result.get("liveness", last_liveness)
            if len(session["sample_embeddings"]) >= FACE_IDENTITY_MAX_STORED_SAMPLES:
                rejected_count += 1
                last_rejection_reason = "max_samples_reached"
                self._increment_reason(reason_counts, last_rejection_reason)
                continue
            if not result.get("accepted"):
                rejected_count += 1
                reason = str(result.get("reason") or "sample_rejected")
                last_rejection_reason = reason
                self._increment_reason(reason_counts, reason)
                if self._is_quality_failure(reason):
                    quality_failed_count += 1
                if self._is_liveness_failure(reason):
                    liveness_failed_count += 1
                continue

            embedding = normalize_embedding(result.get("embedding") or [])
            diversity, diversity_stats = self._embedding_diversity_decision(session["sample_embeddings"], embedding)
            if diversity_stats.get("min_distance_to_existing_sample") is not None:
                value = float(diversity_stats["min_distance_to_existing_sample"])
                min_distance_to_existing_sample = (
                    value
                    if min_distance_to_existing_sample is None
                    else min(min_distance_to_existing_sample, value)
                )
            if diversity_stats.get("centroid_distance") is not None:
                last_centroid_distance = float(diversity_stats["centroid_distance"])
            if diversity == "duplicate":
                rejected_count += 1
                duplicate_count += 1
                last_rejection_reason = "duplicate_embedding"
                self._increment_reason(reason_counts, last_rejection_reason)
                continue
            if diversity == "inconsistent":
                rejected_count += 1
                inconsistent_count += 1
                last_rejection_reason = "inconsistent_embedding"
                self._increment_reason(reason_counts, last_rejection_reason)
                continue

            session["sample_embeddings"].append(embedding)
            session["sample_quality"].append(
                {
                    "quality": result.get("quality", {}),
                    "liveness_confidence": result.get("liveness", {}).get("confidence", 0.0),
                    "liveness_reason": result.get("liveness", {}).get("reason", ""),
                    "liveness_checks": result.get("liveness", {}).get("checks", {}),
                }
            )
            accepted_count += 1

        self._merge_session_counts(
            session,
            accepted_count=accepted_count,
            rejected_count=rejected_count,
            duplicate_count=duplicate_count,
            inconsistent_count=inconsistent_count,
            quality_failed_count=quality_failed_count,
            liveness_failed_count=liveness_failed_count,
            reason_counts=reason_counts,
        )
        return self._batch_response(
            session,
            accepted_count=accepted_count,
            rejected_count=rejected_count,
            duplicate_count=duplicate_count,
            quality_failed_count=quality_failed_count,
            inconsistent_count=inconsistent_count,
            liveness_failed_count=liveness_failed_count,
            reason_counts=reason_counts,
            last_rejection_reason=last_rejection_reason,
            last_quality=last_quality,
            last_liveness=last_liveness,
            min_distance_to_existing_sample=min_distance_to_existing_sample,
            last_centroid_distance=last_centroid_distance,
            guidance=self._guidance(
                reason_counts,
                last_rejection_reason,
                quality_failed_count,
                duplicate_count,
                inconsistent_count,
                liveness_failed_count,
                accepted_count,
            ),
        )

    def complete(self, enrollment_session_id: str) -> dict[str, Any]:
        session = self._sessions.get(enrollment_session_id)
        if not session:
            return {"enrolled": False, "status": "rejected", "reason": "enrollment_session_not_found"}
        embeddings = session.get("sample_embeddings", [])
        centroid = mean_embedding(embeddings)
        embedding_stability = self._calculate_embedding_stability(embeddings)
        consistency_passed = self._consistency_passed(embeddings)
        is_active = bool(centroid) and len(embeddings) >= FACE_IDENTITY_REQUIRED_SAMPLES and consistency_passed
        profile = {
            "profile_id": self.face_identity_service.profile_id,
            "user_name": session.get("user_name", self.face_identity_service.user_name),
            "is_active": is_active,
            "recognition_backend": FACE_IDENTITY_BACKEND,
            "embedding_model": getattr(self.face_identity_service.backend, "model_name", ""),
            "embedding_dim": len(centroid),
            "required_samples": FACE_IDENTITY_REQUIRED_SAMPLES,
            "preferred_samples": FACE_IDENTITY_PREFERRED_SAMPLES,
            "max_stored_samples": FACE_IDENTITY_MAX_STORED_SAMPLES,
            "accepted_samples": len(embeddings),
            "threshold_verified": FACE_IDENTITY_VERIFIED_THRESHOLD,
            "threshold_uncertain": FACE_IDENTITY_UNCERTAIN_THRESHOLD,
            "centroid_embedding": centroid,
            "sample_embeddings": embeddings[:FACE_IDENTITY_MAX_STORED_SAMPLES],
            "sample_quality": session.get("sample_quality", [])[:FACE_IDENTITY_MAX_STORED_SAMPLES],
            "profile_version": 2,
        }
        self.face_identity_service.profile_store.save_profile(profile)
        if is_active:
            self._sessions.pop(enrollment_session_id, None)
        return {
            "enrolled": is_active,
            "status": "active" if is_active else "collecting",
            "accepted_samples": len(embeddings),
            "required_samples": FACE_IDENTITY_REQUIRED_SAMPLES,
            "preferred_samples": FACE_IDENTITY_PREFERRED_SAMPLES,
            "max_stored_samples": FACE_IDENTITY_MAX_STORED_SAMPLES,
            "profile_id": self.face_identity_service.profile_id,
            "embedding_stability": embedding_stability,
            "consistency_passed": consistency_passed,
            "can_complete": is_active,
            "auto_complete": len(embeddings) >= FACE_IDENTITY_PREFERRED_SAMPLES and consistency_passed,
        }

    def _extract_batch_frame_results(self, frames: list[str]) -> list[dict[str, Any]]:
        selected_frames = self._select_model_frames(frames)
        decoded = self.face_identity_service.preprocessor.decode_many(
            selected_frames,
            max_width=FACE_ENROLLMENT_FRAME_MAX_WIDTH,
        )
        if not decoded:
            return []

        detections_by_frame = [self.face_identity_service.detector.detect(frame) for frame in decoded]
        quality_by_frame = [
            self.face_identity_service.quality_validator.validate(frame, detections)
            for frame, detections in zip(decoded, detections_by_frame)
        ]
        valid_indexes = [
            index
            for index, (detections, quality) in enumerate(zip(detections_by_frame, quality_by_frame))
            if len(detections) == 1 and quality.passed
        ]
        liveness_by_index: dict[int, Any] = {}
        if len(valid_indexes) >= 2:
            live_frames = [decoded[index] for index in valid_indexes]
            live_detections = [detections_by_frame[index] for index in valid_indexes]
            live_quality = [quality_by_frame[index] for index in valid_indexes]
            liveness = self.face_identity_service.liveness_service.liveness_detector.evaluate(
                live_frames,
                live_detections,
                live_quality,
            )
            liveness_by_index = {index: liveness for index in valid_indexes}

        results: list[dict[str, Any]] = []
        for index, frame in enumerate(decoded):
            detections = detections_by_frame[index]
            quality = quality_by_frame[index]
            quality_dict = quality.as_dict()
            if not quality.passed:
                results.append(
                    {
                        "accepted": False,
                        "reason": quality.reason,
                        "quality": quality_dict,
                        "liveness": self._liveness_dict(False, quality.reason),
                    }
                )
                continue
            if len(detections) != 1:
                results.append(
                    {
                        "accepted": False,
                        "reason": "face_count_invalid",
                        "quality": quality_dict,
                        "liveness": self._liveness_dict(False, "face_count_invalid"),
                    }
                )
                continue
            liveness = liveness_by_index.get(index)
            if liveness is None or not liveness.is_live:
                reason = liveness.reason if liveness is not None else "not_enough_frames"
                results.append(
                    {
                        "accepted": False,
                        "reason": f"liveness_{reason}",
                        "quality": quality_dict,
                        "liveness": liveness.as_dict() if liveness is not None else self._liveness_dict(False, reason),
                    }
                )
                continue
            embedding = normalize_embedding(self.face_identity_service.embedder.embed(frame, detections[0]))
            results.append(
                {
                    "accepted": bool(embedding),
                    "reason": "accepted" if embedding else "embedding_unavailable",
                    "embedding": embedding,
                    "quality": quality_dict,
                    "liveness": liveness.as_dict(),
                }
            )
        return results

    def _select_model_frames(self, frames: list[str]) -> list[str]:
        usable = [frame for frame in frames or [] if frame]
        if not usable:
            return []
        limit = max(2, int(FACE_ENROLLMENT_MAX_MODEL_FRAMES_PER_BATCH or 3))
        if len(usable) <= limit:
            return usable
        if limit == 1:
            return [usable[len(usable) // 2]]
        indexes = [
            round(index * (len(usable) - 1) / (limit - 1))
            for index in range(limit)
        ]
        selected: list[str] = []
        seen: set[int] = set()
        for index in indexes:
            if index in seen:
                continue
            seen.add(index)
            selected.append(usable[index])
        return selected

    def _embedding_diversity_decision(
        self,
        accepted_embeddings: list[list[float]],
        embedding: list[float],
    ) -> tuple[str, dict[str, float | None]]:
        stats: dict[str, float | None] = {
            "max_similarity_to_existing_sample": None,
            "min_distance_to_existing_sample": None,
            "similarity_to_centroid": None,
            "centroid_distance": None,
        }
        if not embedding:
            return "inconsistent", stats
        if accepted_embeddings:
            max_similarity = max(cosine_similarity(embedding, existing) for existing in accepted_embeddings)
            stats["max_similarity_to_existing_sample"] = max_similarity
            stats["min_distance_to_existing_sample"] = 1.0 - max_similarity
            if 1.0 - max_similarity < FACE_ENROLLMENT_MIN_DIVERSITY_DISTANCE:
                return "duplicate", stats
        if len(accepted_embeddings) >= FACE_ENROLLMENT_CONSISTENCY_MIN_SAMPLES:
            centroid = mean_embedding(accepted_embeddings)
            if centroid:
                centroid_similarity = cosine_similarity(centroid, embedding)
                stats["similarity_to_centroid"] = centroid_similarity
                stats["centroid_distance"] = 1.0 - centroid_similarity
                if stats["centroid_distance"] > FACE_ENROLLMENT_MAX_CENTROID_DISTANCE:
                    return "inconsistent", stats
        return "accepted", stats

    def _calculate_embedding_stability(self, embeddings: list[list[float]]) -> float:
        usable = [embedding for embedding in embeddings if embedding]
        if len(usable) < 2:
            return 0.0
        centroid = mean_embedding(usable)
        if not centroid:
            return 0.0
        return sum(cosine_similarity(centroid, embedding) for embedding in usable) / len(usable)

    def _consistency_passed(self, embeddings: list[list[float]]) -> bool:
        if len(embeddings) < FACE_IDENTITY_REQUIRED_SAMPLES:
            return False
        centroid = mean_embedding(embeddings)
        if not centroid:
            return False
        max_distance = max(1.0 - cosine_similarity(centroid, embedding) for embedding in embeddings)
        return max_distance <= FACE_ENROLLMENT_MAX_CENTROID_DISTANCE

    def _batch_response(
        self,
        session: dict[str, Any] | None,
        *,
        accepted_count: int,
        rejected_count: int,
        duplicate_count: int,
        quality_failed_count: int,
        inconsistent_count: int,
        liveness_failed_count: int,
        reason_counts: dict[str, int] | None = None,
        last_rejection_reason: str,
        guidance: str,
        last_quality: dict[str, Any] | None = None,
        last_liveness: dict[str, Any] | None = None,
        min_distance_to_existing_sample: float | None = None,
        last_centroid_distance: float | None = None,
    ) -> dict[str, Any]:
        embeddings = session.get("sample_embeddings", []) if session else []
        stability = self._calculate_embedding_stability(embeddings)
        consistency_passed = self._consistency_passed(embeddings)
        can_complete = len(embeddings) >= FACE_IDENTITY_REQUIRED_SAMPLES and consistency_passed
        auto_complete = len(embeddings) >= FACE_IDENTITY_PREFERRED_SAMPLES and consistency_passed
        total_reason_counts = dict(session.get("reason_counts_total", {}) if session else {})
        average_similarity_to_centroid = stability if embeddings else 0.0
        diversity_label = self._diversity_label(
            len(embeddings),
            session.get("duplicate_rejection_count", 0) if session else duplicate_count,
            min_distance_to_existing_sample,
        )
        lighting_label = self._lighting_label(last_quality or {})
        stability_label = self._stability_label(stability, last_liveness or {}, consistency_passed, len(embeddings))
        return {
            "accepted_count": accepted_count,
            "rejected_count": rejected_count,
            "duplicate_count": duplicate_count,
            "quality_failed_count": quality_failed_count,
            "inconsistent_count": inconsistent_count,
            "liveness_failed_count": liveness_failed_count,
            "reason_counts": reason_counts or {},
            "total_rejected_count": session.get("rejected_count_total", rejected_count) if session else rejected_count,
            "duplicate_rejection_count": session.get("duplicate_rejection_count", duplicate_count) if session else duplicate_count,
            "inconsistent_rejection_count": session.get("inconsistent_rejection_count", inconsistent_count) if session else inconsistent_count,
            "quality_failed_count_total": session.get("quality_failed_count_total", quality_failed_count) if session else quality_failed_count,
            "liveness_failed_count_total": session.get("liveness_failed_count_total", liveness_failed_count) if session else liveness_failed_count,
            "total_reason_counts": total_reason_counts,
            "accepted_samples": len(embeddings),
            "required_samples": FACE_IDENTITY_REQUIRED_SAMPLES,
            "preferred_samples": FACE_IDENTITY_PREFERRED_SAMPLES,
            "max_stored_samples": FACE_IDENTITY_MAX_STORED_SAMPLES,
            "can_complete": can_complete,
            "can_complete_early": auto_complete,
            "auto_complete": auto_complete,
            "embedding_stability": stability,
            "average_similarity_to_centroid": average_similarity_to_centroid,
            "min_distance_to_existing_sample": min_distance_to_existing_sample,
            "last_centroid_distance": last_centroid_distance,
            "consistency_passed": consistency_passed,
            "diversity": diversity_label,
            "lighting": lighting_label,
            "stability": stability_label,
            "guidance": guidance,
            "last_rejection_reason": last_rejection_reason,
            "last_quality": last_quality or {},
            "last_liveness": last_liveness or {},
        }

    def _guidance(
        self,
        reason_counts: dict[str, int],
        reason: str,
        quality_failed_count: int,
        duplicate_count: int,
        inconsistent_count: int,
        liveness_failed_count: int,
        accepted_count: int,
    ) -> str:
        counts = {str(key or "").lower(): int(value or 0) for key, value in (reason_counts or {}).items()}
        reason = (reason or "").lower()
        if counts.get("no_face", 0) > 0:
            return "Center your face inside the circle."
        if counts.get("multiple_faces", 0) > 0 or counts.get("face_count_invalid", 0) > 0:
            return "Only one face should be visible."
        if counts.get("too_dark", 0) > 0 or "too_dark" in reason:
            return "Lighting is too low. Move closer to a light source."
        if counts.get("too_bright", 0) > 0 or "too_bright" in reason:
            return "Too much light. Reduce glare."
        if counts.get("too_blurry", 0) > 0 or "blur" in reason or "low_quality" in reason or quality_failed_count > 0 and "dark" not in reason and "bright" not in reason:
            return "Hold still. Reduce motion."
        if counts.get("face_too_small", 0) > 0 or "small" in reason:
            return "Move closer to camera."
        if duplicate_count > 0 or "duplicate" in reason:
            return "Change angle slightly."
        if liveness_failed_count > 0 or "liveness" in reason:
            return "Move naturally."
        if inconsistent_count > 0 or "inconsistent" in reason:
            return "Keep same face, avoid extreme angles."
        if accepted_count > 0:
            return "Good. Continue slight movement."
        return "Good"

    def _merge_session_counts(
        self,
        session: dict[str, Any],
        *,
        accepted_count: int,
        rejected_count: int,
        duplicate_count: int,
        inconsistent_count: int,
        quality_failed_count: int,
        liveness_failed_count: int,
        reason_counts: dict[str, int],
    ) -> None:
        session["accepted_count_total"] = int(session.get("accepted_count_total", 0)) + accepted_count
        session["rejected_count_total"] = int(session.get("rejected_count_total", 0)) + rejected_count
        session["duplicate_rejection_count"] = int(session.get("duplicate_rejection_count", 0)) + duplicate_count
        session["inconsistent_rejection_count"] = int(session.get("inconsistent_rejection_count", 0)) + inconsistent_count
        session["quality_failed_count_total"] = int(session.get("quality_failed_count_total", 0)) + quality_failed_count
        session["liveness_failed_count_total"] = int(session.get("liveness_failed_count_total", 0)) + liveness_failed_count
        total_reason_counts = session.setdefault("reason_counts_total", {})
        for key, value in reason_counts.items():
            total_reason_counts[key] = int(total_reason_counts.get(key, 0)) + int(value)

    def _increment_reason(self, counts: dict[str, int], reason: str) -> None:
        key = str(reason or "sample_rejected")
        counts[key] = int(counts.get(key, 0)) + 1

    def _is_liveness_failure(self, reason: str) -> bool:
        return str(reason or "").startswith("liveness_")

    def _diversity_label(
        self,
        accepted_total: int,
        duplicate_total: int,
        min_distance_to_existing_sample: float | None,
    ) -> str:
        if duplicate_total >= max(3, accepted_total):
            return "Needs angle change"
        if min_distance_to_existing_sample is not None and min_distance_to_existing_sample < FACE_ENROLLMENT_MIN_DIVERSITY_DISTANCE * 1.5:
            return "Low"
        if accepted_total >= FACE_IDENTITY_REQUIRED_SAMPLES // 2:
            return "Good"
        return "Low"

    def _lighting_label(self, quality: dict[str, Any]) -> str:
        reason = str(quality.get("reason") or "").lower()
        brightness = quality.get("brightness_score")
        min_brightness = quality.get("min_brightness")
        max_brightness = quality.get("max_brightness")
        if "too_dark" in reason:
            return "Too dark"
        if "too_bright" in reason:
            return "Too bright"
        try:
            if brightness is not None and min_brightness is not None and float(brightness) < float(min_brightness):
                return "Too dark"
            if brightness is not None and max_brightness is not None and float(brightness) > float(max_brightness):
                return "Too bright"
        except (TypeError, ValueError):
            pass
        return "Good"

    def _stability_label(
        self,
        stability: float,
        liveness: dict[str, Any],
        consistency_passed: bool,
        accepted_total: int,
    ) -> str:
        reason = str(liveness.get("reason") or "").lower()
        checks = liveness.get("checks") or {}
        if "unstable" in reason or "excessive_motion" in reason:
            return "Unstable"
        try:
            if float(checks.get("max_motion_px", 0.0)) > 0 and "excessive" in reason:
                return "Unstable"
        except (TypeError, ValueError):
            pass
        if accepted_total >= FACE_IDENTITY_REQUIRED_SAMPLES and not consistency_passed:
            return "Unstable"
        if accepted_total < 2 or stability <= 0:
            return "Pending"
        return "Good"

    def _is_quality_failure(self, reason: str) -> bool:
        return reason in {
            "no_face",
            "multiple_faces",
            "face_count_invalid",
            "face_too_small",
            "low_face_confidence",
            "too_blurry",
            "too_dark",
            "too_bright",
            "quality_failed",
        }

    def _liveness_dict(self, is_live: bool, reason: str) -> dict[str, Any]:
        return {"is_live": is_live, "confidence": 0.0, "reason": reason, "checks": {}}
