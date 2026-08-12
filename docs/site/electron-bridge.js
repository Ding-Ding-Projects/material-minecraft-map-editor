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
    // Selection.copy/cut/paste/delete and the structure/chunk write path --
    // amulet_map_editor/api/sidecar/selection_methods.py. Same rule as the
    // edit path above: every "confirmed" flag here comes from a real user
    // decision made by the caller, never a default this bridge supplies.
    copySelection: copySelection,
    cutSelection: cutSelection,
    pasteSelection: pasteSelection,
    deleteSelection: deleteSelection,
    clipboardStatus: clipboardStatus,
    exportStructure: exportStructure,
    importStructure: importStructure,
    createChunks: createChunks,
    deleteChunks: deleteChunks,
    pruneChunks: pruneChunks,
    // Universal surfaces: notifications with history, local Git-backed
    // version history, and the external-editor handoff. Each is a real
    // bridge.call() against amulet_map_editor.api.sidecar.surface_methods --
    // see docs/site/studio-surfaces.js for the panel that drives these.
    listNotifications: listNotifications,
    addNotification: addNotification,
    searchNotifications: searchNotifications,
    bulkDismissNotifications: bulkDismissNotifications,
    exportNotifications: exportNotifications,
    listHistoryEvents: listHistoryEvents,
    restoreHistoryEvent: restoreHistoryEvent,
    exportHistory: exportHistory,
    historyRoot: historyRoot,
    discoverEditors: discoverEditors,
    openInExternalEditor: openInExternalEditor,
    selectExternalEditor: selectExternalEditor,
    // The shared local School-mode state (amulet_map_editor.api.school_mode)
    // and the optional, off-by-default TTS narrator
    // (amulet_map_editor.api.tts_narrator). See docs/site/studio-language.js
    // for the settings surface that drives these.
    school: {
      status: function () {
        return schoolCall("school.status");
      },
      setModeName: function (modeName) {
        return schoolCall("school.set_mode_name", { mode_name: modeName });
      },
      resetModeName: function () {
        return schoolCall("school.reset_mode_name");
      },
      setCredential: function (credential) {
        return schoolCall("school.set_credential", { credential: credential });
      },
      enable: function () {
        return schoolCall("school.enable");
      },
      unlock: function (credential) {
        return schoolCall("school.unlock", { credential: credential });
      },
    },
    narrator: {
      read: function () {
        return schoolCall("narrator.read");
      },
      write: function (changes) {
        return schoolCall("narrator.write", changes || {});
      },
    },
    // Appearance presets, per-surface toy locks, and the built-in
    // authenticator (amulet_map_editor.api.appearance_presets / item_locks /
    // authenticator via sidecar/security_methods.py). See docs/site/
    // studio-appearance.js and docs/site/studio-security.js for the panels.
    // No function here reads or stores a secret itself -- the OS credential
    // vault does, on the Python side; a secret crosses this bridge only when
    // creating a lock/entry, exactly once, because the vault must receive it
    // from somewhere.
    appearance: {
      listPresets: function () {
        return schoolCall("appearance.presets.list");
      },
      savePreset: function (name, values, replace) {
        return schoolCall("appearance.presets.save", { name: name, values: values, replace: Boolean(replace) });
      },
      deletePreset: function (name) {
        return schoolCall("appearance.presets.delete", { name: name });
      },
      applyPreset: function (name) {
        return schoolCall("appearance.presets.apply", { name: name });
      },
      exportPreset: function (name) {
        return schoolCall("appearance.presets.export", { name: name });
      },
      importPreset: function (payload, replace) {
        return schoolCall("appearance.presets.import", { payload: payload, replace: Boolean(replace) });
      },
      resetProperty: function (propertyName) {
        return schoolCall("appearance.reset_property", { property: propertyName });
      },
      resetAll: function () {
        return schoolCall("appearance.reset_all");
      },
    },
    locks: {
      list: function () {
        return schoolCall("locks.list");
      },
      create: function (scope, targetId, label, method, credential, options) {
        var params = {
          scope: scope,
          target_id: targetId,
          label: label,
          method: method,
          unlock_duration: (options && options.unlockDuration) || "surface",
          locked_on_launch: !options || options.lockedOnLaunch !== false,
        };
        if (method === "totp") params.totp_secret = credential;
        else params.password = credential;
        return schoolCall("locks.create", params);
      },
      attemptUnlock: function (lockId, answer) {
        return schoolCall("locks.attempt_unlock", { lock_id: lockId, answer: answer });
      },
      relock: function (lockId) {
        return schoolCall("locks.relock", { lock_id: lockId });
      },
      remove: function (lockId) {
        return schoolCall("locks.remove", { lock_id: lockId });
      },
      changeCredential: function (lockId, method, credential) {
        var params = { lock_id: lockId };
        if (method === "totp") params.totp_secret = credential;
        else params.password = credential;
        return schoolCall("locks.change_credential", params);
      },
      generateTotpSecret: function () {
        return schoolCall("locks.generate_totp_secret");
      },
    },
    authenticator: {
      listEntries: function () {
        return schoolCall("auth.list_entries");
      },
      generateSecret: function (length) {
        return schoolCall("auth.generate_secret", { length: length });
      },
      buildUri: function (issuer, account, secret, options) {
        var params = { issuer: issuer, account: account, secret: secret };
        if (options) {
          if (options.algorithm) params.algorithm = options.algorithm;
          if (options.digits) params.digits = options.digits;
          if (options.period) params.period = options.period;
        }
        return schoolCall("auth.build_uri", params);
      },
      addEntry: function (issuer, account, secret, options) {
        var params = { issuer: issuer, account: account, secret: secret };
        if (options) {
          if (options.algorithm) params.algorithm = options.algorithm;
          if (options.digits) params.digits = options.digits;
          if (options.period) params.period = options.period;
        }
        return schoolCall("auth.add_entry", params);
      },
      renameEntry: function (entryId, issuer, account) {
        return schoolCall("auth.rename_entry", { entry_id: entryId, issuer: issuer, account: account });
      },
      deleteEntry: function (entryId) {
        return schoolCall("auth.delete_entry", { entry_id: entryId });
      },
      currentCode: function (entryId) {
        return schoolCall("auth.current_code", { entry_id: entryId });
      },
      // Metadata-only export -- the sidecar's own row omits the secret and
      // says so. There is deliberately no bridge call for the
      // secrets-included export; that path belongs behind the
      // super-confirmation gate in studio-security.js, never a plain call.
      exportEntries: function () {
        return schoolCall("auth.export");
      },
      clockWarning: function (assumedOffsetSeconds) {
        return schoolCall("auth.clock_warning", { assumed_offset_seconds: assumedOffsetSeconds || 0 });
      },
    },
    // The Analyze ribbon tab's read-only reporting path --
    // amulet_map_editor/api/sidecar/analyze_methods.py. Every one of these
    // is strictly read-only (never writes, never touches undo/redo), so
    // unlike fillSelection/replaceInSelection above there is no `confirm`
    // flag to thread through here. See docs/site/studio-workspace.js's
    // "analyze" ribbon tab for the caller.
    analyze: {
      blockHistogram: function (worldId, dimension, min, max) {
        return callWorldMethod("analyze.block_histogram", {
          world_id: worldId,
          dimension: dimension,
          min: min,
          max: max,
        });
      },
      chunkInventory: function (worldId, dimension, min, max) {
        return callWorldMethod("analyze.chunk_inventory", {
          world_id: worldId,
          dimension: dimension,
          min: min,
          max: max,
        });
      },
      entityCounts: function (worldId, dimension, min, max) {
        return callWorldMethod("analyze.entity_counts", {
          world_id: worldId,
          dimension: dimension,
          min: min,
          max: max,
        });
      },
      blockAudit: function (worldId, dimension, min, max) {
        return callWorldMethod("analyze.block_audit", {
          world_id: worldId,
          dimension: dimension,
          min: min,
          max: max,
        });
      },
    },
    // The Terrain ribbon tab's column-shaping commands --
    // amulet_map_editor/api/sidecar/terrain_methods.py. Every one of these
    // writes to the world and follows the same `confirm` rule as
    // fillSelection/replaceInSelection above -- a real user decision, never
    // a default this bridge supplies.
    terrain: {
      flatten: function (worldId, dimension, min, max, height, block, confirmed) {
        return callWorldMethod("terrain.flatten", {
          world_id: worldId,
          dimension: dimension,
          min: min,
          max: max,
          height: height,
          block: block,
          confirm: Boolean(confirmed),
        });
      },
      seaLevel: function (worldId, dimension, min, max, seaLevel, mode, confirmed) {
        return callWorldMethod("terrain.sea_level", {
          world_id: worldId,
          dimension: dimension,
          min: min,
          max: max,
          sea_level: seaLevel,
          mode: mode,
          confirm: Boolean(confirmed),
        });
      },
      repaint: function (worldId, dimension, min, max, block, confirmed) {
        return callWorldMethod("terrain.repaint", {
          world_id: worldId,
          dimension: dimension,
          min: min,
          max: max,
          block: block,
          confirm: Boolean(confirmed),
        });
      },
    },
    // The Entities ribbon tab -- amulet_map_editor/api/sidecar/entity_methods.py.
    // `list` is read-only; `remove` and `place` write and require `confirm`.
    entities: {
      list: function (worldId, dimension, min, max) {
        return callWorldMethod("entities.list", {
          world_id: worldId,
          dimension: dimension,
          min: min,
          max: max,
        });
      },
      remove: function (worldId, dimension, min, max, namespace, baseName, confirmed) {
        return callWorldMethod("entities.remove", {
          world_id: worldId,
          dimension: dimension,
          min: min,
          max: max,
          namespace: namespace || undefined,
          base_name: baseName || undefined,
          confirm: Boolean(confirmed),
        });
      },
      place: function (worldId, dimension, position, namespace, baseName, confirmed) {
        return callWorldMethod("entities.place", {
          world_id: worldId,
          dimension: dimension,
          position: position,
          namespace: namespace,
          base_name: baseName,
          confirm: Boolean(confirmed),
        });
      },
    },
    // The Data ribbon tab's level.dat and game-rule surfaces --
    // amulet_map_editor/api/sidecar/entity_methods.py. Reads never require
    // `confirm`; writes always do, and only ever mutate the in-memory NBT
    // tag until a subsequent `saveWorld` writes it to disk.
    data: {
      readLevel: function (worldId) {
        return callWorldMethod("data.level_read", { world_id: worldId });
      },
      writeLevel: function (worldId, fields, confirmed) {
        return callWorldMethod("data.level_write", {
          world_id: worldId,
          fields: fields,
          confirm: Boolean(confirmed),
        });
      },
      readGameRules: function (worldId) {
        return callWorldMethod("data.game_rules_read", { world_id: worldId });
      },
      writeGameRules: function (worldId, rules, confirmed) {
        return callWorldMethod("data.game_rules_write", {
          world_id: worldId,
          rules: rules,
          confirm: Boolean(confirmed),
        });
      },
    },
  };

  /** Thin wrapper shared by the School-mode and narrator calls above: run a
   * sidecar method that already returns `{ok, result}` / `{ok, error}` and
   * resolve to just `result`, rejecting with the real message otherwise.
   * Safe to call before `bridge` is known to exist -- outside Electron it
   * rejects rather than throwing, matching every other status function here. */
  function schoolCall(method, params) {
    if (!bridge || typeof bridge.call !== "function") {
      return Promise.reject(new Error("sidecar unavailable"));
    }
    return bridge.call(method, params || {}).then(function (response) {
      if (!response || !response.ok) {
        throw new Error((response && response.error && response.error.message) || method + " failed");
      }
      return response.result;
    });
  }

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

  /** Copy a selection to the sidecar's per-world clipboard. Read-only --
   * never gated behind confirm, matching selection_methods.py. */
  function copySelection(worldId, dimension, min, max) {
    return callWorldMethod("selection.copy", {
      world_id: worldId,
      dimension: dimension,
      min: min,
      max: max,
    });
  }

  /** Cut (copy, then delete) a selection. Writes to the world -- confirmed
   * must come from a real user decision. */
  function cutSelection(worldId, dimension, min, max, confirmed) {
    return callWorldMethod("selection.cut", {
      world_id: worldId,
      dimension: dimension,
      min: min,
      max: max,
      confirm: Boolean(confirmed),
    });
  }

  /** Paste whatever was last copied/cut for this world at `location`. */
  function pasteSelection(worldId, dimension, location, confirmed) {
    return callWorldMethod("selection.paste", {
      world_id: worldId,
      dimension: dimension,
      location: location,
      confirm: Boolean(confirmed),
    });
  }

  /** Delete (air-fill) a selection without keeping a clipboard copy. */
  function deleteSelection(worldId, dimension, min, max, confirmed) {
    return callWorldMethod("selection.delete", {
      world_id: worldId,
      dimension: dimension,
      min: min,
      max: max,
      confirm: Boolean(confirmed),
    });
  }

  /** Whether this world currently has something copied/cut and ready to
   * paste -- read-only, used to enable/disable the Paste command. */
  function clipboardStatus(worldId) {
    return callWorldMethod("selection.clipboard_status", { world_id: worldId });
  }

  /** Export a selection to a real structure file on disk. Not gated behind
   * the destructive-edit confirm (it never touches the open world), but a
   * pre-existing destination file requires its own explicit
   * overwriteConfirmed, exactly like `convert()` above. */
  function exportStructure(worldId, dimension, min, max, destinationPath, overwriteConfirmed) {
    return callWorldMethod("structure.export", {
      world_id: worldId,
      dimension: dimension,
      min: min,
      max: max,
      destination_path: destinationPath,
      overwrite_confirmed: Boolean(overwriteConfirmed),
    });
  }

  /** Import a structure file and paste it into the open world at
   * `location`. Writes to the world -- confirmed must come from a real
   * user decision. */
  function importStructure(worldId, dimension, sourcePath, location, confirmed) {
    return callWorldMethod("structure.import", {
      world_id: worldId,
      dimension: dimension,
      source_path: sourcePath,
      location: location,
      confirm: Boolean(confirmed),
    });
  }

  /** Create every missing chunk in an area. Never overwrites an existing
   * chunk, so this is not gated behind confirm. */
  function createChunks(worldId, dimension, min, max) {
    return callWorldMethod("chunk.create", {
      world_id: worldId,
      dimension: dimension,
      min: min,
      max: max,
    });
  }

  /** Delete every chunk within an area. Writes to the world -- confirmed
   * must come from a real user decision. */
  function deleteChunks(worldId, dimension, min, max, confirmed) {
    return callWorldMethod("chunk.delete", {
      world_id: worldId,
      dimension: dimension,
      min: min,
      max: max,
      confirm: Boolean(confirmed),
    });
  }

  /** Delete every chunk OUTSIDE an area ("prune"/"delete unselected").
   * Writes to the world -- confirmed must come from a real user decision. */
  function pruneChunks(worldId, dimension, min, max, confirmed) {
    return callWorldMethod("chunk.prune", {
      world_id: worldId,
      dimension: dimension,
      min: min,
      max: max,
      confirm: Boolean(confirmed),
    });
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

  // ------------------------------------------------------------------
  // Universal surfaces: notifications, local history, external editor.
  // Every one of these is `callWorldMethod` against a real
  // surface_methods.py handler -- no generic escape hatch, one function per
  // wire method, matching the parameter names methods.py actually reads.
  // ------------------------------------------------------------------

  function listNotifications(includeDismissed) {
    return callWorldMethod("notifications.list", {
      include_dismissed: includeDismissed !== false,
    });
  }

  function addNotification(severity, title, body, details) {
    return callWorldMethod("notifications.add", {
      severity: severity,
      title: title,
      body: body,
      details: details || "",
    });
  }

  function searchNotifications(query, regex, includeDismissed) {
    return callWorldMethod("notifications.search", {
      query: query || "",
      regex: Boolean(regex),
      include_dismissed: includeDismissed !== false,
    });
  }

  /** Bulk-dismiss the selected notifications -- honestly scoped to exactly
   * the ids passed, never "everything currently loaded". */
  function bulkDismissNotifications(notificationIds) {
    return callWorldMethod("notifications.bulkDismiss", {
      notification_ids: notificationIds || [],
    });
  }

  /** Export honours the active selection when one is given; omit
   * `notificationIds` to export every (filtered) notification currently
   * held. */
  function exportNotifications(format, notificationIds, includeDismissed) {
    return callWorldMethod("notifications.export", {
      format: format || "json",
      notification_ids: notificationIds || undefined,
      include_dismissed: includeDismissed !== false,
    });
  }

  function listHistoryEvents(filters) {
    return callWorldMethod("history.events", filters || {});
  }

  /** Restoring is itself recorded as a NEW history event, never a rewrite --
   * see amulet_map_editor.api.local_history.LocalHistory.restore. */
  function restoreHistoryEvent(eventId) {
    return callWorldMethod("history.restore", { event_id: eventId });
  }

  function exportHistory(format, filters) {
    var params = Object.assign({ format: format || "json" }, filters || {});
    return callWorldMethod("history.export", params);
  }

  function historyRoot() {
    return callWorldMethod("history.root", {});
  }

  function discoverEditors() {
    return callWorldMethod("editor.discover", {});
  }

  function openInExternalEditor(path) {
    return callWorldMethod("editor.open", { path: path });
  }

  function selectExternalEditor(path) {
    return callWorldMethod("editor.select", { path: path });
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
