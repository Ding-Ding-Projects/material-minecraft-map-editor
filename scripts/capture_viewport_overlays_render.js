/**
 * PROOF that the selection-box overlay actually draws over the WebGL2
 * viewport -- not just that its geometry math is correct arithmetic
 * (tests/test_viewport_overlay_geometry.py already covers that without a
 * GPU at all).
 *
 * Launches the packaged Electron shell headlessly (never shows a window --
 * see electron/main.js's AMULET_HEADLESS gate), points it at a tiny
 * standalone harness page that loads viewport-webgl.js + viewport-overlays.js
 * directly (no sidecar, no real world needed -- this is proving the overlay
 * draws, not re-proving the chunk mesh pipeline that
 * capture_viewport_render.js already proves), drives it over the Chrome
 * DevTools protocol, and reads back the canvas pixels via toDataURL() --
 * the same route capture_viewport_render.js uses, because
 * Page.captureScreenshot hangs indefinitely against this WebGL2 canvas.
 *
 * Two frames are captured: one with only a chunk-shaped coloured cube (no
 * overlay) and one with the overlay drawn on top of it. The pixels are
 * compared and must differ -- proving the overlay pass genuinely changed
 * what is on screen, not just that a function was called.
 *
 * Usage: node scripts/capture_viewport_overlays_render.js
 */
const fs = require("fs");
const path = require("path");
const os = require("os");
const { spawn } = require("child_process");
const zlib = require("zlib");

const REPO = path.resolve(__dirname, "..");
const ELECTRON_BIN = path.join(REPO, "node_modules", "electron", "dist", "electron.exe");

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function assert(condition, message) {
  if (!condition) throw new Error("ASSERTION FAILED: " + message);
}

async function cdp(wsUrl) {
  const socket = new WebSocket(wsUrl);
  await new Promise((resolve, reject) => {
    socket.addEventListener("open", resolve, { once: true });
    socket.addEventListener("error", reject, { once: true });
  });
  let nextId = 1;
  const waiting = new Map();
  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    const pending = waiting.get(message.id);
    if (!pending) return;
    waiting.delete(message.id);
    if (message.error) pending.reject(new Error(JSON.stringify(message.error)));
    else pending.resolve(message.result);
  });
  return {
    send(method, params = {}) {
      const id = nextId++;
      socket.send(JSON.stringify({ id, method, params }));
      return new Promise((resolve, reject) => waiting.set(id, { resolve, reject }));
    },
    close: () => socket.close(),
  };
}

function withTimeout(promise, ms, label) {
  let timer;
  const timeout = new Promise((_resolve, reject) => {
    timer = setTimeout(() => reject(new Error("TIMEOUT after " + ms + "ms: " + label)), ms);
  });
  return Promise.race([promise, timeout]).finally(() => clearTimeout(timer));
}

async function evalJSON(client, expression) {
  const result = await withTimeout(
    client.send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true }),
    20000,
    "Runtime.evaluate: " + expression.slice(0, 80)
  );
  if (result.exceptionDetails) {
    throw new Error("Renderer threw: " + JSON.stringify(result.exceptionDetails));
  }
  return result.result && result.result.value;
}

function decodePng(pngBuffer) {
  assert(pngBuffer.slice(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])), "not a PNG");
  let offset = 8;
  let width = 0, height = 0, bitDepth = 0, colorType = 0;
  const idatChunks = [];
  while (offset < pngBuffer.length) {
    const length = pngBuffer.readUInt32BE(offset);
    const type = pngBuffer.toString("ascii", offset + 4, offset + 8);
    const data = pngBuffer.slice(offset + 8, offset + 8 + length);
    if (type === "IHDR") {
      width = data.readUInt32BE(0);
      height = data.readUInt32BE(4);
      bitDepth = data.readUInt8(8);
      colorType = data.readUInt8(9);
    } else if (type === "IDAT") {
      idatChunks.push(data);
    } else if (type === "IEND") {
      break;
    }
    offset += 12 + length;
  }
  assert(bitDepth === 8, "expected 8-bit PNG, got bit depth " + bitDepth);
  const channels = colorType === 6 ? 4 : colorType === 2 ? 3 : 1;
  const raw = zlib.inflateSync(Buffer.concat(idatChunks));
  const stride = width * channels;
  const pixels = Buffer.alloc(width * height * channels);
  for (let y = 0; y < height; y++) {
    const rowStart = y * (stride + 1) + 1;
    raw.copy(pixels, y * stride, rowStart, rowStart + stride);
  }
  return { width, height, channels, pixels };
}

