"""The one colour picker every colour control in the application opens.

It is built around a **continuous** field rather than a palette of swatches.
That is the whole design: a swatch grid can only ever offer the colours
somebody thought of in advance, so a picker built from one quietly tells the
user that the colour they want is not available.  The saturation/value plane,
the hue strip and the alpha strip here are continuous surfaces; the swatches,
the recents and the eyedropper are conveniences laid on top of that, never a
replacement for it.

Beside the field sits the translator.  Every notation the application can read
is shown at once, live, editable, and copyable, so a value can be typed in
whichever one the person thinks in -- and the arithmetic behind it lives in
:mod:`amulet_map_editor.api.colour`, which imports no ``wx`` and adds no
dependency, so the same conversions are testable without a display.

Three facts are always on screen, because each of them is one somebody can be
wrong about without noticing:

* **which space the value was authored in**, so ``oklch`` is not mistaken for
  ``lch``;
* **whether sRGB can actually show it**, before the clipping happens rather
  than after;
* **the contrast** the colour would give as ink and as a surface, against the
  live theme roles.

The window is shown non-modally.  A picker is not a question the application
must have answered before it can carry on, and a modal one would stop the
surface underneath from repainting while the user compares two colours on it.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Callable, Dict, List, Optional, Tuple

import wx

from amulet_map_editor.api import colour as colour_api
from amulet_map_editor.api import config
from amulet_map_editor.api.colour import Colour
from amulet_map_editor.api.studio import tokens, widgets
from amulet_map_editor.api.studio.search import SearchState

log = logging.getLogger(__name__)

__all__ = [
    "AlphaSlider",
    "ColourPickerDialog",
    "ColourPreview",
    "DraggableControl",
    "HueSlider",
    "Note",
    "PaintedControl",
    "SpectrumField",
    "Surface",
    "legible_ink",
    "open_colour_picker",
    "recent_colours",
    "remember_colour",
]

#: Bounded config record holding the colours the picker has recently returned.
#: Recents are a convenience, so the record is small, self-healing, and never
#: load-bearing: an unreadable one means the row is empty, not that the picker
#: refuses to open.
RECENTS_ID = "amulet_colour_picker"
MAX_RECENTS = 24

#: The plane and the strips are generated as small images and scaled up.  A
#: full-resolution generation in Python costs about forty milliseconds per
#: repaint, which is felt immediately while dragging; these gradients are
#: smooth, so a bilinear upscale from this grid is indistinguishable and about
#: twenty times cheaper.
_PLANE_SAMPLES = (96, 72)
_HUE_SAMPLES = (1, 180)
_ALPHA_SAMPLES = (1, 128)

#: The checkerboard drawn behind anything translucent, so a half-transparent
#: colour is visibly half-transparent rather than merely paler.
_CHECKER_SIZE = 7
_CHECKER_LIGHT = wx.Colour(0xFF, 0xFF, 0xFF)
_CHECKER_DARK = wx.Colour(0xCC, 0xCC, 0xCC)


# ---------------------------------------------------------------------------
# persisted recents
# ---------------------------------------------------------------------------


def recent_colours() -> Tuple[str, ...]:
    """Return the recently chosen colours, newest first, as HEX8 strings."""
    raw = config.get(RECENTS_ID, {})
    if not isinstance(raw, dict):
        return ()
    values = raw.get("recents", ())
    if not isinstance(values, (list, tuple)):
        return ()
    kept: List[str] = []
    for value in list(values)[:MAX_RECENTS]:
        try:
            kept.append(colour_api.format_as(colour_api.parse(str(value)), "hex8"))
        except colour_api.ColourError:
            continue
    return tuple(kept)


def remember_colour(value: str) -> Tuple[str, ...]:
    """Record a chosen colour at the front of the recents, and return them."""
    try:
        text = colour_api.format_as(colour_api.parse(str(value)), "hex8")
    except colour_api.ColourError:
        return recent_colours()
    kept = [text] + [item for item in recent_colours() if item != text]
    try:
        config.put(RECENTS_ID, {"recents": kept[:MAX_RECENTS]})
    except OSError:
        log.exception("Could not persist the colour picker's recent colours")
    return tuple(kept[:MAX_RECENTS])


# ---------------------------------------------------------------------------
# drawing helpers
# ---------------------------------------------------------------------------


def _wx_colour(colour: Colour) -> wx.Colour:
    """Return the clipped sRGB form of a colour as a ``wx.Colour``."""
    red, green, blue = colour_api.to_rgb255(colour)
    return wx.Colour(red, green, blue, round(max(0.0, min(1.0, colour.alpha)) * 255))


def _gradient_bitmap(
    width: int,
    height: int,
    sampler: Callable[[float, float], Tuple[int, int, int, int]],
    samples: Tuple[int, int],
) -> wx.Bitmap:
    """Build a smooth gradient at ``samples`` resolution and scale it up.

    ``sampler`` receives ``(u, v)`` in ``0..1`` and returns eight-bit RGBA.
    Alpha is carried through the scale, which is what lets the alpha strip show
    the checkerboard behind it rather than fading to grey.
    """
    columns = max(1, int(samples[0]))
    rows = max(1, int(samples[1]))
    rgb = bytearray(columns * rows * 3)
    alpha = bytearray(columns * rows)
    index = 0
    for row in range(rows):
        v = row / (rows - 1) if rows > 1 else 0.0
        for column in range(columns):
            u = column / (columns - 1) if columns > 1 else 0.0
            red, green, blue, opacity = sampler(u, v)
            rgb[index * 3] = red
            rgb[index * 3 + 1] = green
            rgb[index * 3 + 2] = blue
            alpha[index] = opacity
            index += 1
    image = wx.Image(columns, rows)
    image.SetData(bytes(rgb))
    image.SetAlpha(bytes(alpha))
    if (columns, rows) != (width, height):
        image = image.Scale(
            max(1, int(width)), max(1, int(height)), wx.IMAGE_QUALITY_BILINEAR
        )
    return wx.Bitmap(image)


def _draw_checkerboard(dc: wx.DC, rect: wx.Rect) -> None:
    """Fill ``rect`` with the transparency checkerboard."""
    dc.SetPen(wx.TRANSPARENT_PEN)
    dc.SetBrush(wx.Brush(_CHECKER_LIGHT))
    dc.DrawRectangle(rect)
    dc.SetBrush(wx.Brush(_CHECKER_DARK))
    step = max(2, tokens.scaled(_CHECKER_SIZE))
    for y in range(rect.y, rect.y + rect.height, step):
        for x in range(rect.x, rect.x + rect.width, step):
            if ((x - rect.x) // step + (y - rect.y) // step) % 2:
                continue
            dc.DrawRectangle(
                x,
                y,
                min(step, rect.x + rect.width - x),
                min(step, rect.y + rect.height - y),
            )


def _draw_marker(dc: wx.DC, x: int, y: int, radius: int) -> None:
    """Draw the two-ring marker that stays visible on any colour underneath."""
    dc.SetBrush(wx.TRANSPARENT_BRUSH)
    dc.SetPen(wx.Pen(wx.Colour(0, 0, 0, 190), 3))
    dc.DrawCircle(x, y, radius + 1)
    dc.SetPen(wx.Pen(wx.Colour(255, 255, 255, 235), 2))
    dc.DrawCircle(x, y, radius)


class PaintedControl(wx.Control):
    """A Studio-styled owner-drawn control that can also render into a bitmap.

    It carries the same contract every painted widget in this shell carries:
    the drawing lives in :meth:`render_to`, so a capture on a hidden desktop
    and the running window take the same route through the same code.  It is
    written here rather than inherited from the Studio widget base because that
    base is private to its module, and reaching into it would make this file
    break the next time it is refactored.
    """

    def __init__(self, parent: wx.Window, name: str, size: wx.Size) -> None:
        super().__init__(parent, style=wx.BORDER_NONE | wx.WANTS_CHARS)
        self.SetName(name)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        try:
            self.SetDoubleBuffered(True)
        except (AttributeError, RuntimeError):  # pragma: no cover - backend
            pass
        self.SetInitialSize(size)
        self.SetMinSize(size)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.Bind(wx.EVT_SET_FOCUS, self._on_focus_change)
        self.Bind(wx.EVT_KILL_FOCUS, self._on_focus_change)

    # -- theme ---------------------------------------------------------------
    def palette(self) -> tokens.StudioPalette:
        return tokens.palette()

    def refresh_theme(self) -> None:
        try:
            self.Refresh()
        except RuntimeError:  # pragma: no cover - window already gone
            pass

    def _backdrop(self) -> wx.Colour:
        parent = self.GetParent()
        backdrop = parent.GetBackgroundColour() if parent else wx.NullColour
        return backdrop if backdrop.IsOk() else self.palette().surface

    # -- painting ------------------------------------------------------------
    def render_to(self, dc: wx.DC, rect: wx.Rect) -> None:
        """Draw this control's whole appearance into ``dc`` at ``rect``."""
        with widgets.translated(dc, rect):
            local = wx.Rect(0, 0, rect.width, rect.height)
            dc.SetBrush(wx.Brush(self._backdrop()))
            dc.SetPen(wx.TRANSPARENT_PEN)
            dc.DrawRectangle(local)
            self.draw(dc, local)

    def draw(self, dc: wx.DC, rect: wx.Rect) -> None:
        """Draw the control's own shape.  Overridden by every subclass."""

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        dc, gcdc = widgets.paint_context(self, self._backdrop())
        width, height = self.GetClientSize()
        self.render_to(gcdc, wx.Rect(0, 0, width, height))
        del gcdc

    def _on_focus_change(self, event: wx.FocusEvent) -> None:
        self.Refresh()
        event.Skip()

    def AcceptsFocusFromKeyboard(self) -> bool:  # noqa: N802 - wx API spelling
        return True


