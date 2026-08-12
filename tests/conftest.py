"""Session setup shared by the whole test suite.

Some suite fixtures are *generated* rather than committed in a form that stays
current — the changelog catalog is built from reachable Git tags and history, so
a checkout that has moved on since the catalog was last written no longer
matches it.  Continuous integration already regenerates it immediately before
running the tests, but a developer typing ``pytest tests`` does not, and the
result is 248 subtest failures that say nothing about the code under test and
bury the one failure that does.

Regenerating it here means the suite behaves the same way in both places, and
nobody has to know about an undocumented preparation step.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CHANGELOG_CATALOG = REPO_ROOT / "amulet_map_editor" / "api" / "changelog_catalog.json"
GENERATOR = REPO_ROOT / "scripts" / "generate_changelog.py"


def _head_revision() -> str | None:
    """Return the checkout's current commit, or None outside a repository."""
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if completed.returncode:
        return None
    return completed.stdout.strip() or None


def _catalog_revision() -> str | None:
    """Return the revision the committed catalog was generated from."""
    try:
        payload = json.loads(CHANGELOG_CATALOG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    revision = payload.get("source_revision")
    return revision if isinstance(revision, str) else None


def _catalog_covers_every_tag() -> bool:
    """Return whether the catalog already knows every reachable release tag.

    The commit alone is not enough to decide staleness: continuous integration
    publishes a release on every push, so new tags become reachable without HEAD
    moving at all.  A catalog generated an hour ago is then correct about its
    revision and missing three releases, which fails the changelog tests for a
    reason that has nothing to do with the change under test.
    """
    try:
        completed = subprocess.run(
            ["git", "tag", "--list"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return True
    if completed.returncode:
        return True
    tags = {tag.strip() for tag in completed.stdout.splitlines() if tag.strip()}
    if not tags:
        return True
    try:
        payload = json.loads(CHANGELOG_CATALOG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    known = {
        str(entry.get("tag", ""))
        for entry in payload.get("entries", [])
        if isinstance(entry, dict)
    }
    return tags.issubset(known)


def _regenerate_changelog_catalog() -> str:
    """Rebuild the catalog, returning a one-line description of what happened."""
    if not GENERATOR.is_file():
        return "changelog generator is absent; leaving the committed catalog in place"
    head = _head_revision()
    if head is None:
        return "not a Git checkout; leaving the committed catalog in place"
    if _catalog_revision() == head and _catalog_covers_every_tag():
        return "changelog catalog already matches HEAD and every reachable tag"
    completed = subprocess.run(
        [sys.executable, str(GENERATOR)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()[:400]
        # A failure here is reported rather than raised: the changelog tests
        # will fail with their own specific message, which is more useful than
        # collapsing the whole session at collection time.
        return f"changelog regeneration failed: {detail}"
    return f"changelog catalog regenerated for {head[:8]}"


@pytest.fixture(scope="session", autouse=True)
def generated_fixtures(request: pytest.FixtureRequest) -> None:
    """Bring generated suite fixtures up to date before anything runs."""
    message = _regenerate_changelog_catalog()
    reporter = request.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is not None:
        reporter.write_line(f"[conftest] {message}")


@pytest.fixture(scope="session", autouse=True)
def _one_wx_app_for_the_whole_session():
    """Create exactly one ``wx.App`` before any test runs, and never destroy it.

    Individual test modules each carry their own ``app`` fixture -- most of
    them written as ``existing = wx.App.Get(); created = wx.App(...) if
    existing is None else None``, destroying ``created`` at their own module
    teardown when they were the one that made it.  That pattern is correct
    for the case it was written for -- never leaving two ``wx.App``
    instances alive at once -- but across ~150 modules in one process it
    still means the App gets destroyed and a fresh one created dozens of
    times over the life of the suite, because whichever module's fixture
    runs first after a previous one tore its App down becomes the next
    "creator" in turn.

    Measured directly: ``tests/test_editor_toolbar_material_contract.py``'s
    dimension dropdown -- an ``AnchoredPopup(wx.PopupTransientWindow)`` --
    opens cleanly by itself and in small combinations of preceding files, but
    fails deep into a full run with
    ``TypeError: PopupTransientWindow.Popup(): first argument of unbound
    method must have type 'PopupTransientWindow'``.  That is wxPython's SIP
    layer refusing a method call because the instance's wrapped type no
    longer matches what it expects -- exactly the shape of damage repeated
    ``wx.App`` teardown/recreate cycles are documented to cause for
    platform-native popup classes on MSW, whose window-class registration is
    tied to the App's lifetime.  A single dedicated reproduction of 300
    create/open/destroy popup cycles under one *never-recreated* App did not
    fail, which is the other half of the evidence: the corruption tracks the
    App's own churn, not popup volume.

    Creating the App here, once, before ``generated_fixtures`` or any test
    module's own ``app`` fixture runs, means ``wx.App.Get()`` is never
    ``None`` again for the rest of the session: every module's own fixture
    reuses this instance and its own ``created`` branch never fires, so
    nothing ever tears it down mid-session.  It is deliberately never
    destroyed here either -- process exit reclaims it, and destroying it
    right before interpreter shutdown is its own separate source of the
    "crash while garbage-collecting" failure this suite has already hit once
    (see ``test_capture_blank_detection.py``'s history).
    """
    try:
        import wx
    except ImportError:
        return None
    try:
        app = wx.App.Get() or wx.App(False)
    except Exception:  # pragma: no cover - platform boundary, e.g. no display
        return None
    return app
