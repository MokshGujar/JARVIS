from __future__ import annotations

from typing import Any

from config import FACE_RECOGNITION_DET_SIZE, FACE_RECOGNITION_MODEL_NAME
from app.adapters.face.face_detector import FaceDetection
from app.core.face_vectors import normalize_embedding


class UnavailableFaceRecognitionBackend:
    backend_name = "unavailable"
    model_name = ""
    embedding_dim = 0

    def __init__(self, reason: str = "face_backend_unavailable") -> None:
        self.reason = reason

    def detect_faces(self, frame: Any) -> list[FaceDetection]:
        raise RuntimeError(self.reason)

    def extract_embedding(self, frame: Any, detection: FaceDetection) -> list[float]:
        raise RuntimeError(self.reason)

    def status(self) -> dict:
        return {
            "available": False,
            "backend": self.backend_name,
            "model_name": self.model_name,
            "embedding_dim": self.embedding_dim,
            "reason": self.reason,
        }


class InsightFaceRecognitionBackend:
    backend_name = "insightface"

    def __init__(self, *, model_name: str = FACE_RECOGNITION_MODEL_NAME) -> None:
        self.model_name = model_name
        self.embedding_dim = 512
        self._app = None
        self._load_error = ""
        self._load()

    def _load(self) -> None:
        try:
            from insightface.app import FaceAnalysis

            app = FaceAnalysis(
                name=self.model_name,
                allowed_modules=["detection", "recognition"],
                providers=["CPUExecutionProvider"],
            )
            det_size = max(160, int(FACE_RECOGNITION_DET_SIZE or 320))
            app.prepare(ctx_id=0, det_size=(det_size, det_size))
            self._app = app
        except Exception as exc:
            self._load_error = str(exc) or "insightface_unavailable"
            self._app = None

    def detect_faces(self, frame: Any) -> list[FaceDetection]:
        if self._app is None:
            raise RuntimeError(self._load_error or "insightface_unavailable")
        faces = self._app.get(frame.image_rgb)
        detections: list[FaceDetection] = []
        for face in faces:
            bbox = getattr(face, "bbox", None)
            if bbox is None or len(bbox) < 4:
                continue
            embedding = getattr(face, "normed_embedding", None)
            if embedding is None:
                raw_embedding = getattr(face, "embedding", None)
                embedding = normalize_embedding(raw_embedding.tolist() if hasattr(raw_embedding, "tolist") else (raw_embedding or []))
            else:
                embedding = embedding.tolist() if hasattr(embedding, "tolist") else list(embedding)
            detection = FaceDetection(
                bbox=(float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])),
                confidence=float(getattr(face, "det_score", 0.0) or 0.0),
                landmarks=getattr(face, "kps", None),
                embedding=embedding,
            )
            detections.append(detection)
        return detections

    def extract_embedding(self, frame: Any, detection: FaceDetection) -> list[float]:
        if detection.embedding:
            return normalize_embedding(detection.embedding)
        detections = self.detect_faces(frame)
        if len(detections) != 1 or not detections[0].embedding:
            raise RuntimeError("face_embedding_unavailable")
        return normalize_embedding(detections[0].embedding or [])

    def status(self) -> dict:
        return {
            "available": self._app is not None,
            "backend": self.backend_name,
            "model_name": self.model_name,
            "embedding_dim": self.embedding_dim,
            "reason": "" if self._app is not None else self._load_error,
        }
