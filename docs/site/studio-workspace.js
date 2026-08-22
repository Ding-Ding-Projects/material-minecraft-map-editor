/* Amulet Studio workspace shell -- the ribbon, the breadcrumb context bar,
 * the navigator, the tabbed properties pane and the status bar that sit
 * around the existing 3D viewport (viewport-panel.js / viewport-webgl.js /
 * viewport-overlays.js, which this file mounts rather than reimplements).
 *
 * Traced to design/Amulet Studio.dc.html and design/HANDOFF.md: seventeen
 * ribbon tabs (ribbonTabDefs in the design file), the same command groups,
 * the same breadcrumb/navigator/properties-pane/status-bar layout, and the
 * same Material 3 tokens (design/HANDOFF.md "Design system"), carried here
 * as the [data-studio-workspace] custom properties in studio-workspace.css.
 *
 * Two kinds of ribbon command exist, and every one of the roughly 140
 * buttons below is exactly one of them -- there is no silent third kind
 * that just does nothing when clicked:
 *
 *   1. Wired: backed by a real call, either into the sidecar's write path
 *      (world.fill / world.replace / world.undo / world.redo / world.save,
 *      via the already-working docs/site/viewport-panel.js and
 *      docs/site/electron-bridge.js) or a purely local UI action (switch
 *      ribbon tab, toggle the properties pane, toggle the ribbon, change
 *      theme/density). These render enabled once their precondition (a
 *      sidecar, an open+streaming world) is met.
 *   2. Not yet wired: every command the design specifies that this build
 *      has no real implementation for (brushes, structure import/export,
 *      NBT search, redstone tracing, and so on -- the bulk of the design's
 *      twelve editing surfaces). These render permanently disabled with an
 *      explicit reason in their title and in a visible reason line the
 *      properties pane can show, per this project's "every disabled
 *      control says why" rule.
 *
 * Degrades honestly outside Electron: without window.mmweDesktop.sidecar
 * every ribbon command (including the local-only ones, since a ribbon
 * whose Undo/Redo work but nothing else looks broken) shows the desktop-only
 * reason instead of silently doing nothing, and the navigator and viewport
 * host show the same explicit empty state viewport-panel.js already uses.
 */
