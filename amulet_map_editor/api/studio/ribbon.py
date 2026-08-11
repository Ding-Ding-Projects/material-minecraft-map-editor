"""The Amulet Studio command ribbon: a tab strip over a scrolling panel.

The strip carries the backstage button, the seventeen tab buttons, a search
over the active tab's own commands, and the collapse chevron.  The panel below
draws one column per group -- controls in a row, then a centred uppercase title
beside its dialog launcher -- separated by vertical dividers, and scrolls
horizontally when the groups are wider than the window: a ribbon that clips its
last group hides commands with nothing on screen to say they are there.

Collapsing hides the panel and keeps the strip, and the choice is persisted, so
somebody who works with the ribbon collapsed does not collapse it again at
every launch.
"""

from __future__ import annotations

import logging
from typing import Callable, Dict, List, Optional, Tuple

import wx

from amulet_map_editor.api.studio import context_menu, ribbon_defs, tokens, widgets
from amulet_map_editor.api.studio.ribbon_defs import (
    RIBBON_TABS,
    RibbonButton,
    RibbonField,
    RibbonGroup,
    RibbonSelect,
    RibbonTab,
)
from amulet_map_editor.api.studio.search import SearchState

log = logging.getLogger(__name__)

__all__ = ["RIBBON_STATE_KEY", "RibbonBar"]

#: Where the collapsed/expanded choice is remembered between launches.
RIBBON_STATE_KEY = "studio.ribbon.expanded"

_MEDIUM = getattr(wx, "FONTWEIGHT_MEDIUM", wx.FONTWEIGHT_NORMAL)


def _fill_ribbon_gradient(
    window: wx.Window,
    dc: wx.DC,
    palette: tokens.StudioPalette,
    size: Optional[wx.Size] = None,
) -> None:
    """Continue the ribbon panel's gradient across one of its children.

    A child window cannot see through to its parent's paint, so each one draws
    the same top-to-bottom ramp offset by its own position.  Painting the ramp
    per child rather than a flat colour is what keeps a group column from
    reading as a lighter rectangle sitting on the ribbon.

    ``size`` lets a render use the rect it was handed instead of the window's
    own client size.  The vertical offset still comes from the window's real
    position, because that is what decides where in the ramp this child sits.
    """
    width, height = size if size is not None else window.GetClientSize()
    if width <= 0 or height <= 0:
        return
    parent = window.GetParent()
    total = parent.GetClientSize().height if parent is not None else height
    offset = window.GetPosition().y if parent is not None else 0
    if total <= 0:
        total = height
        offset = 0
    dc.GradientFillLinear(
        wx.Rect(0, -offset, width, total),
        palette.surface,
        palette.surface_container,
        wx.SOUTH,
    )


