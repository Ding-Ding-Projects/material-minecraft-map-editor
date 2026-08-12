"""The heads-up overlays must be movable, and this drives them to prove it.

Every assertion here builds a real :class:`ViewportHost`, moves something, and
reads the geometry back.  None of it reads source text, because source text
cannot tell a control that moves from a control that has a method named as
though it moves: the whole class of defect this file exists to catch looks
perfect in a grep.

Two rules shape the awkward-looking bits.

**A guard nobody has watched fail proves nothing.**  The test that a drag does
not rotate the camera would pass just as happily if the camera callback had
been unwired, so it first proves the callback is live by turning the camera the
ordinary way and watching it fire.  Same for the minimap: before asserting that
a drag left its click alone, it proves the click works at all.

**IsShown() is relative.**  Every visibility question here asks
``IsShownOnScreen()``, which walks the ancestor chain, because a control inside
a hidden parent answers ``True`` to the other one.
"""

from __future__ import annotations

import os
import tempfile
from typing import List, Tuple

import pytest

wx = pytest.importorskip("wx", reason="wxPython is not installed in this environment")

from amulet_map_editor.api.studio import tokens, viewport  # noqa: E402

#: Off-screen, so a run on a visible desktop never throws a window at anybody.
OFFSCREEN = wx.Point(-32000, -32000)

#: Big enough that every overlay group clears its own minimum and is laid out.
BIG = wx.Size(900, 640)


@pytest.fixture(scope="module")
def app():
    """A live wx.App on an isolated profile, so a run cannot touch real settings."""
    os.environ["CONFIG_DIR"] = tempfile.mkdtemp(prefix="amulet-overlay-drag-")
    # Reuse a live ``wx.App`` when the session already has one, and only
    # create -- and later destroy -- a fresh instance when it does not.
    # Unconditionally creating a second ``wx.App`` while one is already
    # current silently orphans it, and destroying that second instance then
    # clears wx's notion of "the current app" out from under every other
    # test module -- the exact sequence that corrupts wxPython's SIP class
    # table for platform-native widgets such as ``wx.PopupTransientWindow``.
    existing = wx.App.Get()
    created = existing is None and wx.App()
    yield existing or created
    if created:
        created.Destroy()


@pytest.fixture
def profile(app, tmp_path):
    """Point the config at an empty directory for one test."""
    previous = os.environ.get("CONFIG_DIR")
    os.environ["CONFIG_DIR"] = str(tmp_path)
    try:
        yield str(tmp_path)
    finally:
        if previous is None:
            os.environ.pop("CONFIG_DIR", None)
        else:
            os.environ["CONFIG_DIR"] = previous


def build_host(size: wx.Size = BIG, **kwargs) -> Tuple[wx.Frame, viewport.ViewportHost]:
    """Return a shown frame and the viewport filling it."""
    frame = wx.Frame(None, pos=OFFSCREEN, size=size)
    host = viewport.ViewportHost(frame, **kwargs)
    sizer = wx.BoxSizer(wx.VERTICAL)
    sizer.Add(host, 1, wx.EXPAND)
    frame.SetSizer(sizer)
    frame.Show()
    frame.Layout()
    wx.Yield()
    return frame, host


def client_rect(host: viewport.ViewportHost) -> wx.Rect:
    width, height = host.GetClientSize()
    return wx.Rect(0, 0, width, height)


def press(grip: viewport.OverlayGrip, point: wx.Point) -> None:
    """Put the pointer down on ``grip`` at a point inside it."""
    event = wx.MouseEvent(wx.wxEVT_LEFT_DOWN)
    event.SetEventObject(grip)
    event.SetPosition(point)
    grip.GetEventHandler().ProcessEvent(event)


def drag(grip: viewport.OverlayGrip, point: wx.Point) -> None:
    """Move the pointer to a point expressed inside ``grip``'s own client area."""
    event = wx.MouseEvent(wx.wxEVT_MOTION)
    event.SetEventObject(grip)
    event.SetPosition(point)
    event.SetLeftDown(True)
    grip.GetEventHandler().ProcessEvent(event)


def release(grip: viewport.OverlayGrip, point: wx.Point) -> None:
    event = wx.MouseEvent(wx.wxEVT_LEFT_UP)
    event.SetEventObject(grip)
    event.SetPosition(point)
    grip.GetEventHandler().ProcessEvent(event)