(function () {
  "use strict";

  var UNWIRED_REASON = "Not yet wired to the desktop sidecar in this build.";
  var NO_SIDECAR_REASON = "Desktop only: this command needs the desktop app's sidecar.";
  var NO_WORLD_REASON = "Open a world in the viewport below first.";
  var THEME_KEY = "amulet-studio-workspace-theme";
  var DENSITY_KEY = "amulet-studio-workspace-density";
  var NAV_OPEN_KEY = "amulet-studio-workspace-nav-open";
  var GRID_VISIBLE_KEY = "amulet-studio-workspace-grid-visible";

  function bridge() {
    return window.mmweDesktop && window.mmweDesktop.sidecar;
  }

  function hasSidecar() {
    var b = bridge();
    return !!(b && typeof b.call === "function");
  }

  function sidecarCall(method, params) {
    var b = bridge();
    if (!b || typeof b.call !== "function") {
      return Promise.resolve({ ok: false, error: { code: "no_bridge" } });
    }
    return b.call(method, params || {});
  }

  function viewportPanel() {
    return window.__AmuletViewportPanel;
  }

  function worldStreaming() {
    var vp = viewportPanel();
    return !!(vp && typeof vp.isStreaming === "function" && vp.isStreaming());
  }

  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    attrs = attrs || {};
    Object.keys(attrs).forEach(function (key) {
      var value = attrs[key];
      if (value === null || value === undefined || value === false) return;
      if (key === "className") node.className = value;
      else if (key === "text") node.textContent = value;
      else if (key.indexOf("on") === 0 && typeof value === "function") {
        node.addEventListener(key.slice(2).toLowerCase(), value);
      } else if (key === "disabled") {
        node.disabled = !!value;
      } else {
        node.setAttribute(key, value);
      }
    });
    (children || []).forEach(function (child) {
      if (child === null || child === undefined) return;
      node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
    });
    return node;
  }

  function matchesQuery(query, regex, text) {
    var q = (query || "").trim();
    if (!q) return true;
    var haystack = String(text || "");
    if (!regex) return haystack.toLowerCase().indexOf(q.toLowerCase()) !== -1;
    try {
      return new RegExp(q, "iu").test(haystack);
    } catch (err) {
      return false;
    }
  }

  // ------------------------------------------------------------- ribbon
  // btn(label, glyph, hint, run, opts) mirrors the design file's own `btn`
  // helper. `run === null` means "the design specifies this command, and
  // this build has no implementation for it yet" -- rendered disabled with
  // UNWIRED_REASON, never silently inert.
  function btn(label, glyph, hint, run, opts) {
    opts = opts || {};
    return {
      label: label,
      glyph: glyph,
      hint: hint || label,
      run: run || null,
      primary: !!opts.primary,
      requiresSidecar: !!opts.requiresSidecar,
      requiresWorld: !!opts.requiresWorld,
    };
  }

  function group(title, items, extra) {
    return Object.assign({ title: title, items: items || [], fields: null, select: null }, extra || {});
  }

  function buildRibbonByTab(actions) {
    return {
      home: [
        group("Clipboard", [
          btn("Paste", "⎘", "Paste a previously copied or cut area into the world.", actions.pasteSelection, { requiresSidecar: true, requiresWorld: true }),
          btn("Copy", "⧉", "Copy the selected area to paste later.", actions.copySelection, { requiresSidecar: true, requiresWorld: true }),
          btn("Cut", "✂", "Copy the selected area to paste later and delete.", actions.cutSelection, { requiresSidecar: true, requiresWorld: true }),
          btn("Delete", "⌫", "Delete the blocks in the selected area.", actions.deleteSelection, { requiresSidecar: true, requiresWorld: true }),
          btn("Clone", "⁙", "Clone the selection with repeatable copies."),
          btn("Move", "⤥", "Lift the selection into a pending import."),
        ]),
        group("Editing", [
          btn("Undo", "↶", "Undo the last edit against the open world.", actions.undo, { primary: true, requiresSidecar: true, requiresWorld: true }),
          btn("Redo", "↷", "Redo the last undone edit.", actions.redo, { requiresSidecar: true, requiresWorld: true }),
          btn("Save", "▣", "Write pending changes to disk.", actions.save, { requiresSidecar: true, requiresWorld: true }),
          btn("History", "⟲", "Project history -- per-project Git repository."),
          btn("Goto", "⌖", "Teleport the camera to a coordinate."),
          btn("Select all", "▩", "Select All."),
          btn("Inspect", "⌕", "Inspect block -- opens the NBT editor."),
        ]),
        group("Panes", [
          btn("Properties", "▤", "Show the properties pane.", actions.showPane),
          btn("Commands", "⌘", "Tell me what to do."),
        ]),
      ],
      selection: [
        group("Points", [
          btn("Move point 1", "◉", "Press and hold, then use the movement controls to move the green point."),
          btn("Move point 2", "◎", "Press and hold, then use the movement controls to move the blue point."),
          btn("Move box", "⬚", "Press and hold, then use the movement controls to move the active box."),
        ]),
        group("Coordinates", [], { fields: actions.selectionFields }),
        group("Boxes", [
          btn("Add box", "＋", "Add another selection box."),
          btn("Remove", "－", "Remove the active selection box."),
          btn("Select all", "▩", "Select All."),
        ]),
      ],
      operations: [
        group("Stock operations", [
          btn("Clone", "⧉", "Copy the selection to another location."),
          btn("Fill", "▧", "Fill the selected block range with the fill-block field in the viewport below.", actions.fill, { primary: true, requiresSidecar: true, requiresWorld: true }),
          btn("Replace", "⇄", "Swap one block for another in the selection, using the find/replace fields in the viewport below.", actions.replace, { requiresSidecar: true, requiresWorld: true }),
          btn("Set biome", "❋", "Apply a biome across the selection."),
          btn("Waterlog", "≈", "Waterlog eligible blocks in the selection."),
        ]),
        group("Plugins", [
          btn("Reload", "↻", "Reload project-specific Python operations."),
          btn("Open folder", "▸", "Open the operations folder."),
        ]),
        group("Run", [
          btn("Run", "▶", "Run the selected operation.", null, { primary: true }),
        ]),
      ],
      structures: [
        group("Import", [
          btn("Import file", "⭳", "Import a .construction/.mcstructure/.schematic/.schem file and paste it at point 1.", actions.importStructure, { primary: true, requiresSidecar: true, requiresWorld: true }),
          btn("Import chunks", "▦", "Replace the selected chunks with chunks from another world."),
        ]),
        group("Export", [
          btn("Export", "⭱", "Export the selection to a .construction file.", actions.exportStructure, { requiresSidecar: true, requiresWorld: true }),
          btn("Open in editor", "▸", "Open the exported folder in Visual Studio Code."),
        ]),
      ],
      chunks: [
        group("Draw range", [], { fields: [{ label: "Min Y", value: "—" }, { label: "Max Y", value: "—" }] }),
        group("Chunks", [
          btn("Create empty", "▢", "Create all chunks in the selection that do not already exist.", actions.createChunks, { primary: true, requiresSidecar: true, requiresWorld: true }),
          btn("Import", "▦", "Replace the selected chunks with chunks from another world."),
          btn("Delete", "⌫", "Delete the selected chunks.", actions.deleteChunks, { requiresSidecar: true, requiresWorld: true }),
          btn("Delete unselected", "⌮", "Delete all chunks that are not selected.", actions.pruneChunks, { requiresSidecar: true, requiresWorld: true }),
        ]),
      ],
      terrain: [
        group("Sculpt", [
          btn("Raise", "▲", "Raise the heightmap under the brush.", null, { primary: true }),
          btn("Lower", "▼", "Lower the heightmap under the brush."),
          btn("Smooth", "≈", "Average neighbouring heights."),
          btn("Flatten", "▬", "Flatten the selection to its own top Y with the fill-block field's block.", actions.terrainFlatten, { requiresSidecar: true, requiresWorld: true }),
          btn("Erode", "◠", "Hydraulic and thermal erosion passes."),
        ]),
        group("Generate", [
          btn("Noise", "⁘", "Fill the selection from a seeded noise field.", null, { primary: true }),
          btn("Sea level", "≡", "Raise or drain the water table to the selection's midpoint Y, per the Sea level mode field in the viewport's edit panel below.", actions.terrainSeaLevel, { requiresSidecar: true, requiresWorld: true }),
          btn("Regenerate", "↻", "Regenerate chunks from the world seed."),
        ]),
        group("Surface", [
          btn("Repaint", "▨", "Repaint the topmost block of every column in the selection with the fill-block field's block.", actions.terrainRepaint, { primary: true, requiresSidecar: true, requiresWorld: true }),
          btn("Snow line", "❄", "Apply snow and ice above a height."),
          btn("Grass fix", "❋", "Restore grass, dirt, and stone banding."),
        ]),
      ],
      build: [
        group("Shapes", [
          btn("Sphere", "◉", "Draw a filled or hollow sphere.", null, { primary: true }),
          btn("Cylinder", "◍", "Draw a cylinder along an axis."),
          btn("Cuboid", "▢", "Fill the selection as a box, using the fill-block field's block.", actions.buildCuboid, { requiresSidecar: true, requiresWorld: true }),
          btn("Line", "／", "Draw a line between the two points."),
          btn("Path", "〜", "Draw a path through waypoints."),
        ]),
        group("Pattern", [
          btn("Pattern", "▦", "Weighted multi-block pattern.", null, { primary: true }),
          btn("Mask", "◫", "Restrict edits to matching blocks."),
          btn("Gradient", "▩", "Blend two blocks across the selection."),
        ]),
        group("Transform", [
          btn("Stack", "⧈", "Repeat the selection along an axis.", null, { primary: true }),
          btn("Array", "⁙", "Grid or radial array of the selection."),
          btn("Rotate", "↻", "Rotate in 90-degree or free steps."),
          btn("Flip", "⇋", "Mirror along a camera-relative axis."),
        ]),
        group("Library", [
          btn("Structures", "❖", "Staged structure library with tags.", null, { primary: true }),
          btn("Waypoints", "⌖", "Named camera and build waypoints."),
        ]),
      ],
      entities: [
        group("Browse", [
          btn("Entities", "☰", "Every entity in the selection.", actions.entitiesList, { primary: true, requiresSidecar: true, requiresWorld: true }),
          btn("Block entities", "▤", "Chests, signs, spawners, and other NBT blocks."),
          btn("Players", "☺", "Player data, inventory, and position."),
        ]),
        group("Edit", [
          btn("Edit entity", "✎", "Edit the selected entity's NBT.", null, { primary: true }),
          btn("Place", "＋", "Place the entity type from the viewport's edit panel at selection point 1.", actions.entitiesPlace, { requiresSidecar: true, requiresWorld: true }),
          btn("Remove", "⌫", "Remove entities in the selection matching the viewport edit panel's entity type field.", actions.entitiesRemove, { requiresSidecar: true, requiresWorld: true }),
        ]),
        group("Spawners", [
          btn("Spawner", "◈", "Edit spawner type, delay, and range."),
          btn("Loot", "▧", "Audit container loot tables."),
        ]),
      ],
      data: [
        group("Search", [
          btn("NBT search", "⌕", "Search and replace across raw tags.", null, { primary: true }),
          btn("Signs", "▭", "Find and edit sign text."),
          btn("Commands", "⌘", "Find command blocks and their commands."),
        ]),
        group("World data", [
          btn("level.dat", "▣", "Read the world's real level.dat fields.", actions.dataLevelRead, { primary: true, requiresSidecar: true, requiresWorld: true }),
          btn("Write level.dat", "✎", "Write the level.dat fields set in the viewport's edit panel below (leave a field blank to keep it unchanged). Edits the world's own metadata -- confirm gate applies.", actions.dataLevelWrite, { requiresSidecar: true, requiresWorld: true }),
          btn("Game rules", "⚖", "Every game rule with its current value.", actions.dataGameRulesRead, { requiresSidecar: true, requiresWorld: true }),
          btn("Write game rule", "⚖", "Set the game rule name/value entered in the viewport's edit panel below. Edits the world's own metadata -- confirm gate applies.", actions.dataGameRulesWrite, { requiresSidecar: true, requiresWorld: true }),
          btn("Scoreboard", "▧", "Objectives, teams, and scores."),
          btn("Maps", "◫", "Map items and their stored images."),
        ]),
        group("Blocks", [
          btn("Block audit", "▨", "Unknown or deprecated block states."),
          btn("Palette", "▩", "Per-chunk block palette usage."),
        ]),
      ],
      analyze: [
        group("Counts", [
          btn("Histogram", "▧", "Block counts and percentages in the selection.", actions.analyzeBlockHistogram, { primary: true, requiresSidecar: true, requiresWorld: true }),
          btn("Chunk inspector", "▦", "Per-chunk status, entity, and block-entity counts in the selection.", actions.analyzeChunkInventory, { requiresSidecar: true, requiresWorld: true }),
          btn("Biome map", "❋", "Biome distribution across the selection."),
        ]),
        group("Integrity", [
          btn("Validate", "✓", "Audit the selection for blocks outside the universal_minecraft namespace (a translation-failure signal); does not repair region data.", actions.analyzeBlockAudit, { primary: true, requiresSidecar: true, requiresWorld: true }),
          btn("Relight", "☀", "Recompute block and sky light."),
          btn("Compare", "⇄", "Diff two worlds chunk by chunk."),
        ]),
        group("Measure", [
          btn("Measure", "⟺", "Distance, volume, and area readouts."),
          btn("Slice", "▬", "Isolate a Y slice in the viewport."),
        ]),
      ],
      redstone: [
        group("Circuits", [
          btn("Trace", "☁", "Trace a redstone circuit and list its components.", null, { primary: true }),
          btn("Signal", "◈", "Inspect signal strength and power sources."),
          btn("Rewire", "⇉", "Rotate or mirror a circuit without breaking wiring."),
        ]),
        group("Travel builders", [
          btn("Portal pair", "◫", "Nether portal travel builder -- matched pair at the 8:1 position.", null, { primary: true }),
          btn("Rail tunnel", "≣", "Rail tunnel builder -- custom walls, roofs, and lighting.", null, { primary: true }),
          btn("Linkage", "⇄", "Portal linkage report and ratio calculator."),
          btn("Rail audit", "☁", "Audit rail networks, powered rails, and junctions."),
          btn("Beds", "▤", "Spawn points, beds, and respawn anchors."),
        ]),
        group("Mechanics", [
          btn("Spawn rules", "◉", "Mob spawning conditions per column."),
          btn("Light levels", "☀", "Light level overlay for spawn-proofing."),
          btn("Tick load", "⏱", "Random-tick and block-entity load per chunk."),
        ]),
      ],
      worldgen: [
        group("Structures", [
          btn("Locate", "⌖", "Find generated structures by type.", null, { primary: true }),
          btn("Strongholds", "◇", "Stronghold ring positions from the seed."),
          btn("Slime chunks", "◍", "Slime chunk grid for the world seed."),
        ]),
        group("Seed", [
          btn("Seed tools", "⁘", "Read, change, and reseed generation.", null, { primary: true }),
          btn("Ore audit", "▨", "Ore distribution per Y layer."),
          btn("Cave map", "◠", "Cave and ravine coverage per slice."),
        ]),
        group("Boundaries", [
          btn("Border", "▢", "World border centre, size, and warning band.", null, { primary: true }),
          btn("Height limits", "▬", "Build range per platform and dimension."),
          btn("Force loaded", "⛁", "Force-loaded and ticket-held chunks."),
        ]),
      ],
      view: [
        group("Appearance", [
          btn("Theme", "◐", "Switch light and dark.", actions.toggleTheme, { primary: true }),
          btn(
            "Options",
            "⚙",
            window.AmuletStudioAppearance
              ? "Open the per-element appearance editor."
              : "Open the per-element appearance editor.",
            window.AmuletStudioAppearance ? actions.openOptions : null
          ),
        ], { select: actions.densitySelect }),
        group("Show", [
          btn("Properties", "▤", "Toggle the properties pane.", actions.togglePane),
          btn("Ribbon", "▬", "Collapse or expand the ribbon.", actions.toggleRibbon),
          btn("Navigator", "◫", "Toggle the navigator sidebar.", actions.toggleNavigator),
        ]),
        group("Views", [
          btn("View", "◱", "View type, camera, and overlays. This build's renderer only draws a single perspective camera -- no orthographic or multi-view mode yet.", null, { primary: true }),
          btn("Four-up", "⊞", "Camera, overhead, and two elevations at once. This build renders one viewport, not four."),
          btn("Cutaway", "◧", "Clip the world along a plane. No clip-plane support in this build's renderer."),
          btn("Work plane", "▬", "The fixed plane brushes snap to. No brush system exists to snap yet."),
        ]),
        group("Layers", [
          btn(
            "Layers",
            "☰",
            "Draw or hide the reference grid overlay.",
            actions.toggleGrid,
            { primary: true, requiresSidecar: true, requiresWorld: true }
          ),
          btn("Installs", "⛁", "Resource packs and texture atlas. This build has no resource-pack manager to list."),
        ]),
      ],
      panels: [
        group("Inspect", [
          // "Inspector -- dockable inspector that follows the selection" is
          // exactly the properties pane this build already has (point1/
          // point2, world/dimension, streaming state, and every command's
          // own analyze/workshop result). No separate inspector surface
          // exists to build, so this opens and focuses the real one.
          btn("Inspector", "⌕", "Dockable inspector that follows the selection -- opens the properties pane.", actions.openInspector, { primary: true }),
          btn("World info", "▣", "World identity, size on disk, time and weather. No such panel exists in this build yet."),
          btn("Players", "☺", "Players, skins, positions, and inventories. No player-data panel exists in this build yet."),
          btn("Inventory", "▦", "Slot-by-slot inventory editor. No inventory editor exists in this build yet."),
        ]),
        group("Objects", [
          btn("Pending", "⧉", "Pending imports awaiting confirmation. No pending-import queue exists in this build yet.", null, { primary: true }),
          btn("Library", "❑", "Schematic library with folders and previews. No schematic library exists in this build yet."),
          btn("Maps", "◫", "Map items and image import. No map-item panel exists in this build yet."),
        ]),
        group("Diagnostics", [
          btn("Log", "▤", "Filterable application log. No application-log panel exists in this build yet."),
          btn("Profiler", "⏱", "Frame time and chunk-loading samples. No profiler exists in this build yet."),
          btn("Console", "⌨", "Embedded Python console. No Python console exists in this build yet."),
          btn("Errors", "⚠", "Local error report with traceback. No error report panel exists in this build yet."),
        ]),
      ],
      extend: [
        group("Pickers", [
          btn("Blocks", "▨", "Block picker with states and textures. No block picker exists in this build yet.", null, { primary: true }),
          btn("Items", "◈", "Item type list with textures. No item picker exists in this build yet."),
          btn("Biomes", "❋", "Biome picker. No biome picker exists in this build yet."),
          btn("Define", "✎", "Configure block and item definitions. No definitions editor exists in this build yet."),
        ]),
        group("Resources", [
          btn("Installs", "⛁", "Minecraft installs, versions, and resource packs. No installs manager exists in this build yet.", null, { primary: true }),
          btn("Versions", "◇", "Platform and data version for handlers. No version manager exists in this build yet."),
        ]),
        group("Plugins", [
          btn("Plugins", "✦", "Installed tools, generators, and commands. No plugin host exists in this build yet.", null, { primary: true }),
          btn("Generate", "⁘", "Generator plugins including L-system. No generator plugin host exists in this build yet."),
          btn("Console", "⌨", "Operation console for Python extensions. No Python console exists in this build yet."),
        ]),
      ],
      automate: [
        group("Scripting", [
          btn("Console", "⌨", "Operation console for Python extensions. No Python console exists in this build yet.", null, { primary: true }),
          btn("Batch queue", "⛁", "Queue several operations across worlds. No batch queue exists in this build yet."),
          btn("Macro", "⏺", "Record and replay operation sequences. No macro recorder exists in this build yet."),
        ]),
        group("Scheduling", [
          btn("Rules", "⏷", "Scheduled language, theme, density, and accent rules. No scheduled-settings surface exists in this build yet.", null, { primary: true }),
        ]),
        group("Records", [
          // The notification drawer (#notif-open, wired by studio-shell.js)
          // is real and already on the same page this ribbon mounts into --
          // this just presses that real button rather than building a
          // second notification surface.
          btn("Notifications", "◉", "Notification history -- opens the notification drawer.", actions.openNotifications),
          btn("History", "⟲", "Version history. The Surfaces view that hosts local history is not switched into by this build's view router yet."),
          btn("Release notes", "♧", "Release notes. This build has no in-app changelog viewer yet -- see the documentation site's own changelog."),
        ]),
        group("Memory", [
          btn("Memory console", "▤", "Agent Global Memory Console. Not applicable inside the desktop app -- this is an operator tool for this project's own agents.", null, { primary: true }),
          btn("Regex builder", ".*", "Open the bounded regex builder. Use this tab's own search field's regex builder for now -- a standalone builder command does not exist yet."),
        ]),
      ],
    };
  }

  var RIBBON_TAB_DEFS = [
    { key: "home", label: "Home" },
    { key: "selection", label: "Selection" },
    { key: "operations", label: "Operations" },
    { key: "structures", label: "Structures" },
    { key: "chunks", label: "Chunks" },
    { key: "terrain", label: "Terrain" },
    { key: "build", label: "Build" },
    { key: "entities", label: "Entities" },
    { key: "data", label: "Data" },
    { key: "analyze", label: "Analyze" },
    { key: "redstone", label: "Redstone" },
    { key: "worldgen", label: "Worldgen" },
    { key: "view", label: "View" },
    { key: "panels", label: "Panels" },
    { key: "extend", label: "Extend" },
    { key: "automate", label: "Automate" },
  ];

  var NAVIGATOR_DEFS = [
    { key: "overworld", label: "Overworld", glyph: "◍" },
    { key: "the_nether", label: "The Nether", glyph: "◔" },
    { key: "the_end", label: "The End", glyph: "◌" },
    { key: "nether", label: "The Nether", glyph: "◔" },
    { key: "end", label: "The End", glyph: "◌" },
  ];

  function navigatorLabel(dimensionName) {
    var def = NAVIGATOR_DEFS.filter(function (d) { return d.key === dimensionName; })[0];
    if (def) return def;
    return { key: dimensionName, label: dimensionName, glyph: "◌" };
  }

  // ============================================================== mount
  function mount(root) {
    var state = {
      ribbonTab: "home",
      ribbonOpen: true,
      ribbonSearch: "",
      ribbonRegex: false,
      paneOpen: true,
      paneTab: "properties",
      navOpen: (function () {
        try {
          return window.localStorage.getItem(NAV_OPEN_KEY) !== "0";
        } catch (err) {
          return true;
        }
      })(),
      // Grid state lives in localStorage too, exactly like theme/density
      // above, so it survives a restart the same way -- but the value that
      // actually decides what draws is viewport-panel.js's own
      // gridVisible closure var (mirrored here on toggle and read back on
      // world-open, since the overlay does not exist until a world does).
      gridVisible: (function () {
        try {
          return window.localStorage.getItem(GRID_VISIBLE_KEY) !== "0";
        } catch (err) {
          return true;
        }
      })(),
      navSearch: "",
      navSelected: null,
      theme: (function () {
        try {
          return window.localStorage.getItem(THEME_KEY) || "light";
        } catch (err) {
          return "light";
        }
      })(),
      density: (function () {
        try {
          return window.localStorage.getItem(DENSITY_KEY) || "comfortable";
        } catch (err) {
          return "comfortable";
        }
      })(),
      dimensions: [], // populated from the sidecar's world.dimensions
      worldOpenError: null,
      wiredCommandCount: 0,
      unwiredCommandCount: 0,
      // The Analyze ribbon tab's own world handle, kept here (rather than
      // read from viewport-panel.js's private closure state, which does not
      // expose it) because analyze.* calls need a world_id the same way
      // fill/replace do. Set once loadDimensionsForPath's open+poll finishes.
      worldId: null,
      analyzeRunning: false,
      analyzeError: null,
      analyzeResult: null, // { command, summary, rows: [[label, value], ...] }
      // Shared result bucket for the Terrain/Entities/Data ribbon tabs' own
      // sidecar calls (terrain.*, entities.list, data.*) -- same shape as
      // the Analyze tab's own state above, rendered in its own pane section
      // so a Terrain result and an Analyze result never overwrite each other.
      workshopRunning: false,
      workshopError: null,
      workshopResult: null, // { command, rows: [[label, value], ...] }
    };

    root.setAttribute("data-studio-workspace", "1");
    root.setAttribute("data-theme", state.theme);
    root.setAttribute("data-density", state.density);
    root.innerHTML = "";

    if (!hasSidecar()) {
      root.appendChild(
        el("div", { className: "sw-desktop-only", role: "status" }, [
          "Desktop only: the workspace ribbon, navigator and properties pane drive the " +
            "desktop app's sidecar, which is not available in a browser. Open this page " +
            "inside the Amulet Studio desktop app to use them.",
        ])
      );
      return { render: function () {}, state: state };
    }

    var actions = {
      undo: function () {
        var vp = viewportPanel();
        if (vp && typeof vp.runUndo === "function") vp.runUndo();
      },
      redo: function () {
        var vp = viewportPanel();
        if (vp && typeof vp.runRedo === "function") vp.runRedo();
      },
      save: function () {
        var vp = viewportPanel();
        if (vp && typeof vp.runSave === "function") vp.runSave();
      },
      copySelection: function () {
        var vp = viewportPanel();
        if (vp && typeof vp.runCopySelection === "function") vp.runCopySelection();
      },
      cutSelection: function () {
        var vp = viewportPanel();
        if (vp && typeof vp.runCutSelection === "function") vp.runCutSelection();
      },
      pasteSelection: function () {
        var vp = viewportPanel();
        if (vp && typeof vp.runPasteSelection === "function") vp.runPasteSelection();
      },
      deleteSelection: function () {
        var vp = viewportPanel();
        if (vp && typeof vp.runDeleteSelection === "function") vp.runDeleteSelection();
      },
      exportStructure: function () {
        var vp = viewportPanel();
        if (vp && typeof vp.runExportStructure === "function") vp.runExportStructure();
      },
      importStructure: function () {
        var vp = viewportPanel();
        if (vp && typeof vp.runImportStructure === "function") vp.runImportStructure();
      },
      createChunks: function () {
        var vp = viewportPanel();
        if (vp && typeof vp.runCreateChunks === "function") vp.runCreateChunks();
      },
      deleteChunks: function () {
        var vp = viewportPanel();
        if (vp && typeof vp.runDeleteChunks === "function") vp.runDeleteChunks();
      },
      pruneChunks: function () {
        var vp = viewportPanel();
        if (vp && typeof vp.runPruneChunks === "function") vp.runPruneChunks();
      },
      fill: function () {
        var vp = viewportPanel();
        if (vp && typeof vp.runFill === "function") vp.runFill();
      },
      replace: function () {
        var vp = viewportPanel();
        if (vp && typeof vp.runReplace === "function") vp.runReplace();
      },
      showPane: function () {
        state.paneOpen = true;
        render();
      },
      // "Inspector" (Panels tab): open and focus the real properties pane
      // -- see the group comment above for why there is no second panel.
      openInspector: function () {
        state.paneOpen = true;
        state.paneTab = "properties";
        render();
      },
      // "Notifications" (Automate tab): press the real notification-drawer
      // toggle studio-shell.js/notifications.js already wire on this same
      // page, rather than reimplementing a second notification list here.
      openNotifications: function () {
        var openBtn = document.getElementById("notif-open");
        if (openBtn && typeof openBtn.click === "function") openBtn.click();
      },
      togglePane: function () {
        state.paneOpen = !state.paneOpen;
        render();
      },
      toggleRibbon: function () {
        state.ribbonOpen = !state.ribbonOpen;
        render();
      },
      toggleNavigator: function () {
        state.navOpen = !state.navOpen;
        try {
          window.localStorage.setItem(NAV_OPEN_KEY, state.navOpen ? "1" : "0");
        } catch (err) {
          /* ignore */
        }
        render();
      },
      // "Layers" (View tab): the only render layer this build's viewport
      // actually draws separately from the world itself is the reference
      // grid overlay (docs/site/viewport-overlays.js), so that is what this
      // toggles -- real and local, via viewport-panel.js's setGridVisible.
      toggleGrid: function () {
        var vp = viewportPanel();
        if (!vp || typeof vp.setGridVisible !== "function") return;
        state.gridVisible = vp.setGridVisible(!vp.isGridVisible());
        try {
          window.localStorage.setItem(GRID_VISIBLE_KEY, state.gridVisible ? "1" : "0");
        } catch (err) {
          /* ignore */
        }
        render();
      },
      // "Options" (View tab): the real per-element appearance editor this
      // build ships (already used by the pane header's own edit icon) --
      // there is no second, broader settings surface to distinguish it
      // from yet, so Options opens the same overlay.
      openOptions: function () {
        openAppearanceEditorOverlay();
      },
      toggleTheme: function () {
        state.theme = state.theme === "dark" ? "light" : "dark";
        try {
          window.localStorage.setItem(THEME_KEY, state.theme);
        } catch (err) {
          /* ignore */
        }
        root.setAttribute("data-theme", state.theme);
      },
      densitySelect: {
        label: "Density",
        value: state.density,
        options: [
          { value: "compact", label: "Compact" },
          { value: "comfortable", label: "Comfortable" },
          { value: "spacious", label: "Spacious" },
        ],
        onChange: function (value) {
          state.density = value;
          try {
            window.localStorage.setItem(DENSITY_KEY, value);
          } catch (err) {
            /* ignore */
          }
          root.setAttribute("data-density", value);
        },
      },
      selectionFields: null, // filled in per-render from the live edit panel

      // -------------------------------------------------- Analyze tab
      // Every analyze.* call is strictly read-only (see
      // amulet_map_editor/api/sidecar/analyze_methods.py's module docstring)
      // so unlike fill/replace there is no confirm gate to thread through
      // here -- running one of these never touches undo/redo or disk.
      runAnalyzeCommand: function (label, callBridge, summarize) {
        var vp = viewportPanel();
        var edit = vp && vp.edit;
        var points = edit && typeof edit.readPoints === "function" ? edit.readPoints() : null;
        var eb = window.AmuletSite && window.AmuletSite.electronSidecar;
        var worldId = vp && typeof vp.getWorldId === "function" ? vp.getWorldId() : null;
        var dimension = vp && typeof vp.getDimension === "function" ? vp.getDimension() : null;
        if (!points) {
          state.analyzeError = label + ": set point 1 and point 2 in the viewport's edit panel first.";
          state.analyzeResult = null;
          render();
          return;
        }
        if (!eb || typeof eb.analyze !== "object" || worldId === null || !dimension) {
          state.analyzeError = label + ": no world open in the viewport yet.";
          state.analyzeResult = null;
          render();
          return;
        }
        state.analyzeRunning = true;
        state.analyzeError = null;
        render();
        callBridge(eb.analyze, worldId, dimension, points.point1, points.point2)
          .then(function (result) {
            state.analyzeRunning = false;
            state.analyzeError = null;
            state.analyzeResult = { command: label, rows: summarize(result) };
            render();
          })
          .catch(function (err) {
            state.analyzeRunning = false;
            state.analyzeResult = null;
            state.analyzeError = label + ": " + (err && err.message ? err.message : String(err));
            render();
          });
      },
      analyzeBlockHistogram: function () {
        actions.runAnalyzeCommand(
          "Histogram",
          function (analyze, worldId, dimension, min, max) {
            return analyze.blockHistogram(worldId, dimension, min, max);
          },
          function (result) {
            var rows = [
              ["Blocks scanned", String(result.blocks_scanned)],
              ["Distinct blocks", String(result.distinct_blocks)],
            ];
            (result.histogram || []).slice(0, 8).forEach(function (entry) {
              rows.push([entry.block, entry.count + " (" + entry.percentage + "%)"]);
            });
            return rows;
          }
        );
      },
      analyzeChunkInventory: function () {
        actions.runAnalyzeCommand(
          "Chunk inspector",
          function (analyze, worldId, dimension, min, max) {
            return analyze.chunkInventory(worldId, dimension, min, max);
          },
          function (result) {
            var rows = [
              ["Chunks in range", String(result.chunks_in_range)],
              ["Chunks present", String(result.chunks_present)],
            ];
            (result.chunks || []).slice(0, 8).forEach(function (chunk) {
              rows.push([
                "chunk " + chunk.cx + "," + chunk.cz,
                (chunk.changed ? "changed" : "unchanged") +
                  " · " +
                  chunk.entity_count +
                  " entities · " +
                  chunk.block_entity_count +
                  " block entities",
              ]);
            });
            return rows;
          }
        );
      },
      analyzeBlockAudit: function () {
        actions.runAnalyzeCommand(
          "Validate (block audit)",
          function (analyze, worldId, dimension, min, max) {
            return analyze.blockAudit(worldId, dimension, min, max);
          },
          function (result) {
            var rows = [
              ["Blocks scanned", String(result.blocks_scanned)],
              ["Flagged blocks", String(result.flagged_count)],
            ];
            (result.flagged_blocks || []).slice(0, 8).forEach(function (entry) {
              rows.push([entry.block, String(entry.count)]);
            });
            if (!result.flagged_count) rows.push(["Result", "No non-universal blocks found in the selection."]);
            return rows;
          }
        );
      },

      // ------------------------------------------ Terrain/Entities/Data
      // Shared preconditions for every command below: a real selection from
      // the viewport's own edit panel, a sidecar, and a streaming world --
      // the exact same three checks runAnalyzeCommand makes above. Returns
      // null (having already recorded the honest reason and re-rendered)
      // when a precondition is missing, so a caller can just return early.
      workshopContext: function (label) {
        var vp = viewportPanel();
        var edit = vp && vp.edit;
        var points = edit && typeof edit.readPoints === "function" ? edit.readPoints() : null;
        var eb = window.AmuletSite && window.AmuletSite.electronSidecar;
        var worldId = vp && typeof vp.getWorldId === "function" ? vp.getWorldId() : null;
        var dimension = vp && typeof vp.getDimension === "function" ? vp.getDimension() : null;
        if (!points) {
          state.workshopError = label + ": set point 1 and point 2 in the viewport's edit panel first.";
          state.workshopResult = null;
          render();
          return null;
        }
        if (!eb || worldId === null || !dimension) {
          state.workshopError = label + ": no world open in the viewport yet.";
          state.workshopResult = null;
          render();
          return null;
        }
        return { eb: eb, worldId: worldId, dimension: dimension, points: points, edit: edit };
      },

      runWorkshopCommand: function (label, call, summarize) {
        state.workshopRunning = true;
        state.workshopError = null;
        render();
        call()
          .then(function (result) {
            state.workshopRunning = false;
            state.workshopError = null;
            state.workshopResult = { command: label, rows: summarize(result) };
            render();
          })
          .catch(function (err) {
            state.workshopRunning = false;
            state.workshopResult = null;
            state.workshopError = label + ": " + (err && err.message ? err.message : String(err));
            render();
          });
      },

      // "Flatten" flattens the current selection to its own top Y (the
      // higher of the two selected points' Y) using the fill-block field's
      // block -- no separate height field exists in this build's edit
      // panel, so the selection's own extent is the honest, real value used
      // rather than an invented default.
      terrainFlatten: function () {
        var ctx = actions.workshopContext("Flatten");
        if (!ctx) return;
        var block = ctx.edit.blockValue();
        if (!block) {
          state.workshopError = "Flatten: enter a block ID in the fill-block field first.";
          state.workshopResult = null;
          render();
          return;
        }
        var height = Math.max(ctx.points.point1[1], ctx.points.point2[1]);
        var run = function () {
          actions.runWorkshopCommand(
            "Flatten",
            function () {
              return ctx.eb.terrain.flatten(ctx.worldId, ctx.dimension, ctx.points.point1, ctx.points.point2, height, block, true);
            },
            function (result) {
              return [
                ["Blocks changed", String(result.blocks_changed)],
                ["Height", String(result.height)],
              ];
            }
          );
        };
        var site = window.AmuletSite;
        if (site && typeof site.confirmDestructive === "function") {
          site.confirmDestructive({
            title: "Flatten selection",
            detail: "Flattens the selection to Y=" + height + " with " + block + ".",
            confirm: "Flatten",
            onConfirm: run,
          });
        } else {
          run();
        }
      },

      // "Sea level" raises or drains the water table across the selection at
      // its own midpoint Y -- there is no dedicated sea level Y field in
      // this build's edit panel, so the selection's vertical midpoint is
      // the real, computed value used. The mode (raise or drain) comes from
      // the Sea level mode select in the viewport's edit panel -- both
      // modes are real in the sidecar (terrain.sea_level's "raise"/"drain"),
      // so this reads the real control instead of hard-coding "raise".
      terrainSeaLevel: function () {
        var ctx = actions.workshopContext("Sea level");
        if (!ctx) return;
        var seaLevel = Math.round((ctx.points.point1[1] + ctx.points.point2[1]) / 2);
        var mode = ctx.edit && typeof ctx.edit.seaLevelModeValue === "function" ? ctx.edit.seaLevelModeValue() : "raise";
        var run = function () {
          actions.runWorkshopCommand(
            "Sea level",
            function () {
              return ctx.eb.terrain.seaLevel(ctx.worldId, ctx.dimension, ctx.points.point1, ctx.points.point2, seaLevel, mode, true);
            },
            function (result) {
              return [
                ["Blocks changed", String(result.blocks_changed)],
                ["Sea level", String(result.sea_level)],
                ["Mode", result.mode],
              ];
            }
          );
        };
        var site = window.AmuletSite;
        if (site && typeof site.confirmDestructive === "function") {
          site.confirmDestructive({
            title: mode === "drain" ? "Drain sea level" : "Raise sea level",
            detail:
              mode === "drain"
                ? "Turns every water block in the selection into air."
                : "Fills air at or below Y=" + seaLevel + " in the selection with water.",
            confirm: mode === "drain" ? "Drain" : "Raise",
            onConfirm: run,
          });
        } else {
          run();
        }
      },

      // "Repaint" repaints the topmost non-air block of every column in the
      // selection with the fill-block field's block.
      terrainRepaint: function () {
        var ctx = actions.workshopContext("Repaint");
        if (!ctx) return;
        var block = ctx.edit.blockValue();
        if (!block) {
          state.workshopError = "Repaint: enter a block ID in the fill-block field first.";
          state.workshopResult = null;
          render();
          return;
        }
        var run = function () {
          actions.runWorkshopCommand(
            "Repaint",
            function () {
              return ctx.eb.terrain.repaint(ctx.worldId, ctx.dimension, ctx.points.point1, ctx.points.point2, block, true);
            },
            function (result) {
              return [["Blocks changed", String(result.blocks_changed)]];
            }
          );
        };
        var site = window.AmuletSite;
        if (site && typeof site.confirmDestructive === "function") {
          site.confirmDestructive({
            title: "Repaint surface",
            detail: "Repaints the topmost block of every column in the selection with " + block + ".",
            confirm: "Repaint",
            onConfirm: run,
          });
        } else {
          run();
        }
      },

      // "Cuboid" (Build tab) is literally world.fill with the fill-block
      // field's block -- "Fill the selection as a box" is exactly what
      // world.fill already does, so this reuses the same wired write path
      // as the Operations tab's own Fill command rather than a second copy.
      buildCuboid: function () {
        actions.fill();
      },

      // "Entities" (Entities tab) lists every entity in the selection --
      // strictly read-only, same shape as the Analyze tab's own commands.
      entitiesList: function () {
        var ctx = actions.workshopContext("Entities");
        if (!ctx) return;
        actions.runWorkshopCommand(
          "Entities",
          function () {
            return ctx.eb.entities.list(ctx.worldId, ctx.dimension, ctx.points.point1, ctx.points.point2);
          },
          function (result) {
            var rows = [["Count", String(result.count)]];
            (result.entities || []).slice(0, 12).forEach(function (entity) {
              rows.push([
                entity.namespace + ":" + entity.base_name,
                "(" + entity.x + ", " + entity.y + ", " + entity.z + ")",
              ]);
            });
            if (!result.count) rows.push(["Result", "No entities in the selection."]);
            return rows;
          }
        );
      },

      // "Place" and "Remove" (Entities tab, Edit group) call the real
      // entities.place/entities.remove backend. Both were disabled purely
      // for want of a type/filter field to drive them from -- viewport-
      // panel.js's edit panel now has that field (entityTypeValue()), and
      // runPlaceEntity/runRemoveEntities on the viewport panel itself do the
      // parsing, the confirm gate, and the bridge call, the same way
      // runFill/runCopySelection/etc. already do for every other write here.
      entitiesPlace: function () {
        var vp = viewportPanel();
        if (vp && typeof vp.runPlaceEntity === "function") vp.runPlaceEntity();
      },
      entitiesRemove: function () {
        var vp = viewportPanel();
        if (vp && typeof vp.runRemoveEntities === "function") vp.runRemoveEntities();
      },

      // "level.dat" (Data tab) reads the world's real level.dat fields --
      // read-only; no selection is required.
      dataLevelRead: function () {
        var vp = viewportPanel();
        var eb = window.AmuletSite && window.AmuletSite.electronSidecar;
        var worldId = vp && typeof vp.getWorldId === "function" ? vp.getWorldId() : null;
        if (!eb || worldId === null) {
          state.workshopError = "level.dat: no world open in the viewport yet.";
          state.workshopResult = null;
          render();
          return;
        }
        actions.runWorkshopCommand(
          "level.dat",
          function () {
            return eb.data.readLevel(worldId);
          },
          function (result) {
            return [
              ["Level name", String(result.level_name)],
              ["Data version", String(result.data_version)],
              ["Difficulty", String(result.difficulty)],
              ["Hardcore", String(result.hardcore)],
              ["Raining", String(result.raining)],
              ["Thundering", String(result.thundering)],
            ];
          }
        );
      },

      // "Game rules" (Data tab) reads the world's real GameRules compound --
      // read-only; no selection is required.
      dataGameRulesRead: function () {
        var vp = viewportPanel();
        var eb = window.AmuletSite && window.AmuletSite.electronSidecar;
        var worldId = vp && typeof vp.getWorldId === "function" ? vp.getWorldId() : null;
        if (!eb || worldId === null) {
          state.workshopError = "Game rules: no world open in the viewport yet.";
          state.workshopResult = null;
          render();
          return;
        }
        actions.runWorkshopCommand(
          "Game rules",
          function () {
            return eb.data.readGameRules(worldId);
          },
          function (result) {
            var rules = result.game_rules || {};
            var names = Object.keys(rules).sort();
            if (!names.length) return [["Result", "This world has no GameRules recorded yet."]];
            return names.map(function (name) {
              return [name, rules[name]];
            });
          }
        );
      },

      // "Write level.dat" and "Write game rule" (Data tab) call the real
      // data.level_write/data.game_rules_write backend. Both were disabled
      // purely for want of editable fields -- viewport-panel.js's edit
      // panel now has them, and runWriteLevel/runWriteGameRules on the
      // viewport panel itself validate the values, apply the confirm gate,
      // and make the bridge call.
      dataLevelWrite: function () {
        var vp = viewportPanel();
        if (vp && typeof vp.runWriteLevel === "function") vp.runWriteLevel();
      },
      dataGameRulesWrite: function () {
        var vp = viewportPanel();
        if (vp && typeof vp.runWriteGameRules === "function") vp.runWriteGameRules();
      },
    };

    // -------------------------------------------------------------- DOM
    var ribbonGroupsRow = el("div", { className: "sw-ribbon-groups" });
    var ribbonSearchInput = el("input", {
      placeholder: "Search this tab's commands",
      "aria-label": "Search this tab's commands",
    });
    var ribbonToggleBtn = el("button", { type: "button", className: "sw-ribbon-toggle", title: "Collapse or expand the command ribbon" }, ["⌃"]);
    var ribbonSearchWrap = el("div", { className: "sw-ribbon-search" }, [
      ribbonSearchInput,
      el("button", { type: "button", className: "sw-regex-btn", title: "Regex builder for this tab's command search" }, [".*"]),
    ]);

    var breadcrumbRow = el("div", { className: "sw-breadcrumb" });
    var navigatorEl = el("div", { className: "sw-navigator" });
    var viewportColumn = el("div", { className: "sw-viewport-column" });
    var paneEl = el("div", { className: "sw-pane" });
    var statusBar = el("div", { className: "sw-status-bar" });
    var bodyRow = el("div", { className: "sw-body" }, [navigatorEl, viewportColumn, paneEl]);

    ribbonSearchInput.addEventListener("input", function () {
      state.ribbonSearch = ribbonSearchInput.value;
      renderRibbonGroups();
    });
    ribbonToggleBtn.addEventListener("click", function () {
      actions.toggleRibbon();
    });

    var ribbonRow = el("div", {
      className: "sw-ribbon-tabs",
      onContextmenu: function (e) {
        openRibbonMenu(e);
      },
    });
    RIBBON_TAB_DEFS.forEach(function (tab) {
      var tabBtn = el(
        "button",
        {
          type: "button",
          className: "sw-ribbon-tab",
          "aria-selected": tab.key === state.ribbonTab ? "true" : "false",
          onClick: function () {
            state.ribbonTab = tab.key;
            render();
          },
        },
        [tab.label]
      );
      tabBtn.setAttribute("data-tab-key", tab.key);
      ribbonRow.appendChild(tabBtn);
    });
    ribbonRow.appendChild(el("div", { style: "flex:1" }));
    ribbonRow.appendChild(ribbonSearchWrap);
    ribbonRow.appendChild(ribbonToggleBtn);

    // -------------------------------------------------------- viewport host
    // Mounted with exactly the ids viewport-panel.js's own DOMContentLoaded
    // init() looks for (docs/site/viewport-panel.js init()), so that module
    // is reused unmodified rather than reimplemented here.
    var viewportOpenInput = el("input", {
      type: "text",
      id: "viewport-world-path",
      placeholder: "Absolute path to a world folder",
      "aria-label": "World path to open in the viewport",
      autocomplete: "off",
      maxlength: "1024",
    });
    var viewportOpenButton = el("button", { type: "button", id: "viewport-open-button", className: "sw-ribbon-btn" }, ["Open world"]);
    var viewportOpenRow = el("div", { id: "viewport-open-row" }, [viewportOpenInput, viewportOpenButton]);
    var viewportCanvas = el("canvas", {
      id: "viewport-canvas",
      width: "1024",
      height: "640",
      tabindex: "0",
      "aria-label":
        "3D world viewport. Drag to look around, scroll to move forward and back, WASD or arrow keys to move and look.",
    });
    var viewportEmpty = el("p", { id: "viewport-empty", className: "sw-desktop-only" });
    var viewportHost = el("div", { id: "viewport-host", className: "sw-viewport-host" }, [
      viewportOpenRow,
      viewportCanvas,
      viewportEmpty,
    ]);
    viewportColumn.appendChild(viewportHost);
    viewportColumn.appendChild(statusBar);

    viewportHost.addEventListener("contextmenu", function (event) {
      openViewportMenu(event);
    });

    // The shared searchable context menu (docs/site/context-menu.js). Each
    // surface registers only actions that already exist in this module or in
    // the viewport panel it drives -- a menu row is never a second, invented
    // command with its own idea of what it does.
    function ribbonMenuItems() {
      return [
        RIBBON_TAB_DEFS.map(function (tab) {
          return {
            label: "Tab: " + tab.label,
            run: function () {
              state.ribbonTab = tab.key;
              render();
            },
          };
        }),
        [
          { separator: true },
          { label: "Toggle ribbon", shortcut: "", run: function () { actions.toggleRibbon(); } },
          { label: "Toggle properties pane", run: function () { actions.togglePane(); } },
          { label: "Toggle navigator", run: function () { actions.toggleNavigator(); } },
          {
            label: "Open command palette",
            shortcut: "Ctrl+Shift+F",
            run: function () {
              var trigger = document.getElementById("palette-open");
              if (trigger && typeof trigger.click === "function") trigger.click();
            },
          },
        ],
      ].reduce(function (out, list) {
        return out.concat(list);
      }, []);
    }

    function openRibbonMenu(event) {
      if (!window.AmuletSite || typeof window.AmuletSite.contextMenu !== "function") {
        event.preventDefault();
        return;
      }
      window.AmuletSite.contextMenu(ribbonMenuItems(), event, "Ribbon commands");
    }

    function viewportMenuItems() {
      var vp = viewportPanel();
      return [
        { label: "Undo", shortcut: "Ctrl+Z", disabled: !vp || typeof vp.runUndo !== "function", reason: UNWIRED_REASON, run: vp ? vp.runUndo : null },
        { label: "Redo", shortcut: "Ctrl+Y", disabled: !vp || typeof vp.runRedo !== "function", reason: UNWIRED_REASON, run: vp ? vp.runRedo : null },
        { label: "Save world", shortcut: "Ctrl+S", disabled: !vp || typeof vp.runSave !== "function", reason: UNWIRED_REASON, run: vp ? vp.runSave : null },
        { separator: true },
        { label: "Copy selection", disabled: !vp || typeof vp.runCopySelection !== "function", reason: NO_WORLD_REASON, run: vp ? vp.runCopySelection : null },
        { label: "Cut selection", disabled: !vp || typeof vp.runCutSelection !== "function", reason: NO_WORLD_REASON, run: vp ? vp.runCutSelection : null },
        { label: "Paste at point 1", disabled: !vp || typeof vp.runPasteSelection !== "function", reason: NO_WORLD_REASON, run: vp ? vp.runPasteSelection : null },
        { label: "Delete selection", disabled: !vp || typeof vp.runDeleteSelection !== "function", reason: NO_WORLD_REASON, run: vp ? vp.runDeleteSelection : null },
        { separator: true },
        {
          label: "Select chunk under camera",
          disabled: !vp || typeof vp.selectChunkUnderCamera !== "function",
          reason: UNWIRED_REASON,
          run: vp ? vp.selectChunkUnderCamera : null,
        },
        {
          label: "Toggle reference grid",
          disabled: !vp || typeof vp.setGridVisible !== "function",
          reason: NO_WORLD_REASON,
          run: function () { actions.toggleGrid(); },
        },
      ];
    }

    function openViewportMenu(event) {
      if (!window.AmuletSite || typeof window.AmuletSite.contextMenu !== "function") {
        event.preventDefault();
        return;
      }
      window.AmuletSite.contextMenu(viewportMenuItems(), event, "Viewport actions");
    }

    // The navigator's own listener on the SAME open button, so choosing a
    // world path once populates both the 3D viewport (via
    // viewport-panel.js's own listener) and this workspace's navigator
    // (dimensions, via the sidecar's world.dimensions) -- one action,
    // two real consumers, no duplicated "open a world" UI.
    viewportOpenButton.addEventListener("click", function () {
      var path = viewportOpenInput.value.trim();
      if (!path) return;
      loadDimensionsForPath(path);
    });

    function loadDimensionsForPath(path) {
      state.dimensions = [];
      state.worldOpenError = null;
      renderNavigator();
      sidecarCall("world.open", { path: path }).then(function (opened) {
        if (!opened.ok) {
          state.worldOpenError = "world.open failed.";
          renderNavigator();
          return;
        }
        var worldId = opened.result.world_id;
        pollUntilReady(worldId, 0);
      });
    }

    function pollUntilReady(worldId, attempt) {
      if (attempt > 200) {
        state.worldOpenError = "Timed out waiting for the world to open.";
        renderNavigator();
        return;
      }
      sidecarCall("world.open_status", { world_id: worldId }).then(function (statusResp) {
        if (!statusResp.ok) {
          state.worldOpenError = "world.open_status failed.";
          renderNavigator();
          return;
        }
        var result = statusResp.result;
        if (result.status === "pending") {
          setTimeout(function () {
            pollUntilReady(worldId, attempt + 1);
          }, 150);
          return;
        }
        if (result.status === "failed") {
          state.worldOpenError = (result.error && result.error.message) || "That world failed to open.";
          renderNavigator();
          return;
        }
        state.worldId = worldId;
        sidecarCall("world.dimensions", { world_id: worldId }).then(function (dimResp) {
          if (!dimResp.ok) {
            state.worldOpenError = "world.dimensions failed.";
            renderNavigator();
            return;
          }
          state.dimensions = dimResp.result.dimensions || [];
          if (state.dimensions.length && state.navSelected === null) {
            state.navSelected = state.dimensions[0].dimension;
          }
          renderNavigator();
        });
      });
    }

    // ---------------------------------------------------------- render
    function paneTabDefs() {
      return [
        { key: "properties", label: "Properties" },
        { key: "layers", label: "Layers" },
        { key: "history", label: "History" },
      ];
    }

    function renderBreadcrumb() {
      breadcrumbRow.innerHTML = "";
      var crumbs = [{ label: "Project", target: null }];
      if (state.navSelected) crumbs.push({ label: "minecraft:" + state.navSelected, target: state.navSelected });
      crumbs.forEach(function (crumb, i) {
        if (i > 0) breadcrumbRow.appendChild(el("span", { className: "sw-crumb-sep" }, ["›"]));
        breadcrumbRow.appendChild(el("span", { className: "sw-crumb" }, [crumb.label]));
      });
      breadcrumbRow.appendChild(el("div", { className: "sw-breadcrumb-fill" }));
      var vp = viewportPanel();
      var revisionKnown = false; // this build has no per-project Git repository read path yet
      breadcrumbRow.appendChild(
        el(
          "button",
          {
            type: "button",
            className: "sw-revision-pill",
            disabled: !revisionKnown,
            title: revisionKnown ? "Project history" : UNWIRED_REASON,
          },
          [el("span", { className: "sw-revision-dot" }), revisionKnown ? "head revision" : "no project history yet"]
        )
      );
      var pointsSummary = "No selection set";
      var edit = vp && vp.edit;
      if (edit && typeof edit.readPoints === "function") {
        var points = edit.readPoints();
        if (points) {
          pointsSummary =
            "(" + points.point1.join(", ") + ") → (" + points.point2.join(", ") + ")";
        }
      }
      breadcrumbRow.appendChild(el("span", { className: "sw-summary-pill sw-mono" }, [pointsSummary]));
    }

    function renderNavigator() {
      navigatorEl.innerHTML = "";
      navigatorEl.addEventListener("contextmenu", function (event) {
        openNavigatorMenu(event);
      });
      navigatorEl.appendChild(
        el("div", { className: "sw-nav-header" }, [el("span", { style: "flex:1" }, ["Navigator"])])
      );
      var searchInput = el("input", { placeholder: "Search navigator", "aria-label": "Search navigator" });
      searchInput.value = state.navSearch;
      searchInput.addEventListener("input", function () {
        state.navSearch = searchInput.value;
        renderNavigator();
      });
      navigatorEl.appendChild(el("div", { className: "sw-nav-search" }, [searchInput]));

      var list = el("div", { className: "sw-nav-list" });
      if (state.worldOpenError) {
        navigatorEl.appendChild(el("p", { className: "sw-nav-empty" }, [state.worldOpenError]));
      } else if (!state.dimensions.length) {
        navigatorEl.appendChild(
          el("p", { className: "sw-nav-empty" }, [
            "No world open yet. Enter a world folder path in the viewport below and choose Open world.",
          ])
        );
      } else {
        state.dimensions
          .filter(function (d) {
            return matchesQuery(state.navSearch, false, d.dimension);
          })
          .forEach(function (d) {
            var meta = navigatorLabel(d.dimension);
            var count = "—";
            if (d.bounds && d.bounds.min && d.bounds.max) {
              count =
                Math.abs(d.bounds.max[0] - d.bounds.min[0]) +
                "x" +
                Math.abs(d.bounds.max[1] - d.bounds.min[1]) +
                "x" +
                Math.abs(d.bounds.max[2] - d.bounds.min[2]);
            }
            var itemBtn = el(
              "button",
              {
                type: "button",
                className: "sw-nav-item",
                "aria-selected": state.navSelected === d.dimension ? "true" : "false",
                onClick: function () {
                  state.navSelected = d.dimension;
                  renderNavigator();
                  renderBreadcrumb();
                },
              },
              [
                el("span", { className: "sw-nav-item-label" }, [meta.label + " · " + d.dimension]),
                el("span", { className: "sw-nav-count sw-mono" }, [count]),
              ]
            );
            list.appendChild(itemBtn);
          });
        navigatorEl.appendChild(list);
      }

      navigatorEl.appendChild(
        el("div", { className: "sw-boxes-header" }, [
          el("span", { style: "flex:1" }, ["Selection boxes"]),
          el("span", { className: "sw-boxes-count" }, ["1"]),
        ])
      );
      var boxesList = el("div", { className: "sw-boxes-list" });
      var vp = viewportPanel();
      var edit = vp && vp.edit;
      var points = edit && typeof edit.readPoints === "function" ? edit.readPoints() : null;
      if (points) {
        var dx = Math.abs(points.point2[0] - points.point1[0]) + 1;
        var dy = Math.abs(points.point2[1] - points.point1[1]) + 1;
        var dz = Math.abs(points.point2[2] - points.point1[2]) + 1;
        boxesList.appendChild(
          el("div", { className: "sw-box-card" }, [
            el("b", {}, ["Box 1 · active"]),
            el("small", { className: "sw-mono" }, [dx + "x" + dy + "x" + dz + " at " + points.point1.join(", ")]),
          ])
        );
      } else {
        boxesList.appendChild(
          el("p", { className: "sw-nav-empty" }, [
            "No selection box yet. Set point 1 and point 2 in the viewport's edit panel below.",
          ])
        );
      }
      navigatorEl.appendChild(boxesList);
    }

    function navigatorMenuItems() {
      var items = [];
      state.dimensions.forEach(function (d) {
        var meta = navigatorLabel(d.dimension);
        items.push({
          label: "Go to " + meta.label + " · " + d.dimension,
          disabled: false,
          run: function () {
            state.navSelected = d.dimension;
            renderNavigator();
            renderBreadcrumb();
          },
        });
      });
      items.push({ separator: true });
      var vp = viewportPanel();
      items.push({
        label: "Copy selection",
        disabled: !vp || typeof vp.runCopySelection !== "function",
        reason: NO_WORLD_REASON,
        run: vp ? vp.runCopySelection : null,
      });
      items.push({
        label: "Delete selection",
        disabled: !vp || typeof vp.runDeleteSelection !== "function",
        reason: NO_WORLD_REASON,
        run: vp ? vp.runDeleteSelection : null,
      });
      items.push({
        label: "Fill selection",
        disabled: !vp || typeof vp.runFill !== "function",
        reason: NO_WORLD_REASON,
        run: vp ? vp.runFill : null,
      });
      return items;
    }

    function openNavigatorMenu(event) {
      if (!window.AmuletSite || typeof window.AmuletSite.contextMenu !== "function") {
        event.preventDefault();
        return;
      }
      window.AmuletSite.contextMenu(navigatorMenuItems(), event, "Navigator actions");
    }

    function fieldsRow(fields) {
      var wrap = el("div", { className: "sw-pane-row" });
      return wrap;
    }

    function commandButton(item, tabKey, groupTitle) {
      var enabled;
      var reason = "";
      if (typeof item.run !== "function") {
        enabled = false;
        reason = UNWIRED_REASON;
        state.unwiredCommandCount++;
      } else if (item.requiresSidecar && !hasSidecar()) {
        enabled = false;
        reason = NO_SIDECAR_REASON;
      } else if (item.requiresWorld && !worldStreaming()) {
        enabled = false;
        reason = NO_WORLD_REASON;
      } else {
        enabled = true;
        state.wiredCommandCount++;
      }
      var button = el(
        "button",
        {
          type: "button",
          className: "sw-ribbon-btn",
          disabled: !enabled,
          title: enabled ? item.hint : item.hint + " (" + reason + ")",
          "data-primary": item.primary ? "true" : "false",
          "aria-label": item.label,
          onClick: enabled
            ? function () {
                item.run();
                render();
              }
            : null,
        },
        [el("span", { className: "sw-ribbon-glyph" }, [item.glyph]), el("span", { className: "sw-ribbon-label" }, [item.label])]
      );
      return button;
    }

    function renderRibbonGroups() {
      ribbonGroupsRow.innerHTML = "";
      if (!state.ribbonOpen) return;
      state.wiredCommandCount = 0;
      state.unwiredCommandCount = 0;
      actions.selectionFields = null;
      var vp = viewportPanel();
      var edit = vp && vp.edit;
      var points = edit && typeof edit.readPoints === "function" ? edit.readPoints() : null;
      actions.selectionFields = points
        ? [
            { label: "x1", value: String(points.point1[0]) },
            { label: "y1", value: String(points.point1[1]) },
            { label: "z1", value: String(points.point1[2]) },
            { label: "x2", value: String(points.point2[0]) },
            { label: "y2", value: String(points.point2[1]) },
            { label: "z2", value: String(points.point2[2]) },
          ]
        : [
            { label: "x1", value: "—" }, { label: "y1", value: "—" }, { label: "z1", value: "—" },
            { label: "x2", value: "—" }, { label: "y2", value: "—" }, { label: "z2", value: "—" },
          ];

      var ribbon = buildRibbonByTab(actions);
      var groups = ribbon[state.ribbonTab] || ribbon.home;
      var query = state.ribbonSearch;
      groups.forEach(function (g) {
        var visibleItems = g.items.filter(function (item) {
          return matchesQuery(query, false, item.label + " " + item.hint);
        });
        if (!visibleItems.length && !g.fields && !g.select && query) return;
        var groupEl = el("div", { className: "sw-ribbon-group" });
        var itemsRow = el("div", { className: "sw-ribbon-group-items" });
        visibleItems.forEach(function (item) {
          itemsRow.appendChild(commandButton(item, state.ribbonTab, g.title));
        });
        if (g.fields) {
          var fieldsWrap = el("div", { style: "display:grid;grid-template-columns:auto 1fr auto 1fr;gap:5px 8px;align-items:center;padding:2px 4px" });
          g.fields.forEach(function (f) {
            fieldsWrap.appendChild(el("span", { className: "sw-mono", style: "font-size:11px;color:var(--sw-onv)" }, [f.label]));
            fieldsWrap.appendChild(
              el("span", { className: "sw-mono", style: "font-size:12px;padding:4px 8px;border:1px solid var(--sw-ol);border-radius:7px;background:var(--sw-sc)" }, [f.value])
            );
          });
          itemsRow.appendChild(fieldsWrap);
        }
        if (g.select) {
          var selectEl = el("select", {
            "aria-label": g.select.label,
            onChange: function (e) {
              g.select.onChange(e.target.value);
            },
          });
          g.select.options.forEach(function (opt) {
            var optionEl = el("option", { value: opt.value }, [opt.label]);
            if (opt.value === g.select.value) optionEl.setAttribute("selected", "selected");
            selectEl.appendChild(optionEl);
          });
          var selectWrap = el("label", { style: "display:grid;gap:3px;font-size:11px;color:var(--sw-onv);padding:2px 4px;min-width:150px" }, [
            g.select.label,
            selectEl,
          ]);
          itemsRow.appendChild(selectWrap);
        }
        groupEl.appendChild(itemsRow);
        groupEl.appendChild(el("div", { className: "sw-ribbon-group-title" }, [g.title]));
        ribbonGroupsRow.appendChild(groupEl);
      });
    }

    /**
     * Opens the real per-element appearance editor (docs/site/
     * studio-appearance.js) anchored in a lightweight overlay, rather than a
     * button that only announces it is unwired. Lazily built and reused
     * across opens so repeated clicks do not accumulate detached overlays.
     */
    var appearanceOverlay = null;
    function openAppearanceEditorOverlay() {
      if (!window.AmuletStudioAppearance) return;
      if (!appearanceOverlay) {
        appearanceOverlay = el("div", { className: "sw-appearance-overlay", role: "dialog", "aria-label": "Edit appearance" });
        var panelHost = el("div", { className: "sw-appearance-overlay-panel" });
        var closeBtn = el(
          "button",
          {
            type: "button",
            className: "sw-pane-icon-btn",
            title: "Close the appearance editor",
            onClick: function () {
              appearanceOverlay.hidden = true;
            },
          },
          ["×"]
        );
        appearanceOverlay.appendChild(closeBtn);
        appearanceOverlay.appendChild(panelHost);
        document.body.appendChild(appearanceOverlay);
        window.AmuletStudioAppearance.mount(panelHost);
      }
      appearanceOverlay.hidden = false;
    }

    function renderPane() {
      paneEl.innerHTML = "";
      if (!state.paneOpen) return;
      var header = el("div", { className: "sw-pane-header" }, [
        el("span", { className: "sw-pane-title" }, ["Properties"]),
        el(
          "button",
          {
            type: "button",
            className: "sw-pane-icon-btn",
            title: window.AmuletStudioAppearance
              ? "Edit appearance for this pane"
              : "Edit appearance for this pane (" + UNWIRED_REASON + ")",
            disabled: !window.AmuletStudioAppearance,
            onClick: function () {
              openAppearanceEditorOverlay();
            },
          },
          ["✎"]
        ),
        el(
          "button",
          {
            type: "button",
            className: "sw-pane-icon-btn",
            title: "Close the properties pane",
            onClick: function () {
              state.paneOpen = false;
              render();
            },
          },
          ["×"]
        ),
      ]);
      paneEl.appendChild(header);

      var tabsRow = el("div", { className: "sw-pane-tabs" });
      paneTabDefs().forEach(function (t) {
        tabsRow.appendChild(
          el(
            "button",
            {
              type: "button",
              className: "sw-pane-tab",
              "aria-selected": state.paneTab === t.key ? "true" : "false",
              onClick: function () {
                state.paneTab = t.key;
                render();
              },
            },
            [t.label]
          )
        );
      });
      paneEl.appendChild(tabsRow);

      var body = el("div", { className: "sw-pane-body" });
      var vp = viewportPanel();
      var edit = vp && vp.edit;
      var points = edit && typeof edit.readPoints === "function" ? edit.readPoints() : null;

      if (state.paneTab === "properties") {
        var sections = [];
        if (points) {
          sections.push({
            title: "Point 1",
            rows: [
              { label: "x1", value: String(points.point1[0]) },
              { label: "y1", value: String(points.point1[1]) },
              { label: "z1", value: String(points.point1[2]) },
            ],
          });
          sections.push({
            title: "Point 2",
            rows: [
              { label: "x2", value: String(points.point2[0]) },
              { label: "y2", value: String(points.point2[1]) },
              { label: "z2", value: String(points.point2[2]) },
            ],
          });
        }
        sections.push({
          title: "World",
          rows: [
            { label: "Dimension", value: state.navSelected || "no world open" },
            { label: "Streaming", value: worldStreaming() ? "yes" : "no" },
          ],
        });
        if (state.analyzeRunning) {
          sections.push({ title: "Analysis", rows: [{ label: "Status", value: "Running…" }] });
        } else if (state.analyzeError) {
          sections.push({ title: "Analysis", rows: [{ label: "Error", value: state.analyzeError }] });
        } else if (state.analyzeResult) {
          sections.push({
            title: "Analysis · " + state.analyzeResult.command,
            rows: state.analyzeResult.rows.map(function (row) {
              return { label: row[0], value: row[1] };
            }),
          });
        }
        if (state.workshopRunning) {
          sections.push({ title: "Workshop", rows: [{ label: "Status", value: "Running…" }] });
        } else if (state.workshopError) {
          sections.push({ title: "Workshop", rows: [{ label: "Error", value: state.workshopError }] });
        } else if (state.workshopResult) {
          sections.push({
            title: "Workshop · " + state.workshopResult.command,
            rows: state.workshopResult.rows.map(function (row) {
              return { label: row[0], value: row[1] };
            }),
          });
        }
        appendSections(body, sections);
      } else if (state.paneTab === "layers") {
        body.appendChild(
          el("p", { className: "sw-pane-empty" }, [
            "Render-layer visibility toggles are not wired to the sidecar in this build. " +
              UNWIRED_REASON,
          ])
        );
      } else if (state.paneTab === "history") {
        body.appendChild(
          el("p", { className: "sw-pane-empty" }, [
            "This build has no per-project Git repository read path yet, so recent revisions " +
              "cannot be shown. " +
              UNWIRED_REASON,
          ])
        );
      }
      paneEl.appendChild(body);
    }

    function appendSections(body, sections) {
      sections.forEach(function (section) {
        var sectionEl = el("div", {});
        sectionEl.appendChild(el("div", { className: "sw-pane-section-title" }, [section.title]));
        var rows = el("div", { className: "sw-pane-rows" });
        section.rows.forEach(function (row) {
          rows.appendChild(
            el("div", { className: "sw-pane-row" }, [
              el("span", { className: "sw-pane-row-label" }, [row.label]),
              el("span", { className: "sw-pane-row-value sw-mono" }, [row.value]),
            ])
          );
        });
        sectionEl.appendChild(rows);
        body.appendChild(sectionEl);
      });
    }

    function renderStatusBar() {
      statusBar.innerHTML = "";
      var statusSpan = el("span", { id: "viewport-status", role: "status" }, [""]);
      statusBar.appendChild(el("span", {}, [el("span", { className: "sw-status-dot" }), statusSpan]));
      statusBar.appendChild(el("span", { className: "sw-status-fill" }));
      statusBar.appendChild(
        el("span", { className: "sw-mono" }, [state.navSelected ? "minecraft:" + state.navSelected : "no dimension selected"])
      );
    }

    function render() {
      root.setAttribute("data-theme", state.theme);
      root.setAttribute("data-density", state.density);
      ribbonRow.querySelectorAll(".sw-ribbon-tab").forEach(function (b) {
        b.setAttribute("aria-selected", b.getAttribute("data-tab-key") === state.ribbonTab ? "true" : "false");
      });
      ribbonSearchInput.value = state.ribbonSearch;
      navigatorEl.hidden = !state.navOpen;
      renderRibbonGroups();
      renderBreadcrumb();
      renderNavigator();
      renderPane();
      renderStatusBar();
    }

    root.appendChild(ribbonRow);
    root.appendChild(ribbonGroupsRow);
    root.appendChild(breadcrumbRow);
    root.appendChild(bodyRow);

    render();

    return {
      render: render,
      state: state,
      reloadDimensions: loadDimensionsForPath,
    };
  }

  function boot() {
    var root = document.getElementById("studio-workspace");
    if (!root) return;
    // Guard against mounting twice: a page that both waits for
    // DOMContentLoaded and re-dispatches it (as this project's own jsdom
    // test harnesses do, and as jsdom itself also does once its own parse
    // finishes) would otherwise rebuild the whole workspace from scratch a
    // moment after the first mount, silently discarding any state (an
    // opened world's dimensions, a selected tab) set in between.
    if (root.getAttribute("data-studio-workspace-mounted") === "1") return;
    root.setAttribute("data-studio-workspace-mounted", "1");
    window.__AmuletStudioWorkspace = mount(root);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
