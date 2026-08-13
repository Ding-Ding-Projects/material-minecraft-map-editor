"""Opening a world updates the workspace's content, not its window tree.

The reported defect was that "every element reloads" when a world opens:
visible flashing and lost user state, which reads as the ribbon, navigator,
properties pane and status bar being torn down and rebuilt from scratch.

Measured against the real :class:`StudioShell`, that is not what happens: the
five panels are constructed once and kept for the shell's whole lifetime, and
:meth:`StudioShell.attach_project` only ever pushes new content into them.
This module pins that down as a regression test -- panel identity, widget
count, the selected ribbon tab, and a resized pane must all survive a second
project attaching -- and also covers the actual, measurable freeze that
produced the same symptom: opening a world used to run a Git commit for the
recent-projects history synchronously on the UI thread on every single open.
"""

from __future__ import annotations

import os
import tempfile
import threading
import time
from typing import Iterator

import pytest

wx = pytest.importorskip("wx")

# Isolated from the real profile's local-history store, which on a machine
# that has actually used the app can hold thousands of events: this module
# is about whether *this session's* work blocks the UI, not about how large
# a store some other session left behind.
_config_dir = tempfile.TemporaryDirectory()
os.environ["CONFIG_DIR"] = _config_dir.name

from amulet_map_editor.api import config as _config

_config.invalidate()

from amulet_map_editor.api.studio.shell import StudioShell

FRAME_SIZE = (1280, 800)


def _count_widgets(win: "wx.Window") -> int:
    total = 1
    for child in win.GetChildren():
        total += _count_widgets(child)
    return total


@pytest.fixture(scope="module")
def app() -> Iterator["wx.App"]:
    existing = wx.App.Get()
    created = None
    if existing is None:
        created = wx.App()
    yield existing or created
    if created is not None:
        created.Destroy()


@pytest.fixture(autouse=True)
def _own_profile(monkeypatch: "pytest.MonkeyPatch") -> Iterator[None]:
    """Count widgets against a profile no other test has written to.

    This file asserts an exact widget count, which makes it the one file in
    the suite that cannot tolerate inherited state. It passed alone and failed
    in the full run at 217 against an expected 216 -- one extra widget,
    contributed by whatever an earlier test had left in the shared profile
    (a recent project, a pinned tab, a stored preference). The shell reads
    those stores when it builds, so its widget count is a function of them.

    An order-dependent failure like that is worse than a plain one: it points
    at the wrong file, it reproduces only in a twenty-minute run, and the
    obvious next step is to loosen the assertion -- which would throw away the
    only check that would notice a widget genuinely leaking on every world
    open.
    """
    import tempfile

    profile = tempfile.mkdtemp(prefix="amulet-workspace-test-")
    for store in (
        "CONFIG_DIR",
        "DATA_DIR",
        "CACHE_DIR",
        "AMULET_RECENTS_DIR",
        "AMULET_HISTORY_DIR",
    ):
        monkeypatch.setenv(store, profile)
    yield


@pytest.fixture
def shell(app: "wx.App") -> Iterator["StudioShell"]:
    frame = wx.Frame(None, size=wx.Size(*FRAME_SIZE))
    try:
        panel = StudioShell(frame, frame)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(panel, 1, wx.EXPAND)
        frame.SetSizer(sizer)
        frame.Show()
        frame.Layout()
        wx.Yield()
        yield panel
    finally:
        frame.Destroy()
        wx.Yield()


def test_a_second_world_reuses_every_panel_and_widget(shell: "StudioShell") -> None:
    shell.attach_project("First World", "C:/fake/first", "java")
    wx.Yield()

    panels_before = (
        shell.workspace,
        shell.workspace.ribbon,
        shell.workspace.navigator,
        shell.workspace.properties,
        shell.workspace.viewport,
        shell.workspace.status,
    )
    identities_before = {id(panel) for panel in panels_before}
    # Counted from the workspace, not the whole shell: the backstage's own
    # "Recent" table legitimately grows by one row every time a genuinely new,
    # distinct project is opened (that is the point of a recent-projects
    # list), so a count taken from `shell` conflates that honest growth with
    # the defect this test actually guards -- whether the *workspace* panels
    # get torn down and rebuilt. Scoping to `shell.workspace` keeps the
    # assertion about the thing it was written to catch.
    widgets_before = _count_widgets(shell.workspace)

    shell.attach_project("Second World", "C:/fake/second", "java")
    wx.Yield()

    panels_after = (
        shell.workspace,
        shell.workspace.ribbon,
        shell.workspace.navigator,
        shell.workspace.properties,
        shell.workspace.viewport,
        shell.workspace.status,
    )
    identities_after = {id(panel) for panel in panels_after}
    widgets_after = _count_widgets(shell.workspace)

    assert identities_after == identities_before, (
        "opening a second world replaced the workspace's own panels instead of "
        "refreshing their content"
    )
    assert widgets_after == widgets_before, (
        f"opening a second world changed the widget count from {widgets_before} "
        f"to {widgets_after}; the panels should refresh in place"
    )


