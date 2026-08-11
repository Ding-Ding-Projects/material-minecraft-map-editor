"""The workspace properties pane: what is selected, what changed, and why.

Three tabs share one column.  **Properties** reads the current selection back
out of the open world -- its bounds, its volume, the dimension it sits in, how
many chunks it covers, and the block the editor's pointer is on.  **History**
lists the project's own local-history events and restores one, which appends a
new event rather than rewinding: the state you restored from stays in the list
and stays restorable in its turn.  **Notes** is a real note stored with the
project, not a scratch box that empties when the window closes.

Nothing here is held between refreshes.  Every row is read at the moment it is
drawn, and the pane subscribes to the world context so the moment a world
opens, closes, changes dimension, or has its selection redrawn, the rows are
read again.  With no world open the pane says so instead of leaving the last
world's figures on screen.

The pane's own search filters the rows in front of it and reports an honest
count, including the empty one.
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import wx

from amulet_map_editor.api import config, local_history
from amulet_map_editor.api.studio import context, tokens
from amulet_map_editor.api.studio.copy import studio_text
from amulet_map_editor.api.studio.search import SearchState
from amulet_map_editor.api.studio.status_bar import (
    clear_container,
    invalidate_project_history,
    open_studio_menu,
    project_history_events,
    project_key_for,
    restore_history_event,
    single_line,
    studio_canvas,
)
from amulet_map_editor.api.studio.widgets import (
    SearchBar,
    SectionLabel,
    StudioButton,
    elide,
    invoke,
    paint_context,
    point_size,
)

log = logging.getLogger(__name__)

#: The design's properties pane width, in design pixels.
PANEL_WIDTH = 308

#: Narrower than this and a label and its monospaced value start colliding.
MIN_PANEL_WIDTH = 240

#: Config record holding one note per project.  Notes are project content, so
#: they are bounded and stored beside the profile rather than inside the user's
#: world directory.
NOTES_CONFIG_ID = "amulet_studio_project_notes"
MAX_NOTE_LENGTH = 20000

#: The tabs across the top of the pane.
PANE_TABS: Tuple[Tuple[str, str], ...] = (
    ("properties", "Properties"),
    ("history", "History"),
    ("notes", "Notes"),
)

_MEDIUM = getattr(wx, "FONTWEIGHT_MEDIUM", wx.FONTWEIGHT_NORMAL)


@dataclass(frozen=True)
class PropertySection:
    """One titled block of label-and-value rows."""

    title: str
    rows: Tuple[Tuple[str, str], ...] = ()

    def matches(self, state: SearchState) -> "PropertySection":
        """Return this section with only the rows the query keeps."""
        if not state.is_active():
            return self
        if state.matches(self.title):
            return self
        kept = tuple(row for row in self.rows if state.matches(f"{row[0]} {row[1]}"))
        return PropertySection(self.title, kept)


@dataclass(frozen=True)
class ProjectRevision:
    """One event in the project's own local-history repository."""

    commit: str
    message: str
    meta: str
    head: bool = False
    #: The full identifier the history store restores by.  The seven characters
    #: in :attr:`commit` are for a person to read; this is what is restored.
    event_id: str = ""

    def haystack(self) -> str:
        """Return everything a search over the history should look at."""
        return f"{self.commit} {self.message} {self.meta}"


#: What the History tab says when a project has recorded nothing yet.
NO_REVISIONS_YET = studio_text(
    "This project has recorded no revisions yet. Every edit that changes it "
    "adds one, and none of them are ever rewritten.",
    "呢個項目而家仲未有任何版本記錄。每次改動都會加一個，而且永遠唔會改寫舊嘅。",
)

#: What it says when the profile could not hold a history repository at all.
NO_HISTORY_AVAILABLE = studio_text(
    "The project history could not be read from this profile, so no revision "
    "can be listed or restored.",
    "喺呢個設定檔度讀唔到項目歷史，所以列唔到亦都還原唔到任何版本。",
)

#: What the History tab says with no project open to have a history.
NO_PROJECT_HISTORY = studio_text(
    "No world is open, so there is no project history to show.",
    "而家未開世界，所以冇項目歷史可以睇。",
)

#: What the Properties tab says with no world open.
NO_WORLD_PROPERTIES = studio_text(
    "No world is open. Open one from the project screen and this pane will "
    "show what is selected in it.",
    "而家未開世界。喺項目版面開一個，呢一欄就會顯示揀咗啲乜。",
)

#: The record types the studio writes, and how each one reads in the list.  A
#: record type this build does not recognise still appears, named by the type
#: the store recorded, rather than being dropped from the history.
_RECORD_LABELS: Dict[str, str] = {
    "studio revision": "Project edit",
    "studio note": "Project note",
}

#: The shipped lists are empty because both are read from the open project.
DEFAULT_REVISIONS: Tuple[ProjectRevision, ...] = ()
DEFAULT_SECTIONS: Tuple[PropertySection, ...] = ()


def format_timestamp(value: str) -> str:
    """Return a stored UTC timestamp as a local date a person reads."""
    text = str(value or "")
    if not text:
        return ""
    try:
        moment = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if moment.tzinfo is not None:
        moment = moment.astimezone()
    return moment.strftime("%d %b %Y, %H:%M")


