# The Electron migration: what has moved, and what has not

This article is the honest status of the piece-by-piece migration described
in `HANDOFF.md`. It is written from evidence gathered against the real,
running artifacts, and it says plainly which phases are done and which are
not, because a migration reported as finished while it still leaves out most
of the surface would be a false report.

## The one-sentence status

**CI now publishes the Electron installer, and it is the wired product, not
a shell around a disconnected renderer.** `build-electron-windows.yml` is the
only workflow that creates a GitHub release; `build-windows.yml` (the
wxPython/PyInstaller build) still builds and reports its own test results on
every push but no longer publishes anything. The Electron shell hosts the
real Amulet Studio interface — backstage and a seventeen-tab ribbon workspace
— against a Python sidecar reached over a versioned stdio protocol with
roughly ninety registered methods. The write path is real: fill, replace,
undo, redo, save, copy/cut/paste, structure import/export, chunk
create/delete/prune, terrain flatten/sea-level/repaint, entity place/remove,
and `level.dat`/game-rule writes all go through the sidecar's real core
calls, gated behind the project's real destructive-action confirm gate. The
3D viewport is WebGL2, meshed by the **unmodified Python mesher**, with
camera input, batched chunk streaming, frustum culling, a selection box with
draggable handles, and click-to-pick ray casting against a real per-block
occupancy bitset. The wxPython application still exists as a second working
implementation of much of the same feature set, but it is no longer what CI
ships to a user who downloads a release.

