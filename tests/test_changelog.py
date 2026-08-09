import json
import re
import subprocess
import sys
import unittest
from datetime import date

from amulet_map_editor.api.changelog import (
    ChangelogCatalog,
    ChangelogQuery,
    ChangelogValidationError,
    UnsupportedChangelogVersion,
    available_actions,
    export_markdown,
    filter_changelog,
    load_bundled_catalog,
    validate_commit_links,
)
from amulet_map_editor.api.regex_builder import RegexBuilder


class ChangelogTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_bundled_catalog()

    def test_catalog_covers_every_reachable_release_tag(self):
        tags = subprocess.run(
            ["git", "tag", "--merged", "HEAD", "--format=%(refname:strip=2)"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout.splitlines()
        self.assertEqual(set(tags), {entry.version for entry in self.catalog.entries})
        self.assertEqual(len(tags), len(self.catalog.entries))

    def test_every_commit_link_resolves_to_a_reachable_local_commit(self):
        result = subprocess.run(
            ["git", "rev-list", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        reachable = set(result.stdout.splitlines())
        missing = validate_commit_links(
            self.catalog, lambda revision: revision in reachable
        )
        self.assertEqual((), missing)

    def test_catalog_shas_dates_and_subjects_match_git_history(self):
        references = subprocess.run(
            ["git", "show-ref", "--tags", "-d"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout.splitlines()
        tagged_commits = {}
        for reference in references:
            revision, name = reference.split(" ", 1)
            tag = name.removeprefix("refs/tags/")
            if tag.endswith("^{}"):
                tagged_commits[tag[:-3]] = revision
            else:
                tagged_commits.setdefault(tag, revision)

        revisions = sorted({entry.commit_sha for entry in self.catalog.entries})
        facts_output = subprocess.run(
            [
                "git",
                "show",
                "-s",
                "--format=%H%x1f%cs%x1f%s",
                "--end-of-options",
                *revisions,
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout.splitlines()
        facts = {}
        for record in facts_output:
            revision, released_on, subject = record.split("\x1f", 2)
            facts[revision] = (released_on, subject)

        for entry in self.catalog.entries:
            with self.subTest(version=entry.version):
                self.assertEqual(tagged_commits[entry.version], entry.commit_sha)
                released_on, subject = facts[entry.commit_sha]
                self.assertEqual(released_on, entry.released_on.isoformat())
                self.assertEqual(subject, entry.changes[0].summary)

    def test_date_action_and_plain_text_filters_compose(self):
        candidates = [
            entry
            for entry in self.catalog.entries
            if date(2026, 7, 1) <= entry.released_on <= date(2026, 7, 31)
            and any(change.action == "fixed" and "registry" in change.summary.casefold() for change in entry.changes)
        ]
        self.assertTrue(candidates, "current catalog should retain a fixed registry change")
        result = filter_changelog(
            self.catalog,
            ChangelogQuery(
                start_date=date(2026, 7, 1),
                end_date=date(2026, 7, 31),
                actions=("fixed",),
                text="registry",
            ),
        )
        self.assertEqual(tuple(entry.version for entry in candidates), tuple(entry.version for entry in result.entries))
        self.assertTrue(all(change.action == "fixed" for entry in result.entries for change in entry.changes))

    def test_text_filter_accepts_bounded_regex_builder_hook(self):
        builder = RegexBuilder(r"Wayland|x11", flags=re.IGNORECASE, regex_enabled=True)
        compiled = builder.compile()
        fixture = ChangelogCatalog.from_dict(
            {
                "schema_version": 1,
                "repository_url": "https://github.com/example/project",
                "source_revision": "a" * 40,
                "entries": [
                    {
                        "version": "fixture",
                        "released_on": "2026-06-01",
                        "commit_sha": "b" * 40,
                        "changes": [
                            {
                                "action": "changed",
                                "summary": "Wayland and x11 fixture",
                                "commit_sha": "b" * 40,
                            }
                        ],
                    }
                ],
            }
        )
        result = filter_changelog(
            fixture,
            ChangelogQuery(text=builder.pattern),
            text_matcher=lambda value: compiled.search(value) is not None,
        )
        summaries = [
            change.summary for entry in result.entries for change in entry.changes
        ]
        self.assertTrue(any("Wayland" in summary for summary in summaries))
        self.assertTrue(any("x11" in summary.casefold() for summary in summaries))

    def test_actions_are_derived_with_counts(self):
        actions = dict(available_actions(self.catalog.entries))
        self.assertTrue(actions)
        self.assertTrue(all(count > 0 for count in actions.values()))
        self.assertEqual(len(self.catalog.entries), sum(actions.values()))

    def test_markdown_export_keeps_version_date_summary_and_commit_link(self):
        filtered = filter_changelog(self.catalog, ChangelogQuery())
        markdown = export_markdown(filtered, title="Filtered changelog")
        self.assertIn("# Filtered changelog", markdown)
        first = filtered.entries[0]
        self.assertIn(f"## {first.version} — {first.released_on.isoformat()}", markdown)
        self.assertIn(first.changes[0].summary, markdown)
        self.assertIn(f"/commit/{first.changes[0].commit_sha}", markdown)

    def test_empty_filtered_export_is_explicit(self):
        empty = filter_changelog(
            self.catalog, ChangelogQuery(text="definitely-not-a-release-subject")
        )
        self.assertIn("No changelog entries match", export_markdown(empty))

    def test_invalid_schema_unknown_fields_and_ranges_fail_closed(self):
        document = {
            "schema_version": 2,
            "repository_url": "https://github.com/example/project",
            "source_revision": "0" * 40,
            "entries": [],
        }
        with self.assertRaises(UnsupportedChangelogVersion):
            ChangelogCatalog.from_dict(document)
        document["schema_version"] = 1
        document["surprise"] = True
        with self.assertRaises(ChangelogValidationError):
            ChangelogCatalog.from_dict(document)
        with self.assertRaises(ChangelogValidationError):
            ChangelogQuery(start_date=date(2026, 8, 2), end_date=date(2026, 8, 1))

    def test_bundled_json_is_utf8_and_strict_json(self):
        from importlib.resources import files

        payload = (
            files("amulet_map_editor.api")
            .joinpath("changelog_catalog.json")
            .read_text(encoding="utf-8")
        )
        self.assertIsInstance(json.loads(payload), dict)

    def test_core_import_and_catalog_loading_do_not_require_wx(self):
        completed = subprocess.run(
                [
                    sys.executable,
                "-c",
                "import sys; sys.modules['wx'] = None; "
                "from amulet_map_editor.api.changelog import load_bundled_catalog; "
                "assert load_bundled_catalog().entries",
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual("", completed.stderr)


if __name__ == "__main__":
    unittest.main()
