from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from config import (
    FACE_LIVENESS_IDENTICAL_FRAME_DIFF_THRESHOLD,
    FACE_LIVENESS_MAX_MOTION_PX,
    FACE_LIVENESS_MIN_CONFIDENCE,
    FACE_LIVENESS_MIN_FACE_IOU,
    FACE_LIVENESS_MIN_MOTION_PX,
)
from app.adapters.face.face_detector import FaceDetection
from app.adapters.face.face_quality import FaceQualityResult


@dataclass(slots=True)
class LivenessResult:
    is_live: bool
    confidence: float
    reason: str
    checks: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "is_live": self.is_live,
            "confidence": self.confidence,
            "reason": self.reason,
            "checks": self.checks,
        }


def _bbox_iou(left: tuple[float, float, float, float], right: tuple[float, float, float, float]) -> float:
    x1 = max(left[0], right[0])
    y1 = max(left[1], right[1])
    x2 = min(left[2], right[2])
    y2 = min(left[3], right[3])
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    left_area = max(0.0, left[2] - left[0]) * max(0.0, left[3] - left[1])
    right_area = max(0.0, right[2] - right[0]) * max(0.0, right[3] - right[1])
    union = left_area + right_area - intersection
    return 0.0 if union <= 0 else intersection / union


class PassiveMultiFrameLiveness:
    def evaluate(
        self,
        frames: list[Any],
        detections_by_frame: list[list[FaceDetection]],
        quality_by_frame: list[FaceQualityResult],
    ) -> LivenessResult:
        if not frames:
            return LivenessResult(False, 0.0, "missing_frames", {})
        if any(not item.passed for item in quality_by_frame):
            failed = next(item for item in quality_by_frame if not item.passed)
            return LivenessResult(False, 0.0, failed.reason, {"quality": [item.as_dict() for item in quality_by_frame]})
        if any(len(detections) != 1 for detections in detections_by_frame):
            return LivenessResult(False, 0.0, "face_count_invalid", {"face_counts": [len(item) for item in detections_by_frame]})
        if len(frames) < 2:
            return LivenessResult(False, 0.0, "not_enough_frames", {"frame_count": len(frames)})

        faces = [detections[0] for detections in detections_by_frame]
        centers = [face.center for face in faces]
        bboxes = [face.bbox for face in faces]
        center_steps = [
            ((centers[i][0] - centers[i - 1][0]) ** 2 + (centers[i][1] - centers[i - 1][1]) ** 2) ** 0.5
            for i in range(1, len(centers))
        ]
        max_motion = max(center_steps) if center_steps else 0.0
        total_motion = sum(center_steps)
        min_iou = min(_bbox_iou(bboxes[i - 1], bboxes[i]) for i in range(1, len(bboxes)))
        frame_diffs = [
            float(abs(frames[i].gray.astype("float32") - frames[i - 1].gray.astype("float32")).mean())
            for i in range(1, len(frames))
        ]
        mean_frame_diff = sum(frame_diffs) / len(frame_diffs) if frame_diffs else 0.0
        checks = {
            "frame_count": len(frames),
            "total_motion_px": total_motion,
            "max_motion_px": max_motion,
            "min_face_iou": min_iou,
            "mean_frame_diff": mean_frame_diff,
            "frame_diffs": frame_diffs,
            "quality": [item.as_dict() for item in quality_by_frame],
        }
        if mean_frame_diff < FACE_LIVENESS_IDENTICAL_FRAME_DIFF_THRESHOLD:
            return LivenessResult(False, 0.0, "frames_identical_or_static", checks)
        if total_motion < FACE_LIVENESS_MIN_MOTION_PX:
            return LivenessResult(False, 0.0, "face_static", checks)
        if max_motion > FACE_LIVENESS_MAX_MOTION_PX:
            return LivenessResult(False, 0.0, "excessive_motion", checks)
        if min_iou < FACE_LIVENESS_MIN_FACE_IOU:
            return LivenessResult(False, 0.0, "face_tracking_unstable", checks)

        motion_score = min(1.0, total_motion / max(FACE_LIVENESS_MIN_MOTION_PX * 3.0, 1.0))
        stability_score = min(1.0, max(0.0, (min_iou - FACE_LIVENESS_MIN_FACE_IOU) / max(1.0 - FACE_LIVENESS_MIN_FACE_IOU, 0.01)))
        diff_score = min(1.0, mean_frame_diff / max(FACE_LIVENESS_IDENTICAL_FRAME_DIFF_THRESHOLD * 3.0, 0.01))
        confidence = 0.45 * motion_score + 0.35 * stability_score + 0.20 * diff_score
        if confidence < FACE_LIVENESS_MIN_CONFIDENCE:
            return LivenessResult(False, confidence, "liveness_confidence_low", checks)
        return LivenessResult(True, confidence, "live", checks)
