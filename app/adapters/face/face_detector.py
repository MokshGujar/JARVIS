from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(slots=True)
class FaceDetection:
    bbox: tuple[float, float, float, float]
    confidence: float
    landmarks: Any = None
    embedding: list[float] | None = None

    @property
    def width(self) -> float:
        return max(0.0, float(self.bbox[2]) - float(self.bbox[0]))

    @property
    def height(self) -> float:
        return max(0.0, float(self.bbox[3]) - float(self.bbox[1]))

    @property
    def center(self) -> tuple[float, float]:
        return ((float(self.bbox[0]) + float(self.bbox[2])) / 2.0, (float(self.bbox[1]) + float(self.bbox[3])) / 2.0)


class FaceDetectorBackend(Protocol):
    def detect_faces(self, frame: Any) -> list[FaceDetection]:
        ...


class FaceDetector:
    def __init__(self, backend: FaceDetectorBackend) -> None:
        self.backend = backend

    def detect(self, frame: Any) -> list[FaceDetection]:
        return self.backend.detect_faces(frame)
