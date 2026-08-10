"""Owner-drawn primitives every Amulet Studio surface is built from.

The design this shell implements asks for shapes wx has no native control for:
pill buttons, ribbon command tiles with a tinted glyph badge, notched outlined
fields, anchored option popups, generated block tiles, and a two-key
authorisation gate.  Rather than let every surface paint its own approximation,
each shape lives here once, reads its appearance from
:mod:`amulet_map_editor.api.studio.tokens`, and repaints itself when the theme
changes.

Everything in this module is keyboard reachable, paints a visible focus ring,
carries an accessible name, and sizes its controls from
:func:`tokens.control_height` so a density or interface-scale change moves the
whole shell together instead of leaving one surface behind.  Nothing here
reaches the network: block previews are generated placeholders and say so.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import wx

from amulet_map_editor.api import config
from amulet_map_editor.api.studio import blocks, tokens
from amulet_map_editor.api.studio.search import MAX_PATTERN_LENGTH, SearchState

log = logging.getLogger(__name__)

#: Config record holding one boolean per :class:`CollapsibleSection` remember
#: key.  Persisted preferences carry a fixed, versioned field set, so a
#: per-section flag lives in its own bounded record beside them rather than
#: growing the shared schema every time a surface gains a section.
SECTION_STATE_ID = "amulet_studio_sections"

#: The image kinds a texture slot accepts, and the size beyond which a file is
#: refused rather than decoded.  Both bounds are reported to the user when a
#: dropped file misses them.
IMAGE_EXTENSIONS: Tuple[str, ...] = (".png", ".jpg", ".jpeg")
MAX_IMAGE_BYTES = 32 * 1024 * 1024

#: Axis inks, transcribed from the design's viewport axis legend.  They are
#: data colours rather than chrome, so they stay fixed across themes.
AXIS_COLOURS: Dict[str, str] = {
    "x": "#FF8A80",
    "y": "#B9F6CA",
    "z": "#82B1FF",
}

#: wxPython 4.1 added a medium weight; older builds fall back to normal rather
#: than raising while a button is being constructed.
_MEDIUM = getattr(wx, "FONTWEIGHT_MEDIUM", wx.FONTWEIGHT_NORMAL)

#: One design pixel in points at the 96 dpi the design was drawn against.
_PX_TO_POINT = 0.75


def point_size(css_pixels: float) -> int:
    """Return the point size matching a design pixel size.

    The design is specified in CSS pixels and wx asks for points, so every font
    size in this module keeps the design's own number and converts here; a
    reader comparing the two can see the same value in both.
    """
    return max(1, round(float(css_pixels) * _PX_TO_POINT))


def colour_of(value: Any, fallback: Optional[wx.Colour] = None) -> wx.Colour:
    """Coerce a hex string, a colour name, or a colour into ``wx.Colour``.

    Spec data carries colours as strings, so a swatch built from a malformed
    value must still paint something rather than raising inside a paint
    handler.
    """
    if isinstance(value, wx.Colour):
        return value
    text = str(value or "").strip()
    if text:
        colour = wx.Colour(text)
        if colour.IsOk():
            return colour
    return fallback if fallback is not None else wx.Colour(138, 138, 138, 255)


def reduced_motion() -> bool:
    """Return whether the platform asks interfaces to avoid animation.

    Windows exposes the preference as the client-area animation system
    parameter; other platforms have no portable query through wx, so they
    report ``False`` and the caller keeps its (short, non-looping) motion.  The
    environment variable is the escape hatch for a host that wants motion off
    everywhere.
    """
    if os.environ.get("AMULET_REDUCED_MOTION", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }:
        return True
    if wx.Platform != "__WXMSW__":
        return False
    try:  # pragma: no cover - platform boundary
        import ctypes

        enabled = ctypes.c_int(1)
        # SPI_GETCLIENTAREAANIMATION = 0x1042
        if ctypes.windll.user32.SystemParametersInfoW(
            0x1042, 0, ctypes.byref(enabled), 0
        ):
            return not bool(enabled.value)
    except Exception:
        log.debug("Could not read the platform animation preference")
    return False


def invoke(callback: Optional[Callable[..., Any]], *args: Any) -> Any:
    """Call a widget callback without letting a failure break the event loop.

    A callback raising inside a paint or size handler tears down the surface it
    was drawing, so the failure is logged with its traceback and the widget
    carries on.
    """
    if callback is None:
        return None
    try:
        return callback(*args)
    except Exception:
        log.exception("A Studio widget callback failed")
        return None


def section_states() -> Dict[str, bool]:
    """Return the persisted expanded state of every remembered section."""
    raw = config.get(SECTION_STATE_ID, {})
    if not isinstance(raw, dict):
        return {}
    return {str(key): bool(value) for key, value in raw.items()}


def remember_section(key: str, expanded: bool) -> None:
    """Persist one section's expanded state, ignoring an unwritable profile."""
    if not key:
        return
    try:
        states = section_states()
        states[str(key)] = bool(expanded)
        config.put(SECTION_STATE_ID, states)
    except OSError:
        log.exception("Could not persist the state of section %r", key)


# ----------------------------------------------------------------------------
# drawing helpers
# ----------------------------------------------------------------------------


def elide(dc: wx.DC, text: str, max_width: int) -> str:
    """Return ``text`` shortened with an ellipsis so it fits ``max_width``."""
    if max_width <= 0 or not text:
        return ""
    if dc.GetTextExtent(text)[0] <= max_width:
        return text
    ellipsis = "…"
    if dc.GetTextExtent(ellipsis)[0] > max_width:
        return ""
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if dc.GetTextExtent(text[:middle] + ellipsis)[0] <= max_width:
            low = middle
        else:
            high = middle - 1
    return text[:low] + ellipsis


def wrap_text(dc: wx.DC, text: str, max_width: int, max_lines: int = 2) -> List[str]:
    """Word-wrap ``text`` into at most ``max_lines`` lines, eliding the last.

    Explicit newlines are honoured first: bilingual copy arrives as an English
    line above a Cantonese one, and splitting that pair across a word wrap
    would read as one run-on sentence in two languages.
    """
    lines: List[str] = []
    for paragraph in str(text).split("\n"):
        if len(lines) >= max_lines:
            break
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        current = words[0]
        for word in words[1:]:
            candidate = f"{current} {word}"
            if dc.GetTextExtent(candidate)[0] <= max_width:
                current = candidate
                continue
            lines.append(current)
            current = word
            if len(lines) >= max_lines:
                break
        if len(lines) < max_lines:
            lines.append(current)
    if not lines:
        return [""]
    lines = lines[:max_lines]
    lines[-1] = elide(dc, lines[-1], max_width)
    return lines


def tracked_width(dc: wx.DC, text: str, tracking: int) -> int:
    """Return the width of ``text`` drawn with extra letter spacing."""
    if not text:
        return 0
    return sum(dc.GetTextExtent(char)[0] for char in text) + tracking * (len(text) - 1)


def draw_tracked_text(
    dc: wx.DC, text: str, x: int, y: int, tracking: int
) -> int:  # noqa: D401
    """Draw ``text`` with extra letter spacing and return the ending x."""
    position = float(x)
    for char in text:
        dc.DrawText(char, round(position), y)
        position += dc.GetTextExtent(char)[0] + tracking
    return round(position)


def draw_focus_ring(
    dc: wx.DC, rect: wx.Rect, radius: int, colour: wx.Colour, inset: int = 1
) -> None:
    """Paint the two-pixel ring that shows which control has the keyboard."""
    ring = wx.Rect(rect)
    ring.Deflate(inset, inset)
    tokens.draw_round_rect(dc, ring, radius, None, colour, border_width=2)


