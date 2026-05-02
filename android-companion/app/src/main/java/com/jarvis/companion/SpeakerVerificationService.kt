package com.jarvis.companion

import android.content.Context

enum class SpeakerVerificationStatus {
    VERIFIED,
    UNCERTAIN,
    NOT_VERIFIED,
    UNAVAILABLE,
}

data class SpeakerVerificationResult(
    val status: SpeakerVerificationStatus,
    val score: Float,
    val reason: String,
)

class SpeakerVerificationService(
    private val context: Context,
    private val prefs: JarvisPreferences,
    private val logger: AppEventLogger,
) {
    fun verifyLive(): SpeakerVerificationResult {
        if (!OnnxSpeakerVerifier.isModelAvailable(context)) {
            return SpeakerVerificationResult(
                status = SpeakerVerificationStatus.UNAVAILABLE,
                score = 0f,
                reason = "speaker_verify.onnx is missing.",
            )
        }

        val enrolled = prefs.getTrustedVoiceprints()
        if (enrolled.isEmpty()) {
            return SpeakerVerificationResult(
                status = SpeakerVerificationStatus.UNAVAILABLE,
                score = 0f,
                reason = "No ONNX trusted voiceprint is enrolled.",
            )
        }

        return OnnxSpeakerVerifier.recordAndExtractFeatureSet(context).fold(
            onSuccess = { current ->
                val score = OnnxSpeakerVerifier.maxSimilarity(enrolled, current)
                val status = when {
                    score >= VERIFIED_THRESHOLD -> SpeakerVerificationStatus.VERIFIED
                    score >= UNCERTAIN_THRESHOLD -> SpeakerVerificationStatus.UNCERTAIN
                    else -> SpeakerVerificationStatus.NOT_VERIFIED
                }
                logger.log("Speaker verification result: $status score=$score")
                SpeakerVerificationResult(status, score, "Voiceprint score ${"%.2f".format(score)}")
            },
            onFailure = { error ->
                logger.log("Speaker verification unavailable: ${error.message}")
                SpeakerVerificationResult(
                    status = SpeakerVerificationStatus.UNAVAILABLE,
                    score = 0f,
                    reason = error.message ?: "Voice verification failed.",
                )
            },
        )
    }

    companion object {
        const val VERIFIED_THRESHOLD = 0.75f
        const val UNCERTAIN_THRESHOLD = 0.62f
    }
}
