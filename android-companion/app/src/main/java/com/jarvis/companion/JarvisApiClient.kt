package com.jarvis.companion

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.TimeUnit

data class IncomingCallPayload(
    val phoneNumber: String,
    val callerNameHint: String?,
    val deviceId: String,
    val speakResult: Boolean,
    val callDirection: String,
)

data class IncomingCallResult(
    val eventId: String,
    val phoneNumber: String,
    val normalizedNumber: String,
    val summary: String,
    val callDirection: String,
    val notificationTitle: String,
    val notificationBody: String,
    val speakText: String,
    val publicDataOnly: Boolean,
    val results: List<String>,
    val source: String,
    val confidence: Float,
    val displayName: String,
    val carrier: String,
    val lineType: String,
    val country: String,
    val location: String,
    val spamRisk: String,
)

data class PendingPhoneAction(
    val actionId: String,
    val actionType: String,
    val status: String,
    val deviceId: String,
    val phoneNumber: String?,
    val contactName: String?,
    val callMethod: String?,
    val message: String,
    val contactId: String?,
    val matchConfidence: Float?,
    val matchReason: String?,
    val channel: String?,
    val messageBody: String?,
    val requiresVerifiedSpeaker: Boolean,
    val verificationStatus: String?,
)

data class ChatResult(
    val response: String,
    val sessionId: String,
)

data class VoiceStatusResult(
    val available: Boolean,
    val backend: String,
    val modelName: String,
    val modelSource: String,
    val device: String,
    val profileExists: Boolean,
    val profileEnrolled: Boolean,
    val profileId: String,
    val displayName: String,
    val requiredSamples: Int,
    val acceptedSamples: Int,
)

data class VoiceEnrollResult(
    val enrolled: Boolean,
    val status: String,
    val sampleAccepted: Boolean,
    val sampleReason: String,
    val acceptedSamples: Int,
    val requiredSamples: Int,
    val profileId: String,
    val modelName: String,
    val modelSource: String,
)

data class VoiceVerifyResult(
    val allowed: Boolean,
    val status: String,
    val confidence: Float,
    val reason: String,
)

data class StreamChatEvent(
    val sessionId: String? = null,
    val chunk: String? = null,
    val audio: ByteArray? = null,
    val done: Boolean = false,
    val error: String? = null,
)

class JarvisApiClient {
    private val client = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(25, TimeUnit.SECONDS)
        .writeTimeout(10, TimeUnit.SECONDS)
        .build()
    private val callerLookupClient = client.newBuilder()
        .connectTimeout(2, TimeUnit.SECONDS)
        .readTimeout(3, TimeUnit.SECONDS)
        .writeTimeout(2, TimeUnit.SECONDS)
        .build()

    fun sendIncomingCall(baseUrl: String, authToken: String, payload: IncomingCallPayload): IncomingCallResult {
        val bodyJson = JSONObject()
            .put("phone_number", payload.phoneNumber)
            .put("caller_name_hint", payload.callerNameHint)
            .put("device_id", payload.deviceId)
            .put("speak_result", payload.speakResult)
            .put("call_direction", payload.callDirection)

        return executeAgainstCandidates(baseUrl) { normalizedBaseUrl ->
            val requestBuilder = Request.Builder()
                .url("${normalizedBaseUrl}/phone/incoming-call")
                .post(bodyJson.toString().toRequestBody(JSON.toMediaType()))
                .addHeader("Content-Type", JSON)

            if (authToken.isNotBlank()) {
                requestBuilder.addHeader("X-Jarvis-Token", authToken)
            }

            callerLookupClient.newCall(requestBuilder.build()).execute().use { response ->
                if (!response.isSuccessful) {
                    val details = response.body?.string().orEmpty().ifBlank { "No response body" }
                    throw IllegalStateException("Jarvis backend returned HTTP ${response.code}: $details")
                }

                val raw = response.body?.string().orEmpty()
                val json = JSONObject(raw)
                IncomingCallResult(
                    eventId = json.optString("event_id"),
                    phoneNumber = json.optString("phone_number"),
                    normalizedNumber = json.optString("normalized_number"),
                    summary = json.optString("summary"),
                    callDirection = json.optString("call_direction", "incoming"),
                    notificationTitle = json.optString("notification_title"),
                    notificationBody = json.optString("notification_body"),
                    speakText = json.optString("speak_text"),
                    publicDataOnly = json.optBoolean("public_data_only", true),
                    results = readResults(json.optJSONArray("results")),
                    source = json.optString("source"),
                    confidence = json.optDouble("confidence", 0.0).toFloat(),
                    displayName = json.optString("display_name"),
                    carrier = json.optString("carrier"),
                    lineType = json.optString("line_type"),
                    country = json.optString("country"),
                    location = json.optString("location"),
                    spamRisk = json.optString("spam_risk"),
                )
            }
        }
    }

