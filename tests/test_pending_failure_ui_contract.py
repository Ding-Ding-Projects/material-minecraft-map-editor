"""A paste that failed says so in the pane, and keeps the object it did not write.

The bridge learning that a paste wrote nothing is only half a fix.  The other
half is what the interface then does with that, and the pane used to do the
worst available thing: it called ``_report_tool_gone``, which logs at debug and
takes the Tool tab away.  So a failed paste and a successful one produced the
same visible result -- the panel disappearing -- while the copy was in fact
still held and still drawn over the world.  A user watching that had no way to
tell "your blocks are in" from "your blocks are nowhere and the thing you were
placing is still on your screen".

**Why the pane is driven with a stand-in canvas.**  The real
``confirm_pending`` runs here -- it is the code under test and is not replaced.
What is replaced is the world beneath it: a canvas whose paste operation raises,
routed through the same ``run_operation`` swallow the real one uses, because
staging a genuinely failing paste inside a real world means breaking the paste
tool on purpose.  The branch logic behind those outcomes is proven in
``tests/test_editor_confirm_outcome.py``; the successful route through a real
world is proven in ``tests/test_editor_clone_runtime.py``.  This module proves
the part neither of those can: that the words reach the screen and the panel
stays.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Iterator, List, Optional, Tuple

import pytest

wx = pytest.importorskip("wx", reason="wxPython is not installed in this environment")

from amulet_map_editor.api import notifications  # noqa: E402
from amulet_map_editor.api.studio import editor_tools  # noqa: E402
from amulet_map_editor.api.studio import properties_pane as pane_module  # noqa: E402
from amulet_map_editor.api.studio.widgets import StudioText  # noqa: E402

EXTENT: Tuple[int, int, int] = (4, 1, 4)
LOCATION: Tuple[int, int, int] = (8, 40, 8)


# ----------------------------------------------------------------------
# a world whose paste fails
# ----------------------------------------------------------------------


class _History:
    def __init__(self, undo_count: int = 0) -> None:
        self.undo_count = undo_count


class _World:
    def __init__(self) -> None:
        self.history_manager = _History()


class _Canvas:
    """A canvas that swallows exactly as ``EditCanvas.run_operation`` does."""

    def __init__(self) -> None:
        self.tools: dict = {}
        self.world = _World()

    def run_operation(
        self,
        operation: Callable[[], Any],
        title: Optional[str] = None,
        msg: str = "Running Operation",
        throw_exceptions: bool = False,
        rollback_on_error: Any = None,
    ) -> Any:
        try:
            out = operation()
        except BaseException as error:  # noqa: BLE001 - the real one is this broad
            if throw_exceptions:
                raise error
        else:
            self.world.history_manager.undo_count += 1
            return out


class _FailingPasteTool:
    def __init__(self, canvas: _Canvas) -> None:
        self._is_enabled = True
        self._canvas = canvas
        self.calls = 0

    def confirm_paste(self) -> None:
        self.calls += 1
        self._canvas.run_operation(self._operation)

    @staticmethod
    def _operation() -> None:
        raise RuntimeError("the paste operation could not read the source chunk")


def _pending() -> editor_tools.PendingObject:
    return editor_tools.PendingObject(
        location=LOCATION,
        rotation=(0.0, 0.0, 0.0),
        scale=(1.0, 1.0, 1.0),
        following=False,
        drawn=True,
        size=" by ".join(str(value) for value in EXTENT),
    )


@pytest.fixture(scope="module")
def app() -> Iterator[Any]:
    existing = wx.App.Get()
    created = None
    if existing is None:
        try:
            created = wx.App(False)
        except Exception as error:  # pragma: no cover - depends on the host
            pytest.skip(f"wx.App could not start on this host: {error!r}")
    yield existing or created
    if created is not None:
        created.Destroy()


@pytest.fixture()
def canvas(monkeypatch: pytest.MonkeyPatch, tmp_path) -> _Canvas:
    """Point the bridge at a world whose paste raises, and a throwaway profile."""
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "profile"))
    built = _Canvas()
    built.tools["Paste"] = _FailingPasteTool(built)
    # The real ``confirm_pending`` is deliberately NOT replaced; only the canvas
    # it resolves is, so the code under test runs in full.
    monkeypatch.setattr(editor_tools, "canvas", lambda: built)
    monkeypatch.setattr(editor_tools, "pending_object", lambda *a, **k: _pending())
    monkeypatch.setattr(editor_tools, "active_tool_name", lambda *a, **k: "Paste")
    monkeypatch.setattr(editor_tools, "camera_location", lambda *a, **k: None)
    monkeypatch.setattr(editor_tools, "movement_sentence", lambda *a, **k: "")
    # Keep the user's real notification history out of a test run.
    monkeypatch.setattr(
        notifications,
        "add",
        lambda severity, title, body, *, details="": notifications.Notification(
            notification_id="test",
            created_at="2026-08-11T00:00:00+00:00",
            severity=severity,
            title=title,
            body=body,
            details=details,
        ),
    )
    return built


@pytest.fixture()
def pane(app, canvas: _Canvas) -> Iterator[Any]:
    """A properties pane showing a Clone activation, on a real frame."""
    window = wx.Frame(None, size=(360, 700), pos=(-32000, -32000))
    built = pane_module.PropertiesPane(window, title="Test world")
    sizer = wx.BoxSizer(wx.VERTICAL)
    sizer.Add(built, 1, wx.EXPAND)
    window.SetSizer(sizer)
    window.SetSize((360, 700))
    window.Show()
    window.Layout()
    wx.Yield()
    built.show_tool_activation(
        editor_tools.Activation(
            key="cloneTool",
            label="Clone",
            ok=True,
            tool="Paste",
            kind="pending",
            message="The selection was copied and the paste tool is holding it.",
        )
    )
    built.Layout()
    wx.Yield()
    try:
        yield built
    finally:
        window.Destroy()
        wx.Yield()


# ----------------------------------------------------------------------
# reading what the pane built
# ----------------------------------------------------------------------


def _descendants(window: Any) -> Iterator[Any]:
    stack = [window]
    while stack:
        node = stack.pop()
        yield node
        try:
            stack.extend(node.GetChildren())
        except Exception:  # noqa: BLE001 - a control mid-teardown
            continue


def _notes(pane: Any) -> List[Tuple[Any, str]]:
    found: List[Tuple[Any, str]] = []
    for node in _descendants(pane):
        if not isinstance(node, StudioText):
            continue
        try:
            found.append((node, " ".join(str(node.GetLabel()).split())))
        except Exception:  # noqa: BLE001
            continue
    return found


def _note_saying(pane: Any, needle: str) -> Optional[Any]:
    wanted = " ".join(str(needle).split())
    for node, text in _notes(pane):
        if wanted in text:
            return node
    return None


# ----------------------------------------------------------------------
# the contract
# ----------------------------------------------------------------------


def test_the_tool_tab_survives_a_paste_that_wrote_nothing(
    pane: Any, canvas: _Canvas
) -> None:
    """The defect, stated as the thing a user would have seen.

    Taking the panel away is what a *successful* confirm-and-clear looks like.
    Doing it after a failure makes the two indistinguishable and strands a copy
    that is still held with no controls for it.
    """
    assert pane.activation is not None, "precondition: the Tool tab is showing"

    pane._confirm_pending()
    wx.Yield()

    assert canvas.tools["Paste"].calls == 1, "the confirm was never attempted"
    assert (
        canvas.world.history_manager.undo_count == 0
    ), "the paste was not meant to land"
    assert pane.activation is not None, (
        "the pane took the Tool tab away after a paste that wrote nothing, which "
        "is exactly what it does after one that succeeded -- the failure is "
        "invisible again"
    )
    assert pane.tab == pane_module.TOOL_TAB[0], "the pane navigated away from the tool"


def test_the_reason_is_on_the_screen_not_only_in_the_log(pane: Any) -> None:
    """A debug log line is not an interface.

    ``IsShownOnScreen`` rather than ``IsShown``: a control inside a hidden
    parent still answers true to the latter, so it would pass over a pane that
    built the note and never displayed it.
    """
    pane._confirm_pending()
    wx.Yield()

    note = _note_saying(pane, "no blocks were written")
    assert note is not None, (
        "the pane rendered nothing saying the paste failed. Every paragraph it "
        f"did render: {[text for _node, text in _notes(pane)]}"
    )
    assert note.IsShownOnScreen(), "the failure note was built but is not visible"
    label = " ".join(str(note.GetLabel()).split())
    for fact, why in (
        ("Confirm placement", "it does not name the operation"),
        ("still being held", "it does not say the object survived"),
        ("Cancel", "it offers no way out"),
    ):
        assert fact in label, f"{why}: {label!r}"


def test_the_object_is_still_described_beside_its_failure(pane: Any) -> None:
    """The controls for the thing that was not written are still there.

    A message about a pending object with no pending object beside it would be
    a dead end -- retrying is the first thing anybody does.
    """
    pane._confirm_pending()
    wx.Yield()

    assert _note_saying(pane, "no blocks were written") is not None
    rows = dict(pane._tool_rows)
    assert (
        "following" in rows and "drawn" in rows
    ), f"the pending object's live rows went with the failure: {sorted(rows)}"
    assert rows["drawn"].IsShownOnScreen()


def test_a_later_success_clears_the_earlier_failure(
    pane: Any, canvas: _Canvas, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stale refusal beside a paste that worked is a new lie."""
    pane._confirm_pending()
    wx.Yield()
    assert _note_saying(pane, "no blocks were written") is not None

    class _Working(_FailingPasteTool):
        @staticmethod
        def _operation() -> None:
            return None

    canvas.tools["Paste"] = _Working(canvas)
    pane._confirm_pending()
    wx.Yield()

    assert canvas.world.history_manager.undo_count == 1, "the second paste did not land"
    assert _note_saying(pane, "no blocks were written") is None, (
        "the failure from the previous attempt is still on screen beside a paste "
        "that succeeded"
    )