function countDifferingPixels(a, b) {
  assert(a.width === b.width && a.height === b.height && a.channels === b.channels, "frame size mismatch");
  let differing = 0;
  for (let i = 0; i < a.pixels.length; i += a.channels) {
    let diff = 0;
    for (let c = 0; c < a.channels; c++) {
      diff += Math.abs(a.pixels[i + c] - b.pixels[i + c]);
    }
    if (diff > 6) differing++;
  }
  return differing;
}

const HARNESS_HTML = `<!doctype html>
<html><body style="margin:0">
<canvas id="canvas" width="480" height="320"></canvas>
<script src="viewport-webgl.js"></script>
<script src="viewport-overlays.js"></script>
<script>
  function buildCubeMesh(min, max, r, g, b) {
    // position(3) texcoord(2) texoffset(4) tint(3), matching
    // AmuletViewportWebGL.VERTEX_STRIDE_FLOATS -- a flat-shaded coloured
    // cube stands in for a real meshed chunk here; this script is only
    // proving the overlay pass, not re-proving the chunk mesher.
    const AmuletViewportOverlays = window.AmuletViewportOverlays;
    const faces = Array.from(AmuletViewportOverlays._buildBoxFaceVertices(min, max));
    const stride = 12;
    const out = new Float32Array((faces.length / 3) * stride);
    for (let i = 0, v = 0; i < faces.length; i += 3, v++) {
      const o = v * stride;
      out[o] = faces[i]; out[o + 1] = faces[i + 1]; out[o + 2] = faces[i + 2];
      out[o + 9] = r; out[o + 10] = g; out[o + 11] = b;
    }
    return out;
  }

  window.__runCapture = function (drawOverlay) {
    const canvas = document.getElementById("canvas");
    const viewport = new window.AmuletViewportWebGL.Viewport(canvas);
    // A 1x1 white texture so the terrain-stand-in cube's tint shows through
    // unmodified (viewport-webgl's fragment shader discards on alpha<0.02
    // and multiplies by tint*0.85).
    viewport.loadAtlasRGBA(new Uint8Array([255, 255, 255, 255]), 1, 1);
    const mesh = buildCubeMesh([0, 0, -4], [12, 4, 4], 0.6, 0.35, 0.2);
    // The mesh vertex format expects real UV/texoffset data too; zero is
    // fine here since the 1x1 atlas is uniform everywhere.
    viewport.loadMesh(mesh.buffer, mesh.length / 12);
    viewport.camera.position = [6, 10, 20];
    viewport.camera.pitch = 0.3;
    viewport.render();

    if (drawOverlay) {
      const overlay = new window.AmuletViewportOverlays.SelectionOverlay(viewport.gl);
      overlay.setGrid({ y: 0, halfExtent: 24, spacing: 2 });
      overlay.setSelection([2, 1, -2], [8, 3, 1]);
      const projection = window.AmuletViewportWebGL._mat4Perspective(
        viewport.fovYRadians, canvas.width / canvas.height, viewport.near, viewport.far
      );
      const view = window.AmuletViewportWebGL._mat4View(
        viewport.camera.position, viewport.camera.yaw, viewport.camera.pitch
      );
      const transform = window.AmuletViewportWebGL._mat4Multiply(projection, view);
      overlay.render(transform, viewport.camera.position);
    }

    return canvas.toDataURL("image/png");
  };
</script>
</body></html>`;

