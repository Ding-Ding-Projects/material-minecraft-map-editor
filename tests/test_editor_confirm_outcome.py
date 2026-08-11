"""``confirm_pending`` reports what the paste did, and says so out loud.

The canvas's ``run_operation`` used to catch ``BaseException`` and answer
``None``, and the paste tool's ``confirm_paste`` used to return nothing.  So a
paste that raised and a paste that wrote four hundred blocks arrived at the
bridge as exactly the same ``None``, and a bridge that returns ``True`` because
the call came back is reporting that it made the call -- which the caller
already knew.

**Both of those are now fixed, and this module covers both shapes on purpose.**
``run_operation`` catches ``Exception`` and returns an ``OperationOutcome``, and
``confirm_paste`` hands that outcome back -- so the bridge can be told *why*
rather than inferring *that* from the world's undo depth.  The depth inference
stays for a build whose paste tool predates the outcome, and
:class:`_PasteTool` below is exactly such a build: it calls ``run_operation``
and drops the answer.  :class:`_ReportingPasteTool` is the shipped one, and it
is not an optional extra here -- every branch that reads the reported outcome is
unreachable without it, which is how the whole of that branch shipped with no
coverage at all while this module was green.

Returning ``False`` was necessary and was not sufficient.  The swallowed
exception is invisible by construction: the progress dialog comes and goes and
every surface then looks exactly as it does after a paste that worked.  So the
second half of the contract is that each refusal reaches the user through the
non-blocking notifier, naming the operation, what did not happen, and what to do
about it -- and that those facts survive every language mode and both funny
levels, which style the voice around them and never the numbers inside them.

**What this module can and cannot prove.**  The failing paste here is driven
through a stand-in canvas that reproduces ``run_operation``'s own swallow --
operation raises, exception is caught, the undo point on the no-exception path
is never reached -- because staging a paste that genuinely raises inside a real
world means breaking the paste tool on purpose.  It therefore proves the
branches and the words.  It proves nothing about the wiring -- whether a real
canvas exposes ``world`` or a real history exposes ``undo_count`` -- and it must
not be read as if it did.  That half is proven by
``test_editor_clone_runtime.test_the_bridge_can_really_read_this_world_s_undo_depth``,
which reads the depth out of a real open world either side of a real paste and
asserts it is a number and that it moved.

This paragraph used to name that module's *``confirmed``* assertion instead, and
that was wrong in a way worth leaving written down, because it is the shape of
mistake this whole area keeps making.  A broken attribute path does not produce
a refusal: ``_undo_depth`` returns ``None``, which routes into the deliberate
"an unanswerable question is not a negative answer" branch and reports
``ok=True`` -- and the blocks still land, because the confirm still ran.  So
renaming ``history_manager`` to something that does not exist leaves the entire
real-world module green while the check that catches a silently failed paste is
switched off.  A guard that cannot fail was being cited as the proof that
another guard works.

One honest gap: ``cancel_pending``'s *successful* path posts a wx tool-change
event, so only its refusal and its already-empty paths are covered here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, List, Optional

import pytest

from amulet_map_editor.api import notifications
from amulet_map_editor.api.studio import editor_tools
from amulet_map_editor.api.studio import copy as studio_copy
from amulet_map_editor.programs.edit.api.canvas.edit_canvas import (
    OperationOutcome,
    contained_outcome,
)
from amulet_map_editor.programs.edit.api.operations.errors import OperationSilentAbort


class _History:
    """A world's undo stack, as much of it as the bridge reads."""

    def __init__(self, undo_count: int = 0) -> None:
        self.undo_count = undo_count


class _World:
    def __init__(self, history: Any) -> None:
        self.history_manager = history


