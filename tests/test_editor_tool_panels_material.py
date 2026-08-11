"""The editing tools' own panels are Material, and still edit the world.

The Paste and Edit chunk tools each build a panel that floats over the 3D
canvas.  Since the canvas moved into the Studio's viewport those panels are
rendered directly beside Material widgets, and they were the last surfaces in
the running editor still made of native ``wx.SpinCtrl``, ``wx.Button``,
``wx.CheckBox``, ``wx.Choice``, ``wx.BitmapButton`` and ``wx.StaticText``.

**Nothing here reads source.**  Every test below builds the real panel through
the real tool constructor and drives the real widgets, because the one thing a
source-text test cannot tell you about a restyle is whether the control still
does what it did.  These panels perform real world edits: a regression here
corrupts somebody's map rather than merely looking wrong.

What is asserted, in order:

* the panels contain none of the native classes they used to (a hand-written
  inventory, because a rule about the classes that *are* there passes happily
  on a panel that has no controls at all),
* every control on them is keyboard reachable and carries an accessible name,
* the numeric fields hold, clamp, refuse, snap and step exactly as the spin
  controls they replace did -- including the difference between the rotation
  boxes, which move in whole increments, and the scale boxes, which must still
  take a typed ``1.5``,
* the values the paste operation actually reads are the values the boxes show,
* and the Studio's own bridge still reads and writes those same boxes, since
  the properties pane drives this tool through them.
"""

from __future__ import annotations

import os
import tempfile
from typing import Any, Iterator, List

import pytest

wx = pytest.importorskip("wx", reason="wxPython is not installed in this environment")

os.environ.setdefault("CONFIG_DIR", tempfile.mkdtemp(prefix="amulet-tool-panels-"))

paste_module = pytest.importorskip(
    "amulet_map_editor.programs.edit.plugins.tools.paste",
    reason="the editor's paste tool needs OpenGL and amulet-core",
)
chunk_module = pytest.importorskip(
    "amulet_map_editor.programs.edit.plugins.tools.chunk",
    reason="the editor's chunk tool needs OpenGL and amulet-core",
)

from amulet_map_editor.programs.edit.api.ui import (  # noqa: E402
    material_tool_panel as mtp,
)
from amulet_map_editor.programs.edit.api.ui.tool import (  # noqa: E402
    default_base_tool_ui,
)

#: The native classes these two panels were built from.  Hand-written on
#: purpose: a check that every control present is a Studio widget is satisfied
#: by a panel with no controls on it at all, so the list of what must be *gone*
#: is the half that actually catches a half-finished migration.
NATIVE_CLASSES = (
    wx.SpinCtrl,
    wx.SpinCtrlDouble,
    wx.CheckBox,
    wx.Choice,
    wx.ComboBox,
    wx.BitmapButton,
    wx.StaticLine,
    wx.StaticText,
    wx.RadioButton,
    wx.Slider,
)

#: ``wx.Button`` needs its own entry: ``wx.SpinCtrl`` and friends are leaves,
#: but a ``wx.Button`` is what ``NudgeButton`` used to be, and the Material one
#: is a ``wx.Control``.  Kept separate so the failure message can say which.
NATIVE_BUTTON = wx.Button


class _Stub:
    """A behaviour the panel constructs but this test does not exercise."""

    def __init__(self, canvas: Any, *args: Any, **kwargs: Any) -> None:
        self._canvas = canvas

    def __getattr__(self, name: str):
        return lambda *args, **kwargs: None


class _FakeLevels:
    active_level_index = None

    def __init__(self) -> None:
        self.active_transform = None
        self.render_levels: List[Any] = []

    def clear(self) -> None:
        return None

    def append(self, *args: Any, **kwargs: Any) -> None:
        return None


class _FakeRenderer:
    def __init__(self) -> None:
        self.fake_levels = _FakeLevels()


