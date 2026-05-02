const ENROLL_API = window.location.origin || 'http://localhost:8000';
const CAPTURE_INTERVAL_MS = 100;
const DUPLICATE_CAPTURE_INTERVAL_MS = 180;
const CAPTURE_FRAME_COUNT = 60;
const CAPTURE_BATCH_SIZE = 6;
const CAPTURE_FRAME_MAX_WIDTH = 480;
const CAPTURE_WARMUP_MS = 500;
const FIRST_ENROLL_BATCH_TIMEOUT_MS = 30000;
const ENROLL_BATCH_TIMEOUT_MS = 15000;
const REDIRECT_DELAY_MS = 700;
const STATUS_MIN_VISIBLE_MS = 350;
const GUIDANCE_ROTATE_MS = 2400;
const PROGRESS_RING_CIRCUMFERENCE = 339.292;

const appEl = document.getElementById('enroll-app');
const videoEl = document.getElementById('camera-video');
const pauseButton = document.getElementById('pause-button');
const resumeButton = document.getElementById('resume-button');
const completeButton = document.getElementById('complete-button');
const restartButton = document.getElementById('restart-button');
const cancelButton = document.getElementById('cancel-button');
const mainStatusEl = document.getElementById('main-status');
const statusCaptionEl = document.getElementById('status-caption');
const topStatusLabelEl = document.getElementById('top-status-label');
const acceptedCountEl = document.getElementById('accepted-count');
const acceptedStatEl = document.getElementById('accepted-stat');
const capturedStatEl = document.getElementById('captured-stat');
const rejectedCountEl = document.getElementById('rejected-count');
const currentStatusEl = document.getElementById('current-status');
const guidanceTextEl = document.getElementById('guidance-text');
const attemptCounterEl = document.getElementById('attempt-counter');
const qualityStatEl = document.getElementById('quality-stat');
const diversityStatEl = document.getElementById('diversity-stat');
const lightingStatEl = document.getElementById('lighting-stat');
const stabilityStatEl = document.getElementById('stability-stat');
const stabilityCaptionEl = document.getElementById('stability-caption');
const progressRingValueEl = document.getElementById('progress-ring-value');
const progressBarFillEl = document.getElementById('progress-bar-fill');
const reactorCanvas = document.getElementById('reactor-canvas');
const statusWaveformCanvas = document.getElementById('status-waveform');
const debugPanelEl = document.getElementById('debug-panel');
const debugStateEl = document.getElementById('debug-state');
const debugRequestIdEl = document.getElementById('debug-request-id');
const debugFramesEl = document.getElementById('debug-frames');
const debugSentEl = document.getElementById('debug-sent');
const debugReceivedEl = document.getElementById('debug-received');
const debugTimeoutEl = document.getElementById('debug-timeout');
const debugHttpStatusEl = document.getElementById('debug-http-status');
const debugReasonEl = document.getElementById('debug-reason');

const stepNodes = {
    cameraOnline: document.querySelector('[data-step="camera-online"]'),
    faceDetected: document.querySelector('[data-step="face-detected"]'),
    qualityCheck: document.querySelector('[data-step="quality-check"]'),
    livenessCheck: document.querySelector('[data-step="liveness-check"]'),
    sampleAccepted: document.querySelector('[data-step="sample-accepted"]'),
};

const guidanceMessages = [
    'Look straight at the camera.',
    'Turn slightly left.',
    'Turn slightly right.',
    'Raise your chin slightly.',
    'Lower your chin slightly.',
    'Move a little closer.',
    'Move slightly farther.',
    'Change expression naturally.',
    'Try a different lighting angle if possible.',
    'Final stability check.',
];

let cameraStream = null;
let activeEnrollmentSessionId = '';
let activeRunId = 0;
let redirectTimerHandle = null;
let guidanceTimerHandle = null;
let animationFrameHandle = 0;
let activeRequestController = null;
let activeRequestTimeoutHandle = null;
let pageClosing = false;
let redirected = false;
let guidanceIndex = 0;
let currentStatusColor = '#00e6ff';
let acceptedSamples = 0;
let rejectedSamples = 0;
let duplicateSamples = 0;
let qualityFailedSamples = 0;
let inconsistentSamples = 0;
let livenessFailedSamples = 0;
let requiredSamples = 20;
let preferredSamples = 20;
let attemptNumber = 0;
let capturedFramesInBurst = 0;
let captureIntervalMs = CAPTURE_INTERVAL_MS;
let latestQualityValue = 0;
let zeroAcceptedBurstStreak = 0;
let backendGuidanceActive = false;
let isPaused = false;
let statusUpdatedAt = 0;
let statusTimerHandle = null;
let pauseWaiter = null;
let completing = false;
let batchRequestCount = 0;
const debugEnabled = new URLSearchParams(window.location.search).get('debug') === '1';
const debugState = {
    state: 'idle',
    requestId: '',
    frames: 0,
    sent: false,
    received: false,
    timeoutMs: 0,
    httpStatus: '-',
    reason: '-',
};

