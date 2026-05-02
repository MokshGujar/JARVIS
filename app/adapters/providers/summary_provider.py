from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any
from typing import Protocol

from app.core.config_loader import ConfigLoader


class SummaryProviderUnavailable(RuntimeError):
    pass


class SummaryProvider(Protocol):
    def summarize(self, text: str, mode: str = "summary") -> str:
        ...


@dataclass(frozen=True, slots=True)
class SummaryProviderReadiness:
    provider_name: str
    configured: bool
    available: bool
    reason: str
    max_input_chars: int
    live_call_required: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "provider_name": self.provider_name,
            "configured": self.configured,
            "available": self.available,
            "reason": self.reason,
            "max_input_chars": self.max_input_chars,
            "live_call_required": self.live_call_required,
        }


class DisabledSummaryProvider:
    def summarize(self, text: str, mode: str = "summary") -> str:
        raise SummaryProviderUnavailable("No summary provider is configured.")


class GroqSummaryProvider:
    def __init__(self, groq_service) -> None:
        self.groq_service = groq_service

    def summarize(self, text: str, mode: str = "summary") -> str:
        prompt = _summary_prompt(text, mode=mode)
        return self.groq_service.get_response(prompt, chat_history=[])


def build_summary_provider(*, config: dict | None = None):
    provider_name = _summary_provider_name(config)
    if provider_name in {"", "none", "disabled", "off"}:
        return DisabledSummaryProvider()
    if provider_name == "fake":
        from app.adapters.providers.fake_summary_provider import FakeSummaryProvider

        return FakeSummaryProvider()
    if provider_name == "groq":
        return _build_groq_provider()
    return DisabledSummaryProvider()


def summary_provider_readiness(*, config: dict | None = None, env: dict[str, str] | None = None) -> SummaryProviderReadiness:
    section = _summary_config_section(config)
    provider_name = _summary_provider_name(section, env=env)
    max_input_chars = _summary_max_input_chars(section)
    if provider_name in {"", "none", "disabled", "off"}:
        return SummaryProviderReadiness(
            provider_name="none",
            configured=False,
            available=False,
            reason="disabled",
            max_input_chars=max_input_chars,
        )
    if provider_name == "fake":
        return SummaryProviderReadiness(
            provider_name="fake",
            configured=True,
            available=True,
            reason="test_or_local_fake",
            max_input_chars=max_input_chars,
        )
    if provider_name == "groq":
        config_present = _groq_config_present(env=env)
        return SummaryProviderReadiness(
            provider_name="groq",
            configured=config_present,
            available=config_present,
            reason="config_present" if config_present else "missing_config",
            max_input_chars=max_input_chars,
        )
    return SummaryProviderReadiness(
        provider_name=provider_name,
        configured=False,
        available=False,
        reason="unsupported_provider",
        max_input_chars=max_input_chars,
    )


def _summary_config_section(config: dict | None = None) -> dict[str, Any]:
    return config if config is not None else ConfigLoader().get_section("summary")


def _summary_provider_name(config: dict | None = None, *, env: dict[str, str] | None = None) -> str:
    env_map = os.environ if env is None else env
    env_value = str(env_map.get("SUMMARY_PROVIDER", "")).strip().lower()
    if env_value:
        return env_value
    section = _summary_config_section(config)
    return str(section.get("provider") or "none").strip().lower()


def _summary_max_input_chars(config: dict | None = None) -> int:
    section = _summary_config_section(config)
    try:
        return int(section.get("max_input_chars") or 32000)
    except (TypeError, ValueError):
        return 32000


def _groq_config_present(*, env: dict[str, str] | None = None) -> bool:
    env_map = os.environ if env is None else env
    if str(env_map.get("GROQ_API_KEY", "")).strip():
        return True
    index = 2
    while index < 20:
        if str(env_map.get(f"GROQ_API_KEY_{index}", "")).strip():
            return True
        index += 1
    return False


def _build_groq_provider() -> GroqSummaryProvider | DisabledSummaryProvider:
    try:
        from config import GROQ_API_KEYS

        if not GROQ_API_KEYS:
            return DisabledSummaryProvider()
        from app.services.groq_service import GroqService
        from app.services.vector_store import VectorStoreService

        return GroqSummaryProvider(GroqService(VectorStoreService()))
    except Exception:
        return DisabledSummaryProvider()


def _summary_prompt(text: str, *, mode: str = "summary") -> str:
    cleaned = str(text or "").strip()
    if mode == "key_points":
        instruction = "Extract concise key points from the text. Do not add facts that are not present."
    elif mode == "notes":
        instruction = "Turn the text into concise notes. Do not add facts that are not present."
    else:
        instruction = "Summarize the text concisely. Do not add facts that are not present."
    return f"{instruction}\n\nText:\n{cleaned}"
