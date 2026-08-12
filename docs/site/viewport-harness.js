/* Drives the real sidecar to open a world, mesh a real chunk, and draw it
 * with the WebGL2 module -- see viewport-harness.html for what this proves
 * and what it deliberately is not.
 */
(function () {
  "use strict";

  var statusEl = document.getElementById("status");
  function log(line) {
    statusEl.textContent += "\n" + line;
    // eslint-disable-next-line no-console
    console.log("[viewport-harness]", line);
  }

  function getWorldPathFromQuery() {
    var params = new URLSearchParams(window.location.search);
    return params.get("world");
  }

  function sidecarCall(method, params) {
    var bridge = window.mmweDesktop && window.mmweDesktop.sidecar;
    if (!bridge) return Promise.resolve({ ok: false, error: { code: "no_bridge" } });
    return bridge.call(method, params || {});
  }

  function readBinary(path) {
    var bridge = window.mmweDesktop && window.mmweDesktop.sidecar;
    if (!bridge || typeof bridge.readBinary !== "function") {
      return Promise.resolve({ ok: false, error: { code: "no_bridge" } });
    }
    return bridge.readBinary(path);
  }

  function sleep(ms) {
    return new Promise(function (resolve) {
      setTimeout(resolve, ms);
    });
  }

  function fail(message) {
    log("ERROR: " + message);
    window.__viewportHarnessDone = true;
    window.__viewportHarnessError = message;
  }

  async function pollOpenStatus(worldId) {
    for (var i = 0; i < 400; i++) {
      var response = await sidecarCall("world.open_status", { world_id: worldId });
      if (!response.ok) throw new Error("world.open_status failed: " + JSON.stringify(response.error));
      if (response.result.status !== "pending") return response.result;
      await sleep(50);
    }
    throw new Error("world.open_status stayed pending");
  }

  async function main() {
    var worldPath = getWorldPathFromQuery();
    if (!worldPath) {
      log("ERROR: no ?world= query parameter given");
      return;
    }
    log("waiting for the sidecar child process to come up...");
    var pingOk = false;
    for (var attempt = 0; attempt < 100; attempt++) {
      var ping = await sidecarCall("protocol.ping", {});
      if (ping.ok) {
        pingOk = true;
        break;
      }
      await sleep(200);
    }
    if (!pingOk) {
      log("ERROR: sidecar never came up (protocol.ping kept failing)");
      window.__viewportHarnessDone = true;
      window.__viewportHarnessError = "sidecar never came up";
      return;
    }
    log("sidecar is up. opening world: " + worldPath);

    var openResponse = await sidecarCall("world.open", { path: worldPath });
    if (!openResponse.ok) {
      log("ERROR: world.open failed: " + JSON.stringify(openResponse.error));
      window.__viewportHarnessDone = true;
      window.__viewportHarnessError = "world.open failed: " + JSON.stringify(openResponse.error);
      return;
    }
    var worldId = openResponse.result.world_id;

    var opened = await pollOpenStatus(worldId);
    if (opened.status !== "ready") {
      fail("world failed to open: " + JSON.stringify(opened));
      return;
    }
    log("world open, dimensions: " + JSON.stringify(opened.dimensions));

    log("preparing resource pack (downloads vanilla textures on first run, be patient)...");
    for (var prepAttempt = 0; prepAttempt < 600; prepAttempt++) {
      var prep = await sidecarCall("viewport.prepare", { world_id: worldId });
      if (!prep.ok) {
        fail("viewport.prepare failed: " + JSON.stringify(prep.error));
        return;
      }
      if (prep.result.status === "ready") break;
      if (prep.result.status === "failed") {
        fail("resource pack build failed: " + JSON.stringify(prep.result));
        return;
      }
      await sleep(500);
    }
    log("resource pack ready.");

    log("requesting texture atlas...");
    var atlasMeta = await sidecarCall("viewport.atlas", { world_id: worldId });
    if (!atlasMeta.ok) {
      fail("viewport.atlas failed: " + JSON.stringify(atlasMeta.error));
      return;
    }
    log("atlas: " + JSON.stringify(atlasMeta.result));

    var atlasBytes = await readBinary(atlasMeta.result.path);
    if (!atlasBytes.ok) {
      fail("reading atlas bytes failed: " + JSON.stringify(atlasBytes.error));
      return;
    }
    var atlasBlob = new Blob([atlasBytes.result], { type: "image/png" });
    var atlasBitmap = await createImageBitmap(atlasBlob);
    log("atlas decoded: " + atlasBitmap.width + "x" + atlasBitmap.height);

    log("requesting mesh for chunk (0, 0)...");
    var meshMeta = await sidecarCall("viewport.chunk_mesh", {
      world_id: worldId,
      dimension: opened.dimensions[0],
      cx: 0,
      cz: 0,
    });
    if (!meshMeta.ok) {
      fail("viewport.chunk_mesh failed: " + JSON.stringify(meshMeta.error));
      return;
    }
    log("mesh: " + JSON.stringify(meshMeta.result));
    if (!meshMeta.result.exists || meshMeta.result.vertex_count === 0) {
      fail("chunk (0, 0) meshed to zero vertices");
      return;
    }

    var meshBytes = await readBinary(meshMeta.result.path);
    if (!meshBytes.ok) {
      fail("reading mesh bytes failed: " + JSON.stringify(meshBytes.error));
      return;
    }

    var canvas = document.getElementById("canvas");
    var viewport = new window.AmuletViewportWebGL.Viewport(canvas);
    viewport.loadAtlasImage(atlasBitmap);
    // meshBytes.result is a Node Buffer structured-cloned into the
    // renderer as a Uint8Array; its .buffer is the raw ArrayBuffer WebGL
    // wants for bufferData.
    var raw = meshBytes.result;
    var arrayBuffer = raw.buffer.slice(raw.byteOffset, raw.byteOffset + raw.byteLength);
    viewport.loadChunkMesh(0, 0, arrayBuffer, meshMeta.result.vertex_count);

    // Render at one camera position, then move the camera with the same
    // moveLocal()/rotateDegrees() API real user input drives, and render
    // again. Two captures from an unmoved camera would be pixel-identical
    // and would prove nothing about camera input actually working -- this
    // is the whole reason two positions are captured rather than one.
    viewport.camera.position = [8, 24, 40];
    viewport.camera.pitch = 0.5;
    viewport.render();
    // Read the actual drawn pixels straight out of the canvas rather than
    // relying on the DevTools Page.captureScreenshot compositor pipeline --
    // that pipeline hung indefinitely against this WebGL2 canvas under a
    // hidden, headless BrowserWindow the one time it was tried, with no
    // error and no timeout of its own. toDataURL() reads the canvas's own
    // backing store synchronously and needs no compositor at all.
    window.__viewportHarnessPNGDataURL = canvas.toDataURL("image/png");

    viewport.moveLocal(-14, 6, 3);
    viewport.rotateDegrees(35, -8);
    viewport.render();
    window.__viewportHarnessPNGDataURL2 = canvas.toDataURL("image/png");

    log("RENDERED " + meshMeta.result.vertex_count + " vertices at two camera positions");
    window.__viewportHarnessDone = true;
  }

  main().catch(function (err) {
    log("FATAL: " + (err && err.stack ? err.stack : err));
    window.__viewportHarnessDone = true;
    window.__viewportHarnessError = String(err);
  });
})();
