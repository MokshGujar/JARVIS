from __future__ import annotations


class SecurityAgent:
    def __init__(self, secure_execution_service) -> None:
        self.secure_execution_service = secure_execution_service

    def secure_execute(self, tool, context):
        return self.secure_execution_service.secure_execute(tool, context)
