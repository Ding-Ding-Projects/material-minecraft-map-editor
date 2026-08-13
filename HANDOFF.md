# Handoff

## Current state

There are two working applications in this repository, built against the
same Python core.

**The Electron application** (`electron/`, `docs/site/`) is now what CI
publishes as the GitHub release. `build-electron-windows.yml` is the only
workflow that creates one; `build-windows.yml` (the wxPython/PyInstaller
build) still runs on every push and reports its own test results, but its
`publish:` job is gone — it is an ordinary, cancellable, non-releasing check
now (`6c44bbe8`).

The Electron shell hosts the Amulet Studio design
(`docs/site/studio.html`) inside a frameless `BrowserWindow`, driving a
Python sidecar process over a versioned, newline-delimited JSON protocol on
stdio. `amulet_map_editor/api/sidecar/methods.py` plus nine grouped modules
(`analyze_methods.py`, `edit_methods.py`, `entity_methods.py`,
`mesh_methods.py`, `security_methods.py`, `selection_methods.py`,
`surface_methods.py`, `terrain_methods.py`, `world_methods.py`) register
roughly ninety real methods — none of them stubs. Both the backstage
(`docs/site/studio-backstage.js`) and the workspace
(`docs/site/studio-workspace.js`, mounted into `studio.html`'s
`#studio-workspace` element by `d4ab1861`) are actually mounted into the
running page, not merely built and unit-tested in isolation.

**The wxPython application** (`amulet_map_editor/api/wx/`,
`amulet_map_editor/api/studio/`) is the original, longer-running
implementation of most of the same feature set, including the 3D viewport,
which stays on PyOpenGL — porting it is out of scope for this migration
while its own open performance defect (reported around 3 fps) is unresolved.
It remains the larger of the two applications by surface area and is not
being deleted; CI simply no longer publishes it as a release.

## The write path

`world.fill`, `world.replace`, `world.undo`, `world.redo`, `world.save`,
`selection.copy`/`cut`/`paste`/`delete`, `structure.export`/`import`,
`chunk.create`/`delete`/`prune`, terrain flatten/sea-level/repaint,
`entities.place`/`remove`, and `data.level_write`/`data.game_rules_write`
are all real sidecar methods calling the same amulet-core APIs the wx
application's stock plugins use, wired all the way to real ribbon controls
in `docs/site/studio-workspace.js`. Every one requires `confirmed: true`,
and on the renderer side that flag is only ever set after
`docs/site/confirm-gate.js`'s real two-key, full-slider gate finishes.
Nothing reaches disk until `world.save`.

