# Project shell

Amulet Studio is built from exactly two views, and the shell owns both. The
**backstage** is where a project is started, opened, inspected, or converted.
The **workspace** is where one is edited. They are swapped rather than stacked,
so there is never a half-visible start screen behind an open world, and never a
ribbon over a window with nothing loaded.

This replaced the previous single start card plus tool strip. The world
notebook that shell used still exists — it owns world loading, per-page
unsaved-work protection, and the tab dock the tab manager edits — but it is no
longer the interface. It is handed to the workspace viewport once a world is
open, so the real renderer draws inside the new shell rather than beside it.

## Behaviour

`StudioShell` (`amulet_map_editor/api/studio/shell.py`) is the frame's only
child. It builds three things and swaps two of them:

- `StudioTitleBar` — the frameless caption, the project title, the saved-state
  indicator, and the window controls. The operating system's own title bar is
  never shown as product chrome.
- `BackstageView` — Home with a template gallery and a searchable, filterable
  recent table; Open; Project info; Convert; **All surfaces**; and a route back
  to the workspace.
- `WorkspaceView` — the seventeen-tab ribbon, the breadcrumb context bar with
  the head revision, the navigator, the viewport and its overlays, the tabbed
  properties pane, and the status bar.

`show_backstage(tab)` and `show_workspace()` move between them. `open_project`,
`attach_project`, `detach_project`, and `close_project` keep the title bar, the
workspace, the status bar, and the recent list agreeing about what is open.
`set_saved` writes the unsaved-work state to every surface that shows it at
once, so the title bar and the status bar cannot disagree.

Every window, panel, and tool the application can open is addressed by a
**surface key**. `amulet_map_editor/api/studio/surfaces.py` decides what a key
actually opens: a declarative spec, one of the two hand-built windows, or a
dialog that predates this shell. A caller never has to know which.

Anything that is not a window is a **command** —
`amulet_map_editor/api/studio/commands.py` — and `run_command` carries it out.
Keeping the two apart is what lets a ribbon tile, a context-menu row, and a
palette result all name one target without knowing how it is performed.

## Configuration

The shell reads the shared preference profile through the School-mode
projection, so theme, density, accent, interface font, interface scale,
language mode, and both funny levels reach it without a per-surface opt-in. A
scheduled rule overrides the persisted value for as long as it is active.
`refresh_theme()` re-resolves the tokens and repaints everything, so an
appearance change lands live rather than at the next launch.

## Failure modes

If the Studio package cannot be constructed at all, the frame logs the
traceback and falls back to the world notebook rather than opening an empty
window. This is deliberate: a build with a broken shell should still open
worlds.

`open_surface` returns `None` when nothing opened, and says so where the user
can see it. A button that silently does nothing is indistinguishable from a
broken application, so every failure names the exact key it was asked for and
routes the report through the non-blocking notifier.

A surface that is indexed but has neither a route nor a spec is a defect the
suite asserts on rather than something a user discovers as a dead button —
`surfaces.unrouted_keys()` must be empty.

## Security and accessibility

Nothing in the shell reaches the network. Fonts fall back through a local
candidate list, block previews are generated from base colours, and there is no
sign-in, telemetry, or cloud storage anywhere in the two views.

Every interactive control sets an accessible name, paints a visible focus ring,
answers Return and Space as well as a click, and takes its minimum height from
`tokens.control_height()` so a compact profile still leaves a usable target.
Long labels elide or wrap rather than being painted past their control, which
is what keeps bilingual mode — two lines per label — from clipping.

## Verification

```powershell
py -3 -m pytest tests/test_studio_shell_hosting_contract.py tests/test_studio_surface_index.py -q
```

Those two files check the wiring and the census: the frame builds the shell,
the old chrome is hidden rather than drawn beside it, the fallback still exists,
and every surface named in the feature inventory is present and openable.
Neither of them is runtime proof. Rendering evidence needs a real build on a
Windows desktop, and no capture of this interface has been taken yet.

Suggested articles: [backstage](../backstage/README.md),
[ribbon](../ribbon/README.md),
[spec renderer](../spec-renderer/README.md), and
[per-project version history](../project-history/README.md).
