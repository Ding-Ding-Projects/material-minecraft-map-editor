/* Hosts the WebGL2 viewport (viewport-webgl.js) as a real tab in the
 * product's Material 3 shell, with real camera input and real chunk
 * streaming against the open world -- as opposed to viewport-harness.html,
 * which is a fixed-camera, single-chunk proof harness for the render
 * pipeline itself.
 *
 * Degrades honestly: outside Electron (a plain browser tab, the published
 * GitHub Pages site) there is no sidecar to talk to, so this shows the
 * "desktop only" empty state and does nothing else. Nothing here throws or
 * leaves the tab half-built when the bridge is missing.
 *
 * Streaming design: on an interval, and whenever the camera has moved far
 * enough, compute the set of chunk (cx, cz) coordinates within
 * STREAM_RADIUS of the camera's current chunk. Every chunk in that set that
 * is not yet loaded goes into ONE "viewport.chunk_mesh_batch" call rather
 * than one "viewport.chunk_mesh" call per chunk -- amulet_map_editor/api/
 * sidecar/benchmark_mesh.py measured the per-file write+read round trip at
 * ~11-14ms/chunk versus ~2ms/chunk once every chunk in a batch shares one
 * combined file, a >5x difference that has nothing to do with meshing cost
 * and everything to do with how many times this loop pays for a temp file
 * and an IPC round trip. The batch call itself follows the same
 * "background thread + poll" pattern world.open/viewport.prepare already
 * use (see mesh_methods.py's _viewport_chunk_mesh_batch): it returns
 * {batch_id, status:"pending"} the instant it is dispatched, so a big batch
 * meshing for hundreds of milliseconds never blocks an unrelated
 * preferences/edit call sitting behind it in the sidecar's single stdio
 * pipe. Once ready, the combined buffer is read ONCE and sliced per chunk
 * by the byte_offset/byte_length each result entry carries, then the batch
 * is explicitly released so its temp file does not linger. Batches
 * themselves still run one at a time -- a burst of camera movement never
 * fires two overlapping batch requests.
 *
 * The write path: this panel also hosts the plain fill/replace/undo/redo/
 * save controls against the CURRENT selection, calling
 * Site.electronSidecar.fillSelection/replaceInSelection/undoEdit/redoEdit/
 * saveWorld (docs/site/electron-bridge.js). Fill and replace go through the
 * project's real destructive-action confirm gate (docs/site/confirm-gate.js)
 * -- the "confirmed" flag the bridge sends is only ever true after that gate
 * finishes, never a default this file sets on the caller's behalf. Every
 * control says why it is disabled rather than sitting there inert, and an
 * unsaved-changes state is shown, not just tracked.
 */