Getting from "the method exists and is tested" to "a ribbon button actually
calls it" was its own piece of work, done in `4c887bf9`: five methods
(`entities.place`, `entities.remove`, `data.level_write`,
`data.game_rules_write`, and `sea_level`'s drain mode) were real and tested
against a live sidecar process for a while with no edit-panel fields to
drive them from — the largest single "built, tested, unreachable" gap the
project had.

## The 3D viewport

WebGL2, fed by the **unmodified Python mesher**. What exists:

- **Batched chunk streaming.** `viewport.chunk_mesh_batch` kicks a
  background thread and returns `"pending"` immediately; combining every
  chunk in a batch into one transport file cut a measured ~294 ms of I/O for
  25 chunks down to ~47 ms (`c6eee90a`, `benchmark_mesh.py`).
- **Frustum culling and back-to-front chunk ordering** for correct
  translucency (`6d49b2aa`).
- **A selection box with draggable handles**, a JS port of `handles.py`'s
  face/corner drag geometry, plus **click-to-pick ray casting**
  (`viewport-picking.js`: cursor → ray → DDA voxel march) against a real
  per-sub-chunk occupancy bitset — 512 bytes, one bit per block — that rides
  in the same `viewport.chunk_mesh_batch` response as the mesh (`21143469`).
  Before that, picking could only test a ray against the reference grid's
  `y = 0` plane; a per-step IPC round trip was never viable, since a DDA
  march takes hundreds of steps per ray on pointer move.
- **Camera input with a keyboard path**, streaming at chunk radius 3, and a
  reference grid.

## What the ribbon does not do yet

`docs/site/studio-workspace.js` declares roughly 150 ribbon buttons. Call
sites reference a real `actions.*` handler for roughly a third of them; the
rest are built with `run: null` and render **permanently disabled with an
explicit reason**, both in their title and in a properties-pane reason line
— never silently inert. The stated reasons are, plainly: this build has no
terrain generator, no shape library, no portable biome table, and no
light-recalculation API, so brushes, most structure-file operations, NBT
search, redstone tracing, and most of the design's twelve editing surfaces
have nothing to call. Outside Electron entirely (no
`window.mmweDesktop`), every command — including purely local ones like tab
switching — shows a desktop-only reason instead, so the ribbon does not look
half-broken in a plain browser tab.

## Verified on this machine

**Command run:** `py -3 -m pytest tests -q` from the repository root.

The Studio (wxPython) tests import without wx by design for their data
layer — the surface index, the command registry, every surface description,
the shared search state, the NBT model, and the Memory Console's content —
and skip cleanly, with the reason stated, wherever a check genuinely needs a
display.

**Two generated resources must be current for the suite to pass:**

```powershell
python scripts/build_docs_bundle.py     # feature articles bundled for the in-app browser
python scripts/generate_changelog.py    # tagged-release catalog
```

## Documentation

`docs/features/` holds one article per feature area — the wxPython
interface, the Electron application, settings, safety and history, builds
and delivery. Articles named `electron-*` are always specifically about the
Electron application; an article with no such prefix predates the Electron
work and is describing the wxPython app. `docs/features/README.md` is the
index; `docs/features/electron-migration/README.md` is the honest,
evidence-gathered status of the migration itself, including exactly which
ribbon commands are wired and which are not.

## The completeness inventory

`docs/features/completeness-inventory/README.md` is the per-feature register
of what is delivered, enforced fail-closed by
`tests/test_feature_completeness_inventory.py`: a row may not regress from
complete to incomplete. It is a statement about the rows a person has typed
into it, not a claim that either application is finished. It has already
caught real defects by being checked rather than trusted — rows it once
marked incomplete turned out to be features that existed only on the
documentation site, or an engine with no surface reachable from the running
application.

## Things that cost real time, so nobody pays twice

- **`Page.captureScreenshot` hangs indefinitely against a WebGL2 canvas**,
  with no error and no timeout. Read the canvas with `toDataURL()` instead —
  and read it in the **same frame as the draw**, because the drawing buffer
  is cleared after compositing unless `preserveDrawingBuffer` is set. A
  capture taken one tick late returns a blank image indistinguishable from a
  viewport that drew nothing.
- **Pixel variance is not proof.** The reference grid alone gives a colour
  range of 245, which is enough to satisfy any "is something drawn" check.
  To prove a specific thing is drawn, capture with it and without it and
  compare bytes.
- **The streaming viewport increments `chunkCount`, not `vertexCount`.** The
  latter belongs to the legacy single-mesh path. Reading the wrong one
  reports zero geometry against an application streaming perfectly.
- **Positive pitch looks down.** From `mat4View`, forward is
  `[sin(yaw)cos(pitch), -sin(pitch), -cos(yaw)cos(pitch)]`, so yaw zero looks
  toward `-Z`. Getting the sign backwards aims the camera at empty sky, which
  looks exactly like a world that failed to load.
- **A capture script must redirect every profile store, not just
  `CONFIG_DIR`.** `AMULET_RECENTS_DIR` and `AMULET_HISTORY_DIR` are separate
  on purpose, and the redirect must happen **before the first application
  import**, because the config module reads the environment at import time.
- **`electron-builder.yml`'s `files` glob has bitten the packaged build
  twice**, both times invisibly to a dev run: once by omitting
  `sidecar-client.js` (the packaged app crashed before creating a window),
  and once by never bundling `amulet_map_editor/` at all while `main.js`
  computed the sidecar's working directory as a path *inside* `app.asar` — a
  virtual archive no interpreter can enter, so every sidecar call failed
  with `sidecar_unavailable` while the window opened and rendered normally.
  `scripts/accept_electron_app.js` exists because of exactly this: it drives
  the **packaged executable**, never `electron .`, over the DevTools
  protocol. A dev run proves the code; only the packaged artifact proves the
  product.
- **An unanchored `.gitignore` pattern matches at any depth.** A line
  written for the documentation site's own test-only `package-lock.json`
  (`docs/site/package-lock.json`) silently swallowed the Electron app's root
  lockfile too, which meant `setup-node`'s npm cache and `npm ci` had
  nothing to key off and the release workflow could not start (`14eafe58`).
- **A crashing child process looks exactly like a slow one.** The converter
  sandbox reported a crashed adapter — one that dies before it can send
  anything, from a spawn-platform unpickling failure, an OS kill, or an
  import error — as a `timeout`, because silence and slowness are
  indistinguishable to a poll. Fixed in `20d7a324` by distinguishing "no
  response yet" from "the process is gone."

## Next

1. Wire more of the ribbon's ~150 buttons to real methods as the missing
   backends (a terrain generator, a shape library, a portable biome table, a
   light-recalculation API) get built — see `docs/features/electron-migration/README.md`
   for the exact list of what each disabled command is waiting on.
2. Level-of-detail and depth sorting in the viewport, once there is a large
   real world to measure against rather than a fixture chunk.
3. Hosted delta publication and a three-version installed-client update
   proof, before delta delivery is advertised to Electron-app clients.
