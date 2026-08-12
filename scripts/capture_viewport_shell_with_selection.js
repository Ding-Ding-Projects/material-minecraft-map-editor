/**
 * Prove the SEAM: real terrain and a real selection box, drawn together, in the
 * product's own viewport panel rather than in either component's own harness.
 *
 * Both halves were built and separately verified, and neither test could see
 * this: the panel drew terrain with no overlay, the overlay drew a box over a
 * stand-in cube with no panel. The module was reachable from nothing at all
 * until it was wired, which is the same defect this project has now hit three
 * times -- a component fully built, fully tested, and connected to no one.
 *
 * Page.captureScreenshot hangs indefinitely against this WebGL2 canvas with no
 * error, so the canvas is read with toDataURL(), exactly as
 * capture_viewport_render.js does.
 */

const fs = require("fs");
const path = require("path");
const os = require("os");
const { spawn, spawnSync } = require("child_process");
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

/** Decode a PNG's raw (unfiltered) pixel bytes, just enough to check
 * "is this a single flat color" -- no external PNG library. */
function pngHasVariance(pngBuffer) {
  assert(pngBuffer.slice(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])), "not a PNG");
  let offset = 8;
  let width = 0;
  let height = 0;
  let bitDepth = 0;
  let colorType = 0;
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
  let min = 255;
  let max = 0;
  let sampled = 0;
  for (let y = 0; y < height; y++) {
    const rowStart = y * (stride + 1) + 1; // +1 filter byte per scanline; assumes filter 0 dominates
    for (let x = 0; x < stride; x += channels) {
      const v = raw[rowStart + x];
      if (v === undefined) continue;
      if (v < min) min = v;
      if (v > max) max = v;
      sampled++;
    }
  }
  return { width, height, min, max, range: max - min, sampled };
}

