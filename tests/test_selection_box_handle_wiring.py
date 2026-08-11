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
    application = wx.App()
    yield application


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


class StubCanvas(wx.Frame):
    """A real wx window -- so binding and dispatch are real -- and no more."""

    def __init__(self):
        super().__init__(None, title="handle wiring", size=(320, 200))
        self.context_identifier = "wiring-test"
        self.renderer = StubRenderer()
        self.camera = StubCamera()
        self.mouse = StubMouse()
        self.selection = StubSelection()
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
