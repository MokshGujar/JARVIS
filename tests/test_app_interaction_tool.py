import unittest

from app.tools.app_interaction_tool import AppInteractionConfig, AppInteractionTool
from app.tools.base import ToolContext


class FakeAdapter:
    def __init__(self, *, available=True, active_title="Notepad", click_success=True):
        self.available = available
        self.active_title = active_title
        self.click_success = click_success
        self.calls = []

    def is_available(self):
        return self.available

    def get_active_window(self):
        self.calls.append(("get_active_window",))
        if self.active_title is None:
            return {"success": False, "action": "get_active_window", "message": "no active window"}
        return {"success": True, "action": "get_active_window", "title": self.active_title}

    def read_window_title(self):
        self.calls.append(("read_window_title",))
        return {"success": bool(self.active_title), "action": "read_window_title", "title": self.active_title or ""}

    def focus_window(self, title):
        self.calls.append(("focus_window", title))
        return {"success": True, "action": "focus_window", "message": f"Focused {title}.", "title": title}

    def type_text(self, text):
        self.calls.append(("type_text", text))
        return {"success": True, "action": "type_text", "message": "Typed."}

    def press_key(self, key):
        self.calls.append(("press_key", key))
        return {"success": True, "action": "press_key", "message": f"Pressed {key}."}

    def press_hotkey(self, keys):
        self.calls.append(("press_hotkey", tuple(keys)))
        return {"success": True, "action": "press_hotkey", "message": "Pressed hotkey."}

    def click_text(self, text):
        self.calls.append(("click_text", text))
        if not self.click_success:
            return {"success": False, "action": "click_text", "message": f"I could not confidently find {text}."}
        return {"success": True, "action": "click_text", "message": f"Clicked {text}."}

    def click_coordinates(self, x, y):
        self.calls.append(("click_coordinates", x, y))
        return {"success": True, "action": "click_coordinates", "message": "Clicked coordinates."}

    def verify_text_present(self, text):
        self.calls.append(("verify_text_present", text))
        return {"success": True, "action": "verify_text_present", "message": "Text found."}


def tool(adapter, **config_overrides):
    config = AppInteractionConfig(**{"enabled": True, "semantic_actions_enabled": True, **config_overrides})
    return AppInteractionTool(adapter=adapter, config=config)


def context(action, args=None):
    return ToolContext(command="planned", intent="app_interaction", payload={"action": action, "args": args or {}})


class AppInteractionToolTests(unittest.TestCase):
    def test_pywinauto_unavailable_returns_clean_error(self):
        result = tool(FakeAdapter(available=False)).execute(context("type_text", {"text": "hello"}))

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "pywinauto_unavailable")
        self.assertEqual(result["tool_name"], "app_interaction")
        self.assertIn("pywinauto", result["message"].lower())
        self.assertEqual(result["verification_status"], "failed")

    def test_type_text_fails_when_focus_required_and_active_window_unknown(self):
        adapter = FakeAdapter(active_title=None)

        result = tool(adapter).execute(context("type_text", {"text": "hello"}))

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "active_window_unknown")
        self.assertNotIn(("type_text", "hello"), adapter.calls)
        self.assertEqual(result["verification_status"], "blocked")

    def test_type_text_succeeds_through_focused_fake_adapter(self):
        adapter = FakeAdapter(active_title="Untitled - Notepad")

        result = tool(adapter).execute(context("type_text", {"text": "hello"}))

        self.assertTrue(result["success"])
        self.assertIn(("get_active_window",), adapter.calls)
        self.assertIn(("type_text", "hello"), adapter.calls)
        self.assertEqual(result["verification_status"], "likely_success")

    def test_select_address_bar_maps_to_ctrl_l(self):
        adapter = FakeAdapter()

        result = tool(adapter).execute(context("select_address_bar"))

        self.assertTrue(result["success"])
        self.assertIn(("press_hotkey", ("ctrl", "l")), adapter.calls)

    def test_clear_current_field_maps_to_select_all_and_backspace(self):
        adapter = FakeAdapter()

        result = tool(adapter).execute(context("clear_current_field"))

        self.assertTrue(result["success"])
        self.assertIn(("press_hotkey", ("ctrl", "a")), adapter.calls)
        self.assertIn(("press_key", "backspace"), adapter.calls)

    def test_replace_current_field_selects_all_then_types(self):
        adapter = FakeAdapter()

        result = tool(adapter).execute(context("replace_current_field", {"text": "AI news"}))

        self.assertTrue(result["success"])
        self.assertIn(("press_hotkey", ("ctrl", "a")), adapter.calls)
        self.assertIn(("type_text", "AI news"), adapter.calls)

    def test_copy_selection_maps_to_ctrl_c(self):
        adapter = FakeAdapter()

        result = tool(adapter).execute(context("copy_selection"))

        self.assertTrue(result["success"])
        self.assertIn(("press_hotkey", ("ctrl", "c")), adapter.calls)

    def test_paste_text_with_content_types_without_real_clipboard(self):
        adapter = FakeAdapter()

        result = tool(adapter).execute(context("paste_text", {"text": "copied text"}))

        self.assertTrue(result["success"])
        self.assertIn(("type_text", "copied text"), adapter.calls)
        self.assertNotIn(("press_hotkey", ("ctrl", "v")), adapter.calls)

    def test_paste_text_without_content_maps_to_ctrl_v(self):
        adapter = FakeAdapter()

        result = tool(adapter).execute(context("paste_text"))

        self.assertTrue(result["success"])
        self.assertIn(("press_hotkey", ("ctrl", "v")), adapter.calls)

    def test_browser_and_editing_hotkeys_map_to_safe_actions(self):
        cases = {
            "open_new_tab": ("ctrl", "t"),
            "close_current_tab": ("ctrl", "w"),
            "browser_back": ("alt", "left"),
            "refresh": ("ctrl", "r"),
            "undo": ("ctrl", "z"),
            "redo": ("ctrl", "y"),
        }
        for action, keys in cases.items():
            with self.subTest(action=action):
                adapter = FakeAdapter()
                result = tool(adapter).execute(context(action))
                self.assertTrue(result["success"])
                self.assertIn(("press_hotkey", keys), adapter.calls)

    def test_click_coordinates_is_blocked_when_disabled(self):
        adapter = FakeAdapter()

        result = tool(adapter, click_coordinates_enabled=False).execute(context("click_coordinates", {"x": 500, "y": 500}))

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "coordinate_click_disabled")
        self.assertNotIn(("click_coordinates", 500, 500), adapter.calls)
        self.assertEqual(result["verification_status"], "blocked")

    def test_click_text_returns_clean_failure_when_target_not_confident(self):
        adapter = FakeAdapter(click_success=False)

        result = tool(adapter).execute(context("click_text", {"text": "Continue"}))

        self.assertFalse(result["success"])
        self.assertIsNone(result["error"])
        self.assertIn("could not confidently find", result["message"].lower())
        self.assertEqual(result["verification_status"], "failed")

    def test_unsupported_action_returns_normalized_result(self):
        result = tool(FakeAdapter()).execute(context("not_a_real_action"))

        self.assertFalse(result["success"])
        for key in ("success", "action", "message", "tool_name", "error", "data", "safety_level"):
            self.assertIn(key, result)
        self.assertEqual(result["action"], "not_a_real_action")


if __name__ == "__main__":
    unittest.main()