def _payload_text(payload: Any, key: str) -> str:
    """Return one field of a recorded payload, or ``""`` when it has none."""
    if isinstance(payload, dict):
        value = payload.get(key)
        if value is not None:
            return str(value)
    return ""


def revision_from_event(event: Any, *, head: bool = False) -> ProjectRevision:
    """Return one history event as the row the History tab draws.

    The message is whatever the event actually recorded.  An event whose
    payload carries no message is named by what it did and what it did it to,
    rather than being given a sentence nobody wrote.
    """
    event_id = str(getattr(event, "event_id", ""))
    action = str(getattr(event, "action", ""))
    record_type = str(getattr(event, "record_type", ""))
    kind = _RECORD_LABELS.get(record_type, record_type or "record")
    payload = getattr(event, "after", None)
    message = _payload_text(payload, "message")
    detail = _payload_text(payload, "detail")
    if not message:
        characters = _payload_text(payload, "characters")
        if characters:
            message = f"{kind} {action}, {characters} characters"
        elif payload is None and action:
            # A deleted or restored record holds no payload to name, so the
            # row says what the event left behind rather than inventing a
            # description of work nobody recorded.
            message = f"{kind} {action}, leaving nothing recorded"
        else:
            message = f"{kind} {action}" if action else kind
    parts = [event_id[:7], format_timestamp(getattr(event, "timestamp", ""))]
    parts.append(detail or action or kind)
    return ProjectRevision(
        commit=event_id[:7],
        message=message,
        meta=" · ".join(part for part in parts if part),
        head=bool(head),
        event_id=event_id,
    )


def load_project_revisions(
    project_key: str, *, refresh: bool = False
) -> Tuple[Tuple[ProjectRevision, ...], bool]:
    """Return one project's revisions, newest first, and whether they read.

    The second value separates a project that has recorded nothing from a
    history that could not be read at all, which are different things to say
    and would otherwise both render as an empty list.
    """
    events, available = project_history_events(project_key, refresh=refresh)
    revisions = tuple(
        revision_from_event(event, head=index == 0)
        for index, event in enumerate(events)
    )
    return revisions, available


def cursor_location(canvas: Any = None) -> Optional[Tuple[int, int, int]]:
    """Return the block the editor's pointer is on, or ``None``.

    The pointer belongs to whichever tool is active rather than to the canvas,
    so the canvas is asked first and each of its tools afterwards.  Nothing is
    substituted when no tool is reporting one: the camera's own position is not
    the cursor, and showing it as though it were would be a number the user
    could not act on.
    """
    target = studio_canvas() if canvas is None else canvas
    if target is None:
        return None
    candidates: List[Any] = [target]
    try:
        candidates.extend(target.tools.values())
    except Exception:  # noqa: BLE001 - a canvas with no tool sizer yet
        pass
    for candidate in list(candidates):
        try:
            candidates.extend(vars(candidate).values())
        except TypeError:  # pragma: no cover - an object with no __dict__
            continue
    for candidate in candidates:
        point = getattr(candidate, "pointer_base", None)
        if point is None:
            continue
        try:
            x, y, z = (int(value) for value in point)
        except Exception:  # noqa: BLE001 - not a coordinate triple
            continue
        return (x, y, z)
    return None


def cursor_block(
    ctx: Optional[context.WorldContext] = None,
) -> Tuple[str, str]:
    """Return the block under the editor's pointer, and where it is.

    The block is translated back into the version the world is saved in, so the
    name is the one the user would see in the game rather than the universal
    palette entry the editor stores it as.  Both halves are empty when the
    editor is not reporting a pointer.
    """
    if ctx is None:
        ctx = context.current()
    if not ctx.open or ctx.level is None:
        return "", ""
    point = cursor_location()
    if point is None:
        return "", ""
    where = f"{point[0]}, {point[1]}, {point[2]}"
    try:
        block = ctx.level.get_block(point[0], point[1], point[2], ctx.dimension)
    except Exception as err:  # noqa: BLE001 - an ungenerated or broken chunk
        # A chunk nobody has generated and a chunk that will not load are
        # different facts, and merging them would hide a corrupt region behind
        # an ordinary empty one.
        if type(err).__name__ == "ChunkDoesNotExist":
            return "that chunk is not generated", where
        return f"not readable ({type(err).__name__})", where
    try:
        platform, version = ctx.level.level_wrapper.max_world_version
        translator = ctx.level.translation_manager.get_version(platform, version).block
        converted = translator.from_universal(block)[0]
        return str(getattr(converted, "full_blockstate", None) or converted), where
    except Exception:  # noqa: BLE001 - a block this version has no name for
        return f"{block.full_blockstate} (universal)", where


