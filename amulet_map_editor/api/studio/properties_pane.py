"""The workspace properties pane: what is selected, what changed, and why.

Three tabs share one column, and a fourth appears while an editing tool is
running.  **Properties** reads the current selection back out of the open world
-- its bounds, its volume, the dimension it sits in, how many chunks it covers,
and the block the editor's pointer is on.  **History** lists the project's own
local-history events and restores one, which appends a new event rather than
rewinding: the state you restored from stays in the list and stays restorable
in its turn.  **Notes** is a real note stored with the project, not a scratch
box that empties when the window closes.

**Tool** is where an editing tool's options live.  Clone, Move, Select block,
Edit chunk, Generate, Paste, Import and Export are in-canvas tools with their
handles drawn over the world, so their options belong beside the viewport
rather than in a window floating on top of it: the tool starts, the world stays
visible, and this column shows what it is holding.  For Clone and Move that is
a live pending object, and the tab shows its position, rotation and scale as
editable values, a nudge control for each axis, the keys the viewport moves it
with, and the two ways out -- confirm it into the world, or cancel and write
nothing.  Every value here is read from and written to the tool's own inputs
through :mod:`amulet_map_editor.api.studio.editor_tools`, because those are the
numbers its confirm actually pastes.

A tool this build does not implement is named as such, with what is missing,
and is given no fields at all: an editable box that writes nothing is worse
than an empty tab, because it looks like it worked.

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
from amulet_map_editor.api.studio import context, editor_tools, tokens
from amulet_map_editor.api.studio.copy import studio_label, studio_text
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
    SearchableChoice,
    SearchBar,
    SectionLabel,
    Stepper,
    StudioButton,
    StudioText,
    VectorField,
    elide,
    format_number,
    invoke,
    paint_context,
    point_size,
    translated,
)

log = logging.getLogger(__name__)


def wrap_status(dc: wx.DC, text: str, max_width: int) -> str:
    """Return ``text`` broken into lines no wider than ``max_width``.

    Different from :func:`~amulet_map_editor.api.studio.widgets.wrap_text` in
    the one way that matters for a status sentence: a run wider than the whole
    line is broken across lines by character rather than elided.  A wrap that
    only splits on spaces has nowhere to split Cantonese, which carries none --
    so the entire Cantonese half of a bilingual status came back as a single
    over-long "word", got cut to the column width, and ended in an ellipsis
    that hid what it said.  ``notification_toast`` breaks its own lines for
    exactly this reason.

    Nothing is elided and no line count is imposed: a status sentence is short,
    the pane it lives in scrolls, and the half of a message that says what to
    do about the problem is usually the second half.
    """
    limit = max(1, int(max_width))
    lines: List[str] = []
    for paragraph in str(text).split("\n"):
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        current = ""
        for word in words:
            while dc.GetTextExtent(word)[0] > limit and len(word) > 1:
                cut = len(word)
                while cut > 1 and dc.GetTextExtent(word[:cut])[0] > limit:
                    cut -= 1
                if current:
                    lines.append(current)
                    current = ""
                lines.append(word[:cut])
                word = word[cut:]
            candidate = f"{current} {word}" if current else word
            if not current or dc.GetTextExtent(candidate)[0] <= limit:
                current = candidate
                continue
            lines.append(current)
            current = word
        if current:
            lines.append(current)
    return "\n".join(lines) if lines else ""


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

#: The tab an editing tool's options live on.  It is not in :data:`PANE_TABS`
#: because it is only there while a tool is running: a pill leading to "no tool
#: is active" on every project that has never started one is a tab that costs
#: width and answers nothing.  Its label stays "Tool" rather than becoming the
#: tool's own name so the strip cannot grow wide enough to clip; which tool it
#: is showing is in the pill's accessible name and in the tab's first heading.
TOOL_TAB: Tuple[str, str] = ("tool", "Tool")

#: Every tab key and the name its search reports itself under.
TAB_LABELS: Dict[str, str] = dict(PANE_TABS + (TOOL_TAB,))

#: How far one press of a nudge control moves a pending object, in blocks.
DEFAULT_NUDGE_STEP = 1
MAX_NUDGE_STEP = 512

#: Which axis each nudge key moves the pending object along, as
#: ``key: (axis, direction)`` with the axis indexed x, y, z.
#:
#: Left and right are x and up and down are z, which is the horizontal plane
#: as it is seen from above with north up -- and north is negative z, so the
#: up arrow decreases it.  Height has no third pair of arrows on a keyboard,
#: so it takes Page Up and Page Down.
#:
#: Kept as data rather than a chain of comparisons so a test can assert on the
#: mapping itself instead of pressing six keys to discover it.
NUDGE_KEYS: Dict[int, Tuple[int, int]] = {
    wx.WXK_LEFT: (0, -1),
    wx.WXK_RIGHT: (0, 1),
    wx.WXK_PAGEUP: (1, 1),
    wx.WXK_PAGEDOWN: (1, -1),
    wx.WXK_UP: (2, -1),
    wx.WXK_DOWN: (2, 1),
}


#: How the nudge keys read to a person, in the order they are described.
#:
#: Short, and it names the nudge step rather than pointing at where the step
#: control is, because this sentence has to sit at the very top of the pending
#: controls to be read at all.  The pane is a scroller; the tool header and the
#: activation summary take 388px of its ~449px column before the pending
#: controls start, so the whole budget for this paragraph is about three lines,
#: and a sentence that says "the step above" while being above the step is
#: worse than one that mentions neither.
NUDGE_KEY_SENTENCE = (
    "Arrow keys nudge the copy by the nudge step: left and right along x, "
    "up and down along z, Page Up and Page Down for height."
)

#: The half of the key behaviour that only matters once a value box has focus.
#:
#: Split out of :data:`NUDGE_KEY_SENTENCE` and shown beside the value boxes
#: rather than above them.  It is not a shortcut anybody has to be told about
#: in advance -- it is what happens when you are already typing a coordinate,
#: and by then the boxes it is about are the thing on screen.
NUDGE_BOX_CAVEAT = "Inside a value box the arrow keys belong to that box instead."

#: Where the chosen anchor is stored, so it survives a restart like any other
#: setting.  One record for the profile rather than one per project: which
#: point a coordinate means is a habit of the person, not a fact about a world.
PASTE_ANCHOR_CONFIG_ID = "amulet_studio_paste_anchor"

#: The heading over the anchor control, and the label it carries.
ANCHOR_FIELD_LABEL = "Position refers to"

#: What the three Position boxes mean, per anchor.
#:
#: The centre one is the disclosure this section was added for.  The editor
#: puts the *centre* of a copy at the position it is given, so a 4 by 1 by 4
#: slab asked for 8, 40, 8 fills 6, 40, 6 to 9, 40, 9 -- half a structure away
#: from the numbers that were typed.  Nothing said so anywhere, which is the
#: most likely reading of "cloning doesn't work" from somebody who typed the
#: coordinate they wanted and looked there for the blocks.
ANCHOR_SENTENCES: Dict[str, str] = {
    editor_tools.ANCHOR_CENTRE: (
        "x, y and z are the centre of the copy, not a corner. The blocks land "
        "in the box below, which is half the copy away in every direction."
    ),
    editor_tools.ANCHOR_BASE: (
        "x, y and z are the middle of the copy's bottom layer, so this is the "
        "block it stands on. The blocks land in the box below."
    ),
    editor_tools.ANCHOR_MINIMUM: (
        "x, y and z are the copy's lowest corner: its smallest x, its smallest "
        "y and its smallest z. The blocks land in the box below."
    ),
    editor_tools.ANCHOR_MAXIMUM: (
        "x, y and z are the copy's highest corner: its largest x, its largest "
        "y and its largest z. The blocks land in the box below."
    ),
}

#: What the section says when the held object's size could not be read.
#:
#: An unknown size is said rather than guessed at.  Without the extent there is
#: no way to work out which block the centre lands on, so no box is drawn and
#: no anchor is offered -- a picker that cannot do what its options say is
#: worse than no picker, and a box readout that quietly shows the position
#: three times would be the exact defect this section exists to remove.
ANCHOR_SIZE_UNKNOWN = (
    "The copy's size could not be read, so x, y and z are the position the "
    "paste tool holds and the box the blocks will fill cannot be shown."
)

#: The two rows that say where the blocks actually go.
PASTE_BOX_ROWS: Tuple[Tuple[str, str], ...] = (
    ("paste_from", "Fills from"),
    ("paste_to", "Fills to"),
)

#: An inclusive block box, or ``None`` when the copy's extent is unknown.
PasteBox = Optional[Tuple[Tuple[int, int, int], Tuple[int, int, int]]]


def load_paste_anchor() -> str:
    """Return the stored anchor, or the editor's own behaviour."""
    try:
        stored = config.get(PASTE_ANCHOR_CONFIG_ID, editor_tools.ANCHOR_CENTRE)
    except OSError:  # pragma: no cover - an unreadable profile
        log.exception("Could not read the stored paste anchor")
        return editor_tools.ANCHOR_CENTRE
    return editor_tools.normalise_anchor(stored)


