package com.jarvis.companion

import android.content.Context
import java.util.concurrent.ConcurrentHashMap

class IncomingCallCoordinator(private val context: Context) {
    companion object {
        private const val DEDUPE_WINDOW_MS = 60_000L
        private val recentCalls = ConcurrentHashMap<String, Long>()
    }

    fun processIncomingCall(
        phoneNumber: String,
        callerNameHint: String? = null,
        source: String,
        callDirection: String = "incoming",
    ) {
        val appContext = context.applicationContext
        val logger = AppEventLogger(appContext)
        val prefs = JarvisPreferences(appContext)
        val api = JarvisApiClient()
        val notifications = NotificationHelper(appContext)
        val mp3Speaker = Mp3Speaker(appContext)
        val resolver = CallerIdentityResolver(appContext, logger)

        val direction = normalizeCallDirection(callDirection)
        logger.log("${direction.replaceFirstChar { it.uppercase() }} call pipeline started from $source")

        val localMetadata = resolver.localMetadata(phoneNumber)
        val normalizedNumber = localMetadata?.normalizedNumber?.ifBlank { null } ?: normalizePhoneNumber(phoneNumber)
        if (normalizedNumber.isBlank()) {
            logger.log("${direction.replaceFirstChar { it.uppercase() }} call pipeline skipped: no usable phone number")
            return
        }

        if (!shouldProcess(normalizedNumber, direction)) {
            logger.log("${direction.replaceFirstChar { it.uppercase() }} call pipeline deduped for $normalizedNumber from $source")
            return
        }

        val resolvedIdentity = resolver.resolve(normalizedNumber)
        val effectiveNameHint = when {
            !callerNameHint.isNullOrBlank() -> callerNameHint
            resolvedIdentity != null -> resolvedIdentity.displayName
            else -> null
        }

        if (resolvedIdentity?.source == "contacts") {
            logger.log("Saved contact detected, skipping caller lookup")
            handleSavedContactCall(
                normalizedNumber = normalizedNumber,
                displayName = resolvedIdentity.displayName,
                callDirection = direction,
                api = api,
                authToken = prefs.getAuthToken(),
                baseUrl = prefs.getBackendUrl(),
                notifications = notifications,
                mp3Speaker = mp3Speaker,
                voiceEnabled = prefs.isVoiceEnabled(),
                logger = logger,
            )
            return
        }

        notifications.showIncomingCallResult(
            title = "${if (direction == "outgoing") "Outgoing call" else "Incoming call"}: $normalizedNumber",
            body = buildCheckingCallerBody(localMetadata),
        )

        runCatching {
            logger.log("Sending /phone/incoming-call")
            val result = api.sendIncomingCall(
                baseUrl = prefs.getBackendUrl(),
                authToken = prefs.getAuthToken(),
                payload = IncomingCallPayload(
                    phoneNumber = normalizedNumber,
                    callerNameHint = effectiveNameHint,
                    deviceId = prefs.getDeviceId(),
                    speakResult = prefs.isVoiceEnabled(),
                    callDirection = direction,
                )
            )
            logger.log("Received caller lookup response")

            val audioBytes = if (prefs.isVoiceEnabled() && result.speakText.isNotBlank()) {
                logger.log("Fetching MP3 from /tts")
                api.fetchTtsAudio(
                    baseUrl = prefs.getBackendUrl(),
                    authToken = prefs.getAuthToken(),
                    text = result.speakText,
                )
            } else {
                null
            }

            result to audioBytes
        }.onSuccess { (result, audioBytes) ->
            logger.log("Showing notification")
            notifications.showIncomingCallResult(
                title = result.notificationTitle,
                body = result.notificationBody
            )

            if (prefs.isVoiceEnabled() && audioBytes != null) {
                val playResult = mp3Speaker.play(audioBytes)
                if (playResult.isSuccess) {
                    logger.log("MP3 playback started")
                } else {
                    logger.log("MP3 playback failed: ${playResult.exceptionOrNull()?.message}")
                }
            } else {
                logger.log("Voice disabled or no audio returned")
            }

            pollForPhoneActions(
                normalizedNumber = normalizedNumber,
                deviceId = prefs.getDeviceId(),
                baseUrl = prefs.getBackendUrl(),
                authToken = prefs.getAuthToken(),
                api = api,
                logger = logger,
            )
        }.onFailure { error ->
            logger.log("${direction.replaceFirstChar { it.uppercase() }} call flow failed: ${error.message}")
            notifications.showIncomingCallResult(
                title = "Jarvis ${direction} call lookup unavailable",
                body = error.message ?: "The backend could not be reached."
            )
        }
    }

