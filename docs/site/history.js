/* Append-only local version history for everything this site owns.
 *
 * The panel is only safe to open because nothing in here ever rewrites a past
 * revision. Restoring writes a NEW revision whose recorded state is the branch
 * it replaced, so pressing Restore on that revision undoes the undo, and so on
 * without end. A "restore" that discarded the state it replaced would make the
 * one screen a worried user reaches for the one screen that can lose their work.
 *
 * Two things feed the log. Other modules call record(); and this file watches
 * AmuletSite.settings itself, because a settings change is the one event that
 * must never depend on some other module remembering to report it. Every label
 * names the actual difference -- "Accent changed from #4d5f92 to #2e6b4f" --
 * because a log of "Updated" is a log nobody can act on.
 */
(function () {
  "use strict";

  var site = window.AmuletSite;
  if (!site) return;

  var el = site.el;
  var lang = site.lang;
  var settings = site.settings;

  var STORE_KEY = "history";
  var RETENTION_KEY = "history.retention";
  var UI_KEY = "history.ui";

  // The real product name, not the renamed display name: an exported file has
  // to say which software produced it or the reader cannot tell.
  var PRODUCT = "Material Minecraft World Editor";

  var LABEL_MAX = 400;
  var SNAPSHOT_MAX = 4000; // serialized characters
  var HARD_CAP = 2000;
  var ARM_MS = 12000;
  var DEDUPE_MS = 1500;
  var COALESCE_MS = 900;
  var DAY_MS = 86400000;

  var CAP_CHOICES = [50, 200, 500, 1000, 2000];
  var DAY_CHOICES = [0, 7, 30, 90, 365];
  var SHIPPED_RETENTION = { cap: 200, days: 0 };

  var MONTHS_EN = ["January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"];
  var DOW_SHORT_EN = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  var DOW_LONG_EN = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday",
    "Friday", "Saturday"];

  // ------------------------------------------------------------------- copy
  function t(en, yue) {
    return lang.t(en, yue);
  }

  /* Funny level 1 is strictly factual, 5 is at its most playful, and each
   * language picks with its own slider. Only the voice moves: every count,
   * value, identifier and timestamp in these strings is interpolated exactly. */
  function graded(en, yue) {
    return lang.t(variant(en, lang.funny("en")), variant(yue, lang.funny("yue")));
  }

  function variant(list, level) {
    var index = level <= 1 ? 0 : level <= 3 ? 1 : 2;
    return list[index] || list[list.length - 1] || "";
  }

  function plural(count, one, many) {
    return count === 1 ? one : many;
  }

  // ------------------------------------------------------------------- time
  function dayStartOf(value) {
    var date = new Date(value);
    if (isNaN(date.getTime())) return null;
    date.setHours(0, 0, 0, 0);
    return date.getTime();
  }

  function dayEndOf(value) {
    var start = dayStartOf(value);
    return start === null ? null : start + DAY_MS - 1;
  }

  function isoDay(value) {
    var date = new Date(value);
    if (isNaN(date.getTime())) return "";
    var month = date.getMonth() + 1;
    var day = date.getDate();
    return date.getFullYear() + "-" + (month < 10 ? "0" + month : month) + "-" + (day < 10 ? "0" + day : day);
  }

  function isoStamp(value) {
    var date = new Date(value);
    try {
      return isNaN(date.getTime()) ? null : date.toISOString();
    } catch (error) {
      return null;
    }
  }

  function exactLabel(value) {
    var date = new Date(value);
    if (isNaN(date.getTime())) return "";
    try {
      return date.toLocaleString();
    } catch (error) {
      return isoDay(value);
    }
  }

  function shortLabel(value) {
    var date = new Date(value);
    if (isNaN(date.getTime())) return "";
    try {
      return date.toLocaleString(undefined, {
        year: "numeric",
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch (error) {
      return exactLabel(value);
    }
  }

  function longDay(value) {
    var date = new Date(value);
    if (isNaN(date.getTime())) return "";
    try {
      return date.toLocaleDateString(undefined, {
        weekday: "long",
        year: "numeric",
        month: "long",
        day: "numeric",
      });
    } catch (error) {
      return isoDay(value);
    }
  }

  function reducedMotion() {
    if (settings.get("reducedMotion") === true) return true;
    try {
      return !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
    } catch (error) {
      return false;
    }
  }

  // ------------------------------------------------------------ value words
  var KEY_LABELS = {
    language: ["Language mode", "語言模式"],
    funnyEn: ["Funny level (English)", "搞笑程度（英文）"],
    funnyYue: ["Funny level (Cantonese)", "搞笑程度（粵語）"],
    theme: ["Theme", "主題"],
    density: ["Density", "密度"],
    accent: ["Accent", "主色"],
    font: ["Interface font", "介面字體"],
    scale: ["Interface scale", "介面縮放"],
    emoji: ["Emoji in messages", "訊息用 emoji"],
    narrator: ["Spoken narrator", "語音旁白"],
    reducedMotion: ["Reduced motion", "減少動態"],
    brand: ["Displayed name", "顯示名稱"],
  };

  var VALUE_WORDS = {
    language: { english: "English", cantonese: "Cantonese", bilingual: "Bilingual" },
    theme: { light: "Light", dark: "Dark", system: "Match system" },
    density: { compact: "Compact", comfortable: "Comfortable", spacious: "Spacious" },
    font: {
      "system-ui": "System UI",
      segoe: "Segoe UI",
      georgia: "Georgia",
      mono: "Cascadia Code",
    },
  };

  /** camelCase and kebab-case both read as words rather than as identifiers. */
  function humanize(token) {
    var spaced = String(token)
      .replace(/[-_]+/g, " ")
      .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
      .trim();
    if (!spaced) return "";
    return spaced.charAt(0).toUpperCase() + spaced.slice(1).toLowerCase();
  }

  function keyLabel(key) {
    var pair = KEY_LABELS[key];
    if (!pair) return humanize(key);
    return t(pair[0], pair[1]);
  }

  function keyLabelEnglish(key) {
    var pair = KEY_LABELS[key];
    return pair ? pair[0] : humanize(key);
  }

  /** The stored value, in words a reader can compare, with the raw value kept. */
  function valueWords(key, value) {
    if (value === true) return "on";
    if (value === false) return "off";
    if (value == null || value === "") return "(empty)";
    if (key === "scale") return value + "%";
    if (key === "funnyEn" || key === "funnyYue") return "level " + value;
    if (key === "brand") return "“" + value + "”";
    var map = VALUE_WORDS[key];
    var word = map ? map[String(value)] : null;
    return word ? word + " (" + value + ")" : String(value);
  }

  function sameValue(a, b) {
    if (a === b) return true;
    if (a == null || b == null) return false;
    return typeof a !== "object" && typeof b !== "object" && String(a) === String(b);
  }

  function diffKeys(before, after) {
    var seen = {};
    var keys = [];
    [before || {}, after || {}].forEach(function (map) {
      Object.keys(map).forEach(function (key) {
        if (!seen[key]) {
          seen[key] = true;
          keys.push(key);
        }
      });
    });
    return keys.filter(function (key) {
      return !sameValue((before || {})[key], (after || {})[key]);
    });
  }

  function describeChanges(before, after, keys, limit) {
    var shown = keys.slice(0, limit || 4).map(function (key) {
      return keyLabelEnglish(key) + " " + valueWords(key, (before || {})[key]) +
        " → " + valueWords(key, (after || {})[key]);
    });
    var rest = keys.length - shown.length;
    return shown.join(", ") + (rest > 0 ? ", and " + rest + " more" : "");
  }

  // ---------------------------------------------------------------- actions
  var ACTION_WORDS = {
    setting: ["Setting changed", "設定改動"],
    "settings-reset": ["Settings reset", "設定重設"],
    restore: ["Restored", "已還原"],
    preset: ["Preset applied", "已套用預設"],
    export: ["Export taken", "已匯出"],
    retention: ["Retention changed", "保留規則改動"],
    "history-pruned": ["History pruned", "記錄已修剪"],
    "history-deleted": ["Revisions deleted", "記錄已刪除"],
    notification: ["Notification dismissed", "通知已清除"],
    "notifications-dismissed": ["Notifications dismissed", "通知已清除"],
    "tabs-closed": ["Tabs closed", "已關閉分頁"],
    "tab-closed": ["Tab closed", "已關閉分頁"],
    appearance: ["Appearance edited", "外觀改動"],
    change: ["Change", "改動"],
  };

  // The two actions this file writes for itself. A module that also reports a
  // settings change would otherwise file the same event twice.
  var WATCHED_ACTIONS = { setting: true, "settings-reset": true, settings: true, reset: true };

  function normalizeAction(value) {
    var token = String(value == null ? "" : value)
      .toLowerCase()
      .replace(/[\s_]+/g, "-")
      .replace(/[^a-z0-9-]/g, "")
      .replace(/-+/g, "-")
      .replace(/^-|-$/g, "")
      .slice(0, 40);
    return token || "change";
  }

  function actionLabel(token) {
    var pair = ACTION_WORDS[token];
    return pair ? t(pair[0], pair[1]) : humanize(token);
  }

  function actionLabelEnglish(token) {
    var pair = ACTION_WORDS[token];
    return pair ? pair[0] : humanize(token);
  }

  // ------------------------------------------------------------------ store
  var entries = [];
  var dropped = 0;
  var seq = 0;
  var storageWarned = false;

  function nextId() {
    seq += 1;
    return "h" + Date.now().toString(36) + "-" + seq;
  }

  function safeJson(value) {
    if (value === undefined) return null;
    try {
      var text = JSON.stringify(value);
      return typeof text === "string" ? text : null;
    } catch (error) {
      return null;
    }
  }

  function clone(value) {
    var text = safeJson(value);
    if (text === null) return null;
    try {
      return JSON.parse(text);
    } catch (error) {
      return null;
    }
  }

  function boundSnapshot(value) {
    if (value == null) return null;
    var text = safeJson(value);
    if (text === null) {
      return { note: "Snapshot omitted: it could not be serialized as JSON." };
    }
    if (text.length > SNAPSHOT_MAX) {
      return {
        note: "Snapshot omitted: " + text.length + " serialized characters exceeds the " +
          SNAPSHOT_MAX + "-character bound.",
        characters: text.length,
      };
    }
    return clone(value);
  }

  function sanitize(row) {
    if (!row || typeof row !== "object") return null;
    var label = String(row.label == null ? "" : row.label).slice(0, LABEL_MAX);
    if (!label) return null;
    var at = Number(row.at);
    var state = row.state && typeof row.state === "object" && !Array.isArray(row.state)
      ? clone(row.state)
      : null;
    return {
      id: String(row.id || nextId()),
      at: isFinite(at) ? at : Date.now(),
      action: normalizeAction(row.action),
      key: row.key ? String(row.key).slice(0, 60) : null,
      label: label,
      labelYue: row.labelYue ? String(row.labelYue).slice(0, LABEL_MAX) : null,
      state: state,
      snapshot: row.snapshot == null ? null : boundSnapshot(row.snapshot),
      restoreOf: row.restoreOf ? String(row.restoreOf) : null,
    };
  }

  function load() {
    var raw = site.store.get(STORE_KEY, null);
    var rows = null;
    var lost = 0;
    if (Array.isArray(raw)) rows = raw;
    else if (raw && typeof raw === "object" && Array.isArray(raw.entries)) {
      rows = raw.entries;
      lost = Number(raw.dropped) || 0;
    }
    if (!rows) return;
    rows.forEach(function (row) {
      var entry = sanitize(row);
      if (entry) entries.push(entry);
    });
    entries.sort(function (a, b) {
      return b.at - a.at;
    });
    dropped = lost;
  }

  function persist() {
    var ok = site.store.set(STORE_KEY, { version: 1, entries: entries, dropped: dropped });
    if (ok || storageWarned) return ok;
    storageWarned = true;
    // A refused history write must never fail the operation the user actually
    // asked for -- it already happened. Say so, and keep the log in memory.
    report(
      t(
        "History could not be saved in this browser. The change you asked for still happened; this revision will be lost when the page is closed.",
        "呢個瀏覽器儲存唔到歷史記錄。你要求嘅改動照樣做咗；不過呢個版本喺閂頁之後就會冇咗。"
      ),
      "warning"
    );
    return ok;
  }

  function report(message, tone) {
    try {
      if (typeof site.toast === "function") site.toast(message, tone || "info");
    } catch (error) {
      /* a refused toast is not a reason to stop recording */
    }
  }

  // -------------------------------------------------------------- retention
  function retention() {
    var saved = site.store.get(RETENTION_KEY, null) || {};
    var cap = Number(saved.cap);
    var days = Number(saved.days);
    return {
      cap: CAP_CHOICES.indexOf(cap) === -1 ? SHIPPED_RETENTION.cap : cap,
      days: DAY_CHOICES.indexOf(days) === -1 ? SHIPPED_RETENTION.days : days,
    };
  }

  function setRetention(next) {
    site.store.set(RETENTION_KEY, { cap: next.cap, days: next.days });
  }

  /** Which revisions the given rules would remove, newest-first order assumed. */
  function overRules(rules) {
    var cutoff = rules.days ? Date.now() - rules.days * DAY_MS : 0;
    return entries.filter(function (entry, index) {
      return index >= rules.cap || (cutoff && entry.at < cutoff);
    });
  }

  function applyRetention() {
    var rules = retention();
    var cutoff = rules.days ? Date.now() - rules.days * DAY_MS : 0;
    var keep = [];
    var removed = 0;
    entries.forEach(function (entry, index) {
      if (index >= Math.min(rules.cap, HARD_CAP) || (cutoff && entry.at < cutoff)) {
        removed += 1;
        return;
      }
      keep.push(entry);
    });
    if (!removed) return 0;
    entries = keep;
    dropped += removed;
    return removed;
  }

  // ----------------------------------------------------------------- writes
  var lastState = settings.all();
  var applying = false;
  var renderQueued = false;

  function scheduleRender() {
    if (renderQueued || !built) return;
    renderQueued = true;
    window.setTimeout(function () {
      renderQueued = false;
      render();
    }, 0);
  }

  function duplicate(action, label, at, origin) {
    var newest = entries[0];
    if (!newest || at - newest.at > DEDUPE_MS) return false;
    if (newest.action === action && newest.label === label) return true;
    // This file watches the settings object directly, so a module reporting the
    // same settings change through record() is the second copy, not a new event.
    return origin === "api" && WATCHED_ACTIONS[action] && WATCHED_ACTIONS[newest.action];
  }

  /**
   * One continuous gesture is one revision. A range input fires on every pixel
   * of a drag, so without this a single slide of the accent hue would file sixty
   * revisions and bury every real event under them. The replaced revision keeps
   * its original recorded state, so restoring it still returns the reader to
   * where the gesture began -- and a drag that ends where it started leaves no
   * revision at all, because nothing changed.
   */
  function coalesce(action, key, label, labelYue, at) {
    var newest = entries[0];
    if (!newest || action !== "setting" || !key) return null;
    if (newest.action !== "setting" || newest.key !== key) return null;
    if (at - newest.at > COALESCE_MS) return null;
    var before = newest.state || {};
    if (sameValue(before[key], settings.get(key))) {
      entries.shift();
      persist();
      scheduleRender();
      return "removed";
    }
    newest.at = at;
    newest.label = label;
    newest.labelYue = labelYue;
    persist();
    scheduleRender();
    return "merged";
  }

  function write(action, label, snapshot, extra) {
    var options = extra || {};
    var token = normalizeAction(action);
    var text = String(label == null ? "" : label).trim().slice(0, LABEL_MAX);
    if (!text) return null; // a revision that names no change describes nothing
    var at = Date.now();
    var yue = options.labelYue ? String(options.labelYue).trim().slice(0, LABEL_MAX) : null;

    var merged = coalesce(token, options.key || null, text, yue, at);
    if (merged) return merged === "merged" ? clone(entries[0]) : null;
    if (duplicate(token, text, at, options.origin || "api")) return null;

    var entry = {
      id: nextId(),
      at: at,
      action: token,
      key: options.key ? String(options.key).slice(0, 60) : null,
      label: text,
      labelYue: yue,
      // The settings as they stood immediately BEFORE this revision. Restore
      // means "put it back the way it was just before this happened", and one
      // invariant is what makes undoing an undo behave predictably.
      state: options.state ? clone(options.state) : settings.all(),
      snapshot: boundSnapshot(snapshot),
      restoreOf: options.restoreOf ? String(options.restoreOf) : null,
    };

    entries.unshift(entry);
    applyRetention();
    persist();
    scheduleRender();
    return clone(entry);
  }

  // -------------------------------------------------------- settings watch
  function resetLabel(before, after, changed) {
    return "Site settings reset — " + changed.length + " " +
      plural(changed.length, "value", "values") + " returned to shipped defaults: " +
      describeChanges(before, after, changed);
  }

  settings.onChange(function (key, value, all) {
    var before = lastState;
    var now = all && typeof all === "object" ? all : settings.all();
    lastState = clone(now) || now;
    if (applying) return; // restore() files one revision for the whole batch

    try {
      if (key === null || key === undefined) {
        var changed = diffKeys(before, now);
        if (!changed.length) return; // an unchanged state records nothing
        write("settings-reset", resetLabel(before, now, changed), null, {
          state: before,
          origin: "watch",
          labelYue: "網站設定已重設 — " + changed.length + " 項回復出廠值：" +
            describeChanges(before, now, changed),
        });
        return;
      }
      if (sameValue(before[key], now[key])) return;
      var line = keyLabelEnglish(key) + " changed from " + valueWords(key, before[key]) +
        " to " + valueWords(key, now[key]);
      write("setting", line, null, {
        state: before,
        key: key,
        origin: "watch",
        labelYue: (KEY_LABELS[key] ? KEY_LABELS[key][1] : humanize(key)) + " 由 " +
          valueWords(key, before[key]) + " 改成 " + valueWords(key, now[key]),
      });
    } catch (error) {
      /* a failed history write never fails the change the user asked for */
    }
  });

  // ---------------------------------------------------------------- restore
  function findEntry(id) {
    var wanted = String(id);
    for (var i = 0; i < entries.length; i++) {
      if (entries[i].id === wanted) return entries[i];
    }
    return null;
  }

  function applyState(target) {
    applying = true;
    try {
      var shipped = settings.DEFAULTS || {};
      Object.keys(shipped).forEach(function (key) {
        var has = Object.prototype.hasOwnProperty.call(target, key);
        settings.set(key, has ? target[key] : shipped[key]);
      });
    } finally {
      applying = false;
      lastState = settings.all();
    }
  }

  function restore(id) {
    var entry = findEntry(id);
    if (!entry) {
      report(
        t(
          "No revision with the identifier " + id + " is recorded, so nothing was restored.",
          "冇識別碼係 " + id + " 嘅版本，所以乜都冇還原。"
        ),
        "warning"
      );
      return null;
    }
    if (!entry.state) {
      report(
        t(
          "That revision carries no recorded settings state, so there is nothing to restore.",
          "嗰個版本冇記低設定狀態，所以冇嘢可以還原。"
        ),
        "warning"
      );
      return null;
    }
    var before = settings.all();
    if (!diffKeys(before, entry.state).length) {
      report(
        t(
          "Every setting already matches that revision, so nothing was changed and nothing was recorded.",
          "所有設定已經同嗰個版本一樣，所以冇改到嘢，亦冇記低新版本。"
        ),
        "info"
      );
      return null;
    }

    applyState(entry.state);
    var after = settings.all();
    var changed = diffKeys(before, after);
    var label = "Restored the settings recorded before " + shortLabel(entry.at) +
      " (" + entry.label + ") — " + changed.length + " " +
      plural(changed.length, "setting", "settings") + " changed back: " +
      describeChanges(before, after, changed);

    var created = write("restore", label, null, {
      state: before,
      restoreOf: entry.id,
      origin: "self",
      labelYue: "還原到 " + shortLabel(entry.at) + " 之前嘅設定（" + entry.label + "）— 改返 " +
        changed.length + " 項：" + describeChanges(before, after, changed),
    });

    site.notify(
      lang.emoji("↩️") + t("Revision restored", "已還原版本"),
      t(
        changed.length + " " + plural(changed.length, "setting", "settings") +
          " changed back: " + describeChanges(before, after, changed) +
          ". This restore was recorded as a new revision, so it can itself be undone.",
        "改返 " + changed.length + " 項：" + describeChanges(before, after, changed) +
          "。今次還原已經記低成一個新版本，所以佢自己都可以再還原。"
      )
    );
    return created;
  }

  // ------------------------------------------------------------------- api
  function record(action, label, snapshot) {
    try {
      return write(action, label, snapshot, { origin: "api" });
    } catch (error) {
      return null; // never throw into the operation that was being recorded
    }
  }

  function all() {
    return entries.map(function (entry) {
      return clone(entry);
    });
  }

  load();

  // Anything raised before this file loaded is drained rather than lost, and
  // the queue is replaced with a forwarder so a module still holding the old
  // reference keeps working instead of silently pushing into a dead array.
  (function drainQueue() {
    var pending = [];
    ["_historyQueue", "_queuedHistory"].forEach(function (name) {
      if (Array.isArray(site[name])) pending = pending.concat(site[name]);
      site[name] = {
        push: function (row) {
          queued(row);
          return 1;
        },
      };
    });
    var stub = site.history;
    if (Array.isArray(stub)) pending = pending.concat(stub);
    else if (stub && typeof stub === "object") {
      ["_queued", "queue", "pending", "entries"].forEach(function (name) {
        if (Array.isArray(stub[name])) pending = pending.concat(stub[name]);
      });
    }
    pending.forEach(queued);
  })();

  function queued(row) {
    if (!row) return;
    if (Array.isArray(row)) record(row[0], row[1], row[2]);
    else if (typeof row === "object") record(row.action, row.label, row.snapshot);
  }

  site.history = { record: record, all: all, restore: restore };

  // ------------------------------------------------------------------ style
  var STYLE_ID = "history-panel-style";
  var PANEL_CSS = [
    // styles.css gives several of these a display value, and an author rule
    // outranks the user-agent [hidden] rule, so hiding one needs saying twice.
    "#history-filters [hidden],#history-list [hidden],.history-gate[hidden],.history-block-body[hidden],.history-cal[hidden]{display:none}",
    "#history-filters{display:block}",
    ".history-toolbar{display:grid;gap:12px;margin-bottom:16px}",
    ".history-block{border:1px solid var(--outline-variant);border-radius:var(--r-lg);background:var(--surface-container);overflow:hidden}",
    ".history-block-toggle{display:flex;width:100%;align-items:center;gap:10px;min-height:46px;padding:10px 16px;border:0;background:transparent;color:inherit;font:inherit;font-weight:650;text-align:left;cursor:pointer}",
    ".history-block-toggle:hover{background:var(--state-layer)}",
    ".history-block-summary{margin-left:auto;font-weight:500;font-size:.8rem;color:var(--on-surface-variant);text-align:right}",
    ".history-block-body{display:grid;gap:14px;padding:4px 16px 16px}",
    ".history-group{display:grid;gap:8px}",
    ".history-group-title{margin:0;font-size:.78rem;font-weight:700;letter-spacing:.04em;text-transform:uppercase;color:var(--secondary)}",
    ".history-fields{display:flex;gap:12px;flex-wrap:wrap;align-items:flex-end}",
    ".history-field{display:grid;gap:4px;min-width:10.5rem}",
    ".history-field label{font-size:.76rem;font-weight:650;color:var(--secondary)}",
    ".history-field input,.history-field select{min-height:42px;border:1px solid var(--outline-variant);border-radius:10px;padding:0 10px;background:transparent;color:inherit;font:inherit}",
    ".history-note{color:var(--on-surface-variant);font-size:.8rem;margin:0}",
    ".history-error{color:#8c1d18;font-weight:700}",
    'html[data-theme="dark"] .history-error,.dark .history-error{color:#ffb4ab}',
    ".history-actions{display:flex;gap:10px;flex-wrap:wrap;align-items:center}",
    ".history-cal{display:grid;gap:10px;padding:12px;border:1px solid var(--outline-variant);border-radius:var(--r-md);background:var(--surface-bright);max-height:min(62vh,440px);overflow:auto}",
    ".history-cal-head{display:flex;gap:8px;flex-wrap:wrap;align-items:center}",
    ".history-cal-head select,.history-cal-head input{min-height:40px;border:1px solid var(--outline-variant);border-radius:10px;padding:0 8px;background:transparent;color:inherit;font:inherit}",
    ".history-cal-head input[type=number]{width:6.5rem}",
    ".history-week{display:grid;grid-template-columns:repeat(7,minmax(34px,1fr));gap:2px}",
    ".history-dow{display:flex;align-items:center;justify-content:center;min-height:28px;font-size:.72rem;font-weight:700;color:var(--on-surface-variant)}",
    ".history-day{min-height:40px;border:1px solid transparent;border-radius:var(--r-xs);background:transparent;color:inherit;font:inherit;font-size:.85rem;cursor:pointer}",
    ".history-day:hover{background:var(--state-layer)}",
    ".history-day.is-outside{color:var(--on-surface-variant);opacity:.55}",
    ".history-day.is-today{border-color:var(--outline);font-weight:800}",
    ".history-day.is-inrange{background:var(--primary-container);color:var(--on-primary-container)}",
    ".history-day.is-edge{background:var(--primary);color:var(--on-primary);font-weight:800}",
    ".history-gate{display:grid;gap:10px;padding:14px 16px;border:2px solid #8c1d18;border-radius:var(--r-md);background:var(--surface-bright)}",
    'html[data-theme="dark"] .history-gate,.dark .history-gate{border-color:#ffb4ab}',
    ".history-gate-text{margin:0;font-weight:650}",
    ".history-gate-actions{display:flex;gap:10px;flex-wrap:wrap}",
    "#history-list{display:grid;gap:10px}",
    ".history-row{display:grid;gap:8px;padding:16px 18px;border:1px solid var(--outline-variant);border-radius:var(--r-lg);background:var(--surface-container)}",
    ".history-row-head{display:flex;gap:10px;align-items:center;flex-wrap:wrap}",
    ".history-badge{display:inline-flex;align-items:center;min-height:24px;padding:0 10px;border-radius:var(--r-full);background:var(--primary-container);color:var(--on-primary-container);font-size:.74rem;font-weight:700}",
    ".history-time{color:var(--on-surface-variant);font-size:.8rem;font-variant-numeric:tabular-nums}",
    ".history-row-label{margin:0;font-weight:600;overflow-wrap:anywhere}",
    ".history-row-foot{display:flex;gap:10px;align-items:center;flex-wrap:wrap}",
    ".history-row-detail summary{cursor:pointer;font-size:.82rem;color:var(--on-surface-variant)}",
    ".history-row-detail pre{overflow-x:auto;margin:8px 0 0;padding:10px;border-radius:var(--r-xs);background:var(--surface);font-family:var(--font-mono);font-size:.76rem}",
    "#history-filters :focus-visible,#history-list :focus-visible{outline:3px solid var(--primary);outline-offset:2px}",
    "#history-filters [disabled],#history-list [disabled]{opacity:.62;cursor:not-allowed}",
  ].join("");

  function installStyle() {
    if (document.getElementById(STYLE_ID)) return;
    var style = el("style", { id: STYLE_ID });
    style.textContent = PANEL_CSS;
    (document.head || document.documentElement).appendChild(style);
  }

  // ------------------------------------------------------------ date typing
  function localeOrder() {
    try {
      if (window.Intl && window.Intl.DateTimeFormat) {
        var format = new window.Intl.DateTimeFormat(undefined, {
          year: "numeric",
          month: "2-digit",
          day: "2-digit",
        });
        if (typeof format.formatToParts === "function") {
          var order = format
            .formatToParts(new Date(2026, 10, 22))
            .filter(function (part) {
              return part.type === "day" || part.type === "month" || part.type === "year";
            })
            .map(function (part) {
              return part.type.charAt(0);
            })
            .join("");
          if (order.length === 3) return order;
        }
      }
    } catch (error) {
      /* an engine without formatToParts falls back to the ISO order */
    }
    return "ymd";
  }

  function localeExample() {
    try {
      return new Date(2026, 7, 11).toLocaleDateString();
    } catch (error) {
      return "2026-08-11";
    }
  }

  function buildDay(year, month, day) {
    if (!(year >= 1970 && year <= 2400)) return null;
    if (!(month >= 1 && month <= 12)) return null;
    if (!(day >= 1 && day <= 31)) return null;
    var date = new Date(year, month - 1, day, 0, 0, 0, 0);
    // Rejects 31 February rather than silently rolling it into March.
    if (date.getFullYear() !== year || date.getMonth() !== month - 1 || date.getDate() !== day) {
      return null;
    }
    return date.getTime();
  }

  /** ISO first, then the numeric order this browser's locale actually writes. */
  function parseDayText(text) {
    var raw = String(text == null ? "" : text).trim();
    if (!raw) return { empty: true };
    var iso = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(raw);
    if (iso) {
      var isoAt = buildDay(Number(iso[1]), Number(iso[2]), Number(iso[3]));
      return isoAt === null ? { invalid: true } : { at: isoAt };
    }
    var parts = raw.split(/[^0-9]+/).filter(function (part) {
      return part !== "";
    });
    if (parts.length !== 3) return { invalid: true };
    var numbers = parts.map(Number);
    var order = localeOrder();
    if (parts[0].length === 4) order = "ymd";
    else if (parts[2].length === 4 && order.charAt(0) === "y") order = "mdy";
    var slot = { y: 0, m: 0, d: 0 };
    for (var i = 0; i < 3; i++) slot[order.charAt(i)] = numbers[i];
    if (slot.y < 100) slot.y += slot.y >= 70 ? 1900 : 2000;
    var at = buildDay(slot.y, slot.m, slot.d);
    return at === null ? { invalid: true } : { at: at };
  }

  // ------------------------------------------------------------ panel state
  var built = false;
  var regexControl = null;
  var nodes = {};
  var range = { from: null, to: null };
  var rangeError = { from: false, to: false };
  var selectedActions = {};
  var calendarOpen = false;
  var view = { year: new Date().getFullYear(), month: new Date().getMonth() };
  var gridFocus = dayStartOf(Date.now());
  var ui = null;

  function uiState() {
    if (ui) return ui;
    var saved = site.store.get(UI_KEY, null) || {};
    ui = {
      filters: saved.filters !== false,
      retention: saved.retention === true,
      format: ["markdown", "json", "csv"].indexOf(saved.format) === -1 ? "markdown" : saved.format,
    };
    return ui;
  }

  function saveUi() {
    site.store.set(UI_KEY, uiState());
  }

  function selectedActionList() {
    return Object.keys(selectedActions).filter(function (token) {
      return selectedActions[token];
    });
  }

  /* Copy written once at build time is copy that stops following the language
   * mode the moment it changes. Every static string this panel renders is
   * registered here instead, and re-run on each render. */
  var localizers = [];

  function loc(fn) {
    localizers.push(fn);
    try {
      fn();
    } catch (error) {
      /* one string failing to render must not take the panel down */
    }
  }

  function localize() {
    localizers.forEach(function (fn) {
      try {
        fn();
      } catch (error) {}
    });
  }

  // ---------------------------------------------------------------- filters
  function haystack(entry) {
    return [
      isoDay(entry.at),
      exactLabel(entry.at),
      entry.action,
      actionLabelEnglish(entry.action),
      actionLabel(entry.action),
      entry.label,
      entry.labelYue || "",
      safeJson(entry.state) || "",
      safeJson(entry.snapshot) || "",
    ].join(" ");
  }

  function textState() {
    if (regexControl) return regexControl.state();
    var input = nodes.search;
    return {
      query: input ? input.value : "",
      regex: false,
      flags: "i",
      valid: true,
      feedback: "",
    };
  }

  function matchesText(entry) {
    if (regexControl) return regexControl.matches(haystack(entry));
    var input = nodes.search;
    var query = input ? input.value : "";
    if (!query) return true;
    try {
      return site.matcher(query, false, "i").test(haystack(entry));
    } catch (error) {
      return false;
    }
  }

  function matchesDate(entry) {
    if (range.from !== null && entry.at < range.from) return false;
    if (range.to !== null && entry.at > range.to + DAY_MS - 1) return false;
    return true;
  }

  function matchesAction(entry) {
    var chosen = selectedActionList();
    if (!chosen.length) return true;
    return chosen.indexOf(entry.action) !== -1;
  }

  /** Everything except the action filter, so a chip can count what it would add. */
  function beforeActions() {
    return entries.filter(function (entry) {
      return matchesDate(entry) && matchesText(entry);
    });
  }

  function visible() {
    return beforeActions().filter(matchesAction);
  }

  function filtersActive() {
    var state = textState();
    return !!(state.query || range.from !== null || range.to !== null || selectedActionList().length);
  }

  function filterSentence() {
    var parts = [];
    var state = textState();
    if (state.query) {
      parts.push(
        t("search “" + state.query + "”", "搜尋“" + state.query + "”") +
          " (" + (state.regex ? "regex, flags " + (state.flags || "i") : t("plain text", "純文字")) + ")"
      );
    }
    if (range.from !== null || range.to !== null) {
      parts.push(
        t("dates ", "日期 ") +
          (range.from === null ? t("any", "不限") : isoDay(range.from)) + " → " +
          (range.to === null ? t("any", "不限") : isoDay(range.to))
      );
    }
    var chosen = selectedActionList();
    if (chosen.length) {
      parts.push(
        t("actions ", "動作 ") +
          chosen.map(actionLabel).join(", ")
      );
    }
    return parts.length ? parts.join(" · ") : t("no filter", "冇篩選");
  }

  // ------------------------------------------------------------------ gates
  function makeGate() {
    var text = el("p", { class: "history-gate-text" });
    var confirm = el("button", { type: "button", class: "button button-filled" });
    var cancel = el("button", { type: "button", class: "button button-text" });
    var bar = el(
      "div",
      { class: "history-gate", role: "alert", hidden: true },
      text,
      el("div", { class: "history-gate-actions" }, confirm, cancel)
    );
    var open = null;
    var timer = 0;

    function close(reason) {
      if (!open) return;
      var onCancel = open.onCancel;
      open = null;
      window.clearTimeout(timer);
      bar.hidden = true;
      if (reason !== "confirm" && typeof onCancel === "function") onCancel();
      if (reason === "cancel" && nodes.lastGateOrigin && nodes.lastGateOrigin.focus) {
        nodes.lastGateOrigin.focus();
      }
    }

    confirm.addEventListener("click", function () {
      if (!open) return;
      var run = open.onConfirm;
      open = null;
      window.clearTimeout(timer);
      bar.hidden = true;
      if (typeof run === "function") run();
    });
    cancel.addEventListener("click", function () {
      close("cancel");
    });
    bar.addEventListener("keydown", function (event) {
      if (event.key !== "Escape" || !open) return;
      event.stopPropagation();
      close("cancel");
    });

    return {
      node: bar,
      armed: function () {
        return !!open;
      },
      arm: function (options) {
        close("replace");
        open = options;
        confirm.textContent = options.confirmLabel;
        cancel.textContent = t("Keep them", "保留");
        // Revealed before the wording is written: an alert announces a change
        // made inside a rendered region, not one made while it was hidden.
        bar.hidden = false;
        text.textContent = options.text;
        confirm.focus();
        window.clearTimeout(timer);
        timer = window.setTimeout(function () {
          close("cancel");
        }, ARM_MS);
      },
      disarm: function () {
        close("cancel");
      },
    };
  }

  // -------------------------------------------------------------- exporting
  function scopeSentence(rows) {
    return rows.length + " of " + entries.length + " recorded revisions · filter: " +
      filterSentence() + " · exported " + new Date().toISOString();
  }

  function markdownExport(rows) {
    var lines = [];
    lines.push("# " + PRODUCT + " — local version history");
    lines.push("");
    lines.push(scopeSentence(rows));
    lines.push("");
    lines.push("| Time | Action | What changed |");
    lines.push("| --- | --- | --- |");
    rows.forEach(function (entry) {
      var cell = function (value) {
        return String(value).replace(/\|/g, "\\|").replace(/\s*\n\s*/g, " ");
      };
      lines.push("| " + cell(isoStamp(entry.at) || entry.at) + " | " +
        cell(actionLabelEnglish(entry.action)) + " | " + cell(entry.label) + " |");
    });
    return lines.join("\n") + "\n";
  }

  function jsonExport(rows) {
    return JSON.stringify(
      {
        product: PRODUCT,
        exported: new Date().toISOString(),
        scope: {
          shown: rows.length,
          recorded: entries.length,
          filter: filterSentence(),
        },
        revisions: rows.map(function (entry) {
          return {
            id: entry.id,
            at: entry.at,
            timestamp: isoStamp(entry.at),
            action: entry.action,
            actionLabel: actionLabelEnglish(entry.action),
            label: entry.label,
            restoreOf: entry.restoreOf,
            stateBefore: entry.state,
            snapshot: entry.snapshot,
          };
        }),
      },
      null,
      2
    ) + "\n";
  }

  function csvExport(rows) {
    var quote = function (value) {
      return '"' + String(value == null ? "" : value).replace(/"/g, '""') + '"';
    };
    var lines = ["id,timestamp,action,label,restore_of,state_before"];
    rows.forEach(function (entry) {
      lines.push([
        quote(entry.id),
        quote(isoStamp(entry.at) || entry.at),
        quote(entry.action),
        quote(entry.label),
        quote(entry.restoreOf || ""),
        quote(safeJson(entry.state) || ""),
      ].join(","));
    });
    return lines.join("\r\n") + "\r\n";
  }

  var FORMATS = {
    markdown: { label: ["Markdown (.md)", "Markdown（.md）"], ext: "md", mime: "text/markdown", build: markdownExport },
    json: { label: ["JSON (.json)", "JSON（.json）"], ext: "json", mime: "application/json", build: jsonExport },
    csv: { label: ["CSV (.csv)", "CSV（.csv）"], ext: "csv", mime: "text/csv", build: csvExport },
  };

  function fileStamp() {
    return isoDay(Date.now()).replace(/-/g, "") + "-" +
      new Date().toTimeString().slice(0, 8).replace(/:/g, "");
  }

  function download(text, filename, mime) {
    try {
      if (!window.Blob || !window.URL || !window.URL.createObjectURL) return false;
      var url = window.URL.createObjectURL(new window.Blob([text], { type: mime + ";charset=utf-8" }));
      var link = el("a", { href: url, download: filename });
      link.style.position = "fixed";
      link.style.left = "-1000px";
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.setTimeout(function () {
        window.URL.revokeObjectURL(url);
      }, 4000);
      return true;
    } catch (error) {
      return false;
    }
  }

  function legacyCopy(text) {
    var returnTo = document.activeElement;
    var field = el("textarea", {
      tabindex: "-1",
      readonly: true,
      "aria-hidden": "true",
    });
    field.value = text;
    field.style.position = "fixed";
    field.style.top = "-1000px";
    field.style.opacity = "0";
    document.body.appendChild(field);
    var copied = false;
    try {
      field.select();
      copied = document.execCommand("copy") === true;
    } catch (error) {
      copied = false;
    }
    document.body.removeChild(field);
    if (returnTo && typeof returnTo.focus === "function") returnTo.focus();
    return copied;
  }

  function exportVisible() {
    var rows = visible();
    if (!rows.length) {
      report(
        t(
          "Nothing matches the current filter, so there was nothing to export.",
          "冇版本符合而家嘅篩選，所以冇嘢可以匯出。"
        ),
        "warning"
      );
      return;
    }
    var key = uiState().format;
    var format = FORMATS[key] || FORMATS.markdown;
    var text = format.build(rows);
    var filename = "material-minecraft-world-editor-history-" + fileStamp() + "." + format.ext;

    var finish = function (method) {
      var delivery = method === "download"
        ? t(
            "A download of " + filename + " was started.",
            "已經開始下載 " + filename + "。"
          )
        : t(
            "This browser refused the download, so " + filename + " was copied to the clipboard instead.",
            "呢個瀏覽器拒絕咗下載，所以 " + filename + " 改為複製咗去剪貼板。"
          );
      record(
        "export",
        "Exported " + rows.length + " of " + entries.length + " revisions as " +
          format.ext.toUpperCase() + " via " + method + " (" + filename + ") with filter: " + filterSentence(),
        { format: key, method: method, shown: rows.length, recorded: entries.length, filename: filename }
      );
      site.notify(
        lang.emoji("📤") + t("History exported", "歷史記錄已匯出"),
        t(
          rows.length + " of " + entries.length + " revisions were exported as " +
            format.ext.toUpperCase() + ". " + delivery,
          entries.length + " 個之中嘅 " + rows.length + " 個版本已匯出成 " +
            format.ext.toUpperCase() + "。" + delivery
        )
      );
    };

    if (download(text, filename, format.mime)) {
      finish("download");
      return;
    }
    var clipboard = navigator.clipboard;
    if (clipboard && typeof clipboard.writeText === "function") {
      clipboard.writeText(text).then(
        function () {
          finish("clipboard");
        },
        function (error) {
          if (legacyCopy(text)) {
            finish("clipboard");
          } else {
            report(
              t(
                "This browser refused both the download and the clipboard, so nothing was exported: " +
                  String((error && error.message) || error),
                "呢個瀏覽器拒絕咗下載同剪貼板，所以乜都冇匯出：" + String((error && error.message) || error)
              ),
              "error"
            );
          }
        }
      );
      return;
    }
    if (legacyCopy(text)) finish("clipboard");
    else {
      report(
        t(
          "This browser exposes no download and no clipboard write, so nothing was exported.",
          "呢個瀏覽器冇下載亦冇剪貼板寫入功能，所以乜都冇匯出。"
        ),
        "error"
      );
    }
  }

  // ---------------------------------------------------------- delete, prune
  function deleteRows(rows) {
    var doomed = {};
    rows.forEach(function (entry) {
      doomed[entry.id] = true;
    });
    var before = entries.length;
    entries = entries.filter(function (entry) {
      return !doomed[entry.id];
    });
    var removed = before - entries.length;
    persist();
    record(
      "history-deleted",
      "Deleted " + removed + " of " + before + " revisions from the local history (filter: " +
        filterSentence() + ")",
      null
    );
    site.notify(
      lang.emoji("🗑️") + t("Revisions deleted", "已刪除版本"),
      t(
        removed + " of " + before + " revisions were deleted from this browser. Deletion is permanent; the settings they described were not changed.",
        before + " 個之中嘅 " + removed + " 個版本已經喺呢個瀏覽器刪除。刪除係永久嘅；佢哋描述嘅設定冇改動。"
      )
    );
    render();
  }

  function pruneNow() {
    var rules = retention();
    var doomed = overRules(rules);
    if (!doomed.length) return;
    var before = entries.length;
    applyRetention();
    persist();
    record(
      "history-pruned",
      "Pruned " + doomed.length + " of " + before + " revisions to the retention rules (newest " +
        rules.cap + " revisions" + (rules.days ? ", kept for " + rules.days + " days" : ", no age limit") + ")",
      null
    );
    site.notify(
      lang.emoji("🧹") + t("History pruned", "歷史記錄已修剪"),
      t(
        doomed.length + " of " + before + " revisions were removed to satisfy the retention rules.",
        before + " 個之中嘅 " + doomed.length + " 個版本已按保留規則移除。"
      )
    );
    render();
  }

  // ----------------------------------------------------------------- render
  function rowNode(entry) {
    var label = entry.labelYue && lang.mode() !== "english"
      ? lang.t(entry.label, entry.labelYue)
      : entry.label;

    var current = settings.all();
    var changed = entry.state ? diffKeys(current, entry.state) : [];
    var foot = [];

    if (changed.length) {
      var button = el("button", {
        type: "button",
        class: "button button-outlined",
        text: t("Restore", "還原"),
        "aria-label": t(
          "Restore the settings recorded before " + shortLabel(entry.at) + ": " + entry.label,
          "還原到 " + shortLabel(entry.at) + " 之前嘅設定：" + entry.label
        ),
        onclick: function () {
          restore(entry.id);
          render();
        },
      });
      foot.push(button);
      foot.push(
        el("span", {
          class: "history-note",
          text: t(
            changed.length + " " + plural(changed.length, "setting", "settings") + " would change back: " +
              describeChanges(current, entry.state, changed, 3) +
              ". The restore is recorded as a new revision, so it can be undone.",
            "會改返 " + changed.length + " 項：" + describeChanges(current, entry.state, changed, 3) +
              "。還原會記低成新版本，所以可以再撤銷。"
          ),
        })
      );
    } else {
      foot.push(
        el("span", {
          class: "history-note",
          text: t(
            "Every setting already matches the state recorded before this revision, so there is nothing to restore.",
            "所有設定已經同呢個版本之前記低嘅狀態一樣，所以冇嘢可以還原。"
          ),
        })
      );
    }

    var detailText = JSON.stringify(
      {
        id: entry.id,
        timestamp: isoStamp(entry.at),
        action: entry.action,
        restoreOf: entry.restoreOf,
        stateBefore: entry.state,
        snapshot: entry.snapshot,
      },
      null,
      2
    );

    return el(
      "article",
      { class: "history-row", role: "listitem", "data-id": entry.id, "data-action": entry.action },
      el(
        "div",
        { class: "history-row-head" },
        el("span", { class: "history-badge", text: actionLabel(entry.action) }),
        el("time", {
          class: "history-time",
          datetime: isoStamp(entry.at),
          title: exactLabel(entry.at),
          text: shortLabel(entry.at),
        }),
        entry.restoreOf
          ? el("span", {
              class: "history-note",
              text: t("undoes revision " + entry.restoreOf, "撤銷版本 " + entry.restoreOf),
            })
          : null
      ),
      el("p", { class: "history-row-label", text: label }),
      el("div", { class: "history-row-foot" }, foot),
      el(
        "details",
        { class: "history-row-detail" },
        el("summary", { text: t("Show the recorded state", "顯示記低嘅狀態") }),
        el("pre", { text: detailText })
      )
    );
  }

  function emptyMessage(state) {
    if (!state.valid) {
      return t(
        "That pattern is not valid, so no revision is shown: " + (state.feedback || "invalid pattern"),
        "呢個 pattern 無效，所以唔顯示任何版本：" + (state.feedback || "invalid pattern")
      );
    }
    if (!entries.length) {
      return graded(
        [
          "No revision recorded yet. Change a setting, apply a preset, dismiss a notification or take an export, and it will appear here with what changed and a way back.",
          "Nothing recorded yet. Change a setting, apply a preset, dismiss a notification or take an export, and this page fills up with exactly what changed and a way back to it.",
          "Empty, which means you have not touched anything yet. Change a setting and this page starts keeping receipts — including a way back.",
        ],
        [
          "仲未有任何版本。改個設定、套用預設、清除通知或者匯出一次，呢度就會出現改咗咩，同埋點樣返轉頭。",
          "仲未記低任何嘢。改個設定、套用預設、清除通知或者匯出一次，呢一頁就會寫低改咗咩，仲有返轉頭嘅路。",
          "空白一片，即係你仲未郁過任何嘢。改個設定，呢頁就開始幫你記數 — 連點返轉頭都寫埋。",
        ]
      );
    }
    return t(
      "No revision matches the current filter (" + filterSentence() + "). " +
        entries.length + " " + plural(entries.length, "revision is", "revisions are") + " recorded.",
      "冇版本符合而家嘅篩選（" + filterSentence() + "）。總共記低咗 " + entries.length + " 個版本。"
    );
  }

  function renderList() {
    var list = nodes.list;
    if (!list) return;
    var state = textState();
    var rows = visible();
    list.setAttribute("role", "list");
    list.setAttribute("aria-label", t("Recorded revisions", "已記錄嘅版本"));
    list.replaceChildren.apply(list, rows.map(rowNode));
    if (nodes.count) nodes.count.textContent = site.describe(rows.length, "revision", state.query);
    if (nodes.empty) {
      nodes.empty.hidden = rows.length !== 0;
      if (!rows.length) nodes.empty.textContent = emptyMessage(state);
    }
    return rows;
  }

  function renderActionChips() {
    var row = nodes.actionRow;
    if (!row) return;
    var pool = beforeActions();
    var counts = {};
    var order = [];
    // The actions are derived from the log itself, so a token this file has
    // never heard of still gets a chip the moment something records it.
    entries.forEach(function (entry) {
      if (counts[entry.action] === undefined) {
        counts[entry.action] = 0;
        order.push(entry.action);
      }
    });
    pool.forEach(function (entry) {
      counts[entry.action] += 1;
    });
    Object.keys(selectedActions).forEach(function (token) {
      if (counts[token] === undefined) delete selectedActions[token];
    });
    order.sort(function (a, b) {
      if (counts[b] !== counts[a]) return counts[b] - counts[a];
      return a < b ? -1 : a > b ? 1 : 0;
    });

    var chips = [];
    var allChip = el(
      "button",
      {
        type: "button",
        class: "chip",
        "aria-pressed": String(selectedActionList().length === 0),
        onclick: function () {
          selectedActions = {};
          render();
        },
      },
      el("span", { class: "chip-label", text: t("All actions", "所有動作") }),
      el("span", { class: "chip-count", text: String(pool.length) })
    );
    chips.push(allChip);

    order.forEach(function (token) {
      var chip = el(
        "button",
        {
          type: "button",
          class: "chip",
          "aria-pressed": String(!!selectedActions[token]),
          "aria-label": actionLabel(token) + ", " + counts[token] + " " +
            plural(counts[token], "revision", "revisions"),
          onclick: function () {
            if (selectedActions[token]) delete selectedActions[token];
            else selectedActions[token] = true;
            render();
          },
        },
        el("span", { class: "chip-label", text: actionLabel(token) }),
        el("span", { class: "chip-count", text: String(counts[token]) })
      );
      chips.push(chip);
    });

    row.replaceChildren.apply(row, chips);
  }

  function renderCalendar() {
    var grid = nodes.calGrid;
    if (!grid) return;
    var first = new Date(view.year, view.month, 1);
    var firstDay = firstDayOfWeek();
    var offset = (first.getDay() - firstDay + 7) % 7;
    var start = new Date(view.year, view.month, 1 - offset);
    var today = dayStartOf(Date.now());
    var rows = [];

    var names = weekdayNames(firstDay);
    var head = el("div", { class: "history-week", role: "row" });
    names.forEach(function (name) {
      head.appendChild(
        el("span", {
          class: "history-dow",
          role: "columnheader",
          "aria-label": name.long,
          text: name.short,
        })
      );
    });
    rows.push(head);

    var focusButton = null;
    for (var week = 0; week < 6; week++) {
      var line = el("div", { class: "history-week", role: "row" });
      for (var day = 0; day < 7; day++) {
        var cell = new Date(start.getFullYear(), start.getMonth(), start.getDate() + week * 7 + day);
        var at = cell.getTime();
        var classes = ["history-day"];
        if (cell.getMonth() !== view.month) classes.push("is-outside");
        if (at === today) classes.push("is-today");
        var edge = at === range.from || at === range.to;
        var inside = range.from !== null && range.to !== null && at > range.from && at < range.to;
        if (edge) classes.push("is-edge");
        else if (inside) classes.push("is-inrange");
        var isFocus = at === gridFocus;
        var button = el("button", {
          type: "button",
          class: classes.join(" "),
          role: "gridcell",
          text: String(cell.getDate()),
          tabindex: isFocus ? "0" : "-1",
          "aria-label": longDay(at),
          "aria-selected": String(edge || inside),
          "aria-current": at === today ? "date" : null,
          "data-at": String(at),
        });
        button.addEventListener("click", function (event) {
          chooseDay(Number(event.currentTarget.getAttribute("data-at")));
        });
        if (isFocus) focusButton = button;
        line.appendChild(button);
      }
      rows.push(line);
    }

    grid.replaceChildren.apply(grid, rows);
    if (nodes.calMonth) nodes.calMonth.value = String(view.month);
    if (nodes.calYear) nodes.calYear.value = String(view.year);
    if (nodes.calHint) {
      nodes.calHint.textContent = range.from !== null && range.to === null
        ? t(
            "Picked " + isoDay(range.from) + " as the start. Choose the last day of the range, or the same day again for a single day.",
            "已揀 " + isoDay(range.from) + " 做開始。再揀範圍最後一日；揀返同一日就係單日。"
          )
        : t(
            "Choose the first day of the range. Arrow keys move by a day, Page Up and Page Down by a month.",
            "揀範圍第一日。方向鍵一日一日行，Page Up／Page Down 一個月一個月行。"
          );
    }
    return focusButton;
  }

  function firstDayOfWeek() {
    try {
      if (window.Intl && typeof window.Intl.Locale === "function") {
        var locale = new window.Intl.Locale(navigator.language || "en");
        var info = typeof locale.getWeekInfo === "function" ? locale.getWeekInfo() : locale.weekInfo;
        // ISO numbers Monday 1 through Sunday 7; JS getDay() puts Sunday at 0.
        if (info && info.firstDay) return info.firstDay % 7;
      }
    } catch (error) {
      /* an engine without week info starts the week on Sunday */
    }
    return 0;
  }

  function weekdayNames(firstDay) {
    var out = [];
    for (var i = 0; i < 7; i++) {
      var index = (firstDay + i) % 7;
      // 4 January 1970 was a Sunday, so this walks the week from a known point.
      var date = new Date(1970, 0, 4 + index);
      var short = null;
      var long = null;
      try {
        short = date.toLocaleDateString(undefined, { weekday: "short" });
        long = date.toLocaleDateString(undefined, { weekday: "long" });
      } catch (error) {
        short = null;
      }
      out.push({ short: short || DOW_SHORT_EN[index], long: long || DOW_LONG_EN[index] });
    }
    return out;
  }

  function chooseDay(at) {
    if (!isFinite(at)) return;
    if (range.from === null || range.to !== null) {
      range.from = at;
      range.to = null;
    } else if (at < range.from) {
      range.to = range.from;
      range.from = at;
    } else {
      range.to = at;
    }
    gridFocus = at;
    rangeError.from = false;
    rangeError.to = false;
    if (nodes.fromInput) nodes.fromInput.value = range.from === null ? "" : isoDay(range.from);
    if (nodes.toInput) nodes.toInput.value = range.to === null ? "" : isoDay(range.to);
    // The grid is repainted separately so the day just pressed can be handed
    // its focus back: replaceChildren destroys the button that was focused.
    render(true);
    var focusButton = renderCalendar();
    if (focusButton) focusButton.focus();
  }

  function moveFocus(days, months) {
    var date = new Date(gridFocus);
    if (months) {
      // setMonth alone rolls 31 January into 3 March; clamping to the target
      // month's last day is what a reader pressing Page Up actually meant.
      var day = date.getDate();
      date.setDate(1);
      date.setMonth(date.getMonth() + months);
      var last = new Date(date.getFullYear(), date.getMonth() + 1, 0).getDate();
      date.setDate(Math.min(day, last));
    }
    if (days) date.setDate(date.getDate() + days);
    date.setHours(0, 0, 0, 0);
    gridFocus = date.getTime();
    view.year = date.getFullYear();
    view.month = date.getMonth();
    var focusButton = renderCalendar();
    if (focusButton) focusButton.focus();
  }

  function renderRangeNote() {
    if (!nodes.rangeNote) return;
    var messages = [];
    var example = localeExample();
    if (rangeError.from) {
      messages.push(
        t(
          "The From box is not a date, so no start bound is applied. Use 2026-08-11 or " + example + ".",
          "「由」嗰格唔係一個日期，所以冇套用開始日期。用 2026-08-11 或者 " + example + "。"
        )
      );
    }
    if (rangeError.to) {
      messages.push(
        t(
          "The To box is not a date, so no end bound is applied. Use 2026-08-11 or " + example + ".",
          "「至」嗰格唔係一個日期，所以冇套用結束日期。用 2026-08-11 或者 " + example + "。"
        )
      );
    }
    if (range.from !== null && range.to !== null && range.to < range.from) {
      messages.push(
        t(
          "The end date " + isoDay(range.to) + " is before the start date " + isoDay(range.from) + ", so no revision can fall inside the range.",
          "結束日期 " + isoDay(range.to) + " 早過開始日期 " + isoDay(range.from) + "，所以冇版本會喺範圍入面。"
        )
      );
    }
    nodes.rangeNote.textContent = messages.join(" ");
    nodes.rangeNote.className = messages.length ? "history-note history-error" : "history-note";
    if (nodes.fromInput) nodes.fromInput.setAttribute("aria-invalid", String(rangeError.from));
    if (nodes.toInput) nodes.toInput.setAttribute("aria-invalid", String(rangeError.to));
  }

  function readRangeInput(which) {
    var input = which === "from" ? nodes.fromInput : nodes.toInput;
    if (!input) return;
    var parsed = parseDayText(input.value);
    if (parsed.empty) {
      range[which] = null;
      rangeError[which] = false;
    } else if (parsed.invalid) {
      // The text stays exactly as typed; only the bound is withheld, so the
      // visible list never claims a constraint the field cannot justify.
      range[which] = null;
      rangeError[which] = true;
    } else {
      range[which] = parsed.at;
      rangeError[which] = false;
      view.year = new Date(parsed.at).getFullYear();
      view.month = new Date(parsed.at).getMonth();
      gridFocus = parsed.at;
    }
    render();
  }

  function applyPreset(preset) {
    var today = dayStartOf(Date.now());
    if (preset === "all") {
      range.from = null;
      range.to = null;
    } else if (preset === "today") {
      range.from = today;
      range.to = today;
    } else if (preset === "7") {
      range.from = today - 6 * DAY_MS;
      range.to = today;
    } else if (preset === "30") {
      range.from = today - 29 * DAY_MS;
      range.to = today;
    } else if (preset === "month") {
      var now = new Date();
      range.from = new Date(now.getFullYear(), now.getMonth(), 1).getTime();
      range.to = today;
    }
    rangeError.from = false;
    rangeError.to = false;
    if (nodes.fromInput) nodes.fromInput.value = range.from === null ? "" : isoDay(range.from);
    if (nodes.toInput) nodes.toInput.value = range.to === null ? "" : isoDay(range.to);
    gridFocus = range.from === null ? today : range.from;
    view.year = new Date(gridFocus).getFullYear();
    view.month = new Date(gridFocus).getMonth();
    render();
  }

  function renderRetention() {
    var rules = retention();
    if (nodes.capSelect) nodes.capSelect.value = String(rules.cap);
    if (nodes.daysSelect) nodes.daysSelect.value = String(rules.days);
    var over = overRules(rules).length;
    if (nodes.pruneButton) {
      nodes.pruneButton.disabled = over === 0;
      nodes.pruneButton.textContent = over
        ? t("Prune " + over + " revisions now", "即刻修剪 " + over + " 個版本")
        : t("Prune to these rules", "按規則修剪");
      nodes.pruneButton.setAttribute(
        "title",
        over
          ? t(over + " recorded revisions fall outside these rules.", "有 " + over + " 個版本超出呢啲規則。")
          : t(
              "Disabled because every recorded revision already satisfies these rules.",
              "停用中，因為所有已記錄版本都已經符合呢啲規則。"
            )
      );
    }
    if (nodes.retentionNote) {
      nodes.retentionNote.textContent = t(
        "Keeping the newest " + rules.cap + " revisions" +
          (rules.days ? " recorded in the last " + rules.days + " days" : ", with no age limit") +
          ". " + entries.length + " recorded now" +
          (dropped ? "; " + dropped + " older revisions have been dropped by these rules since this browser started recording." : "."),
        "保留最新 " + rules.cap + " 個版本" +
          (rules.days ? "，而且只保留最近 " + rules.days + " 日" : "，冇時間上限") +
          "。而家記低咗 " + entries.length + " 個" +
          (dropped ? "；由開始記錄到而家已經有 " + dropped + " 個舊版本按規則移除咗。" : "。")
      );
    }
  }

  function renderChrome() {
    var state = uiState();
    if (nodes.filterToggle) {
      nodes.filterToggle.setAttribute("aria-expanded", String(state.filters));
      nodes.filterLabel.textContent = t("Filters", "篩選");
      nodes.filterSummary.textContent = filtersActive()
        ? filterSentence()
        : t("No filter — every recorded revision is shown", "冇篩選 — 顯示所有已記錄版本");
      nodes.filterBody.hidden = !state.filters;
    }
    if (nodes.retentionToggle) {
      nodes.retentionToggle.setAttribute("aria-expanded", String(state.retention));
      nodes.retentionLabel.textContent = t("Retention and pruning", "保留同修剪");
      nodes.retentionBody.hidden = !state.retention;
    }
    if (nodes.calToggle) {
      nodes.calToggle.setAttribute("aria-expanded", String(calendarOpen));
      nodes.calToggle.textContent = calendarOpen
        ? t("Hide calendar", "收埋日曆")
        : t("Open calendar", "開啟日曆");
    }
    if (nodes.calendar) nodes.calendar.hidden = !calendarOpen;
    if (nodes.copy) {
      nodes.copy.textContent = graded(
        [
          "Append-only, in this browser. Restoring is recorded as a new revision rather than a rewrite, so an undo can itself be undone.",
          "Append-only and local to this browser. A restore is written as a new revision rather than replacing the old one, so the undo can be undone, and that undo undone.",
          "Nothing here is ever overwritten. Restore writes a new revision instead of eating the old one, so you can undo, undo the undo, and keep going as long as you like.",
        ],
        [
          "只加唔改，淨係喺呢個瀏覽器。還原會記低成新版本，唔會改寫舊嘅，所以撤銷都可以再撤銷。",
          "只加唔改，全部留喺呢個瀏覽器。還原係寫多一個版本，唔係食咗舊嗰個，所以撤銷可以再撤銷，再撤銷。",
          "呢度冇嘢會俾人蓋過。還原係寫多個版本，唔會食咗舊嗰個，所以你想撤銷幾多次都得。",
        ]
      );
    }
  }

  function renderStatus(rows) {
    if (!nodes.status) return;
    var shown = rows ? rows.length : 0;
    nodes.status.textContent = t(
      shown + " of " + entries.length + " " + plural(entries.length, "revision", "revisions") +
        " shown · filter: " + filterSentence(),
      entries.length + " 個之中顯示緊 " + shown + " 個版本 · 篩選：" + filterSentence()
    );
    if (nodes.exportButton) {
      nodes.exportButton.disabled = shown === 0;
      nodes.exportButton.textContent = t(
        "Export " + shown + " shown",
        "匯出顯示中嘅 " + shown + " 個"
      );
      nodes.exportButton.setAttribute(
        "title",
        shown
          ? t("Exports exactly the revisions shown above.", "只匯出上面顯示緊嘅版本。")
          : t(
              "Disabled because no revision matches the current filter.",
              "停用中，因為冇版本符合而家嘅篩選。"
            )
      );
    }
    if (nodes.deleteButton) {
      nodes.deleteButton.disabled = shown === 0 || deleteGate.armed();
      nodes.deleteButton.textContent = t(
        "Delete " + shown + " shown",
        "刪除顯示中嘅 " + shown + " 個"
      );
      nodes.deleteButton.setAttribute(
        "title",
        shown
          ? t(
              "Permanently removes the " + shown + " revisions shown above from this browser.",
              "永久刪除上面顯示緊嘅 " + shown + " 個版本。"
            )
          : t(
              "Disabled because no revision matches the current filter.",
              "停用中，因為冇版本符合而家嘅篩選。"
            )
      );
    }
  }

  function render(skipCalendar) {
    if (!built) return;
    renderChrome();
    renderActionChips();
    renderRangeNote();
    renderRetention();
    if (!skipCalendar && calendarOpen) renderCalendar();
    var rows = renderList();
    renderStatus(rows);
  }

  // ------------------------------------------------------------------- gates
  var deleteGate = makeGate();
  var retentionGate = makeGate();

  // ------------------------------------------------------------------ build
  function disclosure(id, storeKey, defaultOpen, body) {
    var labelNode = el("span");
    var summaryNode = el("span", { class: "history-block-summary" });
    var toggle = el(
      "button",
      {
        type: "button",
        class: "history-block-toggle",
        "aria-expanded": String(defaultOpen),
        "aria-controls": id,
      },
      labelNode,
      summaryNode
    );
    body.id = id;
    toggle.addEventListener("click", function () {
      var state = uiState();
      state[storeKey] = !state[storeKey];
      saveUi();
      render();
    });
    return {
      node: el("div", { class: "history-block" }, toggle, body),
      toggle: toggle,
      label: labelNode,
      summary: summaryNode,
      body: body,
    };
  }

  function buildDateGroup() {
    var presets = el("div", { class: "history-actions", role: "group" });
    loc(function () {
      presets.setAttribute("aria-label", t("Date presets", "日期預設"));
    });
    [
      ["all", ["All time", "全部時間"]],
      ["today", ["Today", "今日"]],
      ["7", ["Last 7 days", "最近 7 日"]],
      ["30", ["Last 30 days", "最近 30 日"]],
      ["month", ["This month", "今個月"]],
    ].forEach(function (pair) {
      var chip = el("button", {
        type: "button",
        class: "chip",
        onclick: function () {
          applyPreset(pair[0]);
        },
      });
      loc(function () {
        chip.textContent = t(pair[1][0], pair[1][1]);
      });
      presets.appendChild(chip);
    });

    nodes.fromInput = el("input", {
      type: "text",
      id: "history-date-from",
      autocomplete: "off",
      spellcheck: "false",
      inputmode: "numeric",
      maxlength: "24",
      "aria-describedby": "history-range-note",
    });
    nodes.toInput = el("input", {
      type: "text",
      id: "history-date-to",
      autocomplete: "off",
      spellcheck: "false",
      inputmode: "numeric",
      maxlength: "24",
      "aria-describedby": "history-range-note",
    });
    nodes.fromInput.addEventListener("input", function () {
      readRangeInput("from");
    });
    nodes.toInput.addEventListener("input", function () {
      readRangeInput("to");
    });

    nodes.fromLabel = el("label", { for: "history-date-from" });
    nodes.toLabel = el("label", { for: "history-date-to" });
    loc(function () {
      // The accepted forms are named on the label rather than only in an error,
      // so the reader learns them before typing something that is refused.
      var example = localeExample();
      nodes.fromLabel.textContent = t(
        "From (2026-08-11 or " + example + ")",
        "由（2026-08-11 或者 " + example + "）"
      );
      nodes.toLabel.textContent = t(
        "To (2026-08-11 or " + example + ")",
        "至（2026-08-11 或者 " + example + "）"
      );
    });

    nodes.rangeNote = el("p", { class: "history-note", id: "history-range-note", role: "status" });

    nodes.calToggle = el("button", {
      type: "button",
      class: "button button-text",
      "aria-expanded": "false",
      "aria-controls": "history-calendar",
      onclick: function () {
        calendarOpen = !calendarOpen;
        render();
        if (calendarOpen) {
          var focusButton = renderCalendar();
          if (focusButton) focusButton.focus();
        }
      },
    });

    nodes.calMonth = el("select", { id: "history-cal-month" });
    monthOptions().forEach(function (option) {
      nodes.calMonth.appendChild(option);
    });
    nodes.calMonth.addEventListener("change", function () {
      view.month = Number(nodes.calMonth.value);
      renderCalendar();
    });

    nodes.calYear = el("input", {
      type: "number",
      id: "history-cal-year",
      min: "1970",
      max: "2400",
      step: "1",
    });
    loc(function () {
      nodes.calMonth.setAttribute("aria-label", t("Month", "月份"));
      nodes.calYear.setAttribute("aria-label", t("Year", "年份"));
    });
    nodes.calYear.addEventListener("change", function () {
      var year = Number(nodes.calYear.value);
      if (year >= 1970 && year <= 2400) view.year = year;
      renderCalendar();
    });

    var prev = el("button", {
      type: "button",
      class: "button button-text",
      text: "◀",
      onclick: function () {
        var date = new Date(view.year, view.month - 1, 1);
        view.year = date.getFullYear();
        view.month = date.getMonth();
        renderCalendar();
      },
    });
    var next = el("button", {
      type: "button",
      class: "button button-text",
      text: "▶",
      onclick: function () {
        var date = new Date(view.year, view.month + 1, 1);
        view.year = date.getFullYear();
        view.month = date.getMonth();
        renderCalendar();
      },
    });
    var clear = el("button", {
      type: "button",
      class: "button button-text",
      onclick: function () {
        applyPreset("all");
      },
    });

    nodes.calGrid = el("div", { class: "history-grid", role: "grid" });
    loc(function () {
      // The arrows are glyphs, so their accessible names are the only names.
      prev.setAttribute("aria-label", t("Previous month", "上一個月"));
      next.setAttribute("aria-label", t("Next month", "下一個月"));
      clear.textContent = t("Clear range", "清除範圍");
      nodes.calGrid.setAttribute("aria-label", t("Choose a date range", "揀日期範圍"));
    });
    nodes.calGrid.addEventListener("keydown", function (event) {
      var handled = true;
      if (event.key === "ArrowLeft") moveFocus(-1);
      else if (event.key === "ArrowRight") moveFocus(1);
      else if (event.key === "ArrowUp") moveFocus(-7);
      else if (event.key === "ArrowDown") moveFocus(7);
      else if (event.key === "PageUp") moveFocus(0, -1);
      else if (event.key === "PageDown") moveFocus(0, 1);
      else if (event.key === "Home") moveFocus(-((new Date(gridFocus).getDay() - firstDayOfWeek() + 7) % 7));
      else if (event.key === "End") moveFocus(6 - ((new Date(gridFocus).getDay() - firstDayOfWeek() + 7) % 7));
      else handled = false;
      if (handled) event.preventDefault();
    });

    nodes.calHint = el("p", { class: "history-note" });

    nodes.calendar = el(
      "div",
      { class: "history-cal", id: "history-calendar", hidden: true },
      el("div", { class: "history-cal-head" }, prev, nodes.calMonth, nodes.calYear, next, clear),
      nodes.calGrid,
      nodes.calHint
    );

    var groupTitle = el("p", { class: "history-group-title" });
    var group = el(
      "div",
      { class: "history-group", role: "group" },
      groupTitle,
      presets,
      el(
        "div",
        { class: "history-fields" },
        el("div", { class: "history-field" }, nodes.fromLabel, nodes.fromInput),
        el("div", { class: "history-field" }, nodes.toLabel, nodes.toInput),
        nodes.calToggle
      ),
      nodes.rangeNote,
      nodes.calendar
    );
    loc(function () {
      var title = t("Date range", "日期範圍");
      groupTitle.textContent = title;
      group.setAttribute("aria-label", title);
    });
    return group;
  }

  function monthOptions() {
    var options = [];
    for (var m = 0; m < 12; m++) {
      var name = null;
      try {
        name = new Date(2026, m, 1).toLocaleDateString(undefined, { month: "long" });
      } catch (error) {
        name = null;
      }
      options.push(el("option", { value: String(m), text: name || MONTHS_EN[m] }));
    }
    return options;
  }

  function buildActionGroup() {
    nodes.actionRow = el("div", {
      class: "chip-row",
      id: "history-action-chips",
      role: "group",
    });
    var title = el("p", { class: "history-group-title" });
    loc(function () {
      nodes.actionRow.setAttribute(
        "aria-label",
        t("Filter revisions by action", "按動作篩選版本")
      );
      title.textContent = t("Action — more than one can be selected", "動作 — 可以揀多過一個");
    });
    return el("div", { class: "history-group" }, title, nodes.actionRow);
  }

  function buildRetentionGroup() {
    nodes.capSelect = el("select", { id: "history-cap", "aria-describedby": "history-retention-note" });
    var capOptions = CAP_CHOICES.map(function (cap) {
      var option = el("option", { value: String(cap) });
      nodes.capSelect.appendChild(option);
      return { node: option, cap: cap };
    });
    nodes.daysSelect = el("select", { id: "history-days", "aria-describedby": "history-retention-note" });
    var dayOptions = DAY_CHOICES.map(function (days) {
      var option = el("option", { value: String(days) });
      nodes.daysSelect.appendChild(option);
      return { node: option, days: days };
    });
    loc(function () {
      capOptions.forEach(function (entry) {
        entry.node.textContent = t(entry.cap + " revisions", entry.cap + " 個版本");
      });
      dayOptions.forEach(function (entry) {
        entry.node.textContent = entry.days === 0
          ? t("No age limit", "冇時間限制")
          : t(entry.days + " days", entry.days + " 日");
      });
    });

    function proposeRules(next, describe) {
      var doomed = overRules(next);
      var current = retention();
      if (!doomed.length) {
        setRetention(next);
        record("retention", describe, { cap: next.cap, days: next.days });
        render();
        return;
      }
      nodes.lastGateOrigin = nodes.capSelect;
      retentionGate.arm({
        text: t(
          "Applying “" + describe + "” discards " + doomed.length + " recorded " +
            plural(doomed.length, "revision", "revisions") +
            " permanently. The oldest is " + shortLabel(doomed[doomed.length - 1].at) + ".",
          "套用「" + describe + "」會永久刪除 " + doomed.length + " 個已記錄版本。最舊嗰個係 " +
            shortLabel(doomed[doomed.length - 1].at) + "。"
        ),
        confirmLabel: t("Discard " + doomed.length, "刪除 " + doomed.length + " 個"),
        onConfirm: function () {
          setRetention(next);
          var before = entries.length;
          applyRetention();
          persist();
          record(
            "retention",
            describe + " — " + doomed.length + " of " + before + " revisions discarded",
            { cap: next.cap, days: next.days }
          );
          site.notify(
            lang.emoji("🧹") + t("Retention applied", "已套用保留規則"),
            t(
              doomed.length + " of " + before + " revisions were discarded to satisfy “" + describe + "”.",
              before + " 個之中嘅 " + doomed.length + " 個版本已按「" + describe + "」刪除。"
            )
          );
          render();
        },
        onCancel: function () {
          // The select must never show a rule that was not applied.
          nodes.capSelect.value = String(current.cap);
          nodes.daysSelect.value = String(current.days);
          render();
        },
      });
    }

    nodes.capSelect.addEventListener("change", function () {
      var current = retention();
      var next = { cap: Number(nodes.capSelect.value), days: current.days };
      proposeRules(next, "Retention cap changed from " + current.cap + " to " + next.cap + " revisions");
    });
    nodes.daysSelect.addEventListener("change", function () {
      var current = retention();
      var next = { cap: current.cap, days: Number(nodes.daysSelect.value) };
      proposeRules(
        next,
        "Retention age changed from " + (current.days ? current.days + " days" : "no age limit") +
          " to " + (next.days ? next.days + " days" : "no age limit")
      );
    });

    nodes.pruneButton = el("button", {
      type: "button",
      class: "button button-outlined",
      onclick: function () {
        var doomed = overRules(retention());
        if (!doomed.length) return;
        nodes.lastGateOrigin = nodes.pruneButton;
        retentionGate.arm({
          text: t(
            "Prune " + doomed.length + " " + plural(doomed.length, "revision", "revisions") +
              " that fall outside the retention rules? This is permanent. The oldest is " +
              shortLabel(doomed[doomed.length - 1].at) + ".",
            "修剪 " + doomed.length + " 個超出保留規則嘅版本？呢個係永久操作。最舊嗰個係 " +
              shortLabel(doomed[doomed.length - 1].at) + "。"
          ),
          confirmLabel: t("Prune " + doomed.length, "修剪 " + doomed.length + " 個"),
          onConfirm: pruneNow,
        });
      },
    });

    nodes.retentionNote = el("p", { class: "history-note", id: "history-retention-note" });

    var capLabel = el("label", { for: "history-cap" });
    var daysLabel = el("label", { for: "history-days" });
    var scopeNote = el("p", { class: "history-note" });
    loc(function () {
      capLabel.textContent = t("Keep at most", "最多保留");
      daysLabel.textContent = t("Keep for", "保留時間");
      scopeNote.textContent = t(
        "Retention bounds this browser's storage only. Pruning deletes revisions; it never changes the settings a revision described.",
        "保留規則淨係限制呢個瀏覽器嘅儲存。修剪只會刪除版本記錄，唔會改動版本描述過嘅設定。"
      );
    });

    return el(
      "div",
      { class: "history-block-body" },
      el(
        "div",
        { class: "history-fields" },
        el("div", { class: "history-field" }, capLabel, nodes.capSelect),
        el("div", { class: "history-field" }, daysLabel, nodes.daysSelect),
        nodes.pruneButton
      ),
      nodes.retentionNote,
      scopeNote,
      retentionGate.node
    );
  }

  function buildActionsRow() {
    nodes.formatSelect = el("select", { id: "history-format" });
    var formatOptions = ["markdown", "json", "csv"].map(function (key) {
      var option = el("option", { value: key });
      nodes.formatSelect.appendChild(option);
      return { node: option, key: key };
    });
    loc(function () {
      nodes.formatSelect.setAttribute("aria-label", t("Export format", "匯出格式"));
      formatOptions.forEach(function (entry) {
        entry.node.textContent = t(FORMATS[entry.key].label[0], FORMATS[entry.key].label[1]);
      });
    });
    nodes.formatSelect.value = uiState().format;
    nodes.formatSelect.addEventListener("change", function () {
      uiState().format = nodes.formatSelect.value;
      saveUi();
      render();
    });

    nodes.exportButton = el("button", {
      type: "button",
      class: "button button-filled",
      onclick: exportVisible,
    });

    nodes.deleteButton = el("button", {
      type: "button",
      class: "button button-outlined",
      onclick: function () {
        var rows = visible();
        if (!rows.length) return;
        nodes.lastGateOrigin = nodes.deleteButton;
        deleteGate.arm({
          text: t(
            "Delete " + rows.length + " of " + entries.length + " recorded " +
              plural(entries.length, "revision", "revisions") +
              " — everything matching " + filterSentence() +
              ". Deletion is permanent and cannot be undone. The settings these revisions describe are not changed.",
            "刪除 " + entries.length + " 個之中嘅 " + rows.length + " 個版本 — 即係所有符合" +
              filterSentence() + "嘅記錄。刪除係永久嘅，冇得復原。呢啲版本描述嘅設定唔會改動。"
          ),
          confirmLabel: t("Delete " + rows.length, "刪除 " + rows.length + " 個"),
          onConfirm: function () {
            deleteRows(rows);
          },
          onCancel: render,
        });
        render();
      },
    });

    nodes.status = el("p", { class: "history-note", role: "status" });

    return el(
      "div",
      { class: "history-group" },
      el("div", { class: "history-actions" }, nodes.formatSelect, nodes.exportButton, nodes.deleteButton),
      nodes.status,
      deleteGate.node
    );
  }

  function attachSearch() {
    nodes.search = document.getElementById("history-search");
    var openButton = document.getElementById("history-regex-open");
    var panel = document.getElementById("history-regex");
    if (!nodes.search) return;
    if (site.regex && typeof site.regex.attach === "function") {
      regexControl = site.regex.attach({
        name: "history",
        input: nodes.search,
        openButton: openButton,
        panel: panel,
        sample: "Accent changed from #4d5f92 to #2e6b4f",
        onChange: function () {
          render();
        },
      });
      // attach() degrades to plain-text containment when the builder markup is
      // absent, and that fallback wires no listener of its own.
      if (!document.querySelector('[data-regex-controls="history"]')) {
        nodes.search.addEventListener("input", function () {
          render();
        });
      }
      return;
    }
    // Without the shared builder there is no working regex surface, so the
    // control that would open one is removed rather than left inert.
    if (openButton) openButton.hidden = true;
    if (panel) panel.hidden = true;
    nodes.search.addEventListener("input", function () {
      render();
    });
  }

  function localizeStatic() {
    var search = document.getElementById("history-search");
    if (search) {
      var label = t("Search history", "搜尋歷史記錄");
      search.setAttribute("aria-label", label);
      search.setAttribute("placeholder", label);
    }
  }

  function boot() {
    var container = document.getElementById("history-filters");
    nodes.list = document.getElementById("history-list");
    nodes.empty = document.getElementById("history-empty");
    nodes.count = document.getElementById("history-count");
    nodes.copy = document.getElementById("history-copy");
    if (!container || !nodes.list) return;

    installStyle();

    var filterBody = el(
      "div",
      { class: "history-block-body" },
      buildDateGroup(),
      buildActionGroup()
    );
    var filters = disclosure("history-filter-panel", "filters", uiState().filters, filterBody);
    nodes.filterToggle = filters.toggle;
    nodes.filterLabel = filters.label;
    nodes.filterSummary = filters.summary;
    nodes.filterBody = filters.body;

    var retentionBody = buildRetentionGroup();
    var retentionBlock = disclosure("history-retention-panel", "retention", uiState().retention, retentionBody);
    nodes.retentionToggle = retentionBlock.toggle;
    nodes.retentionLabel = retentionBlock.label;
    nodes.retentionBody = retentionBlock.body;

    container.replaceChildren(
      el(
        "div",
        { class: "history-toolbar" },
        filters.node,
        retentionBlock.node,
        buildActionsRow()
      )
    );

    attachSearch();
    localizeStatic();
    built = true;
    render();

    document.addEventListener("keydown", function (event) {
      if (event.key !== "Escape") return;
      if (deleteGate.armed()) {
        deleteGate.disarm();
        render();
      }
      if (retentionGate.armed()) {
        retentionGate.disarm();
        render();
      }
    });

    settings.onChange(function (key) {
      // Language, emoji and both funny levels rewrite every string this panel
      // renders; any other key changes what a Restore button would do.
      localizeStatic();
      render();
      if (key === "language" || key === "emoji" || key === null) {
        if (nodes.calMonth) {
          nodes.calMonth.replaceChildren.apply(nodes.calMonth, monthOptions());
          nodes.calMonth.value = String(view.month);
        }
      }
    });
  }

  site.ready(boot);

  // --------------------------------------------------------------- palette
  function jump() {
    if (typeof site.showTab === "function") site.showTab("history");
    var section = document.getElementById("history");
    if (!section) return;
    try {
      section.scrollIntoView({ block: "start", behavior: reducedMotion() ? "auto" : "smooth" });
    } catch (error) {
      section.scrollIntoView(false);
    }
  }

  site.registerPaletteSource(function () {
    var shown = built ? visible().length : entries.length;
    function command(id, title, detail, run) {
      return {
        id: "history:" + id,
        kind: "command",
        section: t("Version history", "版本記錄"),
        group: t("Version history", "版本記錄"),
        tab: "history",
        title: title,
        label: title,
        detail: detail,
        hint: detail,
        subtitle: detail,
        keywords: "history revision restore undo append-only 版本 還原 記錄",
        run: run,
        action: run,
      };
    }
    return [
      command(
        "open",
        t("Open version history", "開啟版本記錄"),
        t(
          shown + " of " + entries.length + " revisions match the current filter.",
          entries.length + " 個之中有 " + shown + " 個版本符合而家嘅篩選。"
        ),
        jump
      ),
      command(
        "export",
        t("Export the shown revisions", "匯出顯示中嘅版本"),
        t(
          "Writes " + shown + " revisions as " + (FORMATS[uiState().format] || FORMATS.markdown).ext.toUpperCase() + ".",
          "將 " + shown + " 個版本寫成 " + (FORMATS[uiState().format] || FORMATS.markdown).ext.toUpperCase() + "。"
        ),
        function () {
          jump();
          exportVisible();
        }
      ),
      command(
        "restore-latest",
        t("Undo the newest recorded change", "撤銷最新記錄嘅改動"),
        entries.length
          ? t(
              "Restores the settings recorded before: " + entries[0].label,
              "還原到呢個之前嘅設定：" + entries[0].label
            )
          : t("Nothing is recorded yet, so there is nothing to undo.", "仲未記低任何嘢，所以冇嘢可以撤銷。"),
        function () {
          jump();
          if (!entries.length) {
            report(
              t("Nothing is recorded yet, so there is nothing to undo.", "仲未記低任何嘢，所以冇嘢可以撤銷。"),
              "info"
            );
            return;
          }
          restore(entries[0].id);
          render();
        }
      ),
    ];
  });
})();
