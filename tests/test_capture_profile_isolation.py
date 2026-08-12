"""A script whose captures get published must photograph a fresh profile.

This exists because the boundary was crossed rather than because it might be.
``scripts/capture_studio_surfaces.py`` published 270 images to the documentation
site taken against a real profile. Every one showed that machine's recent
worlds, with ``C:\\Users\\<name>\\...`` paths readable in the list, and every one
showed the application under a display name the user had renamed it to rather
than the name the product ships as. Nothing failed. The captures were real, the
harness reported success, the manifest was accurate, and the images were
published exactly as intended -- which is the whole difficulty: a capture of the
wrong profile is indistinguishable from a capture of the right one unless
somebody looks at what is written inside it.

Four sibling scripts in the same directory already isolated their profile. The
one whose output is published did not, and no guard existed to notice the
difference.

So: a hand-written list of the scripts that publish, and an assertion that each
one redirects ``CONFIG_DIR`` before the application can read it. Hand-written
because a scan can only check the scripts it finds; a new publishing script is
exactly the case that needs catching, and it catches it by failing until
somebody adds it here deliberately.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

#: Capture scripts whose images are committed and published. Add a new one here
#: in the same change that adds the script.
PUBLISHING_CAPTURE_SCRIPTS = (
    "capture_studio_surfaces.py",
    "capture_paste_anchor.py",
    "capture_select_tool_panel.py",
    "capture_selection_handles.py",
    "capture_update_banner.py",
)


@pytest.mark.parametrize("name", PUBLISHING_CAPTURE_SCRIPTS)
def test_the_script_exists(name: str) -> None:
    """A renamed or deleted script must fail here rather than vanish.

    Without this, removing a script from the tree silently removes it from
    every assertion below, and the suite reports the same green it did when
    the script was present and checked.
    """
    assert (SCRIPTS / name).is_file(), (
        f"{name} is listed as a publishing capture script but is not in "
        "scripts/. If it was renamed or retired, update this list in the same "
        "change rather than leaving a name nothing checks."
    )


@pytest.mark.parametrize("name", PUBLISHING_CAPTURE_SCRIPTS)
def test_it_redirects_the_profile_before_the_app_can_read_it(name: str) -> None:
    source = (SCRIPTS / name).read_text(encoding="utf-8")

    # Every store the application reads, because they are separate on purpose.
    # Redirecting CONFIG_DIR alone is what the first fix did: it removed the
    # renamed title from the captures and left the recent-worlds list still
    # reading the real machine's store, so every published row still showed a
    # real user directory. A capture moves all of them or it moves none of the
    # ones that matter.
    REQUIRED = ("CONFIG_DIR", "AMULET_RECENTS_DIR", "AMULET_HISTORY_DIR")
    missing = [store for store in REQUIRED if f'"{store}"' not in source]
    assert not missing, (
        f"{name} never redirects {', '.join(missing)}, so it photographs the "
        "profile of whoever runs it -- their recent worlds, their paths under "
        "their own user directory, and whatever they have renamed the "
        "application to. These images are published."
    )

    # Ordering is the other half, and it is the half that hides. The config
    # module reads the environment when it is imported, so a redirect written
    # after the first import of the application runs too late and does nothing
    # at all -- silently, which is how one of these shipped looking protected.
    first_assignment = re.search(r"os\.environ\[", source)
    first_app_import = re.search(
        r"^\s*(?:import|from)\s+(?:wx|amulet_map_editor)", source, re.MULTILINE
    )
    assert first_assignment, f"{name} names the stores but never assigns them"
    if first_app_import:
        assert first_assignment.start() < first_app_import.start(), (
            f"{name} assigns its environment at character "
            f"{first_assignment.start()}, after it imports the application at "
            f"{first_app_import.start()}. That redirect runs too late and the "
            "real profile is photographed anyway, with nothing failing to say so."
        )


@pytest.mark.parametrize("name", PUBLISHING_CAPTURE_SCRIPTS)
def test_the_redirect_goes_somewhere_temporary(name: str) -> None:
    """A fixed path under the repository is still a profile that accumulates.

    ``build/capture-config`` survives between runs, so a world opened during
    one capture run is in the recents list of every run afterwards. It is not
    the user's own profile, which is the important half, but it is not fresh
    either -- and a stale profile drifts back toward showing real data.
    """
    source = (SCRIPTS / name).read_text(encoding="utf-8")
    if "tempfile.mkdtemp" in source or "TemporaryDirectory" in source:
        return
    pytest.xfail(
        f"{name} redirects CONFIG_DIR to a fixed location rather than a fresh "
        "temporary directory, so its profile accumulates across runs. This is "
        "recorded rather than enforced: it is a real weakness, and it is not "
        "the leak that this file was written for."
    )
