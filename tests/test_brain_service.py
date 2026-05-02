import unittest

from app.services.brain_service import BrainService


class BrainServiceTaskParsingTests(unittest.TestCase):
    def setUp(self):
        self.service = BrainService(groq_service=object())
        self.service._llms = []

    def test_fast_task_parser_splits_multi_action_prompt_without_leaking_segments(self):
        decisions = self.service._fast_task_decisions(
            "Image can you generate an e-mail of a programming language called Python in a snake around it and open Chrome and search about, let's say Narendra Modi?"
        )

        self.assertEqual(
            decisions,
            [
                ("generate_image", "e-mail of a programming language called Python in a snake around it"),
                ("open", "Chrome"),
                ("google_search", "Narendra Modi"),
            ],
        )

    def test_parse_task_decisions_does_not_default_to_open_for_unparseable_llm_output(self):
        self.assertEqual(
            self.service._parse_task_decisions("I don't have enough information to determine the task type."),
            [],
        )

    def test_incomplete_write_prompt_is_treated_as_missing_task_details(self):
        task_types, method, _elapsed_ms = self.service.classify_task("Uh, can you write me an application for?")

        self.assertEqual(task_types, [])
        self.assertEqual(method, "rule-based")


if __name__ == "__main__":
    unittest.main()
