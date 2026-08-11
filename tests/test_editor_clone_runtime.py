"""Cloning writes blocks into the world, and the controls that place them are reachable.

Every other test of the editor bridge in this repository asserts against source
text: that a table names a tool, that a docstring says what a button does.  None
of that can tell whether a clone puts a single block anywhere, because none of it
runs the editor.  This module does.

It opens a real Minecraft world in a real frame, writes a slab of gold into it
through amulet-core, selects exactly that slab, drives the Studio's own Clone
surface, moves the pending object with the Studio's own numeric position, and
confirms.  Then it reads the world back and looks for the gold.

**Why the marker block.**  An earlier probe of this same path asserted against a
box that held stone before the clone and stone after, and a clone that pastes
stone and a clone that pastes nothing are indistinguishable that way -- the probe
reported a failure that was its own measurement error.  A block that appears
nowhere else in the prepared world cannot be confused for one that was already
there, so "the gold moved" is a fact about the paste rather than about the
fixture.

**Why the panels are checked too.**  The editor builds its controls as siblings
of its canvas.  The Studio borrows the canvas into its viewport, and until this
was fixed it borrowed only the canvas: every editing control stayed behind on a
hidden notebook page, reporting ``IsShown() == True`` from inside a hidden
parent.  That is the shape of the defect that makes an operation unreachable
while looking, to any check that asks a panel about itself, entirely fine -- so
the assertion here walks the whole ancestor chain instead of asking the panel.
"""

from __future__ import annotations

import pathlib
import shutil
import time
import zipfile
from typing import Any, Dict, Iterator, List, Tuple

import pytest

wx = pytest.importorskip("wx", reason="wxPython is not installed in this environment")
amulet = pytest.importorskip("amulet", reason="amulet-core is not installed")
numpy = pytest.importorskip("numpy", reason="numpy is not installed")

from amulet.api.block import Block  # noqa: E402
from amulet.api.chunk import Chunk  # noqa: E402

from amulet_map_editor.api.studio import context, editor_tools, navigator  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORLD_ARCHIVE = ROOT / "resource" / "worlds" / "java_1_12_2.zip"
WORLD_NAME = "java_1_12_2"

#: Off-screen, so a run on a visible desktop never throws a window at anybody.
OFFSCREEN = (-32000, -32000)

#: The 3D editor loads a resource pack and builds a texture atlas on a worker
#: thread before it has a canvas, so it is genuinely absent for a while.
CANVAS_WAIT_SECONDS = 120.0

DIMENSION = "minecraft:overworld"
PREPARED_CHUNKS: Tuple[Tuple[int, int], ...] = ((0, 0), (0, 1), (1, 0), (1, 1))

#: The block that proves a paste happened.  It exists nowhere else in the
#: prepared world, so finding one anywhere new is unambiguous.
MARKER = "universal_minecraft:gold_block"

#: The slab of marker blocks, as ``(minimum, size)`` in blocks.  One block tall
#: so the paste's own centring is exact rather than rounded: a structure of
#: height ``h`` centred on ``y`` has its floor at ``y - h // 2``, which for a
#: single layer is ``y`` itself.
SOURCE_MIN = (0, 4, 0)
SOURCE_SIZE = (4, 1, 4)

#: Where the copy is sent.  Far above the terrain, and inside chunk ``(0, 0)``
#: once the paste's centring is accounted for, so one chunk read finds all of it.
DESTINATION = (8, 40, 8)


def _expected_paste_box() -> Tuple[Tuple[int, int, int], Tuple[int, int, int]]:
    """Return the block box the confirmed paste should fill.

    ``location`` is the *centre* of the pasted structure rather than its
    corner.  That is the editor's own behaviour and it is not written down
    anywhere a user can see, which is exactly why it is spelled out here: a
    test that quietly assumed a corner would fail against correct code and send
    the next reader hunting for a bug in the paste.
    """
    minimum = tuple(
        centre - extent // 2 for centre, extent in zip(DESTINATION, SOURCE_SIZE)
    )
    maximum = tuple(start + extent - 1 for start, extent in zip(minimum, SOURCE_SIZE))
    return minimum, maximum  # type: ignore[return-value]


# ----------------------------------------------------------------------
# preparing a world with something worth cloning
# ----------------------------------------------------------------------


def _extract_world(destination: pathlib.Path) -> pathlib.Path:
    if not WORLD_ARCHIVE.is_file():
        pytest.skip(f"the test world archive is missing: {WORLD_ARCHIVE}")
    with zipfile.ZipFile(WORLD_ARCHIVE) as archive:
        archive.extractall(destination)
    source = destination
    for _ in range(4):
        if (source / "level.dat").is_file():
            return source
        children = [child for child in source.iterdir() if child.is_dir()]
        if not children:
            break
        source = children[0]
    pytest.skip(f"no level.dat inside {WORLD_ARCHIVE}")


def _prepare_world(workspace: pathlib.Path) -> str:
    """Copy the world out and fill it with air, a stone floor, and the marker.

    Air is added to the palette first on purpose.  A fresh chunk's block array
    is all zeros, so whichever block is added first becomes every block in the
    chunk; adding stone first silently produces a solid chunk, which is how the
    first probe of this path ended up unable to tell a paste from a no-op.
    """
    source = _extract_world(workspace / "archive")
    path = str(workspace / WORLD_NAME)
    shutil.copytree(source, path, ignore=shutil.ignore_patterns("session.lock"))

    level = amulet.load_level(path)
    try:
        for cx, cz in PREPARED_CHUNKS:
            chunk = Chunk(cx, cz)
            air = chunk.block_palette.get_add_block(Block("universal_minecraft", "air"))
            stone = chunk.block_palette.get_add_block(
                Block("universal_minecraft", "stone")
            )
            gold = chunk.block_palette.get_add_block(
                Block("universal_minecraft", "gold_block")
            )
            chunk.blocks[:, :, :] = air
            chunk.blocks[:, 0:4, :] = stone
            if (cx, cz) == (0, 0):
                x0, y0, z0 = SOURCE_MIN
                dx, dy, dz = SOURCE_SIZE
                chunk.blocks[x0 : x0 + dx, y0 : y0 + dy, z0 : z0 + dz] = gold
            chunk.changed = True
            level.put_chunk(chunk, DIMENSION)
        level.save()
    finally:
        level.close()
    return path


