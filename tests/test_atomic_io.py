import json
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from app.utils.atomic_io import write_json_atomic


class AtomicJsonWriteTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parent / "_tmp" / "atomic_io"
        if self.root.exists():
            shutil.rmtree(self.root)
        self.root.mkdir(parents=True)

    def tearDown(self):
        if self.root.exists():
            shutil.rmtree(self.root)

    def test_write_json_atomic_writes_valid_json(self):
        path = self.root / "state.json"

        write_json_atomic(path, {"ok": True, "items": [1, 2, 3]})

        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["items"], [1, 2, 3])

    def test_write_json_atomic_preserves_existing_file_on_failure(self):
        path = self.root / "state.json"
        write_json_atomic(path, {"version": 1})

        with patch("app.utils.atomic_io.json.dump", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                write_json_atomic(path, {"version": 2})

        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"version": 1})
        self.assertEqual(list(self.root.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
