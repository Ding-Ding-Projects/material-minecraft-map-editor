"""Every window, dialog, tool, and pane the Studio can open, in one index.

The backstage's "All surfaces" page, the command palette, the ribbon, and every
context menu all name a surface by key and let this module decide what actually
opens.  Three kinds of thing live behind one key:

* a **declarative** surface, described by a :class:`~amulet_map_editor.api.studio.spec.Spec`
  and rendered by :mod:`amulet_map_editor.api.studio.spec_dialog`;
* a **hand-built** Studio window the spec renderer cannot express -- the NBT
  editor and the Memory Console;
* a **legacy** dialog that already existed before this shell and is still the
  real implementation -- preferences, the notification history, the changelog,
  the documentation browser, the tab manager, the licence list.

Routing them here rather than at each call site means a caller never has to know
which of the three it is asking for, and a surface can move from a spec to a
hand-built window without a single button changing.

The module carries no wxPython at import time: every dialog is imported inside
the function that opens it, so the index itself can be read, searched, and
asserted on without a display.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from amulet_map_editor.api.studio import commands, ribbon_defs
from amulet_map_editor.api.studio import specs as spec_registry
from amulet_map_editor.api.studio.search import SearchState
from amulet_map_editor.api.studio.spec import Action, Row, Spec, sec

log = logging.getLogger(__name__)

__all__ = [
    "SURFACES",
    "SURFACE_GROUPS",
    "Surface",
    "group",
    "keys",
    "open_surface",
    "search",
    "surface",
    "unrouted_keys",
]


@dataclass(frozen=True)
class Surface:
    """One openable surface, as every index and search shows it."""

    key: str
    label: str
    hint: str
    group: str
    accel: str = ""

    def search_text(self) -> str:
        """Return every word a surface search should find this by."""
        return " ".join(
            part
            for part in (self.label, self.hint, self.group, self.accel, self.key)
            if part
        )

    def accessible_name(self) -> str:
        """Return the screen-reader name for a control that opens this."""
        parts = [self.label, self.group]
        if self.accel:
            parts.append(self.accel)
        return " — ".join(part for part in parts if part)


#: The group headings, in the order the backstage and the palette show them.
#: They are the design's own feature inventory, so a reader who has seen the
#: documentation finds a surface where that document filed it.
SURFACE_GROUPS: Tuple[str, ...] = (
    "Project shell",
    "Editing",
    "MCEdit2 tools",
    "Terrain",
    "Build",
    "Entities and data",
    "NBT editor",
    "Redstone and mechanics",
    "Worldgen",
    "Analysis",
    "Panels and views",
    "Automation",
    "Settings",
    "Global",
)

#: The group each surface belongs to, and the order it appears within it.
_GROUP_MEMBERS: Mapping[str, Tuple[str, ...]] = MappingProxyType(
    {
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
            "undoHistory",
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
)

#: The group a surface falls into when nothing above claims it.  A spec added
#: to :mod:`amulet_map_editor.api.studio.specs` without a line here is still
#: openable rather than invisible, and the omission is logged rather than
#: silently absorbed.
_FALLBACK_GROUP = "Panels and views"

#: The name every index, palette row, and search result lists a surface
#: under, transcribed from the design's own feature inventory.  It is not
#: always the dialog's own title: the block picker's window is headed
#: "Select block" while the inventory files it as "Block picker", and an
#: index row reading "Har gow · 蝦餃" would tell nobody what opens.  Writing
#: every label out here keeps the index reading as the design wrote it
#: rather than following a spec title as it is reworded.
_LABELS: Mapping[str, str] = MappingProxyType(
    {
        "about": "About",
        "analyzeTool": "Analyze",
        "batchQueue": "Batch queue",
        "biomeMap": "Biome map",
        "biomeSelect": "Biome picker",
        "blockAudit": "Block state audit",
        "blockHistogram": "Block histogram",
        "blockSelect": "Block picker",
        "brushSettings": "Brush",
        "brushTool": "Shape brush",
        "caveMap": "Cave coverage",
        "changelog": "Release notes",
        "chunkInspector": "Chunk inspector",
        "cloneTool": "Clone",
        "commandFinder": "Command blocks",
        "configureBlocks": "Configure blocks",
        "confirm": "Destructive action gate",
        "controls": "Key configuration",
        "convertProgress": "Conversion progress",
        "cutawayView": "Cutaway",
        "dimsum": "Dim-sum surprise",
        "docs": "Documentation",
        "editChunkTool": "Edit chunk",
        "elementAppearance": "Element appearance",
        "entityBrowser": "Entity browser",
        "entityEdit": "Edit entity",
        "erosion": "Erosion",
        "errorReport": "Error report",
        "exportStructure": "Export selection",
        "externalEditor": "External editor",
        "findReplaceBlocks": "Find and replace blocks",
        "findReplaceCommands": "Find and replace commands",
        "findReplaceNbt": "Find and replace NBT",
        "flatten": "Flatten to height",
        "floodFill": "Flood fill",
        "forceLoaded": "Force-loaded chunks",
        "fourUpView": "Four-up split",
        "gamerules": "Game rules",
        "generateTool": "Generate",
        "goto": "Teleport",
        "heightLimits": "Height limits",
        "history": "Project history",
        "importChunks": "Import chunks",
        "importMap": "Import map image",
        "inspector": "Inspector",
        "inventoryEditor": "Inventory editor",
        "itemTypeList": "Item types",
        "languageSelect": "Language Select",
        "layerSlice": "Layer slice",
        "levelDat": "level.dat",
        "libraryPanel": "Library",
        "licenses": "Third Party Licenses",
        "lightOverlay": "Light levels",
        "loading": "Renderer loading",
        "logView": "Log",
        "lootAudit": "Loot audit",
        "macroRecorder": "Macro recorder",
        "mapItems": "Map items",
        "measure": "Measure",
        "memory": "Memory console",
        "minecraftInstalls": "Minecraft installs",
        "moveTool": "Move",
        "narrator": "Narrator and voice",
        "nbt": "NBT editor",
        "nbtLegacy": "NBT editor (legacy)",
        "nbtSearch": "NBT search and replace",
        "noiseGen": "Noise fill",
        "notifications": "Notification history",
        "operationClone": "Clone operation",
        "operationFill": "Fill operation",
        "operationOptions": "Operations",
        "operationReplace": "Replace operation",
        "operationSetBiome": "Set biome operation",
        "operationWaterlog": "Waterlog operation",
        "oreAudit": "Ore distribution",
        "palette": "Command palette",
        "patternMask": "Pattern and mask",
        "pendingImports": "Pending imports",
        "playerData": "Player data",
        "playerPanel": "Players",
        "pluginsDialog": "Plugins",
        "portalBuilder": "Nether portal travel builder",
        "portalLinker": "Portal linkage",
        "prefs": "Options",
        "presets": "Appearance presets",
        "profiler": "Profiler",
        "pythonConsole": "Python console",
        "railNetwork": "Rail network",
        "railTunnel": "Rail tunnel builder",
        "redstoneTrace": "Circuit trace",
        "regenerate": "Regenerate chunks",
        "regex": "Regex builder",
        "relight": "Relight",
        "removeEntities": "Remove entities",
        "renderLayers": "Render layers",
        "schematicLibrary": "Structure library",
        "schoolUnlock": "School mode",
        "scoreboard": "Scoreboard",
        "scriptConsole": "Operation console",
        "seaLevel": "Sea level",
        "seedTools": "Seed tools",
        "selectBlockTool": "Select block",
        "selectEntityTool": "Select entity",
        "signSearch": "Sign text",
        "slimeChunks": "Slime chunks",
        "smooth": "Smooth terrain",
        "spawnAnalysis": "Mob spawn analysis",
        "spawnPoints": "Spawn points and beds",
        "stackArray": "Stack and array",
        "structureLocator": "Locate structures",
        "surfacePaint": "Repaint surface",
        "tabManager": "Tabs and groups",
        "terrainBrush": "Terrain brush",
        "tickLoad": "Tick load",
        "toolSettings": "Tool settings",
        "undoHistory": "Undo history",
        "update": "Update status",
        "validateRepair": "Validate and repair",
        "versionSelect": "Version picker",
        "viewControls": "View settings",
        "waypoints": "Waypoints",
        "workPlane": "Work plane",
        "worldBorder": "World border",
        "worldDiff": "Compare worlds",
        "worldInfo": "World info",
    }
)

#: The one line shown beneath a surface's name, transcribed from the same
#: inventory.  A surface with no line here falls back to the ribbon tile that
#: opens it, then to the opening sentence of its spec introduction.
_HINTS: Mapping[str, str] = MappingProxyType(
    {
        "about": "Opened world, support matrix, build",
        "analyzeTool": "Counts for every block, entity, and block entity",
        "batchQueue": "Multi-job runs with per-job revisions",
        "biomeMap": "Distribution with viewport and minimap overlays",
        "biomeSelect": "Searchable biome list per dimension",
        "blockAudit": "Unmapped, deprecated, and placeholder states",
        "blockHistogram": "Counts and percentages in the selection",
        "blockSelect": "Namespace, base name, and block-state properties",
        "brushSettings": "Shapes, modes, size, hollow, noise, work-plane painting",
        "brushTool": "Sphere, cylinder, cuboid, pyramid, line, path, torus",
        "caveMap": "Open volume, ravines, flooding, and cave fill",
        "changelog": "Observed releases with exact dates and commits",
        "chunkInspector": "Status, size, timestamps, and read errors",
        "cloneTool": "Repeatable copies with rotation, mirror, and scale",
        "commandFinder": "Locate and edit stored commands verbatim",
        "configureBlocks": "Override names, textures, and grouping",
        "confirm": "Two keys, full-range slider, emergency exit",
        "controls": "Editable key groups for every action",
        "convertProgress": "Bounded progress with cancel",
        "cutawayView": "Clip along a plane to see interiors",
        "dimsum": "Bounded startup surprise from the public catalog",
        "docs": "Offline article bundle with local link resolution",
        "editChunkTool": "Chunk flags, actions, and raw tags",
        "elementAppearance": "Per-element roles, type, decoration, metrics",
        "entityBrowser": "Counts, filters, and framing per entity type",
        "entityEdit": "Identity, state, flags, and raw tags",
        "erosion": "Hydraulic and thermal weathering passes",
        "errorReport": "Local traceback report, never sent automatically",
        "exportStructure": "construction, mcstructure, schematic, schem",
        "externalEditor": "Discover and validate a VS Code executable",
        "findReplaceBlocks": "Replacement list with state matching",
        "findReplaceCommands": "Command text with coordinate offsetting",
        "findReplaceNbt": "Tag name and value search with results",
        "flatten": "Cut, fill, and feathered edges",
        "floodFill": "Connected-region replace with block limit and connectivity",
        "forceLoaded": "Tickets and spawn-chunk radius",
        "fourUpView": "Four synchronized panes over one selection",
        "gamerules": "Platform-aware rule list with live values",
        "generateTool": "Generator plugins including the L-system",
        "goto": "Camera coordinates with copy and paste",
        "heightLimits": "Build range per platform with conversion warnings",
        "history": "Per-project Git repo, unlimited undo, restore and diff",
        "importChunks": "Restore chunks from another world",
        "importMap": "Map colours or closest-palette blocks with dithering",
        "inspector": "Dockable panel following the selection",
        "inventoryEditor": "Slot-by-slot editing with item textures",
        "itemTypeList": "Searchable item list with ids and textures",
        "languageSelect": "Loaded language and region files",
        "layerSlice": "Isolate a Y range in the viewport",
        "levelDat": "Validated world metadata editing",
        "libraryPanel": "Schematic library with folders and previews",
        "licenses": "Bundled components and licences",
        "lightOverlay": "Block, sky, and threshold overlays",
        "loading": "Resource packs, texture atlas, retry path",
        "logView": "Filterable application log by level and source",
        "lootAudit": "Unrolled tables and container contents",
        "macroRecorder": "Record and replay operation sequences",
        "mapItems": "Stored map data with PNG export",
        "measure": "Distance, volume, area, and chunk counts",
        "memory": "Thirteen views over instructions, skills, and evidence",
        "minecraftInstalls": "Installs, versions, resource packs, texture atlas",
        "moveTool": "Lift the selection into a pending import",
        "narrator": "Optional speech with independent funny levels",
        "nbt": "Full tag workbench: per-type controls, SNBT, bytes, tag history",
        "nbtLegacy": "The pre-Studio tag editor, kept while the workbench replaces it",
        "nbtSearch": "Tag-path search across the selection",
        "noiseGen": "Seeded heightmaps, caves, and scatter",
        "notifications": "Search, bulk dismissal, Markdown export",
        "operationClone": "The stock Clone operation, selected and ready to run",
        "operationFill": "The stock Fill operation, selected and ready to run",
        "operationOptions": "Clone, fill, replace, set biome, waterlog, plugins",
        "operationReplace": "The stock Replace operation, selected and ready to run",
        "operationSetBiome": "The stock Set Biome operation, selected and ready to run",
        "operationWaterlog": "The stock Waterlog operation, selected and ready to run",
        "oreAudit": "Per-Y peaks, counts, and x-ray overlay",
        "palette": "Ctrl+Shift+F over every command and setting",
        "patternMask": "Weighted block sets, masks, and gradients",
        "pendingImports": "Everything awaiting confirmation, per-entry transform",
        "playerData": "Position, state, and inventory per player",
        "playerPanel": "Positions, skins, game modes, inventories",
        "pluginsDialog": "Installed tools, generators, commands, load errors",
        "portalBuilder": "Matched pair at the 8:1 position, landing pods, link capture check",
        "portalLinker": "8:1 coordinate resolution and end portal frames",
        "prefs": "Appearance, language and voice, schedule, search",
        "presets": "Named versioned presets with JSON interchange",
        "profiler": "Frame time, meshing, draw calls, loader queue",
        "pythonConsole": "Interactive console with the session in scope",
        "railNetwork": "Junctions, powered gaps, and rail-shape repair",
        "railTunnel": "Route, profile, custom wall courses, roof shapes, lighting layout",
        "redstoneTrace": "Connected components, signal strength, delay, safe rotation",
        "regenerate": "Rebuild from the world seed behind a safety gate",
        "regex": "Bounded pattern, flags, sample, capture feedback",
        "relight": "Recompute block and sky light, bounded",
        "removeEntities": "Filtered removal with a previewed match set",
        "renderLayers": "Twelve independently drawable layers",
        "schematicLibrary": "Tagged, searchable staged structures",
        "schoolUnlock": "Presentation lock with salted local unlock",
        "scoreboard": "Objectives, teams, and scores",
        "scriptConsole": "Python extensions with exact import errors",
        "seaLevel": "Fill, drain, or replace fluid to a height",
        "seedTools": "Read, change, and reseed with border warnings",
        "selectBlockTool": "State, light, biome, and block entity under the cursor",
        "selectEntityTool": "Entity under the cursor plus nearby counts",
        "signSearch": "Find, edit, and bulk replace sign lines",
        "slimeChunks": "Seed-derived grid with viewport and minimap overlay",
        "smooth": "Averaging passes with kernel radius",
        "spawnAnalysis": "Per-column spawnability with spawn-proofing",
        "spawnPoints": "World spawn, beds, and respawn anchors",
        "stackArray": "Linear, grid, and radial repetition",
        "structureLocator": "Stored references plus seed-predicted positions",
        "surfacePaint": "Height, biome, and slope-driven surface rules",
        "tabManager": "Four searches, pinning, previewed bulk close",
        "terrainBrush": "Raise, lower, shape, falloff, layered materials",
        "tickLoad": "Block entities, scheduled and random ticks per chunk",
        "toolSettings": "Per-tool defaults, handles, and snapping",
        "undoHistory": "The full stack, unlimited depth, jump to any point",
        "update": "Immutable release route, unsigned packages",
        "validateRepair": "Exact file offsets and opt-in repairs",
        "versionSelect": "Platform and data version for handlers",
        "viewControls": "Camera, overhead, iso, cutaway, schematic view",
        "waypoints": "Named camera and build positions per dimension",
        "workPlane": "Fixed plane for brushes and shapes",
        "worldBorder": "Centre, diameter, warning band, and edit clamping",
        "worldDiff": "Chunk-by-chunk diff with selective import",
        "worldInfo": "Identity, size on disk, time and weather",
    }
)

#: Ribbon tiles describe their target in one line; that line is the best hint a
#: surface can have when the inventory above has none, because it is the
#: wording the user already read on the button that opens it.  Every indexed
#: surface currently carries its own line, so this is the fallback a surface
#: added after the inventory falls back to rather than a live source.
_RIBBON_HINTS: Mapping[str, str] = MappingProxyType(
    {
        button.surface: button.hint
        for _tab, _group, button in reversed(ribbon_defs.all_buttons())
        if button.surface and button.hint
    }
)


def _first_sentence(text: str, limit: int = 160) -> str:
    """Return the opening sentence of ``text``, bounded for a one-line card."""
    value = " ".join(str(text).split())
    if not value:
        return ""
    for stop in (". ", "。", "! ", "? "):
        index = value.find(stop)
        if index != -1:
            value = value[: index + 1] if stop == ". " else value[: index + 1]
            break
    if len(value) > limit:
        value = value[: limit - 1].rstrip() + "…"
    return value


def _label_for(key: str) -> str:
    """Return the name a surface is listed under."""
    if key in _LABELS:
        return _LABELS[key]
    spec = spec_registry.get(key)
    return spec.title if spec is not None else key


def _hint_for(key: str) -> str:
    """Return the one-line description shown beneath a surface's name."""
    if key in _HINTS:
        return _HINTS[key]
    if key in _RIBBON_HINTS:
        return _RIBBON_HINTS[key]
    spec = spec_registry.get(key)
    if spec is None:
        return ""
    sentence = _first_sentence(spec.intro)
    if sentence:
        return sentence
    return f"{spec.eyebrow} surface."


