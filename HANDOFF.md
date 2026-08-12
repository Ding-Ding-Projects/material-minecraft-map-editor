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
is the register of what is actually delivered: **18 of 19 rows complete**, each
row's evidence enforced fail-closed by
`tests/test_feature_completeness_inventory.py`. The one open row is
`pages-site-parity`, which needs a headless browser capture harness this
repository does not have.

The inventory earns its keep. Three rows it marked incomplete —
`locked-surfaces`, `two-factor-authenticator`, `app-logo-customization` — turned
out to be features that existed **only on the documentation site**, or an engine
with no surface to reach it from. A tree scan found their names in a dozen files
and every one was a generated catalog. Closing those rows then found four more
defects underneath: `substitute_text()` was never called by anything, the
destructive gate's copy was hard-coded English, `MaterialButton` had no
`render_to` so its captures silently photographed nothing, and `ConverterPanel`
was fully built and reachable from nowhere in the running application.

## What is not verified

Rendering against a loaded world, the real renderer inside the workspace
viewport, and every operation on real world data still need a Windows desktop
with a working OpenGL context. Hosted delta publication and a three-version
installed-client update proof remain open before delta delivery is advertised.

**Open defect: the interface repaints continuously and the viewport reports
3 fps.** Reported from a running build, with two visible symptoms: a black
rectangle around the regex opt-in and builder button in more than one search bar,
and text clipped in the properties pane. Not yet diagnosed. Ruled out so far:
`StudioButton`, `StudioCheckBox` and `SearchBar` all reach `_install()`, which
sets `BG_STYLE_PAINT` and double-buffering, so a missing erase-background
suppression is **not** the cause — that was the first hypothesis and it was
wrong. Next step is to reproduce against a built artifact rather than to reason
about the source, since the source says this should already be correct.

## Converting to an Electron application, piece by piece

The decision is to migrate rather than rewrite. What follows is the order that
keeps a working application at every step.

**Real status, verified against running artifacts (see
`docs/features/electron-migration/README.md` for the full evidence):** the
wxPython application is still the shipping product. Phase 0 and Phase 1 are
done. Phase 2 is half done — the Python sidecar is real and was driven end to
end (`protocol.ping`, `preferences.read`/`write`, `language.get`/`set`/`list`,
`converter.formats`, and its structured error path all answered correctly
from a real child process) — but `electron/main.js` does not spawn it and
`electron/preload.js` exposes no bridge to it, so nothing in the shipped
Electron shell can reach it yet. The Electron shell itself launches
headlessly and renders the real `docs/site/` interface
(`docs/huishots/electron/electron-shell-home.png`), which is genuine progress
independent of the sidecar wiring. Phase 3 (porting a real user-facing
surface) has not started. Phase 4 (the viewport) is explicitly untouched.
Phase 5 (packaging) has config but no built release.

**Why it is tractable at all:** the renderer already exists. `docs/site/` is a
complete Material 3 web application carrying the tabs, the command palette, the
regex builder, the settings surfaces, the appearance system, the locks and the
authenticator, all built to the same contracts as the desktop app and already
tested by `tests/test_site_runtime_render_contract.py`. The migration is
therefore mostly about giving that renderer real data, not about drawing an
interface twice.

**Phase 0 — freeze the contracts.** The completeness inventory becomes the
migration checklist: a row may not regress from complete to incomplete because
of a port. This is the gate that stops a rewrite quietly shipping less than the
thing it replaced.

**Phase 1 — separate the core from wx.** Everything under `amulet_map_editor/api/`
that does not import `wx` is already portable: `config.py`, `lang.py`,
`text_overlay.py`, `authenticator.py`, `item_locks.py`, `converter/`,
`dim_sum_surprise.py`, `app_logo.py`, `changelog_catalog.json`. Give that set an
explicit boundary and a test that fails when a `wx` import crosses it. Do this
first because it is useful on its own even if the migration stops here.

**Phase 2 — a process boundary, not a rewrite.** The core stays Python and runs
as a sidecar; the Electron main process supervises it and speaks a typed,
versioned JSON protocol over stdio. Every call is already shaped for this: the
converter sandbox spawns a child process today, so the pattern is proven in this
repository rather than borrowed.

**Phase 3 — port surfaces one at a time, cheapest first.** Backstage, then
settings, then the dialogs, then the properties pane. Each ported surface keeps
its Python core, its localized copy, its persistence and its tests; only the
drawing moves. The inventory row for that surface must stay complete across the
move, with a capture from the Electron build replacing the wx one.

**Phase 4 — the viewport is the hard part and goes last.** The 3D editor is
PyOpenGL inside a wx canvas and has no web equivalent in this tree. Two honest
options, to be decided with real measurements rather than in advance: keep the
wx viewport as a native child window owned by the sidecar and composite it into
the Electron frame, or port the renderer to WebGL. The second is a genuine
rewrite of the one component whose performance is already a reported defect, so
it must not be started while that defect is open.

**Phase 5 — packaging.** Squirrel.Windows is already the required installer and
is Electron's own updater, so the artifact contract does not change. Code signing
stays permanently out of scope, and the installer keeps saying so.

**Known risks, written down now rather than discovered later.** The OS credential
vault is reached from Python today and the authenticator's and locks' secrets
live there — a port must not migrate a secret through a file or a log to get it
into Node. The capture harness renders wx widgets and does not transfer; an
Electron surface needs its own capture route before its inventory row can claim
capture evidence. And a sidecar that dies must not lose unsaved work: the local
version history has to record before the boundary, not after it.

## Next

1. Reproduce the repaint defect against a built artifact and fix it. It blocks
   the viewport decision in phase 4 and it is what a user sees first.
2. Phase 0 and phase 1 of the migration: freeze the inventory as the checklist,
   then draw the no-`wx` boundary around the core and guard it with a test.
3. Give `pages-site-parity` a headless browser capture harness, which the
   Electron work needs anyway — the same harness photographs both.
