#!/usr/bin/env python3
"""Render the editor's real selection box through the real shader, and save a PNG.

This is not a drawing of what the handles ought to look like.  The shipped
:class:`RenderSelectionEditable` is drawn in a real OpenGL context with the
project's own ``render_chunk`` shader, and the framebuffer is read back -- so a
handle that is missing from the vertex array, collapsed to a point, tinted the
same colour as the box, or facing the wrong way is missing from the picture too.

**The frame is drawn by** :class:`BlockSelectionBehaviour`, not by this script.
That distinction is the whole value of the capture and it was missing from the
first version, which set ``show_handles``, ``set_handle_view`` and
``hovered_handle`` on the mesh itself.  A picture taken that way says the mesh
*can* draw handles; it says nothing about whether the editor ever asks it to,
and it comes out identical if the behaviour's own draw is turning them off.  So
the mesh here is told nothing: the behaviour decides whether the handles are up,
which of them this camera can offer, and which one the pointer is on, exactly as
it does on every frame of the running editor.

Two things stand in for the running editor and neither of them touches the
geometry under test:

* a **stub resource pack** supplying a flat white 2x2 texture instead of the
  Minecraft atlas, because the atlas takes seconds to build and contributes one
  uniform grey to these particular quads;
* an **off-screen window**, positioned far outside any display, because a GL
  context needs a real window handle on Windows and nobody wants a frame
  appearing over their work.  Under ``--headless-desktop`` it is a normal
  visible frame -- on a desktop nobody is looking at.

Run it with a Python that has wx and PyOpenGL::

    py -3.11 scripts/capture_selection_handles.py --out docs/huishots/handles.png

It exits non-zero, loudly, when the frame comes back empty: a capture harness
that reports success over a blank rectangle is worse than no harness.
"""

from __future__ import annotations

# Photograph a fresh profile, never the profile of whoever runs this. These
# images are published, and a real profile puts that machine's recent worlds --
# with its user directory in every path -- and any display name the user has
# renamed the application to onto the documentation site. It must run before
# the config module is imported, because that module reads the environment at
# import time and a later redirect silently does nothing.
import os
import tempfile

_capture_profile = tempfile.mkdtemp(prefix="amulet-capture-profile-")
# Every store the application reads, not just the settings one. Redirecting
# CONFIG_DIR alone removed the renamed title from these captures and left the
# recent-worlds list still reading the real machine's store -- so the published
# images kept showing `C:\Users\<name>\...` in every row. The stores are
# separate on purpose, and a capture has to move all of them or it moves none
# of the ones that matter.
for _store in (
    "CONFIG_DIR",
    "DATA_DIR",
    "CACHE_DIR",
    "LOG_DIR",
    "AMULET_RECENTS_DIR",
    "AMULET_HISTORY_DIR",
    "AMULET_LOG_DIR_PATH",
):
    os.environ[_store] = _capture_profile

import argparse
import math
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    # A script run as a file puts its own directory on the path, not the
    # working directory -- so without this an editable install elsewhere on the
    # machine can answer the import and the capture describes a different
    # checkout entirely.
    sys.path.insert(0, str(REPO_ROOT))

import numpy  # noqa: E402
import wx  # noqa: E402
from wx import glcanvas  # noqa: E402

from OpenGL.GL import (  # noqa: E402
    GL_BLEND,
    GL_COLOR_BUFFER_BIT,
    GL_CULL_FACE,
    GL_DEPTH_BUFFER_BIT,
    GL_DEPTH_TEST,
    GL_LINEAR,
    GL_NEAREST,
    GL_ONE_MINUS_SRC_ALPHA,
    GL_RGBA,
    GL_SRC_ALPHA,
    GL_TEXTURE_2D,
    GL_TEXTURE_MAG_FILTER,
    GL_TEXTURE_MIN_FILTER,
    GL_UNSIGNED_BYTE,
    glBindTexture,
    glBlendFunc,
    glClear,
    glClearColor,
    glCullFace,
    GL_BACK,
    glEnable,
    glGenTextures,
    glReadPixels,
    glTexImage2D,
    glTexParameteri,
    glViewport,
)

import amulet_map_editor  # noqa: E402

if not str(Path(amulet_map_editor.__file__).resolve()).startswith(str(REPO_ROOT)):
    raise SystemExit(
        "amulet_map_editor resolved to "
        f"{amulet_map_editor.__file__}, which is outside {REPO_ROOT}. "
        "The capture would describe a different checkout."
    )

from amulet.api.selection import SelectionBox, SelectionGroup  # noqa: E402