def store_paste_anchor(anchor: str) -> bool:
    """Persist the chosen anchor, saying whether it reached disk."""
    try:
        config.put(PASTE_ANCHOR_CONFIG_ID, editor_tools.normalise_anchor(anchor))
    except OSError:
        log.exception("Could not store the paste anchor")
        return False
    return True


#: The controls whose own arrow-key behaviour must win over nudging.  An arrow
#: press inside one of these moves a caret or changes a value, and doing that
#: and moving the object from one press would be two edits the user asked for
#: once.
_TEXT_ENTRY_CLASSES: Tuple[type, ...] = (
    wx.TextCtrl,
    wx.SpinCtrl,
    wx.SpinCtrlDouble,
    wx.SpinButton,
    wx.Choice,
    wx.ComboBox,
    wx.ListBox,
    wx.Slider,
)

#: How wide one component of a coordinate is in this column, in design pixels.
#: Three of them plus the gaps between fit inside :data:`MIN_PANEL_WIDTH`, so a
#: coordinate stays whole when the pane is dragged to its narrowest.
VECTOR_BOX_WIDTH = 60

#: The value box of the nudge stepper, narrowed from the shared default for the
#: same reason.  Its accessible name carries the unit the suffix would have.
NUDGE_FIELD_WIDTH = 64

