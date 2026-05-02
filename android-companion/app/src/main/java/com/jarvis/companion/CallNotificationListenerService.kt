package com.jarvis.companion

import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

class CallNotificationListenerService : NotificationListenerService() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var lastProcessedKey: String? = null
    private lateinit var contactLookupService: ContactLookupService

    override fun onCreate() {
        super.onCreate()
        contactLookupService = ContactLookupService(applicationContext)
    }

    override fun onListenerConnected() {
        super.onListenerConnected()
        AppEventLogger(applicationContext).log("Notification listener connected")
    }

    override fun onNotificationPosted(sbn: StatusBarNotification) {
        val logger = AppEventLogger(applicationContext)
        val packageName = sbn.packageName.orEmpty()
        val extras = sbn.notification.extras
        val title = extras?.getCharSequence("android.title")?.toString().orEmpty()
        val text = extras?.getCharSequence("android.text")?.toString().orEmpty()
        val bigText = extras?.getCharSequence("android.bigText")?.toString().orEmpty()

        val callDirection = detectCallDirection(sbn)
        if (callDirection == null) {
            maybeStoreMessageNotification(packageName, title, text, bigText, logger)
            return
        }

        if (!looksLikeDialerNotification(sbn, callDirection)) {
            maybeStoreMessageNotification(packageName, title, text, bigText, logger)
            return
        }

        val combined = listOf(title, text, bigText).filter { it.isNotBlank() }.joinToString(" | ")

        logger.log("Dialer notification seen from $packageName: $combined")

        var phoneNumber = extractPhoneNumber(combined)
        var nameHint = extractLikelyName(title, phoneNumber)

        if (phoneNumber.isBlank() && !nameHint.isNullOrBlank()) {
            val contact = contactLookupService.lookupByDisplayName(nameHint)
            if (contact != null && contact.phoneNumber.isNotBlank()) {
                phoneNumber = contact.phoneNumber
                nameHint = contact.displayName
                logger.log("Resolved saved contact from notification title: ${contact.displayName}")
            }
        }

        val dedupeNumber = canonicalPhoneKey(phoneNumber)
        val dedupeKey = "${sbn.key}|$callDirection|$dedupeNumber|$nameHint"

        if (phoneNumber.isBlank() || dedupeKey == lastProcessedKey) {
            if (phoneNumber.isBlank()) {
                logger.log("Notification listener skipped: no phone number resolved")
            }
            return
        }

        lastProcessedKey = dedupeKey
        logger.log("Notification listener captured $callDirection call event from $packageName")

        scope.launch {
            IncomingCallCoordinator(applicationContext).processIncomingCall(
                phoneNumber = phoneNumber,
                callerNameHint = nameHint,
                source = "notification_listener",
                callDirection = callDirection,
            )
        }
    }

    private fun maybeStoreMessageNotification(
        packageName: String,
        title: String,
        text: String,
        bigText: String,
        logger: AppEventLogger,
    ) {
        val loweredPackage = packageName.lowercase()
        val knownMessagingPackage = listOf(
            "com.whatsapp",
            "com.google.android.apps.messaging",
            "com.android.mms",
            "org.telegram.messenger",
            "com.facebook.orca",
            "com.instagram.android",
        ).any { loweredPackage.contains(it) }
        if (!knownMessagingPackage || title.isBlank()) {
            return
        }

        val body = bigText.ifBlank { text }.trim()
        if (body.isBlank()) {
            return
        }

        JarvisPreferences(applicationContext).setRecentMessageNotification(
            packageName = packageName,
            sender = title,
            body = body,
            timestampMs = System.currentTimeMillis(),
        )
        logger.log("Stored recent message notification from $packageName: $title")
    }

    private fun looksLikeDialerNotification(sbn: StatusBarNotification, callDirection: String): Boolean {
        val packageName = sbn.packageName.orEmpty().lowercase()
        val extras = sbn.notification.extras
        val title = extras?.getCharSequence("android.title")?.toString().orEmpty().lowercase()
        val text = extras?.getCharSequence("android.text")?.toString().orEmpty().lowercase()
        val category = sbn.notification.category.orEmpty().lowercase()

        val knownDialerPackage = listOf(
            "com.google.android.dialer",
            "com.android.dialer",
            "com.android.server.telecom",
            "com.vivo.dialer",
            "com.android.incallui",
        ).any { packageName.contains(it) }

        val directionHints = if (callDirection == "outgoing") {
            listOf("calling", "dialing", "outgoing call", "on the call")
        } else {
            listOf("incoming call", "ringing", "answer", "decline")
        }
        val callLikeText = directionHints.any { title.contains(it) || text.contains(it) || category.contains(it) }

        return knownDialerPackage || category == "call" || callLikeText
    }

    private fun detectCallDirection(sbn: StatusBarNotification): String? {
        val extras = sbn.notification.extras
        val combined = listOf(
            extras?.getCharSequence("android.title")?.toString().orEmpty(),
            extras?.getCharSequence("android.text")?.toString().orEmpty(),
            extras?.getCharSequence("android.bigText")?.toString().orEmpty(),
            sbn.notification.category.orEmpty(),
        ).joinToString(" | ").lowercase()

        val incomingHints = listOf("incoming call", "ringing", "answer", "decline")
        if (incomingHints.any { combined.contains(it) }) {
            return "incoming"
        }

        val outgoingHints = listOf("dialing", "outgoing call", "calling via", "calling from your")
        if (outgoingHints.any { combined.contains(it) }) {
            return "outgoing"
        }

        return if (sbn.notification.category.orEmpty().equals("call", ignoreCase = true)) {
            "incoming"
        } else {
            null
        }
    }

    private fun extractPhoneNumber(text: String): String {
        val match = Regex("""(\+?\d[\d\s().-]{5,}\d)""").find(text)
        return match?.value?.trim().orEmpty()
    }

    private fun extractLikelyName(title: String, phoneNumber: String): String? {
        if (title.isBlank()) {
            return null
        }

        val normalizedTitle = title.trim()
        if (phoneNumber.isNotBlank() && normalizedTitle.contains(phoneNumber)) {
            return null
        }

        return normalizedTitle
    }

    private fun canonicalPhoneKey(phoneNumber: String): String {
        val digits = phoneNumber.filter { it.isDigit() }
        if (digits.isBlank()) {
            return phoneNumber.trim()
        }
        return if (digits.length > 10) digits.takeLast(10) else digits
    }
}
