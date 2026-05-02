package com.jarvis.companion

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import android.telecom.TelecomManager
import androidx.core.content.ContextCompat

class CallControlService(private val context: Context) {
    fun answerIncomingCall(): Result<Unit> {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
            return Result.failure(IllegalStateException("Answering calls requires Android 8 or newer."))
        }

        val granted = ContextCompat.checkSelfPermission(
            context,
            Manifest.permission.ANSWER_PHONE_CALLS
        ) == PackageManager.PERMISSION_GRANTED

        if (!granted) {
            return Result.failure(IllegalStateException("ANSWER_PHONE_CALLS permission is not granted."))
        }

        val telecomManager = context.getSystemService(TelecomManager::class.java)
            ?: return Result.failure(IllegalStateException("TelecomManager is unavailable."))

        return runCatching {
            telecomManager.acceptRingingCall()
        }
    }

    fun rejectIncomingCall(): Result<Unit> {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.P) {
            return Result.failure(IllegalStateException("Rejecting calls requires Android 9 or newer in this implementation."))
        }

        val granted = ContextCompat.checkSelfPermission(
            context,
            Manifest.permission.ANSWER_PHONE_CALLS
        ) == PackageManager.PERMISSION_GRANTED

        if (!granted) {
            return Result.failure(IllegalStateException("ANSWER_PHONE_CALLS permission is not granted."))
        }

        val telecomManager = context.getSystemService(TelecomManager::class.java)
            ?: return Result.failure(IllegalStateException("TelecomManager is unavailable."))

        return runCatching {
            val ended = telecomManager.endCall()
            if (!ended) {
                error("No ringing call was available to reject.")
            }
        }
    }
}