Roughly a third of the ribbon's ~150 buttons call a real method today; the
rest render permanently disabled with a stated reason (see "What is
deliberately not wired" below) rather than doing nothing silently.

## What moved, and the evidence for each phase

- **Phase 0 — freeze the contracts.** The completeness inventory
  (`docs/features/completeness-inventory/README.md`,
  `tests/test_feature_completeness_inventory.py`) is the migration checklist:
  a row may not regress from complete to incomplete because of a port.
- **Phase 1 — separate the core from wx.** Done, and load-bearing for
  everything after it. `docs/features/core-boundary/README.md` documents the
  explicit, test-guarded boundary: every module under `amulet_map_editor/api/`
  that does not import `wx` is portable, and
  `amulet_map_editor/api/core_boundary.py` plus its guard test fail closed if
  a `wx` import ever crosses that line. That boundary caught a real defect
  mid-migration: `security_methods.py` pulled in the authenticator, which
  pulled in `forge_accounts.py` for two names, which imports `wx` at module
  scope to define a dialog. The credential-vault helpers were split out of
  `forge_accounts.py` so the sidecar's account/security methods no longer need
  a GUI toolkit at all (`599018bc`).
- **Phase 2 — a process boundary.** `amulet_map_editor/api/sidecar/` is a
  versioned, newline-delimited JSON stdio server
  (`protocol.py`, `server.py`, `__main__.py`) whose methods live in
  `methods.py` plus nine grouped modules: `analyze_methods.py`,
  `edit_methods.py`, `entity_methods.py`, `mesh_methods.py`,
  `security_methods.py`, `selection_methods.py`, `surface_methods.py`,
  `terrain_methods.py`, `world_methods.py`. Together they register roughly
  ninety methods, none of them stubs — every one calls the same core module a
  wx surface already calls (`extract_structure`, `BaseLevel.paste`,
  `delete_chunk`, `put_chunk`, and so on), so the sidecar and the wx app
  cannot disagree about what an operation means. See
  [the sidecar article](../sidecar/README.md) for the protocol itself and
  the full method table.
- **Phase 3 — port a real user-facing surface.** Both halves of Amulet
  Studio are mounted, not just built and tested in isolation:
  - **Backstage** (`docs/site/studio-backstage.js`) is the application's
    start screen against the real sidecar.
  - **The workspace** (`docs/site/studio-workspace.js`, ~150 KB, mounted
    into `studio.html`'s `#studio-workspace` element by `d4ab1861`) builds
    the seventeen-tab ribbon, the breadcrumb, the navigator, the tabbed
    properties pane, and the status bar around the existing WebGL2 viewport
    (`viewport-panel.js`, `viewport-webgl.js`, `viewport-overlays.js`,
    `viewport-picking.js`, `viewport-handles.js`, `viewport-occupancy.js`).
    Getting this far cost a real defect of its own: the workspace module had
    been fully built and unit-tested against `jsdom` for several commits
    before anyone wired its mount point into the actual `studio.html` page —
    `#workspace-view` stayed a static placeholder the whole time, so nothing
    in the shipped page ever ran it until `d4ab1861` linked the stylesheet
    and inserted the real mount element in the one script order that works
    (`studio-workspace.js` before `viewport-panel.js`, because the latter's
    one-shot `DOMContentLoaded` listener looks for `#viewport-canvas`, which
    only the former creates).
  - The properties pane's edit fields for `entities.place`/`entities.remove`,
    `data.level_write`, `data.game_rules_write`, and `sea_level`'s drain mode
    were the largest remaining "tested against a live sidecar process, wired
    to nothing" gap in the project until `4c887bf9` added the missing
    entity-type, sea-level-mode, `level.dat`, and game-rule inputs the ribbon
    buttons needed to actually call those five already-real methods.
- **Phase 4 — the 3D viewport.** Out of scope for the wxPython port
  (`HANDOFF.md` says its PyOpenGL implementation must not be touched while
  its own open performance defect is unresolved), but **not** out of scope
  for Electron: the WebGL2 viewport is a from-scratch renderer fed by the
  unmodified Python mesher, described in full below.
- **Phase 5 — packaging and publication.** Done and live.
  `build-electron-windows.yml` builds the unsigned Squirrel.Windows installer
  with `npm run electron:dist`, verifies `Setup.exe` reports `NotSigned` and
  that `RELEASES` names the produced `.nupkg`, and publishes the GitHub
  release. `build-windows.yml` was retargeted to stop publishing
  (`6c44bbe8`); it keeps building and testing the wxPython/PyInstaller app on
  every push as an ordinary, cancellable, non-releasing check.

## The write path

`amulet_map_editor/api/sidecar/edit_methods.py`,
`selection_methods.py`, `entity_methods.py`, and `terrain_methods.py`
register the operations that actually change a world:

| Group | Methods |
| --- | --- |
| Blocks | `world.fill`, `world.replace`, `world.undo`, `world.redo`, `world.save` |
| Selection | `selection.copy`, `selection.cut`, `selection.paste`, `selection.delete`, `selection.clipboard_status` |
| Structures | `structure.export`, `structure.import` |
| Chunks | `chunk.create`, `chunk.delete`, `chunk.prune` |
| Terrain | flatten, sea-level (including the drain mode), repaint |
| Entities | `entities.place`, `entities.remove` |
| World data | `data.level_write`, `data.game_rules_write` |

Every one of these requires an explicit `confirmed: true` from the caller,
and on the renderer side that flag is only ever `true` after
`docs/site/confirm-gate.js`'s real two-key, full-slider destructive-action
gate finishes — never a default the bridge or the panel sets on the caller's
behalf. Nothing reaches disk until `world.save` is called; `world.undo` and
`world.redo` operate on the same per-project history every other write does.
Every ribbon control that calls one of these states why it is disabled (no
world open, no selection entered, nothing to undo/redo, no unsaved changes)
rather than sitting there inert.

See [Electron world editing](../electron-editing/README.md) for the
per-method detail and [selection handles](../selection-handles/README.md) and
[the viewport overlays article](../electron-viewport-overlays/README.md) for
how a selection is made in the first place.

## The 3D viewport

WebGL2, fed by chunk meshes the **unmodified** Python mesher produces —
`docs/features/electron-viewport-overlays/README.md` and
`docs/features/viewport/README.md` cover the rendering contract in depth.
What is real today:

- **Batched streaming.** `viewport.chunk_mesh_batch` metadata a background
  thread and returns `"pending"` immediately, the same pattern
  `world.open`/`viewport.prepare` use, so a large batch never blocks an
  unrelated call sitting behind it on the sidecar's single stdio channel.
  `benchmark_mesh.py` measured the reason this batching exists: meshing one
  chunk is cheap (4–5 ms), but the earlier one-temp-file-per-chunk transport
  cost ~294 ms of I/O alone for 25 chunks against ~47 ms once every chunk in
  the batch shares one combined file (`c6eee90a`).
- **Frustum culling and back-to-front chunk ordering** for correct
  translucency blending (`6d49b2aa`).
- **A selection box with grabbable handles**, ported from `handles.py`'s
  face/corner geometry and drag constraints so the Electron and wx editors
  cannot disagree about how a box resizes (`viewport-handles.js`, pure
  functions, tested directly against known camera matrices with no GPU
  involved) — plus a reference chunk grid.
- **Click-to-pick ray casting** (`viewport-picking.js`): cursor to ray, a DDA
  voxel march, first solid block and entered face. This is backed by a real
  per-sub-chunk solid/non-solid occupancy bitset — 512 bytes, one bit per
  block — that rides in the *same* `viewport.chunk_mesh_batch` response as
  the mesh (`21143469`). Before this, `setSolidTest` could only test a ray
  against the reference grid's own `y=0` plane, because the sidecar streamed
  meshes with no "what block is at x,y,z" call, and a per-step IPC round trip
  was never viable — a DDA march takes hundreds of steps per ray on pointer
  move.
- **Camera input with a keyboard path**, streaming chunks at a radius of 3.

## What is deliberately not wired

`docs/site/studio-workspace.js` declares roughly 150 ribbon buttons; call
sites reference `actions.*` (a real sidecar or local UI action) for
somewhere around a third of them. Every other one is built with `run: null`,
which the module renders as **permanently disabled with an explicit reason**
in its title and in a properties-pane reason line — never silently inert.
The commonest stated reasons, quoted from the source comment at the top of
`studio-workspace.js`, are that this build has no implementation yet for
brushes, structure-file editing beyond the current import/export pair, NBT
search, redstone tracing, and most of the design's twelve editing surfaces —
in short, no terrain generator, no shape library, no portable biome table,
and no light-recalculation API exist yet to back the buttons that would call
them. Outside Electron entirely (a browser tab with no `window.mmweDesktop`),
every command — including the purely local ones like tab switching — shows a
desktop-only reason instead, because a ribbon whose Undo/Redo work but
nothing else looks broken.

The wxPython application remains a second, independently maintained
implementation of much of this same feature set (see
`docs/features/editing-tools/README.md` and siblings), built years earlier
against PyOpenGL. Nothing in this migration deletes it; CI simply no longer
publishes it as a release artifact.

## Verified against the packaged artifact, not the dev tree

Every check that only runs `electron .` on the development tree sees the
Python package sitting on disk unpacked. Two real defects existed **only**
in the packaged layout and made the application look perfect while doing
nothing:

- `electron-builder.yml` did not bundle `amulet_map_editor/` at all, and
  `main.js` computed the sidecar's working directory as a path **inside**
  `app.asar` — a virtual archive no interpreter can enter. In every packaged
  build, every preference write, language switch, catalog lookup, and world
  open failed with `sidecar_unavailable` while the window opened and the
  interface rendered normally.
- Earlier, `sidecar-client.js` was left out of the `files` glob, so the
  packaged app crashed before it ever created a window.

`scripts/accept_electron_app.js` is the run that exists because of exactly
this lesson: it launches the **packaged executable**, not `electron .`,
headlessly over the DevTools protocol, and checks eleven capabilities
without stopping at the first failure. See
[the acceptance-run article](../electron-acceptance/README.md) for the full
list and how to run it. A dev run proves the code; only the packaged
artifact proves the product.

## How to run and build the Electron app today

```sh
npm install                                          # once, from the repository root
npm run electron:dev                                 # launches the shell (visible window), spawns the sidecar
node scripts/accept_electron_app.js                   # the packaged-artifact acceptance run
node scripts/verify_sidecar_client.js                 # sidecar-client.js vs the real Python process
node scripts/capture_electron_sidecar_roundtrip.js     # renderer -> sidecar -> restart round trip
```

```bat
build-electron.bat /s             :: bootstrap Node, npm install
build-electron-installer.bat /s   :: package the unsigned Squirrel.Windows installer
```

`build-electron-installer.bat /s` refuses to proceed if
`electron/electron-builder.yml` enables any signing control, then packages
and verifies the produced `Setup.exe` carries no Authenticode signer
certificate, writing `Setup.exe`, `RELEASES`, and the full `.nupkg` under
`dist/electron/squirrel-windows/`.

## Related reading

- [The core/wx boundary](../core-boundary/README.md) — what Phase 1 drew a
  line around
- [The Python sidecar](../sidecar/README.md) — the protocol itself, its
  message shapes, error codes, and the full method table
- [Electron world editing](../electron-editing/README.md) — the write-path
  methods in per-method detail
- [Electron world access](../electron-world-access/README.md) — the
  read-only open/inspect/close path the write path builds on
- [Viewport overlays](../electron-viewport-overlays/README.md) — the
  selection box, handles, and grid
- [Electron acceptance run](../electron-acceptance/README.md) — the
  eleven-capability packaged-artifact check
- [The capture matrix](../capture-matrix/README.md) — how screenshots are
  taken and verified across the project
- [Completeness inventory](../completeness-inventory/README.md) — the
  migration checklist this row reports into
