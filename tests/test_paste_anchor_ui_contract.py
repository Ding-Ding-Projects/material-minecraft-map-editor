"""The Position section says which point it names, and where the blocks land.

A paste puts the *centre* of the copy at the position it is given, so somebody
who types the coordinate they want gets blocks half a structure away.  The
arithmetic behind that is checked in ``tests/test_paste_anchor.py`` and the
whole route, from a typed corner to blocks in a real world, in
``tests/test_editor_clone_runtime.py``.  This module checks the part in
between: that the pane actually draws the disclosure, the anchor picker and the
live box, that they are reachable, and that operating them does what they say.

**Why the pane is driven with a stand-in tool.**  A properties pane with no
world open has no pending object to describe, and opening a world here would
make this module as slow as the runtime one.  So the editor bridge is replaced
with a small fake that holds a position the way the real paste tool does.  That
buys the checks below and nothing about the wiring -- a fake answers whatever
it is told to -- which is exactly why the runtime module drives the real thing
as well, and why the two are cross-referenced from each other's docstrings.
"""

from __future__ import annotations

from typing import Any, Dict, Iterator, List, Optional, Tuple

import pytest

wx = pytest.importorskip("wx", reason="wxPython is not installed in this environment")

from amulet_map_editor.api.studio import editor_tools  # noqa: E402
from amulet_map_editor.api.studio import properties_pane as pane_module  # noqa: E402
from amulet_map_editor.api.studio.widgets import (  # noqa: E402
    SearchableChoice,
    StudioText,
)

#: The stand-in copy: four blocks square and one high, which is the shape the
#: runtime module clones so the two modules describe the same object.
EXTENT: Tuple[int, int, int] = (4, 1, 4)

#: Where the fake tool starts.  With that extent the paste fills
#: ``(6, 40, 6)..(9, 40, 9)`` -- the box a real world was observed producing.
LOCATION: Tuple[int, int, int] = (8, 40, 8)

BOX_MINIMUM: Tuple[int, int, int] = (6, 40, 6)
BOX_MAXIMUM: Tuple[int, int, int] = (9, 40, 9)

#: Minimum height for something the user has to hit, in device pixels at the
#: default scale.  Well below the platform's own guidance, so this catches a
#: control that collapsed rather than one that is merely compact.
MIN_TARGET_HEIGHT = 24


class FakeTool:
    """A pending object that answers like the paste tool holding one."""

    def __init__(self) -> None:
        self.location: Tuple[int, int, int] = LOCATION
        self.writes: List[Tuple[int, int, int]] = []

    def pending(self) -> editor_tools.PendingObject:
        return editor_tools.PendingObject(
            location=self.location,
            rotation=(0.0, 0.0, 0.0),
            scale=(1.0, 1.0, 1.0),
            following=False,
            drawn=True,
            size=" by ".join(str(value) for value in EXTENT),
            extent=EXTENT,
        )

    def set_location(self, location, *args: Any, **kwargs: Any) -> bool:
        self.location = tuple(int(round(float(value))) for value in location)
        self.writes.append(self.location)
        return True


@pytest.fixture(scope="module")
def app() -> Iterator[Any]:
    existing = wx.App.Get()
    created = None
    if existing is None:
        try:
            created = wx.App(False)
        except Exception as error:  # pragma: no cover - depends on the host
            pytest.skip(f"wx.App could not start on this host: {error!r}")
    yield existing or created
    if created is not None:
        created.Destroy()


@pytest.fixture()
def tool(monkeypatch: pytest.MonkeyPatch, tmp_path) -> FakeTool:
    """Point the pane at a stand-in tool and a throwaway profile."""
    # The anchor is persisted like any other setting, and this module changes
    # it, so the profile has to be one nobody is using.
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "profile"))
    fake = FakeTool()
    monkeypatch.setattr(editor_tools, "pending_object", lambda *a, **k: fake.pending())
    monkeypatch.setattr(editor_tools, "set_pending_location", fake.set_location)
    monkeypatch.setattr(editor_tools, "active_tool_name", lambda *a, **k: "Paste")
    monkeypatch.setattr(editor_tools, "camera_location", lambda *a, **k: None)
    monkeypatch.setattr(editor_tools, "movement_sentence", lambda *a, **k: "")
    return fake


