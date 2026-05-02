import re
import unittest
from pathlib import Path


ALLOWED_CATEGORIES = {
    "KEEP_AS_SERVICE",
    "MOVE_TO_TOOL",
    "MOVE_TO_CONNECTOR",
    "MOVE_TO_AGENT",
    "MOVE_TO_REPOSITORY",
    "MOVE_TO_ADAPTER",
    "COMPATIBILITY_SHIM",
    "DEPRECATED_OR_UNUSED_CANDIDATE",
}


class ServiceCleanupMapTests(unittest.TestCase):
    def test_every_service_file_is_classified_once(self):
        root = Path(__file__).resolve().parents[1]
        service_files = sorted(path.name for path in (root / "app" / "services").glob("*.py"))
        report = (root / "reports" / "service_cleanup_map.md").read_text(encoding="utf-8")
        rows = {}

        for line in report.splitlines():
            if not line.startswith("| app/services/"):
                continue
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            service_name = cells[0].replace("app/services/", "")
            category = cells[7]
            rows.setdefault(service_name, []).append(category)

        self.assertEqual(sorted(rows), service_files)
        for service_name, categories in rows.items():
            with self.subTest(service=service_name):
                self.assertEqual(len(categories), 1)
                self.assertIn(categories[0], ALLOWED_CATEGORIES)

    def test_cleanup_map_rows_include_target_risk_and_tests(self):
        root = Path(__file__).resolve().parents[1]
        report = (root / "reports" / "service_cleanup_map.md").read_text(encoding="utf-8")
        row_pattern = re.compile(r"^\| app/services/[^|]+\.py \|", re.MULTILINE)
        rows = [line for line in report.splitlines() if row_pattern.match(line)]

        self.assertGreater(len(rows), 0)
        for row in rows:
            cells = [cell.strip() for cell in row.strip().strip("|").split("|")]
            with self.subTest(service=cells[0]):
                self.assertTrue(cells[8])
                self.assertIn(cells[9], {"LOW", "MEDIUM", "HIGH", "CRITICAL"})
                self.assertTrue(cells[10])


if __name__ == "__main__":
    unittest.main()
