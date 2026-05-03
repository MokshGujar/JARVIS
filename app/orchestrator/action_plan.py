from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ActionStep:
    step_id: str
    tool_name: str
    intent: str
    action: str
    args: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    safety_level: str = "LOW"
    requires_confirmation: bool = False
    requires_face_step_up: bool = False
    requires_voice_permission: bool = False
    status: str = "pending"

    def as_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "tool_name": self.tool_name,
            "intent": self.intent,
            "action": self.action,
            "args": dict(self.args),
            "depends_on": list(self.depends_on),
            "safety_level": self.safety_level,
            "requires_confirmation": self.requires_confirmation,
            "requires_face_step_up": self.requires_face_step_up,
            "requires_voice_permission": self.requires_voice_permission,
            "status": self.status,
        }


@dataclass(slots=True)
class ActionPlan:
    original_text: str
    steps: list[ActionStep] = field(default_factory=list)
    is_multistep: bool = False
    requires_confirmation: bool = False
    requires_face_step_up: bool = False
    requires_voice_permission: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "original_text": self.original_text,
            "steps": [step.as_dict() for step in self.steps],
            "is_multistep": self.is_multistep,
            "requires_confirmation": self.requires_confirmation,
            "requires_face_step_up": self.requires_face_step_up,
            "requires_voice_permission": self.requires_voice_permission,
            "metadata": dict(self.metadata),
        }
