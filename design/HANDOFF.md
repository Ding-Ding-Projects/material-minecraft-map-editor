# Handoff — Amulet Studio design rewrite

Date: 2026-08-10

## What this is

A full UI rewrite of the Amulet map editor as a **project workspace**: a backstage start
screen for creating and opening projects, and a command-ribbon workspace for editing them.
It replaces the earlier single start card plus tool-strip shell.

Two design files are in the project:

| File | Purpose |
| --- | --- |
| `Amulet Studio.dc.html` | The rewrite. This is the live deliverable. |
| `Amulet Material 3.dc.html` | Pixel recreation of the existing wxPython Material 3 shell, kept as the before-state reference. |
| `image-slot.js` | Drop-target component used by every texture preview. |
| `ref/` | Screenshots copied from the source repository, used for the recreation. |

Both files are Design Components: single streaming `.dc.html` files, inline styles only,
no build step. Open either directly in a browser.

## Sources this was built from

- `material-minecraft-map-editor` — the Amulet fork. Colour roles, spacing, density, control
  sizing, and every UI string were lifted from `amulet_map_editor/api/wx/material3.py`,
  `api/wx/components.py`, `api/framework/amulet_ui.py`, `api/framework/pages/main_menu.py`,
  `api/wx/ui/*`, `programs/edit/*`, `programs/convert/convert.py`, and `lang/en.lang`.
- `agent-global-memory` — the Memory Console surfaces, copy, and feature contracts, from
  `apps/agent-global-memory/src/*`, `README.md`, `CHANGELOG.md`, `STATUS.md`, and all 43
  articles under `docs/features/`.
- `mcedit2-master` — the tool, panel, view, and picker inventory, from `src/mcedit2/editortools/`,
  `editorcommands/`, `panels/`, `widgets/`, `worldview/`, `rendering/layers.py`, `dialogs/`,
  `plugins/`, `synth/`, and `util/`.

Nothing on screen is invented from memory of what these products look like; every label,
colour, and range traces to a file in one of those three trees.

## Design system

Material 3 roles, carried from the Amulet fork but reseeded for this shell.

```
light   surface #F7FAF9  container #EDF3F2  high #E1EAE8
        on-surface #171D1C  variant #3F4948  outline #6F7978  outline-variant #BFC9C7
        primary #006A63  on-primary #FFFFFF  container #A6F2E9  on-container #00504A
        error #BA1A1A
dark    surface #0E1514  container #182020  high #232C2B
        on-surface #DDE4E2  variant #BEC9C7  outline #899391  outline-variant #3F4948
        primary #82D5CC  on-primary #003733  container #00504A  on-container #A6F2E9
        error #FFB4AB
```

Type: IBM Plex Sans for interface, IBM Plex Mono for every coordinate, id, tag, and hash.
Density tokens set control height: compact 32, comfortable 36, spacious 44.
Three elevation tokens plus an edge-highlight token carry depth; theme, accent, and density
are CSS custom properties on the root, so switching them repaints without re-rendering.

Tweakable props on the root component: `theme`, `density`.

## Structure

**Backstage** (`view: "backstage"`) — Home with a template gallery and a searchable,
filterable recent table; Open; Project info; Convert; **All surfaces**; Workspace.

**Workspace** (`view: "workspace"`) — twelve ribbon tabs (Home, Selection, Operations,
Structures, Chunks, Terrain, Build, Entities, Data, Analyze, Redstone, Worldgen, View,
Panels, Extend, Automate), a breadcrumb context bar with the head revision, a navigator with
dimensions and selection boxes, the viewport with its HUD, a tabbed properties pane, and a
status bar.

**Dialogs** — one spec renderer drives most surfaces. A spec is
`{eyebrow, title, width, intro, sections[], actions[]}`; each section declares a kind:
`search`, `fields`, `selects`, `list`, `keys`, `tree`, `chips`, `checks`, `ranges`,
`swatches`, `progress`, `keygate`, `code`, `note`, `commits`, `texture`. Adding a surface
means adding one spec entry plus one line in the surface index — no new markup.

Two surfaces are hand-built because the spec renderer cannot express them: the **NBT editor**
(three panes, per-tag-type controls) and the **Memory Console** (rail, card grid, docs reader).

## Feature inventory

**All surfaces** in the backstage indexes every one of them with search; the command palette
(Ctrl+Shift+F) covers the same set.

- **Project shell** — start, open, project info, convert, workspace, about, licences.
- **Editing** — selection tool, paste tool, operations, chunk tool, import chunks, export
  selection, teleport, block/biome/version pickers, renderer loading, conversion progress.
- **NBT editor** — six data sources (block entity, entity, item stack, player, level.dat,
  chunk), a control matched to each tag type (toggles for byte booleans, steppers with valid
  ranges, sliders for bounded numerics, dropdowns for enum-like strings, axis-coloured vector
  fields, element chips for arrays, inventory slot grids, colour swatches, container
  open/add), plus live SNBT and hex views, a type switcher over all twelve NBT types,
  validation, and per-tag revision history.
- **Terrain** — sculpt brush, smooth, flatten, erosion, noise fill, sea level, regenerate,
  surface repaint.
- **Build** — shape brush, pattern and mask, stack and array, structure library, waypoints,
  **nether portal travel builder**, **rail tunnel builder** (routing, profile, four editable
  wall courses, roof shapes with ribs, and a lighting designer with fixture definitions,
  placement, spacing, and post-build light verification).
