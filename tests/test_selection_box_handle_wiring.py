"""The handles are wired to real events, not merely to methods that exist.

A test that calls ``_start_handle_drag`` directly proves the arithmetic and
nothing about the application: a handler written and never bound passes it every
time.  So every input here goes in as an event, through the canvas, dispatched
by wx -- ``EVT_INPUT_PRESS``, ``EVT_MOTION``, ``EVT_PRE_DRAW``,
``EVT_INPUT_RELEASE`` -- which is exactly the route the editor uses.  Unbind any
one of them and the corresponding test goes red.

The canvas is a stub, deliberately and only where a stub cannot lie: it supplies
a camera, a pointer position, a place to store the selection and a resource pack
that returns fixed texture bounds.  The behaviour under test, the mesh, the
handle geometry and the event dispatch are all the shipped ones.  Nothing here
opens a world or a GL context, because neither is reachable in a test session
and neither is what these tests are about.
"""

from __future__ import annotations

import math

import numpy
import pytest

wx = pytest.importorskip("wx")

from amulet.api.errors import ChunkLoadError  # noqa: E402
from amulet.api.selection import SelectionBox, SelectionGroup  # noqa: E402

from amulet_map_editor.api.opengl.camera import Projection  # noqa: E402
from amulet_map_editor.api.opengl.events import PreDrawEvent  # noqa: E402
from amulet_map_editor.api.opengl.matrix import (  # noqa: E402
    displacement_matrix,
    perspective_matrix,
    rotation_matrix_yx,
)
from amulet_map_editor.api.opengl.mesh.selection.box import handles as H  # noqa: E402
from amulet_map_editor.programs.edit.api.behaviour.block_selection_behaviour import (  # noqa: E402
    BlockSelectionBehaviour,
)
from amulet_map_editor.programs.edit.api.events import (  # noqa: E402
    InputPressEvent,
    InputReleaseEvent,
)
from amulet_map_editor.programs.edit.api.key_config import ACT_BOX_CLICK  # noqa: E402

FOV = 70.0
ASPECT = 16 / 9
BOX = ((0, 0, 0), (12, 8, 10))
CAMERA_LOCATION = (30.0, 22.0, -26.0)
CAMERA_ROTATION = (-45.0, 25.0)


@pytest.fixture(scope="module")
def app():
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


class StubPack:
    def get_texture_path(self, namespace, path):
        return f"{namespace}:{path}"

    def texture_bounds(self, path):
        return (0.0, 0.0, 1.0, 1.0)


class StubCamera:
    def __init__(self):
        self.location = CAMERA_LOCATION
        self.rotation = CAMERA_ROTATION
        self.fov = FOV
        self.aspect_ratio = ASPECT
        self.projection_mode = Projection.PERSPECTIVE
        self.rotating = False

    @property
    def transformation_matrix(self):
        projection = perspective_matrix(
            math.radians(self.fov), self.aspect_ratio, 0.1, 10000.0
        )
        yaw, pitch = self.rotation
        view = numpy.matmul(
            rotation_matrix_yx(math.radians(yaw + 180), math.radians(pitch)),
            displacement_matrix(*-numpy.array(self.location, dtype=numpy.float64)),
        )
        return numpy.matmul(projection, view)


class StubMouse:
    def __init__(self):
        self.mouse_xy_relative = (0.0, 0.0)


class StubSelection:
    def __init__(self):
        self.selection_group = SelectionGroup()


class StubRenderer:
    def __init__(self):
        self.opengl_resource_pack = StubPack()


class StubWorld:
    """A world with no chunks loaded, which is a state the editor really has.

    ``closest_block_3d`` walks the ray asking for each chunk it crosses and
    treats a load failure as "nothing solid here", so this makes the block
    picking answer honestly rather than being bypassed.  That matters because
    the hover refresh sits in the same branch as the block picking: stub the
    picking out and the branch never runs, which is exactly how a deleted
    ``_refresh_handle_hover`` call went unnoticed.
    """

    sub_chunk_size = 16

    def get_chunk(self, cx, cz, dimension):
        raise ChunkLoadError(f"no chunk {cx},{cz} in {dimension}")


