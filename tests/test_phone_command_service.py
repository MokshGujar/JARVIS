import unittest
from pathlib import Path

from app.services.phone_command_service import PhoneCommandService


class PhoneCommandServiceTests(unittest.TestCase):
    data_root = Path(__file__).resolve().parent / "_phone_service_data"

    def tearDown(self):
        if self.data_root.exists():
            for path in self.data_root.glob("*.json"):
                path.unlink()

    def make_service(self):
        root = self.data_root
        root.mkdir(exist_ok=True)
        for name in ("pending_actions.json", "devices.json"):
            path = root / name
            if path.exists():
                path.unlink()
        service = PhoneCommandService()
        service._actions_path = root / "pending_actions.json"
        service._devices_path = root / "devices.json"
        service._contacts_snapshot_path = root / "contacts_snapshot.json"
        return service

    def test_queue_and_acknowledge_phone_action(self):
        service = self.make_service()

        service.note_device_seen("pixel-test")
        queued = service.queue_answer_call()

        self.assertTrue(queued["success"])
        pending = service.get_pending_actions("pixel-test")
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["action_type"], "answer_call")

        self.assertTrue(service.acknowledge_action(pending[0]["action_id"], device_id="pixel-test"))
        self.assertEqual(service.get_pending_actions("pixel-test"), [])

    def test_place_call_followup_uses_pending_contact(self):
        service = self.make_service()

        service.note_device_seen("pixel-test")
        prompt = service.handle_place_call_request("call Tony", device_id="pixel-test")
        self.assertFalse(prompt["success"])
        self.assertIn("normally or on WhatsApp", prompt["message"])

        queued = service.handle_call_method_followup("whatsapp")
        self.assertIsNotNone(queued)
        self.assertTrue(queued["success"])
        pending = service.get_pending_actions("pixel-test")
        self.assertEqual(pending[0]["action_type"], "place_call")
        self.assertEqual(pending[0]["contact_name"], "tony")
        self.assertEqual(pending[0]["call_method"], "whatsapp")

    def test_phone_request_classification_ignores_jarvis_prefix(self):
        service = self.make_service()

        service.note_device_seen("pixel-test")
        result = service.route_phone_request("Jarvis pick up the phone")

        self.assertIsNotNone(result)
        self.assertTrue(result["success"])
        pending = service.get_pending_actions("pixel-test")
        self.assertEqual(pending[0]["action_type"], "answer_call")

    def test_whatsapp_message_request_queues_protected_draft(self):
        service = self.make_service()

        service.note_device_seen("pixel-test")
        result = service.route_phone_request("Jarvis WhatsApp Hitanshi I'll call in 5 minutes")

        self.assertIsNotNone(result)
        self.assertTrue(result["success"])
        pending = service.get_pending_actions("pixel-test")
        self.assertEqual(pending[0]["action_type"], "draft_message")
        self.assertEqual(pending[0]["contact_name"], "hitanshi")
        self.assertEqual(pending[0]["channel"], "whatsapp")
        self.assertEqual(pending[0]["message_body"], "i'll call in 5 minutes")
        self.assertTrue(pending[0]["requires_verified_speaker"])

    def test_send_whatsapp_message_phrase_queues_protected_draft(self):
        service = self.make_service()

        service.note_device_seen("pixel-test")
        result = service.route_phone_request("send whatsapp message to Alex saying hello")

        self.assertIsNotNone(result)
        self.assertTrue(result["success"])
        pending = service.get_pending_actions("pixel-test")
        self.assertEqual(pending[0]["action_type"], "draft_message")
        self.assertEqual(pending[0]["contact_name"], "alex")
        self.assertEqual(pending[0]["channel"], "whatsapp")
        self.assertEqual(pending[0]["message_body"], "hello")
        self.assertTrue(pending[0]["requires_verified_speaker"])

    def test_message_request_asks_for_channel_then_queues(self):
        service = self.make_service()

        service.note_device_seen("pixel-test")
        prompt = service.route_phone_request("message Tony saying reaching late")
        self.assertIsNotNone(prompt)
        self.assertFalse(prompt["success"])
        self.assertIn("SMS or WhatsApp", prompt["message"])

        queued = service.route_phone_request("sms")
        self.assertIsNotNone(queued)
        self.assertTrue(queued["success"])
        pending = service.get_pending_actions("pixel-test")
        self.assertEqual(pending[0]["action_type"], "draft_message")
        self.assertEqual(pending[0]["contact_name"], "tony")
        self.assertEqual(pending[0]["channel"], "sms")
        self.assertEqual(pending[0]["message_body"], "reaching late")

    def test_sync_contacts_provides_desktop_contact_candidates(self):
        service = self.make_service()

        result = service.sync_contacts("pixel-test", [
            {
                "contact_id": "h1",
                "display_name": "Hetanshi India",
                "phone_number": "+919999999999",
                "aliases": ["hetanshi"],
                "favorite": True,
                "recent": True,
                "frequent": True,
            }
        ])
        contacts = service.list_synced_contacts()

        self.assertTrue(result["success"])
        self.assertEqual(result["count"], 1)
        self.assertEqual(contacts[0].display_name, "Hetanshi India")
        self.assertEqual(contacts[0].phone_number, "+919999999999")
        self.assertTrue(contacts[0].favorite)

    def test_phone_call_uses_unified_contact_resolution_when_contacts_are_synced(self):
        service = self.make_service()
        service.note_device_seen("pixel-test")
        service.sync_contacts("pixel-test", [
            {
                "contact_id": "h1",
                "display_name": "Hetanshi India",
                "phone_number": "+919999999999",
            }
        ])

        result = service.route_phone_request("call Hetanshi India on WhatsApp", device_id="pixel-test")

        self.assertTrue(result["success"])
        pending = service.get_pending_actions("pixel-test")
        self.assertEqual(pending[0]["contact_name"], "Hetanshi India")
        self.assertEqual(pending[0]["phone_number"], "+919999999999")
        self.assertEqual(pending[0]["contact_id"], "h1")
        self.assertEqual(pending[0]["call_method"], "whatsapp")

    def test_stt_contact_variant_clarifies_before_phone_action(self):
        service = self.make_service()
        service.note_device_seen("pixel-test")
        service.sync_contacts("pixel-test", [
            {
                "contact_id": "h1",
                "display_name": "Hetanshi India",
                "phone_number": "+919999999999",
            }
        ])

        result = service.route_phone_request("call Hitanchi India on WhatsApp", device_id="pixel-test")

        self.assertFalse(result["success"])
        self.assertTrue(result["requires_followup"])
        self.assertIn("Hetanshi India", result["message"])
        self.assertEqual(service.get_pending_actions("pixel-test"), [])


if __name__ == "__main__":
    unittest.main()
