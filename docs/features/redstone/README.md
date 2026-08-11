# Redstone and mechanics

Seven surfaces about the parts of a world that behave rather than sit: circuits,
rails, portals, spawning, light, and tick cost. They live on the Redstone ribbon
tab.

## Behaviour

| Surface | What it does |
| --- | --- |
| **Circuit trace** (`redstoneTrace`) | Follow a redstone signal from a source through every component it reaches, listing the path and the signal strength at each step. |
| **Rail network** (`railNetwork`) | Every connected run of rail in the selection, with its length, its powered sections, and its junctions. |
| **Portal linkage** (`portalLinker`) | Which portals link to which, and which have no partner at the coordinates the game would look at. |
| **Spawn points and beds** (`spawnPoints`) | The world spawn, every bed, and every respawn anchor. |
| **Mob spawn analysis** (`spawnAnalysis`) | Where hostile spawning is possible in the selection, and why. |
| **Light levels** (`lightOverlay`) | A light-level readout across the selection, with a threshold. |
| **Tick load** (`tickLoad`) | What in the selection costs ticks: entities, block entities, and scheduled updates. |

These are analyses rather than edits. Each produces a list you can act on — a
row reveals its position in the viewport — but none of them writes to the world
by itself.

## Configuration

Thresholds are bounded ranges with live readouts: the light level that counts as
dark, the signal strength that counts as reaching, the tick cost that counts as
heavy. Each surface's list carries the shared search field with the regex opt-in
and the `.*` builder.

## Failure modes

An analysis over an empty selection says so rather than reporting a clean
result — "no dark blocks found" over a region containing nothing is a
misleading pass.

A circuit that leaves the selection reports that it did rather than reporting a
truncated path as complete. A portal with no partner is listed as unlinked
rather than omitted.

Results are a snapshot of the world as it stands. Editing the world does not
retroactively update an open result; the surface says which revision it was
computed against.

## Security and accessibility

These surfaces read the open world and write nothing. No network access.

Every result row is keyboard reachable and named with its coordinates, and the
light and signal readouts are given as numbers as well as colour, so the
analysis does not depend on distinguishing shades.

## Verification

```powershell
py -3 -m pytest tests/test_studio_spec_registry.py -q
```

That proves the seven surfaces exist, are complete, and resolve. The analyses
themselves run against a loaded world and need a build to exercise.

Suggested articles: [analysis tools](../analysis/README.md),
[build tools](../build/README.md),
[world generation tools](../worldgen/README.md), and
[viewport](../viewport/README.md).
