const LAUNCHER_API = window.location.origin || 'http://localhost:8000';
const FIRST_VERIFY_TIMEOUT_MS = 25000;
const VERIFY_TIMEOUT_MS = 12000;
const CAPTURE_INTERVAL_MS = 150;
const CAPTURE_FRAME_COUNT = 5;
const CAPTURE_WARMUP_MS = 250;
const SUCCESS_REDIRECT_DELAY_MS = 500;
const ERROR_SHAKE_MS = 260;
const MAX_ATTEMPTS = 3;

const appEl = document.getElementById('launcher-app');
const videoEl = document.getElementById('camera-video');
const verifyButton = document.getElementById('verify-button');
const enrollButton = document.getElementById('enroll-button');
const mainStatusEl = document.getElementById('main-status');
const statusCaptionEl = document.getElementById('status-caption');
const systemStatusEl = document.getElementById('system-status');
const attemptsLabelEl = document.getElementById('attempts-label');
const lockoutLabelEl = document.getElementById('lockout-label');
const topStatusLabelEl = document.getElementById('top-status-label');
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

let cameraStream = null;
let activeRequestId = '';
let activeVerifyController = null;
let verifyTimeoutHandle = null;
let lockCountdownHandle = null;
let animationFrameHandle = 0;
let redirectTimerHandle = null;
let errorShakeHandle = null;
let redirected = false;
let attempts = 0;
let lockedUntil = 0;
let verifyInFlight = false;
let pageClosing = false;
let currentState = 'idle';
let currentStatusColor = '#00e6ff';
let hasStartedVerify = false;
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

const verificationStepNodes = {
    cameraOnline: document.querySelector('[data-step="camera-online"]'),
    faceDetected: document.querySelector('[data-step="face-detected"]'),
    qualityCheck: document.querySelector('[data-step="quality-check"]'),
    livenessCheck: document.querySelector('[data-step="liveness-check"]'),
};

const authenticationStepNodes = {
    matchingProfile: document.querySelector('[data-step="matching-profile"]'),
    faceRecognized: document.querySelector('[data-step="face-recognized"]'),
    sessionCreated: document.querySelector('[data-step="session-created"]'),
    openingJarvis: document.querySelector('[data-step="opening-jarvis"]'),
};

function buildRequestId() {
    return `launcher-${Date.now()}-${Math.random().toString(16).slice(2, 10)}`;
}

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
    const states = ['idle', 'scanning', 'success', 'warning', 'error', 'locked'];
    for (const state of states) {
        appEl.classList.toggle(`launcher-state-${state}`, state === nextState);
    }
    currentState = nextState;
    currentStatusColor = {
        idle: '#00e6ff',
        scanning: '#00e6ff',
        success: '#37ffb3',
        warning: '#ffcc66',
        error: '#ff4f6a',
        locked: '#ff4f6a',
    }[nextState] || '#00e6ff';
    updateDebugPanel({ state: nextState });
}

function setStatus(text, caption, state) {
    setVisualState(state);
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
}

function setCameraReady(isReady) {
    appEl.classList.toggle('is-camera-ready', Boolean(isReady));
}

function triggerErrorShake() {
    appEl.classList.remove('is-error-shaking');
    void appEl.offsetWidth;
    appEl.classList.add('is-error-shaking');
    if (errorShakeHandle) {
        window.clearTimeout(errorShakeHandle);
    }
    errorShakeHandle = window.setTimeout(() => {
        appEl.classList.remove('is-error-shaking');
        errorShakeHandle = null;
    }, ERROR_SHAKE_MS);
}

function scheduleRedirect(url) {
    if (redirectTimerHandle) {
        window.clearTimeout(redirectTimerHandle);
    }
    redirectTimerHandle = window.setTimeout(() => {
        redirectTimerHandle = null;
        window.location.assign(url);
    }, SUCCESS_REDIRECT_DELAY_MS);
}

function setSystemStatus(text) {
    systemStatusEl.textContent = text;
}

function setAttemptsLabel() {
    attemptsLabelEl.textContent = `${Math.min(attempts, MAX_ATTEMPTS)} / ${MAX_ATTEMPTS}`;
}

function clearStepStates(group) {
    Object.values(group).forEach((node) => {
        if (!node) return;
        node.classList.remove('is-active', 'is-done', 'is-warning', 'is-error');
    });
}

function setStepState(node, state) {
    if (!node) return;
    node.classList.remove('is-active', 'is-done', 'is-warning', 'is-error');
    if (state) node.classList.add(state);
}

