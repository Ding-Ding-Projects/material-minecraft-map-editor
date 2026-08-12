/* The renderer-side half of the Electron <-> Python sidecar connection.
 *
 * This file is the one real call site the electron-migration article says
 * does not exist yet. It only ever does anything when the page is actually
 * running inside the Electron shell (`window.mmweDesktop.sidecar` present);
 * loaded from a plain browser tab or the GitHub Pages site it is a no-op,
 * because there is no sidecar to talk to there.
 *
 * What it wires:
 *  - EVERY writable preference field the sidecar's `preferences.write`
 *    accepts (see `_WRITABLE_PREFERENCE_FIELDS` in
 *    amulet_map_editor/api/sidecar/methods.py) round-trips through the
 *    site's own `Site.settings`, not just theme. On load the sidecar's
 *    current preferences are read and applied locally; from then on, every
 *    local change to a mapped setting is written back so a restart of the
 *    *Python* side sees the same value a restart of the *renderer* side
 *    already persisted itself.
 *  - `converter.formats` is read once at startup and published on
 *    `Site.electronSidecar.converterFormats` so a real converter surface can
 *    read the actual adapter catalog instead of a hand-written list.
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
    converterFormats: null,
  };

  Site.electronSidecar = status;

  if (!bridge || typeof bridge.call !== "function") {
    // Not running inside Electron (or an older shell build without the
    // bridge) -- the site keeps working exactly as it does on GitHub Pages.
    return;
  }

  // Site setting key -> { pref: preference field name, toPref, fromPref }.
  // `toPref`/`fromPref` convert between the site's on-screen representation
  // and the sidecar's stored representation when they are not identical
  // (the site's UI scale is a 100-based percentage; preferences.ui_scale is
  // a 0.8-2.0 float).
  var FIELD_MAP = {
    theme: { pref: "theme" },
    density: { pref: "density" },
    accent: { pref: "accent" },
    font: { pref: "ui_font" },
    language: { pref: "language_mode" },
    funnyEn: { pref: "funny_level_english" },
    funnyYue: { pref: "funny_level_cantonese" },
    emoji: { pref: "show_dialog_emojis" },
    brand: { pref: "display_name" },
    scale: {
      pref: "ui_scale",
      toPref: function (siteValue) {
        var n = Number(siteValue);
        return isFinite(n) ? n / 100 : 1.0;
      },
      fromPref: function (prefValue) {
        var n = Number(prefValue);
        return isFinite(n) ? Math.round(n * 100) : 100;
      },
    },
  };

  var THEME_VALUES = { light: "light", dark: "dark" };

  function applyRemotePreferences(preferences) {
    if (!preferences || typeof preferences !== "object") return;
    Object.keys(FIELD_MAP).forEach(function (siteKey) {
      var mapping = FIELD_MAP[siteKey];
      if (!Object.prototype.hasOwnProperty.call(preferences, mapping.pref)) return;
      var prefValue = preferences[mapping.pref];

      if (siteKey === "theme") {
        // "system" and anything unrecognised: leave the local theme in charge.
        var theme = THEME_VALUES[prefValue];
        if (!theme) return;
        if (Site.settings.get("theme") !== theme) Site.settings.set("theme", theme);
        return;
      }

      var siteValue = mapping.fromPref ? mapping.fromPref(prefValue) : prefValue;
      if (Site.settings.get(siteKey) !== siteValue) {
        Site.settings.set(siteKey, siteValue);
      }
    });
  }

  var writingBack = false;

  function writeRemotePreference(siteKey, siteValue) {
    var mapping = FIELD_MAP[siteKey];
    if (!mapping) return;
    var params = {};
    params[mapping.pref] = mapping.toPref ? mapping.toPref(siteValue) : siteValue;
    bridge
      .call("preferences.write", params)
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

  function loadConverterFormats() {
    bridge
      .call("converter.formats", {})
      .then(function (response) {
        if (response && response.ok && response.result) {
          status.converterFormats = response.result.adapters || [];
        }
      })
      .catch(function () {
        /* Leave converterFormats null; a converter surface must treat that
         * as "unavailable", never as "no adapters exist". */
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
      loadConverterFormats();
      return bridge.call("preferences.read", {});
    })
    .then(function (readResponse) {
      if (!readResponse) return;
      if (readResponse.ok) {
        writingBack = true;
        applyRemotePreferences(readResponse.result);
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
    if (key === null || !Object.prototype.hasOwnProperty.call(FIELD_MAP, key)) return;
    if (writingBack) return;
    if (!status.available) return;
    writeRemotePreference(key, value);
  });
})();
