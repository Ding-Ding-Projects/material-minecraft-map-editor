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
        self.confirmed: bool = False
        self.marker_before: List[Tuple[int, int, int]] = []
        self.marker_after: List[Tuple[int, int, int]] = []
        self.overlays: List[Dict[str, Any]] = []
        self.notes: List[str] = []


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

        editor_tools.set_pending_location(DESTINATION)
        _pump(0.3)
        record.pending_after = editor_tools.pending_object()

        record.confirmed = editor_tools.confirm_pending()
        _pump(1.5)

        level = context.current().level
        if level is not None:
            record.marker_after = _marker_points(level)
    finally:
        try:
            frame.Destroy()
        except Exception:  # noqa: BLE001 - a frame already gone is fine
            pass
        _pump(0.3)
        context.clear()
    yield record


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
    assert session.confirmed, "the paste tool refused to confirm the placement"

    minimum, maximum = _expected_paste_box()
    landed = _points_in(session.marker_after, minimum, maximum)
    expected = SOURCE_SIZE[0] * SOURCE_SIZE[1] * SOURCE_SIZE[2]
    assert len(landed) == expected, (
        f"a confirmed clone should have written {expected} marker blocks into "
        f"{minimum}..{maximum} and wrote {len(landed)}. Every marker block in "
        f"the chunk afterwards: {sorted(session.marker_after)}"
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