class _Canvas:
    """Enough canvas for the bridge to work on, kept to the shipped shape.

    ``run_operation`` is not a convenience stub.  It is written to match the
    real one, because its shape is what every branch below turns on: the
    exception is caught -- ``Exception``, exactly as the real one now catches,
    not ``BaseException`` -- nothing is re-raised while ``throw_exceptions`` is
    false, an ``OperationOutcome`` is returned either way, and the undo point is
    created only on the path where nothing raised.

    The comment here used to say the real one caught ``BaseException``.  It had
    stopped being true, and a stand-in that lies about the code it stands in for
    is worse than no stand-in: every test written against it proves something
    about a canvas that does not exist.

    ``lose_undo_point`` reproduces the one success whose undo depth does not
    move -- the operation wrote the world and only the undo point could not be
    recorded -- because that is the case the depth inference is guaranteed to
    read as a failure.
    """

    def __init__(self, world: Any, lose_undo_point: bool = False) -> None:
        self.tools: dict = {}
        self.world = world
        self.operations_run = 0
        self._lose_undo_point = lose_undo_point

    def run_operation(
        self,
        operation: Callable[[], Any],
        title: Optional[str] = None,
        msg: str = "Running Operation",
        throw_exceptions: bool = False,
        rollback_on_error: Any = None,
    ) -> OperationOutcome:
        self.operations_run += 1
        try:
            out = operation()
        except Exception as error:
            if throw_exceptions:
                raise error
            return contained_outcome(error)
        if self._lose_undo_point:
            # The world was written; only the history was not.  The depth
            # deliberately does not move, which is the whole point of the token.
            return OperationOutcome(
                ok=True,
                reason="no-undo-point",
                message="the history file is read only",
                value=out,
                error=RuntimeError("the history file is read only"),
            )
        history = getattr(self.world, "history_manager", None)
        if history is not None:
            history.undo_count += 1
        return OperationOutcome(ok=True, value=out)


class _PasteTool:
    """A paste tool from before ``confirm_paste`` reported anything.

    It runs the operation and drops what ``run_operation`` answers, so the
    bridge cannot learn the outcome from the call and falls through to the undo
    depth.  Every build that predates the outcome behaves this way, which is why
    the inference stays and why it is still exercised here.
    """

    def __init__(self, canvas: _Canvas, operation: Callable[[], Any]) -> None:
        self._is_enabled = True
        self._canvas = canvas
        self._operation = operation
        self.calls = 0

    def confirm_paste(self) -> None:
        self.calls += 1
        self._canvas.run_operation(self._operation)


class _ReportingPasteTool(_PasteTool):
    """The shipped paste tool: it returns what ``run_operation`` told it.

    Without this class every branch of ``confirm_pending`` that reads the
    reported outcome is unreachable, and deleting that branch outright leaves
    this module green -- which is exactly what happened when it was added.
    """

    def confirm_paste(self) -> OperationOutcome:
        self.calls += 1
        return self._canvas.run_operation(self._operation)


class _ToolWithoutConfirm:
    def __init__(self) -> None:
        self._is_enabled = True


class _RaisingConfirm:
    """A paste tool whose confirm fails before it reaches ``run_operation``.

    Nothing catches this one, so without a guard it leaves the bridge through a
    wx button handler.
    """

    def __init__(self) -> None:
        self._is_enabled = True
        self.calls = 0

    def confirm_paste(self) -> None:
        self.calls += 1
        raise RuntimeError("the paste tool fell over before running anything")


def _wrote(_canvas: _Canvas) -> Callable[[], Any]:
    def operation() -> None:
        return None

    return operation


def _raised(_canvas: _Canvas) -> Callable[[], Any]:
    def operation() -> None:
        raise RuntimeError("the paste operation could not read the source chunk")

    return operation


def _aborted(_canvas: _Canvas) -> Callable[[], Any]:
    """The user cancelled the progress dialog, or the operation ended itself."""

    def operation() -> None:
        raise OperationSilentAbort()

    return operation


def _canvas(
    operation: Callable[[_Canvas], Callable[[], Any]] = _wrote,
    *,
    keep_history: bool = True,
    tool: type = _PasteTool,
    lose_undo_point: bool = False,
) -> _Canvas:
    canvas = _Canvas(
        _World(_History() if keep_history else None), lose_undo_point=lose_undo_point
    )
    canvas.tools["Paste"] = tool(canvas, operation(canvas))
    return canvas


# ---------------------------------------------------------------------------
# the notification sink
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Recorded:
    severity: str
    title: str
    body: str
    details: str


@pytest.fixture(autouse=True)
def recorded(monkeypatch: pytest.MonkeyPatch) -> List[_Recorded]:
    """Capture what reaches the notification store, without persisting it.

    The store is replaced at its own boundary rather than the bridge's, so
    everything between the two still runs for real: the bridge's reporter, its
    lazy import of the wx notifier, and that notifier's own bounding of the
    text.  Only the durable write at the far end is intercepted -- a test has no
    business appending to the user's real notification history.
    """
    seen: List[_Recorded] = []

    def add(severity: str, title: str, body: str, *, details: str = "") -> Any:
        seen.append(_Recorded(severity, title, body, details))
        return notifications.Notification(
            notification_id="test",
            created_at="2026-08-11T00:00:00+00:00",
            severity=severity,
            title=title,
            body=body,
            details=details,
        )

    monkeypatch.setattr(notifications, "add", add)
    return seen


