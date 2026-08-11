"""Drive the progress overlay, because reading its source cannot.

Every assertion in ``test_progress_overlay_contract.py`` is about source text,
and source text cannot answer the questions that actually matter here: whether
the overlay appears, whether it advances, whether the shell underneath is still
alive while it does, and whether a bar that cannot report a fraction is
genuinely drawn differently from one that is at zero.  A widget that paints in
``EVT_PAINT`` and never overrode ``render_to`` photographs blank while
reporting success, so "the capture worked" is not evidence either -- the pixels
are compared.

The long operation driven here is a real one: ``WorldSelectUI._extract_archive``
extracting a real zip archive off the UI thread, which is the product's own code
on the product's own path.  It is not a re-creation of the loop, because a
re-creation proves things about the test.
"""

from __future__ import annotations

import os
import tempfile
import time
import zipfile
from pathlib import Path
from typing import List, Optional

import pytest

wx = pytest.importorskip("wx", reason="wxPython is not installed in this environment")

from amulet_map_editor.api.progress import (  # noqa: E402
    DONE,
    FAILED,
    RUNNING,
    ProgressTask,
)
from amulet_map_editor.api.wx.progress import begin_progress  # noqa: E402

#: Enough members that the extraction takes more than one 50 ms poll, so the
#: fraction is genuinely observed moving rather than jumping straight to one.
ARCHIVE_MEMBERS = 900


@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("CONFIG_DIR", tempfile.mkdtemp(prefix="amulet-progress-"))
    application = wx.App()
    yield application


@pytest.fixture
def frame(app):
    """A real application frame, shown, with its event loop turned over once."""
    from amulet_map_editor.api.framework import amulet_ui

    window = amulet_ui.AmuletUI(None)
    window.Show()
    wx.SafeYield()
    yield window
    window.Hide()
    window.Destroy()
    wx.SafeYield()


@pytest.fixture
def no_blocking_dialog(monkeypatch):
    """Make any blocking progress surface fail the test that opened it.

    Asserting on the absence of a modal dialog by counting windows is weak --
    a dialog that opens and closes between two polls leaves no trace.  Making
    the constructor itself explode catches it whenever it is reached.
    """
    opened: List[str] = []

    def refuse(name):
        def boom(*_args, **_kwargs):
            opened.append(name)
            raise AssertionError(f"a blocking {name} was opened to report progress")

        return boom

    monkeypatch.setattr(wx, "ProgressDialog", refuse("wx.ProgressDialog"))
    monkeypatch.setattr(wx, "BusyInfo", refuse("wx.BusyInfo"))
    yield opened
    assert opened == []


def _overlay(frame) -> Optional[wx.Panel]:
    return frame._progress_overlay


# ----------------------------------------------------------------------
# it appears, over the interface, without displacing it
# ----------------------------------------------------------------------


def test_the_overlay_floats_over_the_shell_without_taking_space_from_it(frame):
    """A progress row must not reflow the surface it is reporting about.

    This is the whole reason it is positioned rather than added to a sizer, and
    it is the failure a toast already had once: as a sizer child it became a
    full-width banner that pushed the application down the window.
    """
    frame.SetSize(wx.Size(1000, 700))
    wx.SafeYield()
    before = [
        (child.GetPosition().Get(), child.GetSize().Get())
        for child in frame._shell.GetChildren()
        if child.IsShown()
    ]

    report = begin_progress(frame, "float", "Saving world", detail="region files")
    wx.SafeYield()
    overlay = _overlay(frame)
    assert overlay is not None, "reporting progress did not build the overlay"
    assert overlay.IsShownOnScreen(), "the overlay was never actually visible"

    after = [
        (child.GetPosition().Get(), child.GetSize().Get())
        for child in frame._shell.GetChildren()
        if child.IsShown() and child is not overlay
    ]
    assert after == before, "showing progress moved the interface underneath it"

    # And it is over the interface rather than beside it: full width, at the top,
    # below whatever title bar is in use so the window controls stay reachable.
    assert overlay.GetSize().width == frame._shell.GetClientSize().width
    assert overlay.GetPosition().y >= 0
    assert overlay.GetPosition().y < frame._shell.GetClientSize().height // 2
    report.finish()


