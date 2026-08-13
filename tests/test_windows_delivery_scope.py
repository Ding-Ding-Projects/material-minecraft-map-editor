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


def test_windows_workflow_keeps_push_dispatch_release_and_squirrel_contract():
    source = (WORKFLOWS / "build-windows.yml").read_text(encoding="utf-8")
    for marker in (
        "  push:",
        "  workflow_dispatch:",
        "  release:",
        "Windows - Create unsigned Squirrel.Windows release",
        "Setup.exe",
        "RELEASES",
        "full.nupkg",
    ):
        assert marker in source