class DraggableControl(PaintedControl):
    """A painted control operated by dragging, arrow keys, or both."""

    def __init__(self, parent: wx.Window, name: str, size: wx.Size) -> None:
        super().__init__(parent, name, size)
        self._dragging = False
        self.Bind(wx.EVT_LEFT_DOWN, self._on_press)
        self.Bind(wx.EVT_LEFT_UP, self._on_release)
        self.Bind(wx.EVT_MOTION, self._on_motion)
        self.Bind(wx.EVT_MOUSE_CAPTURE_LOST, self._on_capture_lost)
        self.Bind(wx.EVT_KEY_DOWN, self._on_key)

    def _on_press(self, event: wx.MouseEvent) -> None:
        self.SetFocus()
        if not self.HasCapture():
            self.CaptureMouse()
        self._dragging = True
        self.point_at(event.GetPosition())

    def _on_motion(self, event: wx.MouseEvent) -> None:
        if self._dragging and event.Dragging():
            self.point_at(event.GetPosition())
        event.Skip()

    def _release(self) -> None:
        self._dragging = False
        if self.HasCapture():
            self.ReleaseMouse()

    def _on_release(self, _event: wx.MouseEvent) -> None:
        self._release()

    def _on_capture_lost(self, _event: wx.MouseCaptureLostEvent) -> None:
        self._dragging = False

    def _on_key(self, event: wx.KeyEvent) -> None:
        if not self.nudge(event.GetKeyCode(), event.ShiftDown()):
            event.Skip()

    def point_at(self, position: wx.Point) -> None:
        """Set the value from a pointer position.  Overridden per control."""

    def nudge(self, key: int, coarse: bool) -> bool:
        """Adjust the value from an arrow key; return whether it was handled."""
        return False