class StubCanvas(wx.Frame):
    """A real wx window -- so binding and dispatch are real -- and no more."""

    def __init__(self):
        super().__init__(None, title="handle wiring", size=(320, 200))
        self.context_identifier = "wiring-test"
        self.renderer = StubRenderer()
        self.camera = StubCamera()
        self.mouse = StubMouse()
        self.selection = StubSelection()
        self.world = StubWorld()
        self.dimension = "minecraft:overworld"
        self.buttons = type("Buttons", (), {"pressed_actions": frozenset()})()
        self.cursors = []

    # Recorded rather than applied: the assertion is that the behaviour asked
    # for a hand, and a real SetCursor on an unshown frame proves nothing.
    def SetCursor(self, cursor):  # noqa: N802 - wx naming
        self.cursors.append(cursor)
        return True


def cursor_of(matrix, point) -> numpy.ndarray:
    """Where a world point lands, in the units ``mouse_xy_relative`` reports."""
    clip = numpy.matmul(matrix, numpy.array([*point, 1.0], dtype=numpy.float64))
    ndc = clip[:2] / clip[3]
    return numpy.array([ndc[0], -ndc[1]])


@pytest.fixture
def behaviour(app):
    canvas = StubCanvas()
    subject = BlockSelectionBehaviour(canvas)
    subject.bind_events()
    subject.selection_group = SelectionGroup(SelectionBox(*BOX))
    yield subject
    canvas.Destroy()


def send(behaviour_, event) -> None:
    """Dispatch an event the way the canvas does, synchronously."""
    behaviour_.canvas.GetEventHandler().ProcessEvent(event)


def look_at(behaviour_, world_point) -> numpy.ndarray:
    """Point the stub pointer at a world position, and say where that is."""
    where = cursor_of(behaviour_.canvas.camera.transformation_matrix, world_point)
    behaviour_.canvas.mouse.mouse_xy_relative = (float(where[0]), float(where[1]))
    return where


def grabbed_corner(behaviour_) -> numpy.ndarray:
    """The world position of a corner handle that is in view from the camera."""
    box = behaviour_._active_selection
    return H.handle_centre(H.BOX_HANDLES[-1], box.min, box.max)


def handle_position(behaviour_, name: str) -> numpy.ndarray:
    """The world position of the named handle on the active box."""
    box = behaviour_._active_selection
    handle = next(each for each in H.BOX_HANDLES if each.name == name)
    return H.handle_centre(handle, box.min, box.max)


def test_pressing_on_a_handle_starts_a_drag(behaviour) -> None:
    """Through EVT_INPUT_PRESS. Unbind that handler and this goes red."""
    look_at(behaviour, grabbed_corner(behaviour))
    send(behaviour, InputPressEvent(ACT_BOX_CLICK))

    assert behaviour._handle_drag is not None
    assert behaviour._handle_drag.handle.is_corner
    assert behaviour._editing is True
    assert behaviour._resizing is False, "a move must not be mistaken for a resize"


def test_pressing_on_empty_sky_still_starts_the_old_new_box_drag(behaviour) -> None:
    """The handles intercept a press; they must not swallow every press.

    Without this, every click in the viewport would be checked against the
    handles and the ordinary "drag out a new box" gesture would be gone -- a
    regression the drag tests above could never see, because they only ever
    aim at a handle.
    """
    behaviour.canvas.mouse.mouse_xy_relative = (-0.95, -0.95)
    send(behaviour, InputPressEvent(ACT_BOX_CLICK))

    assert behaviour._handle_drag is None
    assert behaviour._editing is True
    assert behaviour._initial_box is None, "this is a new box, not an edit of one"