function updateDebugPanel(patch = {}) {
    if (!debugEnabled || !debugPanelEl) return;
    Object.assign(debugState, patch);
    debugPanelEl.hidden = false;
    debugStateEl.textContent = debugState.state || '-';
    debugRequestIdEl.textContent = debugState.requestId || '-';
    debugFramesEl.textContent = String(debugState.frames || 0);
    debugSentEl.textContent = debugState.sent ? 'yes' : 'no';
    debugReceivedEl.textContent = debugState.received ? 'yes' : 'no';
    debugTimeoutEl.textContent = String(debugState.timeoutMs || 0);
    debugHttpStatusEl.textContent = String(debugState.httpStatus || '-');
    debugReasonEl.textContent = String(debugState.reason || '-').slice(0, 80);
}

function setVisualState(nextState) {
    const states = ['idle', 'scanning', 'success', 'warning', 'error'];
    for (const state of states) {
        appEl.classList.toggle(`enroll-state-${state}`, state === nextState);
    }
    currentStatusColor = {
        idle: '#00e6ff',
        scanning: '#00e6ff',
        success: '#37ffb3',
        warning: '#ffcc66',
        error: '#ff4f6a',
    }[nextState] || '#00e6ff';
    updateDebugPanel({ state: nextState });
}

function applyStatus(text, caption, state) {
    setVisualState(state);
    currentStatusEl.textContent = text;
    mainStatusEl.style.opacity = '0';
    mainStatusEl.style.transform = 'translateY(6px)';
    window.setTimeout(() => {
        mainStatusEl.textContent = text;
        mainStatusEl.style.color = currentStatusColor;
        mainStatusEl.style.opacity = '1';
        mainStatusEl.style.transform = 'translateY(0)';
    }, 90);
    statusCaptionEl.textContent = caption;
    topStatusLabelEl.textContent = state === 'idle' ? 'SCANNING' : String(state || 'scanning').toUpperCase();
    statusUpdatedAt = Date.now();
}

async function setStatus(text, caption, state, force = false) {
    if (statusTimerHandle) {
        window.clearTimeout(statusTimerHandle);
        statusTimerHandle = null;
    }
    if (!force) {
        const elapsed = Date.now() - statusUpdatedAt;
        if (elapsed < STATUS_MIN_VISIBLE_MS) {
            await new Promise((resolve) => {
                statusTimerHandle = window.setTimeout(() => {
                    statusTimerHandle = null;
                    resolve();
                }, STATUS_MIN_VISIBLE_MS - elapsed);
            });
        }
    }
    applyStatus(text, caption, state);
}

function setCameraReady(isReady) {
    appEl.classList.toggle('is-camera-ready', Boolean(isReady));
}

function updateCounters() {
    acceptedCountEl.textContent = `Accepted: ${acceptedSamples} / ${preferredSamples}`;
    acceptedStatEl.textContent = `${acceptedSamples} / ${preferredSamples}`;
    capturedStatEl.textContent = `${capturedFramesInBurst} / ${CAPTURE_FRAME_COUNT}`;
    rejectedCountEl.textContent = String(rejectedSamples);
    attemptCounterEl.textContent = String(attemptNumber);
    qualityStatEl.textContent = latestQualityValue > 0 ? latestQualityValue.toFixed(3) : 'Pending';
    completeButton.disabled = completing || acceptedSamples < requiredSamples || redirected || !activeEnrollmentSessionId;
    const progress = preferredSamples > 0 ? Math.min(acceptedSamples / preferredSamples, 1) : 0;
    progressRingValueEl.style.strokeDasharray = String(PROGRESS_RING_CIRCUMFERENCE);
    progressRingValueEl.style.strokeDashoffset = String(PROGRESS_RING_CIRCUMFERENCE * (1 - progress));
    progressBarFillEl.style.width = `${progress * 100}%`;
}

function setStability(value) {
    latestQualityValue = Number(value || 0);
    stabilityCaptionEl.textContent = `Quality: ${latestQualityValue > 0 ? latestQualityValue.toFixed(3) : 'Pending'}`;
    updateCounters();
}

function clearStepStates() {
    Object.values(stepNodes).forEach((node) => {
        if (!node) return;
        node.classList.remove('is-active', 'is-done', 'is-warning', 'is-error');
    });
}

function setStepState(node, state) {
    if (!node) return;
    node.classList.remove('is-active', 'is-done', 'is-warning', 'is-error');
    if (state) node.classList.add(state);
}

function currentStageGuidance() {
    const progressIndex = preferredSamples > 0
        ? Math.floor((acceptedSamples / preferredSamples) * guidanceMessages.length)
        : 0;
    const stageIndex = Math.min(guidanceMessages.length - 1, Math.max(progressIndex, guidanceIndex % guidanceMessages.length));
    return guidanceMessages[stageIndex];
}

function setGuidance(text, backendDriven = false) {
    const nextText = String(text || '').trim();
    if (!nextText) return;
    backendGuidanceActive = backendDriven;
    guidanceTextEl.textContent = nextText;
}

function rotateGuidance() {
    if (!backendGuidanceActive) {
        setGuidance(currentStageGuidance(), false);
    }
    guidanceIndex += 1;
    guidanceTimerHandle = window.setTimeout(rotateGuidance, GUIDANCE_ROTATE_MS);
}