def test_the_selected_ribbon_tab_survives_a_world_open(shell: "StudioShell") -> None:
    shell.attach_project("First World", "C:/fake/first", "java")
    wx.Yield()
    shell.workspace.set_ribbon_tab("selection")
    wx.Yield()
    before = shell.workspace.ribbon.active_tab

    shell.attach_project("Second World", "C:/fake/second", "java")
    wx.Yield()

    assert (
        shell.workspace.ribbon.active_tab == before == "selection"
    ), "opening a second world reset the selected ribbon tab back to home"


def test_a_dragged_pane_width_survives_a_world_open(shell: "StudioShell") -> None:
    shell.attach_project("First World", "C:/fake/first", "java")
    wx.Yield()
    shell.workspace.set_pane_width("navigator", 260, persist=False)
    before = shell.workspace.pane_width("navigator")

    shell.attach_project("Second World", "C:/fake/second", "java")
    wx.Yield()

    after = shell.workspace.pane_width("navigator")
    assert after == before, (
        f"opening a second world changed the navigator pane width from "
        f"{before} to {after} instead of leaving what the user set alone"
    )


def test_recording_a_recent_project_does_not_block_the_caller(monkeypatch) -> None:
    """``RecentStore._record`` used to run its Git commit inline.

    ``recents.add`` is called synchronously every time a world opens.  On a
    profile whose local history has accumulated real events that commit can
    cost hundreds of milliseconds of real subprocess time -- one of the
    contributors to the freeze the "everything reloads" report actually
    described.  The write has no visible effect of its own, so it is proven
    here to run off the caller's thread: a deliberately slow
    ``safe_record`` must not be able to make ``add`` slow.
    """
    from amulet_map_editor.api.studio import recents as recents_module

    released = threading.Event()

    def _slow_safe_record(*args, **kwargs):
        released.wait(timeout=2.0)

    monkeypatch.setattr(recents_module.local_history, "safe_record", _slow_safe_record)

    store = recents_module.RecentStore(tempfile.mkdtemp())
    t0 = time.perf_counter()
    store.add("A World", kind="world", path="C:/fake/a-world")
    elapsed = time.perf_counter() - t0

    released.set()
    assert elapsed < 0.5, (
        f"RecentStore.add took {elapsed * 1000:.0f} ms while its history "
        "commit was blocked; the commit must run off the caller's thread"
    )


def test_refresh_history_does_not_block_on_a_slow_events_read(
    shell: "StudioShell", monkeypatch
) -> None:
    """``PropertiesPane.refresh_history`` used to read the whole event store
    synchronously on the UI thread every time a world opened. On a profile
    with 1000+ recorded events that first read cost real, measurable wall
    time inside ``properties_pane.refresh_history()``. This pins the fix down:
    a deliberately slow ``load_project_revisions`` must not be able to make
    ``refresh_history`` itself slow, because the read now happens on a
    background thread and lands through ``wx.CallAfter``.
    """
    from amulet_map_editor.api.studio import properties_pane as pane_module

    released = threading.Event()
    called = threading.Event()

    def _slow_load_project_revisions(project_key, *, refresh=False):
        called.set()
        released.wait(timeout=2.0)
        return (), True

    monkeypatch.setattr(
        pane_module, "load_project_revisions", _slow_load_project_revisions
    )
    # Force the cold path: refresh_history takes a fast synchronous shortcut
    # when the project's history is already sitting in the module cache.
    monkeypatch.setattr(pane_module, "project_history_cached", lambda key: False)

    shell.attach_project("Slow History World", "C:/fake/slow-history", "java")
    pane = shell.workspace.properties

    t0 = time.perf_counter()
    pane.refresh_history()
    elapsed = time.perf_counter() - t0

    assert called.wait(timeout=1.0), "refresh_history never reached the slow read"
    assert elapsed < 0.5, (
        f"PropertiesPane.refresh_history took {elapsed * 1000:.0f} ms while "
        "its event read was blocked; the read must run off the caller's thread"
    )
    # While the background read is still running, the pane must say so rather
    # than showing an empty list that looks identical to "no history at all".
    assert pane._history_loading is True
    assert pane._history_note() == pane_module.READING_HISTORY

    released.set()
    for _ in range(200):
        wx.Yield()
        if not pane._history_loading:
            break
        time.sleep(0.01)
    assert not pane._history_loading, "the background history read never landed"


