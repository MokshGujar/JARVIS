from __future__ import annotations

from typing import Any

from app.adapters.providers.stt_provider import STTProvider, build_stt_provider
from app.tools.base import BaseTool, ToolContext, ToolResult, ToolSpec


class STTTool(BaseTool):
    name = "stt"
    spec = ToolSpec(
        name="stt",
        description="Speech-to-text transcription for audio files or bytes.",
        category="voice",
        safety_level="LOW",
        supported_intents=["stt", "speech_to_text", "transcribe_file", "transcribe_audio_bytes", "readiness", "warmup"],
        metadata={
            "supported_actions": ["transcribe_file", "transcribe_audio_bytes", "readiness", "warmup"],
            "current_status": "thin_wrapper",
        },
    )

    def __init__(self, provider: STTProvider | None = None) -> None:
        self.provider = provider if provider is not None else build_stt_provider()

    def execute(self, context: ToolContext, **kwargs: Any) -> dict[str, Any]:
        action = str(context.payload.get("action") or context.intent or "readiness").strip().lower()
        args = dict(context.payload.get("args") or {})
        if action == "readiness":
            readiness = self.provider.readiness()
            return ToolResult(
                success=bool(readiness.get("available")),
                message=str(readiness.get("reason") or "STT readiness checked."),
                tool_name=self.name,
                error=None if readiness.get("available") else "stt_provider_unavailable",
                data={"action": "readiness", "provider_readiness": readiness, **readiness},
            ).as_dict()

        if action == "warmup":
            if not hasattr(self.provider, "warmup"):
                readiness = self.provider.readiness()
                return ToolResult(
                    success=bool(readiness.get("available")),
                    message=str(readiness.get("reason") or "STT provider does not need warmup."),
                    tool_name=self.name,
                    error=None if readiness.get("available") else "stt_provider_unavailable",
                    data={
                        "action": "warmup",
                        "provider_readiness": readiness,
                        "provider": readiness.get("provider_name"),
                        "model": readiness.get("model"),
                        "device": readiness.get("device"),
                        "model_loaded": False,
                        "model_load_ms": 0,
                        "cache_hit": False,
                    },
                ).as_dict()
            return self._as_tool_result(self.provider.warmup())

        if action in {"transcribe_file", "stt", "speech_to_text"}:
            path = str(args.get("path") or args.get("path_or_name") or context.payload.get("path") or context.command or "").strip()
            result = self.provider.transcribe_file(path, language=args.get("language"))
            return self._as_tool_result(result)

        if action == "transcribe_audio_bytes":
            audio = args.get("audio") or context.payload.get("audio")
            filename = str(args.get("filename") or context.payload.get("filename") or "audio.wav")
            result = self.provider.transcribe_bytes(audio, filename=filename, language=args.get("language"))
            return self._as_tool_result(result)

        return ToolResult(
            success=False,
            message=f"STT tool does not support action {action}.",
            tool_name=self.name,
            error="unsupported_action",
            data={"action": action or "unsupported"},
        ).as_dict()

    def _as_tool_result(self, result: dict[str, Any]) -> dict[str, Any]:
        action = str(result.get("action") or "transcribe")
        if bool(result.get("success")) and action != "warmup":
            text = str(result.get("text") or "").strip()
            if not text:
                result = {**result, "success": False, "error": "empty_transcript", "message": "No speech was detected."}

        error = result.get("error")
        data = dict(result)
        data.setdefault("action", action)
        return ToolResult(
            success=bool(result.get("success")),
            message=str(result.get("message") or result.get("text") or "Transcription failed."),
            tool_name=self.name,
            error=str(error) if error else None,
            data=data,
        ).as_dict()
