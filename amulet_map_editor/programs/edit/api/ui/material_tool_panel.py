"""Material controls for the editing tools' own floating panels.

The tools that run inside the 3D editor -- Paste, Edit chunk, and the operation
panels beside them -- each build a small panel that floats over the canvas.
Since the canvas moved into the Studio's viewport those panels sit directly
beside Material widgets, so a native ``wx.SpinCtrl`` in one of them is visible
in the same glance as an M3 field in the other.

What is here is only what those panels need and the shell's own widget module
does not already provide:

* :class:`ToolPanel` -- the scrolling column a panel is built in, coloured as
  an M3 surface rather than the system button face.
* :class:`NumberField` -- a bounded numeric entry: an M3 outlined box with a
  real text control in it, a step down and a step up button beside it, and one
  line of plain-words feedback underneath when a typed value cannot be used.
* :class:`TupleNumberField` -- three of those for an x/y/z triple, keeping the
  ``.value`` tuple property the rest of the editor reads and writes.
* :class:`StepButton` -- the small square that carries one increment.
* :class:`IconButton` -- an M3 icon button drawing one of the bundled icons
  recoloured to the palette's ink, because those icons are black line art and
  a black icon on a dark surface is an invisible control.

Everything drawn here is drawn through ``render_to``, so it paints on a desktop
nobody is looking at and a capture of one of these panels shows the controls
rather than an empty rectangle.  The single exception is the value inside a
:class:`NumberField`, which lives in a real ``wx.TextCtrl`` for exactly the
reason the shell's own text boxes do -- selection, clipboard, caret and screen
reader behaviour are the platform's rather than a re-implementation -- and a
native control does not answer a print request on a desktop with no compositor.
That hole is the harness's, it is the same one every committed capture of the
Studio's coordinate boxes has, and it is worth the accessibility it buys.
"""

from __future__ import annotations

import logging
import math
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import wx
from wx.lib.scrolledpanel import ScrolledPanel

from amulet_map_editor.api.studio import tokens
from amulet_map_editor.api.studio.widgets import (
    AXIS_COLOURS,
    StudioButton,
    StudioText,
    _Interactive,
    _TextBox,
    _Themed,
    draw_focus_ring,
    format_number,
    invoke,
    measuring,
    point_size,
)

log = logging.getLogger(__name__)

__all__ = [
    "IconButton",
    "NumberField",
    "StepButton",
    "ToolPanel",
    "TupleNumberField",
    "panel_note",
    "refresh_tree",
    "section_heading",
    "tool_button",
]

#: These panels float over the viewport in a narrow column beside the
#: properties pane, so the width budget is what a reader can spare from the
#: world rather than what a settings form would like.  The shell's own text box
#: measures from a 160 design-pixel floor, which is half again too wide here.
VALUE_BOX_WIDTH = 96
VALUE_BOX_HEIGHT = 30
STEP_BUTTON = 26
ROW_GAP = 5
PANEL_PADDING = 8


def refresh_tree(window: wx.Window) -> None:
    """Re-read the palette and repaint ``window`` and everything under it.

    Owner-drawn controls read ``IsEnabled`` while they paint but are not told
    to repaint when an *ancestor* is enabled or disabled -- wx flips the flag
    from the C++ side without going through any override -- so a panel that
    goes grey keeps showing live-looking buttons until something else happens
    to invalidate them.  A native control repaints itself, which is why none of
    this was needed before these panels were Material.
    """
    refresh = getattr(window, "refresh_theme", None)
    if callable(refresh):
        refresh()
        return
    window.Refresh()
    for child in window.GetChildren():
        refresh_tree(child)


