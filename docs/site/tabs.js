/* Browser-style tab strip: docking, groups, overflow, four searches, bulk close.
 *
 * Owns #tab-strip, the panels it controls, and every stored preference about how
 * that strip is arranged. Every other script changes page through
 * AmuletSite.showTab, which this file takes over from the core stub, and asks
 * about the strip through AmuletSite.tabs.
 *
 * Two things here are genuinely different code rather than a rotation of one
 * idea, and both are where a tab strip usually breaks:
 *
 *   - a side strip is aria-orientation="vertical", so its arrow keys are Up and
 *     Down. A strip that looks right and answers the wrong keys is unusable by
 *     keyboard and photographs perfectly.
 *   - a side strip's overflow measures HEIGHT. The arithmetic is not the width
 *     arithmetic with the axis renamed, so it is written out per axis.
 *
 * The four searches share no state on purpose. One shared query that silently
 * applies to whichever field was last touched is the failure this avoids.
 */
(function () {
  "use strict";

  var A = window.AmuletSite;
  if (!A) return;

  var el = A.el;

  // This page hosts one strip. Naming the surface in the keys is what makes the
  // stored dock a per-surface preference rather than a global one by accident.
  var SURFACE = "primary";

  var TABS = [
    { id: "home", en: "Home", yue: "首頁" },
    { id: "features", en: "Features", yue: "功能" },
    { id: "docs", en: "Docs", yue: "文件" },
    { id: "screenshots", en: "Screenshots", yue: "截圖" },
    { id: "guides", en: "Guides", yue: "指南" },
    { id: "community", en: "Community", yue: "社群" },
    { id: "changelog", en: "Changelog", yue: "變更記錄" },
    { id: "history", en: "History", yue: "歷史" },
    { id: "settings", en: "Settings", yue: "設定" },
    { id: "security", en: "Security", yue: "保安" }
  ];

  var KEY_PINS = "tabs.pinned"; // shipped key, kept so existing pins survive
  var KEY_DOCK = "tabs.dock." + SURFACE;
  var KEY_GROUPS = "tabs.groups." + SURFACE;
  var KEY_ORDER = "tabs.order." + SURFACE;
  var KEY_CLOSED = "tabs.closed." + SURFACE;

  var DOCKS = ["left", "right", "top", "bottom"];
  var DEFAULT_DOCK = "left";
  var NAME_MAX = 60;
  var GAP = 6; // matches the strip's own CSS gap; used by the overflow arithmetic

  var GROUP_COLOURS = ["#4d5f92", "#7d5260", "#3f6b52", "#8a5a2b", "#5b5b7a", "#6d4c8f"];

  var PIN_ON = "★";
  var PIN_OFF = "☆";

  // ------------------------------------------------------------------ state
  var strip = null;
  var bar = null;
  var note = null;
  var toolsRow = null;
  var pinnedRegion = null;
  var flow = null;
  var overflowButton = null;
  var searchLabel = null;
  var searchField = null;
  var searchControl = null;
  var regexPanel = null;
  var regexHome = null;
  var noteHome = null;

  var live = []; // tabs whose panel actually exists in the document
  var nodes = {}; // id -> { tab, wrap, button, label, initial, pin, panel }
  var pinned = [];
  var closed = {};
  var groups = [];
  var groupNodes = {}; // id -> rendered group record
  var order = [];
  var dock = DEFAULT_DOCK;
  var activeId = null;
  var revealed = {}; // ids forced visible inside a collapsed group
  var searchReveal = {}; // ids a live query is revealing, cleared when it clears
  var overflowed = [];
  var measuring = false;
  var measureQueued = 0;
  var groupSeq = 0;
  var storageWarned = false;

  function t(en, yue) {
    return A.lang.t(en, yue);
  }

  function emoji(glyph) {
    return A.lang.emoji(glyph);
  }

  function labelOf(tab) {
    return t(tab.en, tab.yue);
  }

  function tabOf(id) {
    return nodes[id] ? nodes[id].tab : null;
  }

  function isPinned(id) {
    return pinned.indexOf(id) >= 0;
  }

  function isClosed(id) {
    return closed[id] === true;
  }

  function isVertical() {
    return dock === "left" || dock === "right";
  }

  function prefersReduced() {
    if (A.settings.get("reducedMotion")) return true;
    try {
      return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    } catch (error) {
      return false;
    }
  }

  function count(n, one, many) {
    return n + " " + (n === 1 ? one : many);
  }

  // ---------------------------------------------------------------- storage
  function refused() {
    if (storageWarned) return;
    storageWarned = true;
    A.notify(
      emoji("⚠️") + t("The tab layout is not being saved", "分頁版面儲唔到"),
      t(
        "This browser refused local storage, so the dock, groups, pinned order and closed tabs return to the shipped arrangement on reload.",
        "呢個瀏覽器唔畀用本機儲存，所以停靠位置、分組、釘住次序同已關閉分頁重新載入之後會回復原狀。"
      )
    );
  }

  function put(key, value) {
    if (!A.store.set(key, value)) refused();
  }

  function persistPins() {
    put(KEY_PINS, pinned);
  }

  function persistGroups() {
    put(
      KEY_GROUPS,
      groups.map(function (group) {
        return {
          id: group.id,
          name: group.name,
          colour: group.colour,
          collapsed: group.collapsed === true,
          members: group.members.slice()
        };
      })
    );
  }

  function persistOrder() {
    put(KEY_ORDER, order.slice());
  }

  function persistClosed() {
    put(
      KEY_CLOSED,
      Object.keys(closed).filter(function (id) {
        return closed[id] === true;
      })
    );
  }

  function persistDock() {
    put(KEY_DOCK, dock);
  }

  // ------------------------------------------------------------- validation
  function normaliseHex(value) {
    var raw = String(value == null ? "" : value).trim();
    if (/^#[0-9a-f]{3}$/i.test(raw)) {
      raw =
        "#" +
        raw.charAt(1) + raw.charAt(1) +
        raw.charAt(2) + raw.charAt(2) +
        raw.charAt(3) + raw.charAt(3);
    }
    return /^#[0-9a-f]{6}$/i.test(raw) ? raw.toLowerCase() : null;
  }

  function channel(value) {
    var part = value / 255;
    return part <= 0.03928 ? part / 12.92 : Math.pow((part + 0.055) / 1.055, 2.4);
  }

  /** Header text is measured against the chosen colour, never assumed white. */
  function readableOn(hex) {
    var raw = hex.slice(1);
    var lum =
      0.2126 * channel(parseInt(raw.slice(0, 2), 16)) +
      0.7152 * channel(parseInt(raw.slice(2, 4), 16)) +
      0.0722 * channel(parseInt(raw.slice(4, 6), 16));
    var onWhite = 1.05 / (lum + 0.05);
    var onBlack = (lum + 0.05) / 0.05;
    return onBlack >= onWhite ? "#000000" : "#ffffff";
  }

  function cleanName(value, fallback) {
    var raw = String(value == null ? "" : value).replace(/\s+/g, " ").trim();
    if (!raw) return fallback;
    return raw.slice(0, NAME_MAX);
  }

  function readPins() {
    var raw = A.store.get(KEY_PINS, []);
    if (!Array.isArray(raw)) return [];
    var seen = {};
    var out = [];
    raw.forEach(function (id) {
      if (typeof id !== "string" || !nodes[id] || seen[id]) return;
      seen[id] = true;
      out.push(id);
    });
    return out;
  }

  function readClosed() {
    var raw = A.store.get(KEY_CLOSED, []);
    var out = {};
    if (!Array.isArray(raw)) return out;
    raw.forEach(function (id) {
      if (typeof id === "string" && nodes[id]) out[id] = true;
    });
    return out;
  }

  function readDock() {
    var raw = A.store.get(KEY_DOCK, DEFAULT_DOCK);
    return DOCKS.indexOf(raw) >= 0 ? raw : DEFAULT_DOCK;
  }

  function readGroups() {
    var raw = A.store.get(KEY_GROUPS, []);
    if (!Array.isArray(raw)) return [];
    var seenGroup = {};
    var seenMember = {};
    var out = [];
    raw.forEach(function (row) {
      if (!row || typeof row !== "object") return;
      var id = typeof row.id === "string" && /^g[0-9]{1,6}$/.test(row.id) ? row.id : null;
      if (!id || seenGroup[id]) return;
      seenGroup[id] = true;
      var members = [];
      var list = Array.isArray(row.members) ? row.members : [];
      list.forEach(function (member) {
        // A tab can belong to one group. Storage is editable by hand, so a tab
        // listed twice is kept once rather than rendered in two places.
        if (typeof member !== "string" || !nodes[member] || seenMember[member]) return;
        seenMember[member] = true;
        members.push(member);
      });
      var index = out.length % GROUP_COLOURS.length;
      out.push({
        id: id,
        name: cleanName(row.name, "Group " + (out.length + 1)),
        colour: normaliseHex(row.colour) || GROUP_COLOURS[index],
        collapsed: row.collapsed === true,
        members: members
      });
      var number = Number(id.slice(1));
      if (number > groupSeq) groupSeq = number;
    });
    return out;
  }

  function groupOf(id) {
    for (var i = 0; i < groups.length; i++) {
      if (groups[i].members.indexOf(id) >= 0) return groups[i];
    }
    return null;
  }

  function groupById(id) {
    for (var i = 0; i < groups.length; i++) {
      if (groups[i].id === id) return groups[i];
    }
    return null;
  }

  /** The canonical flow: every group and every ungrouped tab, exactly once. */
  function rebuildOrder() {
    var seen = {};
    var out = [];
    order.forEach(function (token) {
      if (typeof token !== "string" || seen[token]) return;
      if (token.slice(0, 4) === "tab:") {
        var id = token.slice(4);
        if (!nodes[id] || groupOf(id)) return;
        seen[token] = true;
        out.push(token);
      } else if (token.slice(0, 6) === "group:") {
        var gid = token.slice(6);
        if (!groupById(gid)) return;
        seen[token] = true;
        out.push(token);
      }
    });
    groups.forEach(function (group) {
      var token = "group:" + group.id;
      if (!seen[token]) {
        seen[token] = true;
        out.push(token);
      }
    });
    live.forEach(function (tab) {
      var token = "tab:" + tab.id;
      if (!seen[token] && !groupOf(tab.id)) {
        seen[token] = true;
        out.push(token);
      }
    });
    order = out;
    return out;
  }

  function orderedIds() {
    var head = pinned.slice();
    var tail = [];
    rebuildOrder().forEach(function (token) {
      if (token.slice(0, 4) === "tab:") {
        var id = token.slice(4);
        if (head.indexOf(id) < 0) tail.push(id);
      } else {
        var group = groupById(token.slice(6));
        if (!group) return;
        group.members.forEach(function (id) {
          if (head.indexOf(id) < 0) tail.push(id);
        });
      }
    });
    return head.concat(tail);
  }

  function openIds() {
    return orderedIds().filter(function (id) {
      return !isClosed(id);
    });
  }

  // ------------------------------------------------------------------ style
  var STYLE_ID = "tabs-style";
  var CSS = [
    ":root{--tab-rail-width:236px;--tab-rail-narrow:64px;--tab-rail-height:0px}",

    // The strip measures its own overflow, so it must not wrap or clip silently.
    "#tab-strip{flex-wrap:nowrap;overflow:hidden;align-items:center;min-width:0}",
    ".tab-region{display:flex;align-items:center;gap:6px;min-width:0;min-height:0}",
    ".tab-pinned:empty{display:none}",
    ".tab-flow{flex:0 1 auto}",
    '.tab-wrap[data-overflow="true"],.tab-group[data-overflow="true"]{display:none}',
    ".tab-initial{display:none}",
    ".tab-tools{display:flex;align-items:center;gap:6px;flex:0 0 auto;flex-wrap:wrap}",
    ".tab-tool{display:inline-flex;align-items:center;gap:6px;min-height:36px;padding:0 12px;border:1px solid var(--outline);border-radius:var(--r-full,999px);background:var(--surface-container);color:var(--on-surface-variant);font:inherit;font-size:.82rem;font-weight:650;cursor:pointer}",
    ".tab-tool:hover{background:var(--state-layer);color:var(--on-surface)}",
    '.tab-tool[aria-expanded="true"]{background:var(--primary-container);color:var(--on-primary-container)}',
    ".tab-rail-toggle{display:none}",

    // Groups
    ".tab-group{display:flex;flex-direction:column;gap:4px;min-width:0;padding:4px;border:1px solid var(--outline-variant,var(--outline));border-radius:var(--r-md,12px)}",
    ".tab-group-head{display:flex;align-items:center;gap:4px;min-width:0}",
    ".tab-group-toggle{display:inline-flex;align-items:center;gap:8px;flex:1 1 auto;min-width:0;min-height:32px;padding:0 10px;border:0;border-radius:var(--r-sm,8px);background:transparent;color:inherit;font:inherit;font-size:.82rem;font-weight:700;text-align:left;cursor:pointer}",
    ".tab-group-toggle:hover{background:var(--state-layer)}",
    ".tab-group-dot{flex:0 0 auto;width:12px;height:12px;border-radius:50%}",
    ".tab-group-name{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}",
    ".tab-group-count{flex:0 0 auto;opacity:.75;font-variant-numeric:tabular-nums;font-weight:600}",
    ".tab-group-find{flex:0 0 auto;min-width:30px;height:30px;padding:0 6px;border:1px solid var(--outline);border-radius:var(--r-xs,6px);background:var(--surface-container);color:var(--on-surface-variant);font:inherit;font-size:.8rem;cursor:pointer}",
    '.tab-group-find[aria-expanded="true"]{background:var(--primary-container);color:var(--on-primary-container)}',
    ".tab-group-search{display:flex;flex-direction:column;gap:6px;min-width:0}",
    ".tab-group-search[hidden]{display:none}",
    ".tab-group-note{margin:0;color:var(--on-surface-variant);font-size:.74rem}",
    ".tab-group-note:empty{display:none}",
    ".tab-group-body{display:flex;align-items:center;gap:4px;min-width:0}",
    ".tab-group-body:empty::after{content:attr(data-empty);color:var(--on-surface-variant);font-size:.74rem;padding:0 8px}",
    '.tab-group[data-drop="true"]{outline:3px dashed var(--primary);outline-offset:2px}',
    '.tab-wrap[data-dragging="true"]{opacity:.5}',

    // Vertical rails
    ':root[data-tab-dock="left"] .tab-bar,:root[data-tab-dock="right"] .tab-bar{position:fixed;top:0;bottom:0;width:var(--tab-rail-width);flex-direction:column;flex-wrap:nowrap;align-items:stretch;justify-content:flex-start;gap:10px;padding:10px 8px;overflow:auto;z-index:45;border-bottom:0}',
    ':root[data-tab-dock="left"] .tab-bar{left:0;border-right:1px solid var(--outline)}',
    ':root[data-tab-dock="right"] .tab-bar{right:0;border-left:1px solid var(--outline)}',
    ':root[data-tab-dock="left"] body{padding-left:var(--tab-rail-width)}',
    ':root[data-tab-dock="right"] body{padding-right:var(--tab-rail-width)}',
    ':root[data-tab-dock="left"] .skip-link:focus{left:var(--tab-rail-width)}',
    ':root[data-tab-dock="left"] #tab-strip,:root[data-tab-dock="right"] #tab-strip{flex-direction:column;flex-wrap:nowrap;align-items:stretch;flex:1 1 auto;width:100%;min-height:0;overflow:hidden}',
    ':root[data-tab-dock="left"] .tab-region,:root[data-tab-dock="right"] .tab-region{flex-direction:column;flex-wrap:nowrap;align-items:stretch;width:100%}',
    ':root[data-tab-dock="left"] .tab-group-body,:root[data-tab-dock="right"] .tab-group-body{flex-direction:column;flex-wrap:nowrap;align-items:stretch;width:100%}',
    ':root[data-tab-dock="left"] .tab-wrap,:root[data-tab-dock="right"] .tab-wrap{flex:0 0 auto;width:100%;justify-content:space-between}',
    ':root[data-tab-dock="left"] [role="tab"],:root[data-tab-dock="right"] [role="tab"]{flex:1 1 auto;min-width:0;justify-content:flex-start}',
    ':root[data-tab-dock="left"] .tab-label,:root[data-tab-dock="right"] .tab-label{overflow:hidden;text-overflow:ellipsis;min-width:0}',
    ':root[data-tab-dock="left"] .tab-tools,:root[data-tab-dock="right"] .tab-tools{flex-direction:column;align-items:stretch}',
    ':root[data-tab-dock="left"] .search-field-sm,:root[data-tab-dock="right"] .search-field-sm{flex:0 0 auto;width:auto}',

    // Bottom rail
    ':root[data-tab-dock="bottom"] .tab-bar{position:fixed;left:0;right:0;bottom:0;z-index:45;flex-direction:column;align-items:stretch;max-height:62vh;overflow:auto;border-top:1px solid var(--outline);border-bottom:0}',
    ':root[data-tab-dock="bottom"] body{padding-bottom:var(--tab-rail-height)}',

    // Docked anywhere but the top edge, the builder and the note travel with the
    // field they belong to, so the page gutters the shipped rule adds must go.
    ':root:not([data-tab-dock="top"]) #tab-regex{margin-left:0;margin-right:0}',
    ':root:not([data-tab-dock="top"]) .tab-note{margin:0}',

    // A narrow rail collapses to initials. The label is hidden, never rotated;
    // each tab button carries its own aria-label so the name survives.
    "@media (max-width:760px){",
    ':root[data-tab-dock="left"]:not([data-tab-rail="expanded"]) .tab-bar,:root[data-tab-dock="right"]:not([data-tab-rail="expanded"]) .tab-bar{width:var(--tab-rail-narrow);padding-left:6px;padding-right:6px}',
    ':root[data-tab-dock="left"]:not([data-tab-rail="expanded"]) body{padding-left:var(--tab-rail-narrow)}',
    ':root[data-tab-dock="right"]:not([data-tab-rail="expanded"]) body{padding-right:var(--tab-rail-narrow)}',
    ':root[data-tab-dock="left"]:not([data-tab-rail="expanded"]) .skip-link:focus{left:var(--tab-rail-narrow)}',
    ':root[data-tab-dock="left"]:not([data-tab-rail="expanded"]) .tab-label,:root[data-tab-dock="right"]:not([data-tab-rail="expanded"]) .tab-label{display:none}',
    ':root[data-tab-dock="left"]:not([data-tab-rail="expanded"]) .tab-initial,:root[data-tab-dock="right"]:not([data-tab-rail="expanded"]) .tab-initial{display:inline-grid;place-items:center;min-width:20px;font-weight:750}',
    ':root[data-tab-dock="left"]:not([data-tab-rail="expanded"]) .tab-group-name,:root[data-tab-dock="right"]:not([data-tab-rail="expanded"]) .tab-group-name{display:none}',
    ':root[data-tab-dock="left"]:not([data-tab-rail="expanded"]) .tab-strip-search,:root[data-tab-dock="right"]:not([data-tab-rail="expanded"]) .tab-strip-search{display:none}',
    ':root[data-tab-dock="left"]:not([data-tab-rail="expanded"]) #tab-regex,:root[data-tab-dock="right"]:not([data-tab-rail="expanded"]) #tab-regex{display:none}',
    ':root[data-tab-dock="left"]:not([data-tab-rail="expanded"]) .tab-tool-label,:root[data-tab-dock="right"]:not([data-tab-rail="expanded"]) .tab-tool-label{display:none}',
    ':root[data-tab-dock="left"] .tab-rail-toggle,:root[data-tab-dock="right"] .tab-rail-toggle{display:inline-flex}',
    "}",

    // Panels: an overlay that paints nothing lets the page read through it.
    ".tab-panel{position:fixed;z-index:120;display:flex;flex-direction:column;gap:10px;width:min(420px,calc(100vw - 24px));max-height:calc(100vh - 24px);padding:12px;border:1px solid var(--outline);border-radius:var(--r-md,12px);background:var(--surface-container-high,var(--surface-container,#e9e7ee));color:var(--on-surface,#1a1b20);box-shadow:0 14px 38px rgba(0,0,0,.3)}",
    ".tab-panel[hidden]{display:none}",
    ".tab-panel-head{display:flex;align-items:center;justify-content:space-between;gap:12px}",
    ".tab-panel-head h2{margin:0;font-size:.98rem}",
    ".tab-panel-body{display:flex;flex-direction:column;gap:10px;min-height:0;overflow:auto}",
    ".tab-panel-close{flex:0 0 auto;min-width:34px;height:34px;border:1px solid var(--outline);border-radius:var(--r-xs,6px);background:transparent;color:inherit;font:inherit;cursor:pointer}",
    ".tab-panel-list{display:flex;flex-direction:column;gap:4px;min-height:0}",
    ".tab-option{display:flex;align-items:center;gap:10px;width:100%;min-height:40px;padding:6px 10px;border:1px solid transparent;border-radius:var(--r-sm,8px);background:transparent;color:inherit;font:inherit;text-align:left;cursor:pointer}",
    ".tab-option:hover{background:var(--state-layer)}",
    '.tab-option[aria-selected="true"],.tab-option:focus-visible{border-color:var(--primary)}',
    ".tab-option-main{display:flex;flex-direction:column;gap:2px;min-width:0;flex:1 1 auto}",
    ".tab-option-title{font-weight:650;overflow-wrap:anywhere}",
    ".tab-option-meta{font-size:.74rem;color:var(--on-surface-variant);overflow-wrap:anywhere}",
    ".tab-swatch{flex:0 0 auto;width:14px;height:14px;border-radius:50%;border:1px solid var(--outline)}",
    ".tab-panel-note{margin:0;font-size:.78rem;color:var(--on-surface-variant)}",
    '.tab-panel-note[data-state="error"]{color:#8c1d18;font-weight:700}',
    '.dark .tab-panel-note[data-state="error"]{color:#ffb4ab}',
    ".tab-panel-actions{display:flex;gap:8px;flex-wrap:wrap;align-items:center}",
    ".tab-panel-row{display:flex;align-items:center;gap:8px;flex-wrap:wrap}",
    ".tab-panel-row label{font-size:.78rem;font-weight:650;color:var(--secondary,var(--on-surface-variant))}",
    ".tab-panel input[type=text],.tab-panel input[type=search]{min-width:8rem;flex:1 1 8rem;min-height:36px;border:1px solid var(--outline);border-radius:var(--r-xs,6px);padding:0 10px;background:transparent;color:inherit;font:inherit}",
    ".tab-panel input[type=color]{min-width:52px;min-height:36px;padding:2px;border:1px solid var(--outline);border-radius:var(--r-xs,6px);background:transparent}",
    ".tab-panel .regex-builder{margin:0}",
    '.tab-danger[data-armed="true"]{background:#8c1d18;color:#fff;border-color:#8c1d18}',
    ".tab-preview{display:flex;flex-direction:column;gap:2px;max-height:190px;overflow:auto;padding:6px;border:1px solid var(--outline);border-radius:var(--r-xs,6px)}",
    ".tab-preview-row{display:flex;align-items:center;justify-content:space-between;gap:10px;font-size:.8rem}",
    ".tab-preview-flag{font-size:.72rem;color:var(--on-surface-variant)}",
    ".tab-panel :focus-visible{outline:3px solid var(--primary);outline-offset:2px}",
    ".tab-panel [disabled],.tab-tool[disabled]{opacity:.62;cursor:not-allowed}",
    ".tab-option-static{cursor:default}",

    // Every class above sets its own display, and each one outranks the shipped
    // [hidden] rule on source order. A hidden control that still renders is the
    // whole reason this list has to name each of them.
    ".tab-tool[hidden],.tab-region[hidden],.tab-group[hidden],.tab-group-head[hidden]," +
      ".tab-group-body[hidden],.tab-option[hidden],.tab-panel-list[hidden]," +
      ".tab-panel-actions[hidden],.tab-panel-row[hidden],.tab-preview[hidden]," +
      ".tab-tools[hidden],.tab-panel-body[hidden]{display:none}"
  ].join("");

  function installStyle() {
    if (document.getElementById(STYLE_ID)) return;
    var style = el("style", { id: STYLE_ID });
    style.textContent = CSS;
    (document.head || document.documentElement).appendChild(style);
  }

  // ----------------------------------------------------------- search plumbing
  /**
   * One attachment point for all four searches. Each caller passes its own name,
   * so each gets its own persisted mode, its own pattern and its own feedback.
   */
  function attachSearch(config) {
    var input = config.input;
    var report = typeof config.onChange === "function" ? config.onChange : function () {};

    if (A.regex && typeof A.regex.attach === "function") {
      var handle = A.regex.attach({
        name: config.name,
        input: input,
        openButton: config.openButton,
        panel: config.panel,
        sample: config.sample,
        onChange: report
      });
      // attach() degrades to plain-text containment when its own controls are
      // missing, and that fallback wires no listener -- so typing needs a reader.
      if (!document.querySelector('[data-regex-controls="' + config.name + '"]')) {
        input.addEventListener("input", function () {
          report(handle.state());
        });
      }
      return handle;
    }

    // No builder script on the page: the control that would open one is removed
    // rather than left looking live, and the field still filters.
    if (config.openButton) config.openButton.hidden = true;
    if (config.panel) config.panel.hidden = true;
    var plain = {
      state: function () {
        return { query: input.value, regex: false, flags: "i", valid: true, feedback: "", matcher: null };
      },
      matches: function (text) {
        try {
          return A.matcher(input.value, false, "i").test(String(text == null ? "" : text));
        } catch (error) {
          return false;
        }
      },
      refresh: function () {}
    };
    input.addEventListener("input", function () {
      report(plain.state());
    });
    return plain;
  }

  function stateOf(control, input) {
    try {
      if (control && typeof control.state === "function") {
        var state = control.state() || {};
        return {
          query: state.query == null ? "" : String(state.query),
          regex: state.regex === true,
          flags: state.flags == null ? "i" : String(state.flags),
          valid: state.valid !== false,
          feedback: state.feedback ? String(state.feedback) : ""
        };
      }
    } catch (error) {
      /* a broken control must not take its surface down with it */
    }
    return { query: input ? input.value : "", regex: false, flags: "i", valid: true, feedback: "" };
  }

  function hits(control, text) {
    if (!control || typeof control.matches !== "function") return false;
    try {
      return control.matches(text) === true;
    } catch (error) {
      return false;
    }
  }

  function modeSentence(state) {
    if (!state.query) return t("no filter", "冇篩選");
    return state.regex
      ? t("regular expression, flags " + (state.flags || "i"), "正則表達式，flags " + (state.flags || "i"))
      : t("plain text", "純文字");
  }

  function searchRow(config) {
    var input = el("input", {
      type: "search",
      id: config.id,
      autocomplete: "off",
      maxlength: "256",
      "aria-label": config.label,
      placeholder: config.label
    });
    var openButton = el("button", {
      type: "button",
      class: "regex-open",
      id: config.id + "-regex-open",
      "aria-label": config.builderLabel,
      "aria-expanded": "false",
      "aria-controls": config.id + "-regex",
      text: ".*"
    });
    var label = el(
      "label",
      { class: "search-field search-field-sm", for: config.id },
      el("span", { "aria-hidden": "true", text: "⌕" }),
      input,
      openButton
    );
    var panel = el(
      "details",
      { class: "regex-builder", id: config.id + "-regex" },
      el("summary", { text: config.builderLabel }),
      el("div", { class: "regex-controls", "data-regex-controls": config.name })
    );
    return {
      input: input,
      openButton: openButton,
      panel: panel,
      label: label,
      summary: panel.firstChild,
      nodes: [label, panel]
    };
  }

  // ------------------------------------------------------------------ panels
  var openPanelRecord = null;

  /** Every element has a focus method; only some of them answer it. */
  function focusable(node) {
    if (!node || node.nodeType !== 1 || typeof node.focus !== "function") return false;
    if (node.disabled || node.hidden) return false;
    if (typeof node.tabIndex === "number" && node.tabIndex >= 0) return true;
    return /^(BUTTON|A|INPUT|SELECT|TEXTAREA|SUMMARY)$/.test(node.tagName);
  }

  function panelOpen(record) {
    return openPanelRecord === record && !record.root.hidden;
  }

  function closeOpenPanel(restoreFocus) {
    var record = openPanelRecord;
    if (!record) return;
    openPanelRecord = null;
    record.root.hidden = true;
    document.removeEventListener("pointerdown", record.onOutside, true);
    document.removeEventListener("keydown", record.onKey, true);
    window.removeEventListener("resize", record.onViewport, true);
    window.removeEventListener("scroll", record.onViewport, true);
    if (record.trigger && record.trigger.hasAttribute("aria-expanded")) {
      record.trigger.setAttribute("aria-expanded", "false");
    }
    if (typeof record.onClose === "function") record.onClose();
    var back = record.returnTo;
    record.returnTo = null;
    record.trigger = null;
    if (restoreFocus !== false && back && back.isConnected && focusable(back)) {
      try {
        back.focus();
      } catch (error) {
        /* a detached opener simply cannot take focus back */
      }
    }
  }

  function positionPanel(root, anchor) {
    root.style.left = "0px";
    root.style.top = "0px";
    var box = root.getBoundingClientRect();
    var margin = 10;
    var point = { x: margin, y: margin };
    if (anchor && anchor.getBoundingClientRect) {
      var rect = anchor.getBoundingClientRect();
      point = isVertical() && (dock === "left" || dock === "right")
        ? { x: dock === "right" ? rect.left - box.width - 6 : rect.right + 6, y: rect.top }
        : { x: rect.left, y: rect.bottom + 6 };
    }
    var left = Math.min(point.x, window.innerWidth - box.width - margin);
    var top = Math.min(point.y, window.innerHeight - box.height - margin);
    root.style.left = Math.max(margin, left) + "px";
    root.style.top = Math.max(margin, top) + "px";
  }

  function makePanel(id, titleText) {
    var heading = el("h2", { id: id + "-title", text: titleText });
    var body = el("div", { class: "tab-panel-body" });
    var closeButton = el("button", {
      type: "button",
      class: "tab-panel-close",
      text: "×",
      onclick: function () {
        closeOpenPanel(true);
      }
    });
    var root = el(
      "div",
      {
        class: "tab-panel",
        id: id,
        role: "dialog",
        "aria-modal": "false",
        "aria-labelledby": id + "-title",
        hidden: true
      },
      el("div", { class: "tab-panel-head" }, heading, closeButton),
      body
    );

    var record = {
      root: root,
      body: body,
      heading: heading,
      closeButton: closeButton,
      trigger: null,
      returnTo: null,
      onClose: null,
      onOutside: function (event) {
        if (root.contains(event.target)) return;
        // The trigger's own click toggles the panel. Closing here first would
        // make that click reopen what the user just asked to close.
        if (record.trigger && record.trigger.contains(event.target)) return;
        closeOpenPanel(false);
      },
      onKey: function (event) {
        if (event.key !== "Escape") return;
        event.preventDefault();
        event.stopPropagation();
        closeOpenPanel(true);
      },
      onViewport: function (event) {
        if (event && event.target && root.contains(event.target)) return;
        positionPanel(root, record.anchor);
      },
      anchor: null
    };

    document.body.appendChild(root);
    return record;
  }

  function openPanel(record, options) {
    var opts = options || {};
    if (openPanelRecord && openPanelRecord !== record) closeOpenPanel(false);
    else if (openPanelRecord === record) {
      closeOpenPanel(true);
      return false;
    }
    record.anchor = opts.anchor || null;
    record.trigger = opts.trigger || null;
    var back = opts.returnTo || opts.trigger;
    record.returnTo = focusable(back) ? back : document.activeElement;
    record.onClose = opts.onClose || null;
    record.root.hidden = false;
    if (record.trigger && record.trigger.hasAttribute("aria-expanded")) {
      record.trigger.setAttribute("aria-expanded", "true");
    }
    openPanelRecord = record;
    positionPanel(record.root, record.anchor);
    document.addEventListener("pointerdown", record.onOutside, true);
    document.addEventListener("keydown", record.onKey, true);
    window.addEventListener("resize", record.onViewport, true);
    window.addEventListener("scroll", record.onViewport, true);
    if (typeof opts.focus === "function") opts.focus();
    return true;
  }

  /** Arrow/Home/End over a rendered option list, with Enter handled natively. */
  function listKeys(container) {
    container.addEventListener("keydown", function (event) {
      var key = event.key;
      if (key !== "ArrowDown" && key !== "ArrowUp" && key !== "Home" && key !== "End") return;
      // Buttons only: a rendered row that carries no action cannot take focus,
      // and stepping onto one would strand the arrow keys there.
      var items = Array.prototype.slice.call(container.querySelectorAll("button.tab-option:not([disabled])"));
      if (!items.length) return;
      event.preventDefault();
      var at = items.indexOf(document.activeElement);
      var next =
        key === "Home" ? items[0]
        : key === "End" ? items[items.length - 1]
        : items[(at + (key === "ArrowDown" ? 1 : -1) + items.length) % items.length];
      if (next) next.focus();
    });
  }

  function optionButton(config) {
    var main = el(
      "span",
      { class: "tab-option-main" },
      el("span", { class: "tab-option-title", text: config.title }),
      config.meta ? el("span", { class: "tab-option-meta", text: config.meta }) : null
    );
    var button = el("button", {
      type: "button",
      class: "tab-option",
      "aria-label": config.meta ? config.title + ". " + config.meta : config.title,
      onclick: config.run
    });
    if (config.colour) {
      button.appendChild(
        el("span", { class: "tab-swatch", "aria-hidden": "true", style: "background:" + config.colour })
      );
    }
    button.appendChild(main);
    return button;
  }

  function emptyNote(text) {
    return el("p", { class: "tab-panel-note", text: text });
  }

  // ------------------------------------------------------------- tab nodes
  function buildNodes() {
    TABS.forEach(function (tab) {
      var panel = document.getElementById(tab.id);
      if (!panel) return; // no panel, no tab: a tab that controls nothing is a lie

      var labelNode = el("span", { class: "tab-label", text: tab.en });
      var initialNode = el("span", { class: "tab-initial", "aria-hidden": "true", text: tab.en.charAt(0) });
      var button = el(
        "button",
        {
          type: "button",
          class: "tab",
          role: "tab",
          id: "tab-" + tab.id,
          "data-tab": tab.id,
          "aria-controls": tab.id,
          "aria-selected": "false",
          tabindex: "-1"
        },
        initialNode,
        labelNode
      );
      var pin = el("button", {
        type: "button",
        class: "tab-pin",
        "data-tab": tab.id,
        "aria-pressed": "false",
        tabindex: "-1",
        text: PIN_OFF
      });
      // role=presentation keeps the wrapper out of the accessibility tree so the
      // tablist's children read as tabs rather than as generic containers.
      var wrap = el("div", { class: "tab-wrap", role: "presentation", draggable: "true" }, button, pin);

      button.addEventListener("click", function () {
        activate(tab.id, { focusPanel: true });
      });
      button.addEventListener("keydown", onTabKeyDown);
      pin.addEventListener("click", function () {
        togglePin(tab.id);
      });
      wrap.addEventListener("contextmenu", function (event) {
        event.preventDefault();
        A.contextMenu(tabMenuItems(tab.id), event, t("Tab menu", "分頁選單"));
      });
      wireTabDrag(wrap, tab.id);

      nodes[tab.id] = {
        tab: tab,
        wrap: wrap,
        button: button,
        label: labelNode,
        initial: initialNode,
        pin: pin,
        panel: panel
      };
      live.push(tab);
    });
  }

  // -------------------------------------------------------------- drag & drop
  var dragging = null;

  function markDrop(node, on) {
    if (!node) return;
    if (on) node.setAttribute("data-drop", "true");
    else node.removeAttribute("data-drop");
  }

  function wireTabDrag(wrap, id) {
    wrap.addEventListener("dragstart", function (event) {
      dragging = id;
      wrap.setAttribute("data-dragging", "true");
      try {
        event.dataTransfer.setData("text/plain", id);
        event.dataTransfer.effectAllowed = "move";
      } catch (error) {
        /* a browser refusing the transfer object still reports the drag */
      }
    });
    wrap.addEventListener("dragend", function () {
      dragging = null;
      wrap.removeAttribute("data-dragging");
      Array.prototype.slice.call(document.querySelectorAll('[data-drop="true"]')).forEach(function (node) {
        markDrop(node, false);
      });
    });
    wrap.addEventListener("dragover", function (event) {
      if (!dragging || dragging === id) return;
      event.preventDefault();
      event.stopPropagation();
    });
    wrap.addEventListener("drop", function (event) {
      if (!dragging || dragging === id) return;
      event.preventDefault();
      event.stopPropagation();
      var target = groupOf(id);
      moveTabTo(dragging, target ? target.id : null, id);
      dragging = null;
    });
  }

  function wireGroupDrop(node, gid) {
    node.addEventListener("dragover", function (event) {
      if (!dragging) return;
      event.preventDefault();
      markDrop(node, true);
    });
    node.addEventListener("dragleave", function (event) {
      if (event.target === node) markDrop(node, false);
    });
    node.addEventListener("drop", function (event) {
      if (!dragging) return;
      event.preventDefault();
      // The flow is this node's parent and its own drop handler moves a tab out
      // of every group. Letting this bubble would undo the drop that just landed.
      event.stopPropagation();
      markDrop(node, false);
      moveTabTo(dragging, gid, null);
      dragging = null;
    });
  }

  function wireFlowDrop() {
    flow.addEventListener("dragover", function (event) {
      if (!dragging) return;
      event.preventDefault();
    });
    flow.addEventListener("drop", function (event) {
      if (!dragging) return;
      event.preventDefault();
      moveTabTo(dragging, null, null);
      dragging = null;
    });
  }

  // ------------------------------------------------------------------- pins
  function togglePin(id) {
    var at = pinned.indexOf(id);
    if (at >= 0) pinned.splice(at, 1);
    else pinned.push(id);
    persistPins();
    layout();
  }

  function setPinned(id, on) {
    if (!nodes[id]) return false;
    if (isPinned(id) === (on === true)) return true;
    togglePin(id);
    return true;
  }

  function resetOrder() {
    var hadPins = pinned.length;
    var hadGroups = groups.length;
    var hadOrder = order.length;
    if (!hadPins && !hadGroups) {
      order = [];
      persistOrder();
      layout();
      A.notify(
        emoji("📌") + t("Tab order is already the shipped order", "分頁次序本來就係原本嗰個"),
        t(
          "No tab is pinned and no group exists, so there was nothing to reset.",
          "冇分頁被釘住，亦都冇分組，所以冇嘢需要重設。"
        )
      );
      return;
    }
    pinned = [];
    order = [];
    persistPins();
    persistOrder();
    layout();
    A.notify(
      emoji("📌") + t("Tab order reset", "分頁次序已重設"),
      t(
        count(hadPins, "tab was unpinned", "tabs were unpinned") +
          " and the strip is back in its shipped order. " +
          count(hadGroups, "group was kept", "groups were kept") +
          " with its membership intact; " +
          hadOrder +
          " stored order entries were discarded.",
        "已取消釘住 " + hadPins + " 個分頁，分頁條回復原本次序。" +
          hadGroups + " 個分組同佢哋嘅成員照樣保留；刪咗 " + hadOrder + " 項已儲存次序。"
      )
    );
  }

  // ------------------------------------------------------------------ groups
  function newGroupId() {
    groupSeq += 1;
    return "g" + groupSeq;
  }

  function createGroup(name, member) {
    var group = {
      id: newGroupId(),
      name: cleanName(name, t("New group", "新分組")),
      colour: GROUP_COLOURS[groups.length % GROUP_COLOURS.length],
      collapsed: false,
      members: []
    };
    groups.push(group);
    order.push("group:" + group.id);
    if (member) addToGroup(member, group.id, null, true);
    persistGroups();
    persistOrder();
    layout();
    return group;
  }

  function removeFromGroup(id) {
    var group = groupOf(id);
    if (!group) return null;
    group.members = group.members.filter(function (member) {
      return member !== id;
    });
    // The tab rejoins the flow beside the group it left rather than at the end.
    var at = order.indexOf("group:" + group.id);
    if (at < 0) order.push("tab:" + id);
    else order.splice(at + 1, 0, "tab:" + id);
    return group;
  }

  function addToGroup(id, gid, before, quiet) {
    var group = groupById(gid);
    if (!group || !nodes[id]) return false;
    removeFromGroup(id);
    order = order.filter(function (token) {
      return token !== "tab:" + id;
    });
    var at = before ? group.members.indexOf(before) : -1;
    if (at >= 0) group.members.splice(at, 0, id);
    else group.members.push(id);
    if (!quiet) {
      persistGroups();
      persistOrder();
      layout();
    }
    return true;
  }

  function moveTabTo(id, gid, before) {
    if (!nodes[id]) return false;
    if (gid) {
      var group = groupById(gid);
      if (!group) return false;
      var wasCollapsed = group.collapsed === true;
      addToGroup(id, gid, before, true);
      // Moving into a collapsed group leaves it collapsed: the drop was about
      // membership, not about opening something the reader deliberately shut.
      group.collapsed = wasCollapsed;
    } else {
      removeFromGroup(id);
      order = order.filter(function (token) {
        return token !== "tab:" + id;
      });
      var target = before ? order.indexOf("tab:" + before) : -1;
      var host = before ? groupOf(before) : null;
      if (host) {
        addToGroup(id, host.id, before, true);
      } else if (target >= 0) {
        order.splice(target, 0, "tab:" + id);
      } else {
        order.push("tab:" + id);
      }
    }
    persistGroups();
    persistOrder();
    layout();
    return true;
  }

  function renameGroup(gid, name) {
    var group = groupById(gid);
    if (!group) return false;
    group.name = cleanName(name, group.name);
    persistGroups();
    layout();
    return true;
  }

  function recolourGroup(gid, colour) {
    var group = groupById(gid);
    var hex = normaliseHex(colour);
    if (!group || !hex) return false;
    group.colour = hex;
    persistGroups();
    layout();
    return true;
  }

  function setCollapsed(gid, collapsed) {
    var group = groupById(gid);
    if (!group) return false;
    group.collapsed = collapsed === true;
    if (!group.collapsed) {
      group.members.forEach(function (id) {
        delete revealed[id];
      });
    }
    persistGroups();
    layout();
    return true;
  }

  function deleteGroup(gid) {
    var group = groupById(gid);
    if (!group) return false;
    var members = group.members.slice();
    var at = order.indexOf("group:" + gid);
    order = order.filter(function (token) {
      return token !== "group:" + gid;
    });
    // Members are never removed with the group; they return to the flow where
    // the group stood, so deleting a group can never lose a tab.
    var insert = at < 0 ? order.length : at;
    members.forEach(function (id, index) {
      order.splice(insert + index, 0, "tab:" + id);
    });
    groups = groups.filter(function (candidate) {
      return candidate.id !== gid;
    });
    var record = groupNodes[gid];
    if (record && record.node.parentNode) record.node.parentNode.removeChild(record.node);
    delete groupNodes[gid];
    persistGroups();
    persistOrder();
    layout();
    return members;
  }

  function moveGroupBy(gid, delta) {
    var token = "group:" + gid;
    var at = order.indexOf(token);
    if (at < 0) return false;
    var next = at + delta;
    if (next < 0 || next >= order.length) return false;
    order.splice(at, 1);
    order.splice(next, 0, token);
    persistOrder();
    layout();
    return true;
  }

  function moveTabBy(id, delta) {
    var group = groupOf(id);
    if (isPinned(id)) {
      var pinAt = pinned.indexOf(id);
      var pinNext = pinAt + delta;
      if (pinNext < 0 || pinNext >= pinned.length) return false;
      pinned.splice(pinAt, 1);
      pinned.splice(pinNext, 0, id);
      persistPins();
      layout();
      return true;
    }
    if (group) {
      var at = group.members.indexOf(id);
      var next = at + delta;
      if (next < 0 || next >= group.members.length) return false;
      group.members.splice(at, 1);
      group.members.splice(next, 0, id);
      persistGroups();
      layout();
      return true;
    }
    rebuildOrder();
    var token = "tab:" + id;
    var index = order.indexOf(token);
    var target = index + delta;
    if (index < 0 || target < 0 || target >= order.length) return false;
    order.splice(index, 1);
    order.splice(target, 0, token);
    persistOrder();
    layout();
    return true;
  }

  // ------------------------------------------------------------------ closing
  function closeTab(id, silent) {
    if (!nodes[id] || isClosed(id)) return false;
    closed[id] = true;
    persistClosed();
    if (activeId === id) {
      var next = openIds()[0];
      if (next) activate(next, { scroll: false });
      else {
        nodes[id].panel.setAttribute("hidden", "");
        nodes[id].panel.classList.remove("is-visible");
        activeId = null;
      }
    }
    layout();
    if (!silent) {
      A.notify(
        emoji("✖️") + t("Closed the " + tabOf(id).en + " tab", "已關閉「" + tabOf(id).yue + "」分頁"),
        t(
          "Its panel is hidden. Reopen it from Reopen closed tabs in the strip, or from the master tab search.",
          "佢嘅內容已經收埋。可以喺分頁條嘅「重開已關閉分頁」或者總分頁搜尋度開返。"
        )
      );
    }
    return true;
  }

  function reopenTab(id, silent) {
    if (!nodes[id] || !isClosed(id)) return false;
    delete closed[id];
    persistClosed();
    layout();
    if (!silent) {
      A.notify(
        emoji("↩️") + t("Reopened the " + tabOf(id).en + " tab", "已重開「" + tabOf(id).yue + "」分頁"),
        t("It is back in the strip in its stored position.", "佢返返分頁條入面原本嘅位置。")
      );
    }
    return true;
  }

  function closedIds() {
    return live
      .map(function (tab) {
        return tab.id;
      })
      .filter(isClosed);
  }

  function reopenAll() {
    var list = closedIds();
    if (!list.length) return;
    list.forEach(function (id) {
      delete closed[id];
    });
    persistClosed();
    layout();
    A.notify(
      emoji("↩️") + t("Reopened " + count(list.length, "tab", "tabs"), "已重開 " + list.length + " 個分頁"),
      list
        .map(function (id) {
          return labelOf(tabOf(id));
        })
        .join(", ")
    );
  }

  // -------------------------------------------------------------- group nodes
  function ensureGroupNode(group) {
    if (groupNodes[group.id]) return groupNodes[group.id];

    var bodyId = "tab-group-body-" + group.id;
    var searchId = "tab-group-search-" + group.id;
    var dot = el("span", { class: "tab-group-dot", "aria-hidden": "true" });
    var name = el("span", { class: "tab-group-name" });
    var countNode = el("span", { class: "tab-group-count" });
    var toggle = el(
      "button",
      {
        type: "button",
        class: "tab-group-toggle",
        "aria-expanded": "true",
        "aria-controls": bodyId
      },
      dot,
      name,
      countNode
    );
    var find = el("button", {
      type: "button",
      class: "tab-group-find",
      "aria-expanded": "false",
      "aria-controls": searchId,
      text: "⌕"
    });
    var body = el("div", { class: "tab-group-body", id: bodyId });
    var noteNode = el("p", { class: "tab-group-note", role: "status" });

    var search = searchRow({
      id: "tab-group-input-" + group.id,
      name: "tabgroup-" + group.id,
      label: t("Search tabs in this group", "喺呢個分組入面搵分頁"),
      builderLabel: t("Regex builder · group search", "Regex builder · 分組搜尋")
    });
    var searchBox = el(
      "div",
      { class: "tab-group-search", id: searchId, hidden: true },
      search.label,
      search.panel,
      noteNode
    );

    var node = el(
      "div",
      { class: "tab-group", role: "group", "data-group": group.id },
      el("div", { class: "tab-group-head" }, toggle, find),
      searchBox,
      body
    );

    toggle.addEventListener("click", function () {
      setCollapsed(group.id, !groupById(group.id).collapsed);
    });
    toggle.addEventListener("keydown", function (event) {
      if (!event.ctrlKey) return;
      var back = isVertical() ? "ArrowUp" : "ArrowLeft";
      var forward = isVertical() ? "ArrowDown" : "ArrowRight";
      if (event.key !== back && event.key !== forward) return;
      event.preventDefault();
      moveGroupBy(group.id, event.key === forward ? 1 : -1);
      toggle.focus();
    });
    find.addEventListener("click", function () {
      var open = searchBox.hidden;
      searchBox.hidden = !open;
      find.setAttribute("aria-expanded", open ? "true" : "false");
      if (open) search.input.focus();
      else find.focus();
    });
    node.addEventListener("contextmenu", function (event) {
      if (event.target.closest && event.target.closest(".tab-wrap")) return;
      event.preventDefault();
      A.contextMenu(groupMenuItems(group.id, event.shiftKey), event, t("Group menu", "分組選單"));
    });
    wireGroupDrop(node, group.id);

    // The builder's controls are found with document.querySelector, so the node
    // has to be in the document before it is attached, not after.
    flow.appendChild(node);

    var record = {
      group: group,
      node: node,
      toggle: toggle,
      dot: dot,
      name: name,
      count: countNode,
      find: find,
      body: body,
      note: noteNode,
      search: search,
      control: null
    };

    record.control = attachSearch({
      name: "tabgroup-" + group.id,
      input: search.input,
      openButton: search.openButton,
      panel: search.panel,
      sample: "Home Features Docs Screenshots Guides Community Changelog History Settings",
      onChange: function () {
        applyFilter();
      }
    });

    groupNodes[group.id] = record;
    return record;
  }

  // ------------------------------------------------------------------ layout
  function labelWithState(id) {
    var tab = tabOf(id);
    var group = groupOf(id);
    var bits = [labelOf(tab)];
    if (isPinned(id)) bits.push(t("pinned", "已釘住"));
    if (group) bits.push(t("in group " + group.name, "喺分組「" + group.name + "」"));
    if (isClosed(id)) bits.push(t("closed", "已關閉"));
    return bits.join(" · ");
  }

  function layout() {
    var focused = document.activeElement;
    var restore = focused && strip.contains(focused) ? focused : null;

    rebuildOrder();

    var pinnedOpen = pinned.filter(function (id) {
      return nodes[id] && !isClosed(id);
    });
    pinnedOpen.forEach(function (id) {
      pinnedRegion.appendChild(nodes[id].wrap);
    });

    order.forEach(function (token) {
      if (token.slice(0, 4) === "tab:") {
        var id = token.slice(4);
        if (!nodes[id] || isClosed(id) || isPinned(id)) return;
        flow.appendChild(nodes[id].wrap);
        return;
      }
      var group = groupById(token.slice(6));
      if (!group) return;
      var record = ensureGroupNode(group);
      record.group = group;
      flow.appendChild(record.node);
      group.members.forEach(function (id) {
        if (!nodes[id] || isClosed(id) || isPinned(id)) return;
        record.body.appendChild(nodes[id].wrap);
      });
    });

    // A group deleted while its node was cached must not linger in the strip.
    Object.keys(groupNodes).forEach(function (gid) {
      if (groupById(gid)) return;
      var record = groupNodes[gid];
      if (record.node.parentNode) record.node.parentNode.removeChild(record.node);
      delete groupNodes[gid];
    });

    applyLabels();
    applyFilter();
    updateTools();
    if (restore && restore.isConnected) restore.focus();
  }

  function applyLabels() {
    live.forEach(function (tab) {
      var entry = nodes[tab.id];
      var on = isPinned(tab.id);
      var text = labelOf(tab);
      entry.label.textContent = text;
      entry.initial.textContent = text.charAt(0);
      // The accessible name is the visible label, so a narrow rail that hides
      // the text does not also delete the tab's name.
      entry.button.setAttribute("aria-label", text);
      entry.button.setAttribute("title", text);
      entry.wrap.classList.toggle("is-pinned", on);
      entry.pin.textContent = on ? PIN_ON : PIN_OFF;
      entry.pin.setAttribute("aria-pressed", on ? "true" : "false");
      var pinLabel = on
        ? t("Unpin the " + tab.en + " tab", "取消釘住「" + tab.yue + "」分頁")
        : t("Pin the " + tab.en + " tab", "釘住「" + tab.yue + "」分頁");
      entry.pin.setAttribute("aria-label", pinLabel);
      entry.pin.setAttribute("title", pinLabel);
    });

    groups.forEach(function (group) {
      var record = groupNodes[group.id];
      if (!record) return;
      var open = group.members.filter(function (id) {
        return !isClosed(id);
      });
      var pinnedAway = open.filter(isPinned).length;
      record.name.textContent = group.name;
      record.count.textContent = String(open.length);
      record.dot.style.background = group.colour;
      record.node.style.borderColor = group.colour;
      record.toggle.style.color = "";
      record.toggle.setAttribute("aria-expanded", group.collapsed ? "false" : "true");
      var summary =
        t(
          group.name + " group, " + count(open.length, "tab", "tabs"),
          "分組「" + group.name + "」，" + open.length + " 個分頁"
        ) +
        (pinnedAway
          ? t(
              ", " + pinnedAway + " shown in the pinned region",
              "，其中 " + pinnedAway + " 個顯示喺釘住區"
            )
          : "") +
        (group.collapsed ? t(", collapsed", "，已收埋") : "");
      record.node.setAttribute("aria-label", summary);
      record.toggle.setAttribute(
        "aria-label",
        group.collapsed
          ? t("Expand the " + group.name + " group, " + open.length + " tabs", "展開分組「" + group.name + "」，" + open.length + " 個分頁")
          : t("Collapse the " + group.name + " group, " + open.length + " tabs", "收埋分組「" + group.name + "」，" + open.length + " 個分頁")
      );
      record.find.setAttribute(
        "aria-label",
        t("Search tabs in the " + group.name + " group", "喺分組「" + group.name + "」入面搵分頁")
      );
      record.body.setAttribute(
        "data-empty",
        t("No tab is shown here.", "呢度冇顯示任何分頁。")
      );
      if (record.search.summary) {
        record.search.summary.textContent = t(
          "Regex builder · " + group.name + " group search",
          "Regex builder · 分組「" + group.name + "」搜尋"
        );
      }
      var placeholder = t("Search tabs in this group", "喺呢個分組入面搵分頁");
      record.search.input.setAttribute("placeholder", placeholder);
      record.search.input.setAttribute("aria-label", placeholder);
    });
  }

  // ------------------------------------------------------------------ filter
  function stripMatches(id) {
    var tab = tabOf(id);
    return hits(searchControl, labelOf(tab) + " " + tab.id);
  }

  function applyFilter() {
    if (!strip) return;
    var state = stateOf(searchControl, searchField);
    var query = state.query;
    var matched = 0;
    var activeKept = false;
    searchReveal = {};

    var groupNameHit = {};
    if (query && state.valid) {
      groups.forEach(function (group) {
        if (hits(searchControl, group.name)) groupNameHit[group.id] = true;
      });
    }

    live.forEach(function (tab) {
      var id = tab.id;
      var entry = nodes[id];
      if (isClosed(id)) {
        entry.wrap.hidden = true;
        return;
      }
      var group = groupOf(id);
      var stripHit;
      if (!query) stripHit = true;
      else if (!state.valid) stripHit = false; // a broken pattern never widens a search
      else stripHit = stripMatches(id) || (group ? groupNameHit[group.id] === true : false);
      if (query && state.valid && stripHit) matched += 1;

      var groupHit = true;
      if (group && groupNodes[group.id]) {
        var record = groupNodes[group.id];
        var inner = stateOf(record.control, record.search.input);
        if (inner.query) {
          groupHit = inner.valid && hits(record.control, labelOf(tab) + " " + id);
        }
      }

      var collapsedHidden = false;
      if (group && group.collapsed && !revealed[id]) {
        // A live query reveals a match inside a collapsed group; the stored
        // collapsed preference is untouched and returns when the query clears.
        if (query && state.valid && stripHit && !isPinned(id)) searchReveal[id] = true;
        else collapsedHidden = !isPinned(id);
      }

      var show = stripHit && groupHit && !collapsedHidden;
      if (id === activeId) {
        if (!show) activeKept = true;
        show = true;
      }
      entry.wrap.hidden = !show;
    });

    groups.forEach(function (group) {
      var record = groupNodes[group.id];
      if (!record) return;
      var visibleMembers = group.members.filter(function (id) {
        return nodes[id] && !nodes[id].wrap.hidden;
      });
      var keep =
        visibleMembers.length > 0 ||
        !query ||
        !state.valid ||
        groupNameHit[group.id] === true;
      record.node.hidden = !keep;
      writeGroupNote(record);
    });

    writeNote(state, matched, activeKept);
    scheduleMeasure();
  }

  function writeGroupNote(record) {
    var group = record.group;
    var inner = stateOf(record.control, record.search.input);
    if (!inner.query) {
      record.note.textContent = "";
      return;
    }
    if (!inner.valid) {
      record.note.textContent = t(
        "That pattern is not valid, so no tab in this group is shown: " + inner.feedback,
        "呢個 pattern 無效，所以呢個分組冇顯示任何分頁：" + inner.feedback
      );
      return;
    }
    var open = group.members.filter(function (id) {
      return !isClosed(id);
    });
    var found = open.filter(function (id) {
      return hits(record.control, labelOf(tabOf(id)) + " " + id);
    });
    record.note.textContent = t(
      found.length +
        " of " +
        open.length +
        (open.length === 1 ? " tab in " : " tabs in ") +
        group.name +
        " match “" + inner.query + "” (" + modeSentence(inner) + ").",
      "分組「" + group.name + "」" + open.length + " 個分頁之中有 " + found.length +
        " 個配到「" + inner.query + "」（" + modeSentence(inner) + "）。"
    );
  }

  function writeNote(state, matched, activeKept) {
    if (!note) return;
    var query = state.query;
    var closedCount = closedIds().length;
    var suffixParts = [];

    if (activeKept && nodes[activeId]) {
      var open = tabOf(activeId);
      suffixParts.push(
        t("The active tab (" + open.en + ") stays visible.", "目前分頁「" + open.yue + "」照樣顯示。")
      );
    }
    var revealCount = Object.keys(searchReveal).length;
    if (revealCount) {
      suffixParts.push(
        t(
          count(revealCount, "match is", "matches are") +
            " shown inside a collapsed group; the group stays collapsed.",
          "有 " + revealCount + " 個配到嘅分頁喺已收埋嘅分組入面顯示緊，個分組保持收埋。"
        )
      );
    }
    if (!query && closedCount) {
      suffixParts.push(
        t(
          count(closedCount, "tab is", "tabs are") + " closed and not shown.",
          "有 " + closedCount + " 個分頁已關閉，冇顯示。"
        )
      );
    }
    var suffix = suffixParts.length ? " " + suffixParts.join(" ") : "";

    if (!query) {
      note.textContent = suffix.trim();
      return;
    }
    if (!state.valid) {
      note.textContent =
        t(
          "That pattern is not valid: " + state.feedback + " No tab matches it.",
          "呢個正則式唔啱：" + state.feedback + " 冇分頁配到。"
        ) + suffix;
      return;
    }
    var english =
      matched === 0
        ? "No tab matches “" + query + "” (" + modeSentence(state) + ")."
        : matched + (matched === 1 ? " tab matches “" : " tabs match “") + query +
          "” (" + modeSentence(state) + ").";
    var cantonese =
      matched === 0
        ? "冇分頁配到「" + query + "」（" + modeSentence(state) + "）。"
        : matched + " 個分頁配到「" + query + "」（" + modeSentence(state) + "）。";
    note.textContent = t(english, cantonese) + suffix;
  }

  // ---------------------------------------------------------------- overflow
  function scheduleMeasure() {
    if (measureQueued) return;
    measureQueued = window.requestAnimationFrame
      ? window.requestAnimationFrame(function () {
          measureQueued = 0;
          measure();
        })
      : window.setTimeout(function () {
          measureQueued = 0;
          measure();
        }, 16);
  }

  function flowItems() {
    return Array.prototype.slice.call(flow.children).filter(function (node) {
      return !node.hidden;
    });
  }

  function sizeOf(node) {
    return isVertical() ? node.offsetHeight : node.offsetWidth;
  }

  /**
   * A vertical strip's overflow is a height budget, not a width budget with the
   * axis renamed: the reserve, the running total and the container measurement
   * all read the other dimension, so each axis is written out rather than
   * flipped by a variable.
   */
  function measure() {
    if (!strip || measuring || strip.hidden) return;
    measuring = true;
    try {
      overflowed = [];
      Array.prototype.slice.call(flow.children).forEach(function (node) {
        node.removeAttribute("data-overflow");
      });
      overflowButton.hidden = true;

      var vertical = isVertical();
      var available = vertical ? strip.clientHeight : strip.clientWidth;
      if (!available) return;

      var used = pinnedRegion.children.length
        ? (vertical ? pinnedRegion.offsetHeight : pinnedRegion.offsetWidth) + GAP
        : 0;
      var items = flowItems();
      var sizes = items.map(sizeOf);
      var total = used;
      sizes.forEach(function (value) {
        total += value + GAP;
      });
      if (total <= available) return;

      overflowButton.hidden = false;
      var reserve = (vertical ? overflowButton.offsetHeight : overflowButton.offsetWidth) + GAP;
      var budget = available - used - reserve;
      var run = 0;
      items.forEach(function (node, index) {
        run += sizes[index] + GAP;
        if (run > budget) {
          node.setAttribute("data-overflow", "true");
          overflowed.push(node);
        }
      });
      if (!overflowed.length) overflowButton.hidden = true;
    } finally {
      measuring = false;
      updateOverflowLabel();
      updateRailHeight();
    }
  }

  function overflowTabIds() {
    var ids = [];
    overflowed.forEach(function (node) {
      if (node.classList.contains("tab-wrap")) {
        var button = node.querySelector("[data-tab]");
        if (button) ids.push(button.getAttribute("data-tab"));
        return;
      }
      var gid = node.getAttribute("data-group");
      var group = gid ? groupById(gid) : null;
      if (!group) return;
      group.members.forEach(function (id) {
        if (nodes[id] && !nodes[id].wrap.hidden) ids.push(id);
      });
    });
    return ids;
  }

  function updateOverflowLabel() {
    if (!overflowButton) return;
    var ids = overflowTabIds();
    var label = t(
      "More · " + count(ids.length, "tab", "tabs") + " not shown",
      "更多 · 有 " + ids.length + " 個分頁未顯示"
    );
    overflowButton.textContent = t("More", "更多") + " (" + ids.length + ")";
    overflowButton.setAttribute("aria-label", label);
    overflowButton.setAttribute("title", label);
  }

  function updateRailHeight() {
    if (!bar) return;
    if (dock === "bottom") {
      document.documentElement.style.setProperty("--tab-rail-height", bar.offsetHeight + "px");
    } else {
      document.documentElement.style.setProperty("--tab-rail-height", "0px");
    }
  }

  var overflowPanel = null;

  function openOverflow() {
    if (!overflowPanel) {
      overflowPanel = makePanel("tab-overflow-panel", t("Tabs not shown", "未顯示嘅分頁"));
      listKeys(overflowPanel.body);
    }
    if (panelOpen(overflowPanel)) {
      closeOpenPanel(true);
      return;
    }
    overflowPanel.heading.textContent = t("Tabs not shown", "未顯示嘅分頁");
    var list = el("div", { class: "tab-panel-list", role: "group" });
    var ids = overflowTabIds();
    if (!ids.length) {
      list.appendChild(
        emptyNote(t("Every tab fits in the strip right now.", "而家所有分頁都放得落分頁條。"))
      );
    } else {
      ids.forEach(function (id) {
        var group = groupOf(id);
        list.appendChild(
          optionButton({
            title: labelOf(tabOf(id)),
            meta: group
              ? t("In the " + group.name + " group", "喺分組「" + group.name + "」入面")
              : t("Ungrouped", "冇分組"),
            colour: group ? group.colour : null,
            run: function () {
              closeOpenPanel(false);
              activate(id, { focusPanel: true });
            }
          })
        );
      });
    }
    overflowPanel.body.replaceChildren(
      emptyNote(
        t(
          "The strip is too short for every tab at this size, so these are listed here rather than clipped.",
          "呢個尺寸放唔晒所有分頁，所以擺喺呢度而唔係切走佢哋。"
        )
      ),
      list
    );
    openPanel(overflowPanel, {
      anchor: overflowButton,
      trigger: overflowButton,
      focus: function () {
        var first = overflowPanel.body.querySelector(".tab-option");
        if (first) first.focus();
        else overflowPanel.closeButton.focus();
      }
    });
  }

  // ------------------------------------------------------------------ docking
  function arrangeBar() {
    if (dock === "top") {
      bar.appendChild(toolsRow);
      bar.appendChild(strip);
      bar.appendChild(searchLabel);
      if (regexHome && regexPanel) regexHome.parent.insertBefore(regexPanel, regexHome.next);
      if (noteHome && note) noteHome.parent.insertBefore(note, noteHome.next);
      return;
    }
    // Away from the top edge the builder and the note travel with the field they
    // belong to; leaving them in the page flow would detach them from it.
    bar.appendChild(toolsRow);
    bar.appendChild(searchLabel);
    if (regexPanel) bar.appendChild(regexPanel);
    if (note) bar.appendChild(note);
    bar.appendChild(strip);
  }

  function applyDock() {
    document.documentElement.setAttribute("data-tab-dock", dock);
    var vertical = isVertical();
    strip.setAttribute("aria-orientation", vertical ? "vertical" : "horizontal");
    arrangeBar();
    updateTools();
    layout();
    updateRailHeight();
  }

  function setDock(edge, quiet) {
    if (DOCKS.indexOf(edge) < 0) return false;
    if (dock === edge) return true;
    dock = edge;
    persistDock();
    if (document.documentElement.getAttribute("data-tab-rail") === "expanded") {
      document.documentElement.removeAttribute("data-tab-rail");
    }
    applyDock();
    refreshDockCard();
    if (!quiet) {
      A.notify(
        emoji("🧭") + t("Tab strip docked to the " + edge + " edge", "分頁條已停靠喺" + dockName(edge)),
        isVertical()
          ? t(
              "The strip is vertical, so its arrow keys are Up and Down and its overflow is measured by height.",
              "分頁條而家係直向，方向鍵變咗上下，超出範圍係以高度計。"
            )
          : t(
              "The strip is horizontal, so its arrow keys are Left and Right and its overflow is measured by width.",
              "分頁條而家係橫向，方向鍵係左右，超出範圍係以闊度計。"
            )
      );
    }
    return true;
  }

  function dockName(edge) {
    return t(
      edge === "left" ? "left" : edge === "right" ? "right" : edge === "top" ? "top" : "bottom",
      edge === "left" ? "左邊" : edge === "right" ? "右邊" : edge === "top" ? "上面" : "下面"
    );
  }

  function dockLabel(edge) {
    return t(
      edge === "left" ? "Left edge" : edge === "right" ? "Right edge" : edge === "top" ? "Top edge" : "Bottom edge",
      edge === "left" ? "左邊" : edge === "right" ? "右邊" : edge === "top" ? "上面" : "下面"
    );
  }

  // ------------------------------------------------------------------ activate
  function syncHash(id) {
    try {
      history.replaceState(null, "", "#" + id);
    } catch (error) {
      /* A file:// document has an opaque origin and refuses replaceState; the
         tab still changed, so this is not worth failing the activation over. */
    }
  }

  function scrollTabIntoView(button) {
    var overflowing = isVertical()
      ? strip.scrollHeight > strip.clientHeight + 1
      : strip.scrollWidth > strip.clientWidth + 1;
    if (!overflowing) return;
    try {
      button.scrollIntoView({
        behavior: prefersReduced() ? "auto" : "smooth",
        inline: "nearest",
        block: "nearest"
      });
    } catch (error) {
      button.scrollIntoView(false);
    }
  }

  function activate(id, options) {
    var entry = nodes[id];
    if (!entry) return false;
    var opts = options || {};
    if (isClosed(id)) reopenTab(id, true);
    activeId = id;

    var group = groupOf(id);
    if (group && group.collapsed) revealed[id] = true;

    live.forEach(function (tab) {
      var one = nodes[tab.id];
      var on = tab.id === id;
      one.button.setAttribute("aria-selected", on ? "true" : "false");
      one.button.setAttribute("tabindex", on ? "0" : "-1");
      one.button.classList.toggle("is-active", on);
      one.pin.setAttribute("tabindex", on ? "0" : "-1");
      one.panel.classList.toggle("is-visible", on);
      if (on) one.panel.removeAttribute("hidden");
      else one.panel.setAttribute("hidden", "");
    });

    syncHash(id);
    applyFilter();
    if (opts.focusTab) entry.button.focus();
    if (opts.focusPanel) entry.panel.focus();
    if (opts.scroll !== false) scrollTabIntoView(entry.button);
    A.emitTabChange(id);
    return true;
  }

  function visibleTabIds() {
    var out = [];
    Array.prototype.slice.call(strip.querySelectorAll(".tab-wrap")).forEach(function (wrap) {
      if (wrap.hidden || wrap.getAttribute("data-overflow") === "true") return;
      var parentGroup = wrap.closest(".tab-group");
      if (parentGroup && parentGroup.getAttribute("data-overflow") === "true") return;
      var button = wrap.querySelector("[data-tab]");
      if (button) out.push(button.getAttribute("data-tab"));
    });
    return out;
  }

  // ---------------------------------------------------------------- keyboard
  function onTabKeyDown(event) {
    var id = event.currentTarget.getAttribute("data-tab");
    var key = event.key;

    if (!event.ctrlKey && !event.altKey && !event.metaKey && (key === "p" || key === "P")) {
      event.preventDefault();
      togglePin(id);
      return;
    }
    if (!event.ctrlKey && !event.altKey && !event.metaKey && (key === "m" || key === "M")) {
      event.preventDefault();
      openMovePicker(id, nodes[id].button);
      return;
    }

    // The keys that move between tabs follow the axis the strip is drawn on. A
    // vertical strip that answers Left and Right looks right and is unusable.
    var back = isVertical() ? "ArrowUp" : "ArrowLeft";
    var forward = isVertical() ? "ArrowDown" : "ArrowRight";

    if (event.ctrlKey && (key === back || key === forward)) {
      event.preventDefault();
      moveTabBy(id, key === forward ? 1 : -1);
      nodes[id].button.focus();
      return;
    }

    var ids = visibleTabIds();
    if (!ids.length) return;
    var at = ids.indexOf(id);
    var next = null;
    if (key === forward) next = ids[(at + 1) % ids.length];
    else if (key === back) next = ids[(at - 1 + ids.length) % ids.length];
    else if (key === "Home") next = ids[0];
    else if (key === "End") next = ids[ids.length - 1];
    if (!next) return;

    event.preventDefault();
    // Focus stays on the strip here: moving it into the panel would end the very
    // roving navigation the arrow keys exist for. Enter, Space and a click do
    // move it, because those are deliberate activations.
    activate(next, { focusTab: true });
  }

  // ------------------------------------------------------------- move picker
  var movePanel = null;
  var moveControl = null;
  var moveSearch = null;
  var moveList = null;
  var moveTarget = null;

  function buildMovePanel() {
    movePanel = makePanel("tab-move-panel", t("Move into group", "移去分組"));
    moveSearch = searchRow({
      id: "tab-move-search",
      name: "tabmove",
      label: t("Search groups", "搵分組"),
      builderLabel: t("Regex builder · group picker search", "Regex builder · 分組揀選搜尋")
    });
    moveList = el("div", { class: "tab-panel-list", role: "group" });
    var createButton = el("button", {
      type: "button",
      class: "tab-option",
      onclick: function () {
        var id = moveTarget;
        var name = moveSearch.input.value.trim();
        closeOpenPanel(false);
        var group = createGroup(name || null, id);
        A.notify(
          emoji("🗂️") + t("Created the " + group.name + " group", "已建立分組「" + group.name + "」"),
          t(
            labelOf(tabOf(id)) + " was moved into it.",
            "已將「" + labelOf(tabOf(id)) + "」移咗入去。"
          )
        );
        if (nodes[id]) nodes[id].button.focus();
      }
    });
    movePanel.createButton = createButton;
    movePanel.body.replaceChildren(
      el("p", { class: "tab-panel-note", id: "tab-move-lead" }),
      moveSearch.label,
      moveSearch.panel,
      moveList,
      createButton
    );
    listKeys(movePanel.body);
    moveControl = attachSearch({
      name: "tabmove",
      input: moveSearch.input,
      openButton: moveSearch.openButton,
      panel: moveSearch.panel,
      sample: "Reference · Reading · Workspace",
      onChange: renderMoveList
    });
  }

  function renderMoveList() {
    if (!moveList || !moveTarget) return;
    var state = stateOf(moveControl, moveSearch.input);
    var current = groupOf(moveTarget);
    var rows = [];

    if (current) {
      rows.push(
        optionButton({
          title: t("Take it out of " + current.name, "由「" + current.name + "」拎返出嚟"),
          meta: t("Returns it to the ungrouped flow", "放返去冇分組嘅位置"),
          run: function () {
            var id = moveTarget;
            closeOpenPanel(false);
            moveTabTo(id, null, null);
            if (nodes[id]) nodes[id].button.focus();
          }
        })
      );
    }

    var listed = groups.filter(function (group) {
      if (current && group.id === current.id) return false;
      if (!state.query) return true;
      return state.valid && hits(moveControl, group.name);
    });

    listed.forEach(function (group) {
      var open = group.members.filter(function (id) {
        return !isClosed(id);
      });
      rows.push(
        optionButton({
          title: group.name,
          colour: group.colour,
          meta:
            t(count(open.length, "tab", "tabs"), open.length + " 個分頁") +
            (group.collapsed ? t(" · collapsed, and stays collapsed", " · 已收埋，移入之後照樣收埋") : ""),
          run: function () {
            var id = moveTarget;
            closeOpenPanel(false);
            moveTabTo(id, group.id, null);
            if (nodes[id]) nodes[id].button.focus();
          }
        })
      );
    });

    if (!rows.length) {
      rows.push(
        emptyNote(
          !groups.length
            ? t(
                "No group exists yet. Create the first one below.",
                "而家一個分組都未有。喺下面建立第一個。"
              )
            : !state.valid
            ? t(
                "That pattern is not valid, so no group is listed: " + state.feedback,
                "呢個 pattern 無效，所以冇列出任何分組：" + state.feedback
              )
            : t(
                "No group name matches “" + state.query + "” (" + modeSentence(state) + ").",
                "冇分組名配到「" + state.query + "」（" + modeSentence(state) + "）。"
              )
        )
      );
    }
    moveList.replaceChildren.apply(moveList, rows);

    var wanted = moveSearch.input.value.trim();
    movePanel.createButton.textContent = wanted
      ? t("Create the “" + wanted + "” group and move it there", "建立分組「" + wanted + "」再移過去")
      : t("Create a new group and move it there", "建立一個新分組再移過去");
    movePanel.createButton.setAttribute("aria-label", movePanel.createButton.textContent);
  }

  function openMovePicker(id, anchor) {
    if (!nodes[id]) return;
    if (!movePanel) buildMovePanel();
    moveTarget = id;
    movePanel.heading.textContent = t(
      "Move " + tabOf(id).en + " into a group",
      "將「" + tabOf(id).yue + "」移去分組"
    );
    var lead = movePanel.body.querySelector("#tab-move-lead");
    if (lead) {
      lead.textContent = t(
        "Arrow keys move down the list, Enter moves the tab, Escape cancels and returns focus to the tab.",
        "方向鍵喺清單度上落，Enter 就移，Escape 取消並將焦點交返俾個分頁。"
      );
    }
    renderMoveList();
    openPanel(movePanel, {
      anchor: anchor || nodes[id].button,
      returnTo: nodes[id].button,
      focus: function () {
        moveSearch.input.focus();
      }
    });
  }

  // ------------------------------------------------------ group manager panel
  var groupsPanel = null;
  var groupsControl = null;
  var groupsSearch = null;
  var groupsList = null;

  function buildGroupsPanel() {
    groupsPanel = makePanel("tab-groups-panel", t("Tab groups", "分頁分組"));
    groupsSearch = searchRow({
      id: "tab-groups-search",
      name: "tabgroups",
      label: t("Search groups by name", "用名搵分組"),
      builderLabel: t("Regex builder · group name search", "Regex builder · 分組名搜尋")
    });
    groupsList = el("div", { class: "tab-panel-list", role: "group" });
    var create = el("button", {
      type: "button",
      class: "tab-tool",
      onclick: function () {
        var name = groupsSearch.input.value.trim();
        var group = createGroup(name || null, null);
        renderGroupsList();
        A.notify(
          emoji("🗂️") + t("Created the " + group.name + " group", "已建立分組「" + group.name + "」"),
          t(
            "It is empty. Move tabs into it with Move into group, or by dragging one onto it.",
            "而家係空嘅。可以用「移去分組」或者直接拖個分頁入去。"
          )
        );
      }
    });
    groupsPanel.createButton = create;
    groupsPanel.body.replaceChildren(
      groupsSearch.label,
      groupsSearch.panel,
      groupsList,
      el("div", { class: "tab-panel-actions" }, create)
    );
    listKeys(groupsPanel.body);
    groupsControl = attachSearch({
      name: "tabgroups",
      input: groupsSearch.input,
      openButton: groupsSearch.openButton,
      panel: groupsSearch.panel,
      sample: "Reference · Reading · Workspace",
      onChange: renderGroupsList
    });
  }

  function groupActionRow(group) {
    function tool(label, run, disabled, reason) {
      var button = el("button", { type: "button", class: "tab-tool", text: label, onclick: run });
      button.setAttribute("aria-label", label + " — " + group.name);
      if (disabled) {
        button.disabled = true;
        button.setAttribute("title", reason);
        button.setAttribute("aria-label", label + " — " + group.name + " — " + reason);
      }
      return button;
    }
    var at = order.indexOf("group:" + group.id);
    return el(
      "div",
      { class: "tab-panel-actions" },
      tool(group.collapsed ? t("Expand", "展開") : t("Collapse", "收埋"), function () {
        setCollapsed(group.id, !group.collapsed);
        renderGroupsList();
      }),
      tool(t("Edit appearance…", "編輯外觀…"), function () {
        openGroupAppearance(group.id, groupsPanel.root);
      }),
      tool(
        t("Move earlier", "向前移"),
        function () {
          moveGroupBy(group.id, -1);
          renderGroupsList();
        },
        at <= 0,
        t("It is already first in the strip.", "佢已經喺分頁條最前。")
      ),
      tool(
        t("Move later", "向後移"),
        function () {
          moveGroupBy(group.id, 1);
          renderGroupsList();
        },
        at < 0 || at >= order.length - 1,
        t("It is already last in the strip.", "佢已經喺分頁條最後。")
      ),
      tool(t("Remove group…", "移除分組…"), function () {
        confirmRemoveGroup(group.id);
      })
    );
  }

  function renderGroupsList() {
    if (!groupsList) return;
    var state = stateOf(groupsControl, groupsSearch.input);
    var listed = groups.filter(function (group) {
      if (!state.query) return true;
      return state.valid && hits(groupsControl, group.name);
    });
    var rows = [];
    listed.forEach(function (group) {
      var open = group.members.filter(function (id) {
        return !isClosed(id);
      });
      rows.push(
        el(
          "div",
          { class: "tab-option tab-option-static", role: "presentation" },
          el("span", { class: "tab-swatch", "aria-hidden": "true", style: "background:" + group.colour }),
          el(
            "span",
            { class: "tab-option-main" },
            el("span", { class: "tab-option-title", text: group.name }),
            el("span", {
              class: "tab-option-meta",
              text:
                t(count(open.length, "tab", "tabs"), open.length + " 個分頁") +
                " · " +
                (group.collapsed ? t("collapsed", "已收埋") : t("expanded", "已展開")) +
                (open.length
                  ? " · " +
                    open
                      .map(function (id) {
                        return labelOf(tabOf(id));
                      })
                      .join(", ")
                  : "")
            })
          )
        )
      );
      rows.push(groupActionRow(group));
    });
    if (!rows.length) {
      rows.push(
        emptyNote(
          !groups.length
            ? t(
                "No group exists yet. Creating one below adds an empty group to the strip.",
                "而家一個分組都未有。喺下面建立一個就會喺分頁條加返個空分組。"
              )
            : !state.valid
            ? t(
                "That pattern is not valid, so no group is listed: " + state.feedback,
                "呢個 pattern 無效，所以冇列出任何分組：" + state.feedback
              )
            : t(
                "No group name matches “" + state.query + "” (" + modeSentence(state) + ").",
                "冇分組名配到「" + state.query + "」（" + modeSentence(state) + "）。"
              )
        )
      );
    } else {
      rows.unshift(
        emptyNote(
          t(
            listed.length + " of " + count(groups.length, "group", "groups") + " listed.",
            groups.length + " 個分組之中列出咗 " + listed.length + " 個。"
          )
        )
      );
    }
    groupsList.replaceChildren.apply(groupsList, rows);
    var wanted = groupsSearch.input.value.trim();
    groupsPanel.createButton.textContent = wanted
      ? t("Create the “" + wanted + "” group", "建立分組「" + wanted + "」")
      : t("Create a new group", "建立新分組");
  }

  function openGroupsPanel(anchor) {
    if (!groupsPanel) buildGroupsPanel();
    if (panelOpen(groupsPanel)) {
      closeOpenPanel(true);
      return;
    }
    groupsPanel.heading.textContent = t("Tab groups", "分頁分組");
    renderGroupsList();
    openPanel(groupsPanel, {
      anchor: anchor,
      // Only a toolbar button's aria-expanded describes this panel. A group's
      // collapse toggle also carries one, and it means something else entirely.
      trigger: isToolButton(anchor) ? anchor : null,
      returnTo: anchor,
      focus: function () {
        groupsSearch.input.focus();
      }
    });
  }

  // ------------------------------------------------------- group appearance
  var appearancePanel = null;

  function openGroupAppearance(gid, anchor) {
    var group = groupById(gid);
    if (!group) return;
    if (!appearancePanel) appearancePanel = makePanel("tab-appearance-panel", t("Group appearance", "分組外觀"));

    var nameInput = el("input", {
      type: "text",
      id: "tab-appearance-name",
      maxlength: String(NAME_MAX),
      autocomplete: "off",
      spellcheck: "false"
    });
    nameInput.value = group.name;
    var colourInput = el("input", { type: "color", id: "tab-appearance-colour" });
    colourInput.value = group.colour;
    var hexInput = el("input", {
      type: "text",
      id: "tab-appearance-hex",
      maxlength: "7",
      autocomplete: "off",
      spellcheck: "false"
    });
    hexInput.value = group.colour;
    var status = el("p", { class: "tab-panel-note", role: "status" });

    function report(text, bad) {
      status.textContent = text;
      if (bad) status.setAttribute("data-state", "error");
      else status.removeAttribute("data-state");
    }

    function describeColour(hex) {
      return t(
        "Header text on " + hex + " is drawn in " + readableOn(hex) + ", chosen by measured contrast.",
        "喺 " + hex + " 上面嘅標題字用 " + readableOn(hex) + "，係按量出嚟嘅對比度揀。"
      );
    }

    nameInput.addEventListener("input", function () {
      renameGroup(gid, nameInput.value);
      report(
        t(
          "Renamed to “" + groupById(gid).name + "”. Up to " + NAME_MAX + " characters; an empty name keeps the previous one.",
          "已改名做「" + groupById(gid).name + "」。最多 " + NAME_MAX + " 個字元；留白就保留返之前個名。"
        ),
        false
      );
      if (groupsList) renderGroupsList();
    });

    function commitColour(value, source) {
      var hex = normaliseHex(value);
      if (!hex) {
        report(
          t(
            "Not a hex colour yet: use #rgb or #rrggbb. Nothing was changed.",
            "而家仲未係有效嘅 hex 色：要用 #rgb 或者 #rrggbb。冇改到任何嘢。"
          ),
          true
        );
        return;
      }
      recolourGroup(gid, hex);
      if (source !== colourInput) colourInput.value = hex;
      if (source !== hexInput) hexInput.value = hex;
      report(describeColour(hex), false);
      if (groupsList) renderGroupsList();
    }

    colourInput.addEventListener("input", function () {
      commitColour(colourInput.value, colourInput);
    });
    hexInput.addEventListener("input", function () {
      commitColour(hexInput.value, hexInput);
    });

    var presets = el("div", { class: "tab-panel-actions", role: "group" });
    presets.setAttribute("aria-label", t("Preset group colours", "預設分組顏色"));
    GROUP_COLOURS.forEach(function (hex) {
      var swatch = el("button", {
        type: "button",
        class: "tab-tool",
        "aria-label": t("Use " + hex, "用 " + hex),
        onclick: function () {
          commitColour(hex, null);
        }
      });
      swatch.appendChild(el("span", { class: "tab-swatch", "aria-hidden": "true", style: "background:" + hex }));
      swatch.appendChild(el("span", { text: hex }));
      presets.appendChild(swatch);
    });

    appearancePanel.heading.textContent = t(
      "Appearance of the " + group.name + " group",
      "分組「" + group.name + "」嘅外觀"
    );
    appearancePanel.body.replaceChildren(
      emptyNote(
        t(
          "Every change here applies to the strip immediately and is stored in this browser.",
          "呢度每個改動都即刻套用喺分頁條，亦都會存喺呢個瀏覽器。"
        )
      ),
      el(
        "div",
        { class: "tab-panel-row" },
        el("label", { for: "tab-appearance-name", text: t("Name", "名稱") }),
        nameInput
      ),
      el(
        "div",
        { class: "tab-panel-row" },
        el("label", { for: "tab-appearance-colour", text: t("Colour", "顏色") }),
        colourInput,
        el("label", { for: "tab-appearance-hex", text: t("HEX", "HEX") }),
        hexInput
      ),
      presets,
      status
    );
    report(describeColour(group.colour), false);
    openPanel(appearancePanel, {
      anchor: anchor || (groupNodes[gid] ? groupNodes[gid].toggle : null),
      returnTo: groupNodes[gid] ? groupNodes[gid].toggle : null,
      focus: function () {
        nameInput.focus();
      }
    });
  }

  // ---------------------------------------------------------- master search
  var masterPanel = null;
  var masterControl = null;
  var masterSearch = null;
  var masterList = null;
  var masterCount = null;

  function buildMasterPanel() {
    masterPanel = makePanel("tab-master-panel", t("Find any tab", "搵任何分頁"));
    masterSearch = searchRow({
      id: "tab-master-search",
      name: "tabmaster",
      label: t("Search every tab", "搵全部分頁"),
      builderLabel: t("Regex builder · master tab search", "Regex builder · 總分頁搜尋")
    });
    masterCount = el("p", { class: "tab-panel-note", role: "status" });
    masterList = el("div", { class: "tab-panel-list", role: "group" });
    var closeIn = el("button", {
      type: "button",
      class: "tab-tool",
      onclick: function () {
        openBulkClose("in", masterPanel.root);
      }
    });
    var closeOut = el("button", {
      type: "button",
      class: "tab-tool",
      onclick: function () {
        openBulkClose("out", masterPanel.root);
      }
    });
    masterPanel.closeIn = closeIn;
    masterPanel.closeOut = closeOut;
    masterPanel.body.replaceChildren(
      masterSearch.label,
      masterSearch.panel,
      masterCount,
      masterList,
      el("div", { class: "tab-panel-actions" }, closeIn, closeOut)
    );
    listKeys(masterPanel.body);
    masterControl = attachSearch({
      name: "tabmaster",
      input: masterSearch.input,
      openButton: masterSearch.openButton,
      panel: masterSearch.panel,
      sample: "Home Features Docs Screenshots Guides Community Changelog History Settings",
      onChange: renderMasterList
    });
  }

  function renderMasterList() {
    if (!masterList) return;
    var state = stateOf(masterControl, masterSearch.input);
    var all = live.map(function (tab) {
      return tab.id;
    });
    var listed = all.filter(function (id) {
      if (!state.query) return true;
      return state.valid && hits(masterControl, labelOf(tabOf(id)) + " " + id);
    });

    masterCount.textContent = !state.valid
      ? t(
          "That pattern is not valid, so no tab is listed: " + state.feedback,
          "呢個 pattern 無效，所以冇列出任何分頁：" + state.feedback
        )
      : t(
          listed.length + " of " + count(all.length, "tab", "tabs") + " on this page (" + modeSentence(state) + "). Strip: " +
            t("Primary", "主要") + " · " + dockLabel(dock) + ".",
          "呢一頁 " + all.length + " 個分頁之中列出咗 " + listed.length + " 個（" + modeSentence(state) + "）。分頁條：主要 · " + dockLabel(dock) + "。"
        );

    var rows = listed.map(function (id) {
      var group = groupOf(id);
      var meta = [
        t("Strip: Primary", "分頁條：主要"),
        group
          ? t("Group: " + group.name + (group.collapsed ? " (collapsed)" : ""), "分組：" + group.name + (group.collapsed ? "（已收埋）" : ""))
          : t("Group: none", "分組：冇"),
        isPinned(id) ? t("Pinned", "已釘住") : t("Not pinned", "未釘住"),
        isClosed(id) ? t("Closed", "已關閉") : t("Open", "開住")
      ].join(" · ");
      return optionButton({
        title: labelOf(tabOf(id)),
        meta: meta,
        colour: group ? group.colour : null,
        run: function () {
          closeOpenPanel(false);
          // Revealing a hit inside a collapsed group must not open the group:
          // the collapsed preference is the reader's, not the search's.
          activate(id, { focusPanel: true });
        }
      });
    });
    if (!rows.length) {
      rows.push(
        emptyNote(
          state.valid
            ? t(
                "No tab matches “" + state.query + "” in any strip or group.",
                "喺任何分頁條同分組入面都冇分頁配到「" + state.query + "」。"
              )
            : t("Nothing is listed while the pattern is invalid.", "個 pattern 唔啱嘅時候唔會列出任何嘢。")
        )
      );
    }
    masterList.replaceChildren.apply(masterList, rows);
    masterPanel.closeIn.textContent = t("Close tabs containing text…", "關閉包含文字嘅分頁…");
    masterPanel.closeOut.textContent = t("Close tabs not containing text…", "關閉唔包含文字嘅分頁…");
  }

  function openMasterSearch(anchor) {
    if (!masterPanel) buildMasterPanel();
    if (panelOpen(masterPanel)) {
      closeOpenPanel(true);
      return;
    }
    masterPanel.heading.textContent = t("Find any tab", "搵任何分頁");
    renderMasterList();
    openPanel(masterPanel, {
      anchor: anchor,
      trigger: anchor && anchor.hasAttribute && anchor.hasAttribute("aria-expanded") ? anchor : null,
      returnTo: anchor,
      focus: function () {
        masterSearch.input.focus();
      }
    });
  }

  // ------------------------------------------------------------- bulk close
  var closePanelRecord = null;
  var closeControl = null;
  var closeSearch = null;
  var closeMode = "in";
  var closeIncludePinned = false;
  var closeArmed = false;

  function bulkPredicate() {
    var state = stateOf(closeControl, closeSearch.input);
    return {
      state: state,
      // One predicate, negated for the inverse action, so flags, casing and
      // Unicode cannot drift between "containing" and "not containing".
      test: function (id) {
        return hits(closeControl, labelOf(tabOf(id)));
      }
    };
  }

  function bulkSelection() {
    var predicate = bulkPredicate();
    var state = predicate.state;
    if (!state.query || !state.valid) {
      return { state: state, doomed: [], protectedPinned: [], blocked: true };
    }
    var doomed = [];
    var protectedPinned = [];
    live.forEach(function (tab) {
      var id = tab.id;
      if (isClosed(id)) return;
      var hit = predicate.test(id);
      var wanted = closeMode === "in" ? hit : !hit;
      if (!wanted) return;
      if (isPinned(id)) {
        protectedPinned.push(id);
        if (closeIncludePinned) doomed.push(id);
        return;
      }
      doomed.push(id);
    });
    return { state: state, doomed: doomed, protectedPinned: protectedPinned, blocked: false };
  }

  function buildClosePanel() {
    closePanelRecord = makePanel("tab-close-panel", t("Close tabs by text", "按文字關閉分頁"));
    closeSearch = searchRow({
      id: "tab-close-search",
      name: "tabclose",
      label: t("Text to match against tab labels", "用嚟對分頁標籤嘅文字"),
      builderLabel: t("Regex builder · bulk close", "Regex builder · 批次關閉")
    });

    var modeIn = el("input", { type: "radio", name: "tab-close-mode", id: "tab-close-mode-in", value: "in" });
    var modeOut = el("input", { type: "radio", name: "tab-close-mode", id: "tab-close-mode-out", value: "out" });
    var includePinned = el("input", { type: "checkbox", id: "tab-close-pinned" });
    var preview = el("div", { class: "tab-preview" });
    var status = el("p", { class: "tab-panel-note", role: "status" });
    var confirm = el("button", { type: "button", class: "tab-tool tab-danger", id: "tab-close-confirm" });
    var cancel = el("button", { type: "button", class: "tab-tool", id: "tab-close-cancel" });

    function disarm() {
      if (!closeArmed) return;
      closeArmed = false;
      renderClosePanel();
    }

    modeIn.addEventListener("change", function () {
      closeMode = "in";
      disarm();
      renderClosePanel();
    });
    modeOut.addEventListener("change", function () {
      closeMode = "out";
      disarm();
      renderClosePanel();
    });
    includePinned.addEventListener("change", function () {
      closeIncludePinned = includePinned.checked;
      disarm();
      renderClosePanel();
    });
    cancel.addEventListener("click", function () {
      disarm();
      confirm.focus();
    });
    confirm.addEventListener("click", function () {
      var selection = bulkSelection();
      if (selection.blocked || !selection.doomed.length) return;
      if (!closeArmed) {
        closeArmed = true;
        renderClosePanel();
        return;
      }
      closeArmed = false;
      var names = selection.doomed.map(function (id) {
        return labelOf(tabOf(id));
      });
      selection.doomed.forEach(function (id) {
        closeTab(id, true);
      });
      renderClosePanel();
      A.notify(
        emoji("✖️") + t("Closed " + count(names.length, "tab", "tabs"), "已關閉 " + names.length + " 個分頁"),
        t(
          names.join(", ") + ". Their panels are hidden; Reopen closed tabs puts every one of them back.",
          names.join("、") + "。佢哋嘅內容收埋咗；撳「重開已關閉分頁」就可以全部開返。"
        )
      );
      confirm.focus();
    });

    closePanelRecord.parts = {
      modeIn: modeIn,
      modeOut: modeOut,
      includePinned: includePinned,
      preview: preview,
      status: status,
      confirm: confirm,
      cancel: cancel,
      modeInLabel: el("label", { for: "tab-close-mode-in" }),
      modeOutLabel: el("label", { for: "tab-close-mode-out" }),
      pinnedLabel: el("label", { for: "tab-close-pinned" }),
      lead: el("p", { class: "tab-panel-note" })
    };

    closePanelRecord.body.replaceChildren(
      closePanelRecord.parts.lead,
      closeSearch.label,
      closeSearch.panel,
      el(
        "div",
        { class: "tab-panel-row", role: "radiogroup", "aria-label": t("Match mode", "配對方式") },
        modeIn,
        closePanelRecord.parts.modeInLabel,
        modeOut,
        closePanelRecord.parts.modeOutLabel
      ),
      el("div", { class: "tab-panel-row" }, includePinned, closePanelRecord.parts.pinnedLabel),
      preview,
      status,
      el("div", { class: "tab-panel-actions" }, confirm, cancel)
    );

    closePanelRecord.root.addEventListener("focusout", function (event) {
      if (closeArmed && !closePanelRecord.root.contains(event.relatedTarget)) disarm();
    });

    closeControl = attachSearch({
      name: "tabclose",
      input: closeSearch.input,
      openButton: closeSearch.openButton,
      panel: closeSearch.panel,
      sample: "Home Features Docs Screenshots Guides Community Changelog History Settings",
      onChange: function () {
        closeArmed = false;
        renderClosePanel();
      }
    });
  }

  function renderClosePanel() {
    if (!closePanelRecord) return;
    var parts = closePanelRecord.parts;
    var selection = bulkSelection();
    var state = selection.state;

    parts.modeIn.checked = closeMode === "in";
    parts.modeOut.checked = closeMode === "out";
    parts.includePinned.checked = closeIncludePinned;
    parts.modeInLabel.textContent = t("Close tabs containing the text", "關閉包含呢啲文字嘅分頁");
    parts.modeOutLabel.textContent = t("Close tabs not containing the text", "關閉唔包含呢啲文字嘅分頁");
    parts.pinnedLabel.textContent = t("Include pinned tabs", "連釘住嘅分頁一齊計");
    parts.lead.textContent = t(
      "The text is matched against each tab's visible label only. The inverse negates that same match, so the two modes cannot disagree about casing or flags.",
      "呢啲文字淨係對分頁見到嘅標籤。反向模式係將同一個配對取反，所以兩個模式喺大細楷同 flags 上面唔會有出入。"
    );

    var rows = [];
    if (selection.protectedPinned.length) {
      rows.push(
        el("p", {
          class: "tab-preview-flag",
          text: closeIncludePinned
            ? t(
                count(selection.protectedPinned.length, "pinned tab is", "pinned tabs are") +
                  " included and will close: " +
                  selection.protectedPinned
                    .map(function (id) {
                      return labelOf(tabOf(id));
                    })
                    .join(", "),
                "有 " + selection.protectedPinned.length + " 個釘住嘅分頁會一齊關閉：" +
                  selection.protectedPinned
                    .map(function (id) {
                      return labelOf(tabOf(id));
                    })
                    .join("、")
              )
            : t(
                count(selection.protectedPinned.length, "pinned tab matches", "pinned tabs match") +
                  " and is protected: " +
                  selection.protectedPinned
                    .map(function (id) {
                      return labelOf(tabOf(id));
                    })
                    .join(", "),
                "有 " + selection.protectedPinned.length + " 個釘住嘅分頁配到，但受保護冇計入：" +
                  selection.protectedPinned
                    .map(function (id) {
                      return labelOf(tabOf(id));
                    })
                    .join("、")
              )
        })
      );
    }
    selection.doomed.forEach(function (id) {
      var group = groupOf(id);
      rows.push(
        el(
          "div",
          { class: "tab-preview-row" },
          el("span", { text: labelOf(tabOf(id)) }),
          el("span", {
            class: "tab-preview-flag",
            text:
              (isPinned(id) ? t("pinned", "已釘住") + " · " : "") +
              (group ? group.name : t("ungrouped", "冇分組"))
          })
        )
      );
    });
    if (!rows.length) {
      rows.push(
        el("p", {
          class: "tab-preview-flag",
          text: !state.query
            ? t("Nothing will close: there is no text to match yet.", "冇嘢會關閉：仲未有文字可以對。")
            : !state.valid
            ? t("Nothing will close while the pattern is invalid.", "個 pattern 唔啱嘅時候乜都唔會關閉。")
            : t("No open tab matches, so nothing will close.", "冇開住嘅分頁配到，所以乜都唔會關閉。")
        })
      );
    }
    parts.preview.replaceChildren.apply(parts.preview, rows);

    var blocked = selection.blocked || !selection.doomed.length;
    parts.confirm.disabled = blocked;
    parts.confirm.setAttribute("data-armed", String(closeArmed));
    parts.cancel.hidden = !closeArmed;

    if (blocked) {
      parts.confirm.textContent = t("Close matching tabs", "關閉配到嘅分頁");
      parts.status.textContent = !state.query
        ? t(
            "Type the text to match first. A bulk close never runs on an empty query.",
            "要先打要對嘅文字。批次關閉唔會喺冇輸入嘅情況下執行。"
          )
        : !state.valid
        ? t(
            "The pattern is not valid, so the action is refused: " + state.feedback,
            "個 pattern 唔啱，所以拒絕執行：" + state.feedback
          )
        : t(
            "No open tab matches “" + state.query + "” (" + modeSentence(state) + "), so there is nothing to close.",
            "冇開住嘅分頁配到「" + state.query + "」（" + modeSentence(state) + "），所以冇嘢可以關閉。"
          );
      return;
    }

    var names = selection.doomed.map(function (id) {
      return labelOf(tabOf(id));
    });
    parts.confirm.textContent = closeArmed
      ? t("Confirm — close " + names.length + ": " + names.join(", "), "確認 — 關閉 " + names.length + " 個：" + names.join("、"))
      : t("Close " + count(names.length, "tab", "tabs"), "關閉 " + names.length + " 個分頁");
    parts.cancel.textContent = t("Cancel", "取消");
    parts.status.textContent = closeArmed
      ? t(
          "Armed. The next press closes " + names.join(", ") + ". Their panels are hidden, not deleted, and Reopen closed tabs restores every one. Press Cancel or Escape to stop.",
          "已解鎖。再撳一次就會關閉：" + names.join("、") + "。佢哋嘅內容係收埋唔係刪除，撳「重開已關閉分頁」可以全部開返。撳「取消」或者 Escape 就停手。"
        )
      : t(
          count(names.length, "tab", "tabs") + " will close, matched by " + modeSentence(state) +
            " against “" + state.query + "” in " +
            (closeMode === "in" ? "containing" : "not containing") + " mode.",
          "會關閉 " + names.length + " 個分頁，用" + modeSentence(state) + "對「" + state.query + "」，模式係" +
            (closeMode === "in" ? "包含" : "唔包含") + "。"
        );
  }

  function openBulkClose(mode, anchor) {
    if (!closePanelRecord) buildClosePanel();
    closeMode = mode === "out" ? "out" : "in";
    closeArmed = false;
    closePanelRecord.heading.textContent =
      closeMode === "in"
        ? t("Close tabs containing text", "關閉包含文字嘅分頁")
        : t("Close tabs not containing text", "關閉唔包含文字嘅分頁");
    renderClosePanel();
    openPanel(closePanelRecord, {
      anchor: anchor || toolsRow,
      returnTo: anchor || toolsRow,
      onClose: function () {
        closeArmed = false;
      },
      focus: function () {
        closeSearch.input.focus();
      }
    });
  }

  // ------------------------------------------------------- in-place confirms
  var confirmPanel = null;

  function openConfirm(config) {
    if (!confirmPanel) confirmPanel = makePanel("tab-confirm-panel", t("Confirm", "確認"));
    var armed = false;
    var run = el("button", { type: "button", class: "tab-tool tab-danger" });
    var stop = el("button", { type: "button", class: "tab-tool", text: t("Cancel", "取消") });
    var status = el("p", { class: "tab-panel-note", role: "status" });

    function paint() {
      run.setAttribute("data-armed", String(armed));
      run.textContent = armed ? config.confirmLabel : config.armLabel;
      status.textContent = armed ? config.armedText : config.text;
    }

    run.addEventListener("click", function () {
      if (!armed) {
        armed = true;
        paint();
        return;
      }
      closeOpenPanel(false);
      config.run();
    });
    stop.addEventListener("click", function () {
      closeOpenPanel(true);
    });

    confirmPanel.heading.textContent = config.title;
    confirmPanel.body.replaceChildren(status, el("div", { class: "tab-panel-actions" }, run, stop));
    paint();
    openPanel(confirmPanel, {
      anchor: config.anchor,
      returnTo: config.returnTo || config.anchor,
      focus: function () {
        run.focus();
      }
    });
  }

  function confirmCloseTab(id, anchor) {
    var label = labelOf(tabOf(id));
    openConfirm({
      title: t("Close the " + tabOf(id).en + " tab", "關閉「" + tabOf(id).yue + "」分頁"),
      anchor: anchor,
      text: t(
        "Closing hides the " + label + " tab and its panel. Nothing on the page is deleted, and Reopen closed tabs puts it back exactly where it was.",
        "關閉會收埋「" + label + "」分頁同佢嘅內容。頁面上冇任何嘢會被刪除，撳「重開已關閉分頁」就會原位開返。"
      ),
      armLabel: t("Close this tab", "關閉呢個分頁"),
      confirmLabel: t("Confirm — close " + label, "確認 — 關閉「" + label + "」"),
      armedText: t(
        "Armed. The next press closes " + label + ". Press Cancel or Escape to stop.",
        "已解鎖。再撳一次就會關閉「" + label + "」。撳「取消」或者 Escape 就停手。"
      ),
      run: function () {
        closeTab(id);
      }
    });
  }

  function confirmRemoveGroup(gid) {
    var group = groupById(gid);
    if (!group) return;
    var open = group.members.filter(function (id) {
      return !isClosed(id);
    });
    var names = open.map(function (id) {
      return labelOf(tabOf(id));
    });
    openConfirm({
      title: t("Remove the " + group.name + " group", "移除分組「" + group.name + "」"),
      anchor: groupNodes[gid] ? groupNodes[gid].toggle : null,
      text: t(
        "Removing the group discards its name “" + group.name + "”, its colour " + group.colour +
          " and its collapsed state. No tab is closed: " +
          (names.length ? names.join(", ") + " return to the strip where the group stood." : "the group is empty."),
        "移除呢個分組會刪咗個名「" + group.name + "」、顏色 " + group.colour + " 同收埋狀態。冇分頁會被關閉：" +
          (names.length ? names.join("、") + " 會返去分組原本嘅位置。" : "呢個分組本身係空嘅。")
      ),
      armLabel: t("Remove this group", "移除呢個分組"),
      confirmLabel: t("Confirm — remove " + group.name, "確認 — 移除「" + group.name + "」"),
      armedText: t(
        "Armed. The next press removes the group and keeps every tab. Press Cancel or Escape to stop.",
        "已解鎖。再撳一次就會移除個分組，所有分頁照樣保留。撳「取消」或者 Escape 就停手。"
      ),
      run: function () {
        var members = deleteGroup(gid);
        if (groupsList) renderGroupsList();
        A.notify(
          emoji("🗂️") + t("Removed the " + group.name + " group", "已移除分組「" + group.name + "」"),
          t(
            count(members ? members.length : 0, "tab was kept", "tabs were kept") + " and returned to the strip.",
            "保留咗 " + (members ? members.length : 0) + " 個分頁，已經放返分頁條。"
          )
        );
      }
    });
  }

  // ------------------------------------------------------------- menu items
  function dockItems() {
    return DOCKS.map(function (edge) {
      return {
        label: t("Dock the strip to the " + edge + " edge", "將分頁條停靠喺" + dockName(edge)),
        disabled: dock === edge,
        disabledReason: t("The strip is already docked here.", "分頁條已經喺呢邊。"),
        run: function () {
          setDock(edge);
        }
      };
    });
  }

  function tabMenuItems(id) {
    var tab = tabOf(id);
    var on = isPinned(id);
    var group = groupOf(id);
    var axis = isVertical() ? "Ctrl+Up" : "Ctrl+Left";
    var axisNext = isVertical() ? "Ctrl+Down" : "Ctrl+Right";
    var items = [
      {
        label: t("Go to the " + tab.en + " tab", "去「" + tab.yue + "」分頁"),
        shortcut: "Enter",
        run: function () {
          activate(id, { focusPanel: true });
        }
      },
      {
        label: on
          ? t("Unpin the " + tab.en + " tab", "取消釘住「" + tab.yue + "」分頁")
          : t("Pin the " + tab.en + " tab", "釘住「" + tab.yue + "」分頁"),
        shortcut: "P",
        run: function () {
          togglePin(id);
        }
      },
      { separator: true },
      {
        label: t("Move into group…", "移去分組…"),
        shortcut: "M",
        run: function () {
          openMovePicker(id, nodes[id].button);
        }
      }
    ];
    if (group) {
      items.push({
        label: t("Take it out of " + group.name, "由「" + group.name + "」拎返出嚟"),
        run: function () {
          moveTabTo(id, null, null);
        }
      });
    }
    items.push({
      label: t("Move it earlier", "向前移"),
      shortcut: axis,
      run: function () {
        moveTabBy(id, -1);
      }
    });
    items.push({
      label: t("Move it later", "向後移"),
      shortcut: axisNext,
      run: function () {
        moveTabBy(id, 1);
      }
    });
    items.push({ separator: true });
    items.push({
      label: t("Copy link to this tab", "複製呢個分頁嘅連結"),
      run: function () {
        copyLink(id);
      }
    });
    items.push({
      label: t("Close this tab…", "關閉呢個分頁…"),
      run: function () {
        confirmCloseTab(id, nodes[id].button);
      }
    });
    return items.concat(stripMenuItems());
  }

  function groupMenuItems(gid, shiftOpened) {
    var group = groupById(gid);
    if (!group) return stripMenuItems();
    if (shiftOpened) {
      // Shift+right-click opens the appearance editor directly, so the menu it
      // would have shown is skipped rather than shown and then replaced.
      window.setTimeout(function () {
        openGroupAppearance(gid, groupNodes[gid] ? groupNodes[gid].toggle : null);
      }, 0);
      return [];
    }
    var axis = isVertical() ? "Ctrl+Up" : "Ctrl+Left";
    var axisNext = isVertical() ? "Ctrl+Down" : "Ctrl+Right";
    return [
      {
        label: group.collapsed
          ? t("Expand the " + group.name + " group", "展開分組「" + group.name + "」")
          : t("Collapse the " + group.name + " group", "收埋分組「" + group.name + "」"),
        shortcut: "Enter",
        run: function () {
          setCollapsed(gid, !group.collapsed);
        }
      },
      {
        label: t("Edit group appearance…", "編輯分組外觀…"),
        shortcut: "Shift+Right-click",
        run: function () {
          openGroupAppearance(gid, groupNodes[gid] ? groupNodes[gid].toggle : null);
        }
      },
      {
        label: t("Search tabs in this group", "喺呢個分組入面搵分頁"),
        run: function () {
          var record = groupNodes[gid];
          if (!record) return;
          record.node.querySelector(".tab-group-search").hidden = false;
          record.find.setAttribute("aria-expanded", "true");
          record.search.input.focus();
        }
      },
      { separator: true },
      {
        label: t("Move the group earlier", "將分組向前移"),
        shortcut: axis,
        run: function () {
          moveGroupBy(gid, -1);
        }
      },
      {
        label: t("Move the group later", "將分組向後移"),
        shortcut: axisNext,
        run: function () {
          moveGroupBy(gid, 1);
        }
      },
      {
        label: t("Manage all groups…", "管理所有分組…"),
        run: function () {
          openGroupsPanel(groupNodes[gid] ? groupNodes[gid].toggle : null);
        }
      },
      {
        label: t("Remove this group…", "移除呢個分組…"),
        run: function () {
          confirmRemoveGroup(gid);
        }
      }
    ].concat(stripMenuItems());
  }

  function stripMenuItems() {
    var items = [
      { separator: true },
      {
        label: t("Find any tab…", "搵任何分頁…"),
        run: function () {
          openMasterSearch(toolAnchor("master"));
        }
      },
      {
        label: t("Tab groups…", "分頁分組…"),
        run: function () {
          openGroupsPanel(toolAnchor("groups"));
        }
      },
      {
        label: t("Close tabs containing text…", "關閉包含文字嘅分頁…"),
        run: function () {
          openBulkClose("in", toolAnchor("master"));
        }
      },
      {
        label: t("Close tabs not containing text…", "關閉唔包含文字嘅分頁…"),
        run: function () {
          openBulkClose("out", toolAnchor("master"));
        }
      }
    ];
    if (closedIds().length) {
      items.push({
        label: t("Reopen " + count(closedIds().length, "closed tab", "closed tabs"), "重開 " + closedIds().length + " 個已關閉分頁"),
        run: reopenAll
      });
    }
    items.push({ separator: true });
    dockItems().forEach(function (item) {
      items.push(item);
    });
    items.push({ separator: true });
    items.push({ label: t("Reset tab order", "重設分頁次序"), run: resetOrder });
    return items;
  }

  // --------------------------------------------------------------- clipboard
  function tabUrl(id) {
    return location.href.split("#")[0] + "#" + id;
  }

  function legacyCopy(text) {
    // file:// and other insecure contexts have no async clipboard, and a link the
    // user cannot copy is a menu item that does nothing.
    var field = document.createElement("textarea");
    field.value = text;
    field.setAttribute("readonly", "");
    field.style.position = "fixed";
    field.style.opacity = "0";
    document.body.appendChild(field);
    var done = false;
    try {
      field.select();
      done = document.execCommand("copy");
    } catch (error) {
      done = false;
    }
    document.body.removeChild(field);
    return done;
  }

  function copyLink(id) {
    var url = tabUrl(id);
    function reportOk() {
      A.notify(emoji("📋") + t("Link copied", "已複製連結"), url);
    }
    function reportFail(reason) {
      A.notify(
        emoji("⚠️") + t("Could not copy the link", "複製唔到連結"),
        t("Copy it by hand: ", "請自己手動複製：") + url + (reason ? " (" + reason + ")" : "")
      );
    }
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(url).then(reportOk, function (error) {
          if (legacyCopy(url)) reportOk();
          else reportFail(error && error.message ? error.message : String(error));
        });
        return;
      }
    } catch (error) {
      /* fall through to the synchronous route below */
    }
    if (legacyCopy(url)) reportOk();
    else reportFail(t("This browser refused clipboard access.", "呢個瀏覽器唔畀用剪貼簿。"));
  }

  // -------------------------------------------------------------------- tools
  var toolButtons = {};

  /** A panel anchors to a real control so Escape has somewhere to give focus back. */
  function toolAnchor(key) {
    var entry = toolButtons[key];
    if (entry && entry.button && !entry.button.hidden) return entry.button;
    if (activeId && nodes[activeId]) return nodes[activeId].button;
    return toolsRow;
  }

  function buildTools() {
    function tool(key, run, expands) {
      var labelNode = el("span", { class: "tab-tool-label" });
      var button = el("button", { type: "button", class: "tab-tool", "data-tool": key }, labelNode);
      if (expands) button.setAttribute("aria-expanded", "false");
      button.addEventListener("click", function () {
        run(button);
      });
      toolButtons[key] = { button: button, label: labelNode };
      return button;
    }

    var railToggle = el("button", {
      type: "button",
      class: "tab-tool tab-rail-toggle",
      "aria-expanded": "false",
      onclick: function () {
        var root = document.documentElement;
        var open = root.getAttribute("data-tab-rail") === "expanded";
        if (open) root.removeAttribute("data-tab-rail");
        else root.setAttribute("data-tab-rail", "expanded");
        railToggle.setAttribute("aria-expanded", open ? "false" : "true");
        updateTools();
        scheduleMeasure();
      }
    });
    toolButtons.rail = { button: railToggle, label: null };

    toolsRow = el(
      "div",
      { class: "tab-tools", role: "group" },
      tool("master", function (button) {
        openMasterSearch(button);
      }, true),
      tool("groups", function (button) {
        openGroupsPanel(button);
      }, true),
      tool("reopen", function () {
        reopenAll();
      }, false),
      railToggle
    );
  }

  function updateTools() {
    if (!toolsRow) return;
    var master = toolButtons.master;
    if (master) {
      master.label.textContent = t("Find any tab", "搵任何分頁");
      master.button.setAttribute(
        "aria-label",
        t("Find any tab across every strip and group", "喺所有分頁條同分組入面搵任何分頁")
      );
      master.button.setAttribute("title", master.button.getAttribute("aria-label"));
    }
    var groupsTool = toolButtons.groups;
    if (groupsTool) {
      groupsTool.label.textContent = t("Groups", "分組") + " (" + groups.length + ")";
      groupsTool.button.setAttribute(
        "aria-label",
        t(
          "Tab groups, " + count(groups.length, "group", "groups"),
          "分頁分組，共 " + groups.length + " 個"
        )
      );
      groupsTool.button.setAttribute("title", groupsTool.button.getAttribute("aria-label"));
    }
    var reopen = toolButtons.reopen;
    if (reopen) {
      var shut = closedIds();
      // A button that would do nothing is not rendered rather than disabled.
      reopen.button.hidden = shut.length === 0;
      reopen.label.textContent = t("Reopen closed", "重開已關閉") + " (" + shut.length + ")";
      reopen.button.setAttribute(
        "aria-label",
        t(
          "Reopen " + count(shut.length, "closed tab", "closed tabs") + ": " +
            shut
              .map(function (id) {
                return labelOf(tabOf(id));
              })
              .join(", "),
          "重開 " + shut.length + " 個已關閉分頁：" +
            shut
              .map(function (id) {
                return labelOf(tabOf(id));
              })
              .join("、")
        )
      );
      reopen.button.setAttribute("title", reopen.button.getAttribute("aria-label"));
    }
    var rail = toolButtons.rail;
    if (rail) {
      var expanded = document.documentElement.getAttribute("data-tab-rail") === "expanded";
      rail.button.textContent = expanded ? "«" : "»";
      rail.button.setAttribute(
        "aria-label",
        expanded
          ? t("Collapse the tab rail back to initials", "收窄分頁條，只顯示首字")
          : t("Expand the tab rail to show labels and its search", "展開分頁條，顯示標籤同搜尋")
      );
      rail.button.setAttribute("title", rail.button.getAttribute("aria-label"));
    }
    if (overflowButton) updateOverflowLabel();
  }

  // -------------------------------------------------------- settings surface
  var dockCard = null;
  var dockSelect = null;
  var dockCardParts = null;

  function dockProvenance() {
    var storedDock = A.store.get(KEY_DOCK, null);
    return DOCKS.indexOf(storedDock) >= 0
      ? t(
          "Stored in this browser for the primary strip; the shipped value is the left edge.",
          "已為主要分頁條存喺呢個瀏覽器；出廠值係左邊。"
        )
      : t(
          "Not set here yet, so the shipped value (the left edge) is in use.",
          "呢度未設定過，所以用緊出廠值（左邊）。"
        );
  }

  function refreshDockCard() {
    if (!dockCard) return;
    dockCardParts.label.textContent = t("Tab strip edge", "分頁條位置");
    dockCardParts.help.textContent = t(
      "Docks the primary tab strip to the left, right, top or bottom edge. A left or right strip is vertical: its arrow keys become Up and Down and its overflow is measured by height. The choice is stored per surface, and this page has one strip.",
      "將主要分頁條停靠喺左、右、上或者下面。左右兩邊係直向：方向鍵變上下，超出範圍以高度計。呢個選擇按介面分開儲存，而呢一頁得一條分頁條。"
    );
    dockCardParts.provenance.textContent = dockProvenance();
    dockCardParts.options.forEach(function (entry) {
      entry.node.textContent = dockLabel(entry.value);
    });
    if (dockSelect.value !== dock) dockSelect.value = dock;
  }

  function dockSearchText() {
    return [
      "tabdock",
      "Tab strip edge",
      "分頁條位置",
      "dock left right top bottom vertical horizontal orientation",
      dockCardParts ? dockCardParts.help.textContent : "",
      dockLabel(dock)
    ].join(" ");
  }

  function installDockSetting() {
    var grid = document.getElementById("settings-grid");
    if (!grid || dockCard) return;

    var id = "setting-tabdock";
    var labelNode = el("span", { id: id + "-label" });
    var helpNode = el("small", { class: "setting-help", id: id + "-help" });
    var provenanceNode = el("small", { class: "setting-provenance" });
    dockSelect = el("select", {
      id: id,
      "aria-labelledby": id + "-label",
      "aria-describedby": id + "-help",
      onchange: function () {
        setDock(dockSelect.value);
      }
    });
    var options = DOCKS.map(function (edge) {
      var node = el("option", { value: edge });
      dockSelect.appendChild(node);
      return { value: edge, node: node };
    });

    dockCard = el(
      "div",
      { class: "setting-card", id: id + "-card", "data-setting": "tabdock" },
      labelNode,
      el("div", { class: "setting-control" }, dockSelect),
      helpNode,
      provenanceNode
    );
    dockCardParts = { label: labelNode, help: helpNode, provenance: provenanceNode, options: options };
    grid.appendChild(dockCard);
    refreshDockCard();

    // The settings grid has its own search. Reading the shared builder's stored
    // mode reproduces its semantics exactly, so this card hides and shows on the
    // same rule as every card beside it rather than on a private one.
    var input = document.getElementById("settings-search");
    if (input) {
      var filter = function () {
        var query = input.value;
        if (!query) {
          dockCard.hidden = false;
          return;
        }
        var saved = A.store.get("regex.settings", null) || {};
        var match = false;
        try {
          match = A.matcher(query, saved.regex === true, saved.flags == null ? "i" : saved.flags).test(
            dockSearchText()
          );
        } catch (error) {
          match = false;
        }
        dockCard.hidden = !match;
      };
      input.addEventListener("input", filter);
      filter();
    }

    if (typeof A.settings.register === "function") {
      A.settings.register({
        key: "tabdock",
        type: "select",
        tab: "settings",
        cardId: dockCard.id,
        controlId: id,
        label: "Tab strip edge",
        help: "Docks the primary tab strip to the left, right, top or bottom edge.",
        labelNow: function () {
          return t("Tab strip edge", "分頁條位置");
        },
        helpNow: function () {
          return dockCardParts.help.textContent;
        },
        value: function () {
          return dockLabel(dock) + " (" + dock + ")";
        },
        isDefault: function () {
          return DOCKS.indexOf(A.store.get(KEY_DOCK, null)) < 0;
        },
        provenance: dockProvenance,
        focus: function () {
          dockSelect.focus();
        },
        node: dockCard
      });
    }
  }

  // -------------------------------------------------------------------- init
  function idFromHash() {
    var raw = String(location.hash || "").replace(/^#/, "");
    return nodes[raw] ? raw : null;
  }

  function firstShownId() {
    for (var i = 0; i < live.length; i++) {
      var one = nodes[live[i].id];
      if (!one.panel.hasAttribute("hidden") && !isClosed(live[i].id)) return live[i].id;
    }
    var open = openIds();
    return open.length ? open[0] : live.length ? live[0].id : null;
  }

  function attachStripSearch() {
    searchField = document.getElementById("tab-search");
    if (!searchField) return;
    searchLabel = searchField.closest(".search-field") || searchField.parentNode;
    if (searchLabel && searchLabel.classList) searchLabel.classList.add("tab-strip-search");
    searchControl = attachSearch({
      name: "tab",
      input: searchField,
      openButton: document.getElementById("tab-regex-open"),
      panel: document.getElementById("tab-regex"),
      sample: "Home Features Docs Screenshots Guides Community Changelog History Settings",
      onChange: applyFilter
    });
  }

  A.ready(function () {
    strip = document.getElementById("tab-strip");
    if (!strip) return;
    bar = strip.parentNode;
    note = document.getElementById("tab-note");
    regexPanel = document.getElementById("tab-regex");
    if (regexPanel && regexPanel.parentNode) {
      regexHome = { parent: regexPanel.parentNode, next: regexPanel.nextSibling };
    }
    if (note && note.parentNode) {
      noteHome = { parent: note.parentNode, next: note.nextSibling };
    }

    installStyle();
    buildNodes();
    if (!live.length) return;

    pinnedRegion = el("div", { class: "tab-region tab-pinned", role: "presentation" });
    flow = el("div", { class: "tab-region tab-flow", role: "presentation" });
    overflowButton = el("button", {
      type: "button",
      class: "tab-tool tab-overflow",
      "aria-expanded": "false",
      hidden: true,
      onclick: openOverflow
    });
    strip.replaceChildren(pinnedRegion, flow, overflowButton);
    wireFlowDrop();

    buildTools();
    bar.insertBefore(toolsRow, strip);

    pinned = readPins();
    closed = readClosed();
    groups = readGroups();
    order = Array.isArray(A.store.get(KEY_ORDER, [])) ? A.store.get(KEY_ORDER, []) : [];
    dock = readDock();

    attachStripSearch();
    applyDock();

    strip.addEventListener("contextmenu", function (event) {
      if (event.target.closest && (event.target.closest(".tab-wrap") || event.target.closest(".tab-group"))) return;
      event.preventDefault();
      A.contextMenu(stripMenuItems().slice(1), event, t("Tab strip menu", "分頁條選單"));
    });

    A.showTab = function (id, options) {
      var opts = options || {};
      return activate(id, { focusPanel: opts.focusPanel !== false });
    };

    A.tabs = {
      all: function () {
        return live.map(function (tab) {
          var group = groupOf(tab.id);
          return {
            id: tab.id,
            label: labelOf(tab),
            pinned: isPinned(tab.id),
            closed: isClosed(tab.id),
            active: activeId === tab.id,
            group: group ? group.id : null,
            groupName: group ? group.name : null,
            strip: SURFACE
          };
        });
      },
      groups: function () {
        return groups.map(function (group) {
          return {
            id: group.id,
            name: group.name,
            colour: group.colour,
            collapsed: group.collapsed === true,
            members: group.members.slice()
          };
        });
      },
      dock: function () {
        return dock;
      },
      setDock: function (edge) {
        return setDock(edge);
      },
      close: function (id) {
        return closeTab(id);
      },
      pin: function (id, on) {
        return setPinned(id, on === undefined ? !isPinned(id) : on === true);
      }
    };

    A.registerPaletteSource(function () {
      var results = orderedIds().map(function (id) {
        var tab = tabOf(id);
        var group = groupOf(id);
        return {
          kind: "Tab",
          title: labelOf(tab),
          subtitle:
            t("Tab · #" + id, "分頁 · #" + id) +
            (isPinned(id) ? t(" · pinned", " · 已釘住") : "") +
            (group ? t(" · group " + group.name, " · 分組 " + group.name) : "") +
            (isClosed(id) ? t(" · closed", " · 已關閉") : ""),
          run: function () {
            activate(id, { focusPanel: true });
          }
        };
      });

      results.push({
        kind: "Command",
        title: t("Find any tab", "搵任何分頁"),
        subtitle: t(
          "Master search over every tab in every strip and group",
          "喺所有分頁條同分組入面搵每一個分頁"
        ),
        run: function () {
          openMasterSearch(toolAnchor("master"));
        }
      });
      results.push({
        kind: "Command",
        title: t("Tab groups", "分頁分組"),
        subtitle: t(
          count(groups.length, "group", "groups") + " · create, rename, colour, reorder, remove",
          groups.length + " 個分組 · 建立、改名、換色、排序、移除"
        ),
        run: function () {
          openGroupsPanel(toolAnchor("groups"));
        }
      });
      results.push({
        kind: "Command",
        title: t("Close tabs containing text", "關閉包含文字嘅分頁"),
        subtitle: t(
          "Previews the affected tabs and excludes pinned tabs by default",
          "會先預覽受影響嘅分頁，預設唔會計釘住嘅分頁"
        ),
        run: function () {
          openBulkClose("in", toolAnchor("master"));
        }
      });
      results.push({
        kind: "Command",
        title: t("Close tabs not containing text", "關閉唔包含文字嘅分頁"),
        subtitle: t(
          "The same predicate, negated, so casing and flags cannot drift",
          "同一個配對取反，所以大細楷同 flags 唔會有出入"
        ),
        run: function () {
          openBulkClose("out", toolAnchor("master"));
        }
      });
      if (closedIds().length) {
        results.push({
          kind: "Command",
          title: t("Reopen closed tabs", "重開已關閉分頁"),
          subtitle: closedIds()
            .map(function (id) {
              return labelOf(tabOf(id));
            })
            .join(", "),
          run: reopenAll
        });
      }
      DOCKS.forEach(function (edge) {
        if (edge === dock) return;
        results.push({
          kind: "Setting",
          title: t("Dock the tab strip to the " + edge + " edge", "將分頁條停靠喺" + dockName(edge)),
          subtitle: t(
            edge === "left" || edge === "right"
              ? "Vertical strip · Up and Down arrows · height-measured overflow"
              : "Horizontal strip · Left and Right arrows · width-measured overflow",
            edge === "left" || edge === "right"
              ? "直向分頁條 · 上下方向鍵 · 以高度計超出範圍"
              : "橫向分頁條 · 左右方向鍵 · 以闊度計超出範圍"
          ),
          run: function () {
            setDock(edge);
          }
        });
      });
      return results;
    });

    A.settings.onChange(function (key) {
      if (key === null || key === "language" || key === "emoji") {
        layout();
        refreshDockCard();
        if (groupsList) renderGroupsList();
        if (masterList) renderMasterList();
        if (moveList && moveTarget) renderMoveList();
        if (closePanelRecord) renderClosePanel();
      }
      if (key === null || key === "density" || key === "scale" || key === "font") scheduleMeasure();
    });

    window.addEventListener("hashchange", function () {
      var id = idFromHash();
      if (id && id !== activeId) activate(id, { focusPanel: true });
    });

    window.addEventListener("resize", scheduleMeasure);
    if (typeof window.ResizeObserver === "function") {
      var observer = new window.ResizeObserver(function () {
        scheduleMeasure();
      });
      observer.observe(bar);
      observer.observe(strip);
    }

    var pending = typeof A._pendingTab === "string" && nodes[A._pendingTab] ? A._pendingTab : null;
    var initial = idFromHash() || pending || firstShownId();
    // No focus move on load: the reader has not asked to go anywhere yet.
    if (initial) activate(initial, { scroll: false });
    else layout();

    // settings-panel.js replaces the whole grid in its own ready handler, so the
    // dock card is added after every DOMContentLoaded listener has run.
    window.setTimeout(installDockSetting, 0);
  });
})();