def draw_dashed_round_rect(
    dc: wx.DC, rect: wx.Rect, radius: int, colour: wx.Colour
) -> None:
    """Paint the dashed outline the design uses for an empty drop target."""
    dc.SetBrush(wx.TRANSPARENT_BRUSH)
    dc.SetPen(wx.Pen(colour, 1, wx.PENSTYLE_SHORT_DASH))
    dc.DrawRoundedRectangle(rect, min(radius, min(rect.width, rect.height) // 2))
    dc.SetPen(wx.NullPen)
    dc.SetBrush(wx.NullBrush)


def paint_context(window: wx.Window, background: wx.Colour) -> Tuple[wx.DC, wx.DC]:
    """Return a cleared buffered device context and its antialiased wrapper.

    Every painted widget starts the same way, and the wrapper is what makes a
    rounded corner read as a curve rather than a staircase.  The caller deletes
    the wrapper before the buffer goes out of scope.

    The device context type matters more than it looks.  ``wx.GCDC`` accepts a
    ``wx.WindowDC``, a ``wx.MemoryDC``, a ``wx.PrinterDC`` or a
    ``wx.GraphicsContext`` — and on wxPython 4.3.1 / wxWidgets 3.3.3 a
    ``wx.AutoBufferedPaintDC`` matches none of those overloads, so wrapping one
    raises ``TypeError`` *inside* ``EVT_PAINT``.  A paint handler that raises
    leaves its control unpainted, which is how every owner-drawn control in an
    interface becomes a flat grey rectangle while the native ones beside it
    still draw correctly.  ``wx.BufferedPaintDC`` keeps the double buffering
    and is accepted, so it is tried first; ``wx.PaintDC`` is the unbuffered
    fallback, and if a future build rejects the wrapper for both, the plain
    device context is returned as its own wrapper so the control still draws —
    without antialiasing, but visibly, which beats not at all.
    """
    for factory in (wx.BufferedPaintDC, wx.PaintDC):
        try:
            dc = factory(window)
        except (TypeError, RuntimeError, wx.wxAssertionError):
            continue
        try:
            wrapper: wx.DC = wx.GCDC(dc)
        except TypeError:
            # Release the device context before creating another one for the
            # same window: two live paint contexts on one window is undefined.
            del dc
            continue
        dc.SetBackground(wx.Brush(background))
        dc.Clear()
        return dc, wrapper
    dc = wx.PaintDC(window)
    dc.SetBackground(wx.Brush(background))
    dc.Clear()
    return dc, dc


class _Themed:
    """Shared theme, focus, and accessibility plumbing for Studio widgets.

    A widget registers a repaint callback only when no Studio ancestor already
    has one: a theme change then walks each top-level widget once instead of
    repainting a nested control as many times as it has Studio parents.
    """

    _theme_unsubscribe: Optional[Callable[[], None]] = None

    def _install(self, name: str = "", *, listen: Optional[bool] = None) -> None:
        """Finish construction: name, paint mode, and theme registration."""
        if name:
            self.SetName(name)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        # Ask the platform to double-buffer as well, so the unbuffered paint
        # fallback in ``paint_context`` still repaints without flicker.
        try:
            self.SetDoubleBuffered(True)
        except (AttributeError, RuntimeError):
            # Not every platform backend implements it; the buffered device
            # context above is the primary route regardless.
            pass
        if listen is None:
            listen = not self._has_themed_ancestor()
        if listen:
            self._theme_unsubscribe = tokens.register_theme_listener(self.refresh_theme)
            self.Bind(wx.EVT_WINDOW_DESTROY, self._on_destroyed)

    def _has_themed_ancestor(self) -> bool:
        parent = self.GetParent()
        while parent is not None:
            if isinstance(parent, _Themed):
                return True
            parent = parent.GetParent()
        return False

    def _on_destroyed(self, event: wx.WindowDestroyEvent) -> None:
        if event.GetEventObject() is self and self._theme_unsubscribe is not None:
            self._theme_unsubscribe()
            self._theme_unsubscribe = None
        event.Skip()

    def palette(self) -> tokens.StudioPalette:
        """Return the live palette; resolved per paint so a change lands at once."""
        return tokens.palette()

    def _apply_theme(self, palette: tokens.StudioPalette) -> None:
        """Push palette colours into any native children.  Overridden as needed."""

    def refresh_theme(self) -> None:
        """Re-read the tokens and repaint this widget and everything under it."""
        try:
            if self.IsBeingDeleted():
                return
            palette = tokens.palette()
            self._apply_theme(palette)
            for child in self.GetChildren():
                refresh = getattr(child, "refresh_theme", None)
                if callable(refresh):
                    refresh()
            self.Refresh()
        except RuntimeError:
            # The underlying window has already gone; the listener drops itself.
            self._theme_unsubscribe = None


class _Interactive(_Themed):
    """Hover, press, focus, and activation behaviour shared by every button.

    Activation is deliberately duplicated across mouse and keyboard: a control
    that only responds to a click is unreachable to anybody who does not use
    one, and that is a completion blocker rather than a rough edge.
    """

    def _bind_interaction(self) -> None:
        self._hovered = False
        self._pressed = False
        self.SetCursor(wx.Cursor(wx.CURSOR_HAND))
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.Bind(wx.EVT_ENTER_WINDOW, self._on_enter)
        self.Bind(wx.EVT_LEAVE_WINDOW, self._on_leave)
        self.Bind(wx.EVT_LEFT_DOWN, self._on_left_down)
        self.Bind(wx.EVT_LEFT_UP, self._on_left_up)
        self.Bind(wx.EVT_KEY_DOWN, self._on_key_down)
        self.Bind(wx.EVT_SET_FOCUS, self._on_focus)
        self.Bind(wx.EVT_KILL_FOCUS, self._on_focus)

    def _on_enter(self, event: wx.MouseEvent) -> None:
        self._hovered = True
        self.Refresh()
        event.Skip()

    def _on_leave(self, event: wx.MouseEvent) -> None:
        self._hovered = False
        if not event.LeftIsDown():
            self._pressed = False
        self.Refresh()
        event.Skip()

    def _on_left_down(self, event: wx.MouseEvent) -> None:
        if self.IsEnabled():
            self.SetFocus()
            self._pressed = True
            self.Refresh()
        event.Skip()

    def _on_left_up(self, event: wx.MouseEvent) -> None:
        was_pressed = self._pressed
        self._pressed = False
        self.Refresh()
        if was_pressed and self.GetClientRect().Contains(event.GetPosition()):
            self.activate()
        event.Skip()

    def _on_key_down(self, event: wx.KeyEvent) -> None:
        if self.IsEnabled() and event.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_SPACE):
            self.activate()
            return
        event.Skip()

    def _on_focus(self, event: wx.FocusEvent) -> None:
        self.Refresh()
        event.Skip()

    def _emit_button(self) -> None:
        command = wx.CommandEvent(wx.EVT_BUTTON.typeId, self.GetId())
        command.SetEventObject(self)
        self.GetEventHandler().ProcessEvent(command)

    # Every control mixing this in defines ``activate`` -- what the control
    # does when it is clicked, tapped, or reached with Enter or Space -- and
    # ``_on_paint``.  They are deliberately not defined here: a default would
    # let a control that forgot one look finished while doing nothing, whereas
    # a missing attribute fails loudly the moment the control is constructed.


# ----------------------------------------------------------------------------
# buttons and small indicators
# ----------------------------------------------------------------------------

#: Per-variant geometry, transcribed from the design: horizontal padding, corner
#: radius, label size in design pixels, font weight, and a fixed height where
#: the design gives one instead of following the density token.
_BUTTON_METRICS: Dict[str, Tuple[int, int, int, int, Optional[int]]] = {
    "filled": (24, tokens.RADIUS_PILL, 14, _MEDIUM, None),
    "tonal": (20, tokens.RADIUS_PILL, 13, _MEDIUM, None),
    "outlined": (18, tokens.RADIUS_PILL, 13, wx.FONTWEIGHT_NORMAL, None),
    "text": (16, tokens.RADIUS_PILL, 13, _MEDIUM, None),
    "danger": (18, tokens.RADIUS_PILL, 13, wx.FONTWEIGHT_NORMAL, None),
    "icon": (4, 7, 13, wx.FONTWEIGHT_NORMAL, 28),
    "pill": (12, tokens.RADIUS_PILL, 12, wx.FONTWEIGHT_NORMAL, 28),
    "ribbon": (10, 10, 11, wx.FONTWEIGHT_NORMAL, None),
}

BUTTON_VARIANTS: Tuple[str, ...] = tuple(_BUTTON_METRICS)

#: Ribbon tile geometry: the glyph badge is a fixed square above a label that
#: wraps to at most two lines, so a long command name grows the tile rather
#: than being cut in half.
_RIBBON_BADGE = 30
_RIBBON_MIN_WIDTH = 66
_RIBBON_LABEL_WIDTH = 78
_ICON_WIDTH = 30


class StudioButton(wx.Control, _Interactive):
    """Every button the shell draws, in one of the design's eight variants.

    ``on_click`` is called with no arguments; a ``wx.EVT_BUTTON`` is emitted as
    well so a surface can bind either way.  A label containing a newline is
    drawn as a prominent first line above a compact second one, which is what
    bilingual mode produces and what keeps it from crowding a control.
    """

    def __init__(
        self,
        parent: wx.Window,
        label: str = "",
        *,
        variant: str = "filled",
        glyph: str = "",
        hint: str = "",
        on_click: Optional[Callable[[], None]] = None,
        name: str = "",
        min_width: int = 0,
        height: Optional[int] = None,
    ) -> None:
        if variant not in _BUTTON_METRICS:
            raise ValueError(f"Unknown Studio button variant: {variant!r}")
        super().__init__(parent, style=wx.BORDER_NONE | wx.WANTS_CHARS)
        self.variant = variant
        self.glyph = str(glyph)
        self.hint = str(hint)
        self.on_click = on_click
        self._mono = False
        self._min_width = int(min_width)
        self._height = height
        wx.Control.SetLabel(self, str(label))
        self._install(name or str(label) or self.hint or "Button")
        self._bind_interaction()
        if self.hint:
            self.SetToolTip(self.hint)
        self.SetInitialSize(self.DoGetBestSize())

    # -- appearance ----------------------------------------------------------
    def _metrics(self) -> Tuple[int, int, int, int, Optional[int]]:
        return _BUTTON_METRICS[self.variant]

    def _label_font(self, size_px: int, weight: int) -> wx.Font:
        return tokens.font(self, point_size(size_px), weight, mono=self._mono)

    def _height_for(self) -> int:
        padding, _radius, _size, _weight, fixed = self._metrics()
        if self._height is not None:
            return tokens.scaled(int(self._height))
        if fixed is not None:
            return tokens.scaled(fixed)
        return tokens.control_height()

    def _variant_colours(
        self, palette: tokens.StudioPalette
    ) -> Tuple[Optional[wx.Colour], wx.Colour, Optional[wx.Colour]]:
        """Return the resting fill, ink, and border for the current variant."""
        if not self.IsEnabled():
            return (
                palette.surface_container,
                tokens.blend(palette.on_surface_variant, palette.surface, 0.45),
                None,
            )
        if self.variant == "filled":
            return palette.primary, palette.on_primary, None
        if self.variant == "tonal":
            return palette.primary_container, palette.on_primary_container, None
        if self.variant == "outlined":
            return None, palette.primary, palette.outline
        if self.variant == "danger":
            return None, palette.error, palette.error
        if self.variant == "pill":
            return None, palette.on_surface_variant, palette.outline_variant
        if self.variant == "icon":
            return None, palette.on_surface_variant, None
        if self.variant == "ribbon":
            return None, palette.on_surface, None
        return None, palette.primary, None

    def _state_colours(
        self, palette: tokens.StudioPalette
    ) -> Tuple[Optional[wx.Colour], wx.Colour, Optional[wx.Colour]]:
        fill, ink, border = self._variant_colours(palette)
        if not self.IsEnabled():
            return fill, ink, border
        if self.variant in ("icon", "pill", "ribbon", "text"):
            if self._pressed:
                fill = tokens.blend(
                    palette.surface_container_high, palette.on_surface, 0.10
                )
            elif self._hovered:
                fill = palette.surface_container_high
            if self.variant == "ribbon" and (self._hovered or self._pressed):
                border = palette.outline_variant
        elif self._pressed or self._hovered:
            weight = 0.16 if self._pressed else 0.08
            base = fill if fill is not None else palette.surface
            fill = tokens.blend(base, ink, weight)
        return fill, ink, border

    # -- geometry ------------------------------------------------------------
    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        padding, _radius, size_px, weight, _fixed = self._metrics()
        dc = wx.ClientDC(self)
        dc.SetFont(self._label_font(size_px, weight))
        label = self.GetLabel()
        if self.variant == "ribbon":
            lines = wrap_text(dc, label or " ", tokens.scaled(_RIBBON_LABEL_WIDTH), 2)
            text_width = max(dc.GetTextExtent(line)[0] for line in lines)
            line_height = dc.GetCharHeight()
            width = max(
                tokens.scaled(_RIBBON_MIN_WIDTH),
                text_width + tokens.scaled(padding) * 2,
                tokens.scaled(_RIBBON_BADGE) + tokens.scaled(padding) * 2,
                tokens.scaled(self._min_width),
            )
            height = (
                tokens.scaled(9)
                + tokens.scaled(_RIBBON_BADGE)
                + tokens.scaled(6)
                + line_height * len(lines)
                + tokens.scaled(8)
            )
            return wx.Size(width, height)
        height = self._height_for()
        if self.variant == "icon" and not label.strip():
            return wx.Size(
                max(tokens.scaled(_ICON_WIDTH), tokens.scaled(self._min_width)), height
            )
        lines = [line for line in label.split("\n") if line] or [" "]
        text_width = max(dc.GetTextExtent(line)[0] for line in lines)
        if self.glyph:
            text_width += dc.GetTextExtent(f"{self.glyph} ")[0]
        width = text_width + tokens.scaled(padding) * 2
        if self.variant == "icon":
            width = max(width, tokens.scaled(_ICON_WIDTH))
        if len(lines) > 1:
            height = max(height, dc.GetCharHeight() * len(lines) + tokens.scaled(10))
        return wx.Size(max(width, tokens.scaled(self._min_width)), height)

    # -- behaviour -----------------------------------------------------------
    def set_label(self, text: str) -> None:
        """Replace the visible label, its accessible name, and the layout size."""
        self.SetLabel(str(text))

    def SetLabel(self, label: str) -> None:  # noqa: N802 - wx API spelling
        super().SetLabel(str(label))
        self.SetName(str(label) or self.hint or "Button")
        self.InvalidateBestSize()
        self.SetMinSize(self.DoGetBestSize())
        self.Refresh()

    def activate(self) -> None:
        if not self.IsEnabled():
            return
        invoke(self.on_click)
        self._emit_button()

    # -- painting ------------------------------------------------------------
    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = self.palette()
        parent = self.GetParent()
        backdrop = parent.GetBackgroundColour() if parent else palette.surface
        if not backdrop.IsOk():
            backdrop = palette.surface
        dc, gcdc = paint_context(self, backdrop)
        width, height = self.GetClientSize()
        rect = wx.Rect(0, 0, width, height)
        padding, radius, size_px, weight, _fixed = self._metrics()
        fill, ink, border = self._state_colours(palette)
        scaled_radius = (
            radius if radius >= tokens.RADIUS_PILL else tokens.scaled(radius)
        )
        if fill is not None or border is not None:
            tokens.draw_round_rect(gcdc, rect, scaled_radius, fill, border)
        if self.variant == "ribbon":
            self._paint_ribbon(gcdc, palette, rect, size_px, weight, ink)
        else:
            self._paint_label(gcdc, rect, padding, size_px, weight, ink)
        if self.HasFocus():
            draw_focus_ring(gcdc, rect, scaled_radius, palette.primary)
        del gcdc

    def _paint_label(
        self,
        dc: wx.DC,
        rect: wx.Rect,
        padding: int,
        size_px: int,
        weight: int,
        ink: wx.Colour,
    ) -> None:
        label = self.GetLabel()
        if self.glyph and label:
            label = f"{self.glyph} {label}"
        elif self.glyph:
            label = self.glyph
        if not label:
            return
        dc.SetTextForeground(ink)
        primary_font = self._label_font(size_px, weight)
        lines = label.split("\n")
        inner = tokens.scaled(padding)
        available = max(0, rect.width - inner * 2)
        dc.SetFont(primary_font)
        heights = [dc.GetCharHeight()]
        rendered = [elide(dc, lines[0], available)]
        secondary_font = None
        if len(lines) > 1:
            secondary_font = self._label_font(max(9, size_px - 2), weight)
            dc.SetFont(secondary_font)
            for line in lines[1:]:
                rendered.append(elide(dc, line, available))
                heights.append(dc.GetCharHeight())
        total = sum(heights)
        y = rect.y + max(0, (rect.height - total) // 2)
        for index, line in enumerate(rendered):
            dc.SetFont(primary_font if index == 0 else secondary_font)
            dc.SetTextForeground(
                ink if index == 0 else tokens.blend(ink, self.palette().surface, 0.25)
            )
            text_width = dc.GetTextExtent(line)[0]
            x = rect.x + max(inner, (rect.width - text_width) // 2)
            dc.DrawText(line, x, y)
            y += heights[index]

    def _paint_ribbon(
        self,
        dc: wx.DC,
        palette: tokens.StudioPalette,
        rect: wx.Rect,
        size_px: int,
        weight: int,
        ink: wx.Colour,
    ) -> None:
        badge = tokens.scaled(_RIBBON_BADGE)
        badge_rect = wx.Rect(
            rect.x + (rect.width - badge) // 2, rect.y + tokens.scaled(9), badge, badge
        )
        tokens.draw_round_rect(
            dc,
            badge_rect,
            tokens.scaled(9),
            tokens.blend(palette.surface, palette.primary, 0.10),
        )
        if self.glyph:
            dc.SetFont(tokens.font(self, point_size(17)))
            dc.SetTextForeground(palette.primary)
            glyph_width, glyph_height = dc.GetTextExtent(self.glyph)
            dc.DrawText(
                self.glyph,
                badge_rect.x + (badge - glyph_width) // 2,
                badge_rect.y + (badge - glyph_height) // 2,
            )
        dc.SetFont(self._label_font(size_px, weight))
        dc.SetTextForeground(ink)
        available = min(
            tokens.scaled(_RIBBON_LABEL_WIDTH), rect.width - tokens.scaled(8)
        )
        lines = wrap_text(dc, self.GetLabel(), available, 2)
        y = badge_rect.GetBottom() + tokens.scaled(6)
        for line in lines:
            text_width = dc.GetTextExtent(line)[0]
            dc.DrawText(line, rect.x + (rect.width - text_width) // 2, y)
            y += dc.GetCharHeight()


class _GlyphSquare(StudioButton):
    """The filled square that launches a regex builder beside a search field.

    It is the icon variant with a permanent container fill and a monospaced
    ``.*`` face, exactly as the design draws it, so the affordance reads as a
    tool rather than as a decorative glyph.
    """

    def __init__(
        self,
        parent: wx.Window,
        *,
        label: str = ".*",
        size: int = 36,
        on_click: Optional[Callable[[], None]] = None,
        name: str = "Regex builder",
        hint: str = "",
    ) -> None:
        super().__init__(
            parent,
            label,
            variant="icon",
            on_click=on_click,
            name=name,
            hint=hint,
            height=size,
            min_width=size,
        )
        self._mono = True
        self.SetInitialSize(wx.Size(tokens.scaled(size), tokens.scaled(size)))

    def _variant_colours(
        self, palette: tokens.StudioPalette
    ) -> Tuple[Optional[wx.Colour], wx.Colour, Optional[wx.Colour]]:
        if not self.IsEnabled():
            return palette.surface_container, palette.on_surface_variant, None
        return palette.surface_container_high, palette.primary, None


class Chip(wx.Control, _Interactive):
    """A selectable filter chip: 32px tall, outlined, filled when chosen.

    ``on_click`` receives the new selected state so a caller can filter without
    reading the chip back.
    """

    def __init__(
        self,
        parent: wx.Window,
        label: str,
        *,
        selected: bool = False,
        on_click: Optional[Callable[[bool], None]] = None,
    ) -> None:
        super().__init__(parent, style=wx.BORDER_NONE | wx.WANTS_CHARS)
        wx.Control.SetLabel(self, str(label))
        self.selected = bool(selected)
        self.on_click = on_click
        self._install(str(label) or "Chip")
        self._bind_interaction()
        self.SetInitialSize(self.DoGetBestSize())

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        dc = wx.ClientDC(self)
        dc.SetFont(tokens.font(self, point_size(14), _MEDIUM))
        lines = self.GetLabel().split("\n") or [" "]
        width = max(dc.GetTextExtent(line or " ")[0] for line in lines)
        height = max(
            tokens.scaled(32), dc.GetCharHeight() * len(lines) + tokens.scaled(8)
        )
        return wx.Size(width + tokens.scaled(32), height)

    def set_selected(self, selected: bool) -> None:
        """Set the chip's state without running its callback."""
        self.selected = bool(selected)
        self.Refresh()

    def activate(self) -> None:
        if not self.IsEnabled():
            return
        self.selected = not self.selected
        self.Refresh()
        invoke(self.on_click, self.selected)
        self._emit_button()

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = self.palette()
        parent = self.GetParent()
        backdrop = parent.GetBackgroundColour() if parent else palette.surface
        dc, gcdc = paint_context(self, backdrop if backdrop.IsOk() else palette.surface)
        width, height = self.GetClientSize()
        rect = wx.Rect(0, 0, width, height)
        radius = tokens.scaled(tokens.RADIUS_SM)
        if self.selected:
            fill, ink, border = (
                palette.primary_container,
                palette.on_primary_container,
                palette.primary_container,
            )
        else:
            fill, ink, border = (None, palette.on_surface, palette.outline)
            if self._pressed or self._hovered:
                fill = tokens.blend(
                    palette.surface, palette.primary, 0.12 if self._pressed else 0.06
                )
        tokens.draw_round_rect(gcdc, rect, radius, fill, border)
        gcdc.SetFont(tokens.font(self, point_size(14), _MEDIUM))
        gcdc.SetTextForeground(ink)
        lines = self.GetLabel().split("\n")
        available = max(0, width - tokens.scaled(24))
        line_height = gcdc.GetCharHeight()
        y = (height - line_height * len(lines)) // 2
        for line in lines:
            text = elide(gcdc, line, available)
            text_width = gcdc.GetTextExtent(text)[0]
            gcdc.DrawText(text, (width - text_width) // 2, y)
            y += line_height
        if self.HasFocus():
            draw_focus_ring(gcdc, rect, radius, palette.primary)
        del gcdc


class SectionLabel(wx.Control, _Themed):
    """The 10px uppercase caption that titles a block of controls."""

    TRACKING = 1

    def __init__(self, parent: wx.Window, text: str) -> None:
        super().__init__(parent, style=wx.BORDER_NONE)
        wx.Control.SetLabel(self, str(text))
        self._install(str(text) or "Section")
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.SetInitialSize(self.DoGetBestSize())

    def AcceptsFocus(self) -> bool:  # noqa: N802 - wx API spelling
        return False

    def AcceptsFocusFromKeyboard(self) -> bool:  # noqa: N802 - wx API spelling
        return False

    def _font(self) -> wx.Font:
        return tokens.font(self, point_size(10), wx.FONTWEIGHT_BOLD)

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        dc = wx.ClientDC(self)
        dc.SetFont(self._font())
        text = self.GetLabel().upper()
        return wx.Size(
            tracked_width(dc, text, tokens.scaled(self.TRACKING)) + 2,
            dc.GetCharHeight() + tokens.scaled(2),
        )

    def set_label(self, text: str) -> None:
        """Replace the caption and re-measure it."""
        wx.Control.SetLabel(self, str(text))
        self.SetName(str(text) or "Section")
        self.InvalidateBestSize()
        self.SetMinSize(self.DoGetBestSize())
        self.Refresh()

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = self.palette()
        parent = self.GetParent()
        backdrop = parent.GetBackgroundColour() if parent else palette.surface
        dc, gcdc = paint_context(self, backdrop if backdrop.IsOk() else palette.surface)
        gcdc.SetFont(self._font())
        gcdc.SetTextForeground(palette.on_surface_variant)
        draw_tracked_text(
            gcdc, self.GetLabel().upper(), 0, 0, tokens.scaled(self.TRACKING)
        )
        del gcdc


class Card(wx.Panel, _Themed):
    """A rounded container surface that keeps native children inside it."""

    def __init__(
        self,
        parent: wx.Window,
        *,
        role: str = "surface_container",
        radius: int = tokens.RADIUS_MD,
        border: bool = True,
    ) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self.role = role
        self.radius = radius
        self.border = bool(border)
        self._install("Card")
        self._apply_theme(self.palette())
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)

    def _apply_theme(self, palette: tokens.StudioPalette) -> None:
        self.SetBackgroundColour(palette.role(self.role))

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = self.palette()
        parent = self.GetParent()
        backdrop = parent.GetBackgroundColour() if parent else palette.surface
        dc, gcdc = paint_context(self, backdrop if backdrop.IsOk() else palette.surface)
        width, height = self.GetClientSize()
        tokens.draw_round_rect(
            gcdc,
            wx.Rect(0, 0, width, height),
            tokens.scaled(self.radius),
            palette.role(self.role),
            palette.outline_variant if self.border else None,
        )
        del gcdc


class Divider(wx.Control, _Themed):
    """The hairline rule that separates two groups of controls."""

    def __init__(self, parent: wx.Window, *, vertical: bool = False) -> None:
        super().__init__(parent, style=wx.BORDER_NONE)
        self.vertical = bool(vertical)
        self._install("Divider")
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.SetInitialSize(self.DoGetBestSize())

    def AcceptsFocus(self) -> bool:  # noqa: N802 - wx API spelling
        return False

    def AcceptsFocusFromKeyboard(self) -> bool:  # noqa: N802 - wx API spelling
        return False

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        thickness = max(1, tokens.scaled(1))
        return wx.Size(thickness, 16) if self.vertical else wx.Size(16, thickness)

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = self.palette()
        parent = self.GetParent()
        backdrop = parent.GetBackgroundColour() if parent else palette.surface
        dc, _gcdc = paint_context(
            self, backdrop if backdrop.IsOk() else palette.surface
        )
        width, height = self.GetClientSize()
        dc.SetBrush(wx.Brush(palette.outline_variant))
        dc.SetPen(wx.TRANSPARENT_PEN)
        dc.DrawRectangle(0, 0, width, height)
        del _gcdc


def format_number(value: float) -> str:
    """Format a numeric readout without a trailing ``.0`` on whole values."""
    number = float(value)
    if number == int(number):
        return str(int(number))
    return f"{number:g}"


class ToggleSwitch(wx.Control, _Interactive):
    """The 52x32 M3 switch used for every boolean the shell shows.

    ``on_change`` receives the new value.  Space, Enter, and the arrow keys all
    operate it, so it is usable without a pointer.
    """

    TRACK_WIDTH = 52
    TRACK_HEIGHT = 32
    KNOB = 24
    PADDING = 4

    def __init__(
        self,
        parent: wx.Window,
        value: bool = False,
        *,
        on_change: Optional[Callable[[bool], None]] = None,
    ) -> None:
        super().__init__(parent, style=wx.BORDER_NONE | wx.WANTS_CHARS)
        self.value = bool(value)
        self.on_change = on_change
        self._install("Toggle")
        self._bind_interaction()
        self.SetInitialSize(self.DoGetBestSize())

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        return wx.Size(
            tokens.scaled(self.TRACK_WIDTH), tokens.scaled(self.TRACK_HEIGHT)
        )

    def set_value(self, value: bool, *, notify: bool = False) -> None:
        """Set the switch; ``notify`` decides whether the callback runs."""
        self.value = bool(value)
        self.Refresh()
        if notify:
            invoke(self.on_change, self.value)

    def activate(self) -> None:
        if not self.IsEnabled():
            return
        self.set_value(not self.value, notify=True)
        self._emit_button()

    def _on_key_down(self, event: wx.KeyEvent) -> None:
        code = event.GetKeyCode()
        if self.IsEnabled() and code in (wx.WXK_LEFT, wx.WXK_RIGHT):
            self.set_value(code == wx.WXK_RIGHT, notify=True)
            return
        super()._on_key_down(event)

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = self.palette()
        parent = self.GetParent()
        backdrop = parent.GetBackgroundColour() if parent else palette.surface
        dc, gcdc = paint_context(self, backdrop if backdrop.IsOk() else palette.surface)
        width, height = self.GetClientSize()
        track = wx.Rect(0, 0, width, height)
        if self.value:
            fill, border = palette.primary, palette.primary
            knob_colour = palette.on_primary
        else:
            fill, border = palette.surface_container_high, palette.outline
            knob_colour = palette.outline
        tokens.draw_round_rect(gcdc, track, height // 2, fill, border)
        knob = tokens.scaled(self.KNOB)
        padding = tokens.scaled(self.PADDING)
        knob_x = width - padding - knob if self.value else padding
        gcdc.SetBrush(wx.Brush(knob_colour))
        gcdc.SetPen(wx.TRANSPARENT_PEN)
        gcdc.DrawEllipse(knob_x, (height - knob) // 2, knob, knob)
        if self.HasFocus():
            draw_focus_ring(gcdc, track, height // 2, palette.primary)
        del gcdc


class Stepper(wx.Control, _Interactive):
    """A bounded numeric entry drawn as ``[-] value [+]`` with its range.

    Typing works as well as the arrows: digits, a leading minus, and a decimal
    point build a value that Enter commits and Escape abandons, because a
    stepper whose only route to 400 is four hundred key presses is a stepper
    nobody uses.
    """

    BUTTON = 30
    FIELD = 110
    GAP = 7

    def __init__(
        self,
        parent: wx.Window,
        value: float,
        minimum: float,
        maximum: float,
        *,
        on_change: Optional[Callable[[float], None]] = None,
        suffix: str = "",
    ) -> None:
        super().__init__(parent, style=wx.BORDER_NONE | wx.WANTS_CHARS)
        self.minimum = float(min(minimum, maximum))
        self.maximum = float(max(minimum, maximum))
        self.value = self._clamp(value)
        self.suffix = str(suffix)
        self.on_change = on_change
        self._editing = ""
        self._install(
            f"Value between {format_number(self.minimum)} and "
            f"{format_number(self.maximum)}"
        )
        self._bind_interaction()
        self.Bind(wx.EVT_CHAR, self._on_char)
        self.SetInitialSize(self.DoGetBestSize())

    def _clamp(self, value: Any) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = self.minimum
        return max(self.minimum, min(self.maximum, number))

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        dc = wx.ClientDC(self)
        dc.SetFont(tokens.mono_font(self, point_size(10)))
        range_width = dc.GetTextExtent(self._range_text())[0]
        width = (
            tokens.scaled(self.BUTTON) * 2
            + tokens.scaled(self.FIELD)
            + tokens.scaled(self.GAP) * 3
            + range_width
        )
        return wx.Size(width, max(tokens.scaled(self.BUTTON), tokens.control_height()))

    def _range_text(self) -> str:
        text = f"{format_number(self.minimum)} … {format_number(self.maximum)}"
        return f"{text} {self.suffix}".strip()

    def _display_text(self) -> str:
        if self._editing:
            return self._editing
        return f"{format_number(self.value)} {self.suffix}".strip()

    def set_value(self, value: float, *, notify: bool = True) -> None:
        """Clamp and apply a value, reporting it unless ``notify`` is false."""
        previous = self.value
        self.value = self._clamp(value)
        self._editing = ""
        self.Refresh()
        if notify and previous != self.value:
            invoke(self.on_change, self.value)

    def step(self, delta: float) -> None:
        """Move the value by ``delta``, clamped to the bounds."""
        self.set_value(self.value + delta)

    def activate(self) -> None:
        # Activation without a target region commits any typed value.
        self._commit()

    def _commit(self) -> None:
        if self._editing:
            self.set_value(self._editing)
        else:
            self.Refresh()

    def _regions(self) -> Tuple[wx.Rect, wx.Rect, wx.Rect]:
        height = self.GetClientSize().height
        button = tokens.scaled(self.BUTTON)
        gap = tokens.scaled(self.GAP)
        field = tokens.scaled(self.FIELD)
        top = (height - button) // 2
        minus = wx.Rect(0, top, button, button)
        value = wx.Rect(button + gap, top, field, button)
        plus = wx.Rect(button + gap + field + gap, top, button, button)
        return minus, value, plus

    def _on_left_up(self, event: wx.MouseEvent) -> None:
        was_pressed = self._pressed
        self._pressed = False
        self.Refresh()
        if was_pressed:
            minus, _value, plus = self._regions()
            position = event.GetPosition()
            if minus.Contains(position):
                self.step(-1)
            elif plus.Contains(position):
                self.step(1)
        event.Skip()

    def _on_key_down(self, event: wx.KeyEvent) -> None:
        code = event.GetKeyCode()
        if not self.IsEnabled():
            event.Skip()
            return
        if code in (wx.WXK_UP, wx.WXK_RIGHT):
            self.step(1)
        elif code in (wx.WXK_DOWN, wx.WXK_LEFT):
            self.step(-1)
        elif code == wx.WXK_PAGEUP:
            self.step(10)
        elif code == wx.WXK_PAGEDOWN:
            self.step(-10)
        elif code == wx.WXK_HOME:
            self.set_value(self.minimum)
        elif code == wx.WXK_END:
            self.set_value(self.maximum)
        elif code == wx.WXK_BACK:
            self._editing = self._editing[:-1]
            self.Refresh()
        elif code == wx.WXK_ESCAPE:
            self._editing = ""
            self.Refresh()
        elif code in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self._commit()
        else:
            event.Skip()

    def _on_char(self, event: wx.KeyEvent) -> None:
        character = chr(event.GetUnicodeKey()) if event.GetUnicodeKey() else ""
        if character and (character.isdigit() or character in "-."):
            self._editing = (self._editing + character)[:16]
            self.Refresh()
            return
        event.Skip()

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = self.palette()
        parent = self.GetParent()
        backdrop = parent.GetBackgroundColour() if parent else palette.surface
        dc, gcdc = paint_context(self, backdrop if backdrop.IsOk() else palette.surface)
        minus, value, plus = self._regions()
        radius = tokens.scaled(tokens.RADIUS_SM)
        for rect, glyph in ((minus, "−"), (plus, "＋")):
            tokens.draw_round_rect(gcdc, rect, radius, None, palette.outline)
            gcdc.SetFont(tokens.font(self, point_size(14)))
            gcdc.SetTextForeground(palette.primary)
            text_width, text_height = gcdc.GetTextExtent(glyph)
            gcdc.DrawText(
                glyph,
                rect.x + (rect.width - text_width) // 2,
                rect.y + (rect.height - text_height) // 2,
            )
        editing = bool(self._editing)
        tokens.draw_round_rect(
            gcdc,
            value,
            radius,
            palette.surface,
            palette.primary if editing else palette.outline,
            border_width=2 if editing else 1,
        )
        gcdc.SetFont(tokens.mono_font(self, point_size(12)))
        gcdc.SetTextForeground(palette.on_surface)
        text = elide(gcdc, self._display_text(), value.width - tokens.scaled(12))
        text_width, text_height = gcdc.GetTextExtent(text)
        gcdc.DrawText(
            text,
            value.x + (value.width - text_width) // 2,
            value.y + (value.height - text_height) // 2,
        )
        gcdc.SetFont(tokens.mono_font(self, point_size(10)))
        gcdc.SetTextForeground(palette.on_surface_variant)
        gcdc.DrawText(
            self._range_text(),
            plus.GetRight() + tokens.scaled(self.GAP),
            value.y + (value.height - gcdc.GetCharHeight()) // 2,
        )
        if self.HasFocus():
            draw_focus_ring(
                gcdc,
                wx.Rect(0, 0, *self.GetClientSize()),
                radius,
                palette.primary,
                inset=0,
            )
        del gcdc


class _ValuePill(wx.Control, _Themed):
    """The filled readout that sits beside a slider label."""

    def __init__(self, parent: wx.Window, text: str) -> None:
        super().__init__(parent, style=wx.BORDER_NONE)
        wx.Control.SetLabel(self, str(text))
        self._install(f"Value {text}")
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.SetInitialSize(self.DoGetBestSize())

    def AcceptsFocus(self) -> bool:  # noqa: N802 - wx API spelling
        return False

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        dc = wx.ClientDC(self)
        dc.SetFont(tokens.mono_font(self, point_size(12), _MEDIUM))
        width = dc.GetTextExtent(self.GetLabel() or " ")[0]
        return wx.Size(width + tokens.scaled(24), tokens.scaled(26))

    def set_text(self, text: str) -> None:
        """Replace the readout and re-measure the pill around it."""
        wx.Control.SetLabel(self, str(text))
        self.SetName(f"Value {text}")
        self.InvalidateBestSize()
        self.SetMinSize(self.DoGetBestSize())
        self.Refresh()

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = self.palette()
        parent = self.GetParent()
        backdrop = parent.GetBackgroundColour() if parent else palette.surface
        dc, gcdc = paint_context(self, backdrop if backdrop.IsOk() else palette.surface)
        width, height = self.GetClientSize()
        tokens.draw_round_rect(
            gcdc,
            wx.Rect(0, 0, width, height),
            tokens.scaled(tokens.RADIUS_SM),
            palette.primary,
        )
        gcdc.SetFont(tokens.mono_font(self, point_size(12), _MEDIUM))
        gcdc.SetTextForeground(palette.on_primary)
        text = elide(gcdc, self.GetLabel(), width - tokens.scaled(8))
        text_width, text_height = gcdc.GetTextExtent(text)
        gcdc.DrawText(text, (width - text_width) // 2, (height - text_height) // 2)
        del gcdc


class RangeRow(wx.Panel, _Themed):
    """A labelled slider with a live readout, as the design's ranges section.

    The slider is the native control on purpose: wx already gives it arrow-key,
    page, and home/end handling that a painted track would have to reproduce
    from scratch, and screen readers already announce its value.
    """

    def __init__(
        self,
        parent: wx.Window,
        label: str,
        value: float,
        minimum: float,
        maximum: float,
        *,
        step: float = 1,
        on_change: Optional[Callable[[float], None]] = None,
    ) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self.label = str(label)
        self.minimum = float(min(minimum, maximum))
        self.maximum = float(max(minimum, maximum))
        self.step = float(step) if float(step) > 0 else 1.0
        self.on_change = on_change
        self._install(self.label or "Range")
        self._scale = max(1, round(1 / self.step)) if self.step < 1 else 1
        self._caption = wx.StaticText(self, label=self.label)
        self._caption.SetFont(tokens.font(self, point_size(14)))
        self._pill = _ValuePill(self, format_number(value))
        self._slider = wx.Slider(
            self,
            value=self._to_slider(value),
            minValue=self._to_slider(self.minimum),
            maxValue=self._to_slider(self.maximum),
            style=wx.SL_HORIZONTAL,
            name=self.label or "Range",
        )
        self._slider.SetName(self.label or "Range")
        header = wx.BoxSizer(wx.HORIZONTAL)
        header.Add(self._caption, 1, wx.ALIGN_CENTER_VERTICAL)
        header.Add(self._pill, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, tokens.SPACE_SM)
        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(header, 0, wx.EXPAND)
        root.Add(self._slider, 0, wx.EXPAND | wx.TOP, tokens.scaled(tokens.SPACE_SM))
        self.SetSizer(root)
        self._apply_theme(self.palette())
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self._slider.Bind(wx.EVT_SLIDER, self._on_slide)

    def _to_slider(self, value: float) -> int:
        return int(round(float(value) * self._scale))

    def _from_slider(self, value: int) -> float:
        return float(value) / self._scale

    def value(self) -> float:
        """Return the slider's current value in the caller's own units."""
        return self._from_slider(self._slider.GetValue())

    def set_value(self, value: float, *, notify: bool = False) -> None:
        """Move the slider and refresh the readout."""
        clamped = max(self.minimum, min(self.maximum, float(value)))
        self._slider.SetValue(self._to_slider(clamped))
        self._pill.set_text(format_number(clamped))
        self.Layout()
        if notify:
            invoke(self.on_change, clamped)

    def _on_slide(self, _event: wx.CommandEvent) -> None:
        current = self.value()
        self._pill.set_text(format_number(current))
        self.Layout()
        invoke(self.on_change, current)

    def _apply_theme(self, palette: tokens.StudioPalette) -> None:
        self.SetBackgroundColour(
            self.GetParent().GetBackgroundColour()
            if self.GetParent()
            else palette.surface
        )
        self._caption.SetForegroundColour(palette.on_surface)
        self._caption.SetFont(tokens.font(self, point_size(14)))
        self._slider.SetBackgroundColour(self.GetBackgroundColour())
        self._slider.SetForegroundColour(palette.primary)

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        dc, gcdc = paint_context(self, self.GetBackgroundColour())
        del gcdc
        del dc


class Swatch(wx.Control, _Interactive):
    """One colour chip.  ``on_click`` receives the colour it represents."""

    def __init__(
        self,
        parent: wx.Window,
        colour: Any,
        *,
        name: str = "",
        on_click: Optional[Callable[[wx.Colour], None]] = None,
        size: int = 36,
    ) -> None:
        super().__init__(parent, style=wx.BORDER_NONE | wx.WANTS_CHARS)
        self.colour = colour_of(colour)
        self.size = int(size)
        self.on_click = on_click
        label = name or self.colour.GetAsString(wx.C2S_HTML_SYNTAX)
        self._install(label)
        self.SetToolTip(label)
        self._bind_interaction()
        self.SetInitialSize(self.DoGetBestSize())

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        side = tokens.scaled(self.size)
        return wx.Size(side, side)

    def set_colour(self, colour: Any) -> None:
        """Replace the colour this swatch shows."""
        self.colour = colour_of(colour)
        self.Refresh()

    def activate(self) -> None:
        if not self.IsEnabled():
            return
        invoke(self.on_click, self.colour)
        self._emit_button()

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = self.palette()
        parent = self.GetParent()
        backdrop = parent.GetBackgroundColour() if parent else palette.surface
        dc, gcdc = paint_context(self, backdrop if backdrop.IsOk() else palette.surface)
        width, height = self.GetClientSize()
        rect = wx.Rect(0, 0, width, height)
        radius = tokens.scaled(9)
        border = palette.primary if self._hovered else palette.outline
        tokens.draw_round_rect(gcdc, rect, radius, self.colour, border)
        if self.HasFocus():
            draw_focus_ring(gcdc, rect, radius, palette.primary)
        del gcdc


class ProgressRow(wx.Panel, _Themed):
    """A hint, a right-aligned readout, and the 8px bar underneath them."""

    BAR_HEIGHT = 8

    def __init__(
        self, parent: wx.Window, hint: str, fraction: float, label: str
    ) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self.hint = str(hint)
        self.fraction = max(0.0, min(1.0, float(fraction)))
        self.label = str(label)
        self._install(f"{self.hint} {self.label}".strip() or "Progress")
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.SetInitialSize(self.DoGetBestSize())

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        dc = wx.ClientDC(self)
        dc.SetFont(tokens.font(self, point_size(12)))
        height = dc.GetCharHeight() + tokens.scaled(self.BAR_HEIGHT) + tokens.scaled(8)
        return wx.Size(240, height)

    def set_progress(self, fraction: float, label: str = "") -> None:
        """Update the bar and, when given, its readout."""
        self.fraction = max(0.0, min(1.0, float(fraction)))
        if label:
            self.label = str(label)
        self.SetName(f"{self.hint} {self.label}".strip() or "Progress")
        self.Refresh()

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = self.palette()
        parent = self.GetParent()
        backdrop = parent.GetBackgroundColour() if parent else palette.surface
        dc, gcdc = paint_context(self, backdrop if backdrop.IsOk() else palette.surface)
        width, height = self.GetClientSize()
        gcdc.SetFont(tokens.font(self, point_size(12)))
        text_height = gcdc.GetCharHeight()
        gcdc.SetTextForeground(palette.on_surface_variant)
        label_width = gcdc.GetTextExtent(self.label)[0]
        gcdc.DrawText(elide(gcdc, self.hint, max(0, width - label_width - 12)), 0, 0)
        gcdc.SetFont(tokens.font(self, point_size(12), _MEDIUM))
        gcdc.SetTextForeground(palette.primary)
        gcdc.DrawText(self.label, max(0, width - label_width), 0)
        bar_height = tokens.scaled(self.BAR_HEIGHT)
        bar_top = text_height + tokens.scaled(8)
        track = wx.Rect(0, bar_top, width, bar_height)
        tokens.draw_round_rect(
            gcdc, track, bar_height // 2, palette.surface_container_high
        )
        filled = int(width * self.fraction)
        if filled > 0:
            tokens.draw_round_rect(
                gcdc,
                wx.Rect(0, bar_top, filled, bar_height),
                bar_height // 2,
                palette.primary,
            )
        del gcdc


# ----------------------------------------------------------------------------
# text entry
# ----------------------------------------------------------------------------


class _TextBox(wx.Panel, _Themed):
    """An owner-drawn field outline wrapped around one native text control.

    The outline is painted rather than native so a field matches the rest of
    the shell at every theme and density; the entry itself stays a real
    ``wx.TextCtrl`` so selection, clipboard, caret, and screen-reader behaviour
    are the platform's own rather than a re-implementation.
    """

    def __init__(
        self,
        parent: wx.Window,
        *,
        value: str = "",
        placeholder: str = "",
        mono: bool = False,
        radius: int = tokens.RADIUS_SM,
        height: Optional[int] = None,
        prefix: str = "",
        prefix_colour: Any = "",
        on_change: Optional[Callable[[str], None]] = None,
        on_enter: Optional[Callable[[str], None]] = None,
        name: str = "Text field",
        size_px: int = 13,
        fill_role: str = "surface_container",
    ) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self.radius = radius
        self.prefix = str(prefix)
        self.prefix_colour = prefix_colour
        self.on_change = on_change
        self.on_enter = on_enter
        self.size_px = size_px
        self.fill_role = fill_role
        self._mono = bool(mono)
        self._height = height
        self._focused = False
        self._install(name, listen=False)
        style = wx.BORDER_NONE
        if on_enter is not None:
            style |= wx.TE_PROCESS_ENTER
        self.text = wx.TextCtrl(self, value=str(value), style=style, name=name)
        self.text.SetName(name)
        if placeholder:
            self.text.SetHint(str(placeholder))
        self._apply_theme(self.palette())
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.Bind(wx.EVT_SIZE, self._on_size)
        self.text.Bind(wx.EVT_TEXT, self._on_text)
        self.text.Bind(wx.EVT_SET_FOCUS, self._on_focus_change)
        self.text.Bind(wx.EVT_KILL_FOCUS, self._on_focus_change)
        if on_enter is not None:
            self.text.Bind(wx.EVT_TEXT_ENTER, self._on_enter)
        self.SetInitialSize(self.DoGetBestSize())

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        height = (
            tokens.scaled(self._height)
            if self._height is not None
            else tokens.control_height()
        )
        return wx.Size(tokens.scaled(160), height)

    def value(self) -> str:
        """Return the current text."""
        return self.text.GetValue()

    def set_value(self, text: str, *, notify: bool = False) -> None:
        """Replace the text; silent by default so a refresh cannot loop."""
        if notify:
            self.text.SetValue(str(text))
        else:
            self.text.ChangeValue(str(text))
        self.Refresh()

    def SetFocus(self) -> None:  # noqa: N802 - wx API spelling
        self.text.SetFocus()

    def _prefix_width(self, dc: wx.DC) -> int:
        if not self.prefix:
            return 0
        dc.SetFont(tokens.mono_font(self, point_size(10)))
        return dc.GetTextExtent(self.prefix)[0] + tokens.scaled(6)

    def _on_size(self, event: wx.SizeEvent) -> None:
        width, height = self.GetClientSize()
        padding = tokens.scaled(11)
        dc = wx.ClientDC(self)
        prefix = self._prefix_width(dc)
        text_height = self.text.GetBestSize().height
        self.text.SetSize(
            padding + prefix,
            max(0, (height - text_height) // 2),
            max(0, width - padding * 2 - prefix),
            text_height,
        )
        self.Refresh()
        event.Skip()

    def _on_text(self, event: wx.CommandEvent) -> None:
        invoke(self.on_change, self.text.GetValue())
        event.Skip()

    def _on_enter(self, event: wx.CommandEvent) -> None:
        invoke(self.on_enter, self.text.GetValue())
        event.Skip()

    def _on_focus_change(self, event: wx.FocusEvent) -> None:
        self._focused = event.GetEventType() == wx.EVT_SET_FOCUS.typeId
        self.Refresh()
        event.Skip()

    def _apply_theme(self, palette: tokens.StudioPalette) -> None:
        self.SetBackgroundColour(
            self.GetParent().GetBackgroundColour()
            if self.GetParent()
            else palette.surface
        )
        text = getattr(self, "text", None)
        if text is not None:
            text.SetBackgroundColour(palette.role(self.fill_role))
            text.SetForegroundColour(palette.on_surface)
            text.SetFont(tokens.font(self, point_size(self.size_px), mono=self._mono))

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = self.palette()
        dc, gcdc = paint_context(self, self.GetBackgroundColour())
        width, height = self.GetClientSize()
        rect = wx.Rect(0, 0, width, height)
        tokens.draw_round_rect(
            gcdc,
            rect,
            tokens.scaled(self.radius),
            palette.role(self.fill_role),
            palette.primary if self._focused else palette.outline,
            border_width=2 if self._focused else 1,
        )
        if self.prefix:
            gcdc.SetFont(tokens.mono_font(self, point_size(10)))
            gcdc.SetTextForeground(
                colour_of(self.prefix_colour, palette.on_surface_variant)
            )
            gcdc.DrawText(
                self.prefix,
                tokens.scaled(11),
                (height - gcdc.GetCharHeight()) // 2,
            )
        del gcdc


class OutlinedField(wx.Panel, _Themed):
    """An M3 outlined text field with a notched floating label.

    ``on_change`` receives the new text on every keystroke.  The label is
    painted over the outline rather than placed above it, which is what makes
    the field read as one control instead of two stacked ones.
    """

    LABEL_TOP = 6
    BOX_HEIGHT = 48
    TEXT_PADDING = 15

    def __init__(
        self,
        parent: wx.Window,
        label: str,
        value: str = "",
        *,
        placeholder: str = "",
        mono: bool = True,
        on_change: Optional[Callable[[str], None]] = None,
    ) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self.label = str(label)
        self.on_change = on_change
        self._mono = bool(mono)
        self._focused = False
        self._install(self.label or "Field", listen=False)
        self.text = wx.TextCtrl(
            self, value=str(value), style=wx.BORDER_NONE, name=self.label or "Field"
        )
        self.text.SetName(self.label or "Field")
        if placeholder:
            self.text.SetHint(str(placeholder))
        self._apply_theme(self.palette())
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.Bind(wx.EVT_SIZE, self._on_size)
        self.text.Bind(wx.EVT_TEXT, self._on_text)
        self.text.Bind(wx.EVT_SET_FOCUS, self._on_focus_change)
        self.text.Bind(wx.EVT_KILL_FOCUS, self._on_focus_change)
        self.SetInitialSize(self.DoGetBestSize())

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        height = tokens.scaled(self.LABEL_TOP) + tokens.scaled(self.BOX_HEIGHT)
        return wx.Size(tokens.scaled(220), height)

    def value(self) -> str:
        """Return the current text."""
        return self.text.GetValue()

    def set_value(self, text: str, *, notify: bool = False) -> None:
        """Replace the text; silent by default."""
        if notify:
            self.text.SetValue(str(text))
        else:
            self.text.ChangeValue(str(text))
        self.Refresh()

    def SetFocus(self) -> None:  # noqa: N802 - wx API spelling
        self.text.SetFocus()

    def _box_rect(self) -> wx.Rect:
        width, _height = self.GetClientSize()
        return wx.Rect(
            0,
            tokens.scaled(self.LABEL_TOP),
            width,
            tokens.scaled(self.BOX_HEIGHT),
        )

    def _on_size(self, event: wx.SizeEvent) -> None:
        box = self._box_rect()
        padding = tokens.scaled(self.TEXT_PADDING)
        text_height = self.text.GetBestSize().height
        self.text.SetSize(
            padding,
            box.y + max(0, (box.height - text_height) // 2),
            max(0, box.width - padding * 2),
            text_height,
        )
        self.Refresh()
        event.Skip()

    def _on_text(self, event: wx.CommandEvent) -> None:
        invoke(self.on_change, self.text.GetValue())
        event.Skip()

    def _on_focus_change(self, event: wx.FocusEvent) -> None:
        self._focused = event.GetEventType() == wx.EVT_SET_FOCUS.typeId
        self.Refresh()
        event.Skip()

    def _apply_theme(self, palette: tokens.StudioPalette) -> None:
        backdrop = (
            self.GetParent().GetBackgroundColour()
            if self.GetParent()
            else palette.surface
        )
        self.SetBackgroundColour(backdrop if backdrop.IsOk() else palette.surface)
        text = getattr(self, "text", None)
        if text is not None:
            text.SetBackgroundColour(self.GetBackgroundColour())
            text.SetForegroundColour(palette.on_surface)
            text.SetFont(tokens.font(self, point_size(14), mono=self._mono))

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = self.palette()
        dc, gcdc = paint_context(self, self.GetBackgroundColour())
        box = self._box_rect()
        border = palette.primary if self._focused else palette.outline
        tokens.draw_round_rect(
            gcdc,
            box,
            tokens.scaled(4),
            None,
            border,
            border_width=2 if self._focused else 1,
        )
        if self.label:
            gcdc.SetFont(tokens.font(self, point_size(11)))
            label = elide(gcdc, self.label, max(0, box.width - tokens.scaled(30)))
            label_width = gcdc.GetTextExtent(label)[0]
            notch = wx.Rect(
                tokens.scaled(11),
                0,
                label_width + tokens.scaled(8),
                gcdc.GetCharHeight(),
            )
            gcdc.SetBrush(wx.Brush(self.GetBackgroundColour()))
            gcdc.SetPen(wx.TRANSPARENT_PEN)
            gcdc.DrawRectangle(notch)
            gcdc.SetTextForeground(
                palette.primary if self._focused else palette.on_surface_variant
            )
            gcdc.DrawText(label, notch.x + tokens.scaled(4), 0)
        del gcdc


class PathField(wx.Panel, _Themed):
    """A path entry with native Browse buttons and one shared validator.

    A typed path and a browsed path run through exactly the same check, so a
    value chosen from the picker is never trusted more than one somebody typed,
    and the reason a path is refused is stated in words rather than as a red
    outline.
    """

    MODES = ("folder", "file", "both")

    #: Set by the first validation, which every constructor runs; declared here
    #: so a theme refresh arriving before it cannot read a missing attribute.
    _valid = False

    def __init__(
        self,
        parent: wx.Window,
        label: str,
        value: str = "",
        *,
        mode: str = "folder",
        on_change: Optional[Callable[[str], None]] = None,
    ) -> None:
        if mode not in self.MODES:
            raise ValueError(f"Unknown path mode: {mode!r}")
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self.label = str(label)
        self.mode = mode
        self.on_change = on_change
        self._install(self.label or "Path", listen=False)
        self.field = OutlinedField(
            self,
            self.label,
            str(value),
            placeholder="Type a path, or use Browse",
            mono=True,
            on_change=self._on_typed,
        )
        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(self.field, 1, wx.ALIGN_BOTTOM)
        self.folder_button: Optional[StudioButton] = None
        self.file_button: Optional[StudioButton] = None
        if mode in ("folder", "both"):
            self.folder_button = StudioButton(
                self,
                "Browse folders…",
                variant="outlined",
                on_click=self._browse_folder,
                name=f"Browse folders for {self.label}",
                hint=f"Choose a folder for {self.label}",
            )
            row.Add(
                self.folder_button,
                0,
                wx.ALIGN_BOTTOM | wx.LEFT,
                tokens.scaled(tokens.SPACE_SM),
            )
        if mode in ("file", "both"):
            self.file_button = StudioButton(
                self,
                "Browse files…",
                variant="outlined",
                on_click=self._browse_file,
                name=f"Browse files for {self.label}",
                hint=f"Choose a file for {self.label}",
            )
            row.Add(
                self.file_button,
                0,
                wx.ALIGN_BOTTOM | wx.LEFT,
                tokens.scaled(tokens.SPACE_SM),
            )
        self.feedback = wx.StaticText(self, label="")
        self.feedback.SetName(f"{self.label} validation")
        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(row, 0, wx.EXPAND)
        root.Add(self.feedback, 0, wx.EXPAND | wx.TOP, tokens.scaled(tokens.SPACE_XS))
        self.SetSizer(root)
        self._apply_theme(self.palette())
        self._validate(self.field.value())

    def value(self) -> str:
        """Return the current path exactly as typed or chosen."""
        return self.field.value()

    def set_value(self, path: str, *, notify: bool = True) -> None:
        """Replace the path and revalidate it."""
        self.field.set_value(str(path))
        self._validate(str(path))
        if notify:
            invoke(self.on_change, str(path))

    def is_valid(self) -> bool:
        """Return whether the current path passed validation."""
        return self._valid

    def feedback_text(self) -> str:
        """Return the visible validation line."""
        return self.feedback.GetLabel()

    def _validate(self, path: str) -> bool:
        text = str(path).strip()
        palette = self.palette()
        if not text:
            self._valid = False
            message = "No path yet. Type one, or use Browse."
            colour = palette.on_surface_variant
        elif len(text) > 4096:
            self._valid = False
            message = "That path is longer than 4096 characters."
            colour = palette.error
        elif self.mode == "folder" and not os.path.isdir(text):
            self._valid = False
            message = "No folder at that path yet."
            colour = palette.error
        elif self.mode == "file" and not os.path.isfile(text):
            self._valid = False
            message = "No file at that path yet."
            colour = palette.error
        elif self.mode == "both" and not os.path.exists(text):
            self._valid = False
            message = "Nothing exists at that path yet."
            colour = palette.error
        else:
            self._valid = True
            kind = "Folder" if os.path.isdir(text) else "File"
            message = f"{kind} found."
            colour = palette.on_surface_variant
        self.feedback.SetLabel(message)
        self.feedback.SetForegroundColour(colour)
        self.feedback.SetFont(tokens.font(self, point_size(11)))
        self.Layout()
        return self._valid

    def _on_typed(self, text: str) -> None:
        self._validate(text)
        invoke(self.on_change, text)

    def _browse_folder(self) -> None:
        with wx.DirDialog(
            self,
            f"Choose a folder for {self.label}",
            defaultPath=self.value() if os.path.isdir(self.value()) else "",
        ) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                self.set_value(dialog.GetPath())

    def _browse_file(self) -> None:
        with wx.FileDialog(
            self,
            f"Choose a file for {self.label}",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                self.set_value(dialog.GetPath())

    def _apply_theme(self, palette: tokens.StudioPalette) -> None:
        backdrop = (
            self.GetParent().GetBackgroundColour()
            if self.GetParent()
            else palette.surface
        )
        self.SetBackgroundColour(backdrop if backdrop.IsOk() else palette.surface)
        feedback = getattr(self, "feedback", None)
        if feedback is not None:
            feedback.SetFont(tokens.font(self, point_size(11)))
            self._validate(self.field.value())


# ----------------------------------------------------------------------------
# search, popups, and searchable choices
# ----------------------------------------------------------------------------


class SearchBar(wx.Panel, _Themed):
    """A search field, its regex opt-in, its builder, and its feedback line.

    Plain text is always the default: the regex checkbox is an explicit choice,
    an invalid pattern is reported in the feedback line instead of quietly
    matching nothing, and the ``.*`` button opens the shared builder seeded
    with this field's own pattern, flags, and sample and writes the accepted
    pattern back into this field alone.

    ``on_change`` receives the :class:`SearchState` after every edit.
    """

    def __init__(
        self,
        parent: wx.Window,
        placeholder: str,
        state: SearchState,
        *,
        on_change: Optional[Callable[[SearchState], None]] = None,
        show_regex: bool = True,
        compact: bool = False,
        builder: bool = True,
    ) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self.state = state
        self.on_change = on_change
        self.compact = bool(compact)
        self._install(state.label or "Search", listen=False)
        field_height = 30 if compact else None
        self.field = _TextBox(
            self,
            value=state.query,
            placeholder=str(placeholder),
            radius=tokens.RADIUS_SM,
            height=field_height,
            on_change=self._on_query,
            name=state.label or str(placeholder) or "Search",
            size_px=12 if compact else 13,
        )
        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(self.field, 1, wx.ALIGN_CENTER_VERTICAL)
        self.regex_box: Optional[wx.CheckBox] = None
        if show_regex:
            self.regex_box = wx.CheckBox(self, label="Regex")
            self.regex_box.SetValue(bool(state.regex))
            self.regex_box.SetName(f"Use a regular expression for {state.label}")
            self.regex_box.SetToolTip(
                "Plain text is the default. Turn this on to read the query as a "
                "regular expression."
            )
            self.regex_box.Bind(wx.EVT_CHECKBOX, self._on_regex)
            row.Add(
                self.regex_box,
                0,
                wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
                tokens.scaled(tokens.SPACE_SM),
            )
        self.builder_button: Optional[StudioButton] = None
        if builder:
            self.builder_button = _GlyphSquare(
                self,
                size=30 if compact else 36,
                on_click=self.open_builder,
                name=f"Regex builder for {state.label}",
                hint=state.feedback(),
            )
            row.Add(
                self.builder_button,
                0,
                wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
                tokens.scaled(tokens.SPACE_XS),
            )
        self.feedback = wx.StaticText(self, label=state.feedback())
        self.feedback.SetName(f"{state.label} search feedback")
        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(row, 0, wx.EXPAND)
        root.Add(self.feedback, 0, wx.EXPAND | wx.TOP, tokens.scaled(tokens.SPACE_XS))
        self.SetSizer(root)
        self._apply_theme(self.palette())

    # -- state ---------------------------------------------------------------
    def query(self) -> str:
        """Return the current query text."""
        return self.state.query

    def set_query(self, text: str, *, notify: bool = True) -> None:
        """Replace the query, refresh the feedback, and report the change."""
        self.state.query = str(text)[:MAX_PATTERN_LENGTH]
        self.field.set_value(self.state.query)
        self.refresh_feedback()
        if notify:
            invoke(self.on_change, self.state)

    def refresh_feedback(self) -> None:
        """Re-read the state's honest status line and show it."""
        message = self.state.feedback()
        self.feedback.SetLabel(message)
        palette = self.palette()
        invalid = self.state.regex and not self.state.is_valid()
        self.feedback.SetForegroundColour(
            palette.error if invalid else palette.on_surface_variant
        )
        if self.builder_button is not None:
            self.builder_button.SetToolTip(message)
        self.Layout()

    def _on_query(self, text: str) -> None:
        self.state.query = str(text)[:MAX_PATTERN_LENGTH]
        self.refresh_feedback()
        invoke(self.on_change, self.state)

    def _on_regex(self, event: wx.CommandEvent) -> None:
        self.state.regex = bool(self.regex_box.GetValue())
        self.refresh_feedback()
        invoke(self.on_change, self.state)
        event.Skip()

    def open_builder(self) -> None:
        """Open the shared regex builder for this field and apply its result."""
        from amulet_map_editor.api.wx.ui.regex_dialog import RegexBuilderDialog

        flags = re.IGNORECASE if "i" in (self.state.flags or "") else 0
        with RegexBuilderDialog(
            self,
            pattern=self.state.query,
            regex_enabled=bool(self.state.regex),
            flags=flags,
            sample=self.state.sample,
            flags_text=self.state.flags,
        ) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            self.state.query = str(dialog.pattern)[:MAX_PATTERN_LENGTH]
            self.state.regex = bool(dialog.regex_enabled)
            self.state.flags = str(dialog.flags_text) or self.state.flags
            self.state.sample = str(dialog.sample) or self.state.sample
        self.field.set_value(self.state.query)
        if self.regex_box is not None:
            self.regex_box.SetValue(self.state.regex)
        self.refresh_feedback()
        invoke(self.on_change, self.state)

    def SetFocus(self) -> None:  # noqa: N802 - wx API spelling
        self.field.SetFocus()

    def _apply_theme(self, palette: tokens.StudioPalette) -> None:
        backdrop = (
            self.GetParent().GetBackgroundColour()
            if self.GetParent()
            else palette.surface
        )
        self.SetBackgroundColour(backdrop if backdrop.IsOk() else palette.surface)
        feedback = getattr(self, "feedback", None)
        if feedback is not None:
            feedback.SetFont(tokens.font(self, point_size(10 if self.compact else 11)))
            self.refresh_feedback()
        if self.regex_box is not None:
            self.regex_box.SetBackgroundColour(self.GetBackgroundColour())
            self.regex_box.SetForegroundColour(palette.on_surface_variant)
            self.regex_box.SetFont(tokens.font(self, point_size(11)))


class AnchoredPopup(wx.PopupTransientWindow):
    """A transient surface anchored beside the control that opened it.

    It paints its own surface, border, and elevation rather than relying on a
    platform frame, is positioned by wx so it stays inside the display and
    never covers its anchor, and scrolls its content when the content is taller
    than the space available -- clipping a list at a fixed height silently
    deletes whatever was past the cut.
    """

    MARGIN = 4
    PADDING = 8

    def __init__(
        self,
        parent: wx.Window,
        anchor: wx.Window,
        *,
        width: Optional[int] = None,
        max_height: Optional[int] = None,
    ) -> None:
        super().__init__(parent, wx.BORDER_NONE)
        self.anchor = anchor
        self.requested_width = width
        self.requested_max_height = max_height
        #: Called when the popup goes away by any route, including a click
        #: outside it, so the owner never keeps a reference to a dead window.
        self.on_dismiss: Optional[Callable[[], None]] = None
        palette = tokens.palette()
        self.SetBackgroundColour(palette.surface)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        inset = tokens.scaled(self.MARGIN) + tokens.scaled(self.PADDING)
        self.header = wx.Panel(self, style=wx.TAB_TRAVERSAL)
        self.header.SetBackgroundColour(palette.surface)
        self.content = wx.ScrolledWindow(self, style=wx.VSCROLL | wx.TAB_TRAVERSAL)
        self.content.SetBackgroundColour(palette.surface)
        self.content.SetScrollRate(0, tokens.scaled(10))
        self.content_sizer = wx.BoxSizer(wx.VERTICAL)
        self.content.SetSizer(self.content_sizer)
        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(self.header, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, inset)
        root.Add(self.content, 1, wx.EXPAND | wx.ALL, inset)
        self.SetSizer(root)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)

    def work_area(self) -> wx.Rect:
        """Return the usable area of the display the anchor sits on."""
        try:
            index = wx.Display.GetFromWindow(self.anchor)
            display = wx.Display(index if index != wx.NOT_FOUND else 0)
            return display.GetClientArea()
        except Exception:  # pragma: no cover - platform boundary
            return wx.Rect(0, 0, 1280, 800)

    def layout(self) -> None:
        """Size the popup to its content, clamped to the display work area."""
        area = self.work_area()
        self.header.Fit()
        self.content.FitInside()
        self.Fit()
        width, height = self.GetSize()
        if self.requested_width:
            width = tokens.scaled(self.requested_width)
        width = max(width, self.anchor.GetSize().width)
        width = min(width, max(120, area.width - tokens.scaled(16)))
        limit = area.height - tokens.scaled(24)
        if self.requested_max_height:
            limit = min(limit, tokens.scaled(self.requested_max_height))
        height = min(height, limit)
        self.SetSize(wx.Size(width, height))
        self.Layout()

    def popup(self) -> None:
        """Lay out, position beside the anchor, and show the popup."""
        self.layout()
        origin = self.anchor.ClientToScreen(wx.Point(0, 0))
        try:
            self.Position(origin, self.anchor.GetSize())
        except Exception:  # pragma: no cover - platform boundary
            self.SetPosition(
                wx.Point(origin.x, origin.y + self.anchor.GetSize().height)
            )
        self.Popup()

    def OnDismiss(self) -> None:  # noqa: N802 - wx API spelling
        """Hand the keyboard back to whatever opened this popup."""
        invoke(self.on_dismiss)
        try:
            if self.anchor and not self.anchor.IsBeingDeleted():
                self.anchor.SetFocus()
        except RuntimeError:
            pass

    def refresh_theme(self) -> None:
        """Re-read the palette for the popup and everything inside it."""
        palette = tokens.palette()
        self.SetBackgroundColour(palette.surface)
        for panel in (self.header, self.content):
            panel.SetBackgroundColour(palette.surface)
            for child in panel.GetChildren():
                refresh = getattr(child, "refresh_theme", None)
                if callable(refresh):
                    refresh()
        self.Refresh()

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        dc, gcdc = paint_context(self, palette.surface)
        width, height = self.GetClientSize()
        margin = tokens.scaled(self.MARGIN)
        card = wx.Rect(margin, margin, width - margin * 2, height - margin * 2)
        radius = tokens.scaled(tokens.RADIUS_MD)
        tokens.draw_elevation(gcdc, card, radius, 2, palette.dark)
        tokens.draw_round_rect(
            gcdc, card, radius, palette.surface, palette.outline_variant
        )
        del gcdc


class _OptionRow(wx.Control, _Interactive):
    """One selectable line inside a :class:`SearchableChoice` popup."""

    HEIGHT = 30
    SWATCH = 18

    def __init__(
        self,
        parent: wx.Window,
        label: str,
        *,
        selected: bool = False,
        swatch: Any = "",
        on_click: Optional[Callable[[str], None]] = None,
    ) -> None:
        super().__init__(parent, style=wx.BORDER_NONE | wx.WANTS_CHARS)
        wx.Control.SetLabel(self, str(label))
        self.selected = bool(selected)
        self.swatch = swatch
        self.on_click = on_click
        self._install(str(label) or "Option", listen=False)
        self._bind_interaction()
        self.SetInitialSize(self.DoGetBestSize())

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        dc = wx.ClientDC(self)
        dc.SetFont(tokens.font(self, point_size(12)))
        width = dc.GetTextExtent(self.GetLabel() or " ")[0] + tokens.scaled(26)
        if self.swatch:
            width += tokens.scaled(self.SWATCH + 8)
        return wx.Size(width, tokens.scaled(self.HEIGHT))

    def set_selected(self, selected: bool) -> None:
        """Mark this row as the chosen option."""
        self.selected = bool(selected)
        self.Refresh()

    def activate(self) -> None:
        invoke(self.on_click, self.GetLabel())

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = self.palette()
        dc, gcdc = paint_context(self, palette.surface)
        width, height = self.GetClientSize()
        rect = wx.Rect(0, 0, width, height)
        radius = tokens.scaled(7)
        if self.selected:
            tokens.draw_round_rect(gcdc, rect, radius, palette.primary_container)
            ink = palette.on_primary_container
        elif self._hovered or self._pressed:
            tokens.draw_round_rect(gcdc, rect, radius, palette.surface_container_high)
            ink = palette.on_surface
        else:
            ink = palette.on_surface
        left = tokens.scaled(9)
        if self.swatch:
            side = tokens.scaled(self.SWATCH)
            tokens.draw_round_rect(
                gcdc,
                wx.Rect(left, (height - side) // 2, side, side),
                tokens.scaled(4),
                colour_of(self.swatch),
                palette.outline_variant,
            )
            left += side + tokens.scaled(8)
        gcdc.SetFont(tokens.font(self, point_size(12)))
        gcdc.SetTextForeground(ink)
        text = elide(gcdc, self.GetLabel(), max(0, width - left - tokens.scaled(9)))
        gcdc.DrawText(text, left, (height - gcdc.GetCharHeight()) // 2)
        if self.HasFocus():
            draw_focus_ring(gcdc, rect, radius, palette.primary)
        del gcdc


class SearchableChoice(wx.Panel, _Interactive):
    """The shell's only dropdown: an outlined combo that opens a search popup.

    Closed it is an M3 outlined field with a notched floating label.  Open it
    is an :class:`AnchoredPopup` carrying its own :class:`SearchBar` with the
    regex opt-in and builder, an honest feedback line, and a scrolling option
    list.  A bare ``wx.Choice`` would give none of that, which is why no Studio
    surface uses one.

    ``on_change`` receives the chosen option.
    """

    LABEL_TOP = 6
    BOX_HEIGHT = 48
    POPUP_LIST_HEIGHT = 220

    def __init__(
        self,
        parent: wx.Window,
        label: str,
        options: Sequence[str],
        value: str = "",
        *,
        on_change: Optional[Callable[[str], None]] = None,
        swatches: Optional[Mapping[str, str] | Sequence[str]] = None,
    ) -> None:
        super().__init__(parent, style=wx.WANTS_CHARS)
        self.label = str(label)
        self.options: List[str] = [str(option) for option in options]
        self.value = str(value) or (self.options[0] if self.options else "")
        self.on_change = on_change
        self.swatches = self._normalise_swatches(swatches)
        self.state = SearchState(label=f"{self.label} options")
        self._popup: Optional[AnchoredPopup] = None
        self._rows: List[_OptionRow] = []
        self._highlight = 0
        self._install(f"{self.label}: {self.value}")
        self._bind_interaction()
        self.SetInitialSize(self.DoGetBestSize())

    def _normalise_swatches(
        self, swatches: Optional[Mapping[str, str] | Sequence[str]]
    ) -> Dict[str, str]:
        if not swatches:
            return {}
        if isinstance(swatches, Mapping):
            return {str(key): str(value) for key, value in swatches.items()}
        return {
            option: str(colour)
            for option, colour in zip(self.options, list(swatches))
            if colour
        }

    def AcceptsFocus(self) -> bool:  # noqa: N802 - wx API spelling
        return True

    def AcceptsFocusFromKeyboard(self) -> bool:  # noqa: N802 - wx API spelling
        return True

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        height = tokens.scaled(self.LABEL_TOP) + tokens.scaled(self.BOX_HEIGHT)
        return wx.Size(tokens.scaled(220), height)

    # -- value ---------------------------------------------------------------
    def set_value(self, value: str, *, notify: bool = False) -> None:
        """Choose an option; ``notify`` decides whether the callback runs."""
        self.value = str(value)
        self.SetName(f"{self.label}: {self.value}")
        self.Refresh()
        if notify:
            invoke(self.on_change, self.value)

    def set_options(self, options: Sequence[str]) -> None:
        """Replace the option list, keeping the current value when it survives."""
        self.options = [str(option) for option in options]
        if self.value not in self.options:
            self.value = self.options[0] if self.options else ""
        self.Refresh()

    def filtered_options(self) -> List[str]:
        """Return the options matching the popup's own search state."""
        return self.state.filter(self.options)

    # -- popup ---------------------------------------------------------------
    def activate(self) -> None:
        if self._popup is not None:
            self.close_popup()
            return
        self.open_popup()

    def open_popup(self) -> None:
        """Open the option popup with its search field focused."""
        if not self.IsEnabled():
            return
        popup = AnchoredPopup(
            self,
            self,
            width=max(self.GetSize().width, tokens.scaled(260)),
            max_height=self.POPUP_LIST_HEIGHT + 120,
        )
        self._popup = popup
        popup.on_dismiss = self._popup_dismissed
        search = SearchBar(
            popup.header,
            "Search options",
            self.state,
            on_change=lambda _state: self._rebuild_rows(),
            compact=True,
        )
        header_sizer = wx.BoxSizer(wx.VERTICAL)
        header_sizer.Add(search, 0, wx.EXPAND)
        popup.header.SetSizer(header_sizer)
        self._rebuild_rows()
        popup.Bind(wx.EVT_CHAR_HOOK, self._on_popup_key)
        popup.popup()
        search.SetFocus()

    def _popup_dismissed(self) -> None:
        """Forget a popup that closed itself, so nothing holds a dead window."""
        self._popup = None
        self._rows = []
        self.Refresh()

    def close_popup(self) -> None:
        """Dismiss the popup and return focus to the combo."""
        popup, self._popup = self._popup, None
        self._rows = []
        if popup is not None:
            try:
                popup.Dismiss()
                popup.Destroy()
            except RuntimeError:
                pass
        self.SetFocus()

    def _rebuild_rows(self) -> None:
        popup = self._popup
        if popup is None:
            return
        popup.content.DestroyChildren()
        popup.content_sizer = wx.BoxSizer(wx.VERTICAL)
        popup.content.SetSizer(popup.content_sizer)
        self._rows = []
        matches = self.filtered_options()
        if not matches:
            empty = wx.StaticText(
                popup.content,
                label=self.state.describe_matches(0, "option"),
            )
            empty.SetForegroundColour(tokens.palette().on_surface_variant)
            empty.SetFont(tokens.font(self, point_size(12)))
            popup.content_sizer.Add(empty, 0, wx.ALL, tokens.scaled(tokens.SPACE_SM))
        for option in matches:
            row = _OptionRow(
                popup.content,
                option,
                selected=option == self.value,
                swatch=self.swatches.get(option, ""),
                on_click=self._choose,
            )
            popup.content_sizer.Add(row, 0, wx.EXPAND | wx.BOTTOM, tokens.scaled(2))
            self._rows.append(row)
        self._highlight = 0
        popup.layout()

    def _choose(self, option: str) -> None:
        self.set_value(option, notify=True)
        self.close_popup()

    def _on_popup_key(self, event: wx.KeyEvent) -> None:
        code = event.GetKeyCode()
        if code == wx.WXK_ESCAPE:
            self.close_popup()
            return
        if code in (wx.WXK_DOWN, wx.WXK_UP) and self._rows:
            step = 1 if code == wx.WXK_DOWN else -1
            self._highlight = (self._highlight + step) % len(self._rows)
            self._rows[self._highlight].SetFocus()
            return
        if code in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER) and self._rows:
            focused = self.FindFocus()
            row = focused if isinstance(focused, _OptionRow) else self._rows[0]
            self._choose(row.GetLabel())
            return
        event.Skip()

    def _on_key_down(self, event: wx.KeyEvent) -> None:
        if self.IsEnabled() and event.GetKeyCode() in (wx.WXK_DOWN, wx.WXK_F4):
            self.open_popup()
            return
        super()._on_key_down(event)

    # -- painting ------------------------------------------------------------
    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = self.palette()
        parent = self.GetParent()
        backdrop = parent.GetBackgroundColour() if parent else palette.surface
        dc, gcdc = paint_context(self, backdrop if backdrop.IsOk() else palette.surface)
        width, height = self.GetClientSize()
        box = wx.Rect(
            0,
            tokens.scaled(self.LABEL_TOP),
            width,
            height - tokens.scaled(self.LABEL_TOP),
        )
        focused = self.HasFocus() or self._popup is not None
        border = palette.primary if focused else palette.outline
        if self._hovered and not focused:
            border = palette.on_surface
        tokens.draw_round_rect(
            gcdc, box, tokens.scaled(4), None, border, border_width=2 if focused else 1
        )
        gcdc.SetFont(tokens.font(self, point_size(14)))
        gcdc.SetTextForeground(palette.on_surface)
        available = max(0, box.width - tokens.scaled(46))
        value = elide(gcdc, self.value, available)
        gcdc.DrawText(
            value,
            tokens.scaled(15),
            box.y + (box.height - gcdc.GetCharHeight()) // 2,
        )
        gcdc.SetFont(tokens.font(self, point_size(10)))
        gcdc.SetTextForeground(palette.on_surface_variant)
        caret_width = gcdc.GetTextExtent("▾")[0]
        gcdc.DrawText(
            "▾",
            box.width - tokens.scaled(15) - caret_width,
            box.y + (box.height - gcdc.GetCharHeight()) // 2,
        )
        if self.label:
            gcdc.SetFont(tokens.font(self, point_size(11)))
            label = elide(gcdc, self.label, max(0, box.width - tokens.scaled(30)))
            label_width = gcdc.GetTextExtent(label)[0]
            notch = wx.Rect(
                tokens.scaled(11),
                0,
                label_width + tokens.scaled(8),
                gcdc.GetCharHeight(),
            )
            gcdc.SetBrush(wx.Brush(backdrop if backdrop.IsOk() else palette.surface))
            gcdc.SetPen(wx.TRANSPARENT_PEN)
            gcdc.DrawRectangle(notch)
            gcdc.SetTextForeground(
                palette.primary if focused else palette.on_surface_variant
            )
            gcdc.DrawText(label, notch.x + tokens.scaled(4), 0)
        if self.HasFocus():
            draw_focus_ring(gcdc, box, tokens.scaled(4), palette.primary)
        del gcdc


# ----------------------------------------------------------------------------
# block previews and image slots
# ----------------------------------------------------------------------------


class TextureTile(wx.Panel, _Themed):
    """A generated block preview, labelled as the placeholder it is.

    Nothing here is a game texture: the tile is drawn from the block's base
    colour so a block can be shown before any Minecraft install or resource
    pack has been loaded, and the label says so in the picture rather than in a
    footnote somebody might not read.
    """

    def __init__(
        self,
        parent: wx.Window,
        block_id: str,
        *,
        size: int = 132,
        label: str = blocks.PLACEHOLDER_LABEL,
    ) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self.block_id = str(block_id)
        self.size = int(size)
        self.label = str(label)
        self._install(f"{self.block_id} — {self.label}")
        self.SetToolTip(f"{self.block_id} — {self.label}")
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.SetInitialSize(self.DoGetBestSize())

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        side = tokens.scaled(self.size)
        return wx.Size(side, side)

    def set_block(self, block_id: str) -> None:
        """Show a different block's generated tile."""
        self.block_id = str(block_id)
        self.SetName(f"{self.block_id} — {self.label}")
        self.SetToolTip(f"{self.block_id} — {self.label}")
        self.Refresh()

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = self.palette()
        parent = self.GetParent()
        backdrop = parent.GetBackgroundColour() if parent else palette.surface
        dc, gcdc = paint_context(self, backdrop if backdrop.IsOk() else palette.surface)
        width, height = self.GetClientSize()
        side = max(1, min(width, height))
        bitmap = blocks.block_tile_bitmap(self.block_id, side)
        dc.DrawBitmap(bitmap, 0, 0, False)
        rect = wx.Rect(0, 0, width, height)
        tokens.draw_round_rect(
            gcdc, rect, tokens.scaled(11), None, palette.outline_variant
        )
        gcdc.SetFont(tokens.mono_font(self, point_size(9)))
        text_width, text_height = gcdc.GetTextExtent(self.label)
        chip = wx.Rect(
            tokens.scaled(6),
            height - text_height - tokens.scaled(9),
            text_width + tokens.scaled(14),
            text_height + tokens.scaled(4),
        )
        tokens.draw_round_rect(gcdc, chip, tokens.scaled(5), palette.scrim)
        gcdc.SetTextForeground(wx.Colour(255, 255, 255, 255))
        gcdc.DrawText(self.label, chip.x + tokens.scaled(7), chip.y + tokens.scaled(2))
        del gcdc


class _FaceButton(wx.Control, _Interactive):
    """One 30px face preview inside a :class:`FaceRow`."""

    SIDE = 30

    def __init__(
        self,
        parent: wx.Window,
        block_id: str,
        face: str,
        brightness: float,
        *,
        on_click: Optional[Callable[[str], None]] = None,
    ) -> None:
        super().__init__(parent, style=wx.BORDER_NONE | wx.WANTS_CHARS)
        self.block_id = str(block_id)
        self.face = str(face)
        self.brightness = float(brightness)
        self.on_click = on_click
        label = f"{self.face} face of {self.block_id}"
        self._install(label, listen=False)
        self.SetToolTip(label)
        self._bind_interaction()
        self.SetInitialSize(self.DoGetBestSize())

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        side = tokens.scaled(self.SIDE)
        return wx.Size(side, side)

    def activate(self) -> None:
        invoke(self.on_click, self.face)

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = self.palette()
        parent = self.GetParent()
        backdrop = parent.GetBackgroundColour() if parent else palette.surface
        dc, gcdc = paint_context(self, backdrop if backdrop.IsOk() else palette.surface)
        width, height = self.GetClientSize()
        side = max(1, min(width, height))
        dc.DrawBitmap(
            blocks.block_tile_bitmap(self.block_id, side, self.brightness), 0, 0, False
        )
        rect = wx.Rect(0, 0, width, height)
        border = (
            palette.primary
            if (self._hovered or self.HasFocus())
            else palette.outline_variant
        )
        tokens.draw_round_rect(gcdc, rect, tokens.scaled(6), None, border)
        if self.HasFocus():
            draw_focus_ring(gcdc, rect, tokens.scaled(6), palette.primary)
        del gcdc


class FaceRow(wx.Panel, _Themed):
    """The top, side, and bottom previews shown under a block tile."""

    def __init__(self, parent: wx.Window, block_id: str) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self.block_id = str(block_id)
        self._install(f"Faces of {self.block_id}")
        row = wx.BoxSizer(wx.HORIZONTAL)
        self.buttons: List[_FaceButton] = []
        for face, brightness in blocks.FACE_BRIGHTNESS:
            button = _FaceButton(self, self.block_id, face, brightness)
            self.buttons.append(button)
            row.Add(button, 0, wx.RIGHT, tokens.scaled(5))
        self.SetSizer(row)
        self._apply_theme(self.palette())
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)

    def set_block(self, block_id: str) -> None:
        """Show a different block's three faces."""
        self.block_id = str(block_id)
        for button in self.buttons:
            button.block_id = self.block_id
            button.Refresh()

    def _apply_theme(self, palette: tokens.StudioPalette) -> None:
        backdrop = (
            self.GetParent().GetBackgroundColour()
            if self.GetParent()
            else palette.surface
        )
        self.SetBackgroundColour(backdrop if backdrop.IsOk() else palette.surface)

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        dc, gcdc = paint_context(self, self.GetBackgroundColour())
        del gcdc
        del dc


class _ImageDropTarget(wx.FileDropTarget):
    """Routes a dropped file into the slot's own validation."""

    def __init__(self, slot: "ImageSlot") -> None:
        super().__init__()
        self._slot = slot

    def OnDropFiles(  # noqa: N802 - wx API spelling
        self, x: int, y: int, filenames: Sequence[str]
    ) -> bool:
        return self._slot.accept_paths(list(filenames))


class ImageSlot(wx.Panel, _Themed):
    """A drop target for a real texture, with the same path for a click.

    A dropped file and a browsed file run through one validator, so neither
    route can accept something the other would refuse.  A refusal says exactly
    what was wrong through the non-blocking notifier rather than failing
    silently or halting the surface with a modal.
    """

    HEIGHT = 96

    def __init__(
        self,
        parent: wx.Window,
        *,
        hint: str = "",
        slot_id: str = "",
        on_image: Optional[Callable[[str], None]] = None,
    ) -> None:
        super().__init__(parent, style=wx.WANTS_CHARS | wx.TAB_TRAVERSAL)
        self.hint = str(hint) or "Drop a PNG or JPEG here, or click to browse"
        self.slot_id = str(slot_id)
        self.on_image = on_image
        self.path = ""
        self._preview: Optional[wx.Bitmap] = None
        self._hovered = False
        self._install(self.hint)
        self.SetToolTip(self.hint)
        self.SetCursor(wx.Cursor(wx.CURSOR_HAND))
        self.SetDropTarget(_ImageDropTarget(self))
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.Bind(wx.EVT_LEFT_UP, lambda _event: self.browse())
        self.Bind(wx.EVT_ENTER_WINDOW, self._on_hover)
        self.Bind(wx.EVT_LEAVE_WINDOW, self._on_hover)
        self.Bind(wx.EVT_KEY_DOWN, self._on_key)
        self.Bind(wx.EVT_SET_FOCUS, lambda event: (self.Refresh(), event.Skip()))
        self.Bind(wx.EVT_KILL_FOCUS, lambda event: (self.Refresh(), event.Skip()))
        self.SetInitialSize(self.DoGetBestSize())

    def AcceptsFocus(self) -> bool:  # noqa: N802 - wx API spelling
        return True

    def AcceptsFocusFromKeyboard(self) -> bool:  # noqa: N802 - wx API spelling
        return True

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        return wx.Size(tokens.scaled(200), tokens.scaled(self.HEIGHT))

    # -- validation ----------------------------------------------------------
    def validate(self, path: str) -> Tuple[bool, str]:
        """Return whether ``path`` is a usable image, and why when it is not."""
        text = str(path).strip()
        if not text:
            return False, "No file was given."
        if not os.path.isfile(text):
            return False, f"There is no file at {text}."
        if os.path.splitext(text)[1].lower() not in IMAGE_EXTENSIONS:
            allowed = ", ".join(IMAGE_EXTENSIONS)
            return False, f"Only {allowed} files are accepted."
        try:
            size = os.path.getsize(text)
        except OSError as error:
            return False, f"That file could not be read: {error}."
        if size > MAX_IMAGE_BYTES:
            limit = MAX_IMAGE_BYTES // (1024 * 1024)
            return False, f"That file is larger than {limit} MB."
        with wx.LogNull():
            image = wx.Image(text)
        if not image.IsOk():
            return False, "That file is not a readable PNG or JPEG."
        return (
            True,
            f"{os.path.basename(text)} · {image.GetWidth()}×{image.GetHeight()}",
        )

    def accept_paths(self, paths: Sequence[str]) -> bool:
        """Validate and take the first usable path, reporting any refusal."""
        for path in paths:
            valid, message = self.validate(path)
            if valid:
                self._apply(path, message)
                return True
            self._report(message)
            return False
        return False

    def browse(self) -> None:
        """Open the file picker and run the same validation as a drop."""
        wildcard = "Images (*.png;*.jpg;*.jpeg)|*.png;*.jpg;*.jpeg"
        with wx.FileDialog(
            self,
            "Choose a texture image",
            wildcard=wildcard,
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                self.accept_paths([dialog.GetPath()])

    def clear(self) -> None:
        """Forget the loaded image and go back to the empty prompt."""
        self.path = ""
        self._preview = None
        self.SetName(self.hint)
        self.Refresh()

    def _apply(self, path: str, description: str) -> None:
        self.path = str(path)
        with wx.LogNull():
            image = wx.Image(self.path)
        self._preview = wx.Bitmap(image) if image.IsOk() else None
        self.SetName(f"{description} loaded into {self.slot_id or 'texture slot'}")
        self.SetToolTip(self.path)
        self.Refresh()
        invoke(self.on_image, self.path)

    def _report(self, message: str) -> None:
        from amulet_map_editor.api.wx import nonblocking

        nonblocking.notify(
            self,
            "Texture not loaded",
            message,
            severity="warning",
            details=f"Slot: {self.slot_id or 'unnamed'}",
        )

    # -- events --------------------------------------------------------------
    def _on_hover(self, event: wx.MouseEvent) -> None:
        self._hovered = event.GetEventType() == wx.EVT_ENTER_WINDOW.typeId
        self.Refresh()
        event.Skip()

    def _on_key(self, event: wx.KeyEvent) -> None:
        if event.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_SPACE):
            self.browse()
            return
        if event.GetKeyCode() == wx.WXK_DELETE and self.path:
            self.clear()
            return
        event.Skip()

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = self.palette()
        parent = self.GetParent()
        backdrop = parent.GetBackgroundColour() if parent else palette.surface
        dc, gcdc = paint_context(self, backdrop if backdrop.IsOk() else palette.surface)
        width, height = self.GetClientSize()
        rect = wx.Rect(0, 0, width, height)
        radius = tokens.scaled(10)
        tokens.draw_round_rect(gcdc, rect, radius, palette.surface_container)
        if self._preview is not None and self._preview.IsOk():
            scale = min(
                width / max(1, self._preview.GetWidth()),
                height / max(1, self._preview.GetHeight()),
            )
            image = self._preview.ConvertToImage().Scale(
                max(1, int(self._preview.GetWidth() * scale)),
                max(1, int(self._preview.GetHeight() * scale)),
                wx.IMAGE_QUALITY_HIGH,
            )
            bitmap = wx.Bitmap(image)
            dc.DrawBitmap(
                bitmap,
                (width - bitmap.GetWidth()) // 2,
                (height - bitmap.GetHeight()) // 2,
                True,
            )
            tokens.draw_round_rect(gcdc, rect, radius, None, palette.outline_variant)
        else:
            draw_dashed_round_rect(
                gcdc,
                rect,
                radius,
                palette.primary if self._hovered else palette.outline,
            )
            gcdc.SetFont(tokens.font(self, point_size(12)))
            gcdc.SetTextForeground(palette.on_surface_variant)
            lines = wrap_text(gcdc, self.hint, width - tokens.scaled(24), 2)
            y = (height - gcdc.GetCharHeight() * len(lines)) // 2
            for line in lines:
                text_width = gcdc.GetTextExtent(line)[0]
                gcdc.DrawText(line, (width - text_width) // 2, y)
                y += gcdc.GetCharHeight()
        if self.HasFocus():
            draw_focus_ring(gcdc, rect, radius, palette.primary)
        del gcdc


class ListRow(wx.Control, _Interactive):
    """One record row: an optional swatch, a name, a detail, and a tag.

    A row with no ``on_click`` is a record rather than a control, and is drawn
    as one -- no pointer cursor and no hover fill -- because a row that looks
    pressable and does nothing is worse than a row that looks like text.
    """

    SWATCH = 26

    def __init__(
        self,
        parent: wx.Window,
        name: str,
        detail: str = "",
        tag: str = "",
        *,
        swatch: str = "",
        on_click: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(parent, style=wx.BORDER_NONE | wx.WANTS_CHARS)
        self.row_name = str(name)
        self.detail = str(detail)
        self.tag = str(tag)
        self.swatch = str(swatch)
        self.on_click = on_click
        accessible = " · ".join(
            part for part in (self.row_name, self.detail, self.tag) if part
        )
        self._install(accessible or "Row", listen=False)
        self._bind_interaction()
        if on_click is None:
            self.SetCursor(wx.Cursor(wx.CURSOR_ARROW))
        self.SetInitialSize(self.DoGetBestSize())

    def AcceptsFocus(self) -> bool:  # noqa: N802 - wx API spelling
        return self.on_click is not None

    def AcceptsFocusFromKeyboard(self) -> bool:  # noqa: N802 - wx API spelling
        return self.on_click is not None

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        dc = wx.ClientDC(self)
        dc.SetFont(tokens.font(self, point_size(13), _MEDIUM))
        name_height = dc.GetCharHeight()
        dc.SetFont(tokens.font(self, point_size(12)))
        detail_height = dc.GetCharHeight() if self.detail else 0
        height = max(
            tokens.control_height(),
            name_height + detail_height + tokens.scaled(20),
        )
        return wx.Size(tokens.scaled(240), height)

    def activate(self) -> None:
        if self.on_click is None:
            return
        invoke(self.on_click)
        self._emit_button()

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = self.palette()
        parent = self.GetParent()
        backdrop = parent.GetBackgroundColour() if parent else palette.surface
        dc, gcdc = paint_context(self, backdrop if backdrop.IsOk() else palette.surface)
        width, height = self.GetClientSize()
        rect = wx.Rect(0, 0, width, height)
        radius = tokens.scaled(tokens.RADIUS_SM + 2)
        interactive = self.on_click is not None
        border = (
            palette.primary
            if interactive and (self._hovered or self.HasFocus())
            else palette.outline_variant
        )
        tokens.draw_round_rect(gcdc, rect, radius, palette.surface_container, border)
        left = tokens.scaled(12)
        if self.swatch:
            side = tokens.scaled(self.SWATCH)
            tokens.draw_round_rect(
                gcdc,
                wx.Rect(left, (height - side) // 2, side, side),
                tokens.scaled(6),
                colour_of(self.swatch),
                palette.outline_variant,
            )
            left += side + tokens.scaled(11)
        gcdc.SetFont(tokens.mono_font(self, point_size(11)))
        tag_width = gcdc.GetTextExtent(self.tag)[0] if self.tag else 0
        if self.tag:
            gcdc.SetTextForeground(palette.primary)
            gcdc.DrawText(
                self.tag,
                width - tokens.scaled(12) - tag_width,
                (height - gcdc.GetCharHeight()) // 2,
            )
        available = max(0, width - left - tag_width - tokens.scaled(24))
        gcdc.SetFont(tokens.font(self, point_size(13), _MEDIUM))
        gcdc.SetTextForeground(palette.on_surface)
        name_height = gcdc.GetCharHeight()
        detail_height = 0
        if self.detail:
            detail_font = tokens.font(self, point_size(12))
            gcdc.SetFont(detail_font)
            detail_height = gcdc.GetCharHeight()
        top = (height - name_height - detail_height) // 2
        gcdc.SetFont(tokens.font(self, point_size(13), _MEDIUM))
        gcdc.DrawText(elide(gcdc, self.row_name, available), left, top)
        if self.detail:
            gcdc.SetFont(tokens.font(self, point_size(12)))
            gcdc.SetTextForeground(palette.on_surface_variant)
            gcdc.DrawText(elide(gcdc, self.detail, available), left, top + name_height)
        if self.HasFocus():
            draw_focus_ring(gcdc, rect, radius, palette.primary)
        del gcdc


# ----------------------------------------------------------------------------
# composite editors
# ----------------------------------------------------------------------------


class VectorField(wx.Panel, _Themed):
    """An axis-coloured coordinate entry, one bounded box per component.

    ``parts`` is a list of ``(axis, value)`` pairs so a two- or four-component
    vector is as ordinary as a three-component one.  ``on_change`` receives the
    whole tuple of values, because a coordinate only means something as a set.
    """

    def __init__(
        self,
        parent: wx.Window,
        parts: Sequence[Tuple[str, str]],
        *,
        on_change: Optional[Callable[[Tuple[str, ...]], None]] = None,
    ) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self.on_change = on_change
        self.axes: List[str] = []
        self.boxes: List[_TextBox] = []
        self._install("Coordinate", listen=False)
        row = wx.BoxSizer(wx.HORIZONTAL)
        for axis, value in parts:
            axis_name = str(axis)
            self.axes.append(axis_name)
            box = _TextBox(
                self,
                value=str(value),
                mono=True,
                height=30,
                prefix=axis_name,
                prefix_colour=AXIS_COLOURS.get(axis_name.lower(), ""),
                on_change=lambda _text: self._changed(),
                name=f"{axis_name} coordinate",
                size_px=12,
                fill_role="surface",
            )
            self.boxes.append(box)
            row.Add(box, 1, wx.RIGHT, tokens.scaled(7))
        self.pick_button = StudioButton(
            self,
            "⌖",
            variant="outlined",
            on_click=self._use_camera,
            name="Use the camera position",
            hint="Fill these values from the camera position",
            height=30,
            min_width=30,
        )
        row.Add(self.pick_button, 0)
        self.SetSizer(row)
        self._camera_source: Optional[Callable[[], Sequence[str]]] = None
        self._apply_theme(self.palette())
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)

    def values(self) -> Tuple[str, ...]:
        """Return the current component values in order."""
        return tuple(box.value() for box in self.boxes)

    def set_values(self, values: Sequence[str], *, notify: bool = False) -> None:
        """Replace every component that has a matching entry in ``values``."""
        for box, value in zip(self.boxes, values):
            box.set_value(str(value))
        if notify:
            invoke(self.on_change, self.values())

    def set_camera_source(self, source: Callable[[], Sequence[str]]) -> None:
        """Register what the camera button should read the position from."""
        self._camera_source = source

    def _use_camera(self) -> None:
        if self._camera_source is None:
            from amulet_map_editor.api.wx import nonblocking

            nonblocking.notify(
                self,
                "No camera connected",
                "This window is not attached to a viewport, so there is no "
                "camera position to copy.",
                severity="warning",
            )
            return
        values = invoke(self._camera_source) or ()
        self.set_values(list(values), notify=True)

    def _changed(self) -> None:
        invoke(self.on_change, self.values())

    def _apply_theme(self, palette: tokens.StudioPalette) -> None:
        backdrop = (
            self.GetParent().GetBackgroundColour()
            if self.GetParent()
            else palette.surface
        )
        self.SetBackgroundColour(backdrop if backdrop.IsOk() else palette.surface)

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        dc, gcdc = paint_context(self, self.GetBackgroundColour())
        del gcdc
        del dc


class _Slot(wx.Control, _Interactive):
    """One inventory slot: a short label, a stack count, and a hover border."""

    SIDE = 38

    def __init__(
        self,
        parent: wx.Window,
        slot: Mapping[str, Any],
        *,
        on_click: Optional[Callable[[Mapping[str, Any]], None]] = None,
    ) -> None:
        super().__init__(parent, style=wx.BORDER_NONE | wx.WANTS_CHARS)
        self.slot = dict(slot)
        self.on_click = on_click
        title = str(self.slot.get("title") or self.slot.get("short") or "Empty slot")
        self._install(title, listen=False)
        self.SetToolTip(title)
        self._bind_interaction()
        self.SetInitialSize(self.DoGetBestSize())

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        side = tokens.scaled(self.SIDE)
        return wx.Size(side, side)

    def activate(self) -> None:
        invoke(self.on_click, self.slot)

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = self.palette()
        parent = self.GetParent()
        backdrop = parent.GetBackgroundColour() if parent else palette.surface
        dc, gcdc = paint_context(self, backdrop if backdrop.IsOk() else palette.surface)
        width, height = self.GetClientSize()
        rect = wx.Rect(0, 0, width, height)
        radius = tokens.scaled(7)
        block_id = str(self.slot.get("block_id") or "")
        if block_id:
            dc.DrawBitmap(
                blocks.block_tile_bitmap(block_id, max(1, min(width, height))),
                0,
                0,
                False,
            )
        else:
            tokens.draw_round_rect(gcdc, rect, radius, palette.surface_container_high)
        selected = bool(self.slot.get("selected"))
        border = (
            palette.primary
            if (selected or self._hovered or self.HasFocus())
            else palette.outline_variant
        )
        tokens.draw_round_rect(gcdc, rect, radius, None, border)
        short = str(self.slot.get("short") or "")
        if short and not block_id:
            gcdc.SetFont(tokens.mono_font(self, point_size(9)))
            gcdc.SetTextForeground(palette.on_surface_variant)
            text = elide(gcdc, short, width - tokens.scaled(6))
            text_width, text_height = gcdc.GetTextExtent(text)
            gcdc.DrawText(text, (width - text_width) // 2, (height - text_height) // 2)
        count = str(self.slot.get("count") or "")
        if count:
            gcdc.SetFont(tokens.mono_font(self, point_size(9), _MEDIUM))
            gcdc.SetTextForeground(palette.on_surface)
            count_width, count_height = gcdc.GetTextExtent(count)
            gcdc.DrawText(
                count,
                width - count_width - tokens.scaled(3),
                height - count_height - tokens.scaled(2),
            )
        if self.HasFocus():
            draw_focus_ring(gcdc, rect, radius, palette.primary)
        del gcdc


class SlotGrid(wx.Panel, _Themed):
    """A wrapping grid of inventory slots.

    Each slot is its own control so it can be tabbed to, named for a screen
    reader, and activated from the keyboard; a single painted grid would look
    the same and be reachable only with a pointer.
    """

    def __init__(self, parent: wx.Window, slots: Sequence[Mapping[str, Any]]) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self._install("Inventory slots", listen=False)
        self.slots: List[_Slot] = []
        self.on_slot: Optional[Callable[[Mapping[str, Any]], None]] = None
        sizer = wx.WrapSizer(wx.HORIZONTAL)
        for slot in slots:
            control = _Slot(self, slot, on_click=self._clicked)
            self.slots.append(control)
            sizer.Add(control, 0, wx.RIGHT | wx.BOTTOM, tokens.scaled(5))
        self.SetSizer(sizer)
        self._apply_theme(self.palette())
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)

    def _clicked(self, slot: Mapping[str, Any]) -> None:
        invoke(self.on_slot, slot)

    def _apply_theme(self, palette: tokens.StudioPalette) -> None:
        backdrop = (
            self.GetParent().GetBackgroundColour()
            if self.GetParent()
            else palette.surface
        )
        self.SetBackgroundColour(backdrop if backdrop.IsOk() else palette.surface)

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        dc, gcdc = paint_context(self, self.GetBackgroundColour())
        del gcdc
        del dc


class TreeRows(wx.Panel, _Themed):
    """A monospaced tree drawn as one focusable list.

    Arrow keys move the selection and Enter reports it, which is how a list
    behaves on every platform; making each line its own tab stop would put a
    forty-node tree between the user and the next control.
    """

    ROW_HEIGHT = 28

    def __init__(
        self,
        parent: wx.Window,
        nodes: Sequence[Any],
        *,
        on_select: Optional[Callable[[int, str], None]] = None,
    ) -> None:
        super().__init__(parent, style=wx.WANTS_CHARS)
        self.on_select = on_select
        self.nodes = [self._normalise(node) for node in nodes]
        self.selected = next(
            (index for index, node in enumerate(self.nodes) if node[2]), 0
        )
        self._install("Tree")
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.Bind(wx.EVT_LEFT_DOWN, self._on_click)
        self.Bind(wx.EVT_KEY_DOWN, self._on_key)
        self.Bind(wx.EVT_SET_FOCUS, lambda event: (self.Refresh(), event.Skip()))
        self.Bind(wx.EVT_KILL_FOCUS, lambda event: (self.Refresh(), event.Skip()))
        self.SetInitialSize(self.DoGetBestSize())

    @staticmethod
    def _normalise(node: Any) -> Tuple[str, str, bool]:
        if isinstance(node, Mapping):
            return (
                str(node.get("glyph", "")),
                str(node.get("label", "")),
                bool(node.get("selected", False)),
            )
        return (
            str(getattr(node, "glyph", "")),
            str(getattr(node, "label", node)),
            bool(getattr(node, "selected", False)),
        )

    def AcceptsFocus(self) -> bool:  # noqa: N802 - wx API spelling
        return True

    def AcceptsFocusFromKeyboard(self) -> bool:  # noqa: N802 - wx API spelling
        return True

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        dc = wx.ClientDC(self)
        dc.SetFont(tokens.mono_font(self, point_size(12)))
        width = tokens.scaled(200)
        for glyph, label, _selected in self.nodes:
            width = max(
                width, dc.GetTextExtent(f"{glyph} {label}")[0] + tokens.scaled(40)
            )
        rows = max(1, len(self.nodes))
        return wx.Size(width, rows * tokens.scaled(self.ROW_HEIGHT) + tokens.scaled(20))

    def select(self, index: int, *, notify: bool = True) -> None:
        """Move the selection, wrapping inside the list."""
        if not self.nodes:
            return
        self.selected = max(0, min(len(self.nodes) - 1, int(index)))
        self.SetName(f"Tree: {self.nodes[self.selected][1]}")
        self.Refresh()
        if notify:
            invoke(self.on_select, self.selected, self.nodes[self.selected][1])

    def _row_at(self, y: int) -> int:
        inner = y - tokens.scaled(10)
        return inner // max(1, tokens.scaled(self.ROW_HEIGHT))

    def _on_click(self, event: wx.MouseEvent) -> None:
        self.SetFocus()
        index = self._row_at(event.GetPosition().y)
        if 0 <= index < len(self.nodes):
            self.select(index)
        event.Skip()

    def _on_key(self, event: wx.KeyEvent) -> None:
        code = event.GetKeyCode()
        if code == wx.WXK_DOWN:
            self.select(self.selected + 1)
        elif code == wx.WXK_UP:
            self.select(self.selected - 1)
        elif code == wx.WXK_HOME:
            self.select(0)
        elif code == wx.WXK_END:
            self.select(len(self.nodes) - 1)
        elif code in (wx.WXK_RETURN, wx.WXK_SPACE):
            self.select(self.selected)
        else:
            event.Skip()

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = self.palette()
        parent = self.GetParent()
        backdrop = parent.GetBackgroundColour() if parent else palette.surface
        dc, gcdc = paint_context(self, backdrop if backdrop.IsOk() else palette.surface)
        width, height = self.GetClientSize()
        frame = wx.Rect(0, 0, width, height)
        tokens.draw_round_rect(
            gcdc,
            frame,
            tokens.scaled(tokens.RADIUS_SM + 2),
            palette.surface_container,
            palette.outline_variant,
        )
        gcdc.SetFont(tokens.mono_font(self, point_size(12)))
        row_height = tokens.scaled(self.ROW_HEIGHT)
        y = tokens.scaled(10)
        for index, (glyph, label, _selected) in enumerate(self.nodes):
            row = wx.Rect(tokens.scaled(6), y, width - tokens.scaled(12), row_height)
            if index == self.selected:
                tokens.draw_round_rect(
                    gcdc, row, tokens.scaled(6), palette.primary_container
                )
                ink = palette.on_primary_container
            else:
                ink = palette.on_surface
            text_y = y + (row_height - gcdc.GetCharHeight()) // 2
            x = row.x + tokens.scaled(8)
            if glyph:
                gcdc.SetTextForeground(
                    palette.on_primary_container
                    if index == self.selected
                    else palette.primary
                )
                gcdc.DrawText(glyph, x, text_y)
                x += gcdc.GetTextExtent(glyph)[0] + tokens.scaled(8)
            gcdc.SetTextForeground(ink)
            gcdc.DrawText(
                elide(gcdc, label, max(0, row.GetRight() - x - tokens.scaled(6))),
                x,
                text_y,
            )
            y += row_height
        if self.HasFocus():
            draw_focus_ring(
                gcdc, frame, tokens.scaled(tokens.RADIUS_SM + 2), palette.primary
            )
        del gcdc


class _KeyButton(wx.Control, _Interactive):
    """One of the two independent keys that arm a :class:`KeyGate`."""

    def __init__(
        self,
        parent: wx.Window,
        label: str,
        *,
        on_change: Optional[Callable[[bool], None]] = None,
    ) -> None:
        super().__init__(parent, style=wx.BORDER_NONE | wx.WANTS_CHARS)
        wx.Control.SetLabel(self, str(label))
        self.held = False
        self.on_change = on_change
        self._install(f"{label} — hold this key", listen=False)
        self._bind_interaction()
        self.SetInitialSize(self.DoGetBestSize())

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        dc = wx.ClientDC(self)
        dc.SetFont(tokens.font(self, point_size(13)))
        width = dc.GetTextExtent(self.GetLabel())[0] + tokens.scaled(28)
        return wx.Size(width, dc.GetCharHeight() + tokens.scaled(28))

    def set_held(self, held: bool, *, notify: bool = True) -> None:
        """Hold or release this key."""
        self.held = bool(held)
        self.SetName(f"{self.GetLabel()} — {'held' if self.held else 'not held yet'}")
        self.Refresh()
        if notify:
            invoke(self.on_change, self.held)

    def activate(self) -> None:
        self.set_held(not self.held)

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = self.palette()
        parent = self.GetParent()
        backdrop = parent.GetBackgroundColour() if parent else palette.surface
        dc, gcdc = paint_context(self, backdrop if backdrop.IsOk() else palette.surface)
        width, height = self.GetClientSize()
        rect = wx.Rect(0, 0, width, height)
        radius = tokens.scaled(11)
        if self.held:
            fill, ink, border = (
                palette.primary_container,
                palette.on_primary_container,
                palette.primary,
            )
        else:
            fill, ink, border = (
                palette.surface_container,
                palette.primary if self._hovered else palette.on_surface,
                palette.primary if self._hovered else palette.outline_variant,
            )
        tokens.draw_round_rect(gcdc, rect, radius, fill, border)
        gcdc.SetFont(tokens.font(self, point_size(13)))
        gcdc.SetTextForeground(ink)
        label = self.GetLabel() + (" · held" if self.held else "")
        text = elide(gcdc, label, width - tokens.scaled(16))
        text_width, text_height = gcdc.GetTextExtent(text)
        gcdc.DrawText(text, (width - text_width) // 2, (height - text_height) // 2)
        if self.HasFocus():
            draw_focus_ring(gcdc, rect, radius, palette.primary)
        del gcdc


class KeyGate(wx.Panel, _Themed):
    """The two-key gate every destructive action goes through.

    Both keys must be held before the slider does anything, and authorisation
    only happens on full travel; releasing the slider short of the end returns
    it to the start rather than leaving a half-armed control.  The emergency
    exit is always available, Escape cancels, and the completion flourish is
    skipped when the platform asks for reduced motion.
    """

    def __init__(
        self,
        parent: wx.Window,
        *,
        on_authorize: Optional[Callable[[], None]] = None,
        on_exit: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self.on_authorize = on_authorize
        self.on_exit = on_exit
        self.authorized = False
        self._flourish = 0
        self._install("Two-key authorisation")
        self.status = wx.StaticText(
            self,
            label=(
                "Hold both keys, then drag the slider all the way to the right "
                "to authorise."
            ),
        )
        self.status.SetName("Authorisation status")
        keys = wx.BoxSizer(wx.HORIZONTAL)
        self.key_a = _KeyButton(self, "Press A", on_change=self._key_changed)
        self.key_l = _KeyButton(self, "Press L", on_change=self._key_changed)
        keys.Add(self.key_a, 1, wx.RIGHT, tokens.scaled(tokens.SPACE_SM))
        keys.Add(self.key_l, 1)
        self.slider = wx.Slider(
            self, value=0, minValue=0, maxValue=100, style=wx.SL_HORIZONTAL
        )
        self.slider.SetName("Slide all the way to authorise")
        self.slider.Enable(False)
        self.progress = ProgressRow(self, "Authorisation progress", 0.0, "0%")
        self.exit_button = StudioButton(
            self,
            "Emergency exit",
            variant="danger",
            on_click=self.emergency_exit,
            name="Emergency exit",
            hint="Cancel immediately and leave everything unchanged",
        )
        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(self.status, 0, wx.EXPAND | wx.BOTTOM, tokens.scaled(tokens.SPACE_SM))
        root.Add(keys, 0, wx.EXPAND | wx.BOTTOM, tokens.scaled(tokens.SPACE_SM))
        root.Add(self.slider, 0, wx.EXPAND)
        root.Add(
            self.progress,
            0,
            wx.EXPAND | wx.TOP | wx.BOTTOM,
            tokens.scaled(tokens.SPACE_SM),
        )
        root.Add(self.exit_button, 0)
        self.SetSizer(root)
        self._timer = wx.Timer(self)
        self._apply_theme(self.palette())
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.Bind(wx.EVT_TIMER, self._on_timer, self._timer)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
        self.slider.Bind(wx.EVT_SLIDER, self._on_slide)
        self.slider.Bind(wx.EVT_SCROLL_THUMBRELEASE, self._on_release)

    # -- state ---------------------------------------------------------------
    def keys_held(self) -> bool:
        """Return whether both keys are currently held."""
        return self.key_a.held and self.key_l.held

    def is_authorized(self) -> bool:
        """Return whether the gate has been opened."""
        return self.authorized

    def reset(self) -> None:
        """Return the gate to its untouched state."""
        self.authorized = False
        self._flourish = 0
        self.key_a.set_held(False, notify=False)
        self.key_l.set_held(False, notify=False)
        self.slider.SetValue(0)
        self.slider.Enable(False)
        self.progress.set_progress(0.0, "0%")
        self.status.SetLabel(
            "Hold both keys, then drag the slider all the way to the right to "
            "authorise."
        )
        self.Layout()

    def emergency_exit(self) -> None:
        """Abandon the gate at once and report it, whatever state it is in."""
        self.reset()
        self.status.SetLabel("Cancelled. Nothing was changed.")
        invoke(self.on_exit)

    # -- events --------------------------------------------------------------
    def _key_changed(self, _held: bool) -> None:
        ready = self.keys_held()
        self.slider.Enable(ready and not self.authorized)
        if ready:
            self.status.SetLabel("Both keys are held. Drag the slider to the end.")
        else:
            self.status.SetLabel("Hold both keys before the slider will move.")
        if not ready:
            self.slider.SetValue(0)
            self.progress.set_progress(0.0, "0%")
        self.Layout()

    def _on_slide(self, _event: wx.CommandEvent) -> None:
        value = self.slider.GetValue()
        self.progress.set_progress(value / 100.0, f"{value}%")
        if value >= 100 and not self.authorized:
            self._authorize()

    def _on_release(self, event: wx.ScrollEvent) -> None:
        if not self.authorized and self.slider.GetValue() < 100:
            self.slider.SetValue(0)
            self.progress.set_progress(0.0, "0%")
            self.status.SetLabel("Not authorised — the slider has to reach the end.")
        event.Skip()

    def _authorize(self) -> None:
        self.authorized = True
        self.slider.Enable(False)
        self.progress.set_progress(1.0, "100%")
        self.status.SetLabel("Authorised.")
        self.Layout()
        if reduced_motion():
            self._flourish = 0
            self.Refresh()
        else:
            self._flourish = 6
            self._timer.Start(50)
        invoke(self.on_authorize)

    def _on_timer(self, _event: wx.TimerEvent) -> None:
        self._flourish -= 1
        if self._flourish <= 0:
            self._flourish = 0
            self._timer.Stop()
        self.Refresh()

    def _on_char_hook(self, event: wx.KeyEvent) -> None:
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.emergency_exit()
            return
        event.Skip()

    def _apply_theme(self, palette: tokens.StudioPalette) -> None:
        backdrop = (
            self.GetParent().GetBackgroundColour()
            if self.GetParent()
            else palette.surface
        )
        self.SetBackgroundColour(backdrop if backdrop.IsOk() else palette.surface)
        status = getattr(self, "status", None)
        if status is not None:
            status.SetForegroundColour(palette.on_surface_variant)
            status.SetFont(tokens.font(self, point_size(12)))
        slider = getattr(self, "slider", None)
        if slider is not None:
            slider.SetBackgroundColour(self.GetBackgroundColour())
            slider.SetForegroundColour(palette.primary)

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = self.palette()
        dc, gcdc = paint_context(self, self.GetBackgroundColour())
        if self._flourish:
            width, height = self.GetClientSize()
            ring = wx.Rect(0, 0, width, height)
            tokens.draw_round_rect(
                gcdc,
                ring,
                tokens.scaled(tokens.RADIUS_MD),
                None,
                tokens.blend(palette.surface, palette.primary, self._flourish / 6.0),
                border_width=2,
            )
        del gcdc


class CollapsibleSection(wx.Panel, _Themed):
    """A titled block that remembers whether the user left it open.

    Descriptive content starts collapsed so a window opens on the controls
    rather than on prose; a ``remember_key`` makes that choice survive a
    restart, because a section a user opens every session should not need
    opening every session.
    """

    def __init__(
        self,
        parent: wx.Window,
        title: str,
        *,
        expanded: bool = True,
        remember_key: str = "",
    ) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self.title = str(title)
        self.remember_key = str(remember_key)
        stored = section_states().get(self.remember_key) if self.remember_key else None
        self.expanded = bool(expanded if stored is None else stored)
        self._install(self.title or "Section", listen=False)
        self.header = StudioButton(
            self,
            self.title,
            variant="text",
            glyph="▾" if self.expanded else "▸",
            on_click=self.toggle,
            name=f"{self.title} — {'expanded' if self.expanded else 'collapsed'}",
            hint="Show or hide this section",
        )
        self.body = wx.Panel(self, style=wx.TAB_TRAVERSAL)
        self.body_sizer = wx.BoxSizer(wx.VERTICAL)
        self.body.SetSizer(self.body_sizer)
        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(self.header, 0, wx.EXPAND)
        root.Add(self.body, 1, wx.EXPAND | wx.LEFT, tokens.scaled(tokens.SPACE_SM))
        self.SetSizer(root)
        self.body.Show(self.expanded)
        self._apply_theme(self.palette())
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)

    def toggle(self) -> None:
        """Flip the section open or closed and remember the choice."""
        self.set_expanded(not self.expanded)

    def set_expanded(self, expanded: bool) -> None:
        """Open or close the section, persisting a remembered key."""
        self.expanded = bool(expanded)
        self.body.Show(self.expanded)
        self.header.glyph = "▾" if self.expanded else "▸"
        self.header.SetName(
            f"{self.title} — {'expanded' if self.expanded else 'collapsed'}"
        )
        self.header.Refresh()
        self.Layout()
        parent = self.GetParent()
        if parent is not None:
            parent.Layout()
        if self.remember_key:
            remember_section(self.remember_key, self.expanded)

    def _apply_theme(self, palette: tokens.StudioPalette) -> None:
        backdrop = (
            self.GetParent().GetBackgroundColour()
            if self.GetParent()
            else palette.surface
        )
        self.SetBackgroundColour(backdrop if backdrop.IsOk() else palette.surface)
        body = getattr(self, "body", None)
        if body is not None:
            body.SetBackgroundColour(self.GetBackgroundColour())

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        dc, gcdc = paint_context(self, self.GetBackgroundColour())
        del gcdc
        del dc


class BulkActionBar(wx.Panel, _Themed):
    """The actions every list offers over a selection, plus an honest count.

    ``on_action`` receives the action's label.  The count line says what is
    selected rather than what is visible, because those two numbers differ the
    moment a filter is applied and acting on the wrong one is how a bulk delete
    takes more than it was asked to.
    """

    DEFAULT_ACTIONS: Tuple[str, ...] = (
        "Select all",
        "Select none",
        "Invert selection",
        "Export…",
        "Delete…",
    )

    def __init__(
        self,
        parent: wx.Window,
        *,
        on_action: Optional[Callable[[str], None]] = None,
        actions: Sequence[str] = DEFAULT_ACTIONS,
    ) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self.on_action = on_action
        self._install("Bulk actions", listen=False)
        self.count = wx.StaticText(self, label="Nothing selected")
        self.count.SetName("Selection count")
        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(self.count, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, tokens.SPACE_MD)
        self.buttons: List[StudioButton] = []
        for label in actions:
            variant = "danger" if label.lower().startswith("delete") else "outlined"
            button = StudioButton(
                self,
                str(label),
                variant=variant,
                on_click=lambda text=str(label): self._run(text),
                name=str(label),
                hint=f"{label} for the current selection",
            )
            self.buttons.append(button)
            row.Add(button, 0, wx.RIGHT, tokens.scaled(tokens.SPACE_SM))
        self.SetSizer(row)
        self._apply_theme(self.palette())
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)

    def set_count(self, selected: int, total: int = 0) -> None:
        """State how much of the collection the actions would touch."""
        if selected <= 0:
            text = "Nothing selected"
        elif total:
            text = f"{selected} of {total} selected"
        else:
            text = f"{selected} selected"
        self.count.SetLabel(text)
        self.count.SetName(f"Selection count: {text}")
        self.Layout()

    def _run(self, label: str) -> None:
        invoke(self.on_action, label)

    def _apply_theme(self, palette: tokens.StudioPalette) -> None:
        backdrop = (
            self.GetParent().GetBackgroundColour()
            if self.GetParent()
            else palette.surface
        )
        self.SetBackgroundColour(backdrop if backdrop.IsOk() else palette.surface)
        count = getattr(self, "count", None)
        if count is not None:
            count.SetForegroundColour(palette.on_surface_variant)
            count.SetFont(tokens.font(self, point_size(12)))

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        dc, gcdc = paint_context(self, self.GetBackgroundColour())
        del gcdc
        del dc


__all__ = [
    "AXIS_COLOURS",
    "BUTTON_VARIANTS",
    "AnchoredPopup",
    "BulkActionBar",
    "Card",
    "Chip",
    "CollapsibleSection",
    "Divider",
    "FaceRow",
    "IMAGE_EXTENSIONS",
    "ImageSlot",
    "KeyGate",
    "ListRow",
    "MAX_IMAGE_BYTES",
    "OutlinedField",
    "PathField",
    "ProgressRow",
    "RangeRow",
    "SECTION_STATE_ID",
    "SearchBar",
    "SearchableChoice",
    "SectionLabel",
    "SlotGrid",
    "Stepper",
    "StudioButton",
    "Swatch",
    "TextureTile",
    "ToggleSwitch",
    "TreeRows",
    "VectorField",
    "colour_of",
    "draw_dashed_round_rect",
    "draw_focus_ring",
    "draw_tracked_text",
    "elide",
    "format_number",
    "invoke",
    "paint_context",
    "point_size",
    "reduced_motion",
    "remember_section",
    "section_states",
    "tracked_width",
    "wrap_text",
]