def _build() -> Tuple[Surface, ...]:
    """Assemble the index from the group order and the spec registry."""
    placed: Dict[str, str] = {}
    for group_name, members in _GROUP_MEMBERS.items():
        for key in members:
            if key in placed:
                log.error(
                    "Studio surface %r is listed under both %r and %r",
                    key,
                    placed[key],
                    group_name,
                )
                continue
            placed[key] = group_name
    unplaced = [key for key in spec_registry.SPECS if key not in placed]
    if unplaced:
        log.error(
            "Studio surfaces %s have no group; listing them under %r",
            ", ".join(sorted(unplaced)),
            _FALLBACK_GROUP,
        )
    rows: List[Surface] = []
    for group_name in SURFACE_GROUPS:
        for key in _GROUP_MEMBERS.get(group_name, ()):
            if key not in _LABELS and spec_registry.get(key) is None:
                log.error(
                    "Studio surface %r is indexed but has neither a spec nor a label",
                    key,
                )
                continue
            rows.append(
                Surface(
                    key=key,
                    label=_label_for(key),
                    hint=_hint_for(key),
                    group=group_name,
                    accel=commands.ACCELERATORS.get(key, ""),
                )
            )
        if group_name == _FALLBACK_GROUP:
            for key in sorted(unplaced):
                rows.append(
                    Surface(
                        key=key,
                        label=_label_for(key),
                        hint=_hint_for(key),
                        group=group_name,
                        accel=commands.ACCELERATORS.get(key, ""),
                    )
                )
    return tuple(rows)


