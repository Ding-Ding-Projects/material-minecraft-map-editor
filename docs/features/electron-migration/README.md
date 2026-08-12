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
protocol. **The two are not yet connected to each other.** Nothing a user
does in the Electron shell today reaches the sidecar, and nothing the wx app
does today goes through the sidecar either — the wx app still talks to its
core modules in-process, exactly as before this migration started.

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
  - **The Electron side of this boundary does not exist yet.** `electron/main.js`
    does not spawn the sidecar, `electron/preload.js` exposes no sidecar
    bridge, and `docs/site/` never calls one. The verification above was run
    directly against the Python process, from a standalone script, because
    there is no Electron-side caller to drive it through yet. This is the
    single largest gap between "phase 2 is done" and where the migration
    actually stands: the protocol works, but nothing in the shipped app uses
    it.

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
npm run electron:dev   # launches the shell (visible window)
node scripts/capture_electron_shell.js   # headless verification + screenshot
```

This shows the real `docs/site/` renderer inside a frameless Electron
window. It does not yet open worlds, read preferences, or do anything the
sidecar can do — there is no wire between them.

## How the two processes talk (today, and what remains)

**Today:** they do not talk to each other in the shipped configuration. Each
runs and can be exercised independently:

- The wx application talks to the core modules in-process, as it always has.
- The Electron shell hosts `docs/site/` and answers window-chrome IPC calls
  only.
- The sidecar (`python -m amulet_map_editor.api.sidecar`) is a standalone
  stdio server that anything speaking its newline-delimited JSON protocol
  can drive — proven in this article by driving it directly from a
  standalone Python script, not from Electron.

**What remains before "the two processes talk" is a true sentence about the
shipped app:** `electron/main.js` needs to spawn the sidecar as a child
process, `electron/preload.js` needs a bridge method (something like
`window.mmweDesktop.sidecar.call(method, params)`) that forwards to it over
IPC without exposing raw process or filesystem access to the page, and
`docs/site/` needs at least one real call site — for example, driving
`preferences.read`/`preferences.write` from the site's own settings surface
instead of (or in addition to) its current local-storage-only behaviour.
None of that exists yet; it is the next piece of Phase 2 and the
precondition for Phase 3 to begin honestly.

## Related reading

- [The core/wx boundary](../core-boundary/README.md) — what Phase 1 actually
  drew a line around
- [The Python sidecar](../sidecar/README.md) — the protocol itself, its
  message shapes, and its error codes
- [The capture matrix](../capture-matrix/README.md) — how screenshots are
  taken and verified across the project, including this article's evidence
- [Completeness inventory](../completeness-inventory/README.md) — the
  migration checklist that this row reports into
