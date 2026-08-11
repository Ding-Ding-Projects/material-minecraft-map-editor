"""The seventeen command-ribbon tabs, transcribed from the Studio design.

This module is deliberately pure data: no wxPython, no imports that need a
display, and no behaviour beyond lookup and filtering.  Keeping the ribbon's
content separate from the widget that paints it is what lets a test assert on
every label, glyph, hint, and target without constructing a window, and what
lets the command palette and the surface index reuse the same rows rather than
maintaining a second copy that drifts.

Each button names either a **surface** (a dialog key routed through
``surfaces.open_surface``) or a **command** (a shell action key routed through
``StudioShell.run_command``), never both.  A button that names neither would be
a control that looks live and does nothing, which is exactly the defect the
project forbids, so :func:`validate` refuses one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from amulet_map_editor.api.studio.search import SearchState

__all__ = [
    "COMMAND_KEYS",
    "RIBBON_TABS",
    "RibbonButton",
    "RibbonField",
    "RibbonGroup",
    "RibbonOption",
    "RibbonSelect",
    "RibbonTab",
    "TAB_KEYS",
    "all_buttons",
    "buttons",
    "search",
    "surface_keys",
    "tab",
    "validate",
]


@dataclass(frozen=True)
class RibbonOption:
    """One entry of a ribbon dropdown: the stored value and its visible label.

    The two differ throughout the design -- the dimension list stores
    ``overworld`` and shows ``minecraft:overworld`` -- so a widget that only
    kept the label would have to reverse-engineer the identifier it needs to
    pass on.
    """

    value: str
    label: str


@dataclass(frozen=True)
class RibbonButton:
    """One command tile in a ribbon group."""

    label: str
    glyph: str = ""
    hint: str = ""
    surface: str = ""
    command: str = ""
    primary: bool = False

    @property
    def haystack(self) -> str:
        """Return the text the per-tab search matches against."""
        return " ".join(part for part in (self.label, self.hint) if part)

    @property
    def accessible_name(self) -> str:
        """Return the screen-reader name for this tile."""
        return f"{self.label}. {self.hint}" if self.hint else self.label


@dataclass(frozen=True)
class RibbonField:
    """One labelled value in a ribbon group's field grid."""

    label: str
    value: str = ""


@dataclass(frozen=True)
class RibbonSelect:
    """One labelled dropdown column in a ribbon group."""

    label: str
    options: Tuple[RibbonOption, ...] = ()
    value: str = ""
    command: str = ""

    @property
    def option_labels(self) -> Tuple[str, ...]:
        """Return the visible labels, in the order the design lists them."""
        return tuple(option.label for option in self.options)

    def label_for(self, value: str) -> str:
        """Return the visible label for ``value``, or the first label."""
        for option in self.options:
            if option.value == value:
                return option.label
        return self.options[0].label if self.options else ""

    def value_for(self, label: str) -> str:
        """Return the stored value behind a visible ``label``."""
        for option in self.options:
            if option.label == label:
                return option.value
        return ""

    @property
    def default_label(self) -> str:
        """Return the label shown before the user chooses anything."""
        return (
            self.label_for(self.value)
            if self.value
            else (self.options[0].label if self.options else "")
        )


@dataclass(frozen=True)
class RibbonGroup:
    """One column of the ribbon: its controls, its title, and its launcher.

    ``launcher`` is the surface opened by the group's small dialog-launcher
    corner (the design's ``◢``).  Every group has one: a launcher that opened
    nothing would be a decorative control.
    """

    title: str
    buttons: Tuple[RibbonButton, ...] = ()
    fields: Tuple[RibbonField, ...] = ()
    selects: Tuple[RibbonSelect, ...] = ()
    launcher: str = ""

    @property
    def has_fields(self) -> bool:
        """Return whether this group draws a field grid."""
        return bool(self.fields)

    @property
    def has_selects(self) -> bool:
        """Return whether this group draws a dropdown column."""
        return bool(self.selects)


@dataclass(frozen=True)
class RibbonTab:
    """One ribbon tab and the groups it shows."""

    key: str
    label: str
    groups: Tuple[RibbonGroup, ...] = ()

    @property
    def buttons(self) -> Tuple[RibbonButton, ...]:
        """Return every button on this tab, in visual order."""
        return tuple(button for group in self.groups for button in group.buttons)


def _button(
    label: str,
    glyph: str,
    hint: str,
    *,
    surface: str = "",
    command: str = "",
    primary: bool = False,
) -> RibbonButton:
    """Build one tile, defaulting the hint to the label as the design does."""
    return RibbonButton(
        label=label,
        glyph=glyph,
        hint=hint or label,
        surface=surface,
        command=command,
        primary=primary,
    )


def _options(*pairs: Tuple[str, str]) -> Tuple[RibbonOption, ...]:
    """Build a dropdown's options from ``(value, label)`` pairs."""
    return tuple(RibbonOption(value, label) for value, label in pairs)


# ----------------------------------------------------------------------------
# the seventeen tabs
# ----------------------------------------------------------------------------

