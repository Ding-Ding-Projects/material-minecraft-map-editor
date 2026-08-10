"""Owner-drawn Material 3 controls for high-visibility desktop surfaces."""

from __future__ import annotations

from collections.abc import Callable

import wx

from amulet_map_editor.api.wx.material3 import (
    _active_palette,
    _blend_colour,
    _control_min_height,
    _font_for,
)


class MaterialCard(wx.Panel):
    """A rounded M3 surface container that keeps native child controls."""

    def __init__(self, parent: wx.Window, *, name: str = "Material card") -> None:
        super().__init__(parent, name=name)
        self._material3_surface_role = "surface_container"
        self.SetBackgroundColour(_active_palette()["surface_container"])
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self._paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)

    def _paint(self, _event: wx.PaintEvent) -> None:
        palette = _active_palette()
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush(palette["surface"]))
        dc.Clear()
        graphics = wx.GraphicsContext.Create(dc)
        if graphics is None:
            return
        width, height = self.GetClientSize()
        graphics.SetBrush(wx.Brush(palette["surface_container"]))
        graphics.SetPen(wx.Pen(palette["outline"], 1))
        graphics.DrawRoundedRectangle(
            0.5, 0.5, max(0, width - 1), max(0, height - 1), 20
        )


class MaterialButton(wx.Control):
    """Keyboard-operable filled, tonal, outlined, or text M3 button."""

    _VARIANTS = {"filled", "tonal", "outlined", "text"}

    def __init__(
        self,
        parent: wx.Window,
        label: str,
        *,
        variant: str = "filled",
        name: str | None = None,
    ) -> None:
        if variant not in self._VARIANTS:
            raise ValueError(f"Unknown Material button variant: {variant}")
        super().__init__(
            parent, name=name or label, style=wx.BORDER_NONE | wx.WANTS_CHARS
        )
        self._material3_surface_role = "surface_container"
        wx.Control.SetLabel(self, label)
        self.variant = variant
        self._hovered = False
        self._pressed = False
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetCursor(wx.Cursor(wx.CURSOR_HAND))
        self.SetFont(_font_for(self, 10, wx.FONTWEIGHT_MEDIUM))
        self.SetMinSize(self.DoGetBestSize())
        self.Bind(wx.EVT_PAINT, self._paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.Bind(wx.EVT_ENTER_WINDOW, self._enter)
        self.Bind(wx.EVT_LEAVE_WINDOW, self._leave)
        self.Bind(wx.EVT_LEFT_DOWN, self._left_down)
        self.Bind(wx.EVT_LEFT_UP, self._left_up)
        self.Bind(wx.EVT_KEY_DOWN, self._key_down)
        self.Bind(wx.EVT_SET_FOCUS, self._focus_changed)
        self.Bind(wx.EVT_KILL_FOCUS, self._focus_changed)

    def SetLabel(self, label: str) -> None:  # noqa: N802 - wx API spelling
        super().SetLabel(label)
        self.SetName(label)
        self.InvalidateBestSize()
        self.SetMinSize(self.DoGetBestSize())
        self.Refresh()

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        dc = wx.ClientDC(self)
        dc.SetFont(self.GetFont())
        width, text_height = dc.GetTextExtent(self.GetLabel() or " ")
        native_height = wx.Control.DoGetBestSize(self).height
        content_height = max(native_height, text_height) + 20
        return wx.Size(
            max(96, width + 48),
            max(_control_min_height(), content_height),
        )

    def _enter(self, event: wx.MouseEvent) -> None:
        self._hovered = True
        self.Refresh()
        event.Skip()

    def _leave(self, event: wx.MouseEvent) -> None:
        self._hovered = False
        if not event.LeftIsDown():
            self._pressed = False
        self.Refresh()
        event.Skip()

    def _left_down(self, event: wx.MouseEvent) -> None:
        if self.IsEnabled():
            self.SetFocus()
            self._pressed = True
            if not self.HasCapture():
                self.CaptureMouse()
            self.Refresh()
        event.Skip()

    def _left_up(self, event: wx.MouseEvent) -> None:
        was_pressed = self._pressed
        self._pressed = False
        if self.HasCapture():
            self.ReleaseMouse()
        self.Refresh()
        if was_pressed and self.GetClientRect().Contains(event.GetPosition()):
            self._emit_button()
        event.Skip()

    def _key_down(self, event: wx.KeyEvent) -> None:
        if self.IsEnabled() and event.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_SPACE):
            self._emit_button()
            return
        event.Skip()

    def _focus_changed(self, event: wx.FocusEvent) -> None:
        self.Refresh()
        event.Skip()

    def _emit_button(self) -> None:
        event = wx.CommandEvent(wx.EVT_BUTTON.typeId, self.GetId())
        event.SetEventObject(self)
        self.GetEventHandler().ProcessEvent(event)

    def _roles(self) -> tuple[wx.Colour, wx.Colour, wx.Colour | None]:
        palette = _active_palette()
        if not self.IsEnabled():
            return (
                palette["surface_container"],
                palette["on_surface_variant"],
                None,
            )
        if self.variant == "filled":
            background, foreground, border = (
                palette["primary"],
                palette["on_primary"],
                None,
            )
        elif self.variant == "tonal":
            background, foreground, border = (
                palette["primary_container"],
                palette["on_primary_container"],
                None,
            )
        elif self.variant == "outlined":
            background, foreground, border = (
                palette["surface_container"],
                palette["primary"],
                palette["outline"],
            )
        else:
            background, foreground, border = (
                palette["surface_container"],
                palette["primary"],
                None,
            )
        if self._pressed:
            background = _blend_colour(background, foreground, 0.16)
        elif self._hovered:
            background = _blend_colour(background, foreground, 0.08)
        return background, foreground, border

    def _paint(self, _event: wx.PaintEvent) -> None:
        palette = _active_palette()
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush(palette["surface_container"]))
        dc.Clear()
        graphics = wx.GraphicsContext.Create(dc)
        if graphics is None:
            return
        width, height = self.GetClientSize()
        background, foreground, border = self._roles()
        graphics.SetBrush(wx.Brush(background))
        graphics.SetPen(wx.Pen(border or background, 1))
        inset = 2 if self.HasFocus() else 0.5
        graphics.DrawRoundedRectangle(
            inset,
            inset,
            max(0, width - 2 * inset),
            max(0, height - 2 * inset),
            max(8, height / 2),
        )
        if self.HasFocus():
            graphics.SetBrush(wx.TRANSPARENT_BRUSH)
            graphics.SetPen(wx.Pen(palette["primary"], 2))
            graphics.DrawRoundedRectangle(
                1, 1, max(0, width - 2), max(0, height - 2), max(8, height / 2)
            )
        graphics.SetFont(self.GetFont(), foreground)
        text_width, text_height = graphics.GetTextExtent(self.GetLabel())
        graphics.DrawText(
            self.GetLabel(),
            (width - text_width) / 2,
            (height - text_height) / 2,
        )


