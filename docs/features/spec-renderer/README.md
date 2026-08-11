# Spec renderer, and how to add a surface

Most of Amulet Studio's windows are data. A surface is described by a `Spec` —
an eyebrow, a title, a width, an introduction, an ordered list of sections, and
a list of footer actions — and one renderer turns that description into real
controls. Adding a window is a data entry plus one line in the surface index; it
is not a new window class.

## Behaviour

`amulet_map_editor/api/studio/spec.py` holds the description. Each `Section`
names a **kind**, and there are sixteen:

`search`, `fields`, `selects`, `list`, `keys`, `tree`, `chips`, `checks`,
`ranges`, `swatches`, `progress`, `keygate`, `code`, `note`, `commits`,
`texture`.

`amulet_map_editor/api/studio/spec_dialog.py` renders them. `SpecDialog` draws a
header (the eyebrow in small caps above the title, the window search field, and
a close button), a scrolled body with one renderer per section, and a footer
carrying the spec's actions on the left and a filled confirm button on the
right. Escape closes it, the confirm button is the default, and focus returns to
whatever opened it.

Dialogs are shown non-modally, so several surfaces can be open at once and none
of them blocks the workspace behind it.

The **window search** filters the sections and rows live. A section whose own
heading matches keeps all of its members, so searching for a panel's name does
not empty that panel; structural sections — the search field itself, a gate, a
progress readout, a texture preview — stay put while the records around them
filter. A query matching nothing produces an honest no-match line.

A footer action carrying a `surface` opens that surface through the shared
index. One carrying a `command` runs it through the shell. One carrying neither
is a local button the dialog handles itself.

## Adding a surface

1. Add a `Spec` to the right module under
   `amulet_map_editor/api/studio/specs/`. Each module exposes its own `SPECS`
   dictionary and the package merges them.
2. Add the key to the group it belongs to in
   `amulet_map_editor/api/studio/surfaces.py`.

That is the whole change. The surface then appears in the backstage's **All
surfaces** page, in the command palette, and as a valid target for a ribbon
tile, a context-menu row, or another surface's footer action — with no new
markup and no new window class.

A surface the renderer genuinely cannot express gets a hand-built window and a
route in the same index. Two exist: the NBT editor and the Memory Console.

### A surface whose content is live is rebuilt, not written down

A spec family may also expose a `REBUILDERS` mapping of surface key to a
no-argument builder. `specs.get()` calls it instead of serving the import-time
snapshot, so the window shows the state it is opened in rather than the state
the package was imported in. A rebuilder that fails falls back to the snapshot
and logs it — a slightly stale window beats a window that will not open.

**Key Select is the one that needs it.** Its rows are the 3D editor's own action
list, in the editor's own order, each resolved against the key group the editor
is actually listening to through
`amulet_map_editor/api/studio/keys.py`. That module is the single place any
surface reads those bindings — the viewport's right-click menu reads it too — so
a printed key and a working key cannot be two different things.

They had been. The rows were transcribed from the design, and the design and
the editor did not agree: measured against the shipped key group, this window
offered `MMB` for Rotate Camera (really `RMB`), `Ctrl+Scroll` for both selection
distance rows (really `R` and `F`), `Esc` for Deselect Active Box (really
`Ctrl+D`), `RMB` for Inspect Block (really `Alt`) and `P` for Toggle Projection
(really `Tab`) — six wrong keys in the window a user opens to learn the keys,
and the shipped defaults on top of that for anyone who had rebound one.

An action the active group binds nothing to reads `not bound`. A configuration
that cannot be read at all produces a section that says so, rather than an empty
grid or the shipped defaults — which are exactly the keys somebody who rebound
them no longer presses.

A rebuilt description has to reach the reader, and for a while it reached only
some of them. `open_spec` builds one on every press and hands it to the modeless
helper, which raises the window already registered under that key and returns
it — so the new description was dropped and an open Key Select window went on
teaching the group it was opened with. The raised window is now handed the new
description and redraws when it differs from the one it holds. The command
palette had the same gap from the other side: its setting index read
`specs.SPECS[key]` directly, which is the map built at import, so the rebuilder
never ran for it at all. It reads through `specs.get()` now, like every window
does.

### The controls on Key Select

The keys were read live while the window's own controls still described a
window that does not exist. `Active group` listed the reader's real key groups
with the active one pre-selected and was wired to nothing, so choosing another
left all nineteen rows where they were; `Action set` offered `3D editor`,
`Selection` and `Camera`, which the editor has no such concept of, and filtered
nothing; and the footer read `Save group` over a window that saves nothing,
beside `New group`, which creates nothing, and `Reset group`, which routed to
the renderer's generic reset — clearing the window's search boxes and re-reading
the open world.

