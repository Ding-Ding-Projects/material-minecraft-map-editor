# Amulet Studio backstage (Electron)

The Electron shell's start screen -- what a user sees the moment the app
opens, and what it returns to when a project is closed. It replaces the
documentation site's own marketing landing page for the desktop build,
implementing the backstage design in `design/Amulet Studio.dc.html` (see
`design/HANDOFF.md`, "Backstage") against the real sidecar.

## What it is

`docs/site/studio-backstage.js` mounts a full-height view into a container
element (`#studio-backstage` by default; a shell may set
`window.AmuletSite.studioBackstage.mountId` before this script runs to mount
somewhere else) with a left nav rail and five pages:

- **Home** -- a template gallery (five cards, traced to the design's
  `templates` list) and a searchable, filterable recent table.
- **Open** -- a world-folder path field, an Open action, and the design's
  open-source cards and back-up warning.
- **Project info** -- the identity of the world opened this session:
  platform, version, dimensions, path, and world id.
- **Convert** -- reads the sidecar's real adapter catalogue
  (`Site.electronSidecar.converterFormats`) rather than a fixture.
- **All surfaces** -- a searchable index of the feature inventory in
  `design/HANDOFF.md`, grouped the same way. Only the project-shell entries
  (Home / Open / Project info / Convert) route anywhere from the backstage
  itself; everything else says plainly that it opens once a project is open.

`docs/site/studio-backstage.css` carries the design's Material 3 token
values (`design/HANDOFF.md`, "Design system") scoped under `.studio-backstage`
so the surface renders correctly whether or not a shell-level
`studio-tokens.css` has already defined the same custom properties on an
ancestor.

## Real data, not fixtures

- **Recent table**: calls the sidecar's `recents.list` method
  (`amulet_map_editor/api/sidecar/world_methods.py` /
  `amulet_map_editor/api/studio/recents.py`) once on mount. Rows render the
  store's own `name`, `kind`, `platform`, `path`, `opened_iso`/`opened_label`,
  `pinned`, and `tag` fields verbatim -- nothing here invents a recent
  project.
- **Open**: calls `world.open`, then polls `world.open_status` on a 100 ms
  interval up to 60 seconds, exactly the background-load-then-poll contract
  `docs/site/viewport-panel.js` already drives against the same sidecar
  methods. A successful open switches to Project info and calls
  `Site.studioBackstage.onWorldOpened(worldIdentity)` when a shell has
  registered that hook, so a future workspace shell can pick up the open
  world without this module knowing anything about the workspace.
- **Convert**: reads `Site.electronSidecar.converterFormats`, populated by
  `docs/site/electron-bridge.js`'s own `converter.formats` call.

## Honest states

- **No sidecar** (a plain browser tab, the published GitHub Pages site): the
  recent table, Open, and Convert each show a distinct "needs the desktop
  app" message rather than an empty or blank surface.
- **Sidecar reachable, call failed**: the recent table shows the sidecar's
  own error code.
- **Sidecar reachable, zero recents**: an empty-state message pointing at
  the template gallery and the Open page -- never a fabricated sample row.
- **Empty or over-length typed path**: Open reports the problem and never
  calls the sidecar.
- **Folder browsing**: the Browse button next to the path field is real when
  `window.mmweDesktop.sidecar.dialog.chooseFolder` exists, and is disabled
  with an explanatory `title` when it does not -- no such dialog is wired
  into the Electron preload/main process yet, so this build's Browse button
  is honestly inert rather than pretending to open a picker. Typing the path
  remains the fully-working path.

## Search and the regex builder

Both search fields (`#backstage-recent-search` and
`#backstage-features-search`) carry `docs/site/regex-builder.js`'s builder,
each anchored to its own field via `data-regex-controls="backstage-recent"` /
`"backstage-features"` containers, matching the pattern
`docs/site/settings-panel.js` already uses. Plain text is the default; a
missing `Site.regex` (or a container the builder cannot find) degrades to a
plain-text fallback that still filters, rather than a dead search box.

## What this lane does not build

- The workspace shell (ribbon, viewport, navigator, properties pane) is a
  different lane's surface; this module only exposes the
  `onWorldOpened` hook a shell can register.
- The template gallery's non-"Blank world project" / "Conversion job" cards
  route to the closest real destination (Open) and say in their hint that
  the flow itself (structure import, chunk repair, School mode) is not
  wired into this backstage build yet.
- Folder browsing, as above.

## Verification

```powershell
py -3.11 -m pytest tests/test_studio_backstage_runtime_contract.py -q
```

This executes the real module in a DOM (jsdom) with a fake sidecar standing
in for `window.mmweDesktop.sidecar`, the same seam the real Electron preload
script exposes, and checks behaviour rather than source text: recents render
from the fake sidecar's own entries, the filter chips and search field
actually narrow the table, navigation actually switches which panel is
visible, and opening a world drives the real `world.open` /
`world.open_status` pair through to Project info.

No runtime capture of this surface exists yet -- it has not been launched in
the real Electron shell.

Suggested articles: [backstage](../backstage/README.md) (the product-level
design of this surface), [electron migration](../electron-migration/README.md),
[electron world access](../electron-world-access/README.md), and
[search, regular expressions, and the command palette](../search-and-regex/README.md).
