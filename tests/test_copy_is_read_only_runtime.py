"""Copying is a read-only action, and the editor has to treat it as one.

Measured in a real editor on the shipped test world, before this module
existed: with a selection box drawn and settled, pressing Copy left
``SelectionManager.changed`` set to ``True`` -- turned from ``False`` by the
copy itself.  That flag is what decides whether the *next* undo point records
anything, so a read-only action was arming a revision of a selection nobody had
moved: an undo point that undoes nothing.

The cause is one line of ``EditCanvas.run_operation``'s error path.  ``copy``
finishes by raising ``OperationSilentAbort`` -- which is how an operation says
"do not create an undo point for me" -- and every exception out of an operation
is treated as a failed *write* and answered with
``world.restore_last_undo_point()``.  For copy there is no write to undo: it
reads chunks and puts a structure in the clipboard.  What the rollback does
reach is the level's one non-world history manager, this repository's
:class:`~amulet_map_editor.programs.edit.api.selection.SelectionHistoryManager`,
whose ``restore_last_undo_point`` unpacks its stored corners back through
``SelectionManager.set_selection_corners`` -- and that setter's first act is
``self.changed = True``.

An earlier version of this module said the same rollback would put the
selection back to what it was before the box was drawn, if Copy were pressed
inside the four tenths of a second before the selection's own deferred undo
point fires.  Measured in exactly that window with the refusal disabled -- box
drawn, no main loop in between, then Copy -- the box count was one before and
one after, and still one after a further 1.5 s.  Copy's own progress pump is
what finally delivers that timer, so the selection's undo point is committed
with the *current* box before the rollback is reached and what it restores is
the box that is already there.  The damage in that window is the same damage as
everywhere else, and the claim has been withdrawn rather than left standing as
a measured fact it never was.

**Three routes, not one.**  The report for a copy used to live in the Studio
shell, and two shipped controls never go through it: the 3D editor binds
Edit ▸ Copy and Ctrl+C straight to ``EditCanvas.copy``, and the Select tool's
Copy button does the same.  Measured on a running editor, both moved the
clipboard and raised zero notifications at any severity.  So this module
presses all three -- the Studio command, the bare method, and the real button
through a real ``wx.EVT_BUTTON`` -- and requires exactly one notification from
each.  Exactly one, because the fix for silence is a fix for double-reporting
too: if both layers spoke, one Ctrl+C would raise two toasts.

**What this module deliberately does not claim.**  The original report attached
"undo 1, changed True" to Copy.  Driven through a real ``wx`` main loop that is
not what happens: drawing a selection box arms a 400 ms one-shot timer whose
handler calls ``create_undo_point(False, True)``, and *that* is what takes the
level to one undo point and makes ``BaseLevel.changed`` answer ``True`` -- with
or without Copy, because ``MetaHistoryManager.changed`` counts every registered
snapshot including non-world ones.  It looks like Copy's doing under a probe
driven by bare ``wx.Yield``, which never delivers ``wx.Timer`` events, because
Copy's progress dialog is the first thing that pumps the queue properly.  So the
selection is settled here first, and the assertions are about what Copy moves
from that settled state.

**Why the clipboard is checked before anything else.**  "Nothing moved" is what
a copy that never ran produces too, so a regression that unbound Copy entirely
would pass every assertion below.  The clipboard growing by exactly one
structure is the precondition proving the mechanism under test is live.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import time
import zipfile
from typing import Any, Dict, Iterator, List, NoReturn, Optional, Tuple

import pytest

wx = pytest.importorskip("wx", reason="wxPython is not installed in this environment")
amulet = pytest.importorskip("amulet", reason="amulet-core is not installed")

from amulet.api.structure import structure_cache  # noqa: E402

from amulet_map_editor.api import lang, notifications  # noqa: E402
from amulet_map_editor.api.studio import context, editor_tools  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORLD_ARCHIVE = ROOT / "resource" / "worlds" / "java_1_12_2.zip"
WORLD_NAME = "java_1_12_2"

#: Off-screen, so a run on a visible desktop never throws a window at anybody.
OFFSCREEN = (-32000, -32000)

#: The 3D editor loads a resource pack and builds a texture atlas on a worker
#: thread before it has a canvas, so it is genuinely absent for a while.
CANVAS_WAIT_SECONDS = 120.0

#: Longer than ``SelectionManager._start_undo_point``'s 400 ms one-shot timer,
#: with room for a loaded machine.  The settle is asserted rather than assumed,
#: so a value that turned out to be too short fails loudly here instead of
#: quietly measuring the wrong state.
SETTLE_SECONDS = 1.5

#: Whether this host has been told it is one that can run the editor.
STRICT = os.environ.get("MMME_REQUIRE_EDITOR_RUNTIME", "").strip().lower() not in (
    "",
    "0",
    "false",
    "no",
    "off",
)


def _unavailable(reason: str) -> NoReturn:
    """Skip this module -- or fail it, on a host that promised it would run."""
    if STRICT:
        raise AssertionError(
            f"{reason}. MMME_REQUIRE_EDITOR_RUNTIME is set, so this host is "
            "meant to run the editor and a skip here would hide that it did not."
        )
    pytest.skip(reason)


# ----------------------------------------------------------------------
# a world to copy out of
# ----------------------------------------------------------------------


def _extract_world(destination: pathlib.Path) -> pathlib.Path:
    if not WORLD_ARCHIVE.is_file():
        _unavailable(f"the test world archive is missing: {WORLD_ARCHIVE}")
    with zipfile.ZipFile(WORLD_ARCHIVE) as archive:
        archive.extractall(destination)
    source = destination
    for _ in range(4):
        if (source / "level.dat").is_file():
            return source
        children = [child for child in source.iterdir() if child.is_dir()]
        if not children:
            break
        source = children[0]
    _unavailable(f"no level.dat inside {WORLD_ARCHIVE}")


def _prepare_world(workspace: pathlib.Path) -> str:
    """Copy the shipped test world out so nothing here touches the original."""
    source = _extract_world(workspace / "archive")
    path = str(workspace / WORLD_NAME)
    shutil.copytree(source, path, ignore=shutil.ignore_patterns("session.lock"))
    return path


# ----------------------------------------------------------------------
# driving the real editor
# ----------------------------------------------------------------------


def _pump(seconds: float) -> None:
    """Turn the event crank without a main loop, for things that do not need one."""
    end = time.time() + seconds
    while time.time() < end:
        wx.Yield()
        time.sleep(0.01)


def _settle(seconds: float) -> None:
    """Run the application's *real* event loop for ``seconds``.

    ``wx.Yield`` from a script that never started a main loop does not deliver
    ``wx.Timer`` events -- measured here: five seconds of yielding after a
    selection change left the deferred undo point unfired, and it landed the
    moment a progress dialog pumped the queue.  A test built on yielding alone
    therefore cannot tell "the selection has settled" from "it never will",
    which is the exact state this module has to establish before it can measure
    anything.
    """
    app = wx.GetApp()
    later = wx.CallLater(max(1, int(seconds * 1000)), app.ExitMainLoop)
    try:
        app.MainLoop()
    finally:
        later.Stop()


def _wait_for(predicate, seconds: float) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        try:
            if predicate():
                return True
        except Exception:  # noqa: BLE001 - a half-built frame answers this
            pass
        wx.Yield()
        time.sleep(0.05)
    try:
        return bool(predicate())
    except Exception:  # noqa: BLE001
        return False


def _reading(canvas: Any) -> Dict[str, Any]:
    """Everything this module asserts about, read fresh from the live editor."""
    world = canvas.world
    history = world.history_manager
    selection = canvas.selection
    return {
        "undo": int(history.undo_count),
        "redo": int(history.redo_count),
        "world_changed": bool(world.changed),
        "selection_changed": bool(selection.changed),
        "boxes": len(selection.selection_corners),
        "clipboard": len(structure_cache),
    }


def _seen() -> set:
    """The notifications already on record, so a later read can subtract them."""
    return {note.notification_id for note in notifications.list_notifications()}


def _since(seen: set) -> List[Dict[str, str]]:
    """Every notification raised since ``seen`` was taken."""
    return [
        {
            "severity": str(note.severity),
            "title": str(note.title),
            "body": str(note.body),
        }
        for note in notifications.list_notifications()
        if note.notification_id not in seen
    ]


def _find_button(window: Any, label: str) -> Any:
    """Return the first descendant button carrying ``label``.

    The Select tool builds its buttons in a local closure and keeps no
    reference to any of them, so the only way to press the real control is to
    go and find it in the panel it was added to.

    Matched by duck-typed vocabulary rather than ``isinstance(window,
    wx.Button)``: the Material 3 conversion moved every tool-panel button to
    ``StudioButton`` -- a ``wx.Control`` that answers ``GetLabel`` and still
    emits a real ``wx.EVT_BUTTON`` on click, but is not a ``wx.Button`` -- so
    the old isinstance check silently stopped matching it.  Mirrors the
    identical fix already made for the Operation tool's chooser in
    ``tests/test_editor_clone_runtime.py`` and the exporter chooser in
    ``tests/test_export_format_runtime.py``.
    """
    from amulet_map_editor.api.studio.widgets import StudioButton

    if isinstance(window, (wx.Button, StudioButton)) and window.GetLabel() == label:
        return window
    for child in window.GetChildren():
        found = _find_button(child, label)
        if found is not None:
            return found
    return None


class Session:
    """One opened world, and what Copy did to it -- from all three routes."""

    def __init__(self) -> None:
        self.path: str = ""
        self.canvas: Any = None
        self.frame: Any = None
        self.settled: Dict[str, Any] = {}
        self.after_copy: Dict[str, Any] = {}
        self.before_box: Dict[str, Any] = {}
        self.after_box: Dict[str, Any] = {}
        self.toasts: List[Dict[str, str]] = []
        #: The 3D editor's Edit ▸ Copy and its Ctrl+C both end in a bare
        #: ``EditCanvas.copy()`` that never reaches the Studio shell.
        self.direct: Dict[str, Any] = {}
        self.direct_toasts: List[Dict[str, str]] = []
        #: The Select tool's own Copy button, pressed as a real wx event.
        self.button_label: str = ""
        self.button_found: bool = False
        self.button: Dict[str, Any] = {}
        self.button_toasts: List[Dict[str, str]] = []


@pytest.fixture(scope="module")
def app() -> Iterator[Any]:
    existing = wx.App.Get()
    created = None
    if existing is None:
        try:
            created = wx.App(False)
        except Exception as error:  # pragma: no cover - depends on the host
            _unavailable(f"wx.App could not start on this host: {error!r}")
    yield existing or created
    if created is not None:
        created.Destroy()


@pytest.fixture(scope="module")
def session(app, tmp_path_factory) -> Iterator[Session]:
    """Open a world, draw a box, let it settle, then press Copy once."""
    record = Session()
    workspace = tmp_path_factory.mktemp("copy-read-only")
    record.path = _prepare_world(workspace)

    from amulet_map_editor.api.framework.amulet_ui import AmuletUI

    structure_cache.clear()
    frame = AmuletUI(None)
    record.frame = frame
    try:
        frame.SetSize(wx.Size(1500, 950))
        frame.SetPosition(wx.Point(*OFFSCREEN))
        frame.Show()
        _pump(0.3)
        frame.open_level(record.path)
        if not _wait_for(lambda: context.current().open, 60.0):
            _unavailable("the world did not open in this environment")
        if not _wait_for(
            lambda: frame.hosted_canvas() is not None, CANVAS_WAIT_SECONDS
        ):
            frame.sync_studio_project()
            _pump(1.0)
        record.canvas = frame.hosted_canvas() or editor_tools.canvas()
        if record.canvas is None:
            _unavailable("the 3D editor produced no canvas on this host")
        shell = getattr(frame, "_studio", None)
        if shell is None:
            _unavailable("this build fell back to the notebook, so there is no shell")
        _settle(0.5)

        record.before_box = _reading(record.canvas)
        shell.run_command("addBox")
        record.after_box = _reading(record.canvas)
        _settle(SETTLE_SECONDS)
        record.settled = _reading(record.canvas)

        seen = _seen()
        shell.run_command("copy")
        _settle(1.0)
        record.after_copy = _reading(record.canvas)
        record.toasts = _since(seen)

        # ---- the route the 3D editor's own menu and Ctrl+C take -----------
        # ``edit.py`` binds both to ``CallableWeakMethod(self._canvas.copy)``,
        # so what runs is exactly this call and the Studio shell never hears
        # about it.
        seen = _seen()
        before_direct = _reading(record.canvas)
        record.canvas.copy()
        _settle(1.0)
        record.direct = {
            "before": before_direct,
            "after": _reading(record.canvas),
        }
        record.direct_toasts = _since(seen)

        # ---- and the Select tool's own Copy button ------------------------
        record.button_label = lang.get("program_3d_edit.select_tool.copy_button")
        tool = None
        try:
            tool = record.canvas.tools.get("Select")
        except Exception:  # noqa: BLE001 - a canvas without its tool sizer
            tool = None
        panel = getattr(tool, "_button_panel", None)
        button = _find_button(panel, record.button_label) if panel else None
        if button is None:
            button = _find_button(frame, record.button_label)
        record.button_found = button is not None
        if button is not None:
            seen = _seen()
            before_button = _reading(record.canvas)
            # ``StudioButton.activate()`` is the real control's own real
            # interaction path -- what a mouse click or a Space/Enter key
            # press resolves to -- and it both calls ``on_click`` and emits
            # ``wx.EVT_BUTTON`` outward.  A synthetic ``wx.EVT_BUTTON`` sent
            # *into* the control the way a plain ``wx.Button`` would receive
            # one does nothing here: nothing on a ``StudioButton`` listens for
            # an incoming ``EVT_BUTTON`` to trigger ``on_click``, so that
            # route silently pressed nothing.  ``activate()`` is exactly the
            # method this repository's own Material-button tests already use
            # to press a real ``StudioButton`` (see
            # ``tests/test_editor_toolbar_material_contract.py`` and
            # ``tests/test_material_text_and_checkbox_contract.py``).
            button.activate()
            _settle(1.0)
            record.button = {
                "before": before_button,
                "after": _reading(record.canvas),
            }
            record.button_toasts = _since(seen)
    finally:
        try:
            frame.Destroy()
        except Exception:  # noqa: BLE001 - a frame already gone is fine
            pass
        _pump(0.3)
        context.clear()
    yield record


# ----------------------------------------------------------------------
# preconditions: the mechanism under test is live
# ----------------------------------------------------------------------


def test_the_box_was_drawn_and_its_undo_point_settled(session: Session) -> None:
    """Prove the state Copy is measured from, rather than assuming it.

    Two separate things are asserted because two separate things can silently
    not happen: the box has to exist for Copy to have anything to read, and the
    selection's own deferred undo point has to have *already* fired, or the
    assertions below would be measuring a settle that was always going to
    arrive during Copy's own event pump and blaming Copy for it.
    """
    assert session.after_box["boxes"] == session.before_box["boxes"] + 1, (
        "adding a selection box did not add one, so nothing below is measuring "
        f"a copy of anything: {session.before_box} -> {session.after_box}"
    )
    assert session.after_box["selection_changed"] is True, (
        "drawing a box left the selection unmarked, so this module cannot tell "
        "a settled selection from one that was never touched: "
        f"{session.after_box}"
    )
    assert session.settled["selection_changed"] is False, (
        "the selection's deferred undo point had not fired after "
        f"{SETTLE_SECONDS}s, so the state Copy is measured from is not settled "
        f"and the readings below mean nothing: {session.settled}"
    )
    assert session.settled["undo"] > session.after_box["undo"], (
        "the settle recorded no undo point at all, so the deferred mechanism "
        f"this module waits for is not running: {session.after_box} -> "
        f"{session.settled}"
    )


def test_the_copy_actually_reached_the_clipboard(session: Session) -> None:
    """The precondition every "nothing moved" assertion below depends on.

    A Copy that never ran moves nothing either, so without this a regression
    that unbound the command entirely would turn this module green.
    """
    assert session.after_copy["clipboard"] == session.settled["clipboard"] + 1, (
        "pressing Copy did not put a structure in the editor's clipboard, so "
        "every other assertion in this module is measuring a copy that did not "
        f"happen: {session.settled} -> {session.after_copy}"
    )


# ----------------------------------------------------------------------
# the defect
# ----------------------------------------------------------------------


def test_copying_does_not_leave_the_selection_marked_changed(session: Session) -> None:
    """The measured regression: Copy armed a revision of an unmoved selection.

    ``SelectionManager.changed`` is what ``SelectionHistoryManager.
    create_undo_point_iter`` reads to decide whether to record a revision, so
    leaving it set after a read-only action is precisely "a no-op undo point,
    silently".
    """
    assert session.after_copy["selection_changed"] is False, (
        "copying flipped the selection's changed flag, so the next undo point "
        "will record a revision of a selection nobody moved: "
        f"{session.settled} -> {session.after_copy}"
    )


def test_copying_does_not_move_the_undo_depth(session: Session) -> None:
    assert session.after_copy["undo"] == session.settled["undo"], (
        "copying changed the world's undo depth, and a copy writes nothing to "
        f"the world: {session.settled} -> {session.after_copy}"
    )
    assert session.after_copy["redo"] == session.settled["redo"], (
        "copying changed the world's redo depth: "
        f"{session.settled} -> {session.after_copy}"
    )


def test_copying_does_not_change_whether_the_world_has_unsaved_work(
    session: Session,
) -> None:
    """A copy must not be able to turn a clean world into a dirty one.

    Asserted as "unmoved" rather than "False" on purpose: whether the world
    already reports unsaved changes at this point is a question about drawing a
    selection box, which is not what this module is about.  What a read-only
    action may never do is move that answer.
    """
    assert session.after_copy["world_changed"] == session.settled["world_changed"], (
        "copying changed the world's unsaved-changes answer, which is what "
        "puts a false 'you have unsaved work' prompt in front of somebody who "
        f"only pressed Ctrl+C: {session.settled} -> {session.after_copy}"
    )


def test_copying_does_not_disturb_the_selection_it_copied(session: Session) -> None:
    """The rollback's other reach: it unpacks stored corners over the live ones."""
    assert session.after_copy["boxes"] == session.settled["boxes"], (
        "copying changed how many selection boxes there are: "
        f"{session.settled} -> {session.after_copy}"
    )


