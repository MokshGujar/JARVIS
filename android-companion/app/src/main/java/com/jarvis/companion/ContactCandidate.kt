package com.jarvis.companion

data class ContactCandidate(
    val contactId: String,
    val displayName: String,
    val phoneNumber: String,
    val normalizedName: String,
    val aliases: List<String> = emptyList(),
    val favorite: Boolean = false,
    val lastContacted: Long = 0L,
    val timesContacted: Int = 0,
    val score: Float = 0f,
    val reasons: List<String> = emptyList(),
)
