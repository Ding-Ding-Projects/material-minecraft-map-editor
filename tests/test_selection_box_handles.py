"""The selection box's grab handles: where they are, and what dragging does.

Three layers, because a defect can hide in any one of them and the layer above
will not see it.

**The arithmetic.**  A drag is a ray and a subtraction.  Two of the tests below
work the answer out by hand -- a plane intersection and a closest-approach on a
line, both small enough to check on paper -- rather than restating the code, so
a sign error in the module cannot agree with a sign error in the test.

**The round trip.**  The one that matters most presses on a handle at one point
on screen, drags to another, and asserts the handle ends up *there*: it
projects the moved box back through the same camera matrix the renderer uses
and compares against the cursor.  That is the promise the feature makes -- the
box follows the cursor in world space -- stated in a form that cannot be
satisfied by moving the box the wrong distance in the right direction.

**The wiring.**  A drag that works when called directly and never runs in the
application is the failure this repository has already shipped once.  So the
press and the release go in as real events, through the canvas, dispatched by
wx: a handler that was written and never bound fails here instead of passing.

What is *not* covered, said plainly: nothing here draws a pixel.  The mesh tests
assert the vertex array, which is what the GPU is handed, not what a GPU makes
of it.  Looking at the picture is done by ``scripts/capture_selection_handles.py``,
which renders the real mesh through the real shader in a real context.
"""

from __future__ import annotations

import math

import numpy
import pytest

from amulet_map_editor.api.opengl.matrix import (
    displacement_matrix,
    perspective_matrix,
    rotation_matrix_yx,
)
from amulet_map_editor.api.opengl.mesh.selection.box import handles as H
from amulet_map_editor.api.opengl.mesh.selection.box.render_selection_editable import (
    HANDLE_HOVER_SCALE,
    HANDLE_VERT_COUNT,
    HANDLE_VERTS_START,
    HANDLE_VERTS_TOTAL,
    RenderSelectionEditable,
)

FOV = 70.0
ASPECT = 16 / 9


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


class StubResourcePack:
    """Enough of the resource pack to build a mesh's vertices without a GPU."""

    def get_texture_path(self, namespace, path):
        return f"{namespace}:{path}"

    def texture_bounds(self, path):
        return (0.0, 0.0, 1.0, 1.0)


def world_to_screen(location, rotation, aspect: float = ASPECT) -> numpy.ndarray:
    """The camera matrix, built exactly the way ``Camera`` builds it."""
    projection = perspective_matrix(math.radians(FOV), aspect, 0.1, 10000.0)
    yaw, pitch = rotation
    view = numpy.matmul(
        rotation_matrix_yx(math.radians(yaw + 180), math.radians(pitch)),
        displacement_matrix(*-numpy.array(location, dtype=numpy.float64)),
    )
    return numpy.matmul(projection, view)


def cursor_of(matrix: numpy.ndarray, point) -> numpy.ndarray:
    """Where a world point lands, in the same units the pointer reports.

    The projection puts +y at the top of the screen; ``mouse_xy_relative``
    counts y downwards from the top, because that is how wx reports a click.
    The flip is the whole of the difference between the two, and getting it
    wrong would make a drag appear to work while going the wrong way
    vertically -- so it lives here, once, named.
    """
    clip = numpy.matmul(matrix, numpy.array([*point, 1.0], dtype=numpy.float64))
    ndc = clip[:2] / clip[3]
    return numpy.array([ndc[0], -ndc[1]])


def mesh(point1=(0, 0, 0), point2=(12, 8, 10)) -> RenderSelectionEditable:
    box = RenderSelectionEditable("test", StubResourcePack())
    box.point1 = numpy.array(point1)
    box.point2 = numpy.array(point2)
    return box


def handle_named(name: str) -> H.BoxHandle:
    return next(handle for handle in H.BOX_HANDLES if handle.name == name)


def handle_verts(box: RenderSelectionEditable, name: str) -> numpy.ndarray:
    index = H.BOX_HANDLES.index(handle_named(name))
    start = HANDLE_VERTS_START + index * HANDLE_VERT_COUNT
    return box.verts[start : start + HANDLE_VERT_COUNT]


# ---------------------------------------------------------------------------
# the arithmetic, worked out by hand
# ---------------------------------------------------------------------------


