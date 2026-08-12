"""A painted tab strip that answers to the ``wx.Notebook`` API.

``wx.Notebook`` draws the platform's own tabs.  On this surface that is wrong
twice over: it puts a strip of somebody else's design across the top of a
product that paints everything else itself, and -- because a native control on
a desktop with no compositor photographs as an empty rectangle -- a capture of
a notebook comes back with no tabs in it at all while reporting success.

The tab *model* is not reinvented here.  :mod:`amulet_map_editor.api.tab_groups`
already owns docking, ordering, pinning, grouping, the four searches, and the
persisted state behind them, and it is tested on its own.  This module is the
drawn surface over that model: a strip of painted buttons, an overflow list for
what does not fit, a search field carrying the project's regex builder, and a
right-click menu that pins, reorders, re-docks, and opens the per-tab
appearance editor.

The strip docks to any edge and defaults to the left, which is the project's
default and is also the one that fits: a screen is wider than it is tall and a
tab label is wider than it is high, so a vertical strip shows more tabs legibly
than a horizontal one.  Docking is an orientation change rather than a
rotation -- a label is never turned on its side, because a sideways word is a
word nobody reads -- and the keyboard follows the axis, so a vertical strip
moves on Up and Down rather than Left and Right.
"""

from __future__ import annotations

import logging
import re
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import wx

from amulet_map_editor.api import tab_groups
from amulet_map_editor.api.studio import tokens
from amulet_map_editor.api.studio import widgets
from amulet_map_editor.api.studio.search import SearchState
from amulet_map_editor.api.studio.widgets import (
    AnchoredPopup,
    SearchBar,
    StudioButton,
    _Interactive,
    _Themed,
    draw_focus_ring,
    elide,
    invoke,
    measuring,
    point_size,
)

log = logging.getLogger(__name__)

_MEDIUM = (
    wx.FONTWEIGHT_MEDIUM if hasattr(wx, "FONTWEIGHT_MEDIUM") else wx.FONTWEIGHT_BOLD
)

#: How the two axes differ, so the geometry is written once rather than twice.
_VERTICAL_DOCKS = (tab_groups.TabDock.LEFT, tab_groups.TabDock.RIGHT)


def _slug(text: str) -> str:
    """Return a stable tab id for a page title."""
    return re.sub(r"[^a-z0-9]+", "-", str(text).casefold()).strip("-") or "tab"


