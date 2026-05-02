import unittest

from app.adapters.providers.fake_stt_provider import FakeSTTProvider
from app.adapters.providers.stt_provider import DisabledSTTProvider
from app.orchestrator.tool_registry import ToolRegistry
from app.tools.base import ToolContext
from app.tools.stt_tool import STTTool
from app.tools.tool_inventory import build_readiness_tool_registry, get_tool_inventory_record


class STTToolTests(unittest.TestCase):
    def test_stt_tool_is_registered_and_discoverable(self):
        tool = STTTool(FakeSTTProvider("hello"))
        registry = ToolRegistry([tool])

        self.assertIs(registry.by_name("stt"), tool)
        self.assertIs(registry.by_intent("transcribe_file"), tool)

    def test_readiness_registry_uses_stt_tool(self):
        registry = build_readiness_tool_registry()

        self.assertIsInstance(registry.by_name("stt"), STTTool)

    def test_tool_inventory_marks_stt_as_thin_wrapper(self):
        record = get_tool_inventory_record("stt")

        self.assertEqual(record.current_status, "thin_wrapper")
        self.assertEqual(record.safety_level, "LOW")
        self.assertIn("transcribe_file", record.supported_actions)

    def test_disabled_provider_returns_unavailable(self):
        tool = STTTool(DisabledSTTProvider())

        result = tool.execute(ToolContext(command="audio.wav", intent="transcribe_file", payload={"action": "transcribe_file", "args": {"path": "audio.wav"}}))

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "stt_provider_unavailable")
        self.assertEqual(result["tool_name"], "stt")
        self.assertEqual(result["provider_readiness"]["provider_name"], "none")

    def test_fake_provider_transcribes_file(self):
        provider = FakeSTTProvider("deterministic transcript")
        tool = STTTool(provider)

        result = tool.execute(ToolContext(command="", intent="transcribe_file", payload={"action": "transcribe_file", "args": {"path": "sample.wav"}}))

        self.assertTrue(result["success"])
        self.assertEqual(result["text"], "deterministic transcript")
        self.assertEqual(provider.file_calls, [{"path": "sample.wav", "language": None}])

    def test_fake_provider_transcribes_audio_bytes(self):
        provider = FakeSTTProvider("bytes transcript")
        tool = STTTool(provider)

        result = tool.execute(
            ToolContext(
                command="",
                intent="transcribe_audio_bytes",
                payload={"action": "transcribe_audio_bytes", "args": {"audio": b"abc", "filename": "clip.wav", "language": "en"}},
            )
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["text"], "bytes transcript")
        self.assertEqual(provider.bytes_calls, [{"audio": b"abc", "filename": "clip.wav", "language": "en"}])

    def test_stt_tool_readiness_action_returns_provider_readiness(self):
        tool = STTTool(FakeSTTProvider())

        result = tool.execute(ToolContext(command="", intent="readiness", payload={"action": "readiness"}))

        self.assertTrue(result["success"])
        self.assertEqual(result["provider_readiness"]["provider_name"], "fake")

    def test_stt_tool_warmup_delegates_when_provider_supports_it(self):
        class WarmupProvider(FakeSTTProvider):
            def __init__(self):
                super().__init__("hello")
                self.warmup_calls = 0

            def warmup(self):
                self.warmup_calls += 1
                return {
                    "success": True,
                    "action": "warmup",
                    "message": "warm",
                    "provider": "fake",
                    "model": "fake",
                    "device": "cpu",
                    "model_loaded": True,
                    "model_load_ms": 1,
                    "cache_hit": False,
                }

        provider = WarmupProvider()
        tool = STTTool(provider)

        result = tool.execute(ToolContext(command="", intent="warmup", payload={"action": "warmup"}))

        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "warmup")
        self.assertTrue(result["model_loaded"])
        self.assertEqual(provider.warmup_calls, 1)

    def test_empty_transcript_returns_empty_transcript(self):
        tool = STTTool(FakeSTTProvider(""))

        result = tool.execute(ToolContext(command="", intent="transcribe_file", payload={"action": "transcribe_file", "args": {"path": "sample.wav"}}))

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "empty_transcript")

    def test_stt_tool_returns_transcript_without_executing_it(self):
        provider = FakeSTTProvider("open calculator and delete files")
        tool = STTTool(provider)

        result = tool.execute(ToolContext(command="", intent="transcribe_file", payload={"action": "transcribe_file", "args": {"path": "sample.wav"}}))

        self.assertTrue(result["success"])
        self.assertEqual(result["text"], "open calculator and delete files")
        self.assertEqual(result["action"], "transcribe")
        self.assertEqual(provider.file_calls, [{"path": "sample.wav", "language": None}])


if __name__ == "__main__":
    unittest.main()
