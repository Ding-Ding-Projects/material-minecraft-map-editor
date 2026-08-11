"""The viewport host and its heads-up display.

When a renderer canvas is handed to :meth:`ViewportHost.set_canvas` this panel
gets out of its way and simply hosts it.  When there is no renderer -- before a
world is opened, on a machine whose OpenGL context failed, or in a screenshot
harness -- it paints the design's stand-in instead, and says plainly that it is
a stand-in.  A drawn sky that quietly pretends to be a world is the one thing a
placeholder must never do.

Everything on the display is a real control rather than paint: the chips are
named readouts a screen reader can announce, the minimap and compass follow the
camera, the corner handles move the selection with the arrow keys, and the four
tool buttons act.  They are laid out by hand rather than by a sizer because the
design positions them against the four corners of the view.

While a renderer is hosted the four readouts are re-read from that renderer on
a timer -- the world's own platform and version, the dimension it is showing
with that dimension's real build range, the camera's actual position, and the
frames it genuinely drew alongside the chunks it genuinely has in memory.  A
value the renderer cannot answer is left saying so rather than keeping the last
number it happened to have, because a stale reading and a live one look
identical on screen.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

import wx

from amulet_map_editor.api import config
from amulet_map_editor.api.studio import tokens
from amulet_map_editor.api.studio.copy import studio_text
from amulet_map_editor.api.studio.status_bar import open_studio_menu
from amulet_map_editor.api.studio.widgets import (
    AXIS_COLOURS,
    TEXT_SLACK,
    StudioButton,
    colour_of,
    draw_focus_ring,
    elide,
    invoke,
    measuring,
    paint_context,
    point_size,
    translated,
)

log = logging.getLogger(__name__)

#: The design's sky-to-ground gradient, as ``(stop, colour)`` pairs.
SKY_STOPS: Tuple[Tuple[float, str], ...] = (
    (0.00, "#8FAAC4"),
    (0.48, "#89A7C1"),
    (0.54, "#6B8A63"),
    (1.00, "#4A6647"),
)

#: The world grid the design draws over the sky, in design pixels.
GRID_PITCH = 48

#: The selection wireframe the design centres in the view, in design pixels.
WIREFRAME_WIDTH = 280
WIREFRAME_HEIGHT = 120

#: The two selection corner inks, transcribed from the design.
MINIMUM_HANDLE_COLOUR = "#5BD68A"
MAXIMUM_HANDLE_COLOUR = "#6FA8FF"

#: The accent the design uses for every line drawn over the world.
OVERLAY_ACCENT = "#A6F2E9"

#: Where the stand-in view puts its drawn camera.  These are parameters of the
#: drawing, not a reading of anything: while they are in use the view says in
#: its own accessible name and in its notice that no renderer is attached.
DEFAULT_CAMERA: Tuple[float, float, float] = (66.40, 118.13, -43.12)
DEFAULT_YAW = 32.0

#: How often the heads-up display re-reads the hosted renderer, in
#: milliseconds.  Half a second is slow enough to cost nothing and fast enough
#: that a camera readout follows the camera rather than trailing it.
LIVE_POLL_MS = 500

#: What a readout says when there is no renderer to read it from.  Each one is
#: short because it shares a row with three others; the chip's tooltip and
#: accessible name carry the full sentence.
NO_WORLD_CHIP = "no world open"
NO_DIMENSION_CHIP = "no dimension"
NO_CAMERA_CHIP = "no camera"
NO_RENDER_CHIP = "not rendering"

#: What each readout's tooltip says instead of a number.
NO_RENDERER_REASON = (
    "No renderer is attached, so there is nothing to read this from. "
    "Open a world and the reading becomes live."
)

#: The vertical tool column, bottom right.
VIEWPORT_TOOLS: Tuple[Tuple[str, str, str, str], ...] = (
    (
        "frame",
        "▣",
        "Frame selection",
        "Move the camera to the middle of the selection",
    ),
    ("top", "▦", "Top view", "Look straight down at the selection"),
    ("slice", "▬", "Toggle slice", "Show or hide the layer slice band"),
    (
        "reset",
        "⟲",
        "Reset camera",
        "Return the camera to its starting position and heading",
    ),
)

#: Below these widths the display would start overlapping itself, so the
#: elements that need the most room are hidden rather than clipped.
_MINIMAP_MIN_WIDTH = 460
_TOOLS_MIN_HEIGHT = 260


@dataclass(frozen=True)
class OverlayGroup:
    """One movable cluster of heads-up controls, and where it starts life.

    ``anchor_x`` and ``anchor_y`` name the corner a group's remembered position
    is measured from.  That is not decoration: a group anchored bottom-right and
    remembered as "sixteen pixels in from the bottom-right" is still sixteen
    pixels in from the bottom-right after the window is resized, whereas the
    same position stored as an absolute point would be off the edge of a smaller
    window and half way up a larger one.
    """

    key: str
    label: str
    anchor_x: str
    anchor_y: str
    pad: int
    vertical: bool
    gap: int


#: The four groups a user can move, and where the design puts each of them.
#:
#: They are moved as **groups rather than as individual controls**, for two
#: reasons that both come from what these particular widgets are.  The readouts
#: are a row whose members change width twice a second as the numbers behind
#: them change, so four independently positioned chips would drift into each
#: other the moment a camera moved; and the tool column and the minimap stack
#: are single design objects whose members are meaningless apart -- a compass
#: parked away from the map it belongs to is clutter, not customisation.
#: Grouping also gives each grab handle a body big enough to actually grab.
#:
#: The selection corner handles are deliberately absent.  They are not chrome
#: floating over the world: each one marks a block coordinate, so moving one
#: somewhere more convenient would be a lie about where the selection is.
OVERLAY_GROUPS: Tuple[OverlayGroup, ...] = (
    OverlayGroup("readouts", "Readouts", "left", "top", 14, False, 6),
    OverlayGroup("minimap", "Minimap and compass", "right", "top", 14, True, 8),
    OverlayGroup("axes", "Axis key", "left", "bottom", 16, True, 6),
    OverlayGroup("tools", "View tools", "right", "bottom", 16, True, 6),
)

OVERLAY_BY_KEY: Dict[str, OverlayGroup] = {group.key: group for group in OVERLAY_GROUPS}

#: Where remembered overlay positions live, keyed ``<surface>.<group>``.
OVERLAY_LAYOUT_ID = "amulet_studio_overlay_layout"

#: Which viewport a remembered position belongs to.  There is one world view
#: today; the key carries the surface anyway so a second one cannot silently
#: inherit the first one's layout.
OVERLAY_SURFACE = "viewport"

#: How far one arrow key press moves an overlay, and how far it moves while
#: Shift is held, in design pixels.  These are the numbers the grip states in
#: its own name and tooltip, scaled for the live display: a control that says
#: "eight pixels" and moves by six is worse than one that says nothing.
OVERLAY_STEP = 8
OVERLAY_LARGE_STEP = 32

#: The grab handle: how thick the gutter is, how far it sits from the controls
#: it moves, and the shortest it is ever drawn, in design pixels.
GRIP_THICKNESS = 10
GRIP_GAP = 4
GRIP_MIN_LENGTH = 28


def load_overlay_offsets(surface: str = OVERLAY_SURFACE) -> Dict[str, Tuple[int, int]]:
    """Return every remembered overlay position for one surface.

    A position is stored as the distance from the two edges its group is
    anchored to, never as an absolute point, so a window that changes size
    keeps a corner-anchored overlay in its corner.
    """
    raw = config.get(OVERLAY_LAYOUT_ID, {})
    if not isinstance(raw, dict):
        return {}
    prefix = f"{surface}."
    offsets: Dict[str, Tuple[int, int]] = {}
    for key, value in raw.items():
        name = str(key)
        if not name.startswith(prefix):
            continue
        try:
            gap_x, gap_y = value
            offsets[name[len(prefix) :]] = (int(gap_x), int(gap_y))
        except (TypeError, ValueError):
            continue
    return offsets


def store_overlay_offset(surface: str, key: str, offset: Tuple[int, int]) -> None:
    """Remember one overlay's position, ignoring a profile that cannot be written."""
    try:
        raw = config.get(OVERLAY_LAYOUT_ID, {})
        stored = dict(raw) if isinstance(raw, dict) else {}
        stored[f"{surface}.{key}"] = (int(offset[0]), int(offset[1]))
        config.put(OVERLAY_LAYOUT_ID, stored)
    except OSError:
        log.exception("Could not store the %s overlay position", key)


def clear_overlay_offsets(surface: str, key: Optional[str] = None) -> None:
    """Forget one remembered overlay position, or every one on a surface."""
    try:
        raw = config.get(OVERLAY_LAYOUT_ID, {})
        stored = dict(raw) if isinstance(raw, dict) else {}
        if key is None:
            prefix = f"{surface}."
            stored = {
                name: value
                for name, value in stored.items()
                if not str(name).startswith(prefix)
            }
        else:
            stored.pop(f"{surface}.{key}", None)
        config.put(OVERLAY_LAYOUT_ID, stored)
    except OSError:
        log.exception("Could not reset the overlay positions for %r", surface)


def overlay_step(large: bool = False) -> int:
    """Return how far one arrow key press moves an overlay, in real pixels."""
    return tokens.scaled(OVERLAY_LARGE_STEP if large else OVERLAY_STEP)


def overlay_hint_text() -> str:
    """Return the sentence the view shows while an overlay grip has attention.

    The numbers are read rather than written out, because they are scaled for
    the display and a sentence quoting the design's own eight would be wrong on
    every screen that is not at one hundred percent.
    """
    step = overlay_step(False)
    large = overlay_step(True)
    return studio_text(
        f"Drag, or press the arrow keys to move this overlay {step} pixels, "
        f"Shift for {large}. Home puts it back; Shift+Home puts every "
        "overlay back.",
        f"拖佢，或者撳方向鍵郁 {step} 像素，撳住 Shift 就 {large}。"
        "Home 還原呢個，Shift+Home 全部還原。",
    )


def sky_colour(fraction: float) -> wx.Colour:
    """Return the gradient colour at ``fraction`` down the view.

    The heads-up controls are separate child windows, so each one has to clear
    itself with the colour of the sky behind it before compositing its own
    translucent surface; without that they would each paint a visible square of
    the wrong blue.
    """
    position = min(1.0, max(0.0, float(fraction)))
    previous_stop, previous_colour = SKY_STOPS[0]
    for stop, colour in SKY_STOPS:
        if position <= stop:
            if stop <= previous_stop:
                return colour_of(colour)
            ratio = (position - previous_stop) / (stop - previous_stop)
            return tokens.blend(colour_of(previous_colour), colour_of(colour), ratio)
        previous_stop, previous_colour = stop, colour
    return colour_of(SKY_STOPS[-1][1])


def hud_backdrop(window: wx.Window) -> wx.Colour:
    """Return the opaque colour sitting behind a heads-up control."""
    parent = window.GetParent()
    getter = getattr(parent, "background_colour_at", None)
    if callable(getter):
        try:
            return getter(window.GetRect())
        except Exception:  # pragma: no cover - the host is tearing down
            log.debug("Could not sample the viewport background")
    if parent is not None:
        colour = parent.GetBackgroundColour()
        if colour.IsOk():
            return colour
    return sky_colour(0.5)


