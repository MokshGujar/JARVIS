import unittest
from unittest.mock import Mock

from app.connectors.browser_connector import BrowserConnector
from app.orchestrator.intent_router import IntentRouter
from app.orchestrator.main_orchestrator import MainOrchestrator
from app.orchestrator.scenario_policy import ScenarioPolicy
from app.orchestrator.tool_registry import ToolRegistry
from app.tools.base import ToolContext
from app.tools.browser_tool import BrowserTool


class BrowserToolOrchestratorTests(unittest.TestCase):
    def test_registry_registers_browser_tool_and_looks_up_by_intent(self):
        tool = BrowserTool(BrowserConnector(Mock()))
        registry = ToolRegistry([tool])

        self.assertIs(registry.by_name("browser"), tool)
        self.assertIs(registry.by_intent("browser_search"), tool)
        self.assertEqual(registry.by_category("browser"), (tool,))

    def test_intent_router_maps_browser_commands(self):
        router = IntentRouter()
        cases = {
            "browser search python docs": ("browser_search", "search"),
            "search python docs on google": ("browser_search", "search"),
            "open https://example.com": ("browser_open_url", "open_url"),
            "open youtube": ("browser_open_site", "open_site"),
            "play lo-fi music on youtube": ("browser_youtube_play", "youtube_play"),
            "fill form hello": ("browser_form_input", "form_input"),
        }

        for command, expected in cases.items():
            with self.subTest(command=command):
                route = router.route(command)
                self.assertIsNotNone(route)
                self.assertEqual(route.tool_name, "browser")
                self.assertEqual((route.intent, route.operation), expected)

    def test_browser_policy_low_and_high_actions(self):
        router = IntentRouter()
        policy = ScenarioPolicy()

        search = policy.evaluate(router.route("search python docs on google"))
        form_input = policy.evaluate(router.route("fill form hello"))

        self.assertEqual(search.safety_level, "LOW")
        self.assertFalse(search.requires_confirmation)
        self.assertEqual(form_input.safety_level, "HIGH")
        self.assertTrue(form_input.requires_confirmation)

    def test_main_orchestrator_selects_browser_tool_with_connector(self):
        browser_service = Mock()
        browser_service.execute.return_value = {"success": True, "action": "browser_control", "message": "searched"}
        tool = BrowserTool(BrowserConnector(browser_service))
        orchestrator = MainOrchestrator(registry=ToolRegistry([tool]), enforce_policy=False)

        result = orchestrator.execute_text("browser search python docs")

        self.assertTrue(result["success"])
        self.assertEqual(result["selected_tool"], "browser")
        self.assertEqual(result["scenario"], "browser.search")
        browser_service.execute.assert_called_once_with("search", query="python docs", engine="google")

    def test_browser_tool_delegates_to_legacy_bridge_when_available(self):
        bridge = Mock()
        bridge._execute_browser_command_legacy.return_value = {"success": True, "action": "open", "message": "Opening youtube."}
        tool = BrowserTool(automation_bridge=bridge)

        result = tool.execute(ToolContext(command="open youtube", intent="browser_open_site"))

        self.assertTrue(result["success"])
        self.assertEqual(result["tool_name"], "browser")
        bridge._execute_browser_command_legacy.assert_called_once()

    def test_high_browser_action_blocked_without_confirmation(self):
        browser_service = Mock()
        browser_service.execute.return_value = {"success": True, "action": "browser_control", "message": "typed"}
        orchestrator = MainOrchestrator(registry=ToolRegistry([BrowserTool(BrowserConnector(browser_service))]), enforce_policy=True)

        blocked = orchestrator.execute_text("fill form hello")
        allowed = orchestrator.execute(ToolContext(command="fill form hello", confirmation_state={"confirmed": True}))

        self.assertEqual(blocked["action"], "confirmation_required")
        self.assertFalse(blocked["requires_face_step_up"])
        self.assertTrue(allowed["success"])
        self.assertEqual(browser_service.execute.call_count, 1)


if __name__ == "__main__":
    unittest.main()
