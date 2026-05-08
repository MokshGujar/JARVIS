from __future__ import annotations

from typing import Any


class ServiceBackedDomainHelper:
    """Compatibility helper that stores all mutable runtime state on AutomationService."""

    def __init__(self, service: Any) -> None:
        object.__setattr__(self, "_service", service)

    @property
    def service(self) -> Any:
        return object.__getattribute__(self, "_service")

    def __getattr__(self, name: str) -> Any:
        service = self.service
        if name in getattr(service, "__dict__", {}):
            return getattr(service, name)
        for helper_name in ("file_domain", "app_browser_domain", "system_domain", "whatsapp_domain"):
            helper = getattr(service, helper_name, None)
            if helper is not None and helper is not self and hasattr(type(helper), name):
                return getattr(helper, name)
        return getattr(service, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "_service":
            object.__setattr__(self, name, value)
            return
        if hasattr(type(self), name):
            object.__setattr__(self, name, value)
            return
        setattr(self.service, name, value)

    def __delattr__(self, name: str) -> None:
        if name in self.__dict__:
            object.__delattr__(self, name)
            return
        delattr(self.service, name)