function stopGuidanceRotation() {
    if (guidanceTimerHandle) {
        window.clearTimeout(guidanceTimerHandle);
        guidanceTimerHandle = null;
    }
}

function updateControlVisibility() {
    pauseButton.hidden = isPaused;
    resumeButton.hidden = !isPaused;
}

function pauseEnrollmentUi() {
    isPaused = true;
    updateControlVisibility();
}

function resumeEnrollmentUi() {
    isPaused = false;
    updateControlVisibility();
    if (pauseWaiter) {
        pauseWaiter();
        pauseWaiter = null;
    }
}

async function waitIfPaused(runId) {
    if (!isPaused) return;
    await setStatus('Enrollment paused', 'Resume when you are ready to continue.', 'warning');
    await new Promise((resolve) => {
        pauseWaiter = resolve;
    });
    if (runId !== activeRunId || pageClosing) return;
    await setStatus('Resuming enrollment', 'Restarting secure burst capture.', 'scanning');
}

function resizeReactorCanvas() {
    const dpr = window.devicePixelRatio || 1;
    const rect = reactorCanvas.getBoundingClientRect();
    reactorCanvas.width = Math.max(1, Math.floor(rect.width * dpr));
    reactorCanvas.height = Math.max(1, Math.floor(rect.height * dpr));
    if (statusWaveformCanvas) {
        const waveRect = statusWaveformCanvas.getBoundingClientRect();
        statusWaveformCanvas.width = Math.max(1, Math.floor(waveRect.width * dpr));
        statusWaveformCanvas.height = Math.max(1, Math.floor(waveRect.height * dpr));
    }
}

function drawStatusWaveform(timestamp) {
    if (!statusWaveformCanvas) return;
    const ctx = statusWaveformCanvas.getContext('2d');
    if (!ctx) return;
    const dpr = window.devicePixelRatio || 1;
    const width = statusWaveformCanvas.width / dpr;
    const height = statusWaveformCanvas.height / dpr;
    const time = timestamp / 1000;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);
    ctx.save();
    ctx.translate(0, height / 2);
    ctx.strokeStyle = currentStatusColor;
    ctx.fillStyle = currentStatusColor;
    ctx.shadowColor = currentStatusColor;
    ctx.shadowBlur = 10;
    ctx.globalAlpha = 0.35;
    ctx.beginPath();
    ctx.moveTo(0, 0);
    for (let x = 0; x <= width; x += 10) {
        const y = Math.sin((x * 0.045) + time * 4.4) * 5 + Math.sin((x * 0.11) - time * 2.2) * 3;
        ctx.lineTo(x, y);
    }
    ctx.stroke();
    ctx.globalAlpha = 0.85;
    for (let x = 0; x <= width; x += 22) {
        const y = Math.sin((x * 0.055) + time * 4.1) * 6;
        ctx.beginPath();
        ctx.arc(x, y, 1.8, 0, Math.PI * 2);
        ctx.fill();
    }
    ctx.restore();
}