SURFACES: Tuple[Surface, ...] = _build()

_BY_KEY: Mapping[str, Surface] = MappingProxyType(
    {entry.key: entry for entry in SURFACES}
)


def surface(key: object) -> Optional[Surface]:
    """Return the indexed surface for ``key``, or ``None`` when unknown."""
    return _BY_KEY.get(str(key or "").strip())


def keys() -> Tuple[str, ...]:
    """Return every surface key, in index order."""
    return tuple(entry.key for entry in SURFACES)


def group(name: str) -> Tuple[Surface, ...]:
    """Return every surface in one group, in index order."""
    wanted = str(name)
    return tuple(entry for entry in SURFACES if entry.group == wanted)


def search(state: SearchState) -> Tuple[Surface, ...]:
    """Return the surfaces matching a search field's current query."""
    return tuple(state.filter(SURFACES, key=lambda entry: entry.search_text()))


# ---------------------------------------------------------------------------
# locally described surfaces
# ---------------------------------------------------------------------------
def about_spec() -> Spec:
    """Describe this build, reading the real values rather than fixed text.

    Built when it is opened rather than at import so the display name the user
    chose, and the update state the frame has actually observed, are current
    every time the window is shown.
    """
    from amulet_map_editor import __version__
    from amulet_map_editor.api import preferences

    current = preferences.load()
    rows = [
        Row("Version", str(__version__), "build"),
        Row("Shown as", current.display_name, "display name"),
        Row("Installer", "Squirrel.Windows, unsigned", "delivery"),
        Row(
            "Updates", "One immutable release route, checked in the background", "feed"
        ),
        Row("Network use", "None at runtime; every asset is bundled", "privacy"),
    ]
    return Spec(
        key="about",
        eyebrow="Project shell",
        title="About",
        width=620,
        confirm="Close",
        intro=(
            "This build is local-only: there is no sign-in, no telemetry, and no "
            "cloud storage. The name above is a display label; the installer, the "
            "data directory, and the update feed keep the product's own identity."
        ),
        sections=(
            sec("This build", "list", rows=rows),
            sec(
                "",
                "note",
                hint=(
                    "Packages are unsigned by design, so Windows may warn about an "
                    "unknown publisher the first time an installer runs. Nothing in "
                    "this build claims a verified signature."
                ),
            ),
        ),
        actions=(
            Action("Third-party licences", "outlined", surface="licenses"),
            Action("Documentation", "outlined", surface="docs"),
            Action("Changelog", "outlined", surface="changelog"),
        ),
    )


