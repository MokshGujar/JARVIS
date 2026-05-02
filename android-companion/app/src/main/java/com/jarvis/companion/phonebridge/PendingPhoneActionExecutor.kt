package com.jarvis.companion

import android.content.Context

class PendingPhoneActionExecutor(
    context: Context,
    private val logger: AppEventLogger,
) {
    private val callControlService = CallControlService(context)
    private val contactCallService = ContactCallService(context, logger)

    fun execute(action: PendingPhoneAction): Result<String> {
        return when (action.actionType.lowercase()) {
            "answer_call" -> callControlService.answerIncomingCall()
                .map { "Answered the active call." }
            "reject_call" -> callControlService.rejectIncomingCall()
                .map { "Rejected the active call." }
            "place_call" -> contactCallService.placeContactCall(action)
            "draft_message" -> contactCallService.draftMessage(action)
            else -> Result.failure(IllegalStateException("Unsupported phone action: ${action.actionType}"))
        }
    }
}
