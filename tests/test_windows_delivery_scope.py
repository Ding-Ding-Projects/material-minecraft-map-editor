"""Keep the active release surface bounded to the supported Windows installer."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github/workflows"


def test_only_windows_packaging_workflow_remains_active():
    # Two workflows now, both Windows-only: build-windows.yml still builds
    # (report-only tests) the wxPython/PyInstaller app, and
    # build-electron-windows.yml builds and publishes the Electron Squirrel
    # installer -- the only thing this project ships a GitHub release for.
    # Neither is a non-Windows lane, so the delivery scope this test guards
    # (Windows only) still holds; it is the publishing surface that moved.
    names = {path.name for path in WORKFLOWS.glob("build-*.yml")}
    assert names == {"build-windows.yml", "build-electron-windows.yml"}


def test_windows_workflow_keeps_push_dispatch_and_squirrel_contract():
    """The wx workflow still builds on push and on demand, and still packages.

    ``release:`` was in this list because this workflow used to publish, and
    reacting to a publication made sense then. It does not now: the Electron
    workflow publishes, so every Electron release woke this one up and sent it
    looking for a previous *wxPython* Squirrel feed to build a delta
    against -- ``Amulet-<version>-full.nupkg`` assets that an Electron release
    does not have and never will. It failed at "Fetch previous Squirrel feed
    for delta" every time, which meant shipping the Electron app turned this
    workflow red on a schedule.

    The trigger is deliberately gone and this assertion follows it. What the
    test still guards is the part that matters: this workflow keeps building
    the wxPython app on every push and on demand, and keeps producing its
    Squirrel artifacts, so that build cannot rot unnoticed now that nothing
    publishes it.
    """
    source = (WORKFLOWS / "build-windows.yml").read_text(encoding="utf-8")
    assert "  release:" not in source, (
        "build-windows.yml reacts to a release again. It no longer publishes "
        "one, and the Electron release it would react to has no wxPython "
        "Squirrel feed for its delta step to find."
    )
    for marker in (
        "  push:",
        "  workflow_dispatch:",
        "Windows - Create unsigned Squirrel.Windows release",
        "Setup.exe",
        "RELEASES",
        "full.nupkg",
    ):
        assert marker in source
