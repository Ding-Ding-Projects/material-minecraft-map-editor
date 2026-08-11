"""The application reads the user's world, and nothing shows the design mock.

Every other Studio test in this suite proves something about one lane in
isolation: a binder returns the right sections, a panel constructs, a surface
paints.  None of them opens a world.  That seam -- four lanes each verified
against its own stub, joined for the first time at runtime -- is where this
project has lost the most time, so this module refuses to stub anything.

It starts the real :class:`~amulet_map_editor.api.framework.amulet_ui.AmuletUI`
frame, opens a real Minecraft world through the frame's own ``open_level``,
draws a real selection through the navigator's own ``push_selection``, and then
asks two questions of what came out.

**Is it reading the world?**  Every value asserted here is compared against the
``amulet.api.level.BaseLevel`` the application itself opened, or against a
second, independent read of the same folder taken with amulet-core before the
window existed.  Nothing is compared against a number written in this file:
a test that asserts ``seed == "1471929"`` passes just as happily on a fixture
as on a world, which is the exact failure it would be written to catch.

**Is anything still showing the mock?**  A rule that says "surfaces must show
live data" passes on a surface that shows nothing at all, so the positive
assertions above cannot detect a section that was left as the designer wrote
it.  The second half of this module is therefore an inverted assertion: a
hand-written list of strings that appear nowhere in any Minecraft world and
only in the design mock -- a world called ``1.17 Height``, the seed
``1471929``, a player ``6f1c…a904`` -- and a scan of every surface the Studio
can render for them, with the world open.  The surfaces that still carry them
are recorded exactly, so binding one and forgetting to strike it off the list
is a failure rather than a quiet inconsistency.

Running it costs about a minute: it builds one frame, opens one world, and
renders every registered surface once into a captured report that the
individual tests then read.  Capturing once rather than per test also makes the
order the tests run in irrelevant, including for the closed-world half, which
would otherwise have to be the last thing in the file and stay there.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import time
import zipfile
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Tuple

import pytest

wx = pytest.importorskip("wx", reason="wxPython is not installed in this environment")
amulet = pytest.importorskip("amulet", reason="amulet-core is not installed")
numpy = pytest.importorskip("numpy", reason="numpy is not installed")

from amulet.api.block import Block  # noqa: E402
from amulet.api.chunk import Chunk  # noqa: E402

from amulet_map_editor.api.studio import (  # noqa: E402
    context,
    live,
    navigator,
    status_bar,
    surfaces,
)
from amulet_map_editor.api.studio import specs as spec_registry  # noqa: E402
from amulet_map_editor.api.studio.spec_dialog import SpecDialog  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: The world this suite opens, and the archive it is extracted from.  The
#: extracted copy is shared with the other runtime probes in this repository,
#: so it is never edited in place: each run works on its own copy.
WORLD_ARCHIVE = ROOT / "resource" / "worlds" / "java_1_12_2.zip"
WORLD_NAME = "java_1_12_2"

#: The off-screen corner the frame is built at, so running this on a visible
#: desktop never throws a window across somebody's screen.
OFFSCREEN = (-32000, -32000)

#: How long to wait for the 3D editor to hand its canvas to the viewport.  The
#: canvas is built on a worker thread that loads a resource pack, so it is
#: genuinely absent for a few seconds rather than merely slow.
CANVAS_WAIT_SECONDS = 60.0

#: The dimension the prepared world has terrain in, and the box drawn in it.
#: The box is one chunk wide and four blocks tall so the histogram it drives
#: reads a small, exactly known volume rather than a continent.
TEST_DIMENSION = "minecraft:overworld"
SELECTION_MIN = (0, 0, 0)
SELECTION_MAX = (16, 4, 16)

#: The chunks written into the copy, and how deep each layer goes.  Terrain is
#: added because the shipped archive holds an empty ``region`` folder: a world
#: with no chunks cannot prove that the chunk inspector lists real chunks or
#: that the histogram counts real blocks, and a surface with nothing to show
#: passes a "shows live data" rule for the wrong reason.
PREPARED_CHUNKS: Tuple[Tuple[int, int], ...] = ((0, 0), (0, 1), (1, 0), (1, 1))
STONE_LAYERS = (0, 3)
DIRT_LAYERS = (3, 4)


# ----------------------------------------------------------------------
# the design mock
# ----------------------------------------------------------------------

#: Strings from the design mock the Studio was built to match.  Each one is a
#: value no Minecraft world can produce by itself: a world named after a
#: version, a Bedrock folder id, a specific seed, a sign that reads "Market
#: Row", a structure file, a truncated player id with a typographic ellipsis in
#: the middle of it, a seven-character commit hash.
#:
#: This list is what makes the scan below mean anything.  The rule "a surface
#: must show live data" is satisfied by a surface that shows nothing, so only
#: naming the fakes catches one that was left behind.
DESIGN_FIXTURES: Tuple[str, ...] = (
    "1.17 Height",
    "8Dt6Xr5OAAA=",
    "1471929",
    "Market Row",
    "spawn-arch",
    "6f1c…a904",
    "a91f0c7",
    "3 boxes · 576 blocks",
    "bedrock 1.17.0.1",
    "812 chunks queued",
    "overworld · creative · level 34",
    "minecraft:villager",
    "Debug 1.14",
)

#: Every surface that still renders part of the design mock while a real world
#: is open, with the fixtures each one shows.  Measured, not guessed.
#:
#: This is a ledger that is supposed to shrink, and it is asserted exactly
#: rather than as an upper bound: binding one of these surfaces to the world
#: and leaving its name here would otherwise leave a record that says the
#: application is more of a mock than it is, and nothing would ever notice.
#: Striking a line out is part of binding the surface it names.
STILL_SHOWING_THE_MOCK: Dict[str, Tuple[str, ...]] = {
    "about": ("1.17 Height", "bedrock 1.17.0.1"),
    "analyzeTool": ("minecraft:villager",),
    "batchQueue": ("1.17 Height", "spawn-arch"),
    "blockSelect": ("bedrock 1.17.0.1",),
    "convertProgress": ("1.17 Height", "bedrock 1.17.0.1"),
    "entityEdit": ("6f1c…a904", "minecraft:villager"),
    "erosion": ("1471929",),
    "exportStructure": ("bedrock 1.17.0.1", "spawn-arch"),
    "history": ("Debug 1.14", "a91f0c7"),
    "importChunks": ("Debug 1.14",),
    "libraryPanel": ("spawn-arch",),
    "logView": ("1.17 Height", "812 chunks queued", "bedrock 1.17.0.1"),
    "moveTool": ("spawn-arch",),
    "noiseGen": ("1471929",),
    "pendingImports": ("spawn-arch",),
    "playerPanel": ("6f1c…a904", "overworld · creative · level 34"),
    "pythonConsole": ("1.17 Height",),
    "regenerate": ("1471929",),
    "schematicLibrary": ("spawn-arch",),
    "selectEntityTool": ("6f1c…a904", "minecraft:villager"),
    "spawnPoints": ("6f1c…a904",),
    "tabManager": ("1.17 Height", "8Dt6Xr5OAAA=", "Debug 1.14"),
    "undoHistory": ("Debug 1.14", "a91f0c7"),
    "worldDiff": ("1.17 Height", "bedrock 1.17.0.1"),
}

#: Surfaces the index can open that are not descriptions this module can render
#: on its own.  Each opens a hand-built window instead -- the preferences dialog
#: is modal and would hang a test run outright -- so the scan below covers the
#: description registry and says so, rather than quietly covering less than it
#: appears to.  The set is asserted rather than assumed, so a new surface can
#: never drop out of the scan without somebody deciding it should.
UNSCANNED_ROUTED_SURFACES = frozenset(
    {
        "changelog",
        "memory",
        "nbt",
        "notifications",
        "palette",
        "prefs",
        "regex",
    }
)

#: The surfaces opened through the application's own ``open_surface`` route
#: rather than by constructing a dialog here, and the reason each is in the
#: sample.  Between them they cover a field form, a rule list, a mixed identity
#: and disk report, a computation over real chunk data, and a listing of the
#: region files on disk.
SAMPLE_SURFACES: Tuple[Tuple[str, str], ...] = (
    ("levelDat", "the level.dat form"),
    ("gamerules", "the rule list"),
    ("worldInfo", "identity, disk usage, and dimensions"),
    ("blockHistogram", "a count over real chunk data"),
    ("chunkInspector", "a listing of the real region files"),
)

#: How many descendants a text walk visits before giving up.  A malformed tree
#: should fail the test rather than hang the suite.
MAX_DESCENDANTS = 8000

#: Where the shipped surface descriptions live, for the check that every string
#: named above is one that actually exists in the interface.
STUDIO_SOURCE = ROOT / "amulet_map_editor" / "api" / "studio"


# ----------------------------------------------------------------------
# preparing a world, and reading it without the application
# ----------------------------------------------------------------------


def _extract_shared_world() -> pathlib.Path:
    """Return the shared extracted probe world, extracting it if it is absent."""
    local = os.environ.get("LOCALAPPDATA") or os.environ.get("TMPDIR") or "."
    target = pathlib.Path(local) / "amulet-probe" / "world" / WORLD_NAME
    if (target / "level.dat").is_file():
        return target
    if not WORLD_ARCHIVE.is_file():
        pytest.skip(f"the test world archive is missing: {WORLD_ARCHIVE}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(WORLD_ARCHIVE) as archive:
        archive.extractall(target.parent)
    if not (target / "level.dat").is_file():
        pytest.fail(f"{WORLD_ARCHIVE.name} did not extract a level.dat into {target}")
    return target


def _copy_world(source: pathlib.Path, destination: str) -> None:
    """Copy the shared probe world to a private one this run can edit.

    ``session.lock`` is deliberately left behind.  It is the lock file the game
    and amulet-core write while a world is open, so any other process holding
    that world -- another probe, a second test run, the application itself --
    makes it unreadable, and copying it turns an unrelated open window into a
    permission error here.  A world without one is not missing anything: the
    next process to open it writes its own.
    """
    shutil.copytree(
        str(source),
        destination,
        ignore=shutil.ignore_patterns("session.lock"),
    )
    if not os.path.isfile(os.path.join(destination, "level.dat")):
        pytest.fail(f"the copied world at {destination} has no level.dat")


def _add_terrain(path: str) -> None:
    """Write real chunks into the copied world, through amulet-core itself.

    The blocks go in as the universal palette entries the level actually
    stores, which is what a loaded chunk holds and what the histogram reads
    back.  Nothing here asserts anything; the assertions read the world
    afterwards and compare the application against it.
    """
    level = amulet.load_level(path)
    try:
        for cx, cz in PREPARED_CHUNKS:
            chunk = Chunk(cx, cz)
            stone = chunk.block_palette.get_add_block(
                Block("universal_minecraft", "stone")
            )
            dirt = chunk.block_palette.get_add_block(
                Block("universal_minecraft", "dirt")
            )
            chunk.blocks[:, STONE_LAYERS[0] : STONE_LAYERS[1], :] = stone
            chunk.blocks[:, DIRT_LAYERS[0] : DIRT_LAYERS[1], :] = dirt
            chunk.changed = True
            level.put_chunk(chunk, TEST_DIMENSION)
        level.save()
    finally:
        level.close()


@dataclass(frozen=True)
class WorldTruth:
    """What amulet-core says about the world, read without the application.

    Taken before the window exists and from a separate handle, so every
    comparison in this module has a source that the interface could not have
    influenced.
    """

    path: str
    name: str = ""
    platform: str = ""
    version: str = ""
    game_version: str = ""
    dimensions: Tuple[str, ...] = ()
    chunk_counts: Dict[str, int] = field(default_factory=dict)
    bounds: Dict[str, Tuple[int, int]] = field(default_factory=dict)
    sub_chunk_size: int = 16
    seed: str = ""
    spawn: Optional[Tuple[int, int, int]] = None
    game_rules: Dict[str, str] = field(default_factory=dict)
    data_version: Optional[int] = None


def _read_truth(path: str) -> WorldTruth:
    """Return what a plain amulet-core read of ``path`` reports."""
    level = amulet.load_level(path)
    try:
        wrapper = level.level_wrapper
        raw_version = wrapper.version
        if isinstance(raw_version, (tuple, list)):
            version = ".".join(str(part) for part in raw_version)
        else:
            version = str(raw_version)
        game_version = str(wrapper.game_version_string or "")
        if " " in game_version:
            version = game_version.split(" ", 1)[-1]
        names = tuple(str(name) for name in level.dimensions)
        counts = {name: len(list(level.all_chunk_coords(name))) for name in names}
        bounds = {}
        for name in names:
            box = level.bounds(name)
            bounds[name] = (int(box.min_y), int(box.max_y))
        compound = wrapper.root_tag.compound
        data = compound.get_compound("Data") if "Data" in compound else compound
        rules = {}
        if "GameRules" in data:
            for key, value in data.get_compound("GameRules").items():
                rules[str(key)] = str(getattr(value, "py_data", value))
        spawn = tuple(
            int(getattr(data[key], "py_data", data[key]))
            for key in ("SpawnX", "SpawnY", "SpawnZ")
        )
        seed_tag = data["RandomSeed"]
        return WorldTruth(
            path=path,
            name=str(wrapper.level_name),
            platform=str(wrapper.platform),
            version=version,
            game_version=game_version,
            dimensions=names,
            chunk_counts=counts,
            bounds=bounds,
            sub_chunk_size=int(level.sub_chunk_size),
            seed=str(int(getattr(seed_tag, "py_data", seed_tag))),
            spawn=spawn,  # type: ignore[arg-type]
            game_rules=rules,
            data_version=int(
                getattr(data["DataVersion"], "py_data", data["DataVersion"])
            ),
        )
    finally:
        level.close()


def _expected_block_counts(path: str) -> Dict[str, int]:
    """Return the blocks inside the drawn box, named as the world names them.

    Read straight off the chunk's own block array and translated with the
    level's own translator: the histogram is compared against what the level
    holds rather than against a number typed here, so the two can only agree
    when the histogram genuinely read the chunk.
    """
    level = amulet.load_level(path)
    try:
        platform, version = level.level_wrapper.max_world_version
        translator = level.translation_manager.get_version(platform, version).block
        size = level.sub_chunk_size
        counts: Dict[str, int] = {}
        for cx in range(SELECTION_MIN[0] // size, -(-SELECTION_MAX[0] // size)):
            for cz in range(SELECTION_MIN[2] // size, -(-SELECTION_MAX[2] // size)):
                chunk = level.get_chunk(cx, cz, TEST_DIMENSION)
                array = numpy.asarray(
                    chunk.blocks[0:size, SELECTION_MIN[1] : SELECTION_MAX[1], 0:size]
                )
                ids, occurrences = numpy.unique(array, return_counts=True)
                for runtime_id, occurrence in zip(ids.tolist(), occurrences.tolist()):
                    block = chunk.block_palette[runtime_id]
                    converted = translator.from_universal(block)[0]
                    name = str(getattr(converted, "namespaced_name", converted))
                    counts[name] = counts.get(name, 0) + int(occurrence)
        return counts
    finally:
        level.close()


# ----------------------------------------------------------------------
# reading what a window actually rendered
# ----------------------------------------------------------------------


def _rendered_text(window: Any) -> str:
    """Return everything ``window`` shows or announces, as one blob.

    Most of the Studio paints itself, so a great deal of its content lives in
    the accessible name rather than in a label wx would hand back -- and the
    accessible name is what a screen reader gets, which makes it exactly the
    right thing to hold to the same standard.  Custom pills keep their text in
    ``_text``; both are collected.
    """
    parts: List[str] = []
    stack: List[Any] = [window]
    seen = 0
    while stack and seen < MAX_DESCENDANTS:
        node = stack.pop()
        seen += 1
        for getter in ("GetLabel", "GetName", "GetValue", "GetHint"):
            method = getattr(node, getter, None)
            if not callable(method):
                continue
            try:
                value = method()
            except Exception:  # noqa: BLE001 - a control mid-teardown answers this
                continue
            if isinstance(value, str) and value.strip():
                parts.append(value)
        strings = getattr(node, "GetStrings", None)
        if callable(strings):
            try:
                parts.extend(str(item) for item in strings())
            except Exception:  # noqa: BLE001 - not every control has entries
                pass
        text = getattr(node, "_text", None)
        if isinstance(text, str) and text.strip():
            parts.append(text)
        try:
            stack.extend(node.GetChildren())
        except Exception:  # noqa: BLE001 - destroyed mid-walk
            continue
    return "\n".join(parts)


def _fixtures_in(blob: str) -> Tuple[str, ...]:
    """Return every design-mock string present in ``blob``."""
    return tuple(sorted(item for item in DESIGN_FIXTURES if item in blob))


def _pump(seconds: float) -> None:
    """Let wx run its event loop for ``seconds`` without blocking it."""
    end = time.time() + seconds
    while time.time() < end:
        wx.Yield()
        time.sleep(0.01)


def _wait_for(predicate, seconds: float) -> bool:
    """Pump the loop until ``predicate`` holds, or ``seconds`` have passed."""
    end = time.time() + seconds
    while time.time() < end:
        if predicate():
            return True
        wx.Yield()
        time.sleep(0.05)
    return bool(predicate())


# ----------------------------------------------------------------------
# the captured session
# ----------------------------------------------------------------------


@dataclass
class Report:
    """Everything the live session observed, captured once and asserted many.

    Capturing rather than re-opening per test keeps the run to one frame and
    one world, and makes the order the tests run in irrelevant -- including for
    the closed-world half, which mutates the state every other test reads.
    """

    truth: WorldTruth
    expected_blocks: Dict[str, int]

    # with the world open
    open_context: Any = None
    level_dimensions: Tuple[str, ...] = ()
    level_chunk_counts: Dict[str, int] = field(default_factory=dict)
    level_name: str = ""
    level_platform: str = ""
    level_game_version: str = ""
    navigator_entries: Tuple[Tuple[str, int, str], ...] = ()
    navigator_boxes: Tuple[Any, ...] = ()
    breadcrumb_summary: str = ""
    status_selection: str = ""
    status_dimension: str = ""
    status_world: str = ""
    selection_volume: int = 0
    selection_boxes: int = 0
    renderer_took_selection: Optional[bool] = None
    canvas_attached: bool = False

    # the level's own undo depth, before and after a real edit
    undo_before: int = 0
    undo_after: int = 0
    undo_restored: int = 0
    revision_before: Tuple[int, int] = (0, 0)
    revision_after: Tuple[int, int] = (0, 0)
    revision_labels_before: Tuple[str, str] = ("", "")

    # rendered text
    sample_surface_text: Dict[str, str] = field(default_factory=dict)
    surface_text: Dict[str, str] = field(default_factory=dict)
    shell_text: str = ""

    # with no world open
    closed_context_open: Optional[bool] = None
    closed_surface_text: Dict[str, str] = field(default_factory=dict)
    closed_shell_text: str = ""
    closed_workspace_text: str = ""
    closed_navigator_entries: Tuple[Any, ...] = ()
    closed_status_world: str = ""
    closed_status_selection: str = ""
    closed_breadcrumb_summary: str = ""
    failures: List[str] = field(default_factory=list)


@pytest.fixture(scope="module")
def app() -> Iterator[Any]:
    """One application object for the module; wx permits one per process."""
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
def report(app, tmp_path_factory) -> Iterator[Report]:
    """Open a real world in a real frame, and record what the interface says."""
    source = _extract_shared_world()
    workspace = tmp_path_factory.mktemp("live-world")
    world_path = str(workspace / WORLD_NAME)
    _copy_world(source, world_path)
    _add_terrain(world_path)

    truth = _read_truth(world_path)
    if not truth.chunk_counts.get(TEST_DIMENSION):
        pytest.fail(
            "the prepared world holds no chunks, so the chunk inspector and "
            "the histogram would be asserted against nothing"
        )
    expected_blocks = _expected_block_counts(world_path)
    if not expected_blocks:
        pytest.fail("the prepared selection holds no blocks to count")

    record = Report(truth=truth, expected_blocks=expected_blocks)

    from amulet_map_editor.api.framework.amulet_ui import AmuletUI

    frame = AmuletUI(None)
    try:
        frame.SetPosition(wx.Point(*OFFSCREEN))
        frame.Show()
        _pump(0.3)
        frame.open_level(world_path)
        _wait_for(lambda: context.current().open, 30.0)
        record.canvas_attached = _wait_for(
            lambda: frame.hosted_canvas() is not None, CANVAS_WAIT_SECONDS
        )
        _pump(0.3)
        _capture(frame, record)
    finally:
        try:
            frame.Destroy()
        except Exception:  # noqa: BLE001 - a frame already gone is fine
            pass
        _pump(0.3)
        context.clear()
    yield record


def _capture(frame: Any, record: Report) -> None:
    """Fill ``record`` from the running application."""
    studio = frame._studio
    assert studio is not None, (
        "the Studio shell could not be constructed, so the frame is showing "
        "the world notebook and there is no interface to hold to this contract"
    )
    workspace = studio.workspace

    record.renderer_took_selection = navigator.push_selection(
        [navigator.SelectionBox("Box 1", SELECTION_MIN, tuple(SELECTION_MAX))]
    )
    _pump(0.3)

    ctx = context.current()
    record.open_context = ctx
    level = ctx.level
    assert level is not None, "the world context carries no level to compare against"
    record.level_dimensions = tuple(str(name) for name in level.dimensions)
    record.level_chunk_counts = {
        name: len(list(level.all_chunk_coords(name)))
        for name in record.level_dimensions
    }
    record.level_name = str(level.level_wrapper.level_name)
    record.level_platform = str(level.level_wrapper.platform)
    record.level_game_version = str(level.level_wrapper.game_version_string or "")
    record.selection_volume = int(ctx.selection_volume)
    record.selection_boxes = len(ctx.selection_boxes)

    record.navigator_entries = tuple(
        (entry.key, int(entry.chunks), entry.height_range)
        for entry in workspace.navigator.dimensions
    )
    record.navigator_boxes = tuple(workspace.navigator.boxes)
    record.breadcrumb_summary = workspace.breadcrumb.summary._text
    record.status_selection = workspace.status.selection._text
    record.status_dimension = workspace.status.dimension._text
    record.status_world = workspace.status.status_text()
    record.revision_labels_before = (
        workspace.breadcrumb.revision.GetLabel(),
        workspace.status.revision.GetLabel(),
    )

    history = level.history_manager
    record.undo_before = int(history.undo_count)
    record.revision_before = (
        int(workspace.breadcrumb.revision.count),
        int(workspace.status.revision.count),
    )

    record.shell_text = _rendered_text(studio)

    for key, _why in SAMPLE_SURFACES:
        window = surfaces.open_surface(studio, key)
        _pump(0.3)
        if window is None:
            record.failures.append(f"open_surface({key!r}) opened nothing")
            continue
        record.sample_surface_text[key] = _rendered_text(window)
        window.Close()
        _pump(0.2)

    for key in spec_registry.keys():
        record.surface_text[key] = _render_spec(studio, key, record)

    # A real edit, so the revision readouts have something to follow.  It is
    # made on the level rather than through a command so that what the pills
    # are compared against is the level's own undo depth and nothing else, and
    # it is undone afterwards so the world is left as it was found.
    level.create_undo_point()
    context.refresh()
    _pump(0.3)
    record.undo_after = int(history.undo_count)
    record.revision_after = (
        int(workspace.breadcrumb.revision.count),
        int(workspace.status.revision.count),
    )
    level.undo()
    context.refresh()
    _pump(0.2)
    record.undo_restored = int(history.undo_count)

    # Now close the world and record what is left showing.
    frame.close_level(record.truth.path)
    _wait_for(lambda: not context.current().open, 30.0)
    _pump(0.3)
    record.closed_context_open = bool(context.current().open)
    record.closed_shell_text = _rendered_text(studio)
    record.closed_workspace_text = _rendered_text(workspace)
    record.closed_navigator_entries = tuple(workspace.navigator.dimensions)
    record.closed_status_world = workspace.status.status_text()
    record.closed_status_selection = workspace.status.selection._text
    record.closed_breadcrumb_summary = workspace.breadcrumb.summary._text
    for key in sorted(live.bound_keys()):
        if spec_registry.get(key) is None:
            continue
        record.closed_surface_text[key] = _render_spec(studio, key, record)


def _render_spec(host: Any, key: str, record: Report) -> str:
    """Build one surface for real and return everything it rendered."""
    spec = spec_registry.get(key)
    if spec is None:
        record.failures.append(f"surface {key!r} vanished from the registry")
        return ""
    dialog = SpecDialog(host, spec)
    try:
        dialog.Layout()
        dialog.Show()
        wx.Yield()
        return _rendered_text(dialog)
    finally:
        dialog.Hide()
        dialog.Destroy()
        wx.Yield()


# ----------------------------------------------------------------------
# the capture itself has to have happened
# ----------------------------------------------------------------------
def test_the_session_captured_everything_it_claims_to(report: Report):
    """A capture that quietly half-failed would make every test below vacuous."""
    assert not report.failures, "the live session could not capture:\n" + "\n".join(
        "  " + line for line in report.failures
    )
    assert report.open_context is not None and report.open_context.open, (
        "no world was open when the interface was read, so nothing below is "
        "asserting anything about a world"
    )
    assert len(report.surface_text) == len(spec_registry.keys()) > 100, (
        f"only {len(report.surface_text)} of {len(spec_registry.keys())} surfaces "
        "were rendered"
    )
    assert set(report.sample_surface_text) == {key for key, _ in SAMPLE_SURFACES}


# ----------------------------------------------------------------------
# 1. the context reports the world, not a fixture
# ----------------------------------------------------------------------
def test_the_context_reports_the_world_amulet_core_reports(report: Report):
    """Every identity field, against a separate read of the same folder."""
    ctx = report.open_context
    truth = report.truth
    assert ctx.name == truth.name == report.level_name
    assert os.path.normcase(ctx.path) == os.path.normcase(truth.path)
    assert ctx.platform == truth.platform == report.level_platform
    assert ctx.version == truth.version
    assert ctx.game_version == truth.game_version == report.level_game_version
    assert ctx.data_version == truth.data_version
    assert ctx.seed == truth.seed
    assert ctx.spawn == truth.spawn
    assert ctx.dimensions == truth.dimensions == report.level_dimensions
    assert ctx.dimension in ctx.dimensions
    assert ctx.sub_chunk_size == truth.sub_chunk_size
    assert dict(ctx.game_rules) == dict(truth.game_rules)
    assert ctx.game_rules, "the world stores game rules and the context has none"


def test_the_context_dimension_records_match_the_level(report: Report):
    """Build range and chunk count, per dimension, read from the level."""
    ctx = report.open_context
    recorded = {info.name: info for info in ctx.dimension_info}
    assert set(recorded) == set(report.level_dimensions)
    for name, info in recorded.items():
        assert info.counted, f"{name}: the chunk count could not be read at all"
        assert info.chunk_count == report.level_chunk_counts[name], name
        assert (info.min_y, info.max_y) == report.truth.bounds[name], name


def test_nothing_the_context_reports_is_a_design_fixture(report: Report):
    """The comparison above is only meaningful if the two sources differ.

    A world that happened to be named ``1.17 Height`` would make every fixture
    assertion in this module pass for the wrong reason, so the values being
    compared are checked against the mock first.
    """
    truth = report.truth
    values = "\n".join(
        [
            truth.name,
            truth.platform,
            truth.version,
            truth.game_version,
            truth.seed,
            str(truth.spawn),
            " ".join(truth.dimensions),
            " ".join(f"{k}={v}" for k, v in sorted(truth.game_rules.items())),
        ]
    )
    assert not _fixtures_in(values), (
        "the world this suite opens carries a string from the design mock, so "
        "the scan below could not tell live data from a fixture"
    )


# ----------------------------------------------------------------------
# 2. the navigator lists the dimensions the level has
# ----------------------------------------------------------------------
def test_the_navigator_lists_exactly_the_levels_dimensions(report: Report):
    listed = [key for key, _chunks, _range in report.navigator_entries]
    assert listed == list(report.level_dimensions), (
        "the navigator's dimension tree does not match what the level reports: "
        f"{listed} against {list(report.level_dimensions)}"
    )


def test_the_navigator_chunk_counts_match_the_level(report: Report):
    for key, chunks, height_range in report.navigator_entries:
        assert chunks == report.level_chunk_counts[key], (
            f"the navigator shows {chunks} chunks for {key}; the level reports "
            f"{report.level_chunk_counts[key]}"
        )
        low, high = report.truth.bounds[key]
        assert height_range == f"y {low} to {high}", key


def test_the_navigator_lists_the_selection_that_was_drawn(report: Report):
    assert len(report.navigator_boxes) == report.selection_boxes == 1
    box = report.navigator_boxes[0]
    assert tuple(box.minimum) == SELECTION_MIN
    assert tuple(box.size) == tuple(
        high - low for low, high in zip(SELECTION_MIN, SELECTION_MAX)
    )


# ----------------------------------------------------------------------
# 3. the status bar and the breadcrumb
# ----------------------------------------------------------------------
def test_the_selection_reached_the_renderer(report: Report):
    """The selection has to be the editor's own, not one kept beside it."""
    if report.canvas_attached:
        assert report.renderer_took_selection, (
            "the 3D editor's canvas is attached but it did not take the "
            "selection, so the viewport and the panes disagree about what is "
            "selected"
        )
    assert report.selection_volume > 0, "no selection reached the world context"


