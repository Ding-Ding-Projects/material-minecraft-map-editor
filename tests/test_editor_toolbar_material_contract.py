"""The world toolbar over the 3D view is Material, and still does its job.

The row across the top of the rendered world belongs to the legacy edit
program: a native combo box for the dimension, native bitmap buttons for undo,
redo, save and close, native buttons for the projection, the camera position
and the camera speed.  It sat directly above the Studio's own heads-up chips,
which is the worst place in the application for two different design languages
to meet.

This builds the real ``FilePanel`` and asks the constructed objects the things
no grep over the source can answer.  The canvas under it is a stand-in for the
*world* only -- a level wrapper, a camera, and the four actions the toolbar
calls -- because opening a Minecraft world needs a resource pack, an OpenGL
context and two minutes, and none of that changes a pixel of this row.  Every
control is the real widget, and the picture comes out of the same ``render_to``
the screen goes through.

Two claims are checked that are easy to assert loosely and easy to get wrong:

* **Nothing native is left.**  Not "the file no longer says ``wx.Button``" --
  the constructed tree is walked and every class in it is named.
* **It belongs with the chips.**  Not "it looks Material" but the number: the
  bar's surface colour is compared against the colour a heads-up chip resolves
  to over the same backdrop, and they have to be the same colour.
"""

from __future__ import annotations

import pathlib
import sys
from typing import Any, Iterator, List

import pytest

wx = pytest.importorskip("wx", reason="wxPython is not installed in this environment")

_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_ROOT / "scripts"))

import capture_surface  # noqa: E402

from amulet_map_editor.api.opengl.camera import Projection  # noqa: E402
from amulet_map_editor.api.studio import tokens, viewport, widgets  # noqa: E402
from amulet_map_editor.programs.edit.api.events import EVT_EDIT_CLOSE  # noqa: E402
from amulet_map_editor.programs.edit.api.ui import file as file_ui  # noqa: E402

#: wx hands these out as default names, so finding one means nobody set a real
#: accessible name.  Same list the runtime render contract uses.
GENERIC_NAMES = frozenset(
    {"", "panel", "button", "control", "choice", "text", "window", "staticbox"}
)

#: Every native class this toolbar used to be built from.  A control of any of
#: these types anywhere under the two bars means the migration regressed.
NATIVE_CLASSES = (
    wx.Button,
    wx.BitmapButton,
    wx.Choice,
    wx.ComboBox,
    wx.StaticText,
    wx.TextCtrl,
    wx.CheckBox,
    wx.ToggleButton,
)

DIMENSIONS = ["minecraft:overworld", "minecraft:the_nether", "minecraft:the_end"]


class _Wrapper:
    platform = "java"
    version = 3465
    dimensions = DIMENSIONS


class _History:
    undo_count = 12
    redo_count = 3
    unsaved_changes = 7


class _Level:
    def __init__(self) -> None:
        self.level_wrapper = _Wrapper()
        self.history_manager = _History()


class _Camera:
    location = (66.40, 118.13, -43.12)
    move_speed = 33 / 1000 * 12.5
    projection_mode = Projection.PERSPECTIVE


class _Canvas(wx.Panel):
    """Enough canvas for the toolbar: a world, a camera, and four actions."""

    def __init__(self, parent: wx.Window) -> None:
        super().__init__(parent)
        self.world = _Level()
        self.camera = _Camera()
        self.dimension = "minecraft:the_nether"
        self.calls: List[str] = []

    def goto(self) -> None:
        self.calls.append("goto")

    def undo(self) -> None:
        self.calls.append("undo")

    def redo(self) -> None:
        self.calls.append("redo")

    def save(self) -> None:
        self.calls.append("save")


class _Built:
    """One constructed toolbar and the objects around it."""

    def __init__(self) -> None:
        self.frame: Any = None
        self.host: Any = None
        self.canvas: Any = None
        self.panel: Any = None


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


