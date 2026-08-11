"""Everything a grab handle does, a keyboard can do too.

A handle translates the selection box by whole blocks on any of the three axes.
That is the entire contract, and it has to be reachable without a pointer -- a
feature that is only operable by dragging is a feature some people cannot use
at all.

Two routes are asserted here, and one of them had to be built.

**The nudge button.**  ``SelectionMoveButton`` already moved the whole box with
the movement keys, but only while the box-click action was *held* -- and that
action's default binding is the left mouse button.  So the "hold this and press
W" route needed a mouse to start, which made it no keyboard route at all.  It
now also listens while it has keyboard focus: tab to it, press the movement
keys.  The first test below fails against the old gate.

**The coordinate boxes.**  The select tool's six spin controls write through
``active_block_positions``, and moving both points by the same amount is the
same translation a handle performs.  That path is asserted directly, on all
three axes, because it is the fallback when a user would rather type.

What is *not* claimed: the six boxes are six edits where a handle is one drag.
They are equivalent in what they can express, not in how many keystrokes it
takes -- which is why the focus route above matters.
"""

from __future__ import annotations

import numpy
import pytest

wx = pytest.importorskip("wx")

from amulet.api.selection import SelectionBox, SelectionGroup  # noqa: E402

from amulet_map_editor.api.opengl.camera import Projection  # noqa: E402
from amulet_map_editor.programs.edit.api.behaviour.block_selection_behaviour import (  # noqa: E402
    BlockSelectionBehaviour,
)
from amulet_map_editor.programs.edit.api.key_config import (  # noqa: E402
    ACT_MOVE_BACKWARDS,
    ACT_MOVE_DOWN,
    ACT_MOVE_FORWARDS,
    ACT_MOVE_LEFT,
    ACT_MOVE_RIGHT,
    ACT_MOVE_UP,
    DefaultKeys,
)
from amulet_map_editor.programs.edit.api.ui.nudge_button import (
    NudgeButton,
)  # noqa: E402
from amulet_map_editor.api.wx.util.button_input import InputHeldEvent  # noqa: E402

from tests.test_selection_box_handle_wiring import StubCanvas  # noqa: E402


@pytest.fixture(scope="module")
def app():
    application = wx.App()
    yield application


class RecordingCamera:
    """A camera whose rotation the button reads. Real enough to be weakref'd."""

    rotation = (0.0, 0.0)


class RecordingNudge(NudgeButton):
    def __init__(self, parent, camera):
        super().__init__(parent, camera, DefaultKeys, "nudge", "tooltip")
        # The button holds the camera weakly, so the test has to hold it
        # strongly or it is collected and every nudge raises instead of moving.
        self.held_camera = camera
        self.moves = []

    def _move(self, offset):
        self.moves.append(tuple(offset))


@pytest.fixture
def button(app):
    frame = wx.Frame(None, title="nudge", size=(200, 120))
    control = RecordingNudge(frame, RecordingCamera())
    yield control
    frame.Destroy()


def hold(control, *actions) -> None:
    """Deliver a held-keys event the way ButtonInput's timer delivers it."""
    control.GetEventHandler().ProcessEvent(InputHeldEvent(set(actions)))


def focus(control, gained: bool) -> None:
    """Give or take keyboard focus, as an event, so the binding is under test.

    ``SetFocus`` on a frame that was never shown does not reliably move focus,
    and a test that silently did nothing would pass for the wrong reason.
    """
    event = wx.FocusEvent(wx.wxEVT_SET_FOCUS if gained else wx.wxEVT_KILL_FOCUS)
    control.GetEventHandler().ProcessEvent(event)


def test_a_nudge_button_ignores_the_movement_keys_when_it_is_not_involved(
    button,
) -> None:
    """The precondition. Without it, "it moved when focused" proves nothing."""
    hold(button, ACT_MOVE_LEFT)
    assert button.moves == []
    assert button.listening is False


def test_keyboard_focus_alone_makes_the_movement_keys_nudge(button) -> None:
    """The route that did not exist: tab to the button, press the keys.

    Before this, listening required the box-click action to be held, and that
    action is bound to the left mouse button -- so the whole nudge facility was
    pointer-only.
    """
    focus(button, True)
    assert button.listening is True

    hold(button, ACT_MOVE_LEFT)
    assert button.moves, "focus did not enable the movement keys"


