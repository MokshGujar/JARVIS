
/* ================================================================
   J.A.R.V.I.S Frontend — Main Application Logic
   ================================================================

   ARCHITECTURE OVERVIEW
   ---------------------
   This file powers the entire frontend of the J.A.R.V.I.S AI assistant.
   It handles:

   1. CHAT MESSAGING — The user types (or speaks) a message, which is
      sent to the backend via a POST request. The backend responds using
      Server-Sent Events (SSE), allowing the reply to stream in
      token-by-token (like ChatGPT's typing effect).

   2. TEXT-TO-SPEECH (TTS) — When TTS is enabled, the backend also
      sends base64-encoded audio chunks inside the SSE stream. These
      are queued up and played sequentially through a single <audio>
      element. This queue-based approach prevents overlapping audio
      and supports mobile browsers (especially iOS/Safari).

   3. SPEECH RECOGNITION — The Web Speech API captures the user's
      voice, transcribes it in real time, and auto-sends the final
      transcript as a chat message.

   4. ANIMATED ORB — A WebGL-powered visual orb (rendered by a
      separate OrbRenderer class) acts as a visual indicator. It
      "activates" when J.A.R.V.I.S is speaking and goes idle otherwise.

   5. MODE SWITCHING — The UI supports two modes:
      - "General" mode  → uses the /chat/stream endpoint
      - "Realtime" mode → uses the /chat/realtime/stream endpoint
      The mode determines which backend pipeline processes the message.

   6. SESSION MANAGEMENT — A session ID is returned by the server on
      the first message. Subsequent messages include that ID so the
      backend can maintain conversation context. Starting a "New Chat"
      clears the session.

   DATA FLOW (simplified):
   User input → sendMessage() → POST to backend → SSE stream opens →
   tokens arrive as JSON chunks → rendered into the DOM in real time →
   optional audio chunks are enqueued in TTSPlayer → played sequentially.

   ================================================================ */

/*
 * API — The base URL for all backend requests.
 *
 * In production, this resolves to the same origin the page was loaded from
 * (e.g., "https://jarvis.example.com"). During local development, it falls
 * back to "http://localhost:8000" (the default FastAPI dev server port).
 *
 * `window.location.origin` gives us the protocol + host + port of the
 * current page, making the frontend deployment-agnostic (no hardcoded URLs).
 */
const API = (typeof window !== 'undefined' && window.location.origin)
    ? window.location.origin
    : 'http://localhost:8000';

/* ================================================================
   APPLICATION STATE
   ================================================================
   These variables track the global state of the application. They are
   intentionally kept as simple top-level variables rather than in a
   class or store, since this is a single-page app with one chat view.
   ================================================================ */

/*
 * sessionId — Unique conversation identifier returned by the server.
 * Starts as null (no conversation yet). Once the first server response
 * arrives, it contains a UUID string that we send back with every
 * subsequent message so the backend knows which conversation we're in.
 */
const CHAT_SESSION_STORAGE_KEY = 'jarvis_chat_session_id';
let sessionId = localStorage.getItem(CHAT_SESSION_STORAGE_KEY) || null;

/*
 * currentMode — Which AI pipeline to use: 'jarvis', 'general', or 'realtime'.
 * - jarvis:   Unified route; brain classifies, then routes to general or realtime.
 * - general:  Direct /chat/stream (no web search).
 * - realtime: Direct /chat/realtime/stream (with Tavily web search).
 */
const MODE_STORAGE_KEY = 'jarvis_mode';
let currentMode = 'jarvis';
const MODE_ORDER = ['jarvis', 'general', 'realtime', 'screen', 'camera'];
let pendingVisionDataUrl = null;
let cameraStream = null;
let screenStream = null;
let lastScreenShareKind = null;

/*
 * isStreaming — Guard flag that is true while an SSE response is being
 * received. Prevents the user from sending another message while the
 * assistant is still replying (avoids race conditions and garbled output).
 */
let isStreaming = false;

/*
 * isListening — True while the speech recognition engine is actively
 * capturing audio from the microphone. Used to toggle the mic button
 * styling and to decide whether to start or stop listening on click.
 */
let isListening = false;

/*
 * autoListenMode — When true, mic stays "on": after each voice-sent message,
 * we stop listening during the AI response, then auto-restart when the AI
 * and TTS playback are complete. User clicks mic again to turn off.
 */
let autoListenMode = false;
let suppressAutoListenUntil = 0;

/* Speech recognition config */
const SPEECH_ERROR_MAX_RETRIES = 3;
let speechErrorRetryCount = 0;
let speechSendDelayMs = 1200;   /* Pause after final transcript before sending. Raised to reduce cutoffs. */
let speechRestartDelayMs = 700; /* Delay before restarting mic after AI+TTS complete (avoids echo) */
let sttMinRecordSeconds = 1.0;
let sttEndSilenceSeconds = 1.5;
let sttMaxRecordSeconds = 20.0;
let sttSpeechPaddingMs = 300;
let sttCaptureMode = 'backend_parakeet';
let speechSendTimeout = null;
let speechRestartTimeout = null;
let speechRestartBackoffUntil = 0;
let voiceMaxRecordTimeout = null;
let pendingSendTranscript = null;
let safariVoiceHintShown = false;
let voiceCommandRecorder = null;
let voiceCommandStream = null;
let voiceCommandChunks = [];
let voiceCommandCapturePromise = null;
let voiceCommandCaptureMode = 'webm';
let voiceCommandAudioContext = null;
let voiceCommandSource = null;
let voiceCommandProcessor = null;
let voiceCommandWavSamples = [];
let finishingVoiceCommandCapture = false;
let voiceSendInFlight = false;
let voiceIdentityStatus = null;
let speechSupportReason = '';
let faceAuthStatus = null;
let entryGateSessionId = localStorage.getItem('jarvis_entry_gate_session_id') || '';
let faceStatusInAppEnabled = false;
let faceVerifyInAppEnabled = false;
let pendingStepUpToken = '';
let sttEmptyTranscriptBehavior = 'short_prompt';
let sttEmptyTranscriptPrompt = "I didn't catch that.";

/*
 * orb — Reference to the OrbRenderer instance (the animated WebGL orb).
 * Null if OrbRenderer is unavailable or failed to initialize.
 * We call orb.setActive(true/false) to animate it during TTS playback.
 */
let orb = null;

/*
 * recognition — The SpeechRecognition instance from the Web Speech API.
 * Null if the browser doesn't support speech recognition.
 */
let recognition = null;

/*
 * ttsPlayer — Instance of the TTSPlayer class (defined below) that
 * manages queuing and playing audio segments received from the server.
 */
let ttsPlayer = null;
let browserStreamSpeaker = null;
let thinkingAudioPlayer = null;
let reminderPollTimer = null;
let systemMetricsPollTimer = null;
const metricHistory = {
    health: [],
    cpu: [],
    memory: [],
    storage: [],
};
let preStarterPlayer = null;
let thinkingSoundGeneration = 0;
let thinkingSoundPromise = Promise.resolve();
let thinkingSoundDelayTimer = null;
let thinkingSoundMaxTimer = null;
let currentThinkingRequestId = null;
let thinkingAudioPlayedForRequestId = null;
let thinkingAudioPlaying = false;
let finalTtsQueuedForRequestId = null;
let thinkingAudioFinishBeforeFinalTts = true;
let thinkingAudioStopOnFinalTts = false;
let thinkingAudioFinalTtsWaitTimeoutMs = 2500;
let thinkingAudioMaxPerRequest = 1;
let thinkingAudioMode = 'smart';
let thinkingAudioSkipForFastSemantic = true;
let thinkingAudioSkipForEmptyTranscript = true;
let thinkingAudioSkipForClarification = true;
let thinkingAudioMinDelayMs = 250;
const backgroundTaskPolls = new Map();
let voiceGuardVerifiedUntil = 0;
let activeStreamController = null;
let activeClientRequestId = null;
let interruptingForBargeIn = false;
let bargeInListeningMode = false;
let bargeInInterruptSent = false;
let activeStepUpRequestId = null;
let listeningStartedAt = 0;
let voiceSilenceMonitorContext = null;
let voiceSilenceMonitorSource = null;
let voiceSilenceMonitorProcessor = null;
let voiceSilenceLoopActive = false;
let voiceSpeechDetected = false;
let voiceLastSpeechAt = 0;
let voiceSendTriggered = false;

function isCurrentStreamPayload(data, expectedRequestId) {
    const payloadRequestId = data && typeof data === 'object' ? (data.client_request_id || null) : null;
    if (payloadRequestId && payloadRequestId !== expectedRequestId) return false;
    return activeClientRequestId === expectedRequestId;
}

function buildClientRequestId() {
    return `web-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function invalidateActiveStepUp() {
    activeStepUpRequestId = null;
}

async function fetchRuntimeVoiceConfig() {
    try {
        const r = await fetch(`${API}/health`);
        const d = await r.json().catch(() => null);
        const stt = d && d.stt ? d.stt : {};
        sttCaptureMode = String(stt.capture_mode || sttCaptureMode || 'backend_parakeet').toLowerCase();
        speechSendDelayMs = Math.max(700, Math.round(Number(stt.end_silence_seconds || sttEndSilenceSeconds) * 1000));
        sttMinRecordSeconds = Math.max(0.5, Number(stt.min_record_seconds || sttMinRecordSeconds));
        sttEndSilenceSeconds = Math.max(0.7, Number(stt.end_silence_seconds || sttEndSilenceSeconds));
        sttMaxRecordSeconds = Math.max(sttMinRecordSeconds, Number(stt.max_record_seconds || sttMaxRecordSeconds));
        sttSpeechPaddingMs = Math.max(0, Number(stt.speech_padding_ms || sttSpeechPaddingMs));
        sttEmptyTranscriptBehavior = String(stt.empty_transcript_behavior || sttEmptyTranscriptBehavior || 'short_prompt').toLowerCase();
        sttEmptyTranscriptPrompt = String(stt.empty_transcript_prompt || sttEmptyTranscriptPrompt || "I didn't catch that.");
        const faceInApp = d && d.face_in_app ? d.face_in_app : {};
        faceStatusInAppEnabled = faceInApp.status_enabled === true;
        faceVerifyInAppEnabled = faceInApp.verify_enabled === true;
        const thinkingAudio = d && d.tts && d.tts.thinking_audio ? d.tts.thinking_audio : {};
        thinkingAudioFinishBeforeFinalTts = thinkingAudio.finish_before_final_tts !== false;
        thinkingAudioStopOnFinalTts = thinkingAudio.stop_on_final_tts === true;
        thinkingAudioFinalTtsWaitTimeoutMs = Math.max(250, Number(thinkingAudio.final_tts_wait_timeout_ms || thinkingAudioFinalTtsWaitTimeoutMs));
        thinkingAudioMaxPerRequest = Math.max(1, Number(thinkingAudio.max_per_request || thinkingAudioMaxPerRequest));
        thinkingAudioMode = String(thinkingAudio.mode || thinkingAudioMode || 'smart').toLowerCase();
        thinkingAudioSkipForFastSemantic = thinkingAudio.skip_for_fast_semantic !== false;
        thinkingAudioSkipForEmptyTranscript = thinkingAudio.skip_for_empty_transcript !== false;
        thinkingAudioSkipForClarification = thinkingAudio.skip_for_clarification !== false;
        thinkingAudioMinDelayMs = Math.max(0, Number(thinkingAudio.min_delay_ms ?? thinkingAudioMinDelayMs));
    } catch (_) {}
}

function setChatSessionId(nextSessionId) {
    sessionId = nextSessionId || null;
    if (sessionId) {
        localStorage.setItem(CHAT_SESSION_STORAGE_KEY, sessionId);
    } else {
        localStorage.removeItem(CHAT_SESSION_STORAGE_KEY);
    }
}

function isBackendSttCaptureMode() {
    return sttCaptureMode === 'backend_parakeet';
}

function isAssistantAudioActive() {
    return !!(
        preStarterPlayer?.playing ||
        thinkingAudioPlaying ||
        thinkingAudioPlayer?.playing ||
        ttsPlayer?.playing ||
        ttsPlayer?.queue?.length ||
        browserStreamSpeaker?.playing ||
        browserStreamSpeaker?.queue?.length ||
        browserStreamSpeaker?.ttsTextBuffer?.trim?.()
    );
}

function shouldAllowBackendBargeIn() {
    return !!(autoListenMode && isBackendSttCaptureMode() && (isStreaming || isAssistantAudioActive()));
}

/*
 * settings — User preferences (auto-open panels). Stored in localStorage.
 */
const SETTINGS_KEY = 'jarvis_settings';
const DEFAULT_SETTINGS = {
    autoOpenActivity: true,
    autoOpenSearchResults: true,
    thinkingSounds: true,
    voiceGuardEnabled: false,
    voiceprintFeatures: null,
};
let settings = { ...DEFAULT_SETTINGS };
const LOCAL_SLEEP_PHRASES = new Set();
const LOCAL_SLEEP_GOODBYE = '';

function normalizeVoiceShortcut(text) {
    return String(text || '')
        .toLowerCase()
        .replace(/[.,!?]/g, ' ')
        .replace(/\s+/g, ' ')
        .trim();
}

function isVoiceGuardActive() {
    return false;
}

function verifyVoiceGuardTranscript(transcript) {
    if (settings.voiceprintFeatures) {
        if (Date.now() <= voiceGuardVerifiedUntil) {
            return { allowed: true, cleaned: transcript };
        }
        return { allowed: false, verifiedOnly: false, cleaned: '' };
    }

    return { allowed: false, verifiedOnly: false, cleaned: '' };
}

async function captureFaceFrames(count = 5, intervalMs = 150) {
    if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error('Camera is not available.');
    }
    const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user' }, audio: false });
    const video = document.createElement('video');
    video.muted = true;
    video.playsInline = true;
    video.srcObject = stream;
    await video.play();
    await new Promise(resolve => setTimeout(resolve, 250));
    const canvas = document.createElement('canvas');
    canvas.width = video.videoWidth || 640;
    canvas.height = video.videoHeight || 480;
    const ctx = canvas.getContext('2d');
    const frames = [];
    try {
        for (let i = 0; i < count; i++) {
            ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
            frames.push(canvas.toDataURL('image/jpeg', 0.88).split(',')[1]);
            if (i < count - 1) await new Promise(resolve => setTimeout(resolve, intervalMs));
        }
    } finally {
        stream.getTracks().forEach(track => track.stop());
    }
    return frames;
}

function updateFaceAuthStatus() {
    if (!faceAuthStatusEl) return;
    if (entryGateSessionId) {
        faceAuthStatusEl.textContent = 'Entry gate verified for this app session.';
        return;
    }
    const enrolled = !!faceAuthStatus?.profile_enrolled;
    faceAuthStatusEl.textContent = enrolled ? 'Entry gate profile is ready.' : 'Entry gate verification happens in the launcher.';
}

async function refreshFaceAuthStatus() {
    if (!faceStatusInAppEnabled) {
        updateFaceAuthStatus();
        return faceAuthStatus;
    }
    const res = await fetch(`${API}/face/status`);
    faceAuthStatus = await res.json();
    updateFaceAuthStatus();
    return faceAuthStatus;
}

async function consumeLauncherBootstrapToken() {
    const url = new URL(window.location.href);
    const token = url.searchParams.get('bootstrap_token');
    if (!token) return;

    try {
        const res = await fetch(`${API}/auth/launcher/exchange-bootstrap`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ bootstrap_token: token }),
        });
        const payload = await res.json().catch(() => ({}));
        if (res.ok && payload.exchanged && payload.face_session_id) {
            entryGateSessionId = payload.face_session_id;
            localStorage.setItem('jarvis_entry_gate_session_id', entryGateSessionId);
            showToast('Entry gate verified.');
        } else {
            entryGateSessionId = '';
            localStorage.removeItem('jarvis_entry_gate_session_id');
            showToast(payload.reason || 'Launcher authentication expired.');
        }
    } catch (_) {
        entryGateSessionId = '';
        localStorage.removeItem('jarvis_entry_gate_session_id');
        showToast('Launcher authentication unavailable.');
    } finally {
        url.searchParams.delete('bootstrap_token');
        const clean = `${url.pathname}${url.search}${url.hash}`;
        window.history.replaceState({}, document.title, clean);
    }
}

async function verifyFaceNow() {
    if (!faceVerifyInAppEnabled) {
        window.location.assign('/launcher/');
        return { status: 'launcher_required' };
    }
    throw new Error('In-app face verification is disabled.');
}

async function enrollFaceProfile() {
    const start = await fetch(`${API}/face/enroll/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_name: 'Moksh', replace_existing: true }),
    }).then(r => r.json());
    const session = start.enrollment_session_id;
    const required = start.required_samples || 5;
    for (let i = 0; i < required; i++) {
        showToast(`Capturing face sample ${i + 1} of ${required}.`);
        const frames = await captureFaceFrames();
        const sample = await fetch(`${API}/face/enroll/sample`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enrollment_session_id: session, frames }),
        }).then(r => r.json());
        if (!sample.accepted) throw new Error(sample.reason || 'Face sample rejected.');
    }
    const complete = await fetch(`${API}/face/enroll/complete`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enrollment_session_id: session }),
    }).then(r => r.json());
    await refreshFaceAuthStatus();
    if (!complete.enrolled) throw new Error(complete.reason || 'Enrollment needs more valid samples.');
    showToast('Face profile enrolled.');
}

async function clearFaceProfile() {
    const res = await fetch(`${API}/face/profile`, { method: 'DELETE' });
    const payload = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(payload.detail || 'Could not delete face profile.');
    entryGateSessionId = '';
    pendingStepUpToken = '';
    localStorage.removeItem('jarvis_entry_gate_session_id');
    await refreshFaceAuthStatus();
    showToast('Face profile deleted.');
}

async function performStepUpForRisk(authPayload, expectedRequestId = null) {
    activeStepUpRequestId = null;
    throw new Error('Face step-up is disabled inside the app.');
}

async function performFaceAuthorization(authPayload, expectedRequestId = null) {
    activeStepUpRequestId = null;
    throw new Error('Face verification is launcher-only.');
}

function cosineSimilarity(a, b) {
    if (!Array.isArray(a) || !Array.isArray(b)) return 0;
    const size = Math.min(a.length, b.length);
    let dot = 0;
    let aa = 0;
    let bb = 0;
    for (let i = 0; i < size; i++) {
        dot += a[i] * b[i];
        aa += a[i] * a[i];
        bb += b[i] * b[i];
    }
    const denom = Math.sqrt(aa) * Math.sqrt(bb);
    return denom > 0 ? dot / denom : 0;
}

function normalizeFeatureVector(values) {
    const norm = Math.sqrt(values.reduce((sum, value) => sum + value * value, 0));
    return norm > 0 ? values.map(value => Number((value / norm).toFixed(6))) : values;
}

function averageFeatureFrames(frames) {
    if (!frames.length) return [];
    const width = frames[0].length;
    const totals = new Array(width).fill(0);
    for (const frame of frames) {
        for (let i = 0; i < width; i++) {
            totals[i] += frame[i] || 0;
        }
    }
    return totals.map(total => total / frames.length);
}

function asVoiceprintFeatureSet(features) {
    if (!Array.isArray(features) || !features.length) return [];
    return Array.isArray(features[0]) ? features : [features];
}

function maxFeatureSetSimilarity(a, b) {
    const left = asVoiceprintFeatureSet(a);
    const right = asVoiceprintFeatureSet(b);
    let best = 0;
    for (const leftFeature of left) {
        for (const rightFeature of right) {
            best = Math.max(best, cosineSimilarity(leftFeature, rightFeature));
        }
    }
    return best;
}

async function fetchVoiceIdentityStatus(force = false) {
    if (!force && voiceIdentityStatus) return voiceIdentityStatus;
    voiceIdentityStatus = {
        available: false,
        webm_decode_available: false,
        wav_decode_available: true,
        profile_enrolled: false,
    };
    return voiceIdentityStatus;
}