def test_the_overlay_does_not_take_focus(frame):
    """Progress arriving must not move the cursor out of what the user is typing."""
    probe = wx.TextCtrl(frame._shell)
    probe.SetFocus()
    wx.SafeYield()
    focused = wx.Window.FindFocus()

    report = begin_progress(frame, "focus", "Saving world", cancellable=True)
    wx.SafeYield()
    assert wx.Window.FindFocus() is focused, "the overlay stole focus when it appeared"
    report.finish()
    probe.Destroy()


def test_the_overlay_carries_an_accessible_name_and_a_live_value(frame):
    """A screen reader must hear the current reading, not the opening one."""
    report = begin_progress(frame, "a11y", "Saving world", detail="region files")
    wx.SafeYield()
    overlay = _overlay(frame)
    opening = overlay.GetName()
    assert "Saving world" in opening
    # Unmeasured work says so in words rather than going silent.
    assert "unknown" in opening

    report.update(fraction=0.42)
    wx.SafeYield()
    assert "42 percent" in overlay.GetName()
    assert "42 percent" not in opening, "the accessible value never changed"
    report.finish()


# ----------------------------------------------------------------------
# a real long operation
# ----------------------------------------------------------------------


def _build_archive(directory: Path) -> Path:
    archive = directory / "world.mcworld"
    with zipfile.ZipFile(archive, "w") as handle:
        for index in range(ARCHIVE_MEMBERS):
            handle.writestr(f"db/{index:06d}.ldb", b"x" * 512)
    return archive


def test_a_real_extraction_advances_the_overlay_and_leaves_the_shell_alive(
    frame, tmp_path, no_blocking_dialog
):
    """The product's own extraction, driven end to end.

    Four things are measured here and none of them can be read off the source:
    that no blocking dialog was opened, that the overlay was on screen while the
    work ran, that its fraction genuinely moved through intermediate values, and
    that the shell kept processing events throughout -- which is the whole claim
    a non-blocking surface makes.
    """
    from amulet_map_editor.api.wx.ui.select_world import WorldSelectUI

    archive = _build_archive(tmp_path)
    destination = tmp_path / "extracted"
    destination.mkdir()

    # Responsiveness is measured by a real queued user action being handled
    # while the work is still running -- which is the actual claim a
    # non-blocking surface makes, and the thing the application-modal dialog
    # this replaced took away.
    #
    # A ``wx.Timer`` heartbeat was tried first and is a dead end: ``WM_TIMER``
    # is a low-priority message that Windows only synthesises when the queue is
    # otherwise empty, so a busy yield loop starves it and the measurement
    # reads as a frozen interface when the interface is fine.
    clicks: List[float] = []
    button = wx.Button(frame._shell, label="probe")
    button.Bind(wx.EVT_BUTTON, lambda _event: clicks.append(time.monotonic()))

    seen: List[Optional[float]] = []
    visible: List[bool] = []
    handled_while_running: List[int] = []
    posted = False

    report = begin_progress(frame, "extract", "Extracting world", detail=archive.name)
    original_update = report.update

    def watched(**kwargs):
        nonlocal posted
        original_update(**kwargs)
        seen.append(report.task.fraction)
        overlay = _overlay(frame)
        visible.append(bool(overlay is not None and overlay.IsShownOnScreen()))
        if not posted:
            posted = True
            event = wx.CommandEvent(wx.EVT_BUTTON.typeId, button.GetId())
            event.SetEventObject(button)
            wx.PostEvent(button, event)
        handled_while_running.append(len(clicks))

    report.update = watched
    try:
        WorldSelectUI._extract_archive(str(archive), str(destination), report)
    finally:
        report.update = original_update
        report.finish()
        button.Destroy()

    assert len(list(destination.glob("db/*.ldb"))) == ARCHIVE_MEMBERS

    measured = [value for value in seen if value is not None]
    assert measured, "the extraction never reported a fraction"
    assert measured == sorted(measured), f"progress went backwards: {measured[:12]}"
    assert measured[-1] == pytest.approx(1.0)
    assert (
        len(set(measured)) > 1
    ), "progress jumped straight to done; nothing was ever observed advancing"
    assert any(visible), "the overlay was never on screen while the work ran"
    assert clicks, "a click queued during the operation was never handled at all"
    assert max(handled_while_running) > 0, (
        "the click was only handled after the operation finished; the shell was "
        "frozen while it ran"
    )
    assert frame.IsEnabled(), "the shell was disabled during a non-blocking report"


