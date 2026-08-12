/**
 * Preload script -- the only bridge between the sandboxed renderer (the
 * existing docs/site/ bundle) and the main process.
 *
 * contextIsolation is ON and nodeIntegration is OFF in electron/main.js, so
 * this file does not expose ipcRenderer, Node built-ins, or anything else
 * wholesale. It exposes one narrow, typed object -- window.mmweDesktop --
 * carrying only the window-chrome actions a frameless window needs and a
 * version readout. Every entry point is a one-line wrapper around a single
 * ipcMain.handle in main.js; nothing here reaches the filesystem, network,
 * or child processes directly.
 */

const { contextBridge, ipcRenderer } = require("electron");

const ALLOWED_STATE_EVENTS = ["window-state-changed"];

contextBridge.exposeInMainWorld("mmweDesktop", {
  isElectron: true,

  window: {
    minimize: () => ipcRenderer.invoke("window:minimize"),
    maximizeOrRestore: () => ipcRenderer.invoke("window:maximizeOrRestore"),
    close: () => ipcRenderer.invoke("window:close"),
    isMaximized: () => ipcRenderer.invoke("window:isMaximized"),
    /**
     * Subscribe to maximize/unmaximize changes driven from outside the page
     * (double-clicking the title bar area, OS snap, etc). Returns an
     * unsubscribe function. Only a fixed, known-safe set of channel names is
     * ever wired up -- the callback never receives an arbitrary IPC event.
     */
    onStateChanged: (callback) => {
      if (typeof callback !== "function") return () => {};
      const channel = "window-state-changed";
      if (!ALLOWED_STATE_EVENTS.includes(channel)) return () => {};
      const listener = (_event, state) => callback(state);
      ipcRenderer.on(channel, listener);
      return () => ipcRenderer.removeListener(channel, listener);
    },
  },

  app: {
    getVersion: () => ipcRenderer.invoke("app:getVersion"),
  },

  /**
   * The narrow bridge to the Python sidecar (see
   * amulet_map_editor/api/sidecar/). `call` forwards a method name and a
   * plain-object params bag to `ipcMain.handle("sidecar:call", ...)` and
   * always resolves -- it never throws and never hangs the caller past the
   * main process's own request timeout. The renderer never gets
   * `ipcRenderer` itself, a raw child process, or filesystem access: this
   * one method is the entire surface.
   *
   * Resolves to either `{ok: true, result}` or
   * `{ok: false, error: {code, message}}`; the caller branches on `ok`
   * rather than on a thrown exception.
   */
  sidecar: {
    call: (method, params) => {
      if (typeof method !== "string" || !method) {
        return Promise.resolve({
          ok: false,
          error: { code: "invalid_params", message: "'method' must be a non-empty string" },
        });
      }
      var safeParams =
        params && typeof params === "object" && !Array.isArray(params) ? params : {};
      return ipcRenderer.invoke("sidecar:call", { method: method, params: safeParams });
    },
    /**
     * Read a binary file the sidecar itself wrote (a chunk mesh, a texture
     * atlas) as a Node Buffer -- structured-cloned to the renderer as a
     * Uint8Array. main.js refuses any path outside the sidecar's own
     * viewport temp directory (see "sidecar:readBinary" there), so this is
     * not a general filesystem-read primitive: it only ever returns bytes
     * the sidecar generated for this purpose.
     */
    readBinary: (filePath) => {
      if (typeof filePath !== "string" || !filePath) {
        return Promise.resolve({
          ok: false,
          error: { code: "invalid_params", message: "'path' must be a non-empty string" },
        });
      }
      return ipcRenderer.invoke("sidecar:readBinary", filePath);
    },
  },
});
