# Electron studio workspace

`docs/site/studio-workspace.js` + `docs/site/studio-workspace.css` build the
Amulet Studio **workspace** view inside the Electron app: the ribbon (17
tabs), the breadcrumb context bar, the navigator, the tabbed properties pane
and the status bar around the existing 3D viewport. It mounts into a single
`<div id="studio-workspace"></div>` host element and is designed to be
dropped into `docs/site/studio.html` (owned by a separate lane) alongside
the existing `docs/site/viewport-panel.js`, `viewport-webgl.js` and
`viewport-overlays.js`.

Traced to `design/Amulet Studio.dc.html` (the live design deliverable) and
`design/HANDOFF.md`: the same seventeen ribbon tabs (`ribbonTabDefs` in the
design file), the same command groups per tab, the same breadcrumb /
navigator / properties-pane / status-bar layout, and the same Material 3
tokens from `design/HANDOFF.md`'s "Design system" section, reseeded teal
with IBM Plex Sans / IBM Plex Mono and the compact/comfortable/spacious
density tokens (32/36/44px control height).

## What this file owns, and what it reuses

This lane owns only the chrome around the viewport, not the viewport
itself:

- **Reused, not reimplemented**: `docs/site/viewport-panel.js` (the working
  WebGL2 viewport, camera, chunk streaming, and the real write path --
  `world.fill` / `world.replace` / `world.undo` / `world.redo` /
  `world.save` via `docs/site/electron-bridge.js`). This module mounts the
  exact DOM element ids `viewport-panel.js`'s own `DOMContentLoaded`
  handler looks for (`#viewport-host`, `#viewport-canvas`,
  `#viewport-empty`, `#viewport-status`, `#viewport-open-row`,
  `#viewport-open-button`, `#viewport-world-path`) so that module's real
  init logic runs against them unmodified.
- **Built here**: the ribbon tab strip and command groups, the breadcrumb
  bar, the navigator (world dimensions and the current selection box), the
  tabbed properties pane (Properties / Layers / History), and the status
  bar.

**Script order matters.** `docs/site/studio-workspace.js` must load *before*
`docs/site/viewport-panel.js` in the host page, because it builds the
`#viewport-host` element tree that `viewport-panel.js`'s own
`DOMContentLoaded` listener looks up by id. Both listen for
`DOMContentLoaded`; listeners run in the order they were registered, which
follows script-tag order.

## Wired versus not-yet-wired ribbon commands

Every one of the roughly 140 ribbon buttons the design specifies is exactly
one of two kinds -- there is no third kind that silently does nothing:

1. **Wired** -- backed by a real call. Two families exist:
   - Sidecar write-path commands: **Undo**, **Redo**, **Save** (Home ▸
     Editing), **Fill** and **Replace** (Operations ▸ Stock operations).
     Each calls the already-working `window.__AmuletViewportPanel.runUndo /
     runRedo / runSave / runFill / runReplace()` exposed by
     `viewport-panel.js`, so the actual `world.fill` / `world.replace` /
     `world.undo` / `world.redo` / `world.save` sidecar round trip, the
     destructive-action confirm gate, and the unsaved-changes tracking are
     all the real ones -- nothing here re-implements them. These render
     enabled only once a sidecar is present (`window.mmweDesktop.sidecar`)
     **and** a world is open and streaming
     (`window.__AmuletViewportPanel.isStreaming()`); otherwise disabled with
     "Open a world in the viewport below first."
   - Local-only UI commands, which need no sidecar at all: switching ribbon
     tabs, toggling the ribbon (View ▸ Show ▸ Ribbon), showing/hiding the
     properties pane (Home ▸ Panes ▸ Properties and View ▸ Show ▸
     Properties), toggling light/dark theme (View ▸ Appearance ▸ Theme),
     and the density select (View ▸ Appearance). These are enabled whenever
     a sidecar is present (see "Desktop-only degrade" below for the no-
     sidecar case).
