"""The one window that renders every declarative Amulet Studio surface.

Most surfaces in the shell are data: an eyebrow, a title, an introduction, a
list of :class:`~amulet_map_editor.api.studio.spec.Section` values, and a few
footer actions.  This module turns that data into real controls, one renderer
per section kind, so adding a surface is a spec entry rather than a new window
class -- and so every surface inherits the same window search, the same regex
builder, the same keyboard behaviour, and the same theme handling instead of
each one re-implementing them slightly differently.

The window is shown non-modally: several surfaces are routinely open at once,
and a modal renderer would make the shell unusable the moment two of them were
needed together.
"""

from __future__ import annotations

import logging
from typing import Callable, Dict, List, Optional

import wx

from amulet_map_editor.api.studio import spec as spec_api
from amulet_map_editor.api.studio import specs as spec_registry
from amulet_map_editor.api.studio import tokens, widgets
from amulet_map_editor.api.studio.search import SearchState
from amulet_map_editor.api.studio.spec import Action, Section, Spec

log = logging.getLogger(__name__)

#: Footer action kinds mapped onto the button variants the design draws them
#: with.  An unknown kind falls back to outlined rather than refusing to render
#: the action, because a missing button hides a capability entirely.
ACTION_VARIANTS: Dict[str, str] = {
    "tonal": "tonal",
    "outlined": "outlined",
    "danger": "danger",
    "text": "text",
    "filled": "filled",
}

#: The tallest a surface grows before its body starts scrolling.
MAX_DIALOG_HEIGHT = 780

#: wxPython 4.1 added a medium weight; older builds fall back to normal.
_MEDIUM = getattr(wx, "FONTWEIGHT_MEDIUM", wx.FONTWEIGHT_NORMAL)


class _Painted(wx.Control):
    """A static owner-drawn block that repaints when the theme changes.

    These are records rather than controls -- prose, a note, a key binding --
    so they are deliberately not tab stops: putting forty unactionable rows
    between the user and the next button would make the keyboard route through
    a window worse, not better.
    """

    def __init__(self, parent: wx.Window, name: str) -> None:
        super().__init__(parent, style=wx.BORDER_NONE)
        self.SetName(name)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)

    def AcceptsFocus(self) -> bool:  # noqa: N802 - wx API spelling
        return False

    def AcceptsFocusFromKeyboard(self) -> bool:  # noqa: N802 - wx API spelling
        return False

    def refresh_theme(self) -> None:
        """Repaint with the live palette."""
        self.Refresh()

    def _backdrop(self, palette: tokens.StudioPalette) -> wx.Colour:
        parent = self.GetParent()
        colour = parent.GetBackgroundColour() if parent else palette.surface
        return colour if colour.IsOk() else palette.surface

    # Each block below defines its own ``_on_paint``; the base deliberately
    # does not, so a block that forgot one fails at construction rather than
    # rendering as a blank rectangle nobody notices.


class _Paragraph(_Painted):
    """Word-wrapped prose that re-wraps to whatever width it is given."""

    def __init__(
        self,
        parent: wx.Window,
        text: str,
        *,
        size_px: int = 13,
        role: str = "on_surface_variant",
    ) -> None:
        super().__init__(parent, text[:120] or "Paragraph")
        self.text = str(text)
        self.size_px = size_px
        self.role = role
        self._wrapped_at = 0
        self.Bind(wx.EVT_SIZE, self._on_resize)

    def _on_resize(self, event: wx.SizeEvent) -> None:
        """Re-wrap when the column width changes, and only then.

        Recomputing on every size event would re-enter the parent's layout in a
        loop; comparing against the width the text was last wrapped at makes
        the work happen exactly once per real width change.
        """
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
        return widgets.wrap_text(dc, self.text, max(40, width), max_lines=40)

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        dc = wx.ClientDC(self)
        dc.SetFont(tokens.font(self, widgets.point_size(self.size_px)))
        width = self.GetSize().width or tokens.scaled(560)
        lines = self._lines(dc, width)
        return wx.Size(width, int(dc.GetCharHeight() * 1.55 * len(lines)) + 2)

    def set_text(self, text: str) -> None:
        """Replace the prose and re-measure it."""
        self.text = str(text)
        self.SetName(self.text[:120] or "Paragraph")
        self.InvalidateBestSize()
        self.Refresh()

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        dc, gcdc = widgets.paint_context(self, self._backdrop(palette))
        width, _height = self.GetClientSize()
        gcdc.SetFont(tokens.font(self, widgets.point_size(self.size_px)))
        gcdc.SetTextForeground(palette.role(self.role))
        line_height = int(gcdc.GetCharHeight() * 1.55)
        y = 0
        for line in self._lines(gcdc, width):
            gcdc.DrawText(line, 0, y)
            y += line_height
        del gcdc


