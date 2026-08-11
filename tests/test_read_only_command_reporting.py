"""A read-only editor command has to say what it did, from wherever it is run.

``_after_editor_command`` reported through one route: a command listed in
``_MUTATING_COMMANDS``, or one carrying a named ``subject``, got a sentence
about the world's undo depth.  Anything else fell off the end of the function
and the user was told nothing.

Two commands did exactly that, and both are ones whose whole result is
invisible in the viewport.  Measured in a real editor on the shipped test
world: pressing Copy produced **zero** notifications at any severity, and so
did Reload plugins.  A copy that filled the clipboard and a copy that failed to
were therefore indistinguishable from the interface -- and Copy is the one
command where there is nothing on screen to look at afterwards.

Adding them to ``_MUTATING_COMMANDS`` would have been the wrong fix twice over:
neither writes to the world, so both would have been answered with "the world
recorded no new undo point, so nothing in it changed" -- a warning, about a
command that had just worked perfectly.  Their evidence is not undo depth.  It
is the clipboard for Copy and the loaded operation list for Reload plugins.

**And the first fix put Copy's report in the wrong layer.**
``_after_editor_command`` runs only for a command the *shell* routed, and two
shipped controls call ``EditCanvas.copy`` directly and never reach it: the
Select tool's own Copy button, and the 3D editor's Edit ▸ Copy / Ctrl+C.
Measured on a running editor with an isolated ``CONFIG_DIR``, both moved the
clipboard and raised zero notifications at any severity -- so the defect still
reproduced from the two places most people press Copy.  The report lives on
``EditCanvas.copy`` now, which is the one layer all three routes share, and
this module tests it there.  ``tests/test_copy_is_read_only_runtime.py`` drives
the real controls and is the proof that the wiring is live; these are the
branch-by-branch assertions about what each outcome says.

The audit at the end is the part that survives the next command being added.
It reads the shell's *real* routing table -- ``_build_handlers`` run against a
stand-in that records which method each key was routed to -- and requires every
key that reaches ``_cmd_editor`` to be a mutating command, a named member of
``_REPORTED_COMMANDS``, or a named member of ``_EDITOR_REPORTED_COMMANDS``.  A
new editor action wired up without a report fails here rather than shipping
silent.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import pytest

from amulet_map_editor.api.studio.shell import (
    _EDITOR_ACTIONS,
    _EDITOR_REPORTED_COMMANDS,
    _MUTATING_COMMANDS,
    _REPORTED_COMMANDS,
    StudioShell,
)

wx = pytest.importorskip("wx", reason="wxPython is not installed in this environment")

from amulet_map_editor.programs.edit.api.canvas import edit_canvas  # noqa: E402
from amulet_map_editor.programs.edit.api.canvas.edit_canvas import (  # noqa: E402
    EditCanvas,
    OperationOutcome,
)

# ---------------------------------------------------------------------------
# copy, on the canvas, which is where every control reaches it
# ---------------------------------------------------------------------------


class _Clipboard:
    """Stands in for ``structure_cache``, which only ``len`` is asked about."""

    def __init__(self, size: int) -> None:
        self.size = size

    def __len__(self) -> int:
        return self.size


class _Canvas:
    """The smallest ``self`` ``EditCanvas._report_copy`` reaches for.

    The method itself is borrowed from the real class rather than
    reimplemented, so what runs here is the shipped wording and the shipped
    severity choices.
    """

    _report_copy = EditCanvas._report_copy

    def __init__(self, dimension: str = "minecraft:overworld") -> None:
        self.dimension = dimension


def _copy_report(
    monkeypatch: pytest.MonkeyPatch,
    *,
    before: int = 0,
    after: int = 1,
    copied: Optional[Tuple[int, int]] = (4096, 1),
    outcome: Optional[OperationOutcome] = None,
    dimension: str = "minecraft:overworld",
) -> List[Dict[str, str]]:
    """Run the real ``_report_copy`` and return every toast it raised."""
    said: List[Dict[str, str]] = []

    def _notify(
        _parent: Any, title: Any, body: Any, *, severity: str = "info", **_kwargs: Any
    ) -> None:
        said.append({"title": str(title), "body": str(body), "severity": str(severity)})

    monkeypatch.setattr(edit_canvas, "notify", _notify)
    monkeypatch.setattr(edit_canvas, "structure_cache", _Clipboard(after))
    monkeypatch.setattr(edit_canvas, "_copied_structure", lambda: copied)
    # ``outcome if outcome is not None`` rather than ``outcome or``:
    # ``OperationOutcome`` defines ``__bool__``, so every outcome this helper
    # exists to pass in is falsy and ``or`` quietly swapped each one for the
    # successful default.  Both failure tests below passed against code that
    # never saw their outcome at all.
    EditCanvas._report_copy(
        _Canvas(dimension),
        before,
        outcome if outcome is not None else OperationOutcome(ok=True),
    )
    return said


def _one(said: List[Dict[str, str]]) -> Dict[str, str]:
    assert len(said) == 1, (
        f"copying raised {len(said)} notifications, so this test cannot say "
        f"which one it is asserting about: {said}"
    )
    return said[0]


def test_copying_says_how_much_reached_the_clipboard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The defect: Copy said nothing, so a failed copy looked like a good one."""
    said = _one(_copy_report(monkeypatch))
    assert said["severity"] == "success", said
    assert "4,096" in said["body"], (
        "the copy report does not say how many blocks were copied, which is the "
        f"only fact about a copy the user cannot see: {said['body']!r}"
    )
    assert "minecraft:overworld" in said["body"], said["body"]
    # The dimension named has to be the one in the world.  Reading it off the
    # clipboard entry instead produced "copied from main", because every
    # extracted structure calls its single dimension ``"main"``.
    assert " main" not in said["body"], (
        "the copy report is naming the structure's own internal dimension key "
        f"rather than a dimension of the world: {said['body']!r}"
    )


