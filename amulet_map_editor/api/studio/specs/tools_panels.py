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
    Commit,
    Field,
    RangeDef,
    Row,
    Select,
    Spec,
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
        Action("Dock left", "outlined"),
        Action("Float panel", "outlined"),
    ),
)

_PENDING_IMPORTS = Spec(
    key="pendingImports",
    eyebrow="Panels",
    title="Pending imports",
    width=740,
    confirm="Confirm all",
    intro=(
        "Everything lifted, cloned, generated, or imported waits here until "
        "confirmed. Each entry keeps its own position, rotation, and scale."
    ),
    sections=(
        sec(
            "Imports",
            "list",
            rows=[
                Row(
                    "spawn-arch",
                    "24×18×24 at 66, 118, -43 · rotation 90° · scale 1×",
                    "pending",
                ),
                Row(
                    "market-row",
                    "48×22×16 at 412, 71, 188 · rotation 0° · scale 1×",
                    "pending",
                ),
                Row(
                    "generated tree",
                    "9×14×9 at 240, 94, 72 · from L-system",
                    "pending",
                ),
            ],
        ),
        sec(
            "Selected import",
            "fields",
            fields=[
                Field("x", "66"),
                Field("y", "118"),
                Field("z", "-43"),
                Field("Rotation", "90"),
            ],
        ),
        sec(
            "Options",
            "checks",
            checks=[
                Check(
                    "Import air",
                    "Air in the import overwrites existing blocks.",
                ),
                Check(
                    "Import entities",
                    "Entities stored with the structure are placed too.",
                ),
                Check(
                    "Draw a wireframe for each pending import",
                    "Shows placement before confirming.",
                ),
            ],
        ),
    ),
    actions=(
        Action("Confirm selected", "tonal"),
        Action("Discard selected", "danger"),
        Action("Discard all", "danger"),
    ),
)

_PLAYER_PANEL = Spec(
    key="playerPanel",
    eyebrow="Panels",
    title="Players",
    width=720,
    confirm="Save player",
    intro=(
        "Every player stored in the world, with position, dimension, game mode, "
        "and inventory, and a skin preview when one is available."
    ),
    sections=(
        sec(
            "Players",
            "list",
            rows=[
                Row("6f1c…a904", "overworld · creative · level 34", "select"),
                Row("b28d…41ff", "overworld · survival · level 12", "select"),
                Row(
                    "Singleplayer (level.dat)",
                    "Stored in level.dat rather than playerdata",
                    "select",
                ),
            ],
        ),
        sec(
            "Skin",
            "texture",
            hint=(
                "Skins resolve from the local skin cache. The tile is a "
                "placeholder until a skin file is available."
            ),
            block_id="skins/6f1ca904.png",
            slot_id="player-skin-slot",
            faces=("head", "body", "legs"),
        ),
        sec(
            "Move",
            "fields",
            fields=[
                Field("x", "66.40"),
                Field("y", "118.13"),
                Field("z", "-43.12"),
                Field("Dimension", "overworld"),
            ],
        ),
    ),
    actions=(
        Action("Move player to camera", "tonal"),
        Action("Open inventory", "outlined", surface="inventoryEditor"),
        Action("Player data", "outlined", surface="playerData"),
    ),
)

_WORLD_INFO = Spec(
    key="worldInfo",
    eyebrow="Panels",
    title="World info",
    width=700,
    confirm="Save world info",
    sections=(
        sec(
            "Identity",
            "fields",
            fields=[
                Field("Level name", "1.17 Height"),
                Field("Seed", "1471929"),
                Field("Platform", "bedrock"),
                Field("Data version", "1.17.0.1"),
            ],
        ),
        sec(
            "Size on disk",
            "list",
            rows=[
                Row("Region files", "18 files · 142 MiB", "142 MiB"),
                Row(
                    "Chunks",
                    "812 in overworld, 146 in nether, 24 in end",
                    "982",
                ),
                Row("Player data", "2 players", "2"),
                Row("Dimensions", "overworld, the_nether, the_end", "3"),
            ],
        ),
        sec(
            "Time and weather",
            "ranges",
            ranges=[
                RangeDef("Day time (ticks)", 6000, 0, 24000),
                RangeDef("Rain time (ticks)", 12000, 0, 180000),
            ],
        ),
    ),
    actions=(
        Action("Open level.dat", "outlined", surface="levelDat"),
        Action("Game rules", "outlined", surface="gamerules"),
    ),
)

