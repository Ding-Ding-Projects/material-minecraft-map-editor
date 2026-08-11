# Ribbon

The workspace's command surface is a seventeen-tab ribbon: Home, Tools,
Selection, Operations, Structures, Chunks, Terrain, Build, Entities, Data,
Analyze, Redstone, Worldgen, View, Panels, Extend, Automate.

A ribbon is the right shape for this application because the command set is
genuinely large and mostly modal — what you want while sculpting terrain has
almost no overlap with what you want while auditing loot — and because a tab
label is a better index than a nested menu path.

## Behaviour

`RIBBON_TABS` (`amulet_map_editor/api/studio/ribbon_defs.py`) is pure data: each
tab holds groups, each group holds command tiles, field grids, or dropdown
columns, and each group has a small dialog-launcher corner that opens the
surface owning that group.

`RibbonBar` (`amulet_map_editor/api/studio/ribbon.py`) draws it:

- a tab strip with the **Project** button on the left, which is how the
  backstage is reached from inside a project;
- a per-tab search field that filters the active tab's tiles live, carrying the
  regex opt-in and the `.*` builder like every other search field;
- a collapse chevron, so the ribbon can be reduced to its strip when the
  viewport needs the height;
- the panel itself, which scrolls horizontally rather than dropping tiles that
  do not fit.

Every tile names exactly one target: a **surface** to open or a **command** to
run, never both and never neither. Every dropdown stores a value distinct from
its visible label — the dimension list stores `overworld` and shows
`minecraft:overworld` — so a widget never has to reverse-engineer the identifier
it must pass on.

Right-clicking anywhere on the ribbon opens the ribbon context menu, which is
searchable like every other context menu and carries **Edit appearance…**.

## Configuration

The active tab and the collapsed state persist. Appearance follows the shared
tokens, and the per-element appearance editor reaches ribbon tiles like any
other control.

Adding a tab means adding one entry to `RIBBON_TABS` built from groups and
tiles; it needs no new drawing code. Adding a tile to an existing group is one
line naming its label, glyph, hint, and target.

## Failure modes

`ribbon_defs.validate()` returns every structural problem in the definition and
is asserted to be empty by the suite: a tab with no groups, a group with no
controls or no launcher, a tile with no glyph or no hint, a tile naming both a
surface and a command or neither, a dropdown with no options, and a dropdown
defaulting to a value that is not one of its own options.

A tile pointing at a surface nobody registered, or a command nobody implemented,
is caught the same way — as a failing check with the exact tab, group, and label
in the message, rather than as a button that does nothing.

The per-tab search never silently empties the tab: a query matching nothing says
so, and an invalid regular expression is reported rather than treated as a
pattern that matches nothing by coincidence.

## Security and accessibility

The ribbon holds no credentials and performs no network access. Every tile is
keyboard reachable with a visible focus ring, and its accessible name is the
label followed by the hint, so a screen reader reads what the tile does rather
than a two-word abbreviation.

Tile labels wrap to at most two lines and grow the tile rather than being cut in
half, which is what keeps bilingual labels legible. The strip is checked at 100,
125, 150, and 200% display scale.

## Verification

```powershell
py -3 -m pytest tests/test_studio_spec_registry.py -q
```

That file runs `ribbon_defs.validate()`, resolves every tile's surface against
the surface index and every tile's command against the command registry,
resolves every group launcher, and checks that the shortcut drawn beside a
command is the one actually installed.

Suggested articles: [project shell](../project-shell/README.md),
[searchable menus and dropdowns](../searchable-menus/README.md),
[spec renderer](../spec-renderer/README.md), and
[viewport](../viewport/README.md).