# ----------------------------------------------------------------------
# and it has to say what it did
# ----------------------------------------------------------------------


def _assert_reports_a_copy(toasts: List[Dict[str, str]], route: str) -> None:
    """Every route into Copy has to raise exactly one useful notification.

    Counted by how many of them talk about the clipboard rather than by how
    many arrived at all.  The notification store is a profile file on disk and
    is shared by every process using the same ``CONFIG_DIR``, so a second
    editor running beside this one can drop an unrelated record into the same
    window -- and failing this module for somebody else's toast would be a
    flake, not a finding.  A report made in two layers at once still fails,
    because both of those sentences are about the clipboard.
    """
    assert toasts, (
        f"{route} raised no notification at all, so nothing tells the user "
        "whether anything reached the clipboard"
    )
    reports = [toast for toast in toasts if "clipboard" in toast["body"].lower()]
    assert len(reports) == 1, (
        f"{route} raised {len(reports)} notifications about the clipboard for "
        f"one action, so the report is being made in two places at once: "
        f"{toasts}"
    )
    toast = reports[0]
    assert toast["severity"] in ("success", "info"), (
        f"{route} reported a copy that reached the clipboard as "
        f"{toast['severity']!r}: {toast}"
    )
    assert "block" in toast["body"].lower(), (
        f"{route}'s notification does not say how much was copied, which is "
        f"the only fact about a copy the user cannot see: {toast}"
    )