def test_a_cancel_press_stops_a_real_yield_loop(frame, no_blocking_dialog):
    """The Cancel control on the overlay reaches the loop that is running.

    The loop here is the shape ``WorldPageUI.close`` and ``_run_operation`` both
    use -- join, report, yield, check -- driven against a real worker thread.
    """
    import threading

    stop = threading.Event()
    thread = threading.Thread(target=lambda: stop.wait(30), daemon=True)
    thread.start()

    report = begin_progress(frame, "cancel", "Running operation", cancellable=True)
    wx.SafeYield()
    overlay = _overlay(frame)
    button = overlay._buttons.get("cancel")
    assert button is not None, "cancellable work drew no cancel control"
    assert "Cancel" in button.GetName()

    pressed = False
    deadline = time.monotonic() + 10
    while thread.is_alive() and time.monotonic() < deadline:
        thread.join(0.05)
        report.update(indeterminate=True, detail="working")
        wx.SafeYield()
        if not pressed:
            pressed = True
            overlay._activate("cancel")
        if report.cancelled:
            stop.set()
    thread.join(1)

    assert report.cancelled, "pressing Cancel did not reach the running loop"
    assert not thread.is_alive(), "the work carried on after it was cancelled"
    report.finish()


def test_uncancellable_work_draws_no_cancel_control(frame):
    """A control that appears to abort and does not is worse than none."""
    report = begin_progress(frame, "uncancellable", "Closing world")
    wx.SafeYield()
    overlay = _overlay(frame)
    assert overlay._buttons.get("uncancellable") is None
    assert not report.task.cancellable
    report.finish()


def test_the_row_names_what_is_unavailable_rather_than_going_quiet(frame):
    """Where something genuinely is blocked, the row says which thing."""
    report = begin_progress(
        frame,
        "busy",
        "Running operation",
        unavailable="Another edit cannot start until this one finishes.",
    )
    wx.SafeYield()
    assert "Another edit cannot start" in _overlay(frame).GetName()
    report.finish()


# ----------------------------------------------------------------------
# outcomes
# ----------------------------------------------------------------------


def test_a_success_retires_its_row_and_a_failure_keeps_its_own(frame):
    """Errors persist until read; informational progress retires itself."""
    good = begin_progress(frame, "good", "Saving world")
    bad = begin_progress(frame, "bad", "Saving world")
    wx.SafeYield()
    overlay = _overlay(frame)
    assert {task.key for task in overlay.tasks} == {"good", "bad"}

    good.finish()
    bad.fail("The disk went away")
    wx.SafeYield()

    keys = {task.key for task in overlay.tasks}
    assert "good" not in keys, "a finished operation left a row on screen"
    assert "bad" in keys, "a failed operation took its own report down with it"
    failed = overlay.task("bad")
    assert failed.state == FAILED
    assert failed.error == "The disk went away"
    assert overlay.IsShownOnScreen(), "the failed row is not visible"
    # And it offers the only thing left to do with it.
    assert "Dismiss" in overlay._buttons["bad"].GetName()
    overlay._activate("bad")
    wx.SafeYield()
    assert overlay.task("bad") is None


def test_an_exception_inside_the_block_fails_the_row_rather_than_hiding_it(frame):
    """Failure is reported, not swallowed -- structurally, not by remembering."""
    with pytest.raises(ValueError):
        with begin_progress(frame, "boom", "Saving world"):
            raise ValueError("the level would not write")
    wx.SafeYield()
    row = _overlay(frame).task("boom")
    assert row is not None and row.state == FAILED
    assert "would not write" in row.error
    _overlay(frame).dismiss_all()


