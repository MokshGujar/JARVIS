from __future__ import annotations

from typing import Dict

from app.adapters.system.local_system_adapter import LocalSystemAdapter
from app.services.computer_control_service import ComputerControlService


class ComputerSettingsService:
    """Compatibility facade for system UI settings.

    Canonical owner: SystemTool.
    This facade remains for older imports/tests and delegates to LocalSystemAdapter;
    it is not the canonical execution boundary.
    """

    def __init__(self, computer_control: ComputerControlService | None = None, adapter: LocalSystemAdapter | None = None) -> None:
        self.computer_control = computer_control or ComputerControlService()
        self.adapter = adapter or LocalSystemAdapter(self.computer_control)

    def can_handle(self, command: str) -> bool:
        return self.adapter.can_handle(command)

    def execute(self, command: str) -> Dict[str, str | bool]:
        return self.adapter.execute(command)
