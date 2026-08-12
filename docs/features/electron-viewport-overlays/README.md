# Viewport selection-box and grid overlays (WebGL2)

Without a selection box the Electron viewport can display a world but cannot
be used to edit one -- there is nowhere on screen that says "this is the
region an export, fill, or clone is about to act on". This feature adds that
box, plus a reference grid, to the WebGL2 viewport introduced by
`docs/site/viewport-webgl.js`.

## What it is

`docs/site/viewport-overlays.js` is a standalone browser script (UMD-style,
matching `viewport-webgl.js`'s own convention) exporting
`window.AmuletViewportOverlays`. It draws:

- **A selection box**: translucent faces, a cyan wireframe outline, and two
  small marker cubes at the exact `point1`/`point2` locations, tinted green
  and blue respectively.
- **A reference grid**: a ground-plane grid on the XZ plane, centred under
  the camera, so placing a box in otherwise-empty space is not guesswork.

Both are optional and independent: call `setSelection`/`clearSelection` and
`setGrid`/`clearGrid` as the app's selection state changes. When nothing is
selected, nothing selection-shaped is drawn -- a zero-size box at the origin
would read as a bug, not as "nothing selected".

## Matching the desktop app's existing look

The look is not invented here. It mirrors the wxPython desktop app's own
selection box, defined in:

- `amulet_map_editor/api/opengl/mesh/selection/box/render_selection.py` --
  translucent faces drawn first (depth test on, so terrain in front still
  occludes the box), then a wireframe outline drawn with depth test
  *disabled* so the outline always reads even when the box is buried in
  terrain (`RenderSelection.draw()`).
- `amulet_map_editor/api/opengl/mesh/selection/box/colours.json` -- the
  palette: `box_point1` green `(0, 1, 0)`, `box_point2` blue `(0, 0, 1)`,
  `box_edge` cyan `(0.5, 1.0, 1.0)`.
- `render_selection_editable.py`'s `point1_colour`/`point2_colour`, which
  confirm the green/blue convention is per-point, not per-corner-of-the-box
  (point1 and point2 are the two corners the user actually placed; the box's
  min/max are those two points sorted).

This module simplifies one thing relative to the desktop app: instead of the
full 8-corner-handle system in `handles.py` (used for interactive resizing
in the desktop editor, ~540 lines of drag/plane-projection math), it draws
small fixed-size marker cubes at `point1` and `point2` themselves. Resize
handles and drag interaction are a natural follow-up and are out of scope
for this pass, which is about the box being *visible* and *correctly
coloured*, not yet draggable in the web viewport.

## Integration call site

This module owns no `<canvas>` and no `WebGL2RenderingContext` of its own.
It is handed the same context and the same `projection * view` transform
matrix `viewport-webgl.js` already builds for drawing the chunk mesh, and
draws on top of whatever is already in that framebuffer:

```js
var overlay = new window.AmuletViewportOverlays.SelectionOverlay(viewport.gl);
overlay.setGrid({ y: 0 });                 // optional; omit/clearGrid() to hide
overlay.setSelection(point1, point2);      // [x, y, z] arrays
overlay.clearSelection();                  // ...or this, when nothing is selected

// after viewport.render() has drawn the chunk mesh into the same canvas:
overlay.render(transform, viewport.camera.position);
```

`transform` is the exact `mat4Multiply(projection, view)` value
`viewport-webgl.js` computes internally for its own draw call -- pull it out
the same way `scripts/capture_viewport_overlays_render.js` does, or expose
it from `Viewport` if the owning code needs it repeatedly. Building the
overlay's own camera matrix instead would risk the overlay and the terrain
drifting apart frame to frame; sharing one matrix rules that out entirely.

The module is host-agnostic: it does not know about Electron, IPC, or where
the viewport is mounted in the shell, so it slots into whichever surface
ends up hosting `viewport-webgl.js`'s `Viewport`.

## Behaviour

- **Selection box**: faces (12% white alpha) drawn first with depth test on;
  wireframe edges (cyan) and point markers (green/blue) drawn after with
  depth test disabled, so the outline and markers always read through
  terrain -- exactly `RenderSelection.draw()`'s ordering.
- **Degenerate box**: `point1 === point2` produces a valid, well-formed,
  zero-volume vertex set rather than throwing or emitting `NaN`.
- **No selection**: `render()` skips the selection pass entirely when
  `clearSelection()` was called (or `setSelection` was never called).
- **Grid**: an independent XZ-plane grid, re-centred on the camera's X/Z
  each frame so it always appears to extend to the horizon rather than
  scrolling out of view as the camera moves.
- Blend/cull/depth GL state is saved and restored around the overlay draw,
  so it never leaks state into whatever the caller renders next.

## Testing

- `tests/test_viewport_overlay_geometry.py` runs the module's pure geometry
  functions (`_buildBoxEdgeVertices`, `_buildBoxFaceVertices`,
  `_buildGridVertices`, `_buildMarkerCube`, `_sortedBounds`, `_pointInBox`)
  through Node and checks the vertex data arithmetically: edge/face counts,
  bounds, corner membership, degenerate-box safety, and the public
  `SelectionOverlay` API shape. No GPU is required for any of this, matching
  how the same repository checks `totp.js`/`qr.js`.
- `scripts/capture_viewport_overlays_render.js` is the headless GPU proof.
  It launches the packaged Electron shell with `AMULET_HEADLESS=1` (never
  shows a window), loads a small standalone harness page that pulls in
  `viewport-webgl.js` + `viewport-overlays.js` directly (no sidecar, no real
  world -- `scripts/capture_viewport_render.js` already proves the real
  chunk-mesh pipeline; this proves the overlay draw pass specifically),
  renders one frame with the overlay and one without, reads both PNGs back
  with `canvas.toDataURL()` (`Page.captureScreenshot` hangs indefinitely
  against this WebGL2 canvas -- see the repo-wide note on this), and asserts
  the two frames differ by more than 200 pixels. Output lands in
  `docs/huishots/electron/viewport-overlay-{with,without}-selection.png`.

Run both:

```
py -3.11 -m pytest tests/test_viewport_overlay_geometry.py -q
node scripts/capture_viewport_overlays_render.js
```

## Known limitations / follow-up

- No drag/resize interaction yet -- this pass draws the box; wiring pointer
  input to move it (mirroring `handles.py`'s face/corner handle math) is a
  natural next feature.
- The grid is a fixed 1-block default spacing; an app-level zoom-aware
  spacing (finer up close, coarser far away, as many editors do) is not
  implemented.
