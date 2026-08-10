<<<<<<< HEAD
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
protection. Persisted top/bottom docking projects into the live AGW notebook,
and left/right now project into a real keyboard-selectable Material side rail
that mirrors the notebook's pages and active selection. AGW still retains its
native tab header underneath because the control does not expose a supported
hide-header flag; group headers remain a follow-up while the saved discovery
contract stays intact.

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
=======
# Browser-style tabs and groups

`amulet_map_editor.api.tab_groups` is the reusable state and search contract for
browser-style tabs. It is wx-independent so native wx surfaces and the Material
3 documentation surface can project the same state without duplicating rules.

## Behaviour

- A surface stores a bounded, versioned tab list and named groups.
- The tab strip can dock to `left`, `top`, `right`, or `bottom`; new state uses
  `left` and vertical keyboard navigation.
- Tabs retain order, a protected `pinned` flag, group membership, and the active
  tab. Groups retain order and their expanded/collapsed state.
- State is persisted through the existing profile configuration store under a
  surface-scoped identifier. Invalid or over-sized profile data is normalised
  to safe limits (256 tabs and 64 groups).

## Four search contracts

`TabWorkspace` exposes four independent search methods:

1. `search_strip` searches visible tab titles in the current strip.
2. `search_group` searches titles inside one named group.
3. `search_group_names` searches group names.
4. `search_master` searches all tabs owned by the surface.

Each search is plain-text-first and delegates compilation, length limits, regex
opt-in, flags, and nested-quantifier protection to the shared `RegexBuilder`.
Results identify the tab, group, pinned state, search scope, and current dock so
a future UI can teleport to the exact result without losing its group state.

## Accessibility projection

`tab_strip_aria`, `tab_aria`, and `tab_keyboard_target` provide stable ARIA and
roving-focus semantics. `apply_wx_tab_accessibility` applies the safe subset
(`SetName` and `SetHelpText`) when a wx control supplies those methods and always
returns the complete attribute map for a richer native adapter.

This commit supplies the reusable contract and tests; it does **not** claim that
every existing notebook or dialog has already migrated to the new tab strip.
Migration remains a separate UI lane so existing world-editor close and unsaved
work behaviour stays intact.

## Failure and security boundaries

- Empty, control-character, duplicate, unknown, and over-sized identifiers are
  rejected or discarded during normalisation.
- Invalid explicit regex patterns raise `ValueError`; ordinary text such as `[` is
  escaped and remains a literal search.
- Persistence uses the application's existing profile store and never writes a
  `.git` directory into a user project.

## Verification

`tests/test_tab_groups.py` covers round-trip migration, persistence, all four
searches, regex validation, docking, pinned/group state, ARIA attributes, and
keyboard navigation without importing wx.

### Suggested articles

- [Appearance presets](../appearance-presets/README.md) — customize the tab
  chrome after a surface adopts the contract.
- [Local history](../local-history/README.md) — record tab and group changes in
  an append-only profile history.
- [Scheduled settings](../scheduled-settings/README.md) — schedule a dock or
  appearance override while preserving the base value.

>>>>>>> codex/tab-group-contract
