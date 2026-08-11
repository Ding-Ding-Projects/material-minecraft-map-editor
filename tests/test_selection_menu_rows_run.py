"""Four viewport and navigator rows that promised something and did nothing.

``deselectBox``, ``deselectAllBoxes``, ``frameDimension`` and ``duplicateBox``
were named by two of the design's own context menus and registered in no command
table, so all four drew disabled.  Two of them were worse than merely absent:
the viewport reads its accelerators from the *3D editor's* live key group while
it reads whether a row can run from the *shell's* command registry, so "Deselect
all boxes" sat greyed out beside ``Ctrl+Shift+D`` -- a key the editor really does
listen for.  A menu is where a user learns a shortcut, and that pairing teaches
them a working feature is missing.

So these tests do not read source.  They build the shell against a live
:class:`~amulet_map_editor.programs.edit.api.selection.SelectionManager` and a
live :class:`~amulet_map_editor.api.opengl.camera.camera.Camera` -- the very
classes the running editor owns -- run each row's command through the same
``run_command`` a right-click reaches, and then ask the selection and the camera
what they now hold.  A row is verified by the state it changed, never by the
notification it posted.

The framing test is the one worth reading twice: it does not check that the
camera moved somewhere plausible, it multiplies all eight corners of the
dimension's extent by the camera's own ``transformation_matrix`` and asserts
each one lands inside the clip volume.  That is what "in view" means to the
matrix that draws the frame, so it cannot be satisfied by a camera that merely
went in roughly the right direction.
"""

from __future__ import annotations

import math
import os
import tempfile
from typing import Any, Dict, List, Sequence, Tuple

import pytest

wx = pytest.importorskip("wx", reason="wxPython is not installed in this environment")
numpy = pytest.importorskip("numpy", reason="numpy is not installed")

from amulet_map_editor.api.studio import commands, context_menu  # noqa: E402
from amulet_map_editor.api.studio.shell import (  # noqa: E402
    StudioShell,
    frame_camera,
    framing_distance,
    look_at,
    top_down_framing,
)

#: The off-screen corner every window here is built at, so a run on a visible
#: desktop never throws a frame across somebody's screen.
OFFSCREEN = (-32000, -32000)

#: The chunks the fake dimension has generated.  Deliberately **not** square and
#: deliberately **not** centred on the origin: a framing test run against an
#: 8x8 block at the origin passed with the top-down radius bounding the wrong
#: axis, because with equal sides the two are indistinguishable, and passed
#: again with the camera offset by the world origin, because zero minus zero is
#: zero either way.  This one is twice as deep as it is wide and sits away from
#: both origins, so an axis swapped or a centre missed shows up as geometry off
#: the edge of the screen.
SUB_CHUNK = 16
CHUNKS: Tuple[Tuple[int, int], ...] = tuple(
    (x, z) for x in range(2, 8) for z in range(-5, 7)
)
WORLD_MIN_Y = 0
WORLD_MAX_Y = 256

#: The extent those chunks describe, which is what a framing command must hold:
#: 96 blocks across, 192 deep, and 256 tall.
EXTENT_MIN = (2 * SUB_CHUNK, WORLD_MIN_Y, -5 * SUB_CHUNK)
EXTENT_MAX = (8 * SUB_CHUNK, WORLD_MAX_Y, 7 * SUB_CHUNK)
EXTENT_CENTRE = tuple((low + high) / 2.0 for low, high in zip(EXTENT_MIN, EXTENT_MAX))

#: Three boxes drawn in that dimension, in the order the editor holds them.
BOXES: Tuple[Tuple[Tuple[int, int, int], Tuple[int, int, int]], ...] = (
    ((0, 64, 0), (4, 68, 4)),
    ((20, 64, 20), (26, 70, 26)),
    ((40, 10, 40), (48, 20, 48)),
)


# ---------------------------------------------------------------------------
# the world the shell is given
# ---------------------------------------------------------------------------