def test_one_block_is_reported_as_one_block(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 1x1x1 box is the smallest real copy, and the commonest one.

    It read "1 blocks in 1 box ... are on the clipboard", which is the sentence
    a user meets the very first time they press Ctrl+C on a fresh selection.
    """
    said = _one(_copy_report(monkeypatch, copied=(1, 1)))
    assert "1 block in 1 box" in said["body"], said["body"]
    assert "is on the clipboard" in said["body"], said["body"]


def test_many_blocks_keep_the_plural(monkeypatch: pytest.MonkeyPatch) -> None:
    """The other half, so the fix cannot be "always singular"."""
    said = _one(_copy_report(monkeypatch, copied=(4096, 2)))
    assert "4,096 blocks in 2 boxes" in said["body"], said["body"]
    assert "are on the clipboard" in said["body"], said["body"]


def test_a_copy_that_reached_nothing_is_not_reported_as_a_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Evidence, not prediction: the clipboard has to have actually grown.

    ``EditCanvas.run_operation`` contains the operation's exception, so "the
    method was called" says nothing about whether a structure was produced.
    """
    said = _one(_copy_report(monkeypatch, before=1, after=1))
    assert said["severity"] == "warning", (
        "a copy that put nothing on the clipboard was reported as "
        f"{said['severity']!r}: {said['body']!r}"
    )
    assert "clipboard" in said["body"].lower(), said["body"]


def test_a_copy_whose_structure_cannot_be_measured_still_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A clipboard that grew but cannot be read is reported honestly."""
    said = _one(_copy_report(monkeypatch, copied=None))
    assert said["severity"] != "success", said
    assert said["body"], said


def test_the_copy_report_does_not_claim_the_world_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Copy writes nothing, so its report must not talk about undo depth.

    The generic branch's sentence -- "... is now N undo points deep" -- would be
    describing a write that never happened.
    """
    said = _one(_copy_report(monkeypatch))
    assert "undo" not in said["body"].lower(), (
        "the copy report is describing the world's undo depth, and copying "
        f"does not touch it: {said['body']!r}"
    )


def test_a_copy_that_raised_is_not_reported_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``_run_operation`` has already put the failure on screen.

    Adding "nothing reached the clipboard" underneath a red "Operation failed"
    is the same event reported twice, and the second sentence is the less
    useful one.
    """
    said = _copy_report(
        monkeypatch,
        before=1,
        after=1,
        outcome=OperationOutcome(ok=False, reason="raised", message="boom"),
    )
    assert said == [], (
        "a copy whose operation raised was reported a second time here, on top "
        f"of the failure _run_operation had already shown: {said}"
    )


def test_a_cancelled_copy_is_still_told_it_copied_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pair to the test above, so "never report" would not pass both.

    Cancelling the progress row is not a failure, so ``_run_operation`` says
    nothing about it -- which leaves this the only thing that will.
    """
    said = _one(
        _copy_report(
            monkeypatch,
            before=1,
            after=1,
            outcome=OperationOutcome(ok=False, reason="aborted", message=""),
        )
    )
    assert said["severity"] == "warning", said
    assert "clipboard" in said["body"].lower(), said["body"]


# ---------------------------------------------------------------------------
# the wiring: copy() actually calls the report
# ---------------------------------------------------------------------------


class _CopyingCanvas:
    """``EditCanvas.copy`` with only ``_lift`` stood in for.

    The precondition for every assertion above: they exercise ``_report_copy``
    directly, so on their own they would all still pass if ``copy`` stopped
    calling it -- which is exactly the shape of the defect being fixed, one
    layer along.
    """

    copy = EditCanvas.copy

    def __init__(self) -> None:
        self.world = None
        self.dimension = "minecraft:overworld"
        self.selection = None
        self.reports: List[Tuple[int, OperationOutcome]] = []

    def _lift(self, _operation: Any, rollback_on_error: Any = None) -> OperationOutcome:
        self.rollback_on_error = rollback_on_error
        return OperationOutcome(ok=True)

    def _report_copy(self, before: int, outcome: OperationOutcome) -> None:
        self.reports.append((before, outcome))


def test_copy_reports_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(edit_canvas, "structure_cache", _Clipboard(0))
    canvas = _CopyingCanvas()
    canvas.copy()
    assert len(canvas.reports) == 1, (
        "EditCanvas.copy did not report what it copied, so every control that "
        f"calls it directly is silent again: {canvas.reports}"
    )


def test_copy_still_refuses_the_rollback(monkeypatch: pytest.MonkeyPatch) -> None:
    """The other half of the defect, asserted where the answer is chosen."""
    monkeypatch.setattr(edit_canvas, "structure_cache", _Clipboard(0))
    canvas = _CopyingCanvas()
    canvas.copy()
    assert canvas.rollback_on_error is edit_canvas._copy_never_rolls_back, (
        "copy stopped refusing run_operation's rollback, so a read-only action "
        "is marking the selection changed again"
    )
    assert canvas.rollback_on_error() is False


def test_an_internal_copy_does_not_announce_itself(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rotate floats a copy of the selection; that is not a copy the user made.

    Without this, pressing Rotate would put "4,096 blocks are on the clipboard"
    on screen, describing an internal step as though it were the action.
    """
    monkeypatch.setattr(edit_canvas, "structure_cache", _Clipboard(0))
    canvas = _CopyingCanvas()
    canvas.copy(report=False)
    assert canvas.reports == [], canvas.reports


# ---------------------------------------------------------------------------
# reload plugins, which the shell does answer for
# ---------------------------------------------------------------------------


class _Recorder:
    """The smallest ``self`` the shell's reporting branches reach for."""

    doc_title = "test world"
    project_path = "/tmp/test-world"

    _report_plugin_reload = StudioShell._report_plugin_reload

    def __init__(
        self,
        *,
        counts: Tuple[int, int] = (2, 0),
        operations: Optional[Tuple[str, ...]] = ("Clone", "Fill", "Replace"),
    ) -> None:
        self._counts = counts
        self._operations = operations
        self.said: List[Dict[str, str]] = []
        self.recorded: List[Tuple[str, Dict[str, Any]]] = []

    # -- what the method under test calls ---------------------------------
    def _history_counts(self) -> Tuple[int, int]:
        return self._counts

    def notify(self, title: Any, body: Any, severity: str = "info") -> None:
        self.said.append(
            {"title": str(title), "body": str(body), "severity": str(severity)}
        )

    def _record(self, key: str, payload: Dict[str, Any]) -> None:
        self.recorded.append((key, payload))

    def _level(self) -> Any:
        return None

    def _sync_world_state(self) -> None:
        return None

    def _selection_corners(self) -> Tuple[Any, ...]:
        return (((0, 0, 0), (16, 16, 16)),)

    def _dimension_name(self) -> str:
        return "minecraft:overworld"

    def _loaded_operation_names(self) -> Optional[Tuple[str, ...]]:
        return self._operations


def _report(key: str, **kwargs: Any) -> Dict[str, str]:
    """Run the real ``_after_editor_command`` and return its single toast."""
    before = kwargs.pop("before", (2, 0))
    stub = _Recorder(**kwargs)
    StudioShell._after_editor_command(stub, key, before)
    assert len(stub.said) == 1, (
        f"{key!r} raised {len(stub.said)} notifications, so this test cannot "
        f"say which one it is asserting about: {stub.said}"
    )
    return stub.said[0]


def test_reloading_plugins_says_how_many_operations_came_back() -> None:
    said = _report("reloadPlugins")
    assert said["severity"] == "success", said
    assert "3" in said["body"], (
        "the reload report does not say how many operations are available, "
        f"which is the whole visible result of a reload: {said['body']!r}"
    )


def test_a_reload_that_found_no_operations_is_a_warning() -> None:
    said = _report("reloadPlugins", operations=())
    assert said["severity"] == "warning", said


def test_a_reload_that_could_not_be_measured_does_not_claim_a_count() -> None:
    said = _report("reloadPlugins", operations=None)
    assert said["severity"] != "success", said
    assert said["body"], said


def test_the_shell_stays_quiet_about_a_command_the_editor_reports() -> None:
    """One Ctrl+C must not raise two toasts.

    The shell records and re-reads the world for every delegated command; what
    it must not do for these is speak, because the editor's own method already
    has -- from evidence this layer cannot see.
    """
    for key in _EDITOR_REPORTED_COMMANDS:
        stub = _Recorder()
        StudioShell._after_editor_command(stub, key, (2, 0))
        assert stub.said == [], (
            f"{key!r} is reported by the editor's own method and the shell "
            f"reported it as well, so one action raises two toasts: {stub.said}"
        )
        assert stub.recorded, (
            f"{key!r} was not recorded in the shell's history, which is the "
            "half of this function that still has to run"
        )


# ---------------------------------------------------------------------------
# the audit: nothing the shell delegates to the editor stays silent
# ---------------------------------------------------------------------------


class _Routes:
    """A ``self`` whose only job is to name the method each command routes to.

    ``_build_handlers`` is read rather than re-derived here on purpose: a table
    of expected routes written in this file would agree with itself forever and
    say nothing about the shell.
    """

    def __getattr__(self, name: str) -> str:
        if name.startswith("_cmd_"):
            return name
        raise AttributeError(name)


def _editor_routed_commands() -> Tuple[str, ...]:
    handlers = StudioShell._build_handlers(_Routes())
    return tuple(
        sorted(key for key, route in handlers.items() if route == "_cmd_editor")
    )


def test_the_routing_table_still_sends_commands_to_the_editor() -> None:
    """The precondition for the audit below, which is vacuous without it."""
    routed = _editor_routed_commands()
    assert len(routed) >= 8, (
        "almost nothing routes to the editor, so the audit below is checking "
        f"an empty set: {routed}"
    )
    for expected in ("copy", "cut", "paste", "undo", "reloadPlugins"):
        assert expected in routed, (
            f"{expected!r} no longer reaches _cmd_editor, so this audit is not "
            f"looking at the commands it thinks it is: {routed}"
        )


def test_no_delegated_editor_command_reports_nothing() -> None:
    """Every command reaching ``_after_editor_command`` has a way to speak.

    Copy and Reload plugins are the two that did not, and the failure mode is
    the reason this is a list rather than a rule: a command that reports nothing
    raises no error, fails no other test, and looks from every angle except the
    running application exactly like one that reports correctly.
    """
    silent = [
        key
        for key in _editor_routed_commands()
        if key not in _MUTATING_COMMANDS
        and key not in _REPORTED_COMMANDS
        and key not in _EDITOR_REPORTED_COMMANDS
    ]
    assert not silent, (
        "these commands are handed to the world editor and then say nothing at "
        f"all about what happened: {silent}"
    )


def test_a_command_the_editor_reports_names_a_method_that_reports() -> None:
    """``_EDITOR_REPORTED_COMMANDS`` is a claim about the editor, so check it.

    Without this the tuple is a way to opt a command out of the audit above by
    naming it, which is the opposite of what it is for.  The method the routing
    table actually calls is resolved on the real ``EditCanvas`` and has to
    accept ``report`` -- the parameter that exists only because the method
    reports.
    """
    import inspect

    assert _EDITOR_REPORTED_COMMANDS, "the tuple is empty, so this proves nothing"
    for key in _EDITOR_REPORTED_COMMANDS:
        action = _EDITOR_ACTIONS[key]
        method = None
        for name in action.names:
            method = getattr(EditCanvas, name, None)
            if method is not None:
                break
        assert method is not None, (
            f"{key!r} names {action.names} and EditCanvas has none of them, so "
            "nothing is reporting for it"
        )
        parameters = inspect.signature(method).parameters
        assert "report" in parameters, (
            f"EditCanvas.{action.names[0]} takes no 'report' parameter, so it "
            f"is not the method that reports for {key!r}"
        )


def test_every_reported_command_is_one_the_editor_is_actually_given() -> None:
    """The inverse, so the list cannot be padded to make the audit pass."""
    routed = set(_editor_routed_commands())
    stale = [
        key
        for key in _REPORTED_COMMANDS + _EDITOR_REPORTED_COMMANDS
        if key not in routed
    ]
    assert not stale, (
        "_REPORTED_COMMANDS names commands that never reach "
        f"_after_editor_command, so listing them proves nothing: {stale}"
    )


def test_a_reported_command_is_not_also_claimed_to_mutate() -> None:
    """``undo`` and ``redo`` are both, and every other overlap is a mistake.

    A command in both tuples returns from its own branch before the undo-depth
    report can run, so listing it as mutating is a claim nothing acts on.
    """
    overlap = sorted(
        set(_REPORTED_COMMANDS + _EDITOR_REPORTED_COMMANDS) & set(_MUTATING_COMMANDS)
    )
    assert overlap == ["redo", "undo"], (
        "a command is listed as both mutating and separately reported, which "
        f"means one of those two tuples is describing it wrongly: {overlap}"
    )


def test_the_two_reporting_tuples_do_not_overlap() -> None:
    """A command reported in both places is one action with two toasts."""
    overlap = sorted(set(_REPORTED_COMMANDS) & set(_EDITOR_REPORTED_COMMANDS))
    assert not overlap, (
        "these commands are claimed to be reported by the shell and by the "
        f"editor, which is how one Ctrl+C comes to raise two toasts: {overlap}"
    )


@pytest.mark.parametrize("key", sorted(_EDITOR_ACTIONS))
def test_each_editor_action_is_accounted_for(key: str) -> None:
    """Named one by one, so a red run says which command went silent."""
    handlers = StudioShell._build_handlers(_Routes())
    if handlers.get(key) != "_cmd_editor":
        pytest.skip(f"{key!r} is handled by {handlers.get(key)!r}, not _cmd_editor")
    assert (
        key in _MUTATING_COMMANDS
        or key in _REPORTED_COMMANDS
        or key in _EDITOR_REPORTED_COMMANDS
    ), f"{key!r} is delegated to the world editor and then reports nothing"