    fun fetchTtsAudio(baseUrl: String, authToken: String, text: String): ByteArray {
        val bodyJson = JSONObject()
            .put("text", text)

        return executeAgainstCandidates(baseUrl) { normalizedBaseUrl ->
            val requestBuilder = Request.Builder()
                .url("${normalizedBaseUrl}/tts")
                .post(bodyJson.toString().toRequestBody(JSON.toMediaType()))
                .addHeader("Content-Type", JSON)

            if (authToken.isNotBlank()) {
                requestBuilder.addHeader("X-Jarvis-Token", authToken)
            }

            client.newCall(requestBuilder.build()).execute().use { response ->
                if (!response.isSuccessful) {
                    val details = response.body?.string().orEmpty().ifBlank { "No response body" }
                    throw IllegalStateException("Jarvis TTS returned HTTP ${response.code}: $details")
                }
                response.body?.bytes() ?: throw IllegalStateException("Jarvis TTS returned no audio")
            }
        }
    }

    fun sendChat(
        baseUrl: String,
        authToken: String,
        message: String,
        sessionId: String? = null,
    ): ChatResult {
        val bodyJson = JSONObject()
            .put("message", message)
            .put("session_id", sessionId)
            .put("tts", false)

        return executeAgainstCandidates(baseUrl) { normalizedBaseUrl ->
            val requestBuilder = Request.Builder()
                .url("${normalizedBaseUrl}/agent")
                .post(bodyJson.toString().toRequestBody(JSON.toMediaType()))
                .addHeader("Content-Type", JSON)

            if (authToken.isNotBlank()) {
                requestBuilder.addHeader("X-Jarvis-Token", authToken)
            }

            client.newCall(requestBuilder.build()).execute().use { response ->
                if (!response.isSuccessful) {
                    val details = response.body?.string().orEmpty().ifBlank { "No response body" }
                    throw IllegalStateException("Jarvis chat returned HTTP ${response.code}: $details")
                }

                val raw = response.body?.string().orEmpty()
                val json = JSONObject(raw)
                ChatResult(
                    response = json.optString("response"),
                    sessionId = json.optString("session_id"),
                )
            }
        }
    }

    fun getVoiceStatus(baseUrl: String, authToken: String): VoiceStatusResult {
        return executeAgainstCandidates(baseUrl) { normalizedBaseUrl ->
            val requestBuilder = Request.Builder()
                .url("${normalizedBaseUrl}/voice/status")
                .get()

            if (authToken.isNotBlank()) {
                requestBuilder.addHeader("X-Jarvis-Token", authToken)
            }

            client.newCall(requestBuilder.build()).execute().use { response ->
                if (!response.isSuccessful) {
                    val details = response.body?.string().orEmpty().ifBlank { "No response body" }
                    throw IllegalStateException("Jarvis voice status returned HTTP ${response.code}: $details")
                }

                val raw = response.body?.string().orEmpty()
                val json = JSONObject(raw)
                VoiceStatusResult(
                    available = json.optBoolean("available", false),
                    backend = json.optString("backend"),
                    modelName = json.optString("model_name"),
                    modelSource = json.optString("model_source"),
                    device = json.optString("device"),
                    profileExists = json.optBoolean("profile_exists", false),
                    profileEnrolled = json.optBoolean("profile_enrolled", false),
                    profileId = json.optString("profile_id"),
                    displayName = json.optString("display_name"),
                    requiredSamples = json.optInt("required_samples", 3),
                    acceptedSamples = json.optInt("accepted_samples", 0),
                )
            }
        }
    }

