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

## Verification

```powershell
py -3 -m pytest tests/test_studio_spec_registry.py -q
```

That file checks every spec has a key, an eyebrow, a title, and at least one
section; that every section kind is one the renderer draws and every kind is
actually used by something; that no section is empty of what its kind promises;
that every range, select, and progress value is internally consistent; and that
every footer action resolves to a real surface or a real command.

Suggested articles: [project shell](../project-shell/README.md),
[ribbon](../ribbon/README.md),
[texture previews](../texture-previews/README.md), and
[destructive-action gate](../destructive-gate/README.md).
