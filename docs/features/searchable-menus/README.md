# Searchable menus and dropdowns

Every right-click menu and every dropdown in Amulet Studio carries its own
search field. A menu long enough to need scrolling is a menu whose contents
nobody can find, and a dropdown listing every block in a version is exactly that
problem in a smaller box.

## Behaviour

**Context menus.** `SearchableContextMenu`
(`amulet_map_editor/api/studio/context_menu.py`) draws a popup that paints its
own surface, border, and elevation, is bounded by the display, and scrolls when
its content is taller than the space available. At the top is a search field
with the regex opt-in and the `.*` builder; below it, the items.

Each item shows its keyboard shortcut right-aligned, in the platform's own
notation, and the shortcut shown is the one actually installed — the registry
that draws it and the table that binds it are checked against each other rather
than assumed to agree. An item with no shortcut simply shows none.

**A row this build cannot run shows no shortcut either.** The two halves of a
row are read from different places: a viewport row's key comes from the 3D
editor's live key configuration, while whether the row can run comes from the
shell's command registry. So a row can be greyed out beside a key that works,
and one was — "Deselect all boxes" sat disabled next to the editor's real
`ACT_DESELECT_ALL_BOXES` binding, which teaches a user that a working feature is
missing. That row and its three neighbours are wired now, and a disabled row
withholds its accelerator so the pairing cannot return through a different row.

Every menu carries **Edit appearance…**, opening the per-element editor on the
control the menu was raised from.

Menus exist for the ribbon, the navigator, the viewport, a tab, a tab group, a
pane, a recent row, a selection box, and the status bar.

**Dropdowns.** `SearchableChoice`
(`amulet_map_editor/api/studio/widgets.py`) is closed as an outlined combo
button showing the current value. Opening it anchors a popup beside the control
containing a search field and the options; typing filters them, Enter chooses
the highlighted one, and Escape closes and returns focus to the combo. A
dropdown can carry a colour swatch per option where the value has a colour.

There is no bare `wx.Choice`, `wx.ComboBox`, or `wx.SearchCtrl` anywhere in the
package — the suite checks for exactly that, because reintroducing one is how
the shared behaviour quietly stops being shared.

**Moving into a group** is a picker, not an inlined list. A context menu never
grows one item per group; it carries a single entry that opens an anchored
picker with the existing groups, their colours, their member counts, a
create-new path, an honest empty state, and its own search field.

## Configuration

Menu contents are data — `CTX_MENUS` — so adding an entry is a line rather than
a new popup class. Every entry names a surface to open or a command to run.

A row naming a **surface** this build has not registered is the intended
disabled case: the window is genuinely unbuilt, so the row stays where the
design put it with a tooltip saying so. A row naming a **command** is different,
because commands are this repository's own registry rather than an unbuilt
window, so an unregistered command key is an oversight. The suite asserts that
no menu row anywhere names a command that does not exist.

## Failure modes

A search matching nothing shows an honest no-match line rather than an empty
popup that reads as a rendering fault. An invalid pattern is reported and
matches nothing.

An undecorated popup would let whatever is behind it read straight through the
text on top; these paint their own background, border, and elevation explicitly
rather than relying on a platform frame. A popup never covers the control it is
anchored to, and it never paints outside its own card.

Moving a tab into a collapsed group leaves that group collapsed.

## Security and accessibility

Menus hold no credentials and perform no network access.

Every item is keyboard reachable with a visible focus ring, arrow keys move
through the list, Enter activates, and Escape cancels and returns focus to
whatever opened the menu. Shortcuts are exposed to assistive technology as
shortcuts rather than as decorative text, so they are not announced twice.

## Verification

```powershell
py -3 -m pytest tests/test_studio_regex_builder_coverage.py tests/test_studio_spec_registry.py tests/test_selection_menu_rows_run.py -q
```

The first proves both menu search fields still exist, that **Edit appearance…**
is still present, and that no unsearchable control has been reintroduced
anywhere in the package. The second proves the shortcut drawn beside a command
is the one the shell actually installs.

The third builds the menus and the shell for real. It runs each of the four
formerly dead rows through the same `run_command` a right-click reaches and then
asks the editor's own selection and camera what changed — a row is verified by
the state it moved, never by the notification it posted — and sweeps every menu
for a disabled row still printing a key.

Suggested articles: [search, regular expressions, and the command palette](../search-and-regex/README.md),
[ribbon](../ribbon/README.md),
[tabs and groups](../tab-groups/README.md), and
[appearance](../appearance/README.md).
