# Backstage

The backstage is what Amulet Studio opens on and what it returns to when a
project is closed. It is a full view rather than a dialog: starting a project,
finding one you had open last week, reading what a world actually contains, and
converting it between platforms are all first-class work, not a preamble to the
real interface.

## Behaviour

`BackstageView` (`amulet_map_editor/api/studio/backstage.py`) draws a left rail
of pages and one content area:

- **Home** — a greeting, a template gallery for starting a new project, and the
  recent table.
- **Open** — the world picker, listing worlds detected from installed Minecraft
  locations alongside a browse-for-folder path for anything not discovered.
- **Project info** — what the selected world is: platform, version, dimensions,
  size on disk, and when it was last written.
- **Convert** — source world, destination world, and the translation the
  conversion will perform.
- **All surfaces** — every window, panel, and tool the application can open,
  grouped exactly as the feature inventory groups them, with a search field.
- **Workspace** — the way back into an open project.

The **recent table** is searchable and filterable. Filter chips narrow it by
kind; the search field beside them carries the regex opt-in and the `.*`
builder, like every other search field in the product. Rows show the project
name, its path, its platform, and when it was last opened, with the path
rendered monospaced so it can be read exactly.

The **All surfaces** page is the readable form of the same index the command
palette searches. Each row gives the surface's name, the one-line description
the ribbon tile uses for it, and its keyboard shortcut when it has one.

Selecting anything that opens a world hands the path to the frame, which owns
world loading and the unsaved-work protection that goes with it. The backstage
does not open worlds itself.

## Configuration

Recent projects are stored locally by
`amulet_map_editor/api/studio/recents.py`. Nothing about a project leaves this
machine; the record is a name, a path, a platform, and a timestamp.

The template gallery, the filter chips, and the surface index all read the same
registries the rest of the shell reads, so a surface added to the index appears
here without any change to this view.

## Failure modes

A world that cannot be read is listed with what went wrong rather than omitted,
because a world silently missing from a list reads as data loss. Discovery of
installed Minecraft locations is deferred so a slow or unavailable drive delays
nothing at startup.

An empty recent list shows real empty-state copy and the two real ways to
proceed — start from a template, or browse for a world — never a fabricated
sample project. A search that matches nothing says so and repeats what it
searched for.

Bulk actions on the recent table preview exactly what they will affect and
report anything they excluded rather than reporting a whole batch as done.

## Security and accessibility

Paths are shown verbatim and are never rewritten for display, so what is on
screen is what will be opened. No path, project name, or world content is
transmitted anywhere.

The rail is keyboard-navigable with visible focus, every row and tile has an
accessible name, and the tables reflow at narrow widths rather than clipping
their last column. Bilingual mode renders a prominent English line above a
compact Cantonese one, and the layout is checked at the widths and display
scales that produces.

## Verification

```powershell
py -3 -m pytest tests/test_studio_surface_index.py tests/test_studio_regex_builder_coverage.py -q
```

The first proves the surface index this page renders is complete and that every
row opens something; the second proves this page's two search fields still carry
the regex builder. Neither is a picture of the page — no runtime capture of the
backstage exists yet.

Suggested articles: [project shell](../project-shell/README.md),
[ribbon](../ribbon/README.md),
[bulk actions](../bulk-actions/README.md), and
[search, regular expressions, and the command palette](../search-and-regex/README.md).