class _ValueBox(_TextBox):
    """The shell's text box at the width a floating tool panel can afford.

    The floor is a class attribute on ``_TextBox`` precisely so a surface with
    a different budget can state its own rather than fighting the sizer.

    It also dims when it is disabled.  The paste panel is disabled until it is
    actually holding a structure, and a bright white entry box on a dead panel
    is the interface saying "type here" about a control that will not take it.
    """

    WIDTH = VALUE_BOX_WIDTH
    MAX_WIDTH = 220

    def _apply_theme(self, palette: tokens.StudioPalette) -> None:
        super()._apply_theme(palette)
        text = getattr(self, "text", None)
        if text is None or self.IsEnabled():
            return
        text.SetBackgroundColour(palette.surface_container)
        text.SetForegroundColour(
            tokens.blend(palette.on_surface_variant, palette.surface_container, 0.45)
        )

    def Enable(self, enable: bool = True) -> bool:  # noqa: N802 - wx API spelling
        """Enable the box and re-read the colours the new state implies."""
        changed = super().Enable(enable)
        self._apply_theme(self.palette())
        self.Refresh()
        return changed


class ToolPanel(ScrolledPanel, _Themed):
    """The scrolling column an editing tool builds its controls in.

    It is a flat M3 surface rather than a drawn card on purpose.  This floats
    over a live 3D canvas, so a rounded corner or an inset shadow would show
    the *host's* background through it rather than the world behind it, and the
    result reads as a rendering fault.  A flat sheet in the palette's own
    container colour is honest at every theme.

    The background is painted by the ordinary erase rather than by a paint
    handler.  A scrolled window that paints its own background has to prepare
    the device context for the scroll offset on every route into it, and the
    one thing gained -- a colour this already sets -- is not worth a second way
    for the screen and a capture to disagree.
    """

    def __init__(self, parent: wx.Window, name: str = "Tool options") -> None:
        ScrolledPanel.__init__(self, parent, style=wx.TAB_TRAVERSAL)
        self.sizer = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(self.sizer)
        self._install(name)
        # ``_install`` asks for paint-only backgrounds, which every owner-drawn
        # widget wants and a scroller does not; see the class docstring.
        self.SetBackgroundStyle(wx.BG_STYLE_SYSTEM)
        self.SetupScrolling(scroll_x=False, scrollToTop=False)
        self.SetAutoLayout(True)
        self._apply_theme(self.palette())

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        """Return the width the column's contents actually need.

        The tools size their floating panel from this and add the scrollbar
        metric themselves when the canvas is too short to show all of it, so
        this reports the content size alone.
        """
        sizer = self.GetSizer()
        if sizer is None:  # pragma: no cover - only before the sizer is set
            return wx.Size(tokens.scaled(200), tokens.scaled(200))
        return sizer.CalcMin()

    def Enable(self, enable: bool = True) -> bool:  # noqa: N802 - wx API spelling
        """Enable the column and repaint everything that draws its own state."""
        changed = super().Enable(enable)
        refresh_tree(self)
        return changed

    def _apply_theme(self, palette: tokens.StudioPalette) -> None:
        self.SetBackgroundColour(palette.surface_container)

    def _backdrop(self) -> wx.Colour:
        return self.palette().surface_container


