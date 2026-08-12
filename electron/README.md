# Electron desktop shell

This directory is the Electron application shell for the migration described
in `HANDOFF.md` ("Converting to an Electron application, piece by piece").
It does not draw any UI: the renderer is the existing, already-complete
Material 3 web application at `docs/site/`, unmodified.

## What is here

- `main.js` — the main process. Creates a **frameless** `BrowserWindow`
  (this product draws its own Material title bar and never shows the OS
  default one as product chrome), restores window size/position from
  `app.getPath("userData")/window-state.json` across restarts, clamps
  requested geometry to the usable area of the display it would open on so it
  can never open larger than the screen, and loads `docs/site/index.html`
  directly with `loadFile`.
- `preload.js` — runs with `contextIsolation: true` and `nodeIntegration:
  false`. Exposes exactly one narrow object, `window.mmweDesktop`, with
  window-chrome actions (`minimize`, `maximizeOrRestore`, `close`,
  `isMaximized`, `onStateChanged`) and `app.getVersion()`. It never exposes
  `ipcRenderer` itself, Node built-ins, or the filesystem to the page.
- `electron-builder.yml` — packaging configuration. Code signing is
  permanently disabled (`forceCodeSigning: false`, no certificate inputs of
  any kind) per the project's standing policy. The Squirrel.Windows
  packaging pass itself (RELEASES/.nupkg/setup, the update feed, the real
  icon, the unsigned-artifact messaging) is Phase 5 of the migration and is
  intentionally not wired up yet.

## Running it

```sh
npm install          # once, from the repository root
npm run electron:dev # launches the shell
```

## Verifying it renders (headless, no visible window)

```sh
node scripts/capture_electron_shell.js
```

This launches the packaged shell with `--remote-debugging-port`, connects
over the Chrome DevTools Protocol (the same approach
`scripts/capture_site_surfaces.js` uses for the site itself), confirms the
loaded URL is `docs/site/index.html`, confirms `window.mmweDesktop` was
actually exposed to the page, and writes a screenshot plus a manifest to
`docs/huishots/electron/`. It refuses to accept a suspiciously small capture
(a blank or near-blank page) as success.

## What is deliberately out of scope here

- The 3D viewport (PyOpenGL in a wx canvas) stays on wxPython. See
  `HANDOFF.md` phase 4.
- The sidecar process boundary and its JSON protocol (phase 2) are a
  separate lane; this shell does not yet talk to it.
- No UI is added to `docs/site/` from this lane — window-chrome buttons
  wired to `window.mmweDesktop` land when a later phase ports a surface.
