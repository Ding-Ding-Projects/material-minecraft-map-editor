# Viewport

The viewport is the middle of the workspace: the rendered world, and the
overlays that say what you are looking at. It hosts the real renderer rather
than drawing a picture of one — the world notebook that owns world loading is
re-parented into this pane once a project is open.

## Behaviour

`ViewportHost` (`amulet_map_editor/api/studio/viewport.py`) owns the pane and
the overlays drawn on top of it:

- **HUD chips** — the camera position, the block under the cursor, the active
  dimension, the render distance, and the frame rate, each monospaced so a
  coordinate reads exactly.
- **Axes legend** — the orientation indicator, coloured per axis consistently
  with the coordinate fields elsewhere in the shell.
- The **canvas** itself, set by `StudioShell.set_canvas`.

Before a project is open, and while one is loading, the pane shows what is
actually happening — an honest empty state or the loader's real progress — not a
blank rectangle and not a decorative screenshot.

Right-clicking the viewport opens the viewport context menu: searchable, with
each entry's keyboard shortcut shown right-aligned, and carrying
**Edit appearance…** like every other menu.

## Configuration

Render layers, view settings, the four-up split, cutaway, and the work plane are
surfaces of their own, reached from the View and Panels ribbon tabs or by name
from the command palette. The viewport reads the same appearance tokens as the
rest of the shell, so the HUD follows the theme rather than being fixed light or
dark.

## Failure modes

If the renderer cannot be created — no OpenGL, a driver refusal, a world that
fails to load — the pane says so in place, with the reason, and the rest of the
workspace stays usable. The failure is logged with its traceback.

The HUD reports what it actually knows. A value that has not arrived yet is
shown as pending rather than as a zero, because a coordinate readout of `0, 0,
0` is indistinguishable from a real position at the origin.

Overlays never intercept a click meant for the canvas, and they never cover the
control that opened them.

## Security and accessibility

Nothing here fetches anything. Block previews used by the surrounding surfaces
are generated locally from base colours; real textures come only from a loaded
Minecraft installation, a resource pack, or a PNG the user drops on a slot.

The HUD chips have accessible names carrying their values, so the position and
the hovered block are available without seeing the overlay. Every overlay is
readable at the contrast the tokens guarantee, and reduced-motion settings are
respected — the shell has no animation that a reader has to wait out.

## Verification

```powershell
py -3 -m pytest tests/test_studio_accessibility_contract.py -q
```

That proves the pane and its overlays name themselves and follow the theme.
Rendering itself cannot be proven by a static check: it needs a real build with
wxPython and a working OpenGL context, and no capture of this pane exists yet.

Suggested articles: [navigator](../navigator/README.md),
[properties pane](../properties-pane/README.md),
[panels and views](../panels/README.md), and
[texture previews](../texture-previews/README.md).
