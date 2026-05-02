package com.jarvis.companion

import android.content.Context

class CallerIdentityResolver(
    context: Context,
    private val logger: AppEventLogger,
) {
    private val contactProvider = LocalContactIdentityProvider(context)
    private val metadataProvider = LocalNumberMetadataProvider()

    fun resolve(phoneNumber: String): CallerIdentity? {
        val contact = contactProvider.lookup(phoneNumber)
        if (contact != null) {
            logger.log("Resolved caller from saved contacts: ${contact.displayName}")
            return contact
        }

        logger.log("No saved contact found, using local metadata and Jarvis backend lookup")
        return null
    }

    fun localMetadata(phoneNumber: String): CallerIdentity? {
        return metadataProvider.lookup(phoneNumber)
    }
}
