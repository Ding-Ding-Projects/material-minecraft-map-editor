"""Right-click in the 3D viewport reaches the camera, not an appearance menu.

The user reported this twice, with a screenshot: right-clicking anywhere in the
world view put a small "Appearance" popup -- a search field and an "Edit
appearance…" row -- over the world.  Right-drag is how the editor rotates the
camera (``ACT_CHANGE_MOUSE_MODE`` is bound to the right button), so every
attempt to look around was opening a menu and cancelling the drag mid-motion.

Two things put it there.  The shared Material layer binds that popup to every
window it styles, and it binds it *after* the viewport has bound its own
right-click handling -- wx runs the most recently bound handler first, and this
one never skipped, so the viewport's own careful decision never ran at all.  And
the flag a control could opt out with was only read when the handler was bound,
which is too early for the renderer canvas: it is created inside the world
notebook and only later handed to the Studio viewport, so by the time anything
knew it was a renderer it was already bound.

These tests drive it.  They build a real viewport, style a real canvas the way
the application styles it, host it, and then synthesise the actual gesture.
Reading the source would not have caught this: every string these files are
searched for was present and correct while the menu was opening.

The chip test is the one that keeps the rest honest.  Turning the appearance
menu off everywhere would satisfy every other assertion here, and would lose a
capability the product requires; the HUD overlays are legitimate targets for
"Edit appearance…" and must still raise it.
"""

from __future__ import annotations

import os
import tempfile

import pytest

wx = pytest.importorskip("wx")

from amulet_map_editor.api.studio import context_menu  # noqa: E402
from amulet_map_editor.api.studio.viewport import ViewportHost  # noqa: E402
from amulet_map_editor.api.wx.material3 import apply_material3  # noqa: E402


@pytest.fixture(scope="module")
def app():
    """A live wx.App on an isolated profile, so a run cannot touch real settings."""
    os.environ.setdefault("CONFIG_DIR", tempfile.mkdtemp(prefix="amulet-viewport-"))
    application = wx.App()
    yield application


class _Canvas(wx.Panel):
    """Stands in for the editor's GL canvas: it wants the right button.

    It records what it is given rather than asserting anything, so a test can
    say both "no menu opened" and "the camera got the gesture" -- the second is
    what stops the first from passing because nothing was delivered at all.
    """

    def __init__(self, parent: wx.Window) -> None:
        super().__init__(parent, name="World renderer canvas")
        self.camera: list[str] = []
        self.Bind(wx.EVT_RIGHT_DOWN, self._record("down"))
        self.Bind(wx.EVT_MOTION, self._record("motion"))
        self.Bind(wx.EVT_RIGHT_UP, self._record("up"))

    def _record(self, name: str):
        def handler(event: wx.MouseEvent) -> None:
            self.camera.append(name)
            event.Skip()

        return handler


def _pump(application: wx.App, rounds: int = 6) -> None:
    """Let wx finish what the last call started."""
    for _ in range(rounds):
        wx.Yield()
        while application.HasPendingEvents():
            application.ProcessPendingEvents()
            wx.Yield()


def _menus(root: wx.Window) -> list[wx.Window]:
    """Every menu popup that exists anywhere under ``root``, shown or not."""
    found: list[wx.Window] = []
    stack: list[wx.Window] = [root]
    seen: set[int] = set()
    while stack:
        window = stack.pop()
        if id(window) in seen:
            continue
        seen.add(id(window))
        if type(window).__name__ in {"MaterialMenu", "SearchableContextMenu"}:
            found.append(window)
        try:
            stack.extend(window.GetChildren())
        except RuntimeError:  # pragma: no cover - torn down mid-walk
            pass
    return found


def _clear_menus(root: wx.Window, application: wx.App) -> None:
    for menu in _menus(root):
        try:
            menu.Dismiss()
        except Exception:  # pragma: no cover - already dismissed
            pass
        menu.Destroy()
    _pump(application)


def _context_menu_event(window: wx.Window, point: wx.Point) -> None:
    """Raise the event Windows raises off a right-button release."""
    event = wx.ContextMenuEvent(wx.wxEVT_CONTEXT_MENU, window.GetId())
    event.SetEventObject(window)
    event.SetPosition(window.ClientToScreen(point))
    window.GetEventHandler().ProcessEvent(event)


def _right_press(window: wx.Window, point: wx.Point, kind: int) -> None:
    event = wx.MouseEvent(kind)
    event.SetPosition(point)
    event.SetEventObject(window)
    window.GetEventHandler().ProcessEvent(event)


