"""The Amulet Studio title bar: the frame's own chrome, drawn by the shell.

The desktop frame is borderless, so this strip is the window's title bar in the
literal sense -- it carries the project name, the honest saved state, the three
document commands, the command-palette affordance, the notification badge, and
the minimise, maximise, and close buttons, and it is what the user grabs to move
the window.

It replaces :class:`amulet_map_editor.api.wx.title_bar.MaterialTitleBar` for the
main frame while keeping that class's behaviour: dragging the empty area moves
the frame, double-clicking toggles maximise, and the window buttons act on the
real top-level window.  The older bar is left in place because other dialogs
still use it.

Every control here is painted rather than native.  The design asks for a
40-pixel strip holding 28-pixel controls, a pill with two typefaces in it, and a
close button that turns red under the pointer; none of those are shapes wx can
produce from a stock button, and approximating them per surface is how a shell
ends up looking like several products at once.

Every string on this bar is a control label rather than a message, so all of
them go through :func:`~amulet_map_editor.api.studio.copy.studio_label`, which
applies the language mode and never the funny level.  The bar is the strongest
case for that split: at level five the palette pill read "Tell me what to do
(the code is dancing; the facts stay put)" in a 40-pixel strip, which both
stopped being a name and pushed the window buttons off the edge.  Nothing here
speaks to the reader, so nothing here takes tone.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional, Tuple

import wx

from amulet_map_editor.api import notifications
from amulet_map_editor.api.studio import tokens, widgets
from amulet_map_editor.api.studio.copy import studio_label

log = logging.getLogger(__name__)

#: Geometry transcribed from the design's title-bar markup, in design pixels.
#: Every one of them is passed through :func:`tokens.scaled` before it reaches a
#: window, so the bar grows with the interface scale instead of clipping.
BAR_HEIGHT = 40
BAR_PADDING_LEFT = 14
BAR_PADDING_RIGHT = 6
BAR_GAP = 8
MARK_SIZE = 18
MARK_RADIUS = 5
CONTROL_HEIGHT = 28
CONTROL_RADIUS = 7
ICON_WIDTH = 30
NOTIFICATION_WIDTH = 32
WINDOW_BUTTON_WIDTH = 38
DIVIDER_HEIGHT = 18
BADGE_SIZE = 14

#: The close button's hover colour.  It is the design's own literal rather than
#: the palette's ``error`` role: a title-bar close button is the one control
#: whose hover colour users read as "this shuts the window", and matching the
#: platform convention matters more here than matching the accent.
CLOSE_HOVER_FILL = "#B3261E"
CLOSE_HOVER_INK = "#FFFFFF"

#: The keyboard chord that opens the command palette, as an accelerator pair.
PALETTE_ACCELERATOR: Tuple[int, int] = (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("F"))

#: wxPython 4.1 added a medium weight; older builds fall back to normal rather
#: than raising while the bar is being constructed.
_MEDIUM = getattr(wx, "FONTWEIGHT_MEDIUM", wx.FONTWEIGHT_NORMAL)


def single_line(text: str) -> str:
    """Fold a bilingual two-line string onto one line for a 40-pixel strip.

    :func:`~amulet_map_editor.api.studio.copy.studio_label` and its message
    counterpart both return the English above the Cantonese so a roomy surface
    can render a prominent label over a compact one.  The title bar has no
    second line to give, so the two are joined with a separator instead:
    crowding is a layout problem, but dropping the Cantonese would silently turn
    bilingual mode back into English.
    """
    parts = [part.strip() for part in str(text).split("\n") if part.strip()]
    return " · ".join(parts)


def unread_notification_count() -> int:
    """Return how many notifications the user has not dismissed.

    An unreadable or malformed notification store must not stop the title bar
    painting, so the failure is logged and the badge simply reads zero rather
    than claiming a number nobody can verify.
    """
    try:
        return len(notifications.list_notifications(include_dismissed=False))
    except Exception:
        log.exception("Could not read the notification history for the unread badge")
        return 0


class _BarControl(wx.Control):
    """Shared painting, hover, focus, and activation for one title-bar control.

    The title bar deliberately does not reuse
    :class:`~amulet_map_editor.api.studio.widgets.StudioButton`: three of these
    controls need a shape it cannot draw (a two-typeface pill, an overlaid
    unread badge, and a close button with its own hover colour), and having two
    of the five drawn one way and three another is how a strip this small stops
    looking like one bar.  The metrics match the shared button's ``icon`` and
    ``pill`` variants exactly, so the bar and the rest of the shell still agree.
    """

    def __init__(
        self,
        parent: wx.Window,
        *,
        name: str,
        width: int,
        height: int = CONTROL_HEIGHT,
        on_click: Optional[Callable[[], None]] = None,
        hint: str = "",
        focusable: bool = True,
    ) -> None:
        style = wx.BORDER_NONE
        if focusable:
            style |= wx.WANTS_CHARS
        self._focusable = bool(focusable)
        super().__init__(parent, style=style)
        self.design_width = int(width)
        self.design_height = int(height)
        self.on_click = on_click
        self.hint = str(hint)
        self.radius = CONTROL_RADIUS
        self._hovered = False
        self._pressed = False
        self.SetName(name)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        if self.hint:
            self.SetToolTip(self.hint)
        if focusable:
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
        self.SetInitialSize(self.DoGetBestSize())

    # -- geometry ------------------------------------------------------------
    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        return wx.Size(
            tokens.scaled(self.design_width), tokens.scaled(self.design_height)
        )

    def AcceptsFocus(self) -> bool:  # noqa: N802 - wx API spelling
        return getattr(self, "_focusable", True) and self.IsEnabled()

    def AcceptsFocusFromKeyboard(self) -> bool:  # noqa: N802 - wx API spelling
        return self.AcceptsFocus()

    def corner_radius(self) -> int:
        """Return the corner radius this control paints with.

        A pill keeps the unscaled sentinel because the drawing helper clamps it
        to half the shorter edge; every other control scales its radius so a
        corner stays a corner at 200% interface scale.
        """
        return (
            self.radius
            if self.radius >= tokens.RADIUS_PILL
            else tokens.scaled(self.radius)
        )

    # -- interaction ---------------------------------------------------------
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
        if self._focusable and self.IsEnabled():
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

    def activate(self) -> None:
        """Run the control's action, from a click or from the keyboard."""
        if not self.IsEnabled():
            return
        widgets.invoke(self.on_click)
        command = wx.CommandEvent(wx.EVT_BUTTON.typeId, self.GetId())
        command.SetEventObject(self)
        self.GetEventHandler().ProcessEvent(command)

    # -- appearance ----------------------------------------------------------
    def hover_colours(
        self, palette: tokens.StudioPalette
    ) -> Tuple[wx.Colour, wx.Colour]:
        """Return the hover fill and hover ink for this control."""
        return palette.surface_container_high, palette.on_surface

    def resting_colours(
        self, palette: tokens.StudioPalette
    ) -> Tuple[Optional[wx.Colour], wx.Colour]:
        """Return the resting fill (or ``None``) and the resting ink."""
        return None, palette.on_surface_variant

    def _paint_content(
        self, dc: wx.DC, palette: tokens.StudioPalette, rect: wx.Rect, ink: wx.Colour
    ) -> None:
        """Draw whatever sits inside the control.  Subclasses override this."""

    def refresh_theme(self) -> None:
        """Repaint after the palette, density, or interface scale changed."""
        try:
            if self.IsBeingDeleted():
                return
        except RuntimeError:  # pragma: no cover - window already torn down
            return
        self.InvalidateBestSize()
        self.SetMinSize(self.DoGetBestSize())
        self.Refresh()

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        parent = self.GetParent()
        backdrop = parent.GetBackgroundColour() if parent else palette.surface
        if not backdrop.IsOk():
            backdrop = palette.surface_container
        dc, gcdc = widgets.paint_context(self, backdrop)
        width, height = self.GetClientSize()
        rect = wx.Rect(0, 0, width, height)
        fill, ink = self.resting_colours(palette)
        reacts = self._focusable and self.IsEnabled()
        if reacts and (self._hovered or self._pressed):
            fill, ink = self.hover_colours(palette)
            if self._pressed:
                fill = tokens.blend(fill, palette.on_surface, 0.10)
        if not self.IsEnabled():
            ink = tokens.blend(ink, backdrop, 0.45)
        radius = self.corner_radius()
        if fill is not None:
            tokens.draw_round_rect(gcdc, rect, radius, fill)
        self._paint_content(gcdc, palette, rect, ink)
        if self.HasFocus():
            widgets.draw_focus_ring(gcdc, rect, radius, palette.primary)
        del gcdc