function markInitialSteps() {
    clearStepStates(verificationStepNodes);
    clearStepStates(authenticationStepNodes);
    if (cameraStream) setStepState(verificationStepNodes.cameraOnline, 'is-done');
}

function disableVerifyButton(disabled) {
    verifyButton.disabled = disabled;
}

function showEnrollButton(show) {
    enrollButton.hidden = !show;
}

function isFaceProfileEnrolled(statusPayload) {
    if (!statusPayload || !statusPayload.available) return false;
    if (statusPayload.profile_exists === false) return false;
    if (statusPayload.profile_enrolled === false) return false;
    if (statusPayload.profile_active === false) return false;
    if (statusPayload.enrolled === false) return false;
    return Boolean(statusPayload.profile_enrolled || statusPayload.profile_exists || statusPayload.enrolled);
}

function routeToEnrollment() {
    showEnrollButton(true);
    disableVerifyButton(true);
    if (redirected) return;
    redirected = true;
    window.setTimeout(() => {
        window.location.assign('/enroll/');
    }, 900);
}

function recordBackendFailedAttempt(payload) {
    const status = String(payload?.status || '').toLowerCase();
    const reason = String(payload?.reason || '').toLowerCase();
    if (status === 'error' || status === 'unavailable' || reason.includes('unavailable')) return;
    const failedByBackend = ['failed', 'rejected', 'uncertain', 'locked'].includes(status) ||
        reason.includes('locked') ||
        reason.includes('no_face') ||
        reason.includes('multiple_face') ||
        reason.includes('liveness') ||
        reason.includes('quality') ||
        payload?.allowed === false ||
        payload?.verified === false;
    if (!failedByBackend) return;
    attempts += 1;
    setAttemptsLabel();
}

function mapVerifyFailure(payload) {
    const reason = String(payload?.reason || '').toLowerCase();
    const faceCount = Number(payload?.quality?.face_count || 0);
    if (reason.includes('locked')) {
        return { message: 'Too many attempts. Please wait.', caption: 'Verification is temporarily locked.', state: 'locked' };
    }
    if (reason.includes('permission_denied')) {
        return { message: 'Camera permission denied', caption: 'Allow camera access in the browser and try again.', state: 'error' };
    }
    if (faceCount > 1 || reason.includes('multiple_face') || reason.includes('multiple_faces')) {
        return { message: 'Multiple faces detected', caption: 'Ensure only one face is visible in frame.', state: 'warning' };
    }
    if (faceCount === 0 || reason.includes('no_face') || reason.includes('face_count_invalid')) {
        return { message: 'No face detected', caption: 'Center your face inside the targeting brackets.', state: 'warning' };
    }
    if (reason.includes('liveness')) {
        return { message: 'Please move slightly', caption: 'A small amount of natural motion is required.', state: 'warning' };
    }
    if (
        reason.includes('blurry') ||
        reason.includes('dark') ||
        reason.includes('bright') ||
        reason.includes('small') ||
        reason.includes('quality')
    ) {
        return { message: 'Image too blurry or dark', caption: 'Improve framing and lighting, then retry.', state: 'warning' };
    }
    if (reason.includes('unavailable')) {
        return { message: 'Verification unavailable', caption: 'The backend could not complete face verification.', state: 'error' };
    }
    return { message: 'Face not recognized', caption: 'The captured face did not match the enrolled profile.', state: 'error' };
}

function updateResultSteps(payload) {
    clearStepStates(authenticationStepNodes);
    const status = String(payload?.status || '').toLowerCase();
    const isVerified = status === 'verified';
    const qualityPassed = Boolean(payload?.quality?.passed) || isVerified;
    const livenessPassed = Boolean(payload?.liveness?.is_live) || isVerified;
    const faceCount = Number(payload?.quality?.face_count || 0);

    setStepState(verificationStepNodes.faceDetected, faceCount === 1 || isVerified ? 'is-done' : faceCount > 1 ? 'is-warning' : 'is-error');
    setStepState(verificationStepNodes.qualityCheck, qualityPassed ? 'is-done' : 'is-warning');
    setStepState(verificationStepNodes.livenessCheck, livenessPassed ? 'is-done' : 'is-warning');
    setStepState(authenticationStepNodes.matchingProfile, isVerified ? 'is-done' : 'is-warning');
    setStepState(authenticationStepNodes.faceRecognized, isVerified ? 'is-done' : 'is-warning');
}

function clearVerifyState() {
    activeRequestId = '';
    verifyInFlight = false;
    if (activeVerifyController) {
        activeVerifyController.abort();
        activeVerifyController = null;
    }
    if (verifyTimeoutHandle) {
        window.clearTimeout(verifyTimeoutHandle);
        verifyTimeoutHandle = null;
    }
}