_HOME = RibbonTab(
    "home",
    "Home",
    (
        RibbonGroup(
            "Clipboard",
            buttons=(
                _button(
                    "Paste",
                    "⎘",
                    "Paste a previously copied or cut area into the world.",
                    command="paste",
                    primary=True,
                ),
                _button(
                    "Copy",
                    "⧉",
                    "Copy the selected area to paste later.",
                    command="copy",
                ),
                _button(
                    "Cut",
                    "✂",
                    "Copy the selected area to paste later and delete.",
                    command="cut",
                ),
                _button(
                    "Delete",
                    "⌫",
                    "Delete the blocks in the selected area.",
                    command="delete",
                ),
                _button(
                    "Clone",
                    "⁙",
                    "Clone the selection with repeatable copies",
                    surface="cloneTool",
                ),
                _button(
                    "Move",
                    "✥",
                    "Lift the selection into a pending import",
                    surface="moveTool",
                ),
            ),
            launcher="operationOptions",
        ),
        RibbonGroup(
            "Editing",
            buttons=(
                _button(
                    "Undo",
                    "↶",
                    "Undo · unlimited depth from the project Git repository",
                    command="undo",
                ),
                _button("Redo", "↷", "Redo", command="redo"),
                _button("Save", "▣", "Save changes", command="save"),
                _button(
                    "History",
                    "⟲",
                    "Project history · per-project Git repository",
                    surface="history",
                ),
                _button(
                    "Goto",
                    "⌖",
                    "Teleport the camera to a coordinate",
                    surface="goto",
                ),
                _button("Select all", "▩", "Select All", command="selectAll"),
                _button(
                    "Inspect",
                    "⌕",
                    "Inspect block · opens the NBT editor",
                    surface="nbt",
                ),
            ),
            launcher="history",
        ),
        RibbonGroup(
            "Camera",
            buttons=(
                _button("Projection", "◱", "Change view", command="projection"),
                _button(
                    "Speed",
                    "➤",
                    "Camera speed in blocks per second",
                    command="cameraSpeed",
                ),
            ),
            selects=(
                RibbonSelect(
                    "Dimension",
                    _options(
                        ("overworld", "minecraft:overworld"),
                        ("nether", "minecraft:the_nether"),
                        ("end", "minecraft:the_end"),
                    ),
                    value="overworld",
                    command="setDimension",
                ),
            ),
            launcher="controls",
        ),
        RibbonGroup(
            "Panes",
            buttons=(
                _button(
                    "Properties",
                    "▤",
                    "Show the properties pane",
                    command="togglePane",
                ),
                _button("Commands", "⌘", "Tell me what to do", surface="palette"),
            ),
            launcher="inspector",
        ),
    ),
)

_TOOLS = RibbonTab(
    "tools",
    "Tools",
    (
        RibbonGroup(
            "Paint",
            buttons=(
                _button(
                    "Brush",
                    "◉",
                    "Paint blocks through a shape at the cursor",
                    surface="brushSettings",
                    primary=True,
                ),
                _button(
                    "Flood fill",
                    "≈",
                    "Replace a connected region of matching blocks",
                    surface="floodFill",
                ),
                _button(
                    "Settings",
                    "⚙",
                    "Per-tool defaults and handles",
                    surface="toolSettings",
                ),
            ),
            launcher="toolSettings",
        ),
        RibbonGroup(
            "Pick",
            buttons=(
                _button(
                    "Block",
                    "⌖",
                    "Inspect the block under the cursor",
                    surface="selectBlockTool",
                    primary=True,
                ),
                _button(
                    "Entity",
                    "☰",
                    "Inspect the entity under the cursor",
                    surface="selectEntityTool",
                ),
                _button(
                    "Chunk",
                    "▦",
                    "Chunk flags, actions, and raw tags",
                    surface="editChunkTool",
                ),
            ),
            launcher="selectBlockTool",
        ),
        RibbonGroup(
            "Find and replace",
            buttons=(
                _button(
                    "Blocks",
                    "▨",
                    "Find and replace blocks with a replacement list",
                    surface="findReplaceBlocks",
                    primary=True,
                ),
                _button(
                    "Commands",
                    "⌘",
                    "Find and replace command text and coordinates",
                    surface="findReplaceCommands",
                ),
                _button(
                    "NBT",
                    "▤",
                    "Find and replace raw tags",
                    surface="findReplaceNbt",
                ),
                _button(
                    "Analyze",
                    "▥",
                    "Count everything in the selection",
                    surface="analyzeTool",
                ),
            ),
            launcher="findReplaceBlocks",
        ),
    ),
)