from amulet_map_editor.api.opengl.camera import Projection  # noqa: E402
from amulet_map_editor.api.opengl.matrix import (  # noqa: E402
    displacement_matrix,
    perspective_matrix,
    rotation_matrix_yx,
)
from amulet_map_editor.api.opengl.mesh.selection.box import handles  # noqa: E402
from amulet_map_editor.programs.edit.api.behaviour.block_selection_behaviour import (  # noqa: E402
    BlockSelectionBehaviour,
)

#: Fewer distinct colours than this and the frame is a flat rectangle, whatever
#: it claims to have drawn.
MIN_DISTINCT_COLOURS = 6

#: The clear colour, and the only two constants the shader needs to be predicted:
#: the stub atlas is a flat 235 and ``render_chunk`` multiplies by 0.85.  Between
#: them these turn a handle's tint into the byte triple it must land on screen
#: as, which is what lets the capture assert that a handle was *painted* rather
#: than merely counted in the vertex array.
CLEAR_COLOUR = (0.10, 0.11, 0.13)
ATLAS_VALUE = 235 / 255
SHADER_DIM = 0.85

#: How far a pixel may sit from the predicted colour and still count.  Handles
#: are blended over whatever is behind them, which is sometimes the background
#: and sometimes a face of the box, and that backdrop reaches about 8% of the
#: result.
COLOUR_TOLERANCE = 20

#: Below this many pixels of a handle's own colour, nothing recognisable was
#: drawn.  A handle cube on this box covers hundreds.
MIN_HANDLE_PIXELS = 40


def painted(tint) -> numpy.ndarray:
    """The byte colour a tint arrives on screen as, through the real shader.

    ``render_chunk`` computes ``texture * tint * 0.85`` and keeps the texture's
    alpha, so the frame shows that blended over the clear colour.
    """
    source = numpy.array(tint, dtype=numpy.float64) * ATLAS_VALUE * SHADER_DIM
    blended = source * ATLAS_VALUE + numpy.array(CLEAR_COLOUR) * (1 - ATLAS_VALUE)
    return numpy.round(numpy.clip(blended, 0, 1) * 255).astype(numpy.int64)


def count_near(pixels: numpy.ndarray, colour: numpy.ndarray) -> int:
    """How many pixels sit within :data:`COLOUR_TOLERANCE` of ``colour``."""
    difference = numpy.abs(pixels[:, :, :3].astype(numpy.int64) - colour)
    return int(numpy.count_nonzero(numpy.all(difference <= COLOUR_TOLERANCE, axis=2)))


class StubResourcePack:
    """The smallest thing ``TriMesh`` will accept in place of the block atlas."""

    def __init__(self):
        self._texture = None

    def get_texture_path(self, namespace, path):
        return f"{namespace}:{path}"

    def texture_bounds(self, path):
        return (0.0, 0.0, 1.0, 1.0)

    def get_atlas_id(self, context_identifier):
        if self._texture is None:
            self._texture = glGenTextures(1)
            glBindTexture(GL_TEXTURE_2D, self._texture)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
            pixels = numpy.full((2, 2, 4), 235, dtype=numpy.uint8)
            glTexImage2D(
                GL_TEXTURE_2D,
                0,
                GL_RGBA,
                2,
                2,
                0,
                GL_RGBA,
                GL_UNSIGNED_BYTE,
                pixels,
            )
        return self._texture


def cursor_of(camera, point) -> tuple:
    """Where to put the pointer so it lands on ``point``, in viewport units.

    Two answers, because the editor casts two different rays.  In perspective
    the ray runs from the camera through the pixel, so projecting the world
    point through the camera matrix gives the pixel.  Top-down is orthographic:
    every ray is vertical and the one under the pointer starts *above the
    pointer*, at the ``x, z`` that ``get_2d_mouse_location`` derives from the
    same two numbers -- so this inverts that instead.  Using the matrix in both
    would put the pointer somewhere plausible and wrong, and the report would
    name a handle the picture does not show.
    """
    if camera.projection_mode == Projection.TOP_DOWN:
        camera_x, _, camera_z = camera.location
        return (
            float((point[0] - camera_x) / (camera.fov * camera.aspect_ratio)),
            float((point[2] - camera_z) / camera.fov),
        )
    clip = numpy.matmul(
        camera.transformation_matrix,
        numpy.array([*point, 1.0], dtype=numpy.float64),
    )
    ndc = clip[:2] / clip[3]
    return float(ndc[0]), float(-ndc[1])


