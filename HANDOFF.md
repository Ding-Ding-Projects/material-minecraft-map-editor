# Handoff

## Current state

The branch carries **Amulet Studio**: the full user-interface rewrite of the
map editor as a project workspace. `amulet_map_editor/api/framework/amulet_ui.py`
builds `StudioShell` as the frame's content and hides the earlier title bar,
command bar, and notebook container; the notebook itself is kept because it owns
world loading and per-page unsaved-work protection, and it is handed to the
workspace viewport once a world is open.

Underneath it, the previously integrated work is unchanged: the shared Material 3
wxPython layer for the dialogs that predate the Studio, persisted preferences and
the regex builder, non-blocking Squirrel update checks, the versioned
scheduled-settings editor, the searchable local-history browser, the persisted
tab and group manager, the bounded per-element appearance editor, the unsigned
Squirrel.Windows packaging workflow, and the owned Material 3 site source.

## What landed in the interface

| Piece | Where | Size |
| --- | --- | --- |
| Shell, title bar, backstage, workspace | `amulet_map_editor/api/studio/` | two views, swapped |
| Design tokens | `studio/tokens.py` | 14 colour roles × 2 palettes, 3 densities |
| Declarative renderer | `studio/spec.py`, `studio/spec_dialog.py` | 16 section kinds, all in use |
| Surface descriptions | `studio/specs/` | 111 specs in 5 families |
| Surface index | `studio/surfaces.py` | 119 surfaces in 14 groups |
| Ribbon | `studio/ribbon_defs.py`, `studio/ribbon.py` | 17 tabs |
| Commands | `studio/commands.py` | 46 commands in 8 groups |
| Hand-built windows | `studio/nbt_studio.py`, `studio/memory_console.py` | NBT editor; 13-view console |
| NBT model | `studio/nbt_model.py` | 12 tag types, 6 sample documents |

## Verified on this machine

**Command run:** `py -3 -m pytest tests -q` from the repository root.

**Result:** `540 passed, 5 skipped, 293 subtests passed`.

The nine Studio test files contribute `148 passed, 4 skipped` on their own.

**Why the skips.** wxPython is not installed on this machine, so five checks
that genuinely need it skip with that reason stated rather than passing
silently: four in `tests/test_studio_tokens.py` (the built palettes as real
colours, and accent reseeding) and one in
`tests/test_studio_shell_runtime_contract.py`. Everything else in the suite runs
without a display, because the interface's whole data layer — the surface index,
the command registry, every surface description, the shared search state, the
NBT model, and the Memory Console's content — imports without wx by design.

**Two generated resources were rebuilt** as part of this work and are required
for the suite to pass:

```powershell
python scripts/build_docs_bundle.py     # 48 articles
python scripts/generate_changelog.py    # 197 tagged releases
```

The changelog regeneration was not caused by the documentation work — a new tag
had become reachable since the catalog was last written — but the suite needs it
either way, and the session fixture performs it automatically when HEAD has
moved on.

## Tests added

Nine files under `tests/`, following the source-contract style the suite already
uses:

- `test_studio_spec_registry.py` — every spec has a key, an eyebrow, a title and
  real sections; every section kind is known and every kind is used by
  something; every action, ribbon tile, group launcher and dropdown resolves to
  a registered surface or command; the shortcut drawn beside a command is the
  one installed.
- `test_studio_surface_index.py` — a hand-written census of all 119 surfaces
  under their group headings, plus checks that nothing is indexed which the
  documented inventory does not name and that nothing is unroutable.
- `test_studio_search_contract.py` — plain, regex and invalid-pattern behaviour
  with the four feedback strings asserted verbatim.
- `test_studio_regex_builder_coverage.py` — a hand-written census of all
  fourteen search fields, plus proof that no field opts out of the builder and
  that no unsearchable control has been reintroduced.
