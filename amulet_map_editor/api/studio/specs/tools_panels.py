"""Surface descriptions for the editing tools, the find-and-replace family, and
every dockable panel or view the ribbon can open.

The first half of this module transcribes the MCEdit2-derived tool surfaces —
brush, flood fill, clone, move, generate, the two pickers, the chunk editor,
tool settings, the three find-and-replace windows, analyze, and map import — so
each one keeps the exact wording, ordering, and values the design settled on.
The second half carries the panels and views the ribbon's Panels, View, and
Extend tabs launch: they are described here rather than as bespoke windows so
that a panel gains window search, the command palette, and the surface index
without a line of layout code.

Nothing in this module touches wxPython, so it imports on a machine with no
display and can be read by tests, the palette, and the surface index alike.
"""

from __future__ import annotations

from typing import Dict

from amulet_map_editor.api.studio.spec import (
    Action,
    Check,
    Field,
    RangeDef,
    Row,
    Select,
    Spec,
    SwatchDef,
    sec,
    tex_section,
)

_BRUSH_SETTINGS = Spec(
    key="brushSettings",
    eyebrow="Tools",
    title="Brush",
    width=700,
    confirm="Apply brush",
    intro=(
        "The brush paints blocks through a shape at the cursor. Mode decides "
        "what the stroke does with the blocks it touches."
    ),
    sections=(
        sec(
            "Shape",
            "chips",
            chips=[
                "Cube",
                "Sphere",
                "Cylinder",
                "Diamond",
                "Ellipsoid",
                "Square",
                "Disc",
                "Line",
            ],
        ),
        sec(
            "Mode",
            "selects",
            selects=[
                Select(
                    "Brush mode",
                    (
                        "Fill",
                        "Replace",
                        "Erase",
                        "Paint biome",
                        "Flood fill",
                        "Erode",
                        "Smooth",
                        "Raise/Lower",
                    ),
                ),
                Select(
                    "Fill block",
                    (
                        "minecraft:stone",
                        "minecraft:dirt",
                        "minecraft:grass_block",
                        "minecraft:sand",
                        "minecraft:deepslate",
                    ),
                ),
                Select(
                    "Replace block",
                    (
                        "minecraft:air",
                        "minecraft:stone",
                        "minecraft:water",
                        "Any block",
                    ),
                ),
            ],
        ),
        tex_section("minecraft:stone", "brush-fill-texture"),
        sec(
            "Size",
            "ranges",
            ranges=[
                RangeDef("Width", 7, 1, 64),
                RangeDef("Height", 7, 1, 64),
                RangeDef("Length", 7, 1, 64),
            ],
        ),
        sec(
            "Options",
            "checks",
            checks=[
                Check("Hollow", "Only the shell of the shape is painted."),
                Check("Noise", "Randomly skips blocks for a broken edge."),
                Check(
                    "Follow the work plane",
                    "Paints on the fixed plane instead of the surface under the cursor.",
                ),
            ],
        ),
    ),
    actions=(Action("Tool settings…", "outlined", surface="toolSettings"),),
)

_FLOOD_FILL = Spec(
    key="floodFill",
    eyebrow="Tools",
    title="Flood fill",
    width=620,
    confirm="Flood fill",
    intro=(
        "Replaces a connected region of matching blocks starting at the clicked "
        "block. The region is bounded by the selection and a block limit."
    ),
    sections=(
        sec(
            "Blocks",
            "selects",
            selects=[
                Select(
                    "Search block",
                    (
                        "minecraft:water",
                        "minecraft:air",
                        "minecraft:stone",
                        "Block under cursor",
                    ),
                ),
                Select(
                    "Replace with",
                    (
                        "minecraft:air",
                        "minecraft:stone",
                        "minecraft:sand",
                        "minecraft:glass",
                    ),
                ),
            ],
        ),
        tex_section("minecraft:water", "flood-search-texture"),
        sec(
            "Bounds",
            "fields",
            fields=[
                Field("Block limit", "200000"),
                Field("Confine to", "selection"),
            ],
        ),
        sec(
            "Connectivity",
            "selects",
            selects=[
                Select(
                    "Neighbours",
                    ("6 faces", "18 faces and edges", "26 including corners"),
                ),
                Select(
                    "Direction",
                    ("All directions", "Downward only", "Horizontal only"),
                ),
            ],
        ),
    ),
    actions=(Action("Preview region", "tonal"),),
)

_CLONE_TOOL = Spec(
    key="cloneTool",
    eyebrow="Tools",
    title="Clone",
    width=680,
    confirm="Confirm clone",
    intro=(
        "Copies the selection and places repeatable copies. The copy stays live "
        "until confirmed, so rotation and scale can be adjusted first."
    ),
    sections=(
        sec(
            "Offset",
            "fields",
            fields=[
                Field("x", "16"),
                Field("y", "0"),
                Field("z", "0"),
                Field("Repeat count", "3"),
            ],
        ),
        sec(
            "Transform",
            "selects",
            selects=[
                Select("Rotation", ("0°", "90°", "180°", "270°", "Free")),
                Select("Mirror", ("None", "East–west", "North–south", "Vertical")),
                Select("Scale", ("1×", "2×", "0.5×", "Custom")),
            ],
        ),
        sec(
            "Contents",
            "checks",
            checks=[
                Check("Copy air", "Air in the source overwrites the destination."),
                Check(
                    "Copy entities",
                    "Mobs, item frames, and vehicles travel with the clone.",
                ),
                Check("Copy biomes", "Biome data is copied with the blocks."),
            ],
        ),
    ),
    actions=(
        Action("Nudge by one block", "outlined"),
        Action("Cancel clone", "danger"),
    ),
)

_MOVE_TOOL = Spec(
    key="moveTool",
    eyebrow="Tools",
    title="Move",
    width=640,
    confirm="Confirm move",
    intro=(
        "Lifts the selection into a pending import you can drag, rotate, and "
        "scale before it is written back."
    ),
    sections=(
        sec(
            "Destination",
            "fields",
            fields=[
                Field("x", "-2"),
                Field("y", "98"),
                Field("z", "-49"),
                Field("Rotation", "0"),
            ],
        ),
        sec(
            "Behaviour",
            "checks",
            checks=[
                Check("Leave air behind", "The source volume is cleared."),
                Check(
                    "Keep the original in place",
                    "Turns the move into a copy.",
                ),
            ],
        ),
        sec(
            "Pending imports",
            "list",
            rows=[
                Row(
                    "spawn-arch (moving)",
                    "24×18×24 · rotation 90° · scale 1×",
                    "pending",
                ),
            ],
        ),
    ),
    actions=(Action("Pending imports panel", "outlined", surface="pendingImports"),),
)

_GENERATE_TOOL = Spec(
    key="generateTool",
    eyebrow="Tools",
    title="Generate",
    width=720,
    confirm="Generate into world",
    intro=(
        "Generators build an object inside the selection. Each generator is a "
        "plugin, so the list grows with whatever is installed."
    ),
    sections=(
        sec(
            "Generator",
            "selects",
            selects=[
                Select(
                    "Generator",
                    (
                        "Tree (L-system)",
                        "Cave system",
                        "Castle",
                        "Maze",
                        "Sphere",
                        "Pyramid",
                        "Terrain from image",
                    ),
                ),
                Select(
                    "Output",
                    ("Generate in world", "Import as pending object"),
                ),
            ],
        ),
        sec(
            "L-system",
            "fields",
            fields=[
                Field("Iterations", "5"),
                Field("Angle", "22.5"),
                Field("Axiom", "F"),
                Field("Rule F", "F[+F]F[-F]F"),
            ],
        ),
        sec(
            "Material",
            "selects",
            selects=[
                Select(
                    "Trunk block",
                    (
                        "minecraft:oak_log",
                        "minecraft:dark_oak_log",
                        "minecraft:spruce_planks",
                    ),
                ),
                Select(
                    "Leaf block",
                    ("minecraft:moss_block", "minecraft:glass", "minecraft:sculk"),
                ),
            ],
        ),
        tex_section("minecraft:oak_log", "generate-trunk-texture"),
        sec(
            "",
            "note",
            hint=(
                "Generated objects arrive as a pending import first, so nothing "
                "is written until you confirm placement."
            ),
        ),
    ),
    actions=(
        Action("Preview object", "tonal"),
        Action("Plugins…", "outlined", surface="pluginsDialog"),
    ),
)

_SELECT_BLOCK_TOOL = Spec(
    key="selectBlockTool",
    eyebrow="Tools",
    title="Select block",
    width=680,
    confirm="Close",
    intro=(
        "Clicking a block shows everything known about it: state, light, biome, "
        "and the block entity behind it."
    ),
    sections=(
        tex_section(
            "minecraft:chest",
            "inspect-block-texture",
            "Selecting a block shows its texture here. The tile is a generated "
            "placeholder until a resource pack is loaded.",
        ),
        sec(
            "Block",
            "list",
            rows=[
                Row(
                    "minecraft:chest",
                    "facing=north, type=single, waterlogged=false",
                    "state",
                ),
                Row("Position", "412, 71, 188 · chunk 25, 11", "at"),
                Row("Block light", "0", "light"),
                Row("Sky light", "15", "light"),
                Row("Biome", "minecraft:plains", "biome"),
                Row("Block entity", "chest with 14 item stacks", "nbt"),
            ],
        ),
    ),
    actions=(
        Action("Open NBT editor", "tonal", surface="nbt"),
        Action("Pick as fill block", "outlined"),
    ),
)

