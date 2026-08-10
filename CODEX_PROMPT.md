# Copy-paste Codex prompt

Work in the materialized `Ding-Ding-Projects/material-minecraft-map-editor` checkout on branch `codex/m3-completion`.

Read `BUG_AUDIT.md`, `CODEX_HANDOFF_M3_COMPLETION.md`, `RECOMMENDED_CHANGES.md`, `ACCEPTANCE_MATRIX.md`, the repository `AGENTS.md`, `HANDOFF.md`, `ROADMAP.md`, and `docs/features/material-shell/README.md` before editing.

The implementation overlay has already fixed the verified M3 theme traversal, system-theme resolution, owner-drawn input/accessibility, command-menu/focus, scheduled-worker overlap, stale deferred-test contract, and duplicate notebook-branch defects. Do not discard it or rebuild unrelated editor architecture.

Proceed in phases:

1. Inspect `git diff` and run the supplied focused validators/tests.
2. Fix only concrete failures while preserving current world/editor controllers and persistence contracts.
3. Run the full repository tests in the supported environment.
4. Run the native Windows/wxPython matrix in the handoff, including a real world/editor canvas, light/dark/density/scale, menu metacharacter search, keyboard repeat, capture loss, context appearance, and multi-monitor edges.
5. Hunt adjacent regressions and remaining visibly legacy M3 surfaces identified by the checked-in roadmap. Keep fixes small and test-backed.
6. Record exact runtime evidence and package the completed full checkout.

Do not overengineer. Do not weaken tests, invent success, claim static checks are runtime proof, or rewrite map/world logic without a reproducing failure.