def drag_by(grip: viewport.OverlayGrip, dx: int, dy: int) -> None:
    """Drag ``grip`` by a pixel delta, through its real event handlers.

    A real ``EVT_MOTION`` carries the pointer's position **inside the window
    the event went to**, and while a drag is in flight that window is moving
    under the pointer.  So the pointer is tracked here in the viewport's
    coordinates -- which is where it really is -- and converted against the
    grip's live position for each event.  Modelling it the other way round,
    as a fixed offset from the grab point, silently reports a fraction of the
    movement: the first motion moves the grip, and every later one is then
    measured from somewhere the pointer has already been.
    """
    size = grip.GetSize()
    grab = wx.Point(size.width // 2, size.height // 2)
    start = grip.GetPosition() + grab
    press(grip, grab)
    steps = 6
    for step in range(1, steps + 1):
        pointer = wx.Point(start.x + dx * step // steps, start.y + dy * step // steps)
        drag(grip, pointer - grip.GetPosition())
    release(grip, wx.Point(start.x + dx, start.y + dy) - grip.GetPosition())


def inward(group: viewport.OverlayGroup, dx: int, dy: int) -> Tuple[int, int]:
    """Return a delta that moves ``group`` away from the corner it starts in.

    A group already sixteen pixels from the bottom-right corner cannot move
    down and right, and must not: the clamp is doing its job. Testing movement
    with a fixed positive delta would therefore assert the clamp for two groups
    and the drag for the other two, and read as a drag test for all four.
    """
    return (
        dx if group.anchor_x == "left" else -dx,
        dy if group.anchor_y == "top" else -dy,
    )


def key(grip: viewport.OverlayGrip, code: int, *, shift: bool = False) -> None:
    event = wx.KeyEvent(wx.wxEVT_KEY_DOWN)
    event.SetEventObject(grip)
    event.SetKeyCode(code)
    event.SetShiftDown(shift)
    grip.GetEventHandler().ProcessEvent(event)
    up = wx.KeyEvent(wx.wxEVT_KEY_UP)
    up.SetEventObject(grip)
    up.SetKeyCode(code)
    up.SetShiftDown(shift)
    grip.GetEventHandler().ProcessEvent(up)


# ---------------------------------------------------------------------------
# there is something to grab, and it says what it does
# ---------------------------------------------------------------------------


def test_every_movable_overlay_group_has_a_grip(profile) -> None:
    """Each group ships a real, visible, focusable handle."""
    frame, host = build_host()
    try:
        assert viewport.OVERLAY_GROUPS, "No overlay group is declared as movable."
        for group in viewport.OVERLAY_GROUPS:
            grip = host.grips[group.key]
            assert grip.IsShownOnScreen(), (
                f"The {group.key} grip is not on screen, so there is nothing to "
                "grab and nothing for the keyboard to reach either."
            )
            assert grip.AcceptsFocusFromKeyboard(), (
                f"The {group.key} grip refuses keyboard focus, so its arrow keys "
                "can never be pressed."
            )
            assert grip.GetSize().width > 0 and grip.GetSize().height > 0
    finally:
        frame.Destroy()


def test_a_grip_states_its_keyboard_step_where_it_can_be_read(profile) -> None:
    """The step is on the surface, in the name, and in the tooltip."""
    frame, host = build_host()
    try:
        step = str(host.overlay_step(False))
        large = str(host.overlay_step(True))
        grip = host.grips["readouts"]
        name = grip.GetName()
        assert step in name and large in name, (
            "The grip's accessible name does not state how far an arrow key "
            f"moves it: {name!r}"
        )
        tip = grip.GetToolTip()
        assert tip is not None and step in tip.GetTip()

        hint = viewport.overlay_hint_text()
        assert step in hint and large in hint
        # And it is a control on the view, not only an attribute -- a step
        # nobody can see is not "stated on the surface".
        assert step in host.overlay_hint.text()
    finally:
        frame.Destroy()


def test_the_hint_appears_when_a_grip_is_focused(profile) -> None:
    """Focus a grip and the sentence explaining the keys shows itself."""
    frame, host = build_host()
    try:
        assert not host.overlay_hint.IsShownOnScreen(), (
            "The hint is showing before anything was focused, so it is "
            "permanent clutter rather than an affordance."
        )
        host.grips["axes"].SetFocus()
        wx.Yield()
        assert host.overlay_hint.IsShownOnScreen()
        assert client_rect(host).Contains(host.overlay_hint.GetRect())
    finally:
        frame.Destroy()


# ---------------------------------------------------------------------------
# the pointer moves it
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("group", viewport.OVERLAY_GROUPS, ids=lambda g: g.key)
def test_dragging_a_grip_moves_its_overlay(
    profile, group: viewport.OverlayGroup
) -> None:
    """Drag from A to B and the whole group is at B, members included."""
    frame, host = build_host()
    try:
        dx, dy = inward(group, 40, 60)
        before = host.overlay_rect(group.key)
        members = [member.GetRect() for member in host.overlay_members(group.key)]
        assert members, f"The {group.key} group has no members to move."

        drag_by(host.grips[group.key], dx, dy)

        after = host.overlay_rect(group.key)
        assert (after.x, after.y) != (before.x, before.y), (
            f"The {group.key} overlay did not move at all when its grip was " "dragged."
        )
        assert after.x == before.x + dx and after.y == before.y + dy, (
            f"The {group.key} overlay moved to {after.x, after.y}, not to the "
            f"{before.x + dx, before.y + dy} the pointer travelled to."
        )
        moved = [member.GetRect() for member in host.overlay_members(group.key)]
        for was, now in zip(members, moved):
            assert (now.x - was.x, now.y - was.y) == (
                dx,
                dy,
            ), "A member of the group stayed behind, so the group came apart."
    finally:
        frame.Destroy()


def test_a_drag_toward_the_edge_stops_inside_the_view(profile) -> None:
    """Nothing can be dragged somewhere the pointer could not reach it again."""
    frame, host = build_host()
    try:
        view = client_rect(host)
        for group in viewport.OVERLAY_GROUPS:
            drag_by(host.grips[group.key], 4000, 4000)
            rect = host.overlay_rect(group.key)
            assert view.Contains(rect), (
                f"The {group.key} overlay was dragged off the view to {rect}; "
                f"the view is {view}."
            )
            drag_by(host.grips[group.key], -4000, -4000)
            rect = host.overlay_rect(group.key)
            assert view.Contains(
                rect
            ), f"The {group.key} overlay was dragged off the top-left to {rect}."
    finally:
        frame.Destroy()


def test_a_shrunk_window_pulls_a_parked_overlay_back_into_view(profile) -> None:
    """An overlay parked bottom-right of a big window survives the window shrinking."""
    frame, host = build_host(wx.Size(900, 640))
    try:
        drag_by(host.grips["readouts"], 4000, 4000)
        parked = host.overlay_rect("readouts")
        assert parked.GetRight() > 400 and parked.GetBottom() > 300, (
            "The overlay was not actually parked near the far corner, so the "
            "shrink below would prove nothing."
        )

        frame.SetSize(wx.Size(520, 380))
        frame.Layout()
        wx.Yield()

        view = client_rect(host)
        assert view.width < 900
        rect = host.overlay_rect("readouts")
        assert view.Contains(rect), (
            f"After the window shrank to {view.width}x{view.height} the overlay "
            f"is at {rect}, outside it -- unreachable."
        )
        assert host.grips["readouts"].IsShownOnScreen()
    finally:
        frame.Destroy()


def test_nothing_escapes_the_view_at_any_size(profile) -> None:
    """Park every group in the far corner, then squeeze the window right down.

    One size proves one size.  This sweep found a real defect the fixed-size
    tests above could not: the readout row measured itself as all four chips
    even at widths where only two of them are drawn, so the group was clamped
    against a width it did not have and its recorded rectangle sat outside the
    view while every chip inside it was drawn correctly.  A rectangle that
    disagrees with the pixels is worse than either of them being wrong.
    """
    frame, host = build_host(wx.Size(960, 620))
    try:
        for group in viewport.OVERLAY_GROUPS:
            host.place_overlay(group.key, 9999, 9999)
            host.commit_overlay(group.key)

        escaped = []
        laid_out = 0
        for width, height in (
            (1200, 800),
            (760, 500),
            (520, 380),
            (480, 300),
            (360, 260),
            (300, 200),
            (240, 160),
        ):
            frame.SetSize(wx.Size(width, height))
            frame.Layout()
            wx.Yield()
            view = client_rect(host)
            for group in viewport.OVERLAY_GROUPS:
                grip = host.grips[group.key]
                if not grip.IsShownOnScreen():
                    continue
                laid_out += 1
                rect = host.overlay_rect(group.key)
                if not view.Contains(rect):
                    escaped.append(f"{width}x{height} {group.key} group {rect}")
                if not view.Contains(grip.GetRect()):
                    escaped.append(f"{width}x{height} {group.key} grip")
                for member in host.overlay_members(group.key):
                    if member.IsShownOnScreen() and not view.Contains(member.GetRect()):
                        escaped.append(
                            f"{width}x{height} {group.key}/{member.GetName()[:24]}"
                        )
        assert laid_out, (
            "Every group was hidden at every size, so this swept nothing and "
            "would pass with the clamp deleted."
        )
        assert not escaped, "Laid out beyond the view: " + "; ".join(escaped)
    finally:
        frame.Destroy()


# ---------------------------------------------------------------------------
# the keyboard does everything the pointer does
# ---------------------------------------------------------------------------


def test_arrow_keys_move_an_overlay_by_the_step_they_advertise(profile) -> None:
    """Every direction, and the large step, at the exact advertised distance."""
    frame, host = build_host()
    try:
        grip = host.grips["axes"]
        step = host.overlay_step(False)
        large = host.overlay_step(True)
        assert step > 0 and large > step

        start = host.overlay_rect("axes")
        key(grip, wx.WXK_RIGHT)
        assert host.overlay_rect("axes").x == start.x + step
        key(grip, wx.WXK_UP)
        assert host.overlay_rect("axes").y == start.y - step
        key(grip, wx.WXK_LEFT)
        key(grip, wx.WXK_DOWN)
        assert (host.overlay_rect("axes").x, host.overlay_rect("axes").y) == (
            start.x,
            start.y,
        )

        key(grip, wx.WXK_RIGHT, shift=True)
        assert host.overlay_rect("axes").x == start.x + large, (
            "Shift and an arrow moved the overlay by the small step, so the "
            "large step the grip advertises does not exist."
        )
    finally:
        frame.Destroy()


def test_the_keyboard_is_bounded_exactly_as_the_pointer_is(profile) -> None:
    """Holding an arrow down cannot walk an overlay out of the view."""
    frame, host = build_host()
    try:
        grip = host.grips["tools"]
        for _ in range(200):
            key(grip, wx.WXK_DOWN, shift=True)
            key(grip, wx.WXK_RIGHT, shift=True)
        view = client_rect(host)
        assert view.Contains(host.overlay_rect("tools"))
    finally:
        frame.Destroy()


def test_home_resets_one_overlay_and_shift_home_resets_all(profile) -> None:
    """The shipped layout is one key away, for one group and for every group."""
    frame, host = build_host()
    try:
        shipped = {
            group.key: host.overlay_rect(group.key) for group in viewport.OVERLAY_GROUPS
        }
        for group in viewport.OVERLAY_GROUPS:
            drag_by(host.grips[group.key], *inward(group, 30, 30))
            assert host.overlay_rect(group.key) != shipped[group.key]

        key(host.grips["axes"], wx.WXK_HOME)
        assert host.overlay_rect("axes") == shipped["axes"]
        assert (
            host.overlay_rect("tools") != shipped["tools"]
        ), "Resetting one overlay reset another one too."

        key(host.grips["tools"], wx.WXK_HOME, shift=True)
        for group in viewport.OVERLAY_GROUPS:
            assert (
                host.overlay_rect(group.key) == shipped[group.key]
            ), f"Shift+Home left the {group.key} overlay where it was."
    finally:
        frame.Destroy()


def test_reset_is_reachable_without_the_keyboard(profile) -> None:
    """The host exposes the reset the menu row and the palette call."""
    frame, host = build_host()
    try:
        shipped = host.overlay_rect("minimap")
        drag_by(host.grips["minimap"], -120, 90)
        assert host.overlay_rect("minimap") != shipped
        host.reset_overlay_layout()
        assert host.overlay_rect("minimap") == shipped
    finally:
        frame.Destroy()


# ---------------------------------------------------------------------------
# it survives a restart
# ---------------------------------------------------------------------------


def test_a_moved_overlay_is_where_it_was_left_after_a_restart(profile) -> None:
    """Move it, throw the window away, build another: it is still there."""
    frame, host = build_host()
    try:
        drag_by(host.grips["minimap"], -150, 120)
        moved = host.overlay_rect("minimap")
        assert moved != host.overlay_rect("readouts")
    finally:
        frame.Destroy()
    wx.Yield()

    frame, host = build_host()
    try:
        assert host.overlay_rect("minimap") == moved, (
            "The overlay went back to its shipped corner, so nothing was "
            "remembered across the restart."
        )
    finally:
        frame.Destroy()


def test_a_reset_is_remembered_too(profile) -> None:
    """A reset that only lasts until the next launch is not a reset."""
    frame, host = build_host()
    try:
        shipped = host.overlay_rect("tools")
        drag_by(host.grips["tools"], -200, -150)
        assert host.overlay_rect("tools") != shipped
    finally:
        frame.Destroy()

    frame, host = build_host()
    try:
        assert host.overlay_rect("tools") != shipped
        host.reset_overlay_layout()
    finally:
        frame.Destroy()

    frame, host = build_host()
    try:
        assert host.overlay_rect("tools") == shipped
    finally:
        frame.Destroy()


def test_an_unwritable_profile_does_not_take_the_viewport_down(profile) -> None:
    """A profile that cannot be written loses the position, not the window."""
    frame, host = build_host()
    try:
        original = viewport.config.put

        def refuse(*_args, **_kwargs):
            raise OSError("the profile is read only")

        viewport.config.put = refuse
        try:
            drag_by(host.grips["axes"], 25, 25)
        finally:
            viewport.config.put = original
        assert host.overlay_rect("axes").x > 0
    finally:
        frame.Destroy()


# ---------------------------------------------------------------------------
# a drag is not a click, and it is not a camera gesture
# ---------------------------------------------------------------------------


def test_dragging_an_overlay_does_not_turn_the_camera(profile) -> None:
    """The precondition proves the camera callback is live before trusting it."""
    turned: List[Tuple[Tuple[float, float, float], float]] = []
    frame, host = build_host(on_camera=lambda camera, yaw: turned.append((camera, yaw)))
    try:
        host.set_camera(yaw=90.0, notify=True)
        assert turned, (
            "The camera callback never fired even when the camera was turned, "
            "so the assertion below could not fail however broken the drag was."
        )
        turned.clear()

        for group in viewport.OVERLAY_GROUPS:
            drag_by(host.grips[group.key], *inward(group, 20, 20))
        assert not turned, (
            "Dragging an overlay reported a camera move, so the gesture reached "
            "the view underneath it."
        )
    finally:
        frame.Destroy()


def test_a_minimap_click_still_opens_go_to(profile) -> None:
    """The overlay's own action survives the group becoming draggable."""
    opened: List[str] = []
    frame, host = build_host(on_surface=opened.append)
    try:
        host.minimap.activate()
        assert opened == ["goto"], (
            "The minimap did not open Go to even before a drag, so this test "
            "could not detect a drag having broken it."
        )
        opened.clear()

        drag_by(host.grips["minimap"], 30, 30)
        assert opened == [], "Dragging the minimap group opened Go to."

        host.minimap.activate()
        assert opened == ["goto"], (
            "After the group was dragged, clicking the minimap no longer opens "
            "Go to."
        )
    finally:
        frame.Destroy()


def test_a_tool_button_still_runs_after_its_column_is_moved(profile) -> None:
    """Same question for the tool column, whose members are all actions."""
    ran: List[str] = []
    frame, host = build_host(on_tool=ran.append)
    try:
        host.tools["frame"].activate()
        assert ran == ["frame"]
        ran.clear()
        drag_by(host.grips["tools"], -60, -60)
        assert ran == []
        host.tools["frame"].activate()
        assert ran == ["frame"]
    finally:
        frame.Destroy()


# ---------------------------------------------------------------------------
# the grip is a real control, drawn by the same code a capture reads
# ---------------------------------------------------------------------------


def test_the_grip_draws_itself_rather_than_inheriting_the_blank_default(
    profile,
) -> None:
    """A painting widget with no ``render_to`` photographs as an empty box.

    That is not a hypothetical in this repository: the composite capture calls
    ``render_to`` first, and a widget that never overrode it reports the
    backdrop-only default as a successful draw.  The report then says ``route:
    render, skipped: []`` over a blank rectangle.
    """
    from amulet_map_editor.api.studio.widgets import _Themed

    assert viewport.OverlayGrip.render_to is not _Themed.render_to, (
        "OverlayGrip inherited the backdrop-only render_to, so every capture "
        "of the viewport will show its grips as empty rectangles and report "
        "that they drew."
    )

    frame, host = build_host()
    try:
        grip = host.grips["readouts"]
        size = grip.GetSize()
        bitmap = wx.Bitmap(size.width, size.height, 24)
        dc = wx.MemoryDC(bitmap)
        dc.SetBackground(wx.Brush(wx.Colour(255, 0, 255)))
        dc.Clear()
        grip.render_to(wx.GCDC(dc), wx.Rect(0, 0, size.width, size.height))
        dc.SelectObject(wx.NullBitmap)
        image = bitmap.ConvertToImage()
        colours = {
            (
                image.GetRed(x, y),
                image.GetGreen(x, y),
                image.GetBlue(x, y),
            )
            for x in range(size.width)
            for y in range(size.height)
        }
        assert (255, 0, 255) not in colours, (
            "render_to left part of the grip unpainted, so a capture shows the "
            "bitmap's fill through it."
        )

        # Distinct colours over the whole rectangle is far too weak an
        # assertion to make here: a rounded border and its antialiasing supply
        # several on their own, so an empty bar with no grip texture whatsoever
        # passes it. This looks down the middle instead, well inside the
        # border, where the only thing that can vary is the texture itself.
        margin = 6
        assert size.height > margin * 2
        centre = {
            (
                image.GetRed(size.width // 2, y),
                image.GetGreen(size.width // 2, y),
                image.GetBlue(size.width // 2, y),
            )
            for y in range(margin, size.height - margin)
        }
        assert len(centre) > 1, (
            "The grip is a flat bar down its whole length, so nothing about it "
            "reads as something to take hold of."
        )
    finally:
        frame.Destroy()


def test_hovering_a_grip_changes_how_it_looks(profile) -> None:
    """Grabbing has to be obvious: the resting and hovered states differ."""
    frame, host = build_host()
    try:
        grip = host.grips["readouts"]

        def pixels() -> set:
            size = grip.GetSize()
            bitmap = wx.Bitmap(size.width, size.height, 24)
            dc = wx.MemoryDC(bitmap)
            dc.SetBackground(wx.Brush(wx.Colour(20, 20, 20)))
            dc.Clear()
            grip.render_to(wx.GCDC(dc), wx.Rect(0, 0, size.width, size.height))
            dc.SelectObject(wx.NullBitmap)
            image = bitmap.ConvertToImage()
            return {
                (x, y, image.GetRed(x, y), image.GetGreen(x, y), image.GetBlue(x, y))
                for x in range(size.width)
                for y in range(size.height)
            }

        resting = pixels()
        enter = wx.MouseEvent(wx.wxEVT_ENTER_WINDOW)
        enter.SetEventObject(grip)
        grip.GetEventHandler().ProcessEvent(enter)
        hovered = pixels()
        assert resting != hovered, (
            "The grip looks identical hovered and at rest, so nothing tells the "
            "user it can be grabbed."
        )
    finally:
        frame.Destroy()


def test_the_grip_asks_for_a_move_cursor(profile) -> None:
    """Where the platform allows it, the pointer says what will happen."""
    frame, host = build_host()
    try:
        cursor = host.grips["tools"].GetCursor()
        assert cursor.IsOk()
        assert cursor != wx.Cursor(wx.CURSOR_DEFAULT)
    finally:
        frame.Destroy()


def test_the_corner_handles_are_not_movable_chrome(profile) -> None:
    """The selection handles stay where the selection is, on purpose.

    They are not chrome floating over the world: each one marks a block
    coordinate, so moving one somewhere prettier would be a lie about where the
    selection corner is.  This states that decision rather than leaving the
    absence looking like an oversight.
    """
    keys = {group.key for group in viewport.OVERLAY_GROUPS}
    assert "handles" not in keys and "corners" not in keys

    frame, host = build_host()
    try:
        for handle in (host.minimum_handle, host.maximum_handle):
            assert handle not in host.overlay_members("readouts")
            assert handle not in host.overlay_members("tools")
    finally:
        frame.Destroy()