_SELECT_ENTITY_TOOL = Spec(
    key="selectEntityTool",
    eyebrow="Tools",
    title="Select entity",
    width=660,
    confirm="Close",
    sections=(
        sec(
            "Entity under cursor",
            "list",
            rows=[
                Row(
                    "minecraft:villager",
                    "412.5, 71.0, 188.5 · named Ana",
                    "entity",
                ),
                Row("Health", "20.0 / 20.0", "state"),
                Row("UUID", "6f1c…a904", "id"),
            ],
        ),
        sec(
            "Nearby",
            "list",
            rows=[
                Row("minecraft:cow", "3 within 8 blocks", "3"),
                Row("minecraft:item_frame", "2 within 8 blocks", "2"),
            ],
        ),
    ),
    actions=(
        Action("Edit entity", "tonal", surface="entityEdit"),
        Action("Entity browser", "outlined", surface="entityBrowser"),
    ),
)

_EDIT_CHUNK_TOOL = Spec(
    key="editChunkTool",
    eyebrow="Tools",
    title="Edit chunk",
    width=700,
    confirm="Apply to chunk",
    sections=(
        sec(
            "Chunk",
            "fields",
            fields=[Field("Chunk x", "25"), Field("Chunk z", "11")],
        ),
        sec(
            "Flags",
            "checks",
            checks=[
                Check(
                    "TerrainPopulated",
                    "Clearing this makes the game repopulate features.",
                ),
                Check("LightPopulated", "Clearing this forces a relight."),
                Check(
                    "Force load on next tick",
                    "Adds a ticket for this chunk.",
                ),
            ],
        ),
        sec(
            "Actions",
            "chips",
            chips=[
                "Create",
                "Delete",
                "Prune others",
                "Relight",
                "Repopulate",
                "Copy chunk",
                "Paste chunk",
            ],
        ),
        sec(
            "Raw tags",
            "list",
            rows=[
                Row("Status", "full", "tag"),
                Row("InhabitedTime", "3,600 ticks", "tag"),
                Row("LastUpdate", "148,291", "tag"),
            ],
        ),
    ),
    actions=(Action("Open chunk in NBT editor", "outlined", surface="nbt"),),
)

_TOOL_SETTINGS = Spec(
    key="toolSettings",
    eyebrow="Tools",
    title="Tool settings",
    width=680,
    confirm="Save tool settings",
    intro=(
        "Per-tool defaults persist between sessions, so a tool opens the way you "
        "left it."
    ),
    sections=(
        sec(
            "Tool",
            "selects",
            selects=[
                Select(
                    "Tool",
                    (
                        "Select",
                        "Brush",
                        "Clone",
                        "Move",
                        "Flood fill",
                        "Generate",
                        "Edit chunk",
                        "Select block",
                        "Select entity",
                    ),
                ),
                Select(
                    "On activation",
                    ("Restore last settings", "Reset to defaults"),
                ),
            ],
        ),
        sec(
            "Shared",
            "checks",
            checks=[
                Check(
                    "Show the tool's handles in the viewport",
                    "Corner and face handles for dragging.",
                ),
                Check(
                    "Snap handles to the block grid",
                    "Handles move in whole blocks.",
                ),
                Check(
                    "Confirm before writing to the world",
                    "Every tool asks before committing.",
                ),
            ],
        ),
        sec(
            "Handles",
            "ranges",
            ranges=[
                RangeDef("Handle size", 8, 4, 20),
                RangeDef("Selection distance", 12, 1, 64),
            ],
        ),
    ),
    actions=(Action("Reset this tool", "danger"),),
)

_FIND_REPLACE_BLOCKS = Spec(
    key="findReplaceBlocks",
    eyebrow="Find and replace",
    title="Blocks",
    width=760,
    confirm="Replace all",
    intro=(
        "Builds a replacement list, so several block swaps run in one pass over "
        "the selection."
    ),
    sections=(
        sec("", "search", hint="Search block names and states"),
        sec(
            "Replacement list",
            "list",
            rows=[
                Row("minecraft:stone", "→ minecraft:deepslate", "212"),
                Row("minecraft:oak_planks", "→ minecraft:spruce_planks", "48"),
                Row("minecraft:gravel", "→ minecraft:andesite", "16"),
            ],
        ),
        tex_section("minecraft:deepslate", "find-replace-texture"),
        sec(
            "Scope",
            "selects",
            selects=[
                Select(
                    "Search in",
                    ("Selection", "Loaded chunks", "Whole dimension"),
                ),
                Select(
                    "State matching",
                    (
                        "Ignore block states",
                        "Match exact state",
                        "Match listed properties only",
                    ),
                ),
            ],
        ),
    ),
    actions=(
        Action("Add replacement", "tonal"),
        Action("Find all", "outlined"),
        Action("Clear list", "danger"),
    ),
)

_FIND_REPLACE_COMMANDS = Spec(
    key="findReplaceCommands",
    eyebrow="Find and replace",
    title="Commands",
    width=780,
    confirm="Replace in commands",
    intro=(
        "Searches command blocks, signs, and command-bearing items, and can "
        "rewrite coordinates as a group when a build moves."
    ),
    sections=(
        sec("", "search", hint="Search command text"),
        sec(
            "Replace",
            "fields",
            fields=[
                Field("Find", "66 118 -43"),
                Field("Replace with", "412 71 188"),
            ],
        ),
        sec(
            "Sources",
            "checks",
            checks=[
                Check("Command blocks", "Impulse, chain, and repeating."),
                Check("Signs", "All four lines."),
                Check(
                    "Command-bearing items",
                    "Written books and spawn eggs with commands.",
                ),
            ],
        ),
        sec(
            "Coordinate mode",
            "selects",
            selects=[
                Select(
                    "Coordinates",
                    (
                        "Literal text only",
                        "Offset absolute coordinates",
                        "Convert to relative (~)",
                    ),
                ),
                Select(
                    "Offset",
                    ("Match the move I just made", "Custom offset"),
                ),
            ],
        ),
        sec(
            "Results",
            "list",
            rows=[
                Row("412, 70, 190", "/tp @p 66 118 -43", "match"),
                Row("96, 40, -12", "/execute positioned 66 118 -43 run …", "match"),
            ],
        ),
    ),
    actions=(
        Action("Find all", "tonal"),
        Action("Open regex builder", "outlined", surface="regex"),
    ),
)

_FIND_REPLACE_NBT = Spec(
    key="findReplaceNbt",
    eyebrow="Find and replace",
    title="NBT",
    width=780,
    confirm="Replace in tags",
    intro=(
        "Searches tag names and values across chunks, entities, block entities, "
        "and player data, with a results list you can step through."
    ),
    sections=(
        sec("", "search", hint="Search tag names and values"),
        sec(
            "Query",
            "fields",
            fields=[
                Field("Tag name", "CustomName"),
                Field("Value contains", "Storage"),
                Field("Replace value with", "Depot"),
                Field("Result limit", "2000"),
            ],
        ),
        sec(
            "Value type",
            "selects",
            selects=[
                Select(
                    "Tag type",
                    (
                        "Any",
                        "string",
                        "int",
                        "double",
                        "byte",
                        "compound",
                        "list",
                    ),
                ),
                Select("Match", ("Contains", "Exact", "Starts with", "Regex")),
            ],
        ),
        sec(
            "Results",
            "list",
            rows=[
                Row("chest at 88, 65, 24", "CustomName = Storage", "match"),
                Row(
                    "barrel at 412, 71, 188",
                    "CustomName = Storage overflow",
                    "match",
                ),
            ],
        ),
    ),
    actions=(
        Action("Find all", "tonal"),
        Action("Open NBT editor", "outlined", surface="nbt"),
    ),
)

_ANALYZE_TOOL = Spec(
    key="analyzeTool",
    eyebrow="Analysis",
    title="Analyze",
    width=740,
    confirm="Close",
    intro=(
        "Counts every block, entity, and block entity in the selection and "
        "reports the totals in one table."
    ),
    sections=(
        sec("", "search", hint="Search the analysis table"),
        sec(
            "Blocks",
            "list",
            rows=[
                Row("minecraft:stone", "212 blocks", "36.8%"),
                Row("minecraft:dirt", "148 blocks", "25.7%"),
                Row("minecraft:grass_block", "96 blocks", "16.7%"),
            ],
        ),
        sec(
            "Entities",
            "list",
            rows=[
                Row("minecraft:villager", "12 entities", "12"),
                Row("minecraft:chest", "23 block entities", "23"),
            ],
        ),
    ),
    actions=(
        Action("Export CSV", "outlined"),
        Action("Copy table", "outlined"),
    ),
)

_IMPORT_MAP = Spec(
    key="importMap",
    eyebrow="Import",
    title="Import map image",
    width=700,
    confirm="Import as map item",
    intro=(
        "Converts an image into map-item colour data, or into blocks using the "
        "closest matching palette."
    ),
    sections=(
        sec(
            "Source",
            "fields",
            fields=[
                Field("Image file", "", "Choose a PNG or JPEG"),
                Field("Scale", "1"),
            ],
        ),
        sec(
            "Target",
            "selects",
            selects=[
                Select(
                    "Import as",
                    (
                        "Map item colours",
                        "Blocks (closest palette match)",
                        "Both",
                    ),
                ),
                Select("Dithering", ("None", "Floyd–Steinberg", "Ordered")),
                Select(
                    "Palette",
                    (
                        "Map colours",
                        "Full block palette",
                        "Concrete only",
                        "Wool only",
                    ),
                ),
            ],
        ),
        sec(
            "Placement",
            "fields",
            fields=[Field("Centre x", "64"), Field("Centre z", "-32")],
        ),
        sec(
            "",
            "note",
            hint=(
                "Block conversion picks the nearest palette entry per pixel and "
                "reports the palette it used, rather than guessing silently."
            ),
        ),
    ),
    actions=(
        Action("Preview conversion", "tonal"),
        Action("Map items panel", "outlined", surface="mapItems"),
    ),
)

