<div align="center">

<img src="installer/amulet_logo_512.png" width="112" alt="Amulet Map Editor logo">

# Amulet Map Editor

**A free, open-source Minecraft world editor and converter for Java and Bedrock worlds.**

[![Windows build](https://github.com/Ding-Ding-Projects/material-minecraft-map-editor/actions/workflows/build-windows.yml/badge.svg?branch=main)](https://github.com/Ding-Ding-Projects/material-minecraft-map-editor/actions/workflows/build-windows.yml)
[![Unit tests](https://github.com/Ding-Ding-Projects/material-minecraft-map-editor/actions/workflows/unittests.yml/badge.svg?branch=main)](https://github.com/Ding-Ding-Projects/material-minecraft-map-editor/actions/workflows/unittests.yml)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](setup.cfg)
[![Material Design 3 migration](https://img.shields.io/badge/UI-Material%20Design%203%20migration-6750A4)](ROADMAP.md)

[Download verified Windows build 0.10.0-dev.414](https://github.com/Ding-Ding-Projects/material-minecraft-map-editor/releases/download/0.10.0-dev.414/Setup.exe)
· [All releases](https://github.com/Ding-Ding-Projects/material-minecraft-map-editor/releases)
· [Project site source](docs/site/index.html)
· [Feature documentation](docs/features/README.md)
· [Report an issue](https://github.com/Ding-Ding-Projects/material-minecraft-map-editor/issues)

</div>

**Contents:** [one-click builds](#one-click-windows-builds) ·
[the interface](#amulet-studio) ·
[capabilities](#what-amulet-can-do) ·
[screenshots](#screenshots) ·
[Windows install and updates](#install-and-update-on-windows) ·
[development](#development-and-contribution) ·
[verification](#verification-status)

Amulet opens Minecraft worlds outside the game so that you can inspect terrain,
select precise regions, move builds between worlds, run block and biome
operations, import or export structures, delete or regenerate chunks, and
convert world data. The package metadata supports Java Edition 1.12 and newer
and Bedrock Edition 1.7 and newer.

> [!CAUTION]
> Back up every world before editing it. Close the world in Minecraft and any
> other editor first. Conversion can overwrite chunks in the destination world.

## One-click Windows builds

From a fresh Windows checkout, `build.bat /s` checks for the Python launcher and, when it is absent, installs user-scoped Python 3.11 through canonical `winget` when available or the official python.org installer when `winget` is missing. It then bootstraps the declared dependencies and installs the editable package without prompts. `build-installer.bat /s` runs that bootstrap, builds `installer/Amulet.spec`, and invokes the same unsigned Squirrel.Windows packaging path used by CI. Omit `/s` for phase output and the final launch choice. Neither script signs, publishes, tags, or creates a release; both report an exact failure if the canonical bootstrap route itself is unavailable.

The one-click paths were exercised locally on Windows from this checkout: `build.bat /s` exited 0 after resolving the declared runtime dependencies, and `build-installer.bat /s` produced `Setup.exe`, `RELEASES`, and `Amulet-0.10.0-dev-local-full.nupkg` under `installer/dist/squirrel/Amulet-0.10.0-dev-local-Windows-x64`. The installer output is unsigned by design; the script prints SHA-256 digests for all three artifacts. This is local packaging evidence, not a replacement for the immutable CI release record.

## Amulet Studio

The interface is a **project workspace** built from exactly two views, which are
swapped rather than stacked.

**Backstage** is what the application opens on: a template gallery for starting
a project, a searchable and filterable table of recent projects and worlds, an
Open page listing detected Minecraft worlds beside a browse path, project info,
conversion, and an **All surfaces** index of every window, panel, and tool the
application can open.

**Workspace** is where a project is edited: a seventeen-tab ribbon (Home, Tools,
Selection, Operations, Structures, Chunks, Terrain, Build, Entities, Data,
Analyze, Redstone, Worldgen, View, Panels, Extend, Automate), a breadcrumb
context bar carrying the head revision, a navigator for dimensions and selection
boxes, the viewport with its overlays, a tabbed properties pane, and a status
bar.

This replaced the earlier single start card plus tool strip. The world notebook
that shell used still exists — it owns world loading and per-page unsaved-work
protection — and is handed to the workspace viewport once a world is open, so
the real renderer draws inside the new shell rather than beside it. A build
whose Studio package cannot be constructed falls back to that notebook rather
than opening an empty window.

<details>
<summary><strong>How the surfaces are built, and how to add one</strong></summary>

Most windows are **data**. A surface is described by a spec — an eyebrow, a
title, a width, an introduction, an ordered list of sections, and footer actions
— and one renderer turns that into real controls. There are sixteen section
kinds: `search`, `fields`, `selects`, `list`, `keys`, `tree`, `chips`, `checks`,
`ranges`, `swatches`, `progress`, `keygate`, `code`, `note`, `commits`,
`texture`.

Adding a window is one spec entry plus one line in the surface index. It then
appears in the backstage's **All surfaces** page, in the command palette, and as
a valid target for a ribbon tile or a context-menu row, with no new markup.

Two surfaces are hand-built because the renderer cannot express them: the **NBT
editor** (three panes, with a control matched to each of the twelve tag types)
and the **Memory Console** (a thirteen-view rail, a card grid, and a two-pane
documentation reader).

Read [`docs/features/spec-renderer/README.md`](docs/features/spec-renderer/README.md)
for the full contract.

</details>

<details>
<summary><strong>Cross-cutting behaviour every surface shares</strong></summary>

- **Every search field** is the same field: plain text by default, a regex
  opt-in, a `.*` builder anchored beside it, and an honest feedback line. An
  invalid pattern is reported and matches nothing rather than being silently
  ignored.
- **Every dropdown is searchable**, and every right-click menu is searchable and
  shows each item's real keyboard shortcut.
- **`Ctrl+Shift+F`** opens the command palette over every surface, command, and
  setting, reading the same registries the rest of the shell reads.
- **Every project owns an isolated Git repository** beside its world data, which
  is what makes undo depth unlimited. Restoring writes a *new* revision rather
  than rewinding, so the state you restored from stays undoable.
- **Anything irreversible passes a two-key gate** with a full-range slider and
  an always-available emergency exit.
- **Texture previews are generated placeholder swatches and say so.** A real
  texture comes from a loaded Minecraft installation, a resource pack, or a PNG
  dropped on the slot.
- **Nothing reaches the network at runtime.** Fonts fall back through a local
  candidate list; there is no sign-in, telemetry, or cloud storage.
- **Nobody ever pays.** No purchase, licence, subscription, trial, or unlock,
  and no prompt asking for one.

</details>

<details>
<summary><strong>Material Design 3 and global-interface foundations</strong></summary>

The `0.10` source line is being modernized without pretending that the migration
is already complete. The foundations currently checked into this repository
include:

- the Amulet Studio token layer — fourteen colour roles in a light and a dark
  palette, three density heights (32, 36, 44), the spacing and radius scales,
  and a local-only font fallback chain;
- the shared wxPython Material 3 role layer still serving the dialogs that
  predate the Studio, reading the same persisted appearance profile;
- persisted English, playful Hong Kong Cantonese, and bilingual language modes;
- independent English and Cantonese voice-level controls from 1 to 5, plus a
  dialog-emoji preference;
- persisted light, dark, and system themes; compact, comfortable, and spacious
  density; accent color; UI font; and 80–200% UI scaling;
- a wx-independent, versioned named appearance-preset foundation with strict
  JSON export/import plus native Appearance-tab load, save, import, export, and
  staged per-property or appearance-only global reset controls;
- a tabbed native Preferences dialog with searchable settings, a bounded Python
  `re` builder, and a `Ctrl+Shift+F` command palette;
- a shared School-mode presentation lock with a renamed label, salted unlock
  verifier, and native controls that remove inapplicable language settings;
- a persisted notification history with search, bulk dismissal, and Markdown
  export;
- a native scheduled-settings editor and versioned local rule engine for
  language, theme, density, and accent overrides, including priorities,
  weekdays, date ranges, time windows, and deterministic precedence;
- a non-blocking Windows update-status bridge restricted to the project's exact
  immutable HTTPS release route, with explicit unsigned-package warnings;
- a safe external-editor bridge that discovers Visual Studio Code installations,
  persists a validated executable, and opens exported folders as workspace
  roots;
- a bounded startup dim-sum surprise foundation that reads authoritative dish
  names from the public catalog without copying or vendoring photos; and
- a dependency-free Material 3 site shell with tabs, feature and settings
  search, an attached bounded regex builder with flags, sample text, and capture
  feedback, persisted appearance controls, responsive layouts, focus states, and
  reduced-motion support.

These are source and automated-test claims. **No runtime capture of the Amulet
Studio interface exists yet**, so nothing here is pixel evidence for it.

Relevant source and contracts:

- [`amulet_map_editor/api/studio/`](amulet_map_editor/api/studio/)
- [`docs/features/project-shell/README.md`](docs/features/project-shell/README.md)
- [`docs/features/spec-renderer/README.md`](docs/features/spec-renderer/README.md)
- [`amulet_map_editor/api/wx/material3.py`](amulet_map_editor/api/wx/material3.py)
- [`docs/features/material-shell/README.md`](docs/features/material-shell/README.md)
- [`installer/PACKAGING.md`](installer/PACKAGING.md)
- [`docs/site/README.md`](docs/site/README.md)

</details>

## Start here

- **Install:** use the verified [unsigned Windows 0.10.0-dev.414 `Setup.exe`](https://github.com/Ding-Ding-Projects/material-minecraft-map-editor/releases/download/0.10.0-dev.414/Setup.exe), [RELEASES feed](https://github.com/Ding-Ding-Projects/material-minecraft-map-editor/releases/download/0.10.0-dev.414/RELEASES), or [full Squirrel package](https://github.com/Ding-Ding-Projects/material-minecraft-map-editor/releases/download/0.10.0-dev.414/Amulet-0.10.0-dev414-full.nupkg). These immutable assets target `f95695f7cbadecd3272370a1fa694e9b601ab124`.
- **Learn the interface:** start with [project shell](docs/features/project-shell/README.md), then [backstage](docs/features/backstage/README.md) and [ribbon](docs/features/ribbon/README.md).
- **Learn the workflows:** follow the [open-world guide](amulet_map_editor/readme.md), [3D editor guide](amulet_map_editor/programs/edit/readme.md), and [conversion guide](amulet_map_editor/programs/convert/readme.md).
- **Explore the site:** open the dependency-free [Material 3 site source](docs/site/index.html), or visit the [official Amulet website](https://www.amuletmc.com/).
- **Track the modernization:** see the factual [roadmap](ROADMAP.md) and [handoff](HANDOFF.md).
- **Contribute:** read [Development and contribution](#development-and-contribution), then use [Issues](https://github.com/Ding-Ding-Projects/material-minecraft-map-editor/issues) or [Discussions](https://github.com/Ding-Ding-Projects/material-minecraft-map-editor/discussions).

## What Amulet can do

| Area | Capabilities in this source tree |
| --- | --- |
| World access | Discover Java and Bedrock worlds, open a world from another folder, keep several projects in the recent table, and switch between dimensions from the navigator. |
| 2D and 3D editing | Navigate rendered terrain, inspect blocks, change projection, and create one or more selection boxes with direct coordinate controls. |
| Selection workflow | Copy, cut, delete, paste, translate, rotate, scale, mirror, and move selected structures. Copied data can move between simultaneously open worlds. |
| Stock operations | Clone, fill, replace, set biome, and waterlog selected regions; the operation framework also supports project-specific Python extensions. |
| Terrain and build | Sculpt, smooth, flatten, erode, noise-fill, repaint, and regenerate terrain; place patterns, stacks and arrays, structures, waypoints, matched nether portals, and a fully specified rail tunnel with its own lighting designer. |
| World data | Browse and edit entities, players, signs, command blocks, game rules, scoreboards, map items and `level.dat`, with a dedicated NBT editor carrying a control matched to each of the twelve tag types. |
| Analysis | Block histograms, chunk inspection, biome maps, relighting, world comparison, validation and repair, measurement, layer slicing, redstone and rail tracing, spawn and light analysis, and worldgen tools. |
| Structure files | Import supported structures and export `.construction`, `.mcstructure`, legacy `.schematic`, and Sponge `.schem` data through format-specific handlers. |
| Chunk tools | Select chunks, delete selected chunks, or delete everything outside the selected area so Minecraft can regenerate it. |
| World conversion | Merge source-world chunks into a chosen destination world through Amulet's format translation layer. Destination chunks at matching coordinates are overwritten. |
| Editing history | Per-project Git-backed history with unlimited undo depth; restoring writes a new revision rather than rewinding. |
| Delivery | Build PyInstaller bundles and produce unsigned Squirrel.Windows `Setup.exe`, `RELEASES`, and full `.nupkg` assets. |

## Screenshots

<!-- BEGIN CAPTURES -->

### The current interface

Every image below is a real capture of the built interface at commit `caeb179a`, taken by `scripts/capture_studio_surfaces.py`. None is a mockup, a design file, or a retouched image.

**270 surfaces captured.** **3 could not be captured** — listed at the end, with why.

The capture asks each widget to draw itself rather than reading the screen, so the run needs no visible desktop and cannot photograph a window someone happened to drag over it. A surface whose controls could not draw is reported as a failure and its file deleted, because a blank capture is worse than none: it looks like evidence.

Menus, dropdowns and popovers are photographed **open, with their rows drawn**. They are opened through the application's own openers and shown where no display covers them, because a popup grabs the mouse and the keyboard and a capture run must not take those from the machine it runs on.

<details>
<summary><b>Backstage</b> — 6 surfaces</summary>

**`backstage.account`** — 1584x921, light theme, comfortable density

![Amulet Studio backstage, account tab, in the light theme.](docs/huishots/backstage-account-caeb179a-20260811.png)

**`backstage.convert`** — 1584x921, light theme, comfortable density

![Amulet Studio backstage, convert tab, in the light theme.](docs/huishots/backstage-convert-caeb179a-20260811.png)

**`backstage.features`** — 1584x921, light theme, comfortable density

![Amulet Studio backstage, features tab, in the light theme.](docs/huishots/backstage-features-caeb179a-20260811.png)

**`backstage.home`** — 1584x921, light theme, comfortable density

![Amulet Studio backstage, home tab, in the light theme.](docs/huishots/backstage-home-caeb179a-20260811.png)

**`backstage.info`** — 1584x921, light theme, comfortable density

![Amulet Studio backstage, info tab, in the light theme.](docs/huishots/backstage-info-caeb179a-20260811.png)

**`backstage.open`** — 1584x921, light theme, comfortable density

![Amulet Studio backstage, open tab, in the light theme.](docs/huishots/backstage-open-caeb179a-20260811.png)

</details>

<details>
<summary><b>Workspace</b> — 5 surfaces</summary>

**`workspace.navigator`** — 176x687, light theme, comfortable density

![The Amulet Studio workspace navigator, in the light theme.](docs/huishots/workspace-navigator-caeb179a-20260811.png)

**`workspace.properties`** — 240x687, light theme, comfortable density

![The Amulet Studio workspace properties, in the light theme.](docs/huishots/workspace-properties-caeb179a-20260811.png)

**`workspace.ribbon`** — 1584x200, light theme, comfortable density

![The Amulet Studio workspace ribbon, in the light theme.](docs/huishots/workspace-ribbon-caeb179a-20260811.png)

**`workspace.status`** — 1156x34, light theme, comfortable density

![The Amulet Studio workspace status, in the light theme.](docs/huishots/workspace-status-caeb179a-20260811.png)

**`workspace.viewport`** — 1156x653, light theme, comfortable density

![The Amulet Studio workspace viewport, in the light theme.](docs/huishots/workspace-viewport-caeb179a-20260811.png)

</details>

<details>
<summary><b>Ribbon tabs</b> — 17 surfaces</summary>

**`ribbon.analyze`** — 1584x200, light theme, comfortable density

![The Amulet Studio ribbon with the analyze tab selected and its panel open, in the light theme.](docs/huishots/ribbon-analyze-caeb179a-20260811.png)

**`ribbon.automate`** — 1584x215, light theme, comfortable density

![The Amulet Studio ribbon with the automate tab selected and its panel open, in the light theme.](docs/huishots/ribbon-automate-caeb179a-20260811.png)

**`ribbon.build`** — 1584x200, light theme, comfortable density

![The Amulet Studio ribbon with the build tab selected and its panel open, in the light theme.](docs/huishots/ribbon-build-caeb179a-20260811.png)

**`ribbon.chunks`** — 1584x215, light theme, comfortable density

![The Amulet Studio ribbon with the chunks tab selected and its panel open, in the light theme.](docs/huishots/ribbon-chunks-caeb179a-20260811.png)

**`ribbon.data`** — 1584x200, light theme, comfortable density

![The Amulet Studio ribbon with the data tab selected and its panel open, in the light theme.](docs/huishots/ribbon-data-caeb179a-20260811.png)

**`ribbon.entities`** — 1584x200, light theme, comfortable density

![The Amulet Studio ribbon with the entities tab selected and its panel open, in the light theme.](docs/huishots/ribbon-entities-caeb179a-20260811.png)

**`ribbon.extend`** — 1584x200, light theme, comfortable density

![The Amulet Studio ribbon with the extend tab selected and its panel open, in the light theme.](docs/huishots/ribbon-extend-caeb179a-20260811.png)

**`ribbon.home`** — 1584x200, light theme, comfortable density

![The Amulet Studio ribbon with the home tab selected and its panel open, in the light theme.](docs/huishots/ribbon-home-caeb179a-20260811.png)

**`ribbon.operations`** — 1584x200, light theme, comfortable density

![The Amulet Studio ribbon with the operations tab selected and its panel open, in the light theme.](docs/huishots/ribbon-operations-caeb179a-20260811.png)

**`ribbon.panels`** — 1584x200, light theme, comfortable density

![The Amulet Studio ribbon with the panels tab selected and its panel open, in the light theme.](docs/huishots/ribbon-panels-caeb179a-20260811.png)

**`ribbon.redstone`** — 1584x200, light theme, comfortable density

![The Amulet Studio ribbon with the redstone tab selected and its panel open, in the light theme.](docs/huishots/ribbon-redstone-caeb179a-20260811.png)

**`ribbon.selection`** — 1584x302, light theme, comfortable density

![The Amulet Studio ribbon with the selection tab selected and its panel open, in the light theme.](docs/huishots/ribbon-selection-caeb179a-20260811.png)

**`ribbon.structures`** — 1584x200, light theme, comfortable density

![The Amulet Studio ribbon with the structures tab selected and its panel open, in the light theme.](docs/huishots/ribbon-structures-caeb179a-20260811.png)

**`ribbon.terrain`** — 1584x244, light theme, comfortable density

![The Amulet Studio ribbon with the terrain tab selected and its panel open, in the light theme.](docs/huishots/ribbon-terrain-caeb179a-20260811.png)

**`ribbon.tools`** — 1584x200, light theme, comfortable density

![The Amulet Studio ribbon with the tools tab selected and its panel open, in the light theme.](docs/huishots/ribbon-tools-caeb179a-20260811.png)

**`ribbon.view`** — 1584x200, light theme, comfortable density

![The Amulet Studio ribbon with the view tab selected and its panel open, in the light theme.](docs/huishots/ribbon-view-caeb179a-20260811.png)

**`ribbon.worldgen`** — 1584x200, light theme, comfortable density

![The Amulet Studio ribbon with the worldgen tab selected and its panel open, in the light theme.](docs/huishots/ribbon-worldgen-caeb179a-20260811.png)

</details>

<details>
<summary><b>Context menus</b> — 9 surfaces</summary>

**`menu.boxes`** — 300x390, light theme, comfortable density

![The Selection boxes right-click menu, open, showing its search field, its counted feedback line and its 9 rows with their keyboard shortcuts, in the light theme.](docs/huishots/menu-boxes-caeb179a-20260811.png)

**`menu.navigator`** — 300x390, light theme, comfortable density

![The Navigator right-click menu, open, showing its search field, its counted feedback line and its 10 rows with their keyboard shortcuts, in the light theme.](docs/huishots/menu-navigator-caeb179a-20260811.png)

**`menu.pane`** — 300x348, light theme, comfortable density

![The Properties pane right-click menu, open, showing its search field, its counted feedback line and its 7 rows with their keyboard shortcuts, in the light theme.](docs/huishots/menu-pane-caeb179a-20260811.png)

**`menu.recent`** — 300x348, light theme, comfortable density

![The Recent project right-click menu, open, showing its search field, its counted feedback line and its 7 rows with their keyboard shortcuts, in the light theme.](docs/huishots/menu-recent-caeb179a-20260811.png)

**`menu.ribbon`** — 300x390, light theme, comfortable density

![The Ribbon right-click menu, open, showing its search field, its counted feedback line and its 9 rows with their keyboard shortcuts, in the light theme.](docs/huishots/menu-ribbon-caeb179a-20260811.png)

**`menu.statusbar`** — 300x382, light theme, comfortable density

![The Status bar right-click menu, open, showing its search field, its counted feedback line and its 8 rows with their keyboard shortcuts, in the light theme.](docs/huishots/menu-statusbar-caeb179a-20260811.png)

**`menu.tab`** — 300x348, light theme, comfortable density

![The Tab right-click menu, open, showing its search field, its counted feedback line and its 7 rows with their keyboard shortcuts, in the light theme.](docs/huishots/menu-tab-caeb179a-20260811.png)

**`menu.tabGroup`** — 300x348, light theme, comfortable density

![The Tab group right-click menu, open, showing its search field, its counted feedback line and its 7 rows with their keyboard shortcuts, in the light theme.](docs/huishots/menu-tabgroup-caeb179a-20260811.png)

**`menu.viewport`** — 300x390, light theme, comfortable density

![The Viewport right-click menu, open, showing its search field, its counted feedback line and its 19 rows with their keyboard shortcuts, in the light theme.](docs/huishots/menu-viewport-caeb179a-20260811.png)

</details>

<details>
<summary><b>Overlays</b> — 8 surfaces</summary>

**`palette.card`** — 660x620, light theme, comfortable density

![The Ctrl+Shift+F command palette in its card presentation, showing its search field, its result count and its result rows with their live controls, in the light theme.](docs/huishots/palette-card-caeb179a-20260811.png)

**`palette.full`** — 1536x936, light theme, comfortable density

![The Ctrl+Shift+F command palette in its full presentation, showing its search field, its result count and its result rows with their live controls, in the light theme.](docs/huishots/palette-full-caeb179a-20260811.png)

**`picker.moveIntoGroup`** — 300x228, light theme, comfortable density

![The Move into group picker, open, showing its search field, the existing tab groups with their colours and member counts, and the create-a-group action, in the light theme.](docs/huishots/picker-tab-groups-caeb179a-20260811.png)

**`popup.tabOverflow`** — 283x603, light theme, comfortable density

![The ribbon tab overflow list, open on a narrowed window, showing its search field and the 16 tabs the strip could not fit, in the light theme.](docs/huishots/popup-tab-overflow-caeb179a-20260811.png)

**`regexBuilder.dropdown`** — 380x341, light theme, comfortable density

![The anchored regular-expression builder opened from a search field on the Policy dropdown on the Batch queue surface, showing its guided token buttons, its pattern editor, its flags and its live match preview, in the light theme.](docs/huishots/regexbuilder-dropdown-caeb179a-20260811.png)

**`regexBuilder.menu`** — 380x341, light theme, comfortable density

![The anchored regular-expression builder opened from a search field on the Navigator right-click menu, showing its guided token buttons, its pattern editor, its flags and its live match preview, in the light theme.](docs/huishots/regexbuilder-menu-caeb179a-20260811.png)

**`regexBuilder.palette`** — 380x341, light theme, comfortable density

![The anchored regular-expression builder opened from a search field on the command palette, showing its guided token buttons, its pattern editor, its flags and its live match preview, in the light theme.](docs/huishots/regexbuilder-palette-caeb179a-20260811.png)

**`regexBuilder.panel`** — 380x341, light theme, comfortable density

![The anchored regular-expression builder opened from a search field on a Studio panel, showing its guided token buttons, its pattern editor, its flags and its live match preview, in the light theme.](docs/huishots/regexbuilder-panel-caeb179a-20260811.png)

</details>

<details>
<summary><b>Dropdowns</b> — 112 surfaces</summary>

**`dropdown.batchQueue.Policy`** — 348x187, light theme, comfortable density

![The Policy dropdown on the Batch queue surface, open, showing its search field and its 3 options with the current choice marked, in the light theme.](docs/huishots/dropdown-batchqueue-1-policy-caeb179a-20260811.png)

**`dropdown.batchQueue.Report`** — 349x187, light theme, comfortable density

![The Report dropdown on the Batch queue surface, open, showing its search field and its 3 options with the current choice marked, in the light theme.](docs/huishots/dropdown-batchqueue-2-report-caeb179a-20260811.png)

**`dropdown.blockSelect.Namespace`** — 329x155, light theme, comfortable density

![The Namespace dropdown on the Select block surface, open, showing its search field and its 2 options with the current choice marked, in the light theme.](docs/huishots/dropdown-blockselect-2-namespace-caeb179a-20260811.png)

**`dropdown.blockSelect.Platform and version`** — 328x155, light theme, comfortable density

![The Platform and version dropdown on the Select block surface, open, showing its search field and its 2 options with the current choice marked, in the light theme.](docs/huishots/dropdown-blockselect-1-platform-and-version-caeb179a-20260811.png)

**`dropdown.brushSettings.Brush mode`** — 318x340, light theme, comfortable density

![The Brush mode dropdown on the Brush surface, open, showing its search field and its 8 options with the current choice marked, in the light theme.](docs/huishots/dropdown-brushsettings-1-brush-mode-caeb179a-20260811.png)

**`dropdown.brushSettings.Fill block`** — 319x251, light theme, comfortable density

![The Fill block dropdown on the Brush surface, open, showing its search field and its 5 options with the current choice marked, in the light theme.](docs/huishots/dropdown-brushsettings-2-fill-block-caeb179a-20260811.png)

**`dropdown.brushSettings.Replace block`** — 318x219, light theme, comfortable density

![The Replace block dropdown on the Brush surface, open, showing its search field and its 4 options with the current choice marked, in the light theme.](docs/huishots/dropdown-brushsettings-3-replace-block-caeb179a-20260811.png)

**`dropdown.cloneTool.Mirror`** — 309x219, light theme, comfortable density

![The Mirror dropdown on the Clone surface, open, showing its search field and its 4 options with the current choice marked, in the light theme.](docs/huishots/dropdown-clonetool-2-mirror-caeb179a-20260811.png)

**`dropdown.cloneTool.Rotation`** — 308x251, light theme, comfortable density

![The Rotation dropdown on the Clone surface, open, showing its search field and its 5 options with the current choice marked, in the light theme.](docs/huishots/dropdown-clonetool-1-rotation-caeb179a-20260811.png)

**`dropdown.cloneTool.Scale`** — 308x219, light theme, comfortable density

![The Scale dropdown on the Clone surface, open, showing its search field and its 4 options with the current choice marked, in the light theme.](docs/huishots/dropdown-clonetool-3-scale-caeb179a-20260811.png)

**`dropdown.controls.Action set`** — 329x187, light theme, comfortable density

![The Action set dropdown on the Key Select surface, open, showing its search field and its 3 options with the current choice marked, in the light theme.](docs/huishots/dropdown-controls-2-action-set-caeb179a-20260811.png)

**`dropdown.controls.Active group`** — 328x219, light theme, comfortable density

![The Active group dropdown on the Key Select surface, open, showing its search field and its 4 options with the current choice marked, in the light theme.](docs/huishots/dropdown-controls-1-active-group-caeb179a-20260811.png)

**`dropdown.cutawayView.Axis`** — 278x187, light theme, comfortable density

![The Axis dropdown on the Cutaway surface, open, showing its search field and its 3 options with the current choice marked, in the light theme.](docs/huishots/dropdown-cutawayview-1-axis-caeb179a-20260811.png)

**`dropdown.cutawayView.Side kept`** — 279x155, light theme, comfortable density

![The Side kept dropdown on the Cutaway surface, open, showing its search field and its 2 options with the current choice marked, in the light theme.](docs/huishots/dropdown-cutawayview-2-side-kept-caeb179a-20260811.png)

**`dropdown.elementAppearance.Font family`** — 289x187, light theme, comfortable density

![The Font family dropdown on the Edit appearance surface, open, showing its search field and its 3 options with the current choice marked, in the light theme.](docs/huishots/dropdown-elementappearance-2-font-family-caeb179a-20260811.png)

**`dropdown.elementAppearance.Font weight`** — 288x187, light theme, comfortable density

![The Font weight dropdown on the Edit appearance surface, open, showing its search field and its 3 options with the current choice marked, in the light theme.](docs/huishots/dropdown-elementappearance-1-font-weight-caeb179a-20260811.png)

**`dropdown.erosion.Deposit`** — 269x187, light theme, comfortable density

![The Deposit dropdown on the Erosion surface, open, showing its search field and its 3 options with the current choice marked, in the light theme.](docs/huishots/dropdown-erosion-2-deposit-caeb179a-20260811.png)

**`dropdown.erosion.Type`** — 268x187, light theme, comfortable density

![The Type dropdown on the Erosion surface, open, showing its search field and its 3 options with the current choice marked, in the light theme.](docs/huishots/dropdown-erosion-1-type-caeb179a-20260811.png)

**`dropdown.exportStructure.Handler`** — 268x219, light theme, comfortable density

![The Handler dropdown on the Export selection surface, open, showing its search field and its 4 options with the current choice marked, in the light theme.](docs/huishots/dropdown-exportstructure-1-handler-caeb179a-20260811.png)

**`dropdown.exportStructure.Platform`** — 269x155, light theme, comfortable density

![The Platform dropdown on the Export selection surface, open, showing its search field and its 2 options with the current choice marked, in the light theme.](docs/huishots/dropdown-exportstructure-2-platform-caeb179a-20260811.png)

**`dropdown.findReplaceBlocks.Search in`** — 348x187, light theme, comfortable density

![The Search in dropdown on the Blocks surface, open, showing its search field and its 3 options with the current choice marked, in the light theme.](docs/huishots/dropdown-findreplaceblocks-1-search-in-caeb179a-20260811.png)

**`dropdown.findReplaceBlocks.State matching`** — 349x187, light theme, comfortable density

![The State matching dropdown on the Blocks surface, open, showing its search field and its 3 options with the current choice marked, in the light theme.](docs/huishots/dropdown-findreplaceblocks-2-state-matching-caeb179a-20260811.png)

**`dropdown.findReplaceCommands.Coordinates`** — 358x187, light theme, comfortable density

![The Coordinates dropdown on the Commands surface, open, showing its search field and its 3 options with the current choice marked, in the light theme.](docs/huishots/dropdown-findreplacecommands-1-coordinates-caeb179a-20260811.png)

**`dropdown.findReplaceCommands.Offset`** — 359x155, light theme, comfortable density

![The Offset dropdown on the Commands surface, open, showing its search field and its 2 options with the current choice marked, in the light theme.](docs/huishots/dropdown-findreplacecommands-2-offset-caeb179a-20260811.png)

**`dropdown.findReplaceNbt.Match`** — 359x219, light theme, comfortable density

![The Match dropdown on the NBT surface, open, showing its search field and its 4 options with the current choice marked, in the light theme.](docs/huishots/dropdown-findreplacenbt-2-match-caeb179a-20260811.png)

**`dropdown.findReplaceNbt.Tag type`** — 358x315, light theme, comfortable density

![The Tag type dropdown on the NBT surface, open, showing its search field and its 7 options with the current choice marked, in the light theme.](docs/huishots/dropdown-findreplacenbt-1-tag-type-caeb179a-20260811.png)

**`dropdown.flatten.Direction`** — 260x187, light theme, comfortable density

![The Direction dropdown on the Flatten to height surface, open, showing its search field and its 3 options with the current choice marked, in the light theme.](docs/huishots/dropdown-flatten-1-direction-caeb179a-20260811.png)

**`dropdown.flatten.Edge`** — 260x187, light theme, comfortable density

![The Edge dropdown on the Flatten to height surface, open, showing its search field and its 3 options with the current choice marked, in the light theme.](docs/huishots/dropdown-flatten-2-edge-caeb179a-20260811.png)

**`dropdown.floodFill.Direction`** — 279x187, light theme, comfortable density

![The Direction dropdown on the Flood fill surface, open, showing its search field and its 3 options with the current choice marked, in the light theme.](docs/huishots/dropdown-floodfill-4-direction-caeb179a-20260811.png)

**`dropdown.floodFill.Neighbours`** — 278x187, light theme, comfortable density

![The Neighbours dropdown on the Flood fill surface, open, showing its search field and its 3 options with the current choice marked, in the light theme.](docs/huishots/dropdown-floodfill-3-neighbours-caeb179a-20260811.png)

**`dropdown.floodFill.Replace with`** — 279x219, light theme, comfortable density

![The Replace with dropdown on the Flood fill surface, open, showing its search field and its 4 options with the current choice marked, in the light theme.](docs/huishots/dropdown-floodfill-2-replace-with-caeb179a-20260811.png)

**`dropdown.floodFill.Search block`** — 278x219, light theme, comfortable density

![The Search block dropdown on the Flood fill surface, open, showing its search field and its 4 options with the current choice marked, in the light theme.](docs/huishots/dropdown-floodfill-1-search-block-caeb179a-20260811.png)

**`dropdown.fourUpView.Bottom left`** — 298x219, light theme, comfortable density

![The Bottom left dropdown on the Four-up split surface, open, showing its search field and its 4 options with the current choice marked, in the light theme.](docs/huishots/dropdown-fourupview-3-bottom-left-caeb179a-20260811.png)

**`dropdown.fourUpView.Bottom right`** — 299x219, light theme, comfortable density

![The Bottom right dropdown on the Four-up split surface, open, showing its search field and its 4 options with the current choice marked, in the light theme.](docs/huishots/dropdown-fourupview-4-bottom-right-caeb179a-20260811.png)

**`dropdown.fourUpView.Top left`** — 298x251, light theme, comfortable density

![The Top left dropdown on the Four-up split surface, open, showing its search field and its 5 options with the current choice marked, in the light theme.](docs/huishots/dropdown-fourupview-1-top-left-caeb179a-20260811.png)

**`dropdown.fourUpView.Top right`** — 299x219, light theme, comfortable density

![The Top right dropdown on the Four-up split surface, open, showing its search field and its 4 options with the current choice marked, in the light theme.](docs/huishots/dropdown-fourupview-2-top-right-caeb179a-20260811.png)

**`dropdown.generateTool.Generator`** — 328x315, light theme, comfortable density

![The Generator dropdown on the Generate surface, open, showing its search field and its 7 options with the current choice marked, in the light theme.](docs/huishots/dropdown-generatetool-1-generator-caeb179a-20260811.png)

**`dropdown.generateTool.Leaf block`** — 329x187, light theme, comfortable density

![The Leaf block dropdown on the Generate surface, open, showing its search field and its 3 options with the current choice marked, in the light theme.](docs/huishots/dropdown-generatetool-4-leaf-block-caeb179a-20260811.png)

**`dropdown.generateTool.Output`** — 329x155, light theme, comfortable density

![The Output dropdown on the Generate surface, open, showing its search field and its 2 options with the current choice marked, in the light theme.](docs/huishots/dropdown-generatetool-2-output-caeb179a-20260811.png)

**`dropdown.generateTool.Trunk block`** — 328x187, light theme, comfortable density

![The Trunk block dropdown on the Generate surface, open, showing its search field and its 3 options with the current choice marked, in the light theme.](docs/huishots/dropdown-generatetool-3-trunk-block-caeb179a-20260811.png)

**`dropdown.importMap.Dithering`** — 318x187, light theme, comfortable density

![The Dithering dropdown on the Import map image surface, open, showing its search field and its 3 options with the current choice marked, in the light theme.](docs/huishots/dropdown-importmap-2-dithering-caeb179a-20260811.png)

**`dropdown.importMap.Import as`** — 319x187, light theme, comfortable density

![The Import as dropdown on the Import map image surface, open, showing its search field and its 3 options with the current choice marked, in the light theme.](docs/huishots/dropdown-importmap-1-import-as-caeb179a-20260811.png)

**`dropdown.importMap.Palette`** — 319x219, light theme, comfortable density

![The Palette dropdown on the Import map image surface, open, showing its search field and its 4 options with the current choice marked, in the light theme.](docs/huishots/dropdown-importmap-3-palette-caeb179a-20260811.png)

**`dropdown.inspector.Follow`** — 339x155, light theme, comfortable density

![The Follow dropdown on the Inspector surface, open, showing its search field and its 2 options with the current choice marked, in the light theme.](docs/huishots/dropdown-inspector-2-follow-caeb179a-20260811.png)

**`dropdown.inspector.Inspecting`** — 338x251, light theme, comfortable density

![The Inspecting dropdown on the Inspector surface, open, showing its search field and its 5 options with the current choice marked, in the light theme.](docs/huishots/dropdown-inspector-1-inspecting-caeb179a-20260811.png)

**`dropdown.inventoryEditor.Inventory`** — 348x251, light theme, comfortable density

![The Inventory dropdown on the Inventory editor surface, open, showing its search field and its 5 options with the current choice marked, in the light theme.](docs/huishots/dropdown-inventoryeditor-1-inventory-caeb179a-20260811.png)

**`dropdown.inventoryEditor.Item type`** — 349x251, light theme, comfortable density

![The Item type dropdown on the Inventory editor surface, open, showing its search field and its 5 options with the current choice marked, in the light theme.](docs/huishots/dropdown-inventoryeditor-2-item-type-caeb179a-20260811.png)

**`dropdown.lightOverlay.Channel`** — 298x219, light theme, comfortable density

![The Channel dropdown on the Light levels surface, open, showing its search field and its 4 options with the current choice marked, in the light theme.](docs/huishots/dropdown-lightoverlay-1-channel-caeb179a-20260811.png)

**`dropdown.lightOverlay.Display`** — 299x187, light theme, comfortable density

![The Display dropdown on the Light levels surface, open, showing its search field and its 3 options with the current choice marked, in the light theme.](docs/huishots/dropdown-lightoverlay-2-display-caeb179a-20260811.png)

**`dropdown.logView.Minimum level`** — 358x219, light theme, comfortable density

![The Minimum level dropdown on the Log surface, open, showing its search field and its 4 options with the current choice marked, in the light theme.](docs/huishots/dropdown-logview-1-minimum-level-caeb179a-20260811.png)

**`dropdown.logView.Source`** — 359x251, light theme, comfortable density

![The Source dropdown on the Log surface, open, showing its search field and its 5 options with the current choice marked, in the light theme.](docs/huishots/dropdown-logview-2-source-caeb179a-20260811.png)

**`dropdown.macroRecorder.Anchor`** — 318x187, light theme, comfortable density

![The Anchor dropdown on the Macro recorder surface, open, showing its search field and its 3 options with the current choice marked, in the light theme.](docs/huishots/dropdown-macrorecorder-1-anchor-caeb179a-20260811.png)

**`dropdown.macroRecorder.Repeat`** — 319x187, light theme, comfortable density

![The Repeat dropdown on the Macro recorder surface, open, showing its search field and its 3 options with the current choice marked, in the light theme.](docs/huishots/dropdown-macrorecorder-2-repeat-caeb179a-20260811.png)

**`dropdown.minecraftInstalls.Resource pack`** — 339x219, light theme, comfortable density

![The Resource pack dropdown on the Minecraft installs surface, open, showing its search field and its 4 options with the current choice marked, in the light theme.](docs/huishots/dropdown-minecraftinstalls-2-resource-pack-caeb179a-20260811.png)

**`dropdown.minecraftInstalls.Version`** — 338x219, light theme, comfortable density

![The Version dropdown on the Minecraft installs surface, open, showing its search field and its 4 options with the current choice marked, in the light theme.](docs/huishots/dropdown-minecraftinstalls-1-version-caeb179a-20260811.png)

**`dropdown.narrator.Backend`** — 269x155, light theme, comfortable density

![The Backend dropdown on the Narrator and voice surface, open, showing its search field and its 2 options with the current choice marked, in the light theme.](docs/huishots/dropdown-narrator-2-backend-caeb179a-20260811.png)

**`dropdown.narrator.Narrator language`** — 268x187, light theme, comfortable density

![The Narrator language dropdown on the Narrator and voice surface, open, showing its search field and its 3 options with the current choice marked, in the light theme.](docs/huishots/dropdown-narrator-1-narrator-language-caeb179a-20260811.png)

**`dropdown.noiseGen.Noise`** — 278x219, light theme, comfortable density

![The Noise dropdown on the Noise fill surface, open, showing its search field and its 4 options with the current choice marked, in the light theme.](docs/huishots/dropdown-noisegen-1-noise-caeb179a-20260811.png)

**`dropdown.noiseGen.Output`** — 279x187, light theme, comfortable density

![The Output dropdown on the Noise fill surface, open, showing its search field and its 3 options with the current choice marked, in the light theme.](docs/huishots/dropdown-noisegen-2-output-caeb179a-20260811.png)

**`dropdown.patternMask.Applies to`** — 299x187, light theme, comfortable density

![The Applies to dropdown on the Pattern and mask surface, open, showing its search field and its 3 options with the current choice marked, in the light theme.](docs/huishots/dropdown-patternmask-2-applies-to-caeb179a-20260811.png)

**`dropdown.patternMask.Match`** — 298x251, light theme, comfortable density

![The Match dropdown on the Pattern and mask surface, open, showing its search field and its 5 options with the current choice marked, in the light theme.](docs/huishots/dropdown-patternmask-1-match-caeb179a-20260811.png)

**`dropdown.portalBuilder.Corners`** — 378x155, light theme, comfortable density

![The Corners dropdown on the Nether portal travel builder surface, open, showing its search field and its 2 options with the current choice marked, in the light theme.](docs/huishots/dropdown-portalbuilder-3-corners-caeb179a-20260811.png)

**`dropdown.portalBuilder.Frame block`** — 379x187, light theme, comfortable density

![The Frame block dropdown on the Nether portal travel builder surface, open, showing its search field and its 3 options with the current choice marked, in the light theme.](docs/huishots/dropdown-portalbuilder-2-frame-block-caeb179a-20260811.png)

**`dropdown.portalBuilder.Orientation`** — 379x155, light theme, comfortable density

![The Orientation dropdown on the Nether portal travel builder surface, open, showing its search field and its 2 options with the current choice marked, in the light theme.](docs/huishots/dropdown-portalbuilder-4-orientation-caeb179a-20260811.png)

**`dropdown.portalBuilder.Size`** — 378x219, light theme, comfortable density

![The Size dropdown on the Nether portal travel builder surface, open, showing its search field and its 4 options with the current choice marked, in the light theme.](docs/huishots/dropdown-portalbuilder-1-size-caeb179a-20260811.png)

**`dropdown.presets.Property`** — 328x251, light theme, comfortable density

![The Property dropdown on the Appearance presets surface, open, showing its search field and its 5 options with the current choice marked, in the light theme.](docs/huishots/dropdown-presets-1-property-caeb179a-20260811.png)

**`dropdown.presets.Scope`** — 329x187, light theme, comfortable density

![The Scope dropdown on the Appearance presets surface, open, showing its search field and its 3 options with the current choice marked, in the light theme.](docs/huishots/dropdown-presets-2-scope-caeb179a-20260811.png)

**`dropdown.railTunnel.Accent columns`** — 386x219, light theme, comfortable density

![The Accent columns dropdown on the Rail tunnel builder surface, open, showing its search field and its 4 options with the current choice marked, in the light theme.](docs/huishots/dropdown-railtunnel-9-accent-columns-caeb179a-20260811.png)

**`dropdown.railTunnel.Alcoves`** — 386x187, light theme, comfortable density

![The Alcoves dropdown on the Rail tunnel builder surface, open, showing its search field and its 3 options with the current choice marked, in the light theme.](docs/huishots/dropdown-railtunnel-11-alcoves-caeb179a-20260811.png)

**`dropdown.railTunnel.Backing`** — 389x219, light theme, comfortable density

![The Backing dropdown on the Rail tunnel builder surface, open, showing its search field and its 4 options with the current choice marked, in the light theme.](docs/huishots/dropdown-railtunnel-19-backing-caeb179a-20260811.png)

**`dropdown.railTunnel.Body pattern`** — 391x251, light theme, comfortable density

![The Body pattern dropdown on the Rail tunnel builder surface, open, showing its search field and its 5 options with the current choice marked, in the light theme.](docs/huishots/dropdown-railtunnel-8-body-pattern-caeb179a-20260811.png)

**`dropdown.railTunnel.Column block`** — 391x219, light theme, comfortable density

![The Column block dropdown on the Rail tunnel builder surface, open, showing its search field and its 4 options with the current choice marked, in the light theme.](docs/huishots/dropdown-railtunnel-10-column-block-caeb179a-20260811.png)

**`dropdown.railTunnel.Cross-section`** — 388x219, light theme, comfortable density

![The Cross-section dropdown on the Rail tunnel builder surface, open, showing its search field and its 4 options with the current choice marked, in the light theme.](docs/huishots/dropdown-railtunnel-4-cross-section-caeb179a-20260811.png)

**`dropdown.railTunnel.Dimension`** — 388x155, light theme, comfortable density

![The Dimension dropdown on the Rail tunnel builder surface, open, showing its search field and its 2 options with the current choice marked, in the light theme.](docs/huishots/dropdown-railtunnel-3-dimension-caeb179a-20260811.png)

**`dropdown.railTunnel.Fixture block`** — 388x315, light theme, comfortable density

![The Fixture block dropdown on the Rail tunnel builder surface, open, showing its search field and its 7 options with the current choice marked, in the light theme.](docs/huishots/dropdown-railtunnel-18-fixture-block-caeb179a-20260811.png)

**`dropdown.railTunnel.Floor block`** — 388x187, light theme, comfortable density

![The Floor block dropdown on the Rail tunnel builder surface, open, showing its search field and its 3 options with the current choice marked, in the light theme.](docs/huishots/dropdown-railtunnel-6-floor-block-caeb179a-20260811.png)

**`dropdown.railTunnel.Placement`** — 388x251, light theme, comfortable density

![The Placement dropdown on the Rail tunnel builder surface, open, showing its search field and its 5 options with the current choice marked, in the light theme.](docs/huishots/dropdown-railtunnel-16-placement-caeb179a-20260811.png)

**`dropdown.railTunnel.Rib block`** — 389x187, light theme, comfortable density

![The Rib block dropdown on the Rail tunnel builder surface, open, showing its search field and its 3 options with the current choice marked, in the light theme.](docs/huishots/dropdown-railtunnel-15-rib-block-caeb179a-20260811.png)

**`dropdown.railTunnel.Ribs`** — 388x187, light theme, comfortable density

![The Ribs dropdown on the Rail tunnel builder surface, open, showing its search field and its 3 options with the current choice marked, in the light theme.](docs/huishots/dropdown-railtunnel-14-ribs-caeb179a-20260811.png)

**`dropdown.railTunnel.Roof block`** — 389x187, light theme, comfortable density

![The Roof block dropdown on the Rail tunnel builder surface, open, showing its search field and its 3 options with the current choice marked, in the light theme.](docs/huishots/dropdown-railtunnel-7-roof-block-caeb179a-20260811.png)

**`dropdown.railTunnel.Roof block`** — 389x219, light theme, comfortable density

![The Roof block dropdown on the Rail tunnel builder surface, open, showing its search field and its 4 options with the current choice marked, in the light theme.](docs/huishots/dropdown-railtunnel-13-roof-block-caeb179a-20260811.png)

**`dropdown.railTunnel.Routing`** — 388x219, light theme, comfortable density

![The Routing dropdown on the Rail tunnel builder surface, open, showing its search field and its 4 options with the current choice marked, in the light theme.](docs/huishots/dropdown-railtunnel-1-routing-caeb179a-20260811.png)

**`dropdown.railTunnel.Shape`** — 388x283, light theme, comfortable density

![The Shape dropdown on the Rail tunnel builder surface, open, showing its search field and its 6 options with the current choice marked, in the light theme.](docs/huishots/dropdown-railtunnel-12-shape-caeb179a-20260811.png)

**`dropdown.railTunnel.Side`** — 389x219, light theme, comfortable density

![The Side dropdown on the Rail tunnel builder surface, open, showing its search field and its 4 options with the current choice marked, in the light theme.](docs/huishots/dropdown-railtunnel-17-side-caeb179a-20260811.png)

**`dropdown.railTunnel.Slope handling`** — 389x187, light theme, comfortable density

![The Slope handling dropdown on the Rail tunnel builder surface, open, showing its search field and its 3 options with the current choice marked, in the light theme.](docs/huishots/dropdown-railtunnel-2-slope-handling-caeb179a-20260811.png)

**`dropdown.railTunnel.Wall block`** — 389x219, light theme, comfortable density

![The Wall block dropdown on the Rail tunnel builder surface, open, showing its search field and its 4 options with the current choice marked, in the light theme.](docs/huishots/dropdown-railtunnel-5-wall-block-caeb179a-20260811.png)

**`dropdown.redstoneTrace.Action`** — 348x219, light theme, comfortable density

![The Action dropdown on the Circuit trace surface, open, showing its search field and its 4 options with the current choice marked, in the light theme.](docs/huishots/dropdown-redstonetrace-1-action-caeb179a-20260811.png)

**`dropdown.redstoneTrace.Wiring`** — 349x155, light theme, comfortable density

![The Wiring dropdown on the Circuit trace surface, open, showing its search field and its 2 options with the current choice marked, in the light theme.](docs/huishots/dropdown-redstonetrace-2-wiring-caeb179a-20260811.png)

**`dropdown.relight.Area`** — 269x187, light theme, comfortable density

![The Area dropdown on the Relight surface, open, showing its search field and its 3 options with the current choice marked, in the light theme.](docs/huishots/dropdown-relight-2-area-caeb179a-20260811.png)

**`dropdown.relight.Light type`** — 268x187, light theme, comfortable density

![The Light type dropdown on the Relight surface, open, showing its search field and its 3 options with the current choice marked, in the light theme.](docs/huishots/dropdown-relight-1-light-type-caeb179a-20260811.png)

**`dropdown.removeEntities.Category`** — 268x283, light theme, comfortable density

![The Category dropdown on the Remove entities surface, open, showing its search field and its 6 options with the current choice marked, in the light theme.](docs/huishots/dropdown-removeentities-1-category-caeb179a-20260811.png)

**`dropdown.removeEntities.Named entities`** — 269x187, light theme, comfortable density

![The Named entities dropdown on the Remove entities surface, open, showing its search field and its 3 options with the current choice marked, in the light theme.](docs/huishots/dropdown-removeentities-2-named-entities-caeb179a-20260811.png)

**`dropdown.seaLevel.Action`** — 260x187, light theme, comfortable density

![The Action dropdown on the Sea level surface, open, showing its search field and its 3 options with the current choice marked, in the light theme.](docs/huishots/dropdown-sealevel-1-action-caeb179a-20260811.png)

**`dropdown.seaLevel.Enclosure`** — 260x155, light theme, comfortable density

![The Enclosure dropdown on the Sea level surface, open, showing its search field and its 2 options with the current choice marked, in the light theme.](docs/huishots/dropdown-sealevel-2-enclosure-caeb179a-20260811.png)

**`dropdown.spawnAnalysis.Show`** — 348x219, light theme, comfortable density

![The Show dropdown on the Mob spawn analysis surface, open, showing its search field and its 4 options with the current choice marked, in the light theme.](docs/huishots/dropdown-spawnanalysis-1-show-caeb179a-20260811.png)

**`dropdown.spawnAnalysis.Time`** — 349x187, light theme, comfortable density

![The Time dropdown on the Mob spawn analysis surface, open, showing its search field and its 3 options with the current choice marked, in the light theme.](docs/huishots/dropdown-spawnanalysis-2-time-caeb179a-20260811.png)

**`dropdown.stackArray.Axis`** — 279x219, light theme, comfortable density

![The Axis dropdown on the Stack and array surface, open, showing its search field and its 4 options with the current choice marked, in the light theme.](docs/huishots/dropdown-stackarray-2-axis-caeb179a-20260811.png)

**`dropdown.stackArray.Layout`** — 278x187, light theme, comfortable density

![The Layout dropdown on the Stack and array surface, open, showing its search field and its 3 options with the current choice marked, in the light theme.](docs/huishots/dropdown-stackarray-1-layout-caeb179a-20260811.png)

**`dropdown.surfacePaint.Blend`** — 279x187, light theme, comfortable density

![The Blend dropdown on the Repaint surface surface, open, showing its search field and its 3 options with the current choice marked, in the light theme.](docs/huishots/dropdown-surfacepaint-2-blend-caeb179a-20260811.png)

**`dropdown.surfacePaint.Driven by`** — 278x219, light theme, comfortable density

![The Driven by dropdown on the Repaint surface surface, open, showing its search field and its 4 options with the current choice marked, in the light theme.](docs/huishots/dropdown-surfacepaint-1-driven-by-caeb179a-20260811.png)

**`dropdown.tabManager.Group state`** — 379x155, light theme, comfortable density

![The Group state dropdown on the Tabs, groups, and safe closing surface, open, showing its search field and its 2 options with the current choice marked, in the light theme.](docs/huishots/dropdown-tabmanager-2-group-state-caeb179a-20260811.png)

**`dropdown.tabManager.Tab strip edge`** — 378x219, light theme, comfortable density

![The Tab strip edge dropdown on the Tabs, groups, and safe closing surface, open, showing its search field and its 4 options with the current choice marked, in the light theme.](docs/huishots/dropdown-tabmanager-1-tab-strip-edge-caeb179a-20260811.png)

**`dropdown.terrainBrush.Brush shape`** — 288x219, light theme, comfortable density

![The Brush shape dropdown on the Terrain brush surface, open, showing its search field and its 4 options with the current choice marked, in the light theme.](docs/huishots/dropdown-terrainbrush-1-brush-shape-caeb179a-20260811.png)

**`dropdown.terrainBrush.Falloff`** — 289x219, light theme, comfortable density

![The Falloff dropdown on the Terrain brush surface, open, showing its search field and its 4 options with the current choice marked, in the light theme.](docs/huishots/dropdown-terrainbrush-2-falloff-caeb179a-20260811.png)

**`dropdown.toolSettings.On activation`** — 309x155, light theme, comfortable density

![The On activation dropdown on the Tool settings surface, open, showing its search field and its 2 options with the current choice marked, in the light theme.](docs/huishots/dropdown-toolsettings-2-on-activation-caeb179a-20260811.png)

**`dropdown.toolSettings.Tool`** — 308x340, light theme, comfortable density

![The Tool dropdown on the Tool settings surface, open, showing its search field and its 9 options with the current choice marked, in the light theme.](docs/huishots/dropdown-toolsettings-1-tool-caeb179a-20260811.png)

**`dropdown.versionSelect.Data version`** — 260x219, light theme, comfortable density

![The Data version dropdown on the Select version surface, open, showing its search field and its 4 options with the current choice marked, in the light theme.](docs/huishots/dropdown-versionselect-2-data-version-caeb179a-20260811.png)

**`dropdown.versionSelect.Platform`** — 260x187, light theme, comfortable density

![The Platform dropdown on the Select version surface, open, showing its search field and its 3 options with the current choice marked, in the light theme.](docs/huishots/dropdown-versionselect-1-platform-caeb179a-20260811.png)

**`dropdown.viewControls.Control scheme`** — 319x187, light theme, comfortable density

![The Control scheme dropdown on the View settings surface, open, showing its search field and its 3 options with the current choice marked, in the light theme.](docs/huishots/dropdown-viewcontrols-2-control-scheme-caeb179a-20260811.png)

**`dropdown.viewControls.View type`** — 318x283, light theme, comfortable density

![The View type dropdown on the View settings surface, open, showing its search field and its 6 options with the current choice marked, in the light theme.](docs/huishots/dropdown-viewcontrols-1-view-type-caeb179a-20260811.png)

**`dropdown.workPlane.Axis`** — 268x187, light theme, comfortable density

![The Axis dropdown on the Work plane surface, open, showing its search field and its 3 options with the current choice marked, in the light theme.](docs/huishots/dropdown-workplane-1-axis-caeb179a-20260811.png)

**`dropdown.workPlane.Snap`** — 269x187, light theme, comfortable density

![The Snap dropdown on the Work plane surface, open, showing its search field and its 3 options with the current choice marked, in the light theme.](docs/huishots/dropdown-workplane-2-snap-caeb179a-20260811.png)

</details>

<details>
<summary><b>Surfaces</b> — 113 surfaces</summary>

**`about`** — 640x280, light theme, comfortable density

![The About surface (Currently opened world), showing its window search and 2 sections, in the light theme.](docs/huishots/about-caeb179a-20260811.png)

**`analyzeTool`** — 740x280, light theme, comfortable density

![The Analyze surface (Analysis), showing its window search and 3 sections, in the light theme.](docs/huishots/analyzetool-caeb179a-20260811.png)

**`batchQueue`** — 760x280, light theme, comfortable density

![The Batch queue surface (Automation), showing its window search and 3 sections, in the light theme.](docs/huishots/batchqueue-caeb179a-20260811.png)

**`biomeMap`** — 720x280, light theme, comfortable density

![The Biome map surface (Analysis), showing its window search and 2 sections, in the light theme.](docs/huishots/biomemap-caeb179a-20260811.png)

**`biomeSelect`** — 620x280, light theme, comfortable density

![The Select biome surface (Biome picker), showing its window search and 2 sections, in the light theme.](docs/huishots/biomeselect-caeb179a-20260811.png)

**`blockAudit`** — 740x280, light theme, comfortable density

![The Block state audit surface (Blocks), showing its window search and 4 sections, in the light theme.](docs/huishots/blockaudit-caeb179a-20260811.png)

**`blockHistogram`** — 720x280, light theme, comfortable density

![The Block histogram surface (Analysis), showing its window search and 2 sections, in the light theme.](docs/huishots/blockhistogram-caeb179a-20260811.png)

**`blockSelect`** — 720x280, light theme, comfortable density

![The Select block surface (Block picker), showing its window search and 5 sections, in the light theme.](docs/huishots/blockselect-caeb179a-20260811.png)

**`brushSettings`** — 700x280, light theme, comfortable density

![The Brush surface (Tools), showing its window search and 5 sections, in the light theme.](docs/huishots/brushsettings-caeb179a-20260811.png)

**`brushTool`** — 640x280, light theme, comfortable density

![The Shape brush surface (Build), showing its window search and 4 sections, in the light theme.](docs/huishots/brushtool-caeb179a-20260811.png)

**`caveMap`** — 700x280, light theme, comfortable density

![The Cave coverage surface (Worldgen), showing its window search and 3 sections, in the light theme.](docs/huishots/cavemap-caeb179a-20260811.png)

**`chunkInspector`** — 780x280, light theme, comfortable density

![The Chunk inspector surface (Analysis), showing its window search and 3 sections, in the light theme.](docs/huishots/chunkinspector-caeb179a-20260811.png)

**`cloneTool`** — 680x280, light theme, comfortable density

![The Clone surface (Tools), showing its window search and 3 sections, in the light theme.](docs/huishots/clonetool-caeb179a-20260811.png)

**`commandFinder`** — 760x280, light theme, comfortable density

![The Command blocks surface (Data), showing its window search and 4 sections, in the light theme.](docs/huishots/commandfinder-caeb179a-20260811.png)

**`configureBlocks`** — 740x318, light theme, comfortable density

![The Configure blocks surface (Pickers), showing its window search and 4 sections, in the light theme.](docs/huishots/configureblocks-caeb179a-20260811.png)

**`confirm`** — 520x280, light theme, comfortable density

![The Delete unselected chunks surface (Safety gate), showing its window search and 2 sections, in the light theme.](docs/huishots/confirm-caeb179a-20260811.png)

**`controls`** — 720x280, light theme, comfortable density

![The Key Select surface (Key configuration), showing its window search and 3 sections, in the light theme.](docs/huishots/controls-caeb179a-20260811.png)

**`convertProgress`** — 600x280, light theme, comfortable density

![The Converting world surface (World conversion), showing its window search and 3 sections, in the light theme.](docs/huishots/convertprogress-caeb179a-20260811.png)

**`cutawayView`** — 620x280, light theme, comfortable density

![The Cutaway surface (View), showing its window search and 2 sections, in the light theme.](docs/huishots/cutawayview-caeb179a-20260811.png)

**`dimsum`** — 520x280, light theme, comfortable density

![The Har gow · 蝦餃 surface (Startup surprise), showing its window search and 2 sections, in the light theme.](docs/huishots/dimsum-caeb179a-20260811.png)

**`docs`** — 820x280, light theme, comfortable density

![The Documentation surface (Offline bundle), showing its window search and 3 sections, in the light theme.](docs/huishots/docs-caeb179a-20260811.png)

**`editChunkTool`** — 700x280, light theme, comfortable density

![The Edit chunk surface (Tools), showing its window search and 4 sections, in the light theme.](docs/huishots/editchunktool-caeb179a-20260811.png)

**`elementAppearance`** — 640x280, light theme, comfortable density

![The Edit appearance surface (Per-element appearance), showing its window search and 5 sections, in the light theme.](docs/huishots/elementappearance-caeb179a-20260811.png)

**`entityBrowser`** — 800x280, light theme, comfortable density

![The Entity browser surface (Entities), showing its window search and 6 sections, in the light theme.](docs/huishots/entitybrowser-caeb179a-20260811.png)

**`entityEdit`** — 660x318, light theme, comfortable density

![The Edit entity surface (Entities), showing its window search and 4 sections, in the light theme.](docs/huishots/entityedit-caeb179a-20260811.png)

**`erosion`** — 600x280, light theme, comfortable density

![The Erosion surface (Sculpt), showing its window search and 3 sections, in the light theme.](docs/huishots/erosion-caeb179a-20260811.png)

**`errorReport`** — 680x318, light theme, comfortable density

![The Unexpected error surface (Diagnostics), showing its window search and 3 sections, in the light theme.](docs/huishots/errorreport-caeb179a-20260811.png)

**`exportStructure`** — 600x280, light theme, comfortable density

![The Export selection surface (Structure files), showing its window search and 3 sections, in the light theme.](docs/huishots/exportstructure-caeb179a-20260811.png)

**`externalEditor`** — 620x318, light theme, comfortable density

![The External editor surface (Safe bridge), showing its window search and 3 sections, in the light theme.](docs/huishots/externaleditor-caeb179a-20260811.png)

**`findReplaceBlocks`** — 760x280, light theme, comfortable density

![The Blocks surface (Find and replace), showing its window search and 4 sections, in the light theme.](docs/huishots/findreplaceblocks-caeb179a-20260811.png)

**`findReplaceCommands`** — 780x280, light theme, comfortable density

![The Commands surface (Find and replace), showing its window search and 5 sections, in the light theme.](docs/huishots/findreplacecommands-caeb179a-20260811.png)

**`findReplaceNbt`** — 780x280, light theme, comfortable density

![The NBT surface (Find and replace), showing its window search and 4 sections, in the light theme.](docs/huishots/findreplacenbt-caeb179a-20260811.png)

**`flatten`** — 560x280, light theme, comfortable density

![The Flatten to height surface (Sculpt), showing its window search and 2 sections, in the light theme.](docs/huishots/flatten-caeb179a-20260811.png)

**`floodFill`** — 620x280, light theme, comfortable density

![The Flood fill surface (Tools), showing its window search and 4 sections, in the light theme.](docs/huishots/floodfill-caeb179a-20260811.png)

**`forceLoaded`** — 700x280, light theme, comfortable density

![The Force-loaded chunks surface (Boundaries), showing its window search and 2 sections, in the light theme.](docs/huishots/forceloaded-caeb179a-20260811.png)

**`fourUpView`** — 660x280, light theme, comfortable density

![The Four-up split surface (View), showing its window search and 2 sections, in the light theme.](docs/huishots/fourupview-caeb179a-20260811.png)

**`gamerules`** — 700x280, light theme, comfortable density

![The Game rules surface (Data), showing its window search and 4 sections, in the light theme.](docs/huishots/gamerules-caeb179a-20260811.png)

**`generateTool`** — 720x280, light theme, comfortable density

![The Generate surface (Tools), showing its window search and 5 sections, in the light theme.](docs/huishots/generatetool-caeb179a-20260811.png)

**`goto`** — 460x280, light theme, comfortable density

![The Teleport surface (Camera), showing its window search and 1 sections, in the light theme.](docs/huishots/goto-caeb179a-20260811.png)

**`heightLimits`** — 700x280, light theme, comfortable density

![The Height limits surface (Boundaries), showing its window search and 4 sections, in the light theme.](docs/huishots/heightlimits-caeb179a-20260811.png)

**`history`** — 760x366, light theme, comfortable density

![The Project history surface (Local Git repository), showing its window search and 3 sections, in the light theme.](docs/huishots/history-caeb179a-20260811.png)

**`importChunks`** — 600x280, light theme, comfortable density

![The Import chunks surface (Chunk tool), showing its window search and 2 sections, in the light theme.](docs/huishots/importchunks-caeb179a-20260811.png)

**`importMap`** — 700x280, light theme, comfortable density

![The Import map image surface (Import), showing its window search and 4 sections, in the light theme.](docs/huishots/importmap-caeb179a-20260811.png)

**`inspector`** — 740x280, light theme, comfortable density

![The Inspector surface (Panels), showing its window search and 3 sections, in the light theme.](docs/huishots/inspector-caeb179a-20260811.png)

**`inventoryEditor`** — 760x280, light theme, comfortable density

![The Inventory editor surface (Panels), showing its window search and 4 sections, in the light theme.](docs/huishots/inventoryeditor-caeb179a-20260811.png)

**`itemTypeList`** — 720x280, light theme, comfortable density

![The Item types surface (Pickers), showing its window search and 3 sections, in the light theme.](docs/huishots/itemtypelist-caeb179a-20260811.png)

**`languageSelect`** — 520x280, light theme, comfortable density

![The Language Select surface (Localization), showing its window search and 1 sections, in the light theme.](docs/huishots/languageselect-caeb179a-20260811.png)

**`layerSlice`** — 560x280, light theme, comfortable density

![The Layer slice surface (Measure), showing its window search and 3 sections, in the light theme.](docs/huishots/layerslice-caeb179a-20260811.png)

**`levelDat`** — 700x280, light theme, comfortable density

![The level.dat surface (Data), showing its window search and 3 sections, in the light theme.](docs/huishots/leveldat-caeb179a-20260811.png)

**`libraryPanel`** — 760x318, light theme, comfortable density

![The Library surface (Panels), showing its window search and 4 sections, in the light theme.](docs/huishots/librarypanel-caeb179a-20260811.png)

**`licenses`** — 700x280, light theme, comfortable density

![The Third Party Licenses surface (Legal), showing its window search and 2 sections, in the light theme.](docs/huishots/licenses-caeb179a-20260811.png)

**`lightOverlay`** — 660x280, light theme, comfortable density

![The Light levels surface (Mechanics), showing its window search and 4 sections, in the light theme.](docs/huishots/lightoverlay-caeb179a-20260811.png)

**`loading`** — 560x280, light theme, comfortable density

![The Please wait while the renderer loads surface (Renderer), showing its window search and 4 sections, in the light theme.](docs/huishots/loading-caeb179a-20260811.png)

**`logView`** — 780x280, light theme, comfortable density

![The Log surface (Diagnostics), showing its window search and 3 sections, in the light theme.](docs/huishots/logview-caeb179a-20260811.png)

**`lootAudit`** — 720x280, light theme, comfortable density

![The Loot audit surface (Containers), showing its window search and 3 sections, in the light theme.](docs/huishots/lootaudit-caeb179a-20260811.png)

**`macroRecorder`** — 700x280, light theme, comfortable density

![The Macro recorder surface (Automation), showing its window search and 2 sections, in the light theme.](docs/huishots/macrorecorder-caeb179a-20260811.png)

**`mapItems`** — 700x280, light theme, comfortable density

![The Map items surface (Data), showing its window search and 3 sections, in the light theme.](docs/huishots/mapitems-caeb179a-20260811.png)

**`measure`** — 560x280, light theme, comfortable density

![The Measure surface (Measure), showing its window search and 2 sections, in the light theme.](docs/huishots/measure-caeb179a-20260811.png)

**`minecraftInstalls`** — 740x280, light theme, comfortable density

![The Minecraft installs surface (Resources), showing its window search and 4 sections, in the light theme.](docs/huishots/minecraftinstalls-caeb179a-20260811.png)

**`moveTool`** — 640x280, light theme, comfortable density

![The Move surface (Tools), showing its window search and 3 sections, in the light theme.](docs/huishots/movetool-caeb179a-20260811.png)

**`narrator`** — 600x280, light theme, comfortable density

![The Narrator and voice surface (Optional speech), showing its window search and 3 sections, in the light theme.](docs/huishots/narrator-caeb179a-20260811.png)

**`nbtLegacy`** — 720x280, light theme, comfortable density

![The NBT editor surface (Raw data), showing its window search and 3 sections, in the light theme.](docs/huishots/nbtlegacy-caeb179a-20260811.png)

**`nbtSearch`** — 760x318, light theme, comfortable density

![The NBT search and replace surface (Data), showing its window search and 4 sections, in the light theme.](docs/huishots/nbtsearch-caeb179a-20260811.png)

**`noiseGen`** — 620x280, light theme, comfortable density

![The Noise fill surface (Generate), showing its window search and 3 sections, in the light theme.](docs/huishots/noisegen-caeb179a-20260811.png)

**`operationOptions`** — 640x280, light theme, comfortable density

![The Replace surface (Stock operation), showing its window search and 3 sections, in the light theme.](docs/huishots/operationoptions-caeb179a-20260811.png)

**`oreAudit`** — 740x280, light theme, comfortable density

![The Ore distribution surface (Worldgen), showing its window search and 3 sections, in the light theme.](docs/huishots/oreaudit-caeb179a-20260811.png)

**`patternMask`** — 660x280, light theme, comfortable density

![The Pattern and mask surface (Build), showing its window search and 4 sections, in the light theme.](docs/huishots/patternmask-caeb179a-20260811.png)

**`pendingImports`** — 740x318, light theme, comfortable density

![The Pending imports surface (Panels), showing its window search and 3 sections, in the light theme.](docs/huishots/pendingimports-caeb179a-20260811.png)

**`playerData`** — 720x280, light theme, comfortable density

![The Player data surface (Data), showing its window search and 4 sections, in the light theme.](docs/huishots/playerdata-caeb179a-20260811.png)

**`playerPanel`** — 720x318, light theme, comfortable density

![The Players surface (Panels), showing its window search and 3 sections, in the light theme.](docs/huishots/playerpanel-caeb179a-20260811.png)

**`pluginsDialog`** — 740x318, light theme, comfortable density

![The Plugins surface (Extensibility), showing its window search and 4 sections, in the light theme.](docs/huishots/pluginsdialog-caeb179a-20260811.png)

**`portalBuilder`** — 820x414, light theme, comfortable density

![The Nether portal travel builder surface (Travel), showing its window search and 7 sections, in the light theme.](docs/huishots/portalbuilder-caeb179a-20260811.png)

**`portalLinker`** — 740x280, light theme, comfortable density

![The Portal linkage surface (Redstone), showing its window search and 3 sections, in the light theme.](docs/huishots/portallinker-caeb179a-20260811.png)

**`presets`** — 720x462, light theme, comfortable density

![The Appearance presets surface (Versioned interchange), showing its window search and 3 sections, in the light theme.](docs/huishots/presets-caeb179a-20260811.png)

**`profiler`** — 740x318, light theme, comfortable density

![The Profiler surface (Diagnostics), showing its window search and 2 sections, in the light theme.](docs/huishots/profiler-caeb179a-20260811.png)

**`pythonConsole`** — 760x280, light theme, comfortable density

![The Python console surface (Diagnostics), showing its window search and 2 sections, in the light theme.](docs/huishots/pythonconsole-caeb179a-20260811.png)

**`railNetwork`** — 740x280, light theme, comfortable density

![The Rail network surface (Redstone), showing its window search and 4 sections, in the light theme.](docs/huishots/railnetwork-caeb179a-20260811.png)

**`railTunnel`** — 840x414, light theme, comfortable density

![The Rail tunnel builder surface (Travel), showing its window search and 17 sections, in the light theme.](docs/huishots/railtunnel-caeb179a-20260811.png)

**`redstoneTrace`** — 760x318, light theme, comfortable density

![The Circuit trace surface (Redstone), showing its window search and 5 sections, in the light theme.](docs/huishots/redstonetrace-caeb179a-20260811.png)

**`regenerate`** — 600x280, light theme, comfortable density

![The Regenerate chunks surface (Generate), showing its window search and 2 sections, in the light theme.](docs/huishots/regenerate-caeb179a-20260811.png)

**`relight`** — 600x280, light theme, comfortable density

![The Relight surface (Integrity), showing its window search and 2 sections, in the light theme.](docs/huishots/relight-caeb179a-20260811.png)

**`removeEntities`** — 600x280, light theme, comfortable density

![The Remove entities surface (Entities), showing its window search and 3 sections, in the light theme.](docs/huishots/removeentities-caeb179a-20260811.png)

**`renderLayers`** — 640x280, light theme, comfortable density

![The Render layers surface (View), showing its window search and 2 sections, in the light theme.](docs/huishots/renderlayers-caeb179a-20260811.png)

**`schematicLibrary`** — 760x318, light theme, comfortable density

![The Structure library surface (Build), showing its window search and 3 sections, in the light theme.](docs/huishots/schematiclibrary-caeb179a-20260811.png)

**`schoolUnlock`** — 520x280, light theme, comfortable density

![The School mode surface (Presentation lock), showing its window search and 2 sections, in the light theme.](docs/huishots/schoolunlock-caeb179a-20260811.png)

**`scoreboard`** — 740x280, light theme, comfortable density

![The Scoreboard surface (Data), showing its window search and 3 sections, in the light theme.](docs/huishots/scoreboard-caeb179a-20260811.png)

**`scriptConsole`** — 760x318, light theme, comfortable density

![The Operation console surface (Automation), showing its window search and 3 sections, in the light theme.](docs/huishots/scriptconsole-caeb179a-20260811.png)

**`seaLevel`** — 560x280, light theme, comfortable density

![The Sea level surface (Generate), showing its window search and 3 sections, in the light theme.](docs/huishots/sealevel-caeb179a-20260811.png)

**`seedTools`** — 700x280, light theme, comfortable density

![The Seed tools surface (Worldgen), showing its window search and 3 sections, in the light theme.](docs/huishots/seedtools-caeb179a-20260811.png)

**`selectBlockTool`** — 680x280, light theme, comfortable density

![The Select block surface (Tools), showing its window search and 2 sections, in the light theme.](docs/huishots/selectblocktool-caeb179a-20260811.png)

**`selectEntityTool`** — 660x280, light theme, comfortable density

![The Select entity surface (Tools), showing its window search and 2 sections, in the light theme.](docs/huishots/selectentitytool-caeb179a-20260811.png)

**`signSearch`** — 700x280, light theme, comfortable density

![The Sign text surface (Data), showing its window search and 4 sections, in the light theme.](docs/huishots/signsearch-caeb179a-20260811.png)

**`slimeChunks`** — 660x280, light theme, comfortable density

![The Slime chunks surface (Worldgen), showing its window search and 3 sections, in the light theme.](docs/huishots/slimechunks-caeb179a-20260811.png)

**`smooth`** — 560x280, light theme, comfortable density

![The Smooth terrain surface (Sculpt), showing its window search and 2 sections, in the light theme.](docs/huishots/smooth-caeb179a-20260811.png)

**`spawnAnalysis`** — 760x280, light theme, comfortable density

![The Mob spawn analysis surface (Mechanics), showing its window search and 5 sections, in the light theme.](docs/huishots/spawnanalysis-caeb179a-20260811.png)

**`spawnPoints`** — 700x280, light theme, comfortable density

![The Spawn points and beds surface (Redstone), showing its window search and 3 sections, in the light theme.](docs/huishots/spawnpoints-caeb179a-20260811.png)

**`stackArray`** — 620x280, light theme, comfortable density

![The Stack and array surface (Build), showing its window search and 3 sections, in the light theme.](docs/huishots/stackarray-caeb179a-20260811.png)

**`structureLocator`** — 780x280, light theme, comfortable density

![The Locate structures surface (Worldgen), showing its window search and 6 sections, in the light theme.](docs/huishots/structurelocator-caeb179a-20260811.png)

**`surfacePaint`** — 620x280, light theme, comfortable density

![The Repaint surface surface (Surface), showing its window search and 3 sections, in the light theme.](docs/huishots/surfacepaint-caeb179a-20260811.png)

**`tabManager`** — 820x280, light theme, comfortable density

![The Tabs, groups, and safe closing surface (Workspace navigation), showing its window search and 7 sections, in the light theme.](docs/huishots/tabmanager-caeb179a-20260811.png)

**`terrainBrush`** — 640x280, light theme, comfortable density

![The Terrain brush surface (Sculpt), showing its window search and 4 sections, in the light theme.](docs/huishots/terrainbrush-caeb179a-20260811.png)

**`tickLoad`** — 740x280, light theme, comfortable density

![The Tick load surface (Mechanics), showing its window search and 3 sections, in the light theme.](docs/huishots/tickload-caeb179a-20260811.png)

**`toolSettings`** — 680x280, light theme, comfortable density

![The Tool settings surface (Tools), showing its window search and 3 sections, in the light theme.](docs/huishots/toolsettings-caeb179a-20260811.png)

**`undoHistory`** — 700x280, light theme, comfortable density

![The Undo history surface (History), showing its window search and 2 sections, in the light theme.](docs/huishots/undohistory-caeb179a-20260811.png)

**`update`** — 620x318, light theme, comfortable density

![The Update status surface (Windows delivery), showing its window search and 2 sections, in the light theme.](docs/huishots/update-caeb179a-20260811.png)

**`validateRepair`** — 760x318, light theme, comfortable density

![The Validate and repair surface (Integrity), showing its window search and 2 sections, in the light theme.](docs/huishots/validaterepair-caeb179a-20260811.png)

**`versionSelect`** — 560x280, light theme, comfortable density

![The Select version surface (Platform), showing its window search and 2 sections, in the light theme.](docs/huishots/versionselect-caeb179a-20260811.png)

**`viewControls`** — 700x280, light theme, comfortable density

![The View settings surface (View), showing its window search and 3 sections, in the light theme.](docs/huishots/viewcontrols-caeb179a-20260811.png)

**`waypoints`** — 620x280, light theme, comfortable density

![The Waypoints surface (Navigation), showing its window search and 3 sections, in the light theme.](docs/huishots/waypoints-caeb179a-20260811.png)

**`workPlane`** — 600x280, light theme, comfortable density

![The Work plane surface (View), showing its window search and 3 sections, in the light theme.](docs/huishots/workplane-caeb179a-20260811.png)

**`worldBorder`** — 660x280, light theme, comfortable density

![The World border surface (Boundaries), showing its window search and 3 sections, in the light theme.](docs/huishots/worldborder-caeb179a-20260811.png)

**`worldDiff`** — 780x280, light theme, comfortable density

![The Compare worlds surface (Integrity), showing its window search and 2 sections, in the light theme.](docs/huishots/worlddiff-caeb179a-20260811.png)

**`worldInfo`** — 700x280, light theme, comfortable density

![The World info surface (Panels), showing its window search and 3 sections, in the light theme.](docs/huishots/worldinfo-caeb179a-20260811.png)

</details>

<details>
<summary><b>Not captured</b> — 3</summary>

These are recorded rather than omitted. A gap nobody mentions reads as coverage.

| Surface | Why not |
| --- | --- |
| `menu-appearance` | 8 descendant(s) reported drawing but the picture holds only 3 distinct colours and is 74% one colour: the rows did not draw, so the file was deleted rather than shipped as evidence. |
| `menu-application-file` | 9 descendant(s) reported drawing but the picture holds only 3 distinct colours and is 74% one colour: the rows did not draw, so the file was deleted rather than shipped as evidence. |
| `menu-application-view` | 16 descendant(s) reported drawing but the picture holds only 3 distinct colours and is 74% one colour: the rows did not draw, so the file was deleted rather than shipped as evidence. |

</details>

<details>
<summary><b>Menus and overlays not opened</b> — 1</summary>

A menu that a run could not raise is written down here rather than left out. A gap nobody mentions reads as coverage.

| Surface | Why not |
| --- | --- |
| `regexbuilder-every-other-search-field` | The builder is one class, opened by every search bar in the product; it is photographed from 4 kinds of host (regexBuilder.dropdown, regexBuilder.menu, regexBuilder.palette, regexBuilder.panel). The Studio shell alone carries 3 search bars and every spec surface carries at least one more, so photographing each field's builder would repeat the same popover under a different anchor name. |

</details>

<!-- END CAPTURES -->

> [!NOTE]
> The images further down this section show **earlier builds** — the
> pre-Material workflow screenshots and the owner-drawn Material shell that the
> Studio replaced. They are kept because they are genuine records of what they
> show, and they are labelled as such. They are not evidence for the current
> interface; the matrix above is.

Every image in this section is a tracked screenshot of the real wxPython app.
They intentionally retain the version visible in the captured window. No mockup
or generated image is presented as runtime evidence.

### Superseded Material shell (2026-08-09)

![Amulet Material application shell at exact commit b3cbec1c with compact caption controls, an app-owned command bar, and a single action card](resource/img/main-frame-material-shell-b3cbec1c-20260809.png)

Captured from exact commit `b3cbec1c4b1035dd0c2ebdc9a545266f49c257ef`
on an isolated hidden Windows desktop with wxPython 4.2.5. The 2250×1395
capture shows the source frame after startup: no acknowledgement or
purchase prompt, no duplicate one-page tab rail, one logo, and M3 action
hierarchy. **This is the shell Amulet Studio replaced**, not the current one.

<details>
<summary><strong>Open six historical pre-Material workflow screenshots</strong></summary>

<table>
  <tr>
    <td width="50%" valign="top">
      <img src="resource/img/main_menu.jpg" alt="Amulet 0.6.1 main menu with Open World and Help buttons"><br>
      <strong>Historical pre-Material main menu — 0.6.1.</strong> The entry point for opening a world or help in that build.
    </td>
    <td width="50%" valign="top">
      <img src="resource/img/about.jpg" alt="Amulet 0.6.1 open-world workspace with About, Convert, and 3D Editor navigation"><br>
      <strong>Historical pre-Material open-world workspace — 0.6.1.</strong> One open world with the About, Convert, and 3D Editor program rail.
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <img src="resource/img/world_select.jpg" alt="Legacy Amulet world-selection window with Java and Bedrock discovery collapsed"><br>
      <strong>Historical pre-Material world selection.</strong> Java and Bedrock discovery on the left, recent worlds on the right, and a path to open another folder.
    </td>
    <td width="50%" valign="top">
      <img src="resource/img/world_select_expand.jpg" alt="Legacy Amulet world-selection window with Bedrock worlds expanded"><br>
      <strong>Historical pre-Material expanded world browser.</strong> Installed Bedrock worlds are visible alongside recently opened Java and Bedrock worlds.
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <img src="resource/img/convert.jpg" alt="Amulet 0.6.1 conversion surface with source and destination world controls"><br>
      <strong>Historical pre-Material world conversion — 0.6.1.</strong> The source world, destination picker, progress area, and Convert action.
    </td>
    <td width="50%" valign="top">
      <img src="resource/img/edit.jpg" alt="Amulet 0.8.9 3D editor showing a multi-box selection and coordinate controls"><br>
      <strong>Historical pre-Material 3D editor — 0.8.9.</strong> Rendered terrain, multi-box selection controls, dimension and coordinates, undo/redo/save, and the editing tool strip.
    </td>
  </tr>
</table>

</details>

<details>
<summary><strong>Open the four earlier wxPython dialog baselines (2026-08-09)</strong></summary>

These captures are from the real source dialogs at commit `d62ae152`, rendered
on a hidden desktop with wxPython 4.2.5. They preserve an earlier migration
boundary. Several of these dialogs are still the real implementation behind
their Studio surface keys, so they remain useful references — but the chrome
around them has changed.

<table>
  <tr>
    <td width="50%"><img src="resource/img/preferences-runtime-baseline-20260809.png" alt="Earlier Amulet Preferences Language tab captured from the real wxPython app"><br><strong>Earlier Preferences · Language tab.</strong> Genuine native baseline; not current shell proof.</td>
    <td width="50%"><img src="resource/img/preferences-appearance-runtime-baseline-20260809.png" alt="Earlier Amulet Preferences Appearance tab captured from the real wxPython app"><br><strong>Earlier Preferences · Appearance tab.</strong> Genuine native baseline; lower controls require scrolling.</td>
  </tr>
  <tr>
    <td width="50%"><img src="resource/img/notification-history-runtime-baseline-20260809.png" alt="Earlier Amulet notification history with real notification rows"><br><strong>Earlier notification history.</strong> Genuine rows; the pictured columns predate later sizing work.</td>
    <td width="50%"><img src="resource/img/main-frame-runtime-baseline-20260809.png" alt="Earlier Amulet main frame with the first custom borderless title bar"><br><strong>Earlier main-frame baseline.</strong> Superseded twice: first by the Material shell above, then by Amulet Studio.</td>
  </tr>
</table>

</details>

<details>
<summary><strong>Open the full 0.10.47 editing montage</strong></summary>

![Amulet 0.10.47 editing montage: selection, paste transform, block operation, and 2D chunk selection](resource/img/cover.jpg)

This historical pre-Material capture contains four genuine frames showing a 3D terrain selection, paste placement and
transform controls, a block operation over selected boxes, and a top-down chunk
selection. The montage was added to the repository in 2026; the application
title inside the capture identifies the runtime as `0.10.47`.

</details>

<details>
<summary><strong>Screenshot provenance and limitations</strong></summary>

| Asset | Pixels | Repository provenance | Evidence boundary |
| --- | ---: | --- | --- |
| `cover.jpg` | 5120×2760 | Added in 2026 by the upstream README update | Real 0.10.47 montage; not a capture of the current branch. |
| `edit.jpg` | 1920×1030 | Added in 2020 and updated in 2021 | Real 0.8.9 3D editing workflow. |
| `main_menu.jpg` | 541×389 | Added with the 2020 documentation images | Real 0.6.1 main menu. |
| `world_select.jpg` | 1920×1006 | Added with the 2020 documentation images | Real legacy collapsed world browser. |
| `world_select_expand.jpg` | 1920×1026 | Added with the 2020 documentation images | Real legacy expanded world browser. |
| `about.jpg` | 550×435 | Added with the 2020 application guide | Real 0.6.1 open-world workspace. |
| `convert.jpg` | 814×490 | Added with the 2020 program guide | Real 0.6.1 conversion surface. |
| `preferences-runtime-baseline-20260809.png` | 930×720 | Captured 2026-08-09 from commit `d62ae152` on a hidden desktop | Real Preferences Language tab; native wx chrome remains a pre-M3 baseline. |
| `preferences-appearance-runtime-baseline-20260809.png` | 930×720 | Captured 2026-08-09 from commit `d62ae152` on a hidden desktop | Real Appearance tab; lower preset controls require scrolling. |
| `notification-history-runtime-baseline-20260809.png` | 1140×780 | Captured 2026-08-09 from commit `d62ae152` on a hidden desktop | Real notification history with populated rows; column sizing was corrected later. |
| `main-frame-runtime-baseline-20260809.png` | 1500×930 | Captured 2026-08-09 from commit `d7bd3875` on a hidden desktop | Real AmuletUI with the first custom borderless title bar; superseded. |
| `main-frame-material-shell-b3cbec1c-20260809.png` | 2250×1395 | Captured 2026-08-09 from exact commit `b3cbec1c4b1035dd0c2ebdc9a545266f49c257ef` on an isolated hidden desktop | Real owner-drawn Material shell with quiet startup; **superseded by Amulet Studio**. |

The repository does not currently contain an automated desktop screenshot
harness. These captures are therefore documentation artifacts, not a
pixel-regression suite, and none of them shows the current interface. UI
behavior added after the pictured versions must be verified from builds and
tests rather than inferred from these images.

</details>

## Install and update on Windows

### Recommended install

1. Download the verified [`0.10.0-dev.414 Setup.exe`](https://github.com/Ding-Ding-Projects/material-minecraft-map-editor/releases/download/0.10.0-dev.414/Setup.exe), or choose a newer version from [all releases](https://github.com/Ding-Ding-Projects/material-minecraft-map-editor/releases) after checking its exact assets.
2. Read the matching [`0.10.0-dev.414` release notes and asset list](https://github.com/Ding-Ding-Projects/material-minecraft-map-editor/releases/tag/0.10.0-dev.414).
3. Close Minecraft, back up the world you intend to edit, and run the installer.
4. Open the copied world in Amulet and make a small, reviewable change first.

> [!WARNING]
> Windows artifacts from this repository are intentionally **unsigned**. Windows
> may show an Unknown Publisher or SmartScreen warning. The project does not
> claim Authenticode verification; release integrity relies on GitHub's HTTPS
> transport, published asset digests, and the Squirrel `RELEASES` index.

<details>
<summary><strong>Squirrel.Windows release set, and other platforms</strong></summary>

The Windows workflow packages the PyInstaller application into:

- [`Setup.exe`](https://github.com/Ding-Ding-Projects/material-minecraft-map-editor/releases/download/0.10.0-dev.414/Setup.exe) — verified 0.10.0-dev.414 interactive bootstrap installer;
- [`RELEASES`](https://github.com/Ding-Ding-Projects/material-minecraft-map-editor/releases/download/0.10.0-dev.414/RELEASES) — verified 0.10.0-dev.414 Squirrel release index; and
- [`Amulet-0.10.0-dev414-full.nupkg`](https://github.com/Ding-Ding-Projects/material-minecraft-map-editor/releases/download/0.10.0-dev.414/Amulet-0.10.0-dev414-full.nupkg) — verified application payload used by install and update flows.

The release inspected while this README was written was
[`0.10.0-dev.414`](https://github.com/Ding-Ding-Projects/material-minecraft-map-editor/releases/tag/0.10.0-dev.414),
published on 2026-08-09 from `f95695f7cbadecd3272370a1fa694e9b601ab124`
with all three required assets. Later versions should
be evaluated from their own immutable release page rather than assumed to have
the same asset set.

The active delivery path is Windows-only and publishes unsigned
Squirrel.Windows assets. Source code may still be useful on other platforms,
but this repository does not currently present non-Windows installers as
supported release deliverables.

For a development install, use Python 3.11 or newer and follow the steps below.
wxPython, OpenGL, native build dependencies, and the Amulet format stack must be
available for the desktop runtime. A successful source import or unit-test run
does not by itself prove that a graphical session can create and render the wx
window on that machine.

</details>

## First editing workflow

1. **Back up the world.** Work from a copy until you have verified the result in Minecraft.
2. **Close other writers.** Do not leave the same world open in Minecraft or another editor.
3. **Open the project.** From the backstage, pick a detected world, a recent project, or browse to a folder.
4. **Get your bearings.** The navigator shows the dimension and any selection boxes; the status bar shows the head revision and whether there is unsaved work.
5. **Select narrowly.** Start with the smallest useful region and confirm its coordinates and active dimension.
6. **Apply one action.** Use the ribbon tab that owns it, or press `Ctrl+Shift+F` and search for it by name.
7. **Review before saving.** The properties pane's History tab lists what has been applied; restoring writes a new revision, so trying a restore never costs you the state you restored from.
8. **Close Amulet before Minecraft.** Reopen the edited copy in the game and inspect the affected area.

## Development and contribution

This repository follows the `0.10` development line. It is derived from the
[upstream Amulet Map Editor](https://github.com/Amulet-Team/Amulet-Map-Editor)
and carries additional Material 3, preferences, site, update, and delivery work.

### Local checkout

```powershell
git clone https://github.com/Ding-Ding-Projects/material-minecraft-map-editor.git
Set-Location material-minecraft-map-editor
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

On macOS or Linux, activate with `source .venv/bin/activate`. Resolve native
dependencies from the project metadata and your platform's canonical package
source; do not commit a virtual environment or generated build tree.

### Local checks

```powershell
py -3 -m pytest tests -q
python -m black --check --diff .
python scripts/count_lines.py
```

The interface's data layer — the surface index, the command registry, all the
surface descriptions, the shared search state, the NBT model, and the Memory
Console's content — imports without wxPython, so most of the suite runs on a
machine with no display. The handful of checks that genuinely need wx skip with
a stated reason rather than passing silently.

<details>
<summary><strong>The line counter, and what its rows mean</strong></summary>

The committed line counter is the release source of truth. It counts tracked,
line-oriented text and separates source, tests, styles/markup, generated text,
and deliberately excluded text. `project-total` is the three hand-written
project rows; `repository-grand-total` adds the generated and excluded rows.
Each row reports total/nonblank lines plus surviving `git blame` attribution as
agent, person, or unattributed, and the script fails if that arithmetic drifts.
Binary assets are not line-counted. Dependency/build directories and lockfiles
are excluded explicitly instead of disappearing into an unexplained total.

Always run the committed script rather than re-deriving a count by hand: an
ad-hoc sweep silently drops whatever matches none of its patterns, which is the
one misrepresentation the separated rows exist to prevent.

</details>

<details>
<summary><strong>Regenerating the documentation bundle and the changelog catalog</strong></summary>

Two resources in the package are generated from the repository and must be
rebuilt when their sources change:

```powershell
python scripts/build_docs_bundle.py
python scripts/generate_changelog.py
```

The first rebuilds the offline documentation bundle from every
`docs/features/*/README.md`; a stale bundle fails `tests/test_docs_browser.py`
by design, so an article added without regenerating cannot ship missing from the
in-app browser. The second rebuilds the changelog catalog from the reachable
tags, and the test session regenerates it automatically when the checkout has
moved on.

</details>

### Preview the documentation site

```powershell
python -m http.server 8000 --directory docs/site
```

Open `http://localhost:8000`. The site is plain HTML, CSS, and JavaScript with
no CDN, analytics, or third-party runtime assets. See
[`docs/site/README.md`](docs/site/README.md) for the owner-controlled hosting
contract.

<details>
<summary><strong>Build the Windows package by hand</strong></summary>

```powershell
python -m pip install build "pyinstaller~=6.18"
python -m build
python -m pip install dist/amulet_map_editor-*.whl --upgrade
python -m PyInstaller -y --distpath ./installer/dist installer/Amulet.spec
./installer/build-squirrel.ps1 -Version 0.10.0 -Architecture x64
```

The packaging script downloads pinned NuGet and Squirrel.Windows inputs, checks
the NuGet SHA-256, produces `Setup.exe`, `RELEASES`, and a full `.nupkg`, and
fails if an executable or DLL is signed. CI supplies a prior `RELEASES` and
full package only as a validated pair from the nearest semantically older
release in the same explicit channel. When supplied, the script requires and
uploads a verified current delta, while the client-facing feed advertises only
the current full package until a three-version installed-client update proof
passes. GitHub SHA-256 asset digests are checked when available. Read
[`installer/PACKAGING.md`](installer/PACKAGING.md) before changing this path.

Prefer `build.bat` and `build-installer.bat` for an ordinary build: they are the
paths a fresh machine takes, and using them is also what keeps them working.

</details>

### Contribution checklist

- Keep changes focused and preserve unrelated work.
- Add or update tests for behavior changes; run the narrow tests and the full
  `py -3 -m pytest tests -q` run where feasible.
- When you add a Studio surface, add its spec, its index entry, and its line in
  the hand-written test census in `tests/test_studio_surface_index.py`. When you
  add a search field, add it to `tests/test_studio_regex_builder_coverage.py`.
  Those lists exist so a disappearance fails rather than passing quietly;
  deleting an entry to make the suite green defeats the point.
- Update the relevant feature article under [`docs/features/`](docs/features/README.md),
  the [roadmap](ROADMAP.md), and the [handoff](HANDOFF.md) when behavior or
  verification state changes, and regenerate the documentation bundle.
- Keep screenshot captions factual: identify the captured version and never use
  a design mockup as runtime proof.
- Distinguish source inspection, automated tests, package creation, graphical
  runtime verification, and published release evidence in pull requests.
- Use [Issues](https://github.com/Ding-Ding-Projects/material-minecraft-map-editor/issues)
  for actionable defects or features and [Discussions](https://github.com/Ding-Ding-Projects/material-minecraft-map-editor/discussions)
  for design or workflow conversations.

## Verification status

| Evidence | Current status at this README revision |
| --- | --- |
| Amulet Studio interface | Source and automated-test claims only. The surface index, the spec registry, the ribbon definition, the search behaviour, the token values, the NBT model, the Memory Console content, and the accessibility contract are covered by tests; **no runtime capture of the interface exists**. |
| Tracked desktop captures | Twelve genuine images inspected: seven historical workflow captures, four earlier wxPython runtime baselines, and one exact-commit Material shell capture. All predate Amulet Studio. |
| Preference and regex behavior | Covered by repository unit tests, including bounded persistence, plain/regex matching, invalid patterns, and capture groups. |
| Scheduled-settings behavior | Covered by model and UI-contract tests for persistence, validation, precedence, weekday/date/time boundaries, reordering, and bilingual UI strings. |
| Squirrel update bridge | Covered by wx-independent tests for canonical build/manual/release tag publication, explicit-channel discovery across five bounded inventory pages, one shared check deadline, exact route/status/content validation on every page, official progress/JSON command parsing with bounded stdout and stderr, strict CRLF/LF/CR records, exact post-stage version proof within one 900-second apply-and-check deadline, immediate-layout updater discovery, and the guarded process-start-and-wait restart transaction. |
| Windows release | The inspected `0.10.0-dev.414` release is non-draft and contains `Setup.exe`, `RELEASES`, and `Amulet-0.10.0-dev414-full.nupkg`. |
| Live project-site deployment | The site source is published from `docs/site/`; a verified owner-hosted URL of its own is not claimed here. |

## Project links

- [Material modernization repository](https://github.com/Ding-Ding-Projects/material-minecraft-map-editor)
- [Latest release](https://github.com/Ding-Ding-Projects/material-minecraft-map-editor/releases/latest)
- [Build workflows](https://github.com/Ding-Ding-Projects/material-minecraft-map-editor/actions)
- [Material 3 site source](docs/site/index.html)
- [Feature documentation](docs/features/README.md)
- [Desktop documentation](amulet_map_editor/readme.md)
- [Roadmap](ROADMAP.md)
- [Handoff](HANDOFF.md)
- [Upstream Amulet Map Editor](https://github.com/Amulet-Team/Amulet-Map-Editor)
- [Official Amulet website](https://www.amuletmc.com/)

<details>
<summary><strong>Repository-local working agreement</strong></summary>

This repository carries a sanitized mirror of its shared working agreement in
[`AGENTS.md`](AGENTS.md). In short: preserve user work, keep changes reversible,
apply accessible Material Design 3 patterns consistently, keep documentation
and CI claims truthful, distinguish static checks from actual runtime and
release evidence, and never expose credentials. The canonical shared agreement,
repository-local rules, and higher-priority safety requirements take precedence
over this summary.

</details>
