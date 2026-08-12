/* The renderer-side half of the Electron <-> Python sidecar connection.
 *
 * This file is the one real call site the electron-migration article says
 * does not exist yet. It only ever does anything when the page is actually
 * running inside the Electron shell (`window.mmweDesktop.sidecar` present);
 * loaded from a plain browser tab or the GitHub Pages site it is a no-op,
 * because there is no sidecar to talk to there.
 *
 * What it wires: the site's own `theme` setting (already a first-class
 * settings-panel control) round-trips through the sidecar's
 * `preferences.read` / `preferences.write` methods instead of staying
 * purely local-storage-only. On load it reads the sidecar's current theme
 * and applies it; from then on, every local theme change is written back to
 * the sidecar's preferences file so a restart of the *Python* side sees the
 * same value a restart of the *renderer* side already persisted itself.
 */
(function () {
  "use strict";

  var Site = window.AmuletSite;
  if (!Site) return;

  var bridge = window.mmweDesktop && window.mmweDesktop.sidecar;

  var status = {
    available: false,
    lastError: null,
    lastSyncedAt: null,
  };

  Site.electronSidecar = status;

  if (!bridge || typeof bridge.call !== "function") {
    // Not running inside Electron (or an older shell build without the
    // bridge) -- the site keeps working exactly as it does on GitHub Pages.
    return;
  }

  var THEME_VALUES = { light: "light", dark: "dark" };

  function applyRemoteTheme(preferences) {
    if (!preferences || typeof preferences.theme !== "string") return;
    var theme = THEME_VALUES[preferences.theme];
    if (!theme) return; // "system" and anything unrecognised: leave local in charge
    if (Site.settings.get("theme") !== theme) {
      Site.settings.set("theme", theme);
    }
  }

  var writingBack = false;

  function writeRemoteTheme(theme) {
    if (!THEME_VALUES[theme]) return;
    bridge
      .call("preferences.write", { theme: theme })
      .then(function (response) {
        if (response && response.ok) {
          status.lastError = null;
          status.lastSyncedAt = Date.now();
        } else {
          status.lastError = (response && response.error) || { code: "unknown_error" };
        }
      })
      .catch(function (err) {
        status.lastError = { code: "bridge_exception", message: String(err) };
      });
  }

  bridge
    .call("protocol.ping", {})
    .then(function (pingResponse) {
      if (!pingResponse || !pingResponse.ok) {
        status.available = false;
        status.lastError = (pingResponse && pingResponse.error) || {
          code: "sidecar_unavailable",
        };
        return null;
      }
      status.available = true;
      return bridge.call("preferences.read", {});
    })
    .then(function (readResponse) {
      if (!readResponse) return;
      if (readResponse.ok) {
        writingBack = true;
        applyRemoteTheme(readResponse.result);
        writingBack = false;
        status.lastSyncedAt = Date.now();
      } else {
        status.lastError = readResponse.error;
      }
    })
    .catch(function (err) {
      status.available = false;
      status.lastError = { code: "bridge_exception", message: String(err) };
    });

  Site.settings.onChange(function (key, value) {
    if (key !== "theme" || writingBack) return;
    if (!status.available) return;
    writeRemoteTheme(value);
  });
})();
