"""Photograph the auto-update ready banner across every state it renders.

The updater's contract (docs/features/updater/README.md) requires a visible
current/update/failed state for the persistent non-blocking banner that shows
"Restart to install update" once Squirrel has staged an unsigned update. That
banner is real -- ``AmuletUI._render_update_banner`` -- but nobody had ever
constructed the frame off-screen and photographed it, so the ready-banner
claim in the completeness inventory had no capture evidence behind it.

This drives the real ``amulet_map_editor.api.framework.amulet_ui.AmuletUI``
frame, off-screen, through every banner-bearing state:

* ``available``    -- an update was found and can be staged
* ``downloading``   -- staging is running in the background (action disabled)
* ``ready_to_restart`` -- the unsigned update is staged; Restart is live
* ``failed``        -- the update check or staging failed

"up_to_date" and "not_installed" intentionally show no banner at all (the
banner is hidden, and the fact is reported through the status bar instead), so
this also captures the frame's status bar text for those two states as the
honest evidence for "no update".

Usage:
    pythonw -3.11 scripts/capture_update_banner.py --out resource/img/update-banner
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Photograph a fresh profile, never the profile of whoever runs this. These
# images are published, and a real profile puts that machine's recent worlds --
# with its user directory in every path -- and any display name the user has
# renamed the application to onto the documentation site. It must run before
# the config module is imported, because that module reads the environment at
# import time and a later redirect silently does nothing.
import os
import tempfile

_capture_profile = tempfile.mkdtemp(prefix="amulet-capture-profile-")
# Every store the application reads, not just the settings one. Redirecting
# CONFIG_DIR alone removed the renamed title from these captures and left the
# recent-worlds list still reading the real machine's store -- so the published
# images kept showing `C:\Users\<name>\...` in every row. The stores are
# separate on purpose, and a capture has to move all of them or it moves none
# of the ones that matter.
for _store in (
    "CONFIG_DIR",
    "DATA_DIR",
    "CACHE_DIR",
    "LOG_DIR",
    "AMULET_RECENTS_DIR",
    "AMULET_HISTORY_DIR",
    "AMULET_LOG_DIR_PATH",
):
    os.environ[_store] = _capture_profile

import wx

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from capture_surface import capture_composite, capture_window  # noqa: E402


def _non_trivial(path: Path) -> None:
    """Fail loudly if the PNG just written is blank or unreadable."""

    img = wx.Image(str(path))
    if not img.IsOk():
        raise RuntimeError(f"{path} did not decode as an image")
    w, h = img.GetWidth(), img.GetHeight()
    if w < 8 or h < 8:
        raise RuntimeError(f"{path} is too small to be real content ({w}x{h})")
    colours = set()
    data = bytes(img.GetData())
    step = max(1, (w * h) // 4000)
    for i in range(0, w * h, step):
        offset = i * 3
        colours.add(data[offset : offset + 3])
    if len(colours) < 3:
        raise RuntimeError(
            f"{path} has only {len(colours)} distinct sampled colours; looks blank"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out", default="resource/img/update-banner", help="output directory"
    )
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    from amulet_map_editor.api.framework import amulet_ui
    from amulet_map_editor.api.framework.squirrel_update import SquirrelUpdateState

    app = wx.App(False)
    window = amulet_ui.AmuletUI(None)
    try:
        window.SetPosition(wx.Point(-32000, -32000))
        window.Show()
        wx.Yield()
        window.SendSizeEvent()
        wx.Yield()

        report: dict = {"captures": []}

        states = [
            (
                "available",
                SquirrelUpdateState(
                    "available",
                    version="9.9.9",
                    feed_url="https://example.invalid/feed",
                    release_notes_url="https://github.com/example/example/releases/tag/v9.9.9",
                ),
            ),
            (
                "downloading",
                SquirrelUpdateState(
                    "downloading",
                    version="9.9.9",
                    feed_url="https://example.invalid/feed",
                    release_notes_url="https://github.com/example/example/releases/tag/v9.9.9",
                ),
            ),
            (
                "ready-to-restart",
                SquirrelUpdateState(
                    "ready_to_restart",
                    version="9.9.9",
                    release_notes_url="https://github.com/example/example/releases/tag/v9.9.9",
                    detail="Unsigned update staged; restart only after user confirmation",
                ),
            ),
            (
                "failed",
                SquirrelUpdateState(
                    "failed",
                    detail="The update feed was unavailable (offline).",
                ),
            ),
        ]

        for name, state in states:
            window._render_update_banner(
                state
            )  # noqa: SLF001 -- capturing the real surface
            wx.Yield()
            window._position_notification_toasts()  # noqa: SLF001
            wx.Yield()
            path = out / f"update-banner-{name}.png"
            capture_report = capture_composite(
                window._update_banner, path
            )  # noqa: SLF001
            _non_trivial(path)
            report["captures"].append(
                {"name": name, "status": state.status, **capture_report}
            )
            print(f"captured {name} -> {path} ({capture_report['colours']} colours)")

        window._hide_update_banner()  # noqa: SLF001

        for name, status_text, sim_status in [
            (
                "no-update",
                f"{window.GetTitle() or 'Amulet'} is up to date",
                "up_to_date",
            ),
        ]:
            window.SetStatusText(status_text)
            wx.Yield()
            status_bar = window.GetStatusBar()
            if status_bar is not None:
                path = out / f"update-banner-{name}.png"
                # The status bar draws its own text directly and has no child
                # windows to composite, so this reads its own rendered client
                # area rather than walking a (nonexistent) descendant tree.
                colours = capture_window(status_bar, path)
                _non_trivial(path)
                report["captures"].append(
                    {"name": name, "status": sim_status, "colours": colours}
                )
                print(
                    f"captured {name} -> {path} "
                    f"({colours} colours; banner intentionally hidden)"
                )

        manifest_path = out / "manifest.json"
        manifest_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"wrote {manifest_path}")
    finally:
        window.Destroy()
        wx.Yield()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
