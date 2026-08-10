/* Notifications: the toast region, the persisted history, and the drawer.
 *
 * site-core.js queues anything raised before this file loads, so the first job
 * here is draining that queue -- a message lost in the gap between two scripts
 * is a message the user never had the chance to read.
 *
 * An entry keeps the exact words that were shown when it was raised. History is
 * a record of what happened, so a later language change never rewrites it.
 */
(function () {
  "use strict";

  var site = window.AmuletSite;
  if (!site) return;

  var el = site.el;
  var lang = site.lang;
  var settings = site.settings;

  var STORE_KEY = "notifications";
  var MAX_ENTRIES = 200; // bounded so a long-lived profile cannot grow without end
  var MAX_TOASTS = 8;
  var TOAST_MS = 5000;
  var ARM_MS = 12000;

  var TONES = { info: 1, success: 1, warning: 1, error: 1 };
  var GLYPHS = { info: "ℹ️", success: "✅", warning: "⚠️", error: "⛔" };

  var entries = [];
  var seq = 0;
  var pendingToasts = [];
  var toastTimers = [];
  var regexControl = null;
  var armed = null;
  var armTimer = 0;

  // ------------------------------------------------------------------ store
  function load() {
    var saved = site.store.get(STORE_KEY, null);
    if (!Array.isArray(saved)) return null;
    var clean = [];
    saved.forEach(function (row) {
      if (!row || typeof row !== "object") return;
      var at = Number(row.at);
      clean.push({
        id: String(row.id || nextId()),
        at: isFinite(at) ? at : Date.now(),
        title: String(row.title == null ? "" : row.title),
        body: String(row.body == null ? "" : row.body),
        tone: TONES[row.tone] ? row.tone : "info",
      });
    });
    return clean;
  }

  function persist() {
    site.store.set(STORE_KEY, entries);
  }

  function nextId() {
    seq += 1;
    return "n" + Date.now().toString(36) + "-" + seq;
  }

  function seed() {
    var now = Date.now();
    return [
      {
        id: nextId(),
        at: now,
        tone: "info",
        title: lang.t("Site preferences loaded", "網站設定已載入"),
        body: lang.t(
          "Stored in this browser only. Reset restores every shipped value.",
          "只存喺呢個瀏覽器。重設會還原返每一個出廠值。"
        ),
      },
      {
        id: nextId(),
        at: now - 1000,
        tone: "success",
        title: lang.t("Release manifest verified", "發佈清單已驗證"),
        body: lang.t(
          "0.10.0-dev.414 assets target f95695f7cbadecd3272370a1fa694e9b601ab124.",
          "0.10.0-dev.414 資產對應 f95695f7cbadecd3272370a1fa694e9b601ab124。"
        ),
      },
      {
        id: nextId(),
        at: now - 2000,
        tone: "warning",
        title: lang.t("Update channel", "更新通道"),
        body: lang.t(
          "Unsigned Squirrel packages are expected. Signing is permanently prohibited.",
          "未簽署嘅 Squirrel 套件係預期之內。簽署已經永久禁止。"
        ),
      },
    ];
  }

  var restored = load();
  if (restored === null) {
    entries = seed();
    persist();
  } else {
    entries = restored;
  }

  // ------------------------------------------------------------------ time
  function timeLabel(at) {
    var date = new Date(at);
    if (isNaN(date.getTime())) return "--:--";
    return date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  }

  function exactLabel(at) {
    var date = new Date(at);
    return isNaN(date.getTime()) ? null : date.toLocaleString();
  }

  function isoLabel(at) {
    var date = new Date(at);
    try {
      return isNaN(date.getTime()) ? null : date.toISOString();
    } catch (error) {
      return null;
    }
  }

  // --------------------------------------------------------------- motion
  function reducedMotion() {
    if (settings.get("reducedMotion") === true) return true;
    try {
      return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    } catch (error) {
      return false;
    }
  }

  // -------------------------------------------------------------- narrator
  var speech = { active: false, pending: null };

  function speechLang() {
    return lang.mode() === "cantonese" ? "zh-HK" : "en-US";
  }

  function utter(text) {
    var synth = window.speechSynthesis;
    if (!synth || typeof window.SpeechSynthesisUtterance !== "function") return;
    var line = new window.SpeechSynthesisUtterance(text);
    line.lang = speechLang();
    speech.active = true;
    line.onend = line.onerror = function () {
      speech.active = false;
      var next = speech.pending;
      speech.pending = null;
      if (next) utter(next);
    };
    try {
      synth.speak(line);
    } catch (error) {
      speech.active = false;
    }
  }

  /** One line at a time: a newer line replaces a waiting one instead of stacking. */
  function speak(text) {
    if (settings.get("narrator") !== true) return;
    var synth = window.speechSynthesis;
    if (!synth || typeof window.SpeechSynthesisUtterance !== "function") return;
    if (speech.active || synth.speaking) {
      speech.pending = text;
      return;
    }
    utter(text);
  }

  function stopSpeaking() {
    speech.pending = null;
    speech.active = false;
    try {
      if (window.speechSynthesis) window.speechSynthesis.cancel();
    } catch (error) {
      /* a browser refusing to cancel is not a reason to stop rendering */
    }
  }

  // ---------------------------------------------------------------- toasts
  function removeToast(node) {
    if (!node || !node.parentNode) return;
    for (var i = toastTimers.length - 1; i >= 0; i--) {
      if (toastTimers[i].node === node) {
        clearTimeout(toastTimers[i].timer);
        toastTimers.splice(i, 1);
      }
    }
    if (reducedMotion()) {
      node.parentNode.removeChild(node);
      return;
    }
    node.classList.add("toast-leaving");
    setTimeout(function () {
      if (node.parentNode) node.parentNode.removeChild(node);
    }, 180);
  }

  /** Keep the stack readable without ever silently dropping a warning or error. */
  function trimToasts(region) {
    var nodes = Array.prototype.slice.call(region.children).filter(function (node) {
      return !node.classList.contains("toast-leaving");
    });
    while (nodes.length > MAX_TOASTS) {
      var oldest = null;
      for (var i = 0; i < nodes.length; i++) {
        if (nodes[i].getAttribute("data-transient") === "true") {
          oldest = nodes[i];
          break;
        }
      }
      if (!oldest) oldest = nodes[0];
      removeToast(oldest);
      nodes.splice(nodes.indexOf(oldest), 1);
    }
  }

  function toast(message, tone) {
    var text = String(message == null ? "" : message);
    if (!text) return null;
    var kind = TONES[tone] ? tone : "info";
    var region = document.getElementById("toast-region");
    if (!region) {
      pendingToasts.push([text, kind]);
      return null;
    }

    var transient = kind === "info" || kind === "success";
    var glyph = lang.emoji(GLYPHS[kind]).trim();
    var node = el(
      "div",
      { class: "toast toast-" + kind, "data-tone": kind, "data-transient": String(transient) },
      glyph ? el("span", { class: "toast-glyph", "aria-hidden": "true", text: glyph }) : null,
      el("p", { class: "toast-message", text: text }),
      el("button", {
        class: "icon-button toast-dismiss",
        type: "button",
        text: "×",
        "aria-label": lang.t("Dismiss this message", "關閉呢個訊息"),
        onclick: function () {
          removeToast(node);
        },
      })
    );

    region.appendChild(node);
    if (!reducedMotion()) {
      node.classList.add("toast-entering");
      requestAnimationFrame(function () {
        node.classList.remove("toast-entering");
      });
    }
    if (transient) {
      toastTimers.push({
        node: node,
        timer: setTimeout(function () {
          removeToast(node);
        }, TOAST_MS),
      });
    }
    trimToasts(region);
    return node;
  }

  function flushToasts() {
    var queued = pendingToasts.slice();
    pendingToasts.length = 0;
    queued.forEach(function (row) {
      toast(row[0], row[1]);
    });
  }

  // -------------------------------------------------------------- history
  function notify(title, body, tone) {
    var entry = {
      id: nextId(),
      at: Date.now(),
      tone: TONES[tone] ? tone : "info",
      title: String(title == null ? "" : title),
      body: String(body == null ? "" : body),
    };
    entries.unshift(entry);
    if (entries.length > MAX_ENTRIES) entries.length = MAX_ENTRIES;
    persist();
    render();
    toast(entry.body ? entry.title + " — " + entry.body : entry.title, entry.tone);
    speak(entry.body ? entry.title + ". " + entry.body : entry.title);
    return entry;
  }

  site.notify = notify;
  site.toast = toast;

  var queued = Array.isArray(site._queued) ? site._queued.slice() : [];
  site._queued = [];
  queued.forEach(function (row) {
    if (row) notify(row.title, row.body, row.tone);
  });

  // ---------------------------------------------------------------- filter
  function haystack(entry) {
    return timeLabel(entry.at) + " " + entry.title + " " + entry.body;
  }

  function filterState() {
    if (regexControl) return regexControl.state();
    var input = document.getElementById("notif-search");
    return { query: input ? input.value : "", regex: false, flags: "i", valid: true, feedback: "" };
  }

  function fallbackMatcher() {
    var input = document.getElementById("notif-search");
    try {
      return site.matcher(input ? input.value : "", false, "i");
    } catch (error) {
      return null;
    }
  }

  function visible() {
    if (regexControl) {
      return entries.filter(function (entry) {
        return regexControl.matches(haystack(entry));
      });
    }
    var pattern = fallbackMatcher();
    if (!pattern) return [];
    return entries.filter(function (entry) {
      pattern.lastIndex = 0;
      return pattern.test(haystack(entry));
    });
  }

  // ---------------------------------------------------------------- render
  function updateBadge() {
    var count = document.getElementById("notif-count");
    if (count) count.textContent = String(entries.length);
    var bell = document.getElementById("notif-open");
    if (bell) {
      // The button carries an aria-label, so the visible badge is invisible to
      // assistive technology unless the label itself states the count.
      bell.setAttribute(
        "aria-label",
        lang.t(
          "Notification history, " + entries.length + " recorded",
          "通知記錄，共 " + entries.length + " 條"
        )
      );
    }
  }

  function emptyMessage(state, count) {
    if (!state.valid) {
      return lang.t(
        "That pattern is not valid, so no row is shown: " + (state.feedback || "invalid pattern"),
        "呢個 pattern 無效，所以唔顯示任何記錄：" + (state.feedback || "invalid pattern")
      );
    }
    if (!entries.length) {
      return lang.t(
        "No notification recorded yet. Every message is local to this browser.",
        "仲未有任何通知。所有訊息只存喺呢個瀏覽器。"
      );
    }
    var counted = lang.t(
      site.describe(count, "notification", state.query),
      state.query ? "冇通知符合“" + state.query + "”。" : count + " 條通知"
    );
    return (
      counted + " " + lang.t("Every message is local to this browser.", "所有訊息只存喺呢個瀏覽器。")
    );
  }

  function dismissOne(id) {
    var index = -1;
    entries.forEach(function (entry, i) {
      if (entry.id === id) index = i;
    });
    if (index < 0) return;
    var title = entries[index].title;
    entries.splice(index, 1);
    persist();
    render();
    var rows = document.querySelectorAll("#notif-list .notif-row-dismiss");
    var next = rows[Math.min(index, rows.length - 1)];
    if (next) next.focus();
    else {
      var search = document.getElementById("notif-search");
      if (search) search.focus();
    }
    toast(
      lang.t("Dismissed 1 message: " + title, "已清除 1 條訊息：" + title),
      "info"
    );
  }

  function row(entry) {
    return el(
      "article",
      { class: "notif-row", role: "listitem", "data-id": entry.id, "data-tone": entry.tone },
      el(
        "div",
        { class: "notif-row-head" },
        el("strong", { class: "notif-row-title", text: entry.title }),
        el("time", {
          class: "notif-row-time",
          datetime: isoLabel(entry.at),
          title: exactLabel(entry.at),
          text: timeLabel(entry.at),
        })
      ),
      entry.body ? el("p", { class: "notif-row-body", text: entry.body }) : null,
      el("button", {
        class: "icon-button notif-row-dismiss",
        type: "button",
        text: "×",
        "aria-label": lang.t("Dismiss " + entry.title, "清除 " + entry.title),
        onclick: function () {
          dismissOne(entry.id);
        },
      })
    );
  }

  function render() {
    updateBadge();
    var list = document.getElementById("notif-list");
    if (!list) return;
    list.setAttribute("role", "list");
    list.setAttribute("aria-label", lang.t("Recorded notifications", "已記錄嘅通知"));
    var state = filterState();
    var rows = visible();
    list.replaceChildren.apply(
      list,
      rows.map(function (entry) {
        return row(entry);
      })
    );
    var empty = document.getElementById("notif-empty");
    if (empty) {
      empty.hidden = rows.length !== 0;
      if (rows.length === 0) empty.textContent = emptyMessage(state, 0);
    }
    if (armed && armed.count !== rows.length) disarm("stale");
  }

  // ------------------------------------------------------- dismiss visible
  function confirmBar() {
    return document.querySelector("#notifications .notif-confirm");
  }

  function disarm(reason) {
    if (!armed) return;
    var count = armed.count;
    armed = null;
    clearTimeout(armTimer);
    var bar = confirmBar();
    if (bar) bar.hidden = true;
    var button = document.getElementById("notif-dismiss");
    if (button) button.disabled = false;
    if (reason === "cancel") {
      if (button) button.focus();
      toast(
        lang.t(
          "Nothing was dismissed. " + count + " messages are still here.",
          "乜都冇清除。" + count + " 條訊息仲喺度。"
        ),
        "info"
      );
    } else if (reason === "stale") {
      toast(
        lang.t(
          "The visible list changed, so nothing was dismissed.",
          "顯示中嘅清單變咗，所以乜都冇清除。"
        ),
        "info"
      );
    }
  }

  function applyDismiss(rows, query) {
    var doomed = {};
    rows.forEach(function (entry) {
      doomed[entry.id] = true;
    });
    var before = entries.length;
    entries = entries.filter(function (entry) {
      return !doomed[entry.id];
    });
    persist();
    render();
    var removed = before - entries.length;
    toast(
      lang.t(
        "Dismissed " + removed + " of " + before + " messages" + (query ? " matching “" + query + "”." : "."),
        "已清除 " + before + " 條之中嘅 " + removed + " 條" + (query ? "（符合“" + query + "”）。" : "。")
      ),
      "info"
    );
    var button = document.getElementById("notif-dismiss");
    if (button) button.focus();
  }

  function arm(rows, query) {
    var bar = confirmBar();
    if (!bar) {
      // Losing many messages at once without a confirmation is the one outcome
      // this gate exists to prevent, so a missing gate refuses the whole action.
      toast(
        lang.t(
          "The confirmation step is unavailable, so " + rows.length + " messages were kept.",
          "確認步驟用唔到，所以 " + rows.length + " 條訊息全部保留。"
        ),
        "error"
      );
      return;
    }
    armed = { rows: rows, query: query, count: rows.length };
    var yes = bar.querySelector(".notif-confirm-yes");
    if (yes) {
      yes.textContent = lang.t("Dismiss " + rows.length, "清除 " + rows.length + " 條");
    }
    // The bar is revealed before its wording is written: an alert announces a
    // content change inside a rendered region, not one made while it was hidden.
    bar.hidden = false;
    var text = bar.querySelector(".notif-confirm-text");
    if (text) {
      text.textContent = lang.t(
        "Dismiss " + rows.length + " visible messages? Dismissal is permanent and cannot be undone.",
        "清除顯示中嘅 " + rows.length + " 條訊息？清除咗就冇得返轉頭。"
      );
    }
    var button = document.getElementById("notif-dismiss");
    if (button) button.disabled = true;
    if (yes) yes.focus();
    clearTimeout(armTimer);
    armTimer = setTimeout(function () {
      disarm("cancel");
    }, ARM_MS);
  }

  function dismissVisible() {
    if (armed) return;
    var state = filterState();
    var rows = visible();
    if (!rows.length) {
      toast(
        lang.t(
          "Nothing matches that filter, so nothing was dismissed. " + entries.length + " messages are still here.",
          "冇訊息符合篩選，所以乜都冇清除。仲有 " + entries.length + " 條。"
        ),
        "warning"
      );
      return;
    }
    if (rows.length === 1) {
      applyDismiss(rows, state.query);
      return;
    }
    arm(rows, state.query);
  }

  // ---------------------------------------------------------------- export
  function rangeSentence(rows, state) {
    var oldest = rows[rows.length - 1];
    var newest = rows[0];
    var span = timeLabel(oldest.at) + " – " + timeLabel(newest.at);
    var scope = rows.length + " of " + entries.length;
    var filter = state.query
      ? "“" + state.query + "” (" + (state.regex ? "regex, flags " + (state.flags || "i") : "plain text") + ")"
      : null;
    return lang.t(
      scope + " recorded messages · " + span + " · filter: " + (filter || "none"),
      scope + " 條記錄 · " + span + " · 篩選：" + (filter || "無")
    );
  }

  function markdown(rows, state) {
    var lines = [];
    lines.push("# " + lang.t("Notification history", "通知記錄"));
    lines.push("");
    lines.push(rangeSentence(rows, state));
    lines.push("");
    rows.forEach(function (entry) {
      var body = entry.body.replace(/\s*\n\s*/g, " ");
      lines.push("- **" + timeLabel(entry.at) + " · " + entry.title + "**" + (body ? " — " + body : ""));
    });
    return lines.join("\n") + "\n";
  }

  /** Older browsers and file:// previews can refuse the async clipboard. */
  function legacyCopy(text) {
    var returnTo = document.activeElement;
    var field = el("textarea", { tabindex: "-1", readonly: true, "aria-label": lang.t("Markdown export", "Markdown 匯出") });
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

  function reportCopied(rows, state) {
    toast(
      lang.t(
        "Copied " + rangeSentence(rows, state) + " as Markdown.",
        "已複製成 Markdown：" + rangeSentence(rows, state)
      ),
      "success"
    );
  }

  function reportRefused(reason) {
    toast(
      lang.t(
        "The clipboard refused the copy, so nothing was copied: " + reason,
        "剪貼板拒絕咗複製，所以乜都冇複製到：" + reason
      ),
      "error"
    );
  }

  function exportVisible() {
    var state = filterState();
    var rows = visible();
    if (!rows.length) {
      toast(
        lang.t(
          "Nothing matches that filter, so there was nothing to export.",
          "冇訊息符合篩選，所以冇嘢可以匯出。"
        ),
        "warning"
      );
      return;
    }
    var text = markdown(rows, state);
    var clipboard = navigator.clipboard;
    if (clipboard && typeof clipboard.writeText === "function") {
      clipboard.writeText(text).then(
        function () {
          reportCopied(rows, state);
        },
        function (error) {
          if (legacyCopy(text)) reportCopied(rows, state);
          else reportRefused(String((error && error.message) || error || "permission denied"));
        }
      );
      return;
    }
    if (legacyCopy(text)) reportCopied(rows, state);
    else reportRefused("this browser exposes no clipboard write");
  }

  // ---------------------------------------------------------------- drawer
  function drawerEl() {
    return document.getElementById("notifications");
  }

  function isOpen() {
    var drawer = drawerEl();
    return !!drawer && !drawer.hidden;
  }

  function openDrawer() {
    var drawer = drawerEl();
    if (!drawer) return;
    drawer.hidden = false;
    drawer.classList.add("is-open");
    var bell = document.getElementById("notif-open");
    if (bell) bell.setAttribute("aria-expanded", "true");
    render();
    var search = document.getElementById("notif-search");
    if (search) search.focus();
    else drawer.focus();
  }

  function closeDrawer() {
    var drawer = drawerEl();
    if (!drawer) return;
    disarm(null);
    drawer.hidden = true;
    drawer.classList.remove("is-open");
    var bell = document.getElementById("notif-open");
    if (bell) {
      bell.setAttribute("aria-expanded", "false");
      bell.focus();
    }
  }

  function toggleDrawer() {
    if (isOpen()) closeDrawer();
    else openDrawer();
  }

  // ------------------------------------------------------------------ boot
  function localizeChrome() {
    var dismiss = document.getElementById("notif-dismiss");
    if (dismiss) dismiss.textContent = lang.t("Dismiss visible", "清除顯示中");
    var exportButton = document.getElementById("notif-export");
    if (exportButton) exportButton.textContent = lang.t("Export as Markdown", "匯出成 Markdown");
    var close = document.getElementById("notif-close");
    if (close) close.setAttribute("aria-label", lang.t("Close notifications", "關閉通知"));
    var title = document.getElementById("notif-title");
    if (title) title.textContent = lang.t("Notification history", "通知記錄");
    var search = document.getElementById("notif-search");
    if (search) {
      var label = lang.t("Search notifications", "搜尋通知");
      search.setAttribute("aria-label", label);
      search.setAttribute("placeholder", label);
    }
    var bar = confirmBar();
    if (bar) {
      var no = bar.querySelector(".notif-confirm-no");
      if (no) no.textContent = lang.t("Keep them", "保留");
    }
  }

  function buildConfirmBar(actions) {
    var bar = el(
      "div",
      { class: "notif-confirm", role: "alert", hidden: true },
      el("p", { class: "notif-confirm-text" }),
      el("button", {
        class: "button button-filled notif-confirm-yes",
        type: "button",
        onclick: function () {
          if (!armed) return;
          var rows = armed.rows;
          var query = armed.query;
          armed = null;
          clearTimeout(armTimer);
          var node = confirmBar();
          if (node) node.hidden = true;
          var button = document.getElementById("notif-dismiss");
          if (button) button.disabled = false;
          applyDismiss(rows, query);
        },
      }),
      el("button", {
        class: "button button-text notif-confirm-no",
        type: "button",
        onclick: function () {
          disarm("cancel");
        },
      })
    );
    actions.parentNode.insertBefore(bar, actions.nextSibling);
    return bar;
  }

  function attachRegex() {
    var input = document.getElementById("notif-search");
    var openButton = document.getElementById("notif-regex-open");
    var panel = document.getElementById("notif-regex");
    if (!input) return;
    if (!site.regex || typeof site.regex.attach !== "function") {
      // Without the shared builder there is no working regex surface, so the
      // control that would open one is removed rather than left inert.
      if (openButton) openButton.hidden = true;
      if (panel) panel.hidden = true;
      input.addEventListener("input", render);
      return;
    }
    regexControl = site.regex.attach({
      name: "notif",
      input: input,
      openButton: openButton,
      panel: panel,
      sample: "14:22 Release manifest verified 0.10.0-dev.414 assets target f95695f7cbadecd3272370a1fa694e9b601ab124",
      onChange: function () {
        render();
      },
    });
    // The builder falls back to plain-text containment when its own controls are
    // missing, and that fallback listens to nothing -- so typing needs a reader.
    if (!document.querySelector('[data-regex-controls="notif"]')) {
      input.addEventListener("input", render);
    }
  }

  function boot() {
    var drawer = drawerEl();
    if (drawer) {
      drawer.setAttribute("role", "dialog");
      drawer.setAttribute("aria-modal", "false");
      drawer.setAttribute("tabindex", "-1");
    }
    var bell = document.getElementById("notif-open");
    if (bell) bell.addEventListener("click", toggleDrawer);
    var close = document.getElementById("notif-close");
    if (close) close.addEventListener("click", closeDrawer);

    var actions = document.querySelector("#notifications .drawer-actions");
    if (actions) buildConfirmBar(actions);

    var dismiss = document.getElementById("notif-dismiss");
    if (dismiss) dismiss.addEventListener("click", dismissVisible);
    var exportButton = document.getElementById("notif-export");
    if (exportButton) exportButton.addEventListener("click", exportVisible);

    attachRegex();
    localizeChrome();

    document.addEventListener("keydown", function (event) {
      if (event.key !== "Escape" || !isOpen()) return;
      var palette = document.getElementById("command-palette");
      if (palette && palette.open) return; // the palette dialog owns its own Escape
      event.preventDefault();
      if (armed) disarm("cancel");
      else closeDrawer();
    });

    settings.onChange(function (key) {
      if (key === "narrator" && settings.get("narrator") !== true) stopSpeaking();
      // The builder re-grades its feedback text on a funny-level change, and the
      // empty state quotes that text, so it has to be repainted with it.
      if (
        key === null ||
        key === "language" ||
        key === "emoji" ||
        key === "narrator" ||
        key === "funnyEn" ||
        key === "funnyYue"
      ) {
        localizeChrome();
        render();
      }
    });

    flushToasts();
    render();
  }

  site.ready(boot);

  // --------------------------------------------------------------- palette
  site.registerPaletteSource(function () {
    var matching = visible().length;
    var scope = matching + " of " + entries.length + " recorded";
    function command(id, title, detail, run) {
      // The palette is assembled from several modules, so each result carries
      // both naming conventions rather than betting on one.
      return {
        id: "notifications:" + id,
        kind: "command",
        section: lang.t("Notifications", "通知"),
        title: title,
        label: title,
        detail: detail,
        hint: detail,
        run: run,
        action: run,
      };
    }
    return [
      command(
        "open",
        lang.t("Open notification history", "開啟通知記錄"),
        lang.t(scope + " messages match the current filter.", scope + " 條訊息符合而家嘅篩選。"),
        function () {
          openDrawer();
        }
      ),
      command(
        "dismiss-visible",
        lang.t("Dismiss visible notifications", "清除顯示中嘅通知"),
        lang.t(
          "Permanent. " + matching + " messages match the current filter.",
          "冇得復原。" + matching + " 條訊息符合而家嘅篩選。"
        ),
        function () {
          openDrawer();
          dismissVisible();
        }
      ),
      command(
        "export-markdown",
        lang.t("Export notifications as Markdown", "將通知匯出成 Markdown"),
        lang.t(
          "Copies " + matching + " visible messages to the clipboard.",
          "將顯示中嘅 " + matching + " 條訊息複製到剪貼板。"
        ),
        function () {
          openDrawer();
          exportVisible();
        }
      ),
    ];
  });
})();