def hud_paint_context(window: wx.Window) -> Tuple[wx.DC, wx.DC]:
    """Clear a heads-up control against the sky and return its contexts.

    This defers to :func:`widgets.paint_context` rather than building its own
    device context, because the device context type is not a free choice:
    ``wx.GCDC`` rejects a ``wx.AutoBufferedPaintDC`` on wxPython 4.3.1 and the
    resulting ``TypeError`` fires inside ``EVT_PAINT``, leaving the control
    unpainted.  One helper means one place that has to be right.
    """
    return paint_context(window, hud_backdrop(window))


def clear_hud(window: wx.Window, dc: wx.DC, width: int, height: int) -> None:
    """Fill a heads-up control's own rectangle with the sky sitting behind it.

    :func:`hud_paint_context` does this on the way into a paint handler.  A
    capture never goes through a paint handler -- it calls ``render_to``
    directly -- so the same clearing has to be available there, or a widget
    draws its translucent surface over whatever the capture bitmap already
    held.
    """
    dc.SetBrush(wx.Brush(hud_backdrop(window)))
    dc.SetPen(wx.TRANSPARENT_PEN)
    dc.DrawRectangle(0, 0, max(1, width), max(1, height))


class HudChip(wx.Control):
    """One monospaced readout floating over the world.

    It carries an accessible name and a tooltip because it is the only place
    some of these facts appear: a camera position nobody can read is not a
    heads-up display, it is decoration.
    """

    PADDING_X = 10
    PADDING_Y = 6

    def __init__(
        self,
        parent: wx.Window,
        text: str,
        *,
        name: str,
        size_px: int = 11,
        radius: int = tokens.RADIUS_SM,
    ) -> None:
        super().__init__(parent, style=wx.BORDER_NONE)
        self._lines: List[str] = []
        self._detail = ""
        self._size_px = int(size_px)
        self._radius = int(radius)
        self._label = str(name)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.set_text(text)

    def AcceptsFocus(self) -> bool:  # noqa: N802 - wx API spelling
        return False

    def AcceptsFocusFromKeyboard(self) -> bool:  # noqa: N802 - wx API spelling
        return False

    def text(self) -> str:
        """Return the chip's current text, newlines included."""
        return "\n".join(self._lines)

    def set_text(self, text: str, detail: str = "") -> None:
        """Replace the chip's text and re-measure it.

        ``detail`` is the longer sentence behind a short reading -- where the
        number was read from, or why there is no number.  It goes in the
        tooltip and the accessible name, because a chip has room for four words
        and the reason a reading is missing is usually longer than that.

        Setting the same text twice does nothing at all.  These chips are
        re-read twice a second over an OpenGL canvas, and repainting four of
        them on every read whether or not anything changed is visible as a
        flicker across the world.
        """
        lines = [line for line in str(text).splitlines() if line.strip()] or [""]
        if lines == self._lines and str(detail) == self._detail:
            return
        self._lines = lines
        self._detail = str(detail)
        summary = " · ".join(self._lines)
        self.SetName(
            f"{self._label}: {summary}" + (f". {self._detail}" if self._detail else "")
        )
        self.SetToolTip(
            f"{self.text()}\n{self._detail}" if self._detail else self.text()
        )
        self.InvalidateBestSize()
        self.SetSize(self.DoGetBestSize())
        self.Refresh()

    def detail(self) -> str:
        """Return the sentence explaining this reading, or ``""``."""
        return self._detail

    def _font(self) -> wx.Font:
        return tokens.mono_font(self, point_size(self._size_px))

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        """Measure the way the chip paints, or its own text comes out elided.

        A ``wx.ClientDC`` measures through GDI and the chip paints through a
        ``wx.GCDC``, and the two disagree by a pixel or two -- so a chip sized
        from the narrower reading is always a hair short of the text it then
        draws, and :func:`elide` fires on a line that was meant to fit exactly.
        That is not theoretical here: the stand-in's own notice shipped reading
        "a drawn stand-in for the w…" with nothing cutting it off but this.
        """
        with measuring(self) as dc:
            dc.SetFont(self._font())
            width = max(dc.GetTextExtent(line or " ")[0] for line in self._lines)
            height = dc.GetCharHeight() * len(self._lines)
        return wx.Size(
            width + TEXT_SLACK * 2 + tokens.scaled(self.PADDING_X) * 2,
            height + tokens.scaled(self.PADDING_Y) * 2,
        )

    def refresh_theme(self) -> None:
        """Re-measure for the live density and repaint."""
        self.InvalidateBestSize()
        self.SetSize(self.DoGetBestSize())
        self.Refresh()

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        dc, gcdc = hud_paint_context(self)
        width, height = self.GetClientSize()
        rect = wx.Rect(0, 0, width, height)
        radius = tokens.scaled(self._radius)
        tokens.draw_elevation(gcdc, rect, radius, 1, True)
        tokens.draw_round_rect(gcdc, rect, radius, palette.scrim)
        gcdc.SetFont(self._font())
        gcdc.SetTextForeground(wx.Colour(255, 255, 255))
        line_height = gcdc.GetCharHeight()
        top = (height - line_height * len(self._lines)) // 2
        available = max(0, width - tokens.scaled(self.PADDING_X) * 2)
        for line in self._lines:
            gcdc.DrawText(
                elide(gcdc, line, available), tokens.scaled(self.PADDING_X), top
            )
            top += line_height
        del gcdc


class AxesLegend(wx.Control):
    """The axis key in the bottom-left corner, one coloured line per axis."""

    ROWS: Tuple[Tuple[str, str], ...] = (
        ("", "AXES"),
        ("x", "x  east +"),
        ("y", "y  up +"),
        ("z", "z  south +"),
    )
    PADDING_X = 12
    PADDING_Y = 10
    GAP = 4

    def __init__(self, parent: wx.Window) -> None:
        super().__init__(parent, style=wx.BORDER_NONE)
        self.SetName("Axes: x is east positive, y is up positive, z is south positive")
        self.SetToolTip("x east +\ny up +\nz south +")
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.SetSize(self.DoGetBestSize())

    def AcceptsFocus(self) -> bool:  # noqa: N802 - wx API spelling
        return False

    def AcceptsFocusFromKeyboard(self) -> bool:  # noqa: N802 - wx API spelling
        return False

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        with measuring(self) as dc:
            dc.SetFont(tokens.mono_font(self, point_size(10)))
            width = max(dc.GetTextExtent(label)[0] for _axis, label in self.ROWS)
            line_height = dc.GetCharHeight()
        return wx.Size(
            width + TEXT_SLACK * 2 + tokens.scaled(self.PADDING_X) * 2,
            line_height * len(self.ROWS)
            + tokens.scaled(self.GAP) * (len(self.ROWS) - 1)
            + tokens.scaled(self.PADDING_Y) * 2,
        )

    def refresh_theme(self) -> None:
        """Re-measure for the live density and repaint."""
        self.InvalidateBestSize()
        self.SetSize(self.DoGetBestSize())
        self.Refresh()

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        dc, gcdc = hud_paint_context(self)
        width, height = self.GetClientSize()
        rect = wx.Rect(0, 0, width, height)
        radius = tokens.scaled(tokens.RADIUS_SM + 2)
        tokens.draw_elevation(gcdc, rect, radius, 2, True)
        tokens.draw_round_rect(gcdc, rect, radius, palette.scrim)
        gcdc.SetFont(tokens.mono_font(self, point_size(10)))
        top = tokens.scaled(self.PADDING_Y)
        line_height = gcdc.GetCharHeight()
        for axis, label in self.ROWS:
            gcdc.SetTextForeground(
                colour_of(AXIS_COLOURS[axis]) if axis else wx.Colour(255, 255, 255)
            )
            gcdc.DrawText(label, tokens.scaled(self.PADDING_X), top)
            top += line_height + tokens.scaled(self.GAP)
        del gcdc


