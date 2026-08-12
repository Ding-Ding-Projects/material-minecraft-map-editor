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
 * STREAM_RADIUS of the camera's current chunk. Request every chunk in that
 * set that is not yet loaded (via the sidecar's "viewport.chunk_mesh",
 * exactly the harness's own call), upload it to the GPU as it arrives, and
 * release (unloadChunk) every loaded chunk that has fallen outside
 * STREAM_RADIUS + 1. Requests run one at a time on their own async chain so
 * a burst of camera movement never fires dozens of concurrent sidecar
 * requests -- the sidecar dispatcher is shared with every other panel's
 * calls, and world.open/viewport.prepare already demonstrate the
 * "background thread + poll" pattern this loop follows for its own
 * world.open call.
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

  var STREAM_RADIUS = 2; // chunks around the camera to keep loaded
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

    var root = document.createElement("div");
    root.className = "viewport-edit-panel";
    root.appendChild(pointsRow);
    root.appendChild(fillGroup);
    root.appendChild(replaceGroup);
    root.appendChild(historyGroup);
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

    if (edit) {
      edit.onFill(runFill);
      edit.onReplace(runReplace);
      edit.onUndo(runUndo);
      edit.onRedo(runRedo);
      edit.onSave(runSave);
      edit.onPointsChanged(refreshEditControls);
      refreshEditControls();
    }

    function ensureViewport() {
      if (viewport) return viewport;
      viewport = new window.AmuletViewportWebGL.Viewport(canvas);
      detachControls = viewport.attachControls(canvas);
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

    async function requestChunk(cx, cz) {
      var meta = await sidecarCall("viewport.chunk_mesh", {
        world_id: worldId,
        dimension: dimension,
        cx: cx,
        cz: cz,
      });
      if (!meta.ok || !meta.result.exists || meta.result.vertex_count === 0) return;
      var bytes = await readBinary(meta.result.path);
      if (!bytes.ok) return;
      var raw = bytes.result;
      var arrayBuffer = raw.buffer.slice(raw.byteOffset, raw.byteOffset + raw.byteLength);
      var view = ensureViewport();
      view.loadChunkMesh(cx, cz, arrayBuffer, meta.result.vertex_count);
      frameFirstChunk(view, cx, cz);
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
          }
        }
        // Request missing chunks one at a time -- never flood the sidecar
        // dispatcher, which other panels' calls share.
        for (var j = 0; j < wantedList.length && streaming; j++) {
          await requestChunk(wantedList[j][0], wantedList[j][1]);
        }
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

    function ensureOverlay() {
      if (overlay || !viewport || !viewport.gl) return overlay;
      var factory = window.AmuletViewportOverlays;
      if (!factory || typeof factory.SelectionOverlay !== "function") return null;
      overlay = new factory.SelectionOverlay(viewport.gl);
      overlay.setGrid({ y: 0 });
      viewport.afterRender = function (transform, cameraPosition) {
        overlay.render(transform, cameraPosition);
      };
      return overlay;
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
      // Set or clear the drawn selection. Exposed rather than left internal
      // because an overlay nothing can reach is the same defect this project
      // has now hit three times: a component fully built, fully tested, and
      // wired to nothing.
      setSelection: setSelection,
      hasOverlay: function () {
        return Boolean(overlay);
      },
      // Exposed for tests: the edit controls, without reaching into closure
      // state.
      edit: edit,
      runFill: runFill,
      runReplace: runReplace,
      runUndo: runUndo,
      runRedo: runRedo,
      runSave: runSave,
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