class _FakeCanvas(wx.Panel):
    """Just enough canvas for a tool panel to be built and driven against.

    Deliberately not a real ``EditCanvas``: that one needs an OpenGL context
    and a loaded world, and what is under test here is the panel rather than
    the renderer.  Everything the panel actually reads off the canvas -- the
    camera, the key binds, the fake-level transform it pushes into -- is real
    enough to be read back and asserted on.
    """

    def __init__(self, parent: wx.Window) -> None:
        super().__init__(parent, size=(900, 700))
        from amulet_map_editor.api.opengl.camera import Camera
        from amulet_map_editor.programs.edit.api.key_config import DefaultKeys

        self.camera = Camera(self)
        self.key_binds = DefaultKeys
        self.tools: dict = {}
        self.renderer = _FakeRenderer()


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
def tools(app) -> Iterator[dict]:
    """Both tools, built against a stand-in canvas, in a real frame."""
    default_base_tool_ui.CameraBehaviour = _Stub
    chunk_module.ChunkSelectionBehaviour = _Stub
    paste_module.StaticSelectionBehaviour = _Stub
    paste_module.PointerBehaviour = _Stub

    frame = wx.Frame(None, size=(600, 900), pos=(-32000, -32000))
    host = wx.Panel(frame)
    canvas = _FakeCanvas(host)
    canvas.Hide()
    built = {
        "chunk": chunk_module.ChunkTool(canvas),
        "paste": paste_module.PasteTool(canvas),
    }
    canvas.tools = {"Chunk": built["chunk"], "Paste": built["paste"]}
    for tool in built.values():
        for window in tool.windows():
            window.Show()
            window.SetSize(window.GetBestSize())
            window.Layout()
    frame.Show()
    wx.Yield()
    try:
        yield {"canvas": canvas, **built}
    finally:
        frame.Destroy()
        wx.Yield()


def descendants(window: wx.Window) -> List[wx.Window]:
    """Every window under ``window``, itself excluded."""
    found: List[wx.Window] = []
    stack = list(window.GetChildren())
    while stack:
        node = stack.pop()
        found.append(node)
        stack.extend(node.GetChildren())
    return found


# ---------------------------------------------------------------------------
# what the panels are made of
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ("chunk", "paste"))
def test_the_panel_has_no_native_controls_left_on_it(tools, name) -> None:
    """None of the classes these panels were built from survives on them.

    The one native window that is allowed is the ``wx.TextCtrl`` inside each
    numeric field.  That is deliberate and is the same choice the shell's own
    coordinate boxes make: the outline is drawn so it matches the interface at
    every theme, and the entry stays a real text control so selection,
    clipboard, caret and screen-reader behaviour are the platform's rather than
    a re-implementation.
    """
    tool = tools[name]
    panel = list(tool.windows())[0]
    offenders = [
        f"{type(child).__name__} named {child.GetName()!r}"
        for child in descendants(panel)
        if isinstance(child, NATIVE_CLASSES)
        or (isinstance(child, NATIVE_BUTTON) and not isinstance(child, wx.Control))
        or type(child) is NATIVE_BUTTON
    ]
    assert not offenders, (
        f"the {name} tool panel still carries native controls, so it will not "
        f"match the Material widgets it now sits beside: {offenders}"
    )


@pytest.mark.parametrize("name", ("chunk", "paste"))
def test_every_control_on_the_panel_is_named_and_reachable(tools, name) -> None:
    """A control nobody can tab to or name is not a finished control.

    Screen readers announce the accessible name, and the default ``wx``
    name -- ``panel``, ``control``, ``staticText`` -- is what a widget that was
    never given one answers with.  A panel full of "control" is a panel a
    screen-reader user cannot navigate.
    """
    tool = tools[name]
    panel = list(tool.windows())[0]
    default_names = {"panel", "control", "staticText", "item", "", "scrolledpanel"}
    unnamed = []
    unreachable = []
    for child in descendants(panel):
        if not isinstance(child, (mtp.NumberField, mtp.StepButton, mtp.IconButton)):
            continue
        if child.GetName() in default_names:
            unnamed.append(f"{type(child).__name__} at {child.GetPosition()}")
        if isinstance(child, (mtp.StepButton, mtp.IconButton)):
            if not child.AcceptsFocusFromKeyboard():
                unreachable.append(f"{type(child).__name__} {child.GetName()!r}")

    assert (
        not unnamed
    ), f"controls on the {name} panel have no accessible name: {unnamed}"
    assert not unreachable, (
        f"controls on the {name} panel cannot be reached with the keyboard, so "
        f"every action they offer is pointer-only: {unreachable}"
    )


