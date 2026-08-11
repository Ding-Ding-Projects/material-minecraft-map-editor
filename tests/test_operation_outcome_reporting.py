"""What ``run_operation`` contains, what it lets through, and who hears about it.

``EditCanvas.run_operation`` caught ``BaseException`` and answered ``None``.
Two defects came out of that one line.

**It caught the interpreter.**  ``KeyboardInterrupt``, ``SystemExit`` and
``GeneratorExit`` are not an operation failing; they are the process being told
to stop.  Swallowing them meant Ctrl+C during a long world edit did nothing at
all.  ``MemoryError`` is *not* one of them however much it reads like one --
Python derives it from ``Exception`` -- and there is a test below saying so,
because the first version of this fix asserted the opposite and was wrong.

**It answered the same thing either way.**  Most operations return ``None``, so
"wrote four hundred blocks", "ran and wrote nothing" and "raised and was
contained" were one indistinguishable ``None``.  The visible consequence was in
``StudioShell._cmd_transform``, which wrapped ``canvas.copy()`` in
``try``/``except Exception`` -- code that could never run, because the exception
had already been eaten one frame down.  A copy that failed therefore reported
nothing, floated the *previous* contents of the structure cache, and let the
user rotate and paste blocks they had not copied.

The tests below run the **real** ``EditCanvas.run_operation`` against a stand-in
``self``, so the branch under test is the shipped one rather than a
reconstruction of it: only ``_run_operation`` -- the progress dialog and the
worker thread, which need a window and a world -- is stood in for, and it is
stood in for by something that raises or returns on demand.  The shell's two
callers are driven the same way, following
``tests/test_editor_command_report_evidence.py``.

Every test here was watched failing against the code as it shipped before being
kept, and each one that asserts a refusal is paired with the case that must
still succeed -- otherwise "always report a failure" would pass all of them.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

import pytest

from amulet_map_editor.api.outcome import Outcome
from amulet_map_editor.programs.edit.api.canvas.edit_canvas import (
    EditCanvas,
    OperationOutcome,
    contained_outcome,
)
from amulet_map_editor.programs.edit.api.operations.errors import (
    OperationError,
    OperationSilentAbort,
    OperationSuccessful,
)

# ---------------------------------------------------------------------------
# the canvas
# ---------------------------------------------------------------------------


class _Canvas:
    """The smallest ``self`` ``run_operation`` reaches for.

    ``_run_operation`` is scripted rather than stubbed blank: it is called twice
    on the success path -- once for the operation and once for the undo point --
    and the second call is exactly the one the old code could not report a
    failure from.  Each scripted entry is either a value to return or an
    exception instance to raise.
    """

    def __init__(self, *script: Any) -> None:
        self._script: List[Any] = list(script)
        self.calls: List[Tuple[str, bool]] = []

    def _run_operation(
        self,
        operation: Callable[[], Any],
        title: str,
        msg: str,
        cancelable: bool,
        rollback_on_error: Optional[Callable[[], bool]] = None,
    ) -> Any:
        self.calls.append((title, cancelable))
        assert (
            self._script
        ), "run_operation called _run_operation more times than scripted"
        result = self._script.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result

    def create_undo_point_iter(self, world: bool = True, non_world: bool = True):
        yield 1.0
        return True


def _run(*script: Any, **kwargs: Any) -> Tuple[Any, _Canvas]:
    """Run the real ``run_operation`` over a scripted canvas."""
    canvas = _Canvas(*script)
    outcome = EditCanvas.run_operation(canvas, lambda: None, title="Amulet", **kwargs)
    return outcome, canvas


def test_an_operation_that_ran_says_so_and_carries_its_value() -> None:
    """The success half, first, so nothing below can pass by always refusing.

    It also pins the two calls: the operation, cancelable, and then the undo
    point, which is not.  A ``run_operation`` that stopped creating undo points
    would make every refusal assertion below vacuous.
    """
    written = object()
    outcome, canvas = _run(written, None)
    assert isinstance(outcome, OperationOutcome), outcome
    assert outcome.ok and bool(outcome) is True, outcome
    assert outcome.reason == "", outcome
    assert outcome.failed is False, outcome
    assert outcome.value is written, "the operation's own return value was lost"
    assert [cancelable for _, cancelable in canvas.calls] == [True, False], (
        "the undo point was not created after a successful operation, so every "
        f"failure assertion in this module is vacuous: {canvas.calls}"
    )


def test_a_contained_exception_is_reported_as_a_failure() -> None:
    """The defect: a raise and a success were the same ``None`` to the caller."""
    error = OperationError("the chunk was locked")
    outcome, canvas = _run(error)
    assert not outcome, "a contained exception was reported as a success"
    assert outcome.reason == "raised", outcome
    assert outcome.failed is True, outcome
    assert outcome.error is error, "the caller cannot name what went wrong"
    assert "the chunk was locked" in outcome.message, outcome.message
    assert len(canvas.calls) == 1, (
        "an undo point was created for an operation that raised: " f"{canvas.calls}"
    )


def test_an_exception_with_no_message_is_still_named() -> None:
    """A bare ``raise SomeError`` must not produce an empty explanation."""
    outcome, _ = _run(RuntimeError())
    assert outcome.message == "RuntimeError", outcome.message


def test_a_cancelled_operation_is_not_reported_as_a_failure() -> None:
    """The user cancelling the progress dialog is not a fault to show them.

    ``_run_operation`` deliberately says nothing about a ``BaseSilentException``,
    so a caller that treated every falsy outcome as broken would turn the user's
    own cancel into a red error about a thing that did what they asked.
    """
    outcome, _ = _run(OperationSilentAbort())
    assert not outcome, outcome
    assert outcome.reason == "aborted", outcome
    assert outcome.failed is False, "a deliberate cancel was reported as a failure"


def test_an_operation_that_stopped_itself_is_not_reported_as_a_failure() -> None:
    """``OperationSuccessful`` ends the operation with its own message shown."""
    outcome, _ = _run(OperationSuccessful("a scale of zero pastes nothing"))
    assert not outcome, outcome
    assert outcome.reason == "stopped", outcome
    assert outcome.failed is False, outcome
    assert "scale of zero" in outcome.message, outcome.message


@pytest.mark.parametrize("error", (KeyboardInterrupt(), SystemExit(1), GeneratorExit()))
def test_the_interpreter_s_own_exceptions_are_not_contained(
    error: BaseException,
) -> None:
    """Ctrl+C during a long operation must reach the interpreter.

    Catching ``BaseException`` here made an unresponsive application that ignores
    Ctrl+C the mildest possible consequence.  ``throw_exceptions`` is left at its
    default, because whether these travel is not the caller's to decide.
    """
    with pytest.raises(type(error)):
        _run(error)


def test_a_memory_error_is_still_contained_because_python_says_it_is_ordinary() -> None:
    """Written down because the opposite is easy to assume and never noticed.

    ``MemoryError`` reads like a sibling of ``KeyboardInterrupt`` and is not
    one: Python derives it from ``Exception``, so narrowing the catch does not
    let it through.  This test exists so nobody -- including a comment in
    ``edit_canvas`` that said so before this was run -- claims otherwise again.
    """
    outcome, _ = _run(MemoryError("out of memory"))
    assert not outcome and outcome.reason == "raised", outcome
    assert MemoryError.__mro__[1] is Exception


def test_throw_exceptions_still_raises_the_operation_s_own_error() -> None:
    """The existing opt-out is unchanged for the exceptions it was about."""
    error = OperationError("the chunk was locked")
    with pytest.raises(OperationError) as raised:
        _run(error, throw_exceptions=True)
    assert raised.value is error


def test_a_lost_undo_point_does_not_claim_the_write_failed() -> None:
    """The operation wrote the world; only the undo point did not happen.

    Reporting this as a failed edit would send somebody looking for blocks that
    are already there, and reporting nothing at all is how the undo stack
    silently stops matching the world.
    """
    written = object()
    error = RuntimeError("the history file is read only")
    outcome, canvas = _run(written, error)
    assert outcome.ok is True, "an edit that landed was reported as not having"
    assert outcome.reason == "no-undo-point", outcome
    assert outcome.failed is True, "a lost undo point was reported as fine"
    assert outcome.value is written, outcome
    assert outcome.error is error
    assert len(canvas.calls) == 2, canvas.calls


# ---------------------------------------------------------------------------
# copying, where a silent abort means success
# ---------------------------------------------------------------------------


class _Cache:
    """The structure cache, as much of it as ``_lift`` counts."""

    def __init__(self, held: int = 0) -> None:
        self.held = held

    def __len__(self) -> int:
        return self.held


class _LiftCanvas:
    """A canvas whose ``run_operation`` is scripted and whose clipboard is watched."""

    world = object()
    dimension = "minecraft:overworld"
    #: The real one, so ``copy`` reaches the code under test rather than a copy
    #: of it living in this file.
    _lift = EditCanvas._lift

    def __init__(self, outcome: OperationOutcome, adds: int) -> None:
        self._outcome = outcome
        self._adds = adds
        self.selection = self

    @property
    def selection_group(self) -> Any:
        return ()

    def run_operation(self, operation: Callable[[], Any], **kwargs: Any) -> Any:
        _cache.held += self._adds
        return self._outcome


_cache = _Cache()


def _lift(monkeypatch, outcome: OperationOutcome, adds: int) -> OperationOutcome:
    """Run the real ``EditCanvas.copy`` over a scripted clipboard."""
    import amulet_map_editor.programs.edit.api.canvas.edit_canvas as canvas_module

    global _cache
    _cache = _Cache()
    monkeypatch.setattr(canvas_module, "structure_cache", _cache)
    return EditCanvas.copy(_LiftCanvas(outcome, adds))


def test_a_copy_that_ended_in_a_silent_abort_is_still_a_copy(monkeypatch) -> None:
    """The trap this whole method exists for, and it is not hypothetical.

    ``internal_operations.copy`` ends with ``raise OperationSilentAbort`` on the
    path where it worked -- it is declining an undo point for an operation that
    only reads the world.  Reading that as a failure refuses every clone in the
    application, which is precisely what happened until the real-editor clone
    test caught it.
    """
    outcome = _lift(monkeypatch, contained_outcome(OperationSilentAbort()), adds=1)
    assert outcome.ok, (
        "a copy that added a structure to the clipboard was reported as having "
        f"failed, because the operation signalled success by aborting: {outcome}"
    )
    assert outcome.reason == "", outcome


def test_a_copy_that_added_nothing_says_so(monkeypatch) -> None:
    """The other half: a cancel raises the same class and must not pass."""
    outcome = _lift(monkeypatch, contained_outcome(OperationSilentAbort()), adds=0)
    assert not outcome, "a cancelled copy was reported as having filled the clipboard"
    assert outcome.reason == "nothing-copied", outcome


def test_a_copy_that_raised_keeps_its_own_reason(monkeypatch) -> None:
    """A real error is not relabelled into the clipboard's vocabulary."""
    outcome = _lift(
        monkeypatch, contained_outcome(OperationError("nothing is selected")), adds=0
    )
    assert outcome.reason == "raised", outcome
    assert outcome.failed is True
    assert "nothing is selected" in outcome.message