def test_the_status_bar_shows_the_real_selection_volume(report: Report):
    volume = report.selection_volume
    expected = 1
    for low, high in zip(SELECTION_MIN, SELECTION_MAX):
        expected *= high - low
    assert volume == expected
    assert f"{volume:,} blocks" in report.status_selection, report.status_selection
    assert report.status_selection == status_bar.selection_text(report.open_context)


def test_the_breadcrumb_summarises_the_real_selection(report: Report):
    summary = report.breadcrumb_summary
    assert str(report.selection_volume) in summary, summary
    assert summary.startswith(f"{report.selection_boxes} box"), summary


def test_the_status_bar_names_the_world_and_dimension_the_level_reports(
    report: Report,
):
    assert report.level_name in report.status_world
    assert report.level_game_version in report.status_world
    assert report.status_dimension == report.open_context.dimension
    assert report.status_dimension in report.level_dimensions


def test_the_revision_readouts_follow_the_levels_own_undo_depth(report: Report):
    """The count beside the breadcrumb is the world's undo stack, not a tally.

    Before any edit the world holds no undo points and both readouts say so
    rather than showing a commit hash from the mock; after one real edit both
    hold exactly what the level's history manager reports.
    """
    assert report.undo_before == 0
    assert report.revision_before == (0, 0), report.revision_before
    for label in report.revision_labels_before:
        assert label == status_bar.NO_REVISIONS, label
        assert not _fixtures_in(label), label
    assert report.undo_after == 1, (
        "creating an undo point on the level did not move its own undo depth, "
        "so this test proved nothing about the readouts"
    )
    assert report.revision_after == (report.undo_after, report.undo_after), (
        f"the breadcrumb and status readouts show {report.revision_after} while "
        f"the level reports {report.undo_after} undo points"
    )
    assert report.undo_restored == report.undo_before


