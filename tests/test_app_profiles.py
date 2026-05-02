import unittest

from app.orchestrator.app_profiles import get_app_profile
from app.orchestrator.semantic_automation import SemanticAutomationIntent


class AppProfilesTests(unittest.TestCase):
    def test_profile_lookup_normalizes_chrome_and_edge_names(self):
        self.assertEqual(get_app_profile("Google Chrome").canonical_name, "chrome")
        self.assertEqual(get_app_profile("ms edge").canonical_name, "edge")

    def test_chrome_search_maps_to_visible_browser_steps_metadata(self):
        profile = get_app_profile("chrome")
        action = profile.action_for(SemanticAutomationIntent.SEARCH_VISIBLE_BROWSER)

        self.assertEqual(action.tool_name, "app_interaction")
        self.assertEqual(action.tool_actions, ("select_address_bar", "replace_current_field", "submit_current_field"))

    def test_notepad_save_prefers_file_tool_and_no_blind_ctrl_s(self):
        profile = get_app_profile("notepad")
        action = profile.action_for(SemanticAutomationIntent.SAVE_CONTENT)

        self.assertEqual(action.tool_name, "file")
        self.assertTrue(action.metadata["prefer_file_tool"])
        self.assertFalse(action.metadata["blind_ctrl_s"])
        self.assertIn("do not blindly", action.notes.lower())

    def test_whatsapp_send_requires_confirmation(self):
        profile = get_app_profile("whatsapp")
        action = profile.action_for(SemanticAutomationIntent.SEND_MESSAGE_AFTER_CONFIRMATION)

        self.assertTrue(action.requires_confirmation)
        self.assertEqual(action.safety_level, "HIGH")

    def test_unknown_app_returns_generic_cautious_profile(self):
        profile = get_app_profile("unknown app")

        self.assertTrue(profile.cautious)
        self.assertIsNotNone(profile.action_for(SemanticAutomationIntent.TYPE_IN_ACTIVE_FIELD))


if __name__ == "__main__":
    unittest.main()
