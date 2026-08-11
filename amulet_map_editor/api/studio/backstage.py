"""The backstage: the first screen a user meets, before any world is open.

Six destinations behind one navigation rail -- Home, Open, Info, Convert, All
surfaces, and Workspace -- transcribed from the Studio design.  Home is the
template gallery over a searchable, filterable, multi-selectable recent table;
the rest are the project-level surfaces that do not belong inside the editing
workspace.

Everything drawn here is owner-drawn against :mod:`tokens`, so one theme,
density, accent, or interface-scale change repaints the whole screen rather
than the handful of controls somebody remembered to wire.  Nothing is fetched
over the network and no example project is invented: an empty recent list shows
an honest empty state, because a first-run screen listing projects that do not
exist teaches a user to distrust every other number the shell reports.

The module imports ``wx`` but constructs no window at import time, and every
optional dependency -- the surface index, the regex builder, the world picker's
native dialogs -- is imported inside the function that needs it, so importing
this module can never require a display or a module another surface owns.
"""

from __future__ import annotations

import logging
import math
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import wx

from amulet_map_editor.api import preferences
from amulet_map_editor.api.studio import recents, tokens, widgets
from amulet_map_editor.api.studio.copy import studio_label, studio_text
from amulet_map_editor.api.studio.recents import RecentEntry
from amulet_map_editor.api.studio.search import SearchState

log = logging.getLogger(__name__)

_MEDIUM = getattr(wx, "FONTWEIGHT_MEDIUM", wx.FONTWEIGHT_NORMAL)
_LIGHT = getattr(wx, "FONTWEIGHT_LIGHT", wx.FONTWEIGHT_NORMAL)

#: Width of the navigation rail, in design pixels.
RAIL_WIDTH = 236

#: Padding around the scrolling body, transcribed from the design.
BODY_PADDING_TOP = 34
BODY_PADDING_SIDE = 40
BODY_PADDING_BOTTOM = 44

#: The backstage destinations, in rail order.  The keys are what
#: ``StudioShell.show_backstage`` passes in.
TABS: Tuple[str, ...] = ("home", "open", "info", "convert", "features", "account")

#: Command keys this view asks the shell to run.  They are named here so the
#: command registry and this view can be checked against one list rather than
#: against each other's source.
COMMAND_SAVE = "save"
COMMAND_CLOSE_PROJECT = "close_project"
COMMAND_EXPORT_SELECTION = "export_selection"
#: The command that brings the user to the Convert page.  This view is that
#: command's destination rather than one of its callers: the conversion runs
#: here, so pressing Convert does not ask the shell to navigate anywhere.
COMMAND_CONVERT = "convert_world"
COMMAND_UPDATE_RESTART = "update_restart"

#: The logger the conversion extension reports its own result through.  Its
#: completion notification is raised from a worker thread, which wx refuses, so
#: the log is the only place that result actually arrives.
CONVERT_LOGGER = "amulet_map_editor.programs.convert.convert"

#: Surface keys this view opens.  These match the shared surface index.
SURFACE_PREFERENCES = "prefs"
SURFACE_HISTORY = "history"
SURFACE_CHANGELOG = "changelog"
SURFACE_MEMORY = "memory"

#: Bulk actions offered over the recent table, in bar order.
BULK_SELECT_ALL = "Select all matches"
BULK_SELECT_NONE = "Select none"
BULK_INVERT = "Invert selection"
BULK_OPEN = "Open"
BULK_PIN = "Pin"
BULK_UNPIN = "Unpin"
BULK_REMOVE = "Remove from list…"
BULK_EXPORT = "Export list…"

BULK_ACTIONS: Tuple[str, ...] = (
    BULK_SELECT_ALL,
    BULK_SELECT_NONE,
    BULK_INVERT,
    BULK_OPEN,
    BULK_PIN,
    BULK_UNPIN,
    BULK_REMOVE,
    BULK_EXPORT,
)

#: Cantonese for each bulk action, so the bar reads in the chosen language.
BULK_CANTONESE: Dict[str, str] = {
    BULK_SELECT_ALL: "選取所有符合嘅項目",
    BULK_SELECT_NONE: "取消選取",
    BULK_INVERT: "反選",
    BULK_OPEN: "開啟",
    BULK_PIN: "釘住",
    BULK_UNPIN: "取消釘住",
    BULK_REMOVE: "喺清單移除…",
    BULK_EXPORT: "匯出清單…",
}

#: How much of a project directory the size and chunk measurement will read
#: before it stops and says so.  A world can hold hundreds of thousands of
#: files, and an exact figure is not worth a stalled screen.
MEASURE_FILE_LIMIT = 40_000
MEASURE_REGION_LIMIT = 512
MEASURE_SECONDS = 8.0

#: Filenames a world directory may carry as its own icon.
WORLD_ICON_NAMES: Tuple[str, ...] = ("world_icon.jpeg", "world_icon.png", "icon.png")

#: The most worlds one scan of the installed save directories will identify
#: before it stops and says it stopped.  Identifying a world opens its format
#: wrapper, so an installation holding thousands of them is bounded rather than
#: left to run for minutes behind a spinner.
MAX_DETECTED_WORLDS = 400

#: The most detected worlds the Open page lists inline before it says how many
#: more matched.  The page is a route into a world, not a file manager.
MAX_DETECTED_WORLD_ROWS = 12

#: Structure formats the Open tab accepts.
STRUCTURE_WILDCARD = (
    "Structure files|*.construction;*.schem;*.schematic;*.mcstructure|"
    "Amulet construction (*.construction)|*.construction|"
    "Sponge schematic (*.schem)|*.schem|"
    "MCEdit schematic (*.schematic)|*.schematic|"
    "Bedrock structure (*.mcstructure)|*.mcstructure|"
    "All files (*.*)|*.*"
)


# ---------------------------------------------------------------------------
# small shared helpers
# ---------------------------------------------------------------------------
def _px(value: float) -> int:
    """Scale a design pixel measurement by the interface scale."""
    return tokens.scaled(int(round(value)))


def _line_height(dc: wx.DC, size_px: float, factor: float) -> int:
    """Return the leading a design line-height asks for at this font size."""
    return max(dc.GetCharHeight(), _px(round(size_px * factor)))


