from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]


DEFAULT_CONFIG: dict[str, dict[str, Any]] = {
    "automation": {
        "enabled": True,
        "task_timeout_seconds": 120,
        "smart_automation_enabled": True,
        "semantic_planner_enabled": False,
        "automation_context_enabled": True,
        "automation_context_ttl_seconds": 900,
        "automation_context_redact_sensitive": True,
        "automation_dry_run_enabled": True,
        "automation_duplicate_protection_enabled": True,
        "automation_duplicate_window_seconds": 5,
        "app_interaction": {
            "enabled": True,
            "backend": "pywinauto",
            "require_focused_window": True,
            "click_coordinates_enabled": False,
            "type_delay_ms": 10,
            "auto_focus_after_app_open": True,
            "focus_timeout_seconds": 5,
            "semantic_actions_enabled": True,
            "debug": False,
        },
    },
    "security": {
        "step_up_token_ttl_seconds": 30,
        "confirm_medium_risk": True,
        "confirm_high_risk": True,
    },
    "whatsapp": {
        "desktop_timeout_seconds": 8,
        "web_timeout_seconds": 20,
        "contact_fuzzy_threshold": 0.88,
    },
    "browser": {
        "default_timeout_seconds": 20,
        "whatsapp_login_timeout_seconds": 12,
    },
    "models": {
        "chat_model": "llama-3.3-70b-versatile",
        "brain_model": "llama-3.1-8b-instant",
    },
    "summary": {
        "provider": "none",
        "max_input_chars": 32000,
    },
    "stt": {
        "provider": "nemo_parakeet",
        "preferred_local_provider": "nemo_parakeet",
        "parakeet_model": "nvidia/parakeet-tdt-0.6b-v2",
        "parakeet_device": "cuda",
        "parakeet_compute_type": "float16",
        "parakeet_model_dir": "",
        "parakeet_language": "",
        "parakeet_max_audio_mb": "",
        "parakeet_require_wav": True,
        "parakeet_post_processing_enabled": True,
        "parakeet_domain_correction_enabled": True,
        "parakeet_domain_corrections": "Jarris=Jarvis|Javi=Jarvis|Jaris=Jarvis|Javas=Jarvis|Jervis=Jarvis|Javier=Jarvis",
        "parakeet_domain_correction_case_sensitive": False,
        "parakeet_domain_correction_word_boundary": True,
        "provider_cache_enabled": True,
        "parakeet_preload_on_startup": True,
        "warmup_on_startup": True,
        "fail_fast_on_warmup_error": False,
        "min_record_seconds": 1.0,
        "end_silence_seconds": 1.5,
        "max_record_seconds": 20.0,
        "speech_padding_ms": 300,
        "capture_mode": "backend_parakeet",
    },
    "tts": {
        "provider": "edge_tts",
        "edge_voice": "en-GB-RyanNeural",
        "edge_rate": "+20%",
        "edge_fast_rate": "+22%",
        "edge_volume": "+0%",
        "edge_pitch": "+0Hz",
        "punctuation_pause_mode": "natural",
        "enable_ssml_pauses": False,
        "max_sentence_chars": 240,
        "normalize_dates": True,
        "normalize_numbers": True,
        "debug_text": False,
        "no_overlap": True,
        "interrupt_policy": "stop_previous",
        "thinking_audio_enabled": True,
        "thinking_audio_provider": "edge_tts",
        "thinking_audio_phrases": "On it.|Sure.|Got it.|Okay.|One moment.|I'm on it.|Let me check.|Give me a second.|Alright.|Just a moment.",
        "thinking_audio_randomize": True,
        "thinking_audio_avoid_repeat": True,
        "thinking_audio_last_phrase_memory": True,
        "thinking_audio_max_per_request": 1,
        "thinking_audio_max_seconds": 2.0,
        "thinking_audio_rate": "+20%",
        "thinking_audio_volume": "+0%",
        "thinking_audio_finish_before_final_tts": True,
        "thinking_audio_stop_on_final_tts": False,
        "thinking_audio_final_tts_wait_timeout_ms": 2500,
        "thinking_audio_interruptible": True,
        "thinking_audio_cache_enabled": True,
        "thinking_audio_debug": False,
    },
    "features": {
        "vector_store_preload": False,
        "canonical_frontend_actions": False,
    },
}


class ConfigLoader:
    def __init__(self, config_dir: str | Path = "config", *, env_prefix: str = "JARVIS_") -> None:
        self.config_dir = Path(config_dir)
        self.env_prefix = env_prefix

    def load(self) -> dict[str, dict[str, Any]]:
        config = deepcopy(DEFAULT_CONFIG)
        section_names = set(config.keys())
        if self.config_dir.exists():
            section_names.update(path.stem for path in self.config_dir.glob("*.toml"))
        for section in sorted(section_names):
            file_path = self.config_dir / f"{section}.toml"
            if file_path.exists():
                loaded = self._load_toml(file_path)
                if isinstance(loaded, dict):
                    current = config.setdefault(section, {})
                    _deep_merge(current, loaded)
        self._apply_env_overrides(config)
        return config

    def get_section(self, section: str) -> dict[str, Any]:
        return deepcopy(self.load().get(str(section or "").strip().lower(), {}))

    def _load_toml(self, file_path: Path) -> dict[str, Any]:
        with file_path.open("rb") as handle:
            return tomllib.load(handle)

    def _apply_env_overrides(self, config: dict[str, dict[str, Any]]) -> None:
        for name, raw_value in os.environ.items():
            if not name.startswith(self.env_prefix) or "__" not in name:
                continue
            section_key = name.removeprefix(self.env_prefix)
            section, key = section_key.split("__", 1)
            section = section.lower()
            key_path = [part.lower() for part in key.split("__") if part]
            if section not in config:
                config[section] = {}
            existing = _get_nested(config[section], key_path)
            _set_nested(config[section], key_path, _coerce_env_value(raw_value, existing))


def _coerce_env_value(value: str, existing: Any = None) -> Any:
    raw = str(value).strip()
    if isinstance(existing, bool):
        return raw.lower() in {"1", "true", "yes", "on"}
    if isinstance(existing, int) and not isinstance(existing, bool):
        try:
            return int(raw)
        except ValueError:
            return existing
    if isinstance(existing, float):
        try:
            return float(raw)
        except ValueError:
            return existing
    if raw.lower() in {"true", "false"}:
        return raw.lower() == "true"
    return raw


def _deep_merge(target: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = value
    return target


def _get_nested(section: dict[str, Any], key_path: list[str]) -> Any:
    current: Any = section
    for key in key_path:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def _set_nested(section: dict[str, Any], key_path: list[str], value: Any) -> None:
    if not key_path:
        return
    current = section
    for key in key_path[:-1]:
        next_value = current.get(key)
        if not isinstance(next_value, dict):
            next_value = {}
            current[key] = next_value
        current = next_value
    current[key_path[-1]] = value
