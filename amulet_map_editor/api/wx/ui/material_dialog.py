"""The Material 3 scaffold every app-owned dialog in this package is built in.

Three of these dialogs -- the regex builder, the notification centre, and the
local history browser -- were the same window three times over: a filter row, a
body, a row of buttons at the bottom, and a status line nobody had put in the
same place twice.  Each one had built that shape out of raw ``wx.StaticText``,
``wx.Button`` and ``wx.TextCtrl``, so each one also had its own idea of what a
field outline, a footer, or a disabled action should look like.

So the shape lives here once.  :class:`DialogChrome` installs the body and the
footer into a dialog the caller already owns, :class:`Surface` paints a Material
surface role, and :class:`TextField` is the outlined entry -- a real
``wx.TextCtrl`` inside a painted outline, because a caret, a selection, the
clipboard, and a screen reader's idea of an edit box are the platform's to
provide and not worth re-implementing badly.

It is a helper rather than a base class on purpose.  A dialog keeps its own
``wx.Dialog`` declaration, its own window style, its own
:func:`~amulet_map_editor.api.wx.material3.apply_material3` call -- which is
what installs the shared Material title bar over wx's caption -- and its own
lifecycle; this only supplies the parts all of them draw the same way.

**Studio widgets opt out of the native styling pass.**  They are owner-drawn
from the design tokens and re-theme themselves, so the native traversal has
nothing to add and would only overwrite colours the widget is about to redraw.
:func:`studio` is the one-word way to say that, and it is the same helper the
tab manager already uses for the same reason.
"""

from __future__ import annotations

from typing import Callable, Optional, Sequence, Tuple

import wx

from amulet_map_editor.api.studio import tokens, widgets

#: wxPython 4.1 added a medium weight; an older build falls back to normal
#: rather than raising while a header is being drawn.
_MEDIUM = getattr(wx, "FONTWEIGHT_MEDIUM", wx.FONTWEIGHT_NORMAL)

__all__ = [
    "DialogChrome",
    "RecordTable",
    "Surface",
    "TextField",
    "card",
    "heading",
    "studio",
]


def studio(widget: wx.Window) -> wx.Window:
    """Let a Studio widget keep its own painting during the Material pass.

    Studio widgets are owner-drawn from the design tokens and re-theme
    themselves on a theme change, so the native styling traversal has nothing
    to add and would only overwrite colours the widget is about to redraw.
    """

    widget._material3_opt_out = True
    return widget


class Surface(widgets.Card):
    """A flat panel painting one Material surface role, edge to edge.

    :class:`~amulet_map_editor.api.studio.widgets.Card` already paints a role
    and re-themes itself; a dialog region wants the same paint without the
    rounded corner or the outline, because it runs to the window's own edges.

    It also declares ``_material3_surface_role``, which the native styling pass
    reads: without it that pass would set every panel's background to the plain
    ``surface`` role and a footer would stop being distinguishable from the body
    above it the moment a native control was styled beside it.
    """

    def __init__(
        self,
        parent: wx.Window,
        *,
        role: str = "surface",
        name: str = "",
    ) -> None:
        super().__init__(parent, role=role, radius=0, border=False)
        # Read by ``material3._style_control``.  The Studio palette and the
        # native palette carry the same role names, so both routes paint this
        # panel the same colour rather than two shades of nearly the same one.
        self._material3_surface_role = role
        self.SetName(name or f"{role} surface")


def card(
    parent: wx.Window,
    *,
    role: str = "surface_container",
    padding: int = tokens.SPACE_SM,
    orientation: int = wx.VERTICAL,
    name: str = "",
) -> Tuple[widgets.Card, wx.BoxSizer]:
    """Return a rounded Material container and the sizer holding its contents.

    The container is *not* opted out of the native styling pass: whatever is
    dropped inside it is usually a native control -- a list, a date picker --
    and that control still wants the native palette pushed into it.
    """

    surface = widgets.Card(parent, role=role)
    # Read by ``material3._style_control``.  Without it the native pass sets
    # every panel's background to the plain ``surface`` role, so a native
    # control dropped inside this card would inherit a backdrop one shade off
    # the card painted behind it.
    surface._material3_surface_role = role
    if name:
        surface.SetName(name)
    sizer = wx.BoxSizer(orientation)
    outer = wx.BoxSizer(wx.VERTICAL)
    outer.Add(sizer, 1, wx.EXPAND | wx.ALL, tokens.scaled(padding))
    surface.SetSizer(outer)
    return surface, sizer