def _format_bytes(count: int) -> str:
    """Render a byte count the way a file manager would, never as raw bytes."""
    value = float(max(0, count))
    for unit in ("bytes", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit == "bytes":
                return f"{int(value)} bytes"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def _fit_owner_drawn(window: wx.Window) -> None:
    """Widen owner-drawn buttons and chips so their labels are never elided.

    A control that measures its best size on an ordinary device context and
    then draws the same string through an antialiased graphics context asks for
    slightly less room than it needs: the two report different extents for the
    same font, and the difference lands as an ellipsis in the middle of a
    button label.  The shortfall is measured here with both contexts and added
    to the minimum size, which is exact rather than a guessed margin, and does
    nothing at all when the two agree.
    """
    targets: List[wx.Window] = []

    def collect(parent: wx.Window) -> None:
        for child in parent.GetChildren():
            if isinstance(child, (widgets.StudioButton, widgets.Chip)):
                targets.append(child)
            collect(child)

    collect(window)
    if not targets:
        return
    bitmap = wx.Bitmap(1, 1)
    measuring = wx.MemoryDC(bitmap)
    drawing = wx.GCDC(measuring)
    try:
        for control in targets:
            label = control.GetLabel()
            if not label:
                continue
            is_chip = isinstance(control, widgets.Chip)
            font = tokens.font(
                control, widgets.point_size(14 if is_chip else 13), _MEDIUM
            )
            measuring.SetFont(font)
            drawing.SetFont(font)
            lines = label.split("\n") or [""]
            plain = max(measuring.GetTextExtent(line or " ")[0] for line in lines)
            painted = max(drawing.GetTextExtent(line or " ")[0] for line in lines)
            shortfall = max(0, painted - plain)
            if not shortfall:
                continue
            best = control.GetBestSize()
            control.SetMinSize(wx.Size(best.width + shortfall + _px(2), best.height))
    finally:
        del drawing
        measuring.SelectObject(wx.NullBitmap)


#: Identifier written into an exported surface index so a reader knows the
#: columns without having to guess them from the header row.
SURFACE_EXPORT_SCHEMA = "amulet.studio.surfaces"
SURFACE_EXPORT_VERSION = 1


def surface_export_text(
    export_format: str, rows: Sequence[Tuple[str, str, str, str]]
) -> str:
    """Render the surface index as JSON, CSV, or a Markdown table.

    ``rows`` are ``(key, label, group, hint)`` tuples, which is what the index
    itself carries; keeping the tuple rather than the registry's own dataclass
    means this module never has to import a registry it only reads.
    """
    import csv
    import io
    import json

    now = recents.to_iso()
    export_format = str(export_format).lower()
    if export_format == "json":
        return (
            json.dumps(
                {
                    "schema": SURFACE_EXPORT_SCHEMA,
                    "version": SURFACE_EXPORT_VERSION,
                    "encoding": "utf-8",
                    "line_endings": "lf",
                    "exported": now,
                    "count": len(rows),
                    "surfaces": [
                        {"key": key, "label": label, "group": group, "hint": hint}
                        for key, label, group, hint in rows
                    ],
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n"
        )
    if export_format == "csv":
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(("key", "label", "group", "hint"))
        writer.writerows(rows)
        return buffer.getvalue()
    if export_format != "markdown":
        raise ValueError(
            f"Unknown export format {export_format!r}; "
            f"expected one of {', '.join(recents.EXPORT_FORMATS)}."
        )
    lines = [
        "# Amulet Studio surfaces",
        "",
        f"Exported {now} · {len(rows)} {'surface' if len(rows) == 1 else 'surfaces'}"
        f" · UTF-8 · LF line endings · schema {SURFACE_EXPORT_SCHEMA}"
        f" v{SURFACE_EXPORT_VERSION}",
        "",
    ]
    if not rows:
        lines.extend(("No surfaces matched the current search.", ""))
        return "\n".join(lines)
    lines.append("| Key | Surface | Group | What it does |")
    lines.append("| --- | --- | --- | --- |")
    for key, label, group, hint in rows:
        cells = [
            str(value).replace("|", "\\|").replace("\n", " ").strip()
            for value in (key, label, group, hint)
        ]
        lines.append(f"| `{cells[0]}` | {cells[1]} | {cells[2]} | {cells[3]} |")
    lines.append("")
    return "\n".join(lines)


class _ConversionLog(logging.Handler):
    """Collect what the conversion extension itself reported about a run.

    The extension swallows its own exception, builds a message from it, and
    then tries to raise a notification from its worker thread -- which wx
    refuses, so that message never reaches the user.  It does reach the log
    first, so the log is where the real verdict is read from.  Inventing a
    verdict here instead would mean reporting a success this module never
    observed.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.records: List[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    def verdict(self) -> Tuple[Optional[bool], str]:
        """Return ``(succeeded, message)``; ``None`` when nothing was reported."""
        for record in reversed(self.records):
            if record.levelno >= logging.ERROR:
                return False, record.getMessage()
        for record in reversed(self.records):
            if "Finished converting" in record.getMessage():
                return True, record.getMessage()
        return None, ""


def _card_body(card: wx.Window, padding: int = 18) -> wx.BoxSizer:
    """Give a card the design's inset and return the sizer its content goes in.

    Padding an outer sizer once is what keeps every child's own border --
    the 12px under a caption, the 14px under a paragraph -- meaning what it
    says, instead of being silently widened to the card's inset.
    """
    outer = wx.BoxSizer(wx.VERTICAL)
    inner = wx.BoxSizer(wx.VERTICAL)
    outer.Add(inner, 1, wx.EXPAND | wx.ALL, _px(padding))
    card.SetSizer(outer)
    return inner


def _greeting_pair(now: Optional[datetime] = None) -> Tuple[str, str]:
    """Return the greeting for the local time of day, in both languages.

    The design's screenshot says "Good afternoon" because that is when it was
    drawn.  Shipping that string unconditionally would greet somebody at
    midnight with an afternoon, so the hour is read from the local clock.
    """
    hour = (now or datetime.now()).hour
    if 5 <= hour < 12:
        return ("Good morning", "早晨")
    if 12 <= hour < 18:
        return ("Good afternoon", "午安")
    return ("Good evening", "晚安")


def _fill_rounded_top(
    context: wx.GraphicsContext,
    rect: wx.Rect,
    radius: int,
    start: wx.Colour,
    end: wx.Colour,
) -> None:
    """Fill a rectangle with rounded top corners using a diagonal gradient.

    The design paints the template-card header with a 150-degree gradient
    behind rounded top corners and square bottom ones, which no single wx
    primitive draws; a path filled with a gradient brush is the shape it
    actually asks for.
    """
    corner = max(0, min(radius, rect.width // 2, rect.height))
    path = context.CreatePath()
    left, top = float(rect.x), float(rect.y)
    right, bottom = float(rect.x + rect.width), float(rect.y + rect.height)
    path.MoveToPoint(left, bottom)
    path.AddLineToPoint(left, top + corner)
    path.AddArc(left + corner, top + corner, corner, math.pi, 1.5 * math.pi, True)
    path.AddLineToPoint(right - corner, top)
    path.AddArc(right - corner, top + corner, corner, 1.5 * math.pi, 2 * math.pi, True)
    path.AddLineToPoint(right, bottom)
    path.CloseSubpath()
    context.SetPen(wx.TRANSPARENT_PEN)
    context.SetBrush(
        context.CreateLinearGradientBrush(
            left, top, left + rect.width * 0.5, bottom, start, end
        )
    )
    context.FillPath(path)


class _HoverControl(wx.Control):
    """Hover, press, focus, and keyboard activation for an owner-drawn card.

    The backstage draws several shapes wx has no control for -- a template
    card, a recent row, a rail item -- and every one of them has to answer to
    the keyboard as readily as to a click, because a screen that can only be
    used with a mouse is unfinished rather than merely rough.
    """

    def _setup(self, name: str, *, focusable: bool = True) -> None:
        self._hovered = False
        self._pressed = False
        self._focusable = bool(focusable)
        self.SetName(name or "Control")
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        if self._focusable:
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

    def AcceptsFocus(self) -> bool:  # noqa: N802 - wx API spelling
        return self._focusable and self.IsEnabled()

    def AcceptsFocusFromKeyboard(self) -> bool:  # noqa: N802 - wx API spelling
        return self.AcceptsFocus()

    def palette(self) -> tokens.StudioPalette:
        """Return the live palette; resolved per paint so changes land at once."""
        return tokens.palette()

    def backdrop(self) -> wx.Colour:
        """Return the colour behind this control, for a clean buffered paint."""
        parent = self.GetParent()
        colour = parent.GetBackgroundColour() if parent is not None else wx.NullColour
        return colour if colour.IsOk() else self.palette().surface

    def refresh_theme(self) -> None:
        """Repaint after a theme, accent, density, or scale change."""
        try:
            if self.IsBeingDeleted():
                return
        except RuntimeError:  # pragma: no cover - window already destroyed
            return
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
            if self._focusable:
                self.SetFocus()
            self._pressed = True
            self.Refresh()
        event.Skip()

    def _on_left_up(self, event: wx.MouseEvent) -> None:
        was_pressed = self._pressed
        self._pressed = False
        self.Refresh()
        if was_pressed and self.GetClientRect().Contains(event.GetPosition()):
            self.activate(event)
        event.Skip()

    def _on_key_down(self, event: wx.KeyEvent) -> None:
        if self.IsEnabled() and event.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_SPACE):
            self.activate(None)
            return
        event.Skip()

    def _on_focus_change(self, event: wx.FocusEvent) -> None:
        self.Refresh()
        event.Skip()

    def activate(self, event: Optional[wx.MouseEvent]) -> None:
        """Run this control's action.  Every concrete card overrides it."""
        widgets.invoke(getattr(self, "on_click", None))


class _Text(wx.Control):
    """One block of laid-out text: a heading, an eyebrow, or a paragraph.

    wx's ``StaticText`` cannot letter-space an uppercase eyebrow, cannot draw
    a 34px light heading against a token colour, and rewraps unpredictably when
    the interface scale changes.  Drawing the text is less code than working
    around all three, and it keeps every string on the same measurement path.
    """

    def __init__(
        self,
        parent: wx.Window,
        text: str,
        *,
        size_px: float = 13,
        weight: int = wx.FONTWEIGHT_NORMAL,
        role: str = "on_surface",
        line_height: float = 1.45,
        wrap_width: int = 0,
        mono: bool = False,
        uppercase: bool = False,
        tracking: float = 0.0,
        max_lines: int = 64,
        name: str = "",
    ) -> None:
        super().__init__(parent, style=wx.BORDER_NONE)
        self._text = str(text)
        self._size_px = float(size_px)
        self._weight = weight
        self._role = role
        self._line_factor = float(line_height)
        self._wrap_width = int(wrap_width)
        self._mono = bool(mono)
        self._uppercase = bool(uppercase)
        self._tracking = float(tracking)
        self._max_lines = int(max_lines)
        self._lines: List[str] = []
        self._best = wx.Size(1, 1)
        self.SetName(name or self._text.replace("\n", " ") or "Text")
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self._relayout()

    def AcceptsFocus(self) -> bool:  # noqa: N802 - wx API spelling
        return False

    def AcceptsFocusFromKeyboard(self) -> bool:  # noqa: N802 - wx API spelling
        return False

    # -- content -------------------------------------------------------------
    def set_text(self, text: str) -> None:
        """Replace the text and re-measure it."""
        self._text = str(text)
        self.SetName(self._text.replace("\n", " ") or "Text")
        self._relayout()
        self.Refresh()

    def set_role(self, role: str) -> None:
        """Change which palette role paints the ink."""
        self._role = role
        self.Refresh()

    def set_available_width(self, width: int) -> None:
        """Wrap to a new width, growing or shrinking the control to match."""
        width = max(0, int(width))
        if width == self._wrap_width:
            return
        self._wrap_width = width
        self._relayout()
        self.Refresh()

    def _display_text(self) -> str:
        return self._text.upper() if self._uppercase else self._text

    def _font(self) -> wx.Font:
        return tokens.font(
            self, widgets.point_size(self._size_px), self._weight, mono=self._mono
        )

    def _relayout(self) -> None:
        dc = wx.ClientDC(self)
        dc.SetFont(self._font())
        text = self._display_text()
        tracking = _px(self._tracking) if self._tracking else 0
        if self._wrap_width > 0:
            self._lines = widgets.wrap_text(
                dc, text, self._wrap_width, max_lines=self._max_lines
            )
        else:
            self._lines = text.split("\n") or [""]
        leading = _line_height(dc, self._size_px, self._line_factor)
        width = max(
            (widgets.tracked_width(dc, line, tracking) for line in self._lines),
            default=0,
        )
        if self._wrap_width > 0:
            width = min(width, self._wrap_width)
        self._best = wx.Size(max(1, width), max(1, leading * len(self._lines)))
        self.SetMinSize(self._best)
        self.SetInitialSize(self._best)

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        return wx.Size(self._best)

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        parent = self.GetParent()
        colour = parent.GetBackgroundColour() if parent is not None else wx.NullColour
        dc, gcdc = widgets.paint_context(
            self, colour if colour.IsOk() else palette.surface
        )
        gcdc.SetFont(self._font())
        gcdc.SetTextForeground(palette.role(self._role))
        leading = _line_height(gcdc, self._size_px, self._line_factor)
        tracking = _px(self._tracking) if self._tracking else 0
        y = 0
        for line in self._lines:
            if tracking:
                widgets.draw_tracked_text(gcdc, line, 0, y, tracking)
            else:
                gcdc.DrawText(line, 0, y)
            y += leading
        del gcdc


def _heading(parent: wx.Window, english: str, cantonese: str, size_px: float) -> _Text:
    """Build one of the two big page headings the design uses.

    A heading names the page, so it is built with ``studio_label`` and carries
    no tone.  The paragraph underneath it is the application talking and does.
    """
    return _Text(
        parent,
        studio_label(english, cantonese),
        size_px=size_px,
        weight=_LIGHT,
        role="on_surface",
        line_height=1.15,
        name=english,
    )


def _eyebrow(
    parent: wx.Window, english: str, cantonese: str, size_px: float = 13
) -> _Text:
    """Build the uppercase primary caption that titles a block.

    Titling is naming, so this takes no tone either -- and an eyebrow is set in
    uppercase with letter tracking on a single line, which is the least
    forgiving place in the whole design to append a clause to.
    """
    return _Text(
        parent,
        studio_label(english, cantonese),
        size_px=size_px,
        weight=_MEDIUM,
        role="primary",
        line_height=1.3,
        uppercase=True,
        tracking=0.4 if size_px >= 13 else 0.5,
        name=english,
    )


def _body_text(
    parent: wx.Window,
    english: str,
    cantonese: str,
    *,
    size_px: float = 15,
    role: str = "on_surface_variant",
    line_height: float = 1.5,
) -> _Text:
    """Build a wrapping paragraph in the reader's language and tone."""
    return _Text(
        parent,
        studio_text(english, cantonese),
        size_px=size_px,
        role=role,
        line_height=line_height,
        name=english,
    )


# ---------------------------------------------------------------------------
# navigation rail
# ---------------------------------------------------------------------------
class _RailButton(_HoverControl):
    """One 40px navigation item inside the primary-container rail."""

    HEIGHT = 40
    RADIUS = 10
    PADDING = 12
    GLYPH_COLUMN = 18
    GAP = 12

    def __init__(
        self,
        parent: wx.Window,
        label: str,
        glyph: str,
        *,
        on_click: Optional[Callable[[], None]] = None,
        active: bool = False,
        filled: bool = False,
        name: str = "",
        hint: str = "",
    ) -> None:
        super().__init__(parent, style=wx.BORDER_NONE | wx.WANTS_CHARS)
        self.label = str(label)
        self.glyph = str(glyph)
        self.on_click = on_click
        self.active = bool(active)
        self.filled = bool(filled)
        self._setup(name or self.label)
        if hint:
            self.SetToolTip(hint)
        self.SetInitialSize(self.DoGetBestSize())

    def set_active(self, active: bool) -> None:
        """Mark this item as the destination currently on screen."""
        self.active = bool(active)
        self.SetName(f"{self.label} — current" if self.active else self.label)
        self.Refresh()

    def activate(self, _event: Optional[wx.MouseEvent] = None) -> None:
        widgets.invoke(self.on_click)

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        dc = wx.ClientDC(self)
        dc.SetFont(tokens.font(self, widgets.point_size(14)))
        lines = self.label.split("\n") or [""]
        width = max(dc.GetTextExtent(line or " ")[0] for line in lines)
        leading = _line_height(dc, 14, 1.3)
        height = max(_px(self.HEIGHT), leading * len(lines) + _px(8))
        return wx.Size(
            width + _px(self.PADDING * 2 + self.GLYPH_COLUMN + self.GAP), height
        )

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        dc, gcdc = widgets.paint_context(self, palette.primary_container)
        width, height = self.GetClientSize()
        rect = wx.Rect(0, 0, width, height)
        ink = palette.on_primary_container
        fill: Optional[wx.Colour] = None
        weight = wx.FONTWEIGHT_NORMAL
        if self.filled:
            fill, ink, weight = palette.primary, palette.on_primary, _MEDIUM
            if self._pressed or self._hovered:
                fill = tokens.blend(
                    palette.primary,
                    palette.on_primary,
                    0.16 if self._pressed else 0.08,
                )
        elif self.active:
            fill = tokens.blend(palette.primary_container, ink, 0.16)
            weight = _MEDIUM
        elif self._pressed or self._hovered:
            fill = tokens.blend(
                palette.primary_container, ink, 0.12 if self._pressed else 0.06
            )
        tokens.draw_round_rect(gcdc, rect, _px(self.RADIUS), fill, None)
        gcdc.SetTextForeground(ink)
        glyph = self.glyph
        gcdc.SetFont(tokens.font(self, widgets.point_size(14)))
        glyph_width = gcdc.GetTextExtent(glyph)[0] if glyph else 0
        column = _px(self.GLYPH_COLUMN)
        left = _px(self.PADDING)
        if glyph:
            gcdc.DrawText(
                glyph,
                left + max(0, (column - glyph_width) // 2),
                (height - gcdc.GetCharHeight()) // 2,
            )
        gcdc.SetFont(tokens.font(self, widgets.point_size(14), weight))
        text_left = left + column + _px(self.GAP)
        available = max(0, width - text_left - _px(self.PADDING))
        lines = self.label.split("\n") or [""]
        leading = _line_height(gcdc, 14, 1.3)
        y = (height - leading * len(lines)) // 2
        for line in lines:
            gcdc.DrawText(widgets.elide(gcdc, line, available), text_left, y)
            y += leading
        if self.HasFocus():
            widgets.draw_focus_ring(gcdc, rect, _px(self.RADIUS), ink)
        del gcdc


# ---------------------------------------------------------------------------
# home: template gallery
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class _Template:
    """One card in the "New" gallery, and exactly what pressing it does.

    ``action`` names a real route through the application.  A card whose hint
    promises something the build cannot yet do carries that promise in
    :attr:`unavailable` instead of in the hint, so the card says so on its face
    rather than appearing to work and doing nothing.
    """

    title: str
    cantonese_title: str
    hint: str
    cantonese_hint: str
    glyph: str
    action: str
    #: Why this card cannot do what it describes, or ``""`` when it can.
    unavailable: str = ""


TEMPLATES: Tuple[_Template, ...] = (
    _Template(
        "Open a world folder",
        "開啟世界資料夾",
        "Browse for a save directory. Amulet reads level.dat to identify it.",
        "揀一個存檔資料夾，Amulet 會讀 level.dat 去分辨格式。",
        "▢",
        "open_folder",
    ),
    _Template(
        "Open a structure file",
        "開啟結構檔案",
        "Open a .construction, .schem, .schematic, or .mcstructure file.",
        "開啟 .construction、.schem、.schematic 或者 .mcstructure 檔案。",
        "❖",
        "open_structure",
    ),
    _Template(
        "Conversion job",
        "轉換工作",
        "Pair a source and destination world, then merge the chunks across.",
        "配對來源同目的地世界，再將區塊合併過去。",
        "⇄",
        "convert",
    ),
    _Template(
        "Chunk repair",
        "區塊修復",
        "Open a world; pruning and regenerating chunks is the editor's Chunk tool.",
        "開一個世界；修剪同重新生成區塊要用編輯器嘅區塊工具。",
        "▦",
        "chunk_repair",
    ),
    _Template(
        "Classroom kit",
        "課堂套件",
        "Open the settings where School mode and its unlock credential live.",
        "開啟設定，喺嗰度設定課堂模式同解鎖密碼。",
        "✎",
        "school_mode",
    ),
)


class _TemplateCard(_HoverControl):
    """A template tile: a gradient glyph header above a title and a hint."""

    HEADER = 112
    RADIUS = 14
    PADDING_X = 14
    PADDING_TOP = 12
    PADDING_BOTTOM = 14

    def __init__(
        self,
        parent: wx.Window,
        template: _Template,
        *,
        on_click: Optional[Callable[[_Template], None]] = None,
    ) -> None:
        super().__init__(parent, style=wx.BORDER_NONE | wx.WANTS_CHARS)
        self.template = template
        self.on_choose = on_click
        # The title names the card and the hint is the sentence underneath it
        # explaining what the card does -- a name and a message sitting two
        # lines apart, which is why they take different functions.  All five
        # hints are full sentences and all five are also this card's tooltip.
        self.title = studio_label(template.title, template.cantonese_title)
        self.hint = studio_text(template.hint, template.cantonese_hint)
        name = f"{template.title} — {template.hint}"
        if template.unavailable:
            # On the card, in the tooltip, and in the accessible name: a card
            # that cannot do what it says has to say so in all three, because
            # a user reaches it through any one of them.
            self.hint = f"{self.hint}\nNot yet available: {template.unavailable}"
            name += f". Not yet available: {template.unavailable}"
        self._width = 0
        self._setup(name)
        self.SetToolTip(self.hint)
        self.SetInitialSize(self.DoGetBestSize())

    def activate(self, _event: Optional[wx.MouseEvent] = None) -> None:
        widgets.invoke(self.on_choose, self.template)

    def set_available_width(self, width: int) -> None:
        """Re-measure the wrapped hint for a new column width."""
        width = max(0, int(width))
        if width == self._width:
            return
        self._width = width
        self.SetMinSize(self.DoGetBestSize())
        self.Refresh()

    def _body_height(self, dc: wx.DC) -> int:
        available = max(0, self._width - _px(self.PADDING_X * 2))
        dc.SetFont(tokens.font(self, widgets.point_size(14), _MEDIUM))
        title_lines = (
            widgets.wrap_text(dc, self.title, available, max_lines=3)
            if available
            else self.title.split("\n")
        )
        title_height = _line_height(dc, 14, 1.3) * len(title_lines)
        dc.SetFont(tokens.font(self, widgets.point_size(12)))
        hint_lines = (
            widgets.wrap_text(dc, self.hint, available, max_lines=4)
            if available
            else self.hint.split("\n")
        )
        hint_height = _line_height(dc, 12, 1.45) * len(hint_lines)
        return (
            _px(self.PADDING_TOP)
            + title_height
            + _px(4)
            + hint_height
            + _px(self.PADDING_BOTTOM)
        )

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        dc = wx.ClientDC(self)
        return wx.Size(
            max(_px(150), self._width), _px(self.HEADER) + self._body_height(dc)
        )

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        dc, gcdc = widgets.paint_context(self, self.backdrop())
        width, height = self.GetClientSize()
        rect = wx.Rect(0, 0, width, height)
        radius = _px(self.RADIUS)
        border = (
            palette.primary
            if (self._hovered or self._pressed)
            else palette.outline_variant
        )
        tokens.draw_round_rect(gcdc, rect, radius, palette.surface_container, None)
        header = wx.Rect(0, 0, width, _px(self.HEADER))
        context = gcdc.GetGraphicsContext()
        if context is not None:
            _fill_rounded_top(
                context,
                header,
                radius,
                palette.primary_container,
                palette.surface_container_high,
            )
        else:  # pragma: no cover - backend without a graphics context
            dc.GradientFillLinear(
                header,
                palette.primary_container,
                palette.surface_container_high,
                wx.SOUTH,
            )
        gcdc.SetPen(wx.Pen(palette.outline_variant))
        gcdc.DrawLine(0, header.height, width, header.height)
        glyph = self.template.glyph
        gcdc.SetFont(tokens.font(self, widgets.point_size(26)))
        gcdc.SetTextForeground(palette.on_primary_container)
        glyph_width, glyph_height = gcdc.GetTextExtent(glyph)
        gcdc.DrawText(
            glyph, (width - glyph_width) // 2, (header.height - glyph_height) // 2
        )
        available = max(0, width - _px(self.PADDING_X * 2))
        left = _px(self.PADDING_X)
        y = header.height + _px(self.PADDING_TOP)
        gcdc.SetFont(tokens.font(self, widgets.point_size(14), _MEDIUM))
        gcdc.SetTextForeground(palette.on_surface)
        leading = _line_height(gcdc, 14, 1.3)
        for line in widgets.wrap_text(gcdc, self.title, available, max_lines=3):
            gcdc.DrawText(line, left, y)
            y += leading
        y += _px(4)
        gcdc.SetFont(tokens.font(self, widgets.point_size(12)))
        gcdc.SetTextForeground(palette.on_surface_variant)
        leading = _line_height(gcdc, 12, 1.45)
        for line in widgets.wrap_text(gcdc, self.hint, available, max_lines=4):
            gcdc.DrawText(line, left, y)
            y += leading
        tokens.draw_round_rect(gcdc, rect, radius, None, border)
        if self.HasFocus():
            widgets.draw_focus_ring(gcdc, rect, radius, palette.primary)
        del gcdc


# ---------------------------------------------------------------------------
# home: the recent table
# ---------------------------------------------------------------------------
def _recent_columns(width: int) -> List[Tuple[int, int]]:
    """Return the ``(x, width)`` of the table's five columns.

    The design's grid is ``36px 1.6fr 1fr 1fr 120px`` with a 12px gap and 16px
    of padding, and the header and the rows both have to agree about it or the
    columns drift apart as the window is resized.
    """
    gap = _px(12)
    pad = _px(16)
    pin = _px(36)
    opened = _px(120)
    inner = max(0, width - pad * 2)
    flexible = max(0, inner - pin - opened - gap * 4)
    unit = flexible / 3.6 if flexible else 0.0
    name = int(unit * 1.6)
    platform = int(unit)
    location = max(0, flexible - name - platform)
    columns: List[Tuple[int, int]] = []
    x = pad
    for column_width in (pin, name, platform, location, opened):
        columns.append((x, column_width))
        x += column_width + gap
    return columns


class _RecentHeader(wx.Control):
    """The uppercase column header above the recent table."""

    def __init__(self, parent: wx.Window) -> None:
        super().__init__(parent, style=wx.BORDER_NONE)
        self.labels = (
            "",
            studio_label("Name", "名稱"),
            studio_label("Platform", "平台"),
            studio_label("Location", "位置"),
            studio_label("Opened", "開啟時間"),
        )
        self.SetName("Recent projects table columns")
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.SetInitialSize(self.DoGetBestSize())

    def AcceptsFocus(self) -> bool:  # noqa: N802 - wx API spelling
        return False

    def AcceptsFocusFromKeyboard(self) -> bool:  # noqa: N802 - wx API spelling
        return False

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        dc = wx.ClientDC(self)
        dc.SetFont(tokens.font(self, widgets.point_size(11), _MEDIUM))
        lines = max(len(label.split("\n")) for label in self.labels)
        return wx.Size(_px(200), _line_height(dc, 11, 1.35) * lines + _px(20))

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        dc, gcdc = widgets.paint_context(self, palette.surface_container)
        width, height = self.GetClientSize()
        gcdc.SetBrush(wx.Brush(palette.surface_container))
        gcdc.SetPen(wx.TRANSPARENT_PEN)
        gcdc.DrawRectangle(0, 0, width, height)
        gcdc.SetPen(wx.Pen(palette.outline_variant))
        gcdc.DrawLine(0, height - 1, width, height - 1)
        gcdc.SetFont(tokens.font(self, widgets.point_size(11), _MEDIUM))
        gcdc.SetTextForeground(palette.on_surface_variant)
        leading = _line_height(gcdc, 11, 1.35)
        tracking = _px(0.6)
        for (x, column_width), label in zip(_recent_columns(width), self.labels):
            if not label:
                continue
            lines = label.upper().split("\n")
            y = (height - leading * len(lines)) // 2
            for line in lines:
                widgets.draw_tracked_text(
                    gcdc, widgets.elide(gcdc, line, column_width), x, y, tracking
                )
                y += leading
        del gcdc


class _RecentRow(_HoverControl):
    """One project in the recent table, selectable and directly openable.

    A plain click opens the project, exactly as the design says.  Selection is
    an explicit modifier -- Control to add one, Shift to take a range, Space
    from the keyboard -- so a user who only wants to open something never has
    to learn the selection model, and a user running a bulk action never opens
    a world by accident on the way to it.
    """

    def __init__(self, parent: "_RecentTable", entry: RecentEntry, index: int) -> None:
        super().__init__(parent, style=wx.BORDER_NONE | wx.WANTS_CHARS)
        self.table = parent
        self.entry = entry
        self.index = index
        self.selected = False
        self._setup(self._accessible_name())
        self.SetToolTip(
            f"{entry.name} · {entry.kind or 'Project'} · {entry.platform or 'Platform not recorded'}"
            f"\n{entry.path or 'No path recorded'}"
            "\nEnter opens it. Space selects it. Control-click adds to the selection."
        )
        self.SetInitialSize(self.DoGetBestSize())

    def _accessible_name(self) -> str:
        state = "selected" if self.selected else "not selected"
        pinned = "pinned" if self.entry.pinned else "not pinned"
        return (
            f"{self.entry.name}, {self.entry.kind or 'project'}, "
            f"{self.entry.platform or 'platform not recorded'}, "
            f"{self.entry.path or 'no path recorded'}, "
            f"opened {self.entry.opened_label()}, {pinned}, {state}"
        )

    def set_selected(self, selected: bool) -> None:
        """Set the row's selection state and update its accessible name."""
        self.selected = bool(selected)
        self.SetName(self._accessible_name())
        self.Refresh()

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        dc = wx.ClientDC(self)
        dc.SetFont(tokens.font(self, widgets.point_size(14), _MEDIUM))
        name_lines = len(self.entry.name.split("\n"))
        height = _line_height(dc, 14, 1.3) * name_lines
        dc.SetFont(tokens.font(self, widgets.point_size(12)))
        height += _line_height(dc, 12, 1.35)
        return wx.Size(
            _px(200), max(tokens.control_height() + _px(16), height + _px(24))
        )

    # -- interaction ---------------------------------------------------------
    def _pin_rect(self) -> wx.Rect:
        width, height = self.GetClientSize()
        x, column = _recent_columns(width)[0]
        return wx.Rect(x, 0, column + _px(6), height)

    def activate(self, event: Optional[wx.MouseEvent]) -> None:
        if event is not None and self._pin_rect().Contains(event.GetPosition()):
            self.table.toggle_pin(self.index)
            return
        if event is not None and event.ShiftDown():
            self.table.extend_to(self.index)
            return
        if event is not None and (event.ControlDown() or event.CmdDown()):
            self.table.toggle_selection(self.index)
            return
        self.table.open_row(self.index)

    def _on_key_down(self, event: wx.KeyEvent) -> None:
        code = event.GetKeyCode()
        control = event.ControlDown() or event.CmdDown()
        if code == wx.WXK_RETURN:
            self.table.open_row(self.index)
            return
        if code == wx.WXK_SPACE:
            self.table.toggle_selection(self.index)
            return
        if code in (wx.WXK_UP, wx.WXK_DOWN):
            step = -1 if code == wx.WXK_UP else 1
            self.table.move_focus(self.index + step, extend=event.ShiftDown())
            return
        if code == wx.WXK_HOME:
            self.table.move_focus(0, extend=event.ShiftDown())
            return
        if code == wx.WXK_END:
            self.table.move_focus(len(self.table.entries) - 1, extend=event.ShiftDown())
            return
        if control and code in (ord("A"), ord("a")):
            if event.ShiftDown():
                self.table.select_none()
            else:
                self.table.select_all()
            return
        if control and code in (ord("I"), ord("i")):
            self.table.invert_selection()
            return
        if control and code in (ord("P"), ord("p")):
            self.table.toggle_pin(self.index)
            return
        event.Skip()

    # -- painting ------------------------------------------------------------
    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        dc, gcdc = widgets.paint_context(self, palette.surface)
        width, height = self.GetClientSize()
        if self.selected:
            fill = tokens.blend(palette.surface, palette.primary_container, 0.75)
        elif self._pressed:
            fill = palette.surface_container_high
        elif self._hovered:
            fill = palette.surface_container
        else:
            fill = palette.surface
        gcdc.SetBrush(wx.Brush(fill))
        gcdc.SetPen(wx.TRANSPARENT_PEN)
        gcdc.DrawRectangle(0, 0, width, height)
        gcdc.SetPen(wx.Pen(palette.outline_variant))
        gcdc.DrawLine(0, height - 1, width, height - 1)
        columns = _recent_columns(width)
        entry = self.entry
        # pin
        gcdc.SetFont(tokens.font(self, widgets.point_size(14)))
        gcdc.SetTextForeground(palette.primary)
        gcdc.DrawText(
            entry.pin_glyph(), columns[0][0], (height - gcdc.GetCharHeight()) // 2
        )
        # name and kind
        x, column = columns[1]
        gcdc.SetFont(tokens.font(self, widgets.point_size(14), _MEDIUM))
        gcdc.SetTextForeground(palette.on_surface)
        name_leading = _line_height(gcdc, 14, 1.3)
        detail_leading = _line_height(gcdc, 12, 1.35)
        name_lines = entry.name.split("\n")
        total = name_leading * len(name_lines) + detail_leading
        y = max(_px(6), (height - total) // 2)
        for line in name_lines:
            gcdc.DrawText(widgets.elide(gcdc, line, column), x, y)
            y += name_leading
        gcdc.SetFont(tokens.font(self, widgets.point_size(12)))
        gcdc.SetTextForeground(palette.on_surface_variant)
        gcdc.DrawText(widgets.elide(gcdc, entry.kind or "Project", column), x, y)
        # platform
        x, column = columns[2]
        gcdc.SetFont(tokens.font(self, widgets.point_size(13)))
        middle = (height - gcdc.GetCharHeight()) // 2
        gcdc.DrawText(
            widgets.elide(gcdc, entry.platform or "Platform not recorded", column),
            x,
            middle,
        )
        # location, in the monospaced face every path uses
        x, column = columns[3]
        gcdc.SetFont(tokens.mono_font(self, widgets.point_size(12)))
        gcdc.DrawText(
            widgets.elide(gcdc, entry.path or "No path recorded", column),
            x,
            (height - gcdc.GetCharHeight()) // 2,
        )
        # opened
        x, column = columns[4]
        gcdc.SetFont(tokens.font(self, widgets.point_size(12)))
        gcdc.DrawText(
            widgets.elide(gcdc, entry.opened_label(), column),
            x,
            (height - gcdc.GetCharHeight()) // 2,
        )
        if self.HasFocus():
            widgets.draw_focus_ring(
                gcdc, wx.Rect(0, 0, width, height), _px(4), palette.primary
            )
        del gcdc


class _RecentTable(wx.Panel):
    """The bordered recent table: a header, its rows, and its selection model."""

    def __init__(
        self,
        parent: wx.Window,
        *,
        on_open: Optional[Callable[[RecentEntry], None]] = None,
        on_pin: Optional[Callable[[RecentEntry, bool], None]] = None,
        on_selection: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self.on_open = on_open
        self.on_pin = on_pin
        self.on_selection = on_selection
        self.entries: List[RecentEntry] = []
        self.rows: List[_RecentRow] = []
        self._anchor = 0
        self.SetName("Recent projects and worlds")
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.header = _RecentHeader(self)
        self.empty = _Text(
            self,
            studio_text(
                "No projects or worlds have been opened yet. Choose a template "
                "above, or open a world from the Open page.",
                "重未開過任何專案或者世界。可以喺上面揀個範本，或者去「開啟」頁面開一個世界。",
            ),
            size_px=13,
            role="on_surface_variant",
            name="Recent projects empty state",
        )
        self.sizer = wx.BoxSizer(wx.VERTICAL)
        self.sizer.Add(self.header, 0, wx.EXPAND)
        self.sizer.Add(self.empty, 0, wx.EXPAND | wx.ALL, _px(16))
        self.SetSizer(self.sizer)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)

    # -- content -------------------------------------------------------------
    def set_entries(self, entries: Sequence[RecentEntry]) -> None:
        """Replace every row, keeping the selection of records that remain."""
        selected_keys = {entry.key() for entry in self.selection()}
        for row in self.rows:
            self.sizer.Detach(row)
            row.Destroy()
        self.rows = []
        self.entries = list(entries)
        for index, entry in enumerate(self.entries):
            row = _RecentRow(self, entry, index)
            row.set_selected(entry.key() in selected_keys)
            self.rows.append(row)
            self.sizer.Add(row, 0, wx.EXPAND)
        self.empty.Show(not self.entries)
        self._anchor = min(self._anchor, max(0, len(self.entries) - 1))
        self.Layout()
        widgets.invoke(self.on_selection)

    def set_available_width(self, width: int) -> None:
        """Follow the body width so the columns keep the design's proportions."""
        self.empty.set_available_width(max(0, width - _px(32)))

    def selection(self) -> List[RecentEntry]:
        """Return the records the bulk actions would act on."""
        return [row.entry for row in self.rows if row.selected]

    # -- selection -----------------------------------------------------------
    def _changed(self) -> None:
        widgets.invoke(self.on_selection)

    def select_all(self) -> None:
        """Select every row currently in the table."""
        for row in self.rows:
            row.set_selected(True)
        self._changed()

    def select_none(self) -> None:
        """Clear the selection without changing the filter."""
        for row in self.rows:
            row.set_selected(False)
        self._changed()

    def invert_selection(self) -> None:
        """Select what was not selected, and clear what was."""
        for row in self.rows:
            row.set_selected(not row.selected)
        self._changed()

    def toggle_selection(self, index: int) -> None:
        """Add or remove one row from the selection."""
        if not 0 <= index < len(self.rows):
            return
        row = self.rows[index]
        row.set_selected(not row.selected)
        self._anchor = index
        self._changed()

    def extend_to(self, index: int) -> None:
        """Select the inclusive range between the anchor row and ``index``."""
        if not 0 <= index < len(self.rows):
            return
        low, high = sorted((self._anchor, index))
        for position, row in enumerate(self.rows):
            row.set_selected(low <= position <= high)
        self._changed()

    def move_focus(self, index: int, *, extend: bool = False) -> None:
        """Move the keyboard to another row, extending the range on request."""
        if not self.rows:
            return
        index = max(0, min(index, len(self.rows) - 1))
        if extend:
            self.extend_to(index)
        else:
            self._anchor = index
        self.rows[index].SetFocus()

    # -- actions -------------------------------------------------------------
    def open_row(self, index: int) -> None:
        """Open the project on one row."""
        if 0 <= index < len(self.entries):
            self._anchor = index
            widgets.invoke(self.on_open, self.entries[index])

    def toggle_pin(self, index: int) -> None:
        """Pin or unpin one row."""
        if 0 <= index < len(self.entries):
            entry = self.entries[index]
            widgets.invoke(self.on_pin, entry, not entry.pinned)

    def refresh_theme(self) -> None:
        """Repaint the table and every row after an appearance change."""
        for child in self.GetChildren():
            refresh = getattr(child, "refresh_theme", None)
            if callable(refresh):
                refresh()
        self.Refresh()

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        dc, gcdc = widgets.paint_context(self, palette.surface)
        width, height = self.GetClientSize()
        tokens.draw_round_rect(
            gcdc,
            wx.Rect(0, 0, width, height),
            _px(14),
            palette.surface,
            palette.outline_variant,
        )
        del gcdc


# ---------------------------------------------------------------------------
# open: source rows and the advisory
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class _OpenSource:
    """One route into a world or project on the Open page."""

    key: str
    title: str
    cantonese_title: str
    hint: str
    cantonese_hint: str
    glyph: str


OPEN_SOURCES: Tuple[_OpenSource, ...] = (
    _OpenSource(
        "folder",
        "Browse for a world folder",
        "瀏覽世界資料夾",
        "Point Amulet at a save directory. It reads level.dat to identify the format.",
        "揀一個存檔資料夾。Amulet 會讀 level.dat 去分辨格式。",
        "▤",
    ),
    _OpenSource(
        "install",
        "Pick from a detected Minecraft install",
        "喺偵測到嘅 Minecraft 安裝入面揀",
        "Choose one of the worlds found in the Java and Bedrock installations on this machine.",
        "喺呢部機搵到嘅 Java 同 Bedrock 安裝入面揀一個世界。",
        "▦",
    ),
    _OpenSource(
        "structure",
        "Open a structure file",
        "開啟結構檔案",
        "Load a .construction, .schem, .schematic, or .mcstructure file as a project.",
        "將 .construction、.schem、.schematic 或者 .mcstructure 檔案當成專案開啟。",
        "❖",
    ),
    _OpenSource(
        "recent",
        "Open a recent project",
        "開啟最近嘅專案",
        "Reopen a project from the recent list without browsing for it again.",
        "喺最近清單度直接開返專案，唔使再搵一次路徑。",
        "⟲",
    ),
)


class _SourceRow(_HoverControl):
    """One tall Open-page row: a glyph tile, a title, a hint, and a chevron."""

    PADDING = 16
    TILE = 40
    RADIUS = 14
    GAP = 16

    def __init__(
        self,
        parent: wx.Window,
        source: _OpenSource,
        *,
        on_click: Optional[Callable[[_OpenSource], None]] = None,
    ) -> None:
        super().__init__(parent, style=wx.BORDER_NONE | wx.WANTS_CHARS)
        self.source = source
        self.on_choose = on_click
        # Same split as ``_TemplateCard``: the row's title names it, the hint
        # below is the application explaining it and keeps its tone.
        self.title = studio_label(source.title, source.cantonese_title)
        self.hint = studio_text(source.hint, source.cantonese_hint)
        self._width = 0
        self._setup(f"{source.title} — {source.hint}")
        self.SetToolTip(self.hint)
        self.SetInitialSize(self.DoGetBestSize())

    def activate(self, _event: Optional[wx.MouseEvent] = None) -> None:
        widgets.invoke(self.on_choose, self.source)

    def set_available_width(self, width: int) -> None:
        """Re-measure the wrapped hint for a new container width."""
        width = max(0, int(width))
        if width == self._width:
            return
        self._width = width
        self.SetMinSize(self.DoGetBestSize())
        self.Refresh()

    def _text_width(self) -> int:
        return max(
            0,
            self._width
            - _px(self.PADDING * 2)
            - _px(self.TILE)
            - _px(self.GAP) * 2
            - _px(18),
        )

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        dc = wx.ClientDC(self)
        available = self._text_width()
        dc.SetFont(tokens.font(self, widgets.point_size(15), _MEDIUM))
        title_lines = (
            widgets.wrap_text(dc, self.title, available, max_lines=3)
            if available
            else self.title.split("\n")
        )
        height = _line_height(dc, 15, 1.3) * len(title_lines) + _px(3)
        dc.SetFont(tokens.font(self, widgets.point_size(13)))
        hint_lines = (
            widgets.wrap_text(dc, self.hint, available, max_lines=4)
            if available
            else self.hint.split("\n")
        )
        height += _line_height(dc, 13, 1.45) * len(hint_lines)
        return wx.Size(
            max(_px(320), self._width),
            max(_px(self.TILE) + _px(self.PADDING * 2), height + _px(self.PADDING * 2)),
        )

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        dc, gcdc = widgets.paint_context(self, self.backdrop())
        width, height = self.GetClientSize()
        rect = wx.Rect(0, 0, width, height)
        radius = _px(self.RADIUS)
        hovered = self._hovered or self._pressed
        fill = (
            tokens.blend(palette.surface_container, palette.primary, 0.06)
            if self._pressed
            else palette.surface_container
        )
        tokens.draw_round_rect(
            gcdc,
            rect,
            radius,
            fill,
            palette.primary if hovered else palette.outline_variant,
        )
        tile = wx.Rect(
            _px(self.PADDING),
            (height - _px(self.TILE)) // 2,
            _px(self.TILE),
            _px(self.TILE),
        )
        tokens.draw_round_rect(gcdc, tile, _px(10), palette.primary_container, None)
        glyph = self.source.glyph
        gcdc.SetFont(tokens.font(self, widgets.point_size(17)))
        gcdc.SetTextForeground(palette.on_primary_container)
        glyph_width, glyph_height = gcdc.GetTextExtent(glyph)
        gcdc.DrawText(
            glyph,
            tile.x + (tile.width - glyph_width) // 2,
            tile.y + (tile.height - glyph_height) // 2,
        )
        left = tile.x + tile.width + _px(self.GAP)
        available = self._text_width()
        gcdc.SetFont(tokens.font(self, widgets.point_size(15), _MEDIUM))
        title_lines = widgets.wrap_text(gcdc, self.title, available, max_lines=3)
        title_leading = _line_height(gcdc, 15, 1.3)
        gcdc.SetFont(tokens.font(self, widgets.point_size(13)))
        hint_lines = widgets.wrap_text(gcdc, self.hint, available, max_lines=4)
        hint_leading = _line_height(gcdc, 13, 1.45)
        total = (
            title_leading * len(title_lines) + _px(3) + hint_leading * len(hint_lines)
        )
        y = max(_px(self.PADDING), (height - total) // 2)
        gcdc.SetFont(tokens.font(self, widgets.point_size(15), _MEDIUM))
        gcdc.SetTextForeground(palette.on_surface)
        for line in title_lines:
            gcdc.DrawText(line, left, y)
            y += title_leading
        y += _px(3)
        gcdc.SetFont(tokens.font(self, widgets.point_size(13)))
        gcdc.SetTextForeground(palette.on_surface_variant)
        for line in hint_lines:
            gcdc.DrawText(line, left, y)
            y += hint_leading
        gcdc.SetFont(tokens.font(self, widgets.point_size(18)))
        gcdc.SetTextForeground(palette.on_surface_variant)
        chevron = "›"
        chevron_width, chevron_height = gcdc.GetTextExtent(chevron)
        gcdc.DrawText(
            chevron,
            width - _px(self.PADDING) - chevron_width,
            (height - chevron_height) // 2,
        )
        if self.HasFocus():
            widgets.draw_focus_ring(gcdc, rect, radius, palette.primary)
        del gcdc


class _Advisory(wx.Control):
    """The backup warning: a tinted block behind a three-pixel error edge."""

    PADDING_X = 16
    PADDING_Y = 14
    EDGE = 3

    def __init__(self, parent: wx.Window, text: str, *, name: str = "") -> None:
        super().__init__(parent, style=wx.BORDER_NONE)
        self.text = str(text)
        self._width = 0
        self._lines: List[str] = self.text.split("\n")
        self.SetName(name or self.text.replace("\n", " "))
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.SetInitialSize(self.DoGetBestSize())

    def AcceptsFocus(self) -> bool:  # noqa: N802 - wx API spelling
        return False

    def AcceptsFocusFromKeyboard(self) -> bool:  # noqa: N802 - wx API spelling
        return False

    def set_available_width(self, width: int) -> None:
        """Re-wrap the advisory for a new container width."""
        width = max(0, int(width))
        if width == self._width:
            return
        self._width = width
        self.SetMinSize(self.DoGetBestSize())
        self.Refresh()

    def _text_width(self) -> int:
        return max(0, self._width - _px(self.PADDING_X * 2) - _px(self.EDGE))

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        dc = wx.ClientDC(self)
        dc.SetFont(tokens.font(self, widgets.point_size(13)))
        available = self._text_width()
        self._lines = (
            widgets.wrap_text(dc, self.text, available, max_lines=8)
            if available
            else self.text.split("\n")
        )
        height = _line_height(dc, 13, 1.55) * len(self._lines)
        return wx.Size(max(_px(320), self._width), height + _px(self.PADDING_Y * 2))

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        dc, gcdc = widgets.paint_context(self, self.backdrop_colour())
        width, height = self.GetClientSize()
        tokens.draw_round_rect(
            gcdc,
            wx.Rect(0, 0, width, height),
            _px(12),
            palette.surface_container_high,
            None,
        )
        gcdc.SetBrush(wx.Brush(palette.error))
        gcdc.SetPen(wx.TRANSPARENT_PEN)
        gcdc.DrawRectangle(0, _px(4), _px(self.EDGE), max(0, height - _px(8)))
        gcdc.SetFont(tokens.font(self, widgets.point_size(13)))
        gcdc.SetTextForeground(palette.on_surface)
        leading = _line_height(gcdc, 13, 1.55)
        left = _px(self.EDGE) + _px(self.PADDING_X)
        y = _px(self.PADDING_Y)
        for line in widgets.wrap_text(gcdc, self.text, self._text_width(), max_lines=8):
            gcdc.DrawText(line, left, y)
            y += leading
        del gcdc

    def backdrop_colour(self) -> wx.Colour:
        parent = self.GetParent()
        colour = parent.GetBackgroundColour() if parent is not None else wx.NullColour
        return colour if colour.IsOk() else tokens.palette().surface


# ---------------------------------------------------------------------------
# info: rows and measurement
# ---------------------------------------------------------------------------
class _InfoRow(wx.Control):
    """One label-and-value row on the Project info page."""

    PADDING_X = 16
    PADDING_Y = 12
    LABEL_COLUMN = 180
    GAP = 16
    RADIUS = 12

    def __init__(self, parent: wx.Window, label: str, value: str) -> None:
        super().__init__(parent, style=wx.BORDER_NONE)
        self.label = str(label)
        self.value = str(value)
        self._width = 0
        self.SetName(f"{self.label}: {self.value}")
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.SetInitialSize(self.DoGetBestSize())

    def AcceptsFocus(self) -> bool:  # noqa: N802 - wx API spelling
        return False

    def AcceptsFocusFromKeyboard(self) -> bool:  # noqa: N802 - wx API spelling
        return False

    def set_value(self, value: str) -> None:
        """Replace the value once a measurement or lookup has finished."""
        self.value = str(value)
        self.SetName(f"{self.label}: {self.value}")
        self.SetMinSize(self.DoGetBestSize())
        parent = self.GetParent()
        if parent is not None:
            parent.Layout()
        self.Refresh()

    def set_available_width(self, width: int) -> None:
        """Re-wrap the value column for a new container width."""
        width = max(0, int(width))
        if width == self._width:
            return
        self._width = width
        self.SetMinSize(self.DoGetBestSize())
        self.Refresh()

    def _value_width(self) -> int:
        return max(
            0,
            self._width
            - _px(self.PADDING_X * 2)
            - _px(self.LABEL_COLUMN)
            - _px(self.GAP),
        )

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        dc = wx.ClientDC(self)
        dc.SetFont(tokens.mono_font(self, widgets.point_size(13)))
        available = self._value_width()
        lines = (
            widgets.wrap_text(dc, self.value, available, max_lines=4)
            if available
            else [self.value]
        )
        value_height = _line_height(dc, 13, 1.4) * len(lines)
        dc.SetFont(tokens.font(self, widgets.point_size(13)))
        label_height = _line_height(dc, 13, 1.4) * len(self.label.split("\n"))
        return wx.Size(
            max(_px(320), self._width),
            max(value_height, label_height) + _px(self.PADDING_Y * 2),
        )

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        parent = self.GetParent()
        colour = parent.GetBackgroundColour() if parent is not None else wx.NullColour
        dc, gcdc = widgets.paint_context(
            self, colour if colour.IsOk() else palette.surface
        )
        width, height = self.GetClientSize()
        tokens.draw_round_rect(
            gcdc,
            wx.Rect(0, 0, width, height),
            _px(self.RADIUS),
            palette.surface_container,
            palette.outline_variant,
        )
        gcdc.SetFont(tokens.font(self, widgets.point_size(13)))
        gcdc.SetTextForeground(palette.on_surface_variant)
        leading = _line_height(gcdc, 13, 1.4)
        y = _px(self.PADDING_Y)
        for line in self.label.split("\n"):
            gcdc.DrawText(
                widgets.elide(gcdc, line, _px(self.LABEL_COLUMN)),
                _px(self.PADDING_X),
                y,
            )
            y += leading
        gcdc.SetFont(tokens.mono_font(self, widgets.point_size(13)))
        gcdc.SetTextForeground(palette.on_surface)
        left = _px(self.PADDING_X) + _px(self.LABEL_COLUMN) + _px(self.GAP)
        y = _px(self.PADDING_Y)
        for line in widgets.wrap_text(
            gcdc, self.value, self._value_width(), max_lines=4
        ):
            gcdc.DrawText(line, left, y)
            y += leading
        del gcdc


@dataclass(frozen=True)
class ProjectMeasurement:
    """What a bounded walk of a project directory actually established."""

    exists: bool
    total_bytes: int
    files: int
    chunks: int
    region_files: int
    complete: bool
    error: str = ""

    def size_label(self) -> str:
        """Return the size row's value, stating when the walk was cut short."""
        if not self.exists:
            return "Not on disk yet"
        if self.error:
            return f"Not measured — {self.error}"
        size = _format_bytes(self.total_bytes)
        if self.complete:
            return f"{size} across {self.files:,} files"
        return (
            f"over {size} — measurement stopped after {self.files:,} files "
            f"so the screen would not stall"
        )

    def chunk_label(self) -> str:
        """Return the chunk row's value, counted from the region headers."""
        if not self.exists:
            return "Not on disk yet"
        if self.error:
            return f"Not counted — {self.error}"
        if not self.region_files:
            return "No region files found — nothing to count"
        counted = f"{self.chunks:,} stored in {self.region_files:,} region files"
        return counted if self.complete else f"at least {counted}"


def _measure_project(
    path: str,
    *,
    file_limit: int = MEASURE_FILE_LIMIT,
    region_limit: int = MEASURE_REGION_LIMIT,
    seconds: float = MEASURE_SECONDS,
) -> ProjectMeasurement:
    """Walk a project directory for its size and its stored chunk count.

    Both numbers are read from the files themselves rather than guessed, and
    both bounds are reported rather than hidden: a figure that silently stopped
    counting halfway is worse than one that says where it stopped.
    """
    root = Path(path).expanduser()
    try:
        if not root.exists():
            return ProjectMeasurement(False, 0, 0, 0, 0, True)
        if root.is_file():
            size = root.stat().st_size
            return ProjectMeasurement(True, size, 1, 0, 0, True)
    except OSError as error:
        return ProjectMeasurement(False, 0, 0, 0, 0, True, str(error))
    deadline = time.monotonic() + max(0.5, float(seconds))
    total = 0
    files = 0
    chunks = 0
    regions = 0
    complete = True
    try:
        for directory, _subdirectories, names in os.walk(root):
            if time.monotonic() > deadline or files >= file_limit:
                complete = False
                break
            for name in names:
                if files >= file_limit:
                    complete = False
                    break
                target = os.path.join(directory, name)
                try:
                    total += os.path.getsize(target)
                except OSError:
                    continue
                files += 1
                if name.lower().endswith((".mca", ".mcr")) and regions < region_limit:
                    regions += 1
                    chunks += _count_region_chunks(target)
                elif name.lower().endswith((".mca", ".mcr")):
                    complete = False
    except OSError as error:
        return ProjectMeasurement(
            True, total, files, chunks, regions, False, str(error)
        )
    return ProjectMeasurement(True, total, files, chunks, regions, complete)


def _count_region_chunks(path: str) -> int:
    """Count the chunks a region file actually stores, from its 4 KiB header.

    Each of the 1024 header entries is a three-byte offset and a one-byte
    length; a non-zero entry means that chunk was written.  Reading the header
    is exact and costs one small read, whereas estimating from the file size
    would report chunks that were never generated.
    """
    try:
        with open(path, "rb") as stream:
            header = stream.read(4096)
    except OSError:
        return 0
    if len(header) < 4096:
        return 0
    return sum(
        1
        for index in range(0, 4096, 4)
        if header[index : index + 4] != b"\x00\x00\x00\x00"
    )


def _count_revisions(project_key: str) -> str:
    """Return how many history revisions exist for a project, honestly.

    The per-project repository is the workspace's own; what this can prove is
    how many events the application's local history holds for this project, so
    that is what it says.
    """
    if not project_key:
        return "No project open"
    try:
        from amulet_map_editor.api import local_history

        store = local_history.LocalHistory.try_create()
        if store is None:
            return "Local history is unavailable on this machine"
        events = store.events(project_key, limit=10_000)
    except Exception:  # pragma: no cover - history is best-effort
        log.debug("Could not read the project revision count", exc_info=True)
        return "Local history could not be read"
    count = len(events)
    if not count:
        return "No revisions recorded yet"
    return f"{count:,} recorded" if count != 1 else "1 recorded"


# ---------------------------------------------------------------------------
# convert: the world cards
# ---------------------------------------------------------------------------
class _WorldTile(wx.Control):
    """The 96x56 world thumbnail, or the labelled placeholder standing in.

    A world that carries its own icon file shows it.  A world that does not
    shows the words "world icon" in the monospaced face, because a generated
    picture pretending to be the world's own would be a lie told in pixels.
    """

    WIDTH = 96
    HEIGHT = 56

    def __init__(self, parent: wx.Window, path: str = "") -> None:
        super().__init__(parent, style=wx.BORDER_NONE)
        self._bitmap: Optional[wx.Bitmap] = None
        self.SetName("World icon")
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.set_path(path)
        self.SetInitialSize(self.DoGetBestSize())

    def AcceptsFocus(self) -> bool:  # noqa: N802 - wx API spelling
        return False

    def AcceptsFocusFromKeyboard(self) -> bool:  # noqa: N802 - wx API spelling
        return False

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        return wx.Size(_px(self.WIDTH), _px(self.HEIGHT))

    def set_path(self, path: str) -> None:
        """Load the world's own icon from disk, or fall back to the label."""
        self._bitmap = None
        root = Path(str(path)).expanduser() if path else None
        if root is None:
            self.SetName("World icon placeholder")
            self.Refresh()
            return
        for name in WORLD_ICON_NAMES:
            candidate = root / name
            try:
                if not candidate.is_file():
                    continue
                image = wx.Image(str(candidate))
                if not image.IsOk():
                    continue
                image = image.Scale(
                    _px(self.WIDTH), _px(self.HEIGHT), wx.IMAGE_QUALITY_HIGH
                )
                self._bitmap = wx.Bitmap(image)
                self.SetName(f"World icon from {candidate.name}")
                break
            except (OSError, RuntimeError):
                continue
        if self._bitmap is None:
            self.SetName("World icon placeholder")
        self.Refresh()

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        parent = self.GetParent()
        colour = parent.GetBackgroundColour() if parent is not None else wx.NullColour
        dc, gcdc = widgets.paint_context(
            self, colour if colour.IsOk() else palette.surface
        )
        width, height = self.GetClientSize()
        rect = wx.Rect(0, 0, width, height)
        if self._bitmap is not None and self._bitmap.IsOk():
            gcdc.DrawBitmap(self._bitmap, 0, 0, True)
            tokens.draw_round_rect(gcdc, rect, _px(9), None, palette.outline_variant)
            del gcdc
            return
        tokens.draw_round_rect(
            gcdc,
            rect,
            _px(9),
            palette.surface_container_high,
            palette.outline_variant,
        )
        gcdc.SetFont(tokens.mono_font(self, widgets.point_size(10)))
        gcdc.SetTextForeground(palette.on_surface_variant)
        label = widgets.elide(gcdc, "world icon", width - _px(8))
        text_width, text_height = gcdc.GetTextExtent(label)
        gcdc.DrawText(label, (width - text_width) // 2, (height - text_height) // 2)
        del gcdc


class _EmptySlot(wx.Control):
    """The dashed "nothing chosen yet" block the Convert page uses."""

    PADDING = 20

    def __init__(self, parent: wx.Window, text: str) -> None:
        super().__init__(parent, style=wx.BORDER_NONE)
        self.text = str(text)
        self.SetName(self.text.replace("\n", " "))
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.SetInitialSize(self.DoGetBestSize())

    def AcceptsFocus(self) -> bool:  # noqa: N802 - wx API spelling
        return False

    def AcceptsFocusFromKeyboard(self) -> bool:  # noqa: N802 - wx API spelling
        return False

    def set_text(self, text: str) -> None:
        """Replace the empty-state sentence."""
        self.text = str(text)
        self.SetName(self.text.replace("\n", " "))
        self.SetMinSize(self.DoGetBestSize())
        self.Refresh()

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        dc = wx.ClientDC(self)
        dc.SetFont(tokens.font(self, widgets.point_size(13)))
        lines = self.text.split("\n")
        return wx.Size(
            _px(320), _line_height(dc, 13, 1.4) * len(lines) + _px(self.PADDING * 2)
        )

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        parent = self.GetParent()
        colour = parent.GetBackgroundColour() if parent is not None else wx.NullColour
        dc, gcdc = widgets.paint_context(
            self, colour if colour.IsOk() else palette.surface
        )
        width, height = self.GetClientSize()
        widgets.draw_dashed_round_rect(
            gcdc, wx.Rect(0, 0, width - 1, height - 1), _px(12), palette.outline
        )
        gcdc.SetFont(tokens.font(self, widgets.point_size(13)))
        gcdc.SetTextForeground(palette.on_surface_variant)
        lines = self.text.split("\n")
        leading = _line_height(gcdc, 13, 1.4)
        y = (height - leading * len(lines)) // 2
        for line in lines:
            text = widgets.elide(gcdc, line, width - _px(16))
            gcdc.DrawText(text, (width - gcdc.GetTextExtent(text)[0]) // 2, y)
            y += leading
        del gcdc


# ---------------------------------------------------------------------------
# all surfaces
# ---------------------------------------------------------------------------
class _SurfaceCard(_HoverControl):
    """One surface in the All-surfaces index: a label above its own hint."""

    PADDING_X = 14
    PADDING_Y = 12
    RADIUS = 12

    def __init__(
        self,
        parent: wx.Window,
        key: str,
        label: str,
        hint: str,
        *,
        on_click: Optional[Callable[[str], None]] = None,
    ) -> None:
        super().__init__(parent, style=wx.BORDER_NONE | wx.WANTS_CHARS)
        self.key = str(key)
        self.label = str(label)
        self.hint = str(hint)
        self.on_open = on_click
        self._width = 0
        self._setup(f"{self.label} — {self.hint}")
        self.SetToolTip(self.hint)
        self.SetInitialSize(self.DoGetBestSize())

    def activate(self, _event: Optional[wx.MouseEvent] = None) -> None:
        widgets.invoke(self.on_open, self.key)

    def set_available_width(self, width: int) -> None:
        """Re-measure the wrapped hint for a new column width."""
        width = max(0, int(width))
        if width == self._width:
            return
        self._width = width
        self.SetMinSize(self.DoGetBestSize())
        self.Refresh()

    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - wx API spelling
        dc = wx.ClientDC(self)
        available = max(0, self._width - _px(self.PADDING_X * 2))
        dc.SetFont(tokens.font(self, widgets.point_size(13), _MEDIUM))
        label_lines = (
            widgets.wrap_text(dc, self.label, available, max_lines=2)
            if available
            else [self.label]
        )
        height = _line_height(dc, 13, 1.3) * len(label_lines) + _px(3)
        dc.SetFont(tokens.font(self, widgets.point_size(12)))
        hint_lines = (
            widgets.wrap_text(dc, self.hint, available, max_lines=3)
            if available
            else [self.hint]
        )
        height += _line_height(dc, 12, 1.45) * len(hint_lines)
        return wx.Size(max(_px(180), self._width), height + _px(self.PADDING_Y * 2))

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        dc, gcdc = widgets.paint_context(self, self.backdrop())
        width, height = self.GetClientSize()
        rect = wx.Rect(0, 0, width, height)
        radius = _px(self.RADIUS)
        hovered = self._hovered or self._pressed
        tokens.draw_round_rect(
            gcdc,
            rect,
            radius,
            palette.surface_container,
            palette.primary if hovered else palette.outline_variant,
        )
        available = max(0, width - _px(self.PADDING_X * 2))
        left = _px(self.PADDING_X)
        y = _px(self.PADDING_Y)
        gcdc.SetFont(tokens.font(self, widgets.point_size(13), _MEDIUM))
        gcdc.SetTextForeground(palette.on_surface)
        leading = _line_height(gcdc, 13, 1.3)
        for line in widgets.wrap_text(gcdc, self.label, available, max_lines=2):
            gcdc.DrawText(line, left, y)
            y += leading
        y += _px(3)
        gcdc.SetFont(tokens.font(self, widgets.point_size(12)))
        gcdc.SetTextForeground(palette.on_surface_variant)
        leading = _line_height(gcdc, 12, 1.45)
        for line in widgets.wrap_text(gcdc, self.hint, available, max_lines=3):
            gcdc.DrawText(line, left, y)
            y += leading
        if self.HasFocus():
            widgets.draw_focus_ring(gcdc, rect, radius, palette.primary)
        del gcdc


# ---------------------------------------------------------------------------
# world discovery
# ---------------------------------------------------------------------------
#: ``select_world.find_world_paths`` clears and refills one module-level list
#: in place, so two scans running at once can leave one of them reading a list
#: the other has just emptied.  The symptom is a machine that plainly has a
#: Minecraft installation being told it has none, on some runs and not others,
#: which is worse than a slow scan.  One lock makes discovery a single reader.
_DISCOVERY_LOCK = threading.Lock()


def minecraft_save_roots() -> List[Tuple[str, Path]]:
    """Return the save directories this machine's installations actually have.

    The discovery itself belongs to
    :mod:`amulet_map_editor.api.wx.ui.select_world`, which already knows about
    the Java launcher, every Bedrock edition including the Education, Netease,
    and GDK builds, and the per-profile layouts Modrinth and CurseForge use.
    Deriving the list a second time here would produce a shorter answer that
    quietly disagreed with the one the rest of the application uses, so this
    asks that module and reports only the directories that exist.
    """
    from amulet_map_editor.api.wx.ui import select_world

    with _DISCOVERY_LOCK:
        try:
            select_world.find_world_paths()
            discovered = list(select_world.minecraft_world_paths)
        except Exception:  # pragma: no cover - a profile this host cannot read
            log.exception("The installed Minecraft directories could not be listed")
            return []
    roots: List[Tuple[str, Path]] = []
    seen: List[Path] = []
    for group, directory in discovered:
        try:
            path = Path(directory).expanduser()
            if path in seen or not path.is_dir():
                continue
        except (OSError, RuntimeError):
            continue
        seen.append(path)
        roots.append((str(group), path))
    return roots


@dataclass(frozen=True)
class DetectedWorld:
    """One world found in an installation on this machine.

    Every field is read from the world itself through the same loader the
    editor opens it with, so a world listed here is a world Amulet can open.
    """

    name: str
    path: str
    platform: str
    version: str = ""
    group: str = ""
    last_played: int = 0

    def haystack(self) -> str:
        """Return the text a search field matches this world against."""
        return f"{self.name} {self.platform} {self.version} {self.group} {self.path}"

    def detail(self) -> str:
        """Return the second line a list row shows for this world."""
        played = _format_timestamp(self.last_played)
        parts = [part for part in (self.version, self.group) if part]
        if played:
            parts.append(f"last played {played}")
        return " · ".join(parts) or self.path


@dataclass(frozen=True)
class WorldScan:
    """What one pass over the installed save directories established."""

    worlds: Tuple[DetectedWorld, ...] = ()
    roots: Tuple[Tuple[str, Path], ...] = ()
    skipped: int = 0
    truncated: bool = False
    error: str = ""

    def summary(self) -> str:
        """Return the sentence stating what was read and what was not."""
        if self.error:
            return (
                f"The installed Minecraft directories could not be read: {self.error}"
            )
        if not self.roots:
            return (
                "No Minecraft installation was found on this machine, so there "
                "is nothing to list. Browse for a world folder instead."
            )
        found = (
            f"{len(self.worlds)} world{'' if len(self.worlds) == 1 else 's'} found in "
            f"{len(self.roots)} save "
            f"{'directory' if len(self.roots) == 1 else 'directories'}"
        )
        if self.truncated:
            found += f", stopped at {MAX_DETECTED_WORLDS:,}"
        if self.skipped:
            found += (
                f". {self.skipped} folder{'' if self.skipped == 1 else 's'} "
                "matched no loader and cannot be opened here"
            )
        return found + "."

    def roots_text(self) -> str:
        """Return the directories that were read, one per line."""
        return "\n".join(f"{group} — {path}" for group, path in self.roots)


def _format_timestamp(seconds: int) -> str:
    """Return an epoch time as a local date, or ``""`` when it is not recorded."""
    if not seconds:
        return ""
    try:
        return datetime.fromtimestamp(int(seconds)).strftime("%d %b %Y, %H:%M")
    except (OSError, OverflowError, TypeError, ValueError):
        return ""


def detect_worlds(limit: int = MAX_DETECTED_WORLDS) -> WorldScan:
    """Return every world Amulet can open in this machine's installations.

    Each candidate directory is identified by ``amulet.load_format``, which is
    the same call the editor makes when it opens a world, so the name, version,
    and platform shown are the world's own rather than a guess made from which
    folder it was sitting in.  A directory no loader matches is counted and
    reported rather than listed, because offering to open something that cannot
    be opened is worse than saying it was skipped.

    This walks and reads every save directory on the machine, so it belongs on
    a worker thread rather than on the thread drawing the screen.
    """
    roots = minecraft_save_roots()
    if not roots:
        return WorldScan()
    from amulet import load_format

    found: List[DetectedWorld] = []
    skipped = 0
    truncated = False
    for group, root in roots:
        try:
            children = sorted(root.iterdir())
        except OSError:
            continue
        for child in children:
            if len(found) >= max(1, int(limit)):
                truncated = True
                break
            try:
                if not child.is_dir():
                    continue
            except OSError:
                continue
            try:
                world_format = load_format(str(child))
            except Exception:  # noqa: BLE001 - any unloadable folder lands here
                skipped += 1
                continue
            try:
                found.append(
                    DetectedWorld(
                        name=str(world_format.level_name) or child.name,
                        path=str(child),
                        platform=str(world_format.platform).title(),
                        version=str(world_format.game_version_string),
                        group=group,
                        last_played=int(world_format.last_played or 0),
                    )
                )
            except Exception:  # noqa: BLE001 - a wrapper that will not describe itself
                skipped += 1
    found.sort(key=lambda world: (-world.last_played, world.name.lower()))
    return WorldScan(
        worlds=tuple(found),
        roots=tuple(roots),
        skipped=skipped,
        truncated=truncated,
    )


class _WorldPickerDialog(wx.Dialog):
    """A searchable list of the worlds found in this machine's installations."""

    def __init__(self, parent: wx.Window, scan: Optional[WorldScan] = None) -> None:
        super().__init__(
            parent,
            title=studio_label("Choose a world", "揀一個世界"),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.chosen: Optional[DetectedWorld] = None
        # The scan reads every save directory on the machine and asks a loader
        # to identify each world, so it is handed in when the Open page has
        # already done it and run on a worker thread when it has not.  Doing it
        # here on the dialog's own thread is what would make opening the picker
        # feel like the application had hung.
        self._scan = scan
        self.state = SearchState(label="Detected worlds")
        palette = tokens.palette()
        self.SetBackgroundColour(palette.surface)
        root = wx.BoxSizer(wx.VERTICAL)
        self.summary = _Text(
            self,
            self._summary_text(),
            size_px=13,
            role="on_surface_variant",
            wrap_width=_px(560),
            name="Detected worlds summary",
        )
        root.Add(self.summary, 0, wx.EXPAND | wx.ALL, _px(16))
        self.search = widgets.SearchBar(
            self,
            "Search detected worlds",
            self.state,
            on_change=lambda _state: self._refill(),
            compact=True,
        )
        self.search.SetBackgroundStyle(wx.BG_STYLE_SYSTEM)
        self.search.SetBackgroundColour(palette.surface)
        root.Add(self.search, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, _px(16))
        self.list_panel = wx.ScrolledWindow(self, style=wx.TAB_TRAVERSAL | wx.VSCROLL)
        self.list_panel.SetScrollRate(0, _px(12))
        self.list_panel.SetBackgroundColour(palette.surface)
        self.list_panel.SetName("Detected worlds")
        self.list_sizer = wx.BoxSizer(wx.VERTICAL)
        self.list_panel.SetSizer(self.list_sizer)
        root.Add(self.list_panel, 1, wx.EXPAND | wx.ALL, _px(16))
        buttons = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        root.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, _px(16))
        self.SetSizer(root)
        self.SetSize(wx.Size(_px(640), _px(560)))
        self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)
        self._refill()
        if self._scan is None:
            threading.Thread(
                target=self._scan_worker, name="amulet-studio-world-scan", daemon=True
            ).start()

    def _summary_text(self) -> str:
        if self._scan is None:
            return studio_text(
                "Reading the installed Minecraft directories…",
                "讀緊已安裝嘅 Minecraft 資料夾…",
            )
        text = self._scan.summary()
        roots = self._scan.roots_text()
        if not self._scan.worlds and roots:
            text += "\nThese directories were read:\n" + roots
        return text

    def _scan_worker(self) -> None:
        try:
            scan = detect_worlds()
        except Exception as error:  # noqa: BLE001 - report it rather than hang
            log.exception("The installed worlds could not be scanned")
            scan = WorldScan(error=str(error))
        wx.CallAfter(self._apply_scan, scan)

    def _apply_scan(self, scan: WorldScan) -> None:
        try:
            if self.IsBeingDeleted():
                return
        except RuntimeError:  # pragma: no cover - the dialog has already gone
            return
        self._scan = scan
        self.summary.set_text(self._summary_text())
        self._refill()
        self.Layout()

    def _worlds(self) -> Tuple[DetectedWorld, ...]:
        return () if self._scan is None else self._scan.worlds

    def _refill(self) -> None:
        self.list_sizer.Clear(delete_windows=True)
        if self._scan is None:
            self.list_sizer.Add(
                _Text(
                    self.list_panel,
                    studio_text(
                        "Reading the installed worlds. Each one is identified by "
                        "the same loader the editor opens it with.",
                        "讀緊已安裝嘅世界，每個都用編輯器開世界嗰個載入器去辨認。",
                    ),
                    size_px=13,
                    role="on_surface_variant",
                    wrap_width=_px(560),
                    name="Detected worlds progress",
                ),
                0,
                wx.EXPAND | wx.BOTTOM,
                _px(8),
            )
            self.list_panel.Layout()
            self.list_panel.FitInside()
            return
        matches = [
            world for world in self._worlds() if self.state.matches(world.haystack())
        ]
        if not matches:
            self.list_sizer.Add(
                _Text(
                    self.list_panel,
                    self.state.describe_matches(0, "world"),
                    size_px=13,
                    role="on_surface_variant",
                    name="Detected worlds result count",
                ),
                0,
                wx.EXPAND | wx.BOTTOM,
                _px(8),
            )
        for world in matches:
            row = widgets.ListRow(
                self.list_panel,
                world.name,
                world.detail(),
                world.platform,
                on_click=lambda chosen=world: self._choose(chosen),
            )
            row.SetToolTip(f"{world.name}\n{world.path}")
            self.list_sizer.Add(row, 0, wx.EXPAND | wx.BOTTOM, _px(4))
        self.list_panel.Layout()
        self.list_panel.FitInside()

    def _choose(self, world: DetectedWorld) -> None:
        self.chosen = world
        self.EndModal(wx.ID_OK)

    def _on_ok(self, event: wx.CommandEvent) -> None:
        worlds = self._worlds()
        if self.chosen is None and worlds:
            self.chosen = worlds[0]
        event.Skip()


# ---------------------------------------------------------------------------
# bulk preview and the destructive gate
# ---------------------------------------------------------------------------
class _BulkPreviewDialog(wx.Dialog):
    """The reviewable preview every bulk action shows before it runs.

    The count and the list are the point: a bulk action that says "3 items" and
    acts on eleven is the failure this surface exists to prevent.  A
    destructive action gets the two-key gate instead of a confirm button, so
    removing records takes a deliberate act rather than a stray Return.
    """

    def __init__(
        self,
        parent: wx.Window,
        title: str,
        summary: str,
        entries: Sequence[RecentEntry],
        *,
        destructive: bool = False,
        confirm_label: str = "",
    ) -> None:
        super().__init__(
            parent,
            title=title,
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.authorised = False
        palette = tokens.palette()
        self.SetBackgroundColour(palette.surface)
        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(
            _Text(
                self,
                summary,
                size_px=14,
                role="on_surface",
                wrap_width=_px(520),
                name="Bulk action summary",
            ),
            0,
            wx.EXPAND | wx.ALL,
            _px(16),
        )
        preview = wx.ScrolledWindow(self, style=wx.TAB_TRAVERSAL | wx.VSCROLL)
        preview.SetScrollRate(0, _px(12))
        preview.SetBackgroundColour(palette.surface)
        preview.SetName("Affected rows")
        preview_sizer = wx.BoxSizer(wx.VERTICAL)
        for entry in entries:
            preview_sizer.Add(
                widgets.ListRow(
                    preview,
                    entry.name,
                    entry.path or "No path recorded",
                    entry.tag,
                ),
                0,
                wx.EXPAND | wx.BOTTOM,
                _px(4),
            )
        preview.SetSizer(preview_sizer)
        root.Add(preview, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, _px(16))
        if destructive:
            self.gate = widgets.KeyGate(
                self,
                on_authorize=self._authorise,
                on_exit=lambda: self.EndModal(wx.ID_CANCEL),
            )
            root.Add(self.gate, 0, wx.EXPAND | wx.ALL, _px(16))
            root.Add(
                self.CreateStdDialogButtonSizer(wx.CANCEL),
                0,
                wx.ALIGN_RIGHT | wx.LEFT | wx.RIGHT | wx.BOTTOM,
                _px(16),
            )
        else:
            buttons = wx.BoxSizer(wx.HORIZONTAL)
            buttons.AddStretchSpacer()
            buttons.Add(
                widgets.StudioButton(
                    self,
                    "Cancel",
                    variant="outlined",
                    on_click=lambda: self.EndModal(wx.ID_CANCEL),
                    name="Cancel the bulk action",
                ),
                0,
                wx.RIGHT,
                _px(8),
            )
            buttons.Add(
                widgets.StudioButton(
                    self,
                    confirm_label or "Continue",
                    variant="filled",
                    on_click=self._authorise,
                    name=confirm_label or "Continue",
                ),
                0,
            )
            root.Add(buttons, 0, wx.EXPAND | wx.ALL, _px(16))
        self.SetSizer(root)
        _fit_owner_drawn(self)
        self.SetSize(wx.Size(_px(600), _px(520)))
        self.Layout()
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char)

    def _authorise(self) -> None:
        self.authorised = True
        self.EndModal(wx.ID_OK)

    def _on_char(self, event: wx.KeyEvent) -> None:
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.EndModal(wx.ID_CANCEL)
            return
        event.Skip()


# ---------------------------------------------------------------------------
# the view itself
# ---------------------------------------------------------------------------
class BackstageView(wx.Panel):
    """The project screen: a navigation rail beside one scrolling destination.

    The view owns no project state of its own beyond what it is told.  The
    shell says which project is open and what it is called; everything else on
    screen is read from the recent store, from the surface index, or from the
    files the user pointed at, so nothing here can report a project state that
    the rest of the application does not share.
    """

    def __init__(
        self,
        parent: wx.Window,
        *,
        on_surface: Optional[Callable[[str], None]] = None,
        on_command: Optional[Callable[[str], None]] = None,
        on_open_project: Optional[Callable[..., None]] = None,
        on_workspace: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self.on_surface = on_surface
        self.on_command = on_command
        self.on_open_project = on_open_project
        self.on_workspace = on_workspace

        self.tab = "home"
        self.project_open = False
        self.doc_title = "Untitled project"
        self.project_path = ""
        self.project_platform = ""
        self.convert_output = ""
        self.recent_filter = "All"
        self.recent_state = SearchState(label="Recent projects")
        self.surface_state = SearchState(label="All surfaces")
        self.detected_state = SearchState(label="Detected worlds")
        self.update_status = "unknown"
        self.update_version = ""
        self.update_detail = ""

        # The installed worlds, and the one scan that identified them.  Kept on
        # the view rather than rebuilt per page so switching back to Open shows
        # the list at once instead of reading every save directory again.
        self._detected_scan: Optional[WorldScan] = None
        self._detected_thread: Optional[threading.Thread] = None
        self._detected_generation = 0
        self._detected_host: Optional[wx.Panel] = None
        self._detected_summary: Optional[_Text] = None
        # The conversion the Convert page has running, if any.
        self._conversion: Optional[wx.Window] = None
        self._conversion_timer: Optional[wx.Timer] = None
        self._conversion_log: Optional[_ConversionLog] = None
        self._convert_progress: Optional[_Text] = None
        self._convert_button: Optional[widgets.StudioButton] = None

        self.store = recents.store()
        self._width_targets: List[Callable[[int], None]] = []
        self._available_width = 0
        self._measure_generation = 0
        self._info_rows: Dict[str, _InfoRow] = {}
        self._rail_buttons: Dict[str, _RailButton] = {}
        self._table: Optional[_RecentTable] = None
        self._bulk: Optional[widgets.BulkActionBar] = None
        self._bulk_scope: Optional[_Text] = None
        self._bulk_labels: Dict[str, str] = {}
        self._surface_count: Optional[_Text] = None
        self._surface_host: Optional[wx.Panel] = None
        self._surface_cards: Tuple[_SurfaceCard, ...] = ()
        self._filter_chips: Dict[str, widgets.Chip] = {}
        self._convert_error: Optional[_Text] = None
        self._output_slot: Optional[_EmptySlot] = None
        self._recent_search: Optional[widgets.SearchBar] = None

        self.SetName("Project backstage")
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)

        self.rail = wx.Panel(self, style=wx.TAB_TRAVERSAL)
        self.rail.SetName("Backstage navigation")
        self.rail_sizer = wx.BoxSizer(wx.VERTICAL)
        self.rail.SetSizer(self.rail_sizer)

        self.body = wx.ScrolledWindow(self, style=wx.TAB_TRAVERSAL | wx.VSCROLL)
        self.body.SetScrollRate(0, _px(12))
        self.body.SetName("Backstage content")
        self.body_sizer = wx.BoxSizer(wx.VERTICAL)
        self.body.SetSizer(self.body_sizer)
        self.content: Optional[wx.Panel] = None

        root = wx.BoxSizer(wx.HORIZONTAL)
        root.Add(self.rail, 0, wx.EXPAND)
        root.Add(self.body, 1, wx.EXPAND)
        self.SetSizer(root)

        self._theme_unsubscribe = tokens.register_theme_listener(self.refresh_theme)
        self.Bind(wx.EVT_WINDOW_DESTROY, self._on_destroyed)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.body.Bind(wx.EVT_SIZE, self._on_body_size)

        self._apply_palette()
        self._build_rail()
        self._build_content()

    # -- lifecycle -----------------------------------------------------------
    def _on_destroyed(self, event: wx.WindowDestroyEvent) -> None:
        if event.GetEventObject() is self and self._theme_unsubscribe is not None:
            self._theme_unsubscribe()
            self._theme_unsubscribe = None
        event.Skip()

    def _apply_palette(self) -> None:
        palette = tokens.palette()
        self.SetBackgroundColour(palette.surface)
        self.rail.SetBackgroundColour(palette.primary_container)
        self.body.SetBackgroundColour(palette.surface)
        if self.content is not None:
            self.content.SetBackgroundColour(palette.surface)

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        dc, gcdc = widgets.paint_context(self, self.GetBackgroundColour())
        del gcdc
        del dc

    def refresh_theme(self) -> None:
        """Re-resolve the tokens and repaint the rail and the current page."""
        try:
            if self.IsBeingDeleted():
                return
        except RuntimeError:  # pragma: no cover - window already destroyed
            return
        self._apply_palette()
        for child in self.GetChildren():
            refresh = getattr(child, "refresh_theme", None)
            if callable(refresh):
                refresh()
        self.rail.Refresh()
        self.body.Refresh()
        self.Refresh()

    # -- public API ----------------------------------------------------------
    def set_tab(self, tab: str) -> None:
        """Show one backstage destination, rebuilding its page."""
        key = tab if tab in TABS else "home"
        self.tab = key
        for name, button in self._rail_buttons.items():
            button.set_active(name == key)
        self._build_content()

    #: The shell may reasonably spell this either way; both do the same thing.
    show_tab = set_tab

    def set_project(
        self, open_: bool, title: str = "", path: str = "", platform: str = ""
    ) -> None:
        """Tell the view which project the shell currently has open."""
        self.project_open = bool(open_)
        if title:
            self.doc_title = str(title)
        if not self.project_open:
            self.doc_title = "Untitled project"
            self.project_path = ""
            self.project_platform = ""
        else:
            self.project_path = str(path)
            self.project_platform = str(platform)
        self._build_rail()
        self._build_content()

    def set_update_state(
        self, status: str, version: str = "", detail: str = ""
    ) -> None:
        """Record the update state the host has actually observed.

        The view never guesses this.  Until the host says otherwise the
        Workspace page states plainly that no check has been reported, rather
        than implying an update is waiting.
        """
        self.update_status = str(status or "unknown")
        self.update_version = str(version)
        self.update_detail = str(detail)
        if self.tab == "account":
            self._build_content()

    def focus_recent_search(self) -> None:
        """Put the keyboard in the recent-project search field."""
        if self.tab != "home":
            self.set_tab("home")
        if self._recent_search is not None:
            self._recent_search.SetFocus()

    # -- rail ----------------------------------------------------------------
    def _build_rail(self) -> None:
        self.rail_sizer.Clear(delete_windows=True)
        self._rail_buttons = {}
        palette = tokens.palette()
        self.rail.SetBackgroundColour(palette.primary_container)
        # The design pads the rail once -- 20px top and bottom, 12px each side
        # -- so the items inside can keep their own 2px rhythm rather than each
        # of them repeating the container's inset.
        inner = wx.BoxSizer(wx.VERTICAL)
        self.rail_sizer.Add(
            inner,
            1,
            wx.EXPAND | wx.TOP | wx.BOTTOM,
            _px(20),
        )
        wordmark = _Text(
            self.rail,
            self._wordmark_text(),
            size_px=20,
            weight=_MEDIUM,
            role="on_primary_container",
            line_height=1.2,
            name="Product name",
        )
        inner.Add(wordmark, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, _px(12))
        inner.AddSpacer(_px(18))
        items = (
            ("home", "Home", "主頁", "⌂"),
            ("open", "Open", "開啟", "▸"),
            ("info", "Info", "資料", "ⓘ"),
            ("convert", "Convert", "轉換", "⇄"),
            ("features", "All surfaces", "所有介面", "▦"),
            ("account", "Workspace", "工作區", "◎"),
        )
        for key, english, cantonese, glyph in items:
            button = _RailButton(
                self.rail,
                studio_label(english, cantonese),
                glyph,
                on_click=lambda tab=key: self.set_tab(tab),
                active=key == self.tab,
                name=english,
                hint=f"Show the {english} page",
            )
            self._rail_buttons[key] = button
            row = wx.BoxSizer(wx.HORIZONTAL)
            row.Add(button, 1, wx.LEFT | wx.RIGHT, _px(12))
            inner.Add(row, 0, wx.EXPAND | wx.BOTTOM, _px(2))
        inner.AddStretchSpacer()
        options_row = wx.BoxSizer(wx.HORIZONTAL)
        options_row.Add(
            _RailButton(
                self.rail,
                studio_label("Options", "選項"),
                "⚙",
                on_click=lambda: self._open_surface(SURFACE_PREFERENCES),
                name="Options",
                hint="Open the settings window",
            ),
            1,
            wx.LEFT | wx.RIGHT,
            _px(12),
        )
        inner.Add(options_row, 0, wx.EXPAND)
        if self.project_open:
            back_row = wx.BoxSizer(wx.HORIZONTAL)
            back_row.Add(
                _RailButton(
                    self.rail,
                    studio_label("Back to project", "返回專案"),
                    "←",
                    on_click=lambda: widgets.invoke(self.on_workspace),
                    filled=True,
                    name="Back to project",
                    hint=f"Return to {self.doc_title}",
                ),
                1,
                wx.LEFT | wx.RIGHT,
                _px(12),
            )
            inner.Add(back_row, 0, wx.EXPAND | wx.TOP, _px(4))
        self.rail.SetMinSize(wx.Size(_px(RAIL_WIDTH), -1))
        self.rail.Layout()
        self.Layout()

    @staticmethod
    def _wordmark_text() -> str:
        """Return the product name the user has chosen to see it called by.

        Renaming changes only what is displayed: the data directory, the
        package identity, and the update feed all keep the shipped name, so a
        new title can never orphan a stored profile.
        """
        try:
            chosen = preferences.resolve_display_name("{display_name}").strip()
        except (TypeError, ValueError, OSError):
            log.debug("Could not resolve the display name", exc_info=True)
            return "Amulet Studio"
        if not chosen:
            return "Amulet Studio"
        # The suffix is part of the SHIPPED name, not something to bolt onto a
        # chosen one. Appending it unconditionally turned "My Map Studio" into
        # "My Map Studio Studio", and would make any rename read as somebody
        # else's product line. A renamed application shows exactly the name the
        # user typed; only the default gains the word.
        if chosen == preferences.DEFAULT_DISPLAY_NAME:
            return f"{chosen} Studio"
        return chosen

    # -- body ----------------------------------------------------------------
    def _on_body_size(self, event: wx.SizeEvent) -> None:
        available = max(_px(320), event.GetSize().width - _px(BODY_PADDING_SIDE) * 2)
        if available != self._available_width:
            self._available_width = available
            self._apply_widths()
        event.Skip()

    def _register_width(self, setter: Callable[[int], None]) -> None:
        """Register a control that has to be re-measured when the body resizes."""
        self._width_targets.append(setter)

    def _apply_widths(self) -> None:
        available = self._available_width or _px(1024)
        for setter in list(self._width_targets):
            try:
                setter(available)
            except RuntimeError:
                continue
        if self.content is not None:
            self.content.Layout()
        self.body.Layout()
        self.body.FitInside()

    def _build_content(self) -> None:
        self._width_targets = []
        self._info_rows = {}
        self._table = None
        self._bulk = None
        self._bulk_scope = None
        self._bulk_labels = {}
        self._surface_count = None
        self._surface_host = None
        self._surface_cards = ()
        self._filter_chips = {}
        self._convert_error = None
        self._output_slot = None
        self._recent_search = None
        self._detected_host = None
        self._detected_summary = None
        self._convert_progress = None
        self._convert_button = None
        self.body_sizer.Clear(delete_windows=True)
        palette = tokens.palette()
        self.content = wx.Panel(self.body, style=wx.TAB_TRAVERSAL)
        self.content.SetBackgroundColour(palette.surface)
        self.content.SetName(f"Backstage {self.tab} page")
        sizer = wx.BoxSizer(wx.VERTICAL)
        self.content.SetSizer(sizer)
        builders = {
            "home": self._build_home,
            "open": self._build_open,
            "info": self._build_info,
            "convert": self._build_convert,
            "features": self._build_features,
            "account": self._build_workspace,
        }
        builders.get(self.tab, self._build_home)(self.content, sizer)
        self.body_sizer.Add(
            self.content,
            1,
            wx.EXPAND | wx.LEFT | wx.RIGHT,
            _px(BODY_PADDING_SIDE),
        )
        self.body_sizer.InsertSpacer(0, _px(BODY_PADDING_TOP))
        self.body_sizer.AddSpacer(_px(BODY_PADDING_BOTTOM))
        if self._available_width == 0:
            self._available_width = max(
                _px(320), self.body.GetClientSize().width - _px(BODY_PADDING_SIDE) * 2
            )
        _fit_owner_drawn(self.content)
        self._apply_widths()
        self.body.Scroll(0, 0)

    def _search_bar(
        self,
        parent: wx.Window,
        placeholder: str,
        state: SearchState,
        *,
        on_change: Callable[[SearchState], None],
        min_width: int,
    ) -> widgets.SearchBar:
        """Build a search field, its regex opt-in, and its builder button.

        The panel is switched back to a system-erased background because it
        carries no paint handler of its own: left in paint-only mode its strip
        behind the checkbox and the builder button is never cleared, which
        reads as a black gap beside an otherwise finished field.
        """
        bar = widgets.SearchBar(parent, placeholder, state, on_change=on_change)
        bar.SetBackgroundStyle(wx.BG_STYLE_SYSTEM)
        bar.SetBackgroundColour(tokens.palette().surface)
        bar.SetMinSize(wx.Size(_px(min_width), -1))
        return bar

    def _column_width(self, available: int, columns: int, gap: int) -> int:
        """Return one cell's width in an evenly divided grid."""
        return max(_px(120), (available - gap * (columns - 1)) // max(1, columns))

    # -- home ----------------------------------------------------------------
    def _build_home(self, parent: wx.Panel, sizer: wx.BoxSizer) -> None:
        english, cantonese = _greeting_pair()
        greeting = _heading(parent, english, cantonese, 34)
        sizer.Add(greeting, 0, wx.EXPAND | wx.BOTTOM, _px(6))
        intro = _body_text(
            parent,
            "Start a project from a template, or pick up a world you were "
            "editing. Every project stays local to this machine.",
            "揀個範本開新專案，或者接返之前改緊嘅世界。所有專案都淨係留喺呢部機。",
        )
        sizer.Add(intro, 0, wx.EXPAND | wx.BOTTOM, _px(30))
        self._register_width(
            lambda width: intro.set_available_width(min(_px(640), width))
        )

        sizer.Add(_eyebrow(parent, "New", "新增"), 0, wx.EXPAND | wx.BOTTOM, _px(14))
        gap = _px(16)
        grid = wx.GridSizer(len(TEMPLATES), gap, gap)
        cards: List[_TemplateCard] = []
        for template in TEMPLATES:
            card = _TemplateCard(parent, template, on_click=self._start_template)
            cards.append(card)
            grid.Add(card, 0, wx.EXPAND)
        sizer.Add(grid, 0, wx.EXPAND | wx.BOTTOM, _px(38))
        self._register_width(
            lambda width, items=tuple(cards): [
                item.set_available_width(
                    self._column_width(width, len(TEMPLATES), _px(16))
                )
                for item in items
            ]
        )

        header = wx.BoxSizer(wx.HORIZONTAL)
        header.Add(
            _eyebrow(parent, "Recent", "最近"),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            _px(16),
        )
        for name in recents.FILTERS:
            chip = widgets.Chip(
                parent,
                studio_label(
                    name,
                    {"All": "全部", "Worlds": "世界", "Projects": "專案"}.get(
                        name, name
                    ),
                ),
                selected=name == self.recent_filter,
                on_click=lambda _selected, key=name: self._set_recent_filter(key),
            )
            chip.SetName(f"Show {name.lower()} recent records")
            self._filter_chips[name] = chip
            header.Add(chip, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, _px(4))
        header.AddStretchSpacer()
        self._recent_search = self._search_bar(
            parent,
            studio_label("Search recent projects and worlds", "搜尋最近嘅專案同世界"),
            self.recent_state,
            on_change=lambda _state: self._refresh_recent(),
            min_width=460,
        )
        header.Add(self._recent_search, 0, wx.ALIGN_TOP)
        sizer.Add(header, 0, wx.EXPAND | wx.BOTTOM, _px(12))

        # The bar reports whichever label it was given, so the displayed label
        # is mapped back to the canonical action rather than compared against
        # English text that a language mode has already replaced.
        self._bulk_labels = {}
        displayed: List[str] = []
        for action in BULK_ACTIONS:
            label = studio_label(action, BULK_CANTONESE.get(action, ""))
            self._bulk_labels[label] = action
            displayed.append(label)
        self._bulk = widgets.BulkActionBar(
            parent, on_action=self._on_bulk_action, actions=tuple(displayed)
        )
        sizer.Add(self._bulk, 0, wx.EXPAND | wx.BOTTOM, _px(6))
        self._bulk_scope = _Text(
            parent,
            "",
            size_px=12,
            role="on_surface_variant",
            name="Bulk action scope",
        )
        sizer.Add(self._bulk_scope, 0, wx.EXPAND | wx.BOTTOM, _px(12))
        self._register_width(lambda width: self._bulk_scope.set_available_width(width))

        self._table = _RecentTable(
            parent,
            on_open=self._open_recent,
            on_pin=self._pin_recent,
            on_selection=self._update_bulk_state,
        )
        sizer.Add(self._table, 0, wx.EXPAND)
        self._register_width(lambda width: self._table.set_available_width(width))
        self._refresh_recent()

    def _set_recent_filter(self, name: str) -> None:
        self.recent_filter = name if name in recents.FILTERS else "All"
        for key, chip in self._filter_chips.items():
            chip.set_selected(key == self.recent_filter)
        self._refresh_recent()

    def _visible_recent(self) -> List[RecentEntry]:
        return self.store.search(self.recent_state, tag=self.recent_filter)

    def _refresh_recent(self) -> None:
        if self._table is None:
            return
        entries = self._visible_recent()
        self._table.set_entries(entries)
        self._update_bulk_state()
        self._apply_widths()

    def _update_bulk_state(self) -> None:
        if self._table is None or self._bulk is None:
            return
        selected = self._table.selection()
        total = len(self._table.entries)
        self._bulk.set_count(len(selected), total)
        pinned = sum(1 for entry in selected if entry.pinned)
        conditions = {
            BULK_SELECT_ALL: "" if total else "There is nothing in the list to select.",
            BULK_SELECT_NONE: "" if selected else "Nothing is selected.",
            BULK_INVERT: "" if total else "There is nothing in the list to invert.",
            BULK_OPEN: (
                ""
                if len(selected) == 1
                else (
                    "Select exactly one row: a project is opened one at a time, "
                    f"and {len(selected)} are selected."
                    if selected
                    else "Select one row to open it."
                )
            ),
            BULK_PIN: (
                ""
                if selected and pinned < len(selected)
                else (
                    "Every selected row is already pinned."
                    if selected
                    else "Nothing is selected."
                )
            ),
            BULK_UNPIN: (
                ""
                if pinned
                else (
                    "None of the selected rows is pinned."
                    if selected
                    else "Nothing is selected."
                )
            ),
            BULK_REMOVE: "" if selected else "Nothing is selected.",
            BULK_EXPORT: ("" if total else "There is nothing in the list to export."),
        }
        for button in self._bulk.buttons:
            action = self._bulk_labels.get(button.GetLabel(), button.GetLabel())
            reason = conditions.get(action, "")
            button.Enable(not reason)
            button.SetToolTip(reason or f"{action} for the current selection")
        if self._bulk_scope is not None:
            matching = (
                "the current search"
                if self.recent_filter == "All"
                else f"the {self.recent_filter} filter and the current search"
            )
            scope = (
                f"Select all matches takes every one of the {total} "
                f"{'row' if total == 1 else 'rows'} that match {matching}. "
                "This table shows every match on one page, so there is no second "
                "page to miss. Export writes the same set."
            )
            if selected:
                scope = f"{len(selected)} of {total} selected. " + scope
            self._bulk_scope.set_text(scope)
            self._bulk_scope.set_available_width(self._available_width or _px(1024))
            if self.content is not None:
                self.content.Layout()

    def _start_template(self, template: _Template) -> None:
        """Run what a template card says it does, or say why it cannot.

        No card opens a nameless empty project: reporting a project as open
        when nothing was opened is the one outcome that makes every other
        number on the screen untrustworthy.
        """
        if template.unavailable:
            self._notify(
                f"{template.title} is not available yet",
                template.unavailable,
                severity="warning",
            )
            return
        if template.action == "convert":
            self.set_tab("convert")
            return
        if template.action == "open_folder":
            self._open_world_folder()
            return
        if template.action == "open_structure":
            self._open_structure_file()
            return
        if template.action == "chunk_repair":
            if self._open_world_folder():
                self._notify(
                    "World opened for chunk repair",
                    "Pruning, regenerating, and restoring chunks are in the 3D "
                    "editor's Chunk tool, which is now available for this world.",
                )
            return
        if template.action == "school_mode":
            self._open_surface(SURFACE_PREFERENCES)
            return
        self._notify(
            f"{template.title} did nothing",
            f"This card asks for the action {template.action!r}, which this "
            "build does not route anywhere. Nothing was opened or changed.",
            severity="error",
        )

    def _open_recent(self, entry: RecentEntry) -> None:
        self.store.add(
            entry.name,
            kind=entry.kind,
            platform=entry.platform,
            path=entry.path,
            tag=entry.tag,
        )
        widgets.invoke(self.on_open_project, entry.name, entry.path)
        self._refresh_recent()

    def _pin_recent(self, entry: RecentEntry, pinned: bool) -> None:
        self.store.pin(entry, pinned)
        self._refresh_recent()
        self._notify(
            "Pinned" if pinned else "Unpinned",
            f"{entry.name} is {'pinned to' if pinned else 'no longer pinned in'} "
            "the top of the recent list.",
        )

    # -- home: bulk actions --------------------------------------------------
    def _on_bulk_action(self, displayed: str) -> None:
        if self._table is None:
            return
        label = self._bulk_labels.get(displayed, displayed)
        if label == BULK_SELECT_ALL:
            self._table.select_all()
            return
        if label == BULK_SELECT_NONE:
            self._table.select_none()
            return
        if label == BULK_INVERT:
            self._table.invert_selection()
            return
        selected = self._table.selection()
        if label == BULK_OPEN:
            if len(selected) != 1:
                self._notify(
                    "Open acts on one project",
                    f"{len(selected)} rows are selected. Select exactly one row to "
                    "open it.",
                    severity="warning",
                )
                return
            self._open_recent(selected[0])
            return
        if label in (BULK_PIN, BULK_UNPIN):
            pinned = label == BULK_PIN
            affected = [entry for entry in selected if entry.pinned != pinned]
            if not affected:
                self._notify(
                    "Nothing to change",
                    f"Every selected row is already "
                    f"{'pinned' if pinned else 'unpinned'}.",
                    severity="warning",
                )
                return
            if not self._preview(
                "Pin rows" if pinned else "Unpin rows",
                f"{len(affected)} of the {len(selected)} selected "
                f"{'row' if len(selected) == 1 else 'rows'} will be "
                f"{'pinned' if pinned else 'unpinned'}. The rest are already in "
                "that state and will not change.",
                affected,
                confirm_label="Pin" if pinned else "Unpin",
            ):
                return
            for entry in affected:
                self.store.pin(entry, pinned)
            self._refresh_recent()
            self._notify(
                "Pinned" if pinned else "Unpinned",
                f"{len(affected)} {'row' if len(affected) == 1 else 'rows'} "
                f"{'pinned' if pinned else 'unpinned'}.",
            )
            return
        if label == BULK_REMOVE:
            if not selected:
                return
            if not self._preview(
                "Remove from the recent list",
                f"{len(selected)} {'row' if len(selected) == 1 else 'rows'} will be "
                "removed from the recent list. Nothing on disk is deleted: the "
                "worlds and project folders below stay exactly where they are, and "
                "the removal is recorded in the local history so it can be undone.",
                selected,
                destructive=True,
            ):
                return
            removed = self.store.remove_many(selected)
            self._refresh_recent()
            self._notify(
                "Removed from the recent list",
                f"{removed} {'row' if removed == 1 else 'rows'} removed. No files "
                "on disk were touched.",
            )
            return
        if label == BULK_EXPORT:
            self._export_recent(selected)

    def _preview(
        self,
        title: str,
        summary: str,
        entries: Sequence[RecentEntry],
        *,
        destructive: bool = False,
        confirm_label: str = "",
    ) -> bool:
        """Show the affected rows and return whether the action may proceed."""
        dialog = _BulkPreviewDialog(
            self,
            title,
            summary,
            entries,
            destructive=destructive,
            confirm_label=confirm_label,
        )
        try:
            dialog.ShowModal()
            return bool(dialog.authorised)
        finally:
            dialog.Destroy()

    def _export_recent(self, selected: Sequence[RecentEntry]) -> None:
        """Write the visible or selected rows out in JSON, CSV, or Markdown."""
        rows = list(selected) if selected else self._visible_recent()
        if not rows:
            self._notify(
                "Nothing to export",
                "The recent list is empty, so there is nothing to write.",
                severity="warning",
            )
            return
        scope = (
            f"the {len(rows)} selected {'row' if len(rows) == 1 else 'rows'}"
            if selected
            else f"all {len(rows)} {'row' if len(rows) == 1 else 'rows'} matching the "
            f"{self.recent_filter.lower()} filter and the current search"
        )
        if not self._preview(
            "Export the recent list",
            f"Writing {scope}. Choose JSON, CSV, or Markdown in the next dialog; "
            "the file is UTF-8 with LF line endings and states its own schema.",
            rows,
            confirm_label="Choose a file",
        ):
            return
        self._write_export(
            "Export the recent list",
            "recent-projects.json",
            lambda export_format: self.store.export_text(export_format, rows),
            count=len(rows),
            noun="row",
            schema=f"{recents.STORE_SCHEMA} v{recents.STORE_VERSION}",
        )

    def _write_export(
        self,
        title: str,
        default_name: str,
        build: Callable[[str], str],
        *,
        count: int,
        noun: str,
        schema: str,
    ) -> None:
        """Ask where to write an export, write it, and report exactly what landed.

        The chosen filter decides the format rather than the typed extension,
        and the extension is corrected to match, so a file named ``.json`` can
        never hold comma separated values.
        """
        wildcard = (
            "JSON (*.json)|*.json|"
            "Comma separated values (*.csv)|*.csv|"
            "Markdown (*.md)|*.md"
        )
        with wx.FileDialog(
            self,
            title,
            defaultFile=default_name,
            wildcard=wildcard,
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        ) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            target = Path(dialog.GetPath())
            index = dialog.GetFilterIndex()
        export_format = recents.EXPORT_FORMATS[max(0, min(2, index))]
        suffix = recents.EXPORT_EXTENSIONS[export_format]
        if target.suffix.lower() != suffix:
            target = target.with_suffix(suffix)
        try:
            text = build(export_format)
            with open(target, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(text)
        except (OSError, ValueError) as error:
            self._notify(
                "Export failed",
                f"Nothing was written to {target}.",
                severity="error",
                details=str(error),
            )
            return
        self._notify(
            "Export written",
            f"{count} {noun if count == 1 else noun + 's'} written as "
            f"{export_format} to {target}. UTF-8, LF line endings, schema "
            f"{schema}.",
        )
        self._offer_to_open(target)

    def _offer_to_open(self, target: Path) -> None:
        """Ask whether to open an export in the configured editor, then do it."""
        # The shared Material confirmation rather than a platform message box:
        # a native one ignores the application theme, density, and language
        # mode, and the project keeps a guard against reintroducing any.
        from amulet_map_editor.api.wx.ui.confirm import show_material_confirmation

        answer = show_material_confirmation(
            self,
            f"Open {target.name} in the configured external editor?",
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
            "Open the export",
        )
        if answer != wx.ID_YES:
            return
        try:
            from amulet_map_editor.api import export_actions

            action = export_actions.open_exported_path(target)
        except Exception as error:  # pragma: no cover - launcher boundary
            self._notify(
                "Could not open the export",
                f"{target} was written but could not be opened.",
                severity="error",
                details=str(error),
            )
            return
        self._notify(
            "Export opened" if action.ok else "Could not open the export",
            action.message or str(target),
            severity="info" if action.ok else "warning",
        )

    # -- open ----------------------------------------------------------------
    def _build_open(self, parent: wx.Panel, sizer: wx.BoxSizer) -> None:
        block = self._max_width_block(parent, sizer, 900)
        inner = block.GetSizer()
        inner.Add(_heading(block, "Open", "開啟", 30), 0, wx.EXPAND | wx.BOTTOM, _px(8))
        intro = _body_text(
            block,
            "Close the world in game and other tools before opening it here. "
            "Amulet edits the files on disk.",
            "喺遊戲同其他工具入面閂咗個世界先好喺呢度開。Amulet 會直接改硬碟上面嘅檔案。",
        )
        inner.Add(intro, 0, wx.EXPAND | wx.BOTTOM, _px(26))
        rows: List[_SourceRow] = []
        for source in OPEN_SOURCES:
            row = _SourceRow(block, source, on_click=self._run_open_source)
            rows.append(row)
            inner.Add(row, 0, wx.EXPAND | wx.BOTTOM, _px(10))

        # The worlds this machine actually has, listed rather than hidden
        # behind a dialog: the commonest thing a user wants to do on this page
        # is open one of their own worlds, and a list they can see and search
        # is a shorter route to that than a button that opens another list.
        inner.AddSpacer(_px(18))
        header = wx.BoxSizer(wx.HORIZONTAL)
        header.Add(
            _eyebrow(block, "Detected worlds", "偵測到嘅世界"),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            _px(16),
        )
        header.AddStretchSpacer()
        header.Add(
            self._search_bar(
                block,
                studio_label("Search detected worlds", "搜尋偵測到嘅世界"),
                self.detected_state,
                on_change=lambda _state: self._refresh_detected(),
                min_width=420,
            ),
            0,
            wx.ALIGN_TOP,
        )
        inner.Add(header, 0, wx.EXPAND | wx.BOTTOM, _px(10))
        self._detected_summary = _Text(
            block,
            studio_text(
                "Reading the installed Minecraft directories…",
                "讀緊已安裝嘅 Minecraft 資料夾…",
            ),
            size_px=13,
            role="on_surface_variant",
            name="Detected worlds summary",
        )
        inner.Add(self._detected_summary, 0, wx.EXPAND | wx.BOTTOM, _px(10))
        self._detected_host = wx.Panel(block, style=wx.TAB_TRAVERSAL)
        self._detected_host.SetBackgroundColour(tokens.palette().surface)
        self._detected_host.SetName("Detected worlds")
        self._detected_host.SetSizer(wx.BoxSizer(wx.VERTICAL))
        inner.Add(self._detected_host, 0, wx.EXPAND)

        advisory = _Advisory(
            block,
            studio_text(
                "Back up every world before editing it. Conversion overwrites "
                "destination chunks at matching coordinates.",
                "改之前記得備份每個世界。轉換會覆寫目的地入面相同座標嘅區塊。",
            ),
            name="Backup advisory",
        )
        inner.Add(advisory, 0, wx.EXPAND | wx.TOP, _px(20))
        self._register_width(
            lambda width, items=tuple(rows), text=intro, note=advisory: (
                text.set_available_width(min(_px(900), width)),
                [item.set_available_width(min(_px(900), width)) for item in items],
                note.set_available_width(min(_px(900), width)),
                self._detected_summary.set_available_width(min(_px(900), width)),
            )
        )
        self._refresh_detected()
        self._scan_detected_worlds()

    # -- open: the worlds this machine actually has --------------------------
    def _scan_detected_worlds(self, *, force: bool = False) -> None:
        """Identify the installed worlds off the UI thread, once per view.

        Identifying a world opens its format wrapper and reads its level data,
        so this is never done on the thread drawing the page.  The generation
        counter is what stops a slow scan from writing its answer into a page
        the user has already navigated away from.
        """
        if self._detected_scan is not None and not force:
            return
        if self._detected_thread is not None and self._detected_thread.is_alive():
            return
        self._detected_generation += 1
        generation = self._detected_generation

        def worker() -> None:
            try:
                scan = detect_worlds()
            except Exception as error:  # noqa: BLE001 - say so rather than hang
                log.exception("The installed worlds could not be scanned")
                scan = WorldScan(error=str(error))
            wx.CallAfter(self._apply_detected_scan, generation, scan)

        self._detected_thread = threading.Thread(
            target=worker, name="amulet-studio-world-scan", daemon=True
        )
        self._detected_thread.start()

    def _apply_detected_scan(self, generation: int, scan: WorldScan) -> None:
        if generation != self._detected_generation:
            return
        self._detected_scan = scan
        self._refresh_detected()

    def _refresh_detected(self) -> None:
        host = getattr(self, "_detected_host", None)
        if host is None:
            return
        sizer = host.GetSizer()
        try:
            sizer.Clear(delete_windows=True)
        except RuntimeError:  # pragma: no cover - the page has been rebuilt
            return
        scan = self._detected_scan
        if self._detected_summary is not None:
            self._detected_summary.set_text(
                studio_text(
                    "Reading the installed Minecraft directories…",
                    "讀緊已安裝嘅 Minecraft 資料夾…",
                )
                if scan is None
                else scan.summary()
            )
            self._detected_summary.set_available_width(
                min(_px(900), self._available_width or _px(900))
            )
        if scan is None:
            host.Layout()
            self._apply_widths()
            return
        matches = [
            world
            for world in scan.worlds
            if self.detected_state.matches(world.haystack())
        ]
        if not matches:
            message = (
                self.detected_state.describe_matches(0, "world")
                if scan.worlds
                else scan.roots_text()
                or "No installed Minecraft save directory was found on this machine."
            )
            sizer.Add(
                _Text(
                    host,
                    message,
                    size_px=13,
                    role="on_surface_variant",
                    wrap_width=self._available_width or _px(680),
                    name="Detected worlds result count",
                ),
                0,
                wx.EXPAND,
            )
        for world in matches[:MAX_DETECTED_WORLD_ROWS]:
            row = widgets.ListRow(
                host,
                world.name,
                world.detail(),
                world.platform,
                on_click=lambda chosen=world: self._open_detected(chosen),
            )
            row.SetToolTip(f"{world.name}\n{world.path}")
            sizer.Add(row, 0, wx.EXPAND | wx.BOTTOM, _px(4))
        remainder = len(matches) - MAX_DETECTED_WORLD_ROWS
        if remainder > 0:
            sizer.Add(
                _Text(
                    host,
                    f"{remainder} more world{'' if remainder == 1 else 's'} match. "
                    "Narrow the search, or use "
                    "“Pick from a detected Minecraft install” to see them all.",
                    size_px=12,
                    role="on_surface_variant",
                    wrap_width=self._available_width or _px(680),
                    name="Detected worlds remainder",
                ),
                0,
                wx.EXPAND | wx.TOP,
                _px(6),
            )
        host.Layout()
        self._apply_widths()

    def _open_detected(self, world: DetectedWorld) -> None:
        """Open one of the worlds found on this machine."""
        self._open_path(world.name, world.path, world.platform, "Worlds")

    def _run_open_source(self, source: _OpenSource) -> None:
        if source.key == "folder":
            self._open_world_folder()
        elif source.key == "install":
            self._open_detected_world()
        elif source.key == "structure":
            self._open_structure_file()
        else:
            self.set_tab("home")
            self.focus_recent_search()

    def _open_world_folder(self) -> bool:
        """Browse for a save directory with the platform's own folder picker.

        Returns whether a world was actually handed to the shell, so a caller
        that wants to say something afterwards can tell the difference between
        a world opening and the user pressing Cancel.
        """
        from amulet_map_editor.api.wx.ui import path_dialog

        chosen = path_dialog.choose_path(self, "Choose a world folder", directory=True)
        if not chosen:
            return False
        root = Path(chosen)
        if not root.is_dir():
            self._notify(
                "That is not a folder",
                f"{root} is not a directory, so it cannot be opened as a world.",
                severity="error",
            )
            return False
        name, platform = self._identify_world(root)
        self._open_path(name, str(root), platform, "Worlds")
        return True

    def _open_detected_world(self) -> None:
        dialog = _WorldPickerDialog(self, self._detected_scan)
        try:
            if dialog.ShowModal() != wx.ID_OK or dialog.chosen is None:
                return
            chosen = dialog.chosen
        finally:
            dialog.Destroy()
        self._open_path(chosen.name, chosen.path, chosen.platform, "Worlds")

    def _open_structure_file(self) -> bool:
        with wx.FileDialog(
            self,
            "Open a structure file",
            wildcard=STRUCTURE_WILDCARD,
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return False
            target = Path(dialog.GetPath())
        self._open_path(
            target.stem,
            str(target),
            f"{target.suffix.lstrip('.') or 'structure'} file",
            "Projects",
        )
        return True

    @staticmethod
    def _identify_world(root: Path) -> Tuple[str, str]:
        """Return a chosen folder's own name and platform, as its format says.

        The loader is asked first, because it is what will actually open the
        world; when no loader matches, the reply says exactly that rather than
        naming a platform the application cannot then load.
        """
        try:
            from amulet import load_format

            world_format = load_format(str(root))
            return (
                str(world_format.level_name) or root.name,
                str(world_format.platform).title(),
            )
        except Exception:  # noqa: BLE001 - an unloadable folder is reported, not fatal
            log.debug("No loader matched %s", root, exc_info=True)
        return root.name, "No loader matched this folder"

    def _open_path(self, name: str, path: str, platform: str, tag: str) -> None:
        kind = "World project" if tag == "Worlds" else "Structure project"
        self.store.add(name, kind=kind, platform=platform, path=path, tag=tag)
        widgets.invoke(self.on_open_project, name, path)
        self._notify("Opening", f"{name} — {path}")

    # -- info ----------------------------------------------------------------
    @staticmethod
    def _world_context():
        """Return what the open world says about itself, or an empty context.

        The context module is the one place that reads the open level, so the
        backstage asks it rather than reading the level a second way and
        arriving at a slightly different answer from every other surface.
        """
        try:
            from amulet_map_editor.api.studio import context as world_context

            return world_context.current()
        except Exception:  # pragma: no cover - a build without the context
            log.debug("The Studio world context is unavailable", exc_info=True)

            class _Absent:
                """Reads as "nothing is open", which is exactly what is known."""

                open = False
                name = ""
                path = ""
                platform = ""
                version = ""
                game_version = ""
                seed = ""
                size_on_disk = 0
                level = None
                dimension_info: Tuple = ()

                @staticmethod
                def reason(_key: str) -> str:
                    return ""

            return _Absent()

    @staticmethod
    def _dimensions_value(world) -> str:
        """Return one line naming every dimension and what it holds."""
        records = getattr(world, "dimension_info", ()) or ()
        if not records:
            return "This world reports no dimensions"
        parts = []
        for info in records:
            if info.counted:
                chunks = f"{info.chunk_count:,} chunks" + (
                    "+" if info.truncated else ""
                )
            else:
                chunks = "chunk count unavailable"
            parts.append(f"{info.name} ({chunks})")
        return ", ".join(parts)

    def _build_info(self, parent: wx.Panel, sizer: wx.BoxSizer) -> None:
        block = self._max_width_block(parent, sizer, 960)
        inner = block.GetSizer()
        inner.Add(
            _heading(block, "Project info", "專案資料", 30),
            0,
            wx.EXPAND | wx.BOTTOM,
            _px(8),
        )
        world = self._world_context()
        subtitle = _Text(
            block,
            (
                self.doc_title
                if self.project_open
                else studio_text(
                    "No project is open. Everything below says so rather than "
                    "describing the project that was open last.",
                    "而家冇開任何專案。下面每一行都會照直講，唔會講返上次開嗰個。",
                )
            ),
            size_px=15,
            role="on_surface_variant",
            name="Open project",
        )
        inner.Add(subtitle, 0, wx.EXPAND | wx.BOTTOM, _px(26))
        columns = wx.BoxSizer(wx.HORIZONTAL)
        rows_panel = wx.Panel(block, style=wx.TAB_TRAVERSAL)
        rows_panel.SetBackgroundColour(tokens.palette().surface)
        rows_sizer = wx.BoxSizer(wx.VERTICAL)
        rows_panel.SetSizer(rows_sizer)
        entry = self.store.get(self.project_path or self.doc_title)
        absent = "No project is open"
        # The open level answers first, because it is the world itself; the
        # recent record is only consulted for a project the level cannot
        # describe, and neither is allowed to invent a value.
        name = (world.name if world.open else "") or (
            self.doc_title if self.project_open else absent
        )
        platform = (
            world.platform.title() if world.open and world.platform else ""
        ) or (self.project_platform or (entry.platform if entry else ""))
        path = (world.path if world.open else "") or (self.project_path or absent)
        definitions = [
            ("name", "Name", "名稱", name),
            (
                "platform",
                "Platform",
                "平台",
                platform or (absent if not self.project_open else "Not detected"),
            ),
            ("path", "Path", "路徑", path),
        ]
        if world.open:
            definitions.append(
                (
                    "version",
                    "Game version",
                    "遊戲版本",
                    world.game_version
                    or world.version
                    or "This world does not record a game version",
                )
            )
            definitions.append(
                (
                    "dimensions",
                    "Dimensions",
                    "維度",
                    self._dimensions_value(world),
                )
            )
            definitions.append(
                (
                    "seed",
                    "Seed",
                    "種子碼",
                    world.seed or world.reason("seed") or "Not recorded in level.dat",
                )
            )
        definitions.extend(
            [
                ("size", "Size on disk", "硬碟用量", "Measuring…"),
                ("chunks", "Chunks", "區塊", "Counting…"),
                (
                    "revisions",
                    "Revisions",
                    "版本",
                    "Reading the local history…",
                ),
            ]
        )
        for key, english, cantonese, value in definitions:
            row = _InfoRow(rows_panel, studio_label(english, cantonese), value)
            self._info_rows[key] = row
            rows_sizer.Add(row, 0, wx.EXPAND | wx.BOTTOM, _px(12))
        columns.Add(rows_panel, 1, wx.EXPAND | wx.RIGHT, _px(20))

        actions = wx.Panel(block, style=wx.TAB_TRAVERSAL)
        actions.SetBackgroundColour(tokens.palette().surface)
        actions_sizer = wx.BoxSizer(wx.VERTICAL)
        actions.SetSizer(actions_sizer)
        buttons = (
            ("Save project", "儲存專案", "filled", lambda: self._run(COMMAND_SAVE)),
            (
                "Version history",
                "版本紀錄",
                "outlined",
                lambda: self._open_surface(SURFACE_HISTORY),
            ),
            (
                "Export selection…",
                "匯出選取範圍…",
                "outlined",
                lambda: self._run(COMMAND_EXPORT_SELECTION),
            ),
            (
                "Close project",
                "關閉專案",
                "danger",
                lambda: self._run(COMMAND_CLOSE_PROJECT),
            ),
        )
        for english, cantonese, variant, handler in buttons:
            button = widgets.StudioButton(
                actions,
                studio_label(english, cantonese),
                variant=variant,
                on_click=handler,
                name=english,
                hint=(
                    f"{english} — no project is open"
                    if not self.project_open
                    else english
                ),
            )
            button.Enable(self.project_open)
            actions_sizer.Add(button, 0, wx.EXPAND | wx.BOTTOM, _px(10))
        if not self.project_open:
            actions_sizer.Add(
                _Text(
                    actions,
                    "These actions need an open project. Open one from Home or "
                    "from the Open page.",
                    size_px=12,
                    role="on_surface_variant",
                    wrap_width=_px(300),
                    name="Project actions unavailable",
                ),
                0,
                wx.EXPAND,
            )
        actions.SetMinSize(wx.Size(_px(320), -1))
        columns.Add(actions, 0, wx.EXPAND)
        inner.Add(columns, 1, wx.EXPAND)
        self._register_width(
            lambda width, panel=rows_panel: [
                child.set_available_width(
                    max(_px(240), min(_px(960), width) - _px(340))
                )
                for child in panel.GetChildren()
                if hasattr(child, "set_available_width")
            ]
        )
        self._register_width(
            lambda width: subtitle.set_available_width(min(_px(960), width))
        )
        self._start_measurement()

    def _start_measurement(self) -> None:
        """Measure the open project's size, chunks, and revisions off the UI thread.

        A world can hold hundreds of thousands of files, so reading them where
        the screen is being drawn would stall it.  The generation counter is
        what keeps a slow measurement from writing its answer into a page the
        user has already navigated away from.
        """
        if not self._info_rows:
            return
        world = self._world_context()
        path = (world.path if world.open else "") or self.project_path
        if not path:
            self._set_info("size", "No project is open")
            self._set_info("chunks", "No project is open")
            self._set_info("revisions", "No project is open")
            return
        self._measure_generation += 1
        generation = self._measure_generation
        key = path or self.doc_title

        def worker() -> None:
            measurement = _measure_project(path)
            revisions = _count_revisions(f"studio.project:{key}")
            wx.CallAfter(self._apply_measurement, generation, measurement, revisions)

        threading.Thread(
            target=worker, name="amulet-studio-project-measure", daemon=True
        ).start()

    def _apply_measurement(
        self, generation: int, measurement: ProjectMeasurement, revisions: str
    ) -> None:
        if generation != self._measure_generation:
            return
        self._set_info("size", measurement.size_label())
        self._set_info("chunks", measurement.chunk_label())
        self._set_info("revisions", revisions)

    def _set_info(self, key: str, value: str) -> None:
        row = self._info_rows.get(key)
        if row is None:
            return
        try:
            row.set_value(value)
        except RuntimeError:  # pragma: no cover - page already rebuilt
            return
        if self.content is not None:
            self.content.Layout()
            self.body.FitInside()

    # -- convert -------------------------------------------------------------
    def _build_convert(self, parent: wx.Panel, sizer: wx.BoxSizer) -> None:
        block = self._max_width_block(parent, sizer, 860)
        inner = block.GetSizer()
        inner.Add(
            _heading(block, "Convert", "轉換", 30), 0, wx.EXPAND | wx.BOTTOM, _px(8)
        )
        intro = _body_text(
            block,
            "Merge source-world chunks into a destination world through the "
            "format translation layer.",
            "經格式轉譯層將來源世界嘅區塊合併入目的地世界。",
        )
        inner.Add(intro, 0, wx.EXPAND | wx.BOTTOM, _px(26))

        input_card = widgets.Card(block)
        input_sizer = _card_body(input_card)
        input_sizer.Add(
            _eyebrow(input_card, "Input world", "來源世界", 12),
            0,
            wx.EXPAND | wx.BOTTOM,
            _px(12),
        )
        # The source is the world that is actually open, because that is the
        # level whose chunks the conversion reads. The card therefore describes
        # that level rather than whatever the shell was last told to call it.
        world = self._world_context()
        if world.open:
            row = wx.BoxSizer(wx.HORIZONTAL)
            row.Add(_WorldTile(input_card, world.path), 0, wx.RIGHT, _px(14))
            labels = wx.BoxSizer(wx.VERTICAL)
            labels.Add(
                _Text(
                    input_card,
                    world.name or Path(world.path).name or "Unnamed world",
                    size_px=15,
                    role="on_surface",
                    name="Input world name",
                ),
                0,
                wx.EXPAND,
            )
            labels.Add(
                _Text(
                    input_card,
                    world.game_version
                    or " ".join(
                        part for part in (world.platform.title(), world.version) if part
                    )
                    or "This world does not report a platform",
                    size_px=13,
                    role="on_surface_variant",
                    name="Input world platform",
                ),
                0,
                wx.EXPAND | wx.TOP,
                _px(2),
            )
            row.Add(labels, 1, wx.ALIGN_CENTER_VERTICAL)
            row.Add(
                widgets.StudioButton(
                    input_card,
                    studio_label("Change", "更改"),
                    variant="outlined",
                    on_click=self._open_world_folder,
                    name="Change the input world",
                    hint="Choose a different source world",
                ),
                0,
                wx.ALIGN_CENTER_VERTICAL,
            )
            input_sizer.Add(row, 0, wx.EXPAND)
        else:
            input_sizer.Add(
                _EmptySlot(
                    input_card,
                    studio_text(
                        "No world is open, so there are no chunks to convert",
                        "冇開任何世界，所以冇區塊可以轉換",
                    ),
                ),
                0,
                wx.EXPAND | wx.BOTTOM,
                _px(12),
            )
            input_sizer.Add(
                widgets.StudioButton(
                    input_card,
                    studio_label("Select input world", "揀來源世界"),
                    variant="outlined",
                    on_click=self._open_world_folder,
                    name="Select input world",
                    hint="Choose the world whose chunks will be read",
                ),
                0,
            )
        inner.Add(input_card, 0, wx.EXPAND | wx.BOTTOM, _px(16))

        output_card = widgets.Card(block)
        output_sizer = _card_body(output_card)
        output_sizer.Add(
            _eyebrow(output_card, "Output world", "目的地世界", 12),
            0,
            wx.EXPAND | wx.BOTTOM,
            _px(12),
        )
        self._output_slot = _EmptySlot(
            output_card,
            self.convert_output
            or studio_text("No destination world selected", "未揀目的地世界"),
        )
        output_sizer.Add(self._output_slot, 0, wx.EXPAND | wx.BOTTOM, _px(12))
        output_sizer.Add(
            widgets.StudioButton(
                output_card,
                studio_label("Select output world", "揀目的地世界"),
                variant="outlined",
                on_click=self._select_output_world,
                name="Select output world",
                hint="Choose the world the converted chunks are written into",
            ),
            0,
        )
        inner.Add(output_card, 0, wx.EXPAND | wx.BOTTOM, _px(16))

        actions = wx.BoxSizer(wx.HORIZONTAL)
        self._convert_button = widgets.StudioButton(
            block,
            studio_label("Convert", "轉換"),
            variant="filled",
            on_click=self._run_convert,
            name="Convert",
            hint="Merge the source chunks into the destination world",
        )
        self._convert_button.Enable(self._conversion is None)
        actions.Add(
            self._convert_button, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, _px(14)
        )
        self._convert_error = _Text(
            block,
            self._convert_blocker(),
            size_px=13,
            role="error",
            name="Conversion readiness",
        )
        actions.Add(self._convert_error, 1, wx.ALIGN_CENTER_VERTICAL)
        inner.Add(actions, 0, wx.EXPAND | wx.BOTTOM, _px(10))
        self._convert_progress = _Text(
            block,
            (
                "Converting…"
                if self._conversion is not None
                else studio_text(
                    "Nothing is converting. Progress appears here, counted in "
                    "chunks written, once one starts.",
                    "而家冇轉換緊。開始之後，呢度會顯示已經寫咗幾多個區塊。",
                )
            ),
            size_px=13,
            role="on_surface_variant",
            name="Conversion progress",
        )
        inner.Add(self._convert_progress, 0, wx.EXPAND)
        self._register_width(
            lambda width, text=intro, progress=self._convert_progress: (
                text.set_available_width(min(_px(860), width)),
                progress.set_available_width(min(_px(860), width)),
            )
        )

    def _convert_blocker(self) -> str:
        """Return the honest reason conversion cannot start, or an empty line."""
        if self._conversion is not None:
            return "A conversion is already running. Wait for it to finish."
        world = self._world_context()
        if not world.open or world.level is None:
            return (
                "Open the source world first: conversion reads the chunks out "
                "of the world that is open."
            )
        if not self.convert_output:
            return "Choose the destination world before converting."
        if os.path.normcase(os.path.abspath(self.convert_output)) == os.path.normcase(
            os.path.abspath(world.path or "")
        ):
            return "The destination is the source world. Choose a different folder."
        return ""

    def _select_output_world(self) -> None:
        from amulet_map_editor.api.wx.ui import path_dialog

        chosen = path_dialog.choose_path(
            self, "Choose the destination world folder", directory=True
        )
        if not chosen:
            return
        self.convert_output = chosen
        if self._output_slot is not None:
            name, platform = self._identify_world(Path(chosen))
            self._output_slot.set_text(f"{name} · {platform}\n{chosen}")
        if self._convert_error is not None:
            self._convert_error.set_text(self._convert_blocker())
        if self.content is not None:
            self.content.Layout()
            self.body.FitInside()

    def _run_convert(self) -> None:
        """Start the real conversion, or say exactly why it cannot start.

        The conversion itself is the editor's own Convert extension: the same
        code path, the same loader, the same chunk-by-chunk save, so a world
        converted from here and a world converted from the extension are
        converted by one implementation rather than two that resemble each
        other.  The extension is built without being shown, because what is
        wanted from it is its behaviour and not its layout.
        """
        blocker = self._convert_blocker()
        if blocker:
            if self._convert_error is not None:
                self._convert_error.set_text(blocker)
            self._notify("Conversion not started", blocker, severity="warning")
            return
        world = self._world_context()
        destination = self.convert_output
        try:
            from amulet import load_format
            from amulet_map_editor.programs.convert.convert import ConvertExtension
        except Exception as error:  # noqa: BLE001 - report the real import failure
            self._report_convert_failure("This build cannot convert worlds", str(error))
            return
        try:
            load_format(destination)
        except Exception as error:  # noqa: BLE001 - an unloadable destination
            self._report_convert_failure(
                f"No loader matched {destination}",
                f"{type(error).__name__}: {error}. Choose a destination folder "
                "Amulet can open.",
            )
            return
        try:
            extension = ConvertExtension(self, world.level)
        except Exception as error:  # noqa: BLE001 - the extension refused to build
            self._report_convert_failure(
                "The conversion could not be prepared",
                f"{type(error).__name__}: {error}",
            )
            return
        extension.Hide()
        extension.out_world_path = destination
        # The extension reports progress by calling this with the chunk it has
        # reached and the total; wrapping it rather than replacing it keeps the
        # extension's own gauge correct while the page shows the same figures.
        original = extension._update_loading_bar

        def relay(chunk_index: int, chunk_total: int) -> None:
            original(chunk_index, chunk_total)
            wx.CallAfter(self._show_convert_progress, chunk_index, chunk_total)

        extension._update_loading_bar = relay
        # The extension's own tail raises when it tries to notify from its
        # worker thread, which wx refuses. Swallowing that here keeps a real
        # completion from being reported as a crashed thread; the verdict comes
        # from the log the extension had already written by that point.
        convert_method = extension._convert_method

        def guarded() -> None:
            try:
                convert_method()
            except Exception:  # noqa: BLE001 - the tail, not the conversion
                log.debug(
                    "The conversion extension raised after finishing", exc_info=True
                )

        extension._convert_method = guarded
        self._conversion_log = _ConversionLog()
        logging.getLogger(CONVERT_LOGGER).addHandler(self._conversion_log)
        self._conversion = extension
        if self._convert_button is not None:
            self._convert_button.Enable(False)
        if self._convert_error is not None:
            self._convert_error.set_text("")
        self._show_convert_progress(0, 0)
        try:
            extension._convert_event(None)
        except Exception as error:  # noqa: BLE001 - starting the thread failed
            self._finish_conversion()
            self._report_convert_failure(
                "The conversion did not start", f"{type(error).__name__}: {error}"
            )
            return
        if self._conversion_timer is None:
            self._conversion_timer = wx.Timer(self)
            self.Bind(wx.EVT_TIMER, self._watch_conversion, self._conversion_timer)
        self._conversion_timer.Start(500)
        self._notify(
            "Conversion started",
            f"Writing {world.name or 'the open world'} into {destination}. "
            "Progress is counted in chunks on the Convert page.",
        )

    def _show_convert_progress(self, chunk_index: int, chunk_total: int) -> None:
        """Show the chunk the conversion has genuinely reached."""
        if self._convert_progress is None:
            return
        if chunk_total:
            share = max(0.0, min(1.0, chunk_index / chunk_total))
            text = (
                f"Converting: {int(chunk_index):,} of {int(chunk_total):,} chunks "
                f"written ({share * 100:.1f}%)."
            )
        else:
            text = (
                "Converting: the destination is opening and the chunk count is "
                "not known yet."
            )
        try:
            self._convert_progress.set_text(text)
            self._convert_progress.set_available_width(
                min(_px(860), self._available_width or _px(860))
            )
            if self.content is not None:
                self.content.Layout()
        except RuntimeError:  # pragma: no cover - the page has been rebuilt
            return

    def _watch_conversion(self, _event: wx.TimerEvent) -> None:
        """Notice when the conversion thread has finished, and report its result."""
        extension = self._conversion
        if extension is None:
            self._finish_conversion()
            return
        try:
            running = getattr(extension, "_thread", None) is not None
        except RuntimeError:  # pragma: no cover - the extension has gone
            running = False
        if running:
            return
        succeeded, message = (
            self._conversion_log.verdict()
            if self._conversion_log is not None
            else (None, "")
        )
        destination = self.convert_output
        self._finish_conversion()
        if succeeded is True:
            title, severity = "Conversion finished", "success"
            body = message or f"The chunks were written into {destination}."
        elif succeeded is False:
            title, severity = "Conversion failed", "error"
            body = message
        else:
            title, severity = "Conversion ended without a result", "warning"
            body = (
                "The conversion thread stopped without reporting either a "
                f"success or a failure. Check {destination} before relying on it."
            )
        if self._convert_progress is not None:
            try:
                self._convert_progress.set_text(f"{title}. {body}")
                self._convert_progress.set_available_width(
                    min(_px(860), self._available_width or _px(860))
                )
                if self.content is not None:
                    self.content.Layout()
            except RuntimeError:  # pragma: no cover - the page has been rebuilt
                pass
        self._notify(title, body, severity=severity)

    def _finish_conversion(self) -> None:
        """Let go of the conversion, whatever its outcome was."""
        if self._conversion_timer is not None and self._conversion_timer.IsRunning():
            self._conversion_timer.Stop()
        if self._conversion_log is not None:
            logging.getLogger(CONVERT_LOGGER).removeHandler(self._conversion_log)
            self._conversion_log = None
        extension, self._conversion = self._conversion, None
        if extension is not None:
            try:
                extension.Destroy()
            except RuntimeError:  # pragma: no cover - already destroyed
                pass
        if self._convert_button is not None:
            try:
                self._convert_button.Enable(True)
            except RuntimeError:  # pragma: no cover - the page has been rebuilt
                pass

    def _report_convert_failure(self, title: str, detail: str) -> None:
        """State exactly why a conversion cannot run, on the page and in a toast."""
        if self._convert_error is not None:
            try:
                self._convert_error.set_text(f"{title}: {detail}")
            except RuntimeError:  # pragma: no cover - the page has been rebuilt
                pass
        self._notify(title, detail, severity="error")

    # -- all surfaces --------------------------------------------------------
    def _build_features(self, parent: wx.Panel, sizer: wx.BoxSizer) -> None:
        sizer.Add(
            _heading(parent, "All surfaces", "所有介面", 30),
            0,
            wx.EXPAND | wx.BOTTOM,
            _px(8),
        )
        intro = _body_text(
            parent,
            "Every window, dialog, tool, and pane in the application. Open any of "
            "them here; each is also reachable from the ribbon and the command "
            "palette.",
            "應用程式入面每一個視窗、對話框、工具同面板。喺呢度全部開得；功能區同指令面板一樣搵到。",
        )
        sizer.Add(intro, 0, wx.EXPAND | wx.BOTTOM, _px(22))
        self._register_width(
            lambda width: intro.set_available_width(min(_px(680), width))
        )

        row = wx.BoxSizer(wx.HORIZONTAL)
        search = self._search_bar(
            parent,
            studio_label("Search all surfaces", "搜尋所有介面"),
            self.surface_state,
            on_change=lambda _state: self._refresh_surfaces(),
            min_width=480,
        )
        row.Add(search, 0, wx.RIGHT, _px(8))
        self._surface_count = _Text(
            parent,
            "",
            size_px=12,
            role="on_surface_variant",
            name="Surface result count",
        )
        row.Add(self._surface_count, 1, wx.ALIGN_CENTER_VERTICAL)
        row.Add(
            widgets.StudioButton(
                parent,
                studio_label("Export list…", "匯出清單…"),
                variant="outlined",
                on_click=self._export_surfaces,
                name="Export the surface list",
                hint=(
                    "Write the surfaces matching the current search as JSON, CSV, "
                    "or Markdown"
                ),
            ),
            0,
            wx.ALIGN_CENTER_VERTICAL,
        )
        sizer.Add(row, 0, wx.EXPAND | wx.BOTTOM, _px(18))

        self._surface_host = wx.Panel(parent, style=wx.TAB_TRAVERSAL)
        self._surface_host.SetBackgroundColour(tokens.palette().surface)
        self._surface_host.SetName("Surface index")
        self._surface_host.SetSizer(wx.BoxSizer(wx.VERTICAL))
        sizer.Add(self._surface_host, 1, wx.EXPAND)
        # Registered once and reading the live tuple, so re-running the search
        # replaces the cards without leaving a target pointing at destroyed
        # ones -- a stale target is a repaint that raises on every resize.
        self._register_width(
            lambda width: [
                card.set_available_width(self._column_width(width, 3, _px(10)))
                for card in self._surface_cards
            ]
        )
        self._refresh_surfaces()

    def _load_surfaces(
        self,
    ) -> Tuple[Tuple[str, ...], Dict[str, List[Tuple[str, str, str]]], str]:
        """Return the surface index, grouped, or an honest reason it is missing.

        The index is imported here rather than at module scope precisely
        because the shell imports this view: importing it the other way round
        at module scope makes the two modules depend on each other's import
        order, which fails as an inscrutable partial-module error rather than
        as a missing surface.
        """
        try:
            from amulet_map_editor.api.studio import surfaces
        except Exception as error:  # pragma: no cover - index owned elsewhere
            log.debug("The surface index could not be imported", exc_info=True)
            return (), {}, f"The surface index is not available in this build: {error}"
        try:
            matches = surfaces.search(self.surface_state)
            order = tuple(getattr(surfaces, "SURFACE_GROUPS", ()) or ())
        except Exception as error:  # pragma: no cover - index owned elsewhere
            log.debug("The surface index could not be searched", exc_info=True)
            return (), {}, f"The surface index could not be read: {error}"
        grouped: Dict[str, List[Tuple[str, str, str]]] = {}
        for surface in matches:
            grouped.setdefault(surface.group, []).append(
                (surface.key, surface.label, surface.hint)
            )
        groups = tuple(name for name in order if name in grouped)
        groups += tuple(sorted(name for name in grouped if name not in order))
        return groups, grouped, ""

    def _refresh_surfaces(self) -> None:
        host = getattr(self, "_surface_host", None)
        if host is None:
            return
        sizer = host.GetSizer()
        sizer.Clear(delete_windows=True)
        groups, grouped, problem = self._load_surfaces()
        cards: List[_SurfaceCard] = []
        if problem:
            sizer.Add(
                _Text(
                    host,
                    problem,
                    size_px=13,
                    role="error",
                    wrap_width=self._available_width or _px(680),
                    name="Surface index unavailable",
                ),
                0,
                wx.EXPAND,
            )
            if self._surface_count is not None:
                self._surface_count.set_text("No surfaces could be listed.")
        else:
            total = sum(len(grouped[name]) for name in groups)
            if self._surface_count is not None:
                self._surface_count.set_text(
                    self.surface_state.describe_matches(total, "surface")
                )
            if not total:
                sizer.Add(
                    _Text(
                        host,
                        self.surface_state.describe_matches(0, "surface"),
                        size_px=13,
                        role="on_surface_variant",
                        name="No surfaces match",
                    ),
                    0,
                    wx.EXPAND,
                )
            for name in groups:
                sizer.Add(
                    _eyebrow(host, name, "", 12), 0, wx.EXPAND | wx.BOTTOM, _px(10)
                )
                gap = _px(10)
                grid = wx.GridSizer(3, gap, gap)
                for key, label, hint in grouped[name]:
                    card = _SurfaceCard(
                        host, key, label, hint, on_click=self._open_surface
                    )
                    cards.append(card)
                    grid.Add(card, 0, wx.EXPAND)
                remainder = (-len(grouped[name])) % 3
                for _index in range(remainder):
                    grid.Add(0, 0)
                sizer.Add(grid, 0, wx.EXPAND | wx.BOTTOM, _px(22))
        self._surface_cards = tuple(cards)
        host.Layout()
        self._apply_widths()

    def _export_surfaces(self) -> None:
        """Write the surfaces matching the current search out to a file."""
        groups, grouped, problem = self._load_surfaces()
        if problem:
            self._notify("Nothing to export", problem, severity="warning")
            return
        rows = [
            (key, label, name, hint)
            for name in groups
            for key, label, hint in grouped[name]
        ]
        if not rows:
            self._notify(
                "Nothing to export",
                self.surface_state.describe_matches(0, "surface"),
                severity="warning",
            )
            return
        self._write_export(
            "Export the surface list",
            "amulet-studio-surfaces.json",
            lambda export_format: surface_export_text(export_format, rows),
            count=len(rows),
            noun="surface",
            schema=f"{SURFACE_EXPORT_SCHEMA} v{SURFACE_EXPORT_VERSION}",
        )

    # -- workspace -----------------------------------------------------------
    def _build_workspace(self, parent: wx.Panel, sizer: wx.BoxSizer) -> None:
        block = self._max_width_block(parent, sizer, 860)
        inner = block.GetSizer()
        inner.Add(
            _heading(block, "Workspace", "工作區", 30), 0, wx.EXPAND | wx.BOTTOM, _px(8)
        )
        intro = _body_text(
            block,
            "This build is local-only. There is no sign-in, telemetry, or cloud "
            "storage; the update check reads one immutable release route.",
            "呢個版本只喺本機運作。冇登入、冇遙測、冇雲端儲存；更新檢查淨係讀一條固定嘅發佈路徑。",
        )
        inner.Add(intro, 0, wx.EXPAND | wx.BOTTOM, _px(26))
        gap = _px(16)
        grid = wx.GridSizer(2, gap, gap)

        updates = widgets.Card(block)
        updates_sizer = _card_body(updates)
        updates_sizer.Add(
            _Text(
                updates,
                studio_label("Updates", "更新"),
                size_px=17,
                role="on_surface",
                name="Updates",
            ),
            0,
            wx.EXPAND | wx.BOTTOM,
            _px(8),
        )
        update_text = _Text(
            updates,
            self._update_sentence(),
            size_px=13,
            role="on_surface_variant",
            line_height=1.55,
            wrap_width=_px(340),
            name="Update state",
        )
        updates_sizer.Add(update_text, 0, wx.EXPAND | wx.BOTTOM, _px(14))
        update_row = wx.BoxSizer(wx.HORIZONTAL)
        ready = self.update_status == "ready_to_restart"
        restart = widgets.StudioButton(
            updates,
            studio_label("Restart to install", "重新啟動安裝"),
            variant="filled",
            on_click=lambda: self._run(COMMAND_UPDATE_RESTART),
            name="Restart to install",
            hint=(
                "Restart now and apply the staged update"
                if ready
                else "No update is staged yet, so there is nothing to install."
            ),
        )
        restart.Enable(ready)
        update_row.Add(restart, 0, wx.RIGHT, _px(8))
        update_row.Add(
            widgets.StudioButton(
                updates,
                studio_label("Release notes", "發行說明"),
                variant="outlined",
                on_click=lambda: self._open_surface(SURFACE_CHANGELOG),
                name="Release notes",
                hint="Open the changelog",
            ),
            0,
        )
        updates_sizer.Add(update_row, 0, wx.EXPAND)
        grid.Add(updates, 0, wx.EXPAND)

        memory = widgets.Card(block)
        memory_sizer = _card_body(memory)
        memory_sizer.Add(
            _Text(
                memory,
                studio_label("Global memory", "全域記憶庫"),
                size_px=17,
                role="on_surface",
                name="Global memory",
            ),
            0,
            wx.EXPAND | wx.BOTTOM,
            _px(8),
        )
        memory_text = _Text(
            memory,
            studio_text(
                "Canonical instructions, skills, and sync evidence live in their "
                "own console.",
                "正式指引、技能同同步證據都放喺自己嘅主控台入面。",
            ),
            size_px=13,
            role="on_surface_variant",
            line_height=1.55,
            wrap_width=_px(340),
            name="Global memory description",
        )
        memory_sizer.Add(memory_text, 0, wx.EXPAND | wx.BOTTOM, _px(14))
        memory_sizer.Add(
            widgets.StudioButton(
                memory,
                studio_label("Open memory console", "開啟記憶主控台"),
                variant="tonal",
                on_click=lambda: self._open_surface(SURFACE_MEMORY),
                name="Open memory console",
                hint="Open the memory console",
            ),
            0,
        )
        grid.Add(memory, 0, wx.EXPAND)
        inner.Add(grid, 0, wx.EXPAND)
        self._register_width(
            lambda width, texts=(intro, update_text, memory_text): (
                texts[0].set_available_width(min(_px(860), width)),
                [
                    text.set_available_width(
                        max(
                            _px(200),
                            self._column_width(min(_px(860), width), 2, _px(16))
                            - _px(36),
                        )
                    )
                    for text in texts[1:]
                ],
            )
        )

    def _update_sentence(self) -> str:
        """State the running version and the update state that was reported."""
        try:
            from amulet_map_editor import __version__ as running
        except Exception:  # pragma: no cover - version metadata boundary
            running = "an unknown version"
        staged = self.update_version or ""
        if self.update_status == "ready_to_restart":
            body = (
                f"{staged or 'An update'} is staged and ready. "
                if staged
                else "An update is staged and ready. "
            )
        elif self.update_status == "available":
            body = (
                f"{staged or 'An update'} is available and downloading. "
                if staged
                else "An update is available. "
            )
        elif self.update_status == "up_to_date":
            body = "No newer release was found. "
        elif self.update_status == "failed":
            body = "The last update check failed. "
        else:
            body = "No update check has been reported yet. "
        detail = f" {self.update_detail}" if self.update_detail else ""
        return (
            f"Running {running}. {body}Packages are unsigned by design, so the "
            "operating system may warn about an unknown publisher; the studio "
            f"restarts to apply an update.{detail}"
        )

    # -- shared -------------------------------------------------------------
    def _max_width_block(
        self, parent: wx.Panel, sizer: wx.BoxSizer, max_width: int
    ) -> wx.Panel:
        """Add a column that never grows past the design's own maximum width."""
        block = wx.Panel(parent, style=wx.TAB_TRAVERSAL)
        block.SetBackgroundColour(tokens.palette().surface)
        block.SetName("Page content")
        block.SetSizer(wx.BoxSizer(wx.VERTICAL))
        # Deliberately not wx.EXPAND: in a vertical sizer that flag stretches
        # the item to the full width, which is exactly the cap this block
        # exists to impose.  Proportion still gives it the remaining height.
        sizer.Add(block, 1)
        self._register_width(
            lambda width, target=block, cap=_px(max_width): target.SetMinSize(
                wx.Size(min(cap, width), -1)
            )
        )
        return block

    def _open_surface(self, key: str) -> None:
        widgets.invoke(self.on_surface, key)

    def _run(self, key: str) -> None:
        widgets.invoke(self.on_command, key)

    def _notify(
        self,
        title: str,
        body: str,
        *,
        severity: str = "info",
        details: str = "",
    ) -> None:
        """Report a result without halting whatever the user is doing.

        Imported here rather than at module scope so this module stays
        importable without the notification stack being constructible.
        """
        try:
            from amulet_map_editor.api.wx import nonblocking

            nonblocking.notify(self, title, body, severity=severity, details=details)
        except Exception:  # pragma: no cover - notification boundary
            log.info("%s: %s", title, body)


__all__ = [
    "BULK_ACTIONS",
    "BackstageView",
    "DetectedWorld",
    "MAX_DETECTED_WORLDS",
    "MAX_DETECTED_WORLD_ROWS",
    "OPEN_SOURCES",
    "ProjectMeasurement",
    "RAIL_WIDTH",
    "SURFACE_EXPORT_SCHEMA",
    "SURFACE_EXPORT_VERSION",
    "TABS",
    "TEMPLATES",
    "WorldScan",
    "detect_worlds",
    "minecraft_save_roots",
    "surface_export_text",
]