def _right_drag(window: wx.Window, start: wx.Point, end: wx.Point) -> None:
    """Press, travel, release: the gesture a user makes to look around."""
    _right_press(window, start, wx.wxEVT_RIGHT_DOWN)
    for step in range(1, 5):
        motion = wx.MouseEvent(wx.wxEVT_MOTION)
        motion.SetPosition(
            wx.Point(
                start.x + (end.x - start.x) * step // 4,
                start.y + (end.y - start.y) * step // 4,
            )
        )
        motion.SetRightDown(True)
        motion.SetEventObject(window)
        window.GetEventHandler().ProcessEvent(motion)
    _right_press(window, end, wx.wxEVT_RIGHT_UP)
    _context_menu_event(window, end)


def _right_click(window: wx.Window, point: wx.Point) -> None:
    _right_press(window, point, wx.wxEVT_RIGHT_DOWN)
    _right_press(window, point, wx.wxEVT_RIGHT_UP)
    _context_menu_event(window, point)


@pytest.fixture
def viewport(app):
    """A hosted viewport, built in the order the application builds one.

    The canvas is created and styled *before* it is handed to the viewport,
    because that is what really happens: the world notebook owns it first.  A
    test that styled it afterwards would never exercise the case that shipped.
    """
    frame = wx.Frame(None, size=wx.Size(1100, 760), title="viewport gesture probe")
    page = wx.Panel(frame, name="World notebook page")
    canvas = _Canvas(page)
    host = ViewportHost(frame)
    frame.Show()
    apply_material3(frame)
    _pump(app)

    # The precondition the suppression is measured against.  Without it, "no
    # menu opened" would also be true of a build where the menu was never bound
    # to anything, and this file would pass while proving nothing.
    assert getattr(canvas, "_material3_appearance_menu_bound", False) is True

    host.set_canvas(canvas)
    host.SetSize(wx.Size(1100, 700))
    host._layout_overlays()
    _pump(app)
    try:
        yield app, frame, host, canvas
    finally:
        _clear_menus(frame, app)
        frame.Destroy()
        _pump(app)


def test_a_right_drag_over_the_canvas_opens_no_menu(viewport) -> None:
    """Looking around must not raise a menu, and must reach the camera."""
    application, frame, _host, canvas = viewport
    canvas.camera.clear()

    _right_drag(canvas, wx.Point(300, 300), wx.Point(420, 360))
    _pump(application)

    assert [m.GetName() for m in _menus(frame)] == []
    # The other half: the gesture was delivered.  An empty list here would mean
    # the assertion above passed because nothing happened at all.
    assert canvas.camera[0] == "down"
    assert canvas.camera[-1] == "up"
    assert "motion" in canvas.camera


def test_a_plain_right_click_over_the_canvas_opens_no_menu(viewport) -> None:
    """Right-click changes mouse mode in the editor; the menu must not take it."""
    application, frame, _host, canvas = viewport
    canvas.camera.clear()

    _right_click(canvas, wx.Point(300, 300))
    _pump(application)

    assert [m.GetName() for m in _menus(frame)] == []
    assert canvas.camera == ["down", "up"]


def test_a_right_click_on_a_hud_chip_still_opens_the_appearance_menu(viewport) -> None:
    """The overlays keep it.  This is what stops the fix being "turn it off"."""
    application, frame, host, _canvas = viewport

    _right_click(host.world_chip, wx.Point(4, 4))
    _pump(application)

    opened = _menus(frame)
    assert [m.GetName() for m in opened] == ["Appearance menu"]
    assert opened[0].IsShownOnScreen() is True


def test_shift_right_click_over_the_viewport_still_reaches_edit_appearance(
    viewport, monkeypatch
) -> None:
    """The viewport's own appearance row survives, on the modifier gesture.

    ``wx.GetKeyState`` reads the real keyboard, which a synthesised event cannot
    change, so the modifier is stated here and the rest of the path -- the
    viewport's handler, the menu it builds, the rows in it -- is the real one.
    """
    application, frame, host, _canvas = viewport
    monkeypatch.setattr(wx, "GetKeyState", lambda key: key == wx.WXK_SHIFT)

    _right_click(host, wx.Point(300, 300))
    _pump(application)

    opened = _menus(frame)
    assert [m.GetName() for m in opened] == ["Viewport menu"]
    assert "Edit appearance…" in {row.label for row in opened[0].items}


def test_the_viewport_menu_carries_the_appearance_row() -> None:
    """The route named above is a row that exists, not one assumed to."""
    found = context_menu.menu("viewport")
    assert found is not None
    _title, items = found
    assert "Edit appearance…" in {row.label for row in items}
