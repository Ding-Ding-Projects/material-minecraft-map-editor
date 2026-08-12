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

import contextlib
import logging
import os
import re
from typing import (
    Any,
    Callable,
    Dict,
    Iterator,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
)

import wx

from amulet_map_editor.api import config
from amulet_map_editor.api.studio import blocks, copy, tokens
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


class _WidestTextDC:
    """A measuring facade that never under-reports how wide text will draw.

    ``render_to`` is not always handed a ``wx.GCDC``: the ordinary screen
    paints through one (:func:`paint_context` wraps it around the buffered
    paint context), but :func:`elide` and every button's own drawing accept
    *whatever* ``dc`` the caller passes -- and a capture taken on a machine
    with nothing composited, or the plain-device-context fallback
    :func:`paint_context` itself documents, hands over a bare
    ``wx.ClientDC``/``wx.MemoryDC`` instead.  The two backends do not report
    the same width for the same string, and -- unlike the historical "Confirm
    clone" case this class replaced a flat GCDC-only measurement for -- the
    *wider* one is not reliably the same backend from one label to the next.
    "Delete Unselected Chunks" measured six pixels wider through a plain
    ``wx.MemoryDC`` than through the GCDC this used to measure with alone; a
    button sized to the narrower of the two clipped its own label the moment
    something painted it with the other.

    Reporting the larger of the two extents removes the direction dependency
    entirely: a control sized from this can never be a hair narrower than
    either backend actually needs to draw it.
    """

    def __init__(self, primary: wx.DC, secondary: Optional[wx.DC]) -> None:
        self._primary = primary
        self._secondary = secondary

    def __getattr__(self, name: str) -> Any:
        return getattr(self._primary, name)

    def SetFont(self, font: wx.Font) -> None:  # noqa: N802 - wx API spelling
        self._primary.SetFont(font)
        if self._secondary is not None:
            self._secondary.SetFont(font)

    def GetTextExtent(self, text: str) -> wx.Size:  # noqa: N802 - wx API spelling
        primary = self._primary.GetTextExtent(text)
        if self._secondary is None:
            return primary
        secondary = self._secondary.GetTextExtent(text)
        return wx.Size(max(primary[0], secondary[0]), max(primary[1], secondary[1]))

    def GetCharHeight(self) -> int:  # noqa: N802 - wx API spelling
        primary = self._primary.GetCharHeight()
        if self._secondary is None:
            return primary
        return max(primary, self._secondary.GetCharHeight())


@contextlib.contextmanager
def measuring(window: wx.Window) -> Iterator[wx.DC]:
    """Yield a device context that measures text at least as wide as it draws.

    Every Studio surface *usually* paints through a ``wx.GCDC``:
    :func:`paint_context` wraps one around the buffered paint context, and a
    capture wraps one around its own bitmap.  A plain ``wx.ClientDC`` measures
    through GDI instead, and the two do not agree -- and either can be the
    wider one, depending on the label and font, so favouring one backend over
    the other is never safe.  On wxPython 4.3.1 / wxWidgets 3.3.3 the design's
    filled button face reports ``"Confirm clone"`` as 81 pixels wide through
    the client context and 83 through the graphics one, while
    ``"Delete Unselected Chunks"`` reports 123 through the graphics context and
    129 through a plain device context -- the opposite direction.

    A control sized from the narrower of the two measurements is *always* a
    hair narrower than the text some backend then has to draw, so the
    ellipsis in :func:`elide` fires on labels that were meant to fit exactly.
    :class:`_WidestTextDC` reports whichever extent is larger, so this always
    returns the size that fits both.
    """
    source = wx.ClientDC(window)
    try:
        wrapper: wx.DC = wx.GCDC(source)
    except TypeError:  # pragma: no cover - platform boundary
        # Without the wrapper the measurement is the platform's own, which is
        # also what such a build would paint with, so the two still agree.
        yield source
        return
    try:
        yield _WidestTextDC(wrapper, source)
    finally:
        del wrapper


#: Slack added to a measured label before it becomes a control's width.
#: ``GetTextExtent`` reports whole pixels while the graphics renderer lays glyphs
#: out on fractional positions, so a control sized to the reported width can
#: still be a fraction of a pixel short of the drawing.  One pixel each side
#: costs nothing and removes the last case where a label that fits is elided.
TEXT_SLACK = 1


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


def note_elision(window: wx.Window, full: str, drawn: str, *, hint: str = "") -> None:
    """Keep the whole of an elided label reachable from the control itself.

    Sizing a control from its measured text is the first half of the answer to
    a clipped label; the other half is what happens when a container genuinely
    cannot give a control the width its text needs.  A label cut to "Confirm
    clo…" with nothing behind it is information the interface has simply lost,
    and a screen-reader user hears the same stump.

    So the ellipsis is only ever half of the presentation: whenever a widget
    draws less than its full text it puts the full text in its own tooltip
    here, alongside whatever hint it already carried.  The accessible name is
    untouched, because every widget in this module is installed with its
    complete label as its name and keeps it when the drawing shortens -- what
    is on screen changes, what the control is called does not.

    The tooltip is only written when it would change, because this runs from a
    paint handler.
    """
    full_text = str(full)
    hint_text = str(hint or "")
    wanted = hint_text
    if full_text and str(drawn) != full_text:
        wanted = f"{full_text}\n{hint_text}" if hint_text else full_text
    if getattr(window, "_elision_tooltip", None) == wanted:
        return
    window._elision_tooltip = wanted
    try:
        window.SetToolTip(wanted or None)
    except (RuntimeError, TypeError):  # pragma: no cover - the window has gone
        log.debug("Could not record an elided label for %s", window.GetName())


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


#: Set the first time :func:`paint_context` falls all the way through to the
#: unwrapped device context.  The fallback is correct but degraded, and it can
#: run thousands of times a second, so it is reported once and then stays quiet:
#: a warning per paint would bury the report it is trying to make.
_paint_fallback_reported = False


#: Windows currently being drawn into a capture bitmap rather than the screen,
#: keyed by ``id``. Only ever non-empty inside :func:`render_via_paint`.
_capture_redirect: Dict[int, Tuple[wx.DC, wx.DC]] = {}

#: The names an owner-drawn widget binds to ``EVT_PAINT`` in this codebase.
#: Tried in order; the first callable one is the widget's drawing code.
_PAINT_HANDLER_NAMES = ("_on_paint", "_paint", "_on_draw")


