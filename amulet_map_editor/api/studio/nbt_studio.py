"""The NBT editor: three panes over one tag tree, with a control per tag type.

This is one of the two Studio surfaces the declarative spec renderer cannot
express.  A spec section renders the same control for every row it holds; this
window renders a different control for almost every row, because the whole
point of it is that a byte standing in for a boolean deserves a switch, a
bounded integer deserves a stepper that shows its bounds, a position deserves
three axis-coloured boxes and a button that reads the camera, and an inventory
deserves a grid of slots rather than a list of nested compounds nobody can
read.

What each tag deserves is decided in :mod:`amulet_map_editor.api.studio.nbt_model`,
which has no display dependency at all.  This module builds the window, wires
each control back to the model, and keeps the three views -- form, SNBT, and
hex -- showing the same document.  Editing anything marks the document dirty
and re-serialises the other two views, so switching modes never shows a
snapshot from before the last edit.
"""

from __future__ import annotations

import logging
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import wx

from amulet_map_editor.api.studio import copy as studio_copy
from amulet_map_editor.api.studio import nbt_model as model
from amulet_map_editor.api.studio import tokens, widgets
from amulet_map_editor.api.studio.search import SearchState

log = logging.getLogger(__name__)

#: The design's window size.  Both are clamped to the display before use, so a
#: 1366x768 laptop gets a smaller window rather than one with its footer off
#: the bottom of the screen.
DIALOG_WIDTH = 1280
DIALOG_HEIGHT = 820

#: Fixed pane widths from the design's three-column grid.
LEFT_PANE_WIDTH = 250
RIGHT_PANE_WIDTH = 320

#: The label column of every form row.
LABEL_COLUMN = 190

#: One tree line.
TREE_ROW_HEIGHT = 26

#: wxPython 4.1 added a medium weight; older builds fall back to normal.
_MEDIUM = getattr(wx, "FONTWEIGHT_MEDIUM", wx.FONTWEIGHT_NORMAL)

#: The three view modes, in the order the segmented switch draws them.
MODES: Tuple[Tuple[str, str, str], ...] = (
    ("form", "Form", "表單"),
    ("snbt", "SNBT", "SNBT"),
    ("hex", "Hex", "十六進位"),
)


def _text(english: str, cantonese: str = "") -> str:
    """Return one visible MESSAGE in the reader's language and tone."""
    return studio_copy.studio_text(english, cantonese)


def _label(english: str, cantonese: str = "") -> str:
    """Return one CONTROL label in the reader's language, with no tone.

    Button names, tab names, window titles, placeholders, captions, and
    accessible names go through here.  Most of them are short enough that
    ``studio_text`` would have left them alone anyway -- but that is a guess
    about word count, not a statement of intent, and the first six-word button
    anybody adds is styled the moment it is written.  Saying which function to
    use is what makes the intent survive the next edit.
    """
    return studio_copy.studio_label(english, cantonese)


# ---------------------------------------------------------------------------
# painted primitives
# ---------------------------------------------------------------------------


class _Painted(wx.Control):
    """A record rather than a control: owner-drawn, and not a tab stop.

    A window with three panes of them would otherwise put forty unactionable
    rectangles between the keyboard and the next real control.
    """

    def __init__(self, parent: wx.Window, name: str) -> None:
        super().__init__(parent, style=wx.BORDER_NONE)
        self.SetName(name or "Item")
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)

    def AcceptsFocus(self) -> bool:  # noqa: N802 - wx API spelling
        return False

    def AcceptsFocusFromKeyboard(self) -> bool:  # noqa: N802 - wx API spelling
        return False

    def refresh_theme(self) -> None:
        """Repaint with the live palette."""
        self.InvalidateBestSize()
        self.SetMinSize(self.DoGetBestSize())
        self.Refresh()

    def backdrop(self, palette: tokens.StudioPalette) -> wx.Colour:
        """Return the colour behind this block, so its corners blend in."""
        parent = self.GetParent()
        colour = parent.GetBackgroundColour() if parent else palette.surface
        return colour if colour.IsOk() else palette.surface

    def _on_paint(self, _event: wx.PaintEvent) -> None:  # pragma: no cover
        raise NotImplementedError("Every painted block draws itself.")


class _Caption(_Painted):
    """The 10px uppercase caption above a block of controls.

    It stacks the lines of a bilingual label rather than drawing the newline,
    which is what keeps the second language from being clipped away.
    """

    TRACKING = 1

    def __init__(self, parent: wx.Window, text: str) -> None:
        super().__init__(parent, text.replace("\n", " · "))
        self.text = str(text)
        self.SetInitialSize(self.DoGetBestSize())

    def _font(self) -> wx.Font:
        return tokens.font(self, widgets.point_size(10), wx.FONTWEIGHT_BOLD)

    def lines(self) -> List[str]:
        """Return the caption's lines, upper-cased as the design draws them."""
        return [line.upper() for line in self.text.split("\n") if line]

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        dc = wx.ClientDC(self)
        dc.SetFont(self._font())
        tracking = tokens.scaled(self.TRACKING)
        rows = self.lines() or [""]
        width = max(widgets.tracked_width(dc, line, tracking) for line in rows)
        return wx.Size(width + 2, dc.GetCharHeight() * len(rows) + tokens.scaled(4))

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        _dc, gcdc = widgets.paint_context(self, self.backdrop(palette))
        gcdc.SetFont(self._font())
        gcdc.SetTextForeground(palette.on_surface_variant)
        y = 0
        for line in self.lines():
            widgets.draw_tracked_text(gcdc, line, 0, y, tokens.scaled(self.TRACKING))
            y += gcdc.GetCharHeight()
        del gcdc


class _Eyebrow(_Painted):
    """The small uppercase primary caption above the window title."""

    TRACKING = 1

    def __init__(self, parent: wx.Window, text: str) -> None:
        super().__init__(parent, text.replace("\n", " · "))
        self.text = str(text)
        self.SetInitialSize(self.DoGetBestSize())

    def _font(self) -> wx.Font:
        return tokens.font(self, widgets.point_size(11), wx.FONTWEIGHT_BOLD)

    def lines(self) -> List[str]:
        return [line.upper() for line in self.text.split("\n") if line]

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        dc = wx.ClientDC(self)
        dc.SetFont(self._font())
        tracking = tokens.scaled(self.TRACKING)
        rows = self.lines() or [""]
        width = max(widgets.tracked_width(dc, line, tracking) for line in rows)
        return wx.Size(width + 2, dc.GetCharHeight() * len(rows) + tokens.scaled(4))

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        _dc, gcdc = widgets.paint_context(self, self.backdrop(palette))
        gcdc.SetFont(self._font())
        gcdc.SetTextForeground(palette.primary)
        y = 0
        for line in self.lines():
            widgets.draw_tracked_text(gcdc, line, 0, y, tokens.scaled(self.TRACKING))
            y += gcdc.GetCharHeight()
        del gcdc


