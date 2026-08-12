# Electron packaged-app acceptance run

`scripts/accept_electron_app.js` is the one acceptance run that drives the
**packaged** Electron executable — never `electron .` — through everything
the desktop app claims to do, end to end, and reports an honest
per-capability pass/fail table. It exists because a green test suite proves
the source says the right things; it says nothing about whether a person who
downloads the installer and double-clicks it gets a working application.
Running it once caught a defect that every unit test in the repository
missed.

## What it checks

Each of the eleven checks below runs against the real packaged
`dist/electron/win-unpacked/Material Minecraft Map Editor.exe`, launched
headlessly (`AMULET_HEADLESS=1` plus `--remote-debugging-port`, per this
repository's hard no-focus-stealing gate) and driven entirely over the
Chrome DevTools protocol:

1. the window is created and the real interface loads from inside `app.asar`
2. the preload bridge (`window.mmweDesktop`) is present and exposes only
   `{app, isElectron, sidecar, window}` — never `ipcRenderer` or `require`
3. the sidecar starts and `protocol.ping` answers
4. a preference set through the renderer's own `settings.set()` reaches the
   sidecar's real preferences file
5. `language.get`/`set`/`list` against `amulet_map_editor.api.lang`
6. `changelog.entries` and `docs.articles` return the real bundled catalogs
   (a changelog entry's `commit_sha` is checked against a real 40-hex-char
   SHA shape)
7. `converter.formats` returns the real sixteen-adapter registry, plus a
   **real** NBT→JSON conversion run through
   `amulet_map_editor.api.converter.core.convert_one` — honestly reported as
   running outside the Electron IPC bridge, because no `converter.convert`
   sidecar method exists yet (a declared gap in
   `docs/features/electron-migration/README.md`)
8. `world.open` on a real fixture world reports its real identity
   (name, platform, version) and dimensions
9. the viewport panel streams at least one real chunk to the GPU
   (`chunkCount` from the real streaming path, not the legacy single-mesh
   `vertexCount`)
10. the selection overlay actually draws: the same camera with a selection
    set and with it cleared must produce byte-different canvas captures
11. the app quits cleanly and leaves no orphaned Python sidecar process
    behind (checked via `wmic process ... get CommandLine` matching
    `amulet_map_editor.api.sidecar`, both before launch as a baseline and
    for up to 10s after the quit signal)

The run does not stop at the first failure — every check runs regardless of
earlier results — and exits non-zero if any check failed. A check that
genuinely cannot run says so in its own detail string rather than being
silently skipped.

## Real defect found and fixed by this run

The first run of this script against a freshly built package found checks
3–10 failing with `sidecar_unavailable`. The root cause: `electron-builder.yml`
packaged `amulet_map_editor/` nowhere at all — only `electron/*.js` and
`docs/site/**/*` were listed under `files` — and `electron/main.js` computed
the sidecar's working directory as `path.resolve(__dirname, "..")`, which
resolves *inside* `app.asar` once packaged (a virtual archive with no real
on-disk path `python -m amulet_map_editor.api.sidecar` could ever `cwd` into
even if the source were there).

**Every packaged build ever produced before this fix shipped with a
permanently unreachable sidecar** — no preferences, no language switching,
no changelog, no docs browser, no converter, no world data, nothing that
touches Python, for every user who ever installed it.

The fix, in `electron/electron-builder.yml` and `electron/main.js`:

- `extraResources` now copies `amulet_map_editor/` (minus `__pycache__` and
  `*.pyc`) to `<resources>/amulet_map_editor`, outside `app.asar` entirely,
  where a real interpreter can actually read it.
- `main.js` computes the sidecar's `cwd` as `process.resourcesPath` when
  `app.isPackaged`, and as the existing `REPO_ROOT` in a dev run — so
  `python -m amulet_map_editor.api.sidecar` finds the package on `sys.path`
  in both cases.

After the fix, the same run against a rebuilt package passed checks 1–8 and
11 outright. Checks 9–10 then surfaced a second, smaller defect in the
acceptance script itself: check 8 left its fixture-world handle open, and
the world backend holds a real file lock on `level.dat` while a handle is
open, so check 9's later `world.open` of the *same* fixture path (through
the viewport panel this time) blocked forever waiting on a lock the same
process was still holding — `world.open_status` genuinely never left
`"pending"`. Closing the handle with `world.close` at the end of check 8
fixed it. With both fixes in place, all eleven checks pass against the same
rebuilt package, using the exact same fixture world, the exact same
preference round-trip, and the exact same restart-survival path this
repository's other capture scripts already prove in isolation — now proven
together, from the one artifact a user actually installs.

## Running it

```
build-electron.bat /s
node scripts/accept_electron_app.js
```

The script builds nothing itself — run `build-electron.bat` (or
`npx electron-builder --win --dir --config electron/electron-builder.yml`
for a faster unpacked-only rebuild) first so the packaged executable is
current. It writes `docs/huishots/electron/accept-electron-app-manifest.json`
(the full machine-readable per-check result) and, when the viewport/selection
checks pass, `accept-selection-with.png` / `accept-selection-without.png` as
before/after evidence that the overlay actually changes the rendered frame.

## Honest limitations

- Check 7's conversion does not exercise the Electron IPC bridge, because no
  `converter.convert` sidecar method exists — this is stated in the check's
  own detail string, not hidden behind a green result.
- The orphaned-process check (11) inspects process command lines on Windows
  via `wmic`; it establishes a before-launch baseline so it is not fooled by
  an unrelated Python process the host was already running.
- Checks 9 and 10 depend on the real vanilla Java resource pack, downloaded
  on first run and cached afterwards — the run budgets minutes, not seconds,
  and polls real progress rather than sleeping a guessed amount.
