import unittest

from app.orchestrator.automation_context import AutomationContext
from app.orchestrator.smart_automation_planner import SmartAutomationPlanner
from app.orchestrator.task_planner import TaskPlanner
from app.orchestrator.semantic_automation import AutomationMode, SemanticAutomationIntent
from app.services.automation_service import AutomationService


def intents(result):
    return [action.intent for action in result.semantic_actions]


class SmartAutomationPlannerTests(unittest.TestCase):
    def setUp(self):
        self.planner = SmartAutomationPlanner()

    def test_search_python_docs_maps_to_search_web(self):
        result = self.planner.plan("search Python docs")

        self.assertEqual(intents(result), [SemanticAutomationIntent.SEARCH_WEB])
        self.assertEqual(result.semantic_actions[0].query, "python docs")
        self.assertEqual(result.mode, AutomationMode.DIRECT_TOOL)
        self.assertTrue(result.dry_run)
        self.assertFalse(result.executable)

    def test_open_chrome_and_search_maps_to_visible_browser(self):
        result = self.planner.plan("open Chrome and search Python docs")

        self.assertEqual(intents(result), [SemanticAutomationIntent.SEARCH_VISIBLE_BROWSER])
        self.assertEqual(result.mode, AutomationMode.VISIBLE_BROWSER)
        self.assertEqual(result.semantic_actions[0].app, "chrome")
        self.assertEqual([step.tool_name for step in result.action_plan.steps], ["app", "app_interaction", "app_interaction", "app_interaction"])

    def test_create_file_named_test_maps_to_create_file(self):
        result = self.planner.plan("create a file named test")

        self.assertEqual(intents(result), [SemanticAutomationIntent.CREATE_FILE])
        self.assertEqual(result.semantic_actions[0].file_path, "test.txt")

    def test_create_file_and_write_maps_to_two_actions(self):
        result = self.planner.plan("create a file on desktop named meeting note and write meeting at 5 PM in it")

        self.assertEqual(intents(result), [SemanticAutomationIntent.CREATE_FILE, SemanticAutomationIntent.WRITE_FILE])
        self.assertEqual(result.semantic_actions[0].file_path, "desktop/meeting note.txt")
        self.assertEqual(result.semantic_actions[1].content, "meeting at 5 pm")

    def test_create_file_and_write_dry_run_mapping_allows_omitted_in_it_suffix(self):
        result = self.planner.plan("create a file on desktop named notes and write hello")

        self.assertEqual(intents(result), [SemanticAutomationIntent.CREATE_FILE, SemanticAutomationIntent.WRITE_FILE])
        self.assertEqual(result.semantic_actions[0].file_path, "desktop/notes.txt")
        self.assertEqual(result.semantic_actions[1].content, "hello")

    def test_put_this_in_file_asks_followup_without_context(self):
        result = self.planner.plan("put this in a file")

        self.assertEqual(intents(result), [SemanticAutomationIntent.SAVE_CONTENT_AS_FILE])
        self.assertEqual(result.missing_fields, ["content"])
        self.assertEqual(result.follow_up_question, "What should I write?")

    def test_search_this_asks_followup_without_context(self):
        result = self.planner.plan("search this")

        self.assertEqual(intents(result), [SemanticAutomationIntent.SEARCH_WEB])
        self.assertEqual(result.missing_fields, ["search_query"])
        self.assertEqual(result.follow_up_question, "What should I search?")

    def test_replace_that_uses_last_browser_query_context(self):
        context = AutomationContext(session_id="s1", last_browser_query="Python docs", active_app="chrome")

        result = self.planner.plan("replace that with AI news", context=context)

        self.assertEqual(intents(result), [SemanticAutomationIntent.REPLACE_ADDRESS_OR_SEARCH])
        self.assertEqual(result.semantic_actions[0].target, "Python docs")
        self.assertEqual(result.semantic_actions[0].query, "ai news")
        self.assertIsNone(result.follow_up_question)

    def test_add_bring_laptop_uses_document_context(self):
        context = AutomationContext(session_id="s1")
        context.current_document_context = {"app": "notepad", "title": "meeting"}

        result = self.planner.plan("add bring laptop", context=context)

        self.assertEqual(intents(result), [SemanticAutomationIntent.APPEND_TO_NOTE])
        self.assertEqual(result.semantic_actions[0].content, "bring laptop")

    def test_send_it_now_uses_message_draft_and_requires_confirmation(self):
        context = AutomationContext(session_id="s1")
        context.current_message_draft = {"recipient": "Rahul", "content": "I'm late"}

        result = self.planner.plan("send it now", context=context)

        self.assertEqual(intents(result), [SemanticAutomationIntent.SEND_MESSAGE_AFTER_CONFIRMATION])
        self.assertEqual(result.semantic_actions[0].recipient, "Rahul")
        self.assertTrue(result.requires_confirmation)
        self.assertEqual(result.mode, AutomationMode.CONFIRMED_EXECUTION)

    def test_tell_rahul_creates_draft_not_send(self):
        result = self.planner.plan("tell Rahul I'll be late")

        self.assertEqual(intents(result), [SemanticAutomationIntent.DRAFT_MESSAGE])
        self.assertEqual(result.semantic_actions[0].recipient, "Rahul")
        self.assertFalse(result.requires_confirmation)

    def test_delete_it_requires_confirmation(self):
        context = AutomationContext(session_id="s1", last_created_file_path="notes.txt")

        result = self.planner.plan("delete it", context=context)

        self.assertEqual(intents(result), [SemanticAutomationIntent.DELETE_FILE])
        self.assertTrue(result.requires_confirmation)
        self.assertEqual(result.safety_level, "CRITICAL")

    def test_put_world_in_it_claims_file_followup_or_asks_for_file(self):
        missing = self.planner.plan("put World in it", context=AutomationContext(session_id="s1"))
        context = AutomationContext(session_id="s1", last_created_file_path="notes.txt")
        claimed = self.planner.plan("put World in it", context=context)

        self.assertEqual(intents(missing), [SemanticAutomationIntent.APPEND_FILE])
        self.assertEqual(missing.missing_fields, ["file"])
        self.assertEqual(missing.follow_up_question, "Which file should I use?")
        self.assertEqual(intents(claimed), [SemanticAutomationIntent.APPEND_FILE])
        self.assertEqual(claimed.semantic_actions[0].file_path, "notes.txt")
        self.assertEqual(claimed.semantic_actions[0].content, "World")

    def test_click_delete_requires_confirmation(self):
        result = self.planner.plan("click delete")

        self.assertEqual(intents(result), [SemanticAutomationIntent.CLICK_TEXT])
        self.assertTrue(result.requires_confirmation)
        self.assertEqual(result.safety_level, "HIGH")

    def test_stop_maps_to_stop_current_action(self):
        result = self.planner.plan("stop")

        self.assertEqual(intents(result), [SemanticAutomationIntent.STOP_CURRENT_ACTION])

    def test_undo_that_requires_context(self):
        no_context = self.planner.plan("undo that")
        context = AutomationContext(session_id="s1", last_typed_text="hello")
        with_context = self.planner.plan("undo that", context=context)

        self.assertEqual(intents(no_context), [SemanticAutomationIntent.UNDO_SAFE])
        self.assertEqual(no_context.follow_up_question, "What should I undo?")
        self.assertEqual(with_context.missing_fields, [])

    def test_stt_safe_it_correction_only_with_automation_context(self):
        context = AutomationContext(session_id="s1", last_file_path="notes.txt")

        unchanged = self.planner.plan("safe it")
        corrected = self.planner.plan("safe it", context=context)

        self.assertEqual(unchanged.corrected_text, "safe it")
        self.assertEqual(corrected.corrected_text, "save it")
        self.assertIn("safe_it_to_save_it", corrected.corrections_applied)

    def test_stt_past_it_correction_only_with_ui_context(self):
        context = AutomationContext(session_id="s1", current_field_type="clipboard")

        unchanged = self.planner.plan("past it")
        corrected = self.planner.plan("past it", context=context)

        self.assertEqual(unchanged.corrected_text, "past it")
        self.assertEqual(corrected.corrected_text, "paste it")

    def test_duplicate_fingerprint_is_annotated_for_repeated_mutating_action(self):
        context = AutomationContext(session_id="s1")
        first = context.create_fingerprint(
            original_user_text="send it now",
            corrected_text="send it now",
            semantic_action=SemanticAutomationIntent.SEND_MESSAGE_AFTER_CONFIRMATION.value,
            target="Rahul",
            content="I'm late",
            tool_plan={"intent": SemanticAutomationIntent.SEND_MESSAGE_AFTER_CONFIRMATION.value, "preferred_tool": "message"},
        )
        context.record_fingerprint(first)
        context.current_message_draft = {"recipient": "Rahul", "content": "I'm late"}

        result = self.planner.plan("send it now", context=context)

        self.assertTrue(result.duplicate_risk)

    def test_dry_run_result_does_not_execute_tools(self):
        result = self.planner.plan("open Chrome and search Python docs")

        self.assertTrue(result.dry_run)
        self.assertFalse(result.executable)
        self.assertTrue(result.execution_deferred)
        self.assertEqual(result.metadata["planner_phase"], "dry_run_only")

    def test_live_routing_remains_unchanged(self):
        service = AutomationService()
        task_plan = TaskPlanner().plan("open chrome and search for python docs")

        self.assertTrue(task_plan.is_multistep)
        self.assertEqual([step.action for step in task_plan.steps], ["open", "search"])
        self.assertFalse(hasattr(service, "smart_automation_planner"))

    def test_mode_decision_examples(self):
        cases = {
            "create a file and write hello": AutomationMode.DIRECT_TOOL,
            "open Notepad and type hello": AutomationMode.VISIBLE_UI,
            "find latest AI news": AutomationMode.BACKGROUND_RESEARCH,
            "open Chrome and search AI news": AutomationMode.VISIBLE_BROWSER,
            "draft a message to Rahul": AutomationMode.DRAFT,
            "send it now": AutomationMode.CONFIRMED_EXECUTION,
            "what am I looking at": AutomationMode.OBSERVATION,
            "try again": AutomationMode.RECOVERY,
            "plan this but don't run it": AutomationMode.DRY_RUN,
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(self.planner.classify_mode(text), expected)


if __name__ == "__main__":
    unittest.main()