def test_copying_reports_what_it_copied(session: Session) -> None:
    """Copy was silent: no toast at all, at any severity.

    ``_after_editor_command`` reported only for commands in
    ``_MUTATING_COMMANDS`` or with a named subject, and Copy is neither -- so
    the one command whose whole result is invisible in the viewport said
    nothing about having worked.
    """
    _assert_reports_a_copy(session.toasts, "the Studio's Copy command")


# ----------------------------------------------------------------------
# ... from every control that runs it, not just the Studio's own command
# ----------------------------------------------------------------------


def test_a_copy_the_shell_never_sees_still_reaches_the_clipboard(
    session: Session,
) -> None:
    """The precondition for the report assertion below it."""
    assert session.direct["after"]["clipboard"] == (
        session.direct["before"]["clipboard"] + 1
    ), (
        "calling EditCanvas.copy directly put nothing on the clipboard, so the "
        f"assertion below is measuring a copy that did not happen: {session.direct}"
    )


def test_a_copy_the_shell_never_sees_still_reports(session: Session) -> None:
    """The defect the first fix missed, and the reason it missed it.

    ``edit.py`` binds Edit ▸ Copy and Ctrl+C straight to
    ``CallableWeakMethod(self._canvas.copy)``, so neither passes through
    ``StudioShell.run_command`` and neither could ever reach the report that
    used to live in ``_after_editor_command``.  Measured on a running editor
    before this: the clipboard grew and zero notifications were raised.
    """
    _assert_reports_a_copy(session.direct_toasts, "EditCanvas.copy called directly")