The dropdown now switches which group's keys are listed, through
`Select.on_change`: the renderer calls it and then re-reads the surface, so the
rows below rebuild against the group just chosen. The redraw is deferred to the
event loop, because it arrives from inside the dropdown's own click handler and
rebuilding the body destroys that dropdown mid-call.

**It shows a group; it does not switch to one.** Nothing here writes the
reader's configuration — the running canvas registers its actions when it is
built, so a window that wrote the setting would leave the editor listening to
the old group while claiming otherwise. Which group is active is changed in the
3D editor's own Controls window. When the group being shown is not the group
the editor obeys, the note says so and names both; a group that no longer
exists falls back to the active one rather than emptying the window.

## Configuration

Section kinds are a closed set; `sec()` refuses an unknown one at construction
rather than rendering nothing at display time. `tex_section()` builds the
standard texture preview, including the disclaimer that the tile is generated.

Widths, confirm labels, and introductions are per spec. Everything else —
colour, type, spacing, control height — comes from the shared tokens.

## Failure modes

A spec family that fails to import is logged with its traceback and skipped, so
one malformed module cannot take every window in the application down at import
time. A key claimed by two families is reported rather than resolved by luck of
import order.

A key that is indexed but has neither a route nor a spec is reported by
`surfaces.unrouted_keys()`, which the suite asserts is empty — an unopenable
surface is a fact a test can fail on rather than something a user discovers.

## Security and accessibility

The renderer draws only what its data describes; it evaluates nothing, imports
nothing by name, and reaches no network.

Each section renderer produces controls that are keyboard reachable, focus
visible, and named. The body scrolls rather than clipping, so a long spec at a
high display scale loses nothing off the bottom, and the dialog is bounded by
the display it opens on.

### Opening size

A window sizes itself from its content, between a floor of 280 and a ceiling of
`MAX_DIALOG_HEIGHT`, and then within the display it opens on. That reading has
to come from the body's sizer: the body is a `wx.ScrolledWindow`, and asking a
scrolling window for its best size answers with the size of the hole rather
than of what is inside it — 16 pixels for a body holding 790. Asking the dialog
itself therefore summed a header, a footer and almost nothing between them, and
every surface opened at the floor no matter how much it had to show. Key Select
arrived 280 pixels tall with a 113-pixel viewport over nineteen key rows, one of
which fitted; the documentation reader opened with 113 pixels over 579.

The surface caption above the title had the same shape of defect one control
down: measured with a plain `wx.ClientDC` and painted through a `wx.GCDC`, which
lays glyphs out on fractional advances and comes out wider. `KEY CONFIGURATION`
measured 129 pixels, drew 134, and was given 131, so its final letter was drawn
with the right-hand stroke sliced off. It is measured with the context it is
drawn with now.

## Verification

```powershell
py -3 -m pytest tests/test_studio_spec_registry.py -q
```

That file checks every spec has a key, an eyebrow, a title, and at least one
section; that every section kind is one the renderer draws and every kind is
actually used by something; that no section is empty of what its kind promises;
that every range, select, and progress value is internally consistent; and that
every footer action resolves to a real surface or a real command.

```powershell
py -3 -m pytest tests/test_help_surfaces_print_live_keys.py -q
```

That file guards the keys a surface prints against the keys that work. Its
first test compares Key Select's rows with the live lookup, which on its own
would pass on any two things that agree — including two blanks — so two more
sit behind it: one proving the lookup answers with a real key for every row,
and one that changes the user's key group underneath the surface and asserts
the printed keys move with it. A written-down string cannot pass that last one.
It also asserts that no menu row restates an accelerator the shared table
already binds, and that pressing the chord the title bar advertises really does
open the command palette. (The two accelerator tables are checked against each
other by `test_studio_spec_registry.py`, which has done so since before that
file existed; a second copy of the same assertion lived here for a while
claiming to be new coverage, and has been removed rather than restated.) Every
one of them was watched failing against a deliberate break before it was kept.

```powershell
py -3 -m pytest tests/test_key_select_controls_are_live.py ^
                tests/test_live_surfaces_reach_every_reader.py ^
                tests/test_spec_dialog_opens_at_a_usable_size.py -q
```

The first drives Key Select's dropdown and asserts the printed keys move to the
group that was chosen, that the note names both the group shown and the group
the editor obeys, and that the three invented buttons stay gone. The second
proves a rebuilt description reaches the window already on screen and the
command palette's index. The third is measured at runtime: every tall surface
either fits its body or has grown as far as it is allowed, and no surface
caption is narrower than the text drawn into it. Each was watched failing — the
first three against the un-wired dropdown, the rest against the original
formulas, which reported the exact pixel figures quoted above.

Suggested articles: [project shell](../project-shell/README.md),
[ribbon](../ribbon/README.md),
[texture previews](../texture-previews/README.md), and
[destructive-action gate](../destructive-gate/README.md).
