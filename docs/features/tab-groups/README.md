# Tabs and groups

The desktop app exposes **View → Tabs and groups…** and the same destination in
the `Ctrl+Shift+F` command palette. The native Material 3 surface searches open
tabs in plain-text mode by default and has an adjacent bounded regex builder.

The manager persists the existing tab contract: left/top/right/bottom strip
edge, pinned-first ordering, named groups, group membership, and active-tab
teleportation. Selecting **Activate selected** returns to the real notebook
page rather than opening a duplicate surface. Invalid regex input is handled as
an empty result and never changes tab state.

The current notebook remains the source of truth for rendering and close/dirty
protection. The manager is the persisted organisation and discovery surface;
future work will project the chosen edge and group headers into the live strip
without changing the saved contract.

## Failure modes and security

- Search is bounded to 256 characters and evaluates locally.
- Invalid patterns produce no matches and do not mutate state.
- Unknown or malformed persisted IDs are discarded by `TabWorkspace` migration.
- Group and pin changes are saved through the versioned app configuration.

## Verification

`tests/test_tab_manager_ui_contract.py` checks the native M3 shell, regex
builder, persisted operations, View-menu route, and command-palette route.
The underlying `tests/test_tab_groups.py` suite covers persistence, four search
scopes, pinning, grouping, docking, ARIA attributes, and axis-aware keyboard
navigation.

Suggested articles: [Appearance presets](../appearance-presets/README.md),
[Local history](../local-history/README.md), and
[Scheduled settings](../scheduled-settings/README.md).