_SELECTION = RibbonTab(
    "selection",
    "Selection",
    (
        RibbonGroup(
            "Points",
            buttons=(
                _button(
                    "Move point 1",
                    "◉",
                    "Press and hold, then use the movement controls to move "
                    "the green point.",
                    command="movePoint1",
                    primary=True,
                ),
                _button(
                    "Move point 2",
                    "◎",
                    "Press and hold, then use the movement controls to move "
                    "the blue point.",
                    command="movePoint2",
                ),
                _button(
                    "Move box",
                    "⬚",
                    "Press and hold, then use the movement controls to move "
                    "the active box.",
                    command="moveBox",
                ),
            ),
            launcher="controls",
        ),
        RibbonGroup(
            "Coordinates",
            fields=(
                RibbonField("x1", "-2"),
                RibbonField("x2", "13"),
                RibbonField("y1", "98"),
                RibbonField("y2", "99"),
                RibbonField("z1", "-49"),
                RibbonField("z2", "-32"),
            ),
            launcher="goto",
        ),
        RibbonGroup(
            "Boxes",
            buttons=(
                _button("Add box", "＋", "Add another selection box", command="addBox"),
                _button(
                    "Remove",
                    "－",
                    "Remove the active selection box",
                    command="removeBox",
                ),
                _button("Select all", "▩", "Select All", command="selectAll"),
            ),
            launcher="measure",
        ),
    ),
)

_OPERATIONS = RibbonTab(
    "operations",
    "Operations",
    (
        RibbonGroup(
            "Stock operations",
            buttons=(
                _button(
                    "Clone",
                    "⧉",
                    "Copy the selection to another location",
                    surface="operationOptions",
                    primary=True,
                ),
                _button(
                    "Fill",
                    "▧",
                    "Fill the selection with one block",
                    surface="operationOptions",
                ),
                _button(
                    "Replace",
                    "⇄",
                    "Swap one block for another in the selection",
                    surface="operationOptions",
                ),
                _button(
                    "Set biome",
                    "❋",
                    "Apply a biome across the selection",
                    surface="operationOptions",
                ),
                _button(
                    "Waterlog",
                    "≈",
                    "Waterlog eligible blocks in the selection",
                    surface="operationOptions",
                ),
            ),
            launcher="operationOptions",
        ),
        RibbonGroup(
            "Plugins",
            buttons=(
                _button(
                    "Reload",
                    "↻",
                    "Reload project-specific Python operations",
                    command="reloadPlugins",
                ),
                _button(
                    "Open folder",
                    "▸",
                    "Open the operations folder",
                    command="openOperationsFolder",
                ),
            ),
            launcher="pluginsDialog",
        ),
        RibbonGroup(
            "Run",
            buttons=(
                _button(
                    "Run",
                    "▶",
                    "Run the selected operation",
                    command="runOperation",
                    primary=True,
                ),
            ),
            launcher="operationOptions",
        ),
    ),
)

_STRUCTURES = RibbonTab(
    "structures",
    "Structures",
    (
        RibbonGroup(
            "Import",
            buttons=(
                _button(
                    "Import file",
                    "⭳",
                    "Import a supported structure file",
                    command="importFile",
                    primary=True,
                ),
                _button(
                    "Import chunks",
                    "▦",
                    "Replace the selected chunks with chunks from another world",
                    command="importChunks",
                ),
            ),
            launcher="importChunks",
        ),
        RibbonGroup(
            "Export",
            buttons=(
                _button(
                    "Export",
                    "⭱",
                    "Export the selection through a format handler",
                    command="export",
                ),
                _button(
                    "Open in editor",
                    "▸",
                    "Open the exported folder in Visual Studio Code",
                    command="openInEditor",
                ),
            ),
            selects=(
                RibbonSelect(
                    "Format",
                    _options(
                        ("construction", "construction (.construction)"),
                        ("mcstructure", "mcstructure (.mcstructure)"),
                        ("schematic", "schematic (.schematic)"),
                        ("schem", "Sponge schem (.schem)"),
                    ),
                    value="construction",
                ),
            ),
            launcher="exportStructure",
        ),
    ),
)

_CHUNKS = RibbonTab(
    "chunks",
    "Chunks",
    (
        RibbonGroup(
            "Draw range",
            fields=(RibbonField("Min Y", "-64"), RibbonField("Max Y", "320")),
            launcher="heightLimits",
        ),
        RibbonGroup(
            "Chunks",
            buttons=(
                _button(
                    "Create empty",
                    "▢",
                    "Create all chunks in the selection that do not already exist.",
                    command="createChunks",
                    primary=True,
                ),
                _button(
                    "Import",
                    "▦",
                    "Replace the selected chunks with chunks from another world.",
                    command="importChunks",
                ),
                _button(
                    "Delete",
                    "⌫",
                    "Delete the selected chunks.",
                    command="deleteChunks",
                ),
                _button(
                    "Delete unselected",
                    "⌦",
                    "Delete all chunks that are not selected.",
                    command="deleteUnselectedChunks",
                ),
            ),
            launcher="chunkInspector",
        ),
    ),
)

