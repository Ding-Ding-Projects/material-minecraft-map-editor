# World generation tools

Eight surfaces about the world the generator produced: where its structures are,
which chunks are special, what the seed implies, and where the world's own
limits sit. They live on the Worldgen ribbon tab.

## Behaviour

| Surface | What it does |
| --- | --- |
| **Locate structures** (`structureLocator`) | Find generated structures by type, with their coordinates and distance from a point. |
| **Slime chunks** (`slimeChunks`) | Which chunks are slime chunks for this seed. |
| **Seed tools** (`seedTools`) | The world seed, its derived values, and what depends on it. |
| **Ore distribution** (`oreAudit`) | Ore counts by type and by height band across the selection. |
| **Cave coverage** (`caveMap`) | How much of the selection is cave, by height band. |
| **World border** (`worldBorder`) | The border's centre, size, warning distance, and damage. |
| **Height limits** (`heightLimits`) | The world's minimum and maximum build height for the open version. |
| **Force-loaded chunks** (`forceLoaded`) | Which chunks are force-loaded, and where. |

Most are read-only analyses; the world border and the force-loaded set can be
edited, and both are ordinary commits in the project repository.

## Configuration

Search radius, height bands, and structure types are bounded controls with live
readouts. Every list carries the shared search field with its regex opt-in and
`.*` builder.

Slime-chunk and structure results depend on the seed and on the version's own
generation rules; each surface names the version it computed against, because
the same seed does not produce the same result across versions.

## Failure modes

A world whose seed cannot be read reports that rather than computing against a
default seed and presenting the answer as fact — a slime-chunk map for the wrong
seed is worse than none.

A structure search that finds nothing within the radius says so and names the
radius, rather than implying the structure does not exist.

Editing the world border to a value the version does not support is refused with
the supported range named.

## Security and accessibility

The seed is world data and is shown because the user asked for it; it is never
transmitted, logged to a shared location, or included in an export the user did
not request. Nothing here reaches the network.

Every result row is named with its coordinates, results are given as numbers as
well as any colour mapping, and the tables reflow at narrow widths.

## Verification

```powershell
py -3 -m pytest tests/test_studio_spec_registry.py -q
```

That proves the eight surfaces exist, are structurally complete, and resolve.
The generation arithmetic is exercised against a loaded world in a build.

Suggested articles: [analysis tools](../analysis/README.md),
[terrain tools](../terrain/README.md),
[redstone and mechanics](../redstone/README.md), and
[panels and views](../panels/README.md).