@dataclass
class _Prefs:
    """Only the fields the Studio copy layer reads."""

    language_mode: str = "english"
    funny_level_english: int = 1
    funny_level_cantonese: int = 1


@pytest.fixture(autouse=True)
def english(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the presentation so the wording assertions mean one thing.

    This configures the application the way a user's settings would; the copy
    layer itself still runs for real, which is what the language and funny-level
    test below relies on.
    """
    monkeypatch.setattr(
        studio_copy.school_mode,
        "presentation_preferences",
        lambda _preferences: _Prefs(),
    )


# ---------------------------------------------------------------------------
# the outcome
# ---------------------------------------------------------------------------


def test_a_paste_that_wrote_is_reported_as_confirmed(
    recorded: List[_Recorded],
) -> None:
    """The ordinary path still says yes, so the check cannot pass by refusing."""
    canvas = _canvas(_wrote)
    result = editor_tools.confirm_pending(canvas)
    assert result.ok is True
    assert bool(result) is True
    assert result.reason == ""
    assert canvas.tools["Paste"].calls == 1, "the tool's own confirm was not run"
    assert canvas.world.history_manager.undo_count == 1
    assert recorded == [], "a paste that worked must not report anything at all"


def test_a_paste_whose_operation_raised_is_not_reported_as_confirmed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The defect this module exists for.

    The operation raises, ``run_operation`` swallows it exactly as the real one
    does, and ``confirm_paste`` returns normally with the world untouched.
    Anything reporting this as a successful clone would be telling the user
    their blocks are in a world that does not have them.
    """
    canvas = _canvas(_raised)
    with caplog.at_level("ERROR"):
        result = editor_tools.confirm_pending(canvas)

    assert result.ok is False, (
        "a confirm whose operation raised was reported as a successful paste; "
        "the world's undo depth never moved"
    )
    assert bool(result) is False
    assert result.reason == "not-written"
    assert canvas.tools["Paste"].calls == 1, (
        "the confirm was never attempted, so this passed for the wrong reason "
        "-- it must fail because the write did not land, not because it was "
        "never tried"
    )
    assert canvas.operations_run == 1, "the operation never reached the swallow"
    assert canvas.world.history_manager.undo_count == 0
    assert any(
        "nothing was written" in record.getMessage() for record in caplog.records
    ), f"the refusal was silent in the log: {[r.getMessage() for r in caplog.records]}"


def test_the_failed_paste_is_said_where_the_user_can_see_it(
    recorded: List[_Recorded],
) -> None:
    """A return value the interface never renders is a silent failure.

    This is the half a bare ``False`` could not carry.  The user pressed a
    button; the only honest outcome is a message that names the operation, says
    the world is unchanged, and gives them somewhere to go next.
    """
    result = editor_tools.confirm_pending(_canvas(_raised))

    assert len(recorded) == 1, (
        "a paste that wrote nothing produced no notification, so the only trace "
        f"of the failure is a log line the user never sees: {recorded}"
    )
    said = recorded[0]
    assert said.severity == "error", f"a lost paste was reported as {said.severity!r}"
    assert said.title.strip(), "the notification had no title"

    for fact, why in (
        ("Confirm placement", "the message does not name the operation"),
        ("no blocks were written", "the message does not say what did not happen"),
        ("still being held", "the message does not say the object survived"),
        ("Cancel", "the message offers no way out"),
    ):
        assert fact in result.message, f"{why}: {result.message!r}"
    # The notification and the returned message are the same sentence, so the
    # toast and the pane cannot disagree about what went wrong.
    assert said.body.startswith(result.message[:40]), (
        f"the notification said something other than the outcome: {said.body!r} "
        f"vs {result.message!r}"
    )


def test_the_failure_names_the_undo_depth_it_read(
    recorded: List[_Recorded],
) -> None:
    """The number is the evidence, so it is quoted rather than described."""
    canvas = _canvas(_raised)
    canvas.world.history_manager.undo_count = 7
    result = editor_tools.confirm_pending(canvas)
    assert "7" in result.message, result.message
    assert "7" in recorded[0].body, recorded[0].body


@pytest.mark.parametrize("mode", ["english", "cantonese", "bilingual"])
@pytest.mark.parametrize("level", [1, 3, 5])
def test_the_facts_survive_every_language_mode_and_funny_level(
    monkeypatch: pytest.MonkeyPatch, mode: str, level: int
) -> None:
    """Tone styles the voice; it never edits the numbers or the route out.

    The whole point of letting a funny level near an error message is that the
    facts are protected from it.  A level that rewrote "undo history is still at
    7" into a joke would be worse than no message.
    """
    monkeypatch.setattr(
        studio_copy.school_mode,
        "presentation_preferences",
        lambda _preferences: _Prefs(
            language_mode=mode,
            funny_level_english=level,
            funny_level_cantonese=level,
        ),
    )
    canvas = _canvas(_raised)
    canvas.world.history_manager.undo_count = 7
    result = editor_tools.confirm_pending(canvas)

    assert result.ok is False
    assert result.reason == "not-written"
    assert "7" in result.message, (
        f"the undo depth was lost at {mode} level {level}, so the message no "
        f"longer says what was checked: {result.message!r}"
    )
    if mode in ("english", "bilingual"):
        assert "Confirm placement" in result.message
        assert "Cancel" in result.message
    if mode in ("cantonese", "bilingual"):
        assert "確認擺位" in result.message
    assert result.title.strip(), "the title was lost"


@pytest.mark.parametrize("mode", ["english", "cantonese", "bilingual"])
def test_the_notification_is_accepted_by_the_store_in_every_language(
    monkeypatch: pytest.MonkeyPatch, recorded: List[_Recorded], mode: str
) -> None:
    """A report the notification store refuses is a report nobody receives.

    Found by driving the real notifier rather than by reading the code: the
    store rejects every character below space, and bilingual mode joins its two
    labels with a newline, so the title raised on the way in and the whole
    message was dropped -- the same silent failure this fix exists to remove,
    one layer further out.  The title is therefore checked against the store's
    own rule rather than merely being non-empty.
    """
    monkeypatch.setattr(
        studio_copy.school_mode,
        "presentation_preferences",
        lambda _preferences: _Prefs(language_mode=mode),
    )
    result = editor_tools.confirm_pending(_canvas(_raised))

    assert result.ok is False
    assert len(recorded) == 1, f"nothing reached the notification store in {mode} mode"
    said = recorded[0]
    assert said.title.strip(), "the notification had no title"
    assert all(ord(character) >= 32 for character in said.title), (
        f"the {mode} title carries a control character the store rejects, so "
        f"the notification is dropped on the way in: {said.title!r}"
    )
    assert len(said.title) <= notifications.MAX_TEXT_LENGTH
    # The store is the real one apart from its final write, so this proves the
    # value it was handed would have been accepted rather than assuming it.
    notifications._text(said.title, "title")


def test_a_confirm_that_raises_outright_is_caught_and_reported(
    recorded: List[_Recorded],
) -> None:
    """A raise from ``confirm_paste`` itself must not leave a button handler.

    ``run_operation`` is what swallows; a confirm that fails before reaching it
    has nothing catching it, and the bridge is the last place that can turn it
    into a message instead of a traceback.
    """
    tool = _RaisingConfirm()
    canvas = _Canvas(_World(_History()))
    canvas.tools["Paste"] = tool

    result = editor_tools.confirm_pending(canvas)

    assert result.ok is False
    assert result.reason == "not-written"
    assert tool.calls == 1
    assert len(recorded) == 1 and recorded[0].severity == "error"


def test_a_world_with_no_history_is_reported_as_run_not_as_failed(
    recorded: List[_Recorded],
) -> None:
    """An unanswerable question is not a negative answer.

    A build whose level keeps no undo history cannot be asked whether the write
    landed.  Reporting failure there would break every caller on a world that is
    working perfectly well, so the bridge says the confirm ran and puts the
    doubt in the log instead of in the return value.
    """
    canvas = _canvas(_wrote, keep_history=False)
    result = editor_tools.confirm_pending(canvas)
    assert result.ok is True
    assert canvas.tools["Paste"].calls == 1
    assert recorded == []


def test_nothing_pending_is_refused_before_anything_is_called(
    recorded: List[_Recorded],
) -> None:
    """No paste tool holding anything means there is nothing to confirm."""
    canvas = _Canvas(_World(_History()))
    result = editor_tools.confirm_pending(canvas)
    assert result.ok is False
    assert result.reason == "nothing-pending"
    # A stale button, not a lost write: it says so without crying wolf.
    assert recorded and recorded[0].severity == "info"


def test_a_build_whose_paste_tool_has_no_confirm_is_refused(
    recorded: List[_Recorded],
) -> None:
    """The other guard that was already there, kept honest by a test."""
    canvas = _Canvas(_World(_History()))
    canvas.tools["Paste"] = _ToolWithoutConfirm()
    result = editor_tools.confirm_pending(canvas)
    assert result.ok is False
    assert result.reason == "no-confirm"
    assert recorded and recorded[0].severity == "error"


def test_the_undo_depth_reader_separates_zero_from_unanswerable() -> None:
    """``0`` and ``None`` mean different things and must stay different.

    A world with an empty undo stack answers zero; a canvas with no world at
    all answers nothing.  Collapsing the two would make a first-ever paste into
    an unverifiable one.
    """
    empty: List[Any] = []
    assert editor_tools._undo_depth(_Canvas(_World(_History(0)))) == 0
    assert editor_tools._undo_depth(_Canvas(_World(None))) is None
    assert editor_tools._undo_depth(object()) is None
    assert editor_tools._undo_depth(empty) is None


# ---------------------------------------------------------------------------
# what the tool itself reported, which the depth cannot see
# ---------------------------------------------------------------------------


def test_a_reported_failure_is_believed_over_the_undo_depth(
    recorded: List[_Recorded],
) -> None:
    """The reported outcome names the operation's own error; the depth cannot.

    Both routes refuse this paste, so ``reason`` alone proves nothing about
    which one answered -- the evidence is the *wording*.  The reported route
    quotes what the operation said; the inference can only quote the number it
    read.  Deleting the reported branch therefore leaves the refusal in place
    and silently swaps a real explanation for "the undo history is still at 0",
    which is how that branch shipped with no coverage.
    """
    canvas = _canvas(_raised, tool=_ReportingPasteTool)
    result = editor_tools.confirm_pending(canvas)

    assert result.ok is False, result
    assert result.reason == "not-written", result
    assert "could not read the source chunk" in result.message, (
        "the outcome the paste tool reported was thrown away and the undo depth "
        f"was guessed from instead: {result.message!r}"
    )
    assert "undo history is still" not in result.message, (
        "the depth inference answered even though the tool said why: "
        f"{result.message!r}"
    )
    assert canvas.tools["Paste"].calls == 1
    assert recorded and recorded[0].severity == "error", recorded


def test_a_paste_the_user_cancelled_is_not_reported_as_an_error(
    recorded: List[_Recorded],
) -> None:
    """The sharpest of the three, because the two routes disagree entirely.

    A silent abort and a broken paste both leave the undo depth where it was, so
    the inference has to call both of them an error -- and a red notification
    about a paste that did exactly what the user asked is a lie with a toast
    attached.  The reported outcome knows the difference.
    """
    canvas = _canvas(_aborted, tool=_ReportingPasteTool)
    result = editor_tools.confirm_pending(canvas)

    assert result.ok is False, "a cancel still means the blocks are not in"
    assert result.reason == "aborted", result
    assert canvas.tools["Paste"].calls == 1, "the confirm was never attempted"
    assert canvas.world.history_manager.undo_count == 0, (
        "precondition: the depth did not move, so an inference would call this "
        "a failure -- which is the thing being distinguished from"
    )
    assert recorded == [], (
        "the user's own cancel was reported to them as a failed paste: " f"{recorded}"
    )


def test_a_paste_whose_undo_point_was_lost_is_still_a_paste(
    recorded: List[_Recorded],
) -> None:
    """The misreport pointing the other way, and the worse direction.

    ``run_operation`` answers ``ok=True`` with ``no-undo-point`` when the blocks
    went in and only the history could not be written -- and that is by
    definition a write whose undo depth did not move.  Falling through to the
    inference told the user "Confirm placement wrote nothing" about a paste that
    is sitting in their world, sending them looking for blocks that are already
    there.
    """
    canvas = _canvas(_wrote, tool=_ReportingPasteTool, lose_undo_point=True)
    result = editor_tools.confirm_pending(canvas)

    assert canvas.world.history_manager.undo_count == 0, (
        "precondition: the depth must not move, or this test passes through the "
        "ordinary success path and proves nothing"
    )
    assert result.ok is True, (
        "a paste that wrote the world was reported as having written nothing, "
        f"because its undo point was lost: {result.message!r}"
    )
    assert result.reason == "no-undo-point", result
    assert len(recorded) == 1, f"a paste that cannot be undone said nothing: {recorded}"
    said = recorded[0]
    assert said.severity == "warning", (
        f"a successful paste was reported as {said.severity!r}; it worked, and "
        "the only news is that Undo will not take it back"
    )
    assert "Undo" in said.body, said.body


def test_a_reported_success_still_needs_the_write_to_have_landed() -> None:
    """The other half, so the three tests above cannot pass by always agreeing.

    A tool reporting an ordinary success is believed and the depth moved, which
    is the path a real paste takes every time.
    """
    canvas = _canvas(_wrote, tool=_ReportingPasteTool)
    result = editor_tools.confirm_pending(canvas)
    assert result.ok is True and result.reason == "", result
    assert canvas.world.history_manager.undo_count == 1


def test_every_reason_token_these_two_functions_return_is_documented(
    recorded: List[_Recorded],
) -> None:
    """``PASTE_OUTCOME_REASONS`` is a contract, so something has to read it.

    It shipped with no reader at all: nothing in the application and nothing in
    the tests mentioned it, so a token could be added to the tuple without a
    producer, or returned from the code without being documented, and neither
    would fail anything.

    Both directions are asserted because only one of them catches the failure
    that actually happens.  "Every token returned is documented" passes on a
    tuple that has grown a token nobody produces; "every documented token is
    returned" passes on a function that has quietly grown a new one.  The sets
    are equal or this is not a contract.
    """
    produced = set()

    def token(outcome: Any) -> None:
        if outcome.reason:
            produced.add(outcome.reason)

    # confirm_pending, one branch at a time
    token(editor_tools.confirm_pending(_Canvas(_World(_History()))))
    holdless = _Canvas(_World(_History()))
    holdless.tools["Paste"] = _ToolWithoutConfirm()
    token(editor_tools.confirm_pending(holdless))
    token(editor_tools.confirm_pending(_canvas(_raised, tool=_ReportingPasteTool)))
    token(editor_tools.confirm_pending(_canvas(_aborted, tool=_ReportingPasteTool)))
    token(
        editor_tools.confirm_pending(
            _canvas(_wrote, tool=_ReportingPasteTool, lose_undo_point=True)
        )
    )
    # and the successful one, whose reason is empty by convention
    assert editor_tools.confirm_pending(_canvas(_wrote)).reason == ""

    # cancel_pending
    token(editor_tools.cancel_pending(_canvas(_wrote)))
    token(editor_tools.cancel_pending(_Canvas(_World(_History()))))

    documented = set(editor_tools.PASTE_OUTCOME_REASONS)
    assert produced == documented, (
        "the tokens these functions return and the tokens the module documents "
        f"have drifted apart. Returned and undocumented: {sorted(produced - documented)}. "
        f"Documented and never returned: {sorted(documented - produced)}"
    )
    assert len(editor_tools.PASTE_OUTCOME_REASONS) == len(documented), (
        "the documented tuple repeats a token: " f"{editor_tools.PASTE_OUTCOME_REASONS}"
    )


# ---------------------------------------------------------------------------
# cancelling
# ---------------------------------------------------------------------------


def test_a_cancel_that_did_not_let_go_is_reported(recorded: List[_Recorded]) -> None:
    """The same lie, in the other direction.

    Reporting that the object was dropped when the tool is still holding it
    would hide the panel showing it while the copy stays drawn over the world.
    """
    canvas = _canvas(_wrote)
    result = editor_tools.cancel_pending(canvas)
    assert result.ok is False
    assert result.reason == "still-held"
    assert canvas.tools["Paste"].calls == 0, "cancelling must never paste"
    assert canvas.world.history_manager.undo_count == 0, "cancelling wrote to the world"
    assert recorded and recorded[0].severity == "error"


def test_a_cancel_with_nothing_held_is_already_where_it_was_going(
    recorded: List[_Recorded],
) -> None:
    """Holding nothing is the state Cancel exists to reach, so it is not a failure."""
    result = editor_tools.cancel_pending(_Canvas(_World(_History())))
    assert result.ok is True
    assert recorded == [], "an already-empty cancel must not report anything"


def test_an_outcome_is_still_a_plain_yes_or_no() -> None:
    """Callers that only want a boolean keep working, unchanged."""
    assert bool(editor_tools.Outcome(ok=True)) is True
    assert bool(editor_tools.Outcome(ok=False, reason="not-written")) is False
    assert not editor_tools.Outcome(ok=False)
    if editor_tools.Outcome(ok=True):
        return
    raise AssertionError("a successful outcome did not read as true")