function updateVoiceprintStatus() {
    const enrolled = !!voiceIdentityStatus?.profile_enrolled;
    const profileExists = !!voiceIdentityStatus?.profile_exists || (voiceIdentityStatus?.accepted_samples || 0) > 0;
    if (voiceprintStatus) {
        voiceprintStatus.textContent = enrolled
            ? 'Voice identity authentication is disabled.'
            : 'Voice identity authentication has been removed. Speech is command input only.';
    }
    if (clearVoiceprintBtn) clearVoiceprintBtn.disabled = !profileExists;
}

async function refreshVoiceIdentityStatus(force = false) {
    await fetchVoiceIdentityStatus(force);
    updateVoiceprintStatus();
}

async function captureBrowserVoiceprintFeatureSet(durationMs = 3500) {
    if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error('Microphone capture is not available in this browser.');
    }

    const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
            channelCount: 1,
        }
    });

    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    const audioContext = new AudioContextClass();
    const source = audioContext.createMediaStreamSource(stream);
    const analyser = audioContext.createAnalyser();
    analyser.fftSize = 2048;
    analyser.smoothingTimeConstant = 0.35;
    source.connect(analyser);

    const freqData = new Float32Array(analyser.frequencyBinCount);
    const timeData = new Float32Array(analyser.fftSize);
    const spectralBuckets = new Array(12).fill(0);
    const frameFeatures = [];
    let rmsTotal = 0;
    let zcrTotal = 0;
    let frames = 0;

    const stopAt = performance.now() + durationMs;
    try {
        while (performance.now() < stopAt) {
            analyser.getFloatFrequencyData(freqData);
            analyser.getFloatTimeDomainData(timeData);
            let rms = 0;
            let zcr = 0;
            for (let i = 0; i < timeData.length; i++) {
                rms += timeData[i] * timeData[i];
                if (i > 0 && ((timeData[i] >= 0) !== (timeData[i - 1] >= 0))) zcr += 1;
            }
            rms = Math.sqrt(rms / timeData.length);
            rmsTotal += rms;
            zcrTotal += zcr / timeData.length;

            const bucketValues = [];
            for (let bucket = 0; bucket < spectralBuckets.length; bucket++) {
                const start = Math.floor(bucket * freqData.length / spectralBuckets.length);
                const end = Math.floor((bucket + 1) * freqData.length / spectralBuckets.length);
                let sum = 0;
                for (let i = start; i < end; i++) {
                    const db = Number.isFinite(freqData[i]) ? freqData[i] : -100;
                    sum += Math.max(0, (db + 100) / 100);
                }
                const bucketValue = sum / Math.max(1, end - start);
                spectralBuckets[bucket] += bucketValue;
                bucketValues.push(bucketValue);
            }
            frameFeatures.push([rms, zcr / timeData.length, ...bucketValues]);
            frames += 1;
            await new Promise(resolve => setTimeout(resolve, 70));
        }
    } finally {
        stream.getTracks().forEach(track => track.stop());
        await audioContext.close().catch(() => {});
    }

    if (frames === 0 || rmsTotal / frames < 0.006) {
        throw new Error('Voice sample was too quiet.');
    }

    const featureSet = [normalizeFeatureVector([
        rmsTotal / frames,
        zcrTotal / frames,
        ...spectralBuckets.map(value => value / frames),
    ])];

    const windowFrames = Math.max(8, Math.round(1400 / 70));
    const stepFrames = Math.max(4, Math.round(700 / 70));
    for (let start = 0; start + Math.floor(windowFrames / 2) <= frameFeatures.length && featureSet.length < 8; start += stepFrames) {
        const window = frameFeatures.slice(start, Math.min(frameFeatures.length, start + windowFrames));
        if (window.length >= Math.floor(windowFrames / 2)) {
            featureSet.push(normalizeFeatureVector(averageFeatureFrames(window)));
        }
    }

    return featureSet;
}

async function captureBrowserVoiceprintFeatures(durationMs = 1800) {
    const featureSet = await captureBrowserVoiceprintFeatureSet(durationMs);
    return featureSet[0];
}

function canUseWebmVoiceCapture() {
    return !!(voiceIdentityStatus?.webm_decode_available && typeof MediaRecorder !== 'undefined');
}

function canUseWavVoiceCapture() {
    return !!(window.AudioContext || window.webkitAudioContext);
}

function getPreferredWebmRecorderMimeType() {
    if (!canUseWebmVoiceCapture()) return '';
    if (typeof MediaRecorder.isTypeSupported !== 'function') return '';
    for (const candidate of ['audio/webm;codecs=opus', 'audio/webm']) {
        if (MediaRecorder.isTypeSupported(candidate)) return candidate;
    }
    return '';
}

async function createWavCaptureSession(stream) {
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    const audioContext = new AudioContextClass({ sampleRate: 16000 });
    const source = audioContext.createMediaStreamSource(stream);
    const processor = audioContext.createScriptProcessor(4096, 1, 1);
    const mutedOutput = audioContext.createGain();
    mutedOutput.gain.value = 0;
    const chunks = [];

    processor.onaudioprocess = event => {
        const input = event.inputBuffer.getChannelData(0);
        chunks.push(new Float32Array(input));
    };
    source.connect(processor);
    processor.connect(mutedOutput);
    mutedOutput.connect(audioContext.destination);

    return {
        stop: async () => {
            processor.disconnect();
            source.disconnect();
            mutedOutput.disconnect();
            await audioContext.close().catch(() => {});
            return encodeWavDataUrl(chunks, audioContext.sampleRate || 16000);
        },
        processor,
        source,
        audioContext,
        chunks,
    };
}

async function setupVoiceSilenceMonitor(stream) {
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    const audioContext = new AudioContextClass({ sampleRate: 16000 });
    const source = audioContext.createMediaStreamSource(stream);
    const processor = audioContext.createScriptProcessor(2048, 1, 1);
    const mutedOutput = audioContext.createGain();
    mutedOutput.gain.value = 0;

    processor.onaudioprocess = event => {
        const input = event.inputBuffer.getChannelData(0);
        let energy = 0;
        for (let i = 0; i < input.length; i++) energy += input[i] * input[i];
        const rms = Math.sqrt(energy / Math.max(1, input.length));
        if (rms > 0.012) {
            voiceSpeechDetected = true;
            voiceLastSpeechAt = Date.now();
            if (bargeInListeningMode && shouldAllowBackendBargeIn()) {
                handleVoiceBargeInSpeechStart();
            }
        }
    };

    source.connect(processor);
    processor.connect(mutedOutput);
    mutedOutput.connect(audioContext.destination);

    voiceSilenceMonitorContext = audioContext;
    voiceSilenceMonitorSource = source;
    voiceSilenceMonitorProcessor = processor;
    voiceSilenceLoopActive = true;
    voiceSpeechDetected = false;
    voiceLastSpeechAt = Date.now();
    voiceSendTriggered = false;

    const tick = () => {
        if (!voiceSilenceLoopActive || !isBackendSttCaptureMode()) return;
        const elapsedMs = Date.now() - listeningStartedAt;
        const silenceMs = Date.now() - voiceLastSpeechAt;
        const minMet = elapsedMs >= (sttMinRecordSeconds * 1000);
        const silenceMet = silenceMs >= (sttEndSilenceSeconds * 1000);
        if (voiceSpeechDetected && minMet && silenceMet && !voiceSendTriggered) {
            voiceSendTriggered = true;
            stopListening({ discardPending: false, stopRecognition: false });
            return;
        }
        window.setTimeout(tick, 120);
    };
    window.setTimeout(tick, 120);
}

async function teardownVoiceSilenceMonitor() {
    voiceSilenceLoopActive = false;
    try { voiceSilenceMonitorProcessor?.disconnect(); } catch (_) {}
    try { voiceSilenceMonitorSource?.disconnect(); } catch (_) {}
    try { voiceSilenceMonitorContext && await voiceSilenceMonitorContext.close(); } catch (_) {}
    voiceSilenceMonitorProcessor = null;
    voiceSilenceMonitorSource = null;
    voiceSilenceMonitorContext = null;
}

function encodeWavDataUrl(chunks, sampleRate) {
    const totalLength = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
    const merged = new Float32Array(totalLength);
    let offset = 0;
    for (const chunk of chunks) {
        merged.set(chunk, offset);
        offset += chunk.length;
    }

    const buffer = new ArrayBuffer(44 + merged.length * 2);
    const view = new DataView(buffer);
    let position = 0;
    const writeString = value => {
        for (let i = 0; i < value.length; i++) {
            view.setUint8(position++, value.charCodeAt(i));
        }
    };

    writeString('RIFF');
    view.setUint32(position, 36 + merged.length * 2, true); position += 4;
    writeString('WAVE');
    writeString('fmt ');
    view.setUint32(position, 16, true); position += 4;
    view.setUint16(position, 1, true); position += 2;
    view.setUint16(position, 1, true); position += 2;
    view.setUint32(position, sampleRate, true); position += 4;
    view.setUint32(position, sampleRate * 2, true); position += 4;
    view.setUint16(position, 2, true); position += 2;
    view.setUint16(position, 16, true); position += 2;
    writeString('data');
    view.setUint32(position, merged.length * 2, true); position += 4;

    for (let i = 0; i < merged.length; i++) {
        const sample = Math.max(-1, Math.min(1, merged[i]));
        view.setInt16(position, sample < 0 ? sample * 0x8000 : sample * 0x7FFF, true);
        position += 2;
    }

    const bytes = new Uint8Array(buffer);
    let binary = '';
    const chunkSize = 0x8000;
    for (let i = 0; i < bytes.length; i += chunkSize) {
        binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize));
    }
    return `data:audio/wav;base64,${btoa(binary)}`;
}

async function beginVoiceCommandCapture() {
    if (!navigator.mediaDevices?.getUserMedia) return;
    try {
        await fetchVoiceIdentityStatus();
        voiceCommandChunks = [];
        voiceCommandWavSamples = [];
        voiceCommandStream = await navigator.mediaDevices.getUserMedia({
            audio: {
                echoCancellation: true,
                noiseSuppression: true,
                autoGainControl: true,
                channelCount: 1,
            }
        });
        if (isBackendSttCaptureMode()) {
            await setupVoiceSilenceMonitor(voiceCommandStream);
        }
        const preferredWebmMimeType = getPreferredWebmRecorderMimeType();
        if (canUseWavVoiceCapture()) {
            voiceCommandCaptureMode = 'wav';
            const session = await createWavCaptureSession(voiceCommandStream);
            voiceCommandAudioContext = session.audioContext;
            voiceCommandSource = session.source;
            voiceCommandProcessor = session.processor;
            voiceCommandWavSamples = session.chunks;
            voiceCommandCapturePromise = session.stop;
        } else if (preferredWebmMimeType) {
            voiceCommandCaptureMode = 'webm';
            voiceCommandRecorder = new MediaRecorder(voiceCommandStream, { mimeType: preferredWebmMimeType });
            voiceCommandRecorder.ondataavailable = event => {
                if (event.data && event.data.size > 0) voiceCommandChunks.push(event.data);
            };
            voiceCommandCapturePromise = new Promise(resolve => {
                voiceCommandRecorder.onstop = () => {
                    const blob = new Blob(voiceCommandChunks, { type: voiceCommandRecorder?.mimeType || preferredWebmMimeType });
                    const reader = new FileReader();
                    reader.onloadend = () => resolve(String(reader.result || ''));
                    reader.onerror = () => resolve('');
                    reader.readAsDataURL(blob);
                };
            });
            voiceCommandRecorder.start();
        } else {
            throw new Error('No supported voice capture mode is available.');
        }
    } catch (_) {
        voiceCommandRecorder = null;
        voiceCommandStream = null;
        voiceCommandChunks = [];
        voiceCommandCapturePromise = Promise.resolve('');
    }
}

async function finishVoiceCommandCapture() {
    const recorder = voiceCommandRecorder;
    const capturePromise = voiceCommandCapturePromise || Promise.resolve('');
    if (voiceCommandCaptureMode === 'webm') {
        if (recorder && recorder.state !== 'inactive') {
            try { recorder.stop(); } catch (_) {}
        }
    }
    try {
        if (voiceCommandCaptureMode === 'wav' && typeof capturePromise === 'function') {
            return await Promise.race([
                capturePromise(),
                new Promise(resolve => setTimeout(() => resolve(''), 1200)),
            ]);
        }
        return await Promise.race([
            capturePromise,
            new Promise(resolve => setTimeout(() => resolve(''), 1200)),
        ]);
    } finally {
        if (voiceCommandStream) {
            voiceCommandStream.getTracks().forEach(track => track.stop());
        }
        voiceCommandRecorder = null;
        voiceCommandStream = null;
        voiceCommandChunks = [];
        voiceCommandCapturePromise = null;
        voiceCommandAudioContext = null;
        voiceCommandSource = null;
        voiceCommandProcessor = null;
        voiceCommandWavSamples = [];
        teardownVoiceSilenceMonitor().catch(() => {});
    }
}

function dataUrlToBlob(dataUrl) {
    const match = String(dataUrl || '').match(/^data:([^;]+);base64,(.+)$/);
    if (!match) return null;
    const mimeType = match[1];
    const binary = atob(match[2]);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    return new Blob([bytes], { type: mimeType });
}

async function transcribeCapturedVoiceAudio(voiceAudioBase64) {
    const blob = dataUrlToBlob(voiceAudioBase64);
    if (!blob || blob.size === 0) throw new Error('empty_audio');
    const extension = voiceCommandCaptureMode === 'wav' ? 'wav' : 'webm';
    const response = await fetch(`${API}/stt/transcribe`, {
        method: 'POST',
        headers: {
            'Content-Type': blob.type || (extension === 'wav' ? 'audio/wav' : 'audio/webm'),
            'X-Audio-Filename': `voice-command.${extension}`,
        },
        body: blob,
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
        const detail = payload?.detail;
        const message = typeof detail === 'string'
            ? detail
            : (detail?.error || detail?.reason || 'transcription_failed');
        throw new Error(message);
    }
    return payload;
}

function handleEmptyTranscript() {
    cancelThinkingSound();
    setJarvisVisualState(isListening ? 'listening' : 'idle');
    if (sttEmptyTranscriptBehavior !== 'silent') {
        const prompt = sttEmptyTranscriptPrompt || "I didn't catch that.";
        showToast(prompt);
        if (speechWidgetText) speechWidgetText.textContent = prompt;
    }
}

async function sendCapturedVoiceCommand() {
    if (finishingVoiceCommandCapture || voiceSendInFlight) return false;
    finishingVoiceCommandCapture = true;
    voiceSendInFlight = true;
    try {
        if (sttSpeechPaddingMs > 0) {
            await new Promise(resolve => setTimeout(resolve, sttSpeechPaddingMs));
        }
        const voiceAudioBase64 = await finishVoiceCommandCapture();
        const payload = await transcribeCapturedVoiceAudio(voiceAudioBase64);
        const transcript = String(payload?.text || '').trim();
        if (!transcript) {
            handleEmptyTranscript();
            return false;
        }
        if (speechWidgetText) speechWidgetText.textContent = transcript;
        Promise.resolve(sendMessage(transcript, {
            inputSource: 'voice',
            voiceAudioBase64,
        })).finally(() => {
            voiceSendInFlight = false;
            maybeRestartListening();
        });
        return true;
    } catch (error) {
        voiceSendInFlight = false;
        if ((error?.message || error) === 'empty_transcript') {
            handleEmptyTranscript();
            return false;
        }
        showToast(`Voice transcription failed: ${error?.message || error}`);
        throw error;
    } finally {
        finishingVoiceCommandCapture = false;
    }
}

async function sendPendingVoiceTranscript() {
    if (isBackendSttCaptureMode()) {
        return sendCapturedVoiceCommand();
    }
    const transcriptToSend = pendingSendTranscript;
    if (!transcriptToSend || finishingVoiceCommandCapture) return false;

    pendingSendTranscript = null;
    finishingVoiceCommandCapture = true;
    voiceSendInFlight = true;
    try {
        if (sttSpeechPaddingMs > 0) {
            await new Promise(resolve => setTimeout(resolve, sttSpeechPaddingMs));
        }
        const voiceAudioBase64 = await finishVoiceCommandCapture();
        Promise.resolve(sendMessage(transcriptToSend, {
            inputSource: 'voice',
            voiceAudioBase64,
        })).finally(() => {
            voiceSendInFlight = false;
            maybeRestartListening();
        });
        return true;
    } catch (error) {
        voiceSendInFlight = false;
        throw error;
    } finally {
        finishingVoiceCommandCapture = false;
    }
}

async function enrollBrowserVoiceprint() {
    showToast('Voice identity enrollment has been removed. Use face enrollment.');
}

async function clearBackendVoiceprint() {
    voiceIdentityStatus = {
        available: false,
        webm_decode_available: false,
        wav_decode_available: true,
        profile_enrolled: false,
    };
    updateVoiceprintStatus();
    return voiceIdentityStatus;
}

async function resetAndEnrollBrowserVoiceprint() {
    try {
        showToast('Voice identity authentication has been removed.');
        await clearBackendVoiceprint();
        await enrollBrowserVoiceprint();
    } catch (error) {
        showToast(error?.message || 'Voice identity authentication is disabled.');
    }
}

async function handleLocalWakeOrSleep(text) {
    const normalized = normalizeVoiceShortcut(text);
    if (!normalized) return false;

    if (LOCAL_SLEEP_PHRASES.has(normalized)) {
        addMessage('user', text);
        showToast('Jarvis is going to sleep.');
        appendActivity({ type: 'task_completed', label: 'Jarvis is sleeping', detail: 'Say hey jarvis to wake it again.' });
        addMessage('assistant', LOCAL_SLEEP_GOODBYE);
        suppressAutoListenUntil = Date.now() + 2500;
        if (isListening) stopListening();

        const closeWindow = () => {
            setTimeout(() => {
                try {
                    window.open('', '_self');
                    window.close();
                } catch (_) {}
                setTimeout(() => {
                    if (!window.closed) {
                        window.location.replace('about:blank');
                    }
                }, 150);
            }, 700);
        };

        if ('speechSynthesis' in window) {
            try {
                window.speechSynthesis.cancel();
                const utterance = new SpeechSynthesisUtterance(LOCAL_SLEEP_GOODBYE);
                utterance.rate = 1.0;
                utterance.pitch = 1.0;
                utterance.onend = closeWindow;
                utterance.onerror = closeWindow;
                window.speechSynthesis.speak(utterance);
            } catch (_) {
                closeWindow();
            }
        } else {
            closeWindow();
        }

        try {
            await fetch(`${API}/control/sleep`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });
        } catch (_) {}
        return true;
    }

    return false;
}

/* ================================================================
   DOM REFERENCES
   ================================================================
   We grab references to frequently-used DOM elements once at startup
   rather than querying for them every time we need them. This is both
   a performance optimization and a readability convenience.
   ================================================================ */

/*
 * $ — Shorthand helper for document.getElementById. Writing $('foo')
 * is more concise than document.getElementById('foo').
 */
const $ = id => document.getElementById(id);