class _TabButton(widgets.StudioButton):
    """One tab in the strip: 36px tall with only its top corners rounded.

    ``StudioButton`` draws a uniform radius and the design's tabs meet the
    panel below them, so the shape is painted here: a rounded rectangle taller
    than the control, whose bottom corners therefore fall outside the visible
    area and read as square.
    """

    HEIGHT = 36
    RADIUS = 9

    #: Class defaults so the first ``DoGetBestSize`` during construction has
    #: something to measure with.
    emphasis = "quiet"
    on_navigate: Optional[Callable[[int], None]] = None
    #: Which ribbon tab this button opens, or empty for the backstage and
    #: overflow buttons that are on the strip without being tabs.
    tab_key = ""

    def __init__(
        self,
        parent: wx.Window,
        label: str,
        *,
        on_click: Optional[Callable[[], None]] = None,
        on_navigate: Optional[Callable[[int], None]] = None,
        emphasis: str = "quiet",
        name: str = "",
        hint: str = "",
        tab_key: str = "",
    ) -> None:
        super().__init__(
            parent,
            label,
            variant="text",
            on_click=on_click,
            name=name or label,
            hint=hint,
            height=self.HEIGHT,
        )
        self.emphasis = emphasis
        self.on_navigate = on_navigate
        self.tab_key = str(tab_key)
        self.InvalidateBestSize()
        self.SetInitialSize(self.DoGetBestSize())

    def set_emphasis(self, emphasis: str) -> None:
        """Switch between ``filled``, ``active``, and ``quiet`` presentation."""
        if emphasis != self.emphasis:
            self.emphasis = emphasis
            self.InvalidateBestSize()
            self.SetMinSize(self.DoGetBestSize())
            self.Refresh()

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        with widgets.measuring(self) as dc:
            dc.SetFont(tokens.font(self, widgets.point_size(13), _MEDIUM))
            padding = tokens.scaled(18 if self.emphasis == "filled" else 16)
            lines = [line for line in self.GetLabel().split("\n") if line] or [" "]
            width = (
                max(dc.GetTextExtent(line)[0] for line in lines)
                + widgets.TEXT_SLACK * 2
                + padding * 2
            )
            # The design draws a 36px tab; a density or interface-scale change
            # moves every other control in the shell and a tab that stayed at
            # 36 would be the one that did not.
            height = max(tokens.scaled(self.HEIGHT), tokens.control_height())
            if len(lines) > 1:
                height = max(
                    height, dc.GetCharHeight() * len(lines) + tokens.scaled(10)
                )
            return wx.Size(width, height)

    def _tab_colours(
        self, palette: tokens.StudioPalette
    ) -> Tuple[Optional[wx.Colour], wx.Colour]:
        if self.emphasis == "filled":
            return palette.primary, palette.on_primary
        if self.emphasis == "active":
            return palette.primary_container, palette.on_primary_container
        if self._pressed:
            return (
                tokens.blend(palette.surface_container_high, palette.on_surface, 0.10),
                palette.on_surface,
            )
        if self._hovered:
            return palette.surface_container_high, palette.on_surface
        return None, palette.on_surface_variant

    def _backdrop(self) -> wx.Colour:
        palette = self.palette()
        parent = self.GetParent()
        backdrop = parent.GetBackgroundColour() if parent else palette.surface_container
        return backdrop if backdrop.IsOk() else palette.surface_container

    def render_to(self, dc: wx.DC, rect: wx.Rect) -> None:
        """Draw the tab: a shape rounded only at the top, and its label."""
        palette = self.palette()
        with self._painting(dc, rect) as rect:
            width, height = rect.width, rect.height
            radius = tokens.scaled(self.RADIUS)
            fill, ink = self._tab_colours(palette)
            if fill is not None:
                tokens.draw_round_rect(
                    dc, wx.Rect(0, 0, width, height + radius), radius, fill
                )
            weight = (
                _MEDIUM
                if self.emphasis in ("filled", "active")
                else wx.FONTWEIGHT_NORMAL
            )
            dc.SetFont(tokens.font(self, widgets.point_size(13), weight))
            dc.SetTextForeground(ink)
            lines = [line for line in self.GetLabel().split("\n") if line] or [" "]
            available = max(0, width - tokens.scaled(12))
            rendered = [widgets.elide(dc, line, available) for line in lines]
            widgets.note_elision(
                self, "\n".join(lines), "\n".join(rendered), hint=self.hint
            )
            line_height = dc.GetCharHeight()
            y = (height - line_height * len(rendered)) // 2
            for line in rendered:
                dc.DrawText(line, (width - dc.GetTextExtent(line)[0]) // 2, y)
                y += line_height
            if self.HasFocus():
                widgets.draw_focus_ring(dc, rect, radius, palette.primary)

    def _on_key_down(self, event: wx.KeyEvent) -> None:
        if (
            event.GetKeyCode()
            in (
                wx.WXK_LEFT,
                wx.WXK_RIGHT,
                wx.WXK_HOME,
                wx.WXK_END,
            )
            and self.on_navigate is not None
        ):
            widgets.invoke(self.on_navigate, event.GetKeyCode())
            return
        super()._on_key_down(event)


class _RibbonTile(widgets.StudioButton):
    """One command tile: a glyph badge over a label that wraps to two lines.

    The design fills a group's leading command with the primary container so
    the obvious action is visible without reading every label, which the shared
    ``ribbon`` variant has no state for; that fill is applied here.
    """

    def __init__(
        self,
        parent: wx.Window,
        definition: RibbonButton,
        *,
        on_click: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(
            parent,
            definition.label,
            variant="ribbon",
            glyph=definition.glyph,
            hint=definition.hint,
            on_click=on_click,
            name=definition.accessible_name,
        )
        self.definition = definition

    def _state_colours(
        self, palette: tokens.StudioPalette
    ) -> Tuple[Optional[wx.Colour], wx.Colour, Optional[wx.Colour]]:
        fill, ink, border = super()._state_colours(palette)
        definition = getattr(self, "definition", None)
        if definition is None or not definition.primary or not self.IsEnabled():
            return fill, ink, border
        base = palette.primary_container
        if self._pressed:
            base = tokens.blend(base, palette.on_primary_container, 0.16)
        elif self._hovered:
            base = tokens.blend(base, palette.on_primary_container, 0.08)
        return base, palette.on_primary_container, border


class _TabOverflowPopup(widgets.AnchoredPopup):
    """The list of tabs the strip could not fit, with its own search.

    A tab that does not fit is still a tab: it keeps its place in this list,
    its accessible name, and its keyboard route to the panel it opens.  The
    list carries the same search bar and anchored regex builder every other
    list in the shell does, because a strip that has overflowed is exactly when
    somebody wants to find a tab by name rather than by eye.
    """

    def __init__(
        self,
        parent: wx.Window,
        anchor: wx.Window,
        buttons: List["_TabButton"],
        active: Optional[str] = None,
        *,
        on_choose: Optional[Callable[["_TabButton"], None]] = None,
    ) -> None:
        # No height cap of its own: the popup already clamps itself to the
        # display's work area and scrolls past that, and a cap chosen here
        # would leave a row folded in half at the bottom of a list that had
        # room to show it.
        super().__init__(parent, anchor)
        self.buttons = list(buttons)
        self.active = active or ""
        self.on_choose = on_choose
        self.state = SearchState(label="Tabs that do not fit")
        self.search = widgets.SearchBar(
            self.header,
            "Search the tabs in here",
            self.state,
            on_change=lambda _state: self._rebuild(),
            compact=True,
        )
        header_sizer = wx.BoxSizer(wx.VERTICAL)
        header_sizer.Add(self.search, 0, wx.EXPAND)
        self.header.SetSizer(header_sizer)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)
        self._rebuild()

    def _on_key(self, event: wx.KeyEvent) -> None:
        """Escape closes the list; the arrow keys walk it."""
        code = event.GetKeyCode()
        rows = [
            child
            for child in self.content.GetChildren()
            if isinstance(child, widgets._OptionRow)
        ]
        if code == wx.WXK_ESCAPE:
            self.Dismiss()
            return
        if code in (wx.WXK_DOWN, wx.WXK_UP) and rows:
            focused = self.FindFocus()
            index = rows.index(focused) if focused in rows else -1
            step = 1 if code == wx.WXK_DOWN else -1
            rows[(index + step) % len(rows)].SetFocus()
            return
        if code in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER) and rows:
            focused = self.FindFocus()
            row = focused if focused in rows else rows[0]
            row.activate()
            return
        event.Skip()

    def _rebuild(self) -> None:
        """Fill the list with the overflowed tabs matching the query."""
        self.content.DestroyChildren()
        self.content_sizer = wx.BoxSizer(wx.VERTICAL)
        self.content.SetSizer(self.content_sizer)
        matches = [
            button
            for button in self.buttons
            if self.state.matches(button.GetLabel().replace("\n", " "))
        ]
        if not matches:
            empty = widgets.StudioText(
                self.content, self.state.describe_matches(0, "tab"), size_px=12
            )
            self.content_sizer.Add(empty, 0, wx.ALL, tokens.scaled(tokens.SPACE_SM))
        for button in matches:
            label = button.GetLabel().replace("\n", " · ")
            row = widgets._OptionRow(
                self.content,
                label,
                selected=bool(button.tab_key) and button.tab_key == self.active,
                on_click=lambda _label, target=button: self._choose(target),
            )
            self.content_sizer.Add(row, 0, wx.EXPAND | wx.BOTTOM, tokens.scaled(2))
        self.layout()

    def _choose(self, button: "_TabButton") -> None:
        self.Dismiss()
        widgets.invoke(self.on_choose, button)


