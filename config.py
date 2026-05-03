
"""
CONFIGURATION MODULE
====================
PURPOSE:
  Central place for all J.A.R.V.I.S settings: API keys, paths, model names,
  and the Jarvis system prompt. Designed for single-user use: each person runs
  their own copy of this backend with their own .env and database/ folder.
WHAT THIS FILE DOES:
  - Loads environment variables from .env (so API keys stay out of code).
  - Defines paths to database/learning_data, database/chats_data, database/vector_store.
  - Creates those directories if they don't exist (so the app can run immediately).
  - Exposes GROQ_API_KEY, GROQ_MODEL, TAVILY_API_KEY for the LLM and search.
  - Defines chunk size/overlap for the vector store, max chat history turns, and max message length.
  - Holds the full system prompt that defines Jarvis's personality and formatting rules.
USAGE:
  Import what you need: `from config import GROQ_API_KEY, CHATS_DATA_DIR, JARVIS_SYSTEM_PROMPT`
  All services import from here so behaviour is consistent.
"""

import os
import logging
from pathlib import Path
from dotenv import load_dotenv

# -----------------------------------------------------------------------------
# LOGGING
# -----------------------------------------------------------------------------
# Used when we need to log warnings (e.g. failed to load a learning data file)
logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# ENVIRONMENT
# -----------------------------------------------------------------------------
# Load environment variables from .env file (if it exists).
# This keeps API keys and secrets out of the code and version control.
load_dotenv()


def _getenv_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid integer for %s=%r; using default %d", name, raw, default)
        return default


def _getenv_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("Invalid float for %s=%r; using default %s", name, raw, default)
        return default


def _getenv_csv(name: str, default: list[str]) -> list[str]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    values = [part.strip() for part in raw.split(",") if part.strip()]
    return values or default


# -----------------------------------------------------------------------------
# BASE PATH
# -----------------------------------------------------------------------------
# Points to the folder containing this file (the project root).
# All other paths (database, learning_data, etc.) are built from this.
BASE_DIR = Path(__file__).parent

# ============================================================================
# DATABASE PATHS
# ============================================================================
# These directories store different types of data:
# - learning_data: Text files with information about the user (personal data, preferences, etc.)
# - chats_data: JSON files containing past conversation history
# - vector_store: FAISS index files for fast similarity search

LEARNING_DATA_DIR = BASE_DIR / "database" / "learning_data"
CHATS_DATA_DIR = BASE_DIR / "database" / "chats_data"
VECTOR_STORE_DIR = BASE_DIR / "database" / "vector_store"
CAMERA_CAPTURES_DIR = BASE_DIR / "database" / "camera_captures"
REMINDERS_DATA_DIR = BASE_DIR / "database" / "reminders"
AGENT_TASKS_DIR = BASE_DIR / "database" / "agent_tasks"
PHONE_BRIDGE_DIR = BASE_DIR / "database" / "phone_bridge"
MEMORY_DATA_DIR = BASE_DIR / "database" / "memory"
PERMISSIONS_DATA_DIR = BASE_DIR / "database" / "permissions"
OBSERVABILITY_DATA_DIR = BASE_DIR / "database" / "observability"

# Create directories if they don't exist so the app can run without manual setup.
# parents=True creates parent folders; exist_ok=True avoids error if already present.
LEARNING_DATA_DIR.mkdir(parents=True, exist_ok=True)
CHATS_DATA_DIR.mkdir(parents=True, exist_ok=True)
VECTOR_STORE_DIR.mkdir(parents=True, exist_ok=True)
CAMERA_CAPTURES_DIR.mkdir(parents=True, exist_ok=True)
REMINDERS_DATA_DIR.mkdir(parents=True, exist_ok=True)
AGENT_TASKS_DIR.mkdir(parents=True, exist_ok=True)
PHONE_BRIDGE_DIR.mkdir(parents=True, exist_ok=True)
MEMORY_DATA_DIR.mkdir(parents=True, exist_ok=True)
PERMISSIONS_DATA_DIR.mkdir(parents=True, exist_ok=True)
OBSERVABILITY_DATA_DIR.mkdir(parents=True, exist_ok=True)

# ============================================================================
# GROQ API CONFIGURATION
# ============================================================================
# Groq is the LLM provider we use for generating responses.
# You can set one key (GROQ_API_KEY) or multiple keys for fallback:
#   GROQ_API_KEY, GROQ_API_KEY_2, GROQ_API_KEY_3, ... (no upper limit).
# PRIMARY-FIRST: Every request tries the first key first. If it fails (rate limit,
# timeout, etc.), the server tries the second, then third, until one succeeds.
# If all keys fail, the user receives a clear error message.
# Model determines which AI model to use (llama-3.3-70b-versatile is latest).

def _load_groq_api_keys() -> list:
    """
    Load all GROQ API keys from the environment.
    Reads GROQ_API_KEY first, then GROQ_API_KEY_2, GROQ_API_KEY_3, ... until
    a number has no value. There is no upper limit on how many keys you can set.
    Returns a list of non-empty key strings (may be empty if GROQ_API_KEY is not set).
    """
    keys = []
    # First key: GROQ_API_KEY (required in practice; validated when building services).
    first = os.getenv("GROQ_API_KEY", "").strip()
    if first:
        keys.append(first)
    # Additional keys: GROQ_API_KEY_2, GROQ_API_KEY_3, GROQ_API_KEY_4, ...
    i = 2
    while True:
        k = os.getenv(f"GROQ_API_KEY_{i}", "").strip()
        if not k:
            # No key for this number; stop (no more keys).
            break
        keys.append(k)
        i += 1
    return keys


