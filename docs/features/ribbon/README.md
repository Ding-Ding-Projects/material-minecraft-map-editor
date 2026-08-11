# Ribbon

The workspace's command surface is a seventeen-tab ribbon: Home, Tools,
Selection, Operations, Structures, Chunks, Terrain, Build, Entities, Data,
Analyze, Redstone, Worldgen, View, Panels, Extend, Automate.

A ribbon is the right shape for this application because the command set is
genuinely large and mostly modal — what you want while sculpting terrain has
almost no overlap with what you want while auditing loot — and because a tab
label is a better index than a nested menu path.

## Behaviour

`RIBBON_TABS` (`amulet_map_editor/api/studio/ribbon_defs.py`) is pure data: each
tab holds groups, each group holds command tiles, field grids, or dropdown
columns, and each group has a small dialog-launcher corner that opens the
surface owning that group.

`RibbonBar` (`amulet_map_editor/api/studio/ribbon.py`) draws it:

- a tab strip with the **Project** button on the left, which is how the
  backstage is reached from inside a project;
- a per-tab search field that filters the active tab's tiles live, carrying the
  regex opt-in and the `.*` builder like every other search field;
- a collapse chevron, so the ribbon can be reduced to its strip when the
  viewport needs the height;
- the panel itself, which scrolls horizontally rather than dropping tiles that
  do not fit.

Every tile names exactly one target: a **surface** to open or a **command** to
run, never both and never neither. Every dropdown stores a value distinct from
its visible label — the dimension list stores `overworld` and shows
`minecraft:overworld` — so a widget never has to reverse-engineer the identifier
it must pass on.

**Every dropdown also names a command**, under the same rule as a tile. A
dropdown that raises nothing is a control the user operates and nothing
observes, and the Structures ▸ Export **Format** dropdown shipped as exactly
that: four options, no command, a stored value nobody read, and therefore four
formats that all exported a `.construction`. `validate()` now refuses a
command-less dropdown, and the check that resolves a dropdown's command against
the registry no longer skips the case where there is none — that skip was what
let this pass. See [exports](../exports/README.md) for what the Format dropdown
now decides.

**A field grid names a command too**, and commits on Enter or on leaving the
box rather than on every keystroke — a user typing `-250` has passed through
`-` and `-2` on the way, and acting on those means reporting two problems and
one wrong answer before they have finished the word.

Right-clicking anywhere on the ribbon opens the ribbon context menu, which is
searchable like every other context menu and carries **Edit appearance…**.

### Selection ▸ Coordinates

The six boxes — `x1`, `x2`, `y1`, `y2`, `z1`, `z2` — show the **active selection
box**, which is the last box in the editor's selection and the same one
**Remove** and **Duplicate** beside them act on. With more than one box drawn,
the group says which one it is showing rather than leaving that to be guessed.

They shipped holding six numbers transcribed from the design mock — `x1=-2`,
`y1=98`, and the rest. Nothing wrote them from the world and nothing read them
back, so with a world open the ribbon displayed a selection box that did not
exist, and went on displaying it while the real selection was dragged, added to
and cleared. That is worse than a control that does nothing: an inert control
disappoints, while these six asserted facts about the user's world and every one
of them was false.

- **Reading.** `StudioShell._sync_selection_fields` refills them from
  `canvas.selection.selection_corners` on the idle enablement pass, so a box
  dragged in the viewport, an undo, or a command run from anywhere moves the
  numbers without the thing that moved the selection having to know they exist.
  The corners themselves are part of that pass's change signature; with only
  "is anything selected" in it, dragging a box changed nothing the pass could
  see and the boxes never moved.
- **Writing.** A committed edit raises `setSelectionBounds`, which writes
  through `_set_selection_corners` — the one path Add box, Remove and Duplicate
  already use. Two ways to move a selection would be two places for the next
  change to have to be made, and one of them would be missed.
- **Nothing selected.** The boxes are emptied, disabled, and say so, naming
  **Add box** as what to press. Six plausible numbers for a box that does not
  exist is the defect itself.
- **Unusable input** is refused and explained under the grid, beside the box it
  is about: a blank or non-numeric value, a coordinate past the 30,000,000-block
  world limit, or a pair equal on an axis, which would select no blocks at all
  while every operation ran on it and reported success. The typed text stays on
  screen to be corrected, and the selection does not move.
- **A reversed pair is not refused.** The editor keeps a selection as two corner
  points rather than as bounds, and the *Move point 1* tile beside these boxes
  will drag point 1 past point 2, so refusing what the neighbouring control does
  would be the interface disagreeing with itself. The axis is ordered, and
  because the boxes are re-read from the world afterwards the ordering is shown
  back rather than done quietly.

