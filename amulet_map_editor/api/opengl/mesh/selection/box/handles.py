"""Where a selection box's grab handles are, and what dragging one does.

Everything here is arithmetic.  No OpenGL call, no wx window, no canvas: a
handle is a position and a constraint, a drag is a ray and a subtraction, and
both can be checked on a machine with no graphics card at all.  That separation
is the whole point of the module -- the drawing in
:mod:`render_selection_editable` and the input wiring in
``BlockSelectionBehaviour`` both ask *this* file where a handle sits and how far
a drag has moved, so a test that pins the arithmetic pins what the user gets.

Two kinds of handle, with deliberately different constraints:

``face``
    One per face, at its centre.  Dragging moves the box along that face's own
    axis and nothing else, so a drag that wanders sideways on screen still only
    changes one coordinate.

``corner``
    One per corner.  Dragging moves the box in a plane -- two degrees of freedom
    -- with the plane chosen as the one most square-on to the camera, which is
    what makes the box appear to follow the cursor rather than slide away from
    it.

Both resolve to a *world* delta, not a pixel delta.  A box twenty blocks away
and a box two hundred blocks away move by what is under the cursor in each
case, which is the difference between a handle that feels attached to the box
and one that feels attached to the mouse.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple

import numpy

from amulet.utils.matrix import rotation_matrix_xy

__all__ = [
    "AXIS_NAMES",
    "BoxHandle",
    "HandleDrag",
    "BOX_HANDLES",
    "FACE_HANDLES",
    "CORNER_HANDLES",
    "cursor_ray_direction",
    "handle_half_size",
    "handle_centre",
    "handle_bounds",
    "face_handle_is_usable",
    "visible_handles",
    "hit_handle",
    "ray_box_distance",
    "ray_plane_intersection",
    "closest_parameter_on_line",
    "dominant_axis",
    "begin_drag",
]

#: The axis names, in the order the coordinates are stored.
AXIS_NAMES = ("x", "y", "z")

#: Smallest and largest a handle's half-extent may become, in blocks.  The
#: lower bound keeps a handle on a 1x1x1 box big enough to aim at; the upper
#: bound stops the handles on a 300-block region from becoming the region.
MIN_HANDLE_HALF = 0.15
MAX_HANDLE_HALF = 0.75

#: How much of the box's smallest side one handle may take up.  Six means the
#: three handles along an edge (corner, face centre, corner) never touch.
HANDLE_SIZE_DIVISOR = 6.0

#: Below this, a look vector component is treated as zero when picking the
#: plane a corner drag runs in.  Purely to keep the choice stable when the
#: camera is almost exactly on an axis.
_AXIS_EPSILON = 1e-9

#: How closely a face handle's axis may line up with the direction it is being
#: looked along before it stops being offered.  A handle you are staring
#: straight down cannot be dragged: its axis has no width on screen, so the
#: cursor has nothing to move it by, and the closest-point solution turns a
#: pixel of cursor movement into an unbounded jump.  ``0.9`` is about 26
#: degrees, past which the amplification is beyond about two blocks per block.
#:
#: Such a handle is *withheld*, not merely made inert -- a control drawn where
#: it cannot work reads as broken, and the corner handles beside it can still
#: move the box in that plane, so nothing is actually lost.
MAX_FACE_ALIGNMENT = 0.9


@dataclass(frozen=True)
class BoxHandle:
    """One grab handle: where it sits on the box and what dragging it does.

    ``offset`` says where on each axis the handle lives -- ``-1`` at the
    minimum, ``0`` at the centre, ``+1`` at the maximum -- so a face handle has
    exactly one non-zero component and a corner handle has three.
    """

    name: str
    offset: Tuple[int, int, int]

    @property
    def is_face(self) -> bool:
        """Whether this handle sits at the centre of a face."""
        return sum(1 for value in self.offset if value) == 1

    @property
    def is_corner(self) -> bool:
        """Whether this handle sits on a corner."""
        return all(self.offset)

    @property
    def axis(self) -> Optional[int]:
        """The axis a face handle constrains movement to, or ``None``."""
        if not self.is_face:
            return None
        return next(index for index, value in enumerate(self.offset) if value)


def _build_handles() -> Tuple[Tuple[BoxHandle, ...], Tuple[BoxHandle, ...]]:
    """Return the six face handles and the eight corner handles."""
    faces: List[BoxHandle] = []
    for axis in range(3):
        for direction in (-1, 1):
            offset = [0, 0, 0]
            offset[axis] = direction
            sign = "+" if direction > 0 else "-"
            faces.append(
                BoxHandle(
                    f"face:{sign}{AXIS_NAMES[axis]}", (offset[0], offset[1], offset[2])
                )
            )
    corners: List[BoxHandle] = []
    for x in (-1, 1):
        for y in (-1, 1):
            for z in (-1, 1):
                name = "corner:" + "".join(
                    ("+" if value > 0 else "-") + axis
                    for value, axis in zip((x, y, z), AXIS_NAMES)
                )
                corners.append(BoxHandle(name, (x, y, z)))
    return tuple(faces), tuple(corners)


FACE_HANDLES, CORNER_HANDLES = _build_handles()

#: Every handle a box carries, faces first.  Fourteen in total.
BOX_HANDLES: Tuple[BoxHandle, ...] = FACE_HANDLES + CORNER_HANDLES


def cursor_ray_direction(
    yaw: float,
    pitch: float,
    fov: float,
    aspect_ratio: float,
    cursor: Sequence[float] = (0.0, 0.0),
) -> numpy.ndarray:
    """Return the unit-ish world direction the cursor points along.

    ``cursor`` is the pointer position in the viewport as two values in
    ``[-1, 1]``, which is exactly what ``MouseMovement.mouse_xy_relative``
    gives.  ``yaw`` and ``pitch`` are the camera's rotation in degrees.

    This is the construction ``RaycastBehaviour.look_vector`` has always used,
    lifted out so the drag arithmetic and the editor's own picking cannot drift
    apart -- and so a test can build a ray without a canvas.

    One correction came with the move.  The original applied the cursor offset
    only when *both* components were non-zero, so a pointer anywhere on the
    exact horizontal or vertical centre line of the viewport was treated as
    though it were at the centre of the screen.  Dragging along either centre
    line therefore stuck.  Requiring *either* component fixes it and changes
    nothing else: with one component zero its own rotation term is zero anyway,
    and with both zero the matrix is the identity.
    """
    look_vector = numpy.array([0, 0, 1, 0], dtype=numpy.float64)
    delta_x, delta_y = float(cursor[0]), float(cursor[1])
    if delta_x or delta_y:
        screen_dx = math.atan(delta_x * aspect_ratio * math.tan(math.radians(fov / 2)))
        screen_dy = math.atan(
            delta_y * math.cos(screen_dx) * math.tan(math.radians(fov / 2))
        )
        look_vector = numpy.matmul(
            rotation_matrix_xy(screen_dy, -screen_dx),
            look_vector,
        )
    look_vector = numpy.matmul(
        rotation_matrix_xy(*numpy.radians([pitch, -yaw])), look_vector
    )[:3]
    look_vector[abs(look_vector) < 0.000001] = 0.000001
    return look_vector


def handle_half_size(box_min: Sequence[float], box_max: Sequence[float]) -> float:
    """Return half the world-space width of a handle cube on this box.

    It scales with the box so the handles on a two-block selection are not the
    same size as the selection, and stops scaling at both ends so they never
    become unclickable or absurd.
    """
    extent = numpy.abs(
        numpy.asarray(box_max, dtype=numpy.float64)
        - numpy.asarray(box_min, dtype=numpy.float64)
    )
    smallest = float(numpy.min(extent)) if extent.size else 0.0
    return float(
        numpy.clip(smallest / HANDLE_SIZE_DIVISOR, MIN_HANDLE_HALF, MAX_HANDLE_HALF)
    )


def handle_centre(
    handle: BoxHandle, box_min: Sequence[float], box_max: Sequence[float]
) -> numpy.ndarray:
    """Return the world-space centre of ``handle`` on the given box."""
    low = numpy.asarray(box_min, dtype=numpy.float64)
    high = numpy.asarray(box_max, dtype=numpy.float64)
    middle = (low + high) / 2
    centre = numpy.empty(3, dtype=numpy.float64)
    for axis, value in enumerate(handle.offset):
        if value < 0:
            centre[axis] = low[axis]
        elif value > 0:
            centre[axis] = high[axis]
        else:
            centre[axis] = middle[axis]
    return centre


def handle_bounds(
    handle: BoxHandle, box_min: Sequence[float], box_max: Sequence[float]
) -> Tuple[numpy.ndarray, numpy.ndarray]:
    """Return the minimum and maximum corners of ``handle``'s cube."""
    centre = handle_centre(handle, box_min, box_max)
    half = handle_half_size(box_min, box_max)
    return centre - half, centre + half


