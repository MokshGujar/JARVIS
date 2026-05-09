from app.services.real_world_command_suite import get_real_world_command_suite


def test_real_world_suite_contains_all_requested_commands():
    suite = get_real_world_command_suite()

    assert len(suite) == 56
    assert [case.id for case in suite] == list(range(1, 57))


def test_every_real_world_command_has_required_classification_fields():
    for case in get_real_world_command_suite():
        assert case.command
        assert case.expected_route
        assert case.expected_tool
        assert case.policy_decision in {"ALLOW", "CLARIFY", "CONFIRM", "STEP_UP", "DENY"}
        assert case.support_status in {
            "supported now",
            "supported after this phase",
            "blocked for safety",
            "metadata/planned",
            "not implemented",
            "external setup required",
        }
        assert case.test_status


def test_communication_suite_never_marks_setup_required_email_as_direct_send():
    email_cases = [case for case in get_real_world_command_suite() if "email" in case.command.lower() or "gmail" in case.command.lower()]

    assert email_cases
    assert all(not case.direct_execution_allowed for case in email_cases)
    assert all(case.support_status == "external setup required" for case in email_cases)


def test_dangerous_commands_are_not_direct_execution_allowed():
    dangerous = {21: "Delete it", 30: "Shutdown computer", 56: "Refuse unsafe command"}
    by_id = {case.id: case for case in get_real_world_command_suite()}

    for case_id in dangerous:
        assert by_id[case_id].direct_execution_allowed is False
        assert by_id[case_id].policy_decision in {"STEP_UP", "DENY"}
