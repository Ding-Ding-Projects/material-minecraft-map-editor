"""``confirm_pending`` reports what the paste did, not that it was asked.

The canvas's ``run_operation`` catches ``BaseException`` unless a caller asks
for exceptions, and the paste tool's ``confirm_paste`` returns nothing.  So a
paste that raised and a paste that wrote four hundred blocks arrive at the
bridge as exactly the same ``None``, and a bridge that returns ``True`` because
the call came back is reporting that it made the call -- which the caller
already knew.

**What this module can and cannot prove.**  It drives the real
``confirm_pending`` against a stand-in canvas, because staging a paste that
genuinely raises inside a real world means breaking the paste tool on purpose.
It therefore proves the branches: what the bridge does with a world whose undo
depth moved, one whose did not, and one that keeps no history at all.  It proves
nothing about the wiring -- whether a real canvas exposes ``world`` or a real
history exposes ``undo_count`` -- and it must not be read as if it did.  That
half is proven by ``test_editor_clone_runtime``, which opens a real world and
asserts the same call returns ``True`` while gold really lands in it: if the
attribute path here were wrong, that module's ``confirmed`` assertion would go
red against a paste that worked.
"""

from __future__ import annotations

from typing import Any, List

import pytest

from amulet_map_editor.api.studio import editor_tools


class _History:
    """A world's undo stack, as much of it as the bridge reads."""

    def __init__(self, undo_count: int = 0) -> None:
        self.undo_count = undo_count


class _World:
    def __init__(self, history: Any) -> None:
        self.history_manager = history


class _PasteTool:
    """The paste tool, holding something, with a confirm that can be told to fail.

    ``confirm_paste`` returning ``None`` either way is the whole point: it is
    what the real one does, and it is why the bridge cannot learn the outcome
    from the call.
    """

    def __init__(self, world: Any, writes: bool) -> None:
        self._is_enabled = True
        self._world = world
        self._writes = writes
        self.calls = 0

    def confirm_paste(self) -> None:
        self.calls += 1
        if self._writes and self._world.history_manager is not None:
            # What ``run_operation`` does after an operation that raised
            # nothing: it creates an undo point.  A confirm that raised skips
            # this line, exactly as the swallowed exception skips it there.
            self._world.history_manager.undo_count += 1


class _ToolWithoutConfirm:
    def __init__(self) -> None:
        self._is_enabled = True


class _Canvas:
    """Enough canvas for ``_paste_tool`` and ``_undo_depth`` to work on."""

    def __init__(self, tool: Any, world: Any) -> None:
        self.tools = {"Paste": tool}
        self.world = world


def _canvas(writes: bool, history: Any = None, keep_history: bool = True) -> _Canvas:
    history = _History() if (history is None and keep_history) else history
    world = _World(history)
    return _Canvas(_PasteTool(world, writes), world)


def test_a_paste_that_wrote_is_reported_as_confirmed() -> None:
    """The ordinary path still says yes, so the check cannot pass by refusing."""
    canvas = _canvas(writes=True)
    assert editor_tools.confirm_pending(canvas) is True
    assert canvas.tools["Paste"].calls == 1, "the tool's own confirm was not run"
    assert canvas.world.history_manager.undo_count == 1


def test_a_paste_that_raised_is_not_reported_as_confirmed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The defect this exists for.

    ``run_operation`` swallowed the exception, so ``confirm_paste`` returned
    normally and the world is untouched.  Anything that reported this as a
    successful clone would be telling the user their blocks are in a world that
    does not have them.
    """
    canvas = _canvas(writes=False)
    with caplog.at_level("ERROR"):
        result = editor_tools.confirm_pending(canvas)
    assert result is False, (
        "a confirm that wrote nothing was reported as a successful paste; the "
        "world's undo depth never moved"
    )
    assert canvas.tools["Paste"].calls == 1, (
        "the confirm was never attempted, so this passed for the wrong reason "
        "-- it must fail because the write did not land, not because it was "
        "never tried"
    )
    assert any(
        "nothing was written" in record.getMessage() for record in caplog.records
    ), f"the refusal was silent: {[r.getMessage() for r in caplog.records]}"


def test_a_world_with_no_history_is_reported_as_run_not_as_failed() -> None:
    """An unanswerable question is not a negative answer.

    A build whose level keeps no undo history cannot be asked whether the write
    landed.  Reporting failure there would break every caller on a world that
    is working perfectly well, so the bridge says the confirm ran and puts the
    doubt in the log instead of in the return value.
    """
    canvas = _canvas(writes=True, history=None, keep_history=False)
    assert editor_tools.confirm_pending(canvas) is True
    assert canvas.tools["Paste"].calls == 1


def test_nothing_pending_is_refused_before_anything_is_called() -> None:
    """No paste tool holding anything means there is nothing to confirm."""
    canvas = _Canvas(None, _World(_History()))
    assert editor_tools.confirm_pending(canvas) is False


def test_a_build_whose_paste_tool_has_no_confirm_is_refused() -> None:
    """The other guard that was already there, kept honest by a test."""
    canvas = _Canvas(_ToolWithoutConfirm(), _World(_History()))
    assert editor_tools.confirm_pending(canvas) is False


def test_the_undo_depth_reader_separates_zero_from_unanswerable() -> None:
    """``0`` and ``None`` mean different things and must stay different.

    A world with an empty undo stack answers zero; a canvas with no world at
    all answers nothing.  Collapsing the two would make a first-ever paste into
    an unverifiable one.
    """
    empty: List[Any] = []
    assert editor_tools._undo_depth(_Canvas(None, _World(_History(0)))) == 0
    assert editor_tools._undo_depth(_Canvas(None, _World(None))) is None
    assert editor_tools._undo_depth(object()) is None
    assert editor_tools._undo_depth(empty) is None