def face_handle_is_usable(handle: BoxHandle, view_direction: Sequence[float]) -> bool:
    """Whether dragging ``handle`` along its axis can do anything from here.

    Corner handles are always usable -- their plane is chosen to face the
    camera, so it is never edge-on.  A face handle is refused when its axis
    points too nearly at or away from the viewer; see :data:`MAX_FACE_ALIGNMENT`.
    """
    axis = handle.axis
    if axis is None:
        return True
    vector = numpy.asarray(view_direction, dtype=numpy.float64)
    length = float(numpy.linalg.norm(vector))
    if length < 1e-12:
        return True
    return abs(float(vector[axis]) / length) < MAX_FACE_ALIGNMENT


def visible_handles(
    box_min: Sequence[float],
    box_max: Sequence[float],
    camera_position: Optional[Sequence[float]] = None,
    view_direction: Optional[Sequence[float]] = None,
    handles: Iterable[BoxHandle] = BOX_HANDLES,
) -> Tuple[BoxHandle, ...]:
    """Return the handles worth drawing and worth hit-testing from this view.

    One list, used by both the mesh and the input handling, so what is drawn
    and what can be grabbed cannot disagree.  Pass ``view_direction`` for an
    orthographic camera, whose position says nothing about which way it looks;
    pass ``camera_position`` for a perspective one, where each handle is seen
    along its own slightly different ray.  With neither, every handle is
    returned.
    """
    if view_direction is None and camera_position is None:
        return tuple(handles)
    kept: List[BoxHandle] = []
    for handle in handles:
        if view_direction is not None:
            direction = numpy.asarray(view_direction, dtype=numpy.float64)
        else:
            direction = handle_centre(handle, box_min, box_max) - numpy.asarray(
                camera_position, dtype=numpy.float64
            )
        if face_handle_is_usable(handle, direction):
            kept.append(handle)
    return tuple(kept)


