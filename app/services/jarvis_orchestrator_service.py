from __future__ import annotations

import json
import logging
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Union

from app.services.automation_service import AutomationService
from app.services.brain_service import BrainService
from app.services.caller_lookup_service import CallerLookupService
from app.services.chat_service import ChatService
from app.services.groq_service import GroqService
from app.services.personal_memory_service import PersonalMemoryService
from app.services.phone_command_service import PhoneCommandService
from app.services.realtime_service import RealtimeGroqService
from app.services.reminder_service import ReminderService
from app.services.wake_on_lan_service import WakeOnLanService
from app.utils.key_rotation import get_next_key_pair
from config import AGENT_TASKS_DIR, GROQ_API_KEYS

logger = logging.getLogger("J.A.R.V.I.S")


@dataclass
class OrchestratorTool:
    name: str
    description: str
    category: str
    safety_level: str


@dataclass
class OrchestratorStep:
    step_id: str
    tool_name: str
    description: str
    safety_level: str
    input: Dict[str, Any] = field(default_factory=dict)
    status: str = "pending"
    output_summary: str = ""


@dataclass
class OrchestratorTask:
    task_id: str
    session_id: str
    user_message: str
    route: str
    status: str
    created_at: float
    updated_at: float
    final_response: str = ""
    steps: List[OrchestratorStep] = field(default_factory=list)


