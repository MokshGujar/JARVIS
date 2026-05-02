from __future__ import annotations

from app.core.contracts import AssistantContext, CapabilityResult


class VisionCapability:
    def __init__(self, vision_service) -> None:
        self.vision_service = vision_service

    def describe_image(self, context: AssistantContext, prompt: str) -> CapabilityResult:
        if self.vision_service:
            text = self.vision_service.describe_image(context.imgbase64, prompt)
        else:
            text = "Vision is not available. Please set GROQ_API_KEY."
        return CapabilityResult(text=text, route="vision")

