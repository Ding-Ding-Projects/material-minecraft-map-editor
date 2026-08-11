# Terrain tools

Eight surfaces for changing the shape of the ground rather than the blocks in
it. They live on the Terrain ribbon tab.

## Behaviour

| Surface | What it does |
| --- | --- |
| **Terrain brush** (`terrainBrush`) | Raise, lower, or sculpt terrain with a bounded brush. |
| **Smooth terrain** (`smooth`) | Average height across the selection, with a strength and an iteration count. |
| **Flatten to height** (`flatten`) | Level the selection to one Y, filling below and clearing above. |
| **Erosion** (`erosion`) | Simulate weathering across the selection, bounded by iterations. |
| **Noise fill** (`noiseGen`) | Fill with a noise field: type, scale, octaves, and a threshold. |
| **Sea level** (`seaLevel`) | Raise or lower water to a chosen level. |
| **Regenerate chunks** (`regenerate`) | Let the game regenerate the selected chunks. |
| **Repaint surface** (`surfacePaint`) | Replace the surface layer with a chosen block or pattern. |

Every numeric control is a bounded range with a live readout, so a strength or
an octave count cannot be set to something the operation cannot perform. Every
block choice shows a generated placeholder swatch, labelled as one.

## Configuration

Brush shape and radius are shared with the MCEdit2 brush settings, so the two
groups do not drift into two different brushes. Ranges, their bounds, and their
step sizes are part of each surface's description rather than being decided at
draw time.

## Failure modes

**Regenerate chunks is destructive and irreversible in the game's own terms** —
it discards what was there and lets the generator produce something else. It
passes the two-key gate: two independently operated keys, then a full-range
slider, with an emergency exit available throughout. The gate names the exact
chunk count and dimension before it will authorise anything.

Every other terrain operation is one commit in the project repository and can be
restored, and restoring writes a new revision rather than rewinding.

An operation over an empty selection reports that nothing would change rather
than reporting success. An iteration count large enough to take a long time
reports its progress and stays cancellable rather than appearing to hang.

## Security and accessibility

These surfaces read and write the open world only. No network access, no
temporary copies outside the application's own data area.

Sliders are keyboard-operable with arrow keys and expose their value in their
accessible name, so the readout is available without seeing it. Each surface
scrolls rather than clipping at a high display scale.

## Verification

```powershell
py -3 -m pytest tests/test_studio_spec_registry.py -q
```

That proves every range in these surfaces has a usable span with its value
inside it and a positive step, that every dropdown defaults to one of its own
options, and that every footer action resolves. Running the operations against a
real world needs a build.

Suggested articles: [build tools](../build/README.md),
[MCEdit2 tool set](../mcedit2-tools/README.md),
[world generation tools](../worldgen/README.md), and
[destructive-action gate](../destructive-gate/README.md).