_INSPECTOR = Spec(
    key="inspector",
    eyebrow="Panels",
    title="Inspector",
    width=740,
    confirm="Close",
    intro=(
        "A dockable panel that follows the selection: block, entity, chunk, or "
        "player, with a live property list."
    ),
    sections=(
        sec(
            "Target",
            "selects",
            selects=[
                Select(
                    "Inspecting",
                    (
                        "Block under cursor",
                        "Selected entity",
                        "Current chunk",
                        "Player",
                        "Pending import",
                    ),
                ),
                Select("Follow", ("Follow the cursor", "Pin to this target")),
            ],
        ),
        sec(
            "Properties",
            "list",
            rows=[
                Row("id", "minecraft:chest", "string"),
                Row("facing", "north", "state"),
                Row("Items", "14 stacks", "list"),
                Row("Light", "block 0 · sky 15", "computed"),
            ],
        ),
        tex_section("minecraft:chest", "inspector-texture"),
    ),
    actions=(
        Action("Open NBT editor", "tonal", surface="nbt"),
        Action("Pin to this target", "outlined"),
        Action("Dock to the properties pane", "outlined"),
    ),
)

_WORLD_INFO = Spec(
    key="worldInfo",
    eyebrow="Panels",
    title="World info",
    width=740,
    confirm="Save world info",
    intro=(
        "World identity, size on disk, time, and weather, read from level.dat "
        "and the region files rather than guessed. Editing anything here "
        "rewrites level.dat and is recorded as its own revision."
    ),
    sections=(
        sec("", "search", hint="Search world properties"),
        sec(
            "Identity",
            "list",
            rows=[
                Row("World name", "1.17 Height", "level.dat"),
                Row(
                    "Folder",
                    "%APPDATA%\\.minecraft\\saves\\1-17-height",
                    "path",
                ),
                Row("Platform", "bedrock 1.17.0.1", "format"),
                Row("Data version", "2730", "version"),
                Row("Seed", "-4172144997902289642", "seed"),
                Row("Last played", "10 Aug 2026, 09:41", "time"),
            ],
        ),
        sec(
            "Size on disk",
            "list",
            rows=[
                Row("Region files", "184 files · 1.62 GB", "region"),
                Row("Entity files", "184 files · 96.4 MB", "entities"),
                Row("Player data", "3 files · 412 KB", "playerdata"),
                Row(
                    "Project repository",
                    "1,284 revisions · 240 MB beside the world, never inside it",
                    "isolated",
                ),
            ],
        ),
        sec(
            "Dimensions",
            "list",
            rows=[
                Row(
                    "minecraft:overworld",
                    "y -64 to 320 · 168 chunks loaded",
                    "dimension",
                ),
                Row(
                    "minecraft:the_nether",
                    "y 0 to 128 · 0 chunks loaded",
                    "dimension",
                ),
                Row(
                    "minecraft:the_end",
                    "y 0 to 256 · 0 chunks loaded",
                    "dimension",
                ),
            ],
        ),
        sec(
            "Time and weather",
            "selects",
            selects=[
                Select(
                    "Time of day",
                    (
                        "Dawn (0)",
                        "Noon (6000)",
                        "Dusk (12000)",
                        "Midnight (18000)",
                        "Custom tick",
                    ),
                    "Noon (6000)",
                ),
                Select("Weather", ("Clear", "Rain", "Thunder")),
                Select(
                    "Difficulty",
                    ("Peaceful", "Easy", "Normal", "Hard"),
                    "Normal",
                ),
            ],
        ),
        sec(
            "Spawn",
            "fields",
            fields=[
                Field("Spawn x", "64"),
                Field("Spawn y", "72"),
                Field("Spawn z", "-32"),
                Field("World name", "1.17 Height"),
            ],
        ),
        sec(
            "Flags",
            "checks",
            checks=[
                Check(
                    "Hardcore",
                    "Death is permanent for every player in this world.",
                ),
                Check(
                    "Allow commands",
                    "Cheats are enabled for the world.",
                    True,
                ),
                Check(
                    "Difficulty locked",
                    "The difficulty cannot be changed from inside the game.",
                ),
                Check(
                    "Keep the folder read-only",
                    "Amulet opens the world but refuses every write.",
                ),
            ],
        ),
        sec(
            "",
            "note",
            hint=(
                "Sizes are measured from the files on disk. A world open in "
                "Minecraft is reported as locked instead of edited, because two "
                "writers would corrupt the region files."
            ),
        ),
    ),
    actions=(
        Action("Edit level.dat", "tonal", surface="levelDat"),
        Action("Game rules", "outlined", surface="gamerules"),
        Action("Project history", "outlined", surface="history"),
    ),
)

_PLAYER_PANEL = Spec(
    key="playerPanel",
    eyebrow="Panels",
    title="Players",
    width=760,
    confirm="Save player",
    intro=(
        "Every player folder in the world, with position, dimension, health, and "
        "the inventory behind it. Skins are read from the local install cache; "
        "nothing is downloaded."
    ),
    sections=(
        sec("", "search", hint="Search players by name or UUID"),
        sec(
            "Players",
            "list",
            rows=[
                Row(
                    "Ana",
                    "412.5, 71.0, 188.5 · minecraft:overworld · survival",
                    "selected",
                ),
                Row(
                    "Devi",
                    "-118.0, 63.0, 402.5 · minecraft:overworld · creative",
                    "player",
                ),
                Row(
                    "Singleplayer",
                    "66.4, 118.1, -43.1 · minecraft:the_nether · spectator",
                    "local",
                ),
            ],
        ),
        sec(
            "Selected player",
            "list",
            rows=[
                Row("UUID", "6f1c8b2e-40a7-4d19-9a2c-3d61f0aea904", "id"),
                Row("Health", "20.0 / 20.0", "state"),
                Row("Food", "17 · saturation 4.2", "state"),
                Row("Experience", "level 34 · 12,482 points", "state"),
                Row("Spawn point", "64, 72, -32 · minecraft:overworld", "spawn"),
                Row("Inventory", "27 of 41 slots used", "items"),
                Row("Ender chest", "6 of 27 slots used", "items"),
                Row("Last death", "-204, 41, 512 · minecraft:overworld", "recorded"),
            ],
        ),
        sec(
            "Position",
            "fields",
            fields=[
                Field("x", "412.5"),
                Field("y", "71.0"),
                Field("z", "188.5"),
                Field("Yaw", "-134.5"),
                Field("Pitch", "18.0"),
            ],
        ),
        sec(
            "State",
            "selects",
            selects=[
                Select(
                    "Game mode",
                    ("Survival", "Creative", "Adventure", "Spectator"),
                    "Survival",
                ),
                Select(
                    "Dimension",
                    (
                        "minecraft:overworld",
                        "minecraft:the_nether",
                        "minecraft:the_end",
                    ),
                    "minecraft:overworld",
                ),
            ],
        ),
        sec(
            "Flags",
            "checks",
            checks=[
                Check("Flying", "The player is airborne when the world loads."),
                Check("Invulnerable", "Damage is ignored."),
                Check(
                    "Clear the recorded death location",
                    "Removes LastDeathLocation so no compass points at it.",
                ),
            ],
        ),
        sec(
            "",
            "note",
            hint=(
                "Moving a player outside the world border or below the height "
                "limit is written exactly as typed and reported, rather than "
                "quietly clamped."
            ),
        ),
    ),
    actions=(
        Action("Open inventory", "tonal", surface="inventoryEditor"),
        Action("Player data", "outlined", surface="playerData"),
        Action("Open NBT editor", "outlined", surface="nbt"),
        Action("Delete player data", "danger"),
    ),
)