@pytest.fixture
def built(app) -> Iterator[_Built]:
    record = _Built()
    record.frame = wx.Frame(None, size=wx.Size(1100, 220))
    record.frame.SetPosition(wx.Point(-32000, -32000))
    record.host = wx.Panel(record.frame)
    record.host.SetBackgroundColour(viewport.sky_colour(0.1))
    record.canvas = _Canvas(record.host)
    record.canvas.SetSize(wx.Rect(0, 0, 1100, 220))
    record.canvas.Hide()
    record.panel = file_ui.FilePanel(record.canvas)
    record.frame.Show()
    wx.Yield()
    try:
        yield record
    finally:
        record.frame.Destroy()
        wx.Yield()


def _controls(record: _Built) -> List[wx.Window]:
    found: List[wx.Window] = []

    def walk(window: wx.Window) -> None:
        for child in window.GetChildren():
            found.append(child)
            walk(child)

    for window in record.panel.windows():
        walk(window)
    return found


# ----------------------------------------------------------------------
# nothing native is left
# ----------------------------------------------------------------------


def test_the_toolbar_is_built_from_studio_widgets(built) -> None:
    """Both bars are overlay surfaces, not platform panels."""
    windows = built.panel.windows()
    assert len(windows) == 2
    assert all(isinstance(window, widgets.OverlayBar) for window in windows), [
        type(window).__name__ for window in windows
    ]


def test_no_native_control_survives_anywhere_under_the_bars(built) -> None:
    """Walk the constructed tree rather than reading the source for a substring.

    A source test passes the moment the words are gone; this one passes only
    when the objects are.
    """
    offenders = [
        f"{type(control).__name__} ({control.GetName()!r})"
        for control in _controls(built)
        if isinstance(control, NATIVE_CLASSES)
    ]
    assert not offenders, f"native controls remain on the world toolbar: {offenders}"


def test_every_control_draws_through_render_to(built) -> None:
    """``render_to`` is what a capture on a hidden desktop can reach.

    A widget that paints only from ``EVT_PAINT`` photographs as an empty
    rectangle there, which is the shape of a defect that looks fine on a
    developer's screen and blank in every piece of evidence.
    """
    missing = [
        f"{type(control).__name__} ({control.GetName()!r})"
        for control in _controls(built)
        if not hasattr(control, "render_to")
    ]
    assert not missing, f"controls with no render_to: {missing}"


# ----------------------------------------------------------------------
# it still does what it did
# ----------------------------------------------------------------------


def test_each_button_still_runs_its_own_action(built) -> None:
    """Undo undoes, redo redoes, save saves, and the position opens goto."""
    built.panel._undo_button.activate()
    built.panel._redo_button.activate()
    built.panel._save_button.activate()
    built.panel._location_button.activate()
    assert built.canvas.calls == ["undo", "redo", "save", "goto"]


def test_the_close_button_posts_the_close_event(built) -> None:
    """Closing the world is an event, not a direct call, and still is."""
    seen: List[Any] = []
    built.canvas.Bind(EVT_EDIT_CLOSE, lambda event: seen.append(event))
    built.panel._close_button.activate()
    wx.Yield()
    assert seen, "pressing close posted no EditCloseEvent"


def test_the_projection_button_toggles_and_relabels(built) -> None:
    """3D to 2D and back, with the label and the accessible name following."""
    assert built.panel._projection_button.GetLabel() == "3D"
    built.panel._projection_button.activate()
    assert built.canvas.camera.projection_mode == Projection.TOP_DOWN
    built.panel._set_projection_label("2D")
    assert built.panel._projection_button.GetLabel() == "2D"
    assert built.panel._projection_button.GetName().endswith(": 2D")


def test_choosing_a_dimension_sets_it_on_the_canvas(built) -> None:
    """The combo drives the canvas, exactly as the native choice did."""
    assert built.panel._dim_options.options == sorted(DIMENSIONS)
    assert built.panel._dim_options.value == "minecraft:the_nether"
    built.panel._dim_options.set_value("minecraft:the_end", notify=True)
    assert built.canvas.dimension == "minecraft:the_end"


