import unittest

import run


class WakeWordRemovedTests(unittest.TestCase):
    def test_run_has_no_wake_word_supervisor(self):
        self.assertFalse(hasattr(run, "BackendSupervisor"))
        self.assertFalse(hasattr(run, "WAKE_PHRASES"))
        self.assertTrue(hasattr(run, "run_server"))


if __name__ == "__main__":
    unittest.main()
