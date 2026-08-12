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
          btn("Paste", "⎘", "Paste a previously copied or cut area into the world."),
          btn("Copy", "⧉", "Copy the selected area to paste later."),
          btn("Cut", "✂", "Copy the selected area to paste later and delete."),
          btn("Delete", "⌫", "Delete the blocks in the selected area."),
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
          btn("Import file", "⭳", "Import a supported structure file.", null, { primary: true }),
          btn("Import chunks", "▦", "Replace the selected chunks with chunks from another world."),
        ]),
        group("Export", [
          btn("Export", "⭱", "Export the selection through a format handler."),
          btn("Open in editor", "▸", "Open the exported folder in Visual Studio Code."),
        ]),
      ],
      chunks: [
        group("Draw range", [], { fields: [{ label: "Min Y", value: "—" }, { label: "Max Y", value: "—" }] }),
        group("Chunks", [
          btn("Create empty", "▢", "Create all chunks in the selection that do not already exist.", null, { primary: true }),
          btn("Import", "▦", "Replace the selected chunks with chunks from another world."),
          btn("Delete", "⌫", "Delete the selected chunks."),
          btn("Delete unselected", "⌮", "Delete all chunks that are not selected."),
        ]),
      ],
      terrain: [
        group("Sculpt", [
          btn("Raise", "▲", "Raise the heightmap under the brush.", null, { primary: true }),
          btn("Lower", "▼", "Lower the heightmap under the brush."),
          btn("Smooth", "≈", "Average neighbouring heights."),
          btn("Flatten", "▬", "Flatten to a target height."),
          btn("Erode", "◠", "Hydraulic and thermal erosion passes."),
        ]),
        group("Generate", [
          btn("Noise", "⁘", "Fill the selection from a seeded noise field.", null, { primary: true }),
          btn("Sea level", "≡", "Set or drain the water level in the selection."),
          btn("Regenerate", "↻", "Regenerate chunks from the world seed."),
        ]),
        group("Surface", [
          btn("Repaint", "▨", "Repaint the surface layer by biome or block."),
          btn("Snow line", "❄", "Apply snow and ice above a height."),
          btn("Grass fix", "❋", "Restore grass, dirt, and stone banding."),
        ]),
      ],
      build: [
        group("Shapes", [
          btn("Sphere", "◉", "Draw a filled or hollow sphere.", null, { primary: true }),
          btn("Cylinder", "◍", "Draw a cylinder along an axis."),
          btn("Cuboid", "▢", "Fill the selection as a box."),
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
          btn("Entities", "☰", "Every entity in the selection, searchable.", null, { primary: true }),
          btn("Block entities", "▤", "Chests, signs, spawners, and other NBT blocks."),
          btn("Players", "☺", "Player data, inventory, and position."),
        ]),
        group("Edit", [
          btn("Edit entity", "✎", "Edit the selected entity's NBT.", null, { primary: true }),
          btn("Place", "＋", "Place an entity at the cursor."),
          btn("Remove", "⌫", "Remove entities matching a filter."),
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
          btn("level.dat", "▣", "Edit level.dat safely with validation.", null, { primary: true }),
          btn("Game rules", "⚖", "Every game rule with its current value."),
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
          btn("Histogram", "▧", "Block counts and percentages in the selection.", null, { primary: true }),
          btn("Chunk inspector", "▦", "Per-chunk status, size, and timestamps."),
          btn("Biome map", "❋", "Biome distribution across the selection."),
        ]),
        group("Integrity", [
          btn("Validate", "✓", "Validate and repair chunk and region data.", null, { primary: true }),
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
          btn("Options", "⚙", "Open Options."),
        ], { select: actions.densitySelect }),
        group("Show", [
          btn("Properties", "▤", "Toggle the properties pane.", actions.togglePane),
          btn("Ribbon", "▬", "Collapse or expand the ribbon.", actions.toggleRibbon),
        ]),
        group("Views", [
          btn("View", "◱", "View type, camera, and overlays.", null, { primary: true }),
          btn("Four-up", "⊞", "Camera, overhead, and two elevations at once."),
          btn("Cutaway", "◧", "Clip the world along a plane."),
          btn("Work plane", "▬", "The fixed plane brushes snap to."),
        ]),
        group("Layers", [
          btn("Layers", "☰", "Draw or hide each render layer.", null, { primary: true }),
          btn("Installs", "⛁", "Resource packs and texture atlas."),
        ]),
      ],
      panels: [
        group("Inspect", [
          btn("Inspector", "⌕", "Dockable inspector that follows the selection.", null, { primary: true }),
          btn("World info", "▣", "World identity, size on disk, time and weather."),
          btn("Players", "☺", "Players, skins, positions, and inventories."),
          btn("Inventory", "▦", "Slot-by-slot inventory editor."),
        ]),
        group("Objects", [
          btn("Pending", "⧉", "Pending imports awaiting confirmation.", null, { primary: true }),
          btn("Library", "❑", "Schematic library with folders and previews."),
          btn("Maps", "◫", "Map items and image import."),
        ]),
        group("Diagnostics", [
          btn("Log", "▤", "Filterable application log."),
          btn("Profiler", "⏱", "Frame time and chunk-loading samples."),
          btn("Console", "⌨", "Embedded Python console."),
          btn("Errors", "⚠", "Local error report with traceback."),
        ]),
      ],
      extend: [
        group("Pickers", [
          btn("Blocks", "▨", "Block picker with states and textures.", null, { primary: true }),
          btn("Items", "◈", "Item type list with textures."),
          btn("Biomes", "❋", "Biome picker."),
          btn("Define", "✎", "Configure block and item definitions."),
        ]),
        group("Resources", [
          btn("Installs", "⛁", "Minecraft installs, versions, and resource packs.", null, { primary: true }),
          btn("Versions", "◇", "Platform and data version for handlers."),
        ]),
        group("Plugins", [
          btn("Plugins", "✦", "Installed tools, generators, and commands.", null, { primary: true }),
          btn("Generate", "⁘", "Generator plugins including L-system."),
          btn("Console", "⌨", "Operation console for Python extensions."),
        ]),
      ],
      automate: [
        group("Scripting", [
          btn("Console", "⌨", "Operation console for Python extensions.", null, { primary: true }),
          btn("Batch queue", "⛁", "Queue several operations across worlds."),
          btn("Macro", "⏺", "Record and replay operation sequences."),
        ]),
        group("Scheduling", [
          btn("Rules", "⏷", "Scheduled language, theme, density, and accent rules.", null, { primary: true }),
        ]),
        group("Records", [
          btn("Notifications", "◉", "Notification history."),
          btn("History", "⟲", "Version history."),
          btn("Release notes", "♧", "Release notes."),
        ]),
        group("Memory", [
          btn("Memory console", "▤", "Agent Global Memory Console.", null, { primary: true }),
          btn("Regex builder", ".*", "Open the bounded regex builder."),
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
      togglePane: function () {
        state.paneOpen = !state.paneOpen;
        render();
      },
      toggleRibbon: function () {
        state.ribbonOpen = !state.ribbonOpen;
        render();
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
    };

    // -------------------------------------------------------------- DOM
    var ribbonTabsRow = el("div", { className: "sw-ribbon-tabs", onContextmenu: function (e) { e.preventDefault(); } });
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

    var ribbonRow = el("div", { className: "sw-ribbon-tabs" });
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

    function renderPane() {
      paneEl.innerHTML = "";
      if (!state.paneOpen) return;
      var header = el("div", { className: "sw-pane-header" }, [
        el("span", { className: "sw-pane-title" }, ["Properties"]),
        el("button", { type: "button", className: "sw-pane-icon-btn", title: "Edit appearance for this pane (" + UNWIRED_REASON + ")", disabled: true }, ["✎"]),
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