_INVENTORY_EDITOR = Spec(
    key="inventoryEditor",
    eyebrow="Panels",
    title="Inventory editor",
    width=780,
    confirm="Save inventory",
    intro=(
        "Slot-by-slot editing for any container: a player, a chest, a shulker "
        "box, or a pending import. This is the same slot grid the NBT editor "
        "shows for an Items list, so an edit made here reads identically there."
    ),
    sections=(
        sec("", "search", hint="Search slots by item id or count"),
        sec(
            "Container",
            "selects",
            selects=[
                Select(
                    "Container",
                    (
                        "Player: Ana",
                        "Chest at 412, 71, 188",
                        "Barrel at 88, 65, 24",
                        "Shulker box in slot 4",
                        "Ender chest: Ana",
                    ),
                    "Player: Ana",
                ),
                Select(
                    "Layout",
                    (
                        "Player inventory (41 slots)",
                        "Chest (27 slots)",
                        "Double chest (54 slots)",
                        "Hotbar only (9 slots)",
                    ),
                    "Player inventory (41 slots)",
                ),
            ],
        ),
        sec(
            "Slots",
            "list",
            rows=[
                Row(
                    "Slot 0 · hotbar",
                    "minecraft:diamond_pickaxe · Efficiency V, Unbreaking III",
                    "1",
                ),
                Row("Slot 1 · hotbar", "minecraft:bread", "32"),
                Row("Slot 2 · hotbar", "minecraft:torch", "64"),
                Row("Slot 3 · hotbar", "empty", "—"),
                Row("Slot 4 · hotbar", "minecraft:filled_map · map #12", "1"),
                Row("Slot 9 · main", "minecraft:coal", "64"),
                Row("Slot 10 · main", "minecraft:iron_ingot", "48"),
                Row("Slot 11 · main", "minecraft:gold_ingot", "12"),
                Row("Slot 100 · boots", "empty", "—"),
                Row("Slot 103 · helmet", "empty", "—"),
                Row("Slot -106 · offhand", "minecraft:chest", "1"),
            ],
        ),
        sec(
            "Selected slot",
            "fields",
            fields=[
                Field("Item id", "minecraft:diamond_pickaxe"),
                Field("Count", "1"),
                Field("Slot", "0"),
                Field("Damage", "42"),
                Field("Custom name", "", "Leave empty for the default name"),
            ],
        ),
        tex_section("minecraft:diamond_pickaxe", "inventory-slot-texture"),
        sec(
            "Enchantments",
            "list",
            rows=[
                Row("minecraft:efficiency", "level 5", "enchantment"),
                Row("minecraft:unbreaking", "level 3", "enchantment"),
                Row("minecraft:mending", "level 1", "enchantment"),
            ],
        ),
        sec(
            "Rules",
            "checks",
            checks=[
                Check(
                    "Keep enchantments when the item id changes",
                    "Off drops tags the new item cannot carry.",
                ),
                Check(
                    "Clamp the count to the item's stack size",
                    "Off writes the count exactly as typed.",
                ),
                Check(
                    "Write empty slots as absent entries",
                    "Matches what the game itself writes.",
                    True,
                ),
            ],
        ),
        sec(
            "",
            "note",
            hint=(
                "A count above the item's stack size is written exactly as "
                "typed, because some worlds rely on it. The clamp option is off "
                "by default and says so here rather than surprising you later."
            ),
        ),
    ),
    actions=(
        Action("Open NBT editor", "tonal", surface="nbt"),
        Action("Item types", "outlined", surface="itemTypeList"),
        Action("Copy container", "outlined"),
        Action("Clear container", "danger"),
    ),
)

_PENDING_IMPORTS = Spec(
    key="pendingImports",
    eyebrow="Panels",
    title="Pending imports",
    width=760,
    confirm="Confirm all",
    intro=(
        "Objects that have been placed in the world but not written to it. Each "
        "one keeps its own transform until you confirm or discard it, so a "
        "placement can be nudged for as long as you like."
    ),
    sections=(
        sec("", "search", hint="Search pending imports by name or size"),
        sec(
            "Queue",
            "list",
            rows=[
                Row(
                    "spawn-arch",
                    "24×18×24 at -2, 98, -49 · rotation 90° · scale 1×",
                    "moving",
                ),
                Row(
                    "market-row",
                    "48×12×32 at 412, 71, 188 · rotation 0° · scale 1×",
                    "placed",
                ),
                Row(
                    "tree-lsystem-5",
                    "17×26×17 at 96, 64, -12 · generated by the L-system plugin",
                    "generated",
                ),
            ],
        ),
        sec(
            "Selected object",
            "selects",
            selects=[
                Select("Rotation", ("0°", "90°", "180°", "270°", "Free"), "90°"),
                Select("Mirror", ("None", "East–west", "North–south", "Vertical")),
                Select("Scale", ("1×", "2×", "0.5×", "Custom")),
            ],
        ),
        sec(
            "Placement",
            "fields",
            fields=[
                Field("x", "-2"),
                Field("y", "98"),
                Field("z", "-49"),
                Field("Nudge step", "1"),
            ],
        ),
        sec(
            "Contents",
            "checks",
            checks=[
                Check(
                    "Write air from the object",
                    "Air in the object clears whatever it lands on.",
                ),
                Check(
                    "Write entities",
                    "Mobs, item frames, and vehicles come with the object.",
                    True,
                ),
                Check("Write biomes", "Biome data is written with the blocks."),
                Check(
                    "Keep the object after writing",
                    "Leaves it in the queue so it can be stamped again.",
                ),
            ],
        ),
        sec(
            "Progress",
            "progress",
            hint="Writing confirmed objects into the world",
            progress_label="0 of 3",
            progress_fraction=0.0,
        ),
        sec(
            "",
            "note",
            hint=(
                "Nothing in this queue has touched the world yet. Discarding a "
                "pending import loses the placement only; the structure it came "
                "from is still in the library."
            ),
        ),
    ),
    actions=(
        Action("Move tool", "outlined", surface="moveTool"),
        Action("Library", "outlined", surface="libraryPanel"),
        Action("Nudge by one block", "outlined"),
        Action("Discard selected", "danger"),
    ),
)

_LIBRARY_PANEL = Spec(
    key="libraryPanel",
    eyebrow="Panels",
    title="Schematic library",
    width=780,
    confirm="Import selected",
    intro=(
        "Folders of saved structures with a preview, a size, and the format each "
        "one was written in. Importing places the structure as a pending import "
        "first, so nothing is written until you confirm it."
    ),
    sections=(
        sec("", "search", hint="Search the library by name, folder, or format"),
        sec(
            "Source",
            "selects",
            selects=[
                Select(
                    "Folder",
                    ("All folders", "builds", "redstone", "terrain", "imported"),
                    "All folders",
                ),
                Select(
                    "Format",
                    (
                        "Any",
                        ".construction",
                        ".schem",
                        ".schematic",
                        ".mcstructure",
                        ".nbt",
                    ),
                    "Any",
                ),
                Select(
                    "Sort by",
                    ("Name", "Newest first", "Largest first", "Folder"),
                    "Newest first",
                ),
            ],
        ),
        sec(
            "Structures",
            "list",
            rows=[
                Row(
                    "spawn-arch.construction",
                    "24×18×24 · 8,208 blocks · builds · saved 09 Aug 2026, 20:14",
                    ".construction",
                ),
                Row(
                    "market-row.schem",
                    "48×12×32 · 18,432 blocks · builds",
                    ".schem",
                ),
                Row(
                    "sorter-4x.schematic",
                    "12×9×14 · 1,512 blocks · redstone",
                    ".schematic",
                ),
                Row(
                    "hillside.mcstructure",
                    "64×40×64 · bedrock export · terrain",
                    ".mcstructure",
                ),
                Row(
                    "debug-1-14.nbt",
                    "16×16×16 · vanilla structure block · imported",
                    ".nbt",
                ),
            ],
        ),
        tex_section(
            "minecraft:stone_bricks",
            "library-preview-texture",
            "The preview tile is generated from the structure's most common "
            "block. It is a placeholder, not the game texture; load a resource "
            "pack or drop a PNG to show the real one.",
        ),
        sec(
            "Selected structure",
            "fields",
            fields=[
                Field("Name", "spawn-arch"),
                Field("Folder", "builds"),
                Field("Saved", "09 Aug 2026, 20:14"),
                Field(
                    "Library root",
                    "%LOCALAPPDATA%\\Amulet\\library",
                    "Choose the folder that holds your structures",
                ),
            ],
        ),
        sec(
            "Import",
            "checks",
            checks=[
                Check(
                    "Place at the camera instead of the saved position",
                    "Off restores the coordinates the structure was saved at.",
                    True,
                ),
                Check(
                    "Convert blocks to the open world's version",
                    "Off imports the raw palette and reports anything unknown.",
                    True,
                ),
                Check(
                    "Include entities saved with the structure",
                    "Mobs and item frames come with it.",
                ),
            ],
        ),
        sec(
            "",
            "note",
            hint=(
                "The library is a folder on this machine. Nothing is uploaded "
                "and nothing is downloaded; deleting a structure here deletes "
                "the file."
            ),
        ),
    ),
    actions=(
        Action("Export selection to library", "tonal"),
        Action("New folder", "outlined"),
        Action("Reveal in file browser", "outlined"),
        Action("Delete structure", "danger"),
    ),
)

_LOG_VIEW = Spec(
    key="logView",
    eyebrow="Diagnostics",
    title="Log",
    width=800,
    confirm="Close",
    intro=(
        "The application log for this session, filterable by level and source. "
        "The log file stays on this machine; copying it into an issue is "
        "something you do deliberately."
    ),
    sections=(
        sec("", "search", hint="Search log messages"),
        sec(
            "Filter",
            "selects",
            selects=[
                Select(
                    "Level",
                    ("All", "Debug", "Info", "Warning", "Error", "Critical"),
                    "Info",
                ),
                Select(
                    "Source",
                    (
                        "All",
                        "amulet.api",
                        "amulet_map_editor.programs",
                        "renderer",
                        "plugins",
                        "operations",
                    ),
                    "All",
                ),
                Select("Order", ("Newest first", "Oldest first"), "Newest first"),
            ],
        ),
        sec(
            "Entries",
            "list",
            rows=[
                Row(
                    "09:41:12 INFO",
                    "Applied Fill to 12 chunks · committed a91f0c7",
                    "operations",
                ),
                Row(
                    "09:41:12 INFO",
                    "Recorded revision a91f0c7 in the project repository",
                    "history",
                ),
                Row(
                    "09:38:04 WARNING",
                    "Chunk 25, 11 holds an unknown block state "
                    "minecraft:cave_vines_body[age=25]",
                    "amulet.api",
                ),
                Row(
                    "09:37:55 ERROR",
                    "plugins/loot_tables.py failed to import: "
                    "ModuleNotFoundError: No module named 'yaml'",
                    "plugins",
                ),
                Row(
                    "09:36:40 INFO",
                    "Texture atlas built for bedrock 1.17.0.1 in 4.2 s",
                    "renderer",
                ),
                Row(
                    "09:36:12 DEBUG",
                    "OpenGL 4.6 context created · 1,904 block models loaded",
                    "renderer",
                ),
                Row(
                    "09:36:02 INFO",
                    "Opened 1.17 Height · bedrock 1.17.0.1 · 168 chunks indexed",
                    "amulet.api",
                ),
            ],
        ),
        sec(
            "File",
            "fields",
            fields=[
                Field(
                    "Log file",
                    "%LOCALAPPDATA%\\Amulet\\logs\\amulet-2026-08-10.log",
                ),
                Field("Rotation", "10 files · 5 MB each"),
            ],
        ),
        sec(
            "View",
            "checks",
            checks=[
                Check(
                    "Follow new entries",
                    "Scrolls to the newest line as it arrives.",
                    True,
                ),
                Check(
                    "Include debug entries",
                    "Debug lines are written to the file either way.",
                ),
                Check("Wrap long lines", "Off keeps one entry per row."),
            ],
        ),
        sec(
            "",
            "note",
            hint=(
                "World paths and player names can appear in log lines. Read an "
                "export before attaching it to a public issue."
            ),
        ),
    ),
    actions=(
        Action("Copy selected", "outlined"),
        Action("Export log", "outlined"),
        Action("Open log folder", "outlined"),
        Action("Error report", "outlined", surface="errorReport"),
        Action("Clear log view", "danger"),
    ),
)