# ----------------------------------------------------------------------
# 4. the surfaces render values that came from the world
# ----------------------------------------------------------------------
def test_the_level_dat_surface_shows_the_worlds_own_level_dat(report: Report):
    blob = report.sample_surface_text["levelDat"]
    assert report.level_name in blob
    assert report.truth.seed in blob
    assert report.level_game_version in blob
    assert report.truth.path in blob, "the surface does not say where it read from"
    for axis, value in zip("xyz", report.truth.spawn or ()):
        assert str(value) in blob, f"spawn {axis} is not shown"


def test_the_game_rules_surface_lists_every_rule_the_world_stores(report: Report):
    blob = report.sample_surface_text["gamerules"]
    missing = [
        f"{name} = {value}"
        for name, value in sorted(report.truth.game_rules.items())
        if f"{name} · {live.rule_type(value)} · {value}" not in blob
    ]
    assert not missing, (
        f"{len(missing)} of {len(report.truth.game_rules)} rules the world "
        "stores are not shown as it stores them: " + ", ".join(missing[:8])
    )
    assert f"{len(report.truth.game_rules)} rules stored by this world" in blob


def test_the_world_info_surface_shows_the_worlds_identity_and_dimensions(
    report: Report,
):
    blob = report.sample_surface_text["worldInfo"]
    assert report.level_name in blob
    assert report.truth.path in blob
    assert report.truth.seed in blob
    assert report.level_game_version in blob
    for name, count in report.level_chunk_counts.items():
        assert name in blob, name
        assert f"{count:,} chunks" in blob, f"{name}: {count} chunks is not shown"


