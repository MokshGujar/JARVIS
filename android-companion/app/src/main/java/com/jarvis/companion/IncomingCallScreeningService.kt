package com.jarvis.companion

import android.telecom.Call
import android.telecom.CallScreeningService
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

class IncomingCallScreeningService : CallScreeningService() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    override fun onScreenCall(callDetails: Call.Details) {
        val logger = AppEventLogger(applicationContext)
        logger.log("CallScreeningService invoked")

        respondToCall(
            callDetails,
            CallResponse.Builder()
                .setDisallowCall(false)
                .setRejectCall(false)
                .setSkipCallLog(false)
                .setSkipNotification(false)
                .build()
        )

        val handle = callDetails.handle ?: return
        val phoneNumber = handle.schemeSpecificPart ?: return
        logger.log("Incoming number detected: $phoneNumber")

        scope.launch {
            IncomingCallCoordinator(applicationContext).processIncomingCall(
                phoneNumber = phoneNumber,
                source = "call_screening",
                callDirection = "incoming",
            )
        }
    }
}