def test_the_step_buttons_say_which_way_and_by_how_much(tools) -> None:
    """Each arrow names its direction and its increment, not just "plus"."""
    rotation = tools["paste"]._rotation
    assert rotation.x.up.hint.endswith("by 90"), rotation.x.up.hint
    assert rotation.x.down.hint.startswith("Decrease"), rotation.x.down.hint
    # And it follows the increment when free rotation changes it.
    rotation.increment = 1
    assert rotation.x.up.hint.endswith("by 1"), rotation.x.up.hint


# ---------------------------------------------------------------------------
# the numbers themselves
# ---------------------------------------------------------------------------


def test_setting_a_value_is_silent_and_stepping_is_not(tools) -> None:
    """``SetValue`` does not report, which is what ``wx.SpinCtrl`` promised.

    Every caller in the editor writes these boxes from state it has just
    computed -- a pointer move, a decomposed rotation matrix -- so a notifying
    setter would re-enter the handler that computed it.
    """
    seen: List[Any] = []
    field = tools["paste"]._location
    field.on_change = lambda value: seen.append(value)

    field.value = (8, 40, 8)
    assert field.value == (8, 40, 8)
    assert seen == [], "writing a value reported it, which will re-enter the caller"

    field.x.step(1)
    assert field.value == (9, 40, 8)
    assert seen == [(9, 40, 8)], "stepping the box did not report the new value"


def test_a_value_outside_the_bounds_is_clamped_and_the_panel_says_so(tools) -> None:
    """A native spin control rewrote a refused value in silence.

    Enter 400 in a box bounded at 320 and it became 320 with nothing to say it
    moved, which on a coordinate field means blocks land somewhere the reader
    did not ask for.
    """
    field = tools["chunk"]._min_y
    field.box.text.SetValue("99999999999")
    field._commit_typed()

    assert field.value == 30_000_000
    message = field.refused()
    assert "30" in message and "outside" in message, message
    assert field.feedback.IsShown(), "the refusal was recorded but never shown"


def test_something_that_is_not_a_number_keeps_the_last_one(tools) -> None:
    """Typing nonsense must not silently become zero on a coordinate."""
    field = tools["chunk"]._max_y
    field.set_value(64)
    field.box.text.SetValue("banana")
    field._commit_typed()

    assert field.value == 64
    assert "not a number" in field.refused(), field.refused()
    assert field.box.value() == "64", "the box did not go back to the held value"


def test_the_rotation_boxes_snap_and_the_scale_boxes_do_not(tools) -> None:
    """The one difference conflating these two would have quietly broken.

    The rotation boxes move in whole increments -- that is what the free
    rotation switch changes -- so 37 degrees under a 90 degree increment is 0.
    The scale boxes step by 1 and must still accept a typed 1.5, exactly as the
    ``wx.SpinCtrlDouble`` they replace did.
    """
    tool = tools["paste"]

    tool._rotation.increment = 90
    tool._rotation.x.box.text.SetValue("37")
    tool._rotation.x._commit_typed()
    assert tool._rotation.value[0] == 0
    assert "steps of 90" in tool._rotation.x.refused(), tool._rotation.x.refused()

    tool._scale.x.box.text.SetValue("1.5")
    tool._scale.x._commit_typed()
    assert tool._scale.value[0] == 1.5, (
        "the scale box snapped a typed 1.5 to its arrow increment, which would "
        "make every fractional scale impossible to enter"
    )
    assert tool._scale.x.refused() == "", tool._scale.x.refused()


def test_free_rotation_moves_the_increment_on_all_three_boxes(tools) -> None:
    """The switch is the only thing that decides how far an arrow moves."""
    tool = tools["paste"]
    tool._free_rotation.SetValue(False)
    tool._on_free_rotation_change(None)
    assert [field.increment for field in tool._rotation.fields] == [90, 90, 90]

    tool._free_rotation.SetValue(True)
    tool._on_free_rotation_change(None)
    assert [field.increment for field in tool._rotation.fields] == [1, 1, 1]


def test_the_arrow_keys_and_the_wheel_move_the_value(tools) -> None:
    """Both routes a spin control offered still work, on the real widget."""
    field = tools["chunk"]._min_y
    field.set_value(10)

    down = wx.KeyEvent(wx.wxEVT_KEY_DOWN)
    down.SetKeyCode(wx.WXK_UP)
    field.box.text.GetEventHandler().ProcessEvent(down)
    assert field.value == 11, "the up arrow did not step the value"

    wheel = wx.MouseEvent(wx.wxEVT_MOUSEWHEEL)
    wheel.SetWheelRotation(-120)
    field.box.text.GetEventHandler().ProcessEvent(wheel)
    assert field.value == 10, "a wheel notch did not step the value"