def regex_spec() -> Spec:
    """Describe the standalone regular-expression builder.

    The search block is a real
    :class:`~amulet_map_editor.api.studio.widgets.SearchBar`: its ``.*`` button
    opens the same builder every other search field opens, so a pattern worked
    out here behaves exactly as it will where it is used.
    """
    from amulet_map_editor.api.studio.search import MAX_PATTERN_LENGTH

    return Spec(
        key="regex",
        eyebrow="Global",
        title="Regex builder",
        width=560,
        confirm="Close",
        intro=(
            "Type a pattern, turn Regex on, and open the builder with the .* button "
            "to check it against sample text before using it anywhere else."
        ),
        sections=(
            sec("Pattern", "search", hint="Pattern"),
            sec(
                "",
                "note",
                hint=(
                    "Patterns are evaluated by Python's re module with the i and u "
                    f"flags, and are capped at {MAX_PATTERN_LENGTH} characters. Plain "
                    "text is the default everywhere; an invalid pattern is reported "
                    "and matches nothing rather than quietly matching everything."
                ),
            ),
        ),
        actions=(Action("Documentation", "outlined", surface="docs"),),
    )


_LOCAL_SPECS: Mapping[str, Callable[[], Spec]] = MappingProxyType(
    {"about": about_spec, "regex": regex_spec}
)


