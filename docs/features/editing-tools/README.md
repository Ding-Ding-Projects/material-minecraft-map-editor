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
that operation, so its options are in front of you without the list having to be
searched first. That is why they are five keys and not one: they shared
`operationOptions` until this build, which meant every tile started the same tool
and left its list on whatever sorted first — alphabetically Clone, so the Clone
tile looked correct while Fill, Replace, Set biome and Waterlog all quietly
opened Clone.

The tile promises the options, not the **Run Operation** button under them. An
operation's panel scrolls when its options are taller than the pane, and Replace
is: it stacks a source block picker and a replacement block picker, so in a
1500×950 window its Run button starts 557 px below the bottom edge of the frame
and is reached by scrolling. That is measured rather than assumed — see the
verification below — and it is why the tile's copy says *selected with its
options showing* rather than *ready to run*.

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

A confirmed placement that wrote nothing says so where it happened. The editor's
own progress path catches the exception, so a paste that raised and a paste that
wrote four hundred blocks come back identical to the caller; the bridge
therefore reads the world's undo depth either side of the confirm, and a depth
that did not move is reported as a refusal rather than as a placement. The
refusal names the operation, says the world is unchanged, says the copy is still
being held, and gives both ways out — through a non-blocking notification and in
the pending panel, which stays on screen precisely because the copy is still
held. Taking the panel away is what a *successful* placement looks like, so
doing it after a failure would make the two indistinguishable. The refusal is
dropped as soon as another object is lifted, so it can never be read as a report
about the new one.

A pending position past the world's limits is clamped to the nearest position
inside them and reported as the move it is, with the boxes showing the value the
tool actually took. Calling a clamp a failure would take the pending panel away
from a copy that is still held and still drawn, which is the same defect in the
other direction.

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
py -3 -m pytest tests/test_editor_confirm_outcome.py tests/test_pending_failure_ui_contract.py tests/test_pending_move_reporting.py -q
py -3 -m pytest tests/test_editor_clone_runtime.py -q
```

The first pair prove every surface in this group exists, is reachable, is
structurally complete, and that each footer action opens a real surface or runs
a real command — all of it read from source, so none of it can tell whether an
operation renders.

The second opens a real world in a real frame, presses each of the five stock
operation tiles through the same `open_surface` route a press takes, and reads
the operation back off the tool's own list. Five assertions naming five
different operations, so a build where the tiles collapse back onto one key
leaves exactly one of them green.

It also measures where each **Run Operation** control is, rather than asking
whether it is shown. `IsShown()` walked up the ancestor chain, and
`IsShownOnScreen()`, both answer `True` for Replace's Run button while it sits
557 px below the bottom edge of the frame, because neither is a question about
*where* anything is — so the first version of that check went green for a button
that appears in no screenshot of that window at any size. The control's
rectangle now has to fit inside the client area of every window above it, and
the assertion is that the panel can scroll it into view: a Run control laid out
past the end of the scrollable area cannot be scrolled to, which is the shape a
change pushing one off its panel would take, and that goes red.

Both are skipped whole when the world does not open, which reads exactly like
passing in a summary line, so two things back them up. `MMME_REQUIRE_EDITOR_RUNTIME=1`
turns every skip into a failure that names its reason — a fresh checkout skips
because `chunk_builder_cy` has not been compiled there, not because the machine
is flaky. And `tests/test_stock_operation_tiles.py` asserts the tile, its key,
and the operation that key asks for with nothing running at all, so the collapse
this group was rewired to prevent cannot hide behind an environment that could
not start:

```powershell
py -3 -m pytest tests/test_stock_operation_tiles.py -q
```

The third group covers what a placement reports: the branches and the wording
against a stand-in world whose paste raises, the pane keeping its panel and
rendering the sentence, and the position bridge's clamping policy — including
two tests that go red if anyone makes a clamped move report failure.

The fourth opens a real world and reads the undo depth through the bridge's own
reader either side of a real paste. That is the only check that proves a real
canvas and a real level answer to the attribute path the refusal is built on: a
wrong path makes the reader answer nothing at both ends, which is treated as
"the question could not be asked" and reported as success, so every other test
in this area stays green while the check is switched off.

Suggested articles: [where a pasted copy lands](../paste-anchor/README.md),
[MCEdit2 tool set](../mcedit2-tools/README.md),
[navigator](../navigator/README.md),
[texture previews](../texture-previews/README.md), and
[exports](../exports/README.md).
