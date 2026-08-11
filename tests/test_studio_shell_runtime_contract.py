"""The Studio shell still constructs, paints, and routes at runtime.

Every other Studio test in this suite reads source or reads data.  Both are
worth having and neither can see the defect that costs the most time here: a
panel that constructs without error, lays out without error, passes every
source assertion, and renders as a flat rectangle of one colour.  A widget that
paints nothing looks exactly like a widget that paints correctly to anything
short of a real window on a real display.

So this module builds the real thing.  It constructs
:class:`~amulet_map_editor.api.studio.shell.StudioShell` inside a live
``wx.App``, shows it, drives a real paint, reads the pixels back, and counts how
many distinct colours came out.  A blank panel yields one or two.  A shell that
is genuinely drawing its title bar, its navigation, its cards, and its text
yields hundreds.

It also collects anything a paint handler raised.  wxPython dispatches paint on
the event loop, so an exception inside ``EVT_PAINT`` never propagates to the
caller: the handler dies, the region is left unpainted, and the calling code
carries on believing it drew something.  ``sys.excepthook`` is where those land,
so the trap below installs one and the tests fail on anything it caught, naming
each one.

The registry checks at the end are cheap and deliberately blunt.  They are the
seams that break when several people edit the ribbon, the surface index, and the
command table at the same time: a button naming a surface key nobody registered,
a group launcher pointing at a surface that was renamed, a spec with no entry in
the index that is supposed to list every surface.  None of those raise at import
time and every one of them is a control that does nothing when pressed.
"""

from __future__ import annotations

import sys
import traceback
from types import TracebackType
from typing import Iterator, List, Optional, Set, Tuple, Type

import pytest

wx = pytest.importorskip("wx")

from amulet_map_editor.api.studio import commands, ribbon_defs, surfaces
from amulet_map_editor.api.studio import specs as spec_registry

#: How far apart the colour samples are taken, in pixels.  Eight is fine enough
#: to land on text, borders, and card edges rather than only on large flat
#: fills, and coarse enough that sampling a full-size window stays quick.
SAMPLE_STEP = 8

#: The fewest distinct colours a healthy shell view may render.  On this
#: machine the backstage measures roughly 275 and the workspace roughly 400 at
#: 1424x881, so the floor sits far below either while remaining far above the
#: one or two colours a blank panel produces.  It is a floor rather than a
#: target on purpose: a different theme, display scale, or font renders a
#: different number of colours and none of that is a defect.
MIN_VIEW_COLOURS = 32

#: The same floor for one surface dialog, which is smaller and holds less.
#: Measured surfaces run from roughly 70 to 130 distinct colours.
MIN_SURFACE_COLOURS = 16

#: The fewest distinct colours the ribbon's command panel may render.
#:
#: This floor was measured rather than guessed, and the first guess was wrong in
#: the way that matters: an eight-colour floor passed a panel whose every child
#: had been hidden, because the panel's own background and its scrollbar still
#: render fifteen distinct colours on their own.  A guard that a deliberately
#: emptied ribbon walks straight through is not a guard.  Every healthy tab
#: measures between 51 and 80, so the floor sits above what an empty panel can
#: produce by itself and well below the quietest real one.
MIN_RIBBON_COLOURS = 32

#: The window the shell is built in.  Large enough that the ribbon, the
#: navigator, and the properties pane all have room, so a layout failure shows
#: up as a missing region rather than as an honest shortage of space.
FRAME_SIZE = (1440, 920)

#: How many descendants a tree walk will visit before giving up.  A surface
#: dialog holds a few hundred; the bound stops a cycle in a malformed tree from
#: hanging the suite instead of failing it.
MAX_DESCENDANTS = 5000

#: The surfaces opened for real.  Chosen for the section kinds they exercise
#: rather than for being representative of anything: between them they cover
#: every renderer path that has its own drawing code.
SAMPLE_SURFACES: Tuple[Tuple[str, str], ...] = (
    ("railTunnel", "the widest surface in the registry, at seventeen sections"),
    ("configureBlocks", "a texture section, which paints a generated tile"),
    ("regenerate", "a keygate, whose two keys and slider are custom-drawn"),
    ("blockHistogram", "a progress row, which paints its own track and fill"),
    ("biomeSelect", "a surface that is almost entirely one list"),
)