    fun enrollVoiceSample(
        baseUrl: String,
        authToken: String,
        audioBase64: String,
        clientType: String,
        deviceId: String,
        replaceExisting: Boolean,
    ): VoiceEnrollResult {
        val bodyJson = JSONObject()
            .put("audio_base64", audioBase64)
            .put("client_type", clientType)
            .put("device_id", deviceId)
            .put("replace_existing", replaceExisting)

        return executeAgainstCandidates(baseUrl) { normalizedBaseUrl ->
            val requestBuilder = Request.Builder()
                .url("${normalizedBaseUrl}/voice/enroll")
                .post(bodyJson.toString().toRequestBody(JSON.toMediaType()))
                .addHeader("Content-Type", JSON)

            if (authToken.isNotBlank()) {
                requestBuilder.addHeader("X-Jarvis-Token", authToken)
            }

            client.newCall(requestBuilder.build()).execute().use { response ->
                if (!response.isSuccessful) {
                    val details = response.body?.string().orEmpty().ifBlank { "No response body" }
                    throw IllegalStateException("Jarvis voice enroll returned HTTP ${response.code}: $details")
                }

                val raw = response.body?.string().orEmpty()
                val json = JSONObject(raw)
                VoiceEnrollResult(
                    enrolled = json.optBoolean("enrolled", false),
                    status = json.optString("status"),
                    sampleAccepted = json.optBoolean("sample_accepted", false),
                    sampleReason = json.optString("sample_reason"),
                    acceptedSamples = json.optInt("accepted_samples", 0),
                    requiredSamples = json.optInt("required_samples", 3),
                    profileId = json.optString("profile_id"),
                    modelName = json.optString("model_name"),
                    modelSource = json.optString("model_source"),
                )
            }
        }
    }

    fun verifyVoiceSample(
        baseUrl: String,
        authToken: String,
        audioBase64: String,
        clientType: String,
        deviceId: String,
        commandPolicy: String,
    ): VoiceVerifyResult {
        val bodyJson = JSONObject()
            .put("audio_base64", audioBase64)
            .put("client_type", clientType)
            .put("device_id", deviceId)
            .put("command_policy", commandPolicy)

        return executeAgainstCandidates(baseUrl) { normalizedBaseUrl ->
            val requestBuilder = Request.Builder()
                .url("${normalizedBaseUrl}/voice/verify")
                .post(bodyJson.toString().toRequestBody(JSON.toMediaType()))
                .addHeader("Content-Type", JSON)

            if (authToken.isNotBlank()) {
                requestBuilder.addHeader("X-Jarvis-Token", authToken)
            }

            client.newCall(requestBuilder.build()).execute().use { response ->
                if (!response.isSuccessful) {
                    val details = response.body?.string().orEmpty().ifBlank { "No response body" }
                    throw IllegalStateException("Jarvis voice verify returned HTTP ${response.code}: $details")
                }

                val raw = response.body?.string().orEmpty()
                val json = JSONObject(raw)
                VoiceVerifyResult(
                    allowed = json.optBoolean("allowed", false),
                    status = json.optString("status"),
                    confidence = json.optDouble("confidence", 0.0).toFloat(),
                    reason = json.optString("reason"),
                )
            }
        }
    }

    fun streamJarvisChat(
        baseUrl: String,
        authToken: String,
        message: String,
        sessionId: String? = null,
        tts: Boolean = true,
        inputSource: String = "text",
        voiceAudioBase64: String? = null,
        onEvent: (StreamChatEvent) -> Unit,
    ) {
        val bodyJson = JSONObject()
            .put("message", message)
            .put("session_id", sessionId)
            .put("tts", tts)
            .put("input_source", inputSource)
            .put("voice_audio_base64", voiceAudioBase64)

        executeAgainstCandidates(baseUrl) { normalizedBaseUrl ->
            val requestBuilder = Request.Builder()
                .url("${normalizedBaseUrl}/chat/jarvis/stream")
                .post(bodyJson.toString().toRequestBody(JSON.toMediaType()))
                .addHeader("Content-Type", JSON)
                .addHeader("Accept", "text/event-stream")

            if (authToken.isNotBlank()) {
                requestBuilder.addHeader("X-Jarvis-Token", authToken)
            }

            client.newCall(requestBuilder.build()).execute().use { response ->
                if (!response.isSuccessful) {
                    val details = response.body?.string().orEmpty().ifBlank { "No response body" }
                    throw IllegalStateException("Jarvis stream returned HTTP ${response.code}: $details")
                }

                val body = response.body ?: throw IllegalStateException("Jarvis stream returned no body")
                body.charStream().buffered().useLines { lines ->
                    lines.forEach { rawLine ->
                        val line = rawLine.trim()
                        if (!line.startsWith("data:")) {
                            return@forEach
                        }

                        val payload = line.removePrefix("data:").trim()
                        if (payload.isBlank()) {
                            return@forEach
                        }

                        val json = JSONObject(payload)
                        val audio = json.optString("audio").takeIf { it.isNotBlank() }?.let {
                            android.util.Base64.decode(it, android.util.Base64.DEFAULT)
                        }
                        val event = StreamChatEvent(
                            sessionId = json.optString("session_id").ifBlank { null },
                            chunk = json.optString("chunk").takeIf { json.has("chunk") },
                            audio = audio,
                            done = json.optBoolean("done", false),
                            error = json.optString("error").ifBlank { null },
                        )
                        onEvent(event)
                    }
                }
            }
        }
    }