def test_escape_abandons_a_half_typed_number(tools) -> None:
    """The only way out of a part-typed value that does not commit it."""
    field = tools["chunk"]._min_y
    field.set_value(72)
    field.box.text.SetValue("-999")

    escape = wx.KeyEvent(wx.wxEVT_KEY_DOWN)
    escape.SetKeyCode(wx.WXK_ESCAPE)
    field.box.text.GetEventHandler().ProcessEvent(escape)

    assert field.value == 72
    assert field.box.value() == "72"


# ---------------------------------------------------------------------------
# what the tools do with those numbers
# ---------------------------------------------------------------------------


def test_the_chunk_boxes_still_drive_the_camera_clipping(tools) -> None:
    """The two Y boxes are the whole reason that panel has numbers on it."""
    tool = tools["chunk"]
    canvas = tools["canvas"]
    canvas.camera.location = (0, 0, 0)

    tool._min_y.set_value(-64, notify=True)
    tool._max_y.set_value(120, notify=True)

    low, high = canvas.camera.orthographic_clipping
    assert (low, high) == (-121, 65), (
        "the clipping planes do not follow the boxes, so the top-down view no "
        f"longer shows the slice they name: {(low, high)}"
    )


def test_the_paste_transform_reaches_the_renderer(tools) -> None:
    """Moving the location writes the transform the renderer draws with."""
    tool = tools["paste"]
    canvas = tools["canvas"]

    tool.location = (12, 41, -3)
    location, scale, rotation = canvas.renderer.fake_levels.active_transform
    assert tuple(location) == (12, 41, -3)
    assert tuple(scale) == tuple(tool._scale.value)
    assert tuple(rotation) == tuple(tool._rotation_radians())


def test_the_paste_rule_still_maps_to_a_position(tools) -> None:
    """The rule the paste runs under is picked by position, so one is answered."""
    tool = tools["paste"]
    assert tool._paste_rule.GetSelection() == 0
    tool._paste_rule.set_value(tool._paste_rule_options[2])
    assert tool._paste_rule.GetSelection() == 2


def test_the_air_water_and_lava_boxes_answer_getvalue(tools) -> None:
    """``_paste_operation`` reads these directly, so the spelling matters."""
    tool = tools["paste"]
    assert [
        tool._copy_air.GetValue(),
        tool._copy_water.GetValue(),
        tool._copy_lava.GetValue(),
    ] == [True, True, True]
    tool._copy_air.SetValue(False)
    assert tool._copy_air.GetValue() is False


def test_a_zero_scale_still_refuses_the_paste(tools) -> None:
    """A zero on any axis means nothing would be copied, and it says so."""
    from amulet_map_editor.programs.edit.api.operations import OperationSuccessful

    tool = tools["paste"]
    tool._scale.value = (0, 1, 1)
    with pytest.raises(OperationSuccessful):
        list(tool._paste_operation())


def test_the_studio_bridge_still_reads_and_writes_these_boxes(tools) -> None:
    """The properties pane drives this tool through the boxes, not around them.

    ``editor_tools`` reaches ``_location``, ``_rotation`` and ``_scale`` by
    name and uses their ``value`` property, because those are what the confirm
    reads -- writing anywhere else would move the drawing and paste the old
    numbers.
    """
    from amulet_map_editor.api.studio import editor_tools

    tool = tools["paste"]
    canvas = tools["canvas"]
    tool._is_enabled = True
    tool.location = (8, 40, 8)

    assert editor_tools.set_pending_rotation((0, 90, 0), canvas) is True
    assert tuple(tool._rotation.value) == (0, 90, 0)
    assert editor_tools.set_pending_scale((2, 2, 2), canvas) is True
    assert tuple(tool._scale.value) == (2, 2, 2)

    pending = editor_tools.pending_object(canvas)
    assert pending is not None
    assert pending.location == (8, 40, 8)
    assert pending.rotation == (0, 90, 0)
    assert pending.scale == (2, 2, 2)


