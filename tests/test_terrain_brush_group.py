"""The Terrain tab offers no brush settings, because this build has no brush.

The Terrain ribbon carried a group titled **Brush**: four outlined text boxes
holding ``Radius 12``, ``Strength 0.45``, ``Falloff smooth`` and ``Height 98``.
Every one of them was enabled, editable, on screen, and read by nobody.  Driven
through a real ``RibbonBar`` before the removal, typing ``99`` into Radius did
exactly one thing -- it put the string ``"99"`` in ``RibbonBar.field_values`` --
and that dictionary has a single reader anywhere in the application:
``_GroupPanel.__init__``, which seeds the box with whatever it last stored.  No
command was raised, no surface opened, and nothing in the shell, the selection,
the viewport or any tool ever asked what the numbers were.

What makes this worse than an ordinary inert control is what the four values
claimed to configure.  ``editor_tools`` records that this build **has no brush
tool at all** -- the editor ships Select, Paste, Operation, Import, Export and
Chunk, and none of them paints a shape along the pointer -- so the group was
four working-looking boxes offering to tune a feature the application does not
have.  A control that configures a missing feature is a promise, and a promise
is worse than a blank space, because a blank space never had to be believed.

So the group is gone rather than greyed out.  A static preview would have kept
ribbon width to advertise something unbuilt, and the two surfaces the group
touched were never reachable only through it: ``brushSettings`` is still the
Tools tab's **Paint > Brush** tile, and ``terrainBrush`` is still the Sculpt
group's own dialog launcher on this very tab.  Removing the group orphaned
nothing, and the assertions below say so rather than assuming it.

**Why the premise is asserted rather than assumed.**  The first test here
checks that the brush tool is *still* missing.  If somebody builds one, that
test fails, and the failure is the right one to get: it says "you now have a
brush, so decide deliberately whether its settings belong on the ribbon", which
is a conversation, not a regression.  Freezing the removal forever would have
been the easier assertion and the wrong one.

**Scope.**  This module asserts the Terrain tab.  The Selection tab's
``Coordinates`` grid and the Chunks tab's ``Draw range`` grid have the same
unread-value shape and are a separate lane's work; they are deliberately not
asserted here, because a rule written to fail on somebody else's in-flight
change tells you nothing about this one.  The general rule -- that
``ribbon_defs.validate()`` should refuse a field grid nothing reads, the way it
already refuses a dropdown that raises no command -- needs a reader declaration
on :class:`~amulet_map_editor.api.studio.ribbon_defs.RibbonField` that all three
groups can agree on, and belongs in the change that settles the last of them.
"""

from __future__ import annotations

from typing import Any, List, Tuple

import pytest

from amulet_map_editor.api.studio import editor_tools, ribbon_defs

#: Off-screen, so a run on a visible desktop never throws a window at anybody.
OFFSCREEN = (-32000, -32000)


# ---------------------------------------------------------------------------
# the premise: there is no brush tool for these settings to configure
# ---------------------------------------------------------------------------
def test_this_build_still_has_no_brush_tool() -> None:
    """The reason the group went, stated where a future brush will trip over it.

    ``editor_tools`` is the one place that knows which Studio surface means
    which real editor tool, and it lists ``brushTool`` as unavailable with the
    absence written out.  That entry is the whole justification for deleting
    four controls, so it is checked rather than remembered.
    """
    entry = editor_tools.bridge("brushTool")
    assert entry is not None, "the brushTool bridge has been renamed or removed"
    assert not entry.available, (
        "this build now has a brush tool, so the Terrain tab's brush settings "
        "were removed on a premise that no longer holds -- decide deliberately "
        "whether they come back, wired to it this time"
    )
    assert entry.missing.strip(), (
        "brushTool is unavailable but says nothing about what is missing, so a "
        "caller pressing it cannot explain the refusal"
    )


# ---------------------------------------------------------------------------
# the definition
# ---------------------------------------------------------------------------
def test_the_terrain_tab_is_still_built_from_real_groups() -> None:
    """Guard the guard: every assertion below passes on a tab that vanished.

    A rule about what the Terrain tab must not contain is satisfied completely
    by there being no Terrain tab, which is the shape of check this repository
    has already been bitten by.  So the floor is stated first.
    """
    tab = ribbon_defs.tab("terrain")
    assert tab is not None, "the Terrain ribbon tab is gone"
    assert len(tab.groups) >= 3, [group.title for group in tab.groups]
    assert tab.buttons, "the Terrain tab has no command tiles at all"


def test_no_group_on_the_terrain_tab_draws_a_field_grid() -> None:
    """Nothing on this tab reads a typed value, so nothing on it offers a box."""
    tab = ribbon_defs.tab("terrain")
    grids = [
        f"{group.title}: " + ", ".join(f"{f.label}={f.value!r}" for f in group.fields)
        for group in tab.groups
        if group.has_fields
    ]
    assert (
        not grids
    ), "the Terrain tab draws editable boxes whose values nothing reads: " + "; ".join(
        grids
    )