class _PaintTrap:
    """Collect every exception wxPython reports while this is open.

    A paint handler raising on the event loop is reported through
    ``sys.excepthook`` and nowhere else -- it does not propagate to whatever
    called ``Update``, and the only visible symptom is a region that stayed
    unpainted.  Swapping the hook for the duration of a test is therefore the
    only way to turn that into a failure.

    The previous hook is restored on exit even when the body raises, because
    leaving a test's collector installed would make every later failure in the
    session report into a list nobody reads.
    """

    def __init__(self) -> None:
        self.failures: List[str] = []
        self._previous = sys.excepthook

    def __enter__(self) -> "_PaintTrap":
        self._previous = sys.excepthook
        sys.excepthook = self._record
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        sys.excepthook = self._previous

    def _record(
        self,
        exc_type: Type[BaseException],
        exc: BaseException,
        tb: Optional[TracebackType],
    ) -> None:
        self.failures.append("".join(traceback.format_exception(exc_type, exc, tb)))

    def report(self, context: str) -> str:
        """Return a failure message naming everything caught, or an empty one."""
        if not self.failures:
            return ""
        joined = "\n".join(self.failures)
        return f"{len(self.failures)} exception(s) escaped while {context}:\n{joined}"


def _descendants(window: "wx.Window") -> Iterator["wx.Window"]:
    """Yield ``window`` and every window beneath it, breadth first."""
    stack: List["wx.Window"] = [window]
    seen = 0
    while stack and seen < MAX_DESCENDANTS:
        node = stack.pop()
        seen += 1
        yield node
        try:
            stack.extend(node.GetChildren())
        except RuntimeError:  # pragma: no cover - destroyed mid-walk
            continue


def _force_paint(window: "wx.Window") -> None:
    """Invalidate every visible descendant and let wx draw them all now.

    Refreshing only the top window is not enough on this platform: each child
    is its own native window and keeps its own valid region, so a parent-only
    refresh leaves every child's paint handler unrun and a broken one
    undetected.  ``Update`` then forces the queued regions to be drawn
    immediately rather than whenever the loop next idles, and ``Yield`` lets the
    handlers actually run before the caller reads pixels back.
    """
    top = window.GetTopLevelParent() or window
    for node in _descendants(top):
        try:
            if node.IsShownOnScreen():
                node.Refresh()
        except RuntimeError:  # pragma: no cover - destroyed mid-walk
            continue
    top.Update()
    wx.Yield()


def _distinct_colours(window: "wx.Window", step: int = SAMPLE_STEP) -> int:
    """Return how many distinct colours ``window`` actually rendered.

    The client area is blitted into a bitmap and sampled on a grid.  Reading
    the pixels is the whole point: a control can be constructed, sized, laid
    out, shown, and still draw nothing, and no assertion about its size or its
    children can tell the difference.
    """
    width, height = window.GetClientSize()
    if width <= 0 or height <= 0:
        return 0
    bitmap = wx.Bitmap(width, height)
    memory = wx.MemoryDC(bitmap)
    memory.Blit(0, 0, width, height, wx.ClientDC(window), 0, 0)
    memory.SelectObject(wx.NullBitmap)
    image = bitmap.ConvertToImage()
    colours: Set[Tuple[int, int, int]] = set()
    for y in range(0, height, step):
        for x in range(0, width, step):
            colours.add((image.GetRed(x, y), image.GetGreen(x, y), image.GetBlue(x, y)))
    return len(colours)


def _collapsed_children(window: "wx.Window") -> List[str]:
    """Return every shown descendant laid out at zero width or zero height.

    A control with no area is the quieter half of the same defect the colour
    count catches: it exists, it is marked visible, an accessibility walk finds
    it, and the user cannot see or press it.
    """
    collapsed: List[str] = []
    for node in _descendants(window):
        for child in node.GetChildren():
            try:
                if not child.IsShown():
                    continue
                size = child.GetSize()
            except RuntimeError:  # pragma: no cover - destroyed mid-walk
                continue
            if size.width <= 0 or size.height <= 0:
                collapsed.append(
                    f"{type(child).__name__} {child.GetName()!r} "
                    f"at {size.width}x{size.height}"
                )
    return collapsed


@pytest.fixture(scope="module")
def app() -> Iterator["wx.App"]:
    """One application object for the module; wx permits only one per process."""
    existing = wx.App.Get()
    created = None
    if existing is None:
        created = wx.App()
    yield existing or created
    if created is not None:
        created.Destroy()


