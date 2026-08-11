"""Which real editor tool a Studio tool surface activates, and what it holds.

Clone, Move, Select block, Edit chunk, Generate, Paste, Import and Export are
not windows.  They are the editor's own in-canvas tools -- the ones in
``amulet_map_editor.programs.edit.plugins.tools`` -- driven by
``EditCanvas``, with their handles drawn in the viewport over the world.  This
module is the one place that knows which Studio surface key means which of
them, so a ribbon tile, a palette row, a context menu and the properties pane
all reach the same tool by the same route.

Activating a tool here does exactly what pressing the editor's own tool button
does: it posts a ``ToolChangeEvent`` at the canvas.  Nothing is simulated and
no options window opens.  Clone and Move additionally lift the selection first
-- ``EditCanvas.copy`` for a clone, ``EditCanvas.cut`` for a move -- and then
``EditCanvas.paste_from_cache``, which is the editor's own copy-then-paste
path and the same one the shell's rotate and mirror commands already use.  The
result is a live pending object: the paste tool holds it, the renderer draws
it, and it is written into the world only when it is confirmed.

Three things this module refuses to do.  It never claims a tool exists when it
does not: ``brushTool``, ``floodFill`` and ``selectEntityTool`` are listed here
with what is missing, so a caller can say so rather than opening a form whose
fields write nothing.  It never invents a second mechanism for the pending
object: position, rotation and scale are read from and written to the paste
tool's own inputs, because those are the values its confirm actually pastes.
And it never reports a success it has not seen -- every entry point returns an
:class:`Activation` saying what happened.

The module carries no wxPython at import time so the table can be read and
asserted on without a display; wx and the editor package are imported inside
the functions that need them.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from amulet_map_editor.api.outcome import Outcome
from amulet_map_editor.api.studio import context

log = logging.getLogger(__name__)

__all__ = [
    "ANCHORS",
    "ANCHOR_BASE",
    "ANCHOR_CENTRE",
    "ANCHOR_LABELS_CANTONESE",
    "ANCHOR_MAXIMUM",
    "ANCHOR_MINIMUM",
    "Activation",
    "BRIDGES",
    "Outcome",
    "PASTE_OUTCOME_REASONS",
    "PendingObject",
    "STOCK_OPERATIONS",
    "SelectionState",
    "ToolBridge",
    "activate",
    "active_operation_name",
    "active_tool_name",
    "anchor_label",
    "anchor_label_cantonese",
    "anchor_offset",
    "anchor_point",
    "bridge",
    "camera_location",
    "cancel_pending",
    "canvas",
    "confirm_pending",
    "install_surface_routes",
    "is_tool_surface",
    "keys",
    "location_for_anchor",
    "movement_keys",
    "movement_sentence",
    "normalise_anchor",
    "nudge_pending",
    "paste_box",
    "pending_object",
    "selection_state",
    "set_pending_location",
    "set_pending_rotation",
    "set_pending_scale",
    "stop_following",
    "tool_named",
]


# ---------------------------------------------------------------------------
# the table
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolBridge:
    """One Studio surface key and the editor tool behind it.

    ``tool`` is the name the editor's own tool manager registers, so it is what
    ``EditCanvas.tools`` is keyed by.  An empty ``tool`` means this build has no
    implementation, and ``missing`` says what is absent -- that string is meant
    to be shown, not logged and swallowed.
    """

    key: str
    label: str
    tool: str
    kind: str
    summary: str
    missing: str = ""
    lift: str = ""
    needs_selection: bool = False
    #: The operation plugin this surface asks the tool to select, by the name
    #: its own ``export`` gives it.  Empty means the tool starts on whatever it
    #: was last showing, which is what the plain ``operationOptions`` key means.
    operation: str = ""

    @property
    def available(self) -> bool:
        """Return whether something real runs when this is activated."""
        return bool(self.tool)


def _bridge(**kwargs: Any) -> Tuple[str, ToolBridge]:
    entry = ToolBridge(**kwargs)
    return entry.key, entry


#: The stock operations the Operations tab offers as tiles: the surface key, the
#: label the tile shows, and the operation plugin's own ``export["name"]``.  The
#: third column is the one that matters -- it is handed to the Operation tool as
#: the tool change's state, and the tool selects it in its own list.
STOCK_OPERATIONS: Tuple[Tuple[str, str, str], ...] = (
    ("operationClone", "Clone", "Clone"),
    ("operationFill", "Fill", "Fill"),
    ("operationReplace", "Replace", "Replace"),
    ("operationSetBiome", "Set biome", "Set Biome"),
    ("operationWaterlog", "Waterlog", "Waterlog"),
)


def _operation_bridges() -> Tuple[Tuple[str, ToolBridge], ...]:
    """Return one bridge per stock operation, each naming its own operation."""
    return tuple(
        _bridge(
            key=key,
            label=label,
            tool="Operation",
            kind="operation",
            operation=operation,
            summary=(
                f"Activates the editor's Operation tool with the {operation} "
                "operation selected, so its own options are in front of you "
                "without the list having to be searched first. Options taller "
                "than the pane scroll, and the Run control under them scrolls "
                "with them."
            ),
        )
        for key, label, operation in STOCK_OPERATIONS
    )


#: Every Studio surface key this module answers for.  A key that is not here is
#: not a tool surface and is left to whatever else routes it.
BRIDGES: Mapping[str, ToolBridge] = MappingProxyType(
    dict(
        (
            _bridge(
                key="selectBlockTool",
                label="Select block",
                tool="Select",
                kind="selection",
                summary=(
                    "Activates the editor's Select tool: a block-coordinate "
                    "selection box with a nudge control for each corner and "
                    "block inspection in the viewport."
                ),
                missing=(
                    "Selecting every block that matches a block state is not "
                    "implemented; this selects a region."
                ),
            ),
            _bridge(
                key="cloneTool",
                label="Clone",
                tool="Paste",
                kind="pending",
                lift="copy",
                needs_selection=True,
                summary=(
                    "Copies the selection and hands it to the paste tool as a "
                    "live pending object. The source stays where it is, and "
                    "nothing is written until the copy is confirmed."
                ),
            ),
            _bridge(
                key="moveTool",
                label="Move",
                tool="Paste",
                kind="pending",
                lift="cut",
                needs_selection=True,
                summary=(
                    "Cuts the selection out and hands it to the paste tool as a "
                    "live pending object, so it can be placed somewhere else "
                    "and confirmed."
                ),
            ),
            _bridge(
                key="pendingImports",
                label="Pending imports",
                tool="Paste",
                kind="pending",
                summary=(
                    "Shows the object the paste tool is holding: its position, "
                    "its rotation, its scale, and the two ways out of it."
                ),
            ),
            _bridge(
                key="editChunkTool",
                label="Edit chunk",
                tool="Chunk",
                kind="chunk",
                summary=(
                    "Activates the editor's Chunk tool, which selects whole "
                    "chunks from a top-down view and can create, delete, prune "
                    "and import them."
                ),
            ),
            _bridge(
                key="importChunks",
                label="Import chunks",
                tool="Chunk",
                kind="chunk",
                summary=(
                    "Activates the editor's Chunk tool, whose Import chunks "
                    "button reads the selected chunks out of another world."
                ),
            ),
            _bridge(
                key="generateTool",
                label="Generate",
                tool="Operation",
                kind="operation",
                summary=(
                    "Activates the editor's Operation tool. Generators are "
                    "operation plugins, so the generator to run is picked from "
                    "the list of installed operations in the viewport."
                ),
                missing=(
                    "There is no dedicated generator tool; what runs is "
                    "whichever operation plugin is chosen."
                ),
            ),
            _bridge(
                key="operationOptions",
                label="Run operation",
                tool="Operation",
                kind="operation",
                summary=(
                    "Activates the editor's Operation tool, which lists every "
                    "installed operation plugin and shows the chosen one's own "
                    "options."
                ),
            ),
            # One key per stock operation, because one key for all of them is a
            # tile that cannot mean anything different from its neighbour.  The
            # five below shared ``operationOptions`` and therefore all arrived on
            # whichever operation the chooser sorted first, which is Clone -- so
            # Clone looked correct while its four siblings silently opened it
            # instead of themselves.  ``operation`` is the plugin's own
            # ``export["name"]``, and it is what the chooser is asked for.
            *_operation_bridges(),
            _bridge(
                key="exportStructure",
                label="Export selection",
                tool="Export",
                kind="export",
                summary=(
                    "Activates the editor's Export tool, which writes the "
                    "selection out through the installed export operations."
                ),
            ),
            _bridge(
                key="importStructure",
                label="Import structure",
                tool="Import",
                kind="import",
                summary=(
                    "Activates the editor's Import tool, which asks for a "
                    "structure file and hands it to the paste tool as a pending "
                    "object."
                ),
            ),
            _bridge(
                key="brushTool",
                label="Shape brush",
                tool="",
                kind="unavailable",
                summary="",
                missing=(
                    "This build has no brush tool. The editor ships Select, "
                    "Paste, Operation, Import, Export and Chunk, and none of "
                    "them paints a shape along the pointer."
                ),
            ),
            _bridge(
                key="floodFill",
                label="Flood fill",
                tool="",
                kind="unavailable",
                summary="",
                missing=(
                    "This build has no flood fill. The stock Fill operation "
                    "fills the whole selection rather than a connected region, "
                    "so it is not the same tool and is not offered as one."
                ),
            ),
            _bridge(
                key="selectEntityTool",
                label="Select entity",
                tool="",
                kind="unavailable",
                summary="",
                missing=(
                    "This build has no entity selection tool. The editor's "
                    "selection is a region of blocks; entities are not "
                    "selectable on their own."
                ),
            ),
        )
    )
)


def keys() -> Tuple[str, ...]:
    """Return every Studio surface key this module answers for."""
    return tuple(BRIDGES)


def bridge(key: str) -> Optional[ToolBridge]:
    """Return the bridge for one surface key, or ``None``."""
    return BRIDGES.get(str(key or ""))


def is_tool_surface(key: str) -> bool:
    """Return whether this key names an editor tool rather than a window."""
    return str(key or "") in BRIDGES


# ---------------------------------------------------------------------------
# reaching the live editor
# ---------------------------------------------------------------------------


def canvas() -> Any:
    """Return the live editor canvas, or ``None`` when no world is open.

    The world context is the one object handed the canvas, so it is asked here
    exactly as the status bar and the properties pane ask it, rather than each
    surface keeping a reference of its own that goes stale when a world closes.
    """
    getter = getattr(context, "canvas", None)
    if callable(getter):
        try:
            return getter()
        except Exception:  # noqa: BLE001 - a canvas mid-teardown answers this
            return None
    return getattr(context, "_canvas", None)


def _resolve(target: Any) -> Any:
    """Return ``target`` when it is a canvas, otherwise the live one."""
    return canvas() if target is None else target


def tool_named(name: str, target: Any = None) -> Any:
    """Return one of the editor's tools by its own name, or ``None``.

    The tools are sizers rather than windows, so a child walk never finds them;
    the canvas's own mapping is the only route.
    """
    active = _resolve(target)
    if active is None:
        return None
    try:
        return active.tools.get(str(name))
    except Exception:  # noqa: BLE001 - a canvas without its tool manager yet
        log.debug("Could not read the editor tools", exc_info=True)
        return None


def active_tool_name(target: Any = None) -> str:
    """Return the name of the tool the canvas has enabled, or ``""``.

    The tool manager keeps the active tool privately and exposes no accessor,
    so it is read directly and cross-checked against the canvas's own mapping.
    When that attribute is not there, the tool whose panels are on screen is the
    answer, because showing its windows is what enabling a tool does.
    """
    active = _resolve(target)
    if active is None:
        return ""
    try:
        tools = dict(active.tools)
    except Exception:  # noqa: BLE001 - a canvas without its tool manager yet
        return ""
    manager = getattr(active, "_tool_sizer", None)
    current = getattr(manager, "_active_tool", None)
    if current is not None:
        for name, tool in tools.items():
            if tool is current:
                return str(name)
    for name, tool in tools.items():
        windows = []
        try:
            windows = [window for window in tool.windows() if window]
        except Exception:  # noqa: BLE001 - a tool mid-teardown answers this
            continue
        if windows and all(window.IsShown() for window in windows):
            return str(name)
    return ""


def _same_operation(left: str, right: str) -> bool:
    """Return whether two operation names are the same one, spelled either way.

    ``Set Biome`` is the plugin's spelling and ``Set biome`` is the tile's, so
    an exact comparison would report a correct arrival as a failure.
    """
    return (
        " ".join(str(left or "").split()).casefold()
        == " ".join(str(right or "").split()).casefold()
    )


def active_operation_name(target: Any = None) -> str:
    """Return the operation the editor's Operation tool is showing, or ``""``.

    Read from the tool's own chooser, which is the control the user is looking
    at, rather than from anything a caller remembers having asked for.
    """
    tool = tool_named("Operation", target)
    if tool is None:
        return ""
    try:
        return str(tool.active_operation_name or "")
    except Exception:  # noqa: BLE001 - a tool without its chooser yet
        log.debug("Could not read the selected operation", exc_info=True)
        return ""


def _settle(passes: int = 3) -> None:
    """Let the canvas handle the events just posted at it.

    A tool change is a posted event, so without this the next line would read
    the tool that was active a moment ago and report it as the one that just
    started -- which is the difference between saying what happened and saying
    what was asked for.
    """
    try:
        import wx
    except Exception:  # pragma: no cover - no wx in this interpreter
        return
    app = wx.GetApp()
    if app is None:
        return
    for _ in range(max(1, passes)):
        try:
            app.ProcessPendingEvents()
            wx.Yield()
        except Exception:  # noqa: BLE001 - yielding inside a yield
            return


def _post_tool_change(target: Any, name: str, state: Any = None) -> bool:
    """Ask the editor to switch tools, the way its own buttons do.

    A true answer means the event was **posted and settled**, not that the tool
    changed: the switch is somebody else's handler and it may refuse.  Every
    caller here therefore checks the canvas afterwards -- ``_switch`` against
    ``active_tool_name`` and ``cancel_pending`` against the paste tool having
    let go -- and a new caller that reports this return as an outcome would be
    reporting that it asked.
    """
    try:
        import wx

        from amulet_map_editor.programs.edit.api.events import ToolChangeEvent

        wx.PostEvent(target, ToolChangeEvent(tool=str(name), state=state))
    except Exception:
        log.exception("Could not switch the editor to the %r tool", name)
        return False
    _settle()
    return True


def _report(parent: Any, title: str, body: str, severity: str = "warning") -> None:
    """Say what happened where the user can see it, without blocking anything."""
    try:
        from amulet_map_editor.api.wx import nonblocking

        nonblocking.notify(parent, title, body, severity=severity)
    except Exception:  # pragma: no cover - the reporter itself is unavailable
        log.warning("%s: %s", title, body)


def _say(english: str, cantonese: str) -> str:
    """Return one message in the reader's language and tone.

    The tone styles the voice and never the fact: ``studio_text`` leaves an
    identifier, a coordinate or a count exactly as it was written and appends
    its aside around the sentence, so a funny level cannot change which
    operation failed or what the undo depth was.  When the copy module cannot
    be reached at all the English is returned rather than nothing -- a message
    in the wrong language is still a message, and silence is not.
    """
    try:
        from amulet_map_editor.api.studio.copy import studio_text

        return studio_text(english, cantonese)
    except Exception:  # noqa: BLE001 - preferences unreadable this early
        log.debug("Studio copy is unavailable; reporting in English", exc_info=True)
        return english


def _one_line(text: str) -> str:
    """Flatten a heading onto one line for a surface that will not take two.

    Bilingual mode joins its two labels with a newline, which is right for a
    pane that renders a prominent line above a compact one and wrong for a
    notification title: the store rejects every character below space, so a
    two-line title raised out of the notifier and the message never reached the
    notification centre at all.  Silently losing the report of a lost paste is
    the same defect one layer further out, so the separator becomes the one the
    notifier already uses for a folded body.
    """
    return " · ".join(part.strip() for part in str(text).splitlines() if part.strip())


def _say_label(english: str, cantonese: str) -> str:
    """Return a short heading in the reader's language, with no tone applied.

    A notification title is a name rather than the application talking, and a
    name with a funny-level aside on the end stops being a name and starts
    being clipped.
    """
    try:
        from amulet_map_editor.api.studio.copy import studio_label

        return studio_label(english, cantonese)
    except Exception:  # noqa: BLE001 - preferences unreadable this early
        log.debug("Studio copy is unavailable; reporting in English", exc_info=True)
        return english


#: This module's own :class:`Outcome` reason tokens, all of them failures.
#:
#: ``nothing-pending`` -- the paste tool is not holding anything, so the surface
#: showing it is stale.  ``no-confirm`` -- this build's paste tool has no
#: confirm at all.  ``not-written`` -- the confirm ran and the world did not
#: change.  ``still-held`` -- the object was not dropped and is still drawn.
#: ``aborted`` -- the paste was stopped on purpose, by the user cancelling its
#: progress dialog or by the operation ending itself, so nothing went wrong and
#: there is nothing to report as an error.
#:
#: Those five want five different things from the interface, which is exactly
#: why a bare ``False`` was not enough: it made "the tool went away" and "your
#: blocks were not written" the same answer.
#:
#: The class itself lives in :mod:`amulet_map_editor.api.outcome` so the canvas
#: can return the same shape without importing Studio, and is re-exported here
#: because ``editor_tools.Outcome`` is what every caller and test already reads.
PASTE_OUTCOME_REASONS: Tuple[str, ...] = (
    "nothing-pending",
    "no-confirm",
    "not-written",
    "still-held",
    "aborted",
)


def _refused(
    parent: Any,
    reason: str,
    title: Tuple[str, str],
    message: Tuple[str, str],
    severity: str = "error",
) -> Outcome:
    """Build one failed outcome and say it where the user can see it.

    Reporting happens here rather than being left to the caller for the reason
    the module's activations already report their own refusals: a caller that
    forgets is a silent failure, and a silent failure after a button press is
    indistinguishable from a success.
    """
    said_title = _one_line(_say_label(*title))
    said_message = _say(*message)
    _report(parent, said_title, said_message, severity=severity)
    return Outcome(ok=False, reason=reason, title=said_title, message=said_message)


# ---------------------------------------------------------------------------
# the selection a tool acts on
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SelectionState:
    """What the canvas currently has selected, as a tool sees it."""

    boxes: int = 0
    volume: int = 0
    minimum: Tuple[int, int, int] = (0, 0, 0)
    maximum: Tuple[int, int, int] = (0, 0, 0)
    readable: bool = False

    @property
    def empty(self) -> bool:
        """Return whether there is nothing for a tool to act on."""
        return not self.readable or self.volume <= 0


def selection_state(target: Any = None) -> SelectionState:
    """Read the canvas's current selection, or report that it could not be."""
    active = _resolve(target)
    if active is None:
        return SelectionState()
    try:
        group = active.selection.selection_group
        boxes = len(group.selection_boxes)
        if not boxes:
            return SelectionState(readable=True)
        return SelectionState(
            boxes=boxes,
            volume=int(group.volume),
            minimum=tuple(int(value) for value in group.min),
            maximum=tuple(int(value) for value in group.max),
            readable=True,
        )
    except Exception:  # noqa: BLE001 - a canvas without a selection manager
        log.debug("Could not read the editor selection", exc_info=True)
        return SelectionState()