# ---------------------------------------------------------------------------
# opening
# ---------------------------------------------------------------------------
def _top_level(parent: Any) -> Any:
    """Return the top-level window above ``parent``, or ``parent`` itself."""
    try:
        return parent.GetTopLevelParent() or parent
    except AttributeError:  # pragma: no cover - a non-window caller
        return parent


def _frame_method(parent: Any, name: str) -> Optional[Callable[..., Any]]:
    """Return a named method on the hosting frame, when it offers one.

    Several legacy dialogs end themselves with ``EndModal`` and so have to be
    shown modally.  The frame already owns those call sites, so the surface
    index asks the frame to run them instead of opening a second, subtly
    different copy of the same window.
    """
    handler = getattr(_top_level(parent), name, None)
    return handler if callable(handler) else None


def _modeless(parent: Any, key: str, factory: Callable[[Any], Any]) -> Any:
    """Show one reusable non-modal window, reusing the one already open."""
    from amulet_map_editor.api.wx.modeless import show_modeless_dialog

    return show_modeless_dialog(_top_level(parent), key, factory)


def _open_local_spec(parent: Any, key: str) -> Any:
    """Open a surface this module describes itself."""
    from amulet_map_editor.api.studio.spec_dialog import SpecDialog

    spec = _LOCAL_SPECS[key]()
    return _modeless(
        parent, f"studio.spec.{key}", lambda owner: SpecDialog(owner, spec)
    )


