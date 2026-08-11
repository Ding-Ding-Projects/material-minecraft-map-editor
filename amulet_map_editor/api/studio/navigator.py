"""The workspace navigator: dimensions and selection boxes, both searchable.

The navigator is the workspace's index.  It answers two questions -- which
dimension am I editing, and which of my selection boxes is active -- and every
row that answers one of them is a real control: selecting a dimension changes
the dimension the editor is rendering, selecting a box makes it the active one,
and adding a box adds it to the renderer's own selection.

Both lists are read from the world the user has open, through
:mod:`amulet_map_editor.api.studio.context`, and re-read whenever that world,
its dimension, or its selection changes.  With no world open the panel says so
in both lists rather than showing the last world's dimensions, because a list
that outlives the thing it described is worse than an empty one.

The dimension rows expand rather than merely decorating themselves with a
chevron.  A chevron that never opens anything is a control that lies about what
it does, so opening a dimension shows the two facts the world actually reports
about it: its build height range and how many chunks it stores.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence, Set, Tuple

import wx

from amulet_map_editor.api.studio import context, tokens
from amulet_map_editor.api.studio.copy import studio_label, studio_text
from amulet_map_editor.api.studio.search import SearchState
from amulet_map_editor.api.studio.status_bar import (
    clear_container,
    open_studio_menu,
    single_line,
    studio_canvas,
)
from amulet_map_editor.api.studio.widgets import (
    SearchBar,
    SectionLabel,
    StudioButton,
    StudioText,
    draw_dashed_round_rect,
    draw_focus_ring,
    elide,
    invoke,
    paint_context,
    point_size,
)

log = logging.getLogger(__name__)

#: The design's navigator width, in design pixels.
PANEL_WIDTH = 224

#: Narrower than this and the count pill starts eating the dimension name.
MIN_PANEL_WIDTH = 176

_MEDIUM = getattr(wx, "FONTWEIGHT_MEDIUM", wx.FONTWEIGHT_NORMAL)


#: What the dimension tree says with no world open.
NO_WORLD_DIMENSIONS = studio_text(
    "No world is open, so there are no dimensions to list.",
    "而家未開世界，所以冇維度可以列出嚟。",
)

#: What the dimension tree says for a world that reports none of its own.
NO_DIMENSIONS = studio_text(
    "This world reports no dimensions.",
    "呢個世界冇報返任何維度出嚟。",
)

#: What the selection list says with no world open.
NO_WORLD_BOXES = studio_text(
    "No world is open, so there is nothing to select in.",
    "而家未開世界，所以冇嘢可以揀。",
)

#: What it says for an open world with nothing selected in it yet.
NO_BOXES = studio_text(
    "Nothing is selected. Draw a box in the viewport, or add one below.",
    "而家咩都未揀。喺畫面度畫個範圍，或者喺下面加一個。",
)

#: The glyph each dimension is drawn with, chosen by what the dimension's own
#: name ends in.  A dimension this build has never heard of still gets a glyph
#: rather than a blank column.
_DIMENSION_GLYPHS: Tuple[Tuple[str, str], ...] = (
    ("overworld", "◎"),
    ("the_nether", "◆"),
    ("nether", "◆"),
    ("the_end", "◇"),
    ("end", "◇"),
)
_OTHER_DIMENSION_GLYPH = "◈"


def dimension_glyph(name: str) -> str:
    """Return the glyph a dimension row is drawn with."""
    text = str(name).lower()
    for suffix, glyph in _DIMENSION_GLYPHS:
        if text.endswith(suffix):
            return glyph
    return _OTHER_DIMENSION_GLYPH


@dataclass(frozen=True)
class DimensionEntry:
    """One dimension the open world reports, with the facts the row shows."""

    key: str
    label: str
    glyph: str
    chunks: int
    height_range: str
    #: ``False`` when the chunk count could not be read at all, which is a
    #: different statement from a dimension that genuinely holds no chunks.
    counted: bool = True
    #: ``True`` when the count stopped early, so ``chunks`` is a floor.
    truncated: bool = False

    def count_text(self) -> str:
        """Return the count as the pill shows it, or an honest absence."""
        if not self.counted:
            return "—"
        return f"{self.chunks:,}" + ("+" if self.truncated else "")

    def detail(self) -> str:
        """Return the line shown when the dimension row is expanded."""
        if not self.counted:
            return f"{self.height_range} · chunk count unavailable"
        plural = "chunk" if self.chunks == 1 else "chunks"
        more = " or more" if self.truncated else ""
        return f"{self.height_range} · {self.chunks:,} {plural} stored{more}"


def dimension_entries(
    ctx: Optional[context.WorldContext] = None,
) -> Tuple[DimensionEntry, ...]:
    """Return one row per dimension the open world reports.

    A dimension whose build range or chunk list could not be read still
    appears, carrying the parts that did read, so one unreadable dimension
    never empties the whole tree.
    """
    if ctx is None:
        ctx = context.current()
    entries: List[DimensionEntry] = []
    for info in ctx.dimension_info:
        entries.append(
            DimensionEntry(
                key=info.name,
                label=info.name,
                glyph=dimension_glyph(info.name),
                chunks=int(info.chunk_count),
                height_range=(
                    f"y {info.min_y} to {info.max_y}"
                    if info.has_range
                    else "build range not reported"
                ),
                counted=bool(info.counted),
                truncated=bool(info.truncated),
            )
        )
    return tuple(entries)


@dataclass(frozen=True)
class SelectionBox:
    """One selection box: where it starts and how large it is, in blocks.

    The box carries the corner and the size rather than two corners because
    that is what the editor's own selection tool edits, and every derived
    string -- the maximum corner, the size caption, the status bar delta -- is
    computed here so two surfaces can never disagree about the same box.
    """

    label: str
    minimum: Tuple[int, int, int]
    size: Tuple[int, int, int]

    @property
    def maximum(self) -> Tuple[int, int, int]:
        """Return the inclusive far corner of the box."""
        return tuple(
            start + max(1, extent) - 1 for start, extent in zip(self.minimum, self.size)
        )

    @property
    def volume(self) -> int:
        """Return how many blocks the box contains."""
        width, height, depth = (max(0, int(extent)) for extent in self.size)
        return width * height * depth

    def size_text(self) -> str:
        """Return the design's compact size caption, such as ``16x2x18``."""
        return "x".join(str(max(0, int(extent))) for extent in self.size)

    def corner_text(self, corner: Tuple[int, int, int]) -> str:
        """Return a corner formatted the way every coordinate in the shell is."""
        return ", ".join(str(int(value)) for value in corner)

    def delta_text(self) -> str:
        """Return the status bar's selection line for this box."""
        deltas = [max(0, int(extent) - 1) for extent in self.size]
        return f"dx={deltas[0]}, dy={deltas[1]}, dz={deltas[2]} · {self.size_text()}"