def test_the_outcome_is_the_one_shared_convention() -> None:
    """Not a second dataclass with the same fields in a different order."""
    assert issubclass(OperationOutcome, Outcome)
    assert bool(OperationOutcome(ok=True)) is True
    assert bool(OperationOutcome(ok=False, reason="raised")) is False


# ---------------------------------------------------------------------------
# the callers
# ---------------------------------------------------------------------------


from amulet_map_editor.api.studio.shell import StudioShell  # noqa: E402


class _Shell:
    """The smallest ``self`` the two shell methods under test reach for."""

    doc_title = "test world"
    project_path = "/tmp/test-world"

    def __init__(self, corners: Tuple[Any, ...] = (((0, 0, 0), (1, 1, 1)),)) -> None:
        self.said: List[Dict[str, str]] = []
        self.recorded: List[Tuple[str, Dict[str, Any]]] = []
        self._corners = corners
        self.deferred: List[Tuple[Any, ...]] = []

    def notify(self, title: Any, body: Any, severity: str = "info") -> None:
        self.said.append(
            {"title": str(title), "body": str(body), "severity": str(severity)}
        )

    def _record(self, key: str, payload: Dict[str, Any]) -> None:
        self.recorded.append((key, payload))

    def _history_counts(self) -> Tuple[int, int]:
        return (3, 0)

    def _selection_corners(self) -> Tuple[Any, ...]:
        return self._corners

    def _dimension_name(self) -> str:
        return "minecraft:overworld"

    def _level(self) -> Any:
        return None

    def _sync_world_state(self) -> None:
        return None

    def _after_editor_command(
        self, key: str, before: Tuple[int, int], subject: str = ""
    ) -> None:
        self.said.append(
            {
                "title": "after_editor_command",
                "body": f"{key}:{subject}",
                "severity": "success",
            }
        )