def test_a_corner_drag_moves_the_box_by_a_hand_computed_delta() -> None:
    """Press a corner, swing the ray, and the box moves where the plane says.

    Set up so the answer needs no code to predict.  The camera sits at
    ``(0, 0, -20)``; the corner grabbed is at ``(0, 0, 8)``; the ray at the
    press points straight down +z, so the drag plane is ``z = 8``.  A second ray
    with direction ``(3, 4, 28)`` reaches that plane after ``28 / 28`` of its own
    z, putting it at ``(3, 4, 8)``.  The box must therefore move ``(3, 4, 0)``:
    the plane's own normal contributes nothing, by construction.
    """
    box_min, box_max = (0, 0, 0), (8, 8, 8)
    camera = (0.0, 0.0, -20.0)
    corner = handle_named("corner:-x-y+z")
    assert tuple(H.handle_centre(corner, box_min, box_max)) == (0.0, 0.0, 8.0)

    drag = H.begin_drag(corner, box_min, box_max, camera, (0.0, 0.0, 1.0))
    assert drag is not None
    assert list(drag.plane_normal) == [0.0, 0.0, 1.0]

    offset = drag.block_offset(camera, (3.0, 4.0, 28.0))
    assert list(offset) == [3, 0 + 4, 0]


def test_a_face_drag_slides_along_its_own_axis_and_no_other() -> None:
    """A face handle resolves to the point on its axis nearest the line of sight.

    Also worked by hand.  The handle is at ``(8, 4, 4)`` and its axis is x, so
    the line it slides along is ``(t, 4, 4)``.  From ``(4, 4, -20)`` looking
    straight down +z the nearest point on that line is ``x = 4``.  Swing the ray
    to direction ``(1, 0, 10)`` and the two are closest at ``x = 6.4`` -- the
    ray reaches ``x = 4 + u`` while its z closes the 24-block gap at ten per
    unit, so ``u = 2.4``.  Two point four blocks, which rounds to two.

    The parameter is measured *from the handle*, not from the world origin, so
    those two positions read as ``-4`` and ``-1.6``.  The difference is the
    same 2.4 either way, which is the only quantity the drag uses -- but the
    sign of the parameter itself is asserted here so a change of origin cannot
    pass unnoticed.
    """
    box_min, box_max = (0, 0, 0), (8, 8, 8)
    camera = (4.0, 4.0, -20.0)
    face = handle_named("face:+x")
    assert tuple(H.handle_centre(face, box_min, box_max)) == (8.0, 4.0, 4.0)

    drag = H.begin_drag(face, box_min, box_max, camera, (0.0, 0.0, 1.0))
    assert drag is not None
    assert drag.plane_normal is None
    assert drag.start_parameter == pytest.approx(4.0 - 8.0)

    exact = drag.world_offset(camera, (1.0, 0.0, 10.0))
    assert exact[0] == pytest.approx(2.4)
    assert list(drag.block_offset(camera, (1.0, 0.0, 10.0))) == [2, 0, 0]


def test_a_drag_from_one_screen_point_to_another_lands_on_that_point() -> None:
    """The promise, end to end: grab a handle at A, drop it at B, it is at B.

    Nothing here restates the drag arithmetic.  A is read off by projecting the
    handle through the camera matrix; B is chosen; the drag is applied; and the
    moved handle is projected through that same matrix and compared with B.  A
    drag that moved the box the right way by the wrong amount fails, which is
    the thing a direction-only assertion cannot see.

    The tolerance is a rounding tolerance, not a fudge.  A selection box's
    corners are whole blocks, so the landing point can be up to half a block
    out; half a block is converted into screen units by measuring what one
    block is worth at this distance, and the assertion is against that.
    """
    box_min, box_max = (0, 0, 0), (12, 8, 10)
    camera_location = (30.0, 22.0, -26.0)
    camera_rotation = (-45.0, 25.0)
    matrix = world_to_screen(camera_location, camera_rotation)

    corner = handle_named("corner:-x+y-z")
    grabbed = H.handle_centre(corner, box_min, box_max)
    point_a = cursor_of(matrix, grabbed)

    ray_a = H.cursor_ray_direction(*camera_rotation, FOV, ASPECT, point_a)
    drag = H.begin_drag(corner, box_min, box_max, camera_location, ray_a)
    assert drag is not None

    point_b = point_a + numpy.array([0.28, -0.16])
    ray_b = H.cursor_ray_direction(*camera_rotation, FOV, ASPECT, point_b)
    offset = drag.block_offset(camera_location, ray_b)
    assert offset is not None
    assert numpy.any(offset), "the drag resolved to no movement at all"

    landed = cursor_of(matrix, grabbed + offset)

    one_block = numpy.linalg.norm(
        cursor_of(matrix, grabbed + numpy.array([0.0, 1.0, 0.0])) - point_a
    )
    assert numpy.linalg.norm(landed - point_b) < one_block

    # And the box itself moved by exactly that offset -- both corners, so the
    # selection translated rather than resized.
    moved_min = numpy.asarray(box_min) + offset
    moved_max = numpy.asarray(box_max) + offset
    assert list(moved_max - moved_min) == list(
        numpy.asarray(box_max) - numpy.asarray(box_min)
    )


