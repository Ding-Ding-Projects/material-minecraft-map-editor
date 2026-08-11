"""The Memory Console: a rail of thirteen views over this machine's records.

This is one of the two surfaces the declarative spec renderer cannot express.
A spec is a vertical stack of sections; the console is a persistent navigation
rail beside a twelve-column card grid, and one of its views replaces that grid
entirely with a two-pane article reader.  Rather than bend the spec language
until it could describe both, the window is built by hand and its content lives
as data in :mod:`amulet_map_editor.api.studio.memory_content`.

The window is shown non-modally, like every other reference surface in the
shell: it is something to read while working, not a decision that has to be
answered before anything else can happen.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import wx

import amulet_map_editor
from amulet_map_editor.api.studio import copy as studio_copy
from amulet_map_editor.api.studio import memory_content, tokens, widgets
from amulet_map_editor.api.studio.memory_content import (
    ARTICLES,
    DOCS_VIEW_KEY,
    DOMAINS,
    GRID_COLUMNS,
    MEMORY_VIEWS,
    Article,
    CardRow,
    MemoryCard,
    MemoryView,
    search_articles,
)
from amulet_map_editor.api.studio.search import SearchState

log = logging.getLogger(__name__)

#: The window size the design draws, before the interface scale is applied.
DIALOG_WIDTH = 1080
DIALOG_HEIGHT = 720

#: The navigation rail's fixed width, and the height one rail entry draws at
#: before the density token raises it.
RAIL_WIDTH = 150
RAIL_ITEM_HEIGHT = 34

#: The article list scrolls past this height rather than growing the page, so
#: the reader beside it stays visible however many articles match.
ARTICLE_LIST_HEIGHT = 420

#: The reading measure for an article body and a view subtitle.  Prose set much
#: wider than this is measurably harder to read, and the window is wide.
READING_MEASURE = 620

#: The uppercase caption above every view title, transcribed from the design.
CONSOLE_EYEBROW = "Canonical guidance control plane"

#: The window title, and the two runs the header draws it as.
CONSOLE_TITLE = "Agent Global Memory Console"
TITLE_PRIMARY = "Agent Global Memory"
TITLE_SECONDARY = "Console"

#: wxPython 4.1 added a medium weight; older builds fall back to normal rather
#: than raising while the header is being built.
_MEDIUM = getattr(wx, "FONTWEIGHT_MEDIUM", wx.FONTWEIGHT_NORMAL)
_LIGHT = getattr(wx, "FONTWEIGHT_LIGHT", wx.FONTWEIGHT_NORMAL)


def repository_root() -> Path:
    """Return the directory the documentation sources would live under.

    An article's path is recorded relative to the repository, which is where it
    exists in a source checkout.  An installed build has the article text
    bundled but not the file, and that difference is reported honestly by the
    editor bridge rather than guessed at here.
    """
    return Path(amulet_map_editor.__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# small owner-drawn blocks
# ---------------------------------------------------------------------------


class _Painted(wx.Control):
    """A static owner-drawn block that repaints when the theme changes.

    These are records rather than controls -- a caption, a paragraph, a badge
    -- so they are deliberately not tab stops.  Putting unactionable blocks
    between the reader and the next button would make the keyboard route
    through the window worse rather than better.
    """

    def __init__(self, parent: wx.Window, name: str) -> None:
        super().__init__(parent, style=wx.BORDER_NONE)
        self.SetName(name or "Text")
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

    # Every block below defines its own ``_on_paint``; the base deliberately
    # does not, so a block that forgot one fails while it is being constructed
    # rather than rendering as a blank rectangle nobody notices.


class _Eyebrow(_Painted):
    """The small uppercase primary caption above a title."""

    TRACKING = 1

    def __init__(self, parent: wx.Window, text: str, *, size_px: int = 11) -> None:
        super().__init__(parent, str(text) or "Category")
        self.text = str(text)
        self.size_px = size_px

    def _font(self) -> wx.Font:
        return tokens.font(self, widgets.point_size(self.size_px), wx.FONTWEIGHT_BOLD)

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        dc = wx.ClientDC(self)
        dc.SetFont(self._font())
        width = widgets.tracked_width(
            dc, self.text.upper(), tokens.scaled(self.TRACKING)
        )
        return wx.Size(width + 2, dc.GetCharHeight() + tokens.scaled(4))

    def set_text(self, text: str) -> None:
        """Replace the caption and re-measure it."""
        self.text = str(text)
        self.SetName(self.text or "Category")
        self.InvalidateBestSize()
        self.SetMinSize(self.DoGetBestSize())
        self.Refresh()

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        dc, gcdc = widgets.paint_context(self, self._backdrop(palette))
        gcdc.SetFont(self._font())
        gcdc.SetTextForeground(palette.primary)
        widgets.draw_tracked_text(
            gcdc, self.text.upper(), 0, 0, tokens.scaled(self.TRACKING)
        )
        del gcdc


class _Paragraph(_Painted):
    """Word-wrapped prose that re-wraps to whatever width it is given.

    Blank lines in the source are preserved as paragraph breaks, which is how
    an article body keeps its shape, and an optional measure stops a line
    growing past a readable length in a window this wide.
    """

    MAX_LINES = 400

    def __init__(
        self,
        parent: wx.Window,
        text: str,
        *,
        size_px: int = 13,
        role: str = "on_surface_variant",
        line_height: float = 1.55,
        max_width: int = 0,
    ) -> None:
        super().__init__(parent, str(text)[:120] or "Paragraph")
        self.text = str(text)
        self.size_px = size_px
        self.role = role
        self.line_height = float(line_height)
        self.max_width = int(max_width)
        self._wrapped_at = 0
        self.Bind(wx.EVT_SIZE, self._on_resize)

    def _measure(self) -> int:
        """Return the width this prose is allowed to wrap at."""
        width = self.GetSize().width or tokens.scaled(560)
        if self.max_width:
            width = min(width, tokens.scaled(self.max_width))
        return max(40, width)

    def _on_resize(self, event: wx.SizeEvent) -> None:
        """Re-wrap once per real width change.

        Recomputing on every size event re-enters the parent's layout in a
        loop; comparing against the width the text was last wrapped at makes
        the work happen exactly once per genuine change.
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

    def _lines(self, dc: wx.DC) -> List[str]:
        return widgets.wrap_text(dc, self.text, self._measure(), self.MAX_LINES)

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        dc = wx.ClientDC(self)
        dc.SetFont(tokens.font(self, widgets.point_size(self.size_px)))
        lines = self._lines(dc)
        height = int(dc.GetCharHeight() * self.line_height * len(lines)) + 2
        return wx.Size(self.GetSize().width or tokens.scaled(560), height)

    def set_text(self, text: str) -> None:
        """Replace the prose, re-measure it, and repaint."""
        self.text = str(text)
        self.SetName(self.text[:120] or "Paragraph")
        self._wrapped_at = 0
        self.InvalidateBestSize()
        self.SetMinSize(wx.Size(-1, self.DoGetBestSize().height))
        self.Refresh()

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        dc, gcdc = widgets.paint_context(self, self._backdrop(palette))
        gcdc.SetFont(tokens.font(self, widgets.point_size(self.size_px)))
        gcdc.SetTextForeground(palette.role(self.role))
        step = int(gcdc.GetCharHeight() * self.line_height)
        y = 0
        for line in self._lines(gcdc):
            gcdc.DrawText(line, 0, y)
            y += step
        del gcdc