# ---------------------------------------------------------------------------
# where a paste actually lands
# ---------------------------------------------------------------------------
#
# The paste tool's ``location`` is the *centre* of the structure, not a corner.
# amulet-core's clone takes ``rotation_point = (min + max) // 2`` of the source
# bounds and displaces the whole thing by ``location - rotation_point``, so a
# 4x1x4 slab sent to ``(8, 40, 8)`` fills ``(6, 40, 6)..(9, 40, 9)`` -- half a
# structure away from the numbers the user typed, with nothing on screen saying
# so.  That is the most likely cause of "cloning doesn't work" from somebody who
# typed the coordinate they wanted.
#
# Since ``rotation_point`` is ``src_min + extent // 2`` for any source position,
# the offset depends only on the extent, never on where the structure was copied
# from.  So the box a paste will fill can be worked out here, from the extent and
# the transform alone, and shown beside the numbers as they are typed.

#: The anchor a typed position refers to.  ``ANCHOR_CENTRE`` is the editor's own
#: behaviour and stays the default, so an existing habit keeps working.
ANCHOR_CENTRE = "centre"
ANCHOR_BASE = "base"
ANCHOR_MINIMUM = "minimum"
ANCHOR_MAXIMUM = "maximum"

#: Every anchor, in the order they are offered, as ``(key, label)``.  The labels
#: name a direction rather than a word like "origin", because which corner is
#: meant is the whole question this control exists to answer.
ANCHORS: Tuple[Tuple[str, str], ...] = (
    (ANCHOR_CENTRE, "Centre of the copy"),
    (ANCHOR_BASE, "Centre of its base"),
    (ANCHOR_MINIMUM, "Lowest corner, -x -y -z"),
    (ANCHOR_MAXIMUM, "Highest corner, +x +y +z"),
)

