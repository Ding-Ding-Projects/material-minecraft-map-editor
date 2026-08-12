/**
 * Electron main process for the Material Minecraft Map Editor desktop shell.
 *
 * This process owns exactly one thing at this stage of the migration: a
 * frameless window that loads the already-complete Material 3 renderer at
 * docs/site/index.html. It draws nothing of its own -- the product's UI is
 * that site, unmodified, and this process's whole job is to host it, restore
 * its geometry across restarts, and expose a narrow typed bridge for the
 * window-chrome controls a frameless window needs (the OS default title bar
 * is never shown as product chrome; a later lane wires the on-page buttons to
 * the bridge this file exposes).
 *
 * Code signing is permanently out of scope for this project. This process
 * never requests, discovers, or invokes a signer, and packaging config lives
 * in electron-builder.yml with signing explicitly disabled.
 */

const { app, BrowserWindow, ipcMain, screen } = require("electron");
const path = require("path");
const fs = require("fs");

const { SidecarClient } = require("./sidecar-client");

const REPO_ROOT = path.resolve(__dirname, "..");
const SITE_INDEX = path.join(REPO_ROOT, "docs", "site", "index.html");
const PRELOAD = path.join(__dirname, "preload.js");

// The sidecar is a real Python source tree (amulet_map_editor/), not
// something that can live inside app.asar: `python -m amulet_map_editor.api
// .sidecar` needs a real on-disk cwd it can add to sys.path, and app.asar is
// a virtual archive with no such path. In a dev run REPO_ROOT already
// contains amulet_map_editor/ and works as that cwd unchanged. In a packaged
// build electron-builder.yml copies amulet_map_editor/ via `extraResources`
// to `<resources>/amulet_map_editor` (outside app.asar entirely), so the
// correct cwd there is process.resourcesPath, one level above it -- using
// REPO_ROOT (which resolves *inside* app.asar once packaged) here was
// exactly the defect that left the packaged app's sidecar permanently
// unavailable: every preference, language, changelog, docs, converter and
// world call failed with "sidecar_unavailable" from the moment it shipped.
const PY_SIDECAR_CWD = app.isPackaged ? process.resourcesPath : REPO_ROOT;

// The sidecar client owns spawning/restarting/killing the Python child
// process (amulet_map_editor.api.sidecar) and the request/response
// correlation over its stdio protocol. main.js only ever talks to it
// through this narrow object -- see sidecar-client.js for the process
// lifecycle and timeout handling.
const sidecar = new SidecarClient({ repoRoot: PY_SIDECAR_CWD });

const MIN_WIDTH = 720;
const MIN_HEIGHT = 480;
const DEFAULT_WIDTH = 1440;
const DEFAULT_HEIGHT = 900;

/**
 * Window geometry (size + position) is restored across restarts from a small
 * JSON file in the app's userData directory -- never from the user's project
 * repository, and never synced anywhere. This is deliberately hand-rolled
 * rather than pulling in a dependency: it is one bounded read/write of five
 * numbers and a maximized flag.
 */
function statePath() {
  return path.join(app.getPath("userData"), "window-state.json");
}

function loadWindowState() {
  try {
    const raw = fs.readFileSync(statePath(), "utf8");
    const parsed = JSON.parse(raw);
    if (
      typeof parsed === "object" &&
      parsed !== null &&
      Number.isFinite(parsed.width) &&
      Number.isFinite(parsed.height)
    ) {
      return parsed;
    }
  } catch {
    // No saved state yet, or it is unreadable/corrupt -- fall back to
    // defaults rather than failing the launch.
  }
  return null;
}

function saveWindowState(win) {
  if (!win || win.isDestroyed()) return;
  try {
    const bounds = win.isMaximized() ? win.getNormalBounds() : win.getBounds();
    const state = {
      width: bounds.width,
      height: bounds.height,
      x: bounds.x,
      y: bounds.y,
      maximized: win.isMaximized(),
    };
    fs.mkdirSync(path.dirname(statePath()), { recursive: true });
    fs.writeFileSync(statePath(), JSON.stringify(state), "utf8");
  } catch {
    // Best-effort. Losing the saved geometry once is not worth crashing the
    // app over, and the next successful save corrects it.
  }
}