def selection_boxes(
    ctx: Optional[context.WorldContext] = None,
) -> Tuple[SelectionBox, ...]:
    """Return one card per box in the world's current selection.

    The boxes are numbered in the order the renderer holds them, which is the
    order the corners were drawn in, so the number beside a card matches the
    box a user would count to in the viewport.
    """
    if ctx is None:
        ctx = context.current()
    return tuple(
        SelectionBox(
            f"Box {index}",
            tuple(int(value) for value in box.min),
            tuple(int(value) for value in box.size),
        )
        for index, box in enumerate(ctx.selection_boxes, start=1)
    )


def push_selection(boxes: Sequence[SelectionBox]) -> bool:
    """Write ``boxes`` back to the renderer's own selection.

    The renderer is the owner of the selection, so it is written first and the
    world context is told afterwards.  With no renderer attached the context is
    still updated, which keeps the panes agreeing with each other, and the
    caller is told the renderer did not take it.
    """
    corners = tuple(
        (
            tuple(int(value) for value in box.minimum),
            tuple(
                int(start) + max(1, int(extent))
                for start, extent in zip(box.minimum, box.size)
            ),
        )
        for box in boxes
    )
    canvas = studio_canvas()
    applied = False
    if canvas is not None:
        try:
            canvas.selection.selection_corners = corners
            applied = True
        except Exception as err:  # noqa: BLE001 - a canvas being torn down
            log.debug("The selection could not be given to the renderer: %s", err)
    context.set_selection(corners)
    return applied


#: The dimension tree and the selection list are read from the open world, so
#: the shipped lists are empty.  A panel constructed before a world is open
#: shows its honest empty states rather than a world nobody has.
DEFAULT_DIMENSIONS: Tuple[DimensionEntry, ...] = ()
DEFAULT_BOXES: Tuple[SelectionBox, ...] = ()


