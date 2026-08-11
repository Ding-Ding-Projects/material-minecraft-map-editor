# Editing tools

The editing surfaces are the ones a selection passes through: choosing what to
select, moving to it, describing it, and writing it back out.

## Behaviour

Twelve surfaces make up the group, reached from the Home, Selection, Operations,
and Structures ribbon tabs, from the command palette, or from the backstage's
**All surfaces** page:

| Surface | What it does |
| --- | --- |
| **Teleport** (`goto`) | Move the camera and the selection anchor to an exact coordinate, in a chosen dimension. |
| **Select block** (`blockSelect`) | Pick a block state by namespace, name, and properties, with a generated preview of its faces. |
| **Select biome** (`biomeSelect`) | Pick a biome by identifier, with its colour. |
| **Select version** (`versionSelect`) | Choose the platform and version a value should be interpreted in. |
| **Import chunks** (`importChunks`) | Bring chunks in from another world or region file. |
| **Export selection** (`exportStructure`) | Write the selection out as a structure file. |
| **Operations** (`operationOptions`) | The editor's Operation tool, on whichever operation it was last showing. |
| **Clone operation** (`operationClone`) | The Operation tool with the stock Clone operation selected. |
| **Fill operation** (`operationFill`) | The Operation tool with the stock Fill operation selected. |
| **Replace operation** (`operationReplace`) | The Operation tool with the stock Replace operation selected. |
| **Set biome operation** (`operationSetBiome`) | The Operation tool with the stock Set Biome operation selected. |
| **Waterlog operation** (`operationWaterlog`) | The Operation tool with the stock Waterlog operation selected. |

The first six are declarative surfaces, so their fields, dropdowns, lists,
ranges, and checks all come from the shared controls: every dropdown is
searchable with a regex opt-in and a `.*` builder, every path field has a native
browse button beside the free-text entry, and every coordinate is an
axis-coloured vector field.

The last six are not windows at all. Each activates the editor's own Operation
tool in the viewport, and the five that name an operation ask the tool to select
that operation, so its options and its **Run Operation** button are showing
without the list having to be searched first. That is why they are five keys and
not one: they shared `operationOptions` until this build, which meant every tile
started the same tool and left its list on whatever sorted first — alphabetically
Clone, so the Clone tile looked correct while Fill, Replace, Set biome and
Waterlog all quietly opened Clone.

Selection state itself lives in the navigator and the status bar, so a tool
never has to restate where the selection is; it acts on it.

## Configuration

Block, biome, and version pickers read the loaded world's own registries. The
preview beside a chosen block is a **generated placeholder swatch**, labelled as
one; a real texture arrives from a loaded Minecraft installation, a resource
pack, or a PNG dropped on the slot.

Export formats are the ones the format layer supports: `.construction`,
`.mcstructure`, legacy `.schematic`, and Sponge `.schem`.

## Failure modes

An operation that would affect nothing says so before it runs rather than
reporting success over an empty selection. A coordinate outside the world's
height range is refused with the range named. A structure file the format layer
cannot read is reported with the format it was expected to be, not as a generic
failure.

An operation tile asks the tool for its operation and then asks the tool back
which one it is showing. When those disagree — a plugin removed, a group renamed,
a build without that operation installed — the tile reports which operation was
asked for and which one arrived, rather than leaving somebody in front of a form
that edits something else. The tool says the same thing on its own account: an
operation it cannot find is named in a non-blocking notification alongside the
one still selected.

Every applied operation is one commit in the project repository, so it can be
restored — and restoring writes a new revision rather than rewinding.

Import and export both preview what they will touch before touching it, and
report anything they excluded rather than claiming a whole batch succeeded.

## Security and accessibility

Structure files are read from and written to paths the user chose. A typed path
and a browsed path run through exactly the same validation, so a browsed value
is never trusted more than a typed one. Nothing is fetched over the network.

Every control is keyboard reachable with a visible focus ring and an accessible
name, coordinates use the monospaced face so they are unambiguous, and each
window scrolls rather than clipping at a high display scale.

## Verification

```powershell
py -3 -m pytest tests/test_studio_spec_registry.py tests/test_studio_surface_index.py -q
py -3 -m pytest tests/test_editor_operations_runtime.py -q
```

The first pair prove every surface in this group exists, is reachable, is
structurally complete, and that each footer action opens a real surface or runs
a real command — all of it read from source, so none of it can tell whether an
operation renders.

The second opens a real world in a real frame, presses each of the five stock
operation tiles through the same `open_surface` route a press takes, and reads
the operation back off the tool's own list. Five assertions naming five
different operations, each with the count of visible **Run Operation** controls
that operation exposes, so a build where the tiles collapse back onto one key
leaves exactly one of them green.

Suggested articles: [where a pasted copy lands](../paste-anchor/README.md),
[MCEdit2 tool set](../mcedit2-tools/README.md),
[navigator](../navigator/README.md),
[texture previews](../texture-previews/README.md), and
[exports](../exports/README.md).