# ---------------------------------------------------------------------------
# layout
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ("chunk", "paste"))
def test_nothing_on_the_panel_is_drawn_shorter_than_its_own_text(tools, name) -> None:
    """A control cut to "Delete Unselec…" has lost information.

    Every Studio widget routes a shortened draw through ``note_elision``, so
    the question can be asked of the widgets rather than of a picture.  These
    panels size themselves to their contents, so the healthy answer is that
    they grow rather than clip.

    **The positive control is not optional here.**  A panel of self-measuring
    widgets very nearly cannot clip at its own best size, so an assertion that
    nothing was cut is close to a tautology -- and, worse, it stays green if the
    watcher below is never called at all, which is how this guard would rot
    without anyone noticing.  So one of the panel's own buttons is drawn into a
    deliberately impossible rectangle afterwards: it *must* be reported, or the
    instrument is not connected to anything.

    Squeezing the panel itself would not do it, and that is worth knowing: this
    is a scroller, so a narrow host scrolls its content rather than laying it
    out narrower.  See ``test_a_panel_too_tall_for_the_canvas_scrolls``.
    """
    from amulet_map_editor.api.studio import widgets

    cut: List[str] = []
    original = widgets.note_elision

    def watch(window, full, drawn, *, hint=""):
        if str(full) and str(drawn) != str(full):
            cut.append(f"{window.GetName()!r}: {full!r} drawn as {drawn!r}")
        return original(window, full, drawn, hint=hint)

    panel = list(tools[name].windows())[0]
    best = panel.GetBestSize()
    buttons = [
        child
        for child in descendants(panel)
        if isinstance(child, widgets.StudioButton) and child.GetLabel()
    ]
    assert buttons, f"the {name} panel has no labelled button to measure against"

    widgets.note_elision = watch
    try:
        panel.SetSize(best)
        panel.Layout()
        wx.Yield()
        _paint(panel)
        at_best = list(cut)

        cut.clear()
        # The instrument check: no widget can draw this label in 30 pixels.
        buttons[0].render_to(wx.MemoryDC(wx.Bitmap(40, 40, 24)), wx.Rect(0, 0, 30, 30))
        proof = list(cut)
    finally:
        widgets.note_elision = original

    assert proof, (
        "drawing a labelled button into thirty pixels reported no elision, so "
        "this test is not watching the widgets draw and the assertion below "
        "would pass on a panel that clipped everything"
    )
    assert (
        not at_best
    ), f"the {name} panel clipped its own text at its best size: {at_best}"


def test_a_panel_too_tall_for_the_canvas_scrolls(tools) -> None:
    """The floating panel is a scroller, and a short canvas must prove it.

    ``_resize`` caps the panel at the canvas height less a margin.  Without a
    working scroller that cap does not shorten the panel, it *hides* whatever
    did not fit -- and what is at the bottom of the paste panel is Confirm.
    """
    tool = tools["paste"]
    canvas = tools["canvas"]
    panel = tool._paste_panel

    canvas.SetSize(900, 300)
    tool._resize()
    wx.Yield()

    assert panel.GetSize().GetHeight() < panel.GetVirtualSize().GetHeight(), (
        "the panel was not capped below its content, so nothing about this "
        "test is measuring a scroller"
    )
    assert panel.GetScrollRange(wx.VERTICAL) > 0, (
        "the panel is shorter than its content and offers no vertical scroll, "
        "so everything past the cap -- Confirm included -- is unreachable"
    )


def _paint(window: wx.Window) -> None:
    """Ask every Studio widget under ``window`` to draw, into a throwaway bitmap.

    ``render_to`` is the same drawing the screen gets, and calling it directly
    is what makes this runnable on a machine with nothing composited -- which
    is where this suite runs.
    """
    size = window.GetSize()
    bitmap = wx.Bitmap(max(1, size.GetWidth()), max(1, size.GetHeight()), 24)
    memory = wx.MemoryDC(bitmap)
    try:
        stack = [window]
        while stack:
            node = stack.pop()
            render = getattr(node, "render_to", None)
            if callable(render):
                node_size = node.GetSize()
                render(
                    memory,
                    wx.Rect(0, 0, node_size.GetWidth(), node_size.GetHeight()),
                )
            stack.extend(node.GetChildren())
    finally:
        memory.SelectObject(wx.NullBitmap)
