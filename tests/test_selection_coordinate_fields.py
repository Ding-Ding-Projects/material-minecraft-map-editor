"""The six Coordinates boxes show the real selection, and typing moves it.

``selection/Coordinates`` shipped holding six hard-coded numbers from the design
mock -- ``x1=-2, x2=13, y1=98, y2=99, z1=-49, z2=-32`` -- written into
``ribbon_defs`` and re-seeded into the widgets on every rebuild.  Nothing wrote
them from the world and nothing read them back out: ``grep -rn field_value``
answered with ``ribbon.py`` and nothing else.  So with a world open the ribbon
displayed a selection box that did not exist, and went on displaying it while
the real selection was dragged, added to, and cleared.

That is worse than an inert control.  An inert control disappoints; this one
*asserts* something, and the thing it asserted was false.  A user reading those
numbers to check what they were about to fill, replace, or delete was reading a
picture of somebody's mock-up.

Nothing here reads source.  Every test builds a real
:class:`~amulet_map_editor.api.studio.shell.StudioShell`, opens the real
``Selection`` ribbon tab so the real ``OutlinedField`` widgets are constructed,
and drives them: text goes into the ``wx.TextCtrl`` the user types into and the
commit is delivered through the control's own bound handler.  What is asserted
afterwards is the state of a live
:class:`~amulet_map_editor.programs.edit.api.selection.SelectionManager` -- the
class the running editor owns -- never the string the ribbon stored.

The reverse direction is asserted the same way: the selection is moved through
the editor's own ``selection_corners`` setter, which is what a drag in the
viewport, an undo, and the shell's own Add box command all end up calling, and
then the six boxes are read back off the widgets.
"""

from __future__ import annotations

import os
import tempfile
import time
from typing import Any, Dict, Iterator, Sequence, Tuple

import pytest

wx = pytest.importorskip("wx", reason="wxPython is not installed in this environment")

from amulet_map_editor.api.studio import ribbon_defs  # noqa: E402
from amulet_map_editor.api.studio import shell as shell_module  # noqa: E402
from amulet_map_editor.api.studio.shell import StudioShell  # noqa: E402

#: Off-screen, so a run on a visible desktop never throws a frame at anybody.
OFFSCREEN = (-32000, -32000)

#: The group whose six boxes this module is about, and the tab it lives on.
GROUP = "Coordinates"
TAB = "selection"

#: A box that is nothing like the shipped mock numbers on any axis, so a widget
#: still showing the mock cannot coincidentally agree with it.
BOX = ((100, 40, -300), (140, 52, -260))

#: A second box, used for "the selection changed under the ribbon".
MOVED = ((7, 11, 13), (23, 29, 31))


# ---------------------------------------------------------------------------
# the world the shell is given
# ---------------------------------------------------------------------------


class _History:
    """A world's undo depth, which the shell reads before and after a command."""

    def __init__(self) -> None:
        self.undo_count = 0
        self.redo_count = 0


class _Level:
    """Only the parts of a level these commands actually read."""

    def __init__(self) -> None:
        self.changed = False
        self.history_manager = _History()
        self.sub_chunk_size = 16
        self.level_wrapper = None


class _Canvas(wx.Panel):
    """A stand-in for the 3D editor canvas, holding the editor's real selection.

    The selection is the genuine :class:`SelectionManager` the editor owns, not
    a double.  A test that stubs the seam it is checking passes whether or not
    the seam works, and this module exists because of a defect on exactly that
    boundary.
    """

    def __init__(self, parent: wx.Window) -> None:
        super().__init__(parent)
        from amulet_map_editor.programs.edit.api.selection import SelectionManager

        self.world = _Level()
        self.dimension = "minecraft:overworld"
        self.tools: Dict[str, Any] = {}
        self.selection = SelectionManager(self)


class _Frame(wx.Frame):
    """The frame accessors the shell asks for when it looks for the editor."""

    def __init__(self) -> None:
        super().__init__(None, pos=OFFSCREEN, size=(1400, 900))
        self.canvas = _Canvas(self)
        self.canvas.Hide()

    def active_editor_canvas(self) -> _Canvas:
        return self.canvas

    def active_world_page(self) -> None:
        return None

    def active_editor_program(self) -> None:
        return None


