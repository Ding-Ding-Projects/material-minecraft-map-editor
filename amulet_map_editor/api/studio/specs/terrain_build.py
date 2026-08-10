"""Surface descriptions for the terrain, build, navigation, and travel families.

These are the windows that change the world's shape rather than its metadata:
sculpting and generation passes, the build brushes and their pattern/mask
plumbing, the structure library, waypoints, and the two large travel builders
that assemble portals and rail tunnels.  Every value here is data transcribed
from the design source, so the renderer in
:mod:`amulet_map_editor.api.studio.spec_dialog` stays the only place that knows
about wxPython — a new surface is a dictionary entry, never a new window class.
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
    tex_section,
)

SPECS: Dict[str, Spec] = {
    "terrainBrush": Spec(
        key="terrainBrush",
        eyebrow="Sculpt",
        title="Terrain brush",
        width=640,
        confirm="Apply brush",
        intro=(
            "The brush edits the heightmap inside the selection only. Each stroke "
            "commits one revision, so any pass can be restored later."
        ),
        sections=(
            sec(
                "Shape",
                "selects",
                selects=[
                    Select(
                        label="Brush shape",
                        options=("Sphere", "Cylinder", "Square", "Cone"),
                    ),
                    Select(
                        label="Falloff",
                        options=("Smooth", "Linear", "Constant", "Gaussian"),
                    ),
                ],
            ),
            sec(
                "Size",
                "ranges",
                ranges=[
                    RangeDef(label="Radius (blocks)", value=12, min=1, max=64),
                    RangeDef(label="Strength", value=45, min=1, max=100),
                    RangeDef(label="Spacing", value=4, min=1, max=32),
                ],
            ),
            sec(
                "Material",
                "list",
                rows=[
                    Row(
                        name="Surface block",
                        detail="minecraft:grass_block",
                        tag="pick",
                    ),
                    Row(
                        name="Filler block",
                        detail="minecraft:dirt (3 deep)",
                        tag="pick",
                    ),
                    Row(name="Base block", detail="minecraft:stone", tag="pick"),
                ],
            ),
            sec(
                "Limits",
                "checks",
                checks=[
                    Check(
                        label="Respect world height limits",
                        hint="Clamps to the platform's build range.",
                    ),
                    Check(
                        label="Preserve block entities",
                        hint="Chests and signs are moved rather than destroyed.",
                    ),
                    Check(
                        label="Preview before applying",
                        hint="Shows the affected volume as a wireframe.",
                    ),
                ],
            ),
        ),
        actions=(
            Action(label="Preview stroke", kind="tonal"),
            Action(label="Reset brush", kind="outlined"),
        ),
    ),
    "smooth": Spec(
        key="smooth",
        eyebrow="Sculpt",
        title="Smooth terrain",
        width=560,
        confirm="Smooth selection",
        intro=(
            "Averages neighbouring heights across the selection. Higher iteration "
            "counts cost more time and produce softer slopes."
        ),
        sections=(
            sec(
                "Passes",
                "ranges",
                ranges=[
                    RangeDef(label="Iterations", value=3, min=1, max=20),
                    RangeDef(label="Kernel radius", value=2, min=1, max=8),
                ],
            ),
            sec(
                "Scope",
                "checks",
                checks=[
                    Check(
                        label="Smooth water edges",
                        hint="Includes shoreline transitions.",
                    ),
                    Check(
                        label="Ignore man-made blocks",
                        hint="Skips non-natural block palettes.",
                    ),
                ],
            ),
        ),
        actions=(Action(label="Preview", kind="tonal"),),
    ),
    "flatten": Spec(
        key="flatten",
        eyebrow="Sculpt",
        title="Flatten to height",
        width=560,
        confirm="Flatten",
        sections=(
            sec(
                "Target",
                "fields",
                fields=[
                    Field(label="Target Y", value="98"),
                    Field(label="Tolerance", value="2"),
                ],
            ),
            sec(
                "Mode",
                "selects",
                selects=[
                    Select(
                        label="Direction",
                        options=("Cut and fill", "Cut only", "Fill only"),
                    ),
                    Select(
                        label="Edge",
                        options=(
                            "Hard edge",
                            "Feathered 8 blocks",
                            "Feathered 16 blocks",
                        ),
                    ),
                ],
            ),
        ),
        actions=(Action(label="Sample height at cursor", kind="outlined"),),
    ),
    "erosion": Spec(
        key="erosion",
        eyebrow="Sculpt",
        title="Erosion",
        width=600,
        confirm="Run erosion",
        intro=(
            "Hydraulic and thermal passes weather the selection. Results are "
            "deterministic for a given seed and iteration count."
        ),
        sections=(
            sec(
                "Model",
                "selects",
                selects=[
                    Select(label="Type", options=("Hydraulic", "Thermal", "Combined")),
                    Select(
                        label="Deposit",
                        options=("Gravel and sand", "Dirt", "Match surface"),
                    ),
                ],
            ),
            sec(
                "Parameters",
                "ranges",
                ranges=[
                    RangeDef(label="Iterations", value=40, min=1, max=400),
                    RangeDef(label="Rain amount", value=30, min=1, max=100),
                    RangeDef(label="Talus angle", value=34, min=5, max=80),
                ],
            ),
            sec("Seed", "fields", fields=[Field(label="Seed", value="1471929")]),
        ),
        actions=(Action(label="Preview one pass", kind="tonal"),),
    ),
    "noiseGen": Spec(
        key="noiseGen",
        eyebrow="Generate",
        title="Noise fill",
        width=620,
        confirm="Generate",
        sections=(
            sec(
                "Field",
                "selects",
                selects=[
                    Select(
                        label="Noise",
                        options=(
                            "Perlin",
                            "Simplex",
                            "Ridged multifractal",
                            "Worley",
                        ),
                    ),
                    Select(
                        label="Output",
                        options=(
                            "Heightmap",
                            "Density (caves)",
                            "Scatter blocks",
                        ),
                    ),
                ],
            ),
            sec(
                "Shape",
                "ranges",
                ranges=[
                    RangeDef(label="Octaves", value=4, min=1, max=8),
                    RangeDef(label="Frequency ×100", value=12, min=1, max=100),
                    RangeDef(label="Amplitude (blocks)", value=24, min=1, max=128),
                ],
            ),
            sec(
                "Seed and material",
                "fields",
                fields=[
                    Field(label="Seed", value="1471929"),
                    Field(label="Block", value="minecraft:stone"),
                ],
            ),
        ),
        actions=(
            Action(label="Preview slice", kind="tonal"),
            Action(label="Randomize seed", kind="outlined"),
        ),
    ),
    "seaLevel": Spec(
        key="seaLevel",
        eyebrow="Generate",
        title="Sea level",
        width=560,
        confirm="Apply water level",
        sections=(
            sec(
                "Level",
                "fields",
                fields=[
                    Field(label="Water Y", value="62"),
                    Field(label="Fluid", value="minecraft:water"),
                ],
            ),
            sec(
                "Mode",
                "selects",
                selects=[
                    Select(
                        label="Action",
                        options=(
                            "Fill to level",
                            "Drain above level",
                            "Replace fluid",
                        ),
                    ),
                    Select(
                        label="Enclosure",
                        options=("Only enclosed volumes", "Whole selection"),
                    ),
                ],
            ),
            sec(
                "",
                "note",
                hint=(
                    "Draining does not remove waterlogged states. Use Waterlog in "
                    "Operations to change those."
                ),
            ),
        ),
        actions=(),
    ),
    "regenerate": Spec(
        key="regenerate",
        eyebrow="Generate",
        title="Regenerate chunks",
        width=600,
        confirm="Regenerate selection",
        intro=(
            "Deletes the selected chunks so the game regenerates them from the "
            "world seed. Every block, entity, and container inside them is lost."
        ),
        sections=(
            sec(
                "Scope",
                "list",
                rows=[
                    Row(
                        name="Chunks selected",
                        detail="12 chunks across 2 regions",
                        tag="target",
                    ),
                    Row(
                        name="Seed",
                        detail="1471929 (read from level.dat)",
                        tag="world",
                    ),
                    Row(
                        name="Backup",
                        detail="One revision is committed before deletion",
                        tag="safe",
                    ),
                ],
            ),
            sec("Two-key gate", "keygate"),
        ),
        actions=(Action(label="Emergency exit", kind="outlined"),),
    ),
    "surfacePaint": Spec(
        key="surfacePaint",
        eyebrow="Surface",
        title="Repaint surface",
        width=620,
        confirm="Repaint",
        sections=(
            sec(
                "Rule set",
                "list",
                rows=[
                    Row(
                        name="Above Y 120",
                        detail="minecraft:snow_block over minecraft:stone",
                        tag="rule",
                    ),
                    Row(
                        name="Y 96–120",
                        detail="minecraft:grass_block over minecraft:dirt ×3",
                        tag="rule",
                    ),
                    Row(
                        name="Below Y 64 in water",
                        detail="minecraft:sand over minecraft:sandstone",
                        tag="rule",
                    ),
                ],
            ),
            sec(
                "Match",
                "selects",
                selects=[
                    Select(
                        label="Driven by",
                        options=("Height", "Biome", "Slope", "Existing block"),
                    ),
                    Select(
                        label="Blend",
                        options=("Hard bands", "Dithered", "Noise blended"),
                    ),
                ],
            ),
            sec(
                "Depth",
                "ranges",
                ranges=[RangeDef(label="Surface depth", value=3, min=1, max=12)],
            ),
        ),
        actions=(
            Action(label="Add rule", kind="tonal"),
            Action(label="Remove rule", kind="danger"),
        ),
    ),
    "brushTool": Spec(
        key="brushTool",
        eyebrow="Build",
        title="Shape brush",
        width=640,
        confirm="Draw shape",
        sections=(
            sec(
                "Shape",
                "chips",
                chips=[
                    "Sphere",
                    "Hollow sphere",
                    "Cylinder",
                    "Hollow cylinder",
                    "Cuboid",
                    "Pyramid",
                    "Line",
                    "Path",
                    "Torus",
                ],
            ),
            sec(
                "Dimensions",
                "fields",
                fields=[
                    Field(label="Radius / dx", value="8"),
                    Field(label="Height / dy", value="8"),
                    Field(label="Depth / dz", value="8"),
                    Field(label="Wall thickness", value="1"),
                ],
            ),
            sec(
                "Material",
                "list",
                rows=[
                    Row(
                        name="Fill block",
                        detail="minecraft:stone_bricks",
                        tag="pick",
                    ),
                    Row(
                        name="Shell block",
                        detail="minecraft:polished_deepslate",
                        tag="pick",
                    ),
                ],
            ),
            sec(
                "Options",
                "checks",
                checks=[
                    Check(
                        label="Snap to selection centre",
                        hint="Otherwise the shape follows the cursor.",
                    ),
                    Check(
                        label="Replace air only",
                        hint="Existing blocks stay untouched.",
                    ),
                ],
            ),
        ),
        actions=(Action(label="Preview shape", kind="tonal"),),
    ),
    "patternMask": Spec(
        key="patternMask",
        eyebrow="Build",
        title="Pattern and mask",
        width=660,
        confirm="Apply pattern",
        intro=(
            "Patterns are weighted block sets. Masks limit every build and terrain "
            "edit to blocks that match."
        ),
        sections=(
            sec(
                "Pattern",
                "list",
                rows=[
                    Row(name="minecraft:stone", detail="weight 60", tag="60%"),
                    Row(name="minecraft:cobblestone", detail="weight 25", tag="25%"),
                    Row(name="minecraft:andesite", detail="weight 15", tag="15%"),
                ],
            ),
            sec(
                "Mask",
                "selects",
                selects=[
                    Select(
                        label="Match",
                        options=(
                            "Any block",
                            "Air only",
                            "Solid only",
                            "Matching pattern",
                            "Inverse of pattern",
                        ),
                    ),
                    Select(
                        label="Applies to",
                        options=("Build tools", "Terrain tools", "Both"),
                    ),
                ],
            ),
            tex_section(
                "minecraft:stone",
                "pattern-texture",
                "The highest-weighted block in the pattern previews here.",
            ),
            sec(
                "Gradient",
                "fields",
                fields=[
                    Field(label="From block", value="minecraft:stone"),
                    Field(label="To block", value="minecraft:deepslate"),
                ],
            ),
        ),
        actions=(
            Action(label="Add block to pattern", kind="tonal"),
            Action(label="Clear pattern", kind="danger"),
        ),
    ),
    "stackArray": Spec(
        key="stackArray",
        eyebrow="Build",
        title="Stack and array",
        width=620,
        confirm="Create copies",
        sections=(
            sec(
                "Mode",
                "selects",
                selects=[
                    Select(
                        label="Layout",
                        options=("Linear stack", "Grid array", "Radial array"),
                    ),
                    Select(label="Axis", options=("x", "y", "z", "camera facing")),
                ],
            ),
            sec(
                "Counts",
                "fields",
                fields=[
                    Field(label="Copies", value="6"),
                    Field(label="Spacing (blocks)", value="18"),
                    Field(label="Rotation step", value="0"),
                    Field(label="Y offset per copy", value="0"),
                ],
            ),
            sec(
                "Options",
                "checks",
                checks=[
                    Check(
                        label="Include air",
                        hint="Air in the source overwrites the destination.",
                    ),
                    Check(
                        label="Merge into one revision",
                        hint="Otherwise each copy commits separately.",
                    ),
                ],
            ),
        ),
        actions=(Action(label="Preview copies", kind="tonal"),),
    ),
    "schematicLibrary": Spec(
        key="schematicLibrary",
        eyebrow="Build",
        title="Structure library",
        width=760,
        confirm="Stage for paste",
        intro=(
            "Staged structures live inside the project. Tags and search cover file "
            "names, dimensions, and platform."
        ),
        sections=(
            sec("", "search", hint="Search structures, tags, and platforms"),
            sec(
                "Structures",
                "list",
                rows=[
                    Row(
                        name="spawn-arch.construction",
                        detail="24x18x24 · bedrock 1.17 · tags: spawn, stone",
                        tag="stage",
                    ),
                    Row(
                        name="market-row.schem",
                        detail="48x22x16 · java 1.20 · tags: town",
                        tag="stage",
                    ),
                    Row(
                        name="watchtower.mcstructure",
                        detail="12x34x12 · bedrock 1.17 · tags: defence",
                        tag="stage",
                    ),
                    Row(
                        name="bridge-span.schematic",
                        detail="64x9x8 · legacy 1.12 · tags: infra",
                        tag="stage",
                    ),
                ],
            ),
            sec(
                "Tags",
                "chips",
                chips=[
                    "spawn",
                    "town",
                    "defence",
                    "infra",
                    "terrain",
                    "interior",
                ],
            ),
        ),
        actions=(
            Action(label="Import file…", kind="tonal"),
            Action(label="Export selected", kind="outlined"),
            Action(label="Delete", kind="danger"),
        ),
    ),
    "waypoints": Spec(
        key="waypoints",
        eyebrow="Navigation",
        title="Waypoints",
        width=620,
        confirm="Go to waypoint",
        sections=(
            sec("", "search", hint="Search waypoints"),
            sec(
                "Saved",
                "list",
                rows=[
                    Row(
                        name="Spawn platform",
                        detail="66, 118, -43 · overworld",
                        tag="go",
                    ),
                    Row(
                        name="Market row south",
                        detail="412, 71, 188 · overworld",
                        tag="go",
                    ),
                    Row(
                        name="Nether hub",
                        detail="8, 64, -5 · the_nether",
                        tag="go",
                    ),
                    Row(
                        name="End gateway",
                        detail="100, 49, 0 · the_end",
                        tag="go",
                    ),
                ],
            ),
            sec(
                "New waypoint",
                "fields",
                fields=[
                    Field(label="Name", value="", placeholder="Waypoint name"),
                    Field(label="Coordinates", value="66, 118, -43"),
                ],
            ),
        ),
        actions=(
            Action(label="Add current camera", kind="tonal"),
            Action(label="Delete", kind="danger"),
        ),
    ),
    "portalBuilder": Spec(
        key="portalBuilder",
        eyebrow="Travel",
        title="Nether portal travel builder",
        width=820,
        confirm="Build both portals",
        intro=(
            "Builds a matched pair of portals so the link resolves the way you "
            "intend. Overworld and Nether coordinates relate at 8:1, so the builder "
            "places the Nether end at the divided position and reports what the "
            "game will actually resolve to."
        ),
        sections=(
            sec(
                "Overworld end",
                "fields",
                fields=[
                    Field(label="x", value="416"),
                    Field(label="y", value="72"),
                    Field(label="z", value="192"),
                    Field(label="Facing", value="north–south"),
                ],
            ),
            sec(
                "Nether end (computed)",
                "fields",
                fields=[
                    Field(label="x", value="52"),
                    Field(label="y", value="72"),
                    Field(label="z", value="24"),
                    Field(label="Override y", value=""),
                ],
            ),
            sec(
                "Frame",
                "selects",
                selects=[
                    Select(
                        label="Size",
                        options=("4×5 minimum", "5×5", "6×7", "Custom"),
                    ),
                    Select(
                        label="Frame block",
                        options=(
                            "minecraft:obsidian",
                            "minecraft:crying_obsidian",
                            "Mixed pattern",
                        ),
                    ),
                    Select(
                        label="Corners",
                        options=("Filled", "Open (vanilla minimum)"),
                    ),
                    Select(
                        label="Orientation",
                        options=("Match overworld", "Rotate 90°"),
                    ),
                ],
            ),
            sec(
                "Landing safety",
                "checks",
                checks=[
                    Check(
                        label="Clear a landing pod at both ends",
                        hint=(
                            "Carves a 5×3×5 space and floors it so you never arrive "
                            "inside terrain."
                        ),
                    ),
                    Check(
                        label="Wall off lava and open drops",
                        hint="Encloses the pod with the chosen wall block.",
                    ),
                    Check(
                        label="Light both pods",
                        hint="Places light sources at the chosen interval.",
                    ),
                    Check(
                        label="Add a return sign with coordinates",
                        hint=(
                            "Writes the far-side coordinates onto a sign beside each "
                            "portal."
                        ),
                    ),
                ],
            ),
            sec(
                "Materials",
                "list",
                rows=[
                    Row(
                        name="minecraft:obsidian",
                        detail="Frame, both ends",
                        tag="28",
                    ),
                    Row(
                        name="minecraft:stone_bricks",
                        detail="Pod floor, walls, and roof",
                        tag="146",
                    ),
                    Row(
                        name="minecraft:lantern",
                        detail="Pod lighting",
                        tag="8",
                    ),
                    Row(
                        name="minecraft:oak_sign",
                        detail="Return coordinates",
                        tag="2",
                    ),
                ],
            ),
            sec(
                "Link check",
                "list",
                rows=[
                    Row(
                        name="Nearest existing Nether portal",
                        detail="52, 72, 24 · 8 blocks from the computed position",
                        tag="will capture",
                    ),
                    Row(
                        name="Resolved destination",
                        detail="Overworld 416, 72, 192 → Nether 52, 72, 24",
                        tag="as intended",
                    ),
                    Row(
                        name="Roof clearance",
                        detail="Nether end sits below y 122",
                        tag="safe",
                    ),
                    Row(
                        name="Height limits",
                        detail="Nether build range on this platform is 0 to 128",
                        tag="within",
                    ),
                ],
            ),
            sec(
                "",
                "note",
                hint=(
                    "A portal within range of the computed position will capture the "
                    "link instead of your new one. The builder names that portal "
                    "rather than silently linking somewhere else."
                ),
            ),
        ),
        actions=(
            Action(label="Preview both ends", kind="tonal"),
            Action(label="Use camera as overworld end", kind="outlined"),
            Action(label="Build overworld end only", kind="outlined"),
            Action(
                label="Portal linkage report",
                kind="outlined",
                surface="portalLinker",
            ),
            Action(
                label="Add both as waypoints",
                kind="outlined",
                surface="waypoints",
            ),
        ),
    ),
    "railTunnel": Spec(
        key="railTunnel",
        eyebrow="Travel",
        title="Rail tunnel builder",
        width=840,
        confirm="Build tunnel",
        intro=(
            "Carves a tunnel between two points and lays a complete rail line inside "
            "it: bed, power, lighting, and walls. The route is committed as one "
            "revision so the whole line can be restored in a single step."
        ),
        sections=(
            sec(
                "Route",
                "fields",
                fields=[
                    Field(label="From x, y, z", value="66, 118, -43"),
                    Field(label="To x, y, z", value="412, 71, 188"),
                    Field(label="Length (blocks)", value="418"),
                    Field(label="Net drop", value="-47"),
                ],
            ),
            sec(
                "Path",
                "selects",
                selects=[
                    Select(
                        label="Routing",
                        options=(
                            "Straight line",
                            "Right angles (x then z)",
                            "Through waypoints",
                            "Follow terrain",
                        ),
                    ),
                    Select(
                        label="Slope handling",
                        options=(
                            "Stepped 1:1 ramps",
                            "Staircase landings",
                            "Level with bridges and cuts",
                        ),
                    ),
                    Select(
                        label="Dimension",
                        options=("minecraft:overworld", "minecraft:the_nether"),
                    ),
                ],
            ),
            sec(
                "Tunnel profile",
                "selects",
                selects=[
                    Select(
                        label="Cross-section",
                        options=(
                            "1×2 minimum",
                            "2×3 walkable",
                            "3×3 arched",
                            "3×4 station-grade",
                        ),
                    ),
                    Select(
                        label="Wall block",
                        options=(
                            "minecraft:stone_bricks",
                            "minecraft:deepslate_bricks",
                            "minecraft:blackstone",
                            "Match surrounding terrain",
                        ),
                    ),
                    Select(
                        label="Floor block",
                        options=(
                            "minecraft:polished_andesite",
                            "minecraft:stone",
                            "minecraft:smooth_stone",
                        ),
                    ),
                    Select(
                        label="Roof block",
                        options=(
                            "Same as walls",
                            "minecraft:glass",
                            "Open to sky",
                        ),
                    ),
                ],
            ),
            sec(
                "Rails and power",
                "fields",
                fields=[
                    Field(label="Powered rail interval", value="8"),
                    Field(label="Power source", value="minecraft:redstone_block"),
                    Field(label="Detector rails", value="0"),
                    Field(label="Light interval", value="10"),
                ],
            ),
            sec(
                "Rail options",
                "checks",
                checks=[
                    Check(
                        label=("Place powered rails on inclines at a tighter interval"),
                        hint="Uphill runs need more power than level track.",
                    ),
                    Check(
                        label="Recess the power blocks under the bed",
                        hint="Keeps the redstone out of the walkway.",
                    ),
                    Check(
                        label="Add a return line alongside",
                        hint=("Widens the profile and lays a second, opposite track."),
                    ),
                    Check(
                        label="Fence open drops and lava",
                        hint="Seals anything the tunnel cuts into.",
                    ),
                    Check(
                        label="Carve air pockets only",
                        hint="Never replaces existing player-built blocks.",
                    ),
                ],
            ),
            sec(
                "Wall courses (bottom to top)",
                "list",
                rows=[
                    Row(
                        name="Course 1 · plinth",
                        detail="minecraft:polished_deepslate · 1 block tall",
                        tag="edit",
                    ),
                    Row(
                        name="Course 2 · body",
                        detail="minecraft:stone_bricks · 2 blocks tall",
                        tag="edit",
                    ),
                    Row(
                        name="Course 3 · trim",
                        detail="minecraft:chiselled_stone_bricks · 1 block tall",
                        tag="edit",
                    ),
                    Row(
                        name="Course 4 · upper",
                        detail="minecraft:smooth_stone · fills to the roof",
                        tag="edit",
                    ),
                ],
            ),
            sec(
                "Wall pattern",
                "selects",
                selects=[
                    Select(
                        label="Body pattern",
                        options=(
                            "Solid",
                            "Alternating two blocks",
                            "Random weighted pattern",
                            "Vertical stripes",
                            "Brick offset",
                        ),
                    ),
                    Select(
                        label="Accent columns",
                        options=(
                            "Off",
                            "Every 4 blocks",
                            "Every 8 blocks",
                            "Every 16 blocks",
                        ),
                    ),
                    Select(
                        label="Column block",
                        options=(
                            "minecraft:stone_brick_wall",
                            "minecraft:polished_blackstone",
                            "minecraft:oak_log",
                            "minecraft:iron_bars",
                        ),
                    ),
                    Select(
                        label="Alcoves",
                        options=("Off", "Every 16 blocks", "At stations only"),
                    ),
                ],
            ),
            sec(
                "Roof",
                "selects",
                selects=[
                    Select(
                        label="Shape",
                        options=(
                            "Flat",
                            "Arched (1-block rise)",
                            "Barrel vault (2-block rise)",
                            "Gable",
                            "Glass strip down the centre",
                            "Open trench",
                        ),
                    ),
                    Select(
                        label="Roof block",
                        options=(
                            "minecraft:stone_bricks",
                            "minecraft:stone_brick_stairs",
                            "minecraft:deepslate_tiles",
                            "minecraft:glass",
                        ),
                    ),
                    Select(
                        label="Ribs",
                        options=("Off", "Every 4 blocks", "Every 8 blocks"),
                    ),
                    Select(
                        label="Rib block",
                        options=(
                            "minecraft:polished_deepslate",
                            "minecraft:dark_oak_log",
                            "minecraft:copper_block",
                        ),
                    ),
                ],
            ),
            sec(
                "Roof options",
                "checks",
                checks=[
                    Check(
                        label="Seal above the roof",
                        hint="Backfills gravel and water the tunnel cut into.",
                    ),
                    Check(
                        label="Drop hanging elements from the ribs",
                        hint="Chains, lanterns, or vines between ribs.",
                    ),
                    Check(
                        label="Skylight at stations",
                        hint=(
                            "Opens a shaft to the surface where a station has one "
                            "above it."
                        ),
                    ),
                ],
            ),
            sec(
                "Lighting fixtures",
                "list",
                rows=[
                    Row(
                        name="Wall lantern on chain",
                        detail=("minecraft:lantern · wall course 3 · every 10 blocks"),
                        tag="edit",
                    ),
                    Row(
                        name="Recessed glowstone",
                        detail=(
                            "minecraft:glowstone behind minecraft:iron_bars · every "
                            "20 blocks"
                        ),
                        tag="edit",
                    ),
                    Row(
                        name="Floor strip",
                        detail=(
                            "minecraft:sea_lantern flush with the bed · at stations"
                        ),
                        tag="edit",
                    ),
                ],
            ),
            sec(
                "Lighting layout",
                "selects",
                selects=[
                    Select(
                        label="Placement",
                        options=(
                            "Wall-mounted",
                            "Ceiling-hung",
                            "Recessed in wall",
                            "Under the rail bed",
                            "Mixed by course",
                        ),
                    ),
                    Select(
                        label="Side",
                        options=(
                            "Both walls",
                            "Left wall",
                            "Right wall",
                            "Alternating sides",
                        ),
                    ),
                    Select(
                        label="Fixture block",
                        options=(
                            "minecraft:lantern",
                            "minecraft:sea_lantern",
                            "minecraft:glowstone",
                            "minecraft:shroomlight",
                            "minecraft:redstone_lamp",
                            "minecraft:torch",
                            "minecraft:soul_lantern",
                        ),
                    ),
                    Select(
                        label="Backing",
                        options=(
                            "None",
                            "minecraft:iron_bars",
                            "minecraft:stone_brick_wall",
                            "minecraft:trapdoor",
                        ),
                    ),
                ],
            ),
            sec(
                "Lighting spacing",
                "ranges",
                ranges=[
                    RangeDef(
                        label="Fixture interval (blocks)", value=10, min=2, max=32
                    ),
                    RangeDef(label="Mount height above the bed", value=3, min=1, max=6),
                    RangeDef(
                        label="Target minimum light level", value=8, min=0, max=15
                    ),
                ],
            ),
            sec(
                "Lighting checks",
                "checks",
                checks=[
                    Check(
                        label="Verify the target light level after building",
                        hint=(
                            "Runs the light overlay across the finished route and "
                            "reports dark gaps."
                        ),
                    ),
                    Check(
                        label="Spawn-proof any remaining dark faces",
                        hint=(
                            "Adds fixtures or slabs where the target level is not "
                            "met."
                        ),
                    ),
                    Check(
                        label="Use soul fixtures in the Nether section",
                        hint="Switches fixture blocks per dimension.",
                    ),
                ],
            ),
            sec(
                "Stations",
                "list",
                rows=[
                    Row(
                        name="Start · Spawn platform",
                        detail="66, 118, -43 · minecart dispenser and button",
                        tag="station",
                    ),
                    Row(
                        name="Midpoint · Ravine crossing",
                        detail="240, 94, 72 · bridge span 34 blocks",
                        tag="bridge",
                    ),
                    Row(
                        name="End · Market row south",
                        detail="412, 71, 188 · stop rail and chest",
                        tag="station",
                    ),
                ],
            ),
            sec(
                "Material estimate",
                "list",
                rows=[
                    Row(
                        name="minecraft:rail",
                        detail="Level and curved sections",
                        tag="366",
                    ),
                    Row(
                        name="minecraft:powered_rail",
                        detail="One every 8 blocks, tighter on inclines",
                        tag="52",
                    ),
                    Row(
                        name="minecraft:redstone_block",
                        detail="One per powered rail",
                        tag="52",
                    ),
                    Row(
                        name="minecraft:stone_bricks",
                        detail="Walls and roof",
                        tag="3,142",
                    ),
                    Row(
                        name="minecraft:polished_andesite",
                        detail="Floor and bed",
                        tag="836",
                    ),
                    Row(
                        name="minecraft:lantern",
                        detail="Every 10 blocks",
                        tag="42",
                    ),
                    Row(
                        name="minecraft:oak_fence",
                        detail="Bridge railings",
                        tag="68",
                    ),
                ],
            ),
            sec(
                "Route check",
                "list",
                rows=[
                    Row(
                        name="Structures crossed",
                        detail=(
                            "Mineshaft at 296, 32, 144 · route passes 40 blocks "
                            "above"
                        ),
                        tag="clear",
                    ),
                    Row(
                        name="Player-built blocks on path",
                        detail="12 blocks in the market row wall",
                        tag="review",
                    ),
                    Row(
                        name="Chunks touched",
                        detail="38 chunks across 3 regions",
                        tag="38",
                    ),
                    Row(
                        name="World border",
                        detail="Whole route is inside the border",
                        tag="within",
                    ),
                ],
            ),
            sec(
                "Progress",
                "progress",
                hint="Carve, build, and lay track",
                progress_label="0 of 418 blocks",
                progress_fraction=0.0,
            ),
        ),
        actions=(
            Action(label="Preview route", kind="tonal"),
            Action(label="Set start from camera", kind="outlined"),
            Action(label="Pick waypoints", kind="outlined", surface="waypoints"),
            Action(
                label="Rail network audit",
                kind="outlined",
                surface="railNetwork",
            ),
            Action(
                label="Queue as batch job",
                kind="outlined",
                surface="batchQueue",
            ),
        ),
    ),
}
