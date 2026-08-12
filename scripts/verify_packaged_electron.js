/**
 * Launch the PACKAGED Electron executable (dist/electron/win-unpacked) --
 * not `electron .` on the dev source tree -- headlessly, and prove over the
 * DevTools protocol that the real interface loaded and that the sidecar
 * bridge (window.mmweDesktop) is present from the installed/packaged
 * resource layout. A packaged app resolves paths differently from a dev
 * run, so this is the one check that catches a bridge wired only for
 * `electron .`.
 *
 * Never touches the user's visible desktop: launched with
 * --remote-debugging-port and driven entirely over that port.
 *
 * Usage:
 *   node scripts/verify_packaged_electron.js
 */

const fs = require("fs");
const path = require("path");
const os = require("os");
const { spawn } = require("child_process");

const REPO = path.resolve(__dirname, "..");
const PACKAGED_EXE = path.join(
  REPO,
  "dist",
  "electron",
  "win-unpacked",
  "Material Minecraft Map Editor.exe"
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
  if (!fs.existsSync(PACKAGED_EXE)) {
    throw new Error(
      `Packaged executable not found at ${PACKAGED_EXE}. Run ` +
        "build-electron-installer.bat first."
    );
  }

  const userData = fs.mkdtempSync(
    path.join(os.tmpdir(), "mmwe-electron-packaged-verify-")
  );
  const port = 9344;

  const child = spawn(
    PACKAGED_EXE,
    [
      `--remote-debugging-port=${port}`,
      `--user-data-dir=${userData}`,
      "--disable-gpu",
      "--no-sandbox",
    ],
    {
      cwd: path.dirname(PACKAGED_EXE),
      stdio: "ignore",
      windowsHide: true,
    }
  );

  const result = { ok: false };
  try {
    let target = null;
    for (let attempt = 0; attempt < 100 && !target; attempt++) {
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
        "Packaged Electron never exposed a debugging target for its renderer page."
      );
    }

    const client = await cdp(target.webSocketDebuggerUrl);
    await client.send("Page.enable");
    await client.send("Runtime.enable");
    await sleep(1200);

    const urlResult = await client.send("Runtime.evaluate", {
      expression: "location.href",
    });
    const url = urlResult.result?.value || "";
    result.url = url;
    if (!/index\.html(#.*)?$/i.test(url)) {
      throw new Error(
        `the packaged window loaded an unexpected URL (${url}); expected an index.html bundle`
      );
    }

    const titleResult = await client.send("Runtime.evaluate", {
      expression: "document.title",
    });
    result.title = titleResult.result?.value || "";

    const bridgeResult = await client.send("Runtime.evaluate", {
      expression:
        "JSON.stringify({hasBridge: typeof window.mmweDesktop !== 'undefined', isElectron: window.mmweDesktop && window.mmweDesktop.isElectron === true, keys: window.mmweDesktop ? Object.keys(window.mmweDesktop) : []})",
    });
    const bridge = JSON.parse(bridgeResult.result?.value || "{}");
    result.bridge = bridge;
    if (!bridge.hasBridge || bridge.isElectron !== true) {
      throw new Error(
        "window.mmweDesktop bridge was NOT exposed to the renderer in the " +
          "packaged build -- this is exactly the dev-only-bridge defect this " +
          "check exists to catch."
      );
    }

    const bodyResult = await client.send("Runtime.evaluate", {
      expression: "document.body ? document.body.innerText.length : -1",
    });
    result.bodyTextLength = bodyResult.result?.value;
    if (!(result.bodyTextLength > 0)) {
      throw new Error("document.body has no rendered text -- blank page");
    }

    result.ok = true;
    client.close();
    console.log(JSON.stringify(result, null, 2));
  } catch (err) {
    result.error = String(err && err.message ? err.message : err);
    console.error(JSON.stringify(result, null, 2));
    throw err;
  } finally {
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
