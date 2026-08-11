"""Surface descriptions for the analysis, integrity, automation and worldgen families.

These windows report on a world rather than reshape it, so almost every one of
them is a read-out: histograms, chunk reads, diffs, ore counts, structure
positions.  Keeping them as data means the renderer decides how a list or a
progress row looks once, and a surface here only has to say what it is showing
and which other surface a footer button hands the reader on to.

Nothing in this module claims a value it has not been given.  A chunk that fails
to read is reported as an error rather than replaced, a predicted structure is
labelled predicted until its chunk generates, and a conversion says what it will
discard before it runs.

The version-dependent content -- which structures a world can hold, and what a
dimension's build range is -- comes from
:mod:`amulet_map_editor.api.studio.minecraft`, which reads the installed
libraries rather than carrying a version list of its own.  A feature the
install does not know about leaves no chip behind, and every surface that shows
any of it also shows the one sentence saying what this install can actually
read, so a short list is never mistaken for old Minecraft.
"""

from __future__ import annotations

from typing import Dict, List

from amulet_map_editor.api.studio import minecraft
from amulet_map_editor.api.studio.spec import (
    Action,
    Check,
    Field,
    Row,
    Select,
    Spec,
    sec,
)


def _structure_chips() -> List[str]:
    """Return every structure type this install can hold, oldest era first.

    Structures are not blocks, so the installed data cannot be asked about them
    directly; each modern one is gated on the block family that shipped with
    it, which is a question the block data does answer.  A structure that
    predates every gate is always listed, because no install that can read a
    world at all is without it.
    """
    chips = [
        "Village",
        "Stronghold",
        "Mineshaft",
        "Desert pyramid",
        "Jungle temple",
        "Witch hut",
        "Igloo",
        "Ocean monument",
        "Woodland mansion",
        "Pillager outpost",
        "Shipwreck",
        "Ocean ruin",
        "Buried treasure",
        "Ruined portal",
        "Nether fortress",
        "Bastion remnant",
        "Nether fossil",
        "End city",
        "End gateway",
    ]
    chips.extend(minecraft.gated("deep_dark", "Ancient city"))
    chips.extend(minecraft.gated("archaeology", "Trail ruins"))
    chips.extend(minecraft.gated("trial_chambers", "Trial chamber"))
    chips.extend(minecraft.gated("pale_garden", "Pale garden"))
    return chips


def _structure_prediction_rows() -> List[Row]:
    """Return which structure types can be predicted and which must be read.

    A structure reference stored in a generated chunk is a fact; a position
    worked out from the seed is an expectation that only becomes a fact when
    the chunk generates.  The rows say which is which per type, so a reader
    never has to infer it from whether a coordinate happens to look plausible.
    """
    rows = [
        Row(
            name="Village · Pillager outpost · Desert pyramid",
            detail="Read from chunk references, predicted from the seed elsewhere",
            tag="both",
        ),
        Row(
            name="Stronghold",
            detail="Placed by the seed before generation; predicted until read",
            tag="predicted",
        ),
        Row(
            name="Mineshaft · Nether fossil · Buried treasure",
            detail="Only recorded once the chunk generates",
            tag="read",
        ),
        Row(
            name="End city · End gateway",
            detail="Predicted only after the end is generated",
            tag="read",
        ),
    ]
    rows.extend(
        minecraft.gated(
            "deep_dark",
            Row(
                name="Ancient city",
                detail=(
                    "Predicted from the seed until the deep dark chunk "
                    f"generates · {minecraft.feature_note('deep_dark')}"
                ),
                tag="predicted",
            ),
        )
    )
    rows.extend(
        minecraft.gated(
            "archaeology",
            Row(
                name="Trail ruins",
                detail=(
                    "Predicted from the seed until the chunk generates · "
                    f"{minecraft.feature_note('archaeology')}"
                ),
                tag="predicted",
            ),
        )
    )
    rows.extend(
        minecraft.gated(
            "trial_chambers",
            Row(
                name="Trial chamber",
                detail=(
                    "Predicted from the seed until the chunk generates · "
                    f"{minecraft.feature_note('trial_chambers')}"
                ),
                tag="predicted",
            ),
        )
    )
    rows.extend(
        minecraft.gated(
            "pale_garden",
            Row(
                name="Pale garden",
                detail=(
                    "A biome rather than a structure reference, so it is always "
                    f"a prediction · {minecraft.feature_note('pale_garden')}"
                ),
                tag="predicted",
            ),
        )
    )
    return rows