The binding table that says which number each box stands for lives in
`amulet_map_editor/api/studio/selection_fields.py`, hand-written rather than
derived from the labels: a rule reading `x1` as "the X of point 1" is one
renamed label away from silently addressing a different number, and writing the
wrong corner of somebody's selection is indistinguishable from working right up
until they look at what they just deleted.

## Configuration

The active tab and the collapsed state persist. Appearance follows the shared
tokens, and the per-element appearance editor reaches ribbon tiles like any
other control.

Adding a tab means adding one entry to `RIBBON_TABS` built from groups and
tiles; it needs no new drawing code. Adding a tile to an existing group is one
line naming its label, glyph, hint, and target.

## Failure modes

`ribbon_defs.validate()` returns every structural problem in the definition and
is asserted to be empty by the suite: a tab with no groups, a group with no
controls or no launcher, a tile with no glyph or no hint, a tile naming both a
surface and a command or neither, a dropdown with no options, no label, or two
rows storing the same value, a dropdown that raises no command, a dropdown
defaulting to a value that is not one of its own options, a **dropdown option
storing no value** — a row the user can pick that `set_select` discards
silently, raising not even the dropdown's own command — and a **field raising no
command**, which is what every typed box in this ribbon was. It also refuses two
controls that would share one entry in the ribbon's live-value dictionaries,
since those are keyed by a dropdown's label alone and by a field's group title
and label: a collision means typing in one silently overwrites the other, and
the shell reading either gets whichever was touched last. It also checks the
structure-format table the Export dropdown is
built from: a blank cell, a duplicated value, or two formats pointing at one
exporter — and the coordinate binding table behind Selection ▸ Coordinates: a
corner addressed twice, a corner addressed by nothing, a box drawn that the
table does not bind, a box raising something other than `setSelectionBounds`,
and a box shipping a literal value, which is how six mock numbers came to be
displayed as though they described the open world.

A tile pointing at a surface nobody registered, or a command nobody implemented,
is caught the same way — as a failing check with the exact tab, group, and label
in the message, rather than as a button that does nothing.

### The refusals are exercised, not merely written

Every refusal above used to be decoration. Deleting the one that catches an
unbound field left all nineteen checks in `tests/test_studio_spec_registry.py`
green, because the shipped ribbon has no unbound field, so `validate()` returned
an empty tuple either way and nothing had ever watched the rule work. The tests
now hand `validate()` a definition broken on purpose — a one-group ribbon whose
only control is a box with no command, a dropdown with no command, an option
with no value — alongside a bound control of the same shape as the floor, so a
rule that simply complained about everything could not pass either.

The order of the checks is load-bearing and is tested as such. A rule written
`if entry.command and commands.command(...) is None` reads as correct and says
"a command, if there is one, must be registered" — which a field naming no
command satisfies perfectly. That version is kept in the test module as
`_field_problems_written_the_skipping_way` and handed the same unbound box as
the real rule: it is asserted to find nothing while the real rule is asserted to
complain. Rewriting the real rule into that shape turns the second assertion
red. This is measured rather than assumed — with the guard temporarily rewritten
that way, an entirely unbound Coordinates grid passed its own check.

The per-tab search never silently empties the tab: a query matching nothing says
so, and an invalid regular expression is reported rather than treated as a
pattern that matches nothing by coincidence.

## Security and accessibility

The ribbon holds no credentials and performs no network access. Every tile is
keyboard reachable with a visible focus ring, and its accessible name is the
label followed by the hint, so a screen reader reads what the tile does rather
than a two-word abbreviation.

Tile labels wrap to at most two lines and grow the tile rather than being cut in
half, which is what keeps bilingual labels legible. The strip is checked at 100,
125, 150, and 200% display scale.

## Verification

```powershell
py -3 -m pytest tests/test_studio_spec_registry.py -q
py -3 -m pytest tests/test_selection_coordinate_fields.py -q
```

The first runs `ribbon_defs.validate()`, resolves every tile's surface against
the surface index and every tile's command against the command registry,
resolves every group launcher, and checks that the shortcut drawn beside a
command is the one actually installed.

The second builds a real shell against the editor's own `SelectionManager`,
opens the Selection tab so the six real widgets exist, and drives them: text
goes into the `wx.TextCtrl` a user types into and the commit is delivered
through the control's own bound handler. What it asserts afterwards is the state
of the live selection, never the string the ribbon stored — storing the string
was precisely the defect.

Suggested articles: [project shell](../project-shell/README.md),
[searchable menus and dropdowns](../searchable-menus/README.md),
[spec renderer](../spec-renderer/README.md), and
[viewport](../viewport/README.md).