_TERRAIN = RibbonTab(
    "terrain",
    "Terrain",
    (
        RibbonGroup(
            "Sculpt",
            buttons=(
                _button(
                    "Raise",
                    "▲",
                    "Raise the heightmap under the brush",
                    surface="terrainBrush",
                    primary=True,
                ),
                _button(
                    "Lower",
                    "▼",
                    "Lower the heightmap under the brush",
                    surface="terrainBrush",
                ),
                _button(
                    "Smooth",
                    "≈",
                    "Average neighbouring heights",
                    surface="smooth",
                ),
                _button(
                    "Flatten",
                    "▬",
                    "Flatten to a target height",
                    surface="flatten",
                ),
                _button(
                    "Erode",
                    "◠",
                    "Hydraulic and thermal erosion passes",
                    surface="erosion",
                ),
            ),
            launcher="terrainBrush",
        ),
        RibbonGroup(
            "Generate",
            buttons=(
                _button(
                    "Noise",
                    "⁘",
                    "Fill the selection from a seeded noise field",
                    surface="noiseGen",
                    primary=True,
                ),
                _button(
                    "Sea level",
                    "≡",
                    "Set or drain the water level in the selection",
                    surface="seaLevel",
                ),
                _button(
                    "Regenerate",
                    "↻",
                    "Regenerate chunks from the world seed",
                    surface="regenerate",
                ),
            ),
            launcher="noiseGen",
        ),
        RibbonGroup(
            "Surface",
            buttons=(
                _button(
                    "Repaint",
                    "▨",
                    "Repaint the surface layer by biome or block",
                    surface="surfacePaint",
                ),
                _button(
                    "Snow line",
                    "❄",
                    "Apply snow and ice above a height",
                    surface="surfacePaint",
                ),
                _button(
                    "Grass fix",
                    "❋",
                    "Restore grass, dirt, and stone banding",
                    surface="surfacePaint",
                ),
            ),
            launcher="surfacePaint",
        ),
        RibbonGroup(
            "Brush",
            fields=(
                RibbonField("Radius", "12"),
                RibbonField("Strength", "0.45"),
                RibbonField("Falloff", "smooth"),
                RibbonField("Height", "98"),
            ),
            launcher="brushSettings",
        ),
    ),
)

_BUILD = RibbonTab(
    "build",
    "Build",
    (
        RibbonGroup(
            "Shapes",
            buttons=(
                _button(
                    "Sphere",
                    "◉",
                    "Draw a filled or hollow sphere",
                    surface="brushTool",
                    primary=True,
                ),
                _button(
                    "Cylinder",
                    "◍",
                    "Draw a cylinder along an axis",
                    surface="brushTool",
                ),
                _button(
                    "Cuboid",
                    "▢",
                    "Fill the selection as a box",
                    surface="brushTool",
                ),
                _button(
                    "Line",
                    "／",
                    "Draw a line between the two points",
                    surface="brushTool",
                ),
                _button(
                    "Path",
                    "〜",
                    "Draw a path through waypoints",
                    surface="brushTool",
                ),
            ),
            launcher="brushTool",
        ),
        RibbonGroup(
            "Pattern",
            buttons=(
                _button(
                    "Pattern",
                    "▦",
                    "Weighted multi-block pattern",
                    surface="patternMask",
                    primary=True,
                ),
                _button(
                    "Mask",
                    "◫",
                    "Restrict edits to matching blocks",
                    surface="patternMask",
                ),
                _button(
                    "Gradient",
                    "▩",
                    "Blend two blocks across the selection",
                    surface="patternMask",
                ),
            ),
            launcher="patternMask",
        ),
        RibbonGroup(
            "Transform",
            buttons=(
                _button(
                    "Stack",
                    "⧈",
                    "Repeat the selection along an axis",
                    surface="stackArray",
                    primary=True,
                ),
                _button(
                    "Array",
                    "⁙",
                    "Grid or radial array of the selection",
                    surface="stackArray",
                ),
                _button(
                    "Rotate",
                    "↻",
                    "Rotate in 90-degree or free steps",
                    command="rotate",
                ),
                _button(
                    "Flip",
                    "⇋",
                    "Mirror along a camera-relative axis",
                    command="flip",
                ),
            ),
            launcher="stackArray",
        ),
        RibbonGroup(
            "Library",
            buttons=(
                _button(
                    "Structures",
                    "❖",
                    "Staged structure library with tags",
                    surface="schematicLibrary",
                    primary=True,
                ),
                _button(
                    "Waypoints",
                    "⌖",
                    "Named camera and build waypoints",
                    surface="waypoints",
                ),
            ),
            launcher="schematicLibrary",
        ),
    ),
)