#: The same four names in Cantonese, kept beside the English rather than folded
#: into :data:`ANCHORS` so the tuple stays the two-column table every caller and
#: test already reads.  They live in this module because the anchors themselves
#: do: a surface that offers them should not have to keep its own second list
#: that can drift out of step with the keys.
#:
#: This module deliberately imports nothing from the copy pipeline -- it carries
#: no wx and no preferences -- so it publishes both languages and lets the
#: surface drawing the control decide which one the reader gets.
ANCHOR_LABELS_CANTONESE: Dict[str, str] = {
    ANCHOR_CENTRE: "成嚿嘢嘅正中心",
    ANCHOR_BASE: "底面嘅中心",
    ANCHOR_MINIMUM: "最細嗰隻角，-x -y -z",
    ANCHOR_MAXIMUM: "最大嗰隻角，+x +y +z",
}

#: Bigger than any real structure, and far below the +/-30,000,000 a whole
#: world's bounds report.  A pending object whose extent exceeds this is one
#: whose bounds were not the structure's, so no box is claimed for it.
MAX_PASTE_EXTENT = 1_000_000


def normalise_anchor(anchor: Any) -> str:
    """Return a known anchor key, falling back to the editor's own behaviour."""
    value = str(anchor or "").strip().lower()
    return value if value in dict(ANCHORS) else ANCHOR_CENTRE


def anchor_label(anchor: Any) -> str:
    """Return the human name of an anchor key."""
    return dict(ANCHORS)[normalise_anchor(anchor)]


def anchor_label_cantonese(anchor: Any) -> str:
    """Return the Cantonese name of an anchor key.

    Every key in :data:`ANCHORS` has one, so this never falls back to English;
    a missing translation would be a silently English option sitting in a list
    of Cantonese ones, which is the defect this pair of functions exists to
    prevent rather than reproduce.
    """
    return ANCHOR_LABELS_CANTONESE[normalise_anchor(anchor)]


