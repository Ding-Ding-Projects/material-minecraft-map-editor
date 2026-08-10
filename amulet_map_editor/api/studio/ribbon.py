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
    window: wx.Window, dc: wx.DC, palette: tokens.StudioPalette
) -> None:
    """Continue the ribbon panel's gradient across one of its children.

    A child window cannot see through to its parent's paint, so each one draws
    the same top-to-bottom ramp offset by its own position.  Painting the ramp
    per child rather than a flat colour is what keeps a group column from
    reading as a lighter rectangle sitting on the ribbon.
    """
    width, height = window.GetClientSize()
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
        dc = wx.ClientDC(self)
        dc.SetFont(tokens.font(self, widgets.point_size(13), _MEDIUM))
        padding = tokens.scaled(18 if self.emphasis == "filled" else 16)
        lines = [line for line in self.GetLabel().split("\n") if line] or [" "]
        width = max(dc.GetTextExtent(line)[0] for line in lines) + padding * 2
        height = tokens.scaled(self.HEIGHT)
        if len(lines) > 1:
            height = max(height, dc.GetCharHeight() * len(lines) + tokens.scaled(10))
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

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = self.palette()
        parent = self.GetParent()
        backdrop = parent.GetBackgroundColour() if parent else palette.surface_container
        if not backdrop.IsOk():
            backdrop = palette.surface_container
        dc, gcdc = widgets.paint_context(self, backdrop)
        width, height = self.GetClientSize()
        radius = tokens.scaled(self.RADIUS)
        fill, ink = self._tab_colours(palette)
        if fill is not None:
            tokens.draw_round_rect(
                gcdc, wx.Rect(0, 0, width, height + radius), radius, fill
            )
        weight = (
            _MEDIUM if self.emphasis in ("filled", "active") else wx.FONTWEIGHT_NORMAL
        )
        gcdc.SetFont(tokens.font(self, widgets.point_size(13), weight))
        gcdc.SetTextForeground(ink)
        lines = [line for line in self.GetLabel().split("\n") if line] or [" "]
        available = max(0, width - tokens.scaled(12))
        rendered = [widgets.elide(gcdc, line, available) for line in lines]
        line_height = gcdc.GetCharHeight()
        y = (height - line_height * len(rendered)) // 2
        for line in rendered:
            gcdc.DrawText(line, (width - gcdc.GetTextExtent(line)[0]) // 2, y)
            y += line_height
        if self.HasFocus():
            widgets.draw_focus_ring(
                gcdc, wx.Rect(0, 0, width, height), radius, palette.primary
            )
        del gcdc

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


class _TabStrip(wx.Panel, widgets._Themed):
    """The container behind the tab buttons, painted in the container role."""

    def __init__(self, parent: wx.Window) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self._install("Ribbon tabs", listen=False)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self._apply_theme(self.palette())

    def _apply_theme(self, palette: tokens.StudioPalette) -> None:
        self.SetBackgroundColour(palette.surface_container)

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = self.palette()
        dc, gcdc = widgets.paint_context(self, palette.surface_container)
        del gcdc, dc


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

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = self.palette()
        dc, gcdc = widgets.paint_context(self, palette.surface)
        width, height = self.GetClientSize()
        if width <= 0 or height <= 0:
            del gcdc, dc
            return
        dc.GradientFillLinear(
            wx.Rect(0, 0, width, height),
            palette.surface,
            palette.surface_container,
            wx.SOUTH,
        )
        # The design's elevation-1 shadow falls below the panel, where nothing
        # can be painted from inside it, so the edge is carried by a hairline
        # border with one softer band above it.
        gcdc.SetPen(wx.Pen(tokens.blend(palette.outline_variant, palette.surface, 0.6)))
        gcdc.DrawLine(0, height - 2, width, height - 2)
        gcdc.SetPen(wx.Pen(palette.outline_variant))
        gcdc.DrawLine(0, height - 1, width, height - 1)
        del gcdc


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

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = self.palette()
        dc, gcdc = widgets.paint_context(self, palette.surface)
        _fill_ribbon_gradient(self, dc, palette)
        width, height = self.GetClientSize()
        inset = tokens.scaled(self.INSET)
        gcdc.SetPen(wx.Pen(palette.outline_variant))
        gcdc.DrawLine(0, inset, 0, max(inset, height - inset))
        if width > 1:
            gcdc.DrawLine(width - 1, inset, width - 1, max(inset, height - inset))
        del gcdc


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
                )
                field.SetMinSize(
                    wx.Size(tokens.scaled(self.FIELD_WIDTH), field.GetBestSize().height)
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
                choice.SetMinSize(
                    wx.Size(
                        tokens.scaled(self.SELECT_WIDTH), choice.GetBestSize().height
                    )
                )
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

        body = wx.BoxSizer(wx.VERTICAL)
        body.Add(self.controls, 1, wx.EXPAND)
        body.Add(footer, 0, wx.EXPAND | wx.TOP, tokens.scaled(self.TITLE_GAP))
        root = wx.BoxSizer(wx.HORIZONTAL)
        root.Add(
            body, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, tokens.scaled(self.SIDE_PADDING)
        )
        self.SetSizer(root)

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

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = self.palette()
        dc, gcdc = widgets.paint_context(self, palette.surface)
        _fill_ribbon_gradient(self, dc, palette)
        del gcdc, dc


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

    SEARCH_WIDTH = 200
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
        strip_sizer = wx.BoxSizer(wx.HORIZONTAL)
        strip_sizer.Add(
            self.backstage_button,
            0,
            wx.ALIGN_BOTTOM | wx.RIGHT,
            tokens.scaled(tokens.SPACE_XS),
        )
        for tab in RIBBON_TABS:
            button = _TabButton(
                self.strip,
                tab.label,
                on_click=lambda key=tab.key: self.set_tab(key),
                on_navigate=lambda code, key=tab.key: self._navigate(key, code),
                name=f"{tab.label} ribbon tab",
                hint=f"Show the {tab.label} commands",
            )
            self.tab_buttons[tab.key] = button
            strip_sizer.Add(button, 0, wx.ALIGN_BOTTOM | wx.RIGHT, tokens.scaled(2))
        strip_sizer.AddStretchSpacer()
        self.search = widgets.SearchBar(
            self.strip,
            "Search this tab's commands",
            self.state,
            on_change=self._on_search,
            compact=True,
        )
        self.search.field.SetMinSize(
            wx.Size(
                tokens.scaled(self.SEARCH_WIDTH),
                self.search.field.GetBestSize().height,
            )
        )
        strip_sizer.Add(
            self.search,
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT | wx.TOP | wx.BOTTOM,
            tokens.scaled(tokens.SPACE_XS),
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
        strip_sizer.Add(
            self.chevron,
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            tokens.scaled(tokens.SPACE_SM),
        )
        self.strip.SetSizer(strip_sizer)

        self.panel = _RibbonPanel(self)
        self.groups_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.panel_sizer = wx.BoxSizer(wx.VERTICAL)
        self.panel_sizer.Add(
            self.groups_sizer, 1, wx.EXPAND | wx.TOP, tokens.scaled(self.PANEL_TOP)
        )
        self.panel_sizer.Add((0, tokens.scaled(self.PANEL_BOTTOM)), 0)
        self.panel.SetSizer(self.panel_sizer)
        self.empty = wx.StaticText(self.panel, label="")
        self.empty.SetName("Ribbon search results")
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
        self.Layout()
        parent = self.GetParent()
        if parent is not None:
            parent.Layout()

    # -- values --------------------------------------------------------------
    def set_field(self, group_title: str, label: str, text: str) -> None:
        """Record a value typed into one of the ribbon's field grids."""
        self.field_values[(str(group_title), str(label))] = str(text)

    def field_value(self, group_title: str, label: str) -> str:
        """Return the current value of one ribbon field."""
        return self.field_values.get((str(group_title), str(label)), "")

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
        self.empty.SetForegroundColour(palette.on_surface_variant)

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = self.palette()
        dc, gcdc = widgets.paint_context(self, palette.surface_container)
        del gcdc, dc

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
