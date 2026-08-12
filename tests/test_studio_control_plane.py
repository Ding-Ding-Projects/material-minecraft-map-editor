"""Tests for the wx-free live GitHub/git reader behind the Memory Console.

Every test injects a fake ``runner`` instead of shelling out to ``gh`` or
``git``, so these exercise the real parsing, degradation, and formatting
logic without touching the network or requiring an authenticated CLI.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = str(Path(__file__).resolve().parents[1])
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import amulet_map_editor

assert amulet_map_editor.__file__.startswith(REPO)

from amulet_map_editor.api.studio import control_plane as cp


def _runner(table):
    """Build a fake runner keyed by the argv joined with spaces."""

    def run(argv, cwd, timeout):
        key = " ".join(argv)
        for prefix, result in table.items():
            if key.startswith(prefix):
                return result
        return False, "", f"no fake result registered for: {key}"

    return run


# ---------------------------------------------------------------------------
# gh_status
# ---------------------------------------------------------------------------


def test_gh_status_available():
    runner = _runner({"gh auth status": (True, "Logged in", "")})
    status = cp.gh_status(runner=runner)
    assert status.available is True
    assert status.reason == ""


def test_gh_status_not_installed():
    def run(argv, cwd, timeout):
        return False, "", "gh is not installed or not on PATH"

    status = cp.gh_status(runner=run)
    assert status.available is False
    assert "not installed" in status.reason


def test_gh_status_not_authenticated():
    runner = _runner(
        {"gh auth status": (False, "", "You are not logged into any GitHub hosts")}
    )
    status = cp.gh_status(runner=runner)
    assert status.available is False
    assert "not signed in" in status.reason


def test_gh_status_rate_limited():
    runner = _runner({"gh auth status": (False, "", "API rate limit exceeded")})
    status = cp.gh_status(runner=runner)
    assert status.available is False
    assert "rate limit" in status.reason


def test_gh_status_offline():
    runner = _runner(
        {"gh auth status": (False, "", "Could not resolve host: github.com")}
    )
    status = cp.gh_status(runner=runner)
    assert status.available is False
    assert "offline" in status.reason.lower()


def test_gh_status_unknown_failure_keeps_message():
    runner = _runner({"gh auth status": (False, "", "something specific broke")})
    status = cp.gh_status(runner=runner)
    assert status.available is False
    assert status.reason == "something specific broke"


# ---------------------------------------------------------------------------
# git status
# ---------------------------------------------------------------------------


def test_git_status_summary_clean():
    runner = _runner({"git status": (True, "## main...origin/main\n", "")})
    result = cp.git_status_summary(runner=runner)
    assert result.available is True
    assert result.branch == "main"
    assert result.dirty_files == 0
    assert "clean" in result.summary()


def test_git_status_summary_dirty():
    out = "## main...origin/main [ahead 1]\n M foo.py\n?? bar.py\n"
    runner = _runner({"git status": (True, out, "")})
    result = cp.git_status_summary(runner=runner)
    assert result.branch == "main"
    assert result.dirty_files == 2
    assert "2 file" in result.summary()


def test_git_status_summary_failure():
    runner = _runner({"git status": (False, "", "not a git repository")})
    result = cp.git_status_summary(runner=runner)
    assert result.available is False
    assert "not a git repository" in result.summary()


# ---------------------------------------------------------------------------
# operations snapshot
# ---------------------------------------------------------------------------


def test_operations_snapshot_degrades_when_gh_unavailable():
    runner = _runner(
        {
            "git status": (True, "## main\n", ""),
            "gh auth status": (False, "", "not logged in"),
        }
    )
    snapshot = cp.fetch_operations_snapshot(runner=runner)
    assert snapshot.status.available is False
    assert snapshot.git.available is True
    assert snapshot.issues == ()
    assert snapshot.runs == ()


def test_operations_snapshot_reads_issues_and_runs():
    issues_json = json.dumps(
        [
            {
                "number": 5,
                "title": "Fix thing",
                "url": "https://x/5",
                "updatedAt": "2026-08-01",
            }
        ]
    )
    runs_json = json.dumps(
        [
            {
                "name": "CI",
                "status": "completed",
                "conclusion": "success",
                "headBranch": "main",
                "url": "https://x/runs/1",
            }
        ]
    )
    runner = _runner(
        {
            "git status": (True, "## main\n", ""),
            "gh auth status": (True, "ok", ""),
            "gh issue list": (True, issues_json, ""),
            "gh run list": (True, runs_json, ""),
            "gh repo view": (
                True,
                json.dumps({"owner": {"login": "acme"}, "name": "widgets"}),
                "",
            ),
            "gh api graphql -f query=query($owner": (
                True,
                json.dumps({"data": {"repository": {"discussions": {"nodes": []}}}}),
                "",
            ),
            "gh project list": (True, "ID\tTITLE\n", ""),
        }
    )
    snapshot = cp.fetch_operations_snapshot(runner=runner)
    assert snapshot.status.available is True
    assert len(snapshot.issues) == 1
    assert snapshot.issues[0].number == 5
    assert len(snapshot.runs) == 1
    assert snapshot.runs[0].conclusion == "success"


def test_operations_snapshot_records_issue_read_failure_reason():
    runner = _runner(
        {
            "git status": (True, "## main\n", ""),
            "gh auth status": (True, "ok", ""),
            "gh issue list": (False, "", "insufficient scope"),
            "gh run list": (True, "[]", ""),
            "gh repo view": (
                True,
                json.dumps({"owner": {"login": "acme"}, "name": "widgets"}),
                "",
            ),
            "gh api graphql -f query=query($owner": (
                True,
                json.dumps({"data": {"repository": {"discussions": {"nodes": []}}}}),
                "",
            ),
            "gh project list": (True, "ID\tTITLE\n", ""),
        }
    )
    snapshot = cp.fetch_operations_snapshot(runner=runner)
    assert snapshot.issues == ()
    assert "insufficient scope" in snapshot.issues_reason


# ---------------------------------------------------------------------------
# changelog snapshot
# ---------------------------------------------------------------------------


def test_changelog_snapshot_reads_releases_and_links_commits():
    releases_json = json.dumps(
        [
            {
                "tagName": "v1.0.0",
                "name": "1.0.0",
                "publishedAt": "2026-08-01T00:00:00Z",
                "url": "https://x/releases/v1.0.0",
                "isDraft": False,
            }
        ]
    )
    body_json = json.dumps({"body": "Shipped from commit 94630111cb48deadbeef."})
    runner = _runner(
        {
            "gh auth status": (True, "ok", ""),
            "gh release list": (True, releases_json, ""),
            "gh release view": (True, body_json, ""),
        }
    )
    snapshot = cp.fetch_changelog_snapshot(runner=runner)
    assert snapshot.status.available is True
    assert len(snapshot.releases) == 1
    release = snapshot.releases[0]
    assert release.tag == "v1.0.0"
    assert release.source_commit() == "94630111cb48deadbeef"


def test_changelog_snapshot_skips_drafts():
    releases_json = json.dumps(
        [
            {"tagName": "v2.0.0", "name": "2.0.0", "publishedAt": "", "isDraft": True},
        ]
    )
    runner = _runner(
        {
            "gh auth status": (True, "ok", ""),
            "gh release list": (True, releases_json, ""),
        }
    )
    snapshot = cp.fetch_changelog_snapshot(runner=runner)
    assert snapshot.releases == ()


def test_changelog_snapshot_degrades_when_gh_unavailable():
    runner = _runner({"gh auth status": (False, "", "rate limit exceeded")})
    snapshot = cp.fetch_changelog_snapshot(runner=runner)
    assert snapshot.status.available is False
    assert snapshot.releases == ()


def test_filter_releases_by_date_bounds():
    releases = (
        cp.ReleaseSummary(tag="a", name="a", published_at="2026-01-01T00:00:00Z"),
        cp.ReleaseSummary(tag="b", name="b", published_at="2026-06-01T00:00:00Z"),
        cp.ReleaseSummary(tag="c", name="c", published_at="2026-12-01T00:00:00Z"),
    )
    kept = cp.filter_releases_by_date(releases, start="2026-02-01", end="2026-11-01")
    assert [r.tag for r in kept] == ["b"]


def test_filter_releases_by_date_keeps_undated_release():
    releases = (cp.ReleaseSummary(tag="a", name="a", published_at=""),)
    kept = cp.filter_releases_by_date(releases, start="2026-02-01", end="2026-11-01")
    assert kept == releases


def test_export_releases_markdown_includes_commit_and_url():
    releases = (
        cp.ReleaseSummary(
            tag="v1.0.0",
            name="1.0.0",
            published_at="2026-08-01T00:00:00Z",
            url="https://x/releases/v1.0.0",
            body="Shipped from commit abc1234.",
        ),
    )
    text = cp.export_releases_markdown(releases)
    assert "# Changelog" in text
    assert "1.0.0" in text
    assert "abc1234" in text
    assert "https://x/releases/v1.0.0" in text


# ---------------------------------------------------------------------------
# post_discussion_comment: the one write path
# ---------------------------------------------------------------------------


def test_post_discussion_comment_requires_body():
    result = cp.post_discussion_comment("D_123", "   ", runner=_runner({}))
    assert result.ok is False
    assert "Nothing was typed" in result.message


def test_post_discussion_comment_requires_selected_discussion():
    result = cp.post_discussion_comment("", "hello", runner=_runner({}))
    assert result.ok is False
    assert "No Discussion" in result.message


def test_post_discussion_comment_success():
    payload = json.dumps(
        {
            "data": {
                "addDiscussionComment": {
                    "comment": {"id": "C_1", "url": "https://x/c/1"}
                }
            }
        }
    )
    runner = _runner({"gh api graphql": (True, payload, "")})
    result = cp.post_discussion_comment("D_123", "progress update", runner=runner)
    assert result.ok is True
    assert result.url == "https://x/c/1"


def test_post_discussion_comment_gh_failure():
    runner = _runner({"gh api graphql": (False, "", "HTTP 403")})
    result = cp.post_discussion_comment("D_123", "progress update", runner=runner)
    assert result.ok is False
    assert "HTTP 403" in result.message


def test_post_discussion_comment_never_leaks_token_argument():
    """The write path only ever sends query/id/body -- never a credential."""
    captured = {}

    def run(argv, cwd, timeout):
        captured["argv"] = argv
        return (
            True,
            json.dumps(
                {
                    "data": {
                        "addDiscussionComment": {"comment": {"url": "https://x/c/2"}}
                    }
                }
            ),
            "",
        )

    cp.post_discussion_comment("D_9", "hi", runner=run)
    joined = " ".join(captured["argv"])
    assert "token" not in joined.lower()
    assert "gh_token" not in joined.lower().replace(" ", "")