def _marker_points(level: Any) -> List[Tuple[int, int, int]]:
    """Return every marker block in chunk ``(0, 0)``, as chunk-local coordinates."""
    chunk = level.get_chunk(0, 0, DIMENSION)
    array = numpy.asarray(chunk.blocks[:, :, :])
    ids = [
        index
        for index in numpy.unique(array).tolist()
        if str(chunk.block_palette[index].namespaced_name) == MARKER
    ]
    if not ids:
        return []
    return [
        (int(x), int(y), int(z))
        for x, y, z in numpy.argwhere(numpy.isin(array, ids)).tolist()
    ]


def _points_in(
    points: List[Tuple[int, int, int]],
    minimum: Tuple[int, int, int],
    maximum: Tuple[int, int, int],
) -> List[Tuple[int, int, int]]:
    return [
        point
        for point in points
        if all(
            low <= value <= high for value, low, high in zip(point, minimum, maximum)
        )
    ]


# ----------------------------------------------------------------------
# driving the real editor
# ----------------------------------------------------------------------


def _pump(seconds: float) -> None:
    end = time.time() + seconds
    while time.time() < end:
        wx.Yield()
        time.sleep(0.01)


def _wait_for(predicate, seconds: float) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        try:
            if predicate():
                return True
        except Exception:  # noqa: BLE001 - a half-built frame answers this
            pass
        wx.Yield()
        time.sleep(0.05)
    try:
        return bool(predicate())
    except Exception:  # noqa: BLE001
        return False


def _shown_to_the_user(window: Any) -> bool:
    """Whether ``window`` and every ancestor above it are shown.

    ``IsShown`` answers for one window alone, so a panel on a hidden page
    answers ``True`` while being completely invisible.  That single fact is the
    defect this module exists to catch, so the whole chain is walked.
    """
    node = window
    while node is not None:
        try:
            if not node.IsShown():
                return False
            node = node.GetParent()
        except Exception:  # noqa: BLE001 - a window being destroyed
            return False
    return True


class Session:
    """One opened world, and what the editor did to it."""

    def __init__(self) -> None:
        self.path: str = ""
        self.canvas: Any = None
        self.frame: Any = None
        self.selection: Any = None
        self.activation: Any = None
        self.pending_before: Any = None
        self.pending_after: Any = None
        #: The bridge's ``Outcome``, which reads as a boolean and also carries
        #: the reason a refusal gives, so a red assertion below says why.
        self.confirmed: Any = None
        #: The world's undo depth either side of that confirm, read through the
        #: bridge's own reader against the canvas the bridge itself resolves.
        #: This is the only wiring proof in the repository: see
        #: :func:`test_the_bridge_can_really_read_this_world_s_undo_depth`.
        self.undo_before: Any = None
        self.undo_after: Any = None
        self.marker_before: List[Tuple[int, int, int]] = []
        self.marker_after: List[Tuple[int, int, int]] = []
        self.overlays: List[Dict[str, Any]] = []
        self.notes: List[str] = []
        # the arrow-key nudge, driven through the pane's real key binding
        self.key_focus: str = ""
        self.before_key: Any = None
        self.after_key: Any = None
        self.before_key_in_box: Any = None
        self.after_key_in_box: Any = None
        self.nudge_sentence_shown: bool = False
        # where the sentence actually is, rather than merely that it exists
        self.nudge_note_rect: Tuple[int, int, int, int] = (0, 0, 0, 0)
        self.pane_visible_rect: Tuple[int, int, int, int] = (0, 0, 0, 0)
        self.pane_column: List[Tuple[int, int, str]] = []
        # the Operations route, driven separately from the pending one
        self.operation_activation: Any = None
        self.operation_controls: List[Dict[str, Any]] = []
        # the anchored paste: a corner typed into the real pane, confirmed, and
        # then looked for in the world at exactly the corner that was typed
        self.anchor_options: List[str] = []
        self.anchor_chosen: str = ""
        self.anchored_shown: List[str] = []
        self.anchored_tool_location: Any = None
        self.anchored_rows: Dict[str, str] = {}
        self.anchored_confirmed: Any = None
        self.marker_anchored: List[Tuple[int, int, int]] = []


@pytest.fixture(scope="module")
def app() -> Iterator[Any]:
    existing = wx.App.Get()
    created = None
    if existing is None:
        try:
            created = wx.App(False)
        except Exception as error:  # pragma: no cover - depends on the host
            pytest.skip(f"wx.App could not start on this host: {error!r}")
    yield existing or created
    if created is not None:
        created.Destroy()


