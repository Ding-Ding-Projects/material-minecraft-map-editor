# Validation report

## Target

```text
Repository: Ding-Ding-Projects/material-minecraft-map-editor
Branch:     0.10
Commit:     684c9f2be1e72188314a3f9f9cfbb8e2a484476f
Release:    0.10.0-dev.466
```

## Passed in the artifact environment

### Supplied-source gate

Command:

```bash
PYTHONDONTWRITEBYTECODE=1 python run_static_checks.py
```

Result:

```text
11 passed
AST parsed 10 Python files
Synthetic integration patch and idempotence passed
All available static checks passed
```

The contract suite verifies the bounded wx-free menu model, one-pass theme inputs, iterative traversal, one root layout, frozen theme mappings, system-theme resolution/live refresh hook, non-recursive custom best sizing, deferred-theme API compatibility, capture-loss recovery, one-shot key activation, stable explicit accessible names, custom popup/focus paths, and command-menu integration markers.

### End-to-end materializer simulation

A temporary local Git origin was created with the exact structural anchors used by the pinned revision. The actual `bootstrap.py` module then performed its clone, detached baseline checkout, completion-branch creation, overlay copy, fail-closed patch, validator, focused tests, and deterministic full-worktree packaging paths.

Result:

```text
Material 3 completion static validation passed
12 passed in the materialized synthetic worktree
Packaged 19 files in the synthetic full-worktree fixture
ZIP integrity passed
M3 integration was idempotent on the second application
```

This simulation validates the materializer mechanics; it is not a substitute for the real repository's native runtime.

### Determinism and safety checks

- Python parsing used `ast.parse` for every supplied `.py` file.
- The integration patch requires exact structural anchors and refuses ambiguous/missing anchors.
- The stale deferred-theme test correction requires exactly one copy of each old assertion or exactly one copy of each new assertion.
- Reapplying the integration patch produces no source changes.
- Packaging fixes ZIP timestamps, sorts paths, preserves executable bits, excludes Git/caches/backups, writes SHA-256, and checks archive integrity.
- The final implementation manifest hashes every listed implementation/documentation input.

## Not run here

The following require a supported GitHub-connected Windows/wxPython environment and remain explicit Codex release gates:

- importing and running the full application with its pinned dependencies;
- native light/dark/system-theme rendering, DPI, multi-monitor popup, focus, and screen-reader behavior;
- full repository pytest/CI suite;
- opening, editing, saving, closing, and reopening representative real worlds;
- OpenGL/editor-canvas verification and GPU/driver coverage;
- long-running memory/handle/capture checks;
- installer/release packaging and screenshots.

Static checks establish source contracts and headless behavior only. They do not justify claiming that every possible bug in a complex map editor is fixed.

## Environment

```text
Python:   3.13.5
pytest:   9.0.2
Platform: Linux 6.18.35 x86_64, glibc 2.41
wxPython: not imported or executed
```
