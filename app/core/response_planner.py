from __future__ import annotations

from app.core.contracts import ExecutionPlan


class ResponsePlanner:
    def plan(self, route_name: str, *, mode: str = "stream", sensitive: bool = False, requires_face_auth: bool = False, metadata=None) -> ExecutionPlan:
        return ExecutionPlan(
            route=route_name,
            mode=mode,
            sensitive=sensitive,
            requires_face_auth=requires_face_auth,
            metadata=metadata or {},
        )