function enableRetryIfAllowed() {
    if (verifyInFlight || redirected) return;
    if (Date.now() < lockedUntil) {
        disableVerifyButton(true);
        return;
    }
    if (!cameraStream) {
        disableVerifyButton(true);
        return;
    }
    if (!enrollButton.hidden) {
        disableVerifyButton(true);
        return;
    }
    disableVerifyButton(false);
}

function updateLockCountdown() {
    if (lockCountdownHandle) {
        window.clearTimeout(lockCountdownHandle);
        lockCountdownHandle = null;
    }
    const remainingMs = lockedUntil - Date.now();
    if (remainingMs <= 0) {
        lockedUntil = 0;
        lockoutLabelEl.textContent = 'Lockout cleared';
        setStatus('Ready to verify', 'Camera feed is live and the launcher is ready.', 'idle');
        enableRetryIfAllowed();
        return;
    }
    const remainingSeconds = Math.ceil(remainingMs / 1000);
    lockoutLabelEl.textContent = `Retry available in ${remainingSeconds}s`;
    disableVerifyButton(true);
    lockCountdownHandle = window.setTimeout(updateLockCountdown, 1000);
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
    for (let ring = 0; ring < 4; ring += 1) {
        ctx.beginPath();
        ctx.strokeStyle = color;
        ctx.lineWidth = ring === 0 ? 2 : 1;
        ctx.arc(0, 0, radius * (0.62 + ring * 0.14), 0, Math.PI * 2);
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

    ctx.globalAlpha = 0.14;
    for (let i = 0; i < 12; i += 1) {
        const angle = (Math.PI * 2 * i) / 12 + innerRotation * 0.12;
        ctx.beginPath();
        ctx.strokeStyle = color;
        ctx.moveTo(Math.cos(angle) * (radius * 0.3), Math.sin(angle) * (radius * 0.3));
        ctx.lineTo(Math.cos(angle) * (radius * 1.12), Math.sin(angle) * (radius * 1.12));
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
    ctx.beginPath();
    ctx.globalAlpha = 0.36;
    ctx.lineWidth = 1.1;
    ctx.arc(0, 0, radius * 0.8, Math.PI * 1.72, Math.PI * 1.96);
    ctx.stroke();
    ctx.restore();

    ctx.save();
    ctx.rotate(outerRotation);
    ctx.lineWidth = 8;
    ctx.globalAlpha = 0.84;
    const segments = 16;
    for (let i = 0; i < segments; i += 1) {
        const start = (Math.PI * 2 * i) / segments;
        const end = start + Math.PI / segments * 0.34;
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

    ctx.globalAlpha = 0.5;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.strokeStyle = color;
    ctx.arc(0, 0, radius * 1.16, 0, Math.PI * 2);
    ctx.stroke();

    ctx.restore();
    animationFrameHandle = window.requestAnimationFrame(animateReactor);
}

async function waitForVideoReady() {
    if (videoEl.readyState === 4) return;
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
        setStatus('Initializing camera...', 'Requesting secure camera access.', 'idle');
        cameraStream = await navigator.mediaDevices.getUserMedia({
            video: {
                facingMode: 'user',
                width: { ideal: 1280 },
                height: { ideal: 720 },
            },
            audio: false,
        });
        videoEl.srcObject = cameraStream;
        await waitForVideoReady();
        setCameraReady(true);
        setSystemStatus('ONLINE');
        setStepState(verificationStepNodes.cameraOnline, 'is-done');
        return true;
    } catch (error) {
        setCameraReady(false);
        const permissionDenied = error && (error.name === 'NotAllowedError' || error.name === 'SecurityError');
        const message = permissionDenied ? 'Camera permission denied' : 'Camera unavailable';
        const caption = permissionDenied
            ? 'Allow camera access in the browser to continue.'
            : 'No usable camera stream is available for verification.';
        setStatus(message, caption, 'error');
        setSystemStatus('CAMERA OFFLINE');
        disableVerifyButton(true);
        return false;
    }
}

async function fetchFaceStatus() {
    const response = await fetch(`${LAUNCHER_API}/face/status`, { cache: 'no-store' });
    return response.json();
}

async function initializeLauncher() {
    resizeReactorCanvas();
    animationFrameHandle = window.requestAnimationFrame(animateReactor);
    setAttemptsLabel();
    setStatus('Initializing secure launcher...', 'Awaiting camera and backend readiness.', 'idle');
    markInitialSteps();

    const cameraReady = await startCamera();
    if (!cameraReady) return;

    setStatus('Camera online', 'Checking face-gate enrollment and backend readiness.', 'scanning');
    disableVerifyButton(true);

    try {
        const statusPayload = await fetchFaceStatus();
        if (!statusPayload.available) {
            setStatus('Verification unavailable', 'Face authentication backend is offline.', 'error');
            setSystemStatus('BACKEND OFFLINE');
            disableVerifyButton(true);
            return;
        }

        if (!isFaceProfileEnrolled(statusPayload)) {
            setStatus('Face profile not enrolled', 'Routing to enrollment before verification.', 'warning');
            updateDebugPanel({ reason: 'profile_not_enrolled' });
            routeToEnrollment();
            return;
        }

        showEnrollButton(false);
        setStatus('Ready to verify', 'Position your face inside the targeting brackets.', 'idle');
        enableRetryIfAllowed();
    } catch (_error) {
        setStatus('Verification unavailable', 'Backend status could not be loaded.', 'error');
        setSystemStatus('BACKEND OFFLINE');
        disableVerifyButton(true);
    }
}

async function captureFrames() {
    await new Promise((resolve) => window.setTimeout(resolve, CAPTURE_WARMUP_MS));
    const canvas = document.createElement('canvas');
    const width = videoEl.videoWidth || 640;
    const height = videoEl.videoHeight || 480;
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext('2d', { willReadFrequently: true });
    const frames = [];

    for (let index = 0; index < CAPTURE_FRAME_COUNT; index += 1) {
        context.drawImage(videoEl, 0, 0, width, height);
        frames.push(canvas.toDataURL('image/jpeg', 0.9).split(',')[1]);
        if (index < CAPTURE_FRAME_COUNT - 1) {
            await new Promise((resolve) => window.setTimeout(resolve, CAPTURE_INTERVAL_MS));
        }
    }

    return frames;
}

async function startVerify() {
    if (verifyInFlight || redirected || verifyButton.disabled) return;
    if (Date.now() < lockedUntil) return;
    if (!cameraStream) return;

    verifyInFlight = true;
    activeRequestId = buildRequestId();
    const requestId = activeRequestId;
    const isFirstVerify = !hasStartedVerify;
    const timeoutMs = isFirstVerify ? FIRST_VERIFY_TIMEOUT_MS : VERIFY_TIMEOUT_MS;
    hasStartedVerify = true;
    disableVerifyButton(true);
    markInitialSteps();
    setStepState(authenticationStepNodes.matchingProfile, 'is-active');
    setStatus(isFirstVerify ? 'Initializing face engine...' : 'Verifying face...', 'Checking face-gate status before verification.', 'scanning');
    updateDebugPanel({
        requestId,
        frames: 0,
        sent: false,
        received: false,
        timeoutMs,
        httpStatus: '-',
        reason: '-',
    });

    try {
        const statusPayload = await fetchFaceStatus();
        updateDebugPanel({ httpStatus: 200, reason: statusPayload?.backend_reason || statusPayload?.reason || '-' });
        if (activeRequestId !== requestId) return;
        if (!statusPayload.available) {
            verifyInFlight = false;
            activeRequestId = '';
            setStatus('Verification unavailable', 'Face authentication backend is offline.', 'error');
            setSystemStatus('BACKEND OFFLINE');
            disableVerifyButton(true);
            return;
        }
        if (!isFaceProfileEnrolled(statusPayload)) {
            verifyInFlight = false;
            activeRequestId = '';
            setStatus('Face profile not enrolled', 'Routing to enrollment before verification.', 'warning');
            updateDebugPanel({ reason: 'profile_not_enrolled' });
            routeToEnrollment();
            return;
        }
    } catch (_error) {
        if (activeRequestId !== requestId) return;
        verifyInFlight = false;
        activeRequestId = '';
        setStatus('Verification unavailable', 'Backend status could not be loaded.', 'error');
        setSystemStatus('BACKEND OFFLINE');
        disableVerifyButton(true);
        return;
    }

    setStatus(isFirstVerify ? 'Initializing face engine...' : 'Verifying face...', 'Collecting live frames for backend verification.', 'scanning');

    const controller = new AbortController();
    activeVerifyController = controller;
    verifyTimeoutHandle = window.setTimeout(() => {
        if (activeRequestId !== requestId) return;
        controller.abort();
        activeRequestId = '';
        verifyInFlight = false;
        activeVerifyController = null;
        verifyTimeoutHandle = null;
        setStatus('Verification timeout. Try again.', 'The backend did not finish before the timeout.', 'warning');
        updateDebugPanel({ reason: 'timeout' });
        clearStepStates(authenticationStepNodes);
        triggerErrorShake();
        enableRetryIfAllowed();
    }, timeoutMs);

    try {
        const frames = await captureFrames();
        if (activeRequestId !== requestId) return;
        updateDebugPanel({ frames: frames.length });
        setStepState(authenticationStepNodes.matchingProfile, 'is-active');
        setStatus(isFirstVerify ? 'Initializing face engine...' : 'Verifying face...', 'Sending live frames to backend verification.', 'scanning');
        updateDebugPanel({ sent: true });

        const response = await fetch(`${LAUNCHER_API}/face/verify`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                frames,
                client_id: 'launcher',
                request_id: requestId,
            }),
            signal: controller.signal,
        });

        const payload = await response.json().catch(() => ({}));
        if (activeRequestId !== requestId) return;
        if (String(payload.request_id || '') !== requestId) return;
        updateDebugPanel({
            received: true,
            httpStatus: response.status,
            reason: payload.reason || payload.status || '-',
        });

        verifyInFlight = false;
        activeRequestId = '';
        if (verifyTimeoutHandle) {
            window.clearTimeout(verifyTimeoutHandle);
            verifyTimeoutHandle = null;
        }
        activeVerifyController = null;
        updateResultSteps(payload);

        const status = String(payload.status || '').toLowerCase();
        if (status === 'verified' && payload.launcher_bootstrap_token && !redirected) {
            redirected = true;
            setStepState(authenticationStepNodes.sessionCreated, 'is-done');
            setStepState(authenticationStepNodes.openingJarvis, 'is-active');
            setStatus('Opening Jarvis', 'Secure session established. Redirecting to the main interface.', 'success');
            const redirectUrl = `/app/?bootstrap_token=${encodeURIComponent(payload.launcher_bootstrap_token)}`;
            scheduleRedirect(redirectUrl);
            return;
        }

        recordBackendFailedAttempt(payload);

        if (status === 'locked' || String(payload.reason || '').toLowerCase().includes('locked')) {
            const retryAfter = Number(payload.retry_after_seconds || payload.retry_after || 45);
            lockedUntil = Date.now() + (Math.max(1, retryAfter) * 1000);
            setStatus('Too many attempts. Please wait.', 'Verification is temporarily locked.', 'locked');
            updateLockCountdown();
            return;
        }

        const mapped = mapVerifyFailure(payload);
        setStatus(mapped.message, mapped.caption, mapped.state);
        triggerErrorShake();
        enableRetryIfAllowed();
    } catch (error) {
        if (activeRequestId !== requestId) return;
        verifyInFlight = false;
        activeRequestId = '';
        if (verifyTimeoutHandle) {
            window.clearTimeout(verifyTimeoutHandle);
            verifyTimeoutHandle = null;
        }
        activeVerifyController = null;
        if (error && error.name === 'AbortError') {
            enableRetryIfAllowed();
            return;
        }
        setStatus('Verification unavailable', 'Could not complete the verify request.', 'error');
        triggerErrorShake();
        enableRetryIfAllowed();
    }
}