def ray_box_distance(
    origin: Sequence[float],
    direction: Sequence[float],
    box_min: Sequence[float],
    box_max: Sequence[float],
) -> Optional[float]:
    """Return how far along ``direction`` the ray first meets the box.

    ``None`` when it misses, or when the box is entirely behind the origin.  A
    ray starting inside the box returns ``0.0``, which is what makes a handle
    the camera is already sitting inside still grabbable.
    """
    start = numpy.asarray(origin, dtype=numpy.float64)
    vector = numpy.asarray(direction, dtype=numpy.float64)
    low = numpy.asarray(box_min, dtype=numpy.float64)
    high = numpy.asarray(box_max, dtype=numpy.float64)

    near = -numpy.inf
    far = numpy.inf
    for axis in range(3):
        if abs(vector[axis]) < 1e-12:
            # Parallel to this slab: a miss unless the origin is already inside
            # it.  Without this the division below produces an infinity whose
            # sign depends on a rounding artefact.
            if start[axis] < low[axis] or start[axis] > high[axis]:
                return None
            continue
        t1 = (low[axis] - start[axis]) / vector[axis]
        t2 = (high[axis] - start[axis]) / vector[axis]
        if t1 > t2:
            t1, t2 = t2, t1
        near = max(near, t1)
        far = min(far, t2)
        if near > far:
            return None
    if far < 0:
        return None
    return float(max(near, 0.0))


