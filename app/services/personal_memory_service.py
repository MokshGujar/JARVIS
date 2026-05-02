from __future__ import annotations

import json
import logging
import re
import time
import uuid
from typing import Any, Dict, List, Optional

from config import MEMORY_DATA_DIR

logger = logging.getLogger("J.A.R.V.I.S")


class PersonalMemoryService:
    def __init__(self) -> None:
        self._memory_path = MEMORY_DATA_DIR / "personal_memory.json"
        self._session_path = MEMORY_DATA_DIR / "session_notes.json"

    def list_memories(self) -> List[Dict[str, Any]]:
        memories = self._load_memories()
        memories.sort(key=lambda item: float(item.get("updated_at", 0)), reverse=True)
        return memories

    def remember(self, text: str, kind: str = "note", source: str = "manual", tags: Optional[List[str]] = None) -> Dict[str, Any]:
        cleaned = re.sub(r"\s+", " ", (text or "").strip())
        if not cleaned:
            raise ValueError("Memory text cannot be empty.")

        now = time.time()
        memory = {
            "memory_id": str(uuid.uuid4()),
            "kind": (kind or "note").strip().lower(),
            "text": cleaned,
            "source": (source or "manual").strip().lower(),
            "created_at": now,
            "updated_at": now,
            "tags": [str(tag).strip().lower() for tag in (tags or []) if str(tag).strip()],
        }
        memories = self._load_memories()
        memories.append(memory)
        self._save_memories(memories)
        logger.info("[MEMORY] Stored %s memory: %.80s", memory["kind"], memory["text"])
        return memory

    def remember_from_message(self, message: str) -> Optional[Dict[str, Any]]:
        text = re.sub(r"\s+", " ", (message or "").strip())
        if not text:
            return None

        lowered = text.lower()
        patterns = [
            (r"^(?:please\s+)?remember that\s+(.+)$", "note", ["remembered"]),
            (r"^(?:please\s+)?remember\s+(.+)$", "note", ["remembered"]),
            (r"^my favorite ([a-z ]{2,40}) is (.+)$", "preference", ["favorite"]),
            (r"^i prefer (.+)$", "preference", ["preference"]),
            (r"^call me (.+)$", "identity", ["name"]),
            (r"^my name is (.+)$", "identity", ["name"]),
        ]
        for pattern, kind, tags in patterns:
            match = re.match(pattern, lowered, flags=re.IGNORECASE)
            if not match:
                continue
            if pattern.startswith("^my favorite"):
                subject = match.group(1).strip()
                value = text.split(" is ", 1)[1].strip().rstrip(".!?")
                stored = self.remember(f"Favorite {subject}: {value}", kind=kind, source="chat", tags=tags + [subject.lower()])
            else:
                value = match.group(1).strip().rstrip(".!?")
                stored = self.remember(value, kind=kind, source="chat", tags=tags)
            return {
                "success": True,
                "action": "memory_write",
                "message": f"I'll remember that: {stored['text']}",
                "memory": stored,
            }
        return None

    def answer_memory_query(self, message: str) -> Optional[str]:
        text = re.sub(r"\s+", " ", (message or "").strip().lower())
        if not text:
            return None
        if not any(phrase in text for phrase in ("remember about me", "my preferences", "what do you know about me", "what do you remember")):
            return None

        memories = self.list_memories()[:8]
        if not memories:
            return "I do not have any saved personal notes yet."

        summary = "; ".join(item["text"] for item in memories[:5])
        return f"Here’s what I remember so far: {summary}"

    def search_relevant(self, query: str, limit: int = 4) -> List[Dict[str, Any]]:
        terms = self._tokenize(query)
        if not terms:
            return []

        scored: List[tuple[int, Dict[str, Any]]] = []
        for memory in self._load_memories():
            haystack = " ".join(
                [
                    str(memory.get("text", "")),
                    " ".join(memory.get("tags", [])),
                    str(memory.get("kind", "")),
                ]
            ).lower()
            score = sum(1 for term in terms if term in haystack)
            if score > 0:
                scored.append((score, memory))

        scored.sort(key=lambda item: (item[0], float(item[1].get("updated_at", 0))), reverse=True)
        return [memory for _, memory in scored[:limit]]

    def build_prompt_parts(self, query: str) -> List[str]:
        relevant = self.search_relevant(query)
        if not relevant:
            return []
        lines = ["Relevant personal memory:"]
        for item in relevant:
            lines.append(f"- {item['text']}")
        return ["\n".join(lines)]

    def update_session_note(self, session_id: str, route: str, user_message: str, final_response: str) -> None:
        notes = self._load_session_notes()
        notes[session_id] = {
            "session_id": session_id,
            "route": route,
            "updated_at": time.time(),
            "last_user_message": (user_message or "")[:500],
            "last_response_preview": re.sub(r"\s+", " ", (final_response or "").strip())[:500],
        }
        self._save_session_notes(notes)

    def _load_memories(self) -> List[Dict[str, Any]]:
        if not self._memory_path.exists():
            return []
        try:
            return json.loads(self._memory_path.read_text(encoding="utf-8"))
        except Exception:
            return []

    def _save_memories(self, memories: List[Dict[str, Any]]) -> None:
        self._memory_path.write_text(json.dumps(memories, indent=2, ensure_ascii=False), encoding="utf-8")

    def _load_session_notes(self) -> Dict[str, Any]:
        if not self._session_path.exists():
            return {}
        try:
            return json.loads(self._session_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_session_notes(self, notes: Dict[str, Any]) -> None:
        self._session_path.write_text(json.dumps(notes, indent=2, ensure_ascii=False), encoding="utf-8")

    def _tokenize(self, text: str) -> List[str]:
        words = re.findall(r"[a-z0-9]{3,}", (text or "").lower())
        return list(dict.fromkeys(words))
