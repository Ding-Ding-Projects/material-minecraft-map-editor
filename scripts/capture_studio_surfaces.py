"""Walk the Amulet Studio interface and photograph it, writing a manifest.

Runs in-process on purpose. Two capture routes look plausible here and only one
of them tells the truth about this interface:

* ``PrintWindow`` (what an out-of-process screenshot uses) asks each window to
  draw itself. Native controls answer; a window that paints in its own
  ``EVT_PAINT`` with a buffered device context generally does not. This
  interface is owner-drawn end to end, so that route returns a plausible-looking
  grid of empty boxes and reads as a broken renderer rather than a broken
  capture.
* Blitting the window's own client device context copies the pixels actually on
  the surface, asking the window nothing. That is what ``capture_surface``
  does, and it is the only route that sees this interface.

One further trap, which cost a blank white file before it was understood: blit
the *individual* windows, not the composite panel that contains them. A device
context for a parent does not include its child windows on Windows, so
capturing the shell as one object omits everything inside it.

Every capture records its distinct-colour count in the manifest. A number near
the floor is a picture to retake rather than ship, because a blank capture is
worse than none: it looks like evidence.

Nothing here retouches an image. If a face renders as Segoe rather than the
design's IBM Plex, the capture shows Segoe and the manifest says so.

Usage:
    pythonw -3.11 scripts/capture_studio_surfaces.py --out resource/img
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import traceback
from datetime import date
from pathlib import Path
from typing import List

import wx

sys.path.insert(0, str(Path(__file__).resolve().parent))

from capture_surface import capture_composite, settle  # noqa: E402

from amulet_map_editor.api.studio import ribbon_defs  # noqa: E402
from amulet_map_editor.api.studio import specs as spec_registry  # noqa: E402
from amulet_map_editor.api.studio.shell import StudioShell  # noqa: E402
from amulet_map_editor.api.studio.spec_dialog import SpecDialog  # noqa: E402

BACKSTAGE_TABS = ("home", "open", "info", "convert", "features", "account")
PANES = ("ribbon", "navigator", "viewport", "properties", "status")


class Driver:
    def __init__(self, out: Path, commit: str, stamp: str) -> None:
        self.out = out
        self.commit = commit
        self.short = commit[:8]
        self.stamp = stamp
        self.rows: List[dict] = []
        self.failures: List[dict] = []
        self.app = wx.App(False)
        self.frame = wx.Frame(
            None, title="Amulet Studio", size=(1600, 1000), pos=(-32000, -32000)
        )
        host = wx.Panel(self.frame)
        sizer = wx.BoxSizer(wx.VERTICAL)
        self.shell = StudioShell(host, self.frame)
        sizer.Add(self.shell, 1, wx.EXPAND)
        host.SetSizer(sizer)
        self.frame.Show()
        settle(self.shell)

    def shoot(self, name: str, window, *, group: str, alt: str, surface: str) -> None:
        filename = f"{name}-{self.short}-{self.stamp}.png"
        try:
            settle(window)
            report = capture_composite(window, self.out / filename)
        except Exception as error:  # a blank or absent surface, reported not shipped
            self.failures.append(
                {"name": name, "reason": f"{type(error).__name__}: {error}"}
            )
            return
        self.rows.append(
            {
                "filename": filename,
                "surface": surface,
                "group": group,
                "theme": "light",
                "density": "comfortable",
                "viewport": f"{window.GetClientSize().width}x{window.GetClientSize().height}",
                "colours": report["colours"],
                "descendants": report["descendants"],
                "skipped": report.get("skipped", 0),
                "gate": report.get("gate", ""),
                "alt": alt,
                "verified": self.commit,
            }
        )

    def run(self) -> None:
        for tab in BACKSTAGE_TABS:
            self.shell.show_backstage(tab)
            settle(self.shell)
            self.shoot(
                f"backstage-{tab}",
                self.shell.backstage,
                group="Backstage",
                surface=f"backstage.{tab}",
                alt=f"Amulet Studio backstage, {tab} tab, in the light theme.",
            )

        self.shell.open_project(title="Capture World", platform="java")
        self.shell.show_workspace()
        settle(self.shell)

        workspace = self.shell.workspace
        for pane in PANES:
            window = getattr(workspace, pane, None)
            if window is None:
                self.failures.append({"name": f"pane-{pane}", "reason": "not exposed"})
                continue
            self.shoot(
                f"workspace-{pane}",
                window,
                group="Workspace",
                surface=f"workspace.{pane}",
                alt=f"The Amulet Studio workspace {pane}, in the light theme.",
            )

        ribbon = getattr(workspace, "ribbon", None)
        if ribbon is not None and hasattr(ribbon, "set_tab"):
            for key in ribbon_defs.TAB_KEYS:
                ribbon.set_tab(key)
                settle(ribbon)
                self.shoot(
                    f"ribbon-{key}",
                    ribbon,
                    group="Ribbon tabs",
                    surface=f"ribbon.{key}",
                    alt=(
                        f"The Amulet Studio ribbon with the {key} tab selected and "
                        "its panel open, in the light theme."
                    ),
                )

        for key in spec_registry.keys():
            spec = spec_registry.get(key)
            if spec is None:
                continue
            dialog = SpecDialog(self.frame, spec)
            dialog.Layout()
            dialog.Show()
            settle(dialog)
            self.shoot(
                key.lower(),
                dialog,
                group="Surfaces",
                surface=key,
                alt=(
                    f"The {spec.title} surface ({spec.eyebrow}), showing its window "
                    f"search and {len(spec.sections)} sections, in the light theme."
                ),
            )
            dialog.Hide()
            dialog.Destroy()
            wx.Yield()

    def report(self) -> dict:
        self.frame.Destroy()
        wx.Yield()
        return {
            "schemaVersion": 1,
            "commit": self.commit,
            "captured": self.stamp,
            "wxPython": wx.version(),
            "method": "capture_surface.capture_composite after settle()",
            "note": (
                "Captured by compositing each container's visible descendants, after "
                "settle(). An unsettled capture returns the container background with "
                "a few stray native controls on it and a plausible colour count -- the "
                "counts and descendant totals here are evidence, not a pass. A person "
                "has to look at a sample of every run."
            ),
            "captures": self.rows,
            "failures": self.failures,
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("resource/img"))
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--commit", default="")
    args = parser.parse_args()

    commit = (
        args.commit
        or subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True
        ).stdout.strip()
    )
    if not commit:
        raise SystemExit("could not resolve the commit being captured")

    args.out.mkdir(parents=True, exist_ok=True)
    driver = Driver(args.out, commit, date.today().strftime("%Y%m%d"))
    try:
        driver.run()
    except Exception:
        traceback.print_exc()
    report = driver.report()

    manifest = args.manifest or (args.out / f"capture-manifest-{commit[:8]}.json")
    manifest.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"captured {len(report['captures'])}, failed {len(report['failures'])}")
    for entry in report["failures"][:12]:
        print(f"  FAILED {entry['name']}: {entry['reason']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
