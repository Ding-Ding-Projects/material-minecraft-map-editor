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

const REPO_ROOT = path.resolve(__dirname, "..");
const SITE_INDEX = path.join(REPO_ROOT, "docs", "site", "index.html");
const PRELOAD = path.join(__dirname, "preload.js");

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

  mainWindow.once("ready-to-show", () => {
    mainWindow.show();
  });

  mainWindow.on("maximize", () => broadcastWindowState());
  mainWindow.on("unmaximize", () => broadcastWindowState());

  const persist = () => saveWindowState(mainWindow);
  mainWindow.on("resize", persist);
  mainWindow.on("move", persist);
  mainWindow.on("close", persist);

  mainWindow.loadFile(SITE_INDEX);

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

app.whenReady().then(() => {
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

// Never negotiate a permission grant automatically; this app has no need for
// camera/mic/geolocation/notifications from the loaded page today.
app.on("web-contents-created", (_event, contents) => {
  contents.setWindowOpenHandler(() => ({ action: "deny" }));
});