class SpectrumField(DraggableControl):
    """The continuous saturation/value plane for the current hue.

    This is the control the picker exists for.  Horizontal is saturation,
    vertical is value, and every point on it is reachable -- with a pointer by
    dragging, and from the keyboard with the arrow keys, one percent at a time
    or ten with Shift held.
    """

    def __init__(
        self,
        parent: wx.Window,
        *,
        on_change: Optional[Callable[[float, float], None]] = None,
    ) -> None:
        super().__init__(
            parent,
            "Colour spectrum, saturation and value",
            wx.Size(tokens.scaled(300), tokens.scaled(210)),
        )
        self.hue = 0.0
        self.saturation = 1.0
        self.value = 1.0
        self.on_change = on_change
        self._cache: Optional[Tuple[Tuple[int, int, int], wx.Bitmap]] = None

    def set_hsv(self, hue: float, saturation: float, value: float) -> None:
        """Move the marker and, when the hue changed, rebuild the plane."""
        self.hue = float(hue) % 360.0
        self.saturation = max(0.0, min(1.0, float(saturation)))
        self.value = max(0.0, min(1.0, float(value)))
        self.SetName(
            f"Colour spectrum · saturation {self.saturation * 100:.0f}% · "
            f"value {self.value * 100:.0f}% · hue {self.hue:.0f} degrees"
        )
        self.Refresh()

    def _plane(self, width: int, height: int) -> wx.Bitmap:
        key = (round(self.hue), width, height)
        if self._cache is not None and self._cache[0] == key:
            return self._cache[1]

        hue = self.hue

        def sampler(u: float, v: float) -> Tuple[int, int, int, int]:
            red, green, blue = colour_api.to_rgb255(
                colour_api.from_hsv(hue, u, 1.0 - v)
            )
            return red, green, blue, 255

        bitmap = _gradient_bitmap(width, height, sampler, _PLANE_SAMPLES)
        self._cache = (key, bitmap)
        return bitmap

    def point_at(self, position: wx.Point) -> None:
        width, height = self.GetClientSize()
        if width < 2 or height < 2:
            return
        saturation = max(0.0, min(1.0, position.x / (width - 1)))
        value = 1.0 - max(0.0, min(1.0, position.y / (height - 1)))
        self.set_hsv(self.hue, saturation, value)
        widgets.invoke(self.on_change, saturation, value)

    def nudge(self, key: int, coarse: bool) -> bool:
        step = 0.1 if coarse else 0.01
        saturation, value = self.saturation, self.value
        if key == wx.WXK_LEFT:
            saturation -= step
        elif key == wx.WXK_RIGHT:
            saturation += step
        elif key == wx.WXK_UP:
            value += step
        elif key == wx.WXK_DOWN:
            value -= step
        else:
            return False
        saturation = max(0.0, min(1.0, saturation))
        value = max(0.0, min(1.0, value))
        self.set_hsv(self.hue, saturation, value)
        widgets.invoke(self.on_change, saturation, value)
        return True

    def draw(self, dc: wx.DC, rect: wx.Rect) -> None:
        palette = self.palette()
        if rect.width < 2 or rect.height < 2:
            return
        dc.DrawBitmap(self._plane(rect.width, rect.height), rect.x, rect.y, True)
        tokens.draw_round_rect(
            dc, rect, tokens.scaled(2), None, palette.outline_variant
        )
        _draw_marker(
            dc,
            rect.x + round(self.saturation * (rect.width - 1)),
            rect.y + round((1.0 - self.value) * (rect.height - 1)),
            tokens.scaled(7),
        )
        if self.HasFocus():
            widgets.draw_focus_ring(dc, rect, tokens.scaled(2), palette.primary)


class HueSlider(DraggableControl):
    """The continuous hue strip, zero to three hundred and sixty degrees."""

    def __init__(
        self, parent: wx.Window, *, on_change: Optional[Callable[[float], None]] = None
    ) -> None:
        super().__init__(parent, "Hue", wx.Size(tokens.scaled(26), tokens.scaled(210)))
        self.hue = 0.0
        self.on_change = on_change
        self._cache: Optional[Tuple[Tuple[int, int], wx.Bitmap]] = None

    def set_hue(self, hue: float) -> None:
        self.hue = float(hue) % 360.0
        self.SetName(f"Hue · {self.hue:.0f} degrees")
        self.Refresh()

    def _strip(self, width: int, height: int) -> wx.Bitmap:
        key = (width, height)
        if self._cache is not None and self._cache[0] == key:
            return self._cache[1]

        def sampler(_u: float, v: float) -> Tuple[int, int, int, int]:
            red, green, blue = colour_api.to_rgb255(
                colour_api.from_hsv(v * 360.0, 1.0, 1.0)
            )
            return red, green, blue, 255

        bitmap = _gradient_bitmap(width, height, sampler, _HUE_SAMPLES)
        self._cache = (key, bitmap)
        return bitmap

    def point_at(self, position: wx.Point) -> None:
        _width, height = self.GetClientSize()
        if height < 2:
            return
        hue = max(0.0, min(1.0, position.y / (height - 1))) * 360.0
        self.set_hue(hue)
        widgets.invoke(self.on_change, self.hue)

    def nudge(self, key: int, coarse: bool) -> bool:
        step = 15.0 if coarse else 1.0
        if key in (wx.WXK_UP, wx.WXK_LEFT):
            self.set_hue(self.hue - step)
        elif key in (wx.WXK_DOWN, wx.WXK_RIGHT):
            self.set_hue(self.hue + step)
        else:
            return False
        widgets.invoke(self.on_change, self.hue)
        return True

    def draw(self, dc: wx.DC, rect: wx.Rect) -> None:
        palette = self.palette()
        if rect.width < 2 or rect.height < 2:
            return
        dc.DrawBitmap(self._strip(rect.width, rect.height), rect.x, rect.y, True)
        tokens.draw_round_rect(
            dc, rect, tokens.scaled(2), None, palette.outline_variant
        )
        y = rect.y + round((self.hue / 360.0) * (rect.height - 1))
        dc.SetBrush(wx.TRANSPARENT_BRUSH)
        dc.SetPen(wx.Pen(wx.Colour(0, 0, 0, 190), 3))
        dc.DrawRectangle(rect.x - 1, y - 3, rect.width + 2, 7)
        dc.SetPen(wx.Pen(wx.Colour(255, 255, 255, 235), 1))
        dc.DrawRectangle(rect.x, y - 2, rect.width, 5)
        if self.HasFocus():
            widgets.draw_focus_ring(dc, rect, tokens.scaled(2), palette.primary)