@pytest.fixture(scope="module")
def session(app, tmp_path_factory) -> Iterator[Session]:
    """Clone a slab in a real world and record every step of it."""
    record = Session()
    workspace = tmp_path_factory.mktemp("clone-runtime")
    record.path = _prepare_world(workspace)

    level = amulet.load_level(record.path)
    try:
        record.marker_before = _marker_points(level)
    finally:
        level.close()

    from amulet_map_editor.api.framework.amulet_ui import AmuletUI

    frame = AmuletUI(None)
    record.frame = frame
    try:
        frame.SetSize(wx.Size(1500, 950))
        frame.SetPosition(wx.Point(*OFFSCREEN))
        frame.Show()
        _pump(0.3)
        frame.open_level(record.path)
        if not _wait_for(lambda: context.current().open, 60.0):
            pytest.skip("the world did not open in this environment")
        if not _wait_for(
            lambda: frame.hosted_canvas() is not None, CANVAS_WAIT_SECONDS
        ):
            # The viewport takes the canvas on the next project sync, which a
            # frame that never got a user event may not have run yet.
            frame.sync_studio_project()
            _pump(1.0)
        record.canvas = frame.hosted_canvas() or editor_tools.canvas()
        if record.canvas is None:
            pytest.skip("the 3D editor produced no canvas on this host")
        _pump(0.5)

        record.overlays = _describe_overlays(frame, record.canvas)

        navigator.push_selection(
            [navigator.SelectionBox("Clone source", SOURCE_MIN, SOURCE_SIZE)]
        )
        _pump(0.5)
        record.selection = editor_tools.selection_state()

        record.activation = editor_tools.activate("cloneTool", frame)
        _pump(0.5)
        record.pending_before = editor_tools.pending_object()

        _drive_arrow_key(record)

        editor_tools.set_pending_location(DESTINATION)
        _pump(0.3)
        record.pending_after = editor_tools.pending_object()

        # Read through the bridge's own reader, against the canvas the bridge
        # itself resolves, so what is recorded is the exact attribute path
        # ``confirm_pending`` walks rather than one this fixture chose.
        record.undo_before = editor_tools._undo_depth(editor_tools.canvas())
        record.confirmed = editor_tools.confirm_pending()
        _pump(1.5)
        record.undo_after = editor_tools._undo_depth(editor_tools.canvas())


        level = context.current().level
        if level is not None:
            record.marker_after = _marker_points(level)

        # The same tool is still holding the copy, which is what makes a second
        # placement the supported repeat rather than a second clone.
        _drive_anchored_paste(record)
        level = context.current().level
        if level is not None:
            record.marker_anchored = _marker_points(level)

        # Last, because it leaves the paste tool: everything above is recorded
        # before the Operation tool takes over.  This is the route the panel
        # move was made for -- Operations > Clone and its four siblings -- and
        # until it is driven here, a regression that stranded only the
        # Operation tool's own panels would leave every assertion above green.
        record.operation_activation = editor_tools.activate("operationOptions", frame)
        _pump(1.0)
        record.operation_controls = _describe_operation_controls(record.canvas)
    finally:
        try:
            frame.Destroy()
        except Exception:  # noqa: BLE001 - a frame already gone is fine
            pass
        _pump(0.3)
        context.clear()
    yield record


#: Where the pending object is put before the arrow key is pressed.  Well away
#: from the paste destination, so the nudge and the confirmed clone cannot be
#: mistaken for one another.
NUDGE_START = (20, 30, 20)

#: The corner typed into the pane with the lowest-corner anchor chosen.  Inside
#: chunk ``(0, 0)`` so one chunk read finds it, and clear of both the source
#: slab and the first paste so the three cannot be confused for one another.
ANCHORED_CORNER = (11, 50, 11)

#: What the tool's own position has to become for that corner to land there:
#: the centre of a 4 by 1 by 4 copy whose minimum is ``ANCHORED_CORNER``.
ANCHORED_CENTRE = (13, 50, 13)


def _anchor_picker(pane: Any) -> Any:
    """Return the pane's anchor combo, or ``None``."""
    from amulet_map_editor.api.studio import properties_pane as pane_module
    from amulet_map_editor.api.studio.widgets import SearchableChoice

    stack = [pane]
    while stack:
        node = stack.pop()
        if isinstance(node, SearchableChoice) and str(node.label).startswith(
            pane_module.ANCHOR_FIELD_LABEL
        ):
            return node
        try:
            stack.extend(node.GetChildren())
        except Exception:  # noqa: BLE001 - a control mid-teardown
            continue
    return None


def _drive_anchored_paste(record: "Session") -> None:
    """Type a corner into the real pane and confirm, recording every step.

    This is the route the whole anchor feature exists for, driven end to end
    with nothing stubbed: the pane's own combo, the pane's own coordinate boxes,
    the real paste tool underneath them, and afterwards the blocks in the world.

    ``tests/test_paste_anchor_ui_contract.py`` drives the same controls against
    a stand-in tool, which proves the screen and nothing about the wiring.  A
    conversion that reached a fake and never reached the editor passes there and
    fails here, which is the only reason this slower module is worth its two
    minutes.
    """
    from amulet_map_editor.api.studio import properties_pane as pane_module

    pane = editor_tools.host()
    if pane is None:
        record.notes.append("no properties pane is hosting the tool options")
        return
    picker = _anchor_picker(pane)
    if picker is None:
        record.notes.append("the pending controls offered no anchor picker")
        return
    record.anchor_options = [str(option) for option in picker.options]

    # The anchor is a persisted setting and this is the user's real profile, so
    # whatever it was is put back before the fixture returns.
    previous = pane_module.load_paste_anchor()
    try:
        picker.set_value(
            editor_tools.anchor_label(editor_tools.ANCHOR_MINIMUM), notify=True
        )
        _pump(0.3)
        record.anchor_chosen = pane.position_anchor

        field = pane._tool_fields.get("location")
        if field is None:
            record.notes.append("the pending controls offered no position boxes")
            return
        field.set_values([str(value) for value in ANCHORED_CORNER], notify=True)
        _pump(0.4)
        record.anchored_shown = [str(value) for value in field.values()]
        held = editor_tools.pending_object()
        record.anchored_tool_location = None if held is None else tuple(held.location)
        record.anchored_rows = {
            key: pane._tool_rows[key].value
            for key, _label in pane_module.PASTE_BOX_ROWS
            if key in pane._tool_rows
        }

        record.anchored_confirmed = editor_tools.confirm_pending()
        _pump(1.5)
    finally:
        pane_module.store_paste_anchor(previous)


