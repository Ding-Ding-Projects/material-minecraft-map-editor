/**
 * Drives the REAL end-to-end round trip through the built Electron app: the
 * renderer's settings surface -> preload bridge -> IPC -> SidecarClient ->
 * real Python child process -> preferences file -> back again, and proves
 * it survives an app restart.
 *
 * This never stubs the bridge. It launches the packaged shell headlessly
 * with --remote-debugging-port, drives the actual page over the Chrome
 * DevTools protocol, and calls the actual window.mmweDesktop.sidecar
 * surface a real user's click would reach.
 *
 * A throwaway CONFIG_DIR is set for the child Electron process (and so for
 * the sidecar it spawns) before launch, per this repository's capture
 * rules -- never touches a real user's preferences file.
 *
 * Usage: node scripts/capture_electron_sidecar_roundtrip.js
 */
const fs = require("fs");
const path = require("path");
const os = require("os");
const { spawn } = require("child_process");

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

async function launchAndConnect(port, userData, configDir) {
  const child = spawn(
    ELECTRON_BIN,
    [REPO, `--remote-debugging-port=${port}`, `--user-data-dir=${userData}`, "--disable-gpu", "--no-sandbox"],
    {
      cwd: REPO,
      stdio: "ignore",
      windowsHide: true,
      env: Object.assign({}, process.env, { CONFIG_DIR: configDir }),
    }
  );

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

  const client = await cdp(target.webSocketDebuggerUrl);
  await client.send("Page.enable");
  await client.send("Runtime.enable");
  await sleep(2500); // let site-config.json fetch, sidecar spawn/interpreter probing, and settings wiring settle

  return { child, client };
}

async function evalJSON(client, expression) {
  const result = await client.send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  if (result.exceptionDetails) {
    throw new Error("Renderer threw: " + JSON.stringify(result.exceptionDetails));
  }
  return result.result && result.result.value;
}