@pytest.fixture(scope="module")
def app() -> Iterator[Any]:
    """A live ``wx.App`` on an isolated profile, so a run touches no settings."""
    os.environ.setdefault("CONFIG_DIR", tempfile.mkdtemp(prefix="amulet-coords-"))
    application = wx.App()
    yield application


@pytest.fixture
def shell(app) -> Iterator[StudioShell]:
    """A real shell showing the Selection tab, with a real editor behind it."""
    frame = _Frame()
    built = StudioShell(frame, frame)
    built.workspace.ribbon.set_tab(TAB)
    wx.SafeYield()
    try:
        yield built
    finally:
        frame.Destroy()
        wx.SafeYield()


# ---------------------------------------------------------------------------
# reaching the widgets the way the shell does
# ---------------------------------------------------------------------------


def _panel(shell: StudioShell) -> Any:
    """Return the built Coordinates group panel, found the way the shell finds it."""
    ribbon = shell.workspace.ribbon
    for group in shell._ribbon_groups(ribbon):
        if getattr(getattr(group, "group", None), "title", "") == GROUP:
            return group
    raise AssertionError(
        "the ribbon built no Coordinates group panel on the Selection tab"
    )


def _boxes(shell: StudioShell) -> Dict[str, Any]:
    """Return the six live ``OutlinedField`` widgets, keyed by their label."""
    fields = dict(getattr(_panel(shell), "fields", {}))
    missing = [
        item.label for item in ribbon_defs.SELECTION_FIELDS if item.label not in fields
    ]
    assert not missing, f"the Coordinates group is missing the boxes {missing}"
    return fields


def _shown(shell: StudioShell) -> Dict[str, str]:
    """Return what the six boxes are showing right now."""
    return {label: field.value() for label, field in _boxes(shell).items()}


def _idle(shell: StudioShell) -> None:
    """Let the shell's own idle pass run, unforced, as the application's does.

    Deliberately **not** ``_refresh_enablement(force=True)``.  Forcing the pass
    walks straight past the change signature that decides whether there is
    anything to do, and that signature is the whole mechanism by which a
    selection dragged in the viewport reaches these six boxes: with the corners
    left out of it, a drag changes nothing the pass can see and the numbers
    never move.  Measured -- the forced version of this helper passed every test
    in this module with that entry deleted.

    The sleep is the pass's own throttle, which exists so a drag does not cost a
    tree walk per frame; waiting it out is what makes the idle event count.
    """
    time.sleep(shell_module._ENABLEMENT_INTERVAL + 0.05)
    shell.GetEventHandler().ProcessEvent(wx.IdleEvent())
    wx.SafeYield()


def _select(shell: StudioShell, *boxes: Any) -> None:
    """Draw ``boxes`` through the editor's own selection, as a viewport drag does.

    Nothing tells the shell.  The corners go through the editor's own
    ``selection_corners`` setter -- which is what the viewport's selection
    behaviour, an undo, and the shell's own Add box all end up calling -- and
    the ribbon has to notice by itself, on idle.
    """
    shell._canvas().selection.selection_corners = tuple(boxes)
    wx.SafeYield()
    _idle(shell)


def _corners(shell: StudioShell) -> Tuple[Any, ...]:
    """Read the selection back from the editor rather than from the shell."""
    return tuple(shell._canvas().selection.selection_corners)


def _type(shell: StudioShell, label: str, text: str) -> None:
    """Type ``text`` into one box and press Enter, through the real control.

    ``SetValue`` raises the same ``wx.EVT_TEXT`` a keystroke does, which is what
    the field's own change handler listens for; the Enter is then delivered to
    the text control's own event handler, so the code that runs is the handler
    the widget really bound rather than a method called directly.  That the
    control can receive Enter at all is asserted separately, in
    :func:`test_the_boxes_accept_enter_as_a_commit`, because a bound handler on
    a control without ``wx.TE_PROCESS_ENTER`` never fires for a real keypress.
    """
    text_ctrl = _boxes(shell)[label].text
    text_ctrl.SetValue(str(text))
    wx.SafeYield()
    event = wx.CommandEvent(wx.EVT_TEXT_ENTER.typeId, text_ctrl.GetId())
    event.SetEventObject(text_ctrl)
    text_ctrl.GetEventHandler().ProcessEvent(event)
    wx.SafeYield()