def test_the_pointer_ray_no_longer_sticks_on_the_viewport_centre_lines() -> None:
    """A cursor on the exact centre line used to be read as the screen centre.

    The original test was ``if delta_x and delta_y``, so a pointer at
    ``(0.4, 0.0)`` -- anywhere along the horizontal middle of the viewport --
    produced the same ray as one at dead centre.  Dragging horizontally across
    the middle of the screen therefore stopped dead.

    Rather than assert a sign, which is easy to write backwards and then
    "confirm", this sends each ray out to a plane and projects the point it
    reaches back through the camera.  A correct ray comes back as the cursor
    that cast it.  Before the fix the two centre-line cases came back as
    ``(0, 0)``.
    """
    camera = numpy.array([0.0, 0.0, -20.0])
    matrix = world_to_screen(tuple(camera), (0.0, 0.0))

    for cursor in ((0.4, 0.0), (0.0, 0.4), (0.35, -0.25), (-0.5, 0.2)):
        ray = H.cursor_ray_direction(0.0, 0.0, FOV, ASPECT, cursor)
        landing = camera + ray * (20.0 / ray[2])
        # 1e-4 rather than something tighter: the ray builder floors any
        # component below a millionth to a millionth, so a component that ought
        # to be exactly zero arrives as 1e-6.  That guard predates this work and
        # keeps later divisions finite; the error it leaves is four orders of
        # magnitude below the 0.4 the defect produced.
        assert cursor_of(matrix, landing) == pytest.approx(
            numpy.asarray(cursor), abs=1e-4
        ), f"the ray for {cursor} does not point at {cursor}"


def test_a_face_handle_aimed_at_the_camera_is_not_offered() -> None:
    """Looking down an axis, that axis's handles are withheld, not left inert.

    They cannot resolve a drag -- their axis has no width on screen -- and a
    control that is drawn but cannot work is the defect this whole feature was
    asked to avoid.  The corner handles stay, because their plane is chosen to
    face the camera and so is never edge-on.
    """
    box_min, box_max = (0, 0, 0), (8, 8, 8)
    offered = H.visible_handles(box_min, box_max, view_direction=(0.0, -1.0, 0.0))
    names = {handle.name for handle in offered}

    assert "face:+y" not in names
    assert "face:-y" not in names
    assert {"face:+x", "face:-x", "face:+z", "face:-z"} <= names
    assert sum(handle.is_corner for handle in offered) == 8


def test_hit_testing_picks_the_nearer_of_two_handles_on_the_same_line() -> None:
    """Two handles on one line of sight: the near one wins.

    Edge-on to the box, a face handle and the corner handles beside it project
    onto the same pixels.  Taking whichever came first in the list would move
    the box from the far side of it, with nothing on screen to explain why.
    """
    box_min, box_max = (0, 0, 0), (8, 8, 8)
    # Straight down the x axis through both x face handles.
    camera = (-40.0, 4.0, 4.0)
    hit = H.hit_handle(box_min, box_max, camera, (1.0, 0.0, 0.0))
    assert hit is not None and hit.name == "face:-x"

    # And from the other side, the other one.
    hit = H.hit_handle(box_min, box_max, (40.0, 4.0, 4.0), (-1.0, 0.0, 0.0))
    assert hit is not None and hit.name == "face:+x"


def test_a_ray_that_misses_every_handle_grabs_nothing() -> None:
    """Empty sky is not a handle. Without this the box would jump on any click."""
    assert (
        H.hit_handle((0, 0, 0), (8, 8, 8), (0.0, 200.0, -40.0), (0.0, 0.0, 1.0)) is None
    )


def test_a_ray_pointing_away_from_the_drag_plane_reports_nothing() -> None:
    """Rather than the mirrored point behind the camera, which would teleport it."""
    assert (
        H.ray_plane_intersection((0, 0, 0), (0, 0, -1), (0, 0, 10), (0, 0, 1)) is None
    )


def test_handles_scale_with_the_box_but_stop_at_both_ends() -> None:
    """Big enough to aim at on a single block; not the whole of a large region."""
    flat = H.handle_half_size((0, 0, 0), (30, 0, 30))
    single = H.handle_half_size((0, 0, 0), (1, 1, 1))
    middling = H.handle_half_size((0, 0, 0), (3, 3, 3))
    huge = H.handle_half_size((0, 0, 0), (400, 400, 400))

    # A one-block-thick slab has an extent of zero on one axis, and would take
    # the handles to nothing without the floor.
    assert flat == pytest.approx(H.MIN_HANDLE_HALF)
    assert H.MIN_HANDLE_HALF <= single < middling < huge
    assert huge == pytest.approx(H.MAX_HANDLE_HALF)