def test_dragging_moves_the_box_to_where_the_pointer_went(behaviour) -> None:
    """Press on a handle, move the mouse, and the box follows it in world space.

    The whole route runs: the press arrives as an input event, the move as a
    motion event (which is what marks the pointer dirty), and the frame as a
    pre-draw event (which is what makes the behaviour act on it).  The check is
    the same round trip the geometry tests use -- project the handle's new
    position back through the camera and compare it with where the pointer is --
    so a drag that moved the box the right way by the wrong amount fails.
    """
    corner = grabbed_corner(behaviour)
    point_a = look_at(behaviour, corner)
    send(behaviour, InputPressEvent(ACT_BOX_CLICK))
    assert behaviour._handle_drag is not None

    before = behaviour._active_selection.points.copy()

    point_b = point_a + numpy.array([0.3, -0.18])
    behaviour.canvas.mouse.mouse_xy_relative = (float(point_b[0]), float(point_b[1]))
    send(behaviour, wx.MouseEvent(wx.wxEVT_MOTION))
    send(behaviour, PreDrawEvent())

    after = behaviour._active_selection.points
    assert not numpy.array_equal(before, after), "the box did not move at all"

    offset = after - before
    assert numpy.array_equal(
        offset[0], offset[1]
    ), "both corners must take the same offset -- a move, not a resize"

    matrix = behaviour.canvas.camera.transformation_matrix
    landed = cursor_of(matrix, corner + offset[0])
    one_block = numpy.linalg.norm(
        cursor_of(matrix, corner + numpy.array([0.0, 1.0, 0.0])) - point_a
    )
    assert numpy.linalg.norm(landed - point_b) < one_block


def test_releasing_commits_the_move_to_the_canvas_selection(behaviour) -> None:
    """Until the release the world does not know; after it, it does."""
    corner = grabbed_corner(behaviour)
    point_a = look_at(behaviour, corner)
    send(behaviour, InputPressEvent(ACT_BOX_CLICK))
    behaviour.canvas.mouse.mouse_xy_relative = tuple(
        point_a + numpy.array([0.3, -0.18])
    )
    send(behaviour, wx.MouseEvent(wx.wxEVT_MOTION))
    send(behaviour, PreDrawEvent())

    moved = behaviour._active_selection.selection_box
    send(behaviour, InputReleaseEvent(ACT_BOX_CLICK))

    assert behaviour._handle_drag is None
    assert behaviour._editing is False
    assert behaviour._active_selection.locked is True
    committed = behaviour.canvas.selection.selection_group
    assert len(committed) == 1
    assert tuple(committed[0].min) == tuple(moved.min)
    assert tuple(committed[0].max) == tuple(moved.max)


def test_escape_during_a_drag_puts_the_box_back(behaviour) -> None:
    """A move must be abandonable, like every other edit in this tool."""
    original = behaviour._active_selection.points.copy()
    point_a = look_at(behaviour, grabbed_corner(behaviour))
    send(behaviour, InputPressEvent(ACT_BOX_CLICK))
    behaviour.canvas.mouse.mouse_xy_relative = tuple(
        point_a + numpy.array([0.3, -0.18])
    )
    send(behaviour, wx.MouseEvent(wx.wxEVT_MOTION))
    send(behaviour, PreDrawEvent())
    assert not numpy.array_equal(original, behaviour._active_selection.points)

    key = wx.KeyEvent(wx.wxEVT_KEY_DOWN)
    key.SetKeyCode(wx.WXK_ESCAPE)
    send(behaviour, key)

    assert behaviour._handle_drag is None
    assert numpy.array_equal(original, behaviour._active_selection.points)


def test_hovering_a_handle_lights_it_and_offers_a_hand(behaviour) -> None:
    """The two halves of "this is grabbable": the mesh's colour and the cursor.

    Both are asserted because they are set in different places -- one on the
    mesh, one on the window -- and either can be lost without the other
    noticing.
    """
    look_at(behaviour, grabbed_corner(behaviour))
    behaviour._refresh_handle_hover()

    assert behaviour._active_selection.hovered_handle is not None
    assert behaviour.canvas.cursors, "the pointer never changed shape"

    behaviour.canvas.mouse.mouse_xy_relative = (-0.95, -0.95)
    behaviour._refresh_handle_hover()
    assert behaviour._active_selection.hovered_handle is None
    assert len(behaviour.canvas.cursors) == 2, "the hand was never taken away"


def test_a_top_down_camera_withholds_the_vertical_handles(behaviour) -> None:
    """The mode where dragging up and down cannot mean anything.

    Asserted through the behaviour rather than the geometry module, because the
    thing that can break is the behaviour forgetting that an orthographic camera
    does not look along the line from its own position.
    """
    behaviour.canvas.camera.projection_mode = Projection.TOP_DOWN
    behaviour._active_selection.set_handle_view(**behaviour._handle_view())

    offered = {handle.name for handle in behaviour._active_selection.visible_handles}
    assert "face:+y" not in offered and "face:-y" not in offered
    assert {"face:+x", "face:-z"} <= offered


