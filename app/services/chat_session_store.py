import json
import logging
import threading
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional

from app.models import ChatMessage
from app.utils.atomic_io import write_json_atomic

logger = logging.getLogger("J.A.R.V.I.S")


class ChatSessionStore:
    def __init__(self, data_dir: Path, max_history_turns: int):
        self.data_dir = data_dir
        self.max_history_turns = max_history_turns
        self.sessions: Dict[str, List[ChatMessage]] = {}
        self._save_lock = threading.Lock()

    def validate_session_id(self, session_id: str) -> bool:
        if not session_id or not session_id.strip():
            return False

        if "@" in session_id:
            return False

        if ".." in session_id or "/" in session_id or "\\" in session_id:
            return False

        return len(session_id) <= 255

    def load_session_from_disk(self, session_id: str) -> bool:
        filepath = self._path_for_session(session_id)

        if not filepath.exists():
            return False

        try:
            chat_dict = json.loads(filepath.read_text(encoding="utf-8"))
            messages = []

            for msg in chat_dict.get("messages", []):
                if not isinstance(msg, dict):
                    continue

                role = msg.get("role")
                role = role if role in ("user", "assistant") else "user"

                content = msg.get("content")
                content = content if isinstance(content, str) else str(content or "")

                messages.append(ChatMessage(role=role, content=content))

            self.sessions[session_id] = messages
            return True

        except Exception as e:
            logger.warning("Failed to load session %s from disk: %s", session_id, e)
            return False

    def get_or_create_session(self, session_id: Optional[str] = None) -> str:
        t0 = time.perf_counter()

        if not session_id:
            new_session_id = str(uuid.uuid4())
            self.sessions[new_session_id] = []
            logger.info(
                "[TIMING] session_get_or_create: %.3fs (new)",
                time.perf_counter() - t0,
            )
            return new_session_id

        if not self.validate_session_id(session_id):
            raise ValueError(
                f"Invalid session_id format: '{session_id}'. Session ID must be non-empty, "
                "not contain path traversal characters, and be under 255 characters."
            )

        if session_id in self.sessions:
            logger.info(
                "[TIMING] session_get_or_create: %.3fs (memory)",
                time.perf_counter() - t0,
            )
            return session_id

        if self.load_session_from_disk(session_id):
            logger.info(
                "[TIMING] session_get_or_create: %.3fs (disk)",
                time.perf_counter() - t0,
            )
            return session_id

        self.sessions[session_id] = []
        logger.info(
            "[TIMING] session_get_or_create: %.3fs (new_id)",
            time.perf_counter() - t0,
        )
        return session_id

    def add_message(self, session_id: str, role: str, content: str) -> None:
        if session_id not in self.sessions:
            self.sessions[session_id] = []

        self.sessions[session_id].append(ChatMessage(role=role, content=content))

    def get_chat_history(self, session_id: str) -> List[ChatMessage]:
        return self.sessions.get(session_id, [])

    def format_history_for_llm(
        self, session_id: str, exclude_last: bool = False
    ) -> List[tuple]:
        messages = self.get_chat_history(session_id)
        messages_to_process = messages[:-1] if exclude_last and messages else messages
        history = []

        i = 0
        while i < len(messages_to_process) - 1:
            user_msg = messages_to_process[i]
            ai_msg = messages_to_process[i + 1]

            if user_msg.role == "user" and ai_msg.role == "assistant":
                u_content = (
                    user_msg.content
                    if isinstance(user_msg.content, str)
                    else str(user_msg.content or "")
                )
                a_content = (
                    ai_msg.content
                    if isinstance(ai_msg.content, str)
                    else str(ai_msg.content or "")
                )
                history.append((u_content, a_content))
                i += 2
            else:
                i += 1

        if len(history) > self.max_history_turns:
            history = history[-self.max_history_turns :]

        return history

    def save_chat_session(self, session_id: str, log_timing: bool = True) -> None:
        if session_id not in self.sessions or not self.sessions[session_id]:
            return

        chat_dict = {
            "session_id": session_id,
            "messages": [
                {"role": msg.role, "content": msg.content}
                for msg in self.sessions[session_id]
            ],
        }

        max_retries = 3
        last_exc = None

        for attempt in range(max_retries):
            try:
                with self._save_lock:
                    t0 = time.perf_counter() if log_timing else 0
                    write_json_atomic(
                        self._path_for_session(session_id),
                        chat_dict,
                        indent=2,
                        ensure_ascii=False,
                    )

                    if log_timing:
                        logger.info(
                            "[TIMING] save_session_json: %.3fs",
                            time.perf_counter() - t0,
                        )

                    return

            except OSError as e:
                last_exc = e
                if attempt < max_retries - 1:
                    time.sleep(0.1 * (attempt + 1))

            except Exception as e:
                logger.error(
                    "Failed to save chat session %s to disk: %s",
                    session_id,
                    e,
                )
                return

        logger.error(
            "Failed to save chat session %s after %d retries: %s",
            session_id,
            max_retries,
            last_exc,
        )

    def _path_for_session(self, session_id: str) -> Path:
        safe_session_id = session_id.replace(":", "_").replace("/", "_")
        return self.data_dir / f"chat_{safe_session_id}.json"
