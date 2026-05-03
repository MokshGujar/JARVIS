import asyncio
import time
import unittest
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import run
import app.main as app_main
from app.models import FaceEnrollBatchRequest, FaceVerifyRequest
from app.services.launcher_bootstrap_service import LauncherBootstrapService


class LauncherBootstrapServiceTests(unittest.TestCase):
    def test_bootstrap_token_is_single_use(self):
        service = LauncherBootstrapService(ttl_seconds=30)
        created = service.create("face-session")
        token = created["launcher_bootstrap_token"]

        first = service.exchange(token)
        second = service.exchange(token)

        self.assertTrue(first.ok)
        self.assertEqual(first.face_session_id, "face-session")
        self.assertFalse(second.ok)
        self.assertIn(second.reason, {"bootstrap_token_unknown", "bootstrap_token_reused"})

    def test_expired_bootstrap_token_is_rejected(self):
        service = LauncherBootstrapService(ttl_seconds=30)
        created = service.create("face-session")
        token = created["launcher_bootstrap_token"]
        service._tokens[token]["expires_at"] = time.time() - 1

        exchanged = service.exchange(token)

        self.assertFalse(exchanged.ok)
        self.assertEqual(exchanged.reason, "bootstrap_token_expired")

    def test_unknown_bootstrap_token_is_rejected(self):
        service = LauncherBootstrapService(ttl_seconds=30)
        exchanged = service.exchange("missing")

        self.assertFalse(exchanged.ok)
        self.assertEqual(exchanged.reason, "bootstrap_token_unknown")


class RunStartupTests(unittest.TestCase):
    def test_backend_readiness_timeout_blocks_launch(self):
        with patch("urllib.request.urlopen", side_effect=OSError("not ready")):
            self.assertFalse(run.wait_for_health(timeout_seconds=0.01, interval_seconds=0))

    def test_backend_subprocess_cleanup_policy(self):
        self.assertFalse(run.should_stop_backend_after_launcher(browser_opened=False, keep_backend=False))
        self.assertFalse(run.should_stop_backend_after_launcher(browser_opened=False, keep_backend=True))
        self.assertFalse(run.should_stop_backend_after_launcher(browser_opened=True, keep_backend=False))

    def test_browser_launcher_opens_launcher_url(self):
        with patch("run._preferred_browser_launchers", return_value=[]), patch("webbrowser.open", return_value=True) as mocked_open:
            self.assertTrue(run.open_browser_launcher())
        mocked_open.assert_called_once_with("http://localhost:8000/launcher/", new=1)

    def test_browser_launcher_prefers_supported_windows_browser(self):
        with patch("run._preferred_browser_launchers", return_value=[["chrome.exe", "--new-window", "http://localhost:8000/launcher/"]]), patch("subprocess.Popen") as mocked_popen, patch("webbrowser.open") as mocked_open:
            self.assertTrue(run.open_browser_launcher())
        mocked_popen.assert_called_once()
        mocked_open.assert_not_called()

    def test_wake_word_and_voice_auth_are_not_reintroduced(self):
        self.assertFalse(hasattr(run, "BackendSupervisor"))
        self.assertFalse(hasattr(run, "WAKE_PHRASES"))
        with open("run.py", encoding="utf-8") as handle:
            contents = handle.read()
        self.assertNotIn("wake_word_listener", contents)
        self.assertNotIn("tkinter", contents.lower())
        self.assertNotIn("PySide6", contents)


class BackendVerifyLauncherTests(unittest.TestCase):
    def setUp(self):
        self.original_face_identity_service = app_main.face_identity_service
        self.original_launcher_bootstrap_service = app_main.launcher_bootstrap_service

    def tearDown(self):
        app_main.face_identity_service = self.original_face_identity_service
        app_main.launcher_bootstrap_service = self.original_launcher_bootstrap_service

    def test_launcher_verify_returns_bootstrap_token_and_echoes_request_id(self):
        class FaceIdentity:
            def verify_frames(self, *_args, **kwargs):
                return {
                    "status": "verified",
                    "verified": True,
                    "allowed": True,
                    "reason": "verified_match",
                    "face_session_id": "face-session",
                    "request_id": kwargs.get("request_id") or "",
                    "quality": {"passed": True, "face_count": 1},
                    "liveness": {"is_live": True},
                }

        app_main.face_identity_service = FaceIdentity()
        app_main.launcher_bootstrap_service = LauncherBootstrapService(ttl_seconds=30)

        payload = asyncio.run(
            app_main.face_verify(
                FaceVerifyRequest(
                    frames=["frame"],
                    client_id="launcher",
                    request_id="launcher-123",
                )
            )
        )

        self.assertEqual(payload["status"], "verified")
        self.assertEqual(payload["request_id"], "launcher-123")
        self.assertTrue(payload["launcher_bootstrap_token"])
        self.assertGreater(payload["bootstrap_expires_in_seconds"], 0)
        self.assertEqual(payload["face_session_id"], "")

    def test_deprecated_create_bootstrap_endpoint_still_works(self):
        class FaceIdentity:
            def validate_session(self, session_id):
                return session_id == "face-session"

        app_main.face_identity_service = FaceIdentity()
        app_main.launcher_bootstrap_service = LauncherBootstrapService(ttl_seconds=30)

        payload = asyncio.run(
            app_main.auth_launcher_create_bootstrap(
                app_main.LauncherBootstrapCreateRequest(face_session_id="face-session")
            )
        )

        self.assertTrue(payload["created"])
        self.assertTrue(payload["launcher_bootstrap_token"])


