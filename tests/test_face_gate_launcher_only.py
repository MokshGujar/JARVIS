import unittest

import app.main as app_main


class FaceGateLauncherOnlyTests(unittest.TestCase):
    def test_main_app_does_not_verify_or_step_up_face(self):
        with open("frontend/script.js", encoding="utf-8") as handle:
            script = handle.read()

        self.assertNotIn("/face/verify", script)
        self.assertNotIn("/auth/step-up/start", script)
        self.assertNotIn("/auth/step-up/verify", script)
        self.assertNotIn("face_session_id:", script)
        self.assertNotIn("jarvis_face_session_id", script)
        self.assertIn("/auth/launcher/exchange-bootstrap", script)
        self.assertIn("jarvis_entry_gate_session_id", script)

    def test_main_app_status_poll_is_config_gated(self):
        with open("frontend/script.js", encoding="utf-8") as handle:
            script = handle.read()

        self.assertIn("faceStatusInAppEnabled = faceInApp.status_enabled === true", script)
        self.assertIn("if (!faceStatusInAppEnabled)", script)
        self.assertIn("fetch(`${API}/face/status`", script)

    def test_launcher_keeps_face_status_and_verify_flow(self):
        with open("frontend/launcher.js", encoding="utf-8") as handle:
            script = handle.read()

        self.assertIn("/face/status", script)
        self.assertIn("/face/verify", script)
        self.assertIn("launcher_bootstrap_token", script)
        self.assertIn("scheduleRedirect(redirectUrl)", script)

    def test_main_hud_uses_entry_gate_wording(self):
        with open("frontend/index.html", encoding="utf-8") as handle:
            html = handle.read()

        self.assertIn("Entry Gate: Verified", html)
        self.assertIn("ENTRY GATE: VERIFIED", html)
        self.assertNotIn("Face Recognition: Active", html)
        self.assertNotIn("Permission-required tasks are verified automatically", html)
        self.assertNotIn("FACE AUTH: ACTIVE", html)

    def test_health_face_runtime_distinguishes_gate_and_in_app(self):
        payload = app_main._face_runtime_config(None)

        self.assertTrue(payload["enabled"])
        self.assertEqual(payload["scope"], "launcher_only")
        self.assertFalse(payload["in_app_recognition_enabled"])
        self.assertFalse(payload["in_app_status_enabled"])
        self.assertFalse(payload["in_app_verify_enabled"])
        self.assertFalse(payload["step_up_for_tools_enabled"])


if __name__ == "__main__":
    unittest.main()