def test_a_failure_is_recorded_in_notification_history(frame):
    """The row goes when it is dismissed; the record of the failure does not."""
    from amulet_map_editor.api import notifications

    # Asserted by identity rather than by count: the store keeps at most
    # ``MAX_NOTIFICATIONS`` and a developer's profile reaches that cap, at which
    # point "one more was added" is true and the count has not moved.
    message = f"The disk went away at {time.monotonic_ns()}"
    begin_progress(frame, "logged", "Saving world").fail(message)
    wx.SafeYield()
    recorded = [
        item for item in notifications.list_notifications() if message in item.body
    ]
    assert recorded, "a failed operation left no reviewable record behind"
    assert recorded[0].severity == "error"
    assert recorded[0].title == "Saving world"
    _overlay(frame).dismiss_all()


# ----------------------------------------------------------------------
# the two bars must not look the same
# ----------------------------------------------------------------------


def _paint(overlay) -> wx.Image:
    """Render the overlay through its own drawing code, into a bitmap."""
    size = overlay.GetSize()
    bitmap = wx.Bitmap(max(1, size.width), max(1, size.height))
    dc = wx.MemoryDC(bitmap)
    dc.SetBackground(wx.Brush(wx.Colour(0, 0, 0)))
    dc.Clear()
    overlay.render_to(dc, wx.Rect(0, 0, size.width, size.height))
    dc.SelectObject(wx.NullBitmap)
    return bitmap.ConvertToImage()


def _pixels(image: wx.Image) -> bytes:
    return bytes(image.GetData())


def _bar_strip(overlay) -> bytes:
    """Return only the linear indicator's own pixels from the first row.

    Comparing whole-panel captures is not enough, and this is not hypothetical:
    the first version of these tests passed while ``draw_indeterminate_band``
    was replaced wholesale by an empty determinate bar. The two pictures did
    differ -- but by the *reading* beside the title, which says "Working…" in
    one and "0%" in the other, not by the bar the test claims to be about. The
    assertion was satisfied by the very text that makes the mistake invisible.

    So the comparison is cropped to the indicator, where a difference can only
    come from the drawing under test.
    """
    from amulet_map_editor.api.studio import progress_overlay, tokens

    image = _paint(overlay)
    height = max(1, tokens.scaled(progress_overlay.BAR_HEIGHT))
    strip = image.GetSubImage(wx.Rect(0, 0, image.GetWidth(), height))
    return bytes(strip.GetData())


def test_cannot_say_and_nothing_yet_are_drawn_differently(frame, monkeypatch):
    """ "Cannot say" is not "nothing yet", and the pixels have to agree.

    A determinate bar at zero and an indeterminate one are the two states most
    easily collapsed into one appearance, and collapsing them is a lie about
    what the application knows.  Nothing about the source can establish that
    they differ; the two pictures are compared.
    """
    from amulet_map_editor.api.studio import widgets

    monkeypatch.setattr(widgets, "reduced_motion", lambda: False)
    from amulet_map_editor.api.studio import progress_overlay as module

    monkeypatch.setattr(module, "reduced_motion", lambda: False)

    report = begin_progress(frame, "bars", "Saving world")
    wx.SafeYield()
    overlay = _overlay(frame)

    report.update(indeterminate=True)
    wx.SafeYield()
    unmeasured = _bar_strip(overlay)

    report.update(fraction=0.0)
    wx.SafeYield()
    at_zero = _bar_strip(overlay)

    report.update(fraction=0.6)
    wx.SafeYield()
    part_way = _bar_strip(overlay)

    assert unmeasured != at_zero, (
        "work that cannot report a fraction is drawn exactly like work that is "
        "at zero percent"
    )
    assert at_zero != part_way, "the determinate bar does not fill as it advances"
    report.finish()


