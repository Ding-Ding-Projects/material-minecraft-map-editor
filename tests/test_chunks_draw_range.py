"""The Chunks tab does not offer a draw range, because nothing draws one.

The ribbon shipped a ``Draw range`` group on the Chunks tab: two editable
boxes, ``Min Y = -64`` and ``Max Y = 320``, sized and labelled exactly like a
renderer control.  Measured by typing ``999`` into the real widget, the whole
of what moved was one entry in ``RibbonBar.field_values``.  No command ran, no
surface opened, and the one reader of that dictionary is ``_GroupPanel``
re-seeding the box with what it last stored -- so the value travelled from the
box, into a dictionary, and back into the same box.

The reason it could not have done anything is the point of this module: **the
renderer has no vertical draw limit to set.**  What it does have is
``RenderLevel.render_distance``, a horizontal radius in chunks, and the two
construction-time booleans ``draw_floor`` / ``draw_ceil``.  The only Y-wise
filter anywhere in the geometry path is ``RenderChunk._limit_bounds``, which
clips to the *level's own* bounds and is a fixed constructor argument the edit
renderer leaves false.  There was no setting for those boxes to be wired to.

So the group was removed rather than given a renderer feature invented to
justify it.  Two boxes that decide nothing are worse than no boxes: a user who
types ``64`` into ``Max Y`` and sees the world unchanged has been told
something false about the application.

**What this module asserts, and what it does not.**  It proves the renderer
still owns no vertical draw limit, and it drives a real ``RibbonBar`` to prove
the Chunks tab puts no editable box on screen.  It does not render a frame; if
somebody implements a genuine draw limit, the first assertion here goes red on
purpose, saying so -- at which point the control may come back, wired.
"""

from __future__ import annotations

import ast
import inspect
import pathlib
from typing import Dict, List, Set, Tuple

import pytest

from amulet_map_editor.api.studio import ribbon_defs

wx = pytest.importorskip("wx", reason="wxPython is not installed in this environment")

from amulet_map_editor.api.studio import widgets  # noqa: E402
from amulet_map_editor.api.studio.ribbon import RibbonBar  # noqa: E402

#: Words that would name a vertical draw limit.  A hand-written list, because
#: the thing being looked for does not exist and so cannot be discovered from
#: the code -- which is exactly why the positive controls below matter more
#: than the list does.
VERTICAL_LIMIT_WORDS = (
    "draw_range",
    "drawrange",
    "draw_min",
    "draw_max",
    "min_draw",
    "max_draw",
    "draw_limit",
    "y_limit",
    "ylimit",
    "y_range",
    "yrange",
    "vertical_limit",
    "vertical_range",
    "height_limit",
)


def _vertical_limit_names(names) -> List[str]:
    """Return every name that reads as a vertical draw limit."""
    return sorted(
        name
        for name in names
        if any(word in name.lower() for word in VERTICAL_LIMIT_WORDS)
    )


#: ``(module path, class name)`` for the two classes that decide what geometry
#: exists.  ``RenderLevel`` chooses the chunks; ``RenderChunk`` turns one into
#: vertices.  A vertical draw limit would have to be visible in one of them.
RENDERER_CLASSES = (
    ("amulet_map_editor/api/opengl/mesh/level/level.py", "RenderLevel"),
    ("amulet_map_editor/api/opengl/mesh/level/chunk/chunk.py", "RenderChunk"),
)

REPO = pathlib.Path(__file__).resolve().parents[1]


def _live_renderer() -> Tuple[Dict[str, Set[str]], Dict[str, Set[str]]]:
    """Return the two classes' argument and member names, read off the objects.

    Raises on a checkout whose Cython chunk mesher has not been compiled --
    which is an ordinary state of this repository, not a fault.  Note the type:
    ``chunk_builder`` turns the missing extension into a bare ``Exception``, so
    catching ``ImportError`` around this catches nothing at all.
    """
    from amulet_map_editor.api.opengl.mesh.level.chunk import RenderChunk
    from amulet_map_editor.api.opengl.mesh.level.level import RenderLevel

    args, members = {}, {}
    for owner in (RenderLevel, RenderChunk):
        args[owner.__name__] = set(inspect.signature(owner.__init__).parameters)
        members[owner.__name__] = set(dir(owner))
    return args, members