class _CountPill:
    """Geometry helper for the small monospaced count at a row's right edge."""

    PADDING = 7
    HEIGHT = 16

    @staticmethod
    def measure(dc: wx.DC, text: str) -> int:
        if not text:
            return 0
        return dc.GetTextExtent(text)[0] + tokens.scaled(_CountPill.PADDING) * 2

    @staticmethod
    def draw(
        dc: wx.DC,
        text: str,
        right: int,
        centre_y: int,
        ink: wx.Colour,
        fill: wx.Colour,
    ) -> int:
        width = _CountPill.measure(dc, text)
        if not width:
            return right
        height = tokens.scaled(_CountPill.HEIGHT)
        rect = wx.Rect(right - width, centre_y - height // 2, width, height)
        tokens.draw_round_rect(dc, rect, tokens.RADIUS_PILL, fill)
        dc.SetTextForeground(ink)
        text_width, text_height = dc.GetTextExtent(text)
        dc.DrawText(
            text,
            rect.x + (rect.width - text_width) // 2,
            rect.y + (rect.height - text_height) // 2,
        )
        return rect.x


class DimensionRow(StudioButton):
    """One dimension: a disclosure chevron, a glyph, a name, and a chunk count."""

    HEIGHT = 34

    def __init__(
        self,
        parent: wx.Window,
        entry: DimensionEntry,
        *,
        selected: bool = False,
        expanded: bool = False,
        on_select: Optional[Callable[[str], None]] = None,
        on_toggle: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.entry = entry
        self.selected = bool(selected)
        self.expanded = bool(expanded)
        self._on_select = on_select
        self._on_toggle = on_toggle
        super().__init__(
            parent,
            entry.label,
            variant="pill",
            on_click=self._select,
            height=self.HEIGHT,
            hint=f"{entry.label} · {entry.detail()}",
        )
        # Bound after the shared button plumbing so the arrow keys are seen
        # first; anything else skips through to the button's own handler.
        self.Bind(wx.EVT_KEY_DOWN, self._on_arrow)
        self._sync_name()

    # -- behaviour -----------------------------------------------------------
    def _select(self) -> None:
        invoke(self._on_select, self.entry.key)

    def _toggle(self) -> None:
        invoke(self._on_toggle, self.entry.key)

    def _sync_name(self) -> None:
        state = "selected" if self.selected else "not selected"
        disclosure = "expanded" if self.expanded else "collapsed"
        self.SetName(
            f"{self.entry.label}, {self.entry.detail()}, "
            f"{state}, {disclosure}. Left and right arrows open and close it."
        )

    def set_state(self, *, selected: bool, expanded: bool) -> None:
        """Set both row states at once and repaint."""
        self.selected = bool(selected)
        self.expanded = bool(expanded)
        self._sync_name()
        self.Refresh()

    def _on_arrow(self, event: wx.KeyEvent) -> None:
        code = event.GetKeyCode()
        if code == wx.WXK_RIGHT and not self.expanded:
            self._toggle()
            return
        if code == wx.WXK_LEFT and self.expanded:
            self._toggle()
            return
        event.Skip()

    # -- painting ------------------------------------------------------------
    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        return wx.Size(tokens.scaled(MIN_PANEL_WIDTH), tokens.scaled(self.HEIGHT))

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = self.palette()
        parent = self.GetParent()
        backdrop = parent.GetBackgroundColour() if parent else palette.surface_container
        dc, gcdc = paint_context(
            self, backdrop if backdrop.IsOk() else palette.surface_container
        )
        width, height = self.GetClientSize()
        rect = wx.Rect(0, 0, width, height)
        radius = tokens.scaled(tokens.RADIUS_SM)
        if self.selected:
            fill = palette.primary_container
            ink = palette.on_primary_container
            variant_ink = palette.on_primary_container
        else:
            fill = None
            ink = palette.on_surface
            variant_ink = palette.on_surface_variant
            if self._pressed:
                fill = tokens.blend(
                    palette.surface_container_high, palette.on_surface, 0.10
                )
            elif self._hovered:
                fill = palette.surface_container_high
        if fill is not None:
            tokens.draw_round_rect(gcdc, rect, radius, fill)
        centre = height // 2
        left = tokens.scaled(9)
        gcdc.SetFont(tokens.font(self, point_size(9)))
        gcdc.SetTextForeground(variant_ink)
        chevron = "▾" if self.expanded else "▸"
        chevron_width, chevron_height = gcdc.GetTextExtent(chevron)
        gcdc.DrawText(chevron, left, centre - chevron_height // 2)
        left += max(chevron_width, tokens.scaled(9)) + tokens.scaled(9)
        gcdc.SetFont(tokens.font(self, point_size(12)))
        gcdc.SetTextForeground(ink)
        glyph_height = gcdc.GetCharHeight()
        gcdc.DrawText(self.entry.glyph, left, centre - glyph_height // 2)
        left += tokens.scaled(16) + tokens.scaled(9)
        gcdc.SetFont(tokens.mono_font(self, point_size(10)))
        count_left = _CountPill.draw(
            gcdc,
            self.entry.count_text(),
            width - tokens.scaled(9),
            centre,
            variant_ink,
            (
                tokens.blend(palette.primary_container, palette.primary, 0.14)
                if self.selected
                else palette.surface_container_high
            ),
        )
        gcdc.SetFont(tokens.font(self, point_size(13)))
        gcdc.SetTextForeground(ink)
        available = max(0, count_left - left - tokens.scaled(8))
        gcdc.DrawText(
            elide(gcdc, self.entry.label, available),
            left,
            centre - gcdc.GetCharHeight() // 2,
        )
        if self.HasFocus():
            draw_focus_ring(gcdc, rect, radius, palette.primary)
        del gcdc


class DimensionDetail(wx.Control):
    """The single fact line an expanded dimension row reveals."""

    HEIGHT = 26

    def __init__(self, parent: wx.Window, entry: DimensionEntry) -> None:
        super().__init__(parent, style=wx.BORDER_NONE)
        self.entry = entry
        self.SetName(f"{entry.label} details: {entry.detail()}")
        self.SetToolTip(entry.detail())
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.SetInitialSize(self.DoGetBestSize())

    def AcceptsFocus(self) -> bool:  # noqa: N802 - wx API spelling
        return False

    def AcceptsFocusFromKeyboard(self) -> bool:  # noqa: N802 - wx API spelling
        return False

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        return wx.Size(tokens.scaled(MIN_PANEL_WIDTH), tokens.scaled(self.HEIGHT))

    def refresh_theme(self) -> None:
        """Re-measure for the current density and repaint."""
        self.InvalidateBestSize()
        self.SetMinSize(self.DoGetBestSize())
        self.Refresh()

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        parent = self.GetParent()
        backdrop = parent.GetBackgroundColour() if parent else palette.surface_container
        dc, gcdc = paint_context(
            self, backdrop if backdrop.IsOk() else palette.surface_container
        )
        width, height = self.GetClientSize()
        left = tokens.scaled(43)
        gcdc.SetPen(wx.Pen(palette.outline_variant))
        gcdc.DrawLine(
            tokens.scaled(20),
            tokens.scaled(2),
            tokens.scaled(20),
            height - tokens.scaled(6),
        )
        gcdc.SetFont(tokens.mono_font(self, point_size(11)))
        gcdc.SetTextForeground(palette.on_surface_variant)
        gcdc.DrawText(
            elide(gcdc, self.entry.detail(), max(0, width - left - tokens.scaled(8))),
            left,
            (height - gcdc.GetCharHeight()) // 2,
        )
        del gcdc


class BoxCard(StudioButton):
    """One selection box card: its name above its size, the size monospaced."""

    def __init__(
        self,
        parent: wx.Window,
        box: SelectionBox,
        index: int,
        *,
        selected: bool = False,
        on_click: Optional[Callable[[int], None]] = None,
    ) -> None:
        self.box = box
        self.index = int(index)
        self.selected = bool(selected)
        self._on_pick = on_click
        super().__init__(
            parent,
            box.label,
            variant="pill",
            on_click=self._pick,
            hint=(
                f"{box.label} · {box.corner_text(box.minimum)} to "
                f"{box.corner_text(box.maximum)}"
            ),
        )
        self._sync_name()

    def _pick(self) -> None:
        invoke(self._on_pick, self.index)

    def _sync_name(self) -> None:
        state = "selected" if self.selected else "not selected"
        self.SetName(
            f"{self.box.label}, {self.box.size_text()}, {self.box.volume} blocks, "
            f"{state}"
        )

    def set_selected(self, selected: bool) -> None:
        """Mark the card as the active box, or not, and repaint."""
        self.selected = bool(selected)
        self._sync_name()
        self.Refresh()

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        dc = wx.ClientDC(self)
        dc.SetFont(tokens.font(self, point_size(12), _MEDIUM))
        label_height = dc.GetCharHeight()
        dc.SetFont(tokens.mono_font(self, point_size(11)))
        size_height = dc.GetCharHeight()
        return wx.Size(
            tokens.scaled(MIN_PANEL_WIDTH),
            label_height + size_height + tokens.scaled(20),
        )

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = self.palette()
        parent = self.GetParent()
        backdrop = parent.GetBackgroundColour() if parent else palette.surface_container
        dc, gcdc = paint_context(
            self, backdrop if backdrop.IsOk() else palette.surface_container
        )
        width, height = self.GetClientSize()
        rect = wx.Rect(0, 0, width, height)
        radius = tokens.scaled(tokens.RADIUS_SM + 2)
        fill = palette.surface
        border = palette.outline_variant
        if self.selected:
            fill = tokens.blend(palette.surface, palette.primary, 0.10)
            border = palette.primary
        elif self._pressed or self._hovered:
            fill = tokens.blend(
                palette.surface, palette.primary, 0.10 if self._pressed else 0.05
            )
            border = palette.outline
        tokens.draw_round_rect(gcdc, rect, radius, fill, border)
        left = tokens.scaled(10)
        available = max(0, width - left * 2)
        top = tokens.scaled(9)
        gcdc.SetFont(tokens.font(self, point_size(12), _MEDIUM))
        gcdc.SetTextForeground(palette.on_surface)
        gcdc.DrawText(elide(gcdc, self.box.label, available), left, top)
        top += gcdc.GetCharHeight()
        gcdc.SetFont(tokens.mono_font(self, point_size(11)))
        gcdc.SetTextForeground(palette.on_surface_variant)
        gcdc.DrawText(elide(gcdc, self.box.size_text(), available), left, top)
        if self.HasFocus():
            draw_focus_ring(gcdc, rect, radius, palette.primary)
        del gcdc


class DashedButton(StudioButton):
    """The dashed outline the design uses for an add-another affordance."""

    def __init__(
        self,
        parent: wx.Window,
        label: str,
        *,
        on_click: Optional[Callable[[], None]] = None,
        hint: str = "",
        height: int = 32,
    ) -> None:
        super().__init__(
            parent,
            label,
            variant="text",
            on_click=on_click,
            hint=hint,
            height=height,
        )

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = self.palette()
        parent = self.GetParent()
        backdrop = parent.GetBackgroundColour() if parent else palette.surface_container
        dc, gcdc = paint_context(
            self, backdrop if backdrop.IsOk() else palette.surface_container
        )
        width, height = self.GetClientSize()
        rect = wx.Rect(0, 0, width, height)
        radius = tokens.scaled(tokens.RADIUS_SM + 2)
        if self._pressed or self._hovered:
            tokens.draw_round_rect(
                gcdc,
                rect,
                radius,
                tokens.blend(
                    palette.surface_container,
                    palette.primary,
                    0.12 if self._pressed else 0.06,
                ),
            )
        draw_dashed_round_rect(
            gcdc, wx.Rect(rect).Deflate(1, 1), radius, palette.outline
        )
        gcdc.SetFont(tokens.font(self, point_size(12), _MEDIUM))
        gcdc.SetTextForeground(palette.primary)
        lines = self.GetLabel().split("\n")
        line_height = gcdc.GetCharHeight()
        top = (height - line_height * len(lines)) // 2
        for line in lines:
            text = elide(gcdc, line, max(0, width - tokens.scaled(16)))
            text_width = gcdc.GetTextExtent(text)[0]
            gcdc.DrawText(text, (width - text_width) // 2, top)
            top += line_height
        if self.HasFocus():
            draw_focus_ring(gcdc, rect, radius, palette.primary)
        del gcdc


class NavigatorPanel(wx.Panel):
    """The 224px column of dimensions and selection boxes.

    The panel keeps no world data of its own: both lists are read from the open
    world every time it changes, and every choice is written straight back to
    the editor -- picking a dimension changes the one being rendered, adding a
    box adds it to the renderer's selection.  The callbacks remain so the
    workspace still hears about each choice, but they are a report rather than
    the route the change travels by.
    """

    WIDTH = PANEL_WIDTH
    MIN_WIDTH = MIN_PANEL_WIDTH

    def __init__(
        self,
        parent: wx.Window,
        *,
        dimensions: Sequence[DimensionEntry] = DEFAULT_DIMENSIONS,
        boxes: Sequence[SelectionBox] = DEFAULT_BOXES,
        on_dimension: Optional[Callable[[str], None]] = None,
        on_box: Optional[Callable[[int], None]] = None,
        on_add_box: Optional[Callable[[], None]] = None,
        on_surface: Optional[Callable[[str], None]] = None,
        on_command: Optional[Callable[[str], None]] = None,
    ) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self.on_dimension = on_dimension
        self.on_box = on_box
        self.on_add_box = on_add_box
        self.on_surface = on_surface
        self.on_command = on_command
        ctx = context.current()
        self.world_open = bool(ctx.open)
        self.dimensions: List[DimensionEntry] = list(dimensions) or list(
            dimension_entries(ctx)
        )
        self.boxes: List[SelectionBox] = list(boxes) or list(selection_boxes(ctx))
        self.dimension_key = ctx.dimension or (
            self.dimensions[0].key if self.dimensions else ""
        )
        self.box_index = 0
        self.expanded: Set[str] = set()
        self.boxes_shown = True
        #: Guards the report back to the owner in :meth:`apply_context`, so an
        #: owner that rebuilds this panel in response cannot start a loop.
        self._reporting = False
        self.search_state = SearchState(label="Navigator")
        self.SetName("Navigator")
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)

        self.scroller = wx.ScrolledWindow(self, style=wx.VSCROLL | wx.TAB_TRAVERSAL)
        self.scroller.SetScrollRate(0, tokens.scaled(12))
        self.scroller.SetName("Navigator contents")
        self.body = wx.BoxSizer(wx.VERTICAL)
        self.scroller.SetSizer(self.body)

        self.heading = SectionLabel(self.scroller, "Navigator")
        self.collapse_button = StudioButton(
            self.scroller,
            "",
            variant="icon",
            glyph="⌃",
            height=22,
            min_width=22,
            on_click=self.collapse_all,
            hint=single_line(
                studio_text(
                    "Collapse every open dimension and the selection box list.",
                    "收埋所有打開咗嘅維度同埋選取範圍清單。",
                )
            ),
            name="Collapse all",
        )
        self.search = SearchBar(
            self.scroller,
            "Search navigator",
            self.search_state,
            on_change=self._on_search,
            compact=True,
        )
        self.tree_panel = wx.Panel(self.scroller, style=wx.TAB_TRAVERSAL)
        self.tree_sizer = wx.BoxSizer(wx.VERTICAL)
        self.tree_panel.SetSizer(self.tree_sizer)
        self.tree_empty = StudioText(
            self.tree_panel, "", size_px=11, name="Dimension list state"
        )
        self.boxes_heading = SectionLabel(self.scroller, "Selection boxes")
        self.boxes_count = StudioText(
            self.scroller,
            str(len(self.boxes)),
            size_px=10,
            weight=_MEDIUM,
            role="primary",
            mono=True,
            name="Selection box count",
        )
        self.boxes_panel = wx.Panel(self.scroller, style=wx.TAB_TRAVERSAL)
        self.boxes_sizer = wx.BoxSizer(wx.VERTICAL)
        self.boxes_panel.SetSizer(self.boxes_sizer)
        self.boxes_empty = StudioText(
            self.boxes_panel, "", size_px=11, name="Selection list state"
        )
        self.empty_label = StudioText(
            self.scroller, "", size_px=11, name="Navigator search result"
        )

        header = wx.BoxSizer(wx.HORIZONTAL)
        header.Add(self.heading, 1, wx.ALIGN_CENTER_VERTICAL)
        header.Add(self.collapse_button, 0, wx.ALIGN_CENTER_VERTICAL)
        boxes_header = wx.BoxSizer(wx.HORIZONTAL)
        boxes_header.Add(self.boxes_heading, 1, wx.ALIGN_CENTER_VERTICAL)
        boxes_header.Add(self.boxes_count, 0, wx.ALIGN_CENTER_VERTICAL)

        pad = tokens.scaled(tokens.SPACE_SM + 4)
        self.body.Add(header, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, pad)
        self.body.Add(
            self.search,
            0,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP,
            tokens.scaled(tokens.SPACE_SM),
        )
        self.body.Add(
            self.tree_panel,
            0,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP,
            tokens.scaled(tokens.SPACE_SM),
        )
        self.body.Add(
            self.empty_label,
            0,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP,
            tokens.scaled(tokens.SPACE_SM + 4),
        )
        self.body.Add(
            boxes_header,
            0,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP,
            tokens.scaled(tokens.SPACE_SM + 4),
        )
        self.body.Add(
            self.boxes_panel,
            0,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            tokens.scaled(tokens.SPACE_SM + 2),
        )
        frame = wx.BoxSizer(wx.VERTICAL)
        frame.Add(self.scroller, 1, wx.EXPAND)
        self.SetSizer(frame)
        self.SetMinSize(wx.Size(tokens.scaled(self.MIN_WIDTH), -1))
        self.SetSize(wx.Size(tokens.scaled(self.WIDTH), -1))

        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.Bind(wx.EVT_CONTEXT_MENU, self._on_context_menu)
        self.scroller.Bind(wx.EVT_CONTEXT_MENU, self._on_context_menu)
        # The selection boxes have their own menu: right-clicking a box should
        # offer what can be done to a box, not what can be done to the tree
        # above it.
        self.boxes_panel.Bind(wx.EVT_CONTEXT_MENU, self._on_boxes_context_menu)
        self.Bind(wx.EVT_WINDOW_DESTROY, self._on_destroy)
        context.subscribe(self._on_world_context)
        self._apply_theme()
        self.rebuild()

    # -- the open world ------------------------------------------------------
    def _on_world_context(self, ctx: context.WorldContext) -> None:
        """Take a world change from any thread onto the one wx paints on."""
        try:
            if self.IsBeingDeleted():
                return
        except RuntimeError:
            return
        if wx.IsMainThread():
            self.apply_context(ctx)
        else:
            wx.CallAfter(self.apply_context, ctx)

    def apply_context(self, ctx: Optional[context.WorldContext] = None) -> None:
        """Re-read both lists from the world that is open right now.

        The owner is told afterwards, because surfaces outside this panel
        mirror the same two facts -- the breadcrumb bar counts the selection,
        the status bar names the dimension -- and a world that changed under
        them without a word would leave them showing a count nobody could get
        back to.  The report is guarded against re-entry so an owner that
        rebuilds the panel in response cannot start a loop.
        """
        try:
            if self.IsBeingDeleted():
                return
        except RuntimeError:
            return
        if ctx is None:
            ctx = context.current()
        previous_dimension = self.dimension_key
        previous_boxes = list(self.boxes)
        self.world_open = bool(ctx.open)
        self.dimensions = list(dimension_entries(ctx))
        self.boxes = list(selection_boxes(ctx))
        keys = {entry.key for entry in self.dimensions}
        if ctx.dimension in keys:
            self.dimension_key = ctx.dimension
        elif self.dimension_key not in keys:
            self.dimension_key = self.dimensions[0].key if self.dimensions else ""
        self.expanded &= keys
        if self.boxes:
            self.box_index = max(0, min(self.box_index, len(self.boxes) - 1))
        else:
            self.box_index = 0
        self.rebuild()
        if self._reporting:
            return
        self._reporting = True
        try:
            if self.dimension_key != previous_dimension:
                invoke(self.on_dimension, self.dimension_key)
            elif self.boxes != previous_boxes:
                invoke(self.on_box, self.box_index)
        finally:
            self._reporting = False

    def _on_destroy(self, event: wx.WindowDestroyEvent) -> None:
        if event.GetEventObject() is self:
            context.unsubscribe(self._on_world_context)
        event.Skip()

    # -- content -------------------------------------------------------------
    def _dimensions_note(self) -> str:
        """Return what the tree says when it has no dimension to show."""
        return NO_WORLD_DIMENSIONS if not self.world_open else NO_DIMENSIONS

    def _boxes_note(self) -> str:
        """Return what the selection list says when it has no box to show."""
        return NO_WORLD_BOXES if not self.world_open else NO_BOXES

    def _set_note(self, label: StudioText, base_name: str, text: str) -> None:
        """Show one empty-state line, wrapped to the column it sits in.

        The note keeps its own unwrapped text and lays it out at the width it
        is given, so nothing a caller reads back has been edited by the layout.
        ``wx.StaticText.Wrap`` wrote its line breaks into the label itself, so
        ``GetLabel`` answered with newlines the caller never set -- and this
        surface writes that same label into the accessible name.

        Measured rather than assumed, because the obvious worry does not hold:
        on wxWidgets 3.3.3 ``Wrap`` re-derives from the original text, so
        re-wrapping at one width is idempotent and re-wrapping wider recovers
        the string exactly.  The defect was the mangled read-back, not
        cumulative degradation.  The text is still set before the width,
        because that is the order the accessible name wants.
        """
        message = single_line(text)
        label.SetLabel(message)
        label.SetName(f"{base_name}: {message}" if message else base_name)
        if message:
            label.Wrap(
                max(tokens.scaled(120), self.GetClientSize().width - tokens.scaled(28))
            )
        label.Show(bool(message))

    def rebuild(self) -> None:
        """Rebuild both lists from the open world and the search query."""
        state = self.search_state
        clear_container(self.tree_sizer, self.tree_panel, keep=(self.tree_empty,))
        matched_dimensions = [
            entry
            for entry in self.dimensions
            if state.matches(f"{entry.label} {entry.key} {entry.detail()}")
        ]
        gap = tokens.scaled(3)
        for entry in matched_dimensions:
            row = DimensionRow(
                self.tree_panel,
                entry,
                selected=entry.key == self.dimension_key,
                expanded=entry.key in self.expanded,
                on_select=self.select_dimension,
                on_toggle=self.toggle_dimension,
            )
            self.tree_sizer.Add(row, 0, wx.EXPAND | wx.BOTTOM, gap)
            if entry.key in self.expanded:
                self.tree_sizer.Add(
                    DimensionDetail(self.tree_panel, entry),
                    0,
                    wx.EXPAND | wx.BOTTOM,
                    gap,
                )
        self._set_note(
            self.tree_empty,
            "Dimension list state",
            self._dimensions_note() if not self.dimensions else "",
        )
        if not self.dimensions:
            self.tree_sizer.Add(self.tree_empty, 0, wx.EXPAND | wx.BOTTOM, gap)

        clear_container(self.boxes_sizer, self.boxes_panel, keep=(self.boxes_empty,))
        matched_boxes = [
            (index, box)
            for index, box in enumerate(self.boxes)
            if state.matches(f"{box.label} {box.size_text()}")
        ]
        for index, box in matched_boxes:
            card = BoxCard(
                self.boxes_panel,
                box,
                index,
                selected=index == self.box_index,
                on_click=self.select_box,
            )
            self.boxes_sizer.Add(card, 0, wx.EXPAND | wx.BOTTOM, tokens.scaled(6))
        self._set_note(
            self.boxes_empty,
            "Selection list state",
            self._boxes_note() if not self.boxes else "",
        )
        if not self.boxes:
            self.boxes_sizer.Add(
                self.boxes_empty, 0, wx.EXPAND | wx.BOTTOM, tokens.scaled(6)
            )
        self.add_button = DashedButton(
            self.boxes_panel,
            studio_label("Add selection box", "加多個選取範圍"),
            on_click=self._add_box,
            hint=single_line(
                self._add_box_hint(),
            ),
        )
        self.add_button.Enable(self.world_open)
        self.boxes_sizer.Add(self.add_button, 0, wx.EXPAND)

        self.boxes_count.SetLabel(str(len(self.boxes)))
        self.boxes_panel.Show(self.boxes_shown)
        self.empty_label.SetLabel(
            state.describe_matches(
                len(matched_dimensions) + len(matched_boxes), "navigator row"
            )
            if state.is_active()
            else ""
        )
        self.empty_label.Show(bool(state.is_active()))
        self.scroller.FitInside()
        self.scroller.Layout()
        self.Layout()
        self._apply_theme()

    def _add_box_hint(self) -> str:
        """Return what the add button promises, or why it cannot keep it."""
        if not self.world_open:
            return NO_WORLD_BOXES
        if self.boxes:
            return studio_text(
                "Add a one-block box at the active box's corner.",
                "喺而家嗰個範圍嘅角落加一格大嘅新範圍。",
            )
        return studio_text(
            "Add a one-block box at this world's spawn point.",
            "喺呢個世界嘅出生點加一格大嘅範圍。",
        )

    def set_dimensions(self, dimensions: Sequence[DimensionEntry]) -> None:
        """Replace the dimension list, keeping the selection where it still exists."""
        self.dimensions = list(dimensions)
        keys = {entry.key for entry in self.dimensions}
        if self.dimension_key not in keys and self.dimensions:
            self.dimension_key = self.dimensions[0].key
        self.expanded &= keys
        self.rebuild()

    def set_boxes(self, boxes: Sequence[SelectionBox]) -> None:
        """Replace the selection boxes and clamp the active index into range."""
        self.boxes = list(boxes)
        if self.boxes:
            self.box_index = max(0, min(self.box_index, len(self.boxes) - 1))
        else:
            self.box_index = 0
        self.rebuild()

    def selected_dimension(self) -> str:
        """Return the key of the dimension currently being edited."""
        return self.dimension_key

    def dimension(self, key: str = "") -> Optional[DimensionEntry]:
        """Return one dimension entry, defaulting to the selected one."""
        wanted = key or self.dimension_key
        for entry in self.dimensions:
            if entry.key == wanted:
                return entry
        return None

    def selected_box(self) -> Optional[SelectionBox]:
        """Return the active selection box, or ``None`` when there is none."""
        if 0 <= self.box_index < len(self.boxes):
            return self.boxes[self.box_index]
        return None

    # -- behaviour -----------------------------------------------------------
    def select_dimension(self, key: str) -> None:
        """Render ``key`` in the editor and report the change to the workspace.

        The renderer is asked first, because it is the thing that actually
        changes what the user is looking at; the world context is told
        afterwards so the other panes follow.  A renderer that refuses the
        change -- one that is mid-teardown, or has not finished loading -- is
        logged and the dimension is left where it was rather than the panel
        claiming a move that did not happen.
        """
        if key == self.dimension_key:
            self.toggle_dimension(key)
            return
        canvas = studio_canvas()
        if canvas is not None:
            try:
                canvas.dimension = key
            except Exception as err:  # noqa: BLE001 - a canvas being torn down
                log.debug("The renderer would not switch to dimension %r: %s", key, err)
                return
        self.dimension_key = key
        context.set_dimension(key)
        self.rebuild()
        invoke(self.on_dimension, key)

    def toggle_dimension(self, key: str) -> None:
        """Open or close one dimension's detail line."""
        if key in self.expanded:
            self.expanded.discard(key)
        else:
            self.expanded.add(key)
        self.rebuild()

    def select_box(self, index: int) -> None:
        """Make one box the active selection and report it to the workspace."""
        if not 0 <= index < len(self.boxes):
            return
        self.box_index = index
        for child in self.boxes_panel.GetChildren():
            if isinstance(child, BoxCard):
                child.set_selected(child.index == index)
        invoke(self.on_box, index)

    def collapse_all(self) -> None:
        """Close every open dimension and hide the selection box list."""
        if self.expanded or self.boxes_shown:
            self.expanded.clear()
            self.boxes_shown = False
        else:
            self.boxes_shown = True
        self.collapse_button.glyph = "⌃" if self.boxes_shown else "⌄"
        self.collapse_button.SetName(
            "Collapse all" if self.boxes_shown else "Expand the selection boxes"
        )
        self.rebuild()

    def _add_box(self) -> None:
        if self.on_add_box is not None:
            invoke(self.on_add_box)
            return
        self.add_box()

    def add_box(self) -> Optional[SelectionBox]:
        """Add a one-block box to the world's selection and make it active.

        Where the box goes is read rather than chosen: beside the active box
        when there is one, at the world's own spawn point when there is not,
        and at the origin only when the world records no spawn.  With no world
        open there is nothing to select in, so nothing is added and ``None``
        says so.
        """
        ctx = context.current()
        if not ctx.open:
            log.debug("No world is open, so no selection box was added")
            return None
        anchor = self.selected_box()
        if anchor is not None:
            origin = tuple(int(value) for value in anchor.minimum)
        elif ctx.spawn is not None:
            origin = tuple(int(value) for value in ctx.spawn)
        else:
            origin = (0, 0, 0)
        box = SelectionBox(f"Box {len(self.boxes) + 1}", origin, (1, 1, 1))
        self.boxes.append(box)
        self.box_index = len(self.boxes) - 1
        self.boxes_shown = True
        push_selection(self.boxes)
        self.rebuild()
        invoke(self.on_box, self.box_index)
        return box

    def _on_search(self, _state: SearchState) -> None:
        self.rebuild()

    def _menu_position(self, event: wx.ContextMenuEvent) -> wx.Point:
        """Return where a menu should open, including for a keyboard request."""
        position = event.GetPosition()
        if position == wx.DefaultPosition:
            size = self.GetSize()
            return self.ClientToScreen(wx.Point(size.width // 2, size.height // 3))
        return position

    def _on_context_menu(self, event: wx.ContextMenuEvent) -> None:
        open_studio_menu(
            self,
            "navigator",
            self._menu_position(event),
            self.on_surface,
            self.on_command,
        )

    def _on_boxes_context_menu(self, event: wx.ContextMenuEvent) -> None:
        open_studio_menu(
            self,
            "boxes",
            self._menu_position(event),
            self.on_surface,
            self.on_command,
        )

    # -- appearance ----------------------------------------------------------
    def _apply_theme(self) -> None:
        palette = tokens.palette()
        self.SetBackgroundColour(palette.surface_container)
        for panel in (self.scroller, self.tree_panel, self.boxes_panel):
            panel.SetBackgroundColour(palette.surface_container)
        # The four notes are owner-drawn and read their role colour and their
        # font from the tokens on every paint, so a theme or interface-scale
        # change reaches them through the repaint below rather than through a
        # colour pushed in from here.

    def refresh_theme(self) -> None:
        """Re-read the palette for the panel and every row in it."""
        self._apply_theme()
        for child in self.scroller.GetChildren():
            refresh = getattr(child, "refresh_theme", None)
            if callable(refresh):
                refresh()
        for panel in (self.tree_panel, self.boxes_panel):
            for child in panel.GetChildren():
                refresh = getattr(child, "refresh_theme", None)
                if callable(refresh):
                    refresh()
        self.Layout()
        self.Refresh()

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        dc, gcdc = paint_context(self, palette.surface_container)
        width, height = self.GetClientSize()
        gcdc.SetPen(wx.Pen(palette.outline_variant))
        gcdc.DrawLine(width - 1, 0, width - 1, height)
        del gcdc


__all__ = [
    "DEFAULT_BOXES",
    "DEFAULT_DIMENSIONS",
    "MIN_PANEL_WIDTH",
    "NO_BOXES",
    "NO_DIMENSIONS",
    "NO_WORLD_BOXES",
    "NO_WORLD_DIMENSIONS",
    "PANEL_WIDTH",
    "BoxCard",
    "DashedButton",
    "DimensionDetail",
    "DimensionEntry",
    "DimensionRow",
    "NavigatorPanel",
    "SelectionBox",
    "dimension_entries",
    "dimension_glyph",
    "push_selection",
    "selection_boxes",
]