def heading(
    parent: wx.Window,
    text: str,
    *,
    size_px: float = 13,
    role: str = "on_surface",
    name: str = "",
    ellipsize: bool = False,
) -> widgets.StudioText:
    """Return a Studio label already opted out of the native styling pass.

    This is the ``wx.StaticText`` replacement every converted dialog reaches
    for.  It keeps ``SetLabel``/``GetLabel``, so a surface that already talks to
    its labels keeps working, and unlike ``wx.StaticText`` it paints through
    ``render_to`` -- which is what stops it photographing as a blank rectangle
    on a desktop nobody is looking at.
    """

    label = widgets.StudioText(
        parent,
        str(text),
        size_px=size_px,
        role=role,
        ellipsize=bool(ellipsize),
        name=name or str(text) or "Label",
    )
    studio(label)
    return label


class TextField(widgets.Card):
    """A painted Material field outline wrapped around one real ``wx.TextCtrl``.

    The outline, the fill and the focus border are drawn from the design tokens
    so a field matches the rest of the shell at every theme, density and
    interface scale.  The entry itself stays a native control, deliberately:
    caret movement, selection, the clipboard, undo, IME composition and the
    accessible role of an edit box are the platform's, and a re-implementation
    would lose all of them to gain nothing but a rectangle that was already
    being drawn here.

    ``field.text`` is that native control, so a caller keeps ``GetValue``,
    ``ChangeValue``, ``SetHint`` and ``Bind`` exactly as it had them.
    """

    #: Design width, and the widest the field grows to hold its own placeholder.
    #: Past that the prompt is left to the tooltip -- a field scrolls its
    #: content, so nothing typed is lost, but an unreadable placeholder is a
    #: prompt that failed at the one job it has.
    WIDTH = 180
    MAX_WIDTH = 420

    # Class-level defaults, because ``Card.__init__`` calls ``_apply_theme``
    # before the assignments below have run.  An AttributeError raised in there
    # surfaces as a field that cannot be constructed at all.
    _focused = False
    _height: Optional[int] = None
    _size_px = 13.0
    _mono = False

    def __init__(
        self,
        parent: wx.Window,
        *,
        value: str = "",
        placeholder: str = "",
        name: str = "Text field",
        multiline: bool = False,
        read_only: bool = False,
        height: Optional[int] = None,
        size_px: float = 13,
        mono: bool = False,
    ) -> None:
        self._focused = False
        self._height = height
        self._size_px = float(size_px)
        self._mono = bool(mono)
        super().__init__(parent, role="surface_container", radius=tokens.RADIUS_SM)
        # The whole control is drawn from the design tokens, inner entry
        # included, so the native pass has nothing to add here.  Left in, it
        # would push a 40px minimum height into the entry and stand it taller
        # than the outline drawn around it.
        studio(self)
        self.SetName(name)
        style = wx.BORDER_NONE
        if multiline:
            style |= wx.TE_MULTILINE
        if read_only:
            style |= wx.TE_READONLY
        self.text = wx.TextCtrl(self, value=str(value), style=style, name=name)
        self.text.SetName(name)
        if placeholder:
            self.text.SetHint(str(placeholder))
            self.text.SetToolTip(str(placeholder))
        self._apply_theme(self.palette())
        self.Bind(wx.EVT_SIZE, self._on_size)
        self.text.Bind(wx.EVT_SET_FOCUS, self._on_focus_change)
        self.text.Bind(wx.EVT_KILL_FOCUS, self._on_focus_change)
        self.SetInitialSize(self.DoGetBestSize())

    # -- geometry ------------------------------------------------------------
    PADDING = 11

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        height = (
            tokens.scaled(self._height)
            if self._height is not None
            else tokens.control_height()
        )
        entry = getattr(self, "text", None)
        hint = entry.GetHint() if entry is not None else ""
        with widgets.measuring(self) as dc:
            dc.SetFont(tokens.font(self, widgets.point_size(self._size_px)))
            content = dc.GetTextExtent(str(hint) or " ")[0]
        width = min(
            tokens.scaled(self.MAX_WIDTH),
            max(
                tokens.scaled(self.WIDTH),
                content + tokens.scaled(self.PADDING) * 2 + widgets.TEXT_SLACK * 2,
            ),
        )
        return wx.Size(width, height)

    def SetFocus(self) -> None:  # noqa: N802 - wx API spelling
        """Send focus to the entry rather than to the outline around it."""
        self.text.SetFocus()

    def _on_size(self, event: wx.SizeEvent) -> None:
        width, height = self.GetClientSize()
        padding = tokens.scaled(self.PADDING)
        entry_height = self.text.GetBestSize().height
        if self.text.GetWindowStyleFlag() & wx.TE_MULTILINE:
            self.text.SetSize(
                padding,
                padding // 2,
                max(0, width - padding * 2),
                max(0, height - padding),
            )
        else:
            self.text.SetSize(
                padding,
                max(0, (height - entry_height) // 2),
                max(0, width - padding * 2),
                entry_height,
            )
        self.Refresh()
        event.Skip()

    def _on_focus_change(self, event: wx.FocusEvent) -> None:
        self._focused = event.GetEventType() == wx.EVT_SET_FOCUS.typeId
        self.Refresh()
        event.Skip()

    # -- theme ---------------------------------------------------------------
    def _apply_theme(self, palette: tokens.StudioPalette) -> None:
        super()._apply_theme(palette)
        entry = getattr(self, "text", None)
        if entry is None:
            return
        entry.SetBackgroundColour(palette.role(self.role))
        entry.SetForegroundColour(palette.on_surface)
        entry.SetFont(
            tokens.font(self, widgets.point_size(self._size_px), mono=self._mono)
        )

    def render_to(self, dc: wx.DC, rect: wx.Rect) -> None:
        """Draw the field's fill and its outline, thickened while focused."""
        palette = self.palette()
        with self._painting(dc, rect) as rect:
            tokens.draw_round_rect(
                dc,
                rect,
                tokens.scaled(self.radius),
                palette.role(self.role),
                palette.primary if self._focused else palette.outline,
                border_width=2 if self._focused else 1,
            )


class RecordTable(wx.Panel):
    """A multi-column, multi-select record list, drawn from the design tokens.

    It replaces the ``wx.ListCtrl`` the notification centre and the local
    history browser were built on.  Two things drove that.  The list is the
    surface in both of those windows, and a native list contributes **nothing**
    to a capture: photographed off-screen it comes back as a white rectangle
    while the report says the row drew, so the one part of the window worth
    checking was the one part nobody could check.  It is also the only control
    left in either window that the Material palette could recolour but never
    restyle -- a native column header stays a native column header.

    The trade is stated rather than hidden.  A native list exposes one
    accessible item per row; this is one focusable control whose accessible
    name carries the focused row and the selection count, which is the same
    shape :class:`~amulet_map_editor.api.studio.widgets.TreeRows` already uses
    in this design system.  Everything a pointer can do here a keyboard can do:
    arrows and Home/End/PageUp/PageDown move the cursor, Shift extends the
    selection from the anchor, Space toggles one row, ``Ctrl+A`` selects every
    row, ``Ctrl+I`` inverts, and Enter activates.

    ``on_selection`` is called whenever the selection changes -- by pointer,
    keyboard, or a caller's own :meth:`select_all` -- so a host never has to
    remember to refresh its counts after a bulk action.
    """

    HEADER_HEIGHT = 30
    ROW_HEIGHT = 28
    PADDING = 10
    #: Rows a fresh table asks for room to show before anything scrolls.
    PREFERRED_ROWS = 8
    #: The narrowest a column is squeezed to before its text starts eliding.
    MIN_COLUMN = 56
    SCROLL_STEP = 3

    def __init__(
        self,
        parent: wx.Window,
        columns: Sequence[Tuple[str, int]],
        *,
        name: str,
        on_selection: Optional[Callable[[], None]] = None,
        on_activate: Optional[Callable[[], None]] = None,
        empty_text: str = "Nothing to show yet.",
    ) -> None:
        super().__init__(parent, style=wx.WANTS_CHARS)
        self.columns: list = [
            (str(label), max(1, int(weight))) for label, weight in columns
        ]
        self.rows: list = []
        self.selected: set = set()
        self.cursor = 0
        self.anchor = 0
        self.offset = 0
        self.base_name = str(name)
        self.empty_text = str(empty_text)
        self.on_selection = on_selection
        self.on_activate = on_activate
        self._hovered = -1
        self.SetName(self.base_name)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        try:
            self.SetDoubleBuffered(True)
        except (AttributeError, RuntimeError):  # pragma: no cover - backend
            pass
        self.SetCursor(wx.Cursor(wx.CURSOR_ARROW))
        self._theme_unsubscribe = tokens.register_theme_listener(self.refresh_theme)
        self.Bind(wx.EVT_WINDOW_DESTROY, self._on_destroyed)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.Bind(wx.EVT_SIZE, lambda event: (self.Refresh(), event.Skip()))
        self.Bind(wx.EVT_LEFT_DOWN, self._on_left_down)
        self.Bind(wx.EVT_LEFT_DCLICK, self._on_double_click)
        self.Bind(wx.EVT_MOTION, self._on_motion)
        self.Bind(wx.EVT_LEAVE_WINDOW, self._on_leave)
        self.Bind(wx.EVT_MOUSEWHEEL, self._on_wheel)
        self.Bind(wx.EVT_KEY_DOWN, self._on_key_down)
        self.Bind(wx.EVT_SET_FOCUS, lambda event: (self.Refresh(), event.Skip()))
        self.Bind(wx.EVT_KILL_FOCUS, lambda event: (self.Refresh(), event.Skip()))
        self.SetInitialSize(self.DoGetBestSize())

    # -- wx plumbing ---------------------------------------------------------
    def _on_destroyed(self, event: wx.WindowDestroyEvent) -> None:
        if event.GetEventObject() is self and self._theme_unsubscribe is not None:
            self._theme_unsubscribe()
            self._theme_unsubscribe = None
        event.Skip()

    def palette(self) -> tokens.StudioPalette:
        """Return the live palette, resolved per paint so a change lands at once."""

        return tokens.palette()

    def refresh_theme(self) -> None:
        """Repaint after a theme, density, or interface-scale change."""

        try:
            if self.IsBeingDeleted():
                return
            self.Refresh()
        except RuntimeError:  # pragma: no cover - window already gone
            self._theme_unsubscribe = None

    def AcceptsFocus(self) -> bool:  # noqa: N802 - wx API spelling
        return True

    def AcceptsFocusFromKeyboard(self) -> bool:  # noqa: N802 - wx API spelling
        return True

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        width = tokens.scaled(self.MIN_COLUMN) * max(1, len(self.columns))
        height = (
            tokens.scaled(self.HEADER_HEIGHT)
            + tokens.scaled(self.ROW_HEIGHT) * self.PREFERRED_ROWS
        )
        return wx.Size(width, height)

    # -- content -------------------------------------------------------------
    def set_rows(self, rows: Sequence[Sequence[str]]) -> None:
        """Replace every row, and with them the selection.

        A refreshed list is a different list: keeping index-based selection
        across it would silently point the next bulk action at whichever
        records happened to land on the same row numbers.
        """

        self.rows = [tuple(str(cell) for cell in row) for row in rows]
        self.selected = set()
        self.cursor = 0
        self.anchor = 0
        self.offset = 0
        self._announce()
        self.Refresh()
        self._report_selection()

    def row_count(self) -> int:
        """Return how many rows are currently listed."""

        return len(self.rows)

    def selected_indices(self) -> list:
        """Return the selected row indices, in list order."""

        return sorted(index for index in self.selected if 0 <= index < len(self.rows))

    def selection_count(self) -> int:
        """Return how many rows are selected."""

        return len(self.selected_indices())

    def focused_index(self) -> int:
        """Return the row the keyboard cursor is on, or ``-1`` when empty."""

        return self.cursor if self.rows else -1

    # -- selection -----------------------------------------------------------
    def select(self, index: int, on: bool = True, *, notify: bool = True) -> None:
        """Select or deselect one row by index."""

        if not 0 <= index < len(self.rows):
            return
        if on:
            self.selected.add(index)
        else:
            self.selected.discard(index)
        self._after_selection(notify)

    def select_all(self, *, notify: bool = True) -> None:
        """Select every row currently listed -- which is every row that matches.

        The count beside the actions says so: a filtered list selects what is
        visible, never the records a filter is hiding.
        """

        self.selected = set(range(len(self.rows)))
        self._after_selection(notify)

    def select_none(self, *, notify: bool = True) -> None:
        """Clear the selection without touching the cursor."""

        self.selected = set()
        self._after_selection(notify)

    def invert_selection(self, *, notify: bool = True) -> None:
        """Select exactly the rows that were not selected."""

        self.selected = set(range(len(self.rows))) - self.selected
        self._after_selection(notify)

    def _select_only(self, index: int, *, notify: bool = True) -> None:
        self.selected = {index} if 0 <= index < len(self.rows) else set()
        self._after_selection(notify)

    def _select_range(self, start: int, end: int, *, notify: bool = True) -> None:
        low, high = sorted((int(start), int(end)))
        self.selected = {
            index for index in range(low, high + 1) if 0 <= index < len(self.rows)
        }
        self._after_selection(notify)

    def _after_selection(self, notify: bool) -> None:
        self._announce()
        self.Refresh()
        if notify:
            self._report_selection()

    def _report_selection(self) -> None:
        if self.on_selection is not None:
            widgets.invoke(self.on_selection)

    def _announce(self) -> None:
        """Keep the accessible name describing the row in focus and the state.

        A screen reader reads this control's name; without the row in it, a
        keyboard user moving down the list would hear the same word each time.
        """

        if not self.rows:
            self.SetName(f"{self.base_name}: empty")
            return
        index = max(0, min(self.cursor, len(self.rows) - 1))
        summary = " ".join(cell for cell in self.rows[index] if cell)
        state = "selected" if index in self.selected else "not selected"
        self.SetName(
            f"{self.base_name}: row {index + 1} of {len(self.rows)}, {summary}, "
            f"{state}, {len(self.selected)} selected"
        )

    # -- geometry ------------------------------------------------------------
    def _visible_rows(self) -> int:
        _width, height = self.GetClientSize()
        usable = max(0, height - tokens.scaled(self.HEADER_HEIGHT))
        return max(1, usable // max(1, tokens.scaled(self.ROW_HEIGHT)))

    def _row_at(self, y: int) -> int:
        header = tokens.scaled(self.HEADER_HEIGHT)
        if y < header:
            return -1
        row = self.offset + (y - header) // max(1, tokens.scaled(self.ROW_HEIGHT))
        return row if 0 <= row < len(self.rows) else -1

    def _column_rects(self, width: int) -> list:
        """Return one ``(x, width)`` pair per column, weighted across ``width``."""

        padding = tokens.scaled(self.PADDING)
        available = max(0, width - padding * 2)
        weights = [weight for _label, weight in self.columns] or [1]
        total = sum(weights)
        floor = tokens.scaled(self.MIN_COLUMN)
        widths = [max(floor, available * weight // total) for weight in weights]
        # Squeeze proportionally rather than letting the last column run off the
        # edge: a narrow window elides every column a little instead of hiding
        # one completely.
        overflow = sum(widths) - available
        if overflow > 0 and available > 0:
            widths = [max(1, value * available // sum(widths)) for value in widths]
        rects = []
        x = padding
        for value in widths:
            rects.append((x, value))
            x += value
        return rects

    def _ensure_visible(self) -> None:
        visible = self._visible_rows()
        if self.cursor < self.offset:
            self.offset = self.cursor
        elif self.cursor >= self.offset + visible:
            self.offset = self.cursor - visible + 1
        self.offset = max(0, min(self.offset, max(0, len(self.rows) - visible)))

    # -- pointer -------------------------------------------------------------
    def _on_left_down(self, event: wx.MouseEvent) -> None:
        self.SetFocus()
        index = self._row_at(event.GetPosition().y)
        if index < 0:
            event.Skip()
            return
        self.cursor = index
        if event.ShiftDown():
            self._select_range(self.anchor, index)
        elif event.ControlDown():
            self.anchor = index
            self.select(index, index not in self.selected)
        else:
            self.anchor = index
            self._select_only(index)
        self._ensure_visible()
        event.Skip()

    def _on_double_click(self, event: wx.MouseEvent) -> None:
        if self._row_at(event.GetPosition().y) >= 0 and self.on_activate is not None:
            widgets.invoke(self.on_activate)
        event.Skip()

    def _on_motion(self, event: wx.MouseEvent) -> None:
        index = self._row_at(event.GetPosition().y)
        if index != self._hovered:
            self._hovered = index
            self.SetToolTip(self._tooltip_for(event.GetPosition().y, index))
            self.Refresh()
        event.Skip()

    def _tooltip_for(self, y: int, index: int) -> str:
        """Return the full text under the pointer, elided or not.

        A cell narrower than its value is shortened, and a shortened value with
        no way to read the rest of it is lost rather than abbreviated.  Both the
        header and the rows are one hover away at every window width -- which
        matters most in bilingual mode, where a column heading carries two
        languages in the space one was measured for.
        """

        if 0 <= index < len(self.rows):
            return " · ".join(cell for cell in self.rows[index] if cell)
        if y < tokens.scaled(self.HEADER_HEIGHT):
            return " · ".join(str(label) for label, _weight in self.columns)
        return ""

    def _on_leave(self, event: wx.MouseEvent) -> None:
        if self._hovered != -1:
            self._hovered = -1
            self.SetToolTip("")
            self.Refresh()
        event.Skip()

    def _on_wheel(self, event: wx.MouseEvent) -> None:
        if not self.rows:
            event.Skip()
            return
        steps = self.SCROLL_STEP * (1 if event.GetWheelRotation() < 0 else -1)
        limit = max(0, len(self.rows) - self._visible_rows())
        self.offset = max(0, min(limit, self.offset + steps))
        self.Refresh()

    # -- keyboard ------------------------------------------------------------
    def _on_key_down(self, event: wx.KeyEvent) -> None:
        code = event.GetKeyCode()
        if event.ControlDown() and code in (ord("A"), ord("a")):
            self.select_all()
            return
        if event.ControlDown() and code in (ord("I"), ord("i")):
            self.invert_selection()
            return
        if code in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            if self.on_activate is not None:
                widgets.invoke(self.on_activate)
                return
            event.Skip()
            return
        if code == wx.WXK_SPACE:
            self.select(self.cursor, self.cursor not in self.selected)
            return
        if not self.rows:
            event.Skip()
            return
        page = max(1, self._visible_rows() - 1)
        moves = {
            wx.WXK_UP: self.cursor - 1,
            wx.WXK_DOWN: self.cursor + 1,
            wx.WXK_HOME: 0,
            wx.WXK_END: len(self.rows) - 1,
            wx.WXK_PAGEUP: self.cursor - page,
            wx.WXK_PAGEDOWN: self.cursor + page,
        }
        if code not in moves:
            event.Skip()
            return
        self.cursor = max(0, min(len(self.rows) - 1, moves[code]))
        if event.ShiftDown():
            self._select_range(self.anchor, self.cursor)
        else:
            self.anchor = self.cursor
            self._select_only(self.cursor)
        self._ensure_visible()
        self.Refresh()

    # -- painting ------------------------------------------------------------
    def _backdrop(self) -> wx.Colour:
        return self.palette().surface

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        dc, gcdc = widgets.paint_context(self, self._backdrop())
        width, height = self.GetClientSize()
        self.render_to(gcdc, wx.Rect(0, 0, width, height))
        del gcdc

    def render_to(self, dc: wx.DC, rect: wx.Rect) -> None:
        """Draw the frame, the header, every visible row, and the scroll hint."""

        palette = self.palette()
        with widgets.translated(dc, rect):
            frame = wx.Rect(0, 0, rect.width, rect.height)
            dc.SetBrush(wx.Brush(self._backdrop()))
            dc.SetPen(wx.TRANSPARENT_PEN)
            dc.DrawRectangle(frame)
            radius = tokens.scaled(tokens.RADIUS_SM)
            tokens.draw_round_rect(
                dc,
                frame,
                radius,
                palette.surface_container,
                palette.primary if self.HasFocus() else palette.outline_variant,
                border_width=2 if self.HasFocus() else 1,
            )
            self._paint_header(dc, palette, frame)
            if not self.rows:
                self._paint_empty(dc, palette, frame)
            else:
                self._paint_rows(dc, palette, frame)
                self._paint_scroll_hint(dc, palette, frame)

    def _paint_header(
        self, dc: wx.DC, palette: tokens.StudioPalette, frame: wx.Rect
    ) -> None:
        header_height = tokens.scaled(self.HEADER_HEIGHT)
        dc.SetFont(tokens.font(self, widgets.point_size(11), _MEDIUM))
        dc.SetTextForeground(palette.on_surface_variant)
        baseline = (header_height - dc.GetCharHeight()) // 2
        for (x, width), (label, _weight) in zip(
            self._column_rects(frame.width), self.columns
        ):
            text = widgets.elide(dc, str(label), max(0, width - tokens.scaled(8)))
            dc.DrawText(text, x, baseline)
        dc.SetPen(wx.Pen(palette.outline_variant, 1))
        dc.DrawLine(
            tokens.scaled(self.PADDING) // 2,
            header_height,
            frame.width - tokens.scaled(self.PADDING) // 2,
            header_height,
        )

    def _paint_empty(
        self, dc: wx.DC, palette: tokens.StudioPalette, frame: wx.Rect
    ) -> None:
        if not self.empty_text:
            # A caller with no localized copy for this state passes none, and
            # gets the blank surface a native list showed rather than a line of
            # English inside a window that speaks the user's language.
            return
        dc.SetFont(tokens.font(self, widgets.point_size(12)))
        dc.SetTextForeground(palette.on_surface_variant)
        text = widgets.elide(
            dc, self.empty_text, max(0, frame.width - tokens.scaled(self.PADDING) * 2)
        )
        text_width = dc.GetTextExtent(text)[0]
        dc.DrawText(
            text,
            max(tokens.scaled(self.PADDING), (frame.width - text_width) // 2),
            tokens.scaled(self.HEADER_HEIGHT) + tokens.scaled(self.PADDING),
        )

    def _paint_rows(
        self, dc: wx.DC, palette: tokens.StudioPalette, frame: wx.Rect
    ) -> None:
        header_height = tokens.scaled(self.HEADER_HEIGHT)
        row_height = tokens.scaled(self.ROW_HEIGHT)
        padding = tokens.scaled(self.PADDING)
        columns = self._column_rects(frame.width)
        visible = self._visible_rows()
        focused = self.HasFocus()
        dc.SetFont(tokens.font(self, widgets.point_size(12)))
        for position in range(visible):
            index = self.offset + position
            if index >= len(self.rows):
                break
            top = header_height + position * row_height
            band = wx.Rect(
                padding // 2, top, max(0, frame.width - padding), row_height - 1
            )
            chosen = index in self.selected
            if chosen:
                tokens.draw_round_rect(
                    dc, band, tokens.scaled(6), palette.primary_container
                )
                ink = palette.on_primary_container
            elif index == self._hovered:
                tokens.draw_round_rect(
                    dc, band, tokens.scaled(6), palette.surface_container_high
                )
                ink = palette.on_surface
            else:
                ink = palette.on_surface
            if focused and index == self.cursor:
                widgets.draw_focus_ring(dc, band, tokens.scaled(6), palette.primary)
            dc.SetTextForeground(ink)
            baseline = top + (row_height - dc.GetCharHeight()) // 2
            for (x, width), cell in zip(columns, self.rows[index]):
                text = widgets.elide(dc, str(cell), max(0, width - tokens.scaled(8)))
                dc.DrawText(text, x, baseline)

    def _paint_scroll_hint(
        self, dc: wx.DC, palette: tokens.StudioPalette, frame: wx.Rect
    ) -> None:
        visible = self._visible_rows()
        if len(self.rows) <= visible:
            return
        header_height = tokens.scaled(self.HEADER_HEIGHT)
        track_height = max(1, frame.height - header_height - tokens.scaled(6))
        thumb = max(tokens.scaled(18), track_height * visible // len(self.rows))
        span = max(1, len(self.rows) - visible)
        top = header_height + (track_height - thumb) * min(self.offset, span) // span
        width = tokens.scaled(4)
        tokens.draw_round_rect(
            dc,
            wx.Rect(frame.width - width - tokens.scaled(4), top, width, thumb),
            width // 2,
            palette.outline,
        )


class DialogChrome:
    """The body, the footer, the status line, and the action row of a dialog.

    Installed into a ``wx.Dialog`` the caller already owns, so a dialog keeps
    its own class declaration, window style and Material title bar.  The caller
    fills :attr:`body_sizer`, adds its actions with :meth:`action`, and reports
    into :meth:`set_status`.

    The footer holds the status line and the actions together because that is
    where a reader looks after pressing something: an export that wrote a file
    and a restore that failed both have to say so next to the button that was
    pressed, not in a corner of the window somewhere above it.
    """

    def __init__(
        self,
        dialog: wx.Dialog,
        *,
        status_name: str = "",
        footer: bool = True,
        padding: int = tokens.SPACE_MD,
    ) -> None:
        self.dialog = dialog
        self.padding = int(padding)
        self.status_name = str(status_name or "Status")
        self.body = Surface(dialog, role="surface", name="Dialog body")
        self.body_sizer = wx.BoxSizer(wx.VERTICAL)
        body_frame = wx.BoxSizer(wx.VERTICAL)
        body_frame.Add(self.body_sizer, 1, wx.EXPAND | wx.ALL, tokens.scaled(padding))
        self.body.SetSizer(body_frame)

        self.footer: Optional[Surface] = None
        self.status: Optional[widgets.StudioText] = None
        self.actions: list = []
        self._action_sizer: Optional[wx.BoxSizer] = None
        if footer:
            self.footer = Surface(
                dialog, role="surface_container", name="Dialog actions"
            )
            self.status = heading(
                self.footer,
                "",
                size_px=12,
                role="on_surface_variant",
                name=self.status_name,
                # One line beside the actions, so a long path or an error is
                # shortened with the whole of it kept in the tooltip rather
                # than pushing the buttons off the window.
                ellipsize=True,
            )
            self._action_sizer = wx.BoxSizer(wx.HORIZONTAL)
            row = wx.BoxSizer(wx.HORIZONTAL)
            row.Add(
                self.status,
                1,
                wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
                tokens.scaled(tokens.SPACE_MD),
            )
            row.Add(self._action_sizer, 0, wx.ALIGN_CENTER_VERTICAL)
            frame = wx.BoxSizer(wx.VERTICAL)
            frame.Add(
                row,
                1,
                wx.EXPAND | wx.ALL,
                tokens.scaled(tokens.SPACE_SM + tokens.SPACE_XS),
            )
            self.footer.SetSizer(frame)

        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(self.body, 1, wx.EXPAND)
        if self.footer is not None:
            root.Add(self.footer, 0, wx.EXPAND)
        dialog.SetSizer(root)

    # -- body ----------------------------------------------------------------
    def add(
        self,
        control: wx.Window | wx.Sizer,
        proportion: int = 0,
        flag: int = wx.EXPAND,
        border: int = 0,
    ) -> None:
        """Add one control or sizer to the dialog body."""

        self.body_sizer.Add(control, proportion, flag, tokens.scaled(border))

    def gap(self, size: int = tokens.SPACE_SM) -> None:
        """Leave one design-token gap between two body rows."""

        self.body_sizer.AddSpacer(tokens.scaled(size))

    # -- footer --------------------------------------------------------------
    def action(
        self,
        label: str,
        *,
        variant: str = "text",
        on_click: Optional[Callable[[], None]] = None,
        name: str = "",
        hint: str = "",
        enabled: bool = True,
    ) -> widgets.StudioButton:
        """Add one footer action and return it, so a caller can enable it later.

        A disabled action is still built, still named, and still carries its
        tooltip: a control that vanishes when it cannot be used is a control the
        user cannot discover, and one with no explanation reads as broken rather
        than as blocked.
        """

        if self.footer is None or self._action_sizer is None:
            raise RuntimeError("This dialog was built without a footer")
        button = widgets.StudioButton(
            self.footer,
            str(label),
            variant=variant,
            on_click=on_click,
            name=name or str(label),
            hint=hint,
        )
        studio(button)
        button.Enable(bool(enabled))
        self._action_sizer.Add(
            button,
            0,
            wx.LEFT | wx.ALIGN_CENTER_VERTICAL,
            tokens.scaled(tokens.SPACE_SM),
        )
        self.actions.append(button)
        return button

    def set_status(self, text: str) -> None:
        """State what just happened, beside the actions that could cause it."""

        if self.status is None:
            return
        message = str(text)
        self.status.SetLabel(message)
        # The base name stays, so a screen reader still says which line this
        # is; the message is appended rather than replacing it, because a name
        # that is only ever the latest sentence never says what it belongs to.
        self.status.SetName(
            f"{self.status_name}: {message}" if message else self.status_name
        )
        self.status.SetToolTip(message)
        if self.footer is not None:
            self.footer.Layout()

    def status_text(self) -> str:
        """Return the current status line, for a caller that appends to it."""

        return self.status.GetLabel() if self.status is not None else ""