class _Operation:
    def __init__(self, outcome: Any) -> None:
        self._outcome = outcome
        self.runs = 0

    def _run_operation(self, _evt: Any) -> Any:
        self.runs += 1
        return self._outcome


class _OperationTool:
    active_operation_name = "Fill"
    active_operation_id = "some.module.fill"

    def __init__(self, outcome: Any) -> None:
        self._active_operation = _Operation(outcome)


def test_the_shell_reports_a_failed_operation_rather_than_a_quiet_undo_depth() -> None:
    """The user pressed Run operation and the plugin raised.

    Before the outcome existed, the shell could only see that the undo depth had
    not moved, so it said "the world recorded no new undo point" -- true, and
    silent about the error that caused it.
    """
    shell = _Shell()
    tool = _OperationTool(
        OperationOutcome(
            ok=False, reason="raised", message="the block palette is empty"
        )
    )
    StudioShell._run_active_operation(shell, tool)
    assert tool._active_operation.runs == 1, "the operation was never run"
    assert len(shell.said) == 1, shell.said
    said = shell.said[0]
    assert said["severity"] == "error", said
    assert "the block palette is empty" in said["body"], said["body"]
    assert "Fill" in said["body"], said["body"]
    assert "recorded no new undo point" not in said["body"], (
        "the shell reported the symptom it could see before rather than the "
        f"error it can see now: {said['body']!r}"
    )
    assert shell.recorded and shell.recorded[0][1]["failed"] is True, shell.recorded