class AlphaSlider(DraggableControl):
    """The continuous alpha strip, drawn over the transparency checkerboard."""

    def __init__(
        self, parent: wx.Window, *, on_change: Optional[Callable[[float], None]] = None
    ) -> None:
        super().__init__(
            parent, "Alpha", wx.Size(tokens.scaled(26), tokens.scaled(210))
        )
        self.alpha = 1.0
        self.base = Colour(0.0, 0.0, 0.0, 1.0)
        self.on_change = on_change
        self._cache: Optional[Tuple[Tuple[int, int, int], wx.Bitmap]] = None

    def set_alpha(self, alpha: float, base: Optional[Colour] = None) -> None:
        self.alpha = max(0.0, min(1.0, float(alpha)))
        if base is not None:
            self.base = base
        self.SetName(f"Alpha · {self.alpha * 100:.0f}%")
        self.Refresh()

    def _strip(self, width: int, height: int) -> wx.Bitmap:
        red, green, blue = colour_api.to_rgb255(self.base)
        key = (width, height, red << 16 | green << 8 | blue)
        if self._cache is not None and self._cache[0] == key:
            return self._cache[1]

        def sampler(_u: float, v: float) -> Tuple[int, int, int, int]:
            return red, green, blue, round((1.0 - v) * 255)

        bitmap = _gradient_bitmap(width, height, sampler, _ALPHA_SAMPLES)
        self._cache = (key, bitmap)
        return bitmap

    def point_at(self, position: wx.Point) -> None:
        _width, height = self.GetClientSize()
        if height < 2:
            return
        alpha = 1.0 - max(0.0, min(1.0, position.y / (height - 1)))
        self.set_alpha(alpha)
        widgets.invoke(self.on_change, self.alpha)

    def nudge(self, key: int, coarse: bool) -> bool:
        step = 0.1 if coarse else 0.01
        if key in (wx.WXK_UP, wx.WXK_RIGHT):
            self.set_alpha(self.alpha + step)
        elif key in (wx.WXK_DOWN, wx.WXK_LEFT):
            self.set_alpha(self.alpha - step)
        else:
            return False
        widgets.invoke(self.on_change, self.alpha)
        return True

    def draw(self, dc: wx.DC, rect: wx.Rect) -> None:
        palette = self.palette()
        if rect.width < 2 or rect.height < 2:
            return
        _draw_checkerboard(dc, rect)
        dc.DrawBitmap(self._strip(rect.width, rect.height), rect.x, rect.y, True)
        tokens.draw_round_rect(
            dc, rect, tokens.scaled(2), None, palette.outline_variant
        )
        y = rect.y + round((1.0 - self.alpha) * (rect.height - 1))
        dc.SetBrush(wx.TRANSPARENT_BRUSH)
        dc.SetPen(wx.Pen(wx.Colour(0, 0, 0, 190), 3))
        dc.DrawRectangle(rect.x - 1, y - 3, rect.width + 2, 7)
        dc.SetPen(wx.Pen(wx.Colour(255, 255, 255, 235), 1))
        dc.DrawRectangle(rect.x, y - 2, rect.width, 5)
        if self.HasFocus():
            widgets.draw_focus_ring(dc, rect, tokens.scaled(2), palette.primary)


class ColourPreview(PaintedControl):
    """The colour as it stands beside the colour it started as.

    Both halves sit on the transparency checkerboard, so an alpha change is
    visible as transparency rather than as a lighter shade of the same colour.
    """

    def __init__(self, parent: wx.Window) -> None:
        super().__init__(
            parent, "Colour preview", wx.Size(tokens.scaled(120), tokens.scaled(56))
        )
        self.current = Colour(0.0, 0.0, 0.0, 1.0)
        self.original = Colour(0.0, 0.0, 0.0, 1.0)

    def set_colours(self, current: Colour, original: Colour) -> None:
        self.current = current
        self.original = original
        self.SetName(
            "Colour preview · now "
            f"{colour_api.format_as(current, 'hex8')} · was "
            f"{colour_api.format_as(original, 'hex8')}"
        )
        self.Refresh()

    def draw(self, dc: wx.DC, rect: wx.Rect) -> None:
        palette = self.palette()
        half = rect.width // 2
        left = wx.Rect(rect.x, rect.y, half, rect.height)
        right = wx.Rect(rect.x + half, rect.y, rect.width - half, rect.height)
        _draw_checkerboard(dc, rect)
        dc.SetPen(wx.TRANSPARENT_PEN)
        dc.SetBrush(wx.Brush(_wx_colour(self.original)))
        dc.DrawRectangle(left)
        dc.SetBrush(wx.Brush(_wx_colour(self.current)))
        dc.DrawRectangle(right)
        tokens.draw_round_rect(dc, rect, tokens.scaled(3), None, palette.outline)
        dc.SetFont(tokens.font_px(self, widgets.point_size(10)))
        dc.SetTextForeground(legible_ink(self.original))
        dc.DrawText("was", left.x + tokens.scaled(6), left.y + tokens.scaled(5))
        dc.SetTextForeground(legible_ink(self.current))
        dc.DrawText("now", right.x + tokens.scaled(6), right.y + tokens.scaled(5))


def legible_ink(colour: Colour) -> wx.Colour:
    """Return black or white, whichever is legible on ``colour``."""
    opaque = colour_api.composite(colour, Colour(1.0, 1.0, 1.0, 1.0))
    return (
        wx.Colour(0, 0, 0)
        if colour_api.relative_luminance(opaque) > 0.42
        else wx.Colour(255, 255, 255)
    )


class Surface(wx.Panel):
    """A panel that paints the Studio surface role and can render into a bitmap.

    A ``wx.Panel`` left to its own devices contributes nothing to a capture on
    a hidden desktop, because there is no composited surface to read and it has
    no drawing of its own to ask for.  Painting the role explicitly means the
    window behind the controls is real in the picture as well as on screen.
    """

    def __init__(self, parent: wx.Window, *, role: str = "surface") -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self.role = role
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        try:
            self.SetDoubleBuffered(True)
        except (AttributeError, RuntimeError):  # pragma: no cover - backend
            pass
        self.SetBackgroundColour(tokens.palette().role(role))
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)

    def refresh_theme(self) -> None:
        self.SetBackgroundColour(tokens.palette().role(self.role))
        for child in self.GetChildren():
            refresh = getattr(child, "refresh_theme", None)
            if callable(refresh):
                refresh()
        self.Refresh()

    def render_to(self, dc: wx.DC, rect: wx.Rect) -> None:
        dc.SetBrush(wx.Brush(tokens.palette().role(self.role)))
        dc.SetPen(wx.TRANSPARENT_PEN)
        dc.DrawRectangle(rect)

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        dc, gcdc = widgets.paint_context(self, palette.role(self.role))
        width, height = self.GetClientSize()
        self.render_to(gcdc, wx.Rect(0, 0, width, height))
        del gcdc