_PROFILER = Spec(
    key="profiler",
    eyebrow="Diagnostics",
    title="Profiler",
    width=780,
    confirm="Close",
    intro=(
        "Frame time and chunk-loading samples for the running session. Sampling "
        "is off until you start it, so it never costs anything you did not ask "
        "for."
    ),
    sections=(
        sec(
            "Sampling",
            "progress",
            hint="Collecting frame samples",
            progress_label="240 of 600 frames",
            progress_fraction=0.4,
        ),
        sec(
            "Frame time",
            "list",
            rows=[
                Row("Median frame", "8.4 ms · 119 frames per second", "good"),
                Row("95th percentile", "16.9 ms · 59 frames per second", "watch"),
                Row("Worst frame", "62.1 ms during a chunk mesh upload", "spike"),
                Row("Draw calls", "1,842 per frame", "1842"),
                Row("Triangles", "3.1 million per frame", "3.1M"),
                Row("Dropped frames", "4 of 240 sampled", "4"),
            ],
        ),
        sec(
            "Chunk loading",
            "list",
            rows=[
                Row("Chunks decoded", "168 chunks · median 11.2 ms each", "168"),
                Row("Mesh build", "median 18.6 ms per chunk", "18.6 ms"),
                Row("Upload to GPU", "median 3.1 ms per chunk", "3.1 ms"),
                Row("Queue depth", "12 chunks waiting to mesh", "12"),
                Row("Worker threads", "4 of 8 cores in use", "4"),
            ],
        ),
        sec(
            "Operations",
            "list",
            rows=[
                Row("Fill (last run)", "2.8 s over 12 chunks", "operation"),
                Row("Relight (last run)", "6.1 s over 38 chunks", "operation"),
                Row("Repository commit", "0.4 s per revision", "history"),
            ],
        ),
        sec(
            "Sampling",
            "selects",
            selects=[
                Select(
                    "Sample",
                    (
                        "Frame time",
                        "Chunk loading",
                        "Operations",
                        "Everything",
                    ),
                    "Frame time",
                ),
                Select(
                    "Duration",
                    ("600 frames", "10 seconds", "60 seconds", "Until stopped"),
                    "600 frames",
                ),
            ],
        ),
        sec(
            "Options",
            "checks",
            checks=[
                Check(
                    "Record while the camera is still",
                    "Off samples only while the view is moving.",
                    True,
                ),
                Check(
                    "Include Python operation time",
                    "Adds plugin and operation timings to the samples.",
                ),
                Check(
                    "Write samples to the log",
                    "Off keeps the samples in memory until exported.",
                ),
            ],
        ),
        sec(
            "",
            "note",
            hint=(
                "Samples stay in memory unless you export them. The export is a "
                "plain CSV with one row per sample, readable anywhere."
            ),
        ),
    ),
    actions=(
        Action("Start sampling", "tonal"),
        Action("Stop", "outlined"),
        Action("Export CSV", "outlined"),
        Action("Render layers", "outlined", surface="renderLayers"),
        Action("Clear samples", "danger"),
    ),
)

_PYTHON_CONSOLE = Spec(
    key="pythonConsole",
    eyebrow="Diagnostics",
    title="Python console",
    width=800,
    confirm="Close",
    intro=(
        "An embedded console bound to the open world. Anything it can do, an "
        "operation script can do; the console is for trying it once before "
        "writing it down."
    ),
    sections=(
        sec(
            "Session",
            "code",
            code=(
                ">>> world.level_wrapper.platform\n"
                "'bedrock'\n"
                ">>> selection.volume\n"
                "578\n"
                ">>> sum(1 for _ in world.all_chunk_coords('minecraft:overworld'))\n"
                "168\n"
                ">>> world.get_version_block(412, 71, 188, 'minecraft:overworld',\n"
                "...                         ('bedrock', (1, 17, 0)))\n"
                "(Block(minecraft:chest[facing=north]), BlockEntity(minecraft:chest))"
            ),
        ),
        sec(
            "Bindings",
            "fields",
            fields=[
                Field("world", "the open Amulet level"),
                Field("selection", "the current selection group"),
                Field("dimension", "minecraft:overworld"),
                Field("options", "the dict an operation would receive"),
            ],
        ),
        sec(
            "Run",
            "selects",
            selects=[
                Select(
                    "Interpreter",
                    (
                        "Bundled Python 3.11",
                        "Bundled Python 3.11 with the plugins folder on the path",
                    ),
                    "Bundled Python 3.11",
                ),
                Select(
                    "On error",
                    (
                        "Show the traceback here",
                        "Show the traceback and open the error report",
                    ),
                    "Show the traceback here",
                ),
            ],
        ),
        sec(
            "Safety",
            "checks",
            checks=[
                Check(
                    "Record every statement in the log",
                    "The log keeps what was run and when.",
                    True,
                ),
                Check(
                    "Commit a revision after a statement writes to the world",
                    "Keeps console edits inside the same unlimited undo depth.",
                    True,
                ),
                Check(
                    "Ask before a statement writes to the world",
                    "Off lets a write run as soon as you press Run.",
                    True,
                ),
            ],
        ),
        sec(
            "",
            "note",
            hint=(
                "The console runs locally with the editor's own permissions and "
                "has no network access. A statement that writes blocks is a real "
                "edit, undoable through the project repository like any other."
            ),
        ),
    ),
    actions=(
        Action("Run selection", "tonal"),
        Action("Operation console", "outlined", surface="scriptConsole"),
        Action("Open log", "outlined", surface="logView"),
        Action("Clear session", "danger"),
    ),
)

_ERROR_REPORT = Spec(
    key="errorReport",
    eyebrow="Diagnostics",
    title="Error report",
    width=780,
    confirm="Close",
    intro=(
        "The last unhandled error, with the traceback exactly as Python raised "
        "it. The report stays on this machine: nothing is sent anywhere unless "
        "you export it and attach it yourself."
    ),
    sections=(
        sec(
            "Error",
            "list",
            rows=[
                Row("Type", "ModuleNotFoundError", "error"),
                Row("Message", "No module named 'yaml'", "message"),
                Row("Raised", "10 Aug 2026, 09:37:55", "time"),
                Row("While", "Loading plugin plugins/loot_tables.py", "context"),
                Row("Build", "0.10.0-dev.414 · unsigned by policy", "version"),
                Row("World open", "1.17 Height · bedrock 1.17.0.1", "world"),
            ],
        ),
        sec(
            "Traceback",
            "code",
            code=(
                "Traceback (most recent call last):\n"
                '  File "amulet_map_editor/api/plugins/loader.py", line 118, '
                "in load_plugin\n"
                "    module = importlib.import_module(module_name)\n"
                '  File "importlib/__init__.py", line 126, in import_module\n'
                "    return _bootstrap._gcd_import(name[level:], package, level)\n"
                '  File "<frozen importlib._bootstrap>", line 1204, in _gcd_import\n'
                '  File "plugins/loot_tables.py", line 4, in <module>\n'
                "    import yaml\n"
                "ModuleNotFoundError: No module named 'yaml'"
            ),
        ),
        sec(
            "Environment",
            "list",
            rows=[
                Row("Python", "3.11.9 · 64-bit", "runtime"),
                Row("wxPython", "4.2.1 msw (phoenix)", "toolkit"),
                Row("OpenGL", "4.6.0 · vendor driver 552.22", "renderer"),
                Row("Operating system", "Windows 11 · build 26200", "os"),
                Row("Display scale", "150% · 2560 × 1440", "display"),
            ],
        ),
        sec(
            "Include in the export",
            "checks",
            checks=[
                Check(
                    "The session log",
                    "Adds amulet-2026-08-10.log to the exported file.",
                    True,
                ),
                Check(
                    "The world path",
                    "Off replaces the path with the world name only.",
                ),
                Check(
                    "The open project name",
                    "Off exports the report without naming the project.",
                ),
            ],
        ),
        sec(
            "",
            "note",
            hint=(
                "This report is written to disk beside the log and never leaves "
                "the machine on its own. Read what an export contains before "
                "attaching it to a public issue."
            ),
        ),
    ),
    actions=(
        Action("Copy report", "tonal"),
        Action("Export report", "outlined"),
        Action("Open log", "outlined", surface="logView"),
        Action("Plugins", "outlined", surface="pluginsDialog"),
        Action("Clear report", "danger"),
    ),
)

