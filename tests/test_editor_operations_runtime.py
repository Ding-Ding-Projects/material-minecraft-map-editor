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

**Where the Run control actually is.**  The first version of this module asked
``IsShown`` up the ancestor chain and called the answer visibility.  It is not.
Measured in this frame at 1500x950, Replace's ``Run Operation`` button sits 1507
px down a 950 px-tall window -- 557 px below the bottom edge, and 651 px below
the bottom of its own panel -- because Replace stacks two block pickers in a
scrolling panel.  Every ancestor of that button answers ``IsShown() == True``,
and so does ``IsShownOnScreen()``, because neither of them is a question about
*where* anything is.  So the button is reachable only by scrolling, and the
assertion below is the one that survives being told that: the control has to lie
inside the client area of every window above it *after* its panel has been asked
to scroll it into view.  A control laid out past the end of that panel's
scrollable area -- the shape a future change pushing a Run button off its panel
would take -- cannot be scrolled to, and fails.

**When this module cannot run at all.**  Opening a real world needs a real
world, a real GPU context and a machine not already running another copy of
this suite, and when one of those is missing every test here is skipped --
which in a summary line is indistinguishable from every test here passing.  Set
``MMME_REQUIRE_EDITOR_RUNTIME=1`` on a host that is supposed to manage it and
those skips become failures that name their reason.

That variable earned itself immediately.  A fresh checkout of this repository
skips all eleven tests here with "the world did not open in this environment",
which reads as a flaky machine and is nothing of the sort: the renderer imports
``chunk_builder_cy``, the checkout has no compiled copy of it because a ``.pyd``
is a build artifact and not a tracked file, and the editor therefore has no
canvas to put a tool in.  Under the variable the same run says so out loud.
Build the extension in that checkout, or copy the built one beside
``chunk_builder.py``, and the module runs.

What a skipped host still checks is in ``tests/test_stock_operation_tiles.py``,
which needs no display: the tile, the key and the operation it asks for are
asserted there, so the defect this module was written for cannot hide behind an
environment that could not start.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import time
import zipfile
from typing import Any, Dict, Iterator, List, NoReturn, Optional, Tuple

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

#: Whether this host has been told it is one that can run the editor.
STRICT = os.environ.get("MMME_REQUIRE_EDITOR_RUNTIME", "").strip().lower() not in (
    "",
    "0",
    "false",
    "no",
    "off",
)


def _unavailable(reason: str) -> NoReturn:
    """Skip this module -- or fail it, on a host that promised it would run.

    A skipped module and a passing module read the same from a summary line,
    and this one skips for every reason a 3D editor has for not starting.  The
    environment variable is how a host says "I am not one of those", so that a
    run which verified nothing says so in red rather than in grey.
    """
    if STRICT:
        raise AssertionError(
            f"{reason}. MMME_REQUIRE_EDITOR_RUNTIME is set, so this host is "
            "meant to run the editor and a skip here would hide that it did not."
        )
    pytest.skip(reason)


# ----------------------------------------------------------------------
# a world to run an operation against
# ----------------------------------------------------------------------


def _extract_world(destination: pathlib.Path) -> pathlib.Path:
    if not WORLD_ARCHIVE.is_file():
        _unavailable(f"the test world archive is missing: {WORLD_ARCHIVE}")
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
    _unavailable(f"no level.dat inside {WORLD_ARCHIVE}")


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


def _visible_client(window: Any) -> Any:
    """The screen rectangle ``window`` draws its children inside."""
    origin = window.ClientToScreen(wx.Point(0, 0))
    size = window.GetClientSize()
    return wx.Rect(origin.x, origin.y, size.width, size.height)


def _inside_the_window(window: Any) -> bool:
    """Whether every pixel of ``window`` is somewhere inside the frame.

    ``IsShown`` answers about one window and ``IsShownOnScreen`` asks that same
    question of each ancestor in turn; neither is a question about *where*
    anything is, so both answer ``True`` for a control sitting 557 px below the
    bottom edge of the frame.  Replace's Run button is exactly that control, so
    a chain-of-``IsShown`` check passes for a button that appears in no
    screenshot of this window at any size.

    Measured instead: the control's own rectangle has to fit inside the client
    area of every window above it, and the last of those is the frame.  A
    control scrolled out of its panel, laid out past the edge of its parent, or
    pushed off the bottom of the window is not inside it, whatever ``IsShown``
    says about any of them.
    """
    node = window
    try:
        rect = window.GetScreenRect()
    except Exception:  # noqa: BLE001 - a window being destroyed
        return False
    if rect.width <= 0 or rect.height <= 0:
        return False
    while node is not None:
        try:
            if not node.IsShown():
                return False
            parent = node.GetParent()
            if parent is not None and not _visible_client(parent).Contains(rect):
                return False
            node = parent
        except Exception:  # noqa: BLE001 - a window being destroyed
            return False
    return True


