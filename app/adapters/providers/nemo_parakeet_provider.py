from __future__ import annotations

import importlib
import os
import re
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from app.adapters.providers.stt_provider import _config_bool, _env_or_config, _error, nemo_parakeet_readiness, torch_cuda_available


class NemoParakeetProvider:
    provider_name = "nemo_parakeet"

    def __init__(self, config: dict[str, Any] | None = None, *, model_factory=None, cuda_checker=None) -> None:
        self.config = dict(config or {})
        self.model_factory = model_factory
        self.cuda_checker = cuda_checker
        self._model = None
        self._loaded_options: dict[str, Any] | None = None
        self._model_lock = threading.Lock()
        self._last_model_load_ms = 0
        self._last_model_cache_hit = False

    @property
    def model_name(self) -> str:
        return _env_or_config("PARAKEET_MODEL", self.config, "parakeet_model", "nvidia/parakeet-tdt-0.6b-v2")

    @property
    def device(self) -> str:
        return _env_or_config("PARAKEET_DEVICE", self.config, "parakeet_device", "cuda").lower()

    @property
    def compute_type(self) -> str:
        return _env_or_config("PARAKEET_COMPUTE_TYPE", self.config, "parakeet_compute_type", "float16")

    @property
    def model_dir(self) -> str | None:
        value = _env_or_config("PARAKEET_MODEL_DIR", self.config, "parakeet_model_dir", "")
        return value or None

    @property
    def language(self) -> str | None:
        value = _env_or_config("PARAKEET_LANGUAGE", self.config, "parakeet_language", "")
        return value or None

    @property
    def max_audio_mb(self) -> float | None:
        raw = _env_or_config("PARAKEET_MAX_AUDIO_MB", self.config, "parakeet_max_audio_mb", "")
        if not raw:
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    @property
    def require_wav(self) -> bool:
        return _config_bool(self.config, "parakeet_require_wav", True, env_name="PARAKEET_REQUIRE_WAV")

    @property
    def post_processing_enabled(self) -> bool:
        return _config_bool(self.config, "parakeet_post_processing_enabled", True, env_name="PARAKEET_POST_PROCESSING_ENABLED")

    @property
    def domain_correction_enabled(self) -> bool:
        return _config_bool(self.config, "parakeet_domain_correction_enabled", True, env_name="STT_DOMAIN_CORRECTION_ENABLED")

    @property
    def domain_correction_case_sensitive(self) -> bool:
        return _config_bool(self.config, "parakeet_domain_correction_case_sensitive", False, env_name="STT_DOMAIN_CORRECTION_CASE_SENSITIVE")

    @property
    def domain_correction_word_boundary(self) -> bool:
        return _config_bool(self.config, "parakeet_domain_correction_word_boundary", True, env_name="STT_DOMAIN_CORRECTION_WORD_BOUNDARY")

    @property
    def model_loaded(self) -> bool:
        return self._model is not None

    def readiness(self) -> dict[str, Any]:
        return nemo_parakeet_readiness(self.config).as_dict()

    def transcribe_file(self, path: str, language: str | None = None) -> dict[str, Any]:
        source = Path(str(path or ""))
        if not source.exists():
            return _error("audio_file_not_found", f"Audio file was not found: {source}", self.readiness())
        if not source.is_file():
            return _error("invalid_audio", f"Audio path is not a file: {source}", self.readiness())
        if self.require_wav and source.suffix.lower() != ".wav":
            return _error(
                "unsupported_audio_format",
                "Parakeet STT is configured for WAV input only. Convert audio to WAV before transcription or set PARAKEET_REQUIRE_WAV=false.",
                self.readiness(),
                provider=self.provider_name,
                source=str(source),
            )
        too_large = self._file_too_large(source)
        if too_large:
            return too_large

        options_or_error = self._transcription_options()
        if "error" in options_or_error:
            return options_or_error

        try:
            model = self._load_model(options_or_error)
        except Exception as exc:
            return _error("stt_model_load_failed", f"Could not load Parakeet model: {exc}", self.readiness())

        try:
            transcription_started = time.perf_counter()
            raw_result = model.transcribe([str(source)])
            transcription_ms = _elapsed_ms(transcription_started)
            return self._transcription_result(
                raw_result,
                source=str(source),
                options=options_or_error,
                language=language,
                transcription_ms=transcription_ms,
            )
        except Exception as exc:
            return _error("transcription_failed", f"Parakeet transcription failed: {exc}", self.readiness())

    def transcribe_bytes(self, audio: bytes, filename: str, language: str | None = None) -> dict[str, Any]:
        if not isinstance(audio, (bytes, bytearray)) or not audio:
            return _error("invalid_audio", "Audio bytes are empty or invalid.", self.readiness())
        suffix = Path(filename or "audio.wav").suffix or ".wav"
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
                temp_path = Path(handle.name)
                handle.write(bytes(audio))
            return self.transcribe_file(str(temp_path), language=language)
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except Exception:
                    pass

    def _file_too_large(self, source: Path) -> dict[str, Any] | None:
        max_audio_mb = self.max_audio_mb
        if max_audio_mb is None or max_audio_mb < 0:
            return None
        max_bytes = max_audio_mb * 1024 * 1024
        if source.stat().st_size > max_bytes:
            return _error("audio_file_too_large", f"Audio file is larger than {max_audio_mb:g} MB.", self.readiness())
        return None

    def _transcription_options(self) -> dict[str, Any]:
        if self.model_factory is None and not self._dependencies_available():
            return _error("stt_dependency_missing", "NVIDIA NeMo ASR is not installed.", self.readiness())
        if self.device == "cuda" and not self._cuda_available():
            return _error("cuda_unavailable", "CUDA was requested for Parakeet STT but is not available.", self.readiness())
        return {
            "provider": self.provider_name,
            "backend": "nemo",
            "model": self.model_name,
            "device": self.device,
            "compute_type": self.compute_type,
        }

    def _load_model(self, options: dict[str, Any]):
        if self._model is not None and self._loaded_options == options:
            self._last_model_cache_hit = True
            self._last_model_load_ms = 0
            return self._model

        with self._model_lock:
            if self._model is not None and self._loaded_options == options:
                self._last_model_cache_hit = True
                self._last_model_load_ms = 0
                return self._model

            started = time.perf_counter()
            factory = self.model_factory
            if factory is None:
                asr = importlib.import_module("nemo.collections.asr")
                factory = asr.models.ASRModel.from_pretrained

            if self.model_dir:
                model = factory(model_name=options["model"], map_location=options["device"], cache_dir=self.model_dir)
            else:
                model = factory(model_name=options["model"], map_location=options["device"])

            if options["device"] == "cuda" and hasattr(model, "to"):
                model = model.to("cuda")
            if options["device"] == "cuda" and options["compute_type"] == "float16" and hasattr(model, "half"):
                model = model.half()
            if hasattr(model, "eval"):
                model.eval()

            self._model = model
            self._loaded_options = dict(options)
            self._last_model_cache_hit = False
            self._last_model_load_ms = _elapsed_ms(started)
            return self._model

    def warmup(self) -> dict[str, Any]:
        started = time.perf_counter()
        options_or_error = self._transcription_options()
        if "error" in options_or_error:
            return options_or_error
        try:
            self._load_model(options_or_error)
        except Exception as exc:
            return _error("stt_model_load_failed", f"Could not load Parakeet model: {exc}", self.readiness())
        total_ms = _elapsed_ms(started)
        return {
            "success": True,
            "action": "warmup",
            "message": "STT provider warmed up.",
            "provider": self.provider_name,
            "backend": options_or_error["backend"],
            "model": options_or_error["model"],
            "device": options_or_error["device"],
            "compute_type": options_or_error["compute_type"],
            "model_loaded": self.model_loaded,
            "model_load_ms": self._last_model_load_ms,
            "cache_hit": self._last_model_cache_hit,
            "total_ms": total_ms,
        }

    def _transcription_result(self, raw_result, *, source: str, options: dict[str, Any], language: str | None, transcription_ms: int = 0) -> dict[str, Any]:
        post_started = time.perf_counter()
        text, segments, duration = self._extract_text_segments_duration(raw_result)
        original_text = str(text or "").strip()
        text = self._clean_text(text) if self.post_processing_enabled else original_text
        text, corrections_applied = self._apply_domain_corrections(text)
        post_processing_ms = _elapsed_ms(post_started)
        if not text:
            return _error("empty_transcript", "No speech was detected.", self.readiness(), provider=self.provider_name, source=source)
        return {
            "success": True,
            "action": "transcribe",
            "message": text,
            "original_text": original_text,
            "corrected_text": text,
            "text": text,
            "provider": self.provider_name,
            "backend": options["backend"],
            "model": options["model"],
            "device": options["device"],
            "compute_type": options["compute_type"],
            "language": language or self.language,
            "duration": duration,
            "source": source,
            "segments": segments,
            "timestamps": segments,
            "raw_result_type": self._raw_result_type(raw_result),
            "post_processing_used": self.post_processing_enabled,
            "domain_correction_used": self.domain_correction_enabled,
            "corrections_applied": corrections_applied,
            "model_loaded": self.model_loaded,
            "model_load_ms": self._last_model_load_ms,
            "cache_hit": self._last_model_cache_hit,
            "transcription_ms": transcription_ms,
            "post_processing_ms": post_processing_ms,
        }

    def _extract_text_segments_duration(self, raw_result) -> tuple[str, list[dict[str, Any]], Any]:
        first = raw_result[0] if isinstance(raw_result, (list, tuple)) and raw_result else raw_result
        text = ""
        segments: list[dict[str, Any]] = []
        duration = None

        if isinstance(first, str):
            text = first
        elif isinstance(first, dict):
            text = str(first.get("text") or "")
            duration = first.get("duration")
            segments = self._compact_segments(first.get("segments") or first.get("timestamps") or [])
        else:
            text = str(getattr(first, "text", "") or getattr(first, "transcript", "") or "")
            duration = getattr(first, "duration", None)
            segments = self._compact_segments(getattr(first, "segments", None) or getattr(first, "timestamps", None) or [])

        return text, segments, duration

    @staticmethod
    def _compact_segments(raw_segments) -> list[dict[str, Any]]:
        compact = []
        for segment in raw_segments or []:
            if isinstance(segment, dict):
                start = segment.get("start", 0.0)
                end = segment.get("end", 0.0)
                text = segment.get("text", "")
            else:
                start = getattr(segment, "start", 0.0)
                end = getattr(segment, "end", 0.0)
                text = getattr(segment, "text", "")
            compact.append({"start": float(start or 0.0), "end": float(end or 0.0), "text": str(text or "").strip()})
        return compact

    @staticmethod
    def _clean_text(text: str) -> str:
        return re.sub(r"\s+", " ", str(text or "")).strip()

    def _apply_domain_corrections(self, text: str) -> tuple[str, list[dict[str, str]]]:
        corrections = self._domain_corrections()
        if not self.domain_correction_enabled or not corrections or not text:
            return text, []

        corrected = text
        applied: list[dict[str, str]] = []
        for wrong, replacement in corrections.items():
            if not wrong or not replacement:
                continue
            boundary = r"\b" if self.domain_correction_word_boundary else ""
            flags = 0 if self.domain_correction_case_sensitive else re.IGNORECASE
            pattern = re.compile(rf"{boundary}{re.escape(wrong)}{boundary}", flags=flags)
            if not pattern.search(corrected):
                continue
            corrected = pattern.sub(replacement, corrected)
            applied.append({"from": wrong, "to": replacement})
        return corrected, applied

    def _domain_corrections(self) -> dict[str, str]:
        env_value = str(os.environ.get("STT_DOMAIN_CORRECTIONS") or os.environ.get("PARAKEET_DOMAIN_CORRECTIONS") or "").strip()
        if env_value:
            return self._parse_corrections_string(env_value)
        raw = self.config.get("parakeet_domain_corrections", "Jarris=Jarvis|Javi=Jarvis|Jaris=Jarvis|Javas=Jarvis|Jervis=Jarvis|Javier=Jarvis")
        if isinstance(raw, dict):
            return {str(key): str(value) for key, value in raw.items()}
        return self._parse_corrections_string(str(raw or ""))

    @staticmethod
    def _parse_corrections_string(raw: str) -> dict[str, str]:
        corrections: dict[str, str] = {}
        for line in str(raw or "").replace("|", "\n").replace(",", "\n").splitlines():
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if key and value:
                corrections[key] = value
        return corrections

    @staticmethod
    def _raw_result_type(raw_result) -> str:
        if isinstance(raw_result, list):
            item_type = type(raw_result[0]).__name__ if raw_result else "empty"
            return f"list[{item_type}]"
        if isinstance(raw_result, tuple):
            item_type = type(raw_result[0]).__name__ if raw_result else "empty"
            return f"tuple[{item_type}]"
        return type(raw_result).__name__

    @staticmethod
    def _dependencies_available() -> bool:
        return NemoParakeetProvider._nemo_available() and NemoParakeetProvider._torch_available()

    @staticmethod
    def _nemo_available() -> bool:
        try:
            from importlib.util import find_spec

            return find_spec("nemo") is not None
        except Exception:
            return False

    @staticmethod
    def _torch_available() -> bool:
        try:
            from importlib.util import find_spec

            return find_spec("torch") is not None
        except Exception:
            return False

    def _cuda_available(self) -> bool:
        if self.cuda_checker is not None:
            return bool(self.cuda_checker())
        return torch_cuda_available()


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.perf_counter() - started) * 1000))