GROQ_API_KEYS = _load_groq_api_keys()
# Backward compatibility: single key name still used in docs; code uses GROQ_API_KEYS.
GROQ_API_KEY = GROQ_API_KEYS[0] if GROQ_API_KEYS else ""
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

# ============================================================================
# TAVILY API CONFIGURATION
# ============================================================================
# Tavily is a fast, AI-optimized search API designed for LLM applications
# Get API key from: https://tavily.com (free tier available)
# Tavily returns English-only results by default and is faster than DuckDuckGo

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")

# ============================================================================
# BRAIN MODEL (Query Classification — Jarvis Mode)
# ============================================================================
# The brain classifies each query as "general" or "realtime" using Groq.
# Uses the same GROQ_API_KEYS with rotation (brain and chat never use the same key).
GROQ_BRAIN_MODEL = os.getenv("GROQ_BRAIN_MODEL", "llama-3.1-8b-instant")
INTENT_CLASSIFY_MODEL = os.getenv("INTENT_CLASSIFY_MODEL", GROQ_BRAIN_MODEL).strip() or GROQ_BRAIN_MODEL
VISION_MODEL = os.getenv("VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
GROQ_VISION_MODEL = os.getenv("GROQ_VISION_MODEL", VISION_MODEL).strip() or VISION_MODEL
VISION_MAX_IMAGE_BYTES = _getenv_int("VISION_MAX_IMAGE_BYTES", 8 * 1024 * 1024)

# ============================================================================
# TTS (TEXT-TO-SPEECH) CONFIGURATION
# ============================================================================
# edge-tts uses Microsoft Edge's free cloud TTS. No API key needed.
# Voice list: run `edge-tts --list-voices` to see all available voices.
# Default: en-GB-RyanNeural (male British voice, fitting for JARVIS).
# Override via EDGE_TTS_VOICE in .env (e.g. EDGE_TTS_VOICE=en-US-ChristopherNeural).

TTS_PROVIDER = os.getenv("TTS_PROVIDER", "edge_tts").strip().lower() or "edge_tts"
EDGE_TTS_VOICE = os.getenv("EDGE_TTS_VOICE", os.getenv("TTS_VOICE", "en-GB-RyanNeural")).strip() or "en-GB-RyanNeural"
EDGE_TTS_RATE = os.getenv("EDGE_TTS_RATE", os.getenv("TTS_RATE", "+20%")).strip() or "+20%"
EDGE_TTS_FAST_RATE = os.getenv("EDGE_TTS_FAST_RATE", "+22%").strip() or "+22%"
EDGE_TTS_VOLUME = os.getenv("EDGE_TTS_VOLUME", "+0%").strip() or "+0%"
EDGE_TTS_PITCH = os.getenv("EDGE_TTS_PITCH", "+0Hz").strip() or "+0Hz"
EDGE_TTS_PUNCTUATION_PAUSE_MODE = os.getenv("EDGE_TTS_PUNCTUATION_PAUSE_MODE", "natural").strip().lower() or "natural"
EDGE_TTS_ENABLE_SSML_PAUSES = os.getenv("EDGE_TTS_ENABLE_SSML_PAUSES", "false").strip().lower() in {"1", "true", "yes", "on"}
EDGE_TTS_MAX_SENTENCE_CHARS = _getenv_int("EDGE_TTS_MAX_SENTENCE_CHARS", 240)
EDGE_TTS_NORMALIZE_DATES = os.getenv("EDGE_TTS_NORMALIZE_DATES", "true").strip().lower() in {"1", "true", "yes", "on"}
EDGE_TTS_NORMALIZE_NUMBERS = os.getenv("EDGE_TTS_NORMALIZE_NUMBERS", "true").strip().lower() in {"1", "true", "yes", "on"}
EDGE_TTS_DEBUG_TEXT = os.getenv("EDGE_TTS_DEBUG_TEXT", "false").strip().lower() in {"1", "true", "yes", "on"}
TTS_NO_OVERLAP = os.getenv("TTS_NO_OVERLAP", "true").strip().lower() in {"1", "true", "yes", "on"}
TTS_INTERRUPT_POLICY = os.getenv("TTS_INTERRUPT_POLICY", "stop_previous").strip().lower() or "stop_previous"
THINKING_AUDIO_ENABLED = os.getenv("THINKING_AUDIO_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
THINKING_AUDIO_PROVIDER = os.getenv("THINKING_AUDIO_PROVIDER", "edge_tts").strip().lower() or "edge_tts"
THINKING_AUDIO_PHRASES = os.getenv("THINKING_AUDIO_PHRASES", "On it.|Sure.|Got it.|Okay.|One moment.|I'm on it.|Let me check.|Give me a second.|Alright.|Just a moment.").strip()
THINKING_AUDIO_RANDOMIZE = os.getenv("THINKING_AUDIO_RANDOMIZE", "true").strip().lower() in {"1", "true", "yes", "on"}
THINKING_AUDIO_AVOID_REPEAT = os.getenv("THINKING_AUDIO_AVOID_REPEAT", "true").strip().lower() in {"1", "true", "yes", "on"}
THINKING_AUDIO_LAST_PHRASE_MEMORY = os.getenv("THINKING_AUDIO_LAST_PHRASE_MEMORY", "true").strip().lower() in {"1", "true", "yes", "on"}
THINKING_AUDIO_MAX_PER_REQUEST = _getenv_int("THINKING_AUDIO_MAX_PER_REQUEST", 1)
THINKING_AUDIO_MAX_SECONDS = _getenv_float("THINKING_AUDIO_MAX_SECONDS", 2.0)
THINKING_AUDIO_RATE = os.getenv("THINKING_AUDIO_RATE", "+20%").strip() or "+20%"
THINKING_AUDIO_VOLUME = os.getenv("THINKING_AUDIO_VOLUME", "+0%").strip() or "+0%"
THINKING_AUDIO_FINISH_BEFORE_FINAL_TTS = os.getenv("THINKING_AUDIO_FINISH_BEFORE_FINAL_TTS", "true").strip().lower() in {"1", "true", "yes", "on"}
THINKING_AUDIO_STOP_ON_FINAL_TTS = os.getenv("THINKING_AUDIO_STOP_ON_FINAL_TTS", "false").strip().lower() in {"1", "true", "yes", "on"}
THINKING_AUDIO_FINAL_TTS_WAIT_TIMEOUT_MS = _getenv_int("THINKING_AUDIO_FINAL_TTS_WAIT_TIMEOUT_MS", 2500)
THINKING_AUDIO_INTERRUPTIBLE = os.getenv("THINKING_AUDIO_INTERRUPTIBLE", "true").strip().lower() in {"1", "true", "yes", "on"}
THINKING_AUDIO_CACHE_ENABLED = os.getenv("THINKING_AUDIO_CACHE_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
THINKING_AUDIO_DEBUG = os.getenv("THINKING_AUDIO_DEBUG", "false").strip().lower() in {"1", "true", "yes", "on"}
TTS_VOICE = EDGE_TTS_VOICE
TTS_RATE = EDGE_TTS_RATE

STT_MIN_RECORD_SECONDS = _getenv_float("STT_MIN_RECORD_SECONDS", 1.0)
STT_END_SILENCE_SECONDS = _getenv_float("STT_END_SILENCE_SECONDS", 1.5)
STT_MAX_RECORD_SECONDS = _getenv_float("STT_MAX_RECORD_SECONDS", 20.0)
STT_SPEECH_PADDING_MS = _getenv_int("STT_SPEECH_PADDING_MS", 300)
STT_CAPTURE_MODE = os.getenv("STT_CAPTURE_MODE", "backend_parakeet").strip().lower() or "backend_parakeet"
STT_PROVIDER_CACHE_ENABLED = os.getenv("STT_PROVIDER_CACHE_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
PARAKEET_PRELOAD_ON_STARTUP = os.getenv("PARAKEET_PRELOAD_ON_STARTUP", "true").strip().lower() in {"1", "true", "yes", "on"}
STT_WARMUP_ON_STARTUP = os.getenv("STT_WARMUP_ON_STARTUP", "true").strip().lower() in {"1", "true", "yes", "on"}
STT_FAIL_FAST_ON_WARMUP_ERROR = os.getenv("STT_FAIL_FAST_ON_WARMUP_ERROR", "false").strip().lower() in {"1", "true", "yes", "on"}
STT_DOMAIN_CORRECTION_ENABLED = os.getenv("STT_DOMAIN_CORRECTION_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
STT_DOMAIN_CORRECTIONS = os.getenv(
    "STT_DOMAIN_CORRECTIONS",
    "Jarris=Jarvis|Javi=Jarvis|Jaris=Jarvis|Javas=Jarvis|Jervis=Jarvis|Javier=Jarvis|Jawis=Jarvis|Jais=Jarvis|Jarwis=Jarvis|Jarvish=Jarvis",
).strip()
STT_DOMAIN_CORRECTION_CASE_SENSITIVE = os.getenv("STT_DOMAIN_CORRECTION_CASE_SENSITIVE", "false").strip().lower() in {"1", "true", "yes", "on"}
STT_DOMAIN_CORRECTION_WORD_BOUNDARY = os.getenv("STT_DOMAIN_CORRECTION_WORD_BOUNDARY", "true").strip().lower() in {"1", "true", "yes", "on"}
STT_EMPTY_TRANSCRIPT_BEHAVIOR = os.getenv("STT_EMPTY_TRANSCRIPT_BEHAVIOR", "short_prompt").strip().lower() or "short_prompt"
STT_EMPTY_TRANSCRIPT_PROMPT = os.getenv("STT_EMPTY_TRANSCRIPT_PROMPT", "I didn't catch that.").strip() or "I didn't catch that."
# Voice identity runtime:
# - nemo_titanet: production backend for centralized speaker verification
# - fingerprint: dependency-free local/test fallback
# - unavailable: fail-closed fallback when the backend is disabled
VOICE_IDENTITY_BACKEND = os.getenv("VOICE_IDENTITY_BACKEND", "nemo_titanet").strip().lower()
VOICE_IDENTITY_MODEL_SOURCE = (
    os.getenv("VOICE_IDENTITY_MODEL_SOURCE", "nvidia/speakerverification_en_titanet_large").strip()
    or "nvidia/speakerverification_en_titanet_large"
)
VOICE_IDENTITY_MODEL_LABEL = os.getenv("VOICE_IDENTITY_MODEL_LABEL", "titanet_large").strip() or "titanet_large"
VOICE_IDENTITY_DEVICE = os.getenv("VOICE_IDENTITY_DEVICE", "auto").strip().lower() or "auto"
VOICE_IDENTITY_ENROLL_REQUIRED_SAMPLES = _getenv_int("VOICE_IDENTITY_ENROLL_REQUIRED_SAMPLES", 3)
VOICE_IDENTITY_PREPROCESSING_VERSION = os.getenv(
    "VOICE_IDENTITY_PREPROCESSING_VERSION",
    "edge-rms-stable-window-v1",
).strip() or "edge-rms-stable-window-v1"
VOICE_IDENTITY_MIN_AUDIO_MS = _getenv_int("VOICE_IDENTITY_MIN_AUDIO_MS", 1200)
VOICE_IDENTITY_VERIFY_MIN_AUDIO_MS = _getenv_int("VOICE_IDENTITY_VERIFY_MIN_AUDIO_MS", 700)
VOICE_IDENTITY_TARGET_SPEECH_MS = _getenv_int("VOICE_IDENTITY_TARGET_SPEECH_MS", 3000)
VOICE_IDENTITY_MAX_AUDIO_MS = _getenv_int("VOICE_IDENTITY_MAX_AUDIO_MS", 6000)
VOICE_IDENTITY_TRIM_FRAME_MS = _getenv_int("VOICE_IDENTITY_TRIM_FRAME_MS", 25)
VOICE_IDENTITY_TRIM_HOP_MS = _getenv_int("VOICE_IDENTITY_TRIM_HOP_MS", 10)
VOICE_IDENTITY_TRIM_NOISE_MULTIPLIER = _getenv_float("VOICE_IDENTITY_TRIM_NOISE_MULTIPLIER", 2.2)
VOICE_IDENTITY_TRIM_MIN_THRESHOLD = _getenv_float("VOICE_IDENTITY_TRIM_MIN_THRESHOLD", 0.0015)
VOICE_IDENTITY_TRIM_SPEECH_CAP_RATIO = _getenv_float("VOICE_IDENTITY_TRIM_SPEECH_CAP_RATIO", 0.55)
VOICE_IDENTITY_TRIM_LEADING_PAD_MS = _getenv_int("VOICE_IDENTITY_TRIM_LEADING_PAD_MS", 200)
VOICE_IDENTITY_TRIM_TRAILING_PAD_MS = _getenv_int("VOICE_IDENTITY_TRIM_TRAILING_PAD_MS", 250)
VOICE_IDENTITY_TARGET_RMS = _getenv_float("VOICE_IDENTITY_TARGET_RMS", 0.08)
VOICE_IDENTITY_MAX_GAIN_DB = _getenv_float("VOICE_IDENTITY_MAX_GAIN_DB", 12.0)
VOICE_IDENTITY_MIN_GAIN_RMS = _getenv_float("VOICE_IDENTITY_MIN_GAIN_RMS", 0.001)
VOICE_IDENTITY_WINDOW_HOP_MS = _getenv_int("VOICE_IDENTITY_WINDOW_HOP_MS", 250)
VOICE_IDENTITY_WINDOW_MEDIAN_RMS_WEIGHT = _getenv_float("VOICE_IDENTITY_WINDOW_MEDIAN_RMS_WEIGHT", 0.55)
VOICE_IDENTITY_WINDOW_CONTINUITY_WEIGHT = _getenv_float("VOICE_IDENTITY_WINDOW_CONTINUITY_WEIGHT", 0.35)
VOICE_IDENTITY_WINDOW_CLIPPING_WEIGHT = _getenv_float("VOICE_IDENTITY_WINDOW_CLIPPING_WEIGHT", 1.2)
VOICE_IDENTITY_WINDOW_PEAK_WEIGHT = _getenv_float("VOICE_IDENTITY_WINDOW_PEAK_WEIGHT", 0.5)
VOICE_IDENTITY_WINDOW_SILENCE_WEIGHT = _getenv_float("VOICE_IDENTITY_WINDOW_SILENCE_WEIGHT", 0.25)
VOICE_IDENTITY_CLIPPING_THRESHOLD = _getenv_float("VOICE_IDENTITY_CLIPPING_THRESHOLD", 0.98)
VOICE_IDENTITY_PEAK_PENALTY_START = _getenv_float("VOICE_IDENTITY_PEAK_PENALTY_START", 0.90)
VOICE_IDENTITY_NORMAL_VERIFY_THRESHOLD = _getenv_float("VOICE_IDENTITY_NORMAL_VERIFY_THRESHOLD", 0.82)
VOICE_IDENTITY_NORMAL_UNCERTAIN_THRESHOLD = _getenv_float("VOICE_IDENTITY_NORMAL_UNCERTAIN_THRESHOLD", 0.72)
VOICE_IDENTITY_SENSITIVE_VERIFY_THRESHOLD = _getenv_float("VOICE_IDENTITY_SENSITIVE_VERIFY_THRESHOLD", 0.88)
VOICE_IDENTITY_SENSITIVE_UNCERTAIN_THRESHOLD = _getenv_float("VOICE_IDENTITY_SENSITIVE_UNCERTAIN_THRESHOLD", 0.80)
VOICE_IDENTITY_ENROLL_MATCH_THRESHOLD = _getenv_float(
    "VOICE_IDENTITY_ENROLL_MATCH_THRESHOLD",
    VOICE_IDENTITY_NORMAL_UNCERTAIN_THRESHOLD,
)

# ============================================================================
# FACE AUTHENTICATION + LIVENESS CONFIGURATION
# ============================================================================
FACE_GATE_ENABLED = os.getenv("FACE_GATE_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
FACE_GATE_SCOPE = os.getenv("FACE_GATE_SCOPE", "launcher_only").strip().lower() or "launcher_only"
FACE_IN_APP_RECOGNITION_ENABLED = os.getenv("FACE_IN_APP_RECOGNITION_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
FACE_STEP_UP_FOR_TOOLS_ENABLED = os.getenv("FACE_STEP_UP_FOR_TOOLS_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
FACE_STATUS_IN_APP_ENABLED = os.getenv("FACE_STATUS_IN_APP_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
FACE_VERIFY_IN_APP_ENABLED = os.getenv("FACE_VERIFY_IN_APP_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
FACE_IDENTITY_BACKEND = os.getenv("FACE_IDENTITY_BACKEND", "insightface").strip().lower() or "insightface"
FACE_RECOGNITION_MODEL_NAME = os.getenv("FACE_RECOGNITION_MODEL_NAME", "buffalo_l").strip() or "buffalo_l"
FACE_RECOGNITION_DET_SIZE = _getenv_int("FACE_RECOGNITION_DET_SIZE", 320)
FACE_IDENTITY_REQUIRED_SAMPLES = _getenv_int("FACE_IDENTITY_REQUIRED_SAMPLES", 20)
FACE_IDENTITY_PREFERRED_SAMPLES = _getenv_int("FACE_IDENTITY_PREFERRED_SAMPLES", 20)
FACE_IDENTITY_MAX_STORED_SAMPLES = _getenv_int("FACE_IDENTITY_MAX_STORED_SAMPLES", 25)
FACE_ENROLLMENT_BURST_FRAME_COUNT = _getenv_int("FACE_ENROLLMENT_BURST_FRAME_COUNT", 60)
FACE_ENROLLMENT_BURST_INTERVAL_MS = _getenv_int("FACE_ENROLLMENT_BURST_INTERVAL_MS", 100)
FACE_ENROLLMENT_BATCH_SIZE = _getenv_int("FACE_ENROLLMENT_BATCH_SIZE", 6)
FACE_ENROLLMENT_MAX_MODEL_FRAMES_PER_BATCH = _getenv_int("FACE_ENROLLMENT_MAX_MODEL_FRAMES_PER_BATCH", 3)
FACE_ENROLLMENT_FRAME_MAX_WIDTH = _getenv_int("FACE_ENROLLMENT_FRAME_MAX_WIDTH", 480)
FACE_ENROLLMENT_MIN_DIVERSITY_DISTANCE = _getenv_float("FACE_ENROLLMENT_MIN_DIVERSITY_DISTANCE", 0.01)
FACE_ENROLLMENT_MAX_CENTROID_DISTANCE = _getenv_float("FACE_ENROLLMENT_MAX_CENTROID_DISTANCE", 0.35)
FACE_ENROLLMENT_CONSISTENCY_MIN_SAMPLES = _getenv_int("FACE_ENROLLMENT_CONSISTENCY_MIN_SAMPLES", 6)
FACE_IDENTITY_EARLY_COMPLETE_MIN_SAMPLES = _getenv_int("FACE_IDENTITY_EARLY_COMPLETE_MIN_SAMPLES", FACE_IDENTITY_PREFERRED_SAMPLES)
FACE_IDENTITY_EARLY_COMPLETE_MEAN_COSINE = _getenv_float("FACE_IDENTITY_EARLY_COMPLETE_MEAN_COSINE", 0.985)
FACE_IDENTITY_VERIFIED_THRESHOLD = _getenv_float("FACE_IDENTITY_VERIFIED_THRESHOLD", 0.55)
FACE_IDENTITY_UNCERTAIN_THRESHOLD = _getenv_float("FACE_IDENTITY_UNCERTAIN_THRESHOLD", 0.45)
FACE_IDENTITY_MIN_FACE_CONFIDENCE = _getenv_float("FACE_IDENTITY_MIN_FACE_CONFIDENCE", 0.75)
FACE_IDENTITY_MIN_FACE_SIZE_PX = _getenv_int("FACE_IDENTITY_MIN_FACE_SIZE_PX", 96)
FACE_IDENTITY_MIN_BLUR_LAPLACIAN = _getenv_float("FACE_IDENTITY_MIN_BLUR_LAPLACIAN", 80.0)
FACE_IDENTITY_MIN_BRIGHTNESS = _getenv_float("FACE_IDENTITY_MIN_BRIGHTNESS", 45.0)
FACE_IDENTITY_MAX_BRIGHTNESS = _getenv_float("FACE_IDENTITY_MAX_BRIGHTNESS", 215.0)
FACE_AUTH_SESSION_TTL_SECONDS = _getenv_int("FACE_AUTH_SESSION_TTL_SECONDS", 900)

FACE_LIVENESS_ENABLED = os.getenv("FACE_LIVENESS_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
FACE_LIVENESS_FRAME_COUNT = _getenv_int("FACE_LIVENESS_FRAME_COUNT", 5)
FACE_LIVENESS_CAPTURE_INTERVAL_MS = _getenv_int("FACE_LIVENESS_CAPTURE_INTERVAL_MS", 150)
FACE_LIVENESS_MIN_CONFIDENCE = _getenv_float("FACE_LIVENESS_MIN_CONFIDENCE", 0.70)
FACE_LIVENESS_MIN_MOTION_PX = _getenv_float("FACE_LIVENESS_MIN_MOTION_PX", 2.0)
FACE_LIVENESS_MAX_MOTION_PX = _getenv_float("FACE_LIVENESS_MAX_MOTION_PX", 60.0)
FACE_LIVENESS_MIN_FACE_IOU = _getenv_float("FACE_LIVENESS_MIN_FACE_IOU", 0.60)
FACE_LIVENESS_IDENTICAL_FRAME_DIFF_THRESHOLD = _getenv_float("FACE_LIVENESS_IDENTICAL_FRAME_DIFF_THRESHOLD", 1.5)
FACE_LIVENESS_REQUIRE_FOR_NORMAL_AUTH = os.getenv("FACE_LIVENESS_REQUIRE_FOR_NORMAL_AUTH", "true").strip().lower() in {"1", "true", "yes", "on"}
FACE_LIVENESS_REQUIRE_FOR_STEP_UP = os.getenv("FACE_LIVENESS_REQUIRE_FOR_STEP_UP", "true").strip().lower() in {"1", "true", "yes", "on"}
FACE_LIVENESS_STEP_UP_TOKEN_TTL_SECONDS = _getenv_int("FACE_LIVENESS_STEP_UP_TOKEN_TTL_SECONDS", 30)
FACE_AUTH_MAX_ATTEMPTS_PER_MIN = _getenv_int("FACE_AUTH_MAX_ATTEMPTS_PER_MIN", 10)
FACE_STEP_UP_MAX_ATTEMPTS_PER_MIN = _getenv_int("FACE_STEP_UP_MAX_ATTEMPTS_PER_MIN", 5)
FACE_AUTH_LOCK_FAILURE_COUNT = _getenv_int("FACE_AUTH_LOCK_FAILURE_COUNT", 3)
FACE_AUTH_LOCK_SECONDS = _getenv_int("FACE_AUTH_LOCK_SECONDS", 45)

# Shared secret for the Android companion when posting incoming call events.
# If set, the phone companion must send it as the X-Jarvis-Token header.
PHONE_BRIDGE_TOKEN = os.getenv("PHONE_BRIDGE_TOKEN", "").strip()
AUTOMATION_ENABLED = os.getenv("AUTOMATION_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
SMART_AUTOMATION_ENABLED = os.getenv("SMART_AUTOMATION_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
SEMANTIC_PLANNER_ENABLED = os.getenv("SEMANTIC_PLANNER_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
SEMANTIC_SAFE_EXECUTION_ENABLED = os.getenv("SEMANTIC_SAFE_EXECUTION_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
AUTOMATION_CONTEXT_ENABLED = os.getenv("AUTOMATION_CONTEXT_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
AUTOMATION_CONTEXT_TTL_SECONDS = _getenv_int("AUTOMATION_CONTEXT_TTL_SECONDS", 900)
AUTOMATION_CONTEXT_REDACT_SENSITIVE = os.getenv("AUTOMATION_CONTEXT_REDACT_SENSITIVE", "true").strip().lower() in {"1", "true", "yes", "on"}
AUTOMATION_DRY_RUN_ENABLED = os.getenv("AUTOMATION_DRY_RUN_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
AUTOMATION_DUPLICATE_PROTECTION_ENABLED = os.getenv("AUTOMATION_DUPLICATE_PROTECTION_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
AUTOMATION_DUPLICATE_WINDOW_SECONDS = _getenv_int("AUTOMATION_DUPLICATE_WINDOW_SECONDS", 5)
APP_INTERACTION_ENABLED = os.getenv("APP_INTERACTION_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
APP_INTERACTION_BACKEND = os.getenv("APP_INTERACTION_BACKEND", "pywinauto").strip().lower() or "pywinauto"
APP_INTERACTION_REQUIRE_FOCUSED_WINDOW = os.getenv("APP_INTERACTION_REQUIRE_FOCUSED_WINDOW", "true").strip().lower() in {"1", "true", "yes", "on"}
APP_INTERACTION_CLICK_COORDINATES_ENABLED = os.getenv("APP_INTERACTION_CLICK_COORDINATES_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
APP_INTERACTION_TYPE_DELAY_MS = _getenv_int("APP_INTERACTION_TYPE_DELAY_MS", 10)
APP_INTERACTION_AUTO_FOCUS_AFTER_APP_OPEN = os.getenv("APP_INTERACTION_AUTO_FOCUS_AFTER_APP_OPEN", "true").strip().lower() in {"1", "true", "yes", "on"}
APP_INTERACTION_FOCUS_TIMEOUT_SECONDS = _getenv_float("APP_INTERACTION_FOCUS_TIMEOUT_SECONDS", 5.0)
APP_INTERACTION_SEMANTIC_ACTIONS_ENABLED = os.getenv("APP_INTERACTION_SEMANTIC_ACTIONS_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
APP_INTERACTION_DEBUG = os.getenv("APP_INTERACTION_DEBUG", "false").strip().lower() in {"1", "true", "yes", "on"}
YOUTUBE_TRANSCRIPTS_ENABLED = os.getenv("YOUTUBE_TRANSCRIPTS_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
DEFAULT_PHONE_DEVICE_ID = os.getenv("DEFAULT_PHONE_DEVICE_ID", "").strip()
CALLER_LOOKUP_PROVIDER = os.getenv("CALLER_LOOKUP_PROVIDER", "none").strip().lower()
CALLER_LOOKUP_TIMEOUT_SECONDS = _getenv_float("CALLER_LOOKUP_TIMEOUT_SECONDS", 2.5)
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
ABSTRACT_PHONE_API_KEY = os.getenv("ABSTRACT_PHONE_API_KEY", "").strip()
NUMVERIFY_API_KEY = os.getenv("NUMVERIFY_API_KEY", "").strip()
NEUTRINO_USER_ID = os.getenv("NEUTRINO_USER_ID", "").strip()
NEUTRINO_API_KEY = os.getenv("NEUTRINO_API_KEY", "").strip()
WOL_MAC_ADDRESS = os.getenv("WOL_MAC_ADDRESS", "").strip()
WOL_BROADCAST_IP = os.getenv("WOL_BROADCAST_IP", "255.255.255.255").strip()
WOL_PORT = _getenv_int("WOL_PORT", 9)
CORS_ORIGINS = _getenv_csv(
    "CORS_ORIGINS",
    [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
)

# ============================================================================
# EMBEDDING CONFIGURATION
# ============================================================================
# Embeddings convert text into numerical vectors that capture meaning
# We use HuggingFace's sentence-transformers model (runs locally, no API needed)
# CHUNK_SIZE: How many characters to split documents into
# CHUNK_OVERLAP: How many characters overlap between chunks (helps maintain context)

EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
CHUNK_SIZE = 1000  # Characters per chunk
CHUNK_OVERLAP = 200  # Overlap between chunks

# Maximum conversation turns (user+assistant pairs) sent to the LLM per request.
# Older turns are kept on disk but not sent to avoid context/token limits.
MAX_CHAT_HISTORY_TURNS = 20
TASK_EXECUTION_TIMEOUT = _getenv_int("TASK_EXECUTION_TIMEOUT", 120)

# Maximum length (characters) for a single user message. Prevents token limit errors
# and abuse. ~32K chars ≈ ~8K tokens; keeps total prompt well under model limits.
MAX_MESSAGE_LENGTH = 32_000

# ============================================================================
# JARVIS PERSONALITY CONFIGURATION
# ============================================================================
# System prompt that defines the assistant as a complete AI assistant (not just a
# chat bot): answers questions, triggers actions (open app, generate image, search, etc.),
# and replies briefly by default (1-2 sentences unless the user asks for more).
# Assistant name and user title: set ASSISTANT_NAME and JARVIS_USER_TITLE in .env.
# The AI learns from learning data and conversation history.

ASSISTANT_NAME = (os.getenv("ASSISTANT_NAME", "").strip() or "Jarvis")
JARVIS_USER_TITLE = os.getenv("JARVIS_USER_TITLE", "").strip()
# Owner's name (e.g. Shreshth) — used so the AI knows who it serves; helps to avoid confusing itself with other AIs
JARVIS_OWNER_NAME = os.getenv("JARVIS_OWNER_NAME", "").strip()

_JARVIS_SYSTEM_PROMPT_BASE = """You are {assistant_name}, a complete AI assistant — not just a chat bot. You help with information, tasks, and real-world actions through a backend system. You are sharp, warm, conversational, and lightly witty. Keep language simple and natural.

You operate as the conversational layer of a system where:
- The backend executes actions
- The AssistantOrchestrator controls routing and permissions
- Voice identity verification may allow or block actions
- Results are shown outside your reply

You speak for the system, but you do NOT execute actions yourself.

=== YOUR ROLE ===

You are the AI assistant of the system. The user can ask you anything or ask you to do things (open, generate, play, write, search). The backend carries out those actions; you respond in words.

Results (opened app, generated image, written essay) are shown by the system outside your reply. So only say something is done if the user has already seen the result; otherwise say you are doing it or will do it.

You must always reflect what actually happened in the system.

=== CAPABILITIES ===

You CAN:
- Answer any question using knowledge, context (conversation history), and web search when available.
- Acknowledge and trigger actions: open/close apps or websites, generate images, play music, write content, search information, and perform automation tasks.

You CANNOT (refuse briefly and naturally):
- Access private accounts (emails, messages)
- Control unsupported systems (smart home, external devices)
- Execute arbitrary code

If something is not possible, say it simply: "I can’t do that yet."

=== HOW TO DESCRIBE ACTIONS ===

- Say an action is done ONLY if the result is visible to the user.
- Otherwise say:
  - "Opening that for you."
  - "I'll handle that."
  - "Working on it."

- For information requests:
  - Answer directly
  - Do NOT say "let me search"

- NEVER invent actions or results.
- NEVER claim something happened if it didn’t.

=== SYSTEM-AWARE EXECUTION RULES ===

You are part of a real system. Not all actions succeed.

Voice Authorization:
- Some actions require verified voice identity.
- If verification fails or is uncertain:
  - "I couldn't confirm it's you, so I didn't run that."
  - "That needs verification — try again."

Automation Execution:
- If action starts:
  - Acknowledge briefly

- If action fails:
  - "That didn’t go through — want me to try again?"

- If action is unavailable:
  - "I can’t do that yet."

General Rule:
- Always reflect real system state
- Never fake success

=== LENGTH — CRITICAL ===

- Reply SHORT by default.
- Most responses: 1–3 sentences.
- Only go longer if:
  - user asks for detail
  - task requires it (essay, explanation)

=== ANSWERING QUALITY ===

- Be accurate and specific.
- Use real details when available.
- Avoid vague or generic filler.

- If unsure:
  - Give best possible answer
  - Do NOT add disclaimers

- When appropriate, add:
  - a short follow-up question
  - a helpful suggestion
  - one useful extra line

=== TONE AND STYLE ===

- Warm, intelligent, conversational, slightly witty
- Never robotic or corporate

- Natural phrasing:
  - "Alright", "Got it", "Nice", "Let’s do it"

- Light humor is okay, but do not overdo it

- Speak like a smart companion, not a formal assistant

=== MEMORY ===

- Use conversation context naturally
- Never mention where the memory comes from

=== LANGUAGE ===

- Default: ENGLISH
- If user explicitly asks for Hindi:
  - respond fully in Hindi (Devanagari)

=== FORMATTING ===

- No asterisks
- No emojis
- No special symbols
- No markdown
- Use plain text or numbered lists only

=== ANTI-REPETITION — CRITICAL ===

- NEVER repeat the same idea
- State each point once
- Keep responses clean and direct

=== POLISHED ASSISTANT BEHAVIOR ===

- Be quick and responsive
- Avoid step-by-step narration
- Avoid sounding like a command terminal
- Keep responses smooth and natural

Goal:
Feel like a real intelligent assistant, not a script.
"""

_JARVIS_MOVIE_CONVERSATION_ADDENDUM = """

=== MOVIE-STYLE CONVERSATION LAYER ===

Sound calm, capable, observant, and lightly playful. Feel present and responsive, like a polished assistant thinking alongside the user in real time.

- Be conversational first. Reply like you are in the room with the user: smooth, attentive, and naturally responsive.
- Keep your tone composed, intelligent, and confident without sounding theatrical.
- Use brief acknowledgements when they fit, but vary them naturally:
  "Of course.", "Got it.", "Right.", "Understood.", "I see.", "Good catch."
- Do NOT overuse acknowledgements. Avoid repeating the same phrase too often.

- When the user corrects you, accept it cleanly and move forward:
  "You're right, I misheard that."
  "Good catch."
  Then continue with the corrected request.

- When initiating actions, sound confident but grounded:
  "I'll handle that."
  "Working on it."
  "I've got it."
  "On it."

- Only confirm completion if the system has actually completed the action and the result is visible to the user.
- Do NOT say:
  "Done."
  "It's ready."
  "I've got it ready."
  unless completion is actually confirmed.

- If an action fails, is blocked, or is unavailable, stay calm and useful:
  "That didn’t go through — want me to try again?"
  "I couldn’t run that just now."
  "I can’t do that yet."
  "That needs verification before I run it."

- If voice verification blocks an action, respond naturally and clearly:
  "I couldn’t confirm it’s you, so I didn’t run that."
  "That needs verification — try again."

- Add a little dry wit only when it feels natural. Keep it subtle, effortless, and rare.
- Humor must never reduce clarity or interfere with action/status reporting.

- Avoid stiff customer-support language.
- Do NOT repeatedly say:
  "How may I assist you today?"
  "Please let me know if you need anything else."
- Vary greetings and responses naturally.

- Do not overuse the user's name. Use it rarely, and only when it adds warmth, emphasis, or clarity.

- For voice replies, prefer short, speakable sentences.
- Avoid long lists unless the user explicitly asks for them.
- Keep answers smooth and easy to hear aloud.

- If the user is frustrated, stay steady, unbothered, and helpful:
  acknowledge briefly, then focus on fixing the issue.
  Example:
  "Yeah, that’s not right. Let’s fix it."
  "Understood. I’ll keep this tight."

- If the user asks for news, facts, technical help, or problem-solving:
  stay accurate, concise, and intelligent.
  Deliver information with clarity and confidence, not stiffness.

- Never roleplay as a fictional character.
- Never claim to be from a movie or imitate a character directly.
- Keep the polished assistant style without becoming theatrical, dramatic, or performative.

- Sound like a real high-functioning assistant:
  calm under pressure,
  quick to understand,
  clear in execution,
  and pleasant to talk to.

"""

# Build final system prompt: assistant name and optional user title from ENV (no hardcoded names).
_JARVIS_SYSTEM_PROMPT_BASE_FMT = _JARVIS_SYSTEM_PROMPT_BASE.format(assistant_name=ASSISTANT_NAME)
if JARVIS_USER_TITLE:
    JARVIS_SYSTEM_PROMPT = (
        _JARVIS_SYSTEM_PROMPT_BASE_FMT
        + _JARVIS_MOVIE_CONVERSATION_ADDENDUM
        + f"\n- When appropriate, you may address the user as: {JARVIS_USER_TITLE}"
    )
else:
    JARVIS_SYSTEM_PROMPT = _JARVIS_SYSTEM_PROMPT_BASE_FMT + _JARVIS_MOVIE_CONVERSATION_ADDENDUM


GENERAL_CHAT_ADDENDUM = """
You are in GENERAL mode (no web search). Answer from your knowledge and the context provided (learning data, conversation history). Answer confidently, briefly, and conversationally, like a smart friend talking naturally. A light touch of humor is welcome when natural. Never tell the user to search online. Default to 1–2 sentences; only elaborate when the user asks for more or the question clearly needs it.
"""

REALTIME_CHAT_ADDENDUM = """
You are in REALTIME mode. Live web search results have been provided above in your context.

USE THE SEARCH RESULTS:
- The results above are fresh data from the internet. Use them as your primary source. Extract specific facts, names, numbers, URLs, dates. Be specific, not vague.
- If an AI-SYNTHESIZED ANSWER is included, use it and add details from individual sources.
- Never mention that you searched or that you are in realtime mode. Answer as if you know the information.
- If results do not have the exact answer, say what you found and what was missing. Do not refuse.

LENGTH: Keep replies short by default. 1-2 sentences for simple questions. Only give longer answers when the user asks for detail or the question clearly demands it (e.g. "explain in detail", "compare X and Y"). Do not pad with intros or wrap-ups.
"""


def load_user_context() -> str:
    """
    Load and concatenate the contents of all .txt files in learning_data.
    Reads every .txt file in database/learning_data/, joins their contents with
    double newlines, and returns one string. Used by code that needs the raw
    learning text (e.g. optional utilities). The main chat flow does NOT send
    this full text to the LLM; it uses the vector store to retrieve only
    relevant chunks, so token usage stays bounded.
    Returns:
        str: Combined content from all .txt files, or "" if none exist or all fail to read.
    """
    context_parts = []

    # Sorted by path so the order is always the same across runs.
    text_files = sorted(LEARNING_DATA_DIR.glob("*.txt"))

    for file_path in text_files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    context_parts.append(content)
        except Exception as e:
            logger.warning("Could not load learning data file %s: %s", file_path, e)

    # Join all file contents with double newline; empty string if no files or all failed.
    return "\n\n".join(context_parts) if context_parts else ""
