/* Browser-style tab strip.
 *
 * Owns #tab-strip, the panels it controls, the pinned order that survives a
 * reload, and the tab search. Every other script changes page through
 * AmuletSite.showTab, which this file takes over from the core stub.
 */
(function () {
  "use strict";

  var A = window.AmuletSite;
  if (!A) return;

  var TABS = [
    { id: "home", en: "Home", yue: "首頁" },
    { id: "features", en: "Features", yue: "功能" },
    { id: "docs", en: "Docs", yue: "文件" },
    { id: "screenshots", en: "Screenshots", yue: "截圖" },
    { id: "guides", en: "Guides", yue: "指南" },
    { id: "community", en: "Community", yue: "社群" },
    { id: "settings", en: "Settings", yue: "設定" },
  ];

  var PIN_KEY = "tabs.pinned";
  var PIN_ON = "★";
  var PIN_OFF = "☆";

  var strip = null;
  var note = null;
  var searchField = null;
  var searchControl = null;
  var live = []; // tabs whose panel actually exists in the document
  var nodes = {}; // id -> { tab, wrap, button, label, pin, panel }
  var pinned = [];
  var activeId = null;

  function t(en, yue) {
    return A.lang.t(en, yue);
  }

  function labelOf(tab) {
    return t(tab.en, tab.yue);
  }

  function isPinned(id) {
    return pinned.indexOf(id) >= 0;
  }

  function orderedIds() {
    var head = pinned.slice();
    var tail = [];
    live.forEach(function (tab) {
      if (head.indexOf(tab.id) < 0) tail.push(tab.id);
    });
    return head.concat(tail);
  }

  function visibleIds() {
    return orderedIds().filter(function (id) {
      return !nodes[id].wrap.hidden;
    });
  }

  function prefersReduced() {
    if (A.settings.get("reducedMotion")) return true;
    try {
      return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    } catch (error) {
      return false;
    }
  }

  // ------------------------------------------------------------------ pins
  function readPins() {
    var raw = A.store.get(PIN_KEY, []);
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

  function persistPins() {
    if (A.store.set(PIN_KEY, pinned)) return;
    A.notify(
      A.lang.emoji("⚠️") + t("Pinned tabs are not being saved", "釘住嘅分頁儲唔到"),
      t(
        "This browser refused local storage, so the pinned order returns to the shipped order on reload.",
        "呢個瀏覽器唔畀用本機儲存，所以重新載入之後分頁次序會回復原狀。"
      )
    );
  }

  function togglePin(id) {
    var at = pinned.indexOf(id);
    if (at >= 0) pinned.splice(at, 1);
    else pinned.push(id);
    persistPins();
    layout();
  }

  function resetOrder() {
    if (!pinned.length) {
      A.notify(
        A.lang.emoji("📌") + t("Tab order is already the shipped order", "分頁次序本來就係原本嗰個"),
        t("No tab is pinned, so there was nothing to reset.", "冇分頁被釘住，所以冇嘢需要重設。")
      );
      return;
    }
    var count = pinned.length;
    pinned = [];
    persistPins();
    layout();
    A.notify(
      A.lang.emoji("📌") + t("Tab order reset", "分頁次序已重設"),
      t(
        count + (count === 1 ? " tab unpinned" : " tabs unpinned") + "; the strip is back in its shipped order.",
        "已取消釘住 " + count + " 個分頁，分頁條回復原本次序。"
      )
    );
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
      A.notify(A.lang.emoji("📋") + t("Link copied", "已複製連結"), url);
    }
    function reportFail(reason) {
      A.notify(
        A.lang.emoji("⚠️") + t("Could not copy the link", "複製唔到連結"),
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

  // -------------------------------------------------------------- rendering
  function buildNodes() {
    TABS.forEach(function (tab) {
      var panel = document.getElementById(tab.id);
      if (!panel) return; // no panel, no tab: a tab that controls nothing is a lie

      var labelNode = A.el("span", { class: "tab-label", text: tab.en });
      var button = A.el(
        "button",
        {
          type: "button",
          class: "tab",
          role: "tab",
          id: "tab-" + tab.id,
          "data-tab": tab.id,
          "aria-controls": tab.id,
          "aria-selected": "false",
          tabindex: "-1",
        },
        labelNode
      );
      var pin = A.el("button", {
        type: "button",
        class: "tab-pin",
        "data-tab": tab.id,
        "aria-pressed": "false",
        tabindex: "-1",
        text: PIN_OFF,
      });
      // role=presentation keeps the wrapper out of the accessibility tree so the
      // tablist's children read as tabs rather than as generic containers.
      var wrap = A.el("div", { class: "tab-wrap", role: "presentation" }, button, pin);

      button.addEventListener("click", function () {
        activate(tab.id, { focusPanel: true });
      });
      button.addEventListener("keydown", onTabKeyDown);
      pin.addEventListener("click", function () {
        togglePin(tab.id);
      });
      wrap.addEventListener("contextmenu", function (event) {
        event.preventDefault();
        A.contextMenu(menuItems(tab.id), event);
      });

      nodes[tab.id] = { tab: tab, wrap: wrap, button: button, label: labelNode, pin: pin, panel: panel };
      live.push(tab);
      strip.appendChild(wrap);
    });
  }

  /** Order, labels and pin state, applied without replacing any node. */
  function layout() {
    var focused = document.activeElement;
    var restore = focused && strip.contains(focused) ? focused : null;

    orderedIds().forEach(function (id) {
      var entry = nodes[id];
      var on = isPinned(id);
      entry.label.textContent = labelOf(entry.tab);
      entry.wrap.classList.toggle("is-pinned", on);
      entry.pin.textContent = on ? PIN_ON : PIN_OFF;
      entry.pin.setAttribute("aria-pressed", on ? "true" : "false");
      var pinLabel = on
        ? t("Unpin the " + entry.tab.en + " tab", "取消釘住「" + entry.tab.yue + "」分頁")
        : t("Pin the " + entry.tab.en + " tab", "釘住「" + entry.tab.yue + "」分頁");
      entry.pin.setAttribute("aria-label", pinLabel);
      entry.pin.setAttribute("title", pinLabel);
      strip.appendChild(entry.wrap); // appending an attached node moves it
    });

    if (restore) restore.focus();
    applyFilter();
  }

  function scrollTabIntoView(button) {
    if (strip.scrollWidth <= strip.clientWidth + 1) return;
    try {
      button.scrollIntoView({
        behavior: prefersReduced() ? "auto" : "smooth",
        inline: "nearest",
        block: "nearest",
      });
    } catch (error) {
      button.scrollIntoView(false);
    }
  }

  function syncHash(id) {
    try {
      history.replaceState(null, "", "#" + id);
    } catch (error) {
      /* A file:// document has an opaque origin and refuses replaceState; the
         tab still changed, so this is not worth failing the activation over. */
    }
  }

  function activate(id, options) {
    var entry = nodes[id];
    if (!entry) return false;
    var opts = options || {};
    activeId = id;

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

  // ---------------------------------------------------------------- keyboard
  function onTabKeyDown(event) {
    var id = event.currentTarget.getAttribute("data-tab");
    var key = event.key;

    if (key === "p" || key === "P") {
      event.preventDefault();
      togglePin(id);
      return;
    }

    var ids = visibleIds();
    if (!ids.length) return;
    var at = ids.indexOf(id);
    var next = null;
    if (key === "ArrowRight") next = ids[(at + 1) % ids.length];
    else if (key === "ArrowLeft") next = ids[(at - 1 + ids.length) % ids.length];
    else if (key === "Home") next = ids[0];
    else if (key === "End") next = ids[ids.length - 1];
    if (!next) return;

    event.preventDefault();
    // Focus stays on the strip here: moving it into the panel would end the very
    // roving navigation the arrow keys exist for. Enter, Space and a click do
    // move it, because those are deliberate activations.
    activate(next, { focusTab: true });
  }

  // ------------------------------------------------------------------ search
  function fallbackControl() {
    // Without regex-builder.js the field still has to filter, so fall back to the
    // plain-text matcher every search on this site defaults to anyway.
    return {
      state: function () {
        return { query: searchField.value, regex: false, flags: "i", valid: true, feedback: "", matcher: null };
      },
      matches: function (text) {
        try {
          return A.matcher(searchField.value, false, "i").test(text);
        } catch (error) {
          return false;
        }
      },
      refresh: applyFilter,
    };
  }

  function attachSearch() {
    searchField = document.getElementById("tab-search");
    if (!searchField) return;
    var openButton = document.getElementById("tab-regex-open");
    var panel = document.getElementById("tab-regex");

    if (A.regex && typeof A.regex.attach === "function") {
      searchControl = A.regex.attach({
        name: "tab",
        input: searchField,
        openButton: openButton,
        panel: panel,
        sample: "Home Features Docs Screenshots Guides Community Settings",
        onChange: applyFilter,
      });
      return;
    }
    searchControl = fallbackControl();
    searchField.addEventListener("input", applyFilter);
  }

  function readState() {
    try {
      if (searchControl && typeof searchControl.state === "function") {
        var state = searchControl.state() || {};
        return {
          query: state.query == null ? "" : String(state.query),
          valid: state.valid !== false,
          feedback: state.feedback ? String(state.feedback) : "",
        };
      }
    } catch (error) {
      /* a broken control must not take the strip down with it */
    }
    return { query: searchField ? searchField.value : "", valid: true, feedback: "" };
  }

  function matchesText(text) {
    if (!searchControl || typeof searchControl.matches !== "function") return false;
    try {
      return searchControl.matches(text) === true;
    } catch (error) {
      return false;
    }
  }

  function applyFilter() {
    if (!strip) return;
    var state = readState();
    var query = state.query;
    var matched = 0;
    var activeKept = false;

    live.forEach(function (tab) {
      var entry = nodes[tab.id];
      var hit = !query ? true : state.valid && matchesText(labelOf(tab) + " " + tab.id);
      if (query && hit) matched += 1;
      if (query && !hit && tab.id === activeId) activeKept = true;
      entry.wrap.hidden = !(hit || tab.id === activeId);
    });

    writeNote(state, matched, activeKept);
  }

  function writeNote(state, matched, activeKept) {
    if (!note) return;
    var query = state.query;
    if (!query) {
      note.textContent = "";
      return;
    }

    var suffix = "";
    if (activeKept && nodes[activeId]) {
      var open = nodes[activeId].tab;
      suffix = t(
        " The active tab (" + open.en + ") stays visible.",
        "（目前分頁「" + open.yue + "」照樣顯示。）"
      );
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
        ? "No tab matches “" + query + "”."
        : matched + (matched === 1 ? " tab matches “" : " tabs match “") + query + "”.";
    var cantonese =
      matched === 0 ? "冇分頁配到「" + query + "」。" : matched + " 個分頁配到「" + query + "」。";
    note.textContent = t(english, cantonese) + suffix;
  }

  // -------------------------------------------------------------- menu items
  function menuItems(id) {
    var tab = nodes[id].tab;
    var on = isPinned(id);
    return [
      {
        label: on
          ? t("Unpin the " + tab.en + " tab", "取消釘住「" + tab.yue + "」分頁")
          : t("Pin the " + tab.en + " tab", "釘住「" + tab.yue + "」分頁"),
        shortcut: "P",
        run: function () {
          togglePin(id);
        },
      },
      {
        label: t("Go to the " + tab.en + " tab", "去「" + tab.yue + "」分頁"),
        shortcut: "Enter",
        run: function () {
          activate(id, { focusPanel: true });
        },
      },
      {
        label: t("Copy link to this tab", "複製呢個分頁嘅連結"),
        run: function () {
          copyLink(id);
        },
      },
      {
        label: t("Reset tab order", "重設分頁次序"),
        run: resetOrder,
      },
    ];
  }

  // -------------------------------------------------------------------- init
  function idFromHash() {
    var raw = String(location.hash || "").replace(/^#/, "");
    return nodes[raw] ? raw : null;
  }

  function firstShownId() {
    for (var i = 0; i < live.length; i++) {
      var one = nodes[live[i].id];
      if (!one.panel.hasAttribute("hidden")) return live[i].id;
    }
    return live.length ? live[0].id : null;
  }

  A.ready(function () {
    strip = document.getElementById("tab-strip");
    if (!strip) return;
    note = document.getElementById("tab-note");

    buildNodes();
    if (!live.length) return;

    pinned = readPins();
    attachSearch();
    layout();

    A.showTab = function (id, options) {
      var opts = options || {};
      return activate(id, { focusPanel: opts.focusPanel !== false });
    };

    A.registerPaletteSource(function () {
      return orderedIds().map(function (id) {
        var tab = nodes[id].tab;
        return {
          kind: "Tab",
          title: labelOf(tab),
          subtitle:
            t("Tab · #" + id, "分頁 · #" + id) + (isPinned(id) ? t(" · pinned", " · 已釘住") : ""),
          run: function () {
            activate(id, { focusPanel: true });
          },
        };
      });
    });

    A.settings.onChange(function (key) {
      if (key === null || key === "language" || key === "emoji") layout();
    });

    window.addEventListener("hashchange", function () {
      var id = idFromHash();
      if (id && id !== activeId) activate(id, { focusPanel: true });
    });

    var pending = typeof A._pendingTab === "string" && nodes[A._pendingTab] ? A._pendingTab : null;
    var initial = idFromHash() || pending || firstShownId();
    // No focus move on load: the reader has not asked to go anywhere yet.
    activate(initial, { scroll: false });
  });
})();
