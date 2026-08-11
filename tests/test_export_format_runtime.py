"""Each Format choice exports through *its own* exporter, in a real editor.

The Structures tab offers four formats and one Export button.  Until the routing
this module drives existed, choosing a format stored a string nobody read: the
button started the editor's Export tool with no operation named, so the tool
landed on whichever entry its chooser sorted first.  That entry is ``Export
Construction``, because the construction plugin registers itself as
``"\\tExport Construction"`` with a literal leading tab in order to sort to the
top.  Driven end to end before the fix: pick ``schematic (.schematic)``, press
Export, and the tool opens on ``...export_operations.construction`` while the
success toast reads "Export Construction" back at somebody who chose a
schematic.

So the assertion here is deliberately not "an exporter was selected".  Four
assertions name four different exporters, each read back from the ``wx.Choice``
the user is looking at, after the ribbon's own dropdown has been set and the
ribbon's own Export command run.  A regression that dropped the operation state
again would leave exactly one of these green -- construction, the one that was
right by accident -- which is the shape this module exists to make impossible.

**Nothing here names an exporter by hand.**  The expected names come from
``ribbon_defs.STRUCTURE_FORMATS``, and that table is checked against the plugin
files' own declarations in ``tests/test_export_format_routing.py``.  A constant
repeated here would agree with the table by construction.

**When this module cannot run at all.**  Opening a real world needs a real
world, a real GPU context and a machine not already running another copy of this
suite, and when one of those is missing every test here skips -- which in a
summary line is indistinguishable from every test here passing.  Set
``MMME_REQUIRE_EDITOR_RUNTIME=1`` on a host that is supposed to manage it and
those skips become failures naming their reason.  The display-free half is in
``tests/test_export_format_routing.py`` and runs everywhere.
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
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORLD_ARCHIVE = ROOT / "resource" / "worlds" / "java_1_12_2.zip"
WORLD_NAME = "java_1_12_2"

#: Off-screen, so a run on a visible desktop never throws a window at anybody.
OFFSCREEN = (-32000, -32000)

#: The 3D editor loads a resource pack and builds a texture atlas on a worker
#: thread before it has a canvas, so it is genuinely absent for a while.
CANVAS_WAIT_SECONDS = 120.0

#: The box drawn before exporting.  Export needs a selection, and a command with
#: an unmet requirement is refused by the shell before its handler runs -- which
#: would leave every assertion below reading a tool nobody started.
SELECTION = ((0, 0, 0), (16, 4, 16))

#: Whether this host has been told it is one that can run the editor.
STRICT = os.environ.get("MMME_REQUIRE_EDITOR_RUNTIME", "").strip().lower() not in (
    "",
    "0",
    "false",
    "no",
    "off",
)


def _unavailable(reason: str) -> NoReturn:
    """Skip this module -- or fail it, on a host that promised it would run."""
    if STRICT:
        raise AssertionError(
            f"{reason}. MMME_REQUIRE_EDITOR_RUNTIME is set, so this host is "
            "meant to run the editor and a skip here would hide that it did not."
        )
    pytest.skip(reason)


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


def _format_dropdown(shell: Any) -> Optional[Any]:
    """Return the ribbon's own Format combo, or ``None``.

    Through the shell's own ``_ribbon_choice``, which is how the shell reaches
    the Dimension combo too, so this is the control the user clicks rather than
    something that happens to carry the same label.
    """
    try:
        return shell._ribbon_choice("Format")
    except Exception:  # noqa: BLE001 - a ribbon still building
        return None


def _exporter_chooser(canvas: Any) -> Optional[Any]:
    """Return the Export tool's own exporter list, or ``None``.

    Identified by what it holds -- the one ``wx.Choice`` offering every stock
    exporter -- rather than by position, because an exporter's own options panel
    carries dropdowns of its own and the first Choice found is often one of
    those.
    """
    tool = editor_tools.tool_named("Export", canvas)
    if tool is None:
        return None
    wanted = {
        " ".join(item.operation.split()) for item in ribbon_defs.STRUCTURE_FORMATS
    }
    stack: List[Any] = []
    try:
        stack.extend(tool.windows())
    except Exception:  # noqa: BLE001 - a tool without its panels yet
        return None
    while stack:
        node = stack.pop()
        try:
            if isinstance(node, wx.Choice):
                offered = {" ".join(str(text).split()) for text in node.GetStrings()}
                if wanted <= offered:
                    return node
            stack.extend(node.GetChildren())
        except Exception:  # noqa: BLE001 - a control mid-teardown
            continue
    return None


class Session:
    """One opened world, and what each format choice did to the Export tool."""

    def __init__(self) -> None:
        self.path: str = ""
        self.canvas: Any = None
        self.frame: Any = None
        self.shell: Any = None
        self.dropdown_found: bool = False
        #: ``format value -> what the editor was showing after Export``
        self.arrivals: Dict[str, Dict[str, Any]] = {}
        #: What changing the dropdown did to an Export tool already on screen.
        self.retarget: Dict[str, Any] = {}


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
    """Choose every format in turn, press Export, and record where each landed."""
    record = Session()
    workspace = tmp_path_factory.mktemp("export-format-runtime")
    record.path = _prepare_world(workspace)

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
        record.shell = getattr(frame, "_studio", None)
        if record.shell is None:
            _unavailable("the frame built no Studio shell on this host")
        _pump(0.5)

        # Export refuses without a selection, and a refused command never
        # reaches the handler under test.  Written through the same
        # ``selection_corners`` setter the shell's own Add box command uses.
        try:
            record.canvas.selection.selection_corners = (SELECTION,)
        except Exception as error:  # noqa: BLE001
            _unavailable(f"the editor would not take a selection box: {error!r}")
        _pump(0.3)
        if not record.canvas.selection.selection_corners:
            _unavailable("the editor kept an empty selection, so Export is refused")

        # The ribbon builds only the active tab's group panels, so the Format
        # combo exists only while Structures is showing -- which is where a user
        # is standing when they press Export.
        try:
            record.shell.workspace.ribbon.set_tab("structures")
        except Exception as error:  # noqa: BLE001
            _unavailable(f"the ribbon would not open the Structures tab: {error!r}")
        _pump(0.4)

        dropdown = _format_dropdown(record.shell)
        record.dropdown_found = dropdown is not None
        if dropdown is None:
            _unavailable("the ribbon built no Format dropdown on this host")

        for item in ribbon_defs.STRUCTURE_FORMATS:
            # Back to Select first, and this line is load-bearing.  The Format
            # dropdown's own command retargets the Export tool when Export is
            # already the tool on screen, so leaving the tool where the previous
            # iteration left it means the exporter is already correct before the
            # button is ever pressed -- and the whole loop then passes with the
            # Export button's routing deleted.  It was written without this and
            # measured passing against exactly that deletion.  Starting cold
            # leaves the Export press as the only thing that can select an
            # exporter, which is what this module is here to check.
            record.shell._activate_tool("Select")
            _pump(0.3)
            dropdown.set_value(item.label, notify=True)
            _pump(0.3)
            before = _exporter_chooser(record.canvas)
            # Read *now*, not into the dictionary built after the export -- the
            # first version of this line sat inside that literal and therefore
            # recorded the tool the export had just started, which made the
            # "started cold" assertion fail on every format including the one
            # that was correct.
            tool_before = editor_tools.active_tool_name(record.canvas)
            record.shell.run_command("export")
            _pump(0.8)
            chooser = _exporter_chooser(record.canvas)
            record.arrivals[item.value] = {
                "label": item.label,
                "wanted": item.operation,
                "ribbon_holds": record.shell._ribbon_value("Format"),
                "tool_before": tool_before,
                "selected_before": (
                    str(before.GetStringSelection()) if before is not None else ""
                ),
                "chooser_found": chooser is not None,
                "selected": (
                    str(chooser.GetStringSelection()) if chooser is not None else ""
                ),
                "tool": editor_tools.active_tool_name(record.canvas),
            }

        # And then the dropdown's own route, with the Export tool already
        # showing: changing the format there has to move the tool rather than
        # leave the ribbon and the chooser disagreeing.
        record.shell._activate_tool("Select")
        _pump(0.3)
        dropdown.set_value(ribbon_defs.STRUCTURE_FORMATS[0].label, notify=True)
        _pump(0.3)
        record.shell.run_command("export")
        _pump(0.8)
        target = ribbon_defs.STRUCTURE_FORMATS[-1]
        dropdown.set_value(target.label, notify=True)
        _pump(0.5)
        live = _exporter_chooser(record.canvas)
        record.retarget = {
            "label": target.label,
            "wanted": target.operation,
            "selected": str(live.GetStringSelection()) if live is not None else "",
        }
    finally:
        try:
            frame.Destroy()
        except Exception:  # noqa: BLE001 - a frame already gone is fine
            pass
        _pump(0.3)
        context.clear()
    yield record


def test_the_ribbon_offers_a_format_dropdown_with_four_formats(
    session: Session,
) -> None:
    """Four formats were driven.

    Without this every assertion below passes on an empty arrivals map, and a
    rule phrased "each format arrives correctly" is satisfied by no format
    having been chosen at all.
    """
    assert session.dropdown_found, "the ribbon built no Format dropdown"
    assert sorted(session.arrivals) == sorted(ribbon_defs.structure_format_values()), (
        "not every format the ribbon offers was driven: " f"{sorted(session.arrivals)}"
    )


@pytest.mark.parametrize(
    "value,operation",
    [(item.value, item.operation) for item in ribbon_defs.STRUCTURE_FORMATS],
    ids=[item.value for item in ribbon_defs.STRUCTURE_FORMATS],
)
def test_exporting_arrives_on_the_chosen_formats_exporter(
    session: Session, value: str, operation: str
) -> None:
    """One format chosen, one exporter selected -- that one, not the default.

    Read from the chooser the user is looking at rather than from anything the
    command said about itself: "the Export tool started" is exactly what all
    four formats reported while three of them were writing a ``.construction``.
    """
    arrival = session.arrivals.get(value)
    assert arrival is not None, (
        f"the {value!r} format was never chosen, so nothing about it is proven: "
        f"{sorted(session.arrivals)}"
    )
    assert arrival["ribbon_holds"] == value, (
        f"choosing {arrival['label']!r} should leave the ribbon holding "
        f"{value!r}; it holds {arrival['ribbon_holds']!r}"
    )
    assert arrival["tool_before"] != "Export", (
        "the Export tool was already showing before the button was pressed, so "
        "this measurement cannot tell a routed exporter from one the dropdown "
        f"had already selected; the editor was in {arrival['tool_before']!r}"
    )
    assert arrival["tool"] == "Export", (
        f"pressing Export after choosing {value!r} left the editor in the "
        f"{arrival['tool']!r} tool"
    )
    assert arrival["chooser_found"], (
        f"after exporting {value!r} the Export tool exposes no list of "
        "exporters, so this test cannot tell which exporter was chosen"
    )
    assert " ".join(arrival["selected"].split()) == " ".join(operation.split()), (
        f"choosing {arrival['label']!r} and pressing Export should arrive on "
        f"{operation!r} and arrived on {arrival['selected']!r}. That is the "
        "defect this module exists for: the Format dropdown decided nothing, so "
        "every format exported through whichever exporter sorted first."
    )


def test_no_two_formats_arrived_on_the_same_exporter(session: Session) -> None:
    """Four formats, four different destinations.

    Stated separately from the four assertions above because it is the failure
    in one sentence: before the fix all four of these read ``Export
    Construction``, and a reader of a red run should be able to see that at a
    glance rather than infer it from three parametrised failures.
    """
    landed = {
        value: " ".join(arrival["selected"].split())
        for value, arrival in session.arrivals.items()
    }
    assert len(set(landed.values())) == len(landed), (
        "two formats exported through the same exporter, so at least one of "
        f"them writes a file it does not name: {landed}"
    )


def test_changing_the_format_moves_an_export_tool_already_on_screen(
    session: Session,
) -> None:
    """The dropdown's own command does something, with the tool already showing.

    Separate from the four above, and measured separately, because it is a
    different route: those press the button from a cold tool, this changes the
    ribbon while the tool is in front of the user.  A ribbon saying one format
    above a chooser showing another is the same disagreement in a smaller space.
    """
    assert session.retarget, "the retarget case never ran"
    wanted = " ".join(session.retarget["wanted"].split())
    got = " ".join(session.retarget["selected"].split())
    assert got == wanted, (
        f"changing the format to {session.retarget['label']!r} while the Export "
        f"tool was showing should move it to {wanted!r}; it is showing {got!r}"
    )
