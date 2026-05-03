"""
JARVIS MAIN API
===============

This module defines the FastAPI application and all HTTP endpoints. It is
designed for single-user use: one person runs one server (e.g. python run.py)
and uses it as their personal J.A.R.V.I.S backend. Many people can each run
their own copy of this code on their own machine.

ENDPOINTS:
GET /                  - Returns API name and list of endpoints.
GET /health            - Returns status of all services (for monitoring).
POST /chat             - General chat: pure LLM, no web search. Uses learning data
                         and past chats via vector-store retrieval only.
POST /chat/realtime    - Realtime chat: runs a Tavily web search first, then
                         sends results + context to Groq. Same session as /chat.
GET /chat/history/{id} - Returns all messages for a session (general + realtime).

SESSION:
Both /chat and /chat/realtime use the same session_id. If you omit session_id,
the server generates a UUID and returns it; send it back on the next request
to continue the conversation. Sessions are saved to disk and survive restarts.

STARTUP:
On startup, the lifespan function builds the vector store from learning_data/*.txt
and chats_data/*.json, then creates Groq, Realtime, and Chat services. On shutdown,
it saves all in-memory sessions to disk.
"""

from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, RedirectResponse, Response, FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from contextlib import asynccontextmanager
import uvicorn
import logging
import json
import time
import re
import os
import base64
import asyncio
import secrets
import platform
import socket
import threading
import shutil
import subprocess
import tempfile
import random
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
import edge_tts
import psutil
from app.models import (
    ChatRequest,
    ChatResponse,
    TTSRequest,
    FaceEnrollStartRequest,
    FaceEnrollSampleRequest,
    FaceEnrollBatchRequest,
    FaceEnrollCompleteRequest,
    FaceVerifyRequest,
    CommandRiskRequest,
    StepUpStartRequest,
    StepUpVerifyRequest,
    LauncherBootstrapCreateRequest,
    LauncherBootstrapExchangeRequest,
)
from app.adapters.providers.stt_provider import stt_provider_readiness
from app.core.config_loader import ConfigLoader
from app.tools.stt_tool import STTTool
from app.tools.base import ToolContext

RATE_LIMIT_MESSAGE = (
    "You've reached your daily API limit for this assistant. "
    "Your credits will reset in a few hours, or you can upgrade your plan for more. "
    "Please try again later."
)

def _is_rate_limit_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "429" in str(exc) or "rate limit" in msg or "tokens per day" in msg

from app.services.vector_store import VectorStoreService
from app.services.groq_service import GroqService, AllGroqApisFailedError
from app.services.realtime_service import RealtimeGroqService
from app.services.chat_service import ChatService
from app.services.brain_service import BrainService
from app.services.task_executor import TaskExecutor
from app.services.task_executor import TaskResponse
from app.services.vision_service import VisionService
from app.services.task_manager import TaskManager
from app.services.automation_service import AutomationService
from app.services.caller_lookup_service import CallerLookupService
from app.services.phone_command_service import PhoneCommandService
from app.services.wake_on_lan_service import WakeOnLanService
from app.services.reminder_service import ReminderService
from app.services.research_tools_service import ResearchToolsService
from app.services.fast_intent_router_service import FastIntentRouterService
from app.services.acknowledgement_service import AcknowledgementService, DynamicPhraseGenerator
from app.services.interrupt_manager import InterruptManager
from app.services.latency_metrics_service import LatencyTracker
from app.bootstrap.container import build_container
from app.core.contracts import AssistantRequest
from app.services.face_identity_service import FaceIdentityService
from app.services.face_enrollment_service import FaceEnrollmentService
from app.services.command_risk_service import CommandRiskService
from app.services.step_up_auth_service import StepUpAuthService
from app.services.launcher_bootstrap_service import LauncherBootstrapService

