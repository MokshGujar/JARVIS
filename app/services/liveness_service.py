from __future__ import annotations

from typing import Any

from app.adapters.face.face_detector import FaceDetector
from app.adapters.face.face_liveness import LivenessResult, PassiveMultiFrameLiveness
from app.adapters.face.face_quality import FaceQualityValidator, FaceQualityResult


class LivenessService:
    def __init__(
        self,
        *,
        detector: FaceDetector,
        quality_validator: FaceQualityValidator | None = None,
        liveness_detector: PassiveMultiFrameLiveness | None = None,
    ) -> None:
        self.detector = detector
        self.quality_validator = quality_validator or FaceQualityValidator()
        self.liveness_detector = liveness_detector or PassiveMultiFrameLiveness()

    def evaluate(self, frames: list[Any]) -> tuple[LivenessResult, list[list[Any]], list[FaceQualityResult]]:
        detections_by_frame = [self.detector.detect(frame) for frame in frames]
        quality_by_frame = [
            self.quality_validator.validate(frame, detections)
            for frame, detections in zip(frames, detections_by_frame)
        ]
        result = self.liveness_detector.evaluate(frames, detections_by_frame, quality_by_frame)
        return result, detections_by_frame, quality_by_frame