class OrchestratorTaskStore:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir

    def _path_for(self, task_id: str) -> Path:
        return self.base_dir / f"task_{task_id}.json"

    def save(self, task: OrchestratorTask) -> None:
        payload = {
            "task_id": task.task_id,
            "session_id": task.session_id,
            "user_message": task.user_message,
            "route": task.route,
            "status": task.status,
            "created_at": task.created_at,
            "updated_at": task.updated_at,
            "final_response": task.final_response,
            "steps": [asdict(step) for step in task.steps],
        }
        self._path_for(task.task_id).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def load(self, task_id: str) -> Optional[OrchestratorTask]:
        path = self._path_for(task_id)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return OrchestratorTask(
            task_id=data["task_id"],
            session_id=data["session_id"],
            user_message=data["user_message"],
            route=data.get("route", "unknown"),
            status=data.get("status", "unknown"),
            created_at=float(data.get("created_at", time.time())),
            updated_at=float(data.get("updated_at", time.time())),
            final_response=data.get("final_response", ""),
            steps=[OrchestratorStep(**item) for item in data.get("steps", [])],
        )

    def list_tasks(self, limit: int = 50) -> List[OrchestratorTask]:
        tasks: List[OrchestratorTask] = []
        for path in sorted(self.base_dir.glob("task_*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
            task = self.load(path.stem.replace("task_", "", 1))
            if task:
                tasks.append(task)
            if len(tasks) >= limit:
                break
        return tasks


class JarvisOrchestratorService:
    def __init__(
        self,
        *,
        chat_service: ChatService,
        groq_service: GroqService,
        realtime_service: Optional[RealtimeGroqService] = None,
        brain_service: Optional[BrainService] = None,
        caller_lookup_service: Optional[CallerLookupService] = None,
        automation_service: Optional[AutomationService] = None,
        reminder_service: Optional[ReminderService] = None,
        phone_command_service: Optional[PhoneCommandService] = None,
        wake_on_lan_service: Optional[WakeOnLanService] = None,
        personal_memory_service: Optional[PersonalMemoryService] = None,
    ) -> None:
        self.chat_service = chat_service
        self.groq_service = groq_service
        self.realtime_service = realtime_service
        self.brain_service = brain_service
        self.caller_lookup_service = caller_lookup_service
        self.automation_service = automation_service
        self.reminder_service = reminder_service
        self.phone_command_service = phone_command_service
        self.wake_on_lan_service = wake_on_lan_service
        self.personal_memory_service = personal_memory_service
        self.task_store = OrchestratorTaskStore(AGENT_TASKS_DIR)
        self.tools = self._build_tools()

    def list_tools(self) -> List[Dict[str, Any]]:
        return [asdict(tool) for tool in self.tools.values()]

    def list_tasks(self) -> List[OrchestratorTask]:
        return self.task_store.list_tasks()

    def get_task(self, task_id: str) -> Optional[OrchestratorTask]:
        return self.task_store.load(task_id)

    def process_message(self, session_id: str, user_message: str) -> OrchestratorTask:
        final_task = None
        for item in self.process_message_stream(session_id, user_message):
            if isinstance(item, dict) and item.get("_agent_task"):
                final_task = item["_agent_task"]
        if final_task is None:
            raise RuntimeError("Task did not finish.")
        return final_task

    def resume_task(self, task_id: str) -> OrchestratorTask:
        task = self.get_task(task_id)
        if not task:
            raise ValueError("Task not found.")
        final_task = None
        for item in self._run_task(task):
            if isinstance(item, dict) and item.get("_agent_task"):
                final_task = item["_agent_task"]
        if final_task is None:
            raise RuntimeError("Task did not finish.")
        return final_task

    def process_message_stream(
        self,
        session_id: str,
        user_message: str,
    ) -> Iterator[Union[str, Dict[str, Any]]]:
        self.chat_service.add_message(session_id, "user", user_message)
        self.chat_service.add_message(session_id, "assistant", "")
        task = OrchestratorTask(
            task_id=str(uuid.uuid4()),
            session_id=session_id,
            user_message=user_message,
            route="planning",
            status="in_progress",
            created_at=time.time(),
            updated_at=time.time(),
        )
        task.steps, task.route = self._build_plan(session_id, user_message)
        self.task_store.save(task)
        yield {"_activity": {"event": "task_created", "task_id": task.task_id, "route": task.route}}
        yield {"_activity": {"event": "plan_created", "route": task.route, "steps": [asdict(step) for step in task.steps]}}
        yield from self._run_task(task)

    def _run_task(self, task: OrchestratorTask) -> Iterator[Union[str, Dict[str, Any]]]:
        try:
            for step in task.steps:
                if step.status == "completed":
                    continue

                step.status = "in_progress"
                self.task_store.save(task)
                yield {"_activity": {"event": "step_started", "task_id": task.task_id, "step_id": step.step_id, "tool_name": step.tool_name}}

                for item in self._execute_step(task, step):
                    if isinstance(item, str):
                        self.chat_service.sessions[task.session_id][-1].content += item
                    yield item

                step.status = "completed"
                task.updated_at = time.time()
                self.task_store.save(task)
                yield {"_activity": {"event": "step_completed", "task_id": task.task_id, "step_id": step.step_id, "summary": step.output_summary}}

            task.status = "completed"
            task.updated_at = time.time()
            task.final_response = self.chat_service.sessions[task.session_id][-1].content
            self.task_store.save(task)
            self.chat_service.save_chat_session(task.session_id)
            if self.personal_memory_service:
                self.personal_memory_service.update_session_note(task.session_id, task.route, task.user_message, task.final_response)
            yield {"_agent_task": task, "_activity": {"event": "task_completed", "task_id": task.task_id, "route": task.route}}
        except Exception:
            task.status = "failed"
            task.updated_at = time.time()
            task.final_response = self.chat_service.sessions[task.session_id][-1].content
            self.task_store.save(task)
            self.chat_service.save_chat_session(task.session_id)
            raise

    def _build_tools(self) -> Dict[str, OrchestratorTool]:
        return {
            "general_chat": OrchestratorTool("general_chat", "Answer from knowledge and memory.", "chat", "safe"),
            "realtime_chat": OrchestratorTool("realtime_chat", "Answer with live search and current context.", "chat", "safe"),
            "automation": OrchestratorTool("automation", "Run local automation actions.", "automation", "safe"),
            "reminder": OrchestratorTool("reminder", "Create reminders.", "productivity", "safe"),
            "caller_lookup": OrchestratorTool("caller_lookup", "Look up caller identity.", "phone", "safe"),
            "phone_control": OrchestratorTool("phone_control", "Queue phone companion commands.", "phone", "safe"),
            "wake_laptop": OrchestratorTool("wake_laptop", "Send wake-on-LAN packet.", "device", "safe"),
            "memory_write": OrchestratorTool("memory_write", "Save a personal memory or preference.", "memory", "safe"),
            "memory_query": OrchestratorTool("memory_query", "Recall saved memories and preferences.", "memory", "safe"),
            "recent_target": OrchestratorTool("recent_target", "Recall the most recent file or folder touched by Jarvis.", "automation", "safe"),
            "write_and_save": OrchestratorTool("write_and_save", "Generate content and save it to a file.", "automation", "safe"),
        }

    def _build_plan(self, session_id: str, user_message: str) -> tuple[List[OrchestratorStep], str]:
        if self.personal_memory_service:
            memory_write = self.personal_memory_service.remember_from_message(user_message)
            if memory_write:
                return ([self._step("memory_write", "Store a personal memory.", memory_write, "safe")], "memory")
            memory_answer = self.personal_memory_service.answer_memory_query(user_message)
            if memory_answer:
                return ([self._step("memory_query", "Recall saved memory.", {"response": memory_answer}, "safe")], "memory")

        if self.automation_service and self.automation_service.has_pending_delete_confirmation():
            if self.automation_service.looks_like_confirmation_response(user_message):
                return ([self._step("automation", "Confirm or cancel the pending delete action.", {"command": user_message}, "safe")], "automation")

        recent_target_response = self.chat_service._handle_recent_target_query(user_message)
        if recent_target_response is not None:
            return ([self._step("recent_target", "Recall the most recent target.", {"response": recent_target_response}, "safe")], "recent_target")

        write_and_save = self.chat_service._extract_write_and_save_request(user_message)
        if write_and_save and self.automation_service:
            return ([self._step("write_and_save", f"Write content and save it as {write_and_save['filename']}.", write_and_save, "safe")], "write_and_save")

        mixed_intent = self.chat_service._split_action_and_followup(user_message)
        if mixed_intent and self.automation_service:
            action_text, followup_text = mixed_intent
            route, reasoning, elapsed = self._classify_message(session_id, followup_text)
            return (
                [
                    self._step("automation", f"Run automation action: {action_text}", {"command": action_text}, "safe"),
                    self._step(route, f"Answer the follow-up after automation ({reasoning}).", {"message": followup_text, "reasoning": reasoning, "elapsed_ms": elapsed}, self.tools[route].safety_level),
                ],
                f"automation_then_{route}",
            )

        if self.automation_service and self.automation_service.looks_like_automation_request(user_message):
            return ([self._step("automation", f"Run automation action: {user_message}", {"command": user_message}, "safe")], "automation")

        if self.phone_command_service and (
            self.phone_command_service.looks_like_answer_request(user_message)
            or self.phone_command_service.looks_like_reject_request(user_message)
            or self.phone_command_service.looks_like_place_call_request(user_message)
            or self.phone_command_service.looks_like_message_request(user_message)
            or self.phone_command_service.looks_like_call_method_followup(user_message)
            or self.phone_command_service.looks_like_message_channel_followup(user_message)
        ):
            return ([self._step("phone_control", "Queue the requested phone command.", {"message": user_message}, "safe")], "phone_control")

        if self.wake_on_lan_service and self.wake_on_lan_service.looks_like_wake_request(user_message):
            return ([self._step("wake_laptop", "Send a Wake-on-LAN packet to the laptop.", {}, "safe")], "wake_laptop")

        if self.reminder_service and self.reminder_service.looks_like_reminder_request(user_message):
            return ([self._step("reminder", "Create a reminder for the user.", {"command": user_message}, "safe")], "reminder")

        if self.caller_lookup_service and self.caller_lookup_service.looks_like_lookup_request(user_message):
            number = self.caller_lookup_service.extract_phone_number(user_message) or ""
            return ([self._step("caller_lookup", f"Look up public information for {number}.", {"phone_number": number, "question": user_message}, "safe")], "caller_lookup")

        route, reasoning, elapsed = self._classify_message(session_id, user_message)
        return ([self._step(route, f"Answer with the {route} tool.", {"message": user_message, "reasoning": reasoning, "elapsed_ms": elapsed}, self.tools[route].safety_level)], route)

    def _classify_message(self, session_id: str, user_message: str) -> tuple[str, str, int]:
        history = self.chat_service.format_history_for_llm(session_id, exclude_last=True)
        if not self.brain_service:
            return ("realtime_chat", "Brain unavailable; defaulting to realtime.", 0)
        fast_route = self.brain_service.classify_fast(user_message)
        if fast_route:
            query_type, reasoning = fast_route
            return ("general_chat" if query_type == "general" else "realtime_chat", reasoning, 0)
        brain_idx, _ = get_next_key_pair(len(GROQ_API_KEYS), need_brain=True)
        query_type, reasoning, elapsed_ms = self.brain_service.classify(user_message, history, key_index=brain_idx)
        return ("general_chat" if query_type == "general" else "realtime_chat", reasoning, elapsed_ms)

    def _execute_step(self, task: OrchestratorTask, step: OrchestratorStep) -> Iterator[Union[str, Dict[str, Any]]]:
        if step.tool_name == "memory_write":
            response = str(step.input.get("message", "I'll remember that."))
            step.output_summary = self._shorten(response)
            yield response
            return
        if step.tool_name == "memory_query":
            response = str(step.input.get("response", "I do not have any saved memory yet."))
            step.output_summary = self._shorten(response)
            yield response
            return
        if step.tool_name == "recent_target":
            response = str(step.input.get("response", "I do not have a recent target yet."))
            step.output_summary = self._shorten(response)
            yield response
            return
        if step.tool_name == "write_and_save":
            prompt = str(step.input.get("prompt", "")).strip()
            filename = str(step.input.get("filename", "")).strip()
            content = self.groq_service.get_response(
                question=prompt,
                chat_history=self.chat_service.format_history_for_llm(task.session_id, exclude_last=True),
                key_start_index=get_next_key_pair(len(GROQ_API_KEYS), need_brain=False)[1],
                extra_system_parts=self._build_memory_parts(task.user_message),
            )
            result = self.automation_service.create_file_with_content(filename, content)
            response = self.chat_service._build_write_and_save_response(str(result["message"]), content)
            step.output_summary = self._shorten(str(result["message"]))
            yield response
            return
        if step.tool_name == "automation":
            result = self.automation_service.execute(str(step.input.get("command", "")))
            response = str(result["message"])
            step.output_summary = self._shorten(response)
            yield response
            return
        if step.tool_name == "reminder":
            result = self.reminder_service.create_reminder(str(step.input.get("command", "")))
            response = str(result["message"])
            step.output_summary = self._shorten(response)
            yield response
            return
        if step.tool_name == "caller_lookup":
            result = self.caller_lookup_service.lookup_caller(
                phone_number=str(step.input.get("phone_number", "")),
                original_question=str(step.input.get("question", "")),
            )
            response = str(result["summary"])
            step.output_summary = self._shorten(response)
            yield {"_search_results": {"query": result["normalized_number"], "answer": result["summary"], "results": result["results"]}}
            yield response
            return
        if step.tool_name == "phone_control":
            result = step.input.get("result")
            if not isinstance(result, dict):
                result = self.phone_command_service.route_phone_request(str(step.input.get("message", ""))) or {}
            response = str(result.get("message", "Phone command queued."))
            step.output_summary = self._shorten(response)
            yield response
            return
        if step.tool_name == "wake_laptop":
            result = self.wake_on_lan_service.wake_laptop()
            response = str(result["message"])
            step.output_summary = self._shorten(response)
            yield response
            return
        if step.tool_name == "general_chat":
            yield from self._stream_general_chat(task, step)
            return
        if step.tool_name == "realtime_chat":
            yield from self._stream_realtime_chat(task, step)
            return
        raise RuntimeError(f"Unknown orchestrator tool: {step.tool_name}")

    def _stream_general_chat(self, task: OrchestratorTask, step: OrchestratorStep) -> Iterator[Union[str, Dict[str, Any]]]:
        history = self.chat_service.format_history_for_llm(task.session_id, exclude_last=True)
        _, chat_idx = get_next_key_pair(len(GROQ_API_KEYS), need_brain=False)
        step.output_summary = self._shorten("Answered from knowledge and memory.")
        yield {"_activity": {"event": "routing", "route": "general"}}
        for chunk in self.groq_service.stream_response(
            question=str(step.input.get("message", task.user_message)),
            chat_history=history,
            key_start_index=chat_idx,
            extra_system_parts=self._build_memory_parts(task.user_message),
        ):
            yield chunk

    def _stream_realtime_chat(self, task: OrchestratorTask, step: OrchestratorStep) -> Iterator[Union[str, Dict[str, Any]]]:
        history = self.chat_service.format_history_for_llm(task.session_id, exclude_last=True)
        _, chat_idx = get_next_key_pair(len(GROQ_API_KEYS), need_brain=False)
        step.output_summary = self._shorten("Answered with live web search.")
        yield {"_activity": {"event": "routing", "route": "realtime"}}
        formatted_results, payload = self.realtime_service.prefetch_web_search(str(step.input.get("message", task.user_message)), history)
        if payload:
            yield {"_activity": payload}
        for chunk in self.realtime_service.stream_response_with_prefetched(
            question=str(step.input.get("message", task.user_message)),
            chat_history=history,
            formatted_results=formatted_results,
            payload=payload,
            key_start_index=chat_idx,
            extra_system_parts=self._build_memory_parts(task.user_message),
        ):
            yield chunk

    def _build_memory_parts(self, message: str) -> List[str]:
        if not self.personal_memory_service:
            return []
        return self.personal_memory_service.build_prompt_parts(message)

    def _step(self, tool_name: str, description: str, payload: Dict[str, Any], safety_level: str) -> OrchestratorStep:
        return OrchestratorStep(
            step_id=str(uuid.uuid4())[:8],
            tool_name=tool_name,
            description=description,
            safety_level=safety_level,
            input=payload,
        )

    def _shorten(self, text: str, limit: int = 140) -> str:
        cleaned = re.sub(r"\s+", " ", (text or "").strip())
        return cleaned if len(cleaned) <= limit else cleaned[: limit - 3].rstrip() + "..."