_ITEM_TYPE_LIST = Spec(
    key="itemTypeList",
    eyebrow="Extend",
    title="Item types",
    width=760,
    confirm="Use this item",
    intro=(
        "Every item the loaded version defines, with the tile the pickers will "
        "show for it. Tiles are generated placeholders until an install and a "
        "resource pack are both loaded."
    ),
    sections=(
        sec("", "search", hint="Search item names and ids"),
        sec(
            "Source",
            "selects",
            selects=[
                Select(
                    "Platform and version",
                    ("bedrock 1.17.0.1", "java 1.20.4"),
                    "bedrock 1.17.0.1",
                ),
                Select("Namespace", ("minecraft", "amulet"), "minecraft"),
                Select(
                    "Group",
                    (
                        "All items",
                        "Block items",
                        "Tools and weapons",
                        "Food",
                        "Maps and books",
                        "Spawn eggs",
                        "Materials",
                    ),
                    "All items",
                ),
            ],
        ),
        sec(
            "Items",
            "list",
            rows=[
                Row(
                    "minecraft:diamond_pickaxe",
                    "Tool · stack size 1 · durability 1,561",
                    "tool",
                ),
                Row("minecraft:bread", "Food · stack size 64 · restores 5", "food"),
                Row(
                    "minecraft:filled_map",
                    "Map · stack size 1 · scale 1:8",
                    "map",
                ),
                Row("minecraft:coal", "Fuel · stack size 64", "material"),
                Row("minecraft:iron_ingot", "Material · stack size 64", "material"),
                Row("minecraft:gold_ingot", "Material · stack size 64", "material"),
                Row("minecraft:chest", "Block item · stack size 64", "block"),
                Row("minecraft:torch", "Block item · stack size 64", "block"),
            ],
        ),
        tex_section("minecraft:diamond_pickaxe", "item-type-texture"),
        sec(
            "Selected item",
            "fields",
            fields=[
                Field("Item id", "minecraft:diamond_pickaxe"),
                Field("Count", "1"),
                Field("Damage", "0"),
                Field("Custom name", "", "Leave empty for the default name"),
            ],
        ),
        sec(
            "",
            "note",
            hint=(
                "An item the loaded version does not define can still be typed "
                "in. It is written exactly as typed and listed as unknown here, "
                "rather than being silently dropped."
            ),
        ),
    ),
    actions=(
        Action("Add to inventory", "tonal", surface="inventoryEditor"),
        Action("Configure definitions", "outlined", surface="configureBlocks"),
        Action("Minecraft installs", "outlined", surface="minecraftInstalls"),
    ),
)

_CONFIGURE_BLOCKS = Spec(
    key="configureBlocks",
    eyebrow="Extend",
    title="Configure blocks and items",
    width=800,
    confirm="Save definitions",
    intro=(
        "Amulet's own definitions map a block or item to a colour, a model, and "
        "the properties the pickers offer. Editing one here changes every picker "
        "in the editor, and every placeholder tile drawn from it."
    ),
    sections=(
        sec("", "search", hint="Search definitions by id, model, or colour"),
        sec(
            "Set",
            "selects",
            selects=[
                Select(
                    "Definition set",
                    ("Bundled defaults", "User overrides", "Project overrides"),
                    "User overrides",
                ),
                Select(
                    "Applies to",
                    ("Blocks", "Items", "Biomes", "Entities"),
                    "Blocks",
                ),
                Select(
                    "Platform and version",
                    ("bedrock 1.17.0.1", "java 1.20.4"),
                    "bedrock 1.17.0.1",
                ),
            ],
        ),
        sec(
            "Definitions",
            "list",
            rows=[
                Row(
                    "minecraft:deepslate",
                    "Colour #4A4A4F · model cube_column · property axis",
                    "override",
                ),
                Row(
                    "minecraft:sculk",
                    "Colour #0F2A2E · model cube_all · no properties",
                    "default",
                ),
                Row(
                    "minecraft:copper_block",
                    "Colour #C07248 · model cube_all · oxidation stages linked",
                    "override",
                ),
                Row(
                    "minecraft:sea_lantern",
                    "Colour #9FD3C4 · model cube_all · emits light 15",
                    "default",
                ),
                Row(
                    "amulet:unknown_block",
                    "Colour #8A8A8A · model cube_all · fallback for anything "
                    "undefined",
                    "fallback",
                ),
            ],
        ),
        sec(
            "Colour",
            "swatches",
            hint="#4A4A4F · used for the placeholder tile and the biome map",
            swatches=[
                SwatchDef("Deepslate", "#4A4A4F"),
                SwatchDef("Sculk", "#0F2A2E"),
                SwatchDef("Copper block", "#C07248"),
                SwatchDef("Sea lantern", "#9FD3C4"),
                SwatchDef("Unknown fallback", "#8A8A8A"),
            ],
        ),
        sec(
            "Selected definition",
            "fields",
            fields=[
                Field("Namespaced id", "minecraft:deepslate"),
                Field("Model", "cube_column"),
                Field("Properties", "axis=x|y|z"),
                Field("Emitted light", "0"),
            ],
        ),
        tex_section("minecraft:deepslate", "definition-texture"),
        sec(
            "Rules",
            "checks",
            checks=[
                Check(
                    "Fall back to the bundled definition when an override is "
                    "incomplete",
                    "Off leaves the missing field empty and reports it.",
                    True,
                ),
                Check(
                    "Warn when a definition names a block the loaded version "
                    "does not have",
                    "The warning names the id and the version it was checked "
                    "against.",
                    True,
                ),
                Check(
                    "Apply project overrides before user overrides",
                    "Off gives your own overrides the final say.",
                ),
            ],
        ),
        sec(
            "",
            "note",
            hint=(
                "Overrides are stored as plain JSON, per user and per project, "
                "so a bad edit is undone by deleting the file. The bundled "
                "defaults are never written to."
            ),
        ),
    ),
    actions=(
        Action("New override", "tonal"),
        Action("Item types", "outlined", surface="itemTypeList"),
        Action("Block picker", "outlined", surface="blockSelect"),
        Action("Reset to bundled", "danger"),
    ),
)

_MINECRAFT_INSTALLS = Spec(
    key="minecraftInstalls",
    eyebrow="Resources",
    title="Minecraft installs",
    width=800,
    confirm="Use this install",
    intro=(
        "Installs found on this machine supply block models, textures, and the "
        "version data the handlers need. The list is what is already on disk; "
        "nothing is downloaded from here."
    ),
    sections=(
        sec("", "search", hint="Search installs, versions, and resource packs"),
        sec(
            "Installs",
            "list",
            rows=[
                Row(
                    "Minecraft Launcher (Java)",
                    "%APPDATA%\\.minecraft · versions 1.20.4, 1.19.2, 1.16.5",
                    "found",
                ),
                Row(
                    "Minecraft for Windows (Bedrock)",
                    "%LOCALAPPDATA%\\Packages\\Microsoft.MinecraftUWP · 1.17.0.1",
                    "found",
                ),
                Row(
                    "Server folder",
                    "D:\\minecraft\\servers\\andesite · 1.20.4 server jar",
                    "added",
                ),
                Row(
                    "Bundled definitions",
                    "Shipped with Amulet · no textures, colours only",
                    "always available",
                ),
            ],
        ),
        sec(
            "Active",
            "selects",
            selects=[
                Select(
                    "Install",
                    (
                        "Minecraft Launcher (Java)",
                        "Minecraft for Windows (Bedrock)",
                        "Server folder",
                        "Bundled definitions only",
                    ),
                    "Minecraft for Windows (Bedrock)",
                ),
                Select(
                    "Version",
                    ("bedrock 1.17.0.1", "1.20.4", "1.19.2", "1.16.5"),
                    "bedrock 1.17.0.1",
                ),
            ],
        ),
        sec(
            "Resource packs",
            "list",
            rows=[
                Row(
                    "Vanilla (from the install)",
                    "bedrock 1.17.0.1 · 1,512 block textures",
                    "loaded",
                ),
                Row(
                    "Faithful 32x",
                    "resourcepacks\\Faithful32.zip · 1,880 block textures",
                    "loaded",
                ),
                Row(
                    "Java vanilla 1.20.4",
                    "cached from an earlier session · 1,904 block textures",
                    "cached",
                ),
                Row(
                    "Andesite overlay",
                    "resourcepacks\\andesite-overlay.zip · 42 block textures",
                    "off",
                ),
            ],
        ),
        sec(
            "Texture atlas",
            "progress",
            hint="Creating the texture atlas for the active version",
            progress_label="100%",
            progress_fraction=1.0,
        ),
        tex_section(
            "minecraft:copper_block",
            "install-atlas-texture",
            "Until an install and a resource pack are both loaded, every tile in "
            "the editor is a generated placeholder like this one.",
        ),
        sec(
            "Paths",
            "fields",
            fields=[
                Field(
                    "Install root",
                    "%APPDATA%\\.minecraft",
                    "Choose the folder holding versions and resourcepacks",
                ),
                Field(
                    "Resource pack folder",
                    "%APPDATA%\\.minecraft\\resourcepacks",
                    "Choose a folder of .zip resource packs",
                ),
                Field("Atlas cache", "%LOCALAPPDATA%\\Amulet\\atlas"),
            ],
        ),
        sec(
            "Loading",
            "checks",
            checks=[
                Check(
                    "Load resource packs in the order listed",
                    "The last pack listed wins for a texture two packs both " "define.",
                    True,
                ),
                Check(
                    "Rebuild the atlas when a pack file changes",
                    "Off rebuilds only when you ask.",
                    True,
                ),
                Check(
                    "Fall back to placeholder tiles for missing textures",
                    "Off leaves the tile blank and reports the missing texture.",
                    True,
                ),
            ],
        ),
        sec(
            "",
            "note",
            hint=(
                "A pack missing a texture leaves a placeholder tile and names "
                "the texture that was missing, rather than drawing something "
                "else in its place."
            ),
        ),
    ),
    actions=(
        Action("Add install folder", "tonal"),
        Action("Rescan this machine", "outlined"),
        Action("Rebuild atlas", "outlined"),
        Action("Render layers", "outlined", surface="renderLayers"),
        Action("Remove install", "danger"),
    ),
)