_ENTITIES = RibbonTab(
    "entities",
    "Entities",
    (
        RibbonGroup(
            "Browse",
            buttons=(
                _button(
                    "Entities",
                    "☰",
                    "Every entity in the selection, searchable",
                    surface="entityBrowser",
                    primary=True,
                ),
                _button(
                    "Block entities",
                    "▤",
                    "Chests, signs, spawners, and other NBT blocks",
                    surface="entityBrowser",
                ),
                _button(
                    "Players",
                    "☺",
                    "Player data, inventory, and position",
                    surface="playerData",
                ),
            ),
            launcher="entityBrowser",
        ),
        RibbonGroup(
            "Edit",
            buttons=(
                _button(
                    "Edit entity",
                    "✎",
                    "Edit the selected entity's NBT",
                    surface="entityEdit",
                    primary=True,
                ),
                _button(
                    "Place",
                    "＋",
                    "Place an entity at the cursor",
                    surface="entityEdit",
                ),
                _button(
                    "Remove",
                    "⌫",
                    "Remove entities matching a filter",
                    surface="removeEntities",
                ),
            ),
            launcher="entityEdit",
        ),
        RibbonGroup(
            "Spawners",
            buttons=(
                _button(
                    "Spawner",
                    "◈",
                    "Edit spawner type, delay, and range",
                    surface="entityEdit",
                ),
                _button(
                    "Loot",
                    "▧",
                    "Audit container loot tables",
                    surface="lootAudit",
                ),
            ),
            launcher="lootAudit",
        ),
    ),
)

_DATA = RibbonTab(
    "data",
    "Data",
    (
        RibbonGroup(
            "Search",
            buttons=(
                _button(
                    "NBT search",
                    "⌕",
                    "Search and replace across raw tags",
                    surface="nbtSearch",
                    primary=True,
                ),
                _button(
                    "Signs",
                    "▭",
                    "Find and edit sign text",
                    surface="signSearch",
                ),
                _button(
                    "Commands",
                    "⌘",
                    "Find command blocks and their commands",
                    surface="commandFinder",
                ),
            ),
            launcher="nbtSearch",
        ),
        RibbonGroup(
            "World data",
            buttons=(
                _button(
                    "level.dat",
                    "▣",
                    "Edit level.dat safely with validation",
                    surface="levelDat",
                    primary=True,
                ),
                _button(
                    "Game rules",
                    "⚖",
                    "Every game rule with its current value",
                    surface="gamerules",
                ),
                _button(
                    "Scoreboard",
                    "▥",
                    "Objectives, teams, and scores",
                    surface="scoreboard",
                ),
                _button(
                    "Maps",
                    "◫",
                    "Map items and their stored images",
                    surface="mapItems",
                ),
            ),
            launcher="levelDat",
        ),
        RibbonGroup(
            "Blocks",
            buttons=(
                _button(
                    "Block audit",
                    "▨",
                    "Unknown or deprecated block states",
                    surface="blockAudit",
                ),
                _button(
                    "Palette",
                    "▩",
                    "Per-chunk block palette usage",
                    surface="blockHistogram",
                ),
            ),
            launcher="blockAudit",
        ),
    ),
)

_ANALYZE = RibbonTab(
    "analyze",
    "Analyze",
    (
        RibbonGroup(
            "Counts",
            buttons=(
                _button(
                    "Histogram",
                    "▥",
                    "Block counts and percentages in the selection",
                    surface="blockHistogram",
                    primary=True,
                ),
                _button(
                    "Chunk inspector",
                    "▦",
                    "Per-chunk status, size, and timestamps",
                    surface="chunkInspector",
                ),
                _button(
                    "Biome map",
                    "❋",
                    "Biome distribution across the selection",
                    surface="biomeMap",
                ),
            ),
            launcher="blockHistogram",
        ),
        RibbonGroup(
            "Integrity",
            buttons=(
                _button(
                    "Validate",
                    "✓",
                    "Validate and repair chunk and region data",
                    surface="validateRepair",
                    primary=True,
                ),
                _button(
                    "Relight",
                    "☀",
                    "Recompute block and sky light",
                    surface="relight",
                ),
                _button(
                    "Compare",
                    "⇄",
                    "Diff two worlds chunk by chunk",
                    surface="worldDiff",
                ),
            ),
            launcher="validateRepair",
        ),
        RibbonGroup(
            "Measure",
            buttons=(
                _button(
                    "Measure",
                    "⟺",
                    "Distance, volume, and area readouts",
                    surface="measure",
                ),
                _button(
                    "Slice",
                    "▬",
                    "Isolate a Y slice in the viewport",
                    surface="layerSlice",
                ),
            ),
            launcher="measure",
        ),
    ),
)