class _Bounds:
    """What a level answers when asked how tall a dimension is."""

    def __init__(self, low: int, high: int) -> None:
        self.min = (-30_000_000, low, -30_000_000)
        self.max = (30_000_000, high, 30_000_000)


class _History:
    """A world's undo depth, which the shell reads before and after a command."""

    def __init__(self) -> None:
        self.undo_count = 0
        self.redo_count = 0


class _Level:
    """Only the parts of a level these four commands actually read."""

    def __init__(self) -> None:
        self.changed = False
        self.history_manager = _History()
        self.sub_chunk_size = SUB_CHUNK
        self.level_wrapper = None

    def all_chunk_coords(self, _dimension: str) -> Tuple[Tuple[int, int], ...]:
        return CHUNKS

    def bounds(self, _dimension: str) -> _Bounds:
        return _Bounds(WORLD_MIN_Y, WORLD_MAX_Y)


class _Canvas(wx.Panel):
    """A stand-in for the 3D editor canvas, holding the editor's real parts.

    The selection and the camera are the genuine classes from the editor, not
    doubles: this whole module exists because a lane verified against a stub
    passed while the seam it stubbed was broken, so the two objects whose state
    is being asserted are the ones the application uses.
    """

    def __init__(self, parent: wx.Window) -> None:
        super().__init__(parent)
        from amulet_map_editor.api.opengl.camera import Camera
        from amulet_map_editor.programs.edit.api.selection import SelectionManager

        self.world = _Level()
        self.dimension = "minecraft:overworld"
        self.tools: Dict[str, Any] = {}
        self.camera = Camera(self)
        self.selection = SelectionManager(self)


class _Frame(wx.Frame):
    """The frame accessors the shell asks for when it looks for the editor."""

    def __init__(self) -> None:
        super().__init__(None, pos=OFFSCREEN, size=(1200, 800))
        self.canvas = _Canvas(self)
        self.canvas.Hide()

    def active_editor_canvas(self) -> _Canvas:
        return self.canvas

    def active_world_page(self) -> None:
        return None

    def active_editor_program(self) -> None:
        return None


@pytest.fixture(scope="module")
def app():
    """A live ``wx.App`` on an isolated profile, so a run touches no settings."""
    os.environ.setdefault("CONFIG_DIR", tempfile.mkdtemp(prefix="amulet-rows-"))
    application = wx.App()
    yield application


@pytest.fixture
def shell(app):
    """A real :class:`StudioShell` with a real editor selection behind it."""
    frame = _Frame()
    built = StudioShell(frame, frame)
    try:
        yield built
    finally:
        frame.Destroy()
        wx.SafeYield()


def _select(shell: StudioShell, boxes: Sequence[Any]) -> None:
    """Draw ``boxes`` through the editor's own selection, as the user would."""
    shell._canvas().selection.selection_corners = tuple(boxes)


def _corners(shell: StudioShell) -> Tuple[Any, ...]:
    """Read the selection back from the editor rather than from the shell."""
    return tuple(shell._canvas().selection.selection_corners)


# ---------------------------------------------------------------------------
# every row names something this build can run
# ---------------------------------------------------------------------------

#: The four keys two of the design's menus name that had no command behind
#: them.  Written out rather than derived, because a derived list would shrink
#: silently the day somebody deleted a row instead of wiring it.
PREVIOUSLY_DEAD = ("deselectBox", "deselectAllBoxes", "frameDimension", "duplicateBox")


@pytest.mark.parametrize("key", PREVIOUSLY_DEAD)
def test_the_four_dead_rows_now_name_a_registered_command(key: str) -> None:
    entry = commands.command(key)
    assert entry is not None, (
        f"The menus draw a row for {key!r} and nothing is registered under it, so "
        "the row is disabled again."
    )
    assert entry.label