_INVENTORY_EDITOR = Spec(
    key="inventoryEditor",
    eyebrow="Panels",
    title="Inventory editor",
    width=760,
    confirm="Save inventory",
    intro=(
        "Edit any container or player inventory slot by slot. Item types come "
        "from the loaded version's item list."
    ),
    sections=(
        sec(
            "Container",
            "selects",
            selects=[
                Select(
                    "Inventory",
                    (
                        "Player hotbar",
                        "Player main",
                        "Ender chest",
                        "Armour",
                        "Chest at 412, 71, 188",
                    ),
                ),
                Select(
                    "Item type",
                    (
                        "minecraft:diamond_pickaxe",
                        "minecraft:oak_planks",
                        "minecraft:torch",
                        "minecraft:bread",
                        "minecraft:filled_map",
                    ),
                ),
            ],
        ),
        tex_section(
            "minecraft:oak_planks",
            "inventory-item-texture",
            "The selected item's texture shows here. The tile is a generated "
            "placeholder until a resource pack is loaded.",
        ),
        sec(
            "Slot",
            "fields",
            fields=[
                Field("Slot", "0"),
                Field("Count", "1"),
                Field("Damage", "240"),
                Field("Custom name", "Ana's Pick"),
            ],
        ),
        sec(
            "Enchantments",
            "chips",
            chips=[
                "efficiency V",
                "unbreaking III",
                "fortune III",
                "mending I",
                "＋ add",
            ],
        ),
    ),
    actions=(
        Action("Clear slot", "danger"),
        Action("Fill stack", "tonal"),
        Action("Open NBT editor", "outlined", surface="nbt"),
    ),
)

_ITEM_TYPE_LIST = Spec(
    key="itemTypeList",
    eyebrow="Pickers",
    title="Item types",
    width=720,
    confirm="Use this item",
    intro=(
        "Every item type in the loaded version, searchable, with the internal "
        "id and its texture."
    ),
    sections=(
        sec("", "search", hint="Search item names and ids"),
        sec(
            "Items",
            "list",
            rows=[
                Row(
                    "minecraft:diamond_pickaxe",
                    "Tools · max damage 1561",
                    "pick",
                ),
                Row("minecraft:oak_planks", "Building · stacks to 64", "pick"),
                Row("minecraft:torch", "Decoration · stacks to 64", "pick"),
                Row(
                    "minecraft:filled_map",
                    "Miscellaneous · stacks to 1",
                    "pick",
                ),
            ],
        ),
        tex_section("minecraft:oak_planks", "itemtype-texture"),
    ),
    actions=(Action("Configure item list…", "outlined", surface="configureBlocks"),),
)

_CONFIGURE_BLOCKS = Spec(
    key="configureBlocks",
    eyebrow="Pickers",
    title="Configure blocks",
    width=740,
    confirm="Save definitions",
    intro=(
        "Override display names, textures, and grouping for block types the "
        "loaded version does not describe, including modded ids."
    ),
    sections=(
        sec("", "search", hint="Search block definitions"),
        sec(
            "Definitions",
            "list",
            rows=[
                Row(
                    "amulet:unknown_block",
                    "Placeholder from a failed read · shown in magenta",
                    "override",
                ),
                Row(
                    "minecraft:cave_air",
                    "Hidden by default in the render",
                    "hidden",
                ),
                Row(
                    "modded:brass_casing",
                    "Custom display name and texture",
                    "custom",
                ),
            ],
        ),
        sec(
            "Selected definition",
            "fields",
            fields=[
                Field("Internal id", "modded:brass_casing"),
                Field("Display name", "Brass Casing"),
                Field("Group", "Modded"),
                Field("Render as", "full cube"),
            ],
        ),
        tex_section(
            "minecraft:copper_block",
            "configure-block-texture",
            "Assign a texture for this definition. Drop a PNG to use the real one.",
        ),
    ),
    actions=(
        Action("Add definition", "tonal"),
        Action("Reset definition", "danger"),
        Action("Export definitions", "outlined"),
    ),
)

