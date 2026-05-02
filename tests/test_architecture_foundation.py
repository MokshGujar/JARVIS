import os
import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock

from app.connectors.base import BaseConnector, ConnectorCapability, ConnectorResult, ConnectorStatus
from app.core.config_loader import ConfigLoader
from app.core.event_bus import EventBus, EventName
from app.services.command_risk_service import CommandRiskService
from app.services.secure_execution_service import SecureExecutionService
from app.tools.base import BaseTool, ToolContext, ToolExecutionResult, ToolResult, ToolRisk, ToolSpec, normalize_tool_result
from app.tools.registry import ToolRegistry


class FakeTool:
    def __init__(self, risk=None, *, name="fake", result=None):
        self.name = name
        self.risk = risk or ToolRisk()
        self.result = result
        self.calls = []

    def can_handle(self, intent):
        return intent == "fake"

    def classify_risk(self, command):
        return self.risk

    def execute(self, context):
        self.calls.append(context)
        if self.result is not None:
            return self.result
        return {"success": True, "action": "fake", "message": "ran"}


class ExplodingTool(FakeTool):
    def execute(self, context):
        self.calls.append(context)
        raise RuntimeError("boom")


class FakeConnector:
    connector_id = "fake"
    display_name = "Fake Connector"

    def status(self):
        return ConnectorStatus(connected=True, state="ready", message="ok", metadata={"source": "test"})

    def capabilities(self):
        return (ConnectorCapability(name="read", description="Read data"),)