(function () {
  "use strict";

  // amulet_map_editor/api/sidecar/benchmark_mesh.py measured a radius-4
  // (9x9 = 81 chunk) batch against a dense checkerboard fixture at ~415ms
  // of meshing plus ~155ms of combined-file I/O -- real cost, but the
  // batch-per-tick rewrite below (one background-thread request instead of
  // 81 blocking round trips) is what actually made raising this safe: at
  // radius 2 the OLD per-chunk-file path measured ~294ms just in per-file
  // I/O for 25 chunks, more than the new path's meshing+I/O for 81. Radius
  // 3 (49 chunks, well under the batch endpoint's 128-chunk cap) is the
  // number this measurement actually supports raising the radius to; a
  // wider radius still needs a fresh benchmark run before being raised
  // further, not a guess.
  var STREAM_RADIUS = 3; // chunks around the camera to keep loaded
  var UNLOAD_MARGIN = 1; // extra chunks of slack before a loaded chunk is dropped
  var CHUNK_SIZE = 16;
  var STREAM_INTERVAL_MS = 400;

  function bridge() {
    return window.mmweDesktop && window.mmweDesktop.sidecar;
  }

  function sidecarEditBridge() {
    var site = window.AmuletSite;
    return site && site.electronSidecar;
  }

  function sidecarCall(method, params) {
    var b = bridge();
    if (!b || typeof b.call !== "function") {
      return Promise.resolve({ ok: false, error: { code: "no_bridge" } });
    }
    return b.call(method, params || {});
  }

  function readBinary(path) {
    var b = bridge();
    if (!b || typeof b.readBinary !== "function") {
      return Promise.resolve({ ok: false, error: { code: "no_bridge" } });
    }
    return b.readBinary(path);
  }

  function sleep(ms) {
    return new Promise(function (resolve) {
      setTimeout(resolve, ms);
    });
  }

  function chunkCoordOf(worldX, worldZ) {
    return [Math.floor(worldX / CHUNK_SIZE), Math.floor(worldZ / CHUNK_SIZE)];
  }

  /**
   * The plain edit toolbar: six selection-point number fields, a block ID
   * field for fill, find/replace block ID fields for replace, and the five
   * write-path buttons (fill, replace, undo, redo, save). Built with plain
   * DOM calls -- this file has never depended on site-core.js's `el()`
   * helper, and the controls here are honest form fields, not a redesign.
   *
   * Every disabled control carries its reason as visible text next to it
   * (never just a disabled attribute with no explanation), and the reason
   * is recomputed by the caller on every relevant state change via
   * setDisabled(name, disabled, reason).
   */
  function buildEditControls() {
    function field(idSuffix, labelText) {
      var input = document.createElement("input");
      input.type = "number";
      input.step = "1";
      input.id = "viewport-edit-" + idSuffix;
      input.className = "viewport-edit-coord";
      input.setAttribute("aria-label", labelText);
      var wrap = document.createElement("label");
      wrap.className = "viewport-edit-field";
      wrap.setAttribute("for", input.id);
      var span = document.createElement("span");
      span.textContent = labelText;
      wrap.appendChild(span);
      wrap.appendChild(input);
      return { wrap: wrap, input: input };
    }

    var x1 = field("x1", "Point 1 X");
    var y1 = field("y1", "Point 1 Y");
    var z1 = field("z1", "Point 1 Z");
    var x2 = field("x2", "Point 2 X");
    var y2 = field("y2", "Point 2 Y");
    var z2 = field("z2", "Point 2 Z");

    var pointsRow = document.createElement("div");
    pointsRow.className = "viewport-edit-points";
    [x1, y1, z1, x2, y2, z2].forEach(function (f) {
      pointsRow.appendChild(f.wrap);
    });

    function textField(idSuffix, labelText, placeholder) {
      var input = document.createElement("input");
      input.type = "text";
      input.id = "viewport-edit-" + idSuffix;
      input.placeholder = placeholder || "";
      input.setAttribute("aria-label", labelText);
      input.autocomplete = "off";
      var wrap = document.createElement("label");
      wrap.className = "viewport-edit-field";
      wrap.setAttribute("for", input.id);
      var span = document.createElement("span");
      span.textContent = labelText;
      wrap.appendChild(span);
      wrap.appendChild(input);
      return { wrap: wrap, input: input };
    }

    var blockField = textField("fill-block", "Block ID to fill with", "minecraft:stone");
    var findField = textField("find-block", "Block ID to find", "minecraft:dirt");
    var replaceField = textField("replace-block", "Block ID to replace it with", "minecraft:grass_block");

    // entities.place/entities.remove (amulet_map_editor/api/sidecar/entity_methods.py)
    // are real, tested, and were unreachable from the ribbon for want of a
    // type/filter field -- this is that field. One "namespace:base_name"
    // text box serves both commands: Place requires both halves (the
    // sidecar rejects an empty namespace or base_name outright, so a typo
    // like "cow" alone is reported as an error rather than silently
    // resolved to something else); Remove accepts a namespace-only or
    // base_name-only filter, so a plain "cow" with no colon is read as a
    // base_name-only filter there. Placement position reuses selection
    // point 1 -- the same "reuse the real six-field selection" pattern the
    // Build tab's Cuboid command already uses for Fill.
    var entityTypeField = textField("entity-type", "Entity type (namespace:base_name)", "minecraft:cow");

    // terrain.sea_level's "drain" mode (amulet_map_editor/api/sidecar/
    // terrain_methods.py) is real in the sidecar and had no control at all --
    // this build only ever sent "raise". A real value or an explicit choice,
    // never a hidden default: "raise" stays the select's own default so
    // existing behaviour does not silently change underfoot.
    var seaLevelModeSelect = document.createElement("select");
    seaLevelModeSelect.id = "viewport-edit-sea-level-mode";
    seaLevelModeSelect.setAttribute("aria-label", "Sea level mode");
    ["raise", "drain"].forEach(function (value) {
      var option = document.createElement("option");
      option.value = value;
      option.textContent = value === "raise" ? "Raise (air to water)" : "Drain (water to air)";
      seaLevelModeSelect.appendChild(option);
    });
    var seaLevelModeWrap = document.createElement("label");
    seaLevelModeWrap.className = "viewport-edit-field";
    seaLevelModeWrap.setAttribute("for", seaLevelModeSelect.id);
    var seaLevelModeSpan = document.createElement("span");
    seaLevelModeSpan.textContent = "Sea level mode";
    seaLevelModeWrap.appendChild(seaLevelModeSpan);
    seaLevelModeWrap.appendChild(seaLevelModeSelect);

    // data.level_write/data.game_rules_write (same module) are real and were
    // unreachable for want of editable fields. These are the two most
    // dangerous controls on this panel: a bad write can make level.dat --
    // the world's own metadata -- unopenable. Every field here is opt-in
    // (blank means "leave this field alone"; nothing is defaulted or
    // guessed), and the caller in studio-workspace.js routes every write
    // through the project's destructive-action confirm gate before it ever
    // reaches the bridge.
    var levelNameField = textField("level-name", "level.dat: Level name", "leave blank to keep unchanged");
    var difficultyField = textField("level-difficulty", "level.dat: Difficulty (0-3)", "leave blank to keep unchanged");
    difficultyField.input.type = "number";
    difficultyField.input.min = "0";
    difficultyField.input.max = "3";
    difficultyField.input.step = "1";

    function triStateField(idSuffix, labelText) {
      var select = document.createElement("select");
      select.id = "viewport-edit-" + idSuffix;
      select.setAttribute("aria-label", labelText);
      [
        { value: "", label: "Leave unchanged" },
        { value: "true", label: "True" },
        { value: "false", label: "False" },
      ].forEach(function (opt) {
        var option = document.createElement("option");
        option.value = opt.value;
        option.textContent = opt.label;
        select.appendChild(option);
      });
      var wrap = document.createElement("label");
      wrap.className = "viewport-edit-field";
      wrap.setAttribute("for", select.id);
      var span = document.createElement("span");
      span.textContent = labelText;
      wrap.appendChild(span);
      wrap.appendChild(select);
      return { wrap: wrap, select: select };
    }

    var hardcoreField = triStateField("level-hardcore", "level.dat: Hardcore");
    var rainingField = triStateField("level-raining", "level.dat: Raining");
    var thunderingField = triStateField("level-thundering", "level.dat: Thundering");

    var gameRuleNameField = textField("game-rule-name", "Game rule name", "doDaylightCycle");
    var gameRuleValueField = textField("game-rule-value", "Game rule value", "true / false / a number as text");

    function actionButton(text) {
      var button = document.createElement("button");
      button.type = "button";
      button.className = "button button-tonal";
      button.textContent = text;
      return button;
    }

    var fillButton = actionButton("Fill selection");
    var fillReason = document.createElement("p");
    fillReason.className = "viewport-edit-reason";

    var replaceButton = actionButton("Replace blocks");
    var replaceReason = document.createElement("p");
    replaceReason.className = "viewport-edit-reason";

    var undoButton = actionButton("Undo");
    var undoReason = document.createElement("p");
    undoReason.className = "viewport-edit-reason";

    var redoButton = actionButton("Redo");
    var redoReason = document.createElement("p");
    redoReason.className = "viewport-edit-reason";

    var saveButton = actionButton("Save world");
    var saveReason = document.createElement("p");
    saveReason.className = "viewport-edit-reason";

    var unsavedNote = document.createElement("p");
    unsavedNote.className = "viewport-edit-unsaved tab-note";
    unsavedNote.setAttribute("role", "status");

    var fillGroup = document.createElement("div");
    fillGroup.className = "viewport-edit-group";
    fillGroup.appendChild(blockField.wrap);
    fillGroup.appendChild(fillButton);
    fillGroup.appendChild(fillReason);

    var replaceGroup = document.createElement("div");
    replaceGroup.className = "viewport-edit-group";
    replaceGroup.appendChild(findField.wrap);
    replaceGroup.appendChild(replaceField.wrap);
    replaceGroup.appendChild(replaceButton);
    replaceGroup.appendChild(replaceReason);

    var historyGroup = document.createElement("div");
    historyGroup.className = "viewport-edit-group";
    [undoButton, undoReason, redoButton, redoReason, saveButton, saveReason].forEach(function (n) {
      historyGroup.appendChild(n);
    });

    var entityGroup = document.createElement("div");
    entityGroup.className = "viewport-edit-group";
    entityGroup.appendChild(entityTypeField.wrap);

    var terrainGroup = document.createElement("div");
    terrainGroup.className = "viewport-edit-group";
    terrainGroup.appendChild(seaLevelModeWrap);

    var levelDataNote = document.createElement("p");
    levelDataNote.className = "viewport-edit-reason";
    levelDataNote.textContent =
      "These edit the world's own level.dat metadata. A bad write can make the world unopenable -- every field below defaults to \"leave unchanged\" and nothing here is written until Write level.dat is confirmed.";

    var levelDataGroup = document.createElement("div");
    levelDataGroup.className = "viewport-edit-group";
    levelDataGroup.appendChild(levelDataNote);
    levelDataGroup.appendChild(levelNameField.wrap);
    levelDataGroup.appendChild(difficultyField.wrap);
    levelDataGroup.appendChild(hardcoreField.wrap);
    levelDataGroup.appendChild(rainingField.wrap);
    levelDataGroup.appendChild(thunderingField.wrap);

    var gameRulesGroup = document.createElement("div");
    gameRulesGroup.className = "viewport-edit-group";
    gameRulesGroup.appendChild(gameRuleNameField.wrap);
    gameRulesGroup.appendChild(gameRuleValueField.wrap);

    var root = document.createElement("div");
    root.className = "viewport-edit-panel";
    root.appendChild(pointsRow);
    root.appendChild(fillGroup);
    root.appendChild(replaceGroup);
    root.appendChild(historyGroup);
    root.appendChild(entityGroup);
    root.appendChild(terrainGroup);
    root.appendChild(levelDataGroup);
    root.appendChild(gameRulesGroup);
    root.appendChild(unsavedNote);

    var buttons = { fill: fillButton, replace: replaceButton, undo: undoButton, redo: redoButton, save: saveButton };
    var reasons = { fill: fillReason, replace: replaceReason, undo: undoReason, redo: redoReason, save: saveReason };

    function readPoints() {
      var raw = [x1, y1, z1, x2, y2, z2].map(function (f) {
        return f.input.value === "" ? NaN : Number(f.input.value);
      });
      if (raw.some(function (n) { return !isFinite(n); })) return null;
      return { point1: [raw[0], raw[1], raw[2]], point2: [raw[3], raw[4], raw[5]] };
    }

    return {
      root: root,
      fillButton: fillButton,
      replaceButton: replaceButton,
      readPoints: readPoints,
      blockValue: function () { return blockField.input.value.trim(); },
      findBlockValue: function () { return findField.input.value.trim(); },
      replaceBlockValue: function () { return replaceField.input.value.trim(); },
      entityTypeValue: function () { return entityTypeField.input.value.trim(); },
      seaLevelModeValue: function () { return seaLevelModeSelect.value; },
      levelNameValue: function () { return levelNameField.input.value.trim(); },
      // Returns the raw trimmed text so the caller can honestly report an
      // unparseable value as an error rather than this field silently
      // coercing "abc" to NaN and then to some substituted number.
      difficultyRawValue: function () { return difficultyField.input.value.trim(); },
      hardcoreValue: function () { return hardcoreField.select.value; },
      rainingValue: function () { return rainingField.select.value; },
      thunderingValue: function () { return thunderingField.select.value; },
      gameRuleNameValue: function () { return gameRuleNameField.input.value.trim(); },
      gameRuleValueValue: function () { return gameRuleValueField.input.value.trim(); },
      setDisabled: function (name, disabled, reason) {
        var button = buttons[name];
        var reasonEl = reasons[name];
        if (!button || !reasonEl) return;
        button.disabled = Boolean(disabled);
        reasonEl.textContent = disabled ? reason || "" : "";
      },
      setUnsaved: function (unsaved) {
        unsavedNote.textContent = unsaved
          ? "Unsaved changes -- Save world to write them to disk."
          : "No unsaved changes.";
      },
      onFill: function (fn) { fillButton.addEventListener("click", fn); },
      onReplace: function (fn) { replaceButton.addEventListener("click", fn); },
      onUndo: function (fn) { undoButton.addEventListener("click", fn); },
      onRedo: function (fn) { redoButton.addEventListener("click", fn); },
      onSave: function (fn) { saveButton.addEventListener("click", fn); },
      onPointsChanged: function (fn) {
        [x1, y1, z1, x2, y2, z2].forEach(function (f) {
          f.input.addEventListener("input", fn);
        });
      },
      // Write a selection into the six number fields -- used by click-to-pick
      // and by handle dragging, so the pointer and the typed fields are two
      // ways to set ONE value rather than two values that can disagree. A
      // real "input" event is dispatched (not just the property set) so
      // onPointsChanged's listener -- which is what keeps the drawn overlay
      // in step -- actually fires.
      setPoints: function (point1, point2) {
        var fields = [x1, y1, z1, x2, y2, z2];
        var values = point1 && point2 ? point1.concat(point2) : [];
        fields.forEach(function (f, index) {
          f.input.value = index < values.length ? String(Math.round(values[index])) : "";
        });
        var event = typeof Event === "function" ? new Event("input", { bubbles: true }) : null;
        if (event) x1.input.dispatchEvent(event);
      },
    };
  }

  function init() {
    var host = document.getElementById("viewport-host");
    var canvas = document.getElementById("viewport-canvas");
    var emptyEl = document.getElementById("viewport-empty");
    var statusEl = document.getElementById("viewport-status");
    var openRow = document.getElementById("viewport-open-row");
    var openButton = document.getElementById("viewport-open-button");
    var pathInput = document.getElementById("viewport-world-path");
    if (!host || !canvas || !emptyEl || !statusEl) return;

    function setStatus(text) {
      statusEl.textContent = text;
    }

    var b = bridge();
    if (!b || typeof b.call !== "function") {
      // Plain browser / GitHub Pages: no sidecar exists to stream from.
      // Say so honestly rather than showing a dead grey canvas.
      canvas.hidden = true;
      if (openRow) openRow.hidden = true;
      emptyEl.hidden = false;
      emptyEl.textContent =
        "Desktop only: this tab renders live chunk geometry through the desktop app's sidecar, which is not available in a browser.";
      return;
    }

    // Inside Electron. Canvas stays hidden until a world is actually open and
    // streaming, so a viewer never sees a black/empty WebGL surface and
    // mistakes it for a bug.
    canvas.hidden = true;
    emptyEl.hidden = false;
    emptyEl.textContent = "No world open yet. Enter a world folder path above and choose Open world.";

    var viewport = null;
    var detachControls = null;
    var worldId = null;
    var dimension = null;
    var streaming = false;
    var streamBusy = false;
    var streamTimer = null;
    var rafHandle = null;

    // ---------------------------------------------------------- edit path
    // The write path against the currently open world: fill and replace
    // (each real bridge.call() sites gated behind the project's
    // destructive-action confirm, per docs/site/confirm-gate.js), undo,
    // redo and save. Plain controls against the CURRENT selection -- this
    // is a working surface, not a redesign of the viewport tab.
    var edit = buildEditControls();
    if (edit && edit.root) {
      host.parentNode.insertBefore(edit.root, host.nextSibling);
    }
    var editState = { canUndo: false, canRedo: false, unsaved: false };

    function selectionPoints() {
      return edit ? edit.readPoints() : null;
    }

    function refreshEditControls() {
      if (!edit) return;
      var worldOpen = worldId !== null;
      var hasSelection = Boolean(selectionPoints());
      var bridgeReady = Boolean(sidecarEditBridge());
      edit.setDisabled("fill", !worldOpen || !hasSelection || !bridgeReady, !worldOpen
        ? "No world is open yet."
        : !hasSelection
          ? "Enter both selection points first."
          : !bridgeReady
            ? "The sidecar bridge is not available."
            : "");
      edit.setDisabled("replace", !worldOpen || !hasSelection || !bridgeReady, !worldOpen
        ? "No world is open yet."
        : !hasSelection
          ? "Enter both selection points first."
          : !bridgeReady
            ? "The sidecar bridge is not available."
            : "");
      edit.setDisabled("undo", !worldOpen || !editState.canUndo || !bridgeReady, !worldOpen
        ? "No world is open yet."
        : !editState.canUndo
          ? "Nothing to undo yet."
          : !bridgeReady
            ? "The sidecar bridge is not available."
            : "");
      edit.setDisabled("redo", !worldOpen || !editState.canRedo || !bridgeReady, !worldOpen
        ? "No world is open yet."
        : !editState.canRedo
          ? "Nothing to redo yet."
          : !bridgeReady
            ? "The sidecar bridge is not available."
            : "");
      edit.setDisabled("save", !worldOpen || !editState.unsaved || !bridgeReady, !worldOpen
        ? "No world is open yet."
        : !editState.unsaved
          ? "No unsaved changes."
          : !bridgeReady
            ? "The sidecar bridge is not available."
            : "");
      edit.setUnsaved(editState.unsaved);
      var points = selectionPoints();
      setSelection(points ? points.point1 : null, points ? points.point2 : null);
    }

    function runFill() {
      var points = selectionPoints();
      if (!points || worldId === null) return;
      var block = edit.blockValue();
      if (!block) {
        setStatus("Enter a block ID to fill with first.");
        return;
      }
      var site = window.AmuletSite;
      var doFill = function () {
        var eb = sidecarEditBridge();
        if (!eb || typeof eb.fillSelection !== "function") {
          setStatus("world.fill is not available yet.");
          return;
        }
        setStatus("Filling selection...");
        eb.fillSelection(worldId, dimension, points.point1, points.point2, block, true)
          .then(function () {
            editState.canUndo = true;
            editState.canRedo = false;
            editState.unsaved = true;
            refreshEditControls();
            setStatus("Selection filled with " + block + ".");
          })
          .catch(function (err) {
            setStatus("world.fill failed: " + String(err));
          });
      };
      if (site && typeof site.confirmDestructive === "function") {
        site.confirmDestructive({
          title: "Fill selection",
          detail:
            "This overwrites every block from " +
            points.point1.join(",") +
            " to " +
            points.point2.join(",") +
            " with " +
            block +
            ".",
          confirm: "Fill",
          anchor: edit.fillButton,
          onConfirm: doFill,
        });
      } else {
        doFill();
      }
    }

    function runReplace() {
      var points = selectionPoints();
      if (!points || worldId === null) return;
      var findBlock = edit.findBlockValue();
      var replaceBlock = edit.replaceBlockValue();
      if (!findBlock || !replaceBlock) {
        setStatus("Enter both the block to find and the block to replace it with.");
        return;
      }
      var site = window.AmuletSite;
      var doReplace = function () {
        var eb = sidecarEditBridge();
        if (!eb || typeof eb.replaceInSelection !== "function") {
          setStatus("world.replace is not available yet.");
          return;
        }
        setStatus("Replacing blocks...");
        eb.replaceInSelection(worldId, dimension, points.point1, points.point2, findBlock, replaceBlock, true)
          .then(function () {
            editState.canUndo = true;
            editState.canRedo = false;
            editState.unsaved = true;
            refreshEditControls();
            setStatus("Replaced " + findBlock + " with " + replaceBlock + " in the selection.");
          })
          .catch(function (err) {
            setStatus("world.replace failed: " + String(err));
          });
      };
      if (site && typeof site.confirmDestructive === "function") {
        site.confirmDestructive({
          title: "Replace blocks",
          detail:
            "This replaces every " + findBlock + " with " + replaceBlock + " from " +
            points.point1.join(",") + " to " + points.point2.join(",") + ".",
          confirm: "Replace",
          anchor: edit.replaceButton,
          onConfirm: doReplace,
        });
      } else {
        doReplace();
      }
    }

    function runUndo() {
      if (worldId === null) return;
      var eb = sidecarEditBridge();
      if (!eb || typeof eb.undoEdit !== "function") {
        setStatus("world.undo is not available yet.");
        return;
      }
      setStatus("Undoing last edit...");
      eb.undoEdit(worldId)
        .then(function () {
          editState.canRedo = true;
          editState.unsaved = true;
          refreshEditControls();
          setStatus("Undid the last edit.");
        })
        .catch(function (err) {
          setStatus("world.undo failed: " + String(err));
        });
    }

    function runRedo() {
      if (worldId === null) return;
      var eb = sidecarEditBridge();
      if (!eb || typeof eb.redoEdit !== "function") {
        setStatus("world.redo is not available yet.");
        return;
      }
      setStatus("Redoing edit...");
      eb.redoEdit(worldId)
        .then(function () {
          editState.canUndo = true;
          editState.unsaved = true;
          refreshEditControls();
          setStatus("Redid the edit.");
        })
        .catch(function (err) {
          setStatus("world.redo failed: " + String(err));
        });
    }

    function runSave() {
      if (worldId === null) return;
      var eb = sidecarEditBridge();
      if (!eb || typeof eb.saveWorld !== "function") {
        setStatus("world.save is not available yet.");
        return;
      }
      setStatus("Saving world...");
      eb.saveWorld(worldId, true)
        .then(function () {
          editState.unsaved = false;
          refreshEditControls();
          setStatus("World saved.");
        })
        .catch(function (err) {
          setStatus("world.save failed: " + String(err));
        });
    }

    // ------------------------------------------------------ selection / structures / chunks
    // Selection.copy/cut/paste/delete and structure/chunk import/export
    // (amulet_map_editor/api/sidecar/selection_methods.py, exposed via
    // docs/site/electron-bridge.js). These reuse the same six selection-point
    // fields runFill/runReplace already read, rather than a second copy of
    // "what is selected". Paste/import use point 1 as the destination
    // location, and destination/source paths are gathered with a plain
    // prompt -- there is no dedicated path field on this panel yet, so a
    // real (if minimal) prompt is honest where a silently-ignored click
    // would not be.
    function runCopySelection() {
      var points = selectionPoints();
      if (!points || worldId === null) return;
      var eb = sidecarEditBridge();
      if (!eb || typeof eb.copySelection !== "function") {
        setStatus("selection.copy is not available yet.");
        return;
      }
      setStatus("Copying selection...");
      eb.copySelection(worldId, dimension, points.point1, points.point2)
        .then(function (result) {
          setStatus(result.blocks_copied + " block(s) copied to the clipboard.");
        })
        .catch(function (err) {
          setStatus("selection.copy failed: " + String(err));
        });
    }

    function runCutSelection() {
      var points = selectionPoints();
      if (!points || worldId === null) return;
      var site = window.AmuletSite;
      var doCut = function () {
        var eb = sidecarEditBridge();
        if (!eb || typeof eb.cutSelection !== "function") {
          setStatus("selection.cut is not available yet.");
          return;
        }
        setStatus("Cutting selection...");
        eb.cutSelection(worldId, dimension, points.point1, points.point2, true)
          .then(function (result) {
            editState.canUndo = true;
            editState.canRedo = false;
            editState.unsaved = true;
            refreshEditControls();
            setStatus(result.blocks_changed + " block(s) cut to the clipboard.");
          })
          .catch(function (err) {
            setStatus("selection.cut failed: " + String(err));
          });
      };
      if (site && typeof site.confirmDestructive === "function") {
        site.confirmDestructive({
          title: "Cut selection",
          detail:
            "This removes every block from " + points.point1.join(",") + " to " +
            points.point2.join(",") + " after copying it to the clipboard.",
          confirm: "Cut",
          onConfirm: doCut,
        });
      } else {
        doCut();
      }
    }

    function runPasteSelection() {
      var points = selectionPoints();
      if (!points || worldId === null) return;
      var site = window.AmuletSite;
      var doPaste = function () {
        var eb = sidecarEditBridge();
        if (!eb || typeof eb.pasteSelection !== "function") {
          setStatus("selection.paste is not available yet.");
          return;
        }
        setStatus("Pasting clipboard...");
        eb.pasteSelection(worldId, dimension, points.point1, true)
          .then(function (result) {
            editState.canUndo = true;
            editState.canRedo = false;
            editState.unsaved = true;
            refreshEditControls();
            setStatus(result.blocks_pasted + " block(s) pasted at " + points.point1.join(",") + ".");
          })
          .catch(function (err) {
            setStatus("selection.paste failed: " + String(err));
          });
      };
      if (site && typeof site.confirmDestructive === "function") {
        site.confirmDestructive({
          title: "Paste clipboard",
          detail: "This writes the copied/cut structure into the world at " + points.point1.join(",") + ".",
          confirm: "Paste",
          onConfirm: doPaste,
        });
      } else {
        doPaste();
      }
    }

    function runDeleteSelection() {
      var points = selectionPoints();
      if (!points || worldId === null) return;
      var site = window.AmuletSite;
      var doDelete = function () {
        var eb = sidecarEditBridge();
        if (!eb || typeof eb.deleteSelection !== "function") {
          setStatus("selection.delete is not available yet.");
          return;
        }
        setStatus("Deleting selection...");
        eb.deleteSelection(worldId, dimension, points.point1, points.point2, true)
          .then(function (result) {
            editState.canUndo = true;
            editState.canRedo = false;
            editState.unsaved = true;
            refreshEditControls();
            setStatus(result.blocks_changed + " block(s) deleted.");
          })
          .catch(function (err) {
            setStatus("selection.delete failed: " + String(err));
          });
      };
      if (site && typeof site.confirmDestructive === "function") {
        site.confirmDestructive({
          title: "Delete selection",
          detail:
            "This removes every block from " + points.point1.join(",") + " to " + points.point2.join(",") + ".",
          confirm: "Delete",
          onConfirm: doDelete,
        });
      } else {
        doDelete();
      }
    }

    function runExportStructure() {
      var points = selectionPoints();
      if (!points || worldId === null) return;
      var eb = sidecarEditBridge();
      if (!eb || typeof eb.exportStructure !== "function") {
        setStatus("structure.export is not available yet.");
        return;
      }
      var destination = window.prompt("Save the selection as a .construction file at:");
      if (!destination) return;
      setStatus("Exporting structure...");
      eb.exportStructure(worldId, dimension, points.point1, points.point2, destination, false)
        .then(function (result) {
          setStatus(result.chunks_exported + " chunk(s) exported to " + result.destination_path + ".");
        })
        .catch(function (err) {
          setStatus("structure.export failed: " + String(err));
        });
    }

    function runImportStructure() {
      var points = selectionPoints();
      if (!points || worldId === null) return;
      var source = window.prompt("Import a .construction/.mcstructure/.schematic/.schem file from:");
      if (!source) return;
      var site = window.AmuletSite;
      var doImport = function () {
        var eb = sidecarEditBridge();
        if (!eb || typeof eb.importStructure !== "function") {
          setStatus("structure.import is not available yet.");
          return;
        }
        setStatus("Importing structure...");
        eb.importStructure(worldId, dimension, source, points.point1, true)
          .then(function () {
            editState.canUndo = true;
            editState.canRedo = false;
            editState.unsaved = true;
            refreshEditControls();
            setStatus("Imported " + source + " at " + points.point1.join(",") + ".");
          })
          .catch(function (err) {
            setStatus("structure.import failed: " + String(err));
          });
      };
      if (site && typeof site.confirmDestructive === "function") {
        site.confirmDestructive({
          title: "Import structure",
          detail: "This writes " + source + " into the world at " + points.point1.join(",") + ".",
          confirm: "Import",
          onConfirm: doImport,
        });
      } else {
        doImport();
      }
    }

    function runCreateChunks() {
      var points = selectionPoints();
      if (!points || worldId === null) return;
      var eb = sidecarEditBridge();
      if (!eb || typeof eb.createChunks !== "function") {
        setStatus("chunk.create is not available yet.");
        return;
      }
      setStatus("Creating chunks...");
      eb.createChunks(worldId, dimension, points.point1, points.point2)
        .then(function (result) {
          editState.unsaved = editState.unsaved || result.chunks_created > 0;
          refreshEditControls();
          setStatus(result.chunks_created + " chunk(s) created.");
        })
        .catch(function (err) {
          setStatus("chunk.create failed: " + String(err));
        });
    }

    function runDeleteChunks() {
      var points = selectionPoints();
      if (!points || worldId === null) return;
      var site = window.AmuletSite;
      var doDelete = function () {
        var eb = sidecarEditBridge();
        if (!eb || typeof eb.deleteChunks !== "function") {
          setStatus("chunk.delete is not available yet.");
          return;
        }
        setStatus("Deleting chunks...");
        eb.deleteChunks(worldId, dimension, points.point1, points.point2, true)
          .then(function (result) {
            editState.canUndo = false;
            editState.unsaved = true;
            refreshEditControls();
            setStatus(result.chunks_deleted + " chunk(s) deleted.");
          })
          .catch(function (err) {
            setStatus("chunk.delete failed: " + String(err));
          });
      };
      if (site && typeof site.confirmDestructive === "function") {
        site.confirmDestructive({
          title: "Delete chunks",
          detail: "This permanently deletes every chunk from " + points.point1.join(",") + " to " + points.point2.join(",") + ".",
          confirm: "Delete",
          onConfirm: doDelete,
        });
      } else {
        doDelete();
      }
    }

    function runPruneChunks() {
      var points = selectionPoints();
      if (!points || worldId === null) return;
      var site = window.AmuletSite;
      var doPrune = function () {
        var eb = sidecarEditBridge();
        if (!eb || typeof eb.pruneChunks !== "function") {
          setStatus("chunk.prune is not available yet.");
          return;
        }
        setStatus("Deleting unselected chunks...");
        eb.pruneChunks(worldId, dimension, points.point1, points.point2, true)
          .then(function (result) {
            editState.canUndo = false;
            editState.unsaved = true;
            refreshEditControls();
            setStatus(result.chunks_deleted + " unselected chunk(s) deleted; " + result.chunks_kept + " kept.");
          })
          .catch(function (err) {
            setStatus("chunk.prune failed: " + String(err));
          });
      };
      if (site && typeof site.confirmDestructive === "function") {
        site.confirmDestructive({
          title: "Delete unselected chunks",
          detail: "This permanently deletes every chunk OUTSIDE " + points.point1.join(",") + " to " + points.point2.join(",") + ".",
          confirm: "Delete",
          onConfirm: doPrune,
        });
      } else {
        doPrune();
      }
    }

    if (edit) {
      edit.onFill(runFill);
      edit.onReplace(runReplace);
      edit.onUndo(runUndo);
      edit.onRedo(runRedo);
      edit.onSave(runSave);
      edit.onPointsChanged(refreshEditControls);
      refreshEditControls();
    }

    // -------------------------------------- entities.place / entities.remove
    // entities.place needs a position and an entity type; entities.remove
    // needs a filter. Both were real in the sidecar and disabled on the
    // ribbon purely for want of these fields -- see entityTypeField's
    // comment in buildEditControls() for the exact "namespace:base_name"
    // parsing rule shared by both commands below.
    function parseEntityType(raw) {
      var idx = raw.indexOf(":");
      if (idx === -1) return { namespace: "", baseName: raw };
      return { namespace: raw.slice(0, idx).trim(), baseName: raw.slice(idx + 1).trim() };
    }

    function runPlaceEntity() {
      var points = selectionPoints();
      if (!points || worldId === null) return;
      var raw = edit.entityTypeValue();
      if (!raw) {
        setStatus("Enter an entity type (namespace:base_name) first.");
        return;
      }
      var parsed = parseEntityType(raw);
      if (!parsed.namespace || !parsed.baseName) {
        setStatus('Entity type must be "namespace:base_name" (for example minecraft:cow) to place an entity.');
        return;
      }
      var position = points.point1;
      var site = window.AmuletSite;
      var doPlace = function () {
        var eb = sidecarEditBridge();
        if (!eb || !eb.entities || typeof eb.entities.place !== "function") {
          setStatus("entities.place is not available yet.");
          return;
        }
        setStatus("Placing entity...");
        eb.entities
          .place(worldId, dimension, position, parsed.namespace, parsed.baseName, true)
          .then(function () {
            editState.canUndo = true;
            editState.canRedo = false;
            editState.unsaved = true;
            refreshEditControls();
            setStatus(raw + " placed at " + position.join(",") + ".");
          })
          .catch(function (err) {
            setStatus("entities.place failed: " + String(err));
          });
      };
      if (site && typeof site.confirmDestructive === "function") {
        site.confirmDestructive({
          title: "Place entity",
          detail: "This places " + raw + " at " + position.join(",") + ".",
          confirm: "Place",
          onConfirm: doPlace,
        });
      } else {
        doPlace();
      }
    }

    function runRemoveEntities() {
      var points = selectionPoints();
      if (!points || worldId === null) return;
      var raw = edit.entityTypeValue();
      if (!raw) {
        setStatus("Enter a namespace, a base_name, or namespace:base_name to filter which entities to remove.");
        return;
      }
      var parsed = parseEntityType(raw);
      var namespace = parsed.namespace || undefined;
      var baseName = parsed.baseName || undefined;
      var site = window.AmuletSite;
      var doRemove = function () {
        var eb = sidecarEditBridge();
        if (!eb || !eb.entities || typeof eb.entities.remove !== "function") {
          setStatus("entities.remove is not available yet.");
          return;
        }
        setStatus("Removing matching entities...");
        eb.entities
          .remove(worldId, dimension, points.point1, points.point2, namespace, baseName, true)
          .then(function (result) {
            editState.canUndo = editState.canUndo || result.removed > 0;
            editState.canRedo = false;
            editState.unsaved = editState.unsaved || result.removed > 0;
            refreshEditControls();
            setStatus(String(result.removed) + " entity(ies) removed.");
          })
          .catch(function (err) {
            setStatus("entities.remove failed: " + String(err));
          });
      };
      if (site && typeof site.confirmDestructive === "function") {
        site.confirmDestructive({
          title: "Remove entities",
          detail:
            "This removes every entity matching " + raw + " from " + points.point1.join(",") + " to " + points.point2.join(",") + ".",
          confirm: "Remove",
          onConfirm: doRemove,
        });
      } else {
        doRemove();
      }
    }

    // ------------------------------------- data.level_write / game_rules_write
    // The most dangerous controls on this panel -- see levelDataNote's text
    // in buildEditControls(). Every field is opt-in: a blank field is left
    // out of the write entirely rather than defaulted, and an unparseable
    // difficulty value is reported as an error, never silently coerced or
    // dropped.
    function runWriteLevel() {
      if (worldId === null) return;
      var fields = {};
      var levelName = edit.levelNameValue();
      if (levelName) fields.level_name = levelName;
      var difficultyRaw = edit.difficultyRawValue();
      if (difficultyRaw) {
        var difficulty = Number(difficultyRaw);
        if (!Number.isInteger(difficulty) || difficulty < 0 || difficulty > 3) {
          setStatus("Difficulty must be a whole number from 0 to 3 -- \"" + difficultyRaw + "\" does not resolve to one.");
          return;
        }
        fields.difficulty = difficulty;
      }
      var hardcore = edit.hardcoreValue();
      if (hardcore) fields.hardcore = hardcore === "true";
      var raining = edit.rainingValue();
      if (raining) fields.raining = raining === "true";
      var thundering = edit.thunderingValue();
      if (thundering) fields.thundering = thundering === "true";
      if (!Object.keys(fields).length) {
        setStatus("Set at least one level.dat field before writing -- every field currently reads \"leave unchanged\".");
        return;
      }
      var site = window.AmuletSite;
      var doWrite = function () {
        var eb = sidecarEditBridge();
        if (!eb || !eb.data || typeof eb.data.writeLevel !== "function") {
          setStatus("data.level_write is not available yet.");
          return;
        }
        setStatus("Writing level.dat...");
        eb.data
          .writeLevel(worldId, fields, true)
          .then(function (result) {
            editState.unsaved = true;
            refreshEditControls();
            setStatus("level.dat updated: " + (result.updated || []).join(", ") + ".");
          })
          .catch(function (err) {
            setStatus("data.level_write failed: " + String(err));
          });
      };
      if (site && typeof site.confirmDestructive === "function") {
        site.confirmDestructive({
          title: "Write level.dat",
          detail:
            "This edits the world's own level.dat metadata (" + Object.keys(fields).join(", ") + "). A bad write can make the world unopenable.",
          confirm: "Write",
          onConfirm: doWrite,
        });
      } else {
        doWrite();
      }
    }

    function runWriteGameRules() {
      if (worldId === null) return;
      var name = edit.gameRuleNameValue();
      var value = edit.gameRuleValueValue();
      if (!name || !value) {
        setStatus("Enter both a game rule name and its value first.");
        return;
      }
      var rules = {};
      rules[name] = value;
      var site = window.AmuletSite;
      var doWrite = function () {
        var eb = sidecarEditBridge();
        if (!eb || !eb.data || typeof eb.data.writeGameRules !== "function") {
          setStatus("data.game_rules_write is not available yet.");
          return;
        }
        setStatus("Writing game rule...");
        eb.data
          .writeGameRules(worldId, rules, true)
          .then(function () {
            editState.unsaved = true;
            refreshEditControls();
            setStatus("Game rule " + name + " set to " + value + ".");
          })
          .catch(function (err) {
            setStatus("data.game_rules_write failed: " + String(err));
          });
      };
      if (site && typeof site.confirmDestructive === "function") {
        site.confirmDestructive({
          title: "Write game rule",
          detail: "This edits the world's own level.dat metadata: sets " + name + " = " + value + ".",
          confirm: "Write",
          onConfirm: doWrite,
        });
      } else {
        doWrite();
      }
    }

    // -------------------------------------------------------------- picking
    // Turns pointerdown-only-rotates-the-camera into an editor: Alt+click
    // ray-casts into the world (docs/site/viewport-picking.js's DDA march)
    // and sets a selection point; a second Alt+click completes the box.
    // Once a selection exists, Alt-pressing one of its grab handles
    // (docs/site/viewport-handles.js -- the same face/corner handle
    // geometry and drag constraints as the wx app's
    // amulet_map_editor/api/opengl/mesh/selection/box/handles.py) resizes it
    // instead of picking a new point. Plain drag still only rotates the
    // camera, via the shouldRotate hook passed to attachControls() below --
    // an Alt+drag, or a drag that starts on a handle, must not also spin the
    // view underneath it.
    //
    // Every one of those has a keyboard equivalent (see onEditorKeyDown
    // below): a pointer-only editor is a defect here, not a limitation.
    //
    // Real block data: mesh_methods.py's "viewport.chunk_mesh_batch" now
    // ships a packed occupancy bitset alongside every chunk's mesh (see
    // docs/site/viewport-occupancy.js for the exact bit layout), and
    // requestChunks()/unloadChunk() below keep this store's contents in
    // sync with whatever chunks are actually loaded. solidTest answers from
    // that store in constant time -- no IPC round trip on the picking ray's
    // hot path -- and a chunk that has not streamed in yet honestly answers
    // "not solid" rather than blocking the ray.
    // window.__AmuletViewportPanel.setSolidTest still exists so tests (and a
    // future fixture-driven picking test) can override this wholesale.
    var occupancyApi = window.AmuletViewportOccupancy;
    var occupancyStore = occupancyApi ? occupancyApi.createOccupancyStore() : null;
    var solidTest = occupancyStore
      ? occupancyStore.isSolid
      : function () {
          return false;
        };
    var pendingPoint1 = null; // block coords from a first Alt+click, awaiting a second
    var activeDrag = null; // {drag} while a handle is being dragged
    var activeFaceIndex = 0; // which FACE_HANDLES entry the keyboard nudges

    function ndcFromEvent(event) {
      var rect = canvas.getBoundingClientRect();
      var x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      var y = -(((event.clientY - rect.top) / rect.height) * 2 - 1);
      return [x, y];
    }

    function rayFromEvent(event) {
      var picking = window.AmuletViewportPicking;
      if (!picking || !viewport || !canvas.height) return null;
      var ndc = ndcFromEvent(event);
      var aspect = canvas.width / canvas.height;
      return picking.rayFromCamera(viewport.camera, viewport.fovYRadians, aspect, ndc[0], ndc[1]);
    }

    function pickBlock(event) {
      var picking = window.AmuletViewportPicking;
      var ray = rayFromEvent(event);
      if (!picking || !ray) return null;
      var hit = picking.voxelRaycast(ray.origin, ray.direction, solidTest, 256);
      return hit ? hit.block : null;
    }

    /** The current selection as [min, max] block coordinates (no +1 padding
     * -- this matches SelectionOverlay's own sortedBounds(), which draws the
     * box from point1 to point2 exactly as typed), or null. */
    function currentBounds() {
      var points = selectionPoints();
      if (!points) return null;
      return [
        [
          Math.min(points.point1[0], points.point2[0]),
          Math.min(points.point1[1], points.point2[1]),
          Math.min(points.point1[2], points.point2[2]),
        ],
        [
          Math.max(points.point1[0], points.point2[0]),
          Math.max(points.point1[1], points.point2[1]),
          Math.max(points.point1[2], points.point2[2]),
        ],
      ];
    }

    function applyHandleDrag(ray) {
      var handlesApi = window.AmuletViewportHandles;
      if (!handlesApi || !activeDrag) return;
      var offset = handlesApi.dragBlockOffset(activeDrag.drag, ray.origin, ray.direction);
      if (!offset) return; // the ray says nothing usable this frame; leave the box where it is
      var box = handlesApi.applyDragOffset(activeDrag.drag, offset);
      edit.setPoints(box[0], box[1]);
    }

    function onPickPointerDown(event) {
      if (event.button !== 0 || !event.altKey) return;
      var ray = rayFromEvent(event);
      if (!ray || !viewport) return;

      var handlesApi = window.AmuletViewportHandles;
      var bounds = currentBounds();
      if (bounds && handlesApi) {
        var visible = handlesApi.visibleHandles(bounds[0], bounds[1], viewport.camera.position);
        var handle = handlesApi.hitHandle(bounds[0], bounds[1], ray.origin, ray.direction, visible);
        if (handle) {
          var drag = handlesApi.beginDrag(handle, bounds[0], bounds[1], ray.origin, ray.direction);
          if (drag) {
            activeDrag = { drag: drag };
            canvas.setPointerCapture && canvas.setPointerCapture(event.pointerId);
            setStatus("Dragging " + handle.name + "...");
            event.preventDefault();
            return;
          }
        }
      }

      var block = pickBlock(event);
      if (!block) {
        setStatus("Alt+click did not hit anything within range.");
        return;
      }
      if (!pendingPoint1) {
        pendingPoint1 = block;
        edit.setPoints(block, block);
        setStatus("Point 1 set at " + block.join(",") + ". Alt+click again for point 2.");
      } else {
        edit.setPoints(pendingPoint1, block);
        setStatus("Selection set from " + pendingPoint1.join(",") + " to " + block.join(",") + ".");
        pendingPoint1 = null;
      }
      event.preventDefault();
    }

    function onPickPointerMove(event) {
      if (activeDrag) {
        var dragRay = rayFromEvent(event);
        if (dragRay) applyHandleDrag(dragRay);
        return;
      }
      // Hovering with a pending first point previews the box as it is
      // dragged, rather than only showing it on the second click.
      if (!pendingPoint1 || !event.altKey) return;
      var block = pickBlock(event);
      if (block) edit.setPoints(pendingPoint1, block);
    }

    function onPickPointerUp(event) {
      if (!activeDrag) return;
      activeDrag = null;
      canvas.releasePointerCapture && canvas.releasePointerCapture(event.pointerId);
      setStatus("Selection updated.");
    }

    function nudgeActiveFace(delta) {
      var handlesApi = window.AmuletViewportHandles;
      var bounds = currentBounds();
      if (!handlesApi || !bounds) {
        setStatus("Enter both selection points first to nudge a face.");
        return;
      }
      var handle = handlesApi.FACE_HANDLES[activeFaceIndex];
      var min = bounds[0].slice();
      var max = bounds[1].slice();
      var axis = handle.axis;
      if (handle.offset[axis] > 0) max[axis] += delta;
      else min[axis] += delta;
      edit.setPoints(min, max);
      setStatus("Nudged " + handle.name + " by " + delta + " block(s).");
    }

    /** Step the far corner of the selection diagonally -- the keyboard
     * equivalent of dragging a corner handle, which moves two axes at once. */
    function stepFarCorner(deltaX, deltaZ) {
      var bounds = currentBounds();
      if (!bounds) {
        setStatus("Enter both selection points first to step a corner.");
        return;
      }
      var max = bounds[1].slice();
      max[0] += deltaX;
      max[2] += deltaZ;
      edit.setPoints(bounds[0], max);
      setStatus("Stepped the far corner.");
    }

    function selectChunkUnderCamera() {
      if (!viewport) return;
      var pos = viewport.camera.position;
      var cx = Math.floor(pos[0] / CHUNK_SIZE) * CHUNK_SIZE;
      var cz = Math.floor(pos[2] / CHUNK_SIZE) * CHUNK_SIZE;
      edit.setPoints([cx, 0, cz], [cx + CHUNK_SIZE - 1, 255, cz + CHUNK_SIZE - 1]);
      setStatus("Selected the chunk under the camera (" + cx + "," + cz + ").");
    }

    /** The full keyboard equivalent for picking and handle-dragging. None of
     * these keys collide with viewport-webgl.js's own WASD/arrow-key camera
     * controls, so both can be live on the same focused canvas at once. */
    function onEditorKeyDown(event) {
      if (!edit) return;
      var key = event.key;
      if (key >= "1" && key <= "6") {
        activeFaceIndex = Number(key) - 1;
        var handlesApi = window.AmuletViewportHandles;
        var name = handlesApi ? handlesApi.FACE_HANDLES[activeFaceIndex].name : key;
        setStatus("Active face for [ / ] nudging: " + name);
        event.preventDefault();
      } else if (key === "[") {
        nudgeActiveFace(-1);
        event.preventDefault();
      } else if (key === "]") {
        nudgeActiveFace(1);
        event.preventDefault();
      } else if (key === "i") {
        stepFarCorner(0, -1);
        event.preventDefault();
      } else if (key === "k") {
        stepFarCorner(0, 1);
        event.preventDefault();
      } else if (key === "j") {
        stepFarCorner(-1, 0);
        event.preventDefault();
      } else if (key === "l") {
        stepFarCorner(1, 0);
        event.preventDefault();
      } else if (key === "c" || key === "C") {
        selectChunkUnderCamera();
        event.preventDefault();
      }
    }

    canvas.addEventListener("pointerdown", onPickPointerDown);
    canvas.addEventListener("pointermove", onPickPointerMove);
    canvas.addEventListener("pointerup", onPickPointerUp);
    canvas.addEventListener("pointercancel", onPickPointerUp);
    canvas.addEventListener("keydown", onEditorKeyDown);

    function ensureViewport() {
      if (viewport) return viewport;
      viewport = new window.AmuletViewportWebGL.Viewport(canvas);
      detachControls = viewport.attachControls(canvas, {
        // A plain drag still only rotates the camera. An Alt+drag, or a
        // drag that starts on a selection handle, must not also spin the
        // view -- see the module comment above onPickPointerDown.
        shouldRotate: function (event) {
          return !event.altKey && !activeDrag;
        },
      });
      return viewport;
    }

    async function pollWorldOpen(id) {
      for (var i = 0; i < 600; i++) {
        var response = await sidecarCall("world.open_status", { world_id: id });
        if (!response.ok) throw new Error("world.open_status failed: " + JSON.stringify(response.error));
        if (response.result.status !== "pending") return response.result;
        await sleep(100);
      }
      throw new Error("world.open_status stayed pending");
    }

    async function pollResourcePack(id) {
      for (var i = 0; i < 600; i++) {
        var prep = await sidecarCall("viewport.prepare", { world_id: id });
        if (!prep.ok) throw new Error("viewport.prepare failed: " + JSON.stringify(prep.error));
        if (prep.result.status === "ready") return;
        if (prep.result.status === "failed") throw new Error("resource pack build failed");
        await sleep(300);
      }
      throw new Error("resource pack never became ready");
    }

    async function loadAtlas(id) {
      var meta = await sidecarCall("viewport.atlas", { world_id: id });
      if (!meta.ok) throw new Error("viewport.atlas failed: " + JSON.stringify(meta.error));
      var bytes = await readBinary(meta.result.path);
      if (!bytes.ok) throw new Error("reading atlas bytes failed: " + JSON.stringify(bytes.error));
      var blob = new Blob([bytes.result], { type: "image/png" });
      var bitmap = await createImageBitmap(blob);
      ensureViewport().loadAtlasImage(bitmap);
    }

    /**
     * Request every still-missing chunk in one batch call instead of one
     * "viewport.chunk_mesh" call per chunk. See the module doc comment for
     * the measured before/after: batching turns N temp files and N IPC
     * round trips into one combined buffer read once and sliced per chunk
     * via each result's byte_offset/byte_length.
     */
    async function requestChunks(coords) {
      if (!coords.length) return;
      var kicked = await sidecarCall("viewport.chunk_mesh_batch", {
        world_id: worldId,
        dimension: dimension,
        chunks: coords,
      });
      if (!kicked.ok) return;
      var batchId = kicked.result.batch_id;

      var status = null;
      for (var i = 0; i < 600 && streaming; i++) {
        var poll = await sidecarCall("viewport.chunk_mesh_batch_status", { batch_id: batchId });
        if (!poll.ok) return;
        if (poll.result.status === "ready") {
          status = poll.result;
          break;
        }
        if (poll.result.status === "failed") return;
        await sleep(30);
      }
      if (!status) return;

      try {
        // Occupancy is read once here regardless of whether any chunk had a
        // renderable mesh (a superflat ocean chunk can be "all water, zero
        // solid faces" for the mesher and still matter for picking -- the
        // ray needs to know it is water, not treat it as unknown).
        var occBytes = occupancyStore && status.occupancy_path ? await readBinary(status.occupancy_path) : null;
        // Normalise to an ArrayBuffer whose byte 0 IS this result's byte 0
        // -- readBinary's Uint8Array may be a view with a non-zero
        // byteOffset into a larger buffer, and the "occupancy_sub_chunks"
        // offsets from the sidecar are relative to the file's own start.
        var occBuffer =
          occBytes && occBytes.ok
            ? occBytes.result.buffer.slice(
                occBytes.result.byteOffset,
                occBytes.result.byteOffset + occBytes.result.byteLength
              )
            : null;
        if (occupancyStore && occBuffer) {
          for (var k = 0; k < status.chunks.length; k++) {
            var occEntry = status.chunks[k];
            if (occEntry.occupancy_exists) {
              occupancyStore.setChunk(occEntry.cx, occEntry.cz, occEntry.occupancy_sub_chunks, occBuffer);
            }
          }
        }

        var readyChunks = status.chunks.filter(function (c) {
          return c.exists && c.vertex_count > 0;
        });
        if (!readyChunks.length) return;
        var bytes = await readBinary(status.path);
        if (!bytes.ok) return;
        var raw = bytes.result;
        var view = ensureViewport();
        for (var j = 0; j < readyChunks.length; j++) {
          var entry = readyChunks[j];
          var arrayBuffer = raw.buffer.slice(
            raw.byteOffset + entry.byte_offset,
            raw.byteOffset + entry.byte_offset + entry.byte_length
          );
          view.loadChunkMesh(entry.cx, entry.cz, arrayBuffer, entry.vertex_count);
          frameFirstChunk(view, entry.cx, entry.cz);
        }
      } finally {
        // Always release, even on a mid-loop error above, or the batch's
        // combined file leaks until the sidecar's own LRU cap catches up.
        sidecarCall("viewport.chunk_mesh_batch_release", { batch_id: batchId });
      }
    }

    var framed = false;

    /**
     * Point the camera at the world the moment there is a world to point at.
     *
     * The camera starts at a fixed spot chosen before any world is open, which
     * is the only sensible default when nothing is loaded and the wrong place
     * to leave it once something is. A user who opens a world and sees empty
     * sky concludes it failed to load -- the terrain was below and behind them
     * the whole time.
     *
     * Only the FIRST chunk does this. Re-framing on every chunk that streams
     * in would drag the camera around under someone who is already looking
     * where they want to look, which is worse than never framing at all.
     */
    function frameFirstChunk(view, cx, cz) {
      if (framed) return;
      framed = true;
      var centreX = cx * 16 + 8;
      var centreZ = cz * 16 + 8;
      // Back off along +Z and up, then look down at the chunk's middle. The
      // fixture's terrain tops out around y=10 and a real world's surface is
      // near y=64; 40 blocks up and 40 back frames either without clipping in.
      view.camera.position = [centreX, 40, centreZ + 40];
      if (typeof view.setRotationDegrees === "function") {
        // Positive pitch is DOWN here, and the sign is worth stating because
        // getting it backwards aims the camera at empty sky and looks exactly
        // like a world that failed to load. From mat4View:
        //   forward = [sin(yaw)*cos(pitch), -sin(pitch), -cos(yaw)*cos(pitch)]
        // so yaw 0 looks toward -Z -- which is why the camera is placed at
        // +40 on Z, in front of the chunk rather than behind it -- and a
        // positive pitch drives forward.y negative, i.e. downward.
        view.setRotationDegrees(0, 30);
      }
    }

    async function streamTick() {
      if (streamBusy || !streaming || !viewport) return;
      streamBusy = true;
      try {
        var pos = viewport.camera.position;
        var center = chunkCoordOf(pos[0], pos[2]);
        var wanted = {};
        var wantedList = [];
        for (var dx = -STREAM_RADIUS; dx <= STREAM_RADIUS; dx++) {
          for (var dz = -STREAM_RADIUS; dz <= STREAM_RADIUS; dz++) {
            var cx = center[0] + dx;
            var cz = center[1] + dz;
            wanted[cx + "," + cz] = true;
            if (!viewport.hasChunk(cx, cz)) wantedList.push([cx, cz]);
          }
        }
        // Release anything that has drifted well outside range first, so
        // GPU memory never grows unbounded while the camera roams.
        var loaded = viewport.loadedChunkCoords();
        for (var i = 0; i < loaded.length; i++) {
          var lx = loaded[i][0];
          var lz = loaded[i][1];
          var dcx = Math.abs(lx - center[0]);
          var dcz = Math.abs(lz - center[1]);
          if (dcx > STREAM_RADIUS + UNLOAD_MARGIN || dcz > STREAM_RADIUS + UNLOAD_MARGIN) {
            viewport.unloadChunk(lx, lz);
            if (occupancyStore) occupancyStore.unloadChunk(lx, lz);
          }
        }
        // Request every missing chunk in ONE batch call rather than one
        // call per chunk -- see requestChunks()'s doc comment. A single
        // outstanding batch at a time still holds: streamTick itself is
        // re-entrancy-guarded by streamBusy above, so a burst of camera
        // movement never fires two overlapping batch requests.
        await requestChunks(wantedList);
      } catch (err) {
        setStatus("Streaming error: " + String(err));
      } finally {
        streamBusy = false;
      }
    }

    // The overlay module draws the selection box, its handles and the
    // reference grid. It deliberately builds no camera of its own: it is handed
    // the same view-projection the chunks were drawn with, so the box and the
    // terrain cannot drift apart.
    //
    // It is created lazily, on the first frame that has a GL context, because
    // the viewport itself is only constructed once a world is open.
    var overlay = null;
    // Whether the reference grid should be drawn once an overlay exists --
    // read by ensureOverlay() below and by the exposed setGridVisible/
    // isGridVisible() pair, so a toggle pressed before a world (and
    // therefore a GL context) exists still takes effect the moment one
    // shows up, rather than being silently lost.
    var gridVisible = true;

    function ensureOverlay() {
      if (overlay || !viewport || !viewport.gl) return overlay;
      var factory = window.AmuletViewportOverlays;
      if (!factory || typeof factory.SelectionOverlay !== "function") return null;
      overlay = new factory.SelectionOverlay(viewport.gl);
      overlay.setGrid(gridVisible ? { y: 0 } : null);
      viewport.afterRender = function (transform, cameraPosition) {
        overlay.render(transform, cameraPosition);
      };
      return overlay;
    }

    /** Show or hide the reference grid drawn at y=0. Real and local: no
     * sidecar round trip, since the grid is purely a viewport overlay. */
    function setGridVisible(visible) {
      gridVisible = !!visible;
      var current = ensureOverlay();
      if (current && typeof current.setGrid === "function") {
        current.setGrid(gridVisible ? { y: 0 } : null);
      }
      return gridVisible;
    }

    function isGridVisible() {
      return gridVisible;
    }

    /** Set or clear the selection the viewport draws. */
    function setSelection(pointOne, pointTwo) {
      var current = ensureOverlay();
      if (!current) return false;
      if (!pointOne || !pointTwo) current.clearSelection();
      else current.setSelection(pointOne, pointTwo);
      return true;
    }

    function renderLoop() {
      if (viewport) {
        ensureOverlay();
        viewport.render();
      }
      rafHandle = requestAnimationFrame(renderLoop);
    }

    async function openWorld(path) {
      setStatus("Opening world...");
      try {
        var openResponse = await sidecarCall("world.open", { path: path });
        if (!openResponse.ok) {
          setStatus("world.open failed: " + JSON.stringify(openResponse.error));
          return;
        }
        worldId = openResponse.result.world_id;
        var opened = await pollWorldOpen(worldId);
        if (opened.status !== "ready") {
          setStatus("World failed to open: " + JSON.stringify(opened));
          return;
        }
        dimension = opened.dimensions[0];
        setStatus("World open (" + opened.name + "). Building resource pack, this can take a while on first run...");
        await pollResourcePack(worldId);
        setStatus("Loading texture atlas...");
        await loadAtlas(worldId);

        emptyEl.hidden = true;
        canvas.hidden = false;
        setStatus("Streaming chunks. Drag to look, scroll or WASD to move.");
        streaming = true;
        if (streamTimer === null) {
          streamTimer = setInterval(streamTick, STREAM_INTERVAL_MS);
        }
        streamTick();
        if (rafHandle === null) renderLoop();
        editState.canUndo = false;
        editState.canRedo = false;
        editState.unsaved = false;
        refreshEditControls();
      } catch (err) {
        setStatus("Failed to open world: " + String(err));
        refreshEditControls();
      }
    }

    if (openButton && pathInput) {
      openButton.addEventListener("click", function () {
        var path = pathInput.value.trim();
        if (!path) {
          setStatus("Enter an absolute world folder path first.");
          return;
        }
        openWorld(path);
      });
    }

    // Exposed for the headless capture script (scripts/capture_viewport_render.js)
    // and for tests: a narrow, explicit hook rather than reaching into closure
    // state. Never used by the ordinary UI path above.
    window.__AmuletViewportPanel = {
      openWorld: openWorld,
      getViewport: function () {
        return viewport;
      },
      isStreaming: function () {
        return streaming;
      },
      // Read-only access to the world this panel already has open, for a
      // caller (the Analyze ribbon tab in docs/site/studio-workspace.js)
      // that needs the same world_id/dimension fill/replace already use
      // internally, without a second "which world is open" tracked
      // separately and risking disagreeing with this one.
      getWorldId: function () {
        return worldId;
      },
      getDimension: function () {
        return dimension;
      },
      // Test-only: construct the Viewport (and wire attachControls'
      // shouldRotate hook) without going through openWorld()'s sidecar
      // calls, so the picking/handle-drag wiring above can be exercised in
      // a jsdom runtime contract with a fake AmuletViewportWebGL.Viewport
      // standing in for a real GPU context.
      _ensureViewportForTest: ensureViewport,
      // Set or clear the drawn selection. Exposed rather than left internal
      // because an overlay nothing can reach is the same defect this project
      // has now hit three times: a component fully built, fully tested, and
      // wired to nothing.
      setSelection: setSelection,
      hasOverlay: function () {
        return Boolean(overlay);
      },
      // Reference-grid visibility, for the View ribbon tab's "Layers"
      // command (docs/site/studio-workspace.js) -- local UI state, no
      // sidecar involved.
      setGridVisible: setGridVisible,
      isGridVisible: isGridVisible,
      // Picking/handle-dragging hooks, exposed for the same reason as
      // setSelection above -- and so a later change that adds a real
      // per-block sidecar query can swap the ground-plane placeholder out
      // without touching the pointer/keyboard wiring itself.
      setSolidTest: function (fn) {
        if (typeof fn === "function") solidTest = fn;
      },
      pickBlock: pickBlock,
      rayFromEvent: rayFromEvent,
      nudgeActiveFace: nudgeActiveFace,
      stepFarCorner: stepFarCorner,
      selectChunkUnderCamera: selectChunkUnderCamera,
      getActiveFaceIndex: function () {
        return activeFaceIndex;
      },
      isDraggingHandle: function () {
        return Boolean(activeDrag);
      },
      // Exposed for tests: the edit controls, without reaching into closure
      // state.
      edit: edit,
      runFill: runFill,
      runReplace: runReplace,
      runUndo: runUndo,
      runRedo: runRedo,
      runSave: runSave,
      runCopySelection: runCopySelection,
      runCutSelection: runCutSelection,
      runPasteSelection: runPasteSelection,
      runDeleteSelection: runDeleteSelection,
      runExportStructure: runExportStructure,
      runImportStructure: runImportStructure,
      runCreateChunks: runCreateChunks,
      runDeleteChunks: runDeleteChunks,
      runPruneChunks: runPruneChunks,
      runPlaceEntity: runPlaceEntity,
      runRemoveEntities: runRemoveEntities,
      runWriteLevel: runWriteLevel,
      runWriteGameRules: runWriteGameRules,
    };

    window.addEventListener("beforeunload", function () {
      streaming = false;
      if (streamTimer !== null) clearInterval(streamTimer);
      if (rafHandle !== null) cancelAnimationFrame(rafHandle);
      if (detachControls) detachControls();
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
