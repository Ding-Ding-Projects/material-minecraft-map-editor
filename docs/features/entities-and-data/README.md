# Entities and world data

Thirteen surfaces over the records a world holds that are not blocks: entities,
players, signs, command blocks, scoreboards, maps, and `level.dat` itself. They
live on the Entities and Data ribbon tabs.

## Behaviour

| Surface | What it does |
| --- | --- |
| **Entity browser** (`entityBrowser`) | Every entity in range, filtered by type and by a searchable predicate. |
| **Edit entity** (`entityEdit`) | One entity's own record, with a control matched to each field. |
| **Remove entities** (`removeEntities`) | Filtered removal: choose the types and the region, review the count, then authorise. |
| **Loot audit** (`lootAudit`) | Every loot table referenced in the selection, and what refers to it. |
| **NBT search and replace** (`nbtSearch`) | Find and replace inside raw NBT across a region. |
| **Sign text** (`signSearch`) | Every sign's text, searchable and editable in place. |
| **Command blocks** (`commandFinder`) | Every command block and its command, searchable. |
| **Player data** (`playerData`) | The player records the world carries. |
| **level.dat** (`levelDat`) | World settings, spawn, weather, and version. |
| **Game rules** (`gamerules`) | Every game rule and its value. |
| **Scoreboard** (`scoreboard`) | Objectives, teams, and scores. |
| **Map items** (`mapItems`) | The map items the world holds, with their scale and centre. |
| **Block state audit** (`blockAudit`) | Every distinct block state in the selection, with counts. |

Each searchable surface uses the shared behaviour: plain text by default, regex
as an explicit opt-in, the `.*` builder anchored beside the field, and an
invalid pattern reported rather than silently matching nothing.

Anything editing a raw record hands off to the NBT editor rather than
re-implementing a second, subtly different tag editor.

## Configuration

Filters, the last search, and the column widths persist per surface. Identifiers
and coordinates render in the monospaced face, verbatim.

## Failure modes

**Filtered removal is irreversible in the game's terms and passes the two-key
gate.** The gate names the exact entity count, the types, and the region before
it will authorise anything, and an emergency exit is available throughout.

A find-and-replace across raw NBT previews the exact count it will change and
reports every record it excluded — a malformed tag, a record the format layer
cannot rewrite — rather than folding them into the total.

A record the format layer cannot read is listed with the reason rather than
omitted, because a record missing from an audit reads as data that is not there.

Every applied change is one commit in the project repository and can be
restored.

## Security and accessibility

These surfaces read and write the open world only, and nothing is transmitted.
Player records are shown as they are stored; nothing is uploaded, correlated, or
compiled across worlds.

Every list is keyboard navigable with visible focus, rows are named with their
identifier and their position, and long identifiers elide from the middle so
both ends stay readable.

## Verification

```powershell
py -3 -m pytest tests/test_studio_spec_registry.py tests/test_studio_nbt_model.py -q
```

The first proves all thirteen surfaces exist and are structurally complete; the
second covers the tag model every one of them edits through.

Suggested articles: [NBT editor](../nbt-editor/README.md),
[analysis tools](../analysis/README.md),
[panels and views](../panels/README.md), and
[destructive-action gate](../destructive-gate/README.md).