def _expected(box: Sequence[Sequence[int]]) -> Dict[str, str]:
    """Return what the six boxes must show for ``box``, from the binding table."""
    return {
        item.label: str(box[item.point][item.axis])
        for item in ribbon_defs.SELECTION_FIELDS
    }


def _feedback(shell: StudioShell) -> str:
    """Return the group's inline feedback line."""
    return str(_panel(shell).feedback_text())


# ---------------------------------------------------------------------------
# the definition no longer carries invented numbers
# ---------------------------------------------------------------------------


def test_the_shipped_definition_invents_no_coordinates() -> None:
    """No box may ship a literal value: there is nothing true to put there.

    A value written here is a number about a world the build has never seen, and
    it is displayed before any world is open.  The six real numbers can only
    come from the selection, so the definition supplies none.
    """
    group = next(
        item
        for item in ribbon_defs.tab(TAB).groups  # type: ignore[union-attr]
        if item.title == GROUP
    )
    invented = {entry.label: entry.value for entry in group.fields if entry.value}
    assert not invented, (
        "the Coordinates boxes ship hard-coded numbers, which are shown as "
        f"though they described the open world: {invented}"
    )


def test_the_binding_table_covers_every_corner_exactly_once() -> None:
    """Six boxes, two points, three axes, and no square left unclaimed."""
    pairs = [(item.point, item.axis) for item in ribbon_defs.SELECTION_FIELDS]
    assert sorted(pairs) == [(point, axis) for point in (0, 1) for axis in (0, 1, 2)]
    assert not ribbon_defs.validate()


def test_every_box_raises_a_registered_command() -> None:
    """Each box names a command the shell really implements.

    A box that raises nothing stores what was typed and stops there, which is
    what all six did, and is the same defect the Format dropdown was fixed for
    one control along.
    """
    from amulet_map_editor.api.studio import commands

    group = next(
        item
        for item in ribbon_defs.tab(TAB).groups  # type: ignore[union-attr]
        if item.title == GROUP
    )
    for entry in group.fields:
        assert entry.command == ribbon_defs.SELECTION_COMMAND, entry
        assert commands.command(commands.resolve(entry.command)) is not None


# ---------------------------------------------------------------------------
# reading: the boxes show the selection the world holds
# ---------------------------------------------------------------------------


def test_the_boxes_show_the_selection_the_world_holds(shell: StudioShell) -> None:
    """Draw a box in the editor; the ribbon shows *that* box's corners."""
    _select(shell, BOX)
    assert _shown(shell) == _expected(BOX)


def test_the_boxes_follow_a_selection_changed_in_the_viewport(
    shell: StudioShell,
) -> None:
    """Move the selection the way a drag does; the boxes move with it.

    The shell is told nothing.  The new corners go through the editor's own
    ``selection_corners`` setter -- which is what the viewport's selection
    behaviour calls -- and the ribbon has to notice by itself.
    """
    _select(shell, BOX)
    assert _shown(shell) == _expected(BOX)
    _select(shell, MOVED)
    assert _shown(shell) == _expected(MOVED)


def test_the_boxes_show_the_active_box_when_several_exist(
    shell: StudioShell,
) -> None:
    """With three boxes drawn, the six numbers describe the active one.

    The active box is the last, which is the box every other Selection command
    in this shell acts on: Remove drops it and Duplicate copies it.  Six boxes
    that described a different box from the one the buttons beside them act on
    would be a second, quieter lie.
    """
    _select(shell, BOX, MOVED, ((1, 2, 3), (4, 5, 6)))
    assert _shown(shell) == _expected(((1, 2, 3), (4, 5, 6)))
    assert "3" in _feedback(shell), (
        "with three boxes drawn the group says nothing about which one it is "
        f"showing: {_feedback(shell)!r}"
    )