def test_deselecting_a_box_and_removing_one_are_one_implementation() -> None:
    """Two names for one action, so they cannot drift into two behaviours."""
    assert commands.resolve("deselectBox") == "removeBox"
    assert "deselectBox" not in commands.keys(), (
        "An alias must not also be a listed command, or the palette offers the "
        "same action twice under two names."
    )


def test_every_menu_row_names_a_destination_this_build_has(app) -> None:
    """No row in any context menu is left drawing a dead command key.

    Surfaces are exempt: several rows point at windows this build genuinely has
    not registered yet, which is the disabled-with-a-reason case the menus are
    designed around.  A *command* key with nothing behind it is different --
    commands are this repository's own registry, so an unregistered one is an
    oversight rather than an unbuilt window.
    """
    missing: List[str] = []
    for key, (_title, items) in context_menu.CTX_MENUS.items():
        for item in items:
            if item.command and commands.command(item.command) is None:
                missing.append(f"{key}: {item.label} -> {item.command}")
    assert not missing, "Menu rows naming an unregistered command: " + ", ".join(
        missing
    )


# ---------------------------------------------------------------------------
# a disabled row never prints a working shortcut
# ---------------------------------------------------------------------------


def test_a_row_that_cannot_run_withholds_its_shortcut(app) -> None:
    """The mechanism is proved live before it is trusted.

    The first half is the precondition: the same item, enabled, really does
    draw and announce the key.  Without it a row class that had simply lost its
    accelerator support would pass the second half for the wrong reason.
    """
    frame = wx.Frame(None, pos=OFFSCREEN)
    try:
        item = context_menu.MenuItem(
            label="Deselect all boxes", accel="Ctrl+Shift+D", command="deselectAllBoxes"
        )
        live = context_menu._MenuRow(frame, item)
        assert live.accel == "Ctrl+Shift+D"
        assert "Ctrl+Shift+D" in live.GetName()
        assert live.IsEnabled()

        dead = context_menu._MenuRow(
            frame, item, unavailable="Deselect all boxes is unavailable: nothing."
        )
        assert dead.accel == "", (
            "A row drawn disabled printed a keyboard shortcut. That key works, so "
            "the row teaches the user the feature is missing when it is not."
        )
        assert "Ctrl+Shift+D" not in dead.GetName()
        assert not dead.IsEnabled()
    finally:
        frame.Destroy()


def _offends(row: Any) -> bool:
    """Return whether ``row`` is the forbidden pairing: disabled, and keyed."""
    return not row.IsEnabled() and bool(row.accel)


def test_the_sweeps_own_predicate_catches_the_pairing_it_looks_for(app) -> None:
    """Prove the net has a hole in it before trusting the sweep to find none.

    This was written after watching the sweep below stay green while the
    suppression it exists to police was deliberately removed: with every keyed
    row now wired, the menus contain no disabled row carrying an accelerator, so
    the sweep passes by finding nothing rather than by finding nothing wrong.
    It is kept as a net for rows added later, and this is what stops it becoming
    a decoration in the meantime.
    """
    frame = wx.Frame(None, pos=OFFSCREEN)
    try:
        item = context_menu.MenuItem(label="Something", accel="Ctrl+Shift+D")
        keyed_but_dead = context_menu._MenuRow(frame, item, unavailable="nothing.")
        # The row class is *asked* to draw the key here, so a predicate that
        # cannot see the pairing fails on this line rather than passing the
        # sweep.
        keyed_but_dead.accel = item.accel
        assert _offends(keyed_but_dead)
        assert not _offends(context_menu._MenuRow(frame, item))
    finally:
        frame.Destroy()