class _Eyebrow(_Painted):
    """The small uppercase primary caption above a surface title."""

    TRACKING = 1

    def __init__(self, parent: wx.Window, text: str) -> None:
        super().__init__(parent, str(text) or "Category")
        self.text = str(text)

    def _font(self) -> wx.Font:
        return tokens.font(self, widgets.point_size(11), wx.FONTWEIGHT_BOLD)

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        dc = wx.ClientDC(self)
        dc.SetFont(self._font())
        return wx.Size(
            widgets.tracked_width(dc, self.text.upper(), tokens.scaled(self.TRACKING))
            + 2,
            dc.GetCharHeight() + tokens.scaled(4),
        )

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        dc, gcdc = widgets.paint_context(self, self._backdrop(palette))
        gcdc.SetFont(self._font())
        gcdc.SetTextForeground(palette.primary)
        widgets.draw_tracked_text(
            gcdc, self.text.upper(), 0, 0, tokens.scaled(self.TRACKING)
        )
        del gcdc


class _NoteBlock(_Painted):
    """The tinted block with a coloured left edge the design uses for notes."""

    def __init__(self, parent: wx.Window, text: str, *, role: str = "primary") -> None:
        super().__init__(parent, str(text)[:120] or "Note")
        self.text = str(text)
        self.role = role
        self._wrapped_at = 0
        self.Bind(wx.EVT_SIZE, self._on_resize)

    def _on_resize(self, event: wx.SizeEvent) -> None:
        """Re-wrap once per real width change, as :class:`_Paragraph` does."""
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

    def _inner_width(self) -> int:
        width = self.GetSize().width or tokens.scaled(560)
        return max(40, width - tokens.scaled(30))

    def _lines(self, dc: wx.DC) -> List[str]:
        return widgets.wrap_text(dc, self.text, self._inner_width(), max_lines=40)

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        dc = wx.ClientDC(self)
        dc.SetFont(tokens.font(self, widgets.point_size(13)))
        lines = self._lines(dc)
        height = int(dc.GetCharHeight() * 1.55 * len(lines)) + tokens.scaled(24)
        return wx.Size(self.GetSize().width or tokens.scaled(560), height)

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        dc, gcdc = widgets.paint_context(self, self._backdrop(palette))
        width, height = self.GetClientSize()
        rect = wx.Rect(0, 0, width, height)
        tokens.draw_round_rect(
            gcdc, rect, tokens.scaled(10), palette.surface_container_high
        )
        edge = tokens.scaled(3)
        gcdc.SetBrush(wx.Brush(palette.role(self.role)))
        gcdc.SetPen(wx.TRANSPARENT_PEN)
        gcdc.DrawRectangle(
            wx.Rect(0, tokens.scaled(4), edge, height - tokens.scaled(8))
        )
        gcdc.SetFont(tokens.font(self, widgets.point_size(13)))
        gcdc.SetTextForeground(palette.on_surface)
        line_height = int(gcdc.GetCharHeight() * 1.55)
        y = tokens.scaled(12)
        for line in self._lines(gcdc):
            gcdc.DrawText(line, tokens.scaled(14), y)
            y += line_height
        del gcdc


class _KeyRow(_Painted):
    """One action and the key that runs it, drawn as a record with a key cap."""

    def __init__(self, parent: wx.Window, action: str, binding: str) -> None:
        super().__init__(parent, f"{action}: {binding}")
        self.action = str(action)
        self.binding = str(binding)

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        dc = wx.ClientDC(self)
        dc.SetFont(tokens.font(self, widgets.point_size(13)))
        height = dc.GetCharHeight() + tokens.scaled(18)
        return wx.Size(tokens.scaled(240), max(height, tokens.scaled(38)))

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        dc, gcdc = widgets.paint_context(self, self._backdrop(palette))
        width, height = self.GetClientSize()
        rect = wx.Rect(0, 0, width, height)
        tokens.draw_round_rect(
            gcdc,
            rect,
            tokens.scaled(10),
            palette.surface_container,
            palette.outline_variant,
        )
        gcdc.SetFont(tokens.mono_font(self, widgets.point_size(11)))
        cap_width = gcdc.GetTextExtent(self.binding)[0] + tokens.scaled(16)
        cap_height = gcdc.GetCharHeight() + tokens.scaled(6)
        cap = wx.Rect(
            width - cap_width - tokens.scaled(11),
            (height - cap_height) // 2,
            cap_width,
            cap_height,
        )
        tokens.draw_round_rect(
            gcdc, cap, tokens.scaled(6), palette.surface_container_high
        )
        gcdc.SetTextForeground(palette.primary)
        gcdc.DrawText(self.binding, cap.x + tokens.scaled(8), cap.y + tokens.scaled(3))
        gcdc.SetFont(tokens.font(self, widgets.point_size(13)))
        gcdc.SetTextForeground(palette.on_surface)
        available = max(0, cap.x - tokens.scaled(22))
        gcdc.DrawText(
            widgets.elide(gcdc, self.action, available),
            tokens.scaled(11),
            (height - gcdc.GetCharHeight()) // 2,
        )
        del gcdc