    private fun handleSavedContactCall(
        normalizedNumber: String,
        displayName: String,
        callDirection: String,
        api: JarvisApiClient,
        authToken: String,
        baseUrl: String,
        notifications: NotificationHelper,
        mp3Speaker: Mp3Speaker,
        voiceEnabled: Boolean,
        logger: AppEventLogger,
    ) {
        val titlePrefix = if (callDirection == "outgoing") "Outgoing call" else "Incoming call"
        val title = "$titlePrefix: $displayName"
        val body = if (callDirection == "outgoing") {
            "Saved contact being called at $normalizedNumber"
        } else {
            "Saved contact calling from $normalizedNumber"
        }
        val speakText = buildSavedContactSpeech(displayName, callDirection)

        logger.log("Showing saved-contact notification")
        notifications.showIncomingCallResult(
            title = title,
            body = body
        )

        if (!voiceEnabled) {
            logger.log("Voice disabled for saved contact")
            return
        }

        runCatching {
            logger.log("Fetching saved-contact MP3 from /tts")
            api.fetchTtsAudio(
                baseUrl = baseUrl,
                authToken = authToken,
                text = speakText,
            )
        }.onSuccess { audioBytes ->
            val playResult = mp3Speaker.play(audioBytes)
            if (playResult.isSuccess) {
                logger.log("Saved-contact MP3 playback started")
            } else {
                logger.log("Saved-contact MP3 playback failed: ${playResult.exceptionOrNull()?.message}")
            }
        }.onFailure { error ->
            logger.log("Saved-contact voice fetch failed: ${error.message}")
        }
    }

    private fun buildSavedContactSpeech(displayName: String, callDirection: String): String {
        val cleaned = displayName.trim()
        if (cleaned.isBlank()) {
            return if (callDirection == "outgoing") {
                "You are calling a saved contact."
            } else {
                "A saved contact is calling you."
            }
        }

        val compact = cleaned.replace(Regex("""\s+"""), " ")
        val words = compact.split(" ").filter { it.isNotBlank() }

        return when {
            callDirection == "outgoing" && words.size == 1 -> "Calling $compact."
            callDirection == "outgoing" && words.size <= 3 -> "You are calling $compact."
            callDirection == "outgoing" -> "Outgoing call to $compact."
            words.size == 1 -> "$compact is calling."
            words.size <= 3 -> "$compact is calling you."
            else -> "Incoming call from $compact."
        }
    }

    private fun normalizePhoneNumber(phoneNumber: String): String {
        return phoneNumber.trim().replace(Regex("""[^\d+]"""), "")
    }

    private fun buildCheckingCallerBody(localMetadata: CallerIdentity?): String {
        if (localMetadata == null) {
            return "Checking caller identity with Jarvis..."
        }

        val details = listOf(
            localMetadata.lineType.takeIf { it.isNotBlank() && it != "unknown" },
            localMetadata.country.takeIf { it.isNotBlank() },
        ).filterNotNull()

        return if (details.isEmpty()) {
            "Checking caller identity with Jarvis..."
        } else {
            "Checking caller identity. Local metadata: ${details.joinToString(", ")}."
        }
    }

    private fun dedupePhoneKey(phoneNumber: String): String {
        val digits = phoneNumber.filter { it.isDigit() }
        if (digits.isBlank()) {
            return phoneNumber.trim()
        }
        return if (digits.length > 10) digits.takeLast(10) else digits
    }

    private fun pollForPhoneActions(
        normalizedNumber: String,
        deviceId: String,
        baseUrl: String,
        authToken: String,
        api: JarvisApiClient,
        logger: AppEventLogger,
    ) {
        val poller = PendingPhoneActionPoller(api, logger)
        val executor = PendingPhoneActionExecutor(context.applicationContext, logger)
        repeat(12) {
            Thread.sleep(1500)
            val actions = poller.fetchPendingActions(
                baseUrl = baseUrl,
                authToken = authToken,
                deviceId = deviceId,
                phoneNumber = normalizedNumber,
            ).getOrElse {
                return
            }

            val action = actions.firstOrNull { it.status == "pending" } ?: return@repeat
            val result = executor.execute(action)
            if (result.isSuccess) {
                logger.log("${action.actionType} succeeded from backend command")
                poller.acknowledge(
                    baseUrl = baseUrl,
                    authToken = authToken,
                    actionId = action.actionId,
                    deviceId = deviceId,
                    phoneNumber = normalizedNumber,
                    status = "completed",
                )
            } else {
                logger.log("${action.actionType} failed: ${result.exceptionOrNull()?.message}")
                poller.acknowledge(
                    baseUrl = baseUrl,
                    authToken = authToken,
                    actionId = action.actionId,
                    deviceId = deviceId,
                    phoneNumber = normalizedNumber,
                    status = "failed",
                )
            }
            return
        }
    }

    private fun shouldProcess(normalizedNumber: String, callDirection: String): Boolean {
        val now = System.currentTimeMillis()
        val dedupeKey = "$callDirection|${dedupePhoneKey(normalizedNumber)}"

        recentCalls.entries.removeIf { now - it.value > DEDUPE_WINDOW_MS }

        val previous = recentCalls.putIfAbsent(dedupeKey, now)
        if (previous == null) {
            return true
        }

        if (now - previous > DEDUPE_WINDOW_MS) {
            recentCalls[dedupeKey] = now
            return true
        }

        return false
    }

    private fun normalizeCallDirection(callDirection: String): String {
        return if (callDirection.trim().equals("outgoing", ignoreCase = true)) {
            "outgoing"
        } else {
            "incoming"
        }
    }
}