def test_a_stale_history_read_never_overwrites_a_newer_one(
    shell: "StudioShell", monkeypatch
) -> None:
    """Two overlapping reads must not race their results into the pane.

    Opening a second world while the first world's history read is still in
    flight must not let that first, now-stale, read land its result over the
    second world's -- a generation counter (or equivalent guard) must reject
    it.
    """
    from amulet_map_editor.api.studio import properties_pane as pane_module

    first_released = threading.Event()
    calls = []

    def _load(project_key, *, refresh=False):
        calls.append(project_key)
        if project_key == "slow-first":
            first_released.wait(timeout=2.0)
            return (
                (
                    pane_module.ProjectRevision(
                        commit="stale",
                        message="a stale first-world revision",
                        meta="",
                    ),
                ),
                True,
            )
        return ((), True)

    monkeypatch.setattr(pane_module, "load_project_revisions", _load)
    monkeypatch.setattr(pane_module, "project_history_cached", lambda key: False)

    shell.attach_project("First Slow World", "C:/fake/slow-first", "java")
    pane = shell.workspace.properties
    monkeypatch.setattr(pane, "active_project_key", lambda: "slow-first")
    pane.refresh_history()

    # Before the slow first read has returned, point the pane at a second
    # project and refresh again -- this is the newer, wanted request.
    monkeypatch.setattr(pane, "active_project_key", lambda: "second")
    pane.refresh_history()
    for _ in range(200):
        wx.Yield()
        if not pane._history_loading:
            break
        time.sleep(0.01)
    assert not pane._history_loading

    # Now let the stale first read return. Its result must be discarded
    # because a newer refresh has since started.
    first_released.set()
    for _ in range(200):
        wx.Yield()
        time.sleep(0.005)

    assert not any(
        revision.commit == "stale" for revision in pane._live_revisions
    ), "a stale, superseded history read overwrote the newer one's result"


def test_refresh_revision_does_not_block_on_a_slow_events_read(
    shell: "StudioShell", monkeypatch
) -> None:
    """The status bar's revision pill has the same defect shape as the
    Properties pane's history did: ``StatusBar.refresh_revision`` read the
    whole event store synchronously, and ``apply_context`` reaches it on the
    thread wx paints on while a project is being attached. A deliberately slow
    ``project_history_events`` must not be able to make ``refresh_revision``
    itself slow, and while the read is in flight the pill must say it is
    reading rather than claiming the project has no revisions.
    """
    from amulet_map_editor.api.studio import status_bar as bar_module

    released = threading.Event()
    called = threading.Event()

    def _slow_events(project_key, *, refresh=False):
        called.set()
        released.wait(timeout=2.0)
        return (), True

    monkeypatch.setattr(bar_module, "project_history_events", _slow_events)
    # Force the cold path: a cached history is answered synchronously, which is
    # the fast case this test is deliberately not measuring.
    monkeypatch.setattr(bar_module, "project_history_cached", lambda key: False)
    monkeypatch.setattr(bar_module, "project_key_for", lambda ctx=None: "slow-world")

    shell.attach_project("Slow Revision World", "C:/fake/slow-revision", "java")
    bar = shell.workspace.status

    t0 = time.perf_counter()
    bar.refresh_revision()
    elapsed = time.perf_counter() - t0

    assert called.wait(timeout=1.0), "refresh_revision never reached the slow read"
    assert elapsed < 0.5, (
        f"StatusBar.refresh_revision took {elapsed * 1000:.0f} ms while its "
        "event read was blocked; the read must run off the caller's thread"
    )
    # "No revisions yet" during the wait would be a claim the bar has not yet
    # earned, and looks identical to the finished answer.
    assert bar.revision.loading is True
    assert bar.revision.GetLabel() == bar_module.READING_REVISIONS

    released.set()
    for _ in range(200):
        wx.Yield()
        if not bar.revision.loading:
            break
        time.sleep(0.01)
    assert not bar.revision.loading, "the background revision read never landed"


def test_a_stale_revision_read_never_overwrites_a_newer_one(
    shell: "StudioShell", monkeypatch
) -> None:
    """A slow first read must not land its answer over a newer world's."""
    from amulet_map_editor.api.studio import status_bar as bar_module

    class _Event:
        def __init__(self, event_id: str) -> None:
            self.event_id = event_id

    first_released = threading.Event()
    keys = {"current": "slow-first"}

    def _events(project_key, *, refresh=False):
        if project_key == "slow-first":
            first_released.wait(timeout=2.0)
            return (_Event("stale123"),), True
        return (), True

    monkeypatch.setattr(bar_module, "project_history_events", _events)
    monkeypatch.setattr(bar_module, "project_history_cached", lambda key: False)
    monkeypatch.setattr(bar_module, "project_key_for", lambda ctx=None: keys["current"])

    shell.attach_project("First Slow World", "C:/fake/slow-first", "java")
    bar = shell.workspace.status
    bar.refresh_revision()

    # A second world arrives before the first read has returned.
    keys["current"] = "second"
    bar.refresh_revision()
    for _ in range(200):
        wx.Yield()
        if not bar.revision.loading:
            break
        time.sleep(0.01)
    assert not bar.revision.loading

    first_released.set()
    for _ in range(200):
        wx.Yield()
        time.sleep(0.005)

    assert (
        bar.revision.commit != "stale12"
    ), "a stale, superseded revision read overwrote the newer one's result"
