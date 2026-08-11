"""Material drop-ins for the native wx controls a settings surface still uses.

The Studio has owner-drawn widgets for most of what an interface needs, but a
settings dialog written against ``wx`` talks to its controls in ``wx``'s own
words: ``GetValue``, ``SetSelection``, ``GetStringSelection``, ``Set``, and a
handler bound to ``wx.EVT_TEXT`` or ``wx.EVT_CHOICE``.  Every widget here keeps
that vocabulary and changes only what is drawn, so converting a surface is a
constructor swap rather than a rewrite of everything that talks to it
afterwards -- which is the difference between a migration and a regression.

Three properties are load-bearing and are the reason these exist rather than a
sprinkling of ``apply_material3`` calls over native controls:

*Every widget paints itself through* :meth:`render_to`.  A native control on a
desktop nobody is looking at photographs as an empty rectangle -- the outline
of a field with no text in it, a slider with no track, a label that is simply
absent -- so a capture of a native surface reports success over a picture of
nothing.  A widget that draws through ``render_to`` photographs identically
whether or not a compositor exists.

*Every widget is keyboard-operable and names itself.*  A painted control gets
none of that for free.  Arrow keys, Home/End, Page Up/Down, a visible focus
ring, and an accessible name that carries the current value -- the convention
the Studio already uses, ``"Theme: Dark"``, ``"Value 3"`` -- are written out
here rather than assumed.

*Text entry keeps a real* ``wx.TextCtrl`` *inside a painted outline.*  This is
deliberate and is the one place a native window survives.  Caret movement,
selection, the clipboard, IME composition, and screen-reader text review are
the platform's own; a hand-drawn entry would have to reimplement all of it and
would get it subtly wrong.  The visible chrome -- the outline, the notched
floating label, the focus colour -- is painted, so the control reads as
Material while behaving as the platform's own text box.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import wx

from amulet_map_editor.api.studio import tokens
from amulet_map_editor.api.studio import widgets
from amulet_map_editor.api.studio.search import SearchState
from amulet_map_editor.api.studio.widgets import (
    AnchoredPopup,
    SearchBar,
    StudioText,
    _Interactive,
    _Themed,
    draw_focus_ring,
    elide,
    invoke,
    measuring,
    point_size,
)

_MEDIUM = (
    wx.FONTWEIGHT_MEDIUM if hasattr(wx, "FONTWEIGHT_MEDIUM") else wx.FONTWEIGHT_BOLD
)

#: Slack added around measured text, matching the Studio's own widgets.  A
#: string measured to the pixel and then drawn into exactly that many pixels
#: loses its last glyph on some faces.
TEXT_SLACK = 3


def emit(window: wx.Window, binder: wx.PyEventBinder, *, string: str = "") -> None:
    """Post ``binder``'s command event from ``window``, as a native control would.

    A surface that already binds ``wx.EVT_TEXT`` or ``wx.EVT_CHOICE`` keeps
    working when its control is replaced only if the replacement raises the
    same event.  Anything less makes the swap a silent behaviour change: the
    control looks right, the handler never runs, and nothing reports it.
    """
    command = wx.CommandEvent(binder.typeId, window.GetId())
    command.SetEventObject(window)
    if string:
        command.SetString(string)
    window.GetEventHandler().ProcessEvent(command)


# ----------------------------------------------------------------------------
# text entry
# ----------------------------------------------------------------------------


class MaterialTextField(wx.Panel, _Themed):
    """An M3 outlined text field that answers to the ``wx.TextCtrl`` API.

    The outline and its notched floating label are painted; the entry inside is
    a real ``wx.TextCtrl`` so the caret, the selection, the clipboard, and a
    screen reader's text review are the platform's own.  Because a command
    event raised by a child does not identify the panel, ``wx.EVT_TEXT`` and
    ``wx.EVT_TEXT_ENTER`` are re-raised from the panel itself, so a caller may
    bind to either the field or the control inside it.
    """

    #: Room above the box for the floating label, which is centred on the
    #: box's top edge, so half of it has to fit above that edge.
    LABEL_TOP = 9
    BOX_HEIGHT = 46
    TEXT_PADDING = 14
    WIDTH = 200
    MAX_WIDTH = 460

    def __init__(
        self,
        parent: wx.Window,
        label: str = "",
        value: str = "",
        *,
        placeholder: str = "",
        password: bool = False,
        process_enter: bool = False,
        multiline: bool = False,
        mono: bool = False,
        name: str = "",
        on_change: Optional[Callable[[str], None]] = None,
    ) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self.label = str(label)
        self.on_change = on_change
        self._mono = bool(mono)
        self._multiline = bool(multiline)
        self._focused = False
        self._install(name or self.label or "Field", listen=False)
        style = wx.BORDER_NONE
        if password:
            style |= wx.TE_PASSWORD
        if process_enter:
            style |= wx.TE_PROCESS_ENTER
        if multiline:
            style |= wx.TE_MULTILINE
        self.text = wx.TextCtrl(
            self, value=str(value), style=style, name=name or self.label or "Field"
        )
        if placeholder:
            self.text.SetHint(str(placeholder))
        self._apply_theme(self.palette())
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.Bind(wx.EVT_SIZE, self._on_size)
        self.text.Bind(wx.EVT_TEXT, self._on_text)
        if process_enter:
            # wx asserts on binding this without the style, so the binding
            # follows the style rather than being attached unconditionally.
            self.text.Bind(wx.EVT_TEXT_ENTER, self._on_enter)
        self.text.Bind(wx.EVT_SET_FOCUS, self._on_focus_change)
        self.text.Bind(wx.EVT_KILL_FOCUS, self._on_focus_change)
        self.SetInitialSize(self.DoGetBestSize())

    # -- geometry ------------------------------------------------------------
    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        height = tokens.scaled(self.LABEL_TOP) + tokens.scaled(self.BOX_HEIGHT)
        if self._multiline:
            height = tokens.scaled(self.LABEL_TOP) + tokens.scaled(self.BOX_HEIGHT * 2)
        with measuring(self) as dc:
            dc.SetFont(tokens.font(self, point_size(11)))
            label_width = dc.GetTextExtent(self.label or " ")[0]
        width = min(
            tokens.scaled(self.MAX_WIDTH),
            max(
                tokens.scaled(self.WIDTH),
                label_width + tokens.scaled(30) + TEXT_SLACK * 2,
            ),
        )
        return wx.Size(width, height)

    def _box_rect(self, width: int, height: int) -> wx.Rect:
        top = tokens.scaled(self.LABEL_TOP)
        return wx.Rect(0, top, max(0, width), max(0, height - top))

    def _on_size(self, event: wx.SizeEvent) -> None:
        width, height = self.GetClientSize()
        box = self._box_rect(width, height)
        padding = tokens.scaled(self.TEXT_PADDING)
        if self._multiline:
            self.text.SetSize(
                padding,
                box.y + tokens.scaled(8),
                max(0, box.width - padding * 2),
                max(0, box.height - tokens.scaled(16)),
            )
        else:
            # The entry is held inside the outline rather than given its own
            # best height. A native single-line text control asks for a good
            # deal more than its text needs -- 40 pixels for a 13px font on
            # this platform -- and a control that tall, centred in a 46-pixel
            # box, reaches up over the floating label and repaints its lower
            # half in the entry's own fill. The label then reads as though its
            # descenders had been shaved off, which looks like a font problem
            # and is a layout one.
            inset = tokens.scaled(9)
            available = max(1, box.height - inset * 2)
            text_height = min(self.text.GetBestSize().height, available)
            self.text.SetSize(
                padding,
                box.y + inset + max(0, (available - text_height) // 2),
                max(0, box.width - padding * 2),
                text_height,
            )
        self.Refresh()
        event.Skip()

    # -- the wx.TextCtrl vocabulary -----------------------------------------
    def GetValue(self) -> str:  # noqa: N802 - wx API spelling
        """Return the current text."""
        return self.text.GetValue()

    def SetValue(self, value: str) -> None:  # noqa: N802 - wx API spelling
        """Replace the text and report it, exactly as ``wx.TextCtrl`` does."""
        self.text.SetValue(str(value))
        self.Refresh()

    def ChangeValue(self, value: str) -> None:  # noqa: N802 - wx API spelling
        """Replace the text without raising ``wx.EVT_TEXT``."""
        self.text.ChangeValue(str(value))
        self.Refresh()

    def SetHint(self, hint: str) -> bool:  # noqa: N802 - wx API spelling
        """Set the placeholder shown while the field is empty."""
        result = self.text.SetHint(str(hint))
        self.InvalidateBestSize()
        return result

    def GetHint(self) -> str:  # noqa: N802 - wx API spelling
        return self.text.GetHint()

    def SetMaxLength(self, length: int) -> None:  # noqa: N802 - wx API spelling
        self.text.SetMaxLength(int(length))

    def SetEditable(self, editable: bool) -> None:  # noqa: N802 - wx API spelling
        self.text.SetEditable(bool(editable))

    def IsEditable(self) -> bool:  # noqa: N802 - wx API spelling
        return self.text.IsEditable()

    def SetInsertionPointEnd(self) -> None:  # noqa: N802 - wx API spelling
        self.text.SetInsertionPointEnd()

    def SelectAll(self) -> None:  # noqa: N802 - wx API spelling
        self.text.SelectAll()

    def Clear(self) -> None:  # noqa: N802 - wx API spelling
        self.text.Clear()

    def AppendText(self, value: str) -> None:  # noqa: N802 - wx API spelling
        self.text.AppendText(str(value))

    def SetFocus(self) -> None:  # noqa: N802 - wx API spelling
        """Put the caret in the entry, not on the panel around it."""
        self.text.SetFocus()

    def SetName(self, name: str) -> None:  # noqa: N802 - wx API spelling
        """Name the panel and the entry together.

        A screen reader lands on the entry, so naming only the panel leaves the
        control the user actually reaches announcing nothing.
        """
        super().SetName(name)
        text = getattr(self, "text", None)
        if text is not None:
            text.SetName(name)

    def SetToolTip(self, tip: Any) -> None:  # noqa: N802 - wx API spelling
        super().SetToolTip(tip)
        text = getattr(self, "text", None)
        if text is not None:
            text.SetToolTip(tip)

    def Enable(self, enable: bool = True) -> bool:  # noqa: N802 - wx API spelling
        result = super().Enable(enable)
        text = getattr(self, "text", None)
        if text is not None:
            text.Enable(enable)
        self.Refresh()
        return result

    # -- events --------------------------------------------------------------
    def _on_text(self, event: wx.CommandEvent) -> None:
        invoke(self.on_change, self.text.GetValue())
        emit(self, wx.EVT_TEXT, string=self.text.GetValue())
        event.Skip()

    def _on_enter(self, event: wx.CommandEvent) -> None:
        emit(self, wx.EVT_TEXT_ENTER, string=self.text.GetValue())
        event.Skip()

    def _on_focus_change(self, event: wx.FocusEvent) -> None:
        self._focused = event.GetEventType() == wx.EVT_SET_FOCUS.typeId
        self.Refresh()
        event.Skip()

    # -- painting ------------------------------------------------------------
    def _apply_theme(self, palette: tokens.StudioPalette) -> None:
        parent = self.GetParent()
        backdrop = parent.GetBackgroundColour() if parent else palette.surface
        self.SetBackgroundColour(backdrop if backdrop.IsOk() else palette.surface)
        text = getattr(self, "text", None)
        if text is not None:
            text.SetBackgroundColour(self.GetBackgroundColour())
            text.SetForegroundColour(
                palette.on_surface
                if self.IsEnabled()
                else tokens.blend(palette.on_surface_variant, palette.surface, 0.45)
            )
            text.SetFont(tokens.font(self, point_size(13), mono=self._mono))

    def _backdrop(self) -> wx.Colour:
        return self.GetBackgroundColour()

    def render_to(self, dc: wx.DC, rect: wx.Rect) -> None:
        """Draw the outlined box and the label notched into its top edge."""
        palette = self.palette()
        with self._painting(dc, rect) as rect:
            box = self._box_rect(rect.width, rect.height)
            if not self.IsEnabled():
                border = palette.outline_variant
            elif self._focused:
                border = palette.primary
            else:
                border = palette.outline
            tokens.draw_round_rect(
                dc,
                box,
                tokens.scaled(4),
                None,
                border,
                border_width=2 if self._focused else 1,
            )
            if not self.label:
                return
            dc.SetFont(tokens.font(self, point_size(11)))
            label = elide(dc, self.label, max(0, box.width - tokens.scaled(30)))
            widgets.note_elision(self, self.label, label)
            label_width, label_height = dc.GetTextExtent(label)
            # The label straddles the outline: its centre sits on the border,
            # which is what makes the notch read as a gap cut into the box
            # rather than as a caption resting on top of it. Drawing it at the
            # top of the control instead left the descenders under the border
            # line, so every label with a "p" or a "y" in it looked shaved.
            notch = wx.Rect(
                tokens.scaled(11),
                max(0, box.y - label_height // 2),
                label_width + tokens.scaled(8),
                label_height,
            )
            dc.SetBrush(wx.Brush(self.GetBackgroundColour()))
            dc.SetPen(wx.TRANSPARENT_PEN)
            dc.DrawRectangle(notch)
            dc.SetTextForeground(
                palette.primary if self._focused else palette.on_surface_variant
            )
            dc.DrawText(label, notch.x + tokens.scaled(4), notch.y)


# ----------------------------------------------------------------------------
# dropdowns
# ----------------------------------------------------------------------------


class MaterialChoice(widgets.SearchableChoice):
    """The Studio's searchable combo, answering to the ``wx.Choice`` API.

    ``wx.Choice`` addresses its options by index and has a real "nothing is
    selected" state (``wx.NOT_FOUND``); :class:`~amulet_map_editor.api.studio.
    widgets.SearchableChoice` addresses them by value and always has one.  The
    index is therefore tracked here rather than derived from the value, because
    deriving it would quietly turn an empty selection into the first option --
    which is how a preset list with nothing chosen comes to load a preset
    nobody picked.

    Every dropdown gets the search field and the regex builder its parent class
    already provides, which is what the project asks of every dropdown rather
    than only the long ones.
    """

    #: Class level, because the base constructor reaches ``SetName`` -- and so
    #: this class's override, and the name it builds from the selection -- long
    #: before ``__init__`` below has bound either attribute.  An
    #: ``AttributeError`` raised there surfaces as a control that cannot be
    #: constructed at all, which is a hard failure two frames from its cause.
    _selection: int = wx.NOT_FOUND
    _accessible_stem: str = "Choice"

    def __init__(
        self,
        parent: wx.Window,
        choices: Sequence[str] = (),
        *,
        label: str = "",
        name: str = "",
        value: str = "",
    ) -> None:
        options = [str(choice) for choice in choices]
        super().__init__(parent, label or name or "Choice", options, value)
        self._selection = (
            options.index(self.value) if self.value in options else wx.NOT_FOUND
        )
        self._accessible_stem = name or label or "Choice"
        self._sync_name()

    # -- naming --------------------------------------------------------------
    def _sync_name(self) -> None:
        """Carry the current value in the accessible name, as the Studio does."""
        chosen = self.GetStringSelection() or "nothing selected"
        wx.Panel.SetName(self, f"{self._accessible_stem}: {chosen}")

    def SetName(self, name: str) -> None:  # noqa: N802 - wx API spelling
        """Rename the control, keeping the value suffix a screen reader reads."""
        self._accessible_stem = str(name)
        self._sync_name()

    # -- the wx.Choice vocabulary -------------------------------------------
    def Set(self, choices: Sequence[str]) -> None:  # noqa: N802 - wx API spelling
        """Replace every option, clearing the selection as ``wx.Choice`` does."""
        self.set_options([str(choice) for choice in choices])
        self._selection = wx.NOT_FOUND
        self.value = ""
        self._sync_name()
        self.Refresh()

    def Append(self, choice: str) -> int:  # noqa: N802 - wx API spelling
        self.set_options([*self.options, str(choice)])
        return len(self.options) - 1

    def Clear(self) -> None:  # noqa: N802 - wx API spelling
        self.Set([])

    def GetCount(self) -> int:  # noqa: N802 - wx API spelling
        return len(self.options)

    def GetString(self, index: int) -> str:  # noqa: N802 - wx API spelling
        return self.options[index] if 0 <= index < len(self.options) else ""

    def GetStrings(self) -> List[str]:  # noqa: N802 - wx API spelling
        return list(self.options)

    def FindString(self, text: str) -> int:  # noqa: N802 - wx API spelling
        try:
            return self.options.index(str(text))
        except ValueError:
            return wx.NOT_FOUND

    def GetSelection(self) -> int:  # noqa: N802 - wx API spelling
        return self._selection

    def SetSelection(self, index: int) -> None:  # noqa: N802 - wx API spelling
        """Select by index without reporting it, as ``wx.Choice`` does."""
        if 0 <= int(index) < len(self.options):
            self._selection = int(index)
            self.value = self.options[self._selection]
        else:
            self._selection = wx.NOT_FOUND
            self.value = ""
        self._sync_name()
        self.Refresh()

    def GetStringSelection(self) -> str:  # noqa: N802 - wx API spelling
        return (
            self.options[self._selection]
            if 0 <= self._selection < len(self.options)
            else ""
        )

    def SetStringSelection(self, text: str) -> bool:  # noqa: N802 - wx API spelling
        index = self.FindString(text)
        self.SetSelection(index)
        return index != wx.NOT_FOUND

    # -- selection from the popup -------------------------------------------
    def set_value(self, value: str, *, notify: bool = False) -> None:
        """Choose an option, keeping the index and the name in step with it."""
        text = str(value)
        try:
            self._selection = self.options.index(text)
        except ValueError:
            self._selection = wx.NOT_FOUND
        self.value = text
        self._sync_name()
        self.Refresh()
        if notify:
            invoke(self.on_change, self.value)
            emit(self, wx.EVT_CHOICE, string=self.value)


# ----------------------------------------------------------------------------
# sliders
# ----------------------------------------------------------------------------


class MaterialSlider(wx.Control, _Interactive):
    """A painted M3 slider answering to the ``wx.Slider`` API.

    ``wx.Slider`` is drawn by the platform, which means two things this surface
    cannot accept: it looks like the operating system rather than like the rest
    of the product, and it photographs as nothing at all on a desktop with no
    compositor -- the funny-level and UI-scale rows came back as empty space.

    Everything the native control gave for free is written out here rather than
    assumed: arrow keys move by one, Page Up and Page Down by a tenth of the
    range, Home and End go to the ends, the track is draggable, focus is
    visible, and the accessible name carries the value and the range so a
    screen reader announces ``"UI scale: 100 of 80 to 200"`` rather than a
    control with a name and no reading.
    """

    TRACK = 6
    KNOB = 18
    HEIGHT = 34
    LABEL_GAP = 6

    def __init__(
        self,
        parent: wx.Window,
        *,
        value: int = 0,
        minValue: int = 0,  # noqa: N803 - the wx.Slider keyword spelling
        maxValue: int = 100,  # noqa: N803 - the wx.Slider keyword spelling
        name: str = "",
        show_labels: bool = True,
        suffix: str = "",
        on_change: Optional[Callable[[int], None]] = None,
    ) -> None:
        super().__init__(parent, style=wx.BORDER_NONE | wx.WANTS_CHARS)
        self.minimum = int(min(minValue, maxValue))
        self.maximum = int(max(minValue, maxValue))
        self.suffix = str(suffix)
        self.show_labels = bool(show_labels)
        self.on_change = on_change
        self._value = self._clamp(value)
        self._dragging = False
        self._stem = name or "Slider"
        self._install(self._stem, listen=False)
        self._bind_interaction()
        self.Bind(wx.EVT_MOTION, self._on_motion)
        self.Bind(wx.EVT_MOUSE_CAPTURE_LOST, self._on_capture_lost)
        self._sync_name()
        self.SetInitialSize(self.DoGetBestSize())

    # -- geometry ------------------------------------------------------------
    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        height = tokens.scaled(self.HEIGHT)
        if self.show_labels:
            with measuring(self) as dc:
                dc.SetFont(tokens.font(self, point_size(11)))
                height += dc.GetCharHeight() + tokens.scaled(self.LABEL_GAP)
        return wx.Size(tokens.scaled(180), height)

    def _track_rect(self, rect: wx.Rect) -> wx.Rect:
        knob = tokens.scaled(self.KNOB)
        track = tokens.scaled(self.TRACK)
        top = (tokens.scaled(self.HEIGHT) - track) // 2
        return wx.Rect(knob // 2, top, max(1, rect.width - knob), track)

    def _fraction(self) -> float:
        span = self.maximum - self.minimum
        return 0.0 if span <= 0 else (self._value - self.minimum) / span

    def _value_at(self, x: int) -> int:
        rect = wx.Rect(0, 0, *self.GetClientSize())
        track = self._track_rect(rect)
        if track.width <= 0:
            return self._value
        fraction = min(1.0, max(0.0, (x - track.x) / track.width))
        return self._clamp(
            round(self.minimum + fraction * (self.maximum - self.minimum))
        )

    def _clamp(self, value: Any) -> int:
        try:
            number = int(round(float(value)))
        except (TypeError, ValueError):
            number = self.minimum
        return max(self.minimum, min(self.maximum, number))

    # -- the wx.Slider vocabulary -------------------------------------------
    def GetValue(self) -> int:  # noqa: N802 - wx API spelling
        return self._value

    def SetValue(self, value: int) -> None:  # noqa: N802 - wx API spelling
        """Move the slider without reporting it, as ``wx.Slider`` does."""
        self.set_value(value, notify=False)

    def GetMin(self) -> int:  # noqa: N802 - wx API spelling
        return self.minimum

    def GetMax(self) -> int:  # noqa: N802 - wx API spelling
        return self.maximum

    def SetRange(self, minimum: int, maximum: int) -> None:  # noqa: N802
        self.minimum = int(min(minimum, maximum))
        self.maximum = int(max(minimum, maximum))
        self.set_value(self._value, notify=False)

    def set_value(self, value: Any, *, notify: bool = True) -> None:
        """Set the value, reporting it only when it actually moved."""
        previous = self._value
        self._value = self._clamp(value)
        self._sync_name()
        self.Refresh()
        if notify and previous != self._value:
            invoke(self.on_change, self._value)
            emit(self, wx.EVT_SLIDER)

    def _sync_name(self) -> None:
        reading = f"{self._value}{self.suffix}"
        wx.Control.SetName(
            self, f"{self._stem}: {reading} of {self.minimum} to {self.maximum}"
        )

    def SetName(self, name: str) -> None:  # noqa: N802 - wx API spelling
        self._stem = str(name)
        self._sync_name()

    # -- behaviour -----------------------------------------------------------
    def activate(self) -> None:
        """Enter and Space are not a movement, so they commit nothing."""
        return None

    def _step(self) -> int:
        return max(1, round((self.maximum - self.minimum) / 10))

    def _on_key_down(self, event: wx.KeyEvent) -> None:
        if not self.IsEnabled():
            event.Skip()
            return
        code = event.GetKeyCode()
        if code in (wx.WXK_LEFT, wx.WXK_DOWN):
            self.set_value(self._value - 1)
        elif code in (wx.WXK_RIGHT, wx.WXK_UP):
            self.set_value(self._value + 1)
        elif code == wx.WXK_PAGEDOWN:
            self.set_value(self._value - self._step())
        elif code == wx.WXK_PAGEUP:
            self.set_value(self._value + self._step())
        elif code == wx.WXK_HOME:
            self.set_value(self.minimum)
        elif code == wx.WXK_END:
            self.set_value(self.maximum)
        else:
            event.Skip()

    def _on_left_down(self, event: wx.MouseEvent) -> None:
        if self.IsEnabled():
            self.SetFocus()
            self._pressed = True
            self._dragging = True
            if not self.HasCapture():
                self.CaptureMouse()
            self.set_value(self._value_at(event.GetPosition().x))
        event.Skip()

    def _on_left_up(self, event: wx.MouseEvent) -> None:
        self._pressed = False
        self._dragging = False
        if self.HasCapture():
            self.ReleaseMouse()
        self.Refresh()
        event.Skip()

    def _on_motion(self, event: wx.MouseEvent) -> None:
        if self._dragging and event.LeftIsDown() and self.IsEnabled():
            self.set_value(self._value_at(event.GetPosition().x))
        event.Skip()

    def _on_capture_lost(self, _event: wx.MouseCaptureLostEvent) -> None:
        self._dragging = False
        self._pressed = False
        self.Refresh()

    # -- painting ------------------------------------------------------------
    def render_to(self, dc: wx.DC, rect: wx.Rect) -> None:
        """Draw the track, its filled portion, the knob, and the end labels."""
        palette = self.palette()
        with self._painting(dc, rect) as rect:
            enabled = self.IsEnabled()
            track = self._track_rect(rect)
            rest = (
                palette.surface_container_high if enabled else palette.outline_variant
            )
            active = palette.primary if enabled else palette.outline
            tokens.draw_round_rect(dc, track, track.height // 2, rest)
            filled = int(track.width * self._fraction())
            if filled > 0:
                tokens.draw_round_rect(
                    dc,
                    wx.Rect(track.x, track.y, filled, track.height),
                    track.height // 2,
                    active,
                )
            knob = tokens.scaled(self.KNOB)
            centre_x = track.x + filled
            centre_y = track.y + track.height // 2
            knob_rect = wx.Rect(centre_x - knob // 2, centre_y - knob // 2, knob, knob)
            dc.SetBrush(wx.Brush(active))
            dc.SetPen(wx.Pen(palette.surface, max(1, tokens.scaled(2))))
            dc.DrawEllipse(knob_rect)
            dc.SetPen(wx.NullPen)
            if self.HasFocus():
                draw_focus_ring(
                    dc, knob_rect.Inflate(tokens.scaled(4)), knob, palette.primary
                )
            if not self.show_labels:
                return
            baseline = tokens.scaled(self.HEIGHT) + tokens.scaled(self.LABEL_GAP) // 2
            # The live reading is placed first and the two end labels are drawn
            # only where they would not touch it. At either end of the travel
            # the reading sits on top of the end label it has reached, and the
            # two overlapped into an unreadable smear -- a slider at maximum
            # read "55" for a value of 5 on a scale ending at 5.
            dc.SetFont(tokens.mono_font(self, point_size(12), _MEDIUM))
            dc.SetTextForeground(palette.primary if enabled else palette.outline)
            reading = f"{self._value}{self.suffix}"
            reading_width = dc.GetTextExtent(reading)[0]
            reading_x = max(
                0, min(rect.width - reading_width, centre_x - reading_width // 2)
            )
            dc.DrawText(reading, reading_x, baseline)
            gap = tokens.scaled(8)
            dc.SetFont(tokens.font(self, point_size(11)))
            dc.SetTextForeground(palette.on_surface_variant)
            low = f"{self.minimum}{self.suffix}"
            high = f"{self.maximum}{self.suffix}"
            if reading_x > dc.GetTextExtent(low)[0] + gap:
                dc.DrawText(low, 0, baseline)
            high_x = rect.width - dc.GetTextExtent(high)[0]
            if reading_x + reading_width + gap < high_x:
                dc.DrawText(high, high_x, baseline)


# ----------------------------------------------------------------------------
# numeric entry
# ----------------------------------------------------------------------------


class MaterialSpin(widgets.Stepper):
    """The Studio's stepper, answering to the ``wx.SpinCtrl`` API."""

    #: Class level for the same reason :class:`MaterialChoice`'s are: the base
    #: constructor names the control before this one has run.
    _stem: str = "Number"

    def __init__(
        self,
        parent: wx.Window,
        *,
        min: int = 0,  # noqa: A002 - the wx.SpinCtrl keyword spelling
        max: int = 100,  # noqa: A002 - the wx.SpinCtrl keyword spelling
        initial: int = 0,
        name: str = "",
        suffix: str = "",
    ) -> None:
        super().__init__(parent, initial, min, max, suffix=suffix)
        self._stem = name or "Number"
        self._sync_name()

    def _sync_name(self) -> None:
        if not hasattr(self, "value"):
            # Reached from the base constructor, before there is a value to
            # report; the name is rebuilt at the end of ``__init__``.
            return
        wx.Control.SetName(
            self,
            f"{self._stem}: {widgets.format_number(self.value)} "
            f"of {widgets.format_number(self.minimum)} "
            f"to {widgets.format_number(self.maximum)}",
        )

    def SetName(self, name: str) -> None:  # noqa: N802 - wx API spelling
        self._stem = str(name)
        self._sync_name()

    def GetValue(self) -> int:  # noqa: N802 - wx API spelling
        return int(round(self.value))

    def SetValue(self, value: int) -> None:  # noqa: N802 - wx API spelling
        """Set the number without reporting it, as ``wx.SpinCtrl`` does."""
        self.set_value(value, notify=False)
        self._sync_name()

    def GetMin(self) -> int:  # noqa: N802 - wx API spelling
        return int(self.minimum)

    def GetMax(self) -> int:  # noqa: N802 - wx API spelling
        return int(self.maximum)

    def SetRange(self, minimum: int, maximum: int) -> None:  # noqa: N802
        # ``min`` and ``max`` are shadowed only in ``__init__``'s signature,
        # where the wx keyword spelling forces it; here they are the builtins.
        self.minimum = float(min(minimum, maximum))
        self.maximum = float(max(minimum, maximum))
        self.set_value(self.value, notify=False)

    def set_value(self, value: float, *, notify: bool = True) -> None:
        """Apply the value and raise the events ``wx.SpinCtrl`` would raise."""
        previous = self.value
        super().set_value(value, notify=notify)
        self._sync_name()
        if notify and previous != self.value:
            emit(self, wx.EVT_SPINCTRL)
            emit(self, wx.EVT_TEXT, string=widgets.format_number(self.value))


# ----------------------------------------------------------------------------
# lists
# ----------------------------------------------------------------------------


class MaterialListBox(wx.Control, _Interactive):
    """A painted single-selection list answering to the ``wx.ListBox`` API.

    Rows are drawn rather than owned by the platform, so the list matches the
    rest of the surface and photographs with its content in it.  Keyboard
    behaviour is written out for the same reason the slider's is: arrow keys,
    Home, End, and Page Up/Down move the selection, and every move raises
    ``wx.EVT_LISTBOX`` exactly as choosing a row with the mouse does.
    """

    ROW_HEIGHT = 30
    PADDING = 8

    def __init__(
        self,
        parent: wx.Window,
        choices: Sequence[str] = (),
        *,
        name: str = "",
        on_change: Optional[Callable[[int], None]] = None,
    ) -> None:
        super().__init__(parent, style=wx.BORDER_NONE | wx.WANTS_CHARS)
        self._items: List[str] = [str(choice) for choice in choices]
        self._selection = wx.NOT_FOUND
        self._top = 0
        self._stem = name or "List"
        self.on_change = on_change
        self._install(self._stem, listen=False)
        self._bind_interaction()
        self.Bind(wx.EVT_MOUSEWHEEL, self._on_wheel)
        self.Bind(wx.EVT_LEFT_DCLICK, self._on_double_click)
        self._sync_name()
        self.SetInitialSize(wx.Size(tokens.scaled(220), tokens.scaled(120)))

    # -- geometry ------------------------------------------------------------
    def _row_height(self) -> int:
        return tokens.scaled(self.ROW_HEIGHT)

    def _visible_rows(self) -> int:
        height = self.GetClientSize().height - tokens.scaled(self.PADDING) * 2
        return max(1, height // self._row_height())

    def AcceptsFocus(self) -> bool:  # noqa: N802 - wx API spelling
        return True

    def AcceptsFocusFromKeyboard(self) -> bool:  # noqa: N802 - wx API spelling
        return True

    # -- the wx.ListBox vocabulary ------------------------------------------
    def Set(self, choices: Sequence[str]) -> None:  # noqa: N802 - wx API spelling
        """Replace every row, clearing the selection as ``wx.ListBox`` does."""
        self._items = [str(choice) for choice in choices]
        self._selection = wx.NOT_FOUND
        self._top = 0
        self._sync_name()
        self.Refresh()

    def Append(self, choice: str) -> int:  # noqa: N802 - wx API spelling
        self._items.append(str(choice))
        self.Refresh()
        return len(self._items) - 1

    def Clear(self) -> None:  # noqa: N802 - wx API spelling
        self.Set([])

    def GetCount(self) -> int:  # noqa: N802 - wx API spelling
        return len(self._items)

    def GetString(self, index: int) -> str:  # noqa: N802 - wx API spelling
        return self._items[index] if 0 <= index < len(self._items) else ""

    def GetStrings(self) -> List[str]:  # noqa: N802 - wx API spelling
        return list(self._items)

    def SetItems(self, choices: Sequence[str]) -> None:  # noqa: N802 - wx API spelling
        """``wx.ItemContainer``'s spelling of :meth:`Set`, kept for callers of it."""
        self.Set(choices)

    def GetItems(self) -> List[str]:  # noqa: N802 - wx API spelling
        """``wx.ItemContainer``'s spelling of :meth:`GetStrings`, kept the same way."""
        return self.GetStrings()

    def GetSelection(self) -> int:  # noqa: N802 - wx API spelling
        return self._selection

    def SetSelection(self, index: int) -> None:  # noqa: N802 - wx API spelling
        """Select by index without reporting it, as ``wx.ListBox`` does."""
        self.select(index, notify=False)

    def GetStringSelection(self) -> str:  # noqa: N802 - wx API spelling
        return self.GetString(self._selection)

    def SetStringSelection(self, text: str) -> bool:  # noqa: N802 - wx API spelling
        try:
            self.SetSelection(self._items.index(str(text)))
        except ValueError:
            return False
        return True

    def select(self, index: int, *, notify: bool = True) -> None:
        """Move the selection, scroll it into view, and report it."""
        previous = self._selection
        self._selection = (
            int(index) if 0 <= int(index) < len(self._items) else wx.NOT_FOUND
        )
        if self._selection != wx.NOT_FOUND:
            visible = self._visible_rows()
            if self._selection < self._top:
                self._top = self._selection
            elif self._selection >= self._top + visible:
                self._top = self._selection - visible + 1
        self._sync_name()
        self.Refresh()
        if notify and previous != self._selection:
            invoke(self.on_change, self._selection)
            self._emit_listbox(wx.EVT_LISTBOX)

    def _emit_listbox(self, binder: wx.PyEventBinder) -> None:
        command = wx.CommandEvent(binder.typeId, self.GetId())
        command.SetEventObject(self)
        command.SetInt(self._selection)
        command.SetString(self.GetStringSelection())
        self.GetEventHandler().ProcessEvent(command)

    def _sync_name(self) -> None:
        chosen = self.GetStringSelection() or "nothing selected"
        wx.Control.SetName(self, f"{self._stem}: {chosen}, {len(self._items)} items")

    def SetName(self, name: str) -> None:  # noqa: N802 - wx API spelling
        self._stem = str(name)
        self._sync_name()

    # -- behaviour -----------------------------------------------------------
    def _row_at(self, y: int) -> int:
        offset = y - tokens.scaled(self.PADDING)
        if offset < 0:
            return wx.NOT_FOUND
        index = self._top + offset // self._row_height()
        return index if 0 <= index < len(self._items) else wx.NOT_FOUND

    def activate(self) -> None:
        return None

    def _on_left_down(self, event: wx.MouseEvent) -> None:
        if self.IsEnabled():
            self.SetFocus()
            row = self._row_at(event.GetPosition().y)
            if row != wx.NOT_FOUND:
                self.select(row)
        event.Skip()

    def _on_left_up(self, event: wx.MouseEvent) -> None:
        self._pressed = False
        event.Skip()

    def _on_double_click(self, event: wx.MouseEvent) -> None:
        row = self._row_at(event.GetPosition().y)
        if row != wx.NOT_FOUND:
            self.select(row)
            self._emit_listbox(wx.EVT_LISTBOX_DCLICK)
        event.Skip()

    def _on_wheel(self, event: wx.MouseEvent) -> None:
        if not self._items:
            return
        lines = 3 if event.GetWheelRotation() < 0 else -3
        highest = max(0, len(self._items) - self._visible_rows())
        self._top = max(0, min(highest, self._top + lines))
        self.Refresh()

    def _on_key_down(self, event: wx.KeyEvent) -> None:
        if not self.IsEnabled() or not self._items:
            event.Skip()
            return
        code = event.GetKeyCode()
        current = self._selection if self._selection != wx.NOT_FOUND else 0
        page = self._visible_rows()
        if code == wx.WXK_DOWN:
            self.select(min(len(self._items) - 1, current + 1))
        elif code == wx.WXK_UP:
            self.select(max(0, current - 1))
        elif code == wx.WXK_PAGEDOWN:
            self.select(min(len(self._items) - 1, current + page))
        elif code == wx.WXK_PAGEUP:
            self.select(max(0, current - page))
        elif code == wx.WXK_HOME:
            self.select(0)
        elif code == wx.WXK_END:
            self.select(len(self._items) - 1)
        elif code in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self._emit_listbox(wx.EVT_LISTBOX_DCLICK)
        else:
            event.Skip()

    # -- painting ------------------------------------------------------------
    def render_to(self, dc: wx.DC, rect: wx.Rect) -> None:
        """Draw the list surface and every row currently scrolled into view."""
        palette = self.palette()
        with self._painting(dc, rect) as rect:
            tokens.draw_round_rect(
                dc,
                rect,
                tokens.scaled(tokens.RADIUS_SM),
                palette.surface_container,
                palette.outline_variant,
            )
            padding = tokens.scaled(self.PADDING)
            row_height = self._row_height()
            dc.SetFont(tokens.font(self, point_size(12)))
            if not self._items:
                dc.SetTextForeground(palette.on_surface_variant)
                dc.DrawText("No entries yet", padding, padding)
                return
            visible = self._visible_rows()
            for offset in range(visible):
                index = self._top + offset
                if index >= len(self._items):
                    break
                row = wx.Rect(
                    padding,
                    padding + offset * row_height,
                    max(0, rect.width - padding * 2),
                    row_height,
                )
                if index == self._selection:
                    tokens.draw_round_rect(
                        dc, row, tokens.scaled(6), palette.primary_container
                    )
                    dc.SetTextForeground(palette.on_primary_container)
                else:
                    dc.SetTextForeground(palette.on_surface)
                text = elide(dc, self._items[index], row.width - tokens.scaled(12))
                dc.DrawText(
                    text,
                    row.x + tokens.scaled(6),
                    row.y + (row.height - dc.GetCharHeight()) // 2,
                )
            if self.HasFocus():
                draw_focus_ring(
                    dc, rect, tokens.scaled(tokens.RADIUS_SM), palette.primary
                )


# ----------------------------------------------------------------------------
# colour
# ----------------------------------------------------------------------------


class MaterialColourField(wx.Panel, _Themed):
    """A live swatch that opens the project's continuous colour picker.

    It answers to the ``wx.ColourPickerCtrl`` API -- ``GetColour``,
    ``SetColour``, and ``wx.EVT_COLOURPICKER_CHANGED`` -- so a surface that
    already reads a colour from a native picker keeps working.  What changes is
    what opens: the project's own picker, with its spectrum, its numeric entry
    in every supported space, its translator, and its contrast readout, rather
    than the operating system's finite swatch grid.
    """

    SWATCH = 34

    def __init__(
        self,
        parent: wx.Window,
        colour: Any = "#6750A4",
        *,
        name: str = "Colour",
        subject: str = "Appearance",
        on_change: Optional[Callable[[wx.Colour], None]] = None,
    ) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self._stem = str(name)
        self.subject = str(subject)
        self.on_change = on_change
        self._colour = widgets.colour_of(colour)
        self._install(self._stem, listen=False)
        row = wx.BoxSizer(wx.HORIZONTAL)
        self.swatch = widgets.Swatch(
            self,
            self._hex(),
            name=f"{self._stem} preview",
            on_click=lambda _colour: self.open_picker(),
            size=self.SWATCH,
        )
        self.button = widgets.StudioButton(
            self,
            self._hex(),
            variant="outlined",
            hint="Open the colour picker, its translator, and its contrast readout",
            on_click=self.open_picker,
            name=f"{self._stem}: {self._hex()}",
        )
        row.Add(self.swatch, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, tokens.SPACE_SM)
        row.Add(self.button, 0, wx.ALIGN_CENTER_VERTICAL)
        self.SetSizer(row)
        self._apply_theme(self.palette())

    def _hex(self) -> str:
        return "#%02X%02X%02X" % (
            self._colour.Red(),
            self._colour.Green(),
            self._colour.Blue(),
        )

    # -- the wx.ColourPickerCtrl vocabulary ---------------------------------
    def GetColour(self) -> wx.Colour:  # noqa: N802 - wx API spelling
        return self._colour

    def SetColour(self, colour: Any) -> None:  # noqa: N802 - wx API spelling
        """Set the colour without reporting it, as the native picker does."""
        self.set_colour(colour, notify=False)

    def set_colour(self, colour: Any, *, notify: bool = True) -> None:
        """Apply a colour to the swatch, the label, and the accessible name."""
        resolved = widgets.colour_of(colour)
        if not resolved.IsOk():
            return
        changed = resolved.GetRGB() != self._colour.GetRGB()
        self._colour = resolved
        self.swatch.set_colour(self._colour)
        self.swatch.SetName(f"{self._stem} preview: {self._hex()}")
        self.swatch.SetToolTip(f"{self._stem} preview: {self._hex()}")
        self.button.SetLabel(self._hex())
        self.button.SetName(f"{self._stem}: {self._hex()}")
        self.Layout()
        if notify and changed:
            invoke(self.on_change, self._colour)
            command = wx.CommandEvent(wx.EVT_COLOURPICKER_CHANGED.typeId, self.GetId())
            command.SetEventObject(self)
            self.GetEventHandler().ProcessEvent(command)

    def SetName(self, name: str) -> None:  # noqa: N802 - wx API spelling
        self._stem = str(name)
        super().SetName(name)

    def SetFocus(self) -> None:  # noqa: N802 - wx API spelling
        self.button.SetFocus()

    def Enable(self, enable: bool = True) -> bool:  # noqa: N802 - wx API spelling
        result = super().Enable(enable)
        for child in (getattr(self, "swatch", None), getattr(self, "button", None)):
            if child is not None:
                child.Enable(enable)
        return result

    # -- the picker ----------------------------------------------------------
    def open_picker(self) -> None:
        """Open the continuous picker, applying its result when confirmed."""
        if not self.IsEnabled():
            return
        try:
            from amulet_map_editor.api.wx.ui.colour_picker import ColourPickerDialog
        except ImportError:
            # The picker is optional for a partial install; the field still
            # shows and reports its colour, so say so rather than failing.
            self.button.SetToolTip("The colour picker is not available in this build")
            return
        dialog = ColourPickerDialog(
            self,
            self._hex(),
            on_apply=lambda value: self.set_colour(value, notify=True),
            title=self._stem,
            subject=self.subject,
        )
        dialog.Show()

    def _apply_theme(self, palette: tokens.StudioPalette) -> None:
        parent = self.GetParent()
        backdrop = parent.GetBackgroundColour() if parent else palette.surface
        self.SetBackgroundColour(backdrop if backdrop.IsOk() else palette.surface)


# ----------------------------------------------------------------------------
# the dialog's own chrome
# ----------------------------------------------------------------------------


class _WindowButton(wx.Control, _Interactive):
    """A painted caption action: minimise, maximise, or close.

    The glyph is stroked rather than set as text.  A font without the character
    draws its own placeholder box, and a close button whose glyph is a hollow
    rectangle reads as a control that does nothing.
    """

    WIDTH = 44
    HEIGHT = 32

    def __init__(
        self, parent: wx.Window, action: str, name: str, on_click: Callable[[], None]
    ) -> None:
        super().__init__(parent, style=wx.BORDER_NONE | wx.WANTS_CHARS)
        if action not in ("minimize", "maximize", "close"):
            raise ValueError(f"Unknown window action: {action!r}")
        self.action = action
        self.on_click = on_click
        self._install(name, listen=False)
        self.SetToolTip(name)
        self._bind_interaction()
        self.SetInitialSize(
            wx.Size(tokens.scaled(self.WIDTH), tokens.scaled(self.HEIGHT))
        )

    def activate(self) -> None:
        invoke(self.on_click)

    def render_to(self, dc: wx.DC, rect: wx.Rect) -> None:
        """Draw the hover state layer and the stroked glyph."""
        palette = self.palette()
        with self._painting(dc, rect) as rect:
            ink = palette.on_surface_variant
            if self._hovered or self._pressed:
                fill = (
                    palette.error
                    if self.action == "close"
                    else palette.surface_container_high
                )
                tokens.draw_round_rect(dc, rect, tokens.scaled(6), fill)
                if self.action == "close":
                    ink = palette.surface
            size = tokens.scaled(10)
            left = (rect.width - size) // 2
            top = (rect.height - size) // 2
            pen = wx.Pen(ink, max(1, tokens.scaled(1)))
            pen.SetCap(wx.CAP_ROUND)
            dc.SetPen(pen)
            dc.SetBrush(wx.TRANSPARENT_BRUSH)
            middle = top + size // 2
            if self.action == "minimize":
                dc.DrawLine(left, middle, left + size, middle)
            elif self.action == "maximize":
                dc.DrawRectangle(wx.Rect(left, top, size, size))
            else:
                dc.DrawLine(left, top, left + size, top + size)
                dc.DrawLine(left + size, top, left, top + size)
            dc.SetPen(wx.NullPen)
            if self.HasFocus():
                draw_focus_ring(dc, rect, tokens.scaled(6), palette.primary)


class MaterialDialogTitleBar(wx.Panel, _Themed):
    """The product's own title bar for a borderless dialog.

    A Windows desktop app in this project uses a frameless window and draws its
    own caption; leaving the operating system's title bar on a dialog puts a
    strip of somebody else's design across the top of the product.  The bar
    drags the window, double-click maximises it where the window allows it, and
    every button is reachable from the keyboard with a name of its own.
    """

    HEIGHT = 40

    def __init__(
        self,
        parent: wx.TopLevelWindow,
        title: str,
        *,
        subtitle: str = "",
        maximise: bool = False,
        minimise: bool = False,
    ) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        window = (
            parent
            if isinstance(parent, wx.TopLevelWindow)
            else parent.GetTopLevelParent()
        )
        if not isinstance(window, wx.TopLevelWindow):
            raise TypeError("A title bar needs a top-level window to move and close")
        self._window = window
        self._drag_origin: Optional[wx.Point] = None
        self._install("Window title bar", listen=False)
        self.SetMinSize(wx.Size(-1, tokens.scaled(self.HEIGHT)))
        row = wx.BoxSizer(wx.HORIZONTAL)
        self.title = StudioText(
            self,
            str(title),
            size_px=13,
            weight=_MEDIUM,
            role="on_surface",
            ellipsize=True,
            name="Window title",
        )
        row.Add(self.title, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, tokens.SPACE_MD)
        if subtitle:
            row.Add(
                StudioText(self, str(subtitle), size_px=12, name="Window subtitle"),
                0,
                wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
                tokens.SPACE_SM,
            )
        row.AddStretchSpacer()
        self.buttons: List[_WindowButton] = []
        if minimise:
            self.buttons.append(
                _WindowButton(
                    self, "minimize", "Minimize window", lambda: window.Iconize(True)
                )
            )
        if maximise:
            self.buttons.append(
                _WindowButton(
                    self, "maximize", "Maximize window", self._toggle_maximise
                )
            )
        self.buttons.append(_WindowButton(self, "close", "Close window", self._close))
        for button in self.buttons:
            row.Add(button, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, tokens.SPACE_XS)
        row.AddSpacer(tokens.SPACE_SM)
        self.SetSizer(row)
        for control in (self, self.title):
            control.Bind(wx.EVT_LEFT_DOWN, self._drag_start)
            control.Bind(wx.EVT_LEFT_UP, self._drag_end)
            control.Bind(wx.EVT_MOTION, self._drag_move)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self._apply_theme(self.palette())

    def set_title(self, title: str) -> None:
        """Replace the visible title and the name a screen reader reads."""
        self.title.SetLabel(str(title))
        self.Layout()

    def _toggle_maximise(self) -> None:
        self._window.Maximize(not self._window.IsMaximized())

    def _close(self) -> None:
        if isinstance(self._window, wx.Dialog) and self._window.IsModal():
            self._window.EndModal(wx.ID_CANCEL)
            return
        self._window.Close()

    def _drag_start(self, event: wx.MouseEvent) -> None:
        self._drag_origin = event.GetPosition()
        if not self.HasCapture():
            self.CaptureMouse()
        event.Skip()

    def _drag_end(self, event: wx.MouseEvent) -> None:
        if self.HasCapture():
            self.ReleaseMouse()
        self._drag_origin = None
        event.Skip()

    def _drag_move(self, event: wx.MouseEvent) -> None:
        if self._drag_origin is None or not event.Dragging() or not event.LeftIsDown():
            event.Skip()
            return
        screen = self.ClientToScreen(event.GetPosition())
        origin = self.ClientToScreen(self._drag_origin)
        position = self._window.GetPosition()
        self._window.Move(
            position.x + screen.x - origin.x, position.y + screen.y - origin.y
        )

    def _backdrop(self) -> wx.Colour:
        return self.palette().surface_container

    def _apply_theme(self, palette: tokens.StudioPalette) -> None:
        """Give the bar and everything on it the same container colour.

        The children are told explicitly rather than left to inherit. Each one
        works out its own backdrop from its parent's background colour, and the
        shared ``apply_material3`` pass runs afterwards and re-colours native
        and painted children to the plain surface role -- so the title and the
        subtitle came out drawn on white tiles laid over a grey bar.
        """
        self.SetBackgroundColour(palette.surface_container)
        for child in self.GetChildren():
            child.SetBackgroundColour(palette.surface_container)
            child.Refresh()

    def render_to(self, dc: wx.DC, rect: wx.Rect) -> None:
        """Fill the caption strip and rule it off from the content below."""
        palette = self.palette()
        with self._painting(dc, rect) as rect:
            dc.SetBrush(wx.Brush(palette.surface_container))
            dc.SetPen(wx.TRANSPARENT_PEN)
            dc.DrawRectangle(rect)
            dc.SetPen(wx.Pen(palette.outline_variant, 1))
            dc.DrawLine(0, rect.height - 1, rect.width, rect.height - 1)
            dc.SetPen(wx.NullPen)


class MaterialFontField(wx.Panel, _Themed):
    """A face name drawn in its own face, opening the project's typography editor.

    It answers to the ``wx.FontPickerCtrl`` API -- ``GetSelectedFont``,
    ``SetSelectedFont``, and ``wx.EVT_FONTPICKER_CHANGED`` -- while opening the
    editor this project actually has, with its searchable face list, its
    variable-font axes, and the rest of the word-processor-depth controls,
    instead of the platform's own font dialog.
    """

    def __init__(
        self,
        parent: wx.Window,
        font: Optional[wx.Font] = None,
        *,
        name: str = "Font",
        subject: str = "Appearance",
        on_change: Optional[Callable[[wx.Font], None]] = None,
    ) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self._stem = str(name)
        self.subject = str(subject)
        self.on_change = on_change
        self._font = font or wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)
        self._install(self._stem, listen=False)
        row = wx.BoxSizer(wx.HORIZONTAL)
        self.button = widgets.StudioButton(
            self,
            self._face_label(),
            variant="outlined",
            hint="Open the typography editor for this font",
            on_click=self.open_picker,
            name=f"{self._stem}: {self._face_label()}",
        )
        row.Add(self.button, 0, wx.ALIGN_CENTER_VERTICAL)
        self.SetSizer(row)
        self._apply_theme(self.palette())

    def _face_label(self) -> str:
        face = self._font.GetFaceName()
        return face or "Platform default"

    # -- the wx.FontPickerCtrl vocabulary -----------------------------------
    def GetSelectedFont(self) -> wx.Font:  # noqa: N802 - wx API spelling
        return self._font

    def SetSelectedFont(self, font: wx.Font) -> None:  # noqa: N802 - wx API spelling
        """Set the face without reporting it, as the native picker does."""
        self.set_font(font, notify=False)

    def set_font(self, font: wx.Font, *, notify: bool = True) -> None:
        """Adopt a font, keeping the label, the sample face, and the name in step."""
        if font is None or not font.IsOk():
            return
        self._font = font
        self.button.SetLabel(self._face_label())
        self.button.SetName(f"{self._stem}: {self._face_label()}")
        self.Layout()
        if notify:
            invoke(self.on_change, self._font)
            command = wx.CommandEvent(wx.EVT_FONTPICKER_CHANGED.typeId, self.GetId())
            command.SetEventObject(self)
            self.GetEventHandler().ProcessEvent(command)

    def SetName(self, name: str) -> None:  # noqa: N802 - wx API spelling
        self._stem = str(name)
        super().SetName(name)

    def SetFocus(self) -> None:  # noqa: N802 - wx API spelling
        self.button.SetFocus()

    def Enable(self, enable: bool = True) -> bool:  # noqa: N802 - wx API spelling
        result = super().Enable(enable)
        button = getattr(self, "button", None)
        if button is not None:
            button.Enable(enable)
        return result

    def open_picker(self) -> None:
        """Open the typography editor, adopting the face it comes back with."""
        if not self.IsEnabled():
            return
        try:
            from amulet_map_editor.api.wx.ui.font_picker import (
                FontStyle,
                open_font_picker,
            )
        except ImportError:
            self.button.SetToolTip("The typography editor is not available here")
            return
        open_font_picker(
            self,
            FontStyle(face=self._font.GetFaceName(), size=self._font.GetPointSize()),
            on_apply=self._adopt_style,
            title=self._stem,
            subject=self.subject,
        )

    def _adopt_style(self, style: Any) -> None:
        face = getattr(style, "face", "") or ""
        size = int(getattr(style, "size", 0) or self._font.GetPointSize())
        font = wx.Font(
            max(6, size),
            wx.FONTFAMILY_DEFAULT,
            wx.FONTSTYLE_NORMAL,
            wx.FONTWEIGHT_NORMAL,
            faceName=face,
        )
        self.set_font(font, notify=True)

    def _apply_theme(self, palette: tokens.StudioPalette) -> None:
        parent = self.GetParent()
        backdrop = parent.GetBackgroundColour() if parent else palette.surface
        self.SetBackgroundColour(backdrop if backdrop.IsOk() else palette.surface)


class MaterialScrolled(wx.ScrolledWindow):
    """A scrolling page whose scrollbar is painted rather than the platform's.

    The scrolling itself is still ``wx.ScrolledWindow``'s: the wheel, the
    keyboard, and ``Scroll`` all keep working, and reimplementing them would be
    reimplementing the one part of this control that was never wrong.  What
    changes is the bar, which is hidden and drawn instead, so a settings page
    does not carry a strip of the operating system's chrome down its edge.

    The thumb is drawn in viewport coordinates deliberately.  ``DoPrepareDC``
    is not called for this paint, so the origin does not move with the content
    and the bar stays where a scrollbar belongs rather than scrolling away with
    what it is scrolling.

    **The content goes on** :attr:`content`, **not on this window.**  A sizer
    installed directly on a scrolled window is laid out into the *viewport* by
    ``wxWindow::Layout``, and a ``wx.BoxSizer`` given less room than its
    children need does not report the shortfall -- it takes it out of whatever
    is at the end.  On a settings page the end of the column is the rest of the
    settings, so a 1875-pixel column laid into a 601-pixel viewport gave its
    first four rows their full height and every row after them **zero**: the
    accent colour, the font controls, the scale and the whole preset library
    were in the tree, reported ``IsShown()``, and were 669x0.  Nothing about
    that looks like a failure -- the page scrolls, the bar has a range, and
    the content below the fold simply is not there.

    Overriding ``Layout`` to lay the sizer out over the content height does not
    fix it: wx re-lays the window out through paths that do not reach a Python
    override, and the squash comes back.  An inner panel sized explicitly does
    fix it, because nothing else is in a position to resize it.
    """

    WIDTH = 8
    MARGIN = 3

    def __init__(self, parent: wx.Window, *, name: str = "Scrolling page") -> None:
        super().__init__(parent, style=wx.VSCROLL | wx.TAB_TRAVERSAL)
        self.SetName(name)
        #: Build the page's content on this, and give it a sizer.  It is sized
        #: to its own content height by :meth:`fit_content`.
        self.content = wx.Panel(self, style=wx.TAB_TRAVERSAL)
        self.content.SetName(f"{name} content")
        self.SetScrollRate(0, tokens.scaled(12))
        try:
            self.ShowScrollbars(wx.SHOW_SB_NEVER, wx.SHOW_SB_NEVER)
        except (AttributeError, RuntimeError):
            # A platform without the call keeps its native bar; the page still
            # scrolls, which is the behaviour that matters.
            pass
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self._dragging = False
        self._fitting = False
        self._fitted_width = -1
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.Bind(wx.EVT_SIZE, self._on_size)
        self.Bind(wx.EVT_LEFT_DOWN, self._on_left_down)
        self.Bind(wx.EVT_LEFT_UP, self._on_left_up)
        self.Bind(wx.EVT_MOTION, self._on_motion)
        self.Bind(wx.EVT_MOUSE_CAPTURE_LOST, self._on_capture_lost)
        self.refresh_theme()

    def refresh_theme(self) -> None:
        """Re-read the palette; the page is a plain surface behind its content."""
        try:
            surface = tokens.palette().surface
            self.SetBackgroundColour(surface)
            self._apply_content_theme(surface)
            self.Refresh()
        except RuntimeError:
            return

    def fit_content(self) -> None:
        """Size :attr:`content` to its own column height and set the scroll range.

        Call it once after the page's rows are built.  It is also run on every
        resize, because the rows re-wrap their help text to the width they are
        given and a re-wrap changes the height of the column.
        """
        sizer = self.content.GetSizer()
        if sizer is None or self._fitting:
            # Re-entry guard. Setting the virtual size below makes the scroll
            # helper re-adjust its scrollbars, and that adjustment can raise
            # the size event that runs this, so the fit is kept from calling
            # itself rather than relying on the sizes happening to settle.
            return
        self._fitting = True
        try:
            self._fit(sizer)
        finally:
            self._fitting = False

    def _fit(self, sizer: wx.Sizer) -> None:
        # The content is laid out at the full client width and the painted bar
        # is drawn over it, rather than the column being narrowed to leave the
        # bar its own lane. Narrowing would feed the fit back into its own
        # input -- a narrower column is a taller one, and a taller one changes
        # the scroll range -- and the pages that use this carry 20 pixels of
        # padding, which is wider than the bar, so nothing lands underneath it.
        width = max(1, self.GetClientSize().width)
        sizer.SetDimension(0, 0, width, sizer.GetMinSize().height)
        height = max(sizer.GetMinSize().height, self.GetClientSize().height)
        # Resize at the position the panel already has. The scroll helper moves
        # this panel in order to scroll it, so passing (0, 0) here pins the page
        # back to the top every time it is re-fitted -- the scrollbar moves and
        # the content does not. Passing its own position keeps both true.
        position = self.content.GetPosition()
        if tuple(self.content.GetSize()) != (width, height):
            self.content.SetSize(position.x, position.y, width, height)
        # Only when it actually changed. Setting it unconditionally makes the
        # scroll helper re-adjust its scrollbars on every size event, and each
        # adjustment raises another size event: the queue never drains, and a
        # single Scroll() call never returns. It looks exactly like a hang and
        # prints nothing.
        wanted = wx.Size(width, height)
        if tuple(self.GetVirtualSize()) != tuple(wanted):
            self.SetVirtualSize(wanted)

    def _on_size(self, event: wx.SizeEvent) -> None:
        """Re-fit the content when the viewport's **width** changes, and only then.

        The rows re-wrap their help text to the width they are given, so a
        width change alters their heights and therefore the height of the
        column; a height change does not, and neither does a scroll.

        The guard is on the width rather than on the event, because fitting
        sets the virtual size and the scroll helper can answer that with
        another size event.  Refitting only when the width has actually moved
        breaks that cycle at its cause instead of damping it.
        """
        width = self.GetClientSize().width
        if width != self._fitted_width:
            self._fitted_width = width
            self.fit_content()
        self.Refresh()
        event.Skip()

    def _apply_content_theme(self, colour: wx.Colour) -> None:
        self.content.SetBackgroundColour(colour)

    # -- the thumb -----------------------------------------------------------
    def _extent(self) -> Tuple[int, int, int]:
        """Return the viewport height, the content height, and the offset."""
        view = self.GetClientSize().height
        rate = max(1, self.GetScrollPixelsPerUnit()[1])
        content = self.GetVirtualSize().height
        offset = self.GetViewStart()[1] * rate
        return view, max(content, view), offset

    def _thumb_rect(self) -> Optional[wx.Rect]:
        view, content, offset = self._extent()
        if content <= view or view <= 0:
            return None
        width = tokens.scaled(self.WIDTH)
        margin = tokens.scaled(self.MARGIN)
        track = view - margin * 2
        height = max(tokens.scaled(24), int(track * view / content))
        travel = track - height
        top = margin + (int(travel * offset / (content - view)) if travel > 0 else 0)
        return wx.Rect(self.GetClientSize().width - width - margin, top, width, height)

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush(palette.surface))
        dc.Clear()
        thumb = self._thumb_rect()
        if thumb is None:
            return
        try:
            gcdc: wx.DC = wx.GCDC(dc)
        except TypeError:  # pragma: no cover - platform boundary
            gcdc = dc
        track = wx.Rect(
            thumb.x,
            tokens.scaled(self.MARGIN),
            thumb.width,
            self.GetClientSize().height - tokens.scaled(self.MARGIN) * 2,
        )
        tokens.draw_round_rect(gcdc, track, thumb.width // 2, palette.surface_container)
        tokens.draw_round_rect(
            gcdc,
            thumb,
            thumb.width // 2,
            palette.outline if self._dragging else palette.outline_variant,
        )

    def _scroll_to(self, y: int) -> None:
        view, content, _offset = self._extent()
        margin = tokens.scaled(self.MARGIN)
        thumb = self._thumb_rect()
        if thumb is None:
            return
        travel = max(1, view - margin * 2 - thumb.height)
        fraction = min(1.0, max(0.0, (y - margin - thumb.height / 2) / travel))
        rate = max(1, self.GetScrollPixelsPerUnit()[1])
        self.Scroll(0, int(round(fraction * (content - view) / rate)))
        self.Refresh()

    def _on_left_down(self, event: wx.MouseEvent) -> None:
        thumb = self._thumb_rect()
        position = event.GetPosition()
        if thumb is not None and position.x >= thumb.x:
            self._dragging = True
            if not self.HasCapture():
                self.CaptureMouse()
            self._scroll_to(position.y)
        event.Skip()

    def _on_left_up(self, event: wx.MouseEvent) -> None:
        self._dragging = False
        if self.HasCapture():
            self.ReleaseMouse()
        self.Refresh()
        event.Skip()

    def _on_motion(self, event: wx.MouseEvent) -> None:
        if self._dragging and event.LeftIsDown():
            self._scroll_to(event.GetPosition().y)
        event.Skip()

    def _on_capture_lost(self, _event: wx.MouseCaptureLostEvent) -> None:
        self._dragging = False
        self.Refresh()


# ----------------------------------------------------------------------------
# one settings element, with its explanation and its provenance
# ----------------------------------------------------------------------------


class SettingRow(wx.Panel, _Themed):
    """One settings element: its name, its control, its help, its provenance.

    Two things sit beside the control and are not decoration.

    The *explanation* is behind progressive disclosure -- a question-mark
    affordance that reveals a sentence saying what the setting actually does,
    rather than restating its own label.  It is collapsed by default so a page
    of thirty settings stays scannable, and it is a real toggle rather than a
    tooltip so it is reachable from the keyboard and readable by a screen
    reader.

    The *provenance* line says plainly whether the value on screen came from
    something the user or a prior process actually wrote, or whether the
    application is quietly falling back to a compiled-in default -- and when it
    is a default, names the real value rather than the opaque word "default".
    A settings page that cannot answer "did I set this, or is it just what it
    came with?" makes every value on it ambiguous.
    """

    def __init__(
        self,
        parent: wx.Window,
        label: str,
        *,
        explanation: str = "",
        provenance: str = "",
        name: str = "",
    ) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self.setting_label = str(label)
        self._install(name or f"{label} setting", listen=False)
        self.control: Optional[wx.Window] = None
        root = wx.BoxSizer(wx.VERTICAL)

        head = wx.BoxSizer(wx.HORIZONTAL)
        self.caption = StudioText(
            self,
            self.setting_label,
            size_px=13,
            weight=_MEDIUM,
            role="on_surface",
            name=f"{self.setting_label} label",
        )
        head.Add(self.caption, 0, wx.ALIGN_CENTER_VERTICAL)
        self.disclosure: Optional[widgets.StudioButton] = None
        if explanation:
            self.disclosure = widgets.StudioButton(
                self,
                "?",
                variant="icon",
                hint=f"Explain what {self.setting_label} does",
                on_click=self.toggle_explanation,
                name=f"Explain {self.setting_label}, collapsed",
            )
            head.Add(
                self.disclosure, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, tokens.SPACE_XS
            )
        root.Add(head, 0, wx.BOTTOM, tokens.SPACE_XS)

        self.body = wx.Panel(self, style=wx.TAB_TRAVERSAL)
        self.body.SetSizer(wx.BoxSizer(wx.HORIZONTAL))
        root.Add(self.body, 0, wx.EXPAND)

        self.explanation = StudioText(
            self,
            str(explanation),
            size_px=12,
            wrap_width=520,
            max_lines=6,
            name=f"{self.setting_label} explanation",
        )
        self.explanation.Show(False)
        root.Add(self.explanation, 0, wx.EXPAND | wx.TOP, tokens.SPACE_XS)

        self.provenance = StudioText(
            self,
            str(provenance),
            size_px=11,
            wrap_width=520,
            max_lines=3,
            name=f"{self.setting_label} value source",
        )
        root.Add(self.provenance, 0, wx.EXPAND | wx.TOP, 2)
        self.SetSizer(root)
        self.Bind(wx.EVT_SIZE, self._on_size)
        self._apply_theme(self.palette())

    #: The width the help lines were last wrapped to.  Re-wrapping changes a
    #: label's best size, which asks the sizer to lay the row out again, which
    #: raises the size event that does the wrapping: without remembering the
    #: width, a row spins on its own resize.
    _wrapped_at: int = -1

    def _on_size(self, event: wx.SizeEvent) -> None:
        """Re-wrap the help and provenance lines to the width actually given.

        Wrapping to a fixed number of pixels is how a sentence ends up running
        off the right-hand edge of a narrow window while looking perfect in the
        one the author happened to have open.
        """
        width = max(tokens.scaled(200), self.GetClientSize().width - tokens.SPACE_SM)
        if width != self._wrapped_at:
            self._wrapped_at = width
            for line in (self.explanation, self.provenance):
                if line.GetLabel():
                    line.Wrap(width)
        event.Skip()

    def set_control(self, control: wx.Window, proportion: int = 1) -> wx.Window:
        """Adopt the control this row is about.  Build it on :attr:`body`."""
        self.control = control
        self.body.GetSizer().Add(control, proportion, wx.EXPAND)
        self.body.Layout()
        return control

    def add_extra(self, control: wx.Window, proportion: int = 0) -> wx.Window:
        """Add a second control -- a Browse button, a reset -- beside the first.

        Centred on the vertical axis rather than expanded.  A button stretched
        to the height of the field beside it becomes a pill four times its
        design height, which is not a Material button at any density.
        """
        self.body.GetSizer().Add(
            control,
            proportion,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            tokens.SPACE_SM,
        )
        self.body.Layout()
        return control

    def set_provenance(self, text: str) -> None:
        """Replace the value-source line."""
        self.provenance.SetLabel(str(text))
        self.Layout()

    def toggle_explanation(self) -> None:
        """Reveal or hide the explanation, keeping its state in the button name."""
        shown = not self.explanation.IsShown()
        self.explanation.Show(shown)
        if self.disclosure is not None:
            self.disclosure.SetName(
                f"Explain {self.setting_label}, "
                f"{'expanded' if shown else 'collapsed'}"
            )
        self.Layout()
        parent = self.GetParent()
        if parent is not None:
            parent.Layout()
            fit = getattr(parent, "FitInside", None)
            if callable(fit):
                fit()

    def _apply_theme(self, palette: tokens.StudioPalette) -> None:
        parent = self.GetParent()
        backdrop = parent.GetBackgroundColour() if parent else palette.surface
        resolved = backdrop if backdrop.IsOk() else palette.surface
        self.SetBackgroundColour(resolved)
        self.body.SetBackgroundColour(resolved)

    def _backdrop(self) -> wx.Colour:
        return self.GetBackgroundColour()


def stored_provenance(
    stored: Dict[str, Any], key: str, default: Any, *, unit: str = ""
) -> str:
    """Return one setting's truthful value-source line.

    ``stored`` is the raw persisted record, so a key that is absent from it is
    a value nobody has ever written and the application is falling back to what
    it was compiled with -- which the line then names, because "default" on its
    own tells a reader nothing about what they are actually looking at.
    """
    shipped = f"{default}{unit}" if default != "" else "empty"
    if key in stored:
        return f"Saved in your preferences file. The shipped value is {shipped}."
    return f"Not saved yet — showing the shipped value, {shipped}."


def make_frameless(window: wx.TopLevelWindow) -> None:
    """Strip the operating system's caption from ``window``.

    The project's rule is that a desktop window draws its own title bar, so the
    platform's caption, system menu, and its minimise and maximise boxes are
    removed here and replaced by :class:`MaterialDialogTitleBar`.  The resize
    border stays: a dialog that cannot be resized clips its own content at the
    display scales this project supports.
    """
    style = window.GetWindowStyleFlag()
    window.SetWindowStyleFlag(
        (style & ~wx.CAPTION & ~wx.SYSTEM_MENU & ~wx.MINIMIZE_BOX & ~wx.MAXIMIZE_BOX)
        | wx.NO_BORDER
        | wx.RESIZE_BORDER
    )