function animateReactor(timestamp) {
    if (pageClosing) return;
    drawStatusWaveform(timestamp);
    const ctx = reactorCanvas.getContext('2d');
    if (!ctx) return;
    const dpr = window.devicePixelRatio || 1;
    const width = reactorCanvas.width / dpr;
    const height = reactorCanvas.height / dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);

    const cx = width / 2;
    const cy = height / 2;
    const radius = Math.min(width, height) * 0.42;
    const time = timestamp / 1000;
    const color = currentStatusColor;
    const pulse = 0.985 + Math.sin(time * (Math.PI / 0.95)) * 0.018;
    const outerRotation = time * ((Math.PI * 2) / 3.2);
    const innerRotation = -time * ((Math.PI * 2) / 4.4);

    ctx.save();
    ctx.translate(cx, cy);

    for (let glowIndex = 0; glowIndex < 3; glowIndex += 1) {
        ctx.beginPath();
        ctx.strokeStyle = color;
        ctx.globalAlpha = [0.1, 0.2, 0.52][glowIndex];
        ctx.lineWidth = [28, 16, 3.2][glowIndex];
        ctx.shadowColor = color;
        ctx.shadowBlur = [48, 28, 14][glowIndex];
        ctx.arc(0, 0, radius * 0.9 * pulse, 0, Math.PI * 2);
        ctx.stroke();
    }

    ctx.shadowBlur = 0;
    ctx.globalAlpha = 0.72;
    for (let ringIndex = 0; ringIndex < 4; ringIndex += 1) {
        ctx.beginPath();
        ctx.strokeStyle = color;
        ctx.lineWidth = ringIndex === 0 ? 2 : 1;
        ctx.arc(0, 0, radius * (0.62 + ringIndex * 0.14), 0, Math.PI * 2);
        ctx.stroke();
    }

    ctx.globalAlpha = 0.22;
    ctx.lineWidth = 1;
    for (let i = 0; i < 96; i += 1) {
        const angle = (Math.PI * 2 * i) / 96 + outerRotation * 0.08;
        const inner = radius * 1.02;
        const outer = radius * (i % 4 === 0 ? 1.13 : 1.08);
        ctx.beginPath();
        ctx.strokeStyle = color;
        ctx.moveTo(Math.cos(angle) * inner, Math.sin(angle) * inner);
        ctx.lineTo(Math.cos(angle) * outer, Math.sin(angle) * outer);
        ctx.stroke();
    }

    ctx.globalAlpha = 0.72;
    ctx.lineWidth = 1.8;
    ctx.beginPath();
    ctx.strokeStyle = color;
    ctx.arc(0, 0, radius * 0.56, 0, Math.PI * 2);
    ctx.stroke();

    ctx.save();
    ctx.rotate(innerRotation);
    ctx.globalAlpha = 0.94;
    ctx.lineWidth = 2.8;
    ctx.beginPath();
    ctx.strokeStyle = color;
    ctx.shadowColor = color;
    ctx.shadowBlur = 18;
    ctx.arc(0, 0, radius * 0.8, 0.1, Math.PI * 1.58);
    ctx.stroke();
    ctx.restore();

    ctx.save();
    ctx.rotate(outerRotation);
    ctx.lineWidth = 8;
    ctx.globalAlpha = 0.84;
    for (let i = 0; i < 16; i += 1) {
        const start = (Math.PI * 2 * i) / 16;
        const end = start + (Math.PI / 16) * 0.34;
        ctx.beginPath();
        ctx.strokeStyle = color;
        ctx.shadowColor = color;
        ctx.shadowBlur = 18;
        ctx.arc(0, 0, radius * 0.98, start, end);
        ctx.stroke();
    }
    ctx.restore();

    ctx.save();
    ctx.rotate(-outerRotation * 0.55);
    ctx.lineWidth = 3;
    ctx.globalAlpha = 0.7;
    for (let i = 0; i < 10; i += 1) {
        const start = (Math.PI * 2 * i) / 10 + 0.08;
        const end = start + 0.22;
        ctx.beginPath();
        ctx.strokeStyle = color;
        ctx.arc(0, 0, radius * 1.2, start, end);
        ctx.stroke();
    }
    ctx.restore();

    ctx.restore();
    animationFrameHandle = window.requestAnimationFrame(animateReactor);
}

async function waitForVideoReady() {
    if (videoEl.readyState >= 2) return;
    await new Promise((resolve, reject) => {
        const cleanup = () => {
            videoEl.removeEventListener('loadeddata', onReady);
            videoEl.removeEventListener('error', onError);
        };
        const onReady = () => {
            cleanup();
            resolve();
        };
        const onError = () => {
            cleanup();
            reject(new Error('camera_unavailable'));
        };
        videoEl.addEventListener('loadeddata', onReady, { once: true });
        videoEl.addEventListener('error', onError, { once: true });
    });
}

async function startCamera() {
    try {
        setCameraReady(false);
        await setStatus('Initializing camera...', 'Requesting secure camera access.', 'idle', true);
        cameraStream = await navigator.mediaDevices.getUserMedia({
            video: {
                facingMode: 'user',
                width: { ideal: 1280 },
                height: { ideal: 720 },
            },
            audio: false,
        });
        videoEl.srcObject = cameraStream;
        await videoEl.play().catch(() => {});
        await waitForVideoReady();
        setCameraReady(true);
        setStepState(stepNodes.cameraOnline, 'is-done');
        return true;
    } catch (error) {
        const permissionDenied = error && (error.name === 'NotAllowedError' || error.name === 'SecurityError');
        setCameraReady(false);
        await setStatus(
            permissionDenied ? 'Camera permission denied' : 'Camera unavailable',
            permissionDenied ? 'Allow camera access to continue enrollment.' : 'No usable camera stream is available for enrollment.',
            'error',
            true
        );
        return false;
    }
}

async function captureBurstFrames(runId) {
    await new Promise((resolve) => window.setTimeout(resolve, CAPTURE_WARMUP_MS));
    const canvas = document.createElement('canvas');
    const sourceWidth = videoEl.videoWidth || 640;
    const sourceHeight = videoEl.videoHeight || 480;
    const scale = sourceWidth > CAPTURE_FRAME_MAX_WIDTH ? CAPTURE_FRAME_MAX_WIDTH / sourceWidth : 1;
    const width = Math.max(1, Math.round(sourceWidth * scale));
    const height = Math.max(1, Math.round(sourceHeight * scale));
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext('2d', { willReadFrequently: true });
    const frames = [];
    capturedFramesInBurst = 0;
    backendGuidanceActive = false;
    setGuidance(currentStageGuidance(), false);
    updateCounters();

    for (let index = 0; index < CAPTURE_FRAME_COUNT; index += 1) {
        await waitIfPaused(runId);
        if (runId !== activeRunId || pageClosing || redirected) return frames;
        context.drawImage(videoEl, 0, 0, width, height);
        frames.push(canvas.toDataURL('image/jpeg', 0.9).split(',')[1]);
        capturedFramesInBurst = index + 1;
        updateDebugPanel({ frames: frames.length });
        updateCounters();
        if (index < CAPTURE_FRAME_COUNT - 1) {
            await new Promise((resolve) => window.setTimeout(resolve, captureIntervalMs));
        }
    }

    return frames;
}

