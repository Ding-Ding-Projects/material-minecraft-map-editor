# Properties pane

The properties pane is the workspace's right-hand pane: a tabbed inspector for
whatever is currently selected, plus the project's own revision history.

## Behaviour

`PropertiesPane` (`amulet_map_editor/api/studio/properties_pane.py`) shows one
tab strip and one panel beneath it. The tabs cover the selection's properties,
its block or entity data where it has any, and **History** — the commits this
project's own Git repository has recorded, newest first, with the head revision
marked.

Every property is a labelled row. A value that can be edited is edited in place
through the same controls the rest of the shell uses: an outlined field for
text, a stepper for a bounded number, a searchable dropdown for an enumerated
value, an axis-coloured vector field for a coordinate. A value that cannot be
edited says so rather than looking editable and refusing.

The pane carries its own search field — with the regex opt-in and the `.*`
builder — filtering the visible rows live. A search that matches nothing reports
what it searched for.

History rows offer **Diff** and **Restore**. Restoring writes a *new* revision
rather than rewinding, so the state you restored from is still there to go back
to.

Right-clicking the pane opens the pane context menu, searchable and carrying
**Edit appearance…**. The pane is resizable by its sash and its width persists.

## Configuration

The tab strip follows the shared tab contract: tabs can be reordered, and the
order persists. Appearance follows the shared tokens and the per-element editor
reaches individual rows.

## Failure modes

A property whose value cannot be read is shown with the reason, not omitted. An
edit that would produce an invalid value is refused with a message naming the
valid range, and the field keeps what the user typed rather than silently
reverting it.

If the project repository cannot be read, the History tab says so and the rest
of the pane keeps working; a history write that fails never fails the operation
the user actually asked for.

## Security and accessibility

The pane reads and writes only the open project's own data and its local
repository. Nothing is transmitted.

Every row has an accessible name combining its label and its value, so a screen
reader announces both. Rows reflow at narrow widths, long values elide rather
than clipping, and every control takes its height from the density token.

## Verification

```powershell
py -3 -m pytest tests/test_studio_accessibility_contract.py tests/test_local_history.py -q
```

The first proves the pane names itself and follows the theme; the second proves
the append-only history contract the History tab presents. Neither is runtime
proof of the pane's own rendering.

Suggested articles: [where a pasted copy lands](../paste-anchor/README.md),
[per-project version history](../project-history/README.md),
[navigator](../navigator/README.md),
[NBT editor](../nbt-editor/README.md), and
[local version history](../local-history/README.md).