# ----------------------------------------------------------------------
# the call sites, rather than the things they call
#
# Every test above aims at a function that does the work.  Each one of them
# passes with the *call* to that function deleted, because the test makes the
# call itself.  These do not: they drive ``draw`` and ``_update_pointer`` -- the
# two methods the editor calls every frame -- and assert what those methods do
# to the real mesh.  Delete a line from either and one of these goes red.
# ----------------------------------------------------------------------


def record_gl(behaviour_) -> list:
    """Silence the three GL draw calls, and say which meshes were asked to draw.

    Only ``draw`` is replaced, and only on the mesh instances.  ``show_handles``,
    ``set_handle_view`` and ``visible_handles`` stay the shipped ones, so the
    assertions land on real state that the real ``draw`` really set -- a
    recording double in place of the whole mesh would happily accept whatever it
    was told and prove nothing.
    """
    drawn: list = []

    def recorder(name, mesh):
        def draw(*args, **kwargs):
            drawn.append(name)

        mesh.draw = draw

    recorder("group", behaviour_._selection)
    recorder("pointer", behaviour_._pointer)
    if behaviour_._active_selection is not None:
        recorder("active", behaviour_._active_selection)
    return drawn


def test_drawing_a_settled_box_puts_its_handles_up(behaviour) -> None:
    """The frame that follows an ordinary idle moment shows the handles.

    ``draw`` is where that is decided, and nothing else asserts it: the geometry
    knows where a handle goes and the mesh knows how to draw one, but if the
    behaviour never asks, fourteen handles are computed every frame and none of
    them reach the screen.
    """
    behaviour._active_selection.show_handles = False  # a state a previous edit leaves
    drawn = record_gl(behaviour)

    behaviour.draw()

    assert behaviour._active_selection.show_handles is True
    assert "active" in drawn, "the box mesh was never asked to draw"


def test_drawing_mid_creation_takes_the_handles_off(behaviour) -> None:
    """While a box is being dragged out they would sit under the pointer."""
    behaviour.canvas.mouse.mouse_xy_relative = (-0.95, -0.95)
    send(behaviour, InputPressEvent(ACT_BOX_CLICK))
    assert behaviour._editing and behaviour._handle_drag is None
    record_gl(behaviour)

    behaviour.draw()

    assert behaviour._active_selection.show_handles is False


def test_drawing_mid_handle_drag_keeps_the_handles_up(behaviour) -> None:
    """The one edit the handles are for must not make them vanish.

    ``_editing`` is true throughout a handle drag -- it is what stops the rest
    of the editor touching the box -- so a rule of "hide them while editing"
    written without the drag in mind would blank the handle being held.
    """
    look_at(behaviour, grabbed_corner(behaviour))
    send(behaviour, InputPressEvent(ACT_BOX_CLICK))
    assert behaviour._handle_drag is not None and behaviour._editing
    record_gl(behaviour)

    behaviour.draw()

    assert behaviour._active_selection.show_handles is True


def test_grabbing_a_handle_unlocks_the_box(behaviour) -> None:
    """The colour that says "this is moving", and its return.

    Locked is the state the box is drawn in when nothing is happening to it.  A
    drag that never unlocks it looks identical to one that never started.
    """
    look_at(behaviour, grabbed_corner(behaviour))
    assert behaviour._active_selection.locked is True

    send(behaviour, InputPressEvent(ACT_BOX_CLICK))
    assert behaviour._active_selection.locked is False, "the box never went live"

    send(behaviour, InputReleaseEvent(ACT_BOX_CLICK))
    assert behaviour._active_selection.locked is True


def test_drawing_refreshes_the_withheld_set_as_the_camera_orbits(behaviour) -> None:
    """Orbiting changes which handles work, and the mouse need not have moved.

    That is the whole reason the refresh is in ``draw`` as well as in the
    pointer update: a camera swinging overhead under keyboard control fires no
    motion event, so without this the offered set would be whatever it was when
    the pointer last moved, and a face handle pointing straight at the viewer
    would still be drawn and still be grabbable.
    """
    record_gl(behaviour)
    behaviour.draw()
    before = {handle.name for handle in behaviour._active_selection.visible_handles}
    assert {"face:+y", "face:-y"} <= before, "nothing was withheld to begin with"

    behaviour.canvas.camera.location = (6.0, 200.0, 5.0)  # straight overhead
    behaviour.draw()

    after = {handle.name for handle in behaviour._active_selection.visible_handles}
    assert "face:+y" not in after and "face:-y" not in after
    assert {"face:+x", "face:-x", "face:+z", "face:-z"} <= after