    fun fetchPendingPhoneActions(
        baseUrl: String,
        authToken: String,
        deviceId: String,
        phoneNumber: String,
    ): List<PendingPhoneAction> {
        return executeAgainstCandidates(baseUrl) { normalizedBaseUrl ->
            val url = "${normalizedBaseUrl}/phone/pending-actions?device_id=${encode(deviceId)}&phone_number=${encode(phoneNumber)}"
            val requestBuilder = Request.Builder()
                .url(url)
                .get()

            if (authToken.isNotBlank()) {
                requestBuilder.addHeader("X-Jarvis-Token", authToken)
            }

            client.newCall(requestBuilder.build()).execute().use { response ->
                if (!response.isSuccessful) {
                    val details = response.body?.string().orEmpty().ifBlank { "No response body" }
                    throw IllegalStateException("Jarvis pending-actions returned HTTP ${response.code}: $details")
                }

                val raw = response.body?.string().orEmpty()
                val json = JSONObject(raw)
                val actions = json.optJSONArray("actions") ?: JSONArray()
                val items = mutableListOf<PendingPhoneAction>()
                for (i in 0 until actions.length()) {
                    val obj = actions.optJSONObject(i) ?: continue
                    items += PendingPhoneAction(
                        actionId = obj.optString("action_id"),
                        actionType = obj.optString("action_type"),
                        status = obj.optString("status"),
                        deviceId = obj.optString("device_id"),
                        phoneNumber = obj.optString("phone_number").ifBlank { null },
                        contactName = obj.optString("contact_name").ifBlank { null },
                        callMethod = obj.optString("call_method").ifBlank { null },
                        message = obj.optString("message"),
                        contactId = obj.optString("contact_id").ifBlank { null },
                        matchConfidence = if (obj.has("match_confidence") && !obj.isNull("match_confidence")) {
                            obj.optDouble("match_confidence").toFloat()
                        } else {
                            null
                        },
                        matchReason = obj.optString("match_reason").ifBlank { null },
                        channel = obj.optString("channel").ifBlank { null },
                        messageBody = obj.optString("message_body").ifBlank { null },
                        requiresVerifiedSpeaker = obj.optBoolean("requires_verified_speaker", true),
                        verificationStatus = obj.optString("verification_status").ifBlank { null },
                    )
                }
                items
            }
        }
    }

    fun syncContacts(
        baseUrl: String,
        authToken: String,
        deviceId: String,
        contacts: List<ContactCandidate>,
    ) {
        val contactsJson = JSONArray()
        contacts.forEach { contact ->
            contactsJson.put(
                JSONObject()
                    .put("contact_id", contact.contactId)
                    .put("display_name", contact.displayName)
                    .put("phone_number", contact.phoneNumber)
                    .put("aliases", JSONArray(contact.aliases))
                    .put("favorite", contact.favorite)
                    .put("recent", contact.lastContacted > 0L && System.currentTimeMillis() - contact.lastContacted < CONTACT_RECENT_WINDOW_MS)
                    .put("frequent", contact.timesContacted >= 5)
            )
        }
        val bodyJson = JSONObject()
            .put("device_id", deviceId)
            .put("contacts", contactsJson)

        executeAgainstCandidates(baseUrl) { normalizedBaseUrl ->
            val requestBuilder = Request.Builder()
                .url("${normalizedBaseUrl}/phone/contacts/sync")
                .post(bodyJson.toString().toRequestBody(JSON.toMediaType()))
                .addHeader("Content-Type", JSON)

            if (authToken.isNotBlank()) {
                requestBuilder.addHeader("X-Jarvis-Token", authToken)
            }

            client.newCall(requestBuilder.build()).execute().use { response ->
                if (!response.isSuccessful) {
                    val details = response.body?.string().orEmpty().ifBlank { "No response body" }
                    throw IllegalStateException("Jarvis contact sync returned HTTP ${response.code}: $details")
                }
            }
        }
    }