class _Pill(_Painted):
    """A tinted monospaced pill: the source label, and a container's size."""

    def __init__(self, parent: wx.Window, text: str, *, name: str = "") -> None:
        super().__init__(parent, name or str(text))
        self.text = str(text)
        self.SetInitialSize(self.DoGetBestSize())

    def _font(self) -> wx.Font:
        return tokens.mono_font(self, widgets.point_size(11))

    def set_text(self, text: str) -> None:
        """Replace the pill's text and re-measure it."""
        self.text = str(text)
        self.SetName(self.text)
        self.refresh_theme()

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        dc = wx.ClientDC(self)
        dc.SetFont(self._font())
        width, height = dc.GetTextExtent(self.text or " ")
        return wx.Size(width + tokens.scaled(20), height + tokens.scaled(8))

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        _dc, gcdc = widgets.paint_context(self, self.backdrop(palette))
        width, height = self.GetClientSize()
        rect = wx.Rect(0, 0, width, height)
        # The design's tint role is translucent, so it is composited onto the
        # strip behind it rather than drawn straight over it.
        fill = tokens.blend(self.backdrop(palette), palette.primary, 0.14)
        tokens.draw_round_rect(gcdc, rect, height // 2, fill)
        gcdc.SetFont(self._font())
        gcdc.SetTextForeground(palette.on_primary_container)
        text = widgets.elide(gcdc, self.text, width - tokens.scaled(16))
        text_width, text_height = gcdc.GetTextExtent(text)
        gcdc.DrawText(text, (width - text_width) // 2, (height - text_height) // 2)
        del gcdc


class _InspectorRow(_Painted):
    """One label-and-value row of the selected-tag inspector."""

    def __init__(self, parent: wx.Window, label: str, value: str) -> None:
        super().__init__(parent, f"{label}: {value}")
        self.label = str(label)
        self.value = str(value)
        self.SetInitialSize(self.DoGetBestSize())

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        dc = wx.ClientDC(self)
        dc.SetFont(tokens.mono_font(self, widgets.point_size(11)))
        lines = max(1, len(self._value_lines(dc, tokens.scaled(150))))
        return wx.Size(
            tokens.scaled(RIGHT_PANE_WIDTH - 28),
            dc.GetCharHeight() * lines + tokens.scaled(18),
        )

    def _value_lines(self, dc: wx.DC, width: int) -> List[str]:
        return widgets.wrap_text(dc, self.value, max(40, width), max_lines=3)

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        _dc, gcdc = widgets.paint_context(self, self.backdrop(palette))
        width, height = self.GetClientSize()
        tokens.draw_round_rect(
            gcdc,
            wx.Rect(0, 0, width, height),
            tokens.scaled(9),
            palette.surface,
            palette.outline_variant,
        )
        padding = tokens.scaled(11)
        gcdc.SetFont(tokens.font(self, widgets.point_size(11)))
        gcdc.SetTextForeground(palette.on_surface_variant)
        label_width = min(
            gcdc.GetTextExtent(self.label)[0], max(0, width // 2 - padding)
        )
        gcdc.DrawText(
            widgets.elide(gcdc, self.label, label_width),
            padding,
            (height - gcdc.GetCharHeight()) // 2,
        )
        gcdc.SetFont(tokens.mono_font(self, widgets.point_size(11)))
        gcdc.SetTextForeground(palette.on_surface)
        available = max(20, width - label_width - padding * 3)
        lines = self._value_lines(gcdc, available)
        line_height = gcdc.GetCharHeight()
        y = (height - line_height * len(lines)) // 2
        for line in lines:
            line_width = gcdc.GetTextExtent(line)[0]
            gcdc.DrawText(line, width - padding - line_width, y)
            y += line_height
        del gcdc


class _NoteBlock(_Painted):
    """The validation panel: a surface with a coloured rule down its left edge."""

    def __init__(self, parent: wx.Window, text: str, *, severity: str = "ok") -> None:
        super().__init__(parent, text[:120] or "Validation")
        self.text = str(text)
        self.severity = str(severity)
        self._wrapped_at = 0
        self.Bind(wx.EVT_SIZE, self._on_resize)
        self.SetInitialSize(self.DoGetBestSize())

    def set_note(self, text: str, severity: str) -> None:
        """Replace the message and its severity, then re-measure."""
        self.text = str(text)
        self.severity = str(severity)
        self.SetName(self.text[:120] or "Validation")
        self._wrapped_at = 0
        self.refresh_theme()

    def _accent(self, palette: tokens.StudioPalette) -> wx.Colour:
        if self.severity == "error":
            return palette.error
        if self.severity == "warning":
            return tokens.blend(palette.primary, palette.error, 0.5)
        return palette.primary

    def _on_resize(self, event: wx.SizeEvent) -> None:
        width = self.GetSize().width
        if width and width != self._wrapped_at:
            self._wrapped_at = width
            self.InvalidateBestSize()
            self.SetMinSize(wx.Size(-1, self.DoGetBestSize().height))
            parent = self.GetParent()
            if parent is not None:
                parent.Layout()
        self.Refresh()
        event.Skip()

    def _lines(self, dc: wx.DC, width: int) -> List[str]:
        return widgets.wrap_text(dc, self.text, max(60, width), max_lines=12)

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        dc = wx.ClientDC(self)
        dc.SetFont(tokens.font(self, widgets.point_size(12)))
        width = self.GetSize().width or tokens.scaled(RIGHT_PANE_WIDTH - 28)
        lines = self._lines(dc, width - tokens.scaled(28))
        height = int(dc.GetCharHeight() * 1.55 * len(lines)) + tokens.scaled(20)
        return wx.Size(width, height)

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        _dc, gcdc = widgets.paint_context(self, self.backdrop(palette))
        width, height = self.GetClientSize()
        rect = wx.Rect(0, 0, width, height)
        tokens.draw_round_rect(gcdc, rect, tokens.scaled(10), palette.surface)
        accent = self._accent(palette)
        gcdc.SetBrush(wx.Brush(accent))
        gcdc.SetPen(wx.TRANSPARENT_PEN)
        gcdc.DrawRectangle(
            0, tokens.scaled(2), tokens.scaled(3), height - tokens.scaled(4)
        )
        gcdc.SetFont(tokens.font(self, widgets.point_size(12)))
        gcdc.SetTextForeground(palette.on_surface)
        padding = tokens.scaled(12)
        lines = self._lines(gcdc, width - padding * 2 - tokens.scaled(4))
        line_height = int(gcdc.GetCharHeight() * 1.55)
        y = tokens.scaled(10)
        for line in lines:
            gcdc.DrawText(line, padding + tokens.scaled(4), y)
            y += line_height
        del gcdc


class _CrumbTrail(_Painted):
    """The monospaced breadcrumb trail above the form."""

    def __init__(self, parent: wx.Window, parts: Sequence[str]) -> None:
        super().__init__(parent, "Path: " + ".".join(parts))
        self.parts = list(parts)
        self.SetInitialSize(self.DoGetBestSize())

    def set_parts(self, parts: Sequence[str]) -> None:
        """Replace the trail and re-measure it."""
        self.parts = list(parts)
        self.SetName("Path: " + ".".join(self.parts))
        self.refresh_theme()

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        dc = wx.ClientDC(self)
        dc.SetFont(tokens.mono_font(self, widgets.point_size(11)))
        width = sum(
            dc.GetTextExtent(f"{part} ")[0] + tokens.scaled(6) for part in self.parts
        )
        return wx.Size(max(tokens.scaled(120), width), tokens.scaled(28))

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        _dc, gcdc = widgets.paint_context(self, self.backdrop(palette))
        width, height = self.GetClientSize()
        gcdc.SetFont(tokens.mono_font(self, widgets.point_size(11)))
        y = (height - gcdc.GetCharHeight()) // 2
        x = 0
        for index, part in enumerate(self.parts):
            last = index == len(self.parts) - 1
            gcdc.SetTextForeground(
                palette.on_surface if last else palette.on_surface_variant
            )
            text = widgets.elide(gcdc, part, max(0, width - x))
            if not text:
                break
            gcdc.DrawText(text, x, y)
            x += gcdc.GetTextExtent(text)[0]
            if not last:
                gcdc.SetTextForeground(palette.outline)
                separator = " › "
                gcdc.DrawText(separator, x, y)
                x += gcdc.GetTextExtent(separator)[0]
        del gcdc


class _FieldLabel(_Painted):
    """The 190px label column of a form row: badge, name, and one-line hint."""

    def __init__(self, parent: wx.Window, badge: str, name: str, hint: str) -> None:
        super().__init__(parent, f"{name} ({badge})")
        self.badge = str(badge)
        # Held as ``title`` rather than ``name``: the window already has a name,
        # and two spellings of it in one class is a trap for the next reader.
        self.title = str(name)
        self.hint = str(hint)
        self.SetInitialSize(self.DoGetBestSize())

    def _hint_lines(self, dc: wx.DC) -> List[str]:
        if not self.hint:
            return []
        dc.SetFont(tokens.font(self, widgets.point_size(11)))
        return widgets.wrap_text(
            dc, self.hint, tokens.scaled(LABEL_COLUMN) - tokens.scaled(4), max_lines=3
        )

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        dc = wx.ClientDC(self)
        dc.SetFont(tokens.font(self, widgets.point_size(12), _MEDIUM))
        height = max(dc.GetCharHeight(), tokens.scaled(16))
        lines = self._hint_lines(dc)
        if lines:
            height += tokens.scaled(3) + int(dc.GetCharHeight() * 1.4 * len(lines))
        return wx.Size(tokens.scaled(LABEL_COLUMN), height)

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        _dc, gcdc = widgets.paint_context(self, self.backdrop(palette))
        width, _height = self.GetClientSize()
        gcdc.SetFont(tokens.mono_font(self, widgets.point_size(9)))
        badge_width = gcdc.GetTextExtent(self.badge)[0] + tokens.scaled(10)
        badge_height = gcdc.GetCharHeight() + tokens.scaled(2)
        badge = wx.Rect(0, 0, badge_width, badge_height)
        tokens.draw_round_rect(
            gcdc, badge, tokens.scaled(4), palette.surface_container_high
        )
        gcdc.SetTextForeground(palette.primary)
        gcdc.DrawText(self.badge, tokens.scaled(5), tokens.scaled(1))
        gcdc.SetFont(tokens.font(self, widgets.point_size(12), _MEDIUM))
        gcdc.SetTextForeground(palette.on_surface)
        name_x = badge_width + tokens.scaled(7)
        gcdc.DrawText(
            widgets.elide(gcdc, self.title, max(0, width - name_x)),
            name_x,
            (badge_height - gcdc.GetCharHeight()) // 2,
        )
        gcdc.SetFont(tokens.font(self, widgets.point_size(11)))
        gcdc.SetTextForeground(palette.on_surface_variant)
        y = badge_height + tokens.scaled(3)
        line_height = int(gcdc.GetCharHeight() * 1.4)
        for line in self._hint_lines(gcdc):
            gcdc.DrawText(line, 0, y)
            y += line_height
        del gcdc


# ---------------------------------------------------------------------------
# interactive primitives
# ---------------------------------------------------------------------------


class _Clickable(wx.Control):
    """A focusable owner-drawn control with the shell's usual key handling.

    ``widgets`` keeps its own interaction mixin private, so this repeats the
    minimum of it: hover and pressed state, Space and Enter activation, a
    visible focus ring drawn by each subclass, and an accessible name.
    """

    def __init__(self, parent: wx.Window, name: str) -> None:
        super().__init__(parent, style=wx.BORDER_NONE | wx.WANTS_CHARS)
        self._hovered = False
        self._pressed = False
        self.SetName(name or "Button")
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetCursor(wx.Cursor(wx.CURSOR_HAND))
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.Bind(wx.EVT_ENTER_WINDOW, self._on_enter)
        self.Bind(wx.EVT_LEAVE_WINDOW, self._on_leave)
        self.Bind(wx.EVT_LEFT_DOWN, self._on_down)
        self.Bind(wx.EVT_LEFT_UP, self._on_up)
        self.Bind(wx.EVT_KEY_DOWN, self._on_key)
        self.Bind(wx.EVT_SET_FOCUS, lambda event: (self.Refresh(), event.Skip()))
        self.Bind(wx.EVT_KILL_FOCUS, lambda event: (self.Refresh(), event.Skip()))

    def AcceptsFocus(self) -> bool:  # noqa: N802 - wx API spelling
        return True

    def AcceptsFocusFromKeyboard(self) -> bool:  # noqa: N802 - wx API spelling
        return True

    def refresh_theme(self) -> None:
        """Repaint with the live palette."""
        self.Refresh()

    def activate(self) -> None:  # pragma: no cover - overridden everywhere
        """Run whatever this control does."""

    def _on_enter(self, event: wx.MouseEvent) -> None:
        self._hovered = True
        self.Refresh()
        event.Skip()

    def _on_leave(self, event: wx.MouseEvent) -> None:
        self._hovered = False
        self._pressed = False
        self.Refresh()
        event.Skip()

    def _on_down(self, event: wx.MouseEvent) -> None:
        self._pressed = True
        self.SetFocus()
        self.Refresh()
        event.Skip()

    def _on_up(self, event: wx.MouseEvent) -> None:
        pressed = self._pressed
        self._pressed = False
        self.Refresh()
        if pressed and self.IsEnabled():
            self.activate()
        event.Skip()

    def _on_key(self, event: wx.KeyEvent) -> None:
        if event.GetKeyCode() in (wx.WXK_SPACE, wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            if self.IsEnabled():
                self.activate()
            return
        event.Skip()

    def _on_paint(self, _event: wx.PaintEvent) -> None:  # pragma: no cover
        raise NotImplementedError("Every clickable control draws itself.")

    def backdrop(self, palette: tokens.StudioPalette) -> wx.Colour:
        """Return the colour behind this control."""
        parent = self.GetParent()
        colour = parent.GetBackgroundColour() if parent else palette.surface
        return colour if colour.IsOk() else palette.surface


class _SegmentButton(_Clickable):
    """One segment of the Form / SNBT / Hex switch."""

    HEIGHT = 26

    def __init__(
        self,
        parent: wx.Window,
        label: str,
        *,
        selected: bool = False,
        on_click: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(parent, label.replace("\n", " · "))
        self.label = str(label)
        self.selected = bool(selected)
        self.on_click = on_click
        self.SetInitialSize(self.DoGetBestSize())

    def set_selected(self, selected: bool) -> None:
        """Set the segment's state without running its callback."""
        self.selected = bool(selected)
        self.Refresh()

    def activate(self) -> None:
        widgets.invoke(self.on_click)

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        dc = wx.ClientDC(self)
        dc.SetFont(tokens.font(self, widgets.point_size(12)))
        lines = self.label.split("\n")
        width = max(dc.GetTextExtent(line or " ")[0] for line in lines)
        height = max(
            tokens.scaled(self.HEIGHT),
            dc.GetCharHeight() * len(lines) + tokens.scaled(6),
        )
        return wx.Size(width + tokens.scaled(28), height)

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        _dc, gcdc = widgets.paint_context(self, self.backdrop(palette))
        width, height = self.GetClientSize()
        rect = wx.Rect(0, 0, width, height)
        if self.selected:
            fill, ink = palette.primary, palette.on_primary
        elif self._hovered or self._pressed:
            fill = tokens.blend(self.backdrop(palette), palette.primary, 0.10)
            ink = palette.on_surface
        else:
            fill, ink = None, palette.on_surface_variant
        if fill is not None:
            tokens.draw_round_rect(gcdc, rect, height // 2, fill)
        gcdc.SetFont(tokens.font(self, widgets.point_size(12)))
        gcdc.SetTextForeground(ink)
        lines = self.label.split("\n")
        line_height = gcdc.GetCharHeight()
        y = (height - line_height * len(lines)) // 2
        for line in lines:
            text = widgets.elide(gcdc, line, width - tokens.scaled(12))
            gcdc.DrawText(text, (width - gcdc.GetTextExtent(text)[0]) // 2, y)
            y += line_height
        if self.HasFocus():
            widgets.draw_focus_ring(gcdc, rect, height // 2, palette.primary)
        del gcdc


class _ModeSwitch(wx.Panel):
    """The rounded container holding the three view segments."""

    def __init__(
        self,
        parent: wx.Window,
        mode: str,
        *,
        on_change: Optional[Callable[[str], None]] = None,
    ) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self.on_change = on_change
        self.mode = str(mode)
        self.SetName("View mode")
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.buttons: Dict[str, _SegmentButton] = {}
        row = wx.BoxSizer(wx.HORIZONTAL)
        for key, english, cantonese in MODES:
            button = _SegmentButton(
                self,
                _label(english, cantonese),
                selected=key == self.mode,
                on_click=lambda name=key: self._choose(name),
            )
            button.SetName(_label(f"{english} view", f"{cantonese}檢視"))
            self.buttons[key] = button
            row.Add(button, 0, wx.RIGHT, tokens.scaled(2))
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(row, 0, wx.ALL, tokens.scaled(2))
        self.SetSizer(outer)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.refresh_theme()

    def _choose(self, mode: str) -> None:
        self.set_mode(mode)
        widgets.invoke(self.on_change, mode)

    def set_mode(self, mode: str) -> None:
        """Select a segment without reporting the change."""
        self.mode = str(mode)
        for key, button in self.buttons.items():
            button.set_selected(key == self.mode)

    def refresh_theme(self) -> None:
        """Re-read the palette for the strip and its segments."""
        palette = tokens.palette()
        parent = self.GetParent()
        backdrop = parent.GetBackgroundColour() if parent else palette.surface
        self.SetBackgroundColour(backdrop if backdrop.IsOk() else palette.surface)
        for button in self.buttons.values():
            button.refresh_theme()
        self.Refresh()

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        _dc, gcdc = widgets.paint_context(self, self.GetBackgroundColour())
        width, height = self.GetClientSize()
        tokens.draw_round_rect(
            gcdc,
            wx.Rect(0, 0, width, height),
            height // 2,
            palette.surface_container_high,
        )
        del gcdc


class _SourceButton(_Clickable):
    """One of the six data sources: a glyph, a label, and its tag count."""

    HEIGHT = 32

    def __init__(
        self,
        parent: wx.Window,
        info: model.SourceInfo,
        count: int,
        *,
        selected: bool = False,
        on_click: Optional[Callable[[str], None]] = None,
    ) -> None:
        label = _label(info.label, "")
        super().__init__(parent, f"{label} · {count} tags")
        self.info = info
        self.label = label
        self.count = int(count)
        self.selected = bool(selected)
        self.on_click = on_click
        self.SetToolTip(f"{info.summary} ({count} tags)")
        self.SetInitialSize(self.DoGetBestSize())

    def set_selected(self, selected: bool) -> None:
        """Set the row's state without running its callback."""
        self.selected = bool(selected)
        self.Refresh()

    def activate(self) -> None:
        widgets.invoke(self.on_click, self.info.key)

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        dc = wx.ClientDC(self)
        dc.SetFont(tokens.font(self, widgets.point_size(12)))
        lines = self.label.split("\n")
        # The density token is the floor every touch target has to reach, and
        # a bilingual label needs whichever of the three figures is tallest.
        height = max(
            tokens.scaled(self.HEIGHT),
            tokens.control_height(),
            dc.GetCharHeight() * len(lines) + tokens.scaled(8),
        )
        return wx.Size(tokens.scaled(LEFT_PANE_WIDTH - 24), height)

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        _dc, gcdc = widgets.paint_context(self, self.backdrop(palette))
        width, height = self.GetClientSize()
        rect = wx.Rect(0, 0, width, height)
        radius = tokens.scaled(tokens.RADIUS_SM)
        if self.selected:
            tokens.draw_round_rect(gcdc, rect, radius, palette.primary_container)
            ink = palette.on_primary_container
            muted = palette.on_primary_container
        else:
            if self._hovered or self._pressed:
                tokens.draw_round_rect(
                    gcdc, rect, radius, palette.surface_container_high
                )
            ink = palette.on_surface
            muted = palette.on_surface_variant
        padding = tokens.scaled(10)
        gcdc.SetFont(tokens.font(self, widgets.point_size(11)))
        gcdc.SetTextForeground(ink)
        glyph = self.info.glyph
        gcdc.DrawText(glyph, padding, (height - gcdc.GetCharHeight()) // 2)
        gcdc.SetFont(tokens.mono_font(self, widgets.point_size(10)))
        gcdc.SetTextForeground(muted)
        count = str(self.count)
        count_width = gcdc.GetTextExtent(count)[0]
        gcdc.DrawText(
            count, width - padding - count_width, (height - gcdc.GetCharHeight()) // 2
        )
        gcdc.SetFont(tokens.font(self, widgets.point_size(12)))
        gcdc.SetTextForeground(ink)
        label_x = padding + tokens.scaled(23)
        available = max(0, width - label_x - count_width - padding * 2)
        lines = self.label.split("\n")
        line_height = gcdc.GetCharHeight()
        y = (height - line_height * len(lines)) // 2
        for line in lines:
            gcdc.DrawText(widgets.elide(gcdc, line, available), label_x, y)
            y += line_height
        if self.HasFocus():
            widgets.draw_focus_ring(gcdc, rect, radius, palette.primary)
        del gcdc


class _TagTreeView(_Clickable):
    """The monospaced tag tree: caret, type badge, and label, one row each.

    The whole tree is one control rather than one control per row: a document
    with two hundred tags would otherwise put two hundred tab stops between the
    reader and the form beside it.  Arrow keys move the selection, left and
    right collapse and expand, and Enter re-reports the current row.
    """

    BADGE_WIDTH = 26
    CARET_WIDTH = 9

    def __init__(
        self,
        parent: wx.Window,
        *,
        on_select: Optional[Callable[[model.Tag], None]] = None,
        on_toggle: Optional[Callable[[model.Tag], None]] = None,
    ) -> None:
        super().__init__(parent, "Tag tree")
        self.on_select = on_select
        self.on_toggle = on_toggle
        self.rows: Tuple[model.TreeRow, ...] = ()
        self.selected_uid: int = -1
        self.empty_message = ""
        self.SetCursor(wx.Cursor(wx.CURSOR_ARROW))

    # -- data ----------------------------------------------------------------
    def set_rows(
        self,
        rows: Sequence[model.TreeRow],
        selected_uid: int,
        *,
        empty_message: str = "",
    ) -> None:
        """Replace the visible rows and re-measure the control."""
        self.rows = tuple(rows)
        self.selected_uid = int(selected_uid)
        self.empty_message = str(empty_message)
        current = self.selected_row()
        self.SetName(
            f"Tag tree: {current.label}" if current is not None else "Tag tree"
        )
        self.InvalidateBestSize()
        self.SetMinSize(self.DoGetBestSize())
        self.Refresh()

    def selected_index(self) -> int:
        """Return the index of the selected row, or ``-1`` when it is hidden."""
        for index, row in enumerate(self.rows):
            if row.tag.uid == self.selected_uid:
                return index
        return -1

    def selected_row(self) -> Optional[model.TreeRow]:
        """Return the selected row, or ``None`` when the filter hides it."""
        index = self.selected_index()
        return self.rows[index] if index >= 0 else None

    def row_top(self, index: int) -> int:
        """Return the y offset of a row, for scrolling it into view."""
        return tokens.scaled(6) + index * tokens.scaled(TREE_ROW_HEIGHT)

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        rows = max(1, len(self.rows))
        height = rows * tokens.scaled(TREE_ROW_HEIGHT) + tokens.scaled(12)
        if not self.rows and self.empty_message:
            height = tokens.scaled(60)
        return wx.Size(tokens.scaled(LEFT_PANE_WIDTH - 24), height)

    # -- interaction ---------------------------------------------------------
    def _row_at(self, y: int) -> int:
        inner = y - tokens.scaled(6)
        if inner < 0:
            return -1
        return inner // max(1, tokens.scaled(TREE_ROW_HEIGHT))

    def _on_down(self, event: wx.MouseEvent) -> None:
        self.SetFocus()
        index = self._row_at(event.GetPosition().y)
        if 0 <= index < len(self.rows):
            row = self.rows[index]
            caret_edge = tokens.scaled(6 + self.CARET_WIDTH + 6)
            if row.expandable and event.GetPosition().x <= caret_edge:
                widgets.invoke(self.on_toggle, row.tag)
            else:
                self.select_index(index)
        event.Skip()

    def _on_up(self, event: wx.MouseEvent) -> None:
        event.Skip()

    def select_index(self, index: int) -> None:
        """Select a row by position and report it."""
        if not self.rows:
            return
        index = max(0, min(len(self.rows) - 1, int(index)))
        row = self.rows[index]
        self.selected_uid = row.tag.uid
        self.SetName(f"Tag tree: {row.label}")
        self.Refresh()
        widgets.invoke(self.on_select, row.tag)

    def activate(self) -> None:
        index = self.selected_index()
        if index >= 0:
            self.select_index(index)

    def _on_key(self, event: wx.KeyEvent) -> None:
        code = event.GetKeyCode()
        index = self.selected_index()
        if code == wx.WXK_DOWN:
            self.select_index(index + 1 if index >= 0 else 0)
            return
        if code == wx.WXK_UP:
            self.select_index(index - 1 if index > 0 else 0)
            return
        if code == wx.WXK_HOME:
            self.select_index(0)
            return
        if code == wx.WXK_END:
            self.select_index(len(self.rows) - 1)
            return
        if code in (wx.WXK_LEFT, wx.WXK_RIGHT) and index >= 0:
            row = self.rows[index]
            opening = code == wx.WXK_RIGHT
            if row.expandable and opening != (row.caret == "▾"):
                widgets.invoke(self.on_toggle, row.tag)
                return
            if not opening and index > 0:
                # Collapsing a leaf walks out to its parent, which is what the
                # left arrow does in every other tree the platform ships.
                depth = row.depth
                for above in range(index - 1, -1, -1):
                    if self.rows[above].depth < depth:
                        self.select_index(above)
                        return
            return
        super()._on_key(event)

    # -- painting ------------------------------------------------------------
    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        _dc, gcdc = widgets.paint_context(self, self.backdrop(palette))
        width, height = self.GetClientSize()
        if not self.rows:
            gcdc.SetFont(tokens.font(self, widgets.point_size(12)))
            gcdc.SetTextForeground(palette.on_surface_variant)
            for offset, line in enumerate(
                widgets.wrap_text(
                    gcdc, self.empty_message, width - tokens.scaled(12), max_lines=4
                )
            ):
                gcdc.DrawText(
                    line,
                    tokens.scaled(6),
                    tokens.scaled(8) + offset * gcdc.GetCharHeight(),
                )
            del gcdc
            return
        row_height = tokens.scaled(TREE_ROW_HEIGHT)
        badge_width = tokens.scaled(self.BADGE_WIDTH)
        caret_width = tokens.scaled(self.CARET_WIDTH)
        focused = self.HasFocus()
        for index, row in enumerate(self.rows):
            top = self.row_top(index)
            if top > height:
                break
            rect = wx.Rect(tokens.scaled(2), top, width - tokens.scaled(4), row_height)
            selected = row.tag.uid == self.selected_uid
            if selected:
                tokens.draw_round_rect(
                    gcdc, rect, tokens.scaled(6), palette.primary_container
                )
                ink = palette.on_primary_container
            else:
                ink = palette.on_surface
            x = rect.x + tokens.scaled(4) + tokens.scaled(9) * row.depth
            gcdc.SetFont(tokens.font(self, widgets.point_size(8)))
            gcdc.SetTextForeground(
                palette.on_primary_container if selected else palette.on_surface_variant
            )
            gcdc.DrawText(row.caret, x, top + (row_height - gcdc.GetCharHeight()) // 2)
            x += caret_width + tokens.scaled(6)
            badge = wx.Rect(
                x, top + tokens.scaled(5), badge_width, row_height - tokens.scaled(10)
            )
            tokens.draw_round_rect(
                gcdc, badge, tokens.scaled(4), palette.surface_container_high
            )
            gcdc.SetFont(tokens.mono_font(self, widgets.point_size(9)))
            gcdc.SetTextForeground(palette.primary)
            badge_text = widgets.elide(gcdc, row.badge, badge.width - tokens.scaled(2))
            gcdc.DrawText(
                badge_text,
                badge.x + (badge.width - gcdc.GetTextExtent(badge_text)[0]) // 2,
                badge.y + (badge.height - gcdc.GetCharHeight()) // 2,
            )
            x += badge_width + tokens.scaled(6)
            gcdc.SetFont(tokens.mono_font(self, widgets.point_size(11)))
            gcdc.SetTextForeground(ink)
            label = widgets.elide(gcdc, row.label, max(0, rect.GetRight() - x))
            gcdc.DrawText(label, x, top + (row_height - gcdc.GetCharHeight()) // 2)
            if selected and focused:
                widgets.draw_focus_ring(gcdc, rect, tokens.scaled(6), palette.primary)
        del gcdc


class _TypeChip(_Clickable):
    """One of the twelve buttons in the "Change tag type" grid."""

    HEIGHT = 26

    def __init__(
        self,
        parent: wx.Window,
        tag_type: model.TagType,
        *,
        selected: bool = False,
        lossy: bool = False,
        hint: str = "",
        on_click: Optional[Callable[[model.TagType], None]] = None,
    ) -> None:
        label = model.type_label(tag_type)
        super().__init__(parent, label)
        self.tag_type = tag_type
        self.label = label
        self.selected = bool(selected)
        self.lossy = bool(lossy)
        self.on_click = on_click
        if hint:
            self.SetToolTip(hint)
        self.SetInitialSize(self.DoGetBestSize())

    def activate(self) -> None:
        widgets.invoke(self.on_click, self.tag_type)

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        dc = wx.ClientDC(self)
        dc.SetFont(tokens.mono_font(self, widgets.point_size(11)))
        width = dc.GetTextExtent(self.label)[0] + tokens.scaled(20)
        return wx.Size(width, tokens.scaled(self.HEIGHT))

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        _dc, gcdc = widgets.paint_context(self, self.backdrop(palette))
        width, height = self.GetClientSize()
        rect = wx.Rect(0, 0, width, height)
        radius = tokens.scaled(6)
        if self.selected:
            fill = palette.primary_container
            ink = palette.on_primary_container
            border = palette.primary
        else:
            fill = None
            border = palette.outline_variant
            ink = palette.on_surface
            if self._hovered or self._pressed:
                border = palette.error if self.lossy else palette.primary
                ink = border
        tokens.draw_round_rect(gcdc, rect, radius, fill, border)
        gcdc.SetFont(tokens.mono_font(self, widgets.point_size(11)))
        gcdc.SetTextForeground(ink)
        text = widgets.elide(gcdc, self.label, width - tokens.scaled(8))
        text_width, text_height = gcdc.GetTextExtent(text)
        gcdc.DrawText(text, (width - text_width) // 2, (height - text_height) // 2)
        if self.lossy and not self.selected:
            gcdc.SetPen(wx.Pen(palette.error, 1))
            gcdc.DrawLine(
                width - tokens.scaled(6),
                tokens.scaled(4),
                width - tokens.scaled(6),
                tokens.scaled(8),
            )
        if self.HasFocus():
            widgets.draw_focus_ring(gcdc, rect, radius, palette.primary)
        del gcdc


class _ElementChip(_Clickable):
    """One value of a packed array, editable by clicking it."""

    def __init__(
        self,
        parent: wx.Window,
        index: int,
        value: str,
        *,
        on_click: Optional[Callable[[int], None]] = None,
    ) -> None:
        super().__init__(parent, f"Element {index}: {value}")
        self.index = int(index)
        self.value = str(value)
        self.on_click = on_click
        self.SetToolTip(f"Element [{index}] — click to edit it")
        self.SetInitialSize(self.DoGetBestSize())

    def activate(self) -> None:
        widgets.invoke(self.on_click, self.index)

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        dc = wx.ClientDC(self)
        dc.SetFont(tokens.mono_font(self, widgets.point_size(11)))
        width, height = dc.GetTextExtent(self.value or " ")
        return wx.Size(width + tokens.scaled(18), height + tokens.scaled(6))

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        _dc, gcdc = widgets.paint_context(self, self.backdrop(palette))
        width, height = self.GetClientSize()
        rect = wx.Rect(0, 0, width, height)
        radius = tokens.scaled(6)
        fill = palette.surface_container_high
        if self._hovered or self._pressed:
            fill = tokens.blend(fill, palette.primary, 0.16)
        tokens.draw_round_rect(gcdc, rect, radius, fill)
        gcdc.SetFont(tokens.mono_font(self, widgets.point_size(11)))
        gcdc.SetTextForeground(palette.on_surface)
        text = widgets.elide(gcdc, self.value, width - tokens.scaled(8))
        text_width, text_height = gcdc.GetTextExtent(text)
        gcdc.DrawText(text, (width - text_width) // 2, (height - text_height) // 2)
        if self.HasFocus():
            widgets.draw_focus_ring(gcdc, rect, radius, palette.primary)
        del gcdc


class _Field(wx.Panel):
    """A bordered entry box: one line by default, three when multiline.

    The outline is painted so it matches the rest of the shell at every theme
    and density, while the entry stays a real ``wx.TextCtrl`` so selection,
    the clipboard, the caret, and screen-reader behaviour are the platform's.
    """

    HEIGHT = 30

    def __init__(
        self,
        parent: wx.Window,
        value: str = "",
        *,
        placeholder: str = "",
        mono: bool = False,
        multiline: bool = False,
        name: str = "Value",
        on_change: Optional[Callable[[str], None]] = None,
        on_commit: Optional[Callable[[str], None]] = None,
        width: int = 0,
    ) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self.on_change = on_change
        self.on_commit = on_commit
        self._mono = bool(mono)
        self._multiline = bool(multiline)
        self._width = int(width)
        self._focused = False
        self.SetName(name)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        style = wx.BORDER_NONE
        if multiline:
            style |= wx.TE_MULTILINE | wx.TE_BESTWRAP
        elif on_commit is not None:
            style |= wx.TE_PROCESS_ENTER
        self.text = wx.TextCtrl(self, value=str(value), style=style, name=name)
        self.text.SetName(name)
        if placeholder:
            self.text.SetHint(str(placeholder))
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.Bind(wx.EVT_SIZE, self._on_size)
        self.text.Bind(wx.EVT_TEXT, self._on_text)
        self.text.Bind(wx.EVT_SET_FOCUS, self._on_focus_change)
        self.text.Bind(wx.EVT_KILL_FOCUS, self._on_focus_change)
        if on_commit is not None and not multiline:
            self.text.Bind(wx.EVT_TEXT_ENTER, self._on_enter)
        self.refresh_theme()
        self.SetInitialSize(self.DoGetBestSize())

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        if self._multiline:
            height = tokens.scaled(22) * 3 + tokens.scaled(18)
        else:
            # The design draws a 30px box; the density token is the floor every
            # touch target has to reach, so the taller of the two wins.
            height = max(tokens.scaled(self.HEIGHT), tokens.control_height())
        width = tokens.scaled(self._width) if self._width else tokens.scaled(180)
        return wx.Size(width, height)

    def value(self) -> str:
        """Return the current text."""
        return self.text.GetValue()

    def set_value(self, text: str) -> None:
        """Replace the text without reporting a change."""
        self.text.ChangeValue(str(text))
        self.Refresh()

    def SetFocus(self) -> None:  # noqa: N802 - wx API spelling
        self.text.SetFocus()

    def refresh_theme(self) -> None:
        """Re-read the palette for the box and the entry inside it."""
        palette = tokens.palette()
        parent = self.GetParent()
        backdrop = parent.GetBackgroundColour() if parent else palette.surface
        self.SetBackgroundColour(backdrop if backdrop.IsOk() else palette.surface)
        self.text.SetBackgroundColour(palette.surface)
        self.text.SetForegroundColour(palette.on_surface)
        self.text.SetFont(
            tokens.mono_font(self, widgets.point_size(12))
            if self._mono
            else tokens.font(self, widgets.point_size(12))
        )
        self.Refresh()

    def _on_size(self, event: wx.SizeEvent) -> None:
        width, height = self.GetClientSize()
        inset = tokens.scaled(10)
        inner_width = max(0, width - inset * 2)
        if self._multiline:
            pad = tokens.scaled(8)
            self.text.SetSize(inset, pad, inner_width, max(0, height - pad * 2))
        else:
            text_height = min(height, self.text.GetBestSize().height or height)
            self.text.SetSize(
                inset, max(0, (height - text_height) // 2), inner_width, text_height
            )
        event.Skip()

    def _on_text(self, event: wx.CommandEvent) -> None:
        widgets.invoke(self.on_change, self.text.GetValue())
        event.Skip()

    def _on_enter(self, event: wx.CommandEvent) -> None:
        widgets.invoke(self.on_commit, self.text.GetValue())
        event.Skip()

    def _on_focus_change(self, event: wx.FocusEvent) -> None:
        self._focused = event.GetEventType() == wx.EVT_SET_FOCUS.typeId
        if not self._focused:
            # Leaving the field ends the burst of typing, which is the moment
            # one revision covering the whole burst belongs in the history.
            widgets.invoke(self.on_commit, self.text.GetValue())
        self.Refresh()
        event.Skip()

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        _dc, gcdc = widgets.paint_context(self, self.GetBackgroundColour())
        width, height = self.GetClientSize()
        tokens.draw_round_rect(
            gcdc,
            wx.Rect(0, 0, width, height),
            tokens.scaled(tokens.RADIUS_SM),
            palette.surface,
            palette.primary if self._focused else palette.outline,
            border_width=2 if self._focused else 1,
        )
        del gcdc


class _SliderRow(wx.Panel):
    """A bounded numeric control: a native slider and a monospaced readout.

    The slider is the platform's own because it already answers arrow keys,
    page keys, home and end, and already reports its value to a screen reader.
    """

    STEPS = 1000

    def __init__(
        self,
        parent: wx.Window,
        value: float,
        minimum: float,
        maximum: float,
        *,
        step: float = 1.0,
        suffix: str = "",
        name: str = "Value",
        on_change: Optional[Callable[[float], None]] = None,
        on_commit: Optional[Callable[[float], None]] = None,
    ) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self.on_commit = on_commit
        self.minimum = float(min(minimum, maximum))
        self.maximum = float(max(minimum, maximum))
        self.step = float(step) if float(step) > 0 else 1.0
        self.suffix = str(suffix)
        self.on_change = on_change
        self.SetName(name)
        span = max(1e-9, self.maximum - self.minimum)
        self._ticks = max(1, min(self.STEPS, int(round(span / self.step))))
        self.slider = wx.Slider(
            self,
            value=self._to_tick(value),
            minValue=0,
            maxValue=self._ticks,
            style=wx.SL_HORIZONTAL,
            name=name,
        )
        self.slider.SetToolTip(
            f"{widgets.format_number(self.minimum)} to "
            f"{widgets.format_number(self.maximum)}"
        )
        self.readout = wx.StaticText(self, label=self._format(float(value)))
        self.readout.SetName(f"{name} value")
        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(self.slider, 1, wx.ALIGN_CENTER_VERTICAL)
        row.Add(
            self.readout,
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            tokens.scaled(tokens.SPACE_SM),
        )
        self.SetSizer(row)
        self.slider.Bind(wx.EVT_SLIDER, self._on_slide)
        self.slider.Bind(wx.EVT_SCROLL_THUMBRELEASE, self._on_settled)
        self.slider.Bind(wx.EVT_KILL_FOCUS, self._on_settled)
        self.refresh_theme()

    def _to_tick(self, value: float) -> int:
        span = max(1e-9, self.maximum - self.minimum)
        ratio = (float(value) - self.minimum) / span
        return max(0, min(self._ticks, int(round(ratio * self._ticks))))

    def _from_tick(self, tick: int) -> float:
        span = self.maximum - self.minimum
        return self.minimum + span * (int(tick) / max(1, self._ticks))

    def _format(self, value: float) -> str:
        return f"{widgets.format_number(value)}{self.suffix}"

    def value(self) -> float:
        """Return the current value in the tag's own units."""
        return self._from_tick(self.slider.GetValue())

    def refresh_theme(self) -> None:
        """Re-read the palette for the row."""
        palette = tokens.palette()
        parent = self.GetParent()
        backdrop = parent.GetBackgroundColour() if parent else palette.surface
        self.SetBackgroundColour(backdrop if backdrop.IsOk() else palette.surface)
        self.readout.SetForegroundColour(palette.primary)
        self.readout.SetFont(tokens.mono_font(self, widgets.point_size(12)))
        self.Refresh()

    def _on_slide(self, event: wx.CommandEvent) -> None:
        value = self.value()
        self.readout.SetLabel(self._format(value))
        self.Layout()
        widgets.invoke(self.on_change, value)
        event.Skip()

    def _on_settled(self, event: wx.Event) -> None:
        """Report the value the drag or the keyboard finally landed on."""
        widgets.invoke(self.on_commit, self.value())
        event.Skip()


class _HistoryRow(wx.Panel):
    """One recorded revision, with the button that restores it."""

    def __init__(
        self,
        parent: wx.Window,
        revision: model.Revision,
        *,
        on_restore: Optional[Callable[[model.Revision], None]] = None,
    ) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self.revision = revision
        self.SetName(f"{revision.label}: {revision.detail}")
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.label = wx.StaticText(
            self, label=f"{revision.label} · {revision.timestamp}"
        )
        self.label.SetName(revision.label)
        self.detail = wx.StaticText(self, label=revision.detail)
        self.detail.SetName(revision.detail)
        self.button = widgets.StudioButton(
            self,
            _label("Restore", "還原"),
            variant="tonal",
            on_click=lambda: widgets.invoke(on_restore, revision),
            name=f"Restore {revision.label}",
            hint=(
                f"Write {revision.label} back as a new revision, leaving the "
                "current one in the history"
            ),
            height=26,
        )
        texts = wx.BoxSizer(wx.VERTICAL)
        texts.Add(self.label, 0)
        texts.Add(self.detail, 0, wx.TOP, tokens.scaled(2))
        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(texts, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, tokens.scaled(8))
        row.Add(self.button, 0, wx.ALIGN_CENTER_VERTICAL)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(row, 1, wx.EXPAND | wx.ALL, tokens.scaled(9))
        self.SetSizer(outer)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.refresh_theme()

    def refresh_theme(self) -> None:
        """Re-read the palette for the row and its button."""
        palette = tokens.palette()
        parent = self.GetParent()
        backdrop = parent.GetBackgroundColour() if parent else palette.surface
        self.SetBackgroundColour(backdrop if backdrop.IsOk() else palette.surface)
        self.label.SetForegroundColour(palette.on_surface)
        self.label.SetFont(tokens.mono_font(self, widgets.point_size(11), _MEDIUM))
        self.detail.SetForegroundColour(palette.on_surface_variant)
        self.detail.SetFont(tokens.font(self, widgets.point_size(11)))
        self.detail.Wrap(tokens.scaled(RIGHT_PANE_WIDTH - 140))
        self.button.refresh_theme()
        self.Refresh()

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        _dc, gcdc = widgets.paint_context(self, self.GetBackgroundColour())
        width, height = self.GetClientSize()
        tokens.draw_round_rect(
            gcdc,
            wx.Rect(0, 0, width, height),
            tokens.scaled(9),
            palette.surface,
            palette.outline_variant,
        )
        del gcdc


class _AddChipButton(_Clickable):
    """The dashed "add an element" affordance beside a run of array chips."""

    def __init__(
        self,
        parent: wx.Window,
        label: str,
        *,
        name: str = "",
        on_click: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(parent, name or label.replace("\n", " · "))
        self.label = str(label)
        self.on_click = on_click
        self.SetInitialSize(self.DoGetBestSize())

    def activate(self) -> None:
        widgets.invoke(self.on_click)

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        dc = wx.ClientDC(self)
        dc.SetFont(tokens.font(self, widgets.point_size(11)))
        lines = self.label.split("\n")
        width = max(dc.GetTextExtent(line or " ")[0] for line in lines)
        height = max(
            tokens.scaled(24), dc.GetCharHeight() * len(lines) + tokens.scaled(6)
        )
        return wx.Size(width + tokens.scaled(20), height)

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        _dc, gcdc = widgets.paint_context(self, self.backdrop(palette))
        width, height = self.GetClientSize()
        rect = wx.Rect(0, 0, width, height)
        radius = tokens.scaled(6)
        if self._hovered or self._pressed:
            tokens.draw_round_rect(
                gcdc,
                rect,
                radius,
                tokens.blend(self.backdrop(palette), palette.primary, 0.10),
            )
        widgets.draw_dashed_round_rect(gcdc, rect, radius, palette.outline)
        gcdc.SetFont(tokens.font(self, widgets.point_size(11)))
        gcdc.SetTextForeground(palette.primary)
        lines = self.label.split("\n")
        line_height = gcdc.GetCharHeight()
        y = (height - line_height * len(lines)) // 2
        for line in lines:
            text = widgets.elide(gcdc, line, width - tokens.scaled(10))
            gcdc.DrawText(text, (width - gcdc.GetTextExtent(text)[0]) // 2, y)
            y += line_height
        if self.HasFocus():
            widgets.draw_focus_ring(gcdc, rect, radius, palette.primary)
        del gcdc


class _EdgePanel(wx.Panel):
    """A pane or strip carrying its own fill and one hairline edge."""

    def __init__(
        self,
        parent: wx.Window,
        *,
        edge: str = "bottom",
        role: str = "surface_container",
    ) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self.edge = str(edge)
        self.role = str(role)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.refresh_theme()

    def refresh_theme(self) -> None:
        """Re-read the palette for the strip and everything on it."""
        self.SetBackgroundColour(tokens.palette().role(self.role))
        for child in self.GetChildren():
            refresh = getattr(child, "refresh_theme", None)
            if callable(refresh):
                refresh()
        self.Refresh()

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        _dc, gcdc = widgets.paint_context(self, palette.role(self.role))
        width, height = self.GetClientSize()
        gcdc.SetPen(wx.Pen(palette.outline_variant, 1))
        if self.edge == "bottom":
            gcdc.DrawLine(0, height - 1, width, height - 1)
        elif self.edge == "top":
            gcdc.DrawLine(0, 0, width, 0)
        elif self.edge == "right":
            gcdc.DrawLine(width - 1, 0, width - 1, height)
        elif self.edge == "left":
            gcdc.DrawLine(0, 0, 0, height)
        del gcdc


class _FormRow(wx.Panel):
    """One form row: the 190px label column beside the control it asked for."""

    def __init__(
        self,
        parent: wx.Window,
        badge: str,
        name: str,
        hint: str,
        build_control: Callable[[wx.Window], wx.Window],
    ) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self.SetName(f"{name} row")
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.label = _FieldLabel(self, badge, name, hint)
        self.control = build_control(self)
        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(
            self.label,
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            tokens.scaled(14),
        )
        row.Add(self.control, 1, wx.ALIGN_CENTER_VERTICAL)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(
            row,
            1,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP | wx.BOTTOM,
            tokens.scaled(12),
        )
        self.SetSizer(outer)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.refresh_theme()

    def refresh_theme(self) -> None:
        """Re-read the palette for the card and its two columns."""
        self.SetBackgroundColour(tokens.palette().surface_container)
        for child in self.GetChildren():
            refresh = getattr(child, "refresh_theme", None)
            if callable(refresh):
                refresh()
        self.Refresh()

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        parent = self.GetParent()
        backdrop = parent.GetBackgroundColour() if parent else palette.surface
        _dc, gcdc = widgets.paint_context(
            self, backdrop if backdrop.IsOk() else palette.surface
        )
        width, height = self.GetClientSize()
        tokens.draw_round_rect(
            gcdc,
            wx.Rect(0, 0, width, height),
            tokens.scaled(11),
            palette.surface_container,
            palette.outline_variant,
        )
        del gcdc


class _CodeView(wx.Panel):
    """The SNBT and hex views: a bordered card around a read-only text area.

    It is a real text control rather than painted text so the reader can
    select, scroll, and copy what they are looking at.  It is read-only
    because it is a view of the document: the footer's Import SNBT… is the
    route that changes it, and a box that accepted typing but discarded it
    would be worse than one that plainly does not.
    """

    def __init__(self, parent: wx.Window, text: str, *, wrap: bool, name: str) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self.SetName(name)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        style = wx.TE_MULTILINE | wx.TE_READONLY | wx.BORDER_NONE
        style |= wx.TE_BESTWRAP if wrap else (wx.TE_DONTWRAP | wx.HSCROLL)
        self.text = wx.TextCtrl(self, value=str(text), style=style, name=name)
        self.text.SetName(name)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(self.text, 1, wx.EXPAND | wx.ALL, tokens.scaled(14))
        self.SetSizer(outer)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.refresh_theme()

    def set_text(self, text: str) -> None:
        """Replace the rendered text, keeping the scroll position sensible."""
        self.text.ChangeValue(str(text))

    def refresh_theme(self) -> None:
        """Re-read the palette for the card and the text inside it."""
        palette = tokens.palette()
        self.SetBackgroundColour(palette.surface_container)
        self.text.SetBackgroundColour(palette.surface_container)
        self.text.SetForegroundColour(palette.on_surface)
        self.text.SetFont(tokens.mono_font(self, widgets.point_size(12)))
        self.Refresh()

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        parent = self.GetParent()
        backdrop = parent.GetBackgroundColour() if parent else palette.surface
        _dc, gcdc = widgets.paint_context(
            self, backdrop if backdrop.IsOk() else palette.surface
        )
        width, height = self.GetClientSize()
        tokens.draw_round_rect(
            gcdc,
            wx.Rect(0, 0, width, height),
            tokens.scaled(11),
            palette.surface_container,
            palette.outline_variant,
        )
        del gcdc


# ---------------------------------------------------------------------------
# the small decision dialogs
# ---------------------------------------------------------------------------


class _PromptDialog(wx.Dialog):
    """A short modal form: add a tag, rename one, or edit an array element.

    It is modal because each of these is a decision that changes the document
    and has to be answered before the edit can proceed.  The submit callback
    returns a :class:`~amulet_map_editor.api.studio.nbt_model.ValidationResult`,
    and a refusal is shown in the dialog rather than closing it and silently
    doing nothing.
    """

    def __init__(
        self,
        parent: wx.Window,
        title: str,
        intro: str,
        fields: Sequence[Tuple[str, str, str, str]],
        *,
        confirm: str,
        on_submit: Callable[[Dict[str, str]], model.ValidationResult],
    ) -> None:
        super().__init__(
            parent,
            title=title,
            style=wx.DEFAULT_DIALOG_STYLE,
            name=title,
        )
        self.on_submit = on_submit
        self._controls: Dict[str, wx.Window] = {}
        palette = tokens.palette()
        self.SetBackgroundColour(palette.surface)

        body = wx.BoxSizer(wx.VERTICAL)
        caption = wx.StaticText(self, label=intro)
        caption.SetName(intro)
        caption.SetForegroundColour(palette.on_surface_variant)
        caption.SetFont(tokens.font(self, widgets.point_size(13)))
        caption.Wrap(tokens.scaled(420))
        body.Add(caption, 0, wx.EXPAND | wx.BOTTOM, tokens.scaled(tokens.SPACE_MD))

        for key, label, kind, value in fields:
            body.Add(
                _Caption(self, label), 0, wx.BOTTOM, tokens.scaled(tokens.SPACE_XS)
            )
            if kind == "type":
                control: wx.Window = widgets.SearchableChoice(
                    self,
                    label,
                    [model.type_label(item) for item in model.TAG_TYPES],
                    value,
                )
            else:
                control = _Field(
                    self,
                    value,
                    mono=kind == "mono",
                    multiline=kind == "long",
                    name=label,
                    width=420,
                )
            self._controls[key] = control
            body.Add(control, 0, wx.EXPAND | wx.BOTTOM, tokens.scaled(tokens.SPACE_MD))

        self.note = _NoteBlock(self, "", severity="ok")
        self.note.Hide()
        body.Add(self.note, 0, wx.EXPAND | wx.BOTTOM, tokens.scaled(tokens.SPACE_SM))

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        buttons.AddStretchSpacer(1)
        self.cancel_button = widgets.StudioButton(
            self,
            _label("Cancel", "取消"),
            variant="text",
            on_click=self._cancel,
            name=_label("Cancel", "取消"),
            height=40,
        )
        self.confirm_button = widgets.StudioButton(
            self,
            confirm,
            variant="filled",
            on_click=self._submit,
            name=confirm,
            height=40,
        )
        buttons.Add(self.cancel_button, 0, wx.RIGHT, tokens.scaled(tokens.SPACE_SM))
        buttons.Add(self.confirm_button, 0)
        body.Add(buttons, 0, wx.EXPAND)

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(body, 1, wx.EXPAND | wx.ALL, tokens.scaled(18))
        self.SetSizerAndFit(outer)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
        first = next(iter(self._controls.values()), None)
        if first is not None:
            first.SetFocus()

    def values(self) -> Dict[str, str]:
        """Return the current entry values by key."""
        out: Dict[str, str] = {}
        for key, control in self._controls.items():
            if isinstance(control, widgets.SearchableChoice):
                out[key] = control.value
            elif isinstance(control, _Field):
                out[key] = control.value()
        return out

    def _submit(self) -> None:
        result = self.on_submit(self.values())
        if result.ok:
            self.EndModal(wx.ID_OK)
            return
        self.note.set_note(result.message, result.severity)
        self.note.Show()
        self.Layout()
        self.Fit()

    def _cancel(self) -> None:
        self.EndModal(wx.ID_CANCEL)

    def _on_char_hook(self, event: wx.KeyEvent) -> None:
        code = event.GetKeyCode()
        if code == wx.WXK_ESCAPE:
            self._cancel()
            return
        if code in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            focus = wx.Window.FindFocus()
            if isinstance(focus, wx.TextCtrl) and focus.IsMultiLine():
                event.Skip()
                return
            self._submit()
            return
        event.Skip()


class _DeleteGateDialog(wx.Dialog):
    """The two-key gate a tag deletion goes through.

    Deleting a tag can take a whole subtree with it, so it is gated exactly as
    every other destructive action in the shell: two keys held independently,
    then a slider through its full travel, with an emergency exit that is
    always available.
    """

    def __init__(self, parent: wx.Window, tag: model.Tag) -> None:
        title = _label("Delete tag", "刪除標籤")
        super().__init__(parent, title=title, style=wx.DEFAULT_DIALOG_STYLE, name=title)
        self.authorized = False
        palette = tokens.palette()
        self.SetBackgroundColour(palette.surface)
        subtree = tag.count() - 1
        detail = (
            f"{model.type_label(tag.tag_type)} {tag.path()} will be removed"
            + (f", and the {subtree} tags inside it with it." if subtree else ".")
            + " The deletion is recorded on the parent tag's history, so it can "
            "be restored from there."
        )
        note = _NoteBlock(self, detail, severity="error")
        note.SetMinSize(wx.Size(tokens.scaled(460), -1))
        self.gate = widgets.KeyGate(
            self, on_authorize=self._authorize, on_exit=self._exit
        )
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(note, 0, wx.EXPAND | wx.BOTTOM, tokens.scaled(tokens.SPACE_MD))
        outer.Add(self.gate, 1, wx.EXPAND)
        frame = wx.BoxSizer(wx.VERTICAL)
        frame.Add(outer, 1, wx.EXPAND | wx.ALL, tokens.scaled(18))
        self.SetSizerAndFit(frame)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)

    def _authorize(self) -> None:
        self.authorized = True
        self.EndModal(wx.ID_OK)

    def _exit(self) -> None:
        self.authorized = False
        self.EndModal(wx.ID_CANCEL)

    def _on_char_hook(self, event: wx.KeyEvent) -> None:
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self._exit()
            return
        event.Skip()


# ---------------------------------------------------------------------------
# the editor
# ---------------------------------------------------------------------------


class NbtStudioDialog(wx.Dialog):
    """The NBT editor: a source rail and tag tree, a form, and an inspector.

    The window owns one :class:`~amulet_map_editor.api.studio.nbt_model.NbtDocument`
    at a time.  Every control writes through the document rather than to the
    tag directly, so every edit is validated, recorded in the tag's own
    history, and reflected in the SNBT and hex views before the reader can
    switch to them.
    """

    def __init__(
        self, parent: wx.Window, *, source: str = model.DEFAULT_SOURCE
    ) -> None:
        title = _label("NBT editor", "NBT 編輯器")
        super().__init__(
            parent,
            title=title,
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
            name=f"Raw data: {title}",
        )
        self.document = model.sample_document(source)
        self.selected: model.Tag = self.document.root
        self.mode = "form"
        self.expanded: set = set(self.document.default_expansion())
        self.tag_search = SearchState(label="Tag")
        self._counts = model.sample_tag_counts()
        # Tags whose value has been applied live but whose revision has not
        # been written yet, each with the value text its burst of edits began
        # from.  Flushed whenever that burst can be said to have ended.
        self._pending: Dict[int, Tuple[model.Tag, str]] = {}
        self._opener = wx.Window.FindFocus()
        self._focus_returned = False
        self._theme_unsubscribe = tokens.register_theme_listener(self.refresh_theme)

        self._build_header()
        self._build_left()
        self._build_centre()
        self._build_right()
        self._build_footer()

        body = wx.BoxSizer(wx.HORIZONTAL)
        body.Add(self.left_pane, 0, wx.EXPAND)
        body.Add(self.centre_pane, 1, wx.EXPAND)
        body.Add(self.right_pane, 0, wx.EXPAND)
        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(self.header, 0, wx.EXPAND)
        root.Add(body, 1, wx.EXPAND)
        root.Add(self.footer, 0, wx.EXPAND)
        self.SetSizer(root)

        self.refresh_tree()
        self.rebuild_centre()
        self.rebuild_right()
        self.refresh_footer()
        self.refresh_theme()
        self.SetClientSize(self._preferred_size())
        self.SetMinSize(wx.Size(tokens.scaled(880), tokens.scaled(560)))
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
        self.Bind(wx.EVT_CLOSE, self._on_close)
        self.Bind(wx.EVT_WINDOW_DESTROY, self._on_destroy)
        self.tree.SetFocus()

    # ------------------------------------------------------------------
    # construction
    # ------------------------------------------------------------------
    def _preferred_size(self) -> wx.Size:
        width = tokens.scaled(DIALOG_WIDTH)
        height = tokens.scaled(DIALOG_HEIGHT)
        try:
            index = wx.Display.GetFromWindow(self)
            area = wx.Display(index if index != wx.NOT_FOUND else 0).GetClientArea()
            width = min(width, area.width - tokens.scaled(48))
            height = min(height, area.height - tokens.scaled(48))
        except Exception:  # pragma: no cover - platform boundary
            log.debug("Could not read the display size; using the design size")
        return wx.Size(max(tokens.scaled(880), width), max(tokens.scaled(560), height))

    def _build_header(self) -> None:
        self.header = _EdgePanel(self, edge="bottom")
        self.eyebrow = _Eyebrow(self.header, _label("Raw data", "原始資料"))
        self.title_text = wx.StaticText(
            self.header, label=_label("NBT editor", "NBT 編輯器")
        )
        self.title_text.SetName(_label("NBT editor", "NBT 編輯器"))
        self.source_pill = _Pill(
            self.header, self.document.source.pill, name="Open data source"
        )
        self.mode_switch = _ModeSwitch(self.header, self.mode, on_change=self.set_mode)
        self.close_button = widgets.StudioButton(
            self.header,
            "✕",
            variant="icon",
            on_click=self.close,
            # The accessible name names the button; the hint is its tooltip,
            # which is the application explaining and keeps its tone.
            name=_label("Close this window", "關閉此視窗"),
            hint=_text("Close this window", "關閉此視窗"),
            height=30,
            min_width=34,
        )
        titles = wx.BoxSizer(wx.VERTICAL)
        titles.Add(self.eyebrow, 0)
        titles.Add(self.title_text, 0, wx.TOP, tokens.scaled(3))
        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(titles, 0, wx.ALIGN_CENTER_VERTICAL)
        row.Add(
            self.source_pill,
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            tokens.scaled(12),
        )
        row.AddStretchSpacer(1)
        row.Add(self.mode_switch, 0, wx.ALIGN_CENTER_VERTICAL)
        row.Add(
            self.close_button,
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            tokens.scaled(12),
        )
        # The design pads the strip 12px all round except on the left, where
        # the title sits 18px in; an explicit spacer keeps both figures rather
        # than averaging them into one border flag.
        line = wx.BoxSizer(wx.HORIZONTAL)
        line.AddSpacer(tokens.scaled(18))
        line.Add(row, 1, wx.EXPAND)
        line.AddSpacer(tokens.scaled(12))
        frame = wx.BoxSizer(wx.VERTICAL)
        frame.AddSpacer(tokens.scaled(12))
        frame.Add(line, 0, wx.EXPAND)
        frame.AddSpacer(tokens.scaled(12))
        self.header.SetSizer(frame)

    def _build_left(self) -> None:
        self.left_pane = _EdgePanel(self, edge="right")
        self.left_pane.SetMinSize(wx.Size(tokens.scaled(LEFT_PANE_WIDTH), -1))
        self.source_caption = _Caption(
            self.left_pane, _label("Data source", "資料來源")
        )
        self.source_buttons: Dict[str, _SourceButton] = {}
        sources = wx.BoxSizer(wx.VERTICAL)
        for info in model.SOURCES:
            button = _SourceButton(
                self.left_pane,
                info,
                self._counts.get(info.key, 0),
                selected=info.key == self.document.key,
                on_click=self.load_source,
            )
            self.source_buttons[info.key] = button
            sources.Add(button, 0, wx.EXPAND | wx.BOTTOM, tokens.scaled(3))
        self.tag_search_bar = widgets.SearchBar(
            self.left_pane,
            _label("Search tags", "搜尋標籤"),
            self.tag_search,
            on_change=self._on_tag_search,
            compact=True,
        )
        self.tree_scroll = wx.ScrolledWindow(
            self.left_pane, style=wx.VSCROLL | wx.HSCROLL
        )
        self.tree_scroll.SetScrollRate(tokens.scaled(8), tokens.scaled(TREE_ROW_HEIGHT))
        self.tree = _TagTreeView(
            self.tree_scroll,
            on_select=self.select_tag,
            on_toggle=self.toggle_expanded,
        )
        tree_sizer = wx.BoxSizer(wx.VERTICAL)
        tree_sizer.Add(self.tree, 0, wx.EXPAND)
        self.tree_scroll.SetSizer(tree_sizer)
        column = wx.BoxSizer(wx.VERTICAL)
        column.Add(
            self.source_caption, 0, wx.LEFT | wx.BOTTOM, tokens.scaled(tokens.SPACE_SM)
        )
        column.Add(sources, 0, wx.EXPAND | wx.BOTTOM, tokens.scaled(14))
        column.Add(
            self.tag_search_bar,
            0,
            wx.EXPAND | wx.BOTTOM,
            tokens.scaled(tokens.SPACE_SM),
        )
        column.Add(self.tree_scroll, 1, wx.EXPAND)
        frame = wx.BoxSizer(wx.VERTICAL)
        frame.Add(column, 1, wx.EXPAND | wx.ALL, tokens.scaled(10))
        self.left_pane.SetSizer(frame)

    def _build_centre(self) -> None:
        self.centre_pane = wx.ScrolledWindow(self, style=wx.VSCROLL | wx.TAB_TRAVERSAL)
        self.centre_pane.SetScrollRate(0, tokens.scaled(12))
        # The sizer is created by each rebuild rather than here: setting a new
        # one destroys the old, and a sizer that had already been nested inside
        # the padding wrapper would be destroyed out from under it.
        self.centre_sizer = wx.BoxSizer(wx.VERTICAL)

    def _build_right(self) -> None:
        self.right_pane = _EdgePanel(self, edge="left")
        self.right_pane.SetMinSize(wx.Size(tokens.scaled(RIGHT_PANE_WIDTH), -1))
        self.right_scroll = wx.ScrolledWindow(
            self.right_pane, style=wx.VSCROLL | wx.TAB_TRAVERSAL
        )
        self.right_scroll.SetScrollRate(0, tokens.scaled(12))
        self.right_sizer = wx.BoxSizer(wx.VERTICAL)
        frame = wx.BoxSizer(wx.VERTICAL)
        frame.Add(self.right_scroll, 1, wx.EXPAND | wx.ALL, tokens.scaled(14))
        self.right_pane.SetSizer(frame)

    def _build_footer(self) -> None:
        self.footer = _EdgePanel(self, edge="top")
        self.footer_buttons: List[widgets.StudioButton] = []

        def add(
            label: str, variant: str, handler: Callable[[], None], hint: str
        ) -> widgets.StudioButton:
            button = widgets.StudioButton(
                self.footer,
                label,
                variant=variant,
                on_click=handler,
                name=label,
                hint=hint,
                height=tokens.control_height(),
            )
            self.footer_buttons.append(button)
            return button

        # The six actions wrap onto a second line at narrow widths, exactly as
        # the design's flex row does; the closing pair stays pinned right so
        # Commit never moves out from under the pointer.
        wrap = wx.WrapSizer(wx.HORIZONTAL)
        row = wx.BoxSizer(wx.HORIZONTAL)
        actions = (
            (
                _label("Add tag", "新增標籤"),
                "tonal",
                self.add_tag,
                _text(
                    "Add a child tag to the selected container.",
                    "喺選中嘅容器加一個子標籤。",
                ),
            ),
            (
                _label("Rename", "重新命名"),
                "outlined",
                self.rename_tag,
                _text(
                    "Rename the selected tag inside its compound.",
                    "喺同一個 compound 入面改名。",
                ),
            ),
            (
                _label("Duplicate", "複製一份"),
                "outlined",
                self.duplicate_tag,
                _text(
                    "Copy the selected tag beside itself.",
                    "喺原本標籤旁邊複製一份。",
                ),
            ),
            (
                _label("Import SNBT…", "匯入 SNBT…"),
                "outlined",
                self.import_snbt,
                _text(
                    "Read SNBT from a file and replace the selected tag.",
                    "由檔案讀 SNBT，換走選中嘅標籤。",
                ),
            ),
            (
                _label("Export SNBT", "匯出 SNBT"),
                "outlined",
                self.export_snbt,
                _text(
                    "Write the document out as SNBT text.",
                    "將成份文件寫做 SNBT 文字。",
                ),
            ),
            (
                _label("Delete tag", "刪除標籤"),
                "danger",
                self.delete_tag,
                _text(
                    "Remove the selected tag, through the two-key gate.",
                    "經兩把鎖嘅關卡刪走選中標籤。",
                ),
            ),
        )
        for label, variant, handler, hint in actions:
            wrap.Add(
                add(label, variant, handler, hint),
                0,
                wx.RIGHT | wx.BOTTOM,
                tokens.scaled(tokens.SPACE_SM),
            )
        row.Add(wrap, 1, wx.ALIGN_CENTER_VERTICAL)
        self.dirty_text = wx.StaticText(self.footer, label=self.document.dirty_text())
        self.dirty_text.SetName("Unsaved state")
        row.Add(
            self.dirty_text,
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            tokens.scaled(tokens.SPACE_SM),
        )
        self.cancel_button = add(
            _label("Cancel", "取消"),
            "text",
            self.cancel,
            _text("Close without committing.", "唔提交就閂咗佢。"),
        )
        row.Add(self.cancel_button, 0, wx.RIGHT, tokens.scaled(tokens.SPACE_XS))
        self.commit_button = add(
            _label("Commit changes", "提交更改"),
            "filled",
            self.commit,
            _text(
                "Validate every tag, record the edits, and close.",
                "驗證每個標籤、記低改動，然後閂窗。",
            ),
        )
        row.Add(self.commit_button, 0, wx.ALIGN_CENTER_VERTICAL)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.AddSpacer(tokens.scaled(12))
        outer.Add(row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, tokens.scaled(16))
        outer.AddSpacer(tokens.scaled(12))
        self.footer.SetSizer(outer)

    # ------------------------------------------------------------------
    # document and selection
    # ------------------------------------------------------------------
    def load_source(self, key: str) -> None:
        """Open one of the six data sources, warning about unsaved edits first."""
        if key == self.document.key:
            return
        self._flush_edits()
        if self.document.dirty and not self._confirm_discard(
            _text(
                "Switching data source discards the edits that have not been "
                "committed. Switch anyway?",
                "轉資料來源會掉咗未提交嘅改動。照轉？",
            )
        ):
            return
        self.document = model.sample_document(key)
        self.selected = self.document.root
        self.expanded = set(self.document.default_expansion())
        for source_key, button in self.source_buttons.items():
            button.set_selected(source_key == self.document.key)
        self.source_pill.set_text(self.document.source.pill)
        self.refresh_tree()
        self.rebuild_centre()
        self.rebuild_right()
        self.refresh_footer()
        self.header.Layout()

    def select_tag(self, tag: model.Tag) -> None:
        """Make ``tag`` the selected tag and rebuild the panes that follow it."""
        self.selected = tag
        if tag.is_container:
            self.expanded.add(tag.uid)
        self.refresh_tree()
        self.rebuild_centre()
        self.rebuild_right()

    def toggle_expanded(self, tag: model.Tag) -> None:
        """Open or close a container in the tree."""
        if tag.uid in self.expanded:
            self.expanded.discard(tag.uid)
        else:
            self.expanded.add(tag.uid)
        self.refresh_tree()

    def _on_tag_search(self, _state: SearchState) -> None:
        self.refresh_tree()

    def refresh_tree(self) -> None:
        """Re-read the tree rows for the current expansion and search."""
        matcher = self.tag_search.matches if self.tag_search.is_active() else None
        rows = self.document.rows(expanded=tuple(self.expanded), matches=matcher)
        empty = self.tag_search.describe_matches(0, "tag")
        self.tree.set_rows(rows, self.selected.uid, empty_message=empty)
        self.tree_scroll.Layout()
        self.tree_scroll.FitInside()
        self._scroll_selection_into_view()

    def _scroll_selection_into_view(self) -> None:
        index = self.tree.selected_index()
        if index < 0:
            return
        step = max(1, tokens.scaled(TREE_ROW_HEIGHT))
        view_x, view_y = self.tree_scroll.GetViewStart()
        height = self.tree_scroll.GetClientSize().height
        top = self.tree.row_top(index)
        first = view_y * step
        if top < first:
            self.tree_scroll.Scroll(view_x, top // step)
        elif top + step > first + height:
            self.tree_scroll.Scroll(view_x, max(0, (top + step - height) // step + 1))

    # ------------------------------------------------------------------
    # centre pane
    # ------------------------------------------------------------------
    def _form_tags(self) -> List[model.Tag]:
        """Return the tags the form shows for the current selection."""
        if self.selected.is_container and self.selected.children:
            return list(self.selected.children)
        return [self.selected]

    def rebuild_centre(self) -> None:
        """Re-render the centre pane for the current mode and selection."""
        # Destroying the controls ends any burst of typing in them, so the
        # revision covering that burst is written before they go.
        self._flush_edits()
        self.centre_pane.DestroyChildren()
        self.centre_sizer = wx.BoxSizer(wx.VERTICAL)
        palette = tokens.palette()
        self.centre_pane.SetBackgroundColour(palette.surface)

        crumbs = wx.BoxSizer(wx.HORIZONTAL)
        self.crumb_trail = _CrumbTrail(
            self.centre_pane, self.document.breadcrumbs(self.selected)
        )
        self.copy_path_button = widgets.StudioButton(
            self.centre_pane,
            _text("Copy path", "複製路徑"),
            variant="outlined",
            on_click=self.copy_path,
            name=_text("Copy path", "複製路徑"),
            hint=f"Copy {self.selected.path()} to the clipboard",
            height=28,
        )
        crumbs.Add(self.crumb_trail, 1, wx.ALIGN_CENTER_VERTICAL)
        crumbs.Add(self.copy_path_button, 0, wx.ALIGN_CENTER_VERTICAL)
        self.centre_sizer.Add(crumbs, 0, wx.EXPAND | wx.BOTTOM, tokens.scaled(14))

        if self.mode == "snbt":
            self.snbt_view = _CodeView(
                self.centre_pane,
                self.document.snbt(self.selected),
                wrap=True,
                name=_text("SNBT text", "SNBT 文字"),
            )
            self.centre_sizer.Add(self.snbt_view, 1, wx.EXPAND)
            self._add_view_note(
                _text(
                    "This is the live serialisation of the selected tag. It is "
                    "read-only here; Import SNBT… is the route that replaces it.",
                    "呢個係選中標籤即時嘅序列化文字，喺呢度淨係睇；要換就用「匯入 SNBT…」。",
                )
            )
        elif self.mode == "hex":
            self.hex_view = _CodeView(
                self.centre_pane,
                self.document.hex_view(self.selected),
                wrap=False,
                name=_text("Hex dump", "十六進位傾印"),
            )
            self.centre_sizer.Add(self.hex_view, 1, wx.EXPAND)
            self._add_view_note(
                _text(
                    "Uncompressed big-endian NBT, exactly as the tag would be "
                    "written to disk.",
                    "未壓縮嘅大端 NBT，同寫落硬碟嗰陣一模一樣。",
                )
            )
        else:
            for tag in self._form_tags():
                row = self._build_form_row(tag)
                self.centre_sizer.Add(row, 0, wx.EXPAND | wx.BOTTOM, tokens.scaled(10))
            if not self.selected.children and self.selected.is_container:
                self._add_view_note(
                    _text(
                        "This container is empty. Add child creates its first tag.",
                        "呢個容器係空嘅，撳「加子標籤」開第一個。",
                    )
                )
        self.centre_pane.SetSizer(
            self._padded(self.centre_sizer, tokens.scaled(18), tokens.scaled(16))
        )
        self.centre_pane.Layout()
        self.centre_pane.FitInside()

    @staticmethod
    def _padded(sizer: wx.Sizer, horizontal: int, vertical: int) -> wx.Sizer:
        """Wrap a sizer in the padding the design gives a pane."""
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.AddSpacer(vertical)
        outer.Add(sizer, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, horizontal)
        outer.AddSpacer(vertical)
        return outer

    def _add_view_note(self, text: str) -> None:
        note = wx.StaticText(self.centre_pane, label=text)
        note.SetName(text)
        note.SetForegroundColour(tokens.palette().on_surface_variant)
        note.SetFont(tokens.font(self.centre_pane, widgets.point_size(11)))
        note.Wrap(tokens.scaled(720))
        self.centre_sizer.Add(note, 0, wx.EXPAND | wx.TOP, tokens.scaled(10))

    def _build_form_row(self, tag: model.Tag) -> _FormRow:
        spec = model.control_for(tag)
        return _FormRow(
            self.centre_pane,
            model.type_badge(tag.tag_type),
            spec.label,
            spec.hint,
            lambda host, item=tag, control=spec: self._build_control(
                host, item, control
            ),
        )

    # ------------------------------------------------------------------
    # one control per tag type
    # ------------------------------------------------------------------
    def _readout(self, parent: wx.Window, text: str) -> wx.StaticText:
        """Return the monospaced value caption that sits beside a control."""
        label = wx.StaticText(parent, label=text)
        label.SetName(f"Stored value {text}")
        label.SetForegroundColour(tokens.palette().on_surface_variant)
        label.SetFont(tokens.mono_font(parent, widgets.point_size(11)))
        return label

    def _host(self, parent: wx.Window) -> wx.Panel:
        """Return a transparent panel that carries a composite control."""
        panel = wx.Panel(parent, style=wx.TAB_TRAVERSAL)
        panel.SetBackgroundColour(tokens.palette().surface_container)
        return panel

    def _build_control(
        self, parent: wx.Window, tag: model.Tag, spec: model.ControlSpec
    ) -> wx.Window:
        """Build the one control this tag's :class:`ControlSpec` asked for."""
        builders: Dict[
            str, Callable[[wx.Window, model.Tag, model.ControlSpec], wx.Window]
        ] = {
            "toggle": self._control_toggle,
            "stepper": self._control_stepper,
            "slider": self._control_slider,
            "select": self._control_select,
            "vector": self._control_vector,
            "chips": self._control_chips,
            "slots": self._control_slots,
            "color": self._control_colour,
            "container": self._control_container,
            "longtext": self._control_longtext,
            "text": self._control_text,
        }
        builder = builders.get(spec.kind, self._control_text)
        return builder(parent, tag, spec)

    def _control_toggle(
        self, parent: wx.Window, tag: model.Tag, spec: model.ControlSpec
    ) -> wx.Window:
        host = self._host(parent)
        readout = self._readout(host, spec.value)

        def changed(value: bool) -> None:
            self._edit(tag, 1 if value else 0)
            readout.SetLabel(model.format_scalar(tag.tag_type, tag.value))
            host.Layout()

        switch = widgets.ToggleSwitch(host, spec.boolean, on_change=changed)
        switch.SetName(f"{spec.label} on or off")
        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(switch, 0, wx.ALIGN_CENTER_VERTICAL)
        row.Add(readout, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, tokens.scaled(12))
        host.SetSizer(row)
        return host

    def _control_stepper(
        self, parent: wx.Window, tag: model.Tag, spec: model.ControlSpec
    ) -> wx.Window:
        stepper = widgets.Stepper(
            parent,
            spec.number,
            spec.minimum,
            spec.maximum,
            on_change=lambda value: self._edit(tag, int(round(value))),
        )
        stepper.SetName(
            f"{spec.label}, a whole number between "
            f"{widgets.format_number(spec.minimum)} and "
            f"{widgets.format_number(spec.maximum)}"
        )
        return stepper

    def _control_slider(
        self, parent: wx.Window, tag: model.Tag, spec: model.ControlSpec
    ) -> wx.Window:
        return _SliderRow(
            parent,
            spec.number,
            spec.minimum,
            spec.maximum,
            step=spec.step,
            name=spec.label,
            on_change=lambda value: self._apply_live(tag, value),
            on_commit=lambda value: self._commit_number(tag, value),
        )

    def _control_select(
        self, parent: wx.Window, tag: model.Tag, spec: model.ControlSpec
    ) -> wx.Window:
        return widgets.SearchableChoice(
            parent,
            spec.label,
            spec.options,
            spec.value,
            on_change=lambda value: self._edit(tag, value),
        )

    @staticmethod
    def _vector_children(tag: model.Tag) -> List[model.Tag]:
        """Return the child tags a vector row edits, in the order it shows them."""
        if tag.tag_type is model.TagType.COMPOUND:
            out: List[model.Tag] = []
            for axis in ("x", "y", "z"):
                child = next(
                    (
                        item
                        for item in tag.children
                        if item.name.casefold() == axis and item.is_numeric
                    ),
                    None,
                )
                if child is not None:
                    out.append(child)
            return out
        return list(tag.children)

    def _control_vector(
        self, parent: wx.Window, tag: model.Tag, spec: model.ControlSpec
    ) -> wx.Window:
        children = self._vector_children(tag)

        def changed(values: Sequence[str]) -> None:
            for child, text in zip(children, values):
                self._apply_live(child, self._coerce(child, text))

        field = widgets.VectorField(parent, spec.parts, on_change=changed)
        field.SetName(f"{spec.label} coordinates")
        return field

    def _control_chips(
        self, parent: wx.Window, tag: model.Tag, spec: model.ControlSpec
    ) -> wx.Window:
        host = self._host(parent)
        wrap = wx.WrapSizer(wx.HORIZONTAL)
        for index, value in enumerate(spec.chips):
            chip = _ElementChip(
                host,
                index,
                value,
                on_click=lambda position=index: self._edit_element(tag, position),
            )
            wrap.Add(chip, 0, wx.RIGHT | wx.BOTTOM, tokens.scaled(5))
        add_button = _AddChipButton(
            host,
            _text("＋ element", "＋ 元素"),
            name=f"Add an element to {spec.label}",
            on_click=lambda: self._add_element(tag),
        )
        wrap.Add(add_button, 0, wx.BOTTOM, tokens.scaled(5))
        host.SetSizer(wrap)
        return host

    def _control_slots(
        self, parent: wx.Window, tag: model.Tag, spec: model.ControlSpec
    ) -> wx.Window:
        grid = widgets.SlotGrid(parent, spec.slots)
        grid.SetName(f"{spec.label}, {len(spec.slots)} stacks")

        def opened(slot) -> None:
            index = int(slot.get("index", -1))
            if 0 <= index < len(tag.children):
                self.select_tag(tag.children[index])

        grid.on_slot = opened
        return grid

    def _control_colour(
        self, parent: wx.Window, tag: model.Tag, spec: model.ControlSpec
    ) -> wx.Window:
        host = self._host(parent)
        row = wx.WrapSizer(wx.HORIZONTAL)
        field = _Field(
            host,
            spec.value,
            mono=True,
            name=f"{spec.label} as a hex colour",
            width=100,
            on_change=lambda text: self._apply_live(tag, model.colour_value(text)),
            on_commit=lambda text: self._commit_text(
                tag, str(model.colour_value(text))
            ),
        )
        for name, colour in spec.swatches:
            swatch = widgets.Swatch(
                host,
                colour,
                name=f"{name} ({colour})",
                size=26,
                on_click=lambda chosen, hex_value=colour: self._set_colour(
                    tag, hex_value, field
                ),
            )
            row.Add(swatch, 0, wx.RIGHT | wx.BOTTOM, tokens.scaled(5))
        row.Add(field, 0, wx.LEFT | wx.BOTTOM, tokens.scaled(3))
        host.SetSizer(row)
        return host

    def _set_colour(self, tag: model.Tag, hex_value: str, field: _Field) -> None:
        """Apply a swatch, keeping the hex entry showing the same colour."""
        field.set_value(hex_value)
        self._edit(tag, model.colour_value(hex_value))

    def _control_container(
        self, parent: wx.Window, tag: model.Tag, spec: model.ControlSpec
    ) -> wx.Window:
        host = self._host(parent)
        pill = _Pill(host, spec.value, name=f"{spec.label}: {spec.value}")
        open_button = widgets.StudioButton(
            host,
            _text("Open", "打開"),
            variant="outlined",
            on_click=lambda: self.select_tag(tag),
            name=f"Open {spec.label}",
            hint=f"Show the tags inside {tag.path()}",
            height=28,
        )
        add_button = widgets.StudioButton(
            host,
            _text("Add child", "加子標籤"),
            variant="tonal",
            on_click=lambda: self.add_tag(tag),
            name=f"Add a child tag to {spec.label}",
            hint=f"Add a new tag inside {tag.path()}",
            height=28,
        )
        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(pill, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, tokens.scaled(8))
        row.Add(open_button, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, tokens.scaled(8))
        row.Add(add_button, 0, wx.ALIGN_CENTER_VERTICAL)
        host.SetSizer(row)
        return host

    def _control_longtext(
        self, parent: wx.Window, tag: model.Tag, spec: model.ControlSpec
    ) -> wx.Window:
        return _Field(
            parent,
            spec.value,
            placeholder=spec.placeholder,
            mono=True,
            multiline=True,
            name=spec.label,
            on_change=lambda text: self._edit_text(tag, text),
            on_commit=lambda text: self._commit_text(tag, text),
        )

    def _control_text(
        self, parent: wx.Window, tag: model.Tag, spec: model.ControlSpec
    ) -> wx.Window:
        return _Field(
            parent,
            spec.value,
            placeholder=spec.placeholder,
            mono=tag.is_numeric,
            name=spec.label,
            on_change=lambda text: self._edit_text(tag, text),
            on_commit=lambda text: self._commit_text(tag, text),
        )

    # ------------------------------------------------------------------
    # editing
    # ------------------------------------------------------------------
    def _edit(self, tag: model.Tag, value) -> None:
        """Write a discrete value through the document and refresh what follows.

        A switch, a stepper press, or a chosen option is one interaction and
        one revision, so it goes straight through rather than through the live
        apply-then-record path that a burst of typing takes.
        """
        self._flush_edits()
        result = self.document.set_value(tag, value)
        self._after_edit(tag, result)

    def _coerce(self, tag: model.Tag, text: str):
        """Return typed text as the payload this tag's type actually holds."""
        kind = model.TYPE_INFO[tag.tag_type].kind
        if kind == "integer":
            return model.coerce_integer(text)
        if kind == "float":
            return model.coerce_float(text)
        return text

    def _apply_live(self, tag: model.Tag, value) -> model.ValidationResult:
        """Apply a value from a control that is still being operated.

        The document is updated immediately -- the tree, the footer, and both
        serialised views follow the live value -- while the one revision that
        covers the whole burst waits for :meth:`_flush_edits`.
        """
        if tag.uid not in self._pending:
            self._pending[tag.uid] = (tag, tag.value_text())
        result = self.document.apply_value(tag, value)
        self.refresh_tree()
        self.refresh_footer()
        return result

    def _flush_edits(self) -> int:
        """Write one revision per burst of edits that has ended, and count them.

        The count is what tells a caller whether anything actually changed: a
        field the reader tabbed through without typing must not rebuild the
        inspector, because rebuilding it while the keyboard is moving would
        destroy the control the focus is moving to.
        """
        if not self._pending:
            return 0
        pending, self._pending = self._pending, {}
        written = 0
        for tag, before in pending.values():
            if self.document.record_edit(tag, before) is not None:
                written += 1
        return written

    def _edit_text(self, tag: model.Tag, text: str) -> None:
        """Apply typed text live, coerced to the tag's own type."""
        self._apply_live(tag, self._coerce(tag, text))

    def _commit_text(self, tag: model.Tag, text: str) -> None:
        """End a burst of typing: record it, then refresh what it changed."""
        result = self.document.apply_value(tag, self._coerce(tag, text))
        if self._flush_edits():
            self._after_edit(tag, result)

    def _commit_number(self, tag: model.Tag, value: float) -> None:
        """End a slider drag: record it, then refresh what it changed."""
        result = self.document.apply_value(tag, value)
        if self._flush_edits():
            self._after_edit(tag, result)

    def _after_edit(
        self,
        tag: model.Tag,
        result: Optional[model.ValidationResult] = None,
        *,
        rebuild_right: bool = True,
    ) -> None:
        """Refresh every pane that shows something the edit changed."""
        self.refresh_tree()
        self.refresh_footer()
        if rebuild_right:
            self.rebuild_right()
        if result is not None and not result.ok:
            self._notify(
                _text("That value is not valid", "呢個值唔正確"),
                result.message,
                severity="warning",
                details=f"Tag: {tag.path()}",
            )

    def _edit_element(self, tag: model.Tag, index: int) -> None:
        """Edit one packed array value through a short modal prompt."""
        if not 0 <= index < len(tag.value):
            return
        info = model.TYPE_INFO[tag.tag_type]

        def submit(values: Dict[str, str]) -> model.ValidationResult:
            updated = list(tag.value)
            updated[index] = model.coerce_integer(values.get("value", "0"))
            candidate = model.Tag(tag.name, tag.tag_type, updated)
            check = model.validate(candidate)
            if not check.ok:
                return check
            return self.document.set_value(tag, updated)

        dialog = _PromptDialog(
            self,
            _text("Edit element", "改元素"),
            _text(
                f"Element [{index}] of {tag.path()}. A {info.label} element holds "
                f"a whole number from {info.minimum} to {info.maximum}.",
                f"{tag.path()} 嘅第 [{index}] 個元素，範圍係 "
                f"{info.minimum} 到 {info.maximum}。",
            ),
            [("value", _text("Value", "數值"), "mono", str(tag.value[index]))],
            confirm=_text("Apply", "套用"),
            on_submit=submit,
        )
        try:
            if dialog.ShowModal() == wx.ID_OK:
                self.rebuild_centre()
                self._after_edit(tag)
        finally:
            dialog.Destroy()

    def _add_element(self, tag: model.Tag) -> None:
        """Append one value to a packed array."""
        updated = list(tag.value) + [0]
        self.document.set_value(tag, updated)
        self.rebuild_centre()
        self._after_edit(tag)

    # ------------------------------------------------------------------
    # right pane
    # ------------------------------------------------------------------
    def rebuild_right(
        self, *, focus_type: Optional[model.TagType] = None, focus_history: bool = False
    ) -> None:
        """Re-render the inspector, type grid, validation, and history.

        Whatever had the keyboard inside this pane is put back on the control
        that replaces it: rebuilding a pane the reader is working in and
        leaving the focus nowhere is how a keyboard route through a window
        silently breaks.
        """
        focus_type = focus_type or self._focused_type()
        focus_history = focus_history or self._focus_is_in_history()
        self.right_scroll.DestroyChildren()
        self.right_sizer = wx.BoxSizer(wx.VERTICAL)
        self.right_scroll.SetSizer(self.right_sizer)
        palette = tokens.palette()
        self.right_scroll.SetBackgroundColour(palette.surface_container)
        tag = self.selected

        self.right_sizer.Add(
            _Caption(self.right_scroll, _text("Selected tag", "選中標籤")),
            0,
            wx.BOTTOM,
            tokens.scaled(tokens.SPACE_SM),
        )
        for label, value in self._inspector_rows(tag):
            self.right_sizer.Add(
                _InspectorRow(self.right_scroll, label, value),
                0,
                wx.EXPAND | wx.BOTTOM,
                tokens.scaled(7),
            )

        self.right_sizer.AddSpacer(tokens.scaled(7))
        self.right_sizer.Add(
            _Caption(self.right_scroll, _text("Change tag type", "更改標籤類型")),
            0,
            wx.BOTTOM,
            tokens.scaled(tokens.SPACE_SM),
        )
        types = wx.WrapSizer(wx.HORIZONTAL)
        self.type_chips: Dict[model.TagType, _TypeChip] = {}
        for tag_type in model.TAG_TYPES:
            report = model.retype_preview(tag, tag_type)
            chip = _TypeChip(
                self.right_scroll,
                tag_type,
                selected=tag_type is tag.tag_type,
                lossy=not report.ok or report.lossy,
                hint=report.message,
                on_click=self.change_type,
            )
            self.type_chips[tag_type] = chip
            types.Add(chip, 0, wx.RIGHT | wx.BOTTOM, tokens.scaled(5))
        self.right_sizer.Add(types, 0, wx.EXPAND | wx.BOTTOM, tokens.scaled(14))

        self.right_sizer.Add(
            _Caption(self.right_scroll, _text("Validation", "驗證")),
            0,
            wx.BOTTOM,
            tokens.scaled(tokens.SPACE_SM),
        )
        result = self.document.validate(tag)
        self.validation_note = _NoteBlock(
            self.right_scroll, result.message, severity=result.severity
        )
        self.right_sizer.Add(
            self.validation_note, 0, wx.EXPAND | wx.BOTTOM, tokens.scaled(14)
        )

        self.right_sizer.Add(
            _Caption(self.right_scroll, _text("Tag history", "標籤歷史")),
            0,
            wx.BOTTOM,
            tokens.scaled(tokens.SPACE_SM),
        )
        revisions = self.document.history(tag)
        self.history_rows: List[_HistoryRow] = []
        if not revisions:
            empty = wx.StaticText(
                self.right_scroll,
                label=_text(
                    "No revisions yet. The first edit records the value this tag "
                    "was opened with, so there is always something to go back to.",
                    "重未有版本。第一次改動會記低打開時嘅值，永遠有得返轉頭。",
                ),
            )
            empty.SetName("Tag history is empty")
            empty.SetForegroundColour(palette.on_surface_variant)
            empty.SetFont(tokens.font(self.right_scroll, widgets.point_size(11)))
            empty.Wrap(tokens.scaled(RIGHT_PANE_WIDTH - 40))
            self.right_sizer.Add(empty, 0, wx.EXPAND)
        for revision in revisions:
            row = _HistoryRow(self.right_scroll, revision, on_restore=self.restore)
            self.history_rows.append(row)
            self.right_sizer.Add(row, 0, wx.EXPAND | wx.BOTTOM, tokens.scaled(6))

        self.right_scroll.Layout()
        self.right_scroll.FitInside()
        self.right_pane.Layout()
        if focus_type is not None and focus_type in self.type_chips:
            self.type_chips[focus_type].SetFocus()
        elif focus_history and self.history_rows:
            self.history_rows[-1].button.SetFocus()

    def _focused_type(self) -> Optional[model.TagType]:
        """Return the type whose chip currently has the keyboard, if any."""
        focus = wx.Window.FindFocus()
        for tag_type, chip in getattr(self, "type_chips", {}).items():
            if chip is focus:
                return tag_type
        return None

    def _focus_is_in_history(self) -> bool:
        """Return whether a restore button currently has the keyboard."""
        focus = wx.Window.FindFocus()
        return any(row.button is focus for row in getattr(self, "history_rows", ()))

    def _inspector_rows(self, tag: model.Tag) -> List[Tuple[str, str]]:
        """Return the label and value pairs the inspector lists."""
        parent = tag.parent
        rows: List[Tuple[str, str]] = [
            (_text("Name", "名稱"), tag.display_name()),
            (_text("Type", "類型"), model.type_label(tag.tag_type)),
            (_text("Path", "路徑"), tag.path()),
            (_text("Value", "數值"), tag.value_text()),
        ]
        if tag.is_container:
            rows.append((_text("Subtree", "子樹"), f"{tag.count() - 1} tags"))
        rows.append(
            (
                _text("Inside", "喺邊"),
                (
                    parent.path()
                    if parent is not None
                    else _text("The document root", "文件根")
                ),
            )
        )
        rows.append((_text("Revisions", "版本"), str(len(self.document.history(tag)))))
        return rows

    def change_type(self, tag_type: model.TagType) -> None:
        """Retype the selected tag, saying first what the conversion costs."""
        self._flush_edits()
        tag = self.selected
        if tag_type is tag.tag_type:
            return
        report = model.retype_preview(tag, tag_type)
        if not report.ok:
            self._notify(
                _text("That conversion is refused", "呢個轉換做唔到"),
                report.message,
                severity="warning",
                details=f"Tag: {tag.path()}",
            )
            return
        if report.lossy and not self._confirm_discard(
            f"{report.message} {_text('Convert anyway?', '照轉？')}"
        ):
            return
        applied = self.document.retype(tag, tag_type)
        self.refresh_tree()
        self.rebuild_centre()
        self.rebuild_right(focus_type=tag_type)
        self.refresh_footer()
        self._notify(
            _text("Tag retyped", "標籤已轉類型"),
            applied.message,
            details=f"Tag: {tag.path()}",
        )

    def restore(self, revision: model.Revision) -> None:
        """Restore a revision, which appends a new one rather than rewinding."""
        self._flush_edits()
        tag = self.selected
        written = self.document.restore(tag, revision)
        self.refresh_tree()
        self.rebuild_centre()
        self.rebuild_right(focus_history=True)
        self.refresh_footer()
        self._notify(
            _text("Revision restored", "版本已還原"),
            f"{written.detail} Recorded as {written.label}, so the state you "
            "restored from is still in the history.",
            details=f"Tag: {tag.path()}",
        )

    # ------------------------------------------------------------------
    # footer actions
    # ------------------------------------------------------------------
    def refresh_footer(self) -> None:
        """Re-read the honest unsaved-work line."""
        self.dirty_text.SetLabel(self.document.dirty_text())
        self.footer.Layout()

    def set_mode(self, mode: str) -> None:
        """Switch between the form, the SNBT text, and the hex dump."""
        if mode not in {key for key, _english, _cantonese in MODES}:
            return
        self.mode = mode
        self.mode_switch.set_mode(mode)
        self.rebuild_centre()

    def copy_path(self) -> None:
        """Put the selected tag's path on the clipboard, and say whether it landed."""
        path = self.selected.path()
        if not wx.TheClipboard.Open():
            self._notify(
                _text("The clipboard is busy", "剪貼簿而家用緊"),
                _text(
                    "Another application is holding the clipboard, so nothing "
                    "was copied.",
                    "第個程式霸住剪貼簿，所以冇複製到。",
                ),
                severity="warning",
            )
            return
        try:
            wx.TheClipboard.SetData(wx.TextDataObject(path))
            wx.TheClipboard.Flush()
        finally:
            wx.TheClipboard.Close()
        self._notify(_text("Path copied", "路徑已複製"), path)

    def add_tag(self, parent_tag: Optional[model.Tag] = None) -> None:
        """Add a child tag to the selected container, or to its parent."""
        target = parent_tag or self.selected
        if not target.is_container:
            target = target.parent or self.document.root
        in_list = target.tag_type is model.TagType.LIST

        def submit(values: Dict[str, str]) -> model.ValidationResult:
            name = "" if in_list else values.get("name", "").strip()
            tag_type = model.type_for_label(values.get("type", "")) or model.TagType.INT
            if not in_list and not name:
                return model.ValidationResult(
                    False, "error", "A tag inside a compound needs a name."
                )
            if not in_list and any(child.name == name for child in target.children):
                return model.ValidationResult(
                    False,
                    "error",
                    f'"{target.display_name()}" already holds a tag named '
                    f'"{name}".',
                )
            if (
                in_list
                and target.children
                and (target.children[0].tag_type is not tag_type)
            ):
                return model.ValidationResult(
                    False,
                    "error",
                    f"This list holds {model.type_label(target.children[0].tag_type)}"
                    f" elements, so a {model.type_label(tag_type)} cannot join it.",
                )
            raw = values.get("value", "")
            kind = model.TYPE_INFO[tag_type].kind
            if kind == "integer":
                payload = model.coerce_integer(raw)
            elif kind == "float":
                payload = model.coerce_float(raw)
            elif kind == "array":
                payload = [
                    model.coerce_integer(part) for part in raw.replace(",", " ").split()
                ]
            elif kind == "string":
                payload = raw
            else:
                payload = None
            # The value is checked on a detached tag first: adding it and then
            # reporting that it was invalid would leave the document holding a
            # tag the reader was told had been refused.
            candidate = model.Tag(name, tag_type, payload)
            check = model.validate(candidate)
            if not check.ok:
                return check
            created = self.document.add_child(target, name, tag_type, payload)
            return model.ValidationResult(
                True,
                "ok",
                f"Added {model.type_label(created.tag_type)} {created.path()}.",
            )

        fields: List[Tuple[str, str, str, str]] = []
        if not in_list:
            fields.append(("name", _text("Name", "名稱"), "text", ""))
        fields.append(
            ("type", _text("Type", "類型"), "type", model.type_label(model.TagType.INT))
        )
        fields.append(("value", _text("Value", "數值"), "mono", "0"))
        dialog = _PromptDialog(
            self,
            _text("Add tag", "新增標籤"),
            _text(
                f"The new tag goes inside {target.path()}. A container is created "
                "empty; every other type takes the value below.",
                f"新標籤會加喺 {target.path()} 入面。容器會係空嘅，其他類型就用下面嘅值。",
            ),
            fields,
            confirm=_text("Add tag", "新增標籤"),
            on_submit=submit,
        )
        try:
            if dialog.ShowModal() == wx.ID_OK:
                self.expanded.add(target.uid)
                self.select_tag(target.children[-1] if target.children else target)
                self.refresh_footer()
        finally:
            dialog.Destroy()

    def rename_tag(self) -> None:
        """Rename the selected tag inside its compound."""
        self._flush_edits()
        tag = self.selected

        def submit(values: Dict[str, str]) -> model.ValidationResult:
            return self.document.rename(tag, values.get("name", ""))

        dialog = _PromptDialog(
            self,
            _text("Rename tag", "重新命名標籤"),
            _text(
                f"Renaming {tag.path()}. The name must be unused inside its "
                "compound.",
                f"改緊 {tag.path()} 個名，喺同一個 compound 入面唔可以撞名。",
            ),
            [("name", _text("Name", "名稱"), "text", tag.name)],
            confirm=_text("Rename", "重新命名"),
            on_submit=submit,
        )
        try:
            if dialog.ShowModal() == wx.ID_OK:
                self.refresh_tree()
                self.rebuild_centre()
                self.rebuild_right()
                self.refresh_footer()
        finally:
            dialog.Destroy()

    def duplicate_tag(self) -> None:
        """Copy the selected tag beside itself."""
        self._flush_edits()
        tag = self.selected
        copy_tag = self.document.duplicate(tag)
        if copy_tag is None:
            self._notify(
                _text("Nothing to duplicate", "冇嘢可以複製"),
                _text(
                    "The root tag has no parent to hold a copy. Select a tag "
                    "inside it first.",
                    "根標籤冇上層放副本，揀入面嘅標籤先。",
                ),
                severity="warning",
            )
            return
        self.select_tag(copy_tag)
        self.refresh_footer()
        self._notify(
            _text("Tag duplicated", "已複製標籤"),
            f"{tag.path()} was copied as {copy_tag.path()}.",
        )

    def delete_tag(self) -> None:
        """Delete the selected tag, through the two-key gate."""
        self._flush_edits()
        tag = self.selected
        if tag.parent is None:
            self._notify(
                _text("The root tag cannot be deleted", "根標籤刪唔到"),
                _text(
                    "Deleting the root would leave no document. Delete the tags "
                    "inside it instead.",
                    "刪咗根就冇文件，刪入面嘅標籤好過。",
                ),
                severity="warning",
            )
            return
        dialog = _DeleteGateDialog(self, tag)
        try:
            authorized = dialog.ShowModal() == wx.ID_OK and dialog.authorized
        finally:
            dialog.Destroy()
        if not authorized:
            self._notify(
                _text("Nothing was deleted", "冇刪任何嘢"),
                f"{tag.path()} is still in the document.",
            )
            return
        parent = tag.parent
        path = tag.path()
        if not self.document.delete(tag):
            self._notify(
                _text("The tag was not deleted", "標籤未刪到"),
                f"{path} could not be removed from {parent.path()}.",
                severity="error",
            )
            return
        self.expanded.discard(tag.uid)
        self.select_tag(parent)
        self.refresh_footer()
        self._notify(
            _text("Tag deleted", "標籤已刪"),
            f"{path} was removed. The deletion is on {parent.path()}'s history, "
            "so it can be restored from there.",
        )

    def import_snbt(self) -> None:
        """Read SNBT from a file and replace the selected tag with it."""
        self._flush_edits()
        with wx.FileDialog(
            self,
            _text("Import SNBT", "匯入 SNBT"),
            wildcard=(
                "SNBT text (*.snbt)|*.snbt|Text files (*.txt)|*.txt|"
                "All files (*.*)|*.*"
            ),
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            path = dialog.GetPath()
        try:
            with open(path, "r", encoding="utf-8") as handle:
                text = handle.read()
        except (OSError, UnicodeDecodeError) as error:
            self._notify(
                _text("Nothing was imported", "冇匯入到"),
                f"{path} could not be read as UTF-8 text.",
                severity="error",
                details=str(error),
            )
            return
        try:
            parsed = model.parse_snbt(text, name=self.selected.name)
        except model.SnbtError as error:
            self._notify(
                _text("That file is not valid SNBT", "呢個檔案唔係正確 SNBT"),
                str(error),
                severity="error",
                details=f"File: {path}",
            )
            return
        check = model.validate_tree(parsed)
        if not check.ok:
            self._notify(
                _text("Nothing was imported", "冇匯入到"),
                check.message,
                severity="error",
                details=f"File: {path}",
            )
            return
        self.document.replace(self.selected, parsed)
        self.expanded.add(self.selected.uid)
        self.refresh_tree()
        self.rebuild_centre()
        self.rebuild_right()
        self.refresh_footer()
        self._notify(
            _text("SNBT imported", "已匯入 SNBT"),
            f"{self.selected.path()} now holds {self.selected.count() - 1} "
            f"child tags read from the file.",
            details=f"File: {path}",
        )

    def export_snbt(self) -> None:
        """Validate the document, then write it out as SNBT."""
        self._flush_edits()
        check = self.document.validate_all()
        if not check.ok:
            self._notify(
                _text("Nothing was written", "冇寫任何嘢"),
                check.message,
                severity="error",
                details="Fix the tag it names, then export again.",
            )
            return
        default = f"{self.document.key}.snbt"
        with wx.FileDialog(
            self,
            _text("Export SNBT", "匯出 SNBT"),
            defaultFile=default,
            wildcard=(
                "SNBT text (*.snbt)|*.snbt|Text files (*.txt)|*.txt|"
                "All files (*.*)|*.*"
            ),
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        ) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            path = dialog.GetPath()
        text = self.document.snbt()
        try:
            with open(path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
                handle.write("\n")
        except OSError as error:
            self._notify(
                _text("Nothing was written", "冇寫任何嘢"),
                f"{path} could not be written.",
                severity="error",
                details=str(error),
            )
            return
        self._notify(
            _text("SNBT exported", "已匯出 SNBT"),
            f"{len(text)} characters written to {path}, UTF-8 with Unix line "
            "endings.",
        )

    def commit(self) -> None:
        """Validate everything, record the edits, and close.

        The window closes only when the document actually passed validation and
        the edits were recorded; a refusal leaves it open with the reason,
        because a window that closes on a failure has told the reader the work
        was saved.
        """
        self._flush_edits()
        check = self.document.validate_all()
        if not check.ok:
            self._notify(
                _text("Nothing was committed", "冇提交任何嘢"),
                check.message,
                severity="error",
                details="Fix the tag it names, then commit again.",
            )
            return
        edits = self.document.edit_count
        if not self.document.dirty or not edits:
            # A value typed and typed back leaves the document touched but with
            # no revision to hand on, and reporting "0 edits committed" would
            # claim work that does not exist.
            self._notify(
                _text("There was nothing to commit", "冇嘢需要提交"),
                _text(
                    "No tag ended up different, so the document is unchanged.",
                    "最後冇標籤改過，文件同原本一樣。",
                ),
            )
            self.close()
            return
        recorded = self._record_history(edits)
        self.document.mark_committed()
        self.refresh_footer()
        detail = (
            "The edits are in the local history and can be restored from there."
            if recorded
            else "The local history was unavailable, so no restore point was written."
        )
        counted = "1 edit" if edits == 1 else f"{edits} edits"
        self._notify(
            _text("Changes committed", "已提交更改"),
            f"{counted} to {self.document.source.label} committed. {detail}",
            severity="info" if recorded else "warning",
        )
        self.close()

    def _record_history(self, edits: int) -> bool:
        """Record the commit in the project's local history, honestly."""
        try:
            from amulet_map_editor.api import local_history
        except ImportError:  # pragma: no cover - packaging boundary
            log.debug("Local history is unavailable in this build")
            return False
        try:
            event = local_history.safe_record(
                f"nbt.{self.document.key}",
                {
                    "source": self.document.key,
                    "edits": edits,
                    "tags": self.document.tag_count(),
                    "snbt": self.document.snbt(),
                },
                record_type="nbt-document",
            )
        except Exception:
            log.exception("Could not record the NBT commit in the local history")
            return False
        return event is not None

    def cancel(self) -> None:
        """Close without committing, confirming first when there are edits."""
        self._flush_edits()
        if self.document.dirty and not self._confirm_discard(
            _text(
                "Closing now discards the edits that have not been committed. "
                "Close anyway?",
                "而家閂窗會掉咗未提交嘅改動。照閂？",
            )
        ):
            return
        self.close()

    # ------------------------------------------------------------------
    # window plumbing
    # ------------------------------------------------------------------
    def _notify(
        self,
        title: str,
        body: str,
        *,
        severity: str = "info",
        details: str = "",
    ) -> None:
        """Report a result without blocking the window."""
        try:
            from amulet_map_editor.api.wx import nonblocking
        except ImportError:  # pragma: no cover - packaging boundary
            log.info("%s: %s", title, body)
            return
        nonblocking.notify(self, title, body, severity=severity, details=details)

    def _confirm_discard(self, message: str) -> bool:
        """Ask a genuine yes-or-no question, defaulting to keeping the work."""
        try:
            from amulet_map_editor.api.wx.ui import confirm
        except ImportError:  # pragma: no cover - packaging boundary
            return False
        answer = confirm.show_material_confirmation(
            self,
            message,
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_EXCLAMATION,
            _text("Unsaved edits", "未提交嘅改動"),
        )
        return answer in (wx.ID_YES, wx.YES)

    def close(self) -> None:
        """Close the window and hand the keyboard back to whatever opened it."""
        self._return_focus()
        self.Close()

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
        except RuntimeError:
            pass

    def _on_char_hook(self, event: wx.KeyEvent) -> None:
        code = event.GetKeyCode()
        if code == wx.WXK_ESCAPE:
            self.cancel()
            return
        event.Skip()

    def _on_close(self, event: wx.CloseEvent) -> None:
        self._flush_edits()
        self._return_focus()
        event.Skip()

    def _on_destroy(self, event: wx.WindowDestroyEvent) -> None:
        if event.GetEventObject() is self and self._theme_unsubscribe is not None:
            self._theme_unsubscribe()
            self._theme_unsubscribe = None
        event.Skip()

    def refresh_theme(self) -> None:
        """Re-read the tokens and repaint every pane."""
        try:
            if self.IsBeingDeleted():
                return
            palette = tokens.palette()
            self.SetBackgroundColour(palette.surface)
            self.title_text.SetForegroundColour(palette.on_surface)
            self.title_text.SetFont(tokens.font(self, widgets.point_size(18)))
            self.dirty_text.SetForegroundColour(palette.on_surface_variant)
            self.dirty_text.SetFont(tokens.font(self, widgets.point_size(12)))
            self.centre_pane.SetBackgroundColour(palette.surface)
            self.tree_scroll.SetBackgroundColour(palette.surface_container)
            self.right_scroll.SetBackgroundColour(palette.surface_container)
            for strip in (self.header, self.left_pane, self.right_pane, self.footer):
                strip.refresh_theme()
            for pane in (self.centre_pane, self.right_scroll, self.tree_scroll):
                for child in pane.GetChildren():
                    refresh = getattr(child, "refresh_theme", None)
                    if callable(refresh):
                        refresh()
            self.Refresh()
        except RuntimeError:
            self._theme_unsubscribe = None


def open_nbt_studio(
    parent: wx.Window, source: str = model.DEFAULT_SOURCE
) -> NbtStudioDialog:
    """Open the NBT editor non-modally, reusing an already-open window.

    Several Studio surfaces open it at once -- a block inspector, an entity
    browser, a chunk report -- and stacking a second copy on top of the first
    would leave two windows editing two different documents with no sign of
    which one the reader was looking at.
    """
    from amulet_map_editor.api.wx.modeless import show_modeless_dialog

    return show_modeless_dialog(
        parent,
        "studio.nbt",
        lambda owner: NbtStudioDialog(owner, source=source),
    )


__all__ = [
    "DIALOG_HEIGHT",
    "DIALOG_WIDTH",
    "LABEL_COLUMN",
    "LEFT_PANE_WIDTH",
    "MODES",
    "RIGHT_PANE_WIDTH",
    "TREE_ROW_HEIGHT",
    "NbtStudioDialog",
    "open_nbt_studio",
]