class _CheckRow(wx.Panel):
    """A checkbox with the explanation that says what turning it on does."""

    def __init__(
        self,
        parent: wx.Window,
        label: str,
        hint: str = "",
        value: bool = False,
        *,
        on_change: Optional[Callable[[bool], None]] = None,
    ) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self.on_change = on_change
        self.check = wx.CheckBox(self, label=str(label))
        self.check.SetValue(bool(value))
        self.check.SetName(str(label))
        if hint:
            self.check.SetToolTip(str(hint))
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.check, 0, wx.EXPAND)
        self.hint: Optional[_Paragraph] = None
        if hint:
            self.hint = _Paragraph(self, str(hint), size_px=12)
            sizer.Add(
                self.hint,
                0,
                wx.EXPAND | wx.LEFT | wx.TOP,
                tokens.scaled(tokens.SPACE_LG),
            )
        self.SetSizer(sizer)
        self.SetMinSize(wx.Size(-1, tokens.scaled(56)))
        self.check.Bind(wx.EVT_CHECKBOX, self._changed)
        self.refresh_theme()

    def value(self) -> bool:
        """Return whether the box is ticked."""
        return self.check.GetValue()

    def _changed(self, event: wx.CommandEvent) -> None:
        widgets.invoke(self.on_change, self.check.GetValue())
        event.Skip()

    def refresh_theme(self) -> None:
        """Re-read the palette for the box and its explanation."""
        palette = tokens.palette()
        parent = self.GetParent()
        backdrop = parent.GetBackgroundColour() if parent else palette.surface
        self.SetBackgroundColour(backdrop if backdrop.IsOk() else palette.surface)
        self.check.SetBackgroundColour(self.GetBackgroundColour())
        self.check.SetForegroundColour(palette.on_surface)
        self.check.SetFont(tokens.font(self, widgets.point_size(14)))
        if self.hint is not None:
            self.hint.refresh_theme()


class _CodeBlock(wx.Panel):
    """A monospaced, selectable, read-only block for code and transcripts.

    It is a real text control rather than painted text so the content can be
    selected and copied; a code sample nobody can copy is a picture of code.
    """

    def __init__(self, parent: wx.Window, code: str) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self.code = str(code)
        self.text = wx.TextCtrl(
            self,
            value=self.code,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.BORDER_NONE | wx.TE_DONTWRAP,
        )
        self.text.SetName("Code")
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.text, 1, wx.EXPAND | wx.ALL, tokens.scaled(12))
        self.SetSizer(sizer)
        self.refresh_theme()
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        lines = self.code.count("\n") + 1
        height = tokens.scaled(min(24, max(2, lines)) * 18 + 24)
        self.SetMinSize(wx.Size(-1, height))

    def refresh_theme(self) -> None:
        """Re-read the palette for the block and the text inside it."""
        palette = tokens.palette()
        parent = self.GetParent()
        backdrop = parent.GetBackgroundColour() if parent else palette.surface
        self.SetBackgroundColour(backdrop if backdrop.IsOk() else palette.surface)
        self.text.SetBackgroundColour(palette.surface_container_high)
        self.text.SetForegroundColour(palette.on_surface_variant)
        self.text.SetFont(tokens.mono_font(self, widgets.point_size(12)))
        self.Refresh()

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        dc, gcdc = widgets.paint_context(self, self.GetBackgroundColour())
        width, height = self.GetClientSize()
        tokens.draw_round_rect(
            gcdc,
            wx.Rect(0, 0, width, height),
            tokens.scaled(10),
            palette.surface_container_high,
        )
        del gcdc