    fun acknowledgePhoneAction(
        baseUrl: String,
        authToken: String,
        actionId: String,
        deviceId: String,
        phoneNumber: String,
        status: String = "completed",
    ) {
        val bodyJson = JSONObject()
            .put("action_id", actionId)
            .put("status", status)
            .put("device_id", deviceId)
            .put("phone_number", phoneNumber)

        executeAgainstCandidates(baseUrl) { normalizedBaseUrl ->
            val requestBuilder = Request.Builder()
                .url("${normalizedBaseUrl}/phone/pending-actions/ack")
                .post(bodyJson.toString().toRequestBody(JSON.toMediaType()))
                .addHeader("Content-Type", JSON)

            if (authToken.isNotBlank()) {
                requestBuilder.addHeader("X-Jarvis-Token", authToken)
            }

            client.newCall(requestBuilder.build()).execute().use { response ->
                if (!response.isSuccessful) {
                    val details = response.body?.string().orEmpty().ifBlank { "No response body" }
                    throw IllegalStateException("Jarvis phone action ack returned HTTP ${response.code}: $details")
                }
            }
        }
    }

    fun resolveReachableBaseUrl(baseUrl: String, authToken: String = ""): String {
        return executeAgainstCandidates(baseUrl) { normalizedBaseUrl ->
            val requestBuilder = Request.Builder()
                .url("${normalizedBaseUrl}/health")
                .get()

            if (authToken.isNotBlank()) {
                requestBuilder.addHeader("X-Jarvis-Token", authToken)
            }

            client.newCall(requestBuilder.build()).execute().use { response ->
                if (!response.isSuccessful) {
                    throw IllegalStateException("Jarvis health returned HTTP ${response.code}")
                }
                normalizedBaseUrl
            }
        }
    }

    private fun candidateBaseUrls(baseUrl: String): List<String> {
        val normalized = JarvisPreferences.splitBackendUrls(baseUrl)
        if (normalized.isEmpty()) {
            throw IllegalStateException("Jarvis backend URL is empty")
        }
        return normalized
    }

    private fun <T> executeAgainstCandidates(baseUrl: String, block: (String) -> T): T {
        val candidates = candidateBaseUrls(baseUrl)
        var lastError: Exception? = null

        for (candidate in candidates) {
            try {
                return block(candidate)
            } catch (error: Exception) {
                lastError = error
            }
        }

        throw IllegalStateException(
            buildString {
                append("None of the configured Jarvis backend URLs responded")
                if (candidates.isNotEmpty()) {
                    append(": ")
                    append(candidates.joinToString(", "))
                }
                lastError?.message?.let {
                    append(". Last error: ")
                    append(it)
                }
            },
            lastError
        )
    }

    private fun readResults(array: JSONArray?): List<String> {
        if (array == null) {
            return emptyList()
        }

        val items = mutableListOf<String>()
        for (i in 0 until array.length()) {
            val obj = array.optJSONObject(i) ?: continue
            val title = obj.optString("title")
            val url = obj.optString("url")
            if (title.isNotBlank() || url.isNotBlank()) {
                items += listOf(title, url).filter { it.isNotBlank() }.joinToString(" | ")
            }
        }
        return items
    }

    companion object {
        private const val JSON = "application/json; charset=utf-8"
        private const val CONTACT_RECENT_WINDOW_MS = 30L * 24L * 60L * 60L * 1000L

        private fun encode(value: String): String {
            return java.net.URLEncoder.encode(value, "UTF-8")
        }
    }
}
