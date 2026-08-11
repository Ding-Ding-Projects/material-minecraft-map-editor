"""The hand-written census of every surface Amulet Studio must be able to open.

The list below is written out by hand on purpose.  A rule phrased as "every
surface in the index resolves" is satisfied by an index holding nothing, so it
would pass just as happily on the day somebody deleted a whole spec family.  The
enumeration is what turns a disappearance into a failure, and it is transcribed
from the design handoff's feature inventory rather than generated from the code
it is meant to check.

Deleting an entry to make this file pass is the one edit that defeats its
purpose: a surface that genuinely goes away should be removed from the design
inventory first, and from here as part of that same change.
"""

from __future__ import annotations

from amulet_map_editor.api.studio import specs, surfaces
from amulet_map_editor.api.studio.search import SearchState

#: Every surface, under the group heading the inventory files it beneath.
REQUIRED_SURFACES = {
    "Project shell": (
        "worldInfo",
        "about",
        "licenses",
        "loading",
        "convertProgress",
    ),
    "Editing": (
        "goto",
        "blockSelect",
        "biomeSelect",
        "versionSelect",
        "importChunks",
        "exportStructure",
        "operationOptions",
        # One key per stock operation.  They shared ``operationOptions``, which
        # made five tiles into one: every one of them started the Operation tool
        # and left its list on whatever sorted first.
        "operationClone",
        "operationFill",
        "operationReplace",
        "operationSetBiome",
        "operationWaterlog",
    ),
    "MCEdit2 tools": (
        "brushTool",
        "brushSettings",
        "floodFill",
        "cloneTool",
        "moveTool",
        "generateTool",
        "selectBlockTool",
        "selectEntityTool",
        "editChunkTool",
        "toolSettings",
        "findReplaceBlocks",
        "findReplaceCommands",
        "findReplaceNbt",
        "analyzeTool",
        "importMap",
    ),
    "Terrain": (
        "terrainBrush",
        "smooth",
        "flatten",
        "erosion",
        "noiseGen",
        "seaLevel",
        "regenerate",
        "surfacePaint",
    ),
    "Build": (
        "patternMask",
        "stackArray",
        "schematicLibrary",
        "waypoints",
        "portalBuilder",
        "railTunnel",
    ),
    "Entities and data": (
        "entityBrowser",
        "entityEdit",
        "removeEntities",
        "lootAudit",
        "nbtSearch",
        "signSearch",
        "commandFinder",
        "playerData",
        "levelDat",
        "gamerules",
        "scoreboard",
        "mapItems",
        "blockAudit",
    ),
    "NBT editor": (
        "nbt",
        "nbtLegacy",
    ),
    "Redstone and mechanics": (
        "redstoneTrace",
        "railNetwork",
        "portalLinker",
        "spawnPoints",
        "spawnAnalysis",
        "lightOverlay",
        "tickLoad",
    ),
    "Worldgen": (
        "structureLocator",
        "slimeChunks",
        "seedTools",
        "oreAudit",
        "caveMap",
        "worldBorder",
        "heightLimits",
        "forceLoaded",
    ),
    "Analysis": (
        "blockHistogram",
        "chunkInspector",
        "biomeMap",
        "relight",
        "worldDiff",
        "validateRepair",
        "measure",
        "layerSlice",
    ),
    "Panels and views": (
        "undoHistory",
        "inspector",
        "pendingImports",
        "playerPanel",
        "inventoryEditor",
        "itemTypeList",
        "configureBlocks",
        "libraryPanel",
        "renderLayers",
        "viewControls",
        "fourUpView",
        "cutawayView",
        "workPlane",
        "minecraftInstalls",
        "pluginsDialog",
        "history",
        "logView",
        "profiler",
        "pythonConsole",
        "errorReport",
    ),
    "Automation": (
        "scriptConsole",
        "batchQueue",
        "macroRecorder",
    ),
    "Settings": (
        "prefs",
        "presets",
        "elementAppearance",
        "controls",
        "languageSelect",
        "narrator",
        "schoolUnlock",
        "externalEditor",
        "tabManager",
        "confirm",
    ),
    "Global": (
        "palette",
        "regex",
        "docs",
        "changelog",
        "notifications",
        "update",
        "dimsum",
        "memory",
    ),
}

