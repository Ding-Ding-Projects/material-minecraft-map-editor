# Codex handoff — Material Minecraft Map Editor M3 completion

## Mission

Finish and verify the checked-in Material 3 migration without replacing working map-editor logic, changing world data semantics, or inventing a second architecture. Start from the exact pinned `0.10` revision, apply this kit, then hunt regressions in the changed surfaces and the remaining legacy dialogs identified by the repository's own roadmap.

Do not overengineer. Prefer small fixes, existing controllers/models, owner-drawn shared components, and explicit tests.

## Deterministic baseline

```text
Repository: https://github.com/Ding-Ding-Projects/material-minecraft-map-editor
Branch:     0.10
Commit:     684c9f2be1e72188314a3f9f9cfbb8e2a484476f
Work branch: codex/m3-completion
```

The repository already contains a meaningful M3 foundation. Preserve its preferences, scheduled runtime, School mode, tab/group state, update UI, history, documentation, notifications, title bar, editor models, and world-operation contracts.

## Implemented in this kit

### 1. Theme traversal performance and consistency

`amulet_map_editor/api/wx/material3.py` is replaced with an implementation that:

- resolves `preferences.load()`, `scheduled_runtime.current_values()`, and the bounded element-override map once per complete style pass;
- carries an immutable `MaterialThemeContext` through that pass;
- walks the window tree iteratively;
- lays out and refreshes only the traversal root;
- preserves the existing public/internal helper names used by current tests and components;
- preserves dialog/frame M3 title-bar integration and element-appearance overrides;
- adds coherent primary, secondary, surface-container, outline, error, disabled, and on-colour roles;
- correctly resolves the persisted `system` theme from the host OS appearance and restyles top-level surfaces on system-colour changes;
- keeps opted-out renderer subtrees untouched.

This directly removes the old recursive preference/override I/O and repeated layout amplification on large editor trees.

### 2. Owner-drawn control input correctness

`amulet_map_editor/api/wx/components.py` is replaced with hardened controls:

- `MaterialButton` and `MaterialWindowButton` recover from mouse-capture loss;
- mouse capture is used consistently for press/release semantics;
- Return/Space arm once and activate on key-up, so auto-repeat cannot invoke a command repeatedly;
- disabled controls clear press state;
- dynamic labels no longer replace explicitly assigned accessible control names;
- parent surface colours are respected during owner-drawn painting;
- existing accessible names, focus rings, labels, event types, and class names remain compatible.

### 3. Pure M3 command menus

The kit adds:

```text
amulet_map_editor/api/material_menu.py
amulet_map_editor/api/wx/components.py::MaterialSearchField
amulet_map_editor/api/wx/components.py::MaterialMenu
```

The headless model provides:

- literal matching; no user-supplied regex compilation;
- Unicode NFKC/case-fold normalisation;
- label, description, section, and keyword search;
- a 256-character query cap;
- a 200-result cap;
- stable ranking and roving selection that skips disabled items.

The wx view provides:

- an owner-drawn M3 popup surface;
- keyboard Up/Down/Home/End/Enter/Escape behaviour;
- bounded scrolling and display-edge clamping;
- an accessible search field and command names;
- command IDs/callbacks compatible with the old `wx.Menu` path;
- explicit Escape/activation dismissal returns focus to the opening control without stealing focus on click-away.

`patches/apply_completion.py` rewrites only `AmuletUI.create_menu`, preserving the existing menu dictionary and page extension contract.

### 4. Small verified logic fixes

The integration patch also:

- updates the two stale deferred-theme assertions in the pinned test to require the already-used `apply_material3_deferred` helper;
- prevents a second scheduled-settings worker while the previous one is alive;
- retains the five-minute cadence;
- removes the identical `if/else` branches in notebook page-change handling.

## Codex execution phases

### Phase 1 — materialize and inspect

Run:

```powershell
.\bootstrap.ps1
```

Then inspect:

```powershell
git -C .\material-minecraft-map-editor-m3-complete status --short
git -C .\material-minecraft-map-editor-m3-complete diff --check
git -C .\material-minecraft-map-editor-m3-complete diff
```

Do not discard unrelated upstream work. The bootstrap refuses dirty existing worktrees and the patcher fails when structural anchors do not match.

### Phase 2 — focused correctness gates

From the materialized repository:

```powershell
python scripts\validate-m3-completion.py --repo .
python -m pytest -q tests\test_material_menu.py tests\test_m3_completion_contract.py
python -m pytest -q tests\test_material3_global_contract.py tests\test_material_components_contract.py tests\test_material3_common_control_roles.py tests\test_m3_surface_inventory.py
```

Then run the full repository test suite using its supported development environment. Fix failures at their source; do not weaken assertions merely to turn CI green.

### Phase 3 — native Windows runtime matrix

Use the repository's supported Python/wxPython environment. Capture actual built-window evidence for:

1. Light and dark themes.
2. Compact, comfortable, and spacious density.
3. Default and increased UI scale.
4. A narrow window and a normal desktop window.
5. English and any checked-in bilingual/localised mode supported by the current preferences.
6. Empty main menu, one open world, and multiple world tabs.

For each pass verify:

- title bar drag/minimise/maximise/restore/close;
- command menu opening by mouse and keyboard;
- literal searches containing `[`, `*`, `?`, `(`, `\\`, and non-ASCII text;
- Up/Down/Home/End/Enter/Escape navigation;
- no duplicate command activation when Return/Space is held;
- popup remains on-screen near every display edge;
- right-click appearance menu opens, edits, resets, and restyles;
- preferences and scheduled theme changes restyle the full shell;
- repeated dialog open/close does not leave orphan popups or captured mouse state;
- OpenGL/editor canvases retain renderer-owned colours;
- opening a large editor page does not show the previous recursive restyle lag.

### Phase 4 — bounded bug hunt

Concentrate on regressions adjacent to this change:

- stale/destroyed wx objects after popup dismissal;
- callback signatures/IDs from page-provided menu extensions;
- focus restoration after dismissal;
- menu sections containing disabled or dynamically changing commands;
- multi-monitor scaling and negative display coordinates;
- scheduled worker shutdown during app close;
- legacy dialogs that still visibly violate the checked-in M3 surface inventory.

Do not rewrite world loaders, chunk operations, rendering, update transport, persistence formats, or tab state unless a failing test/runtime trace proves the changed M3 work caused the defect.

### Phase 5 — release evidence and packaging

Before declaring completion:

```powershell
git diff --check
python -m pytest -q
python scripts\validate-m3-completion.py --repo .
```

Store runtime screenshots/logs under a clearly named evidence directory, record exact Python/wx/OS versions, and package with:

```powershell
python package_completed_codebase.py --source . --output ..\material-minecraft-map-editor-m3-complete.zip
```

## Commit plan

Keep commits reviewable:

1. `fix(ui): make Material 3 styling a single-pass traversal`
2. `fix(ui): harden owner-drawn button input state`
3. `feat(ui): replace command bar native menus with searchable M3 popups`
4. `fix(runtime): prevent overlapping scheduled preference refreshes`
5. `test(ui): add M3 menu and completion regression coverage`
6. `docs(ui): record native runtime evidence and remaining limitations`

Combine only when changes are inseparable. Do not create abstraction-only cleanup commits.

## Stop conditions

Do not claim release-ready until all of these are true:

- focused and full tests pass;
- a real Windows/wxPython run has completed;
- at least one real world opens and closes without regression;
- editor canvas rendering remains correct;
- menu mouse/keyboard/accessibility paths are exercised;
- no native `wx.Menu` remains in the command-bar path;
- evidence distinguishes static checks from runtime proof.