_RENDER_LAYERS = Spec(
    key="renderLayers",
    eyebrow="View",
    title="Render layers",
    width=640,
    confirm="Apply layers",
    intro=(
        "Each layer can be drawn or hidden independently, so a crowded world "
        "stays readable."
    ),
    sections=(
        sec(
            "Layers",
            "checks",
            checks=[
                Check("Blocks", "Terrain and built blocks."),
                Check("Items", "Dropped item entities."),
                Check("TileEntities", "Chests, signs, spawners."),
                Check(
                    "TileEntityLocations",
                    "Markers where block entities sit.",
                ),
                Check("CommandBlockColors", "Command blocks tinted by type."),
                Check("CommandBlockLocations", "Markers for command blocks."),
                Check("ItemFrames", "Item frames and their contents."),
                Check("TileTicks", "Scheduled tick markers."),
                Check("MonsterLocations", "Markers for hostile entities."),
                Check("ChunkSections", "Section boundaries."),
                Check("HeightMap", "Stored heightmap overlay."),
                Check(
                    "Places Where Creepers Can Spawn",
                    "Spawnable surface overlay.",
                ),
            ],
        ),
        sec(
            "Presets",
            "chips",
            chips=[
                "Default visible",
                "Blocks only",
                "Everything",
                "Data overlays",
                "Spawn checking",
            ],
        ),
    ),
    actions=(Action("Reset to defaults", "outlined"),),
)

_VIEW_CONTROLS = Spec(
    key="viewControls",
    eyebrow="View",
    title="View settings",
    width=700,
    confirm="Apply view",
    intro=(
        "Four view types share one world: fly camera, overhead, isometric, and "
        "a four-up split. Each keeps its own camera."
    ),
    sections=(
        sec(
            "View",
            "selects",
            selects=[
                Select(
                    "View type",
                    (
                        "Camera (fly)",
                        "Overhead",
                        "Isometric",
                        "Four-up split",
                        "Cutaway",
                        "Schematic view",
                    ),
                ),
                Select(
                    "Control scheme",
                    (
                        "Hold right mouse to look",
                        "Click to capture mouse",
                        "Arrow keys only",
                    ),
                ),
            ],
        ),
        sec(
            "Camera",
            "ranges",
            ranges=[
                RangeDef("Field of view", 70, 30, 110),
                RangeDef("View distance (chunks)", 12, 2, 32),
                RangeDef("Movement speed (blocks/s)", 12, 1, 60),
            ],
        ),
        sec(
            "Overlays",
            "checks",
            checks=[
                Check("Compass", "North indicator in the corner."),
                Check("World ruler", "Coordinate ruler along the edges."),
                Check("Minimap", "Overhead minimap panel."),
                Check("Chunk grid", "Section and chunk boundaries."),
                Check(
                    "Work plane",
                    "The fixed plane brushes and shapes snap to.",
                ),
                Check(
                    "Sky and lightmap",
                    "Sky gradient and light-based shading.",
                ),
            ],
        ),
    ),
    actions=(
        Action("Render layers…", "outlined", surface="renderLayers"),
        Action("Reset camera", "outlined"),
    ),
)