function stopActiveRequest() {
    if (activeRequestTimeoutHandle) {
        window.clearTimeout(activeRequestTimeoutHandle);
        activeRequestTimeoutHandle = null;
    }
    if (activeRequestController) {
        activeRequestController.abort();
        activeRequestController = null;
    }
}

function scheduleRedirectToLauncher() {
    if (redirected) return;
    redirected = true;
    redirectTimerHandle = window.setTimeout(() => {
        redirectTimerHandle = null;
        window.location.assign('/launcher/');
    }, REDIRECT_DELAY_MS);
}

function resetEnrollmentUi() {
    acceptedSamples = 0;
    rejectedSamples = 0;
    duplicateSamples = 0;
    qualityFailedSamples = 0;
    inconsistentSamples = 0;
    livenessFailedSamples = 0;
    requiredSamples = 20;
    preferredSamples = 20;
    attemptNumber = 0;
    capturedFramesInBurst = 0;
    captureIntervalMs = CAPTURE_INTERVAL_MS;
    latestQualityValue = 0;
    zeroAcceptedBurstStreak = 0;
    backendGuidanceActive = false;
    batchRequestCount = 0;
    activeEnrollmentSessionId = '';
    completing = false;
    clearStepStates();
    if (cameraStream) {
        setStepState(stepNodes.cameraOnline, 'is-done');
    }
    updateCounters();
    diversityStatEl.textContent = 'Low';
    lightingStatEl.textContent = 'Good';
    stabilityStatEl.textContent = 'Pending';
    setStability(0);
    resumeEnrollmentUi();
}

