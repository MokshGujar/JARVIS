package com.jarvis.companion

import android.Manifest
import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import androidx.core.content.ContextCompat
import java.util.Locale

class ContactCallService(
    private val context: Context,
    private val logger: AppEventLogger,
) {
    private val contactLookupService = ContactLookupService(context)

    fun placeContactCall(action: PendingPhoneAction): Result<String> {
        val contact = runCatching { resolveContactForAction(action) }.getOrElse { error ->
            return Result.failure(error)
        } ?: return Result.failure(IllegalStateException("I could not find ${action.contactName.orEmpty()} in your contacts."))

        return placeResolvedContactCall(contact, action.callMethod.orEmpty())
    }

    fun placeContactCall(contactName: String, callMethod: String): Result<String> {
        val contact = runCatching { resolveContactByName(contactName) }.getOrElse { error ->
            return Result.failure(error)
        } ?: return Result.failure(IllegalStateException("I could not find $contactName in your contacts."))

        return placeResolvedContactCall(contact, callMethod)
    }

    fun draftMessage(action: PendingPhoneAction): Result<String> {
        val body = action.messageBody.orEmpty().trim()
        if (body.isBlank()) {
            return Result.failure(IllegalStateException("The message draft is empty."))
        }

        val contact = runCatching { resolveContactForAction(action) }.getOrElse { error ->
            return Result.failure(error)
        } ?: return Result.failure(IllegalStateException("I could not find ${action.contactName.orEmpty()} in your contacts."))

        return if (action.channel.equals("whatsapp", ignoreCase = true)) {
            openWhatsAppContact(contact, body)
        } else {
            openSmsDraft(contact, body)
        }
    }

    private fun resolveContactForAction(action: PendingPhoneAction): CallerIdentity? {
        contactLookupService.identityFromResolvedAction(
            contactName = action.contactName.orEmpty(),
            phoneNumber = action.phoneNumber,
            contactId = action.contactId,
            confidence = action.matchConfidence,
        )?.let { return it }

        return resolveContactByName(action.contactName.orEmpty())
    }

    private fun resolveContactByName(contactName: String): CallerIdentity? {
        val candidates = contactLookupService.rankByDisplayName(contactName)
        if (candidates.isEmpty()) {
            return null
        }

        if (candidates.size > 1) {
            val top = candidates[0]
            val second = candidates[1]
            if (!ContactMatcher().isAutoCallable(contactName, candidates) || top.score - second.score < ContactMatcher.MIN_AUTO_CALL_GAP) {
                val names = candidates.take(3).joinToString(", ") { it.displayName }
                throw IllegalStateException("I found similar contacts: $names. Please say the full name.")
            }
        }

        return contactLookupService.lookupBestByDisplayName(contactName)
    }

    private fun placeResolvedContactCall(contact: CallerIdentity, callMethod: String): Result<String> {
        return if (callMethod.equals("whatsapp", ignoreCase = true)) {
            openWhatsAppContact(contact).recoverCatching {
                logger.log("WhatsApp flow failed for ${contact.displayName}: ${it.message}. Falling back to dialer.")
                openDialer(contact)
            }.getOrThrow().let { Result.success(it) }
        } else {
            startPhoneCall(contact)
        }
    }

    private fun startPhoneCall(contact: CallerIdentity): Result<String> {
        val phoneNumber = sanitizePhoneNumber(contact.phoneNumber)
        if (phoneNumber.isBlank()) {
            return Result.failure(IllegalStateException("I found ${contact.displayName}, but the contact has no phone number."))
        }

        val hasCallPermission =
            ContextCompat.checkSelfPermission(context, Manifest.permission.CALL_PHONE) ==
                PackageManager.PERMISSION_GRANTED

        if (!hasCallPermission) {
            return runCatching { openDialer(contact) }
        }

        val intent = Intent(Intent.ACTION_CALL, Uri.parse("tel:$phoneNumber")).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        context.startActivity(intent)
        logger.log("Started normal call to ${contact.displayName}")
        return Result.success("Calling ${contact.displayName}.")
    }

    private fun openDialer(contact: CallerIdentity): String {
        val phoneNumber = sanitizePhoneNumber(contact.phoneNumber)
        if (phoneNumber.isBlank()) {
            throw IllegalStateException("I found ${contact.displayName}, but the contact has no phone number.")
        }
        val dialIntent = Intent(Intent.ACTION_DIAL, Uri.parse("tel:$phoneNumber")).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        context.startActivity(dialIntent)
        logger.log("Opened dialer fallback for ${contact.displayName}")
        return "Opened the dialer for ${contact.displayName}."
    }

    private fun openSmsDraft(contact: CallerIdentity, messageBody: String): Result<String> {
        val phoneNumber = sanitizePhoneNumber(contact.phoneNumber)
        if (phoneNumber.isBlank()) {
            return Result.failure(IllegalStateException("I found ${contact.displayName}, but the contact has no phone number."))
        }

        val intent = Intent(Intent.ACTION_SENDTO, Uri.parse("smsto:$phoneNumber")).apply {
            putExtra("sms_body", messageBody)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        context.startActivity(intent)
        logger.log("Opened SMS draft for ${contact.displayName}")
        return Result.success("Drafting an SMS to ${contact.displayName}.")
    }

    private fun openWhatsAppContact(contact: CallerIdentity, messageBody: String = ""): Result<String> {
        val candidates = buildWhatsAppCandidates(contact.phoneNumber)
        if (candidates.isEmpty()) {
            return Result.failure(IllegalStateException("I found ${contact.displayName}, but the contact has no phone number."))
        }

        val packages = listOf("com.whatsapp", "com.whatsapp.w4b")
        for (pkg in packages) {
            for (candidate in candidates) {
                val deepLinks = listOf(
                    buildWhatsAppDeepLink(candidate, messageBody),
                    buildWhatsAppApiLink(candidate, messageBody)
                )
                for (deepLink in deepLinks) {
                    val intent = Intent(Intent.ACTION_VIEW, Uri.parse(deepLink)).apply {
                        addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                        setPackage(pkg)
                    }
                    try {
                        context.startActivity(intent)
                        logger.log("Opened WhatsApp flow for ${contact.displayName} using $candidate via $pkg")
                        return Result.success(
                            if (messageBody.isBlank()) {
                                "Opening WhatsApp for ${contact.displayName}."
                            } else {
                                "Drafting a WhatsApp message to ${contact.displayName}."
                            }
                        )
                    } catch (_: ActivityNotFoundException) {
                    }
                }
            }
        }

        return Result.failure(IllegalStateException("WhatsApp is not installed or could not open this contact on the phone."))
    }

    private fun buildWhatsAppDeepLink(phoneNumber: String, messageBody: String): String {
        val encoded = Uri.encode(messageBody)
        return if (messageBody.isBlank()) {
            "https://wa.me/$phoneNumber"
        } else {
            "https://wa.me/$phoneNumber?text=$encoded"
        }
    }

    private fun buildWhatsAppApiLink(phoneNumber: String, messageBody: String): String {
        val encoded = Uri.encode(messageBody)
        return if (messageBody.isBlank()) {
            "https://api.whatsapp.com/send?phone=$phoneNumber"
        } else {
            "https://api.whatsapp.com/send?phone=$phoneNumber&text=$encoded"
        }
    }

    private fun sanitizePhoneNumber(raw: String): String {
        return raw.filter { it.isDigit() || it == '+' }
    }

    private fun buildWhatsAppCandidates(raw: String): List<String> {
        val sanitized = sanitizePhoneNumber(raw)
        if (sanitized.isBlank()) {
            return emptyList()
        }

        val digitsOnly = sanitized.filter { it.isDigit() }
        val candidates = linkedSetOf<String>()
        if (digitsOnly.isNotBlank()) {
            candidates += digitsOnly
        }

        if (!sanitized.startsWith("+") && digitsOnly.length == 10 && Locale.getDefault().country.equals("IN", ignoreCase = true)) {
            candidates += "91$digitsOnly"
        }

        return candidates.toList()
    }
}
