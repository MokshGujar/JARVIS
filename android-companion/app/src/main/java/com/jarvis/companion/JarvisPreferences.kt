package com.jarvis.companion

import android.content.Context
import android.provider.Settings

class JarvisPreferences(context: Context) {
    private val prefs = context.getSharedPreferences("jarvis_companion", Context.MODE_PRIVATE)
    private val appContext = context.applicationContext

    fun getWifiBackendUrl(): String {
        val stored = prefs.getString(KEY_BACKEND_URL_WIFI, null).orEmpty()
        if (stored.isNotBlank()) {
            return normalizeBackendUrl(stored)
        }

        val legacy = splitBackendUrls(prefs.getString(KEY_BACKEND_URL, DEFAULT_BACKEND_URL).orEmpty())
        return legacy.getOrNull(0).orEmpty()
    }

    fun setWifiBackendUrl(value: String) {
        prefs.edit().putString(KEY_BACKEND_URL_WIFI, normalizeBackendUrl(value)).apply()
    }

    fun getEthernetBackendUrl(): String {
        val stored = prefs.getString(KEY_BACKEND_URL_ETHERNET, null).orEmpty()
        if (stored.isNotBlank()) {
            return normalizeBackendUrl(stored)
        }

        val legacy = splitBackendUrls(prefs.getString(KEY_BACKEND_URL, DEFAULT_BACKEND_URL).orEmpty())
        return legacy.getOrNull(1).orEmpty()
    }

    fun setEthernetBackendUrl(value: String) {
        prefs.edit().putString(KEY_BACKEND_URL_ETHERNET, normalizeBackendUrl(value)).apply()
    }

    fun getBackendUrl(): String {
        val combined = listOf(
            getWifiBackendUrl(),
            getEthernetBackendUrl(),
        ).filter { it.isNotBlank() }

        if (combined.isNotEmpty()) {
            return combined.joinToString("\n")
        }

        return normalizeBackendUrls(prefs.getString(KEY_BACKEND_URL, DEFAULT_BACKEND_URL).orEmpty())
    }

    fun setBackendUrl(value: String) {
        val urls = splitBackendUrls(value)
        setWifiBackendUrl(urls.getOrNull(0).orEmpty())
        setEthernetBackendUrl(urls.getOrNull(1).orEmpty())
        prefs.edit().putString(KEY_BACKEND_URL, normalizeBackendUrls(value)).apply()
    }

    fun getDeviceId(): String {
        val stored = prefs.getString(KEY_DEVICE_ID, null)
        if (!stored.isNullOrBlank()) {
            return stored
        }

        val generated = Settings.Secure.getString(
            appContext.contentResolver,
            Settings.Secure.ANDROID_ID
        ) ?: "android-device"
        setDeviceId(generated)
        return generated
    }

    fun setDeviceId(value: String) {
        prefs.edit().putString(KEY_DEVICE_ID, value.trim()).apply()
    }

    fun getAuthToken(): String {
        return prefs.getString(KEY_AUTH_TOKEN, DEFAULT_AUTH_TOKEN).orEmpty()
    }

    fun setAuthToken(value: String) {
        prefs.edit().putString(KEY_AUTH_TOKEN, value.trim()).apply()
    }

    fun getPrivacyPin(): String {
        return prefs.getString(KEY_PRIVACY_PIN, "").orEmpty()
    }

    fun setPrivacyPin(value: String) {
        setInitialPrivacyPin(value)
    }

    fun isPrivacyPinSet(): Boolean {
        if (prefs.getBoolean(KEY_PRIVACY_PIN_SET, false)) {
            return true
        }

        val stored = prefs.getString(KEY_PRIVACY_PIN, null)
        return !stored.isNullOrBlank() && stored != DEFAULT_PRIVACY_PIN
    }