def _height_rows() -> List[Row]:
    """Return the build range of every dimension on every installed platform.

    Each range is read through :func:`minecraft.height_range` at that
    platform's newest installed version, and each row carries the note saying
    where the numbers came from, so a range is never a constant somebody typed.
    """
    rows: List[Row] = []
    for platform in minecraft.editable_platforms():
        version = minecraft.latest(platform)
        for dimension, bounds in minecraft.height_ranges(platform, version):
            rows.append(
                Row(
                    name=f"{platform} · {dimension}",
                    detail=minecraft.height_range_note(platform, version, dimension),
                    tag=minecraft.range_text(bounds),
                )
            )
    if not rows:
        rows.append(
            Row(
                name="No build range could be read",
                detail=minecraft.support_report(),
                tag="unavailable",
            )
        )
    return rows


def _conversion_rows() -> List[Row]:
    """Return the oldest and newest target of each platform, with its range.

    A conversion drops whatever falls outside the target's overworld, so the
    two ends of the installed range are the two rows that actually matter when
    deciding whether a build survives one.
    """
    rows: List[Row] = []
    for platform in minecraft.editable_platforms():
        for version in (minecraft.oldest(platform), minecraft.latest(platform)):
            if not version:
                continue
            bounds = minecraft.height_range(platform, version, minecraft.OVERWORLD)
            rows.append(
                Row(
                    name=f"{platform} {minecraft.version_text(version)}",
                    detail=(
                        "Blocks outside this overworld range are reported before "
                        "a conversion runs, never dropped silently"
                    ),
                    tag=minecraft.range_text(bounds),
                )
            )
    if not rows:
        rows.append(
            Row(
                name="No conversion target could be read",
                detail=minecraft.support_report(),
                tag="unavailable",
            )
        )
    return rows


#: The example operation shown in the operation console, transcribed verbatim so
#: the reader sees a script that would genuinely run against the selection.
_OPERATION_EXAMPLE = """def operation(world, dimension, selection, options):
    target = options["block"]
    for box in selection.selection_boxes:
        for x, y, z in box.blocks:
            world.set_version_block(x, y, z, dimension, target)
    return "Filled %d blocks" % selection.volume"""