class _SquareButton(wx.Control, _Interactive):
    """Shared state layer, focus ring, and geometry for the small squares.

    Deliberately without an ``__init__``: a subclass has its own state to set
    -- which stroke to draw, which icon to tint -- and setting it on a Python
    object whose wx half has not been constructed yet is how a control ends up
    raising from inside a paint handler.  Each subclass therefore builds the wx
    window itself, sets its own state, and then calls :meth:`_setup`.
    """

    SIDE = STEP_BUTTON
    RADIUS = 7

    def _setup(
        self,
        *,
        hint: str,
        name: str,
        on_click: Optional[Callable[[], None]],
        side: int,
    ) -> None:
        self.hint = str(hint)
        self.on_click = on_click
        self._side = int(side)
        self._install(name or self.hint or "Button")
        self._bind_interaction()
        if self.hint:
            self.SetToolTip(self.hint)
        self.SetInitialSize(self.DoGetBestSize())

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        side = tokens.scaled(self._side)
        return wx.Size(side, side)

    def activate(self) -> None:
        """Run the handler and post a button event, so either binding works."""
        if not self.IsEnabled():
            return
        invoke(self.on_click)
        self._emit_button()

    def set_hint(self, hint: str) -> None:
        """Replace the tooltip, which is also this control's accessible hint."""
        self.hint = str(hint)
        self.SetToolTip(self.hint)

    def _ink(self, palette: tokens.StudioPalette) -> wx.Colour:
        if not self.IsEnabled():
            return tokens.blend(
                palette.on_surface_variant, palette.surface_container, 0.45
            )
        return palette.on_surface_variant

    def _draw_state_layer(
        self, dc: wx.DC, area: wx.Rect, palette: tokens.StudioPalette
    ) -> None:
        radius = tokens.scaled(self.RADIUS)
        if not self.IsEnabled():
            return
        if self._pressed:
            tokens.draw_round_rect(
                dc,
                area,
                radius,
                tokens.blend(palette.surface_container_high, palette.on_surface, 0.10),
            )
        elif self._hovered:
            tokens.draw_round_rect(dc, area, radius, palette.surface_container_high)

    def _draw_focus(
        self, dc: wx.DC, area: wx.Rect, palette: tokens.StudioPalette
    ) -> None:
        if self.HasFocus():
            draw_focus_ring(dc, area, tokens.scaled(self.RADIUS), palette.primary)


class StepButton(_SquareButton):
    """One increment, drawn as a minus or a plus rather than set as a glyph.

    A font that lacks the character draws its own placeholder box, and a step
    button whose glyph is a hollow rectangle reads as broken, so the two
    strokes are drawn.
    """

    def __init__(
        self,
        parent: wx.Window,
        kind: str,
        *,
        hint: str = "",
        name: str = "",
        on_click: Optional[Callable[[], None]] = None,
    ) -> None:
        if kind not in ("minus", "plus"):
            raise ValueError(f"Unknown step button kind: {kind!r}")
        wx.Control.__init__(self, parent, style=wx.BORDER_NONE | wx.WANTS_CHARS)
        self.kind = kind
        self._setup(hint=hint, name=name, on_click=on_click, side=STEP_BUTTON)

    def render_to(self, dc: wx.DC, rect: wx.Rect) -> None:
        """Draw the outlined square, its state layer, and the stroke inside."""
        palette = self.palette()
        with self._painting(dc, rect) as area:
            radius = tokens.scaled(self.RADIUS)
            tokens.draw_round_rect(dc, area, radius, None, palette.outline_variant)
            self._draw_state_layer(dc, area, palette)
            ink = self._ink(palette)
            pen = wx.Pen(ink, max(1, tokens.scaled(2)))
            pen.SetCap(wx.CAP_ROUND)
            dc.SetPen(pen)
            dc.SetBrush(wx.TRANSPARENT_BRUSH)
            middle_x = area.x + area.width // 2
            middle_y = area.y + area.height // 2
            arm = max(3, int(area.width * 0.26))
            dc.DrawLine(middle_x - arm, middle_y, middle_x + arm, middle_y)
            if self.kind == "plus":
                dc.DrawLine(middle_x, middle_y - arm, middle_x, middle_y + arm)
            dc.SetPen(wx.NullPen)
            self._draw_focus(dc, area, palette)


