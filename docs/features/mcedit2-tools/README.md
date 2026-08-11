# MCEdit2 tool set

Fifteen surfaces carrying the tool set MCEdit2 users expect, so a habit learned
in that editor still works here. They live on the Tools, Selection, and
Operations ribbon tabs and in the surface index under **MCEdit2 tools**.

## Behaviour

| Surface | What it does |
| --- | --- |
| **Shape brush** (`brushTool`) | Paint with a shape: sphere, cube, cylinder, or diamond, at a chosen radius. |
| **Brush** (`brushSettings`) | The brush's own settings: shape, size, falloff, and the block or pattern it paints. |
| **Flood fill** (`floodFill`) | Replace a connected region of one block with another, bounded by a limit. |
| **Clone** (`cloneTool`) | Copy the selection to another position, with repeats and offsets. |
| **Move** (`moveTool`) | Move the selection, leaving air or a chosen fill behind. |
| **Generate** (`generateTool`) | Generate structures, including an L-system generator. |
| **Select block** (`selectBlockTool`) | Select every block matching a state. |
| **Select entity** (`selectEntityTool`) | Select entities by type and by NBT predicate. |
| **Edit chunk** (`editChunkTool`) | Edit a single chunk's own records. |
| **Tool settings** (`toolSettings`) | The shared settings every tool reads. |
| **Blocks** (`findReplaceBlocks`) | Find and replace block states across a region. |
| **Commands** (`findReplaceCommands`) | Find and replace inside command blocks. |
| **NBT** (`findReplaceNbt`) | Find and replace inside raw NBT. |
| **Analyze** (`analyzeTool`) | Count what a region contains. |
| **Import map image** (`importMap`) | Turn an image into blocks, with a palette and a dithering choice. |

Each find-and-replace surface pairs a search section with the shared search
behaviour: plain text by default, regular expressions as an explicit opt-in with
the `.*` builder beside the field, and an invalid pattern reported rather than
treated as a pattern that matches nothing.

## Configuration

Brush shape, size, and falloff persist between uses, as do the tool settings the
whole group shares. Block and pattern choices show a generated placeholder
swatch, labelled as one.

Image import reads a local file chosen through a path field with a native browse
button; the same validation runs whether the path was typed or browsed.

## Failure modes

A tool with nothing selected says what it needs rather than running over an
empty region. A replacement that would affect nothing reports the count as zero
instead of reporting success.

Flood fill is bounded, so a fill that would run away is stopped and reports the
limit it hit rather than locking the application.

Every applied tool is one commit in the project repository. Anything
irreversible passes the two-key gate first.

Find and replace previews the exact count it will change, and reports anything
excluded rather than folding it silently into the total.

## Security and accessibility

Nothing here fetches anything; an imported image comes from a local path the
user chose. Patterns are evaluated locally by Python's `re` module, bounded in
length, so a pathological expression is refused before it reaches the engine.

Every control is keyboard reachable, focus is visible, and each surface's own
window search filters its sections live. Numbers and identifiers use the
monospaced face.

## Verification

```powershell
py -3 -m pytest tests/test_studio_spec_registry.py tests/test_studio_search_contract.py -q
```

The first proves all fifteen surfaces are complete and reachable; the second
proves the search behaviour the three find-and-replace surfaces depend on,
including that an invalid pattern matches nothing and says why.

Suggested articles: [editing tools](../editing-tools/README.md),
[terrain tools](../terrain/README.md),
[build tools](../build/README.md), and
[search, regular expressions, and the command palette](../search-and-regex/README.md).