_FOUR_UP_VIEW = Spec(
    key="fourUpView",
    eyebrow="View",
    title="Four-up split",
    width=660,
    confirm="Apply layout",
    intro=(
        "Shows camera, overhead, and two side views at once, with one shared "
        "selection across all four panes."
    ),
    sections=(
        sec(
            "Panes",
            "selects",
            selects=[
                Select(
                    "Top left",
                    (
                        "Camera (fly)",
                        "Overhead",
                        "North elevation",
                        "East elevation",
                        "Isometric",
                    ),
                ),
                Select(
                    "Top right",
                    (
                        "Overhead",
                        "Camera (fly)",
                        "Isometric",
                        "North elevation",
                    ),
                ),
                Select(
                    "Bottom left",
                    (
                        "North elevation",
                        "East elevation",
                        "Overhead",
                        "Camera (fly)",
                    ),
                ),
                Select(
                    "Bottom right",
                    (
                        "East elevation",
                        "Isometric",
                        "Camera (fly)",
                        "Overhead",
                    ),
                ),
            ],
        ),
        sec(
            "Sync",
            "checks",
            checks=[
                Check(
                    "Share the selection across panes",
                    "Editing in one pane updates the others.",
                ),
                Check("Lock zoom together", "All panes zoom as one."),
                Check(
                    "Show the ruler in orthographic panes",
                    "Coordinates along each edge.",
                ),
            ],
        ),
    ),
    actions=(Action("Single pane", "outlined"),),
)

_CUTAWAY_VIEW = Spec(
    key="cutawayView",
    eyebrow="View",
    title="Cutaway",
    width=620,
    confirm="Apply cutaway",
    intro=(
        "Clips the world along a plane so interiors and caves are visible "
        "without deleting anything."
    ),
    sections=(
        sec(
            "Plane",
            "selects",
            selects=[
                Select(
                    "Axis",
                    (
                        "Y (horizontal slice)",
                        "X (east–west)",
                        "Z (north–south)",
                    ),
                ),
                Select("Side kept", ("Below the plane", "Above the plane")),
            ],
        ),
        sec(
            "Position",
            "ranges",
            ranges=[
                RangeDef("Plane position", 98, -64, 320),
                RangeDef("Fade above the cut", 40, 0, 100),
            ],
        ),
    ),
    actions=(
        Action("Follow the camera", "outlined"),
        Action("Reset", "outlined"),
    ),
)

_WORK_PLANE = Spec(
    key="workPlane",
    eyebrow="View",
    title="Work plane",
    width=600,
    confirm="Set work plane",
    intro=(
        "A fixed plane brushes and shapes snap to, so edits land at a chosen "
        "height even over empty air."
    ),
    sections=(
        sec(
            "Plane",
            "selects",
            selects=[
                Select("Axis", ("Y (height)", "X", "Z")),
                Select("Snap", ("Whole blocks", "Half blocks", "Free")),
            ],
        ),
        sec("Position", "ranges", ranges=[RangeDef("Height", 98, -64, 320)]),
        sec(
            "Options",
            "checks",
            checks=[
                Check(
                    "Draw the plane in the viewport",
                    "A translucent grid at the plane height.",
                ),
                Check(
                    "Restrict edits to the plane",
                    "Tools refuse to write off-plane.",
                ),
            ],
        ),
    ),
    actions=(Action("Set from cursor", "tonal"),),
)

