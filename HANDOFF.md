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

## What is not verified

**There is no runtime capture of the Amulet Studio interface.** Everything above
is source and automated-test evidence. Every image tracked in the README shows a
superseded build, and the README, the articles and the site say so where a
current capture would otherwise be implied.

Rendering, the real renderer inside the workspace viewport, the `Ctrl+Shift+F`
shortcut actually firing, and every operation against a loaded world all need a
build on a Windows desktop with wxPython and a working OpenGL context.

Hosted CI and release publication are proven for earlier integrated commits; the
newest workflow may still be running. Hosted delta publication and a
three-version installed-client update proof remain open before delta delivery is
advertised.

## Next

1. Build the application and photograph the Studio interface — the backstage,
   the workspace, a spec dialog, the NBT editor, the Memory Console, the command
   palette — then replace the "no capture exists" statements with real images.
2. Drive the built application from a clean profile rather than only capturing a
   fixed list, because that is how a surface nobody thought to photograph gets
   found.
3. Close out the per-element appearance and tab-projection items still marked in
   progress in the roadmap.
