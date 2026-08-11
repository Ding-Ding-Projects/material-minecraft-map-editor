"""Which operation each Operations tile asks for, with no editor to ask it of.

``tests/test_editor_operations_runtime.py`` proves the real thing: a real world
in a real frame, five tiles pressed, the operation read back off the wx.Choice
the user is looking at.  It is also the module that cannot run without a world,
a GPU context and a machine not already running another copy of itself, and
when any of those is missing it skips all of itself -- which in a summary line
looks exactly like passing all of itself.  A run on such a host verified
nothing about the defect these tiles were rewired for, and said so only in grey.

So the wiring is asserted here as well, where nothing has to start: the tile the
user presses, the surface key it names, and the operation that key asks the
Operation tool to select.  The table below is written out by hand rather than
read from :data:`editor_tools.STOCK_OPERATIONS`, because a table generated from
the thing under test agrees with it by construction and would go on agreeing
with it through the exact regression this module exists for -- five tiles
collapsing back onto one key, or five keys collapsing back onto one operation.

What this module cannot see is whether pressing a tile *does* any of it.  That
is the runtime module's job, and neither of them is a substitute for the other.
"""

from __future__ import annotations

from typing import Tuple

from amulet_map_editor.api.studio import editor_tools, ribbon_defs, surfaces

#: The tile label, the surface key it names, and the operation plugin's own
#: ``export["name"]`` that key must ask for.  Three columns, written by hand.
TILES: Tuple[Tuple[str, str, str], ...] = (
    ("Clone", "operationClone", "Clone"),
    ("Fill", "operationFill", "Fill"),
    ("Replace", "operationReplace", "Replace"),
    ("Set biome", "operationSetBiome", "Set Biome"),
    ("Waterlog", "operationWaterlog", "Waterlog"),
)

#: The group's own launcher, which is the whole unfiltered chooser and is
#: deliberately *not* one of the five: it must keep starting the tool on
#: whatever it was last showing.
LAUNCHER = "operationOptions"


def _stock_group():
    tab = ribbon_defs.tab("operations")
    assert tab is not None, "the ribbon offers no Operations tab at all"
    for group in tab.groups:
        if group.title == "Stock operations":
            return group
    raise AssertionError(
        "the Operations tab has no 'Stock operations' group; its groups are "
        f"{[group.title for group in tab.groups]}"
    )


def test_the_operations_tab_offers_the_five_stock_tiles() -> None:
    """Five tiles, in this order, naming these five keys.

    Without this the assertions below are satisfied by a ribbon that offers no
    stock operations at all, which is a rule about a thing done wrongly passing
    on the thing not being done.
    """
    group = _stock_group()
    labels = [button.label for button in group.buttons]
    assert labels == [label for label, _key, _operation in TILES], (
        "the Operations tab should offer Clone, Fill, Replace, Set biome and "
        f"Waterlog as its stock operations; it offers {labels}"
    )
    keys = [button.surface for button in group.buttons]
    assert keys == [key for _label, key, _operation in TILES], (
        "each stock-operation tile names its own surface key; the tiles name " f"{keys}"
    )


def test_no_two_stock_tiles_lead_to_the_same_place() -> None:
    """The defect, stated directly: five tiles that meant one thing.

    All five named ``operationOptions``, so all five started the Operation tool
    and left its list on whatever sorted first -- which was Clone, which looked
    correct while standing in for its four siblings.
    """
    group = _stock_group()
    keys = [button.surface for button in group.buttons]
    assert len(set(keys)) == len(keys), (
        "the stock-operation tiles share a surface key, so pressing one of "
        f"them cannot mean anything different from pressing another: {keys}"
    )
    operations = [getattr(editor_tools.bridge(key), "operation", "") for key in keys]
    assert len(set(operations)) == len(operations), (
        "two stock-operation tiles ask for the same operation, so one of them "
        f"opens something other than what it says: {dict(zip(keys, operations))}"
    )
    assert "" not in operations, (
        "a stock-operation tile asks for no operation in particular, which is "
        "how the Operation tool ends up on whichever entry sorts first: "
        f"{dict(zip(keys, operations))}"
    )


def test_each_tile_asks_the_operation_tool_for_its_own_operation() -> None:
    """Key by key: the Operation tool, and the operation named on the tile."""
    problems = []
    for label, key, operation in TILES:
        entry = editor_tools.bridge(key)
        if entry is None:
            problems.append(f"{key}: no editor-tool bridge, so {label} opens nothing")
            continue
        if entry.tool != "Operation":
            problems.append(
                f"{key}: starts the {entry.tool!r} tool rather than 'Operation'"
            )
        if entry.operation != operation:
            problems.append(
                f"{key}: asks for {entry.operation!r} rather than {operation!r}"
            )
    assert not problems, "; ".join(problems)


def test_the_group_launcher_still_opens_the_chooser_itself() -> None:
    """The launcher is the unfiltered list, and must not name an operation.

    A launcher that acquired one would silently become a sixth tile, and the
    one route to the operations these five do not cover would be gone.
    """
    group = _stock_group()
    assert group.launcher == LAUNCHER, (
        "the Stock operations group's launcher should open the whole operation "
        f"chooser ({LAUNCHER!r}); it opens {group.launcher!r}"
    )
    entry = editor_tools.bridge(LAUNCHER)
    assert entry is not None, f"{LAUNCHER} has no editor-tool bridge"
    assert (
        entry.tool == "Operation"
    ), f"{LAUNCHER} should start the Operation tool and starts {entry.tool!r}"
    assert entry.operation == "", (
        f"{LAUNCHER} names the {entry.operation!r} operation, so the one tile "
        "that was meant to leave the choice to the user has stopped doing that"
    )


def test_each_key_is_routed_rather_than_rendered_as_a_description() -> None:
    """A stock operation is a tool, not a page describing one.

    An unrouted key falls through to the spec renderer, which would answer a
    tile press with a window describing the operation instead of selecting it.
    """
    unrouted = set(surfaces.unrouted_keys())
    stranded = [key for _label, key, _operation in TILES if key in unrouted]
    assert not stranded, (
        "these stock-operation keys are not routed to the editor, so pressing "
        f"their tiles opens a description instead of the tool: {stranded}"
    )


def test_the_hint_on_each_tile_names_its_own_operation() -> None:
    """The copy under the tile says which operation, and says it correctly.

    It also deliberately does not promise that the Run control is on screen.
    Replace stacks two block pickers in a scrolling panel, so in a 1500x950
    window its Run button starts 557 px below the bottom edge and the user
    scrolls to it -- a promise the tile cannot keep, measured in
    ``tests/test_editor_operations_runtime.py``.
    """
    problems = []
    for label, key, operation in TILES:
        entry = surfaces.surface(key)
        if entry is None:
            problems.append(f"{key}: not in the surface index at all")
            continue
        hint = entry.hint
        if operation.casefold() not in hint.casefold():
            problems.append(f"{key}: the hint {hint!r} does not name {operation!r}")
        if "ready to run" in hint.casefold():
            problems.append(
                f"{key}: the hint {hint!r} promises the operation is ready to "
                "run, which is not true of an operation whose Run control is "
                "below the fold of its own panel"
            )
        if label.casefold() not in entry.label.casefold():
            problems.append(
                f"{key}: the label {entry.label!r} does not name the {label!r} tile"
            )
    assert not problems, "; ".join(problems)
