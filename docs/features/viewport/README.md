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
**Edit appearance…** like every other menu. The shortcuts on the selection and
projection rows are read from the user's own 3D editor key configuration, not
from the shipped defaults, so a rebound key is the one the menu prints.

**While a renderer canvas is hosted, the right button belongs to the camera.**
Right-drag rotates the view and right-click changes mouse mode, so no menu
opens over the live world — not the viewport menu and not the shared two-row
appearance popup the Material layer otherwise binds to every window it styles.
A menu that opens on that gesture does not merely add a menu, it cancels the
drag mid-motion, which is what made looking around impossible. The viewport
panel and the canvas it hosts both set `_material3_appearance_menu_disabled`,
which the shared handler now reads when the menu is raised rather than only
when it is bound — the canvas is created and styled inside the world notebook
long before this pane is handed it, so a bind-time-only check came too late to
see it.

Nothing is lost, only moved off the plain right button:

- The **HUD overlays** — chips, minimap, compass, tool buttons, corner
  handles — are separate windows and still raise **Edit appearance…** on an
  ordinary right-click.
- **Shift+right-click** over the viewport opens the viewport menu, whose last
  row is **Edit appearance…** for the pane itself.
- The **Element appearance** surface, from the command palette, edits whatever
  control has focus.

With no renderer attached — the drawn stand-in before a world is open — a plain
right-click opens the viewport menu as before.

**Deselect active box** and **Deselect all boxes** run the same two changes the
editor's `ACT_DESELECT_BOX` and `ACT_DESELECT_ALL_BOXES` keys make: one drops
the active box from the selection, the other clears it. They were greyed out
while printing those very keys, which taught the reader a working feature was
missing; a row that cannot run now prints no shortcut at all.

## Moving the overlays

Every heads-up overlay sits on top of the world, so whichever corner of the map
you want to look at, something is over it. They are movable.

Four **groups** move, each with its own grab handle — a faint dotted gutter down
the left of the group, which brightens on hover and takes the move cursor:

| Group | What moves together | Where it ships |
| --- | --- | --- |
| Readouts | the four monospaced chips | top left |
| Minimap and compass | the map card and the heading dial | top right |
| Axis key | the axes legend | bottom left |
| View tools | the four square tool buttons | bottom right |

They move as groups rather than as individual controls for two reasons. The
readout chips are re-measured twice a second as the numbers behind them change,
so four independently placed chips would drift into each other the moment the
camera moved; and the tool column and the map stack are single design objects
whose members mean nothing apart. Grouping also gives each handle a body big
enough to actually take hold of.

**The selection corner handles are deliberately not movable.** They are not
chrome floating over the world — each one marks a block coordinate, so moving
one somewhere more convenient would be a lie about where the selection is.

- **Pointer** — drag the handle. The group follows the pointer from wherever it
  was picked up, rather than snapping its corner to the cursor.
- **Keyboard** — focus a handle and press an arrow key. The distance is stated
  on the handle itself, in its accessible name and its tooltip, and again in a
  hint that appears beside the handle while it is hovered or focused. The
  numbers there are read from the live display scale rather than written out, so
  the sentence stays true at every zoom level.
- **Reset** — `Home` on a handle puts that group back; `Shift`+`Home` puts every
  group back. **Reset overlay positions** in the viewport's own right-click menu
  and in the command palette does the same thing for somebody who moved an
  overlay with the pointer and never focused a handle.

A group is always clamped inside the view, so nothing can be dragged somewhere
the pointer could not reach it again. The clamp is full containment rather than
"leave a few pixels showing", because a handle is ten pixels wide and a rule
that leaves ten pixels visible can leave exactly the wrong ten — the far edge of
a tool column, with the handle itself off the window.

A position is remembered as the **distance from the two edges its group is
anchored to**, never as an absolute point. That is what makes an overlay parked
sixteen pixels in from the bottom-right still sixteen pixels in from the
bottom-right after the window is resized, instead of off the edge of a smaller
window and halfway up a larger one. Positions are re-clamped on every resize, so
an overlay parked in the far corner of a large window is pulled back into view
when the window shrinks rather than vanishing.

Dragging a handle never reaches the world underneath it: a handle is a separate
child window, so the press is delivered to it and the renderer never sees the
gesture that would have rotated the camera. It also never consumes an overlay's
own action — clicking the minimap still opens **Go to**, and a tool button still
runs its tool, because the handle is a different window from the control it
moves and there is nothing to guess between.

Positions live in the `amulet_studio_overlay_layout` profile entry, keyed
`viewport.<group>`. Only groups that have actually been moved are stored, so a
reset forgets rather than storing the default a second time. A profile that
cannot be written loses the remembered position and nothing else — the overlay
still moves, and the viewport carries on.

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
py -3 -m pytest tests/test_viewport_overlay_drag.py -q
```

The first proves the pane and its overlays name themselves and follow the theme.

The second builds a real `ViewportHost` and drives it: it drags each group from
A to B through the widget's own mouse handlers and checks it arrived, drags one
at the edges and checks it stayed reachable, shrinks the window and checks a
parked overlay came back, presses the arrow keys and checks the distance matches
the one the handle advertises, destroys the window and rebuilds it and checks
the position survived, and — with a precondition proving each callback is live
first — checks that a drag turns no camera and steals no minimap click. It also
renders a handle into a bitmap and reads the pixels, because a handle that draws
nothing is a handle nobody can find.

Rendering the world itself cannot be proven by a static check: it needs a real
build with wxPython and a working OpenGL context.

Every overlay draws through `render_to`, which is what both the screen and the
capture harness call. That is not a formality: `MinimapView`, `CompassView`,
`ViewportToolButton` and `CornerHandle` painted only in `EVT_PAINT`, so a
capture fell back to `StudioButton.render_to` and photographed all four as empty
rounded buttons — a picture with the map, the compass and both selection handles
missing, and a capture report saying every one of them had drawn.

Suggested articles: [navigator](../navigator/README.md),
[properties pane](../properties-pane/README.md),
[panels and views](../panels/README.md), and
[texture previews](../texture-previews/README.md).