_PLUGINS_DIALOG = Spec(
    key="pluginsDialog",
    eyebrow="Plugins",
    title="Plugins",
    width=800,
    confirm="Close",
    intro=(
        "Tools, generators, and operations loaded from the plugins folder. A "
        "plugin that fails to import stays in the list with its exact error, "
        "instead of quietly disappearing."
    ),
    sections=(
        sec("", "search", hint="Search plugins by name, kind, path, or error"),
        sec(
            "Filter",
            "selects",
            selects=[
                Select(
                    "Kind",
                    ("All", "Tools", "Generators", "Operations", "Commands"),
                    "All",
                ),
                Select(
                    "State",
                    ("All", "Loaded", "Disabled", "Failed"),
                    "All",
                ),
                Select("Source", ("All", "Bundled", "User", "Project"), "All"),
            ],
        ),
        sec(
            "Installed",
            "list",
            rows=[
                Row(
                    "Shape brush",
                    "Tool · bundled · plugins/shape_brush.py · API 0.10",
                    "loaded",
                ),
                Row(
                    "L-system tree",
                    "Generator · bundled · plugins/generators/lsystem.py",
                    "loaded",
                ),
                Row(
                    "Cave system",
                    "Generator · bundled · plugins/generators/caves.py",
                    "loaded",
                ),
                Row(
                    "Rail tunnel builder",
                    "Tool · user · plugins/rail_tunnel.py · API 0.10",
                    "loaded",
                ),
                Row(
                    "Structure locator",
                    "Command · bundled · plugins/commands/locate.py",
                    "loaded",
                ),
                Row(
                    "Chunk pruner",
                    "Operation · user · plugins/chunk_pruner.py",
                    "disabled",
                ),
                Row(
                    "Loot table audit",
                    "Operation · user · plugins/loot_tables.py",
                    "failed",
                ),
            ],
        ),
        sec(
            "Import error",
            "code",
            code=(
                "plugins/loot_tables.py\n"
                "  line 4: import yaml\n"
                "ModuleNotFoundError: No module named 'yaml'\n"
                "\n"
                "The plugin is listed as failed and is not loaded. Installing\n"
                "PyYAML into the bundled interpreter, or removing the import,\n"
                "is what fixes it."
            ),
        ),
        sec(
            "Selected plugin",
            "fields",
            fields=[
                Field("Name", "Loot table audit"),
                Field("Kind", "Operation"),
                Field("Path", "plugins/loot_tables.py"),
                Field("API version", "0.10"),
            ],
        ),
        sec(
            "Loading",
            "checks",
            checks=[
                Check(
                    "Load user plugins at startup",
                    "Off loads bundled plugins only until you ask for more.",
                    True,
                ),
                Check(
                    "Reload a plugin when its file changes",
                    "Useful while writing one; slower on a large folder.",
                ),
                Check(
                    "Keep a failed plugin listed until it loads",
                    "Off hides the failure, which is how one gets forgotten.",
                    True,
                ),
            ],
        ),
        sec(
            "",
            "note",
            hint=(
                "Plugins run with the editor's own permissions and can write to "
                "the world. Read a plugin you did not write before enabling it."
            ),
        ),
    ),
    actions=(
        Action("Reload plugins", "tonal"),
        Action("Open plugins folder", "outlined"),
        Action("Enable selected", "outlined"),
        Action("Error report", "outlined", surface="errorReport"),
        Action("Disable selected", "danger"),
    ),
)

_VIEW_CONTROLS = Spec(
    key="viewControls",
    eyebrow="View",
    title="View settings",
    width=740,
    confirm="Apply view",
    intro=(
        "Camera, projection, and the overlays drawn on top of the world. "
        "Nothing on this surface changes world data, and every setting is "
        "restored the next time the project opens."
    ),
    sections=(
        sec("", "search", hint="Search view settings"),
        sec(
            "Camera",
            "selects",
            selects=[
                Select(
                    "View type",
                    (
                        "3D perspective",
                        "Top-down",
                        "Front elevation",
                        "Side elevation",
                        "Four-up split",
                    ),
                    "3D perspective",
                ),
                Select(
                    "Projection",
                    ("Perspective", "Orthographic"),
                    "Perspective",
                ),
                Select(
                    "Controls",
                    ("Fly", "Orbit the selection", "Pan and zoom"),
                    "Fly",
                ),
            ],
        ),
        sec(
            "Position",
            "fields",
            fields=[
                Field("x", "66.40"),
                Field("y", "118.13"),
                Field("z", "-43.12"),
                Field("Yaw", "-134.5"),
                Field("Pitch", "18.0"),
            ],
        ),
        sec(
            "Feel",
            "ranges",
            ranges=[
                RangeDef("Field of view", 70, 30, 110),
                RangeDef("Move speed", 12, 1, 64),
                RangeDef("Render distance (chunks)", 8, 2, 32),
                RangeDef("Mouse sensitivity", 50, 1, 100),
            ],
        ),
        sec(
            "Overlays",
            "checks",
            checks=[
                Check(
                    "Selection outline",
                    "The selection boxes and their drag handles.",
                    True,
                ),
                Check("Chunk grid", "A 16-block grid on chunk boundaries."),
                Check(
                    "World border",
                    "The border wall and its warning distance.",
                    True,
                ),
                Check(
                    "Coordinate axes at the origin",
                    "Three coloured lines through 0, 0, 0.",
                ),
                Check(
                    "Compass and coordinate readout",
                    "The heads-up display in the viewport corner.",
                    True,
                ),
            ],
        ),
        sec(
            "Background",
            "selects",
            selects=[
                Select(
                    "Sky",
                    ("Gradient", "Flat colour", "Void black"),
                    "Gradient",
                ),
                Select(
                    "Fog",
                    ("Off", "Distance fog", "Match the render distance"),
                    "Match the render distance",
                ),
            ],
        ),
        sec(
            "",
            "note",
            hint=(
                "Render distance is the single biggest frame-rate control here. "
                "The profiler shows what each change actually bought."
            ),
        ),
    ),
    actions=(
        Action("Reset camera", "outlined"),
        Action("Four-up split", "outlined", surface="fourUpView"),
        Action("Render layers", "outlined", surface="renderLayers"),
        Action("Teleport", "outlined", surface="goto"),
    ),
)

_FOUR_UP_VIEW = Spec(
    key="fourUpView",
    eyebrow="View",
    title="Four-up split",
    width=740,
    confirm="Apply layout",
    intro=(
        "Shows the camera view together with an overhead and two elevations, so "
        "a build can be lined up from every side without flying around it."
    ),
    sections=(
        sec(
            "Layout",
            "selects",
            selects=[
                Select(
                    "Split",
                    (
                        "2 × 2",
                        "Camera large, three small",
                        "Two columns",
                        "Two rows",
                    ),
                    "2 × 2",
                ),
                Select(
                    "Top left",
                    (
                        "3D perspective",
                        "Top-down",
                        "Front elevation",
                        "Side elevation",
                    ),
                    "3D perspective",
                ),
                Select(
                    "Top right",
                    (
                        "3D perspective",
                        "Top-down",
                        "Front elevation",
                        "Side elevation",
                    ),
                    "Top-down",
                ),
                Select(
                    "Bottom left",
                    (
                        "3D perspective",
                        "Top-down",
                        "Front elevation",
                        "Side elevation",
                    ),
                    "Front elevation",
                ),
                Select(
                    "Bottom right",
                    (
                        "3D perspective",
                        "Top-down",
                        "Front elevation",
                        "Side elevation",
                    ),
                    "Side elevation",
                ),
            ],
        ),
        sec(
            "Panes",
            "list",
            rows=[
                Row("Top left", "3D perspective · 66.4, 118.1, -43.1", "camera"),
                Row("Top right", "Top-down · y 118 · 24 blocks across", "ortho"),
                Row("Bottom left", "Front elevation · z -43", "ortho"),
                Row("Bottom right", "Side elevation · x 66", "ortho"),
            ],
        ),
        sec(
            "Dividers",
            "ranges",
            ranges=[
                RangeDef("Vertical divider (%)", 50, 10, 90),
                RangeDef("Horizontal divider (%)", 50, 10, 90),
                RangeDef("Orthographic zoom (blocks across)", 24, 4, 128),
            ],
        ),
        sec(
            "Linking",
            "checks",
            checks=[
                Check(
                    "Link camera position across panes",
                    "Moving in one pane moves the others to match.",
                    True,
                ),
                Check(
                    "Link the selection highlight",
                    "The selection is drawn in every pane.",
                    True,
                ),
                Check(
                    "Draw the camera frustum in the flat panes",
                    "Shows where the 3D pane is looking.",
                ),
                Check(
                    "Render every pane at full detail",
                    "Off draws the three small panes at half render distance to "
                    "keep the frame rate up.",
                ),
            ],
        ),
        sec(
            "",
            "note",
            hint=(
                "Four panes cost roughly twice the frame time of one. Pane "
                "detail is the first thing to turn down on a slow machine."
            ),
        ),
    ),
    actions=(
        Action("Single pane", "outlined"),
        Action("View settings", "outlined", surface="viewControls"),
        Action("Profiler", "outlined", surface="profiler"),
    ),
)

