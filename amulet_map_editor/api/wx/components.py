"""Owner-drawn Material 3 controls for high-visibility desktop surfaces."""

from __future__ import annotations

from collections.abc import Callable, Iterable

import wx

from amulet_map_editor.api.material_menu import (
    MaterialMenuItem,
    MenuSelection,
    filter_menu_items,
    fit_menu_command_viewport,
)
from amulet_map_editor.api.wx.material3 import (
    _active_palette,
    _blend_colour,
    _control_min_height,
    _font_for,
    _is_deleted_wrapped_object_error,
    apply_material3,
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
        parent = self.GetParent()
        outside = (
            parent.GetBackgroundColour() if parent is not None else palette["surface"]
        )
        dc.SetBackground(wx.Brush(outside))
        dc.Clear()
        graphics = wx.GraphicsContext.Create(dc)
        if graphics is None:
            return
        width, height = self.GetClientSize()
        graphics.SetBrush(wx.Brush(palette["surface_container"]))
        graphics.SetPen(wx.Pen(palette["outline_variant"], 1))
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
        text_alignment: str = "center",
    ) -> None:
        if variant not in self._VARIANTS:
            raise ValueError(f"Unknown Material button variant: {variant}")
        if text_alignment not in {"left", "center"}:
            raise ValueError(
                "Material button text_alignment must be 'left' or 'center'"
            )
        super().__init__(
            parent, name=name or label, style=wx.BORDER_NONE | wx.WANTS_CHARS
        )
        self._material3_surface_role = "surface_container"
        self._name_tracks_label = name is None
        wx.Control.SetLabel(self, label)
        self.variant = variant
        self.text_alignment = text_alignment
        self._hovered = False
        self._pressed = False
        self._keyboard_armed: int | None = None
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
        self.Bind(wx.EVT_MOUSE_CAPTURE_LOST, self._capture_lost)
        self.Bind(wx.EVT_KEY_DOWN, self._key_down)
        self.Bind(wx.EVT_KEY_UP, self._key_up)
        self.Bind(wx.EVT_SET_FOCUS, self._focus_changed)
        self.Bind(wx.EVT_KILL_FOCUS, self._focus_changed)

    def SetLabel(self, label: str) -> None:  # noqa: N802 - wx API spelling
        wx.Control.SetLabel(self, label)
        if self._name_tracks_label:
            self.SetName(label)
        self.InvalidateBestSize()
        self.SetMinSize(self.DoGetBestSize())
        parent = self.GetParent()
        if parent is not None:
            parent.Layout()
        self.Refresh()

    def Enable(self, enable: bool = True) -> bool:  # noqa: N802 - wx API spelling
        if not enable:
            self._cancel_press(release_capture=True)
        changed = super().Enable(enable)
        self.SetCursor(wx.Cursor(wx.CURSOR_HAND if enable else wx.CURSOR_ARROW))
        self.Refresh()
        return changed

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        dc = wx.ClientDC(self)
        dc.SetFont(self.GetFont())
        width, height = dc.GetTextExtent(self.GetLabel() or " ")
        horizontal = 32 if self.text_alignment == "left" else 48
        return wx.Size(
            max(96, width + horizontal),
            _control_min_height(natural_height=height + 20),
        )

    def _enter(self, event: wx.MouseEvent) -> None:
        self._hovered = True
        self.Refresh()
        event.Skip()

    def _leave(self, event: wx.MouseEvent) -> None:
        self._hovered = False
        if not self.HasCapture() and self._keyboard_armed is None:
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
        was_pressed = self._pressed and self.IsEnabled()
        inside = self.GetClientRect().Contains(event.GetPosition())
        self._cancel_press(release_capture=True)
        if was_pressed and inside:
            self._emit_button()
        event.Skip()

    def _capture_lost(self, event: wx.MouseCaptureLostEvent) -> None:
        self._cancel_press(release_capture=False)
        event.Skip()

    def _key_down(self, event: wx.KeyEvent) -> None:
        key = event.GetKeyCode()
        if self.IsEnabled() and key in (wx.WXK_RETURN, wx.WXK_SPACE):
            # Arm once and activate on key-up.  Holding Space/Return no longer
            # emits an unbounded stream of commands through key auto-repeat.
            if self._keyboard_armed is None:
                self._keyboard_armed = key
                self._pressed = True
                self.Refresh()
            return
        event.Skip()

    def _key_up(self, event: wx.KeyEvent) -> None:
        key = event.GetKeyCode()
        if self._keyboard_armed == key:
            activate = self.IsEnabled()
            self._cancel_press(release_capture=False)
            if activate:
                self._emit_button()
            return
        event.Skip()

    def _focus_changed(self, event: wx.FocusEvent) -> None:
        if not self.HasFocus() and self._keyboard_armed is not None:
            self._cancel_press(release_capture=False)
        self.Refresh()
        event.Skip()

    def _cancel_press(self, *, release_capture: bool) -> None:
        self._pressed = False
        self._keyboard_armed = None
        if release_capture and self.HasCapture():
            self.ReleaseMouse()
        self.Refresh()

    def _emit_button(self) -> None:
        event = wx.CommandEvent(wx.EVT_BUTTON.typeId, self.GetId())
        event.SetEventObject(self)
        self.GetEventHandler().ProcessEvent(event)

    def _roles(self) -> tuple[wx.Colour, wx.Colour, wx.Colour | None]:
        palette = _active_palette()
        if not self.IsEnabled():
            return (
                palette["disabled_container"],
                palette["on_disabled"],
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
                palette["secondary_container"],
                palette["on_secondary_container"],
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
        parent = self.GetParent()
        outside = (
            parent.GetBackgroundColour()
            if parent is not None
            else palette["surface_container"]
        )
        dc.SetBackground(wx.Brush(outside))
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
        text_x = 16 if self.text_alignment == "left" else (width - text_width) / 2
        graphics.DrawText(
            self.GetLabel(),
            max(8, text_x),
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
        self._keyboard_armed: int | None = None
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
        self.Bind(wx.EVT_MOUSE_CAPTURE_LOST, self._capture_lost)
        self.Bind(wx.EVT_KEY_DOWN, self._key_down)
        self.Bind(wx.EVT_KEY_UP, self._key_up)
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
        if not self.HasCapture() and self._keyboard_armed is None:
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
        was_pressed = self._pressed and self.IsEnabled()
        inside = self.GetClientRect().Contains(event.GetPosition())
        self._cancel_press(release_capture=True)
        if was_pressed and inside:
            self._emit_button()
        event.Skip()

    def _capture_lost(self, event: wx.MouseCaptureLostEvent) -> None:
        self._cancel_press(release_capture=False)
        event.Skip()

    def _key_down(self, event: wx.KeyEvent) -> None:
        key = event.GetKeyCode()
        if self.IsEnabled() and key in (wx.WXK_RETURN, wx.WXK_SPACE):
            if self._keyboard_armed is None:
                self._keyboard_armed = key
                self._pressed = True
                self.Refresh()
            return
        event.Skip()

    def _key_up(self, event: wx.KeyEvent) -> None:
        key = event.GetKeyCode()
        if self._keyboard_armed == key:
            activate = self.IsEnabled()
            self._cancel_press(release_capture=False)
            if activate:
                self._emit_button()
            return
        event.Skip()

    def _focus_changed(self, event: wx.FocusEvent) -> None:
        if not self.HasFocus() and self._keyboard_armed is not None:
            self._cancel_press(release_capture=False)
        self.Refresh()
        event.Skip()

    def _cancel_press(self, *, release_capture: bool) -> None:
        self._pressed = False
        self._keyboard_armed = None
        if release_capture and self.HasCapture():
            self.ReleaseMouse()
        self.Refresh()

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


class MaterialSearchField(wx.Panel):
    """Outlined M3 search field with a native text editor and custom surface."""

    def __init__(
        self,
        parent: wx.Window,
        *,
        hint: str = "Search commands",
        name: str = "Material menu search",
    ) -> None:
        super().__init__(parent, name=name)
        self._material3_surface_role = "surface_container_high"
        self._material3_appearance_menu_disabled = True
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.text = wx.TextCtrl(
            self,
            style=wx.BORDER_NONE | wx.TE_PROCESS_ENTER,
            name=name,
        )
        self.text._material3_appearance_menu_disabled = True
        self.text.SetHint(hint)
        self.text.SetFont(_font_for(self.text, 10))
        root = wx.BoxSizer(wx.HORIZONTAL)
        root.Add(self.text, 1, wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.RIGHT, 14)
        self.SetSizer(root)
        self.SetMinSize(wx.Size(260, _control_min_height(natural_height=48)))
        self.Bind(wx.EVT_PAINT, self._paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.text.Bind(wx.EVT_SET_FOCUS, self._focus_changed)
        self.text.Bind(wx.EVT_KILL_FOCUS, self._focus_changed)

    def GetValue(self) -> str:  # noqa: N802 - wx API spelling
        return self.text.GetValue()

    def SetValue(self, value: str) -> None:  # noqa: N802 - wx API spelling
        self.text.SetValue(value)

    def SetFocus(self) -> None:  # noqa: N802 - wx API spelling
        self.text.SetFocus()

    def _focus_changed(self, event: wx.FocusEvent) -> None:
        self.Refresh()
        event.Skip()

    def _paint(self, _event: wx.PaintEvent) -> None:
        palette = _active_palette()
        dc = wx.AutoBufferedPaintDC(self)
        parent = self.GetParent()
        outside = (
            parent.GetBackgroundColour()
            if parent is not None
            else palette["surface_container"]
        )
        dc.SetBackground(wx.Brush(outside))
        dc.Clear()
        graphics = wx.GraphicsContext.Create(dc)
        if graphics is None:
            return
        width, height = self.GetClientSize()
        graphics.SetBrush(wx.Brush(palette["surface_container_high"]))
        graphics.SetPen(
            wx.Pen(
                palette["primary"] if self.text.HasFocus() else palette["outline"],
                2 if self.text.HasFocus() else 1,
            )
        )
        graphics.DrawRoundedRectangle(
            1,
            1,
            max(0, width - 2),
            max(0, height - 2),
            max(12, height / 2),
        )


class MaterialMenu(wx.PopupTransientWindow):
    """Searchable owner-drawn M3 popup replacing native ``wx.Menu`` surfaces."""

    def __init__(
        self,
        parent: wx.Window,
        *,
        title: str,
        items: Iterable[MaterialMenuItem],
    ) -> None:
        popup_style = wx.BORDER_NONE | getattr(wx, "PU_CONTAINS_CONTROLS", 0)
        super().__init__(parent, popup_style)
        self.SetName(f"{title} menu")
        self._material3_surface_role = "surface_container"
        self._material3_appearance_menu_disabled = True
        self._title = str(title)
        self._items = tuple(items)
        self._visible: tuple[MaterialMenuItem, ...] = ()
        self._buttons: list[MaterialButton] = []
        self._selection = MenuSelection()
        self._anchor: wx.Window | None = None

        self._card = MaterialCard(self, name=f"{title} menu card")
        self._card._material3_appearance_menu_disabled = True
        card_sizer = wx.BoxSizer(wx.VERTICAL)
        heading = wx.StaticText(self._card, label=self._title, name="Menu heading")
        heading._material3_appearance_menu_disabled = True
        heading.SetFont(_font_for(heading, 12, wx.FONTWEIGHT_MEDIUM))
        card_sizer.Add(heading, 0, wx.LEFT | wx.RIGHT | wx.TOP | wx.EXPAND, 16)

        self._search = MaterialSearchField(self._card)
        card_sizer.Add(self._search, 0, wx.ALL | wx.EXPAND, 12)

        self._scroll = wx.ScrolledWindow(
            self._card,
            style=wx.VSCROLL | wx.BORDER_NONE,
            name="Material menu commands",
        )
        self._scroll._material3_surface_role = "surface_container"
        self._scroll._material3_appearance_menu_disabled = True
        self._scroll.SetScrollRate(0, 12)
        self._buttons_sizer = wx.BoxSizer(wx.VERTICAL)
        self._scroll.SetSizer(self._buttons_sizer)
        card_sizer.Add(self._scroll, 1, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        self._empty = wx.StaticText(
            self._card,
            label="No matching commands",
            name="Empty menu result",
        )
        self._empty._material3_appearance_menu_disabled = True
        card_sizer.Add(self._empty, 0, wx.ALL | wx.EXPAND, 16)
        self._card.SetSizer(card_sizer)

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(self._card, 1, wx.EXPAND)
        self.SetSizer(outer)

        self._search.text.Bind(wx.EVT_TEXT, self._on_query)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
        self._rebuild("")
        apply_material3(self)

    def show_for(self, anchor: wx.Window) -> None:
        anchor_top = anchor.ClientToScreen(wx.Point(0, 0))
        point = wx.Point(anchor_top.x, anchor_top.y + anchor.GetClientSize().height)
        self._show_at(anchor, point, above_y=anchor_top.y)

    def show_at(self, anchor: wx.Window, screen_position: wx.Point) -> None:
        self._show_at(anchor, screen_position, above_y=screen_position.y)

    def _show_at(
        self, anchor: wx.Window, screen_position: wx.Point, *, above_y: int
    ) -> None:
        self._anchor = anchor
        self._search.text.ChangeValue("")
        self._rebuild("")
        self.Layout()
        self._card.Layout()
        self._scroll.FitInside()
        best = self.GetBestSize()

        display_index = wx.Display.GetFromPoint(screen_position)
        if display_index == wx.NOT_FOUND:
            display_index = wx.Display.GetFromWindow(anchor)
        if display_index == wx.NOT_FOUND:
            display_index = 0
        area = wx.Display(display_index).GetClientArea()
        command_content_height = (
            max(0, self._buttons_sizer.GetMinSize().height) if self._visible else 0
        )
        # A scrolled window's best size describes its native viewport, not its
        # virtual children.  On packaged Windows wx this was 24 px, so the
        # popup fitted the title/search chrome and clipped every command below
        # a scrollbar-width strip.  Separate the measured chrome from that
        # provisional viewport and explicitly reserve a bounded command area.
        provisional_viewport_height = max(0, self._scroll.GetSize().height)
        if self._visible and provisional_viewport_height <= 0:
            provisional_viewport_height = max(0, self._scroll.GetBestSize().height)
        chrome_height = max(0, best.height - provisional_viewport_height)
        viewport_layout = fit_menu_command_viewport(
            chrome_height=chrome_height,
            command_content_height=command_content_height,
            area_height=area.height,
        )
        scrollbar_width = (
            max(0, wx.SystemSettings.GetMetric(wx.SYS_VSCROLL_X, self))
            if command_content_height > viewport_layout.command_viewport_height
            else 0
        )
        width = min(max(320, best.width + scrollbar_width), min(520, area.width))
        height = viewport_layout.popup_height
        if self._visible:
            self._scroll.SetMinSize(
                wx.Size(300, viewport_layout.command_viewport_height)
            )
        x = min(max(area.x, screen_position.x), area.GetRight() - width + 1)
        if screen_position.y + height <= area.GetBottom() + 1:
            y = screen_position.y
        elif above_y - height >= area.y:
            y = above_y - height
        else:
            y = area.GetBottom() - height + 1
        y = min(max(area.y, y), area.GetBottom() - height + 1)
        self.SetSize(wx.Size(width, height))
        self.SetPosition(wx.Point(x, y))
        self.Layout()
        self._card.Layout()
        self._scroll.Layout()
        self._scroll.FitInside()
        self.Popup(self._search.text)
        wx.CallAfter(self._search.SetFocus)

    def Dismiss(self) -> None:  # noqa: N802 - wx API spelling
        # Explicit dismissals (Escape or activation) return focus to the menu
        # anchor.  A transient click-away goes through OnDismiss instead and
        # keeps focus on the newly clicked control.
        anchor = self._anchor
        super().Dismiss()
        self._reset_dismissed_state()
        if anchor is not None:
            wx.CallAfter(self._restore_focus_if_live, anchor)

    def OnDismiss(self) -> None:  # noqa: N802 - wx API spelling
        self._reset_dismissed_state()

    @staticmethod
    def _restore_focus_if_live(anchor: wx.Window) -> None:
        try:
            if not anchor.IsBeingDeleted() and anchor.IsEnabled():
                anchor.SetFocus()
        except RuntimeError as error:
            if not _is_deleted_wrapped_object_error(error):
                raise

    def _reset_dismissed_state(self) -> None:
        self._anchor = None
        self._selection.index = -1

    def _on_query(self, event: wx.CommandEvent) -> None:
        self._rebuild(event.GetString())
        event.Skip()

    def _rebuild(self, query: str) -> None:
        palette = _active_palette()
        self._visible = filter_menu_items(self._items, query)
        self._buttons_sizer.Clear(delete_windows=True)
        self._buttons = []
        previous_section: str | None = None
        for index, item in enumerate(self._visible):
            if item.section and item.section != previous_section:
                section = wx.StaticText(
                    self._scroll,
                    label=item.section,
                    name=f"{item.section} menu section",
                )
                section._material3_appearance_menu_disabled = True
                section.SetFont(_font_for(section, 9, wx.FONTWEIGHT_MEDIUM))
                section.SetForegroundColour(palette["on_surface_variant"])
                section.SetBackgroundColour(palette["surface_container"])
                self._buttons_sizer.Add(
                    section, 0, wx.LEFT | wx.RIGHT | wx.TOP | wx.EXPAND, 12
                )
            previous_section = item.section
            display_label = (
                f"{item.label}    {item.shortcut}" if item.shortcut else item.label
            )
            button = MaterialButton(
                self._scroll,
                display_label,
                variant="text",
                name=f"{item.label} command",
                text_alignment="left",
            )
            button._material3_appearance_menu_disabled = True
            button.Enable(item.enabled)
            tooltip = item.description
            if item.shortcut:
                tooltip = f"{tooltip} ({item.shortcut})" if tooltip else item.shortcut
            if tooltip:
                button.SetToolTip(tooltip)
            button.SetMinSize(wx.Size(300, max(40, button.GetBestSize().height)))
            button.Bind(
                wx.EVT_BUTTON,
                lambda _event, selected=item: self._activate(selected),
            )
            button.Bind(wx.EVT_KEY_DOWN, self._on_button_key)
            self._buttons_sizer.Add(button, 0, wx.EXPAND | wx.TOP, 2)
            self._buttons.append(button)

        self._empty.Show(not self._visible)
        self._scroll.Show(bool(self._visible))
        enabled = tuple(item.enabled for item in self._visible)
        self._selection.reset(enabled)
        self._scroll.Layout()
        self._scroll.FitInside()
        self._scroll.Scroll(0, 0)
        self._card.Layout()
        self.Layout()
        self.SendSizeEvent()

    def _on_button_key(self, event: wx.KeyEvent) -> None:
        key = event.GetKeyCode()
        if key in (wx.WXK_UP, wx.WXK_DOWN, wx.WXK_HOME, wx.WXK_END):
            if key == wx.WXK_HOME:
                self._selection.index = -1
                self._selection.move(1, tuple(item.enabled for item in self._visible))
            elif key == wx.WXK_END:
                self._selection.index = -1
                self._selection.move(-1, tuple(item.enabled for item in self._visible))
            else:
                self._move_selection(1 if key == wx.WXK_DOWN else -1)
            self._focus_selection()
            return
        event.Skip()

    def _on_char_hook(self, event: wx.KeyEvent) -> None:
        key = event.GetKeyCode()
        if key == wx.WXK_ESCAPE:
            self.Dismiss()
            return
        if key in (wx.WXK_UP, wx.WXK_DOWN):
            # The first arrow press from the search field enters the command
            # list at its nearest edge instead of skipping the first item.
            if wx.Window.FindFocus() is self._search.text:
                self._selection.index = -1
            self._move_selection(1 if key == wx.WXK_DOWN else -1)
            self._focus_selection()
            return
        if key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            focus = wx.Window.FindFocus()
            if focus is self._search.text and 0 <= self._selection.index < len(
                self._visible
            ):
                self._activate(self._visible[self._selection.index])
                return
        event.Skip()

    def _move_selection(self, delta: int) -> None:
        enabled = tuple(item.enabled for item in self._visible)
        self._selection.move(delta, enabled)

    def _focus_selection(self) -> None:
        index = self._selection.clamp(tuple(item.enabled for item in self._visible))
        if 0 <= index < len(self._buttons):
            self._buttons[index].SetFocus()

    def _activate(self, item: MaterialMenuItem) -> None:
        if not item.enabled:
            return
        event_object = self._anchor or self
        self.Dismiss()
        identifier = item.identifier if item.identifier >= 0 else wx.ID_ANY
        event = wx.CommandEvent(wx.EVT_MENU.typeId, identifier)
        event.SetEventObject(event_object)
        wx.CallAfter(item.callback, event)


__all__ = [
    "MaterialButton",
    "MaterialCard",
    "MaterialMenu",
    "MaterialSearchField",
    "MaterialWindowButton",
]
