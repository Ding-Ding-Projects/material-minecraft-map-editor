# Bulk actions

Every list, table, and grid in Amulet Studio supports acting on many rows at
once. Selecting one row and repeating an action forty times is the application
failing to do its job.

## Behaviour

**Selecting.** Click, shift-click for a range, and a keyboard equivalent for
both. A select-all that states plainly whether it means *this page* or *every
match*, and an inverse selection.

**The bar.** `BulkActionBar`
(`amulet_map_editor/api/studio/widgets.py`) appears when a selection exists,
reports the count, and offers the actions that surface supports singly —
delete, export, move, copy, duplicate, rename by pattern, tag, enable, disable,
retry — rather than a token subset.

**Composing with search.** Bulk selection composes with the surface's own search
and filters, so "select everything matching this query" is one step, and the
query's regex opt-in and `.*` builder apply exactly as they do for filtering.

**Where it applies.** The backstage's recent table, the surface index, the
navigator's selection boxes, every result list in the analysis and worldgen
groups, the entity and loot lists, the schematic library, the batch queue, the
notification centre, and the local version history. A notification centre is a
list, and "it is only a log" is not an exemption.

## Before it happens

**Say what will happen.** The exact count, and a reviewable preview of the
affected rows. `42 selected` and `42 will change` are distinguished when some
are skipped, so a bulk action never silently ignores part of its own selection.

A blocking confirmation is used only for the destructive and irreversible ones,
and those go through the two-key gate rather than a dialog with a default
button.

## Configuration

Selection is per surface and does not survive navigating away, because a
selection the user cannot see is a selection they will act on by accident. The
scope of a select-all is stated on the control rather than inferred.

## Failure modes

**Never silently skip.** Anything excluded is reported with the reason: a row
that is pinned, a record the format layer cannot rewrite, a file already open
elsewhere.

A long-running bulk action reports progress, stays cancellable, and reports
partial results honestly rather than claiming a whole batch succeeded when part
of it did not.

Bulk actions are undoable through the same local version history everything else
uses. Where one genuinely cannot be, the surface explains why before it runs
rather than after.

## Security and accessibility

Nothing is transmitted. A bulk export writes to a local path chosen through a
path field with a native browse button, and honours the active filter so the
file matches what was on screen.

The selection count is a named live region, so it is announced as it changes.
Every bar action is keyboard reachable with a visible focus ring and an
accessible name that includes the count it will act on — "Delete 42 selected
rows", not "Delete".

## Verification

```powershell
py -3 -m pytest tests/test_notifications.py tests/test_studio_accessibility_contract.py -q
```

The first covers bulk dismissal and export over a real record store; the second
proves the bar names itself, follows the theme, and answers the keyboard.

Suggested articles: [exports](../exports/README.md),
[destructive-action gate](../destructive-gate/README.md),
[notification centre](../notification-centre/README.md), and
[backstage](../backstage/README.md).