- **Entities and data** — entity browser, entity editor, filtered removal, loot audit, NBT
  search and replace, sign text, command blocks, player data, level.dat, game rules,
  scoreboard, map items, block state audit.
- **Redstone and mechanics** — circuit trace, rail network, portal linkage, spawn points,
  mob spawn analysis, light levels, tick load.
- **Worldgen** — structure locator, slime chunks, seed tools, ore distribution, cave
  coverage, world border, height limits, force-loaded chunks.
- **MCEdit2 tools** — brush, flood fill, clone, move, generate (with L-system), select block,
  select entity, edit chunk, tool settings, find and replace for blocks / commands / NBT,
  analyze, import map image.
- **Panels and views** — inspector, pending imports, players, world info, inventory editor,
  item types, configure blocks, library, render layers (all twelve), view settings, four-up
  split, cutaway, work plane, Minecraft installs, plugins, undo history, log, profiler,
  Python console, error report.
- **Analysis** — block histogram, chunk inspector, biome map, relight, world diff, validate
  and repair, measure, layer slice.
- **Automation** — operation console, batch queue, macro recorder, scheduled rules.
- **Settings** — options (appearance, language and voice, schedule, searchable settings),
  appearance presets, element appearance, key configuration, Language Select, narrator,
  school mode, external editor, tabs and groups, destructive-action gate.
- **Global** — command palette, regex builder, documentation, update status, dim-sum
  surprise, Memory Console.

## Per-project Git repository

Every project owns an isolated Git repository beside its world data, which is what makes undo
depth unlimited. One commit per applied operation, rename, or selection change. Restoring
writes a **new** revision rather than rewinding, so the state you restored from stays
undoable. Surfaced in: Project history (commit graph with Diff and Restore), Undo history
(the stack with jump-to-point), the breadcrumb context bar, the status bar, project info, and
the properties pane's History tab.

## Cross-cutting contracts

Carried from the global-memory working agreement and applied everywhere:

- **Every dropdown is searchable** with a regex toggle and a `.*` builder button. Plain text
  is the default; regex is opt-in and reports an invalid pattern instead of silently matching
  nothing.
- **Every right-click menu is searchable** with the same regex toggle and builder. Viewport,
  navigator, and ribbon each have their own menu.
- **Ctrl+Shift+F command palette** over every command, setting, and pane.
- **Regex builder** with pattern, flags, sample text, and live capture feedback.
- **Destructive actions** go through the two-key gate with a full-range slider and an
  emergency exit.
- **Texture previews**: picking a block, item, or texture shows a tile with top, side, and
  bottom faces. These are **generated placeholder swatches**, labelled as such — real
  textures come from a loaded install or resource pack, or from dropping a PNG onto the slot.

## Memory Console

Thirteen rail views: Overview, Sync, Skills, Memory, Docs, History, Changelog, Operations,
Security, Two-factor, Locks, Status Hub, Settings.

Docs is a working two-pane reader over all 43 feature articles with domain filters, search, a
regex builder, and per-article path and summary. Skills lists all eight installed skills.
Security, Two-factor, Locks, and Status Hub carry the current contracts: authenticator
pairing with a locally drawn QR (third-party QR services prohibited), confirm-before-arming,
RFC 6238 over RFC 4226 against published vectors, reported clock skew, vault-only storage
with secrets omitted from exports; per-item locks with no master credential or inheritance,
the honest speed-bump framing, and the fictional Support Tickets desk; Status Hub sessions,
the `.mjs` MIME repair, `loadState()` refresh ordering, fail-closed session keys, allowlisted
projections, and the build-status card; builder containment and the tainted-history note;
native failure propagation; the permanent unsigned-signing policy; and the private vocabulary
contracts named without reproducing private phrasing.

## Known limits

1. **The 3D viewport is a placeholder.** The renderer owns that canvas in the real app; the
   gradient, wireframe, minimap, and compass stand in for it. No terrain is rendered.
2. **Block and item textures are generated swatches**, not game textures — I cannot generate
   images. Each preview says so and offers a drop target and a "load resource pack" action.
3. **All data is representative.** Coordinates, counts, revisions, and file sizes are
   plausible fixtures, not read from a world.
4. **Prototype interactions.** Navigation, tabs, ribbon, dropdowns, right-click menus,
   search and filtering, theme, density, and the NBT controls are live. Buttons that would
   write to a world are inert.
5. **`Amulet Material 3.dc.html`** is the before-state and is not being carried forward;
   changes belong in `Amulet Studio.dc.html`.

## Extending it

- **New dialog**: add a spec to `specs` in the logic class, then one entry in `featureDefs`
  (its `group` must be in `featureGroupOrder`). It gets the surface index, the palette, and
  the ribbon launcher for free.
- **New ribbon tab**: add to `ribbonTabDefs` and a matching key in `ribbonByTab`, built from
  `group(title, [btn(...)], extras)`.
- **New dropdown**: use a `selects` section; `decorateSelects` gives it search, the regex
  toggle, the builder, and selection state automatically.
- **New right-click menu**: add a key to `ctxMenus` and an `onContextMenu` handler wired to
  `openCtx("<key>")`.
- **New texture preview**: `texSection(blockId, slotId, hint)`. Add the block's base colour
  to `blockColours` so the placeholder swatch is in the right family.