_REDSTONE = RibbonTab(
    "redstone",
    "Redstone",
    (
        RibbonGroup(
            "Circuits",
            buttons=(
                _button(
                    "Trace",
                    "⌁",
                    "Trace a redstone circuit and list its components",
                    surface="redstoneTrace",
                    primary=True,
                ),
                _button(
                    "Signal",
                    "◈",
                    "Inspect signal strength and power sources",
                    surface="redstoneTrace",
                ),
                _button(
                    "Rewire",
                    "⇉",
                    "Rotate or mirror a circuit without breaking wiring",
                    surface="redstoneTrace",
                ),
            ),
            launcher="redstoneTrace",
        ),
        RibbonGroup(
            "Travel builders",
            buttons=(
                _button(
                    "Portal pair",
                    "◫",
                    "Nether portal travel builder · matched pair at the 8:1 "
                    "position",
                    surface="portalBuilder",
                    primary=True,
                ),
                _button(
                    "Rail tunnel",
                    "≣",
                    "Rail tunnel builder · custom walls, roofs, and lighting",
                    surface="railTunnel",
                    primary=True,
                ),
                _button(
                    "Linkage",
                    "⇄",
                    "Portal linkage report and ratio calculator",
                    surface="portalLinker",
                ),
                _button(
                    "Rail audit",
                    "⌁",
                    "Audit rail networks, powered rails, and junctions",
                    surface="railNetwork",
                ),
                _button(
                    "Beds",
                    "▤",
                    "Spawn points, beds, and respawn anchors",
                    surface="spawnPoints",
                ),
            ),
            launcher="railTunnel",
        ),
        RibbonGroup(
            "Mechanics",
            buttons=(
                _button(
                    "Spawn rules",
                    "◉",
                    "Mob spawning conditions per column",
                    surface="spawnAnalysis",
                ),
                _button(
                    "Light levels",
                    "☀",
                    "Light level overlay for spawn-proofing",
                    surface="lightOverlay",
                ),
                _button(
                    "Tick load",
                    "⏱",
                    "Random-tick and block-entity load per chunk",
                    surface="tickLoad",
                ),
            ),
            launcher="spawnAnalysis",
        ),
    ),
)

_WORLDGEN = RibbonTab(
    "worldgen",
    "Worldgen",
    (
        RibbonGroup(
            "Structures",
            buttons=(
                _button(
                    "Locate",
                    "⌖",
                    "Find generated structures by type",
                    surface="structureLocator",
                    primary=True,
                ),
                _button(
                    "Strongholds",
                    "◇",
                    "Stronghold ring positions from the seed",
                    surface="structureLocator",
                ),
                _button(
                    "Slime chunks",
                    "◍",
                    "Slime chunk grid for the world seed",
                    surface="slimeChunks",
                ),
            ),
            launcher="structureLocator",
        ),
        RibbonGroup(
            "Seed",
            buttons=(
                _button(
                    "Seed tools",
                    "⁘",
                    "Read, change, and reseed generation",
                    surface="seedTools",
                    primary=True,
                ),
                _button(
                    "Ore audit",
                    "▨",
                    "Ore distribution per Y layer",
                    surface="oreAudit",
                ),
                _button(
                    "Cave map",
                    "◠",
                    "Cave and ravine coverage per slice",
                    surface="caveMap",
                ),
            ),
            launcher="seedTools",
        ),
        RibbonGroup(
            "Boundaries",
            buttons=(
                _button(
                    "Border",
                    "▢",
                    "World border centre, size, and warning band",
                    surface="worldBorder",
                    primary=True,
                ),
                _button(
                    "Height limits",
                    "▬",
                    "Build range per platform and dimension",
                    surface="heightLimits",
                ),
                _button(
                    "Force loaded",
                    "⛁",
                    "Force-loaded and ticket-held chunks",
                    surface="forceLoaded",
                ),
            ),
            launcher="worldBorder",
        ),
    ),
)

_VIEW = RibbonTab(
    "view",
    "View",
    (
        RibbonGroup(
            "Appearance",
            buttons=(
                _button(
                    "Theme",
                    "◐",
                    "Switch light and dark",
                    command="toggleTheme",
                    primary=True,
                ),
                _button("Options", "⚙", "Open Options", surface="prefs"),
            ),
            selects=(
                RibbonSelect(
                    "Density",
                    _options(
                        ("compact", "Compact"),
                        ("comfortable", "Comfortable"),
                        ("spacious", "Spacious"),
                    ),
                    value="comfortable",
                    command="setDensity",
                ),
            ),
            launcher="presets",
        ),
        RibbonGroup(
            "Show",
            buttons=(
                _button(
                    "Properties",
                    "▤",
                    "Toggle the properties pane",
                    command="togglePane",
                ),
                _button(
                    "Ribbon",
                    "▬",
                    "Collapse or expand the ribbon",
                    command="toggleRibbon",
                ),
            ),
            launcher="viewControls",
        ),
        RibbonGroup(
            "Views",
            buttons=(
                _button(
                    "View",
                    "◱",
                    "View type, camera, and overlays",
                    surface="viewControls",
                    primary=True,
                ),
                _button(
                    "Four-up",
                    "⊞",
                    "Camera, overhead, and two elevations at once",
                    surface="fourUpView",
                ),
                _button(
                    "Cutaway",
                    "◧",
                    "Clip the world along a plane",
                    surface="cutawayView",
                ),
                _button(
                    "Work plane",
                    "▬",
                    "The fixed plane brushes snap to",
                    surface="workPlane",
                ),
            ),
            launcher="viewControls",
        ),
        RibbonGroup(
            "Layers",
            buttons=(
                _button(
                    "Layers",
                    "☰",
                    "Draw or hide each render layer",
                    surface="renderLayers",
                    primary=True,
                ),
                _button(
                    "Installs",
                    "⛁",
                    "Resource packs and texture atlas",
                    surface="minecraftInstalls",
                ),
            ),
            launcher="renderLayers",
        ),
    ),
)