def world_sections(
    ctx: Optional[context.WorldContext] = None,
) -> Tuple[PropertySection, ...]:
    """Describe the open world's selection, dimension, and head revision.

    Every row here was read from the level a moment before it was built.  A
    fact the world does not record is stated as absent rather than filled in.
    """
    if ctx is None:
        ctx = context.current()
    if not ctx.open:
        return ()

    selection_rows: List[Tuple[str, str]] = []
    bounds = ctx.selection_bounds()
    if bounds is None or not ctx.selection_boxes:
        selection_rows.append(("Selection", "nothing selected"))
    else:
        low, high = bounds
        extent = tuple(max(0, high[axis] - low[axis]) for axis in range(3))
        # The level stores the far corner one block past the last block the
        # box contains, which is the arithmetic the editor wants and not the
        # coordinate a user reads off the viewport, so the last contained
        # block is what is shown.
        last = tuple(
            high[axis] - 1 if extent[axis] else high[axis] for axis in range(3)
        )
        # With more than one box the extent describes the box that encloses
        # them all while the volume counts the blocks they actually cover, and
        # those are different numbers.  Each is labelled for what it is rather
        # than being left side by side to be read as one measurement.
        many = len(ctx.selection_boxes) > 1
        selection_rows.extend(
            [
                ("Boxes", str(len(ctx.selection_boxes))),
                ("Minimum", ", ".join(str(value) for value in low)),
                ("Maximum", ", ".join(str(value) for value in last)),
                (
                    "Bounding size" if many else "Size",
                    "x".join(str(value) for value in extent),
                ),
                (
                    "Selected volume" if many else "Volume",
                    f"{ctx.selection_volume:,} "
                    + ("block" if ctx.selection_volume == 1 else "blocks"),
                ),
                ("Chunks", f"{len(ctx.selection_chunks()):,}"),
            ]
        )
    block, where = cursor_block(ctx)
    if block:
        selection_rows.append(("Block at cursor", block))
        selection_rows.append(("Cursor", where))
    else:
        selection_rows.append(("Block at cursor", "the editor is not reporting one"))

    info = ctx.current_dimension()
    dimension_rows: List[Tuple[str, str]] = [
        ("Dimension", ctx.dimension or "none reported"),
        (
            "Height range",
            (
                f"{info.min_y} to {info.max_y}"
                if info is not None and info.has_range
                else "not reported"
            ),
        ),
        (
            "Chunks stored",
            (
                "not readable"
                if info is not None and not info.counted
                else f"{ctx.chunk_count:,}" + ("+" if info and info.truncated else "")
            ),
        ),
        ("Dimensions", str(len(ctx.dimension_info))),
    ]

    world_rows: List[Tuple[str, str]] = [
        ("World", ctx.name or "not recorded"),
        (
            "Version",
            ctx.game_version
            or " ".join(part for part in (ctx.platform, ctx.version) if part)
            or "not reported",
        ),
        ("Seed", ctx.seed or ctx.reason("seed") or "not recorded"),
        (
            "Spawn",
            (
                ", ".join(str(value) for value in ctx.spawn)
                if ctx.spawn is not None
                else ctx.reason("spawn") or "not recorded"
            ),
        ),
    ]

    revisions, available = load_project_revisions(project_key_for(ctx))
    revision_rows: List[Tuple[str, str]] = []
    if not available:
        revision_rows.append(("History", "could not be read from this profile"))
    elif not revisions:
        revision_rows.append(("History", "nothing recorded yet"))
    else:
        head = revisions[0]
        committed = [part.strip() for part in head.meta.split("·")]
        revision_rows.extend(
            [
                ("Head", head.commit),
                ("Message", head.message),
                ("Recorded", committed[1] if len(committed) > 1 else head.meta),
                ("Revisions", f"{len(revisions):,}"),
            ]
        )

    return (
        PropertySection("Selection", tuple(selection_rows)),
        PropertySection("Dimension", tuple(dimension_rows)),
        PropertySection("World", tuple(world_rows)),
        PropertySection("Revision", tuple(revision_rows)),
    )


def load_notes() -> Dict[str, str]:
    """Return every stored project note, keyed by project."""
    raw = config.get(NOTES_CONFIG_ID, {})
    if not isinstance(raw, dict):
        return {}
    return {str(key): str(value) for key, value in raw.items()}


def note_for(project_key: str) -> str:
    """Return the note stored for one project, or an empty string."""
    return load_notes().get(str(project_key), "")


def store_note(project_key: str, text: str) -> bool:
    """Persist one project's note, returning whether it reached disk.

    An unwritable profile is reported to the caller rather than swallowed: a
    note the user believes was saved and was not is worse than being told the
    save failed.
    """
    key = str(project_key)
    if not key:
        return False
    try:
        notes = load_notes()
        notes[key] = str(text)[:MAX_NOTE_LENGTH]
        config.put(NOTES_CONFIG_ID, notes)
    except OSError:
        log.exception("Could not store the note for project %r", key)
        return False
    local_history.safe_record(
        f"studio-note-{key}",
        {"project": key, "characters": len(str(text)[:MAX_NOTE_LENGTH])},
        record_type="studio note",
    )
    return True