def test_the_brush_windows_are_still_reachable() -> None:
    """Removing the group must not have been the only route to a surface.

    ``brushSettings`` was the removed group's dialog launcher and ``terrainBrush``
    is what its neighbours sculpt with.  Both are in the surface index, so
    losing the last ribbon route to one would leave an indexed window that the
    ribbon can no longer open -- a quieter defect than the one being fixed.
    """
    reachable = set()
    for tab in ribbon_defs.RIBBON_TABS:
        for group in tab.groups:
            if group.launcher:
                reachable.add(group.launcher)
            for button in group.buttons:
                if button.surface:
                    reachable.add(button.surface)
    assert "brushSettings" in reachable, (
        "no ribbon tile or launcher opens brushSettings any more, so the brush "
        "settings window became unreachable when the Terrain group went"
    )
    assert "terrainBrush" in reachable, "terrainBrush is no longer opened by the ribbon"


# ---------------------------------------------------------------------------
# the widget, driven
# ---------------------------------------------------------------------------
def _boxes(window: Any) -> List[Tuple[str, Any]]:
    """Return every text box under ``window`` a user could actually type into.

    ``IsShown`` answers ``True`` for a control inside a hidden parent, so it
    would report the boxes on all seventeen tabs at once; ``IsShownOnScreen``
    is the question being asked here -- can somebody see this and click it.
    """
    import wx

    found: List[Tuple[str, Any]] = []
    stack = list(window.GetChildren())
    while stack:
        child = stack.pop()
        stack.extend(child.GetChildren())
        if isinstance(child, wx.TextCtrl) and child.IsShownOnScreen():
            found.append((child.GetName(), child))
    return found


@pytest.fixture(scope="module")
def app() -> Any:
    """A live ``wx.App`` on an isolated profile, so a run touches no settings."""
    import os
    import tempfile

    wx = pytest.importorskip("wx", reason="wxPython is not installed")
    os.environ.setdefault("CONFIG_DIR", tempfile.mkdtemp(prefix="amulet-terrain-"))
    # Reuse a live ``wx.App`` when the session already has one, rather than
    # unconditionally creating a second instance -- that silently orphans
    # the existing app and, once garbage-collected, can corrupt wxPython's
    # SIP class table for platform-native widgets such as
    # ``wx.PopupTransientWindow`` in every module that runs afterward.
    yield wx.App.Get() or wx.App()


@pytest.fixture()
def frame(app: Any) -> Any:
    """An off-screen frame, shown, so ``IsShownOnScreen`` can mean anything."""
    import wx

    window = wx.Frame(None, size=(1600, 600), pos=OFFSCREEN)
    window.Show()
    wx.Yield()
    try:
        yield window
    finally:
        window.Destroy()


def test_the_box_walker_finds_a_box_when_one_is_there(frame: Any) -> None:
    """Prove the walker can fail before believing it when it passes.

    The assertion this module rests on is "the walker found nothing", and a
    walker that can never find anything satisfies it on every tab of every
    build forever.  So it is pointed at one field built here, of exactly the
    class the removed group used.
    """
    import wx

    from amulet_map_editor.api.studio import widgets

    field = widgets.OutlinedField(frame, "Radius", "12")
    frame.Layout()
    wx.Yield()
    names = [name for name, _ctrl in _boxes(frame)]
    assert names == ["Radius"], f"the walker saw {names} where one Radius box was built"
    field.Destroy()


def test_the_terrain_ribbon_shows_no_box_to_type_into(frame: Any) -> None:
    """Switch a real ribbon to Terrain and look at what a user can type into.

    The command panel is walked rather than the whole bar, because the bar's
    own per-tab search field is a text box and a live one.  Everything inside
    the panel is a group's control.
    """
    import wx

    from amulet_map_editor.api.studio import ribbon

    commands: List[str] = []
    surfaces: List[str] = []
    bar = ribbon.RibbonBar(
        frame, on_command=commands.append, on_surface=surfaces.append
    )
    bar.set_tab("terrain")
    frame.Layout()
    wx.Yield()

    assert bar.active_tab == "terrain", bar.active_tab
    shown = [panel for panel in bar._groups if panel.IsShownOnScreen()]
    assert len(shown) >= 3, (
        "the Terrain command panel built "
        f"{len(shown)} visible groups, so the walk below covers nothing"
    )
    assert any(panel.tiles for panel in shown), "no Terrain group built a command tile"

    names = [name for name, _ctrl in _boxes(bar.panel)]
    assert not names, (
        "the Terrain ribbon offers boxes to type into, and nothing reads what "
        f"is typed: {names}"
    )


def test_the_ribbon_holds_no_value_for_a_brush_it_cannot_configure(frame: Any) -> None:
    """The stored-value map is seeded from the definition, so it says so too.

    ``field_values`` is filled for every field on every tab when the bar is
    constructed, tab switching or not.  A ``Brush`` entry in it means the group
    came back somewhere, even on a tab nobody has looked at yet.
    """
    from amulet_map_editor.api.studio import ribbon

    bar = ribbon.RibbonBar(frame)
    brush = sorted(key for key in bar.field_values if key[0] == "Brush")
    assert not brush, f"the ribbon still stores brush settings nothing reads: {brush}"