def _scroll_into_view(window: Any) -> str:
    """Ask the nearest scrolling ancestor to bring ``window`` into view.

    Returns what was asked, for the failure message: "no scrolled ancestor" is
    a different defect from "scrolled and the control still is not there", and
    a reader of a red run should not have to guess which one they have.
    """
    child = window
    node = window.GetParent()
    while node is not None:
        if isinstance(node, wx.ScrolledWindow) and hasattr(node, "ScrollChildIntoView"):
            try:
                node.ScrollChildIntoView(child)
                return f"{type(node).__name__}.ScrollChildIntoView"
            except Exception as error:  # noqa: BLE001
                return f"{type(node).__name__}.ScrollChildIntoView raised {error!r}"
        child = node
        node = node.GetParent()
    return "no scrolling ancestor"


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
            _unavailable(f"wx.App could not start on this host: {error!r}")
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
            _unavailable("the world did not open in this environment")
        if not _wait_for(
            lambda: frame.hosted_canvas() is not None, CANVAS_WAIT_SECONDS
        ):
            frame.sync_studio_project()
            _pump(1.0)
        record.canvas = frame.hosted_canvas() or editor_tools.canvas()
        if record.canvas is None:
            _unavailable("the 3D editor produced no canvas on this host")
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
            # Where each Run control is before anything scrolls, and then where
            # it is once its own panel has been asked for it.  Both, because
            # "already there" and "one scroll away" are different answers and
            # only one of them matches the copy on the tile.
            in_window = [control for control in runs if _inside_the_window(control)]
            scrolls = [_scroll_into_view(control) for control in runs]
            _pump(0.2)
            reachable = [control for control in runs if _inside_the_window(control)]
            record.arrivals[tile.label] = {
                "surface": tile.surface,
                "ok": bool(getattr(opened, "ok", False)),
                "message": str(getattr(opened, "message", "")),
                "chooser_found": chooser is not None,
                "selected": (
                    str(chooser.GetStringSelection()) if chooser is not None else ""
                ),
                "chooser_shown": (
                    _inside_the_window(chooser) if chooser is not None else False
                ),
                "run_controls": len(runs),
                "run_in_window": len(in_window),
                "run_reachable": len(reachable),
                "run_scrolled_by": scrolls,
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


def test_the_visibility_measurement_notices_a_control_below_the_fold(app) -> None:
    """Prove the measurement above can say no, before believing it saying yes.

    Built here rather than looked for in the editor, so this is deterministic
    and so it runs on a host where no world opens.  Three states, because the
    difference between them is the whole point: a control in view, a control
    scrolled out of view that scrolling brings back, and a control laid out
    past the end of the scrollable area that nothing brings back.  The middle
    one is what a chain of ``IsShown`` calls cannot see, and the last one is the
    regression the Run-control assertion below exists to catch.
    """
    from wx.lib.scrolledpanel import ScrolledPanel

    frame = wx.Frame(None, size=wx.Size(400, 300))
    frame.SetPosition(wx.Point(*OFFSCREEN))
    try:
        panel = ScrolledPanel(frame)
        sizer = wx.BoxSizer(wx.VERTICAL)
        panel.SetSizer(sizer)
        top = wx.Button(panel, label="near the top")
        sizer.Add(top, 0, wx.ALL, 5)
        for index in range(20):
            sizer.Add(wx.StaticText(panel, label=f"row {index}"), 0, wx.ALL, 12)
        below = wx.Button(panel, label=RUN_LABEL)
        sizer.Add(below, 0, wx.ALL, 5)
        panel.SetupScrolling()
        panel.SetAutoLayout(1)
        frame.Show()
        _pump(0.3)

        assert _inside_the_window(top), (
            "a control at the top of a visible panel is inside the window, and "
            "a measurement that cannot say yes says nothing by saying no"
        )
        assert not _inside_the_window(below), (
            "a control scrolled far below the visible area of its panel is not "
            "inside the window -- and this is exactly what IsShownOnScreen "
            f"answers True for: {below.IsShownOnScreen()}"
        )
        _scroll_into_view(below)
        _pump(0.2)
        assert _inside_the_window(
            below
        ), "scrolling a control into view should put it inside the window"

        # Laid out beyond the panel's scrollable extent: the shape a change
        # that pushed a Run button off its panel would take.
        stray = wx.Button(panel, label=RUN_LABEL, pos=wx.Point(0, 5000))
        _pump(0.2)
        _scroll_into_view(stray)
        _pump(0.2)
        assert not _inside_the_window(stray), (
            "a control positioned past the end of a scrolled panel cannot be "
            "scrolled to, so no assertion about it should pass"
        )
    finally:
        frame.Destroy()
        _pump(0.2)


@pytest.mark.parametrize("label,operation", EXPECTED_OPERATIONS)
def test_a_stock_operation_tile_arrives_with_its_run_control_reachable(
    session: Session, label: str, operation: str
) -> None:
    """The chosen operation exposes the control that runs it, and it can be got to.

    "Reachable" rather than "already in view", and the difference is measured
    rather than assumed: Replace's options are two block pickers stacked in a
    scrolling panel, so its Run button starts 651 px below the bottom of that
    panel in this frame and the user scrolls to it.  What must never happen is
    the panel not being able to scroll to it at all -- a Run control laid out
    past the end of the scrollable area is one no user can press, and it is
    indistinguishable from a working one to every ``IsShown`` in wxPython.
    """
    arrival = session.arrivals.get(label)
    assert arrival is not None, f"the {label} tile was never pressed"
    assert arrival["chooser_shown"], (
        f"after pressing {label} the operation list is not inside the window, "
        "so the chosen operation cannot be changed or confirmed"
    )
    assert arrival["run_controls"] == 1, (
        f"the {operation} operation should expose exactly one {RUN_LABEL!r} "
        f"control and the tool is holding {arrival['run_controls']}. None means "
        "the operation's panel did not finish building -- which is what a wx "
        "assertion mid-constructor leaves behind -- and more than one means a "
        "previous operation's panel was stranded rather than replaced."
    )
    assert arrival["run_reachable"] == 1, (
        f"the {operation} operation's {RUN_LABEL!r} control cannot be brought "
        "inside the window: it is laid out past the end of its panel's "
        "scrollable area, so scrolling does not reach it and neither does the "
        f"user. Before scrolling {arrival['run_in_window']} of "
        f"{arrival['run_controls']} were in view; the scroll attempted was "
        f"{arrival['run_scrolled_by']}."
    )
