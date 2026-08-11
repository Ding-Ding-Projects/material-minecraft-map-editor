"""What moving the pending object reports, and the one thing it deliberately does not.

``stop_following`` reads its flag back rather than trusting the write.
``set_pending_location`` does not read the *position* back, and the asymmetry
inside one module is the kind of thing a later reader tidies up on sight.  This
module exists so that tidying goes red.

**Why the position is not compared.**  The tool's coordinate boxes are spin
controls bounded to the world's limits, so a position outside them is answered
with the nearest one inside them -- a real move, and the right one.  A read-back
that called that a failure would be believed by callers that treat a failure as
"the tool has gone": the pane's ``_nudge`` and its ``_pending_to_camera`` both
answer one by hiding the pending panel.  The copy is still held and still drawn
at that point, so the panel disappearing is precisely the defect
``confirm_pending`` was fixed for, arriving through the position boxes instead.

**Why the flag still gets checked, just not here.**  ``following`` is read back
out of the tool by ``pending_object`` and rendered by the pane as its own row,
so an object that went on following the pointer says so on screen.  The check
exists; it lives at the layer that can show the answer instead of at the layer
that would have to guess what to do about it.

The clamping stand-in below mirrors ``TupleIntInput``, whose ``wx.SpinCtrl``
bounds are the source of the behaviour, so the test is about the real widget's
rule rather than about an invented one.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import pytest

from amulet_map_editor.api.studio import editor_tools

#: The bounds ``TupleInput`` gives every one of its spin controls.
LIMIT = 30_000_000


class _ClampingInput:
    """A coordinate triple that bounds what it is given, as a spin control does."""

    def __init__(self, start: Tuple[int, int, int] = (0, 0, 0)) -> None:
        self._value = tuple(int(value) for value in start)

    @property
    def value(self) -> Tuple[int, int, int]:
        return self._value

    @value.setter
    def value(self, value: Any) -> None:
        self._value = tuple(
            max(-LIMIT, min(LIMIT, int(number))) for number in value
        )  # type: ignore[assignment]


class _PasteTool:
    """The paste tool, to the depth the position bridge touches it."""

    def __init__(self, start: Tuple[int, int, int] = (0, 0, 0)) -> None:
        self._is_enabled = True
        self._moving = True
        self._location = _ClampingInput(start)
        self._rotation = _ClampingInput((0, 0, 0))
        self._scale = _ClampingInput((1, 1, 1))

    @property
    def location(self) -> Tuple[int, int, int]:
        return self._location.value

    @location.setter
    def location(self, value: Any) -> None:
        self._location.value = value


class _RefusingTool(_PasteTool):
    """A tool whose position cannot be written at all."""

    @property
    def location(self) -> Tuple[int, int, int]:
        return self._location.value

    @location.setter
    def location(self, value: Any) -> None:
        raise RuntimeError("this build's paste tool will not take a position")


class _Canvas:
    def __init__(self, tool: Any) -> None:
        self.tools: Dict[str, Any] = {"Paste": tool}


def _canvas(tool: Optional[Any] = None) -> _Canvas:
    return _Canvas(_PasteTool() if tool is None else tool)


# ----------------------------------------------------------------------
# the ordinary move, so nothing below can pass by refusing
# ----------------------------------------------------------------------


def test_a_position_inside_the_world_is_written_and_reported() -> None:
    """The precondition for every assertion below.

    Without it, a bridge that had stopped writing anything at all would satisfy
    the clamping test -- "it returned True and the position is not what was
    asked for" is exactly what a dead write produces.
    """
    canvas = _canvas()
    assert editor_tools.set_pending_location((8, 40, 8), canvas) is True
    assert canvas.tools["Paste"].location == (8, 40, 8)


def test_dropping_stops_the_object_following_where_the_pane_reads_it() -> None:
    """The flag is answered by a read-back, at the layer that renders it.

    A typed coordinate does not survive an object that is still tracking the
    pointer, so this is the half that has to be true rather than assumed --
    and ``pending_object`` is where the pane gets its "Following the pointer"
    row from, so this is the value a user actually sees.
    """
    canvas = _canvas()
    assert canvas.tools["Paste"]._moving is True, "precondition: it was following"

    editor_tools.set_pending_location((8, 40, 8), canvas)

    held = editor_tools.pending_object(canvas)
    assert held is not None
    assert held.following is False, (
        "the object is still following the pointer after a position was typed, "
        "so the next mouse move overwrites it and the pane says otherwise"
    )


def test_asking_it_not_to_drop_leaves_the_object_following() -> None:
    """``drop`` is a real choice, not a parameter nothing reads."""
    canvas = _canvas()
    editor_tools.set_pending_location((8, 40, 8), canvas, drop=False)
    held = editor_tools.pending_object(canvas)
    assert held is not None and held.following is True


# ----------------------------------------------------------------------
# the policy this module exists for
# ----------------------------------------------------------------------


def test_a_position_past_the_world_edge_is_a_move_and_not_a_vanished_tool() -> None:
    """A clamped position is reported as the move it is.

    This is the assertion that costs something to break.  Comparing the
    position back and returning ``False`` here reads as a tidy-up -- the
    function above it does read its flag back -- and it hands the pane a
    failure, which the pane answers by hiding the pending panel while the copy
    is still held and still drawn over the world.  A user who nudged into the
    world's edge would watch the controls for the thing they are holding
    disappear.

    So: the write is reported as having happened, because it did, and the
    position the tool ended up at is available to anyone who wants it by
    reading the tool back.
    """
    canvas = _canvas(_PasteTool((0, 0, 0)))
    asked = (LIMIT + 5000, 40, 8)

    assert editor_tools.set_pending_location(asked, canvas) is True, (
        "a position outside the world's limits was reported as a failed move. "
        "Every caller that reacts to that decides the tool has gone and takes "
        "the pending panel away, so the copy stays held with no controls for it"
    )

    held = editor_tools.pending_object(canvas)
    assert held is not None
    assert held.location == (LIMIT, 40, 8), (
        "the object should have moved to the nearest position inside the "
        f"world, and is at {held.location}"
    )
    assert held.location != asked[:3], (
        "the stand-in did not clamp anything, so this test proved nothing "
        "about a clamped move"
    )


def test_a_nudge_into_the_edge_still_answers_with_a_position() -> None:
    """The caller that would hide the panel gets an answer instead of ``None``.

    ``nudge_pending`` returning ``None`` is what reaches ``_report_tool_gone``.
    Asserting it here means the policy is pinned at the layer the pane actually
    calls, not only at the one below it.
    """
    canvas = _canvas(_PasteTool((LIMIT - 1, 40, 8)))
    moved = editor_tools.nudge_pending(0, 1000, canvas)
    assert moved is not None, (
        "nudging into the world's edge reported that there is nothing to move, "
        "which the pane answers by taking the pending panel away"
    )
    assert moved == (LIMIT, 40, 8), moved


def test_a_tool_that_refuses_the_write_is_still_reported_as_a_failure() -> None:
    """The policy is about clamping, not about swallowing everything.

    A position that could not be written at all is a genuine failure and has to
    keep saying so, or the paragraph above becomes a licence to report success
    unconditionally -- which is the defect this whole area was fixed for.
    """
    canvas = _canvas(_RefusingTool())
    assert editor_tools.set_pending_location((8, 40, 8), canvas) is False


def test_nothing_held_is_reported_as_a_failure() -> None:
    """No paste tool means no object to move."""
    assert editor_tools.set_pending_location((8, 40, 8), _Canvas(None)) is False