_LIBRARY_PANEL = Spec(
    key="libraryPanel",
    eyebrow="Panels",
    title="Library",
    width=760,
    confirm="Import selected",
    intro=(
        "The schematic library holds saved selections and downloaded "
        "structures, with folders, search, and a preview of each entry."
    ),
    sections=(
        sec("", "search", hint="Search the library"),
        sec(
            "Entries",
            "list",
            rows=[
                Row(
                    "spawn-arch.schematic",
                    "24×18×24 · saved 10 Aug 2026",
                    "import",
                ),
                Row(
                    "market-row.schematic",
                    "48×22×16 · saved 09 Aug 2026",
                    "import",
                ),
                Row(
                    "downloads/castle.schematic",
                    "96×48×96 · imported file",
                    "import",
                ),
            ],
        ),
        sec(
            "Preview",
            "texture",
            hint=(
                "The library renders each entry in a small schematic view. The "
                "tile is a placeholder until that render is available."
            ),
            block_id="spawn-arch.schematic",
            slot_id="library-preview-slot",
            faces=("top", "front", "side"),
        ),
        sec(
            "Folders",
            "chips",
            chips=[
                "All",
                "Saved selections",
                "downloads",
                "spawn",
                "town",
                "＋ new folder",
            ],
        ),
    ),
    actions=(
        Action("Save selection to library", "tonal"),
        Action("Reveal in folder", "outlined"),
        Action("Delete entry", "danger"),
    ),
)

_PLUGINS_DIALOG = Spec(
    key="pluginsDialog",
    eyebrow="Extensibility",
    title="Plugins",
    width=740,
    confirm="Close",
    intro=(
        "Plugins add tools, generators, and commands. Each is enabled "
        "independently and reports its own load errors."
    ),
    sections=(
        sec("", "search", hint="Search plugins"),
        sec(
            "Installed",
            "list",
            rows=[
                Row("L-system generator", "Generator plugin · enabled", "on"),
                Row("Fill selection", "Command plugin · enabled", "on"),
                Row("Swap palette", "Command plugin · enabled", "on"),
                Row(
                    "broken_plugin.py",
                    "Import error on line 12 · not registered",
                    "failed",
                ),
            ],
        ),
        sec(
            "Folders",
            "list",
            rows=[
                Row(
                    "Project plugins",
                    "operations/ inside the project",
                    "scanned",
                ),
                Row("User plugins", "%APPDATA%\\Amulet\\plugins", "scanned"),
            ],
        ),
        sec(
            "",
            "note",
            hint=(
                "A plugin that fails to import reports the exact error and is "
                "not registered. The rest keep working."
            ),
        ),
    ),
    actions=(
        Action("Reload plugins", "tonal"),
        Action("Open plugins folder", "outlined"),
        Action("Operation console", "outlined", surface="scriptConsole"),
    ),
)

_MINECRAFT_INSTALLS = Spec(
    key="minecraftInstalls",
    eyebrow="Resources",
    title="Minecraft installs",
    width=740,
    confirm="Use this install",
    intro=(
        "Amulet reads block models, textures, and item lists from a real game "
        "install or resource pack. Versions are listed as found on disk."
    ),
    sections=(
        sec(
            "Installs",
            "list",
            rows=[
                Row(
                    "Official launcher",
                    "%APPDATA%\\.minecraft · 14 versions",
                    "found",
                ),
                Row("Bedrock UWP", "Package data folder · 1 version", "found"),
                Row("Custom folder", "Not configured", "add"),
            ],
        ),
        sec(
            "Versions",
            "selects",
            selects=[
                Select(
                    "Version",
                    ("1.20.4", "1.17.1", "1.12.2", "bedrock 1.17.0.1"),
                ),
                Select(
                    "Resource pack",
                    (
                        "Vanilla",
                        "Faithful (installed)",
                        "Custom folder",
                        "None (placeholder swatches)",
                    ),
                ),
            ],
        ),
        sec(
            "Texture atlas",
            "progress",
            hint="Building the texture atlas",
            progress_label="100%",
            progress_fraction=1.0,
        ),
        sec(
            "",
            "note",
            hint=(
                "Without an install or resource pack, blocks render as "
                "generated placeholder swatches rather than pretending to be "
                "game textures."
            ),
        ),
    ),
    actions=(
        Action("Add install folder…", "tonal"),
        Action("Rebuild atlas", "outlined"),
    ),
)

