/**
 * Drives electron/sidecar-client.js against the real Python sidecar child
 * process -- no Electron, no mocked bridge. This is the seam test for
 * SidecarClient itself: spawn, ping, write a preference, read it back,
 * confirm an unknown method reports a structured error, then stop and
 * confirm every further call reports "unavailable" rather than hanging.
 *
 * A throwaway CONFIG_DIR is set before the child spawns so this never
 * touches a real user's preferences file.
 *
 * Usage: node scripts/verify_sidecar_client.js
 */
const fs = require("fs");
const os = require("os");
const path = require("path");

const REPO = path.resolve(__dirname, "..");
const { SidecarClient } = require(path.join(REPO, "electron", "sidecar-client.js"));

function assert(condition, message) {
  if (!condition) throw new Error("ASSERTION FAILED: " + message);
}

async function main() {
  const configDir = fs.mkdtempSync(path.join(os.tmpdir(), "mmwe-sidecar-verify-"));
  const previousConfigDir = process.env.CONFIG_DIR;
  process.env.CONFIG_DIR = configDir;

  const client = new SidecarClient({ repoRoot: REPO, callTimeoutMs: 10000 });
  client.start();

  try {
    // Give the interpreter-probing loop a moment to land on a working
    // "python"/"py -3.11" candidate and for the child to start reading stdin.
    let ping = null;
    for (let attempt = 0; attempt < 40 && (!ping || !ping.ok); attempt++) {
      ping = await client.call("protocol.ping", {});
      if (!ping.ok) await new Promise((r) => setTimeout(r, 250));
    }
    assert(ping && ping.ok, "protocol.ping should succeed once the sidecar is up: " + JSON.stringify(ping));
    assert(ping.result && ping.result.ok === true, "protocol.ping result shape");
    console.log("protocol.ping ->", JSON.stringify(ping.result));

    const written = await client.call("preferences.write", { theme: "dark" });
    assert(written.ok, "preferences.write should succeed: " + JSON.stringify(written));
    assert(written.result.theme === "dark", "written theme should be dark");
    console.log("preferences.write({theme: 'dark'}) -> theme =", written.result.theme);

    const read = await client.call("preferences.read", {});
    assert(read.ok, "preferences.read should succeed: " + JSON.stringify(read));
    assert(read.result.theme === "dark", "round-tripped theme should still be dark");
    console.log("preferences.read() -> theme =", read.result.theme);

    const unknown = await client.call("not.a.real.method", {});
    assert(!unknown.ok, "an unknown method must report a structured error, not succeed");
    assert(unknown.error && unknown.error.code === "unknown_method", "expected unknown_method, got " + JSON.stringify(unknown.error));
    console.log("not.a.real.method -> structured error", JSON.stringify(unknown.error));

    client.stop();

    const afterStop = await client.call("protocol.ping", {});
    assert(!afterStop.ok, "a call after stop() must report unavailable, not hang or succeed");
    console.log("call after stop() -> ", JSON.stringify(afterStop.error));

    console.log("\nAll sidecar-client.js round-trip checks passed against the real Python sidecar.");
  } finally {
    client.stop();
    if (previousConfigDir === undefined) delete process.env.CONFIG_DIR;
    else process.env.CONFIG_DIR = previousConfigDir;
    try {
      fs.rmSync(configDir, { recursive: true, force: true });
    } catch {
      // best-effort cleanup
    }
  }
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
