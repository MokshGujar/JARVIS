import base64
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Iterator, Any, Union

from config import CHATS_DATA_DIR, CAMERA_CAPTURES_DIR, MAX_CHAT_HISTORY_TURNS, GROQ_API_KEYS
from app.models import ChatMessage
from app.services.groq_service import GroqService
from app.services.realtime_service import RealtimeGroqService
from app.services.brain_service import BrainService
from app.services.decision_types import (
    CATEGORY_GENERAL,
    CATEGORY_REALTIME,
    CATEGORY_CAMERA,
    CATEGORY_TASK,
    CATEGORY_MIXED,
    HEAVY_INTENTS,
    INSTANT_INTENTS,
)
from app.services.task_executor import TaskExecutor, TaskResponse
from app.services.task_manager import TaskManager
from app.services.vision_service import VisionService
from app.services.automation_service import AutomationService
from app.services.wake_on_lan_service import WakeOnLanService
from app.services.phone_command_service import PhoneCommandService
from app.services.reminder_service import ReminderService
from app.services.research_tools_service import ResearchToolsService
from app.utils.key_rotation import get_next_key_pair
from app.services.chat_session_store import ChatSessionStore
from app.core.contracts import AssistantRequest

CAMERA_BYPASS_TOKEN = "TTCAMTOKENTT"


def _save_camera_image(img_base64: str, session_id: str) -> Optional[Path]:
    if not img_base64 or not CAMERA_CAPTURES_DIR:
        return None

    raw = img_base64.split(",", 1)[-1] if "," in img_base64 else img_base64

    try:
        data = base64.b64decode(raw)
        if len(data) < 1000:
            logger.warning(
                "[VISION] Captured image very small (%d bytes), may be invalid",
                len(data),
            )

        ts = time.strftime("%Y%m%d_%H%M%S", time.localtime())
        safe_id = (session_id or "").replace("/", "_")[:16] or "unknown"
        filename = f"cam_{safe_id}_{ts}.jpg"

        path = CAMERA_CAPTURES_DIR / filename
        path.write_bytes(data)

        logger.info(
            "[VISION] Saved camera capture: %s (%d bytes) -> %s",
            path.name,
            len(data),
            path,
        )

        return path

    except Exception as e:
        logger.warning("[VISION] Failed to save camera image: %s", e)
        return None

logger = logging.getLogger("J.A.R.V.I.S")

JARVIS_BRAIN_SEARCH_TIMEOUT = 15
SAVE_EVERY_N_CHUNKS = 5