def test_the_shell_still_reports_a_successful_operation_normally() -> None:
    """Otherwise the test above would pass on "always report an error"."""
    shell = _Shell()
    tool = _OperationTool(OperationOutcome(ok=True, value=None))
    StudioShell._run_active_operation(shell, tool)
    assert [said["body"] for said in shell.said] == ["runOperation:Fill"], shell.said


def test_the_shell_still_defers_to_the_undo_depth_when_nothing_is_reported() -> None:
    """A panel that answers ``None`` is not evidence of a failure."""
    shell = _Shell()
    tool = _OperationTool(None)
    StudioShell._run_active_operation(shell, tool)
    assert [said["body"] for said in shell.said] == ["runOperation:Fill"], shell.said


def test_the_shell_does_not_run_an_operation_over_an_empty_selection() -> None:
    """``runOperation`` needs only ``editor``, and every operation gets the selection.

    So the command that brings the Operation tool to the front would also hand a
    plugin an empty ``SelectionGroup`` and run it, with the tool's own list of
    operations showing whatever it happened to be showing.
    """
    shell = _Shell(corners=())
    tool = _OperationTool(OperationOutcome(ok=True))
    StudioShell._run_active_operation(shell, tool)
    assert tool._active_operation.runs == 0, (
        "an operation was run with nothing selected, so it was handed an empty "
        "selection group"
    )
    assert len(shell.said) == 1, shell.said
    said = shell.said[0]
    assert said["severity"] == "warning", said
    assert "nothing is selected" in said["body"], said["body"]
    assert "Run button" in said["body"], (
        "declining must name the route that still works for an operation which "
        f"does not need a selection: {said['body']!r}"
    )


