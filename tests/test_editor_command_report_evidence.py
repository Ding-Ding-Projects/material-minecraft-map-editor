"""What a delegated editor command is allowed to claim, and in what words.

Three defects sat behind one function each, and all three shipped green.

``_after_editor_command`` holds the undo-depth evidence check that stops the
shell announcing a change the world did not record.  The check asked
``key in _MUTATING_COMMANDS`` while the report it guards fired for ``key in
_MUTATING_COMMANDS or subject`` -- so ``runOperation``, the one command that
hands the world to an arbitrary plugin, walked past the check and reported that
an operation recording no undo point had "finished".  Measured in a real editor
on the shipped test world: undo depth 3 before and 3 after, severity
``success``.  Paste and delete, which differ only in being listed in that
tuple, said "nothing in it changed" at ``warning`` for the identical condition.

``_tool_message`` and ``_run_active_operation`` announced the operation's
*identifier* rather than its name.  The identifier is a dotted module path, so
pressing Export told the user "The selected exporter is
amulet_map_editor.programs.edit.plugins.operations.stock_plugins.
export_operations.construction."  ``BaseOperationChoiceToolUI`` exposes
``active_operation_name`` for exactly this and says so in its own docstring.

``_cmd_set_dimension`` reported ``success`` and the sentence "No 3D editor is
attached, so the renderer did not move" whenever the switch had not happened --
including when an editor *was* attached and had just refused it.  Measured: a
live ``EditCanvas`` raising from its ``dimension`` setter produced "Editing
minecraft:the_nether. ... No 3D editor is attached", while both the renderer
and Studio stayed on ``minecraft:overworld``.

The functions are exercised against a stand-in ``self`` rather than a built
frame: the defect is entirely in these branches, and the wiring around them was
verified separately by driving the real editor.  Every one of these tests was
watched failing against the code as it shipped before being kept.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import pytest

from amulet_map_editor.api.studio import context_menu
from amulet_map_editor.api.studio.shell import (
    _MUTATING_COMMANDS,
    _REPORTED_COMMANDS,
    StudioShell,
)


class _Recorder:
    """The smallest ``self`` these four methods actually reach for."""

    doc_title = "test world"
    project_path = "/tmp/test-world"

    def __init__(self, before: Tuple[int, int], after: Tuple[int, int]) -> None:
        self._counts = [before, after]
        self.said: List[Dict[str, str]] = []
        self.recorded: List[Tuple[str, Dict[str, Any]]] = []

    # -- what the methods under test call ---------------------------------
    def _history_counts(self) -> Tuple[int, int]:
        """The depth *after* the command; the before value is passed in."""
        return self._counts[1]

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
        return (((0, 0, 0), (1, 1, 1)),)

    def _dimension_name(self) -> str:
        return "minecraft:overworld"

    #: The format the ribbon is holding, for the export toast below.  The real
    #: lookup is bound rather than stubbed, because which exporter a format
    #: names is part of what that toast has to get right.
    ribbon_format = "construction"

    def _ribbon_value(self, label: str) -> str:
        return self.ribbon_format if label == "Format" else ""

    _export_operation = StudioShell._export_operation
    _shown_operation_name = StudioShell._shown_operation_name


def _report(before: int, after: int, key: str, subject: str = "") -> Dict[str, str]:
    """Run the real ``_after_editor_command`` and return the one toast it raised."""
    stub = _Recorder((before, 0), (after, 0))
    StudioShell._after_editor_command(stub, key, (before, 0), subject=subject)
    assert len(stub.said) == 1, (
        f"{key!r} raised {len(stub.said)} notifications, so this test cannot say "
        "which one it is asserting about"
    )
    return stub.said[0]


# ---------------------------------------------------------------------------
# the evidence check
# ---------------------------------------------------------------------------


def test_an_operation_that_recorded_nothing_does_not_report_success() -> None:
    """The defect itself: ``runOperation`` with an unchanged undo depth.

    A plugin that silently did nothing -- or one whose exception
    ``EditCanvas.run_operation`` swallowed, which it does for every exception
    when ``throw_exceptions`` is false -- must not be announced as finished.
    """
    said = _report(3, 3, "runOperation", subject="Clone")
    assert said["severity"] == "warning", (
        "an operation that recorded no undo point was reported as "
        f"{said['severity']!r}: {said['body']!r}"
    )
    assert "nothing in it changed" in said["body"]
    assert "Clone" in said["body"], (
        "the warning should name the operation that did nothing, so the user "
        f"knows which one to look at: {said['body']!r}"
    )


def test_an_operation_that_recorded_an_undo_point_still_reports_success() -> None:
    """The other half, so the fix cannot be "always warn"."""
    said = _report(3, 4, "runOperation", subject="Clone")
    assert said["severity"] == "success", said
    assert "finished" in said["body"]


@pytest.mark.parametrize("key", ("paste", "delete", "cut", "createChunks"))
def test_a_mutating_command_keeps_its_evidence_check(key: str) -> None:
    """The commands the check already covered are still covered."""
    said = _report(2, 2, key)
    assert said["severity"] == "warning", said
    assert "nothing in it changed" in said["body"]


def test_the_check_and_the_report_ask_the_same_question() -> None:
    """No input may reach the success branch without moving the undo depth.

    This is the shape of the original defect rather than one instance of it:
    two conditions written differently, one guarding the other.  Asserting the
    pairing directly means a future edit that widens the report without
    widening the check fails here.

    The keys are derived rather than written out, so a command added to
    ``_MUTATING_COMMANDS`` is covered without anyone remembering to add it
    here.  ``_REPORTED_COMMANDS`` comes back out because those return from a
    branch of their own before this one is reached and answer from evidence
    that is not the undo depth -- Reload plugins from the operation list, for
    instance.  (Copy answers from the clipboard, but no longer here: its report
    is raised by ``EditCanvas.copy``, which is the layer the Select tool's Copy
    button and the editor's Ctrl+C share with this shell's own command.)
    ``runOperation`` is added because it is not a mutating
    command and reaches this branch anyway, through its subject, which is
    exactly how the original defect got in.
    """
    generic = sorted(set(_MUTATING_COMMANDS) - set(_REPORTED_COMMANDS))
    generic.append("runOperation")
    assert len(generic) >= 8, (
        "almost nothing reaches the generic report any more, so this test is "
        f"asserting about an empty loop: {generic}"
    )
    for key in generic:
        for subject in ("", "Clone"):
            stub = _Recorder((5, 0), (5, 0))
            StudioShell._after_editor_command(stub, key, (5, 0), subject=subject)
            # Saying nothing is allowed -- a command that neither mutates nor
            # names a subject has nothing to report.  Claiming success is not.
            for said in stub.said:
                assert said["severity"] != "success", (
                    f"{key!r} with subject {subject!r} claimed success while the "
                    f"world recorded no new undo point: {said['body']!r}"
                )


# ---------------------------------------------------------------------------
# what the user is shown instead of a module path
# ---------------------------------------------------------------------------


class _Tool:
    """An operation chooser, answering both the name and the identifier.

    The name is the construction plugin's own ``export["name"]``, tab and all.
    An earlier version of this stub answered ``"construction (.construction)"``
    -- the *dropdown's* label -- which no chooser has ever shown, and which made
    this test agree with a message the running application could not produce.
    """

    active_operation_name = "\tExport Construction"
    active_operation_id = (
        "amulet_map_editor.programs.edit.plugins.operations.stock_plugins."
        "export_operations.construction"
    )


def test_the_export_toast_names_the_format_not_a_python_module() -> None:
    stub = _Recorder((0, 0), (0, 0))
    message = StudioShell._tool_message(stub, "export", "Export", _Tool())
    assert "construction (.construction)" in message, message
    assert "amulet_map_editor." not in message, (
        "the export toast is showing the operation's dotted module path, which "
        f"is not what the user picked from a list: {message!r}"
    )


def test_the_export_toast_still_names_something_without_a_name() -> None:
    """A tool exposing only the identifier is named by it rather than not at all."""

    class _Older:
        active_operation_id = "some.module.path"

    stub = _Recorder((0, 0), (0, 0))
    message = StudioShell._tool_message(stub, "export", "Export", _Older())
    assert "some.module.path" in message, message


def test_the_export_toast_names_the_format_the_user_actually_chose() -> None:
    """Not the exporter the tool happened to be on, which is what it said.

    The chooser is showing Construction and the ribbon is holding ``schem``.
    The old message read that chooser and reported "Export Construction" as a
    success, which is exactly how three of the four formats shipped announcing
    a file they were not writing.
    """
    stub = _Recorder((0, 0), (0, 0))
    stub.ribbon_format = "schem"
    message = StudioShell._tool_message(stub, "export", "Export", _Tool())
    assert "Sponge schem (.schem)" in message, message
    assert "Export Sponge Schematic" in message, message
    assert "Export Construction" in message, (
        "a tool left on a different exporter must say which one it is showing "
        f"rather than only which one was asked for: {message!r}"
    )


# ---------------------------------------------------------------------------
# a refused dimension switch
# ---------------------------------------------------------------------------


def test_a_refused_dimension_switch_is_not_a_success(monkeypatch) -> None:
    """An attached editor that raised must not be reported as absent.

    Driven for real before this was written: the toast read "Editing
    minecraft:the_nether. ... No 3D editor is attached, so the renderer did not
    move." at severity ``success``, with ``EditCanvas`` attached and both the
    renderer and Studio still on ``minecraft:overworld``.
    """
    import amulet_map_editor.api.studio.shell as shell_module

    class _Refusing:
        @property
        def dimension(self) -> str:
            return "minecraft:overworld"

        @dimension.setter
        def dimension(self, value: str) -> None:
            raise RuntimeError("the renderer is rebuilding")

    class _Project:
        dimensions = ("minecraft:overworld", "minecraft:the_nether")

        @staticmethod
        def dimension_named(name: str) -> None:
            return None

    monkeypatch.setattr(shell_module.context, "current", lambda: _Project())
    monkeypatch.setattr(shell_module.context, "set_dimension", lambda value: None)

    class _Stub(_Recorder):
        _dimension_key = staticmethod(StudioShell._dimension_key)

        def _ribbon_dimension(self) -> str:
            return "minecraft:the_nether"

        def _canvas(self) -> Any:
            return _Refusing()

        def _select_navigator_dimension(self, target: str) -> None:
            return None

    stub = _Stub((0, 0), (0, 0))
    StudioShell._cmd_set_dimension(stub, "setDimension")
    assert stub.said, "a refused dimension switch said nothing at all"
    said = stub.said[-1]
    assert (
        said["severity"] != "success"
    ), f"a refused dimension switch reported {said['severity']!r}: {said['body']!r}"
    assert "No 3D editor is attached" not in said["body"], (
        "an attached editor that refused the switch was reported as absent: "
        f"{said['body']!r}"
    )
    assert "minecraft:the_nether" in said["body"], said["body"]


# ---------------------------------------------------------------------------
# the keys the viewport menu teaches
# ---------------------------------------------------------------------------

#: Each viewport row backed by a 3D editor action, and that action.
_ROWS_WITH_ACTIONS = {
    "Inspect block": "ACT_INSPECT_BLOCK",
    "Add selection box here": "ACT_BOX_CLICK_ADD",
    "Deselect active box": "ACT_DESELECT_BOX",
    "Deselect all boxes": "ACT_DESELECT_ALL_BOXES",
    "Toggle projection": "ACT_CHANGE_PROJECTION",
}


def test_the_viewport_menu_prints_the_keys_the_editor_listens_for() -> None:
    """A menu is where a shortcut is learnt, so a wrong one teaches a habit.

    Measured against the shipped key group before this was written: the menu
    offered ``Esc`` for "Deselect active box" (bound to ``Ctrl+D``), ``P`` for
    "Toggle projection" (bound to ``Tab``) and ``RMB`` for "Inspect block"
    (bound to ``Alt``).
    """
    rows = {item.label: item.accel for item in context_menu._viewport_menu()}
    missing = sorted(set(_ROWS_WITH_ACTIONS) - set(rows))
    assert not missing, (
        "these rows are named by this test but are no longer in the viewport "
        f"menu, so the rule silently stopped covering them: {missing}"
    )
    wrong = {}
    for label, action in _ROWS_WITH_ACTIONS.items():
        live = context_menu.viewport_accelerator(action)
        if rows[label] != live:
            wrong[label] = (rows[label], live)
    assert not wrong, (
        "these viewport rows print a key the 3D editor is not bound to "
        f"(row: shown, really bound): {wrong}"
    )


def test_the_live_binding_lookup_is_actually_answering() -> None:
    """Without this, the rule above passes on a lookup that returns nothing.

    ``viewport_accelerator`` returns an empty string for anything it cannot
    read, and the menu would then draw empty accelerators -- which would match
    an empty lookup on every row and prove nothing at all.
    """
    answered = {
        action: context_menu.viewport_accelerator(action)
        for action in _ROWS_WITH_ACTIONS.values()
    }
    blank = sorted(action for action, key in answered.items() if not key)
    assert not blank, (
        "the live keybind lookup answered nothing for these actions, so the "
        f"comparison above is vacuous: {blank}"
    )
