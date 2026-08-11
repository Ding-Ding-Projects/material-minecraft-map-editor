#!/usr/bin/env python3
"""Render the real selection-box mesh through the real shader, and save a PNG.

This is not a drawing of what the handles ought to look like.  It builds the
shipped :class:`RenderSelectionEditable`, in a real OpenGL context, with the
project's own ``render_chunk`` shader, and reads the framebuffer back -- so a
handle that is missing from the vertex array, collapsed to a point, tinted the
same colour as the box, or facing the wrong way is missing from the picture too.

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

import argparse
import math
import os
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

from amulet_map_editor.api.opengl.matrix import (  # noqa: E402
    displacement_matrix,
    perspective_matrix,
    rotation_matrix_yx,
)
from amulet_map_editor.api.opengl.mesh.selection.box.render_selection_editable import (  # noqa: E402
    RenderSelectionEditable,
)

#: Fewer distinct colours than this and the frame is a flat rectangle, whatever
#: it claims to have drawn.
MIN_DISTINCT_COLOURS = 6


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


def camera_matrix(
    location, rotation, width: int, height: int, fov: float = 70.0
) -> numpy.ndarray:
    """The world-to-screen matrix, built the way ``Camera`` builds it."""
    projection = perspective_matrix(math.radians(fov), width / height, 0.1, 10000.0)
    yaw, pitch = rotation
    view = numpy.matmul(
        rotation_matrix_yx(math.radians(yaw + 180), math.radians(pitch)),
        displacement_matrix(*-numpy.array(location, dtype=numpy.float64)),
    )
    return numpy.matmul(projection, view)


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

    resource_pack = StubResourcePack()
    box = RenderSelectionEditable("capture", resource_pack)
    box.point1 = numpy.array([0, 0, 0])
    box.point2 = numpy.array([12, 8, 10])
    box.locked = True
    box.show_handles = show_handles

    if top_down:
        # What the editor's top-down mode sees.  Its projection is orthographic
        # rather than this one, but the fact being shown is not about the
        # projection: looking straight down, the two y face handles are
        # withheld, because dragging along an axis pointing at the viewer
        # cannot move anything.
        location = (6.0, 40.0, 5.0)
        rotation = (0.0, 89.9)
        box.set_handle_view(view_direction=(0.0, -1.0, 0.0))
    else:
        # A three-quarter view from above: the one angle at which every face and
        # every corner handle that is offered is also visible.
        location = (24.0, 19.0, 24.0)
        rotation = (135.0, 28.0)
        box.set_handle_view(camera_position=location)
    if hovered:
        box.hovered_handle = hovered

    box.draw(camera_matrix(location, rotation, width, height))

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
        "distinct_colours": len(counts),
        "non_background_fraction": drawn / max(1, sum(counts.values())),
        "visible_handles": [handle.name for handle in box.visible_handles],
        "hovered": box.hovered_handle,
    }

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
        help="draw the box with handles off, for a before/after pair",
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
    return 0


if __name__ == "__main__":
    os.environ.setdefault("CONFIG_DIR", str(REPO_ROOT / "build" / "capture-config"))
    raise SystemExit(main())