class PropertyRow(wx.Control):
    """One label on the left, one monospaced value on the right."""

    PADDING_X = 11
    PADDING_Y = 9

    def __init__(self, parent: wx.Window, label: str, value: str) -> None:
        super().__init__(parent, style=wx.BORDER_NONE)
        self.label = str(label)
        self.value = str(value)
        self.SetName(f"{self.label}: {self.value}")
        self.SetToolTip(f"{self.label}: {self.value}")
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
        dc.SetFont(tokens.font(self, point_size(12)))
        label_width, label_height = dc.GetTextExtent(self.label or " ")
        dc.SetFont(tokens.mono_font(self, point_size(12)))
        value_width, value_height = dc.GetTextExtent(self.value or " ")
        return wx.Size(
            label_width + value_width + tokens.scaled(self.PADDING_X * 2 + 10),
            max(label_height, value_height) + tokens.scaled(self.PADDING_Y) * 2,
        )

    def refresh_theme(self) -> None:
        """Re-measure for the live density and repaint."""
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
        tokens.draw_round_rect(
            gcdc,
            wx.Rect(0, 0, width, height),
            tokens.scaled(tokens.RADIUS_SM + 1),
            palette.surface,
            palette.outline_variant,
        )
        inset = tokens.scaled(self.PADDING_X)
        gcdc.SetFont(tokens.mono_font(self, point_size(12)))
        value = elide(gcdc, self.value, max(0, width - inset * 2))
        value_width = gcdc.GetTextExtent(value)[0]
        gcdc.SetTextForeground(palette.on_surface)
        gcdc.DrawText(
            value, width - inset - value_width, (height - gcdc.GetCharHeight()) // 2
        )
        gcdc.SetFont(tokens.font(self, point_size(12)))
        gcdc.SetTextForeground(palette.on_surface_variant)
        available = max(0, width - inset * 2 - value_width - tokens.scaled(10))
        gcdc.DrawText(
            elide(gcdc, self.label, available),
            inset,
            (height - gcdc.GetCharHeight()) // 2,
        )
        del gcdc


class RevisionRow(wx.Panel):
    """One revision: what it changed, when, and a way back to it."""

    def __init__(
        self,
        parent: wx.Window,
        revision: ProjectRevision,
        *,
        on_restore: Optional[Callable[[str], None]] = None,
    ) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self.revision = revision
        self.on_restore = on_restore
        state = " (head)" if revision.head else ""
        self.SetName(f"Revision {revision.message}{state}, {revision.meta}")
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.restore_button = StudioButton(
            self,
            studio_text("Restore"),
            variant="outlined",
            height=28,
            on_click=self._restore,
            hint=single_line(
                studio_text(
                    "Restoring writes a new revision, so this one stays undoable.",
                    "還原會寫多個新版本，所以呢個版本一樣仲可以還原返。",
                )
            ),
            name=f"Restore revision {revision.commit}",
        )
        row = wx.BoxSizer(wx.HORIZONTAL)
        row.AddStretchSpacer(1)
        row.Add(self.restore_button, 0, wx.ALIGN_CENTER_VERTICAL)
        frame = wx.BoxSizer(wx.VERTICAL)
        frame.AddSpacer(tokens.scaled(38))
        frame.Add(row, 0, wx.EXPAND | wx.ALL, tokens.scaled(10))
        self.SetSizer(frame)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self._apply_theme()

    def _restore(self) -> None:
        invoke(self.on_restore, self.revision.commit)

    def _apply_theme(self) -> None:
        self.SetBackgroundColour(tokens.palette().surface_container)

    def refresh_theme(self) -> None:
        """Re-read the palette for the row and its button."""
        self._apply_theme()
        self.restore_button.refresh_theme()
        self.Refresh()

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        palette = tokens.palette()
        dc, gcdc = paint_context(self, palette.surface_container)
        width, height = self.GetClientSize()
        tokens.draw_round_rect(
            gcdc,
            wx.Rect(0, 0, width, height),
            tokens.scaled(tokens.RADIUS_SM + 1),
            palette.surface,
            palette.primary if self.revision.head else palette.outline_variant,
        )
        left = tokens.scaled(11)
        dot = tokens.scaled(9)
        top = tokens.scaled(14)
        gcdc.SetPen(wx.TRANSPARENT_PEN)
        gcdc.SetBrush(
            wx.Brush(palette.primary if self.revision.head else palette.outline_variant)
        )
        gcdc.DrawEllipse(left, top, dot, dot)
        text_left = left + dot + tokens.scaled(10)
        available = max(0, width - text_left - tokens.scaled(11))
        gcdc.SetFont(tokens.font(self, point_size(12), _MEDIUM))
        gcdc.SetTextForeground(palette.on_surface)
        gcdc.DrawText(
            elide(gcdc, self.revision.message, available), text_left, tokens.scaled(10)
        )
        gcdc.SetFont(tokens.mono_font(self, point_size(11)))
        gcdc.SetTextForeground(palette.on_surface_variant)
        gcdc.DrawText(
            elide(gcdc, self.revision.meta, available),
            text_left,
            tokens.scaled(10) + gcdc.GetCharHeight() + tokens.scaled(4),
        )
        del gcdc


