from app.services.error_recovery_service import ErrorRecoveryService


def test_contact_not_found_recovery_is_actionable_and_redacted():
    recovery = ErrorRecoveryService().recover("contact_not_found", target="+919999999999")

    payload = recovery.as_dict()
    assert "contacts" in payload["message"]
    assert "Sync phone contacts" in payload["message"]
    assert "+919999999999" not in payload["message"]


def test_gmail_not_configured_recovery():
    recovery = ErrorRecoveryService().recover("gmail_not_configured")

    assert "Gmail is not configured" in recovery.message
    assert "Connect Gmail OAuth" in recovery.message


def test_whatsapp_selector_missing_recovery():
    recovery = ErrorRecoveryService().recover("whatsapp_selector_missing")

    assert "could not find the message box" in recovery.message
    assert "Open the chat once" in recovery.message


def test_file_query_missing_recovery():
    recovery = ErrorRecoveryService().recover("file_query_missing")

    assert "filename or keyword" in recovery.message


def test_protected_destructive_action_recovery():
    recovery = ErrorRecoveryService().recover("protected_destructive_action")

    assert recovery.retry_possible is False
    assert "protected" in recovery.message


def test_unsupported_document_type_recovery():
    recovery = ErrorRecoveryService().recover("unsupported_document_type")

    assert "cannot read that document type" in recovery.message
