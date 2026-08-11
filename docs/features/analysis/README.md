# Analysis tools

Eight surfaces that answer questions about a world rather than changing it —
except the two that repair, which say so plainly. They live on the Analyze
ribbon tab.

## Behaviour

| Surface | What it does |
| --- | --- |
| **Block histogram** (`blockHistogram`) | Every distinct block state in the selection with its count and share. |
| **Chunk inspector** (`chunkInspector`) | One chunk's sections, height maps, block entities, and status. |
| **Biome map** (`biomeMap`) | The biomes present in the selection, with their coverage. |
| **Relight** (`relight`) | Recompute lighting across the selection. |
| **Compare worlds** (`worldDiff`) | What differs between two worlds, by chunk. |
| **Validate and repair** (`validateRepair`) | Structural problems in the world data, and the repairs available for each. |
| **Measure** (`measure`) | Distance, area, and volume between two points, in blocks and in chunks. |
| **Layer slice** (`layerSlice`) | One Y layer at a time, as a readable grid. |

Every result list carries the shared search field with its regex opt-in and `.*`
builder, and every row reveals its position in the viewport.

Results are exportable. The formats offered are the ones that can carry the
shape of the data without dropping a column — a histogram exports as CSV or
TSV as readily as JSON, and the export says which encoding and which line
endings it used.

## Configuration

Selection bounds come from the navigator; nothing here asks the user to retype a
region they have already selected. Thresholds and layer indices are bounded
controls with live readouts.

## Failure modes

**Relight and Validate and repair change the world.** Both preview exactly what
they will alter, and the repair path passes the two-key gate before applying
anything irreversible. Both are recorded as commits in the project repository,
so they can be restored.

An analysis over an empty selection says so. A chunk the format layer cannot
read is listed with the reason rather than skipped, because a missing chunk in
a comparison reads as "identical".

**Compare worlds** names both revisions it compared, so a result read later is
not mistaken for a comparison of the current state.

## Security and accessibility

Both worlds in a comparison are opened read-only unless a repair is explicitly
authorised. Nothing is transmitted; exports go to a local path chosen through a
path field with a native browse button.

Result tables are keyboard navigable, every row is named with its coordinates
and its value, counts and shares are given as numbers rather than only as bar
length, and the tables reflow at narrow widths rather than clipping a column.

## Verification

```powershell
py -3 -m pytest tests/test_studio_spec_registry.py tests/test_export_actions.py -q
```

The first proves the eight surfaces are complete and reachable; the second
covers the shared export behaviour these results are written out through.

Suggested articles: [world generation tools](../worldgen/README.md),
[redstone and mechanics](../redstone/README.md),
[exports](../exports/README.md), and
[entities and world data](../entities-and-data/README.md).
