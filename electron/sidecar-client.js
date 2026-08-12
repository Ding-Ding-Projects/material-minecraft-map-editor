/**
 * Owns the Python sidecar child process's whole lifetime and the
 * request/response correlation over its newline-delimited JSON stdio
 * protocol (see amulet_map_editor/api/sidecar/protocol.py).
 *
 * Everything this module promises:
 *   - spawns `python -m amulet_map_editor.api.sidecar`, trying a short list
 *     of interpreter names so a host without a "python3.11" on PATH still
 *     works if "py -3.11" or "python" resolves to something usable;
 *   - restarts the child if it dies while the app is still running, so a
 *     transient crash does not permanently strand every future call;
 *   - kills the child (and cancels every in-flight request with a
 *     structured error) on `stop()`, which main.js calls from
 *     `app.on("before-quit")` -- no orphaned interpreter survives the app;
 *   - correlates requests by id, times a request out rather than hanging
 *     the renderer forever, and never lets a bad line or a dead process
 *     throw out of `call()` -- callers always get back either
 *     `{ok: true, result}` or `{ok: false, error: {code, message}}`.
 *
 * This is deliberately not exposed to the renderer directly. preload.js
 * forwards a narrow `sidecar.call(method, params)` over IPC to
 * `ipcMain.handle("sidecar:call", ...)` in main.js, which is the only
 * caller of this module.
 */

const { spawn } = require("child_process");
const readline = require("readline");

// Tried in order; the first one that spawns without erroring out is used
// for the lifetime of the client. "py -3.11" is two tokens (a launcher plus
// an argument), everything else is a single executable name.
const INTERPRETER_CANDIDATES = [
  { command: "py", args: ["-3.11"] },
  { command: "py", args: ["-3"] },
  { command: "python3.11", args: [] },
  { command: "python3", args: [] },
  { command: "python", args: [] },
];

const SIDECAR_MODULE_ARGS = ["-m", "amulet_map_editor.api.sidecar"];

const DEFAULT_CALL_TIMEOUT_MS = 15000;
const RESTART_DELAY_MS = 500;
const MAX_CONSECUTIVE_RESTARTS = 5;

const ERR_SIDECAR_UNAVAILABLE = "sidecar_unavailable";
const ERR_TIMEOUT = "sidecar_timeout";
const ERR_TRANSPORT = "sidecar_transport_error";

class SidecarClient {
  constructor({ repoRoot, callTimeoutMs = DEFAULT_CALL_TIMEOUT_MS } = {}) {
    this._repoRoot = repoRoot;
    this._callTimeoutMs = callTimeoutMs;
    this._child = null;
    this._rl = null;
    this._nextId = 1;
    this._pending = new Map(); // id -> { resolve, timer }
    this._stopped = false;
    this._consecutiveRestarts = 0;
    this._interpreter = null; // the candidate that worked, memoized
  }

  start() {
    this._stopped = false;
    this._spawnOnce();
  }

  _spawnOnce() {
    if (this._stopped) return;

    const candidates = this._interpreter
      ? [this._interpreter]
      : INTERPRETER_CANDIDATES;

    const tryNext = (index) => {
      if (index >= candidates.length) {
        // Nothing on this host can run the sidecar. Every pending and
        // future call is answered with a structured error rather than
        // hanging -- this is a reportable state, not a crash.
        this._interpreter = null;
        return;
      }
      const candidate = candidates[index];
      let child;
      try {
        child = spawn(
          candidate.command,
          [...candidate.args, ...SIDECAR_MODULE_ARGS],
          { cwd: this._repoRoot, stdio: ["pipe", "pipe", "pipe"], windowsHide: true }
        );
      } catch {
        tryNext(index + 1);
        return;
      }

      let settled = false;
      const onEarlyError = () => {
        if (settled) return;
        settled = true;
        tryNext(index + 1);
      };
      child.once("error", onEarlyError);
      // A process that exits within a beat of spawning almost certainly
      // means the interpreter name resolved to nothing runnable; try the
      // next candidate rather than accepting a dead child as "started".
      const earlyExitTimer = setTimeout(() => {
        if (settled) return;
        settled = true;
        this._interpreter = candidate;
        this._attach(child);
      }, 400);
      child.once("exit", () => {
        clearTimeout(earlyExitTimer);
        onEarlyError();
      });
    };

    tryNext(0);
  }

  _attach(child) {
    this._child = child;
    this._consecutiveRestarts = 0;

    this._rl = readline.createInterface({ input: child.stdout });
    this._rl.on("line", (line) => this._onLine(line));

    child.stderr.on("data", () => {
      // The sidecar's own stderr carries diagnostic tracebacks for local
      // debugging only (see server.py); this process never parses or
      // forwards it to the renderer.
    });

    child.on("exit", () => {
      this._child = null;
      if (this._rl) {
        this._rl.close();
        this._rl = null;
      }
      this._failAllPending(ERR_TRANSPORT, "The sidecar process exited");
      if (this._stopped) return;
      if (this._consecutiveRestarts >= MAX_CONSECUTIVE_RESTARTS) return;
      this._consecutiveRestarts += 1;
      setTimeout(() => this._spawnOnce(), RESTART_DELAY_MS);
    });
  }

  _onLine(line) {
    let payload;
    try {
      payload = JSON.parse(line);
    } catch {
      return; // malformed line from the child; nothing sane to correlate
    }
    const pending = this._pending.get(payload.id);
    if (!pending) return;
    this._pending.delete(payload.id);
    clearTimeout(pending.timer);
    if (payload.error) {
      pending.resolve({ ok: false, error: payload.error });
    } else {
      pending.resolve({ ok: true, result: payload.result });
    }
  }

  _failAllPending(code, message) {
    for (const [, pending] of this._pending) {
      clearTimeout(pending.timer);
      pending.resolve({ ok: false, error: { code, message } });
    }
    this._pending.clear();
  }

  /**
   * Send one request and resolve with a structured result -- never throws,
   * never hangs past the configured timeout.
   */
  call(method, params) {
    if (!this._child || !this._child.stdin.writable) {
      return Promise.resolve({
        ok: false,
        error: {
          code: ERR_SIDECAR_UNAVAILABLE,
          message: "The sidecar process is not running",
        },
      });
    }

    const id = this._nextId++;
    const request = { id, method, params: params || {}, protocol_version: 1 };

    return new Promise((resolve) => {
      const timer = setTimeout(() => {
        this._pending.delete(id);
        resolve({
          ok: false,
          error: {
            code: ERR_TIMEOUT,
            message: `No response from the sidecar within ${this._callTimeoutMs}ms`,
          },
        });
      }, this._callTimeoutMs);

      this._pending.set(id, { resolve, timer });

      try {
        this._child.stdin.write(JSON.stringify(request) + "\n");
      } catch (err) {
        this._pending.delete(id);
        clearTimeout(timer);
        resolve({
          ok: false,
          error: { code: ERR_TRANSPORT, message: String(err && err.message ? err.message : err) },
        });
      }
    });
  }

  stop() {
    this._stopped = true;
    this._failAllPending(ERR_SIDECAR_UNAVAILABLE, "The sidecar was stopped");
    if (this._rl) {
      this._rl.close();
      this._rl = null;
    }
    if (this._child) {
      try {
        this._child.kill();
      } catch {
        // best-effort
      }
      this._child = null;
    }
  }

  /** Test/diagnostic helper: is a child process currently attached? */
  isRunning() {
    return this._child !== null;
  }
}

module.exports = { SidecarClient, ERR_SIDECAR_UNAVAILABLE, ERR_TIMEOUT, ERR_TRANSPORT };