class _CommitRow(wx.Panel):
    """One revision: its dot, its message and metadata, and its two actions."""

    def __init__(
        self,
        parent: wx.Window,
        message: str,
        meta: str,
        head: bool,
        *,
        on_action: Optional[Callable[[str], None]] = None,
    ) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self.message = str(message)
        self.meta = str(meta)
        self.head = bool(head)
        self.on_action = on_action
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.title = wx.StaticText(self, label=self.message)
        self.detail = wx.StaticText(self, label=self.meta)
        self.diff = widgets.StudioButton(
            self,
            "Diff",
            variant="outlined",
            on_click=lambda: widgets.invoke(self.on_action, "Diff"),
            name=f"Diff {self.message}",
            hint=f"Compare {self.meta} with the working tree",
            height=30,
        )
        self.restore = widgets.StudioButton(
            self,
            "Restore",
            variant="tonal",
            on_click=lambda: widgets.invoke(self.on_action, "Restore"),
            name=f"Restore {self.message}",
            hint="Restoring writes a new revision; nothing is rewound",
            height=30,
        )
        text = wx.BoxSizer(wx.VERTICAL)
        text.Add(self.title, 0, wx.EXPAND)
        text.Add(self.detail, 0, wx.EXPAND | wx.TOP, tokens.scaled(2))
        buttons = wx.BoxSizer(wx.HORIZONTAL)
        buttons.Add(self.diff, 0, wx.RIGHT, tokens.scaled(6))
        buttons.Add(self.restore, 0)
        row = wx.BoxSizer(wx.HORIZONTAL)
        row.AddSpacer(tokens.scaled(24))
        row.Add(text, 1, wx.ALIGN_CENTER_VERTICAL)
        row.Add(buttons, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, tokens.scaled(12))
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(row, 1, wx.EXPAND | wx.TOP | wx.BOTTOM, tokens.scaled(10))
        self.SetSizer(outer)
        self.refresh_theme()
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)

    def refresh_theme(self) -> None:
        """Re-read the palette for the row and its two buttons."""
        palette = tokens.palette()
        parent = self.GetParent()
        backdrop = parent.GetBackgroundColour() if parent else palette.surface
        self.SetBackgroundColour(backdrop if backdrop.IsOk() else palette.surface)
        self.title.SetForegroundColour(palette.on_surface)
        self.title.SetFont(tokens.font(self, widgets.point_size(13), _MEDIUM))
        self.detail.SetForegroundColour(palette.on_surface_variant)
        self.detail.SetFont(tokens.mono_font(self, widgets.point_size(11)))
        for button in (self.diff, self.restore):
            button.refresh_theme()
        self.Refresh()

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        dc, gcdc = widgets.paint_context(self, self.GetBackgroundColour())
        width, height = self.GetClientSize()
        gcdc.SetPen(wx.Pen(palette.outline_variant, 1))
        gcdc.DrawLine(0, height - 1, width, height - 1)
        dot = tokens.scaled(9)
        centre_x = tokens.scaled(12)
        top = tokens.scaled(14)
        gcdc.SetPen(wx.TRANSPARENT_PEN)
        if self.head:
            gcdc.SetBrush(wx.Brush(palette.primary_container))
            gcdc.DrawEllipse(centre_x - dot, top - dot // 2, dot * 2, dot * 2)
            gcdc.SetBrush(wx.Brush(palette.primary))
        else:
            gcdc.SetBrush(wx.Brush(palette.outline_variant))
        gcdc.DrawEllipse(centre_x - dot // 2, top, dot, dot)
        gcdc.SetPen(wx.Pen(palette.outline_variant, 1))
        gcdc.DrawLine(centre_x, top + dot, centre_x, height - tokens.scaled(4))
        del gcdc


class _EdgePanel(wx.Panel):
    """A header or footer strip carrying one hairline edge."""

    def __init__(self, parent: wx.Window, *, edge: str = "bottom") -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self.edge = edge
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.refresh_theme()

    def refresh_theme(self) -> None:
        """Re-read the palette for the strip and everything on it."""
        self.SetBackgroundColour(tokens.palette().surface)
        for child in self.GetChildren():
            refresh = getattr(child, "refresh_theme", None)
            if callable(refresh):
                refresh()
        self.Refresh()

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        dc, gcdc = widgets.paint_context(self, palette.surface)
        width, height = self.GetClientSize()
        gcdc.SetPen(wx.Pen(palette.outline_variant, 1))
        if self.edge == "bottom":
            gcdc.DrawLine(0, height - 1, width, height - 1)
        else:
            gcdc.DrawLine(0, 0, width, 0)
        del gcdc


class SpecDialog(wx.Dialog):
    """One window rendered from a :class:`Spec`, with a live window search.

    The header carries the surface's category, its title, a compact search over
    everything the window contains, and a close button; the body renders one
    block per section; the footer carries the surface's own actions and the
    filled confirm button.  The search filters the visible sections and rows as
    it is typed and says plainly when nothing matches, rather than showing an
    empty window and leaving the reader to guess whether the surface is broken
    or the query simply found nothing.
    """

    def __init__(
        self,
        parent: wx.Window,
        spec: Spec,
        *,
        on_action: Optional[Callable[[Action], None]] = None,
    ) -> None:
        super().__init__(
            parent,
            title=spec.title,
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
            name=f"{spec.eyebrow}: {spec.title}",
        )
        self.spec = spec
        self.on_action = on_action
        self._opener = wx.Window.FindFocus()
        self._focus_returned = False
        self.window_search = SearchState(label=f"{spec.title} window")
        self._section_states: Dict[int, SearchState] = {}
        self._section_bars: Dict[int, widgets.SearchBar] = {}
        self._focus_request: Optional[int] = None
        self._theme_unsubscribe = tokens.register_theme_listener(self.refresh_theme)

        self.header = _EdgePanel(self, edge="bottom")
        self.eyebrow = _Eyebrow(self.header, spec.eyebrow)
        self.title_text = wx.StaticText(self.header, label=spec.title)
        self.title_text.SetName(spec.title)
        self.search_bar = widgets.SearchBar(
            self.header,
            "Search this window",
            self.window_search,
            on_change=self._on_window_search,
            compact=True,
        )
        self.close_button = widgets.StudioButton(
            self.header,
            "✕",
            variant="icon",
            on_click=self.close,
            name="Close this window",
            hint="Close this window",
            height=30,
            min_width=34,
        )
        titles = wx.BoxSizer(wx.VERTICAL)
        titles.Add(self.eyebrow, 0, wx.BOTTOM, tokens.scaled(5))
        titles.Add(self.title_text, 0)
        controls = wx.BoxSizer(wx.HORIZONTAL)
        controls.Add(self.search_bar, 0, wx.ALIGN_CENTER_VERTICAL)
        controls.Add(
            self.close_button,
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            tokens.scaled(tokens.SPACE_XS),
        )
        header_row = wx.BoxSizer(wx.HORIZONTAL)
        header_row.Add(titles, 1, wx.ALIGN_TOP)
        header_row.Add(
            controls, 0, wx.ALIGN_TOP | wx.LEFT, tokens.scaled(tokens.SPACE_MD)
        )
        self.header.SetSizer(
            self._padded(header_row, tokens.scaled(18), tokens.scaled(16))
        )

        self.body = wx.ScrolledWindow(self, style=wx.VSCROLL | wx.TAB_TRAVERSAL)
        self.body.SetScrollRate(0, tokens.scaled(12))
        self.body_sizer = wx.BoxSizer(wx.VERTICAL)
        self.body.SetSizer(self.body_sizer)

        self.footer = _EdgePanel(self, edge="top")
        self.footer_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.action_buttons: List[widgets.StudioButton] = []
        for action in spec.actions:
            button = widgets.StudioButton(
                self.footer,
                action.label,
                variant=ACTION_VARIANTS.get(action.kind, "outlined"),
                on_click=lambda item=action: self.run_action(item),
                name=action.label,
                hint=self._action_hint(action),
                height=40,
            )
            self.action_buttons.append(button)
            self.footer_sizer.Add(button, 0, wx.RIGHT, tokens.scaled(tokens.SPACE_SM))
        self.footer_sizer.AddStretchSpacer(1)
        self.confirm_button = widgets.StudioButton(
            self.footer,
            spec.confirm,
            variant="filled",
            on_click=self.confirm,
            name=spec.confirm,
            hint=f"{spec.confirm} and close this window",
            height=40,
        )
        self.footer_sizer.Add(self.confirm_button, 0)
        self.footer.SetSizer(
            self._padded(self.footer_sizer, tokens.scaled(18), tokens.scaled(14))
        )

        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(self.header, 0, wx.EXPAND)
        root.Add(self.body, 1, wx.EXPAND)
        root.Add(self.footer, 0, wx.EXPAND)
        self.SetSizer(root)
        self.rebuild()
        self.refresh_theme()
        self.SetClientSize(self._preferred_size())
        self.SetMinSize(wx.Size(tokens.scaled(420), tokens.scaled(320)))
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
        self.Bind(wx.EVT_CLOSE, self._on_close)
        self.Bind(wx.EVT_WINDOW_DESTROY, self._on_destroy)
        self.confirm_button.SetFocus()

    # ------------------------------------------------------------------
    # construction helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _padded(sizer: wx.Sizer, horizontal: int, vertical: int) -> wx.Sizer:
        """Wrap ``sizer`` in the padding the design gives a header or footer."""
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.AddSpacer(vertical)
        outer.Add(sizer, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, horizontal)
        outer.AddSpacer(vertical)
        return outer

    def _preferred_size(self) -> wx.Size:
        width = tokens.scaled(max(360, int(self.spec.width)))
        best = self.GetBestSize().height or tokens.scaled(480)
        height = min(tokens.scaled(MAX_DIALOG_HEIGHT), max(tokens.scaled(280), best))
        try:
            index = wx.Display.GetFromWindow(self)
            area = wx.Display(index if index != wx.NOT_FOUND else 0).GetClientArea()
            width = min(width, area.width - tokens.scaled(48))
            height = min(height, area.height - tokens.scaled(48))
        except Exception:  # pragma: no cover - platform boundary
            log.debug("Could not read the display size; using the spec width")
        return wx.Size(width, height)

    @staticmethod
    def _action_hint(action: Action) -> str:
        if action.surface:
            return f"Open {action.surface}"
        if action.command:
            return f"Run {action.command}"
        return action.label

    # ------------------------------------------------------------------
    # searching
    # ------------------------------------------------------------------
    def active_states(self) -> List[SearchState]:
        """Return every search state currently narrowing this window."""
        states = [self.window_search] + list(self._section_states.values())
        return [state for state in states if state.is_active()]

    def _narrow(self, section: Section) -> Optional[Section]:
        """Return ``section`` as the searches leave it, or ``None`` if dropped."""
        current = Spec(
            key=self.spec.key,
            eyebrow="",
            title="",
            sections=(section,),
        )
        for state in self.active_states():
            narrowed = spec_api.searchable(current, state)
            if not narrowed.sections:
                return None
            current = narrowed
        return current.sections[0]

    def _on_window_search(self, _state: SearchState) -> None:
        self._focus_request = None
        self.rebuild()

    def _on_section_search(self, index: int) -> None:
        self._focus_request = index
        self.rebuild()

    # ------------------------------------------------------------------
    # body
    # ------------------------------------------------------------------
    def rebuild(self) -> None:
        """Re-render the body for the current searches."""
        self.body.DestroyChildren()
        self._section_bars = {}
        self.body_sizer = wx.BoxSizer(wx.VERTICAL)
        self.body.SetSizer(self.body_sizer)
        gap = tokens.scaled(18)
        if self.spec.intro:
            intro = _Paragraph(self.body, self.spec.intro)
            self.body_sizer.Add(intro, 0, wx.EXPAND | wx.ALL, gap)
        shown = 0
        for index, section in enumerate(self.spec.sections):
            narrowed = self._narrow(section)
            if narrowed is None:
                continue
            if narrowed.kind != "search":
                shown += 1
            block = self._render_section(index, narrowed)
            if block is not None:
                self.body_sizer.Add(
                    block, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, gap
                )
        if shown == 0 and self.active_states():
            self.body_sizer.Add(
                _Paragraph(
                    self.body,
                    self.window_search.describe_matches(0, "section")
                    + " Clear the search to see the whole window again.",
                ),
                0,
                wx.EXPAND | wx.ALL,
                gap,
            )
        self.body.Layout()
        self.body.FitInside()
        self.Layout()
        self.refresh_theme()
        self._restore_search_focus()

    def _restore_search_focus(self) -> None:
        index = self._focus_request
        self._focus_request = None
        if index is None:
            return
        bar = self._section_bars.get(index)
        if bar is None:
            return
        bar.SetFocus()
        bar.field.text.SetInsertionPointEnd()

    def _render_section(self, index: int, section: Section) -> Optional[wx.Window]:
        """Build one section's block, titled where the section carries a title."""
        collapsible = section.kind == "code" or (
            section.kind == "note" and bool(section.title)
        )
        if collapsible:
            container = widgets.CollapsibleSection(
                self.body,
                section.title or section.kind.title(),
                expanded=False,
                remember_key=f"{self.spec.key}.{index}.{section.kind}",
            )
            host = container.body
            host_sizer = container.body_sizer
        else:
            container = wx.Panel(self.body, style=wx.TAB_TRAVERSAL)
            container.SetBackgroundColour(tokens.palette().surface)
            host = container
            host_sizer = wx.BoxSizer(wx.VERTICAL)
            container.SetSizer(host_sizer)
            if section.title:
                host_sizer.Add(
                    widgets.SectionLabel(host, section.title),
                    0,
                    wx.BOTTOM,
                    tokens.scaled(9),
                )
        content = self._render_content(host, index, section)
        for child, expand in content:
            host_sizer.Add(
                child, 0, (wx.EXPAND if expand else 0) | wx.BOTTOM, tokens.scaled(7)
            )
        return container

    def _render_content(
        self, host: wx.Window, index: int, section: Section
    ) -> List[tuple]:
        """Return the controls for one section, paired with their expand flag."""
        renderer = getattr(self, f"_render_{section.kind}", None)
        if renderer is None:
            log.error("No renderer for section kind %r", section.kind)
            return [
                (
                    _NoteBlock(
                        host,
                        f"This surface asks for a “{section.kind}” block, which "
                        f"this window cannot render yet.",
                        role="error",
                    ),
                    True,
                )
            ]
        return renderer(host, index, section)

    # -- the sixteen section kinds ------------------------------------------
    def _render_search(
        self, host: wx.Window, index: int, section: Section
    ) -> List[tuple]:
        state = self._section_states.setdefault(
            index, SearchState(label=section.hint or "these records")
        )
        bar = widgets.SearchBar(
            host,
            section.hint or "Search this window",
            state,
            on_change=lambda _state, key=index: self._on_section_search(key),
        )
        self._section_bars[index] = bar
        return [(bar, True)]

    def _render_fields(
        self, host: wx.Window, _index: int, section: Section
    ) -> List[tuple]:
        grid = wx.FlexGridSizer(0, 2, tokens.scaled(14), tokens.scaled(12))
        grid.AddGrowableCol(0, 1)
        grid.AddGrowableCol(1, 1)
        panel = wx.Panel(host, style=wx.TAB_TRAVERSAL)
        panel.SetBackgroundColour(tokens.palette().surface)
        for field in section.fields:
            grid.Add(
                widgets.OutlinedField(
                    panel,
                    field.label,
                    field.value,
                    placeholder=field.placeholder,
                    mono=True,
                ),
                1,
                wx.EXPAND,
            )
        panel.SetSizer(grid)
        return [(panel, True)]

    def _render_selects(
        self, host: wx.Window, _index: int, section: Section
    ) -> List[tuple]:
        grid = wx.FlexGridSizer(0, 2, tokens.scaled(10), tokens.scaled(10))
        grid.AddGrowableCol(0, 1)
        grid.AddGrowableCol(1, 1)
        panel = wx.Panel(host, style=wx.TAB_TRAVERSAL)
        panel.SetBackgroundColour(tokens.palette().surface)
        for select in section.selects:
            grid.Add(
                widgets.SearchableChoice(
                    panel,
                    select.label,
                    select.options,
                    select.current(),
                ),
                1,
                wx.EXPAND,
            )
        panel.SetSizer(grid)
        return [(panel, True)]

    def _render_list(
        self, host: wx.Window, _index: int, section: Section
    ) -> List[tuple]:
        return [
            (
                widgets.ListRow(host, row.name, row.detail, row.tag, swatch=row.swatch),
                True,
            )
            for row in section.rows
        ]

    def _render_keys(
        self, host: wx.Window, _index: int, section: Section
    ) -> List[tuple]:
        grid = wx.FlexGridSizer(0, 2, tokens.scaled(7), tokens.scaled(7))
        grid.AddGrowableCol(0, 1)
        grid.AddGrowableCol(1, 1)
        panel = wx.Panel(host, style=wx.TAB_TRAVERSAL)
        panel.SetBackgroundColour(tokens.palette().surface)
        for binding in section.keys:
            grid.Add(_KeyRow(panel, binding.action, binding.binding), 1, wx.EXPAND)
        panel.SetSizer(grid)
        return [(panel, True)]

    def _render_tree(
        self, host: wx.Window, _index: int, section: Section
    ) -> List[tuple]:
        return [(widgets.TreeRows(host, section.tree), True)]

    def _render_chips(
        self, host: wx.Window, _index: int, section: Section
    ) -> List[tuple]:
        panel = wx.Panel(host, style=wx.TAB_TRAVERSAL)
        panel.SetBackgroundColour(tokens.palette().surface)
        wrap = wx.WrapSizer(wx.HORIZONTAL)
        for label in section.chips:
            wrap.Add(
                widgets.Chip(panel, label),
                0,
                wx.RIGHT | wx.BOTTOM,
                tokens.scaled(tokens.SPACE_SM),
            )
        panel.SetSizer(wrap)
        return [(panel, True)]

    def _render_checks(
        self, host: wx.Window, _index: int, section: Section
    ) -> List[tuple]:
        return [
            (_CheckRow(host, check.label, check.hint, check.value), True)
            for check in section.checks
        ]

    def _render_ranges(
        self, host: wx.Window, _index: int, section: Section
    ) -> List[tuple]:
        return [
            (
                widgets.RangeRow(
                    host,
                    item.label,
                    item.value,
                    item.min,
                    item.max,
                    step=item.step,
                ),
                True,
            )
            for item in section.ranges
        ]

    def _render_swatches(
        self, host: wx.Window, _index: int, section: Section
    ) -> List[tuple]:
        panel = wx.Panel(host, style=wx.TAB_TRAVERSAL)
        panel.SetBackgroundColour(tokens.palette().surface)
        row = wx.WrapSizer(wx.HORIZONTAL)
        for swatch in section.swatches:
            row.Add(
                widgets.Swatch(panel, swatch.colour, name=swatch.name),
                0,
                wx.RIGHT | wx.BOTTOM,
                tokens.scaled(tokens.SPACE_SM),
            )
        panel.SetSizer(row)
        blocks: List[tuple] = [(panel, True)]
        if section.hint:
            hint = wx.StaticText(host, label=section.hint)
            hint.SetName(section.hint)
            hint.SetFont(tokens.mono_font(host, widgets.point_size(12)))
            hint.SetForegroundColour(tokens.palette().on_surface_variant)
            blocks.append((hint, False))
        return blocks

    def _render_progress(
        self, host: wx.Window, _index: int, section: Section
    ) -> List[tuple]:
        return [
            (
                widgets.ProgressRow(
                    host,
                    section.hint,
                    section.progress_fraction,
                    section.progress_label,
                ),
                True,
            )
        ]

    def _render_keygate(
        self, host: wx.Window, _index: int, section: Section
    ) -> List[tuple]:
        blocks: List[tuple] = []
        if section.hint:
            blocks.append((_NoteBlock(host, section.hint, role="error"), True))
        blocks.append(
            (
                widgets.KeyGate(
                    host,
                    on_authorize=self._gate_authorized,
                    on_exit=self._gate_exited,
                ),
                True,
            )
        )
        return blocks

    def _render_code(
        self, host: wx.Window, _index: int, section: Section
    ) -> List[tuple]:
        return [(_CodeBlock(host, section.code), True)]

    def _render_note(
        self, host: wx.Window, _index: int, section: Section
    ) -> List[tuple]:
        return [(_NoteBlock(host, section.hint), True)]

    def _render_commits(
        self, host: wx.Window, _index: int, section: Section
    ) -> List[tuple]:
        return [
            (
                _CommitRow(
                    host,
                    commit.message,
                    commit.meta,
                    commit.head,
                    on_action=lambda label, item=commit: self.run_action(
                        Action(label=f"{label}: {item.message}", kind="outlined")
                    ),
                ),
                True,
            )
            for commit in section.commits
        ]

    def _render_texture(
        self, host: wx.Window, _index: int, section: Section
    ) -> List[tuple]:
        panel = wx.Panel(host, style=wx.TAB_TRAVERSAL)
        panel.SetBackgroundColour(tokens.palette().surface)
        preview = wx.BoxSizer(wx.VERTICAL)
        preview.Add(widgets.TextureTile(panel, section.block_id), 0)
        preview.Add(
            widgets.FaceRow(panel, section.block_id), 0, wx.TOP, tokens.scaled(7)
        )
        details = wx.BoxSizer(wx.VERTICAL)
        identifier = wx.StaticText(panel, label=section.block_id)
        identifier.SetName(section.block_id)
        identifier.SetFont(tokens.mono_font(panel, widgets.point_size(12)))
        identifier.SetForegroundColour(tokens.palette().on_surface)
        details.Add(identifier, 0, wx.BOTTOM, tokens.scaled(9))
        details.Add(
            _Paragraph(panel, section.hint or spec_api.TEXTURE_HINT, size_px=12),
            0,
            wx.EXPAND | wx.BOTTOM,
            tokens.scaled(9),
        )
        details.Add(
            widgets.ImageSlot(
                panel,
                hint=spec_api.TEXTURE_SLOT_HINT,
                slot_id=section.slot_id,
                on_image=lambda path: self.run_action(
                    Action(label=f"Loaded texture {path}", kind="text")
                ),
            ),
            0,
            wx.EXPAND | wx.BOTTOM,
            tokens.scaled(9),
        )
        buttons = wx.BoxSizer(wx.HORIZONTAL)
        buttons.Add(
            widgets.StudioButton(
                panel,
                "Load resource pack",
                variant="tonal",
                on_click=lambda: self.run_action(
                    Action(label="Load resource pack", kind="tonal")
                ),
                name="Load resource pack",
                hint="Show the real textures from a resource pack",
                height=30,
            ),
            0,
            wx.RIGHT,
            tokens.scaled(6),
        )
        buttons.Add(
            widgets.StudioButton(
                panel,
                "Use vanilla textures",
                variant="outlined",
                on_click=lambda: self.run_action(
                    Action(label="Use vanilla textures", kind="outlined")
                ),
                name="Use vanilla textures",
                hint="Show the textures from a detected Minecraft install",
                height=30,
            ),
            0,
        )
        details.Add(buttons, 0)
        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(preview, 0, wx.RIGHT, tokens.scaled(14))
        row.Add(details, 1, wx.EXPAND)
        panel.SetSizer(row)
        return [(panel, True)]

    # ------------------------------------------------------------------
    # actions
    # ------------------------------------------------------------------
    def run_action(self, action: Action) -> None:
        """Route one action to a surface, the shell, or an honest report."""
        if action.surface and self._open_surface(action.surface):
            return
        if self.on_action is not None:
            widgets.invoke(self.on_action, action)
            return
        self._report_unhandled(action)

    def _open_surface(self, key: str) -> bool:
        """Open another surface, preferring the shell's own registry."""
        try:
            from amulet_map_editor.api.studio import surfaces
        except ImportError:
            surfaces = None
        if surfaces is not None:
            opener = getattr(surfaces, "open_surface", None)
            if callable(opener):
                try:
                    if opener(self, key) is not None:
                        return True
                except Exception:
                    log.exception("Could not open the surface %r", key)
        if spec_registry.get(key) is not None:
            return open_spec(self, key) is not None
        return False

    def _report_unhandled(self, action: Action) -> None:
        from amulet_map_editor.api.wx import nonblocking

        detail = action.command or action.surface or "no target"
        nonblocking.notify(
            self,
            action.label,
            "No project shell is connected to this window, so nothing ran.",
            severity="warning",
            details=f"Surface: {self.spec.key} · Action target: {detail}",
        )

    def _gate_authorized(self) -> None:
        self.run_action(Action(label=f"{self.spec.title} authorised", kind="danger"))

    def _gate_exited(self) -> None:
        from amulet_map_editor.api.wx import nonblocking

        nonblocking.notify(
            self,
            "Cancelled",
            f"{self.spec.title} was cancelled and nothing was changed.",
        )

    def confirm(self) -> None:
        """Run the confirm action where it has one, then close the window."""
        label = (self.spec.confirm or "").strip()
        if label.lower() not in ("close", "done", "ok", ""):
            self.run_action(Action(label=label, kind="filled"))
        self.close()

    def close(self) -> None:
        """Close the window and hand the keyboard back to whatever opened it."""
        self._return_focus()
        self.Close()

    # ------------------------------------------------------------------
    # window plumbing
    # ------------------------------------------------------------------
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
            self.close()
            return
        if code in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            focus = wx.Window.FindFocus()
            if isinstance(focus, wx.TextCtrl) and focus.IsMultiLine():
                event.Skip()
                return
            if hasattr(focus, "activate"):
                event.Skip()
                return
            self.confirm()
            return
        event.Skip()

    def _on_close(self, event: wx.CloseEvent) -> None:
        self._return_focus()
        event.Skip()

    def _on_destroy(self, event: wx.WindowDestroyEvent) -> None:
        if event.GetEventObject() is self and self._theme_unsubscribe is not None:
            self._theme_unsubscribe()
            self._theme_unsubscribe = None
        event.Skip()

    def refresh_theme(self) -> None:
        """Re-read the tokens and repaint the whole window."""
        try:
            if self.IsBeingDeleted():
                return
            palette = tokens.palette()
            self.SetBackgroundColour(palette.surface)
            self.body.SetBackgroundColour(palette.surface)
            self.title_text.SetForegroundColour(palette.on_surface)
            self.title_text.SetFont(tokens.font(self, widgets.point_size(19)))
            for strip in (self.header, self.footer):
                strip.refresh_theme()
            for child in self.body.GetChildren():
                refresh = getattr(child, "refresh_theme", None)
                if callable(refresh):
                    refresh()
                else:
                    child.SetBackgroundColour(palette.surface)
            self.Refresh()
        except RuntimeError:
            self._theme_unsubscribe = None


def open_spec(parent: wx.Window, key: str) -> Optional[SpecDialog]:
    """Open the surface registered under ``key``, reusing an open window.

    Surfaces are non-modal so several can be open together; the modeless helper
    keeps one window per key rather than stacking duplicates every time a
    ribbon button is pressed.  An unknown key is logged and reported as
    ``None`` rather than opening an empty window that looks like a defect.
    """
    spec = spec_registry.get(key)
    if spec is None:
        log.error("No Studio surface is registered under the key %r", key)
        return None
    from amulet_map_editor.api.wx.modeless import show_modeless_dialog

    return show_modeless_dialog(
        parent, f"studio.spec.{key}", lambda owner: SpecDialog(owner, spec)
    )


__all__ = ["ACTION_VARIANTS", "MAX_DIALOG_HEIGHT", "SpecDialog", "open_spec"]
