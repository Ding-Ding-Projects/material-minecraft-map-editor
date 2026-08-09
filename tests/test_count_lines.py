from __future__ import annotations

from io import StringIO
from pathlib import PurePosixPath
import unittest

from scripts.count_lines import (
    LineRow,
    _is_agent_identity,
    classify,
    collect_rows,
    write_csv,
)


class LineCounterContractTests(unittest.TestCase):
    def test_agent_identity_uses_words_not_name_substrings(self):
        self.assertTrue(_is_agent_identity("Claude Fable 5 <noreply@anthropic.com>"))
        self.assertTrue(_is_agent_identity("dependabot[bot] <bot@example.invalid>"))
        self.assertFalse(_is_agent_identity("Morgan Abbott <morgan@example.invalid>"))

    def test_classification_separates_generated_and_excluded_text(self):
        self.assertEqual(
            "generated",
            classify(PurePosixPath("amulet_map_editor/api/docs_articles.json")),
        )
        self.assertEqual("excluded", classify(PurePosixPath("package-lock.json")))
        self.assertEqual("excluded", classify(PurePosixPath("amulet_app.exe.txt")))
        self.assertEqual("tests", classify(PurePosixPath("tests/test_example.py")))
        self.assertEqual("styles-markup", classify(PurePosixPath("docs/guide.md")))
        self.assertEqual("source", classify(PurePosixPath("scripts/tool.py")))

    def test_live_repository_totals_and_attribution_are_internally_consistent(self):
        rows = collect_rows()
        for name in (
            "source",
            "tests",
            "styles-markup",
            "generated",
            "excluded",
            "project-total",
            "repository-grand-total",
        ):
            self.assertIn(name, rows)
            row = rows[name]
            self.assertEqual(
                row.total_lines,
                row.agent_lines + row.person_lines + row.unattributed_lines,
                name,
            )

        expected_project = LineRow()
        for name in ("source", "tests", "styles-markup"):
            expected_project.add(rows[name])
        self.assertEqual(expected_project, rows["project-total"])

        expected_grand = LineRow()
        for name in ("source", "tests", "styles-markup", "generated", "excluded"):
            expected_grand.add(rows[name])
        self.assertEqual(expected_grand, rows["repository-grand-total"])

        output = StringIO()
        write_csv(rows, output)
        table = output.getvalue()
        self.assertIn(
            "category,total_lines,nonblank_lines,agent_lines,person_lines,unattributed_lines",
            table,
        )
        self.assertIn("repository-grand-total,", table)


if __name__ == "__main__":
    unittest.main()