class _Badge(_Painted):
    """The small rounded primary square that opens the header."""

    SIDE = 24

    def __init__(self, parent: wx.Window, letter: str) -> None:
        super().__init__(parent, "Application badge")
        self.letter = str(letter)[:1]
        side = tokens.scaled(self.SIDE)
        self.SetInitialSize(wx.Size(side, side))

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        side = tokens.scaled(self.SIDE)
        return wx.Size(side, side)

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        dc, gcdc = widgets.paint_context(self, self._backdrop(palette))
        width, height = self.GetClientSize()
        tokens.draw_round_rect(
            gcdc, wx.Rect(0, 0, width, height), tokens.scaled(7), palette.primary
        )
        gcdc.SetFont(tokens.font(self, widgets.point_size(12), wx.FONTWEIGHT_BOLD))
        gcdc.SetTextForeground(palette.on_primary)
        text_width, text_height = gcdc.GetTextExtent(self.letter)
        gcdc.DrawText(
            self.letter, (width - text_width) // 2, (height - text_height) // 2
        )
        del gcdc


class _CodeBlock(wx.Panel):
    """A monospaced, selectable, read-only transcript block.

    It is a real text control rather than painted text so its content can be
    selected and copied; a transcript nobody can copy is a picture of one.
    """

    MAX_VISIBLE_LINES = 20

    def __init__(self, parent: wx.Window, code: str, *, name: str = "Record") -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self.code = str(code)
        self.text = wx.TextCtrl(
            self,
            value=self.code,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.BORDER_NONE | wx.TE_DONTWRAP,
        )
        self.text.SetName(name)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.text, 1, wx.EXPAND | wx.ALL, tokens.scaled(11))
        self.SetSizer(sizer)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.refresh_theme()
        self._resize_to_content()

    def set_code(self, code: str) -> None:
        """Replace the transcript and re-measure the block."""
        self.code = str(code)
        self.text.SetValue(self.code)
        self._resize_to_content()
        self.Refresh()

    def _resize_to_content(self) -> None:
        lines = min(self.MAX_VISIBLE_LINES, max(1, self.code.count("\n") + 1))
        self.SetMinSize(wx.Size(-1, tokens.scaled(lines * 17 + 24)))

    def refresh_theme(self) -> None:
        """Re-read the palette for the block and the text inside it."""
        palette = tokens.palette()
        parent = self.GetParent()
        backdrop = parent.GetBackgroundColour() if parent else palette.surface
        self.SetBackgroundColour(backdrop if backdrop.IsOk() else palette.surface)
        self.text.SetBackgroundColour(palette.surface_container_high)
        self.text.SetForegroundColour(palette.on_surface_variant)
        self.text.SetFont(tokens.mono_font(self, widgets.point_size(11)))
        self.Refresh()

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        dc, gcdc = widgets.paint_context(self, self.GetBackgroundColour())
        width, height = self.GetClientSize()
        tokens.draw_round_rect(
            gcdc,
            wx.Rect(0, 0, width, height),
            tokens.scaled(9),
            palette.surface_container_high,
        )
        del gcdc


class _EdgeStrip(wx.Panel):
    """A container painting one role and a hairline along one edge."""

    def __init__(
        self,
        parent: wx.Window,
        *,
        edge: str = "bottom",
        role: str = "surface_container",
    ) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self.edge = edge
        self.role = role
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
        dc, gcdc = widgets.paint_context(self, palette.role(self.role))
        width, height = self.GetClientSize()
        gcdc.SetPen(wx.Pen(palette.outline_variant, 1))
        if self.edge == "bottom":
            gcdc.DrawLine(0, height - 1, width, height - 1)
        elif self.edge == "right":
            gcdc.DrawLine(width - 1, 0, width - 1, height)
        else:
            gcdc.DrawLine(0, 0, width, 0)
        del gcdc


# ---------------------------------------------------------------------------
# interactive blocks
# ---------------------------------------------------------------------------


