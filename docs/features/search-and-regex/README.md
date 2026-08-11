# Search, regular expressions, and the command palette

Every search field in Amulet Studio behaves the same way, because a regex toggle
that means one thing in the palette and another in a menu is worse than no
toggle at all — the user cannot learn it.

## Behaviour

**One state object.** `SearchState`
(`amulet_map_editor/api/studio/search.py`) holds the query, the mode, the flags,
the sample text, and the field's label. Every search surface owns one, and they
all read the same code.

**Plain text is the default, everywhere.** A plain query is a case-insensitive
substring match, and a query like `1.17.` matches the literal text rather than
being read as a pattern.

**Regular expressions are an explicit opt-in.** The `Regex` checkbox beside each
field turns them on for that field alone. Patterns compile with the
case-insensitive and Unicode flags, and are capped at 500 characters so a
pathological expression is refused before it reaches the engine.

**The feedback line is always honest.** It says one of four things:

| State | Line |
| --- | --- |
| No query | `Plain-text search. Enable regex deliberately.` |
| Plain query | `Filtering by plain text.` |
| Valid pattern | `Regex is valid.` |
| Broken pattern | `Invalid pattern: <the exact compiler message>` |

**An invalid pattern matches nothing and says why.** It is never treated as an
empty query, because a broken pattern that quietly matched everything looks like
a search that was ignored.

**The `.*` builder is anchored to its own field.** Pressing it opens the builder
beside the field the user is already typing in, seeded with that field's
pattern, flags, and sample, and writes the accepted pattern back into that field
alone. A modal dialog is the fallback for a display too small to hold the
popover, and nothing else.

**Every field has one.** The backstage's recent table, the surface index, the
world picker, the ribbon's per-tab command search, every right-click menu, the
tab-group picker, each spec dialog's window search, the navigator, the
properties pane, the NBT tag tree, the Memory Console's view search and its
documentation reader, and every searchable dropdown.

## Command palette

`Ctrl+Shift+F` opens the palette from anywhere in the application. It searches
the same registries the rest of the shell reads — every surface, every command,
and every setting — so it cannot drift from what is actually there.

A result shows what it is, which group it belongs to, and its keyboard shortcut
when it has one. Choosing one opens the owning surface or runs the command.
The palette carries the same search field as everything else, including the
builder.

## Configuration

Flags are per field. The sample text a builder starts from is per field too, so
working out a pattern for one search does not disturb another.

## Failure modes

A query matching nothing produces an honest count line naming what was searched
for, never a blank panel. A pattern over the length cap is refused with the cap
named. The count line for a broken pattern reports the failure rather than
reporting zero results as though the search had worked.

## Security and accessibility

Patterns and sample text are evaluated locally by Python's `re` module and are
never transmitted or persisted as telemetry. The length cap and the bounded
evaluation are what keep a catastrophic backtracking pattern from locking the
interface.

Every field, its checkbox, and its builder button are keyboard reachable with
visible focus and distinct accessible names — the builder button announces which
field it belongs to. The feedback line is a named region, so its message is
announced rather than only shown.

## Verification

```powershell
py -3 -m pytest tests/test_studio_search_contract.py tests/test_studio_regex_builder_coverage.py -q
```

The first asserts the four feedback strings verbatim along with plain, regex,
invalid, flag, highlight, and count behaviour. The second holds a hand-written
census of every search field in the shell and fails when one loses its builder —
a rule alone would pass on a surface that had quietly shipped a bare text box.

Suggested articles: [command palette](../command-palette/README.md),
[searchable menus and dropdowns](../searchable-menus/README.md),
[Memory Console](../memory-console/README.md), and
[spec renderer](../spec-renderer/README.md).