class IconButton(_SquareButton):
    """An M3 icon button drawing a bundled icon in the palette's own ink.

    The icons this takes are black line art carried entirely by an alpha
    channel, which is invisible on a dark surface.  Every distinct ink gets one
    recoloured copy rather than a second set of assets, so the icon follows the
    theme for free and the source of truth stays the one PNG.
    """

    SIDE = 30
    ICON = 22

    def __init__(
        self,
        parent: wx.Window,
        bitmap: wx.Bitmap,
        *,
        hint: str = "",
        name: str = "",
        on_click: Optional[Callable[[], None]] = None,
    ) -> None:
        wx.Control.__init__(self, parent, style=wx.BORDER_NONE | wx.WANTS_CHARS)
        self._source = bitmap
        self._tinted: Dict[Tuple[int, int, int, int], wx.Bitmap] = {}
        self._setup(hint=hint, name=name, on_click=on_click, side=self.SIDE)

    def _icon(self, ink: wx.Colour, side: int) -> wx.Bitmap:
        """Return the icon at ``side`` pixels square, recoloured to ``ink``."""
        key = (ink.Red(), ink.Green(), ink.Blue(), side)
        cached = self._tinted.get(key)
        if cached is not None:
            return cached
        image = self._source.ConvertToImage()
        if side > 0 and (image.GetWidth() != side or image.GetHeight() != side):
            image = image.Scale(side, side, wx.IMAGE_QUALITY_HIGH)
        # ``SetRGB`` over a rectangle replaces the colour and leaves the alpha
        # channel alone, which is the whole of the recolouring: these icons are
        # a black mask, so their shape lives entirely in that alpha.
        image.SetRGB(
            wx.Rect(0, 0, image.GetWidth(), image.GetHeight()),
            ink.Red(),
            ink.Green(),
            ink.Blue(),
        )
        bitmap = wx.Bitmap(image)
        self._tinted[key] = bitmap
        return bitmap

    def refresh_theme(self) -> None:
        """Forget the recoloured copies: the ink they were tinted to has moved."""
        self._tinted.clear()
        super().refresh_theme()

    def render_to(self, dc: wx.DC, rect: wx.Rect) -> None:
        """Draw the state layer, the recoloured icon, and the focus ring."""
        palette = self.palette()
        with self._painting(dc, rect) as area:
            self._draw_state_layer(dc, area, palette)
            side = tokens.scaled(self.ICON)
            icon = self._icon(self._ink(palette), side)
            dc.DrawBitmap(
                icon,
                area.x + (area.width - side) // 2,
                area.y + (area.height - side) // 2,
                True,
            )
            self._draw_focus(dc, area, palette)