from config import (
    VECTOR_STORE_DIR, GROQ_API_KEYS, GROQ_MODEL, TAVILY_API_KEY,
    EMBEDDING_MODEL, CHUNK_SIZE, CHUNK_OVERLAP, MAX_CHAT_HISTORY_TURNS,
    ASSISTANT_NAME, TTS_VOICE, TTS_RATE, TTS_PROVIDER,
    EDGE_TTS_VOICE, EDGE_TTS_RATE, EDGE_TTS_VOLUME, EDGE_TTS_PITCH,
    EDGE_TTS_PUNCTUATION_PAUSE_MODE, EDGE_TTS_ENABLE_SSML_PAUSES,
    EDGE_TTS_FAST_RATE, EDGE_TTS_MAX_SENTENCE_CHARS,
    EDGE_TTS_NORMALIZE_DATES, EDGE_TTS_NORMALIZE_NUMBERS, EDGE_TTS_DEBUG_TEXT,
    TTS_NO_OVERLAP, TTS_INTERRUPT_POLICY,
    THINKING_AUDIO_ENABLED, THINKING_AUDIO_PROVIDER, THINKING_AUDIO_PHRASES,
    THINKING_AUDIO_RANDOMIZE, THINKING_AUDIO_MAX_SECONDS, THINKING_AUDIO_RATE,
    THINKING_AUDIO_AVOID_REPEAT, THINKING_AUDIO_LAST_PHRASE_MEMORY,
    THINKING_AUDIO_MAX_PER_REQUEST, THINKING_AUDIO_VOLUME,
    THINKING_AUDIO_FINISH_BEFORE_FINAL_TTS, THINKING_AUDIO_STOP_ON_FINAL_TTS,
    THINKING_AUDIO_FINAL_TTS_WAIT_TIMEOUT_MS, THINKING_AUDIO_INTERRUPTIBLE,
    THINKING_AUDIO_CACHE_ENABLED, THINKING_AUDIO_DEBUG,
    STT_MIN_RECORD_SECONDS, STT_END_SILENCE_SECONDS, STT_MAX_RECORD_SECONDS, STT_SPEECH_PADDING_MS, STT_CAPTURE_MODE,
    STT_PROVIDER_CACHE_ENABLED, PARAKEET_PRELOAD_ON_STARTUP, STT_WARMUP_ON_STARTUP, STT_FAIL_FAST_ON_WARMUP_ERROR,
    STT_DOMAIN_CORRECTION_ENABLED, STT_EMPTY_TRANSCRIPT_BEHAVIOR, STT_EMPTY_TRANSCRIPT_PROMPT,
    FACE_GATE_ENABLED, FACE_GATE_SCOPE, FACE_IN_APP_RECOGNITION_ENABLED, FACE_STEP_UP_FOR_TOOLS_ENABLED,
    FACE_STATUS_IN_APP_ENABLED, FACE_VERIFY_IN_APP_ENABLED,
    SMART_AUTOMATION_ENABLED, SEMANTIC_PLANNER_ENABLED, SEMANTIC_SAFE_EXECUTION_ENABLED,
    AUTOMATION_CONTEXT_ENABLED, AUTOMATION_DRY_RUN_ENABLED, AUTOMATION_DUPLICATE_PROTECTION_ENABLED,
    CALLER_LOOKUP_PROVIDER,
    PHONE_BRIDGE_TOKEN, CORS_ORIGINS,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

logger = logging.getLogger("J.A.R.V.I.S")
QUIET_REQUEST_LOG_PATHS = {"/system/metrics"}


class QuietEndpointAccessFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        return not any(path in message for path in QUIET_REQUEST_LOG_PATHS)


logging.getLogger("uvicorn.access").addFilter(QuietEndpointAccessFilter())

_network_metric_sample = {
    "timestamp": None,
    "bytes_sent": None,
    "bytes_recv": None,
}

vector_store_service: VectorStoreService = None
groq_service: GroqService = None
realtime_service: RealtimeGroqService = None
brain_service: BrainService = None
task_executor: TaskExecutor = None
task_manager: TaskManager = None
vision_service: VisionService = None
chat_service: ChatService = None
automation_service: AutomationService = None
caller_lookup_service: CallerLookupService = None
phone_command_service: PhoneCommandService = None
wake_on_lan_service: WakeOnLanService = None
reminder_service: ReminderService = None
research_tools_service: ResearchToolsService = None
fast_intent_router_service: FastIntentRouterService = None
acknowledgement_service: AcknowledgementService = None
face_identity_service: FaceIdentityService = None
face_enrollment_service: FaceEnrollmentService = None
command_risk_service: CommandRiskService = None
step_up_auth_service: StepUpAuthService = None
launcher_bootstrap_service: LauncherBootstrapService = None
interrupt_manager: InterruptManager = None
assistant_orchestrator = None
app_container = None
_pending_command_confirmations = {}

def print_title():
    """Print a console-safe J.A.R.V.I.S banner."""
    title = """

    +--------------------------------------------------+
    |                      JARVIS                      |
    |        Just A Rather Very Intelligent System     |
    +--------------------------------------------------+
    """
    print(title)

@asynccontextmanager
async def lifespan(app: FastAPI):
    global vector_store_service, groq_service, realtime_service, brain_service
    global task_executor, task_manager, vision_service, chat_service, automation_service
    global caller_lookup_service, phone_command_service, wake_on_lan_service
    global reminder_service, research_tools_service
    global fast_intent_router_service, acknowledgement_service, face_identity_service, face_enrollment_service
    global command_risk_service, step_up_auth_service, launcher_bootstrap_service, interrupt_manager
    global assistant_orchestrator, app_container

    print_title()
    logger.info("=" * 60)
    logger.info("J.A.R.V.I.S - Starting Up...")
    logger.info("=" * 60)

    logger.info("[CONFIG] Assistant name: %s", ASSISTANT_NAME)
    logger.info("[CONFIG] Groq model: %s", GROQ_MODEL)
    logger.info("[CONFIG] Groq API keys loaded: %d", len(GROQ_API_KEYS))
    logger.info("[CONFIG] Tavily API key: %s", "configured" if TAVILY_API_KEY else "NOT SET")
    logger.info("[CONFIG] Caller lookup provider: %s", CALLER_LOOKUP_PROVIDER or "none")
    logger.info("[CONFIG] Image generation: Pollinations.ai (free, no API key)")
    logger.info("[CONFIG] Embedding model: %s", EMBEDDING_MODEL)
    logger.info(
        "[CONFIG] Chunk size: %d | Overlap: %d | Max history turns: %d",
        CHUNK_SIZE, CHUNK_OVERLAP, MAX_CHAT_HISTORY_TURNS
    )
    stt_status = _stt_capture_runtime_config()
    logger.info(
        "[STT] capture_mode=%s provider=%s model=%s device=%s require_wav=%s ffmpeg_available=%s readiness=%s",
        stt_status.get("capture_mode"),
        stt_status.get("provider"),
        stt_status.get("model"),
        stt_status.get("device"),
        str(stt_status.get("require_wav")).lower(),
        str(stt_status.get("ffmpeg_available")).lower(),
        "available" if stt_status.get("available") else stt_status.get("reason"),
    )
    semantic_status = _semantic_runtime_config()
    logger.info(
        "[SEMANTIC] smart=%s planner=%s safe_execution=%s context=%s duplicate=%s dry_run=%s",
        str(semantic_status["smart_enabled"]).lower(),
        str(semantic_status["planner_enabled"]).lower(),
        str(semantic_status["safe_execution_enabled"]).lower(),
        str(semantic_status["context_enabled"]).lower(),
        str(semantic_status["duplicate_protection_enabled"]).lower(),
        str(semantic_status["dry_run_enabled"]).lower(),
    )
    if semantic_status["safe_execution_enabled"]:
        logger.info("[SEMANTIC] safe execution enabled for LOW/MEDIUM actions only")
    else:
        logger.info("[SEMANTIC] safe execution disabled; live commands use legacy routing")
    _get_stt_tool(app, force_rebuild=not _stt_provider_cache_enabled())
    _run_startup_stt_warmup(app)

    try:
        t0 = time.perf_counter()
        app_container = build_container()
        logger.info("[TIMING] startup_container: %.3fs", time.perf_counter() - t0)
        vector_store_service = app_container.vector_store_service
        groq_service = app_container.groq_service
        realtime_service = app_container.realtime_service
        brain_service = app_container.brain_service
        task_executor = app_container.task_executor
        task_manager = app_container.task_manager
        vision_service = app_container.vision_service
        chat_service = app_container.chat_service
        automation_service = app_container.automation_service
        caller_lookup_service = app_container.caller_lookup_service
        phone_command_service = app_container.phone_command_service
        wake_on_lan_service = app_container.wake_on_lan_service
        reminder_service = app_container.reminder_service
        research_tools_service = app_container.research_tools_service
        fast_intent_router_service = app_container.fast_intent_router_service
        acknowledgement_service = app_container.acknowledgement_service
        face_identity_service = app_container.face_identity_service
        face_enrollment_service = app_container.face_enrollment_service
        command_risk_service = app_container.command_risk_service
        step_up_auth_service = app_container.step_up_auth_service
        launcher_bootstrap_service = app_container.launcher_bootstrap_service
        interrupt_manager = app_container.interrupt_manager
        assistant_orchestrator = app_container.orchestrator

        logger.info("=" * 60)
        logger.info("Service Status:")
        vector_status = (
            vector_store_service.status()
            if vector_store_service is not None and hasattr(vector_store_service, "status")
            else {"available": False, "degraded": True, "reason": "not initialized"}
        )
        logger.info(
            " - Vector Store: %s",
            "Ready" if vector_status.get("available") else f"Degraded ({vector_status.get('reason')})",
        )
        logger.info(" - Groq AI (General): Ready")
        logger.info(" - Groq AI (Realtime): Ready")
        logger.info(" - Brain (Unified Decision): Ready")
        logger.info(" - Task Executor: Ready")
        logger.info(" - Automation: Ready")
        logger.info(" - Phone Bridge: Ready")
        logger.info(" - Wake-on-LAN: %s", "Ready" if wake_on_lan_service and wake_on_lan_service.is_configured() else "Not configured")
        logger.info(" - Reminders: Ready")
        logger.info(" - Research Tools: Ready")
        logger.info(" - Fast Intent Router: Ready")
        logger.info(" - Acknowledgements: Ready")
        logger.info(" - Face Gate: %s", _face_runtime_config(face_identity_service))
        logger.info(" - In-App Face Recognition: %s", "Enabled" if FACE_IN_APP_RECOGNITION_ENABLED else "Disabled")
        logger.info(" - Step-up Auth: Ready (%s)", "tool face step-up enabled" if FACE_STEP_UP_FOR_TOOLS_ENABLED else "tool face step-up disabled")
        logger.info(" - Interrupt Manager: Ready")
        logger.info(" - Background Task Manager: Ready")
        logger.info(" - Vision (Groq): Ready")
        logger.info(" - Chat Service: Ready")
        logger.info("=" * 60)

        logger.info("J.A.R.V.I.S is online and ready!")
        logger.info("API: http://localhost:8000")
        logger.info("Launcher: http://localhost:8000/launcher/ (open in browser)")
        logger.info("Frontend: http://localhost:8000/app/")
        logger.info("=" * 60)

        yield

        logger.info("\nShutting down J.A.R.V.I.S...")
        _tts_pool.shutdown(wait=True)

        if app_container:
            app_container.shutdown()

        logger.info("All sessions saved. Goodbye!")

    except Exception as e:
        logger.error(f"Fatal error during startup: {e}", exc_info=True)
        raise

app = FastAPI(
    title="J.A.R.V.I.S API",
    description="Just A Rather Very Intelligent System",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _require_phone_bridge_token(request: Request) -> None:
    if not PHONE_BRIDGE_TOKEN:
        return

    supplied = request.headers.get("X-Jarvis-Token", "")
    if not secrets.compare_digest(supplied, PHONE_BRIDGE_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid or missing phone bridge token")

class TimingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        t0 = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - t0
        path = request.url.path
        if path.startswith("/app") or path.startswith("/launcher") or path.startswith("/enroll") or path == "/favicon.ico":
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        if path not in QUIET_REQUEST_LOG_PATHS:
            logger.info("[REQUEST] %s %s -> %s (%.3fs)", request.method, path, response.status_code, elapsed)
        return response


app.add_middleware(TimingMiddleware)


class NoCacheStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        response.headers["ETag"] = str(time.time_ns())
        return response


@app.get("/api")
async def api_info():
    return {
        "message": "J.A.R.V.I.S API",
        "endpoints": {
            "/chat": "General chat (non-streaming)",
            "/chat/stream": "General chat (streaming chunks)",
            "/chat/realtime": "Realtime chat (non-streaming)",
            "/chat/realtime/stream": "Realtime chat (streaming chunks)",
            "/chat/jarvis/stream": "Jarvis unified route (two-stage brain: classify → route → execute/stream)",
            "/chat/history/{session_id}": "Get chat history",
            "/tasks/{task_id}": "Get background task status and result",
            "/health": "System health check",
            "/tts": "Text-to-speech (POST text, returns streamed MP3)"
        }
    }

@app.get("/health")
async def health():
    try:
        return {
            "status": "healthy",
            "vector_store": vector_store_service is not None,
            "retrieval": (
                vector_store_service.status()
                if vector_store_service is not None and hasattr(vector_store_service, "status")
                else {"available": False, "degraded": True, "reason": "vector store service not initialized"}
            ),
            "groq_service": groq_service is not None,
            "realtime_service": realtime_service is not None,
            "brain_service": brain_service is not None,
            "task_executor": task_executor is not None,
            "automation_service": automation_service is not None,
            "task_manager": task_manager is not None,
            "vision_service": vision_service is not None,
            "chat_service": chat_service is not None,
            "caller_lookup_service": caller_lookup_service is not None,
            "phone_command_service": phone_command_service is not None,
            "wake_on_lan_service": wake_on_lan_service is not None,
            "reminder_service": reminder_service is not None,
            "research_tools_service": research_tools_service is not None,
            "fast_intent_router_service": fast_intent_router_service is not None,
            "acknowledgement_service": acknowledgement_service is not None,
            "face_identity_service": face_identity_service is not None,
            "step_up_auth_service": step_up_auth_service is not None,
            "launcher_bootstrap_service": launcher_bootstrap_service is not None,
            "interrupt_manager": interrupt_manager is not None,
            "tts": _tts_runtime_config(),
            "stt": _stt_capture_runtime_config(),
            "semantic": _semantic_runtime_config(),
            "face_gate": _face_runtime_config(face_identity_service),
            "face_in_app": {
                "enabled": bool(FACE_IN_APP_RECOGNITION_ENABLED),
                "status_enabled": bool(FACE_STATUS_IN_APP_ENABLED),
                "verify_enabled": bool(FACE_VERIFY_IN_APP_ENABLED),
                "step_up_for_tools_enabled": bool(FACE_STEP_UP_FOR_TOOLS_ENABLED),
            },
            "face_identity": face_identity_service.status() if face_identity_service else {"available": False},
            "wake_on_lan": (
                wake_on_lan_service.status()
                if wake_on_lan_service is not None
                else {"configured": False, "broadcast_ip": "", "port": 0}
            ),
        }
    except Exception as e:
        logger.warning("[API /health] Error: %s", e)
        return {"status": "degraded", "error": str(e)}


def _semantic_runtime_config() -> dict[str, object]:
    return {
        "smart_enabled": bool(SMART_AUTOMATION_ENABLED),
        "planner_enabled": bool(SEMANTIC_PLANNER_ENABLED),
        "safe_execution_enabled": bool(SEMANTIC_SAFE_EXECUTION_ENABLED),
        "context_enabled": bool(AUTOMATION_CONTEXT_ENABLED),
        "duplicate_protection_enabled": bool(AUTOMATION_DUPLICATE_PROTECTION_ENABLED),
        "dry_run_enabled": bool(AUTOMATION_DRY_RUN_ENABLED),
    }


def _face_runtime_config(service: FaceIdentityService | None = None) -> dict[str, object]:
    status = service.status() if service else {"available": False}
    return {
        "enabled": bool(FACE_GATE_ENABLED),
        "scope": FACE_GATE_SCOPE,
        "available": bool(status.get("available")),
        "profile_enrolled": bool(status.get("profile_enrolled", False)),
        "in_app_recognition_enabled": bool(FACE_IN_APP_RECOGNITION_ENABLED),
        "in_app_status_enabled": bool(FACE_STATUS_IN_APP_ENABLED),
        "in_app_verify_enabled": bool(FACE_VERIFY_IN_APP_ENABLED),
        "step_up_for_tools_enabled": bool(FACE_STEP_UP_FOR_TOOLS_ENABLED),
    }


def _format_bytes(value: float | int | None) -> str:
    if value is None:
        return "Unavailable"
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size) < 1024.0:
            return f"{size:.1f} {unit}" if unit != "B" else f"{size:.0f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PB"


def _primary_disk_path() -> str:
    if platform.system().lower() == "windows":
        return Path.home().anchor or "C:\\"
    return "/"


def _primary_disk_fstype(path: str) -> str:
    try:
        resolved = str(Path(path).resolve()).lower()
        best = None
        for partition in psutil.disk_partitions(all=False):
            mountpoint = partition.mountpoint.lower()
            if resolved.startswith(mountpoint) and (best is None or len(mountpoint) > len(best.mountpoint)):
                best = partition
        return best.fstype if best and best.fstype else "Unknown"
    except Exception:
        return "Unknown"


def _temperature_metric() -> dict:
    try:
        sensors = getattr(psutil, "sensors_temperatures", None)
        if not sensors:
            return {"available": False, "celsius": None, "label": "Unavailable"}
        readings = sensors() or {}
        for entries in readings.values():
            for entry in entries:
                current = getattr(entry, "current", None)
                if current is not None:
                    return {
                        "available": True,
                        "celsius": round(float(current), 1),
                        "label": getattr(entry, "label", "") or "Sensor",
                    }
    except Exception:
        pass
    return {"available": False, "celsius": None, "label": "Unavailable"}


def _battery_metric() -> dict:
    try:
        battery = psutil.sensors_battery()
        if battery is None:
            return {"available": False, "percent": None, "plugged": None, "status": "Unavailable"}
        return {
            "available": True,
            "percent": round(float(battery.percent), 1) if battery.percent is not None else None,
            "plugged": bool(battery.power_plugged),
            "status": "AC powered" if battery.power_plugged else "On battery",
        }
    except Exception:
        return {"available": False, "percent": None, "plugged": None, "status": "Unavailable"}


def _protection_metric() -> dict:
    if platform.system().lower() != "windows":
        return {"available": False, "status": "Unknown", "detail": "Unsupported OS probe"}
    try:
        service = psutil.win_service_get("WinDefend")
        status = service.status()
        return {
            "available": True,
            "status": "Active" if status == "running" else "Inactive",
            "detail": f"WinDefend {status}",
        }
    except Exception:
        return {"available": False, "status": "Unknown", "detail": "Windows Defender status unavailable"}


def _connection_metric() -> dict:
    try:
        with socket.create_connection(("1.1.1.1", 53), timeout=0.35):
            return {"available": True, "status": "Stable"}
    except Exception:
        return {"available": True, "status": "Offline"}


def collect_system_metrics() -> dict:
    now = time.time()
    cpu_percent = psutil.cpu_percent(interval=None)
    cpu_freq = psutil.cpu_freq()
    memory = psutil.virtual_memory()
    disk_path = _primary_disk_path()
    disk = psutil.disk_usage(disk_path)
    net = psutil.net_io_counters()

    sent_rate = None
    recv_rate = None
    previous_ts = _network_metric_sample["timestamp"]
    if previous_ts and now > previous_ts:
        elapsed = max(now - previous_ts, 0.001)
        sent_rate = max(0.0, (net.bytes_sent - (_network_metric_sample["bytes_sent"] or net.bytes_sent)) / elapsed)
        recv_rate = max(0.0, (net.bytes_recv - (_network_metric_sample["bytes_recv"] or net.bytes_recv)) / elapsed)
    _network_metric_sample.update({
        "timestamp": now,
        "bytes_sent": net.bytes_sent,
        "bytes_recv": net.bytes_recv,
    })

    return {
        "timestamp": now,
        "platform": {
            "system": platform.system(),
            "machine": platform.machine(),
        },
        "cpu": {
            "percent": round(float(cpu_percent), 1),
            "frequency_mhz": round(float(cpu_freq.current), 1) if cpu_freq and cpu_freq.current else None,
            "physical_cores": psutil.cpu_count(logical=False),
            "logical_cores": psutil.cpu_count(logical=True),
        },
        "memory": {
            "percent": round(float(memory.percent), 1),
            "used": memory.used,
            "total": memory.total,
            "used_label": _format_bytes(memory.used),
            "total_label": _format_bytes(memory.total),
        },
        "disk": {
            "path": disk_path,
            "percent": round(float(disk.percent), 1),
            "used": disk.used,
            "total": disk.total,
            "used_label": _format_bytes(disk.used),
            "total_label": _format_bytes(disk.total),
            "filesystem": _primary_disk_fstype(disk_path),
        },
        "network": {
            "bytes_sent_rate": sent_rate,
            "bytes_recv_rate": recv_rate,
            "sent_rate_label": _format_bytes(sent_rate) + "/s" if sent_rate is not None else "Measuring",
            "recv_rate_label": _format_bytes(recv_rate) + "/s" if recv_rate is not None else "Measuring",
        },
        "battery": _battery_metric(),
        "temperature": _temperature_metric(),
        "protection": _protection_metric(),
        "connection": _connection_metric(),
    }


@app.get("/system/metrics")
async def system_metrics():
    try:
        return collect_system_metrics()
    except Exception as e:
        logger.warning("[API /system/metrics] Error: %s", e)
        raise HTTPException(status_code=503, detail="System metrics unavailable")


@app.get("/reminders/due")
async def reminders_due():
    if reminder_service is None:
        raise HTTPException(status_code=503, detail="Reminder service is not initialized")
    return {"reminders": reminder_service.get_due_reminders()}


@app.post("/control/sleep")
async def control_sleep():
    return {"status": "ok", "message": "Sleep acknowledged"}


@app.post("/face/enroll/start")
async def face_enroll_start(request: FaceEnrollStartRequest):
    if face_enrollment_service is None:
        raise HTTPException(status_code=503, detail="Face enrollment service is not initialized")
    return face_enrollment_service.start(user_name=request.user_name, replace_existing=request.replace_existing)


@app.post("/face/enroll/sample")
async def face_enroll_sample(request: FaceEnrollSampleRequest):
    if face_enrollment_service is None:
        raise HTTPException(status_code=503, detail="Face enrollment service is not initialized")
    try:
        return face_enrollment_service.add_sample(request.enrollment_session_id, request.frames)
    except Exception as exc:
        logger.warning("[FACE] Enroll sample failed: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/face/enroll/batch")
async def face_enroll_batch(request: FaceEnrollBatchRequest):
    if face_enrollment_service is None:
        raise HTTPException(status_code=503, detail="Face enrollment service is not initialized")
    try:
        return face_enrollment_service.add_batch(request.enrollment_session_id, request.frames)
    except Exception as exc:
        logger.warning("[FACE] Enroll batch failed: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/face/enroll/complete")
async def face_enroll_complete(request: FaceEnrollCompleteRequest):
    if face_enrollment_service is None:
        raise HTTPException(status_code=503, detail="Face enrollment service is not initialized")
    return face_enrollment_service.complete(request.enrollment_session_id)


@app.post("/face/verify")
async def face_verify(request: FaceVerifyRequest):
    if face_identity_service is None or launcher_bootstrap_service is None:
        raise HTTPException(status_code=503, detail="Face identity service is not initialized")
    payload = face_identity_service.verify_frames(
        request.frames,
        client_id=request.client_id,
        issue_session=True,
        request_id=request.request_id,
    )
    if str(request.client_id or "").strip().lower() != "launcher":
        return payload
    payload.setdefault("launcher_bootstrap_token", "")
    payload.setdefault("bootstrap_expires_in_seconds", 0)
    if str(payload.get("status") or "").lower() != "verified":
        return payload
    face_session_id = str(payload.get("face_session_id") or "").strip()
    created = launcher_bootstrap_service.create(face_session_id)
    payload["launcher_bootstrap_token"] = str(created.get("launcher_bootstrap_token") or "")
    payload["bootstrap_expires_in_seconds"] = int(created.get("expires_in_seconds") or 0)
    payload["face_session_id"] = ""
    if not created.get("created"):
        payload["status"] = "unavailable"
        payload["verified"] = False
        payload["allowed"] = False
        payload["reason"] = str(created.get("reason") or "launcher_bootstrap_unavailable")
    return payload


@app.post("/auth/launcher/create-bootstrap")
async def auth_launcher_create_bootstrap(request: LauncherBootstrapCreateRequest):
    # Deprecated startup path retained temporarily for compatibility with older callers.
    if face_identity_service is None or launcher_bootstrap_service is None:
        raise HTTPException(status_code=503, detail="Launcher bootstrap service is not initialized")
    if not face_identity_service.validate_session(request.face_session_id):
        return {
            "created": False,
            "reason": "invalid_face_session",
            "launcher_bootstrap_token": "",
            "expires_in_seconds": 0,
        }
    return launcher_bootstrap_service.create(request.face_session_id)


@app.post("/auth/launcher/exchange-bootstrap")
async def auth_launcher_exchange_bootstrap(request: LauncherBootstrapExchangeRequest):
    if launcher_bootstrap_service is None:
        raise HTTPException(status_code=503, detail="Launcher bootstrap service is not initialized")
    exchanged = launcher_bootstrap_service.exchange(request.bootstrap_token)
    if not exchanged.ok:
        return {
            "exchanged": False,
            "reason": exchanged.reason,
            "face_session_id": "",
        }
    return {
        "exchanged": True,
        "reason": exchanged.reason,
        "face_session_id": exchanged.face_session_id,
    }


@app.get("/face/status")
async def face_status():
    if face_identity_service is None:
        raise HTTPException(status_code=503, detail="Face identity service is not initialized")
    return face_identity_service.status()


@app.delete("/face/profile")
async def face_profile_delete():
    if face_identity_service is None:
        raise HTTPException(status_code=503, detail="Face identity service is not initialized")
    return face_identity_service.delete_profile()


@app.post("/auth/command-risk")
async def auth_command_risk(request: CommandRiskRequest):
    if command_risk_service is None:
        raise HTTPException(status_code=503, detail="Command risk service is not initialized")
    return command_risk_service.classify(request.command_text, command_action=request.command_action).as_dict()


@app.post("/auth/step-up/start")
async def auth_step_up_start(request: StepUpStartRequest):
    if step_up_auth_service is None:
        raise HTTPException(status_code=503, detail="Step-up auth service is not initialized")
    return step_up_auth_service.start(
        face_session_id=request.face_session_id,
        command_text=request.command_text,
        command_action=request.command_action,
    )


@app.post("/auth/step-up/verify")
async def auth_step_up_verify(request: StepUpVerifyRequest):
    if step_up_auth_service is None:
        raise HTTPException(status_code=503, detail="Step-up auth service is not initialized")
    return step_up_auth_service.verify(
        challenge_id=request.challenge_id,
        face_session_id=request.face_session_id,
        command_text=request.command_text,
        command_action=request.command_action,
        frames=request.frames,
        client_id=request.client_id,
    )


@app.post("/chat/interrupt")
async def chat_interrupt(request: Request):
    if interrupt_manager is None:
        raise HTTPException(status_code=503, detail="Interrupt manager is not initialized")
    t0 = time.perf_counter()
    payload = await request.json()
    session_id = str(payload.get("session_id") or "").strip()
    client_request_id = str(payload.get("client_request_id") or "").strip() or None
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")
    interrupted = interrupt_manager.interrupt(session_id, client_request_id)
    _warn_latency_budget("interrupt", int((time.perf_counter() - t0) * 1000), _INTERRUPT_WARN_MS)
    return {"status": "ok", "interrupted": interrupted}


@app.post("/wake-on-lan/test")
async def wake_on_lan_test(request: Request):
    _require_phone_bridge_token(request)
    if wake_on_lan_service is None:
        raise HTTPException(status_code=503, detail="Wake-on-LAN service is not initialized")
    result = wake_on_lan_service.wake_laptop()
    status = wake_on_lan_service.status()
    return {
        "configured": bool(status.get("configured")),
        "broadcast_ip": status.get("broadcast_ip", ""),
        "port": status.get("port", 0),
        **result,
    }


def _basic_phone_payload(
    phone_number: str,
    caller_name_hint: str = "",
    speak_result: bool = True,
    call_direction: str = "incoming",
    error: str = "",
) -> dict:
    direction = "outgoing" if (call_direction or "").strip().lower() == "outgoing" else "incoming"
    direction_label = "Outgoing call" if direction == "outgoing" else "Incoming call"
    display = (caller_name_hint or "").strip() or (phone_number or "").strip() or "Unknown number"
    summary = (
        f"{display} is calling you."
        if direction == "incoming" and caller_name_hint
        else f"Incoming call from {display}."
        if direction == "incoming"
        else f"You are calling {display}."
    )
    if error:
        summary = f"{summary} Caller lookup is unavailable right now: {error}"
    return {
        "event_id": f"local-{int(time.time() * 1000)}",
        "phone_number": phone_number,
        "normalized_number": re.sub(r"[^\d+]", "", phone_number or ""),
        "summary": summary,
        "call_direction": direction,
        "notification_title": f"{direction_label}: {display}",
        "notification_body": summary[:180],
        "speak_text": summary if speak_result else "",
        "public_data_only": True,
        "results": [],
        "source": "basic_fallback",
        "confidence": 0.25 if caller_name_hint else 0.1,
        "display_name": caller_name_hint or "",
        "carrier": "",
        "line_type": "",
        "country": "",
        "location": "",
        "spam_risk": "",
    }


@app.post("/agent", response_model=ChatResponse)
async def agent_chat(request: Request, chat_request: ChatRequest):
    """Compatibility endpoint used by the Android background voice service."""
    _require_phone_bridge_token(request)
    return await chat(chat_request)


@app.post("/phone/incoming-call")
async def phone_incoming_call(request: Request):
    _require_phone_bridge_token(request)
    if not phone_command_service:
        raise HTTPException(status_code=503, detail="Phone bridge service not initialized")

    payload = await request.json()
    phone_number = str(payload.get("phone_number") or "").strip()
    caller_name_hint = str(payload.get("caller_name_hint") or "").strip()
    device_id = str(payload.get("device_id") or "").strip()
    speak_result = bool(payload.get("speak_result", True))
    call_direction = str(payload.get("call_direction") or "incoming").strip().lower()

    if not phone_number:
        raise HTTPException(status_code=400, detail="phone_number is required")

    phone_command_service.note_device_seen(device_id)

    if not caller_lookup_service:
        return _basic_phone_payload(
            phone_number=phone_number,
            caller_name_hint=caller_name_hint,
            speak_result=speak_result,
            call_direction=call_direction,
            error="caller lookup service is not initialized",
        )

    try:
        return caller_lookup_service.build_incoming_call_payload(
            phone_number=phone_number,
            caller_name_hint=caller_name_hint,
            speak_result=speak_result,
            call_direction=call_direction,
        )
    except Exception as exc:
        logger.warning("[PHONE] Caller lookup failed, using basic announcement: %s", exc)
        return _basic_phone_payload(
            phone_number=phone_number,
            caller_name_hint=caller_name_hint,
            speak_result=speak_result,
            call_direction=call_direction,
            error=str(exc),
        )


@app.post("/phone/contacts/sync")
async def phone_contacts_sync(request: Request):
    _require_phone_bridge_token(request)
    if not phone_command_service:
        raise HTTPException(status_code=503, detail="Phone bridge service not initialized")

    payload = await request.json()
    device_id = str(payload.get("device_id") or "").strip()
    contacts = payload.get("contacts") or []
    if not isinstance(contacts, list):
        raise HTTPException(status_code=400, detail="contacts must be a list")
    if not hasattr(phone_command_service, "sync_contacts"):
        raise HTTPException(status_code=503, detail="Contact sync is unavailable")

    result = phone_command_service.sync_contacts(device_id=device_id, contacts=contacts)
    return {
        "status": "ok",
        "count": int(result.get("count", 0)),
        "device_id": device_id,
    }


@app.get("/phone/pending-actions")
async def phone_pending_actions(request: Request, device_id: str = "", phone_number: str = ""):
    _require_phone_bridge_token(request)
    if not phone_command_service:
        raise HTTPException(status_code=503, detail="Phone bridge service not initialized")

    phone_command_service.note_device_seen(device_id)
    return {
        "actions": phone_command_service.get_pending_actions(
            device_id=device_id,
            phone_number=phone_number,
        )
    }


@app.post("/phone/pending-actions/ack")
async def phone_pending_actions_ack(request: Request):
    _require_phone_bridge_token(request)
    if not phone_command_service:
        raise HTTPException(status_code=503, detail="Phone bridge service not initialized")

    payload = await request.json()
    action_id = str(payload.get("action_id") or "").strip()
    status = str(payload.get("status") or "completed").strip()
    device_id = str(payload.get("device_id") or "").strip()
    phone_number = str(payload.get("phone_number") or "").strip()

    if not action_id:
        raise HTTPException(status_code=400, detail="action_id is required")

    ok = phone_command_service.acknowledge_action(
        action_id=action_id,
        status=status,
        device_id=device_id or None,
        phone_number=phone_number or None,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Phone action not found")
    return {"status": "ok"}

@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):

    if not assistant_orchestrator:
        raise HTTPException(status_code=503, detail="Chat service not initialized")

    logger.info(
        "[API /chat] Incoming | session_id=%s | message_len=%d | message=%.100s",
        request.session_id or "new", len(request.message), request.message
    )

    try:
        session_id, response_text = assistant_orchestrator.handle_chat(
            AssistantRequest(
                message=request.message,
                session_id=request.session_id,
                imgbase64=request.imgbase64,
                input_source=request.input_source,
                voice_audio_base64=request.voice_audio_base64,
                face_session_id=request.face_session_id,
                step_up_token=request.step_up_token,
                client_request_id=request.client_request_id,
            ),
            mode="general",
        )

        logger.info(
            "[API /chat] Done | session_id=%s | response_len=%d",
            session_id[:12], len(response_text)
        )

        return ChatResponse(response=response_text, session_id=session_id)

    except ValueError as e:
        logger.warning("[API /chat] Invalid session_id: %s", e)
        raise HTTPException(status_code=400, detail=str(e))

    except AllGroqApisFailedError as e:
        logger.error("[API /chat] All Groq APIs failed: %s", e)
        raise HTTPException(status_code=503, detail=str(e))

    except Exception as e:
        if _is_rate_limit_error(e):
            logger.warning("[API /chat] Rate limit hit: %s", e)
            raise HTTPException(status_code=429, detail=RATE_LIMIT_MESSAGE)

        logger.error("[API /chat] Error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error processing chat: {str(e)}")


_SPLIT_RE = re.compile(r"(?<=[.!?;:])\s+")
_MIN_WORDS_FIRST = 1
_MIN_WORDS = 1
_MERGE_IF_WORDS = 2
_TTS_BUFFER_TIMEOUT = 0.6
_TTS_BUFFER_MIN_WORDS = 4

_ABBREV_HOLD_RE = re.compile(
    r"^(?:Dr|Mr|Mrs|Ms|Prof|Sr|Jr|St|Vs|Etc)\.$",
    re.IGNORECASE
)

def _should_hold_sentence_for_continuation(sent: str) -> bool:
    t = sent.strip()

    if not t.endswith("."):
        return False

    words = t.split()

    if len(words) != 1:
        return False

    return bool(_ABBREV_HOLD_RE.match(words[0]))

def _split_sentences(buf: str):
    parts = _SPLIT_RE.split(buf)

    if len(parts) <= 1:
        return [], buf

    raw = [p.strip() for p in parts[:-1] if p.strip()]
    sentences, pending = [], ""

    for s in raw:
        if pending:
            s = (pending + " " + s).strip()
            pending = ""

        min_req = _MIN_WORDS_FIRST if not sentences else _MIN_WORDS

        if len(s.split()) < min_req:
            pending = s
            continue

        sentences.append(s)

    remaining = (pending + " " + parts[-1].strip()).strip() if pending else parts[-1].strip()

    return sentences, remaining

def _merge_short(sentences):
    if not sentences:
        return []

    merged, i = [], 0

    while i < len(sentences):
        cur = sentences[i]
        j = i + 1

        while j < len(sentences) and len(sentences[j].split()) <= _MERGE_IF_WORDS:
            cur = (cur + " " + sentences[j]).strip()
            j += 1

        merged.append(cur)
        i = j

    return merged


def _validate_edge_tts_rate(value: str) -> str:
    return value if re.fullmatch(r"[+-]?\d+%", str(value or "").strip()) else "+20%"


def _validate_edge_tts_volume(value: str) -> str:
    return value if re.fullmatch(r"[+-]?\d+%", str(value or "").strip()) else "+0%"


def _validate_edge_tts_pitch(value: str) -> str:
    return value if re.fullmatch(r"[+-]?\d+Hz", str(value or "").strip(), re.IGNORECASE) else "+0Hz"


def _tts_runtime_config() -> dict[str, object]:
    interrupt_policy = str(TTS_INTERRUPT_POLICY or "stop_previous").strip().lower()
    if interrupt_policy not in {"stop_previous", "reject_new"}:
        interrupt_policy = "stop_previous"
    return {
        "provider": "edge_tts" if str(TTS_PROVIDER or "").strip().lower() == "edge_tts" else "edge_tts",
        "voice": str(EDGE_TTS_VOICE or TTS_VOICE or "en-GB-RyanNeural").strip() or "en-GB-RyanNeural",
        "rate": _validate_edge_tts_rate(EDGE_TTS_RATE or TTS_RATE),
        "fast_rate": _validate_edge_tts_rate(EDGE_TTS_FAST_RATE),
        "volume": _validate_edge_tts_volume(EDGE_TTS_VOLUME),
        "pitch": _validate_edge_tts_pitch(EDGE_TTS_PITCH),
        "punctuation_pause_mode": str(EDGE_TTS_PUNCTUATION_PAUSE_MODE or "natural").strip().lower() or "natural",
        "enable_ssml_pauses": bool(EDGE_TTS_ENABLE_SSML_PAUSES),
        "max_sentence_chars": max(80, int(EDGE_TTS_MAX_SENTENCE_CHARS or 240)),
        "normalize_dates": bool(EDGE_TTS_NORMALIZE_DATES),
        "normalize_numbers": bool(EDGE_TTS_NORMALIZE_NUMBERS),
        "debug_text": bool(EDGE_TTS_DEBUG_TEXT),
        "no_overlap": bool(TTS_NO_OVERLAP),
        "interrupt_policy": interrupt_policy,
        "thinking_audio": _thinking_audio_runtime_config(),
    }


def _thinking_audio_runtime_config() -> dict[str, object]:
    phrases = [item.strip() for item in str(THINKING_AUDIO_PHRASES or "").split("|") if item.strip()]
    if not phrases:
        phrases = ["On it.", "Sure.", "Got it.", "Okay.", "One moment."]
    return {
        "enabled": bool(THINKING_AUDIO_ENABLED),
        "provider": "edge_tts" if str(THINKING_AUDIO_PROVIDER or "").strip().lower() == "edge_tts" else "edge_tts",
        "phrases": phrases,
        "randomize": bool(THINKING_AUDIO_RANDOMIZE),
        "avoid_repeat": bool(THINKING_AUDIO_AVOID_REPEAT),
        "last_phrase_memory": bool(THINKING_AUDIO_LAST_PHRASE_MEMORY),
        "max_per_request": max(1, int(THINKING_AUDIO_MAX_PER_REQUEST or 1)),
        "max_seconds": max(0.2, float(THINKING_AUDIO_MAX_SECONDS or 2.0)),
        "rate": _validate_edge_tts_rate(THINKING_AUDIO_RATE),
        "volume": _validate_edge_tts_volume(THINKING_AUDIO_VOLUME),
        "finish_before_final_tts": bool(THINKING_AUDIO_FINISH_BEFORE_FINAL_TTS),
        "stop_on_final_tts": bool(THINKING_AUDIO_STOP_ON_FINAL_TTS),
        "final_tts_wait_timeout_ms": max(250, int(THINKING_AUDIO_FINAL_TTS_WAIT_TIMEOUT_MS or 2500)),
        "interruptible": bool(THINKING_AUDIO_INTERRUPTIBLE),
        "cache_enabled": bool(THINKING_AUDIO_CACHE_ENABLED),
        "debug": bool(THINKING_AUDIO_DEBUG),
    }


def _normalize_edge_tts_text(text: str, config: dict[str, object] | None = None) -> str:
    cfg = config or _tts_runtime_config()
    if str(cfg.get("punctuation_pause_mode") or "natural") != "natural":
        return str(text or "").strip()

    source = str(text or "").strip()
    if not source:
        return source

    protected: list[str] = []

    def protect(match: re.Match[str]) -> str:
        protected.append(match.group(0))
        return f"__JARVIS_TTS_PROTECTED_{len(protected) - 1}__"

    # Keep tokens where punctuation is semantic, not a pause cue.
    patterns = [
        r"https?://\S+|www\.\S+",
        r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b",
        r"\b[A-Za-z]:\\[^\s]+",
        r"\b[\w.-]+[/\\][^\s]+",
        r"\b[\w-]+\.[A-Za-z0-9]{1,8}\b",
        r"\bv?\d+(?:\.\d+){1,}\b",
        r"\b\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?\b",
        r"\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b",
        r"\b(?:Mr|Mrs|Ms|Dr|Prof|Sr|Jr|St)\.\b",
        r"\b(?:e\.g|i\.e|etc)\.\b",
    ]
    for pattern in patterns:
        source = re.sub(pattern, protect, source, flags=re.IGNORECASE)

    if bool(cfg.get("normalize_dates", True)):
        months = r"January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
        source = re.sub(rf"\b(\d{{1,2}}(?:st|nd|rd|th)?),\s+({months})\b", r"\1 \2", source, flags=re.IGNORECASE)
        source = re.sub(rf"\b({months})\s+(\d{{1,2}}(?:st|nd|rd|th)?),\s+(\d{{4}})\b", r"\1 \2 \3", source, flags=re.IGNORECASE)

    if bool(cfg.get("normalize_numbers", True)):
        source = re.sub(r"(?<=\d),(?=\d{3}\b)", "", source)

    # Keep commas inside casual clauses, but avoid comma-as-hard-pause around short date fragments.
    source = re.sub(r"\s+", " ", source).strip()

    for idx, token in enumerate(protected):
        source = source.replace(f"__JARVIS_TTS_PROTECTED_{idx}__", token)

    return source


def _stt_provider_cache_enabled() -> bool:
    section = ConfigLoader().get_section("stt")
    return _stt_runtime_bool(section, "STT_PROVIDER_CACHE_ENABLED", "provider_cache_enabled", bool(STT_PROVIDER_CACHE_ENABLED))


def _stt_preload_enabled() -> bool:
    section = ConfigLoader().get_section("stt")
    return _stt_runtime_bool(section, "PARAKEET_PRELOAD_ON_STARTUP", "parakeet_preload_on_startup", bool(PARAKEET_PRELOAD_ON_STARTUP))


def _stt_warmup_on_startup_enabled() -> bool:
    section = ConfigLoader().get_section("stt")
    return _stt_runtime_bool(section, "STT_WARMUP_ON_STARTUP", "warmup_on_startup", bool(STT_WARMUP_ON_STARTUP))


def _stt_fail_fast_on_warmup_error_enabled() -> bool:
    section = ConfigLoader().get_section("stt")
    return _stt_runtime_bool(section, "STT_FAIL_FAST_ON_WARMUP_ERROR", "fail_fast_on_warmup_error", bool(STT_FAIL_FAST_ON_WARMUP_ERROR))


def _get_stt_tool(app_instance=None, *, force_rebuild: bool = False) -> tuple[STTTool, dict[str, object]]:
    target_app = app_instance or app
    cache_enabled = _stt_provider_cache_enabled()
    started = time.perf_counter()
    if cache_enabled and not force_rebuild:
        cached = getattr(target_app.state, "stt_tool", None)
        if cached is not None:
            return cached, {
                "provider_build_ms": 0,
                "provider_reused": True,
                "cache_enabled": True,
            }

    tool = STTTool()
    provider_build_ms = max(0, int((time.perf_counter() - started) * 1000))
    if cache_enabled and not force_rebuild:
        target_app.state.stt_tool = tool
        target_app.state.stt_provider = getattr(tool, "provider", None)
    return tool, {
        "provider_build_ms": provider_build_ms,
        "provider_reused": False,
        "cache_enabled": cache_enabled,
    }


def _stt_cached_provider(app_instance=None):
    target_app = app_instance or app
    provider = getattr(target_app.state, "stt_provider", None)
    if provider is not None:
        return provider
    tool = getattr(target_app.state, "stt_tool", None)
    return getattr(tool, "provider", None) if tool is not None else None


def _stt_model_loaded(provider) -> bool:
    if provider is None:
        return False
    value = getattr(provider, "model_loaded", None)
    if isinstance(value, bool):
        return value
    return bool(getattr(provider, "_model", None) is not None)


def _warmup_stt_tool(app_instance=None) -> dict[str, object]:
    tool, cache_info = _get_stt_tool(app_instance)
    result = tool.execute(ToolContext(command="stt warmup", intent="warmup", payload={"action": "warmup"}))
    provider = getattr(tool, "provider", None)
    return {
        **dict(result or {}),
        **cache_info,
        "provider": (result or {}).get("provider") or getattr(provider, "provider_name", None),
        "model_loaded": bool((result or {}).get("model_loaded", _stt_model_loaded(provider))),
    }


def _run_startup_stt_warmup(app_instance=None) -> dict[str, object] | None:
    target_app = app_instance or app
    preload_enabled = _stt_preload_enabled()
    warmup_on_startup = _stt_warmup_on_startup_enabled()
    fail_fast = _stt_fail_fast_on_warmup_error_enabled()
    logger.info(
        "[STT] startup_warmup_config preload_enabled=%s warmup_on_startup=%s fail_fast=%s",
        str(preload_enabled).lower(),
        str(warmup_on_startup).lower(),
        str(fail_fast).lower(),
    )
    if not (preload_enabled or warmup_on_startup):
        target_app.state.stt_warmup_result = {
            "success": None,
            "skipped": True,
            "reason": "startup_warmup_disabled",
            "preload_enabled": preload_enabled,
            "warmup_on_startup": warmup_on_startup,
        }
        return None

    logger.info("[STT] startup_warmup model load start")
    try:
        warmup_result = _warmup_stt_tool(target_app)
    except Exception as exc:
        warmup_result = {
            "success": False,
            "action": "warmup",
            "error": "stt_warmup_failed",
            "message": f"Startup STT warmup failed: {exc}",
            "model_loaded": False,
            "cache_hit": False,
            "preload_enabled": preload_enabled,
            "warmup_on_startup": warmup_on_startup,
        }

    warmup_result = {
        **dict(warmup_result or {}),
        "preload_enabled": preload_enabled,
        "warmup_on_startup": warmup_on_startup,
    }
    target_app.state.stt_warmup_result = warmup_result
    if bool(warmup_result.get("success")):
        logger.info(
            "[STT] startup_warmup completed provider=%s model_loaded=%s model_load_ms=%s cache_hit=%s",
            warmup_result.get("provider"),
            bool(warmup_result.get("model_loaded")),
            warmup_result.get("model_load_ms"),
            bool(warmup_result.get("cache_hit")),
        )
    else:
        logger.warning(
            "[STT] startup_warmup failed error=%s message=%s",
            warmup_result.get("error"),
            warmup_result.get("message"),
        )
        if fail_fast:
            raise RuntimeError(str(warmup_result.get("message") or warmup_result.get("error") or "STT warmup failed"))
    return warmup_result


def _stt_capture_runtime_config() -> dict[str, object]:
    section = ConfigLoader().get_section("stt")
    mode = str(os.getenv("STT_CAPTURE_MODE", STT_CAPTURE_MODE) or "backend_parakeet").strip().lower()
    if mode not in {"backend_parakeet", "browser_legacy"}:
        mode = "backend_parakeet"
    readiness = stt_provider_readiness(config=section).as_dict()
    provider = _stt_cached_provider()
    warmup_result = getattr(app.state, "stt_warmup_result", None) or {}
    model = readiness.get("model") or os.getenv("PARAKEET_MODEL") or section.get("parakeet_model", "nvidia/parakeet-tdt-0.6b-v2")
    device = readiness.get("device") or os.getenv("PARAKEET_DEVICE") or section.get("parakeet_device", "cuda")
    return {
        "capture_mode": mode,
        "provider": readiness.get("provider_name"),
        "provider_name": readiness.get("provider_name"),
        "configured": bool(readiness.get("configured")),
        "available": bool(readiness.get("available")),
        "reason": readiness.get("reason"),
        "model": model,
        "device": device,
        "require_wav": _stt_runtime_bool(section, "PARAKEET_REQUIRE_WAV", "parakeet_require_wav", True),
        "ffmpeg_available": _ffmpeg_available(),
        "provider_cached": provider is not None,
        "model_loaded": _stt_model_loaded(provider),
        "preload_enabled": _stt_preload_enabled(),
        "warmup_on_startup": _stt_warmup_on_startup_enabled(),
        "warmup_success": warmup_result.get("success"),
        "warmup_error": warmup_result.get("error"),
        "warmup_reason": warmup_result.get("message") or warmup_result.get("reason"),
        "fail_fast_on_warmup_error": _stt_fail_fast_on_warmup_error_enabled(),
        "cache_enabled": _stt_provider_cache_enabled(),
        "domain_correction_enabled": _stt_runtime_bool(section, "STT_DOMAIN_CORRECTION_ENABLED", "parakeet_domain_correction_enabled", bool(STT_DOMAIN_CORRECTION_ENABLED)),
        "empty_transcript_behavior": str(os.getenv("STT_EMPTY_TRANSCRIPT_BEHAVIOR", "") or section.get("empty_transcript_behavior") or STT_EMPTY_TRANSCRIPT_BEHAVIOR),
        "empty_transcript_prompt": str(os.getenv("STT_EMPTY_TRANSCRIPT_PROMPT", "") or section.get("empty_transcript_prompt") or STT_EMPTY_TRANSCRIPT_PROMPT),
        "live_call_required": bool(readiness.get("live_call_required", False)),
        "preferred_local_provider": "nemo_parakeet",
        "min_record_seconds": STT_MIN_RECORD_SECONDS,
        "end_silence_seconds": STT_END_SILENCE_SECONDS,
        "max_record_seconds": STT_MAX_RECORD_SECONDS,
        "speech_padding_ms": STT_SPEECH_PADDING_MS,
    }


def _stt_runtime_bool(config: dict[str, object], env_name: str, key: str, default: bool) -> bool:
    raw_env = str(os.getenv(env_name, "")).strip().lower()
    if raw_env:
        return raw_env in {"1", "true", "yes", "on"}
    raw_value = config.get(key, default)
    if isinstance(raw_value, bool):
        return raw_value
    return str(raw_value).strip().lower() in {"1", "true", "yes", "on"}


def _audio_suffix_from_name(filename: str, content_type: str = "") -> str:
    lower_name = str(filename or "").strip().lower()
    if lower_name.endswith(".wav"):
        return ".wav"
    if lower_name.endswith(".webm"):
        return ".webm"
    if lower_name.endswith(".m4a"):
        return ".m4a"
    if "wav" in str(content_type or "").lower():
        return ".wav"
    if "webm" in str(content_type or "").lower():
        return ".webm"
    if "mp4" in str(content_type or "").lower() or "m4a" in str(content_type or "").lower():
        return ".m4a"
    return ""


def _ffmpeg_available() -> bool:
    return bool(shutil.which("ffmpeg"))


def _maybe_convert_audio_to_wav(audio_bytes: bytes, filename: str, content_type: str) -> tuple[bytes, str] | tuple[None, None]:
    suffix = _audio_suffix_from_name(filename, content_type)
    if suffix == ".wav":
        return bytes(audio_bytes), filename or "audio.wav"
    if not _ffmpeg_available():
        return None, None

    src_path = None
    dst_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix or ".audio") as src:
            src_path = Path(src.name)
            src.write(bytes(audio_bytes))
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as dst:
            dst_path = Path(dst.name)
        command = [
            "ffmpeg",
            "-y",
            "-i",
            str(src_path),
            "-ar",
            "16000",
            "-ac",
            "1",
            str(dst_path),
        ]
        subprocess.run(command, check=True, capture_output=True, timeout=20)
        return dst_path.read_bytes(), f"{Path(filename or 'audio').stem}.wav"
    except Exception:
        return None, None
    finally:
        for candidate in (src_path, dst_path):
            if candidate is not None:
                try:
                    candidate.unlink(missing_ok=True)
                except Exception:
                    pass


def _generate_tts_sync(text: str, voice: str, rate: str, volume: str, pitch: str) -> bytes:

    async def _inner():
        return await _edge_tts_bytes(text, voice=voice, rate=rate, volume=volume, pitch=pitch)

    return asyncio.run(_inner())


_tts_pool = ThreadPoolExecutor(max_workers=4)
_stream_poll_pool = ThreadPoolExecutor(max_workers=2)
_tts_request_lock = threading.Lock()
_tts_request_generation = 0
_thinking_tts_cache: dict[tuple[str, str, str, str, str], bytes] = {}
_thinking_phrase_lock = threading.Lock()
_last_thinking_phrase: str | None = None
_THINKING_START_DELAY_SECONDS = 0.4
_ROUTING_WARN_MS = 20
_ACK_WARN_MS = 100
_INTERRUPT_WARN_MS = 150
_FIRST_TOKEN_WARN_MS = 700


def _select_thinking_phrase(
    phrases: list[str],
    *,
    randomize: bool = True,
    avoid_repeat: bool = True,
    last_phrase_memory: bool = True,
) -> str:
    global _last_thinking_phrase
    cleaned = [str(item).strip() for item in phrases if str(item).strip()]
    if not cleaned:
        raise ValueError("empty_thinking_phrases")
    with _thinking_phrase_lock:
        if randomize:
            candidates = cleaned
            if avoid_repeat and _last_thinking_phrase and len(cleaned) > 1:
                non_repeating = [item for item in cleaned if item != _last_thinking_phrase]
                if non_repeating:
                    candidates = non_repeating
            phrase = random.choice(candidates)
        else:
            phrase = cleaned[0]
        if last_phrase_memory:
            _last_thinking_phrase = phrase
        return phrase


def _warn_latency_budget(label: str, elapsed_ms: int | float | None, budget_ms: int) -> None:
    if elapsed_ms is None:
        return
    if float(elapsed_ms) > budget_ms:
        logger.warning("[LATENCY] %s exceeded budget: %sms > %sms", label, int(elapsed_ms), budget_ms)


async def _edge_tts_bytes(text: str, *, voice: str, rate: str, volume: str, pitch: str, config: dict[str, object] | None = None) -> bytes:
    normalized_text = _normalize_edge_tts_text(text, config or _tts_runtime_config())
    communicate = edge_tts.Communicate(
        text=normalized_text,
        voice=voice,
        rate=rate,
        volume=volume,
        pitch=pitch,
    )
    parts = []
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            parts.append(chunk["data"])
    return b"".join(parts)

def _stream_generator(
    session_id: str,
    chunk_iter,
    is_realtime: bool,
    tts_enabled: bool = False,
    interrupt_token=None,
    metrics: LatencyTracker = None,
):
    request_id = getattr(interrupt_token, "client_request_id", None)
    generation_id = request_id

    buffer = ""
    held = None
    is_first = True
    audio_queue = []
    last_submit_time = time.perf_counter()
    first_audio_marked = False
    thinking_active = False

    def _cancelled() -> bool:
        return bool(interrupt_token is not None and getattr(interrupt_token, "cancelled", False))

    def _event(payload: dict) -> str:
        event_payload = dict(payload)
        event_payload["client_request_id"] = request_id
        if "audio" in event_payload:
            event_payload["generation_id"] = generation_id
        return f"data: {json.dumps(event_payload)}\n\n"

    yield _event({"session_id": session_id, "chunk": "", "done": False})

    def _submit(text):
        nonlocal last_submit_time

        if _cancelled() or not text or not text.strip():
            return

        tts_config = _tts_runtime_config()
        audio_queue.append(
            (
                _tts_pool.submit(
                    _generate_tts_sync,
                    text,
                    str(tts_config["voice"]),
                    str(tts_config["rate"]),
                    str(tts_config["volume"]),
                    str(tts_config["pitch"]),
                ),
                text,
            )
        )
        last_submit_time = time.perf_counter()

    def _drain_ready():
        nonlocal first_audio_marked, thinking_active
        events = []

        while audio_queue and audio_queue[0][0].done():
            fut, sent = audio_queue.pop(0)

            try:
                audio = fut.result()
                b64 = base64.b64encode(audio).decode("ascii")
                if metrics and not first_audio_marked:
                    first_audio_marked = True
                    elapsed = metrics.mark_once("first_audio")
                    metrics.set("first_audio_ms", elapsed)
                    if thinking_active:
                        thinking_active = False
                        events.append(_event({"activity": {"event": "thinking", "state": "stop"}}))
                    events.append(_event({"metrics": metrics.snapshot()}))
                events.append(_event({"audio": b64, "sentence": sent}))
            except Exception as exc:
                logger.warning("[TTS-INLINE] Failed for '%s': %s", sent[:40], exc)

        return events
    
    def _yield_completed_audio():
        if not tts_enabled:
            return

        for ev in _drain_ready():
            yield ev


    try:
        for chunk in chunk_iter:
            if _cancelled():
                for fut, _ in audio_queue:
                    fut.cancel()
                yield _event({"activity": {"event": "interrupted"}, "done": True})
                return

            if isinstance(chunk, dict):
                emitted = False
                if "activity" in chunk or "_activity" in chunk:
                    payload = chunk.get("activity", chunk.get("_activity"))
                    if payload.get("event") == "thinking":
                        thinking_active = payload.get("state") == "start"
                    elif payload.get("event") in {"interrupted", "tasks_completed"}:
                        thinking_active = False
                    yield _event({"activity": payload})
                    yield from _yield_completed_audio()
                    emitted = True
                    continue

                if "search_results" in chunk or "_search_results" in chunk:
                    payload = chunk.get("search_results", chunk.get("_search_results"))
                    yield _event({"search_results": payload})
                    yield from _yield_completed_audio()
                    emitted = True
                    continue

                if "actions" in chunk or "_actions" in chunk:
                    payload = chunk.get("actions", chunk.get("_actions"))
                    yield _event({"actions": payload})
                    yield from _yield_completed_audio()
                    emitted = True
                    continue

                if "background_tasks" in chunk or "_background_tasks" in chunk:
                    payload = chunk.get("background_tasks", chunk.get("_background_tasks"))
                    yield _event({"background_tasks": payload})
                    yield from _yield_completed_audio()
                    emitted = True
                    continue

                for key in ("ack", "metrics"):
                    if key in chunk:
                        yield _event({key: chunk[key]})
                        yield from _yield_completed_audio()
                        emitted = True
                        break

                if emitted:
                    continue

                logger.warning("[STREAM] Ignoring unexpected dict chunk keys: %s", list(chunk.keys()))
                yield from _yield_completed_audio()
                continue

            if not chunk:
                yield from _yield_completed_audio()
                continue

            yield _event({"chunk": chunk, "done": False})

            if not tts_enabled:
                continue

            yield from _yield_completed_audio()

            buffer += chunk
            sentences, buffer = _split_sentences(buffer)
            sentences = _merge_short(sentences)

            if held and sentences and len(sentences[0].split()) <= _MERGE_IF_WORDS:
                held = (held + " " + sentences[0]).strip()
                sentences = sentences[1:]

            for i, sent in enumerate(sentences):
                min_w = _MIN_WORDS_FIRST if is_first else _MIN_WORDS
                if len(sent.split()) < min_w:
                    continue

                is_last = (i == len(sentences) - 1)

                if held:
                    _submit(held)
                    held = None
                    is_first = False

                if is_last and _should_hold_sentence_for_continuation(sent):
                    held = sent
                else:
                    _submit(sent)
                    is_first = False

            if buffer and len(buffer.split()) >= _TTS_BUFFER_MIN_WORDS:
                if time.perf_counter() - last_submit_time > _TTS_BUFFER_TIMEOUT:
                    if held:
                        _submit(held)
                        held = None
                        is_first = False

                    _submit(buffer.strip())
                    buffer = ""
                    is_first = False

            yield from _yield_completed_audio()

        if tts_enabled:
            remaining = buffer.strip()

            if held:
                if remaining and len(remaining.split()) <= _MERGE_IF_WORDS:
                    _submit((held + " " + remaining).strip())
                else:
                    _submit(held)
                    if remaining:
                        _submit(remaining)

            elif remaining:
                _submit(remaining)

            for fut, sent in audio_queue:
                if _cancelled():
                    fut.cancel()
                    continue
                try:
                    audio = fut.result(timeout=15)
                    b64 = base64.b64encode(audio).decode("ascii")
                    if metrics and not first_audio_marked:
                        first_audio_marked = True
                        elapsed = metrics.mark_once("first_audio")
                        metrics.set("first_audio_ms", elapsed)
                        if thinking_active:
                            thinking_active = False
                            yield _event({"activity": {"event": "thinking", "state": "stop"}})
                        yield _event({"metrics": metrics.snapshot()})
                    yield _event({"audio": b64, "sentence": sent})
                except FuturesTimeoutError:
                    logger.warning("[TTS-INLINE] Timeout for '%s' (15s)", (sent or "")[:40])
                except Exception as exc:
                    logger.warning("[TTS-INLINE] Failed for '%s': %s", (sent or "")[:40], exc)

        if thinking_active:
            yield _event({"activity": {"event": "thinking", "state": "stop"}})

        if metrics:
            yield _event({"metrics": metrics.snapshot(final=True)})

        yield _event({"chunk": "", "done": True, "session_id": session_id})
    except Exception as e:
        for fut, _ in audio_queue:
            fut.cancel()

        if thinking_active:
            yield _event({"activity": {"event": "thinking", "state": "stop"}})
        yield _event({"chunk": "", "done": True, "error": str(e)})
        return
    finally:
        if interrupt_manager and interrupt_token is not None:
            interrupt_manager.finish(interrupt_token)

@app.post("/chat/stream")
async def chat_stream(request: ChatRequest):

    if not assistant_orchestrator:
        raise HTTPException(status_code=503, detail="Chat service not initialized")

    logger.info(
        "[API /chat/stream] Incoming | session_id=%s | message_len=%d | message=%.100s",
        request.session_id or "new", len(request.message), request.message
    )

    try:
        session_id, chunk_iter = assistant_orchestrator.stream_chat(
            AssistantRequest(
                message=request.message,
                session_id=request.session_id,
                imgbase64=request.imgbase64,
                input_source=request.input_source,
                voice_audio_base64=request.voice_audio_base64,
                face_session_id=request.face_session_id,
                step_up_token=request.step_up_token,
                client_request_id=request.client_request_id,
            ),
            mode="general",
        )

        return StreamingResponse(
            _stream_generator(
                session_id,
                chunk_iter,
                is_realtime=False,
                tts_enabled=request.tts
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no"
            },
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    except AllGroqApisFailedError as e:
        raise HTTPException(status_code=503, detail=str(e))

    except Exception as e:
        if _is_rate_limit_error(e):
            raise HTTPException(status_code=429, detail=RATE_LIMIT_MESSAGE)

        logger.error("[API /chat/stream] Error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/chat/realtime", response_model=ChatResponse)
async def chat_realtime(request: ChatRequest):

    if not assistant_orchestrator:
        raise HTTPException(status_code=503, detail="Chat service not initialized")

    if not realtime_service:
        raise HTTPException(status_code=503, detail="Realtime service not initialized")

    logger.info(
        "[API /chat/realtime] Incoming | session_id=%s | message_len=%d | message=%.100s",
        request.session_id or "new", len(request.message), request.message
    )

    try:
        session_id, response_text = assistant_orchestrator.handle_chat(
            AssistantRequest(
                message=request.message,
                session_id=request.session_id,
                imgbase64=request.imgbase64,
                input_source=request.input_source,
                voice_audio_base64=request.voice_audio_base64,
                face_session_id=request.face_session_id,
                step_up_token=request.step_up_token,
                client_request_id=request.client_request_id,
            ),
            mode="realtime",
        )

        logger.info(
            "[API /chat/realtime] Done | session_id=%s | response_len=%d",
            session_id[:12], len(response_text)
        )

        return ChatResponse(response=response_text, session_id=session_id)

    except ValueError as e:
        logger.warning("[API /chat/realtime] Invalid session_id: %s", e)
        raise HTTPException(status_code=400, detail=str(e))

    except AllGroqApisFailedError as e:
        logger.error("[API /chat/realtime] All Groq APIs failed: %s", e)
        raise HTTPException(status_code=503, detail=str(e))

    except Exception as e:
        if _is_rate_limit_error(e):
            logger.warning("[API /chat/realtime] Rate limit hit: %s", e)
            raise HTTPException(status_code=429, detail=RATE_LIMIT_MESSAGE)

        logger.error("[API /chat/realtime] Error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error processing chat: {str(e)}")

@app.post("/chat/realtime/stream")
async def chat_realtime_stream(request: ChatRequest):

    if not assistant_orchestrator or not realtime_service:
        raise HTTPException(status_code=503, detail="Service not initialized")

    logger.info(
        "[API /chat/realtime/stream] Incoming | session_id=%s | message_len=%d | message=%.100s",
        request.session_id or "new", len(request.message), request.message
    )

    try:
        session_id, chunk_iter = assistant_orchestrator.stream_chat(
            AssistantRequest(
                message=request.message,
                session_id=request.session_id,
                imgbase64=request.imgbase64,
                input_source=request.input_source,
                voice_audio_base64=request.voice_audio_base64,
                face_session_id=request.face_session_id,
                step_up_token=request.step_up_token,
                client_request_id=request.client_request_id,
            ),
            mode="realtime",
        )

        return StreamingResponse(
            _stream_generator(
                session_id,
                chunk_iter,
                is_realtime=True,
                tts_enabled=request.tts
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no"
            },
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    except AllGroqApisFailedError as e:
        raise HTTPException(status_code=503, detail=str(e))

    except Exception as e:
        if _is_rate_limit_error(e):
            raise HTTPException(status_code=429, detail=RATE_LIMIT_MESSAGE)

        logger.error("[API /chat/realtime/stream] Error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


def _safe_input_source(value: str) -> str:
    return "voice" if (value or "").strip().lower() == "voice" else "text"


def _metrics_event(metrics: LatencyTracker) -> dict:
    return {"metrics": metrics.snapshot()}


def _record_fast_response(session_id: str, user_message: str, response_text: str) -> None:
    if assistant_orchestrator:
        assistant_orchestrator.record_fast_response(session_id, user_message, response_text)
        return
    chat_service.add_message(session_id, "user", user_message)
    chat_service.add_message(session_id, "assistant", response_text)
    chat_service.save_chat_session(session_id)


def _task_actions_from_response(response: TaskResponse) -> dict:
    return {
        "wopens": response.wopens,
        "plays": response.plays,
        "images": [],
        "contents": [],
        "googlesearches": response.googlesearches,
        "youtubesearches": response.youtubesearches,
        "cam": response.cam,
    }


def _execute_fast_route(session_id: str, request: ChatRequest, route) -> tuple[str, dict | None]:
    if assistant_orchestrator:
        return assistant_orchestrator.execute_fast_route(
            session_id,
            AssistantRequest(
                message=request.message,
                session_id=session_id,
                imgbase64=request.imgbase64,
                input_source=request.input_source,
                voice_audio_base64=request.voice_audio_base64,
                face_session_id=request.face_session_id,
                step_up_token=request.step_up_token,
                client_request_id=request.client_request_id,
            ),
            route,
        )
    return "Done.", None


def _normalize_confirmation_text(message: str) -> str:
    return " ".join((message or "").strip().lower().split()).strip(" .!?")


def _get_pending_command_confirmation(session_id: str):
    pending = _pending_command_confirmations.get(session_id)
    if not pending:
        return None
    if time.time() - float(pending.get("created_at", 0)) > 45:
        _pending_command_confirmations.pop(session_id, None)
        return None
    return pending


def _has_frontend_actions(actions) -> bool:
    if isinstance(actions, list):
        return bool(actions)
    if isinstance(actions, dict):
        return bool(
            actions.get(key)
            for key in ("wopens", "plays", "googlesearches", "youtubesearches", "images", "contents", "cam", "open_url", "open_content", "open_image", "play_media", "download_file")
        ) or bool(actions.get("auth"))
    return False


def _jarvis_realtime_pipeline(session_id: str, request: ChatRequest, interrupt_token, metrics: LatencyTracker):
    thinking_started = False
    thinking_stopped = False
    first_output_marked = False

    def thinking_stop():
        nonlocal thinking_stopped
        if thinking_started and not thinking_stopped:
            thinking_stopped = True
            return {"activity": {"event": "thinking", "state": "stop"}}
        return None

    def emit_ack(text: str):
        elapsed = metrics.mark("ack_elapsed_ms")
        _warn_latency_budget("ack", elapsed, _ACK_WARN_MS)
        return {
            "ack": {
                "text": text,
                "intent": route.intent,
                "confidence": route.confidence,
            }
        }

    try:
        if interrupt_token.cancelled:
            yield {"activity": {"event": "interrupted"}}
            return

        metrics.mark_once("processing_start")

        confirmation_text = _normalize_confirmation_text(request.message)
        pending_confirmation = _get_pending_command_confirmation(session_id)
        if pending_confirmation and confirmation_text in {"yes", "y", "continue", "go ahead", "confirm", "do it", "proceed"}:
            _pending_command_confirmations.pop(session_id, None)
            original_message = str(pending_confirmation.get("message") or "")
            route = pending_confirmation.get("route")
            confirmed_request = request.model_copy(update={"message": original_message})
            ack_text = "Confirmed..."
            metrics.mark("ack_elapsed_ms")
            yield {"ack": {"text": ack_text, "intent": getattr(route, "intent", "confirmed"), "confidence": getattr(route, "confidence", 1.0)}}
            yield {"activity": {"event": "routing", "route": getattr(route, "intent", "confirmed")}}
            yield {"activity": {"event": "tasks_executing", "message": ack_text}}
            text, actions = _execute_fast_route(session_id, confirmed_request, route)
            _record_fast_response(session_id, f"{request.message} (confirmed: {original_message})", text)
            yield {"activity": {"event": "tasks_completed", "message": text}}
            if _has_frontend_actions(actions):
                yield {"actions": actions}
            yield text
            return

        if pending_confirmation and confirmation_text in {"no", "n", "cancel", "stop", "do not", "don't", "dont", "never mind"}:
            _pending_command_confirmations.pop(session_id, None)
            text = "Cancelled."
            _record_fast_response(session_id, request.message, text)
            yield {"activity": {"event": "routing", "route": "confirmation"}}
            yield text
            return

        if automation_service and hasattr(automation_service, "_load_session_pending_state"):
            automation_service._load_session_pending_state(session_id)

        route = fast_intent_router_service.route(
            request.message,
            imgbase64=request.imgbase64,
        )
        metrics.set("fast_router_ms", route.elapsed_ms)
        _warn_latency_budget("routing", route.elapsed_ms, _ROUTING_WARN_MS)
        yield _metrics_event(metrics)

        ack_text = acknowledgement_service.build_ack(route, message=request.message)
        yield emit_ack(ack_text)
        yield _metrics_event(metrics)

        if route.type == "instant":
            metrics.mark("execution_dispatch_ms")
            yield {"activity": {"event": "query_detected", "message": request.message}}
            yield {"activity": {"event": "routing", "route": route.intent or "instant"}}
            yield {"activity": {"event": "tasks_executing", "message": ack_text}}
            if interrupt_token.cancelled:
                yield {"activity": {"event": "interrupted"}}
                return
            text, actions = _execute_fast_route(session_id, request, route)
            _record_fast_response(session_id, request.message, text)
            yield {"activity": {"event": "tasks_completed", "message": text}}
            if _has_frontend_actions(actions):
                yield {"actions": actions}
            yield text
            return

        nonlocal_thinking = acknowledgement_service.phrase_generator.next_phrase()
        stream_iter = iter(chat_service.process_jarvis_message_stream(
            session_id,
            request.message,
            imgbase64=request.imgbase64,
        ))

        stream_end = object()
        first_chunk_future = _stream_poll_pool.submit(lambda: next(stream_iter, stream_end))
        thinking_deadline = time.perf_counter() + _THINKING_START_DELAY_SECONDS

        while True:
            wait_timeout = 0.05 if thinking_started else max(0.0, thinking_deadline - time.perf_counter())
            wait_timeout = max(wait_timeout, 0.01)
            try:
                first_chunk = first_chunk_future.result(timeout=wait_timeout)
                break
            except FuturesTimeoutError:
                if interrupt_token.cancelled:
                    stop = thinking_stop()
                    if stop:
                        yield stop
                    yield {"activity": {"event": "interrupted"}}
                    return
                if not thinking_started and time.perf_counter() >= thinking_deadline:
                    metrics.mark("thinking_start_ms")
                    thinking_started = True
                    yield {"activity": {"event": "thinking", "state": "start", "message": nonlocal_thinking}}
                    yield _metrics_event(metrics)

        if first_chunk is stream_end:
            stop = thinking_stop()
            if stop:
                yield stop
            return

        def iter_chunks():
            yield first_chunk
            yield from stream_iter

        for chunk in iter_chunks():
            if interrupt_token.cancelled:
                stop = thinking_stop()
                if stop:
                    yield stop
                yield {"activity": {"event": "interrupted"}}
                return

            is_first_output = (
                not first_output_marked
                and (
                    (isinstance(chunk, str) and bool(chunk))
                    or (
                        isinstance(chunk, dict)
                        and chunk.get("activity", {}).get("event") in {"first_chunk", "tasks_completed"}
                    )
                )
            )
            if is_first_output:
                first_output_marked = True
                stop = thinking_stop()
                if stop:
                    yield stop
                if isinstance(chunk, str):
                    elapsed = metrics.mark_once("first_token")
                    metrics.set("first_chunk_ms", elapsed)
                    _warn_latency_budget("first_token", elapsed, _FIRST_TOKEN_WARN_MS)
                    yield _metrics_event(metrics)

            yield chunk

        stop = thinking_stop()
        if stop:
            yield stop

    finally:
        pass

@app.post("/chat/jarvis/stream")
async def chat_jarvis_stream(request: ChatRequest):

    if not chat_service:
        raise HTTPException(status_code=503, detail="Service not initialized")
    if not fast_intent_router_service or not acknowledgement_service or not interrupt_manager:
        raise HTTPException(status_code=503, detail="Realtime assistant services not initialized")

    logger.info(
        "[API /chat/jarvis/stream] Incoming | session_id=%s | message_len=%d | img=%s | message=%.100s",
        request.session_id or "new",
        len(request.message),
        "yes" if request.imgbase64 else "no",
        request.message
    )

    try:
        session_id = chat_service.get_or_create_session(request.session_id)
        metrics = LatencyTracker()
        metrics.mark("speech_end")
        token = interrupt_manager.start(session_id, request.client_request_id)

        chunk_iter = _jarvis_realtime_pipeline(
            session_id,
            request,
            token,
            metrics,
        )

        return StreamingResponse(
            _stream_generator(
                session_id,
                chunk_iter,
                is_realtime=True,
                tts_enabled=request.tts,
                interrupt_token=token,
                metrics=metrics,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no"
            },
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    except AllGroqApisFailedError as e:
        raise HTTPException(status_code=503, detail=str(e))

    except Exception as e:
        if _is_rate_limit_error(e):
            raise HTTPException(status_code=429, detail=RATE_LIMIT_MESSAGE)

        logger.error("[API /chat/jarvis/stream] Error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/tasks/{task_id}")
async def get_task_status(task_id: str):
    if not task_manager:
        raise HTTPException(status_code=503, detail="Task manager not initialized")

    if not task_id or len(task_id) > 32:
        raise HTTPException(status_code=400, detail="Invalid task_id")

    data = task_manager.get_serializable(task_id)

    if not data:
        raise HTTPException(status_code=404, detail="Task not found")

    return data


@app.get("/tasks/{task_id}/image")
async def get_task_image(task_id: str):
    if not task_manager:
        raise HTTPException(status_code=503, detail="Task manager not initialized")

    if not task_id or len(task_id) > 32:
        raise HTTPException(status_code=400, detail="Invalid task_id")

    entry = task_manager.get(task_id)

    if not entry:
        raise HTTPException(status_code=404, detail="Task not found")

    if entry.status != "completed" or not entry.image_bytes:
        raise HTTPException(status_code=404, detail="Image not ready")

    return Response(content=entry.image_bytes, media_type="image/png")

@app.get("/chat/history/{session_id}")
async def get_chat_history(session_id: str):
    if not chat_service:
        raise HTTPException(status_code=503, detail="Chat service not initialized")

    if not chat_service.validate_session_id(session_id):
        raise HTTPException(status_code=400, detail="Invalid session_id format")

    try:
        messages = chat_service.get_chat_history(session_id)
        return {
            "session_id": session_id,
            "messages": [
                {"role": msg.role, "content": msg.content}
                for msg in messages
            ]
        }

    except Exception as e:
        logger.error(f"Error retrieving history: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving history: {str(e)}"
        )


@app.post("/stt/transcribe")
async def stt_transcribe(request: Request):
    total_started = time.perf_counter()
    audio_bytes = await request.body()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="empty_audio")

    filename = str(request.headers.get("X-Audio-Filename") or "voice-command.wav").strip() or "voice-command.wav"
    content_type = str(request.headers.get("Content-Type") or "").strip().lower()
    suffix = _audio_suffix_from_name(filename, content_type)
    if not suffix:
        raise HTTPException(status_code=400, detail="unsupported_audio_format")

    normalized_audio = bytes(audio_bytes)
    normalized_filename = filename
    conversion_ms = 0
    ffmpeg_used = False
    if suffix != ".wav":
        conversion_started = time.perf_counter()
        converted_audio, converted_filename = _maybe_convert_audio_to_wav(audio_bytes, filename, content_type)
        conversion_ms = max(0, int((time.perf_counter() - conversion_started) * 1000))
        if converted_audio is None or not converted_filename:
            raise HTTPException(status_code=400, detail="unsupported_audio_format")
        normalized_audio = converted_audio
        normalized_filename = converted_filename
        ffmpeg_used = True

    tool, cache_info = _get_stt_tool(request.app)
    provider = getattr(tool, "provider", None)
    logger.info(
        "[STT] transcribe_start provider=%s model_loaded=%s cache_enabled=%s content_type=%s",
        getattr(provider, "provider_name", None) or type(provider).__name__,
        _stt_model_loaded(provider),
        bool(cache_info.get("cache_enabled")),
        content_type or "unknown",
    )

    result = tool.execute(
        ToolContext(
            command="backend stt transcription",
            intent="transcribe_audio_bytes",
            payload={
                "action": "transcribe_audio_bytes",
                "args": {
                    "audio": normalized_audio,
                    "filename": normalized_filename,
                },
            },
        )
    )
    total_ms = max(0, int((time.perf_counter() - total_started) * 1000))
    timing = {
        "provider_build_ms": int(cache_info.get("provider_build_ms") or 0),
        "model_load_ms": int(result.get("model_load_ms") or 0),
        "conversion_ms": conversion_ms,
        "transcription_ms": int(result.get("transcription_ms") or 0),
        "post_processing_ms": int(result.get("post_processing_ms") or 0),
        "total_ms": total_ms,
        "cache_hit": bool(result.get("cache_hit")),
        "provider_reused": bool(cache_info.get("provider_reused")),
        "model_loaded": bool(result.get("model_loaded", _stt_model_loaded(provider))),
        "audio_format": suffix.lstrip("."),
        "audio_duration": result.get("duration"),
        "ffmpeg_used": ffmpeg_used,
    }
    logger.info(
        "[STT] transcribe provider=%s cache_hit=%s model_loaded=%s conversion_ms=%s model_load_ms=%s transcription_ms=%s total_ms=%s",
        result.get("provider") or getattr(provider, "provider_name", None),
        timing["cache_hit"],
        timing["model_loaded"],
        timing["conversion_ms"],
        timing["model_load_ms"],
        timing["transcription_ms"],
        timing["total_ms"],
    )
    if not bool(result.get("success")):
        error = str(result.get("error") or "transcription_failed")
        if error in {"stt_provider_unavailable", "stt_dependency_missing", "cuda_unavailable"}:
            readiness = dict(result.get("provider_readiness") or {})
            if not readiness:
                readiness = _stt_capture_runtime_config()
            raise HTTPException(
                status_code=400,
                detail={
                    "error": error,
                    "provider_name": readiness.get("provider_name") or readiness.get("provider"),
                    "available": bool(readiness.get("available")),
                    "reason": readiness.get("reason") or error,
                    "capture_mode": _stt_capture_runtime_config().get("capture_mode"),
                    "provider_readiness": readiness,
                },
            )
        raise HTTPException(status_code=400, detail=error)
    return {
        "success": True,
        "text": str(result.get("text") or ""),
        "message": str(result.get("message") or ""),
        "original_text": result.get("original_text"),
        "corrected_text": result.get("corrected_text") or result.get("text"),
        "provider": result.get("provider"),
        "model": result.get("model"),
        "device": result.get("device"),
        "source": result.get("source"),
        "duration": result.get("duration"),
        "audio_duration": result.get("duration"),
        "segments": result.get("segments") or [],
        "timestamps": result.get("timestamps") or [],
        "raw_result_type": result.get("raw_result_type"),
        "corrections_applied": result.get("corrections_applied") or [],
        "domain_correction_used": bool(result.get("domain_correction_used", False)),
        **timing,
    }


@app.post("/stt/warmup")
async def stt_warmup(request: Request):
    result = _warmup_stt_tool(request.app)
    if not bool(result.get("success")):
        error = str(result.get("error") or "stt_warmup_failed")
        raise HTTPException(status_code=400, detail=error)
    return {
        "success": True,
        "provider": result.get("provider"),
        "model": result.get("model"),
        "device": result.get("device"),
        "model_loaded": bool(result.get("model_loaded")),
        "model_load_ms": int(result.get("model_load_ms") or 0),
        "cache_hit": bool(result.get("cache_hit")),
        "provider_reused": bool(result.get("provider_reused")),
        "provider_build_ms": int(result.get("provider_build_ms") or 0),
        "total_ms": int(result.get("total_ms") or 0),
    }


@app.post("/tts/thinking")
async def thinking_text_to_speech():
    tts_config = _tts_runtime_config()
    thinking_config = dict(tts_config.get("thinking_audio") or {})
    if not bool(thinking_config.get("enabled", True)):
        raise HTTPException(status_code=404, detail="thinking_audio_disabled")
    if str(thinking_config.get("provider") or "edge_tts") != "edge_tts":
        raise HTTPException(status_code=503, detail="tts_provider_unavailable")

    phrases = [str(item).strip() for item in thinking_config.get("phrases") or [] if str(item).strip()]
    if not phrases:
        raise HTTPException(status_code=400, detail="empty_text")
    phrase = _select_thinking_phrase(
        phrases,
        randomize=bool(thinking_config.get("randomize", True)),
        avoid_repeat=bool(thinking_config.get("avoid_repeat", True)),
        last_phrase_memory=bool(thinking_config.get("last_phrase_memory", True)),
    )
    voice = str(tts_config["voice"])
    rate = str(thinking_config.get("rate") or tts_config["rate"])
    volume = str(thinking_config.get("volume") or tts_config["volume"])
    pitch = str(tts_config["pitch"])
    cache_key = (phrase, voice, rate, volume, pitch)

    async def generate():
        try:
            if bool(thinking_config.get("cache_enabled", True)) and cache_key in _thinking_tts_cache:
                yield _thinking_tts_cache[cache_key]
                return
            audio = await _edge_tts_bytes(
                phrase,
                voice=voice,
                rate=rate,
                volume=volume,
                pitch=pitch,
                config=tts_config,
            )
            if bool(thinking_config.get("cache_enabled", True)):
                _thinking_tts_cache[cache_key] = audio
            if audio:
                yield audio
        except Exception as e:
            if bool(thinking_config.get("debug", False)):
                logger.warning("[TTS thinking] Error generating thinking audio: %s", e)

    return StreamingResponse(
        generate(),
        media_type="audio/mpeg",
        headers={
            "Cache-Control": "no-cache",
            "X-Jarvis-Thinking-Phrase": phrase,
        },
    )


@app.post("/tts")
async def text_to_speech(request: TTSRequest):
    text = request.text.strip()

    if not text:
        raise HTTPException(status_code=400, detail="Text is required")
    tts_config = _tts_runtime_config()
    if str(tts_config["provider"]) != "edge_tts":
        raise HTTPException(status_code=503, detail="tts_provider_unavailable")

    global _tts_request_generation
    with _tts_request_lock:
        if bool(tts_config["no_overlap"]) and _tts_request_generation > 0 and str(tts_config["interrupt_policy"]) == "reject_new":
            raise HTTPException(status_code=409, detail="speech_already_active")
        _tts_request_generation += 1
        generation = _tts_request_generation

    async def generate():
        global _tts_request_generation
        try:
            normalized_text = _normalize_edge_tts_text(text, tts_config)
            if bool(tts_config.get("debug_text")):
                logger.debug("[TTS] normalized text: %s", normalized_text)
            communicate = edge_tts.Communicate(
                text=normalized_text,
                voice=str(tts_config["voice"]),
                rate=str(tts_config["rate"]),
                volume=str(tts_config["volume"]),
                pitch=str(tts_config["pitch"]),
            )
            async for chunk in communicate.stream():
                if bool(tts_config["no_overlap"]) and str(tts_config["interrupt_policy"]) == "stop_previous" and generation != _tts_request_generation:
                    break
                if chunk["type"] == "audio":
                    yield chunk["data"]
        except Exception as e:
            logger.error("[TTS] Error generating speech: %s", e)
        finally:
            with _tts_request_lock:
                if generation == _tts_request_generation:
                    _tts_request_generation = 0

    return StreamingResponse(
        generate(),
        media_type="audio/mpeg",
        headers={"Cache-Control": "no-cache"},
    )


_frontend_dir = Path(__file__).resolve().parent.parent / "frontend"

if _frontend_dir.exists():
    app.mount("/app", NoCacheStaticFiles(directory=str(_frontend_dir), html=True), name="frontend")


def _launcher_asset_response(filename: str, media_type: str) -> FileResponse:
    path = _frontend_dir / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"{filename} not found")
    response = FileResponse(path, media_type=media_type)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.get("/launcher")
@app.get("/launcher/")
async def launcher_page():
    return _launcher_asset_response("launcher.html", "text/html; charset=utf-8")


@app.get("/launcher/launcher.css")
async def launcher_css():
    return _launcher_asset_response("launcher.css", "text/css; charset=utf-8")


@app.get("/launcher/launcher.js")
async def launcher_js():
    return _launcher_asset_response("launcher.js", "application/javascript; charset=utf-8")


@app.get("/enroll")
@app.get("/enroll/")
async def enroll_page():
    return _launcher_asset_response("enroll.html", "text/html; charset=utf-8")


@app.get("/enroll/enroll.css")
async def enroll_css():
    return _launcher_asset_response("enroll.css", "text/css; charset=utf-8")


@app.get("/enroll/enroll.js")
async def enroll_js():
    return _launcher_asset_response("enroll.js", "application/javascript; charset=utf-8")


@app.get("/favicon.ico")
async def favicon_redirect():
    return RedirectResponse(url="/app/favicon.svg", status_code=302)


@app.get("/")
async def root_redirect():
    return RedirectResponse(url="/launcher/", status_code=302)


def run():
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )


if __name__ == "__main__":
    run()