class MaterialWindowButton(wx.Control):
    """Compact M3 caption action whose glyph is drawn, not font-dependent."""

    _ACTIONS = {"minimize", "maximize", "close"}

    def __init__(
        self,
        parent: wx.Window,
        action: str,
        accessible_name: str,
        handler: Callable[[wx.CommandEvent], None],
    ) -> None:
        if action not in self._ACTIONS:
            raise ValueError(f"Unknown window action: {action}")
        super().__init__(
            parent,
            name=accessible_name,
            style=wx.BORDER_NONE | wx.WANTS_CHARS,
        )
        self._material3_surface_role = "surface"
        self.action = action
        self._hovered = False
        self._pressed = False
        self.SetToolTip(accessible_name)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetMinSize(wx.Size(44, 40))
        self.Bind(wx.EVT_BUTTON, handler)
        self.Bind(wx.EVT_PAINT, self._paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.Bind(wx.EVT_ENTER_WINDOW, self._enter)
        self.Bind(wx.EVT_LEAVE_WINDOW, self._leave)
        self.Bind(wx.EVT_LEFT_DOWN, self._left_down)
        self.Bind(wx.EVT_LEFT_UP, self._left_up)
        self.Bind(wx.EVT_KEY_DOWN, self._key_down)
        self.Bind(wx.EVT_SET_FOCUS, self._focus_changed)
        self.Bind(wx.EVT_KILL_FOCUS, self._focus_changed)

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        return wx.Size(44, 40)

    def _enter(self, event: wx.MouseEvent) -> None:
        self._hovered = True
        self.Refresh()
        event.Skip()

    def _leave(self, event: wx.MouseEvent) -> None:
        self._hovered = False
        if not event.LeftIsDown():
            self._pressed = False
        self.Refresh()
        event.Skip()

    def _left_down(self, event: wx.MouseEvent) -> None:
        if self.IsEnabled():
            self.SetFocus()
            self._pressed = True
            self.Refresh()
        event.Skip()

    def _left_up(self, event: wx.MouseEvent) -> None:
        was_pressed = self._pressed
        self._pressed = False
        self.Refresh()
        if was_pressed and self.GetClientRect().Contains(event.GetPosition()):
            self._emit_button()
        event.Skip()

    def _key_down(self, event: wx.KeyEvent) -> None:
        if self.IsEnabled() and event.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_SPACE):
            self._emit_button()
            return
        event.Skip()

    def _focus_changed(self, event: wx.FocusEvent) -> None:
        self.Refresh()
        event.Skip()

    def _emit_button(self) -> None:
        event = wx.CommandEvent(wx.EVT_BUTTON.typeId, self.GetId())
        event.SetEventObject(self)
        self.GetEventHandler().ProcessEvent(event)

    def _paint(self, _event: wx.PaintEvent) -> None:
        palette = _active_palette()
        dc = wx.AutoBufferedPaintDC(self)
        background = palette["surface"]
        if self._hovered or self._pressed:
            overlay = palette["error"] if self.action == "close" else palette["primary"]
            background = _blend_colour(
                background, overlay, 0.18 if self._pressed else 0.10
            )
        dc.SetBackground(wx.Brush(background))
        dc.Clear()
        graphics = wx.GraphicsContext.Create(dc)
        if graphics is None:
            return
        width, height = self.GetClientSize()
        colour = palette["on_surface"]
        dc.SetPen(wx.Pen(colour, 2))
        centre_x, centre_y = width // 2, height // 2
        if self.action == "minimize":
            dc.DrawLine(centre_x - 6, centre_y + 3, centre_x + 7, centre_y + 3)
        elif self.action == "maximize":
            dc.SetBrush(wx.TRANSPARENT_BRUSH)
            dc.DrawRectangle(centre_x - 6, centre_y - 6, 13, 13)
        else:
            dc.DrawLine(centre_x - 5, centre_y - 5, centre_x + 6, centre_y + 6)
            dc.DrawLine(centre_x + 5, centre_y - 5, centre_x - 6, centre_y + 6)
        if self.HasFocus():
            graphics.SetBrush(wx.TRANSPARENT_BRUSH)
            graphics.SetPen(wx.Pen(palette["primary"], 2))
            graphics.DrawRoundedRectangle(
                2, 2, max(0, width - 4), max(0, height - 4), 8
            )


__all__ = ["MaterialButton", "MaterialCard", "MaterialWindowButton"]