async function postJson(url, body, runId, timeoutMs = 0) {
    stopActiveRequest();
    const controller = new AbortController();
    activeRequestController = controller;
    const requestId = `enroll-${runId}-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
    let didTimeout = false;
    updateDebugPanel({
        requestId,
        sent: false,
        received: false,
        timeoutMs,
        httpStatus: '-',
        reason: '-',
    });
    if (timeoutMs > 0) {
        activeRequestTimeoutHandle = window.setTimeout(() => {
            didTimeout = true;
            controller.abort();
        }, timeoutMs);
    }
    try {
        updateDebugPanel({ sent: true });
        const response = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
            signal: controller.signal,
        });
        if (runId !== activeRunId) {
            return null;
        }
        const payload = await response.json().catch(() => ({}));
        if (runId !== activeRunId) {
            return null;
        }
        if (activeRequestTimeoutHandle) {
            window.clearTimeout(activeRequestTimeoutHandle);
            activeRequestTimeoutHandle = null;
        }
        activeRequestController = null;
        updateDebugPanel({
            received: true,
            httpStatus: response.status,
            reason: payload.reason || payload.guidance || payload.status || '-',
        });
        return payload;
    } catch (error) {
        if (activeRequestTimeoutHandle) {
            window.clearTimeout(activeRequestTimeoutHandle);
            activeRequestTimeoutHandle = null;
        }
        activeRequestController = null;
        if (error && error.name === 'AbortError') {
            if (didTimeout) {
                updateDebugPanel({ reason: 'timeout' });
                throw new Error('request_timeout');
            }
            return null;
        }
        throw error;
    }
}

function batchReasonCount(payload, reason) {
    const reasonCounts = payload?.reason_counts || {};
    return Number(reasonCounts[reason] || 0);
}

function qualityReason(payload) {
    return String(payload?.last_quality?.reason || payload?.last_rejection_reason || '').toLowerCase();
}

function livenessReason(payload) {
    return String(payload?.last_liveness?.reason || payload?.last_rejection_reason || '').toLowerCase();
}

function rejectionReason(payload) {
    return String(payload?.last_rejection_reason || '').toLowerCase();
}

function backendGuidanceForPayload(payload) {
    const reason = qualityReason(payload);
    const liveReason = livenessReason(payload);
    const rejectedReason = rejectionReason(payload);
    const duplicateCount = Number(payload?.duplicate_count || 0);
    const totalDuplicates = Number(payload?.duplicate_rejection_count || duplicateSamples);
    const qualityFailures = Number(payload?.quality_failed_count || 0);
    const livenessFailures = Number(payload?.liveness_failed_count || 0);
    const inconsistent = Number(payload?.inconsistent_count || 0);
    const accepted = Number(payload?.accepted_count || 0);
    const duplicateHigh = duplicateCount >= 2 || totalDuplicates >= Math.max(3, Math.ceil(acceptedSamples / 2));

    if (batchReasonCount(payload, 'no_face') > 0) {
        return { text: 'Center your face inside the circle.', message: 'Center your face', caption: 'Keep your face fully inside the circle.', state: 'warning' };
    }
    if (batchReasonCount(payload, 'multiple_faces') > 0 || batchReasonCount(payload, 'face_count_invalid') > 0) {
        return { text: 'Only one face should be visible.', message: 'One face only', caption: 'Move other faces out of the camera view.', state: 'warning' };
    }
    if (batchReasonCount(payload, 'too_dark') > 0 || reason.includes('too_dark')) {
        return { text: 'Lighting is too low. Move closer to a light source.', message: 'Improve lighting', caption: 'Face a light source before continuing.', state: 'warning' };
    }
    if (batchReasonCount(payload, 'too_bright') > 0 || reason.includes('too_bright')) {
        return { text: 'Too much light. Reduce glare.', message: 'Reduce glare', caption: 'Avoid backlight or screen reflection.', state: 'warning' };
    }
    if (batchReasonCount(payload, 'too_blurry') > 0 || reason.includes('blur') || reason.includes('low_quality')) {
        return { text: 'Hold still. Reduce motion.', message: 'Reduce motion', caption: 'Pause head motion briefly during capture.', state: 'warning' };
    }
    if (batchReasonCount(payload, 'face_too_small') > 0 || reason.includes('small')) {
        return { text: 'Move closer to camera.', message: 'Move closer', caption: 'Your face is too small for strong samples.', state: 'warning' };
    }
    if (duplicateHigh || (duplicateCount > 0 && qualityFailures === 0)) {
        return { text: 'Change angle slightly.', message: 'Change angle', caption: 'Add a small angle change before the next burst.', state: 'warning' };
    }
    if (livenessFailures > 0 || liveReason.includes('static') || liveReason.includes('liveness')) {
        return { text: 'Move naturally.', message: 'Move naturally', caption: 'Use small natural motion while staying centered.', state: 'warning' };
    }
    if (inconsistent > 0 || rejectedReason.includes('inconsistent')) {
        return { text: 'Keep same face, avoid extreme angles.', message: 'Keep centered', caption: 'Use slight angles only, not profile turns.', state: 'warning' };
    }
    if (qualityFailures > 0) {
        return { text: 'Improve lighting and framing.', message: 'Improve quality', caption: 'Fix lighting and framing before the next burst.', state: 'warning' };
    }
    if (accepted > 0 || Number(payload?.accepted_samples || 0) > 0) {
        return { text: 'Good. Continue slight movement.', message: 'Quality: Good', caption: 'The backend is accepting face samples.', state: 'success' };
    }
    const fallback = String(payload?.guidance || currentStageGuidance());
    return { text: fallback, message: fallback, caption: 'Follow the current coverage stage.', state: 'scanning' };
}

function mapGuidanceToStatus(payload) {
    return backendGuidanceForPayload(payload);
}

function applyBatchSteps(payload) {
    const quality = payload?.last_quality || {};
    const liveness = payload?.last_liveness || {};
    const accepted = Number(payload?.accepted_count || 0) > 0;
    const faceCount = Number(quality.face_count || 0);

    setStepState(stepNodes.faceDetected, faceCount === 1 || accepted ? 'is-done' : faceCount > 1 ? 'is-warning' : 'is-error');
    setStepState(stepNodes.qualityCheck, accepted || quality.passed ? 'is-done' : 'is-warning');
    setStepState(stepNodes.livenessCheck, accepted || liveness.is_live ? 'is-done' : 'is-warning');
    setStepState(stepNodes.sampleAccepted, accepted ? 'is-done' : 'is-warning');
}

function applyBatchPayload(payload) {
    acceptedSamples = Number(payload.accepted_samples || acceptedSamples);
    requiredSamples = Number(payload.required_samples || requiredSamples);
    preferredSamples = Number(payload.preferred_samples || preferredSamples);
    rejectedSamples = Number(payload.total_rejected_count ?? (rejectedSamples + Number(payload.rejected_count || 0)));
    duplicateSamples = Number(payload.duplicate_rejection_count ?? (duplicateSamples + Number(payload.duplicate_count || 0)));
    qualityFailedSamples = Number(payload.quality_failed_count_total ?? (qualityFailedSamples + Number(payload.quality_failed_count || 0)));
    inconsistentSamples = Number(payload.inconsistent_rejection_count ?? (inconsistentSamples + Number(payload.inconsistent_count || 0)));
    livenessFailedSamples = Number(payload.liveness_failed_count_total ?? (livenessFailedSamples + Number(payload.liveness_failed_count || 0)));
    setStability(payload.average_similarity_to_centroid || payload.embedding_stability || 0);
    diversityStatEl.textContent = String(payload.diversity || diversityStatEl.textContent || 'Low');
    lightingStatEl.textContent = String(payload.lighting || lightingStatEl.textContent || 'Good');
    stabilityStatEl.textContent = String(payload.stability || stabilityStatEl.textContent || 'Pending');
    if (Number(payload.duplicate_count || 0) > 0 || Number(payload.duplicate_rejection_count || 0) > Math.max(2, acceptedSamples / 2)) {
        captureIntervalMs = DUPLICATE_CAPTURE_INTERVAL_MS;
    } else if (Number(payload.quality_failed_count || 0) === 0 && Number(payload.accepted_count || 0) > 0) {
        captureIntervalMs = CAPTURE_INTERVAL_MS;
    }
    updateCounters();
    const mapped = backendGuidanceForPayload(payload);
    setGuidance(mapped.text, mapped.state === 'warning' || mapped.state === 'error');
    applyBatchSteps(payload);
}

async function completeEnrollment(runId) {
    if (completing || !activeEnrollmentSessionId) return;
    completing = true;
    updateCounters();
    try {
        await setStatus('Completing enrollment...', 'Finalizing the face profile with the backend.', 'scanning');
        const payload = await postJson(`${ENROLL_API}/face/enroll/complete`, {
            enrollment_session_id: activeEnrollmentSessionId,
        }, runId);
        if (!payload || runId !== activeRunId || pageClosing) return;

        acceptedSamples = Number(payload.accepted_samples || acceptedSamples);
        requiredSamples = Number(payload.required_samples || requiredSamples);
        preferredSamples = Number(payload.preferred_samples || preferredSamples);
        updateCounters();
        setStability(payload.embedding_stability || 0);

        if (payload.enrolled) {
            await setStatus('Enrollment complete.', 'Returning to the launcher for face verification.', 'success', true);
            scheduleRedirectToLauncher();
            return;
        }

        completing = false;
        updateCounters();
        await setStatus('Collecting more samples', 'Capture another burst to finish the profile.', 'warning');
    } catch (_error) {
        completing = false;
        updateCounters();
        await setStatus('Backend unavailable', 'The backend could not complete enrollment.', 'error', true);
        restartButton.disabled = false;
    }
}

async function sendBurstBatches(frames, runId) {
    let latestPayload = null;
    let burstAcceptedCount = 0;
    let burstRejectedCount = 0;
    let burstDuplicateCount = 0;
    for (let index = 0; index < frames.length; index += CAPTURE_BATCH_SIZE) {
        await waitIfPaused(runId);
        if (runId !== activeRunId || pageClosing || redirected) return latestPayload;
        const batchNumber = Math.floor(index / CAPTURE_BATCH_SIZE) + 1;
        const totalBatches = Math.ceil(frames.length / CAPTURE_BATCH_SIZE);
        const timeoutMs = batchRequestCount === 0 ? FIRST_ENROLL_BATCH_TIMEOUT_MS : ENROLL_BATCH_TIMEOUT_MS;
        batchRequestCount += 1;
        await setStatus('Processing burst...', `Reviewing batch ${batchNumber} of ${totalBatches}.`, 'scanning');
        const batch = frames.slice(index, index + CAPTURE_BATCH_SIZE);
        const payload = await postJson(`${ENROLL_API}/face/enroll/batch`, {
            enrollment_session_id: activeEnrollmentSessionId,
            frames: batch,
        }, runId, timeoutMs);
        if (!payload || runId !== activeRunId || pageClosing) return latestPayload;
        latestPayload = payload;
        burstAcceptedCount += Number(payload.accepted_count || 0);
        burstRejectedCount += Number(payload.rejected_count || 0);
        burstDuplicateCount += Number(payload.duplicate_count || 0);
        latestPayload.burst_accepted_count = burstAcceptedCount;
        latestPayload.burst_rejected_count = burstRejectedCount;
        latestPayload.burst_duplicate_count = burstDuplicateCount;
        applyBatchPayload(payload);
        if (payload.auto_complete) {
            await completeEnrollment(runId);
            return latestPayload;
        }
        if (
            burstDuplicateCount >= Math.max(3, burstAcceptedCount + 2)
            && Number(payload.quality_failed_count || 0) === 0
            && Number(payload.accepted_count || 0) === 0
        ) {
            captureIntervalMs = DUPLICATE_CAPTURE_INTERVAL_MS;
            latestPayload.guidance = 'Change angle slightly.';
            setGuidance(latestPayload.guidance, true);
            break;
        }
    }
    return latestPayload;
}

function shouldPauseForPoorEnrollment(payload) {
    const burstAccepted = Number(payload?.burst_accepted_count ?? payload?.accepted_count ?? 0);
    if (burstAccepted === 0) {
        zeroAcceptedBurstStreak += 1;
    } else {
        zeroAcceptedBurstStreak = 0;
    }
    const rejectedTooHigh = rejectedSamples > acceptedSamples * 5 && rejectedSamples > 0;
    return rejectedTooHigh || zeroAcceptedBurstStreak >= 3;
}

async function pauseForPoorEnrollmentQuality(runId) {
    pauseEnrollmentUi();
    captureIntervalMs = Math.max(captureIntervalMs, DUPLICATE_CAPTURE_INTERVAL_MS);
    setGuidance('Adjust lighting, center your face, then resume.', true);
    await setStatus(
        'Adjust lighting and framing',
        'Adjust lighting, center your face, then resume.',
        'warning',
        true
    );
    await waitIfPaused(runId);
}

async function burstLoop(runId) {
    try {
        while (!pageClosing && runId === activeRunId && activeEnrollmentSessionId && !redirected) {
            await waitIfPaused(runId);
            if (runId !== activeRunId || pageClosing || !activeEnrollmentSessionId) return;
            attemptNumber += 1;
            capturedFramesInBurst = 0;
            updateCounters();
            backendGuidanceActive = false;
            setGuidance(currentStageGuidance(), false);
            await setStatus('Capturing secure face profile...', `Burst ${attemptNumber}: capture is running.`, 'scanning');
            const frames = await captureBurstFrames(runId);
            if (runId !== activeRunId || pageClosing || redirected) return;
            const payload = await sendBurstBatches(frames, runId);
            if (!payload || runId !== activeRunId || pageClosing || redirected) return;
            const mapped = mapGuidanceToStatus(payload);
            await setStatus(mapped.message, mapped.caption, mapped.state, mapped.state === 'error');
            if (payload.auto_complete) return;
            if (payload.can_complete) {
                await setStatus('Ready to complete', 'Enough secure samples were accepted.', 'success');
                updateCounters();
                return;
            }
            if (shouldPauseForPoorEnrollment(payload)) {
                await pauseForPoorEnrollmentQuality(runId);
                if (runId !== activeRunId || pageClosing || redirected) return;
            }
            await setStatus('Capture another burst', `${mapped.text || payload.guidance || 'Adjust framing'} and keep going.`, 'warning');
        }
    } catch (error) {
        if (error && error.message === 'request_timeout') {
            await setStatus('Processing timeout. Try again.', 'The backend did not finish the burst batch in time.', 'warning', true);
        } else {
            await setStatus('Backend unavailable', 'The backend could not accept the burst.', 'error', true);
        }
        restartButton.disabled = false;
    }
}

async function beginEnrollment() {
    activeRunId += 1;
    const runId = activeRunId;
    redirected = false;
    stopActiveRequest();
    if (redirectTimerHandle) {
        window.clearTimeout(redirectTimerHandle);
        redirectTimerHandle = null;
    }
    resetEnrollmentUi();
    restartButton.disabled = true;
    await setStatus('Starting enrollment...', 'Creating a fresh enrollment session.', 'scanning', true);

    try {
        const payload = await postJson(`${ENROLL_API}/face/enroll/start`, {
            user_name: 'Moksh',
            replace_existing: true,
        }, runId);
        if (!payload || runId !== activeRunId || pageClosing) return;

        activeEnrollmentSessionId = String(payload.enrollment_session_id || '');
        requiredSamples = Number(payload.required_samples || requiredSamples);
        preferredSamples = Number(payload.preferred_samples || preferredSamples);
        updateCounters();
        if (!activeEnrollmentSessionId) {
            await setStatus('Enrollment session expired', 'The backend could not create an enrollment session.', 'error', true);
            restartButton.disabled = false;
            return;
        }
        await setStatus('Enrollment active', 'Camera warmed up. Starting burst capture.', 'scanning');
        restartButton.disabled = false;
        await burstLoop(runId);
    } catch (_error) {
        await setStatus('Backend unavailable', 'The backend could not start enrollment.', 'error', true);
        restartButton.disabled = false;
    }
}

function stopCameraStream() {
    if (!cameraStream) return;
    cameraStream.getTracks().forEach((track) => track.stop());
    cameraStream = null;
}

function cleanupEnrollment() {
    pageClosing = true;
    activeRunId += 1;
    stopGuidanceRotation();
    stopActiveRequest();
    if (redirectTimerHandle) {
        window.clearTimeout(redirectTimerHandle);
        redirectTimerHandle = null;
    }
    if (statusTimerHandle) {
        window.clearTimeout(statusTimerHandle);
        statusTimerHandle = null;
    }
    if (animationFrameHandle) {
        window.cancelAnimationFrame(animationFrameHandle);
        animationFrameHandle = 0;
    }
    stopCameraStream();
}

async function initializeEnrollmentPage() {
    resizeReactorCanvas();
    animationFrameHandle = window.requestAnimationFrame(animateReactor);
    rotateGuidance();
    updateControlVisibility();
    updateCounters();
    setStability(0);
    clearStepStates();
    await setStatus('Initializing enrollment system...', 'Awaiting camera and enrollment session.', 'idle', true);

    const cameraReady = await startCamera();
    if (!cameraReady) {
        restartButton.disabled = false;
        return;
    }

    restartButton.disabled = false;
    await beginEnrollment();
}

restartButton.addEventListener('click', () => {
    if (!cameraStream || pageClosing) return;
    beginEnrollment();
});

pauseButton.addEventListener('click', async () => {
    if (isPaused || pageClosing || redirected) return;
    pauseEnrollmentUi();
    await setStatus('Enrollment paused', 'Resume when you are ready to continue.', 'warning', true);
});

resumeButton.addEventListener('click', async () => {
    if (!isPaused || pageClosing || redirected) return;
    resumeEnrollmentUi();
    await setStatus('Resuming enrollment', 'Restarting secure burst capture.', 'scanning', true);
});

completeButton.addEventListener('click', async () => {
    if (completeButton.disabled || pageClosing || redirected) return;
    await completeEnrollment(activeRunId);
});

cancelButton.addEventListener('click', () => {
    if (redirected) return;
    redirected = true;
    window.location.assign('/launcher/');
});

window.addEventListener('resize', resizeReactorCanvas);
window.addEventListener('pagehide', cleanupEnrollment);
window.addEventListener('beforeunload', cleanupEnrollment);

initializeEnrollmentPage();