def _open_nbt(parent: Any) -> Any:
    from amulet_map_editor.api.studio.nbt_studio import NbtStudioDialog

    return _modeless(parent, "studio.nbt", NbtStudioDialog)


def _open_memory(parent: Any) -> Any:
    from amulet_map_editor.api.studio.memory_console import MemoryConsoleDialog

    return _modeless(parent, "studio.memory", MemoryConsoleDialog)


def _open_palette(parent: Any) -> Any:
    from amulet_map_editor.api.studio import palette_dialog

    return palette_dialog.open_palette(parent)


def _open_preferences(parent: Any) -> Any:
    """Open the real preferences dialog, which the frame shows modally."""
    handler = _frame_method(parent, "open_preferences")
    if handler is None:
        return None
    handler()
    return _top_level(parent)


def _open_history(parent: Any) -> Any:
    """Open the local-history browser the frame owns."""
    handler = _frame_method(parent, "open_local_history")
    if handler is None:
        from amulet_map_editor.api.wx.ui.local_history import LocalHistoryDialog

        return _modeless(parent, "local-history", LocalHistoryDialog)
    handler()
    return _top_level(parent)


def _open_tab_manager(parent: Any) -> Any:
    """Open the tab and group manager over the frame's real notebook."""
    handler = _frame_method(parent, "open_tab_manager")
    if handler is None:
        return _open_spec(parent, "tabManager")
    handler()
    return _top_level(parent)


