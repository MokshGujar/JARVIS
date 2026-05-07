import unittest
from pathlib import Path
from unittest.mock import Mock

import app.services.chat_service as chat_module
from app.services.chat_service import ChatService
from app.services.phone_command_service import PhoneCommandService


class ChatServiceRoutingTests(unittest.TestCase):
    data_root = Path(__file__).resolve().parent / "_tmp" / "chat_service_routing"

    def setUp(self):
        self.data_root.mkdir(parents=True, exist_ok=True)
        self._old_chats_dir = chat_module.CHATS_DATA_DIR
        chat_module.CHATS_DATA_DIR = self.data_root

    def tearDown(self):
        chat_module.CHATS_DATA_DIR = self._old_chats_dir
        if self.data_root.exists():
            for path in self.data_root.glob("*.json"):
                path.unlink()

    def make_phone_service(self):
        service = PhoneCommandService()
        service._actions_path = self.data_root / "pending_actions.json"
        service._devices_path = self.data_root / "devices.json"
        return service

    def test_time_question_is_answered_locally_without_realtime(self):
        service = ChatService(groq_service=None)

        chunks = list(service.process_jarvis_message_stream("time-test", "can you tell me the time"))

        self.assertTrue(any(chunk == {"activity": {"event": "routing", "route": "local"}} for chunk in chunks))
        self.assertTrue(any(isinstance(chunk, str) and chunk.startswith("It's ") for chunk in chunks))

    def test_call_request_routes_to_phone_service_before_task_brain(self):
        phone_service = self.make_phone_service()
        phone_service.note_device_seen("pixel-test")
        service = ChatService(groq_service=None, phone_command_service=phone_service)

        chunks = list(service.process_jarvis_message_stream("phone-test", "call hitanshi India"))

        self.assertTrue(any(chunk == {"activity": {"event": "routing", "route": "phone"}} for chunk in chunks))
        self.assertTrue(any(isinstance(chunk, str) and "normally or on WhatsApp" in chunk for chunk in chunks))

    def test_message_request_routes_to_phone_service_before_task_brain(self):
        phone_service = self.make_phone_service()
        phone_service.note_device_seen("pixel-test")
        service = ChatService(groq_service=None, phone_command_service=phone_service)

        chunks = list(service.process_jarvis_message_stream("msg-test", "WhatsApp Hitanshi I will call soon"))

        self.assertTrue(any(chunk == {"activity": {"event": "routing", "route": "phone"}} for chunk in chunks))
        self.assertTrue(any(isinstance(chunk, str) and "Drafting a whatsapp to hitanshi" in chunk for chunk in chunks))

    def test_send_whatsapp_message_routes_to_phone_service_before_automation(self):
        phone_service = self.make_phone_service()
        phone_service.note_device_seen("pixel-test")
        service = ChatService(groq_service=None, phone_command_service=phone_service)

        chunks = list(service.process_jarvis_message_stream("msg-test", "send whatsapp message to Alex saying hello"))

        self.assertTrue(any(chunk == {"activity": {"event": "routing", "route": "phone"}} for chunk in chunks))
        self.assertTrue(any(isinstance(chunk, str) and "Drafting a whatsapp to alex" in chunk for chunk in chunks))
        pending = phone_service.get_pending_actions("pixel-test")
        self.assertEqual(pending[0]["channel"], "whatsapp")
        self.assertEqual(pending[0]["contact_name"], "alex")

    def test_polite_text_request_prompts_for_message_body(self):
        phone_service = self.make_phone_service()
        phone_service.note_device_seen("pixel-test")
        service = ChatService(groq_service=None, phone_command_service=phone_service)

        chunks = list(service.process_jarvis_message_stream("msg-test", "Jarvis, can you text Suhani?"))

        self.assertTrue(any(chunk == {"activity": {"event": "routing", "route": "phone"}} for chunk in chunks))
        self.assertTrue(any(isinstance(chunk, str) and "What should I say to suhani?" in chunk for chunk in chunks))

    def test_subject_setting_routes_to_automation_before_general_brain(self):
        automation = Mock()
        automation.has_pending_open_clarification.return_value = False
        automation.has_pending_browser_search.return_value = False
        automation.has_pending_create_file_location.return_value = False
        automation.looks_like_automation_request.return_value = True
        automation.execute.return_value = {"success": True, "action": "subject_updated", "message": "Okay."}
        service = ChatService(groq_service=Mock(), automation_service=automation)

        chunks = list(service.process_jarvis_message_stream("subject-test", "Change the subject to MS Zoni."))

        self.assertTrue(any(chunk == {"activity": {"event": "routing", "route": "automation"}} for chunk in chunks))
        automation.execute.assert_called_once()
        service.groq_service.stream_response.assert_not_called()

    def test_system_status_routes_to_automation_before_general_brain(self):
        automation = Mock()
        automation.has_pending_open_clarification.return_value = False
        automation.has_pending_browser_search.return_value = False
        automation.has_pending_create_file_location.return_value = False
        automation.looks_like_automation_request.return_value = True
        automation.execute.return_value = {"success": True, "action": "safe_command_info", "message": "System OK"}
        service = ChatService(groq_service=Mock(), automation_service=automation)

        chunks = list(service.process_jarvis_message_stream("system-test", "Show system status"))

        self.assertTrue(any(chunk == {"activity": {"event": "routing", "route": "automation"}} for chunk in chunks))
        automation.execute.assert_called_once()
        service.groq_service.stream_response.assert_not_called()


if __name__ == "__main__":
    unittest.main()
