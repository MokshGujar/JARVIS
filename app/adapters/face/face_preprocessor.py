from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

import numpy as np

try:
    import cv2
except Exception:  # pragma: no cover - exercised when OpenCV is unavailable
    cv2 = None


@dataclass(slots=True)
class FaceFrame:
    image_bgr: Any
    image_rgb: Any
    gray: Any
    width: int
    height: int
    source_index: int = 0


class FacePreprocessor:
    def decode_base64_frame(
        self,
        image_base64: str,
        *,
        source_index: int = 0,
        max_width: int | None = None,
    ) -> FaceFrame:
        if cv2 is None:
            raise ValueError("opencv_unavailable")
        raw = (image_base64 or "").strip()
        if not raw:
            raise ValueError("missing_image")
        if "," in raw and raw.split(",", 1)[0].lower().startswith("data:"):
            raw = raw.split(",", 1)[1]
        try:
            data = base64.b64decode(raw, validate=False)
        except Exception as exc:
            raise ValueError("image_decode_failed") from exc
        buffer = np.frombuffer(data, dtype=np.uint8)
        image_bgr = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
        if image_bgr is None:
            raise ValueError("image_decode_failed")
        if max_width and max_width > 0 and image_bgr.shape[1] > max_width:
            scale = float(max_width) / float(image_bgr.shape[1])
            target_size = (int(max_width), max(1, int(image_bgr.shape[0] * scale)))
            image_bgr = cv2.resize(image_bgr, target_size, interpolation=cv2.INTER_AREA)
        height, width = image_bgr.shape[:2]
        image_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
        gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
        return FaceFrame(
            image_bgr=image_bgr,
            image_rgb=image_rgb,
            gray=gray,
            width=int(width),
            height=int(height),
            source_index=source_index,
        )

    def decode_many(self, frames: list[str], *, max_width: int | None = None) -> list[FaceFrame]:
        return [
            self.decode_base64_frame(frame, source_index=index, max_width=max_width)
            for index, frame in enumerate(frames or [])
        ]