_UNDO_HISTORY = Spec(
    key="undoHistory",
    eyebrow="History",
    title="Undo history",
    width=700,
    confirm="Close",
    intro=(
        "The full undo stack for this session, backed by the project's Git "
        "repository, so depth is unlimited and any point is reachable."
    ),
    sections=(
        sec(
            "Stack",
            "commits",
            commits=[
                Commit(
                    "Fill selection with deepslate",
                    "a91f0c7 · 10 Aug 2026, 09:41 · 12 chunks",
                    head=True,
                ),
                Commit(
                    "Move box 1 to -2, 98, -49",
                    "5d3e118 · 10 Aug 2026, 09:22 · 1 box",
                ),
                Commit(
                    "Paste spawn arch structure",
                    "c72ba40 · 10 Aug 2026, 08:58 · 384 blocks",
                ),
                Commit(
                    "Delete unselected chunks",
                    "1e6f9d2 · 09 Aug 2026, 21:14 · 96 chunks",
                ),
                Commit(
                    "Import Debug 1.14 chunk backup",
                    "7ab4c05 · 09 Aug 2026, 20:02 · 48 chunks",
                ),
                Commit(
                    "Initial project commit",
                    "0004aa1 · 09 Aug 2026, 19:40 · world snapshot",
                ),
            ],
        ),
        sec(
            "Depth",
            "list",
            rows=[
                Row("Undo available", "1,284 steps", "unlimited"),
                Row("Redo available", "0 steps", "0"),
                Row(
                    "Storage",
                    "Append-only Git repository beside the project",
                    "local",
                ),
            ],
        ),
    ),
    actions=(
        Action("Jump to selected", "tonal"),
        Action("Project history", "outlined", surface="history"),
    ),
)

#: The log lines the diagnostics log shows, transcribed verbatim so the reader
#: sees the real mix of levels and sources rather than a tidied sample.
_LOG_LINES = """INFO  worldloader  Opened 1.17 Height (bedrock 1.17.0.1)
INFO  renderer     Texture atlas built in 812 ms
WARN  plugins      broken_plugin.py: ImportError on line 12
INFO  renderer     812 chunks queued, 812 drawn
ERROR worldloader  chunk 7,-13: malformed compression header"""

_LOG_VIEW = Spec(
    key="logView",
    eyebrow="Diagnostics",
    title="Log",
    width=780,
    confirm="Close",
    sections=(
        sec("", "search", hint="Search log lines"),
        sec(
            "Level",
            "selects",
            selects=[
                Select(
                    "Minimum level",
                    ("DEBUG", "INFO", "WARNING", "ERROR"),
                ),
                Select(
                    "Source",
                    ("All", "renderer", "worldloader", "plugins", "updater"),
                ),
            ],
        ),
        sec("Lines", "code", code=_LOG_LINES),
    ),
    actions=(
        Action("Copy log", "outlined"),
        Action("Save log…", "outlined"),
        Action("Clear", "danger"),
    ),
)

_PROFILER = Spec(
    key="profiler",
    eyebrow="Diagnostics",
    title="Profiler",
    width=740,
    confirm="Close",
    intro=(
        "Samples frame time and world-loading work so a slow world can be "
        "diagnosed rather than guessed at."
    ),
    sections=(
        sec(
            "Frame",
            "list",
            rows=[
                Row("Frame time", "16.4 ms average over 600 frames", "60 fps"),
                Row("Chunk meshing", "6.2 ms per frame", "38%"),
                Row("Draw calls", "1,412", "1412"),
                Row("Chunk loader queue", "0 pending", "idle"),
            ],
        ),
        sec(
            "Sampling",
            "checks",
            checks=[
                Check("Sample every frame", "Higher overhead, finer detail."),
                Check("Record to file", "Writes a profile beside the project."),
            ],
        ),
    ),
    actions=(
        Action("Start sampling", "tonal"),
        Action("Export profile", "outlined"),
        Action("Tick load report", "outlined", surface="tickLoad"),
    ),
)