def test_the_block_histogram_counts_the_blocks_the_level_holds(report: Report):
    """Every count is the level's own, computed from the chunk array beside it."""
    blob = report.sample_surface_text["blockHistogram"]
    assert live.NO_SELECTION not in blob, (
        "the histogram says nothing is selected, but a selection was drawn "
        "before it was opened"
    )
    total = sum(report.expected_blocks.values())
    assert total == report.selection_volume
    assert f"{total:,} blocks read from" in blob, blob[:400]
    for name, count in sorted(report.expected_blocks.items()):
        assert name in blob, f"{name} is in the world but not in the histogram"
        assert f"{count:,} blocks" in blob, f"{name}: {count} is not the count shown"


def test_the_chunk_inspector_lists_the_chunks_the_level_stores(report: Report):
    blob = report.sample_surface_text["chunkInspector"]
    dimension = report.open_context.dimension
    stored = report.level_chunk_counts[dimension]
    assert f"{stored:,} chunks are stored in {dimension}" in blob
    for cx, cz in PREPARED_CHUNKS:
        assert f"chunk {cx}, {cz}" in blob, f"chunk {cx}, {cz} is stored but not listed"


# ----------------------------------------------------------------------
# 5. nothing shows the design mock that is not recorded as showing it
# ----------------------------------------------------------------------
def test_the_shell_shows_no_design_fixture_while_a_world_is_open(report: Report):
    found = _fixtures_in(report.shell_text)
    assert not found, (
        "the workspace shell -- its ribbon, navigator, breadcrumb, status bar "
        f"and properties pane -- still shows the design mock: {list(found)}"
    )