class Note(PaintedControl):
    """A wrapped, owner-drawn line of explanatory copy.

    Studio has no static text primitive that paints itself, and a native
    ``wx.StaticText`` disappears from a capture on a hidden desktop, so the
    gamut warning and the contrast reading -- the two things this window says
    that nothing else in the interface says -- would be missing from every
    screenshot of it.
    """

    def __init__(
        self,
        parent: wx.Window,
        text: str = "",
        *,
        role: str = "on_surface_variant",
        size_px: int = 12,
        name: str = "",
        width: int = 280,
    ) -> None:
        self.text = str(text)
        self.role = role
        self.size_px = size_px
        self.natural_width = int(width)
        super().__init__(
            parent, name or self.text or "Note", wx.Size(tokens.scaled(width), -1)
        )

    def set_text(self, text: str, *, role: Optional[str] = None) -> None:
        self.text = str(text)
        if role is not None:
            self.role = role
        self.SetName(self.text or "Note")
        self.InvalidateBestSize()
        self.Refresh()

    def AcceptsFocus(self) -> bool:  # noqa: N802 - wx API spelling
        return False

    def AcceptsFocusFromKeyboard(self) -> bool:  # noqa: N802 - wx API spelling
        return False

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        width = max(
            tokens.scaled(40),
            self.GetSize().width or tokens.scaled(self.natural_width),
        )
        with widgets.measuring(self) as dc:
            dc.SetFont(tokens.font_px(self, widgets.point_size(self.size_px)))
            lines = widgets.wrap_text(dc, self.text or " ", width, max_lines=6)
            return wx.Size(width, max(1, len(lines)) * dc.GetCharHeight())

    def draw(self, dc: wx.DC, rect: wx.Rect) -> None:
        dc.SetFont(tokens.font_px(self, widgets.point_size(self.size_px)))
        dc.SetTextForeground(self.palette().role(self.role))
        y = rect.y
        for line in widgets.wrap_text(dc, self.text, rect.width, max_lines=6):
            dc.DrawText(line, rect.x, y)
            y += dc.GetCharHeight()


# ---------------------------------------------------------------------------
# the window
# ---------------------------------------------------------------------------

#: Theme roles offered as ready-made swatches and as contrast targets.  They
#: are read from the live palette rather than hard-coded, so the picker offers
#: the colours the application is actually painted with right now.
_ROLE_SWATCHES: Tuple[Tuple[str, str], ...] = (
    ("surface", "Surface"),
    ("surface_container", "Surface container"),
    ("surface_container_high", "Surface container high"),
    ("on_surface", "On surface"),
    ("on_surface_variant", "On surface variant"),
    ("outline", "Outline"),
    ("primary", "Primary"),
    ("on_primary", "On primary"),
    ("primary_container", "Primary container"),
    ("on_primary_container", "On primary container"),
    ("error", "Error"),
)