#: The console session shown in the Python console, transcribed verbatim so the
#: prompt, the results, and the blank-free spacing read as a real session.
_PYTHON_SESSION = """>>> session.world.level_name
'1.17 Height'
>>> len(session.selection.selection_boxes)
3
>>> session.selection.volume
576"""

_PYTHON_CONSOLE = Spec(
    key="pythonConsole",
    eyebrow="Diagnostics",
    title="Python console",
    width=760,
    confirm="Close",
    intro=(
        "An embedded interactive console with the editor session in scope, for "
        "inspecting objects and running one-off edits."
    ),
    sections=(
        sec("Session", "code", code=_PYTHON_SESSION),
        sec(
            "In scope",
            "list",
            rows=[
                Row("session", "The active editor session", "object"),
                Row("session.world", "The open world", "object"),
                Row("session.selection", "Current selection boxes", "object"),
                Row("session.undo", "The undo stack", "object"),
            ],
        ),
    ),
    actions=(Action("Clear console", "outlined"),),
)

#: The traceback the error report shows, transcribed verbatim: a real failure
#: from the chunk loader rather than an invented one.
_ERROR_TRACEBACK = """Traceback (most recent call last):
  File "worldloader.py", line 214, in load_chunk
    raise ChunkFormatError(offset)
ChunkFormatError: malformed compression header at 0x1A400"""

_ERROR_REPORT = Spec(
    key="errorReport",
    eyebrow="Diagnostics",
    title="Unexpected error",
    width=680,
    confirm="Close",
    intro=(
        "An error report is written locally with the traceback and the last "
        "log lines. Nothing is sent anywhere unless you choose to send it."
    ),
    sections=(
        sec("Traceback", "code", code=_ERROR_TRACEBACK),
        sec(
            "Report",
            "checks",
            checks=[
                Check(
                    "Include the last 200 log lines",
                    "Helps reproduce the failure.",
                ),
                Check(
                    "Include the world path",
                    "Off by default; the path may be private.",
                ),
            ],
        ),
        sec(
            "",
            "note",
            hint=(
                "Reports stay on this machine by default. Sending is an "
                "explicit action, never automatic."
            ),
        ),
    ),
    actions=(
        Action("Open report folder", "outlined"),
        Action("Copy traceback", "outlined"),
        Action("Validate and repair", "tonal", surface="validateRepair"),
    ),
)

_ABOUT = Spec(
    key="about",
    eyebrow="Currently opened world",
    title="About",
    width=640,
    confirm="Close",
    intro=(
        "Choose from the options on the left what you would like to do. You "
        "can switch between these at any time."
    ),
    sections=(
        sec(
            "World",
            "list",
            rows=[
                Row("1.17 Height", "bedrock 1.17.0.1", "open"),
                Row("Support", "Java 1.12+ and Bedrock 1.7+", "metadata"),
                Row(
                    "Build",
                    "0.10.0-dev.414+2.gb3cbec1c (source)",
                    "version",
                ),
            ],
        ),
        sec(
            "",
            "note",
            hint=(
                "Back up every world before editing it. Close the world in "
                "Minecraft and any other editor first."
            ),
        ),
    ),
    actions=(
        Action("User guide", "outlined"),
        Action("Third party licenses", "outlined", surface="licenses"),
    ),
)


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
        _PENDING_IMPORTS,
        _PLAYER_PANEL,
        _WORLD_INFO,
        _INVENTORY_EDITOR,
        _ITEM_TYPE_LIST,
        _CONFIGURE_BLOCKS,
        _RENDER_LAYERS,
        _VIEW_CONTROLS,
        _FOUR_UP_VIEW,
        _CUTAWAY_VIEW,
        _WORK_PLANE,
        _LIBRARY_PANEL,
        _PLUGINS_DIALOG,
        _MINECRAFT_INSTALLS,
        _UNDO_HISTORY,
        _LOG_VIEW,
        _PROFILER,
        _PYTHON_CONSOLE,
        _ERROR_REPORT,
        _ABOUT,
    )
}

__all__ = ["SPECS"]
