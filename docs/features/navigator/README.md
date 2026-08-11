# Navigator

The navigator is the workspace's left pane: which dimension you are in, and
which selection boxes exist in it. It answers "where am I and what have I
selected" without needing the viewport to be looked at, which matters because
those two facts decide what almost every command on the ribbon will do.

## Behaviour

`NavigatorPanel` (`amulet_map_editor/api/studio/navigator.py`) draws:

- **Dimensions** — every dimension the open world carries, with the current one
  marked. Selecting one moves the viewport and the status bar together.
- **Dimension detail** — the identifier, the height range, and the chunk count
  of the current dimension, rendered monospaced so identifiers and coordinates
  can be read exactly.
- **Selection boxes** — one row per box, with its corner coordinates, its size
  in blocks, and its volume. Rows can be selected, renamed, and removed, and a
  row reveals its box in the viewport.
- A **search field** over both lists, with the regex opt-in and the `.*`
  builder.

Right-clicking a row opens the navigator context menu — searchable, showing each
row's keyboard shortcut, and carrying **Edit appearance…**. Every row in it runs:

- **Frame this dimension** moves the camera so the dimension's *generated*
  extent is in view, which is the chunks the world actually has rather than its
  nominal thirty-million-block bounds. In perspective the camera retreats along
  a bearing 35 degrees above the horizon, far enough for the whole extent to fit
  inside the narrower of the viewport's two field-of-view angles; in top-down it
  stays overhead and widens the orthographic radius instead. Reading the extent
  walks the region files, the same cost **Select all** pays.
- **Duplicate selection box** copies the active box one box-width east of
  itself, so the copy is visible and shares no block with its original. A
  duplicate laid on top of its source would be a box nobody can see or pick.
- **Delete selection box** drops the active box from the editor's own selection.

The pane is resizable by its sash and its width persists.

## Configuration

Dimension identifiers and box coordinates are shown in the monospaced face the
tokens resolve, never re-rounded for display. Appearance follows the shared
theme, density, and accent, and per-element appearance overrides reach the rows.

## Failure modes

A world with a dimension the editor cannot read lists that dimension with the
reason rather than omitting it. An empty selection shows real empty-state copy
naming how a box is made, not a fabricated example box.

A search that matches nothing reports the query it searched for; an invalid
pattern is reported and matches nothing, rather than being quietly ignored.

Removing a box is a state change and is recorded in the project history like any
other, so it can be restored. Removing several at once previews the exact count
and lists anything excluded.

## Security and accessibility

The navigator reads world metadata already loaded by the editor; it opens no
files of its own and reaches no network.

Every row is keyboard reachable with a visible focus ring and an accessible
name that includes the coordinates, so a screen-reader user gets the numbers
rather than "row 3". The pane reflows at narrow widths and its coordinate
columns elide from the middle, keeping both ends of a long value readable.

## Verification

```powershell
py -3 -m pytest tests/test_studio_accessibility_contract.py tests/test_studio_regex_builder_coverage.py -q
```

The first proves the panel names itself and can re-read the palette; the second
proves its search field still carries the builder. Neither is runtime evidence:
selection behaviour against a real world needs a build on a Windows desktop.

Suggested articles: [viewport](../viewport/README.md),
[properties pane](../properties-pane/README.md),
[editing tools](../editing-tools/README.md), and
[project shell](../project-shell/README.md).