def test_the_select_tools_copy_button_is_still_there(session: Session) -> None:
    """Without the button this module's last test asserts about nothing."""
    assert session.button_found, (
        "the Select tool has no button labelled "
        f"{session.button_label!r}, so the test below is vacuous"
    )
    assert session.button["after"]["clipboard"] == (
        session.button["before"]["clipboard"] + 1
    ), (
        "pressing the Select tool's Copy button put nothing on the clipboard: "
        f"{session.button}"
    )


def test_the_select_tools_copy_button_reports(session: Session) -> None:
    """The other control that calls the canvas directly, pressed for real."""
    _assert_reports_a_copy(session.button_toasts, "the Select tool's Copy button")


def test_no_route_into_copy_disturbs_the_selection(session: Session) -> None:
    """The read-only half, asserted for the two routes the shell never sees."""
    for route, reading in (
        ("EditCanvas.copy", session.direct),
        ("the Copy button", session.button),
    ):
        if not reading:
            continue
        assert reading["after"]["selection_changed"] is False, (
            f"{route} left the selection marked changed, so the next undo "
            f"point will record a revision nobody made: {reading}"
        )
        assert reading["after"]["undo"] == reading["before"]["undo"], (
            f"{route} moved the world's undo depth, and a copy writes nothing "
            f"to the world: {reading}"
        )
        assert (
            reading["after"]["boxes"] == reading["before"]["boxes"]
        ), f"{route} changed how many selection boxes there are: {reading}"