/**
 * Clamp requested geometry to the usable area of the display it would open
 * on, so a window saved on a larger or since-removed monitor can never open
 * larger than the screen the user actually has, or land off every display.
 */
function clampToUsableArea(state) {
  const displays = screen.getAllDisplays();
  const point = { x: state?.x ?? 0, y: state?.y ?? 0 };
  const display =
    screen.getDisplayNearestPoint(point) || screen.getPrimaryDisplay();
  const usable = display.workArea;

  let width = Math.min(state?.width ?? DEFAULT_WIDTH, usable.width);
  let height = Math.min(state?.height ?? DEFAULT_HEIGHT, usable.height);
  width = Math.max(width, MIN_WIDTH);
  height = Math.max(height, MIN_HEIGHT);
  // MIN_WIDTH/MIN_HEIGHT can still exceed a very small usable area; never let
  // the floor push the window past the screen it is clamped to.
  width = Math.min(width, usable.width);
  height = Math.min(height, usable.height);

  let x = state && Number.isFinite(state.x) ? state.x : undefined;
  let y = state && Number.isFinite(state.y) ? state.y : undefined;
  if (x === undefined || y === undefined) {
    x = Math.round(usable.x + (usable.width - width) / 2);
    y = Math.round(usable.y + (usable.height - height) / 2);
  } else {
    // Keep at least a sliver of the saved position inside the usable area
    // instead of trusting a stale coordinate from a monitor that is gone.
    x = Math.min(Math.max(x, usable.x), usable.x + usable.width - width);
    y = Math.min(Math.max(y, usable.y), usable.y + usable.height - height);
  }

  return { width, height, x, y, maximized: Boolean(state?.maximized) };
}

let mainWindow = null;