class TabPill(StudioButton):
    """One of the pane's pill tabs, filled while it is the open one."""

    def __init__(
        self,
        parent: wx.Window,
        key: str,
        label: str,
        *,
        selected: bool = False,
        on_click: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.key = str(key)
        self.selected = bool(selected)
        self._on_pick = on_click
        super().__init__(
            parent,
            label,
            variant="pill",
            on_click=self._pick,
            height=28,
            hint=f"Show {label}",
        )
        self._sync_name()

    def _pick(self) -> None:
        invoke(self._on_pick, self.key)

    def _sync_name(self) -> None:
        state = "selected" if self.selected else "not selected"
        self.SetName(f"{self.GetLabel()} tab, {state}")

    def set_selected(self, selected: bool) -> None:
        """Mark the tab as the open one, or not."""
        self.selected = bool(selected)
        self._sync_name()
        self.Refresh()

    def _state_colours(
        self, palette: tokens.StudioPalette
    ) -> Tuple[Optional[wx.Colour], wx.Colour, Optional[wx.Colour]]:
        if self.selected:
            fill = palette.primary_container
            if self._pressed:
                fill = tokens.blend(fill, palette.primary, 0.18)
            elif self._hovered:
                fill = tokens.blend(fill, palette.primary, 0.10)
            return fill, palette.on_primary_container, palette.primary_container
        fill: Optional[wx.Colour] = None
        if self._pressed:
            fill = tokens.blend(
                palette.surface_container_high, palette.on_surface, 0.10
            )
        elif self._hovered:
            fill = palette.surface_container_high
        return fill, palette.on_surface_variant, None


class PropertiesPane(wx.Panel):
    """The 308px column on the right of the workspace."""

    WIDTH = PANEL_WIDTH
    MIN_WIDTH = MIN_PANEL_WIDTH

    def __init__(
        self,
        parent: wx.Window,
        *,
        title: str = "Box 1",
        project_key: str = "",
        sections: Sequence[PropertySection] = DEFAULT_SECTIONS,
        revisions: Sequence[ProjectRevision] = DEFAULT_REVISIONS,
        on_close: Optional[Callable[[], None]] = None,
        on_action: Optional[Callable[[str], None]] = None,
        on_restore: Optional[Callable[[str], None]] = None,
        on_surface: Optional[Callable[[str], None]] = None,
        on_command: Optional[Callable[[str], None]] = None,
    ) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self.on_close = on_close
        self.on_action = on_action
        self.on_restore = on_restore
        self.on_surface = on_surface
        self.on_command = on_command
        self.sections: List[PropertySection] = list(sections)
        self.revisions: List[ProjectRevision] = list(revisions)
        self.project_key = str(project_key)
        self.tab = "properties"
        self.search_state = SearchState(label="Properties")
        self._note_dirty = False
        self._note_key = self.active_project_key()
        self._live_revisions: List[ProjectRevision] = []
        self._history_available = True
        self.SetName("Properties pane")
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)

        self.title_label = wx.StaticText(self, label=str(title))
        self.title_label.SetName("Properties pane title")
        self.appearance_button = StudioButton(
            self,
            "",
            variant="icon",
            glyph="✎",
            height=26,
            min_width=26,
            on_click=self.open_appearance_editor,
            hint="Edit appearance for this pane",
            name="Edit appearance",
        )
        self.close_button = StudioButton(
            self,
            "",
            variant="icon",
            glyph="×",
            height=26,
            min_width=26,
            on_click=self._close,
            hint="Close the properties pane",
            name="Close the properties pane",
        )
        self.tab_buttons: Dict[str, TabPill] = {}
        tab_row = wx.BoxSizer(wx.HORIZONTAL)
        for key, label in PANE_TABS:
            pill = TabPill(
                self, key, label, selected=key == self.tab, on_click=self.set_tab
            )
            self.tab_buttons[key] = pill
            tab_row.Add(pill, 0, wx.RIGHT, tokens.scaled(2))
        self.search = SearchBar(
            self,
            "Search these properties",
            self.search_state,
            on_change=self._on_search,
            compact=True,
        )
        self.scroller = wx.ScrolledWindow(self, style=wx.VSCROLL | wx.TAB_TRAVERSAL)
        self.scroller.SetScrollRate(0, tokens.scaled(12))
        self.scroller.SetName("Properties pane contents")
        self.body = wx.BoxSizer(wx.VERTICAL)
        self.scroller.SetSizer(self.body)
        self.status_label = wx.StaticText(self.scroller, label="")
        self.status_label.SetName("Properties pane search result")
        self.empty_note = wx.StaticText(self.scroller, label="")
        self.empty_note.SetName("Properties pane state")
        self.notes_field = wx.TextCtrl(
            self.scroller,
            value=note_for(self._note_key),
            style=wx.TE_MULTILINE | wx.TE_RICH2,
        )
        self.notes_field.SetName("Project note")
        self.notes_field.SetHint(
            single_line(
                studio_text(
                    "Write anything this project needs remembered.",
                    "呢個項目要記住嘅嘢，寫低喺度。",
                )
            )
        )
        self.notes_field.SetMaxLength(MAX_NOTE_LENGTH)
        self.notes_field.SetMinSize(wx.Size(-1, tokens.scaled(160)))
        self.notes_field.Bind(wx.EVT_TEXT, self._on_note_changed)
        self.notes_field.Bind(wx.EVT_KILL_FOCUS, self._on_note_focus_lost)
        self.notes_status = wx.StaticText(self.scroller, label="")
        self.notes_status.SetName("Project note status")
        self.action_button = StudioButton(
            self,
            "",
            variant="filled",
            on_click=self._run_action,
            name="Pane action",
        )

        header = wx.BoxSizer(wx.HORIZONTAL)
        header.Add(self.title_label, 1, wx.ALIGN_CENTER_VERTICAL)
        header.Add(
            self.appearance_button,
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            tokens.scaled(tokens.SPACE_SM),
        )
        header.Add(
            self.close_button,
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            tokens.scaled(tokens.SPACE_XS),
        )
        pad = tokens.scaled(tokens.SPACE_SM + 4)
        frame = wx.BoxSizer(wx.VERTICAL)
        frame.Add(header, 0, wx.EXPAND | wx.ALL, pad)
        frame.Add(tab_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, tokens.scaled(10))
        frame.Add(
            self.search,
            0,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP,
            tokens.scaled(tokens.SPACE_MD - 2),
        )
        frame.Add(
            self.scroller,
            1,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP,
            tokens.scaled(tokens.SPACE_MD - 2),
        )
        frame.Add(
            self.action_button,
            0,
            wx.EXPAND | wx.ALL,
            tokens.scaled(tokens.SPACE_MD - 2),
        )
        self.SetSizer(frame)
        self.SetMinSize(wx.Size(tokens.scaled(self.MIN_WIDTH), -1))
        self.SetSize(wx.Size(tokens.scaled(self.WIDTH), -1))

        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.Bind(wx.EVT_CONTEXT_MENU, self._on_context_menu)
        self.Bind(wx.EVT_WINDOW_DESTROY, self._on_destroy)
        self.scroller.Bind(wx.EVT_CONTEXT_MENU, self._on_context_menu)
        context.subscribe(self._on_world_context)
        self._apply_theme()
        self.refresh_history()
        self.rebuild()

    # -- the open world ------------------------------------------------------
    def active_project_key(self) -> str:
        """Return the project whose note and history this pane is showing.

        The open world wins over whatever the owner last named, because the
        world is the thing the notes and the history actually belong to and it
        is the one the user is looking at.
        """
        return project_key_for() or self.project_key

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
        """Re-read every tab from the world that is open right now."""
        try:
            if self.IsBeingDeleted():
                return
        except RuntimeError:
            return
        key = self.active_project_key()
        if key != self._note_key:
            if self._note_dirty:
                self.save_note()
            self._note_key = key
            self.notes_field.ChangeValue(note_for(key))
            self._note_dirty = False
        self.refresh_history()
        self.rebuild()

    def refresh_history(self, *, reread: bool = False) -> None:
        """Re-read the project's revisions from its own local history."""
        revisions, available = load_project_revisions(
            self.active_project_key(), refresh=reread
        )
        self._live_revisions = list(revisions)
        self._history_available = bool(available)

    def _on_destroy(self, event: wx.WindowDestroyEvent) -> None:
        if event.GetEventObject() is self:
            context.unsubscribe(self._on_world_context)
        event.Skip()

    # -- content -------------------------------------------------------------
    def set_title(self, title: str) -> None:
        """Name what the pane is describing."""
        self.title_label.SetLabel(single_line(title))
        self.title_label.SetName(f"Properties for {single_line(title)}")
        self.Layout()

    def visible_sections(self) -> Tuple[PropertySection, ...]:
        """Return the rows the Properties tab shows right now.

        The open world is the source whenever there is one, read at the moment
        this is called rather than kept from the last push.  Sections the owner
        supplied are what is left when no world is open, which is when there is
        nothing to read.
        """
        live = world_sections()
        return live if live else tuple(self.sections)

    def visible_revisions(self) -> Tuple[ProjectRevision, ...]:
        """Return the revisions the History tab shows right now."""
        if self._history_available:
            return tuple(self._live_revisions)
        return tuple(self.revisions)

    def set_sections(self, sections: Sequence[PropertySection]) -> None:
        """Set the rows shown when no world is open to read them from."""
        self.sections = list(sections)
        if self.tab == "properties":
            self.rebuild()

    def set_revisions(self, revisions: Sequence[ProjectRevision]) -> None:
        """Set the revisions shown when the local history cannot be read."""
        self.revisions = list(revisions)
        if self.tab == "history":
            self.rebuild()

    def set_project(self, project_key: str, title: str = "") -> None:
        """Point the pane at another project, loading that project's note."""
        if self._note_dirty:
            self.save_note()
        self.project_key = str(project_key)
        self._note_key = self.active_project_key()
        self.notes_field.ChangeValue(note_for(self._note_key))
        self._note_dirty = False
        if title:
            self.set_title(title)
        self.refresh_history()
        self.rebuild()

    def set_tab(self, key: str) -> None:
        """Open one of the three tabs."""
        if key not in self.tab_buttons:
            return
        self.tab = key
        for name, pill in self.tab_buttons.items():
            pill.set_selected(name == key)
        self.search_state.label = dict(PANE_TABS)[key]
        if key == "history":
            self.refresh_history(reread=True)
        self.rebuild()

    def _set_empty_note(self, text: str) -> None:
        """Show one wrapped empty-state line, or none at all.

        The label is set before it is wrapped every time, because wrapping
        writes newlines into the label and wrapping an already-wrapped string
        again would break it into progressively shorter fragments.
        """
        message = single_line(text)
        self.empty_note.SetLabel(message)
        self.empty_note.SetName(
            f"Properties pane state: {message}" if message else "Properties pane state"
        )
        if message:
            self.empty_note.Wrap(
                max(tokens.scaled(160), self.GetClientSize().width - tokens.scaled(32))
            )
        self.empty_note.Show(bool(message))

    def rebuild(self) -> None:
        """Rebuild the open tab's body from the open world and the query."""
        state = self.search_state
        clear_container(
            self.body,
            self.scroller,
            keep=(
                self.status_label,
                self.empty_note,
                self.notes_field,
                self.notes_status,
            ),
        )
        self.notes_field.Show(self.tab == "notes")
        self.notes_status.Show(self.tab == "notes")
        gap = tokens.scaled(tokens.SPACE_SM - 1)
        self._set_empty_note("")

        if self.tab == "properties":
            sections = self.visible_sections()
            kept = 0
            for section in sections:
                filtered = section.matches(state)
                if not filtered.rows:
                    continue
                kept += len(filtered.rows)
                self.body.Add(
                    SectionLabel(self.scroller, filtered.title),
                    0,
                    wx.EXPAND | wx.BOTTOM,
                    tokens.scaled(tokens.SPACE_SM),
                )
                for label, value in filtered.rows:
                    self.body.Add(
                        PropertyRow(self.scroller, label, value),
                        0,
                        wx.EXPAND | wx.BOTTOM,
                        gap,
                    )
                self.body.AddSpacer(tokens.scaled(tokens.SPACE_SM))
            if not sections:
                self._set_empty_note(NO_WORLD_PROPERTIES)
                self.body.Add(self.empty_note, 0, wx.EXPAND | wx.BOTTOM, gap)
            self.status_label.SetLabel(
                state.describe_matches(kept, "property") if state.is_active() else ""
            )
        elif self.tab == "history":
            revisions = self.visible_revisions()
            matched = [
                revision for revision in revisions if state.matches(revision.haystack())
            ]
            for revision in matched:
                self.body.Add(
                    RevisionRow(self.scroller, revision, on_restore=self._restore),
                    0,
                    wx.EXPAND | wx.BOTTOM,
                    gap,
                )
            if not revisions:
                self._set_empty_note(self._history_note())
                self.body.Add(self.empty_note, 0, wx.EXPAND | wx.BOTTOM, gap)
            self.status_label.SetLabel(
                state.describe_matches(len(matched), "revision")
                if state.is_active()
                else (f"{len(matched)} revisions · newest first" if matched else "")
            )
        else:
            self.body.Add(self.notes_field, 0, wx.EXPAND | wx.BOTTOM, gap)
            self.body.Add(self.notes_status, 0, wx.EXPAND | wx.BOTTOM, gap)
            self._set_note_status(
                studio_text(
                    "Stored with the project.",
                    "會同項目一齊存住。",
                )
            )
            self.status_label.SetLabel(
                single_line(
                    studio_text(
                        "The search filters the Properties and History tabs.",
                        "個搜尋係篩「屬性」同「歷史」嗰兩版。",
                    )
                )
                if state.is_active()
                else ""
            )

        self.status_label.Show(bool(self.status_label.GetLabel()))
        if self.status_label.GetLabel():
            self.body.Add(self.status_label, 0, wx.EXPAND | wx.TOP, gap)
        label, _handler = self._action_for_tab()
        self.action_button.SetLabel(label)
        self.action_button.SetName(single_line(label))
        self.scroller.FitInside()
        self.scroller.Layout()
        self.Layout()
        self._apply_theme()

    def _history_note(self) -> str:
        """Return why the History tab has nothing to list."""
        if not self._history_available:
            return NO_HISTORY_AVAILABLE
        if not self.active_project_key():
            return NO_PROJECT_HISTORY
        return NO_REVISIONS_YET

    # -- actions -------------------------------------------------------------
    def _action_for_tab(self) -> Tuple[str, Callable[[], None]]:
        """Return the primary action for the open tab: its label and its work."""
        if self.tab == "history":
            return (
                studio_text("Open project history", "開項目歷史"),
                lambda: invoke(self.on_surface, "history"),
            )
        if self.tab == "notes":
            return (studio_text("Save note", "儲存筆記"), self.save_note)
        return (
            studio_text("Frame selection", "對準選取範圍"),
            lambda: invoke(self.on_action, "frame"),
        )

    def _run_action(self) -> None:
        _label, handler = self._action_for_tab()
        handler()

    def _restore(self, commit: str) -> None:
        """Restore the revision a row names, then tell the owner it happened.

        The restore is done here rather than handed to the owner, because the
        history the row came from is the one that has to be written back to;
        the callback still fires so the workspace can react, and it fires only
        once the store has genuinely accepted the new event.
        """
        self.restore_revision(commit)

    def restore_revision(self, commit: str) -> Optional[ProjectRevision]:
        """Restore one revision by appending a new one, and re-read the list."""
        target = next(
            (
                revision
                for revision in self.visible_revisions()
                if revision.commit == str(commit) or revision.event_id == str(commit)
            ),
            None,
        )
        if target is None or not target.event_id:
            log.debug("No history event %r to restore", commit)
            invoke(self.on_restore, commit)
            return None
        restored = restore_history_event(target.event_id)
        if restored is None:
            self._set_note_status(
                studio_text(
                    "That revision could not be restored.",
                    "還原唔到嗰個版本。",
                )
            )
            log.debug("The history store refused to restore %r", target.event_id)
            invoke(self.on_restore, commit)
            return None
        invalidate_project_history()
        self.refresh_history(reread=True)
        self.rebuild()
        invoke(self.on_restore, target.commit)
        return target

    def _close(self) -> None:
        invoke(self.on_close)

    def open_appearance_editor(self) -> None:
        """Open the shared per-element appearance editor for this pane."""
        try:
            from amulet_map_editor.api.wx.ui import element_appearance
        except ImportError:
            log.debug("The element appearance editor is not available")
            return
        try:
            element_appearance.open_element_appearance(self)
        except Exception:
            log.exception("Could not open the appearance editor for the pane")

    # -- notes ---------------------------------------------------------------
    def note(self) -> str:
        """Return the note text currently in the field."""
        return self.notes_field.GetValue()

    def save_note(self) -> bool:
        """Write the note to the project's record and say whether it landed."""
        key = self.active_project_key()
        if not key:
            self._set_note_status(
                studio_text(
                    "No project is open, so there is nowhere to store this note yet.",
                    "而家未開項目，所以呢個筆記暫時冇地方擺。",
                )
            )
            return False
        saved = store_note(key, self.note())
        if saved:
            invalidate_project_history(key)
        self._note_dirty = not saved
        self._set_note_status(
            studio_text("Saved with the project.", "已經同項目一齊存好。")
            if saved
            else studio_text(
                "The note could not be written to your profile.",
                "呢個筆記寫唔入你個設定檔。",
            )
        )
        return saved

    def _set_note_status(self, text: str) -> None:
        self.notes_status.SetLabel(single_line(text))
        self.notes_status.SetName(f"Project note status: {single_line(text)}")
        self.Layout()

    def _on_note_changed(self, event: wx.CommandEvent) -> None:
        self._note_dirty = True
        self._set_note_status(
            studio_text("Unsaved changes.", "仲未儲存。"),
        )
        event.Skip()

    def _on_note_focus_lost(self, event: wx.FocusEvent) -> None:
        if self._note_dirty:
            self.save_note()
        event.Skip()

    # -- events --------------------------------------------------------------
    def _on_search(self, _state: SearchState) -> None:
        self.rebuild()

    def _on_context_menu(self, event: wx.ContextMenuEvent) -> None:
        position = event.GetPosition()
        if position == wx.DefaultPosition:
            size = self.GetSize()
            position = self.ClientToScreen(wx.Point(size.width // 2, size.height // 3))
        open_studio_menu(self, "pane", position, self.on_surface, self.on_command)

    # -- appearance ----------------------------------------------------------
    def _apply_theme(self) -> None:
        palette = tokens.palette()
        self.SetBackgroundColour(palette.surface_container)
        self.scroller.SetBackgroundColour(palette.surface_container)
        self.title_label.SetForegroundColour(palette.on_surface)
        self.title_label.SetFont(tokens.font(self, point_size(14), _MEDIUM))
        for label in (self.status_label, self.notes_status, self.empty_note):
            label.SetForegroundColour(palette.on_surface_variant)
            label.SetFont(tokens.font(self, point_size(11)))
        self.notes_field.SetBackgroundColour(palette.surface)
        self.notes_field.SetForegroundColour(palette.on_surface)
        self.notes_field.SetFont(tokens.font(self, point_size(12)))

    def refresh_theme(self) -> None:
        """Re-read the palette for the pane and every row in it."""
        self._apply_theme()
        for child in list(self.GetChildren()) + list(self.scroller.GetChildren()):
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
        gcdc.DrawLine(0, 0, 0, height)
        tabs_bottom = self.search.GetPosition().y - tokens.scaled(tokens.SPACE_SM)
        if 0 < tabs_bottom < height:
            gcdc.DrawLine(0, tabs_bottom, width, tabs_bottom)
        del gcdc


__all__ = [
    "DEFAULT_REVISIONS",
    "DEFAULT_SECTIONS",
    "MAX_NOTE_LENGTH",
    "MIN_PANEL_WIDTH",
    "NOTES_CONFIG_ID",
    "NO_HISTORY_AVAILABLE",
    "NO_PROJECT_HISTORY",
    "NO_REVISIONS_YET",
    "NO_WORLD_PROPERTIES",
    "PANEL_WIDTH",
    "PANE_TABS",
    "ProjectRevision",
    "PropertiesPane",
    "PropertyRow",
    "PropertySection",
    "RevisionRow",
    "TabPill",
    "cursor_block",
    "cursor_location",
    "format_timestamp",
    "load_notes",
    "load_project_revisions",
    "note_for",
    "revision_from_event",
    "store_note",
    "world_sections",
]