def hit_handle(
    box_min: Sequence[float],
    box_max: Sequence[float],
    origin: Sequence[float],
    direction: Sequence[float],
    handles: Iterable[BoxHandle] = BOX_HANDLES,
) -> Optional[BoxHandle]:
    """Return the nearest handle the ray passes through, or ``None``.

    Nearest rather than first-found: two handles genuinely overlap on screen
    when the camera is edge-on to the box, and picking the far one would move
    the box the wrong way with no visible reason.
    """
    best: Optional[BoxHandle] = None
    best_distance = numpy.inf
    for handle in handles:
        low, high = handle_bounds(handle, box_min, box_max)
        distance = ray_box_distance(origin, direction, low, high)
        if distance is None:
            continue
        if distance < best_distance:
            best = handle
            best_distance = distance
    return best


def closest_parameter_on_line(
    line_point: Sequence[float],
    line_direction: Sequence[float],
    ray_origin: Sequence[float],
    ray_direction: Sequence[float],
) -> Optional[float]:
    """Return ``t`` where the line is closest to the ray, or ``None``.

    ``None`` when the two are parallel, where "closest" has no single answer.
    This is what turns a cursor position into a position along one axis: the
    handle slides to the point on its own axis nearest the line of sight.
    """
    p = numpy.asarray(line_point, dtype=numpy.float64)
    u = numpy.asarray(line_direction, dtype=numpy.float64)
    q = numpy.asarray(ray_origin, dtype=numpy.float64)
    v = numpy.asarray(ray_direction, dtype=numpy.float64)

    uu = float(numpy.dot(u, u))
    vv = float(numpy.dot(v, v))
    uv = float(numpy.dot(u, v))
    denominator = uu * vv - uv * uv
    if abs(denominator) < 1e-12 or uu < 1e-12:
        return None
    w = p - q
    uw = float(numpy.dot(u, w))
    vw = float(numpy.dot(v, w))
    return float((uv * vw - vv * uw) / denominator)


def ray_plane_intersection(
    origin: Sequence[float],
    direction: Sequence[float],
    plane_point: Sequence[float],
    plane_normal: Sequence[float],
) -> Optional[numpy.ndarray]:
    """Return where the ray meets the plane, or ``None`` if it never does.

    A ray running away from the plane returns ``None`` rather than the point
    behind the camera it would meet if extended backwards -- dragging must not
    teleport the box to a mirrored position when the cursor crosses the horizon.
    """
    start = numpy.asarray(origin, dtype=numpy.float64)
    vector = numpy.asarray(direction, dtype=numpy.float64)
    point = numpy.asarray(plane_point, dtype=numpy.float64)
    normal = numpy.asarray(plane_normal, dtype=numpy.float64)

    denominator = float(numpy.dot(normal, vector))
    if abs(denominator) < 1e-9:
        return None
    distance = float(numpy.dot(normal, point - start)) / denominator
    if distance < 0:
        return None
    return start + vector * distance


def dominant_axis(direction: Sequence[float]) -> int:
    """Return the world axis a direction points along most strongly."""
    vector = numpy.abs(numpy.asarray(direction, dtype=numpy.float64))
    vector[vector < _AXIS_EPSILON] = 0.0
    return int(numpy.argmax(vector))