const chatMessages = $('chat-messages');   // The scrollable container that holds all chat messages
const messageInput = $('message-input');   // The <textarea> where the user types their message
const sendBtn      = $('send-btn');        // The send button (arrow icon)
const micBtn       = $('mic-btn');         // The microphone button for speech-to-text
const ttsBtn       = $('tts-btn');         // The speaker button to toggle text-to-speech
const newChatBtn   = $('new-chat-btn');    // The "New Chat" button that resets the conversation
const charCount    = $('char-count');      // Shows character count when the message gets long
const welcomeTitle = $('welcome-title');   // The greeting text on the welcome screen ("Good morning.", etc.)
const modeSlider   = $('mode-slider');     // The sliding pill indicator behind the mode toggle buttons
const btnJarvis    = $('btn-jarvis');      // The "Jarvis" mode button (unified, brain-routed)
const btnGeneral   = $('btn-general');     // The "General" mode button
const btnRealtime  = $('btn-realtime');    // The "Realtime" mode button
const btnScreen    = $('btn-screen');
const btnCamera    = $('btn-camera');
const modePrevBtn  = $('mode-prev');
const modeNextBtn  = $('mode-next');
const visionToggleBtn = $('vision-toggle-btn');
const statusDot    = document.querySelector('.status-dot');  // Green/red dot showing backend status
const statusText   = document.querySelector('.status-text'); // Text next to the dot ("Online" / "Offline")
const orbContainer = $('orb-container');   // The container <div> that holds the WebGL orb canvas
const searchResultsToggle = $('search-results-toggle');   // Header button to open search results panel
const searchResultsWidget = $('search-results-widget');   // Right-side panel for Tavily search data
const searchResultsClose  = $('search-results-close');    // Close button inside the panel
const searchResultsQuery  = $('search-results-query');    // Displays the search query
const searchResultsAnswer = $('search-results-answer');   // Displays the AI answer from search
const searchResultsList   = $('search-results-list');     // Container for source result cards
const activityPanel       = $('activity-panel');          // Left panel for Jarvis activity flow
const activityToggle      = $('activity-toggle');          // Header button to open activity panel
const activityClose       = $('activity-close');           // Close button inside activity panel
const activityList        = $('activity-list');            // Container for activity items
const panelOverlay        = $('panel-overlay');            // Backdrop when a side panel is open
const speechWidget        = $('speech-widget');            // Live speech-to-text display
const speechWidgetText    = $('speech-widget-text');       // Transcript text element
const settingsBtn         = $('settings-btn');              // Gear icon to open settings
const settingsPanel       = $('settings-panel');            // Settings modal/panel
const settingsClose       = $('settings-close');           // Close settings
const toggleAutoActivity  = $('toggle-auto-activity');     // Auto-open activity panel
const toggleAutoSearch    = $('toggle-auto-search');        // Auto-open search results
const toggleThinkingSounds = $('toggle-thinking-sounds');   // Thinking sound effects
const faceAuthStatusEl = $('face-auth-status');
const verifyFaceBtn = $('verify-face-btn');
const enrollFaceBtn = $('enroll-face-btn');
const clearFaceProfileBtn = $('clear-face-profile-btn');
const toggleVoiceGuard = null;
const voiceprintStatus = null;
const enrollVoiceprintBtn = null;
const clearVoiceprintBtn = null;
const toastContainer     = $('toast-container');           // Toast container for error/status feedback
const visionPanel        = $('vision-panel');
const visionPanelTitle   = $('vision-panel-title');
const visionCaptureBtn   = $('vision-capture-btn');
const visionVideo        = $('vision-video');
const visionPreview      = $('vision-preview');
const visionPlaceholder  = $('vision-placeholder');
const visionStatusBadge  = $('vision-status-badge');
const visionStatusText   = $('vision-status-text');
const visionPresets      = () => document.querySelectorAll('[data-vision-prompt]');
const modeSwitch         = $('mode-switch');
const hudTime            = $('hud-time');
const coreVisual         = $('jarvis-core-visual');
const cameraPreviewPanel = $('camera-preview-panel');
const screenPreviewPanel = $('screen-preview-panel');
const cameraPreviewClose = $('camera-preview-close');
const screenPreviewClose = $('screen-preview-close');
const cameraPreviewBody  = $('camera-preview-body');
const screenPreviewBody  = $('screen-preview-body');
const screenPreviewKind  = $('screen-preview-kind');

class PreStarterPlayer {
    constructor() {
        this.ctx = null;
        this.master = null;
        this.timer = null;
        this.nodes = [];
        this.playing = false;
        this.onComplete = null;
        this.nextPulseMs = 0;
    }

    unlock() {
        if (!this._ensureContext()) return;
        try {
            const now = this.ctx.currentTime;
            const osc = this.ctx.createOscillator();
            const gain = this.ctx.createGain();
            gain.gain.value = 0.0001;
            osc.connect(gain);
            gain.connect(this.master);
            osc.start(now);
            osc.stop(now + 0.001);
        } catch (_) {}
    }

    _ensureContext() {
        const AudioContextClass = window.AudioContext || window.webkitAudioContext;
        if (!AudioContextClass) return false;
        if (!this.ctx || this.ctx.state === 'closed') {
            this.ctx = new AudioContextClass();
            this.master = this.ctx.createGain();
            this.master.gain.value = 0.035;
            this.master.connect(this.ctx.destination);
        }
        if (this.ctx.state === 'suspended') {
            this.ctx.resume().catch(() => {});
        }
        return true;
    }

    _pulse() {
        if (!this.playing || !this.ctx || !this.master) return;

        const now = this.ctx.currentTime;
        const osc = this.ctx.createOscillator();
        const gain = this.ctx.createGain();
        const filter = this.ctx.createBiquadFilter();
        const duration = 0.07 + Math.random() * 0.08;
        const baseFreq = 190 + Math.random() * 170;

        osc.type = Math.random() > 0.35 ? 'sine' : 'triangle';
        osc.frequency.setValueAtTime(baseFreq, now);
        osc.frequency.exponentialRampToValueAtTime(baseFreq * (1.18 + Math.random() * 0.18), now + duration);

        filter.type = 'lowpass';
        filter.frequency.value = 900 + Math.random() * 700;

        gain.gain.setValueAtTime(0.0001, now);
        gain.gain.exponentialRampToValueAtTime(0.12 + Math.random() * 0.08, now + 0.018);
        gain.gain.exponentialRampToValueAtTime(0.0001, now + duration);

        osc.connect(filter);
        filter.connect(gain);
        gain.connect(this.master);
        osc.start(now);
        osc.stop(now + duration + 0.03);

        const cleanup = () => {
            this.nodes = this.nodes.filter(node => node !== osc);
            try { osc.disconnect(); } catch (_) {}
            try { filter.disconnect(); } catch (_) {}
            try { gain.disconnect(); } catch (_) {}
        };
        osc.onended = cleanup;
        this.nodes.push(osc);

        this.nextPulseMs = 180 + Math.random() * 520;
        this.timer = setTimeout(() => this._pulse(), this.nextPulseMs);
    }

    play(onComplete) {
        this.stop(false);
        this.onComplete = onComplete;
        if (!this._ensureContext()) {
            if (onComplete) onComplete();
            return;
        }
        this.playing = true;
        this._pulse();
    }

    stop(complete = true) {
        this.playing = false;
        clearTimeout(this.timer);
        this.timer = null;
        for (const node of this.nodes) {
            try { node.stop(); } catch (_) {}
            try { node.disconnect(); } catch (_) {}
        }
        this.nodes = [];
        const done = this.onComplete;
        this.onComplete = null;
        if (complete && done) done();
    }

    fadeOut(durationMs = 180) {
        if (!this.playing || !this.ctx || !this.master) {
            this.stop();
            return;
        }
        const now = this.ctx.currentTime;
        const endAt = now + Math.max(0.05, durationMs / 1000);
        try {
            this.master.gain.cancelScheduledValues(now);
            this.master.gain.setValueAtTime(Math.max(this.master.gain.value, 0.0001), now);
            this.master.gain.exponentialRampToValueAtTime(0.0001, endAt);
        } catch (_) {
            this.stop();
            return;
        }
        clearTimeout(this.timer);
        this.timer = setTimeout(() => this.stop(), durationMs + 30);
    }
}

class ThinkingAudioPlayer {
    constructor() {
        this.audio = document.createElement('audio');
        this.audio.preload = 'auto';
        this.playing = false;
        this._generation = 0;
        this._controller = null;
    }

    play(onComplete = null) {
        this.stop(false);
        const generation = ++this._generation;
        this._controller = new AbortController();
        fetch(`${API}/tts/thinking`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({}),
            signal: this._controller.signal,
        })
            .then(res => {
                if (!res.ok) throw new Error('thinking_tts_failed');
                return res.arrayBuffer();
            })
            .then(buffer => {
                if (generation !== this._generation || !buffer || buffer.byteLength === 0) return;
                const bytes = new Uint8Array(buffer);
                let binary = '';
                const chunkSize = 0x8000;
                for (let i = 0; i < bytes.length; i += chunkSize) {
                    binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize));
                }
                this.audio.src = 'data:audio/mp3;base64,' + btoa(binary);
                this.audio.currentTime = 0;
                this.playing = true;
                const done = () => {
                    if (generation !== this._generation) return;
                    this.playing = false;
                    this.audio.onended = null;
                    this.audio.onerror = null;
                    if (typeof onComplete === 'function') onComplete();
                };
                this.audio.onended = done;
                this.audio.onerror = done;
                const p = this.audio.play();
                if (p) p.catch(done);
            })
            .catch(() => {
                if (generation !== this._generation) return;
                this.playing = false;
                if (typeof onComplete === 'function') onComplete();
            });
    }

    stop(complete = true) {
        this._generation += 1;
        try { this._controller?.abort(); } catch (_) {}
        this._controller = null;
        this.playing = false;
        try { this.audio.pause(); } catch (_) {}
        this.audio.onended = null;
        this.audio.onerror = null;
        this.audio.removeAttribute('src');
        try { this.audio.load(); } catch (_) {}
        if (complete && !isListening && !isStreaming && !isAssistantAudioActive()) {
            setJarvisVisualState('idle');
        }
    }

    fadeOut(durationMs = 120) {
        this.stop();
    }
}

function playThinkingSound(requestId = null) {
    const resolvedRequestId = requestId || activeClientRequestId || buildClientRequestId();
    if (thinkingAudioPlayedForRequestId === resolvedRequestId) {
        return thinkingSoundPromise || Promise.resolve();
    }
    thinkingSoundGeneration += 1;
    clearTimeout(thinkingSoundDelayTimer);
    clearTimeout(thinkingSoundMaxTimer);
    if (!settings.thinkingSounds) {
        thinkingSoundPromise = Promise.resolve();
        return thinkingSoundPromise;
    }

    currentThinkingRequestId = resolvedRequestId;
    thinkingAudioPlayedForRequestId = resolvedRequestId;
    finalTtsQueuedForRequestId = null;
    thinkingSoundPromise = new Promise(resolve => {
        if (
            preStarterPlayer.playing ||
            ttsPlayer?.playing ||
            ttsPlayer?.queue?.length ||
            browserStreamSpeaker?.playing ||
            browserStreamSpeaker?.queue?.length ||
            browserStreamSpeaker?.ttsTextBuffer?.trim?.()
        ) {
            thinkingAudioPlaying = false;
            resolve();
            return;
        }
        thinkingAudioPlaying = true;
        const complete = () => {
            clearTimeout(thinkingSoundMaxTimer);
            thinkingAudioPlaying = false;
            resolve();
        };
        if (thinkingAudioPlayer) {
            thinkingAudioPlayer.play(complete);
        } else if (preStarterPlayer) {
            preStarterPlayer.play(complete);
        } else {
            thinkingAudioPlaying = false;
            resolve();
            return;
        }
        thinkingSoundMaxTimer = setTimeout(() => {
            cancelThinkingSound(false);
            resolve();
        }, 2200);
    });
    return thinkingSoundPromise;
}

function shouldSkipThinkingAudioForText(text) {
    if (thinkingAudioMode !== 'smart') return false;
    const value = String(text || '').trim().toLowerCase();
    if (!value) return thinkingAudioSkipForEmptyTranscript;
    if (thinkingAudioSkipForClarification && /^(?:port waldenet|i'?ll put wald in it)[.!?]*$/.test(value)) {
        return true;
    }
    if (
        thinkingAudioSkipForFastSemantic &&
        /(?:\b(?:create|make)\b.+\bfile\b.+\b(?:write|put|with)\b|\b(?:put|write|add|append)\b.+\b(?:in|to)\s+(?:it|the file|that file)\b)/.test(value)
    ) {
        return true;
    }
    return false;
}

function scheduleThinkingSound(text, requestId = null) {
    clearTimeout(thinkingSoundDelayTimer);
    if (shouldSkipThinkingAudioForText(text)) {
        thinkingSoundPromise = Promise.resolve();
        return thinkingSoundPromise;
    }
    const delay = thinkingAudioMode === 'smart' ? Math.max(0, Number(thinkingAudioMinDelayMs || 0)) : 0;
    if (delay <= 0) {
        return playThinkingSound(requestId);
    }
    const scheduledRequestId = requestId || activeClientRequestId || buildClientRequestId();
    thinkingSoundPromise = new Promise(resolve => {
        thinkingSoundDelayTimer = setTimeout(() => {
            Promise.resolve(playThinkingSound(scheduledRequestId)).finally(resolve);
        }, delay);
    });
    return thinkingSoundPromise;
}

function cancelThinkingSound(resetRequestTracking = true) {
    thinkingSoundGeneration += 1;
    clearTimeout(thinkingSoundDelayTimer);
    clearTimeout(thinkingSoundMaxTimer);
    currentThinkingRequestId = null;
    if (resetRequestTracking) thinkingAudioPlayedForRequestId = null;
    thinkingAudioPlaying = false;
    finalTtsQueuedForRequestId = null;
    thinkingSoundPromise = Promise.resolve();
    if (thinkingAudioPlayer) thinkingAudioPlayer.stop();
    if (preStarterPlayer) preStarterPlayer.stop();
}

function fadeThinkingSound(durationMs = 180) {
    thinkingSoundGeneration += 1;
    clearTimeout(thinkingSoundDelayTimer);
    clearTimeout(thinkingSoundMaxTimer);
    currentThinkingRequestId = null;
    thinkingAudioPlaying = false;
    finalTtsQueuedForRequestId = null;
    thinkingSoundPromise = Promise.resolve();
    if (thinkingAudioPlayer) thinkingAudioPlayer.fadeOut(durationMs);
    if (preStarterPlayer) preStarterPlayer.fadeOut(durationMs);
}

async function waitForThinkingSoundBeforeFinalTts(generationId = null) {
    if (!thinkingAudioFinishBeforeFinalTts || thinkingAudioStopOnFinalTts) {
        fadeThinkingSound(180);
        return;
    }
    const requestId = generationId || activeClientRequestId || currentThinkingRequestId;
    if (!thinkingAudioPlaying || !currentThinkingRequestId) return;
    if (requestId && currentThinkingRequestId !== requestId) return;

    finalTtsQueuedForRequestId = requestId || currentThinkingRequestId;
    const observedGeneration = thinkingSoundGeneration;
    const timeoutMs = Math.max(250, Number(thinkingAudioFinalTtsWaitTimeoutMs || 2500));
    await Promise.race([
        thinkingSoundPromise.catch(() => {}),
        new Promise(resolve => {
            setTimeout(() => {
                if (thinkingSoundGeneration === observedGeneration && thinkingAudioPlaying) {
                    cancelThinkingSound(false);
                }
                resolve();
            }, timeoutMs);
        }),
    ]);
    if (!requestId || finalTtsQueuedForRequestId === requestId) {
        finalTtsQueuedForRequestId = null;
    }
}

function setJarvisVisualState(state) {
    const normalized = ['idle', 'listening', 'thinking', 'speaking', 'interrupted'].includes(state)
        ? state
        : 'idle';
    if (coreVisual) coreVisual.dataset.state = normalized;
}

function stopBrowserSpeech() {
    try {
        if ('speechSynthesis' in window) {
            window.speechSynthesis.cancel();
        }
    } catch (_) {}
    if (ttsBtn) ttsBtn.classList.remove('tts-speaking');
    if (orbContainer) orbContainer.classList.remove('speaking');
    if (orb) orb.setActive(false);
    if (!isListening && !isStreaming) setJarvisVisualState('idle');
}

function isJarvisSpeakingOrStreaming() {
    return !!(
        isStreaming ||
        preStarterPlayer?.playing ||
        thinkingAudioPlayer?.playing ||
        (ttsPlayer && (ttsPlayer.playing || ttsPlayer.queue.length > 0)) ||
        (browserStreamSpeaker && (browserStreamSpeaker.playing || browserStreamSpeaker.queue.length > 0 || browserStreamSpeaker.ttsTextBuffer.trim()))
    );
}

function handleVoiceBargeInSpeechStart() {
    if (bargeInInterruptSent) return;
    bargeInInterruptSent = true;
    interruptCurrentResponse();
    setJarvisVisualState('listening');
}

function interruptCurrentResponse() {
    interruptingForBargeIn = true;
    suppressAutoListenUntil = Date.now() + 800;
    const interruptedSessionId = sessionId;
    const interruptedRequestId = activeClientRequestId;
    invalidateActiveStepUp();
    try { activeStreamController?.abort(); } catch (_) {}
    activeStreamController = null;
    if (interruptedSessionId) {
        fetch(`${API}/chat/interrupt`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                session_id: interruptedSessionId,
                client_request_id: interruptedRequestId,
            }),
        }).catch(() => {});
    }
    cancelThinkingSound();
    stopBrowserSpeech();
    if (browserStreamSpeaker) browserStreamSpeaker.reset();
    if (ttsPlayer) ttsPlayer.stop();
    activeClientRequestId = null;
    removeTypingIndicator();
    document.querySelectorAll('.stream-cursor').forEach(node => node.remove());
    isStreaming = false;
    if (sendBtn) sendBtn.disabled = false;
    if (messageInput) messageInput.disabled = false;
    if (orbContainer) {
        orbContainer.classList.remove('active');
        orbContainer.classList.remove('speaking');
    }
    setJarvisVisualState('interrupted');
    setTimeout(() => {
        if (!isListening && !isStreaming && !isJarvisSpeakingOrStreaming()) setJarvisVisualState('idle');
    }, 320);
}

function formatAckTextForDisplay(text) {
    const trimmed = String(text || '').trim();
    if (!trimmed) return '';
    if (trimmed === 'Verifying your voice') return 'Verifying your voice...';
    return trimmed;
}

function renderAckPlaceholder(contentEl, ackText) {
    if (!contentEl || !ackText) return;
    const textSpan = contentEl.querySelector('.msg-stream-text');
    if (!textSpan) return;
    textSpan.textContent = ackText;
    textSpan.classList.add('stream-placeholder');
    scrollToBottom();
}

function speakWithBrowserTTS(text) {
    const content = (text || '').trim();
    if (!ttsPlayer?.enabled || !content || !('speechSynthesis' in window)) return false;

    stopBrowserSpeech();

    const utterance = new SpeechSynthesisUtterance(content);
    utterance.rate = 1.05;
    utterance.pitch = 1;

    const clearVisuals = () => {
        if (ttsBtn) ttsBtn.classList.remove('tts-speaking');
        if (orbContainer) orbContainer.classList.remove('speaking');
        if (orb) orb.setActive(false);
        if (!isListening && !isStreaming) setJarvisVisualState('idle');
        maybeRestartListening();
    };

    utterance.onstart = () => {
        if (ttsBtn) ttsBtn.classList.add('tts-speaking');
        if (orbContainer) orbContainer.classList.add('speaking');
        if (orb) orb.setActive(true);
        setJarvisVisualState('speaking');
    };
    utterance.onend = clearVisuals;
    utterance.onerror = clearVisuals;

    window.speechSynthesis.speak(utterance);
    return true;
}

class BrowserStreamSpeaker {
    constructor() {
        this.supported = typeof fetch === 'function';
        this.queue = [];
        this.ttsTextBuffer = '';
        this.playing = false;
        this._generation = 0;
        this.currentGenerationId = null;
    }

    reset(generationId = null) {
        this.queue = [];
        this.ttsTextBuffer = '';
        this.playing = false;
        this._generation += 1;
        this.currentGenerationId = generationId || null;
        stopBrowserSpeech();
    }

    pushText(chunk, generationId = null) {
        if (!this.supported || !ttsPlayer?.enabled || !chunk) return;
        if (generationId && activeClientRequestId && generationId !== activeClientRequestId) return;
        if (generationId && this.currentGenerationId && generationId !== this.currentGenerationId) return;
        this.ttsTextBuffer += chunk;
        this._flushReadySegments(false);
    }

    finish() {
        if (!this.supported || !ttsPlayer?.enabled) return;
        this._flushReadySegments(true);
    }