@pytest.fixture
def shell(app: "wx.App") -> Iterator[object]:
    """A live shell in a shown frame, torn down whatever the test did.

    Built fresh per test rather than shared: the shell owns a theme
    subscription and a palette shortcut, and a test that switched views or
    rebuilt the ribbon would otherwise hand the next one a state it did not
    ask for.
    """
    from amulet_map_editor.api.studio.shell import StudioShell

    frame = wx.Frame(None, size=wx.Size(*FRAME_SIZE))
    try:
        panel = StudioShell(frame, frame)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(panel, 1, wx.EXPAND)
        frame.SetSizer(sizer)
        frame.Show()
        frame.Layout()
        _force_paint(frame)
        yield panel
    finally:
        frame.Destroy()
        wx.Yield()


# ----------------------------------------------------------------------
# the two views actually render
# ----------------------------------------------------------------------
def test_the_backstage_renders_a_non_uniform_client_area(shell):
    with _PaintTrap() as trap:
        shell.show_backstage("home")
        _force_paint(shell)
        colours = _distinct_colours(shell)
    assert trap.report("painting the backstage") == ""
    width, height = shell.GetClientSize()
    assert width > 0 and height > 0, f"the shell has no client area: {width}x{height}"
    assert colours >= MIN_VIEW_COLOURS, (
        f"the backstage rendered only {colours} distinct colours across "
        f"{width}x{height}; a blank panel renders one or two, so this is a view "
        "that is not drawing its content"
    )


def test_the_workspace_renders_a_non_uniform_client_area(shell):
    with _PaintTrap() as trap:
        shell.show_workspace()
        _force_paint(shell)
        colours = _distinct_colours(shell)
    assert trap.report("painting the workspace") == ""
    width, height = shell.GetClientSize()
    assert colours >= MIN_VIEW_COLOURS, (
        f"the workspace rendered only {colours} distinct colours across "
        f"{width}x{height}; the ribbon, navigator, viewport, and properties "
        "pane together render hundreds"
    )


def test_building_and_showing_the_shell_raises_nothing_on_the_event_loop(app):
    """The construction itself is the thing under test here, so it is inside
    the trap rather than behind the fixture that normally builds it."""
    from amulet_map_editor.api.studio.shell import StudioShell

    with _PaintTrap() as trap:
        frame = wx.Frame(None, size=wx.Size(*FRAME_SIZE))
        try:
            panel = StudioShell(frame, frame)
            sizer = wx.BoxSizer(wx.VERTICAL)
            sizer.Add(panel, 1, wx.EXPAND)
            frame.SetSizer(sizer)
            frame.Show()
            frame.Layout()
            _force_paint(frame)
            panel.show_workspace()
            _force_paint(frame)
            panel.show_backstage("home")
            _force_paint(frame)
        finally:
            frame.Destroy()
            wx.Yield()
    assert trap.report("building, showing, and switching the shell") == ""


# ----------------------------------------------------------------------
# every ribbon tab
# ----------------------------------------------------------------------
def test_every_ribbon_tab_switches_and_paints(shell):
    """All seventeen, one at a time, each forced to draw.

    A tab is rebuilt from scratch when it is selected, so a group definition
    that the widget cannot render is invisible until somebody looks at that one
    tab.  Seventeen switches is cheap; discovering the broken one from a user
    report is not.
    """
    shell.show_workspace()
    ribbon = shell.workspace.ribbon
    assert len(ribbon_defs.TAB_KEYS) == 17, ribbon_defs.TAB_KEYS

    blank: List[str] = []
    unbuilt: List[str] = []
    with _PaintTrap() as trap:
        for key in ribbon_defs.TAB_KEYS:
            ribbon.set_tab(key)
            shell.Layout()
            _force_paint(shell)
            assert (
                ribbon.active_tab == key
            ), f"selecting the {key!r} ribbon tab left {ribbon.active_tab!r} active"
            size = ribbon.panel.GetSize()
            expected = len(ribbon_defs.tab(key).groups)
            # Counting shown children rather than all of them, because a hidden
            # child stays in GetChildren() forever: the first version of this
            # check counted the whole list and therefore passed a panel on which
            # every single group had been hidden.
            built = sum(1 for child in ribbon.panel.GetChildren() if child.IsShown())
            if size.width <= 0 or size.height <= 0 or built < expected:
                unbuilt.append(
                    f"{key}: panel {size.width}x{size.height} with {built} of "
                    f"{expected} groups showing"
                )
                continue
            colours = _distinct_colours(ribbon.panel)
            if colours < MIN_RIBBON_COLOURS:
                blank.append(f"{key}: {colours} distinct colours")
    assert trap.report("walking every ribbon tab") == ""
    assert not unbuilt, "ribbon tabs whose command panel was never built: " + "; ".join(
        unbuilt
    )
    assert (
        not blank
    ), "ribbon tabs whose command panel rendered as good as blank: " + "; ".join(blank)