def _rotate(
    point: Tuple[float, float, float], radians: Tuple[float, float, float]
) -> Tuple[float, float, float]:
    """Rotate a point about the origin, x then y then z.

    The same order and the same handedness as
    :func:`amulet.utils.matrix.transform_matrix` with its default ``xyz``
    order, which is what the paste itself uses.  Written out in plain
    arithmetic so this module keeps its promise of importing without numpy or a
    display.
    """
    x, y, z = (float(value) for value in point)
    rx, ry, rz = radians
    cos, sin = math.cos(rx), math.sin(rx)
    y, z = y * cos - z * sin, y * sin + z * cos
    cos, sin = math.cos(ry), math.sin(ry)
    x, z = x * cos + z * sin, -x * sin + z * cos
    cos, sin = math.cos(rz), math.sin(rz)
    x, y = x * cos - y * sin, x * sin + y * cos
    return x, y, z


def paste_box(
    location: Sequence[float],
    extent: Sequence[int],
    scale: Sequence[float] = (1.0, 1.0, 1.0),
    rotation: Sequence[float] = (0.0, 0.0, 0.0),
) -> Optional[Tuple[Tuple[int, int, int], Tuple[int, int, int]]]:
    """Return the inclusive block box a paste would fill, or ``None``.

    ``None`` means the held object's extent could not be read, which is a
    different fact from an empty box and must not be shown as one: a readout
    that quietly says ``0, 0, 0`` when it does not know is the failure this
    whole surface exists to remove.

    At the default transform this is exactly the box amulet-core writes.  Under
    a rotation or a scale it is the axis-aligned bounding box of the transformed
    structure, which is exact for the 90-degree turns the tool's own buttons
    make and a true bound for anything in between.
    """
    try:
        sizes = tuple(int(value) for value in extent)
        origin = tuple(int(round(float(value))) for value in location)
        factors = tuple(float(value) for value in scale)
        radians = tuple(math.radians(float(value)) for value in rotation)
    except (TypeError, ValueError):
        return None
    if len(sizes) != 3 or len(origin) != 3 or len(factors) != 3 or len(radians) != 3:
        return None
    if any(size <= 0 or size > MAX_PASTE_EXTENT for size in sizes):
        return None

    # The structure's own corners, relative to the point the paste rotates and
    # displaces about.  ``low`` is the minimum block and ``high`` is one past
    # the maximum, which is how amulet-core holds selection bounds.
    low = tuple(-(size // 2) for size in sizes)
    high = tuple(size - size // 2 for size in sizes)
    corners = [
        _rotate((x * factors[0], y * factors[1], z * factors[2]), radians)
        for x in (low[0], high[0])
        for y in (low[1], high[1])
        for z in (low[2], high[2])
    ]
    # A hair of tolerance so an exact integer corner is not pushed a whole block
    # outwards by the floating point a rotation of zero still goes through.
    minimum = tuple(
        origin[axis] + int(math.floor(min(corner[axis] for corner in corners) + 1e-9))
        for axis in range(3)
    )
    maximum = tuple(
        origin[axis]
        + int(math.ceil(max(corner[axis] for corner in corners) - 1e-9))
        - 1
        for axis in range(3)
    )
    maximum = tuple(max(low, high) for low, high in zip(minimum, maximum))
    return minimum, maximum  # type: ignore[return-value]


def anchor_offset(
    minimum: Sequence[int], maximum: Sequence[int], anchor: Any = ANCHOR_CENTRE
) -> Tuple[int, int, int]:
    """Return how far an anchor sits from the minimum corner of a box."""
    size = tuple(int(high) - int(low) + 1 for low, high in zip(minimum, maximum))
    key = normalise_anchor(anchor)
    if key == ANCHOR_MINIMUM:
        return (0, 0, 0)
    if key == ANCHOR_MAXIMUM:
        return tuple(max(0, value - 1) for value in size)  # type: ignore[return-value]
    if key == ANCHOR_BASE:
        return (size[0] // 2, 0, size[2] // 2)
    return tuple(value // 2 for value in size)  # type: ignore[return-value]


def anchor_point(
    location: Sequence[float],
    extent: Sequence[int],
    scale: Sequence[float] = (1.0, 1.0, 1.0),
    rotation: Sequence[float] = (0.0, 0.0, 0.0),
    anchor: Any = ANCHOR_CENTRE,
) -> Optional[Tuple[int, int, int]]:
    """Return where a tool position reads as, under one anchor."""
    box = paste_box(location, extent, scale, rotation)
    if box is None:
        return None
    minimum, maximum = box
    return tuple(  # type: ignore[return-value]
        value + offset
        for value, offset in zip(minimum, anchor_offset(minimum, maximum, anchor))
    )


def location_for_anchor(
    point: Sequence[float],
    extent: Sequence[int],
    scale: Sequence[float] = (1.0, 1.0, 1.0),
    rotation: Sequence[float] = (0.0, 0.0, 0.0),
    anchor: Any = ANCHOR_CENTRE,
) -> Optional[Tuple[int, int, int]]:
    """Return the tool position that puts an anchor on a block.

    The inverse of :func:`anchor_point`, and it is an exact inverse because the
    transform only ever translates the box: the box at the origin plus the
    position is the box at that position, so the position is the difference.
    """
    box = paste_box((0, 0, 0), extent, scale, rotation)
    if box is None:
        return None
    minimum, maximum = box
    offset = anchor_offset(minimum, maximum, anchor)
    try:
        wanted = tuple(int(round(float(value))) for value in point)
    except (TypeError, ValueError):
        return None
    if len(wanted) != 3:
        return None
    return tuple(  # type: ignore[return-value]
        value - start - shift for value, start, shift in zip(wanted, minimum, offset)
    )


# ---------------------------------------------------------------------------
# the pending object
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PendingObject:
    """The object the paste tool is holding, as the pane shows it.

    ``location`` is in blocks, ``rotation`` in degrees and ``scale`` a
    multiplier per axis -- the same units the paste tool's own inputs use, and
    the same ones its confirm pastes with.  ``following`` is true while the
    object is tracking the pointer, which is why a value typed into the pane
    would otherwise be overwritten on the next mouse move.
    """

    location: Tuple[int, int, int] = (0, 0, 0)
    rotation: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    scale: Tuple[float, float, float] = (1.0, 1.0, 1.0)
    following: bool = False
    drawn: bool = False
    #: How big the held object is, in blocks, as ``x by y by z``.  It is the
    #: extracted structure's own bounds rather than the selection's, so a
    #: pending object that came from a file says what it really is.
    size: str = ""
    #: The same measurement as numbers, per axis, or ``(0, 0, 0)`` when the
    #: held object's bounds could not be read.  ``size`` is for showing and
    #: this is for arithmetic: :func:`paste_box` needs the extent to say where
    #: a paste will land, and parsing it back out of a sentence would be a
    #: second place for the two to stop agreeing.
    extent: Tuple[int, int, int] = (0, 0, 0)


def camera_location(target: Any = None) -> Optional[Tuple[int, int, int]]:
    """Return the block the editor's camera is standing on, or ``None``."""
    active = _resolve(target)
    if active is None:
        return None
    try:
        x, y, z = active.camera.location
    except Exception:  # noqa: BLE001 - a canvas without a camera yet
        return None
    return (int(round(x)), int(round(y)), int(round(z)))


def _paste_tool(target: Any = None) -> Any:
    """Return the paste tool when it is holding something, or ``None``."""
    tool = tool_named("Paste", target)
    if tool is None:
        return None
    if not getattr(tool, "_is_enabled", False):
        return None
    return tool


def _tuple_input(tool: Any, name: str) -> Any:
    """Return one of the paste tool's coordinate inputs, or ``None``.

    The tool exposes a public setter for its location alone, so the rotation
    and scale inputs are reached directly.  They are the values its confirm
    reads, so writing anywhere else would move the drawing and paste the old
    numbers.
    """
    return getattr(tool, name, None)


def _values(widget: Any, fallback: Sequence[float]) -> Tuple[float, ...]:
    try:
        return tuple(float(value) for value in widget.value)
    except Exception:  # noqa: BLE001 - an input that has been destroyed
        return tuple(float(value) for value in fallback)


def pending_object(target: Any = None) -> Optional[PendingObject]:
    """Return what the paste tool is holding, or ``None`` when it holds nothing.

    ``None`` and an object with ``drawn`` false are different facts: the first
    says no pending object exists, the second says one exists but the renderer
    is not currently drawing it, and merging them would hide a renderer fault
    behind an empty state.
    """
    active = _resolve(target)
    tool = _paste_tool(active)
    if tool is None:
        return None
    location = _values(_tuple_input(tool, "_location"), (0, 0, 0))
    rotation = _values(_tuple_input(tool, "_rotation"), (0.0, 0.0, 0.0))
    scale = _values(_tuple_input(tool, "_scale"), (1.0, 1.0, 1.0))
    drawn = False
    try:
        drawn = active.renderer.fake_levels.active_level_index is not None
    except Exception:  # noqa: BLE001 - no renderer on this canvas
        drawn = False
    extent = _pending_extent(active)
    return PendingObject(
        location=tuple(int(round(value)) for value in location),
        rotation=tuple(float(value) for value in rotation),
        scale=tuple(float(value) for value in scale),
        following=bool(getattr(tool, "_moving", False)),
        drawn=drawn,
        size=" by ".join(str(value) for value in extent) if any(extent) else "",
        extent=extent,
    )


def _pending_extent(target: Any) -> Tuple[int, int, int]:
    """Return the held object's own extent in blocks, or ``(0, 0, 0)``.

    The structure's bounds are asked rather than the selection's, because the
    two stop agreeing the moment a second thing is copied, and this is meant to
    say what is actually being carried.
    """
    try:
        levels = target.renderer.fake_levels
        index = levels.active_level_index
        if index is None:
            return (0, 0, 0)
        render_level = levels.render_levels[index]
        level = render_level.level
        bounds = level.bounds(render_level.dimension)
        extent = [int(high) - int(low) for low, high in zip(bounds.min, bounds.max)]
        if len(extent) != 3:
            return (0, 0, 0)
        return (extent[0], extent[1], extent[2])
    except Exception:  # noqa: BLE001 - a renderer without a fake level
        return (0, 0, 0)


def _push_transform(tool: Any, target: Any) -> bool:
    """Send the tool's inputs to the renderer so the drawing agrees with them.

    Returns whether the renderer was told.  A false answer does **not** mean the
    value was rejected: the tool's own inputs are what its confirm pastes, and
    those have already been written by the caller, so a failure here means the
    drawing has fallen behind the numbers rather than that the numbers were
    lost.  That is why the callers still report success -- reporting a refusal
    would be the opposite lie.

    The tool's own updater used to be called bare.  Every caller here is a wx
    button or a typed value, so a renderer that raised turned a value change
    into an unhandled exception out of the event handler instead of a logged
    warning; catching it keeps the tool usable and keeps the fault visible.
    """
    update = getattr(tool, "_update_transform", None)
    if callable(update):
        try:
            update()
        except Exception:  # noqa: BLE001 - a renderer mid-teardown
            log.warning(
                "The paste tool's transform was set but the renderer refused it, "
                "so the drawing may lag the values shown",
                exc_info=True,
            )
            return False
        return True
    try:
        target.renderer.fake_levels.active_transform = (
            _values(_tuple_input(tool, "_location"), (0, 0, 0)),
            _values(_tuple_input(tool, "_scale"), (1.0, 1.0, 1.0)),
            tuple(
                math.radians(value)
                for value in _values(_tuple_input(tool, "_rotation"), (0.0, 0.0, 0.0))
            ),
        )
    except Exception:  # noqa: BLE001 - no renderer to update
        log.debug("Could not push the pending transform to the renderer", exc_info=True)
        return False
    return True


def stop_following(target: Any = None) -> bool:
    """Set the pending object down where it is, and say whether it could be.

    This is the same state the editor's own left click in the viewport toggles;
    an object still following the pointer takes its position from the pointer
    on every mouse move, so a typed coordinate would not survive one.

    The flag is read back rather than assumed.  A tool that ignored the write --
    a property with a setter of its own, a stand-in that does not carry the
    attribute -- would otherwise leave this reporting that the object had been
    set down while it went on following the pointer, and the next typed
    coordinate would be overwritten with no sign of why.  The renderer's own
    agreement is a separate question: see :func:`_push_transform` for why a
    drawing that lags the values is not a failure of this call.
    """
    active = _resolve(target)
    tool = _paste_tool(active)
    if tool is None:
        return False
    tool._moving = False
    _push_transform(tool, active)
    if getattr(tool, "_moving", False):
        log.error("The paste tool is still following the pointer after being set down")
        return False
    return True


def set_pending_location(
    location: Sequence[float], target: Any = None, *, drop: bool = True
) -> bool:
    """Move the pending object to a block position.

    **Why this one does not read the position back**, when :func:`stop_following`
    two functions above deliberately does.  The tool's own coordinate boxes are
    spin controls bounded to the world's limits, so a position outside them is
    answered with the nearest position inside them.  That is a real move and the
    right one; a read-back that compared the value would call it a failure, and
    two of the three callers answer a failure by deciding the tool has gone.
    The pane's ``_nudge`` (through :func:`nudge_pending`) and its
    ``_pending_to_camera`` both reach ``_report_tool_gone``, which takes the
    pending panel away -- so nudging into the world's edge would make the panel
    vanish while the copy stayed held and drawn: the exact defect
    :func:`confirm_pending` was fixed for, arriving through the position boxes
    instead.  The third caller, ``_on_location_typed``, ignores the return
    entirely and re-reads the tool, which is why a typed coordinate already
    shows the clamped value rather than the one that was typed.

    The flag is a different question and is answered by the caller reading the
    object back: ``pending_object().following`` is what the pane renders, so an
    object that went on following the pointer says so on screen rather than
    being asserted here.  ``tests/test_pending_move_reporting.py`` pins both
    halves, so a later read-back cannot be added without a red test explaining
    what it costs.
    """
    active = _resolve(target)
    tool = _paste_tool(active)
    if tool is None:
        return False
    if drop:
        tool._moving = False
    try:
        tool.location = tuple(int(round(float(value))) for value in location)
    except Exception:
        log.exception("Could not set the pending object's position")
        return False
    return True


def nudge_pending(
    axis: int, delta: int, target: Any = None
) -> Optional[Tuple[int, int, int]]:
    """Move the pending object by whole blocks on one axis.

    Returns its new position, or ``None`` when there is nothing to move.
    """
    current = pending_object(target)
    if current is None:
        return None
    location = list(current.location)
    if not 0 <= int(axis) < 3:
        return None
    location[int(axis)] += int(delta)
    if not set_pending_location(location, target):
        return None
    moved = pending_object(target)
    return None if moved is None else moved.location


def set_pending_rotation(rotation: Sequence[float], target: Any = None) -> bool:
    """Set the pending object's rotation, in degrees per axis."""
    active = _resolve(target)
    tool = _paste_tool(active)
    widget = _tuple_input(tool, "_rotation") if tool is not None else None
    if widget is None:
        return False
    try:
        widget.value = tuple(float(value) for value in rotation)
    except Exception:
        log.exception("Could not set the pending object's rotation")
        return False
    _push_transform(tool, active)
    return True


def set_pending_scale(scale: Sequence[float], target: Any = None) -> bool:
    """Set the pending object's scale, as a multiplier per axis."""
    active = _resolve(target)
    tool = _paste_tool(active)
    widget = _tuple_input(tool, "_scale") if tool is not None else None
    if widget is None:
        return False
    try:
        widget.value = tuple(float(value) for value in scale)
    except Exception:
        log.exception("Could not set the pending object's scale")
        return False
    _push_transform(tool, active)
    return True


def _undo_depth(active: Any) -> Optional[int]:
    """Return how many undo points the open world has, or ``None``.

    ``None`` means the question could not be asked at all -- no world, or a
    build whose level keeps no history -- which is different from an answer of
    zero and has to stay different, because one is "nothing was written" and
    the other is "nobody knows".
    """
    history = getattr(getattr(active, "world", None), "history_manager", None)
    if history is None:
        return None
    try:
        return int(history.undo_count)
    except Exception:  # noqa: BLE001 - a history mid-write
        log.debug("Could not read the world's undo depth", exc_info=True)
        return None


def confirm_pending(target: Any = None, parent: Any = None) -> Outcome:
    """Write the pending object into the world through the paste tool.

    The tool's own confirm is what runs, so the blocks written are the ones the
    renderer has been drawing, with the editor's progress reporting and its
    undo point.

    **Why the undo depth is read.**  ``confirm_paste`` used to return nothing,
    and the canvas's ``run_operation`` contains an operation's exceptions unless
    it is asked not to -- so a paste that raised and a paste that wrote the world
    were the same ``None`` to the caller.  Both now report an outcome and it is
    believed when it arrives, but the depth check stays: it is the only evidence
    available from a build whose paste tool predates that, and it is what
    ``test_editor_confirm_outcome`` exercises.  Reporting success from "the call
    returned" would
    therefore say the blocks landed whenever the confirm was merely *attempted*,
    which is the one thing a caller cannot check for itself without reading the
    world back.  ``run_operation`` creates its undo point only on the path where
    nothing was raised, so a depth that did not move is proof the write did not
    happen.

    When the depth cannot be read at all this reports the confirm as run and
    says so in the log, rather than inventing a failure: an unanswerable
    question is not a negative answer.

    **Why it says so out loud.**  Returning ``False`` was necessary and was not
    sufficient.  The swallowed exception is invisible by construction: the user
    pressed Confirm, the progress dialog came and went, and every surface then
    looked exactly as it does after a paste that worked.  So each refusal is
    reported through the non-blocking notifier before it is returned, naming the
    operation, what did not happen and what to do about it -- the same contract
    :func:`activate` already keeps for its own refusals.  ``parent`` is the
    window the notification is anchored to; ``None`` still records it.
    """
    active = _resolve(target)
    tool = _paste_tool(active)
    if tool is None:
        return _refused(
            parent,
            "nothing-pending",
            ("Nothing to place", "冇嘢可以擺"),
            (
                "Confirm placement had nothing to write: the paste tool is not "
                "holding an object. Copy or cut a selection, or import a "
                "structure, and it will be held here ready to place.",
                "「確認擺位」冇嘢好寫，因為貼上工具而家冇揸住嘢。複製或者剪一個選取"
                "範圍，又或者匯入一個結構，佢就會喺呢度等你擺。",
            ),
            severity="info",
        )
    confirm = getattr(tool, "confirm_paste", None)
    if not callable(confirm):
        log.error("This build's paste tool exposes no confirm")
        return _refused(
            parent,
            "no-confirm",
            ("Confirm placement is unavailable", "確認擺位用唔到"),
            (
                "This build's paste tool exposes no confirm, so the object being "
                "held cannot be written into the world. Nothing was changed. Use "
                "Cancel to drop the object.",
                "呢個 build 嘅貼上工具冇「確認」呢個功能，所以揸住嗰嚿嘢寫唔入世界。"
                "世界乜都冇改到。撳「取消」放低佢。",
            ),
        )
    before = _undo_depth(active)
    try:
        reported = confirm()
    except Exception:  # noqa: BLE001 - a confirm that raised before run_operation
        # ``confirm_paste`` normally hands the work to ``run_operation``, which
        # swallows.  A raise arriving here therefore means it did not even get
        # that far, and letting it out of a button handler would take the whole
        # callback with it.
        log.exception("The paste tool's confirm raised before it ran the operation")
        return _refused(
            parent,
            "not-written",
            ("Confirm placement failed", "確認擺位失敗"),
            (
                "Confirm placement stopped with an error before the paste ran, so "
                "no blocks were written and the world is unchanged. The object is "
                "still being held: try Confirm placement again, or Cancel to drop "
                "it. The error is in the application log.",
                "「確認擺位」喺貼上開始之前就出錯停咗，所以一格方塊都冇寫入，個世界"
                "冇變過。嗰嚿嘢仲揸喺手：可以再撳一次「確認擺位」，或者撳「取消」放低"
                "佢。錯誤詳情喺程式嘅 log 度。",
            ),
        )
    _settle()
    # A paste tool that reports its own outcome is believed over the undo-depth
    # inference below, because it knows *why* rather than only *that*: a user who
    # cancelled the progress dialog and a paste that broke both leave the depth
    # unmoved, and the depth check has to call both of them an error.  A tool
    # that answers ``None`` -- every build before ``confirm_paste`` returned one,
    # and every stand-in -- falls through to the depth exactly as before.
    if reported is not None and not reported:
        if getattr(reported, "reason", "") == "aborted":
            # Stopped on purpose.  ``_run_operation`` says nothing about a silent
            # abort by design, and a notification here would turn the user's own
            # cancel into a red error about a paste that did what they asked.
            log.info("The paste was cancelled before it wrote anything")
            return Outcome(ok=False, reason="aborted")
        detail = str(getattr(reported, "message", "") or "")
        return _refused(
            parent,
            "not-written",
            ("Confirm placement wrote nothing", "確認擺位乜都冇寫入"),
            (
                "Confirm placement ran and the paste was stopped before any blocks "
                "were written, so the world is unchanged"
                + (f": {detail}. " if detail else ". ")
                + "The object is still being held: try Confirm placement again, or "
                "Cancel to drop it. The error is in the application log.",
                "「確認擺位」行咗，但係貼上喺寫入之前就俾人攔住咗，個世界冇變過"
                + (f"：{detail}。" if detail else "。")
                + "嗰嚿嘢仲揸喺手：可以再撳一次「確認擺位」，或者撳「取消」放低佢。"
                "錯誤詳情喺程式嘅 log 度。",
            ),
        )
    after = _undo_depth(active)
    if before is None or after is None:
        log.warning(
            "The world kept no undo history, so the paste was run without its "
            "outcome being checked"
        )
        return Outcome(ok=True)
    if after <= before:
        log.error(
            "The paste tool's confirm raised: the world's undo depth is still "
            "%d, so nothing was written",
            after,
        )
        return _refused(
            parent,
            "not-written",
            ("Confirm placement wrote nothing", "確認擺位乜都冇寫入"),
            (
                "Confirm placement ran and the world's undo history is still at "
                f"{after}, so the paste was stopped by an error and no blocks were "
                "written. The object is still being held: try Confirm placement "
                "again, or Cancel to drop it. The error is in the application log.",
                "「確認擺位」行咗，但係個世界嘅還原紀錄仲係停喺 "
                f"{after}，即係貼上俾錯誤攔住咗，一格方塊都冇寫入。嗰嚿嘢仲揸喺手："
                "可以再撳一次「確認擺位」，或者撳「取消」放低佢。錯誤詳情喺程式嘅 "
                "log 度。",
            ),
        )
    return Outcome(ok=True)


def cancel_pending(target: Any = None, parent: Any = None) -> Outcome:
    """Drop the pending object without writing anything, back to Select.

    Leaving the paste tool is what discards it: the tool clears the renderer's
    copy as it is disabled, and nothing has touched the world up to that point.

    The tool change is a posted event, so this checks afterwards that the object
    really was let go rather than reporting that the event was posted.  The two
    differ in the case that matters: a cancel that did not take leaves the object
    still held and still drawn over the world, and a caller that believed the
    post would hide the panel showing it -- so the object would still be there
    with nothing on screen admitting it.
    """
    active = _resolve(target)
    if active is None or _paste_tool(active) is None:
        # Already holding nothing, which is the state Cancel exists to reach.
        return Outcome(ok=True, reason="nothing-pending")
    if _post_tool_change(active, "Select") and _paste_tool(active) is None:
        return Outcome(ok=True)
    return _refused(
        parent,
        "still-held",
        ("Cancel did not drop the object", "取消放唔低嗰嚿嘢"),
        (
            "The editor was asked to leave the paste tool and it is still holding "
            "the object, so the object is still drawn over the world. Nothing was "
            "written either way. Try Cancel again, or switch to the Select tool in "
            "the viewport.",
            "已經叫個編輯器離開貼上工具，但係佢仲揸住嗰嚿嘢，所以個世界上面仲畫住"
            "佢。無論點都冇嘢寫入過。再撳多次「取消」，或者喺畫面度轉去「選取」工具。",
        ),
    )


# ---------------------------------------------------------------------------
# the keys that move it
# ---------------------------------------------------------------------------

#: How a stored key name reads to a person.  Anything absent is shown as the
#: editor stores it rather than being dropped, so a rebound key still names
#: itself even when this table has not heard of it.
_KEY_NAMES: Mapping[str, str] = MappingProxyType(
    {
        "MOUSE_LEFT": "left mouse button",
        "MOUSE_MIDDLE": "middle mouse button",
        "MOUSE_RIGHT": "right mouse button",
        "MOUSE_WHEEL_SCROLL_UP": "scroll up",
        "MOUSE_WHEEL_SCROLL_DOWN": "scroll down",
        "SPACE": "Space",
        "SHIFT": "Shift",
        "CTRL": "Ctrl",
        "ALT": "Alt",
        "TAB": "Tab",
        "RETURN": "Enter",
        "ESCAPE": "Esc",
    }
)

#: The editor actions that move a pending object, and what each one does.
_MOVE_ACTIONS: Tuple[Tuple[str, str], ...] = (
    ("ACT_MOVE_FORWARDS", "forwards"),
    ("ACT_MOVE_BACKWARDS", "backwards"),
    ("ACT_MOVE_LEFT", "left"),
    ("ACT_MOVE_RIGHT", "right"),
    ("ACT_MOVE_UP", "up"),
    ("ACT_MOVE_DOWN", "down"),
)


def _key_name(binding: Any) -> str:
    """Return one stored keybind as a person reads it."""
    try:
        modifiers, key = binding
    except Exception:  # noqa: BLE001 - a binding this build does not store
        return ""
    parts = [_KEY_NAMES.get(str(item), str(item)) for item in tuple(modifiers)]
    parts.append(_KEY_NAMES.get(str(key), str(key)))
    return "+".join(part for part in parts if part)


def movement_keys(target: Any = None) -> Tuple[Tuple[str, str], ...]:
    """Return the configured movement keys as ``(direction, key)`` pairs.

    They are read from the editor's live keybind group rather than from the
    shipped default, so a user who rebound them is told what they actually
    bound.  An empty result means the canvas could not be asked.
    """
    active = _resolve(target)
    if active is None:
        return ()
    try:
        binds = dict(active.key_binds)
    except Exception:  # noqa: BLE001 - a canvas without its configuration
        return ()
    pairs = []
    for action, direction in _MOVE_ACTIONS:
        name = _key_name(binds.get(action))
        if name:
            pairs.append((direction, name))
    return tuple(pairs)


def movement_sentence(target: Any = None) -> str:
    """Say, in one line, how the viewport moves the pending object.

    The editor's own gesture is a held button plus a direction key, which is
    not guessable, so it is spelled out with the keys this profile has bound.
    """
    pairs = movement_keys(target)
    if not pairs:
        return ""
    active = _resolve(target)
    click = ""
    try:
        click = _key_name(dict(active.key_binds).get("ACT_BOX_CLICK"))
    except Exception:  # noqa: BLE001 - a canvas without its configuration
        click = ""
    listed = ", ".join(f"{key} {direction}" for direction, key in pairs)
    if click:
        return (
            f"In the viewport, hold the {click} on the editor's Move selection "
            f"button and press {listed}."
        )
    return f"In the viewport, press {listed} while the Move selection button is held."


# ---------------------------------------------------------------------------
# activating a tool
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Activation:
    """What one activation actually did.

    It is returned rather than assumed so a caller can show the outcome; every
    unsuccessful activation carries the reason in ``message`` and has already
    been reported where the user can see it.
    """

    key: str
    label: str
    ok: bool
    tool: str = ""
    kind: str = ""
    message: str = ""
    detail: str = ""
    missing: str = ""
    pending: bool = False
    notes: Tuple[str, ...] = field(default_factory=tuple)


def _failed(entry: ToolBridge, message: str, **extra: Any) -> Activation:
    return Activation(
        key=entry.key,
        label=entry.label,
        ok=False,
        tool=entry.tool,
        kind=entry.kind,
        message=message,
        missing=entry.missing,
        **extra,
    )


def activate(key: str, parent: Any = None, target: Any = None) -> Activation:
    """Activate the editor tool one Studio surface key stands for.

    Nothing is opened: the tool starts in the canvas with its handles in the
    viewport and the world still visible.  The properties pane is asked to show
    the tool's own options when one is hosting them, so the options live beside
    the world rather than over it.
    """
    entry = bridge(key)
    if entry is None:
        log.error("No editor tool is registered for the surface key %r", key)
        return Activation(
            key=str(key or ""),
            label=str(key or ""),
            ok=False,
            message=f"No editor tool is registered under the key {key!r}.",
        )

    if not entry.available:
        _report(
            parent,
            f"{entry.label} is not implemented",
            entry.missing,
            severity="warning",
        )
        result = _failed(entry, entry.missing)
        _show_in_host(result)
        return result

    active = _resolve(target)
    if active is None:
        message = (
            f"No world is open in the 3D editor, so the {entry.label} tool has "
            "nothing to act on."
        )
        _report(parent, f"{entry.label} did not start", message)
        result = _failed(entry, message)
        _show_in_host(result)
        return result

    if tool_named(entry.tool, active) is None:
        message = (
            f"This world's editor has no {entry.tool} tool, so {entry.label} "
            "cannot start."
        )
        _report(parent, f"{entry.label} did not start", message)
        result = _failed(entry, message)
        _show_in_host(result)
        return result

    if entry.lift:
        result = _lift_selection(entry, active, parent)
    elif entry.kind == "pending":
        result = _show_pending(entry, active, parent)
    else:
        result = _switch(entry, active, parent)
    _show_in_host(result)
    return result


def _switch(entry: ToolBridge, active: Any, parent: Any) -> Activation:
    """Start a tool that edits in place, and report what the canvas did."""
    state = {"operation": entry.operation} if entry.operation else None
    if not _post_tool_change(active, entry.tool, state):
        message = f"The editor refused to switch to the {entry.tool} tool."
        _report(parent, f"{entry.label} did not start", message, severity="error")
        return _failed(entry, message)
    running = active_tool_name(active)
    if running != entry.tool:
        message = (
            f"The editor was asked for the {entry.tool} tool and is reporting "
            f"{running or 'no tool'} instead."
        )
        _report(parent, f"{entry.label} did not start", message, severity="error")
        return _failed(entry, message, detail=running)
    detail = f"The editor is now in its {running} tool."
    if entry.operation:
        # Asked back rather than assumed.  A tool that started and then selected
        # something else is the exact failure these keys exist to end, and it is
        # invisible from the fact that the tool started.
        chosen = active_operation_name(active)
        if _same_operation(chosen, entry.operation):
            detail = (
                f"The editor is now in its {running} tool with "
                f"{chosen or entry.operation} selected."
            )
        else:
            message = (
                f"The editor was asked for the {entry.operation} operation and "
                f"is showing {chosen or 'no operation'} instead."
            )
            _report(
                parent,
                f"{entry.label} did not start",
                message,
                severity="error",
            )
            return _failed(entry, message, detail=chosen)
    return Activation(
        key=entry.key,
        label=entry.label,
        ok=True,
        tool=entry.tool,
        kind=entry.kind,
        message=entry.summary,
        detail=detail,
        missing=entry.missing,
    )


def _show_pending(entry: ToolBridge, active: Any, parent: Any) -> Activation:
    """Show whatever the paste tool is already holding, or say it holds nothing."""
    if _paste_tool(active) is not None:
        return Activation(
            key=entry.key,
            label=entry.label,
            ok=True,
            tool=entry.tool,
            kind=entry.kind,
            message=entry.summary,
            detail="The paste tool is holding an object.",
            pending=True,
        )
    try:
        from amulet.api.structure import structure_cache
    except Exception:  # pragma: no cover - a build without the structure cache
        structure_cache = None
    if not structure_cache:
        message = (
            "Nothing is waiting to be placed. Copy or cut a selection, or "
            "import a structure, and it will appear here."
        )
        _report(parent, "No pending object", message, severity="info")
        return _failed(entry, message)
    # The same trap as lifting a selection: asking for the paste tool while it
    # is the active one is how its own button confirms, so it is left first
    # even though it is holding nothing.
    if active_tool_name(active) == "Paste":
        _post_tool_change(active, "Select")
    try:
        active.paste_from_cache()
    except Exception:
        log.exception("Could not hand the copied structure to the paste tool")
        message = "The copied structure could not be handed to the paste tool."
        _report(parent, f"{entry.label} did not start", message, severity="error")
        return _failed(entry, message)
    _settle()
    return _confirm_pending_started(entry, active, parent)


def _lift_selection(entry: ToolBridge, active: Any, parent: Any) -> Activation:
    """Copy or cut the selection and hand it to the paste tool.

    The paste tool is left first when it is already running, because asking the
    editor for the paste tool while it is the active one is how its own button
    confirms a paste -- so lifting a second selection without leaving would
    write the first one into the world instead.
    """
    selection = selection_state(active)
    if selection.empty:
        message = (
            f"Nothing is selected, so there is nothing to {entry.label.lower()}. "
            "Select a region in the viewport first."
            if selection.readable
            else "The editor's selection could not be read, so nothing was lifted."
        )
        _report(parent, f"{entry.label} needs a selection", message)
        return _failed(entry, message)

    if active_tool_name(active) == "Paste":
        _post_tool_change(active, "Select")

    lift = getattr(active, "copy" if entry.lift == "copy" else "cut", None)
    if not callable(lift):
        message = f"This build's editor cannot {entry.lift} a selection."
        _report(parent, f"{entry.label} did not start", message, severity="error")
        return _failed(entry, message)
    try:
        lifted = lift()
    except Exception:
        log.exception("Could not %s the selection for %r", entry.lift, entry.key)
        message = (
            f"The selection could not be {entry.lift}. The details are in the log."
        )
        _report(parent, f"{entry.label} did not start", message, severity="error")
        return _failed(entry, message)
    # The canvas contains the operation's own exceptions, so the ``except``
    # above only ever catches a failure to *call* the copy -- never a copy that
    # failed while it ran, which is every real one.  Without this the structure
    # cache still holds whatever was copied last, so the paste tool would take
    # the *previous* copy and the pane would report the wrong blocks as lifted.
    # A canvas that answers ``None`` is one that cannot say, and is not treated
    # as a refusal.
    if lifted is not None and not lifted:
        detail = str(getattr(lifted, "message", "") or "")
        # ``entry.lift`` is the verb -- "copy" or "cut" -- and this sentence
        # needs the past participle, or it reads "the selection was not copy".
        done = "copied" if entry.lift == "copy" else "cut"
        message = (
            f"The selection was not {done}, so nothing was handed to the "
            "paste tool" + (f": {detail}" if detail else ".")
        )
        _report(
            parent,
            f"{entry.label} did not start",
            message,
            severity="error" if getattr(lifted, "failed", False) else "warning",
        )
        return _failed(entry, message)
    try:
        active.paste_from_cache()
    except Exception:
        log.exception("Could not hand the lifted selection to the paste tool")
        message = "The lifted selection could not be handed to the paste tool."
        _report(parent, f"{entry.label} did not start", message, severity="error")
        return _failed(entry, message)
    _settle()
    result = _confirm_pending_started(entry, active, parent)
    if result.ok and entry.lift == "cut":
        return Activation(
            key=result.key,
            label=result.label,
            ok=True,
            tool=result.tool,
            kind=result.kind,
            message=result.message,
            detail=result.detail,
            missing=result.missing,
            pending=result.pending,
            notes=result.notes
            + (
                "The source blocks have already been removed and an undo point "
                "was recorded. Cancelling leaves them removed; Undo puts them "
                "back.",
            ),
        )
    return result


def _confirm_pending_started(entry: ToolBridge, active: Any, parent: Any) -> Activation:
    """Check the paste tool really took the object, rather than assuming it."""
    current = pending_object(active)
    if current is None:
        message = (
            "The editor did not start its paste tool, so there is no pending "
            "object to place."
        )
        _report(parent, f"{entry.label} did not start", message, severity="error")
        return _failed(entry, message, detail=active_tool_name(active))
    detail = (
        "The copy is following the pointer."
        if current.following
        else f"The copy is at {', '.join(str(value) for value in current.location)}."
    )
    return Activation(
        key=entry.key,
        label=entry.label,
        ok=True,
        tool=entry.tool,
        kind=entry.kind,
        message=entry.summary,
        detail=detail,
        missing=entry.missing,
        pending=True,
    )


# ---------------------------------------------------------------------------
# where the options are shown
# ---------------------------------------------------------------------------

#: The properties pane currently hosting tool options, if one is.  It is a
#: plain reference cleared by the pane as it is destroyed, so nothing here
#: keeps a dead window alive.
_host: Any = None


def set_host(pane: Any) -> None:
    """Register the pane that shows a tool's options, or clear it with ``None``."""
    global _host
    _host = pane


def host() -> Any:
    """Return the pane currently showing tool options, or ``None``."""
    return _host


def _show_in_host(result: Activation) -> None:
    """Ask the hosting pane to show this activation's options."""
    pane = _host
    if pane is None:
        return
    show = getattr(pane, "show_tool_activation", None)
    if not callable(show):
        return
    try:
        show(result)
    except Exception:
        log.exception("Could not show the %r tool options in the pane", result.key)


# ---------------------------------------------------------------------------
# routing the surface keys
# ---------------------------------------------------------------------------


def surface_routes() -> Dict[str, Callable[[Any], Any]]:
    """Return ``{surface key: opener}`` for every tool this module bridges.

    Each opener activates the tool and returns the :class:`Activation`, which is
    never ``None`` -- the surface index treats ``None`` as nothing having
    opened, and a refusal that has already been reported is not that.
    """

    def opener(key: str) -> Callable[[Any], Any]:
        return lambda parent: activate(key, parent)

    return {key: opener(key) for key in BRIDGES}


def install_surface_routes() -> Tuple[str, ...]:
    """Point the tool surface keys at the canvas instead of an options window.

    The surface index holds its routes in one private mapping with no
    registration call, so the mapping is replaced here with one carrying these
    keys as well.  An existing route always wins: this only claims keys that
    would otherwise open a described window for a tool that already exists.

    Returns the keys it installed, which is empty on a second call and empty
    again if that mapping is ever renamed -- and it says so in the log rather
    than reporting a route it did not make.
    """
    try:
        from types import MappingProxyType as _Proxy

        from amulet_map_editor.api.studio import surfaces
    except Exception:  # pragma: no cover - a build without the surface index
        log.debug("The Studio surface index is unavailable", exc_info=True)
        return ()
    existing = getattr(surfaces, "_ROUTES", None)
    if not isinstance(existing, Mapping):
        log.warning(
            "The Studio surface index no longer keeps its routes in _ROUTES, so "
            "the editor tools were not routed to the canvas"
        )
        return ()
    installed: List[str] = []
    merged = dict(existing)
    for key, opener in surface_routes().items():
        if key in merged:
            continue
        merged[key] = opener
        installed.append(key)
    if not installed:
        return ()
    try:
        surfaces._ROUTES = _Proxy(merged)
    except Exception:  # pragma: no cover - a module that refuses the write
        log.exception("Could not route the editor tools through the surface index")
        return ()
    log.info("Routed %s to the editor's own tools", ", ".join(sorted(installed)))
    return tuple(installed)
