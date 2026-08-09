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
protection. Persisted top/bottom docking now projects into the live AGW
notebook. Left/right remain explicitly capability-limited because this native
control has no side-strip renderer yet; group headers remain a follow-up while
the saved discovery contract stays intact.

The manager also provides **Close tabs containing text** and **Close tabs not
containing text**. Both actions use their own plain-text-first query and
adjacent regex builder, show a reviewable count before closing, protect pinned
tabs unless **Include pinned** is selected, and route each real close through
the notebook's existing unsaved-work veto. Skipped pages are counted instead
of being silently reported as closed.

## Failure modes and security

- Search is bounded to 256 characters and evaluates locally.
- Invalid patterns produce no matches and do not mutate state.
- Unknown or malformed persisted IDs are discarded by `TabWorkspace` migration.
- Group and pin changes are saved through the versioned app configuration.

## Verification

`tests/test_tab_manager_ui_contract.py` checks the native M3 shell, regex
builder, persisted operations, View-menu route, and command-palette route.
`tests/test_tab_workspace_projection_contract.py` checks the live bottom-dock
projection and manager-to-notebook update path.
The underlying `tests/test_tab_groups.py` suite covers persistence, four search
scopes, pinning, grouping, docking, ARIA attributes, and axis-aware keyboard
navigation.

Suggested articles: [Appearance presets](../appearance-presets/README.md),
[Local history](../local-history/README.md), and
[Scheduled settings](../scheduled-settings/README.md).
