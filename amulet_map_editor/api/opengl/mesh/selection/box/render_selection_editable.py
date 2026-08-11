from typing import Optional, Sequence, Tuple

import numpy
from OpenGL.GL import (
    GL_TRIANGLES,
    glCullFace,
    GL_FRONT,
    GL_BACK,
    glDisable,
    GL_DEPTH_TEST,
    GL_LINE_STRIP,
    glEnable,
    glGetBooleanv,
    glGetIntegerv,
    GL_CULL_FACE_MODE,
)

from amulet.api.data_types import PointCoordinatesAny
from .render_selection_highlightable import RenderSelectionHighlightable
from amulet_map_editor.api.opengl.resource_pack import OpenGLResourcePack
from amulet_map_editor.api.opengl.data_types import RGBColour
from . import handles as handle_geometry
from .colours import colours

#: Where the handle cubes start in the vertex array, and how many verts each
#: one takes.  The numbers above them are the existing layout; a handle is an
#: ordinary six-faced box, so it costs the same 36 verts as the outer box does.
HANDLE_VERTS_START = 360
HANDLE_VERT_COUNT = 6 * 2 * 3
HANDLE_VERTS_TOTAL = HANDLE_VERT_COUNT * len(handle_geometry.BOX_HANDLES)

#: How much bigger the handle under the pointer is drawn.  Colour alone would
#: not do it: the hover colour has to differ from an orange handle, a gold one,
#: the cyan edges and the grey face, and any colour that manages all four is
#: still a colour, which is the one channel some readers do not have.  Size is
#: the second channel, and it costs nothing but a multiply.
HANDLE_HOVER_SCALE = 1.4


