# Feature documentation index

Every article records behaviour, configuration, failure modes, security
boundaries, and verification evidence, and ends with a short list of related
reading. Articles are bundled into the offline documentation browser and into
the Memory Console's own reader, so a reader never has to be online.

If you are new to the interface, start with
[project shell](project-shell/README.md).

## The interface

- [Project shell](project-shell/README.md) — the two views the application is
  built from
- [Backstage](backstage/README.md) — starting, opening, inspecting, converting
- [Ribbon](ribbon/README.md) — the seventeen command tabs
- [Navigator](navigator/README.md) — dimensions and selection boxes
- [Viewport](viewport/README.md) — the rendered world and its overlays
- [Properties pane](properties-pane/README.md) — the tabbed inspector
- [Spec renderer](spec-renderer/README.md) — how most windows are described,
  and how to add one
- [Material application shell](material-shell/README.md) — the frame and its
  shared token layer

## Editing a world

- [Editing tools](editing-tools/README.md)
- [Grab handles on the selection box](selection-handles/README.md) — dragging
  the box itself, and the keyboard routes that do the same
- [Where a pasted copy lands](paste-anchor/README.md) — what the Position
  numbers name, and the box the blocks will fill
- [MCEdit2 tool set](mcedit2-tools/README.md)
- [Terrain tools](terrain/README.md)
- [Build tools](build/README.md)
- [Entities and world data](entities-and-data/README.md)
- [NBT editor](nbt-editor/README.md)
- [Texture previews](texture-previews/README.md)

## Understanding a world

- [Analysis tools](analysis/README.md)
- [Redstone and mechanics](redstone/README.md)
- [World generation tools](worldgen/README.md)
- [Panels and views](panels/README.md)
- [Automation](automation/README.md)

## Finding things

- [Search, regular expressions, and the command palette](search-and-regex/README.md)
- [Command palette](command-palette/README.md)
- [Searchable menus and dropdowns](searchable-menus/README.md)
- [Material command menu contract](material-menu/README.md) — the app-owned
  popup behind the fallback shell's command bar
- [Tabs and groups](tab-groups/README.md)
- [Base tab runtime contract](base-tab-runtime/README.md) — the underlying
  `BaseTab` lifecycle every tab implements
- [Offline documentation](offline-documentation/README.md)
- [Memory Console](memory-console/README.md)

## Settings and presentation

- [Settings and appearance](settings/README.md)
- [Appearance](appearance/README.md)
- [Appearance presets](appearance-presets/README.md)
- [Language modes and funny levels](language-modes/README.md)
- [School mode](school-mode/README.md)
- [Scheduled settings](scheduled-settings/README.md)
- [Optional narrator](tts-narrator/README.md)
- [Per-surface locks](item-locks/README.md)
- [Built-in authenticator](authenticator/README.md)

## Safety, history, and getting data out

- [Per-project version history](project-history/README.md)
- [Local version history](local-history/README.md)
- [Destructive-action gate](destructive-gate/README.md)
- [Bulk actions](bulk-actions/README.md)
- [Exports](exports/README.md)
- [File converter](file-converter/README.md) — a local, sandboxed converter
  for standalone structures, JSON, and images
- [External editor](external-editor/README.md)
- [Notification centre](notification-centre/README.md)
- [Non-blocking error reporting](non-blocking-error-reporting/README.md)
- [In-app progress](progress-overlay/README.md) — the linear indicator that
  replaced every modal progress dialog

## Builds and delivery

- [Build scripts](build-scripts/README.md)
- [The capture matrix](capture-matrix/README.md) — how the README's screenshots
  are taken, including the menus and overlays a page capture cannot see
- [Release delivery contract](release-delivery/README.md)
- [Release code name](release-code-name/README.md)
- [Updater](updater/README.md)
- [Changelog](changelog/README.md)
- [Dim-sum surprise](dim-sum-surprise/README.md)
- [The core/wx boundary](core-boundary/README.md) — which modules are already
  portable off wxPython, and how that feeds the Electron migration
- [The Python sidecar](sidecar/README.md) — the versioned stdio protocol that
  lets a non-wx host (Electron's main process, or a test) drive the core
- [The Electron migration](electron-migration/README.md) — what has actually
  moved off wxPython so far (not much yet), verified against real running
  artifacts rather than claimed from source
- [Amulet Studio backstage (Electron)](electron-studio-backstage/README.md) —
  the desktop shell's start screen, mounted against the real sidecar
- [Amulet Studio workspace (Electron)](electron-studio-workspace/README.md) —
  the ribbon, breadcrumb, navigator, properties pane and status bar around
  the working 3D viewport, with every ribbon command either wired to the
  real sidecar write path or disabled with an explicit reason
