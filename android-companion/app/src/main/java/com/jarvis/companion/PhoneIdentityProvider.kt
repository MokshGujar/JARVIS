package com.jarvis.companion

interface PhoneIdentityProvider {
    fun lookup(phoneNumber: String): CallerIdentity?
}