def _first_focusable(pane: Any) -> Any:
    """Return a control in ``pane`` that is not a value box, or ``None``.

    The nudge keys deliberately stand aside for text and spin controls, so a
    press has to be delivered from somewhere else in the pane to test the
    thing that moves rather than the thing that refuses.
    """
    from amulet_map_editor.api.studio.properties_pane import _TEXT_ENTRY_CLASSES

    stack = [pane]
    while stack:
        node = stack.pop()
        if (
            node is not pane
            and not isinstance(node, _TEXT_ENTRY_CLASSES)
            and node.AcceptsFocus()
        ):
            return node
        try:
            stack.extend(node.GetChildren())
        except Exception:  # noqa: BLE001 - a control mid-teardown
            continue
    return None


def _find_value_box(pane: Any) -> Any:
    """Return a text or spin control inside ``pane``, or ``None``."""
    stack = [pane]
    while stack:
        node = stack.pop()
        if isinstance(node, (wx.TextCtrl, wx.SpinCtrl, wx.SpinCtrlDouble)):
            return node
        try:
            stack.extend(node.GetChildren())
        except Exception:  # noqa: BLE001
            continue
    return None


def _press(pane: Any, key: int) -> None:
    """Send one real key press through the pane's own event handler.

    A synthesised ``EVT_CHAR_HOOK`` rather than a direct call to the handler,
    so what is exercised is the binding as well as the code behind it: a
    handler that was never bound would pass a direct-call test and do nothing
    for a user.
    """
    event = wx.KeyEvent(wx.wxEVT_CHAR_HOOK)
    event.SetKeyCode(key)
    event.SetEventObject(pane)
    pane.GetEventHandler().ProcessEvent(event)
    _pump(0.2)


def _drive_arrow_key(record: "Session") -> None:
    """Press the left arrow with the pane focused, and with a value box focused."""
    from amulet_map_editor.api.studio import properties_pane as pane_module

    pane = editor_tools.host()
    if pane is None:
        record.notes.append("no properties pane is hosting the tool options")
        return
    record.nudge_sentence_shown = _pane_says(pane, pane_module.NUDGE_KEY_SENTENCE)
    note = _pane_widget_saying(pane, pane_module.NUDGE_KEY_SENTENCE)
    if note is not None:
        record.nudge_note_rect = _rect(note)
        # The scroller rather than the pane.  The pane's rectangle takes in the
        # title, the tabs and the search bar above the column and the action
        # button below it, so a note measured against it could sit behind the
        # header and still be reported as visible.  The scroller's own
        # rectangle is the viewport, and a scrolled child's screen position
        # already carries the scroll offset, so containment in it is exactly
        # the question "can this be read right now".
        record.pane_visible_rect = _rect(note.GetParent())
        record.pane_column = _column_of(note.GetParent())

    editor_tools.set_pending_location(NUDGE_START)
    _pump(0.3)

    target = _first_focusable(pane)
    if target is None:
        record.notes.append("the pane offered no focusable control to press a key on")
        return
    target.SetFocus()
    _pump(0.2)
    record.key_focus = type(wx.Window.FindFocus()).__name__
    record.before_key = editor_tools.pending_object()
    _press(pane, wx.WXK_LEFT)
    record.after_key = editor_tools.pending_object()

    box = _find_value_box(pane)
    if box is not None:
        box.SetFocus()
        _pump(0.2)
        record.before_key_in_box = editor_tools.pending_object()
        _press(pane, wx.WXK_LEFT)
        record.after_key_in_box = editor_tools.pending_object()


def _pane_widget_saying(pane: Any, sentence: str) -> Any:
    """Return the widget in ``pane`` whose text is ``sentence``, or ``None``.

    Separate from :func:`_pane_says` because "a widget exists carrying this
    text" and "a person can read this text" are different claims, and only the
    widget itself can answer the second one -- it knows where it is.
    """
    needle = " ".join(str(sentence).split())
    stack = [pane]
    while stack:
        node = stack.pop()
        for getter in ("GetLabel", "GetName"):
            method = getattr(node, getter, None)
            if not callable(method):
                continue
            try:
                value = method()
            except Exception:  # noqa: BLE001
                continue
            if isinstance(value, str) and needle in " ".join(value.split()):
                return node
        try:
            stack.extend(node.GetChildren())
        except Exception:  # noqa: BLE001
            continue
    return None


def _pane_says(pane: Any, sentence: str) -> bool:
    """Whether a widget carrying ``sentence`` exists anywhere in the pane.

    Deliberately weak, and named for what it can actually prove: it walks the
    widget tree, so it answers the same ``True`` whether the sentence is on
    screen, scrolled hundreds of pixels below the fold, zero-height or clipped.
    Anything claiming the user was *told* something needs :func:`_rect` as well.
    """
    return _pane_widget_saying(pane, sentence) is not None


def _column_of(scroller: Any) -> List[Tuple[int, int, str]]:
    """Return every shown child of ``scroller`` as ``(top, bottom, name)``.

    Recorded so a failure below can say what is taking the room rather than
    only that something is: "the note is off the bottom" is a symptom, and the
    list of what sits above it is the cause.
    """
    column: List[Tuple[int, int, str]] = []
    try:
        children = list(scroller.GetChildren())
    except Exception:  # noqa: BLE001
        return column
    for child in children:
        try:
            if not child.IsShown():
                continue
            rect = child.GetScreenRect()
            name = child.GetName() or type(child).__name__
        except Exception:  # noqa: BLE001
            continue
        column.append(
            (rect.GetTop(), rect.GetBottom(), " ".join(str(name).split())[:60])
        )
    column.sort()
    return column


