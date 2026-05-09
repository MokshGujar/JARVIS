package com.jarvis.companion

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.media.AudioManager
import android.media.AudioRecordingConfiguration
import android.media.MediaPlayer
import android.net.Uri
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import java.io.File
import java.util.concurrent.ConcurrentHashMap

class BackgroundVoiceService : Service() {
    private val mainHandler = Handler(Looper.getMainLooper())
    private val pendingActionsHandler = Handler(Looper.getMainLooper())
    private val micRestartRunnable = Runnable { startListeningLoop() }
    private var speechRecognizer: SpeechRecognizer? = null
    private var isListening = false
    private var isSpeaking = false
    private var isPollingActions = false
    private var awaitingFollowup = false
    private var awaitingFollowupUntil = 0L
    private var awaitingVoiceVerification = false
    private var awaitingVoiceVerificationUntil = 0L
    private var trustedVoiceVerifiedUntil = 0L
    private var trustedVoiceRetryCount = 0
    private var pendingCommandAfterVerification: String? = null
    private var pendingUncertainPhoneAction: PendingPhoneAction? = null
    private var pendingUncertainPhoneActionUntil = 0L
    private var isRecordingVoiceprint = false
    private var activeCommandAudioRecording: CommandAudioRecorder.LiveRecording? = null
    private var isMicPaused = false
    private var isMicPausedForExternalRecorder = false
    private var micPausedUntil = 0L
    private var activeExternalRecorderCount = 0
    private var lastAckCueAt = 0L
    private var lastAckPhrase = ""
    private var consecutiveRecognizerErrors = 0
    private var currentPlayer: MediaPlayer? = null
    private var currentAudioFile: File? = null
    private val streamAudioQueue = ArrayDeque<ByteArray>()
    private var streamReplyText = ""
    private var streamAudioComplete = false
    private var streamPlaybackComplete = false
    private val cuePlayers = mutableSetOf<MediaPlayer>()
    private val cueAudioCache = ConcurrentHashMap<String, ByteArray>()
    private var lastNotificationText = ""
    private lateinit var logger: AppEventLogger
    private lateinit var prefs: JarvisPreferences

