#!/usr/bin/env python3
"""Photograph the Material select-tool panel, docked beside a wide canvas.

The panel used to be a raw ``wx.Panel`` full of native ``wx.Button`` and
``wx.SpinCtrl`` controls, floated a third of the way down the *left* edge of
the 3D viewport with a manual ``SetSize``/``Raise`` call -- squarely on top of
whatever the reader was trying to look at.  ``select.py`` now builds it from
the shell's own :class:`ToolPanel`/:class:`TupleNumberField`/``tool_button``
pieces, exactly as the already-converted paste and chunk tools do, and docks it
flush against the *right* edge instead of centring it over the world.

This drives the real ``SelectTool.__init__`` against a stub canvas -- the same
kind ``tests/test_selection_box_handle_wiring.py`` already uses to exercise
``BlockSelectionBehaviour`` without a loaded world -- and reads back the
composed panel with :func:`capture_surface.capture_composite`, so the picture
is the production widget tree rather than a redrawing of what it ought to look
like.

Run with::

    py -3.11 scripts/capture_select_tool_panel.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

_capture_profile = tempfile.mkdtemp(prefix="amulet-capture-profile-")
# Every store the application reads, not just the settings one -- they are
# separate on purpose, and a capture that moves only CONFIG_DIR still publishes
# the real machine's recent worlds with its user directory in every path.
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

import wx  # noqa: E402

import amulet_map_editor  # noqa: E402

if not str(Path(amulet_map_editor.__file__).resolve()).startswith(str(REPO_ROOT)):
    raise SystemExit(
        f"amulet_map_editor resolved to {amulet_map_editor.__file__}, "
        f"outside {REPO_ROOT}. The capture would describe a different checkout."
    )

from capture_surface import capture_composite  # noqa: E402

from amulet.api.selection import SelectionBox, SelectionGroup  # noqa: E402

from amulet_map_editor.api import preferences  # noqa: E402
from amulet_map_editor.programs.edit.api.key_config import DefaultKeys  # noqa: E402
from tests.test_selection_box_handle_wiring import (  # noqa: E402
    StubMouse,
    StubRenderer,
    StubSelection,
    StubWorld,
)

OUTPUT = REPO_ROOT / "docs" / "huishots" / "select-tool-panel.png"


class SelectToolStubCanvas(wx.Panel):
    """A real, ordinary child window standing in for the GL viewport.

    The wiring tests' ``StubCanvas`` is a top-level ``wx.Frame`` with no
    parent, which is the right shape for driving events in isolation but the
    wrong one here: ``ToolPanel`` docks itself against ``canvas.GetParent()``,
    exactly as the paste and chunk tools' panels do, so the stand-in needs a
    real parent -- and needs to be an *ordinary* child rather than another
    top-level window, or wx's "one child, no sizer, fill the parent" default
    silently stretches the dock panel back over the whole viewport the moment
    the host is laid out.  A plain ``wx.Panel`` alongside a host that owns its
    own sizer avoids both problems, matching how ``EditCanvas`` and the tool
    panel are real siblings inside ``EditExtension`` in the running editor.
    """

    background_colour = (0.10, 0.11, 0.13)

    def __init__(self, host: wx.Window):
        super().__init__(host)
        self.context_identifier = "select-tool-capture"
        from amulet_map_editor.api.opengl.camera import Projection

        camera = type(
            "Camera",
            (),
            {"rotation": (0.0, 0.0), "projection_mode": Projection.PERSPECTIVE},
        )()
        self.renderer = StubRenderer()
        self.camera = camera
        self.mouse = StubMouse()
        self.selection = StubSelection()
        self.selection.selection_group = SelectionGroup(
            SelectionBox((0, 0, 0), (8, 8, 8))
        )
        self.world = StubWorld()
        self.dimension = "minecraft:overworld"
        self.buttons = type("Buttons", (), {"pressed_actions": frozenset()})()
        self.key_binds = DefaultKeys
        self.cursors = []
        # A real ``EditCanvas`` is a GL canvas and answers a paint-driven
        # redraw by making its context current.  This stand-in is a plain
        # panel with no GL context at all, so the redraw is a no-op rather
        # than an ``AttributeError`` on every frame.
        self.context = None

    def SetCurrent(self, context):  # noqa: N802 - wx API spelling
        return True

    def SwapBuffers(self):  # noqa: N802 - wx API spelling
        return True

    def SetCursor(self, cursor):  # noqa: N802 - wx naming
        self.cursors.append(cursor)
        return True

    def mask_gl(self):
        pass


def main() -> int:
    app = wx.App()

    preferences.update(theme="dark", language_mode="bilingual")

    # ``host`` stands in for the ``EditExtension`` panel: in the real editor
    # the GL canvas and the tool panel are siblings inside it, the canvas
    # managed by ``EditExtension``'s own sizer and the panel positioned by
    # hand.  Giving ``host`` a real sizer here (rather than leaving it empty)
    # matters: a window with no sizer and exactly one real child window
    # silently stretches that child to fill it on every layout pass, which
    # would fight the panel's own docking the moment ``host.Layout()`` ran.
    host = wx.Frame(None, title="edit program host", size=(1400, 820))
    host_sizer = wx.BoxSizer(wx.VERTICAL)
    host.SetSizer(host_sizer)
    canvas = SelectToolStubCanvas(host)
    canvas.SetBackgroundColour(wx.Colour(26, 28, 33))
    host_sizer.Add(canvas, 1, wx.EXPAND)

    from amulet_map_editor.programs.edit.plugins.tools.select import SelectTool

    tool = SelectTool(canvas)
    tool.bind_events()
    tool.enable()

    panel = list(tool.windows())[0]
    panel.Show()
    host.Show()
    host.Layout()
    for _ in range(3):
        wx.YieldIfNeeded()

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    report = capture_composite(panel, OUTPUT)
    print(f"wrote {OUTPUT}")
    print(
        f"descendants={report['descendants']} routes={report['routes']} "
        f"skipped={report['skipped']} size={report['size']}"
    )

    # The panel must be docked at the canvas's right edge, not floated over
    # the middle of it -- that is the whole point of this capture.
    panel_rect = panel.GetRect()
    canvas_width = canvas.GetClientSize().GetWidth()
    right_gap = canvas_width - panel_rect.GetRight()
    print(
        f"panel rect={panel_rect} canvas_width={canvas_width} " f"right_gap={right_gap}"
    )
    if right_gap > 4:
        raise SystemExit(
            f"Select-tool panel is not docked to the canvas's right edge "
            f"(gap of {right_gap}px)."
        )
    if panel_rect.GetLeft() < canvas_width // 2:
        raise SystemExit(
            "Select-tool panel starts left of centre -- it is still floating "
            "over the world rather than docked at the edge."
        )

    host.Destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