function stopCameraStream() {
    if (!cameraStream) return;
    cameraStream.getTracks().forEach((track) => track.stop());
    cameraStream = null;
}

function cleanupLauncher() {
    pageClosing = true;
    clearVerifyState();
    if (lockCountdownHandle) {
        window.clearTimeout(lockCountdownHandle);
        lockCountdownHandle = null;
    }
    if (redirectTimerHandle) {
        window.clearTimeout(redirectTimerHandle);
        redirectTimerHandle = null;
    }
    if (errorShakeHandle) {
        window.clearTimeout(errorShakeHandle);
        errorShakeHandle = null;
    }
    if (animationFrameHandle) {
        window.cancelAnimationFrame(animationFrameHandle);
        animationFrameHandle = 0;
    }
    stopCameraStream();
}

verifyButton.addEventListener('click', () => {
    startVerify();
});

enrollButton.addEventListener('click', () => {
    if (redirected) return;
    redirected = true;
    window.location.assign('/enroll/');
});

document.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter') return;
    if (verifyButton.disabled || verifyInFlight || redirected) return;
    event.preventDefault();
    startVerify();
});

window.addEventListener('resize', resizeReactorCanvas);
window.addEventListener('pagehide', cleanupLauncher);
window.addEventListener('beforeunload', cleanupLauncher);

initializeLauncher();