@pytest.fixture()
def pane(app, tool: FakeTool) -> Iterator[Any]:
    """A properties pane showing a Clone activation, on a real frame."""
    # As tall as the real workspace gives the column, so the scrolling below is
    # the scrolling a user would actually have to do rather than an artefact of
    # a test window nobody sized.
    window = wx.Frame(None, size=(360, 700), pos=(-32000, -32000))
    built = pane_module.PropertiesPane(window, title="Test world")
    sizer = wx.BoxSizer(wx.VERTICAL)
    sizer.Add(built, 1, wx.EXPAND)
    window.SetSizer(sizer)
    window.Show()
    window.Layout()
    wx.Yield()
    built.show_tool_activation(
        editor_tools.Activation(
            key="cloneTool",
            label="Clone",
            ok=True,
            tool="Paste",
            kind="pending",
            message="The selection was copied and the paste tool is holding it.",
        )
    )
    built.Layout()
    wx.Yield()
    try:
        yield built
    finally:
        window.Destroy()
        wx.Yield()


# ----------------------------------------------------------------------
# finding what the pane built
# ----------------------------------------------------------------------


def _descendants(window: Any) -> Iterator[Any]:
    stack = [window]
    while stack:
        node = stack.pop()
        yield node
        try:
            stack.extend(node.GetChildren())
        except Exception:  # noqa: BLE001 - a control mid-teardown
            continue


def _anchor_choice(pane: Any) -> Optional[SearchableChoice]:
    for node in _descendants(pane):
        if isinstance(node, SearchableChoice) and node.label.startswith(
            pane_module.ANCHOR_FIELD_LABEL
        ):
            return node
    return None


def _note_saying(pane: Any, needle: str) -> Optional[StudioText]:
    """Return the paragraph carrying ``needle``, ignoring its line breaks."""
    wanted = " ".join(str(needle).split())
    for node in _descendants(pane):
        if not isinstance(node, StudioText):
            continue
        try:
            text = " ".join(str(node.GetLabel()).split())
        except Exception:  # noqa: BLE001
            continue
        if wanted and wanted in text:
            return node
    return None


def _rows(pane: Any) -> Dict[str, Any]:
    """Return the pane's live rows by the key it registered them under."""
    return dict(pane._tool_rows)