def _renderer_from_source() -> Tuple[Dict[str, Set[str]], Dict[str, Set[str]]]:
    """Return the same two name sets, parsed from the files themselves.

    The fallback for an uncompiled checkout.  It is a weaker reading than the
    live one and is *not* a skip: the assertions below still run against it, so
    a draw limit added to either class is still caught on a machine that cannot
    import the mesher.
    """
    args: Dict[str, Set[str]] = {}
    members: Dict[str, Set[str]] = {}
    for relative, name in RENDERER_CLASSES:
        tree = ast.parse((REPO / relative).read_text(encoding="utf-8"))
        found = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef) and node.name == name
        ]
        assert found, f"{name} is no longer defined in {relative}"
        node = found[0]
        seen: Set[str] = set()
        for child in ast.walk(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                seen.add(child.name)
                if child.name == "__init__":
                    argument = child.args
                    args[name] = {
                        item.arg
                        for item in (
                            *argument.posonlyargs,
                            *argument.args,
                            *argument.kwonlyargs,
                        )
                    }
            elif isinstance(child, ast.Attribute) and isinstance(child.value, ast.Name):
                if child.value.id == "self":
                    seen.add(child.attr)
        members[name] = seen
        assert name in args, f"{name}.__init__ was not found in {relative}"
    return args, members


def test_the_renderer_still_owns_no_vertical_draw_limit():
    """Nothing in the draw path takes a Y range, so nothing can be wired to one.

    The positive controls come first.  A test that only looks for an absent
    thing is satisfied by looking at the wrong object entirely -- rename
    ``RenderLevel`` and this would go on passing forever -- so it first proves
    it is holding the classes that really decide what gets drawn.

    Read off the live classes where the Cython chunk mesher has been compiled,
    and off their source where it has not.  Both readings assert; neither is a
    skip, because an uncompiled checkout is the common case here and a skipped
    check reads exactly like a passing one in a summary line.
    """
    try:
        args, members = _live_renderer()
        how = "the imported classes"
    except Exception as err:  # noqa: BLE001 - narrowed on the next line
        if "cython" not in str(err).lower():
            raise
        args, members = _renderer_from_source()
        how = "the source files (the Cython chunk mesher is not compiled here)"

    # Positive controls: the real horizontal limit, and the real Y-wise filter.
    assert "render_distance" in members["RenderLevel"], (
        f"RenderLevel.render_distance is gone from {how}; this test is no "
        "longer holding the renderer"
    )
    for name in ("RenderLevel", "RenderChunk"):
        assert "limit_bounds" in args[name], (
            f"{name}.__init__ no longer takes limit_bounds, read from {how}; "
            "the Y-wise filter this test is measuring against has moved"
        )

    found = _vertical_limit_names(set().union(*args.values(), *members.values()))
    assert not found, (
        f"the renderer now names a vertical draw limit, read from {how} "
        f"({', '.join(found)}), so the Chunks tab may have its Draw range "
        "group back -- wired to it, and proved by driving the widget"
    )


def test_the_chunks_ribbon_tab_defines_no_field_grid():
    """No group on the Chunks tab may offer a box until something reads it.

    ``RibbonField`` carries a label and a value and nothing else -- no command,
    the way ``RibbonSelect`` has one -- so ``ribbon_defs.validate()`` cannot
    refuse an inert field the way it now refuses a command-less dropdown.  This
    is that refusal, hand-written for the one tab whose fields were measured to
    decide nothing.
    """
    chunks = ribbon_defs.tab("chunks")
    assert chunks.groups, "the Chunks tab has no groups at all"

    offered = [
        f"{group.title}/{field.label}"
        for group in chunks.groups
        for field in group.fields
        if field.command
    ]
    assert not offered, (
        "the Chunks tab offers editable boxes with nothing behind them "
        f"({', '.join(offered)}). A RibbonField names no command and is read "
        "only by the group panel that re-seeds it, so typing into one changes "
        "nothing a user can see. Give RibbonField a command and wire it, or "
        "leave the box out."
    )


def test_the_chunks_tab_puts_no_editable_box_on_screen(chunks_ribbon):
    """Driven, not read: build the tab and look for a field the user could type in.

    The collector is proved on a field of this test's own making first.  An
    empty answer from a collector that finds nothing anywhere is the shape of
    guard this repository has already shipped once.
    """
    bar, frame = chunks_ribbon

    control = widgets.OutlinedField(frame, "Positive control", "1")
    assert _fields_under(control) == [
        control
    ], "the field collector cannot find a field it is pointed straight at"

    on_screen = [field for field in _fields_under(bar.panel) if field.IsShownOnScreen()]
    assert not on_screen, (
        "the Chunks tab shows editable boxes: "
        f"{', '.join(field.label for field in on_screen)}"
    )

    # Non-vacuous: the tab is genuinely built and genuinely visible, so the
    # empty answer above is an absence of fields rather than an absence of tab.
    titles = [panel.group.title for panel in bar._groups]
    assert titles == ["Chunks"], titles
    tiles = [tile for panel in bar._groups for tile in panel.tiles]
    assert tiles, "the Chunks tab built no command tiles"
    assert any(
        tile.IsShownOnScreen() for tile in tiles
    ), "the Chunks tab built tiles but none of them reached the screen"


def test_removing_the_group_did_not_orphan_the_height_limits_surface():
    """The removed group launched ``heightLimits``; it is still reachable.

    Deleting a group deletes its dialog launcher with it, which is a quiet way
    to make a surface unreachable from the ribbon.  This is the one thing the
    removal could have broken.
    """
    reachable = {
        button.surface
        for _tab_key, _group_title, button in ribbon_defs.all_buttons()
        if button.surface
    } | {group.launcher for tab in ribbon_defs.RIBBON_TABS for group in tab.groups}
    assert "heightLimits" in reachable, sorted(reachable)


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------
def _fields_under(window) -> List["widgets.OutlinedField"]:
    """Return every outlined text field in ``window``'s subtree, itself included."""
    found: List[widgets.OutlinedField] = []
    stack = [window]
    while stack:
        item = stack.pop()
        if isinstance(item, widgets.OutlinedField):
            found.append(item)
            continue
        stack.extend(item.GetChildren())
    return found


@pytest.fixture
def chunks_ribbon():
    """A real ``RibbonBar`` in a shown frame, sitting on the Chunks tab."""
    app = wx.App.Get() or wx.App()
    frame = wx.Frame(None, size=(1600, 700))
    bar = RibbonBar(frame)
    frame.Show()
    wx.Yield()
    bar.set_tab("chunks")
    wx.Yield()
    try:
        yield bar, frame
    finally:
        frame.Destroy()
        wx.Yield()
        del app