def test_no_surface_that_reads_the_world_shows_a_design_fixture(report: Report):
    bound = sorted(key for key in live.bound_keys() if key in report.surface_text)
    assert bound, "no surface claims to read the open world"
    offenders = {
        key: list(_fixtures_in(report.surface_text[key]))
        for key in bound
        if _fixtures_in(report.surface_text[key])
    }
    assert not offenders, (
        "surfaces that are bound to the open world are still rendering the "
        f"design mock: {offenders}"
    )


def test_the_surfaces_still_showing_the_mock_are_exactly_the_recorded_ones(
    report: Report,
):
    """The ledger of what is still a demo, held to exactly.

    A surface that gains live data and stays on this list leaves a record
    claiming the application is more of a mock than it is; one that loses it
    and is absent from the list is a regression nobody would see.  Both are
    failures here, and both are fixed by editing one line.
    """
    found = {
        key: list(_fixtures_in(blob))
        for key, blob in sorted(report.surface_text.items())
        if _fixtures_in(blob)
    }
    expected = {
        key: list(value) for key, value in sorted(STILL_SHOWING_THE_MOCK.items())
    }
    regressed = {k: v for k, v in found.items() if k not in expected}
    improved = sorted(set(expected) - set(found))
    changed = {
        k: (expected[k], v)
        for k, v in found.items()
        if k in expected and expected[k] != v
    }
    assert not regressed, (
        "these surfaces have started showing the design mock while a real "
        f"world is open: {regressed}"
    )
    assert not improved, (
        "these surfaces no longer show the design mock, so their lines in "
        f"STILL_SHOWING_THE_MOCK are now false and should be deleted: {improved}"
    )
    assert not changed, (
        "the fixtures these surfaces show have changed; update "
        f"STILL_SHOWING_THE_MOCK: {changed}"
    )