class _Tappable(wx.Control):
    """Hover, press, focus, and activation shared by the console's own buttons.

    Activation is bound to the mouse and to Enter and Space alike: a control
    reachable only with a pointer is unreachable to anybody who does not use
    one, which is a completion blocker rather than a rough edge.
    """

    def __init__(
        self,
        parent: wx.Window,
        name: str,
        *,
        on_click: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(parent, style=wx.BORDER_NONE | wx.WANTS_CHARS)
        self.on_click = on_click
        self._hovered = False
        self._pressed = False
        self.SetName(name or "Button")
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetCursor(wx.Cursor(wx.CURSOR_HAND))
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.Bind(wx.EVT_ENTER_WINDOW, self._on_enter)
        self.Bind(wx.EVT_LEAVE_WINDOW, self._on_leave)
        self.Bind(wx.EVT_LEFT_DOWN, self._on_left_down)
        self.Bind(wx.EVT_LEFT_UP, self._on_left_up)
        self.Bind(wx.EVT_KEY_DOWN, self._on_key_down)
        self.Bind(wx.EVT_SET_FOCUS, self._on_focus_change)
        self.Bind(wx.EVT_KILL_FOCUS, self._on_focus_change)

    # -- behaviour -----------------------------------------------------------
    def activate(self) -> None:
        """Run the control's action, however it was reached."""
        if not self.IsEnabled():
            return
        widgets.invoke(self.on_click)

    def refresh_theme(self) -> None:
        """Repaint with the live palette."""
        self.Refresh()

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

    def _on_focus_change(self, event: wx.FocusEvent) -> None:
        self.Refresh()
        event.Skip()

    def _backdrop(self, palette: tokens.StudioPalette) -> wx.Colour:
        parent = self.GetParent()
        colour = parent.GetBackgroundColour() if parent else palette.surface
        return colour if colour.IsOk() else palette.surface

    # Each control below defines its own ``_on_paint`` and, where it does more
    # than call back, its own ``activate``.  Neither is defined here, for the
    # same reason the static blocks omit theirs.


class _RailItem(_Tappable):
    """One navigation entry: a glyph, a label, and its selected state."""

    GLYPH_WIDTH = 16
    GAP = 10
    PADDING = 10

    def __init__(
        self,
        parent: wx.Window,
        view: MemoryView,
        *,
        selected: bool = False,
        on_click: Optional[Callable[[], None]] = None,
    ) -> None:
        self.view = view
        self.selected = bool(selected)
        super().__init__(parent, self._accessible_name(), on_click=on_click)
        self.SetToolTip(view.subtitle)
        self.SetInitialSize(self.DoGetBestSize())

    def _accessible_name(self) -> str:
        state = ", selected" if self.selected else ""
        return f"{self.view.label} view{state}"

    def set_selected(self, selected: bool) -> None:
        """Mark or unmark the entry without running its action."""
        self.selected = bool(selected)
        self.SetName(self._accessible_name())
        self.Refresh()

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        dc = wx.ClientDC(self)
        dc.SetFont(tokens.font(self, widgets.point_size(13)))
        width = (
            tokens.scaled(self.PADDING) * 2
            + tokens.scaled(self.GLYPH_WIDTH)
            + tokens.scaled(self.GAP)
            + dc.GetTextExtent(self.view.label)[0]
        )
        height = max(
            tokens.scaled(RAIL_ITEM_HEIGHT),
            tokens.control_height(),
            dc.GetCharHeight() + tokens.scaled(10),
        )
        return wx.Size(width, height)

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        dc, gcdc = widgets.paint_context(self, self._backdrop(palette))
        width, height = self.GetClientSize()
        rect = wx.Rect(0, 0, width, height)
        radius = tokens.scaled(9)
        if self.selected:
            fill = palette.primary_container
            ink = palette.on_primary_container
        else:
            ink = palette.on_surface
            fill = None
            if self._pressed:
                fill = tokens.blend(
                    palette.surface_container_high, palette.on_surface, 0.10
                )
            elif self._hovered:
                fill = palette.surface_container_high
        if fill is not None:
            tokens.draw_round_rect(gcdc, rect, radius, fill)
        left = tokens.scaled(self.PADDING)
        gcdc.SetTextForeground(ink)
        gcdc.SetFont(tokens.font(self, widgets.point_size(13)))
        glyph_height = gcdc.GetCharHeight()
        gcdc.DrawText(self.view.glyph, left, (height - glyph_height) // 2)
        left += tokens.scaled(self.GLYPH_WIDTH) + tokens.scaled(self.GAP)
        available = max(0, width - left - tokens.scaled(self.PADDING))
        label = widgets.elide(gcdc, self.view.label, available)
        gcdc.DrawText(label, left, (height - gcdc.GetCharHeight()) // 2)
        if self.HasFocus():
            widgets.draw_focus_ring(gcdc, rect, radius, palette.primary)
        del gcdc


class _ArticleButton(_Tappable):
    """One row of the article list: its title above its monospaced path."""

    PADDING_X = 11
    PADDING_Y = 9

    def __init__(
        self,
        parent: wx.Window,
        article: Article,
        *,
        selected: bool = False,
        on_click: Optional[Callable[[], None]] = None,
    ) -> None:
        self.article = article
        self.selected = bool(selected)
        super().__init__(parent, f"{article.title}, {article.path}", on_click=on_click)
        self.SetToolTip(article.summary)
        self.SetInitialSize(self.DoGetBestSize())

    def set_selected(self, selected: bool) -> None:
        """Mark or unmark the row without running its action."""
        self.selected = bool(selected)
        self.Refresh()

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        dc = wx.ClientDC(self)
        dc.SetFont(tokens.font(self, widgets.point_size(12), _MEDIUM))
        title_height = dc.GetCharHeight()
        dc.SetFont(tokens.mono_font(self, widgets.point_size(10)))
        path_height = dc.GetCharHeight()
        height = max(
            tokens.control_height(),
            title_height + path_height + tokens.scaled(self.PADDING_Y) * 2 + 2,
        )
        return wx.Size(tokens.scaled(200), height)

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        dc, gcdc = widgets.paint_context(self, self._backdrop(palette))
        width, height = self.GetClientSize()
        rect = wx.Rect(0, 0, width, height)
        radius = tokens.scaled(10)
        if self.selected:
            fill = palette.primary_container
            border = palette.primary
            title_ink = palette.on_primary_container
            path_ink = palette.on_primary_container
        else:
            fill = palette.surface
            border = (
                palette.primary
                if (self._hovered or self._pressed or self.HasFocus())
                else palette.outline_variant
            )
            title_ink = palette.on_surface
            path_ink = palette.on_surface_variant
        tokens.draw_round_rect(gcdc, rect, radius, fill, border)
        left = tokens.scaled(self.PADDING_X)
        available = max(0, width - left * 2)
        top = tokens.scaled(self.PADDING_Y)
        gcdc.SetFont(tokens.font(self, widgets.point_size(12), _MEDIUM))
        gcdc.SetTextForeground(title_ink)
        gcdc.DrawText(widgets.elide(gcdc, self.article.title, available), left, top)
        top += gcdc.GetCharHeight() + 2
        gcdc.SetFont(tokens.mono_font(self, widgets.point_size(10)))
        gcdc.SetTextForeground(path_ink)
        gcdc.DrawText(widgets.elide(gcdc, self.article.path, available), left, top)
        if self.HasFocus():
            widgets.draw_focus_ring(gcdc, rect, radius, palette.primary)
        del gcdc


# ---------------------------------------------------------------------------
# the console
# ---------------------------------------------------------------------------


class MemoryConsoleDialog(wx.Dialog):
    """The thirteen-view console over this machine's guidance records.

    The header carries the console's badge, its name, a search covering every
    view, and a close button.  The rail selects a view; the body renders that
    view's card grid, or -- for the documentation view -- a two-pane reader
    over every feature article.  Both searches default to plain text with a
    regular expression as a deliberate opt-in, and both report an invalid
    pattern rather than quietly matching nothing.
    """

    def __init__(self, parent: wx.Window, *, view_key: str = "") -> None:
        super().__init__(
            parent,
            title=CONSOLE_TITLE,
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
            name=CONSOLE_TITLE,
        )
        self._opener = wx.Window.FindFocus()
        self._focus_returned = False
        self.console_search = SearchState(label="Memory Console")
        self.article_search = SearchState(label="Feature articles")
        self.domain = ""
        self.view_key = (
            view_key if memory_content.view(view_key) else MEMORY_VIEWS[0].key
        )
        self.article_path = ARTICLES[0].path if ARTICLES else ""

        self._build_header()
        self._build_body()
        # Registered only once the window it repaints exists, so a theme change
        # can never reach a half-built console.
        self._theme_unsubscribe: Optional[Callable[[], None]] = (
            tokens.register_theme_listener(self.refresh_theme)
        )

        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(self.header, 0, wx.EXPAND)
        root.Add(self.body, 1, wx.EXPAND)
        self.SetSizer(root)

        self.show_view(self.view_key)
        self.refresh_theme()
        self.SetClientSize(self._preferred_size())
        self.SetMinSize(wx.Size(tokens.scaled(720), tokens.scaled(460)))
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
        self.Bind(wx.EVT_CLOSE, self._on_close)
        self.Bind(wx.EVT_WINDOW_DESTROY, self._on_destroy)
        self.close_button.SetFocus()

    # ------------------------------------------------------------------
    # construction
    # ------------------------------------------------------------------
    def _build_header(self) -> None:
        """Build the badge, the two-run title, the search, and the close button."""
        self.header = _EdgeStrip(self, edge="bottom", role="surface_container")
        self.badge = _Badge(self.header, "A")
        self.title_primary = widgets.StudioText(
            self.header,
            TITLE_PRIMARY,
            size_px=15,
            weight=_MEDIUM,
            role="on_surface",
            name=CONSOLE_TITLE,
        )
        self.title_secondary = widgets.StudioText(
            self.header,
            TITLE_SECONDARY,
            size_px=15,
            name=TITLE_SECONDARY,
        )
        self.search_bar = widgets.SearchBar(
            self.header,
            "Search every view",
            self.console_search,
            on_change=self._on_console_search,
            compact=True,
        )
        self.close_button = widgets.StudioButton(
            self.header,
            "✕",
            variant="icon",
            on_click=self.close,
            name="Close the Memory Console",
            hint="Close this window",
            height=30,
            min_width=34,
        )
        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(self.badge, 0, wx.ALIGN_CENTER_VERTICAL)
        row.Add(
            self.title_primary,
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            tokens.scaled(tokens.SPACE_SM + 2),
        )
        row.Add(
            self.title_secondary,
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            tokens.scaled(tokens.SPACE_XS),
        )
        row.AddStretchSpacer(1)
        row.Add(
            self.search_bar,
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            tokens.scaled(tokens.SPACE_MD),
        )
        row.Add(
            self.close_button,
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            tokens.scaled(tokens.SPACE_XS),
        )
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.AddSpacer(tokens.scaled(14))
        outer.Add(row, 1, wx.EXPAND | wx.LEFT, tokens.scaled(18))
        outer.AddSpacer(tokens.scaled(14))
        wrapper = wx.BoxSizer(wx.HORIZONTAL)
        wrapper.Add(outer, 1, wx.EXPAND | wx.RIGHT, tokens.scaled(14))
        self.header.SetSizer(wrapper)

    def _build_body(self) -> None:
        """Build the rail and the scrolling content column beside it."""
        self.body = wx.Panel(self, style=wx.TAB_TRAVERSAL)
        self.rail = _EdgeStrip(self.body, edge="right", role="surface_container")
        self.rail_items: Dict[str, _RailItem] = {}
        rail_sizer = wx.BoxSizer(wx.VERTICAL)
        for view in MEMORY_VIEWS:
            item = _RailItem(
                self.rail,
                view,
                selected=view.key == self.view_key,
                on_click=lambda key=view.key: self.show_view(key),
            )
            self.rail_items[view.key] = item
            rail_sizer.Add(item, 0, wx.EXPAND | wx.BOTTOM, tokens.scaled(3))
        rail_outer = wx.BoxSizer(wx.VERTICAL)
        rail_outer.AddSpacer(tokens.scaled(12))
        rail_outer.Add(
            rail_sizer,
            1,
            wx.EXPAND | wx.LEFT | wx.RIGHT,
            tokens.scaled(tokens.SPACE_SM),
        )
        rail_outer.AddSpacer(tokens.scaled(12))
        self.rail.SetSizer(rail_outer)
        self.rail.SetMinSize(wx.Size(tokens.scaled(RAIL_WIDTH), -1))

        self.content = wx.ScrolledWindow(self.body, style=wx.VSCROLL | wx.TAB_TRAVERSAL)
        self.content.SetScrollRate(0, tokens.scaled(12))
        self.eyebrow = _Eyebrow(self.content, CONSOLE_EYEBROW)
        self.view_title = widgets.StudioText(
            self.content,
            "",
            size_px=26,
            weight=_LIGHT,
            role="on_surface",
            name="View title",
        )
        self.view_subtitle = _Paragraph(
            self.content,
            "",
            size_px=14,
            line_height=1.5,
            max_width=READING_MEASURE,
        )
        self.match_line = _Paragraph(self.content, "", size_px=11, line_height=1.4)
        self.docs_panel = self._build_docs_panel(self.content)
        self.cards_panel = wx.Panel(self.content, style=wx.TAB_TRAVERSAL)
        self.cards_panel.SetName("Cards")

        column = wx.BoxSizer(wx.VERTICAL)
        column.Add(self.eyebrow, 0, wx.EXPAND | wx.BOTTOM, tokens.scaled(7))
        column.Add(self.view_title, 0, wx.EXPAND | wx.BOTTOM, tokens.scaled(6))
        column.Add(self.view_subtitle, 0, wx.EXPAND | wx.BOTTOM, tokens.scaled(16))
        column.Add(self.match_line, 0, wx.EXPAND | wx.BOTTOM, tokens.scaled(14))
        column.Add(self.docs_panel, 0, wx.EXPAND | wx.BOTTOM, tokens.scaled(20))
        column.Add(self.cards_panel, 0, wx.EXPAND)
        content_outer = wx.BoxSizer(wx.VERTICAL)
        content_outer.AddSpacer(tokens.scaled(22))
        content_outer.Add(column, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, tokens.scaled(24))
        content_outer.AddSpacer(tokens.scaled(30))
        self.content.SetSizer(content_outer)

        body_sizer = wx.BoxSizer(wx.HORIZONTAL)
        body_sizer.Add(self.rail, 0, wx.EXPAND)
        body_sizer.Add(self.content, 1, wx.EXPAND)
        self.body.SetSizer(body_sizer)

    def _build_docs_panel(self, parent: wx.Window) -> wx.Panel:
        """Build the two-pane reader: the filtered list and the article beside it."""
        panel = wx.Panel(parent, style=wx.TAB_TRAVERSAL)
        panel.SetName("Feature article reader")
        left = wx.Panel(panel, style=wx.TAB_TRAVERSAL)
        left.SetName("Article list")
        self.article_bar = widgets.SearchBar(
            left,
            "Search all feature articles",
            self.article_search,
            on_change=self._on_article_search,
        )
        self.domain_chips: Dict[str, widgets.Chip] = {}
        chips = wx.WrapSizer(wx.HORIZONTAL)
        for key, label in (("", "All"),) + tuple((name, name) for name in DOMAINS):
            chip = widgets.Chip(
                left,
                label,
                selected=key == self.domain,
                on_click=lambda _selected, value=key: self.choose_domain(value),
            )
            chip.SetName(f"Filter articles by {label}")
            self.domain_chips[key] = chip
            chips.Add(
                chip,
                0,
                wx.RIGHT | wx.BOTTOM,
                tokens.scaled(tokens.SPACE_XS + 2),
            )
        self.article_count = _Paragraph(left, "", size_px=11, line_height=1.4)
        self.article_list = wx.ScrolledWindow(left, style=wx.VSCROLL | wx.TAB_TRAVERSAL)
        self.article_list.SetName("Feature articles")
        self.article_list.SetScrollRate(0, tokens.scaled(10))
        self.article_list.SetMinSize(wx.Size(-1, tokens.scaled(ARTICLE_LIST_HEIGHT)))
        self.article_buttons: Dict[str, _ArticleButton] = {}
        left_sizer = wx.BoxSizer(wx.VERTICAL)
        left_sizer.Add(self.article_bar, 0, wx.EXPAND)
        left_sizer.Add(chips, 0, wx.EXPAND | wx.TOP, tokens.scaled(12))
        left_sizer.Add(self.article_count, 0, wx.EXPAND | wx.TOP, tokens.scaled(6))
        left_sizer.Add(self.article_list, 1, wx.EXPAND | wx.TOP, tokens.scaled(10))
        left.SetSizer(left_sizer)

        reader = widgets.Card(panel, radius=14)
        reader.SetName("Selected article")
        self.reader_domain = _Eyebrow(reader, "")
        self.reader_title = widgets.StudioText(
            reader, "", size_px=20, role="on_surface", name="Article title"
        )
        self.reader_summary = _Paragraph(
            reader, "", size_px=13, line_height=1.6, max_width=READING_MEASURE
        )
        self.reader_body = _Paragraph(
            reader, "", size_px=13, line_height=1.6, max_width=READING_MEASURE
        )
        self.reader_path = _CodeBlock(reader, "", name="Article source path")
        actions = wx.BoxSizer(wx.HORIZONTAL)
        self.open_editor_button = widgets.StudioButton(
            reader,
            "Open in VS Code",
            variant="tonal",
            on_click=self.open_article_in_editor,
            name="Open the selected article in VS Code",
            hint="Open this article's source file in the configured external editor",
            height=32,
        )
        self.export_button = widgets.StudioButton(
            reader,
            "Export article",
            variant="outlined",
            on_click=self.export_article,
            name="Export the selected article",
            hint="Write this article as Markdown, plain text, HTML, or JSON",
            height=32,
        )
        self.copy_path_button = widgets.StudioButton(
            reader,
            "Copy path",
            variant="outlined",
            on_click=self.copy_article_path,
            name="Copy the selected article's path",
            hint="Copy the article's source path to the clipboard",
            height=32,
        )
        for button in (
            self.open_editor_button,
            self.export_button,
            self.copy_path_button,
        ):
            actions.Add(button, 0, wx.RIGHT, tokens.scaled(7))
        reader_sizer = wx.BoxSizer(wx.VERTICAL)
        reader_sizer.Add(self.reader_domain, 0, wx.EXPAND | wx.BOTTOM, tokens.scaled(5))
        reader_sizer.Add(self.reader_title, 0, wx.EXPAND | wx.BOTTOM, tokens.scaled(10))
        reader_sizer.Add(
            self.reader_summary, 0, wx.EXPAND | wx.BOTTOM, tokens.scaled(10)
        )
        reader_sizer.Add(self.reader_body, 0, wx.EXPAND | wx.BOTTOM, tokens.scaled(12))
        reader_sizer.Add(self.reader_path, 0, wx.EXPAND | wx.BOTTOM, tokens.scaled(12))
        reader_sizer.Add(actions, 0, wx.EXPAND)
        reader_outer = wx.BoxSizer(wx.VERTICAL)
        reader_outer.Add(reader_sizer, 1, wx.EXPAND | wx.ALL, tokens.scaled(18))
        reader.SetSizer(reader_outer)

        columns = wx.BoxSizer(wx.HORIZONTAL)
        columns.Add(left, 1, wx.ALIGN_TOP)
        columns.Add(reader, 1, wx.ALIGN_TOP | wx.LEFT, tokens.scaled(16))
        panel.SetSizer(columns)
        return panel

    # ------------------------------------------------------------------
    # navigation
    # ------------------------------------------------------------------
    def show_view(self, key: str) -> None:
        """Select a rail view and rebuild the body for it."""
        view = memory_content.view(key)
        if view is None:
            log.error("No Memory Console view is registered under the key %r", key)
            return
        self.view_key = view.key
        for item_key, item in self.rail_items.items():
            item.set_selected(item_key == view.key)
        self.view_title.SetLabel(view.title)
        self.view_title.SetName(view.title)
        self.view_subtitle.set_text(studio_copy.studio_text(view.subtitle))
        docs = view.key == DOCS_VIEW_KEY
        self.docs_panel.Show(docs)
        if docs:
            self._rebuild_articles()
            self._show_article(self.article_path)
        self._rebuild_cards(view)
        self._update_match_line(view)
        self._relayout()

    def choose_domain(self, domain: str) -> None:
        """Filter the article list to one domain, or to all of them."""
        self.domain = str(domain)
        for key, chip in self.domain_chips.items():
            chip.set_selected(key == self.domain)
        self._rebuild_articles()
        self._relayout()

    def _current_article(self) -> Optional[Article]:
        return memory_content.article(self.article_path)

    def _show_article(self, path: str) -> None:
        """Point the reader at one article and mark it in the list."""
        article = memory_content.article(path)
        if article is None:
            return
        self.article_path = article.path
        self.reader_domain.set_text(article.domain)
        self.reader_title.SetLabel(article.title)
        self.reader_title.SetName(article.title)
        self.reader_summary.set_text(studio_copy.studio_text(article.summary))
        self.reader_body.set_text(
            studio_copy.studio_text("\n\n".join(article.paragraphs()))
        )
        self.reader_path.set_code(article.path)
        for key, button in self.article_buttons.items():
            button.set_selected(key == article.path)

    def select_article(self, path: str) -> None:
        """Show an article and lay the reader out again."""
        self._show_article(path)
        self._relayout()

    def _open_article_view(self, path: str) -> None:
        """Move to the documentation view and open one article there."""
        self.show_view(DOCS_VIEW_KEY)
        self.select_article(path)

    # ------------------------------------------------------------------
    # searching
    # ------------------------------------------------------------------
    def _on_console_search(self, _state: SearchState) -> None:
        self._apply_rail_filter()
        view = memory_content.view(self.view_key)
        if view is not None:
            self._rebuild_cards(view)
            self._update_match_line(view)
        self._relayout()

    def _apply_rail_filter(self) -> None:
        """Hide the rail entries the query excludes, keeping the current one.

        The selected view stays visible even when it does not match, because
        hiding the entry the reader is standing on leaves them with no way back
        to it and no explanation of where it went.
        """
        matched = {
            view.key for view in memory_content.search_views(self.console_search)
        }
        for key, item in self.rail_items.items():
            item.Show(key in matched or key == self.view_key)
        self.rail.Layout()

    def _update_match_line(self, view: MemoryView) -> None:
        """Report honestly how much the query is currently hiding."""
        if not self.console_search.is_active():
            self.match_line.Hide()
            return
        views = len(memory_content.search_views(self.console_search))
        cards = len(memory_content.search_cards(view.cards, self.console_search))
        summary = self.console_search.describe_matches(cards, "card")
        self.match_line.set_text(
            f"{views} of {len(MEMORY_VIEWS)} views match · {summary}"
        )
        self.match_line.Show()

    def _on_article_search(self, _state: SearchState) -> None:
        self._rebuild_articles()
        self._relayout()

    def _article_count_text(self, matches: Sequence[Article]) -> str:
        scope = self.domain or "every domain"
        if self.article_search.is_active():
            return f"{self.article_search.describe_matches(len(matches), 'article')} · {scope}"
        return f"{len(matches)} of {len(ARTICLES)} articles · {scope}"

    # ------------------------------------------------------------------
    # rebuilding
    # ------------------------------------------------------------------
    def _rebuild_articles(self) -> None:
        """Rebuild the filtered article list and keep the reader in step."""
        matches = search_articles(self.article_search, self.domain)
        if matches and self.article_path not in {item.path for item in matches}:
            # Keeping a selection the list no longer shows would leave the
            # reader and the list disagreeing about what is selected.
            self._show_article(matches[0].path)
        self.article_list.SetSizer(None)
        self.article_list.DestroyChildren()
        self.article_buttons = {}
        sizer = wx.BoxSizer(wx.VERTICAL)
        if not matches:
            note = _Paragraph(
                self.article_list,
                self._article_count_text(matches),
                size_px=12,
            )
            sizer.Add(note, 0, wx.EXPAND | wx.ALL, tokens.scaled(tokens.SPACE_SM))
        for article in matches:
            button = _ArticleButton(
                self.article_list,
                article,
                selected=article.path == self.article_path,
                on_click=lambda path=article.path: self.select_article(path),
            )
            self.article_buttons[article.path] = button
            sizer.Add(button, 0, wx.EXPAND | wx.BOTTOM, tokens.scaled(5))
        self.article_list.SetSizer(sizer)
        self.article_count.set_text(self._article_count_text(matches))
        self.article_list.Layout()
        self.article_list.FitInside()

    def _rebuild_cards(self, view: MemoryView) -> None:
        """Rebuild the twelve-column card grid for one view."""
        self.cards_panel.SetSizer(None)
        self.cards_panel.DestroyChildren()
        cards = memory_content.search_cards(view.cards, self.console_search)
        if not cards:
            sizer = wx.BoxSizer(wx.VERTICAL)
            sizer.Add(
                _Paragraph(
                    self.cards_panel,
                    self.console_search.describe_matches(0, "card"),
                    size_px=13,
                ),
                0,
                wx.EXPAND,
            )
            self.cards_panel.SetSizer(sizer)
            return
        gap = tokens.scaled(14)
        grid = wx.GridBagSizer(gap, gap)
        row = 0
        column = 0
        for card in cards:
            span = max(1, min(GRID_COLUMNS, int(card.span)))
            if column + span > GRID_COLUMNS:
                row += 1
                column = 0
            grid.Add(
                self._build_card(card),
                pos=(row, column),
                span=(1, span),
                flag=wx.EXPAND,
            )
            column += span
            if column >= GRID_COLUMNS:
                row += 1
                column = 0
        if column:
            # Every one of the twelve columns must carry an item before it can
            # be made growable, so the last partial row is padded rather than
            # left with columns that exist only in the arithmetic.
            grid.Add(
                tokens.scaled(1),
                tokens.scaled(1),
                pos=(row, column),
                span=(1, GRID_COLUMNS - column),
            )
        for index in range(GRID_COLUMNS):
            grid.AddGrowableCol(index, 1)
        self.cards_panel.SetSizer(grid)
        # No restyle pass is needed after a rebuild any more.  Every label on a
        # card resolves its own ink and font from the palette on each paint, so
        # there is no registry of native controls to refresh -- and none to
        # leak a card's worth of dead entries into on every view change.

    def _build_card(self, card: MemoryCard) -> wx.Window:
        """Build one card: its title, and whichever parts it declares."""
        panel = widgets.Card(self.cards_panel, radius=14)
        panel.SetName(card.title)
        sizer = wx.BoxSizer(wx.VERTICAL)
        title = widgets.StudioText(
            panel, card.title, size_px=17, role="on_surface", name=card.title
        )
        sizer.Add(title, 0, wx.EXPAND)
        if card.stat:
            stat = widgets.StudioText(
                panel,
                card.stat,
                size_px=26,
                weight=wx.FONTWEIGHT_BOLD,
                role="primary",
                name=f"{card.title}: {card.stat}",
            )
            sizer.Add(stat, 0, wx.EXPAND | wx.TOP, tokens.scaled(10))
        if card.body:
            sizer.Add(
                _Paragraph(panel, studio_copy.studio_text(card.body), size_px=13),
                0,
                wx.EXPAND | wx.TOP,
                tokens.scaled(10),
            )
        for entry in card.rows:
            sizer.Add(
                widgets.ListRow(
                    panel,
                    entry.name,
                    entry.detail,
                    entry.tag,
                    on_click=lambda item=entry: self.activate_row(item),
                ),
                0,
                wx.EXPAND | wx.TOP,
                tokens.scaled(7),
            )
        if card.code:
            sizer.Add(
                _CodeBlock(panel, card.code, name=f"{card.title} record"),
                0,
                wx.EXPAND | wx.TOP,
                tokens.scaled(12),
            )
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(sizer, 1, wx.EXPAND | wx.ALL, tokens.scaled(16))
        panel.SetSizer(outer)
        return panel

    def _relayout(self) -> None:
        """Lay out the body again and refresh the scrolled extent."""
        self.content.Layout()
        self.content.FitInside()
        self.body.Layout()
        self.Layout()

    # ------------------------------------------------------------------
    # row and article actions
    # ------------------------------------------------------------------
    def activate_row(self, row: CardRow) -> None:
        """Follow a card row's target, or report the detail it records.

        Navigation is deferred to the next idle turn because moving to another
        view rebuilds the card grid, which destroys the very row whose click is
        still being handled; running it inline would leave wx finishing an
        event on a window that no longer exists.
        """
        target = str(row.target)
        if target.startswith("view:"):
            wx.CallAfter(self.show_view, target.split(":", 1)[1])
            return
        if target.startswith("article:"):
            path = target.split(":", 1)[1]
            wx.CallAfter(self._open_article_view, path)
            return
        detail = row.note or row.detail or "No further detail is recorded for this row."
        self._notify(
            row.name,
            studio_copy.studio_text(detail),
            details=f"{row.name} · {row.tag}" if row.tag else row.name,
        )

    def open_article_in_editor(self) -> None:
        """Open the selected article's source file in the external editor."""
        from amulet_map_editor.api import external_editor

        article = self._current_article()
        if article is None:
            return
        target = repository_root() / Path(article.path)
        result = external_editor.open_path(target)
        details = f"Article: {article.path}"
        if not result.ok and result.status == "invalid_target":
            details = (
                f"{details}\n"
                "The article text is bundled with this build. Its source file "
                "is present only in a source checkout, so export the article "
                "and open the exported copy instead."
            )
        self._notify(
            "Open in VS Code",
            result.message,
            severity="info" if result.ok else "warning",
            details=details,
        )

    def export_article(self) -> None:
        """Write the selected article to a file in the chosen format."""
        article = self._current_article()
        if article is None:
            return
        stem = Path(article.path).parent.name or "article"
        wildcard = (
            "Markdown (*.md)|*.md|"
            "Plain text (*.txt)|*.txt|"
            "HTML (*.html)|*.html|"
            "JSON (*.json)|*.json"
        )
        formats = memory_content.ARTICLE_FORMATS
        with wx.FileDialog(
            self,
            "Export article",
            defaultFile=f"{stem}{formats[0]}",
            wildcard=wildcard,
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        ) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            destination = Path(dialog.GetPath())
            index = dialog.GetFilterIndex()
        chosen = formats[index] if 0 <= index < len(formats) else formats[0]
        if destination.suffix.lower() not in formats:
            # A name typed without an extension takes the format the user
            # actually chose in the dialog, so the file's contents and its name
            # cannot end up describing different things.
            destination = destination.with_name(destination.name + chosen)
        text = memory_content.render_article(article, destination.suffix)
        try:
            destination.write_text(text, encoding="utf-8")
        except OSError as error:
            self._notify(
                "Export article",
                f"The article could not be written: {error}",
                severity="error",
                details=f"Destination: {destination}",
            )
            return
        self._record(
            "studio.memory.article.exported",
            {
                "article": article.path,
                "format": destination.suffix,
                "destination": str(destination),
            },
        )
        self._notify(
            "Export article",
            f"Wrote {article.title} to {destination}.",
            details=(
                f"Format: {destination.suffix} · Encoding: UTF-8 · "
                f"Source: {article.path}"
            ),
        )

    def copy_article_path(self) -> None:
        """Copy the selected article's source path to the clipboard."""
        article = self._current_article()
        if article is None:
            return
        if not wx.TheClipboard.Open():
            self._notify(
                "Copy path",
                "The clipboard could not be opened, so nothing was copied.",
                severity="warning",
                details=f"Path: {article.path}",
            )
            return
        try:
            wx.TheClipboard.SetData(wx.TextDataObject(article.path))
            wx.TheClipboard.Flush()
        finally:
            wx.TheClipboard.Close()
        self._notify("Copy path", f"Copied {article.path} to the clipboard.")

    # ------------------------------------------------------------------
    # reporting
    # ------------------------------------------------------------------
    def _notify(
        self, title: str, body: str, *, severity: str = "info", details: str = ""
    ) -> None:
        """Report a result without interrupting whatever is being read."""
        from amulet_map_editor.api.wx import nonblocking

        nonblocking.notify(self, title, body, severity=severity, details=details)

    @staticmethod
    def _record(record_id: str, payload: object) -> None:
        """Record a state-changing action, never failing the action itself."""
        from amulet_map_editor.api import local_history

        local_history.safe_record(record_id, payload, record_type="export")

    # ------------------------------------------------------------------
    # window plumbing
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
        return wx.Size(max(tokens.scaled(560), width), max(tokens.scaled(400), height))

    def close(self) -> None:
        """Close the console and hand the keyboard back to whatever opened it."""
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
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.close()
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
        """Re-read the tokens and repaint the whole console."""
        try:
            if self.IsBeingDeleted():
                return
            palette = tokens.palette()
            self.SetBackgroundColour(palette.surface)
            self.body.SetBackgroundColour(palette.surface)
            self.content.SetBackgroundColour(palette.surface)
            self.cards_panel.SetBackgroundColour(palette.surface)
            self.docs_panel.SetBackgroundColour(palette.surface)
            self.article_list.SetBackgroundColour(palette.surface)
            self.header.refresh_theme()
            self.rail.refresh_theme()
            _refresh_children(self.content, palette)
            self.Refresh()
        except RuntimeError:
            self._theme_unsubscribe = None


def _refresh_children(window: wx.Window, palette: tokens.StudioPalette) -> None:
    """Repaint every descendant, using each one's own handler where it has one."""
    for child in window.GetChildren():
        refresh = getattr(child, "refresh_theme", None)
        if callable(refresh):
            refresh()
            continue
        if isinstance(child, (wx.Panel, wx.ScrolledWindow)):
            child.SetBackgroundColour(palette.surface)
        _refresh_children(child, palette)


def open_memory_console(
    parent: wx.Window, *, view_key: str = ""
) -> MemoryConsoleDialog:
    """Open the console, reusing the window when one is already open.

    The console is a reference surface rather than a decision, so it is shown
    non-modally and one window is kept per top-level parent instead of stacking
    a new one every time the surface is asked for.
    """
    from amulet_map_editor.api.wx.modeless import show_modeless_dialog

    return show_modeless_dialog(
        parent,
        "studio.memory",
        lambda owner: MemoryConsoleDialog(owner, view_key=view_key),
    )


__all__ = [
    "ARTICLE_LIST_HEIGHT",
    "CONSOLE_EYEBROW",
    "CONSOLE_TITLE",
    "DIALOG_HEIGHT",
    "DIALOG_WIDTH",
    "MemoryConsoleDialog",
    "RAIL_WIDTH",
    "READING_MEASURE",
    "open_memory_console",
    "repository_root",
]
