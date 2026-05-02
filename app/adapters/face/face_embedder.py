from __future__ import annotations

from typing import Any, Protocol

from app.adapters.face.face_detector import FaceDetection


class FaceEmbeddingBackend(Protocol):
    backend_name: str
    model_name: str
    embedding_dim: int

    def extract_embedding(self, frame: Any, detection: FaceDetection) -> list[float]:
        ...


class FaceEmbedder:
    def __init__(self, backend: FaceEmbeddingBackend) -> None:
        self.backend = backend

    def embed(self, frame: Any, detection: FaceDetection) -> list[float]:
        return self.backend.extract_embedding(frame, detection)
