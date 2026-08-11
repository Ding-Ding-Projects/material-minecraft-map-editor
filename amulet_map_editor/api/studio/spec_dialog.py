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

What a surface renders is not the shipped description on its own.  Every spec
goes through :func:`amulet_map_editor.api.studio.live.bind` first, which
rewrites its record-carrying sections from the world the user actually has
open, and the window re-binds whenever that world changes.  A surface with no
binder renders exactly as it is described; a surface with one shows the user's
world, or says plainly that no world is open rather than showing the rows the
design was drawn with.
"""

from __future__ import annotations

import csv
import datetime
import importlib
import io
import json
import logging
import os
import pkgutil
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import wx

from amulet_map_editor.api.studio import context as world_context
from amulet_map_editor.api.studio import live
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

#: The export formats a surface can be written out in, in the order the save
#: dialog offers them: a label, the extension, and the renderer that produces
#: the text.  Every one of them carries the same readings -- a format is a way
#: of writing what the window shows, never a smaller subset of it.
EXPORT_FORMATS: Tuple[Tuple[str, str], ...] = (
    ("Markdown", "md"),
    ("JSON", "json"),
    ("CSV", "csv"),
    ("Plain text", "txt"),
)

#: The wildcard the save dialog is opened with, built from the formats above so
#: the two can never disagree about which extension goes with which filter.
EXPORT_WILDCARD = "|".join(
    f"{label} (*.{extension})|*.{extension}" for label, extension in EXPORT_FORMATS
)


def load_binders() -> Tuple[str, ...]:
    """Import every ``binders_*`` module in this package, returning their names.

    The binder registry is populated as a side effect of importing the modules
    that register into it, so something has to import them -- and this window is
    the one place every declarative surface passes through.  Discovering them
    rather than listing them means a new family of binders starts working the
    moment its module lands, and a module that fails to import takes its own
    surfaces down to their shipped descriptions instead of taking the window
    with it.
    """
    package = __name__.rsplit(".", 1)[0]
    loaded: List[str] = []
    try:
        module = importlib.import_module(package)
        search_path = list(getattr(module, "__path__", ()))
    except Exception:  # pragma: no cover - the package is already imported here
        log.exception("Could not read the Studio package to find its live binders")
        return ()
    for entry in pkgutil.iter_modules(search_path):
        if not entry.name.startswith("binders_"):
            continue
        try:
            importlib.import_module(f"{package}.{entry.name}")
        except Exception:
            log.exception("The live binder module %r could not be imported", entry.name)
            continue
        loaded.append(entry.name)
    return tuple(sorted(loaded))


BINDER_MODULES = load_binders()


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


class _WrapRow(wx.Panel):
    """A row of controls that wraps onto further lines instead of crushing.

    Both of the obvious ways to build such a row fail, and both fail silently.
    A ``wx.WrapSizer`` puts its children on as many lines as they need, but the
    height it reports is the height of one line unless wx has told it how wide
    it is going to be -- and wx only tells a sizer that when it is nested
    directly inside another sizer, never when it is set on a panel.  A row
    built that way lays its second line out below its own bottom edge, where
    every control on it is clipped to zero height.  A horizontal
    ``wx.BoxSizer`` has no second line to give, so it takes the shortfall out
    of the last controls instead until they are zero wide.  Either way the
    controls are still there, still in the tab order, and no longer visible.

    This panel measures the lines itself, at whatever width it is handed, and
    reports the height they genuinely need, so the row grows downwards and
    every control on it keeps its own size.
    """

    def __init__(self, parent: wx.Window, *, gap: int = 0) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self.gap = int(gap)
        # The last control on a line is deliberately not stretched out to the
        # margin: a chip reading "Torus" drawn four hundred pixels wide reads
        # as a different kind of control from the one sitting next to it.
        self._row = wx.WrapSizer(wx.HORIZONTAL, flags=wx.REMOVE_LEADING_SPACES)
        self.SetSizer(self._row)
        self._measured_at = 0
        self.Bind(wx.EVT_SIZE, self._on_resize)

    def add(self, child: wx.Window) -> wx.Window:
        """Put one control on the row and hand it back."""
        self._row.Add(child, 0, wx.RIGHT | wx.BOTTOM, self.gap)
        return child

    def _height_for(self, width: int) -> int:
        """Return the height the row needs to lay its controls out in ``width``.

        The line breaks are worked out the way ``wx.WrapSizer`` works them out
        -- each control claims its own width plus the gap that follows it, and
        a control that would not fit starts a new line -- so the height
        reported here is the height wx will actually use rather than a
        near-miss that clips the bottom line.
        """
        limit = max(1, width)
        used = 0
        line = 0
        total = 0
        for child in self.GetChildren():
            if not child.IsShown():
                continue
            size = child.GetEffectiveMinSize()
            claim = size.width + self.gap
            if used and used + claim > limit:
                total += line
                used = 0
                line = 0
            used += claim
            line = max(line, size.height + self.gap)
        return total + line

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        width = self.GetSize().width
        return wx.Size(width, self._height_for(width or tokens.scaled(560)))

    def _on_resize(self, event: wx.SizeEvent) -> None:
        """Re-measure once per real width change, as :class:`_Paragraph` does.

        Re-measuring on every size event would re-enter the layout that raised
        it; comparing against the width the row was last measured at makes the
        work happen exactly once per real width change.
        """
        width = self.GetSize().width
        if width and width != self._measured_at:
            self._measured_at = width
            self.InvalidateBestSize()
            self.SetMinSize(wx.Size(-1, self._height_for(width)))
            top = self.GetTopLevelParent()
            if top is not None:
                top.Layout()
        event.Skip()

    def refresh_theme(self) -> None:
        """Re-read the palette for the row and every control standing on it."""
        palette = tokens.palette()
        parent = self.GetParent()
        backdrop = parent.GetBackgroundColour() if parent else palette.surface
        self.SetBackgroundColour(backdrop if backdrop.IsOk() else palette.surface)
        for child in self.GetChildren():
            refresh = getattr(child, "refresh_theme", None)
            if callable(refresh):
                refresh()
        self.Refresh()


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
        self.check = widgets.StudioCheckBox(
            self, str(label), value=bool(value), size_px=14
        )
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
        # The box is owner-drawn: it reads its border, tick, ink, and font from
        # the tokens on every paint, so repainting it is the whole of the work.
        self.check.refresh_theme()
        if self.hint is not None:
            self.hint.refresh_theme()


class _CodeBlock(wx.Panel):
    """A monospaced, selectable, read-only block for code and transcripts.

    It is a real text control rather than painted text so the content can be
    selected and copied; a code sample nobody can copy is a picture of code.
    """

    #: A block stops growing at this many lines and scrolls the rest.
    VISIBLE_LINES = 24

    #: The widest a block asks to be before its own scrollbar takes over.
    MAX_WIDTH = 720

    #: The gap between the block's rounded edge and the text inside it.
    PADDING = 12

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
        sizer.Add(self.text, 1, wx.EXPAND | wx.ALL, tokens.scaled(self.PADDING))
        self.SetSizer(sizer)
        self.refresh_theme()
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        # Size and lay the block out now rather than waiting to be laid out.
        # Every code section is rendered inside a collapsible block that starts
        # closed, and a hidden panel is never laid out at all -- so without
        # this the block keeps the 20x20 default wx gives an unsized panel
        # while the text control inside it sits at its own initial size,
        # overflowing a container several times smaller than its content.
        self.SetSize(self.DoGetBestSize())
        self.Layout()
        # Keep the height a block needs even when it is squeezed horizontally,
        # but leave the width free -- and set it after the size above, which
        # would otherwise pin the minimum width to the content and stop a
        # narrow window from ever scrolling the code instead of overflowing.
        self.SetMinSize(wx.Size(-1, self._content_height()))

    def _content_height(self) -> int:
        """Return the height of the lines this block shows before scrolling."""
        lines = self.code.count("\n") + 1
        rows = min(self.VISIBLE_LINES, max(2, lines))
        return tokens.scaled(rows * 18 + self.PADDING * 2)

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        """Return the size the code itself asks for, capped so it stays sane.

        Measuring the real text is what makes a one-line snippet and a forty
        line transcript different sizes; the cap is what stops a single very
        long line demanding a window nobody can fit on a display, and the text
        control scrolls past it.
        """
        dc = wx.ClientDC(self)
        dc.SetFont(tokens.mono_font(self, widgets.point_size(12)))
        widest = max(
            (dc.GetTextExtent(line)[0] for line in self.code.split("\n")), default=0
        )
        padding = tokens.scaled(self.PADDING) * 2
        return wx.Size(
            min(tokens.scaled(self.MAX_WIDTH), widest + padding + tokens.scaled(6)),
            self._content_height(),
        )

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
        #: The shipped description, kept so the surface can be bound again
        #: against a different world without the previous world's readings
        #: still in it.
        self.source_spec = spec
        self.spec = self._bind(spec)
        self.on_action = on_action
        self._opener = wx.Window.FindFocus()
        self._focus_returned = False
        self.window_search = SearchState(label=f"{spec.title} window")
        self._section_states: Dict[int, SearchState] = {}
        self._section_bars: Dict[int, widgets.SearchBar] = {}
        self._focus_request: Optional[int] = None
        #: The record the user last clicked in a list, and the target every
        #: action that needs one operates on.
        self.selected_row: Optional[spec_api.Row] = None
        #: The last file this window wrote, so "open in VS Code" has something
        #: real to open rather than guessing at a path.
        self.last_export: Optional[Path] = None
        self._theme_unsubscribe = tokens.register_theme_listener(self.refresh_theme)
        world_context.subscribe(self._on_world_changed)

        self.header = _EdgePanel(self, edge="bottom")
        self.eyebrow = _Eyebrow(self.header, spec.eyebrow)
        self.title_text = widgets.StudioText(
            self.header, spec.title, size_px=19, role="on_surface", name=spec.title
        )
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
        # The actions wrap and the confirm button keeps the right-hand end.  A
        # plain horizontal row cannot do that: the surfaces carrying five or
        # six actions need more width than the window has, and a box sizer
        # answers a shortfall by shrinking its last children to nothing --
        # which on those surfaces took the confirm button itself with it.
        self.actions_row = _WrapRow(self.footer, gap=tokens.scaled(tokens.SPACE_SM))
        self.footer_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.action_buttons: List[widgets.StudioButton] = []
        for action in spec.actions:
            button = widgets.StudioButton(
                self.actions_row,
                action.label,
                variant=ACTION_VARIANTS.get(action.kind, "outlined"),
                on_click=lambda item=action: self.run_action(item),
                name=action.label,
                hint=self._action_hint(action),
                height=40,
            )
            self.action_buttons.append(button)
            self.actions_row.add(button)
        self.footer_sizer.Add(
            self.actions_row, 1, wx.EXPAND | wx.RIGHT, tokens.scaled(tokens.SPACE_SM)
        )
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
    # the open world
    # ------------------------------------------------------------------
    @staticmethod
    def _bind(spec: Spec) -> Spec:
        """Return ``spec`` rewritten from whatever world is open right now.

        Binding never fails the window: :func:`live.bind` already returns the
        shipped description when a binder is absent or raises, and the extra
        guard here covers a registry that could not be reached at all.
        """
        try:
            bound = live.bind(spec, world_context.current())
        except Exception:  # noqa: BLE001 - a surface still has to open
            log.exception("Could not bind the surface %r to the open world", spec.key)
            return spec
        return bound if isinstance(bound, Spec) else spec

    def _on_world_changed(self, _context: world_context.WorldContext) -> None:
        """Re-read the world into this window when the open world changes.

        The publish can arrive from whichever thread opened or closed the
        world, so the rebuild is handed back to the main loop rather than
        touching controls from under it.
        """
        try:
            if self.IsBeingDeleted():
                return
        except RuntimeError:
            return
        wx.CallAfter(self.rebind)

    def rebind(self) -> None:
        """Bind the shipped description to the open world and redraw the body."""
        try:
            if self.IsBeingDeleted():
                return
        except RuntimeError:
            return
        self.spec = self._bind(self.source_spec)
        # A section search is keyed by position, and binding can change what
        # sits at each position, so a query left behind would silently narrow a
        # section it was never typed into.
        self._section_states = {}
        self.selected_row = None
        self.rebuild()

    def world(self) -> world_context.WorldContext:
        """Return the world this window is currently showing."""
        return world_context.current()

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

    def _collapsible(self, section: Section) -> bool:
        """Return whether a section starts folded away behind a disclosure.

        A titled note beside real records is an aside, and folding it keeps the
        records in view.  A titled note that *is* the window's content -- which
        is what a surface shows when no world is open, or when the world holds
        nothing to list -- is the answer, and folding the answer away makes an
        honest empty state look like a window that failed to load.
        """
        if section.kind == "code":
            return True
        if section.kind != "note" or not section.title:
            return False
        return any(other.kind not in ("note", "search") for other in self.spec.sections)

    def _render_section(self, index: int, section: Section) -> Optional[wx.Window]:
        """Build one section's block, titled where the section carries a title."""
        if self._collapsible(section):
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
        if not host.IsShown():
            # A collapsed section hides its body, and wx never lays a hidden
            # panel out: it keeps the 20x20 default it was created with, so
            # everything inside it overflows a container smaller than one line
            # of its own content.  Sizing it to what it holds means the section
            # is already right the moment it is opened, rather than one layout
            # pass later, and that nothing is measured against a size no part
            # of the window ever intended.
            host_sizer.Fit(host)
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
        # Every row is clickable, because the footer actions that need a target
        # -- add, remove, reset -- have nowhere to point without one, and an
        # action that names no record is an action nobody can check.
        return [
            (
                widgets.ListRow(
                    host,
                    row.name,
                    row.detail,
                    row.tag,
                    swatch=row.swatch,
                    on_click=lambda item=row: self.select_row(item),
                ),
                True,
            )
            for row in section.rows
        ]

    def select_row(self, row: spec_api.Row) -> None:
        """Record the row the user just picked as this window's target."""
        self.selected_row = row
        top = self.GetTopLevelParent()
        try:
            top.SetStatusText(f"Selected: {row.name}")
        except Exception:  # noqa: BLE001 - a frame with no status bar is normal
            log.debug("No status bar to report the selected record on")

    def selected_label(self) -> str:
        """Return the selected record as one line, or ``""`` when none is."""
        row = self.selected_row
        if row is None:
            return ""
        return " · ".join(part for part in (row.name, row.detail, row.tag) if part)

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
        row = _WrapRow(host, gap=tokens.scaled(tokens.SPACE_SM))
        row.SetBackgroundColour(tokens.palette().surface)
        for label in section.chips:
            row.add(widgets.Chip(row, label))
        return [(row, True)]

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
        row = _WrapRow(host, gap=tokens.scaled(tokens.SPACE_SM))
        row.SetBackgroundColour(tokens.palette().surface)
        for swatch in section.swatches:
            row.add(widgets.Swatch(row, swatch.colour, name=swatch.name))
        blocks: List[tuple] = [(row, True)]
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
        """Route one action to a surface, to this window, or to an honest report.

        The order matters.  An action that names another surface opens it, and
        always has.  An action this window can genuinely carry out against the
        open world -- writing an export, copying a reading, counting what the
        search matches, re-reading the world -- is carried out here rather than
        handed on, because handing it to a shell that only reports would turn a
        real capability back into a message about one.
        """
        if action.surface and self._open_surface(action.surface):
            return
        if self._perform(action):
            return
        if self.on_action is not None:
            widgets.invoke(self.on_action, action)
            return
        self._report_unhandled(action)

    def _verb(self, label: str) -> str:
        """Return the operation ``label`` asks for, or ``""`` when it names none."""
        text = " ".join(str(label).split()).lower()
        if not text:
            return ""
        for phrase in ("vs code", "visual studio code", "external editor"):
            if phrase in text:
                return "open"
        first = text.split(" ", 1)[0]
        if first in ("export", "copy", "find", "preview", "add", "remove", "reset"):
            return first
        return ""

    def _perform(self, action: Action) -> bool:
        """Carry out ``action`` here when it names something this window can do."""
        verb = self._verb(action.label)
        if not verb:
            return False
        handler = getattr(self, f"_do_{verb}", None)
        if handler is None:
            return False
        try:
            handler(action)
        except Exception as error:  # noqa: BLE001 - a failed action is reported
            log.exception(
                "The action %r failed on surface %r", action.label, self.spec.key
            )
            self._notify(
                action.label,
                f"{action.label} could not be completed: {type(error).__name__}: "
                f"{error}. Nothing was changed.",
                severity="error",
            )
        return True

    # -- reporting ----------------------------------------------------------
    def _notify(
        self, title: str, body: str, *, severity: str = "info", details: str = ""
    ) -> None:
        """Report an outcome without halting the window."""
        from amulet_map_editor.api.wx import nonblocking

        nonblocking.notify(
            self, title, body, severity=severity, details=details or self._provenance()
        )

    def _provenance(self) -> str:
        """Return where this window's readings came from, for a report's details."""
        ctx = self.world()
        if not ctx.open:
            return f"Surface: {self.spec.key} · No world is open."
        return (
            f"Surface: {self.spec.key} · World: {ctx.name or 'unnamed'} · "
            f"Folder: {ctx.path or 'not recorded'} · Dimension: "
            f"{ctx.dimension or 'not reported'}"
        )

    def _needs_world(self, action: Action) -> bool:
        """Report and refuse when a world-dependent action has no world open."""
        if self.world().open:
            return False
        if self.spec.key not in live.bound_keys():
            return False
        self._notify(
            action.label,
            f"No world is open, so {action.label.lower()} has nothing to work "
            "with. Open a world from the project screen and run it again.",
            severity="warning",
        )
        return True

    # -- the readings this window holds -------------------------------------
    def _records(self) -> List[Tuple[str, str, str, str]]:
        """Return every reading currently on show, as section, name, detail, tag.

        This is what an export writes and what a search counts, so the two can
        never disagree about what the window is showing.
        """
        rows: List[Tuple[str, str, str, str]] = []
        for section in self._visible_sections():
            title = section.title or section.kind
            for row in section.rows:
                rows.append((title, row.name, row.detail, row.tag))
            for field in section.fields:
                rows.append((title, field.label, field.value, field.placeholder))
            for select in section.selects:
                rows.append(
                    (title, select.label, select.current(), ", ".join(select.options))
                )
            for check in section.checks:
                rows.append(
                    (title, check.label, "on" if check.value else "off", check.hint)
                )
            for item in section.ranges:
                rows.append((title, item.label, str(item.value), ""))
            for swatch in section.swatches:
                rows.append((title, swatch.name, swatch.colour, ""))
            for binding in section.keys:
                rows.append((title, binding.action, binding.binding, ""))
            for node in section.tree:
                rows.append((title, node.label, node.glyph, ""))
            for chip in section.chips:
                rows.append((title, chip, "", ""))
            for commit in section.commits:
                rows.append((title, commit.message, commit.meta, ""))
            if section.kind == "note" and section.hint:
                rows.append((title, "note", section.hint, ""))
        return rows

    def _visible_sections(self) -> List[Section]:
        """Return the sections the searches currently leave on show."""
        sections = []
        for section in self.spec.sections:
            narrowed = self._narrow(section)
            if narrowed is not None:
                sections.append(narrowed)
        return sections

    def _total_records(self) -> int:
        """Return how many readings the window holds before any search."""
        total = 0
        for section in self.spec.sections:
            total += len(section.items()) + len(section.chips)
        return total

    # -- export -------------------------------------------------------------
    def _export_text(self, extension: str) -> str:
        """Return this window's readings written in one of the export formats."""
        ctx = self.world()
        stamp = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
        records = self._records()
        source = ctx.path or ctx.name or "no world open"
        if extension == "json":
            return json.dumps(
                {
                    "surface": self.spec.key,
                    "title": self.spec.title,
                    "exported": stamp,
                    "world": {
                        "open": ctx.open,
                        "name": ctx.name,
                        "path": ctx.path,
                        "platform": ctx.platform,
                        "version": ctx.game_version or ctx.version,
                        "dimension": ctx.dimension,
                    },
                    "search": self.window_search.query,
                    "records": [
                        {
                            "section": section,
                            "name": name,
                            "detail": detail,
                            "tag": tag,
                        }
                        for section, name, detail, tag in records
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        if extension == "csv":
            buffer = io.StringIO()
            writer = csv.writer(buffer, lineterminator="\n")
            writer.writerow(["section", "name", "detail", "tag"])
            writer.writerows(records)
            return buffer.getvalue()
        if extension == "md":
            lines = [
                f"# {self.spec.title}",
                "",
                f"- Surface: `{self.spec.key}`",
                f"- Exported: {stamp}",
                f"- Read from: {source}",
            ]
            if self.window_search.query:
                lines.append(f"- Search: `{self.window_search.query}`")
            lines.append("")
            current = ""
            for section, name, detail, tag in records:
                if section != current:
                    current = section
                    lines.extend(["", f"## {section}", ""])
                suffix = f" — `{tag}`" if tag else ""
                lines.append(f"- **{name}** {detail}{suffix}".rstrip())
            lines.append("")
            return "\n".join(lines)
        lines = [
            self.spec.title,
            "=" * len(self.spec.title),
            f"Surface: {self.spec.key}",
            f"Exported: {stamp}",
            f"Read from: {source}",
            "",
        ]
        current = ""
        for section, name, detail, tag in records:
            if section != current:
                current = section
                lines.extend([f"[{section}]"])
            lines.append(
                "  " + " · ".join(part for part in (name, detail, tag) if part)
            )
        return "\n".join(lines) + "\n"

    def _do_export(self, action: Action) -> None:
        """Write what this window is showing to a file the user picks."""
        if self._needs_world(action):
            return
        records = self._records()
        if not records:
            self._notify(
                action.label,
                "This window is showing no records, so there is nothing to " "export.",
                severity="warning",
            )
            return
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        with wx.FileDialog(
            self,
            f"{action.label} — choose where to write it",
            defaultFile=f"{self.spec.key}-{stamp}.md",
            wildcard=EXPORT_WILDCARD,
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        ) as chooser:
            if chooser.ShowModal() != wx.ID_OK:
                self._notify(
                    action.label, "The export was cancelled; no file was written."
                )
                return
            target = Path(chooser.GetPath())
            index = max(0, min(chooser.GetFilterIndex(), len(EXPORT_FORMATS) - 1))
        label, extension = EXPORT_FORMATS[index]
        if target.suffix.lower() != f".{extension}":
            target = target.with_suffix(f".{extension}")
        content = self._export_text(extension)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8", newline="\n")
        except OSError as error:
            self._notify(
                action.label,
                f"The export could not be written to {target}: {error}",
                severity="error",
            )
            return
        self.last_export = target
        self._record_history(
            f"studio.export.{self.spec.key}",
            {
                "surface": self.spec.key,
                "format": extension,
                "path": str(target),
                "records": len(records),
                "world": self.world().path,
            },
            record_type="studio export",
        )
        self._notify(
            action.label,
            f"Wrote {len(records)} records as {label} to {target}.",
            details=f"{self._provenance()} · {target}",
        )

    def _do_open(self, action: Action) -> None:
        """Open the last export -- or the world folder -- in the external editor."""
        from amulet_map_editor.api import export_actions

        target: Optional[Path] = None
        what = ""
        if self.last_export is not None and self.last_export.exists():
            target, what = self.last_export, "the file this window just exported"
        else:
            ctx = self.world()
            if ctx.path and os.path.isdir(ctx.path):
                target, what = Path(ctx.path), "the open world's folder"
        if target is None:
            self._notify(
                action.label,
                "There is nothing to open: this window has not exported a file "
                "yet, and no world folder is open. Export first, or open a "
                "world, and the editor will have something real to show.",
                severity="warning",
            )
            return
        result = export_actions.open_exported_path(target)
        self._notify(
            action.label,
            (
                f"{result.message} Opened {what}: {target}."
                if result.ok
                else f"{result.message} The target was {target}."
            ),
            severity="info" if result.ok else "error",
        )

    # -- copy ---------------------------------------------------------------
    def _do_copy(self, action: Action) -> None:
        """Put a reading on the clipboard -- the named one, or the whole window."""
        if self._needs_world(action):
            return
        ctx = self.world()
        text = ""
        what = ""
        label = action.label.lower()
        if "seed" in label:
            if not ctx.seed:
                self._notify(
                    action.label,
                    "This world records no seed in its level.dat"
                    + (f" ({ctx.reason('seed')})" if ctx.reason("seed") else "")
                    + ", so there is nothing to copy.",
                    severity="warning",
                )
                return
            text, what = ctx.seed, "the world seed"
        elif "path" in label or "folder" in label:
            text, what = ctx.path, "the world folder"
        elif self.selected_row is not None:
            text, what = self.selected_label(), "the selected record"
        else:
            text, what = self._export_text("txt"), "everything this window shows"
        if not text:
            self._notify(
                action.label,
                "There is nothing to copy: this window is showing no records.",
                severity="warning",
            )
            return
        if not wx.TheClipboard.Open():
            self._notify(
                action.label,
                "The clipboard could not be opened, so nothing was copied.",
                severity="error",
            )
            return
        try:
            wx.TheClipboard.SetData(wx.TextDataObject(text))
            wx.TheClipboard.Flush()
        finally:
            wx.TheClipboard.Close()
        summary = text if len(text) <= 60 else f"{len(text)} characters"
        self._notify(action.label, f"Copied {what}: {summary}.")

    # -- searching ----------------------------------------------------------
    def _match_report(self) -> str:
        """Return what the current searches actually match, in one sentence."""
        total = self._total_records()
        matched = len([record for record in self._records() if record[1] != "note"])
        query = self.window_search.query
        if not query:
            return (
                f"No search is active, so all {total} readings in this window "
                "are on show."
            )
        return f"{matched} of {total} readings match “{query}”."

    def _do_find(self, action: Action) -> None:
        """Report what the window search matches in the readings on show."""
        if self._needs_world(action):
            return
        self._notify(action.label, self._match_report())

    def _do_preview(self, action: Action) -> None:
        """Report what the window is about to act on, before anything acts."""
        if self._needs_world(action):
            return
        selected = self.selected_label()
        detail = f" The selected record is {selected}." if selected else ""
        self._notify(
            action.label,
            self._match_report()
            + detail
            + " Nothing has been changed; this is what the operation would cover.",
        )

    # -- records ------------------------------------------------------------
    def _reads_from(self) -> str:
        """Return what this surface reads, named as the user would name it."""
        ctx = self.world()
        return ctx.path or ctx.name or "the open world"

    def _do_add(self, action: Action) -> None:
        self._report_read_only(action, "add a record to")

    def _do_remove(self, action: Action) -> None:
        self._report_read_only(action, "remove a record from")

    def _report_read_only(self, action: Action, what: str) -> None:
        """Say plainly that this window reads its records and does not write them."""
        if self._needs_world(action):
            return
        selected = self.selected_label()
        target = (
            f"The selected record is {selected}."
            if selected
            else "No record is selected in this window."
        )
        self._notify(
            action.label,
            f"{target} This window reads its records from {self._reads_from()} "
            f"and does not {what} it, so nothing was changed. Use the editor "
            "for that data -- the NBT editor writes the stored tags directly.",
            severity="warning",
        )

    def _do_reset(self, action: Action) -> None:
        """Clear the window's searches and read the world again from disk."""
        ctx = self.world()
        # The window search lives in the header, which a rebuild never touches,
        # so clearing the state alone would leave the old query still typed in
        # the field it no longer applies to.
        self.search_bar.set_query("", notify=False)
        self.window_search.reset()
        for state in self._section_states.values():
            state.reset()
        refreshed = ctx
        if ctx.open:
            try:
                refreshed = world_context.refresh()
            except Exception as error:  # noqa: BLE001 - reported, never raised
                log.exception("Could not re-read the open world")
                self._notify(
                    action.label,
                    f"The open world could not be re-read: "
                    f"{type(error).__name__}: {error}.",
                    severity="error",
                )
                return
        self.rebind()
        self._record_history(
            f"studio.reset.{self.spec.key}",
            {
                "surface": self.spec.key,
                "world": refreshed.path,
                "sections": len(self.spec.sections),
            },
            record_type="studio reset",
        )
        if not refreshed.open:
            self._notify(
                action.label,
                "Cleared this window's searches. No world is open, so there was "
                "nothing to re-read.",
            )
            return
        name = refreshed.name or "the open world"
        self._notify(
            action.label,
            f"Cleared this window's searches and read {name} again from disk: "
            f"{self._total_records()} readings in "
            f"{len(self.spec.sections)} sections. Nothing stored in the world "
            "was changed.",
        )

    @staticmethod
    def _record_history(record_id: str, payload: dict, *, record_type: str) -> None:
        """Record one change in the local history, never failing the action."""
        try:
            from amulet_map_editor.api import local_history

            local_history.safe_record(record_id, payload, record_type=record_type)
        except Exception:  # noqa: BLE001 - history is audit support, not the job
            log.debug("Could not record %s in the local history", record_id)

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
        if event.GetEventObject() is self:
            if self._theme_unsubscribe is not None:
                self._theme_unsubscribe()
                self._theme_unsubscribe = None
            # A destroyed window that is still subscribed is told about the
            # next world and rebuilds controls that no longer exist, which
            # takes the whole shell down rather than only this surface.
            world_context.unsubscribe(self._on_world_changed)
        event.Skip()

    def refresh_theme(self) -> None:
        """Re-read the tokens and repaint the whole window."""
        try:
            if self.IsBeingDeleted():
                return
            palette = tokens.palette()
            self.SetBackgroundColour(palette.surface)
            self.body.SetBackgroundColour(palette.surface)
            # The title is owner-drawn and reads its role and its font per
            # paint, so it follows a theme or scale change on its own.
            self.title_text.refresh_theme()
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


__all__ = [
    "ACTION_VARIANTS",
    "BINDER_MODULES",
    "EXPORT_FORMATS",
    "EXPORT_WILDCARD",
    "MAX_DIALOG_HEIGHT",
    "SpecDialog",
    "load_binders",
    "open_spec",
]