def _rect(window: Any) -> Tuple[int, int, int, int]:
    """Return a window's position on screen as ``(left, top, right, bottom)``.

    Screen coordinates rather than the parent's, because the note and the pane
    are several levels apart in the tree and the scroller between them carries
    an offset of its own.
    """
    try:
        rect = window.GetScreenRect()
    except Exception:  # noqa: BLE001 - a window mid-teardown
        return (0, 0, 0, 0)
    return (rect.GetLeft(), rect.GetTop(), rect.GetRight(), rect.GetBottom())


#: What has to be reachable before a single stock operation can be run: the
#: list you pick the operation from, and the button that runs it.  Matched on
#: what a user sees rather than on an attribute name, because a control renamed
#: in the source is still the same control to the person looking for it.
OPERATION_CONTROLS: Tuple[Tuple[str, str], ...] = (
    ("chooser", "the list of installed operations"),
    ("Run Operation", "the button that runs the chosen one"),
)


def _inside(inner: Any, outer: Any) -> bool:
    """Whether ``inner``'s rectangle is inside ``outer``'s, on screen."""
    try:
        a, b = inner.GetScreenRect(), outer.GetScreenRect()
    except Exception:  # noqa: BLE001
        return False
    return bool(b.Contains(a))


def _describe_operation_controls(canvas: Any) -> List[Dict[str, Any]]:
    """Record where the Operation tool's own two controls ended up.

    Walked from the tool's own windows rather than from a search of the whole
    frame, so a control found here is one the Operation tool built: a stray
    ``Run Operation`` button belonging to something else could not stand in for
    the one that is missing.
    """
    described: List[Dict[str, Any]] = []
    tool = editor_tools.tool_named("Operation", canvas)
    if tool is None:
        return described
    viewport = canvas.GetParent()
    stack: List[Any] = []
    try:
        stack.extend(tool.windows())
    except Exception:  # noqa: BLE001 - a tool without its panels yet
        return described
    while stack:
        node = stack.pop()
        try:
            label = str(node.GetLabel() or "")
            kind = "chooser" if isinstance(node, wx.Choice) else label
            if kind in dict(OPERATION_CONTROLS):
                described.append(
                    {
                        "control": kind,
                        "class": type(node).__name__,
                        "parent": type(node.GetParent()).__name__,
                        "parent_name": str(node.GetParent().GetName() or ""),
                        "shown_to_the_user": _shown_to_the_user(node),
                        "inside_the_viewport": _inside(node, viewport),
                        "rect": _rect(node),
                    }
                )
            stack.extend(node.GetChildren())
        except Exception:  # noqa: BLE001 - a control mid-teardown
            continue
    return described


def _describe_overlays(frame: Any, canvas: Any) -> List[Dict[str, Any]]:
    """Record where each of the editor's own control panels ended up."""
    from amulet_map_editor.api.framework.amulet_ui import AmuletUI

    described: List[Dict[str, Any]] = []
    for window in AmuletUI.editor_overlay_windows(canvas):
        try:
            described.append(
                {
                    "class": type(window).__name__,
                    "parent": type(window.GetParent()).__name__,
                    "parent_is_canvas_parent": window.GetParent() is canvas.GetParent(),
                    "shown": bool(window.IsShown()),
                    "shown_to_the_user": _shown_to_the_user(window),
                }
            )
        except Exception:  # noqa: BLE001 - a window mid-teardown
            continue
    return described


# ----------------------------------------------------------------------
# the clone itself
# ----------------------------------------------------------------------


def test_the_prepared_world_holds_the_marker_in_one_place(session: Session) -> None:
    """The fixture is worth cloning, and the marker is unambiguous.

    Asserted before anything else, because every result below is read as "the
    marker moved": a fixture whose marker was never written, or which held the
    marker in two places already, would make those results mean nothing.
    """
    expected = SOURCE_SIZE[0] * SOURCE_SIZE[1] * SOURCE_SIZE[2]
    assert len(session.marker_before) == expected, (
        f"the prepared world should hold exactly {expected} marker blocks before "
        f"anything is cloned, and holds {len(session.marker_before)}"
    )
    levels = {point[1] for point in session.marker_before}
    assert levels == {SOURCE_MIN[1]}, (
        "the marker should exist on exactly one y level before the clone, so "
        f"a copy landing anywhere is visible; it is on {sorted(levels)}"
    )


def test_clone_starts_and_holds_a_pending_object(session: Session) -> None:
    """The Clone surface really lifted the selection."""
    assert session.selection is not None and not session.selection.empty, (
        "the selection the clone was asked to lift is empty, so the rest of "
        f"this module would prove nothing: {session.selection}"
    )
    assert session.activation is not None and session.activation.ok, (
        "the Clone surface did not start: "
        f"{getattr(session.activation, 'message', session.activation)}"
    )
    assert session.pending_before is not None, (
        "Clone reported success and the paste tool is holding nothing, so "
        "there is no copy to place"
    )


def test_the_pending_object_moves_to_the_position_it_is_given(
    session: Session,
) -> None:
    """Typing a position moves the copy, and stops it tracking the pointer."""
    pending = session.pending_after
    assert pending is not None, "the pending object vanished before it was moved"
    assert tuple(pending.location) == tuple(DESTINATION), (
        f"the pending object was sent to {DESTINATION} and reports "
        f"{tuple(pending.location)}"
    )
    assert not pending.following, (
        "the copy is still following the pointer after a position was typed, so "
        "the next mouse move would overwrite the typed value"
    )


