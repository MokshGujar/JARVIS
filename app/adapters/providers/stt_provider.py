from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Protocol

from app.core.config_loader import ConfigLoader


class STTProviderUnavailable(RuntimeError):
    pass


class STTProvider(Protocol):
    def transcribe_file(self, path: str, language: str | None = None) -> dict[str, Any]:
        ...

    def transcribe_bytes(self, audio: bytes, filename: str, language: str | None = None) -> dict[str, Any]:
        ...

    def readiness(self) -> dict[str, Any]:
        ...


@dataclass(frozen=True, slots=True)
class STTProviderReadiness:
    provider_name: str
    configured: bool
    available: bool
    reason: str
    backend: str
    model: str
    device: str
    compute_type: str
    language: str | None = None
    live_call_required: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider_name": self.provider_name,
            "configured": self.configured,
            "available": self.available,
            "reason": self.reason,
            "backend": self.backend,
            "model": self.model,
            "device": self.device,
            "compute_type": self.compute_type,
            "language": self.language,
            "live_call_required": self.live_call_required,
        }


_DISABLED_PROVIDER_NAMES = {"", "none", "disabled", "off"}
_AUTO_PROVIDER_NAMES = {"auto", "default"}


class DisabledSTTProvider:
    def transcribe_file(self, path: str, language: str | None = None) -> dict[str, Any]:
        return _error("stt_provider_unavailable", "STT provider is disabled.", self.readiness())

    def transcribe_bytes(self, audio: bytes, filename: str, language: str | None = None) -> dict[str, Any]:
        return _error("stt_provider_unavailable", "STT provider is disabled.", self.readiness())

    def readiness(self) -> dict[str, Any]:
        return stt_provider_readiness(config={"provider": "none"}).as_dict()


def build_stt_provider(*, config: dict | None = None) -> STTProvider:
    provider_name = _stt_provider_name(config)
    if provider_name in _DISABLED_PROVIDER_NAMES:
        return DisabledSTTProvider()
    if provider_name == "fake":
        from app.adapters.providers.fake_stt_provider import FakeSTTProvider

        return FakeSTTProvider()
    if provider_name == "nemo_parakeet":
        from app.adapters.providers.nemo_parakeet_provider import NemoParakeetProvider

        return NemoParakeetProvider(config=_stt_config_section(config))
    return DisabledSTTProvider()


def stt_provider_readiness(*, config: dict | None = None, env: dict[str, str] | None = None) -> STTProviderReadiness:
    section = _stt_config_section(config)
    provider_name = _stt_provider_name(section, env=env)

    if provider_name in _DISABLED_PROVIDER_NAMES:
        return STTProviderReadiness("none", False, False, "disabled", "none", "", "", "", None)
    if provider_name == "fake":
        return STTProviderReadiness("fake", True, True, "test_or_local_fake", "fake", "fake", "cpu", "fake", None)
    if provider_name == "nemo_parakeet":
        return nemo_parakeet_readiness(section, env=env)
    return STTProviderReadiness(provider_name, False, False, "unsupported_stt_provider", "unsupported", "", "", "", None)


def nemo_parakeet_readiness(config: dict[str, Any], *, env: dict[str, str] | None = None) -> STTProviderReadiness:
    model = _env_or_config("PARAKEET_MODEL", config, "parakeet_model", "nvidia/parakeet-tdt-0.6b-v2", env=env)
    device = _env_or_config("PARAKEET_DEVICE", config, "parakeet_device", "cuda", env=env).lower()
    compute_type = _env_or_config("PARAKEET_COMPUTE_TYPE", config, "parakeet_compute_type", "float16", env=env)
    language = _env_or_config("PARAKEET_LANGUAGE", config, "parakeet_language", "", env=env) or None

    try:
        from importlib.util import find_spec

        nemo_present = find_spec("nemo") is not None
        torch_present = find_spec("torch") is not None
    except Exception:
        nemo_present = False
        torch_present = False
    if not nemo_present or not torch_present:
        return STTProviderReadiness("nemo_parakeet", True, False, "stt_dependency_missing", "nemo", model, device, compute_type, language)

    if device == "cuda" and not torch_cuda_available():
        return STTProviderReadiness("nemo_parakeet", True, False, "cuda_unavailable", "nemo", model, device, compute_type, language)
    if device == "cuda":
        return STTProviderReadiness("nemo_parakeet", True, True, "cuda_available", "nemo", model, device, compute_type, language)

    return STTProviderReadiness("nemo_parakeet", True, True, "dependency_present", "nemo", model, device, compute_type, language)


def _stt_config_section(config: dict | None = None) -> dict[str, Any]:
    return dict(config if config is not None else ConfigLoader().get_section("stt"))


def _stt_provider_name(config: dict | None = None, *, env: dict[str, str] | None = None) -> str:
    section = _stt_config_section(config)
    env_map = os.environ if env is None else env
    raw_env = str(env_map.get("STT_PROVIDER", "")).strip().lower()
    if raw_env:
        return raw_env

    configured = str(section.get("provider", "auto")).strip().lower()
    if configured and configured not in _AUTO_PROVIDER_NAMES:
        return configured

    capture_mode = _stt_capture_mode(section, env=env)
    if capture_mode == "backend_parakeet":
        preferred = str(section.get("preferred_local_provider", "nemo_parakeet")).strip().lower()
        return preferred or "nemo_parakeet"
    return "none"


def _stt_capture_mode(config: dict[str, Any], *, env: dict[str, str] | None = None) -> str:
    mode = _env_or_config("STT_CAPTURE_MODE", config, "capture_mode", "backend_parakeet", env=env).strip().lower()
    return mode if mode in {"backend_parakeet", "browser_legacy"} else "backend_parakeet"


def _env_or_config(env_name: str, config: dict[str, Any], key: str, default: Any, *, env: dict[str, str] | None = None) -> str:
    env_map = os.environ if env is None else env
    raw_env = str(env_map.get(env_name, "")).strip()
    if raw_env:
        return raw_env
    return str(config.get(key, default)).strip()


def _config_bool(config: dict[str, Any], key: str, default: bool, *, env_name: str, env: dict[str, str] | None = None) -> bool:
    raw = _env_or_config(env_name, config, key, str(default).lower(), env=env).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def torch_cuda_available() -> bool:
    try:
        import importlib

        torch = importlib.import_module("torch")
        return bool(torch.cuda.is_available())
    except Exception:
        return False


def _error(error: str, message: str, readiness: dict[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
    return {
        "success": False,
        "action": "transcribe",
        "message": message,
        "error": error,
        "provider_readiness": readiness or {},
        **extra,
    }