class RenderSelectionEditable(RenderSelectionHighlightable):
    """A drawable selection box with additional editing controls"""

    def __init__(self, context_identifier: str, resource_pack: OpenGLResourcePack):
        super().__init__(context_identifier, resource_pack)
        # is the locked or is it being modified. Changes the colour of the faces.
        self._locked = True
        # Grab handles: which are worth offering from where the camera is, and
        # which one the pointer is currently over.
        self._visible_handles: Tuple[handle_geometry.BoxHandle, ...] = (
            handle_geometry.BOX_HANDLES
        )
        self._hovered_handle: Optional[str] = None
        self._show_handles = True

    def _init_verts(self):
        # the first 36 verts are used for the full box which is used for lines
        # the next 36 verts are used for the inset faces
        # the next 144 verts are used for the edges
        # the next 144 verts are used for the corners
        # the next 504 verts are used for the fourteen grab handles

        verts_per_quad = 2 * 3  # triangles * verts
        self.verts = numpy.zeros(
            (
                6 * verts_per_quad
                + 6  # original box verts (used for the lines)
                * 9
                * verts_per_quad  # new verts
                + HANDLE_VERTS_TOTAL,  # the grab handles
                self._vert_len,
            ),
            dtype=numpy.float32,
        )
        self.verts[:, 5:9] = self.resource_pack.texture_bounds(
            self.resource_pack.get_texture_path("amulet", "amulet_ui/selection")
        )

        self.verts[verts_per_quad * 6 :, 9:12] = self.box_tint
        self.verts[verts_per_quad * 12 : verts_per_quad * 36, 9:12] = self.edge_colour

    @property
    def highlight_colour(self) -> RGBColour:
        if self.locked:
            return colours.get("box_highlight", (0.5, 0.5, 1.0))
        else:
            return colours.get("box_highlight_move", (1.0, 0.7, 0.3))

    @property
    def edge_colour(self) -> RGBColour:
        return colours.get("box_edge", (0.5, 1.0, 1.0))

    @property
    def corner_colour(self) -> RGBColour:
        return colours.get("box_corner", (1.0, 1.0, 0.5))

    @property
    def point1_colour(self) -> RGBColour:
        return colours.get("box_point1", (0.0, 1.0, 0.0))

    @property
    def point2_colour(self) -> RGBColour:
        return colours.get("box_point2", (0.0, 0.0, 1.0))

    @property
    def face_handle_colour(self) -> RGBColour:
        """The colour of the six face-centre handles.

        Warm, because everything else on this box is cool: the edges are cyan,
        the corners pale yellow and the highlight blue, so a handle that shared
        any of those would read as another piece of the box rather than as
        something to take hold of.
        """
        return colours.get("box_handle", (1.0, 0.45, 0.1))

    @property
    def corner_handle_colour(self) -> RGBColour:
        """The colour of the eight corner handles.

        Deliberately not the face colour: the two do different things -- one
        axis against a plane -- and a user who cannot tell them apart until
        after dragging has been told nothing.
        """
        return colours.get("box_handle_corner", (1.0, 0.75, 0.2))

    @property
    def handle_hover_colour(self) -> RGBColour:
        """The colour of the handle under the pointer.

        Magenta because nothing else on this box is: the handles are orange and
        gold, the edges cyan, the faces grey, the point markers green and blue.
        A white hover looked like a lit grey face in the capture and was the
        first thing that had to change.
        """
        return colours.get("box_handle_hover", (1.0, 0.25, 0.85))

    @property
    def show_handles(self) -> bool:
        """Whether the grab handles are drawn at all."""
        return self._show_handles

    @show_handles.setter
    def show_handles(self, show: bool):
        show = bool(show)
        if show != self._show_handles:
            self._show_handles = show
            self._mark_recreate()

    @property
    def visible_handles(self) -> Tuple[handle_geometry.BoxHandle, ...]:
        """The handles currently drawn, which are the ones that can be grabbed.

        The behaviour hit-tests against this exact tuple, so a handle that is
        not drawn cannot be grabbed by accident and a handle that is drawn
        cannot turn out to be inert.
        """
        return self._visible_handles

    @property
    def hovered_handle(self) -> Optional[str]:
        """The name of the handle under the pointer, or ``None``."""
        return self._hovered_handle

    @hovered_handle.setter
    def hovered_handle(self, name: Optional[str]):
        if name != self._hovered_handle:
            self._hovered_handle = name
            self._mark_recreate()

    def set_handle_view(
        self,
        camera_position: Optional[Sequence[float]] = None,
        view_direction: Optional[Sequence[float]] = None,
    ):
        """Recompute which handles this camera can usefully offer.

        Rebuilding the mesh is only asked for when the set actually changes,
        because this is called whenever the camera moves and the alternative is
        rebuilding 864 vertices on every frame of a pan.
        """
        visible = handle_geometry.visible_handles(
            self.min,
            self.max,
            camera_position=camera_position,
            view_direction=view_direction,
        )
        if visible != self._visible_handles:
            self._visible_handles = visible
            if self._hovered_handle is not None and self._hovered_handle not in {
                handle.name for handle in visible
            }:
                self._hovered_handle = None
            self._mark_recreate()

    @property
    def locked(self) -> bool:
        """Is the selection locked or not.
        If locked (True) the highlight colour will be used, if unlocked (False) the moving colour will be used.
        """
        return self._locked

    @locked.setter
    def locked(self, lock: bool):
        """Set if the selection locked or not.
        If locked (True) the highlight colour will be used, if unlocked (False) the moving colour will be used.
        """
        self._locked = bool(lock)

    def _create_geometry_(self):
        super()._create_geometry_()

        point1, point2 = self._points - self.min + (self.min % 16)
        size = numpy.abs(point2 - point1)
        verts_per_face = 2 * 3  # triangles * verts
        # the edges of the box
        min_point, max_point = numpy.sort([point1, point2], 0).astype(numpy.float64)
        min_point -= 0.01
        max_point += 0.01
        # the edge points offset by the boundary amount.
        min_point_1 = min_point + numpy.min([numpy.ones(3), size / 4], 0)
        max_point_1 = max_point - numpy.min([numpy.ones(3), size / 4], 0)

        # down, up
        # west, east
        # north, south

        face_offset = verts_per_face * 6

        # inset faces
        for axis in ("y", "z", "x"):
            (
                self.verts[face_offset : face_offset + verts_per_face * 2, :3],
                self.verts[face_offset : face_offset + verts_per_face * 2, 3:5],
            ) = self._create_box_faces(
                (
                    min_point[0] if axis == "x" else min_point_1[0],
                    min_point[1] if axis == "y" else min_point_1[1],
                    min_point[2] if axis == "z" else min_point_1[2],
                ),
                (
                    max_point[0] if axis == "x" else max_point_1[0],
                    max_point[1] if axis == "y" else max_point_1[1],
                    max_point[2] if axis == "z" else max_point_1[2],
                ),
                up=axis == "y",
                down=axis == "y",
                north=axis == "z",
                south=axis == "z",
                west=axis == "x",
                east=axis == "x",
            )
            face_offset += verts_per_face * 2

        for y in (False, True):
            for x in (False, True):
                (
                    self.verts[face_offset : face_offset + verts_per_face * 2, :3],
                    self.verts[face_offset : face_offset + verts_per_face * 2, 3:5],
                ) = self._create_box_faces(
                    (
                        max_point_1[0] if x else min_point[0],
                        max_point_1[1] if y else min_point[1],
                        min_point_1[2],
                    ),
                    (
                        max_point[0] if x else min_point_1[0],
                        max_point[1] if y else min_point_1[1],
                        max_point_1[2],
                    ),
                    up=y,
                    down=not y,
                    west=not x,
                    east=x,
                )
                face_offset += verts_per_face * 2

        for y in (False, True):
            for z in (False, True):
                (
                    self.verts[face_offset : face_offset + verts_per_face * 2, :3],
                    self.verts[face_offset : face_offset + verts_per_face * 2, 3:5],
                ) = self._create_box_faces(
                    (
                        min_point_1[0],
                        max_point_1[1] if y else min_point[1],
                        max_point_1[2] if z else min_point[2],
                    ),
                    (
                        max_point_1[0],
                        max_point[1] if y else min_point_1[1],
                        max_point[2] if z else min_point_1[2],
                    ),
                    up=y,
                    down=not y,
                    north=not z,
                    south=z,
                )
                face_offset += verts_per_face * 2

        for x in (False, True):
            for z in (False, True):
                (
                    self.verts[face_offset : face_offset + verts_per_face * 2, :3],
                    self.verts[face_offset : face_offset + verts_per_face * 2, 3:5],
                ) = self._create_box_faces(
                    (
                        max_point_1[0] if x else min_point[0],
                        min_point_1[1],
                        max_point_1[2] if z else min_point[2],
                    ),
                    (
                        max_point[0] if x else min_point_1[0],
                        max_point_1[1],
                        max_point[2] if z else min_point_1[2],
                    ),
                    north=not z,
                    south=z,
                    west=not x,
                    east=x,
                )
                face_offset += verts_per_face * 2

        self.verts[216:360, 9:12] = self.corner_colour
        corners = point2 >= point1
        not_corners = numpy.invert(corners)
        # corners
        for y in (False, True):
            for z in (False, True):
                for x in (False, True):
                    (
                        self.verts[face_offset : face_offset + verts_per_face * 3, :3],
                        self.verts[face_offset : face_offset + verts_per_face * 3, 3:5],
                    ) = self._create_box_faces(
                        (
                            max_point_1[0] if x else min_point[0],
                            max_point_1[1] if y else min_point[1],
                            max_point_1[2] if z else min_point[2],
                        ),
                        (
                            max_point[0] if x else min_point_1[0],
                            max_point[1] if y else min_point_1[1],
                            max_point[2] if z else min_point_1[2],
                        ),
                        up=y,
                        down=not y,
                        north=not z,
                        south=z,
                        west=not x,
                        east=x,
                    )
                    if numpy.array_equal(corners, (x, y, z)):
                        self.verts[
                            face_offset : face_offset + verts_per_face * 3, 9:12
                        ] = self.point2_colour
                    elif numpy.array_equal(not_corners, (x, y, z)):
                        self.verts[
                            face_offset : face_offset + verts_per_face * 3, 9:12
                        ] = self.point1_colour
                    face_offset += verts_per_face * 3

        self._create_handle_geometry(min_point, max_point)

        self.verts[:, 3:5] /= 16

        self.verts[36:72, 9:12] = self.box_tint

        indexes = numpy.zeros(6, numpy.uint8)
        if self.point2[0] > self.point1[0]:
            indexes[[4, 5]] = 0, 3
        else:
            indexes[[4, 5]] = 3, 0

        if self.point2[1] > self.point1[1]:
            indexes[[0, 1]] = 1, 4
        else:
            indexes[[0, 1]] = 4, 1

        if self.point2[2] > self.point1[2]:
            indexes[[2, 3]] = 2, 5
        else:
            indexes[[2, 3]] = 5, 2

        self.verts[36:72][
            numpy.repeat(self._highlight_edges.ravel()[indexes], 6), 9:12
        ] = self.highlight_colour

    def _create_handle_geometry(self, box_min: numpy.ndarray, box_max: numpy.ndarray):
        """Write the grab handle cubes into the tail of the vertex array.

        Every handle keeps a fixed slot whether or not it is drawn, and a
        handle that is not drawn has its slot collapsed to a single point.  A
        degenerate triangle covers no pixels, so nothing appears -- and the draw
        call keeps one constant start and count instead of a length that has to
        be recomputed and kept in step with the geometry.

        The positions here are in the same box-local frame as the rest of this
        mesh (the whole thing is translated by ``transformation_matrix``), which
        is why the *sizes* come from the box's extent rather than its position:
        the extent is the same in either frame.
        """
        offset = HANDLE_VERTS_START
        drawn = (
            {handle.name for handle in self._visible_handles}
            if self._show_handles
            else set()
        )
        half = handle_geometry.handle_half_size(box_min, box_max)
        for handle in handle_geometry.BOX_HANDLES:
            slot = slice(offset, offset + HANDLE_VERT_COUNT)
            if handle.name in drawn:
                centre = handle_geometry.handle_centre(handle, box_min, box_max)
                hovered = handle.name == self._hovered_handle
                extent = half * HANDLE_HOVER_SCALE if hovered else half
                (
                    self.verts[slot, :3],
                    self.verts[slot, 3:5],
                ) = self._create_box(centre - extent, centre + extent)
                if hovered:
                    colour = self.handle_hover_colour
                elif handle.is_corner:
                    colour = self.corner_handle_colour
                else:
                    colour = self.face_handle_colour
                self.verts[slot, 9:12] = colour
            else:
                self.verts[slot, :3] = 0.0
                self.verts[slot, 3:5] = 0.0
            offset += HANDLE_VERT_COUNT

    def draw(
        self, camera_matrix: numpy.ndarray, camera_position: PointCoordinatesAny = None
    ):
        """
        Draw the selection box
        :param camera_matrix: 4x4 transformation matrix for the camera
        :param camera_position: The position of the camera. Used to flip draw direction if camera inside box.
        :return:
        """
        self._setup()
        if self._needs_rebuild:
            self._create_geometry()

        transformation_matrix = numpy.matmul(camera_matrix, self.transformation_matrix)

        depth_state = glGetBooleanv(GL_DEPTH_TEST)
        cull_state = glGetIntegerv(GL_CULL_FACE_MODE)

        # draw the lines around the boxes
        self.draw_start = 0
        self.draw_count = 36

        if depth_state:
            glDisable(GL_DEPTH_TEST)
        self._draw_mode = GL_LINE_STRIP
        super()._draw(transformation_matrix)
        if depth_state:
            glEnable(GL_DEPTH_TEST)

        if camera_position is not None:
            if camera_position in self:
                glCullFace(GL_FRONT)
            else:
                glCullFace(GL_BACK)
        self._draw_mode = GL_TRIANGLES
        self.draw_start = 36
        # 6 faces, 9 quads/face, 2 triangles/quad, 3 verts/triangle
        self.draw_count = 324
        super()._draw(transformation_matrix)

        if self._show_handles:
            # Handles ignore the depth buffer, exactly as the outline does.
            # The hit test behind them has no notion of occlusion either -- it
            # is a ray against fourteen cubes, nothing else -- so a handle that
            # hid behind a hill would still be grabbable, and a control you can
            # grab without seeing is worse than one you can see through.
            if depth_state:
                glDisable(GL_DEPTH_TEST)
            self.draw_start = HANDLE_VERTS_START
            self.draw_count = HANDLE_VERTS_TOTAL
            super()._draw(transformation_matrix)
            if depth_state:
                glEnable(GL_DEPTH_TEST)

        glCullFace(cull_state)
