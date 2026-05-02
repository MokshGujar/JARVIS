from __future__ import annotations

import json
import logging
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Union

from app.services.caller_lookup_service import CallerLookupService
from app.services.chat_service import ChatService
from app.services.groq_service import AllGroqApisFailedError, GroqService
from app.services.phone_command_service import PhoneCommandService
from app.services.realtime_service import RealtimeGroqService
from app.services.reminder_service import ReminderService
from app.services.automation_service import AutomationService
from app.services.brain_service import BrainService
from app.services.wake_on_lan_service import WakeOnLanService
from config import AGENT_TASKS_DIR, GROQ_API_KEYS
from app.utils.key_rotation import get_next_key_pair

logger = logging.getLogger("J.A.R.V.I.S")


@dataclass
class AgentPlanStep:
    step_id: str
    tool_name: str
    description: str
    safety_level: str = "safe"
    input: Dict[str, Any] = field(default_factory=dict)
    status: str = "pending"
    output_summary: str = ""


@dataclass
class AgentTask:
    task_id: str
    session_id: str
    user_message: str
    route: str
    status: str
    created_at: float
    updated_at: float
    steps: List[AgentPlanStep] = field(default_factory=list)
    final_response: str = ""


@dataclass
class AgentTool:
    name: str
    description: str
    safety_level: str


class AgentTaskStore:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir

    def _path_for(self, task_id: str) -> Path:
        return self.base_dir / f"task_{task_id}.json"

    def save(self, task: AgentTask) -> None:
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
        self._path_for(task.task_id).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def load(self, task_id: str) -> Optional[AgentTask]:
        path = self._path_for(task_id)
        if not path.exists():
            return None

        data = json.loads(path.read_text(encoding="utf-8"))
        steps = [AgentPlanStep(**step) for step in data.get("steps", [])]
        return AgentTask(
            task_id=data["task_id"],
            session_id=data["session_id"],
            user_message=data["user_message"],
            route=data.get("route", "unknown"),
            status=data.get("status", "unknown"),
            created_at=float(data.get("created_at", time.time())),
            updated_at=float(data.get("updated_at", time.time())),
            steps=steps,
            final_response=data.get("final_response", ""),
        )


