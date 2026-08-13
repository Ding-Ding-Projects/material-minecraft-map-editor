"""The site's captures exist, are distinct, and say what they show.

The site had every other kind of evidence and no pictures. Its runtime contract
executes the real scripts in jsdom, which proves the page does not throw on
load -- and jsdom has no renderer, so it can say nothing at all about whether
anything is visible. A surface can satisfy every assertion in that file while
rendering as a blank column.

This checks the output of ``scripts/capture_site_surfaces.js``, which drives a
real browser headlessly. The browser is not run here: it is not on every
machine that runs this suite, and a capture run takes long enough that putting
it in the unit suite would make people skip the suite. What is checked is that
the committed evidence is real evidence.

The distinctness assertion is the one that matters, and it is here because the
harness's own first run failed it. That run reported "10 captured, 0 failed"
while four of the ten were byte-identical copies of the home page: every
selector in it had been invented rather than read out of the site, so each
opener silently did nothing and photographed whatever was already on screen.
Nothing in a count of files can see that.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHOTS = ROOT / "docs" / "huishots" / "site"
MANIFEST = SHOTS / "manifest.json"

#: Below this, the harness has broken rather than the site having shrunk. A
#: sweep that silently captures nothing passes every other assertion here.
MINIMUM_CAPTURES = 20

#: A rendered page is never this small. A blank one is, and a blank capture is
#: worse than a missing one because it looks like evidence.
MINIMUM_BYTES = 5000


@pytest.fixture(scope="module")
def manifest() -> dict:
    if not MANIFEST.exists():
        pytest.fail(
            f"No capture manifest at {MANIFEST.relative_to(ROOT).as_posix()}. "
            "Run `node scripts/capture_site_surfaces.js`. This is not skipped: "
            "skipping would leave the suite green while the site had no visual "
            "evidence at all, which is the state this file exists to end."
        )
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_the_run_captured_a_real_number_of_surfaces(manifest: dict) -> None:
    captures = manifest["captures"]
    assert len(captures) >= MINIMUM_CAPTURES, (
        f"Only {len(captures)} site surfaces were captured. Either the site "
        "lost most of its surfaces, or -- far more likely -- the harness "
        "stopped finding them and every assertion below is now passing on "
        "an almost empty list."
    )


def test_every_declared_capture_exists_and_is_not_blank(manifest: dict) -> None:
    faults = []
    for entry in manifest["captures"]:
        path = SHOTS / entry["filename"]
        if not path.exists():
            faults.append(f"{entry['filename']}: declared in the manifest, not on disk")
            continue
        size = path.stat().st_size
        if size < MINIMUM_BYTES:
            faults.append(
                f"{entry['filename']}: {size} bytes, which is a blank or "
                "near-blank page rather than a rendered surface"
            )
    assert not faults, "Captures that are not real evidence:\n  " + "\n  ".join(faults)


def test_no_two_captures_are_the_same_image(manifest: dict) -> None:
    """Two identical files are one surface counted twice.

    An opener that fails silently -- a renamed id, a tab that no longer
    exists, a control moved behind a menu -- leaves the previous surface on
    screen and photographs that. The file count still goes up.
    """
    digests: dict[str, str] = {}
    collisions = []
    for entry in manifest["captures"]:
        path = SHOTS / entry["filename"]
        if not path.exists():
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest in digests:
            collisions.append(f"{entry['filename']} is identical to {digests[digest]}")
        else:
            digests[digest] = entry["filename"]
    assert not collisions, (
        "These captures are the same image under different names, so an "
        "opener ran without changing anything on screen:\n  " + "\n  ".join(collisions)
    )


def test_every_capture_says_what_it_shows(manifest: dict) -> None:
    """Alt text, so the evidence is readable by somebody who cannot see it."""
    missing = [
        entry["filename"]
        for entry in manifest["captures"]
        if not str(entry.get("alt", "")).strip()
    ]
    assert not missing, f"Captures with no alt text: {missing}"


def test_failures_are_recorded_rather_than_omitted(manifest: dict) -> None:
    """A gap nobody mentions reads as coverage.

    This does not require the failure list to be empty -- a surface the
    harness genuinely cannot reach is a fact, not a test failure. It requires
    each one to carry a reason, so the gap stays legible instead of becoming
    a silently shorter list.
    """
    unexplained = [
        failure.get("surface", "?")
        for failure in manifest.get("failures", [])
        if not str(failure.get("reason", "")).strip()
    ]
    assert not unexplained, f"Failures recorded with no reason: {unexplained}"
