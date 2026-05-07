from __future__ import annotations

from typing import Any

from app.services.automation_response import (
    AUTOMATION_RESPONSE_FORMATTER,
    AutomationResponseFormatter,
    normalize_automation_response,
)


class AutomationFacadeResponseFormatter:
    """Compatibility response formatter for the AutomationService facade."""

    def normalize(self, result: Any) -> dict[str, Any]:
        return normalize_automation_response(result)

    def format_message(self, result: dict[str, Any]) -> str | None:
        return AUTOMATION_RESPONSE_FORMATTER.format(result)


__all__ = [
    "AUTOMATION_RESPONSE_FORMATTER",
    "AutomationFacadeResponseFormatter",
    "AutomationResponseFormatter",
    "normalize_automation_response",
]
