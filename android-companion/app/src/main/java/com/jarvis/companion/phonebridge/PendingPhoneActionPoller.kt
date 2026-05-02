package com.jarvis.companion

class PendingPhoneActionPoller(
    private val api: JarvisApiClient,
    private val logger: AppEventLogger,
) {
    fun fetchPendingActions(
        baseUrl: String,
        authToken: String,
        deviceId: String,
        phoneNumber: String,
    ): Result<List<PendingPhoneAction>> {
        return runCatching {
            api.fetchPendingPhoneActions(
                baseUrl = baseUrl,
                authToken = authToken,
                deviceId = deviceId,
                phoneNumber = phoneNumber,
            )
        }.onFailure { error ->
            logger.log("Pending phone action poll failed: ${error.message}")
        }
    }

    fun acknowledge(
        baseUrl: String,
        authToken: String,
        actionId: String,
        deviceId: String,
        phoneNumber: String,
        status: String,
    ): Result<Unit> {
        return runCatching {
            api.acknowledgePhoneAction(
                baseUrl = baseUrl,
                authToken = authToken,
                actionId = actionId,
                deviceId = deviceId,
                phoneNumber = phoneNumber,
                status = status,
            )
        }.onFailure { error ->
            logger.log("Pending phone action ack failed: ${error.message}")
        }
    }
}