_CUTAWAY_VIEW = Spec(
    key="cutawayView",
    eyebrow="View",
    title="Cutaway",
    width=720,
    confirm="Apply cutaway",
    intro=(
        "Clips the world along a plane or a slab so you can see inside a build "
        "without deleting anything. This is a view setting: no block is changed "
        "and operations still see the whole world."
    ),
    sections=(
        sec(
            "Clip",
            "selects",
            selects=[
                Select(
                    "Mode",
                    (
                        "Off",
                        "Single plane",
                        "Slab between two planes",
                        "Box around the selection",
                    ),
                    "Slab between two planes",
                ),
                Select(
                    "Axis",
                    (
                        "Y (horizontal slice)",
                        "X (east–west)",
                        "Z (north–south)",
                        "Camera facing",
                    ),
                    "Y (horizontal slice)",
                ),
                Select(
                    "Hidden side",
                    ("Hide in front of the plane", "Hide behind the plane"),
                    "Hide in front of the plane",
                ),
            ],
        ),
        sec(
            "Planes",
            "ranges",
            ranges=[
                RangeDef("Near plane (y)", 118, -64, 320),
                RangeDef("Far plane (y)", 132, -64, 320),
                RangeDef("Slab thickness", 14, 1, 128),
                RangeDef("Edge fade", 0, 0, 16),
            ],
        ),
        sec(
            "Readout",
            "fields",
            fields=[
                Field("Visible range", "y 118 to y 132"),
                Field("Blocks hidden", "1,284,096"),
                Field("Chunks affected", "168"),
            ],
        ),
        sec(
            "Contents",
            "checks",
            checks=[
                Check(
                    "Keep entities visible through the cut",
                    "Off hides entities outside the visible range too.",
                ),
                Check(
                    "Draw a bright edge where blocks are cut",
                    "Makes the cut face readable against dark terrain.",
                    True,
                ),
                Check(
                    "Clip the selection highlight too",
                    "Off keeps the whole selection outline visible.",
                ),
                Check(
                    "Follow the camera height",
                    "The plane tracks the camera's y as you fly.",
                ),
            ],
        ),
        sec(
            "",
            "note",
            hint=(
                "Cutaway hides blocks from the renderer only. Selections, "
                "operations, exports, and the analysis table still count every "
                "hidden block."
            ),
        ),
    ),
    actions=(
        Action("Slice at camera height", "tonal"),
        Action("Layer slice", "outlined", surface="layerSlice"),
        Action("View settings", "outlined", surface="viewControls"),
        Action("Clear cutaway", "outlined"),
    ),
)

_WORK_PLANE = Spec(
    key="workPlane",
    eyebrow="View",
    title="Work plane",
    width=700,
    confirm="Apply work plane",
    intro=(
        "A fixed plane that brushes and placement snap to, so a stroke stays "
        "flat instead of following whatever surface happens to be under the "
        "cursor."
    ),
    sections=(
        sec(
            "Plane",
            "selects",
            selects=[
                Select(
                    "Axis",
                    (
                        "Y (horizontal)",
                        "X (east–west)",
                        "Z (north–south)",
                        "Camera facing",
                    ),
                    "Y (horizontal)",
                ),
                Select(
                    "Origin",
                    (
                        "Fixed height",
                        "Camera height",
                        "Selection floor",
                        "Last clicked block",
                    ),
                    "Fixed height",
                ),
            ],
        ),
        sec(
            "Position",
            "ranges",
            ranges=[
                RangeDef("Height", 98, -64, 320),
                RangeDef("Grid spacing", 16, 1, 64),
                RangeDef("Grid opacity (%)", 40, 0, 100),
            ],
        ),
        sec(
            "Snapping",
            "fields",
            fields=[
                Field("Snap step", "1"),
                Field("Offset from the plane", "0"),
                Field("Plane at", "y 98 · minecraft:overworld"),
            ],
        ),
        sec(
            "Behaviour",
            "checks",
            checks=[
                Check(
                    "Snap the brush to the plane",
                    "The brush paints on the plane instead of the surface under "
                    "the cursor.",
                    True,
                ),
                Check(
                    "Snap the selection handles to the plane",
                    "Dragging a handle keeps it on the plane.",
                ),
                Check(
                    "Draw the plane grid in the viewport",
                    "Off keeps the plane active but invisible.",
                    True,
                ),
                Check(
                    "Clamp placement to the world height limits",
                    "A plane outside -64 to 320 places nothing and says so.",
                    True,
                ),
            ],
        ),
        sec(
            "",
            "note",
            hint=(
                "The work plane is a placement aid. It never writes blocks on "
                "its own, and turning it off leaves everything already placed "
                "exactly where it is."
            ),
        ),
    ),
    actions=(
        Action("Set from camera", "tonal"),
        Action("Set from selection floor", "outlined"),
        Action("Brush settings", "outlined", surface="brushSettings"),
        Action("Clear work plane", "outlined"),
    ),
)

_RENDER_LAYERS = Spec(
    key="renderLayers",
    eyebrow="View",
    title="Render layers",
    width=720,
    confirm="Apply layers",
    intro=(
        "Each layer draws independently, so hiding one costs nothing and reveals "
        "what is behind it. A hidden layer is skipped rather than drawn "
        "transparent, and hiding a layer never changes world data."
    ),
    sections=(
        sec("", "search", hint="Search render layers"),
        sec(
            "Layers",
            "checks",
            checks=[
                Check(
                    "Terrain",
                    "Solid and transparent blocks. Hiding it leaves entities and "
                    "overlays visible.",
                    True,
                ),
                Check(
                    "Water",
                    "Water and other fluid surfaces, drawn after terrain so they "
                    "blend correctly.",
                    True,
                ),
                Check(
                    "Entities",
                    "Mobs, vehicles, item frames, and dropped items.",
                    True,
                ),
                Check(
                    "Block entities",
                    "Chests, signs, banners, and other blocks carrying their own "
                    "data.",
                    True,
                ),
                Check(
                    "Selection",
                    "The selection boxes and their drag handles.",
                    True,
                ),
                Check(
                    "Chunk grid",
                    "A 16-block grid drawn on chunk boundaries.",
                ),
                Check(
                    "Sky box",
                    "The sky gradient and the horizon behind the world.",
                    True,
                ),
                Check(
                    "Biome overlay",
                    "Tints each column by its biome colour.",
                ),
                Check(
                    "Light overlay",
                    "Shades every block by its block light and sky light.",
                ),
                Check(
                    "Structure bounds",
                    "Bounding boxes for generated structures such as mineshafts "
                    "and villages.",
                ),
                Check(
                    "Pending imports",
                    "Objects placed but not yet written to the world.",
                    True,
                ),
                Check(
                    "World border",
                    "The border wall and its warning distance.",
                ),
            ],
        ),
        sec(
            "Detail",
            "ranges",
            ranges=[
                RangeDef("Render distance (chunks)", 8, 2, 32),
                RangeDef("Entity distance (chunks)", 6, 1, 32),
                RangeDef("Overlay opacity (%)", 60, 0, 100),
            ],
        ),
        sec(
            "Cost",
            "list",
            rows=[
                Row("Terrain", "1,842 draw calls · 3.1 M triangles", "heaviest"),
                Row("Water", "212 draw calls · sorted per frame", "moderate"),
                Row("Entities", "312 draw calls · 96 K triangles", "moderate"),
                Row("Light overlay", "recomputed on every chunk change", "costly"),
                Row("Biome overlay", "one texture per chunk column", "cheap"),
                Row("Chunk grid", "1 draw call", "free"),
            ],
        ),
        sec(
            "",
            "note",
            hint=(
                "Hiding the light overlay is usually the quickest way to get "
                "frames back, because it is the only layer recomputed whenever a "
                "block changes."
            ),
        ),
    ),
    actions=(
        Action("Show every layer", "outlined"),
        Action("Hide overlays only", "outlined"),
        Action("View settings", "outlined", surface="viewControls"),
        Action("Profiler", "outlined", surface="profiler"),
    ),
)

#: Every tool, find-and-replace, panel, and view surface this module owns.
SPECS: Dict[str, Spec] = {
    spec.key: spec
    for spec in (
        _BRUSH_SETTINGS,
        _FLOOD_FILL,
        _CLONE_TOOL,
        _MOVE_TOOL,
        _GENERATE_TOOL,
        _SELECT_BLOCK_TOOL,
        _SELECT_ENTITY_TOOL,
        _EDIT_CHUNK_TOOL,
        _TOOL_SETTINGS,
        _FIND_REPLACE_BLOCKS,
        _FIND_REPLACE_COMMANDS,
        _FIND_REPLACE_NBT,
        _ANALYZE_TOOL,
        _IMPORT_MAP,
        _INSPECTOR,
        _WORLD_INFO,
        _PLAYER_PANEL,
        _INVENTORY_EDITOR,
        _PENDING_IMPORTS,
        _LIBRARY_PANEL,
        _LOG_VIEW,
        _PROFILER,
        _PYTHON_CONSOLE,
        _ERROR_REPORT,
        _ITEM_TYPE_LIST,
        _CONFIGURE_BLOCKS,
        _MINECRAFT_INSTALLS,
        _PLUGINS_DIALOG,
        _VIEW_CONTROLS,
        _FOUR_UP_VIEW,
        _CUTAWAY_VIEW,
        _WORK_PLANE,
        _RENDER_LAYERS,
    )
}

__all__ = ["SPECS"]
