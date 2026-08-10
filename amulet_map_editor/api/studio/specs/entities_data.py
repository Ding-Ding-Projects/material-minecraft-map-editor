"""Surface descriptions for the entity, world-data, and mechanics families.

These twenty surfaces all read or rewrite the *stored* side of a world rather
than its blocks: the entities and block entities inside a selection, the raw NBT
behind them, ``level.dat`` and its game rules, and the derived views (redstone
wiring, rail networks, portal linkage, spawn conditions, tick load) that answer
questions about a world without editing it.

Keeping them here as data means the dialogs are one registry entry each instead
of twenty near-identical window classes, and it keeps every user-visible string
in one reviewable place.  Nothing in this module imports wx, so it loads
headlessly and can be asserted on in tests.
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
    sec,
)

SPECS: Dict[str, Spec] = {
    "entityBrowser": Spec(
        key="entityBrowser",
        eyebrow="Entities",
        title="Entity browser",
        width=800,
        confirm="Close",
        intro=(
            "Every entity and block entity inside the selection, with counts per "
            "type. Selecting a row frames it in the viewport."
        ),
        sections=(
            sec("", "search", hint="Search by type, name, or NBT path"),
            sec(
                "Filters",
                "chips",
                chips=[
                    "Hostile",
                    "Passive",
                    "Villagers",
                    "Items",
                    "Vehicles",
                    "Block entities",
                    "Named only",
                ],
            ),
            sec(
                "Entities",
                "list",
                rows=[
                    Row(
                        name="minecraft:villager",
                        detail="12 in selection · 3 named · profession librarian",
                        tag="12",
                    ),
                    Row(
                        name="minecraft:zombie",
                        detail="8 in selection · none named",
                        tag="8",
                    ),
                    Row(
                        name="minecraft:item_frame",
                        detail="6 in selection · 4 hold items",
                        tag="6",
                    ),
                    Row(
                        name="minecraft:chest (block entity)",
                        detail="23 in selection · 19 non-empty",
                        tag="23",
                    ),
                    Row(
                        name="minecraft:mob_spawner",
                        detail="2 in selection · skeleton, cave_spider",
                        tag="2",
                    ),
                ],
            ),
        ),
        actions=(
            Action("Frame in viewport", "tonal"),
            Action("Edit selected", "outlined", surface="entityEdit"),
            Action("Export list", "outlined"),
        ),
    ),
    "entityEdit": Spec(
        key="entityEdit",
        eyebrow="Entities",
        title="Edit entity",
        width=660,
        confirm="Commit entity",
        sections=(
            sec(
                "Identity",
                "fields",
                fields=[
                    Field(label="Type", value="minecraft:villager"),
                    Field(label="Custom name", value="Ana"),
                    Field(label="UUID", value="6f1c…a904"),
                    Field(label="Position", value="412.5, 71.0, 188.5"),
                ],
            ),
            sec(
                "State",
                "fields",
                fields=[
                    Field(label="Health", value="20.0"),
                    Field(label="Rotation", value="142.0, 0.0"),
                    Field(label="Profession", value="librarian"),
                    Field(label="Level", value="3"),
                ],
            ),
            sec(
                "Flags",
                "checks",
                checks=[
                    Check(label="Persistent", hint="Never despawns."),
                    Check(label="Invulnerable", hint="Ignores damage sources."),
                    Check(label="No AI", hint="Freezes behaviour."),
                    Check(label="Silent", hint="Suppresses sounds."),
                ],
            ),
            sec(
                "Raw tags",
                "code",
                code=(
                    "Villager:\n"
                    "  VillagerData: { profession: librarian, level: 3 }\n"
                    "  Offers: { Recipes: [ 4 entries ] }\n"
                    "  Brain: { memories: { … } }"
                ),
            ),
        ),
        actions=(
            Action("Open in NBT editor", "outlined", surface="nbt"),
            Action("Duplicate", "tonal"),
            Action("Delete entity", "danger"),
        ),
    ),
    "removeEntities": Spec(
        key="removeEntities",
        eyebrow="Entities",
        title="Remove entities",
        width=600,
        confirm="Remove matching",
        intro=(
            "Removal is scoped to the selection and previewed before it runs. One "
            "revision is committed so it can be restored."
        ),
        sections=(
            sec(
                "Filter",
                "selects",
                selects=[
                    Select(
                        label="Category",
                        options=(
                            "All entities",
                            "Hostile",
                            "Passive",
                            "Items on ground",
                            "Vehicles",
                            "Projectiles",
                        ),
                    ),
                    Select(
                        label="Named entities",
                        options=("Include named", "Skip named", "Named only"),
                    ),
                ],
            ),
            sec(
                "Type filter",
                "fields",
                fields=[
                    Field(
                        label="Type pattern",
                        value="minecraft:zombie|minecraft:husk",
                    ),
                ],
            ),
            sec(
                "Preview",
                "list",
                rows=[
                    Row(
                        name="Matches",
                        detail="14 entities across 6 chunks",
                        tag="14",
                    ),
                    Row(name="Skipped", detail="3 named entities", tag="3"),
                ],
            ),
        ),
        actions=(
            Action("Preview matches", "tonal"),
            Action("Open regex builder", "outlined", surface="regex"),
        ),
    ),
    "lootAudit": Spec(
        key="lootAudit",
        eyebrow="Containers",
        title="Loot audit",
        width=720,
        confirm="Close",
        sections=(
            sec("", "search", hint="Search containers, loot tables, and items"),
            sec(
                "Containers",
                "list",
                rows=[
                    Row(
                        name="minecraft:chest at 412, 71, 188",
                        detail="Unrolled · 14 item stacks",
                        tag="filled",
                    ),
                    Row(
                        name="minecraft:chest at 96, 42, -12",
                        detail="LootTable: minecraft:chests/simple_dungeon",
                        tag="unrolled",
                    ),
                    Row(
                        name="minecraft:barrel at 66, 118, -43",
                        detail="Empty",
                        tag="empty",
                    ),
                ],
            ),
            sec(
                "",
                "note",
                hint=(
                    "An unrolled loot table generates only when a player first "
                    "opens the container. Editing the contents clears the table "
                    "reference."
                ),
            ),
        ),
        actions=(
            Action("Clear loot tables", "danger"),
            Action("Export inventory report", "outlined"),
        ),
    ),
    "nbtSearch": Spec(
        key="nbtSearch",
        eyebrow="Data",
        title="NBT search and replace",
        width=760,
        confirm="Replace matches",
        intro=(
            "Searches raw tags across the selection. Plain text is the default; "
            "regex is opt-in and bounded."
        ),
        sections=(
            sec("", "search", hint="Tag path or value, e.g. Items[].id"),
            sec(
                "Query",
                "fields",
                fields=[
                    Field(label="Tag path", value="Items[].id"),
                    Field(label="Find value", value="minecraft:oak_planks"),
                    Field(label="Replace with", value="minecraft:spruce_planks"),
                    Field(label="Max matches", value="5000"),
                ],
            ),
            sec(
                "Scope",
                "checks",
                checks=[
                    Check(
                        label="Block entities",
                        hint="Chests, signs, spawners, and similar.",
                    ),
                    Check(label="Entities", hint="Mobs, items, and vehicles."),
                    Check(
                        label="Chunk-level tags",
                        hint="Heightmaps and structure references.",
                    ),
                ],
            ),
            sec(
                "Matches",
                "list",
                rows=[
                    Row(
                        name="minecraft:chest at 412, 71, 188",
                        detail="Items[3].id = minecraft:oak_planks",
                        tag="match",
                    ),
                    Row(
                        name="minecraft:barrel at 88, 64, 24",
                        detail="Items[0].id = minecraft:oak_planks",
                        tag="match",
                    ),
                ],
            ),
        ),
        actions=(
            Action("Find matches", "tonal"),
            Action("Open regex builder", "outlined", surface="regex"),
            Action("Export matches", "outlined"),
        ),
    ),
    "signSearch": Spec(
        key="signSearch",
        eyebrow="Data",
        title="Sign text",
        width=700,
        confirm="Apply edits",
        sections=(
            sec("", "search", hint="Search sign text on all four lines"),
            sec(
                "Signs",
                "list",
                rows=[
                    Row(
                        name="412, 72, 188",
                        detail="Market Row / Open daily / — / south gate",
                        tag="edit",
                    ),
                    Row(
                        name="66, 119, -43",
                        detail="Spawn / mind the drop",
                        tag="edit",
                    ),
                    Row(
                        name="88, 65, 24",
                        detail="Storage / planks and logs",
                        tag="edit",
                    ),
                ],
            ),
            sec(
                "Selected sign",
                "fields",
                fields=[
                    Field(label="Line 1", value="Market Row"),
                    Field(label="Line 2", value="Open daily"),
                    Field(label="Line 3", value=""),
                    Field(label="Line 4", value="south gate"),
                ],
            ),
            sec(
                "Style",
                "selects",
                selects=[
                    Select(
                        label="Text colour",
                        options=("black", "white", "red", "blue", "yellow"),
                    ),
                    Select(label="Glowing", options=("off", "on")),
                ],
            ),
        ),
        actions=(
            Action("Replace across matches", "tonal"),
            Action("Export text", "outlined"),
        ),
    ),
    "commandFinder": Spec(
        key="commandFinder",
        eyebrow="Data",
        title="Command blocks",
        width=760,
        confirm="Apply edits",
        sections=(
            sec("", "search", hint="Search commands, coordinates, and block types"),
            sec(
                "Command blocks",
                "list",
                rows=[
                    Row(
                        name="412, 70, 190 · impulse",
                        detail="/tp @p 66 118 -43",
                        tag="needs redstone",
                    ),
                    Row(
                        name="412, 70, 191 · chain",
                        detail="/effect give @p minecraft:speed 10 1",
                        tag="always active",
                    ),
                    Row(
                        name="96, 40, -12 · repeat",
                        detail=(
                            "/execute as @a[distance=..8] run title @s actionbar …"
                        ),
                        tag="always active",
                    ),
                ],
            ),
            sec(
                "Selected block",
                "fields",
                fields=[
                    Field(label="Command", value="/tp @p 66 118 -43"),
                    Field(label="Custom name", value="@"),
                    Field(label="Type", value="impulse"),
                    Field(label="Condition", value="unconditional"),
                ],
            ),
            sec(
                "",
                "note",
                hint=(
                    "Amulet does not validate command syntax against a game build. "
                    "Commands are stored verbatim."
                ),
            ),
        ),
        actions=(
            Action("Replace in matches", "tonal"),
            Action("Export commands", "outlined"),
        ),
    ),
    "playerData": Spec(
        key="playerData",
        eyebrow="Data",
        title="Player data",
        width=720,
        confirm="Commit player data",
        sections=(
            sec(
                "Players",
                "list",
                rows=[
                    Row(
                        name="6f1c…a904",
                        detail="Last seen 66, 118, -43 · overworld · level 34",
                        tag="local",
                    ),
                    Row(
                        name="b28d…41ff",
                        detail="Last seen 412, 71, 188 · overworld · level 12",
                        tag="local",
                    ),
                ],
            ),
            sec(
                "Position",
                "fields",
                fields=[
                    Field(label="x", value="66.40"),
                    Field(label="y", value="118.13"),
                    Field(label="z", value="-43.12"),
                    Field(label="Dimension", value="overworld"),
                ],
            ),
            sec(
                "State",
                "fields",
                fields=[
                    Field(label="Health", value="20.0"),
                    Field(label="Food", value="18"),
                    Field(label="XP level", value="34"),
                    Field(label="Game mode", value="creative"),
                ],
            ),
            sec(
                "Inventory",
                "list",
                rows=[
                    Row(name="Hotbar", detail="9 slots · 7 occupied", tag="edit"),
                    Row(
                        name="Main inventory",
                        detail="27 slots · 14 occupied",
                        tag="edit",
                    ),
                    Row(
                        name="Ender chest",
                        detail="27 slots · 3 occupied",
                        tag="edit",
                    ),
                ],
            ),
        ),
        actions=(
            Action("Open in NBT editor", "outlined", surface="nbt"),
            Action("Reset position to spawn", "tonal"),
        ),
    ),
    "levelDat": Spec(
        key="levelDat",
        eyebrow="Data",
        title="level.dat",
        width=700,
        confirm="Save level.dat",
        intro=(
            "Fields are validated against the platform before saving. A rejected "
            "value reports an exact reason and is not written."
        ),
        sections=(
            sec(
                "World",
                "fields",
                fields=[
                    Field(label="Level name", value="1.17 Height"),
                    Field(label="Seed", value="1471929"),
                    Field(label="Spawn x", value="66"),
                    Field(label="Spawn y", value="118"),
                    Field(label="Spawn z", value="-43"),
                    Field(label="Time", value="148291"),
                ],
            ),
            sec(
                "Rules",
                "selects",
                selects=[
                    Select(
                        label="Default game mode",
                        options=("survival", "creative", "adventure", "spectator"),
                    ),
                    Select(
                        label="Difficulty",
                        options=("peaceful", "easy", "normal", "hard"),
                    ),
                    Select(
                        label="Generator",
                        options=("default", "flat", "large_biomes", "amplified"),
                    ),
                    Select(label="Weather", options=("clear", "rain", "thunder")),
                ],
            ),
            sec(
                "Flags",
                "checks",
                checks=[
                    Check(
                        label="Allow commands",
                        hint="Enables cheats in single player.",
                    ),
                    Check(
                        label="Hardcore",
                        hint="Death locks the world to spectator.",
                    ),
                    Check(label="Raining", hint="Sets the current weather state."),
                ],
            ),
        ),
        actions=(
            Action("Open in NBT editor", "outlined", surface="nbt"),
            Action("Revert changes", "danger"),
        ),
    ),
    "gamerules": Spec(
        key="gamerules",
        eyebrow="Data",
        title="Game rules",
        width=700,
        confirm="Save game rules",
        sections=(
            sec("", "search", hint="Search game rules"),
            sec(
                "Rules",
                "list",
                rows=[
                    Row(name="doDaylightCycle", detail="Boolean", tag="true"),
                    Row(name="keepInventory", detail="Boolean", tag="false"),
                    Row(name="mobGriefing", detail="Boolean", tag="false"),
                    Row(name="randomTickSpeed", detail="Integer", tag="3"),
                    Row(name="commandBlockOutput", detail="Boolean", tag="false"),
                    Row(name="maxEntityCramming", detail="Integer", tag="24"),
                    Row(name="doFireTick", detail="Boolean", tag="true"),
                    Row(
                        name="showCoordinates",
                        detail="Boolean · Bedrock only",
                        tag="true",
                    ),
                ],
            ),
            sec(
                "",
                "note",
                hint=(
                    "Rules that do not exist on the world's platform are hidden "
                    "rather than written with a default."
                ),
            ),
        ),
        actions=(Action("Reset rule to default", "outlined"),),
    ),
    "scoreboard": Spec(
        key="scoreboard",
        eyebrow="Data",
        title="Scoreboard",
        width=740,
        confirm="Save scoreboard",
        sections=(
            sec(
                "Objectives",
                "list",
                rows=[
                    Row(
                        name="deaths",
                        detail="criteria deathCount · displayed in sidebar",
                        tag="12 scores",
                    ),
                    Row(
                        name="blocksMined",
                        detail="criteria minecraft.mined:minecraft.stone",
                        tag="2 scores",
                    ),
                ],
            ),
            sec(
                "Teams",
                "list",
                rows=[
                    Row(
                        name="builders",
                        detail="3 members · colour aqua · friendly fire off",
                        tag="edit",
                    ),
                    Row(
                        name="testers",
                        detail="1 member · colour gold",
                        tag="edit",
                    ),
                ],
            ),
            sec(
                "Scores",
                "fields",
                fields=[
                    Field(label="Holder", value="Ana"),
                    Field(label="Score", value="14"),
                ],
            ),
        ),
        actions=(
            Action("Add objective", "tonal"),
            Action("Remove", "danger"),
        ),
    ),
    "mapItems": Spec(
        key="mapItems",
        eyebrow="Data",
        title="Map items",
        width=700,
        confirm="Close",
        sections=(
            sec(
                "Maps",
                "list",
                rows=[
                    Row(
                        name="map_0",
                        detail="overworld · scale 3 · centre 64, -32 · locked",
                        tag="view",
                    ),
                    Row(
                        name="map_1",
                        detail="overworld · scale 1 · centre 416, 192",
                        tag="view",
                    ),
                    Row(
                        name="map_2",
                        detail="the_nether · scale 2 · centre 0, 0",
                        tag="view",
                    ),
                ],
            ),
            sec(
                "Selected map",
                "fields",
                fields=[
                    Field(label="Scale", value="3"),
                    Field(label="Centre x", value="64"),
                    Field(label="Centre z", value="-32"),
                    Field(label="Banners tracked", value="4"),
                ],
            ),
            sec(
                "",
                "note",
                hint=(
                    "Stored map colour data is exported as an image; it is not "
                    "re-rendered from the world."
                ),
            ),
        ),
        actions=(
            Action("Export as PNG", "outlined"),
            Action("Clear map data", "danger"),
        ),
    ),
    "blockAudit": Spec(
        key="blockAudit",
        eyebrow="Blocks",
        title="Block state audit",
        width=740,
        confirm="Close",
        intro=(
            "Lists block states that the translation layer could not map cleanly. "
            "Nothing is rewritten without an explicit choice."
        ),
        sections=(
            sec(
                "Findings",
                "list",
                rows=[
                    Row(
                        name="minecraft:cave_air",
                        detail="42 blocks · unknown on target java 1.12.2",
                        tag="unmapped",
                    ),
                    Row(
                        name="minecraft:oak_log[axis=none]",
                        detail="6 blocks · deprecated state value",
                        tag="deprecated",
                    ),
                    Row(
                        name="amulet:unknown_block",
                        detail="3 blocks · placeholder from a failed read",
                        tag="placeholder",
                    ),
                ],
            ),
            sec(
                "Resolution",
                "selects",
                selects=[
                    Select(
                        label="Action",
                        options=(
                            "Leave as-is",
                            "Map to nearest state",
                            "Replace with air",
                            "Replace with chosen block",
                        ),
                    ),
                    Select(
                        label="Scope",
                        options=("Selection", "Loaded chunks", "Whole dimension"),
                    ),
                ],
            ),
        ),
        actions=(
            Action("Apply resolution", "tonal"),
            Action("Export report", "outlined"),
        ),
    ),
    "redstoneTrace": Spec(
        key="redstoneTrace",
        eyebrow="Redstone",
        title="Circuit trace",
        width=760,
        confirm="Close",
        intro=(
            "Follows wiring outward from the selected component and lists "
            "everything electrically connected to it. Tracing never changes blocks."
        ),
        sections=(
            sec(
                "Origin",
                "fields",
                fields=[
                    Field(label="Component", value="minecraft:lever"),
                    Field(label="Position", value="412, 70, 190"),
                ],
            ),
            sec(
                "Connected components",
                "list",
                rows=[
                    Row(
                        name="minecraft:redstone_wire",
                        detail="48 blocks · longest run 14",
                        tag="wire",
                    ),
                    Row(
                        name="minecraft:repeater",
                        detail="6 · delays 1, 1, 2, 2, 4, 4",
                        tag="delay 14t",
                    ),
                    Row(
                        name="minecraft:comparator",
                        detail="2 · one in subtract mode",
                        tag="logic",
                    ),
                    Row(
                        name="minecraft:piston",
                        detail="4 sticky, 2 normal",
                        tag="output",
                    ),
                    Row(
                        name="minecraft:observer",
                        detail="3 · facing up",
                        tag="input",
                    ),
                ],
            ),
            sec(
                "Signal",
                "list",
                rows=[
                    Row(
                        name="Source strength",
                        detail="Lever powers adjacent wire",
                        tag="15",
                    ),
                    Row(
                        name="Weakest tail",
                        detail="Wire at 402, 70, 190",
                        tag="1",
                    ),
                    Row(
                        name="Total delay",
                        detail="Sum of repeater delays on the longest path",
                        tag="14 ticks",
                    ),
                ],
            ),
            sec(
                "Transform",
                "selects",
                selects=[
                    Select(
                        label="Action",
                        options=(
                            "Rotate 90° clockwise",
                            "Rotate 90° anti-clockwise",
                            "Mirror east–west",
                            "Mirror north–south",
                        ),
                    ),
                    Select(
                        label="Wiring",
                        options=(
                            "Preserve facing and delays",
                            "Reset repeater delays",
                        ),
                    ),
                ],
            ),
            sec(
                "",
                "note",
                hint=(
                    "Rotating a circuit rewrites facing, rail shape, and observer "
                    "direction together so the wiring stays valid."
                ),
            ),
        ),
        actions=(
            Action("Frame circuit", "tonal"),
            Action("Apply transform", "outlined"),
            Action("Export component list", "outlined"),
        ),
    ),
    "railNetwork": Spec(
        key="railNetwork",
        eyebrow="Redstone",
        title="Rail network",
        width=740,
        confirm="Close",
        sections=(
            sec("", "search", hint="Search by coordinate, rail type, or junction"),
            sec(
                "Networks",
                "list",
                rows=[
                    Row(
                        name="Spawn ↔ market line",
                        detail="412 rails · 18 powered · 4 junctions · 6 detector",
                        tag="connected",
                    ),
                    Row(
                        name="Nether highway spur",
                        detail="96 rails · 2 powered · unpowered gap at 44, 64, 12",
                        tag="gap",
                    ),
                    Row(
                        name="Storage loop",
                        detail="64 rails · closed circuit",
                        tag="connected",
                    ),
                ],
            ),
            sec(
                "Findings",
                "list",
                rows=[
                    Row(
                        name="Unpowered run too long",
                        detail="22 blocks between powered rails at 44, 64, 12",
                        tag="warning",
                    ),
                    Row(
                        name="Dead-end junction",
                        detail="Rail at 118, 70, 8 points into a wall",
                        tag="warning",
                    ),
                ],
            ),
            sec(
                "Repair",
                "checks",
                checks=[
                    Check(
                        label="Insert powered rails at the maximum interval",
                        hint="Uses redstone blocks beneath where no power exists.",
                    ),
                    Check(
                        label="Fix rail shapes at junctions",
                        hint="Rewrites rail shape so curves connect.",
                    ),
                ],
            ),
        ),
        actions=(
            Action("Frame network", "tonal"),
            Action("Apply repairs", "outlined"),
        ),
    ),
    "portalLinker": Spec(
        key="portalLinker",
        eyebrow="Redstone",
        title="Portal linkage",
        width=740,
        confirm="Close",
        intro=(
            "Overworld and Nether coordinates link at an 8:1 ratio. This lists "
            "every portal and the destination it will actually resolve to."
        ),
        sections=(
            sec(
                "Portals",
                "list",
                rows=[
                    Row(
                        name="Overworld 416, 72, 192",
                        detail=(
                            "Links to nether 52, 72, 24 · nearest portal 8 blocks "
                            "away"
                        ),
                        tag="linked",
                    ),
                    Row(
                        name="Overworld 64, 118, -40",
                        detail="Links to nether 8, 118, -5 · no portal within 128",
                        tag="will build",
                    ),
                    Row(
                        name="Nether 8, 64, -5",
                        detail="Links to overworld 64, 64, -40",
                        tag="linked",
                    ),
                    Row(
                        name="End portal 100, 49, 0",
                        detail="12 frames · 12 eyes placed",
                        tag="complete",
                    ),
                ],
            ),
            sec(
                "Ratio calculator",
                "fields",
                fields=[
                    Field(label="Overworld x", value="416"),
                    Field(label="Overworld z", value="192"),
                    Field(label="Nether x", value="52"),
                    Field(label="Nether z", value="24"),
                ],
            ),
            sec(
                "",
                "note",
                hint=(
                    "Amulet reports the coordinates the game will use. It does not "
                    "simulate the portal search radius beyond the documented rules."
                ),
            ),
        ),
        actions=(
            Action("Go to portal", "tonal"),
            Action("Export linkage table", "outlined"),
        ),
    ),
    "spawnPoints": Spec(
        key="spawnPoints",
        eyebrow="Redstone",
        title="Spawn points and beds",
        width=700,
        confirm="Close",
        sections=(
            sec(
                "World spawn",
                "fields",
                fields=[
                    Field(label="x", value="66"),
                    Field(label="y", value="118"),
                    Field(label="z", value="-43"),
                    Field(label="Spawn radius", value="16"),
                ],
            ),
            sec(
                "Player respawn",
                "list",
                rows=[
                    Row(
                        name="6f1c…a904",
                        detail="Bed at 412, 71, 188 · overworld · valid",
                        tag="bed",
                    ),
                    Row(
                        name="b28d…41ff",
                        detail="Respawn anchor at 12, 64, 8 · the_nether · 3 charges",
                        tag="anchor",
                    ),
                ],
            ),
            sec(
                "Findings",
                "list",
                rows=[
                    Row(
                        name="Obstructed bed",
                        detail="Bed at 96, 42, -12 has no clear space",
                        tag="warning",
                    ),
                ],
            ),
        ),
        actions=(
            Action("Set world spawn to camera", "tonal"),
            Action("Clear respawn point", "danger"),
        ),
    ),
    "spawnAnalysis": Spec(
        key="spawnAnalysis",
        eyebrow="Mechanics",
        title="Mob spawn analysis",
        width=760,
        confirm="Close",
        intro=(
            "Evaluates spawn conditions per column inside the selection: light "
            "level, block face, space, and biome category."
        ),
        sections=(
            sec(
                "Summary",
                "list",
                rows=[
                    Row(
                        name="Spawnable columns",
                        detail="142 of 288 surface columns",
                        tag="49%",
                    ),
                    Row(
                        name="Hostile-capable",
                        detail="118 columns · light level 0",
                        tag="41%",
                    ),
                    Row(
                        name="Passive-capable",
                        detail="64 columns · grass with sky access",
                        tag="22%",
                    ),
                    Row(
                        name="Blocked",
                        detail="146 columns · lit, slabbed, or no space",
                        tag="51%",
                    ),
                ],
            ),
            sec(
                "Overlay",
                "selects",
                selects=[
                    Select(
                        label="Show",
                        options=(
                            "Hostile spawnable",
                            "Passive spawnable",
                            "Both",
                            "Off",
                        ),
                    ),
                    Select(
                        label="Time",
                        options=("Night", "Day", "Ignore time"),
                    ),
                ],
            ),
            sec(
                "Spawn-proof",
                "checks",
                checks=[
                    Check(
                        label="Place light sources on spawnable faces",
                        hint="Uses the chosen block at the calculated interval.",
                    ),
                    Check(
                        label="Place slabs on spawnable faces",
                        hint="Blocks spawning without adding light.",
                    ),
                ],
            ),
        ),
        actions=(
            Action("Apply spawn-proofing", "tonal"),
            Action("Light level overlay", "outlined", surface="lightOverlay"),
        ),
    ),
    "lightOverlay": Spec(
        key="lightOverlay",
        eyebrow="Mechanics",
        title="Light levels",
        width=660,
        confirm="Apply overlay",
        sections=(
            sec(
                "Overlay",
                "selects",
                selects=[
                    Select(
                        label="Channel",
                        options=(
                            "Block light",
                            "Sky light",
                            "Combined",
                            "Spawn threshold only",
                        ),
                    ),
                    Select(
                        label="Display",
                        options=("Numbers on faces", "Heat colours", "Both"),
                    ),
                ],
            ),
            sec(
                "Threshold",
                "ranges",
                ranges=[
                    RangeDef(label="Highlight at or below", value=0, min=0, max=15),
                ],
            ),
            sec(
                "Readout",
                "list",
                rows=[
                    Row(
                        name="Light level 0",
                        detail="118 exposed faces",
                        tag="spawnable",
                    ),
                    Row(name="Light level 1–7", detail="64 faces", tag="dim"),
                    Row(name="Light level 8–15", detail="106 faces", tag="lit"),
                ],
            ),
            sec(
                "",
                "note",
                hint=(
                    "Values are read from stored light data. Run Relight first if "
                    "the world was edited outside Amulet."
                ),
            ),
        ),
        actions=(Action("Relight selection", "outlined", surface="relight"),),
    ),
    "tickLoad": Spec(
        key="tickLoad",
        eyebrow="Mechanics",
        title="Tick load",
        width=740,
        confirm="Close",
        intro=(
            "Estimates per-chunk work from block entities, scheduled ticks, and "
            "random-tick candidates. Useful for finding lag sources before a world "
            "ships."
        ),
        sections=(
            sec(
                "Heaviest chunks",
                "list",
                rows=[
                    Row(
                        name="chunk 26, 12",
                        detail=("148 block entities · 62 hoppers · 12 scheduled ticks"),
                        tag="heavy",
                    ),
                    Row(
                        name="chunk 4, -13",
                        detail="26 block entities · 4 scheduled ticks",
                        tag="normal",
                    ),
                    Row(
                        name="chunk -8, 40",
                        detail="8 block entities · 212 random-tick candidates",
                        tag="watch",
                    ),
                ],
            ),
            sec(
                "Contributors",
                "list",
                rows=[
                    Row(
                        name="minecraft:hopper",
                        detail="212 in selection",
                        tag="high",
                    ),
                    Row(
                        name="minecraft:observer",
                        detail="48 in selection",
                        tag="medium",
                    ),
                    Row(
                        name="minecraft:sapling",
                        detail="96 random-tick candidates",
                        tag="low",
                    ),
                ],
            ),
            sec(
                "Random tick",
                "fields",
                fields=[
                    Field(label="randomTickSpeed", value="3"),
                    Field(label="Candidates per chunk", value="212"),
                ],
            ),
        ),
        actions=(
            Action("Frame chunk", "tonal"),
            Action("Export report", "outlined"),
            Action("Open game rules", "outlined", surface="gamerules"),
        ),
    ),
}