class BackendEnrollBatchTests(unittest.TestCase):
    def setUp(self):
        self.original_face_enrollment_service = app_main.face_enrollment_service

    def tearDown(self):
        app_main.face_enrollment_service = self.original_face_enrollment_service

    def test_enroll_batch_route_uses_batch_service(self):
        class Enrollment:
            def add_batch(self, session_id, frames):
                return {
                    "enrollment_session_id": session_id,
                    "accepted_count": len(frames),
                    "rejected_count": 0,
                    "duplicate_count": 0,
                    "quality_failed_count": 0,
                    "accepted_samples": len(frames),
                    "required_samples": 20,
                    "preferred_samples": 20,
                    "can_complete": True,
                    "guidance": "Good",
                }

        app_main.face_enrollment_service = Enrollment()

        payload = asyncio.run(
            app_main.face_enroll_batch(
                FaceEnrollBatchRequest(enrollment_session_id="enroll-session", frames=["a", "b"])
            )
        )

        self.assertEqual(payload["accepted_count"], 2)
        self.assertEqual(payload["required_samples"], 20)
        self.assertEqual(payload["preferred_samples"], 20)


class LauncherRoutingTests(unittest.TestCase):
    def test_launcher_page_route_points_to_launcher_html(self):
        response = asyncio.run(app_main.launcher_page())
        self.assertTrue(str(response.path).endswith("frontend\\launcher.html") or str(response.path).endswith("frontend/launcher.html"))

    def test_launcher_asset_routes_are_isolated(self):
        css_response = asyncio.run(app_main.launcher_css())
        js_response = asyncio.run(app_main.launcher_js())
        self.assertTrue(str(css_response.path).endswith("frontend\\launcher.css") or str(css_response.path).endswith("frontend/launcher.css"))
        self.assertTrue(str(js_response.path).endswith("frontend\\launcher.js") or str(js_response.path).endswith("frontend/launcher.js"))

    def test_enroll_routes_serve_dedicated_assets(self):
        page_response = asyncio.run(app_main.enroll_page())
        css_response = asyncio.run(app_main.enroll_css())
        js_response = asyncio.run(app_main.enroll_js())
        self.assertTrue(str(page_response.path).endswith("frontend\\enroll.html") or str(page_response.path).endswith("frontend/enroll.html"))
        self.assertTrue(str(css_response.path).endswith("frontend\\enroll.css") or str(css_response.path).endswith("frontend/enroll.css"))
        self.assertTrue(str(js_response.path).endswith("frontend\\enroll.js") or str(js_response.path).endswith("frontend/enroll.js"))

    def test_root_redirects_to_launcher(self):
        response = asyncio.run(app_main.root_redirect())
        self.assertEqual(response.headers["location"], "/launcher/")