def test_every_named_fixture_is_a_string_the_interface_really_contains():
    """A misspelt fixture string would make the whole scan pass on nothing.

    Every string in ``DESIGN_FIXTURES`` has to be one the shipped interface
    actually carries.  One that is not is a typo or a mock that has been fully
    removed, and either way it is scanning for something nothing can produce --
    a check that cannot fail, sitting in the middle of the check that matters.

    A string can be present here and absent from every rendered surface: that
    is what a binder replacing its section looks like, and it is the outcome
    this whole module is asking for.
    """
    sources = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in sorted(STUDIO_SOURCE.rglob("*.py"))
    )
    assert sources, f"no Studio source was read from {STUDIO_SOURCE}"
    missing = [item for item in DESIGN_FIXTURES if item not in sources]
    assert not missing, (
        "these design-mock strings are named in DESIGN_FIXTURES but appear "
        f"nowhere in the Studio source, so they guard nothing: {missing}"
    )


def test_the_recorded_ledger_only_names_fixtures_this_module_scans_for():
    recorded = set()
    for fixtures in STILL_SHOWING_THE_MOCK.values():
        recorded.update(fixtures)
    unnamed = sorted(recorded - set(DESIGN_FIXTURES))
    assert not unnamed, f"recorded fixtures that are not in DESIGN_FIXTURES: {unnamed}"