- `test_studio_tokens.py` — the light and dark palettes as the design's exact
  hex values, the three density heights, the spacing and radius scales, and (wx
  permitting) that any accent reseeds to readable inks.
- `test_studio_nbt_model.py` — SNBT round-tripping, per-type validation,
  retyping in every lossy direction, per-tag controls, and the append-only
  history rule.
- `test_studio_memory_content.py` — thirteen views, every article's path,
  domain, summary and body, every pressable row resolving, and no visible string
  leaking a machine, a path, or a placeholder.
- `test_studio_accessibility_contract.py` — every interactive widget names
  itself, answers the keyboard, and re-reads the palette.
- `test_studio_shell_hosting_contract.py` — the frame builds the Studio shell,
  hides the old chrome rather than drawing it beside, keeps the fallback, and
  still offers the call sites the surface index asks it for.

Two of the nine carry **hand-written lists on purpose**. A rule phrased as
"every surface resolves" passes on an empty registry, and "every search bar has
a builder" passes on a file with no search bar; the enumeration is what turns a
disappearance into a failure. The census check was verified in the failing
direction before it was trusted.

No existing test asserted a contract the rewrite invalidated: the checks that
describe the earlier shell describe the fallback path, which still exists. What
the rewrite did invalidate was the prose — the README, the roadmap, the handoff,
the feature articles, and the site data all described a single start card — and
that has been rewritten.

## Documentation

`docs/features/` now holds 48 articles, one per feature area, each covering
behaviour, configuration, failure modes, security considerations and
verification, and each ending with related reading. Twenty-eight are new,
covering the shell, the backstage, the ribbon, the navigator, the viewport, the
properties pane, the spec renderer and how to add a surface, every tool group,
the NBT editor, the Memory Console, search and the regex builder, searchable
menus, texture previews, per-project history, the destructive gate, language
modes, exports, and bulk actions. `material-shell`, `command-palette` and
`appearance` were rewritten to describe the Studio rather than the old shell.

The eighteen article paths the Memory Console's reader names are now real files,
and the suite asserts that they are.

## What is verified now

The interface has been photographed. `scripts/capture_studio_surfaces.py` renders
each widget into a bitmap rather than reading the screen, so a run needs no
visible desktop and cannot photograph a window that happened to be dragged over
it; the README's capture matrix is generated from the manifest that run writes,
so an image in the README exists on disk and carries the commit it was taken at.
A surface whose controls could not draw is recorded as a failure with its reason
and its file deleted, because a blank capture is worse than none — it looks like
evidence.

Release 1.0.0 is published with its Squirrel.Windows artifacts, unsigned and
stated as unsigned.

The per-surface completeness inventory (`docs/features/completeness-inventory/`)
is the register of what is delivered: **all 19 rows complete**, each row's
evidence enforced fail-closed by `tests/test_feature_completeness_inventory.py`.
That is a statement about this register, not a claim that the product is
finished — a row is complete when its declared evidence exists and the test
enforces it, and the register only ever knew about the nineteen features a
person typed into it.

It earned its keep several times over. Three rows it marked incomplete —
`locked-surfaces`, `two-factor-authenticator`, `app-logo-customization` — turned
out to be features that existed **only on the documentation site**, or an engine
with no surface to reach it from. A tree scan found their names in a dozen files
and every one was a generated catalog. Closing those rows found four more
defects underneath: `substitute_text()` was never called by anything, the
destructive gate's copy was hard-coded English, `MaterialButton` had no
`render_to` so its captures silently photographed nothing, and `ConverterPanel`
was fully built and reachable from nowhere in the running application.

## The Electron application

It exists, it is packaged, and it works. `scripts/accept_electron_app.js` is the
single run that says so: it launches the **packaged executable** — not
`electron .` — headlessly over the DevTools protocol and checks eleven
capabilities without stopping at the first failure. All eleven pass.