def test_the_combo_follows_the_canvas_without_calling_back(built) -> None:
    """A dimension changed in code shows in the row and starts no loop.

    The native control's guard was ``FindString`` plus a selection comparison.
    Losing it is not a crash -- it is the toolbar telling the canvas what the
    canvas just told the toolbar, forever.
    """
    calls: List[str] = []
    built.panel._dim_options.on_change = calls.append
    built.panel._set_dimension("minecraft:overworld")
    assert built.panel._dim_options.value == "minecraft:overworld"
    # Already showing it, and a dimension the world does not have.
    built.panel._set_dimension("minecraft:overworld")
    built.panel._set_dimension("minecraft:the_moon")
    assert built.panel._dim_options.value == "minecraft:overworld"
    assert calls == [], f"showing a dimension called back into the canvas: {calls}"


def test_the_counts_are_shown_and_named(built) -> None:
    """The label is the reading; the accessible name is the action and the reading.

    A button whose accessible name followed its label would introduce itself as
    "0", then as "1", and be a different control every time the count moved.
    """
    assert built.panel._undo_button.GetLabel() == "12"
    assert built.panel._redo_button.GetLabel() == "3"
    assert built.panel._save_button.GetLabel() == "7"
    assert built.panel._undo_button.GetName().endswith(": 12")
    built.canvas.world.history_manager.undo_count = 13
    built.panel._update_buttons()
    assert built.panel._undo_button.GetLabel() == "13"
    assert built.panel._undo_button.GetName().endswith(": 13")


def test_the_camera_readout_follows_the_camera(built) -> None:
    """The position button relabels on a camera move and renames with it."""

    class _Moved:
        camera_location = (1.0, 2.0, 3.0)

        def Skip(self) -> None:  # noqa: N802 - wx API spelling
            pass

    built.panel._on_camera_move(_Moved())
    assert built.panel._location_button.GetLabel() == "1.00, 2.00, 3.00"
    assert built.panel._location_button.GetName().endswith(": 1.00, 2.00, 3.00")


# ----------------------------------------------------------------------
# accessibility, keyboard, and the tooltips that were already there
# ----------------------------------------------------------------------


def test_every_control_keeps_a_real_accessible_name(built) -> None:
    unnamed = [
        type(control).__name__
        for control in _controls(built)
        if control.GetName().strip().lower() in GENERIC_NAMES
    ]
    assert not unnamed, f"controls with no accessible name of their own: {unnamed}"


def test_every_control_keeps_its_tooltip(built) -> None:
    """The native row's tooltips are the only place some of these facts appear.

    They are also the thing most easily lost in this particular migration:
    ``note_elision`` rewrites a Studio widget's tooltip on every paint, so one
    set from outside is erased the first time the control draws.
    """
    missing = [
        f"{type(control).__name__} ({control.GetName()!r})"
        for control in _controls(built)
        if not control.GetToolTip() or not control.GetToolTipText().strip()
    ]
    assert not missing, f"controls that lost their tooltip: {missing}"


def test_every_button_is_reachable_from_the_keyboard(built) -> None:
    """A control only a mouse can reach is a completion blocker, not a rough edge."""
    unreachable = [
        f"{type(control).__name__} ({control.GetName()!r})"
        for control in _controls(built)
        if isinstance(control, (widgets.OverlayButton, widgets.OverlayChoice))
        and not control.AcceptsFocusFromKeyboard()
    ]
    assert not unreachable, f"controls off the keyboard path: {unreachable}"


def _key_event(window: wx.Window, code: int) -> wx.KeyEvent:
    """Return a key-down event carrying ``code``, or fail saying it does not.

    ``m_keyCode`` is settable on this build and silently ignored: assigning it
    leaves ``GetKeyCode()`` at zero, the handler under test skips the event, and
    a test written that way reports "the key did nothing" whether or not the
    binding exists.  ``SetKeyCode`` is the one that lands, and the assertion
    below is the precondition that proves it did -- without it this test would
    pass on a control whose keyboard route had been deleted, because a dead
    handler and an empty event produce exactly the same silence.
    """
    event = wx.KeyEvent(wx.wxEVT_KEY_DOWN)
    event.SetEventObject(window)
    event.SetKeyCode(code)
    assert event.GetKeyCode() == code, (
        "the probe could not put a key code on the event, so nothing below "
        "says anything about the control's keyboard route"
    )
    return event