    _flushReadySegments(forceTail) {
        const segments = [];
        let working = this.ttsTextBuffer;
        let boundary = this._findSafeBoundary(working, false);
        while (boundary > 0) {
            const segment = working.slice(0, boundary).trim();
            if (this._isSpeakableSegment(segment)) {
                segments.push(segment);
            }
            working = working.slice(boundary).trimStart();
            boundary = this._findSafeBoundary(working, false);
        }

        if (forceTail) {
            const tail = working.trim();
            if (this._isSpeakableSegment(tail)) {
                segments.push(tail);
                working = '';
            }
        }

        this.ttsTextBuffer = working;

        for (const segment of segments) {
            this.queue.push({
                text: segment,
                generationId: this.currentGenerationId || activeClientRequestId || null,
            });
        }

        if (!this.playing) {
            this._playNext();
        }
    }

    _isSpeakableSegment(segment) {
        const normalized = String(segment || '').trim();
        if (!normalized) return false;
        const words = normalized.match(/\b[\w']+\b/g) || [];
        return words.length >= 5;
    }

    _findSafeBoundary(text, allowTail) {
        const working = String(text || '');
        if (!working) return -1;
        for (let index = 0; index < working.length; index += 1) {
            const ch = working[index];
            const candidate = working.slice(0, index + 1).trim();
            const words = candidate.match(/\b[\w']+\b/g) || [];
            if (ch === '\n' && words.length >= 5) return index + 1;
            if (/[.!?]/.test(ch) && words.length >= 5) return index + 1;
            if (/[;,]/.test(ch) && words.length >= 7) return index + 1;
        }
        if (allowTail) {
            const tail = working.trim();
            const words = tail.match(/\b[\w']+\b/g) || [];
            if (words.length >= 5 && !/\b\w{1,3}$/.test(tail)) {
                return working.length;
            }
        }
        return -1;
    }

    async _playNext() {
        if (!this.supported || !ttsPlayer?.enabled) {
            this.playing = false;
            return;
        }
        if (this.playing) return;

        this.playing = true;
        const generation = this._generation;

        while (this.queue.length > 0) {
            if (generation !== this._generation) break;
            const next = this.queue.shift();
            if (!next?.text) continue;
            await this._synthesizeAndEnqueue(next.text, next.generationId, generation);
        }

        if (generation !== this._generation) {
            this.playing = false;
            return;
        }
        this.playing = false;
        if (!isListening && !isStreaming && !isAssistantAudioActive()) setJarvisVisualState('idle');
        maybeRestartListening();
    }

    async _synthesizeAndEnqueue(text, generationId, speakerGeneration) {
        try {
            const res = await fetch(`${API}/tts`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text }),
            });
            if (!res.ok) return;
            const buffer = await res.arrayBuffer();
            if (speakerGeneration !== this._generation) return;
            if (generationId && this.currentGenerationId && generationId !== this.currentGenerationId) return;
            const bytes = new Uint8Array(buffer);
            let binary = '';
            const chunkSize = 0x8000;
            for (let i = 0; i < bytes.length; i += chunkSize) {
                binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize));
            }
            if (binary && ttsPlayer) {
                ttsPlayer.enqueue(btoa(binary), generationId || this.currentGenerationId || null);
            }
        } catch (_) {
            // TTS failure should not block the text response.
        }
    }
}

/* ================================================================
   TTS AUDIO PLAYER (Text-to-Speech Queue System)
   ================================================================

   HOW THE TTS QUEUE WORKS — EXPLAINED FOR LEARNERS
   -------------------------------------------------
   When TTS is enabled, the backend doesn't send one giant audio file.
   Instead, it sends many small base64-encoded MP3 *chunks* as part of
   the SSE stream (one chunk per sentence or phrase). This approach has
   two advantages:
     1. Audio starts playing before the full response is generated
        (lower latency — the user hears the first sentence immediately).
     2. Each chunk is small, so there's no long download wait.

   The TTSPlayer works like a conveyor belt:
     - enqueue() adds a new audio chunk to the end of the queue.
     - _playLoop() picks up chunks one by one and plays them.
     - When a chunk finishes playing (audio.onended), the loop moves
       to the next chunk.
     - When the queue is empty and no more chunks are arriving, playback
       stops and the orb goes back to idle.

   WHY A SINGLE <audio> ELEMENT?
   iOS Safari has strict autoplay policies — it only allows audio
   playback from a user-initiated event. By reusing one <audio> element
   that was "unlocked" during a user gesture, all subsequent plays
   through that same element are allowed. Creating new Audio() objects
   each time would trigger autoplay blocks on iOS.

   ================================================================ */
class TTSPlayer {
    /**
     * Creates a new TTSPlayer instance.
     *
     * Properties:
     *   queue    — Array of base64 audio strings waiting to be played.
     *   playing  — True if the play loop is currently running.
     *   enabled  — True if the user has toggled TTS on (via the speaker button).
     *   stopped  — True if playback was forcibly stopped (e.g., new chat).
     *              This prevents queued audio from playing after a stop.
     *   audio    — A single persistent <audio> element reused for all playback.
     */
    constructor() {
        this.queue = [];
        this.playing = false;
        this.enabled = true;   // TTS on by default
        this.stopped = false;
        this.currentGenerationId = null;
        this.audio = document.createElement('audio');
        this.audio.preload = 'auto';
    }

    /**
     * unlock() — "Warms up" the audio element so browsers (especially iOS
     * Safari) allow subsequent programmatic playback.
     *
     * This should be called during a user gesture (e.g., clicking "Send").
     *
     * It does two things:
     *   1. Plays a tiny silent WAV file on the <audio> element, which
     *      tells the browser "the user initiated audio playback."
     *   2. Creates a brief AudioContext oscillator at zero volume — this
     *      unlocks the Web Audio API context on iOS (a separate lock from
     *      the <audio> element).
     *
     * After this, the browser treats subsequent .play() calls on the same
     * <audio> element as user-initiated, even if they happen in an async
     * callback (like our SSE stream handler).
     */
    unlock() {
        // A minimal valid WAV file (44-byte header + 2 bytes of silence)
        const silentWav = 'data:audio/wav;base64,UklGRigAAABXQVZFZm10IBIAAAABAAEARKwAAIhYAQACABAAAABkYXRhAgAAAAEA';
        this.audio.src = silentWav;
        const p = this.audio.play();
        if (p) p.catch(() => {});
        try {
            // Create a Web Audio context and play a zero-volume oscillator for <1ms
            const ctx = new (window.AudioContext || window.webkitAudioContext)();
            const g = ctx.createGain();
            g.gain.value = 0;
            const o = ctx.createOscillator();
            o.connect(g);
            g.connect(ctx.destination);
            o.start(0);
            o.stop(ctx.currentTime + 0.001);
            setTimeout(() => ctx.close(), 200);
        } catch (_) {}
    }

    /**
     * enqueue(base64Audio) — Adds a base64-encoded MP3 chunk to the
     * playback queue.
     *
     * @param {string} base64Audio - The base64 string of the MP3 audio data.
     *
     * If TTS is disabled or playback has been force-stopped, the chunk
     * is silently discarded. Otherwise it's pushed onto the queue.
     * If the play loop isn't already running, we kick it off.
     */
    enqueue(base64Audio, generationId = null) {
        if (!this.enabled || this.stopped) return;
        if (generationId && this.currentGenerationId && generationId !== this.currentGenerationId) return;
        const resolvedGenerationId = generationId || this.currentGenerationId || null;
        this.queue.push({ b64: base64Audio, generationId: resolvedGenerationId });
        if (!this.playing) this._playLoop();
    }

    /**
     * stop() — Immediately halts all audio playback and clears the queue.
     *
     * Called when:
     *   - The user starts a "New Chat"
     *   - The user toggles TTS off while audio is playing
     *   - We need to reset before a new streaming response
     *
     * It also removes visual indicators (CSS classes on the TTS button,
     * the orb container, and deactivates the orb animation).
     */
    stop() {
        this.stopped = true;
        cancelThinkingSound();
        this._loopId = (this._loopId || 0) + 1;
        this.audio.onended = null;
        this.audio.onerror = null;
        this.audio.pause();
        this.audio.removeAttribute('src');
        this.audio.load();                        // Fully resets the audio element
        this.queue = [];                           // Discard any pending audio chunks
        this.playing = false;
        this.currentGenerationId = null;
        if (ttsBtn) ttsBtn.classList.remove('tts-speaking');
        if (orbContainer) orbContainer.classList.remove('speaking');
        if (orb) orb.setActive(false);
        if (typeof this.onPlaybackComplete === 'function') this.onPlaybackComplete();   // AI stopped — maybe restart mic
    }

    /**
     * reset() — Stops playback AND clears the "stopped" flag so new
     * audio can be enqueued again.
     *
     * Called at the beginning of each new message send. Increments _loopId
     * so any in-flight _playLoop exits immediately.
     */
    reset(generationId = null) {
        this.stop();
        this.stopped = false;
        this.currentGenerationId = generationId || null;
        this._loopId = (this._loopId || 0) + 1;   // Supersede in-flight play loop
    }

    /**
     * _playLoop() — The internal playback engine. Processes the queue
     * one chunk at a time in a while-loop.
     *
     * WHY THE LOOP ID (_loopId)?
     * If stop() is called and then a new stream starts, there could be
     * two concurrent _playLoop() calls — the old one (still awaiting a
     * Promise) and the new one. The loop ID lets us detect when a loop
     * has been superseded: each invocation gets a unique ID, and if the
     * ID changes mid-loop (because a new loop started), the old loop
     * exits gracefully. This prevents double-playback or stale loops.
     *
     * VISUAL INDICATORS:
     * While playing, we add CSS classes 'tts-speaking' (to the button)
     * and 'speaking' (to the orb container) for visual feedback. These
     * are removed when the queue is drained or playback is stopped.
     */
    async _playLoop() {
        if (this.playing) return;
        this.playing = true;
        this._loopId = (this._loopId || 0) + 1;
        const myId = this._loopId;

        // Activate visual indicators: button glow + orb animation
        if (ttsBtn) ttsBtn.classList.add('tts-speaking');
        if (orbContainer) orbContainer.classList.add('speaking');
        if (orb) orb.setActive(true);
        setJarvisVisualState('speaking');

        // Process queued audio chunks one at a time
        while (this.queue.length > 0) {
            if (this.stopped || myId !== this._loopId) break;  // Exit if stopped or superseded
            const item = this.queue.shift();                    // Take the next chunk from the front
            if (!item) continue;
            if (item.generationId && this.currentGenerationId && item.generationId !== this.currentGenerationId) continue;
            try {
                await waitForThinkingSoundBeforeFinalTts(item.generationId);
                if (this.stopped || myId !== this._loopId) break;
                await this._playB64(item.b64);                  // Wait for it to finish playing
            } catch (e) {
                console.warn('TTS segment error:', e);
            }
        }

        // If another loop took over, don't touch the shared state
        if (myId !== this._loopId) {
            this.playing = false;   // Allow new loop to start
            return;
        }
        this.playing = false;
        // Deactivate visual indicators
        if (ttsBtn) ttsBtn.classList.remove('tts-speaking');
        if (orbContainer) orbContainer.classList.remove('speaking');
        if (orb) orb.setActive(false);
        if (!isListening && !isStreaming) setJarvisVisualState('idle');
        // Notify when playback is fully complete (for auto-restart listening)
        if (typeof this.onPlaybackComplete === 'function') this.onPlaybackComplete();
    }

    /**
     * _playB64(b64) — Plays a single base64-encoded MP3 chunk.
     *
     * @param {string} b64 - Base64-encoded MP3 audio data.
     * @returns {Promise<void>} Resolves when the audio finishes playing
     *                          (or errors out).
     *
     * Sets the <audio> element's src to a data URL and calls .play().
     * Returns a Promise that resolves on 'ended' or 'error', so the
     * _playLoop() can await it and move to the next chunk.
     */
    _playB64(b64) {
        return new Promise(resolve => {
            stopBrowserSpeech();
            this.audio.src = 'data:audio/mp3;base64,' + b64;
            const done = () => { resolve(); };
            this.audio.onended = done;   // Normal completion
            this.audio.onerror = done;   // Error — resolve anyway so the loop continues
            const p = this.audio.play();
            if (p) p.catch(done);        // Handle play() rejection (e.g., autoplay block)
        });
    }
}

/* ================================================================
   INITIALIZATION
   ================================================================ */
async function init() {
    if (!chatMessages || !messageInput) {
        console.error('[JARVIS] Required DOM elements (chat-messages, message-input) not found.');
        return;
    }
    loadSettings();
    ttsPlayer = new TTSPlayer();
    browserStreamSpeaker = new BrowserStreamSpeaker();
    thinkingAudioPlayer = new ThinkingAudioPlayer();
    ttsPlayer.onPlaybackComplete = maybeRestartListening;   // Auto-restart mic when TTS finishes
    if (ttsBtn) ttsBtn.classList.add('tts-active');   // Show TTS as on by default
    setGreeting();
    initOrb();
    await fetchRuntimeVoiceConfig();
    initSpeech();
    preStarterPlayer = new PreStarterPlayer();
    setJarvisVisualState('idle');
    checkHealth();
    startSystemMetricsPolling();
    consumeLauncherBootstrapToken().catch(() => {});
    refreshFaceAuthStatus().catch(() => {});
    startReminderPolling();
    bindEvents();
    bindModeSwitchSwipe();
    startHudClock();
    setMode(currentMode);   // Sync mode slider, labels, and activity toggle
    autoResizeInput();
}

function startHudClock() {
    if (!hudTime) return;
    const update = () => {
        hudTime.textContent = new Date().toLocaleTimeString([], {
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
        });
    };
    update();
    setInterval(update, 1000);
}

function pct(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return null;
    return Math.max(0, Math.min(100, number));
}

function setText(selector, value) {
    const el = document.querySelector(selector);
    if (el) el.textContent = value;
}

function setMetricHistory(name, value) {
    const number = pct(value);
    if (number === null || !metricHistory[name]) return;
    metricHistory[name].push(number);
    if (metricHistory[name].length > 8) metricHistory[name].shift();
    const bars = document.querySelectorAll(`[data-metric-graph="${name}"] i`);
    const values = metricHistory[name];
    bars.forEach((bar, index) => {
        const fallback = values[values.length - 1] || 5;
        const resolved = values[index - Math.max(0, bars.length - values.length)] ?? fallback;
        bar.style.height = `${Math.max(10, resolved)}%`;
    });
}

function setRing(name, value) {
    const resolved = pct(value);
    const ring = document.querySelector(`[data-ring="${name}"]`);
    if (ring) ring.style.setProperty('--value', resolved === null ? 0 : resolved);
    const valueEl = document.querySelector(`[data-metric-value="${name}"]`);
    if (valueEl) valueEl.textContent = resolved === null ? '--' : `${Math.round(resolved)}%`;
}

function deriveHealth(metrics) {
    const cpu = pct(metrics?.cpu?.percent);
    const memory = pct(metrics?.memory?.percent);
    const disk = pct(metrics?.disk?.percent);
    const values = [cpu, memory, disk].filter(v => v !== null);
    if (!values.length) return null;
    const worstLoad = Math.max(...values);
    return Math.max(0, Math.round(100 - (worstLoad * 0.55)));
}

function renderSystemMetrics(metrics) {
    if (!metrics || typeof metrics !== 'object') return;

    const health = deriveHealth(metrics);
    setText('[data-metric-value="health"]', health === null ? 'Unavailable' : `${health}%`);
    setText('[data-metric-sub="health"]', health === null ? 'Waiting for metrics' : health > 72 ? 'Optimal' : health > 48 ? 'Degraded' : 'Attention');
    setMetricHistory('health', health);

    const cpu = pct(metrics.cpu?.percent);
    setRing('cpu', cpu);
    setText('[data-metric-main="cpu"]', cpu === null ? 'Unavailable' : `${cpu.toFixed(1)}%`);
    const freq = metrics.cpu?.frequency_mhz ? `${(metrics.cpu.frequency_mhz / 1000).toFixed(2)} GHz` : 'Frequency unavailable';
    const cores = metrics.cpu?.physical_cores && metrics.cpu?.logical_cores
        ? `${metrics.cpu.physical_cores} cores / ${metrics.cpu.logical_cores} threads`
        : 'Cores unavailable';
    setText('[data-metric-sub="cpu"]', `${freq} • ${cores}`);
    setMetricHistory('cpu', cpu);

    const memory = pct(metrics.memory?.percent);
    setRing('memory', memory);
    setText('[data-metric-main="memory"]', memory === null ? 'Unavailable' : `${memory.toFixed(1)}%`);
    setText('[data-metric-sub="memory"]', metrics.memory?.used_label && metrics.memory?.total_label ? `${metrics.memory.used_label} / ${metrics.memory.total_label}` : 'RAM unavailable');
    setMetricHistory('memory', memory);

    const disk = pct(metrics.disk?.percent);
    setText('[data-metric-main="storage"]', disk === null ? 'Unavailable' : `${disk.toFixed(1)}%`);
    setText('[data-metric-sub="storage"]', metrics.disk?.used_label && metrics.disk?.total_label ? `${metrics.disk.used_label} / ${metrics.disk.total_label} • ${metrics.disk.filesystem || 'Unknown'}` : 'Disk unavailable');
    const diskBar = document.querySelector('[data-metric-bar="storage"]');
    if (diskBar) diskBar.style.width = `${disk === null ? 0 : disk}%`;
    setMetricHistory('storage', disk);

    setText('[data-metric-main="network"]', metrics.network?.recv_rate_label || 'Measuring');
    setText('[data-metric-sub="network"]', `Connection: ${metrics.connection?.status || 'Unknown'}`);
    setText('[data-network-down]', metrics.network?.recv_rate_label || '--');
    setText('[data-network-up]', metrics.network?.sent_rate_label || '--');

    const battery = metrics.battery || {};
    setText('[data-metric-main="battery"]', battery.available && battery.percent !== null ? `${battery.percent}%` : 'Unavailable');
    setText('[data-metric-sub="battery"]', battery.status || 'Power unknown');
    setText('[data-side-power]', battery.available && battery.percent !== null ? `${battery.percent}%` : (battery.status || 'Unknown'));

    const temperature = metrics.temperature || {};
    const temperatureText = temperature.available && temperature.celsius !== null ? `${temperature.celsius}C` : 'Unavailable';
    setText('[data-metric-main="temperature"]', temperatureText);
    setText('[data-metric-sub="temperature"]', temperature.label || 'Sensor unavailable');
    setText('[data-side-temperature]', temperatureText);

    const protection = metrics.protection || {};
    setText('[data-metric-main="protection"]', protection.status || 'Unknown');
    setText('[data-metric-sub="protection"]', protection.detail || 'Status unknown');
    setText('[data-side-protection]', protection.status || 'Unknown');

    const connection = metrics.connection || {};
    setText('[data-metric-main="connection"]', connection.status || 'Unknown');
    setText('[data-metric-sub="connection"]', connection.available ? 'Network probe complete' : 'Checking');
    setText('[data-side-connection]', connection.status || 'Unknown');
}

function startSystemMetricsPolling() {
    if (systemMetricsPollTimer) clearInterval(systemMetricsPollTimer);
    const poll = async () => {
        try {
            const res = await fetch(`${API}/system/metrics`, { cache: 'no-store' });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            renderSystemMetrics(await res.json());
        } catch (err) {
            setText('[data-metric-value="health"]', 'Unavailable');
            setText('[data-metric-sub="health"]', 'Metrics endpoint unavailable');
        }
    };
    poll();
    systemMetricsPollTimer = setInterval(poll, 3000);
}

function loadSettings() {
    try {
        const s = localStorage.getItem(SETTINGS_KEY);
        if (s) {
            const parsed = JSON.parse(s);
            settings = { ...DEFAULT_SETTINGS, ...parsed };
            if (!Object.prototype.hasOwnProperty.call(parsed, 'thinkingSounds') && toggleThinkingSounds) {
                settings.thinkingSounds = !!toggleThinkingSounds.checked;
            }
        } else if (toggleThinkingSounds) {
            settings.thinkingSounds = !!toggleThinkingSounds.checked;
        }
        const savedMode = localStorage.getItem(MODE_STORAGE_KEY);
        if (savedMode === 'jarvis') {
            currentMode = savedMode;
        }
        if (toggleAutoActivity) toggleAutoActivity.checked = settings.autoOpenActivity;
        if (toggleAutoSearch) toggleAutoSearch.checked = settings.autoOpenSearchResults;
        if (toggleThinkingSounds) toggleThinkingSounds.checked = settings.thinkingSounds;
        if (toggleVoiceGuard) toggleVoiceGuard.checked = false;
        updateVoiceprintStatus();
    } catch (_) {
        updateVoiceprintStatus();
    }
}

function startReminderPolling() {
    if (reminderPollTimer) clearInterval(reminderPollTimer);
    const poll = async () => {
        try {
            const res = await fetch(`${API}/reminders/due`);
            if (!res.ok) return;
            const data = await res.json();
            const reminders = Array.isArray(data?.reminders) ? data.reminders : [];
            for (const reminder of reminders) {
                const text = `Reminder: ${reminder.message}`;
                showToast(text, 9000);
                playReminderTts(text);
            }
        } catch (_) {}
    };
    poll();
    reminderPollTimer = setInterval(poll, 15000);
}

async function playReminderTts(text) {
    if (!ttsPlayer || !ttsPlayer.enabled || !text) return;
    try {
        const res = await fetch(`${API}/tts`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text }),
        });
        if (!res.ok) return;
        const buffer = await res.arrayBuffer();
        const bytes = new Uint8Array(buffer);
        let binary = '';
        const chunkSize = 0x8000;
        for (let i = 0; i < bytes.length; i += chunkSize) {
            binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize));
        }
        ttsPlayer.reset();
        ttsPlayer.unlock();
        if (preStarterPlayer) preStarterPlayer.unlock();
        ttsPlayer.enqueue(btoa(binary));
    } catch (_) {}
}