def hover_via_pointer_update(behaviour_, world_point) -> None:
    """Point at a world position and run one frame the way the editor does."""
    look_at(behaviour_, world_point)
    send(behaviour_, wx.MouseEvent(wx.wxEVT_MOTION))
    send(behaviour_, PreDrawEvent())


def test_moving_the_pointer_lights_the_handle_under_it(behaviour) -> None:
    """Hover through ``_update_pointer``, not by calling the refresh directly.

    Calling ``_refresh_handle_hover`` in a test proves the refresh works and
    says nothing about whether anything calls it.  This goes in as a motion
    event and a frame, so the branch that actually reaches it -- the one with
    the block picking in it -- has to run.
    """
    hover_via_pointer_update(behaviour, grabbed_corner(behaviour))

    assert behaviour._active_selection.hovered_handle is not None
    assert behaviour.canvas.cursors, "the pointer never offered a hand"

    hover_via_pointer_update(behaviour, numpy.array([300.0, 300.0, 300.0]))
    assert behaviour._active_selection.hovered_handle is None


def test_a_handle_wins_over_the_face_behind_it(behaviour) -> None:
    """A handle sits on a face, so both are under the pointer at once.

    Whichever the box highlights is the one the user is being promised, and the
    press does the handle.  A *face* handle is the case that matters: it sits in
    the middle of a face the ray unambiguously hits, so the resize highlight
    would certainly come on without the rule.  A corner handle would not prove
    it -- the ray only grazes the box there and may miss it altogether, leaving
    the highlight off for a reason that has nothing to do with handles.

    The first half is the precondition that keeps the second honest: aim at bare
    face and the highlight really does come on, so its absence over a handle
    means something.
    """
    hover_via_pointer_update(behaviour, numpy.array([3.0, 2.0, 0.0]))
    assert (
        behaviour._active_selection.hovered_handle is None
    ), "aim at bare face, not at a handle"
    assert behaviour._highlight is True, "the face highlight never came on at all"

    hover_via_pointer_update(behaviour, handle_position(behaviour, "face:-z"))

    assert behaviour._active_selection.hovered_handle == "face:-z"
    assert behaviour._highlight is False, "the box offered a resize under the handle"


def test_the_hand_comes_back_after_an_orbit_that_ended_on_a_handle(behaviour) -> None:
    """Turning the camera must not cost the pointer its shape for good.

    The camera takes the cursor away while it is being turned -- blank during,
    default afterwards -- so the behaviour's record of what it applied is stale
    the moment an orbit starts.  Recording a hand it never got to apply makes
    the "nothing changed" early-out swallow every later attempt, and the handle
    under the pointer stays a plain arrow until the pointer leaves it and comes
    back.
    """
    # An orbit locks the pointer to the middle of the viewport, so the ray that
    # decides what is hovered mid-turn is the one through dead centre -- not
    # wherever the mouse was.  Aiming the camera straight down it is the only
    # way to reach the latch at all: leave the pointer off-centre and nothing is
    # hovered during the orbit, the flag never moves, and a test built that way
    # passes against the broken code.
    corner = handle_position(behaviour, "corner:+x+y-z")
    behaviour.canvas.camera.location = (
        float(corner[0]),
        float(corner[1]),
        float(corner[2]) - 20.0,
    )
    behaviour.canvas.camera.rotation = (0.0, 0.0)
    behaviour.canvas.mouse.mouse_xy_relative = (0.0, 0.0)

    behaviour.canvas.camera.rotating = True
    behaviour._refresh_handle_hover()
    assert (
        behaviour._active_selection.hovered_handle is not None
    ), "the centre ray missed every handle, so the orbit case was never reached"
    assert not behaviour.canvas.cursors, "a hand was drawn over a hidden cursor"

    behaviour.canvas.camera.rotating = False
    behaviour._refresh_handle_hover()

    assert behaviour._active_selection.hovered_handle is not None
    assert behaviour.canvas.cursors, "the hand never came back after the orbit"
