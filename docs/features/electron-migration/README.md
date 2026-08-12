# The Electron migration: what has moved, and what has not

This article is the honest status of the piece-by-piece migration described
in `HANDOFF.md` ("Converting to an Electron application, piece by piece"). It
is written from evidence gathered against the real, running artifacts — not
from source reading — and it says plainly which phases are done and which are
not, because a migration reported as finished while the shipping product is
still the wxPython app would be a false report.

## The one-sentence status

**The wxPython desktop application remains the shipping product.** An
Electron shell exists, launches, and renders the real interface. A Python
sidecar process exists and answers real requests over its versioned stdio
protocol. **The two are now connected**: `electron/main.js` spawns and
supervises the sidecar, `electron/preload.js` exposes a narrow
`window.mmweDesktop.sidecar.call(method, params)` bridge, and the site's own
`theme` setting round-trips through it for real (`docs/site/electron-bridge.js`).
Nothing else the Electron shell does reaches the sidecar yet, and the wx app
still talks to its core modules in-process exactly as before — this lane
connected one process pair and one real setting, not the whole surface.

## What has moved (Phases 0–2, partially)

- **Phase 0 — freeze the contracts.** The completeness inventory
  (`docs/features/completeness-inventory/README.md`,
  `tests/test_feature_completeness_inventory.py`) is the migration checklist:
  a row may not regress from complete to incomplete because of a port. This
  row is itself governed by that same guard.
- **Phase 1 — separate the core from wx.** Done, and load-bearing for
  everything after it. `docs/features/core-boundary/README.md` documents the
  explicit, test-guarded boundary: every module under
  `amulet_map_editor/api/` that does not import `wx` is portable, and
  `amulet_map_editor/api/core_boundary.py` plus its guard test fail closed if
  a `wx` import ever crosses that line.