function saveSettings() {
    try {
        localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
    } catch (_) {}
}

/* ================================================================
   GREETING
   ================================================================ */

/**
 * setGreeting() — Sets the welcome screen title based on the current
 * time of day.
 *
 * Time ranges:
 *   00:00–11:59 → "Good morning."
 *   12:00–16:59 → "Good afternoon."
 *   17:00–21:59 → "Good evening."
 *   22:00–23:59 → "Burning the midnight oil?" (a fun late-night touch)
 *
 * This is called on page load and when starting a new chat.
 */
function setGreeting() {
    const h = new Date().getHours();
    let g = 'Good evening.';
    if (h < 12) g = 'Good morning.';
    else if (h < 17) g = 'Good afternoon.';
    else if (h >= 22) g = 'Burning the midnight oil?';
    if (welcomeTitle) welcomeTitle.textContent = g;
}

function isVisionMode(mode = currentMode) {
    return mode === 'screen' || mode === 'camera';
}

/* ================================================================
   WEBGL ORB INITIALIZATION
   ================================================================ */

/**
 * initOrb() — Creates the animated WebGL orb inside the orbContainer.
 *
 * OrbRenderer is defined in a separate JS file (orb.js). If that file
 * hasn't loaded (e.g., network error), OrbRenderer will be undefined
 * and we skip initialization gracefully.
 *
 * Configuration:
 *   hue: 0                           — The base hue of the orb color
 *   hoverIntensity: 0.3              — How much the orb reacts to mouse hover
 *   backgroundColor: [0.02,0.02,0.06] — Near-black dark blue background (RGB, 0–1 range)
 *
 * The orb's "active" state (pulsing animation) is toggled via
 * orb.setActive(true/false), which we call when TTS starts/stops.
 */
function initOrb() {
    if (typeof OrbRenderer === 'undefined') return;
    try {
        orb = new OrbRenderer(orbContainer, {
            hue: 0,
            hoverIntensity: 0.3,
            backgroundColor: [0.02, 0.02, 0.06]
        });
    } catch (e) { console.warn('Orb init failed:', e); }
}

/* ================================================================
   SPEECH RECOGNITION (Speech-to-Text)
   ================================================================

   SPEECH-TO-TEXT REDESIGN — PC-FIRST, ACCURATE, AUTO-RESTART
   ----------------------------------------------------------
   Design goals:
   1. Work reliably on every PC (Chrome, Edge, etc.)
   2. Accurate transcription — no duplication or concatenation bugs
   3. Auto-restart after AI finishes speaking (stream + TTS complete)
   4. Single utterance per session — clean, predictable behavior

   Flow:
   - User clicks mic → startListening() → recognition.start()
   - User speaks → interim results shown in real time
   - User pauses → final result → brief delay → send message → stopListening()
   - AI responds (stream + TTS) → when TTS queue empty → maybeRestartListening()
   - After SPEECH_RESTART_DELAY_MS → startListening() again

   Chrome sends INCREMENTAL results (each extends the previous). We use
   ONLY the last result to avoid "hello Ja hello jar..." duplication.
   ================================================================ */

/** Detect Safari/iOS — needs different settings for stability */
function isSafariOrIOS() {
    if (typeof navigator === 'undefined') return false;
    const ua = navigator.userAgent || '';
    return /iPad|iPhone|iPod/.test(ua) ||
        (navigator.vendor && navigator.vendor.indexOf('Apple') > -1) ||
        (/Safari/.test(ua) && !/Chrome|Chromium|CriOS/.test(ua));
}

/**
 * initSpeech() — Sets up SpeechRecognition with PC-optimized settings.
 * Uses single-utterance mode (continuous: false) for clean, accurate results.
 */
function initSpeech() {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) {
        if (isBackendSttCaptureMode() && navigator.mediaDevices?.getUserMedia) {
            speechSupportReason = '';
            recognition = null;
            return;
        }
        speechSupportReason = 'Voice input requires Chrome or Edge. This browser does not support speech recognition.';
        if (micBtn) micBtn.title = speechSupportReason;
        return;
    }

    recognition = new SR();

    /* PC: single utterance, interim results for real-time feedback. Avoids Chrome incremental bug. */
    /* Safari: no interim (unstable), single utterance. */
    const safariMode = isSafariOrIOS();
    recognition.continuous = false;
    recognition.interimResults = !safariMode;
    recognition.maxAlternatives = 1;
    recognition.lang = 'en-US';

    recognition.onresult = e => {
        if (!e.results || e.results.length === 0) return;
        /* Chrome sends incremental results — each extends the previous. Use ONLY the last. */
        const last = e.results[e.results.length - 1];
        const transcript = (last && last[0]) ? last[0].transcript.trim() : '';
        const isFinal = last && last.isFinal;

        if (speechWidgetText) speechWidgetText.textContent = transcript;
        if (speechWidget) speechWidget.classList.add('visible');

        if (isFinal && transcript) {
            if (isVoiceGuardActive()) {
                const guard = verifyVoiceGuardTranscript(transcript);
                if (guard.verifiedOnly) {
                    pendingSendTranscript = null;
                    showToast('Trusted voice verified for the next few minutes.');
                    clearTimeout(speechSendTimeout);
                    speechSendTimeout = null;
                    stopListening();
                    return;
                }
                if (!guard.allowed) {
                    pendingSendTranscript = null;
                    showToast('Voiceprint verification is required before Jarvis accepts voice commands.');
                    clearTimeout(speechSendTimeout);
                    speechSendTimeout = null;
                    stopListening();
                    return;
                }
                pendingSendTranscript = guard.cleaned;
            } else {
                pendingSendTranscript = transcript;
            }
            clearTimeout(speechSendTimeout);
            speechSendTimeout = setTimeout(async () => {
                await sendPendingVoiceTranscript();
                speechSendTimeout = null;
                stopListening({ discardPending: false });
            }, Math.max(speechSendDelayMs, Math.round(Math.max(0, sttMinRecordSeconds - ((Date.now() - listeningStartedAt) / 1000)) * 1000)));
        } else if (!isFinal) {
            pendingSendTranscript = null;
            clearTimeout(speechSendTimeout);
            speechSendTimeout = null;
        }
    };

    recognition.onstart = () => {
        speechErrorRetryCount = 0;
        speechRestartBackoffUntil = 0;
        isListening = true;
        if (micBtn) micBtn.classList.add('listening');
        if (speechWidget) speechWidget.classList.add('visible');
        setJarvisVisualState('listening');
    };

    recognition.onerror = e => {
        const msg = (e && e.error) ? String(e.error) : '';
        const isPermissionDenied = /denied|not-allowed|permission/i.test(msg);
        const isNoMicrophone = /audio-capture|no-microphone/i.test(msg);
        stopListening({ stopRecognition: false });
        if (isPermissionDenied && micBtn) {
            micBtn.title = 'Microphone access denied. Allow in browser settings.';
            showToast('Microphone access denied. Allow microphone access in browser settings.');
            speechErrorRetryCount = SPEECH_ERROR_MAX_RETRIES;
        } else if (isNoMicrophone && micBtn) {
            micBtn.title = 'No microphone detected. Check Windows input settings.';
            showToast('No microphone detected. Check your Windows input device.');
            speechErrorRetryCount = SPEECH_ERROR_MAX_RETRIES;
        }
        if (!autoListenMode) setJarvisVisualState('idle');
        if (autoListenMode && !isStreaming && speechErrorRetryCount < SPEECH_ERROR_MAX_RETRIES) {
            speechErrorRetryCount++;
            const delayMs = speechRestartDelayMs * speechErrorRetryCount;
            speechRestartBackoffUntil = Date.now() + delayMs;
            maybeRestartListening(delayMs);
        } else if (speechErrorRetryCount >= SPEECH_ERROR_MAX_RETRIES && micBtn) {
            micBtn.title = 'Voice input — click to try again';
        }
    };

    recognition.onend = () => {
        if (pendingSendTranscript) {
            clearTimeout(speechSendTimeout);
            speechSendTimeout = null;
            sendPendingVoiceTranscript();
        } else {
            clearTimeout(speechSendTimeout);
            speechSendTimeout = null;
        }
        if (isListening) {
            stopListening({
                discardPending: false,
                finishCapture: !finishingVoiceCommandCapture,
                stopRecognition: false,
            });
        }
        maybeRestartListening();
    };
}

/**
 * startListening() — Activates the microphone and begins speech recognition.
 *
 * Guards:
 *   - Does nothing if recognition isn't available (unsupported browser).
 *   - Does nothing if we're currently streaming a response (to avoid
 *     accidentally sending a voice message mid-stream).
 */
async function startListening(options = {}) {
    if (!recognition && !isBackendSttCaptureMode()) {
        if (micBtn) micBtn.title = speechSupportReason || 'Voice input is unavailable in this browser.';
        showToast(speechSupportReason || 'Voice input requires Chrome or Edge.');
        return;
    }
    const allowBargeIn = !!options.bargeIn && shouldAllowBackendBargeIn();
    if ((isStreaming || isAssistantAudioActive()) && !allowBargeIn) return;
    if (isListening) return;
    if (isSafariOrIOS() && !safariVoiceHintShown) {
        showToast('Voice works best in Chrome. Safari has limited support.');
        safariVoiceHintShown = true;
    }
    if (isVoiceGuardActive() && !settings.voiceprintFeatures) {
        showToast('Enroll your browser voiceprint before using voice commands.');
        return;
    }
    if (isVoiceGuardActive() && Date.now() > voiceGuardVerifiedUntil) {
        const matched = await verifyBrowserVoiceprint();
        if (!matched || isStreaming || isListening) return;
    }
    isListening = true;
    bargeInListeningMode = allowBargeIn;
    bargeInInterruptSent = false;
    listeningStartedAt = Date.now();
    pendingSendTranscript = null;
    clearTimeout(speechRestartTimeout);
    speechRestartTimeout = null;
    clearTimeout(speechSendTimeout);
    speechSendTimeout = null;
    clearTimeout(voiceMaxRecordTimeout);
    voiceMaxRecordTimeout = null;
    if (micBtn) micBtn.classList.add('listening');
    if (speechWidget) speechWidget.classList.add('visible');
    if (speechWidgetText) speechWidgetText.textContent = '';
    setJarvisVisualState('listening');
    try {
        await beginVoiceCommandCapture();
        voiceMaxRecordTimeout = setTimeout(() => {
            voiceMaxRecordTimeout = null;
            if (isListening) stopListening({ discardPending: false });
        }, Math.round(sttMaxRecordSeconds * 1000));
        if (recognition && !isBackendSttCaptureMode()) {
            recognition.start();
        }
    } catch (err) {
        isListening = false;
        finishVoiceCommandCapture().catch(() => {});
        if (micBtn) micBtn.classList.remove('listening');
        if (speechWidget) speechWidget.classList.remove('visible');
        setJarvisVisualState('idle');
        showToast('Microphone could not start. Allow mic access and use Chrome or Edge.');
        if (isSafariOrIOS()) showToast('Tap the mic to continue voice input.');
    }
}

/**
 * stopListening() — Deactivates the microphone and stops recognition.
 *
 * Called when:
 *   - A final transcript is received (auto-send).
 *   - The user clicks the mic button again (manual toggle off).
 *   - An error occurs.
 *   - The recognition engine stops unexpectedly.
 */
function stopListening(options = {}) {
    const {
        discardPending = true,
        finishCapture = true,
        stopRecognition = true,
    } = options;
    clearTimeout(speechSendTimeout);
    clearTimeout(speechRestartTimeout);
    clearTimeout(voiceMaxRecordTimeout);
    speechRestartTimeout = null;
    speechSendTimeout = null;
    voiceMaxRecordTimeout = null;
    if (discardPending) pendingSendTranscript = null;
    isListening = false;
    bargeInListeningMode = false;
    bargeInInterruptSent = false;
    if (micBtn) micBtn.classList.remove('listening');  // Remove visual highlight
    if (speechWidget) speechWidget.classList.remove('visible');
    if (speechWidgetText) speechWidgetText.textContent = '';
    if (!isStreaming && !isJarvisSpeakingOrStreaming()) setJarvisVisualState('idle');
    if (finishCapture && isBackendSttCaptureMode() && !finishingVoiceCommandCapture && !voiceSendInFlight) {
        if (voiceSpeechDetected || (Date.now() - listeningStartedAt) >= (sttMinRecordSeconds * 1000)) {
            sendCapturedVoiceCommand().catch(() => {});
        } else {
            finishVoiceCommandCapture().catch(() => {});
        }
    } else if (finishCapture && !finishingVoiceCommandCapture && !pendingSendTranscript) {
        finishVoiceCommandCapture().catch(() => {});
    }
    if (stopRecognition && recognition) {
        try { recognition.stop(); } catch (_) {}
    }
}

/**
 * maybeRestartListening() — If autoListenMode is on and the AI response
 * (stream + TTS) is fully complete, restart listening after a short delay.
 * Called from: sendMessage finally block, TTSPlayer.onPlaybackComplete.
 */
function maybeRestartListening(delayMs = speechRestartDelayMs) {
    if (!autoListenMode || (!recognition && !isBackendSttCaptureMode())) return;
    if (voiceSendInFlight) return;
    const busyWithAudioOrStream = isStreaming || isAssistantAudioActive();
    if (busyWithAudioOrStream && !isBackendSttCaptureMode()) return;
    if (Date.now() < suppressAutoListenUntil) return;
    const backoffRemainingMs = Math.max(0, speechRestartBackoffUntil - Date.now());
    const restartDelayMs = busyWithAudioOrStream && isBackendSttCaptureMode()
        ? Math.max(120, backoffRemainingMs)
        : Math.max(delayMs, backoffRemainingMs);
    clearTimeout(speechRestartTimeout);
    speechRestartTimeout = setTimeout(() => {
        speechRestartTimeout = null;
        if (interruptingForBargeIn) return;
        const bargeIn = shouldAllowBackendBargeIn();
        if (
            autoListenMode &&
            !isListening &&
            (bargeIn || !isStreaming) &&
            (recognition || isBackendSttCaptureMode()) &&
            Date.now() >= suppressAutoListenUntil
        ) {
            startListening({ bargeIn });
        }
    }, restartDelayMs);
}

/* ================================================================
   BACKEND HEALTH CHECK
   ================================================================ */

/**
 * checkHealth() — Pings the backend's /health endpoint to determine
 * if the server is running and healthy.
 *
 * Updates the status indicator in the UI:
 *   - Green dot + "Online"  if the server responds with { status: "healthy" }
 *   - Red dot   + "Offline" if the request fails or returns unhealthy
 *
 * Uses AbortSignal.timeout(5000) to avoid waiting forever if the
 * server is down — the request will automatically abort after 5 seconds.
 */
async function checkHealth() {
    try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 5000);
        const r = await fetch(`${API}/health`, { signal: controller.signal });
        clearTimeout(timeoutId);
        const d = await r.json().catch(() => null);
        const ok = d && (d.status === 'healthy' || d.status === 'degraded');
        if (statusDot) statusDot.classList.toggle('offline', !ok);
        if (statusText) statusText.textContent = ok ? 'Online' : 'Offline';
    } catch (e) {
        if (statusDot) statusDot.classList.add('offline');
        if (statusText) statusText.textContent = 'Offline';
        if (typeof console !== 'undefined' && console.warn) console.warn('[Health] Check failed:', e);
    }
}

/**
 * showToast(msg, durationMs) — Brief feedback for errors/status.
 * Auto-dismisses after durationMs (default 5000).
 */
function showToast(msg, durationMs = 5000) {
    if (!toastContainer || !msg) return;
    const el = document.createElement('div');
    el.className = 'toast';
    el.textContent = msg;
    toastContainer.appendChild(el);
    el.offsetHeight;   // Force reflow for animation
    el.classList.add('toast-visible');
    const t = setTimeout(() => {
        el.classList.remove('toast-visible');
        setTimeout(() => el.remove(), 300);
    }, durationMs);
    el.addEventListener('click', () => { clearTimeout(t); el.classList.remove('toast-visible'); setTimeout(() => el.remove(), 300); });
}

/* ================================================================
   EVENT BINDING
   ================================================================
   All user-interaction event listeners are centralized here for
   clarity. This function is called once during init().
   ================================================================ */

/**
 * bindEvents() — Wires up all click, keydown, and input event
 * listeners for the UI.
 */
