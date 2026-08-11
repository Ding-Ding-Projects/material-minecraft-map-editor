"""Each Operations tile arrives with *its own* operation selected, in a real editor.

Operations > Clone, Fill, Replace, Set biome and Waterlog are five tiles.  Until
this module existed they were five tiles pointing at one surface key, so pressing
any of them started the editor's Operation tool with whatever the chooser happened
to default to -- and because that chooser sorts its entries alphabetically, the
default was Clone.  Clone therefore *appeared* to work while the other four
silently opened the wrong operation, which is the worst shape a defect can take:
one visibly correct case standing in for four broken ones.

So the assertion here is deliberately not "the chooser opened".  Five separate
assertions name five different operations, each read back from the wx.Choice the
user is looking at, together with the Run control that operation must expose
before it can do anything.  A regression that collapsed the five keys back onto
one would leave exactly one of these green.

The route driven is the one a tile press takes: the ribbon definition's own
``surface`` key, through ``surfaces.open_surface``.  Nothing here names a key by
hand, so a tile rewired to a key that selects nothing fails here rather than
passing on a constant this module agreed with in advance.
"""

from __future__ import annotations

import pathlib
import shutil
import time
import zipfile
from typing import Any, Dict, Iterator, List, Optional, Tuple

import pytest

wx = pytest.importorskip("wx", reason="wxPython is not installed in this environment")
amulet = pytest.importorskip("amulet", reason="amulet-core is not installed")

