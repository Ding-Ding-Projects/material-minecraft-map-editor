#!/usr/bin/env python3
"""Photograph the Position section of the pending controls, both anchors.

Run it with no arguments; it writes ``docs/huishots/paste-anchor-centre.png``
and ``docs/huishots/paste-anchor-corner.png`` and prints the composite report
for each, so a reader can see whether anything was skipped before looking at
the files.

The pane is built around a stand-in pending object rather than a loaded world:
this captures a surface, and opening a world would make it a two-minute run for
a picture of the same 300 pixels.  What the surface says about a *real* clone is
proved by ``tests/test_editor_clone_runtime.py``, which drives these same
controls against a world and reads the blocks back afterwards.

**One known hole, and it is the harness rather than this pane.**  The value
inside a coordinate box lives in a native ``wx.TextCtrl``; ``_TextBox.render_to``
draws the outline and the axis letter and leaves the text to that control, which
does not answer ``PrintWindow`` with its content on a desktop nobody is
compositing.  So the three Position boxes photograph empty here exactly as they
do in every committed capture of the Clone tool.  The disclosure sentence, the
anchor picker's chosen value, and the *Fills from* / *Fills to* rows are all
owner-drawn and do appear, which is the part this capture exists to show.

A second harness artefact, for a reader of the files: the composite draws every
descendant at its own position without the scroller's clipping, so content that
has been scrolled out of the column still lands in the picture -- ghosted text
across the top and the footer's Confirm button over the last nudge row.  On
screen the scroller clips both.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

#: A throwaway profile, because the anchor this script chooses is persisted and
#: running a capture must not rewrite the settings of whoever ran it.
os.environ["CONFIG_DIR"] = tempfile.mkdtemp(prefix="amulet-paste-anchor-")

import wx  # noqa: E402

from capture_surface import capture_composite  # noqa: E402

from amulet_map_editor.api.studio import editor_tools  # noqa: E402
from amulet_map_editor.api.studio import properties_pane as pane_module  # noqa: E402
from amulet_map_editor.api.studio.widgets import SearchableChoice  # noqa: E402

OUTPUT = ROOT / "docs" / "huishots"

#: The same copy the runtime module clones, so the two describe one object.
EXTENT = (4, 1, 4)
LOCATION = (8, 40, 8)


def _install_stand_in() -> None:
    """Point the bridge at a pending object that behaves like a held copy."""
    state = {"location": LOCATION}

    def pending(*_args, **_kwargs):
        return editor_tools.PendingObject(
            location=state["location"],
            rotation=(0.0, 0.0, 0.0),
            scale=(1.0, 1.0, 1.0),
            following=False,
            drawn=True,
            size=" by ".join(str(value) for value in EXTENT),
            extent=EXTENT,
        )

    def set_location(location, *_args, **_kwargs):
        state["location"] = tuple(int(round(float(value))) for value in location)
        return True

    editor_tools.pending_object = pending
    editor_tools.set_pending_location = set_location
    editor_tools.active_tool_name = lambda *a, **k: "Paste"
    editor_tools.camera_location = lambda *a, **k: None
    editor_tools.movement_sentence = lambda *a, **k: ""


def _anchor_picker(pane):
    stack = [pane]
    while stack:
        node = stack.pop()
        if isinstance(node, SearchableChoice) and str(node.label).startswith(
            pane_module.ANCHOR_FIELD_LABEL
        ):
            return node
        stack.extend(node.GetChildren())
    return None


def _scroll_to(pane, window) -> None:
    """Put ``window``'s top at the top of the scrolling column."""
    scroller = pane.scroller
    top = scroller.ScreenToClient(window.GetScreenPosition()).y
    virtual = scroller.CalcUnscrolledPosition(0, top)[1]
    unit = scroller.GetScrollPixelsPerUnit()[1] or 1
    scroller.Scroll(-1, max(0, virtual // unit))
    wx.Yield()


def main() -> int:
    _install_stand_in()
    app = wx.App(False)  # noqa: F841 - the application must outlive the frame
    frame = wx.Frame(None, size=(360, 700), pos=(-32000, -32000))
    pane = pane_module.PropertiesPane(frame, title="java_1_12_2")
    sizer = wx.BoxSizer(wx.VERTICAL)
    sizer.Add(pane, 1, wx.EXPAND)
    frame.SetSizer(sizer)
    frame.Show()
    frame.Layout()
    wx.Yield()

    pane.show_tool_activation(
        editor_tools.Activation(
            key="cloneTool",
            label="Clone",
            ok=True,
            tool="Paste",
            kind="pending",
            message="The selection was copied and the paste tool is holding it.",
        )
    )
    pane.Layout()
    wx.Yield()

    picker = _anchor_picker(pane)
    if picker is None:
        print("no anchor picker was built; nothing to capture", file=sys.stderr)
        return 1

    reports = {}
    for name, anchor in (
        ("centre", editor_tools.ANCHOR_CENTRE),
        ("corner", editor_tools.ANCHOR_MINIMUM),
    ):
        picker.set_value(editor_tools.anchor_label(anchor), notify=True)
        wx.Yield()
        _scroll_to(pane, picker)
        pane.Layout()
        wx.Yield()
        report = capture_composite(pane, OUTPUT / f"paste-anchor-{name}.png")
        report["anchor"] = pane.position_anchor
        report["picker_on_screen"] = bool(picker.IsShownOnScreen())
        report["picker_rect"] = tuple(picker.GetScreenRect())
        report["visible_band"] = tuple(pane.scroller.GetScreenRect())
        report["box_rows"] = {
            key: pane._tool_rows[key].value
            for key, _label in pane_module.PASTE_BOX_ROWS
            if key in pane._tool_rows
        }
        report["position_boxes"] = list(pane._tool_fields["location"].values())
        reports[name] = report

    print(json.dumps(reports, indent=2, default=str))
    frame.Destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