function bindEvents() {
    // SEND BUTTON — Send the message when clicked; a new send interrupts the current response first.
    if (sendBtn) sendBtn.addEventListener('click', () => { sendMessage(); });

    // ENTER KEY — Send on Enter (but allow Shift+Enter for new lines)
    if (messageInput) messageInput.addEventListener('keydown', e => {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
    });

    // INPUT CHANGE — Auto-resize the textarea and show character count for long messages
    if (messageInput) messageInput.addEventListener('input', () => {
        autoResizeInput();
        const len = messageInput.value.length;
        if (charCount) charCount.textContent = len > 100 ? `${len.toLocaleString()} / 32,000` : '';
    });

    // MIC BUTTON — Toggle speech recognition. When ON: auto mode — listen, stop on send, restart after AI+TTS done.
    if (micBtn) micBtn.addEventListener('click', () => {
        if (isJarvisSpeakingOrStreaming() && !isListening) {
            interruptCurrentResponse();
            autoListenMode = true;
            if (micBtn) {
                micBtn.classList.add('auto-listen');
                micBtn.title = 'Voice input — click to stop auto-listen';
            }
            setTimeout(() => {
                interruptingForBargeIn = false;
                suppressAutoListenUntil = 0;
                startListening();
            }, 120);
            return;
        }
        if (isListening) {
            autoListenMode = false;
            stopListening();
            if (micBtn) micBtn.classList.remove('auto-listen');
        } else {
            autoListenMode = true;
            speechErrorRetryCount = 0;   // Reset retry count on fresh start
            if (micBtn) {
                micBtn.classList.add('auto-listen');
                micBtn.title = 'Voice input — click to stop auto-listen';
            }
            startListening();
        }
    });

    // TTS BUTTON — Toggle text-to-speech on/off
    if (ttsBtn) ttsBtn.addEventListener('click', () => {
        if (ttsPlayer) ttsPlayer.enabled = !ttsPlayer.enabled;
        ttsBtn.classList.toggle('tts-active', ttsPlayer && ttsPlayer.enabled);
        if (ttsPlayer && !ttsPlayer.enabled) ttsPlayer.stop();
        if (ttsPlayer && !ttsPlayer.enabled && browserStreamSpeaker) browserStreamSpeaker.reset();
    });

    // NEW CHAT BUTTON — Reset the conversation
    if (newChatBtn) newChatBtn.addEventListener('click', newChat);

    if (visionToggleBtn) visionToggleBtn.addEventListener('click', () => {
        if (currentMode === 'jarvis') setMode('screen');
        else setMode('jarvis');
    });
    if (btnJarvis) btnJarvis.addEventListener('click', () => setMode('jarvis'));
    if (btnGeneral) btnGeneral.addEventListener('click', () => setMode('jarvis'));
    if (btnRealtime) btnRealtime.addEventListener('click', () => setMode('jarvis'));
    if (btnScreen) btnScreen.addEventListener('click', async () => {
        setMode('screen');
        try { await startScreenPreview(); } catch (err) { showToast(err.message || 'Screen share could not start.'); setMode('jarvis'); }
    });
    if (btnCamera) btnCamera.addEventListener('click', async () => {
        setMode('camera');
        try { await startCameraPreview(); } catch (err) { showToast(err.message || 'Camera could not start.'); setMode('jarvis'); }
    });
    if (modePrevBtn) modePrevBtn.addEventListener('click', () => stepMode(-1));
    if (modeNextBtn) modeNextBtn.addEventListener('click', () => stepMode(1));
    if (cameraPreviewClose) cameraPreviewClose.addEventListener('click', () => setMode('jarvis'));
    if (screenPreviewClose) screenPreviewClose.addEventListener('click', () => setMode('jarvis'));
    if (visionCaptureBtn) visionCaptureBtn.addEventListener('click', async () => {
        try {
            if (currentMode === 'screen') await captureScreenImage();
            if (currentMode === 'camera') await captureCameraImage();
        } catch (err) {
            showToast(err.message || 'Capture failed.');
        }
    });
    visionPresets().forEach(btn => {
        btn.addEventListener('click', () => {
            if (messageInput) {
                messageInput.value = btn.dataset.visionPrompt || '';
                autoResizeInput();
            }
            sendMessage(btn.dataset.visionPrompt || '');
        });
    });

    // QUICK-ACTION CHIPS — Predefined messages on the welcome screen
    // Each chip has a data-msg attribute containing the message to send
    document.querySelectorAll('.chip').forEach(c => {
        c.addEventListener('click', () => { sendMessage(c.dataset.msg); });
    });

    // SEARCH RESULTS WIDGET — Toggle panel open/close from header button; close from panel button
    if (searchResultsToggle) {
        searchResultsToggle.addEventListener('click', () => {
            if (searchResultsWidget) { searchResultsWidget.classList.toggle('open'); updatePanelOverlay(); }
        });
    }
    if (searchResultsClose && searchResultsWidget) {
        searchResultsClose.addEventListener('click', () => { searchResultsWidget.classList.remove('open'); updatePanelOverlay(); });
    }
    // ACTIVITY PANEL — Toggle open/close from header button; close from panel button
    if (activityToggle) {
        activityToggle.addEventListener('click', () => {
            if (activityPanel) { activityPanel.classList.toggle('open'); updatePanelOverlay(); }
        });
    }
    if (activityClose && activityPanel) {
        activityClose.addEventListener('click', () => { activityPanel.classList.remove('open'); updatePanelOverlay(); });
    }
    // Panels close ONLY via their X button — overlay does not close on click
    // SETTINGS
    if (settingsBtn && settingsPanel) {
        settingsBtn.addEventListener('click', () => {
            settingsPanel.classList.toggle('open');
            updatePanelOverlay();
        });
    }
    if (settingsClose && settingsPanel) {
        settingsClose.addEventListener('click', () => {
            settingsPanel.classList.remove('open');
            updatePanelOverlay();
        });
    }
    if (toggleAutoActivity) {
        toggleAutoActivity.addEventListener('change', () => {
            settings.autoOpenActivity = toggleAutoActivity.checked;
            saveSettings();
        });
    }
    if (toggleAutoSearch) {
        toggleAutoSearch.addEventListener('change', () => {
            settings.autoOpenSearchResults = toggleAutoSearch.checked;
            saveSettings();
        });
    }
    if (toggleThinkingSounds) {
        toggleThinkingSounds.addEventListener('change', () => {
            settings.thinkingSounds = toggleThinkingSounds.checked;
            if (!settings.thinkingSounds) cancelThinkingSound();
            saveSettings();
        });
    }
    if (verifyFaceBtn) verifyFaceBtn.addEventListener('click', () => verifyFaceNow().catch(err => showToast(err.message)));
    if (enrollFaceBtn) enrollFaceBtn.addEventListener('click', () => enrollFaceProfile().catch(err => showToast(err.message)));
    if (clearFaceProfileBtn) clearFaceProfileBtn.addEventListener('click', () => clearFaceProfile().catch(err => showToast(err.message)));
}

/**
 * autoResizeInput() — Dynamically adjusts the textarea height to fit
 * its content, up to a maximum of 120px.
 *
 * How it works:
 *   1. Reset height to 'auto' so scrollHeight reflects actual content height.
 *   2. Set height to the smaller of scrollHeight or 120px.
 *   This creates a textarea that grows as the user types but doesn't
 *   take over the whole screen for very long messages.
 */
function autoResizeInput() {
    messageInput.style.height = 'auto';
    messageInput.style.height = Math.min(messageInput.scrollHeight, 120) + 'px';
}

/* ================================================================
   MODE SWITCH (General ↔ Realtime)
   ================================================================
   The app supports two AI modes, each hitting a different backend
   endpoint:
     - "General"  → /chat/stream         (standard LLM pipeline)
     - "Realtime" → /chat/realtime/stream (realtime/low-latency pipeline)

   The mode is purely a UI + routing concern — the frontend logic for
   streaming and rendering is identical for both modes.
   ================================================================ */

/**
 * updatePanelOverlay() — Shows/hides the backdrop overlay when any side panel is open.
 */
function updatePanelOverlay() {
    if (!panelOverlay) return;
    const anyOpen = (activityPanel && activityPanel.classList.contains('open')) ||
        (searchResultsWidget && searchResultsWidget.classList.contains('open')) ||
        (settingsPanel && settingsPanel.classList.contains('open'));
    panelOverlay.classList.toggle('visible', !!anyOpen);
}

/**
 * setMode(mode) — Switches the active mode and updates the UI.
 *
 * @param {string} mode - Either 'general' or 'realtime'.
 *
 * Updates:
 *   - currentMode variable (used when sending messages)
 *   - Button active states (highlights the selected button)
 *   - Slider position (slides the pill indicator left or right)
 */
function setMode(mode) {
    if (mode === 'general' || mode === 'realtime') {
        mode = 'jarvis';
    }
    if (!MODE_ORDER.includes(mode)) {
        mode = 'jarvis';
    }

    currentMode = mode;

    try {
        localStorage.setItem(MODE_STORAGE_KEY, mode);
    } catch (_) {}

    suppressAutoListenUntil = 0;

    if (btnJarvis)   btnJarvis.classList.toggle('active', mode === 'jarvis');
    if (btnGeneral)  btnGeneral.classList.toggle('active', mode === 'general');
    if (btnRealtime) btnRealtime.classList.toggle('active', mode === 'realtime');
    if (btnScreen)   btnScreen.classList.toggle('active', mode === 'screen');
    if (btnCamera)   btnCamera.classList.toggle('active', mode === 'camera');
    if (modeSlider) {
        const index = Math.max(0, MODE_ORDER.indexOf(mode));
        modeSlider.style.transform = `translateX(calc(${index * 100}% + ${index * 2}px))`;
    }
    if (messageInput) {
        messageInput.placeholder = mode === 'screen'
            ? 'Ask about the screen after you share or capture it...'
            : mode === 'camera'
                ? 'Ask about what the camera sees...'
                : 'Ask Jarvis anything...';
    }
    if (visionToggleBtn) {
        visionToggleBtn.classList.remove('mode-screen', 'mode-camera');
        visionToggleBtn.title = 'Turn on screen mode';
        if (mode === 'screen') {
            visionToggleBtn.classList.add('mode-screen');
            visionToggleBtn.title = 'Switch to camera mode';
        } else if (mode === 'camera') {
            visionToggleBtn.classList.add('mode-camera');
            visionToggleBtn.title = 'Return to Jarvis mode';
        }
    }
    // Activity toggle always visible — panel shows flow in all modes
    if (activityToggle) activityToggle.style.display = '';
    updateVisionModeUI();
}

function setVisionStatus(state, detail) {
    if (visionStatusBadge) {
        visionStatusBadge.textContent = state;
        visionStatusBadge.className = 'vision-status-badge';
        visionStatusBadge.classList.add(`is-${String(state || 'idle').toLowerCase()}`);
    }
    if (visionStatusText) {
        visionStatusText.textContent = detail || '';
    }
}

function beginVisionActivity(prompt) {
    if (activityList) {
        activityList.innerHTML = '<div class="activity-empty" id="activity-empty">Processing...</div>';
    }
    if (activityToggle) activityToggle.style.display = '';
    if (activityPanel && settings.autoOpenActivity) {
        activityPanel.classList.add('open');
        updatePanelOverlay();
    }

    appendActivity({ event: 'query_detected', message: prompt });
    appendActivity({ event: 'routing', route: currentMode });
}

/* ================================================================
   NEW CHAT
   ================================================================ */

/**
 * newChat() — Resets the entire conversation to a fresh state.
 *
 * Steps:
 *   1. Stop any playing TTS audio.
 *   2. Clear the session ID (server will create a new one on next message).
 *   3. Clear all messages from the chat container.
 *   4. Re-create and display the welcome screen.
 *   5. Clear the input field and reset its size.
 *   6. Update the greeting text (in case time-of-day changed).
 */
function newChat() {
    if (ttsPlayer) ttsPlayer.stop();
    cancelThinkingSound();
    if (browserStreamSpeaker) browserStreamSpeaker.reset();
    backgroundTaskPolls.forEach(timer => clearInterval(timer));
    backgroundTaskPolls.clear();
    stopScreenPreview();
    stopCameraPreview();
    setChatSessionId(null);
    pendingVisionDataUrl = null;
    lastScreenShareKind = null;
    if (chatMessages) chatMessages.innerHTML = '';
    chatMessages.appendChild(createWelcome());
    messageInput.value = '';
    autoResizeInput();
    setGreeting();
    if (searchResultsWidget) searchResultsWidget.classList.remove('open');
    if (searchResultsToggle) searchResultsToggle.style.display = 'none';
    if (activityPanel) activityPanel.classList.remove('open');
    if (settingsPanel) settingsPanel.classList.remove('open');
    if (activityToggle) activityToggle.style.display = '';
    if (activityList) {
        activityList.innerHTML = '<div class="activity-empty" id="activity-empty">Send a message to see the flow here.</div>';
    }
    updatePanelOverlay();
}

/**
 * createWelcome() — Builds and returns the welcome screen DOM element.
 *
 * @returns {HTMLDivElement} The welcome screen element, ready to be
 *                           appended to the chat container.
 *
 * The welcome screen includes:
 *   - A decorative SVG icon
 *   - A time-based greeting (same logic as setGreeting)
 *   - A subtitle prompt ("How may I assist you today?")
 *   - Quick-action chip buttons with predefined messages
 *
 * The chip buttons get their own click listeners here because they
 * are dynamically created (not present in the original HTML).
 */
function createWelcome() {
    const div = document.createElement('div');
    div.className = 'welcome-screen';
    div.id = 'welcome-screen';
    div.setAttribute('aria-hidden', 'true');
    return div;
}

/* ================================================================
   MESSAGE RENDERING
   ================================================================
   These functions build the chat message DOM elements. Each message
   consists of:
     - An avatar circle ("J" for Jarvis, "U" for user)
     - A body containing a label (name + mode) and the content text

   The structure mirrors common chat UIs (Slack, Discord, ChatGPT).
   ================================================================ */

/**
 * isUrlLike(str) — True if the string looks like a URL or encoded path (not a readable title/snippet).
 */
