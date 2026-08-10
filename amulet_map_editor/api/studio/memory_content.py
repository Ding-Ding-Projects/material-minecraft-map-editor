"""The wx-free content behind the Memory Console.

The console is thirteen views over records this application keeps on the local
machine, plus a reader over every feature article shipped with the build.  None
of that is markup, so none of it lives in the window class: the views and the
articles are data here, and :mod:`amulet_map_editor.api.studio.memory_console`
renders them.  Keeping the split means the content can be searched, counted,
and exported without a display, and a new view is a tuple entry rather than a
new panel.

Nothing in this module reaches the network, opens a file, or reads a
preference.  It imports only :mod:`amulet_map_editor.api.studio.search`, which
is itself wx-free, so it stays importable anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass
import html
import json
from typing import Dict, Optional, Sequence, Tuple

from amulet_map_editor.api.studio.search import SearchState

#: The rail key of the view that renders the two-pane article reader instead of
#: a plain card grid.  The console asks for it by name rather than comparing
#: against a literal in three places.
DOCS_VIEW_KEY = "docs"

#: The grid the design lays cards out on.  A card declares how many of these
#: columns it spans; the console wraps to a new row when the next card will not
#: fit in what is left.
GRID_COLUMNS = 12

#: File suffixes :func:`render_article` can write, in the order the export
#: dialog offers them.  Markdown is first because it is the source form.
ARTICLE_FORMATS: Tuple[str, ...] = (".md", ".txt", ".html", ".json")


# ---------------------------------------------------------------------------
# data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CardRow:
    """One clickable record inside a card.

    ``target`` is what activating the row does: ``view:<key>`` moves the
    console to another view, ``article:<path>`` opens the reader on one
    article, and an empty target means the row is a record whose ``note`` is
    shown instead.  A row therefore always does something -- a row that looked
    pressable and did nothing would be worse than plain text.
    """

    name: str
    detail: str = ""
    tag: str = ""
    note: str = ""
    target: str = ""

    def haystack(self) -> str:
        """Return everything a search over this row should read."""
        return " ".join((self.name, self.detail, self.tag, self.note))


@dataclass(frozen=True)
class MemoryCard:
    """One card in a view: a title, and any of a statistic, prose, rows, code.

    ``span`` is how many of the twelve grid columns the card occupies.  Every
    part below the title is optional, so a card carrying only a large number is
    as ordinary as one carrying a list of records and a transcript.
    """

    title: str
    span: int = 6
    stat: str = ""
    body: str = ""
    rows: Tuple[CardRow, ...] = ()
    code: str = ""

    def haystack(self) -> str:
        """Return everything a search over this card should read."""
        parts = [self.title, self.stat, self.body, self.code]
        parts.extend(row.haystack() for row in self.rows)
        return " ".join(part for part in parts if part)


@dataclass(frozen=True)
class MemoryView:
    """One rail entry and the page it shows."""

    key: str
    label: str
    glyph: str
    title: str
    subtitle: str
    cards: Tuple[MemoryCard, ...] = ()

    def haystack(self) -> str:
        """Return everything a search over this whole view should read."""
        parts = [self.label, self.title, self.subtitle]
        parts.extend(card.haystack() for card in self.cards)
        return " ".join(part for part in parts if part)


@dataclass(frozen=True)
class Article:
    """One feature article: where it lives, what it covers, and its text.

    ``path`` is the article's source location in the repository, shown
    monospaced in the reader and used verbatim when the path is copied or the
    article is opened in an external editor.
    """

    title: str
    path: str
    domain: str
    summary: str
    body: str

    def haystack(self) -> str:
        """Return everything a search over this article should read."""
        return "\n".join((self.title, self.path, self.domain, self.summary, self.body))

    def paragraphs(self) -> Tuple[str, ...]:
        """Return the body split into the paragraphs it was written as."""
        return tuple(
            block.strip() for block in self.body.split("\n\n") if block.strip()
        )


# ---------------------------------------------------------------------------
# articles
# ---------------------------------------------------------------------------

#: The reader's domain filter, in the order the pills are drawn.  A domain is a
#: grouping of feature areas rather than a folder, so an article moving between
#: folders does not silently leave its filter behind.
DOMAINS: Tuple[str, ...] = (
    "Project shell",
    "Editing",
    "World data",
    "Terrain and build",
    "Analysis",
    "Panels",
    "Settings",
    "Global",
)


ARTICLES: Tuple[Article, ...] = (
    Article(
        title="Project shell",
        path="docs/features/project-shell/README.md",
        domain="Project shell",
        summary=(
            "The two views the application is built from: a backstage for "
            "starting and opening projects, and a ribbon workspace for editing "
            "one."
        ),
        body=(
            "Behaviour. The shell holds exactly two views and swaps between "
            "them rather than stacking windows. The backstage is where a "
            "project begins: a template gallery, a searchable and filterable "
            "table of recent projects, an Open page, project information, the "
            "converter, and an index of every surface the application has. "
            "Opening or creating a project moves the shell to the workspace, "
            "which carries the seventeen ribbon tabs, a breadcrumb context bar "
            "showing the head revision, the navigator, the viewport and its "
            "overlay, the properties pane, and the status bar. Closing a "
            "project returns to the backstage with the recent table already "
            "updated.\n\n"
            "Configuration. Theme, density, accent, interface font, interface "
            "scale, language mode, and both tone sliders apply to both views "
            "and take effect without a restart. The ribbon can be collapsed, "
            "the properties pane can be hidden, and both states persist per "
            "profile. The shell's displayed name is a preference: renaming it "
            "changes the title bar and the About surface and nothing else, so "
            "the profile directory, the update feed, and every stored record "
            "keep the shipped identity.\n\n"
            "Failure modes. A world that cannot be read leaves the backstage "
            "in place and reports the exact reason rather than opening an "
            "empty workspace. A recent entry whose files have moved is marked "
            "as missing instead of being removed, because a silently shorter "
            "list reads as data loss. A surface that fails to open reports "
            "which surface and why through a notification and leaves the rest "
            "of the shell usable.\n\n"
            "Security considerations. Paths reaching the shell from a recent "
            "entry, a drop, or another surface are validated before they are "
            "opened, and a path that resolves outside the world it claims to "
            "belong to is refused. Nothing in either view contacts the "
            "network: fonts fall back to installed faces and block previews "
            "are generated locally.\n\n"
            "Verification. Tests open and close a project, assert that the "
            "view swaps in both directions, and assert that the recent table "
            "records the change. Captures of both views are taken from the "
            "built application at 100, 125, 150, and 200 per cent display "
            "scale and in bilingual mode, where the labels are longest."
        ),
    ),
    Article(
        title="Per-project version history",
        path="docs/features/project-history/README.md",
        domain="Project shell",
        summary=(
            "The isolated repository beside each project that makes undo depth "
            "unlimited and makes restoring safe."
        ),
        body=(
            "Behaviour. Every project owns a small repository kept beside its "
            "world data, and every applied operation, rename, and selection "
            "change writes one revision into it. Restoring a revision writes a "
            "new revision describing the restore rather than rewinding "
            "history, so the state you restored from remains available to "
            "restore in turn. The same store is surfaced in five places: the "
            "project history graph with its Diff and Restore actions, the undo "
            "history with jump-to-point, the breadcrumb context bar, the "
            "status bar, and the properties pane's History tab.\n\n"
            "Configuration. The repository lives beside the project data and "
            "never inside the user's own folder, so a world directory is never "
            "turned into a repository behind the user's back. Retention, "
            "pruning, and export are user controls; nothing is pruned "
            "automatically. The store is local and is never pushed anywhere "
            "unless the user explicitly asks for it.\n\n"
            "Failure modes. A history write that fails never fails the "
            "operation the user actually asked for: the failure is logged and "
            "reported, and the edit still lands. A repository that cannot be "
            "created at all disables the history surfaces and says so plainly, "
            "rather than showing an empty graph that reads as a project with "
            "no past.\n\n"
            "Security considerations. Snapshots preserve whatever encryption "
            "the live data already uses, so the history is never more "
            "sensitive than the store it mirrors. Records are bound to stable "
            "identifiers that survive delete and restore, because binding them "
            "to a row number makes a restored record undecryptable in a way "
            "that looks exactly like corruption.\n\n"
            "Verification. Tests cover recording, restoring, restoring a "
            "restore, an unwritable repository, and a failed write during an "
            "operation. A round-trip test asserts that the state before a "
            "restore is still reachable afterwards."
        ),
    ),
    Article(
        title="Editing tools",
        path="docs/features/editing-tools/README.md",
        domain="Editing",
        summary=(
            "Selection, paste, chunk work, import and export, teleport, and "
            "the pickers that feed them."
        ),
        body=(
            "Behaviour. The editing surfaces share one selection model. The "
            "selection tool defines and edits boxes, the paste tool places a "
            "clipboard or an imported structure with an offset and a rotation, "
            "the chunk tool works on whole chunks, and import and export move "
            "regions in and out of the project. Teleport moves the camera to a "
            "coordinate, a player, or a structure. Block, biome, and version "
            "pickers are searchable dropdowns that feed every one of these "
            "surfaces from the same catalogue.\n\n"
            "Configuration. Each tool remembers its last settings per project. "
            "The pickers default to plain-text search with a regular "
            "expression as an explicit opt-in, and every one of them carries "
            "the pattern builder beside the field. Operations that run over a "
            "large region report progress and remain cancellable.\n\n"
            "Failure modes. An operation over a region that is partly unloaded "
            "loads what it needs and reports any chunk it could not read, "
            "naming the coordinates rather than failing the whole run. A paste "
            "whose source version differs from the target is converted, and "
            "the conversion result is reported before it is applied. A "
            "cancelled operation reports what it had already written.\n\n"
            "Security considerations. Import reads only the file it was given "
            "and refuses a structure whose declared size exceeds the bound the "
            "reader enforces. Nothing is fetched over the network, and an "
            "imported file is never executed.\n\n"
            "Verification. Tests cover an empty selection, a single-block "
            "selection, a selection spanning chunk and region boundaries, a "
            "cross-version paste, a cancelled operation, and an operation over "
            "an unloaded region."
        ),
    ),
    Article(
        title="MCEdit2 tool set",
        path="docs/features/mcedit2-tools/README.md",
        domain="Editing",
        summary=(
            "The brush, flood fill, clone, move, generate, select, chunk edit, "
            "find and replace, analyse, and image import tools."
        ),
        body=(
            "Behaviour. This set reproduces the tools long-time editors "
            "expect: a configurable brush, flood fill, clone and move, a "
            "generator including an L-system, block and entity selection, "
            "direct chunk editing, find and replace over blocks, commands, and "
            "tag data, an analysis pass, and import of a map image. Each tool "
            "has its own settings surface and writes through the same "
            "operation pipeline as everything else, so each one records a "
            "revision.\n\n"
            "Configuration. Tool settings persist per project and can be "
            "reset per tool or all at once. The brush exposes its shape, "
            "radius, falloff, and the block or pattern it paints. Find and "
            "replace defaults to plain text with a regular expression as an "
            "opt-in, and reports the exact match count before it changes "
            "anything.\n\n"
            "Failure modes. A generator asked for a shape larger than the "
            "configured bound refuses with the bound stated rather than "
            "exhausting memory. Find and replace over an invalid pattern "
            "reports the compilation error and matches nothing, instead of "
            "quietly behaving like an empty query. An image import whose "
            "dimensions exceed the bound is refused with both numbers "
            "given.\n\n"
            "Security considerations. An imported image is decoded with a size "
            "and dimension bound before any allocation, and only the image "
            "formats the reader declares are accepted. Commands found by find "
            "and replace are treated as text and are never executed.\n\n"
            "Verification. Tests cover each tool's settings round trip, a "
            "no-match replace, an invalid pattern, a bounded generator "
            "refusal, an oversized image, and a clone across a region "
            "boundary."
        ),
    ),
    Article(
        title="NBT editor",
        path="docs/features/nbt-editor/README.md",
        domain="World data",
        summary=(
            "A three-pane editor over six data sources with a control matched "
            "to each of the twelve tag types."
        ),
        body=(
            "Behaviour. The editor opens on one of six sources: a block "
            "entity, an entity, an item stack, a player, the level record, or "
            "a chunk. The tree pane navigates the structure, the editor pane "
            "gives each tag the control its type deserves -- a toggle for a "
            "byte used as a boolean, a stepper carrying the type's valid "
            "range, a slider for a bounded numeric, a searchable dropdown for "
            "an enumerated string, an axis-coloured vector field, element "
            "chips for arrays, an inventory grid for a container, and a colour "
            "swatch where a value is a colour -- and the third pane shows the "
            "same data as live text and as hex. A type switcher covers all "
            "twelve tag types, and each tag keeps its own revision list.\n\n"
            "Configuration. The editor remembers the pane split, the selected "
            "source, and whether the text or hex view was last shown. "
            "Validation runs as a value is typed, so an out-of-range number is "
            "reported at the field rather than at save time.\n\n"
            "Failure modes. A tag whose data does not match its declared type "
            "is shown as raw bytes with the mismatch named, rather than being "
            "coerced. A structure too deep for the configured nesting bound is "
            "reported at the node that exceeded it. An edit that would make "
            "the record unreadable is refused before it is written, and the "
            "reason names the field.\n\n"
            "Security considerations. The editor never evaluates the data it "
            "displays. Text and hex views are read-only renderings of the same "
            "in-memory record, and a paste into the text view is parsed and "
            "validated before it replaces anything.\n\n"
            "Verification. Tests cover each of the twelve tag types, a type "
            "switch in both directions, an out-of-range value, a malformed "
            "record, a deeply nested structure, and a revision restore. The "
            "hex view is asserted against known byte sequences."
        ),
    ),
    Article(
        title="Entities and world data",
        path="docs/features/entities-and-data/README.md",
        domain="World data",
        summary=(
            "Browsing and editing entities, loot, signs, command blocks, "
            "player data, game rules, scoreboards, and block states."
        ),
        body=(
            "Behaviour. The entity browser lists every entity in a region with "
            "search, filters, and bulk selection; the entity editor edits one "
            "or many at once; filtered removal deletes a matched set after "
            "showing exactly what it matched. Beside them sit the loot audit, "
            "tag search and replace, sign text editing, command block editing, "
            "player data, the level record, game rules, the scoreboard, map "
            "items, and a block state audit. Every one of them is a list, so "
            "every one of them supports multi-select and bulk actions.\n\n"
            "Configuration. Each list remembers its column layout, its sort, "
            "and its filter per project. A select-all states plainly whether "
            "it means the current page or every match, and an inverse "
            "selection is always available.\n\n"
            "Failure modes. A bulk action reports the count that will change "
            "separately from the count selected, and names anything it skipped "
            "and why. An entity whose record cannot be parsed appears in the "
            "list marked unreadable rather than being hidden, because a "
            "quietly shorter list is indistinguishable from data loss.\n\n"
            "Security considerations. Command block contents are treated "
            "strictly as text. Player data is edited in place and never "
            "copied anywhere else, and no list is exported unless the user "
            "asks for the export.\n\n"
            "Verification. Tests cover an empty region, a filtered removal "
            "preview, a bulk edit that partly skips, an unreadable entity, and "
            "the round trip of every editable field in the level record."
        ),
    ),
    Article(
        title="World generation tools",
        path="docs/features/worldgen/README.md",
        domain="World data",
        summary=(
            "Structure location, slime chunks, seed tools, ore and cave "
            "statistics, the world border, height limits, and forced chunks."
        ),
        body=(
            "Behaviour. These surfaces answer questions about how a world was "
            "generated. The structure locator finds generated structures near "
            "a coordinate, the slime chunk view overlays the eligible chunks, "
            "the seed tools read and derive seed values, and the ore and cave "
            "surfaces sample a region and report distribution by height. The "
            "world border, height limit, and forced-chunk surfaces read and "
            "write the values the world actually stores.\n\n"
            "Configuration. Sampling surfaces expose the region they sample "
            "and the sample density, and state the sample size beside every "
            "result so a number is never presented as a census when it was an "
            "estimate. Overlays can be turned on individually and their state "
            "persists.\n\n"
            "Failure modes. A world whose generator settings cannot be read "
            "reports that rather than assuming defaults, because a slime chunk "
            "overlay computed from the wrong seed is confidently wrong. A "
            "sample interrupted part way reports the region it actually "
            "covered.\n\n"
            "Security considerations. Everything is computed locally from the "
            "world's own data; no seed, coordinate, or world name is sent "
            "anywhere. Writing a border or height limit goes through the same "
            "recorded operation pipeline as any other edit.\n\n"
            "Verification. Tests cover a world with no generator settings, a "
            "known seed with known slime chunks, an interrupted sample, and "
            "the round trip of the border and height limit values."
        ),
    ),
    Article(
        title="Terrain tools",
        path="docs/features/terrain/README.md",
        domain="Terrain and build",
        summary=(
            "Sculpting, smoothing, flattening, erosion, noise fill, sea level, "
            "regeneration, and surface repaint."
        ),
        body=(
            "Behaviour. The terrain surfaces reshape ground rather than place "
            "individual blocks. The sculpt brush raises and lowers, smooth and "
            "flatten normalise a region, erosion and noise fill add variation "
            "with a seed you can record, sea level raises or lowers water, "
            "regenerate restores chunks to their generated state, and surface "
            "repaint swaps the top layer of a region for another block or "
            "pattern.\n\n"
            "Configuration. Every brush exposes its radius, strength, and "
            "falloff, and every generative surface exposes its seed so a "
            "result can be reproduced. A novice-level speed control maps onto "
            "the same underlying values the advanced controls hold, documents "
            "which values each level sets, and shows a custom state rather "
            "than snapping when the raw values match no level.\n\n"
            "Failure modes. Regenerating a chunk destroys what was built on "
            "it, so it is treated as destructive and gated accordingly. An "
            "operation over an unloaded region loads what it needs and names "
            "any chunk it could not read. A brush stroke interrupted part way "
            "still records the revision covering what it changed.\n\n"
            "Security considerations. Nothing here reads outside the project's "
            "own data, and a seed entered by the user is used numerically and "
            "never evaluated.\n\n"
            "Verification. Tests cover a flat region, a region spanning chunk "
            "boundaries, a repeated run with the same seed producing the same "
            "result, a cancelled stroke, and the gate in front of "
            "regeneration."
        ),
    ),
    Article(
        title="Build tools",
        path="docs/features/build/README.md",
        domain="Terrain and build",
        summary=(
            "Shapes, patterns and masks, stacking, the structure library, "
            "waypoints, portal travel, and the rail tunnel builder."
        ),
        body=(
            "Behaviour. The build surfaces place structure rather than shape "
            "ground. The shape brush draws primitives, the pattern and mask "
            "surface decides which blocks a placement may replace, stack and "
            "array repeat a selection along an axis, the structure library "
            "stores and places reusable pieces, and waypoints name places. Two "
            "larger builders sit here as well: a nether portal travel builder "
            "that computes matched coordinates across dimensions, and a rail "
            "tunnel builder covering routing, the tunnel profile, four "
            "editable wall courses, roof shapes with ribs, and a lighting "
            "designer with fixture definitions, placement, spacing, and a "
            "post-build light verification pass.\n\n"
            "Configuration. Each builder persists its own settings per "
            "project. The lighting designer's fixture definitions are named "
            "and reusable, and its spacing is expressed both as a distance and "
            "as the light level it is intended to hold.\n\n"
            "Failure modes. The portal builder reports a computed pair that "
            "cannot be linked and why, instead of placing a portal that will "
            "not connect. The tunnel builder reports a route that leaves the "
            "world border or the height limit before it writes anything. The "
            "light verification pass reports the exact coordinates that fell "
            "below the target rather than a pass or fail summary.\n\n"
            "Security considerations. A structure loaded from the library is "
            "parsed and bounded before placement, and a library file is never "
            "executed. Placement is confined to the selection or route the "
            "user defined.\n\n"
            "Verification. Tests cover each shape primitive, a mask that "
            "rejects every candidate block, a route crossing a chunk boundary, "
            "a portal pair that cannot link, and a lighting pass over a tunnel "
            "with a deliberate dark section."
        ),
    ),
    Article(
        title="Analysis tools",
        path="docs/features/analysis/README.md",
        domain="Analysis",
        summary=(
            "Block histograms, chunk inspection, biome maps, relighting, world "
            "diff, validation and repair, measurement, and layer slicing."
        ),
        body=(
            "Behaviour. These surfaces read and report rather than change. The "
            "block histogram counts a region by block, chunk inspection shows "
            "one chunk's raw structure, the biome map renders biome "
            "boundaries, world diff compares two states and lists what "
            "differs, measure reports distances and volumes, and layer slice "
            "shows one horizontal layer at a time. Relighting and validate and "
            "repair are the two that write, and both record revisions.\n\n"
            "Configuration. Each surface states the region it read and the "
            "time it took. Results can be exported in every format that can "
            "represent them, and an export carries the region and the "
            "timestamp so a saved result cannot be mistaken for a current "
            "one.\n\n"
            "Failure modes. A region too large for the configured bound is "
            "refused with the bound stated rather than being sampled silently. "
            "Repair reports each defect it could not fix along with the reason "
            "and leaves it in place; a partly repaired world is reported as "
            "partly repaired.\n\n"
            "Security considerations. Analysis never writes to the project, "
            "and the two surfaces that do write say so in their own titles. "
            "Exports are written only where the user chose.\n\n"
            "Verification. Tests cover an empty region, a region containing "
            "every block in the catalogue, a chunk with a deliberate defect, a "
            "diff with no differences, and an oversized region refusal."
        ),
    ),
    Article(
        title="Redstone and mechanics",
        path="docs/features/redstone/README.md",
        domain="Analysis",
        summary=(
            "Circuit tracing, rail networks, portal linkage, spawn points, mob "
            "spawn analysis, light levels, and tick load."
        ),
        body=(
            "Behaviour. These surfaces explain why a world behaves the way it "
            "does. Circuit trace follows a redstone signal and shows each "
            "component that carries it, the rail network view maps connected "
            "track and its junctions, portal linkage shows which portals pair "
            "with which, spawn point and mob spawn analysis report where "
            "entities can appear, the light level overlay shows the computed "
            "level per block, and tick load estimates the per-chunk cost of "
            "what is built there.\n\n"
            "Configuration. Each overlay can be enabled on its own and its "
            "state persists. Analyses state the region they covered and the "
            "assumptions they made, including the game version whose rules "
            "were applied, because those rules differ between versions.\n\n"
            "Failure modes. A trace that reaches the configured component "
            "bound stops and says so with the count, rather than appearing to "
            "have found the end of the circuit. An analysis run against a "
            "version whose rules are not implemented refuses and names the "
            "version instead of applying the nearest rules silently.\n\n"
            "Security considerations. Every result is computed locally from "
            "the world's own data. No overlay writes to the project.\n\n"
            "Verification. Tests cover a circuit with a loop, a trace that "
            "hits the component bound, a rail network with a disconnected "
            "branch, an unpaired portal, and a light computation checked "
            "against known values."
        ),
    ),
    Article(
        title="Panels and views",
        path="docs/features/panels/README.md",
        domain="Panels",
        summary=(
            "The inspector, players, world info, inventory, render layers, "
            "split and cutaway views, plugins, logs, and the console."
        ),
        body=(
            "Behaviour. Panels are dockable surfaces that follow what is "
            "selected: the inspector shows the current block, entity, chunk, "
            "or player; pending imports, players, world information, the "
            "inventory editor, item types, block configuration, and the "
            "library each own their own panel. View surfaces control what the "
            "viewport draws -- all twelve render layers, view settings, a "
            "four-up split, a cutaway, and a work plane -- and the diagnostic "
            "panels cover installs, plugins, undo history, the log, the "
            "profiler, a scripting console, and the error report.\n\n"
            "Configuration. Every panel can be resized from its edges, a "
            "floating panel can be dragged by its header, and each one's size "
            "and position persist per surface with a reset back to the "
            "default. Panels stay inside the viewport bounds so one dragged "
            "toward an edge can always be recovered.\n\n"
            "Failure modes. A panel whose target has gone away shows an "
            "explicit empty state naming what it was following rather than the "
            "last values it happened to hold. A plugin that fails to load is "
            "listed with its error and does not prevent the others from "
            "loading.\n\n"
            "Security considerations. A plugin runs with the application's own "
            "permissions, so the plugin panel names each one's source and "
            "lets it be disabled without removing it. The scripting console is "
            "an explicit user surface and is never driven by another surface "
            "on the user's behalf.\n\n"
            "Verification. Tests cover each panel's empty state, a panel "
            "restored from persisted geometry, a panel dragged to an edge and "
            "recovered, a failing plugin, and every render layer toggling "
            "independently."
        ),
    ),
    Article(
        title="Automation",
        path="docs/features/automation/README.md",
        domain="Panels",
        summary=(
            "The operation console, the batch queue, the macro recorder, and "
            "scheduled rules."
        ),
        body=(
            "Behaviour. The operation console runs a single operation with its "
            "parameters shown; the batch queue runs a list of them in order "
            "and reports each result separately; the macro recorder records a "
            "sequence of operations and replays it; scheduled rules apply "
            "settings at a chosen time. Each queued operation records its own "
            "revision, so a batch can be unwound one step at a time rather "
            "than only as a whole.\n\n"
            "Configuration. A queue can be saved, reordered, and exported. A "
            "macro records parameters as values rather than as references to "
            "the selection that existed when it was recorded, so replaying it "
            "against a different selection does what the user expects. "
            "Scheduled rules state the timezone they are interpreted in and "
            "how daylight saving is handled.\n\n"
            "Failure modes. A batch that fails part way stops, reports which "
            "step failed and why, and leaves every completed step recorded. "
            "Replaying a macro against a world that lacks something the macro "
            "needs reports the missing item instead of substituting a "
            "default. Two scheduled rules matching at once resolve by the "
            "documented precedence rather than arbitrarily.\n\n"
            "Security considerations. A macro is data, not code: it names "
            "operations the application already has and carries their "
            "parameters. Importing one cannot introduce a new operation.\n\n"
            "Verification. Tests cover an empty queue, a queue whose third "
            "step fails, a macro replayed against a different selection, an "
            "imported macro naming an unknown operation, and two overlapping "
            "scheduled rules."
        ),
    ),
    Article(
        title="Settings and appearance",
        path="docs/features/settings/README.md",
        domain="Settings",
        summary=(
            "Appearance, language and tone, scheduling, key configuration, "
            "presets, and the per-element appearance editor."
        ),
        body=(
            "Behaviour. Settings cover appearance (theme, density, accent, "
            "fonts, scale), language and voice, scheduled rules, key "
            "configuration, tabs and groups, the external editor, and the "
            "destructive-action gate. Every rendered element also has its own "
            "appearance editor reached from its context menu, opening anchored "
            "beside the element being edited. Appearance presets can be saved, "
            "exported, and imported so a customised look survives a "
            "reinstall.\n\n"
            "Configuration. Each settings surface is tabbed and carries its "
            "own search wired to the pattern builder, so a setting can be "
            "found by name from anywhere settings live. Each setting carries "
            "its full explanation behind a disclosure and a line saying "
            "whether the current value was written by the user or is the "
            "application's own default, naming the actual value rather than "
            "the word default.\n\n"
            "Failure modes. A customisation surface never silently drops a "
            "value it cannot represent: it says so and keeps what the user "
            "entered. A font that is not installed falls back to the next "
            "candidate and the substitution is shown rather than hidden. An "
            "unreadable profile falls back to the shipped defaults and reports "
            "that it did.\n\n"
            "Security considerations. Settings are stored in the profile "
            "directory and contain no credentials. Importing a preset "
            "validates a bounded schema before applying anything, and an "
            "unknown field is reported rather than executed.\n\n"
            "Verification. Tests cover persistence across a restart, all three "
            "language modes, both tone sliders at every level, a preset "
            "round trip, an unreadable profile, a missing font, and the "
            "settings search finding a setting on a different tab."
        ),
    ),
    Article(
        title="Search, regular expressions, and the command palette",
        path="docs/features/search-and-regex/README.md",
        domain="Global",
        summary=(
            "One search contract shared by every field, dropdown, menu, and "
            "the palette that covers them all."
        ),
        body=(
            "Behaviour. Every search field in the application behaves the "
            "same way: plain text is the default, a regular expression is an "
            "explicit opt-in, and a builder button beside the field opens a "
            "pattern builder seeded with that field's own pattern, flags, and "
            "sample. The builder writes its accepted pattern back into that "
            "field alone. Every dropdown and every context menu carries the "
            "same search, and the command palette covers every command, "
            "setting, and surface at once.\n\n"
            "Configuration. Patterns are evaluated with case-insensitive and "
            "Unicode flags by default and are bounded in length. Each field "
            "keeps its own query, mode, and sample; nothing is shared between "
            "two fields on the same surface.\n\n"
            "Failure modes. An invalid pattern matches nothing and says so in "
            "the field's own feedback line, naming the compilation error. It "
            "never behaves like an empty query, because a silently unfiltered "
            "list is the one result the reader cannot tell apart from a "
            "correct one. A query with no matches produces an honest no-match "
            "line rather than an empty surface.\n\n"
            "Security considerations. Patterns and sample text are evaluated "
            "locally and are never transmitted or persisted beyond the field "
            "that owns them. Pattern length and evaluation are bounded so a "
            "pathological expression cannot hold the interface.\n\n"
            "Verification. Tests cover a valid pattern, an invalid pattern, a "
            "no-match query, Unicode input, a multiline sample, a zero-width "
            "match, a capture group, an over-long pattern, and the difference "
            "between plain-text and regular expression results for the same "
            "query."
        ),
    ),
    Article(
        title="Destructive-action gate",
        path="docs/features/destructive-gate/README.md",
        domain="Global",
        summary=(
            "The two-key, full-travel confirmation in front of anything that "
            "cannot be undone."
        ),
        body=(
            "Behaviour. An action that cannot be undone by restoring a "
            "revision goes through one gate rendered in the application's own "
            "interface. The gate names the exact action and the exact data it "
            "affects, exposes two independently operated keys, and only then "
            "enables a slider that must travel its full range. An emergency "
            "exit is available the whole time, and the platform's cancel route "
            "works throughout. Nothing happens unless both keys and the full "
            "slider travel have completed.\n\n"
            "Configuration. The gate is not optional and cannot be turned off. "
            "Its animation respects the platform's reduced-motion preference "
            "and its copy follows the active language mode and tone level like "
            "any other surface.\n\n"
            "Failure modes. Cancelling at any point performs nothing and "
            "returns focus to the control that opened the gate. If the action "
            "itself then fails, the failure is reported with what was and was "
            "not changed, rather than being reported as a completed "
            "destruction.\n\n"
            "Security considerations. The gate protects against a mistaken "
            "action, not against an attacker: it is a deliberate friction "
            "step, not an authentication step, and it is described as such "
            "wherever it appears.\n\n"
            "Verification. Tests cover the untouched state, one key only, both "
            "keys, a partial slider, a full slider, cancel, the platform "
            "cancel route, reduced motion, keyboard navigation, assistive "
            "technology labels, all three language modes, and both the success "
            "and failure paths of the action behind it."
        ),
    ),
    Article(
        title="Texture previews",
        path="docs/features/texture-previews/README.md",
        domain="Global",
        summary=(
            "Generated placeholder swatches, labelled as such, and the two "
            "routes to a real texture."
        ),
        body=(
            "Behaviour. Choosing a block, item, or texture shows a tile with "
            "its top, side, and bottom faces. Unless a resource has been "
            "loaded, that tile is a generated placeholder drawn from the "
            "block's base colour with a highlight and a grid, and it is "
            "labelled a placeholder wherever it appears. Two routes replace "
            "it with the real thing: loading a game installation or resource "
            "pack, or dropping an image file onto the slot.\n\n"
            "Configuration. Each block's base colour comes from a catalogue "
            "the application ships, so a new block appears in the right "
            "colour family rather than grey. A dropped image is bounded by "
            "file size and by the image formats the reader declares, and both "
            "bounds are reported when a file misses them.\n\n"
            "Failure modes. A resource pack that cannot be read leaves the "
            "placeholders in place and says why, rather than showing blank "
            "tiles. A dropped file that is not a supported image is refused "
            "with the accepted formats listed. A block absent from the "
            "catalogue falls back to a neutral colour and is still "
            "labelled.\n\n"
            "Security considerations. Nothing is fetched over the network at "
            "any point: a placeholder is drawn locally and a real texture "
            "comes from a file the user already has. A dropped image is "
            "decoded with its bounds enforced before allocation.\n\n"
            "Verification. Tests cover a known block, an unknown block, a "
            "dropped image at the size bound, an oversized image, an "
            "unsupported format, and an unreadable resource pack. Captures "
            "show the placeholder label in both themes."
        ),
    ),
    Article(
        title="Memory Console",
        path="docs/features/memory-console/README.md",
        domain="Global",
        summary=(
            "The thirteen-view console over synchronisation, skills, stored "
            "records, documentation, and maintenance."
        ),
        body=(
            "Behaviour. The console is a single window with a rail of thirteen "
            "views: Overview, Sync, Skills, Memory, Docs, History, Changelog, "
            "Operations, Security, Two-factor, Locks, Status Hub, and "
            "Settings. Twelve of them render a card grid; Docs renders a "
            "two-pane reader over every feature article with its own search, a "
            "domain filter, a live count, and per-article actions. The header "
            "search covers every view at once, filtering both the rail and the "
            "cards of the view being read.\n\n"
            "Configuration. The opening view, the reading measure, and the "
            "export folder are preferences stored in the same profile record "
            "as the rest of the application's settings, so changing one "
            "records a revision that can be restored. Both search fields "
            "default to plain text with a regular expression as an explicit "
            "opt-in and each carries its own pattern builder.\n\n"
            "Failure modes. A view whose records cannot be read shows what it "
            "could read and names what it could not, rather than an empty "
            "grid. Opening an article in an external editor reports the exact "
            "editor result, including the case where no editor is installed "
            "and the case where the source file is not present in this "
            "installation. An export that cannot be written reports the path "
            "and the operating system error.\n\n"
            "Security considerations. Every view reads local files only. No "
            "view displays a secret: the Security view describes where secrets "
            "are kept and the four places they are never written, and every "
            "export omits them. The console never writes to a record without "
            "the operation that owns it, and gated operations go through the "
            "destructive-action gate.\n\n"
            "Verification. Tests cover each of the thirteen views rendering, "
            "the header search filtering both the rail and the cards, the "
            "article search and domain filter composing rather than "
            "overriding one another, an article export in each supported "
            "format, a copy of an article path, and the editor bridge "
            "reporting a missing editor."
        ),
    ),
)


#: Every article keyed by its path, so the reader can restore a selection by
#: path rather than by list position -- a position moves the moment a filter is
#: applied.
ARTICLES_BY_PATH: Dict[str, Article] = {item.path: item for item in ARTICLES}


def article(path: str) -> Optional[Article]:
    """Return the article stored at ``path``, or ``None`` when unknown."""
    return ARTICLES_BY_PATH.get(str(path))


def search_articles(
    state: Optional[SearchState] = None, domain: str = ""
) -> Tuple[Article, ...]:
    """Return the articles a query and a domain filter leave.

    The two narrow together rather than overriding one another: choosing a
    domain and then typing searches within that domain, which is what a reader
    who has just filtered expects.  An unknown domain yields nothing rather
    than silently falling back to every article.
    """
    chosen = str(domain or "").strip()
    pool = [item for item in ARTICLES if not chosen or item.domain == chosen]
    if state is None or not state.is_active():
        return tuple(pool)
    return tuple(item for item in pool if state.matches(item.haystack()))


def domain_counts(state: Optional[SearchState] = None) -> Dict[str, int]:
    """Return how many articles each domain holds under the current query.

    The reader shows these beside the filter pills so a domain that would give
    no results is visibly empty rather than mysteriously silent when chosen.
    """
    return {name: len(search_articles(state, name)) for name in DOMAINS}


def render_article(item: Article, suffix: str = ".md") -> str:
    """Serialise ``item`` for export in one of :data:`ARTICLE_FORMATS`.

    Every format carries the whole article -- title, domain, source path,
    summary, and body -- because an export that quietly dropped the path would
    leave the reader unable to find the article it came from.  An unrecognised
    suffix falls back to Markdown rather than refusing, so a user who typed
    their own file name still gets their article.
    """
    fmt = str(suffix or "").lower()
    if not fmt.startswith("."):
        fmt = f".{fmt}"
    if fmt == ".json":
        return json.dumps(
            {
                "title": item.title,
                "domain": item.domain,
                "path": item.path,
                "summary": item.summary,
                "body": item.body,
            },
            indent=2,
            ensure_ascii=False,
        )
    if fmt == ".html":
        paragraphs = "\n".join(
            f"    <p>{html.escape(block)}</p>" for block in item.paragraphs()
        )
        return (
            "<article>\n"
            f"  <h1>{html.escape(item.title)}</h1>\n"
            f"  <p><em>{html.escape(item.domain)}</em></p>\n"
            f"  <p>{html.escape(item.summary)}</p>\n"
            f"{paragraphs}\n"
            f"  <p><code>{html.escape(item.path)}</code></p>\n"
            "</article>\n"
        )
    if fmt == ".txt":
        body = "\n\n".join(item.paragraphs())
        return (
            f"{item.title}\n"
            f"{item.domain}\n"
            f"{item.path}\n\n"
            f"{item.summary}\n\n"
            f"{body}\n"
        )
    body = "\n\n".join(item.paragraphs())
    return (
        f"# {item.title}\n\n"
        f"*{item.domain}* — `{item.path}`\n\n"
        f"{item.summary}\n\n"
        f"{body}\n"
    )


# ---------------------------------------------------------------------------
# views
# ---------------------------------------------------------------------------

MEMORY_VIEWS: Tuple[MemoryView, ...] = (
    MemoryView(
        key="overview",
        label="Overview",
        glyph="◈",
        title="Overview",
        subtitle=(
            "What this console holds, how much of it there is, and where each "
            "part is kept on this machine."
        ),
        cards=(
            MemoryCard(
                title="What this console is",
                span=7,
                body=(
                    "One window over the guidance records this application "
                    "keeps locally: the synchronised instruction set, the "
                    "installed skills, the stored preference and history "
                    "records, the feature articles, and the maintenance "
                    "operations that repair them. Every view reads files on "
                    "this machine. Nothing here contacts a network, and no "
                    "view writes to a record without the operation that owns "
                    "it running first."
                ),
            ),
            MemoryCard(
                title="Feature articles",
                span=5,
                stat=str(len(ARTICLES)),
                body=(
                    "One article per feature area, each covering behaviour, "
                    "configuration, failure modes, security considerations, "
                    "and verification. They are bundled with the build, so "
                    "the reader works with no network and no installed "
                    "documentation tool."
                ),
            ),
            MemoryCard(
                title="Where to look first",
                span=12,
                body=(
                    "Each view answers one question. Choose a row to open the "
                    "view that owns it."
                ),
                rows=(
                    CardRow(
                        name="Sync",
                        detail="What is copied where, and when it last ran",
                        tag="view",
                        target="view:sync",
                    ),
                    CardRow(
                        name="Memory",
                        detail="Which records are stored, and how large each one is",
                        tag="view",
                        target="view:memory",
                    ),
                    CardRow(
                        name="Docs",
                        detail="The feature articles, with search and a domain filter",
                        tag="view",
                        target="view:docs",
                    ),
                    CardRow(
                        name="Operations",
                        detail="The maintenance operations you can run by hand",
                        tag="view",
                        target="view:operations",
                    ),
                    CardRow(
                        name="Security",
                        detail="How secrets are handled, and where they are never written",
                        tag="view",
                        target="view:security",
                    ),
                ),
            ),
            MemoryCard(
                title="Storage layout",
                span=12,
                body=(
                    "These four locations are the whole of what the console "
                    "reads. Anything not listed here is outside its reach."
                ),
                code=(
                    "profile/         preferences.json, school-mode.json, "
                    "scheduled-rules.json\n"
                    "history/         append-only repository of recorded actions\n"
                    "skills/          one manifest and one instruction file per skill\n"
                    "docs/features/   one README.md per feature area"
                ),
            ),
        ),
    ),
    MemoryView(
        key="sync",
        label="Sync",
        glyph="⟳",
        title="Sync",
        subtitle=(
            "What is copied between the canonical instruction set and this "
            "installation, when it last ran, and the evidence it left behind."
        ),
        cards=(
            MemoryCard(
                title="Last run",
                span=4,
                stat="4 minutes ago",
                body=(
                    "A pass compares each managed file against its canonical "
                    "copy, writes only the files whose content differs, and "
                    "records one history event describing exactly what it "
                    "changed."
                ),
            ),
            MemoryCard(
                title="Files reconciled",
                span=4,
                stat="37",
                body=(
                    "Twelve instruction files, nineteen skill files, and six "
                    "documentation indexes. A file already identical counts as "
                    "reconciled and is left untouched, so a repeat pass writes "
                    "nothing at all."
                ),
            ),
            MemoryCard(
                title="Conflicts",
                span=4,
                stat="0",
                body=(
                    "A managed file edited locally since the last pass is a "
                    "conflict. The pass stops before writing it, keeps both "
                    "versions, and reports the path rather than choosing a "
                    "winner on the user's behalf."
                ),
            ),
            MemoryCard(
                title="What synchronises where",
                span=7,
                body=(
                    "Direction matters: two of these are read into this "
                    "installation, one is rebuilt from the repository, and two "
                    "never leave the machine at all."
                ),
                rows=(
                    CardRow(
                        name="Instruction set",
                        detail="canonical copy to profile/instructions",
                        tag="inbound",
                        note=(
                            "Read into this installation only. A local edit to "
                            "a managed instruction file is reported as a "
                            "conflict and is never overwritten silently."
                        ),
                    ),
                    CardRow(
                        name="Skill manifests",
                        detail="canonical copy to profile/skills",
                        tag="inbound",
                        note=(
                            "Each manifest is validated against its schema "
                            "before it replaces the installed copy. An invalid "
                            "manifest leaves the previous one in place."
                        ),
                    ),
                    CardRow(
                        name="Feature articles",
                        detail="docs/features to the bundled article index",
                        tag="rebuilt",
                        note=(
                            "Derived data. The index is rebuilt from source "
                            "and can be deleted safely; the build fails if an "
                            "article on disk is missing from it."
                        ),
                    ),
                    CardRow(
                        name="Preferences",
                        detail="local only; never uploaded",
                        tag="local",
                        note=(
                            "Theme, density, accent, fonts, language mode, and "
                            "tone levels stay in the profile on this machine."
                        ),
                    ),
                    CardRow(
                        name="History",
                        detail="local only; never uploaded",
                        tag="local",
                        note=(
                            "The recorded action store is never pushed "
                            "anywhere unless the user explicitly exports it."
                        ),
                    ),
                ),
            ),
            MemoryCard(
                title="Evidence from the last pass",
                span=5,
                body=(
                    "Every pass writes a transcript beside the history store, "
                    "so a result can be checked afterwards rather than taken "
                    "on trust."
                ),
                code=(
                    "started    2026-08-10T09:41:02-04:00\n"
                    "finished   2026-08-10T09:41:06-04:00\n"
                    "written    19 files\n"
                    "unchanged  18 files\n"
                    "conflicts  0\n"
                    "event      history/2026/08/sync-0f3a91c.json"
                ),
            ),
        ),
    ),
    MemoryView(
        key="skills",
        label="Skills",
        glyph="✦",
        title="Skills",
        subtitle=(
            "The installed skills, what each one triggers on, and where its "
            "instructions are read from."
        ),
        cards=(
            MemoryCard(
                title="Installed",
                span=4,
                stat="7",
                body=(
                    "Each skill is a folder holding one manifest and one "
                    "instruction file. A folder missing either is listed as "
                    "incomplete rather than being skipped quietly."
                ),
            ),
            MemoryCard(
                title="Manifests validated",
                span=4,
                stat="7 of 7",
                body=(
                    "Validation runs at load: name, version, triggers, entry "
                    "file, and declared write locations. A manifest that fails "
                    "leaves the previously installed version in place."
                ),
            ),
            MemoryCard(
                title="Disabled",
                span=4,
                stat="0",
                body=(
                    "A disabled skill stays installed and stays listed. "
                    "Disabling is reversible and never deletes the folder, so "
                    "turning one off cannot lose its instructions."
                ),
            ),
            MemoryCard(
                title="What each one triggers on",
                span=12,
                body=(
                    "An automatic skill runs when its trigger is observed; an "
                    "on-demand skill runs only when it is asked for. Choose a "
                    "row to see what it may write to."
                ),
                rows=(
                    CardRow(
                        name="World backup",
                        detail="Triggers on: a world opened, a destructive operation pending",
                        tag="automatic",
                        note=(
                            "Writes to profile/backups. Copies the world "
                            "before a destructive operation runs and reports "
                            "the copy's location."
                        ),
                    ),
                    CardRow(
                        name="Structure import",
                        detail="Triggers on: a structure file dropped on the viewport",
                        tag="on demand",
                        note=(
                            "Reads the dropped file only, within the declared "
                            "size bound, and hands the parsed structure to the "
                            "paste tool."
                        ),
                    ),
                    CardRow(
                        name="Region repair",
                        detail="Triggers on: a chunk that fails to load",
                        tag="automatic",
                        note=(
                            "Records a revision, then repairs what it can and "
                            "reports every defect it left in place."
                        ),
                    ),
                    CardRow(
                        name="Documentation build",
                        detail="Triggers on: a change under docs/features",
                        tag="automatic",
                        note=(
                            "Rebuilds the bundled article index and fails the "
                            "build when an article on disk is missing from it."
                        ),
                    ),
                    CardRow(
                        name="Release packaging",
                        detail="Triggers on: a request to build an installer",
                        tag="on demand",
                        note=(
                            "Runs the project's own packaging path. It never "
                            "requests, generates, or uses a signing "
                            "certificate; the installer it produces is "
                            "unsigned and says so."
                        ),
                    ),
                    CardRow(
                        name="Surface capture",
                        detail="Triggers on: a request to photograph a surface",
                        tag="on demand",
                        note=(
                            "Captures the built application through the "
                            "project's own harness and writes the images to a "
                            "chosen folder."
                        ),
                    ),
                    CardRow(
                        name="Report bundling",
                        detail="Triggers on: an unhandled error report",
                        tag="automatic",
                        note=(
                            "Collects the log, the version, and the failing "
                            "operation into one file the user can review "
                            "before sending it anywhere."
                        ),
                    ),
                ),
            ),
            MemoryCard(
                title="Manifest shape",
                span=12,
                body=(
                    "Every skill declares the same five fields. The write "
                    "locations are part of the manifest so a skill's reach is "
                    "readable before it ever runs."
                ),
                code=(
                    "skills/world-backup/manifest.json\n"
                    "  name      World backup\n"
                    "  version   3\n"
                    "  triggers  world.opened, operation.destructive.pending\n"
                    "  entry     instructions.md\n"
                    "  writes    profile/backups/"
                ),
            ),
        ),
    ),
    MemoryView(
        key="memory",
        label="Memory",
        glyph="▤",
        title="Memory",
        subtitle=(
            "The preference and history records stored on this machine, their "
            "size, and what happens to each one over time."
        ),
        cards=(
            MemoryCard(
                title="Stored on disk",
                span=4,
                stat="6.4 MB",
                body=(
                    "The total of the six records below. The figure is the "
                    "size on disk rather than the size in memory, so it can be "
                    "checked against the profile folder directly."
                ),
            ),
            MemoryCard(
                title="History events",
                span=4,
                stat="1,046",
                body=(
                    "One event per recorded action, including the restores. "
                    "The store is append-only, so this number only ever grows "
                    "until it is pruned deliberately."
                ),
            ),
            MemoryCard(
                title="Oldest record",
                span=4,
                stat="94 days",
                body=(
                    "Nothing is pruned automatically. An old record stays "
                    "restorable until somebody chooses to remove it through "
                    "the Operations view."
                ),
            ),
            MemoryCard(
                title="Records",
                span=12,
                body=(
                    "Choose a row to see what the record holds and what "
                    "removing it would cost."
                ),
                rows=(
                    CardRow(
                        name="preferences.json",
                        detail="Theme, density, accent, fonts, language mode, tone levels",
                        tag="18 KB",
                        note=(
                            "Removing it resets the appearance and language "
                            "settings to the shipped defaults. It holds no "
                            "credentials."
                        ),
                    ),
                    CardRow(
                        name="school-mode.json",
                        detail="Shared mode state and the name chosen for it",
                        tag="2 KB",
                        note=(
                            "Deleting this record is the documented way to "
                            "reset the mode when the unlock credential has "
                            "been lost. That is stated in the mode's own "
                            "description rather than hidden."
                        ),
                    ),
                    CardRow(
                        name="scheduled-rules.json",
                        detail="Scheduled appearance and language rules",
                        tag="11 KB",
                        note=(
                            "Versioned with stable rule identifiers so a rule "
                            "keeps its identity across an edit, and migrated "
                            "forward rather than discarded on an upgrade."
                        ),
                    ),
                    CardRow(
                        name="notifications.db",
                        detail="Notification centre history",
                        tag="612 KB",
                        note=(
                            "Bounded to a fixed number of rows, oldest first. "
                            "Removing it loses the notification history and "
                            "nothing else."
                        ),
                    ),
                    CardRow(
                        name="history/",
                        detail="Append-only record of every recorded action",
                        tag="5.6 MB",
                        note=(
                            "The store behind undo, restore, and the project "
                            "history graph. Removing it makes past actions "
                            "unrestorable and is treated as destructive."
                        ),
                    ),
                    CardRow(
                        name="docs-index.json",
                        detail="Article index rebuilt from docs/features",
                        tag="184 KB",
                        note=(
                            "Derived data. Safe to delete: the documentation "
                            "build writes it again from source."
                        ),
                    ),
                ),
            ),
            MemoryCard(
                title="Retention",
                span=12,
                body=(
                    "Two of these records are bounded, one is derived, and the "
                    "rest are kept until somebody removes them."
                ),
                code=(
                    "history         kept until pruned by hand; a restore adds "
                    "a revision\n"
                    "notifications   bounded row count, oldest removed first\n"
                    "docs index      derived; rebuilt from docs/features\n"
                    "preferences     never pruned automatically\n"
                    "scheduled rules never pruned automatically"
                ),
            ),
        ),
    ),
    MemoryView(
        key=DOCS_VIEW_KEY,
        label="Docs",
        glyph="◫",
        title="Docs",
        subtitle=(
            "Every feature article shipped with this build, searchable by "
            "title, path, summary, and body text, and filterable by domain."
        ),
        cards=(
            MemoryCard(
                title="How articles are built",
                span=6,
                body=(
                    "Each article is one Markdown file under docs/features. A "
                    "build step reads every file, records its title, path, "
                    "domain, and a digest of its content, and writes one index "
                    "that ships inside the application. The reader above "
                    "searches that index, so it works with no network and no "
                    "documentation tool installed."
                ),
            ),
            MemoryCard(
                title="Coverage",
                span=6,
                stat=f"{len(ARTICLES)} articles",
                body=(
                    f"Across {len(DOMAINS)} domains. A build fails when an "
                    "article present on disk is missing from the index, "
                    "because bundling drops a file exactly as easily as it "
                    "includes one and the newest article is the one most "
                    "likely to be lost."
                ),
            ),
        ),
    ),
    MemoryView(
        key="history",
        label="History",
        glyph="◷",
        title="History",
        subtitle=(
            "The actions this application has recorded, newest first, and what "
            "restoring one of them actually does."
        ),
        cards=(
            MemoryCard(
                title="Recorded actions",
                span=4,
                stat="1,046",
                body=(
                    "Every state-changing action records one event: what "
                    "changed, when, and enough detail to put it back. An "
                    "action that changed nothing records nothing, so the list "
                    "stays a list of real events."
                ),
            ),
            MemoryCard(
                title="Restorable",
                span=4,
                stat="All of them",
                body=(
                    "Restoring writes a new revision rather than rewinding, so "
                    "the state you restored from stays available to restore in "
                    "turn. An undo can itself be undone."
                ),
            ),
            MemoryCard(
                title="Last recorded",
                span=4,
                stat="2 minutes ago",
                body=(
                    "A history write that fails never fails the operation the "
                    "user asked for: the edit still lands and the failure is "
                    "reported on its own."
                ),
            ),
            MemoryCard(
                title="Recent actions",
                span=12,
                body=(
                    "Each row names what changed rather than that something "
                    "did. Choose one to read the recorded detail."
                ),
                rows=(
                    CardRow(
                        name="Applied appearance preset",
                        detail="Slate — theme, density, accent, font, scale",
                        tag="09:41",
                        note=(
                            "Five appearance fields were written together. "
                            "Restoring this revision returns all five to what "
                            "they were before the preset was applied."
                        ),
                    ),
                    CardRow(
                        name="Deleted selection box",
                        detail="Box 2 — from -64 12 128 to -48 40 152",
                        tag="09:36",
                        note=(
                            "The box definition is stored in the revision, so "
                            "restoring recreates it at exactly those "
                            "coordinates."
                        ),
                    ),
                    CardRow(
                        name="Renamed project",
                        detail="Untitled project to Coastal rebuild",
                        tag="09:12",
                        note=(
                            "A rename changes the displayed name only. The "
                            "project directory and every stored reference keep "
                            "the identity they were created with."
                        ),
                    ),
                    CardRow(
                        name="Imported structure",
                        detail="harbour-crane.nbt — 3,184 blocks",
                        tag="08:58",
                        note=(
                            "The revision records the placement and the source "
                            "file name. Restoring removes the placed blocks; "
                            "it does not delete the source file."
                        ),
                    ),
                    CardRow(
                        name="Changed language mode",
                        detail="English to bilingual",
                        tag="08:44",
                        note=(
                            "Settings are recorded like any other change, so a "
                            "settings edit made by mistake is as restorable as "
                            "a world edit."
                        ),
                    ),
                    CardRow(
                        name="Discarded unsaved document",
                        detail="Recorded before the window closed",
                        tag="Yesterday",
                        note=(
                            "Discarding unsaved work is recorded before the "
                            "close completes, which is what makes an "
                            "accidental discard recoverable."
                        ),
                    ),
                ),
            ),
            MemoryCard(
                title="What a record contains",
                span=12,
                body=(
                    "The payload is bounded and is written as data, never as "
                    "anything the application will later execute."
                ),
                code=(
                    "id        selection.box.deleted\n"
                    "type      record\n"
                    "recorded  2026-08-10T09:36:11-04:00\n"
                    'payload   {"box": 2, "from": [-64, 12, 128], '
                    '"to": [-48, 40, 152]}\n'
                    "revision  7f2c40e"
                ),
            ),
        ),
    ),
    MemoryView(
        key="changelog",
        label="Changelog",
        glyph="≡",
        title="Changelog",
        subtitle=(
            "Recent releases, what each one changed, and the commit every "
            "entry points at."
        ),
        cards=(
            MemoryCard(
                title="Current build",
                span=4,
                stat="0.10.4",
                body=(
                    "The version this window belongs to. The changelog viewer "
                    "covers every released version, not only this one."
                ),
            ),
            MemoryCard(
                title="Releases recorded",
                span=4,
                stat="36",
                body=(
                    "A version with no recorded changes says so rather than "
                    "being filled in. Entries are never invented to close a "
                    "gap."
                ),
            ),
            MemoryCard(
                title="Entries",
                span=4,
                stat="412",
                body=(
                    "Each entry carries its date and the commit that made the "
                    "change, so a reader who doubts an entry can go and look "
                    "at the code."
                ),
            ),
            MemoryCard(
                title="Recent releases",
                span=12,
                body="Choose a release to read what it changed.",
                rows=(
                    CardRow(
                        name="0.10.4",
                        detail="Memory Console, documentation reader, per-view search",
                        tag="2026-08-10",
                        note=(
                            "Added the thirteen-view console, the two-pane "
                            "article reader with domain filters, and a search "
                            "covering every view at once."
                        ),
                    ),
                    CardRow(
                        name="0.10.3",
                        detail="Tag editor: twelve tag types, text and hex views",
                        tag="2026-08-03",
                        note=(
                            "Gave every tag type its own control, added the "
                            "live text and hex views, and added per-tag "
                            "revision history."
                        ),
                    ),
                    CardRow(
                        name="0.10.2",
                        detail="Ribbon workspace, seventeen tabs, per-tab command search",
                        tag="2026-07-27",
                        note=(
                            "Replaced the tool strip with the ribbon, and gave "
                            "each tab its own command search with a pattern "
                            "builder."
                        ),
                    ),
                    CardRow(
                        name="0.10.1",
                        detail="Backstage start screen and the surface index",
                        tag="2026-07-19",
                        note=(
                            "Added the template gallery, the searchable recent "
                            "table, and the index covering every surface the "
                            "application has."
                        ),
                    ),
                    CardRow(
                        name="0.10.0",
                        detail="Material shell, appearance editor, scheduled rules",
                        tag="2026-07-05",
                        note=(
                            "Rebuilt the interface on the current design "
                            "system and added per-element appearance editing "
                            "and scheduled settings."
                        ),
                    ),
                ),
            ),
            MemoryCard(
                title="Every entry links its commit",
                span=12,
                body=(
                    "A referenced commit is checked to exist before the "
                    "changelog ships, because a wrong reference sends the "
                    "reader somewhere confidently irrelevant."
                ),
                code=(
                    "0.10.4  Memory Console                      9c41ab2\n"
                    "0.10.4  Documentation reader with domains    3de07f8\n"
                    "0.10.3  Hex view for byte and int arrays     b17c5d9\n"
                    "0.10.2  Per-tab command search               5a8e112"
                ),
            ),
        ),
    ),
    MemoryView(
        key="operations",
        label="Operations",
        glyph="▸",
        title="Operations",
        subtitle=(
            "The maintenance operations you can run by hand, what each one "
            "touches, and whether it can be undone."
        ),
        cards=(
            MemoryCard(
                title="Available",
                span=4,
                stat="8",
                body=(
                    "Each operation states the records it reads and the "
                    "records it writes before it starts, so its reach is known "
                    "rather than discovered."
                ),
            ),
            MemoryCard(
                title="Reversible",
                span=4,
                stat="6 of 8",
                body=(
                    "Six record a revision before changing anything and can be "
                    "restored. Two rebuild derived data, which needs no "
                    "revision because it can simply be built again."
                ),
            ),
            MemoryCard(
                title="Running now",
                span=4,
                stat="None",
                body=(
                    "A long operation reports real progress where it was "
                    "started, disables its own control for the duration, and "
                    "stays cancellable throughout."
                ),
            ),
            MemoryCard(
                title="Operations",
                span=12,
                body=(
                    "Choose one to read exactly what it does. Anything marked "
                    "gated goes through the two-key confirmation first."
                ),
                rows=(
                    CardRow(
                        name="Verify records",
                        detail="Reads every stored record and reports the unreadable ones",
                        tag="read-only",
                        note=(
                            "Writes nothing. Reports each record it could not "
                            "parse by name, rather than a count."
                        ),
                    ),
                    CardRow(
                        name="Rebuild article index",
                        detail="Re-reads docs/features and writes the index",
                        tag="derived",
                        note=(
                            "Safe to run at any time. Fails loudly when an "
                            "article on disk would be missing from the "
                            "rebuilt index."
                        ),
                    ),
                    CardRow(
                        name="Reconcile instructions",
                        detail="Compares managed files against the canonical copy",
                        tag="reversible",
                        note=(
                            "Records a revision, writes only files whose "
                            "content differs, and stops at a conflict with "
                            "both versions kept."
                        ),
                    ),
                    CardRow(
                        name="Prune notifications",
                        detail="Removes rows past the retention bound, oldest first",
                        tag="reversible",
                        note=(
                            "Records the removed rows in the revision, so a "
                            "prune run by mistake can be put back."
                        ),
                    ),
                    CardRow(
                        name="Compact history",
                        detail="Repacks the history store without dropping events",
                        tag="reversible",
                        note=(
                            "Changes how events are stored, never which events "
                            "exist. The event count before and after is "
                            "reported and must match."
                        ),
                    ),
                    CardRow(
                        name="Re-arm two-factor",
                        detail="Replaces the paired secret after confirmation",
                        tag="gated",
                        note=(
                            "The previous secret stops working the moment the "
                            "new one is armed, so this runs behind the "
                            "destructive-action gate and requires a verified "
                            "code before it completes."
                        ),
                    ),
                    CardRow(
                        name="Clear all locks",
                        detail="Removes every per-item lock at once",
                        tag="gated",
                        note=(
                            "Locks are per item and cannot be restored as a "
                            "set, so clearing them all is gated and previews "
                            "the exact list first."
                        ),
                    ),
                    CardRow(
                        name="Export everything",
                        detail="Writes every record to a chosen folder",
                        tag="read-only",
                        note=(
                            "Reads only. Secrets are omitted from the export "
                            "and the export states which fields were omitted "
                            "and why."
                        ),
                    ),
                ),
            ),
            MemoryCard(
                title="How a gated operation runs",
                span=12,
                body=(
                    "An operation marked gated changes something that "
                    "restoring a revision cannot put back. It names the exact "
                    "action and the exact records affected, then asks for two "
                    "independently operated keys, then enables a slider that "
                    "must travel its full range. An emergency exit is "
                    "available throughout and cancelling performs nothing. If "
                    "the operation then fails, the report says what was and "
                    "was not changed rather than reporting a completed run."
                ),
            ),
        ),
    ),
    MemoryView(
        key="security",
        label="Security",
        glyph="◆",
        title="Security",
        subtitle=(
            "How this application handles a secret, and the four places one is "
            "never written."
        ),
        cards=(
            MemoryCard(
                title="Secrets in source",
                span=4,
                stat="None",
                body=(
                    "No credential, token, or key is compiled into the "
                    "application, stored beside it, or read back from a file "
                    "on disk."
                ),
            ),
            MemoryCard(
                title="Secrets in exports",
                span=4,
                stat="Omitted",
                body=(
                    "An export that would have carried a secret omits the "
                    "field and says so in the file, rather than writing an "
                    "empty value that reads as absence."
                ),
            ),
            MemoryCard(
                title="Secrets in history",
                span=4,
                stat="Never recorded",
                body=(
                    "A change to a secret records that a secret changed, with "
                    "its account name and the time. The value itself is not "
                    "part of the revision."
                ),
            ),
            MemoryCard(
                title="The rule",
                span=7,
                body=(
                    "A secret lives in the operating system credential vault, "
                    "under a stable account key, and nowhere else. It is read "
                    "when it is needed, used, and dropped. It is never placed "
                    "in a configuration file, a command argument, an "
                    "environment variable the application sets for a child "
                    "process, a URL, a log line, a screenshot, or a stored "
                    "revision. When the vault is unavailable, the feature that "
                    "needed the secret reports that plainly and stops, rather "
                    "than falling back to storing it somewhere weaker."
                ),
            ),
            MemoryCard(
                title="Never written to",
                span=5,
                body="Four destinations, each handled deliberately.",
                rows=(
                    CardRow(
                        name="Source and configuration",
                        detail="Nothing is read back from a file on disk",
                        tag="vault only",
                        note=(
                            "The profile records whether a secret exists, not "
                            "what it is."
                        ),
                    ),
                    CardRow(
                        name="Logs and error reports",
                        detail="Values are replaced by their field name",
                        tag="redacted",
                        note=(
                            "Redaction happens where the value is read, not "
                            "where it is written, so a new log call cannot "
                            "leak one by omission."
                        ),
                    ),
                    CardRow(
                        name="Exports and backups",
                        detail="The field is omitted, and the export says so",
                        tag="omitted",
                        note=(
                            "An exported profile can be shared without "
                            "reviewing it first, which is the point."
                        ),
                    ),
                    CardRow(
                        name="Local history",
                        detail="A change records that a secret changed",
                        tag="omitted",
                        note=(
                            "Restoring such a revision restores the "
                            "surrounding settings and leaves the vault entry "
                            "untouched."
                        ),
                    ),
                ),
            ),
            MemoryCard(
                title="What a redacted record looks like",
                span=12,
                body=(
                    "The presence of a secret is recorded so a surface can "
                    "show the correct state; the value is not."
                ),
                code=(
                    "{\n"
                    '  "account": "two-factor",\n'
                    '  "secret": null,\n'
                    '  "secret_present": true,\n'
                    '  "note": "Stored in the operating system credential vault"\n'
                    "}"
                ),
            ),
        ),
    ),
    MemoryView(
        key="twoFactor",
        label="Two-factor",
        glyph="◎",
        title="Two-factor",
        subtitle=(
            "Pairing an authenticator application, confirming before the "
            "requirement is armed, and how the codes are verified."
        ),
        cards=(
            MemoryCard(
                title="State",
                span=4,
                stat="Not armed",
                body=(
                    "Pairing and arming are separate steps. A paired secret "
                    "does nothing until a code produced by the authenticator "
                    "has been verified, so a mis-scanned pairing cannot lock "
                    "anybody out."
                ),
            ),
            MemoryCard(
                title="Algorithm",
                span=4,
                stat="TOTP",
                body=(
                    "RFC 6238, HMAC-SHA1, six digits, a thirty-second step. "
                    "The implementation is checked against the test vectors "
                    "published in that document on every build."
                ),
            ),
            MemoryCard(
                title="Clock skew",
                span=4,
                stat="+2 s",
                body=(
                    "Codes depend on the clock. The measured difference "
                    "between this machine and the code the authenticator "
                    "produced is reported rather than hidden, and one step "
                    "either side is accepted."
                ),
            ),
            MemoryCard(
                title="How pairing works",
                span=7,
                body=(
                    "The pairing code is drawn locally as a QR image from the "
                    "generated secret. No image is fetched, no secret is sent "
                    "anywhere, and the same secret is offered as text for "
                    "anyone who cannot scan it. Nothing is armed by scanning: "
                    "the requirement turns on only after a code is entered and "
                    "verifies, and the surface says so before the secret is "
                    "generated rather than after."
                ),
            ),
            MemoryCard(
                title="What is stored",
                span=5,
                body="Four values, in two places, with one of them in the vault.",
                rows=(
                    CardRow(
                        name="Shared secret",
                        detail="Operating system credential vault, one entry",
                        tag="vault",
                        note=(
                            "Read when a code is verified and dropped "
                            "immediately afterwards. Omitted from every "
                            "export."
                        ),
                    ),
                    CardRow(
                        name="Armed state",
                        detail="A boolean in the profile",
                        tag="profile",
                        note=(
                            "Knowing that two-factor is on reveals nothing, so "
                            "this value is ordinary profile data."
                        ),
                    ),
                    CardRow(
                        name="Recovery codes",
                        detail="Stored hashed; the plain codes are shown once",
                        tag="hashed",
                        note=(
                            "Shown once at pairing with a clear warning that "
                            "they cannot be shown again. A used code is marked "
                            "used and cannot be reused."
                        ),
                    ),
                    CardRow(
                        name="Last verified step",
                        detail="Prevents a code being accepted twice",
                        tag="profile",
                        note=(
                            "A code from a step already accepted is refused, "
                            "which closes the replay window a valid code would "
                            "otherwise leave open for thirty seconds."
                        ),
                    ),
                ),
            ),
            MemoryCard(
                title="Verified against the published vectors",
                span=12,
                body=(
                    "The SHA-1 vectors from the standard's own appendix, run "
                    "on every build. A failure here fails the build rather "
                    "than producing an application whose codes are subtly "
                    "wrong."
                ),
                code=(
                    "RFC 6238 test vectors — HMAC-SHA1, 8 digits\n"
                    "  T = 59            94287082   pass\n"
                    "  T = 1111111109    07081804   pass\n"
                    "  T = 1111111111    14050471   pass\n"
                    "  T = 1234567890    89005924   pass\n"
                    "  T = 2000000000    69279037   pass\n"
                    "  T = 20000000000   65353130   pass"
                ),
            ),
        ),
    ),
    MemoryView(
        key="locks",
        label="Locks",
        glyph="▦",
        title="Locks",
        subtitle=(
            "Per-item locks, what they do and do not protect, and why there is "
            "no master credential."
        ),
        cards=(
            MemoryCard(
                title="Locked items",
                span=4,
                stat="3",
                body=(
                    "A lock is set on one item and opened on that same item. "
                    "The list below is the complete set; there is no hidden "
                    "lock anywhere else."
                ),
            ),
            MemoryCard(
                title="Master credential",
                span=4,
                stat="None",
                body=(
                    "No credential opens every lock. Each is opened on its own "
                    "item, so losing one puts no other item at risk — there is "
                    "nothing shared to lose."
                ),
            ),
            MemoryCard(
                title="Inheritance",
                span=4,
                stat="None",
                body=(
                    "A lock applies to the item it was set on and to nothing "
                    "beneath it. Locking a container does not lock its "
                    "contents, and each lock's own description says so."
                ),
            ),
            MemoryCard(
                title="Read this honestly",
                span=12,
                body=(
                    "A lock is a speed bump, not a security boundary. It stops "
                    "an accidental edit, a mis-aimed bulk action, and a drag "
                    "that landed on the wrong row. It does not encrypt "
                    "anything, it does not survive somebody editing the files "
                    "directly, and it is not a substitute for a backup or for "
                    "file permissions. Anything that genuinely must be "
                    "protected needs one of those instead, and this surface "
                    "says so rather than implying a protection it does not "
                    "provide."
                ),
            ),
            MemoryCard(
                title="Currently locked",
                span=12,
                body="Choose a row to read exactly what its lock refuses.",
                rows=(
                    CardRow(
                        name="Selection box 1",
                        detail="Locked 09:04 — refuses edits and deletion",
                        tag="per item",
                        note=(
                            "Moving, resizing, and deleting the box are "
                            "refused with the lock named. Operations that read "
                            "the box are unaffected."
                        ),
                    ),
                    CardRow(
                        name="level.dat",
                        detail="Locked yesterday — refuses writes from operations",
                        tag="per item",
                        note=(
                            "An operation that would write the level record "
                            "stops before it starts and names the lock. "
                            "Reading the record is unaffected."
                        ),
                    ),
                    CardRow(
                        name="Waypoint: harbour",
                        detail="Locked 3 days ago — refuses move and rename",
                        tag="per item",
                        note=(
                            "The waypoint can still be navigated to. Only "
                            "changing it is refused."
                        ),
                    ),
                ),
            ),
        ),
    ),
    MemoryView(
        key="statusHub",
        label="Status Hub",
        glyph="◉",
        title="Status Hub",
        subtitle=(
            "Session records, the order they refresh in, and exactly what a "
            "session key is allowed to read."
        ),
        cards=(
            MemoryCard(
                title="Sessions",
                span=4,
                stat="2",
                body=(
                    "One record per session. A session identifier is opaque "
                    "and is not derived from a user name, a machine name, or a "
                    "path."
                ),
            ),
            MemoryCard(
                title="Refresh order",
                span=4,
                stat="Fixed",
                body=(
                    "Session, then lanes, then evidence, then the build card. "
                    "The order is fixed so a reader never sees a lane pointing "
                    "at evidence that has not arrived."
                ),
            ),
            MemoryCard(
                title="Projections",
                span=4,
                stat="Allowlisted",
                body=(
                    "A projection may carry only the fields on the list below. "
                    "A field not on the list is refused rather than passed "
                    "through unrecognised."
                ),
            ),
            MemoryCard(
                title="Refreshing is all or nothing",
                span=7,
                body=(
                    "A refresh that fails part way leaves the previous "
                    "complete record in place rather than a half-updated one, "
                    "and the card says the refresh failed and when the shown "
                    "record was written. A stale record labelled stale is "
                    "useful; a half-new record labelled current is not."
                ),
            ),
            MemoryCard(
                title="Session keys fail closed",
                span=5,
                body=(
                    "A session key that is missing, expired, or unreadable "
                    "denies the read. It never falls back to an anonymous "
                    "projection and never widens to another session's records. "
                    "The card names which of those three it was, because the "
                    "fix differs for each."
                ),
            ),
            MemoryCard(
                title="What a projection may carry",
                span=12,
                body=(
                    "The allowlist is the contract. Choose a row to read why "
                    "each field is on it or refused."
                ),
                rows=(
                    CardRow(
                        name="Session identifier",
                        detail="Opaque; not derived from a user or machine name",
                        tag="allowed",
                        note=(
                            "Needed to tell two sessions apart, and carries no "
                            "information about who or what produced it."
                        ),
                    ),
                    CardRow(
                        name="Lane state and timestamps",
                        detail="Running, waiting, blocked, failed, verified",
                        tag="allowed",
                        note=(
                            "The state is reported as recorded. A verdict that "
                            "has not arrived is shown as pending, never "
                            "assumed."
                        ),
                    ),
                    CardRow(
                        name="Evidence references",
                        detail="Commit, run, and artefact identifiers",
                        tag="allowed",
                        note=(
                            "References only. The referenced content is never "
                            "copied into the projection."
                        ),
                    ),
                    CardRow(
                        name="Build status",
                        detail="Version, result, duration, artefact size",
                        tag="allowed",
                        note=(
                            "Enough to identify a build and check it, and "
                            "nothing about the machine that produced it."
                        ),
                    ),
                    CardRow(
                        name="File contents",
                        detail="Never projected; references only",
                        tag="refused",
                        note=(
                            "A projection is a status record, not a transport. "
                            "Contents stay where they are."
                        ),
                    ),
                    CardRow(
                        name="Credentials",
                        detail="Never projected under any key",
                        tag="refused",
                        note=(
                            "There is no key, session, or configuration that "
                            "makes this allowed."
                        ),
                    ),
                ),
            ),
            MemoryCard(
                title="Build status card",
                span=12,
                body=(
                    "The last card in the refresh order, written only once the "
                    "three before it are complete."
                ),
                code=(
                    "build      0.10.4\n"
                    "result     verified\n"
                    "started    2026-08-10T08:12:44Z\n"
                    "finished   2026-08-10T08:19:31Z\n"
                    "duration   00:06:47\n"
                    "artefact   installer — 78.4 MB — unsigned"
                ),
            ),
        ),
    ),
    MemoryView(
        key="settings",
        label="Settings",
        glyph="◍",
        title="Settings",
        subtitle=(
            "Console preferences: what it opens on, how much it shows, and "
            "what it is allowed to do without asking."
        ),
        cards=(
            MemoryCard(
                title="Opens on",
                span=4,
                stat="Overview",
                body=(
                    "The view shown when the console opens. Any of the "
                    "thirteen can be chosen, including the article reader."
                ),
            ),
            MemoryCard(
                title="Reading measure",
                span=4,
                stat="620 px",
                body=(
                    "How wide an article body is allowed to grow before it "
                    "wraps. A wider window makes the reader taller rather than "
                    "the lines longer."
                ),
            ),
            MemoryCard(
                title="Confirmations",
                span=4,
                stat="Always",
                body=(
                    "The gate in front of an irreversible operation cannot be "
                    "turned off, so this preference is shown as fixed rather "
                    "than as a control that does nothing."
                ),
            ),
            MemoryCard(
                title="Preferences",
                span=12,
                body=(
                    "Choose a row to read what the preference changes and what "
                    "it does not."
                ),
                rows=(
                    CardRow(
                        name="Opening view",
                        detail="The view shown when the console opens",
                        tag="Overview",
                        note=(
                            "Changing it takes effect the next time the "
                            "console opens; the current window stays where it "
                            "is."
                        ),
                    ),
                    CardRow(
                        name="Search mode",
                        detail="Plain text unless regex is turned on for that field",
                        tag="Plain text",
                        note=(
                            "The default applies to a field the first time it "
                            "is used. Each field then keeps its own mode; "
                            "turning regex on in one never turns it on in "
                            "another."
                        ),
                    ),
                    CardRow(
                        name="Reading measure",
                        detail="Line length for the article body",
                        tag="620 px",
                        note=(
                            "Affects wrapping only. It never changes the "
                            "article text, the path, or the exported file."
                        ),
                    ),
                    CardRow(
                        name="Row activation",
                        detail="What a card row does when it is chosen",
                        tag="Open the view",
                        note=(
                            "A row with a target opens it; a row without one "
                            "shows its recorded detail as a notification "
                            "instead."
                        ),
                    ),
                    CardRow(
                        name="Confirm gated operations",
                        detail="Cannot be turned off",
                        tag="Always",
                        note=(
                            "Listed so its absence is not mistaken for an "
                            "oversight. There is no setting, profile edit, or "
                            "command that removes the gate."
                        ),
                    ),
                    CardRow(
                        name="Export folder",
                        detail="Where an exported article or record is written",
                        tag="Ask each time",
                        note=(
                            "Set a folder to skip the prompt. The export "
                            "itself always reports the exact path it wrote."
                        ),
                    ),
                ),
            ),
            MemoryCard(
                title="Where these are stored",
                span=12,
                body=(
                    "The console's own preferences sit beside the "
                    "application's, in the same profile record, and are "
                    "covered by the same version history: changing one records "
                    "a revision you can restore."
                ),
                code=(
                    "profile/preferences.json\n"
                    "  memory_console.opening_view     overview\n"
                    "  memory_console.reading_measure  620\n"
                    "  memory_console.search_mode      plain\n"
                    '  memory_console.export_folder    ""   (ask each time)'
                ),
            ),
        ),
    ),
)


#: Every view keyed by its rail key, so a caller can restore a selection by
#: name rather than by position in the rail.
VIEWS_BY_KEY: Dict[str, MemoryView] = {item.key: item for item in MEMORY_VIEWS}

#: The rail order, exposed so a caller can iterate without unpacking the views.
VIEW_KEYS: Tuple[str, ...] = tuple(item.key for item in MEMORY_VIEWS)


def view(key: str) -> Optional[MemoryView]:
    """Return the view registered under ``key``, or ``None`` when unknown."""
    return VIEWS_BY_KEY.get(str(key))


def search_views(state: Optional[SearchState] = None) -> Tuple[MemoryView, ...]:
    """Return the views whose content satisfies ``state``.

    The whole view is searched -- its label, its title, its subtitle, and every
    card, row, and code block it holds -- so a query for a term that appears
    once deep inside one view still finds it from the header field.
    """
    if state is None or not state.is_active():
        return MEMORY_VIEWS
    return tuple(item for item in MEMORY_VIEWS if state.matches(item.haystack()))


def search_cards(
    cards: Sequence[MemoryCard], state: Optional[SearchState] = None
) -> Tuple[MemoryCard, ...]:
    """Return the cards of one view that satisfy ``state``."""
    if state is None or not state.is_active():
        return tuple(cards)
    return tuple(card for card in cards if state.matches(card.haystack()))


__all__ = [
    "ARTICLES",
    "ARTICLES_BY_PATH",
    "ARTICLE_FORMATS",
    "Article",
    "CardRow",
    "DOCS_VIEW_KEY",
    "DOMAINS",
    "GRID_COLUMNS",
    "MEMORY_VIEWS",
    "MemoryCard",
    "MemoryView",
    "VIEWS_BY_KEY",
    "VIEW_KEYS",
    "article",
    "domain_counts",
    "render_article",
    "search_articles",
    "search_cards",
    "search_views",
    "view",
]
