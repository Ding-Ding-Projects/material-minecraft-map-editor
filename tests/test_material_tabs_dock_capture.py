"""Build the real painted tab strip and capture it at every dock edge.

Source text can say the strip docks to any edge; it proves nothing about
whether tabs actually draw there. This constructs a real ``MaterialTabs`` on
a real ``wx.Frame``, adds real tabs, docks it to each of the four edges in
turn, and reads the composited PNG back to confirm drawn tab rows rather than
an empty strip.

It also exercises the two things a screenshot cannot show: the strip's
projected ARIA orientation, and which arrow keys move focus along the strip's
own axis.

``CONFIG_DIR`` is forced with ``monkeypatch.setenv`` rather than
``os.environ.setdefault``. Importing ``amulet_map_editor`` sets a real
default -- the actual per-user AmuletMapEditor config directory -- before
this module's own fixtures run, so a ``setdefault`` here is a silent no-op
and every persisted tab-state write in this file lands in the real profile
instead of a throwaway one. That is not hypothetical: it is exactly what
happened while this file was first written, and cleaning up the polluted
real profile is what proved it.
"""

from __future__ import annotations

import os
import sys
import tempfile

import pytest

wx = pytest.importorskip("wx", reason="wxPython is not installed in this environment")

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import amulet_map_editor  # noqa: E402

assert amulet_map_editor.__file__.startswith(REPO)

from amulet_map_editor.api import tab_groups  # noqa: E402
from amulet_map_editor.api.wx.ui.material_tabs import MaterialTabs  # noqa: E402
from scripts.capture_surface import capture_composite  # noqa: E402
from scripts.capture_surface import settle as capture_surface_settle  # noqa: E402

OFFSCREEN = wx.Point(-31900, -31900)

DOCKS = [
    tab_groups.TabDock.LEFT,
    tab_groups.TabDock.RIGHT,
    tab_groups.TabDock.TOP,
    tab_groups.TabDock.BOTTOM,
]


@pytest.fixture(scope="module")
def app():
    existing = wx.App.Get()
    created = existing is None and wx.App()
    yield existing or created
    if created:
        created.Destroy()


@pytest.fixture
def frame(app, monkeypatch, tmp_path_factory):
    # A forced assignment, not ``setdefault``: importing ``amulet_map_editor``
    # has already set ``CONFIG_DIR`` to the real per-user profile directory,
    # so anything less than an override here writes this test's tab state
    # into that real, persistent file.
    monkeypatch.setenv(
        "CONFIG_DIR", str(tmp_path_factory.mktemp("amulet-tabs-ui-config"))
    )
    win = wx.Frame(None, size=(760, 520))
    win.SetPosition(OFFSCREEN)
    win.Show()
    capture_surface_settle(win)
    yield win
    win.Destroy()


def _build_tabs(frame, surface_id: str) -> MaterialTabs:
    tabs = MaterialTabs(frame, surface_id)
    for title in (
        "World Editor",
        "Structure Blocks",
        "Chunk Inspector",
        "Import/Export",
    ):
        page = wx.Panel(tabs)
        page.SetBackgroundColour(wx.Colour(240, 240, 240))
        tabs.AddPage(page, title)
    tabs.SetSize(frame.GetClientSize())
    capture_surface_settle(tabs)
    return tabs


@pytest.mark.parametrize("dock", DOCKS)
def test_tab_strip_captures_at_every_dock_edge(frame, dock, tmp_path):
    surface_id = f"dock-capture-{dock.value}"
    tabs = _build_tabs(frame, surface_id)
    tabs.set_dock(dock)
    tabs.SetSize(frame.GetClientSize())
    capture_surface_settle(tabs)

    png_path = tmp_path / f"material_tabs_{dock.value}.png"
    report = capture_composite(tabs, png_path)

    assert png_path.exists()
    assert png_path.stat().st_size > 0

    import wx as _wx

    image = _wx.Image(str(png_path))
    assert image.IsOk()
    assert image.GetWidth() > 0 and image.GetHeight() > 0

    # A blank strip -- reported success with nothing drawn -- is the one
    # failure the structural fields below cannot see on their own.
    assert report["uniform_fraction"] < 0.98, (
        f"{dock.value} dock composited as {report['uniform_fraction']:.3f} "
        "uniform; the strip looks blank"
    )
    assert report["descendants"] >= len(tabs._order)
    assert not report["skipped"], f"{dock.value} dock skipped: {report['skipped']}"