#: What the Tool tab says with no tool running.
NO_TOOL_ACTIVE = studio_text(
    "No editing tool is running. Start one from the Tools ribbon tab and its "
    "options will appear here, beside the world rather than over it.",
    "而家冇編輯工具喺度行緊。喺工具嗰版開一個，佢啲設定就會喺呢度出，喺世界隔籬而唔係遮住個世界。",
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

    def set_value(self, value: str) -> bool:
        """Replace the value without rebuilding the row around it.

        A live row is re-read several times a second while a tool is running,
        and rebuilding the whole tab that often would take the keyboard out of
        whatever field the user was typing in.

        The row is re-measured, and the caller is told whether anything moved so
        it can lay the column out once rather than on every tick.  Without the
        re-measure a row keeps the minimum width its first value asked for and
        :meth:`_draw` elides anything longer -- survivable while every live row
        said "yes" or "no", and not survivable for a row holding a coordinate,
        which is exactly the value a reader would go to this row to check.
        """
        text = str(value)
        if text == self.value:
            return False
        self.value = text
        self.SetName(f"{self.label}: {self.value}")
        self.SetToolTip(f"{self.label}: {self.value}")
        self.InvalidateBestSize()
        self.SetMinSize(self.DoGetBestSize())
        self.Refresh()
        return True

    def refresh_theme(self) -> None:
        """Re-measure for the live density and repaint."""
        self.InvalidateBestSize()
        self.SetMinSize(self.DoGetBestSize())
        self.Refresh()

    def _backdrop(self) -> wx.Colour:
        """Return what shows through the row's rounded corners."""
        palette = tokens.palette()
        parent = self.GetParent()
        backdrop = parent.GetBackgroundColour() if parent else palette.surface_container
        return backdrop if backdrop.IsOk() else palette.surface_container

    def render_to(self, dc: wx.DC, rect: wx.Rect) -> None:
        """Draw the row into someone else's device context.

        Every painted Studio widget answers this, because a capture on a
        desktop nobody is looking at cannot read a window's on-screen surface
        and an owner-drawn control does not answer the operating system's own
        print message.  Without it this row photographs as an empty rounded
        box: the shape is there, both halves of the text are not, and the
        picture looks exactly like a rendering fault in the pane.
        """
        with translated(dc, rect):
            dc.SetBrush(wx.Brush(self._backdrop()))
            dc.SetPen(wx.TRANSPARENT_PEN)
            dc.DrawRectangle(0, 0, rect.width, rect.height)
            self._draw(dc, rect.width, rect.height)

    def _draw(self, dc: wx.DC, width: int, height: int) -> None:
        """Draw the row's surface, its value, and its label."""
        palette = tokens.palette()
        tokens.draw_round_rect(
            dc,
            wx.Rect(0, 0, width, height),
            tokens.scaled(tokens.RADIUS_SM + 1),
            palette.surface,
            palette.outline_variant,
        )
        inset = tokens.scaled(self.PADDING_X)
        dc.SetFont(tokens.mono_font(self, point_size(12)))
        value = elide(dc, self.value, max(0, width - inset * 2))
        value_width = dc.GetTextExtent(value)[0]
        dc.SetTextForeground(palette.on_surface)
        dc.DrawText(
            value, width - inset - value_width, (height - dc.GetCharHeight()) // 2
        )
        dc.SetFont(tokens.font(self, point_size(12)))
        dc.SetTextForeground(palette.on_surface_variant)
        available = max(0, width - inset * 2 - value_width - tokens.scaled(10))
        dc.DrawText(
            elide(dc, self.label, available),
            inset,
            (height - dc.GetCharHeight()) // 2,
        )

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        dc, gcdc = paint_context(self, self._backdrop())
        width, height = self.GetClientSize()
        self._draw(gcdc, width, height)
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
            studio_label("Restore"),
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

    def render_to(self, dc: wx.DC, rect: wx.Rect) -> None:
        """Draw the row into someone else's device context.

        The same reason as :meth:`PropertyRow.render_to`: without it a capture
        photographs the revision list as a column of empty cards.
        """
        with translated(dc, rect):
            dc.SetBrush(wx.Brush(tokens.palette().surface_container))
            dc.SetPen(wx.TRANSPARENT_PEN)
            dc.DrawRectangle(0, 0, rect.width, rect.height)
            self._draw(dc, rect.width, rect.height)

    def _draw(self, dc: wx.DC, width: int, height: int) -> None:
        """Draw the card, its state dot, and the two lines of text."""
        palette = tokens.palette()
        tokens.draw_round_rect(
            dc,
            wx.Rect(0, 0, width, height),
            tokens.scaled(tokens.RADIUS_SM + 1),
            palette.surface,
            palette.primary if self.revision.head else palette.outline_variant,
        )
        left = tokens.scaled(11)
        dot = tokens.scaled(9)
        top = tokens.scaled(14)
        dc.SetPen(wx.TRANSPARENT_PEN)
        dc.SetBrush(
            wx.Brush(palette.primary if self.revision.head else palette.outline_variant)
        )
        dc.DrawEllipse(left, top, dot, dot)
        text_left = left + dot + tokens.scaled(10)
        available = max(0, width - text_left - tokens.scaled(11))
        dc.SetFont(tokens.font(self, point_size(12), _MEDIUM))
        dc.SetTextForeground(palette.on_surface)
        dc.DrawText(
            elide(dc, self.revision.message, available), text_left, tokens.scaled(10)
        )
        dc.SetFont(tokens.mono_font(self, point_size(11)))
        dc.SetTextForeground(palette.on_surface_variant)
        dc.DrawText(
            elide(dc, self.revision.meta, available),
            text_left,
            tokens.scaled(10) + dc.GetCharHeight() + tokens.scaled(4),
        )

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        dc, gcdc = paint_context(self, tokens.palette().surface_container)
        width, height = self.GetClientSize()
        self._draw(gcdc, width, height)
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
        #: The tool this pane is showing the options for, and what activating
        #: it actually did.  ``None`` means no tool has been started.
        self.activation: Optional[editor_tools.Activation] = None
        #: What the last confirm or cancel refused to do, ready to be shown
        #: beside the object it refused about.  A toast can be missed and a log
        #: line is not an interface, so the reason is kept here and rendered at
        #: the top of the pending controls until the next attempt clears it.
        #: It arrives already in the reader's language and tone from the bridge,
        #: so it is shown as given rather than styled a second time.
        self._pending_failure = ""
        self.nudge_step = DEFAULT_NUDGE_STEP
        #: Which point of the copy the Position boxes name.  Loaded rather than
        #: defaulted so a chosen anchor survives a restart, and it falls back to
        #: the editor's own centre so an existing habit keeps working.
        self.position_anchor = load_paste_anchor()
        self._tool_rows: Dict[str, PropertyRow] = {}
        self._tool_fields: Dict[str, VectorField] = {}
        self._anchor_choice: Optional[SearchableChoice] = None
        self._anchor_note: Optional[StudioText] = None
        self._tool_timer: Optional[wx.Timer] = None
        #: The width the current contents were wrapped for.  Wrapping is done
        #: once per build, so a pane the user has narrowed keeps paragraphs
        #: wider than the column until it is built again.
        self._built_width = 0
        self.SetName("Properties pane")
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)

        self.title_label = StudioText(
            self,
            str(title),
            size_px=14,
            weight=_MEDIUM,
            role="on_surface",
            name="Properties pane title",
        )
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
        # A wrapping row rather than a straight one: four pills fit across the
        # design's 308px column and do not fit across the 240 the pane can be
        # dragged to, and a strip that runs off the edge takes the tab a user
        # is looking for with it.  Wrapping costs one row of height in the case
        # where the alternative is an unreachable control.
        tab_row = wx.WrapSizer(wx.HORIZONTAL)
        for key, label in PANE_TABS + (TOOL_TAB,):
            pill = TabPill(
                self, key, label, selected=key == self.tab, on_click=self.set_tab
            )
            self.tab_buttons[key] = pill
            tab_row.Add(pill, 0, wx.RIGHT, tokens.scaled(2))
        # The tool pill is hidden rather than absent so the strip's layout is
        # the one it will have when a tool starts, and showing it is a single
        # state change rather than a rebuild of the header.
        self.tab_buttons[TOOL_TAB[0]].Hide()
        self.search = SearchBar(
            self,
            "Search these properties",
            self.search_state,
            on_change=self._on_search,
            compact=True,
        )
        self.scroller = wx.ScrolledWindow(
            self, style=wx.VSCROLL | wx.HSCROLL | wx.TAB_TRAVERSAL
        )
        # Horizontal scrolling is enabled rather than suppressed.  A control
        # whose smallest honest width is wider than the pane the user has
        # dragged narrow has to go somewhere, and a scrollbar says so; with the
        # rate at zero the same content is silently cut off at the right edge
        # instead, taking each row's value with it.
        self.scroller.SetScrollRate(tokens.scaled(12), tokens.scaled(12))
        self.scroller.SetName("Properties pane contents")
        self.body = wx.BoxSizer(wx.VERTICAL)
        self.scroller.SetSizer(self.body)
        self.status_label = StudioText(
            self.scroller, "", size_px=11, name="Properties pane search result"
        )
        self.empty_note = StudioText(
            self.scroller, "", size_px=11, name="Properties pane state"
        )
        self.notes_field = wx.TextCtrl(
            self.scroller,
            value=note_for(self._note_key),
            style=wx.TE_MULTILINE | wx.TE_RICH2,
        )
        self.notes_field.SetName("Project note")
        self.notes_field.SetHint(
            single_line(
                studio_label(
                    "Write anything this project needs remembered.",
                    "呢個項目要記住嘅嘢，寫低喺度。",
                )
            )
        )
        self.notes_field.SetMaxLength(MAX_NOTE_LENGTH)
        self.notes_field.SetMinSize(wx.Size(-1, tokens.scaled(160)))
        self.notes_field.Bind(wx.EVT_TEXT, self._on_note_changed)
        self.notes_field.Bind(wx.EVT_KILL_FOCUS, self._on_note_focus_lost)
        self.notes_status = StudioText(
            self.scroller, "", size_px=11, name="Project note status"
        )
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
        self.Bind(wx.EVT_SIZE, self._on_resize)
        self.Bind(wx.EVT_WINDOW_DESTROY, self._on_destroy)
        # A hook rather than a key event on each control: the nudge keys have
        # to work wherever the focus is inside this pane, and binding them to
        # the buttons alone would mean they only worked once a nudge button
        # already had focus -- which is the one moment the user does not need
        # them.
        self.Bind(wx.EVT_CHAR_HOOK, self._on_tool_key)
        self.scroller.Bind(wx.EVT_CONTEXT_MENU, self._on_context_menu)
        context.subscribe(self._on_world_context)
        # This pane is where a tool's options are shown, so it says so once and
        # every route into a tool -- ribbon, palette, context menu, keyboard --
        # lands here rather than each of them knowing about this class.
        editor_tools.set_host(self)
        editor_tools.install_surface_routes()
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
            self._stop_tool_timer()
            if editor_tools.host() is self:
                editor_tools.set_host(None)
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
        """Open one of the pane's tabs."""
        if key not in self.tab_buttons:
            return
        self.tab = key
        for name, pill in self.tab_buttons.items():
            pill.set_selected(name == key)
        self._name_tool_pill()
        self.search_state.label = TAB_LABELS.get(key, key)
        if key == "history":
            self.refresh_history(reread=True)
        self.rebuild()

    def _note_width(self) -> int:
        """Return how wide a wrapped paragraph may be, inside the scrollbar.

        The pane's own width is the wrong measurement: the scrolling area is
        narrower by whatever its vertical scrollbar takes, and a paragraph
        wrapped to the pane sets a minimum wider than the column it is in --
        which pushes every row in the tab out past the right edge, values
        first.
        """
        width = self.scroller.GetClientSize().width
        if width <= 0:
            width = self.GetClientSize().width - tokens.scaled(32)
        return max(tokens.scaled(140), width - tokens.scaled(10))

    def _wrap_in_column(self, label: StudioText) -> None:
        """Break ``label``'s current text to the column it sits in.

        The breaks are measured here rather than left to ``StudioText.Wrap``
        for the reason :meth:`_set_note_status` gives at length: the word wrap
        behind it splits on spaces and elides whatever will not fit, and a
        Cantonese sentence carries no spaces at all, so the whole of it arrives
        as one over-long "word" and is cut to an ellipsis.  :func:`wrap_status`
        breaks an unbreakable run by character instead.

        The font comes from :meth:`StudioText.text_font` rather than
        ``GetFont``: nothing pushes a font into an owner-drawn label, so
        ``GetFont`` answers with the platform default and the measurement would
        be for a font the pane never draws.
        """
        text = single_line(label.GetLabel())
        if not text:
            return
        dc = wx.ClientDC(label)
        dc.SetFont(label.text_font())
        label.SetLabel(wrap_status(dc, text, self._note_width()))

    def _set_empty_note(self, text: str) -> None:
        """Show one wrapped empty-state line, or none at all.

        The accessible name keeps the unwrapped single line, so a screen reader
        reads a sentence rather than the column's line breaks.
        """
        message = single_line(text)
        self.empty_note.SetLabel(message)
        self.empty_note.SetName(
            f"Properties pane state: {message}" if message else "Properties pane state"
        )
        if message:
            self._wrap_in_column(self.empty_note)
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
        # The live rows and fields belong to the tree that was just cleared, so
        # the timer must not be holding references to them when it next fires.
        self._tool_rows = {}
        self._tool_fields = {}
        self._anchor_choice = None
        self._anchor_note = None

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
            # The count of rows actually drawn decides this, not the count of
            # sections: an owner that pushed three empty sections would leave
            # the tab blank with no explanation on it, which reads as a pane
            # that failed to load rather than one with nothing to report.
            if not kept and not state.is_active():
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
            if not matched and not state.is_active():
                self._set_empty_note(self._history_note())
                self.body.Add(self.empty_note, 0, wx.EXPAND | wx.BOTTOM, gap)
            self.status_label.SetLabel(
                state.describe_matches(len(matched), "revision")
                if state.is_active()
                else (f"{len(matched)} revisions · newest first" if matched else "")
            )
        elif self.tab == "tool":
            self._build_tool_tab(gap)
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

        self._built_width = self.GetClientSize().width
        self.status_label.Show(bool(self.status_label.GetLabel()))
        if self.status_label.GetLabel():
            # Wrapped for the same reason the notes are: a one-line status
            # sentence sets a minimum wider than the column and pushes every
            # row in the tab out past the right edge with it.  Each branch
            # above sets the label first, so this never wraps a wrapped string.
            self._wrap_in_column(self.status_label)
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

    # -- editing tools -------------------------------------------------------
    def activate_tool(self, key: str) -> editor_tools.Activation:
        """Start the editor tool one surface key names and show its options.

        The tool starts in the canvas with its handles over the world; this
        pane shows what it is holding.  The result is returned as well as shown
        so a caller can react to a tool that refused to start.
        """
        return editor_tools.activate(key, self)

    def show_tool_activation(self, activation: editor_tools.Activation) -> None:
        """Show one tool's options, including a tool that could not start.

        A refusal opens the tab too.  It is the only place that says why, and
        sending the user back to a tab about something else after pressing a
        tool would leave the press looking like it did nothing at all.
        """
        self.activation = activation
        pill = self.tab_buttons.get(TOOL_TAB[0])
        if pill is not None:
            pill.Show()
        self.set_tab(TOOL_TAB[0])
        self.Layout()

    def _name_tool_pill(self) -> None:
        """Say which tool the Tool tab is showing, for a screen reader.

        The pill's own label stays "Tool" so the strip cannot outgrow the
        column, which leaves the name as the only place the tool is announced.
        It is re-applied on every tab change because selecting a pill rewrites
        its name from its label.
        """
        pill = self.tab_buttons.get(TOOL_TAB[0])
        if pill is None or self.activation is None:
            return
        state = "selected" if self.tab == TOOL_TAB[0] else "not selected"
        pill.SetName(f"{self.activation.label} tool options, tab, {state}")
        pill.SetToolTip(f"Options for the {self.activation.label} tool")

    def clear_tool(self) -> None:
        """Take the Tool tab away, because no tool is running any more."""
        self.activation = None
        # The failure belonged to an object that is no longer held, so keeping
        # it would attach an old refusal to the next thing lifted.
        self._pending_failure = ""
        self._stop_tool_timer()
        pill = self.tab_buttons.get(TOOL_TAB[0])
        if pill is not None:
            pill.Hide()
        if self.tab == TOOL_TAB[0]:
            self.set_tab("properties")
        else:
            self.rebuild()
        self.Layout()

    def _tool_label(self, text: str) -> None:
        """Add one heading to the Tool tab."""
        self.body.Add(
            SectionLabel(self.scroller, text),
            0,
            wx.EXPAND | wx.BOTTOM,
            tokens.scaled(tokens.SPACE_SM),
        )

    def _tool_row(self, label: str, value: str, gap: int, *, live: str = "") -> None:
        """Add one label-and-value row, remembering the ones that change."""
        row = PropertyRow(self.scroller, label, value)
        if live:
            self._tool_rows[live] = row
        self.body.Add(row, 0, wx.EXPAND | wx.BOTTOM, gap)

    def _tool_note(self, text: str, gap: int) -> Optional[StudioText]:
        """Add one wrapped paragraph of explanation to the Tool tab.

        The control is returned so a caller whose sentence changes without the
        tab being rebuilt can keep hold of it -- the anchor disclosure is
        rewritten the moment the anchor is chosen, and a rebuild there would
        scroll the section the user is reading back off the top of the column.
        """
        message = single_line(text)
        if not message:
            return None
        note = StudioText(self.scroller, message, size_px=11, name=message)
        self._wrap_in_column(note)
        self.body.Add(note, 0, wx.EXPAND | wx.BOTTOM, gap)
        return note

    def _tool_vector(
        self,
        name: str,
        axes: Sequence[str],
        values: Sequence[str],
        handler: Callable[[Tuple[str, ...]], None],
        gap: int,
    ) -> None:
        """Add one three-component editable value bound to the live tool.

        The shared coordinate control is sized for a 680px window, where three
        160px boxes and a camera button fit side by side.  This column is 308px
        and may be dragged down to 240, so each box is given a width that keeps
        all three inside the narrowest supported pane; the sizer hands them the
        slack back at the full width.  Left alone, the control is a third wider
        than the pane and the last axis is simply not on screen.
        """
        field = VectorField(
            self.scroller,
            [(axis, value) for axis, value in zip(axes, values)],
            on_change=handler,
        )
        for box in field.boxes:
            box.SetMinSize(wx.Size(tokens.scaled(VECTOR_BOX_WIDTH), tokens.scaled(30)))
        # The camera button belongs to a coordinate, and rotation and scale are
        # not coordinates; the position field gets a full-width button of its
        # own below instead, which also states what it does rather than drawing
        # a glyph the width here cannot afford.
        field.pick_button.Hide()
        field.InvalidateBestSize()
        self._tool_fields[name] = field
        self.body.Add(field, 0, wx.EXPAND | wx.BOTTOM, gap)

    def _build_tool_tab(self, gap: int) -> None:
        """Draw the running tool's own options, or say why there are none."""
        activation = self.activation
        if activation is None:
            self._stop_tool_timer()
            self._set_empty_note(NO_TOOL_ACTIVE)
            self.body.Add(self.empty_note, 0, wx.EXPAND | wx.BOTTOM, gap)
            self.status_label.SetLabel("")
            return

        self._tool_label(activation.label)
        if not activation.ok:
            # Nothing editable is drawn for a tool that did not start: a field
            # that writes nowhere is the one thing worse than an empty tab.
            self._stop_tool_timer()
            self._tool_row("Editor tool", activation.tool or "none in this build", gap)
            self._tool_note(studio_text(activation.message), gap)
            if activation.missing and activation.missing != activation.message:
                self._tool_note(studio_text(activation.missing), gap)
            self.status_label.SetLabel(
                single_line(
                    studio_text(
                        f"{activation.label} did not start.",
                        f"{activation.label} 開唔到。",
                    )
                )
            )
            return

        running = editor_tools.active_tool_name()
        self._tool_row("Editor tool", activation.tool, gap)
        self._tool_row(
            "State",
            (
                f"running as {running}"
                if running == activation.tool
                else f"the canvas reports {running or 'no tool'}"
            ),
            gap,
            live="state",
        )
        # ``detail`` is what was true at the moment the tool started, so it is
        # deliberately not shown here: the rows below are re-read live, and a
        # stale sentence beside a live row is the one that gets believed.
        self._tool_note(studio_text(activation.message), gap)
        if activation.missing:
            self._tool_note(studio_text(activation.missing), gap)

        if activation.kind == "pending":
            self._build_pending_controls(gap)
        elif activation.kind == "selection":
            self._build_selection_readout(gap)
        else:
            self._tool_note(
                studio_text(
                    f"The {activation.tool} tool's own controls are on its panel "
                    "in the viewport, over the world it is acting on.",
                    f"{activation.tool} 工具嘅控制係喺畫面嗰個面板度，就喺佢改緊嘅世界上面。",
                ),
                gap,
            )
            self._stop_tool_timer()

        for note in activation.notes:
            self._tool_note(studio_text(note), gap)
        self.status_label.SetLabel(
            single_line(
                studio_text(
                    "The search filters the Properties and History tabs.",
                    "個搜尋係篩「屬性」同「歷史」嗰兩版。",
                )
            )
            if self.search_state.is_active()
            else ""
        )

    def _build_selection_readout(self, gap: int) -> None:
        """Show what the Select tool currently has, read from the canvas."""
        self._stop_tool_timer()
        selection = editor_tools.selection_state()
        self._tool_label(studio_label("Selection"))
        if not selection.readable:
            self._tool_note(
                studio_text(
                    "The editor's selection could not be read, so there is "
                    "nothing to report about it.",
                    "讀唔到編輯器嘅選取範圍，所以講唔到佢有咩。",
                ),
                gap,
            )
            return
        if selection.empty:
            self._tool_note(
                studio_text(
                    "Nothing is selected yet. Drag in the viewport to place the "
                    "two corners of a box.",
                    "而家未揀到嘢。喺畫面度拖一拖，擺低個框嘅兩隻角。",
                ),
                gap,
            )
            return
        self._tool_row("Boxes", f"{selection.boxes}", gap)
        self._tool_row(
            "Minimum", ", ".join(str(value) for value in selection.minimum), gap
        )
        self._tool_row(
            "Maximum", ", ".join(str(value) for value in selection.maximum), gap
        )
        self._tool_row("Volume", f"{selection.volume:,} blocks", gap)
        self._tool_note(
            studio_text(
                "The per-corner nudge controls belong to the tool and are on "
                "its panel in the viewport.",
                "逐隻角微調嗰啲掣係工具本身嘅，喺畫面嗰個面板度。",
            ),
            gap,
        )

    def _build_pending_controls(self, gap: int) -> None:
        """Show the pending object, and every way of moving it.

        This is the answer to "how do I move the thing I just dragged out":
        it is a live object the paste tool is holding, its position is an
        editable value here, each axis has a nudge control, the viewport keys
        that move it are named, and confirming writes it into the world while
        cancelling writes nothing.
        """
        pending = editor_tools.pending_object()
        if pending is None:
            self._stop_tool_timer()
            self._tool_note(
                studio_text(
                    "The paste tool is not holding anything any more, so there "
                    "is nothing to place.",
                    "貼上工具而家冇揸住嘢，所以冇嘢可以擺。",
                ),
                gap,
            )
            return

        self._tool_label(studio_label("Pending object"))
        # Ahead of everything else, because it is the answer to the question the
        # user is holding: they pressed Confirm and the object is still here.
        # Already localized and toned by the bridge, so it is not passed through
        # ``studio_text`` again -- that would append a second funny-level aside
        # to a sentence that already has one.
        if self._pending_failure:
            self._tool_note(self._pending_failure, gap)
        # Directly under the heading, ahead of the object's own facts, because
        # this is the only place in the column it can be read.  A control
        # announces itself through its accessible name and a key press cannot,
        # so the keys have to be written down -- and written down where the
        # pane opens.  Beside the nudge buttons they describe, which is where
        # they read most naturally, the sentence sat 237px past the bottom of
        # the visible column: a shortcut told below the fold is not told.
        self._tool_note(studio_text(NUDGE_KEY_SENTENCE), gap)
        if pending.size:
            self._tool_row("Size in blocks", pending.size, gap)
        self._tool_row(
            "Following the pointer",
            "yes" if pending.following else "no",
            gap,
            live="following",
        )
        self._tool_row(
            "Drawn in the viewport",
            "yes" if pending.drawn else "no",
            gap,
            live="drawn",
        )
        if pending.following:
            self.body.Add(
                StudioButton(
                    self.scroller,
                    studio_label("Drop it here", "擺低喺呢度"),
                    variant="tonal",
                    on_click=self._drop_pending,
                    hint=single_line(
                        studio_text(
                            "Stop the copy tracking the pointer and leave it "
                            "where it is. Clicking in the viewport does the same.",
                            "唔好再跟住個滑鼠，就咁擺低。喺畫面度撳一下都係一樣。",
                        )
                    ),
                    name="Drop the pending object where it is",
                ),
                0,
                wx.EXPAND | wx.BOTTOM,
                gap,
            )

        self._tool_label(studio_label("Position"))
        values, box = self._anchor_values(pending)
        # The picker first, because it says what the three boxes under it mean.
        # It is only offered when the copy's size is known: without the extent
        # there is no way to turn a corner into the position the tool holds, so
        # an anchor other than the centre could not be honoured and offering it
        # would be a control that lies about what it does.
        if box is not None:
            self._anchor_choice = SearchableChoice(
                self.scroller,
                studio_label(ANCHOR_FIELD_LABEL),
                [label for _key, label in editor_tools.ANCHORS],
                editor_tools.anchor_label(self.position_anchor),
                on_change=self._on_anchor_chosen,
            )
            self._anchor_choice.SetToolTip(
                single_line(
                    studio_text(
                        "Which point of the copy the x, y and z boxes name. "
                        "The editor itself uses the centre.",
                        "揀 x、y、z 係指嗰嚿嘢邊一點。編輯器本身係用正中心。",
                    )
                )
            )
            self.body.Add(self._anchor_choice, 0, wx.EXPAND | wx.BOTTOM, gap)
        else:
            self._anchor_choice = None
        self._tool_vector(
            "location",
            ("x", "y", "z"),
            values,
            self._on_location_typed,
            gap,
        )
        # The disclosure, directly under the boxes it is about.  A coordinate
        # control that does not say which point of the object it names is a
        # coordinate control the user has to discover by pasting and looking.
        self._anchor_note = self._tool_note(
            studio_text(self._anchor_sentence(box)), gap
        )
        for key, label in PASTE_BOX_ROWS:
            self._tool_row(label, self._box_text(box, key), gap, live=key)
        # Beside the boxes it is about, rather than in the sentence above: it
        # describes what an arrow key does once one of these has focus, which
        # is a thing a user meets while typing here and not a shortcut they
        # have to be told about before they can find it.
        self._tool_note(studio_text(NUDGE_BOX_CAVEAT), gap)
        if editor_tools.camera_location() is not None:
            self.body.Add(
                StudioButton(
                    self.scroller,
                    studio_label("Bring it to the camera", "拉埋嚟鏡頭度"),
                    variant="outlined",
                    on_click=self._pending_to_camera,
                    hint=single_line(
                        studio_text(
                            "Put the copy at the block the camera is standing on.",
                            "將個複製擺去鏡頭而家企嗰格。",
                        )
                    ),
                    name="Move the pending object to the camera position",
                ),
                0,
                wx.EXPAND | wx.BOTTOM,
                gap,
            )
        self._build_nudge_controls(gap)

        self._tool_label(studio_label("Rotation"))
        self._tool_vector(
            "rotation",
            ("x", "y", "z"),
            [format_number(value) for value in pending.rotation],
            self._on_rotation_typed,
            gap,
        )
        self._tool_note(
            studio_text(
                "Degrees around each axis.",
                "每條軸嘅角度。",
            ),
            gap,
        )

        self._tool_label(studio_label("Scale"))
        self._tool_vector(
            "scale",
            ("x", "y", "z"),
            [format_number(value) for value in pending.scale],
            self._on_scale_typed,
            gap,
        )

        self.body.Add(
            StudioButton(
                self.scroller,
                studio_label("Cancel", "取消"),
                variant="outlined",
                on_click=self._cancel_pending,
                hint=single_line(
                    studio_text(
                        "Drop the pending object without writing anything.",
                        "唔寫入世界，直接放棄嗰嚿嘢。",
                    )
                ),
                name="Cancel the pending placement",
            ),
            0,
            wx.EXPAND | wx.BOTTOM,
            gap,
        )
        self._tool_note(
            studio_text(
                "Confirm writes the copy into the world and keeps holding it, "
                "so it can be nudged and confirmed again for a repeat.",
                "撳確認會將呢個複製寫入世界，而且仲會揸住佢，可以再郁再確認，做多一份。",
            ),
            gap,
        )
        self._start_tool_timer()

    def _build_nudge_controls(self, gap: int) -> None:
        """Add a per-axis nudge for the pending object, and name the real keys."""
        self._tool_label(studio_label("Nudge step, in blocks"))
        step = Stepper(
            self.scroller,
            self.nudge_step,
            1,
            MAX_NUDGE_STEP,
            on_change=self._on_step_change,
        )
        # The unit is in the heading above and in the accessible name rather
        # than in a suffix repeated after both bounds, which is what pushes the
        # control past the width of this column.
        step.FIELD = NUDGE_FIELD_WIDTH
        step.InvalidateBestSize()
        step.SetMinSize(step.DoGetBestSize())
        step.SetName("Nudge step, in blocks")
        self.body.Add(step, 0, wx.EXPAND | wx.BOTTOM, gap)
        for axis, name in enumerate(("x", "y", "z")):
            row = wx.BoxSizer(wx.HORIZONTAL)
            for delta, glyph in ((-1, "−"), (1, "+")):
                row.Add(
                    StudioButton(
                        self.scroller,
                        f"{glyph}{name.upper()}",
                        variant="outlined",
                        height=32,
                        on_click=lambda a=axis, d=delta: self._nudge(a, d),
                        hint=(
                            f"Move the pending object {'back' if delta < 0 else 'along'}"
                            f" the {name} axis by the step above"
                        ),
                        name=f"Nudge {name} by {'minus ' if delta < 0 else ''}the step",
                    ),
                    1,
                    wx.RIGHT,
                    tokens.scaled(4),
                )
            self.body.Add(row, 0, wx.EXPAND | wx.BOTTOM, gap)
        sentence = editor_tools.movement_sentence()
        if sentence:
            self._tool_note(sentence, gap)

    # -- what the tool controls do -------------------------------------------
    def _numbers(self, values: Sequence[str]) -> Optional[Tuple[float, float, float]]:
        """Return three typed values as numbers, or ``None`` while half-typed.

        A field holding ``-`` or an empty box is a value in the middle of being
        typed, not a value of zero, and writing zero into the world's live
        preview on the way to ``-12`` would move the object twice.
        """
        try:
            numbers = tuple(float(str(value).strip()) for value in values)
        except (TypeError, ValueError):
            return None
        return numbers if len(numbers) == 3 else None

    # -- which point of the copy a position names ------------------------------
    def _anchor_values(
        self, pending: editor_tools.PendingObject
    ) -> Tuple[List[str], PasteBox]:
        """Return what the Position boxes should read, and the box it fills.

        A ``None`` box means the copy's extent could not be read.  The boxes
        then show the tool's own position unconverted, because converting it
        would need the extent that is missing -- and a number silently offset
        by a size nobody knows is worse than one that is simply the position.
        """
        box = editor_tools.paste_box(
            pending.location, pending.extent, pending.scale, pending.rotation
        )
        if box is None:
            return [str(value) for value in pending.location], None
        point = editor_tools.anchor_point(
            pending.location,
            pending.extent,
            pending.scale,
            pending.rotation,
            self.position_anchor,
        )
        if point is None:  # pragma: no cover - both read the same extent
            return [str(value) for value in pending.location], box
        return [str(value) for value in point], box

    def _anchor_sentence(self, box: PasteBox) -> str:
        """Return the sentence that says what x, y and z mean right now."""
        if box is None:
            return ANCHOR_SIZE_UNKNOWN
        return ANCHOR_SENTENCES[editor_tools.normalise_anchor(self.position_anchor)]

    @staticmethod
    def _box_text(box: PasteBox, key: str) -> str:
        """Return one corner of the paste box, or an honest unknown."""
        if box is None:
            return "not known"
        corner = box[0] if key == PASTE_BOX_ROWS[0][0] else box[1]
        return ", ".join(str(value) for value in corner)

    def _on_anchor_chosen(self, label: str) -> None:
        """Remember which point the Position boxes name, and re-read them."""
        chosen = next(
            (key for key, name in editor_tools.ANCHORS if name == label),
            editor_tools.ANCHOR_CENTRE,
        )
        if chosen == self.position_anchor:
            return
        self.position_anchor = chosen
        store_paste_anchor(chosen)
        note = self._anchor_note
        if note is not None:
            try:
                pending = editor_tools.pending_object()
                box = (
                    None
                    if pending is None
                    else editor_tools.paste_box(
                        pending.location,
                        pending.extent,
                        pending.scale,
                        pending.rotation,
                    )
                )
                message = single_line(studio_text(self._anchor_sentence(box)))
                note.SetLabel(message)
                note.SetName(message)
                self._wrap_in_column(note)
            except RuntimeError:  # pragma: no cover - the note was replaced
                self._anchor_note = None
        # The position itself has not moved; only the point being named has, so
        # the boxes are re-read rather than written back through the tool.
        self._refresh_tool_live()
        self.scroller.Layout()

    def _on_location_typed(self, values: Tuple[str, ...]) -> None:
        numbers = self._numbers(values)
        if numbers is None:
            return
        pending = editor_tools.pending_object()
        location: Sequence[float] = numbers
        if pending is not None:
            converted = editor_tools.location_for_anchor(
                numbers,
                pending.extent,
                pending.scale,
                pending.rotation,
                self.position_anchor,
            )
            if converted is not None:
                location = converted
        editor_tools.set_pending_location(location)
        self._refresh_tool_live(fields=False)

    def _on_rotation_typed(self, values: Tuple[str, ...]) -> None:
        numbers = self._numbers(values)
        if numbers is not None:
            editor_tools.set_pending_rotation(numbers)

    def _on_scale_typed(self, values: Tuple[str, ...]) -> None:
        numbers = self._numbers(values)
        if numbers is not None:
            editor_tools.set_pending_scale(numbers)

    def _on_step_change(self, value: float) -> None:
        self.nudge_step = max(1, min(MAX_NUDGE_STEP, int(round(float(value)))))

    def _nudge(self, axis: int, direction: int) -> None:
        """Move the pending object one step along an axis."""
        moved = editor_tools.nudge_pending(axis, direction * self.nudge_step)
        if moved is None:
            self._report_tool_gone()
            return
        self._refresh_tool_live()

    def nudge_key_applies(self, key: int, focus: Optional[wx.Window]) -> bool:
        """Whether a key press should nudge, given what currently has focus.

        Split out from the event handler so the decision can be asserted on
        directly.  The half that matters is the refusal: an arrow key inside a
        value box belongs to that box, and nudging as well would move the
        object on the way to typing a coordinate for it.
        """
        if key not in NUDGE_KEYS:
            return False
        if self.tab != TOOL_TAB[0]:
            return False
        activation = self.activation
        if activation is None or not activation.ok or activation.kind != "pending":
            return False
        if focus is None:
            return False
        if isinstance(focus, _TEXT_ENTRY_CLASSES):
            return False
        # A composite value control puts focus on an inner text box whose class
        # is checked above, but some platforms focus the wrapper instead.
        node = focus
        while node is not None and node is not self:
            if isinstance(node, _TEXT_ENTRY_CLASSES):
                return False
            node = node.GetParent()
        # Focus outside this pane is somebody else's key press -- the viewport
        # moves the camera with the same arrows.
        return node is self

    def _on_tool_key(self, event: wx.KeyEvent) -> None:
        """Nudge the pending object with the arrow keys."""
        if event.HasAnyModifiers() or not self.nudge_key_applies(
            event.GetKeyCode(), wx.Window.FindFocus()
        ):
            event.Skip()
            return
        axis, direction = NUDGE_KEYS[event.GetKeyCode()]
        self._nudge(axis, direction)

    def _pending_to_camera(self) -> None:
        """Put the pending object where the camera is standing."""
        location = editor_tools.camera_location()
        if location is None or not editor_tools.set_pending_location(location):
            self._report_tool_gone()
            return
        self._refresh_tool_live()

    def _drop_pending(self) -> None:
        """Stop the pending object following the pointer."""
        if not editor_tools.stop_following():
            self._report_tool_gone()
            return
        self.rebuild()

    def _confirm_pending(self) -> None:
        """Write the pending object into the world.

        The three outcomes need three different things from this pane, which is
        why the bridge is asked *why* rather than only whether.  A paste that
        wrote refreshes the history and redraws.  A paste that was stopped by an
        error must keep the panel: the object is still held, so hiding the panel
        would leave the user with a live copy, no controls for it, and a screen
        that looks exactly like the one a successful paste leaves behind -- the
        original defect, moved one layer out.  Only a tool that has genuinely
        stopped holding anything takes the tab away.
        """
        outcome = editor_tools.confirm_pending(parent=self)
        if outcome.ok:
            self._pending_failure = ""
            self.refresh_history(reread=True)
            self.rebuild()
            return
        if outcome.reason == "nothing-pending":
            self._report_tool_gone()
            return
        self._pending_failure = outcome.message
        self.rebuild()

    def _cancel_pending(self) -> None:
        """Drop the pending object without writing anything.

        The panel is taken away only once the object really has been let go.
        Hiding it on a cancel that did not take would leave the copy drawn over
        the world with nothing on screen admitting that it is still there.
        """
        outcome = editor_tools.cancel_pending(parent=self)
        if not outcome.ok:
            self._pending_failure = outcome.message
            self.rebuild()
            return
        self._pending_failure = ""
        self.clear_tool()

    def _report_tool_gone(self) -> None:
        """Say that the tool stopped holding the object, and stop showing it."""
        log.debug("The editor is no longer holding a pending object")
        self.clear_tool()

    # -- keeping the tool tab live -------------------------------------------
    def _start_tool_timer(self) -> None:
        """Re-read the pending object often enough to look live.

        The object follows the pointer, so its position changes without this
        pane being told; a value that is only correct until the mouse moves is
        worse than none, because the number on screen looks authoritative.
        """
        if self._tool_timer is None:
            self._tool_timer = wx.Timer(self)
            self.Bind(wx.EVT_TIMER, self._on_tool_timer, self._tool_timer)
        if not self._tool_timer.IsRunning():
            self._tool_timer.Start(300)

    def _stop_tool_timer(self) -> None:
        """Stop re-reading the tool, because nothing on screen is reading it."""
        if self._tool_timer is not None and self._tool_timer.IsRunning():
            self._tool_timer.Stop()

    def _on_tool_timer(self, _event: wx.TimerEvent) -> None:
        self._refresh_tool_live()

    def _refresh_tool_live(self, *, fields: bool = True) -> None:
        """Update the live rows and values in place, without a rebuild."""
        if self.tab != TOOL_TAB[0] or self.activation is None:
            self._stop_tool_timer()
            return
        pending = editor_tools.pending_object()
        if pending is None:
            self._stop_tool_timer()
            self.rebuild()
            return
        running = editor_tools.active_tool_name()
        position, box = self._anchor_values(pending)
        values = {
            "state": (
                f"running as {running}"
                if running == self.activation.tool
                else f"the canvas reports {running or 'no tool'}"
            ),
            "following": "yes" if pending.following else "no",
            "drawn": "yes" if pending.drawn else "no",
            PASTE_BOX_ROWS[0][0]: self._box_text(box, PASTE_BOX_ROWS[0][0]),
            PASTE_BOX_ROWS[1][0]: self._box_text(box, PASTE_BOX_ROWS[1][0]),
        }
        moved = False
        for key, value in values.items():
            row = self._tool_rows.get(key)
            if row is None:
                continue
            try:
                moved |= bool(row.set_value(value))
            except RuntimeError:  # pragma: no cover - the row has been replaced
                self._tool_rows.pop(key, None)
        if moved:
            # A row that grew asked for more width, and nothing gives it any
            # until the column is laid out again.  Only when something actually
            # changed: this runs several times a second.
            self.scroller.Layout()
        if not fields:
            return
        live = {
            # The anchored reading, not the raw position: the boxes are labelled
            # by whatever anchor is chosen, and writing the tool's own centre
            # into them would silently disagree with the sentence beneath.
            "location": position,
            "rotation": [format_number(value) for value in pending.rotation],
            "scale": [format_number(value) for value in pending.scale],
        }
        focused = wx.Window.FindFocus()
        for key, texts in live.items():
            field = self._tool_fields.get(key)
            if field is None:
                continue
            try:
                # A field the user is typing in is left alone: overwriting it
                # mid-keystroke would fight whoever is holding the keyboard.
                if focused is not None and field.IsDescendant(focused):
                    continue
                if list(field.values()) != texts:
                    field.set_values(texts)
            except RuntimeError:  # pragma: no cover - the field was replaced
                self._tool_fields.pop(key, None)

    # -- actions -------------------------------------------------------------
    def _action_for_tab(self) -> Tuple[str, Callable[[], None]]:
        """Return the primary action for the open tab: its label and its work."""
        if self.tab == TOOL_TAB[0]:
            activation = self.activation
            # Confirm is the primary action only while there is genuinely
            # something pending to write; on any other tool the pane keeps its
            # ordinary action rather than offering a confirm that would do
            # nothing.
            if (
                activation is not None
                and activation.ok
                and activation.kind == "pending"
                and editor_tools.pending_object() is not None
            ):
                return (
                    studio_label("Confirm placement", "確認擺位"),
                    self._confirm_pending,
                )
        if self.tab == "history":
            return (
                studio_label("Open project history", "開項目歷史"),
                lambda: invoke(self.on_surface, "history"),
            )
        if self.tab == "notes":
            return (studio_label("Save note", "儲存筆記"), self.save_note)
        return (
            studio_label("Frame selection", "對準選取範圍"),
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
        """Show one line about the note's state, wrapped to the pane's column.

        The wrap is the whole point.  This was the one status label in the pane
        that never got one -- ``status_label`` and ``empty_note`` are both
        wrapped to :meth:`_note_width` -- and an unwrapped sentence does not get
        politely cut, it sets a minimum wider than the column and drags the pane
        out past its own right edge, values first.

        It was survivable while the strings were short: "Unsaved changes." wants
        88 pixels of a 202-pixel column.  A funny level made every one of them
        overflow -- 280 pixels for that same sentence at level five, 904 in
        bilingual mode, which is four and a half times the column it has to fit
        in.  The tone is correct here, because this is a message rather than a
        label; what was wrong is that the label was never sized for a sentence
        of any length.

        The breaks are measured here rather than left to a control's own
        ``Wrap``.  The word wrap behind that splits on spaces and elides
        whatever will not fit, and a Cantonese sentence carries no spaces at
        all, so the whole of it arrives as one over-long "word" and is cut to
        an ellipsis -- which matters exactly here, because this label is
        rewritten on every keystroke and every save.  ``wrap_status`` breaks an
        unbreakable run by character instead, and ``notification_toast``
        measures its own breaks for the same reason.

        The font comes from :meth:`StudioText.text_font` rather than
        ``GetFont``: nothing pushes a font into an owner-drawn label, so
        ``GetFont`` answers with the platform's default GUI font and the
        measurement would be for a font the pane never draws.

        The accessible name keeps the unwrapped single line, so a screen reader
        reads a sentence rather than the pane's line breaks.
        """
        message = single_line(text)
        self.notes_status.SetName(f"Project note status: {message}")
        if message:
            dc = wx.ClientDC(self.notes_status)
            dc.SetFont(self.notes_status.text_font())
            message = wrap_status(dc, message, self._note_width())
        self.notes_status.SetLabel(message)
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

    def _on_resize(self, event: wx.SizeEvent) -> None:
        """Re-lay the tab when the sash has changed the column's width.

        Only a real width change triggers it, and only after the size event has
        finished: rebuilding from inside the event is how a layout pass ends up
        calling itself.
        """
        event.Skip()
        if abs(self.GetClientSize().width - self._built_width) >= tokens.scaled(8):
            wx.CallAfter(self._rebuild_for_width)

    def _rebuild_for_width(self) -> None:
        try:
            if self.IsBeingDeleted():
                return
        except RuntimeError:  # pragma: no cover - the pane has already gone
            return
        if abs(self.GetClientSize().width - self._built_width) >= tokens.scaled(8):
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
        # The four text labels resolve their own ink and font from the palette
        # and the live interface scale, so pushing a colour or a font into them
        # here would only pin what they already track -- and a pinned font is a
        # label that stops re-measuring when the scale moves.
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
    "ANCHOR_FIELD_LABEL",
    "ANCHOR_SENTENCES",
    "ANCHOR_SIZE_UNKNOWN",
    "DEFAULT_NUDGE_STEP",
    "DEFAULT_REVISIONS",
    "DEFAULT_SECTIONS",
    "MAX_NOTE_LENGTH",
    "MAX_NUDGE_STEP",
    "MIN_PANEL_WIDTH",
    "NUDGE_FIELD_WIDTH",
    "NOTES_CONFIG_ID",
    "PASTE_ANCHOR_CONFIG_ID",
    "PASTE_BOX_ROWS",
    "NO_HISTORY_AVAILABLE",
    "NO_PROJECT_HISTORY",
    "NO_REVISIONS_YET",
    "NO_TOOL_ACTIVE",
    "NO_WORLD_PROPERTIES",
    "PANEL_WIDTH",
    "PANE_TABS",
    "TAB_LABELS",
    "TOOL_TAB",
    "VECTOR_BOX_WIDTH",
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
    "load_paste_anchor",
    "load_project_revisions",
    "note_for",
    "revision_from_event",
    "store_note",
    "store_paste_anchor",
    "world_sections",
]