SPECS: Dict[str, Spec] = {
    "blockHistogram": Spec(
        key="blockHistogram",
        eyebrow="Analysis",
        title="Block histogram",
        width=720,
        confirm="Close",
        sections=(
            sec(
                "Selection",
                "list",
                rows=[
                    Row(
                        name="Total blocks",
                        detail="16 × 2 × 18 = 576",
                        tag="100%",
                    ),
                    Row(name="minecraft:stone", detail="212 blocks", tag="36.8%"),
                    Row(name="minecraft:dirt", detail="148 blocks", tag="25.7%"),
                    Row(name="minecraft:grass_block", detail="96 blocks", tag="16.7%"),
                    Row(name="minecraft:water", detail="72 blocks", tag="12.5%"),
                    Row(name="minecraft:air", detail="48 blocks", tag="8.3%"),
                ],
            ),
            sec(
                "Distribution",
                "progress",
                hint="Non-air fill",
                progress_label="91.7%",
                progress_fraction=0.917,
            ),
        ),
        actions=(
            Action(label="Export CSV", kind="outlined"),
            Action(label="Select a block type", kind="tonal"),
        ),
    ),
    "chunkInspector": Spec(
        key="chunkInspector",
        eyebrow="Analysis",
        title="Chunk inspector",
        width=780,
        confirm="Close",
        sections=(
            sec("", "search", hint="Search by chunk coordinate or status"),
            sec(
                "Chunks",
                "list",
                rows=[
                    Row(
                        name="r.0.-1 · chunk 4, -13",
                        detail=(
                            "full · 48 KiB · saved 10 Aug 2026 09:41 · 26 block entities"
                        ),
                        tag="ok",
                    ),
                    Row(
                        name="r.0.-1 · chunk 5, -13",
                        detail="full · 44 KiB · 12 entities",
                        tag="ok",
                    ),
                    Row(
                        name="r.0.-1 · chunk 6, -13",
                        detail="empty · never generated",
                        tag="missing",
                    ),
                    Row(
                        name="r.0.-1 · chunk 7, -13",
                        detail="read error · malformed compression header",
                        tag="error",
                    ),
                ],
            ),
            sec(
                "",
                "note",
                hint=(
                    "A chunk that fails to read is never silently replaced. Use "
                    "Validate and repair to decide what happens to it."
                ),
            ),
        ),
        actions=(
            Action(label="Frame chunk", kind="tonal"),
            Action(
                label="Validate and repair",
                kind="outlined",
                surface="validateRepair",
            ),
        ),
    ),
    "biomeMap": Spec(
        key="biomeMap",
        eyebrow="Analysis",
        title="Biome map",
        width=720,
        confirm="Close",
        sections=(
            sec(
                "Distribution",
                "list",
                rows=[
                    Row(name="minecraft:plains", detail="412 columns", tag="44%"),
                    Row(name="minecraft:dark_forest", detail="286 columns", tag="31%"),
                    Row(name="minecraft:river", detail="142 columns", tag="15%"),
                    Row(name="minecraft:warm_ocean", detail="92 columns", tag="10%"),
                ],
            ),
            sec(
                "View",
                "selects",
                selects=[
                    Select(
                        label="Resolution",
                        options=("Per column", "Per 4×4", "Per chunk"),
                    ),
                    Select(
                        label="Overlay",
                        options=("Off", "Viewport overlay", "Minimap only"),
                    ),
                ],
            ),
        ),
        actions=(
            Action(
                label="Set biome in selection",
                kind="tonal",
                surface="biomeSelect",
            ),
            Action(label="Export map", kind="outlined"),
        ),
    ),
    "relight": Spec(
        key="relight",
        eyebrow="Integrity",
        title="Relight",
        width=600,
        confirm="Relight selection",
        intro=(
            "Recomputes block and sky light for the selected chunks. Long runs "
            "report bounded progress and can be cancelled."
        ),
        sections=(
            sec(
                "Scope",
                "selects",
                selects=[
                    Select(
                        label="Light type",
                        options=("Block and sky", "Block only", "Sky only"),
                    ),
                    Select(
                        label="Area",
                        options=("Selection", "Loaded chunks", "Whole dimension"),
                    ),
                ],
            ),
            sec(
                "Progress",
                "progress",
                hint="Relighting chunks",
                progress_label="0%",
                progress_fraction=0.0,
            ),
        ),
        actions=(Action(label="Cancel job", kind="danger"),),
    ),
    "worldDiff": Spec(
        key="worldDiff",
        eyebrow="Integrity",
        title="Compare worlds",
        width=780,
        confirm="Close",
        intro=(
            "Compares two worlds chunk by chunk and reports only what actually "
            "differs. Nothing is written by a comparison."
        ),
        sections=(
            sec(
                "Worlds",
                "list",
                rows=[
                    Row(
                        name="Left",
                        detail="1.17 Height · bedrock 1.17.0.1",
                        tag="current",
                    ),
                    Row(
                        name="Right",
                        detail="1.17 Height backup · bedrock 1.17.0.1",
                        tag="pick",
                    ),
                ],
            ),
            sec(
                "Differences",
                "list",
                rows=[
                    Row(
                        name="chunk 4, -13",
                        detail="212 blocks differ · 2 block entities added",
                        tag="changed",
                    ),
                    Row(name="chunk 5, -13", detail="identical", tag="same"),
                    Row(
                        name="chunk 6, -13",
                        detail="present on left only",
                        tag="added",
                    ),
                    Row(
                        name="chunk 9, -14",
                        detail="present on right only",
                        tag="removed",
                    ),
                ],
            ),
        ),
        actions=(
            Action(
                label="Import differing chunks",
                kind="tonal",
                surface="importChunks",
            ),
            Action(label="Export diff report", kind="outlined"),
        ),
    ),
    "validateRepair": Spec(
        key="validateRepair",
        eyebrow="Integrity",
        title="Validate and repair",
        width=760,
        confirm="Repair selected",
        intro=(
            "Every finding names the exact file and offset. Repairs are opt-in "
            "per finding and commit one revision each."
        ),
        sections=(
            sec(
                "Findings",
                "list",
                rows=[
                    Row(
                        name="Malformed compression header",
                        detail="r.0.-1.mca offset 0x1A400 · chunk 7, -13",
                        tag="repairable",
                    ),
                    Row(
                        name="Orphaned block entity",
                        detail="chunk 4, -13 · chest with no block",
                        tag="repairable",
                    ),
                    Row(
                        name="Height map out of range",
                        detail="chunk 5, -13 · values above build limit",
                        tag="repairable",
                    ),
                    Row(
                        name="Unknown block state",
                        detail="3 blocks · see block state audit",
                        tag="review",
                    ),
                ],
            ),
            sec(
                "Repair policy",
                "checks",
                checks=[
                    Check(
                        label="Commit a revision before each repair",
                        hint="Leaves every repair individually undoable.",
                    ),
                    Check(
                        label="Skip findings that need a decision",
                        hint="Review-only findings are never auto-repaired.",
                    ),
                ],
            ),
        ),
        actions=(
            Action(label="Re-scan", kind="tonal"),
            Action(label="Export report", kind="outlined"),
            Action(
                label="Open block audit",
                kind="outlined",
                surface="blockAudit",
            ),
        ),
    ),
    "measure": Spec(
        key="measure",
        eyebrow="Measure",
        title="Measure",
        width=560,
        confirm="Close",
        sections=(
            sec(
                "Readouts",
                "list",
                rows=[
                    Row(
                        name="Point to point",
                        detail="15, 1, 17",
                        tag="22.7 blocks",
                    ),
                    Row(
                        name="Bounding volume",
                        detail="16 × 2 × 18",
                        tag="576 blocks",
                    ),
                    Row(name="Footprint", detail="16 × 18", tag="288 blocks"),
                    Row(
                        name="Chunks touched",
                        detail="2 × 2 grid",
                        tag="4 chunks",
                    ),
                ],
            ),
            sec(
                "Units",
                "selects",
                selects=[
                    Select(
                        label="Distance",
                        options=("Blocks", "Chunks", "Regions"),
                    ),
                    Select(
                        label="Anchor",
                        options=(
                            "Box corners",
                            "Box centres",
                            "Camera to cursor",
                        ),
                    ),
                ],
            ),
        ),
        actions=(Action(label="Copy readout", kind="outlined"),),
    ),
    "layerSlice": Spec(
        key="layerSlice",
        eyebrow="Measure",
        title="Layer slice",
        width=560,
        confirm="Apply slice",
        intro=(
            "Isolates a Y range in the viewport so caves, dimensions, and "
            "interiors are readable. The slice affects rendering only."
        ),
        sections=(
            sec(
                "Range",
                "fields",
                fields=[
                    Field(label="Min Y", value="-64"),
                    Field(label="Max Y", value="320"),
                ],
            ),
            sec(
                "Quick ranges",
                "chips",
                chips=[
                    "Whole world",
                    "Surface 60–140",
                    "Caves -64–48",
                    "Nether 0–128",
                    "Active box only",
                ],
            ),
            sec(
                "Options",
                "checks",
                checks=[
                    Check(
                        label="Fade blocks above the slice",
                        hint="Keeps context without hiding it entirely.",
                    ),
                    Check(
                        label="Clip the selection wireframe too",
                        hint="Otherwise the wireframe always draws in full.",
                    ),
                ],
            ),
        ),
        actions=(Action(label="Reset slice", kind="outlined"),),
    ),
    "scriptConsole": Spec(
        key="scriptConsole",
        eyebrow="Automation",
        title="Operation console",
        width=760,
        confirm="Run script",
        intro=(
            "The operation framework loads project-specific Python extensions. "
            "Scripts run against the selection and commit one revision per run."
        ),
        sections=(
            sec("Script", "code", code=_OPERATION_EXAMPLE),
            sec(
                "Loaded operations",
                "list",
                rows=[
                    Row(
                        name="fill_selection.py",
                        detail="operations/ · registered as Fill selection",
                        tag="loaded",
                    ),
                    Row(
                        name="swap_palette.py",
                        detail="operations/ · registered as Swap palette",
                        tag="loaded",
                    ),
                    Row(
                        name="broken_plugin.py",
                        detail="operations/ · import error on line 12",
                        tag="failed",
                    ),
                ],
            ),
            sec(
                "",
                "note",
                hint=(
                    "A plugin that fails to import reports the exact error and "
                    "is not registered. Other plugins keep working."
                ),
            ),
        ),
        actions=(
            Action(label="Reload plugins", kind="tonal"),
            Action(label="Open operations folder", kind="outlined"),
            Action(label="Open in VS Code", kind="outlined"),
        ),
    ),
    "batchQueue": Spec(
        key="batchQueue",
        eyebrow="Automation",
        title="Batch queue",
        width=760,
        confirm="Run queue",
        intro=(
            "Queue several operations across worlds and run them in one pass. "
            "Each job commits its own revision and reports its own result."
        ),
        sections=(
            sec(
                "Queue",
                "list",
                rows=[
                    Row(
                        name="1 · Replace stone → deepslate",
                        detail="1.17 Height · selection 3 boxes",
                        tag="ready",
                    ),
                    Row(
                        name="2 · Relight selection",
                        detail="1.17 Height · 12 chunks",
                        tag="ready",
                    ),
                    Row(
                        name="3 · Export spawn-arch.construction",
                        detail="1.17 Height · box 1",
                        tag="ready",
                    ),
                    Row(
                        name="4 · Convert to java 1.12.2",
                        detail="1.12.2 Amulet Output",
                        tag="blocked",
                    ),
                ],
            ),
            sec(
                "On failure",
                "selects",
                selects=[
                    Select(
                        label="Policy",
                        options=(
                            "Stop the queue",
                            "Skip and continue",
                            "Retry once then skip",
                        ),
                    ),
                    Select(
                        label="Report",
                        options=("Notification", "Markdown export", "Both"),
                    ),
                ],
            ),
            sec(
                "Progress",
                "progress",
                hint="Queue progress",
                progress_label="0 of 4",
                progress_fraction=0.0,
            ),
        ),
        actions=(
            Action(label="Add job", kind="tonal"),
            Action(label="Reorder", kind="outlined"),
            Action(label="Clear queue", kind="danger"),
        ),
    ),
    "macroRecorder": Spec(
        key="macroRecorder",
        eyebrow="Automation",
        title="Macro recorder",
        width=700,
        confirm="Save macro",
        intro=(
            "Records the operations you run so the sequence can be replayed on "
            "another selection or world."
        ),
        sections=(
            sec(
                "Recorded steps",
                "list",
                rows=[
                    Row(
                        name="1 · Set selection 16×2×18",
                        detail="relative to box origin",
                        tag="step",
                    ),
                    Row(
                        name="2 · Fill minecraft:stone",
                        detail="mask: air only",
                        tag="step",
                    ),
                    Row(
                        name="3 · Smooth · 3 iterations",
                        detail="kernel radius 2",
                        tag="step",
                    ),
                    Row(
                        name="4 · Repaint surface",
                        detail="3 height rules",
                        tag="step",
                    ),
                ],
            ),
            sec(
                "Replay",
                "selects",
                selects=[
                    Select(
                        label="Anchor",
                        options=(
                            "Selection origin",
                            "World coordinates",
                            "Camera position",
                        ),
                    ),
                    Select(
                        label="Repeat",
                        options=("Once", "Per selection box", "Per chunk"),
                    ),
                ],
            ),
        ),
        actions=(
            Action(label="Record", kind="tonal"),
            Action(label="Replay", kind="outlined"),
            Action(label="Delete macro", kind="danger"),
        ),
    ),
    "structureLocator": Spec(
        key="structureLocator",
        eyebrow="Worldgen",
        title="Locate structures",
        width=780,
        confirm="Go to structure",
        intro=(
            "Reads structure references stored in the chunks. Ungenerated "
            "structures are predicted from the seed and marked as such."
        ),
        sections=(
            sec("", "search", hint="Search structure types and coordinates"),
            sec("Type", "chips", chips=_structure_chips()),
            sec(
                "Found",
                "list",
                rows=[
                    Row(
                        name="minecraft:village",
                        detail="384, 68, 208 · plains · generated",
                        tag="42 m",
                    ),
                    Row(
                        name="minecraft:mineshaft",
                        detail="296, 32, 144 · generated",
                        tag="180 m",
                    ),
                    Row(
                        name="minecraft:stronghold",
                        detail="1412, 32, -880 · predicted from seed",
                        tag="predicted",
                    ),
                    Row(
                        name="minecraft:ancient_city",
                        detail="-624, -51, 992 · predicted from seed",
                        tag="predicted",
                    ),
                ],
            ),
            sec("Prediction support", "list", rows=_structure_prediction_rows()),
            sec(
                "",
                "note",
                hint=(
                    "A predicted position comes from the generation algorithm "
                    "for this seed. It is confirmed only once the chunk "
                    "generates."
                ),
            ),
            sec("", "note", hint=minecraft.support_report()),
        ),
        actions=(
            Action(label="Add as waypoint", kind="tonal", surface="waypoints"),
            Action(label="Export list", kind="outlined"),
        ),
    ),
    "slimeChunks": Spec(
        key="slimeChunks",
        eyebrow="Worldgen",
        title="Slime chunks",
        width=660,
        confirm="Apply overlay",
        sections=(
            sec(
                "Seed",
                "fields",
                fields=[
                    Field(label="World seed", value="1471929"),
                    Field(label="Chunk radius", value="16"),
                ],
            ),
            sec(
                "Nearest slime chunks",
                "list",
                rows=[
                    Row(
                        name="chunk 5, -13",
                        detail="80, 40, -208 · inside the current selection",
                        tag="here",
                    ),
                    Row(name="chunk 9, -11", detail="144, 40, -176", tag="68 m"),
                    Row(name="chunk -2, -14", detail="-32, 40, -224", tag="112 m"),
                ],
            ),
            sec(
                "Overlay",
                "checks",
                checks=[
                    Check(
                        label="Show slime chunk grid in the viewport",
                        hint="Draws a tint over qualifying chunks.",
                    ),
                    Check(
                        label="Show on the minimap",
                        hint="Marks chunks in the minimap panel.",
                    ),
                ],
            ),
        ),
        actions=(Action(label="Frame nearest", kind="tonal"),),
    ),
    "seedTools": Spec(
        key="seedTools",
        eyebrow="Worldgen",
        title="Seed tools",
        width=700,
        confirm="Save seed",
        intro=(
            "Changing the seed affects only chunks generated after the change. "
            "Existing chunks keep their terrain and will not match the new seed "
            "at their borders."
        ),
        sections=(
            sec(
                "Seed",
                "fields",
                fields=[
                    Field(label="Current seed", value="1471929"),
                    Field(label="New seed", value=""),
                    Field(label="Generator", value="default"),
                    Field(label="Dimension", value="overworld"),
                ],
            ),
            sec(
                "Derived",
                "list",
                rows=[
                    Row(
                        name="Slime chunk grid",
                        detail="Recomputed from the seed",
                        tag="derived",
                    ),
                    Row(
                        name="Structure positions",
                        detail="Predicted positions change with the seed",
                        tag="derived",
                    ),
                    Row(
                        name="Biome layout",
                        detail="Only ungenerated chunks are affected",
                        tag="partial",
                    ),
                ],
            ),
            sec(
                "",
                "note",
                hint=(
                    "Amulet warns about the border mismatch rather than hiding "
                    "it. Regenerate the boundary chunks if you want a clean "
                    "seam."
                ),
            ),
        ),
        actions=(
            Action(label="Copy seed", kind="outlined"),
            Action(label="Randomize", kind="outlined"),
            Action(
                label="Regenerate boundary",
                kind="tonal",
                surface="regenerate",
            ),
        ),
    ),
    "oreAudit": Spec(
        key="oreAudit",
        eyebrow="Worldgen",
        title="Ore distribution",
        width=740,
        confirm="Close",
        sections=(
            sec(
                "Per Y layer",
                "list",
                rows=[
                    Row(
                        name="minecraft:diamond_ore",
                        detail="peak at y -59 · 42 blocks in selection",
                        tag="42",
                    ),
                    Row(
                        name="minecraft:iron_ore",
                        detail="peak at y 16 · 312 blocks",
                        tag="312",
                    ),
                    Row(
                        name="minecraft:copper_ore",
                        detail="peak at y 48 · 186 blocks",
                        tag="186",
                    ),
                    Row(
                        name="minecraft:ancient_debris",
                        detail="nether only · 8 blocks",
                        tag="8",
                    ),
                    Row(
                        name="minecraft:redstone_ore",
                        detail="peak at y -58 · 96 blocks",
                        tag="96",
                    ),
                ],
            ),
            sec(
                "Range",
                "fields",
                fields=[
                    Field(label="Min Y", value="-64"),
                    Field(label="Max Y", value="128"),
                ],
            ),
            sec(
                "Overlay",
                "checks",
                checks=[
                    Check(
                        label="X-ray the selected ore in the viewport",
                        hint="Hides non-ore blocks for the chosen type.",
                    ),
                ],
            ),
        ),
        actions=(
            Action(label="Export CSV", kind="outlined"),
            Action(
                label="Histogram",
                kind="outlined",
                surface="blockHistogram",
            ),
        ),
    ),
    "caveMap": Spec(
        key="caveMap",
        eyebrow="Worldgen",
        title="Cave coverage",
        width=700,
        confirm="Apply overlay",
        sections=(
            sec(
                "Coverage",
                "list",
                rows=[
                    Row(
                        name="Open cave volume",
                        detail="18,240 blocks below y 40",
                        tag="12%",
                    ),
                    Row(
                        name="Ravines",
                        detail="2 intersecting the selection",
                        tag="2",
                    ),
                    Row(
                        name="Deep dark",
                        detail="1 sculk patch at -624, -51, 992",
                        tag="1",
                    ),
                    Row(
                        name="Flooded sections",
                        detail="3,120 water blocks in cave volume",
                        tag="17%",
                    ),
                ],
            ),
            sec(
                "Slice",
                "fields",
                fields=[
                    Field(label="Min Y", value="-64"),
                    Field(label="Max Y", value="40"),
                ],
            ),
            sec(
                "Actions",
                "checks",
                checks=[
                    Check(
                        label="Show cave outline in the viewport",
                        hint="Draws the air volume as a wireframe shell.",
                    ),
                    Check(
                        label="Fill caves in the selection",
                        hint="Requires a fill block; commits one revision.",
                    ),
                ],
            ),
        ),
        actions=(
            Action(label="Layer slice", kind="outlined", surface="layerSlice"),
            Action(label="Fill caves", kind="tonal"),
        ),
    ),
    "worldBorder": Spec(
        key="worldBorder",
        eyebrow="Boundaries",
        title="World border",
        width=660,
        confirm="Save border",
        sections=(
            sec(
                "Border",
                "fields",
                fields=[
                    Field(label="Centre x", value="0"),
                    Field(label="Centre z", value="0"),
                    Field(label="Diameter", value="59999968"),
                    Field(label="Warning distance", value="5"),
                ],
            ),
            sec(
                "Damage",
                "fields",
                fields=[
                    Field(label="Damage per block", value="0.2"),
                    Field(label="Damage buffer", value="5"),
                ],
            ),
            sec(
                "Options",
                "checks",
                checks=[
                    Check(
                        label="Draw the border in the viewport",
                        hint="Shows the wall and the warning band.",
                    ),
                    Check(
                        label="Clamp edits to the border",
                        hint="Refuses operations that would write outside it.",
                    ),
                ],
            ),
        ),
        actions=(
            Action(label="Fit border to selection", kind="tonal"),
            Action(label="Reset to default", kind="outlined"),
        ),
    ),
    "heightLimits": Spec(
        key="heightLimits",
        eyebrow="Boundaries",
        title="Height limits",
        width=700,
        confirm="Close",
        intro=(
            "Build range varies by platform and dimension. Operations clamp to "
            "the range of the world actually being edited. The ranges below are "
            "the installed platform ranges; open a world and its own dimension "
            "types replace them, because a data pack may set any range it likes."
        ),
        sections=(
            sec("Installed platform ranges", "list", rows=_height_rows()),
            sec("Conversion targets", "list", rows=_conversion_rows()),
            sec(
                "",
                "note",
                hint=(
                    "Amulet reports what a conversion will discard before it "
                    "runs, rather than truncating silently. The upper bound is "
                    "exclusive, so an overworld of -64 to 320 has its highest "
                    "placeable block at 319."
                ),
            ),
            sec("", "note", hint=minecraft.support_report()),
        ),
        actions=(Action(label="Check selection against target", kind="tonal"),),
    ),
    "forceLoaded": Spec(
        key="forceLoaded",
        eyebrow="Boundaries",
        title="Force-loaded chunks",
        width=700,
        confirm="Save",
        sections=(
            sec(
                "Force loaded",
                "list",
                rows=[
                    Row(
                        name="chunk 26, 12",
                        detail="Ticket: forced · added by command",
                        tag="remove",
                    ),
                    Row(name="chunk 27, 12", detail="Ticket: forced", tag="remove"),
                    Row(
                        name="chunk 0, 0",
                        detail="Spawn chunks · always ticking",
                        tag="spawn",
                    ),
                ],
            ),
            sec(
                "Summary",
                "list",
                rows=[
                    Row(
                        name="Forced chunks",
                        detail="2 in this dimension",
                        tag="2",
                    ),
                    Row(
                        name="Spawn chunk radius",
                        detail="Derived from world spawn and platform",
                        tag="16",
                    ),
                ],
            ),
        ),
        actions=(
            Action(label="Force load selection", kind="tonal"),
            Action(label="Clear all tickets", kind="danger"),
        ),
    ),
}