async function main() {
  const configDir = fs.mkdtempSync(path.join(os.tmpdir(), "mmwe-roundtrip-config-"));
  const outDir = path.resolve(REPO, "docs/huishots/electron");
  fs.mkdirSync(outDir, { recursive: true });

  if (!fs.existsSync(ELECTRON_BIN)) {
    throw new Error(`Electron binary not found at ${ELECTRON_BIN}. Run "npm install" first.`);
  }

  const manifest = { steps: [], failures: [] };

  // --- Pass 1: confirm the bridge is real, then change the theme setting
  // through the exact same settings.set() the settings-panel UI calls, and
  // confirm the sidecar bridge reports the write actually reached Python.
  let userData1 = fs.mkdtempSync(path.join(os.tmpdir(), "mmwe-roundtrip-userdata-1-"));
  let session1 = null;
  try {
    session1 = await launchAndConnect(9334, userData1, configDir);
    const { client } = session1;

    const bridgeCheck = await evalJSON(
      client,
      "JSON.stringify({hasBridge: typeof window.mmweDesktop !== 'undefined', hasSidecar: typeof (window.mmweDesktop && window.mmweDesktop.sidecar && window.mmweDesktop.sidecar.call) === 'function'})"
    );
    const bridge = JSON.parse(bridgeCheck);
    assert(bridge.hasBridge, "window.mmweDesktop must be exposed to the renderer");
    assert(bridge.hasSidecar, "window.mmweDesktop.sidecar.call must be exposed to the renderer");
    manifest.steps.push({ step: "bridge_present", ok: true });

    // Wait for electron-bridge.js's own startup ping/read to settle so our
    // write isn't racing its initial preferences.read.
    await sleep(1200);

    const pingResult = await evalJSON(client, "window.mmweDesktop.sidecar.call('protocol.ping', {}).then(JSON.stringify)");
    const ping = JSON.parse(pingResult);
    assert(ping.ok === true, "a direct sidecar ping through the bridge must succeed: " + pingResult);
    manifest.steps.push({ step: "direct_sidecar_ping", ok: true, result: ping });

    // Drive it exactly the way a user clicking the theme control would:
    // through the site's own settings.set(), not a bypassed direct call.
    // Also drive density and scale -- the two fields this lane widened the
    // bridge to cover beyond theme -- so this proves more than a
    // single-field special case still works.
    const setResult = await evalJSON(
      client,
      "window.AmuletSite.settings.set('theme', 'dark');" +
        "window.AmuletSite.settings.set('density', 'spacious');" +
        "window.AmuletSite.settings.set('scale', 125);" +
        "'ok'"
    );
    assert(setResult === "ok", "settings.set() for theme/density/scale should run without throwing");

    // electron-bridge.js's onChange listener fires the sidecar write
    // asynchronously; give it a moment then confirm via a DIRECT sidecar
    // read (bypassing the site's own cached settings) that Python's
    // preferences file actually has the new values.
    await sleep(1500);
    const confirmResult = await evalJSON(
      client,
      "window.mmweDesktop.sidecar.call('preferences.read', {}).then(JSON.stringify)"
    );
    const confirm = JSON.parse(confirmResult);
    assert(confirm.ok === true, "preferences.read after the settings change must succeed: " + confirmResult);
    assert(
      confirm.result.theme === "dark",
      "the sidecar's own preferences file must show theme=dark after settings.set() -- got " + JSON.stringify(confirm.result)
    );
    assert(
      confirm.result.density === "spacious",
      "the sidecar's own preferences file must show density=spacious after settings.set() -- got " + JSON.stringify(confirm.result)
    );
    assert(
      Math.abs(confirm.result.ui_scale - 1.25) < 1e-6,
      "the sidecar's own preferences file must show ui_scale=1.25 (site scale 125) after settings.set() -- got " + JSON.stringify(confirm.result)
    );
    manifest.steps.push({
      step: "renderer_write_reaches_python",
      ok: true,
      theme: confirm.result.theme,
      density: confirm.result.density,
      ui_scale: confirm.result.ui_scale,
    });
    console.log(
      "Renderer settings.set() -> sidecar preferences: theme=",
      confirm.result.theme,
      "density=",
      confirm.result.density,
      "ui_scale=",
      confirm.result.ui_scale
    );

    const shot = await client.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
    const bytes = Buffer.from(shot.data, "base64");
    assert(bytes.length >= 5000, "capture must not be a blank/near-blank page, got " + bytes.length + " bytes");
    fs.writeFileSync(path.join(outDir, "electron-sidecar-roundtrip-dark.png"), bytes);
    manifest.steps.push({ step: "capture_after_write", ok: true, bytes: bytes.length });

    client.close();
  } finally {
    if (session1) session1.child.kill();
    try {
      fs.rmSync(userData1, { recursive: true, force: true });
    } catch {}
  }

  // --- Pass 2: a fresh app instance (fresh renderer userData, but the SAME
  // CONFIG_DIR) must read the persisted theme back from the sidecar on
  // startup and apply it locally -- proving the value survived a real
  // restart of both processes, not just an in-memory variable.
  let userData2 = fs.mkdtempSync(path.join(os.tmpdir(), "mmwe-roundtrip-userdata-2-"));
  let session2 = null;
  try {
    session2 = await launchAndConnect(9335, userData2, configDir);
    const { client } = session2;
    // Poll rather than a fixed sleep: sidecar interpreter probing/spawn time
    // is not bounded tightly enough for a fixed delay to be reliable.
    let ready = false;
    for (let attempt = 0; attempt < 30 && !ready; attempt++) {
      await sleep(500);
      const s = JSON.parse(await evalJSON(client, "JSON.stringify(window.AmuletSite.electronSidecar)"));
      if (s.available && s.lastSyncedAt) ready = true;
    }

    const debugStatus = await evalJSON(client, "JSON.stringify(window.AmuletSite.electronSidecar)");
    console.log("electronSidecar status on restart:", debugStatus);

    const afterRestart = JSON.parse(
      await evalJSON(
        client,
        "JSON.stringify({theme: window.AmuletSite.settings.get('theme'), density: window.AmuletSite.settings.get('density'), scale: window.AmuletSite.settings.get('scale')})"
      )
    );
    assert(
      afterRestart.theme === "dark",
      "after restarting the app against the same CONFIG_DIR, the site's theme setting must be 'dark' (read from the sidecar on startup), got " +
        JSON.stringify(afterRestart)
    );
    assert(
      afterRestart.density === "spacious",
      "after restarting the app, the site's density setting must be 'spacious' (read from the sidecar on startup), got " +
        JSON.stringify(afterRestart)
    );
    assert(
      afterRestart.scale === 125,
      "after restarting the app, the site's scale setting must be 125 (read from the sidecar's ui_scale on startup), got " +
        JSON.stringify(afterRestart)
    );
    manifest.steps.push({ step: "preferences_survive_restart", ok: true, ...afterRestart });
    console.log("After restart, site settings =", afterRestart);

    client.close();
  } finally {
    if (session2) session2.child.kill();
    try {
      fs.rmSync(userData2, { recursive: true, force: true });
    } catch {}
  }

  fs.writeFileSync(path.join(outDir, "sidecar-roundtrip-manifest.json"), JSON.stringify(manifest, null, 2));
  try {
    fs.rmSync(configDir, { recursive: true, force: true });
  } catch {}

  console.log("\nFull renderer -> preload -> IPC -> sidecar -> Python -> restart round trip verified.");
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