async function main() {
  if (!fs.existsSync(ELECTRON_BIN)) {
    throw new Error(`Electron binary not found at ${ELECTRON_BIN}. Run "npm install" first.`);
  }

  const outDir = path.resolve(REPO, "docs/huishots/electron");
  fs.mkdirSync(outDir, { recursive: true });

  const harnessDir = fs.mkdtempSync(path.join(os.tmpdir(), "mmwe-overlay-harness-"));
  fs.writeFileSync(path.join(harnessDir, "index.html"), HARNESS_HTML);
  fs.copyFileSync(path.join(REPO, "docs/site/viewport-webgl.js"), path.join(harnessDir, "viewport-webgl.js"));
  fs.copyFileSync(path.join(REPO, "docs/site/viewport-overlays.js"), path.join(harnessDir, "viewport-overlays.js"));

  const configDir = fs.mkdtempSync(path.join(os.tmpdir(), "mmwe-overlay-config-"));
  const userData = fs.mkdtempSync(path.join(os.tmpdir(), "mmwe-overlay-userdata-"));

  const port = 9337;
  const child = spawn(
    ELECTRON_BIN,
    [
      REPO,
      `--remote-debugging-port=${port}`,
      `--user-data-dir=${userData}`,
      "--no-sandbox",
      "--use-gl=angle",
      "--use-angle=swiftshader",
      "--enable-unsafe-swiftshader",
    ],
    {
      cwd: REPO,
      stdio: "inherit",
      windowsHide: true,
      env: Object.assign({}, process.env, {
        CONFIG_DIR: configDir,
        AMULET_HEADLESS: "1",
      }),
    }
  );

  let client = null;
  try {
    let target = null;
    for (let attempt = 0; attempt < 80 && !target; attempt++) {
      try {
        const response = await fetch(`http://127.0.0.1:${port}/json/list`);
        const targets = await response.json();
        target = targets.find((t) => t.type === "page" && !/^devtools:/.test(t.url));
      } catch {
        await sleep(250);
      }
    }
    if (!target) throw new Error("Electron never exposed a debugging target for its renderer page.");

    client = await cdp(target.webSocketDebuggerUrl);
    await client.send("Page.enable");
    await client.send("Runtime.enable");

    const harnessUrl = "file:///" + path.join(harnessDir, "index.html").replace(/\\/g, "/");
    await client.send("Page.navigate", { url: harnessUrl });
    await sleep(500);
    for (let attempt = 0; attempt < 40; attempt++) {
      const ready = await evalJSON(client, "typeof window.__runCapture === 'function'");
      if (ready) break;
      await sleep(250);
    }
    assert(
      await evalJSON(client, "typeof window.__runCapture === 'function'"),
      "harness page never finished loading (window.__runCapture missing)"
    );

    console.log("step: capturing frame WITHOUT overlay...");
    const withoutDataUrl = await evalJSON(client, "window.__runCapture(false)");
    console.log("step: capturing frame WITH overlay...");
    const withDataUrl = await evalJSON(client, "window.__runCapture(true)");

    assert(typeof withoutDataUrl === "string" && withoutDataUrl.startsWith("data:image/png;base64,"), "no-overlay capture failed");
    assert(typeof withDataUrl === "string" && withDataUrl.startsWith("data:image/png;base64,"), "overlay capture failed");

    const withoutBuffer = Buffer.from(withoutDataUrl.slice("data:image/png;base64,".length), "base64");
    const withBuffer = Buffer.from(withDataUrl.slice("data:image/png;base64,".length), "base64");

    const withoutPath = path.join(outDir, "viewport-overlay-without-selection.png");
    const withPath = path.join(outDir, "viewport-overlay-with-selection.png");
    fs.writeFileSync(withoutPath, withoutBuffer);
    fs.writeFileSync(withPath, withBuffer);
    console.log("Wrote", withoutPath, withoutBuffer.length, "bytes");
    console.log("Wrote", withPath, withBuffer.length, "bytes");

    // Read both PNGs back and compare actual pixels -- proof the overlay
    // pass changed the framebuffer, not just that a function ran.
    const withoutDecoded = decodePng(fs.readFileSync(withoutPath));
    const withDecoded = decodePng(fs.readFileSync(withPath));
    const differing = countDifferingPixels(withoutDecoded, withDecoded);
    console.log("Pixels differing between with/without overlay:", differing, "of", withoutDecoded.width * withoutDecoded.height);
    assert(differing > 200, "overlay render is pixel-identical (or nearly so) to the no-overlay frame -- the overlay did not actually draw anything");

    console.log("\nSelection overlay PROOF: real WebGL2 draw calls changed " + differing + " pixels when the selection box + grid were drawn over the terrain-stand-in geometry.");
  } finally {
    if (client) client.close();
    child.kill();
    try {
      fs.rmSync(configDir, { recursive: true, force: true });
      fs.rmSync(userData, { recursive: true, force: true });
      fs.rmSync(harnessDir, { recursive: true, force: true });
    } catch {}
  }
}

const HARD_TIMEOUT_MS = 5 * 60 * 1000;
const hardTimeout = setTimeout(() => {
  console.error("HARD TIMEOUT: capture script exceeded " + HARD_TIMEOUT_MS + "ms, forcing exit");
  process.exit(1);
}, HARD_TIMEOUT_MS);
hardTimeout.unref?.();

main()
  .then(() => clearTimeout(hardTimeout))
  .catch((err) => {
    clearTimeout(hardTimeout);
    console.error(err);
    process.exitCode = 1;
  });
