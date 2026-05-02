from __future__ import annotations


class MemoryCapability:
    def __init__(self, personal_memory_service) -> None:
        self.personal_memory_service = personal_memory_service

    def build_prompt_parts(self, query: str) -> list[str]:
        if not self.personal_memory_service:
            return []
        return self.personal_memory_service.build_prompt_parts(query)