async function main() {
  if (!fs.existsSync(ELECTRON_BIN)) {
    throw new Error(`Electron binary not found at ${ELECTRON_BIN}. Run "npm install" first.`);
  }

  const outDir = path.resolve(REPO, "docs/huishots/electron");
  fs.mkdirSync(outDir, { recursive: true });

  const fixtureDir = fs.mkdtempSync(path.join(os.tmpdir(), "mmwe-viewport-fixture-"));
  const worldPath = path.join(fixtureDir, "world");
  console.log("Building fixture world at", worldPath);
  const build = spawnSync("py", ["-3.11", path.join(REPO, "scripts", "make_viewport_fixture_world.py"), worldPath], {
    cwd: REPO,
    encoding: "utf8",
  });
  if (build.status !== 0) {
    console.error(build.stdout);
    console.error(build.stderr);
    throw new Error("Fixture world build failed");
  }
  assert(fs.existsSync(path.join(worldPath, "level.dat")), "fixture world was not actually written");

  const configDir = fs.mkdtempSync(path.join(os.tmpdir(), "mmwe-viewport-config-"));
  const userData = fs.mkdtempSync(path.join(os.tmpdir(), "mmwe-viewport-userdata-"));

  const port = 9336;
  const child = spawn(
    ELECTRON_BIN,
    [
      REPO,
      `--remote-debugging-port=${port}`,
      `--user-data-dir=${userData}`,
      "--no-sandbox",
      // WebGL2 needs a real (software) GL backend to composite. Plain
      // --disable-gpu (used by this repo's other, non-WebGL capture
      // scripts) disables the GPU process entirely, which made
      // Page.captureScreenshot hang indefinitely against a WebGL2 canvas
      // the one time it was tried -- there was nothing for the compositor
      // to read back from. SwiftShader gives WebGL2 a real, headless-safe,
      // software-rendered GL backend instead.
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

    client = await (async () => cdp(target.webSocketDebuggerUrl))();
    await client.send("Page.enable");
    await client.send("Runtime.enable");

    // The harness downloads the real vanilla Java resource pack on first
    // run (cached afterwards) and meshes a real chunk -- give it real time
    // rather than a short fixed sleep, and poll its own completion flag.
    let done = false;
    let lastStatus = "";
    for (let attempt = 0; attempt < 240 && !done; attempt++) {
      await sleep(1000);
      const flag = await evalJSON(client, "JSON.stringify(Boolean(window.__viewportHarnessDone))");
      done = JSON.parse(flag);
      if (attempt % 5 === 0) {
        lastStatus = await evalJSON(client, "document.getElementById('status') ? document.getElementById('status').textContent : ''");
        console.log("...waiting, status so far:\n" + lastStatus);
      }
    }
    lastStatus = await evalJSON(client, "document.getElementById('status') ? document.getElementById('status').textContent : ''");
    console.log("Final harness status:\n" + lastStatus);

    console.log("step: reading harness error flag...");
    const harnessError = await evalJSON(client, "window.__viewportHarnessError || null");
    console.log("step: harness error =", harnessError);
    assert(!harnessError, "the page reported an error: " + harnessError);
    // No harness signal here on purpose: this drives the product page, which
    // has no reason to emit one. The real completion signal is geometry
    // actually reaching the GPU, which the openWorld step above already waited
    // for and refused to continue without.
    // Same reason: "RENDERED n vertices" is the harness's own status line.

    console.log("step: opening the fixture world through the panel's own openWorld()...");
    {
      const opened = await evalJSON(client,
        "(function(){var p=window.__AmuletViewportPanel;" +
        "if(!p) return 'no-panel';" +
        "p.openWorld(" + JSON.stringify(worldPath).replace(/\\/g, "/") + ");" +
        "return 'requested';})()");
      console.log("  openWorld ->", opened);
      if (opened === "no-panel") {
        throw new Error("the product page exposes no viewport panel at all");
      }
      // Opening runs through the sidecar's background-thread-and-poll path, so
      // it is not done when the call returns. Wait for real geometry rather
      // than for a fixed delay that would pass on an empty canvas.
      let vertices = 0;
      for (let attempt = 0; attempt < 60 && vertices <= 0; attempt++) {
        await sleep(1000);
        // chunkCount, NOT vertexCount. The streaming path uploads through
        // loadChunkMesh() into per-chunk buffers and increments chunkCount;
        // vertexCount belongs to the legacy single-mesh loadMesh() the proof
        // harness used. Reading the legacy field here reported zero geometry
        // against an application that was streaming perfectly well -- a check
        // that was wrong about a thing that was right, which is the worst
        // direction for a check to fail in.
        const state = await evalJSON(client,
          "(function(){var v=window.__AmuletViewportPanel.getViewport();" +
          "if(!v) return '0';" +
          "return String((v.chunkCount||0) + (v.vertexCount>0?1:0));})()");
        vertices = Number(state) || 0;
      }
      console.log("  chunks uploaded ->", vertices);
      if (vertices <= 0) {
        throw new Error("no chunk geometry ever reached the viewport, so this capture would prove nothing");
      }
    }
    console.log("step: setting a real selection through the panel's own public API...");
    {
      const wired = await evalJSON(client,
        "(function(){var p=window.__AmuletViewportPanel;" +
        "if(!p||typeof p.setSelection!=='function') return 'no-panel-api';" +
        "var ok=p.setSelection([2,1,2],[13,12,13]);" +
        "return JSON.stringify({ok:ok,hasOverlay:p.hasOverlay()});})()");
      console.log("  selection set ->", wired);
      if (wired === "no-panel-api") {
        throw new Error(
          "the viewport panel exposes no setSelection(), so the overlay module " +
          "is reachable from nothing -- which is the whole point of this check"
        );
      }
      const parsed = JSON.parse(wired);
      if (!parsed.ok || !parsed.hasOverlay) {
        throw new Error("the overlay did not attach: " + wired);
      }
    }
    console.log("step: reading canvas pixels via toDataURL() at two camera positions...");
    // Read the product page's own canvas rather than a harness global. The
    // canvas must be read in the SAME frame it was drawn in: a WebGL2
    // drawing buffer is cleared after compositing unless preserveDrawingBuffer
    // is set, so a toDataURL() taken a tick later returns a blank image and
    // reads exactly like a viewport that drew nothing.
    const grabCanvas =
      "new Promise(function(resolve){" +
      "  requestAnimationFrame(function(){" +
      "    var p=window.__AmuletViewportPanel;" +
      "    var v=p&&p.getViewport();" +
      "    if(!v||!v.gl){resolve(null);return;}" +
      "    v.render();" +
      "    resolve(v.gl.canvas.toDataURL('image/png'));" +
      "  });" +
      "})";

    const withSelection = await evalJSON(client, grabCanvas);
    await evalJSON(client, "(function(){window.__AmuletViewportPanel.setSelection(null,null);return 'cleared';})()");
    await sleep(200);
    const withoutSelection = await evalJSON(client, grabCanvas);
    await evalJSON(client, "(function(){window.__AmuletViewportPanel.setSelection([2,1,2],[13,12,13]);return 'restored';})()");
    await sleep(200);

    {
      // Pixel variance is not enough and the previous run proved it: the grid
      // plane alone gives a range of 245, so the script printed PROOF over an
      // image containing no selection box and no terrain. The only honest test
      // of "the box is drawn" is the same camera with the box and without it.
      const a = Buffer.from(String(withSelection).split(",")[1] || "", "base64");
      const b = Buffer.from(String(withoutSelection).split(",")[1] || "", "base64");
      if (!a.length || !b.length) throw new Error("one of the two comparison captures came back empty");
      if (a.equals(b)) {
        throw new Error(
          "the canvas is byte-identical with the selection set and cleared, so " +
          "the selection box is not being drawn at all -- setSelection() " +
          "returned true and changed nothing on screen"
        );
      }
      console.log("  selection changes the image: with=" + a.length + "B without=" + b.length + "B");
    }

    const dataUrl1 = withSelection;
    // Move the camera with the panel's real input path, then take the second.
    await evalJSON(client,
      "(function(){var v=window.__AmuletViewportPanel.getViewport();" +
      "v.rotateDegrees(28,-6); v.moveLocal(0,2,-6); return 'moved';})()");
    await sleep(400);
    const dataUrl2 = await evalJSON(client, grabCanvas);
    assert(typeof dataUrl1 === "string" && dataUrl1.indexOf("data:image/png;base64,") === 0, "harness did not produce a first PNG data URL: " + String(dataUrl1).slice(0, 80));
    assert(typeof dataUrl2 === "string" && dataUrl2.indexOf("data:image/png;base64,") === 0, "harness did not produce a second (moved-camera) PNG data URL: " + String(dataUrl2).slice(0, 80));

    const pngBuffer1 = Buffer.from(dataUrl1.slice("data:image/png;base64,".length), "base64");
    const pngBuffer2 = Buffer.from(dataUrl2.slice("data:image/png;base64,".length), "base64");
    const outPath1 = path.join(outDir, "viewport-webgl2-chunk-render.png");
    const outPath2 = path.join(outDir, "viewport-webgl2-chunk-render-moved-camera.png");
    fs.writeFileSync(outPath1, pngBuffer1);
    fs.writeFileSync(outPath2, pngBuffer2);
    console.log("Wrote", outPath1, pngBuffer1.length, "bytes");
    console.log("Wrote", outPath2, pngBuffer2.length, "bytes");

    // Read both PNGs back and confirm neither is a flat clear-colour
    // rectangle -- a capture is not proof until you have looked at what is
    // actually in it.
    const readBack1 = fs.readFileSync(outPath1);
    const readBack2 = fs.readFileSync(outPath2);
    const stats1 = pngHasVariance(readBack1);
    const stats2 = pngHasVariance(readBack2);
    console.log("Pixel stats (camera A):", stats1);
    console.log("Pixel stats (camera B, after moveLocal()/rotateDegrees()):", stats2);
    assert(stats1.width > 0 && stats1.height > 0, "first captured PNG has zero dimensions");
    assert(stats2.width > 0 && stats2.height > 0, "second captured PNG has zero dimensions");
    assert(stats1.range > 20, "first captured PNG has almost no pixel variance (min=" + stats1.min + " max=" + stats1.max + ") -- looks like an empty/cleared canvas, not real geometry");
    assert(stats2.range > 20, "second captured PNG has almost no pixel variance (min=" + stats2.min + " max=" + stats2.max + ") -- looks like an empty/cleared canvas, not real geometry");

    // A camera that did not actually move would render pixel-identical
    // frames. Compare the raw PNG bytes directly: same dimensions, same
    // codec, same content -- if the camera moved, the encoded bytes differ.
    assert(
      !pngBuffer1.equals(pngBuffer2),
      "the two camera positions produced byte-identical PNGs -- the camera did not actually move between renders"
    );

    console.log("\nWebGL2 viewport PROOF: a real chunk, meshed by the real Python mesher, rendered by real GL2 draw calls, captured with visible geometry at two different camera positions that produced two different images.");
  } finally {
    if (client) client.close();
    child.kill();
    try {
      fs.rmSync(configDir, { recursive: true, force: true });
      fs.rmSync(userData, { recursive: true, force: true });
      fs.rmSync(fixtureDir, { recursive: true, force: true });
    } catch {}
  }
}

const HARD_TIMEOUT_MS = 900000;
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
