import unittest

from app.orchestrator.semantic_automation import (
    AutomationDomain,
    AutomationMode,
    SemanticActionPlan,
    SemanticAutomationAction,
    SemanticAutomationIntent,
    VerificationStatus,
)


class SemanticAutomationModelsTests(unittest.TestCase):
    def test_required_enum_values_exist(self):
        self.assertEqual(AutomationDomain.BROWSER.value, "browser")
        self.assertEqual(AutomationDomain.VISIBLE_UI.value, "visible_ui")
        self.assertEqual(AutomationMode.DIRECT_TOOL.value, "direct_tool")
        self.assertEqual(AutomationMode.DRY_RUN.value, "dry_run")
        self.assertEqual(SemanticAutomationIntent.SEARCH_WEB.value, "SEARCH_WEB")
        self.assertEqual(SemanticAutomationIntent.SAVE_CONTENT_AS_FILE.value, "SAVE_CONTENT_AS_FILE")

    def test_browser_search_action_representation(self):
        action = SemanticAutomationAction(
            intent=SemanticAutomationIntent.SEARCH_WEB,
            domain=AutomationDomain.BROWSER,
            mode=AutomationMode.DIRECT_TOOL,
            query="Python docs",
            preferred_tool="browser",
            fallback_tool="app_interaction",
            verification_strategy="query_or_navigation_state",
        )

        payload = action.as_dict()
        self.assertEqual(payload["intent"], "SEARCH_WEB")
        self.assertEqual(payload["query"], "Python docs")
        self.assertEqual(payload["preferred_tool"], "browser")

    def test_save_content_missing_filename_representation(self):
        action = SemanticAutomationAction(
            intent=SemanticAutomationIntent.SAVE_CONTENT_AS_FILE,
            domain=AutomationDomain.FILE,
            mode=AutomationMode.DIRECT_TOOL,
            content="meeting at 5",
            requires_context=True,
            missing_fields=["file_name"],
            preferred_tool="file",
        )

        self.assertTrue(action.requires_context)
        self.assertEqual(action.as_dict()["missing_fields"], ["file_name"])

    def test_verification_status_values_compare_and_serialize(self):
        self.assertEqual(VerificationStatus.VERIFIED, "verified")
        self.assertEqual(VerificationStatus.LIKELY_SUCCESS.value, "likely_success")
        self.assertEqual(str(VerificationStatus.BLOCKED), "blocked")

    def test_semantic_action_plan_serializes_actions(self):
        plan = SemanticActionPlan(
            original_text="search Python docs",
            mode=AutomationMode.DRY_RUN,
            actions=[
                SemanticAutomationAction(
                    intent=SemanticAutomationIntent.SEARCH_WEB,
                    domain=AutomationDomain.BROWSER,
                    mode=AutomationMode.DIRECT_TOOL,
                    query="Python docs",
                )
            ],
        )

        payload = plan.as_dict()
        self.assertEqual(payload["mode"], "dry_run")
        self.assertEqual(payload["actions"][0]["intent"], "SEARCH_WEB")


if __name__ == "__main__":
    unittest.main()