_PANELS = RibbonTab(
    "panels",
    "Panels",
    (
        RibbonGroup(
            "Inspect",
            buttons=(
                _button(
                    "Inspector",
                    "⌕",
                    "Dockable inspector that follows the selection",
                    surface="inspector",
                    primary=True,
                ),
                _button(
                    "World info",
                    "▣",
                    "World identity, size on disk, time and weather",
                    surface="worldInfo",
                ),
                _button(
                    "Players",
                    "☺",
                    "Players, skins, positions, and inventories",
                    surface="playerPanel",
                ),
                _button(
                    "Inventory",
                    "▦",
                    "Slot-by-slot inventory editor",
                    surface="inventoryEditor",
                ),
            ),
            launcher="inspector",
        ),
        RibbonGroup(
            "Objects",
            buttons=(
                _button(
                    "Pending",
                    "⧉",
                    "Pending imports awaiting confirmation",
                    surface="pendingImports",
                    primary=True,
                ),
                _button(
                    "Library",
                    "❑",
                    "Schematic library with folders and previews",
                    surface="libraryPanel",
                ),
                _button(
                    "Maps",
                    "◫",
                    "Map items and image import",
                    surface="importMap",
                ),
            ),
            launcher="libraryPanel",
        ),
        RibbonGroup(
            "Diagnostics",
            buttons=(
                _button(
                    "Log",
                    "▤",
                    "Filterable application log",
                    surface="logView",
                ),
                _button(
                    "Profiler",
                    "⏱",
                    "Frame time and chunk-loading samples",
                    surface="profiler",
                ),
                _button(
                    "Console",
                    "⌨",
                    "Embedded Python console",
                    surface="pythonConsole",
                ),
                _button(
                    "Errors",
                    "⚠",
                    "Local error report with traceback",
                    surface="errorReport",
                ),
            ),
            launcher="logView",
        ),
    ),
)

_EXTEND = RibbonTab(
    "extend",
    "Extend",
    (
        RibbonGroup(
            "Pickers",
            buttons=(
                _button(
                    "Blocks",
                    "▨",
                    "Block picker with states and textures",
                    surface="blockSelect",
                    primary=True,
                ),
                _button(
                    "Items",
                    "◈",
                    "Item type list with textures",
                    surface="itemTypeList",
                ),
                _button("Biomes", "❋", "Biome picker", surface="biomeSelect"),
                _button(
                    "Define",
                    "✎",
                    "Configure block and item definitions",
                    surface="configureBlocks",
                ),
            ),
            launcher="blockSelect",
        ),
        RibbonGroup(
            "Resources",
            buttons=(
                _button(
                    "Installs",
                    "⛁",
                    "Minecraft installs, versions, and resource packs",
                    surface="minecraftInstalls",
                    primary=True,
                ),
                _button(
                    "Versions",
                    "◇",
                    "Platform and data version for handlers",
                    surface="versionSelect",
                ),
            ),
            launcher="minecraftInstalls",
        ),
        RibbonGroup(
            "Plugins",
            buttons=(
                _button(
                    "Plugins",
                    "✦",
                    "Installed tools, generators, and commands",
                    surface="pluginsDialog",
                    primary=True,
                ),
                _button(
                    "Generate",
                    "⁘",
                    "Generator plugins including L-system",
                    surface="generateTool",
                ),
                _button(
                    "Console",
                    "⌨",
                    "Operation console for Python extensions",
                    surface="scriptConsole",
                ),
            ),
            launcher="pluginsDialog",
        ),
    ),
)

_AUTOMATE = RibbonTab(
    "automate",
    "Automate",
    (
        RibbonGroup(
            "Scripting",
            buttons=(
                _button(
                    "Console",
                    "⌨",
                    "Operation console for Python extensions",
                    surface="scriptConsole",
                    primary=True,
                ),
                _button(
                    "Batch queue",
                    "⛁",
                    "Queue several operations across worlds",
                    surface="batchQueue",
                ),
                _button(
                    "Macro",
                    "⏺",
                    "Record and replay operation sequences",
                    surface="macroRecorder",
                ),
            ),
            launcher="scriptConsole",
        ),
        RibbonGroup(
            "Scheduling",
            buttons=(
                _button(
                    "Rules",
                    "◷",
                    "Scheduled language, theme, density, and accent rules",
                    surface="prefs",
                    primary=True,
                ),
            ),
            launcher="prefs",
        ),
        RibbonGroup(
            "Records",
            buttons=(
                _button(
                    "Notifications",
                    "◉",
                    "Notification history",
                    surface="notifications",
                ),
                _button("History", "⟲", "Version history", surface="history"),
                _button("Release notes", "♧", "Release notes", surface="changelog"),
            ),
            launcher="notifications",
        ),
        RibbonGroup(
            "Memory",
            buttons=(
                _button(
                    "Memory console",
                    "▤",
                    "Agent Global Memory Console",
                    surface="memory",
                    primary=True,
                ),
                _button(
                    "Regex builder",
                    ".*",
                    "Open the bounded regex builder",
                    surface="regex",
                ),
            ),
            launcher="memory",
        ),
    ),
)

