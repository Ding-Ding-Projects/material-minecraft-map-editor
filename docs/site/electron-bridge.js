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
 *  - `changelog.entries` is read once at startup and published on
 *    `Site.electronSidecar.changelogEntries` (the sidecar's real bundled
 *    catalog, with real commit SHAs) instead of the site's own bundled
 *    `changelog-data.js`. This bridge also overwrites `window.AMULET_CHANGELOG`
 *    with the same shape `changelog.js` already reads, so a consuming
 *    surface that reads the global after this script has run sees the real
 *    Python catalog rather than the site-bundled one.
 *  - `docs.articles` is read once at startup and published on
 *    `Site.electronSidecar.docsArticles` -- the real bundled feature
 *    documentation articles from `amulet_map_editor/api/docs_articles.json`,
 *    the same bundle the desktop app's own in-app documentation browser
 *    reads (see `docs/features/sidecar/README.md` for how the two relate).
 *  - `dimsum.draw` is exposed as `Site.electronSidecar.drawDimSum(language)`,
 *    a thin wrapper any surface can call to run the sidecar's *real* 10%
 *    draw (`amulet_map_editor.api.dim_sum_surprise.should_show`) and the
 *    real public catalog fetch, rather than reimplementing the odds or the
 *    catalog parsing in JavaScript.
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
    changelogEntries: null,
    docsArticles: null,
    drawDimSum: drawDimSum,
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

  function loadChangelogEntries() {
    bridge
      .call("changelog.entries", {})
      .then(function (response) {
        if (!response || !response.ok || !response.result) return;
        var result = response.result;
        status.changelogEntries = result.entries || [];
        // The exact shape changelog.js's own catalogueSource() already
        // reads from window.AMULET_CHANGELOG (repository_url,
        // source_revision, entries[]) -- so a surface that reads the global
        // after this script has run sees the sidecar's real catalog instead
        // of the one changelog-data.js bundled for the standalone site.
        window.AMULET_CHANGELOG = {
          repository_url: result.repository_url,
          source_revision: result.source_revision,
          entries: result.entries,
        };
      })
      .catch(function () {
        /* Leave changelogEntries null and window.AMULET_CHANGELOG as the
         * site's own bundled data -- an unreachable sidecar must fall back
         * to the standalone site's behaviour, never render nothing. */
      });
  }

  function loadDocsArticles() {
    bridge
      .call("docs.articles", {})
      .then(function (response) {
        if (response && response.ok && response.result) {
          status.docsArticles = response.result.articles || [];
        }
      })
      .catch(function () {
        /* Leave docsArticles null; a docs surface must treat that as
         * "unavailable", never as "no articles exist". */
      });
  }

  /** Run the sidecar's real dim-sum draw. Resolves to the sidecar's real
   * response shape ({status:"not_drawn"|"unavailable"|"ready", ...}) so a
   * caller sees exactly the same honesty the Python module already has --
   * "unavailable" is a real, distinct outcome from "did not win the draw",
   * never collapsed into a single failure case. Rejects (rather than
   * silently returning null) when the bridge itself is unreachable, so a
   * caller can fall back to the site's own bundled draw. */
  function drawDimSum(languageMode) {
    if (!status.available) {
      return Promise.reject(new Error("sidecar unavailable"));
    }
    return bridge
      .call("dimsum.draw", { language_mode: languageMode || "english" })
      .then(function (response) {
        if (!response || !response.ok) {
          throw new Error((response && response.error && response.error.message) || "dimsum.draw failed");
        }
        return response.result;
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
      loadChangelogEntries();
      loadDocsArticles();
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