class _TabButton(wx.Control, _Interactive):
    """One painted tab: its title, its pinned marker, and its selected state."""

    PADDING = 12
    HEIGHT = 36
    PIN = 6

    def __init__(self, parent: wx.Window, tab: tab_groups.Tab) -> None:
        super().__init__(parent, style=wx.BORDER_NONE | wx.WANTS_CHARS)
        self.tab = tab
        self.selected = False
        self.vertical = True
        self._install(tab.title, listen=False)
        self._bind_interaction()
        self.Bind(wx.EVT_CONTEXT_MENU, self._on_context_menu)
        self.SetInitialSize(self.DoGetBestSize())

    # -- geometry ------------------------------------------------------------
    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        with measuring(self) as dc:
            dc.SetFont(tokens.font_px(self, point_size(13), _MEDIUM))
            width = dc.GetTextExtent(self.tab.title or " ")[0]
        padding = tokens.scaled(self.PADDING)
        return wx.Size(
            width + padding * 2 + tokens.scaled(self.PIN) * 2 + 6,
            tokens.scaled(self.HEIGHT),
        )

    def set_tab(self, tab: tab_groups.Tab) -> None:
        """Adopt a new model row, re-measuring and renaming around it."""
        self.tab = tab
        self.InvalidateBestSize()
        self.SetMinSize(self.DoGetBestSize())
        self._sync_name()
        self.Refresh()

    def set_selected(self, selected: bool) -> None:
        self.selected = bool(selected)
        self._sync_name()
        self.Refresh()

    def _sync_name(self) -> None:
        """Name the tab the way the shared model says a tab should be named."""
        tab_groups.apply_wx_tab_accessibility(
            self,
            tab=self.tab,
            active=self.selected,
            position=self.tab.order + 1,
            panel_id=f"panel-{self.tab.tab_id}",
        )
        state = "selected" if self.selected else "not selected"
        pinned = ", pinned" if self.tab.pinned else ""
        wx.Control.SetName(self, f"{self.tab.title}{pinned}, {state}")

    # -- behaviour -----------------------------------------------------------
    def activate(self) -> None:
        strip = self.GetParent()
        chooser = getattr(strip, "choose", None)
        if callable(chooser):
            chooser(self.tab.tab_id)

    def _on_key_down(self, event: wx.KeyEvent) -> None:
        strip = self.GetParent()
        mover = getattr(strip, "move_focus", None)
        code = event.GetKeyCode()
        forward = wx.WXK_DOWN if self.vertical else wx.WXK_RIGHT
        backward = wx.WXK_UP if self.vertical else wx.WXK_LEFT
        if callable(mover) and code in (forward, backward, wx.WXK_HOME, wx.WXK_END):
            mover(self.tab.tab_id, code, forward, backward)
            return
        super()._on_key_down(event)

    def _on_context_menu(self, event: wx.ContextMenuEvent) -> None:
        strip = self.GetParent()
        opener = getattr(strip, "open_tab_menu", None)
        if callable(opener):
            opener(self)
        event.Skip(False)

    # -- painting ------------------------------------------------------------
    def render_to(self, dc: wx.DC, rect: wx.Rect) -> None:
        """Draw the tab's container, its pinned marker, and its title."""
        palette = self.palette()
        with self._painting(dc, rect) as rect:
            radius = tokens.scaled(tokens.RADIUS_SM)
            if self.selected:
                tokens.draw_round_rect(dc, rect, radius, palette.primary_container)
                ink = palette.on_primary_container
            elif self._hovered or self._pressed:
                tokens.draw_round_rect(dc, rect, radius, palette.surface_container_high)
                ink = palette.on_surface
            else:
                ink = palette.on_surface_variant
            left = tokens.scaled(self.PADDING)
            if self.tab.pinned:
                pin = tokens.scaled(self.PIN)
                dc.SetBrush(wx.Brush(palette.primary))
                dc.SetPen(wx.TRANSPARENT_PEN)
                dc.DrawEllipse(left - pin // 2, (rect.height - pin) // 2, pin, pin)
                left += pin + tokens.scaled(4)
            dc.SetFont(tokens.font_px(self, point_size(13), _MEDIUM))
            dc.SetTextForeground(ink)
            title = elide(
                dc, self.tab.title, max(0, rect.width - left - tokens.scaled(8))
            )
            widgets.note_elision(self, self.tab.title, title)
            dc.DrawText(title, left, (rect.height - dc.GetCharHeight()) // 2)
            if self.HasFocus():
                draw_focus_ring(dc, rect, radius, palette.primary)


class _MenuPopup(AnchoredPopup):
    """A searchable anchored menu.

    Every menu in this project carries its own search field wired to the full
    regex builder, and that is not a rule about long menus: a four-item menu
    grows to fourteen without anybody revisiting the decision, and a user who
    has learned to type in one menu and finds the next one inert has learned
    that the pattern is unreliable.
    """

    def __init__(
        self,
        parent: wx.Window,
        anchor: wx.Window,
        title: str,
        rows: Sequence[Tuple[str, Callable[[], None]]],
        *,
        label: str = "Menu",
    ) -> None:
        super().__init__(parent, anchor, width=tokens.scaled(280), max_height=380)
        self.SetName(f"{title} menu")
        self._rows = list(rows)
        self._buttons: List[StudioButton] = []
        self.state = SearchState(label=label)
        header = wx.BoxSizer(wx.VERTICAL)
        self.search = SearchBar(
            self.header,
            f"Search {label.casefold()}",
            self.state,
            on_change=lambda _state: self._rebuild(),
            compact=True,
        )
        header.Add(self.search, 0, wx.EXPAND)
        self.header.SetSizer(header)
        self._feedback = widgets.StudioText(
            self.content, "", size_px=11, name=f"{title} menu feedback"
        )
        self._rebuild()

    def _rebuild(self) -> None:
        """Redraw the rows surviving the menu's own search, and count them."""
        for button in self._buttons:
            button.Destroy()
        self._buttons = []
        self.content_sizer.Clear(False)
        labels = [label for label, _action in self._rows]
        try:
            surviving = set(self.state.filter(labels))
        except (re.error, ValueError):
            surviving = set()
        for label, action in self._rows:
            if label not in surviving:
                continue
            button = StudioButton(
                self.content,
                label,
                variant="text",
                on_click=self._runner(action),
                name=label,
            )
            self._buttons.append(button)
            self.content_sizer.Add(button, 0, wx.EXPAND | wx.BOTTOM, 2)
        # A menu narrowed to two rows still says how many it started with, so
        # an empty result reads as no match rather than as a broken menu.
        self._feedback.SetLabel(
            f"{len(surviving)} of {len(labels)} rows · {self.state.feedback()}"
        )
        self.content_sizer.Add(self._feedback, 0, wx.EXPAND | wx.TOP, tokens.SPACE_XS)
        self.layout()

    def _runner(self, action: Callable[[], None]) -> Callable[[], None]:
        def run() -> None:
            self.Dismiss()
            invoke(action)

        return run


class _Strip(wx.Panel, _Themed):
    """The painted band the tab buttons sit on.

    It is painted rather than left as a native panel for the same reason the
    buttons are: a native container photographs as a flat rectangle of the
    platform's own colour, so a capture of the strip shows neither the band nor
    the edge it is ruled off with.
    """

    def __init__(self, parent: wx.Window) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self._install("Tab strip", listen=False)
        self.vertical = True
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self._apply_theme(self.palette())

    def _apply_theme(self, palette: tokens.StudioPalette) -> None:
        self.SetBackgroundColour(palette.surface_container)

    def _backdrop(self) -> wx.Colour:
        return self.palette().surface_container

    def render_to(self, dc: wx.DC, rect: wx.Rect) -> None:
        """Fill the band and rule it off from the content beside it."""
        palette = self.palette()
        with self._painting(dc, rect) as rect:
            dc.SetBrush(wx.Brush(palette.surface_container))
            dc.SetPen(wx.TRANSPARENT_PEN)
            dc.DrawRectangle(rect)
            dc.SetPen(wx.Pen(palette.outline_variant, 1))
            if self.vertical:
                dc.DrawLine(rect.width - 1, 0, rect.width - 1, rect.height)
            else:
                dc.DrawLine(0, rect.height - 1, rect.width, rect.height - 1)
            dc.SetPen(wx.NullPen)


class MaterialTabs(wx.Panel, _Themed):
    """A painted, dockable tab surface answering to the ``wx.Notebook`` API.

    ``AddPage``, ``GetPageCount``, ``GetPageIndex``, ``RemovePage``,
    ``SetSelection``, ``GetSelection``, ``GetPageText`` and ``GetPage`` keep
    their spelling, and a page change raises ``wx.EVT_NOTEBOOK_PAGE_CHANGED``,
    so a surface written against ``wx.Notebook`` is a constructor swap.

    ``surface_id`` names the persisted state: the dock edge, the tab order, the
    pinned set, and the groups all survive a restart under that key.
    """

    STRIP_PADDING = 8
    SEARCH_WIDTH = 190

    def __init__(
        self,
        parent: wx.Window,
        surface_id: str,
        *,
        dock: Optional[tab_groups.TabDock] = None,
    ) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self._install("Tabs", listen=False)
        self.workspace = tab_groups.TabWorkspace(surface_id)
        if dock is not None:
            self._safely(lambda: self.workspace.set_dock(dock))
        self._pages: Dict[str, wx.Window] = {}
        self._buttons: Dict[str, _TabButton] = {}
        self._order: List[str] = []
        self._selection = wx.NOT_FOUND
        self._menu: Optional[_MenuPopup] = None
        self._overflowed: List[str] = []
        #: Guards the hand-written layout against re-entering itself: it
        #: resizes the strip, which raises the size event that runs it.
        self._laying_out = False

        self.strip = _Strip(self)
        self.strip.vertical = self.vertical
        self.strip.choose = self.select_tab  # type: ignore[attr-defined]
        self.strip.move_focus = self._move_focus  # type: ignore[attr-defined]
        self.strip.open_tab_menu = self.open_tab_menu  # type: ignore[attr-defined]
        self.strip.Bind(wx.EVT_CONTEXT_MENU, self._on_strip_menu)

        self.search_state = SearchState(label="Tabs on this strip")
        self.search = SearchBar(
            self.strip,
            "Search tabs",
            self.search_state,
            on_change=lambda _state: self._relayout(),
            compact=True,
        )
        self.overflow = StudioButton(
            self.strip,
            "More…",
            variant="text",
            hint="Tabs that do not fit on the strip",
            on_click=self.open_overflow,
            name="More tabs",
        )
        self.overflow.Hide()

        self.host = wx.Panel(self, style=wx.TAB_TRAVERSAL)
        self.host.SetName("Tab content")
        self.host.SetSizer(wx.BoxSizer(wx.VERTICAL))

        self._layout_root()
        self.Bind(wx.EVT_SIZE, lambda event: (self._relayout(), event.Skip()))
        self.strip.Bind(wx.EVT_SIZE, lambda event: (self._relayout(), event.Skip()))
        self._apply_theme(self.palette())

    # -- persistence ---------------------------------------------------------
    @staticmethod
    def _safely(call: Callable[[], object]) -> None:
        """Run a persisted-state change, keeping a read-only profile usable.

        A settings surface that refuses to open because its tab order could not
        be written would turn an unwritable profile into a broken application.
        """
        try:
            call()
        except (ValueError, OSError):
            log.debug("A tab-state change could not be persisted", exc_info=True)

    @property
    def dock(self) -> tab_groups.TabDock:
        return self.workspace.state.dock

    @property
    def vertical(self) -> bool:
        return self.dock in _VERTICAL_DOCKS

    def set_dock(self, dock: tab_groups.TabDock) -> None:
        """Move the strip to another edge and re-lay the surface out around it."""
        self._safely(lambda: self.workspace.set_dock(dock))
        for button in self._buttons.values():
            button.vertical = self.vertical
        self.strip.vertical = self.vertical
        self._layout_root()
        self._relayout()

    def _layout_root(self) -> None:
        """Place the strip and the content on the axis the dock chooses."""
        # Detach first.  ``SetSizer(deleteOld=True)`` destroys the old sizer
        # but leaves each child still claiming to be in one, so re-adding it
        # trips a wx assertion -- which is what a dock change did every time.
        existing = self.GetSizer()
        if existing is not None:
            existing.Detach(self.strip)
            existing.Detach(self.host)
        horizontal = self.vertical
        root = wx.BoxSizer(wx.HORIZONTAL if horizontal else wx.VERTICAL)
        first = self.dock in (tab_groups.TabDock.LEFT, tab_groups.TabDock.TOP)
        if first:
            root.Add(self.strip, 0, wx.EXPAND)
            root.Add(self.host, 1, wx.EXPAND)
        else:
            root.Add(self.host, 1, wx.EXPAND)
            root.Add(self.strip, 0, wx.EXPAND)
        self.SetSizer(root, deleteOld=True)
        self.Layout()

    # -- the wx.Notebook vocabulary -----------------------------------------
    def AddPage(  # noqa: N802 - wx API spelling
        self, page: wx.Window, text: str, select: bool = False
    ) -> bool:
        """Adopt ``page`` under a new tab titled ``text``."""
        tab_id = _slug(text)
        suffix = 1
        while tab_id in self._pages:
            suffix += 1
            tab_id = f"{_slug(text)}-{suffix}"
        existing = next(
            (item for item in self.workspace.state.tabs if item.tab_id == tab_id), None
        )
        if existing is None:
            self._safely(lambda: self.workspace.add_tab(text, tab_id=tab_id))
            existing = next(
                (item for item in self.workspace.state.tabs if item.tab_id == tab_id),
                tab_groups.Tab(tab_id, str(text), None, False, len(self._order)),
            )
        page.Reparent(self.host)
        page.Hide()
        self.host.GetSizer().Add(page, 1, wx.EXPAND)
        self._pages[tab_id] = page
        self._order.append(tab_id)
        button = _TabButton(self.strip, existing)
        button.vertical = self.vertical
        self._buttons[tab_id] = button
        if select or self._selection == wx.NOT_FOUND:
            self.SetSelection(len(self._order) - 1)
        else:
            self._relayout()
        return True

    def GetPageCount(self) -> int:  # noqa: N802 - wx API spelling
        return len(self._order)

    def GetPage(self, index: int) -> Optional[wx.Window]:  # noqa: N802
        tab_id = self._tab_id(index)
        return self._pages.get(tab_id) if tab_id else None

    def GetPageIndex(self, page: wx.Window) -> int:  # noqa: N802 - wx API spelling
        for index, tab_id in enumerate(self._order):
            if self._pages.get(tab_id) is page:
                return index
        return wx.NOT_FOUND

    def GetPageText(self, index: int) -> str:  # noqa: N802 - wx API spelling
        tab_id = self._tab_id(index)
        button = self._buttons.get(tab_id) if tab_id else None
        return button.tab.title if button is not None else ""

    def SetPageText(self, index: int, text: str) -> bool:  # noqa: N802
        tab_id = self._tab_id(index)
        button = self._buttons.get(tab_id) if tab_id else None
        if button is None:
            return False
        button.set_tab(
            tab_groups.Tab(
                button.tab.tab_id,
                str(text),
                button.tab.group_id,
                button.tab.pinned,
                button.tab.order,
            )
        )
        self._relayout()
        return True

    def RemovePage(self, index: int) -> bool:  # noqa: N802 - wx API spelling
        """Detach a page without destroying it, as ``wx.Notebook`` does."""
        tab_id = self._tab_id(index)
        if tab_id is None:
            return False
        page = self._pages.pop(tab_id, None)
        button = self._buttons.pop(tab_id, None)
        self._order.remove(tab_id)
        if page is not None:
            self.host.GetSizer().Detach(page)
            page.Hide()
        if button is not None:
            button.Destroy()
        if self._selection >= len(self._order):
            self._selection = len(self._order) - 1
        if self._order:
            self.SetSelection(max(0, self._selection))
        else:
            self._selection = wx.NOT_FOUND
            self._relayout()
        return True

    def DeletePage(self, index: int) -> bool:  # noqa: N802 - wx API spelling
        tab_id = self._tab_id(index)
        page = self._pages.get(tab_id) if tab_id else None
        removed = self.RemovePage(index)
        if removed and page is not None:
            page.Destroy()
        return removed

    def GetSelection(self) -> int:  # noqa: N802 - wx API spelling
        return self._selection

    def SetSelection(self, index: int) -> int:  # noqa: N802 - wx API spelling
        """Show one page, hide the rest, and report the change."""
        previous = self._selection
        if not 0 <= int(index) < len(self._order):
            return previous
        self._selection = int(index)
        chosen = self._order[self._selection]
        for tab_id, page in self._pages.items():
            page.Show(tab_id == chosen)
        for tab_id, button in self._buttons.items():
            button.set_selected(tab_id == chosen)
        self._safely(lambda: self.workspace.activate_tab(chosen))
        self.host.Layout()
        self._relayout()
        if previous != self._selection:
            command = wx.BookCtrlEvent(
                wx.EVT_NOTEBOOK_PAGE_CHANGED.typeId,
                self.GetId(),
                self._selection,
                previous,
            )
            command.SetEventObject(self)
            self.GetEventHandler().ProcessEvent(command)
        return previous

    def ChangeSelection(self, index: int) -> int:  # noqa: N802 - wx API spelling
        """Select without raising the page-changed event."""
        previous = self._selection
        if not 0 <= int(index) < len(self._order):
            return previous
        self._selection = int(index)
        chosen = self._order[self._selection]
        for tab_id, page in self._pages.items():
            page.Show(tab_id == chosen)
        for tab_id, button in self._buttons.items():
            button.set_selected(tab_id == chosen)
        self.host.Layout()
        self._relayout()
        return previous

    def _tab_id(self, index: int) -> Optional[str]:
        return self._order[index] if 0 <= int(index) < len(self._order) else None

    # -- selection by id -----------------------------------------------------
    def select_tab(self, tab_id: str) -> None:
        if tab_id in self._order:
            self.SetSelection(self._order.index(tab_id))
            button = self._buttons.get(tab_id)
            if button is not None and button.IsShownOnScreen():
                button.SetFocus()

    def _move_focus(self, tab_id: str, code: int, forward: int, backward: int) -> None:
        """Move the keyboard along the strip's own axis."""
        visible = [key for key in self._order if self._buttons[key].IsShown()]
        if not visible:
            return
        current = visible.index(tab_id) if tab_id in visible else 0
        if code == forward:
            target = min(len(visible) - 1, current + 1)
        elif code == backward:
            target = max(0, current - 1)
        elif code == wx.WXK_HOME:
            target = 0
        else:
            target = len(visible) - 1
        self.select_tab(visible[target])

    # -- layout --------------------------------------------------------------
    def _matching(self) -> List[str]:
        """Return the tab ids surviving the strip's own search."""
        titles = {key: self._buttons[key].tab.title for key in self._order}
        try:
            surviving = set(self.search_state.filter(list(titles.values())))
        except (re.error, ValueError):
            surviving = set(titles.values())
        if not self.search_state.query.strip():
            return list(self._order)
        chosen = self._tab_id(self._selection)
        return [
            key
            for key in self._order
            # The tab currently showing stays on the strip whatever the query
            # says: nobody should have to clear a search to see where they are.
            if titles[key] in surviving or key == chosen
        ]

    def _relayout(self) -> None:
        """Place the search, the tabs that fit, and the overflow control.

        The strip lays itself out rather than handing the job to a sizer.  A
        ``wx.BoxSizer`` given less room than its children ask for does not say
        so -- it takes the shortfall out of whatever is last in the row, which
        on this strip is the search field, so a narrow window silently pushed
        the search past the edge instead of moving a tab into the overflow.
        """
        if self._laying_out:
            return
        self._laying_out = True
        try:
            self._place()
        finally:
            self._laying_out = False

    def _place(self) -> None:
        if not self._order:
            self.search.Show(False)
            self.overflow.Hide()
            self.strip.Layout()
            return
        self.search.Show(True)
        vertical = self.vertical
        padding = tokens.scaled(self.STRIP_PADDING)
        width, height = self.strip.GetClientSize()
        matching = self._matching()
        # Pinned tabs occupy a stable region before the ordinary ones and stay
        # on the strip when the ordinary ones overflow.
        pinned = [key for key in matching if self._buttons[key].tab.pinned]
        ordinary = [key for key in matching if not self._buttons[key].tab.pinned]
        chosen = self._tab_id(self._selection)

        search_size = self.search.GetBestSize()
        # Claim the short axis before placing anything: a strip laid out inside
        # a sizer cell it never asked for is a strip whose last tab is off the
        # end of the window.
        if vertical:
            wanted = wx.Size(self.strip_width(), -1)
        else:
            wanted = wx.Size(
                -1,
                max(search_size.height, tokens.scaled(_TabButton.HEIGHT)) + padding * 2,
            )
        if self.strip.GetMinSize() != wanted:
            self.strip.SetMinSize(wanted)
            self.Layout()
            width, height = self.strip.GetClientSize()
        if vertical:
            self.search.SetSize(
                padding, padding, max(0, width - padding * 2), search_size.height
            )
            self.search.Layout()
            # The search bar carries a feedback line under its field, and that
            # line is not in every backend's reported best height. Measuring
            # what the field actually occupies after it is placed is what keeps
            # the first tab from being drawn underneath it.
            cursor = padding + self.search.GetSize().height + tokens.scaled(12)
            budget = height - padding
        else:
            # Wide enough for the bar's own feedback line, not just its field.
            # Sized to the field alone, the horizontal strip cut the line to
            # "Enable regex deliberat" -- a sentence about being deliberate,
            # truncated mid-word, which is worse than not showing it at all.
            search_width = min(
                max(tokens.scaled(self.SEARCH_WIDTH), search_size.width),
                max(tokens.scaled(self.SEARCH_WIDTH), width // 2),
            )
            self.search.SetSize(
                max(padding, width - search_width - padding),
                padding,
                search_width,
                search_size.height,
            )
            cursor = padding
            budget = width - search_width - padding * 3

        overflowed: List[str] = []
        for key in self._order:
            self._buttons[key].Show(False)
        for key in pinned + ordinary:
            button = self._buttons[key]
            best = button.DoGetBestSize()
            span = best.height if vertical else max(best.width, tokens.scaled(90))
            if cursor + span > budget and key != chosen:
                overflowed.append(key)
                continue
            if vertical:
                button.SetSize(
                    padding, cursor, max(0, width - padding * 2), best.height
                )
            else:
                button.SetSize(cursor, padding, span, best.height)
            button.Show(True)
            cursor += span + tokens.scaled(4)

        self._overflowed = overflowed
        if overflowed:
            best = self.overflow.DoGetBestSize()
            if vertical:
                self.overflow.SetSize(
                    padding, cursor, max(0, width - padding * 2), best.height
                )
            else:
                self.overflow.SetSize(cursor, padding, best.width, best.height)
            self.overflow.SetLabel(f"More… ({len(overflowed)})")
            self.overflow.Show()
        else:
            self.overflow.Hide()
        self.strip.Refresh()

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        return wx.Size(tokens.scaled(720), tokens.scaled(420))

    def strip_width(self) -> int:
        """Return the strip's own measured extent along the short axis."""
        padding = tokens.scaled(self.STRIP_PADDING)
        if not self._buttons:
            return padding * 2
        widest = max(button.DoGetBestSize().width for button in self._buttons.values())
        return max(widest, self.search.GetBestSize().width) + padding * 2

    # -- menus ---------------------------------------------------------------
    def open_overflow(self) -> None:
        """List the tabs that did not fit, with their own search field."""
        overflowed = getattr(self, "_overflowed", [])
        rows = [
            (self._buttons[key].tab.title, self._chooser(key))
            for key in overflowed
            if key in self._buttons
        ]
        if not rows:
            return
        self._show_menu(self.overflow, "Tabs that do not fit", rows, label="Tabs")

    def _chooser(self, tab_id: str) -> Callable[[], None]:
        return lambda: self.select_tab(tab_id)

    def open_tab_menu(self, button: _TabButton) -> None:
        """Open one tab's own menu: pin, reorder, re-dock, edit appearance."""
        tab = button.tab
        rows: List[Tuple[str, Callable[[], None]]] = [
            (
                "Unpin tab" if tab.pinned else "Pin tab",
                lambda: self._set_pinned(tab.tab_id, not tab.pinned),
            ),
            ("Move tab earlier", lambda: self._reorder(tab.tab_id, -1)),
            ("Move tab later", lambda: self._reorder(tab.tab_id, 1)),
            ("Edit tab appearance…", lambda: self._edit_appearance(button)),
            (
                "Dock tab strip to the left",
                lambda: self.set_dock(tab_groups.TabDock.LEFT),
            ),
            (
                "Dock tab strip to the top",
                lambda: self.set_dock(tab_groups.TabDock.TOP),
            ),
            (
                "Dock tab strip to the right",
                lambda: self.set_dock(tab_groups.TabDock.RIGHT),
            ),
            (
                "Dock tab strip to the bottom",
                lambda: self.set_dock(tab_groups.TabDock.BOTTOM),
            ),
        ]
        self._show_menu(button, tab.title, rows, label="Tab actions")

    def _on_strip_menu(self, event: wx.ContextMenuEvent) -> None:
        rows: List[Tuple[str, Callable[[], None]]] = [
            (
                "Dock tab strip to the left",
                lambda: self.set_dock(tab_groups.TabDock.LEFT),
            ),
            (
                "Dock tab strip to the top",
                lambda: self.set_dock(tab_groups.TabDock.TOP),
            ),
            (
                "Dock tab strip to the right",
                lambda: self.set_dock(tab_groups.TabDock.RIGHT),
            ),
            (
                "Dock tab strip to the bottom",
                lambda: self.set_dock(tab_groups.TabDock.BOTTOM),
            ),
            ("Clear the tab search", self._clear_search),
        ]
        self._show_menu(self.search, "Tab strip", rows, label="Strip actions")
        event.Skip(False)

    def _show_menu(
        self,
        anchor: wx.Window,
        title: str,
        rows: Sequence[Tuple[str, Callable[[], None]]],
        *,
        label: str,
    ) -> None:
        self._dismiss_menu()
        menu = _MenuPopup(self, anchor, title, rows, label=label)
        self._menu = menu
        menu.on_dismiss = self._forget_menu
        menu.popup()
        menu.search.SetFocus()

    def _forget_menu(self) -> None:
        self._menu = None

    def _dismiss_menu(self) -> None:
        menu, self._menu = self._menu, None
        if menu is not None:
            try:
                menu.Dismiss()
                menu.Destroy()
            except RuntimeError:
                pass

    def _clear_search(self) -> None:
        self.search_state.query = ""
        self.search.field.set_value("")
        self.search.refresh_feedback()
        self._relayout()

    # -- model changes -------------------------------------------------------
    def _set_pinned(self, tab_id: str, pinned: bool) -> None:
        self._safely(lambda: self.workspace.set_pinned(tab_id, pinned))
        self._adopt_state()

    def _reorder(self, tab_id: str, offset: int) -> None:
        current = self._order.index(tab_id) if tab_id in self._order else 0
        self._safely(lambda: self.workspace.reorder_tab(tab_id, current + offset))
        self._adopt_state()

    def _adopt_state(self) -> None:
        """Re-read the model after a change and re-order the strip to match."""
        rows = {tab.tab_id: tab for tab in self.workspace.state.tabs}
        chosen = self._tab_id(self._selection)
        for tab_id, button in self._buttons.items():
            if tab_id in rows:
                button.set_tab(rows[tab_id])
        self._order.sort(
            key=lambda key: (
                rows[key].order if key in rows else len(self._order),
                key,
            )
        )
        if chosen in self._order:
            self._selection = self._order.index(chosen)
        self._relayout()

    def _edit_appearance(self, button: _TabButton) -> None:
        try:
            from amulet_map_editor.api.wx.ui.element_appearance import (
                open_element_appearance,
            )
        except ImportError:
            log.debug("The element appearance editor is not available")
            return
        open_element_appearance(button)

    # -- painting ------------------------------------------------------------
    def _apply_theme(self, palette: tokens.StudioPalette) -> None:
        self.SetBackgroundColour(palette.surface)
        self.strip.SetBackgroundColour(palette.surface_container)
        self.host.SetBackgroundColour(palette.surface)

    def _backdrop(self) -> wx.Colour:
        return self.palette().surface