#: Every ribbon tab, in the order the design's tab strip lists them.
RIBBON_TABS: Tuple[RibbonTab, ...] = (
    _HOME,
    _TOOLS,
    _SELECTION,
    _OPERATIONS,
    _STRUCTURES,
    _CHUNKS,
    _TERRAIN,
    _BUILD,
    _ENTITIES,
    _DATA,
    _ANALYZE,
    _REDSTONE,
    _WORLDGEN,
    _VIEW,
    _PANELS,
    _EXTEND,
    _AUTOMATE,
)

#: The tab keys in strip order, for persistence and keyboard navigation.
TAB_KEYS: Tuple[str, ...] = tuple(item.key for item in RIBBON_TABS)

_BY_KEY: Dict[str, RibbonTab] = {item.key: item for item in RIBBON_TABS}


def tab(key: str) -> Optional[RibbonTab]:
    """Return the tab with ``key``, or ``None`` when there is no such tab."""
    return _BY_KEY.get(str(key))


def buttons(tab_key: str) -> Tuple[RibbonButton, ...]:
    """Return every button on one tab, in visual order."""
    found = tab(tab_key)
    return found.buttons if found is not None else ()


def all_buttons() -> Tuple[Tuple[str, str, RibbonButton], ...]:
    """Return ``(tab key, group title, button)`` for every ribbon button.

    The command palette and the surface index both need the ribbon flattened
    with its provenance intact, so a result can say which tab and group a
    command lives on rather than showing a bare label.
    """
    rows: List[Tuple[str, str, RibbonButton]] = []
    for item in RIBBON_TABS:
        for group in item.groups:
            for button in group.buttons:
                rows.append((item.key, group.title, button))
    return tuple(rows)


def search(
    state: SearchState, tab_key: str = ""
) -> Tuple[Tuple[str, str, RibbonButton], ...]:
    """Filter ribbon buttons by ``state``, optionally within one tab.

    An invalid regular expression matches nothing here exactly as it does
    everywhere else; the failure is reported by the field's feedback line
    rather than being mistaken for an empty ribbon.
    """
    rows = all_buttons()
    if tab_key:
        rows = tuple(row for row in rows if row[0] == tab_key)
    return tuple(state.filter(rows, key=lambda row: row[2].haystack))


def surface_keys() -> Tuple[str, ...]:
    """Return every surface key the ribbon can open, sorted and unique."""
    keys = {button.surface for _tab, _group, button in all_buttons() if button.surface}
    keys.update(
        group.launcher
        for item in RIBBON_TABS
        for group in item.groups
        if group.launcher
    )
    return tuple(sorted(keys))


#: Every shell command key the ribbon can raise, sorted and unique.  The shell
#: registry is expected to contain each of these; a ribbon tile pointing at a
#: command nobody implemented would be a control that does nothing.
COMMAND_KEYS: Tuple[str, ...] = tuple(
    sorted(
        {button.command for _tab, _group, button in all_buttons() if button.command}
        | {
            select.command
            for item in RIBBON_TABS
            for group in item.groups
            for select in group.selects
            if select.command
        }
    )
)


def validate() -> Tuple[str, ...]:
    """Return every structural problem in the ribbon definition.

    Called by the test suite rather than at import time: a definition mistake
    should fail a check with a precise message, not stop the application from
    starting.  An empty result means every tab, group, button, and dropdown is
    wired to something real.
    """
    problems: List[str] = []
    seen: set = set()
    for item in RIBBON_TABS:
        if item.key in seen:
            problems.append(f"Duplicate ribbon tab key: {item.key}")
        seen.add(item.key)
        if not item.label:
            problems.append(f"Ribbon tab {item.key} has no label")
        if not item.groups:
            problems.append(f"Ribbon tab {item.key} has no groups")
        for group in item.groups:
            where = f"{item.key}/{group.title}"
            if not group.title:
                problems.append(f"A group on tab {item.key} has no title")
            if not group.launcher:
                problems.append(f"Group {where} has no dialog launcher")
            if not (group.buttons or group.fields or group.selects):
                problems.append(f"Group {where} has no controls")
            for button in group.buttons:
                if bool(button.surface) == bool(button.command):
                    problems.append(
                        f"Button {where}/{button.label} must name exactly one of "
                        "a surface or a command"
                    )
                if not button.glyph:
                    problems.append(f"Button {where}/{button.label} has no glyph")
                if not button.hint:
                    problems.append(f"Button {where}/{button.label} has no hint")
            for select in group.selects:
                if not select.options:
                    problems.append(f"Dropdown {where}/{select.label} has no options")
                if select.value and not select.label_for(select.value):
                    problems.append(
                        f"Dropdown {where}/{select.label} defaults to a value that "
                        "is not one of its options"
                    )
            for entry in group.fields:
                if not entry.label:
                    problems.append(f"A field in group {where} has no label")
    return tuple(problems)


def iter_tabs() -> Iterable[RibbonTab]:
    """Iterate the tabs in strip order."""
    return iter(RIBBON_TABS)