def _open_language_select(parent: Any) -> Any:
    """Open the language chooser the start page owns."""
    handler = _frame_method(parent, "select_language")
    if handler is None:
        return _open_spec(parent, "languageSelect")
    handler()
    return _top_level(parent)


def _open_notifications(parent: Any) -> Any:
    from amulet_map_editor.api.wx.ui.notifications import NotificationHistoryDialog

    return _modeless(parent, "notification-history", NotificationHistoryDialog)


def _open_changelog(parent: Any) -> Any:
    from amulet_map_editor.api.wx.ui.preferences import ChangelogDialog

    return _modeless(parent, "changelog", ChangelogDialog)


def _open_documentation(parent: Any) -> Any:
    from amulet_map_editor.api.wx.ui.documentation import DocumentationDialog

    return _modeless(parent, "documentation", DocumentationDialog)


def _open_licences(parent: Any) -> Any:
    from amulet_map_editor.api.framework.pages._legal import LicenceDialog

    return _modeless(parent, "third-party-licences", LicenceDialog)


def _open_element_appearance(parent: Any) -> Any:
    """Edit the appearance of whatever control the keyboard is on.

    The per-element editor edits one element, so it needs one; the focused
    control is the element the user was last working with, and the opener is
    the honest fallback when nothing has focus.
    """
    import wx

    from amulet_map_editor.api.wx.ui import element_appearance

    target = wx.Window.FindFocus() or parent
    element_appearance.open_element_appearance(target)
    return target


