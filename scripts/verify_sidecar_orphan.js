/**
 * Proves the Python sidecar does not outlive its Electron parent.
 *
 * Two scenarios, both against the REAL packaged app (electron/main.js,
 * unmodified, launched exactly the way a user's shortcut would launch it --
 * headless only via AMULET_HEADLESS=1 per this repository's never-steal-
 * focus rule):
 *
 *   1. graceful quit -- close the one window through the same
 *      window.mmweDesktop.window.close() a user's titlebar click would call.
 *      That triggers Electron's "window-all-closed" -> app.quit() ->
 *      "before-quit" -> sidecar.stop() path in main.js, which should kill
 *      the Python child before the process exits.
 *
 *   2. hard kill -- terminate the Electron main process itself with no
 *      chance to run its own quit handlers (taskkill /F), the way a crash
 *      or "End Task" would. Node's child_process.spawn() on Windows does
 *      not put children in a Job Object by default, so nothing guarantees
 *      the sidecar dies with its parent in this path; this scenario exists
 *      to PROVE that fact rather than assume it.
 *
 * Both scenarios: launch, resolve the sidecar's real PID via a live
 * "protocol.ping"-adjacent call is not enough (that only proves the
 * sidecar answered, not its PID) -- instead the sidecar's PID is resolved
 * from the OS process tree (Win32_Process filtered by ParentProcessId),
 * which is the only source of truth for "is this child still alive and
 * whose child was it".
 *
 * Usage: node scripts/verify_sidecar_orphan.js
 * Exit code 0 and "ALL SIDECAR ORPHAN CHECKS PASSED" on success.
 */

const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawn, execFileSync } = require("child_process");

const REPO = path.resolve(__dirname, "..");
const ELECTRON_BIN = path.join(REPO, "node_modules", "electron", "dist", "electron.exe");

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function assert(condition, message) {
  if (!condition) throw new Error("ASSERTION FAILED: " + message);
}

/** Real child PIDs of `pid` whose process name looks like a Python
 * interpreter, read straight from the OS process table via PowerShell's
 * CIM cmdlet -- not inferred, not guessed. */
function pythonChildPids(pid) {
  const script =
    "Get-CimInstance Win32_Process -Filter \"ParentProcessId=" +
    pid +
    "\" | Where-Object { $_.Name -match '^(py|python|python3|python3\\.11)\\.exe$' } | " +
    "Select-Object -ExpandProperty ProcessId";
  let out;
  try {
    out = execFileSync("powershell.exe", ["-NoProfile", "-NonInteractive", "-Command", script], {
      encoding: "utf8",
      timeout: 15000,
    });
  } catch {
    return [];
  }
  return out
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => /^\d+$/.test(line))
    .map((line) => Number(line));
}