def test_no_context_menu_draws_a_disabled_row_beside_a_shortcut(app) -> None:
    """The sweep, with a precondition so it cannot pass by finding nothing."""
    frame = wx.Frame(None, pos=OFFSCREEN)
    offenders: List[str] = []
    disabled = 0
    try:
        for key in context_menu.CTX_MENUS:
            popup = context_menu.SearchableContextMenu(frame, key)
            for row in popup._rows:
                if row.IsEnabled():
                    continue
                disabled += 1
                if _offends(row):
                    offenders.append(f"{key}: {row.item.label} -> {row.accel}")
            popup.Destroy()
    finally:
        frame.Destroy()
    assert disabled, (
        "No menu row was disabled at all, so this sweep proved nothing. Either "
        "every surface is registered now -- in which case delete this test -- or "
        "the disabled state stopped being reported."
    )
    assert not offenders, "Disabled rows printing a shortcut: " + ", ".join(offenders)


# ---------------------------------------------------------------------------
# the rows do what their labels promise
# ---------------------------------------------------------------------------


def test_deselect_active_box_drops_the_last_box(shell: StudioShell) -> None:
    _select(shell, BOXES)
    assert len(_corners(shell)) == 3

    shell.run_command("deselectBox")

    remaining = _corners(shell)
    assert len(remaining) == 2, "The row promised to deselect the active box."
    assert remaining == BOXES[:2]
    assert BOXES[2] not in remaining


def test_deselect_all_boxes_clears_the_whole_selection(shell: StudioShell) -> None:
    _select(shell, BOXES)
    assert len(_corners(shell)) == 3

    shell.run_command("deselectAllBoxes")

    assert _corners(shell) == (), "The row promised to deselect every box."
    assert len(shell._canvas().selection.selection_group) == 0


def test_deselect_all_boxes_on_an_empty_selection_changes_nothing(
    shell: StudioShell,
) -> None:
    """It refuses rather than reporting that it cleared an empty selection."""
    _select(shell, ())
    shell.run_command("deselectAllBoxes")
    assert _corners(shell) == ()


def test_duplicating_a_box_adds_a_copy_clear_of_the_original(
    shell: StudioShell,
) -> None:
    """A duplicate laid on its original would be a box nobody can see or pick."""
    _select(shell, (BOXES[2],))

    shell.run_command("duplicateBox")

    corners = _corners(shell)
    assert len(corners) == 2, "The row promised a second box."
    original, copy = corners
    assert original == BOXES[2], "The box that was duplicated must not have moved."
    width = original[1][0] - original[0][0]
    assert copy == (
        (original[0][0] + width, original[0][1], original[0][2]),
        (original[1][0] + width, original[1][1], original[1][2]),
    )
    # The point of the offset: the two boxes share no block.
    assert copy[0][0] >= original[1][0]
    assert len(shell._canvas().selection.selection_group) == 2


def test_duplicating_with_nothing_selected_adds_nothing(shell: StudioShell) -> None:
    _select(shell, ())
    shell.run_command("duplicateBox")
    assert _corners(shell) == ()


# ---------------------------------------------------------------------------
# framing, asked of the matrix that draws the frame
# ---------------------------------------------------------------------------


def _corners_of(
    minimum: Tuple[int, int, int], maximum: Tuple[int, int, int]
) -> Tuple[Tuple[float, float, float], ...]:
    return tuple(
        (float(x), float(y), float(z))
        for x in (minimum[0], maximum[0])
        for y in (minimum[1], maximum[1])
        for z in (minimum[2], maximum[2])
    )


def _clip(camera: Any, point: Tuple[float, float, float]) -> Tuple[float, float, float]:
    """Return a world point in normalised device coordinates."""
    vector = numpy.array([point[0], point[1], point[2], 1.0], dtype=float)
    x, y, z, w = numpy.matmul(camera.transformation_matrix, vector)
    return (x / w, y / w, z / w)


def test_framing_the_dimension_puts_every_corner_of_it_on_screen(
    shell: StudioShell,
) -> None:
    camera = shell._canvas().camera
    camera.location_rotation = ((0.0, 0.0, 0.0), (0.0, 0.0))
    before = camera.location

    shell.run_command("frameDimension")

    assert camera.location != before, "The camera did not move."
    for corner in _corners_of(EXTENT_MIN, EXTENT_MAX):
        x, y, z = _clip(camera, corner)
        assert abs(x) <= 1.0 + 1e-9, f"{corner} is off the side of the screen: x={x}"
        assert abs(y) <= 1.0 + 1e-9, f"{corner} is off the top or bottom: y={y}"
        assert -1.0 - 1e-9 <= z <= 1.0 + 1e-9, f"{corner} is outside the clip: z={z}"