- **Phase 2 — a process boundary, not a rewrite.** The Python half is real
  and verified. `amulet_map_editor/api/sidecar/` (`protocol.py`,
  `methods.py`, `server.py`, `__main__.py`) is a versioned, newline-delimited
  JSON stdio server. It was driven end to end for this article — real child
  process, real stdin/stdout, real preferences file — and answered correctly:
  - `protocol.ping` → `{"ok": true}`
  - `language.list` → the eighteen real bundled language IDs
  - `preferences.read` / `preferences.write` → the real preferences record,
    round-tripped (write `theme: "dark"`, read it back as `"dark"`); an
    unknown field is refused with `invalid_params` rather than silently
    accepted
  - `language.set` / `language.get` → round-tripped
  - `converter.formats` → the real seventeen-adapter list from the file
    converter, each with its lossiness and metadata disclosure
  - an unrecognised method name → a structured `unknown_method` error, not a
    crash
  - See `docs/features/sidecar/README.md` for the protocol itself.
  - **The Electron side of this boundary now exists.** `electron/main.js`
    spawns `python -m amulet_map_editor.api.sidecar` (trying `py -3.11`,
    `py -3`, `python3.11`, `python3`, then `python` in order), restarts it if
    it dies while the app is running, and kills it from
    `app.on("before-quit")` so nothing is orphaned. `electron/preload.js`
    exposes exactly `window.mmweDesktop.sidecar.call(method, params)` —
    never `ipcRenderer` itself, never a filesystem or child-process escape
    hatch — which forwards over one IPC handle
    (`ipcMain.handle("sidecar:call", ...)`) to `electron/sidecar-client.js`,
    the module that owns request/response correlation, per-call timeouts,
    and the "unavailable" error a caller gets instead of a hang when the
    child is not running. `docs/site/electron-bridge.js` is the first real
    call site: when the page is running inside Electron, the site's own
    `theme` setting reads from `preferences.read` on load and writes through
    `preferences.write` on every change, through the *exact* `settings.set()`
    the settings-panel UI itself calls — not a bypassed direct call.

    Verified for this update, against the real artifacts and a throwaway
    `CONFIG_DIR`, never a stub:
    - `node scripts/verify_sidecar_client.js` spawns the real Python child
      through `electron/sidecar-client.js` (no Electron involved) and
      round-trips `protocol.ping`, `preferences.write`/`preferences.read`
      (`theme: "dark"` written and read back), an unknown method reporting
      `unknown_method` rather than throwing, and a call after `stop()`
      reporting `sidecar_unavailable` rather than hanging.
    - `node scripts/capture_electron_sidecar_roundtrip.js` launches the real
      built Electron shell headlessly with `--remote-debugging-port`, drives
      it over the Chrome DevTools protocol, and proves the *whole* chain in
      two passes: (1) calling `window.AmuletSite.settings.set('theme', 'dark')`
      in the renderer, then reading `preferences.read` directly through the
      bridge and confirming Python's own preferences file shows
      `theme: "dark"` — the renderer's setting change genuinely reached the
      Python process; (2) killing that Electron instance and launching a
      *second* one against the same `CONFIG_DIR`, confirming
      `window.AmuletSite.settings.get('theme')` reads back `"dark"` on
      startup — the value survived a real restart of both processes, not an
      in-memory variable. A screenshot after the write
      (`docs/huishots/electron/electron-sidecar-roundtrip-dark.png`,
      129,300 bytes, read back and confirmed a real PNG) is the visual
      evidence for pass 1.
    - `tests/test_electron_sidecar_bridge.py` runs the first script from
      pytest and adds static wiring guards (main.js actually calls
      `sidecar.start()`/`sidecar.stop()` and registers the IPC handle;
      preload.js exposes no wider surface; the site actually includes and
      calls the bridge script).

    What was missing at the time this section was first written: only
    `theme` was wired end to end. That has since widened — every writable
    preference field round-trips (`docs/site/electron-bridge.js`'s
    `FIELD_MAP`), and `converter.formats`, `changelog.entries`,
    `docs.articles` and `dimsum.draw` each have a real call site too.

    **The write path now has a real call site as well.**
    `docs/site/electron-bridge.js` exposes `fillSelection`,
    `replaceInSelection`, `undoEdit`, `redoEdit` and `saveWorld`, each a
    genuine `bridge.call("world.fill" | "world.replace" | "world.undo" |
    "world.redo" | "world.save", ...)` against the sidecar. `docs/site/
    viewport-panel.js` is the caller: a plain toolbar next to the viewport
    (six selection-point fields, a fill block field, find/replace block
    fields, and Fill/Replace/Undo/Redo/Save buttons) that calls those
    methods against the world the viewport already has open and the
    selection currently entered. Fill and replace go through the project's
    real destructive-action confirm gate (`docs/site/confirm-gate.js`) —
    the `confirmed` flag the bridge sends is only ever `true` after that
    gate's two keys and slider finish, never a default the bridge or the
    panel sets on the caller's behalf. Every control states why it is
    disabled (no world open, no selection entered, nothing to undo/redo,
    no unsaved changes) instead of sitting there inert, and an
    unsaved-changes line is shown, not just tracked internally.

    **This was written against the sidecar methods this lane's task agreed
    with the parallel lane building `world.fill`/`world.replace`/
    `world.undo`/`world.redo`/`world.save` — the exact method names and
    parameter shapes (`world_id`, `dimension`, `point1`, `point2`, `block`
    / `find_block`+`replace_block`, `confirmed`) that lane's task brief
    specified.** If those methods have not landed in
    `amulet_map_editor/api/sidecar/methods.py` yet, every one of these
    calls fails honestly with `world.fill is not available yet.` (etc.) in
    the panel's status line rather than crashing or silently doing nothing
    — `tests/test_electron_sidecar_bridge.py` covers the static wiring
    (the call sites exist, the confirm gate is used, every disabled
    control has a reason) but does not itself prove the sidecar methods
    exist; that proof belongs to the sidecar lane's own tests.

## What exists but is not wired to anything (the shell)

`electron/` is a real, running Electron application shell:

- `electron/main.js` creates a frameless `BrowserWindow` (no OS title bar —
  this product draws its own), restores window geometry across restarts, and
  loads `docs/site/index.html` — the same complete Material 3 renderer the
  documentation site already ships — with `loadFile`, unmodified.
- `electron/preload.js` runs with `contextIsolation: true`,
  `nodeIntegration: false`, and `sandbox: true`, exposing exactly one narrow
  bridge object (`window.mmweDesktop`) for window-chrome actions and the app
  version. It exposes no sidecar access, no filesystem, no `ipcRenderer`.
- `electron/electron-builder.yml` targets Squirrel.Windows with signing
  explicitly and permanently disabled at every relevant key
  (`forceCodeSigning`, `signExecutable`, `signAndEditExecutable`,
  `signDlls`). The packaging pass that actually produces `Setup.exe`,
  `RELEASES`, and the `.nupkg` set (Phase 5) has not been run for a real
  release yet.

### Verified for this article

`npm install` was run from the repository root; the `electron` package's own
binary was confirmed present at `node_modules/electron/dist/electron.exe`.
`node scripts/capture_electron_shell.js` was then run, which:

1. Launches the packaged shell headlessly with `--remote-debugging-port`
   (no visible window — this never touches anyone's desktop).
2. Connects over the Chrome DevTools Protocol.
3. Confirms the loaded URL is `docs/site/index.html`.
4. Confirms `window.mmweDesktop` is actually present on the page (the
   preload bridge really ran, not just "the page loaded").
5. Captures a screenshot and refuses anything under 5KB as evidence of a
   blank or broken page.

The result: `docs/huishots/electron/electron-shell-home.png` (132,066
bytes), read back and visually confirmed for this article to show the real
Home surface — tab strip at the left dock, the command palette's `Ctrl+Shift+F`
hint, the hero copy, the download card, the safety notice, and the Backstage
preview card — running inside the Electron window, not a blank or error
page. This is the same renderer the documentation site ships, hosted by
Electron instead of a browser tab, exactly as the migration plan intended:
the interface was not drawn twice.

## What has not moved at all

- **The wxPython application is still the product a user installs and
  runs.** `amulet_map_editor/api/wx/` is untouched by this migration. Every
  surface in the completeness inventory that is marked complete today is
  complete against the wx app, not against Electron, unless its row says
  otherwise.
- **The 3D viewport stays on wxPython, explicitly, and is out of scope for
  every lane of this migration**, not just this one. It is PyOpenGL rendered
  into a wx canvas (`amulet_map_editor/api/wx/ui/viewport*`), it has an open
  performance defect (reported around 3 fps), and `HANDOFF.md` phase 4 says
  in so many words that porting it is a genuine rewrite of the one component
  whose performance is already broken, and must not be started while that
  defect is open. Nothing in this lane touches it, measures it, or plans its
  replacement.
- **No user-facing surface has actually been ported (Phase 3 has not
  started).** Backstage, settings, the dialogs, and the properties pane all
  still run as wx widgets in the shipping app. `docs/site/` already contains
  a Material 3 rendering of Backstage-shaped content (it was built as the
  documentation site, to the same contracts), but it is not fed real project
  data, does not open real worlds, and is not the surface a user reaches by
  running the application.
- **Packaging (Phase 5) has not produced a release artifact.** The Squirrel
  config exists and disables signing correctly, but no Electron installer
  has been built or published from it.

## How to run the Electron shell today

```sh
npm install            # once, from the repository root
npm run electron:dev   # launches the shell (visible window), spawns the sidecar
node scripts/capture_electron_shell.js              # headless shell verification + screenshot
node scripts/verify_sidecar_client.js                # sidecar-client.js vs the real Python process
node scripts/capture_electron_sidecar_roundtrip.js   # full renderer -> sidecar -> restart round trip
```

The shell shows the real `docs/site/` renderer inside a frameless Electron
window, and now spawns and talks to the Python sidecar too: opening the app
starts the sidecar, and the site's `theme` setting reads and writes through
it for real.

## Building a real installable artifact

```bat
build-electron.bat /s             :: bootstrap Node, npm install
build-electron-installer.bat /s   :: package the unsigned Squirrel.Windows installer
```

Both scripts have been run end to end on a real Windows checkout, not merely
written:

- `build-electron.bat /s` bootstraps Node.js if missing, refreshes `PATH` in
  the running process, and runs `npm ci`/`npm install`.
- `build-electron-installer.bat /s` calls the above, refuses to proceed if
  `electron/electron-builder.yml` enables any signing control, then runs
  `electron-builder --config electron/electron-builder.yml` and verifies the
  produced setup executable carries no Authenticode signer certificate.
- The build writes `Setup.exe`, `RELEASES`, and the full `.nupkg` under
  `dist/electron/squirrel-windows/`, and the script prints the setup
  executable's path and SHA-256.

**A real packaging defect was caught and fixed by running this end to end.**
`electron/electron-builder.yml`'s `files` list originally named
`electron/main.js` and `electron/preload.js` explicitly but not
`electron/sidecar-client.js`, which `main.js` requires. The packaged
`app.asar` therefore omitted a file the main process needs to start, so the
packaged executable crashed before ever creating a window or opening its
DevTools port — invisible in a dev run (`npm run electron:dev`, which reads
`sidecar-client.js` straight off disk) and invisible to a script that only
checks "did the installer get produced," since packaging itself succeeded.
The fix widened the glob to `electron/*.js` so every same-level module main.js
depends on ships with it.

Verification that the **packaged** build (not the dev one) actually works:
`scripts/verify_packaged_electron.js` launches
`dist/electron/win-unpacked/Material Minecraft Map Editor.exe` headlessly
with `--remote-debugging-port`, connects over the DevTools protocol, and
asserts the loaded URL is the real `docs/site/index.html` served out of
`app.asar`, that `document.title`/body text are non-empty, and that
`window.mmweDesktop` (with its `sidecar` key) is exposed from the installed
resource layout — a bridge that only worked from `electron/main.js` on the
dev source tree and not from inside `app.asar` would be caught here.

## How the two processes talk (today, and what remains)

**Today**, on every launch: `electron/main.js` spawns
`python -m amulet_map_editor.api.sidecar` as a child process and owns its
whole lifetime (restart on crash, kill on quit). The renderer never talks to
that child directly — it calls `window.mmweDesktop.sidecar.call(method, params)`
(from `electron/preload.js`), which goes over one IPC handle to
`electron/sidecar-client.js` in the main process, which writes one JSON line
to the child's stdin and resolves the matching line back off its stdout,
timing the call out rather than hanging if the sidecar never answers.
`docs/site/electron-bridge.js` is the one real caller today: it reads the
sidecar's `theme` preference on load and applies it locally, and writes the
site's `theme` setting back to the sidecar on every change — the same
`settings.set()` call the settings-panel UI itself makes, not a bypassed
direct write.

- The wx application still talks to the core modules in-process, exactly as
  before this migration started — nothing here changed that.
- The sidecar remains a standalone stdio server: anything speaking its
  newline-delimited JSON protocol can drive it, and the wx app does not use
  this path.

**What remains:** every writable preference field now round-trips, and
`converter.formats`, `changelog.entries`, `docs.articles` and `dimsum.draw`
each have a real site-side caller, as does the world-edit write path
(`world.fill`/`world.replace`/`world.undo`/`world.redo`/`world.save`, from
the viewport panel's own toolbar). Porting the rest of a real user-facing
surface (Backstage, the properties pane, the dialogs) onto this same bridge
is Phase 3, and has not started.

## Related reading

- [The core/wx boundary](../core-boundary/README.md) — what Phase 1 actually
  drew a line around
- [The Python sidecar](../sidecar/README.md) — the protocol itself, its
  message shapes, and its error codes
- [The capture matrix](../capture-matrix/README.md) — how screenshots are
  taken and verified across the project, including this article's evidence
- [Completeness inventory](../completeness-inventory/README.md) — the
  migration checklist that this row reports into