function isUrlLike(str) {
    if (!str || typeof str !== 'string') return false;
    const s = str.trim();
    return s.length > 40 && (/^https?:\/\//i.test(s) || /\%2f|\%3a|\.com\/|\.org\//i.test(s));
}

/**
 * friendlyUrlLabel(url) — Short, readable label for a URL (domain + path hint) for display.
 */
function friendlyUrlLabel(url) {
    if (!url || typeof url !== 'string') return 'View source';
    try {
        const u = new URL(url.startsWith('http') ? url : 'https://' + url);
        const host = u.hostname.replace(/^www\./, '');
        const path = u.pathname !== '/' ? u.pathname.slice(0, 20) + (u.pathname.length > 20 ? '…' : '') : '';
        return path ? host + path : host;
    } catch (_) {
        return url.length > 40 ? url.slice(0, 37) + '…' : url;
    }
}

/**
 * truncateSnippet(text, maxLen) — Truncate to maxLen with ellipsis, one line for card content.
 */
function truncateSnippet(text, maxLen) {
    if (!text || typeof text !== 'string') return '';
    const t = text.trim();
    if (t.length <= maxLen) return t;
    return t.slice(0, maxLen).trim() + '…';
}

/**
 * renderSearchResults(payload) — Fills the right-side search results widget
 * with Tavily data (query, AI answer, and source cards). Filters junk, truncates
 * content, and shows friendly URL labels so layout stays clean and responsive.
 */
function renderSearchResults(payload) {
    if (!payload) return;
    if (searchResultsQuery) searchResultsQuery.textContent = (payload.query || '').trim() || 'Search';
    if (searchResultsAnswer) searchResultsAnswer.textContent = (payload.answer || '').trim() || '';
    if (!searchResultsList) return;
    searchResultsList.innerHTML = '';
    const results = payload.results || [];
    const maxContentLen = 220;
    for (const r of results) {
        let title = (r.title || '').trim();
        let content = (r.content || '').trim();
        const url = (r.url || '').trim();
        if (isUrlLike(title)) title = friendlyUrlLabel(url) || 'Source';
        if (!title) title = friendlyUrlLabel(url) || 'Source';
        if (isUrlLike(content)) content = '';
        content = truncateSnippet(content, maxContentLen);
        const score = r.score != null ? Math.round((r.score || 0) * 100) : null;
        const card = document.createElement('div');
        card.className = 'search-result-card';
        const urlDisplay = url ? escapeHtml(friendlyUrlLabel(url)) : '';
        const hrefSafe = safeUrlForHref(url);
        const urlMarkup = urlDisplay
            ? (hrefSafe ? `<a href="${hrefSafe}" target="_blank" rel="noopener" class="card-url" title="${escapeAttr(url)}">${urlDisplay}</a>` : `<span class="card-url">${urlDisplay}</span>`)
            : '';
        card.innerHTML = `
            <div class="card-title">${escapeHtml(title)}</div>
            ${content ? `<div class="card-content">${escapeHtml(content)}</div>` : ''}
            ${urlMarkup}
            ${score != null ? `<div class="card-score">Relevance: ${escapeHtml(String(score))}%</div>` : ''}`;
        searchResultsList.appendChild(card);
    }
}

/**
 * safeUrlForHref(url) — Returns URL only if it's http/https; otherwise empty.
 * Prevents XSS via javascript:, data:, or other dangerous protocols.
 */
function safeUrlForHref(url) {
    if (!url || typeof url !== 'string') return '';
    const u = url.trim();
    if (u.startsWith('https://') || u.startsWith('http://')) return escapeAttr(u);
    return '';
}

/**
 * escapeAttr(str) — Escape for HTML attribute (e.g. href, title).
 * Order matters: & first, then ", <, >.
 */
function escapeAttr(str) {
    if (typeof str !== 'string') return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/"/g, '&quot;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

/** Step labels for activity events (left panel). */
const ACTIVITY_STEPS = {
    query_detected:      { step: 1, label: 'Query detected' },
    decision:            { step: 2, label: 'Brain decision' },
    routing:             { step: 3, label: 'Route selected' },
    streaming_started:   { step: 4, label: 'Streaming response' },
    task_started:        { step: 4, label: 'Working' },
    task_completed:      { step: 5, label: 'Done' },
    vision_capture_started: { step: 4, label: 'Capture started' },
    vision_capture_ready:   { step: 5, label: 'Capture ready' },
    vision_analyzing:       { step: 6, label: 'Vision analyzing' },
    vision_complete:        { step: 7, label: 'Vision complete' },
    extracting_query:    { step: 0, label: 'Extracting query' },
    searching_web:       { step: 0, label: 'Searching web' },
    search_completed:    { step: 0, label: 'Search completed' },
    context_retrieved:   { step: 0, label: 'Context retrieved' },
    first_chunk:         { step: 5, label: 'Core responded' },
};

/**
 * appendActivity(activity) — Appends an activity event to the left panel.
 * Structured with step numbers, icons, and clear hierarchy.
 */
function appendActivity(activity) {
    if (!activityList || !activity) return;
    const item = document.createElement('div');
    item.className = 'activity-item';
    item.setAttribute('data-event', activity.event || '');
    const stepInfo = ACTIVITY_STEPS[activity.event] || { step: 0, label: activity.event || 'Activity', icon: 'dot' };
    let detail = '';
    if (activity.event === 'query_detected') {
        detail = activity.message || '';
    } else if (activity.event === 'decision') {
        const ms = activity.elapsed_ms;
        const timing = ms != null ? ` (Cortex: ${ms < 1000 ? ms + ' ms' : (ms / 1000).toFixed(2) + ' s'})` : '';
        detail = `${(activity.query_type || '?').charAt(0).toUpperCase() + (activity.query_type || '').slice(1)} — ${activity.reasoning || ''}${timing}`;
        if (activity.query_type === 'general') item.classList.add('route-general');
        if (activity.query_type === 'realtime') item.classList.add('route-realtime');
    } else if (activity.event === 'routing') {
        detail = `→ ${(activity.route || '?').charAt(0).toUpperCase() + (activity.route || '').slice(1)}`;
        if (activity.route === 'general') item.classList.add('route-general');
        if (activity.route === 'realtime') item.classList.add('route-realtime');
        if (activity.route === 'screen') item.classList.add('route-screen');
        if (activity.route === 'camera') item.classList.add('route-camera');
    } else if (activity.event === 'streaming_started') {
        detail = `Generating via ${(activity.route || '?').charAt(0).toUpperCase() + (activity.route || '').slice(1)}`;
        if (activity.route === 'general') item.classList.add('route-general');
        if (activity.route === 'realtime') item.classList.add('route-realtime');
        if (activity.route === 'screen') item.classList.add('route-screen');
        if (activity.route === 'camera') item.classList.add('route-camera');
    } else if (activity.event === 'task_started') {
        detail = activity.message || 'Jarvis is working on it.';
        item.classList.add('route-general');
    } else if (activity.event === 'task_completed') {
        detail = activity.message || 'Task completed.';
        item.classList.add('route-general');
    } else if (activity.event === 'vision_capture_started') {
        detail = activity.message || 'Preparing a fresh capture.';
        item.classList.add(currentMode === 'camera' ? 'route-camera' : 'route-screen');
    } else if (activity.event === 'vision_capture_ready') {
        detail = activity.message || 'A new image is ready for analysis.';
        item.classList.add(currentMode === 'camera' ? 'route-camera' : 'route-screen');
    } else if (activity.event === 'vision_analyzing') {
        detail = activity.message || 'Sending the image to Jarvis vision.';
        item.classList.add(currentMode === 'camera' ? 'route-camera' : 'route-screen');
    } else if (activity.event === 'vision_complete') {
        detail = activity.message || 'Vision response received.';
        item.classList.add(currentMode === 'camera' ? 'route-camera' : 'route-screen');
    } else if (activity.event === 'first_chunk') {
        const ms = activity.elapsed_ms;
        detail = ms != null ? `Core responded in ${ms < 1000 ? ms + ' ms' : (ms / 1000).toFixed(2) + ' s'}` : 'Response started';
        if (activity.route === 'general') item.classList.add('route-general');
        if (activity.route === 'realtime') item.classList.add('route-realtime');
        if (activity.route === 'screen') item.classList.add('route-screen');
        if (activity.route === 'camera') item.classList.add('route-camera');
    } else if (activity.event === 'extracting_query') {
        detail = activity.message || 'Parsing your question for search...';
        item.classList.add('activity-sub');
    } else if (activity.event === 'searching_web') {
        detail = activity.message || (activity.query ? `Query: "${activity.query}"` : 'Scanning Pulse...');
        item.classList.add('activity-sub', 'route-realtime');
    } else if (activity.event === 'search_completed') {
        detail = activity.message || 'Search completed';
        item.classList.add('activity-sub', 'route-realtime');
    } else if (activity.event === 'context_retrieved') {
        detail = activity.message || 'Knowledge base ready';
        item.classList.add('activity-sub', 'route-general');
    } else {
        detail = activity.message || (typeof activity === 'object' ? JSON.stringify(activity) : String(activity));
    }
    const stepNum = stepInfo.step ? `<span class="activity-step">${stepInfo.step}</span>` : '';
    item.innerHTML = `
        <div class="activity-event">${stepNum}${escapeHtml(stepInfo.label)}</div>
        <div class="activity-detail">${escapeHtml(detail || '')}</div>`;
    const emptyEl = activityList.querySelector('.activity-empty');
    if (emptyEl) emptyEl.style.display = 'none';
    activityList.appendChild(item);
    activityList.scrollTop = activityList.scrollHeight;
}

/**
 * escapeHtml(str) — Escapes & < > " ' for safe insertion into HTML.
 */
function escapeHtml(str) {
    if (typeof str !== 'string') return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

/**
 * hideWelcome() — Removes the welcome screen from the DOM.
 *
 * Called before adding the first message, since the welcome screen
 * should disappear once a conversation begins.
 */
function hideWelcome() {
    const w = document.getElementById('welcome-screen');
    if (w) w.remove();
}

/**
 * addMessage(role, text) — Creates and appends a chat message bubble.
 *
 * @param {string} role - Either 'user' or 'assistant'. Determines
 *                         styling, avatar letter, and label text.
 * @param {string} text - The message content to display.
 * @returns {HTMLDivElement} The inner content element — returned so
 *                           the caller (sendMessage) can update it
 *                           later during streaming.
 *
 * DOM structure created:
 *   <div class="message user|assistant">
 *     <div class="msg-avatar"><svg>...</svg></div>
 *     <div class="msg-body">
 *       <div class="msg-label">Jarvis (General) | You</div>
 *       <div class="msg-content">...text...</div>
 *     </div>
 *   </div>
 */
/* Inline SVG icons for chat avatars (user = person, assistant = bot). */
const AVATAR_ICON_USER = '<svg class="msg-avatar-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>';
const AVATAR_ICON_ASSISTANT = '<svg class="msg-avatar-icon" viewBox="0 0 64 64" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><circle cx="32" cy="32" r="27"/><circle cx="32" cy="32" r="19"/><circle cx="32" cy="32" r="8"/><path d="M32 8v14"/><path d="M32 42v14"/><path d="M8 32h14"/><path d="M42 32h14"/><path d="M15.5 15.5l10 10"/><path d="M38.5 38.5l10 10"/><path d="M48.5 15.5l-10 10"/><path d="M25.5 38.5l-10 10"/></svg>';

function addMessage(role, text) {
    hideWelcome();
    const msg = document.createElement('div');
    msg.className = `message ${role}`;

    const avatar = document.createElement('div');
    avatar.className = 'msg-avatar';
    avatar.innerHTML = role === 'assistant' ? AVATAR_ICON_ASSISTANT : AVATAR_ICON_USER;

    const body = document.createElement('div');
    body.className = 'msg-body';

    const label = document.createElement('div');
    label.className = 'msg-label';
    label.textContent = role === 'assistant'
        ? (currentMode === 'jarvis' ? 'Jarvis' : `Jarvis (${formatModeLabel(currentMode)})`)
        : 'You';
    label.dataset.time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

    const content = document.createElement('div');
    content.className = 'msg-content';
    content.textContent = text;

    body.appendChild(label);
    body.appendChild(content);
    msg.appendChild(avatar);
    msg.appendChild(body);
    chatMessages.appendChild(msg);
    scrollToBottom();
    return content;  // Returned so the streaming logic can update it in real time
}

function addImageResultMessage(title, imageUrl) {
    const content = addMessage('assistant', '');
    content.innerHTML = `
        <div class="task-result-card">
            <span class="task-result-label">${escapeHtml(title || 'Your image is ready.')}</span>
            <img src="${escapeAttr(imageUrl)}" alt="${escapeAttr(title || 'Generated image')}" loading="lazy">
        </div>`;
    scrollToBottom();
    return content;
}

function addContentResultMessage(title, bodyText) {
    const content = addMessage('assistant', '');
    content.innerHTML = `
        <div class="task-result-card">
            <span class="task-result-label">${escapeHtml(title || 'Your content is ready.')}</span>
            <div class="task-result-content">${escapeHtml(bodyText || '')}</div>
        </div>`;
    scrollToBottom();
    return content;
}

/**
 * addTypingIndicator() — Shows an animated "..." typing indicator
 * while waiting for the assistant's response to begin streaming.
 *
 * @returns {HTMLDivElement} The content element (containing the dots).
 *
 * This creates a message bubble that looks like the assistant is
 * typing. It's removed once actual content starts arriving.
 * The three <span> elements inside .typing-dots are animated via CSS
 * to create the bouncing dots effect.
 */
function addTypingIndicator() {
    hideWelcome();
    const msg = document.createElement('div');
    msg.className = 'message assistant';
    msg.id = 'typing-msg';               // ID so we can find and remove it later

    const avatar = document.createElement('div');
    avatar.className = 'msg-avatar';
    avatar.innerHTML = AVATAR_ICON_ASSISTANT;

    const body = document.createElement('div');
    body.className = 'msg-body';

    const label = document.createElement('div');
    label.className = 'msg-label';
    label.textContent = currentMode === 'jarvis' ? 'Jarvis' : `Jarvis (${formatModeLabel(currentMode)})`;
    label.dataset.time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

    const content = document.createElement('div');
    content.className = 'msg-content';
    content.innerHTML = '<span class="msg-stream-text">...</span>';

    body.appendChild(label);
    body.appendChild(content);
    msg.appendChild(avatar);
    msg.appendChild(body);
    chatMessages.appendChild(msg);
    scrollToBottom();
    return content;
}

/**
 * removeTypingIndicator() — Removes the typing indicator from the DOM.
 *
 * Called when:
 *   - The first token of the response arrives (replaced by real content).
 *   - An error occurs (replaced by an error message).
 */
function removeTypingIndicator() {
    const t = document.getElementById('typing-msg');
    if (t) t.remove();
}

/**
 * scrollToBottom() — Scrolls the chat container to show the latest message.
 *
 * Uses requestAnimationFrame so the scroll runs after the browser has
 * laid out newly added content (typing indicator, "Thinking...", or
 * streamed chunks). Without this, scroll can happen before layout and
 * the user would have to scroll manually to see new content.
 */
function scrollToBottom() {
    requestAnimationFrame(() => {
        chatMessages.scrollTop = chatMessages.scrollHeight;
    });
}

function formatModeLabel(mode) {
    if (mode === 'jarvis') return 'Jarvis';
    if (mode === 'general') return 'Jarvis';
    if (mode === 'realtime') return 'Jarvis';
    if (mode === 'screen') return 'Screen';
    if (mode === 'camera') return 'Camera';
    return 'Jarvis';
}

function updateVisionModeUI() {
    const isVision = currentMode === 'screen' || currentMode === 'camera';
    if (visionPanel) visionPanel.hidden = true;

    if (!isVision) {
        stopScreenPreview();
        stopCameraPreview();
        pendingVisionDataUrl = null;
        if (visionPreview) visionPreview.hidden = true;
        if (visionVideo) visionVideo.hidden = true;
        if (visionPlaceholder) visionPlaceholder.hidden = false;
        setVisionStatus('Idle', 'Screen and camera access are off.');
        return;
    }

    if (visionPanelTitle) {
        visionPanelTitle.textContent = currentMode === 'screen'
            ? 'Screen Mode'
            : 'Camera Mode';
    }

    if (visionCaptureBtn) {
        if (currentMode === 'screen') {
            visionCaptureBtn.textContent = screenStream ? 'Capture Screen Frame' : 'Start Screen Share';
        } else {
            visionCaptureBtn.textContent = cameraStream ? 'Capture Camera Frame' : 'Start Camera';
        }
    }

    if (currentMode === 'screen') {
        if (cameraStream) stopCameraPreview();
        setVisionStatus(
            screenStream ? (pendingVisionDataUrl ? 'Ready' : 'Live') : 'Idle',
            screenStream
                ? (pendingVisionDataUrl
                    ? `Live ${describeDisplaySurface(lastScreenShareKind)} preview is on. The latest captured frame is ready to analyze.`
                    : `Live ${describeDisplaySurface(lastScreenShareKind)} preview is on. Jarvis will answer from the current shared screen frame.`)
                : 'Jarvis is not looking at your screen yet. Choose Entire Screen in the share picker if you want your full desktop, not just this Jarvis tab.'
        );
    } else {
        if (screenStream) stopScreenPreview();
        setVisionStatus(
            cameraStream ? (pendingVisionDataUrl ? 'Ready' : 'Live') : 'Idle',
            cameraStream
                ? (pendingVisionDataUrl
                    ? 'Captured camera frame ready. Jarvis can answer from what the camera just saw.'
                    : 'Camera preview is live. Jarvis will use your camera frame when you capture or send a question in Camera mode.')
                : 'Camera is off until you start it.'
        );
    }

}

function handleServerActions(actions) {
    if (!actions) return;

    if (Array.isArray(actions)) {
        actions.forEach(action => {
            if (!action || typeof action !== 'object') return;
            const type = action.type || action.action;
            if (type === 'open_url') {
                const url = action.url || action.href;
                if (!url) return;
                if (action.internal_browser && typeof appendActivity === 'function') {
                    appendActivity({ event: 'task_started', message: action.title || `Opening ${url}` });
                }
                try { window.open(url, '_blank', 'noopener'); } catch (_) {}
                return;
            }
            if (type === 'open_content') {
                addContentResultMessage(action.title || 'Content ready.', action.text || action.body || '');
                return;
            }
            if (type === 'open_image') {
                const imageUrl = action.url || action.src;
                if (imageUrl) addImageResultMessage(action.title || 'Image ready.', imageUrl);
                return;
            }
            if (type === 'play_media') {
                const mediaUrl = action.url || action.src;
                if (mediaUrl) {
                    try { window.open(mediaUrl, '_blank', 'noopener'); } catch (_) {}
                }
                return;
            }
            if (type === 'download_file') {
                const url = action.url || action.href;
                if (!url) return;
                const link = document.createElement('a');
                link.href = url;
                link.download = action.filename || '';
                link.rel = 'noopener';
                document.body.appendChild(link);
                link.click();
                link.remove();
                return;
            }
            if (type === 'show_status') {
                appendActivity({ event: 'task_completed', message: action.message || action.status || 'Automation status updated.' });
                return;
            }
            if (type === 'show_task_result') {
                addContentResultMessage(action.title || 'Task result', action.text || action.message || '');
            }
        });
        return;
    }

    if (typeof actions !== 'object') return;

    const urls = [];
    if (Array.isArray(actions.wopens)) urls.push(...actions.wopens.filter(Boolean));
    if (Array.isArray(actions.plays)) urls.push(...actions.plays.filter(Boolean));
    if (Array.isArray(actions.googlesearches)) urls.push(...actions.googlesearches.filter(Boolean));
    if (Array.isArray(actions.youtubesearches)) urls.push(...actions.youtubesearches.filter(Boolean));
    if (Array.isArray(actions.open_url)) urls.push(...actions.open_url.filter(Boolean));
    if (typeof actions.play_media === 'string') urls.push(actions.play_media);
    if (typeof actions.download_file === 'string') urls.push(actions.download_file);

    urls.forEach(url => {
        try {
            window.open(url, '_blank', 'noopener');
        } catch (_) {}
    });

    const images = [];
    if (Array.isArray(actions.images)) images.push(...actions.images);
    if (Array.isArray(actions.open_image)) images.push(...actions.open_image);
    images.forEach(image => {
        if (typeof image === 'string') {
            addImageResultMessage('Image ready.', image);
            return;
        }
        if (image && image.url) {
            addImageResultMessage(image.title || 'Image ready.', image.url);
        }
    });

    const contents = [];
    if (Array.isArray(actions.contents)) contents.push(...actions.contents);
    if (Array.isArray(actions.open_content)) contents.push(...actions.open_content);
    contents.forEach(content => {
        if (typeof content === 'string') {
            addContentResultMessage('Content ready.', content);
            return;
        }
        if (content && (content.text || content.body)) {
            addContentResultMessage(content.title || 'Content ready.', content.text || content.body || '');
        }
    });
}

function handleBackgroundTasks(tasks) {
    if (!Array.isArray(tasks)) return;
    tasks.forEach(task => startBackgroundTaskPolling(task));
}

function startBackgroundTaskPolling(task) {
    const taskId = task && task.task_id;
    if (!taskId || backgroundTaskPolls.has(taskId)) return;

    const startedAt = Date.now();
    appendActivity({
        event: 'task_started',
        message: task.label ? `${task.label} is running in the background.` : 'Background task started.',
    });

    const poll = async () => {
        try {
            const res = await fetch(`${API}/tasks/${encodeURIComponent(taskId)}`);
            if (!res.ok) {
                if (res.status === 404 && Date.now() - startedAt < 15000) return;
                throw new Error(`Task ${taskId} is unavailable.`);
            }

            const data = await res.json();
            if (data.status === 'running') return;

            backgroundTaskPolls.delete(taskId);
            clearInterval(timer);

                if (data.status === 'completed' && data.result) {
                    if (data.result.type === 'image' && data.result.url) {
                        const imageUrl = `${API}${data.result.url}`;
                        const promptText = data.result.prompt ? `Image ready: ${data.result.prompt}` : 'Your generated image is ready.';
                        addImageResultMessage(promptText, imageUrl);
                        appendActivity({ event: 'task_completed', message: 'Image generation completed.' });
                        return;
                    }
                    if (data.result.type === 'content' && data.result.text) {
                        const promptText = data.result.prompt ? `Written content: ${data.result.prompt}` : 'Here is what I wrote.';
                        addContentResultMessage(promptText, data.result.text);
                        appendActivity({ event: 'task_completed', message: 'Content writing completed.' });
                        return;
                    }
                }

            if (data.status === 'failed') {
                addMessage('assistant', data.error || 'A background task failed.');
                appendActivity({ event: 'task_completed', message: data.error || 'Background task failed.' });
            }
        } catch (err) {
            backgroundTaskPolls.delete(taskId);
            clearInterval(timer);
            showToast(err.message || 'Background task polling failed.');
        }
    };

    const timer = setInterval(poll, 1800);
    backgroundTaskPolls.set(taskId, timer);
    poll();
}

function bindModeSwitchSwipe() {
    if (!modeSwitch) return;

    let dragging = false;

    const pickModeFromX = clientX => {
        const rect = modeSwitch.getBoundingClientRect();
        if (!rect.width) return;
        const rawIndex = Math.floor(((clientX - rect.left) / rect.width) * MODE_ORDER.length);
        const clampedIndex = Math.min(MODE_ORDER.length - 1, Math.max(0, rawIndex));
        const nextMode = MODE_ORDER[clampedIndex];
        if (nextMode && nextMode !== currentMode) {
            setMode(nextMode);
        }
    };

    modeSwitch.addEventListener('pointerdown', e => {
        dragging = true;
        pickModeFromX(e.clientX);
    });

    modeSwitch.addEventListener('pointermove', e => {
        if (!dragging) return;
        pickModeFromX(e.clientX);
    });

    const stopDragging = () => {
        dragging = false;
    };

    modeSwitch.addEventListener('pointerup', stopDragging);
    modeSwitch.addEventListener('pointercancel', stopDragging);
    modeSwitch.addEventListener('pointerleave', stopDragging);
}

function stepMode(direction) {
    const currentIndex = MODE_ORDER.indexOf(currentMode);
    if (currentIndex === -1) return;
    const nextIndex = (currentIndex + direction + MODE_ORDER.length) % MODE_ORDER.length;
    setMode(MODE_ORDER[nextIndex]);
}

function describeDisplaySurface(surface) {
    if (surface === 'monitor') return 'entire screen';
    if (surface === 'window') return 'shared window';
    if (surface === 'browser') return 'browser tab';
    return 'shared screen content';
}

async function startCameraPreview() {
    if (cameraStream || !visionVideo) return;
    setVisionStatus('Starting', 'Requesting camera access...');
    cameraStream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: 'environment' } },
        audio: false,
    });
    if (cameraPreviewBody && visionVideo.parentNode !== cameraPreviewBody) {
        cameraPreviewBody.prepend(visionVideo);
    }
    visionVideo.srcObject = cameraStream;
    visionVideo.hidden = false;
    if (cameraPreviewPanel) {
        cameraPreviewPanel.hidden = false;
        cameraPreviewPanel.setAttribute('aria-hidden', 'false');
    }
    if (visionPlaceholder) visionPlaceholder.hidden = true;
    setVisionStatus('Live', 'Camera preview is live. Jarvis only inspects a frame after capture/send.');
}

function stopCameraPreview() {
    if (cameraStream) {
        cameraStream.getTracks().forEach(track => track.stop());
        cameraStream = null;
    }
    if (visionVideo) {
        if (currentMode !== 'screen') {
            visionVideo.srcObject = null;
            visionVideo.hidden = true;
        }
    }
    if (cameraPreviewPanel) {
        cameraPreviewPanel.hidden = true;
        cameraPreviewPanel.setAttribute('aria-hidden', 'true');
    }
    if (currentMode === 'camera') {
        setVisionStatus('Idle', 'Camera is off until you start it again.');
    }
}

async function startScreenPreview() {
    if (screenStream || !visionVideo) return;
    setVisionStatus('Starting', 'Requesting screen share access...');
    screenStream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: false });
    const [track] = screenStream.getVideoTracks();
    lastScreenShareKind = track?.getSettings?.().displaySurface || null;
    if (screenPreviewKind) screenPreviewKind.textContent = describeDisplaySurface(lastScreenShareKind);
    if (track) {
        track.onended = () => {
            stopScreenPreview();
            if (currentMode === 'screen') {
                setMode('jarvis');
            }
        };
    }
    if (screenPreviewBody && visionVideo.parentNode !== screenPreviewBody) {
        screenPreviewBody.prepend(visionVideo);
    }
    visionVideo.srcObject = screenStream;
    visionVideo.hidden = false;
    if (screenPreviewPanel) {
        screenPreviewPanel.hidden = false;
        screenPreviewPanel.setAttribute('aria-hidden', 'false');
    }
    if (visionPreview) visionPreview.hidden = true;
    if (visionPlaceholder) visionPlaceholder.hidden = true;
    setVisionStatus(
        'Live',
        `Live ${describeDisplaySurface(lastScreenShareKind)} preview is on. Jarvis can analyze the current shared screen when you ask.`
    );
}

function stopScreenPreview() {
    if (screenStream) {
        screenStream.getTracks().forEach(track => track.stop());
        screenStream = null;
    }
    lastScreenShareKind = null;
    if (visionVideo) {
        if (currentMode !== 'camera') {
            visionVideo.srcObject = null;
            visionVideo.hidden = true;
        }
    }
    if (screenPreviewPanel) {
        screenPreviewPanel.hidden = true;
        screenPreviewPanel.setAttribute('aria-hidden', 'true');
    }
}

function captureFrameFromVideo(video) {
    const canvas = document.createElement('canvas');
    canvas.width = video.videoWidth || 1280;
    canvas.height = video.videoHeight || 720;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL('image/png');
}

