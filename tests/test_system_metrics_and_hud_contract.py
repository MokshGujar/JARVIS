import unittest

import app.main as main_module


def _walk_keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key)
            yield from _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


class SystemMetricsAndHudContractTests(unittest.TestCase):
    def test_system_metrics_schema_contains_safe_public_sections(self):
        metrics = main_module.collect_system_metrics()

        for key in (
            "cpu",
            "memory",
            "disk",
            "network",
            "battery",
            "temperature",
            "protection",
            "connection",
        ):
            self.assertIn(key, metrics)

        self.assertIn("percent", metrics["cpu"])
        self.assertIn("used_label", metrics["memory"])
        self.assertIn("filesystem", metrics["disk"])
        self.assertIn("recv_rate_label", metrics["network"])
        self.assertIn("status", metrics["connection"])

    def test_system_metrics_do_not_expose_sensitive_identity_fields(self):
        metrics = main_module.collect_system_metrics()
        keys = {key.lower() for key in _walk_keys(metrics)}

        for forbidden in ("hostname", "username", "user", "ip", "ipv4", "ipv6", "mac", "address"):
            self.assertNotIn(forbidden, keys)

    def test_app_frontend_preserves_required_dom_ids_once(self):
        with open("frontend/index.html", encoding="utf-8") as handle:
            html = handle.read()

        required_ids = (
            "chat-messages",
            "message-input",
            "send-btn",
            "mic-btn",
            "tts-btn",
            "btn-camera",
            "btn-screen",
            "btn-jarvis",
            "btn-general",
            "btn-realtime",
            "mode-next",
            "mode-prev",
            "mode-slider",
            "mode-switch",
            "orb-container",
            "activity-panel",
            "search-results-widget",
            "settings-panel",
            "vision-panel",
            "speech-widget",
            "speech-widget-text",
        )
        for dom_id in required_ids:
            self.assertEqual(html.count(f'id="{dom_id}"'), 1, dom_id)

    def test_visible_mode_labels_and_greeting_are_removed_from_app_shell(self):
        with open("frontend/index.html", encoding="utf-8") as handle:
            html = handle.read()

        for text in (
            "Smart",
            "Fast",
            "Deep Search",
            "Research",
            "Analyze",
            "Automate",
            "Hello, Sir.",
            "How can I assist you today?",
            "All local systems are synchronized and ready.",
            "Show me a summary of my system status.",
            "Your computer metrics are live.",
        ):
            self.assertNotIn(text, html)

    def test_frontend_action_handling_contract_strings_remain_present(self):
        with open("frontend/script.js", encoding="utf-8") as handle:
            script = handle.read()

        for token in (
            "open_url",
            "open_content",
            "open_image",
            "play_media",
            "download_file",
            "addImageResultMessage",
            "addContentResultMessage",
            "startBackgroundTaskPolling",
        ):
            self.assertIn(token, script)


if __name__ == "__main__":
    unittest.main()