def test_confirming_a_clone_writes_the_blocks_into_the_world(
    session: Session,
) -> None:
    """The blocks really land, at the position the interface reported.

    This is the assertion the whole module exists for.  It compares against the
    world the application itself has open, read block by block, rather than
    against anything the interface said about itself.
    """
    assert session.confirmed, (
        "the paste tool refused to confirm the placement: "
        f"{getattr(session.confirmed, 'reason', '')} "
        f"{getattr(session.confirmed, 'message', session.confirmed)}"
    )

    minimum, maximum = _expected_paste_box()
    landed = _points_in(session.marker_after, minimum, maximum)
    expected = SOURCE_SIZE[0] * SOURCE_SIZE[1] * SOURCE_SIZE[2]
    assert len(landed) == expected, (
        f"a confirmed clone should have written {expected} marker blocks into "
        f"{minimum}..{maximum} and wrote {len(landed)}. Every marker block in "
        f"the chunk afterwards: {sorted(session.marker_after)}"
    )


def test_the_bridge_can_really_read_this_world_s_undo_depth(
    session: Session,
) -> None:
    """The wiring, asserted rather than assumed.

    ``confirm_pending`` decides whether a paste landed by reading
    ``canvas.world.history_manager.undo_count``.  Every other test of that
    decision runs against a stand-in world written to have those attributes, so
    all of them prove the arithmetic and none of them prove that a *real*
    canvas and a *real* amulet level answer to those names.

    The test above cannot stand in for this one, and it is worth saying exactly
    why, because it looks as though it should.  A broken attribute path does
    not make ``confirm_pending`` return a refusal -- it makes ``_undo_depth``
    return ``None`` at both ends, which routes into the deliberate "an
    unanswerable question is not a negative answer" branch and reports
    ``ok=True``.  The blocks still land, because the confirm still ran.  So
    ``session.confirmed`` stays truthy, the block count stays right, and the
    whole module passes while the check that is supposed to catch a silently
    failed paste has been switched off.  Verified by mutating the attribute
    name and watching this module stay green.

    Hence the depth itself: a number at both ends, and a number that moved.
    """
    assert isinstance(session.undo_before, int), (
        "the bridge could not read the undo depth of a real open world before "
        "the paste, so its check for a paste that wrote nothing is inert here "
        "and every confirm is reported as successful without being checked. "
        f"It read {session.undo_before!r}"
    )
    assert isinstance(session.undo_after, int), (
        "the bridge could not read the undo depth after the paste: "
        f"{session.undo_after!r}"
    )
    assert session.undo_after > session.undo_before, (
        "a paste that really wrote blocks into a real world left the undo "
        f"depth at {session.undo_after} from {session.undo_before}, so the "
        "evidence the refusal path is built on does not move when a write "
        "happens -- which would make every failed paste unreportable"
    )


def test_a_clone_leaves_the_blocks_it_copied_alone(session: Session) -> None:
    """Clone copies; it does not move.  The source must survive."""
    source_max = tuple(
        start + extent - 1 for start, extent in zip(SOURCE_MIN, SOURCE_SIZE)
    )
    still_there = _points_in(session.marker_after, SOURCE_MIN, source_max)
    assert len(still_there) == len(session.marker_before), (
        "cloning took blocks away from the source: "
        f"{len(session.marker_before)} before, {len(still_there)} after"
    )


# ----------------------------------------------------------------------
# typing a corner, in the real editor, and finding the blocks at that corner
# ----------------------------------------------------------------------


def test_the_running_editor_offers_the_anchor_picker(session: Session) -> None:
    """The picker exists on the pane the real tool is driving.

    Not a restatement of the contract module: that one builds the pane around a
    stand-in tool, so it proves the picker is drawn for an object the test
    itself invented.  This one proves it is drawn for the object the editor is
    actually holding, whose extent had to be read out of a real structure.
    """
    assert session.anchor_options, (
        "the running editor's pending controls offer no anchor picker, so a "
        f"typed coordinate can only ever mean the centre: {session.notes}"
    )
    assert len(session.anchor_options) == len(editor_tools.ANCHORS)
    assert session.anchor_chosen == editor_tools.ANCHOR_MINIMUM, (
        "choosing the lowest corner in the real pane left the anchor at "
        f"{session.anchor_chosen!r}"
    )


def test_typing_a_corner_moves_the_real_tool_to_the_matching_centre(
    session: Session,
) -> None:
    """The conversion reaches the paste tool, not just the pane's own boxes.

    The tool pastes the centre it holds.  A pane that showed a corner and left
    the tool where it was would look exactly right and paste the old position,
    so the number checked here is the tool's, read back out of it afterwards.
    """
    assert (
        session.anchored_tool_location is not None
    ), f"nothing was holding the copy after the corner was typed: {session.notes}"
    assert session.anchored_tool_location == ANCHORED_CENTRE, (
        f"typing the corner {ANCHORED_CORNER} should have moved the paste tool "
        f"to {ANCHORED_CENTRE}, and it is at {session.anchored_tool_location}"
    )
    assert session.anchored_shown == [str(value) for value in ANCHORED_CORNER], (
        "the pane's own boxes no longer read the corner that was typed into "
        f"them: {session.anchored_shown}"
    )