function snapshotActiveVisionStream() {
    if (currentMode === 'screen' && screenStream && visionVideo) {
        return captureFrameFromVideo(visionVideo);
    }
    if (currentMode === 'camera' && cameraStream && visionVideo) {
        return captureFrameFromVideo(visionVideo);
    }
    return null;
}

async function playVisionTts(text) {
    if (!ttsPlayer || !ttsPlayer.enabled || !text) return;
    suppressAutoListenUntil = Date.now() + 4000;
    if (isListening) stopListening();

    try {
        const res = await fetch(`${API}/tts`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text }),
        });
        if (!res.ok) return;
        const buffer = await res.arrayBuffer();
        const bytes = new Uint8Array(buffer);
        let binary = '';
        const chunkSize = 0x8000;
        for (let i = 0; i < bytes.length; i += chunkSize) {
            binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize));
        }
        ttsPlayer.reset();
        ttsPlayer.unlock();
        ttsPlayer.enqueue(btoa(binary));
    } catch (_) {}
}

async function captureScreenImage() {
    appendActivity({ event: 'vision_capture_started', message: 'Preparing the live shared-screen preview.' });
    if (!screenStream) {
        setVisionStatus('Capturing', 'Choose what to share. Pick Entire Screen if you want Jarvis to see your whole desktop.');
        await startScreenPreview();
    }
    await new Promise(resolve => setTimeout(resolve, 250));
    pendingVisionDataUrl = captureFrameFromVideo(visionVideo);
    if (visionPreview) {
        visionPreview.src = pendingVisionDataUrl;
        visionPreview.hidden = false;
    }
    if (visionVideo) visionVideo.hidden = false;
    if (visionPlaceholder) visionPlaceholder.hidden = true;
    appendActivity({
        event: 'vision_capture_ready',
        message: `Fresh frame from your live ${describeDisplaySurface(lastScreenShareKind)} preview is ready.`,
    });
    setVisionStatus(
        'Ready',
        `Captured a frame from your live ${describeDisplaySurface(lastScreenShareKind)} preview. Jarvis is waiting for your prompt.`
    );
}

async function captureCameraImage() {
    if (!cameraStream) {
        await startCameraPreview();
        await new Promise(resolve => setTimeout(resolve, 250));
    }
    appendActivity({ event: 'vision_capture_started', message: 'Capturing a still frame from the live camera preview.' });
    setVisionStatus('Capturing', 'Capturing the current camera frame...');
    pendingVisionDataUrl = captureFrameFromVideo(visionVideo);
    if (visionPreview) {
        visionPreview.src = pendingVisionDataUrl;
        visionPreview.hidden = false;
    }
    if (visionPlaceholder) visionPlaceholder.hidden = true;
    appendActivity({ event: 'vision_capture_ready', message: 'Camera frame captured and ready.' });
    setVisionStatus('Ready', 'Camera frame captured. Send your prompt when ready.');
}

async function sendVisionMessage(textOverride) {
    const rawText = (textOverride || messageInput.value).trim();
    const text = rawText || (currentMode === 'screen'
        ? 'Briefly explain the main thing visible on the shared screen. Keep it short and skip minor UI details.'
        : 'Briefly explain the main thing visible in the camera view. Keep it short.');
    if (isStreaming) interruptCurrentResponse();

    beginVisionActivity(text);

    try {
        if (currentMode === 'screen' && !pendingVisionDataUrl) {
            await captureScreenImage();
        } else if (currentMode === 'camera' && !pendingVisionDataUrl) {
            await captureCameraImage();
        }
    } catch (err) {
        setVisionStatus('Error', err.message || 'Capture failed.');
        showToast(err.message || 'Capture failed.');
        return;
    }

    if (!pendingVisionDataUrl) {
        setVisionStatus('Error', 'Capture an image first.');
        showToast('Capture an image first.');
        return;
    }

    const liveSnapshot = snapshotActiveVisionStream();
    if (liveSnapshot) {
        pendingVisionDataUrl = liveSnapshot;
        if (visionPreview) {
            visionPreview.src = pendingVisionDataUrl;
            visionPreview.hidden = false;
        }
    }

    messageInput.value = '';
    autoResizeInput();
    charCount.textContent = '';
    addMessage('user', text);
    addTypingIndicator();
    const clientRequestId = buildClientRequestId();
    isStreaming = true;
    stopBrowserSpeech();
    if (browserStreamSpeaker) browserStreamSpeaker.reset(clientRequestId);
    if (ttsPlayer) { ttsPlayer.reset(clientRequestId); ttsPlayer.unlock(); }
    if (preStarterPlayer) preStarterPlayer.unlock();
    scheduleThinkingSound(text, clientRequestId);
    setJarvisVisualState('thinking');
    maybeRestartListening(120);
    const controller = new AbortController();
    activeStreamController = controller;
    activeClientRequestId = clientRequestId;
    appendActivity({
        event: 'vision_analyzing',
        message: currentMode === 'screen'
            ? `Jarvis is analyzing the captured ${describeDisplaySurface(lastScreenShareKind)} now.`
            : 'Jarvis is analyzing the captured camera frame.',
    });
    setVisionStatus(
        'Analyzing',
        currentMode === 'screen'
            ? `Jarvis is looking at the captured ${describeDisplaySurface(lastScreenShareKind)} now.`
            : 'Jarvis is using the captured camera frame now.'
    );

    try {
        const imagePayload = pendingVisionDataUrl;
        const res = await fetch(`${API}/chat/jarvis/stream`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: `TTCAMTOKENTT ${text}`,
                imgbase64: imagePayload,
                session_id: sessionId,
                tts: false,
                client_request_id: clientRequestId,
            }),
            signal: controller.signal,
        });
        if (!res.ok) {
            const err = await res.json().catch(() => null);
            throw new Error(err?.detail || `HTTP ${res.status}`);
        }

        if (!res.body) throw new Error('No response body');

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let sseBuffer = '';
        let responseText = '';
        let streamDone = false;

        while (!streamDone) {
            const { done, value } = await reader.read();
            if (done) break;
            sseBuffer += decoder.decode(value, { stream: true });
            const lines = sseBuffer.split('\n');
            sseBuffer = lines.pop();

            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                const data = JSON.parse(line.slice(6));
                if (!isCurrentStreamPayload(data, clientRequestId)) continue;
                if (data.session_id) setChatSessionId(data.session_id);
                if (data.activity) {
                    appendActivity(data.activity);
                    if (
                        data.activity.event === 'interrupted' ||
                        (!thinkingAudioFinishBeforeFinalTts && data.activity.event === 'thinking' && data.activity.state === 'stop')
                    ) {
                        cancelThinkingSound();
                    }
                }
                if (data.error) throw new Error(data.error);
                if (data.chunk) {
                    responseText += data.chunk;
                    if (browserStreamSpeaker) {
                        browserStreamSpeaker.pushText(data.chunk, clientRequestId);
                    }
                }
                if (data.done) {
                    if (browserStreamSpeaker) browserStreamSpeaker.finish();
                    streamDone = true;
                    break;
                }
            }
        }

        removeTypingIndicator();
        addMessage('assistant', responseText || '(No response)');
        appendActivity({
            event: 'vision_complete',
            message: currentMode === 'screen'
                ? `Screen analysis finished for the captured ${describeDisplaySurface(lastScreenShareKind)}.`
                : 'Camera analysis finished.',
        });
        pendingVisionDataUrl = null;
        if (visionPreview) visionPreview.hidden = true;
        if (visionPlaceholder && currentMode === 'screen') visionPlaceholder.hidden = false;
        setVisionStatus(
            'Ready',
            currentMode === 'screen'
                ? `Analysis finished. Capture again if you want Jarvis to inspect a newer ${describeDisplaySurface(lastScreenShareKind)}.`
                : 'Analysis finished. Camera preview can stay live for another question or capture.'
        );
    } catch (err) {
        removeTypingIndicator();
        cancelThinkingSound();
        if (err.name === 'AbortError' && interruptingForBargeIn) {
            return;
        }
        addMessage('assistant', `Something went wrong: ${err.message}`);
        showToast(err.message || 'Vision request failed.');
        setVisionStatus('Error', err.message || 'Vision request failed.');
    } finally {
        if (activeStreamController === controller) activeStreamController = null;
        if (activeClientRequestId === clientRequestId) activeClientRequestId = null;
        isStreaming = false;
        interruptingForBargeIn = false;
        updateVisionModeUI();
        if (!isJarvisSpeakingOrStreaming() && !isListening) setJarvisVisualState('idle');
        maybeRestartListening();
    }
}

/* ================================================================
   SEND MESSAGE + SSE STREAMING
   ================================================================

   HOW SSE (Server-Sent Events) STREAMING WORKS — EXPLAINED FOR LEARNERS
   ----------------------------------------------------------------------
   Instead of waiting for the entire AI response to generate (which
   could take seconds), we use SSE streaming to receive the response
   token-by-token as it's generated. This creates the "typing" effect.

   STANDARD SSE FORMAT:
   The server sends a stream of lines like:
     data: {"chunk": "Hello"}
     data: {"chunk": " there"}
     data: {"chunk": "!"}
     data: {"done": true}

   Each line starts with "data: " followed by a JSON payload. Lines
   are separated by newlines ("\n"). An empty line separates events.

   HOW WE READ THE STREAM:
   1. We POST the user's message to the backend.
   2. The server responds with Content-Type: text/event-stream.
   3. We use res.body.getReader() to read the response body as a
      stream of raw bytes (Uint8Array chunks).
   4. We decode each chunk to text and append it to an SSE buffer.
   5. We split the buffer by newlines and process each complete line.
   6. Lines starting with "data: " are parsed as JSON.
   7. Each JSON payload may contain:
      - chunk: a piece of the text response (appended to the UI)
      - audio: a base64 MP3 segment (enqueued for TTS playback)
      - session_id: the conversation ID (saved for future messages)
      - error: an error message from the server
      - done: true when the response is complete

   WHY NOT USE EventSource?
   The native EventSource API only supports GET requests. We need POST
   (to send the message body), so we use fetch() + manual SSE parsing.

   THE SSE BUFFER:
   Network chunks don't align with SSE line boundaries — one chunk
   might contain half a line, or multiple lines. The sseBuffer variable
   accumulates raw text. We split by '\n', process all complete lines,
   and keep the last (potentially incomplete) line in the buffer for
   the next iteration.

   ================================================================ */

/**
 * sendMessage(textOverride) — Sends a user message and streams the AI response.
 *
 * AUDIO WORKFLOW (minimizes waiting):
 *   Main speech starts directly from the assistant response stream.
 */
async function sendMessage(textOverride, options = {}) {
    if (currentMode === 'screen' || currentMode === 'camera') {
        return sendVisionMessage(textOverride);
    }

    // Step 1: Get the message text, trimming whitespace
    const text = (textOverride || messageInput.value).trim();
    if (!text) return;  // Ignore empty messages
    if (isStreaming) interruptCurrentResponse();

    if (await handleLocalWakeOrSleep(text)) {
        messageInput.value = '';
        autoResizeInput();
        charCount.textContent = '';
        return;
    }

    // Step 2: Clear the input field immediately (responsive UX)
    messageInput.value = '';
    autoResizeInput();
    charCount.textContent = '';

    // Step 3: Display the user's message and show typing indicator
    addMessage('user', text);
    addTypingIndicator();

    const clientRequestId = buildClientRequestId();

    // Step 4: Mark this request as active.
    isStreaming = true;
    if (orbContainer) orbContainer.classList.add('active');

    // Step 5: Reset TTS for this new response and unlock audio (iOS)
    stopBrowserSpeech();
    if (browserStreamSpeaker) browserStreamSpeaker.reset(clientRequestId);
    if (ttsPlayer) { ttsPlayer.reset(clientRequestId); ttsPlayer.unlock(); }
    if (preStarterPlayer) preStarterPlayer.unlock();
    cancelThinkingSound();
    scheduleThinkingSound(text, clientRequestId);
    setJarvisVisualState('thinking');
    maybeRestartListening(120);

    // Step 6: Choose the endpoint based on the current mode
    const endpoint = '/chat/jarvis/stream';

    // Clear activity panel (query_detected only — no duplicate user message)
    if (activityList) {
        activityList.innerHTML = '<div class="activity-empty" id="activity-empty">Processing...</div>';
        if (activityToggle) activityToggle.style.display = '';
        if (activityPanel && settings.autoOpenActivity) { activityPanel.classList.add('open'); updatePanelOverlay(); }
    }

    let firstChunkReceived = false;
    let timeoutId = null;
    const controller = new AbortController();
    activeStreamController = controller;
    activeClientRequestId = clientRequestId;

    try {
        timeoutId = setTimeout(() => controller.abort(), 300000);
        const res = await fetch(`${API}${endpoint}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: text,                                 // The user's message
                session_id: sessionId,                         // null on first message; UUID after that
                tts: false,
                input_source: options.inputSource || 'text',
                voice_audio_base64: options.voiceAudioBase64 || null,
                client_request_id: clientRequestId,
            }),
            signal: controller.signal,
        });
        pendingStepUpToken = '';

        // Handle HTTP errors (4xx, 5xx)
        if (!res.ok) {
            const err = await res.json().catch(() => null);
            throw new Error(err?.detail || `HTTP ${res.status}`);
        }

        // Step 8: Replace the typing indicator with an empty assistant message
        removeTypingIndicator();
        const contentEl = addMessage('assistant', '');
        contentEl.innerHTML = '<span class="msg-stream-text">...</span>';
        scrollToBottom();   // Scroll so placeholder is visible without manual scroll

        // Set up the stream reader and SSE parser
        if (!res.body) throw new Error('No response body');
        const reader = res.body.getReader();       // ReadableStream reader for the response body
        const decoder = new TextDecoder();          // Converts raw bytes (Uint8Array) to strings
        let sseBuffer = '';                         // Accumulates partial SSE lines between chunks
        let fullResponse = '';                      // The complete assistant response text so far
        let cursorEl = null;                        // The blinking "|" cursor shown during streaming

        // Step 9: Read the stream in a loop until it's done
        let streamDone = false;
        while (!streamDone) {
            const { done, value } = await reader.read();
            if (done) break;  // Stream has ended

            // Decode the bytes and add to our SSE buffer
            sseBuffer += decoder.decode(value, { stream: true });

            // Split by newlines to get individual SSE lines
            const lines = sseBuffer.split('\n');

            // The last element might be an incomplete line — keep it in the buffer
            sseBuffer = lines.pop();

            // Process each complete line
            for (const line of lines) {
                // SSE lines that don't start with "data: " are empty lines or comments — skip them
                if (!line.startsWith('data: ')) continue;
                try {
                    // Parse the JSON payload (everything after "data: ")
                    const data = JSON.parse(line.slice(6));
                    if (!isCurrentStreamPayload(data, clientRequestId)) continue;

                    // Save the session ID if the server sends one
                    if (data.session_id) setChatSessionId(data.session_id);

                    // ACTIVITY — Jarvis flow (query detected, decision, routing): show in left panel
                    if (data.activity) {
                        appendActivity(data.activity);
                        if (
                            data.activity.event === 'interrupted' ||
                            (!thinkingAudioFinishBeforeFinalTts && data.activity.event === 'thinking' && data.activity.state === 'stop')
                        ) {
                            cancelThinkingSound();
                        }
                        if (activityToggle) activityToggle.style.display = '';
                        if (activityPanel && settings.autoOpenActivity) { activityPanel.classList.add('open'); updatePanelOverlay(); }
                    }

                    if (data.ack && data.ack.text) {
                        renderAckPlaceholder(contentEl, formatAckTextForDisplay(data.ack.text));
                    }

                    // SEARCH RESULTS — Tavily data (realtime only): show in right-side widget and reveal toggle
                    if (data.search_results) {
                        renderSearchResults(data.search_results);
                        if (searchResultsToggle) searchResultsToggle.style.display = '';
                        if (searchResultsWidget && settings.autoOpenSearchResults) { searchResultsWidget.classList.add('open'); updatePanelOverlay(); }
                    }

                    if (data.actions) {
                        if (
                            data.actions.auth &&
                            (data.actions.auth.step_up_required || data.actions.auth.face_verification_required)
                        ) {
                            cancelThinkingSound();
                            stopBrowserSpeech();
                            if (browserStreamSpeaker) browserStreamSpeaker.reset();
                            if (ttsPlayer) ttsPlayer.stop();
                            showToast('That action needs permission before it can run.');
                            try { controller.abort(); } catch (_) {}
                            streamDone = true;
                            break;
                        }
                        handleServerActions(data.actions);
                    }

                    if (data.background_tasks) {
                        handleBackgroundTasks(data.background_tasks);
                    }

                    // TEXT CHUNK — Append to the displayed response (chunk can be "" in some streams)
                    if ('chunk' in data) {
                        const chunkText = data.chunk || '';
                        // Only treat as "main started" when we get actual content — the initial event
                        // has chunk: "" for session_id
                        if (chunkText && !firstChunkReceived) {
                            firstChunkReceived = true;
                            if (!isJarvisSpeakingOrStreaming()) setJarvisVisualState('idle');
                        }
                        fullResponse += chunkText;
                        const textSpan = contentEl.querySelector('.msg-stream-text');
                        if (textSpan) {
                            textSpan.textContent = fullResponse;
                            textSpan.classList.remove('stream-placeholder');
                        }
                        if (browserStreamSpeaker) {
                            browserStreamSpeaker.pushText(chunkText, clientRequestId);
                        }
                        // Add a blinking cursor at the end (created once, on the first chunk)
                        if (!cursorEl) {
                            cursorEl = document.createElement('span');
                            cursorEl.className = 'stream-cursor';
                            cursorEl.textContent = '|';
                            contentEl.appendChild(cursorEl);
                        }
                        scrollToBottom();
                    }

                    // AUDIO CHUNK — Enqueue for TTS playback
                    // ERROR — The server reported an error in the stream
                    if (data.error) throw new Error(data.error);

                    // DONE — The server signals that the response is complete
                    if (data.done) {
                        if (browserStreamSpeaker) browserStreamSpeaker.finish();
                        streamDone = true;
                        break;
                    }
                } catch (parseErr) {
                    // Ignore JSON parse errors (e.g., partial lines) but re-throw real errors
                    if (parseErr.message && !parseErr.message.includes('JSON'))
                        throw parseErr;
                }
            }
            if (streamDone) break;
        }

        // Step 10: Clean up — remove the blinking cursor
        if (browserStreamSpeaker) browserStreamSpeaker.finish();

        if (cursorEl) cursorEl.remove();
        // If the server sent nothing, show a placeholder
        const textSpan = contentEl.querySelector('.msg-stream-text');
        if (textSpan && !fullResponse) textSpan.textContent = '(No response)';

    } catch (err) {
        clearTimeout(timeoutId);
        if (browserStreamSpeaker) browserStreamSpeaker.reset();
        removeTypingIndicator();
        cancelThinkingSound();
        if (err.name === 'AbortError' && interruptingForBargeIn) {
            return;
        }
        if (activeClientRequestId !== null && activeClientRequestId !== clientRequestId) {
            return;
        }
        const msg = err.name === 'AbortError' ? 'Request timed out. Please try again.' : `Something went wrong: ${err.message}`;
        addMessage('assistant', msg);
        showToast(msg);
    } finally {
        clearTimeout(timeoutId);
        if (activeStreamController === controller) activeStreamController = null;
        if (activeClientRequestId === clientRequestId) activeClientRequestId = null;
        isStreaming = false;
        interruptingForBargeIn = false;
        if (orbContainer) orbContainer.classList.remove('active');
        if (!isJarvisSpeakingOrStreaming() && !isListening) setJarvisVisualState('idle');
        maybeRestartListening();   // Auto-restart mic when stream ends (TTS may still be playing)
    }
}

/* ================================================================
   BOOT — Application Entry Point
   ================================================================
   DOMContentLoaded fires when the HTML document has been fully parsed
   (but before images/stylesheets finish loading). This is the ideal
   time to initialize our app because all DOM elements are available.
   ================================================================ */
document.addEventListener('DOMContentLoaded', init);
