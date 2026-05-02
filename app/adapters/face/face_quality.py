from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from config import (
    FACE_IDENTITY_MAX_BRIGHTNESS,
    FACE_IDENTITY_MIN_BLUR_LAPLACIAN,
    FACE_IDENTITY_MIN_BRIGHTNESS,
    FACE_IDENTITY_MIN_FACE_CONFIDENCE,
    FACE_IDENTITY_MIN_FACE_SIZE_PX,
)
from app.adapters.face.face_detector import FaceDetection

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None


@dataclass(slots=True)
class FaceQualityResult:
    passed: bool
    reason: str
    face_count: int = 0
    face_confidence: float = 0.0
    face_box_size: float = 0.0
    blur_score: float = 0.0
    brightness_score: float = 0.0
    checks: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "reason": self.reason,
            "face_count": self.face_count,
            "face_confidence": self.face_confidence,
            "face_box_size": self.face_box_size,
            "blur_score": self.blur_score,
            "brightness_score": self.brightness_score,
            **self.checks,
        }


class FaceQualityValidator:
    def validate(self, frame: Any, detections: list[FaceDetection]) -> FaceQualityResult:
        face_count = len(detections)
        blur_score = self.blur_score(frame)
        brightness_score = self.brightness_score(frame)
        base = {
            "min_face_size_px": FACE_IDENTITY_MIN_FACE_SIZE_PX,
            "min_face_confidence": FACE_IDENTITY_MIN_FACE_CONFIDENCE,
            "min_blur_laplacian": FACE_IDENTITY_MIN_BLUR_LAPLACIAN,
            "min_brightness": FACE_IDENTITY_MIN_BRIGHTNESS,
            "max_brightness": FACE_IDENTITY_MAX_BRIGHTNESS,
        }
        if face_count <= 0:
            return FaceQualityResult(False, "no_face", face_count, blur_score=blur_score, brightness_score=brightness_score, checks=base)
        if face_count > 1:
            return FaceQualityResult(False, "multiple_faces", face_count, blur_score=blur_score, brightness_score=brightness_score, checks=base)

        face = detections[0]
        face_box_size = min(face.width, face.height)
        if face_box_size < FACE_IDENTITY_MIN_FACE_SIZE_PX:
            return FaceQualityResult(False, "face_too_small", face_count, face.confidence, face_box_size, blur_score, brightness_score, base)
        if face.confidence < FACE_IDENTITY_MIN_FACE_CONFIDENCE:
            return FaceQualityResult(False, "low_face_confidence", face_count, face.confidence, face_box_size, blur_score, brightness_score, base)
        if blur_score < FACE_IDENTITY_MIN_BLUR_LAPLACIAN:
            return FaceQualityResult(False, "too_blurry", face_count, face.confidence, face_box_size, blur_score, brightness_score, base)
        if brightness_score < FACE_IDENTITY_MIN_BRIGHTNESS:
            return FaceQualityResult(False, "too_dark", face_count, face.confidence, face_box_size, blur_score, brightness_score, base)
        if brightness_score > FACE_IDENTITY_MAX_BRIGHTNESS:
            return FaceQualityResult(False, "too_bright", face_count, face.confidence, face_box_size, blur_score, brightness_score, base)
        return FaceQualityResult(True, "ok", face_count, face.confidence, face_box_size, blur_score, brightness_score, base)

    def blur_score(self, frame: Any) -> float:
        if cv2 is None:
            return 0.0
        return float(cv2.Laplacian(frame.gray, cv2.CV_64F).var())

    def brightness_score(self, frame: Any) -> float:
        return float(frame.gray.mean())
