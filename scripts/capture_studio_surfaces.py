"""Hold one Amulet Studio surface open so a headless capture can photograph it.

This is deliberately a *launcher*, not a renderer, and that is the whole lesson
of building it. Rendering in-process -- blitting a `wx.ClientDC` of the shell
into a bitmap -- looks like the tidy answer and produces a **blank white image**:
on Windows a device context for a composite panel does not include its child
windows, so everything the user actually looks at is missing. `PrintWindow` does
include them, which is what the headless screenshot route uses, so the
application is held open here and captured from outside.

The opposite trap is worth stating beside it, because both produce a plausible
picture. Before the paint path was fixed, a `PrintWindow` capture came back with
every native control drawn and every owner-drawn control a flat grey rectangle.
That was not a limitation of the capture: the paint handlers were raising. A
capture that looks half-broken is evidence about the application, not about the
camera -- check which before concluding either.

Nothing here retouches an image. If a face renders as Segoe rather than the
design's IBM Plex, the capture shows Segoe and the manifest says Segoe.

Usage:
    pythonw -3.11 scripts/capture_studio_surfaces.py backstage home
    pythonw -3.11 scripts/capture_studio_surfaces.py workspace
    pythonw -3.11 scripts/capture_studio_surfaces.py ribbon terrain
    pythonw -3.11 scripts/capture_studio_surfaces.py surface railTunnel

The window is titled ``AMULET_CAPTURE::<name>`` so the capture driver can find
it by title. Resolve it by class as well: a wx Frame is ``wxWindowNR`` and a wx
Dialog is ``#32770``, and one wx process publishes roughly ten other top-level
windows -- IME, Cicero and UAC helpers -- several of them zero by zero.
"""

from __future__ import annotations

import sys

import wx

from amulet_map_editor.api.studio import ribbon_defs, specs as spec_registry
from amulet_map_editor.api.studio.shell import StudioShell
from amulet_map_editor.api.studio.spec_dialog import SpecDialog

#: Surfaces whose known layout defects are being fixed. Photographing one now
#: would put a picture of a defect into the README.
HELD = frozenset(
    {
        "brushTool",
        "editChunkTool",
        "layerSlice",
        "nbtLegacy",
        "structureLocator",
        "portalBuilder",
        "presets",
        "docs",
        "elementAppearance",
        "entityEdit",
        "errorReport",
        "pluginsDialog",
        "pythonConsole",
        "scriptConsole",
    }
)

BACKSTAGE_TABS = ("home", "open", "info", "convert", "features", "account")


class ShellFrame(wx.Frame):
    def __init__(self, name: str) -> None:
        super().__init__(None, title=f"AMULET_CAPTURE::{name}", size=(1600, 1000))
        host = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)
        self.shell = StudioShell(host, self)
        sizer.Add(self.shell, 1, wx.EXPAND)
        host.SetSizer(sizer)
        self.Show()


def main(argv: list[str]) -> int:
    mode = argv[0] if argv else "backstage"
    target = argv[1] if len(argv) > 1 else "home"

    app = wx.App(False)

    if mode == "surface":
        if target in HELD:
            print(f"{target} is held back while its layout defect is fixed")
            return 2
        spec = spec_registry.get(target)
        if spec is None:
            print(f"no surface registered under {target!r}")
            return 2
        host = wx.Frame(None, title="AMULET_CAPTURE::host", pos=(-32000, -32000))
        host.Show()
        dialog = SpecDialog(host, spec)
        dialog.SetTitle(f"AMULET_CAPTURE::{target}")
        dialog.Layout()
        dialog.Centre()
        dialog.Show()
    else:
        name = target if mode != "workspace" else "workspace"
        frame = ShellFrame(name)
        if mode == "workspace" or mode == "ribbon":
            frame.shell.open_project(title="Capture World", platform="java")
            frame.shell.show_workspace()
            if mode == "ribbon":
                ribbon = getattr(frame.shell.workspace, "ribbon", None)
                if ribbon is None or not hasattr(ribbon, "set_tab"):
                    print("the workspace exposes no ribbon.set_tab")
                    return 2
                if target not in ribbon_defs.TAB_KEYS:
                    print(f"{target!r} is not a ribbon tab")
                    return 2
                ribbon.set_tab(target)
        else:
            if target not in BACKSTAGE_TABS:
                print(f"{target!r} is not a backstage tab")
                return 2
            frame.shell.show_backstage(target)
        frame.Layout()

    # Let every deferred paint run before the driver takes the picture.
    for _ in range(4):
        wx.Yield()
    app.MainLoop()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
