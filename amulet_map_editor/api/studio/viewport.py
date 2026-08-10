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
"""

from __future__ import annotations

import logging
import math
from typing import Callable, Dict, List, Optional, Tuple

import wx

from amulet_map_editor.api.studio import tokens
from amulet_map_editor.api.studio.copy import studio_text
from amulet_map_editor.api.studio.status_bar import open_studio_menu
from amulet_map_editor.api.studio.widgets import (
    AXIS_COLOURS,
    StudioButton,
    colour_of,
    draw_focus_ring,
    elide,
    invoke,
    point_size,
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

#: The camera the design's heads-up display reports.
DEFAULT_CAMERA: Tuple[float, float, float] = (66.40, 118.13, -43.12)
DEFAULT_YAW = 32.0

#: The world identity chip, exactly as the design shows it.
DEFAULT_WORLD = "bedrock, (1, 17, 0, 58, 0)"
DEFAULT_FPS = 60
DEFAULT_CHUNKS = 812

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


def hud_paint_context(window: wx.Window) -> Tuple[wx.DC, wx.GCDC]:
    """Clear a heads-up control against the sky and return its contexts."""
    dc = wx.AutoBufferedPaintDC(window)
    dc.SetBackground(wx.Brush(hud_backdrop(window)))
    dc.Clear()
    return dc, wx.GCDC(dc)


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

    def set_text(self, text: str) -> None:
        """Replace the chip's text and re-measure it."""
        self._lines = [line for line in str(text).splitlines() if line.strip()] or [""]
        self.SetName(f"{self._label}: {' · '.join(self._lines)}")
        self.SetToolTip(self.text())
        self.InvalidateBestSize()
        self.SetSize(self.DoGetBestSize())
        self.Refresh()

    def _font(self) -> wx.Font:
        return tokens.mono_font(self, point_size(self._size_px))

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        dc = wx.ClientDC(self)
        dc.SetFont(self._font())
        width = max(dc.GetTextExtent(line or " ")[0] for line in self._lines)
        height = dc.GetCharHeight() * len(self._lines)
        return wx.Size(
            width + tokens.scaled(self.PADDING_X) * 2,
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
        dc = wx.ClientDC(self)
        dc.SetFont(tokens.mono_font(self, point_size(10)))
        width = max(dc.GetTextExtent(label)[0] for _axis, label in self.ROWS)
        line_height = dc.GetCharHeight()
        return wx.Size(
            width + tokens.scaled(self.PADDING_X) * 2,
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

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = self.palette()
        dc, gcdc = hud_paint_context(self)
        width, height = self.GetClientSize()
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
        del gcdc


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

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = self.palette()
        dc, gcdc = hud_paint_context(self)
        width, height = self.GetClientSize()
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
        del gcdc


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

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = self.palette()
        dc, gcdc = hud_paint_context(self)
        width, height = self.GetClientSize()
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
        del gcdc


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

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        dc, gcdc = hud_paint_context(self)
        width, height = self.GetClientSize()
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

        self.SetName("World viewport")
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetBackgroundColour(sky_colour(0.5))

        self.world_chip = HudChip(self, DEFAULT_WORLD, name="World version")
        self.position_chip = HudChip(
            self, self._position_text(), name="Camera position"
        )
        self.performance_chip = HudChip(
            self,
            f"{DEFAULT_FPS} fps · {DEFAULT_CHUNKS} chunks",
            name="Render performance",
        )
        self.chips = (self.world_chip, self.position_chip, self.performance_chip)
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
        self._sync_selection_controls()

        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.Bind(wx.EVT_SIZE, self._on_size)
        self.Bind(wx.EVT_CONTEXT_MENU, self._on_context_menu)

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
            self._canvas.Hide()
        self._canvas = window
        if window is not None:
            if window.GetParent() is not self:
                try:
                    window.Reparent(self)
                except Exception:
                    log.exception("Could not reparent the renderer canvas")
            window.Show()
            window.Lower()
            self._raise_overlays()
        self._sync_placeholder_controls()
        self._layout_overlays()
        self.Refresh()

    def canvas(self) -> Optional[wx.Window]:
        """Return the hosted renderer canvas, or ``None``."""
        return self._canvas

    def has_canvas(self) -> bool:
        """Return whether a real renderer is currently attached."""
        return self._canvas is not None

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
        """Update the three chips from whatever the caller actually knows."""
        if world is not None:
            self.world_chip.set_text(str(world))
        if dimension is not None:
            self.dimension = str(dimension)
            self.minimap.set_view(dimension=self.dimension)
        if position is not None:
            self.set_camera(position=position)
        if fps is not None or chunks is not None:
            current = self.performance_chip.text().split(" · ")
            fps_text = (
                f"{float(fps):.0f} fps"
                if fps is not None
                else (current[0] if current else f"{DEFAULT_FPS} fps")
            )
            chunk_text = (
                f"{int(chunks)} chunks"
                if chunks is not None
                else (current[1] if len(current) > 1 else f"{DEFAULT_CHUNKS} chunks")
            )
            self.performance_chip.set_text(f"{fps_text} · {chunk_text}")
        self._layout_overlays()

    def set_camera(
        self,
        position: Optional[Tuple[float, float, float]] = None,
        yaw: Optional[float] = None,
        *,
        notify: bool = False,
    ) -> None:
        """Move the camera, updating the chip, the minimap, and the compass."""
        if position is not None:
            self.camera = tuple(float(value) for value in position)
            self.position_chip.set_text(self._position_text())
        if yaw is not None:
            self.yaw = float(yaw) % 360.0
            self.compass.set_yaw(self.yaw)
        self.minimap.set_view(camera=self.camera)
        self._layout_overlays()
        if notify:
            invoke(self.on_camera, self.camera, self.yaw)

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

    def frame_selection(self) -> None:
        """Put the camera above the middle of the selection."""
        centre = [
            (low + high + 1) / 2
            for low, high in zip(self.selection_minimum, self.selection_maximum)
        ]
        height = centre[1] + max(
            16.0, (self.selection_maximum[1] - self.selection_minimum[1] + 1) * 2.0
        )
        self.set_camera(position=(centre[0], height, centre[2]), notify=True)

    def toggle_slice(self) -> None:
        """Show or hide the slice band drawn across the stand-in view."""
        self.slice_visible = not self.slice_visible
        self.tools["slice"].set_active(self.slice_visible)
        self.Refresh()

    def reset_camera(self) -> None:
        """Return the camera to the position and heading the view opened with."""
        self.set_camera(position=DEFAULT_CAMERA, yaw=DEFAULT_YAW, notify=True)

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

    def _layout_overlays(self) -> None:
        """Place every heads-up control against the corners of the view."""
        width, height = self.GetClientSize()
        if width <= 0 or height <= 0:
            return
        self._sync_placeholder_controls()
        inset = tokens.scaled(14)
        gap = tokens.scaled(6)

        left = inset
        for chip in self.chips:
            size = chip.GetSize()
            fits = left + size.width <= width - inset
            chip.Show(self._overlays_visible and fits)
            if fits:
                chip.SetPosition(wx.Point(left, inset))
                left += size.width + gap

        room_for_map = width >= tokens.scaled(_MINIMAP_MIN_WIDTH)
        self.minimap.Show(self._overlays_visible and room_for_map)
        self.compass.Show(self._overlays_visible and room_for_map)
        if room_for_map:
            map_size = self.minimap.GetSize()
            self.minimap.SetPosition(wx.Point(width - inset - map_size.width, inset))
            compass_size = self.compass.GetSize()
            self.compass.SetPosition(
                wx.Point(
                    width - inset - compass_size.width,
                    inset + map_size.height + tokens.scaled(8),
                )
            )

        bottom_inset = tokens.scaled(16)
        axes_size = self.axes.GetSize()
        axes_fits = height >= axes_size.height + tokens.scaled(120)
        self.axes.Show(self._overlays_visible and axes_fits)
        if axes_fits:
            self.axes.SetPosition(
                wx.Point(bottom_inset, height - bottom_inset - axes_size.height)
            )

        tools_fit = height >= tokens.scaled(_TOOLS_MIN_HEIGHT)
        tool_top = height - bottom_inset
        for key, _glyph, _label, _hint in reversed(VIEWPORT_TOOLS):
            tool = self.tools[key]
            tool.Show(self._overlays_visible and tools_fit)
            if not tools_fit:
                continue
            size = tool.GetSize()
            tool_top -= size.height
            tool.SetPosition(wx.Point(width - bottom_inset - size.width, tool_top))
            tool_top -= gap

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
    def _on_context_menu(self, event: wx.ContextMenuEvent) -> None:
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
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush(sky_colour(0.5)))
        dc.Clear()
        if width <= 0 or height <= 0:
            return
        if self.has_canvas():
            # The renderer owns every pixel inside the host; painting a sky
            # under it would only flash through during a resize.
            return
        self._paint_sky(dc, width, height)
        gcdc = wx.GCDC(dc)
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
    "DEFAULT_CHUNKS",
    "DEFAULT_FPS",
    "DEFAULT_WORLD",
    "DEFAULT_YAW",
    "GRID_PITCH",
    "HudChip",
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
