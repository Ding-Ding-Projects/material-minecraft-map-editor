# Tabs and groups

The desktop app exposes **View → Tabs and groups…** and the same destination in
the `Ctrl+Shift+F` command palette. The native Material 3 surface searches open
tabs in plain-text mode by default and has an adjacent bounded regex builder.

The manager projects the reusable `amulet_map_editor.api.tab_groups` state and
search contract into the existing notebook without duplicating persistence or
search rules. It persists the tab strip edge (`left`, `top`, `right`, or
`bottom`), pinned-first ordering, named groups, group membership, and active-tab
teleportation. Selecting **Activate selected** returns to the real notebook page
rather than opening a duplicate surface. Invalid regex input is handled as an
empty result and never changes tab state.

The current notebook remains the source of truth for rendering and close/dirty
protection. Persisted top/bottom docking projects into the live AGW notebook,
and left/right project into a keyboard-selectable Material side rail that mirrors
the notebook's pages and active selection. AGW retains its native tab header
because the control does not expose a supported hide-header flag; group headers
remain a follow-up while the saved discovery contract stays intact.

The manager also provides **Close tabs containing text** and **Close tabs not
containing text**. Both actions use their own plain-text-first query and adjacent
regex builder, show a reviewable count before closing, protect pinned tabs unless
**Include pinned** is selected, and route each real close through the notebook's
existing unsaved-work veto. Skipped pages are counted instead of being silently
reported as closed.

## Reusable state and four searches

A surface stores bounded, versioned tab and group state. `TabWorkspace` exposes
four independent plain-text-first searches, each using the shared `RegexBuilder`
for bounded regex opt-in, flags, validation, and nested-quantifier protection:

1. `search_strip` searches visible tab titles in the current strip.
2. `search_group` searches titles inside one named group.
3. `search_group_names` searches group names.
4. `search_master` searches all tabs owned by the surface.

Results identify the tab, group, pinned state, scope, and dock, so a native
surface can teleport to the exact result without losing collapsed-group state.
`tab_strip_aria`, `tab_aria`, and `tab_keyboard_target` provide axis-aware
roving-focus semantics; `apply_wx_tab_accessibility` projects the safe native
subset through `SetName` and `SetHelpText`.

## Failure modes and security

- Search is bounded to 256 characters and evaluates locally.
- Invalid patterns produce no matches and do not mutate state.
- Empty, control-character, duplicate, unknown, and over-sized persisted IDs
  are rejected or discarded during `TabWorkspace` normalization.
- Group and pin changes are saved through the versioned app configuration; the
  contract never creates a `.git` directory in a user project.

## Verification

`tests/test_tab_manager_ui_contract.py` checks the native M3 shell, regex
builder, persisted operations, View-menu route, and command-palette route.
`tests/test_tab_workspace_projection_contract.py` checks the live bottom-dock
projection and manager-to-notebook update path.
`tests/test_tab_groups.py` covers round-trip migration, persistence, all four
search scopes, pinning, grouping, docking, ARIA attributes, and axis-aware
keyboard navigation without importing wx.

### Suggested articles

- [Appearance presets](../appearance-presets/README.md) — customize tab chrome
  after a surface adopts the contract.
- [Local history](../local-history/README.md) — record tab and group changes in
  append-only profile history.
- [Scheduled settings](../scheduled-settings/README.md) — schedule a dock or
  appearance override while preserving the base value.
