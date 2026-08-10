# Start here

This archive contains the **actual Material 3 completion code**, tests, a fail-closed integration patch, and a Codex handoff for:

`Ding-Ding-Projects/material-minecraft-map-editor`

It is pinned to branch `0.10` at commit:

```text
684c9f2be1e72188314a3f9f9cfbb8e2a484476f
```

## Fastest path on Windows

From PowerShell in this extracted kit:

```powershell
.\bootstrap.ps1
```

That command:

1. Clones the exact pinned repository revision.
2. Creates `codex/m3-completion`.
3. Copies the complete replacement/new files.
4. Applies the small `AmuletUI` integration patch.
5. Runs the focused static/contract tests available in the checkout.
6. Produces `material-minecraft-map-editor-m3-complete.zip` beside the worktree.

To apply it to an existing **clean** checkout already at the pinned commit:

```powershell
.\bootstrap.ps1 -Repo "C:\src\material-minecraft-map-editor"
```

Python can be called directly on any platform:

```bash
python bootstrap.py
python bootstrap.py --repo /path/to/clean/checkout
```

## What is already implemented

- A single immutable Material theme context per style pass instead of preference, schedule, and element-override reads for every child control.
- Non-recursive window-tree styling and one root layout, removing repeated descendant layout work.
- Expanded light/dark Material 3 roles, correct live OS-following `system` theme resolution, density/font scaling, and contrast-derived on-colours.
- Mouse-capture-loss recovery, one-shot key-up activation, stable accessible names on dynamic labels, and explicit popup focus restoration.
- A custom searchable `MaterialMenu`/`MaterialSearchField` popup, replacing the command bar's native `wx.Menu` UI.
- Literal, case-folded, bounded command filtering with headless tests.
- A guard against overlapping scheduled-settings worker threads.
- Removal of the duplicate notebook branch that executed the same operation in both paths.

## Evidence boundary

This environment could inspect the public source and create/test the implementation overlay, but it could not transfer a complete GitHub checkout into the artifact sandbox. Therefore, this ZIP is a **deterministic codebase materialization kit**, not a misleading partial checkout presented as a compiled release.

The included code passed Python parsing, 11 headless/contract tests, synthetic integration-patch application, patch idempotence, and an end-to-end local clone/materialize/test/package simulation. Native Windows/wxPython rendering, world loading, GPU canvas behaviour, packaging, and release screenshots still require a real supported runtime and are explicit Codex acceptance gates.

Read next:

- `CODEX_HANDOFF_M3_COMPLETION.md`
- `BUG_AUDIT.md`
- `RECOMMENDED_CHANGES.md`
- `ACCEPTANCE_MATRIX.md`
- `VALIDATION_REPORT.md`
