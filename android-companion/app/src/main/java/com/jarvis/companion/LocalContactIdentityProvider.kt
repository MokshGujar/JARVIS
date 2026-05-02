package com.jarvis.companion

import android.content.Context

class LocalContactIdentityProvider(context: Context) : PhoneIdentityProvider {
    private val contactLookupService = ContactLookupService(context)

    override fun lookup(phoneNumber: String): CallerIdentity? {
        return contactLookupService.lookup(phoneNumber)?.copy(
            source = "contacts",
            confidence = 1.0f,
        )
    }
}
