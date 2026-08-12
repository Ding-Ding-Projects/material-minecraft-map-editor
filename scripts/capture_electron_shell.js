/**
 * Launch the Electron shell headlessly and photograph its window.
 *
 * This is the Electron-side twin of scripts/capture_site_surfaces.js: same
 * approach (drive the real, built artifact over the DevTools protocol,
 * capture bytes, refuse to accept a suspiciously small image), applied to
 * `electron .` instead of a browser loading the site file directly. It
 * proves the frameless window actually opens and actually renders the real
 * docs/site/ bundle through Electron's loadFile, not just that a browser can
 * open that same HTML on its own.
 *
 * It never touches the user's visible desktop: Electron is launched with
 * --remote-debugging-port on an off-screen/headless-safe configuration and
 * driven entirely over that port.
 *
 * Usage:
 *   node scripts/capture_electron_shell.js [--out docs/huishots/electron]
 */

const fs = require("fs");
const path = require("path");
const os = require("os");
const { spawn } = require("child_process");

const REPO = path.resolve(__dirname, "..");
const ELECTRON_BIN = path.join(
  REPO,
  "node_modules",
  "electron",
  "dist",
  "electron.exe"
);

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

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
      return new Promise((resolve, reject) =>
        waiting.set(id, { resolve, reject })
      );
    },
    close: () => socket.close(),
  };
}

async function main() {
  if (!fs.existsSync(ELECTRON_BIN)) {
    throw new Error(
      `Electron binary not found at ${ELECTRON_BIN}. Run "npm install" at ` +
        "the repository root first."
    );
  }

  const outIndex = process.argv.indexOf("--out");
  const outDir = path.resolve(
    REPO,
    outIndex >= 0 ? process.argv[outIndex + 1] : "docs/huishots/electron"
  );
  fs.mkdirSync(outDir, { recursive: true });

  const userData = fs.mkdtempSync(
    path.join(os.tmpdir(), "mmwe-electron-capture-")
  );
  const port = 9333;

  const child = spawn(
    ELECTRON_BIN,
    [
      REPO,
      `--remote-debugging-port=${port}`,
      `--user-data-dir=${userData}`,
      "--disable-gpu",
      "--no-sandbox",
    ],
    {
      cwd: REPO,
      stdio: "ignore",
      windowsHide: true,
    }
  );

  const manifest = { captures: [], failures: [] };
  try {
    let target = null;
    for (let attempt = 0; attempt < 80 && !target; attempt++) {
      try {
        const response = await fetch(`http://127.0.0.1:${port}/json/list`);
        const targets = await response.json();
        target = targets.find(
          (t) => t.type === "page" && !/^devtools:/.test(t.url)
        );
      } catch {
        await sleep(250);
      }
    }
    if (!target) {
      throw new Error(
        "Electron never exposed a debugging target for its renderer page."
      );
    }

    const client = await cdp(target.webSocketDebuggerUrl);
    await client.send("Page.enable");
    await client.send("Runtime.enable");

    // Give the page's own scripts (site-config.json fetch, tab wiring, the
    // dim sum surprise's random draw) time to settle before the shot.
    await sleep(1200);

    const urlResult = await client.send("Runtime.evaluate", {
      expression: "location.href",
    });
    const url = urlResult.result?.value || "";
    if (!/docs[\\/]site[\\/]index\.html/i.test(url) && !/index\.html$/i.test(url)) {
      throw new Error(
        `the window loaded an unexpected URL (${url}); expected the ` +
          "docs/site/index.html bundle"
      );
    }

    const bridgeResult = await client.send("Runtime.evaluate", {
      expression:
        "JSON.stringify({hasBridge: typeof window.mmweDesktop !== 'undefined', isElectron: window.mmweDesktop && window.mmweDesktop.isElectron === true})",
    });
    const bridge = JSON.parse(bridgeResult.result?.value || "{}");
    if (!bridge.hasBridge || bridge.isElectron !== true) {
      throw new Error(
        "window.mmweDesktop bridge was not exposed to the renderer as expected"
      );
    }

    const shot = await client.send("Page.captureScreenshot", {
      format: "png",
      captureBeyondViewport: false,
    });
    const bytes = Buffer.from(shot.data, "base64");
    if (bytes.length < 5000) {
      throw new Error(
        `the capture is only ${bytes.length} bytes, which is a blank or ` +
          "near-blank page rather than the rendered shell"
      );
    }

    const file = "electron-shell-home.png";
    fs.writeFileSync(path.join(outDir, file), bytes);
    manifest.captures.push({
      file,
      alt: "The Electron desktop shell's frameless window, loading the existing docs/site/ Material 3 renderer",
      bytes: bytes.length,
      url,
      bridgeVerified: true,
    });

    console.log(
      `Captured ${file} (${bytes.length} bytes) at ${url}; bridge verified.`
    );

    client.close();
  } catch (err) {
    manifest.failures.push({ error: String(err && err.message ? err.message : err) });
    throw err;
  } finally {
    fs.writeFileSync(
      path.join(outDir, "manifest.json"),
      JSON.stringify(manifest, null, 2)
    );
    child.kill();
    try {
      fs.rmSync(userData, { recursive: true, force: true });
    } catch {
      // best-effort cleanup
    }
  }
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