def _scroll_into_view(pane: Any, window: Any) -> None:
    """Scroll the pane's column until ``window``'s top is at the top of it.

    ``wx.ScrolledWindow`` has no ``ScrollChildIntoView`` -- that belongs to
    ``wx.lib.scrolledpanel`` -- so the offset is worked out from the control's
    own screen position and the scroller's rate, which is the same arithmetic
    the panel version does.  Deliberately only the top is aligned: a control
    taller than the visible column still fails the containment check below,
    which is the honest answer for something that cannot be read at once.
    """
    scroller = pane.scroller
    top = scroller.ScreenToClient(window.GetScreenPosition()).y
    virtual = scroller.CalcUnscrolledPosition(0, top)[1]
    unit = scroller.GetScrollPixelsPerUnit()[1] or 1
    scroller.Scroll(-1, max(0, virtual // unit))
    wx.Yield()


def _inside_the_band(pane: Any, window: Any) -> bool:
    """Whether ``window`` lies inside the scroller's visible rectangle.

    Screen coordinates, because a scrolled child's screen position already
    carries the scroll offset -- so containment is exactly the question "can
    this be read right now", which is what the widget tree cannot answer.
    """
    band = pane.scroller.GetScreenRect()
    rect = window.GetScreenRect()
    return bool(
        rect.GetTop() >= band.GetTop()
        and rect.GetBottom() <= band.GetBottom()
        and rect.GetHeight() > 0
    )


# ----------------------------------------------------------------------
# the disclosure exists and can be read
# ----------------------------------------------------------------------


def test_the_pane_really_drew_the_pending_controls(pane) -> None:
    """The fixture produced a Position section at all.

    Every assertion below looks for one control inside that section, and a
    section that was never built would make each of them fail for the wrong
    reason -- or, for the ones shaped "if it is there it is correct", pass
    while showing nothing.
    """
    assert pane.tab == pane_module.TOOL_TAB[0], "the Tool tab did not open"
    rows = _rows(pane)
    for key, _label in pane_module.PASTE_BOX_ROWS:
        assert key in rows, f"the pane built no {key!r} row: {sorted(rows)}"
    assert "location" in pane._tool_fields, "the pane built no position boxes"


def test_the_position_boxes_say_which_point_they_name(pane) -> None:
    """The sentence that was missing, in the section where it was missing."""
    note = _note_saying(pane, "centre of the copy, not a corner")
    assert note is not None, (
        "the Position section does not say that x, y and z are the centre of "
        "the copy. Without it a typed coordinate lands half a structure away "
        "and nothing on screen says why."
    )
    _scroll_into_view(pane, note)
    assert note.IsShownOnScreen(), "the disclosure is not shown on screen"
    assert _inside_the_band(pane, note), (
        "the disclosure cannot be brought into the pane's visible column. It "
        f"occupies {note.GetScreenRect()} and the column is "
        f"{pane.scroller.GetScreenRect()}"
    )


def test_the_pane_shows_the_box_the_blocks_will_fill(pane) -> None:
    """The readout is the answer to "then where do they actually go"."""
    rows = _rows(pane)
    assert rows[pane_module.PASTE_BOX_ROWS[0][0]].value == "6, 40, 6"
    assert rows[pane_module.PASTE_BOX_ROWS[1][0]].value == "9, 40, 9"
    for key, _label in pane_module.PASTE_BOX_ROWS:
        row = rows[key]
        _scroll_into_view(pane, row)
        assert row.IsShownOnScreen(), f"the {key!r} row is not shown on screen"
        assert _inside_the_band(pane, row), (
            f"the {key!r} row cannot be brought into the visible column: "
            f"{row.GetScreenRect()} against {pane.scroller.GetScreenRect()}"
        )


def test_the_box_readout_follows_the_position_as_it_is_typed(pane, tool) -> None:
    """Live, so the box answers the number being typed rather than the last one."""
    field = pane._tool_fields["location"]
    field.set_values(["100", "64", "-20"], notify=True)
    wx.Yield()
    rows = _rows(pane)
    assert rows[pane_module.PASTE_BOX_ROWS[0][0]].value == "98, 64, -22"
    assert rows[pane_module.PASTE_BOX_ROWS[1][0]].value == "101, 64, -19"


# ----------------------------------------------------------------------
# the anchor picker is a real control that really moves the copy
# ----------------------------------------------------------------------


def test_the_anchor_picker_is_a_control_and_not_a_caption(pane) -> None:
    """Accessible name, keyboard reachable, focusable, big enough to hit."""
    choice = _anchor_choice(pane)
    assert choice is not None, (
        "the Position section offers no way to choose which point x, y and z "
        "name, so the only anchor is the one the engine happens to use"
    )
    _scroll_into_view(pane, choice)
    assert choice.IsShownOnScreen(), "the anchor picker is not shown on screen"
    assert _inside_the_band(pane, choice), (
        "the anchor picker cannot be brought into the visible column: "
        f"{choice.GetScreenRect()} against {pane.scroller.GetScreenRect()}"
    )
    assert choice.AcceptsFocus() and choice.AcceptsFocusFromKeyboard(), (
        "the anchor picker cannot be reached from the keyboard, so it is a "
        "mouse-only control in a pane that is otherwise keyboard operable"
    )
    name = choice.GetName()
    assert pane_module.ANCHOR_FIELD_LABEL in name and "Centre of the copy" in name, (
        "the anchor picker's accessible name should carry what it is and what "
        f"it currently holds, and is {name!r}"
    )
    assert choice.GetSize().GetHeight() >= MIN_TARGET_HEIGHT, (
        f"the anchor picker is {choice.GetSize().GetHeight()}px tall, which is "
        "not a target anybody can hit"
    )


def test_choosing_a_corner_rewrites_the_boxes_without_moving_the_copy(
    pane, tool
) -> None:
    """Naming a different point renames it; it does not shift the object.

    This is the half that is easy to get wrong in the other direction: writing
    the anchored value straight back through the tool would move the copy by
    half its own size every time the anchor changed.
    """
    choice = _anchor_choice(pane)
    assert choice is not None
    before = tool.location
    choice.set_value(
        editor_tools.anchor_label(editor_tools.ANCHOR_MINIMUM), notify=True
    )
    wx.Yield()

    assert tool.location == before, (
        "choosing an anchor moved the pending object from "
        f"{before} to {tool.location}; it should only change which point is named"
    )
    assert list(pane._tool_fields["location"].values()) == ["6", "40", "6"], (
        "with the lowest corner chosen the boxes should read the box's own "
        f"minimum, and read {pane._tool_fields['location'].values()}"
    )
    rows = _rows(pane)
    assert rows[pane_module.PASTE_BOX_ROWS[0][0]].value == "6, 40, 6"
    assert rows[pane_module.PASTE_BOX_ROWS[1][0]].value == "9, 40, 9"
    assert _note_saying(pane, "lowest corner") is not None, (
        "the disclosure still describes the centre after a corner was chosen, "
        "so the sentence and the boxes now disagree"
    )


def test_typing_a_corner_moves_the_copy_so_that_corner_lands_there(pane, tool) -> None:
    """The promise the control makes, checked against what it wrote.

    With the lowest corner chosen, typing ``11, 50, 11`` must leave the paste
    filling a box that starts at ``11, 50, 11`` -- which means writing ``13,
    50, 13`` to the tool, because the tool's own position is the centre.
    """
    choice = _anchor_choice(pane)
    assert choice is not None
    choice.set_value(
        editor_tools.anchor_label(editor_tools.ANCHOR_MINIMUM), notify=True
    )
    wx.Yield()

    pane._tool_fields["location"].set_values(["11", "50", "11"], notify=True)
    wx.Yield()

    assert tool.location == (13, 50, 13), (
        "the pane should have converted the typed corner into the centre the "
        f"tool holds, and wrote {tool.location}"
    )
    assert editor_tools.paste_box(tool.location, EXTENT) == ((11, 50, 11), (14, 50, 14))
    rows = _rows(pane)
    assert rows[pane_module.PASTE_BOX_ROWS[0][0]].value == "11, 50, 11"

    # And again with the far corner, whose offset from the box's own minimum is
    # not zero.  Without this the whole conversion can drop the anchor offset
    # and still pass: for the lowest corner that offset *is* zero, so the one
    # anchor easiest to reach for is the one anchor that proves least.
    choice.set_value(
        editor_tools.anchor_label(editor_tools.ANCHOR_MAXIMUM), notify=True
    )
    wx.Yield()
    pane._tool_fields["location"].set_values(["14", "50", "14"], notify=True)
    wx.Yield()
    assert tool.location == (13, 50, 13), (
        "typing the highest corner should reach the same centre by a different "
        f"offset, and wrote {tool.location}"
    )
    assert _rows(pane)[pane_module.PASTE_BOX_ROWS[1][0]].value == "14, 50, 14"


def test_the_camera_button_means_the_same_point_the_boxes_do(
    app, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """ "Bring it to the camera" must agree with the sentence above it.

    It is the same act as typing the camera position into the boxes, so under a
    corner anchor it puts that corner at the camera rather than the centre.  A
    button that filled the boxes and then meant a different point would
    contradict the disclosure sitting directly above it.
    """
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "profile"))
    fake = FakeTool()
    monkeypatch.setattr(editor_tools, "pending_object", lambda *a, **k: fake.pending())
    monkeypatch.setattr(editor_tools, "set_pending_location", fake.set_location)
    monkeypatch.setattr(editor_tools, "active_tool_name", lambda *a, **k: "Paste")
    monkeypatch.setattr(editor_tools, "movement_sentence", lambda *a, **k: "")
    monkeypatch.setattr(editor_tools, "camera_location", lambda *a, **k: (40, 70, 40))

    window = wx.Frame(None, size=(360, 700), pos=(-32000, -32000))
    try:
        built = pane_module.PropertiesPane(window, title="Test world")
        window.Show()
        wx.Yield()
        built.show_tool_activation(
            editor_tools.Activation(
                key="cloneTool", label="Clone", ok=True, tool="Paste", kind="pending"
            )
        )
        wx.Yield()
        choice = _anchor_choice(built)
        assert choice is not None
        choice.set_value(
            editor_tools.anchor_label(editor_tools.ANCHOR_MINIMUM), notify=True
        )
        wx.Yield()

        built._pending_to_camera()
        wx.Yield()
        assert editor_tools.paste_box(fake.location, EXTENT) == (
            (40, 70, 40),
            (43, 70, 43),
        ), (
            "with the lowest corner chosen, bringing the copy to the camera "
            f"should start it at the camera; the tool is at {fake.location}"
        )
        assert list(built._tool_fields["location"].values()) == ["40", "70", "40"], (
            "the boxes should read the camera position after the button, and "
            f"read {built._tool_fields['location'].values()}"
        )
    finally:
        window.Destroy()
        wx.Yield()


def test_the_centre_anchor_writes_the_position_through_unchanged(pane, tool) -> None:
    """The default must behave exactly as it did before this section existed.

    Somebody who has learned the centre behaviour and does their own arithmetic
    must not find their numbers quietly reinterpreted.
    """
    assert pane.position_anchor == editor_tools.ANCHOR_CENTRE
    pane._tool_fields["location"].set_values(["1", "2", "3"], notify=True)
    wx.Yield()
    assert tool.location == (1, 2, 3), (
        "with the centre chosen the typed value is the tool's own position, "
        f"and the pane wrote {tool.location}"
    )


def test_the_chosen_anchor_survives_a_restart(pane, tool) -> None:
    """It is persisted like any other setting, and read back on the next pane."""
    choice = _anchor_choice(pane)
    assert choice is not None
    choice.set_value(editor_tools.anchor_label(editor_tools.ANCHOR_BASE), notify=True)
    wx.Yield()
    assert pane_module.load_paste_anchor() == editor_tools.ANCHOR_BASE, (
        "the chosen anchor did not reach the profile, so it would be forgotten "
        "the next time the application starts"
    )

    window = wx.Frame(None, size=(360, 700), pos=(-32000, -32000))
    try:
        fresh = pane_module.PropertiesPane(window, title="Test world")
        assert fresh.position_anchor == editor_tools.ANCHOR_BASE, (
            "a newly built pane went back to the centre, so the stored anchor "
            "is written and never read"
        )
    finally:
        window.Destroy()
        wx.Yield()


def test_an_unreadable_size_says_so_and_offers_no_anchor(
    app, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """No extent means no box and no picker, rather than a confident zero.

    An anchor other than the centre cannot be honoured without the extent, so
    offering one would be a control that does not do what its options say --
    and a box readout showing the position three times would be exactly the
    wrong answer stated confidently, which is what this surface exists to stop.
    """
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "profile"))
    monkeypatch.setattr(
        editor_tools,
        "pending_object",
        lambda *a, **k: editor_tools.PendingObject(
            location=LOCATION, drawn=True, extent=(0, 0, 0)
        ),
    )
    monkeypatch.setattr(editor_tools, "set_pending_location", lambda *a, **k: True)
    monkeypatch.setattr(editor_tools, "active_tool_name", lambda *a, **k: "Paste")
    monkeypatch.setattr(editor_tools, "camera_location", lambda *a, **k: None)
    monkeypatch.setattr(editor_tools, "movement_sentence", lambda *a, **k: "")

    window = wx.Frame(None, size=(360, 700), pos=(-32000, -32000))
    try:
        built = pane_module.PropertiesPane(window, title="Test world")
        window.Show()
        wx.Yield()
        built.show_tool_activation(
            editor_tools.Activation(
                key="cloneTool", label="Clone", ok=True, tool="Paste", kind="pending"
            )
        )
        wx.Yield()
        assert _anchor_choice(built) is None, (
            "an anchor picker is offered for a copy whose size could not be "
            "read, so choosing a corner would silently do nothing"
        )
        assert _note_saying(built, "size could not be read") is not None, (
            "the pane does not say that the size is unknown, so the position "
            "boxes look like they mean whatever the last anchor said"
        )
        rows = _rows(built)
        for key, _label in pane_module.PASTE_BOX_ROWS:
            assert rows[key].value == "not known", (
                f"the {key!r} row claims a box for an object whose size is "
                f"unknown: {rows[key].value!r}"
            )
    finally:
        window.Destroy()
        wx.Yield()


def test_a_row_that_grew_is_measured_again(app) -> None:
    """A live row holding a coordinate must not elide when the value gets longer.

    The rows this section adds hold coordinates, and a coordinate at the far
    edge of a world is several times longer than one near the origin.  Before
    this, a live row kept the minimum width its *first* value asked for and
    quietly elided anything longer -- survivable while every live row said
    "yes" or "no", and not survivable for the row a reader goes to precisely to
    check a number.
    """
    window = wx.Frame(None, size=(360, 200), pos=(-32000, -32000))
    try:
        row = pane_module.PropertyRow(window, "Fills from", "6, 40, 6")
        narrow = row.GetMinSize().GetWidth()
        assert row.set_value("-29999999, -64, -29999999") is True
        assert row.set_value("-29999999, -64, -29999999") is False, (
            "setting the same value again reported a change, so the column "
            "would be laid out on every tick of the live timer"
        )
        assert row.GetMinSize().GetWidth() > narrow, (
            "a much longer value left the row asking for the same width, so it "
            f"will be elided: {narrow}px before and "
            f"{row.GetMinSize().GetWidth()}px after"
        )
    finally:
        window.Destroy()
        wx.Yield()