class NumberField(wx.Panel, _Themed):
    """A bounded number: an M3 field, two step buttons, and honest feedback.

    It replaces ``wx.SpinCtrl`` and ``wx.SpinCtrlDouble`` and keeps everything
    those could do -- type a value, roll the wheel over it, press the arrows,
    hold the keyboard arrows -- while looking like the rest of the interface.

    What it adds is that a refused value is *said*.  A native spin control
    silently rewrites what was typed: enter 400 in a box bounded at 320 and it
    becomes 320 with nothing to say it moved, which on a coordinate field means
    blocks land somewhere the reader did not ask for.  The value is still
    bounded -- the tool has to have a usable number -- and a line underneath
    states what happened, in words, until the next edit clears it.

    Judgement waits until the edit is finished (focus leaves, Enter, an arrow,
    the wheel) rather than running on every keystroke, because a field that
    objects at the minus sign of ``-40`` objects at everybody.
    """

    def __init__(
        self,
        parent: wx.Window,
        label: str,
        value: float,
        minimum: float,
        maximum: float,
        *,
        increment: float = 1,
        digits: int = 0,
        wrap: bool = False,
        snap: bool = False,
        axis: str = "",
        tooltip: str = "",
        name: str = "",
        on_change: Optional[Callable[[float], None]] = None,
        on_layout: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self.minimum = float(min(minimum, maximum))
        self.maximum = float(max(minimum, maximum))
        self.digits = max(0, int(digits))
        self.wrap = bool(wrap)
        self.snap = bool(snap)
        self.on_change = on_change
        self.on_layout = on_layout
        self._increment = float(increment) or 1.0
        self._value = self._snapped(float(value))
        self._label = str(label)
        self._name = name or f"{self._label} value".strip()
        self._install(self._name, listen=False)
        # Before any child is built: ``_TextBox`` reads its parent's colour on
        # the way up, so a field themed afterwards leaves its own entry sitting
        # on whatever colour wx defaulted to.
        self._apply_theme(self.palette())

        column = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(column)

        self.caption: Optional[StudioText] = None
        if not axis:
            # A one-letter axis is drawn inside the box; anything longer needs
            # its own line, or it eats the width the number is entered in.
            self.caption = StudioText(
                self,
                self._label,
                size_px=11,
                role="on_surface_variant",
                name=f"{self._label} label",
            )
            column.Add(self.caption, 0, wx.BOTTOM, tokens.scaled(2))

        row = wx.BoxSizer(wx.HORIZONTAL)
        column.Add(row, 0, wx.EXPAND)
        self.box = _ValueBox(
            self,
            value=self._format(self._value),
            mono=True,
            height=VALUE_BOX_HEIGHT,
            prefix=str(axis),
            prefix_colour=AXIS_COLOURS.get(str(axis).lower(), ""),
            on_change=self._on_typed,
            name=self._name,
            size_px=12,
            fill_role="surface",
        )
        if tooltip:
            self.box.text.SetToolTip(tooltip)
        row.Add(self.box, 1, wx.ALIGN_CENTER_VERTICAL)
        self.down = StepButton(
            self,
            "minus",
            hint=self._step_hint(-1),
            name=f"Decrease {self._name}",
            on_click=lambda: self.step(-1),
        )
        row.Add(self.down, 0, wx.LEFT | wx.ALIGN_CENTER_VERTICAL, tokens.scaled(4))
        self.up = StepButton(
            self,
            "plus",
            hint=self._step_hint(1),
            name=f"Increase {self._name}",
            on_click=lambda: self.step(1),
        )
        row.Add(self.up, 0, wx.LEFT | wx.ALIGN_CENTER_VERTICAL, tokens.scaled(4))

        self.feedback = StudioText(
            self,
            "",
            size_px=11,
            role="error",
            wrap_width=tokens.scaled(VALUE_BOX_WIDTH + STEP_BUTTON * 2 + 12),
            name=f"{self._name} feedback",
        )
        self.feedback.Hide()
        column.Add(self.feedback, 0, wx.TOP, tokens.scaled(2))

        self.box.text.Bind(wx.EVT_KEY_DOWN, self._on_key_down)
        self.box.text.Bind(wx.EVT_KILL_FOCUS, self._on_kill_focus)
        # Only over the box itself.  The tooltips these boxes inherited say
        # "scroll wheel over ... to change", so the wheel has to work there --
        # but a column of nine fields whose every pixel eats the wheel is a
        # column nobody can scroll, so the rest of the row lets it through.
        self.box.text.Bind(wx.EVT_MOUSEWHEEL, self._on_wheel)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.SetInitialSize(self.DoGetBestSize())

    # -- value ---------------------------------------------------------------
    def _step_hint(self, direction: int) -> str:
        verb = "Increase" if direction > 0 else "Decrease"
        return f"{verb} {self._name} by {format_number(self._increment)}"

    @property
    def increment(self) -> float:
        """How far one arrow press, one wheel notch, or one key moves."""
        return self._increment

    @increment.setter
    def increment(self, increment: float) -> None:
        self._increment = float(increment) or 1.0
        self.down.set_hint(self._step_hint(-1))
        self.up.set_hint(self._step_hint(1))
        # Re-seat the value on the new grid, exactly as the rotation boxes did
        # when free rotation was turned off: a 37 degree angle left sitting
        # under a 90 degree increment is a value the arrows can never return to.
        self.set_value(self._value)

    def _clamp(self, value: float) -> float:
        if self.wrap:
            span = self.maximum - self.minimum
            if span > 0 and not (self.minimum <= value <= self.maximum):
                value = self.minimum + math.fmod(value - self.minimum, span)
                if value < self.minimum:
                    value += span
        return max(self.minimum, min(self.maximum, value))

    def _snapped(self, value: float) -> float:
        """Return ``value`` quantised the way this field's values go, then bounded.

        Two different quantisings, and conflating them was a real regression
        waiting to happen.  ``snap`` is the rotation boxes' behaviour: they move
        in whole increments, so 37 degrees under a 90 degree increment becomes
        0.  Everything else keeps the increment for the *arrows* alone -- the
        scale boxes step by 1 and must still accept a typed 1.5, exactly as the
        ``wx.SpinCtrlDouble`` they replace did.  A field showing no decimals is
        an integer field and rounds to one.
        """
        if self.snap and self._increment > 0:
            value = round(value / self._increment) * self._increment
        elif not self.digits:
            value = round(value)
        return self._clamp(value)

    def _format(self, value: float) -> str:
        if self.digits:
            return f"{value:.{self.digits}f}"
        return str(int(round(value)))

    def GetValue(self) -> float:  # noqa: N802 - wx API spelling
        """Return the committed value.  The ``wx.SpinCtrl`` spelling."""
        return self.value

    def SetValue(self, value: float) -> None:  # noqa: N802 - wx API spelling
        """Set the value without reporting it, as ``wx.SpinCtrl`` does."""
        self.set_value(value)

    @property
    def value(self) -> float:
        return self._value if self.digits else int(round(self._value))

    @value.setter
    def value(self, value: float) -> None:
        self.set_value(value)

    def set_value(self, value: float, *, notify: bool = False) -> None:
        """Snap, bound, and show a value; report it only when asked to.

        Silent by default because ``wx.SpinCtrl.SetValue`` is silent, and every
        caller in the editor sets these boxes from state it has just computed --
        a notifying setter would re-enter the handler that computed it.
        """
        try:
            number = float(value)
        except (TypeError, ValueError):
            return
        previous = self._value
        self._value = self._snapped(number)
        self.box.set_value(self._format(self._value))
        self._clear_feedback()
        if notify and previous != self._value:
            invoke(self.on_change, self.value)

    def step(self, steps: float) -> None:
        """Move by whole increments from the value in the box, and report it."""
        base = self._typed_value()
        self._commit(base + steps * self._increment, notify=True)

    # -- editing -------------------------------------------------------------
    def _typed_value(self) -> float:
        """Return what is in the box if it is a number, else the held value."""
        try:
            return float(self.box.value().strip())
        except ValueError:
            return self._value

    def _on_typed(self, _text: str) -> None:
        """A keystroke landed.  Drop any refusal; judge it when the edit ends."""
        self._clear_feedback()

    def _on_key_down(self, event: wx.KeyEvent) -> None:
        code = event.GetKeyCode()
        if code in (wx.WXK_UP, wx.WXK_NUMPAD_UP):
            self.step(1)
            return
        if code in (wx.WXK_DOWN, wx.WXK_NUMPAD_DOWN):
            self.step(-1)
            return
        if code in (wx.WXK_PAGEUP, wx.WXK_NUMPAD_PAGEUP):
            self.step(10)
            return
        if code in (wx.WXK_PAGEDOWN, wx.WXK_NUMPAD_PAGEDOWN):
            self.step(-10)
            return
        if code in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self._commit_typed()
            return
        if code == wx.WXK_ESCAPE:
            # Abandon the edit and put the held value back, which is the only
            # way out of a half-typed number that does not commit it.
            self.box.set_value(self._format(self._value))
            self._clear_feedback()
            return
        event.Skip()

    def _on_kill_focus(self, event: wx.FocusEvent) -> None:
        # Focus also leaves on the way to being destroyed, and reading a text
        # control whose wx half has already gone raises rather than answering.
        try:
            self._commit_typed()
        except RuntimeError:  # pragma: no cover - only during teardown
            log.debug("A number field lost focus while being destroyed")
        event.Skip()

    def _on_wheel(self, event: wx.MouseEvent) -> None:
        if not self.IsEnabled():
            event.Skip()
            return
        rotation = event.GetWheelRotation()
        if rotation > 0:
            self.step(1)
        elif rotation < 0:
            self.step(-1)

    def _commit_typed(self) -> None:
        """Read the box and make it the value, or say why it did not become one."""
        text = self.box.value().strip()
        try:
            number = float(text)
        except ValueError:
            held = self._format(self._value)
            self._refuse(
                f"“{text}” is not a number, so {held} was kept."
                if text
                else f"An empty box is not a number, so {held} was kept."
            )
            self.box.set_value(held)
            return
        self._commit(number, notify=True, typed=True)

    def _commit(self, number: float, *, notify: bool, typed: bool = False) -> None:
        bounded = self._snapped(number)
        previous = self._value
        self._value = bounded
        self.box.set_value(self._format(bounded))
        if typed and not math.isclose(bounded, number, rel_tol=1e-9, abs_tol=1e-9):
            if number < self.minimum or number > self.maximum:
                self._refuse(
                    f"{format_number(number)} is outside "
                    f"{format_number(self.minimum)} to "
                    f"{format_number(self.maximum)}, so "
                    f"{self._format(bounded)} was used."
                )
            elif self.snap:
                self._refuse(
                    f"This moves in steps of {format_number(self._increment)}, "
                    f"so {self._format(bounded)} was used."
                )
            else:
                self._refuse(
                    f"This takes whole numbers, so {self._format(bounded)} was used."
                )
        else:
            self._clear_feedback()
        if notify and previous != bounded:
            invoke(self.on_change, self.value)

    def _refuse(self, message: str) -> None:
        """Show one line saying what happened to a value that was not taken."""
        self.feedback.SetLabel(message)
        if self.feedback.IsShown():
            self.feedback.Refresh()
        else:
            self.feedback.Show()
            self._relayout()

    def _clear_feedback(self) -> None:
        if self.feedback.IsShown():
            self.feedback.Hide()
            self._relayout()

    def _relayout(self) -> None:
        self.InvalidateBestSize()
        self.SetMinSize(self.DoGetBestSize())
        self.Layout()
        invoke(self.on_layout)

    def refused(self) -> str:
        """The feedback line currently showing, or an empty string."""
        return self.feedback.GetLabel() if self.feedback.IsShown() else ""

    # -- appearance ----------------------------------------------------------
    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        sizer = self.GetSizer()
        if sizer is None:  # pragma: no cover - only before the sizer is set
            return wx.Size(tokens.scaled(160), tokens.scaled(VALUE_BOX_HEIGHT))
        return sizer.CalcMin()

    def _apply_theme(self, palette: tokens.StudioPalette) -> None:
        parent = self.GetParent()
        backdrop = parent.GetBackgroundColour() if parent else palette.surface_container
        self.SetBackgroundColour(
            backdrop if backdrop.IsOk() else palette.surface_container
        )

    def _backdrop(self) -> wx.Colour:
        return self.GetBackgroundColour()


class TupleNumberField(wx.Panel, _Themed):
    """Three bounded numbers as one value, for a coordinate or a transform.

    ``value`` is the whole triple in and out, because a coordinate only means
    something as a set -- and because that is the property the editor's own
    bridge reads and writes when the properties pane moves a pending object.
    """

    def __init__(
        self,
        parent: wx.Window,
        labels: Sequence[str],
        *,
        minimum: float = -30_000_000,
        maximum: float = 30_000_000,
        start_value: float = 0,
        increment: float = 1,
        digits: int = 0,
        wrap: bool = False,
        snap: bool = False,
        group: str = "",
        tooltips: Sequence[str] = (),
        on_change: Optional[Callable[[Tuple[float, ...]], None]] = None,
        on_layout: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self.on_change = on_change
        self._install(group or "Coordinate", listen=False)
        self._apply_theme(self.palette())
        column = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(column)
        self.fields: List[NumberField] = []
        hints = list(tooltips) + [""] * len(labels)
        for index, label in enumerate(labels):
            text = str(label)
            field = NumberField(
                self,
                text,
                start_value,
                minimum,
                maximum,
                increment=increment,
                digits=digits,
                wrap=wrap,
                snap=snap,
                axis=text if len(text) == 1 else "",
                tooltip=hints[index],
                name=f"{group} {text}".strip() if group else text,
                on_change=lambda _value: self._changed(),
                on_layout=on_layout,
            )
            self.fields.append(field)
            column.Add(
                field,
                0,
                wx.EXPAND | (wx.TOP if index else 0),
                tokens.scaled(ROW_GAP) if index else 0,
            )
        padded = self.fields + [None, None, None]
        self.x, self.y, self.z = padded[0], padded[1], padded[2]
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.SetInitialSize(self.DoGetBestSize())

    @property
    def value(self) -> Tuple[float, ...]:
        return tuple(field.value for field in self.fields)

    @value.setter
    def value(self, value: Sequence[float]) -> None:
        for field, number in zip(self.fields, value):
            field.set_value(number)

    @property
    def increment(self) -> float:
        return self.fields[0].increment if self.fields else 1.0

    @increment.setter
    def increment(self, increment: float) -> None:
        for field in self.fields:
            field.increment = increment

    def rotation_radians(self) -> Tuple[float, ...]:
        """The triple read as degrees and answered in radians."""
        return tuple(math.radians(value) for value in self.value)

    def _changed(self) -> None:
        invoke(self.on_change, self.value)

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        sizer = self.GetSizer()
        if sizer is None:  # pragma: no cover - only before the sizer is set
            return wx.Size(tokens.scaled(160), tokens.scaled(VALUE_BOX_HEIGHT))
        return sizer.CalcMin()

    def _apply_theme(self, palette: tokens.StudioPalette) -> None:
        parent = self.GetParent()
        backdrop = parent.GetBackgroundColour() if parent else palette.surface_container
        self.SetBackgroundColour(
            backdrop if backdrop.IsOk() else palette.surface_container
        )

    def _backdrop(self) -> wx.Colour:
        return self.GetBackgroundColour()


# ----------------------------------------------------------------------------
# the small pieces a tool panel repeats
# ----------------------------------------------------------------------------


def section_heading(parent: wx.Window, text: str) -> StudioText:
    """The title above a block of controls, in the shell's caption style."""
    return StudioText(
        parent,
        str(text),
        size_px=11,
        weight=wx.FONTWEIGHT_BOLD,
        role="primary",
        uppercase=True,
        tracking=0.8,
        name=str(text),
    )


def panel_note(parent: wx.Window, text: str, wrap_width: int) -> StudioText:
    """One wrapped sentence of explanation under a control.

    Wrapped at a width taken from the control it explains rather than left to
    size itself: these panels are sized to their own best width, so an
    unwrapped sentence would not be a caption under the boxes -- it would make
    the whole panel as wide as the sentence and push the viewport's own
    controls off the edge of the canvas.
    """
    return StudioText(
        parent,
        str(text),
        size_px=11,
        role="on_surface_variant",
        wrap_width=max(tokens.scaled(140), int(wrap_width)),
        name=str(text)[:60],
    )


def tool_button(
    parent: wx.Window,
    label: str,
    *,
    tooltip: str = "",
    variant: str = "tonal",
    on_click: Optional[Callable[[], None]] = None,
) -> StudioButton:
    """A full-width action button for a tool panel."""
    return StudioButton(
        parent,
        label,
        variant=variant,
        hint=tooltip,
        on_click=on_click,
        name=label,
        height=34,
    )


def measure_text(window: wx.Window, text: str, size_px: float = 11) -> int:
    """Return how wide ``text`` is in ``window``'s own font, in pixels."""
    with measuring(window) as dc:
        dc.SetFont(tokens.font(window, point_size(size_px)))
        return int(dc.GetTextExtent(str(text))[0])