# ----------------------------------------------------------------------
# the registry seams
# ----------------------------------------------------------------------
def test_every_ribbon_button_resolves_to_a_real_surface_or_command():
    """A tile naming a key nobody registered is a button that does nothing.

    It costs no display and it is the exact breakage a rename produces, in the
    one direction no type checker looks: the key is a string on one side and a
    dictionary lookup on the other.
    """
    dangling: List[str] = []
    for definition in ribbon_defs.RIBBON_TABS:
        for group in definition.groups:
            for button in group.buttons:
                if button.surface and surfaces.surface(button.surface) is None:
                    dangling.append(
                        f"{definition.key}/{group.title}/{button.label} names the "
                        f"surface {button.surface!r}, which is not in the index"
                    )
                if button.command and commands.command(button.command) is None:
                    dangling.append(
                        f"{definition.key}/{group.title}/{button.label} names the "
                        f"command {button.command!r}, which is not registered"
                    )
    assert not dangling, "\n".join(dangling)


def test_every_ribbon_group_launcher_resolves_to_a_real_surface():
    dangling = [
        f"{definition.key}/{group.title} launches {group.launcher!r}, which is "
        "not in the surface index"
        for definition in ribbon_defs.RIBBON_TABS
        for group in definition.groups
        if group.launcher and surfaces.surface(group.launcher) is None
    ]
    assert not dangling, "\n".join(dangling)


def test_every_registered_spec_has_an_entry_in_the_surface_index():
    """A spec the index does not list is a window nothing can reach.

    The index is what the backstage, the palette, and every search read, so a
    surface missing from it exists in the code and nowhere a user can go.
    """
    missing = sorted(
        key for key in spec_registry.SPECS if surfaces.surface(key) is None
    )
    assert (
        not missing
    ), "specs with no Surface entry, so nothing can open them: " + ", ".join(missing)
    assert (
        not spec_registry.UNAVAILABLE_MODULES
    ), "spec families that failed to import: " + ", ".join(
        spec_registry.UNAVAILABLE_MODULES
    )
    assert (
        not surfaces.unrouted_keys()
    ), "indexed surfaces with neither a route nor a spec: " + ", ".join(
        surfaces.unrouted_keys()
    )


# ----------------------------------------------------------------------
# real surfaces open and draw
# ----------------------------------------------------------------------
@pytest.mark.parametrize(
    ("key", "why"), SAMPLE_SURFACES, ids=[key for key, _ in SAMPLE_SURFACES]
)
def test_a_representative_surface_opens_and_renders(shell, key: str, why: str):
    with _PaintTrap() as trap:
        window = surfaces.open_surface(shell, key)
        try:
            assert window is not None, (
                f"open_surface({key!r}) returned nothing, so the surface chosen "
                f"for {why} never opened"
            )
            window.Show()
            window.Layout()
            _force_paint(window)
            colours = _distinct_colours(window)
            collapsed = _collapsed_children(window)
            size = window.GetClientSize()
        finally:
            if window is not None:
                window.Close()
                wx.Yield()
    assert trap.report(f"opening and painting the {key!r} surface") == ""
    assert (
        size.width > 0 and size.height > 0
    ), f"the {key!r} surface opened at {size.width}x{size.height}"
    assert colours >= MIN_SURFACE_COLOURS, (
        f"the {key!r} surface, which was chosen for {why}, rendered only "
        f"{colours} distinct colours across {size.width}x{size.height}"
    )
    assert (
        not collapsed
    ), f"controls on the {key!r} surface are shown but have no area: " + "; ".join(
        collapsed
    )
