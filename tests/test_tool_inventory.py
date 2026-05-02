import unittest

from app.tools.tool_inventory import VALID_TOOL_CATEGORIES, VALID_TOOL_STATUSES, get_tool_inventory, get_tool_inventory_record


class ToolInventoryTests(unittest.TestCase):
    def test_tool_inventory_loads_successfully(self):
        inventory = get_tool_inventory()

        self.assertGreaterEqual(len(inventory), 32)
        self.assertIsNotNone(get_tool_inventory_record("file"))

    def test_every_tool_has_required_metadata_fields(self):
        for record in get_tool_inventory():
            with self.subTest(tool=record.name):
                self.assertTrue(record.name)
                self.assertTrue(record.category)
                self.assertTrue(record.description)
                self.assertTrue(record.supported_intents)
                self.assertTrue(record.supported_actions)
                self.assertTrue(record.safety_level)
                self.assertIn(record.current_status, VALID_TOOL_STATUSES)
                self.assertTrue(record.planned_phase)
                self.assertTrue(record.test_requirements)

    def test_tool_names_are_unique(self):
        names = [record.name for record in get_tool_inventory()]

        self.assertEqual(len(names), len(set(names)))

    def test_tool_categories_are_valid(self):
        for record in get_tool_inventory():
            with self.subTest(tool=record.name):
                self.assertIn(record.category, VALID_TOOL_CATEGORIES)

    def test_requested_tool_names_are_present(self):
        required = {
            "file",
            "app",
            "app_interaction",
            "browser",
            "system",
            "tts",
            "stt",
            "summary",
            "research",
            "memory",
            "reminder",
            "whatsapp",
            "message",
            "contact",
            "phone",
            "caller_lookup",
            "clipboard",
            "keyboard_mouse",
            "window",
            "screenshot",
            "vision",
            "youtube",
            "network",
            "wake_on_lan",
            "terminal",
            "project",
            "code_search",
            "code_edit",
            "safe_command_info",
            "game",
        }

        self.assertTrue(required.issubset({record.name for record in get_tool_inventory()}))

    def test_legacy_inventory_records_remain_explicitly_disabled_or_discoverable(self):
        legacy = {
            "voice_identity",
            "task_status",
        }

        self.assertTrue(legacy.issubset({record.name for record in get_tool_inventory()}))
        for name in legacy:
            with self.subTest(tool=name):
                self.assertEqual(get_tool_inventory_record(name).current_status, "disabled")

    def test_live_routed_statuses_are_explicit(self):
        self.assertEqual(get_tool_inventory_record("file").current_status, "live_routed")
        self.assertEqual(get_tool_inventory_record("app").current_status, "live_routed")
        self.assertEqual(get_tool_inventory_record("browser").current_status, "live_routed")
        self.assertEqual(get_tool_inventory_record("system").current_status, "live_routed")

    def test_planned_tools_are_present(self):
        self.assertEqual(get_tool_inventory_record("app_interaction").current_status, "thin_wrapper")
        self.assertEqual(get_tool_inventory_record("summary").current_status, "thin_wrapper")
        for name in ("whatsapp", "message", "stt", "tts", "memory", "research", "keyboard_mouse", "clipboard"):
            with self.subTest(tool=name):
                self.assertIsNotNone(get_tool_inventory_record(name))

    def test_inventory_metadata_exposes_status_provider_and_action_policy(self):
        terminal = get_tool_inventory_record("terminal")
        stt = get_tool_inventory_record("stt")

        self.assertEqual(terminal.as_tool_spec().metadata["status"], "metadata_only")
        self.assertEqual(dict(terminal.action_safety)["run_command"], "CRITICAL")
        self.assertIn("run_command", terminal.protected_actions)
        self.assertEqual(stt.as_tool_spec().metadata["target_provider"], "NemoParakeetProvider")

    def test_high_tools_require_confirmation_by_default(self):
        for record in get_tool_inventory():
            if record.safety_level == "HIGH":
                with self.subTest(tool=record.name):
                    self.assertTrue(record.requires_confirmation)
                    self.assertFalse(record.requires_face_step_up)

    def test_critical_tools_require_confirmation_without_action_level_face_step_up_by_default(self):
        for record in get_tool_inventory():
            if record.safety_level == "CRITICAL":
                with self.subTest(tool=record.name):
                    self.assertTrue(record.requires_confirmation)
                    self.assertFalse(record.requires_face_step_up)


if __name__ == "__main__":
    unittest.main()