def test_enter_and_space_activate_a_button_without_a_mouse(built) -> None:
    button = built.panel._undo_button
    button._on_key_down(_key_event(button, wx.WXK_RETURN))
    button._on_key_down(_key_event(button, wx.WXK_SPACE))
    assert built.canvas.calls == ["undo", "undo"]


def test_the_down_arrow_opens_the_dimension_dropdown(built) -> None:
    """The keyboard route a ``wx.Choice`` gave for free, kept deliberately."""
    combo = built.panel._dim_options
    assert combo._popup is None
    combo._on_key_down(_key_event(combo, wx.WXK_DOWN))
    wx.Yield()
    try:
        assert combo._popup is not None, "the down arrow opened nothing"
    finally:
        combo.close_popup()


def test_every_control_clears_the_touch_target_floor(built) -> None:
    """The row's controls are at least as tall as the density says they must be."""
    floor = tokens.control_height()
    short = [
        (type(control).__name__, control.GetSize().height)
        for control in _controls(built)
        if isinstance(control, (widgets.OverlayButton, widgets.OverlayChoice))
        and control.GetSize().height < floor
    ]
    assert not short, f"controls below the {floor}px touch-target floor: {short}"


def test_the_dimension_dropdown_carries_a_search_and_its_regex_builder(built) -> None:
    """Every dropdown gets a search field with the builder beside it.

    The native ``wx.Choice`` this replaces had neither, which is the whole
    reason the Studio has one dropdown rather than two.
    """
    combo = built.panel._dim_options
    combo.open_popup()
    wx.Yield()
    try:
        assert combo._popup is not None, "the dimension dropdown opened nothing"
        found: List[wx.Window] = []

        def walk(window: wx.Window) -> None:
            for child in window.GetChildren():
                found.append(child)
                walk(child)

        walk(combo._popup)
        assert any(isinstance(control, widgets.SearchBar) for control in found), [
            type(control).__name__ for control in found
        ]
        assert [row.GetLabel() for row in combo._rows] == sorted(DIMENSIONS)
    finally:
        combo.close_popup()


# ----------------------------------------------------------------------
# it belongs with the chips
# ----------------------------------------------------------------------


def test_the_bars_resolve_to_the_same_surface_as_a_heads_up_chip(built) -> None:
    """The claim "it looks like it belongs" as a number rather than an opinion.

    A chip clears itself to the sky, lifts itself one elevation step, and
    paints the translucent scrim on top.  A bar has to arrive at the same
    colour by its own route or the two read as two tones of almost the same
    idea, which is worse than either alone.
    """
    chip = viewport.HudChip(built.host, "java 3465", name="World version")
    chip.SetPosition(wx.Point(8, 120))
    wx.Yield()
    try:
        backdrop = viewport.hud_backdrop(chip)
        lifted = tokens.elevation_tint(backdrop, 1, True)
        expected = widgets.overlay_fill(lifted, tokens.palette())
        for window in built.panel.windows():
            assert window.surface_colour() == expected, (
                f"{window.GetName()} paints "
                f"{window.surface_colour().GetAsString(wx.C2S_HTML_SYNTAX)} while a "
                f"chip resolves to {expected.GetAsString(wx.C2S_HTML_SYNTAX)}"
            )
    finally:
        chip.Destroy()


def test_the_toolbar_composites_with_nothing_missing(built, tmp_path) -> None:
    """Every control draws, by the render route, with nothing skipped.

    ``skipped`` naming a control is a hole in the picture at exactly the place
    the name says.  It is not proof the picture shows anything -- a person still
    has to look -- but a name in it is proof that it does not.
    """
    report = capture_surface.capture_composite(
        built.panel._button_window, tmp_path / "toolbar.png"
    )
    assert report["skipped"] == [], report["skipped"]
    assert report["blitted_leaves"] == [], report["blitted_leaves"]
    assert report["descendants"] == 8, report
    assert report["routes"]["render"] == 8, report["routes"]
    assert report["routes"]["print"] == 0, report["routes"]