    fun setInitialPrivacyPin(value: String): Boolean {
        val pin = value.filter { it.isDigit() }.take(4)
        if (pin.length != 4 || isPrivacyPinSet()) {
            return false
        }

        prefs.edit()
            .putString(KEY_PRIVACY_PIN, pin)
            .putBoolean(KEY_PRIVACY_PIN_SET, true)
            .apply()
        return true
    }

    fun isHiyaEnabled(): Boolean {
        return prefs.getBoolean(KEY_HIYA_ENABLED, false)
    }

    fun setHiyaEnabled(enabled: Boolean) {
        prefs.edit().putBoolean(KEY_HIYA_ENABLED, enabled).apply()
    }

    fun getHiyaAppId(): String {
        return prefs.getString(KEY_HIYA_APP_ID, "").orEmpty()
    }

    fun setHiyaAppId(value: String) {
        prefs.edit().putString(KEY_HIYA_APP_ID, value.trim()).apply()
    }

    fun getHiyaApiKey(): String {
        return prefs.getString(KEY_HIYA_API_KEY, "").orEmpty()
    }

    fun setHiyaApiKey(value: String) {
        prefs.edit().putString(KEY_HIYA_API_KEY, value.trim()).apply()
    }

    fun isVoiceEnabled(): Boolean {
        return prefs.getBoolean(KEY_VOICE_ENABLED, true)
    }

    fun setVoiceEnabled(enabled: Boolean) {
        prefs.edit().putBoolean(KEY_VOICE_ENABLED, enabled).apply()
    }

    fun isBackgroundVoiceEnabled(): Boolean {
        return prefs.getBoolean(KEY_BACKGROUND_VOICE_ENABLED, false)
    }

    fun setBackgroundVoiceEnabled(enabled: Boolean) {
        prefs.edit().putBoolean(KEY_BACKGROUND_VOICE_ENABLED, enabled).apply()
    }

    fun isTrustedVoiceEnabled(): Boolean {
        return prefs.getBoolean(KEY_TRUSTED_VOICE_ENABLED, false)
    }

    fun setTrustedVoiceEnabled(enabled: Boolean) {
        prefs.edit().putBoolean(KEY_TRUSTED_VOICE_ENABLED, enabled).apply()
    }

    fun getTrustedVoicePhrase(): String {
        return prefs.getString(KEY_TRUSTED_VOICE_PHRASE, DEFAULT_TRUSTED_VOICE_PHRASE).orEmpty()
    }

    fun setTrustedVoicePhrase(value: String) {
        prefs.edit().putString(KEY_TRUSTED_VOICE_PHRASE, value.trim()).apply()
    }

    fun getTrustedVoiceprint(): FloatArray? {
        return getTrustedVoiceprints().firstOrNull()
    }

    fun getTrustedVoiceprints(): List<FloatArray> {
        return OnnxSpeakerVerifier.parseFeatureSet(prefs.getString(KEY_TRUSTED_VOICEPRINT, "").orEmpty())
    }

    fun setTrustedVoiceprint(features: FloatArray) {
        setTrustedVoiceprints(listOf(features))
    }

    fun setTrustedVoiceprints(features: List<FloatArray>) {
        val serialized = OnnxSpeakerVerifier.serializeFeatureSet(features)
        val saved = prefs.edit().putString(KEY_TRUSTED_VOICEPRINT, serialized).commit()
        if (!saved) {
            prefs.edit().putString(KEY_TRUSTED_VOICEPRINT, serialized).apply()
        }
    }

    fun clearTrustedVoiceprint() {
        prefs.edit().remove(KEY_TRUSTED_VOICEPRINT).apply()
    }

    fun hasTrustedVoiceprint(): Boolean {
        return getTrustedVoiceprints().isNotEmpty()
    }

    fun getBackgroundVoiceSessionId(): String {
        return prefs.getString(KEY_BACKGROUND_VOICE_SESSION_ID, "").orEmpty()
    }

    fun setBackgroundVoiceSessionId(value: String) {
        prefs.edit().putString(KEY_BACKGROUND_VOICE_SESSION_ID, value.trim()).apply()
    }