def test_lifting_another_object_leaves_the_old_refusal_behind(
    pane: Any, canvas: _Canvas
) -> None:
    """The same lie as the defect above, pointing the other way.

    Pressing Clone again goes ``editor_tools.activate`` ->
    ``_show_in_host`` -> ``show_tool_activation``, and ``clear_tool`` is not
    anywhere on that path -- it is reached only from a cancel and from the tool
    going away.  So the sentence about a paste that wrote nothing used to
    survive into the *next* activation and be rendered beside an object nobody
    had tried to write yet.  Over-reporting failure rather than success, which
    is the safe direction, and still the interface stating something untrue
    about a paste.

    Driven through ``show_tool_activation`` rather than by clearing the
    attribute, because the attribute is not what a user presses.
    """
    pane._confirm_pending()
    wx.Yield()
    assert (
        _note_saying(pane, "no blocks were written") is not None
    ), "precondition: the failure this test is about is on screen"

    pane.show_tool_activation(
        editor_tools.Activation(
            key="cloneTool",
            label="Clone",
            ok=True,
            tool="Paste",
            kind="pending",
            message="The selection was copied and the paste tool is holding it.",
        )
    )
    pane.Layout()
    wx.Yield()

    assert _note_saying(pane, "no blocks were written") is None, (
        "the refusal from the previous object is still on screen beside the "
        "one just lifted, so the pane is reporting a failed paste of something "
        "nobody has tried to paste"
    )
    assert not pane._pending_failure, (
        "the note is not being rendered but the pane is still holding it, so it "
        "returns the moment anything rebuilds"
    )
    # The panel itself must survive: this is a clear, not a clear_tool.
    assert pane.activation is not None and pane.tab == pane_module.TOOL_TAB[0]
    assert "following" in pane._tool_rows, "the pending object's rows went with it"


def test_the_failed_pending_panel_composites_without_holes(
    pane: Any, tmp_path: Path
) -> None:
    """Look at the picture rather than trusting the widget tree.

    A capture whose report names a skipped window or a blitted leaf is a capture
    with a hole in it at the place that name says, so the note being "present"
    would prove nothing about it having been drawn.
    """
    capture = pytest.importorskip(
        "scripts.capture_surface", reason="the capture harness is unavailable"
    )
    pane._confirm_pending()
    wx.Yield()
    pane.Layout()
    wx.Yield()

    # Without this the module's own empty state composites perfectly well and
    # this test passes over a pane showing nothing of what it claims to check.
    note = _note_saying(pane, "no blocks were written")
    assert (
        note is not None and note.IsShownOnScreen()
    ), "the surface about to be photographed is not the failed-paste one"

    destination = tmp_path / "pending_failure.png"
    report = capture.capture_composite(pane, destination)

    assert destination.exists() and destination.stat().st_size > 0
    assert not report.get("skipped"), f"holes in the capture: {report['skipped']}"
    assert not report.get("blitted_leaves"), (
        f"windows drawn by a route the report cannot vouch for: "
        f"{report['blitted_leaves']}"
    )
