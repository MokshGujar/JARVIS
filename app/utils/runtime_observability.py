from __future__ import annotations

import logging
import re
from typing import Any


SENSITIVE_KEYS = re.compile(r"(api[_-]?key|token|secret|password|message_body|content|tts_text)", re.I)


def safe_value(key: str, value: Any) -> str:
    if value is None:
        return ""
    if SENSITIVE_KEYS.search(str(key or "")):
        return "[redacted]"
    text = re.sub(r"\s+", " ", str(value)).strip()
    if len(text) > 120:
        return f"{text[:117]}..."
    return text.replace('"', "'")


def log_boundary(logger: logging.Logger, boundary: str, **fields: Any) -> None:
    rendered = " ".join(f'{key}="{safe_value(key, value)}"' for key, value in fields.items())
    logger.info("[%s] %s", boundary, rendered)
