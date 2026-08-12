#!/usr/bin/env python3
"""Photograph the Position section of the pending controls, in both languages.

Run it with no arguments; it writes ``docs/huishots/paste-anchor-centre.png``,
``docs/huishots/paste-anchor-corner.png`` and
``docs/huishots/paste-anchor-cantonese.png``, and prints the composite report
for each, so a reader can see whether anything was skipped before looking at
the files.

**The Cantonese one is not decoration.**  Every string in this section reaches
the reader through ``studio_label`` or ``studio_text``, and both return the
English untouched when no Cantonese was supplied -- a silent failure that an
English-only capture cannot show, because in English the two are the same
picture.  A reader of these files should be able to see that the picker, its
options, the disclosure sentence and the two box rows are all in the language
that was asked for.

A note for whoever reads that file: the Cantonese-specific characters (嚿, 嘢,
啲, 喺, 嗰) come from a fallback face and render with colour fringing where the
rest of the text does not.  That is the platform picking a font for glyphs the
primary face lacks, it predates this section, and it applies to every Cantonese
string in the product rather than these.

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

from capture_surface import capture_composite  # noqa: E402

from amulet_map_editor.api import preferences  # noqa: E402
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
    """Find the anchor picker whatever language its label is in.

    Matched on the shape of its option list rather than on the English label.
    A ``startswith(ANCHOR_FIELD_LABEL)`` finder silently returns nothing the
    moment the pane is not English, and this script would then report "no
    picker" for a picker sitting right there -- which is exactly what it did
    the first time the Cantonese capture was added.
    """
    names = {editor_tools.anchor_label(key) for key, _label in editor_tools.ANCHORS} | {
        editor_tools.anchor_label_cantonese(key) for key, _label in editor_tools.ANCHORS
    }
    stack = [pane]
    while stack:
        node = stack.pop()
        if (
            isinstance(node, SearchableChoice)
            and len(node.options) == len(editor_tools.ANCHORS)
            and set(node.options) <= names
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
        # Through the pane's own label helper rather than the English table:
        # in a non-English mode the picker's options are not the English names,
        # so setting an English value would match nothing and this script would
        # quietly photograph whatever was already selected.
        picker.set_value(pane._anchor_option_label(anchor), notify=True)
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

    # And the same section for a reader who asked for Cantonese, which is the
    # half a capture taken only in English cannot show.  The tab is rebuilt
    # rather than refreshed: every string in it is resolved when it is built,
    # so a language change that did not rebuild would photograph the old one.
    preferences.update(language_mode="cantonese")
    pane.rebuild()
    pane.Layout()
    wx.Yield()
    picker = _anchor_picker(pane)
    if picker is None:
        print("no anchor picker after the language change", file=sys.stderr)
        return 1
    picker.set_value(pane._anchor_option_label(editor_tools.ANCHOR_CENTRE), notify=True)
    wx.Yield()
    _scroll_to(pane, picker)
    pane.Layout()
    wx.Yield()
    report = capture_composite(pane, OUTPUT / "paste-anchor-cantonese.png")
    report["anchor"] = pane.position_anchor
    report["language_mode"] = preferences.load().language_mode
    report["picker_label"] = picker.label
    report["picker_value"] = picker.value
    report["picker_options"] = list(picker.options)
    report["picker_on_screen"] = bool(picker.IsShownOnScreen())
    report["box_rows"] = {
        pane._tool_rows[key].label: pane._tool_rows[key].value
        for key, _label in pane_module.PASTE_BOX_ROWS
        if key in pane._tool_rows
    }
    reports["cantonese"] = report

    print(json.dumps(reports, indent=2, default=str, ensure_ascii=False))
    frame.Destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
