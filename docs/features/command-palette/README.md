# Command palette

Press `Ctrl+Shift+F` anywhere in the application to open the command palette. It
is the one global shortcut for reaching anything by name, and the frame installs
it so it stays reachable while any child window has focus.

## Behaviour

The palette searches the registries the rest of the shell reads rather than a
second copy of them:

- every **surface** in `amulet_map_editor/api/studio/surfaces.py` — all the
  windows, panels, and tools, grouped exactly as the backstage groups them;
- every **command** in `amulet_map_editor/api/studio/commands.py` — save, undo,
  redo, the clipboard, selection, chunk and transform actions, the view and
  application commands;
- every **setting**, and the documentation articles.

Because it reads the same data the ribbon and the backstage read, it cannot
drift from what is actually there. A surface added to the index appears in the
palette with no change to the palette.

A result shows what it is, which group it belongs to, and its keyboard shortcut
where it has one — and the shortcut shown is the one actually installed, checked
against the binding table rather than assumed. Choosing a result opens the
owning surface, selects the relevant tab or group, reveals the target, focuses
it, and leaves the rest of the user's state alone.

The palette's own search field is the shared one: plain text by default, the
regex opt-in, the `.*` builder anchored beside it, and the honest feedback line.

## Configuration

The palette opens as a bounded card by default; its size is a user choice and
persists. School mode omits inapplicable destinations from the result set rather
than listing them disabled.

## Failure modes

An empty result is an explicit no-match line naming what was searched for, never
a blank panel. An invalid or oversized pattern is reported locally with the
compiler's own message and matches nothing; it never freezes the interface,
because patterns are length-bounded before they reach the engine.

A result whose surface fails to open says so through the non-blocking notifier,
naming the exact key, rather than closing the palette as though it had worked.

## Security and accessibility

Search values stay local to the process; nothing is transmitted or persisted as
telemetry.

The result list is keyboard navigable with roving selection, visible focus, and
list roles, and every row is named with its label, its group, and its shortcut.
The palette is bounded by the display and scrolls rather than clipping.

## Verification

```powershell
py -3 -m pytest tests/test_studio_spec_registry.py tests/test_studio_search_contract.py tests/test_studio_shell_hosting_contract.py -q
```

Those prove the registries the palette reads are complete and internally
consistent, that the shortcut drawn beside a command is the installed one, that
the search behaviour is the shared one, and that the frame still installs
`Ctrl+Shift+F` alongside the Studio's own accelerator table.

Runtime proof of the shortcut itself needs a real build on a Windows desktop.

Suggested articles: [search, regular expressions, and the command palette](../search-and-regex/README.md),
[project shell](../project-shell/README.md),
[offline documentation](../offline-documentation/README.md), and
[appearance](../appearance/README.md).