@dataclass
class HandleDrag:
    """A drag in progress: what was grabbed, and where it was grabbed from.

    Held by the behaviour between the press and the release.  It stores the box
    as it was when the drag began, so every intermediate position is measured
    from the same origin -- accumulating per-frame deltas instead would drift,
    and the drift would be worst exactly where the ray is most glancing.
    """

    handle: BoxHandle
    start_min: numpy.ndarray
    start_max: numpy.ndarray
    #: ``None`` for an axis drag; the plane's normal for a corner drag.
    plane_normal: Optional[numpy.ndarray]
    #: The parameter along the axis at the moment of the press (axis drags).
    start_parameter: float = 0.0
    #: The world point under the cursor at the moment of the press (corner drags).
    start_point: Optional[numpy.ndarray] = None

    @property
    def axis(self) -> Optional[int]:
        """The single axis this drag is constrained to, or ``None``."""
        return self.handle.axis

    def world_offset(
        self, origin: Sequence[float], direction: Sequence[float]
    ) -> Optional[numpy.ndarray]:
        """Return the continuous world offset for the cursor ray, or ``None``.

        ``None`` means the ray says nothing usable this frame -- looking away
        from the drag plane, or straight down the drag axis -- and the caller
        should leave the box where it is rather than guess.
        """
        if self.plane_normal is None:
            axis = self.handle.axis
            if axis is None:
                return None
            unit = numpy.zeros(3, dtype=numpy.float64)
            unit[axis] = 1.0
            parameter = closest_parameter_on_line(
                handle_centre(self.handle, self.start_min, self.start_max),
                unit,
                origin,
                direction,
            )
            if parameter is None:
                return None
            return unit * (parameter - self.start_parameter)

        if self.start_point is None:
            return None
        point = ray_plane_intersection(
            origin,
            direction,
            self.start_point,
            self.plane_normal,
        )
        if point is None:
            return None
        offset = point - self.start_point
        # Kill any component along the normal.  Floating point leaves a
        # residue there even though the point is by construction on the plane,
        # and rounding that residue can add a whole block on the wrong axis.
        offset = offset - self.plane_normal * float(
            numpy.dot(offset, self.plane_normal)
        )
        return offset

    def block_offset(
        self, origin: Sequence[float], direction: Sequence[float]
    ) -> Optional[numpy.ndarray]:
        """Return the whole-block offset for the cursor ray, or ``None``.

        A selection box's corners are integers, so a drag that resolves to 3.4
        blocks moves the box 3 -- rounded, not truncated, or the box would lag
        half a block behind the cursor in one direction and not the other.
        """
        offset = self.world_offset(origin, direction)
        if offset is None:
            return None
        return numpy.round(offset).astype(numpy.int64)


def begin_drag(
    handle: BoxHandle,
    box_min: Sequence[float],
    box_max: Sequence[float],
    origin: Sequence[float],
    direction: Sequence[float],
) -> Optional[HandleDrag]:
    """Start a drag on ``handle``, or return ``None`` if it cannot be started.

    The plane a corner drag runs in is chosen here, once, from the direction
    the camera is looking at the moment of the press -- not re-chosen every
    frame.  Re-choosing would flip the plane mid-drag as the cursor crosses a
    diagonal, and the box would jump.
    """
    low = numpy.asarray(box_min, dtype=numpy.float64)
    high = numpy.asarray(box_max, dtype=numpy.float64)
    centre = handle_centre(handle, low, high)

    if handle.is_face:
        axis = handle.axis
        unit = numpy.zeros(3, dtype=numpy.float64)
        unit[axis] = 1.0
        parameter = closest_parameter_on_line(centre, unit, origin, direction)
        if parameter is None:
            return None
        return HandleDrag(
            handle=handle,
            start_min=low.copy(),
            start_max=high.copy(),
            plane_normal=None,
            start_parameter=parameter,
        )

    normal = numpy.zeros(3, dtype=numpy.float64)
    normal[dominant_axis(direction)] = 1.0
    point = ray_plane_intersection(origin, direction, centre, normal)
    if point is None:
        return None
    return HandleDrag(
        handle=handle,
        start_min=low.copy(),
        start_max=high.copy(),
        plane_normal=normal,
        start_point=point,
    )
