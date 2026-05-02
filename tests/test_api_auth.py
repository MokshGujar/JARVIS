import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import app.main as main


class FakePhoneCommandService:
    def note_device_seen(self, device_id):
        self.last_device_id = device_id

    def get_pending_actions(self, device_id="", phone_number=""):
        return []


class ApiTokenTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.old_phone_service = main.phone_command_service
        self.old_caller_service = main.caller_lookup_service
        main.phone_command_service = FakePhoneCommandService()
        main.caller_lookup_service = None

    def tearDown(self):
        main.phone_command_service = self.old_phone_service
        main.caller_lookup_service = self.old_caller_service

    def test_configured_token_rejects_missing_header(self):
        with patch.object(main, "PHONE_BRIDGE_TOKEN", "secret-token"):
            response = self.client.post(
                "/phone/incoming-call",
                json={"phone_number": "+10000000000"},
            )

        self.assertEqual(response.status_code, 401)

    def test_agent_endpoint_requires_configured_token(self):
        with patch.object(main, "PHONE_BRIDGE_TOKEN", "secret-token"):
            response = self.client.post(
                "/agent",
                json={"message": "hello"},
            )

        self.assertEqual(response.status_code, 401)

    def test_configured_token_rejects_wrong_header(self):
        with patch.object(main, "PHONE_BRIDGE_TOKEN", "secret-token"):
            response = self.client.post(
                "/phone/incoming-call",
                headers={"X-Jarvis-Token": "wrong-token"},
                json={"phone_number": "+10000000000"},
            )

        self.assertEqual(response.status_code, 401)

    def test_configured_token_accepts_correct_header(self):
        with patch.object(main, "PHONE_BRIDGE_TOKEN", "secret-token"):
            response = self.client.post(
                "/phone/incoming-call",
                headers={"X-Jarvis-Token": "secret-token"},
                json={"phone_number": "+10000000000"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["source"], "basic_fallback")

    def test_empty_token_preserves_local_dev_behavior(self):
        with patch.object(main, "PHONE_BRIDGE_TOKEN", ""):
            response = self.client.post(
                "/phone/incoming-call",
                json={"phone_number": "+10000000000"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["source"], "basic_fallback")


if __name__ == "__main__":
    unittest.main()