def _open_spec(parent: Any, key: str) -> Any:
    """Open the declarative surface registered under ``key``."""
    from amulet_map_editor.api.studio.spec_dialog import open_spec

    return open_spec(_top_level(parent), key)


def _open_editor_tool(key: str) -> Callable[[Any], Any]:
    """Return an opener that starts the editor tool one key stands for.

    The stock operations are not windows and never were: each one is the
    editor's Operation tool with that operation selected.  They are routed here
    rather than left to :func:`editor_tools.install_surface_routes` so the key
    resolves to the same thing before the properties pane exists -- a surface
    that opens one thing at start-up and another once a pane has been built is
    two surfaces wearing one name.
    """

    def open_tool(parent: Any) -> Any:
        from amulet_map_editor.api.studio import editor_tools

        return editor_tools.activate(key, parent)

    return open_tool


#: Surfaces whose implementation is not the spec renderer.
_ROUTES: Mapping[str, Callable[[Any], Any]] = MappingProxyType(
    {
        "about": lambda parent: _open_local_spec(parent, "about"),
        "changelog": _open_changelog,
        "docs": _open_documentation,
        "elementAppearance": _open_element_appearance,
        "history": _open_history,
        "languageSelect": _open_language_select,
        "licenses": _open_licences,
        "memory": _open_memory,
        "nbt": _open_nbt,
        "notifications": _open_notifications,
        "operationClone": _open_editor_tool("operationClone"),
        "operationFill": _open_editor_tool("operationFill"),
        "operationReplace": _open_editor_tool("operationReplace"),
        "operationSetBiome": _open_editor_tool("operationSetBiome"),
        "operationWaterlog": _open_editor_tool("operationWaterlog"),
        "palette": _open_palette,
        "prefs": _open_preferences,
        "regex": lambda parent: _open_local_spec(parent, "regex"),
        "tabManager": _open_tab_manager,
    }
)


def unrouted_keys() -> Tuple[str, ...]:
    """Return indexed surfaces with neither a route nor a spec to render.

    Nothing should be in this list; it exists so a missing surface is a fact a
    test can assert on rather than something a user discovers as a button that
    reports it cannot open anything.
    """
    return tuple(
        entry.key
        for entry in SURFACES
        if entry.key not in _ROUTES and spec_registry.get(entry.key) is None
    )


def _report(parent: Any, title: str, body: str, severity: str = "warning") -> None:
    """Say plainly that a surface did not open, without halting anything."""
    try:
        from amulet_map_editor.api.wx import nonblocking

        nonblocking.notify(parent, title, body, severity=severity)
    except Exception:  # pragma: no cover - the reporter itself is unavailable
        log.exception("%s: %s", title, body)


def open_surface(parent: Any, key: str) -> Any:
    """Open the surface registered under ``key`` and return its window.

    Returns ``None`` when nothing opened, and says so where the user can see
    it: a button that silently does nothing is indistinguishable from a broken
    application, so every failure names the exact key it was asked for.
    """
    name = str(key or "").strip()
    if not name:
        log.error("open_surface was called without a surface key")
        return None
    entry = surface(name)
    route = _ROUTES.get(name)
    try:
        window = route(parent) if route is not None else _open_spec(parent, name)
    except Exception:
        log.exception("Could not open the Studio surface %r", name)
        _report(
            parent,
            f"{entry.label if entry else name} did not open",
            f"Opening the {name!r} surface failed. The details are in the log.",
            severity="error",
        )
        return None
    if window is None:
        log.error("No Studio surface is registered under the key %r", name)
        _report(
            parent,
            "That surface is not available",
            f"Nothing is registered under the surface key {name!r}, so no window "
            "opened.",
        )
    return window