    override fun onCreate() {
        super.onCreate()
        logger = AppEventLogger(applicationContext)
        prefs = JarvisPreferences(applicationContext)
        createNotificationChannel()
        startForeground(NOTIFICATION_ID, buildNotification("Listening for Jarvis voice commands"))
        registerRecordingWatcher()
        if (prefs.isListeningCueEnabled()) {
            warmJarvisCueCache()
        }
        startListeningLoop()
        startPendingActionPolling()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> {
                logger.log("Background voice service stopping")
                stopSelf()
                return START_NOT_STICKY
            }
            ACTION_PAUSE_MIC -> {
                pauseMicForExternalRecognition()
            }
            ACTION_RESUME_MIC -> {
                resumeMicListening()
            }
            else -> {
                logger.log("Background voice service running")
                startListeningLoop()
            }
        }
        return START_STICKY
    }

    override fun onDestroy() {
        stopListeningLoop()
        stopPendingActionPolling()
        unregisterRecordingWatcher()
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun startListeningLoop() {
        if (isMicPaused) {
            val now = System.currentTimeMillis()
            if (isMicPausedForExternalRecorder) {
                updateNotification("Jarvis mic paused while another app records")
                scheduleRestart(delayMs = EXTERNAL_RECORDER_CHECK_MS)
                return
            }
            if (now < micPausedUntil) {
                updateNotification("Jarvis mic paused so other apps can listen")
                scheduleRestart(delayMs = micPausedUntil - now)
                return
            }
            isMicPaused = false
            isMicPausedForExternalRecorder = false
            micPausedUntil = 0L
        }

        if (!hasMicPermission()) {
            logger.log("Background voice service cannot start: RECORD_AUDIO not granted")
            stopSelf()
            return
        }

        if (!SpeechRecognizer.isRecognitionAvailable(this)) {
            logger.log("Background voice service cannot start: SpeechRecognizer unavailable")
            stopSelf()
            return
        }

        if (speechRecognizer == null) {
            speechRecognizer = SpeechRecognizer.createSpeechRecognizer(this).apply {
                setRecognitionListener(object : RecognitionListener {
                    override fun onReadyForSpeech(params: Bundle?) {
                        isListening = true
                        consecutiveRecognizerErrors = 0
                        updateNotification("Listening for Jarvis voice commands")
                    }

                    override fun onBeginningOfSpeech() {
                        updateNotification("Heard speech, processing...")
                    }

                    override fun onRmsChanged(rmsdB: Float) = Unit

                    override fun onBufferReceived(buffer: ByteArray?) = Unit

                    override fun onEndOfSpeech() {
                        isListening = false
                        updateNotification("Processing voice command...")
                    }

                    override fun onError(error: Int) {
                        isListening = false
                        cancelCommandAudioCapture()
                        logger.log("Background voice recognizer error: $error")
                        scheduleRecognizerRestartAfterError(error)
                    }

                    override fun onResults(results: Bundle?) {
                        isListening = false
                        consecutiveRecognizerErrors = 0
                        handleResults(results)
                    }

                    override fun onPartialResults(partialResults: Bundle?) = Unit

                    override fun onEvent(eventType: Int, params: Bundle?) = Unit
                })
            }
        }

        if (isCuePlaybackActive()) {
            updateNotification("Jarvis is speaking...")
            scheduleRestart(delayMs = 600L)
            return
        }

        if (!isListening && !isSpeaking && !isRecordingVoiceprint) {
            runCatching {
                startCommandAudioCapture()
                speechRecognizer?.startListening(buildRecognizerIntent())
            }.onFailure {
                cancelCommandAudioCapture()
                logger.log("Background voice start failed: ${it.message}")
                scheduleRestart()
            }
        }
    }

    private fun stopListeningLoop() {
        cancelScheduledRestart()
        releaseSpeechRecognizer()
        stopCurrentPlayback()
    }

    private fun releaseSpeechRecognizer() {
        runCatching { speechRecognizer?.stopListening() }
        runCatching { speechRecognizer?.cancel() }
        speechRecognizer?.destroy()
        speechRecognizer = null
        isListening = false
        cancelCommandAudioCapture()
    }

    private fun startPendingActionPolling() {
        pendingActionsHandler.removeCallbacksAndMessages(null)
        pendingActionsHandler.post(pendingActionsRunnable)
    }

    private fun stopPendingActionPolling() {
        pendingActionsHandler.removeCallbacksAndMessages(null)
    }

    private fun scheduleRestart(delayMs: Long = 1200L) {
        cancelScheduledRestart()
        mainHandler.postDelayed(micRestartRunnable, delayMs)
    }

    private fun cancelScheduledRestart() {
        mainHandler.removeCallbacks(micRestartRunnable)
    }

    private fun scheduleRecognizerRestartAfterError(error: Int) {
        consecutiveRecognizerErrors += 1

        if (error == SpeechRecognizer.ERROR_RECOGNIZER_BUSY) {
            releaseSpeechRecognizer()
        }

        val delayMs = when (error) {
            SpeechRecognizer.ERROR_NO_MATCH,
            SpeechRecognizer.ERROR_SPEECH_TIMEOUT -> IDLE_RECOGNIZER_RESTART_DELAY_MS
            SpeechRecognizer.ERROR_RECOGNIZER_BUSY -> BUSY_RECOGNIZER_RESTART_DELAY_MS
            else -> minOf(
                ERROR_RECOGNIZER_RESTART_DELAY_MS * consecutiveRecognizerErrors,
                MAX_RECOGNIZER_RESTART_DELAY_MS
            )
        }
        scheduleRestart(delayMs = delayMs)
    }

    private fun handleResults(results: Bundle?) {
        val matches = results
            ?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
            ?.map { it.trim() }
            ?.filter { it.isNotBlank() }
            .orEmpty()

        if (matches.isEmpty()) {
            return
        }

        val best = matches.first()
        val capturedVoiceAudioBase64 = finishCommandAudioCapture()
        logger.log("Background voice heard: $best")

        val normalized = normalizeCommand(best)
        val callControlService = CallControlService(applicationContext)
        val pendingActionExecutor = PendingPhoneActionExecutor(applicationContext, logger)
        val uncertainPhoneAction = pendingUncertainPhoneAction
        if (uncertainPhoneAction != null && System.currentTimeMillis() <= pendingUncertainPhoneActionUntil) {
            when {
                isConfirmationYes(normalized) -> {
                    pendingUncertainPhoneAction = null
                    pendingUncertainPhoneActionUntil = 0L
                    executeConfirmedPhoneAction(uncertainPhoneAction, pendingActionExecutor)
                    scheduleRestart(delayMs = 900L)
                    return
                }
                isConfirmationNo(normalized) -> {
                    pendingUncertainPhoneAction = null
                    pendingUncertainPhoneActionUntil = 0L
                    updateState("failure", "Phone action cancelled after uncertain voice match")
                    playJarvisCue("Understood. I will not continue.", throttleMs = 600L)
                    scheduleRestart(delayMs = 700L)
                    return
                }
            }
        } else if (uncertainPhoneAction != null) {
            pendingUncertainPhoneAction = null
            pendingUncertainPhoneActionUntil = 0L
            updateState("failure", "Uncertain phone confirmation expired")
        }

        val wakeOnly = WAKE_ONLY_PHRASES.any { normalized == it }
        val wakePrefixed = normalized.startsWith("jarvis ")
        val followupActive = awaitingFollowup && System.currentTimeMillis() <= awaitingFollowupUntil
        val trustedVoiceRequired = prefs.isTrustedVoiceEnabled()
        val trustedVoiceVerified = !trustedVoiceRequired || System.currentTimeMillis() <= trustedVoiceVerifiedUntil
        val protectedVoiceVerified = System.currentTimeMillis() <= trustedVoiceVerifiedUntil

        when {
            wakeOnly -> {
                updateState("listening", "Wake phrase accepted")
                acknowledgeWakeAndAwaitFollowup()
                return
            }
            ANSWER_PHRASES.any { normalized.contains(it) } -> {
                updateState("processing", "Answer call command detected")
                if (!protectedVoiceVerified) {
                    pendingCommandAfterVerification = best
                    requestTrustedVoiceVerification()
                    return
                }
                val result = callControlService.answerIncomingCall()
                if (result.isSuccess) {
                    logger.log("Background voice answered the call")
                    updateNotification("Answered the incoming call")
                } else {
                    logger.log("Background voice failed to answer: ${result.exceptionOrNull()?.message}")
                    updateNotification("Could not answer the call")
                }
                clearFollowupState()
                scheduleRestart(delayMs = 700L)
            }
            REJECT_PHRASES.any { normalized.contains(it) } -> {
                updateState("processing", "Reject call command detected")
                if (!protectedVoiceVerified) {
                    pendingCommandAfterVerification = best
                    requestTrustedVoiceVerification()
                    return
                }
                val result = callControlService.rejectIncomingCall()
                if (result.isSuccess) {
                    logger.log("Background voice rejected the call")
                    updateNotification("Rejected the incoming call")
                } else {
                    logger.log("Background voice failed to reject: ${result.exceptionOrNull()?.message}")
                    updateNotification("Could not reject the call")
                }
                clearFollowupState()
                scheduleRestart(delayMs = 700L)
            }
            isReadRecentMessageRequest(normalized) -> {
                updateState("processing", "Recent message read requested")
                if (!protectedVoiceVerified) {
                    pendingCommandAfterVerification = LOCAL_READ_LAST_MESSAGE_COMMAND
                    requestTrustedVoiceVerification()
                    return
                }
                readRecentMessageAloud()
                return
            }
            wakePrefixed || followupActive -> {
                updateState("processing", "Sending command to Jarvis")
                clearFollowupState()
                sendToJarvisBackend(best, capturedVoiceAudioBase64)
                return
            }
            else -> {
                scheduleRestart(delayMs = 500L)
            }
        }
    }

    private fun acknowledgeWakeAndAwaitFollowup() {
        armFollowupWindow()
        stopCurrentPlayback()
        updateNotification("Jarvis is listening...")
        scheduleRestart(delayMs = LOCAL_ACK_RESTART_DELAY_MS)
    }

    private fun clearFollowupState() {
        awaitingFollowup = false
        awaitingFollowupUntil = 0L
    }

    private fun requestTrustedVoiceVerification() {
        trustedVoiceRetryCount = 0
        requestVoiceprintVerification()
    }

    private fun requestVoiceprintVerification() {
        if (isRecordingVoiceprint) {
            return
        }

        awaitingVoiceVerification = true
        awaitingVoiceVerificationUntil = System.currentTimeMillis() + TRUSTED_VOICE_PROMPT_WINDOW_MS
        stopCurrentPlayback()
        cancelScheduledRestart()
        releaseSpeechRecognizer()
        isRecordingVoiceprint = true
        updateState("verifying_user", "Verifying your voice with Jarvis...")
        playJarvisCue("Verifying voice.", throttleMs = 600L)

        Thread {
            Thread.sleep(1_300L)
            val result = verifyLiveVoiceWithBackend("sensitive")

            mainHandler.post {
                isRecordingVoiceprint = false
                when (result.status) {
                    SpeakerVerificationStatus.VERIFIED -> {
                        logger.log("Backend trusted voice accepted: ${result.score}")
                        handleTrustedVoiceAccepted()
                    }
                    SpeakerVerificationStatus.UNCERTAIN -> {
                        logger.log("Backend trusted voice uncertain: ${result.score}")
                        handleTrustedVoiceRejected("That sounds like you, but I need a clearer match")
                    }
                    SpeakerVerificationStatus.NOT_VERIFIED -> {
                        logger.log("Backend trusted voice rejected: ${result.score}")
                        handleTrustedVoiceRejected("Voiceprint did not match")
                    }
                    SpeakerVerificationStatus.UNAVAILABLE -> {
                        logger.log("Backend trusted voice unavailable: ${result.reason}")
                        handleTrustedVoiceRejected(result.reason.ifBlank { "Voiceprint check failed. Try speaking again." })
                    }
                }
            }
        }.start()
    }

    private fun verifyLiveVoiceWithBackend(commandPolicy: String): SpeakerVerificationResult {
        val baseUrl = prefs.getBackendUrl()
        if (baseUrl.isBlank()) {
            return SpeakerVerificationResult(
                status = SpeakerVerificationStatus.UNAVAILABLE,
                score = 0f,
                reason = "Jarvis backend URL is not configured.",
            )
        }

        val api = JarvisApiClient()
        val authToken = prefs.getAuthToken()
        val status = runCatching {
            api.getVoiceStatus(baseUrl, authToken)
        }.getOrElse { error ->
            return SpeakerVerificationResult(
                status = SpeakerVerificationStatus.UNAVAILABLE,
                score = 0f,
                reason = error.message ?: "Voice verification is unavailable.",
            )
        }

        if (!status.profileEnrolled) {
            return SpeakerVerificationResult(
                status = SpeakerVerificationStatus.UNAVAILABLE,
                score = 0f,
                reason = "Enroll your voice on the Jarvis backend first.",
            )
        }

        val recording = CommandAudioRecorder.startLiveRecording(applicationContext).getOrElse { error ->
            return SpeakerVerificationResult(
                status = SpeakerVerificationStatus.UNAVAILABLE,
                score = 0f,
                reason = error.message ?: "Voice sample capture failed.",
            )
        }
        Thread.sleep(3_500L)
        val sample = recording.stopAndCapture().getOrElse { error ->
            return SpeakerVerificationResult(
                status = SpeakerVerificationStatus.UNAVAILABLE,
                score = 0f,
                reason = error.message ?: "Voice sample capture failed.",
            )
        }

        val verify = runCatching {
            api.verifyVoiceSample(
                baseUrl = baseUrl,
                authToken = authToken,
                audioBase64 = WavEncoding.encodeClipAsBase64(sample),
                clientType = "android",
                deviceId = prefs.getDeviceId(),
                commandPolicy = commandPolicy,
            )
        }.getOrElse { error ->
            return SpeakerVerificationResult(
                status = SpeakerVerificationStatus.UNAVAILABLE,
                score = 0f,
                reason = error.message ?: "Voice verification failed.",
            )
        }

        val verificationStatus = when (verify.status.lowercase()) {
            "verified" -> SpeakerVerificationStatus.VERIFIED
            "uncertain" -> SpeakerVerificationStatus.UNCERTAIN
            "rejected" -> SpeakerVerificationStatus.NOT_VERIFIED
            else -> SpeakerVerificationStatus.UNAVAILABLE
        }
        return SpeakerVerificationResult(
            status = verificationStatus,
            score = verify.confidence,
            reason = verify.reason,
        )
    }

    private fun handleTrustedVoiceAccepted() {
        awaitingVoiceVerification = false
        awaitingVoiceVerificationUntil = 0L
        trustedVoiceRetryCount = 0
        trustedVoiceVerifiedUntil = System.currentTimeMillis() + TRUSTED_VOICE_WINDOW_MS
        val pendingCommand = pendingCommandAfterVerification
        pendingCommandAfterVerification = null
        if (!pendingCommand.isNullOrBlank()) {
            if (pendingCommand == LOCAL_READ_LAST_MESSAGE_COMMAND) {
                readRecentMessageAloud()
                return
            }
            clearFollowupState()
            sendToJarvisBackend(pendingCommand)
        } else {
            updateState("success", "Voice verified")
            acknowledgeWakeAndAwaitFollowup()
        }
    }

    private fun handleTrustedVoiceRejected(message: String) {
        if (trustedVoiceRetryCount < TRUSTED_VOICE_MAX_RETRIES) {
            trustedVoiceRetryCount += 1
            updateNotification("$message Listening again...")
            mainHandler.postDelayed({
                requestVoiceprintVerification()
            }, TRUSTED_VOICE_RETRY_DELAY_MS)
            return
        }

        pendingCommandAfterVerification = null
        awaitingVoiceVerification = false
        awaitingVoiceVerificationUntil = 0L
        trustedVoiceRetryCount = 0
        updateNotification(message)
        playRejectCue()
        scheduleRestart(delayMs = 700L)
    }

    private fun armFollowupWindow() {
        awaitingFollowup = true
        awaitingFollowupUntil = System.currentTimeMillis() + FOLLOWUP_WINDOW_MS
    }

    private fun sendToJarvisBackend(spokenText: String, voiceAudioBase64: String? = null) {
        val cleaned = spokenText
            .replace(Regex("""(?i)\bjarvis\b"""), "")
            .replace(Regex("""\s+"""), " ")
            .trim()

        if (cleaned.isBlank()) {
            updateNotification("Listening for Jarvis voice commands")
            scheduleRestart(delayMs = 400L)
            return
        }

        updateNotification("Sending to Jarvis...")
        mainHandler.post {
            stopCurrentPlayback()
            isSpeaking = true
            streamAudioComplete = false
            streamPlaybackComplete = false
            streamReplyText = ""
            streamAudioQueue.clear()
            updateNotification("Jarvis is thinking...")
        }

        Thread {
            val api = JarvisApiClient()
            val baseUrl = prefs.getBackendUrl()
            val authToken = prefs.getAuthToken()
            val sessionId = prefs.getBackgroundVoiceSessionId().ifBlank { null }
            val replyBuilder = StringBuilder()

            runCatching {
                api.streamJarvisChat(
                    baseUrl = baseUrl,
                    authToken = authToken,
                    message = cleaned,
                    sessionId = sessionId,
                    tts = true,
                    inputSource = "voice",
                    voiceAudioBase64 = voiceAudioBase64,
                ) { event ->
                    event.sessionId?.takeIf { it.isNotBlank() }?.let { prefs.setBackgroundVoiceSessionId(it) }
                    event.error?.let { throw IllegalStateException(it) }
                    event.chunk?.let { chunk ->
                        if (chunk.isNotBlank()) {
                            replyBuilder.append(chunk)
                        }
                    }
                    event.audio?.let { audioBytes ->
                        mainHandler.post {
                            enqueueStreamAudio(audioBytes)
                        }
                    }
                    if (event.done) {
                        mainHandler.post {
                            finishStreamAudio(replyBuilder.toString())
                        }
                    }
                }
                replyBuilder.toString()
            }.onSuccess { reply ->
                logger.log("Background voice stream completed (${reply.length} chars)")
                mainHandler.post {
                    finishStreamAudio(reply)
                }
            }.onFailure { error ->
                logger.log("Background voice backend request failed: ${error.message}")
                mainHandler.post {
                    stopCurrentPlayback()
                    updateNotification("Jarvis reply failed")
                    scheduleRestart(delayMs = 1200L)
                }
            }
        }.start()
    }

    private fun startCommandAudioCapture() {
        if (activeCommandAudioRecording != null) {
            return
        }
        activeCommandAudioRecording = CommandAudioRecorder.startLiveRecording(applicationContext).getOrNull()
    }

    private fun finishCommandAudioCapture(): String? {
        val recording = activeCommandAudioRecording ?: return null
        activeCommandAudioRecording = null
        return recording.stopAndCapture().getOrNull()?.let { clip ->
            WavEncoding.encodeClipAsBase64(clip)
        }
    }

    private fun cancelCommandAudioCapture() {
        activeCommandAudioRecording?.cancel()
        activeCommandAudioRecording = null
    }

    private fun enqueueStreamAudio(audioBytes: ByteArray) {
        if (audioBytes.isEmpty()) {
            logger.log("Background voice stream audio chunk was empty")
            return
        }
        streamAudioQueue += audioBytes
        if (currentPlayer == null) {
            playNextStreamAudio()
        }
    }

    private fun finishStreamAudio(reply: String) {
        if (reply.isNotBlank()) {
            streamReplyText = reply
        }
        streamAudioComplete = true
        if (currentPlayer == null && streamAudioQueue.isEmpty()) {
            completeStreamPlayback()
        }
    }

    private fun playNextStreamAudio() {
        val audioBytes = streamAudioQueue.removeFirstOrNull()
        if (audioBytes == null) {
            if (streamAudioComplete) {
                completeStreamPlayback()
            }
            return
        }

        isSpeaking = true
        updateNotification("Jarvis replying...")

        runCatching {
            val tempFile = File.createTempFile("jarvis-bg-voice-", ".mp3", cacheDir)
            tempFile.writeBytes(audioBytes)
            currentAudioFile = tempFile

            val player = MediaPlayer().apply {
                setDataSource(tempFile.absolutePath)
                setOnCompletionListener {
                    cleanupPlayback(tempFile, it)
                    playNextStreamAudio()
                }
                setOnErrorListener { mp, _, _ ->
                    logger.log("Background voice stream playback failed")
                    cleanupPlayback(tempFile, mp)
                    playNextStreamAudio()
                    true
                }
                prepare()
            }

            currentPlayer = player
            player.start()
        }.onFailure { error ->
            logger.log("Background voice stream audio setup failed: ${error.message}")
            currentAudioFile?.delete()
            currentAudioFile = null
            currentPlayer = null
            playNextStreamAudio()
        }
    }

    private fun completeStreamPlayback() {
        if (streamPlaybackComplete) {
            return
        }
        streamPlaybackComplete = true
        val reply = streamReplyText.trim()
        if (reply.isNotBlank()) {
            logger.log("Jarvis said: $reply")
            if (shouldAwaitFollowup(reply)) {
                armFollowupWindow()
            }
        } else {
            logger.log("Jarvis stream completed without spoken text")
        }
        streamAudioComplete = false
        streamReplyText = ""
        isSpeaking = false
        updateNotification("Listening for Jarvis voice commands")
        scheduleRestart(delayMs = 500L)
    }

    private fun cleanupPlayback(tempFile: File, player: MediaPlayer) {
        if (currentPlayer === player) {
            currentPlayer = null
        }
        if (currentAudioFile == tempFile) {
            currentAudioFile = null
        }
        runCatching { player.release() }
        tempFile.delete()
    }

    private fun stopCurrentPlayback() {
        currentPlayer?.runCatching {
            if (isPlaying) {
                stop()
            }
        }
        currentPlayer?.release()
        currentPlayer = null
        currentAudioFile?.delete()
        currentAudioFile = null
        streamAudioQueue.clear()
        streamAudioComplete = false
        streamPlaybackComplete = false
        streamReplyText = ""
        cuePlayers.forEach { player ->
            runCatching { player.release() }
        }
        cuePlayers.clear()
        isSpeaking = false
    }

    private fun playAckCue() {
        val phrases = arrayOf(
            "I'm listening.",
            "Go ahead.",
            "Yes, Sir?",
            "Ready.",
            "At your service.",
            "I'm with you.",
        )
        val available = phrases.filter { it != lastAckPhrase }.ifEmpty { phrases.toList() }
        val index = ((System.currentTimeMillis() / 1000L) % available.size).toInt()
        val phrase = available[index]
        lastAckPhrase = phrase
        playJarvisCue(phrase, throttleMs = 900L)
    }

    private fun playRejectCue() {
        playJarvisCue("Voiceprint did not match.", throttleMs = 600L)
    }

    private fun playJarvisCue(text: String, throttleMs: Long) {
        if (!prefs.isListeningCueEnabled()) {
            logger.log("Jarvis cue suppressed by listening cue config")
            return
        }
        val now = System.currentTimeMillis()
        if (now - lastAckCueAt < throttleMs) {
            return
        }
        lastAckCueAt = now

        Thread {
            val cueFile = jarvisCueFile(text)
            val audioBytes = cueAudioCache[text]
                ?: runCatching { cueFile.takeIf { it.exists() }?.readBytes() }.getOrNull()
                ?: runCatching {
                    JarvisApiClient().fetchTtsAudio(
                        baseUrl = prefs.getBackendUrl(),
                        authToken = prefs.getAuthToken(),
                        text = text,
                    )
                }.onSuccess { fetched ->
                    cueAudioCache[text] = fetched
                    if (fetched.isNotEmpty()) {
                        runCatching { cueFile.writeBytes(fetched) }
                    }
                }.getOrNull()

            if (audioBytes == null || audioBytes.isEmpty()) {
                logger.log("Jarvis acknowledgement cue unavailable")
                return@Thread
            }

            mainHandler.post {
                runCatching {
                    val tempFile = File.createTempFile("jarvis-ack-", ".mp3", cacheDir)
                    tempFile.writeBytes(audioBytes)
                    isSpeaking = true
                    val player = MediaPlayer().apply {
                        setDataSource(tempFile.absolutePath)
                        setOnCompletionListener {
                            cuePlayers.remove(it)
                            runCatching { it.release() }
                            tempFile.delete()
                            if (!isCuePlaybackActive() && currentPlayer == null) {
                                isSpeaking = false
                            }
                        }
                        setOnErrorListener { mp, _, _ ->
                            cuePlayers.remove(mp)
                            runCatching { mp.release() }
                            tempFile.delete()
                            if (!isCuePlaybackActive() && currentPlayer == null) {
                                isSpeaking = false
                            }
                            true
                        }
                        prepare()
                        start()
                    }
                    cuePlayers += player
                }.onFailure {
                    if (!isCuePlaybackActive() && currentPlayer == null) {
                        isSpeaking = false
                    }
                    logger.log("Jarvis acknowledgement playback failed: ${it.message}")
                }
            }
        }.start()
    }

    private fun warmJarvisCueCache() {
        if (!prefs.isListeningCueEnabled()) {
            return
        }
        Thread {
            JARVIS_CUE_PHRASES.forEach { phrase ->
                if (cueAudioCache.containsKey(phrase)) {
                    return@forEach
                }

                val cueFile = jarvisCueFile(phrase)
                if (cueFile.exists()) {
                    runCatching { cueAudioCache[phrase] = cueFile.readBytes() }
                    return@forEach
                }

                runCatching {
                    JarvisApiClient().fetchTtsAudio(
                        baseUrl = prefs.getBackendUrl(),
                        authToken = prefs.getAuthToken(),
                        text = phrase,
                    )
                }.onSuccess { audioBytes ->
                    if (audioBytes.isNotEmpty()) {
                        cueAudioCache[phrase] = audioBytes
                        runCatching { cueFile.writeBytes(audioBytes) }
                    }
                }.onFailure {
                    logger.log("Jarvis cue warmup failed for '$phrase': ${it.message}")
                }
            }
        }.start()
    }

    private fun jarvisCueFile(text: String): File {
        val index = JARVIS_CUE_PHRASES.indexOf(text).takeIf { it >= 0 } ?: text.hashCode()
        return File(filesDir, "jarvis-cue-$index.mp3")
    }

    private fun buildRecognizerIntent(): Intent {
        val completeSilenceMs = if (awaitingFollowup) 4_500L else 2_200L
        val possibleSilenceMs = if (awaitingFollowup) 2_500L else 1_500L
        val minimumSpeechMs = if (awaitingFollowup) 500L else 300L
        return Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, false)
            putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, false)
            putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 3)
            putExtra(RecognizerIntent.EXTRA_CALLING_PACKAGE, packageName)
            putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_COMPLETE_SILENCE_LENGTH_MILLIS, completeSilenceMs)
            putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_POSSIBLY_COMPLETE_SILENCE_LENGTH_MILLIS, possibleSilenceMs)
            putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_MINIMUM_LENGTH_MILLIS, minimumSpeechMs)
        }
    }

    private fun normalizeCommand(text: String): String {
        return text
            .lowercase()
            .replace(Regex("""\s+"""), " ")
            .trim()
    }

    private fun isReadRecentMessageRequest(normalized: String): Boolean {
        return normalized in setOf(
            "read my last message",
            "read last message",
            "read recent message",
            "read my recent message",
            "what was my last message",
            "what is my last message",
        ) || (
            normalized.contains("last message") &&
                (normalized.contains("read") || normalized.contains("what"))
            )
    }

    private fun readRecentMessageAloud() {
        val summary = prefs.getRecentMessageSummary()
            ?: "I do not have a recent message notification to read."
        clearFollowupState()
        updateNotification(summary)
        playJarvisCue(summary, throttleMs = 600L)
        scheduleRestart(delayMs = 1800L)
    }

    private fun shouldAwaitFollowup(reply: String): Boolean {
        val normalized = reply.lowercase()
        return normalized.contains("?") ||
            normalized.contains("normal or whatsapp") ||
            normalized.contains("normally or on whatsapp")
    }

    private fun pollPendingActions() {
        if (isPollingActions) {
            return
        }

        val baseUrl = prefs.getBackendUrl()
        val deviceId = prefs.getDeviceId()
        if (baseUrl.isBlank() || deviceId.isBlank()) {
            return
        }

        isPollingActions = true
        Thread {
            val api = JarvisApiClient()
            val poller = PendingPhoneActionPoller(api, logger)
            val authToken = prefs.getAuthToken()
            val executor = PendingPhoneActionExecutor(applicationContext, logger)
            runCatching {
                val contacts = ContactLookupService(applicationContext).listContactCandidates()
                api.syncContacts(
                    baseUrl = baseUrl,
                    authToken = authToken,
                    deviceId = deviceId,
                    contacts = contacts,
                )
                logger.log("Synced ${contacts.size} contacts to Jarvis backend")
            }.onFailure { error ->
                logger.log("Contact sync skipped: ${error.message}")
            }
            poller.fetchPendingActions(
                baseUrl = baseUrl,
                authToken = authToken,
                deviceId = deviceId,
                phoneNumber = "",
            ).onSuccess { actions ->
                actions.forEach { action ->
                    val sensitive = action.requiresVerifiedSpeaker ||
                        action.actionType.lowercase() in setOf("answer_call", "reject_call", "place_call", "draft_message")
                    val verification = if (sensitive) {
                        val trustedNow = System.currentTimeMillis() <= trustedVoiceVerifiedUntil
                        if (trustedNow) {
                            SpeakerVerificationResult(SpeakerVerificationStatus.VERIFIED, 1f, "Trusted voice window active.")
                        } else {
                            mainHandler.post {
                                updateNotification("Verifying your voice before phone action...")
                                playJarvisCue("Verifying voice.", throttleMs = 600L)
                                releaseSpeechRecognizer()
                            }
                            Thread.sleep(1300L)
                            verifyLiveVoiceWithBackend("sensitive").also { result ->
                                if (result.status == SpeakerVerificationStatus.VERIFIED) {
                                    trustedVoiceVerifiedUntil = System.currentTimeMillis() + TRUSTED_VOICE_WINDOW_MS
                                }
                            }
                        }
                    } else {
                        SpeakerVerificationResult(SpeakerVerificationStatus.VERIFIED, 1f, "Verification not required.")
                    }

                    val result = if (verification.status == SpeakerVerificationStatus.VERIFIED) {
                        executor.execute(action)
                    } else {
                        val message = when (verification.status) {
                            SpeakerVerificationStatus.UNCERTAIN -> {
                                if (action.actionType.lowercase() in setOf("place_call", "draft_message", "answer_call", "reject_call")) {
                                    "That sounds like you, but I need a clearer match before phone actions."
                                } else {
                                    pendingUncertainPhoneAction = action
                                    pendingUncertainPhoneActionUntil = System.currentTimeMillis() + PHONE_ACTION_CONFIRM_WINDOW_MS
                                    mainHandler.post {
                                        updateState("confirming", "That sounds like you, but I want to be sure. Should I continue?")
                                        playJarvisCue("That sounds like you, but I want to be sure. Should I continue?", throttleMs = 600L)
                                    }
                                    "Awaiting confirmation after uncertain voice match."
                                }
                            }
                            SpeakerVerificationStatus.UNAVAILABLE ->
                                "Voice verification is unavailable. I won't place the call."
                            SpeakerVerificationStatus.NOT_VERIFIED ->
                                "I can't confirm it's you. I won't place the call."
                            SpeakerVerificationStatus.VERIFIED ->
                                "Voice verified."
                        }
                        Result.failure(IllegalStateException(message))
                    }

                    val status = if (result.isSuccess) "completed" else if (pendingUncertainPhoneAction?.actionId == action.actionId) "pending_confirmation" else "failed"
                    val detail = result.getOrNull() ?: result.exceptionOrNull()?.message.orEmpty()
                    logger.log(
                        if (result.isSuccess) {
                            "Phone action completed: ${action.actionType} | $detail"
                        } else {
                            "Phone action failed: ${action.actionType} | ${result.exceptionOrNull()?.message}"
                        }
                    )
                    if (result.isSuccess) {
                        updateNotification(detail.ifBlank { "Phone action completed" })
                    } else {
                        updateNotification(detail.ifBlank { "Phone action blocked" })
                    }

                    if (status != "pending_confirmation") {
                        poller.acknowledge(
                            baseUrl = baseUrl,
                            authToken = authToken,
                            actionId = action.actionId,
                            deviceId = deviceId,
                            phoneNumber = action.phoneNumber.orEmpty(),
                            status = status,
                        )
                    }
                }
            }

            isPollingActions = false
        }.start()
    }

    private fun executeConfirmedPhoneAction(
        action: PendingPhoneAction,
        executor: PendingPhoneActionExecutor,
    ) {
        updateState("acting", "Continuing after confirmation")
        val result = executor.execute(action)
        val detail = result.getOrNull() ?: result.exceptionOrNull()?.message.orEmpty()
        if (result.isSuccess) {
            updateState("success", detail.ifBlank { "Phone action completed" })
        } else {
            updateState("failure", detail.ifBlank { "Phone action failed" })
        }

        Thread {
            PendingPhoneActionPoller(JarvisApiClient(), logger).acknowledge(
                baseUrl = prefs.getBackendUrl(),
                authToken = prefs.getAuthToken(),
                actionId = action.actionId,
                deviceId = prefs.getDeviceId(),
                phoneNumber = action.phoneNumber.orEmpty(),
                status = if (result.isSuccess) "completed" else "failed",
            )
        }.start()
    }

    private fun isConfirmationYes(normalized: String): Boolean {
        return normalized in setOf("yes", "yes continue", "continue", "go ahead", "do it", "proceed", "confirm")
    }

    private fun isConfirmationNo(normalized: String): Boolean {
        return normalized in setOf("no", "cancel", "stop", "do not", "don't", "dont", "never mind")
    }

    private fun updateState(state: String, detail: String) {
        logger.log("Voice state: $state | $detail")
        updateNotification(detail)
    }

    private fun hasMicPermission(): Boolean {
        return ContextCompat.checkSelfPermission(
            this,
            android.Manifest.permission.RECORD_AUDIO
        ) == PackageManager.PERMISSION_GRANTED
    }

    private fun pauseMicForExternalRecognition(durationMs: Long = MANUAL_MIC_PAUSE_MS) {
        isMicPaused = true
        isMicPausedForExternalRecorder = activeExternalRecorderCount > 0
        micPausedUntil = System.currentTimeMillis() + durationMs
        cancelScheduledRestart()
        releaseSpeechRecognizer()
        logger.log("Background voice mic paused for external speech recognition")
        updateNotification(
            if (isMicPausedForExternalRecorder) {
                "Jarvis mic paused while another app records"
            } else {
                "Jarvis mic paused so other apps can listen"
            }
        )
        scheduleRestart(delayMs = if (isMicPausedForExternalRecorder) EXTERNAL_RECORDER_CHECK_MS else durationMs)
    }

    private fun resumeMicListening() {
        isMicPaused = false
        isMicPausedForExternalRecorder = false
        micPausedUntil = 0L
        cancelScheduledRestart()
        logger.log("Background voice mic resumed")
        updateNotification("Listening for Jarvis voice commands")
        startListeningLoop()
    }

    private fun registerRecordingWatcher() {
        val audioManager = getSystemService(AudioManager::class.java) ?: return
        runCatching {
            audioManager.registerAudioRecordingCallback(recordingCallback, mainHandler)
        }.onFailure {
            logger.log("Background voice recording watcher unavailable: ${it.message}")
        }
    }

    private fun unregisterRecordingWatcher() {
        val audioManager = getSystemService(AudioManager::class.java) ?: return
        runCatching {
            audioManager.unregisterAudioRecordingCallback(recordingCallback)
        }
    }

    private fun handleRecordingConfigChanged(configs: List<AudioRecordingConfiguration>) {
        val activeConfigs = configs.filter { config ->
            !config.isClientSilenced
        }
        val hasSilencedRecorder = configs.any { config ->
            config.isClientSilenced
        }
        activeExternalRecorderCount = if (isMicPausedForExternalRecorder) {
            activeConfigs.size
        } else if (hasSilencedRecorder) {
            1
        } else if (activeConfigs.size > 1) {
            activeConfigs.size - 1
        } else {
            0
        }

        if (
            !isMicPaused &&
            activeExternalRecorderCount > 0 &&
            !isRecordingVoiceprint &&
            !isSpeaking
        ) {
            logger.log("External recorder detected; yielding Jarvis mic")
            isMicPaused = true
            isMicPausedForExternalRecorder = true
            micPausedUntil = System.currentTimeMillis() + MANUAL_MIC_PAUSE_MS
            cancelScheduledRestart()
            releaseSpeechRecognizer()
            updateNotification("Jarvis mic paused while another app records")
            scheduleRestart(delayMs = EXTERNAL_RECORDER_CHECK_MS)
            return
        }

        if (isMicPaused && activeExternalRecorderCount == 0 && isMicPausedForExternalRecorder) {
            logger.log("External recorder stopped; resuming Jarvis mic")
            resumeMicListening()
            return
        }

        if (isMicPaused && activeExternalRecorderCount > 0 && !isMicPausedForExternalRecorder) {
            isMicPausedForExternalRecorder = true
            updateNotification("Jarvis mic paused while another app records")
            scheduleRestart(delayMs = EXTERNAL_RECORDER_CHECK_MS)
        }
    }

    private fun buildNotification(text: String): Notification {
        val openIntent = Intent(this, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
        }
        val stopIntent = Intent(this, BackgroundVoiceService::class.java).apply {
            action = ACTION_STOP
        }
        val pauseIntent = Intent(this, BackgroundVoiceService::class.java).apply {
            action = ACTION_PAUSE_MIC
        }
        val resumeIntent = Intent(this, BackgroundVoiceService::class.java).apply {
            action = ACTION_RESUME_MIC
        }

        val contentPendingIntent = PendingIntent.getActivity(
            this,
            10,
            openIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val stopPendingIntent = PendingIntent.getService(
            this,
            11,
            stopIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val pausePendingIntent = PendingIntent.getService(
            this,
            12,
            pauseIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val resumePendingIntent = PendingIntent.getService(
            this,
            13,
            resumeIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        val builder = NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setContentTitle("Jarvis background listening")
            .setContentText(text)
            .setContentIntent(contentPendingIntent)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setSilent(true)
            .setPriority(NotificationCompat.PRIORITY_LOW)

        if (isMicPaused) {
            builder.addAction(0, "Resume mic", resumePendingIntent)
        } else {
            builder.addAction(0, "Pause mic", pausePendingIntent)
        }

        return builder
            .addAction(0, "Stop", stopPendingIntent)
            .build()
    }

    private fun updateNotification(text: String) {
        if (lastNotificationText == text) {
            return
        }
        lastNotificationText = text
        val manager = getSystemService(NotificationManager::class.java) ?: return
        manager.notify(NOTIFICATION_ID, buildNotification(text))
    }

    private fun isCuePlaybackActive(): Boolean {
        return cuePlayers.any { player ->
            runCatching { player.isPlaying }.getOrDefault(false)
        }
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
            return
        }

        val manager = getSystemService(NotificationManager::class.java) ?: return
        val channel = NotificationChannel(
            CHANNEL_ID,
            "Jarvis Background Listening",
            NotificationManager.IMPORTANCE_LOW
        ).apply {
            description = "Keeps Jarvis voice command listening active in the background."
            setSound(null as Uri?, null)
            enableVibration(false)
            setShowBadge(false)
        }
        manager.createNotificationChannel(channel)
    }

    companion object {
        private const val CHANNEL_ID = "jarvis_background_voice"
        private const val NOTIFICATION_ID = 2001
        private const val ACTION_STOP = "com.jarvis.companion.action.STOP_BACKGROUND_VOICE"
        private const val ACTION_PAUSE_MIC = "com.jarvis.companion.action.PAUSE_BACKGROUND_MIC"
        private const val ACTION_RESUME_MIC = "com.jarvis.companion.action.RESUME_BACKGROUND_MIC"
        private const val MANUAL_MIC_PAUSE_MS = 5 * 60_000L
        private const val EXTERNAL_RECORDER_CHECK_MS = 1_500L
        private const val IDLE_RECOGNIZER_RESTART_DELAY_MS = 6_000L
        private const val BUSY_RECOGNIZER_RESTART_DELAY_MS = 2_500L
        private const val ERROR_RECOGNIZER_RESTART_DELAY_MS = 2_000L
        private const val MAX_RECOGNIZER_RESTART_DELAY_MS = 10_000L
        private const val FOLLOWUP_WINDOW_MS = 8_000L
        private const val PENDING_ACTION_POLL_MS = 4_000L
        private const val TRUSTED_VOICE_PROMPT_WINDOW_MS = 8_000L
        private const val TRUSTED_VOICE_WINDOW_MS = 2 * 60_000L
        private const val TRUSTED_VOICE_MAX_RETRIES = 2
        private const val TRUSTED_VOICE_RETRY_DELAY_MS = 700L
        private const val PHONE_ACTION_CONFIRM_WINDOW_MS = 10_000L
        private const val LOCAL_ACK_RESTART_DELAY_MS = 1_300L
        private const val LOCAL_READ_LAST_MESSAGE_COMMAND = "__jarvis_local_read_last_message__"
        private val JARVIS_CUE_PHRASES = arrayOf(
            "Hmm?",
            "I'm listening.",
            "Go ahead.",
            "Yes, Sir?",
            "Ready.",
            "At your service.",
            "I'm with you.",
            "Verifying voice.",
            "Voiceprint did not match.",
            "That sounds like you, but I want to be sure. Should I continue?",
            "Understood. I will not continue.",
        )
        private val WAKE_ONLY_PHRASES = setOf(
            "jarvis",
            "hey jarvis",
            "hello jarvis",
            "hi jarvis",
        )
        private val ANSWER_PHRASES = setOf(
            "answer",
            "answer it",
            "answer now",
            "jarvis answer the call",
            "jarvis answer",
            "pick up",
            "pick it up",
            "jarvis pick up the call",
            "jarvis pick up the phone",
            "jarvis answer the phone",
            "jarvis accept the call",
            "take the call",
            "take it",
            "accept it",
        )
        private val REJECT_PHRASES = setOf(
            "reject",
            "reject it",
            "decline",
            "decline it",
            "jarvis reject the call",
            "jarvis reject",
            "cut it",
            "jarvis decline the call",
            "jarvis cut the call",
            "jarvis hang up the call",
            "hang up",
            "ignore it",
            "ignore the call",
        )

        fun start(context: Context) {
            val intent = Intent(context, BackgroundVoiceService::class.java)
            ContextCompat.startForegroundService(context, intent)
        }

        fun stop(context: Context) {
            val intent = Intent(context, BackgroundVoiceService::class.java).apply {
                action = ACTION_STOP
            }
            context.startService(intent)
        }
    }

    private val pendingActionsRunnable = object : Runnable {
        override fun run() {
            pollPendingActions()
            pendingActionsHandler.postDelayed(this, PENDING_ACTION_POLL_MS)
        }
    }

    private val recordingCallback = object : AudioManager.AudioRecordingCallback() {
        override fun onRecordingConfigChanged(configs: List<AudioRecordingConfiguration>) {
            handleRecordingConfigChanged(configs)
        }
    }
}