def test_framing_looks_at_the_middle_of_the_dimension(shell: StudioShell) -> None:
    """The centre lands in the middle of the screen, not merely inside it.

    This is what catches a framing that aimed at the world origin instead of at
    the dimension's own centre, which every "did the camera move" assertion
    passes.  It does not catch a mirrored *yaw*: the camera is placed due north
    of the centre, so its sideways offset is zero and both signs point at the
    same place.  :func:`test_look_at_agrees_with_the_renderers_own_camera_matrix`
    is what covers that, and it was watched failing on a flipped sign.
    """
    camera = shell._canvas().camera
    shell.run_command("frameDimension")
    x, y, _z = _clip(camera, EXTENT_CENTRE)
    assert abs(x) < 1e-6
    assert abs(y) < 1e-6


def test_framing_a_dimension_with_no_chunks_leaves_the_camera_alone(
    shell: StudioShell,
) -> None:
    canvas = shell._canvas()
    canvas.world.all_chunk_coords = lambda _dimension: ()
    canvas.camera.location_rotation = ((7.0, 8.0, 9.0), (10.0, 11.0))

    shell.run_command("frameDimension")

    assert canvas.camera.location == (7.0, 8.0, 9.0)
    assert canvas.camera.rotation == (10.0, 11.0)


def test_framing_top_down_keeps_looking_down_and_widens_the_view(
    shell: StudioShell,
) -> None:
    """Top-down has no viewpoint to retreat to; the orthographic radius grows."""
    from amulet_map_editor.api.opengl.camera import Projection

    camera = shell._canvas().camera
    camera.projection_mode = Projection.TOP_DOWN
    camera.fov = 10.0

    shell.run_command("frameDimension")

    # ``Camera.set_rotation`` normalises yaw into ``[-180, 180)``, so the 180 the
    # editor's own behaviour hands it comes back as -180. Same bearing; asserting
    # the literal would be asserting the normaliser rather than the framing.
    assert camera.rotation[1] == 90.0, "Top-down must still look straight down."
    assert abs(camera.rotation[0]) == 180.0
    assert camera.location[0] == pytest.approx(EXTENT_CENTRE[0])
    assert camera.location[2] == pytest.approx(EXTENT_CENTRE[2])
    assert camera.location[1] > EXTENT_MAX[1]
    assert camera.fov > 10.0, "The orthographic radius did not widen."
    # The dimension is deeper than it is wide, so a radius bounding the wrong
    # axis leaves its north and south ends off the screen -- which is exactly
    # what this loop caught while the axes were deliberately swapped.
    for corner in _corners_of(EXTENT_MIN, EXTENT_MAX):
        x, y, _z = _clip(camera, corner)
        assert abs(x) <= 1.0 + 1e-9, f"{corner} is off the side: x={x}"
        assert abs(y) <= 1.0 + 1e-9, f"{corner} is off the top or bottom: y={y}"


# ---------------------------------------------------------------------------
# the framing arithmetic on its own
# ---------------------------------------------------------------------------