function createWindow() {
  const saved = loadWindowState();
  const bounds = clampToUsableArea(saved);

  mainWindow = new BrowserWindow({
    width: bounds.width,
    height: bounds.height,
    x: bounds.x,
    y: bounds.y,
    minWidth: MIN_WIDTH,
    minHeight: MIN_HEIGHT,
    // Frameless: this product draws its own Material title bar. The OS
    // default title bar must never appear as product chrome.
    frame: false,
    show: false,
    backgroundColor: "#121212",
    webPreferences: {
      preload: PRELOAD,
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  if (bounds.maximized) {
    mainWindow.maximize();
  }

  // A verification run must never take the foreground window from whoever is
  // using this machine. The window is still created, still loads, still lays
  // out and is still fully drivable over the DevTools protocol -- it simply is
  // never shown, which is everything an automated check reads and nothing a
  // person would notice.
  //
  // This exists because the alternative was discovered the hard way: a verifier
  // that launches the packaged application with only --remote-debugging-port
  // pops a real window onto the user's desktop every time it runs.
  const headless =
    process.env.AMULET_HEADLESS === "1" ||
    process.argv.includes("--headless") ||
    process.argv.some((arg) => arg.startsWith("--remote-debugging-port"));

  mainWindow.once("ready-to-show", () => {
    if (headless) return;
    mainWindow.show();
  });

  mainWindow.on("maximize", () => broadcastWindowState());
  mainWindow.on("unmaximize", () => broadcastWindowState());

  const persist = () => saveWindowState(mainWindow);
  mainWindow.on("resize", persist);
  mainWindow.on("move", persist);
  mainWindow.on("close", persist);

  // AMULET_VIEWPORT_HARNESS_WORLD is set only by the WebGL2 viewport's own
  // capture script (scripts/capture_viewport_render.js). It swaps the
  // loaded page for docs/site/viewport-harness.html, a proof harness that
  // opens the given world through the real sidecar, meshes a real chunk,
  // and draws it -- it never loads instead of the product's own
  // docs/site/index.html in an ordinary run.
  const viewportHarnessWorld = process.env.AMULET_VIEWPORT_HARNESS_WORLD;
  if (viewportHarnessWorld) {
    const harnessPath = path.join(REPO_ROOT, "docs", "site", "viewport-harness.html");
    mainWindow.loadFile(harnessPath, {
      query: { world: viewportHarnessWorld },
    });
  } else {
    mainWindow.loadFile(SITE_INDEX);
  }

  mainWindow.on("closed", () => {
    mainWindow = null;
  });

  return mainWindow;
}

function broadcastWindowState() {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  mainWindow.webContents.send("window-state-changed", {
    maximized: mainWindow.isMaximized(),
  });
}

// --- Narrow, typed IPC surface for the frameless window's chrome controls.
// The preload script is the only thing allowed to invoke these; nothing here
// is exposed to the renderer directly (see preload.js).

ipcMain.handle("window:minimize", () => {
  mainWindow?.minimize();
});

ipcMain.handle("window:maximizeOrRestore", () => {
  if (!mainWindow) return { maximized: false };
  if (mainWindow.isMaximized()) {
    mainWindow.unmaximize();
  } else {
    mainWindow.maximize();
  }
  return { maximized: mainWindow.isMaximized() };
});

ipcMain.handle("window:close", () => {
  mainWindow?.close();
});

ipcMain.handle("window:isMaximized", () => {
  return Boolean(mainWindow?.isMaximized());
});

ipcMain.handle("app:getVersion", () => app.getVersion());

// --- The sidecar bridge. Exactly one handle, forwarding a bounded
// {method, params} to the SidecarClient and returning its structured
// {ok, result} / {ok:false, error} shape -- never a raw ipcRenderer escape
// hatch, never a way to reach the filesystem or a child process directly
// from the page (see preload.js for the narrow surface this backs).
ipcMain.handle("sidecar:call", (_event, payload) => {
  const method = payload && typeof payload.method === "string" ? payload.method : "";
  const params =
    payload && typeof payload.params === "object" && payload.params !== null
      ? payload.params
      : {};
  return sidecar.call(method, params);
});

// --- The one binary-file bridge, for the WebGL2 viewport.
//
// The sidecar's newline-delimited JSON protocol is right for preferences
// and settings and wrong by an order of magnitude for a chunk's vertex
// data or its texture atlas -- base64-encoding tens of thousands of
// floats into a JSON string is bytes-on-the-wire waste for no benefit.
// "viewport.chunk_mesh" and "viewport.atlas" (see
// amulet_map_editor/api/sidecar/mesh_methods.py) instead write raw bytes
// to a file under the sidecar's own per-process temp directory and return
// that path in their (small) JSON result. This handler is the only way
// the renderer can turn that path into actual bytes: it asks the sidecar
// itself (never the renderer, never a hard-coded guess) what that
// directory is, caches the answer, and refuses to open anything outside
// it -- the sidecar can hand the renderer a chunk mesh, never an arbitrary
// file on the user's disk.
let _viewportTempRoot = null;

async function _resolveViewportTempRoot() {
  if (_viewportTempRoot) return _viewportTempRoot;
  const response = await sidecar.call("viewport.temp_root", {});
  if (response && response.ok && response.result && typeof response.result.path === "string") {
    _viewportTempRoot = response.result.path;
  }
  return _viewportTempRoot;
}

ipcMain.handle("sidecar:readBinary", async (_event, requestPath) => {
  if (typeof requestPath !== "string" || !requestPath) {
    return { ok: false, error: { code: "invalid_params", message: "path must be a non-empty string" } };
  }
  const root = await _resolveViewportTempRoot();
  if (!root) {
    return {
      ok: false,
      error: { code: "sidecar_unavailable", message: "Could not resolve the sidecar's viewport temp directory" },
    };
  }
  const resolvedRoot = path.resolve(root) + path.sep;
  const resolvedRequest = path.resolve(requestPath);
  if (!(resolvedRequest + path.sep).startsWith(resolvedRoot) && resolvedRequest !== path.resolve(root)) {
    return { ok: false, error: { code: "invalid_params", message: "path is outside the viewport temp directory" } };
  }
  try {
    const data = fs.readFileSync(resolvedRequest);
    return { ok: true, result: data };
  } catch (err) {
    return { ok: false, error: { code: "read_failed", message: String(err && err.message ? err.message : err) } };
  }
});

app.whenReady().then(() => {
  sidecar.start();
  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

// The sidecar must never outlive the app -- an orphaned Python process is
// exactly the failure this handler exists to prevent.
app.on("before-quit", () => {
  sidecar.stop();
});

// Never negotiate a permission grant automatically; this app has no need for
// camera/mic/geolocation/notifications from the loaded page today.
app.on("web-contents-created", (_event, contents) => {
  contents.setWindowOpenHandler(() => ({ action: "deny" }));
});