class _TransformCanvas:
    def __init__(self, outcome: Any) -> None:
        self._outcome = outcome
        self.pasted = 0

    def copy(self) -> Any:
        return self._outcome

    def paste_from_cache(self) -> None:
        self.pasted += 1


class _IdlePaste:
    _is_enabled = False


class _TransformShell(_Shell):
    def __init__(self, canvas: Any) -> None:
        super().__init__()
        self._transform_canvas = canvas

    def _canvas(self) -> Any:
        return self._transform_canvas

    def _editor_tool(self, name: str) -> Any:
        return _IdlePaste()

    def _apply_paste_transform(self, key: str, announce: bool = False) -> None:
        # Never called: ``wx.CallAfter`` is recorded rather than run, because
        # scheduling it is the fact under test and running it needs a live app.
        raise AssertionError("the deferred transform should not have run inline")


def _transform(canvas: Any, monkeypatch: Any) -> _TransformShell:
    """Run the real ``_cmd_transform``, with ``wx.CallAfter`` recorded."""
    import amulet_map_editor.api.studio.shell as shell_module

    shell = _TransformShell(canvas)
    monkeypatch.setattr(
        shell_module.wx,
        "CallAfter",
        lambda *args, **kwargs: shell.deferred.append(args),
    )
    StudioShell._cmd_transform(shell, "rotate")
    return shell


def test_a_failed_copy_stops_the_transform_instead_of_floating_the_last_one(
    monkeypatch,
) -> None:
    """The unreachable ``except`` in ``_cmd_transform``, made reachable.

    Without this the structure cache still holds whatever was copied before, so
    the rotate command floats *that*, transforms it, and offers the user blocks
    they never copied.
    """
    canvas = _TransformCanvas(
        OperationOutcome(ok=False, reason="raised", message="the selection is locked")
    )
    shell = _transform(canvas, monkeypatch)
    assert canvas.pasted == 0, (
        "a copy that failed was still floated in the paste tool, so the user is "
        "looking at the previous copy"
    )
    assert not shell.deferred, "the transform was applied after a failed copy"
    assert len(shell.said) == 1, shell.said
    said = shell.said[0]
    assert said["severity"] == "error", said
    assert "the selection is locked" in said["body"], said["body"]


def test_a_cancelled_copy_stops_the_transform_without_calling_it_an_error(
    monkeypatch,
) -> None:
    canvas = _TransformCanvas(OperationOutcome(ok=False, reason="aborted"))
    shell = _transform(canvas, monkeypatch)
    assert canvas.pasted == 0
    assert shell.said and shell.said[0]["severity"] == "warning", shell.said


def test_a_successful_copy_still_floats_and_transforms(monkeypatch) -> None:
    """The other half: the guard must not stop a copy that worked."""
    canvas = _TransformCanvas(OperationOutcome(ok=True))
    shell = _transform(canvas, monkeypatch)
    assert canvas.pasted == 1, "a successful copy was not handed to the paste tool"
    assert shell.deferred, "the transform was never scheduled after a good copy"
    assert not shell.said, shell.said


def test_a_canvas_that_reports_nothing_still_floats_and_transforms(
    monkeypatch,
) -> None:
    """An absent answer is not a refusal; an older canvas keeps working."""
    canvas = _TransformCanvas(None)
    shell = _transform(canvas, monkeypatch)
    assert canvas.pasted == 1, shell.said
    assert shell.deferred, shell.said