def test_the_recorded_ledger_names_real_unbound_surfaces():
    """The ledger cannot be allowed to rot into a list of renamed keys."""
    unknown = sorted(set(STILL_SHOWING_THE_MOCK) - set(spec_registry.keys()))
    assert (
        not unknown
    ), f"STILL_SHOWING_THE_MOCK names surfaces that no longer exist: {unknown}"
    excused = sorted(set(STILL_SHOWING_THE_MOCK) & set(live.bound_keys()))
    assert not excused, (
        "these surfaces are bound to the open world and are also excused from "
        f"showing the mock, which cannot both be true: {excused}"
    )


def test_the_scan_covers_every_surface_it_can_render():
    """The surfaces left out are exactly the ones that are not descriptions."""
    routed_only = set(surfaces.keys()) - set(spec_registry.keys())
    assert routed_only == set(UNSCANNED_ROUTED_SURFACES), (
        "the set of surfaces this scan cannot render has changed; a new one "
        "must be added to UNSCANNED_ROUTED_SURFACES deliberately rather than "
        f"dropping out of the scan: {sorted(routed_only)}"
    )


# ----------------------------------------------------------------------
# 6. with no world open, the world-dependent surfaces say so
# ----------------------------------------------------------------------
def test_closing_the_world_empties_the_context(report: Report):
    assert report.closed_context_open is False, (
        "closing the world left a world in the context, so every surface is "
        "still reading a level nobody has open"
    )


