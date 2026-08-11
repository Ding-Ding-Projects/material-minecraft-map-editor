# Panels and views

Nineteen surfaces that show the application's own state or change how the world
is drawn. They live on the View, Panels, and Extend ribbon tabs and are the
largest group in the surface index.

## Behaviour

**Inspecting what is loaded**

| Surface | What it shows |
| --- | --- |
| **Inspector** (`inspector`) | The selected object's full record. |
| **Pending imports** (`pendingImports`) | Structures staged but not yet placed. |
| **Players** (`playerPanel`) | The players the world carries. |
| **Inventory editor** (`inventoryEditor`) | One inventory as a slot grid. |
| **Item types** (`itemTypeList`) | Every item type the loaded version defines. |
| **Configure blocks and items** (`configureBlocks`) | How blocks and items are matched and displayed. |
| **Schematic library** (`libraryPanel`) | The saved structures on this machine. |

**Changing how the world is drawn**

| Surface | What it does |
| --- | --- |
| **Render layers** (`renderLayers`) | All twelve layers, each toggleable. |
| **View settings** (`viewControls`) | Projection, field of view, render distance, and fog. |
| **Four-up split** (`fourUpView`) | Three orthographic views beside the perspective one. |
| **Cutaway** (`cutawayView`) | Hide everything above a plane, so interiors are visible. |
| **Work plane** (`workPlane`) | The plane new blocks are placed on. |

**The application's own state**

| Surface | What it shows |
| --- | --- |
| **Minecraft installs** (`minecraftInstalls`) | The installations found on this machine, and a path field for one that was not. |
| **Plugins** (`pluginsDialog`) | The installed operation plugins. |
| **Project history** (`history`) | The commit graph, with Diff and Restore. |
| **Log** (`logView`) | This session's log, filterable by level. |
| **Profiler** (`profiler`) | Where frame time is going. |
| **Python console** (`pythonConsole`) | A console for the operation API. |
| **Error report** (`errorReport`) | The last failure with its full traceback, and a copy action. |

Every list carries the shared search field with its regex opt-in and `.*`
builder. Every panel is a normal surface: reachable by name from the command
palette, listed in the backstage, and openable from a ribbon tile.

## Configuration

Render layer visibility, view settings, and the work plane persist per project.
Panel sizes and positions persist per surface and have a reset path back to
their defaults.

Minecraft installations are discovered lazily, so a slow or missing drive delays
nothing at startup, and a location can always be added by hand through a path
field with a native browse button.

## Failure modes

A panel with nothing to show shows real empty-state copy naming how it would get
content — never a fabricated sample row.

The Python console runs against the operation API with the application's own
permissions. It is a real console: it can change the open world, and everything
it changes is recorded as a commit like any other action.

The error report shows the real traceback rather than a summary, and copies it
verbatim; it does not send anything anywhere.

## Security and accessibility

Nothing here reaches the network, including the update and installation panels,
which read local state only. The log and the error report are shown to the user
and copied on request; neither is transmitted, and neither is written outside
the application's own data area.

Every panel is keyboard reachable with visible focus, every row is named, and
panels are resizable and draggable within the viewport bounds so one can always
be grabbed back after being moved to an edge.

## Verification

```powershell
py -3 -m pytest tests/test_studio_surface_index.py tests/test_studio_spec_registry.py -q
```

Those prove all nineteen are present in the index under this group and that each
opens something real.

Suggested articles: [viewport](../viewport/README.md),
[properties pane](../properties-pane/README.md),
[automation](../automation/README.md), and
[per-project version history](../project-history/README.md).
