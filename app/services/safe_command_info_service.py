from __future__ import annotations

from typing import Dict

from app.connectors.safe_command_info_connector import SafeCommandInfoConnector


class SafeCommandInfoService:
    """Compatibility facade for allowlisted read-only command information.

    Canonical owner: SystemTool/safe command metadata path.
    This facade delegates to SafeCommandInfoConnector and is not the canonical execution boundary.
    """

    def __init__(self, connector: SafeCommandInfoConnector | None = None) -> None:
        self.connector = connector or SafeCommandInfoConnector()

    def execute(self, command: str) -> Dict[str, str | bool]:
        return self.connector.execute(command)