The interface is the existing Material 3 renderer under `docs/site/`, unmodified,
hosted in a frameless window. Behind it, a Python sidecar runs the real core over
a versioned newline-delimited JSON protocol on stdio: preferences, language,
changelog, documentation articles, the dim sum draw, the converter — including
running a real conversion — and read-only world access with untrusted-path
validation. The 3D viewport draws real chunks in WebGL2, meshed by the
**unmodified Python mesher**, with camera input, chunk streaming, a selection box
and a chunk grid.

### What the packaged run caught that nothing else could

Every check before it ran `electron .` on the development tree, where the Python
package is simply present on disk. Two defects existed only in the packaged
layout, and both made the application look perfect while doing nothing:

- `electron-builder.yml` never bundled `amulet_map_editor/` at all, and
  `main.js` computed the sidecar's working directory as a path **inside
  `app.asar`** — a virtual archive no interpreter can enter. In every packaged
  build, every preference write, language switch, catalog lookup and world open
  failed with `sidecar_unavailable`, while the window opened and the interface
  rendered.
- Earlier, the same shape: `sidecar-client.js` was omitted from the `files` glob,
  so the packaged app crashed before creating a window.

Both are the same lesson written twice. **A dev run proves the code; only the
packaged artifact proves the product.**

### What is not done

The viewport is a first pass. There is no level-of-detail, no translucent depth
sorting, no biome tint, and no editing — it draws a world and a selection, and
nothing yet modifies one through it. The wx application remains the shipping
product until editing moves across.

The renderer has one surface per capability rather than a designed workflow: the
settings surface drives real preferences, the viewport tab opens a world by path.
Wiring the remaining surfaces to the methods that now exist is ordinary work with
no unknowns left in it.

## What is not verified

Rendering against a large real world, and every operation on real world data,
still need a Windows desktop with a working OpenGL context.

Hosted delta publication and a three-version installed-client update proof remain
open before delta delivery is advertised.

## Things that cost real time, so nobody pays twice

- **`Page.captureScreenshot` hangs indefinitely against a WebGL2 canvas**, with no
  error and no timeout. Read the canvas with `toDataURL()` instead — and read it
  in the **same frame as the draw**, because the drawing buffer is cleared after
  compositing unless `preserveDrawingBuffer` is set. A capture taken one tick
  late returns a blank image that is indistinguishable from a viewport which
  drew nothing.
- **Pixel variance is not proof.** The reference grid alone gives a colour range
  of 245, which is enough to satisfy any "is something drawn" check. To prove a
  specific thing is drawn, capture with it and without it and compare bytes.
- **The streaming viewport increments `chunkCount`, not `vertexCount`.** The
  latter belongs to the legacy single-mesh path. Reading the wrong one reports
  zero geometry against an application that is streaming perfectly.
- **Positive pitch looks down.** From `mat4View`, forward is
  `[sin(yaw)cos(pitch), -sin(pitch), -cos(yaw)cos(pitch)]`, so yaw zero looks
  toward `-Z`. Getting the sign backwards aims the camera at empty sky, which
  looks exactly like a world that failed to load.
- **A capture script must redirect every profile store, not just `CONFIG_DIR`.**
  `AMULET_RECENTS_DIR` and `AMULET_HISTORY_DIR` are separate on purpose, and the
  redirect must happen **before the first application import**, because the
  config module reads the environment at import time. A redirect written after
  it runs too late and does nothing, silently.
- **Test windows are shown without activating them**, never moved off-screen. A
  window with no on-screen pixels never paints, so the capture tests photograph
  a flat colour and report, correctly, that nothing is drawing.

## Next

1. Wire the remaining renderer surfaces to the sidecar methods that already
   exist. No unknowns; ordinary work.
2. Editing through the viewport — the first operation that writes to a world is
   the point at which the Electron app can start replacing the wx one.
3. Level-of-detail and depth sorting in the viewport, once there is a large real
   world to measure against rather than a fixture chunk.