class ChatService:
    def __init__(
        self,
        groq_service: GroqService,
        realtime_service: RealtimeGroqService = None,
        brain_service=None,
        task_executor: TaskExecutor = None,
        vision_service: VisionService = None,
        task_manager: TaskManager = None,
        automation_service: AutomationService = None,
        wake_on_lan_service: WakeOnLanService = None,
        phone_command_service: PhoneCommandService = None,
        reminder_service: ReminderService = None,
        research_tools_service: ResearchToolsService = None,
    ):
        self.groq_service = groq_service
        self.realtime_service = realtime_service
        self.brain_service = brain_service
        self.task_executor = task_executor
        self.vision_service = vision_service
        self.task_manager = task_manager
        self.automation_service = automation_service
        self.wake_on_lan_service = wake_on_lan_service
        self.phone_command_service = phone_command_service
        self.reminder_service = reminder_service
        self.research_tools_service = research_tools_service

        self._session_store = ChatSessionStore(CHATS_DATA_DIR, MAX_CHAT_HISTORY_TURNS)
        self.sessions = self._session_store.sessions
        self.orchestrator = None

    def _instant_local_answer(self, user_message: str) -> Optional[str]:
        text = " ".join((user_message or "").strip().lower().split())
        if not text:
            return None
        text = text.strip(" .,!?\t\r\n")
        for name in ("jarvis", "javis", "jervis"):
            if text == name:
                break
            if text.startswith(name):
                rest = text[len(name):].lstrip(" .,!?\t\r\n")
                if rest != text:
                    text = rest
                    break

        time_patterns = (
            "what time is it",
            "tell me the time",
            "current time",
            "time now",
            "what's the time",
            "whats the time",
            "can you tell me the time",
        )
        if any(pattern in text for pattern in time_patterns):
            return f"It's {datetime.now().strftime('%I:%M %p').lstrip('0')}."

        if text in {"hello", "hi", "hey", "good morning", "good afternoon", "good evening"}:
            return "Hello. I'm ready."

        if text in {"how are you", "how are you doing", "what's up", "whats up"}:
            return "I'm online and running smoothly."

        if text in {"thanks", "thank you", "thank you jarvis", "no thanks"}:
            return "Anytime."

        if text in {"uh", "um", "hmm", "mm", "jarvis", "javis", "jervis"}:
            return "I'm here. Tell me what you need."

        return None

    def _looks_like_mixed_action_and_chat(self, user_message: str) -> bool:
        text = " ".join((user_message or "").strip().lower().split())
        if not text:
            return False

        has_action = any(
            token in text
            for token in (
                "open ", "launch ", "go to ", "visit ", "play ", "put on ",
                "generate ", "draw ", "create an image", "make a picture",
                "write ", "draft ", "compose ",
            )
        )
        has_chat_request = any(
            token in text
            for token in (
                "tell me", "what is", "what are", "who is", "who are",
                "how does", "how do", "explain", "analysis", "fun fact",
            )
        )
        return has_action and has_chat_request
    def load_session_from_disk(self, session_id: str) -> bool:
        return self._session_store.load_session_from_disk(session_id)
    
    def validate_session_id(self, session_id: str) -> bool:
        return self._session_store.validate_session_id(session_id)
    
    def get_or_create_session(self, session_id: Optional[str] = None) -> str:
        return self._session_store.get_or_create_session(session_id)
    
    def add_message(self, session_id: str, role: str, content: str):
        self._session_store.add_message(session_id, role, content)


    def get_chat_history(self, session_id: str) -> List[ChatMessage]:
        return self._session_store.get_chat_history(session_id)


    def format_history_for_llm(
        self, session_id: str, exclude_last: bool = False
    ) -> List[tuple]:
        return self._session_store.format_history_for_llm(session_id, exclude_last)
    
    def process_message(self, session_id: str, user_message: str) -> str:
        logger.info("[GENERAL] Session: %s | User: %.200s", session_id[:12], user_message)

        self.add_message(session_id, "user", user_message)
        chat_history = self.format_history_for_llm(session_id, exclude_last=True)

        logger.info("[GENERAL] History pairs sent to LLM: %d", len(chat_history))

        _, chat_idx = get_next_key_pair(GROQ_API_KEYS, need_brain=False)

        response = self.groq_service.get_response(
            question=user_message,
            chat_history=chat_history,
            key_start_index=chat_idx,
        )

        self.add_message(session_id, "assistant", response)

        logger.info(
            "[GENERAL] Response length: %d chars | Preview: %.120s",
            len(response),
            response,
        )

        return response


    def process_realtime_message(self, session_id: str, user_message: str) -> str:
        if not self.realtime_service:
            raise ValueError("Realtime service is not initialized. Cannot process realtime queries.")

        logger.info("[REALTIME] Session: %s | User: %.200s", session_id[:12], user_message)

        self.add_message(session_id, "user", user_message)
        chat_history = self.format_history_for_llm(session_id, exclude_last=True)

        logger.info("[REALTIME] History pairs sent to LLM: %d", len(chat_history))

        _, chat_idx = get_next_key_pair(GROQ_API_KEYS, need_brain=False)

        response = self.realtime_service.get_response(
            question=user_message,
            chat_history=chat_history,
            key_start_index=chat_idx,
        )

        self.add_message(session_id, "assistant", response)

        logger.info(
            "[REALTIME] Response length: %d chars | Preview: %.120s",
            len(response),
            response,
        )

        return response

    def process_message_stream(
        self, session_id: str, user_message: str
    ) -> Iterator[Union[str, Dict[str, Any]]]:
        logger.info("[GENERAL-STREAM] Session: %s | User: %.200s", session_id[:12], user_message)

        self.add_message(session_id, "user", user_message)
        self.add_message(session_id, "assistant", "")

        chat_history = self.format_history_for_llm(session_id, exclude_last=True)

        logger.info("[GENERAL-STREAM] History pairs sent to LLM: %d", len(chat_history))

        yield {"activity": {"event": "query_detected", "message": user_message}}
        yield {"activity": {"event": "routing", "route": "general"}}
        yield {"activity": {"event": "streaming_started", "route": "general"}}

        _, chat_idx = get_next_key_pair(len(GROQ_API_KEYS), need_brain=False)

        chunk_count = 0
        t0 = time.perf_counter()

        try:
            for chunk in self.groq_service.stream_response(
                question=user_message,
                chat_history=chat_history,
                key_start_index=chat_idx,
            ):
                if isinstance(chunk, dict):
                    yield chunk
                    continue

                if chunk_count == 0:
                    elapsed_ms = int((time.perf_counter() - t0) * 1000)
                    yield {
                        "activity": {
                            "event": "first_chunk",
                            "route": "general",
                            "elapsed_ms": elapsed_ms,
                        }
                    }

                self.sessions[session_id][-1].content += chunk
                chunk_count += 1

                if chunk_count % SAVE_EVERY_N_CHUNKS == 0:
                    self.save_chat_session(session_id, log_timing=False)

                yield chunk

        finally:
            final_response = self.sessions[session_id][-1].content
            logger.info(
                "[GENERAL-STREAM] Completed | Chunks: %d | Response length: %d chars",
                chunk_count,
                len(final_response),
            )
            self.save_chat_session(session_id)


    def process_realtime_message_stream(
        self, session_id: str, user_message: str
    ) -> Iterator[Union[str, Dict[str, Any]]]:

        if not self.realtime_service:
            raise ValueError("Realtime service is not initialized.")

        logger.info("[REALTIME-STREAM] Session: %s | User: %.200s", session_id[:12], user_message)

        self.add_message(session_id, "user", user_message)
        self.add_message(session_id, "assistant", "")

        chat_history = self.format_history_for_llm(session_id, exclude_last=True)

        logger.info("[REALTIME-STREAM] History pairs sent to LLM: %d", len(chat_history))

        yield {"activity": {"event": "query_detected", "message": user_message}}
        yield {"activity": {"event": "routing", "route": "realtime"}}
        yield {"activity": {"event": "streaming_started", "route": "realtime"}}

        _, chat_idx = get_next_key_pair(len(GROQ_API_KEYS), need_brain=False)

        chunk_count = 0
        t0 = time.perf_counter()

        try:
            for chunk in self.realtime_service.stream_response(
                question=user_message,
                chat_history=chat_history,
                key_start_index=chat_idx,
            ):
                if isinstance(chunk, dict):
                    yield chunk
                    continue

                if chunk_count == 0:
                    elapsed_ms = int((time.perf_counter() - t0) * 1000)
                    yield {
                        "activity": {
                            "event": "first_chunk",
                            "route": "realtime",
                            "elapsed_ms": elapsed_ms,
                        }
                    }

                self.sessions[session_id][-1].content += chunk
                chunk_count += 1

                if chunk_count % SAVE_EVERY_N_CHUNKS == 0:
                    self.save_chat_session(session_id, log_timing=False)

                yield chunk

        finally:
            final_response = self.sessions[session_id][-1].content
            logger.info(
                "[REALTIME-STREAM] Completed | Chunks: %d | Response length: %d chars",
                chunk_count,
                len(final_response),
            )
            self.save_chat_session(session_id)
    
    def process_jarvis_message_stream(
        self, session_id: str, user_message: str, imgbase64: Optional[str] = None
    ) -> Iterator[Union[str, Dict[str, Any]]]:
        if self.orchestrator is not None:
            _delegated_session_id, stream_iter = self.orchestrator.stream_assistant_llm(
                AssistantRequest(
                    message=user_message,
                    session_id=session_id,
                    imgbase64=imgbase64,
                )
            )
            yield from stream_iter
            return

        t0_jarvis = time.perf_counter()

        logger.info(
            "[JARVIS-STREAM] Session: %s | User: %.200s | img: %s",
            session_id[:12],
            user_message[:80],
            "yes" if imgbase64 else "no",
        )

        self.add_message(session_id, "user", user_message)
        self.add_message(session_id, "assistant", "")

        chat_history = self.format_history_for_llm(session_id, exclude_last=True)

        yield {"activity": {"event": "query_detected", "message": user_message}}

        if self.wake_on_lan_service and self.wake_on_lan_service.looks_like_wake_request(user_message):
            yield {"activity": {"event": "routing", "route": "wake_on_lan"}}
            yield {
                "activity": {
                    "event": "tasks_executing",
                    "message": "Sending Wake-on-LAN packet...",
                }
            }
            wol_result = self.wake_on_lan_service.wake_laptop()
            text = str(wol_result.get("message", "Wake-on-LAN request handled."))
            self.sessions[session_id][-1].content = text
            yield {
                "activity": {
                    "event": "tasks_completed",
                    "message": text,
                }
            }
            yield text
            self.save_chat_session(session_id)
            return

        instant_text = self._instant_local_answer(user_message)
        if instant_text:
            yield {"activity": {"event": "routing", "route": "local"}}
            yield {"activity": {"event": "streaming_started", "route": "local"}}
            self.sessions[session_id][-1].content = instant_text
            yield instant_text
            self.save_chat_session(session_id)
            logger.info("[JARVIS-STREAM] Local answer complete in %.2fs", time.perf_counter() - t0_jarvis)
            return

        if self.reminder_service and self.reminder_service.looks_like_reminder_request(user_message):
            yield {"activity": {"event": "routing", "route": "reminder"}}
            yield {
                "activity": {
                    "event": "tasks_executing",
                    "message": "Creating reminder...",
                }
            }
            reminder_result = self.reminder_service.create_reminder(user_message)
            text = str(reminder_result.get("message", "Reminder request handled."))
            self.sessions[session_id][-1].content = text
            yield {
                "activity": {
                    "event": "tasks_completed",
                    "message": text,
                }
            }
            yield text
            self.save_chat_session(session_id)
            logger.info("[JARVIS-STREAM] Reminder flow complete in %.2fs", time.perf_counter() - t0_jarvis)
            return

        if self.research_tools_service and self.research_tools_service.looks_like_research_request(user_message):
            yield {"activity": {"event": "routing", "route": "research"}}
            yield {
                "activity": {
                    "event": "tasks_executing",
                    "message": "Looking that up...",
                }
            }
            research_result = self.research_tools_service.handle_request(
                user_message,
                chat_history=chat_history,
            )
            text = str(research_result.get("message", "Research request handled."))
            self.sessions[session_id][-1].content = text
            yield {
                "activity": {
                    "event": "tasks_completed",
                    "message": text,
                }
            }
            yield text
            self.save_chat_session(session_id)
            logger.info("[JARVIS-STREAM] Research flow complete in %.2fs", time.perf_counter() - t0_jarvis)
            return

        if (
            self.automation_service
            and (
                self.automation_service.whatsapp_domain._looks_like_whatsapp_command(str(user_message or "").strip().lower())
                or (
                    re.search(r"\b(?:gmail|email|mail)\b", str(user_message or ""), flags=re.IGNORECASE)
                    and re.search(r"\b(?:send|draft|compose|write|reply|search|read|unread)\b", str(user_message or ""), flags=re.IGNORECASE)
                )
            )
        ):
            yield {"activity": {"event": "routing", "route": "automation"}}
            yield {"activity": {"event": "tasks_executing", "message": "Running communication action..."}}
            automation_result = self.automation_service.execute(user_message, session_id=session_id, source="user")
            text = str(automation_result.get("message", "Done."))
            self.sessions[session_id][-1].content = text
            yield {"activity": {"event": "tasks_completed", "message": text}}
            yield text
            self.save_chat_session(session_id)
            return

        if self.phone_command_service and (
            self.phone_command_service.looks_like_answer_request(user_message)
            or self.phone_command_service.looks_like_reject_request(user_message)
            or self.phone_command_service.looks_like_place_call_request(user_message)
            or self.phone_command_service.looks_like_message_request(user_message)
            or self.phone_command_service.looks_like_call_method_followup(user_message)
            or self.phone_command_service.looks_like_message_channel_followup(user_message)
        ):
            yield {"activity": {"event": "routing", "route": "phone"}}
            yield {
                "activity": {
                    "event": "tasks_executing",
                    "message": "Sending command to your phone...",
                }
            }
            phone_result = self.phone_command_service.route_phone_request(user_message)
            text = str((phone_result or {}).get("message") or "Phone command queued.")
            self.sessions[session_id][-1].content = text
            yield {
                "activity": {
                    "event": "tasks_completed",
                    "message": text,
                }
            }
            yield text
            self.save_chat_session(session_id)
            logger.info("[JARVIS-STREAM] Phone flow complete in %.2fs", time.perf_counter() - t0_jarvis)
            return

        if self.automation_service and (
            self.automation_service.has_pending_open_clarification()
            or self.automation_service.has_pending_browser_search()
            or self.automation_service.has_pending_create_file_location()
        ):
            yield {"activity": {"event": "routing", "route": "automation"}}
            yield {
                "activity": {
                    "event": "tasks_executing",
                    "message": (
                        "Resolving whether to open the app or the website..."
                        if self.automation_service.has_pending_open_clarification()
                        else "Running the next browser step..."
                    ),
                }
            }
            automation_result = self.automation_service.execute(user_message, session_id=session_id)
            text = str(automation_result.get("message", "Done."))
            self.sessions[session_id][-1].content = text
            yield {
                "activity": {
                    "event": "tasks_completed",
                    "message": text,
                }
            }
            yield text
            self.save_chat_session(session_id)
            return

        if (
            self.automation_service
            and self.automation_service.looks_like_automation_request(user_message)
            and not self._looks_like_mixed_action_and_chat(user_message)
        ):
            yield {"activity": {"event": "routing", "route": "automation"}}
            yield {
                "activity": {
                    "event": "tasks_executing",
                    "message": "Running desktop automation...",
                }
            }
            automation_result = self.automation_service.execute(user_message, session_id=session_id)
            text = str(automation_result.get("message", "Done."))
            self.sessions[session_id][-1].content = text
            yield {
                "activity": {
                    "event": "tasks_completed",
                    "message": text,
                }
            }
            yield text
            self.save_chat_session(session_id)
            elapsed_jarvis = time.perf_counter() - t0_jarvis
            logger.info(
                "[JARVIS-STREAM] Automation flow complete in %.2fs",
                elapsed_jarvis,
            )
            return

        if imgbase64 and CAMERA_BYPASS_TOKEN in (user_message or ""):
            yield {
                "activity": {
                    "event": "decision",
                    "query_type": "camera",
                    "reasoning": "Image attached",
                    "elapsed_ms": 0,
                }
            }
            yield {"activity": {"event": "routing", "route": "vision"}}
            yield {
                "activity": {
                    "event": "vision_analyzing",
                    "message": "Analyzing image...",
                }
            }
            yield {"activity": {"event": "streaming_started", "route": "vision"}}

            prompt = (
                (user_message or "").replace(CAMERA_BYPASS_TOKEN, "").strip()
                or "What do you see in this image?"
            )
            clean_msg = prompt or "What do you see in this image?"

            if self.sessions[session_id]:
                self.sessions[session_id][-2].content = clean_msg

            _save_camera_image(imgbase64, session_id)

            if self.vision_service:
                text = self.vision_service.describe_image(imgbase64, prompt)
            else:
                text = "Vision is not available. Please set GROQ_API_KEY."

            self.sessions[session_id][-1].content = text
            yield text

            self.save_chat_session(session_id)
            return
        
        brain_idx, chat_idx = get_next_key_pair(len(GROQ_API_KEYS), need_brain=bool(self.brain_service))

        category = CATEGORY_GENERAL
        primary_elapsed_ms = 0
        primary_method = "default"

        if self.brain_service:
            category, primary_method, primary_elapsed_ms = self.brain_service.classify_primary(
                user_message,
                chat_history,
                key_index=brain_idx if brain_idx is not None else 0,
            )

        yield {
            "activity": {
                "event": "decision",
                "query_type": category,
                "reasoning": primary_method.capitalize(),
                "elapsed_ms": primary_elapsed_ms,
            }
        }

        if category == CATEGORY_CAMERA:
            yield {"activity": {"event": "routing", "route": "camera"}}

            if imgbase64:
                yield {
                    "activity": {
                        "event": "vision_analyzing",
                        "message": "Analyzing image...",
                    }
                }
                yield {"activity": {"event": "streaming_started", "route": "vision"}}

                _save_camera_image(imgbase64, session_id)

                if self.vision_service:
                    text = self.vision_service.describe_image(imgbase64, user_message)
                else:
                    text = "Vision is not available. Please set GROQ_API_KEY."

            else:
                text = "Let me take a look..."
                yield {
                    "actions": {
                        "wopens": [],
                        "plays": [],
                        "images": [],
                        "contents": [],
                        "googlesearches": [],
                        "youtubesearches": [],
                        "cam": {
                            "action": "open_and_capture",
                            "resend_message": user_message,
                        },
                    }
                }
                yield {
                    "activity": {
                        "event": "actions_emitted",
                        "message": "camera (auto-capture)",
                    }
                }

            self.sessions[session_id][-1].content = text
            yield text

            self.save_chat_session(session_id)

            elapsed_jarvis = time.perf_counter() - t0_jarvis
            logger.info(
                "[JARVIS-STREAM] Camera flow complete in %.2fs", elapsed_jarvis
            )
            return
        
        if category in (CATEGORY_TASK, CATEGORY_MIXED):
            yield {
                "activity": {
                    "event": "routing",
                    "route": "task" if category == CATEGORY_TASK else "mixed",
                }
            }

            task_types = []
            task_elapsed_ms = 0
            task_method = "default"

            if self.brain_service:
                task_types, task_method, task_elapsed_ms = self.brain_service.classify_task(
                    user_message,
                    chat_history,
                    key_index=brain_idx if brain_idx is not None else 0,
                )

            task_name = ", ".join(task_types[:3]) if task_types else "task"

            yield {
                "activity": {
                    "event": "intent_classified",
                    "intent": task_name,
                }
            }

            intents = (
                self.brain_service.extract_task_payloads(user_message, task_types, chat_history)
                if self.brain_service
                else []
            )

            instant_intents = [(t, p) for t, p in intents if t not in HEAVY_INTENTS]
            heavy_intents = [(t, p) for t, p in intents if t in HEAVY_INTENTS]

            instant_response = TaskResponse()

            if self.task_executor and instant_intents:
                yield {
                    "activity": {
                        "event": "tasks_executing",
                        "message": "Running instant tasks...",
                    }
                }

                instant_response = self.task_executor.execute(instant_intents, chat_history)

                yield {
                    "activity": {
                        "event": "tasks_completed",
                        "message": "Instant tasks done",
                    }
                }

                has_instant_actions = (
                    instant_response.wopens
                    or instant_response.plays
                    or instant_response.googlesearches
                    or instant_response.youtubesearches
                    or instant_response.cam
                )

                if has_instant_actions:
                    actions = {
                        "wopens": instant_response.wopens,
                        "plays": instant_response.plays,
                        "images": [],
                        "contents": [],
                        "googlesearches": instant_response.googlesearches,
                        "youtubesearches": instant_response.youtubesearches,
                        "cam": instant_response.cam,
                    }

                    action_summary = []
                    if instant_response.wopens:
                        action_summary.append("open")
                    if instant_response.plays:
                        action_summary.append("play")
                    if instant_response.googlesearches or instant_response.youtubesearches:
                        action_summary.append("search")
                    if instant_response.cam:
                        action_summary.append("camera")

                    yield {
                        "activity": {
                            "event": "actions_emitted",
                            "message": ", ".join(action_summary) or "actions",
                        }
                    }

                    yield {"actions": actions}

            bg_task_ids = []
            if self.task_manager and heavy_intents:
                yield {
                    "activity": {
                        "event": "tasks_executing",
                        "message": "Dispatching background tasks...",
                    }
                }

                for intent_type, payload in heavy_intents:
                    task_id = self.task_manager.submit(intent_type, payload, chat_history)
                    bg_task_ids.append(
                        {
                            "task_id": task_id,
                            "type": intent_type,
                            "label": (
                                payload.get("prompt")
                                or payload.get("message", "")[:100]
                            ),
                        }
                    )

                yield {
                    "activity": {
                        "event": "background_dispatched",
                        "message": f"{len(bg_task_ids)} task(s) in background",
                    }
                }

            elif not self.task_manager and heavy_intents:
                yield {
                    "activity": {
                        "event": "tasks_executing",
                        "message": f"Running {task_name}...",
                    }
                }

                sync_response = (
                    self.task_executor.execute(heavy_intents, chat_history)
                    if self.task_executor
                    else TaskResponse()
                )

                yield {
                    "activity": {
                        "event": "tasks_completed",
                        "message": "Tasks completed",
                    }
                }

                if sync_response.images or sync_response.contents:
                    actions = {
                        "wopens": [],
                        "plays": [],
                        "images": sync_response.images,
                        "contents": sync_response.contents,
                        "googlesearches": [],
                        "youtubesearches": [],
                        "cam": None,
                    }
                    yield {"actions": actions}

                instant_response.text = instant_response.text or sync_response.text

            if category == CATEGORY_MIXED:
                yield {"activity": {"event": "streaming_started", "route": "mixed"}}

                stream_svc = self.realtime_service if self.realtime_service else self.groq_service
                chunk_count = 0
                t0 = time.perf_counter()

                try:
                    for chunk in stream_svc.stream_response(
                        question=user_message,
                        chat_history=chat_history,
                        key_start_index=chat_idx,
                    ):
                        if isinstance(chunk, dict):
                            yield chunk
                            continue

                        if chunk_count == 0:
                            elapsed_ms = int((time.perf_counter() - t0) * 1000)
                            yield {
                                "activity": {
                                    "event": "first_chunk",
                                    "route": "mixed",
                                    "elapsed_ms": elapsed_ms,
                                }
                            }

                        self.sessions[session_id][-1].content += chunk
                        chunk_count += 1

                        if chunk_count % SAVE_EVERY_N_CHUNKS == 0:
                            self.save_chat_session(session_id, log_timing=False)

                        yield chunk

                finally:
                    self.save_chat_session(session_id)

                if bg_task_ids:
                    yield {"background_tasks": bg_task_ids}

                elapsed_jarvis = time.perf_counter() - t0_jarvis
                logger.info(
                    "[JARVIS-STREAM] Mixed flow complete in %.2fs | tasks: %s",
                    elapsed_jarvis,
                    task_types,
                )
                return
            
            text_parts = []
            if instant_response.text:
                text_parts.append(instant_response.text)

            if bg_task_ids:
                bg_labels = []

                for bt in bg_task_ids:
                    if bt["type"] == "generate_image":
                        bg_labels.append("image generation")
                    elif bt["type"] == "content":
                        bg_labels.append("content writing")
                    else:
                        bg_labels.append(bt["type"])

                text_parts.append(
                    f"I'm working on the {', '.join(bg_labels)} in the background. I'll open it for you when it's ready."
                )

            if not text_parts and not bg_task_ids and not intents:
                text = "Could you clarify what you'd like me to do?"
            else:
                text = " ".join(text_parts) if text_parts else "Done."

            self.sessions[session_id][-1].content = text
            yield text

            if bg_task_ids:
                yield {"background_tasks": bg_task_ids}

            self.save_chat_session(session_id)

            elapsed_jarvis = time.perf_counter() - t0_jarvis
            logger.info(
                "[JARVIS-STREAM] Task flow complete in %.2fs | tasks: %s | bg: %d",
                elapsed_jarvis,
                task_types,
                len(bg_task_ids),
            )

            return
        
        use_realtime = category == CATEGORY_REALTIME and self.realtime_service
        route_name = "realtime" if use_realtime else "general"

        yield {"activity": {"event": "routing", "route": route_name}}
        yield {"activity": {"event": "streaming_started", "route": route_name}}

        stream_svc = self.realtime_service if use_realtime else self.groq_service

        chunk_count = 0
        t0 = time.perf_counter()

        try:
            for chunk in stream_svc.stream_response(
                question=user_message,
                chat_history=chat_history,
                key_start_index=chat_idx,
            ):
                if isinstance(chunk, dict):
                    yield chunk
                    continue

                if chunk_count == 0:
                    elapsed_ms = int((time.perf_counter() - t0) * 1000)
                    yield {
                        "activity": {
                            "event": "first_chunk",
                            "route": route_name,
                            "elapsed_ms": elapsed_ms,
                        }
                    }

                self.sessions[session_id][-1].content += chunk
                chunk_count += 1

                if chunk_count % SAVE_EVERY_N_CHUNKS == 0:
                    self.save_chat_session(session_id, log_timing=False)

                yield chunk

        finally:
            self.save_chat_session(session_id)

        elapsed_jarvis = time.perf_counter() - t0_jarvis
        logger.info(
            "[JARVIS-STREAM] %s flow complete in %.2fs | chunks: %d",
            route_name,
            elapsed_jarvis,
            chunk_count,
        )
    def save_chat_session(self, session_id: str, log_timing: bool = True):
        self._session_store.save_chat_session(session_id, log_timing=log_timing)