function processAlive(pid) {
  try {
    // signal 0 does not kill anything; it only checks existence/permission.
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

async function waitUntil(predicate, timeoutMs, intervalMs = 250) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    if (predicate()) return true;
    await sleep(intervalMs);
  }
  return predicate();
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

async function evalJSON(client, expression) {
  const result = await client.send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  if (result.exceptionDetails) {
    throw new Error("Renderer threw: " + JSON.stringify(result.exceptionDetails));
  }
  return result.result && result.result.value;
}

async function launchApp(port, userData, configDir) {
  const child = spawn(
    ELECTRON_BIN,
    [REPO, `--remote-debugging-port=${port}`, `--user-data-dir=${userData}`, "--disable-gpu", "--no-sandbox"],
    {
      cwd: REPO,
      stdio: "ignore",
      windowsHide: true,
      env: Object.assign({}, process.env, { CONFIG_DIR: configDir, AMULET_HEADLESS: "1" }),
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

  return { child, client };
}

async function findSidecarPid(electronPid) {
  let pids = [];
  await waitUntil(() => {
    pids = pythonChildPids(electronPid);
    return pids.length > 0;
  }, 20000, 500);
  return pids;
}

async function main() {
  if (!fs.existsSync(ELECTRON_BIN)) {
    throw new Error(`Electron binary not found at ${ELECTRON_BIN}. Run "npm install" first.`);
  }

  const report = { scenarios: [] };

  // --- Scenario 1: graceful quit through the real window-close IPC path.
  {
    const configDir = fs.mkdtempSync(path.join(os.tmpdir(), "mmwe-orphan-config-1-"));
    const userData = fs.mkdtempSync(path.join(os.tmpdir(), "mmwe-orphan-userdata-1-"));
    let session = null;
    try {
      session = await launchApp(9420, userData, configDir);
      const electronPid = session.child.pid;

      // Let the bridge finish loading and the sidecar interpreter probe
      // settle before asking for its PID.
      await sleep(1000);
      const bridgeReady = await evalJSON(
        client_or_session(session),
        "typeof window.mmweDesktop !== 'undefined' && typeof window.mmweDesktop.sidecar !== 'undefined'"
      );
      assert(bridgeReady === true, "window.mmweDesktop.sidecar must be present before this test can proceed");

      const ping = JSON.parse(
        await evalJSON(session.client, "window.mmweDesktop.sidecar.call('protocol.ping', {}).then(JSON.stringify)")
      );
      assert(ping.ok === true, "the sidecar must answer a ping before we look for its process: " + JSON.stringify(ping));

      const sidecarPids = await findSidecarPid(electronPid);
      assert(
        sidecarPids.length > 0,
        `expected at least one Python child process of Electron PID ${electronPid}; found none. ` +
          "Either the sidecar never spawned, or it is not a direct child of the Electron main process."
      );
      console.log("Scenario 1 (graceful quit): Electron pid=" + electronPid + " sidecar pid(s)=" + sidecarPids.join(","));

      // The real user path: window.mmweDesktop.window.close() -> IPC
      // "window:close" -> mainWindow.close() -> "closed" ->
      // "window-all-closed" -> app.quit() -> "before-quit" -> sidecar.stop().
      await evalJSON(session.client, "window.mmweDesktop.window.close(); 'closed-requested'");

      const electronExited = await waitUntil(() => !processAlive(electronPid), 15000, 250);
      assert(electronExited, `Electron main process (pid ${electronPid}) did not exit within 15s of a graceful window close`);

      const sidecarGone = await waitUntil(
        () => sidecarPids.every((pid) => !processAlive(pid)),
        5000,
        250
      );
      report.scenarios.push({
        name: "graceful_quit",
        electronPid,
        sidecarPids,
        sidecarGone,
      });
      assert(
        sidecarGone,
        `After a graceful window close and Electron exit, the sidecar process(es) ${sidecarPids.join(",")} ` +
          "were still alive. before-quit -> sidecar.stop() failed to kill the Python child."
      );
      console.log("Scenario 1 PASSED: sidecar pid(s) " + sidecarPids.join(",") + " are gone after graceful quit.");
    } finally {
      if (session && session.child && !session.child.killed) {
        try {
          session.child.kill();
        } catch {}
      }
      try {
        fs.rmSync(userData, { recursive: true, force: true });
      } catch {}
      try {
        fs.rmSync(configDir, { recursive: true, force: true });
      } catch {}
    }
  }

  // --- Scenario 2: a hard kill of the parent (crash / "End Task"), which
  // gives Electron's own quit handlers no chance to run at all.
  {
    const configDir = fs.mkdtempSync(path.join(os.tmpdir(), "mmwe-orphan-config-2-"));
    const userData = fs.mkdtempSync(path.join(os.tmpdir(), "mmwe-orphan-userdata-2-"));
    let session = null;
    try {
      session = await launchApp(9421, userData, configDir);
      const electronPid = session.child.pid;

      await sleep(1000);
      const ping = JSON.parse(
        await evalJSON(session.client, "window.mmweDesktop.sidecar.call('protocol.ping', {}).then(JSON.stringify)")
      );
      assert(ping.ok === true, "the sidecar must answer a ping before we look for its process: " + JSON.stringify(ping));

      const sidecarPids = await findSidecarPid(electronPid);
      assert(sidecarPids.length > 0, `expected at least one Python child process of Electron PID ${electronPid}; found none.`);
      console.log("Scenario 2 (hard kill): Electron pid=" + electronPid + " sidecar pid(s)=" + sidecarPids.join(","));

      // Hard-kill ONLY the Electron main process itself -- deliberately no
      // "/T" (which would kill the whole process tree, including the
      // sidecar, and prove nothing about whether Windows ties the
      // sidecar's lifetime to its parent on its own). No before-quit, no
      // sidecar.stop(), nothing but the OS tearing down that one process.
      try {
        execFileSync("taskkill", ["/PID", String(electronPid), "/F"], { timeout: 10000 });
      } catch {
        // taskkill can exit non-zero if the process already exited; what
        // matters is whether electronPid itself is gone, checked below.
      }

      const electronExited = await waitUntil(() => !processAlive(electronPid), 5000, 250);
      assert(electronExited, `Electron main process (pid ${electronPid}) survived taskkill /F`);

      const sidecarGoneAfterHardKill = await waitUntil(
        () => sidecarPids.every((pid) => !processAlive(pid)),
        5000,
        250
      );
      report.scenarios.push({
        name: "hard_kill",
        electronPid,
        sidecarPids,
        sidecarGone: sidecarGoneAfterHardKill,
      });
      if (!sidecarGoneAfterHardKill) {
        // Clean up what the OS did not, then report this as the honest,
        // reproducible finding it is rather than pretending it passed.
        for (const pid of sidecarPids) {
          if (processAlive(pid)) {
            try {
              execFileSync("taskkill", ["/PID", String(pid), "/F"], { timeout: 5000 });
            } catch {}
          }
        }
        throw new Error(
          `ORPHAN CONFIRMED: after taskkill /F on the Electron main process (pid ${electronPid}), ` +
            `sidecar process(es) ${sidecarPids.join(",")} were still running. ` +
            "child_process.spawn() on Windows does not place children in a Job Object, so a hard kill " +
            "of the parent does not take the Python sidecar down with it. This is a real defect in " +
            "electron/sidecar-client.js's process lifecycle (not owned by this lane) -- it needs a " +
            "Windows Job Object (or an equivalent watchdog) so the sidecar is tied to its parent's " +
            "lifetime even when the parent cannot run its own before-quit handler."
        );
      }
      console.log("Scenario 2 PASSED: sidecar pid(s) " + sidecarPids.join(",") + " are gone after a hard kill of the parent.");
    } finally {
      if (session && session.child && !session.child.killed) {
        try {
          session.child.kill();
        } catch {}
      }
      try {
        fs.rmSync(userData, { recursive: true, force: true });
      } catch {}
      try {
        fs.rmSync(configDir, { recursive: true, force: true });
      } catch {}
    }
  }

  console.log("\n" + JSON.stringify(report, null, 2));
  console.log("\nALL SIDECAR ORPHAN CHECKS PASSED");
}

// Tiny helper purely so scenario 1's early assertion reads naturally above
// (kept local rather than restructuring the whole file around it).
function client_or_session(session) {
  return session.client;
}

main().catch((err) => {
  console.error(err && err.message ? err.message : err);
  process.exitCode = 1;
});