def test_an_empty_selection_leaves_the_boxes_blank_and_says_why(
    shell: StudioShell,
) -> None:
    """With nothing selected the boxes are empty, disabled, and explain it.

    This is the defect at its purest.  Before the wiring, closing the selection
    left six plausible numbers sitting there describing a box that did not
    exist, and there was no way for a reader to tell that from a box that did.
    """
    _select(shell, BOX)
    _select(shell)
    assert set(_shown(shell).values()) == {""}
    for label, field in _boxes(shell).items():
        assert not field.IsEnabled(), f"{label} is editable with nothing selected"
        # The text control specifically, not just the panel around it: what
        # stops a user typing into a box that describes nothing is the control
        # under the caret being disabled, not its container.
        assert not field.text.IsEnabled(), f"{label} still takes typing"
        assert "Add box" in field.GetToolTipText(), (
            f"the disabled {label} box does not name what is missing; its "
            f"tooltip reads {field.GetToolTipText()!r}"
        )
    message = _feedback(shell)
    assert message, "nothing tells the reader why the boxes are empty"
    assert "Add box" in message, (
        "the empty state does not say what to do next; it reads " f"{message!r}"
    )


def test_no_world_at_all_says_so_rather_than_naming_a_dead_button(
    shell: StudioShell,
) -> None:
    """With no world open the boxes do not send the reader to press Add box.

    Add box is greyed out too when nothing is open, so the empty-selection
    sentence would be advice that cannot be followed -- the reader presses a
    dead control and learns nothing about why.
    """
    _select(shell, BOX)
    shell.frame.active_editor_canvas = lambda: None
    try:
        _idle(shell)
        assert set(_shown(shell).values()) == {""}
        message = _feedback(shell)
        assert "No world is open" in message, message
        assert "Add box" not in message, message
    finally:
        shell.frame.active_editor_canvas = lambda: shell.frame.canvas


# ---------------------------------------------------------------------------
# writing: typing into a box moves the real selection
# ---------------------------------------------------------------------------


def test_typing_a_new_x1_moves_the_real_selection(shell: StudioShell) -> None:
    """Type 999 into x1 and the editor's own selection is at 999 afterwards."""
    _select(shell, BOX)
    _type(shell, "x1", "999")
    corners = _corners(shell)
    assert len(corners) == 1
    low, high = corners[0]
    assert (low[0], high[0]) == (140, 999), (
        "the selection did not move to the typed X: the editor holds " f"{corners[0]!r}"
    )
    # And every other axis is exactly where it was: one box edited, not six.
    assert (low[1], low[2]) == (40, -300)
    assert (high[1], high[2]) == (52, -260)


def test_typing_moves_only_the_active_box(shell: StudioShell) -> None:
    """The other boxes in the selection are left exactly as they were."""
    _select(shell, BOX, MOVED)
    _type(shell, "y2", "77")
    corners = _corners(shell)
    assert corners[0] == BOX, f"an untouched box moved: {corners[0]!r}"
    assert 77 in (corners[1][0][1], corners[1][1][1])


def test_leaving_a_box_commits_what_was_typed(shell: StudioShell) -> None:
    """Tabbing away commits too, so a value typed and abandoned is not lost."""
    _select(shell, BOX)
    field = _boxes(shell)["z1"]
    field.text.SetValue("-500")
    wx.SafeYield()
    event = wx.FocusEvent(wx.EVT_KILL_FOCUS.typeId, field.text.GetId())
    event.SetEventObject(field.text)
    field.text.GetEventHandler().ProcessEvent(event)
    wx.SafeYield()
    low, high = _corners(shell)[0]
    assert -500 in (low[2], high[2]), (
        "leaving the box threw the typed value away: the editor holds "
        f"{(low, high)!r}"
    )


def test_the_boxes_accept_enter_as_a_commit(shell: StudioShell) -> None:
    """The control really can receive Enter, rather than merely being bound to it.

    ``wx.TE_PROCESS_ENTER`` is what makes a text control raise
    ``wx.EVT_TEXT_ENTER`` instead of handing the key to the surrounding dialog.
    Without it every commit test above still passes -- the event is delivered by
    hand -- while a real user pressing Enter changes nothing at all.
    """
    for label, field in _boxes(shell).items():
        assert field.text.GetWindowStyleFlag() & wx.TE_PROCESS_ENTER, (
            f"the {label} box cannot receive Enter, so pressing it in the "
            "running application commits nothing"
        )


