"""No editor command the shell delegates is allowed to say nothing at all.

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
is the clipboard for Copy and the loaded operation list for Reload plugins, and
each now reports from the thing it actually did.

The audit at the end is the part that survives the next command being added.
It reads the shell's *real* routing table -- ``_build_handlers`` run against a
stand-in that records which method each key was routed to -- and requires every
key that reaches ``_cmd_editor`` to be either a mutating command or a named
member of ``_REPORTED_COMMANDS``.  A new editor action wired up without a
report fails here rather than shipping silent.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import pytest

from amulet_map_editor.api.studio.shell import (
    _EDITOR_ACTIONS,
    _MUTATING_COMMANDS,
    _REPORTED_COMMANDS,
    StudioShell,
)


class _Recorder:
    """The smallest ``self`` the reporting branches actually reach for.

    The two report methods are borrowed from the real class rather than
    reimplemented, so what runs here is the shell's own wording and its own
    severity choices.  Only the three *data sources* below are stand-ins --
    the clipboard, the copied structure, and the loaded operation list -- which
    is the part a test cannot supply from a world it never opened.
    """

    doc_title = "test world"
    project_path = "/tmp/test-world"

    _report_copy = StudioShell._report_copy
    _report_plugin_reload = StudioShell._report_plugin_reload

    def __init__(
        self,
        *,
        counts: Tuple[int, int] = (2, 0),
        clipboard: int = 1,
        copied: Optional[Tuple[int, int]] = (4096, 1),
        operations: Optional[Tuple[str, ...]] = ("Clone", "Fill", "Replace"),
    ) -> None:
        self._counts = counts
        self._clipboard = clipboard
        self._copied = copied
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

    def _clipboard_size(self) -> int:
        return self._clipboard

    def _copied_structure(self) -> Optional[Tuple[int, int]]:
        return self._copied

    def _loaded_operation_names(self) -> Optional[Tuple[str, ...]]:
        return self._operations


def _report(key: str, **kwargs: Any) -> Dict[str, str]:
    """Run the real ``_after_editor_command`` and return its single toast."""
    before = kwargs.pop("before", (2, 0))
    clipboard_before = kwargs.pop("clipboard_before", 0)
    stub = _Recorder(**kwargs)
    StudioShell._after_editor_command(
        stub, key, before, clipboard_before=clipboard_before
    )
    assert len(stub.said) == 1, (
        f"{key!r} raised {len(stub.said)} notifications, so this test cannot "
        f"say which one it is asserting about: {stub.said}"
    )
    return stub.said[0]


# ---------------------------------------------------------------------------
# copy
# ---------------------------------------------------------------------------


def test_copying_says_how_much_reached_the_clipboard() -> None:
    """The defect: Copy said nothing, so a failed copy looked like a good one."""
    said = _report("copy")
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


def test_one_block_is_reported_as_one_block() -> None:
    """A 1x1x1 box is the smallest real copy, and the commonest one.

    It read "1 blocks in 1 box ... are on the clipboard", which is the sentence
    a user meets the very first time they press Ctrl+C on a fresh selection.
    """
    said = _report("copy", copied=(1, 1))
    assert "1 block in 1 box" in said["body"], said["body"]
    assert "is on the clipboard" in said["body"], said["body"]


def test_many_blocks_keep_the_plural() -> None:
    """The other half, so the fix cannot be "always singular"."""
    said = _report("copy", copied=(4096, 2))
    assert "4,096 blocks in 2 boxes" in said["body"], said["body"]
    assert "are on the clipboard" in said["body"], said["body"]


def test_a_copy_that_reached_nothing_is_not_reported_as_a_success() -> None:
    """Evidence, not prediction: the clipboard has to have actually grown.

    ``EditCanvas.run_operation`` swallows the operation's exception when
    ``throw_exceptions`` is false, so "the method was called" says nothing
    about whether a structure was produced.
    """
    said = _report("copy", clipboard_before=1, clipboard=1)
    assert said["severity"] == "warning", (
        "a copy that put nothing on the clipboard was reported as "
        f"{said['severity']!r}: {said['body']!r}"
    )
    assert "clipboard" in said["body"].lower(), said["body"]


def test_a_copy_whose_structure_cannot_be_measured_still_says_so() -> None:
    """A clipboard that grew but cannot be read is reported honestly."""
    said = _report("copy", copied=None)
    assert said["severity"] != "success", said
    assert said["body"], said


def test_the_copy_report_does_not_claim_the_world_changed() -> None:
    """Copy writes nothing, so its report must not talk about undo depth.

    The generic branch's sentence -- "... is now N undo points deep" -- would be
    describing a write that never happened.
    """
    said = _report("copy")
    assert "undo" not in said["body"].lower(), (
        "the copy report is describing the world's undo depth, and copying "
        f"does not touch it: {said['body']!r}"
    )


# ---------------------------------------------------------------------------
# reload plugins
# ---------------------------------------------------------------------------


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
        if key not in _MUTATING_COMMANDS and key not in _REPORTED_COMMANDS
    ]
    assert not silent, (
        "these commands are handed to the world editor and then say nothing at "
        f"all about what happened: {silent}"
    )


def test_every_reported_command_is_one_the_editor_is_actually_given() -> None:
    """The inverse, so the list cannot be padded to make the audit pass."""
    routed = set(_editor_routed_commands())
    stale = [key for key in _REPORTED_COMMANDS if key not in routed]
    assert not stale, (
        "_REPORTED_COMMANDS names commands that never reach "
        f"_after_editor_command, so listing them proves nothing: {stale}"
    )


def test_a_reported_command_is_not_also_claimed_to_mutate() -> None:
    """``undo`` and ``redo`` are both, and every other overlap is a mistake.

    A command in both tuples returns from its own branch before the undo-depth
    report can run, so listing it as mutating is a claim nothing acts on.
    """
    overlap = sorted(set(_REPORTED_COMMANDS) & set(_MUTATING_COMMANDS))
    assert overlap == ["redo", "undo"], (
        "a command is listed as both mutating and separately reported, which "
        f"means one of those two tuples is describing it wrongly: {overlap}"
    )


@pytest.mark.parametrize("key", sorted(_EDITOR_ACTIONS))
def test_each_editor_action_is_accounted_for(key: str) -> None:
    """Named one by one, so a red run says which command went silent."""
    handlers = StudioShell._build_handlers(_Routes())
    if handlers.get(key) != "_cmd_editor":
        pytest.skip(f"{key!r} is handled by {handlers.get(key)!r}, not _cmd_editor")
    assert (
        key in _MUTATING_COMMANDS or key in _REPORTED_COMMANDS
    ), f"{key!r} is delegated to the world editor and then reports nothing"