    fun setRecentMessageNotification(packageName: String, sender: String, body: String, timestampMs: Long) {
        prefs.edit()
            .putString(KEY_RECENT_MESSAGE_PACKAGE, packageName.trim())
            .putString(KEY_RECENT_MESSAGE_SENDER, sender.trim())
            .putString(KEY_RECENT_MESSAGE_BODY, body.trim())
            .putLong(KEY_RECENT_MESSAGE_AT, timestampMs)
            .apply()
    }

    fun getRecentMessageSummary(maxAgeMs: Long = 15 * 60_000L): String? {
        val timestamp = prefs.getLong(KEY_RECENT_MESSAGE_AT, 0L)
        if (timestamp <= 0L || System.currentTimeMillis() - timestamp > maxAgeMs) {
            return null
        }

        val sender = prefs.getString(KEY_RECENT_MESSAGE_SENDER, "").orEmpty()
        val body = prefs.getString(KEY_RECENT_MESSAGE_BODY, "").orEmpty()
        if (sender.isBlank() && body.isBlank()) {
            return null
        }

        val cleanedSender = sender.ifBlank { "Someone" }
        return if (body.isBlank()) {
            "$cleanedSender sent you a message."
        } else {
            "$cleanedSender says: $body"
        }
    }

    companion object {
        fun normalizeBackendUrl(value: String): String {
            val trimmed = value.trim().trimEnd('/')
            if (trimmed.isBlank()) {
                return ""
            }
            return if (trimmed.startsWith("http://", ignoreCase = true) || trimmed.startsWith("https://", ignoreCase = true)) {
                trimmed
            } else {
                "http://$trimmed"
            }
        }

        fun splitBackendUrls(value: String): List<String> {
            return value
                .split('\n', ',', ';')
                .map { normalizeBackendUrl(it) }
                .filter { it.isNotBlank() }
                .distinct()
        }

        fun normalizeBackendUrls(value: String): String {
            return splitBackendUrls(value).joinToString("\n")
        }

        private const val KEY_BACKEND_URL = "backend_url"
        private const val KEY_BACKEND_URL_WIFI = "backend_url_wifi"
        private const val KEY_BACKEND_URL_ETHERNET = "backend_url_ethernet"
        private const val KEY_DEVICE_ID = "device_id"
        private const val KEY_AUTH_TOKEN = "auth_token"
        private const val KEY_PRIVACY_PIN = "privacy_pin"
        private const val KEY_PRIVACY_PIN_SET = "privacy_pin_set"
        private const val KEY_HIYA_ENABLED = "hiya_enabled"
        private const val KEY_HIYA_APP_ID = "hiya_app_id"
        private const val KEY_HIYA_API_KEY = "hiya_api_key"
        private const val KEY_VOICE_ENABLED = "voice_enabled"
        private const val KEY_BACKGROUND_VOICE_ENABLED = "background_voice_enabled"
        private const val KEY_TRUSTED_VOICE_ENABLED = "trusted_voice_enabled"
        private const val KEY_TRUSTED_VOICE_PHRASE = "trusted_voice_phrase"
        private const val KEY_TRUSTED_VOICEPRINT = "trusted_voiceprint"
        private const val KEY_BACKGROUND_VOICE_SESSION_ID = "background_voice_session_id"
        private const val KEY_RECENT_MESSAGE_PACKAGE = "recent_message_package"
        private const val KEY_RECENT_MESSAGE_SENDER = "recent_message_sender"
        private const val KEY_RECENT_MESSAGE_BODY = "recent_message_body"
        private const val KEY_RECENT_MESSAGE_AT = "recent_message_at"
        private const val DEFAULT_BACKEND_URL = "http://192.168.1.2:8000"
        private const val DEFAULT_AUTH_TOKEN = ""
        private const val DEFAULT_PRIVACY_PIN = "0000"
        private const val DEFAULT_TRUSTED_VOICE_PHRASE = "arc reactor"
    }
}