def test_with_no_world_open_the_shell_says_so_rather_than_showing_rows(
    report: Report,
):
    assert report.closed_status_world == status_bar.world_status_text(context.EMPTY)
    assert report.closed_status_selection == "No world open"
    assert report.closed_navigator_entries == ()
    assert report.closed_breadcrumb_summary.startswith("0 box")
    # The workspace, not the whole shell: the project screen's recent-projects
    # list names worlds that have been opened before, which is a real record of
    # what the user has done rather than a world it is claiming is open.
    assert (
        report.level_name not in report.closed_workspace_text
    ), "the editing workspace still names the world that was closed"
    assert not _fixtures_in(report.closed_shell_text)


def test_with_no_world_open_every_bound_surface_shows_its_empty_state(
    report: Report,
):
    assert (
        report.closed_surface_text
    ), "no bound surface was rendered with no world open"
    silent = [
        key
        for key, blob in sorted(report.closed_surface_text.items())
        if live.NO_WORLD not in blob and live.NO_SELECTION not in blob
    ]
    assert not silent, (
        "these surfaces read the world but say nothing about there being no "
        f"world to read: {silent}"
    )


def test_with_no_world_open_no_bound_surface_invents_rows(report: Report):
    """An empty state is honest; the closed world's numbers are not."""
    leaking = {
        key: sorted(
            value
            for value in (report.level_name, report.truth.seed, report.truth.path)
            if value and value in blob
        )
        for key, blob in sorted(report.closed_surface_text.items())
    }
    leaking = {key: value for key, value in leaking.items() if value}
    assert not leaking, (
        "these surfaces still show the closed world's own values: " f"{leaking}"
    )
    offenders = {
        key: list(_fixtures_in(blob))
        for key, blob in sorted(report.closed_surface_text.items())
        if _fixtures_in(blob)
    }
    assert not offenders, (
        "with no world open these surfaces fell back to the design mock rather "
        f"than to an empty state: {offenders}"
    )