class ColourPickerDialog(wx.Dialog):
    """The continuous picker, its translator, and its readings.

    Shown non-modally: ``on_apply`` receives the chosen colour as a HEX8 string
    when the user confirms, and nothing is called when they cancel.  The window
    returns focus to whatever opened it on either path.
    """

    def __init__(
        self,
        parent: wx.Window,
        value: str = "#6750A4",
        *,
        on_apply: Optional[Callable[[str], None]] = None,
        title: str = "Colour",
        subject: str = "Appearance",
    ) -> None:
        super().__init__(
            parent,
            title=title,
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
            name=f"{subject}: {title}",
        )
        try:
            self.colour = colour_api.parse(value)
        except colour_api.ColourError:
            self.colour = Colour(0.404, 0.314, 0.643, 1.0, "hex")
        self.original = self.colour
        self.on_apply = on_apply
        self._opener = wx.Window.FindFocus()
        self._focus_returned = False
        self._updating = False
        self._sampling = False
        self._theme_unsubscribe = tokens.register_theme_listener(self.refresh_theme)
        self.search = SearchState(label="Colour representations")
        self.contrast_role = "surface"

        self.root = Surface(self)
        header = self._build_header()
        body = self._build_body()
        footer = self._build_footer()

        layout = wx.BoxSizer(wx.VERTICAL)
        layout.Add(header, 0, wx.EXPAND)
        layout.Add(body, 1, wx.EXPAND)
        layout.Add(footer, 0, wx.EXPAND)
        self.root.SetSizer(layout)

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(self.root, 1, wx.EXPAND)
        self.SetSizer(outer)
        self.SetMinSize(wx.Size(tokens.scaled(640), tokens.scaled(600)))
        self.SetSize(wx.Size(tokens.scaled(700), tokens.scaled(760)))

        self.Bind(wx.EVT_CLOSE, self._on_close)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
        self.Bind(wx.EVT_LEFT_DOWN, self._on_sample_click)
        self._sync(source="init")

    # -- construction --------------------------------------------------------
    def _build_header(self) -> wx.Window:
        header = Surface(self.root, role="surface_container")
        self.title_label = Note(
            header, "Colour", role="on_surface", size_px=22, name="Colour"
        )
        self.eyebrow = Note(header, "Appearance", role="primary", size_px=11)
        self.search_bar = widgets.SearchBar(
            header,
            "Search representations",
            self.search,
            on_change=self._on_search,
            compact=True,
        )
        close = widgets.StudioButton(
            header,
            "✕",
            variant="icon",
            on_click=self.cancel,
            name="Close the colour picker",
            hint="Close the colour picker",
            height=30,
            min_width=34,
        )
        titles = wx.BoxSizer(wx.VERTICAL)
        titles.Add(self.eyebrow, 0, wx.EXPAND | wx.BOTTOM, tokens.scaled(4))
        titles.Add(self.title_label, 0, wx.EXPAND)
        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(titles, 1, wx.ALIGN_CENTER_VERTICAL)
        row.Add(self.search_bar, 0, wx.ALIGN_CENTER_VERTICAL)
        row.Add(close, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, tokens.scaled(8))
        padded = wx.BoxSizer(wx.VERTICAL)
        padded.Add(row, 0, wx.EXPAND | wx.ALL, tokens.scaled(16))
        header.SetSizer(padded)
        return header

    def _build_body(self) -> wx.Window:
        body = wx.ScrolledWindow(self.root, style=wx.VSCROLL | wx.TAB_TRAVERSAL)
        body.SetScrollRate(0, tokens.scaled(12))
        body.SetBackgroundColour(tokens.palette().surface)
        self.body = body
        sizer = wx.BoxSizer(wx.VERTICAL)

        # -- the continuous picker, which is the point of the window ---------
        self.spectrum = SpectrumField(body, on_change=self._on_spectrum)
        self.hue_slider = HueSlider(body, on_change=self._on_hue)
        self.alpha_slider = AlphaSlider(body, on_change=self._on_alpha)
        picker_row = wx.BoxSizer(wx.HORIZONTAL)
        picker_row.Add(self.spectrum, 1, wx.EXPAND)
        picker_row.Add(self.hue_slider, 0, wx.EXPAND | wx.LEFT, tokens.scaled(12))
        picker_row.Add(self.alpha_slider, 0, wx.EXPAND | wx.LEFT, tokens.scaled(12))
        sizer.Add(picker_row, 0, wx.EXPAND | wx.ALL, tokens.scaled(16))

        # -- what the value currently is, and what it costs -------------------
        self.preview = ColourPreview(body)
        self.space_note = Note(body, "", role="on_surface", size_px=13)
        self.gamut_note = Note(body, "", size_px=12)
        readings = wx.BoxSizer(wx.VERTICAL)
        readings.Add(self.space_note, 0, wx.EXPAND | wx.BOTTOM, tokens.scaled(4))
        readings.Add(self.gamut_note, 0, wx.EXPAND)
        reading_row = wx.BoxSizer(wx.HORIZONTAL)
        reading_row.Add(self.preview, 0)
        reading_row.Add(readings, 1, wx.LEFT, tokens.scaled(12))
        sizer.Add(
            reading_row,
            0,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            tokens.scaled(16),
        )

        # -- contrast, against a role the user picks --------------------------
        sizer.Add(
            widgets.SectionLabel(body, "Contrast"),
            0,
            wx.LEFT | wx.RIGHT | wx.BOTTOM,
            tokens.scaled(16),
        )
        self.contrast_choice = widgets.SearchableChoice(
            body,
            "Compare against",
            [label for _role, label in _ROLE_SWATCHES],
            "Surface",
            on_change=self._on_contrast_role,
        )
        self.contrast_ink = Note(body, "", size_px=12)
        self.contrast_surface = Note(body, "", size_px=12)
        contrast_box = wx.BoxSizer(wx.VERTICAL)
        contrast_box.Add(
            self.contrast_choice, 0, wx.EXPAND | wx.BOTTOM, tokens.scaled(8)
        )
        contrast_box.Add(self.contrast_ink, 0, wx.EXPAND | wx.BOTTOM, tokens.scaled(2))
        contrast_box.Add(self.contrast_surface, 0, wx.EXPAND)
        sizer.Add(
            contrast_box,
            0,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            tokens.scaled(16),
        )

        # -- conveniences: swatches, recents, eyedropper ----------------------
        sizer.Add(
            widgets.SectionLabel(body, "Swatches, recents, and the eyedropper"),
            0,
            wx.LEFT | wx.RIGHT | wx.BOTTOM,
            tokens.scaled(16),
        )
        sizer.Add(
            Note(
                body,
                "These are shortcuts to colours already in play. Everything they "
                "offer is reachable on the continuous field above, which is never "
                "limited to a list.",
                size_px=11,
            ),
            0,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            tokens.scaled(16),
        )
        palette = tokens.palette()
        swatch_row = wx.WrapSizer(wx.HORIZONTAL, wx.REMOVE_LEADING_SPACES)
        for role, label in _ROLE_SWATCHES:
            swatch_row.Add(
                widgets.Swatch(
                    body,
                    palette.role(role),
                    name=f"{label} theme colour",
                    on_click=self._on_swatch,
                    size=30,
                ),
                0,
                wx.RIGHT | wx.BOTTOM,
                tokens.scaled(6),
            )
        sizer.Add(
            swatch_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, tokens.scaled(16)
        )

        self.recents_holder = Surface(body)
        self.recents_sizer = wx.WrapSizer(wx.HORIZONTAL, wx.REMOVE_LEADING_SPACES)
        self.recents_holder.SetSizer(self.recents_sizer)
        sizer.Add(
            self.recents_holder,
            0,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            tokens.scaled(16),
        )
        self.recents_note = Note(body, "", size_px=11)
        sizer.Add(
            self.recents_note,
            0,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            tokens.scaled(16),
        )

        self.eyedropper_button = widgets.StudioButton(
            body,
            "Eyedropper",
            variant="outlined",
            on_click=self._begin_sampling,
            name="Sample a colour from the screen",
            hint="Then click anywhere to sample the pixel under the pointer",
        )
        self.status_note = Note(body, "", size_px=11)
        tool_row = wx.BoxSizer(wx.HORIZONTAL)
        tool_row.Add(self.eyedropper_button, 0, wx.RIGHT, tokens.scaled(12))
        tool_row.Add(self.status_note, 1, wx.ALIGN_CENTER_VERTICAL)
        sizer.Add(
            tool_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, tokens.scaled(16)
        )

        # -- the translator ---------------------------------------------------
        sizer.Add(
            widgets.SectionLabel(body, "Translator"),
            0,
            wx.LEFT | wx.RIGHT | wx.BOTTOM,
            tokens.scaled(16),
        )
        self.translator_rows: Dict[
            str, Tuple[wx.Window, widgets.OutlinedField, Note]
        ] = {}
        self.translator_sizer = wx.BoxSizer(wx.VERTICAL)
        for key in colour_api.REPRESENTATIONS:
            label, explanation = colour_api.REPRESENTATION_LABELS[key]
            holder = Surface(body)
            field = widgets.OutlinedField(
                holder,
                label,
                "",
                placeholder=explanation,
                mono=True,
                on_change=lambda text, name=key: self._on_typed(name, text),
            )
            copy_button = widgets.StudioButton(
                holder,
                "Copy",
                variant="text",
                on_click=lambda name=key: self._copy(name),
                name=f"Copy the {label} value",
                hint=f"Copy the {label} value to the clipboard",
            )
            note = Note(holder, explanation, size_px=11)
            row = wx.BoxSizer(wx.HORIZONTAL)
            row.Add(field, 1, wx.ALIGN_CENTER_VERTICAL)
            row.Add(
                copy_button, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, tokens.scaled(8)
            )
            column = wx.BoxSizer(wx.VERTICAL)
            column.Add(row, 0, wx.EXPAND)
            column.Add(note, 0, wx.EXPAND | wx.BOTTOM, tokens.scaled(6))
            holder.SetSizer(column)
            self.translator_rows[key] = (holder, field, note)
            self.translator_sizer.Add(holder, 0, wx.EXPAND)
        sizer.Add(
            self.translator_sizer,
            0,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            tokens.scaled(16),
        )
        self.empty_note = Note(body, "", size_px=12)
        sizer.Add(
            self.empty_note,
            0,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            tokens.scaled(16),
        )

        body.SetSizer(sizer)
        return body

    def _build_footer(self) -> wx.Window:
        footer = Surface(self.root, role="surface_container")
        reset = widgets.StudioButton(
            footer,
            "Reset",
            variant="text",
            on_click=self.reset,
            name="Reset to the colour this opened with",
        )
        cancel = widgets.StudioButton(
            footer, "Cancel", variant="outlined", on_click=self.cancel, name="Cancel"
        )
        confirm = widgets.StudioButton(
            footer,
            "Use this colour",
            variant="filled",
            on_click=self.confirm,
            name="Use this colour",
        )
        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(reset, 0)
        row.AddStretchSpacer(1)
        row.Add(cancel, 0, wx.RIGHT, tokens.scaled(8))
        row.Add(confirm, 0)
        padded = wx.BoxSizer(wx.VERTICAL)
        padded.Add(row, 0, wx.EXPAND | wx.ALL, tokens.scaled(16))
        footer.SetSizer(padded)
        return footer

    # -- state ---------------------------------------------------------------
    def set_colour(self, colour: Colour, *, source: str = "") -> None:
        """Replace the current colour and refresh everything that shows it."""
        self.colour = colour
        self._sync(source=source)

    def _sync(self, *, source: str = "") -> None:
        """Push the current colour into every control that displays it.

        ``source`` names the control the change came from, so that control is
        left alone: rewriting a field's text while somebody is typing in it
        moves the caret to the end of the line on every keystroke.
        """
        if self._updating:
            return
        self._updating = True
        try:
            shown = colour_api.clipped(self.colour)
            hue, saturation, value = colour_api.to_hsv(shown)
            if source not in ("spectrum", "hue"):
                self.spectrum.set_hsv(hue, saturation, value)
            if source != "hue":
                self.hue_slider.set_hue(hue)
            if source != "alpha":
                self.alpha_slider.set_alpha(self.colour.alpha, shown.with_alpha(1.0))
            else:
                self.alpha_slider.base = shown.with_alpha(1.0)
            self.preview.set_colours(self.colour, self.original)

            report = colour_api.gamut(self.colour)
            name = colour_api.name_of(self.colour)
            nearest, distance = colour_api.nearest_name(self.colour)
            named = (
                f"named {name}"
                if name
                else f"no exact CSS name · nearest is {nearest}, {distance:.0f}/255 away"
            )
            self.space_note.set_text(
                f"Active space: {self.colour.space} · alpha "
                f"{self.colour.alpha * 100:.0f}% · {named}"
            )
            self.gamut_note.set_text(
                report.message,
                role="on_surface_variant" if report.in_gamut else "error",
            )

            self._sync_contrast()
            self._sync_translator(source)
            self._sync_recents()
            self.body.Layout()
            self.body.FitInside()
        finally:
            self._updating = False

    def _sync_contrast(self) -> None:
        palette = tokens.palette()
        role = self.contrast_role
        wx_role = palette.role(role)
        other = Colour(
            wx_role.Red() / 255.0, wx_role.Green() / 255.0, wx_role.Blue() / 255.0, 1.0
        )
        label = dict(_ROLE_SWATCHES).get(role, role)
        as_ink = colour_api.contrast_report(self.colour, other)
        as_surface = colour_api.contrast_report(other, colour_api.clipped(self.colour))
        self.contrast_ink.set_text(
            f"As ink on {label}: {as_ink.summary}",
            role="on_surface_variant" if as_ink.passes_aa_normal else "error",
        )
        self.contrast_surface.set_text(
            f"As a surface under {label}: {as_surface.summary}",
            role=("on_surface_variant" if as_surface.passes_aa_normal else "error"),
        )

    def _sync_translator(self, source: str) -> None:
        query_matches = self._matches
        written = colour_api.translate(self.colour)
        for key, (holder, field, note) in self.translator_rows.items():
            label, explanation = colour_api.REPRESENTATION_LABELS[key]
            text = written[key]
            if source != f"field:{key}":
                if key == "name" and not text:
                    field.set_value("")
                    note.set_text(
                        "No CSS keyword matches this colour exactly, so there is "
                        "nothing honest to write here."
                    )
                else:
                    field.set_value(text)
                    note.set_text(explanation)
            visible = query_matches(f"{label} {key} {text} {explanation}")
            holder.Show(visible)
        matched = sum(
            1
            for holder, _field, _note in self.translator_rows.values()
            if holder.IsShown()
        )
        self.empty_note.set_text(
            ""
            if matched
            else f"No representation matches {self.search.query!r}. "
            "Clear the search to see all fourteen."
        )

    def _matches(self, haystack: str) -> bool:
        query = (self.search.query or "").strip()
        if not query:
            return True
        return bool(self.search.matches(haystack))

    def _sync_recents(self) -> None:
        self.recents_sizer.Clear(True)
        values = recent_colours()
        for value in values:
            try:
                parsed = colour_api.parse(value)
            except colour_api.ColourError:
                continue
            self.recents_sizer.Add(
                widgets.Swatch(
                    self.recents_holder,
                    _wx_colour(parsed),
                    name=f"Recent colour {value}",
                    on_click=lambda _colour, text=value: self._on_recent(text),
                    size=26,
                ),
                0,
                wx.RIGHT | wx.BOTTOM,
                tokens.scaled(6),
            )
        self.recents_note.set_text(
            f"{len(values)} recent colour(s)."
            if values
            else "No colours have been chosen here yet, so there are no recents to offer."
        )
        self.recents_holder.Layout()

    # -- events --------------------------------------------------------------
    def _on_search(self, _state: SearchState) -> None:
        self._sync(source="search")

    def _on_spectrum(self, saturation: float, value: float) -> None:
        hue = self.hue_slider.hue
        self.set_colour(
            replace(
                colour_api.from_hsv(hue, saturation, value, self.colour.alpha),
                space="hsv",
            ),
            source="spectrum",
        )

    def _on_hue(self, hue: float) -> None:
        self.spectrum.set_hsv(hue, self.spectrum.saturation, self.spectrum.value)
        self.set_colour(
            replace(
                colour_api.from_hsv(
                    hue,
                    self.spectrum.saturation,
                    self.spectrum.value,
                    self.colour.alpha,
                ),
                space="hsv",
            ),
            source="hue",
        )

    def _on_alpha(self, alpha: float) -> None:
        self.set_colour(self.colour.with_alpha(alpha), source="alpha")

    def _on_contrast_role(self, label: str) -> None:
        for role, name in _ROLE_SWATCHES:
            if name == label:
                self.contrast_role = role
                break
        self._sync(source="contrast")

    def _on_swatch(self, colour: wx.Colour) -> None:
        self.set_colour(
            colour_api.from_rgb255(
                colour.Red(), colour.Green(), colour.Blue(), colour.Alpha() / 255.0
            ),
            source="swatch",
        )

    def _on_recent(self, value: str) -> None:
        try:
            self.set_colour(colour_api.parse(value), source="recent")
        except colour_api.ColourError:
            self.status_note.set_text(
                f"The recent value {value!r} could not be read and was skipped.",
                role="error",
            )

    def _on_typed(self, key: str, text: str) -> None:
        if self._updating:
            return
        _holder, _field, note = self.translator_rows[key]
        label, explanation = colour_api.REPRESENTATION_LABELS[key]
        if not str(text).strip():
            note.set_text(f"{label} is empty; type a value or use the field above.")
            return
        try:
            parsed = colour_api.parse(text)
        except colour_api.ColourError as error:
            note.set_text(str(error), role="error")
            return
        note.set_text(explanation)
        self.set_colour(parsed, source=f"field:{key}")

    def _copy(self, key: str) -> None:
        text = colour_api.format_as(self.colour, key)
        label = colour_api.REPRESENTATION_LABELS[key][0]
        if not text:
            self.status_note.set_text(
                f"There is no {label} value to copy: this colour has no exact CSS name.",
                role="error",
            )
            return
        if not wx.TheClipboard.Open():
            self.status_note.set_text(
                "The clipboard could not be opened, so nothing was copied.",
                role="error",
            )
            return
        try:
            wx.TheClipboard.SetData(wx.TextDataObject(text))
            wx.TheClipboard.Flush()
        finally:
            wx.TheClipboard.Close()
        self.status_note.set_text(f"Copied the {label} value: {text}")

    # -- eyedropper ----------------------------------------------------------
    def _begin_sampling(self) -> None:
        """Arm the eyedropper: the next click anywhere samples that pixel."""
        if self._sampling:
            return
        try:
            self.CaptureMouse()
        except (RuntimeError, wx.wxAssertionError):
            self.status_note.set_text(
                "The pointer could not be captured, so the eyedropper is "
                "unavailable on this display. Every colour it could reach is "
                "still reachable on the field above.",
                role="error",
            )
            return
        self._sampling = True
        self.status_note.set_text(
            "Eyedropper armed: click anywhere to sample the pixel under the pointer."
        )

    def _on_sample_click(self, event: wx.MouseEvent) -> None:
        if not self._sampling:
            event.Skip()
            return
        self._end_sampling()
        position = wx.GetMousePosition()
        try:
            screen = wx.ScreenDC()
            result = screen.GetPixel(position.x, position.y)
        except (RuntimeError, wx.wxAssertionError):
            self.status_note.set_text(
                "This display would not report the pixel under the pointer, so "
                "nothing was sampled.",
                role="error",
            )
            return
        sampled = result[1] if isinstance(result, tuple) else result
        if sampled is None or not sampled.IsOk():
            self.status_note.set_text(
                "The pixel under the pointer could not be read, so nothing was "
                "sampled.",
                role="error",
            )
            return
        self.set_colour(
            colour_api.from_rgb255(
                sampled.Red(), sampled.Green(), sampled.Blue(), self.colour.alpha
            ),
            source="eyedropper",
        )
        self.status_note.set_text(f"Sampled the screen at {position.x}, {position.y}.")

    def _end_sampling(self) -> None:
        self._sampling = False
        if self.HasCapture():
            self.ReleaseMouse()

    # -- lifecycle -----------------------------------------------------------
    def refresh_theme(self) -> None:
        """Re-read the tokens and repaint the window and everything in it."""
        try:
            if self.IsBeingDeleted():
                return
            self.root.refresh_theme()
            self.body.SetBackgroundColour(tokens.palette().surface)
            for child in self.body.GetChildren():
                refresh = getattr(child, "refresh_theme", None)
                if callable(refresh):
                    refresh()
            self._sync_contrast()
            self.Refresh()
        except RuntimeError:  # pragma: no cover - window already gone
            self._theme_unsubscribe = None

    def reset(self) -> None:
        """Return to the colour the window opened with."""
        self.set_colour(self.original, source="reset")
        self.status_note.set_text("Reset to the colour this window opened with.")

    def confirm(self) -> None:
        """Hand the chosen colour back and close."""
        value = colour_api.format_as(self.colour, "hex8")
        remember_colour(value)
        widgets.invoke(self.on_apply, value)
        self.close()

    def cancel(self) -> None:
        """Close without changing anything."""
        self.close()

    def close(self) -> None:
        self.Close()

    def _on_char_hook(self, event: wx.KeyEvent) -> None:
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            if self._sampling:
                self._end_sampling()
                self.status_note.set_text("Eyedropper cancelled.")
                return
            self.cancel()
            return
        event.Skip()

    def _return_focus(self) -> None:
        if self._focus_returned:
            return
        self._focus_returned = True
        opener = self._opener
        if opener is None:
            return
        try:
            if opener and not opener.IsBeingDeleted():
                opener.SetFocus()
        except RuntimeError:  # pragma: no cover - the opener has gone
            pass

    def _on_close(self, event: wx.CloseEvent) -> None:
        self._end_sampling()
        if self._theme_unsubscribe is not None:
            self._theme_unsubscribe()
            self._theme_unsubscribe = None
        self._return_focus()
        event.Skip()
        self.Destroy()


def open_colour_picker(
    parent: wx.Window,
    value: str = "#6750A4",
    *,
    on_apply: Optional[Callable[[str], None]] = None,
    title: str = "Colour",
    subject: str = "Appearance",
) -> ColourPickerDialog:
    """Open the picker beside ``parent`` and return it.

    This is the entry point every colour control in the application calls.  It
    is deliberately non-blocking: ``on_apply`` receives the chosen colour as a
    HEX8 string, and nothing is called if the user cancels, so a caller never
    has to guess whether an empty return meant "cancelled" or "black".
    """
    dialog = ColourPickerDialog(
        parent, value, on_apply=on_apply, title=title, subject=subject
    )
    dialog.CentreOnParent()
    dialog.Show()
    return dialog
