from pathlib import Path
import shutil

import app.services.chat_service as chat_module
from app.services.capability_summary_service import CapabilitySummaryService
from app.services.chat_service import ChatService


class FakeUnavailableGmail:
    def status(self):
        return {
            "available": False,
            "status": "not_configured",
            "message": "Gmail connector is not configured.",
        }


class ExplodingGroq:
    def stream_response(self, *args, **kwargs):
        raise AssertionError("LLM should not be called for capability summary")


def test_what_can_you_do_is_deterministic_and_truthful():
    service = CapabilitySummaryService(gmail_connector=FakeUnavailableGmail())

    answer = service.answer("What can you do?")

    assert "search and read local files" in answer
    assert "Gmail is not configured" in answer
    assert "Terminal execution is proposal-only" in answer
    assert "LangGraph agents are disabled" in answer


def test_specific_capability_questions_use_runtime_status():
    service = CapabilitySummaryService(gmail_connector=FakeUnavailableGmail())

    assert "Gmail is unavailable" in service.answer("Can you send email?")
    assert "Developer Mode is disabled" in service.answer("Can you run terminal commands?")
    assert "Destructive actions stay protected" in service.answer("Can you access my laptop?")
    assert "WhatsApp" in service.answer("Can you use WhatsApp?")


def test_chat_service_routes_capability_summary_without_llm():
    temp_dir = Path(__file__).resolve().parent / "_tmp" / "capability_summary"
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir(parents=True)
    old_chats_dir = chat_module.CHATS_DATA_DIR
    chat_module.CHATS_DATA_DIR = temp_dir
    try:
        service = ChatService(
            groq_service=ExplodingGroq(),
            capability_summary_service=CapabilitySummaryService(gmail_connector=FakeUnavailableGmail()),
        )

        chunks = list(service.process_jarvis_message_stream("cap-test", "What tools do you have?"))
    finally:
        chat_module.CHATS_DATA_DIR = old_chats_dir
        if temp_dir.exists():
            shutil.rmtree(temp_dir)

    assert {"activity": {"event": "routing", "route": "capability_summary"}} in chunks
    assert any(isinstance(chunk, str) and "Gmail is not configured" in chunk for chunk in chunks)