def test_strip_orientation_is_vertical_when_docked_left_or_right(frame):
    tabs = _build_tabs(frame, "orientation-left-right")
    for dock in (tab_groups.TabDock.LEFT, tab_groups.TabDock.RIGHT):
        tabs.set_dock(dock)
        assert tabs.vertical is True
        assert tabs.strip.GetName() == "Tab strip, vertical"
        assert tab_groups.tab_strip_aria(dock)["aria-orientation"] == "vertical"


def test_strip_orientation_is_horizontal_when_docked_top_or_bottom(frame):
    tabs = _build_tabs(frame, "orientation-top-bottom")
    for dock in (tab_groups.TabDock.TOP, tab_groups.TabDock.BOTTOM):
        tabs.set_dock(dock)
        assert tabs.vertical is False
        assert tabs.strip.GetName() == "Tab strip, horizontal"
        assert tab_groups.tab_strip_aria(dock)["aria-orientation"] == "horizontal"


def test_arrow_keys_follow_the_strip_axis(frame):
    """Up/Down move focus when vertical; Left/Right move it when horizontal.

    Goes through ``_TabButton._on_key_down`` -- the real gate that decides
    whether a key is even forwarded to ``_move_focus`` -- rather than calling
    ``_move_focus`` directly, since that gate is exactly what proves the
    "wrong" arrow keys do nothing on a given axis.
    """
    tabs = _build_tabs(frame, "arrow-key-axis")
    order = list(tabs._order)

    def press(tab_id: str, key_code: int) -> None:
        button = tabs._buttons[tab_id]
        event = wx.KeyEvent(wx.EVT_KEY_DOWN.typeId)
        event.SetEventObject(button)
        event.SetKeyCode(key_code)
        button._on_key_down(event)

    tabs.set_dock(tab_groups.TabDock.LEFT)
    tabs.select_tab(order[0])
    press(order[0], wx.WXK_DOWN)
    assert tabs._selection == 1
    press(order[1], wx.WXK_UP)
    assert tabs._selection == 0
    # The horizontal keys must not move a vertical strip.
    before = tabs._selection
    press(order[0], wx.WXK_RIGHT)
    assert tabs._selection == before

    tabs.set_dock(tab_groups.TabDock.TOP)
    tabs.select_tab(order[0])
    press(order[0], wx.WXK_RIGHT)
    assert tabs._selection == 1
    press(order[1], wx.WXK_LEFT)
    assert tabs._selection == 0
    # The vertical keys must not move a horizontal strip.
    before = tabs._selection
    press(order[0], wx.WXK_DOWN)
    assert tabs._selection == before


def test_no_tab_label_is_rotated(frame):
    """A tab button never rotates its title, on any dock edge."""
    tabs = _build_tabs(frame, "no-rotation")
    for dock in DOCKS:
        tabs.set_dock(dock)
        for button in tabs._buttons.values():
            assert button.tab.title != ""  # sanity: has a title to draw
        capture_surface_settle(tabs)
        # render_to draws with DrawText, which wx never rotates on this
        # code path; the guard here is that the drawing code path taken is
        # the plain DrawText one and not a rotated-DC variant. Source proof:
        import inspect

        from amulet_map_editor.api.wx.ui.material_tabs import _TabButton

        source = inspect.getsource(_TabButton.render_to)
        assert "RotateBoundingBox" not in source
        assert "SetTextRotation" not in source


def test_overflow_measures_the_strip_axis_when_vertical(frame):
    """The overflow surface's budget is height when vertical, width when not."""
    tabs = MaterialTabs(frame, "overflow-axis-measure")
    for index in range(12):
        page = wx.Panel(tabs)
        tabs.AddPage(page, f"Tab {index}")
    tabs.set_dock(tab_groups.TabDock.LEFT)
    tabs.SetSize(200, 240)
    capture_surface_settle(tabs)
    assert tabs.vertical is True
    assert tabs._overflowed, "expected some tabs to overflow a narrow vertical strip"

    tabs.set_dock(tab_groups.TabDock.TOP)
    tabs.SetSize(200, 240)
    capture_surface_settle(tabs)
    assert tabs.vertical is False
    assert tabs._overflowed, "expected some tabs to overflow a narrow horizontal strip"