from amulet_map_editor.api.studio import (  # noqa: E402
    context,
    editor_tools,
    ribbon_defs,
    surfaces,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORLD_ARCHIVE = ROOT / "resource" / "worlds" / "java_1_12_2.zip"
WORLD_NAME = "java_1_12_2"

#: Off-screen, so a run on a visible desktop never throws a window at anybody.
OFFSCREEN = (-32000, -32000)

#: The 3D editor loads a resource pack and builds a texture atlas on a worker
#: thread before it has a canvas, so it is genuinely absent for a while.
CANVAS_WAIT_SECONDS = 120.0

#: The tile label the user presses, and the operation the editor must land on --
#: the plugin's own ``export["name"]``, which is the string its chooser shows.
#: Written out by hand rather than derived from the ribbon, because a table
#: generated from the thing under test agrees with it by construction.
EXPECTED_OPERATIONS: Tuple[Tuple[str, str], ...] = (
    ("Clone", "Clone"),
    ("Fill", "Fill"),
    ("Replace", "Replace"),
    ("Set biome", "Set Biome"),
    ("Waterlog", "Waterlog"),
)

#: The label on the control that actually runs the chosen operation.
RUN_LABEL = "Run Operation"


# ----------------------------------------------------------------------
# a world to run an operation against
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
    """Copy the shipped test world out so nothing here touches the original."""
    source = _extract_world(workspace / "archive")
    path = str(workspace / WORLD_NAME)
    shutil.copytree(source, path, ignore=shutil.ignore_patterns("session.lock"))
    return path


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

    ``IsShown`` answers for one window alone, so a control on a hidden page
    answers ``True`` while being completely invisible.  The whole chain is
    walked because that is the only form of the question worth asking.
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


def _operation_tiles() -> Tuple[Any, ...]:
    """Return the five stock-operation tiles, from the ribbon's own definition."""
    tab = ribbon_defs.tab("operations")
    if tab is None:
        return ()
    for group in tab.groups:
        if group.title == "Stock operations":
            return tuple(group.buttons)
    return ()


def _chooser(canvas: Any) -> Optional[Any]:
    """Return the Operation tool's own operation list, or ``None``.

    Identified by what it holds rather than by where it sits: the operation
    list is the one ``wx.Choice`` offering every stock operation.  The first
    version of this walked the tool's windows and took the first Choice it
    found, which was fine while the panel underneath was always Clone's (Clone
    has no dropdowns) and started answering with *Set Biome's own mode
    dropdown* the moment the fix made the other operations reachable -- a
    measurement error that would have read as the fix not working.
    """
    tool = editor_tools.tool_named("Operation", canvas)
    if tool is None:
        return None
    wanted = {operation for _label, operation in EXPECTED_OPERATIONS}
    stack: List[Any] = []
    try:
        stack.extend(tool.windows())
    except Exception:  # noqa: BLE001 - a tool without its panels yet
        return None
    while stack:
        node = stack.pop()
        try:
            if isinstance(node, wx.Choice) and wanted <= set(node.GetStrings()):
                return node
            stack.extend(node.GetChildren())
        except Exception:  # noqa: BLE001 - a control mid-teardown
            continue
    return None


def _run_controls(canvas: Any) -> List[Any]:
    """Return every control that runs the chosen operation.

    Every one rather than the first, because an operation whose panel failed
    half-way through building is left parented to the tool and never destroyed:
    its stale Run button would answer a search for "is there one" on behalf of
    the operation that is actually showing.  Two is as wrong as none, and only
    a count can tell the difference.
    """
    found: List[Any] = []
    tool = editor_tools.tool_named("Operation", canvas)
    if tool is None:
        return found
    stack: List[Any] = []
    try:
        stack.extend(tool.windows())
    except Exception:  # noqa: BLE001
        return found
    while stack:
        node = stack.pop()
        try:
            if str(node.GetLabel() or "") == RUN_LABEL:
                found.append(node)
            stack.extend(node.GetChildren())
        except Exception:  # noqa: BLE001
            continue
    return found


class Session:
    """One opened world, and what each tile did to it."""

    def __init__(self) -> None:
        self.path: str = ""
        self.canvas: Any = None
        self.frame: Any = None
        self.tiles: Tuple[Any, ...] = ()
        self.routed: Tuple[str, ...] = ()
        #: ``tile label -> what the editor was showing after that tile``
        self.arrivals: Dict[str, Dict[str, Any]] = {}
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
    """Press every stock-operation tile in turn and record where each landed."""
    record = Session()
    workspace = tmp_path_factory.mktemp("operations-runtime")
    record.path = _prepare_world(workspace)
    record.tiles = _operation_tiles()

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
            frame.sync_studio_project()
            _pump(1.0)
        record.canvas = frame.hosted_canvas() or editor_tools.canvas()
        if record.canvas is None:
            pytest.skip("the 3D editor produced no canvas on this host")
        _pump(0.5)

        # The tool surfaces are routed onto the canvas by the properties pane as
        # it is built.  Asked for again here so this module drives the same
        # route whether or not that pane exists yet, and so a red run says which
        # operation arrived rather than that a described window opened instead.
        record.routed = editor_tools.install_surface_routes()

        for tile in record.tiles:
            opened = surfaces.open_surface(frame, tile.surface)
            _pump(0.8)
            chooser = _chooser(record.canvas)
            runs = _run_controls(record.canvas)
            record.arrivals[tile.label] = {
                "surface": tile.surface,
                "ok": bool(getattr(opened, "ok", False)),
                "message": str(getattr(opened, "message", "")),
                "chooser_found": chooser is not None,
                "selected": (
                    str(chooser.GetStringSelection()) if chooser is not None else ""
                ),
                "chooser_shown": (
                    _shown_to_the_user(chooser) if chooser is not None else False
                ),
                "run_controls": len(runs),
                "run_shown": sum(1 for control in runs if _shown_to_the_user(control)),
            }
    finally:
        try:
            frame.Destroy()
        except Exception:  # noqa: BLE001 - a frame already gone is fine
            pass
        _pump(0.3)
        context.clear()
    yield record


# ----------------------------------------------------------------------
# the tiles themselves
# ----------------------------------------------------------------------


def test_the_ribbon_still_offers_the_five_stock_operations(session: Session) -> None:
    """The enumeration finds five tiles with five distinct keys.

    Without this every assertion below passes on an empty list, and a rule
    phrased "each tile arrives correctly" is satisfied by a ribbon with no
    tiles on it at all.
    """
    labels = [tile.label for tile in session.tiles]
    assert labels == [label for label, _operation in EXPECTED_OPERATIONS], (
        "the Operations tab should offer Clone, Fill, Replace, Set biome and "
        f"Waterlog as its stock operations; it offers {labels}"
    )
    keys = [tile.surface for tile in session.tiles]
    assert len(set(keys)) == len(keys), (
        "the stock-operation tiles share a surface key, so pressing one of them "
        f"cannot mean anything different from pressing another: {keys}"
    )


@pytest.mark.parametrize("label,operation", EXPECTED_OPERATIONS)
def test_a_stock_operation_tile_arrives_with_that_operation_selected(
    session: Session, label: str, operation: str
) -> None:
    """Pressing one tile selects one operation -- that one, not the default.

    Read from the chooser the user is looking at rather than from anything the
    activation said about itself, because "the Operation tool started" is
    exactly what all five tiles reported while four of them were wrong.
    """
    arrival = session.arrivals.get(label)
    assert arrival is not None, (
        f"the {label} tile was never pressed, so nothing about it is proven: "
        f"{sorted(session.arrivals)}"
    )
    assert arrival[
        "ok"
    ], f"pressing {label} did not start the operation: {arrival['message']!r}"
    assert arrival["chooser_found"], (
        f"after pressing {label} the editor exposes no list of installed "
        "operations, so this test cannot tell which operation was chosen"
    )
    assert arrival["selected"] == operation, (
        f"pressing {label} should arrive with the {operation!r} operation "
        f"selected and arrived with {arrival['selected']!r}. That is the "
        "defect this module exists for: every tile started the same tool and "
        "left the chooser on whatever it defaulted to."
    )


@pytest.mark.parametrize("label,operation", EXPECTED_OPERATIONS)
def test_a_stock_operation_tile_arrives_ready_to_run(
    session: Session, label: str, operation: str
) -> None:
    """The chosen operation exposes the control that runs it, on screen.

    An operation selected behind a hidden panel is not reachable, and
    ``IsShown`` alone would not notice: the whole ancestor chain is walked.
    """
    arrival = session.arrivals.get(label)
    assert arrival is not None, f"the {label} tile was never pressed"
    assert arrival["chooser_shown"], (
        f"after pressing {label} the operation list is not visible to the user, "
        "so the chosen operation cannot be changed or confirmed"
    )
    assert arrival["run_controls"] == 1, (
        f"the {operation} operation should expose exactly one {RUN_LABEL!r} "
        f"control and the tool is holding {arrival['run_controls']}. None means "
        "the operation's panel did not finish building -- which is what a wx "
        "assertion mid-constructor leaves behind -- and more than one means a "
        "previous operation's panel was stranded rather than replaced."
    )
    assert arrival["run_shown"] == 1, (
        f"the {operation} operation's {RUN_LABEL!r} control is not visible to "
        "the user, so the operation cannot be run"
    )