def test_an_empty_bar_is_still_a_visible_bar(frame, monkeypatch):
    """A determinate bar at zero must be an empty track, not an absent one.

    Found by looking at a capture rather than by any assertion: the shared
    determinate bar draws its unfilled track in ``surface_container_high``, and
    the row was painted that same colour -- so at zero percent the indicator
    was invisible, and "nothing has happened yet" looked exactly like "this
    surface has no progress bar". Both of the other bar tests still passed,
    because both compare two drawings that were each equally invisible.
    """
    from amulet_map_editor.api.studio import progress_overlay, tokens

    monkeypatch.setattr(progress_overlay, "reduced_motion", lambda: False)

    report = begin_progress(frame, "empty", "Saving world", detail="region files")
    report.update(fraction=0.0)
    wx.SafeYield()
    overlay = _overlay(frame)

    image = _paint(overlay)
    bar_height = max(1, tokens.scaled(progress_overlay.BAR_HEIGHT))
    # A pixel in the middle of the track, and one in the row below it.
    x = image.GetWidth() // 2
    track = (
        image.GetRed(x, bar_height // 2),
        image.GetGreen(x, bar_height // 2),
        image.GetBlue(x, bar_height // 2),
    )
    row = (
        image.GetRed(x, bar_height + tokens.scaled(6)),
        image.GetGreen(x, bar_height + tokens.scaled(6)),
        image.GetBlue(x, bar_height + tokens.scaled(6)),
    )
    assert track != row, (
        "the empty track is the same colour as the row it sits on, so a bar at "
        f"zero percent is invisible (both {track})"
    )
    report.finish()


def test_the_travelling_band_actually_travels(frame, monkeypatch):
    """An indeterminate row animates; a determinate one does not."""
    from amulet_map_editor.api.studio import progress_overlay as module

    monkeypatch.setattr(module, "reduced_motion", lambda: False)

    report = begin_progress(frame, "band", "Closing world")
    wx.SafeYield()
    overlay = _overlay(frame)
    overlay._retune_timer()
    assert overlay._timer.IsRunning(), "an unmeasured row is not animating"

    first = _bar_strip(overlay)
    for _ in range(6):
        overlay._on_tick(None)
    moved = _bar_strip(overlay)
    assert first != moved, "the band never moved"

    report.update(fraction=0.5)
    wx.SafeYield()
    assert (
        not overlay._timer.IsRunning()
    ), "a measured row keeps animating, drawing motion that means nothing"
    report.finish()


def test_reduced_motion_still_distinguishes_cannot_say_from_zero(frame, monkeypatch):
    """Motion off must not mean "the same picture, frozen".

    A stationary band is the exact shape of a part-filled determinate bar, so a
    reader who asked for less motion would be shown a percentage that does not
    exist.  The still appearance is a different picture, and it is checked
    against the one it must not be confused with.
    """
    from amulet_map_editor.api.studio import progress_overlay as module

    monkeypatch.setattr(module, "reduced_motion", lambda: True)

    report = begin_progress(frame, "still", "Closing world")
    wx.SafeYield()
    overlay = _overlay(frame)
    overlay._retune_timer()
    assert not overlay._timer.IsRunning(), "reduced motion did not stop the animation"

    still = _bar_strip(overlay)
    report.update(fraction=0.0)
    wx.SafeYield()
    at_zero = _bar_strip(overlay)
    report.update(fraction=0.5)
    wx.SafeYield()
    half = _bar_strip(overlay)

    assert still != at_zero
    assert still != half, "the still indeterminate bar reads as a half-filled one"
    report.finish()


def test_the_overlay_photographs_as_something_rather_than_a_blank_band(frame, tmp_path):
    """A capture that reports success over an empty rectangle is a false negative.

    The overlay paints in ``EVT_PAINT``; a widget that never overrode
    ``render_to`` inherits the backdrop-only default and photographs blank while
    every structural field in the report stays healthy.  So the picture is
    checked for having more than a background in it.
    """
    capture = pytest.importorskip(
        "scripts.capture_surface", reason="the capture harness is unavailable"
    )

    report = begin_progress(
        frame,
        "shot",
        "Saving world",
        detail="Writing region r.0.0.mca",
        cancellable=True,
    )
    report.update(fraction=0.62)
    wx.SafeYield()
    overlay = _overlay(frame)
    assert overlay.IsShownOnScreen()

    destination = tmp_path / "progress-overlay.png"
    outcome = capture.capture_composite(overlay, destination)
    assert destination.exists() and destination.stat().st_size > 0
    assert not outcome.get("skipped"), f"holes in the capture: {outcome['skipped']}"
    # ``uniform_fraction`` near 1.0 is the field that sees a capture where every
    # descendant claimed to draw and nothing arrived.
    assert outcome["uniform_fraction"] < 0.98, (
        "the overlay photographed as one flat colour; it drew nothing " f"({outcome})"
    )
    assert outcome["colours"] >= capture.MIN_DISTINCT_COLOURS
    report.finish()
