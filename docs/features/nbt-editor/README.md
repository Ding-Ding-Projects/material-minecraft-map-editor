# NBT editor

The NBT editor is one of the two Studio surfaces the spec renderer cannot
express, because what it needs is a different control for every tag type rather
than a fixed set of sections. It is three panes: a source rail, the tag tree,
and an inspector for the selected tag.

## Behaviour

**Six data sources** are listed in the rail: block entity, entity, item stack,
player, `level.dat`, and chunk. Each opens a document of its own, and each is
built fresh, so two open editors can never edit each other's tags.

**A control matched to each tag type.** The editor decides what a tag really is
before deciding how to draw it — that reasoning lives in
`amulet_map_editor/api/studio/nbt_model.py` and needs no display:

- a byte named for a flag becomes a switch, not a number field;
- an integer with a known valid range becomes a stepper bounded by that range;
- a bounded numeric becomes a slider with a live readout;
- an enumerated string becomes a searchable dropdown;
- a three- or four-element list of numbers becomes an axis-coloured vector
  field;
- an array becomes element chips;
- a list of compounds named for an inventory becomes a slot grid;
- a colour integer becomes a swatch with a hex translation;
- a list or compound becomes an expandable container with add and open actions.

**Live SNBT and hex views.** Both are produced from the document itself, so what
is shown is what would be written. SNBT round-trips: parsing what the editor
prints reproduces the same text, including the suffixes that say which numeric
type a tag is and the `[B;`, `[I;`, `[L;` array prefixes.

**A type switcher over all twelve types**, with a preview before it is applied.
Retyping reports exactly what it will cost: widening says nothing is lost;
narrowing names the value and the bound it will be clamped to; converting a
value to a container says the value is discarded; a double to a byte reports
both the fraction and the magnitude.

**Validation** runs per tag and over the whole tree. An out-of-range integer is
reported with the exact valid range and the fact that writing it would wrap;
a float that cannot hold the typed value exactly says so rather than showing
something other than what was typed; two children of one compound cannot share a
name.

**Per-tag history.** The first edit records the state the tag was opened in, so
there is always something to go back to. Restoring applies an old revision and
records that as a *new* revision — history is append-only, so an undo can itself
be undone, and restoring twice gives the same result both times.

The tag tree has its own search field with the regex opt-in and the `.*`
builder. A result inside a collapsed branch opens the branches needed to reach
it, because a result nobody can see is not a result.

## Configuration

Ranges, boolean names, inventory names, vector names, enumerated options, and
per-tag hints are tables in `nbt_model.py`. Adding knowledge about a tag is a
table entry rather than a new control.

## Failure modes

Malformed SNBT is refused with the character position and the excerpt where the
parser gave up, rather than being guessed at. An unknown source key opens the
default document rather than no window, because the editor is opened from
several places and a mistyped key should still show something usable.

A deletion inside the editor passes the two-key gate. An edit that fails
validation is applied and reported rather than silently rejected, so the field
shows what the user typed alongside the reason it is wrong.

## Security and accessibility

The model imports no wxPython, touches no filesystem, and reaches no network;
the six built-in documents are constructed in memory. Nothing is written to a
world until the editor is asked to commit.

Every control in the inspector is keyboard reachable with a visible focus ring
and an accessible name carrying the tag's name and value. The tree rows expose
their depth and expansion state, and the monospaced face is used for every
identifier, value, and hex offset so nothing is ambiguous.

## Verification

```powershell
py -3 -m pytest tests/test_studio_nbt_model.py -q
```

Forty-two checks cover the twelve types, SNBT round-tripping for all six
documents, string quoting, malformed input, per-type validation and its
boundaries, retyping in every lossy direction, the per-tag control choice, and
the append-only history rule including restoring a container's children.

The drawing half is not covered by that file; it needs a real build on a Windows
desktop, and no capture of this window exists yet.

Suggested articles: [entities and world data](../entities-and-data/README.md),
[properties pane](../properties-pane/README.md),
[destructive-action gate](../destructive-gate/README.md), and
[spec renderer](../spec-renderer/README.md).