def test_look_at_agrees_with_the_renderers_own_camera_matrix() -> None:
    """The angles are checked against the matrix the renderer actually builds."""
    from amulet.utils.matrix import displacement_matrix, rotation_matrix_yx

    cases = (
        ((0.0, 0.0, 0.0), (0.0, 0.0, 10.0)),
        ((0.0, 0.0, 0.0), (10.0, 0.0, 0.0)),
        ((0.0, 100.0, 0.0), (0.0, 0.0, 0.0)),
        ((30.0, 80.0, -40.0), (5.0, 12.0, 90.0)),
        ((-120.0, 45.0, 17.0), (33.0, -8.0, -60.0)),
    )
    for location, target in cases:
        yaw, pitch = look_at(location, target)
        matrix = numpy.matmul(
            rotation_matrix_yx(math.radians(yaw + 180), math.radians(pitch)),
            displacement_matrix(*-numpy.array(location, dtype=float)),
        )
        x, y, z, _w = numpy.matmul(matrix, numpy.array([*target, 1.0], dtype=float))
        assert x == pytest.approx(0.0, abs=1e-9)
        assert y == pytest.approx(0.0, abs=1e-9)
        assert z == pytest.approx(-math.dist(location, target), abs=1e-9)


def test_look_at_a_point_the_camera_is_standing_on_invents_no_angle() -> None:
    assert look_at((3.0, 4.0, 5.0), (3.0, 4.0, 5.0)) == (0.0, 0.0)


def test_framing_distance_grows_with_the_subject_and_shrinks_with_the_view() -> None:
    close = framing_distance(10.0, fov=70.0, aspect=4 / 3)
    far = framing_distance(20.0, fov=70.0, aspect=4 / 3)
    assert far == pytest.approx(close * 2)
    assert framing_distance(10.0, fov=100.0, aspect=4 / 3) < close


def test_framing_distance_fits_the_sphere_inside_both_screen_angles() -> None:
    """The distance is checked against the property, not against a comparison.

    A "portrait retreats further than landscape" assertion was here first and it
    passed with the two angles deliberately swapped: taking the *wider* angle
    still leaves portrait behind landscape, so the comparison held while the
    arithmetic was inverted.  What actually has to be true is that the angle the
    subject subtends fits inside both the vertical and the horizontal half-angle
    and wastes no room beyond that, which is what is asserted here and what
    fails the moment either angle is dropped.
    """
    radius = 10.0
    fov = 70.0
    half_vertical = math.radians(fov) / 2.0
    for aspect in (2.0, 4 / 3, 1.0, 0.75, 0.5):
        distance = framing_distance(radius, fov=fov, aspect=aspect)
        subtended = math.asin(radius / distance)
        half_horizontal = math.atan(math.tan(half_vertical) * aspect)
        assert subtended <= half_vertical + 1e-12, (
            f"At aspect {aspect} the subject overflows the top and bottom of the "
            "screen."
        )
        assert (
            subtended <= half_horizontal + 1e-12
        ), f"At aspect {aspect} the subject overflows the sides of the screen."
        assert subtended == pytest.approx(min(half_vertical, half_horizontal)), (
            f"At aspect {aspect} the camera retreated further than it needed to, "
            "so the dimension is drawn smaller than the viewport allows."
        )


def test_framing_is_capped_at_the_far_clipping_plane() -> None:
    _location, _rotation, capped = frame_camera(
        (0, 0, 0), (100_000, 256, 100_000), fov=70.0, aspect=4 / 3, far=10_000.0
    )
    assert capped, (
        "A dimension larger than the render distance was framed without saying "
        "the far edge will not be drawn."
    )
    _location, _rotation, fits = frame_camera(
        (0, 0, 0), (128, 256, 128), fov=70.0, aspect=4 / 3, far=10_000.0
    )
    assert not fits


def test_top_down_radius_bounds_z_directly_and_x_by_the_aspect() -> None:
    """Looking down, world Z runs up the screen and world X runs across it.

    Checked against the renderer's matrices rather than assumed; getting the
    two the wrong way round frames a long, thin dimension by cutting its ends
    off, which no assertion about "the camera moved" would notice.
    """
    _location, deep = top_down_framing((0, 0, 0), (100, 10, 800), aspect=2.0)
    assert deep == pytest.approx(400.0)
    _location, wide = top_down_framing((0, 0, 0), (800, 10, 100), aspect=2.0)
    assert wide == pytest.approx(200.0)