class StubCamera:
    """The camera's read-only surface, which is all a behaviour ever touches."""

    def __init__(self, location, rotation, aspect_ratio, top_down: bool):
        self.location = location
        self.rotation = rotation
        self.fov = 70.0
        self.aspect_ratio = aspect_ratio
        self.projection_mode = (
            Projection.TOP_DOWN if top_down else Projection.PERSPECTIVE
        )
        self.rotating = False

    @property
    def transformation_matrix(self) -> numpy.ndarray:
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
    def __init__(self, resource_pack):
        self.opengl_resource_pack = resource_pack


def render(
    width: int,
    height: int,
    out_path: Path,
    hovered: str | None,
    show_handles: bool,
    headless_desktop: bool,
    top_down: bool = False,
) -> dict:
    """Draw one frame and write it out. Returns a report about what was drawn."""
    app = wx.App()
    style = wx.DEFAULT_FRAME_STYLE
    frame = wx.Frame(
        None,
        title="selection handle capture",
        size=(width, height),
        style=style,
        pos=(0, 0) if headless_desktop else (-4000, -4000),
    )
    # The requested size is the *client* size.  Sizing the frame instead leaves
    # the title bar and borders inside it, and the capture comes back with a
    # black band across the top where the canvas does not reach.
    frame.SetClientSize(width, height)
    attributes = glcanvas.GLAttributes()
    attributes.PlatformDefaults().MinRGBA(8, 8, 8, 8).DoubleBuffer().Depth(24).EndList()
    canvas = glcanvas.GLCanvas(frame, attributes, size=(width, height), pos=(0, 0))
    context_attributes = glcanvas.GLContextAttrs()
    context_attributes.CoreProfile().OGLVersion(3, 3).EndList()
    context = glcanvas.GLContext(canvas, ctxAttrs=context_attributes)
    frame.Show()
    for _ in range(5):
        wx.Yield()
    if not canvas.SetCurrent(context):
        raise SystemExit("could not make the OpenGL context current")

    glViewport(0, 0, width, height)
    glClearColor(0.10, 0.11, 0.13, 1.0)
    glEnable(GL_DEPTH_TEST)
    glEnable(GL_CULL_FACE)
    glCullFace(GL_BACK)
    glEnable(GL_BLEND)
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

    if top_down:
        # What the editor's top-down mode sees.  Its projection is orthographic
        # rather than this one, but the fact being shown is not about the
        # projection: looking straight down, the two y face handles are
        # withheld, because dragging along an axis pointing at the viewer
        # cannot move anything.  The behaviour is told the mode, and works the
        # rest out; nothing here passes it a view direction.
        location = (6.0, 40.0, 5.0)
        rotation = (0.0, 89.9)
    else:
        # A three-quarter view from above: the one angle at which every face and
        # every corner handle that is offered is also visible.
        location = (24.0, 19.0, 24.0)
        rotation = (135.0, 28.0)

    resource_pack = StubResourcePack()
    stub_canvas = wx.Frame(None, title="capture canvas")
    stub_canvas.context_identifier = "capture"
    stub_canvas.renderer = StubRenderer(resource_pack)
    stub_canvas.camera = StubCamera(location, rotation, width / height, top_down)
    stub_canvas.mouse = StubMouse()
    stub_canvas.selection = StubSelection()
    stub_canvas.world = None
    stub_canvas.dimension = "minecraft:overworld"
    stub_canvas.buttons = type("Buttons", (), {"pressed_actions": frozenset()})()

    behaviour = BlockSelectionBehaviour(stub_canvas)
    behaviour.selection_group = SelectionGroup(SelectionBox((0, 0, 0), (12, 8, 10)))
    box = behaviour._active_selection

    if hovered:
        # Put the pointer where that handle actually is on screen and let the
        # behaviour work out what is under it.  Naming the handle to the mesh
        # instead would prove only that the mesh can colour one in.
        handle = next(each for each in handles.BOX_HANDLES if each.name == hovered)
        stub_canvas.mouse.mouse_xy_relative = cursor_of(
            stub_canvas.camera,
            handles.handle_centre(handle, box.min, box.max),
        )
        behaviour._refresh_handle_hover()
        if box.hovered_handle != hovered:
            raise SystemExit(
                f"asked to hover {hovered}; the behaviour reports "
                f"{box.hovered_handle}. The capture would be mislabelled."
            )

    if not show_handles:
        # The one thing the mesh is still told directly: a reference frame of
        # the box as it looked before handles existed.  It is a "before"
        # picture, not evidence about the behaviour, and the report says so.
        box.show_handles = False
        box.draw(stub_canvas.camera.transformation_matrix, location)
    else:
        behaviour.draw()

    raw = glReadPixels(0, 0, width, height, GL_RGBA, GL_UNSIGNED_BYTE)
    pixels = numpy.frombuffer(raw, dtype=numpy.uint8).reshape((height, width, 4))
    pixels = pixels[::-1]  # OpenGL reads bottom-up

    image = wx.Image(width, height)
    image.SetData(pixels[:, :, :3].tobytes())
    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.SaveFile(str(out_path), wx.BITMAP_TYPE_PNG)

    counts = Counter(map(tuple, pixels[::4, ::4, :3].reshape(-1, 3).tolist()))
    # Whatever colour dominates a frame containing one small box is the clear
    # colour.  Reading it back beats writing the constant down: an eighth of a
    # unit of rounding between ``glClearColor`` and the framebuffer would make
    # a hard-coded background match nothing, and the fraction below -- the one
    # field that can see an empty frame -- would report a full one every time.
    background, _ = counts.most_common(1)[0]
    drawn = sum(count for colour, count in counts.items() if colour != background)
    report = {
        "path": str(out_path),
        "size": (width, height),
        "driven_by": (
            "mesh (before-picture reference)"
            if not show_handles
            else "BlockSelectionBehaviour.draw"
        ),
        "distinct_colours": len(counts),
        "non_background_fraction": drawn / max(1, sum(counts.values())),
        "show_handles": box.show_handles,
        "visible_handles": [handle.name for handle in box.visible_handles],
        "hovered": box.hovered_handle,
        "face_handle_pixels": count_near(pixels, painted(box.face_handle_colour)),
        "corner_handle_pixels": count_near(pixels, painted(box.corner_handle_colour)),
        "hover_pixels": count_near(pixels, painted(box.handle_hover_colour)),
    }

    stub_canvas.Destroy()
    frame.Destroy()
    for _ in range(3):
        wx.Yield()
    del app
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="docs/huishots/selection-handles.png")
    parser.add_argument("--width", type=int, default=900)
    parser.add_argument("--height", type=int, default=620)
    parser.add_argument(
        "--hover",
        default=None,
        help="name of a handle to draw in the hover colour, e.g. face:+y",
    )
    parser.add_argument(
        "--no-handles",
        action="store_true",
        help=(
            "a before-picture: the mesh is told to hide the handles, so this "
            "one frame is not driven by the behaviour and is not evidence "
            "about it"
        ),
    )
    parser.add_argument(
        "--top-down",
        action="store_true",
        help="look straight down, where the two y face handles are withheld",
    )
    parser.add_argument(
        "--headless-desktop",
        action="store_true",
        help="the window is on a desktop nobody is looking at; show it normally",
    )
    args = parser.parse_args()

    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = REPO_ROOT / out_path

    report = render(
        args.width,
        args.height,
        out_path,
        args.hover,
        not args.no_handles,
        args.headless_desktop,
        args.top_down,
    )
    for key, value in report.items():
        print(f"{key}: {value}")

    if report["distinct_colours"] < MIN_DISTINCT_COLOURS:
        print(
            "FAIL: the frame has almost no colours in it, which means nothing "
            "drew. A capture that reports success over a blank rectangle is the "
            "defect this check exists for.",
            file=sys.stderr,
        )
        return 2
    if report["non_background_fraction"] < 0.02:
        print(
            "FAIL: almost every pixel is the clear colour. The box is not in " "frame.",
            file=sys.stderr,
        )
        return 3

    # The handles, specifically, rather than "something drew".  Every check
    # above passes over a frame containing the box and no handles at all --
    # which is exactly what a deleted draw call, a collapsed cube or a
    # behaviour that never turns them on would produce.
    if args.no_handles:
        if report["face_handle_pixels"] or report["corner_handle_pixels"]:
            print(
                "FAIL: the before-picture has handle-coloured pixels in it.",
                file=sys.stderr,
            )
            return 4
        return 0

    handle_pixels = report["face_handle_pixels"] + report["corner_handle_pixels"]
    if handle_pixels < MIN_HANDLE_PIXELS:
        print(
            f"FAIL: only {handle_pixels} pixels carry a handle colour. The box "
            "is in frame and its handles are not, which is the whole feature "
            "missing behind a picture that looks fine.",
            file=sys.stderr,
        )
        return 5
    if args.hover and report["hover_pixels"] < MIN_HANDLE_PIXELS:
        print(
            f"FAIL: {args.hover} is reported as hovered but only "
            f"{report['hover_pixels']} pixels carry the hover colour.",
            file=sys.stderr,
        )
        return 6
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
