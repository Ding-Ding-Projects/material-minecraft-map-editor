/* The changelog viewer: every released version, its date, its categorised
 * changes, and the commit each one names.
 *
 * Two filters run over one list and neither is allowed to win. The date range
 * and the search are ANDed, both are stated in the visible summary, and both
 * are stated again at the top of anything exported -- an export whose range is
 * a mystery is a file nobody can cite.
 *
 * A commit reference is a fact, so it is never guessed at. A change links its
 * own recorded SHA; failing that it links its release's SHA and says that is
 * what it is; failing that it says no commit was recorded and links nothing. A
 * neighbouring entry's SHA is never borrowed to fill the gap, because a link
 * that goes somewhere confidently wrong is worse than a link that is absent.
 */
(function () {
  "use strict";

  var site = window.AmuletSite;
  if (!site) return;

  var el = site.el;
  var lang = site.lang;
  var settings = site.settings;

  // The repository this catalogue describes. Data may name its own, but only
  // if it is a plain GitHub repository URL -- a link built from arbitrary
  // stored text is a link this page cannot vouch for.
  var FALLBACK_REPO = "https://github.com/Ding-Ding-Projects/material-minecraft-map-editor";
  var REPO_SHAPE = /^https:\/\/github\.com\/[A-Za-z0-9][A-Za-z0-9._-]*\/[A-Za-z0-9][A-Za-z0-9._-]*$/;
  var SHA_SHAPE = /^[0-9a-f]{7,40}$/;
  var ISO_SHAPE = /^(\d{4})-(\d{2})-(\d{2})$/;

  var STORE_KEY = "changelog.range";
  var FIELD_MAX = 32;
  var SHORT_SHA = 7;
  var DAY = 86400000;
  var HIGHLIGHT_MS = 1600;
  var GRID_CELLS = 42; // six fixed rows, so the panel does not resize per month

  // Keep-a-Changelog's own categories, in its own order. An action the data
  // carries that is not on this list keeps its recorded name and sorts last:
  // renaming it would be inventing a category the release never used.
  var ACTIONS = [
    { id: "added", en: "Added", yue: "新增" },
    { id: "changed", en: "Changed", yue: "改動" },
    { id: "deprecated", en: "Deprecated", yue: "將棄用" },
    { id: "removed", en: "Removed", yue: "移除" },
    { id: "fixed", en: "Fixed", yue: "修正" },
    { id: "security", en: "Security", yue: "保安" },
  ];

  // ------------------------------------------------------------------- copy
  function t(en, yue) {
    return lang.t(en, yue);
  }

  function variant(list, level) {
    return list[level <= 1 ? 0 : level <= 3 ? 1 : 2] || list[list.length - 1] || "";
  }

  /* Level 1 is strictly factual, 5 is at its most playful, and each language
   * reads its own slider. Every variant of a line carries the same numbers,
   * dates and SHAs; only the words around them move. */
  function graded(en, yue) {
    return lang.t(variant(en, lang.funny("en")), variant(yue, lang.funny("yue")));
  }

  function text(value) {
    return value == null ? "" : String(value);
  }

  function trimmed(value) {
    return text(value).trim();
  }

  function pad2(value) {
    return value < 10 ? "0" + value : String(value);
  }

  // ------------------------------------------------------------------ dates
  /* Everything here is a date, never a moment, so it is held as UTC midnight.
   * A local-midnight Date shifts across a timezone boundary and would put a
   * release on the wrong side of a range bound for readers west of UTC. */
  function utc(y, m, d) {
    return Date.UTC(y, m - 1, d);
  }

  function partsOf(ms) {
    var date = new Date(ms);
    return { y: date.getUTCFullYear(), m: date.getUTCMonth() + 1, d: date.getUTCDate() };
  }

  function isoOf(ms) {
    var p = partsOf(ms);
    return p.y + "-" + pad2(p.m) + "-" + pad2(p.d);
  }

  function daysInMonth(y, m) {
    return new Date(Date.UTC(y, m, 0)).getUTCDate();
  }

  function todayMs() {
    var now = new Date();
    return utc(now.getFullYear(), now.getMonth() + 1, now.getDate());
  }

  function parseIso(value) {
    var found = ISO_SHAPE.exec(trimmed(value));
    if (!found) return null;
    var y = Number(found[1]);
    var m = Number(found[2]);
    var d = Number(found[3]);
    if (m < 1 || m > 12) return null;
    if (d < 1 || d > daysInMonth(y, m)) return null;
    return utc(y, m, d);
  }

  function longDate(ms) {
    try {
      return new Date(ms).toLocaleDateString(undefined, {
        weekday: "long",
        year: "numeric",
        month: "long",
        day: "numeric",
        timeZone: "UTC",
      });
    } catch (error) {
      return isoOf(ms);
    }
  }

  function monthTitle(y, m) {
    try {
      return new Date(utc(y, m, 1)).toLocaleDateString(undefined, {
        year: "numeric",
        month: "long",
        timeZone: "UTC",
      });
    } catch (error) {
      return y + "-" + pad2(m);
    }
  }

  function monthName(m) {
    try {
      return new Date(utc(2026, m, 1)).toLocaleDateString(undefined, {
        month: "long",
        timeZone: "UTC",
      });
    } catch (error) {
      return String(m);
    }
  }

  /* The reader's own numeric date order, read out of the platform rather than
   * assumed, so a typed 03/04/2026 is parsed the way this reader wrote it. */
  var LOCALE_FORMAT = (function () {
    var fallback = { order: ["year", "month", "day"], example: "2026-11-22" };
    try {
      var probe = new Date(utc(2026, 11, 22));
      var fmt = new Intl.DateTimeFormat(undefined, {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        timeZone: "UTC",
      });
      var order = [];
      fmt.formatToParts(probe).forEach(function (part) {
        if (part.type === "year" || part.type === "month" || part.type === "day") {
          order.push(part.type);
        }
      });
      if (order.length !== 3) return fallback;
      return { order: order, example: fmt.format(probe) };
    } catch (error) {
      return fallback;
    }
  })();

  var ISO_EXAMPLE = "2026-11-22";

  /* Both accepted spellings, unless this reader's locale already is the ISO
   * one -- offering the same example twice reads as a bug in the hint. */
  function examples() {
    return LOCALE_FORMAT.example === ISO_EXAMPLE
      ? ISO_EXAMPLE
      : LOCALE_FORMAT.example + t(" or ", " 或者 ") + ISO_EXAMPLE;
  }

  function orderSentence() {
    var names = { year: "year", month: "month", day: "day" };
    var yueNames = { year: "年", month: "月", day: "日" };
    return t(
      LOCALE_FORMAT.order
        .map(function (part) {
          return names[part];
        })
        .join("/"),
      LOCALE_FORMAT.order
        .map(function (part) {
          return yueNames[part];
        })
        .join("/")
    );
  }

  /* Accepts a plain ISO date and this reader's numeric locale order. A result
   * is one of: a date, "not finished yet", or "cannot be a date" -- and the
   * last two carry the reason, because a field that rejects input without
   * saying why is a field the reader has to guess at. */
  function parseTyped(raw) {
    var value = trimmed(raw);
    if (!value) return { kind: "empty" };

    var iso = parseIso(value);
    if (iso !== null) return { kind: "date", ms: iso };

    var groups = value.match(/\d+/g) || [];
    if (!groups.length) {
      return {
        kind: "invalid",
        message: t(
          "No digits here yet. Write " + examples() + ".",
          "而家仲未有數字。請寫 " + examples() + "。"
        ),
      };
    }
    if (groups.length < 3) {
      return {
        kind: "partial",
        message: t(
          "Only " + groups.length + " of the 3 numbers a date needs. Keep typing: " + examples() + ".",
          "日期要 3 個數字，而家只有 " + groups.length + " 個。繼續打：" + examples() + "。"
        ),
      };
    }
    if (groups.length > 3) {
      return {
        kind: "invalid",
        message: t(
          groups.length + " numbers were typed and a date takes exactly 3.",
          "打咗 " + groups.length + " 個數字，但日期淨係要 3 個。"
        ),
      };
    }

    var yearAt = -1;
    for (var i = 0; i < 3; i++) {
      if (groups[i].length === 4) yearAt = i;
    }
    if (yearAt === -1) {
      return {
        kind: "invalid",
        message: t(
          "Write the year in full, four digits, so 26 cannot mean two different years.",
          "年份要寫齊四位數，唔係「26」可以係兩個唔同嘅年。"
        ),
      };
    }
    if (yearAt === 1) {
      return {
        kind: "invalid",
        message: t(
          "The year is in the middle. Expected " + orderSentence() + " or a plain 2026-11-22.",
          "年份夾喺中間。應該係 " + orderSentence() + "，或者純 ISO 嘅 2026-11-22。"
        ),
      };
    }

    var rest = LOCALE_FORMAT.order.filter(function (part) {
      return part !== "year";
    });
    // Year-first input reads month then day, which is what every year-first
    // locale and ISO both do; year-last input follows this locale's own order.
    var slots = yearAt === 0 ? ["month", "day"] : rest;
    var others = yearAt === 0 ? [groups[1], groups[2]] : [groups[0], groups[1]];
    var picked = { year: Number(groups[yearAt]) };
    slots.forEach(function (part, index) {
      picked[part] = Number(others[index]);
    });

    if (picked.month < 1 || picked.month > 12) {
      return {
        kind: "invalid",
        message: t(
          "Month " + picked.month + " is not between 1 and 12. This reader's order is " +
            orderSentence() + ".",
          "月份 " + picked.month + " 唔喺 1 至 12 之間。呢部機嘅次序係 " + orderSentence() + "。"
        ),
      };
    }
    var last = daysInMonth(picked.year, picked.month);
    if (picked.day < 1 || picked.day > last) {
      return {
        kind: "invalid",
        message: t(
          "Day " + picked.day + " does not exist: " + monthName(picked.month) + " " +
            picked.year + " has " + last + " days.",
          "冇 " + picked.day + " 號：" + picked.year + " 年 " + monthName(picked.month) +
            " 得 " + last + " 日。"
        ),
      };
    }
    return { kind: "date", ms: utc(picked.year, picked.month, picked.day) };
  }

  // -------------------------------------------------------------- catalogue
  function catalogueSource() {
    var raw = window.AMULET_CHANGELOG;
    if (Array.isArray(raw)) return { meta: {}, rows: raw };
    if (raw && typeof raw === "object") {
      var rows = raw.entries || raw.releases || raw.versions;
      return { meta: raw, rows: Array.isArray(rows) ? rows : [] };
    }
    // null, not [], so the empty state can tell "the file never loaded" apart
    // from "the file loaded and records nothing".
    return { meta: {}, rows: null };
  }

  function shaOf(value) {
    var raw = trimmed(value).toLowerCase();
    return SHA_SHAPE.test(raw) ? raw : null;
  }

  // `entries` is what the generated catalogue actually calls this, and reading
  // only `changes`/`notes` rendered 244 releases with every one of their changes
  // missing -- the headers were there, so the page looked plausible and the
  // count read "0 / 0 changes" beside 244 releases.
  function changeRows(row) {
    if (Array.isArray(row.entries)) return row.entries;
    if (Array.isArray(row.changes)) return row.changes;
    if (Array.isArray(row.notes)) return row.notes;
    if (trimmed(row.summary)) return [{ summary: row.summary, action: row.action }];
    return [];
  }

  function normaliseChange(raw, releaseSha) {
    var source = typeof raw === "string" ? { summary: raw } : raw && typeof raw === "object" ? raw : {};
    var own = shaOf(source.commit_sha || source.commitSha || source.commit || source.sha);
    return {
      // `subject` is the catalogue's own word for it, and is what git calls the
      // first line of a commit message; the others are here for hand-written data.
      summary: trimmed(
        source.summary || source.subject || source.text || source.description || source.title
      ),
      action: trimmed(source.action || source.category || source.type).toLowerCase(),
      sha: own,
      // Recorded so the link can say which commit it is actually pointing at.
      inherited: !own && !!releaseSha,
      link: own || releaseSha || null,
    };
  }

  function readCatalogue() {
    var source = catalogueSource();
    var repo = (function () {
      var candidate = trimmed(
        source.meta.repository_url || source.meta.repositoryUrl || source.meta.repository
      )
        .replace(/\.git$/, "")
        .replace(/\/+$/, "");
      return REPO_SHAPE.test(candidate) ? candidate : FALLBACK_REPO;
    })();

    var releases = [];
    var unnamed = 0;
    var undated = 0;

    (source.rows || []).forEach(function (row) {
      if (!row || typeof row !== "object") return;
      var version = trimmed(row.version || row.tag || row.name);
      if (!version) {
        // A release with no version cannot be named, cited or jumped to. It is
        // counted and reported rather than rendered as a blank card.
        unnamed += 1;
        return;
      }
      var ms = parseIso(trimmed(row.released_on || row.releasedOn || row.date || row.released).slice(0, 10));
      if (ms === null) undated += 1;
      var sha = shaOf(row.commit_sha || row.commitSha || row.commit || row.sha);
      var changes = changeRows(row)
        .map(function (entry) {
          return normaliseChange(entry, sha);
        })
        .filter(function (entry) {
          return entry.summary !== "";
        });
      releases.push({
        index: releases.length,
        version: version,
        ms: ms,
        iso: ms === null ? null : isoOf(ms),
        sha: sha,
        changes: changes,
      });
    });

    return {
      loaded: source.rows !== null,
      revision: shaOf(source.meta.source_revision || source.meta.revision),
      repo: repo,
      releases: releases,
      unnamed: unnamed,
      undated: undated,
      changeCount: releases.reduce(function (total, release) {
        return total + release.changes.length;
      }, 0),
    };
  }

  var CATALOGUE = readCatalogue();

  var DATED = CATALOGUE.releases.filter(function (release) {
    return release.ms !== null;
  });

  var YEAR_RANGE = (function () {
    var now = new Date().getFullYear();
    var low = now;
    var high = now;
    DATED.forEach(function (release) {
      var year = partsOf(release.ms).y;
      if (year < low) low = year;
      if (year > high) high = year;
    });
    return { low: low, high: high };
  })();

  var MIN_MS = utc(YEAR_RANGE.low, 1, 1);
  var MAX_MS = utc(YEAR_RANGE.high, 12, 31);

  function actionLabel(id) {
    for (var i = 0; i < ACTIONS.length; i++) {
      if (ACTIONS[i].id === id) return t(ACTIONS[i].en, ACTIONS[i].yue);
    }
    // An unrecognised action keeps exactly the word the catalogue recorded.
    return id ? id : t("Other", "其他");
  }

  function actionRank(id) {
    for (var i = 0; i < ACTIONS.length; i++) {
      if (ACTIONS[i].id === id) return i;
    }
    return ACTIONS.length;
  }

  // ------------------------------------------------------------------ style
  var STYLE_ID = "changelog-panel-style";
  var CSS = [
    "#changelog-filters{display:grid;gap:14px;margin:0 0 18px;padding:var(--pad);border:1px solid var(--outline-variant,var(--outline));border-radius:var(--r-lg);background:var(--surface-container)}",
    "#changelog-filters .cl-legend{margin:0;font-size:.78rem;font-weight:650;letter-spacing:.05em;text-transform:uppercase;color:var(--secondary)}",
    "#changelog-filters .cl-presets{display:flex;flex-wrap:wrap;gap:8px;align-items:center}",
    "#changelog-filters .cl-range{position:relative;display:flex;flex-wrap:wrap;gap:16px;align-items:flex-start}",
    "#changelog-filters .cl-field{display:grid;gap:6px;flex:1 1 15rem;min-width:min(100%,13rem)}",
    "#changelog-filters .cl-field>label{font-size:.78rem;font-weight:650;color:var(--secondary)}",
    "#changelog-filters .cl-input-row{display:flex;gap:8px;align-items:center}",
    "#changelog-filters input[type=text]{flex:1;min-width:6rem;min-height:42px;border:1px solid var(--outline-variant,var(--outline));border-radius:var(--r-sm);padding:0 12px;background:var(--surface-bright);color:inherit;font:inherit;font-variant-numeric:tabular-nums}",
    '#changelog-filters input[aria-invalid="true"]{border-color:#8c1d18;border-width:2px}',
    'html[data-theme="dark"] #changelog-filters input[aria-invalid="true"]{border-color:#ffb4ab}',
    "#changelog-filters .cl-note{margin:0;font-size:.76rem;color:var(--on-surface-variant)}",
    '#changelog-filters .cl-note[data-state="error"]{color:#8c1d18;font-weight:650}',
    'html[data-theme="dark"] #changelog-filters .cl-note[data-state="error"]{color:#ffb4ab}',
    "#changelog-filters .cl-actions{display:flex;flex-wrap:wrap;gap:10px;align-items:center}",
    "#changelog-filters .cl-summary{margin:0;font-size:.82rem;color:var(--on-surface-variant)}",
    "#changelog-filters .cl-pick{min-height:42px;padding:0 12px;border:1px solid var(--outline);border-radius:var(--r-sm);background:transparent;color:inherit;font:inherit;font-size:.82rem;font-weight:600;cursor:pointer}",
    "#changelog-filters .cl-pick:hover{background:var(--state-layer)}",
    "#changelog-filters .cl-actions .button[disabled]{opacity:.55;cursor:not-allowed}",
    // The panel paints its own surface: an overlay that lets the page read
    // through it is unreadable, and one that runs past the viewport hides the
    // days at the bottom with nothing to say they are there.
    "#changelog-calendar{position:absolute;z-index:40;top:calc(100% + 8px);left:0;width:min(21rem,calc(100vw - 32px));max-height:min(70vh,32rem);overflow:auto;padding:14px;border:1px solid var(--outline);border-radius:var(--r-lg);background:var(--surface-bright);color:var(--on-surface);box-shadow:var(--shadow-3)}",
    "#changelog-calendar[hidden]{display:none}",
    "#changelog-calendar .cl-cal-row{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin-bottom:8px}",
    "#changelog-calendar select{min-height:38px;border:1px solid var(--outline-variant,var(--outline));border-radius:var(--r-sm);background:transparent;color:inherit;font:inherit;padding:0 6px}",
    "#changelog-calendar .cl-step{min-width:38px;min-height:38px;border:1px solid var(--outline);border-radius:var(--r-sm);background:transparent;color:inherit;font:inherit;cursor:pointer}",
    "#changelog-calendar .cl-step:hover:not([disabled]){background:var(--state-layer)}",
    "#changelog-calendar .cl-step[disabled]{opacity:.45;cursor:not-allowed}",
    "#changelog-calendar .cl-target{flex:1 1 auto;min-height:38px;padding:0 10px;border:1px solid var(--outline);border-radius:var(--r-full);background:transparent;color:inherit;font:inherit;font-size:.8rem;font-weight:600;cursor:pointer}",
    '#changelog-calendar .cl-target[aria-pressed="true"]{background:var(--primary-container);color:var(--on-primary-container);border-color:transparent}',
    "#changelog-calendar table{width:100%;border-collapse:collapse;margin-top:6px}",
    "#changelog-calendar caption{caption-side:top;text-align:left;font-size:.82rem;font-weight:700;padding-bottom:6px}",
    "#changelog-calendar th{padding:4px 0;font-size:.7rem;font-weight:650;color:var(--secondary)}",
    "#changelog-calendar td{padding:1px}",
    "#changelog-calendar td button{width:100%;min-height:36px;border:1px solid transparent;border-radius:var(--r-sm);background:transparent;color:inherit;font:inherit;font-size:.85rem;font-variant-numeric:tabular-nums;cursor:pointer}",
    "#changelog-calendar td button:hover{background:var(--state-layer)}",
    '#changelog-calendar td button[data-outside="true"]{opacity:.5}',
    '#changelog-calendar td button[data-range="true"]{background:var(--primary-container);color:var(--on-primary-container)}',
    '#changelog-calendar td button[aria-pressed="true"]{background:var(--primary);color:var(--on-primary);font-weight:700}',
    '#changelog-calendar td button[aria-current="date"]{border-color:var(--primary)}',
    "#changelog-calendar .cl-cal-foot{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px;align-items:center}",
    "#changelog-calendar .cl-cal-hint{margin:0;font-size:.76rem;color:var(--on-surface-variant)}",
    "#changelog-list{display:grid;gap:14px}",
    "#changelog-list .cl-release{padding:var(--pad);border:1px solid var(--outline-variant,var(--outline));border-radius:var(--r-lg);background:var(--surface-container);scroll-margin-top:140px}",
    "#changelog-list .cl-release-head{display:flex;flex-wrap:wrap;gap:8px 14px;align-items:baseline;justify-content:space-between}",
    "#changelog-list .cl-version{margin:0;font-size:1.12rem;line-height:1.3}",
    "#changelog-list .cl-meta{display:flex;flex-wrap:wrap;gap:6px 14px;align-items:baseline;font-size:.82rem;color:var(--on-surface-variant)}",
    "#changelog-list .cl-sha,#changelog-list .cl-when{font-family:var(--font-mono);font-size:.8rem}",
    "#changelog-list a.cl-sha{color:var(--accent-text,var(--primary))}",
    "#changelog-list .cl-nosha{font-style:italic}",
    "#changelog-list .cl-group{margin-top:14px}",
    "#changelog-list .cl-action{margin:0 0 6px;font-size:.74rem;font-weight:700;letter-spacing:.07em;text-transform:uppercase;color:var(--secondary)}",
    "#changelog-list .cl-changes{margin:0;padding-left:1.15rem;display:grid;gap:8px}",
    "#changelog-list .cl-changes li{line-height:1.5}",
    "#changelog-list .cl-partial{margin:10px 0 0;font-size:.78rem;color:var(--on-surface-variant)}",
  ].join("");

  function installStyle() {
    if (document.getElementById(STYLE_ID)) return;
    var style = el("style", { id: STYLE_ID });
    style.textContent = CSS;
    (document.head || document.documentElement).appendChild(style);
  }

  // ------------------------------------------------------------------ state
  var nodes = {};
  var fields = {};
  var presetButtons = [];
  var releaseNodes = {};
  var regexControl = null;
  // Shaped like a real view from the start: the palette reads this before the
  // first render whenever it is opened from another tab.
  var lastView = {
    rows: [],
    changes: 0,
    droppedUndated: 0,
    state: { query: "", regex: false, flags: "i", valid: true, feedback: "" },
  };

  var bounds = { from: null, to: null };
  var problems = { from: null, to: null };

  var calendar = {
    open: false,
    target: "from",
    view: null,
    focus: null,
    opener: null,
    grid: null,
    caption: null,
    monthSelect: null,
    yearSelect: null,
    prev: null,
    next: null,
    hint: null,
    targets: {},
  };

  function motionSafe() {
    if (settings.get("reducedMotion") === true) return false;
    try {
      return !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    } catch (error) {
      return true;
    }
  }

  // ---------------------------------------------------------------- presets
  function presetRange(id) {
    var today = todayMs();
    if (id === "7") return { from: today - 6 * DAY, to: today };
    if (id === "30") return { from: today - 29 * DAY, to: today };
    if (id === "90") return { from: today - 89 * DAY, to: today };
    if (id === "year") {
      var y = new Date(today).getUTCFullYear();
      return { from: utc(y, 1, 1), to: utc(y, 12, 31) };
    }
    return { from: null, to: null };
  }

  var PRESETS = [
    { id: "all", en: "All", yue: "全部" },
    { id: "7", en: "Last 7 days", yue: "最近 7 日" },
    { id: "30", en: "Last 30 days", yue: "最近 30 日" },
    { id: "90", en: "Last 90 days", yue: "最近 90 日" },
    { id: "year", en: "This year", yue: "今年" },
  ];

  /* Derived from the two fields rather than stored beside them: a stored
   * "last 30 days" would still claim to be current tomorrow, when the dates it
   * actually filters by have not moved. */
  function activePreset() {
    for (var i = 0; i < PRESETS.length; i++) {
      var range = presetRange(PRESETS[i].id);
      if (range.from === bounds.from && range.to === bounds.to) return PRESETS[i].id;
    }
    return "custom";
  }

  function hasDateFilter() {
    return bounds.from !== null || bounds.to !== null;
  }

  function hasQuery() {
    return searchState().query !== "";
  }

  // ---------------------------------------------------------------- search
  function searchState() {
    if (regexControl) {
      try {
        var state = regexControl.state();
        if (state) {
          return {
            query: text(state.query),
            regex: state.regex === true,
            flags: text(state.flags || "i"),
            valid: state.valid !== false,
            feedback: text(state.feedback),
          };
        }
      } catch (error) {
        /* fall through to the field's own value */
      }
    }
    var input = nodes.search;
    return {
      query: input ? text(input.value) : "",
      regex: false,
      flags: "i",
      valid: true,
      feedback: "",
    };
  }

  function makeMatcher(state) {
    if (regexControl) {
      return function (value) {
        return regexControl.matches(value);
      };
    }
    var pattern;
    try {
      pattern = site.matcher(state.query, false, "i");
    } catch (error) {
      return null;
    }
    return function (value) {
      pattern.lastIndex = 0;
      return pattern.test(text(value));
    };
  }

  function releaseHaystack(release) {
    return [release.version, release.iso || "", release.sha || ""].join(" ");
  }

  function changeHaystack(change) {
    return [change.action, change.summary, change.sha || ""].join(" ");
  }

  // ---------------------------------------------------------------- filter
  /* One pass, both filters, in the order the reader would apply them: the date
   * range decides which releases are in scope, the search decides what is
   * shown inside them. Neither is allowed to widen what the other narrowed. */
  function computeView() {
    var state = searchState();
    var query = state.query;
    var matches = state.valid ? makeMatcher(state) : null;
    var rows = [];
    var changeTotal = 0;
    var droppedUndated = 0;

    if (state.valid && matches) {
      CATALOGUE.releases.forEach(function (release) {
        if (hasDateFilter()) {
          if (release.ms === null) {
            droppedUndated += 1;
            return;
          }
          if (bounds.from !== null && release.ms < bounds.from) return;
          if (bounds.to !== null && release.ms > bounds.to) return;
        }
        var visibleChanges;
        var partial = false;
        if (!query) {
          visibleChanges = release.changes;
        } else if (matches(releaseHaystack(release))) {
          visibleChanges = release.changes;
        } else {
          visibleChanges = release.changes.filter(function (change) {
            return matches(changeHaystack(change));
          });
          if (!visibleChanges.length) return;
          partial = visibleChanges.length !== release.changes.length;
        }
        changeTotal += visibleChanges.length;
        rows.push({ release: release, changes: visibleChanges, partial: partial });
      });
    }

    return {
      state: state,
      rows: rows,
      changes: changeTotal,
      droppedUndated: droppedUndated,
    };
  }

  // ------------------------------------------------------------ range words
  function rangeSentence() {
    if (bounds.from !== null && bounds.to !== null) {
      return isoOf(bounds.from) + " to " + isoOf(bounds.to);
    }
    if (bounds.from !== null) return "from " + isoOf(bounds.from) + " onwards";
    if (bounds.to !== null) return "up to and including " + isoOf(bounds.to);
    return "every recorded date";
  }

  function rangeSentenceYue() {
    if (bounds.from !== null && bounds.to !== null) {
      return isoOf(bounds.from) + " 至 " + isoOf(bounds.to);
    }
    if (bounds.from !== null) return isoOf(bounds.from) + " 之後";
    if (bounds.to !== null) return isoOf(bounds.to) + " 或之前";
    return "所有已記錄日期";
  }

  function filterSentence(state) {
    if (!state.query) return t("no search", "冇搜尋");
    return (
      "“" + state.query + "” " +
      (state.regex ? "(regex, flags " + (state.flags || "i") + ")" : t("(plain text)", "（純文字）"))
    );
  }

  // ---------------------------------------------------------------- render
  function shaLink(sha, kind, version) {
    var full = sha;
    var label =
      kind === "release"
        ? t("Release commit " + full, "發佈 commit " + full)
        : kind === "inherited"
        ? t(
            "Release commit " + full + " — this change records no commit of its own",
            "發佈 commit " + full + " — 呢項改動本身冇記錄 commit"
          )
        : t("Commit " + full, "Commit " + full);
    var suffix = full.length < 40
      ? t(
          " (the catalogue recorded this reference abbreviated)",
          "（目錄記錄嘅係縮寫）"
        )
      : "";
    return el("a", {
      class: "cl-sha",
      href: CATALOGUE.repo + "/commit/" + full,
      target: "_blank",
      rel: "noreferrer",
      title: label + suffix + " · " + version,
      // The visible text is truncated, so the accessible name carries the
      // whole SHA: a reader who cannot see seven characters cannot compare
      // them against a release page either.
      "aria-label": label + suffix,
      text: full.slice(0, SHORT_SHA),
    });
  }

  function noSha(kind) {
    return el("span", {
      class: "cl-sha cl-nosha",
      text:
        kind === "release"
          ? t("No commit recorded for this release", "呢個版本冇記錄 commit")
          : t("No commit recorded", "冇記錄 commit"),
    });
  }

  function groupChanges(changes) {
    var groups = [];
    var byAction = {};
    changes.forEach(function (change) {
      var key = change.action || "";
      if (!byAction[key]) {
        byAction[key] = { action: key, rows: [] };
        groups.push(byAction[key]);
      }
      byAction[key].rows.push(change);
    });
    groups.sort(function (a, b) {
      return actionRank(a.action) - actionRank(b.action);
    });
    return groups;
  }

  function releaseCard(row) {
    var release = row.release;
    var headingId = "changelog-release-" + release.index + "-title";
    var card = el("article", {
      class: "cl-release",
      id: "changelog-release-" + release.index,
      // listitem rather than the implicit article role: the count of releases
      // a filter left standing is the more useful thing to hear on arrival.
      role: "listitem",
      tabindex: "-1",
      "aria-labelledby": headingId,
    });

    card.appendChild(
      el(
        "div",
        { class: "cl-release-head" },
        el("h2", { class: "cl-version", id: headingId, text: release.version }),
        el(
          "div",
          { class: "cl-meta" },
          release.iso
            ? el("time", { class: "cl-when", datetime: release.iso, text: release.iso })
            : el("span", { class: "cl-nosha", text: t("No release date recorded", "冇記錄發佈日期") }),
          release.sha ? shaLink(release.sha, "release", release.version) : noSha("release")
        )
      )
    );

    if (!row.changes.length) {
      card.appendChild(
        el("p", {
          class: "cl-partial",
          text: t(
            "This release records no changes.",
            "呢個版本冇記錄任何改動。"
          ),
        })
      );
      return card;
    }

    groupChanges(row.changes).forEach(function (group) {
      var list = el("ul", { class: "cl-changes" });
      group.rows.forEach(function (change) {
        list.appendChild(
          el(
            "li",
            null,
            document.createTextNode(change.summary + " "),
            change.link
              ? shaLink(change.link, change.inherited ? "inherited" : "change", release.version)
              : noSha("change")
          )
        );
      });
      card.appendChild(
        el(
          "div",
          { class: "cl-group" },
          el("h3", {
            class: "cl-action",
            text: actionLabel(group.action) + " · " + group.rows.length,
          }),
          list
        )
      );
    });

    if (row.partial) {
      card.appendChild(
        el("p", {
          class: "cl-partial",
          text: t(
            row.changes.length + " of " + release.changes.length +
              " changes in this release match the search; the rest are hidden.",
            "呢個版本 " + release.changes.length + " 項改動之中有 " + row.changes.length +
              " 項符合搜尋，其餘暫時收埋。"
          ),
        })
      );
    }

    return card;
  }

  function countLine(view) {
    var shown = view.rows.length;
    var total = CATALOGUE.releases.length;
    return graded(
      [
        shown + " / " + total + " releases · " + view.changes + " / " + CATALOGUE.changeCount + " changes",
        shown + " of " + total + " releases · " + view.changes + " of " + CATALOGUE.changeCount + " changes",
        shown + " of " + total + " releases made it through · " + view.changes + " of " +
          CATALOGUE.changeCount + " changes",
      ],
      [
        shown + " / " + total + " 個版本 · " + view.changes + " / " + CATALOGUE.changeCount + " 項改動",
        total + " 個版本入面有 " + shown + " 個 · " + CATALOGUE.changeCount + " 項改動入面有 " + view.changes + " 項",
        total + " 個版本入面殺出 " + shown + " 個 · " + CATALOGUE.changeCount + " 項改動入面有 " + view.changes + " 項",
      ]
    );
  }

  function summaryLine(view) {
    var parts = [];
    parts.push(
      graded(
        [
          "Showing " + rangeSentence() + ", filter: " + filterSentence(view.state) + ".",
          "Showing " + rangeSentence() + ", filter: " + filterSentence(view.state) + ".",
          "On show: " + rangeSentence() + ", filter: " + filterSentence(view.state) + ".",
        ],
        [
          "顯示緊 " + rangeSentenceYue() + "，篩選：" + filterSentence(view.state) + "。",
          "顯示緊 " + rangeSentenceYue() + "，篩選：" + filterSentence(view.state) + "。",
          "而家擺出嚟嘅係 " + rangeSentenceYue() + "，篩選：" + filterSentence(view.state) + "。",
        ]
      )
    );
    if (problems.from) {
      parts.push(t("Start date: ", "開始日期：") + problems.from);
    }
    if (problems.to) {
      parts.push(t("End date: ", "結束日期：") + problems.to);
    }
    if (view.droppedUndated) {
      parts.push(
        t(
          view.droppedUndated + " releases record no date, so a date range cannot include them.",
          "有 " + view.droppedUndated + " 個版本冇記錄日期，所以日期範圍包唔到佢哋。"
        )
      );
    }
    if (CATALOGUE.unnamed) {
      parts.push(
        t(
          CATALOGUE.unnamed + " catalogue rows carry no version and are not listed.",
          "目錄有 " + CATALOGUE.unnamed + " 行冇版本號，冇列出嚟。"
        )
      );
    }
    return parts.join(" ");
  }

  function emptyLine(view) {
    if (!CATALOGUE.loaded) {
      return t(
        "window.AMULET_CHANGELOG is not present on this page, so no release can be listed. changelog-data.js did not load.",
        "呢一頁冇 window.AMULET_CHANGELOG，所以列唔到任何版本。changelog-data.js 冇載入到。"
      );
    }
    if (!CATALOGUE.releases.length) {
      return t(
        "The catalogue loaded and records 0 releases.",
        "目錄載入咗，但入面記錄咗 0 個版本。"
      );
    }
    if (!view.state.valid) {
      return t(
        "That pattern never ran, so nothing was searched: " + (view.state.feedback || "invalid pattern"),
        "個 pattern 冇行過，所以乜都冇搵：" + (view.state.feedback || "invalid pattern")
      );
    }
    var clauses = [];
    if (hasDateFilter()) {
      clauses.push(t("the range " + rangeSentence(), "日期範圍 " + rangeSentenceYue()));
    }
    if (view.state.query) {
      clauses.push(t("the search " + filterSentence(view.state), "搜尋 " + filterSentence(view.state)));
    }
    if (!clauses.length) {
      return t(
        "No release is shown, and no filter is active. All " + CATALOGUE.releases.length +
          " releases in the catalogue were skipped.",
        "冇顯示任何版本，亦冇任何篩選。目錄入面全部 " + CATALOGUE.releases.length + " 個版本都冇顯示。"
      );
    }
    return graded(
      [
        "0 of " + CATALOGUE.releases.length + " releases match " + clauses.join(" and ") + ".",
        "0 of " + CATALOGUE.releases.length + " releases match " + clauses.join(" and ") + ". Widen one of them.",
        "0 of " + CATALOGUE.releases.length + " releases match " + clauses.join(" and ") +
          ". Something has to give — widen the range, or shorten the search.",
      ],
      [
        CATALOGUE.releases.length + " 個版本之中，0 個符合" + clauses.join("同") + "。",
        CATALOGUE.releases.length + " 個版本之中，0 個符合" + clauses.join("同") + "，放寬其中一項試吓。",
        CATALOGUE.releases.length + " 個版本之中，0 個符合" + clauses.join("同") +
          "。總要讓一步：放寬日期，或者搜尋打短啲。",
      ]
    );
  }

  function renderList() {
    var view = computeView();
    lastView = view;
    releaseNodes = {};

    var fragment = document.createDocumentFragment();
    view.rows.forEach(function (row) {
      var card = releaseCard(row);
      releaseNodes[row.release.index] = card;
      fragment.appendChild(card);
    });
    nodes.list.textContent = "";
    nodes.list.appendChild(fragment);

    if (nodes.count) nodes.count.textContent = countLine(view);
    if (nodes.summary) nodes.summary.textContent = summaryLine(view);
    if (nodes.empty) {
      nodes.empty.hidden = view.rows.length !== 0;
      if (!view.rows.length) nodes.empty.textContent = emptyLine(view);
    }
    if (nodes.clear) {
      var active = hasDateFilter() || hasQuery();
      nodes.clear.disabled = !active;
      nodes.clear.title = active
        ? t(
            "Clears the date range and the search query.",
            "清除日期範圍同搜尋內容。"
          )
        : t(
            "Disabled because no date range and no search query are set.",
            "而家冇設定日期範圍，亦冇搜尋內容，所以停用。"
          );
    }
    var exportable = view.rows.length > 0;
    [nodes.copy, nodes.download].forEach(function (button) {
      if (!button) return;
      button.disabled = !exportable;
      button.title = exportable
        ? t(
            "Covers the " + view.rows.length + " releases shown right now.",
            "涵蓋而家顯示緊嘅 " + view.rows.length + " 個版本。"
          )
        : t(
            "Disabled because no release matches the current filter, so there is nothing to write.",
            "而家冇版本符合篩選，冇嘢可以寫，所以停用。"
          );
    });
    return view;
  }

  // -------------------------------------------------------------- calendar
  var FIRST_WEEKDAY = (function () {
    try {
      var locale = new Intl.Locale(navigator.language || "en");
      var info = typeof locale.getWeekInfo === "function" ? locale.getWeekInfo() : locale.weekInfo;
      if (info && typeof info.firstDay === "number") return info.firstDay % 7;
    } catch (error) {
      /* no week information: ISO-8601 Monday is the safe default */
    }
    return 1;
  })();

  function weekdayNames() {
    var sunday = utc(2026, 1, 4);
    sunday -= new Date(sunday).getUTCDay() * DAY; // land on an actual Sunday
    var out = [];
    for (var i = 0; i < 7; i++) {
      var ms = sunday + ((FIRST_WEEKDAY + i) % 7) * DAY;
      var date = new Date(ms);
      out.push({
        short: date.toLocaleDateString(undefined, { weekday: "short", timeZone: "UTC" }),
        long: date.toLocaleDateString(undefined, { weekday: "long", timeZone: "UTC" }),
      });
    }
    return out;
  }

  function clampMs(ms) {
    if (ms < MIN_MS) return MIN_MS;
    if (ms > MAX_MS) return MAX_MS;
    return ms;
  }

  function defaultFocus() {
    if (calendar.target === "to" && bounds.to !== null) return bounds.to;
    if (calendar.target === "from" && bounds.from !== null) return bounds.from;
    if (bounds.from !== null) return bounds.from;
    if (bounds.to !== null) return bounds.to;
    return clampMs(todayMs());
  }

  function buildCalendar(host) {
    var panel = el("div", {
      class: "cl-calendar",
      id: "changelog-calendar",
      role: "dialog",
      "aria-label": t("Date range calendar", "日期範圍月曆"),
      hidden: true,
    });

    calendar.targets.from = el("button", {
      type: "button",
      class: "cl-target",
      "aria-pressed": "true",
      onclick: function () {
        setTarget("from");
      },
    });
    calendar.targets.to = el("button", {
      type: "button",
      class: "cl-target",
      "aria-pressed": "false",
      onclick: function () {
        setTarget("to");
      },
    });
    panel.appendChild(
      el("div", { class: "cl-cal-row", role: "group" }, calendar.targets.from, calendar.targets.to)
    );

    calendar.prev = el("button", {
      type: "button",
      class: "cl-step",
      text: "‹",
      onclick: function () {
        stepMonth(-1);
      },
    });
    calendar.next = el("button", {
      type: "button",
      class: "cl-step",
      text: "›",
      onclick: function () {
        stepMonth(1);
      },
    });
    calendar.monthSelect = el("select", {
      id: "changelog-cal-month",
      "aria-label": t("Jump to month", "跳去邊個月"),
      onchange: function () {
        calendar.view.m = Number(calendar.monthSelect.value);
        calendar.focus = clampMs(
          utc(
            calendar.view.y,
            calendar.view.m,
            Math.min(partsOf(calendar.focus).d, daysInMonth(calendar.view.y, calendar.view.m))
          )
        );
        renderCalendar();
      },
    });
    for (var m = 1; m <= 12; m++) {
      calendar.monthSelect.appendChild(el("option", { value: String(m), text: monthName(m) }));
    }
    calendar.yearSelect = el("select", {
      id: "changelog-cal-year",
      "aria-label": t("Jump to year", "跳去邊一年"),
      onchange: function () {
        calendar.view.y = Number(calendar.yearSelect.value);
        calendar.focus = clampMs(
          utc(
            calendar.view.y,
            calendar.view.m,
            Math.min(partsOf(calendar.focus).d, daysInMonth(calendar.view.y, calendar.view.m))
          )
        );
        renderCalendar();
      },
    });
    for (var y = YEAR_RANGE.low; y <= YEAR_RANGE.high; y++) {
      calendar.yearSelect.appendChild(el("option", { value: String(y), text: String(y) }));
    }
    panel.appendChild(
      el(
        "div",
        { class: "cl-cal-row" },
        calendar.prev,
        calendar.monthSelect,
        calendar.yearSelect,
        calendar.next
      )
    );

    calendar.caption = el("caption");
    calendar.grid = el("table", { role: "grid" });
    calendar.grid.appendChild(calendar.caption);
    panel.appendChild(calendar.grid);

    calendar.hint = el("p", { class: "cl-cal-hint", role: "status" });
    panel.appendChild(
      el(
        "div",
        { class: "cl-cal-foot" },
        el("button", {
          type: "button",
          class: "button button-text",
          text: t("Close", "閂"),
          onclick: function () {
            closeCalendar(true);
          },
        })
      )
    );
    panel.appendChild(calendar.hint);

    calendar.grid.addEventListener("keydown", onGridKey);
    // A view before the panel is ever opened: localiseChrome() paints the grid
    // as part of applying copy, and a null view there would throw.
    calendar.focus = clampMs(todayMs());
    calendar.view = { y: partsOf(calendar.focus).y, m: partsOf(calendar.focus).m };
    host.appendChild(panel);
    return panel;
  }

  function setTarget(which) {
    calendar.target = which;
    calendar.focus = defaultFocus();
    calendar.view = { y: partsOf(calendar.focus).y, m: partsOf(calendar.focus).m };
    renderCalendar();
    focusDay();
  }

  function stepMonth(delta) {
    var y = calendar.view.y;
    var m = calendar.view.m + delta;
    if (m < 1) {
      m = 12;
      y -= 1;
    } else if (m > 12) {
      m = 1;
      y += 1;
    }
    if (y < YEAR_RANGE.low || y > YEAR_RANGE.high) return;
    calendar.view = { y: y, m: m };
    calendar.focus = clampMs(utc(y, m, Math.min(partsOf(calendar.focus).d, daysInMonth(y, m))));
    renderCalendar();
    focusDay();
  }

  function moveFocus(deltaDays, months) {
    var next = calendar.focus;
    if (months) {
      var p = partsOf(next);
      var y = p.y;
      var m = p.m + months;
      while (m < 1) {
        m += 12;
        y -= 1;
      }
      while (m > 12) {
        m -= 12;
        y += 1;
      }
      next = utc(y, m, Math.min(p.d, daysInMonth(y, m)));
    } else {
      next += deltaDays * DAY;
    }
    calendar.focus = clampMs(next);
    var parts = partsOf(calendar.focus);
    calendar.view = { y: parts.y, m: parts.m };
    renderCalendar();
    focusDay();
  }

  function onGridKey(event) {
    if (event.isComposing) return;
    var key = event.key;
    var handled = true;
    if (key === "ArrowLeft") moveFocus(-1);
    else if (key === "ArrowRight") moveFocus(1);
    else if (key === "ArrowUp") moveFocus(-7);
    else if (key === "ArrowDown") moveFocus(7);
    else if (key === "PageUp") moveFocus(0, event.shiftKey ? -12 : -1);
    else if (key === "PageDown") moveFocus(0, event.shiftKey ? 12 : 1);
    else if (key === "Home") moveFocus(-((new Date(calendar.focus).getUTCDay() - FIRST_WEEKDAY + 7) % 7));
    else if (key === "End") moveFocus(6 - ((new Date(calendar.focus).getUTCDay() - FIRST_WEEKDAY + 7) % 7));
    else handled = false;
    if (handled) event.preventDefault();
  }

  function focusDay() {
    if (!calendar.open || !calendar.grid) return;
    var button = calendar.grid.querySelector('button[data-ms="' + calendar.focus + '"]');
    if (button) button.focus();
  }

  function pickDay(ms) {
    var iso = isoOf(ms);
    if (calendar.target === "from") {
      var end = bounds.to;
      writeField("from", iso);
      // A start after the current end swaps the two rather than discarding
      // either. The other field holds something the reader put there, and this
      // control does not get to empty it to make its own choice fit.
      if (end !== null && end < ms) {
        writeField("from", isoOf(end));
        writeField("to", iso);
      }
      calendar.target = "to";
    } else {
      var begin = bounds.from;
      writeField("to", iso);
      if (begin !== null && begin > ms) {
        writeField("to", isoOf(begin));
        writeField("from", iso);
      }
      calendar.target = "from";
    }
    calendar.focus = ms;
    apply(); // repaints the calendar too, because the range it draws just moved
    focusDay();
  }

  function dayState(ms) {
    var isFrom = bounds.from !== null && ms === bounds.from;
    var isTo = bounds.to !== null && ms === bounds.to;
    var inside =
      bounds.from !== null && bounds.to !== null && ms > bounds.from && ms < bounds.to;
    return { endpoint: isFrom || isTo, inside: inside, isFrom: isFrom, isTo: isTo };
  }

  function renderCalendar() {
    if (!calendar.grid) return;
    var view = calendar.view;
    calendar.caption.textContent = monthTitle(view.y, view.m);
    calendar.monthSelect.value = String(view.m);
    calendar.yearSelect.value = String(view.y);

    calendar.prev.disabled = view.y === YEAR_RANGE.low && view.m === 1;
    calendar.next.disabled = view.y === YEAR_RANGE.high && view.m === 12;
    calendar.prev.setAttribute(
      "aria-label",
      calendar.prev.disabled
        ? t(
            "Previous month is unavailable: " + monthTitle(YEAR_RANGE.low, 1) +
              " is the earliest month this catalogue covers.",
            "上一個月用唔到：呢個目錄最早去到 " + monthTitle(YEAR_RANGE.low, 1) + "。"
          )
        : t("Previous month", "上一個月")
    );
    calendar.next.setAttribute(
      "aria-label",
      calendar.next.disabled
        ? t(
            "Next month is unavailable: " + monthTitle(YEAR_RANGE.high, 12) +
              " is the latest month this catalogue covers.",
            "下一個月用唔到：呢個目錄最遲去到 " + monthTitle(YEAR_RANGE.high, 12) + "。"
          )
        : t("Next month", "下一個月")
    );
    if (calendar.prev.disabled) {
      calendar.prev.title = calendar.prev.getAttribute("aria-label");
    } else {
      calendar.prev.removeAttribute("title");
    }
    if (calendar.next.disabled) {
      calendar.next.title = calendar.next.getAttribute("aria-label");
    } else {
      calendar.next.removeAttribute("title");
    }

    var days = weekdayNames();
    var head = el("thead");
    var headRow = el("tr");
    days.forEach(function (day) {
      headRow.appendChild(el("th", { scope: "col", abbr: day.long, text: day.short }));
    });
    head.appendChild(headRow);

    var body = el("tbody");
    var first = utc(view.y, view.m, 1);
    var lead = (new Date(first).getUTCDay() - FIRST_WEEKDAY + 7) % 7;
    var start = first - lead * DAY;
    var today = todayMs();
    var row = null;

    for (var i = 0; i < GRID_CELLS; i++) {
      if (i % 7 === 0) {
        row = el("tr");
        body.appendChild(row);
      }
      var ms = start + i * DAY;
      var parts = partsOf(ms);
      var outside = parts.m !== view.m;
      var flags = dayState(ms);
      var name = longDate(ms);
      if (flags.isFrom) name += t(" — selected as the start date", " — 已選做開始日期");
      if (flags.isTo) name += t(" — selected as the end date", " — 已選做結束日期");
      if (flags.inside) name += t(" — inside the selected range", " — 喺已選範圍入面");
      var button = el("button", {
        type: "button",
        "data-ms": String(ms),
        "data-outside": outside ? "true" : "false",
        "data-range": flags.inside ? "true" : "false",
        "aria-pressed": flags.endpoint ? "true" : "false",
        "aria-label": name,
        tabindex: ms === calendar.focus ? "0" : "-1",
        text: String(parts.d),
      });
      if (ms === today) button.setAttribute("aria-current", "date");
      button.addEventListener("click", function (event) {
        pickDay(Number(event.currentTarget.getAttribute("data-ms")));
      });
      row.appendChild(el("td", { role: "gridcell" }, button));
    }

    calendar.grid.textContent = "";
    calendar.grid.appendChild(calendar.caption);
    calendar.grid.appendChild(head);
    calendar.grid.appendChild(body);

    calendar.targets.from.textContent = t("Set start", "設開始") +
      (bounds.from === null ? "" : " · " + isoOf(bounds.from));
    calendar.targets.to.textContent = t("Set end", "設結束") +
      (bounds.to === null ? "" : " · " + isoOf(bounds.to));
    calendar.targets.from.setAttribute("aria-pressed", calendar.target === "from" ? "true" : "false");
    calendar.targets.to.setAttribute("aria-pressed", calendar.target === "to" ? "true" : "false");

    calendar.hint.textContent =
      calendar.target === "from"
        ? t(
            "The next date you choose becomes the start of the range. Arrow keys move a day, Page Up and Page Down move a month.",
            "你揀嘅下一個日期會做範圍開始。方向鍵一日一日行，Page Up／Page Down 一個月咁行。"
          )
        : t(
            "The next date you choose becomes the end of the range. Arrow keys move a day, Page Up and Page Down move a month.",
            "你揀嘅下一個日期會做範圍結束。方向鍵一日一日行，Page Up／Page Down 一個月咁行。"
          );
  }

  function openCalendar(which, opener) {
    calendar.open = true;
    calendar.opener = opener || null;
    calendar.target = which;
    calendar.focus = defaultFocus();
    var parts = partsOf(calendar.focus);
    calendar.view = { y: parts.y, m: parts.m };
    nodes.calendar.hidden = false;
    updatePickButtons();
    renderCalendar();
    focusDay();
  }

  function closeCalendar(restoreFocus) {
    if (!calendar.open) return;
    calendar.open = false;
    nodes.calendar.hidden = true;
    updatePickButtons();
    if (restoreFocus && calendar.opener && typeof calendar.opener.focus === "function") {
      calendar.opener.focus();
    }
    calendar.opener = null;
  }

  function updatePickButtons() {
    ["from", "to"].forEach(function (which) {
      var button = fields[which] && fields[which].pick;
      if (!button) return;
      var open = calendar.open && calendar.target === which;
      button.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }

  // ------------------------------------------------------------ date fields
  function writeField(which, value) {
    fields[which].input.value = value;
    readField(which);
  }

  function readField(which) {
    var input = fields[which].input;
    var note = fields[which].note;
    var parsed = parseTyped(input.value);
    var hint = fields[which].hint;

    if (parsed.kind === "date") {
      bounds[which] = parsed.ms;
      problems[which] = null;
      note.textContent = hint;
      note.removeAttribute("data-state");
      input.setAttribute("aria-invalid", "false");
      return;
    }
    bounds[which] = null;
    if (parsed.kind === "empty") {
      problems[which] = null;
      note.textContent = hint;
      note.removeAttribute("data-state");
      input.setAttribute("aria-invalid", "false");
      return;
    }
    // Nothing typed is ever rewritten or cleared here: the text stays exactly
    // as it was entered and the bound simply is not applied while it cannot be
    // read as a date.
    var tail = which === "from"
      ? t(" Your text is kept, and no start bound is applied.", " 你打嘅字會保留，暫時冇套用開始日期。")
      : t(" Your text is kept, and no end bound is applied.", " 你打嘅字會保留，暫時冇套用結束日期。");
    problems[which] = parsed.message + tail;
    note.textContent = problems[which];
    note.setAttribute("data-state", "error");
    input.setAttribute("aria-invalid", "true");
  }

  function persist() {
    site.store.set(STORE_KEY, {
      from: fields.from.input.value,
      to: fields.to.input.value,
    });
  }

  function syncPresets() {
    var active = activePreset();
    presetButtons.forEach(function (entry) {
      entry.node.setAttribute("aria-pressed", entry.id === active ? "true" : "false");
    });
  }

  function apply() {
    persist();
    syncPresets();
    if (calendar.open) renderCalendar();
    renderList();
  }

  function applyPreset(id) {
    var range = presetRange(id);
    // Writing the ISO text into the fields is what keeps the two halves in
    // step: a preset that filtered without showing its dates would leave the
    // reader guessing at what "last 30 days" resolved to.
    fields.from.input.value = range.from === null ? "" : isoOf(range.from);
    fields.to.input.value = range.to === null ? "" : isoOf(range.to);
    readField("from");
    readField("to");
    if (calendar.open) {
      calendar.focus = defaultFocus();
      var parts = partsOf(calendar.focus);
      calendar.view = { y: parts.y, m: parts.m };
    }
    apply();
  }

  function clearFilters(silent) {
    fields.from.input.value = "";
    fields.to.input.value = "";
    readField("from");
    readField("to");
    if (nodes.search && nodes.search.value) {
      nodes.search.value = "";
      // The builder's pattern field is the other half of this one query, and it
      // only listens for input events -- assigning .value announces nothing.
      if (typeof window.Event === "function") {
        nodes.search.dispatchEvent(new window.Event("input", { bubbles: true }));
      }
    }
    apply();
    if (!silent) {
      site.notify(
        lang.emoji("🧹") + t("Changelog filters cleared", "更新記錄篩選已清除"),
        t(
          "The date range and the search query were cleared. All " + CATALOGUE.releases.length +
            " releases are listed again.",
          "日期範圍同搜尋內容都清咗，全部 " + CATALOGUE.releases.length + " 個版本重新列出。"
        )
      );
    }
  }

  // ---------------------------------------------------------------- export
  function exportRangeLine(view) {
    var scope =
      view.rows.length + " of " + CATALOGUE.releases.length + " releases, " +
      view.changes + " of " + CATALOGUE.changeCount + " changes";
    var dates = rangeSentence();
    var search = view.state.query
      ? "“" + view.state.query + "” " +
        (view.state.regex ? "(regex, flags " + (view.state.flags || "i") + ")" : "(plain text)")
      : "none";
    return "Exported range: " + dates + " · " + scope + " · search filter: " + search;
  }

  function markdown(view) {
    var lines = [];
    lines.push("# Changelog — Material Minecraft World Editor");
    lines.push("");
    lines.push(exportRangeLine(view));
    if (CATALOGUE.revision) lines.push("Catalogue revision: " + CATALOGUE.revision);
    lines.push("Repository: " + CATALOGUE.repo);
    lines.push("Exported at: " + new Date().toISOString());
    lines.push("");
    view.rows.forEach(function (row) {
      var release = row.release;
      var head = "## " + release.version + " — " + (release.iso || "no release date recorded");
      head += release.sha
        ? " — [" + release.sha.slice(0, SHORT_SHA) + "](" + CATALOGUE.repo + "/commit/" + release.sha + ")"
        : " — no commit recorded";
      lines.push(head);
      lines.push("");
      if (!row.changes.length) {
        lines.push("_This release records no changes._");
        lines.push("");
        return;
      }
      groupChanges(row.changes).forEach(function (group) {
        var name = group.action || "other";
        lines.push("### " + name.charAt(0).toUpperCase() + name.slice(1) + " (" + group.rows.length + ")");
        group.rows.forEach(function (change) {
          var tail = change.link
            ? " ([" + change.link.slice(0, SHORT_SHA) + "](" + CATALOGUE.repo + "/commit/" + change.link + ")" +
              (change.inherited ? ", release commit" : "") + ")"
            : " (no commit recorded)";
          lines.push("- " + change.summary + tail);
        });
        lines.push("");
      });
      if (row.partial) {
        lines.push(
          "_" + row.changes.length + " of " + release.changes.length +
            " changes in this release matched the search filter._"
        );
        lines.push("");
      }
    });
    return lines.join("\n") + "\n";
  }

  /** file:// previews and older browsers can refuse the async clipboard. */
  function legacyCopy(value) {
    var returnTo = document.activeElement;
    var field = el("textarea", {
      tabindex: "-1",
      readonly: true,
      "aria-label": t("Changelog export", "更新記錄匯出"),
    });
    field.value = value;
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

  function reportCopied(view) {
    site.notify(
      lang.emoji("📋") + t("Changelog copied", "更新記錄已複製"),
      // The range line is the artifact's own first line, quoted exactly so the
      // notification and the copied file cannot describe different exports.
      t("Copied as Markdown. ", "已複製成 Markdown。") + exportRangeLine(view),
      "success"
    );
  }

  function reportRefused(reason) {
    site.notify(
      lang.emoji("⛔") + t("Nothing was copied", "冇複製到任何嘢"),
      t(
        "The clipboard refused the copy, so nothing left this page: " + reason,
        "剪貼板拒絕咗，所以冇嘢離開過呢一頁：" + reason
      ),
      "error"
    );
  }

  function copyView() {
    var view = lastView;
    if (!view.rows.length) {
      site.notify(
        lang.emoji("⚠️") + t("Nothing to copy", "冇嘢可以複製"),
        t(
          "No release matches the current filter, so nothing was copied.",
          "冇版本符合而家嘅篩選，所以冇複製到嘢。"
        ),
        "warning"
      );
      return;
    }
    var body = markdown(view);
    var clipboard = navigator.clipboard;
    if (clipboard && typeof clipboard.writeText === "function") {
      clipboard.writeText(body).then(
        function () {
          reportCopied(view);
        },
        function (error) {
          if (legacyCopy(body)) reportCopied(view);
          else reportRefused(String((error && error.message) || error || "permission denied"));
        }
      );
      return;
    }
    if (legacyCopy(body)) reportCopied(view);
    else reportRefused(t("this browser exposes no clipboard write", "呢個瀏覽器冇提供剪貼板寫入"));
  }

  function downloadView() {
    var view = lastView;
    if (!view.rows.length) {
      site.notify(
        lang.emoji("⚠️") + t("Nothing to export", "冇嘢可以匯出"),
        t(
          "No release matches the current filter, so no file was written.",
          "冇版本符合而家嘅篩選，所以冇寫任何檔案。"
        ),
        "warning"
      );
      return;
    }
    var name =
      "changelog-" +
      (bounds.from === null ? "start" : isoOf(bounds.from)) +
      "_" +
      (bounds.to === null ? "latest" : isoOf(bounds.to)) +
      ".md";
    var url = null;
    try {
      var blob = new Blob([markdown(view)], { type: "text/markdown;charset=utf-8" });
      url = URL.createObjectURL(blob);
      var anchor = el("a", { href: url, download: name });
      anchor.style.display = "none";
      document.body.appendChild(anchor);
      anchor.click();
      document.body.removeChild(anchor);
    } catch (error) {
      site.notify(
        lang.emoji("⛔") + t("No file was written", "冇寫到檔案"),
        t(
          "This browser refused the download, so nothing was saved: " +
            ((error && error.message) || String(error)),
          "呢個瀏覽器拒絕咗下載，所以乜都冇儲低：" + ((error && error.message) || String(error))
        ),
        "error"
      );
      return;
    } finally {
      if (url) {
        // Revoked on the next task: revoking synchronously can cancel the
        // download the click just started.
        window.setTimeout(function () {
          URL.revokeObjectURL(url);
        }, 0);
      }
    }
    site.notify(
      lang.emoji("💾") + t("Changelog exported as Markdown", "更新記錄已匯出成 Markdown"),
      t("Written to ", "已寫入 ") + name + " · " + exportRangeLine(view),
      "success"
    );
  }

  // ------------------------------------------------------------------ jump
  function jumpTo(index) {
    site.showTab("changelog");
    var node = releaseNodes[index];
    if (!node) {
      clearFilters(true);
      node = releaseNodes[index];
      if (node) {
        site.notify(
          lang.emoji("🧹") + t("Changelog filters cleared", "更新記錄篩選已清除"),
          t(
            "The filters hid " + CATALOGUE.releases[index].version + ", so they were cleared to reach it.",
            "篩選遮住咗 " + CATALOGUE.releases[index].version + "，所以清咗篩選去搵佢。"
          )
        );
      }
    }
    if (!node) return;
    // Guarded rather than caught: an engine without scrollIntoView throws from
    // the fallback too, and a palette jump that lands on the right card must
    // not die on its way to being polite about how it got there.
    if (typeof node.scrollIntoView === "function") {
      try {
        node.scrollIntoView({ block: "center", behavior: motionSafe() ? "smooth" : "auto" });
      } catch (error) {
        node.scrollIntoView(false);
      }
    }
    node.focus();
    node.style.outline = "3px solid var(--primary)";
    node.style.outlineOffset = "3px";
    window.setTimeout(function () {
      node.style.outline = "";
      node.style.outlineOffset = "";
    }, HIGHLIGHT_MS);
  }

  // ------------------------------------------------------------------ build
  function buildField(which, labelPair) {
    var id = "changelog-" + which;
    var input = el("input", {
      type: "text",
      id: id,
      class: "cl-date",
      maxlength: String(FIELD_MAX),
      autocomplete: "off",
      spellcheck: "false",
      inputmode: "numeric",
      // Deliberately not <input type="date">: this field has to accept a typed
      // locale date and a plain ISO one, report a partial entry inline without
      // throwing the text away, and stay in step with the calendar below. A
      // native picker owns all three of those and reports none of them.
      "aria-describedby": id + "-note",
    });
    var note = el("small", { class: "cl-note", id: id + "-note" });
    var pick = el("button", {
      type: "button",
      class: "cl-pick",
      "aria-haspopup": "dialog",
      "aria-expanded": "false",
      "aria-controls": "changelog-calendar",
    });
    var label = el("label", { for: id });

    // hint is written by localiseChrome(), which owns every piece of copy here.
    fields[which] = { input: input, note: note, pick: pick, label: label, hint: "", labelPair: labelPair };

    input.addEventListener("input", function () {
      readField(which);
      if (bounds[which] !== null && calendar.open) {
        var parts = partsOf(bounds[which]);
        calendar.focus = bounds[which];
        calendar.view = { y: parts.y, m: parts.m };
      }
      apply();
    });

    pick.addEventListener("click", function () {
      if (calendar.open && calendar.target === which) closeCalendar(true);
      else openCalendar(which, pick);
    });

    return el(
      "div",
      { class: "cl-field" },
      label,
      el("div", { class: "cl-input-row" }, input, pick),
      note
    );
  }

  function localiseChrome() {
    if (nodes.presetLegend) {
      nodes.presetLegend.textContent = t("Date range", "日期範圍");
    }
    if (nodes.presetGroup) {
      nodes.presetGroup.setAttribute(
        "aria-label",
        t("Named date ranges", "常用日期範圍")
      );
    }
    presetButtons.forEach(function (entry) {
      entry.node.textContent = t(entry.en, entry.yue);
    });
    ["from", "to"].forEach(function (which) {
      var field = fields[which];
      field.label.textContent = t(field.labelPair[0], field.labelPair[1]);
      field.input.setAttribute("placeholder", LOCALE_FORMAT.example);
      field.pick.textContent = t("Calendar", "月曆");
      field.pick.setAttribute(
        "aria-label",
        which === "from"
          ? t("Pick the start date on the calendar", "喺月曆揀開始日期")
          : t("Pick the end date on the calendar", "喺月曆揀結束日期")
      );
      field.hint = t(
        "Type " + examples() + ", or use the calendar.",
        "打 " + examples() + "，又或者用月曆。"
      );
      readField(which);
    });
    if (nodes.copy) nodes.copy.textContent = t("Copy this view", "複製呢個檢視");
    if (nodes.download) nodes.download.textContent = t("Export as Markdown", "匯出成 Markdown");
    if (nodes.clear) nodes.clear.textContent = t("Clear filters", "清除篩選");
    if (nodes.search) {
      var label = t("Search the changelog", "搜尋更新記錄");
      nodes.search.setAttribute("aria-label", label);
      nodes.search.setAttribute("placeholder", label);
    }
    if (nodes.list) {
      nodes.list.setAttribute("role", "list");
      nodes.list.setAttribute(
        "aria-label",
        t("Releases, in catalogue order", "版本，按目錄記錄嘅次序")
      );
    }
    if (calendar.grid) renderCalendar();
  }

  function buildFilters(host) {
    host.textContent = "";

    nodes.presetLegend = el("p", { class: "cl-legend" });
    nodes.presetGroup = el("div", { class: "cl-presets", role: "group" });
    PRESETS.forEach(function (preset) {
      var button = el("button", {
        type: "button",
        class: "chip",
        "aria-pressed": "false",
        onclick: function () {
          applyPreset(preset.id);
        },
      });
      presetButtons.push({ id: preset.id, node: button, en: preset.en, yue: preset.yue });
      nodes.presetGroup.appendChild(button);
    });

    var range = el("div", { class: "cl-range" });
    range.appendChild(buildField("from", ["Start date", "開始日期"]));
    range.appendChild(buildField("to", ["End date", "結束日期"]));
    nodes.calendar = buildCalendar(range);

    nodes.copy = el("button", {
      type: "button",
      class: "button button-outlined",
      id: "changelog-copy",
      onclick: copyView,
    });
    nodes.download = el("button", {
      type: "button",
      class: "button button-filled",
      id: "changelog-export",
      onclick: downloadView,
    });
    nodes.clear = el("button", {
      type: "button",
      class: "button button-text",
      id: "changelog-clear",
      onclick: function () {
        clearFilters(false);
      },
    });
    nodes.summary = el("p", { class: "cl-summary", role: "status", "aria-live": "polite" });

    host.appendChild(nodes.presetLegend);
    host.appendChild(nodes.presetGroup);
    host.appendChild(range);
    host.appendChild(el("div", { class: "cl-actions" }, nodes.copy, nodes.download, nodes.clear));
    host.appendChild(nodes.summary);
  }

  function attachSearch() {
    var input = nodes.search;
    var openButton = document.getElementById("changelog-regex-open");
    var panel = document.getElementById("changelog-regex");
    if (!input) return;
    if (!site.regex || typeof site.regex.attach !== "function") {
      // Without the shared builder there is no bounded regex surface, so the
      // button that would open one is removed rather than left inert.
      if (openButton) openButton.hidden = true;
      if (panel) panel.hidden = true;
      input.addEventListener("input", renderList);
      return;
    }
    regexControl = site.regex.attach({
      name: "changelog",
      input: input,
      openButton: openButton,
      panel: panel,
      sample: "0.10.29 2026-08-09 adfc760 Upload the exact Squirrel release directory",
      onChange: function () {
        renderList();
      },
    });
    // attach() degrades to plain-text containment when its markup is absent,
    // and that fallback listens to nothing of its own.
    if (!document.querySelector('[data-regex-controls="changelog"]')) {
      input.addEventListener("input", renderList);
    }
  }

  function restore() {
    var saved = site.store.get(STORE_KEY, null);
    if (!saved || typeof saved !== "object") return;
    fields.from.input.value = text(saved.from).slice(0, FIELD_MAX);
    fields.to.input.value = text(saved.to).slice(0, FIELD_MAX);
  }

  function boot() {
    nodes.list = document.getElementById("changelog-list");
    nodes.count = document.getElementById("changelog-count");
    nodes.empty = document.getElementById("changelog-empty");
    nodes.search = document.getElementById("changelog-search");
    var host = document.getElementById("changelog-filters");
    if (!nodes.list || !host) return;

    installStyle();
    buildFilters(host);
    restore();
    localiseChrome();
    attachSearch();
    apply();

    document.addEventListener("keydown", function (event) {
      if (event.key !== "Escape" || !calendar.open) return;
      var palette = document.getElementById("command-palette");
      if (palette && palette.open) return; // the palette dialog owns its own Escape
      event.preventDefault();
      closeCalendar(true);
    });

    document.addEventListener("mousedown", function (event) {
      if (!calendar.open) return;
      if (nodes.calendar.contains(event.target)) return;
      if (fields.from.pick.contains(event.target) || fields.to.pick.contains(event.target)) return;
      closeCalendar(false);
    });

    settings.onChange(function (key) {
      if (key === null || key === "language" || key === "emoji") {
        localiseChrome();
        syncPresets();
        renderList();
        return;
      }
      // A funny level moves the voice of the summary, count and empty state,
      // and nothing else on this page -- the release rows are recorded facts.
      if (key === "funnyEn" || key === "funnyYue") renderList();
    });
  }

  site.ready(boot);

  // --------------------------------------------------------------- palette
  site.registerPaletteSource(function () {
    var kind = t("Release", "版本");
    var items = CATALOGUE.releases.map(function (release) {
      var summary = release.changes.length
        ? release.changes[0].summary
        : t("No changes recorded", "冇記錄改動");
      var detail =
        (release.iso || t("no date recorded", "冇記錄日期")) +
        " · " +
        (release.sha ? release.sha.slice(0, SHORT_SHA) : t("no commit recorded", "冇記錄 commit")) +
        " · " +
        summary;
      var run = function () {
        jumpTo(release.index);
      };
      return {
        id: "changelog:" + release.index,
        kind: kind,
        section: t("Changelog", "更新記錄"),
        tab: "changelog",
        title: release.version,
        label: release.version,
        subtitle: detail,
        detail: detail,
        run: run,
        action: run,
      };
    });

    function command(id, title, detail, run) {
      return {
        id: "changelog:" + id,
        kind: t("Changelog", "更新記錄"),
        section: t("Changelog", "更新記錄"),
        tab: "changelog",
        title: title,
        label: title,
        subtitle: detail,
        detail: detail,
        run: run,
        action: run,
      };
    }

    var shown = lastView.rows.length;
    items.push(
      command(
        "open",
        t("Open the changelog", "開啟更新記錄"),
        t(
          CATALOGUE.releases.length + " releases are catalogued; " + shown + " match the current filter.",
          "目錄有 " + CATALOGUE.releases.length + " 個版本，其中 " + shown + " 個符合而家嘅篩選。"
        ),
        function () {
          site.showTab("changelog");
        }
      ),
      command(
        "copy",
        t("Copy the filtered changelog", "複製篩選後嘅更新記錄"),
        t(
          "Copies " + shown + " releases to the clipboard as Markdown, stating the range.",
          "將 " + shown + " 個版本以 Markdown 複製到剪貼板，並寫明範圍。"
        ),
        function () {
          site.showTab("changelog");
          copyView();
        }
      ),
      command(
        "export",
        t("Export the filtered changelog as Markdown", "將篩選後嘅更新記錄匯出成 Markdown"),
        t(
          "Writes " + shown + " releases to a local .md file, stating the range.",
          "將 " + shown + " 個版本寫成本機 .md 檔，並寫明範圍。"
        ),
        function () {
          site.showTab("changelog");
          downloadView();
        }
      ),
      command(
        "clear",
        t("Clear the changelog filters", "清除更新記錄篩選"),
        t(
          "Clears the date range and the search query.",
          "清除日期範圍同搜尋內容。"
        ),
        function () {
          site.showTab("changelog");
          clearFilters(false);
        }
      )
    );
    return items;
  });
})();