def test_the_pane_said_where_the_blocks_would_land(session: Session) -> None:
    """The readout is checked against blocks, not against its own arithmetic.

    This is the assertion the box rows exist for.  What the pane promised is
    recorded before the confirm; what the world holds is read after it; and a
    readout that is confidently wrong fails here rather than being believed.
    """
    assert (
        session.anchored_rows
    ), f"the pending controls showed no paste box at all: {session.notes}"
    landed = _points_in(session.marker_anchored, ANCHORED_CORNER, (14, 50, 14))
    assert landed, (
        "no blocks landed in the box the pane promised, so there is nothing to "
        f"check its claim against. Every marker afterwards: "
        f"{sorted(session.marker_anchored)}"
    )
    minimum = tuple(min(point[axis] for point in landed) for axis in range(3))
    maximum = tuple(max(point[axis] for point in landed) for axis in range(3))
    said = list(session.anchored_rows.values())
    assert said[0] == ", ".join(str(value) for value in minimum), (
        f"the pane said the blocks would start at {said[0]!r} and they start "
        f"at {minimum}"
    )
    assert said[1] == ", ".join(str(value) for value in maximum), (
        f"the pane said the blocks would end at {said[1]!r} and they end at "
        f"{maximum}"
    )


def test_a_clone_anchored_to_a_corner_lands_at_the_corner_that_was_typed(
    session: Session,
) -> None:
    """The whole point, in one assertion, against blocks in a real world.

    Somebody who types ``11, 50, 11`` with the lowest corner chosen must find
    the copy starting at ``11, 50, 11``.  Before this the same typing put it at
    ``9, 50, 9`` -- half a structure away, with nothing on screen saying why.
    """
    assert session.anchored_confirmed, (
        "the paste tool refused to confirm the anchored placement: "
        f"{getattr(session.anchored_confirmed, 'reason', '')} "
        f"{getattr(session.anchored_confirmed, 'message', session.anchored_confirmed)}"
    )
    expected = SOURCE_SIZE[0] * SOURCE_SIZE[1] * SOURCE_SIZE[2]
    landed = _points_in(session.marker_anchored, ANCHORED_CORNER, (14, 50, 14))
    assert len(landed) == expected, (
        f"a corner-anchored clone should have written {expected} marker blocks "
        f"into {ANCHORED_CORNER}..{(14, 50, 14)} and wrote {len(landed)}. Every "
        f"marker block in the chunk afterwards: {sorted(session.marker_anchored)}"
    )
    minimum = tuple(min(point[axis] for point in landed) for axis in range(3))
    assert minimum == ANCHORED_CORNER, (
        f"the lowest corner of the copy should be the {ANCHORED_CORNER} that "
        f"was typed, and is {minimum}"
    )
    # Nothing outside the promised box: a paste that also scattered blocks
    # elsewhere would satisfy the count above while being plainly wrong.
    strays = [
        point
        for point in session.marker_anchored
        if point not in landed and point not in session.marker_after
    ]
    assert (
        not strays
    ), f"the anchored clone wrote marker blocks outside its box: {strays}"


def test_the_anchored_clone_left_the_first_one_alone(session: Session) -> None:
    """Pasting again is a repeat, not a move: the earlier copy has to survive."""
    minimum, maximum = _expected_paste_box()
    still_there = _points_in(session.marker_anchored, minimum, maximum)
    assert len(still_there) == len(
        _points_in(session.marker_after, minimum, maximum)
    ), (
        "confirming a second placement took blocks away from the first: "
        f"{len(_points_in(session.marker_after, minimum, maximum))} before, "
        f"{len(still_there)} after"
    )


# ----------------------------------------------------------------------
# the controls that place them
# ----------------------------------------------------------------------


def test_the_editor_has_control_panels_to_move_at_all(session: Session) -> None:
    """The enumeration finds something.

    Without this, every assertion below passes on an empty list -- which is
    exactly how a guard that walks a collection stops guarding when the
    collection stops being populated.
    """
    assert len(session.overlays) >= 6, (
        "the editor should expose its file panel, its tool button row and one "
        f"options panel per tool; the enumeration found {session.overlays}"
    )


def test_every_editor_panel_follows_the_canvas_into_the_viewport(
    session: Session,
) -> None:
    """No editing control is left behind on the hidden notebook page.

    A panel stranded there still answers ``IsShown() == True``.  That is why
    the recorded fact is the whole ancestor chain: before this was fixed, every
    panel here reported ``shown`` true and ``shown_to_the_user`` false, and the
    Operations tab had no reachable way to run a single operation.
    """
    stranded = [
        entry for entry in session.overlays if not entry["parent_is_canvas_parent"]
    ]
    assert not stranded, (
        "these editor panels did not follow the canvas into the viewport, so "
        f"the controls on them cannot be reached: {stranded}"
    )


def test_an_arrow_key_moves_the_pending_object_by_the_stated_step(
    session: Session,
) -> None:
    """Pressing left really moves the copy, through the pane's own key binding.

    The press is a synthesised ``EVT_CHAR_HOOK`` put through the pane's event
    handler rather than a call to the handler function, so a handler that was
    written and never bound fails here instead of passing.
    """
    from amulet_map_editor.api.studio import properties_pane as pane_module

    assert session.before_key is not None and session.after_key is not None, (
        "the arrow key was never delivered, so nothing about it is proven: "
        f"{session.notes}"
    )
    assert session.key_focus, "no control in the pane took focus for the key press"

    axis, direction = pane_module.NUDGE_KEYS[wx.WXK_LEFT]
    expected = list(session.before_key.location)
    expected[axis] += direction * pane_module.DEFAULT_NUDGE_STEP
    assert list(session.after_key.location) == expected, (
        f"the left arrow should have moved the copy from "
        f"{session.before_key.location} to {tuple(expected)} and it is at "
        f"{session.after_key.location}"
    )