class AgentService:
    def __init__(
        self,
        chat_service: ChatService,
        groq_service: GroqService,
        realtime_service: Optional[RealtimeGroqService] = None,
        brain_service: Optional[BrainService] = None,
        caller_lookup_service: Optional[CallerLookupService] = None,
        automation_service: Optional[AutomationService] = None,
        reminder_service: Optional[ReminderService] = None,
        phone_command_service: Optional[PhoneCommandService] = None,
        wake_on_lan_service: Optional[WakeOnLanService] = None,
    ):
        self.chat_service = chat_service
        self.groq_service = groq_service
        self.realtime_service = realtime_service
        self.brain_service = brain_service
        self.caller_lookup_service = caller_lookup_service
        self.automation_service = automation_service
        self.reminder_service = reminder_service
        self.phone_command_service = phone_command_service
        self.wake_on_lan_service = wake_on_lan_service
        self.task_store = AgentTaskStore(AGENT_TASKS_DIR)
        self.tools = self._build_tools()

    def _build_tools(self) -> Dict[str, AgentTool]:
        return {
            "general_chat": AgentTool(
                name="general_chat",
                description="Answer from knowledge and memory without live web search.",
                safety_level="safe",
            ),
            "realtime_chat": AgentTool(
                name="realtime_chat",
                description="Answer with live web search and current context.",
                safety_level="safe",
            ),
            "automation": AgentTool(
                name="automation",
                description="Perform local desktop, app, browser, and file automation tasks.",
                safety_level="confirm",
            ),
            "reminder": AgentTool(
                name="reminder",
                description="Create and manage reminders for the user.",
                safety_level="safe",
            ),
            "caller_lookup": AgentTool(
                name="caller_lookup",
                description="Look up caller identity from public web sources.",
                safety_level="safe",
            ),
            "recent_target": AgentTool(
                name="recent_target",
                description="Recall the most recent file or folder Jarvis created or changed.",
                safety_level="safe",
            ),
            "write_and_save": AgentTool(
                name="write_and_save",
                description="Generate text and save it to a file through the automation layer.",
                safety_level="confirm",
            ),
            "phone_control": AgentTool(
                name="phone_control",
                description="Queue a command for the Android companion to answer, reject, or place a call from contacts.",
                safety_level="confirm",
            ),
            "wake_laptop": AgentTool(
                name="wake_laptop",
                description="Send a Wake-on-LAN packet to power on the laptop.",
                safety_level="safe",
            ),
        }

    def get_task(self, task_id: str) -> Optional[AgentTask]:
        return self.task_store.load(task_id)

    def process_message(self, session_id: str, user_message: str) -> AgentTask:
        final_task: Optional[AgentTask] = None
        for item in self.process_message_stream(session_id, user_message):
            if isinstance(item, dict) and item.get("_agent_task"):
                final_task = item["_agent_task"]
        if final_task is None:
            raise RuntimeError("Agent task did not complete.")
        return final_task

    def process_message_stream(
        self,
        session_id: str,
        user_message: str,
    ) -> Iterator[Union[str, Dict[str, Any]]]:
        logger.info("[AGENT] Session: %s | User: %.200s", session_id[:12], user_message)

        self.chat_service.add_message(session_id, "user", user_message)
        self.chat_service.add_message(session_id, "assistant", "")

        task = AgentTask(
            task_id=str(uuid.uuid4()),
            session_id=session_id,
            user_message=user_message,
            route="planning",
            status="in_progress",
            created_at=time.time(),
            updated_at=time.time(),
        )
        self.task_store.save(task)

        yield {"_activity": {"event": "task_created", "task_id": task.task_id}}

        chat_history = self.chat_service.format_history_for_llm(session_id, exclude_last=True)
        plan_steps, route = self._build_plan(user_message, chat_history)
        task.route = route
        task.steps = plan_steps
        task.updated_at = time.time()
        self.task_store.save(task)

        yield {
            "_activity": {
                "event": "plan_created",
                "route": route,
                "steps": [
                    {
                        "step_id": step.step_id,
                        "tool_name": step.tool_name,
                        "description": step.description,
                        "safety_level": step.safety_level,
                    }
                    for step in task.steps
                ],
            }
        }

        try:
            for step in task.steps:
                step.status = "in_progress"
                task.updated_at = time.time()
                self.task_store.save(task)

                yield {
                    "_activity": {
                        "event": "step_started",
                        "task_id": task.task_id,
                        "step_id": step.step_id,
                        "tool_name": step.tool_name,
                        "description": step.description,
                        "safety_level": step.safety_level,
                    }
                }

                for item in self._execute_step(task, step):
                    if isinstance(item, str):
                        self.chat_service.sessions[session_id][-1].content += item
                    yield item

                step.status = "completed"
                task.updated_at = time.time()
                self.task_store.save(task)

                yield {
                    "_activity": {
                        "event": "step_completed",
                        "task_id": task.task_id,
                        "step_id": step.step_id,
                        "tool_name": step.tool_name,
                        "summary": step.output_summary,
                    }
                }

            task.status = "completed"
            task.final_response = self.chat_service.sessions[session_id][-1].content
            task.updated_at = time.time()
            self.task_store.save(task)
            self.chat_service.save_chat_session(session_id)

            yield {
                "_agent_task": task,
                "_activity": {
                    "event": "task_completed",
                    "task_id": task.task_id,
                    "route": task.route,
                    "status": task.status,
                },
            }

        except Exception as exc:
            task.status = "failed"
            task.updated_at = time.time()
            if not self.chat_service.sessions[session_id][-1].content:
                self.chat_service.sessions[session_id][-1].content = str(exc)
            task.final_response = self.chat_service.sessions[session_id][-1].content
            self.task_store.save(task)
            self.chat_service.save_chat_session(session_id)
            raise

    def _build_plan(
        self,
        user_message: str,
        chat_history: List[tuple],
    ) -> tuple[List[AgentPlanStep], str]:
        recent_target_response = self.chat_service._handle_recent_target_query(user_message)
        if recent_target_response is not None:
            return (
                [
                    AgentPlanStep(
                        step_id=self._step_id(),
                        tool_name="recent_target",
                        description="Recall the most recent file or folder target.",
                        input={"response": recent_target_response},
                    )
                ],
                "recent_target",
            )

        write_and_save = self.chat_service._extract_write_and_save_request(user_message)
        if write_and_save and self.automation_service:
            return (
                [
                    AgentPlanStep(
                        step_id=self._step_id(),
                        tool_name="write_and_save",
                        description=f"Write content and save it as {write_and_save['filename']}.",
                        input=write_and_save,
                    )
                ],
                "write_and_save",
            )

        mixed_intent = self.chat_service._split_action_and_followup(user_message)
        if mixed_intent and self.automation_service:
            action_text, followup_text = mixed_intent
            followup_route, reasoning, elapsed = self._classify_message(followup_text, chat_history)
            return (
                [
                    AgentPlanStep(
                        step_id=self._step_id(),
                        tool_name="automation",
                        description=f"Run automation action: {action_text}",
                        input={"command": action_text},
                    ),
                    AgentPlanStep(
                        step_id=self._step_id(),
                        tool_name=followup_route,
                        description=f"Answer the follow-up after automation ({reasoning}).",
                        input={
                            "message": followup_text,
                            "reasoning": reasoning,
                            "elapsed_ms": elapsed,
                        },
                    ),
                ],
                "automation_then_" + followup_route,
            )

        if self.automation_service and self.automation_service.looks_like_automation_request(user_message):
            return (
                [
                    AgentPlanStep(
                        step_id=self._step_id(),
                        tool_name="automation",
                        description=f"Run automation action: {user_message}",
                        input={"command": user_message},
                    )
                ],
                "automation",
            )

        if self.phone_command_service and self.phone_command_service.looks_like_answer_request(user_message):
            return (
                [
                    AgentPlanStep(
                        step_id=self._step_id(),
                        tool_name="phone_control",
                        description="Queue a command to answer the active phone call.",
                        input={"action": "answer_call"},
                    )
                ],
                "phone_control",
            )

        if self.phone_command_service and self.phone_command_service.looks_like_reject_request(user_message):
            return (
                [
                    AgentPlanStep(
                        step_id=self._step_id(),
                        tool_name="phone_control",
                        description="Queue a command to reject the active phone call.",
                        input={"action": "reject_call"},
                    )
                ],
                "phone_control",
            )

        if self.phone_command_service:
            call_followup = self.phone_command_service.handle_call_method_followup(user_message)
            if call_followup:
                return (
                    [
                        AgentPlanStep(
                            step_id=self._step_id(),
                            tool_name="phone_control",
                            description="Queue the requested contact call on the Android companion.",
                            input={"action": "place_call", "result": call_followup},
                        )
                    ],
                    "phone_control",
                )

        if self.phone_command_service and self.phone_command_service.looks_like_place_call_request(user_message):
            return (
                [
                    AgentPlanStep(
                        step_id=self._step_id(),
                        tool_name="phone_control",
                        description="Queue a contact call on the Android companion.",
                        input={"action": "place_call", "message": user_message},
                    )
                ],
                "phone_control",
            )

        if self.wake_on_lan_service and self.wake_on_lan_service.looks_like_wake_request(user_message):
            return (
                [
                    AgentPlanStep(
                        step_id=self._step_id(),
                        tool_name="wake_laptop",
                        description="Send a Wake-on-LAN packet to the laptop.",
                        input={},
                    )
                ],
                "wake_laptop",
            )

        if self.reminder_service and self.reminder_service.looks_like_reminder_request(user_message):
            return (
                [
                    AgentPlanStep(
                        step_id=self._step_id(),
                        tool_name="reminder",
                        description="Create a reminder for the user.",
                        input={"command": user_message},
                    )
                ],
                "reminder",
            )

        if self.caller_lookup_service and self.caller_lookup_service.looks_like_lookup_request(user_message):
            phone_number = self.caller_lookup_service.extract_phone_number(user_message) or ""
            return (
                [
                    AgentPlanStep(
                        step_id=self._step_id(),
                        tool_name="caller_lookup",
                        description=f"Look up public information for {phone_number}.",
                        input={"phone_number": phone_number, "question": user_message},
                    )
                ],
                "caller_lookup",
            )

        route, reasoning, elapsed = self._classify_message(user_message, chat_history)
        return (
            [
                AgentPlanStep(
                    step_id=self._step_id(),
                    tool_name=route,
                    description=f"Answer with the {route} tool.",
                    input={"message": user_message, "reasoning": reasoning, "elapsed_ms": elapsed},
                )
            ],
            route,
        )

    def _classify_message(
        self,
        user_message: str,
        chat_history: List[tuple],
    ) -> tuple[str, str, int]:
        if not self.brain_service:
            return ("realtime_chat", "Brain unavailable; defaulting to realtime.", 0)

        fast_route = self.brain_service.classify_fast(user_message)
        if fast_route is not None:
            query_type, reasoning = fast_route
            return (self._route_to_tool_name(query_type), reasoning, 0)

        brain_idx, _ = get_next_key_pair(len(GROQ_API_KEYS), need_brain=True)
        query_type, reasoning, elapsed_ms = self.brain_service.classify(
            user_message,
            chat_history,
            key_index=brain_idx,
        )
        return (self._route_to_tool_name(query_type), reasoning, elapsed_ms)

    def _execute_step(
        self,
        task: AgentTask,
        step: AgentPlanStep,
    ) -> Iterator[Union[str, Dict[str, Any]]]:
        tool_name = step.tool_name

        if tool_name == "recent_target":
            response = str(step.input.get("response", "I do not have a recent target yet."))
            step.output_summary = self._shorten(response)
            yield response
            return

        if tool_name == "write_and_save":
            if not self.automation_service:
                raise RuntimeError("Automation service is not initialized.")
            prompt = str(step.input.get("prompt", "")).strip()
            filename = str(step.input.get("filename", "")).strip()
            step.output_summary = f"Generating content for {filename}"
            yield {"_activity": {"event": "task_started", "message": step.output_summary}}
            content = self.groq_service.get_response(
                question=prompt,
                chat_history=self.chat_service.format_history_for_llm(task.session_id, exclude_last=True),
                key_start_index=get_next_key_pair(len(GROQ_API_KEYS), need_brain=False)[1],
            )
            save_result = self.automation_service.create_file_with_content(filename, content)
            response = self.chat_service._build_write_and_save_response(str(save_result["message"]), content)
            step.output_summary = self._shorten(str(save_result["message"]))
            yield {"_activity": {"event": "task_completed", "message": str(save_result["message"])}}
            yield response
            return

        if tool_name == "automation":
            if not self.automation_service:
                raise RuntimeError("Automation service is not initialized.")
            command = str(step.input.get("command", "")).strip()
            result = self.automation_service.execute(command)
            response = str(result["message"])
            step.output_summary = self._shorten(response)
            yield {"_activity": {"event": "tool_result", "tool_name": tool_name, "message": response}}
            yield response
            return

        if tool_name == "reminder":
            if not self.reminder_service:
                raise RuntimeError("Reminder service is not initialized.")
            result = self.reminder_service.create_reminder(str(step.input.get("command", "")))
            response = str(result["message"])
            step.output_summary = self._shorten(response)
            yield {"_activity": {"event": "tool_result", "tool_name": tool_name, "message": response}}
            yield response
            return

        if tool_name == "caller_lookup":
            if not self.caller_lookup_service:
                raise RuntimeError("Caller lookup service is not initialized.")
            phone_number = str(step.input.get("phone_number", "")).strip()
            question = str(step.input.get("question", "")).strip()
            yield {
                "_activity": {
                    "event": "searching_web",
                    "query": phone_number,
                    "message": f"Looking up public caller information for {phone_number}",
                }
            }
            result = self.caller_lookup_service.lookup_caller(
                phone_number=phone_number,
                original_question=question,
            )
            response = str(result["summary"])
            step.output_summary = self._shorten(response)
            yield {
                "_search_results": {
                    "query": result["normalized_number"],
                    "answer": result["summary"],
                    "results": result["results"],
                }
            }
            yield response
            return

        if tool_name == "phone_control":
            if not self.phone_command_service:
                raise RuntimeError("Phone command service is not initialized.")
            action = str(step.input.get("action", "answer_call")).strip().lower()
            if action == "place_call":
                result = step.input.get("result")
                if not isinstance(result, dict):
                    result = self.phone_command_service.handle_place_call_request(
                        str(step.input.get("message", "")).strip()
                    )
            elif action == "reject_call":
                result = self.phone_command_service.queue_reject_call()
            else:
                result = self.phone_command_service.queue_answer_call()
            response = str(result["message"])
            step.output_summary = self._shorten(response)
            yield {"_activity": {"event": "tool_result", "tool_name": tool_name, "message": response}}
            yield response
            return

        if tool_name == "wake_laptop":
            if not self.wake_on_lan_service:
                raise RuntimeError("Wake-on-LAN service is not initialized.")
            result = self.wake_on_lan_service.wake_laptop()
            response = str(result["message"])
            step.output_summary = self._shorten(response)
            yield {"_activity": {"event": "tool_result", "tool_name": tool_name, "message": response}}
            yield response
            return

        if tool_name == "general_chat":
            yield from self._stream_general_chat(task, step)
            return

        if tool_name == "realtime_chat":
            yield from self._stream_realtime_chat(task, step)
            return

        raise RuntimeError(f"Unknown agent tool: {tool_name}")

    def _stream_general_chat(
        self,
        task: AgentTask,
        step: AgentPlanStep,
    ) -> Iterator[Union[str, Dict[str, Any]]]:
        message = str(step.input.get("message", task.user_message))
        chat_history = self.chat_service.format_history_for_llm(task.session_id, exclude_last=True)
        _, chat_idx = get_next_key_pair(len(GROQ_API_KEYS), need_brain=False)
        step.output_summary = self._shorten("Answered from knowledge and memory.")

        yield {"_activity": {"event": "routing", "route": "general"}}
        yield {"_activity": {"event": "streaming_started", "route": "general"}}

        for chunk in self.groq_service.stream_response(
            question=message,
            chat_history=chat_history,
            key_start_index=chat_idx,
        ):
            yield chunk

    def _stream_realtime_chat(
        self,
        task: AgentTask,
        step: AgentPlanStep,
    ) -> Iterator[Union[str, Dict[str, Any]]]:
        if not self.realtime_service:
            raise RuntimeError("Realtime service is not initialized.")

        message = str(step.input.get("message", task.user_message))
        chat_history = self.chat_service.format_history_for_llm(task.session_id, exclude_last=True)
        _, chat_idx = get_next_key_pair(len(GROQ_API_KEYS), need_brain=False)
        reasoning = str(step.input.get("reasoning", "Needs live web search"))
        elapsed_ms = int(step.input.get("elapsed_ms", 0))
        step.output_summary = self._shorten("Answered with live web search.")

        yield {
            "_activity": {
                "event": "decision",
                "query_type": "realtime",
                "reasoning": reasoning,
                "elapsed_ms": elapsed_ms,
            }
        }
        yield {"_activity": {"event": "routing", "route": "realtime"}}

        formatted_results, search_payload = self.realtime_service.prefetch_web_search(message, chat_history)
        if search_payload:
            yield {"_activity": search_payload}

        yield {"_activity": {"event": "streaming_started", "route": "realtime"}}

        for chunk in self.realtime_service.stream_response_with_prefetched(
            question=message,
            chat_history=chat_history,
            formatted_results=formatted_results,
            payload=search_payload,
            key_start_index=chat_idx,
        ):
            yield chunk

    def _route_to_tool_name(self, query_type: str) -> str:
        return "general_chat" if query_type == "general" else "realtime_chat"

    def _step_id(self) -> str:
        return str(uuid.uuid4())[:8]

    def _shorten(self, text: str, limit: int = 140) -> str:
        cleaned = re.sub(r"\s+", " ", (text or "").strip())
        if len(cleaned) <= limit:
            return cleaned
        return cleaned[: limit - 3].rstrip() + "..."
