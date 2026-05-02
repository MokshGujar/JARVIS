package com.jarvis.companion

import android.content.Context
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

class AppEventLogger(context: Context) {
    private val prefs = context.getSharedPreferences("jarvis_companion", Context.MODE_PRIVATE)

    fun log(message: String) {
        val timestamp = SimpleDateFormat("HH:mm:ss", Locale.getDefault()).format(Date())
        val existing = prefs.getString(KEY_EVENT_LOG, "").orEmpty()
        val updated = buildString {
            appendLine("[$timestamp] $message")
            if (existing.isNotBlank()) {
                append(existing)
            }
        }
        prefs.edit().putString(KEY_EVENT_LOG, updated.take(MAX_LOG_CHARS)).apply()
    }

    fun read(): String {
        return prefs.getString(KEY_EVENT_LOG, "").orEmpty()
    }

    fun clear() {
        prefs.edit().remove(KEY_EVENT_LOG).apply()
    }

    companion object {
        private const val KEY_EVENT_LOG = "event_log"
        private const val MAX_LOG_CHARS = 8000
    }
}
