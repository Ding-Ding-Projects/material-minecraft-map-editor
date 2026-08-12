"""The update-ready banner needs a real capture for every state it renders.

The completeness inventory used to credit auto-updates with implementation,
documentation and tests while declaring, in the same row, that nobody had ever
photographed the ready-banner UI -- the persistent "Restart to install update"
card the updater's whole contract is built around. A hand-written list is what
keeps that from happening again: a rule shaped "every captured file is a real
PNG" passes cleanly on a directory with no files in it, because it never looked
for the ones that are supposed to be there.

``scripts/capture_update_banner.py`` builds the real
``amulet_map_editor.api.framework.amulet_ui.AmuletUI`` frame off-screen, drives
its real ``_render_update_banner`` through every status the banner shows
(``available``, ``downloading``, ``ready_to_restart``, ``failed``), and reads
the status bar for the one state -- "no update" -- where the banner is
correctly hidden. This module checks that every one of those files exists,
decodes, and carries more than a background's worth of colour, so a blank or
missing capture fails the suite instead of quietly shipping as evidence.
"""

from __future__ import annotations

import pathlib

import pytest

wx = pytest.importorskip("wx", reason="wxPython is not installed in this environment")

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_OUT = _ROOT / "resource" / "img" / "update-banner"

#: Every state the ready banner (or its "no update" stand-in, the status bar)
#: must have a real, non-blank capture for. Hand-written on purpose: a glob
#: over whatever the directory happens to hold would pass on a run that
#: silently dropped a state, which is exactly the failure this guards against.
REQUIRED_CAPTURES = (
    "update-banner-available.png",
    "update-banner-downloading.png",
    "update-banner-ready-to-restart.png",
    "update-banner-failed.png",
    "update-banner-no-update.png",
)

#: Below this, a capture is almost certainly a blank card -- a background
#: rectangle and nothing else. It is a smoke floor, not a quality bar.
MIN_DISTINCT_COLOURS = 8


def _distinct_colours(path: pathlib.Path) -> int:
    image = wx.Image(str(path))
    assert image.IsOk(), f"{path} did not decode as an image"
    width, height = image.GetWidth(), image.GetHeight()
    assert width >= 8 and height >= 8, f"{path} is too small to be real content"
    seen = set()
    step = 3
    for x in range(0, width, step):
        for y in range(0, height, step):
            seen.add((image.GetRed(x, y), image.GetGreen(x, y), image.GetBlue(x, y)))
    return len(seen)


@pytest.mark.parametrize("filename", REQUIRED_CAPTURES)
def test_required_capture_exists_and_is_not_blank(filename: str) -> None:
    path = _OUT / filename
    assert path.is_file(), (
        f"{path} is missing -- run scripts/capture_update_banner.py to "
        "regenerate the ready-banner capture evidence"
    )
    colours = _distinct_colours(path)
    assert colours >= MIN_DISTINCT_COLOURS, (
        f"{path} has only {colours} distinct sampled colours; it looks blank "
        "rather than showing the banner's real title, body and buttons"
    )


def test_capture_directory_has_no_stray_files_outside_the_hand_written_list() -> None:
    """Catch a renamed or duplicated capture the list above was not updated for."""

    expected = set(REQUIRED_CAPTURES) | {"manifest.json"}
    actual = {entry.name for entry in _OUT.iterdir() if entry.is_file()}
    unexpected = actual - expected
    assert not unexpected, (
        f"unexpected files in {_OUT}: {sorted(unexpected)} -- add them to "
        "REQUIRED_CAPTURES above or remove them"
    )
    missing = expected - actual
    assert not missing, f"missing files in {_OUT}: {sorted(missing)}"
