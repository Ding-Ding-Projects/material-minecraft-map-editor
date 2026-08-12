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
 *  - `world.fill` / `world.replace` / `world.undo` / `world.redo` /
 *    `world.save` are exposed as `Site.electronSidecar.fillSelection(...)`,
 *    `.replaceInSelection(...)`, `.undoEdit(...)`, `.redoEdit(...)` and
 *    `.saveWorld(...)` -- the real write path against the world the sidecar
 *    has open, called against the viewport panel's own selection rather
 *    than reimplemented as a second copy of "what is selected" in this
 *    file. Parameter names here match
 *    `amulet_map_editor/api/sidecar/edit_methods.py` exactly: selection
 *    points are `min`/`max` (not `point1`/`point2`), the confirmation flag
 *    is `confirm` (not `confirmed`), and replace takes `original_block` /
 *    `replacement_block` (not `find_block`/`replace_block`) -- the sidecar
 *    lane landed with those names, and this file was updated to match
 *    rather than left pointing at names that only ever existed in a
 *    comment.
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
    // The catalogue was reachable and the action was not: converterFormats
    // listed sixteen adapters while nothing in the renderer could ask for a
    // single conversion. Exposed here so a converter surface can actually run
    // one rather than describe one.
    convert: convertFile,
    // The world-edit write path. Each of these is a real bridge.call() site
    // against the sidecar's world.* methods -- never a flag this file sets
    // to true on the caller's behalf. `confirmed` must come from a real user
    // decision made in the interface (the destructive-action confirm gate),
    // not a default supplied here.
    fillSelection: fillSelection,
    replaceInSelection: replaceInSelection,
    undoEdit: undoEdit,
    redoEdit: redoEdit,
    saveWorld: saveWorld,
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
        var theme = THEME_VALUES[prefValue];
        if (!theme) {
          // Python holds a value this renderer has no way to show -- "system"
          // is a real third state here and the site only has light and dark.
          //
          // Leaving the local theme in charge, which is what this did, opens a
          // hole that stays open: the two stores sit permanently divergent,
          // and because Site.settings.set() returns early when the value is
          // unchanged, a later set() to the value the site ALREADY holds fires
          // no listener and never reaches Python at all. The renderer then
          // looks right, the write looks accepted, and the preferences file
          // never moves.
          //
          // So the explicit local choice is pushed up instead. A value the user
          // actually chose outranks a default the other store happens to be
          // sitting on, and afterwards the two agree, which is the property
          // that makes every later write behave.
          var local = Site.settings.get("theme");
          if (local && THEME_VALUES[local]) writeRemotePreference("theme", local);
          return;
        }
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
  /**
   * Run one conversion through the sidecar.
   *
   * overwrite_confirmed is deliberately NOT defaulted to true here. Overwriting
   * a file the user already has is their decision to make in a surface that
   * tells them, not a default a bridge quietly supplies on their behalf.
   */
  function convertFile(sourcePath, adapterId, destinationPath, overwriteConfirmed) {
    return bridge
      .call("converter.convert", {
        source_path: sourcePath,
        adapter_id: adapterId,
        destination_path: destinationPath,
        overwrite_confirmed: Boolean(overwriteConfirmed),
      })
      .then(function (response) {
        if (!response || !response.ok) {
          throw new Error(
            (response && response.error && response.error.message) ||
              "converter.convert failed"
          );
        }
        return response.result;
      });
  }

  function callWorldMethod(method, params) {
    return bridge.call(method, params).then(function (response) {
      if (!response || !response.ok) {
        throw new Error(
          (response && response.error && response.error.message) || method + " failed"
        );
      }
      return response.result;
    });
  }

  /**
   * Fill the given selection with one block.
   *
   * `confirmed` is deliberately NOT defaulted to true, exactly like
   * `convertFile`'s `overwriteConfirmed` above -- writing blocks into a
   * world the user has open is their decision, made in the confirm gate,
   * not a default this bridge quietly supplies. It is sent to the sidecar
   * as `confirm`, the field name `edit_methods.py`'s `_require_confirm`
   * actually reads.
   */
  function fillSelection(worldId, dimension, min, max, block, confirmed) {
    return callWorldMethod("world.fill", {
      world_id: worldId,
      dimension: dimension,
      min: min,
      max: max,
      block: block,
      confirm: Boolean(confirmed),
    });
  }

  /** Replace every matching block within the selection with another. */
  function replaceInSelection(worldId, dimension, min, max, originalBlock, replacementBlock, confirmed) {
    return callWorldMethod("world.replace", {
      world_id: worldId,
      dimension: dimension,
      min: min,
      max: max,
      original_block: originalBlock,
      replacement_block: replacementBlock,
      confirm: Boolean(confirmed),
    });
  }

  /** Undo the most recent edit against this world. Not gated: undoing is the
   * un-destructive direction, and `world.undo` takes no `confirm` field. */
  function undoEdit(worldId) {
    return callWorldMethod("world.undo", { world_id: worldId });
  }

  /** Redo the most recently undone edit against this world. */
  function redoEdit(worldId) {
    return callWorldMethod("world.redo", { world_id: worldId });
  }

  /** Save the open world to disk. `confirmed` follows the same rule as the
   * edit methods above -- a real user decision, never a default. */
  function saveWorld(worldId, confirmed) {
    return callWorldMethod("world.save", { world_id: worldId, confirm: Boolean(confirmed) });
  }

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

  /**
   * Ping until the sidecar answers, rather than judging it once.
   *
   * The renderer finishes loading before the Python child process has finished
   * starting, so a single ping at page load routinely arrives too early. The
   * bridge then recorded "the sidecar process is not running", set
   * `available` to false, and never asked again -- and because every write is
   * gated on that flag, EVERY preference change for the rest of the session was
   * silently dropped. Nothing reported an error: the renderer applied the
   * change, the interface updated, the value persisted in browser storage, and
   * Python simply never heard about any of it.
   *
   * It was not that the sidecar was missing. Calling it directly from the same
   * page a second later worked perfectly. The bridge had only asked at the one
   * moment the answer was no.
   *
   * Bounded on purpose: a sidecar that genuinely never starts must end up
   * reported as unavailable rather than retried forever behind a spinner.
   */
  function pingUntilReady(attemptsLeft, delayMs) {
    return bridge.call("protocol.ping", {}).then(function (response) {
      if (response && response.ok) return response;
      if (attemptsLeft <= 0) return response;
      return new Promise(function (resolve) {
        setTimeout(resolve, delayMs);
      }).then(function () {
        return pingUntilReady(attemptsLeft - 1, Math.min(delayMs * 2, 2000));
      });
    });
  }

  pingUntilReady(8, 250)
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