def render_via_paint(window: wx.Window, dc: wx.DC, rect: wx.Rect) -> bool:
    """Draw ``window``'s own paint handler into ``dc`` at ``rect``.

    A widget that paints in ``EVT_PAINT`` can normally only be photographed by
    reading the screen underneath it, and a window positioned off-screen -- which
    is how captures avoid disturbing the desktop -- has no screen underneath it
    to read.  The result is a file where some controls are correct and others
    are white rectangles, with nothing in the capture reporting which.

    Rather than ask fourteen widget classes each to grow a second copy of their
    drawing code, this drives the drawing code they already have.  The shared
    :func:`paint_context` helper is the single point every one of them gets its
    device context from, so redirecting that for the duration of one call is
    enough to send an entire subtree into a bitmap instead of onto the screen.

    ``SetDeviceOrigin`` is what makes the widget's own coordinates -- which
    start at its top-left, as they must -- land at the right place in a
    composite of the whole window.

    Returns whether the widget drew.
    """
    handler = None
    for name in _PAINT_HANDLER_NAMES:
        candidate = getattr(window, name, None)
        if callable(candidate):
            handler = candidate
            break
    if handler is None:
        return False

    # wx.PaintEvent() takes an id on wxPython 4.3.1 -- constructing one without
    # arguments raises TypeError. That failure is caught below and looks
    # identical to "this widget cannot draw", so every widget fell silently
    # through to the blit route and arrived white, with the report calling it a
    # capture. Build the event the way this wx build wants it, and keep a stub
    # for a build that wants something else again: a paint handler uses almost
    # nothing of the event it is handed.
    try:
        event: Any = wx.PaintEvent(window.GetId())
    except TypeError:

        class _StubPaintEvent:
            def Skip(self, *_args: Any, **_kwargs: Any) -> None:
                return None

            def GetEventObject(self) -> wx.Window:
                return window

            def GetId(self) -> int:
                return window.GetId()

        event = _StubPaintEvent()

    # The origin is set BEFORE the wrapper is built, and this order is the
    # whole of it. A wx.GCDC carries its own graphics transform, taken from the
    # device context at the moment it is constructed; moving the origin
    # afterwards moves the plain context and leaves the wrapper where it was.
    #
    # Owner-drawn widgets do almost all their drawing through the wrapper --
    # that is what makes a rounded corner a curve rather than a staircase -- so
    # building it first sent every label, chip and card to the top-left of the
    # bitmap. The result was a capture with the interface drawn correctly in
    # one place and every piece of its text piled up in the corner, which reads
    # as a rendering catastrophe and is really two coordinate systems.
    origin = dc.GetDeviceOrigin()
    dc.SetDeviceOrigin(origin.x + rect.x, origin.y + rect.y)
    try:
        wrapper: wx.DC = wx.GCDC(dc)
    except TypeError:
        wrapper = dc

    key = id(window)
    _capture_redirect[key] = (dc, wrapper)
    try:
        handler(event)
        return True
    except Exception:  # noqa: BLE001 - a widget that cannot draw is the finding
        log.debug("render_via_paint failed for %s", window.GetName(), exc_info=True)
        return False
    finally:
        _capture_redirect.pop(key, None)
        if wrapper is not dc:
            del wrapper
        dc.SetDeviceOrigin(origin.x, origin.y)


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

    That last path is a real degradation, so it says so: it is logged once per
    process as a warning naming the wx build.  Every rounded corner, focus ring
    and elevation shadow renders stepped once it is taken and nothing else about
    the interface changes, which leaves nobody able to tell a degraded build
    from a badly drawn one.
    """
    redirect = _capture_redirect.get(id(window))
    if redirect is not None:
        # A capture is driving this widget's paint handler into a bitmap rather
        # than onto the screen. Handing back the capture's device context is
        # what lets the handler draw normally, with no knowledge that it is
        # being photographed and no second copy of its drawing code to keep in
        # step. See render_via_paint.
        #
        # The background is filled here for the same reason it is filled below:
        # a caller hands us a background because it expects to be drawing onto
        # it, and every widget in this codebase relies on that. Returning the
        # context without clearing left each one drawing onto whatever the
        # bitmap already held, so a page that paints cards and section labels
        # but no field of its own came out as light cards floating on pure
        # black -- which reads as a catastrophic theme failure in an interface
        # that has no dark surface in it at all.
        #
        # The fill is bounded to this widget's own client area rather than the
        # whole device context: the context is shared by the entire composite,
        # and clearing all of it would erase every sibling already drawn.
        capture_dc = redirect[0]
        size = window.GetClientSize()
        if size.width > 0 and size.height > 0:
            capture_dc.SetBrush(wx.Brush(background))
            capture_dc.SetPen(wx.Pen(background))
            capture_dc.DrawRectangle(0, 0, size.width, size.height)
        return redirect

    global _paint_fallback_reported
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
    if not _paint_fallback_reported:
        _paint_fallback_reported = True
        try:
            build = str(wx.version())
        except Exception:  # pragma: no cover - platform boundary
            build = "an unknown wxPython build"
        log.warning(
            "%s would not wrap either paint device context in wx.GCDC, so Studio "
            "surfaces are painting without antialiasing: rounded corners, focus "
            "rings and elevation shadows will look stepped. Reported once per "
            "session; every later paint takes the same path without logging.",
            build,
        )
    dc = wx.PaintDC(window)
    dc.SetBackground(wx.Brush(background))
    dc.Clear()
    return dc, dc


@contextlib.contextmanager
def translated(dc: wx.DC, rect: wx.Rect) -> Iterator[None]:
    """Move ``dc``'s origin to ``rect``'s corner for the enclosed drawing.

    Every :meth:`_Themed.render_to` body draws in its own coordinates, from
    ``0, 0`` to the widget's width and height, because that is what a paint
    handler has always given it.  A capture, though, draws a child into a
    parent's bitmap at the child's offset, so the same code has to land
    somewhere else on the surface.

    Shifting the device origin is what makes both true at once: the drawing
    code is unchanged and every coordinate in it is interpreted relative to
    ``rect``.  The previous origin is read rather than assumed -- a scrolled
    window's paint context carries one -- and restored on the way out even when
    the drawing raises, because a device context left translated would move
    every later paint on that surface.
    """
    origin = dc.GetDeviceOrigin()
    dc.SetDeviceOrigin(origin.x + rect.x, origin.y + rect.y)
    try:
        yield
    finally:
        dc.SetDeviceOrigin(origin.x, origin.y)


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

    # -- painting ------------------------------------------------------------
    def _backdrop(self) -> wx.Colour:
        """Return the colour this widget clears itself to before it draws.

        A Studio widget paints its own background, so it starts from whatever
        is behind it -- its parent's colour -- and draws its shape on top.  A
        widget whose backdrop is fixed by the design rather than inherited
        overrides this.
        """
        palette = self.palette()
        parent = self.GetParent()
        backdrop = parent.GetBackgroundColour() if parent else palette.surface
        return backdrop if backdrop.IsOk() else palette.surface

    def render_to(self, dc: wx.DC, rect: wx.Rect) -> None:
        """Draw this widget's current appearance into ``dc`` at ``rect``.

        This is the whole of a Studio widget's painting, reachable without a
        paint event, without a window handle, and without anybody looking at
        the screen.  That last part is the point.  ``wx.ClientDC`` *reads* a
        window's on-screen surface, so on a hidden desktop -- where nothing is
        ever composited -- it returns the buffer's leftovers rather than the
        interface; ``PrintWindow`` asks the window to draw, which native
        controls answer and owner-drawn ones do not, because there is no
        ``WM_PRINT`` handler behind an ``EVT_PAINT`` handler.  Both routes
        photographed this interface as empty rectangles.

        Calling the drawing code directly has neither problem: the appearance
        comes from the same method the screen gets, so a capture matrix on a
        hidden desktop and a running window cannot disagree.

        The default paints the widget's backdrop and nothing else, which is the
        honest appearance of a container that draws no shape of its own.  Every
        painted widget overrides it, and ``_on_paint`` below is a thin caller
        of whichever override applies.
        """
        with self._painting(dc, rect):
            pass

    @contextlib.contextmanager
    def _painting(self, dc: wx.DC, rect: wx.Rect) -> Iterator[wx.Rect]:
        """Prepare ``dc`` for one :meth:`render_to` body and yield its own rect.

        It does the two things every painted widget starts with: moves the
        origin to ``rect`` so the enclosed drawing can keep working in the
        widget's own coordinates, and fills the backdrop, which is what a
        paint context's ``Clear`` does on the way in.  Filling it here rather
        than only there is what makes ``render_to`` complete on its own -- a
        capture calls it with no paint context in sight, and a widget that drew
        its shape but not its background would show whatever its parent had
        painted through the corners its shape does not cover.
        """
        with translated(dc, rect):
            local = wx.Rect(0, 0, rect.width, rect.height)
            dc.SetBrush(wx.Brush(self._backdrop()))
            dc.SetPen(wx.TRANSPARENT_PEN)
            dc.DrawRectangle(local)
            yield local

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        """Paint the widget by asking it to render into its own paint context.

        Every Studio widget shares this handler: the drawing lives in
        :meth:`render_to`, so the screen and a capture take the same route
        through the same code rather than one of them taking a second one that
        can rot unnoticed.
        """
        dc, gcdc = paint_context(self, self._backdrop())
        width, height = self.GetClientSize()
        self.render_to(gcdc, wx.Rect(0, 0, width, height))
        del gcdc

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
            # Every Studio widget paints its own background in ``render_to``,
            # so the default GDI erase this would otherwise trigger repaints
            # nothing useful -- it just clears to the system brush a frame
            # before ``render_to`` draws over it, which is the flash a theme
            # change (or any other wide repaint) was putting across the
            # whole tree.
            self.Refresh(eraseBackground=False)
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
    # ``render_to``.  ``activate`` is deliberately not defined here: a default
    # would let a control that forgot one look finished while doing nothing,
    # whereas a missing attribute fails loudly the moment it is activated.
    # ``render_to`` does have a default, on ``_Themed``, because a widget that
    # forgot to override it draws its backdrop and is visibly blank rather than
    # raising inside a paint handler and leaving the whole surface unpainted.


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

    A button given an explicit ``name`` keeps it when its label changes.  That
    matters wherever the label is a *reading* rather than a name: an undo
    button whose label is the depth counter would otherwise introduce itself to
    a screen reader as "0", and then as "1", and be a different control every
    time the count moved.
    """

    #: Class level, because wx can reach ``SetLabel`` before ``__init__`` has
    #: bound the instance attribute, and an ``AttributeError`` raised there
    #: surfaces as a button that cannot be constructed at all.
    _named: bool = False

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
        # After ``_install``, which goes through the ``SetName`` override below
        # and would otherwise mark every button as explicitly named -- including
        # the ones whose name is only the label echoed back.
        self._named = bool(name)
        self._bind_interaction()
        if self.hint:
            self.SetToolTip(self.hint)
        self.SetInitialSize(self.DoGetBestSize())

    # -- appearance ----------------------------------------------------------
    def _metrics(self) -> Tuple[int, int, int, int, Optional[int]]:
        return _BUTTON_METRICS[self.variant]

    def _label_font(self, size_px: int, weight: int) -> wx.Font:
        return tokens.font_px(self, point_size(size_px), weight, mono=self._mono)

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
        with measuring(self) as dc:
            dc.SetFont(self._label_font(size_px, weight))
            label = self.GetLabel()
            if self.variant == "ribbon":
                lines = wrap_text(
                    dc, label or " ", tokens.scaled(_RIBBON_LABEL_WIDTH), 2
                )
                text_width = max(dc.GetTextExtent(line)[0] for line in lines)
                line_height = dc.GetCharHeight()
                width = max(
                    tokens.scaled(_RIBBON_MIN_WIDTH),
                    text_width + TEXT_SLACK * 2 + tokens.scaled(padding) * 2,
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
                    max(tokens.scaled(_ICON_WIDTH), tokens.scaled(self._min_width)),
                    height,
                )
            lines = [line for line in label.split("\n") if line] or [" "]
            text_width = max(dc.GetTextExtent(line)[0] for line in lines)
            if self.glyph:
                text_width += dc.GetTextExtent(f"{self.glyph} ")[0]
            width = text_width + TEXT_SLACK * 2 + tokens.scaled(padding) * 2
            if self.variant == "icon":
                width = max(width, tokens.scaled(_ICON_WIDTH))
            if len(lines) > 1:
                height = max(
                    height, dc.GetCharHeight() * len(lines) + tokens.scaled(10)
                )
            return wx.Size(max(width, tokens.scaled(self._min_width)), height)

    # -- behaviour -----------------------------------------------------------
    def set_label(self, text: str) -> None:
        """Replace the visible label, its accessible name, and the layout size."""
        self.SetLabel(str(text))

    def SetLabel(self, label: str) -> None:  # noqa: N802 - wx API spelling
        super().SetLabel(str(label))
        if not self._named:
            self.SetName(str(label) or self.hint or "Button")
        self.InvalidateBestSize()
        self.SetMinSize(self.DoGetBestSize())
        self.Refresh()

    def SetName(self, name: str) -> None:  # noqa: N802 - wx API spelling
        """Set the accessible name, and stop deriving it from the label."""
        self._named = bool(name)
        super().SetName(name)

    def activate(self) -> None:
        if not self.IsEnabled():
            return
        invoke(self.on_click)
        self._emit_button()

    # -- painting ------------------------------------------------------------
    def render_to(self, dc: wx.DC, rect: wx.Rect) -> None:
        """Draw the button's shape, label, and focus ring into ``dc``."""
        palette = self.palette()
        with self._painting(dc, rect) as rect:
            padding, radius, size_px, weight, _fixed = self._metrics()
            fill, ink, border = self._state_colours(palette)
            scaled_radius = (
                radius if radius >= tokens.RADIUS_PILL else tokens.scaled(radius)
            )
            if fill is not None or border is not None:
                tokens.draw_round_rect(dc, rect, scaled_radius, fill, border)
            if self.variant == "ribbon":
                self._paint_ribbon(dc, palette, rect, size_px, weight, ink)
            else:
                self._paint_label(dc, rect, padding, size_px, weight, ink)
            if self.HasFocus():
                draw_focus_ring(dc, rect, scaled_radius, self._focus_ink(palette))

    def _focus_ink(self, palette: tokens.StudioPalette) -> wx.Colour:
        """Return the ink the focus ring is drawn in.

        A subclass drawn on something other than a Studio surface -- an overlay
        floating over a rendered world, say -- overrides this, because a primary
        ring on a dark scrim is the one part of the focus indicator that
        disappears exactly when a keyboard user needs it.
        """
        return palette.primary

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
        note_elision(self, label, "\n".join(rendered), hint=self.hint)
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
            dc.SetFont(tokens.font_px(self, point_size(17)))
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
        note_elision(
            self, " ".join(self.GetLabel().split()), " ".join(lines), hint=self.hint
        )
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
        with measuring(self) as dc:
            dc.SetFont(tokens.font_px(self, point_size(14), _MEDIUM))
            lines = self.GetLabel().split("\n") or [" "]
            width = max(dc.GetTextExtent(line or " ")[0] for line in lines)
            height = max(
                tokens.scaled(32), dc.GetCharHeight() * len(lines) + tokens.scaled(8)
            )
            return wx.Size(width + TEXT_SLACK * 2 + tokens.scaled(32), height)

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

    def render_to(self, dc: wx.DC, rect: wx.Rect) -> None:
        """Draw the chip's outline or fill, its label, and its focus ring."""
        palette = self.palette()
        with self._painting(dc, rect) as rect:
            width, height = rect.width, rect.height
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
                        palette.surface,
                        palette.primary,
                        0.12 if self._pressed else 0.06,
                    )
            tokens.draw_round_rect(dc, rect, radius, fill, border)
            dc.SetFont(tokens.font_px(self, point_size(14), _MEDIUM))
            dc.SetTextForeground(ink)
            lines = self.GetLabel().split("\n")
            available = max(0, width - tokens.scaled(24))
            line_height = dc.GetCharHeight()
            y = (height - line_height * len(lines)) // 2
            rendered = [elide(dc, line, available) for line in lines]
            note_elision(self, self.GetLabel(), "\n".join(rendered))
            for text in rendered:
                text_width = dc.GetTextExtent(text)[0]
                dc.DrawText(text, (width - text_width) // 2, y)
                y += line_height
            if self.HasFocus():
                draw_focus_ring(dc, rect, radius, palette.primary)


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
        return tokens.font_px(self, point_size(10), wx.FONTWEIGHT_BOLD)

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        with measuring(self) as dc:
            dc.SetFont(self._font())
            text = self.GetLabel().upper()
            return wx.Size(
                tracked_width(dc, text, tokens.scaled(self.TRACKING)) + TEXT_SLACK * 2,
                dc.GetCharHeight() + tokens.scaled(2),
            )

    def set_label(self, text: str) -> None:
        """Replace the caption and re-measure it."""
        wx.Control.SetLabel(self, str(text))
        self.SetName(str(text) or "Section")
        self.InvalidateBestSize()
        self.SetMinSize(self.DoGetBestSize())
        self.Refresh()

    def render_to(self, dc: wx.DC, rect: wx.Rect) -> None:
        """Draw the tracked uppercase caption, shortened only if it must be."""
        palette = self.palette()
        with self._painting(dc, rect) as rect:
            dc.SetFont(self._font())
            dc.SetTextForeground(palette.on_surface_variant)
            tracking = tokens.scaled(self.TRACKING)
            text = self.GetLabel().upper()
            drawn = text
            # A caption is sized to its own tracked width, so this only bites
            # when a container squeezed it -- and then the whole caption is
            # still one tooltip away rather than gone.
            if tracked_width(dc, text, tracking) > rect.width:
                body = text
                while body and tracked_width(dc, f"{body}…", tracking) > rect.width:
                    body = body[:-1]
                drawn = f"{body}…" if body else ""
            note_elision(self, text, drawn)
            draw_tracked_text(dc, drawn, 0, 0, tracking)


class StudioText(wx.Control, _Themed):
    """One block of laid-out text: a caption, a status line, or a paragraph.

    ``wx.StaticText`` is the control this replaces, and it loses three things
    the shell needs.  It takes its ink from a native foreground colour rather
    than a palette role, so a theme change leaves it behind unless every
    surface remembers to recolour it by hand.  It cannot letter-space, and its
    ``Wrap`` writes the line breaks into the label itself, so ``GetLabel``
    answers with newlines the caller never set -- which matters wherever a
    surface copies that label into an accessible name.  And -- the reason a
    capture of this interface used to come back with holes in it -- it paints
    through the platform rather than through :meth:`_Themed.render_to`, so on a
    desktop nobody is looking at, where there is no surface to read back, it
    photographs as a blank rectangle.

    It is deliberately drop-in for the control it replaces.  ``SetLabel``,
    ``GetLabel``, ``Wrap`` and ``SetForegroundColour`` all behave as a caller
    of ``wx.StaticText`` expects, so migrating a surface is a constructor swap
    rather than a rewrite of everything that talks to it afterwards.  Setting a
    foreground colour explicitly wins over the palette role, because a caller
    that paints its own error ink means it; :meth:`set_role` hands control back.

    A tooltip is given as ``hint`` rather than set from outside.  This control
    owns its own tooltip: :func:`note_elision` rewrites it on every paint so the
    whole of a shortened line stays reachable, and a tooltip set by a caller
    afterwards is therefore erased the first time the control draws -- silently,
    and with nothing in the source to say why.
    """

    # Class-level defaults, because wx may call an overridden setter from
    # inside ``wx.Control.__init__`` -- before ``__init__`` below has bound the
    # instance attribute the override reads.  An AttributeError raised there
    # surfaces as a control that cannot be constructed at all.
    _font_override: Optional[wx.Font] = None
    _ink_override: Optional[wx.Colour] = None
    _named: bool = False
    _best: wx.Size = wx.Size(1, 1)

    def __init__(
        self,
        parent: wx.Window,
        label: str = "",
        *,
        size_px: float = 13,
        weight: int = wx.FONTWEIGHT_NORMAL,
        role: str = "on_surface_variant",
        line_height: float = 1.4,
        wrap_width: int = 0,
        mono: bool = False,
        uppercase: bool = False,
        tracking: float = 0.0,
        max_lines: int = 64,
        ellipsize: bool = False,
        name: str = "",
        hint: str = "",
    ) -> None:
        super().__init__(parent, style=wx.BORDER_NONE)
        wx.Control.SetLabel(self, str(label))
        self.hint = str(hint)
        self._size_px = float(size_px)
        self._weight = weight
        self._role = str(role)
        self._line_factor = float(line_height)
        self._wrap_width = max(0, int(wrap_width))
        self._mono = bool(mono)
        self._uppercase = bool(uppercase)
        self._tracking = float(tracking)
        self._max_lines = max(1, int(max_lines))
        self._ellipsize = bool(ellipsize)
        self._font_override: Optional[wx.Font] = None
        self._ink_override: Optional[wx.Colour] = None
        self._lines: List[str] = []
        self._install(name or str(label).replace("\n", " ") or "Text")
        # After ``_install``, which goes through the ``SetName`` override and
        # would otherwise mark every control as explicitly named -- including
        # the ones whose name is only the label echoed back.
        self._named = bool(name)
        if self.hint:
            self.SetToolTip(self.hint)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self._relayout()

    # Text is read, never operated, so it stays out of the tab order: a caption
    # that takes focus is a stop on the keyboard path to nowhere.
    def AcceptsFocus(self) -> bool:  # noqa: N802 - wx API spelling
        return False

    def AcceptsFocusFromKeyboard(self) -> bool:  # noqa: N802 - wx API spelling
        return False

    # -- content -------------------------------------------------------------
    def SetLabel(self, label: str) -> None:  # noqa: N802 - wx API spelling
        """Replace the text and re-measure it.

        A control given an explicit ``name`` keeps it.  ``wx.StaticText`` never
        renamed itself on a new label, and a status line whose accessible name
        is "Local history filter status" must not silently become whatever its
        last message happened to say -- a screen reader user navigating by name
        would find a different control every time the filter changed.
        """
        text = str(label)
        if text == self.GetLabel():
            return
        wx.Control.SetLabel(self, text)
        if not self._named:
            self.SetName(text.replace("\n", " ") or "Text")
        self._relayout()
        self.Refresh()

    def SetName(self, name: str) -> None:  # noqa: N802 - wx API spelling
        """Set the accessible name, and stop deriving it from the label."""
        self._named = bool(name)
        super().SetName(name)

    def set_text(self, text: str) -> None:
        """Replace the text.  The Studio spelling of :meth:`SetLabel`."""
        self.SetLabel(text)

    def Wrap(self, width: int) -> None:  # noqa: N802 - wx API spelling
        """Wrap to ``width``, as ``wx.StaticText.Wrap`` does.

        A width of ``-1`` or ``0`` means no wrapping, matching the control this
        replaces, so a surface that passes the platform's own sentinel does not
        silently collapse to a single-character column.
        """
        self.set_available_width(0 if int(width) <= 0 else int(width))

    def set_available_width(self, width: int) -> None:
        """Rewrap to a new width, growing or shrinking the control to match."""
        width = max(0, int(width))
        if width == self._wrap_width:
            return
        self._wrap_width = width
        self._relayout()
        self.Refresh()

    def set_role(self, role: str) -> None:
        """Paint the ink from a palette role again, dropping any explicit colour."""
        self._role = str(role)
        self._ink_override = None
        self.Refresh()

    def SetForegroundColour(  # noqa: N802 - wx API spelling
        self, colour: wx.Colour
    ) -> bool:
        """Paint the ink in ``colour``, overriding the palette role.

        The role is how a caption follows the theme; an explicit colour is how
        a status line goes red when its filter is invalid.  Both have to work,
        so the explicit one wins until :meth:`set_role` takes it back.
        """
        resolved = colour_of(colour) if colour is not None else None
        self._ink_override = (
            resolved if resolved is not None and resolved.IsOk() else None
        )
        result = super().SetForegroundColour(colour)
        self.Refresh()
        return result

    def SetFont(self, font: wx.Font) -> bool:  # noqa: N802 - wx API spelling
        """Adopt ``font`` for measurement and drawing, overriding ``size_px``."""
        self._font_override = (
            wx.Font(font) if font is not None and font.IsOk() else None
        )
        result = super().SetFont(font)
        self._relayout()
        self.Refresh()
        return result

    def set_size_px(self, size_px: float, *, weight: Optional[int] = None) -> None:
        """Return to a token-driven font at a new design size."""
        self._size_px = float(size_px)
        if weight is not None:
            self._weight = weight
        self._font_override = None
        self._relayout()
        self.Refresh()

    # -- geometry ------------------------------------------------------------
    def _font(self) -> wx.Font:
        if self._font_override is not None:
            return self._font_override
        return tokens.font_px(
            self, point_size(self._size_px), self._weight, mono=self._mono
        )

    def text_font(self) -> wx.Font:
        """Return the font this actually draws with.

        ``GetFont`` cannot answer this.  Nothing pushes a font into a control
        that resolves its own from ``size_px`` and the live interface scale, so
        ``GetFont`` returns the platform's default GUI font -- a different
        family at a different size from the one on screen.  A caller that has
        to measure the text before setting it (the pane statuses break their
        own lines, because a Cantonese sentence carries no spaces to break on)
        needs the real one, or it wraps to a width the drawing never had.
        """
        return self._font()

    def _display_text(self) -> str:
        text = self.GetLabel()
        return text.upper() if self._uppercase else text

    def _leading(self, dc: wx.DC) -> int:
        return max(1, int(round(dc.GetCharHeight() * self._line_factor)))

    def _relayout(self) -> None:
        with measuring(self) as dc:
            dc.SetFont(self._font())
            text = self._display_text()
            tracking = tokens.scaled(int(self._tracking)) if self._tracking else 0
            if self._wrap_width > 0 and not self._ellipsize:
                self._lines = wrap_text(
                    dc, text, self._wrap_width, max_lines=self._max_lines
                )
            else:
                self._lines = text.split("\n") or [""]
            width = max(
                (tracked_width(dc, line, tracking) for line in self._lines),
                default=0,
            )
            if self._wrap_width > 0:
                width = min(width, self._wrap_width)
            height = self._leading(dc) * max(1, len(self._lines))
        self._best = wx.Size(max(1, width + TEXT_SLACK * 2), max(1, height))
        self.InvalidateBestSize()
        self.SetMinSize(self._best)
        self.SetInitialSize(self._best)

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        return wx.Size(self._best)

    def _apply_theme(self, palette: tokens.StudioPalette) -> None:
        """Re-measure, because the font this draws with may have just changed.

        Interface scale and the chosen font family both feed
        :func:`tokens.font`, so a preferences change moves the text without
        moving the control around it.  ``wx.StaticText`` got this for free:
        every surface pushed a fresh ``SetFont`` into it on a theme change,
        which re-measured as a side effect.  Nothing pushes a font in here, so
        the re-measure has to be asked for -- otherwise the text grows and the
        control it sits in stays the size it was, which is a clipped label.
        """
        if self._font_override is None:
            self._relayout()

    # -- painting ------------------------------------------------------------
    def _ink(self, palette: tokens.StudioPalette) -> wx.Colour:
        if self._ink_override is not None:
            return self._ink_override
        return palette.role(self._role)

    def render_to(self, dc: wx.DC, rect: wx.Rect) -> None:
        """Draw every line of the text, shortened only when it must be."""
        palette = self.palette()
        with self._painting(dc, rect) as rect:
            dc.SetFont(self._font())
            dc.SetTextForeground(self._ink(palette))
            tracking = tokens.scaled(int(self._tracking)) if self._tracking else 0
            leading = self._leading(dc)
            drawn: List[str] = []
            y = 0
            for line in self._lines:
                text = elide(dc, line, rect.width) if self._ellipsize else line
                drawn.append(text)
                if tracking:
                    draw_tracked_text(dc, text, 0, y, tracking)
                else:
                    dc.DrawText(text, 0, y)
                y += leading
            note_elision(self, "\n".join(self._lines), "\n".join(drawn), hint=self.hint)


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

    def render_to(self, dc: wx.DC, rect: wx.Rect) -> None:
        """Draw the card's rounded surface and its optional outline."""
        palette = self.palette()
        with self._painting(dc, rect) as rect:
            tokens.draw_round_rect(
                dc,
                rect,
                tokens.scaled(self.radius),
                palette.role(self.role),
                palette.outline_variant if self.border else None,
            )


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

    def render_to(self, dc: wx.DC, rect: wx.Rect) -> None:
        """Fill the hairline rule."""
        palette = self.palette()
        with self._painting(dc, rect) as rect:
            dc.SetBrush(wx.Brush(palette.outline_variant))
            dc.SetPen(wx.TRANSPARENT_PEN)
            dc.DrawRectangle(0, 0, rect.width, rect.height)


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

    def render_to(self, dc: wx.DC, rect: wx.Rect) -> None:
        """Draw the switch track and its knob at the current value."""
        palette = self.palette()
        with self._painting(dc, rect) as track:
            width, height = track.width, track.height
            if self.value:
                fill, border = palette.primary, palette.primary
                knob_colour = palette.on_primary
            else:
                fill, border = palette.surface_container_high, palette.outline
                knob_colour = palette.outline
            tokens.draw_round_rect(dc, track, height // 2, fill, border)
            knob = tokens.scaled(self.KNOB)
            padding = tokens.scaled(self.PADDING)
            knob_x = width - padding - knob if self.value else padding
            dc.SetBrush(wx.Brush(knob_colour))
            dc.SetPen(wx.TRANSPARENT_PEN)
            dc.DrawEllipse(knob_x, (height - knob) // 2, knob, knob)
            if self.HasFocus():
                draw_focus_ring(dc, track, height // 2, palette.primary)


class StudioCheckBox(wx.Control, _Interactive):
    """The M3 checkbox: an 18px box, its tick, and the label beside it.

    A switch and a checkbox are not interchangeable, which is why this exists
    beside :class:`ToggleSwitch` rather than instead of it.  A switch says a
    setting is on or off and applies immediately; a checkbox says an item is
    included, and reads wrong on a row that opts one search field into regex or
    ticks one entry in a list.  Substituting one for the other is a change to
    what the control means, not a restyle.

    It is drop-in for ``wx.CheckBox``: ``GetValue``, ``SetValue``,
    ``IsChecked``, ``SetLabel`` and ``GetLabel`` keep their spelling, and
    activation posts a real ``wx.EVT_CHECKBOX`` whose ``IsChecked`` answers
    correctly -- so a surface that already binds the event keeps working
    untouched, exactly as :class:`StudioButton` does for ``wx.EVT_BUTTON``.
    """

    BOX = 18
    RADIUS = 2
    BORDER = 2
    GAP = 8

    def __init__(
        self,
        parent: wx.Window,
        label: str = "",
        *,
        value: bool = False,
        size_px: float = 12,
        on_change: Optional[Callable[[bool], None]] = None,
        name: str = "",
    ) -> None:
        super().__init__(parent, style=wx.BORDER_NONE | wx.WANTS_CHARS)
        wx.Control.SetLabel(self, str(label))
        self.value = bool(value)
        self.on_change = on_change
        self._size_px = float(size_px)
        self._install(name or str(label) or "Checkbox")
        self._bind_interaction()
        self.SetInitialSize(self.DoGetBestSize())

    # -- geometry ------------------------------------------------------------
    def _font(self) -> wx.Font:
        return tokens.font_px(self, point_size(self._size_px))

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        box = tokens.scaled(self.BOX)
        label = self.GetLabel()
        if not label:
            return wx.Size(box, box)
        with measuring(self) as dc:
            dc.SetFont(self._font())
            text_width, text_height = dc.GetTextExtent(label)
        return wx.Size(
            box + tokens.scaled(self.GAP) + text_width + TEXT_SLACK * 2,
            max(box, text_height),
        )

    # -- state ---------------------------------------------------------------
    def GetValue(self) -> bool:  # noqa: N802 - wx API spelling
        """Return whether the box is ticked."""
        return self.value

    def IsChecked(self) -> bool:  # noqa: N802 - wx API spelling
        """Return whether the box is ticked.  The ``wx.CheckBox`` spelling."""
        return self.value

    def SetValue(self, value: bool) -> None:  # noqa: N802 - wx API spelling
        """Tick or clear the box without reporting the change.

        ``wx.CheckBox.SetValue`` does not fire ``EVT_CHECKBOX`` either, so a
        surface that sets a box from stored state does not re-enter its own
        handler here any more than it did before.
        """
        self.set_value(value)

    def set_value(self, value: bool, *, notify: bool = False) -> None:
        """Set the box; ``notify`` decides whether the callback and event run."""
        self.value = bool(value)
        self.Refresh()
        if notify:
            invoke(self.on_change, self.value)
            self._emit_checkbox()

    def SetLabel(self, label: str) -> None:  # noqa: N802 - wx API spelling
        """Replace the label and re-measure the control around it."""
        wx.Control.SetLabel(self, str(label))
        self.InvalidateBestSize()
        self.SetMinSize(self.DoGetBestSize())
        self.Refresh()

    def _apply_theme(self, palette: tokens.StudioPalette) -> None:
        """Re-measure: the label's font follows the interface scale.

        The box is a fixed 18 design pixels but the label beside it is not, so
        a scale change that leaves the control at its old width crops its own
        text.  The native checkbox this replaces was re-measured by the
        ``SetFont`` every surface pushed into it on a theme change.
        """
        self.InvalidateBestSize()
        self.SetMinSize(self.DoGetBestSize())

    def activate(self) -> None:
        if not self.IsEnabled():
            return
        self.set_value(not self.value, notify=True)

    def _emit_checkbox(self) -> None:
        """Post the event a ``wx.CheckBox`` would post, carrying its state.

        ``wx.CommandEvent.IsChecked`` reads the integer payload, so a handler
        that asks the event rather than the control -- which is the ordinary
        way to write one -- gets the right answer.
        """
        command = wx.CommandEvent(wx.EVT_CHECKBOX.typeId, self.GetId())
        command.SetEventObject(self)
        command.SetInt(1 if self.value else 0)
        self.GetEventHandler().ProcessEvent(command)

    # -- painting ------------------------------------------------------------
    def render_to(self, dc: wx.DC, rect: wx.Rect) -> None:
        """Draw the box, its tick, the label, and the focus ring."""
        palette = self.palette()
        with self._painting(dc, rect) as rect:
            enabled = self.IsEnabled()
            box = tokens.scaled(self.BOX)
            top = rect.y + max(0, (rect.height - box) // 2)
            square = wx.Rect(rect.x, top, box, box)
            if self.value:
                fill = palette.primary if enabled else palette.outline
                tokens.draw_round_rect(
                    dc, square, tokens.scaled(self.RADIUS), fill, fill
                )
                self._draw_tick(dc, square, palette.on_primary)
            else:
                border = palette.on_surface_variant if enabled else palette.outline
                if self._hovered and enabled:
                    border = palette.primary
                tokens.draw_round_rect(
                    dc,
                    square,
                    tokens.scaled(self.RADIUS),
                    None,
                    border,
                    border_width=max(1, tokens.scaled(self.BORDER)),
                )
            content = wx.Rect(square)
            label = self.GetLabel()
            if label:
                dc.SetFont(self._font())
                ink = palette.on_surface_variant if enabled else palette.outline
                dc.SetTextForeground(ink)
                left = square.GetRight() + 1 + tokens.scaled(self.GAP)
                drawn = elide(dc, label, max(0, rect.GetRight() + 1 - left))
                note_elision(self, label, drawn)
                text_height = dc.GetCharHeight()
                dc.DrawText(
                    drawn, left, rect.y + max(0, (rect.height - text_height) // 2)
                )
                content = wx.Rect(
                    square.x,
                    rect.y,
                    min(rect.width, left - square.x + dc.GetTextExtent(drawn)[0]),
                    rect.height,
                )
            if self.HasFocus():
                # The ring hugs the box and its label rather than the allocated
                # rectangle: a checkbox stretched by an EXPAND flag is as wide
                # as its column, and a ring drawn around that reads as a
                # selected row rather than a focused control.
                draw_focus_ring(
                    dc, content, tokens.scaled(self.RADIUS), palette.primary
                )

    def _draw_tick(self, dc: wx.DC, square: wx.Rect, ink: wx.Colour) -> None:
        """Stroke the checkmark inside a ticked box.

        It is drawn rather than set as a glyph because a font that lacks the
        character renders its own name or a placeholder box, and a checkbox
        whose tick is a hollow rectangle reads as unchecked.
        """
        pen = wx.Pen(ink, max(2, tokens.scaled(2)))
        pen.SetCap(wx.CAP_ROUND)
        pen.SetJoin(wx.JOIN_ROUND)
        dc.SetPen(pen)
        dc.SetBrush(wx.TRANSPARENT_BRUSH)
        left = square.x + square.width * 0.24
        middle_x = square.x + square.width * 0.43
        right = square.x + square.width * 0.76
        middle_y = square.y + square.height * 0.52
        bottom = square.y + square.height * 0.70
        top = square.y + square.height * 0.32
        dc.DrawLines(
            [
                wx.Point(round(left), round(middle_y)),
                wx.Point(round(middle_x), round(bottom)),
                wx.Point(round(right), round(top)),
            ]
        )
        dc.SetPen(wx.NullPen)


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
        self._field_cache: Optional[int] = None
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
        with measuring(self) as dc:
            dc.SetFont(tokens.mono_font_px(self, point_size(10)))
            range_width = dc.GetTextExtent(self._range_text())[0]
            field = self._field_width(dc)
            width = (
                tokens.scaled(self.BUTTON) * 2
                + field
                + tokens.scaled(self.GAP) * 3
                + range_width
                + TEXT_SLACK * 2
            )
            return wx.Size(
                width, max(tokens.scaled(self.BUTTON), tokens.control_height())
            )

    def _field_width(self, dc: Optional[wx.DC] = None) -> int:
        """Return how wide the value box has to be for any value it can hold.

        The design's width was measured against a two-digit value with no
        suffix.  A stepper bounded at 100000, or one carrying "blocks" after
        its number, needs more -- and sizing to the *current* value instead
        would resize the control on every keystroke.  Both bounds are measured,
        so the box is as wide as the widest thing it will ever show and then
        stops moving.

        The result is remembered because the hit regions are worked out from it
        on every paint and every click, and neither of those should be paying
        for a graphics context.  The bounds and the suffix do not change after
        construction; a density or scale change goes through
        :meth:`refresh_theme`, which clears it.
        """
        cached = getattr(self, "_field_cache", None)
        if cached is not None:
            return cached
        if dc is None:
            with measuring(self) as own:
                return self._field_width(own)
        dc.SetFont(tokens.mono_font_px(self, point_size(12)))
        widest = max(
            dc.GetTextExtent(f"{format_number(bound)} {self.suffix}".strip() or " ")[0]
            for bound in (self.minimum, self.maximum)
        )
        width = max(
            tokens.scaled(self.FIELD), widest + TEXT_SLACK * 2 + tokens.scaled(12)
        )
        self._field_cache = width
        return width

    def refresh_theme(self) -> None:
        """Re-read the tokens, forgetting the measurement they were taken at."""
        self._field_cache = None
        super().refresh_theme()

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

    def _regions(
        self, height: Optional[int] = None
    ) -> Tuple[wx.Rect, wx.Rect, wx.Rect]:
        """Return the minus, value, and plus rectangles, top to bottom centred.

        ``height`` lets a render honour the rect it was handed instead of the
        control's own client size, so the same geometry serves a paint and a
        capture that draws this stepper somewhere else on a bitmap.
        """
        if height is None:
            height = self.GetClientSize().height
        button = tokens.scaled(self.BUTTON)
        gap = tokens.scaled(self.GAP)
        field = self._field_width()
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

    def render_to(self, dc: wx.DC, rect: wx.Rect) -> None:
        """Draw the two arrow buttons, the value box, and the range readout."""
        palette = self.palette()
        with self._painting(dc, rect) as area:
            minus, value, plus = self._regions(area.height)
            radius = tokens.scaled(tokens.RADIUS_SM)
            for rect, glyph in ((minus, "−"), (plus, "＋")):
                tokens.draw_round_rect(dc, rect, radius, None, palette.outline)
                dc.SetFont(tokens.font_px(self, point_size(14)))
                dc.SetTextForeground(palette.primary)
                text_width, text_height = dc.GetTextExtent(glyph)
                dc.DrawText(
                    glyph,
                    rect.x + (rect.width - text_width) // 2,
                    rect.y + (rect.height - text_height) // 2,
                )
            editing = bool(self._editing)
            tokens.draw_round_rect(
                dc,
                value,
                radius,
                palette.surface,
                palette.primary if editing else palette.outline,
                border_width=2 if editing else 1,
            )
            dc.SetFont(tokens.mono_font_px(self, point_size(12)))
            dc.SetTextForeground(palette.on_surface)
            text = elide(dc, self._display_text(), value.width - tokens.scaled(12))
            text_width, text_height = dc.GetTextExtent(text)
            dc.DrawText(
                text,
                value.x + (value.width - text_width) // 2,
                value.y + (value.height - text_height) // 2,
            )
            dc.SetFont(tokens.mono_font_px(self, point_size(10)))
            dc.SetTextForeground(palette.on_surface_variant)
            dc.DrawText(
                self._range_text(),
                plus.GetRight() + tokens.scaled(self.GAP),
                value.y + (value.height - dc.GetCharHeight()) // 2,
            )
            if self.HasFocus():
                draw_focus_ring(dc, area, radius, palette.primary, inset=0)


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
        with measuring(self) as dc:
            dc.SetFont(tokens.mono_font_px(self, point_size(12), _MEDIUM))
            width = dc.GetTextExtent(self.GetLabel() or " ")[0]
            return wx.Size(
                width + TEXT_SLACK * 2 + tokens.scaled(24), tokens.scaled(26)
            )

    def set_text(self, text: str) -> None:
        """Replace the readout and re-measure the pill around it."""
        wx.Control.SetLabel(self, str(text))
        self.SetName(f"Value {text}")
        self.InvalidateBestSize()
        self.SetMinSize(self.DoGetBestSize())
        self.Refresh()

    def render_to(self, dc: wx.DC, rect: wx.Rect) -> None:
        """Draw the filled pill and the readout centred inside it."""
        palette = self.palette()
        with self._painting(dc, rect) as rect:
            width, height = rect.width, rect.height
            tokens.draw_round_rect(
                dc,
                rect,
                tokens.scaled(tokens.RADIUS_SM),
                palette.primary,
            )
            dc.SetFont(tokens.mono_font_px(self, point_size(12), _MEDIUM))
            dc.SetTextForeground(palette.on_primary)
            text = elide(dc, self.GetLabel(), width - tokens.scaled(8))
            text_width, text_height = dc.GetTextExtent(text)
            dc.DrawText(text, (width - text_width) // 2, (height - text_height) // 2)


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
        self._caption = StudioText(
            self, self.label, size_px=14, role="on_surface", name=self.label or "Range"
        )
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
        # The caption reads its ink from the ``on_surface`` role and its font
        # from the tokens on every paint, so a theme or scale change lands
        # without this pushing anything into it.
        self._slider.SetBackgroundColour(self.GetBackgroundColour())
        self._slider.SetForegroundColour(palette.primary)

    def _backdrop(self) -> wx.Colour:
        return self.GetBackgroundColour()

    # The row draws nothing of its own: its caption, pill, and slider are all
    # real child windows, so the inherited ``render_to`` -- which fills the
    # backdrop and stops -- is the whole of its appearance.


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

    def render_to(self, dc: wx.DC, rect: wx.Rect) -> None:
        """Draw the colour chip and its hover or focus border."""
        palette = self.palette()
        with self._painting(dc, rect) as rect:
            radius = tokens.scaled(9)
            border = palette.primary if self._hovered else palette.outline
            tokens.draw_round_rect(dc, rect, radius, self.colour, border)
            if self.HasFocus():
                draw_focus_ring(dc, rect, radius, palette.primary)


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
        with measuring(self) as dc:
            dc.SetFont(tokens.font_px(self, point_size(12)))
            height = (
                dc.GetCharHeight() + tokens.scaled(self.BAR_HEIGHT) + tokens.scaled(8)
            )
            # The hint and the readout share one line, so the row is as wide as
            # both of them plus the gap between; the design's 240 is the floor
            # rather than the answer, and it was not scaled at all before.
            hint_width = dc.GetTextExtent(self.hint)[0]
            dc.SetFont(tokens.font_px(self, point_size(12), _MEDIUM))
            label_width = dc.GetTextExtent(self.label)[0]
            width = max(
                tokens.scaled(240),
                hint_width + label_width + tokens.scaled(24) + TEXT_SLACK * 2,
            )
            return wx.Size(width, height)

    def set_progress(self, fraction: float, label: str = "") -> None:
        """Update the bar and, when given, its readout."""
        self.fraction = max(0.0, min(1.0, float(fraction)))
        if label and str(label) != self.label:
            self.label = str(label)
            # The readout is part of what the row is measured against, so a
            # longer one has to re-measure rather than push the hint off.
            self.InvalidateBestSize()
            self.SetMinSize(self.DoGetBestSize())
        self.SetName(f"{self.hint} {self.label}".strip() or "Progress")
        self.Refresh()

    def render_to(self, dc: wx.DC, rect: wx.Rect) -> None:
        """Draw the hint, the readout, and the bar under them."""
        palette = self.palette()
        with self._painting(dc, rect) as rect:
            width = rect.width
            dc.SetFont(tokens.font_px(self, point_size(12)))
            text_height = dc.GetCharHeight()
            dc.SetTextForeground(palette.on_surface_variant)
            label_width = dc.GetTextExtent(self.label)[0]
            hint = elide(dc, self.hint, max(0, width - label_width - tokens.scaled(12)))
            note_elision(self, self.hint, hint)
            dc.DrawText(hint, 0, 0)
            dc.SetFont(tokens.font_px(self, point_size(12), _MEDIUM))
            dc.SetTextForeground(palette.primary)
            dc.DrawText(self.label, max(0, width - label_width), 0)
            bar_height = tokens.scaled(self.BAR_HEIGHT)
            bar_top = text_height + tokens.scaled(8)
            track = wx.Rect(0, bar_top, width, bar_height)
            tokens.draw_round_rect(
                dc, track, bar_height // 2, palette.surface_container_high
            )
            filled = int(width * self.fraction)
            if filled > 0:
                tokens.draw_round_rect(
                    dc,
                    wx.Rect(0, bar_top, filled, bar_height),
                    bar_height // 2,
                    palette.primary,
                )


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
            # A field narrower than its own placeholder shows a clipped prompt
            # and nothing else; the whole prompt stays reachable here.
            self.text.SetToolTip(str(placeholder))
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

    #: The design's field width, and the widest a field will grow to hold its
    #: own placeholder.  Past that the hint is left to the tooltip: a field
    #: scrolls its content, so nothing typed is ever lost, but a placeholder
    #: nobody can read is a prompt that failed at the one job it has.
    WIDTH = 160
    MAX_WIDTH = 360

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        height = (
            tokens.scaled(self._height)
            if self._height is not None
            else tokens.control_height()
        )
        with measuring(self) as dc:
            dc.SetFont(tokens.font_px(self, point_size(self.size_px), mono=self._mono))
            hint = self.text.GetHint() if getattr(self, "text", None) else ""
            content = dc.GetTextExtent(str(hint) or " ")[0]
            padding = tokens.scaled(11) * 2 + self._prefix_width(dc)
        width = min(
            tokens.scaled(self.MAX_WIDTH),
            max(tokens.scaled(self.WIDTH), content + padding + TEXT_SLACK * 2),
        )
        return wx.Size(width, height)

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
        dc.SetFont(tokens.mono_font_px(self, point_size(10)))
        return dc.GetTextExtent(self.prefix)[0] + tokens.scaled(6)

    def _on_size(self, event: wx.SizeEvent) -> None:
        width, height = self.GetClientSize()
        padding = tokens.scaled(11)
        with measuring(self) as dc:
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
            text.SetFont(
                tokens.font_px(self, point_size(self.size_px), mono=self._mono)
            )

    def _backdrop(self) -> wx.Colour:
        return self.GetBackgroundColour()

    def render_to(self, dc: wx.DC, rect: wx.Rect) -> None:
        """Draw the field outline and its axis prefix.

        The text itself belongs to the native ``wx.TextCtrl`` inside this
        panel, which is a window of its own and paints itself.
        """
        palette = self.palette()
        with self._painting(dc, rect) as rect:
            height = rect.height
            tokens.draw_round_rect(
                dc,
                rect,
                tokens.scaled(self.radius),
                palette.role(self.fill_role),
                palette.primary if self._focused else palette.outline,
                border_width=2 if self._focused else 1,
            )
            if self.prefix:
                dc.SetFont(tokens.mono_font_px(self, point_size(10)))
                dc.SetTextForeground(
                    colour_of(self.prefix_colour, palette.on_surface_variant)
                )
                dc.DrawText(
                    self.prefix,
                    tokens.scaled(11),
                    (height - dc.GetCharHeight()) // 2,
                )


class OutlinedField(wx.Panel, _Themed):
    """An M3 outlined text field with a notched floating label.

    ``on_change`` receives the new text on every keystroke.  The label is
    painted over the outline rather than placed above it, which is what makes
    the field read as one control instead of two stacked ones.

    ``on_commit`` receives it once the value is *finished* -- Enter pressed, or
    the field left -- and only when it differs from what was last committed or
    set.  A field whose value drives something real needs both: a per-keystroke
    callback cannot be the one that acts, because a user typing ``-250`` has
    passed through ``-`` and ``-2`` on the way, and acting on those means
    reporting two problems and one wrong answer before they have finished the
    word.  Giving the callback also puts ``wx.TE_PROCESS_ENTER`` on the text
    control, so Enter reaches the field rather than the surrounding dialog.
    """

    LABEL_TOP = 6
    BOX_HEIGHT = 48
    TEXT_PADDING = 15
    #: The design's field width, and the widest one will grow to hold its own
    #: floating label.  The label is painted into the outline, so unlike the
    #: value it cannot scroll: a field narrower than its label loses the name
    #: of the thing being edited.
    WIDTH = 220
    MAX_WIDTH = 420

    def __init__(
        self,
        parent: wx.Window,
        label: str,
        value: str = "",
        *,
        placeholder: str = "",
        mono: bool = True,
        on_change: Optional[Callable[[str], None]] = None,
        on_commit: Optional[Callable[[str], None]] = None,
    ) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self.label = str(label)
        self.on_change = on_change
        self.on_commit = on_commit
        self._mono = bool(mono)
        self._focused = False
        #: The last value this field has handed to ``on_commit``, or been given
        #: by :meth:`set_value`.  A commit that matches it is not raised again,
        #: so tabbing through a row of untouched fields runs nothing.
        self._committed = str(value)
        self._install(self.label or "Field", listen=False)
        self.text = wx.TextCtrl(
            self,
            value=str(value),
            style=wx.BORDER_NONE
            | (wx.TE_PROCESS_ENTER if on_commit is not None else 0),
            name=self.label or "Field",
        )
        self.text.SetName(self.label or "Field")
        if placeholder:
            self.text.SetHint(str(placeholder))
        self._apply_theme(self.palette())
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.Bind(wx.EVT_SIZE, self._on_size)
        self.text.Bind(wx.EVT_TEXT, self._on_text)
        if on_commit is not None:
            self.text.Bind(wx.EVT_TEXT_ENTER, self._on_enter)
        self.text.Bind(wx.EVT_SET_FOCUS, self._on_focus_change)
        self.text.Bind(wx.EVT_KILL_FOCUS, self._on_focus_change)
        self.SetInitialSize(self.DoGetBestSize())

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        height = tokens.scaled(self.LABEL_TOP) + tokens.scaled(self.BOX_HEIGHT)
        with measuring(self) as dc:
            dc.SetFont(tokens.font_px(self, point_size(11)))
            label_width = dc.GetTextExtent(self.label or " ")[0]
        width = min(
            tokens.scaled(self.MAX_WIDTH),
            max(
                tokens.scaled(self.WIDTH),
                label_width + tokens.scaled(30) + TEXT_SLACK * 2,
            ),
        )
        return wx.Size(width, height)

    def value(self) -> str:
        """Return the current text."""
        return self.text.GetValue()

    def set_value(self, text: str, *, notify: bool = False) -> None:
        """Replace the text; silent by default.

        The new text becomes what a later commit is compared against, so a
        field refilled from somewhere else does not then raise ``on_commit``
        the next time it is merely tabbed through.
        """
        self._committed = str(text)
        if notify:
            self.text.SetValue(str(text))
        else:
            self.text.ChangeValue(str(text))
        self.Refresh()

    def commit(self) -> None:
        """Hand the current text to ``on_commit``, if it has changed."""
        if self.on_commit is None:
            return
        current = self.text.GetValue()
        if current == self._committed:
            return
        # Recorded before the callback runs, not after: the handler may write
        # back into this field, and a commit that recorded afterwards would
        # overwrite what the handler had just put there with what the user
        # typed, so the next commit would compare against the wrong text.
        self._committed = current
        invoke(self.on_commit, current)

    def SetFocus(self) -> None:  # noqa: N802 - wx API spelling
        self.text.SetFocus()

    def _box_rect(self, width: Optional[int] = None) -> wx.Rect:
        """Return the outlined box below the floating label.

        ``width`` lets a render use the rect it was handed rather than the
        control's own client size.
        """
        if width is None:
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

    def _on_enter(self, event: wx.CommandEvent) -> None:
        self.commit()
        event.Skip()

    def _on_focus_change(self, event: wx.FocusEvent) -> None:
        self._focused = event.GetEventType() == wx.EVT_SET_FOCUS.typeId
        if not self._focused:
            # Leaving commits too, so a value typed and then tabbed away from is
            # not silently discarded -- which, in a field that drives something
            # real, looks exactly like the field being ignored.
            self.commit()
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
            text.SetFont(tokens.font_px(self, point_size(14), mono=self._mono))

    def _backdrop(self) -> wx.Colour:
        return self.GetBackgroundColour()

    def render_to(self, dc: wx.DC, rect: wx.Rect) -> None:
        """Draw the outlined box and the label notched into its top edge."""
        palette = self.palette()
        with self._painting(dc, rect) as rect:
            box = self._box_rect(rect.width)
            border = palette.primary if self._focused else palette.outline
            tokens.draw_round_rect(
                dc,
                box,
                tokens.scaled(4),
                None,
                border,
                border_width=2 if self._focused else 1,
            )
            if self.label:
                dc.SetFont(tokens.font_px(self, point_size(11)))
                label = elide(dc, self.label, max(0, box.width - tokens.scaled(30)))
                note_elision(self, self.label, label)
                label_width = dc.GetTextExtent(label)[0]
                notch = wx.Rect(
                    tokens.scaled(11),
                    0,
                    label_width + tokens.scaled(8),
                    dc.GetCharHeight(),
                )
                dc.SetBrush(wx.Brush(self.GetBackgroundColour()))
                dc.SetPen(wx.TRANSPARENT_PEN)
                dc.DrawRectangle(notch)
                dc.SetTextForeground(
                    palette.primary if self._focused else palette.on_surface_variant
                )
                dc.DrawText(label, notch.x + tokens.scaled(4), 0)


class PathField(wx.Panel, _Themed):
    """A path entry with native Browse buttons and one shared validator.

    A typed path and a browsed path run through exactly the same check, so a
    value chosen from the picker is never trusted more than one somebody typed,
    and the reason a path is refused is stated in words rather than as a red
    outline.

    ``"save_file"`` is the odd mode out: everywhere else a path is only useful
    once something already exists there, but a save target is useful precisely
    because nothing does yet, so it is the one mode that does not fail
    validation on a path that is merely unwritten so far.
    """

    MODES = ("folder", "file", "both", "save_file")

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
        self._save = mode == "save_file"
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
        if mode in ("file", "both", "save_file"):
            file_label = "Save to…" if self._save else "Browse files…"
            file_hint = (
                f"Choose where to save {self.label}"
                if self._save
                else f"Choose a file for {self.label}"
            )
            self.file_button = StudioButton(
                self,
                file_label,
                variant="outlined",
                on_click=self._browse_file,
                name=f"{file_label} for {self.label}",
                hint=file_hint,
            )
            row.Add(
                self.file_button,
                0,
                wx.ALIGN_BOTTOM | wx.LEFT,
                tokens.scaled(tokens.SPACE_SM),
            )
        self.feedback = StudioText(
            self, "", size_px=11, name=f"{self.label} validation"
        )
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
        elif self.mode == "save_file":
            self._valid = True
            message = (
                "This will overwrite the existing file."
                if os.path.isfile(text)
                else "Ready to save here."
            )
            colour = palette.on_surface_variant
        else:
            self._valid = True
            kind = "Folder" if os.path.isdir(text) else "File"
            message = f"{kind} found."
            colour = palette.on_surface_variant
        self.feedback.SetLabel(message)
        # Only the error red is pushed in.  Handing the ordinary colour back as
        # an explicit override would pin it to the palette that was live when
        # the path was last validated, so the line would keep the old theme's
        # grey after a theme change; ``set_role`` returns it to the palette.
        if self._valid:
            self.feedback.set_role("on_surface_variant")
        else:
            self.feedback.SetForegroundColour(colour)
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
        if self._save:
            style = wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT
        else:
            style = wx.FD_OPEN | wx.FD_FILE_MUST_EXIST
        with wx.FileDialog(
            self,
            (
                f"Choose where to save {self.label}"
                if self._save
                else f"Choose a file for {self.label}"
            ),
            defaultFile=os.path.basename(self.value()) if self._save else "",
            style=style,
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
        # The feedback line resolves its own font from the live interface
        # scale; re-validating is what re-picks the ink, which is either the
        # palette's error red or its ordinary variant.
        if getattr(self, "feedback", None) is not None:
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
        self.regex_box: Optional[StudioCheckBox] = None
        if show_regex:
            self.regex_box = StudioCheckBox(
                self,
                "Regex",
                value=bool(state.regex),
                size_px=11,
            )
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
        self.feedback = StudioText(
            self,
            state.feedback(),
            size_px=10 if compact else 11,
            name=f"{state.label} search feedback",
        )
        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(row, 0, wx.EXPAND)
        # A gap the feedback line's own font is measured against, rather than a
        # fixed few pixels: at the smaller compact size the descenders of the
        # field's rounded box and the ascenders of the feedback text sat close
        # enough to read as painted on top of one another, worst in bilingual
        # mode where the line is longest and every other row is two lines deep.
        root.Add(
            self.feedback,
            0,
            wx.EXPAND | wx.TOP,
            tokens.scaled(tokens.SPACE_XS + 2),
        )
        self.SetSizer(root)
        self.Bind(wx.EVT_SIZE, self._on_resize)
        self._apply_theme(self.palette())

    def _on_resize(self, event: wx.SizeEvent) -> None:
        """Rewrap the feedback line to the bar's own width, not the field's.

        Without this the feedback ``StudioText`` never wrapped at all, so its
        best-size height was always one line even when the drawn text -- an
        error sentence, or the bilingual pairing of one -- was long enough to
        need two.  The sizer kept reserving that single-line height, and the
        control's own painting then drew a second line straight through the
        space the sizer had given the field above it: the helper text reading
        as printed over the field's own lower edge instead of below it.
        """
        width = self.GetClientSize().width
        if width > 0:
            self.feedback.set_available_width(width)
            self.Layout()
        event.Skip()

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
        width = self.GetClientSize().width
        if width > 0:
            self.feedback.set_available_width(width)
        self.feedback.SetLabel(message)
        invalid = self.state.regex and not self.state.is_valid()
        # Only the error red is pushed in; the ordinary colour goes back to the
        # palette role, so a theme change does not leave the line inked in the
        # previous theme's grey.
        if invalid:
            self.feedback.SetForegroundColour(self.palette().error)
        else:
            self.feedback.set_role("on_surface_variant")
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
        """Open the regex builder for this field and apply its result.

        The builder is anchored beside the field it belongs to, because that is
        the field the user is already typing in.  A modal dialog is the fallback
        for a display too small to hold the popover, and nothing else.
        """
        if self._builder_fits():
            popup = _RegexBuilderPopup(
                self,
                self.builder_button or self.field,
                self.state,
                on_apply=self._adopt_builder_result,
            )
            popup.popup()
            return
        self._open_builder_dialog()

    def _builder_fits(self) -> bool:
        """Return whether this display can hold the anchored builder."""
        try:
            index = wx.Display.GetFromWindow(self)
            area = wx.Display(index if index != wx.NOT_FOUND else 0).GetClientArea()
        except Exception:  # pragma: no cover - platform boundary
            return False
        return area.width >= tokens.scaled(520) and area.height >= tokens.scaled(420)

    def _adopt_builder_result(self, state: SearchState) -> None:
        """Reflect a pattern built in the popover back into this field."""
        self.field.set_value(state.query)
        if self.regex_box is not None:
            self.regex_box.SetValue(state.regex)
        self.refresh_feedback()
        invoke(self.on_change, self.state)

    def _open_builder_dialog(self) -> None:
        """Fall back to the modal builder when the popover cannot fit."""
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
            feedback.set_size_px(10 if self.compact else 11)
            self.refresh_feedback()
        # The regex box is owner-drawn and reads its own ink, border, and font
        # from the tokens on every paint, so there is nothing to push into it
        # here.  ``refresh_theme`` on this panel repaints it along with the
        # rest of the row.


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
        """Size the popup to its content, clamped to the display work area.

        The height comes from the content sizer's own minimum rather than from
        ``Fit()``.  A ``wx.ScrolledWindow`` reports its *viewport* as its best
        size, so fitting the popup around one collapses it to a couple of rows
        and silently hides everything below the cut -- which is the exact
        failure the scrolling was added to prevent.

        The arithmetic follows the root sizer rather than approximating it.
        The header is added with the inset above it and the content with the
        inset on all four sides, so three insets of vertical space are spoken
        for, not two-and-a-bit: the old sum was four pixels short at the
        shipped tokens, and four pixels is exactly enough to slice the bottom
        row of a menu in half lengthways while leaving every row above it
        looking perfect.  The header is measured into the width too, because a
        search field wider than the list it filters was being cut off at
        "Reg".
        """
        area = self.work_area()
        self.header.Fit()
        header_size = self.header.GetBestSize()
        header_height = header_size.height
        content_min = self.content_sizer.GetMinSize()
        self.content.SetVirtualSize(content_min)
        inset = tokens.scaled(self.MARGIN) + tokens.scaled(self.PADDING)

        width = max(content_min.width, header_size.width) + inset * 2
        if self.requested_width:
            width = tokens.scaled(self.requested_width)
        width = max(width, self.anchor.GetSize().width)
        width = min(width, max(120, area.width - tokens.scaled(16)))

        height = header_height + content_min.height + inset * 3
        limit = area.height - tokens.scaled(24)
        if self.requested_max_height:
            limit = min(limit, tokens.scaled(self.requested_max_height))
        # Clamping is what makes the content scroll instead of being clipped:
        # the virtual size above stays at the full content height either way.
        height = max(tokens.scaled(48), min(height, limit))
        self.SetSize(wx.Size(width, height))
        self.Layout()
        self.content.FitInside()

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

    def render_to(self, dc: wx.DC, rect: wx.Rect) -> None:
        """Draw the popup's elevated card into ``dc`` at ``rect``.

        The popup is a ``wx.PopupTransientWindow`` rather than a ``_Themed``
        widget, so it carries its own copy of the contract instead of
        inheriting one -- same public method, same meaning, reachable by a
        capture without a paint event.
        """
        palette = tokens.palette()
        with translated(dc, rect):
            width, height = rect.width, rect.height
            dc.SetBrush(wx.Brush(palette.surface))
            dc.SetPen(wx.TRANSPARENT_PEN)
            dc.DrawRectangle(0, 0, width, height)
            margin = tokens.scaled(self.MARGIN)
            card = wx.Rect(margin, margin, width - margin * 2, height - margin * 2)
            radius = tokens.scaled(tokens.RADIUS_MD)
            tokens.draw_elevation(dc, card, radius, 2, palette.dark)
            tokens.draw_round_rect(
                dc, card, radius, palette.surface, palette.outline_variant
            )

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        dc, gcdc = paint_context(self, palette.surface)
        width, height = self.GetClientSize()
        self.render_to(gcdc, wx.Rect(0, 0, width, height))
        del gcdc


class _RegexBuilderPopup(AnchoredPopup):
    """The regex builder, anchored beside the field it belongs to.

    The builder belongs to the search bar the user is already typing in, so it
    opens attached to that field rather than as a window somewhere else on the
    screen.  A modal dialog remains the fallback for a display too small to hold
    the popover, which is the only case the design allows it for.
    """

    WIDTH = 380
    PREVIEW_LIMIT = 6

    def __init__(
        self,
        parent: wx.Window,
        anchor: wx.Window,
        state: SearchState,
        *,
        on_apply=None,
    ) -> None:
        super().__init__(parent, anchor, width=self.WIDTH, max_height=460)
        self.state = state
        self.on_apply = on_apply
        self.SetName("Regex builder")
        palette = tokens.palette()

        header_sizer = wx.BoxSizer(wx.VERTICAL)
        header_sizer.Add(SectionLabel(self.header, "Regex builder"), 0, wx.EXPAND)
        self.header.SetSizer(header_sizer)

        self.pattern_field = OutlinedField(
            self.content,
            "Pattern",
            state.query,
            placeholder="height|debug",
            mono=True,
            on_change=self._on_edit,
        )
        self.flags_field = OutlinedField(
            self.content,
            "Flags",
            state.flags,
            placeholder="iu",
            mono=True,
            on_change=self._on_edit,
        )
        self.sample_field = OutlinedField(
            self.content,
            "Sample text",
            state.sample,
            mono=False,
            on_change=self._on_edit,
        )
        # 12 design pixels is the 9pt these two were built at: ``point_size``
        # is the one conversion, so keeping the design number here keeps the
        # rendered size identical to the native controls they replace.
        self.feedback = StudioText(
            self.content, "", size_px=12, name="Regex builder feedback"
        )
        self.preview = StudioText(
            self.content,
            "",
            size_px=12,
            mono=True,
            role="on_surface",
            name="Regex builder match preview",
        )

        actions = wx.BoxSizer(wx.HORIZONTAL)
        actions.AddStretchSpacer()
        actions.Add(
            StudioButton(
                self.content,
                "Cancel",
                variant="text",
                on_click=self.Dismiss,
                name="Cancel the regex builder",
            ),
            0,
            wx.RIGHT,
            tokens.SPACE_SM,
        )
        actions.Add(
            StudioButton(
                self.content,
                "Apply pattern",
                variant="filled",
                on_click=self._apply,
                name="Apply the built pattern",
            ),
            0,
        )

        gap = tokens.scaled(tokens.SPACE_SM)
        for control in (
            self.pattern_field,
            self.flags_field,
            self.sample_field,
            self.feedback,
            self.preview,
        ):
            self.content_sizer.Add(control, 0, wx.EXPAND | wx.BOTTOM, gap)
        self.content_sizer.Add(actions, 0, wx.EXPAND | wx.TOP, gap)
        self._refresh_preview()

    def _current(self) -> SearchState:
        """Return a throwaway state carrying whatever is typed right now."""
        return SearchState(
            query=self.pattern_field.value()[:MAX_PATTERN_LENGTH],
            regex=True,
            flags=self.flags_field.value()[:8],
            sample=self.sample_field.value(),
        )

    def _on_edit(self, _text: str) -> None:
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        """Show whether the pattern compiles and what it matches right now."""
        probe = self._current()
        self.feedback.SetLabel(probe.feedback())
        # Only the error red is pushed in; the ordinary colour goes back to the
        # palette role rather than being pinned to whichever theme was live.
        if probe.is_valid():
            self.feedback.set_role("on_surface_variant")
        else:
            self.feedback.SetForegroundColour(tokens.palette().error)
        if not probe.is_active():
            self.preview.SetLabel("Type a pattern to see what it matches.")
        elif not probe.is_valid():
            self.preview.SetLabel("No matches while the pattern is invalid.")
        else:
            spans = probe.highlights(probe.sample)
            if not spans:
                self.preview.SetLabel("No match in the sample text.")
            else:
                shown = spans[: self.PREVIEW_LIMIT]
                pieces = [probe.sample[start:end] for start, end in shown]
                more = len(spans) - len(shown)
                text = " \u00b7 ".join(pieces)
                if more > 0:
                    text = f"{text} \u00b7 +{more} more"
                self.preview.SetLabel(f"{len(spans)} match: {text}")
        self.preview.Wrap(tokens.scaled(self.WIDTH) - tokens.scaled(40))
        self.layout()

    def _apply(self) -> None:
        """Write the built pattern back into the field state and close."""
        probe = self._current()
        self.state.query = probe.query
        self.state.flags = probe.flags or self.state.flags
        self.state.sample = probe.sample or self.state.sample
        self.state.regex = True
        invoke(self.on_apply, self.state)
        self.Dismiss()


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
        with measuring(self) as dc:
            dc.SetFont(tokens.font_px(self, point_size(12)))
            width = (
                dc.GetTextExtent(self.GetLabel() or " ")[0]
                + TEXT_SLACK * 2
                + tokens.scaled(26)
            )
            if self.swatch:
                width += tokens.scaled(self.SWATCH + 8)
            return wx.Size(width, tokens.scaled(self.HEIGHT))

    def set_selected(self, selected: bool) -> None:
        """Mark this row as the chosen option."""
        self.selected = bool(selected)
        self.Refresh()

    def activate(self) -> None:
        invoke(self.on_click, self.GetLabel())

    def _backdrop(self) -> wx.Colour:
        # The row lives inside a popup, whose surface is the design's rather
        # than whatever the parent window happens to report.
        return self.palette().surface

    def render_to(self, dc: wx.DC, rect: wx.Rect) -> None:
        """Draw the row's selection or hover fill, its swatch, and its label."""
        palette = self.palette()
        with self._painting(dc, rect) as rect:
            width, height = rect.width, rect.height
            radius = tokens.scaled(7)
            if self.selected:
                tokens.draw_round_rect(dc, rect, radius, palette.primary_container)
                ink = palette.on_primary_container
            elif self._hovered or self._pressed:
                tokens.draw_round_rect(dc, rect, radius, palette.surface_container_high)
                ink = palette.on_surface
            else:
                ink = palette.on_surface
            left = tokens.scaled(9)
            if self.swatch:
                side = tokens.scaled(self.SWATCH)
                tokens.draw_round_rect(
                    dc,
                    wx.Rect(left, (height - side) // 2, side, side),
                    tokens.scaled(4),
                    colour_of(self.swatch),
                    palette.outline_variant,
                )
                left += side + tokens.scaled(8)
            dc.SetFont(tokens.font_px(self, point_size(12)))
            dc.SetTextForeground(ink)
            text = elide(dc, self.GetLabel(), max(0, width - left - tokens.scaled(9)))
            note_elision(self, self.GetLabel(), text)
            dc.DrawText(text, left, (height - dc.GetCharHeight()) // 2)
            if self.HasFocus():
                draw_focus_ring(dc, rect, radius, palette.primary)


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
        hint: str = "",
    ) -> None:
        super().__init__(parent, style=wx.WANTS_CHARS)
        self.hint = str(hint)
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
        # The combo owns its tooltip: ``note_elision`` rewrites it on every
        # paint so an elided value stays readable, which silently erases one set
        # from outside.  ``hint`` is how a caller gets one that survives.
        self.SetToolTip(self.hint or self.label)
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

    #: The design's combo width, and the widest one grows to.  The value is
    #: elided rather than scrolled, so a combo narrower than the option it is
    #: showing hides the current choice; both the label and the longest option
    #: are measured.
    WIDTH = 220
    MAX_WIDTH = 420

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        height = tokens.scaled(self.LABEL_TOP) + tokens.scaled(self.BOX_HEIGHT)
        with measuring(self) as dc:
            dc.SetFont(tokens.font_px(self, point_size(14)))
            values = [*self.options, self.value] or [" "]
            value_width = max(dc.GetTextExtent(text or " ")[0] for text in values)
            dc.SetFont(tokens.font_px(self, point_size(11)))
            label_width = dc.GetTextExtent(self.label or " ")[0]
        width = min(
            tokens.scaled(self.MAX_WIDTH),
            max(
                tokens.scaled(self.WIDTH),
                value_width + tokens.scaled(46) + TEXT_SLACK * 2,
                label_width + tokens.scaled(30) + TEXT_SLACK * 2,
            ),
        )
        return wx.Size(width, height)

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
        # A new option list is new content, and the combo is sized to the
        # widest thing it can show.
        self.InvalidateBestSize()
        self.SetMinSize(self.DoGetBestSize())
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
            message = self.state.describe_matches(0, "option")
            empty = StudioText(
                popup.content,
                message,
                size_px=12,
                name=f"{self.state.label} options: {message}",
            )
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
    def render_to(self, dc: wx.DC, rect: wx.Rect) -> None:
        """Draw the closed combo: its outline, value, caret, and notched label."""
        palette = self.palette()
        backdrop = self._backdrop()
        with self._painting(dc, rect) as rect:
            width, height = rect.width, rect.height
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
                dc,
                box,
                tokens.scaled(4),
                None,
                border,
                border_width=2 if focused else 1,
            )
            dc.SetFont(tokens.font_px(self, point_size(14)))
            dc.SetTextForeground(palette.on_surface)
            available = max(0, box.width - tokens.scaled(46))
            value = elide(dc, self.value, available)
            note_elision(self, self.value, value, hint=self.hint or self.label)
            dc.DrawText(
                value,
                tokens.scaled(15),
                box.y + (box.height - dc.GetCharHeight()) // 2,
            )
            dc.SetFont(tokens.font_px(self, point_size(10)))
            dc.SetTextForeground(palette.on_surface_variant)
            caret_width = dc.GetTextExtent("▾")[0]
            dc.DrawText(
                "▾",
                box.width - tokens.scaled(15) - caret_width,
                box.y + (box.height - dc.GetCharHeight()) // 2,
            )
            if self.label:
                dc.SetFont(tokens.font_px(self, point_size(11)))
                label = elide(dc, self.label, max(0, box.width - tokens.scaled(30)))
                label_width = dc.GetTextExtent(label)[0]
                notch = wx.Rect(
                    tokens.scaled(11),
                    0,
                    label_width + tokens.scaled(8),
                    dc.GetCharHeight(),
                )
                dc.SetBrush(wx.Brush(backdrop))
                dc.SetPen(wx.TRANSPARENT_PEN)
                dc.DrawRectangle(notch)
                dc.SetTextForeground(
                    palette.primary if focused else palette.on_surface_variant
                )
                dc.DrawText(label, notch.x + tokens.scaled(4), 0)
            if self.HasFocus():
                draw_focus_ring(dc, box, tokens.scaled(4), palette.primary)


# ----------------------------------------------------------------------------
# floating overlays over a rendered view
# ----------------------------------------------------------------------------

#: The ink everything on an overlay surface is drawn in.  An overlay is a scrim
#: -- dark in both themes, because what is behind it is a rendered world rather
#: than a Studio surface -- so its ink is fixed rather than a palette role that
#: would go dark on a dark backdrop and vanish.  This is the same white the
#: heads-up chips use, which is what makes a toolbar and the chips under it read
#: as one family instead of two.
OVERLAY_INK = wx.Colour(255, 255, 255)

#: The state-layer opacities M3 specifies, as alpha out of 255: hover 8%,
#: pressed 12%, plus the outline and disabled ink strengths an on-scrim control
#: needs to stay legible.
_OVERLAY_HOVER_ALPHA = 20
_OVERLAY_PRESSED_ALPHA = 36
_OVERLAY_OUTLINE_ALPHA = 110
_OVERLAY_DISABLED = 0.55


def overlay_fill(backdrop: wx.Colour, palette: tokens.StudioPalette) -> wx.Colour:
    """Return the opaque colour the scrim resolves to over ``backdrop``.

    The scrim role is translucent, and a child window cannot see through its
    parent: on Windows a sibling of an OpenGL canvas is its own surface, so
    "translucent" would mean "translucent over whatever the parent last
    painted" rather than over the world.  Compositing the scrim here gives one
    opaque colour that the bar paints and that every control inside it clears
    to, so the bar reads as a single surface instead of a patchwork of
    rectangles each guessing at its own backdrop.
    """
    scrim = palette.scrim
    opaque = wx.Colour(scrim.Red(), scrim.Green(), scrim.Blue(), 255)
    return tokens.blend(backdrop, opaque, scrim.Alpha() / 255.0)


class OverlayBar(wx.Panel, _Themed):
    """A floating M3 surface for controls drawn over a rendered view.

    It is the toolbar counterpart of the heads-up chips: same scrim, same
    corner radius family, same elevation, so a row of controls at the top of a
    3D view belongs with the readouts under it rather than looking like the
    platform's own chrome someone forgot to style.

    The surface is drawn inset by :attr:`MARGIN` so its shadow has somewhere to
    fall -- :func:`tokens.draw_elevation` paints *outside* the rectangle it is
    given, and a bar filling its whole client area clips its own elevation away.
    """

    #: Room left around the painted surface for the shadow, in design pixels.
    MARGIN = 3
    #: Shape and lift, both taken from the heads-up chips rather than chosen
    #: afresh, because the whole point of this surface is to sit beside them.
    RADIUS = tokens.RADIUS_SM
    ELEVATION = 1
    #: A scrim floats over *rendered content*, not over a Studio surface, so its
    #: shadow is the dark one in either theme -- the same call the chips make.
    SHADOW_IS_DARK = True

    def __init__(
        self,
        parent: wx.Window,
        *,
        name: str = "Overlay",
        radius: Optional[int] = None,
        elevation: Optional[int] = None,
    ) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self.radius = int(self.RADIUS if radius is None else radius)
        self.elevation = int(self.ELEVATION if elevation is None else elevation)
        self._install(name or "Overlay")
        self._apply_theme(self.palette())
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)

    def surface_colour(self) -> wx.Colour:
        """Return the opaque colour this bar paints its surface in.

        The bar's own shadow is part of the answer.  ``draw_elevation`` covers
        the interior of the rectangle it lifts as well as the ground around it,
        and the heads-up chips paint their scrim translucently on top of that --
        so a bar that composited the scrim over the bare backdrop alone would
        come out visibly paler than a chip sitting two pixels beneath it, at
        the same elevation, in the same theme.
        """
        palette = self.palette()
        backdrop = self._parent_colour()
        if backdrop is None or not backdrop.IsOk():
            backdrop = palette.surface
        lifted = tokens.elevation_tint(backdrop, self.elevation, self.SHADOW_IS_DARK)
        return overlay_fill(lifted, palette)

    def _parent_colour(self) -> Optional[wx.Colour]:
        """Return what the host paints behind this bar.

        A host that draws a gradient answers per rectangle through
        ``background_colour_at``, which is how the heads-up readouts already
        sample the sky they float over.  Asking the same question the same way
        is what keeps a toolbar and the chips beneath it the same shade instead
        of two guesses at one backdrop.
        """
        parent = self.GetParent()
        if parent is None:
            return None
        sampler = getattr(parent, "background_colour_at", None)
        if callable(sampler):
            try:
                return sampler(self.GetRect())
            except Exception:  # noqa: BLE001 - the host is mid-teardown
                log.debug("Could not sample the backdrop behind %s", self.GetName())
        return parent.GetBackgroundColour()

    def _backdrop(self) -> wx.Colour:
        # The few pixels of shadow margin around the surface, which show what
        # is behind the bar rather than the bar itself.
        colour = self._parent_colour()
        return (
            colour if colour is not None and colour.IsOk() else self.palette().surface
        )

    def _apply_theme(self, palette: tokens.StudioPalette) -> None:
        # Every Studio child clears itself to its parent's background colour, so
        # this has to be the colour the bar actually paints -- otherwise each
        # control paints a rectangle of the wrong shade inside the surface.
        self.SetBackgroundColour(self.surface_colour())

    def Reparent(self, parent: wx.Window) -> bool:  # noqa: N802 - wx API spelling
        """Move the bar, and re-resolve the surface against its new backdrop.

        An overlay is routinely reparented: the editor builds its panels beside
        its own canvas and the shell then borrows them onto the viewport.  The
        scrim is composited against whatever is behind it, so a bar that kept
        the old parent's colour would paint the shade of a window it no longer
        sits on.
        """
        moved = super().Reparent(parent)
        self._apply_theme(self.palette())
        self.Refresh()
        return moved

    def surface_rect(self, rect: wx.Rect) -> wx.Rect:
        """Return the painted surface inside ``rect``, shadow margin removed."""
        margin = tokens.scaled(self.MARGIN)
        return wx.Rect(
            rect.x + margin,
            rect.y + margin,
            max(0, rect.width - margin * 2),
            max(0, rect.height - margin * 2),
        )

    def render_to(self, dc: wx.DC, rect: wx.Rect) -> None:
        """Draw the bar's shadow and its rounded scrim surface.

        The surface goes down opaque rather than as a translucent scrim, and
        :meth:`surface_colour` has already folded the shadow into that colour.
        Painting it opaque is what lets a child window clear itself to exactly
        the same value: a child is a separate surface and cannot see through to
        what its parent composited.
        """
        with self._painting(dc, rect) as rect:
            surface = self.surface_rect(rect)
            if surface.width <= 0 or surface.height <= 0:
                return
            radius = tokens.scaled(self.radius)
            tokens.draw_elevation(
                dc, surface, radius, self.elevation, self.SHADOW_IS_DARK
            )
            tokens.draw_round_rect(dc, surface, radius, self.surface_colour())


def overlay_backdrop(window: wx.Window) -> Optional[wx.Colour]:
    """Return the surface colour of the :class:`OverlayBar` above ``window``.

    Read live rather than taken from the parent's stored background colour,
    because an overlay is reparented in normal use and a control that cached
    its backdrop would clear itself to the shade of a window it left.
    """
    parent = window.GetParent()
    while parent is not None:
        if isinstance(parent, OverlayBar):
            return parent.surface_colour()
        parent = parent.GetParent()
    return None


class _OnOverlay:
    """Backdrop resolution shared by every control drawn on an overlay bar."""

    def _backdrop(self) -> wx.Colour:
        colour = overlay_backdrop(self)
        return colour if colour is not None else super()._backdrop()


class OverlayButton(_OnOverlay, StudioButton):
    """A :class:`StudioButton` drawn on an :class:`OverlayBar`.

    Everything a Studio button already does is kept -- ``on_click`` and the
    emitted ``wx.EVT_BUTTON``, Enter and Space activation, the focus ring, the
    tooltip, the accessible name, the measured best size, and one ``render_to``
    that both the screen and a capture go through.  Only the palette changes:
    resting is transparent so the scrim shows, ink is the overlay white, and
    hover and press are white state layers rather than surface containers that
    would be invisible on a dark bar.
    """

    def __init__(
        self,
        parent: wx.Window,
        label: str = "",
        *,
        variant: str = "text",
        **kwargs: Any,
    ) -> None:
        super().__init__(parent, label, variant=variant, **kwargs)

    def _variant_colours(
        self, palette: tokens.StudioPalette
    ) -> Tuple[Optional[wx.Colour], wx.Colour, Optional[wx.Colour]]:
        if not self.IsEnabled():
            return (
                None,
                tokens.blend(OVERLAY_INK, self._backdrop(), _OVERLAY_DISABLED),
                None,
            )
        return None, OVERLAY_INK, None

    def _state_colours(
        self, palette: tokens.StudioPalette
    ) -> Tuple[Optional[wx.Colour], wx.Colour, Optional[wx.Colour]]:
        fill, ink, border = self._variant_colours(palette)
        if self.IsEnabled() and (self._pressed or self._hovered):
            alpha = _OVERLAY_PRESSED_ALPHA if self._pressed else _OVERLAY_HOVER_ALPHA
            fill = wx.Colour(255, 255, 255, alpha)
        return fill, ink, border

    def _focus_ink(self, palette: tokens.StudioPalette) -> wx.Colour:
        return OVERLAY_INK


class OverlayText(_OnOverlay, StudioText):
    """A :class:`StudioText` reading in the overlay ink rather than a role.

    It exists so a caller does not have to remember to recolour every readout
    it puts on a bar, and so the ink survives a theme change: a role-coloured
    caption on a scrim is legible in one theme and gone in the other.
    """

    def __init__(self, parent: wx.Window, label: str = "", **kwargs: Any) -> None:
        super().__init__(parent, label, **kwargs)
        self.SetForegroundColour(OVERLAY_INK)


class OverlayChoice(_OnOverlay, SearchableChoice):
    """The compact dropdown an :class:`OverlayBar` carries.

    It is a :class:`SearchableChoice` throughout -- the same popup, the same
    search field, the same regex opt-in and builder, the same keyboard path --
    drawn small enough to sit in a toolbar and inked for a scrim.  The floating
    label a full-height combo carries is dropped, because a toolbar row has no
    vertical room for one; the label it was given still names the control to a
    screen reader and still titles the popup, so nothing is lost but the pixels.
    """

    WIDTH = 132
    MAX_WIDTH = 280

    def _row_height(self) -> int:
        """Return the closed combo's height.

        The density's control height, so the combo lines up with the buttons
        beside it and clears the touch-target floor at every density rather
        than being sized to whatever a toolbar happened to have room for.
        """
        return tokens.control_height()

    def set_value(self, value: str, *, notify: bool = False) -> None:
        """Choose an option, and re-measure: the combo is sized to its value."""
        super().set_value(value, notify=notify)
        self.InvalidateBestSize()
        self.SetMinSize(self.DoGetBestSize())

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        with measuring(self) as dc:
            dc.SetFont(tokens.font_px(self, point_size(13), _MEDIUM))
            # Only the current value is measured, not the longest option: a
            # toolbar has a fixed width to spend and a dimension list can be
            # arbitrarily long, so the popup is where a long name is read.
            value_width = dc.GetTextExtent(self.value or " ")[0]
        width = min(
            tokens.scaled(self.MAX_WIDTH),
            max(
                tokens.scaled(self.WIDTH),
                value_width + tokens.scaled(42) + TEXT_SLACK * 2,
            ),
        )
        return wx.Size(width, self._row_height())

    def render_to(self, dc: wx.DC, rect: wx.Rect) -> None:
        """Draw the closed combo: its outline, current value, and caret."""
        palette = self.palette()
        with self._painting(dc, rect) as rect:
            radius = tokens.scaled(tokens.RADIUS_SM)
            opened = self._popup is not None
            focused = self.HasFocus() or opened
            fill = None
            if opened or self._pressed:
                fill = wx.Colour(255, 255, 255, _OVERLAY_PRESSED_ALPHA)
            elif self._hovered:
                fill = wx.Colour(255, 255, 255, _OVERLAY_HOVER_ALPHA)
            border = (
                OVERLAY_INK
                if focused
                else wx.Colour(255, 255, 255, _OVERLAY_OUTLINE_ALPHA)
            )
            tokens.draw_round_rect(
                dc, rect, radius, fill, border, border_width=2 if focused else 1
            )
            left = tokens.scaled(11)
            dc.SetFont(tokens.font_px(self, point_size(10)))
            caret_width, caret_height = dc.GetTextExtent("▾")
            caret_x = rect.width - tokens.scaled(10) - caret_width
            dc.SetTextForeground(OVERLAY_INK)
            dc.DrawText("▾", caret_x, (rect.height - caret_height) // 2)
            dc.SetFont(tokens.font_px(self, point_size(13), _MEDIUM))
            value = elide(dc, self.value, max(0, caret_x - left - tokens.scaled(6)))
            note_elision(self, self.value, value, hint=self.hint or self.label)
            dc.DrawText(value, left, (rect.height - dc.GetCharHeight()) // 2)
            if self.HasFocus():
                draw_focus_ring(dc, rect, radius, OVERLAY_INK)


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

    def render_to(self, dc: wx.DC, rect: wx.Rect) -> None:
        """Draw the generated tile, its outline, and the placeholder chip."""
        palette = self.palette()
        with self._painting(dc, rect) as rect:
            width, height = rect.width, rect.height
            side = max(1, min(width, height))
            bitmap = blocks.block_tile_bitmap(self.block_id, side)
            dc.DrawBitmap(bitmap, 0, 0, False)
            tokens.draw_round_rect(
                dc, rect, tokens.scaled(11), None, palette.outline_variant
            )
            dc.SetFont(tokens.mono_font_px(self, point_size(9)))
            text_width, text_height = dc.GetTextExtent(self.label)
            chip = wx.Rect(
                tokens.scaled(6),
                height - text_height - tokens.scaled(9),
                text_width + tokens.scaled(14),
                text_height + tokens.scaled(4),
            )
            tokens.draw_round_rect(dc, chip, tokens.scaled(5), palette.scrim)
            dc.SetTextForeground(wx.Colour(255, 255, 255, 255))
            dc.DrawText(
                self.label, chip.x + tokens.scaled(7), chip.y + tokens.scaled(2)
            )


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

    def render_to(self, dc: wx.DC, rect: wx.Rect) -> None:
        """Draw one face preview and its hover or focus border."""
        palette = self.palette()
        with self._painting(dc, rect) as rect:
            side = max(1, min(rect.width, rect.height))
            dc.DrawBitmap(
                blocks.block_tile_bitmap(self.block_id, side, self.brightness),
                0,
                0,
                False,
            )
            border = (
                palette.primary
                if (self._hovered or self.HasFocus())
                else palette.outline_variant
            )
            tokens.draw_round_rect(dc, rect, tokens.scaled(6), None, border)
            if self.HasFocus():
                draw_focus_ring(dc, rect, tokens.scaled(6), palette.primary)


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

    def _backdrop(self) -> wx.Colour:
        return self.GetBackgroundColour()

    # The three face buttons are windows of their own, so the row's whole
    # appearance is the backdrop the inherited ``render_to`` fills.


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

    def render_to(self, dc: wx.DC, rect: wx.Rect) -> None:
        """Draw the dropped image, or the dashed empty target and its hint."""
        palette = self.palette()
        with self._painting(dc, rect) as rect:
            width, height = rect.width, rect.height
            radius = tokens.scaled(10)
            tokens.draw_round_rect(dc, rect, radius, palette.surface_container)
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
                tokens.draw_round_rect(dc, rect, radius, None, palette.outline_variant)
            else:
                draw_dashed_round_rect(
                    dc,
                    rect,
                    radius,
                    palette.primary if self._hovered else palette.outline,
                )
                dc.SetFont(tokens.font_px(self, point_size(12)))
                dc.SetTextForeground(palette.on_surface_variant)
                lines = wrap_text(dc, self.hint, width - tokens.scaled(24), 2)
                y = (height - dc.GetCharHeight() * len(lines)) // 2
                for line in lines:
                    text_width = dc.GetTextExtent(line)[0]
                    dc.DrawText(line, (width - text_width) // 2, y)
                    y += dc.GetCharHeight()
            if self.HasFocus():
                draw_focus_ring(dc, rect, radius, palette.primary)


class BitmapPreview(wx.Panel, _Themed):
    """A read-only square bitmap preview that paints through ``render_to``.

    A plain ``wx.StaticBitmap`` is a native control: this codebase's capture
    harness composites it through ``PrintWindow`` or a client-DC blit, and
    both routes photograph an empty rectangle wherever there is no real
    on-screen compositor behind the window -- exactly the "photographs
    blank" failure this project's own working notes warn about. Painting the
    bitmap in ``render_to`` instead means the screen and a capture take the
    same code path, so this control shows the same pixels either way.
    """

    def __init__(self, parent: wx.Window, *, size: int = 64, name: str = "") -> None:
        super().__init__(parent, style=wx.WANTS_CHARS | wx.TAB_TRAVERSAL)
        self.size = int(size)
        self._bitmap: Optional[wx.Bitmap] = None
        self._install(name or "Preview")
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.SetInitialSize(self.DoGetBestSize())

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        side = tokens.scaled(self.size)
        return wx.Size(side, side)

    def set_bitmap(self, bitmap: Optional[wx.Bitmap]) -> None:
        """Replace the previewed bitmap, or clear it with ``None``."""
        self._bitmap = bitmap if bitmap is not None and bitmap.IsOk() else None
        self.Refresh()

    def render_to(self, dc: wx.DC, rect: wx.Rect) -> None:
        """Draw the bitmap centred and scaled to fit, over its own backdrop."""
        palette = self.palette()
        with self._painting(dc, rect) as rect:
            radius = tokens.scaled(6)
            tokens.draw_round_rect(
                dc, rect, radius, palette.surface_container, palette.outline
            )
            if self._bitmap is None:
                return
            image = self._bitmap.ConvertToImage()
            source_w = max(1, image.GetWidth())
            source_h = max(1, image.GetHeight())
            scale = min(rect.width / source_w, rect.height / source_h)
            target_w = max(1, int(source_w * scale))
            target_h = max(1, int(source_h * scale))
            if (target_w, target_h) != (source_w, source_h):
                image = image.Scale(target_w, target_h, wx.IMAGE_QUALITY_HIGH)
            bitmap = wx.Bitmap(image)
            x = rect.x + (rect.width - target_w) // 2
            y = rect.y + (rect.height - target_h) // 2
            dc.DrawBitmap(bitmap, x, y, True)


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

    #: The design's row width, and the widest a row grows to before its name
    #: and detail start eliding into their own tooltip.
    WIDTH = 240
    MAX_WIDTH = 520

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        with measuring(self) as dc:
            dc.SetFont(tokens.font_px(self, point_size(13), _MEDIUM))
            name_height = dc.GetCharHeight()
            text_width = dc.GetTextExtent(self.row_name or " ")[0]
            dc.SetFont(tokens.font_px(self, point_size(12)))
            detail_height = dc.GetCharHeight() if self.detail else 0
            if self.detail:
                text_width = max(text_width, dc.GetTextExtent(self.detail)[0])
            dc.SetFont(tokens.mono_font_px(self, point_size(11)))
            tag_width = dc.GetTextExtent(self.tag)[0] if self.tag else 0
            height = max(
                tokens.control_height(),
                name_height + detail_height + tokens.scaled(20),
            )
        chrome = tokens.scaled(36) + (
            tokens.scaled(self.SWATCH + 11) if self.swatch else 0
        )
        width = min(
            tokens.scaled(self.MAX_WIDTH),
            max(
                tokens.scaled(self.WIDTH),
                text_width + tag_width + chrome + TEXT_SLACK * 2,
            ),
        )
        return wx.Size(width, height)

    def activate(self) -> None:
        if self.on_click is None:
            return
        invoke(self.on_click)
        self._emit_button()

    def render_to(self, dc: wx.DC, rect: wx.Rect) -> None:
        """Draw the row surface, its swatch, its two lines, and its tag."""
        palette = self.palette()
        with self._painting(dc, rect) as rect:
            width, height = rect.width, rect.height
            radius = tokens.scaled(tokens.RADIUS_SM + 2)
            interactive = self.on_click is not None
            border = (
                palette.primary
                if interactive and (self._hovered or self.HasFocus())
                else palette.outline_variant
            )
            tokens.draw_round_rect(dc, rect, radius, palette.surface_container, border)
            left = tokens.scaled(12)
            if self.swatch:
                side = tokens.scaled(self.SWATCH)
                tokens.draw_round_rect(
                    dc,
                    wx.Rect(left, (height - side) // 2, side, side),
                    tokens.scaled(6),
                    colour_of(self.swatch),
                    palette.outline_variant,
                )
                left += side + tokens.scaled(11)
            dc.SetFont(tokens.mono_font_px(self, point_size(11)))
            tag_width = dc.GetTextExtent(self.tag)[0] if self.tag else 0
            if self.tag:
                dc.SetTextForeground(palette.primary)
                dc.DrawText(
                    self.tag,
                    width - tokens.scaled(12) - tag_width,
                    (height - dc.GetCharHeight()) // 2,
                )
            available = max(0, width - left - tag_width - tokens.scaled(24))
            dc.SetFont(tokens.font_px(self, point_size(13), _MEDIUM))
            dc.SetTextForeground(palette.on_surface)
            name_height = dc.GetCharHeight()
            detail_height = 0
            if self.detail:
                detail_font = tokens.font_px(self, point_size(12))
                dc.SetFont(detail_font)
                detail_height = dc.GetCharHeight()
            top = (height - name_height - detail_height) // 2
            dc.SetFont(tokens.font_px(self, point_size(13), _MEDIUM))
            drawn_name = elide(dc, self.row_name, available)
            dc.DrawText(drawn_name, left, top)
            drawn_detail = self.detail
            if self.detail:
                dc.SetFont(tokens.font_px(self, point_size(12)))
                dc.SetTextForeground(palette.on_surface_variant)
                drawn_detail = elide(dc, self.detail, available)
                dc.DrawText(drawn_detail, left, top + name_height)
            note_elision(
                self,
                " · ".join(part for part in (self.row_name, self.detail) if part),
                " · ".join(part for part in (drawn_name, drawn_detail) if part),
            )
            if self.HasFocus():
                draw_focus_ring(dc, rect, radius, palette.primary)


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

    def _backdrop(self) -> wx.Colour:
        return self.GetBackgroundColour()

    # Each component box and the camera button is its own window, so the
    # inherited backdrop fill is the whole of this panel's appearance.


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

    def render_to(self, dc: wx.DC, rect: wx.Rect) -> None:
        """Draw the slot's tile or empty fill, its label, and its stack count."""
        palette = self.palette()
        with self._painting(dc, rect) as rect:
            width, height = rect.width, rect.height
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
                tokens.draw_round_rect(dc, rect, radius, palette.surface_container_high)
            selected = bool(self.slot.get("selected"))
            border = (
                palette.primary
                if (selected or self._hovered or self.HasFocus())
                else palette.outline_variant
            )
            tokens.draw_round_rect(dc, rect, radius, None, border)
            short = str(self.slot.get("short") or "")
            if short and not block_id:
                dc.SetFont(tokens.mono_font_px(self, point_size(9)))
                dc.SetTextForeground(palette.on_surface_variant)
                text = elide(dc, short, width - tokens.scaled(6))
                text_width, text_height = dc.GetTextExtent(text)
                dc.DrawText(
                    text, (width - text_width) // 2, (height - text_height) // 2
                )
            count = str(self.slot.get("count") or "")
            if count:
                dc.SetFont(tokens.mono_font_px(self, point_size(9), _MEDIUM))
                dc.SetTextForeground(palette.on_surface)
                count_width, count_height = dc.GetTextExtent(count)
                dc.DrawText(
                    count,
                    width - count_width - tokens.scaled(3),
                    height - count_height - tokens.scaled(2),
                )
            if self.HasFocus():
                draw_focus_ring(dc, rect, radius, palette.primary)


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

    def _backdrop(self) -> wx.Colour:
        return self.GetBackgroundColour()

    # Every slot is its own control, so the grid itself only has a backdrop.


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
        with measuring(self) as dc:
            dc.SetFont(tokens.mono_font_px(self, point_size(12)))
            width = tokens.scaled(200)
            for glyph, label, _selected in self.nodes:
                width = max(
                    width,
                    dc.GetTextExtent(f"{glyph} {label}")[0]
                    + TEXT_SLACK * 2
                    + tokens.scaled(40),
                )
            rows = max(1, len(self.nodes))
            return wx.Size(
                width, rows * tokens.scaled(self.ROW_HEIGHT) + tokens.scaled(20)
            )

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

    def render_to(self, dc: wx.DC, rect: wx.Rect) -> None:
        """Draw the tree frame and one monospaced line per node."""
        palette = self.palette()
        with self._painting(dc, rect) as frame:
            width = frame.width
            tokens.draw_round_rect(
                dc,
                frame,
                tokens.scaled(tokens.RADIUS_SM + 2),
                palette.surface_container,
                palette.outline_variant,
            )
            dc.SetFont(tokens.mono_font_px(self, point_size(12)))
            row_height = tokens.scaled(self.ROW_HEIGHT)
            y = tokens.scaled(10)
            for index, (glyph, label, _selected) in enumerate(self.nodes):
                row = wx.Rect(
                    tokens.scaled(6), y, width - tokens.scaled(12), row_height
                )
                if index == self.selected:
                    tokens.draw_round_rect(
                        dc, row, tokens.scaled(6), palette.primary_container
                    )
                    ink = palette.on_primary_container
                else:
                    ink = palette.on_surface
                text_y = y + (row_height - dc.GetCharHeight()) // 2
                x = row.x + tokens.scaled(8)
                if glyph:
                    dc.SetTextForeground(
                        palette.on_primary_container
                        if index == self.selected
                        else palette.primary
                    )
                    dc.DrawText(glyph, x, text_y)
                    x += dc.GetTextExtent(glyph)[0] + tokens.scaled(8)
                dc.SetTextForeground(ink)
                dc.DrawText(
                    elide(dc, label, max(0, row.GetRight() - x - tokens.scaled(6))),
                    x,
                    text_y,
                )
                y += row_height
            if self.HasFocus():
                draw_focus_ring(
                    dc, frame, tokens.scaled(tokens.RADIUS_SM + 2), palette.primary
                )


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
        with measuring(self) as dc:
            dc.SetFont(tokens.font_px(self, point_size(13)))
            width = (
                dc.GetTextExtent(self.GetLabel())[0]
                + TEXT_SLACK * 2
                + tokens.scaled(28)
            )
            return wx.Size(width, dc.GetCharHeight() + tokens.scaled(28))

    def set_held(self, held: bool, *, notify: bool = True) -> None:
        """Hold or release this key."""
        self.held = bool(held)
        state = (
            copy.studio_label("held", "揸實咗")
            if self.held
            else copy.studio_label("not held yet", "重未揸")
        )
        self.SetName(f"{self.GetLabel()} — {state}")
        self.Refresh()
        if notify:
            invoke(self.on_change, self.held)

    def activate(self) -> None:
        self.set_held(not self.held)

    def render_to(self, dc: wx.DC, rect: wx.Rect) -> None:
        """Draw the key in its held or waiting state."""
        palette = self.palette()
        with self._painting(dc, rect) as rect:
            width, height = rect.width, rect.height
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
            tokens.draw_round_rect(dc, rect, radius, fill, border)
            dc.SetFont(tokens.font_px(self, point_size(13)))
            dc.SetTextForeground(ink)
            label = self.GetLabel() + (
                " · " + copy.studio_label("held", "揸實咗") if self.held else ""
            )
            text = elide(dc, label, width - tokens.scaled(16))
            text_width, text_height = dc.GetTextExtent(text)
            dc.DrawText(text, (width - text_width) // 2, (height - text_height) // 2)
            if self.HasFocus():
                draw_focus_ring(dc, rect, radius, palette.primary)


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
        self._install(copy.studio_label("Two-key authorisation", "雙匙授權"))
        self.status = StudioText(
            self,
            copy.studio_text(
                "Hold both keys, then drag the slider all the way to the right "
                "to authorise.",
                "揸實兩條匙，再將滑桿拉到最右先可以授權。",
            ),
            size_px=12,
            name=copy.studio_label("Authorisation status", "授權狀態"),
        )
        keys = wx.BoxSizer(wx.HORIZONTAL)
        self.key_a = _KeyButton(
            self, copy.studio_label("Press A", "撳 A"), on_change=self._key_changed
        )
        self.key_l = _KeyButton(
            self, copy.studio_label("Press L", "撳 L"), on_change=self._key_changed
        )
        keys.Add(self.key_a, 1, wx.RIGHT, tokens.scaled(tokens.SPACE_SM))
        keys.Add(self.key_l, 1)
        self.slider = wx.Slider(
            self, value=0, minValue=0, maxValue=100, style=wx.SL_HORIZONTAL
        )
        self.slider.SetName(
            copy.studio_label("Slide all the way to authorise", "拉到盡先授權")
        )
        self.slider.Enable(False)
        self.progress = ProgressRow(
            self,
            copy.studio_label("Authorisation progress", "授權進度"),
            0.0,
            "0%",
        )
        self.exit_button = StudioButton(
            self,
            copy.studio_label("Emergency exit", "緊急離開"),
            variant="danger",
            on_click=self.emergency_exit,
            name=copy.studio_label("Emergency exit", "緊急離開"),
            hint=copy.studio_text(
                "Cancel immediately and leave everything unchanged",
                "即刻取消，乜都唔會改",
            ),
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
            copy.studio_text(
                "Hold both keys, then drag the slider all the way to the right "
                "to authorise.",
                "揸實兩條匙，再將滑桿拉到最右先可以授權。",
            )
        )
        self.Layout()

    def emergency_exit(self) -> None:
        """Abandon the gate at once and report it, whatever state it is in."""
        self.reset()
        self.status.SetLabel(
            copy.studio_text("Cancelled. Nothing was changed.", "取消咗。乜都無改過。")
        )
        invoke(self.on_exit)

    # -- events --------------------------------------------------------------
    def _key_changed(self, _held: bool) -> None:
        ready = self.keys_held()
        self.slider.Enable(ready and not self.authorized)
        if ready:
            self.status.SetLabel(
                copy.studio_text(
                    "Both keys are held. Drag the slider to the end.",
                    "兩條匙都揸實咗。將滑桿拉到盡。",
                )
            )
        else:
            self.status.SetLabel(
                copy.studio_text(
                    "Hold both keys before the slider will move.",
                    "要兩條匙都揸實，滑桿先郁得。",
                )
            )
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
            self.status.SetLabel(
                copy.studio_text(
                    "Not authorised — the slider has to reach the end.",
                    "未授權——滑桿要拉到盡先得。",
                )
            )
        event.Skip()

    def _authorize(self) -> None:
        self.authorized = True
        self.slider.Enable(False)
        self.progress.set_progress(1.0, "100%")
        self.status.SetLabel(copy.studio_text("Authorised.", "已授權。"))
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
        # The status resolves its own ink and font from the palette and the
        # live interface scale; pushing either in here would pin what it tracks.
        slider = getattr(self, "slider", None)
        if slider is not None:
            slider.SetBackgroundColour(self.GetBackgroundColour())
            slider.SetForegroundColour(palette.primary)

    def _backdrop(self) -> wx.Colour:
        return self.GetBackgroundColour()

    def render_to(self, dc: wx.DC, rect: wx.Rect) -> None:
        """Draw the completion flourish ring, when one is running."""
        palette = self.palette()
        with self._painting(dc, rect) as ring:
            if self._flourish:
                tokens.draw_round_rect(
                    dc,
                    ring,
                    tokens.scaled(tokens.RADIUS_MD),
                    None,
                    tokens.blend(
                        palette.surface, palette.primary, self._flourish / 6.0
                    ),
                    border_width=2,
                )


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

    def _backdrop(self) -> wx.Colour:
        return self.GetBackgroundColour()

    # The header button and the body panel paint themselves, so the section
    # itself is only its backdrop.


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
        self.count = StudioText(
            self, "Nothing selected", size_px=12, name="Selection count"
        )
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
        # The count resolves its own ink and font from the palette and the live
        # interface scale; pushing either in here would pin what it tracks.

    def _backdrop(self) -> wx.Colour:
        return self.GetBackgroundColour()

    # The count label and every action button is its own window, so the bar
    # itself is only its backdrop.


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
    "OVERLAY_INK",
    "OutlinedField",
    "OverlayBar",
    "OverlayButton",
    "OverlayChoice",
    "OverlayText",
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
    "StudioCheckBox",
    "StudioText",
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
    "overlay_fill",
    "paint_context",
    "point_size",
    "reduced_motion",
    "remember_section",
    "section_states",
    "tracked_width",
    "wrap_text",
]