class _TabStrip(wx.Panel, widgets._Themed):
    """The tab buttons, the command search, and the chevron, laid out by hand.

    Seventeen tabs, a search field and a collapse control do not fit at every
    width, and a ``wx.BoxSizer`` given less room than its children ask for does
    not say so: it takes the shortfall out of whatever is at the end of the
    row.  On this strip the end of the row is the search, so at 1024 pixels the
    field was pushed past the right-hand edge and what survived of it read
    "Reg" and "Plain-tex" -- a search bar cut in half by a tab strip that had
    quietly claimed the space.

    So the strip lays itself out.  The search and the chevron are placed from
    the right-hand edge first, because they are the two controls that must
    always be reachable; the tabs then take what is left, and the ones that do
    not fit move into an overflow control that lists them by name.  A tab is
    never merely clipped, and the tab currently showing is always on the strip
    even when it would otherwise have overflowed -- nobody should have to open
    a menu to see where they already are.
    """

    #: Gaps, transcribed from the design: after the backstage button, between
    #: tabs, and around the trailing controls.
    LEAD_GAP = tokens.SPACE_XS
    TAB_GAP = 2
    TRAIL_GAP = tokens.SPACE_XS
    EDGE = tokens.SPACE_SM
    VERTICAL_PAD = 4

    def __init__(self, parent: wx.Window) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self._install("Ribbon tabs", listen=False)
        self.leading: Optional[wx.Window] = None
        self.tabs: List[_TabButton] = []
        self.search: Optional[wx.Window] = None
        self.chevron: Optional[wx.Window] = None
        self.overflow: Optional[widgets.StudioButton] = None
        self.search_stretch = 0
        self._overflowed: List[_TabButton] = []
        self._popup: Optional[_TabOverflowPopup] = None
        #: Called with the tab button somebody picked out of the overflow list.
        self.on_overflow_choice: Optional[Callable[["_TabButton"], None]] = None
        #: Returns the key of the tab currently showing, so the strip can keep
        #: it visible; the bar owns that state, not the strip.
        self.active_key: Optional[Callable[[], str]] = None
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.Bind(wx.EVT_SIZE, self._on_size)
        self._apply_theme(self.palette())

    # -- construction --------------------------------------------------------
    def adopt(
        self,
        leading: wx.Window,
        tabs: List["_TabButton"],
        search: wx.Window,
        chevron: wx.Window,
        *,
        search_stretch: int = 0,
    ) -> None:
        """Take the controls the bar built and create the overflow button.

        ``search_stretch`` is how much wider than its floor the search field
        would like to be.  Only the field inside the search bar is elastic --
        the regex checkbox and the builder button are measured from their own
        text and are never squeezed, because squeezing them is what turned
        "Regex" into "Reg".
        """
        self.leading = leading
        self.tabs = list(tabs)
        self.search = search
        self.chevron = chevron
        self.search_stretch = max(0, int(search_stretch))
        self.overflow = _TabButton(
            self,
            "More",
            on_click=self.open_overflow,
            emphasis="quiet",
            name="More ribbon tabs",
            hint="Show the ribbon tabs that do not fit at this width",
        )
        self.overflow.Hide()
        self.InvalidateBestSize()

    # -- geometry ------------------------------------------------------------
    @staticmethod
    def _wanted(window: Optional[wx.Window]) -> wx.Size:
        return window.GetEffectiveMinSize() if window is not None else wx.Size(0, 0)

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        """Return the height the tallest control needs, and the narrowest the
        strip may become before the search itself would start to clip.

        The width is a floor rather than a wish: it is the backstage button,
        the overflow control, the search at the smallest it is allowed to be,
        and the chevron.  Everything above that floor is tabs.
        """
        heights = [
            self._wanted(window).height
            for window in (self.leading, self.search, self.chevron, self.overflow)
        ]
        heights.extend(self._wanted(tab).height for tab in self.tabs)
        height = max([*heights, tokens.control_height()]) + tokens.scaled(
            self.VERTICAL_PAD * 2
        )
        width = (
            self._wanted(self.leading).width
            + tokens.scaled(self.LEAD_GAP)
            + self._wanted(self.overflow).width
            + tokens.scaled(self.TAB_GAP)
            + self._search_floor()
            + tokens.scaled(self.TRAIL_GAP)
            + self._wanted(self.chevron).width
            + tokens.scaled(self.EDGE)
        )
        return wx.Size(width, height)

    def _search_floor(self) -> int:
        """Return the narrowest the whole search bar may be drawn."""
        if self.search is None:
            return 0
        return self._wanted(self.search).width

    def _search_preferred(self) -> int:
        """Return the width the search bar would take if the strip had room."""
        return self._search_floor() + self.search_stretch

    def _on_size(self, event: wx.SizeEvent) -> None:
        self.relayout()
        event.Skip()

    def relayout(self) -> None:
        """Place every control, moving the tabs that do not fit into overflow.

        Right-hand controls are placed first and tabs take the remainder, so a
        narrow window loses tabs to a control that lists them rather than
        losing the search off the edge of the window.
        """
        if self.search is None or self.chevron is None or self.leading is None:
            return
        width, height = self.GetClientSize()
        if width <= 0 or height <= 0:
            return
        edge = tokens.scaled(self.EDGE)
        trail_gap = tokens.scaled(self.TRAIL_GAP)
        tab_gap = tokens.scaled(self.TAB_GAP)
        lead_gap = tokens.scaled(self.LEAD_GAP)
        pad = tokens.scaled(self.VERTICAL_PAD)

        chevron_size = self._wanted(self.chevron)
        search_size = self._wanted(self.search)
        lead_size = self._wanted(self.leading)

        # The chevron and the search keep the right-hand end, in that order.
        chevron_x = max(0, width - edge - chevron_size.width)
        self.chevron.SetSize(
            chevron_x,
            max(pad, (height - chevron_size.height) // 2),
            chevron_size.width,
            chevron_size.height,
        )

        # Tabs get what is left after the backstage button and the search.
        # The search shrinks towards its floor before a single tab is dropped,
        # because a tab that overflows is still reachable and a clipped search
        # field is not.
        floor = self._search_floor()
        room_for_search = chevron_x - trail_gap - (lead_size.width + lead_gap)
        search_width = max(0, min(self._search_preferred(), room_for_search))
        if search_width < floor:
            search_width = max(0, min(floor, max(0, chevron_x - trail_gap)))
        search_x = max(0, chevron_x - trail_gap - search_width)
        self.search.SetSize(
            search_x,
            max(pad, (height - search_size.height) // 2),
            search_width,
            search_size.height,
        )

        self.leading.SetSize(
            0,
            max(0, height - pad - lead_size.height),
            lead_size.width,
            lead_size.height,
        )
        cursor = lead_size.width + lead_gap
        limit = search_x - trail_gap

        active = ""
        if self.active_key is not None:
            active = str(widgets.invoke(self.active_key) or "")
        active_tab = next(
            (tab for tab in self.tabs if tab.tab_key and tab.tab_key == active), None
        )

        visible, overflowed = self._split(cursor, limit, tab_gap, active_tab)
        self._overflowed = overflowed
        for tab in overflowed:
            tab.Hide()
        x = cursor
        for tab in visible:
            size = self._wanted(tab)
            tab.Show()
            tab.SetSize(x, max(0, height - pad - size.height), size.width, size.height)
            x += size.width + tab_gap
        if self.overflow is not None:
            if overflowed:
                self.overflow.SetLabel(f"{len(overflowed)} more")
                # ``SetLabel`` renames the control after itself, which would
                # leave a screen reader announcing "12 more" with nothing to
                # say what twelve more of.
                self.overflow.SetName(
                    f"{len(overflowed)} more ribbon tabs: "
                    + ", ".join(tab.GetLabel().replace("\n", " ") for tab in overflowed)
                )
                overflow_size = self._wanted(self.overflow)
                self.overflow.Show()
                self.overflow.SetSize(
                    min(x, max(cursor, limit - overflow_size.width)),
                    max(0, height - pad - overflow_size.height),
                    overflow_size.width,
                    overflow_size.height,
                )
            else:
                self.overflow.Hide()
        self.Refresh()

    def _split(
        self,
        start: int,
        limit: int,
        gap: int,
        active: Optional["_TabButton"],
    ) -> Tuple[List["_TabButton"], List["_TabButton"]]:
        """Return the tabs that fit between ``start`` and ``limit``, and the rest.

        The tab currently showing is kept on the strip whatever its position,
        because a strip that hides the tab you are looking at reads as a bug
        rather than as an overflow.  Room for the overflow control is reserved
        as soon as a single tab has to move into it.
        """
        widths = {tab: self._wanted(tab).width for tab in self.tabs}
        total = sum(width + gap for width in widths.values())
        if start + total - gap <= limit:
            return list(self.tabs), []

        overflow_width = self._wanted(self.overflow).width + gap
        room = limit - start - overflow_width

        def prefix(reserved: int) -> Tuple[List[_TabButton], List[_TabButton]]:
            """Return the longest run of tabs fitting in ``room - reserved``."""
            visible: List[_TabButton] = []
            overflowed: List[_TabButton] = []
            used = 0
            for tab in self.tabs:
                if tab is active and reserved:
                    continue
                claim = widths[tab] + gap
                if not overflowed and used + claim <= room - reserved:
                    visible.append(tab)
                    used += claim
                else:
                    overflowed.append(tab)
            return visible, overflowed

        # The natural order first.  Moving the active tab to the end of the run
        # is only worth doing when it would otherwise be hidden: a strip that
        # shuffles the tab you are looking at for no reason is its own kind of
        # confusing.
        visible, overflowed = prefix(0)
        if active is None or active in visible:
            return visible, overflowed
        visible, overflowed = prefix(widths[active] + gap)
        visible.append(active)
        return visible, overflowed

    # -- overflow ------------------------------------------------------------
    def open_overflow(self) -> None:
        """Show the tabs that did not fit, as a searchable anchored list."""
        if not self._overflowed or self.overflow is None:
            return
        self.close_overflow()
        active = ""
        if self.active_key is not None:
            active = str(widgets.invoke(self.active_key) or "")
        popup = _TabOverflowPopup(
            self,
            self.overflow,
            self._overflowed,
            active,
            on_choose=self._chose_overflow,
        )
        self._popup = popup
        popup.on_dismiss = self._overflow_dismissed
        popup.popup()
        popup.search.SetFocus()

    def _overflow_dismissed(self) -> None:
        self._popup = None

    def close_overflow(self) -> None:
        """Dismiss the overflow list if one is open."""
        popup, self._popup = self._popup, None
        if popup is not None:
            try:
                popup.Dismiss()
                popup.Destroy()
            except RuntimeError:  # pragma: no cover - the popup has gone
                pass

    def _chose_overflow(self, button: "_TabButton") -> None:
        widgets.invoke(self.on_overflow_choice, button)

    def overflowed_labels(self) -> List[str]:
        """Return the labels currently living in the overflow control."""
        return [tab.GetLabel() for tab in self._overflowed]

    def _apply_theme(self, palette: tokens.StudioPalette) -> None:
        self.SetBackgroundColour(palette.surface_container)

    def _backdrop(self) -> wx.Colour:
        return self.palette().surface_container

    # The strip's whole appearance is that container colour; the tab buttons,
    # the search, and the chevron on top of it are windows of their own.


class _RibbonPanel(wx.ScrolledWindow, widgets._Themed):
    """The scrolling command panel: a vertical gradient with a bottom edge.

    Horizontal scrolling is deliberate.  The alternative -- letting the last
    group fall off the right-hand edge -- removes commands from the interface
    with nothing on screen to say they exist.
    """

    def __init__(self, parent: wx.Window) -> None:
        super().__init__(parent, style=wx.HSCROLL | wx.TAB_TRAVERSAL)
        self._install("Ribbon commands", listen=False)
        self.SetScrollRate(tokens.scaled(10), 0)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self._apply_theme(self.palette())

    def _apply_theme(self, palette: tokens.StudioPalette) -> None:
        self.SetBackgroundColour(palette.surface_container)

    def _backdrop(self) -> wx.Colour:
        return self.palette().surface

    def render_to(self, dc: wx.DC, rect: wx.Rect) -> None:
        """Draw the panel's vertical gradient and the edge under it."""
        palette = self.palette()
        with self._painting(dc, rect) as rect:
            width, height = rect.width, rect.height
            if width <= 0 or height <= 0:
                return
            dc.GradientFillLinear(
                wx.Rect(0, 0, width, height),
                palette.surface,
                palette.surface_container,
                wx.SOUTH,
            )
            # The design's elevation-1 shadow falls below the panel, where
            # nothing can be painted from inside it, so the edge is carried by
            # a hairline border with one softer band above it.
            dc.SetPen(
                wx.Pen(tokens.blend(palette.outline_variant, palette.surface, 0.6))
            )
            dc.DrawLine(0, height - 2, width, height - 2)
            dc.SetPen(wx.Pen(palette.outline_variant))
            dc.DrawLine(0, height - 1, width, height - 1)


class _GroupDivider(wx.Control, widgets._Themed):
    """The hairline between two ribbon groups."""

    WIDTH = 1
    INSET = 6

    def __init__(self, parent: wx.Window) -> None:
        super().__init__(parent, style=wx.BORDER_NONE)
        self._install("", listen=False)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.SetInitialSize(wx.Size(tokens.scaled(self.WIDTH), -1))

    def AcceptsFocus(self) -> bool:  # noqa: N802 - wx API spelling
        return False

    def AcceptsFocusFromKeyboard(self) -> bool:  # noqa: N802 - wx API spelling
        return False

    def _backdrop(self) -> wx.Colour:
        return self.palette().surface

    def render_to(self, dc: wx.DC, rect: wx.Rect) -> None:
        """Continue the ribbon gradient, then draw the hairline over it."""
        palette = self.palette()
        with self._painting(dc, rect) as rect:
            width, height = rect.width, rect.height
            _fill_ribbon_gradient(self, dc, palette, wx.Size(width, height))
            inset = tokens.scaled(self.INSET)
            dc.SetPen(wx.Pen(palette.outline_variant))
            dc.DrawLine(0, inset, 0, max(inset, height - inset))
            if width > 1:
                dc.DrawLine(width - 1, inset, width - 1, max(inset, height - inset))


class _GroupPanel(wx.Panel, widgets._Themed):
    """One ribbon group: its controls, its title, and its dialog launcher."""

    TITLE_GAP = 8
    SIDE_PADDING = 12
    FIELD_WIDTH = 132
    SELECT_WIDTH = 200
    LAUNCHER_SIZE = 24

    def __init__(
        self, parent: wx.Window, group: RibbonGroup, owner: "RibbonBar"
    ) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self.group = group
        self.owner = owner
        self._install(f"{group.title} ribbon group", listen=False)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self._apply_theme(self.palette())

        self.tiles: List[_RibbonTile] = []
        self.controls = wx.BoxSizer(wx.HORIZONTAL)
        for definition in group.buttons:
            tile = _RibbonTile(
                self,
                definition,
                on_click=lambda item=definition: owner.run_button(item),
            )
            self.tiles.append(tile)
            self.controls.Add(
                tile, 0, wx.ALIGN_TOP | wx.RIGHT, tokens.scaled(tokens.SPACE_XS + 2)
            )

        self.fields: Dict[str, widgets.OutlinedField] = {}
        if group.fields:
            grid = wx.FlexGridSizer(2, tokens.scaled(4), tokens.scaled(8))
            for definition in group.fields:
                field = widgets.OutlinedField(
                    self,
                    definition.label,
                    owner.field_value(group.title, definition.label),
                    mono=True,
                    on_change=lambda text, label=definition.label: owner.set_field(
                        group.title, label, text
                    ),
                    # The keystroke callback above only remembers; this one is
                    # what raises the field's command, once the value is
                    # finished.  Given unconditionally, so every field grid in
                    # this ribbon behaves the same way and Enter reaches the box
                    # rather than the surrounding window.  A definition naming
                    # no command is refused by ``ribbon_defs.validate()``, so
                    # this raising nothing is a guard rather than a route.
                    on_commit=lambda text, item=definition: owner.commit_field(
                        group.title, item, text
                    ),
                )
                # The design's width is a floor, not a cap.  A field whose
                # floating label is longer than 132 pixels -- which "Offset Z"
                # is in bilingual mode -- has that label painted into its own
                # outline, where it cannot scroll and can only be cut.
                best = field.GetBestSize()
                field.SetMinSize(
                    wx.Size(
                        max(tokens.scaled(self.FIELD_WIDTH), best.width), best.height
                    )
                )
                self.fields[definition.label] = field
                grid.Add(field, 0, wx.ALIGN_CENTER_VERTICAL)
            self.controls.Add(
                grid,
                0,
                wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
                tokens.scaled(tokens.SPACE_XS),
            )

        self.selects: Dict[str, widgets.SearchableChoice] = {}
        if group.selects:
            column = wx.BoxSizer(wx.VERTICAL)
            for definition in group.selects:
                choice = widgets.SearchableChoice(
                    self,
                    definition.label,
                    definition.option_labels,
                    owner.select_label(definition),
                    on_change=lambda label, item=definition: owner.set_select(
                        item, label
                    ),
                )
                # Same floor-not-cap rule: a dropdown narrower than the option
                # it is showing elides the current choice, and the current
                # choice is the one thing the closed control exists to say.
                best = choice.GetBestSize()
                dropdown_width = max(tokens.scaled(self.SELECT_WIDTH), best.width)
                choice.SetMinSize(wx.Size(dropdown_width, best.height))
                self.selects[definition.label] = choice
                column.Add(choice, 0, wx.EXPAND | wx.BOTTOM, tokens.scaled(4))
            self.controls.Add(
                column,
                0,
                wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
                tokens.scaled(tokens.SPACE_XS),
            )

        self.title = widgets.SectionLabel(self, group.title)
        self.launcher = widgets.StudioButton(
            self,
            "◢",
            variant="icon",
            hint=f"More {group.title} options",
            on_click=lambda: owner.open_surface(group.launcher),
            name=f"More {group.title} options",
            height=self.LAUNCHER_SIZE,
            min_width=self.LAUNCHER_SIZE,
        )
        footer = wx.BoxSizer(wx.HORIZONTAL)
        footer.AddStretchSpacer()
        footer.Add(self.title, 0, wx.ALIGN_CENTER_VERTICAL)
        footer.Add(
            self.launcher,
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            tokens.scaled(tokens.SPACE_XS),
        )
        footer.AddStretchSpacer()

        # A group's own line for what its controls have to say: why a value was
        # refused, or why its boxes are empty.  It sits under the controls
        # rather than in a notification because it is about the box directly
        # above it, and a toast in the corner leaves the reader to work out
        # which of six fields it means.  Hidden while it has nothing to say, so
        # a group costs no height until something goes wrong.
        self.feedback = widgets.StudioText(
            self,
            "",
            size_px=11,
            name=f"{group.title} field feedback",
        )
        self.feedback.Hide()

        body = wx.BoxSizer(wx.VERTICAL)
        body.Add(self.controls, 1, wx.EXPAND)
        body.Add(self.feedback, 0, wx.EXPAND | wx.TOP, tokens.scaled(2))
        body.Add(footer, 0, wx.EXPAND | wx.TOP, tokens.scaled(self.TITLE_GAP))
        root = wx.BoxSizer(wx.HORIZONTAL)
        root.Add(
            body, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, tokens.scaled(self.SIDE_PADDING)
        )
        self.SetSizer(root)

    # -- the group's own message ---------------------------------------------
    def feedback_text(self) -> str:
        """Return what the group's feedback line currently says."""
        return self.feedback.GetLabel()

    def set_feedback(self, message: str, *, severity: str = "error") -> None:
        """Show ``message`` under the controls, or clear it when empty.

        ``severity`` picks the ink only.  An error takes the palette's error
        red; anything else stays in the ordinary variant ink, because a line
        that merely says which box of three is showing is not a fault and must
        not be painted like one.
        """
        message = str(message or "")
        if message == self.feedback_text() and bool(message) == self.feedback.IsShown():
            return
        # Wrapped to the controls it is about rather than laid out on one line.
        # These sentences run to a hundred characters, and an unwrapped line
        # that long makes the group wider than its own field grid -- so a
        # refused value would shove every group to its right sideways and start
        # the ribbon scrolling, which is a strange thing for a typo to do.
        width = max(self.controls.GetMinSize().width, tokens.scaled(self.FIELD_WIDTH))
        self.feedback.Wrap(width)
        self.feedback.SetLabel(message)
        if severity == "error":
            self.feedback.SetForegroundColour(self.palette().error)
        else:
            # Handed back to the palette rather than pinned to a colour, so a
            # theme change repaints it like every other ordinary line.
            self.feedback.set_role("on_surface_variant")
        self.feedback.Show(bool(message))
        self.Layout()
        owner = getattr(self, "owner", None)
        relayout = getattr(owner, "refresh_layout", None)
        if callable(relayout):
            relayout()

    def apply_search(self, state: SearchState) -> int:
        """Show only the tiles matching ``state``; return how many survive."""
        matches = 0
        for tile in self.tiles:
            visible = state.matches(tile.definition.haystack)
            tile.Show(visible)
            matches += int(visible)
        self.Layout()
        return matches

    def _apply_theme(self, palette: tokens.StudioPalette) -> None:
        self.SetBackgroundColour(palette.surface_container)

    def _backdrop(self) -> wx.Colour:
        return self.palette().surface

    def render_to(self, dc: wx.DC, rect: wx.Rect) -> None:
        """Continue the ribbon gradient across this group's column."""
        palette = self.palette()
        with self._painting(dc, rect) as rect:
            _fill_ribbon_gradient(self, dc, palette, wx.Size(rect.width, rect.height))


class RibbonBar(wx.Panel, widgets._Themed):
    """The workspace's command ribbon.

    ``on_surface`` opens a dialog by key, ``on_command`` runs a shell command by
    key, and ``on_backstage`` returns to the project screen.  The bar holds no
    application state beyond which tab is showing, what its search field
    contains, and the values typed into its field grids and dropdowns --
    everything else belongs to the shell.

    The tab buttons are the design's 36px and sit on the strip's bottom edge,
    but the strip itself takes whatever height the command search needs: that
    field reports its own validation feedback, and squeezing the strip to 36px
    would clip the one line that says why a regular expression matched nothing.
    """

    #: The design's width for the command search field, and the narrowest that
    #: field may be drawn at before the strip stops taking room from it and
    #: starts moving tabs into the overflow control instead.  A field at the
    #: floor still shows a query being typed; a field at nothing shows a
    #: half-eaten word, which is what a box sizer produced here.
    SEARCH_WIDTH = 200
    SEARCH_MIN_FIELD = 110
    PANEL_TOP = 12
    PANEL_BOTTOM = 8
    CHEVRON_SIZE = 32

    def __init__(
        self,
        parent: wx.Window,
        *,
        on_surface: Optional[Callable[[str], None]] = None,
        on_command: Optional[Callable[[str], None]] = None,
        on_backstage: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self.on_surface = on_surface
        self.on_command = on_command
        self.on_backstage = on_backstage
        self.active_tab = ribbon_defs.TAB_KEYS[0]
        self.state = SearchState(label="This tab's commands")
        self._expanded = self._load_expanded()
        self._menu: Optional[context_menu.SearchableContextMenu] = None
        #: Values typed into a group's field grid, keyed by group title and
        #: field label so a value survives switching tabs and back.
        self.field_values: Dict[Tuple[str, str], str] = {}
        #: Values chosen in the ribbon's dropdowns, keyed by dropdown label.
        self.select_values: Dict[str, str] = {}
        for tab in RIBBON_TABS:
            for group in tab.groups:
                for entry in group.fields:
                    self.field_values.setdefault(
                        (group.title, entry.label), entry.value
                    )
                for select in group.selects:
                    self.select_values.setdefault(
                        select.label,
                        select.value or select.value_for(select.default_label),
                    )
        self._install("Command ribbon")
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)

        self.strip = _TabStrip(self)
        self.backstage_button = _TabButton(
            self.strip,
            "Project",
            on_click=lambda: widgets.invoke(self.on_backstage),
            emphasis="filled",
            name="Project · open the project screen",
            hint="Leave the workspace and open the project screen",
        )
        self.tab_buttons: Dict[str, _TabButton] = {}
        for tab in RIBBON_TABS:
            button = _TabButton(
                self.strip,
                tab.label,
                on_click=lambda key=tab.key: self.set_tab(key),
                on_navigate=lambda code, key=tab.key: self._navigate(key, code),
                name=f"{tab.label} ribbon tab",
                hint=f"Show the {tab.label} commands",
                tab_key=tab.key,
            )
            self.tab_buttons[tab.key] = button
        self.search = widgets.SearchBar(
            self.strip,
            "Search this tab's commands",
            self.state,
            on_change=self._on_search,
            compact=True,
        )
        # The design's width is what the field asks for, not a floor it is
        # nailed to: the strip shrinks it towards ``SEARCH_MIN_FIELD`` when the
        # window is narrow, and never past it.
        self.search.field.SetMinSize(
            wx.Size(
                tokens.scaled(self.SEARCH_MIN_FIELD),
                self.search.field.GetBestSize().height,
            )
        )
        self.chevron = widgets.StudioButton(
            self.strip,
            "⌃",
            variant="icon",
            hint="Collapse or expand the command ribbon",
            on_click=self.toggle_collapsed,
            name="Collapse the command ribbon",
            height=self.CHEVRON_SIZE,
            min_width=self.CHEVRON_SIZE,
        )
        self.strip.adopt(
            self.backstage_button,
            [self.tab_buttons[tab.key] for tab in RIBBON_TABS],
            self.search,
            self.chevron,
            search_stretch=tokens.scaled(self.SEARCH_WIDTH)
            - tokens.scaled(self.SEARCH_MIN_FIELD),
        )
        self.strip.active_key = lambda: self.active_tab
        self.strip.on_overflow_choice = self._chose_overflow_tab
        self.strip.SetMinSize(self.strip.DoGetBestSize())

        self.panel = _RibbonPanel(self)
        self.groups_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.panel_sizer = wx.BoxSizer(wx.VERTICAL)
        self.panel_sizer.Add(
            self.groups_sizer, 1, wx.EXPAND | wx.TOP, tokens.scaled(self.PANEL_TOP)
        )
        self.panel_sizer.Add((0, tokens.scaled(self.PANEL_BOTTOM)), 0)
        self.panel.SetSizer(self.panel_sizer)
        self.empty = widgets.StudioText(
            self.panel, "", size_px=12, name="Ribbon search results"
        )
        self.groups_sizer.Add(
            self.empty,
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            tokens.scaled(tokens.SPACE_MD),
        )
        self._groups: List[_GroupPanel] = []
        self._dividers: List[_GroupDivider] = []

        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(self.strip, 0, wx.EXPAND)
        root.Add(self.panel, 0, wx.EXPAND)
        self.SetSizer(root)

        for window in (self, self.strip, self.panel):
            window.Bind(wx.EVT_CONTEXT_MENU, self._on_context_menu)
        self.panel.Show(self._expanded)
        self.chevron.SetLabel("⌃" if self._expanded else "⌄")
        self.chevron.SetName(
            "Collapse the command ribbon"
            if self._expanded
            else "Expand the command ribbon"
        )
        self._apply_theme(self.palette())
        self._build_tab()

    # -- persistence ---------------------------------------------------------
    @staticmethod
    def _load_expanded() -> bool:
        """Read the remembered collapsed state, defaulting to expanded."""
        try:
            return bool(widgets.section_states().get(RIBBON_STATE_KEY, True))
        except Exception:  # pragma: no cover - unreadable profile
            log.debug("Could not read the remembered ribbon state", exc_info=True)
            return True

    # -- tabs ----------------------------------------------------------------
    @property
    def expanded(self) -> bool:
        """Return whether the command panel is showing."""
        return self._expanded

    def tab(self) -> RibbonTab:
        """Return the tab currently on show."""
        found = ribbon_defs.tab(self.active_tab)
        return found if found is not None else RIBBON_TABS[0]

    def set_tab(self, key: str) -> None:
        """Show one tab's groups, expanding the ribbon if it was collapsed."""
        if ribbon_defs.tab(key) is None:
            log.warning("No ribbon tab named %r", key)
            return
        changed = str(key) != self.active_tab
        self.active_tab = str(key)
        if not self._expanded:
            self.toggle_collapsed()
        if changed or not self._groups:
            self._build_tab()
        else:
            self._refresh_tab_emphasis()

    def _navigate(self, from_key: str, code: int) -> None:
        """Move between tabs with the arrow, Home, and End keys."""
        keys = ribbon_defs.TAB_KEYS
        try:
            index = keys.index(from_key)
        except ValueError:  # pragma: no cover - the strip is built from keys
            return
        if code == wx.WXK_LEFT:
            index = (index - 1) % len(keys)
        elif code == wx.WXK_RIGHT:
            index = (index + 1) % len(keys)
        elif code == wx.WXK_HOME:
            index = 0
        elif code == wx.WXK_END:
            index = len(keys) - 1
        target = keys[index]
        self.set_tab(target)
        button = self.tab_buttons.get(target)
        if button is not None:
            button.SetFocus()

    def _refresh_tab_emphasis(self) -> None:
        for key, button in self.tab_buttons.items():
            button.set_emphasis("active" if key == self.active_tab else "quiet")
        # An active tab is drawn wider than a quiet one, and the tab that is
        # now active may have been in the overflow list a moment ago, so the
        # strip is re-fitted rather than left holding last tab's arithmetic.
        self.strip.relayout()

    def _chose_overflow_tab(self, button: _TabButton) -> None:
        """Open a tab somebody picked out of the strip's overflow list."""
        widgets.invoke(button.on_click)
        target = self.tab_buttons.get(button.tab_key)
        if target is not None and target.IsShown():
            target.SetFocus()

    # -- collapsing ----------------------------------------------------------
    def toggle_collapsed(self) -> None:
        """Hide or show the command panel and remember the choice."""
        self._expanded = not self._expanded
        self.panel.Show(self._expanded)
        self.chevron.SetLabel("⌃" if self._expanded else "⌄")
        self.chevron.SetName(
            "Collapse the command ribbon"
            if self._expanded
            else "Expand the command ribbon"
        )
        widgets.remember_section(RIBBON_STATE_KEY, self._expanded)
        self._relayout()

    def set_collapsed(self, collapsed: bool) -> None:
        """Set the collapsed state directly, for the shell's own command."""
        if bool(collapsed) != self._expanded:
            return
        self.toggle_collapsed()

    # -- content -------------------------------------------------------------
    def _clear_groups(self) -> None:
        for window in (*self._dividers, *self._groups):
            self.groups_sizer.Detach(window)
            window.Destroy()
        self._groups = []
        self._dividers = []

    def _build_tab(self) -> None:
        """Rebuild the panel for the active tab and re-apply the query."""
        self._clear_groups()
        position = 0
        for index, group in enumerate(self.tab().groups):
            if index:
                divider = _GroupDivider(self.panel)
                self.groups_sizer.Insert(position, divider, 0, wx.EXPAND)
                self._dividers.append(divider)
                position += 1
            panel = _GroupPanel(self.panel, group, self)
            self.groups_sizer.Insert(position, panel, 0, wx.EXPAND)
            self._groups.append(panel)
            position += 1
        self._refresh_tab_emphasis()
        self._apply_search()

    def _on_search(self, _state: SearchState) -> None:
        self._apply_search()

    def _apply_search(self) -> None:
        """Filter the active tab's tiles and report an honest empty state."""
        active = self.state.is_active()
        matches = 0
        for index, panel in enumerate(self._groups):
            found = panel.apply_search(self.state)
            matches += found
            # A group whose only content is a field grid or a dropdown has no
            # commands for a command search to match, so it steps aside while a
            # query is running rather than pretending to be a result.
            visible = bool(found) or not active
            panel.Show(visible)
            if index:
                self._dividers[index - 1].Show(visible)
        if active and matches == 0:
            self.empty.SetLabel(
                f"No {self.tab().label} commands match “{self.state.query}”."
                if self.state.is_valid()
                else self.state.feedback()
            )
            self.empty.Show()
        else:
            self.empty.SetLabel("")
            self.empty.Hide()
        self._relayout()

    def _relayout(self) -> None:
        """Resize the scrolling panel to its content and lay the bar out."""
        if self._expanded:
            self.panel_sizer.Layout()
            content = self.panel_sizer.GetMinSize()
            # The horizontal scrollbar is always allowed for, so a ribbon that
            # begins to overflow never does it by eating the group titles.
            bar = wx.SystemSettings.GetMetric(wx.SYS_HSCROLL_Y)
            if bar <= 0:
                bar = tokens.scaled(16)
            self.panel.SetVirtualSize(wx.Size(content.width, content.height))
            self.panel.SetMinSize(wx.Size(-1, content.height + bar))
        else:
            self.panel.SetMinSize(wx.Size(-1, 0))
        self.strip.InvalidateBestSize()
        self.strip.SetMinSize(self.strip.DoGetBestSize())
        self.Layout()
        # The strip lays itself out, so it is re-fitted after the bar has told
        # it how wide it now is rather than before.
        self.strip.relayout()
        parent = self.GetParent()
        if parent is not None:
            parent.Layout()

    # -- values --------------------------------------------------------------
    def set_field(self, group_title: str, label: str, text: str) -> None:
        """Record a value typed into one of the ribbon's field grids.

        Called on every keystroke, so it only remembers.  Acting on a value is
        :meth:`commit_field`'s job, once the user has finished typing it.
        """
        self.field_values[(str(group_title), str(label))] = str(text)

    def commit_field(
        self, group_title: str, definition: RibbonField, text: str
    ) -> None:
        """Record a finished field value and raise its command, if it has one.

        The dropdown beside it works the same way -- see :meth:`set_select` --
        and for the same reason: a control that stores a value nobody reads is a
        control that operates and decides nothing.
        """
        self.set_field(group_title, definition.label, text)
        if definition.command:
            widgets.invoke(self.on_command, definition.command)

    def field_value(self, group_title: str, label: str) -> str:
        """Return the current value of one ribbon field."""
        return self.field_values.get((str(group_title), str(label)), "")

    def group_panel(self, title: str) -> Optional["_GroupPanel"]:
        """Return the built group panel titled ``title``, or ``None``.

        Only the active tab's groups exist, so this answers ``None`` for a group
        on a tab nobody is looking at -- which is a real state a caller has to
        handle rather than an error.
        """
        wanted = str(title)
        for panel in self._groups:
            if panel.group.title == wanted:
                return panel
        return None

    def refresh_layout(self) -> None:
        """Re-fit the bar after a group's own content changed height."""
        self._relayout()

    def select_label(self, select: RibbonSelect) -> str:
        """Return the visible label a dropdown should show right now."""
        value = self.select_values.get(select.label, select.value)
        return select.label_for(value) if value else select.default_label

    def set_select(self, select: RibbonSelect, label: str) -> None:
        """Record a dropdown choice and raise its command, if it has one."""
        value = select.value_for(label)
        if not value:
            return
        self.select_values[select.label] = value
        if select.command:
            widgets.invoke(self.on_command, select.command)

    def selected_value(self, select_label: str) -> str:
        """Return the stored value behind one dropdown, for the shell to read."""
        return self.select_values.get(str(select_label), "")

    # -- actions -------------------------------------------------------------
    def run_button(self, definition: RibbonButton) -> None:
        """Open a tile's surface, or run its command."""
        if definition.surface:
            self.open_surface(definition.surface)
        elif definition.command:
            widgets.invoke(self.on_command, definition.command)

    def open_surface(self, key: str) -> None:
        """Open one surface through the shell."""
        if key:
            widgets.invoke(self.on_surface, key)

    # -- context menu --------------------------------------------------------
    def _on_context_menu(self, event: wx.ContextMenuEvent) -> None:
        position = event.GetPosition()
        if position == wx.DefaultPosition:
            # A keyboard-raised menu has no pointer position; anchor it under
            # the ribbon rather than dropping it in a display corner.
            position = self.ClientToScreen(wx.Point(0, self.GetSize().height))
        target = event.GetEventObject()
        self._menu = context_menu.open_context_menu(
            self,
            "ribbon",
            position,
            on_surface=self.open_surface,
            on_command=lambda key: widgets.invoke(self.on_command, key),
            target=target if isinstance(target, wx.Window) else self,
        )

    # -- theme ---------------------------------------------------------------
    def _apply_theme(self, palette: tokens.StudioPalette) -> None:
        self.SetBackgroundColour(palette.surface_container)
        # The search-result note is owner-drawn and reads its own role colour
        # per paint, so the repaint that follows a theme change is enough.

    def _backdrop(self) -> wx.Colour:
        return self.palette().surface_container

    # The bar is the strip plus the panel, both of which are their own windows,
    # so its own appearance is the container colour behind them.

    def refresh_theme(self) -> None:
        """Re-read the tokens for the strip, the panel, and every group."""
        try:
            if self.IsBeingDeleted():
                return
        except RuntimeError:  # pragma: no cover - the window has gone
            return
        palette = tokens.palette()
        self._apply_theme(palette)
        for child in (self.strip, self.panel):
            refresh = getattr(child, "refresh_theme", None)
            if callable(refresh):
                refresh()
        self._relayout()
        self.Refresh()