class _AppMark(_BarControl):
    """The 18-pixel rounded primary square that opens the bar.

    It is decoration rather than a control, so it never takes focus and never
    claims a keyboard route the user would then find does nothing.
    """

    def __init__(self, parent: wx.Window) -> None:
        super().__init__(
            parent,
            name="Amulet Studio",
            width=MARK_SIZE,
            height=MARK_SIZE,
            focusable=False,
        )

    def resting_colours(
        self, palette: tokens.StudioPalette
    ) -> Tuple[Optional[wx.Colour], wx.Colour]:
        return None, palette.primary

    def hover_colours(
        self, palette: tokens.StudioPalette
    ) -> Tuple[wx.Colour, wx.Colour]:
        return palette.surface_container, palette.primary

    def _paint_content(
        self, dc: wx.DC, palette: tokens.StudioPalette, rect: wx.Rect, ink: wx.Colour
    ) -> None:
        tokens.draw_round_rect(dc, rect, tokens.scaled(MARK_RADIUS), palette.primary)


class _GlyphButton(_BarControl):
    """One title-bar icon button: a glyph, a tooltip, and a real action."""

    def __init__(
        self,
        parent: wx.Window,
        glyph: str,
        *,
        name: str,
        hint: str,
        width: int = ICON_WIDTH,
        glyph_px: int = 13,
        on_click: Optional[Callable[[], None]] = None,
    ) -> None:
        self.glyph = str(glyph)
        self.glyph_px = int(glyph_px)
        super().__init__(parent, name=name, width=width, hint=hint, on_click=on_click)

    def set_glyph(self, glyph: str) -> None:
        """Replace the drawn glyph, for a button whose state changed."""
        self.glyph = str(glyph)
        self.Refresh()

    def describe(self, name: str, hint: str) -> None:
        """Replace the accessible name and the tooltip together.

        They are set in one call on purpose: a maximise button that has become
        a restore button and only updated one of the two tells a sighted user
        one thing and a screen-reader user another.
        """
        self.SetName(name)
        self.SetToolTip(hint)
        self.hint = hint

    def _paint_content(
        self, dc: wx.DC, palette: tokens.StudioPalette, rect: wx.Rect, ink: wx.Colour
    ) -> None:
        if not self.glyph:
            return
        dc.SetFont(tokens.font(self, widgets.point_size(self.glyph_px)))
        dc.SetTextForeground(ink)
        glyph_width, glyph_height = dc.GetTextExtent(self.glyph)
        dc.DrawText(
            self.glyph,
            rect.x + (rect.width - glyph_width) // 2,
            rect.y + (rect.height - glyph_height) // 2,
        )