def test_the_keyboard_reaches_all_three_axes_in_both_directions(button) -> None:
    """Six keys, six directions, three axes -- the whole of what a handle does.

    A handle can translate the box along x, y or z.  If any one of those had no
    key, the keyboard route would be a partial substitute, and this is where
    that would show.
    """
    focus(button, True)
    for action in (
        ACT_MOVE_LEFT,
        ACT_MOVE_RIGHT,
        ACT_MOVE_UP,
        ACT_MOVE_DOWN,
        ACT_MOVE_FORWARDS,
        ACT_MOVE_BACKWARDS,
    ):
        button._timeout = 10  # the repeat gate, reset as a fresh press would
        hold(button, action)

    axes_moved = {axis for move in button.moves for axis in range(3) if move[axis]}
    assert axes_moved == {0, 1, 2}, f"only axes {sorted(axes_moved)} are reachable"

    directions = {tuple(numpy.sign(move)) for move in button.moves}
    for axis in range(3):
        signs = {move[axis] for move in button.moves}
        assert 1 in signs and -1 in signs, f"axis {axis} only moves one way"
    assert len(directions) == 6


def test_losing_focus_stops_the_button_listening(button) -> None:
    """Otherwise every WASD press anywhere in the panel would move the box."""
    focus(button, True)
    focus(button, False)
    assert button.listening is False
    hold(button, ACT_MOVE_LEFT)
    assert button.moves == []


def test_typing_coordinates_moves_the_box_on_every_axis(app) -> None:
    """The select tool's six coordinate boxes reach the same result as a drag.

    They write through ``active_block_positions``, which is asserted here
    directly: move both points by the same amount and the box translates,
    unchanged in size, on whichever axis was asked for.
    """
    canvas = StubCanvas()
    try:
        behaviour = BlockSelectionBehaviour(canvas)
        behaviour.bind_events()
        behaviour.selection_group = SelectionGroup(SelectionBox((0, 0, 0), (12, 8, 10)))

        for axis, delta in ((0, 5), (1, -3), (2, 7)):
            point1, point2 = behaviour.active_block_positions
            moved1 = list(point1)
            moved2 = list(point2)
            moved1[axis] += delta
            moved2[axis] += delta
            behaviour.active_block_positions = (tuple(moved1), tuple(moved2))

            now1, now2 = behaviour.active_block_positions
            assert now1 == tuple(moved1), f"axis {axis} did not take the new minimum"
            assert now2 == tuple(moved2), f"axis {axis} did not take the new maximum"
            size_before = tuple(b - a for a, b in zip(point1, point2))
            size_after = tuple(b - a for a, b in zip(now1, now2))
            assert size_before == size_after, "typing a coordinate resized the box"
    finally:
        canvas.Destroy()


def test_the_selection_move_button_translates_the_whole_box(app) -> None:
    """The one-gesture keyboard equivalent, wired to the real behaviour.

    ``SelectionMoveButton`` is the class the select tool builds; this drives its
    ``_move`` against a real ``BlockSelectionBehaviour`` rather than a recorder,
    so a button that computes an offset and sends it nowhere fails.
    """
    from amulet_map_editor.programs.edit.plugins.tools.select import (
        SelectionMoveButton,
    )

    canvas = StubCanvas()
    try:
        behaviour = BlockSelectionBehaviour(canvas)
        behaviour.bind_events()
        behaviour.selection_group = SelectionGroup(SelectionBox((0, 0, 0), (12, 8, 10)))
        canvas.camera.projection_mode = Projection.PERSPECTIVE

        frame = wx.Frame(None, title="select tool", size=(200, 120))
        camera = RecordingCamera()
        control = SelectionMoveButton(
            frame,
            camera,
            DefaultKeys,
            "move",
            "tooltip",
            behaviour,
        )
        try:
            before = behaviour.active_block_positions
            control._move((2, -1, 3))
            after = behaviour.active_block_positions
            assert after[0] == tuple(a + b for a, b in zip(before[0], (2, -1, 3)))
            assert after[1] == tuple(a + b for a, b in zip(before[1], (2, -1, 3)))
        finally:
            frame.Destroy()
    finally:
        canvas.Destroy()