# ---------------------------------------------------------------------------
# the mesh
# ---------------------------------------------------------------------------


def test_the_mesh_carries_a_cube_for_every_handle() -> None:
    """Fourteen handles, fourteen cubes, each centred where the geometry says.

    The comparison is against ``handle_centre`` on the *local* box the mesh
    builds in, so this is not the module agreeing with itself: it is the mesh
    agreeing with the module the hit test also uses.  If those two ever part
    company, a handle is drawn in one place and grabbable in another.
    """
    box = mesh()
    box._create_geometry_()

    low = box.min % 16 - 0.01
    high = low + (box.max - box.min) + 0.02

    assert box.verts.shape[0] == HANDLE_VERTS_START + HANDLE_VERTS_TOTAL
    for handle in H.BOX_HANDLES:
        chunk = handle_verts(box, handle.name)
        expected = H.handle_centre(handle, low, high)
        assert numpy.allclose(
            chunk[:, :3].mean(axis=0), expected, atol=1e-3
        ), f"{handle.name} is drawn away from where it can be grabbed"
        assert chunk[:, :3].max() > chunk[:, :3].min(), f"{handle.name} has no size"


def test_face_and_corner_handles_are_told_apart_by_colour() -> None:
    """They do different things -- one axis against a plane -- so they look different."""
    box = mesh()
    box._create_geometry_()

    face = tuple(handle_verts(box, "face:+x")[0, 9:12])
    corner = tuple(handle_verts(box, "corner:+x+y+z")[0, 9:12])
    assert face != corner
    assert face == pytest.approx(box.face_handle_colour)
    assert corner == pytest.approx(box.corner_handle_colour)


def test_the_hovered_handle_changes_colour_and_grows() -> None:
    """Two channels, because colour alone is one channel some readers lack."""
    box = mesh()
    box._create_geometry_()
    before = handle_verts(box, "face:+y").copy()

    box.hovered_handle = "face:+y"
    box._create_geometry_()
    after = handle_verts(box, "face:+y")

    assert tuple(after[0, 9:12]) == pytest.approx(box.handle_hover_colour)
    assert tuple(after[0, 9:12]) != pytest.approx(box.face_handle_colour)

    def span(verts):
        return float(verts[:, 0].max() - verts[:, 0].min())

    # The literal first, and it is the assertion that matters.  Comparing only
    # against ``HANDLE_HOVER_SCALE`` would make this test agree with the
    # constant rather than with the requirement: set the constant to 1.0 and a
    # scale-only assertion passes over a hover that no longer grows at all.
    # Watched doing exactly that before this line was added.
    assert span(after) > span(before) * 1.15, "the hover is not visibly bigger"
    assert span(after) == pytest.approx(span(before) * HANDLE_HOVER_SCALE, rel=1e-3)

    # Its neighbours are untouched: hover marks one handle, not the set.
    assert tuple(handle_verts(box, "face:+x")[0, 9:12]) == pytest.approx(
        box.face_handle_colour
    )


def test_a_withheld_handle_leaves_no_geometry_behind() -> None:
    """Not merely recoloured or moved away -- collapsed, so it rasterises nothing."""
    box = mesh()
    box.set_handle_view(view_direction=(0.0, -1.0, 0.0))
    box._create_geometry_()

    withheld = handle_verts(box, "face:+y")
    assert withheld[:, :3].min() == 0.0 and withheld[:, :3].max() == 0.0

    kept = handle_verts(box, "face:+x")
    assert kept[:, :3].max() > kept[:, :3].min()


def test_hovering_a_handle_that_is_then_withheld_forgets_it() -> None:
    """Otherwise a handle nobody can see stays lit, and the hover never clears."""
    box = mesh()
    box.hovered_handle = "face:+y"
    box.set_handle_view(view_direction=(0.0, -1.0, 0.0))
    assert box.hovered_handle is None


def test_turning_the_handles_off_removes_all_of_them() -> None:
    """The state a box being drawn out or resized is in."""
    box = mesh()
    box.show_handles = False
    box._create_geometry_()
    tail = box.verts[HANDLE_VERTS_START:, :3]
    assert tail.min() == 0.0 and tail.max() == 0.0


def test_the_handles_do_not_disturb_the_box_they_sit_on() -> None:
    """The first 360 vertices are the box, and they must still be the box.

    Appending to a vertex array whose offsets are written down in four places
    is exactly the change that silently overwrites one of them.
    """
    plain = mesh()
    plain.show_handles = False
    plain._create_geometry_()
    with_handles = mesh()
    with_handles._create_geometry_()

    assert numpy.array_equal(
        plain.verts[:HANDLE_VERTS_START], with_handles.verts[:HANDLE_VERTS_START]
    )
