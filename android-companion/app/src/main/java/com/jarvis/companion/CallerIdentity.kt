package com.jarvis.companion

data class CallerIdentity(
    val displayName: String,
    val phoneNumber: String,
    val source: String,
    val normalizedNumber: String = phoneNumber,
    val carrier: String = "",
    val lineType: String = "",
    val country: String = "",
    val location: String = "",
    val spamRisk: String = "",
    val confidence: Float = 0f,
)
