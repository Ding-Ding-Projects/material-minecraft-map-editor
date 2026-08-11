"""Private working shorthand must never reach a user-facing surface.

The shorthand this project's authors use in conversation is for conversation.
A commit subject carrying one is a mistake that has already happened here --
`d7cc7c21` shipped one -- and a published commit message cannot be corrected
without rewriting history.  Everything downstream of it can be, and the
generated changelog catalog is downstream: the in-application changelog viewer
renders it to users.

So the guard is on the artifact, not on the commit: whatever a subject says, the
catalog the application ships must read as ordinary technical English.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CATALOG = REPO_ROOT / "amulet_map_editor" / "api" / "changelog_catalog.json"
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from generate_changelog import (  # noqa: E402
    PRIVATE_TERM_REPLACEMENTS,
    sanitise_subject,
)


def test_every_private_term_is_replaced_with_ordinary_english():
    """Each shorthand becomes the plain technical term it stands for."""
    for term, replacement in PRIVATE_TERM_REPLACEMENTS:
        rendered = sanitise_subject(f"Change the {term} today")
        assert (
            term.lower() not in rendered.lower()
        ), f"{term!r} survived sanitisation: {rendered!r}"
        assert replacement.lower() in rendered.lower()


def test_an_ordinary_subject_is_left_exactly_alone():
    """Sanitising must not rewrite prose that was never shorthand."""
    for subject in (
        "Fix the chunk builder",
        "Add a review step",
        "Normalize repository Python formatting",
        "Reduce the widget redraw cost",
    ):
        assert sanitise_subject(subject) == subject


def test_capitalisation_survives_the_substitution():
    """A sanitised subject still reads as a sentence."""
    assert sanitise_subject("Dewed the branch").startswith("Pushed")


@pytest.mark.skipif(not CATALOG.is_file(), reason="catalog has not been generated")
def test_the_shipped_catalog_contains_no_private_shorthand():
    """The artifact users actually read is the one that has to be clean."""
    payload = json.loads(CATALOG.read_text(encoding="utf-8"))
    offenders = []
    for entry in payload.get("entries", []):
        for change in entry.get("changes", []):
            summary = str(change.get("summary", ""))
            for term, _ in PRIVATE_TERM_REPLACEMENTS:
                # Whole-word only: "reviewer" must not trip on a term inside it.
                words = {word.strip(".,:;()[]").lower() for word in summary.split()}
                if term.lower() in words or term.lower() in summary.lower().split(
                    " and "
                ):
                    if term.lower() in summary.lower():
                        offenders.append((entry.get("tag"), summary, term))
    assert not offenders, (
        "the shipped changelog carries private working shorthand, which the "
        f"in-application viewer renders to users: {offenders[:5]}"
    )