class MinimapView(StudioButton):
    """The camera-and-selection map in the top-right corner.

    The map scales itself so the camera and the whole selection are both on it.
    A fixed scale would be simpler and would regularly draw an empty square,
    because the camera is often further from the selection than a 110 pixel
    card can show.
    """

    SIZE = 110
    GRID = 16

    def __init__(
        self,
        parent: wx.Window,
        *,
        on_click: Optional[Callable[[], None]] = None,
    ) -> None:
        self.camera: Tuple[float, float, float] = DEFAULT_CAMERA
        self.dimension = "overworld"
        self.minimum: Tuple[int, int, int] = (-2, 98, -49)
        self.maximum: Tuple[int, int, int] = (13, 99, -32)
        super().__init__(
            parent,
            "",
            variant="icon",
            on_click=on_click,
            hint="Open Go to location",
            height=self.SIZE,
            min_width=self.SIZE,
        )
        self._sync_name()

    def _sync_name(self) -> None:
        x, _y, z = self.camera
        self.SetName(
            f"Minimap of {self.dimension}. Camera at x {x:.2f}, z {z:.2f}. "
            "Opens Go to location."
        )

    def set_view(
        self,
        *,
        camera: Optional[Tuple[float, float, float]] = None,
        dimension: Optional[str] = None,
        minimum: Optional[Tuple[int, int, int]] = None,
        maximum: Optional[Tuple[int, int, int]] = None,
    ) -> None:
        """Update anything the map draws and repaint once."""
        if camera is not None:
            self.camera = tuple(float(value) for value in camera)
        if dimension is not None:
            self.dimension = str(dimension).split(":")[-1]
        if minimum is not None:
            self.minimum = tuple(int(value) for value in minimum)
        if maximum is not None:
            self.maximum = tuple(int(value) for value in maximum)
        self._sync_name()
        self.Refresh()

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        side = tokens.scaled(self.SIZE)
        return wx.Size(side, side)

    def _scale(self, half: float) -> float:
        """Return pixels per block that fit the camera and selection on the card."""
        centre_x = (self.minimum[0] + self.maximum[0] + 1) / 2
        centre_z = (self.minimum[2] + self.maximum[2] + 1) / 2
        half_x = (self.maximum[0] - self.minimum[0] + 1) / 2
        half_z = (self.maximum[2] - self.minimum[2] + 1) / 2
        mid_x = (centre_x + self.camera[0]) / 2
        mid_z = (centre_z + self.camera[2]) / 2
        span = max(
            abs(self.camera[0] - mid_x),
            abs(self.camera[2] - mid_z),
            abs(centre_x - mid_x) + half_x,
            abs(centre_z - mid_z) + half_z,
            1.0,
        )
        return max(0.05, (half - 8.0) / span)

    def render_to(self, dc: wx.DC, rect: wx.Rect) -> None:
        """Draw the map, in the one place both the screen and a capture use.

        Without this the base :class:`StudioButton` one applies, and that draws
        a *button*: a capture of the viewport came back with an empty rounded
        rectangle where the map should be, and reported it as having drawn.
        """
        with translated(dc, rect):
            clear_hud(self, dc, rect.width, rect.height)
            self._draw(dc, rect.width, rect.height)

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        dc, gcdc = hud_paint_context(self)
        width, height = self.GetClientSize()
        self._draw(gcdc, width, height)
        del gcdc

    def _draw(self, gcdc: wx.DC, width: int, height: int) -> None:
        palette = self.palette()
        rect = wx.Rect(0, 0, width, height)
        radius = tokens.scaled(tokens.RADIUS_MD)
        tokens.draw_elevation(gcdc, rect, radius, 2, True)
        tokens.draw_round_rect(
            gcdc, rect, radius, palette.scrim, wx.Colour(255, 255, 255, 64)
        )
        gcdc.SetPen(wx.Pen(wx.Colour(255, 255, 255, 31)))
        pitch = tokens.scaled(self.GRID)
        for x in range(pitch, width, pitch):
            gcdc.DrawLine(x, 1, x, height - 1)
        for y in range(pitch, height, pitch):
            gcdc.DrawLine(1, y, width - 1, y)

        centre_x = (self.minimum[0] + self.maximum[0] + 1) / 2
        centre_z = (self.minimum[2] + self.maximum[2] + 1) / 2
        mid_x = (centre_x + self.camera[0]) / 2
        mid_z = (centre_z + self.camera[2]) / 2
        half = min(width, height) / 2
        scale = self._scale(half)

        def to_pixel(x: float, z: float) -> Tuple[int, int]:
            return (
                int(round(width / 2 + (x - mid_x) * scale)),
                int(round(height / 2 + (z - mid_z) * scale)),
            )

        left, top = to_pixel(self.minimum[0], self.minimum[2])
        right, bottom = to_pixel(self.maximum[0] + 1, self.maximum[2] + 1)
        selection = wx.Rect(left, top, max(2, right - left), max(2, bottom - top))
        accent = colour_of(OVERLAY_ACCENT)
        gcdc.SetBrush(
            wx.Brush(wx.Colour(accent.Red(), accent.Green(), accent.Blue(), 71))
        )
        gcdc.SetPen(wx.Pen(accent))
        gcdc.DrawRectangle(selection)
        marker_x, marker_y = to_pixel(self.camera[0], self.camera[2])
        dot = tokens.scaled(6)
        gcdc.SetBrush(wx.Brush(wx.Colour(255, 255, 255)))
        gcdc.SetPen(wx.TRANSPARENT_PEN)
        gcdc.DrawEllipse(marker_x - dot // 2, marker_y - dot // 2, dot, dot)
        gcdc.SetFont(tokens.mono_font(self, point_size(9)))
        gcdc.SetTextForeground(wx.Colour(255, 255, 255))
        label = f"MINIMAP · {self.dimension}"
        gcdc.DrawText(
            elide(gcdc, label, width - tokens.scaled(16)),
            tokens.scaled(8),
            height - tokens.scaled(5) - gcdc.GetCharHeight(),
        )
        if self.HasFocus() or self._hovered:
            draw_focus_ring(gcdc, rect, radius, accent)


class CompassView(StudioButton):
    """The heading dial, whose needle follows the camera's yaw."""

    SIZE = 64
    NEEDLE = 22

    def __init__(
        self,
        parent: wx.Window,
        *,
        on_click: Optional[Callable[[], None]] = None,
    ) -> None:
        self.yaw = DEFAULT_YAW
        super().__init__(
            parent,
            "",
            variant="icon",
            on_click=on_click,
            hint="Face the camera north",
            height=self.SIZE,
            min_width=self.SIZE,
        )
        self._sync_name()

    def _sync_name(self) -> None:
        self.SetName(
            f"Compass, heading {self.yaw:.0f} degrees. Faces the camera north."
        )

    def set_yaw(self, yaw: float) -> None:
        """Point the needle at a new heading, in degrees clockwise from north."""
        self.yaw = float(yaw) % 360.0
        self._sync_name()
        self.Refresh()

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        side = tokens.scaled(self.SIZE)
        return wx.Size(side, side)

    def render_to(self, dc: wx.DC, rect: wx.Rect) -> None:
        """Draw the dial itself, rather than the button underneath it."""
        with translated(dc, rect):
            clear_hud(self, dc, rect.width, rect.height)
            self._draw(dc, rect.width, rect.height)

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        dc, gcdc = hud_paint_context(self)
        width, height = self.GetClientSize()
        self._draw(gcdc, width, height)
        del gcdc

    def _draw(self, gcdc: wx.DC, width: int, height: int) -> None:
        palette = self.palette()
        rect = wx.Rect(0, 0, width, height)
        tokens.draw_elevation(gcdc, rect, width // 2, 2, True)
        gcdc.SetBrush(wx.Brush(palette.scrim))
        gcdc.SetPen(wx.Pen(wx.Colour(255, 255, 255, 64)))
        gcdc.DrawEllipse(0, 0, width - 1, height - 1)
        accent = colour_of(OVERLAY_ACCENT)
        gcdc.SetFont(tokens.mono_font(self, point_size(9)))
        dim = wx.Colour(255, 255, 255, 153)
        inset = tokens.scaled(5)
        edge = tokens.scaled(6)
        for text, ink, anchor in (
            ("N", wx.Colour(255, 255, 255), "north"),
            ("S", dim, "south"),
            ("W", dim, "west"),
            ("E", accent, "east"),
        ):
            gcdc.SetTextForeground(ink)
            text_width, text_height = gcdc.GetTextExtent(text)
            if anchor == "north":
                origin = ((width - text_width) // 2, inset)
            elif anchor == "south":
                origin = ((width - text_width) // 2, height - inset - text_height)
            elif anchor == "west":
                origin = (edge, (height - text_height) // 2)
            else:
                origin = (width - edge - text_width, (height - text_height) // 2)
            gcdc.DrawText(text, int(origin[0]), int(origin[1]))
        angle = math.radians(self.yaw)
        length = tokens.scaled(self.NEEDLE)
        centre = wx.Point(width // 2, height // 2)
        tip = wx.Point(
            int(centre.x + math.sin(angle) * length),
            int(centre.y - math.cos(angle) * length),
        )
        gcdc.SetPen(wx.Pen(accent, max(2, tokens.scaled(2))))
        gcdc.DrawLine(centre.x, centre.y, tip.x, tip.y)
        if self.HasFocus() or self._hovered:
            gcdc.SetBrush(wx.TRANSPARENT_BRUSH)
            gcdc.SetPen(wx.Pen(accent, 2))
            gcdc.DrawEllipse(2, 2, width - 5, height - 5)


class ViewportToolButton(StudioButton):
    """One of the square tool buttons stacked in the bottom-right corner."""

    SIZE = 34

    def __init__(
        self,
        parent: wx.Window,
        key: str,
        glyph: str,
        label: str,
        hint: str,
        *,
        on_click: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.key = str(key)
        self.active = False
        self._on_tool = on_click
        super().__init__(
            parent,
            "",
            variant="icon",
            glyph=glyph,
            hint=hint,
            on_click=self._run,
            height=self.SIZE,
            min_width=self.SIZE,
            name=label,
        )
        self.label_text = str(label)
        self._sync_name()

    def _run(self) -> None:
        invoke(self._on_tool, self.key)

    def _sync_name(self) -> None:
        suffix = ", on" if self.active else ""
        self.SetName(f"{self.label_text}{suffix}")

    def set_active(self, active: bool) -> None:
        """Show the button as latched on, for the tools that toggle."""
        self.active = bool(active)
        self._sync_name()
        self.Refresh()

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        side = tokens.scaled(self.SIZE)
        return wx.Size(side, side)

    def render_to(self, dc: wx.DC, rect: wx.Rect) -> None:
        """Draw the tool's own scrim and glyph, not a plain Studio button."""
        with translated(dc, rect):
            clear_hud(self, dc, rect.width, rect.height)
            self._draw(dc, rect.width, rect.height)

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        dc, gcdc = hud_paint_context(self)
        width, height = self.GetClientSize()
        self._draw(gcdc, width, height)
        del gcdc

    def _draw(self, gcdc: wx.DC, width: int, height: int) -> None:
        palette = self.palette()
        rect = wx.Rect(0, 0, width, height)
        radius = tokens.scaled(tokens.RADIUS_SM + 1)
        accent = colour_of(OVERLAY_ACCENT)
        highlighted = self.active or self._hovered or self._pressed or self.HasFocus()
        fill = palette.scrim
        if self.active:
            fill = wx.Colour(accent.Red(), accent.Green(), accent.Blue(), 92)
        tokens.draw_elevation(gcdc, rect, radius, 1, True)
        tokens.draw_round_rect(
            gcdc,
            rect,
            radius,
            fill,
            accent if highlighted else wx.Colour(255, 255, 255, 56),
        )
        gcdc.SetFont(tokens.font(self, point_size(14)))
        gcdc.SetTextForeground(accent if highlighted else wx.Colour(255, 255, 255))
        glyph_width, glyph_height = gcdc.GetTextExtent(self.glyph)
        gcdc.DrawText(
            self.glyph, (width - glyph_width) // 2, (height - glyph_height) // 2
        )
        if self.HasFocus():
            draw_focus_ring(gcdc, rect, radius, accent)


class CornerHandle(StudioButton):
    """One corner of the selection, movable a block at a time from the keyboard.

    The stand-in view is not a projection of the world, so dragging a handle
    with the mouse could not be turned into honest block coordinates.  The
    arrow keys can: each press moves the corner by exactly the number of blocks
    it says it does, and the workspace is told the new bounds.
    """

    SIZE = 14

    def __init__(
        self,
        parent: wx.Window,
        role: str,
        colour: str,
        *,
        on_nudge: Optional[Callable[[str, Tuple[int, int, int]], None]] = None,
        on_click: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.role = str(role)
        self.colour = str(colour)
        self.corner: Tuple[int, int, int] = (0, 0, 0)
        self._on_nudge = on_nudge
        self._on_pick = on_click
        super().__init__(
            parent,
            "",
            variant="icon",
            on_click=self._pick,
            height=self.SIZE,
            min_width=self.SIZE,
            hint=(
                "Arrow keys move this corner east, west, north, and south; "
                "Page Up and Page Down move it up and down. Hold Shift for eight "
                "blocks."
            ),
        )
        self.Bind(wx.EVT_KEY_DOWN, self._on_arrow)
        self._sync_name()

    def _pick(self) -> None:
        invoke(self._on_pick, self.role)

    def _sync_name(self) -> None:
        x, y, z = self.corner
        self.SetName(f"Selection {self.role} corner at {x}, {y}, {z}")

    def set_corner(self, corner: Tuple[int, int, int]) -> None:
        """Show a new corner position and announce it."""
        self.corner = tuple(int(value) for value in corner)
        self._sync_name()
        self.Refresh()

    def _on_arrow(self, event: wx.KeyEvent) -> None:
        step = 8 if event.ShiftDown() else 1
        moves: Dict[int, Tuple[int, int, int]] = {
            wx.WXK_LEFT: (-step, 0, 0),
            wx.WXK_RIGHT: (step, 0, 0),
            wx.WXK_UP: (0, 0, -step),
            wx.WXK_DOWN: (0, 0, step),
            wx.WXK_PAGEUP: (0, step, 0),
            wx.WXK_PAGEDOWN: (0, -step, 0),
        }
        delta = moves.get(event.GetKeyCode())
        if delta is None:
            event.Skip()
            return
        invoke(self._on_nudge, self.role, delta)

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        side = tokens.scaled(self.SIZE)
        return wx.Size(side, side)

    def render_to(self, dc: wx.DC, rect: wx.Rect) -> None:
        """Draw the coloured knob, not the square button behind it."""
        with translated(dc, rect):
            clear_hud(self, dc, rect.width, rect.height)
            self._draw(dc, rect.width, rect.height)

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        dc, gcdc = hud_paint_context(self)
        width, height = self.GetClientSize()
        self._draw(gcdc, width, height)
        del gcdc

    def _draw(self, gcdc: wx.DC, width: int, height: int) -> None:
        side = min(width, height)
        ink = colour_of(self.colour)
        if self._pressed or self._hovered:
            ink = tokens.blend(ink, wx.Colour(255, 255, 255), 0.25)
        gcdc.SetPen(wx.Pen(wx.Colour(0, 0, 0, 89), 2))
        gcdc.SetBrush(wx.Brush(ink))
        gcdc.DrawEllipse(1, 1, side - 3, side - 3)
        if self.HasFocus():
            gcdc.SetBrush(wx.TRANSPARENT_BRUSH)
            gcdc.SetPen(wx.Pen(colour_of(OVERLAY_ACCENT), 2))
            gcdc.DrawEllipse(0, 0, side - 1, side - 1)


class OverlayGrip(wx.Control):
    """The gutter you grab to move one overlay group, and its keyboard.

    It is a **separate window from the controls it moves**, and that is the
    whole design rather than an implementation detail.  The minimap opens Go to
    when it is clicked and each tool button runs its tool; making those same
    surfaces double as drag targets would mean guessing, on every press,
    whether the user meant the action or the move.  A grip has one job, so
    there is nothing to guess -- and because it is a child window of the
    viewport, a press on it is delivered to it and never reaches the renderer
    canvas underneath, which is what keeps a drag from also turning the camera.

    It is drawn faintly at rest rather than hidden until hovered.  A handle
    that only exists once the pointer is already over it is a handle nobody
    finds, and worse, a hidden window is skipped by tab traversal, so the
    keyboard route would have been unreachable too.
    """

    #: The three dots the gutter is drawn with, as a fraction of its length.
    DOTS = (0.36, 0.5, 0.64)

    def __init__(
        self,
        parent: wx.Window,
        key: str,
        label: str,
        *,
        on_place: Optional[Callable[[str, int, int], None]] = None,
        on_move: Optional[Callable[[str, int, int], None]] = None,
        on_commit: Optional[Callable[[str], None]] = None,
        on_reset: Optional[Callable[[str, bool], None]] = None,
        on_attention: Optional[Callable[[str, bool], None]] = None,
    ) -> None:
        super().__init__(parent, style=wx.BORDER_NONE | wx.WANTS_CHARS)
        self.key = str(key)
        self.label_text = str(label)
        self._on_place = on_place
        self._on_move = on_move
        self._on_commit = on_commit
        self._on_reset = on_reset
        self._on_attention = on_attention
        self._hovered = False
        self._dragging = False
        self._grab: Optional[wx.Point] = None
        self._nudged = False
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetCursor(wx.Cursor(wx.CURSOR_SIZING))
        self._sync_name()
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.Bind(wx.EVT_ENTER_WINDOW, self._on_enter)
        self.Bind(wx.EVT_LEAVE_WINDOW, self._on_leave)
        self.Bind(wx.EVT_LEFT_DOWN, self._on_left_down)
        self.Bind(wx.EVT_MOTION, self._on_motion)
        self.Bind(wx.EVT_LEFT_UP, self._on_left_up)
        self.Bind(wx.EVT_MOUSE_CAPTURE_LOST, self._on_capture_lost)
        self.Bind(wx.EVT_KEY_DOWN, self._on_key_down)
        self.Bind(wx.EVT_KEY_UP, self._on_key_up)
        self.Bind(wx.EVT_SET_FOCUS, self._on_focus)
        self.Bind(wx.EVT_KILL_FOCUS, self._on_blur)
        self.SetInitialSize(self.DoGetBestSize())

    # -- accessibility -------------------------------------------------------
    def AcceptsFocus(self) -> bool:  # noqa: N802 - wx API spelling
        return True

    def AcceptsFocusFromKeyboard(self) -> bool:  # noqa: N802 - wx API spelling
        return True

    def _sync_name(self) -> None:
        """State what this handle does, and exactly how far its keys move it."""
        step = overlay_step(False)
        large = overlay_step(True)
        sentence = (
            f"Move the {self.label_text.lower()} overlay. Drag it, or press the "
            f"arrow keys to move it {step} pixels, Shift and an arrow for "
            f"{large}. Home returns it to its shipped place, and Shift and Home "
            "returns every overlay."
        )
        self.SetName(sentence)
        self.SetToolTip(sentence)

    def refresh_theme(self) -> None:
        """Re-read the step for the live density and repaint."""
        self._sync_name()
        self.Refresh()

    # -- pointer -------------------------------------------------------------
    def _on_enter(self, event: wx.MouseEvent) -> None:
        self._hovered = True
        invoke(self._on_attention, self.key, True)
        self.Refresh()
        event.Skip()

    def _on_leave(self, event: wx.MouseEvent) -> None:
        self._hovered = False
        if not self._dragging and not self.HasFocus():
            invoke(self._on_attention, self.key, False)
        self.Refresh()
        event.Skip()

    def _on_left_down(self, event: wx.MouseEvent) -> None:
        self.SetFocus()
        self._grab = wx.Point(event.GetPosition())
        self._dragging = True
        if not self.HasCapture():
            try:
                self.CaptureMouse()
            except Exception:  # pragma: no cover - platform boundary
                log.debug("Could not capture the pointer for the %s grip", self.key)
        invoke(self._on_attention, self.key, True)
        self.Refresh()

    def _on_motion(self, event: wx.MouseEvent) -> None:
        """Follow the pointer, in the parent's coordinates.

        The position on the event is inside this window, and this window moves
        as the drag proceeds, so the two are added: where the pointer is on the
        viewport is where the grip sits plus where the pointer is on the grip.
        Subtracting the point the drag started from keeps the handle under the
        same part of the pointer it was picked up by, rather than snapping its
        corner to the cursor on the first pixel of movement.
        """
        if not self._dragging or self._grab is None:
            event.Skip()
            return
        origin = self.GetPosition()
        here = event.GetPosition()
        invoke(
            self._on_place,
            self.key,
            origin.x + here.x - self._grab.x,
            origin.y + here.y - self._grab.y,
        )

    def _on_left_up(self, event: wx.MouseEvent) -> None:
        was_dragging = self._dragging
        self._release()
        if was_dragging:
            invoke(self._on_commit, self.key)
        self.Refresh()
        event.Skip()

    def _on_capture_lost(self, _event: wx.MouseCaptureLostEvent) -> None:
        """Another window took the pointer; keep the move already made."""
        was_dragging = self._dragging
        self._dragging = False
        self._grab = None
        if was_dragging:
            invoke(self._on_commit, self.key)
        self.Refresh()

    def _release(self) -> None:
        self._dragging = False
        self._grab = None
        if self.HasCapture():
            try:
                self.ReleaseMouse()
            except Exception:  # pragma: no cover - platform boundary
                log.debug("Could not release the pointer for the %s grip", self.key)

    # -- keyboard ------------------------------------------------------------
    #: Everything the pointer can do, one key press at a time.
    MOVES: Dict[int, Tuple[int, int]] = {
        wx.WXK_LEFT: (-1, 0),
        wx.WXK_RIGHT: (1, 0),
        wx.WXK_UP: (0, -1),
        wx.WXK_DOWN: (0, 1),
        wx.WXK_NUMPAD_LEFT: (-1, 0),
        wx.WXK_NUMPAD_RIGHT: (1, 0),
        wx.WXK_NUMPAD_UP: (0, -1),
        wx.WXK_NUMPAD_DOWN: (0, 1),
    }

    def _on_key_down(self, event: wx.KeyEvent) -> None:
        code = event.GetKeyCode()
        if code in (wx.WXK_HOME, wx.WXK_NUMPAD_HOME):
            invoke(self._on_reset, self.key, bool(event.ShiftDown()))
            return
        delta = self.MOVES.get(code)
        if delta is None:
            event.Skip()
            return
        step = overlay_step(bool(event.ShiftDown()))
        self._nudged = True
        invoke(self._on_move, self.key, delta[0] * step, delta[1] * step)

    def _on_key_up(self, event: wx.KeyEvent) -> None:
        """Write the position down once the key is let go, not once per repeat.

        A held arrow key repeats about thirty times a second, and the profile is
        a gzipped pickle: writing on every repeat would put thirty file writes a
        second behind one keypress for no gain, since only the last one is the
        position the user meant.
        """
        if self._nudged:
            self._nudged = False
            invoke(self._on_commit, self.key)
        event.Skip()

    def _on_focus(self, event: wx.FocusEvent) -> None:
        invoke(self._on_attention, self.key, True)
        self.Refresh()
        event.Skip()

    def _on_blur(self, event: wx.FocusEvent) -> None:
        if not self._hovered and not self._dragging:
            invoke(self._on_attention, self.key, False)
        self.Refresh()
        event.Skip()

    # -- painting ------------------------------------------------------------
    def _backdrop(self) -> wx.Colour:
        return hud_backdrop(self)

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        return wx.Size(tokens.scaled(GRIP_THICKNESS), tokens.scaled(GRIP_MIN_LENGTH))

    def active(self) -> bool:
        """Return whether the handle is showing itself as grabbable."""
        return bool(self._hovered or self._dragging or self.HasFocus())

    def render_to(self, dc: wx.DC, rect: wx.Rect) -> None:
        """Draw the handle, in one place both the screen and a capture use.

        A widget that paints only in ``EVT_PAINT`` and never overrides this
        inherits a default that fills its backdrop and returns, and the capture
        harness records that as a successful draw -- so the report comes back
        clean and the picture has an empty rectangle where the handle should
        be.  This is that override.
        """
        with translated(dc, rect):
            width = max(1, rect.width)
            height = max(1, rect.height)
            dc.SetBrush(wx.Brush(self._backdrop()))
            dc.SetPen(wx.TRANSPARENT_PEN)
            dc.DrawRectangle(0, 0, width, height)

            accent = colour_of(OVERLAY_ACCENT)
            body = wx.Rect(0, 0, width, height)
            radius = tokens.scaled(tokens.RADIUS_SM - 2)
            if self.active():
                fill = wx.Colour(accent.Red(), accent.Green(), accent.Blue(), 92)
                border = accent
                dot = accent
            else:
                fill = wx.Colour(255, 255, 255, 36)
                border = wx.Colour(255, 255, 255, 56)
                dot = wx.Colour(255, 255, 255, 140)
            tokens.draw_round_rect(dc, body, radius, fill, border)

            size = max(2, tokens.scaled(3))
            dc.SetPen(wx.TRANSPARENT_PEN)
            dc.SetBrush(wx.Brush(dot))
            for fraction in self.DOTS:
                centre_y = int(round(height * fraction))
                dc.DrawEllipse((width - size) // 2, centre_y - size // 2, size, size)
            if self.HasFocus():
                draw_focus_ring(dc, body, radius, accent)

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        dc, gcdc = paint_context(self, self._backdrop())
        width, height = self.GetClientSize()
        self.render_to(gcdc, wx.Rect(0, 0, width, height))
        del gcdc


class ViewportHost(wx.Panel):
    """The world view: a real renderer when there is one, a stand-in when not."""

    def __init__(
        self,
        parent: wx.Window,
        *,
        on_surface: Optional[Callable[[str], None]] = None,
        on_command: Optional[Callable[[str], None]] = None,
        on_tool: Optional[Callable[[str], None]] = None,
        on_projection: Optional[Callable[[str], None]] = None,
        on_camera: Optional[Callable[[Tuple[float, float, float], float], None]] = None,
        on_selection: Optional[
            Callable[[Tuple[int, int, int], Tuple[int, int, int]], None]
        ] = None,
        overlay_surface: str = OVERLAY_SURFACE,
    ) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL | wx.FULL_REPAINT_ON_RESIZE)
        self.on_surface = on_surface
        self.on_command = on_command
        self.on_tool = on_tool
        self.on_projection = on_projection
        self.on_camera = on_camera
        self.on_selection = on_selection

        self.camera: Tuple[float, float, float] = DEFAULT_CAMERA
        self.yaw = DEFAULT_YAW
        self.dimension = "minecraft:overworld"
        self.projection_key = "3d"
        self.slice_visible = False
        self.selection_label = "Box 1"
        self.selection_minimum: Tuple[int, int, int] = (-2, 98, -49)
        self.selection_maximum: Tuple[int, int, int] = (13, 99, -32)
        self._canvas: Optional[wx.Window] = None
        self._overlays_visible = True
        # Live-readout state.  ``_reading`` is the last set of values actually
        # read from the renderer, kept so a caller -- a test, a report, a
        # diagnostic -- can ask what the display is showing and where it came
        # from rather than parsing the chips back out of their own text.
        self._live_timer: Optional[wx.Timer] = None
        self._frames = 0
        self._frame_clock = time.monotonic()
        self._fps: Optional[float] = None
        self._frame_binder: Any = None
        self._bounds_cache: Dict[str, Optional[Tuple[int, int]]] = {}
        self._home_view: Optional[Tuple[Tuple[float, float, float], float]] = None
        self._reading: Dict[str, Any] = {}
        self._placeholder_reason = ""
        # Where each movable overlay group has been put, and where it is now.
        # ``_overlay_offsets`` holds only the groups the user has actually
        # moved, as distances from the corner that group is anchored to; a
        # group absent from it is drawn at the shipped inset, which is what
        # makes a reset "forget" rather than "store the default again".
        self._overlay_surface = str(overlay_surface or OVERLAY_SURFACE)
        self._overlay_offsets: Dict[str, Tuple[int, int]] = load_overlay_offsets(
            self._overlay_surface
        )
        self._overlay_rects: Dict[str, wx.Rect] = {}
        self._overlay_placed: Dict[str, Tuple[wx.Window, ...]] = {}
        self._hint_for: Optional[str] = None

        self.SetName("World viewport")
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetBackgroundColour(sky_colour(0.5))
        # The world surface answers its own right-click, in _on_context_menu
        # below.  The shared Material layer otherwise binds a two-row
        # "Appearance" popup to every window it styles, and because that handler
        # is bound later it runs first and never skips -- so it shadowed this
        # panel's own decision entirely and put a menu over the world on every
        # right-click and every right-drag.  Right-drag rotates the camera, so
        # that menu was cancelling the gesture the user was making.  The HUD
        # overlays are separate windows and keep their own appearance menu; the
        # viewport's own "Edit appearance…" is the last row of the viewport menu
        # this panel opens, and the Element appearance surface reaches it from
        # the command palette.
        self._material3_appearance_menu_disabled = True

        self.world_chip = HudChip(self, NO_WORLD_CHIP, name="World version")
        self.dimension_chip = HudChip(self, NO_DIMENSION_CHIP, name="Dimension")
        self.position_chip = HudChip(self, NO_CAMERA_CHIP, name="Camera position")
        self.performance_chip = HudChip(self, NO_RENDER_CHIP, name="Render performance")
        self.chips = (
            self.world_chip,
            self.dimension_chip,
            self.position_chip,
            self.performance_chip,
        )
        self.caption = HudChip(
            self,
            self._caption_text(),
            name="Selected box",
            size_px=10,
            radius=tokens.RADIUS_SM - 2,
        )
        self.placeholder_notice = HudChip(
            self,
            studio_text(
                "Placeholder view. No renderer is attached, so this is a drawn "
                "stand-in for the world.",
                "呢個係示意圖。渲染器未接上，所以先用幅畫代住個世界。",
            ),
            name="Renderer status",
            size_px=11,
        )
        self._clear_readouts()
        self.minimap = MinimapView(self, on_click=self._open_goto)
        self.compass = CompassView(self, on_click=self.face_north)
        self.axes = AxesLegend(self)
        self.tools: Dict[str, ViewportToolButton] = {}
        for key, glyph, label, hint in VIEWPORT_TOOLS:
            self.tools[key] = ViewportToolButton(
                self, key, glyph, label, hint, on_click=self.run_tool
            )
        self.minimum_handle = CornerHandle(
            self,
            "minimum",
            MINIMUM_HANDLE_COLOUR,
            on_nudge=self._nudge_corner,
            on_click=self._focus_corner,
        )
        self.maximum_handle = CornerHandle(
            self,
            "maximum",
            MAXIMUM_HANDLE_COLOUR,
            on_nudge=self._nudge_corner,
            on_click=self._focus_corner,
        )
        self.grips: Dict[str, OverlayGrip] = {}
        for group in OVERLAY_GROUPS:
            self.grips[group.key] = OverlayGrip(
                self,
                group.key,
                group.label,
                on_place=self.place_overlay,
                on_move=self.move_overlay,
                on_commit=self.commit_overlay,
                on_reset=self._reset_from_grip,
                on_attention=self._overlay_attention,
            )
        # The keyboard route has to be stated somewhere a user can read it, and
        # a ten pixel gutter has room for no words at all.  This chip is that
        # sentence: hidden until a grip is hovered or focused, so it is an
        # answer to "what do I do with this" rather than permanent clutter.
        self.overlay_hint = HudChip(
            self,
            overlay_hint_text(),
            name="Overlay move keys",
            size_px=10,
            radius=tokens.RADIUS_SM - 2,
        )
        self.overlay_hint.Hide()
        self._sync_selection_controls()

        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.Bind(wx.EVT_SIZE, self._on_size)
        self.Bind(wx.EVT_CONTEXT_MENU, self._on_context_menu)
        # Right-drag rotates the camera and right-click inspects a block: both
        # belong to the editor, and a context menu that opens on button-down
        # takes the gesture away mid-motion.  Tracking the press lets the menu
        # open only when the button comes back up without having travelled.
        self.Bind(wx.EVT_RIGHT_DOWN, self._on_right_down)
        self.Bind(wx.EVT_RIGHT_UP, self._on_right_up)
        self._right_press: Optional[wx.Point] = None
        self._right_dragged = False
        self.Bind(wx.EVT_WINDOW_DESTROY, self._on_destroy)

    def _on_destroy(self, event: wx.WindowDestroyEvent) -> None:
        """Stop reading the renderer before wx tears this panel down."""
        if event.GetEventObject() is self:
            self._stop_live_readout()
        event.Skip()

    # -- renderer ------------------------------------------------------------
    def set_canvas(self, window: Optional[wx.Window]) -> None:
        """Host a real renderer canvas, or return to the drawn stand-in.

        The canvas keeps its own parent when it already has this host as one;
        anything else is reparented, because a canvas that is not a child of
        this panel cannot be positioned inside it.
        """
        if self._canvas is window:
            self._position_canvas()
            return
        if self._canvas is not None:
            self._stop_live_readout()
            # Handed back to the notebook, it is an ordinary control again.
            self._canvas._material3_appearance_menu_disabled = False
            self._canvas.Hide()
        self._canvas = window
        if window is not None:
            # The live 3D surface belongs to the editor's own mouse bindings:
            # right-drag rotates the camera and right-click changes mouse mode.
            # An appearance menu opening on either does not merely add a menu,
            # it takes the gesture away mid-motion.
            window._material3_appearance_menu_disabled = True
            if window.GetParent() is not self:
                try:
                    window.Reparent(self)
                except Exception:
                    log.exception("Could not reparent the renderer canvas")
            window.Show()
            window.Lower()
            # A canvas that has never been laid out arrives at zero by zero and
            # would draw the world into no pixels at all, so it is given the
            # host's size here rather than waiting for the next resize.
            self._position_canvas()
            self._raise_overlays()
            self._start_live_readout()
        else:
            self._clear_readouts()
        self._sync_placeholder_controls()
        self._layout_overlays()
        self.Refresh()

    def canvas(self) -> Optional[wx.Window]:
        """Return the hosted renderer canvas, or ``None``."""
        return self._canvas

    def has_canvas(self) -> bool:
        """Return whether a real renderer is currently attached."""
        return self._canvas is not None

    def set_placeholder_reason(self, reason: str) -> None:
        """State why there is no renderer, in the stand-in's own notice.

        "No world is open" and "the renderer is still starting" are different
        facts and the user can act on them differently, so the host says which
        one it is rather than showing one sentence for every absence.
        """
        self._placeholder_reason = str(reason or "")
        text = self._placeholder_reason or studio_text(
            "Placeholder view. No renderer is attached, so this is a drawn "
            "stand-in for the world.",
            "呢個係示意圖。渲染器未接上，所以先用幅畫代住個世界。",
        )
        self.placeholder_notice.set_text(text)
        self._layout_overlays()

    # -- live readout --------------------------------------------------------
    def readout(self) -> Dict[str, Any]:
        """Return the values last read from the renderer, and their source.

        Every entry is either something the renderer actually answered or is
        absent.  Callers use this to prove a reading came from the canvas
        rather than from the layout beside it.
        """
        return dict(self._reading)

    def _start_live_readout(self) -> None:
        """Begin re-reading the hosted renderer on a timer."""
        self._bounds_cache = {}
        self._frames = 0
        self._frame_clock = time.monotonic()
        self._fps = None
        self._home_view = None
        self._bind_frame_counter()
        if self._live_timer is None:
            self._live_timer = wx.Timer(self)
            self.Bind(wx.EVT_TIMER, self._on_live_tick, self._live_timer)
        if not self._live_timer.IsRunning():
            self._live_timer.Start(LIVE_POLL_MS)
        self._read_canvas()

    def _stop_live_readout(self) -> None:
        """Stop reading, and let go of the counter bound to the old canvas."""
        if self._live_timer is not None and self._live_timer.IsRunning():
            self._live_timer.Stop()
        self._unbind_frame_counter()
        self._reading = {}

    def _unbind_frame_counter(self) -> None:
        canvas, binder = self._canvas, self._frame_binder
        self._frame_binder = None
        if canvas is None or binder is None:
            return
        try:
            canvas.Unbind(binder, handler=self._count_frame)
        except Exception:  # pragma: no cover - the canvas is already gone
            log.debug("Could not unbind the frame counter")

    def _bind_frame_counter(self) -> None:
        """Count the renderer's own pre-draw events, one per frame it draws.

        The count is re-established on every tick rather than once, because the
        editor canvas unbinds every handler on its own event table whenever the
        active tool changes -- a counter bound once would silently stop
        counting the first time the user picked a different tool, and an fps
        reading that has quietly stopped looks exactly like one that has not.
        """
        canvas = self._canvas
        if canvas is None:
            return
        try:
            from amulet_map_editor.api.opengl.events import EVT_PRE_DRAW
        except Exception:  # pragma: no cover - a build without OpenGL
            log.debug("The renderer's draw events are unavailable", exc_info=True)
            self._frame_binder = None
            return
        self._frame_binder = EVT_PRE_DRAW
        try:
            canvas.Unbind(EVT_PRE_DRAW, handler=self._count_frame)
        except Exception:  # pragma: no cover - nothing was bound
            pass
        try:
            canvas.Bind(EVT_PRE_DRAW, self._count_frame)
        except Exception:  # pragma: no cover - the canvas is tearing down
            log.debug("Could not bind the frame counter")
            self._frame_binder = None

    def _count_frame(self, event: wx.Event) -> None:
        self._frames += 1
        event.Skip()

    def _on_live_tick(self, _event: wx.TimerEvent) -> None:
        self._bind_frame_counter()
        self._read_canvas()

    def _canvas_is_live(self) -> bool:
        canvas = self._canvas
        if canvas is None:
            return False
        try:
            return bool(canvas) and not canvas.IsBeingDeleted()
        except RuntimeError:  # pragma: no cover - already destroyed
            return False

    @staticmethod
    def _ask(getter: Callable[[], Any]) -> Any:
        """Return what the renderer answered, or ``None`` when it could not.

        A renderer mid-teardown, mid-load, or on a platform missing a piece of
        state raises rather than answering, and one unanswered reading must not
        take the other three down with it.
        """
        try:
            return getter()
        except Exception:  # noqa: BLE001 - any read may fail; none is fatal
            return None

    def _loaded_chunk_count(self) -> Optional[int]:
        """Return how many chunks the renderer currently holds in memory."""
        canvas = self._canvas

        def count() -> int:
            manager = canvas.renderer.render_world.chunk_manager
            total = len(getattr(manager, "_chunk_temp_set", ()))
            for region in getattr(manager, "_regions", {}).values():
                total += len(getattr(region, "_chunks", ()))
            return total

        value = self._ask(count)
        return None if value is None else int(value)

    def _dimension_bounds(self, dimension: str) -> Optional[Tuple[int, int]]:
        """Return the dimension's real build range, asking the world once."""
        if dimension in self._bounds_cache:
            return self._bounds_cache[dimension]
        canvas = self._canvas

        def bounds() -> Tuple[int, int]:
            box = canvas.world.bounds(dimension)
            return int(box.min_y), int(box.max_y)

        value = self._ask(bounds)
        self._bounds_cache[dimension] = value
        return value

    def _world_label(self) -> str:
        """Return the open world's own platform and version, as it reports it."""
        canvas = self._canvas
        printable = self._ask(
            lambda: str(canvas.world.level_wrapper.game_version_string)
        )
        if printable:
            return printable
        platform = self._ask(lambda: str(canvas.world.level_wrapper.platform)) or ""
        version = self._ask(lambda: canvas.world.level_wrapper.version)
        if isinstance(version, (tuple, list)):
            version = ".".join(str(part) for part in version)
        parts = [part for part in (platform, str(version or "")) if part]
        return " ".join(parts)

    def _read_canvas(self) -> None:
        """Re-read every live value from the renderer and show what it said."""
        if not self._canvas_is_live():
            return
        canvas = self._canvas
        reading: Dict[str, Any] = {"source": type(canvas).__name__}

        world = self._world_label()
        if world:
            reading["world"] = world
            self.world_chip.set_text(
                world, "The open world's own platform and version, from level.dat."
            )
        else:
            self.world_chip.set_text(
                NO_WORLD_CHIP, "The renderer did not report a world version."
            )

        dimension = self._ask(lambda: str(canvas.dimension or ""))
        if dimension:
            reading["dimension"] = dimension
            bounds = self._dimension_bounds(dimension)
            if bounds is None:
                self.dimension_chip.set_text(
                    dimension, "This world did not report a build range for it."
                )
            else:
                reading["bounds"] = bounds
                self.dimension_chip.set_text(
                    f"{dimension} · y {bounds[0]} to {bounds[1]}",
                    "The dimension the renderer is showing and its real build range.",
                )
            if dimension != self.dimension:
                self.dimension = dimension
                self.minimap.set_view(dimension=dimension)
        else:
            self.dimension_chip.set_text(
                NO_DIMENSION_CHIP, "The renderer did not report a dimension."
            )

        location = self._ask(lambda: tuple(float(v) for v in canvas.camera.location))
        rotation = self._ask(lambda: tuple(float(v) for v in canvas.camera.rotation))
        if location is not None and len(location) == 3:
            reading["camera"] = location
            if rotation:
                reading["yaw"] = float(rotation[0])
            if self._home_view is None:
                self._home_view = (location, float(rotation[0]) if rotation else 0.0)
            self.camera = location
            self.position_chip.set_text(
                self._position_text(), "The renderer's camera, in block coordinates."
            )
            if rotation:
                self.yaw = float(rotation[0]) % 360.0
                self.compass.set_yaw(self.yaw)
            self.minimap.set_view(camera=self.camera)
        else:
            self.position_chip.set_text(
                NO_CAMERA_CHIP, "The renderer did not report a camera position."
            )

        elapsed = time.monotonic() - self._frame_clock
        if elapsed >= LIVE_POLL_MS / 1000.0:
            self._fps = self._frames / elapsed if self._frames else 0.0
            self._frames = 0
            self._frame_clock = time.monotonic()
        chunks = self._loaded_chunk_count()
        if chunks is not None:
            reading["chunks"] = chunks
        if self._fps is not None:
            reading["fps"] = self._fps
        fps_text = "fps unmeasured" if self._fps is None else f"{self._fps:.0f} fps"
        chunk_text = "chunks unavailable" if chunks is None else f"{chunks:,} chunks"
        self.performance_chip.set_text(
            f"{fps_text} · {chunk_text}",
            "Frames the renderer actually drew in the last half second, and "
            "the chunks it currently holds in memory.",
        )

        self._reading = reading
        self._layout_overlays()

    def _clear_readouts(self) -> None:
        """Say plainly that there is nothing to read, rather than a last value."""
        self._fps = None
        self._reading = {}
        self.world_chip.set_text(NO_WORLD_CHIP, NO_RENDERER_REASON)
        self.dimension_chip.set_text(NO_DIMENSION_CHIP, NO_RENDERER_REASON)
        self.position_chip.set_text(NO_CAMERA_CHIP, NO_RENDERER_REASON)
        self.performance_chip.set_text(NO_RENDER_CHIP, NO_RENDERER_REASON)

    def set_overlays_visible(self, visible: bool) -> None:
        """Show or hide every heads-up control at once."""
        self._overlays_visible = bool(visible)
        self._sync_placeholder_controls()
        self._layout_overlays()

    # -- readouts ------------------------------------------------------------
    def _position_text(self) -> str:
        return ", ".join(f"{value:.2f}" for value in self.camera)

    def _caption_text(self) -> str:
        size = [
            high - low + 1
            for low, high in zip(self.selection_minimum, self.selection_maximum)
        ]
        return f"{self.selection_label} · {'x'.join(str(value) for value in size)}"

    def set_status(
        self,
        *,
        world: Optional[str] = None,
        position: Optional[Tuple[float, float, float]] = None,
        fps: Optional[float] = None,
        chunks: Optional[int] = None,
        dimension: Optional[str] = None,
    ) -> None:
        """Point the stand-in view at a dimension and a camera.

        The four chips are readings, not settings: they show what the hosted
        renderer answered, and when nothing is hosted they say so.  A caller
        that knows a dimension name or a camera position is describing the
        drawn stand-in, so those two move the stand-in; ``world``, ``fps``, and
        ``chunks`` are facts only a renderer can establish and are recorded for
        :meth:`readout` rather than displayed as though they had been measured.
        """
        for key, value in (("world", world), ("fps", fps), ("chunks", chunks)):
            if value is not None and not self.has_canvas():
                log.debug(
                    "Ignoring a pushed %s of %r: the viewport shows only what a "
                    "renderer reported",
                    key,
                    value,
                )
        if dimension is not None:
            self.dimension = str(dimension)
            self.minimap.set_view(dimension=self.dimension)
        if position is not None and not self.has_canvas():
            self.set_camera(position=position)
        self._layout_overlays()

    def set_camera(
        self,
        position: Optional[Tuple[float, float, float]] = None,
        yaw: Optional[float] = None,
        *,
        notify: bool = False,
    ) -> None:
        """Move the camera, in the renderer when there is one.

        With a renderer hosted this writes the real camera, so framing a
        selection or facing north moves the world rather than only the drawn
        minimap; the next live read then shows where the camera actually ended
        up, which is not always exactly where it was asked to go.
        """
        if position is not None:
            self.camera = tuple(float(value) for value in position)
        if yaw is not None:
            self.yaw = float(yaw) % 360.0
            self.compass.set_yaw(self.yaw)
        if self.has_canvas():
            self._push_camera(position, yaw)
            self.position_chip.set_text(
                self._position_text(), "The renderer's camera, in block coordinates."
            )
        self.minimap.set_view(camera=self.camera)
        self._layout_overlays()
        if notify:
            invoke(self.on_camera, self.camera, self.yaw)

    def _push_camera(
        self,
        position: Optional[Tuple[float, float, float]],
        yaw: Optional[float],
    ) -> None:
        """Write a camera move into the hosted renderer."""
        canvas = self._canvas
        if canvas is None:
            return
        if position is not None:
            point = tuple(float(value) for value in position)
            self._ask(lambda: setattr(canvas.camera, "location", point))
        if yaw is not None:
            current = self._ask(
                lambda: tuple(float(value) for value in canvas.camera.rotation)
            ) or (0.0, 0.0)
            pitch = current[1] if len(current) > 1 else 0.0
            self._ask(
                lambda: setattr(canvas.camera, "rotation", (float(yaw) % 360.0, pitch))
            )

    def set_selection(
        self,
        label: str,
        minimum: Tuple[int, int, int],
        maximum: Tuple[int, int, int],
    ) -> None:
        """Show a different selection box on the stand-in view."""
        self.selection_label = str(label)
        self.selection_minimum = tuple(int(value) for value in minimum)
        self.selection_maximum = tuple(int(value) for value in maximum)
        self._sync_selection_controls()
        self._layout_overlays()
        self.Refresh()

    def _sync_selection_controls(self) -> None:
        self.caption.set_text(self._caption_text())
        self.minimum_handle.set_corner(self.selection_minimum)
        self.maximum_handle.set_corner(self.selection_maximum)
        self.minimap.set_view(
            minimum=self.selection_minimum, maximum=self.selection_maximum
        )

    def projection(self) -> str:
        """Return the current projection key."""
        return self.projection_key

    def set_projection(self, key: str, *, notify: bool = False) -> None:
        """Switch between the 3D and top-down views."""
        self.projection_key = "top" if str(key) == "top" else "3d"
        self.tools["top"].set_active(self.projection_key == "top")
        self.Refresh()
        if notify:
            invoke(self.on_projection, self.projection_key)

    # -- tools ---------------------------------------------------------------
    def run_tool(self, key: str) -> None:
        """Run one of the four viewport tools."""
        if key == "frame":
            self.frame_selection()
        elif key == "top":
            self.set_projection(
                "3d" if self.projection_key == "top" else "top", notify=True
            )
        elif key == "slice":
            self.toggle_slice()
        elif key == "reset":
            self.reset_camera()
        invoke(self.on_tool, key)

    def live_selection(
        self,
    ) -> Optional[Tuple[Tuple[int, int, int], Tuple[int, int, int]]]:
        """Return the selection the renderer actually holds, or ``None``.

        ``None`` says there is no renderer or it could not be asked; an empty
        selection reports itself as ``None`` too, because framing nothing would
        move the camera somewhere the user never chose.
        """
        canvas = self._canvas
        if canvas is None:
            return None

        def bounds() -> Optional[Tuple[Tuple[int, int, int], Tuple[int, int, int]]]:
            group = canvas.selection.selection_group
            boxes = list(group.selection_boxes)
            if not boxes:
                return None
            lows = [tuple(int(value) for value in box.min) for box in boxes]
            highs = [tuple(int(value) for value in box.max) for box in boxes]
            return (
                (
                    min(point[0] for point in lows),
                    min(point[1] for point in lows),
                    min(point[2] for point in lows),
                ),
                (
                    max(point[0] for point in highs),
                    max(point[1] for point in highs),
                    max(point[2] for point in highs),
                ),
            )

        return self._ask(bounds)

    def frame_selection(self) -> None:
        """Put the camera above the middle of the selection.

        The renderer's own selection is used when there is one, so the button
        frames what the user actually drew rather than the box the stand-in
        happens to be drawing.
        """
        live = self.live_selection()
        if live is not None:
            minimum, maximum = live
        else:
            minimum, maximum = self.selection_minimum, self.selection_maximum
        centre = [(low + high + 1) / 2 for low, high in zip(minimum, maximum)]
        height = centre[1] + max(16.0, (maximum[1] - minimum[1] + 1) * 2.0)
        self.set_camera(position=(centre[0], height, centre[2]), notify=True)

    def toggle_slice(self) -> None:
        """Show or hide the slice band drawn across the stand-in view."""
        self.slice_visible = not self.slice_visible
        self.tools["slice"].set_active(self.slice_visible)
        self.Refresh()

    def reset_camera(self) -> None:
        """Return the camera to the position and heading the view opened with.

        With a renderer hosted that is where its camera genuinely was when the
        world opened, which was read from the world's own player data; without
        one it is the stand-in's drawn viewpoint.
        """
        if self._home_view is not None:
            position, yaw = self._home_view
        else:
            position, yaw = DEFAULT_CAMERA, DEFAULT_YAW
        self.set_camera(position=position, yaw=yaw, notify=True)

    def face_north(self) -> None:
        """Turn the camera to face north."""
        self.set_camera(yaw=0.0, notify=True)

    def _open_goto(self) -> None:
        invoke(self.on_surface, "goto")

    def _focus_corner(self, role: str) -> None:
        handle = self.minimum_handle if role == "minimum" else self.maximum_handle
        handle.SetFocus()

    def _nudge_corner(self, role: str, delta: Tuple[int, int, int]) -> None:
        """Move one selection corner by whole blocks and report the new bounds."""
        minimum = list(self.selection_minimum)
        maximum = list(self.selection_maximum)
        target = minimum if role == "minimum" else maximum
        for axis in range(3):
            target[axis] += delta[axis]
        for axis in range(3):
            if minimum[axis] > maximum[axis]:
                if role == "minimum":
                    minimum[axis] = maximum[axis]
                else:
                    maximum[axis] = minimum[axis]
        self.selection_minimum = tuple(minimum)
        self.selection_maximum = tuple(maximum)
        self._sync_selection_controls()
        self.Refresh()
        invoke(self.on_selection, self.selection_minimum, self.selection_maximum)

    # -- movable overlays ----------------------------------------------------
    def overlay_step(self, large: bool = False) -> int:
        """Return how far one arrow key press moves an overlay, in real pixels."""
        return overlay_step(large)

    def overlay_rect(self, key: str) -> wx.Rect:
        """Return where one overlay group currently sits, grab handle included.

        An empty rectangle means the group is not laid out at all -- the view is
        too small for it, or the overlays are hidden -- rather than that it sits
        at the origin.
        """
        return wx.Rect(self._overlay_rects.get(key, wx.Rect(0, 0, 0, 0)))

    def overlay_members(self, key: str) -> Tuple[wx.Window, ...]:
        """Return the controls the last layout actually placed in one group."""
        return self._overlay_placed.get(key, ())

    def _overlay_controls(self, key: str) -> Tuple[wx.Window, ...]:
        """Return every control belonging to one group, shown or not."""
        if key == "readouts":
            return tuple(self.chips)
        if key == "minimap":
            return (self.minimap, self.compass)
        if key == "axes":
            return (self.axes,)
        if key == "tools":
            return tuple(self.tools[entry[0]] for entry in VIEWPORT_TOOLS)
        return ()

    def _overlay_content_size(self, group: OverlayGroup) -> wx.Size:
        """Return how much room one group's controls need, laid out together."""
        members = self._overlay_controls(group.key)
        if not members:
            return wx.Size(0, 0)
        gap = tokens.scaled(group.gap)
        widths = [member.GetSize().width for member in members]
        heights = [member.GetSize().height for member in members]
        spacing = gap * (len(members) - 1)
        if group.vertical:
            return wx.Size(max(widths), sum(heights) + spacing)
        return wx.Size(sum(widths) + spacing, max(heights))

    @staticmethod
    def _clamp_overlay(
        x: int, y: int, group_width: int, group_height: int, width: int, height: int
    ) -> Tuple[int, int]:
        """Pull a position back inside the view, so it can always be grabbed again.

        Full containment rather than "leave a few pixels showing": a handle is
        ten pixels wide, and a rule that leaves ten pixels of a group visible
        can leave exactly the wrong ten -- the far edge of a tool column, with
        the grab handle itself outside the window and nothing to take hold of.
        A group wider or taller than the view is pinned to the near edge, which
        is the most of it that can be reached.
        """
        return (
            min(max(0, int(x)), max(0, width - group_width)),
            min(max(0, int(y)), max(0, height - group_height)),
        )

    def _overlay_origin(
        self,
        group: OverlayGroup,
        group_width: int,
        group_height: int,
        width: int,
        height: int,
    ) -> Tuple[int, int]:
        """Return where one group starts, remembered position and clamp applied."""
        pad = tokens.scaled(group.pad)
        gap_x, gap_y = self._overlay_offsets.get(group.key, (pad, pad))
        x = gap_x if group.anchor_x == "left" else width - group_width - gap_x
        y = gap_y if group.anchor_y == "top" else height - group_height - gap_y
        return self._clamp_overlay(x, y, group_width, group_height, width, height)

    def place_overlay(self, key: str, x: int, y: int) -> wx.Rect:
        """Put one overlay group's top-left corner at a point, clamped to the view.

        The position is recorded as the distance from the two edges its group is
        anchored to rather than as the point itself, so the same overlay is in
        the same *place* after the window changes size instead of the same
        coordinate.
        """
        group = OVERLAY_BY_KEY.get(key)
        rect = self._overlay_rects.get(key)
        if group is None or rect is None or rect.width <= 0:
            return self.overlay_rect(key)
        width, height = self.GetClientSize()
        x, y = self._clamp_overlay(x, y, rect.width, rect.height, width, height)
        self._overlay_offsets[key] = (
            x if group.anchor_x == "left" else width - rect.width - x,
            y if group.anchor_y == "top" else height - rect.height - y,
        )
        self._layout_overlays()
        self.Refresh()
        return self.overlay_rect(key)

    def move_overlay(self, key: str, dx: int, dy: int) -> wx.Rect:
        """Move one overlay group by a pixel delta, clamped to the view."""
        rect = self._overlay_rects.get(key)
        if rect is None or rect.width <= 0:
            return self.overlay_rect(key)
        return self.place_overlay(key, rect.x + int(dx), rect.y + int(dy))

    def commit_overlay(self, key: str) -> None:
        """Write one overlay's position to the profile, at the end of a gesture."""
        offset = self._overlay_offsets.get(key)
        if offset is None:
            clear_overlay_offsets(self._overlay_surface, key)
            return
        store_overlay_offset(self._overlay_surface, key, offset)

    def reset_overlay(self, key: str) -> None:
        """Put one overlay group back where it shipped, and remember that."""
        self._overlay_offsets.pop(key, None)
        clear_overlay_offsets(self._overlay_surface, key)
        self._layout_overlays()
        self.Refresh()

    def reset_overlay_layout(self) -> None:
        """Put every overlay group back where it shipped, and remember that."""
        self._overlay_offsets.clear()
        clear_overlay_offsets(self._overlay_surface)
        self._layout_overlays()
        self.Refresh()

    def _reset_from_grip(self, key: str, every: bool) -> None:
        if every:
            self.reset_overlay_layout()
        else:
            self.reset_overlay(key)

    def _overlay_attention(self, key: str, showing: bool) -> None:
        """Show or hide the sentence explaining how to move an overlay."""
        self._hint_for = key if showing else None
        self._place_overlay_hint()

    def _place_overlay_hint(self) -> None:
        """Put the hint beside the grip that asked for it, inside the view."""
        key = self._hint_for
        rect = self._overlay_rects.get(key or "")
        if not self._overlays_visible or key is None or rect is None or not rect.width:
            self.overlay_hint.Hide()
            return
        self.overlay_hint.set_text(overlay_hint_text())
        size = self.overlay_hint.GetSize()
        width, height = self.GetClientSize()
        gap = tokens.scaled(6)
        below = rect.GetBottom() + gap
        x = rect.x
        y = below if below + size.height <= height else rect.y - gap - size.height
        x, y = self._clamp_overlay(x, y, size.width, size.height, width, height)
        self.overlay_hint.SetPosition(wx.Point(x, y))
        self.overlay_hint.Show()
        try:
            self.overlay_hint.Raise()
        except Exception:  # pragma: no cover - platform boundary
            log.debug("Could not raise the overlay hint")

    # -- geometry ------------------------------------------------------------
    def background_colour_at(self, rect: wx.Rect) -> wx.Colour:
        """Return the sky colour behind a child window's rectangle."""
        height = max(1, self.GetClientSize().height)
        centre = rect.y + rect.height / 2 if rect.height else rect.y
        return sky_colour(centre / height)

    def wireframe_rect(self) -> wx.Rect:
        """Return where the stand-in draws the selection box."""
        width, height = self.GetClientSize()
        box_width = min(
            tokens.scaled(WIREFRAME_WIDTH), max(40, width - tokens.scaled(80))
        )
        box_height = min(
            tokens.scaled(WIREFRAME_HEIGHT), max(30, height - tokens.scaled(120))
        )
        return wx.Rect(
            (width - box_width) // 2, (height - box_height) // 2, box_width, box_height
        )

    def _raise_overlays(self) -> None:
        for child in self.GetChildren():
            if child is not self._canvas:
                try:
                    child.Raise()
                except Exception:  # pragma: no cover - platform boundary
                    log.debug("Could not raise a heads-up control")

    def _placeholder_controls(self) -> Tuple[wx.Window, ...]:
        return (
            self.caption,
            self.placeholder_notice,
            self.minimum_handle,
            self.maximum_handle,
        )

    def _sync_placeholder_controls(self) -> None:
        placeholder = self._overlays_visible and not self.has_canvas()
        # The name is where the stand-in is admitted to assistive technology,
        # and it holds even at sizes too small to show the notice itself.
        self.SetName(
            "World viewport"
            if self.has_canvas()
            else "World viewport, placeholder: no renderer is attached"
        )
        for control in self._placeholder_controls():
            control.Show(placeholder)
        for control in self.chips + (self.minimap, self.compass, self.axes):
            control.Show(self._overlays_visible)
        for tool in self.tools.values():
            tool.Show(self._overlays_visible)

    def _position_canvas(self) -> None:
        if self._canvas is not None:
            self._canvas.SetSize(self.GetClientSize())
            self._canvas.SetPosition(wx.Point(0, 0))

    def _on_size(self, event: wx.SizeEvent) -> None:
        self._position_canvas()
        self._layout_overlays()
        self.Refresh()
        event.Skip()

    def _layout_overlay_group(
        self, group: OverlayGroup, width: int, height: int, visible: bool
    ) -> None:
        """Place one movable group: its grab handle first, then its controls."""
        members = self._overlay_controls(group.key)
        grip = self.grips[group.key]
        if not visible or not members:
            for member in members:
                member.Show(False)
            grip.Show(False)
            self._overlay_rects[group.key] = wx.Rect(0, 0, 0, 0)
            self._overlay_placed[group.key] = ()
            return

        thickness = tokens.scaled(GRIP_THICKNESS)
        grip_gap = tokens.scaled(GRIP_GAP)
        member_gap = tokens.scaled(group.gap)
        if group.vertical:
            showing = list(members)
            content = self._overlay_content_size(group)
        else:
            # A row is the one shape that can outgrow the view: the readout
            # chips are re-measured every time a reading changes, and four long
            # ones do not fit a narrow window.  Which of them fit has to be
            # settled *before* the group is measured, or the group is sized to
            # a row it is not going to draw -- and then clamped against a width
            # it does not have, which puts the recorded rectangle outside the
            # view while every chip inside it is drawn correctly.  A rectangle
            # that disagrees with the pixels is worse than either.
            showing, used = [], 0
            room = max(0, width - thickness - grip_gap)
            for member in members:
                size = member.GetSize()
                extra = size.width if not showing else member_gap + size.width
                if showing and used + extra > room:
                    break
                showing.append(member)
                used += extra
            content = wx.Size(
                used, max((member.GetSize().height for member in showing), default=0)
            )
        group_width = thickness + grip_gap + content.width
        group_height = max(content.height, tokens.scaled(GRIP_MIN_LENGTH))
        x, y = self._overlay_origin(group, group_width, group_height, width, height)
        self._overlay_rects[group.key] = wx.Rect(x, y, group_width, group_height)

        grip.Show(True)
        grip.SetSize(wx.Size(thickness, group_height))
        grip.SetPosition(wx.Point(x, y))

        left = x + thickness + grip_gap
        top = y
        for member in members:
            if member not in showing:
                member.Show(False)
                continue
            size = member.GetSize()
            member.Show(True)
            if group.vertical:
                # A vertical group hangs off the edge it is anchored to, so its
                # members line up on that side: the compass sits under the right
                # edge of the minimap, as the design draws it, rather than under
                # its left edge with a ragged gap down the middle.
                offset = content.width - size.width if group.anchor_x == "right" else 0
                member.SetPosition(wx.Point(left + offset, top))
                top += size.height + member_gap
            else:
                member.SetPosition(
                    wx.Point(left, y + (group_height - size.height) // 2)
                )
                left += size.width + member_gap
        self._overlay_placed[group.key] = tuple(showing)

    def _layout_overlays(self) -> None:
        """Place every heads-up control, at the corner or wherever it was moved to."""
        width, height = self.GetClientSize()
        if width <= 0 or height <= 0:
            return
        self._sync_placeholder_controls()
        gap = tokens.scaled(6)
        bottom_inset = tokens.scaled(16)

        # Whether a group is shown at all is still decided by the view's size,
        # not by where the user put it: below these the display would overlap
        # itself, and hiding beats clipping.
        axes_size = self.axes.GetSize()
        axes_fits = height >= axes_size.height + tokens.scaled(120)
        tools_fit = height >= tokens.scaled(_TOOLS_MIN_HEIGHT)
        visible = {
            "readouts": self._overlays_visible,
            "minimap": self._overlays_visible
            and width >= tokens.scaled(_MINIMAP_MIN_WIDTH),
            "axes": self._overlays_visible and axes_fits,
            "tools": self._overlays_visible and tools_fit,
        }
        for group in OVERLAY_GROUPS:
            self._layout_overlay_group(
                group, width, height, visible.get(group.key, False)
            )
        self._place_overlay_hint()

        box = self.wireframe_rect()
        placeholder = self._overlays_visible and not self.has_canvas()
        if placeholder:
            caption_size = self.caption.GetSize()
            self.caption.SetPosition(
                wx.Point(
                    (width - caption_size.width) // 2,
                    min(
                        box.GetBottom() + tokens.scaled(16),
                        height - caption_size.height - tokens.scaled(4),
                    ),
                )
            )
            minimum_size = self.minimum_handle.GetSize()
            self.minimum_handle.SetPosition(
                wx.Point(
                    box.x - minimum_size.width // 2, box.y - minimum_size.height // 2
                )
            )
            maximum_size = self.maximum_handle.GetSize()
            self.maximum_handle.SetPosition(
                wx.Point(
                    box.GetRight() - maximum_size.width // 2,
                    box.GetBottom() - maximum_size.height // 2,
                )
            )
            notice_size = self.placeholder_notice.GetSize()
            # The notice sits below the caption, between the axis key and the
            # tool column.  It is hidden only when it genuinely cannot be shown
            # without covering one of them -- the view's own accessible name
            # still says the renderer is missing, so the fact never disappears.
            reserved = tokens.scaled(32)
            if self.axes.IsShown():
                reserved += axes_size.width + gap
            if tools_fit:
                reserved += self.tools[VIEWPORT_TOOLS[0][0]].GetSize().width + gap
            notice_fits = notice_size.width <= width - reserved
            self.placeholder_notice.Show(notice_fits)
            if notice_fits:
                self.placeholder_notice.SetPosition(
                    wx.Point(
                        (width - notice_size.width) // 2,
                        min(
                            box.GetBottom() + tokens.scaled(52),
                            max(0, height - bottom_inset - notice_size.height),
                        ),
                    )
                )

    # -- painting ------------------------------------------------------------
    #: How far the pointer may travel between press and release and still count
    #: as a click rather than a drag.  Smaller than a deliberate camera nudge,
    #: larger than the wobble of a hand releasing a button.
    RIGHT_DRAG_SLOP = 4

    def _on_right_down(self, event: wx.MouseEvent) -> None:
        """Remember where a right press started, then let the editor have it."""
        self._right_press = event.GetPosition()
        self._right_dragged = False
        event.Skip()

    def _on_right_up(self, event: wx.MouseEvent) -> None:
        """Decide whether that press was a click or the end of a drag."""
        start = self._right_press
        if start is not None:
            moved = event.GetPosition() - start
            self._right_dragged = (
                abs(moved.x) > self.RIGHT_DRAG_SLOP
                or abs(moved.y) > self.RIGHT_DRAG_SLOP
            )
        self._right_press = None
        event.Skip()

    def _on_context_menu(self, event: wx.ContextMenuEvent) -> None:
        """Open the viewport menu, unless the gesture was a camera drag.

        A renderer canvas uses right-drag to rotate the camera.  Opening a menu
        on that gesture does not merely add a menu, it cancels the drag, so the
        camera stops moving the instant the user tries to look around.
        """
        if self._right_dragged:
            self._right_dragged = False
            return
        if self.has_canvas():
            # While the real renderer owns this surface the editor's own
            # right-click bindings take precedence: inspecting a block is the
            # documented gesture and the menu must not consume it.  The menu
            # stays reachable from the ribbon, the command palette, and
            # Shift+right-click below.
            if not wx.GetKeyState(wx.WXK_SHIFT):
                event.Skip()
                return
        position = event.GetPosition()
        if position == wx.DefaultPosition:
            size = self.GetSize()
            position = self.ClientToScreen(wx.Point(size.width // 2, size.height // 2))
        open_studio_menu(self, "viewport", position, self.on_surface, self.on_command)

    def refresh_theme(self) -> None:
        """Re-read the palette for every heads-up control and repaint."""
        for child in self.GetChildren():
            refresh = getattr(child, "refresh_theme", None)
            if callable(refresh):
                refresh()
        self._layout_overlays()
        self.Refresh()

    def _paint_sky(self, dc: wx.DC, width: int, height: int) -> None:
        """Fill the view with the design's four-stop sky-to-ground gradient."""
        previous_stop, previous_colour = SKY_STOPS[0]
        for stop, colour in SKY_STOPS[1:]:
            top = int(round(previous_stop * height))
            bottom = int(round(stop * height))
            if bottom > top:
                dc.GradientFillLinear(
                    wx.Rect(0, top, width, bottom - top),
                    colour_of(previous_colour),
                    colour_of(colour),
                    wx.SOUTH,
                )
            previous_stop, previous_colour = stop, colour

    def _paint_grid(self, dc: wx.DC, width: int, height: int) -> None:
        dc.SetPen(wx.Pen(wx.Colour(255, 255, 255, 15)))
        pitch = max(8, tokens.scaled(GRID_PITCH))
        for x in range(0, width, pitch):
            dc.DrawLine(x, 0, x, height)
        for y in range(0, height, pitch):
            dc.DrawLine(0, y, width, y)

    def _paint_selection(self, dc: wx.DC) -> None:
        box = self.wireframe_rect()
        accent = colour_of(OVERLAY_ACCENT)
        dc.SetBrush(
            wx.Brush(wx.Colour(accent.Red(), accent.Green(), accent.Blue(), 46))
        )
        dc.SetPen(wx.Pen(wx.Colour(0, 0, 0, 89)))
        dc.DrawRectangle(wx.Rect(box).Inflate(1, 1))
        dc.SetBrush(wx.TRANSPARENT_BRUSH)
        dc.SetPen(wx.Pen(wx.Colour(255, 255, 255, 230), 2, wx.PENSTYLE_SHORT_DASH))
        dc.DrawRectangle(box)

    def _paint_slice(self, dc: wx.DC, width: int) -> None:
        box = self.wireframe_rect()
        accent = colour_of(OVERLAY_ACCENT)
        band = wx.Rect(0, box.y, width, box.height)
        dc.SetPen(wx.TRANSPARENT_PEN)
        dc.SetBrush(
            wx.Brush(wx.Colour(accent.Red(), accent.Green(), accent.Blue(), 33))
        )
        dc.DrawRectangle(band)
        dc.SetPen(wx.Pen(accent, 1, wx.PENSTYLE_SHORT_DASH))
        dc.DrawLine(0, band.y, width, band.y)
        dc.DrawLine(0, band.GetBottom(), width, band.GetBottom())

    def _paint_crosshair(self, dc: wx.DC, width: int, height: int) -> None:
        dc.SetFont(tokens.font(self, point_size(14)))
        dc.SetTextForeground(wx.Colour(255, 255, 255, 191))
        text = "＋"
        text_width, text_height = dc.GetTextExtent(text)
        dc.DrawText(text, (width - text_width) // 2, (height - text_height) // 2)

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        width, height = self.GetClientSize()
        # The shared helper picks a device context this wx build will actually
        # wrap; constructing one here is how a paint handler starts raising.
        dc, gcdc = paint_context(self, sky_colour(0.5))
        if width <= 0 or height <= 0:
            return
        if self.has_canvas():
            # The renderer owns every pixel inside the host; painting a sky
            # under it would only flash through during a resize.
            return
        self._paint_sky(dc, width, height)
        self._paint_grid(gcdc, width, height)
        if self.slice_visible:
            self._paint_slice(gcdc, width)
        self._paint_selection(gcdc)
        self._paint_crosshair(gcdc, width, height)
        del gcdc


__all__ = [
    "AxesLegend",
    "CompassView",
    "CornerHandle",
    "DEFAULT_CAMERA",
    "DEFAULT_YAW",
    "GRID_PITCH",
    "HudChip",
    "LIVE_POLL_MS",
    "NO_CAMERA_CHIP",
    "NO_DIMENSION_CHIP",
    "NO_RENDERER_REASON",
    "NO_RENDER_CHIP",
    "NO_WORLD_CHIP",
    "MAXIMUM_HANDLE_COLOUR",
    "MINIMUM_HANDLE_COLOUR",
    "MinimapView",
    "OVERLAY_ACCENT",
    "SKY_STOPS",
    "VIEWPORT_TOOLS",
    "ViewportHost",
    "ViewportToolButton",
    "WIREFRAME_HEIGHT",
    "WIREFRAME_WIDTH",
    "hud_backdrop",
    "hud_paint_context",
    "sky_colour",
]