def test_a_committed_edit_is_shown_back_the_way_the_world_stored_it(
    shell: StudioShell,
) -> None:
    """Corners typed in the wrong order come back in the order they were kept.

    The editor keeps a box as two corner points and normalises them, so typing
    an x1 beyond x2 is not refused -- it is applied and then shown back
    normalised.  The round trip is what makes that visible rather than silent.
    """
    _select(shell, BOX)
    _type(shell, "x1", "200")
    assert _shown(shell) == _expected(_corners(shell)[0])


# ---------------------------------------------------------------------------
# invalid input is refused in plain words, and changes nothing
# ---------------------------------------------------------------------------


def _refused(shell: StudioShell, label: str, text: str) -> str:
    """Type something unusable, and return the message the group showed."""
    before = _corners(shell)
    _type(shell, label, text)
    assert _corners(shell) == before, (
        f"typing {text!r} into {label} changed the selection to " f"{_corners(shell)!r}"
    )
    message = _feedback(shell)
    assert message, f"typing {text!r} into {label} was refused without saying so"
    return message


def test_letters_are_refused_and_named(shell: StudioShell) -> None:
    _select(shell, BOX)
    message = _refused(shell, "x1", "abc")
    assert "x1" in message
    assert "whole number" in message


def test_a_blank_box_is_refused_and_named(shell: StudioShell) -> None:
    _select(shell, BOX)
    message = _refused(shell, "y2", "")
    assert "y2" in message


def test_a_zero_thickness_box_is_refused(shell: StudioShell) -> None:
    """x1 == x2 selects nothing at all, so it is refused rather than applied."""
    _select(shell, BOX)
    message = _refused(shell, "x1", "140")
    assert "x1" in message and "x2" in message
    assert "empty" in message


def test_a_value_beyond_the_world_is_refused(shell: StudioShell) -> None:
    _select(shell, BOX)
    message = _refused(shell, "z2", "999999999")
    assert "z2" in message
    assert str(ribbon_defs.SELECTION_LIMIT) in message.replace(",", "")


def test_a_refusal_keeps_the_text_the_user_typed(shell: StudioShell) -> None:
    """A refused value stays on screen to be corrected, not silently reverted."""
    _select(shell, BOX)
    _type(shell, "x1", "abc")
    _idle(shell)
    assert _shown(shell)["x1"] == "abc"


def test_a_refusal_clears_once_the_world_moves(shell: StudioShell) -> None:
    """A stale complaint about text nobody can see any more is itself a lie."""
    _select(shell, BOX)
    _type(shell, "x1", "abc")
    assert _feedback(shell)
    _select(shell, MOVED)
    assert _shown(shell) == _expected(MOVED)
    assert not _feedback(shell)


# ---------------------------------------------------------------------------
# the pure parser, which the shell and the tests above both go through
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "values, expected",
    [
        ({"x1": "1", "x2": "2", "y1": "3", "y2": "4", "z1": "5", "z2": "6"}, True),
        ({"x1": "1", "x2": "1", "y1": "3", "y2": "4", "z1": "5", "z2": "6"}, False),
        ({"x1": "", "x2": "2", "y1": "3", "y2": "4", "z1": "5", "z2": "6"}, False),
        ({"x1": "1.5", "x2": "2", "y1": "3", "y2": "4", "z1": "5", "z2": "6"}, False),
        ({"x1": "1", "x2": "2", "y1": "3", "y2": "4", "z1": "5"}, False),
    ],
)
def test_the_parser_accepts_only_a_usable_box(
    values: Dict[str, str], expected: bool
) -> None:
    box, problem = ribbon_defs.parse_selection_box(values)
    assert (box is not None) is expected
    assert bool(problem) is not expected


def test_the_parser_orders_each_axis() -> None:
    """A reversed pair is ordered rather than refused; the editor allows it."""
    box, problem = ribbon_defs.parse_selection_box(
        {"x1": "9", "x2": "1", "y1": "3", "y2": "4", "z1": "5", "z2": "6"}
    )
    assert not problem
    assert box == ((1, 3, 5), (9, 4, 6))
