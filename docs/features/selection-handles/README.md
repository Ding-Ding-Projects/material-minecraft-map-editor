# Grab handles on the selection box

The selection box could be resized by dragging a face, drawn out from scratch,
and typed into. It could not be *moved* by dragging — the only ways to shift a
box that was already the right size were to retype six coordinates or to hold a
button down while pressing the movement keys. "How do I move the thing" had no
answer involving the box itself.

It now has fourteen: six face handles and eight corner handles, drawn on the
box, grabbed with the pointer.

![The selection box with its grab handles: eight gold corner cubes, orange
cubes at the centre of each face, and the handle under the pointer drawn larger
and in magenta.](../../huishots/selection-handles.png)

## Behaviour

**A face handle moves the box along that face's own axis.** One degree of
freedom: a drag that wanders sideways on screen still changes one coordinate.
They are orange, at the centre of each face.

**A corner handle moves the box in a plane.** Two degrees of freedom, in the
plane most square-on to the camera, which is what makes the box appear to
follow the cursor rather than slide away from it. They are gold, at the eight
corners.

Both resolve to a **world** offset, not a pixel offset. A box twenty blocks away
and a box two hundred blocks away each move by what is under the cursor, which
is the difference between a handle that feels attached to the box and one that
feels attached to the mouse. The offset is rounded to whole blocks, because a
selection box's corners are whole blocks.

**The handle under the pointer is drawn larger and in magenta**, and the pointer
becomes a hand. Two channels rather than one: colour alone is the channel some
readers do not have.

**Releasing commits the move.** Pressing <kbd>Escape</kbd> mid-drag puts the box
back where it started, like every other edit in this tool.

**A drag moves; it never resizes.** Both corners take the same offset. The
existing resize gesture — press a highlighted face and drag — is unchanged, and
a handle takes priority over the face behind it so a press does the thing the
pointer was showing.

### Handles that cannot work are withheld, not left inert

A face handle whose axis points at the viewer cannot be dragged: its axis has no
width on screen, so the cursor has nothing to move it along, and the arithmetic
turns a pixel into an unbounded jump. Those handles are **not drawn** rather than
drawn and dead — a control that looks operable and is not is worse than no
control. The cutoff is 26 degrees.

Looking straight down, that is both y face handles:

![The same box from directly above. The two vertical face handles are gone; the
four horizontal ones and all eight corners remain, with one corner
hovered.](../../huishots/selection-handles-top-down.png)

Nothing is lost by it. The corner handles beside them move the box in that same
plane, and they are never edge-on, because their plane is chosen to face the
camera.

For reference, the same box with the handles turned off — the state it is in
while a box is being drawn out or resized:

![The selection box with no handles: cyan edges, the green and blue point
markers, and nothing to grab.](../../huishots/selection-handles-before.png)

## Doing it without a pointer

Everything a handle does — translate the box by whole blocks on any of the three
axes — is reachable from the keyboard.

**The Move selection button** in the select tool moves the whole box with the
movement keys. It used to require the box-click action to be *held*, and that
action's default binding is the left mouse button, so the route needed a mouse
to start and was therefore no keyboard route at all. It now also listens while
it has keyboard focus: tab to it and press the movement keys. The same applies
to the two point buttons beside it and to the paste tool's move button.

**The six coordinate boxes** in the select tool each carry arrow-key stepping.
Moving both points by the same amount is the same translation a handle performs,
on any axis. It is six edits where a handle is one drag — equivalent in what it
can express, not in how many keystrokes it takes, which is why the focus route
above matters.

## Configuration

The handle colours live beside the rest of the box palette in
`amulet_map_editor/api/opengl/mesh/selection/box/colours.json`:

| Key | What it colours |
| --- | --- |
| `box_handle` | The six face handles |
| `box_handle_corner` | The eight corner handles |
| `box_handle_hover` | Whichever handle the pointer is over |

Sizes are not configurable and scale with the box instead: a handle is a sixth
of the box's smallest side, bounded so that the handles on a single block are
still big enough to aim at and the handles on a 400-block region are not the
region.

## Failure modes

**A ray that says nothing leaves the box alone.** Looking away from the drag
plane, or straight down the drag axis, produces no answer, and the box stays
where it is rather than being sent somewhere invented.

**Handles ignore the depth buffer,** exactly as the box outline does, so a
handle behind terrain is still visible. That matches the hit test, which is a
ray against fourteen cubes and has no notion of occlusion either. A handle you
could grab without being able to see would be worse.

**Top-down is an orthographic projection**, so its rays are parallel and start
above the pointer rather than at the camera. The drag builds its ray that way in
that mode; using the camera position there would resolve the drag against a ray
nobody is pointing along.

**One pre-existing defect was fixed on the way.** The editor's cursor ray applied
its screen offset only when *both* components were non-zero, so a pointer
anywhere on the exact horizontal or vertical centre line of the viewport was
read as being at the centre of the screen. Dragging across either centre line
stuck. The same construction is now shared by the drag and by the editor's own
block picking, so the fix reaches both.

## What this does not cover

**The paste tool's pending object has no handles.** It is moved by clicking to
put it down, by the arrow keys, by its nudge buttons and by its Position boxes —
see [Where a pasted copy lands](../paste-anchor/README.md). Giving it handles
means drawing a box around a structure that may be rotated and scaled, which is
a different piece of work from this one; nothing here blocks it.

## Verification

`tests/test_selection_box_handles.py` — the arithmetic. Two of its cases work
the expected answer out by hand (a plane intersection and a closest-approach on
a line) rather than restating the code. The one that matters most presses on a
handle at one point on screen, drags to another, projects the moved box back
through the same camera matrix the renderer uses, and asserts it landed there:
a drag that moved the box the right way by the wrong amount fails it.

`tests/test_selection_box_handle_wiring.py` — the wiring. Every input goes in as
a real event through the canvas, dispatched by wx, so a handler that was written
and never bound fails instead of passing.

`tests/test_selection_keyboard_equivalence.py` — the keyboard routes, including
the focus gate that had to be built.

Every one of those guards was watched failing against a deliberate break before
it was kept — including one that had to be rewritten because it passed against
the break it existed to catch: it compared the hover size against the constant
that sets the hover size, so setting that constant to 1.0 satisfied it.

`scripts/capture_selection_handles.py` renders the real mesh through the real
shader in a real OpenGL context and reads the framebuffer back. The three images
above came from it. It exits non-zero when the frame comes back empty, because a
capture harness that reports success over a blank rectangle is worse than none.