class FoundationArchitectureTests(unittest.TestCase):
    def test_tool_registry_selects_first_matching_tool(self):
        tool = FakeTool()
        registry = ToolRegistry([tool])

        self.assertIs(registry.select("fake"), tool)
        self.assertIsNone(registry.select("missing"))

    def test_tool_registry_rejects_empty_and_duplicate_normalized_names(self):
        registry = ToolRegistry()
        with self.assertRaises(ValueError):
            registry.register(FakeTool(name=" "))

        registry.register(FakeTool(name="Fake Tool"))
        with self.assertRaises(ValueError):
            registry.register(FakeTool(name=" fake   tool "))

    def test_tool_registry_exposes_stable_keys_items_and_contains(self):
        tool = FakeTool(name="Fake Tool")
        registry = ToolRegistry([tool])

        self.assertTrue(registry.contains(" fake tool "))
        self.assertEqual(registry.keys(), ("Fake Tool",))
        self.assertEqual(registry.items(), (("Fake Tool", tool),))
        self.assertIs(registry.get("FAKE TOOL"), tool)
        with self.assertRaisesRegex(KeyError, "Tool is not registered"):
            registry.get("missing")

    def test_tool_spec_and_result_normalization_are_backward_compatible(self):
        spec = ToolSpec(name="fake")

        self.assertEqual(spec.category, "automation")
        self.assertEqual(spec.risk_level, "LOW_RISK")
        self.assertEqual(spec.safety_level, "LOW")
        self.assertFalse(spec.requires_confirmation)
        self.assertFalse(spec.requires_face_step_up)
        self.assertEqual(spec.supported_intents, [])
        self.assertGreater(spec.timeout_seconds, 0)
        self.assertEqual(spec.required_capabilities, [])
        self.assertEqual(spec.metadata, {})
        execution_result = normalize_tool_result(ToolExecutionResult(True, "ok", "done"))
        self.assertEqual(execution_result["success"], True)
        self.assertEqual(execution_result["action"], "ok")
        self.assertEqual(execution_result["message"], "done")
        self.assertIn("data", execution_result)
        self.assertIn("safety_level", execution_result)
        self.assertIn("requires_voice_permission", execution_result)
        self.assertEqual(
            normalize_tool_result(ToolResult(True, "done", tool_name="fake", requires_face_step_up=True), default_action="fake")["requires_face_step_up"],
            True,
        )
        invalid_result = normalize_tool_result(None, default_action="fake")
        self.assertFalse(invalid_result["success"])
        self.assertEqual(invalid_result["action"], "fake")
        self.assertEqual(invalid_result["message"], "Tool returned an invalid result.")
        self.assertIsNone(invalid_result["error"])

    def test_base_tool_exposes_contract_metadata(self):
        class ContractTool(BaseTool):
            name = "contract"
            spec = ToolSpec(
                name="contract",
                description="Contract test tool",
                category="test",
                supported_intents=["contract_intent"],
                safety_level="MEDIUM",
                requires_confirmation=True,
            )

            def execute(self, context, **kwargs):
                return {"success": True, "action": "contract", "message": context.user_text}

        tool = ContractTool()

        self.assertEqual(tool.description, "Contract test tool")
        self.assertEqual(tool.category, "test")
        self.assertEqual(tool.safety_level, "MEDIUM")
        self.assertTrue(tool.requires_confirmation)
        self.assertTrue(tool.can_handle("contract_intent"))

    def test_connector_result_and_base_contract_are_predictable(self):
        result = ConnectorResult(success=True, status="ready", message="ok", data={"count": 2})
        connector = FakeConnector()

        self.assertEqual(result.as_dict(), {"success": True, "status": "ready", "message": "ok", "count": 2})
        self.assertIsInstance(connector, BaseConnector)
        self.assertTrue(connector.status().connected)
        self.assertEqual(connector.capabilities()[0].name, "read")

    def test_event_bus_sanitizes_sensitive_payloads(self):
        bus = EventBus(record_history=True)
        seen = []
        bus.subscribe("*", seen.append)

        event = bus.publish(
            EventName.TOOL_STARTED,
            {
                "token": "secret",
                "Authorization": "Bearer secret",
                "api_key": "key",
                "nested": {"password": "pw", "safe": "ok"},
                "items": [{"step_up_token": "step", "refresh-token": "refresh"}],
            },
        )

        self.assertEqual(event.payload["token"], "[redacted]")
        self.assertEqual(event.payload["Authorization"], "[redacted]")
        self.assertEqual(event.payload["api_key"], "[redacted]")
        self.assertEqual(event.payload["nested"]["password"], "[redacted]")
        self.assertEqual(event.payload["nested"]["safe"], "ok")
        self.assertEqual(event.payload["items"][0]["step_up_token"], "[redacted]")
        self.assertEqual(event.payload["items"][0]["refresh-token"], "[redacted]")
        self.assertEqual(seen[0].name, EventName.TOOL_STARTED)
        self.assertEqual(bus.history()[0], event)

    def test_config_loader_applies_defaults_toml_and_env_overrides_recursively(self):
        config_dir = Path("tests") / "_tmp" / f"config_loader_{uuid.uuid4().hex}"
        config_dir.mkdir(parents=True, exist_ok=True)
        Path(config_dir, "browser.toml").write_text("default_timeout_seconds = 9\n", encoding="utf-8")
        Path(config_dir, "features.toml").write_text("[nested]\ntimeout = 4\nenabled = true\n", encoding="utf-8")
        old_browser = os.environ.get("JARVIS_BROWSER__DEFAULT_TIMEOUT_SECONDS")
        old_nested = os.environ.get("JARVIS_FEATURES__NESTED__TIMEOUT")
        os.environ["JARVIS_BROWSER__DEFAULT_TIMEOUT_SECONDS"] = "13"
        os.environ["JARVIS_FEATURES__NESTED__TIMEOUT"] = "9"
        try:
            loader = ConfigLoader(config_dir)
            loaded = loader.load()
            browser_section = loader.get_section("browser")
        finally:
            if old_browser is None:
                os.environ.pop("JARVIS_BROWSER__DEFAULT_TIMEOUT_SECONDS", None)
            else:
                os.environ["JARVIS_BROWSER__DEFAULT_TIMEOUT_SECONDS"] = old_browser
            if old_nested is None:
                os.environ.pop("JARVIS_FEATURES__NESTED__TIMEOUT", None)
            else:
                os.environ["JARVIS_FEATURES__NESTED__TIMEOUT"] = old_nested

        self.assertEqual(loaded["browser"]["default_timeout_seconds"], 13)
        self.assertEqual(loaded["security"]["step_up_token_ttl_seconds"], 30)
        self.assertEqual(loaded["features"]["nested"]["timeout"], 9)
        self.assertTrue(loaded["features"]["nested"]["enabled"])
        self.assertEqual(browser_section["default_timeout_seconds"], 13)

    def test_secure_execute_consumes_high_risk_token_once(self):
        risk = ToolRisk(level="HIGH_RISK", step_up_required=True, reasons=["delete_files"])
        tool = FakeTool(risk)
        face = Mock()
        face.validate_session.return_value = True
        step_up = Mock()
        step_up.consume.side_effect = [(True, "ok"), (False, "step_up_token_reused")]
        secure = SecureExecutionService(
            command_risk_service=CommandRiskService(),
            face_identity_service=face,
            step_up_auth_service=step_up,
        )
        context = ToolContext(
            command="delete notes.txt",
            intent="automation",
            face_session_id="face-session",
            step_up_token="token",
        )

        first = secure.secure_execute(tool, context)
        second = secure.secure_execute(tool, context)

        self.assertTrue(first["success"])
        self.assertEqual(second["action"], "auth_required")
        self.assertEqual(second["auth"]["reason"], "step_up_token_reused")
        self.assertEqual(len(tool.calls), 1)

    def test_secure_execute_refuses_high_risk_without_face_session(self):
        risk = ToolRisk(level="HIGH_RISK", step_up_required=True, reasons=["delete_files"])
        tool = FakeTool(risk)
        secure = SecureExecutionService(command_risk_service=CommandRiskService())

        result = secure.secure_execute(tool, ToolContext(command="delete notes.txt", intent="automation"))

        self.assertEqual(result["action"], "auth_required")
        self.assertTrue(result["auth"]["face_verification_required"])
        self.assertEqual(len(tool.calls), 0)

    def test_secure_execute_refuses_high_risk_without_step_up_service(self):
        risk = ToolRisk(level="HIGH_RISK", step_up_required=True, reasons=["delete_files"])
        tool = FakeTool(risk)
        face = Mock()
        face.validate_session.return_value = True
        secure = SecureExecutionService(command_risk_service=CommandRiskService(), face_identity_service=face)

        result = secure.secure_execute(
            tool,
            ToolContext(command="delete notes.txt", intent="automation", face_session_id="face-session"),
        )

        self.assertEqual(result["action"], "auth_required")
        self.assertEqual(result["auth"]["reason"], "step_up_unavailable")
        self.assertEqual(len(tool.calls), 0)

    def test_secure_execute_does_not_execute_when_token_consume_fails(self):
        risk = ToolRisk(level="HIGH_RISK", step_up_required=True, reasons=["delete_files"])
        tool = FakeTool(risk)
        face = Mock()
        face.validate_session.return_value = True
        step_up = Mock()
        step_up.consume.return_value = (False, "step_up_command_mismatch")
        secure = SecureExecutionService(
            command_risk_service=CommandRiskService(),
            face_identity_service=face,
            step_up_auth_service=step_up,
        )

        result = secure.secure_execute(
            tool,
            ToolContext(command="delete notes.txt", intent="automation", face_session_id="face-session", step_up_token="token"),
        )

        self.assertEqual(result["action"], "auth_required")
        self.assertEqual(result["auth"]["reason"], "step_up_command_mismatch")
        self.assertEqual(len(tool.calls), 0)

    def test_secure_execute_emits_events_and_handles_tool_exceptions_as_failure(self):
        bus = EventBus(record_history=True)
        tool = ExplodingTool()
        secure = SecureExecutionService(command_risk_service=CommandRiskService(), event_bus=bus)

        result = secure.secure_execute(tool, ToolContext(command="open calculator", intent="fake"))

        self.assertFalse(result["success"])
        self.assertEqual(result["action"], "fake")
        self.assertIn("Tool execution failed", result["message"])
        self.assertEqual([event.name for event in bus.history()], [EventName.TOOL_SELECTED, EventName.TOOL_STARTED, EventName.TOOL_FAILED])

    def test_secure_execute_falls_back_to_command_risk_service(self):
        class CommandRiskOnlyTool:
            name = "command_risk_only"

            def can_handle(self, intent):
                return True

            def execute(self, context):
                return {"success": True, "action": "ok", "message": "ok"}

        secure = SecureExecutionService(command_risk_service=CommandRiskService())
        result = secure.secure_execute(CommandRiskOnlyTool(), ToolContext(command="browser get text", intent="automation"))

        self.assertTrue(result["success"])


if __name__ == "__main__":
    unittest.main()