def test_an_arrow_key_inside_a_value_box_belongs_to_that_box(
    session: Session,
) -> None:
    """Typing a coordinate must not move the object at the same time.

    This is the half of the key handling that is easy to leave out and
    impossible to notice from the code: without the refusal, arrowing along a
    number being typed also drags the object, and the value the user is
    editing stops agreeing with where the object is.
    """
    if session.before_key_in_box is None:
        pytest.skip("the pane rendered no value box to test the refusal against")
    assert session.after_key_in_box is not None, "the pending object vanished"
    # Without this, the whole test passes on a key binding that does nothing at
    # all: "the object did not move" is exactly what a dead handler produces,
    # and a refusal that cannot tell itself apart from a no-op proves nothing.
    assert (
        session.after_key is not None
        and session.before_key is not None
        and session.after_key.location != session.before_key.location
    ), (
        "the arrow key does not move the object even outside a value box, so "
        "this test cannot tell a working refusal from a dead binding"
    )
    assert session.after_key_in_box.location == session.before_key_in_box.location, (
        "an arrow key pressed inside a value box moved the pending object as "
        f"well: {session.before_key_in_box.location} -> "
        f"{session.after_key_in_box.location}"
    )


def test_the_pane_holds_a_widget_saying_the_arrow_keys_exist(
    session: Session,
) -> None:
    """The sentence is built at all.

    Named for exactly what it proves.  It walks the widget tree, so it cannot
    tell a sentence on screen from one scrolled below the fold -- which is why
    the test below it exists and why this one no longer claims the user was
    told anything.
    """
    assert session.nudge_sentence_shown, (
        "the pending controls do not state that the arrow keys nudge, so the "
        "only way to find them is to press one and hope"
    )


def test_the_arrow_key_note_is_on_screen_without_scrolling(
    session: Session,
) -> None:
    """A shortcut nobody is told about is a shortcut nobody uses.

    The sentence existing in the widget tree is not being told: the pending
    pane is a scroller, and a note placed after the six nudge buttons sits
    hundreds of pixels below the bottom of the visible column, reachable only
    by a user who scrolls looking for something they do not yet know is there.
    So this asserts the note's rectangle against the pane's, in screen
    coordinates, with the pane at rest where the tool left it.
    """
    left, top, right, bottom = session.nudge_note_rect
    pane_left, pane_top, pane_right, pane_bottom = session.pane_visible_rect
    assert (right, bottom) != (0, 0) and (pane_right, pane_bottom) != (0, 0), (
        "no rectangle was measured for the arrow-key note, so this proves "
        f"nothing: note={session.nudge_note_rect} pane={session.pane_visible_rect}"
    )
    assert top >= pane_top and bottom <= pane_bottom, (
        "the arrow-key note is not on screen when the pending controls open. "
        f"The note occupies y {top}..{bottom} and the visible pane is y "
        f"{pane_top}..{pane_bottom}, so it is "
        f"{max(0, bottom - pane_bottom)}px of it is below the fold -- a user "
        "has to scroll to be told the keys exist. What is above it, as "
        f"(top, bottom, name): {session.pane_column}"
    )
    assert left >= pane_left, (
        f"the arrow-key note starts left of the visible column: it occupies x "
        f"{left}..{right} and the column is x {pane_left}..{pane_right}"
    )
    # The right edge is deliberately not asserted.  The note is added with
    # ``wx.EXPAND``, so the sizer stretches the *control* to the widest
    # honest minimum in the column -- a coordinate field, here -- while the
    # *text* inside it is wrapped to ``_note_width()``, which is the scroller's
    # client width less a margin.  A control wider than the viewport is
    # therefore normal in this pane, which enables horizontal scrolling on
    # purpose rather than cutting rows off at the edge, and asserting on it
    # fails against correct code.


def test_the_panel_of_a_running_tool_is_actually_visible(session: Session) -> None:
    """A tool that is running has its controls on screen, not merely shown."""
    visible = [
        entry
        for entry in session.overlays
        if entry["shown"] and entry["shown_to_the_user"]
    ]
    assert visible, (
        "not one of the editor's panels is visible all the way up to the "
        f"frame, so nothing can be pressed: {session.overlays}"
    )


# ----------------------------------------------------------------------
# the Operations route, which is the one the panel move was made for
# ----------------------------------------------------------------------


def test_the_operations_route_starts_the_operation_tool(session: Session) -> None:
    """``Operations > Clone`` and its siblings reach the Operation tool at all.

    The pending-paste route above was already working before the panels were
    moved.  This one was not: it started the tool, selected the operation, and
    showed the user none of it.  So the route is activated here by its own
    surface key rather than being assumed to behave like the paste one.
    """
    activation = session.operation_activation
    assert activation is not None and activation.ok, (
        "the Run operation surface did not start the Operation tool: "
        f"{getattr(activation, 'message', activation)}"
    )


def test_the_operation_chooser_and_its_run_button_are_reachable(
    session: Session,
) -> None:
    """Both controls exist, are shown to the user, and are inside the viewport.

    This is the assertion the panel move exists to hold up.  Without it a
    regression that stranded only the Operation tool's panels -- leaving the
    paste tool's own working, which is what the rest of this module drives --
    passes the whole suite green while there is again no way to run a single
    stock operation from the Studio.
    """
    found = {entry["control"]: entry for entry in session.operation_controls}
    for control, description in OPERATION_CONTROLS:
        entry = found.get(control)
        assert entry is not None, (
            f"the Operation tool built no {description}, so there is no way to "
            f"run an operation. What it did build: {session.operation_controls}"
        )
        assert entry["shown_to_the_user"], (
            f"{description} is not shown all the way up to the frame, so it "
            f"cannot be clicked: {entry}"
        )
        assert entry["inside_the_viewport"], (
            f"{description} is outside the viewport that hosts the canvas, so "
            f"it is drawn somewhere the user is not looking: {entry}"
        )
