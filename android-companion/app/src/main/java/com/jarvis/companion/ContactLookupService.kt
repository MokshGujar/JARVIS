package com.jarvis.companion

import android.content.Context
import android.provider.ContactsContract

class ContactLookupService(private val context: Context) {
    private val matcher = ContactMatcher()

    fun lookup(phoneNumber: String): CallerIdentity? {
        val uri = android.net.Uri.withAppendedPath(
            ContactsContract.PhoneLookup.CONTENT_FILTER_URI,
            android.net.Uri.encode(phoneNumber)
        )

        context.contentResolver.query(
            uri,
            arrayOf(
                ContactsContract.PhoneLookup.DISPLAY_NAME,
                ContactsContract.PhoneLookup.NUMBER
            ),
            null,
            null,
            null
        )?.use { cursor ->
            if (cursor.moveToFirst()) {
                val name = cursor.getString(0).orEmpty()
                val number = cursor.getString(1).orEmpty()
                if (name.isNotBlank() || number.isNotBlank()) {
                    return CallerIdentity(
                        displayName = name.ifBlank { number },
                        phoneNumber = number.ifBlank { phoneNumber },
                        source = "contacts"
                    )
                }
            }
        }

        return null
    }

    fun lookupByDisplayName(displayName: String): CallerIdentity? {
        val cleaned = displayName.trim()
        if (cleaned.isBlank()) {
            return null
        }

        context.contentResolver.query(
            ContactsContract.CommonDataKinds.Phone.CONTENT_URI,
            arrayOf(
                ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME,
                ContactsContract.CommonDataKinds.Phone.NUMBER
            ),
            "${ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME} = ?",
            arrayOf(cleaned),
            null
        )?.use { cursor ->
            if (cursor.moveToFirst()) {
                val name = cursor.getString(0).orEmpty()
                val number = cursor.getString(1).orEmpty()
                if (name.isNotBlank() || number.isNotBlank()) {
                    return CallerIdentity(
                        displayName = name.ifBlank { cleaned },
                        phoneNumber = number,
                        source = "contacts"
                    )
                }
            }
        }

        return null
    }

    fun lookupByContactId(contactId: String): CallerIdentity? {
        val cleaned = contactId.trim()
        if (cleaned.isBlank()) {
            return null
        }

        context.contentResolver.query(
            ContactsContract.CommonDataKinds.Phone.CONTENT_URI,
            arrayOf(
                ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME,
                ContactsContract.CommonDataKinds.Phone.NUMBER
            ),
            "${ContactsContract.CommonDataKinds.Phone.CONTACT_ID} = ?",
            arrayOf(cleaned),
            null
        )?.use { cursor ->
            if (cursor.moveToFirst()) {
                val name = cursor.getString(0).orEmpty()
                val number = cursor.getString(1).orEmpty()
                if (name.isNotBlank() || number.isNotBlank()) {
                    return CallerIdentity(
                        displayName = name.ifBlank { number },
                        phoneNumber = number,
                        source = "contacts",
                        normalizedNumber = number,
                        confidence = 1f,
                    )
                }
            }
        }

        return null
    }

    fun identityFromResolvedAction(
        contactName: String,
        phoneNumber: String?,
        contactId: String?,
        confidence: Float?,
    ): CallerIdentity? {
        contactId?.takeIf { it.isNotBlank() }?.let { id ->
            lookupByContactId(id)?.let { return it }
        }

        val number = phoneNumber.orEmpty().trim()
        if (number.isNotBlank()) {
            val contact = lookup(number)
            return contact ?: CallerIdentity(
                displayName = contactName.ifBlank { number },
                phoneNumber = number,
                source = "pending_action",
                normalizedNumber = number,
                confidence = confidence ?: 1f,
            )
        }

        return null
    }

    fun lookupBestByDisplayName(displayName: String): CallerIdentity? {
        val cleaned = displayName.trim()
        if (cleaned.isBlank()) {
            return null
        }

        val ranked = rankByDisplayName(cleaned)
        if (ranked.isEmpty()) {
            return null
        }

        val top = ranked.first()
        if (!matcher.isAutoCallable(cleaned, ranked) && top.score < ContactMatcher.MEDIUM_CONFIDENCE) {
            return null
        }

        return CallerIdentity(
            displayName = top.displayName,
            phoneNumber = top.phoneNumber,
            source = "contacts",
            normalizedNumber = top.phoneNumber,
            confidence = top.score,
        )
    }

    fun rankByDisplayName(displayName: String): List<ContactCandidate> {
        val cleaned = displayName.trim()
        if (cleaned.isBlank()) {
            return emptyList()
        }
        return matcher.rank(cleaned, loadContactCandidates())
    }

    fun listContactCandidates(): List<ContactCandidate> {
        return loadContactCandidates()
    }

    private fun loadContactCandidates(): List<ContactCandidate> {
        val contacts = mutableListOf<ContactCandidate>()
        context.contentResolver.query(
            ContactsContract.CommonDataKinds.Phone.CONTENT_URI,
            arrayOf(
                ContactsContract.CommonDataKinds.Phone.CONTACT_ID,
                ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME,
                ContactsContract.CommonDataKinds.Phone.NUMBER,
                ContactsContract.CommonDataKinds.Phone.STARRED,
                ContactsContract.CommonDataKinds.Phone.LAST_TIME_CONTACTED,
                ContactsContract.CommonDataKinds.Phone.TIMES_CONTACTED,
            ),
            null,
            null,
            "${ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME} ASC"
        )?.use { cursor ->
            while (cursor.moveToNext()) {
                val contactId = cursor.getLong(0).toString()
                val name = cursor.getString(1).orEmpty()
                val number = cursor.getString(2).orEmpty()
                val favorite = cursor.getInt(3) == 1
                val lastContacted = cursor.getLong(4)
                val timesContacted = cursor.getInt(5)
                if (name.isBlank() && number.isBlank()) {
                    continue
                }
                contacts += ContactCandidate(
                    contactId = contactId,
                    displayName = name.ifBlank { number },
                    phoneNumber = number,
                    normalizedName = normalizeName(name),
                    aliases = buildLocalAliases(name),
                    favorite = favorite,
                    lastContacted = lastContacted,
                    timesContacted = timesContacted,
                )
            }
        }
        return contacts
    }

    private fun buildLocalAliases(name: String): List<String> {
        val normalized = normalizeName(name)
        val words = normalized.split(" ").filter { it.isNotBlank() }
        val aliases = mutableListOf<String>()
        if (words.size > 1) {
            aliases += words.first()
            aliases += words.last()
        }
        return aliases.distinct()
    }

    private fun normalizeName(value: String): String {
        return value
            .lowercase()
            .replace(Regex("[^\\p{L}\\p{N}]"), " ")
            .replace(Regex("\\s+"), " ")
            .trim()
    }
}