class _CloseButton(_GlyphButton):
    """The window close button, which turns red under the pointer."""

    def hover_colours(
        self, palette: tokens.StudioPalette
    ) -> Tuple[wx.Colour, wx.Colour]:
        return (
            widgets.colour_of(CLOSE_HOVER_FILL),
            widgets.colour_of(CLOSE_HOVER_INK),
        )


class _NotificationButton(_GlyphButton):
    """The notifications button and the unread count riding on top of it.

    The badge is painted rather than added as a child window because it has to
    overlap the glyph; the count is also folded into the accessible name, so a
    screen reader reports "3 unread" instead of announcing a bell nobody can
    see the number on.
    """

    def __init__(
        self,
        parent: wx.Window,
        *,
        hint: str,
        on_click: Optional[Callable[[], None]] = None,
    ) -> None:
        self.unread = 0
        self._base_hint = hint
        super().__init__(
            parent,
            "◉",
            name="Notifications",
            hint=hint,
            width=NOTIFICATION_WIDTH,
            on_click=on_click,
        )
        self.set_unread(0)

    def set_unread(self, count: int) -> None:
        """Set the unread count, its badge, and its accessible name."""
        self.unread = max(0, int(count))
        if self.unread:
            plural = "notification" if self.unread == 1 else "notifications"
            name = f"Notifications, {self.unread} unread {plural}"
        else:
            name = "Notifications, none unread"
        self.SetName(name)
        self.SetToolTip(f"{self._base_hint}\n{name}")
        self.Refresh()

    def badge_text(self) -> str:
        """Return the number drawn in the badge, capped so it still fits."""
        if self.unread <= 0:
            return ""
        return "99+" if self.unread > 99 else str(self.unread)

    def _paint_content(
        self, dc: wx.DC, palette: tokens.StudioPalette, rect: wx.Rect, ink: wx.Colour
    ) -> None:
        super()._paint_content(dc, palette, rect, ink)
        text = self.badge_text()
        if not text:
            return
        dc.SetFont(tokens.font(self, widgets.point_size(9), _MEDIUM))
        text_width, text_height = dc.GetTextExtent(text)
        diameter = max(tokens.scaled(BADGE_SIZE), text_width + tokens.scaled(6))
        badge = wx.Rect(
            rect.GetRight() - diameter + tokens.scaled(2),
            rect.y + tokens.scaled(1),
            diameter,
            tokens.scaled(BADGE_SIZE),
        )
        tokens.draw_round_rect(dc, badge, badge.height // 2, palette.error)
        dc.SetTextForeground(tokens.on_colour(palette.error))
        dc.DrawText(
            text,
            badge.x + (badge.width - text_width) // 2,
            badge.y + (badge.height - text_height) // 2,
        )


class _ShortcutPill(_BarControl):
    """The "Tell me what to do" pill with its accelerator set in mono type.

    Two typefaces on one control is why this is painted: the label is the
    interface face and the chord beside it is the monospaced one in the primary
    colour, exactly as the design draws it, so the chord reads as something you
    press rather than as part of the sentence.
    """

    LABEL_PX = 12
    ACCEL_PX = 10
    GAP = 10
    PADDING_LEFT = 12
    PADDING_RIGHT = 10

    def __init__(
        self,
        parent: wx.Window,
        label: str,
        accelerator: str,
        *,
        hint: str = "",
        on_click: Optional[Callable[[], None]] = None,
    ) -> None:
        self.label = single_line(label)
        self.accelerator = str(accelerator)
        super().__init__(
            parent,
            name=f"{self.label} ({self.accelerator})",
            width=0,
            hint=hint or f"{self.label} — {self.accelerator}",
            on_click=on_click,
        )
        self.radius = tokens.RADIUS_PILL
        self.SetInitialSize(self.DoGetBestSize())

    def set_label(self, label: str) -> None:
        """Replace the visible label, its accessible name, and the width."""
        self.label = single_line(label)
        self.SetName(f"{self.label} ({self.accelerator})")
        self.InvalidateBestSize()
        self.SetMinSize(self.DoGetBestSize())
        self.Refresh()

    def _fonts(self) -> Tuple[wx.Font, wx.Font]:
        return (
            tokens.font(self, widgets.point_size(self.LABEL_PX)),
            tokens.mono_font(self, widgets.point_size(self.ACCEL_PX)),
        )

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        """Return the width this pill needs, measured the way it is drawn.

        The measurement has to go through a ``wx.GCDC`` because that is what
        :meth:`_paint_content` draws with, and the two contexts do not agree:
        GDI+ returns this label two pixels wider than GDI and the chord three
        wider.  Measured with the plain context the control came out five pixels
        narrower than its own text, so the paint handler elided every single
        time -- the pill read "Tell me what to …" at funny level one as well as
        five, in every language, which looks exactly like a clipped interface
        and is really two device contexts disagreeing about one string.
        """
        client = wx.ClientDC(self)
        try:
            dc: wx.DC = wx.GCDC(client)
        except TypeError:  # pragma: no cover - platform without a graphics context
            dc = client
        label_font, accel_font = self._fonts()
        dc.SetFont(label_font)
        label_width = dc.GetTextExtent(self.label)[0]
        dc.SetFont(accel_font)
        accel_width = dc.GetTextExtent(self.accelerator)[0]
        if dc is not client:
            del dc
        width = (
            tokens.scaled(self.PADDING_LEFT)
            + label_width
            + tokens.scaled(self.GAP)
            + accel_width
            + tokens.scaled(self.PADDING_RIGHT)
        )
        return wx.Size(width, tokens.scaled(self.design_height))

    def resting_colours(
        self, palette: tokens.StudioPalette
    ) -> Tuple[Optional[wx.Colour], wx.Colour]:
        return palette.surface, palette.on_surface_variant

    def _paint_content(
        self, dc: wx.DC, palette: tokens.StudioPalette, rect: wx.Rect, ink: wx.Colour
    ) -> None:
        tokens.draw_round_rect(
            dc,
            rect,
            tokens.RADIUS_PILL,
            None,
            palette.outline_variant,
        )
        label_font, accel_font = self._fonts()
        dc.SetFont(accel_font)
        accel_width, accel_height = dc.GetTextExtent(self.accelerator)
        dc.SetFont(label_font)
        available = max(
            0,
            rect.width
            - tokens.scaled(self.PADDING_LEFT)
            - tokens.scaled(self.PADDING_RIGHT)
            - tokens.scaled(self.GAP)
            - accel_width,
        )
        label = widgets.elide(dc, self.label, available)
        label_width, label_height = dc.GetTextExtent(label)
        dc.SetTextForeground(ink)
        dc.DrawText(
            label,
            rect.x + tokens.scaled(self.PADDING_LEFT),
            rect.y + (rect.height - label_height) // 2,
        )
        dc.SetFont(accel_font)
        dc.SetTextForeground(palette.primary)
        dc.DrawText(
            self.accelerator,
            rect.GetRight() - tokens.scaled(self.PADDING_RIGHT) - accel_width + 1,
            rect.y + (rect.height - accel_height) // 2,
        )


class StudioTitleBar(wx.Panel):
    """The Studio's own title bar for a borderless top-level window.

    ``on_command``, ``on_surface``, and ``on_palette`` let the shell own what
    the buttons actually do.  When one is not supplied the bar looks for an
    ancestor that offers the matching method -- ``run_command``,
    ``open_surface``, ``open_palette`` -- so it works when the shell hosts it
    and still works when a test or a preview hosts it directly.  A command with
    nowhere to go leaves its button disabled with a tooltip naming exactly what
    is missing, rather than looking live and doing nothing.
    """

    #: Bar command keys, in the order they appear, with their glyph, accessible
    #: name, and tooltip source.  The keys are the shell's own command names.
    DOCUMENT_COMMANDS: Tuple[Tuple[str, str, str, str], ...] = (
        ("save", "▣", "Save project", "儲存呢個專案"),
        ("undo", "↶", "Undo", "還原"),
        ("redo", "↷", "Redo", "重做"),
    )

    def __init__(
        self,
        parent: wx.Window,
        frame: Optional[wx.TopLevelWindow] = None,
        *,
        title: str = "Untitled project",
        saved: bool = True,
        on_command: Optional[Callable[[str], None]] = None,
        on_surface: Optional[Callable[[str], Any]] = None,
        on_palette: Optional[Callable[[], Any]] = None,
    ) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        resolved = frame if frame is not None else parent.GetTopLevelParent()
        if not isinstance(resolved, wx.TopLevelWindow):
            raise TypeError(
                "StudioTitleBar needs a top-level window to move, maximise, and close."
            )
        self._frame: wx.TopLevelWindow = resolved
        self._on_command = on_command
        self._on_surface = on_surface
        self._on_palette = on_palette
        self._drag_origin: Optional[wx.Point] = None
        self._title = str(title)
        self._saved = bool(saved)
        self._theme_unsubscribe: Optional[Callable[[], None]] = None

        self.SetName("Studio title bar")
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetMinSize(wx.Size(-1, self.bar_height()))

        row = wx.BoxSizer(wx.HORIZONTAL)
        gap = tokens.scaled(BAR_GAP)

        self.mark = _AppMark(self)
        row.Add(
            self.mark,
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            tokens.scaled(BAR_PADDING_LEFT),
        )

        self.title_label = widgets.StudioText(
            self,
            self._title,
            size_px=13,
            weight=_MEDIUM,
            role="on_surface",
            ellipsize=True,
            name="Project title",
        )
        row.Add(self.title_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, gap)

        self.saved_label = widgets.StudioText(
            self,
            "",
            size_px=12,
            ellipsize=True,
            name="Save state",
        )
        row.Add(self.saved_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, gap)

        row.Add(
            self._divider(),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.RIGHT,
            tokens.scaled(BAR_GAP // 2),
        )

        self.command_buttons: Dict[str, _GlyphButton] = {}
        for key, glyph, english, cantonese in self.DOCUMENT_COMMANDS:
            hint = single_line(studio_label(english, cantonese))
            button = _GlyphButton(
                self,
                glyph,
                name=english,
                hint=hint,
                on_click=lambda command=key: self.run_command(command),
            )
            self.command_buttons[key] = button
            row.Add(
                button,
                0,
                wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
                tokens.scaled(tokens.SPACE_XS),
            )

        row.AddStretchSpacer(1)

        self.palette_button = _ShortcutPill(
            self,
            studio_label("Tell me what to do", "話我知你想做乜"),
            "Ctrl+Shift+F",
            hint=single_line(
                studio_label(
                    "Search every command, setting, and pane.",
                    "搵勻每個指令、設定同面板。",
                )
            ),
            on_click=self.open_palette,
        )
        row.Add(self.palette_button, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, gap)

        self.notifications_button = _NotificationButton(
            self,
            hint=single_line(studio_label("Notifications", "通知")),
            on_click=lambda: self.open_surface("notifications"),
        )
        row.Add(
            self.notifications_button,
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            tokens.scaled(tokens.SPACE_XS),
        )

        row.Add(
            self._divider(),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.RIGHT,
            tokens.scaled(2),
        )

        self.minimise_button = _GlyphButton(
            self,
            "—",
            name="Minimize window",
            hint=single_line(studio_label("Minimize window", "縮到最細")),
            width=WINDOW_BUTTON_WIDTH,
            glyph_px=12,
            on_click=self.minimise,
        )
        row.Add(self.minimise_button, 0, wx.ALIGN_CENTER_VERTICAL)

        self.maximise_button = _GlyphButton(
            self,
            "□",
            name="Maximize window",
            hint=single_line(studio_label("Maximize window", "放到最大")),
            width=WINDOW_BUTTON_WIDTH,
            glyph_px=11,
            on_click=self.toggle_maximise,
        )
        row.Add(self.maximise_button, 0, wx.ALIGN_CENTER_VERTICAL)

        self.close_button = _CloseButton(
            self,
            "×",
            name="Close window",
            hint=single_line(studio_label("Close window", "閂咗個視窗")),
            width=WINDOW_BUTTON_WIDTH,
            glyph_px=14,
            on_click=self.close_window,
        )
        row.Add(
            self.close_button,
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            tokens.scaled(BAR_PADDING_RIGHT),
        )

        self.SetSizer(row)

        for surface in (self, self.mark, self.title_label, self.saved_label):
            surface.Bind(wx.EVT_LEFT_DOWN, self._drag_start)
            surface.Bind(wx.EVT_LEFT_UP, self._drag_end)
            surface.Bind(wx.EVT_MOTION, self._drag_move)
            surface.Bind(wx.EVT_LEFT_DCLICK, self._on_double_click)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.Bind(wx.EVT_MOUSE_CAPTURE_LOST, self._on_capture_lost)
        self.Bind(wx.EVT_WINDOW_DESTROY, self._on_destroy)
        self._frame.Bind(wx.EVT_MAXIMIZE, self._on_frame_state)
        self._frame.Bind(wx.EVT_SIZE, self._on_frame_state)

        if not self._has_themed_ancestor():
            self._theme_unsubscribe = tokens.register_theme_listener(self.refresh_theme)

        self.set_title(self._title)
        self.set_saved(self._saved)
        self.set_unread(None)
        self.sync_window_state()
        self.apply_theme()
        wx.CallAfter(self.sync_commands)

    # -- construction helpers -------------------------------------------------
    def _divider(self) -> widgets.Divider:
        """Build one of the bar's vertical hairlines at the design's height."""
        rule = widgets.Divider(self, vertical=True)
        rule.SetMinSize(
            wx.Size(max(1, tokens.scaled(1)), tokens.scaled(DIVIDER_HEIGHT))
        )
        return rule

    def _has_themed_ancestor(self) -> bool:
        """Return whether some ancestor already repaints this bar on a theme change.

        Registering a second listener would only repaint the bar twice; the
        check keeps a theme switch to one pass over each top-level surface.
        """
        parent = self.GetParent()
        while parent is not None:
            if callable(getattr(parent, "refresh_theme", None)):
                return True
            parent = parent.GetParent()
        return False

    def bar_height(self) -> int:
        """Return the strip's height, scaled and never shorter than its controls."""
        return max(
            tokens.scaled(BAR_HEIGHT),
            tokens.scaled(CONTROL_HEIGHT) + tokens.scaled(12),
        )

    # -- shell wiring ---------------------------------------------------------
    def _resolve(self, method: str) -> Optional[Callable[..., Any]]:
        """Find an ancestor that offers ``method``, or ``None``.

        The bar is built before the shell finishes wiring itself in some
        layouts, so the lookup happens per call rather than once at
        construction; a shell that appears later is found the next time a
        button is pressed.
        """
        window: Optional[wx.Window] = self.GetParent()
        while window is not None:
            candidate = getattr(window, method, None)
            if callable(candidate):
                return candidate
            window = window.GetParent()
        return None

    def command_handler(self) -> Optional[Callable[[str], Any]]:
        """Return whatever will run a document command, or ``None``."""
        return self._on_command or self._resolve("run_command")

    def sync_commands(self) -> None:
        """Enable or disable the document buttons against a live handler.

        A disabled button says which condition is unmet in its own tooltip; a
        greyed control with no explanation reads as broken rather than blocked.
        """
        try:
            handler = self.command_handler()
            for key, _glyph, english, cantonese in self.DOCUMENT_COMMANDS:
                button = self.command_buttons.get(key)
                if button is None:
                    continue
                hint = single_line(studio_label(english, cantonese))
                if handler is None:
                    button.Enable(False)
                    button.describe(
                        f"{english} (unavailable)",
                        f"{hint}\nNo project shell is connected to run this "
                        "command yet.",
                    )
                else:
                    button.Enable(True)
                    button.describe(english, hint)
        except RuntimeError:  # pragma: no cover - window torn down mid-callback
            return

    def run_command(self, key: str) -> None:
        """Route one document command to the shell that owns it."""
        handler = self.command_handler()
        if handler is None:
            self.sync_commands()
            return
        widgets.invoke(handler, key)

    def open_surface(self, key: str) -> Any:
        """Open a Studio surface, through the shell when one is connected."""
        handler = self._on_surface or self._resolve("open_surface")
        if handler is not None:
            return widgets.invoke(handler, key)
        try:
            from amulet_map_editor.api.studio import surfaces
        except ImportError:
            log.exception("The Studio surface registry is unavailable")
            return None
        return surfaces.open_surface(self, key)

    def open_palette(self) -> Any:
        """Open the command palette from the pill or from the accelerator."""
        handler = self._on_palette or self._resolve("open_palette")
        if handler is not None:
            return widgets.invoke(handler)
        from amulet_map_editor.api.studio import palette_dialog

        return palette_dialog.open_palette(self)

    # -- public state ---------------------------------------------------------
    def set_title(self, title: str) -> None:
        """Show the project's name, keeping the full text reachable.

        The label elides when the window is narrow, so the untruncated title
        stays in the tooltip and in the accessible name: a truncated name in a
        screen reader is a name nobody can act on.
        """
        self._title = str(title)
        self.title_label.SetLabel(self._title)
        self.title_label.SetName(f"Project title: {self._title}")
        self.title_label.SetToolTip(self._title)
        self.Layout()

    def set_saved(self, saved: bool) -> None:
        """Report whether the project's work is on disk.

        This never says "Saved" while something is not: the state is the one
        piece of the bar a user relies on before closing a window, and a
        cheerful label over unsaved work is worse than no label at all.
        """
        self._saved = bool(saved)
        text = single_line(
            studio_label("Saved", "已儲存")
            if self._saved
            else studio_label("Unsaved changes", "仲有嘢未儲存")
        )
        self.saved_label.SetLabel(text)
        self.saved_label.SetName(f"Save state: {text}")
        self.saved_label.SetToolTip(text)
        palette = tokens.palette()
        self.saved_label.SetForegroundColour(
            palette.on_surface_variant if self._saved else palette.primary
        )
        self.Layout()
        self.Refresh()

    def set_unread(self, count: Optional[int] = None) -> None:
        """Set the notification badge; ``None`` reads the live unread count."""
        self.notifications_button.set_unread(
            unread_notification_count() if count is None else int(count)
        )

    def is_saved(self) -> bool:
        """Return the saved state the bar is currently reporting."""
        return self._saved

    def title(self) -> str:
        """Return the project title the bar is currently showing."""
        return self._title

    # -- window state ---------------------------------------------------------
    def sync_window_state(self) -> None:
        """Match the maximise button to the frame's real state.

        The button is the only way to tell a maximised borderless frame from a
        merely large one, so it follows ``IsMaximized`` rather than a flag this
        bar keeps for itself and hopes stays true.
        """
        try:
            maximised = bool(self._frame.IsMaximized())
        except RuntimeError:  # pragma: no cover - frame already destroyed
            return
        if maximised:
            self.maximise_button.set_glyph("❐")
            self.maximise_button.describe(
                "Restore window",
                single_line(studio_label("Restore window", "還原視窗大細")),
            )
        else:
            self.maximise_button.set_glyph("□")
            self.maximise_button.describe(
                "Maximize window",
                single_line(studio_label("Maximize window", "放到最大")),
            )

    def _on_frame_state(self, event: wx.Event) -> None:
        self.sync_window_state()
        event.Skip()

    def minimise(self) -> None:
        """Iconise the frame this bar belongs to."""
        self._frame.Iconize(True)

    def toggle_maximise(self) -> None:
        """Maximise the frame, or restore it when it is already maximised."""
        self._frame.Maximize(not self._frame.IsMaximized())
        self.sync_window_state()

    def close_window(self) -> None:
        """Ask the frame to close, so unsaved-work protection still runs."""
        self._frame.Close()

    # -- dragging -------------------------------------------------------------
    def _on_double_click(self, event: wx.MouseEvent) -> None:
        self.toggle_maximise()
        event.Skip()

    def _drag_start(self, event: wx.MouseEvent) -> None:
        source = event.GetEventObject()
        position = event.GetPosition()
        if source is not self:
            position = self.ScreenToClient(source.ClientToScreen(position))
        self._drag_origin = position
        if not self.HasCapture():
            self.CaptureMouse()
        event.Skip()

    def _drag_end(self, event: wx.MouseEvent) -> None:
        if self.HasCapture():
            self.ReleaseMouse()
        self._drag_origin = None
        event.Skip()

    def _on_capture_lost(self, _event: wx.MouseCaptureLostEvent) -> None:
        self._drag_origin = None

    def _restore_under_pointer(self, pointer: wx.Point) -> None:
        """Un-maximise so a dragged frame keeps following the pointer.

        Dragging a maximised window is how every desktop restores it, and the
        restored frame has to arrive under the pointer rather than jumping to
        wherever it happened to be last: the grab point is kept as a fraction
        of the bar's width and reapplied to the restored width.
        """
        width = max(1, self.GetClientSize().width)
        fraction = min(1.0, max(0.0, pointer.x / width))
        screen = self.ClientToScreen(pointer)
        self._frame.Restore()
        restored = self._frame.GetSize().width
        self._frame.Move(
            round(screen.x - fraction * restored),
            round(screen.y - pointer.y),
        )
        self._drag_origin = wx.Point(round(fraction * restored), pointer.y)
        self.sync_window_state()

    def _drag_move(self, event: wx.MouseEvent) -> None:
        if self._drag_origin is None or not event.Dragging() or not event.LeftIsDown():
            event.Skip()
            return
        source = event.GetEventObject()
        position = event.GetPosition()
        if source is not self:
            position = self.ScreenToClient(source.ClientToScreen(position))
        if self._frame.IsMaximized():
            self._restore_under_pointer(position)
            event.Skip()
            return
        screen_point = self.ClientToScreen(position)
        origin_screen = self.ClientToScreen(self._drag_origin)
        frame_position = self._frame.GetPosition()
        self._frame.Move(
            frame_position.x + screen_point.x - origin_screen.x,
            frame_position.y + screen_point.y - origin_screen.y,
        )
        event.Skip()

    # -- appearance -----------------------------------------------------------
    def apply_theme(self) -> None:
        """Push the live palette into the bar's labels and its own size.

        The two labels are owner-drawn and take their font from the tokens on
        every paint, so only the save state's ink is set here -- it is the one
        colour that follows the document rather than the theme.
        """
        palette = tokens.palette()
        self.SetBackgroundColour(palette.surface_container)
        self.SetMinSize(wx.Size(-1, self.bar_height()))
        self.saved_label.SetForegroundColour(
            palette.on_surface_variant if self._saved else palette.primary
        )

    def refresh_theme(self) -> None:
        """Re-read the tokens and repaint the bar and every control on it."""
        try:
            if self.IsBeingDeleted():
                return
            self.apply_theme()
            for child in self.GetChildren():
                refresh = getattr(child, "refresh_theme", None)
                if callable(refresh):
                    refresh()
            self.set_saved(self._saved)
            self.Layout()
            self.Refresh()
        except RuntimeError:
            # The window has already gone; the listener drops itself below.
            self._theme_unsubscribe = None

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        dc, gcdc = widgets.paint_context(self, palette.surface_container)
        width, height = self.GetClientSize()
        thickness = max(1, tokens.scaled(1))
        gcdc.SetPen(wx.TRANSPARENT_PEN)
        gcdc.SetBrush(wx.Brush(palette.outline_variant))
        gcdc.DrawRectangle(0, height - thickness, width, thickness)
        del gcdc

    # -- teardown -------------------------------------------------------------
    def _on_destroy(self, event: wx.WindowDestroyEvent) -> None:
        if event.GetEventObject() is self:
            if self._theme_unsubscribe is not None:
                self._theme_unsubscribe()
                self._theme_unsubscribe = None
            try:
                self._frame.Unbind(wx.EVT_MAXIMIZE, handler=self._on_frame_state)
                self._frame.Unbind(wx.EVT_SIZE, handler=self._on_frame_state)
            except RuntimeError:  # pragma: no cover - frame already destroyed
                pass
        event.Skip()


def install_palette_shortcut(
    window: wx.Window, opener: Optional[Callable[[], Any]] = None
) -> Callable[[], None]:
    """Make Ctrl+Shift+F open the command palette anywhere inside ``window``.

    The chord is bound as a character hook on the top-level window rather than
    through an accelerator table on purpose: an accelerator is swallowed by a
    focused text control, and "anywhere in the application" has to include the
    moment the user is typing in a field.  The returned callable removes the
    binding again.
    """
    target = window.GetTopLevelParent() or window

    def _on_char_hook(event: wx.KeyEvent) -> None:
        if (
            event.ControlDown()
            and event.ShiftDown()
            and not event.AltDown()
            and event.GetKeyCode() in (ord("F"), ord("f"))
        ):
            if opener is not None:
                widgets.invoke(opener)
            else:
                from amulet_map_editor.api.studio import palette_dialog

                palette_dialog.open_palette(target)
            return
        event.Skip()

    target.Bind(wx.EVT_CHAR_HOOK, _on_char_hook)
    return lambda: target.Unbind(wx.EVT_CHAR_HOOK, handler=_on_char_hook)


__all__ = [
    "BAR_HEIGHT",
    "CLOSE_HOVER_FILL",
    "CONTROL_HEIGHT",
    "PALETTE_ACCELERATOR",
    "StudioTitleBar",
    "install_palette_shortcut",
    "single_line",
    "unread_notification_count",
]