#: The two surfaces the spec renderer cannot express, and which therefore have
#: hand-built windows of their own.
HAND_BUILT_SURFACES = ("nbt", "memory")

#: Surfaces whose real implementation predates this shell.  They are routed to
#: the dialog that already exists rather than re-described as a spec, so the
#: index must keep a route for each one.
LEGACY_ROUTED_SURFACES = (
    "prefs",
    "history",
    "notifications",
    "changelog",
    "docs",
    "tabManager",
    "licenses",
    "languageSelect",
    "elementAppearance",
)


def test_every_required_surface_is_present_under_its_own_group():
    indexed = {entry.key: entry for entry in surfaces.SURFACES}
    missing = []
    misfiled = []
    for group_name, members in REQUIRED_SURFACES.items():
        for key in members:
            entry = indexed.get(key)
            if entry is None:
                missing.append(f"{group_name}/{key}")
            elif entry.group != group_name:
                misfiled.append(f"{key}: filed under {entry.group!r}")
    assert not missing, f"surfaces have gone missing from the index: {missing}"
    assert not misfiled, misfiled


def test_the_index_holds_nothing_the_inventory_does_not_name():
    """An unlisted surface is either undocumented or a leftover; both matter."""
    expected = {key for members in REQUIRED_SURFACES.values() for key in members}
    extra = sorted(set(surfaces.keys()) - expected)
    assert not extra, (
        "these surfaces are in the index but not in the documented inventory: "
        f"{extra}"
    )


def test_the_group_order_is_the_inventorys_order():
    assert surfaces.SURFACE_GROUPS == tuple(REQUIRED_SURFACES)


def test_no_surface_key_is_indexed_twice():
    keys = surfaces.keys()
    assert len(keys) == len(set(keys))


def test_every_surface_carries_a_label_and_a_hint():
    problems = []
    for entry in surfaces.SURFACES:
        if not entry.label.strip():
            problems.append(f"{entry.key}: no label")
        if not entry.hint.strip():
            problems.append(f"{entry.key}: no hint")
        if entry.label.strip() == entry.key:
            problems.append(f"{entry.key}: listed under its own key, not a name")
        if entry.key not in entry.accessible_name() and not entry.accessible_name():
            problems.append(f"{entry.key}: no accessible name")
    assert not problems, problems


def test_every_indexed_surface_can_actually_open_something():
    """A button that reports it cannot open anything is a broken button."""
    assert surfaces.unrouted_keys() == ()


def test_the_hand_built_and_legacy_surfaces_are_still_routed_rather_than_specs():
    for key in HAND_BUILT_SURFACES:
        assert surfaces.surface(key) is not None, key
        assert specs.get(key) is None, f"{key} should be a hand-built window"
    for key in LEGACY_ROUTED_SURFACES:
        assert surfaces.surface(key) is not None, key
    assert set(surfaces.unrouted_keys()).isdisjoint(LEGACY_ROUTED_SURFACES)


def test_surface_search_is_plain_text_by_default_and_finds_by_name():
    state = SearchState(query="nbt")
    found = {entry.key for entry in surfaces.search(state)}
    assert "nbt" in found
    assert "nbtSearch" in found
    assert len(found) < len(surfaces.SURFACES)


def test_surface_search_reads_a_regex_only_when_it_is_asked_to():
    literal = SearchState(query="rail.*tunnel")
    assert surfaces.search(literal) == ()
    pattern = SearchState(query="rail.*tunnel", regex=True)
    assert {entry.key for entry in surfaces.search(pattern)} == {"railTunnel"}


def test_an_unknown_key_is_answered_with_nothing_rather_than_a_guess():
    assert surfaces.surface("no-such-surface") is None
    assert surfaces.surface("") is None
    assert surfaces.surface(None) is None


def test_every_group_actually_contains_something():
    empty = [name for name in surfaces.SURFACE_GROUPS if not surfaces.group(name)]
    assert not empty, empty
