from __future__ import annotations

from typing import Any


class FakeSTTProvider:
    def __init__(self, transcript: str = "fake transcript") -> None:
        self.transcript = transcript
        self.file_calls: list[dict[str, Any]] = []
        self.bytes_calls: list[dict[str, Any]] = []

    def readiness(self) -> dict[str, Any]:
        return {
            "provider_name": "fake",
            "configured": True,
            "available": True,
            "reason": "test_or_local_fake",
            "backend": "fake",
            "model": "fake",
            "device": "cpu",
            "compute_type": "fake",
            "language": None,
            "live_call_required": False,
        }

    def transcribe_file(self, path: str, language: str | None = None) -> dict[str, Any]:
        self.file_calls.append({"path": path, "language": language})
        return self._result(source=str(path), language=language)

    def transcribe_bytes(self, audio: bytes, filename: str, language: str | None = None) -> dict[str, Any]:
        self.bytes_calls.append({"audio": audio, "filename": filename, "language": language})
        return self._result(source=str(filename), language=language)

    def _result(self, *, source: str, language: str | None) -> dict[str, Any]:
        if not self.transcript.strip():
            return {
                "success": False,
                "action": "transcribe",
                "message": "No speech was detected.",
                "error": "empty_transcript",
                "provider": "fake",
                "source": source,
            }
        return {
            "success": True,
            "action": "transcribe",
            "message": self.transcript,
            "text": self.transcript,
            "provider": "fake",
            "backend": "fake",
            "model": "fake",
            "device": "cpu",
            "compute_type": "fake",
            "language": language,
            "source": source,
            "segments": [{"start": 0.0, "end": 1.0, "text": self.transcript}],
            "fallback_used": False,
        }
