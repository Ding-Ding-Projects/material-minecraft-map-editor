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
      ensureViewport().loadChunkMesh(cx, cz, arrayBuffer, meta.result.vertex_count);
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

    function renderLoop() {
      if (viewport) viewport.render();
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
      } catch (err) {
        setStatus("Failed to open world: " + String(err));
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