class FrontendSourceTests(unittest.TestCase):
    def test_app_frontend_exchanges_and_clears_bootstrap_token(self):
        with open("frontend/script.js", encoding="utf-8") as handle:
            script = handle.read()

        self.assertIn("/auth/launcher/exchange-bootstrap", script)
        self.assertIn("localStorage.setItem('jarvis_entry_gate_session_id'", script)
        self.assertIn("url.searchParams.delete('bootstrap_token')", script)
        self.assertIn("window.history.replaceState", script)
        self.assertNotIn("face_session_id=", script)

    def test_launcher_html_uses_isolated_assets_and_reuses_app_style(self):
        with open("frontend/launcher.html", encoding="utf-8") as handle:
            html = handle.read()

        self.assertIn('/app/style.css', html)
        self.assertIn('/launcher/launcher.css', html)
        self.assertIn('/launcher/launcher.js', html)

    def test_enroll_html_uses_isolated_assets_and_reuses_app_style(self):
        with open("frontend/enroll.html", encoding="utf-8") as handle:
            html = handle.read()

        self.assertIn('/app/style.css', html)
        self.assertIn('/enroll/enroll.css', html)
        self.assertIn('/enroll/enroll.js', html)

    def test_launcher_js_uses_request_id_timeout_redirect_and_cleanup(self):
        with open("frontend/launcher.js", encoding="utf-8") as handle:
            script = handle.read()

        self.assertIn("getUserMedia", script)
        self.assertIn("request_id", script)
        self.assertIn("AbortController", script)
        self.assertIn("FIRST_VERIFY_TIMEOUT_MS = 25000", script)
        self.assertIn("VERIFY_TIMEOUT_MS = 12000", script)
        self.assertIn("SUCCESS_REDIRECT_DELAY_MS = 500", script)
        self.assertIn("scheduleRedirect(redirectUrl)", script)
        self.assertNotIn("window.location.assign(redirectUrl)", script)
        self.assertIn("redirectTimerHandle", script)
        self.assertIn("clearTimeout(redirectTimerHandle)", script)
        self.assertIn("Initializing camera...", script)
        self.assertIn("Initializing face engine...", script)
        self.assertIn("Verifying face...", script)
        self.assertIn("Verification timeout. Try again.", script)
        self.assertIn("Face profile not enrolled", script)
        self.assertIn("fetchFaceStatus()", script)
        self.assertIn("isFaceProfileEnrolled", script)
        self.assertLess(script.index("fetchFaceStatus()"), script.index("/face/verify"))
        self.assertIn("setCameraReady(true)", script)
        self.assertIn("setCameraReady(false)", script)
        self.assertLess(script.index("'Checking face-gate status before verification.'"), script.index("'Sending live frames to backend verification.'"))
        self.assertLess(script.index("recordBackendFailedAttempt(payload)"), script.index("mapVerifyFailure(payload)"))
        self.assertIn("triggerErrorShake()", script)
        self.assertIn("pagehide", script)
        self.assertIn("beforeunload", script)
        self.assertIn("activeRequestId !== requestId", script)
        self.assertIn("window.location.assign('/enroll/')", script)
        self.assertNotIn("/app/?mode=enroll", script)
        self.assertNotIn("localStorage", script)
        self.assertNotIn("sessionStorage", script)
        self.assertNotIn("console.log", script)

    def test_launcher_js_handles_permission_denied_separately(self):
        with open("frontend/launcher.js", encoding="utf-8") as handle:
            script = handle.read()

        self.assertIn("Camera permission denied", script)
        self.assertIn("Camera unavailable", script)
        self.assertIn("event.key !== 'Enter'", script)

    def test_launcher_css_has_mobile_layout_rules(self):
        with open("frontend/launcher.css", encoding="utf-8") as handle:
            css = handle.read()

        self.assertIn("--hud-header-h: clamp(110px, 16vh, 150px)", css)
        self.assertIn("--hud-bottom-h: clamp(120px, 18vh, 155px)", css)
        self.assertIn("--scanner-size: clamp(300px, min(38vw, 46vh), 440px)", css)
        self.assertIn("grid-template-rows: var(--hud-header-h) minmax(0, 1fr) var(--hud-bottom-h)", css)
        self.assertIn(".launcher-action-row", css)
        self.assertIn("z-index: 20", css)
        self.assertIn("@media (max-height: 760px)", css)
        self.assertIn("@media (max-height: 680px)", css)
        self.assertIn("@media (max-width: 1100px)", css)
        self.assertIn("@media (max-width: 720px)", css)
        self.assertIn(".launcher-app", css)
        self.assertIn(".launcher-app.is-camera-ready .launcher-camera-video", css)
        self.assertIn("@keyframes launcher-subtle-shake", css)
        self.assertIn("is-error-shaking", css)
        self.assertIn("overflow-x: hidden", css)

    def test_enroll_js_uses_enrollment_apis_and_launcher_redirect_only(self):
        with open("frontend/enroll.js", encoding="utf-8") as handle:
            script = handle.read()
        with open("frontend/enroll.html", encoding="utf-8") as handle:
            html = handle.read()

        self.assertIn("getUserMedia", script)
        self.assertIn("/face/enroll/start", script)
        self.assertIn("/face/enroll/batch", script)
        self.assertIn("/face/enroll/complete", script)
        self.assertIn("CAPTURE_FRAME_COUNT = 60", script)
        self.assertIn("CAPTURE_INTERVAL_MS = 100", script)
        self.assertIn("CAPTURE_BATCH_SIZE = 6", script)
        self.assertIn("CAPTURE_FRAME_MAX_WIDTH = 480", script)
        self.assertIn("FIRST_ENROLL_BATCH_TIMEOUT_MS = 30000", script)
        self.assertIn("ENROLL_BATCH_TIMEOUT_MS = 15000", script)
        self.assertIn("STATUS_MIN_VISIBLE_MS = 350", script)
        self.assertIn("pauseButton", script)
        self.assertIn("resumeButton", script)
        self.assertIn("completeButton", script)
        self.assertIn("cancelButton", script)
        self.assertIn("progress-ring-value", html)
        self.assertIn("progress-bar-fill", html)
        self.assertIn("attempt-counter", html)
        self.assertIn("enroll-action-row", html)
        self.assertIn("debug-panel", html)
        self.assertIn("Accepted: ${acceptedSamples} / ${preferredSamples}", script)
        self.assertIn("payload.total_rejected_count", script)
        self.assertIn("accepted-stat", html)
        self.assertIn("captured-stat", html)
        self.assertIn("quality-stat", html)
        self.assertIn("payload.can_complete", script)
        self.assertIn("payload.auto_complete", script)
        self.assertIn("Processing burst...", script)
        self.assertIn("request_timeout", script)
        self.assertIn("updateDebugPanel", script)
        self.assertIn("window.location.assign('/launcher/')", script)
        self.assertIn("RESTART ENROLLMENT", html)
        self.assertIn("PAUSE ENROLLMENT", html)
        self.assertIn("RESUME ENROLLMENT", html)
        self.assertIn("COMPLETE ENROLLMENT", html)
        self.assertIn("RETURN TO LAUNCHER", html)
        self.assertIn("Look straight at the camera.", script)
        self.assertIn("Change expression naturally.", script)
        self.assertIn("Try a different lighting angle if possible.", script)
        self.assertIn("Capturing secure face profile...", script)
        self.assertIn("Quality: Good", script)
        self.assertIn("Lighting is too low. Move closer to a light source.", script)
        self.assertIn("Hold still. Reduce motion.", script)
        self.assertIn("Keep same face, avoid extreme angles.", script)
        self.assertIn("Move slightly", script)
        self.assertIn("Move closer", script)
        self.assertNotIn("/face/verify", script)
        self.assertNotIn("/face/enroll/sample", script)
        self.assertNotIn("/auth/launcher", script)
        self.assertNotIn("face_session_id", script)
        self.assertNotIn("launcher_bootstrap_token", script)
        self.assertNotIn("localStorage", script)
        self.assertNotIn("sessionStorage", script)
        self.assertNotIn("console.log", script)

    def test_enroll_css_and_required_samples_defaults_exist(self):
        with open("frontend/enroll.css", encoding="utf-8") as handle:
            css = handle.read()
        with open("config.py", encoding="utf-8") as handle:
            config_text = handle.read()

        self.assertIn('FACE_IDENTITY_REQUIRED_SAMPLES = _getenv_int("FACE_IDENTITY_REQUIRED_SAMPLES", 20)', config_text)
        self.assertIn('FACE_IDENTITY_PREFERRED_SAMPLES = _getenv_int("FACE_IDENTITY_PREFERRED_SAMPLES", 20)', config_text)
        self.assertIn('FACE_IDENTITY_MAX_STORED_SAMPLES = _getenv_int("FACE_IDENTITY_MAX_STORED_SAMPLES", 25)', config_text)
        self.assertIn('FACE_ENROLLMENT_BURST_FRAME_COUNT = _getenv_int("FACE_ENROLLMENT_BURST_FRAME_COUNT", 60)', config_text)
        self.assertIn('FACE_ENROLLMENT_BURST_INTERVAL_MS = _getenv_int("FACE_ENROLLMENT_BURST_INTERVAL_MS", 100)', config_text)
        self.assertIn('FACE_ENROLLMENT_BATCH_SIZE = _getenv_int("FACE_ENROLLMENT_BATCH_SIZE", 6)', config_text)
        self.assertIn('FACE_ENROLLMENT_MAX_MODEL_FRAMES_PER_BATCH = _getenv_int("FACE_ENROLLMENT_MAX_MODEL_FRAMES_PER_BATCH", 3)', config_text)
        self.assertIn('FACE_ENROLLMENT_FRAME_MAX_WIDTH = _getenv_int("FACE_ENROLLMENT_FRAME_MAX_WIDTH", 480)', config_text)
        self.assertIn(".enroll-app", css)
        self.assertIn("--hud-header-h: clamp(110px, 16vh, 150px)", css)
        self.assertIn("--hud-bottom-h: clamp(120px, 18vh, 155px)", css)
        self.assertIn("--scanner-size: clamp(300px, min(38vw, 46vh), 440px)", css)
        self.assertIn("grid-template-rows: var(--hud-header-h) minmax(0, 1fr) var(--hud-bottom-h)", css)
        self.assertIn(".enroll-action-row", css)
        self.assertIn("z-index: 20", css)
        self.assertIn("@media (max-height: 760px)", css)
        self.assertIn("@media (max-height: 680px)", css)
        self.assertIn(".enroll-app.is-camera-ready .enroll-camera-video", css)
        self.assertIn("@media (max-width: 1100px)", css)
        self.assertIn("@media (max-width: 720px)", css)


if __name__ == "__main__":
    unittest.main()
