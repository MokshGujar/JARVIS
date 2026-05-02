package com.jarvis.companion

import com.google.i18n.phonenumbers.NumberParseException
import com.google.i18n.phonenumbers.PhoneNumberUtil
import java.util.Locale

class LocalNumberMetadataProvider : PhoneIdentityProvider {
    private val phoneUtil = PhoneNumberUtil.getInstance()

    override fun lookup(phoneNumber: String): CallerIdentity? {
        val raw = phoneNumber.trim()
        if (raw.isBlank()) {
            return null
        }

        val region = Locale.getDefault().country.ifBlank { "IN" }
        return try {
            val parsed = phoneUtil.parse(raw, region)
            if (!phoneUtil.isPossibleNumber(parsed)) {
                return null
            }

            val normalized = phoneUtil.format(parsed, PhoneNumberUtil.PhoneNumberFormat.E164)
            val country = phoneUtil.getRegionCodeForNumber(parsed).orEmpty()
            val lineType = when (phoneUtil.getNumberType(parsed)) {
                PhoneNumberUtil.PhoneNumberType.MOBILE -> "mobile"
                PhoneNumberUtil.PhoneNumberType.FIXED_LINE -> "fixed_line"
                PhoneNumberUtil.PhoneNumberType.FIXED_LINE_OR_MOBILE -> "fixed_or_mobile"
                PhoneNumberUtil.PhoneNumberType.TOLL_FREE -> "toll_free"
                PhoneNumberUtil.PhoneNumberType.PREMIUM_RATE -> "premium_rate"
                PhoneNumberUtil.PhoneNumberType.VOIP -> "voip"
                PhoneNumberUtil.PhoneNumberType.PERSONAL_NUMBER -> "personal_number"
                PhoneNumberUtil.PhoneNumberType.PAGER -> "pager"
                PhoneNumberUtil.PhoneNumberType.UAN -> "uan"
                PhoneNumberUtil.PhoneNumberType.VOICEMAIL -> "voicemail"
                else -> "unknown"
            }

            CallerIdentity(
                displayName = normalized,
                phoneNumber = normalized,
                normalizedNumber = normalized,
                source = "local_metadata",
                lineType = lineType,
                country = country,
                confidence = if (phoneUtil.isValidNumber(parsed)) 0.5f else 0.35f,
            )
        } catch (_: NumberParseException) {
            null
        }
    }
}