2. **Not yet wired** -- every other command the design specifies (brushes,
   structure import/export, chunk tools, NBT search, redstone tracing, and
   the rest of the twelve editing surfaces the design inventories). These
   render **permanently disabled**, with the reason "Not yet wired to the
   desktop sidecar in this build." in both the button's `title` attribute
   and, for the ribbon buttons under test, surfaced the same way every
   disabled control in this project explains itself. Clicking one does
   nothing observable, which is expected -- the button has no `onClick`
   handler attached at all when disabled, per this project's "every
   disabled control says why, never a silent no-op" rule.

The wired/unwired split lives in `buildRibbonByTab()` in
`studio-workspace.js`: a group's button either passes a real function as
its `run` argument, or passes nothing (`null`), which `commandButton()`
turns into `disabled` + the explicit reason.

## Navigator

The navigator lists the open world's dimensions, sourced from the sidecar's
real `world.dimensions` method (`amulet_map_editor/api/sidecar/
world_methods.py`), which returns each dimension's name and bounding box.
Rather than duplicating the viewport tab's own "open a world" flow, the
navigator attaches a second listener to the *same* `#viewport-open-button`
that `viewport-panel.js` already listens on: choosing a world path once
both starts the 3D viewport streaming (via `viewport-panel.js`'s own
listener) and populates the navigator (via this module's own
`world.open` → `world.open_status` → `world.dimensions` call chain). Before
any world is open, the navigator shows the honest empty state "No world
open yet." rather than a blank list.

The "Selection boxes" section reads the same six coordinate fields
`viewport-panel.js`'s edit panel maintains
(`window.__AmuletViewportPanel.edit.readPoints()`), so the box shown here
and the box the Fill/Replace buttons operate on can never drift apart --
there is exactly one selection, read from exactly one place.

## Properties pane

Three tabs: **Properties** (the current selection's two points and the
open world's dimension/streaming state, when known), **Layers** and
**History**, both of which currently have no sidecar-backed data source and
say so explicitly rather than showing fabricated rows -- this build has no
render-layer visibility toggle and no per-project Git repository read path
yet.

## Status bar

Shows the same live status text `viewport-panel.js` already writes (`Opening
world...`, `Streaming chunks...`, `world.fill failed: ...`, and so on) via
the shared `#viewport-status` element id, plus the currently selected
dimension.

## Desktop-only degrade

Outside Electron (a plain browser tab, the published GitHub Pages site --
which never loads this module) `window.mmweDesktop.sidecar` does not exist.
The whole workspace renders one explicit paragraph saying so instead of a
ribbon full of buttons that would all be silently inert; no ribbon,
navigator, viewport host, properties pane, or status bar is built in that
case.

## Testing

`tests/test_studio_workspace_runtime_contract.py` executes the real script
in jsdom (the same pattern as `tests/test_site_runtime_render_contract.py`)
and asks behavioural questions no source-text grep can answer: does the
module throw on load; does the desktop-only message show with no sidecar;
do all seventeen ribbon tabs render and does clicking one switch the
visible command groups; is an unwired command (e.g. "Paste") disabled with
the exact reason text; is a wired-but-precondition-unmet command (Undo with
no open world) disabled with "Open a world..."; does Undo render enabled
and actually call the real `runUndo()` once a world is reported streaming;
does opening a world populate the navigator from a mocked `world.dimensions`
response; does the properties pane close and reopen; and are the exact DOM
element ids `viewport-panel.js` depends on present. No UI smoke testing (no
Electron launch, no screenshots) was performed for this lane, per the task's
explicit instruction -- only jsdom execution and static guards. A real
Electron launch would additionally prove: that `studio-workspace.js` and
`viewport-panel.js` load in the correct order from the actual
`studio.html` the tokens lane builds, that the real sidecar's
`world.dimensions` response shape matches the mocked one used here, and
that the rendered layout matches the design's pixel sizes and colors at
1440x920.
