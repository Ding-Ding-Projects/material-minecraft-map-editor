/* Multi-select and bulk operations for every list, grid and collection here.
 *
 * Selecting one row and repeating an action forty times is the site failing to
 * do its job, so every collection gets the same bar: real checkboxes, click and
 * shift-click ranges, a keyboard path that reaches all of it, and a select-all
 * that says out loud which of the two possible scopes it means.
 *
 * Three rules shape the rest of this file.
 *
 *   - Nothing runs before it has been described. Every action arms first and
 *     paints the exact count, the items it will touch, and the ones it will
 *     skip with the reason for each. Destructive actions arm into a second,
 *     louder gate; the rest arm into a plain review.
 *   - Nothing is claimed that was not observed. A run reports what actually
 *     happened -- including a cancellation half way through, a clipboard that
 *     refused, and a row that vanished while the batch was in flight.
 *   - Nothing is invented. A collection whose contents this page cannot change
 *     is given copy and export actions only; it does not get a delete button
 *     drawn on it so the bar looks symmetrical.
 *
 * The lists are wired at the bottom. Several of them are rendered by scripts
 * that rebuild their nodes on a language change, so every instance re-indexes
 * from a MutationObserver rather than trusting the nodes it saw at boot.
 */
(function () {
  "use strict";

  var site = window.AmuletSite;
  if (!site) return;

  var el = site.el;
  var lang = site.lang;
  var settings = site.settings;

  var ARM_MS = 15000;
  var DEFAULT_CHUNK = 25;
  var ANNOUNCE_MS = 500;
  var STORE_PREFIX = "bulk.open.";

  // Anything a click on the item body must be allowed to reach unchanged. A
  // card carrying a link and a selection checkbox has to keep the link.
  var INTERACTIVE =
    "a[href], button, input, select, textarea, label, summary, [role='button'], [role='link'], [contenteditable='true']";

  var instances = [];
  var seq = 0;

  // ------------------------------------------------------------------- copy
  function t(en, yue) {
    return lang.t(en, yue);
  }

  function level(list, value) {
    if (typeof list === "string") return list;
    var index = value <= 1 ? 0 : value <= 3 ? 1 : 2;
    return list[index] || list[list.length - 1] || "";
  }

  /* Voice only. Every count, key, reason and identifier in this file is passed
   * in already rendered, so no funny level can reach a fact. */
  function graded(en, yue) {
    return t(level(en, lang.funny("en")), level(yue, lang.funny("yue")));
  }

  function fill(template, values) {
    var out = String(template);
    for (var i = 0; i < values.length; i++) {
      out = out.split("{" + i + "}").join(String(values[i]));
    }
    return out;
  }

  function textOf(node) {
    if (!node) return "";
    return String(node.textContent || "").replace(/\s+/g, " ").trim();
  }

  function clip(value, max) {
    var raw = String(value == null ? "" : value).replace(/\s+/g, " ").trim();
    return raw.length > max ? raw.slice(0, max - 1) + "…" : raw;
  }

  function reducedMotion() {
    if (settings.get("reducedMotion") === true) return true;
    try {
      return !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
    } catch (error) {
      return false;
    }
  }

  function nowIso() {
    try {
      return new Date().toISOString();
    } catch (error) {
      return String(Date.now());
    }
  }

  // ------------------------------------------------------------------ style
  var STYLE_ID = "bulk-actions-style";
  var CSS = [
    ".bulk-bar{display:grid;gap:10px;margin:0 0 16px;padding:12px 14px;border:1px solid var(--outline-variant);border-radius:var(--r-md,16px);background:var(--surface-container);}",
    ".bulk-bar[hidden]{display:none}",
    ".bulk-head{display:flex;align-items:center;gap:10px;flex-wrap:wrap}",
    ".bulk-head h2{margin:0;font-size:.86rem;font-weight:700;letter-spacing:.02em}",
    ".bulk-body{display:grid;gap:10px}",
    ".bulk-body[hidden]{display:none}",
    ".bulk-line{display:flex;gap:8px;flex-wrap:wrap;align-items:center}",
    ".bulk-bar .button{min-height:40px;padding:0 14px;font-size:.82rem}",
    ".bulk-bar .button.bulk-disclose{min-height:32px;padding:0 10px;font-size:.78rem}",
    ".bulk-status{margin:0;font-size:.8rem;color:var(--secondary);font-variant-numeric:tabular-nums}",
    ".bulk-hint{margin:0;font-size:.76rem;color:var(--secondary)}",
    ".bulk-panel{display:grid;gap:8px;padding:10px 12px;border:1px solid var(--outline-variant);border-radius:var(--r-sm,12px);background:var(--surface-bright)}",
    ".bulk-panel[hidden]{display:none}",
    '.bulk-panel[data-destructive="true"]{border-width:2px;border-color:#8c1d18}',
    ".bulk-panel p{margin:0;font-size:.82rem}",
    ".bulk-panel h3{margin:0;font-size:.82rem;font-weight:700}",
    ".bulk-list{margin:0;padding-inline-start:1.15rem;max-height:10rem;overflow:auto;font-size:.78rem;color:var(--on-surface-variant)}",
    ".bulk-list li{margin:2px 0}",
    ".bulk-track{height:6px;border-radius:999px;background:var(--outline-variant);overflow:hidden}",
    ".bulk-fill{display:block;height:100%;width:0;background:var(--primary);transition:width var(--motion-fast,130ms) var(--ease,linear)}",
    ':root[data-reduced-motion="true"] .bulk-fill{transition:none}',
    "@media (prefers-reduced-motion: reduce){.bulk-fill{transition:none}}",
    ".bulk-check-wrap{display:flex;align-items:center;gap:8px;min-height:22px}",
    ".bulk-check{width:20px;height:20px;min-height:0;min-width:20px;margin:0;accent-color:var(--primary);cursor:pointer}",
    '[data-bulk-collapsed="true"] .bulk-check-wrap{display:none}',
    ".bulk-selected{outline:2px solid var(--primary);outline-offset:3px;border-radius:var(--r-sm,12px)}",
    ".bulk-bar :focus-visible,.bulk-check:focus-visible{outline:3px solid var(--primary);outline-offset:2px}",
    ".bulk-bar [disabled]{opacity:.62;cursor:not-allowed}",
    ".bulk-sr{position:absolute;width:1px;height:1px;margin:-1px;padding:0;border:0;clip:rect(0 0 0 0);clip-path:inset(50%);overflow:hidden;white-space:nowrap}",
    '.bulk-note[data-state="error"]{color:#8c1d18;font-weight:700}',
    '.dark .bulk-note[data-state="error"],html[data-theme="dark"] .bulk-note[data-state="error"]{color:#ffb4ab}',
  ].join("");

  function installStyle() {
    if (document.getElementById(STYLE_ID)) return;
    var style = el("style", { id: STYLE_ID });
    style.textContent = CSS;
    (document.head || document.documentElement).appendChild(style);
  }

  // -------------------------------------------------------------- clipboard
  /** Older browsers and file:// previews can refuse the async clipboard. */
  function legacyCopy(value) {
    var returnTo = document.activeElement;
    var field = el("textarea", {
      tabindex: "-1",
      readonly: true,
      "aria-hidden": "true",
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

  function copyText(value, onDone) {
    var clipboard = navigator.clipboard;
    if (clipboard && typeof clipboard.writeText === "function") {
      clipboard.writeText(value).then(
        function () {
          onDone(true, "");
        },
        function (error) {
          if (legacyCopy(value)) onDone(true, "");
          else onDone(false, String((error && error.message) || error || "permission denied"));
        }
      );
      return;
    }
    if (legacyCopy(value)) onDone(true, "");
    else onDone(false, "this browser exposes no clipboard write");
  }

  // ----------------------------------------------------------------- format
  function columnsOf(rows) {
    var names = ["Item"];
    rows.forEach(function (row) {
      Object.keys(row.fields || {}).forEach(function (name) {
        if (names.indexOf(name) === -1) names.push(name);
      });
    });
    return names;
  }

  function cellOf(row, name) {
    if (name === "Item") return row.label;
    var value = (row.fields || {})[name];
    return value == null ? "" : String(value).replace(/\s+/g, " ").trim();
  }

  function markdown(inst, rows, scope) {
    var names = columnsOf(rows);
    var lines = ["# " + inst.title(), "", scope, ""];
    lines.push("| " + names.join(" | ") + " |");
    lines.push("| " + names.map(function () { return "---"; }).join(" | ") + " |");
    rows.forEach(function (row) {
      lines.push(
        "| " +
          names
            .map(function (name) {
              return cellOf(row, name).split("|").join("\\|");
            })
            .join(" | ") +
          " |"
      );
    });
    return lines.join("\n") + "\n";
  }

  function csvCell(value) {
    var raw = String(value == null ? "" : value);
    return /[",\n\r]/.test(raw) ? '"' + raw.split('"').join('""') + '"' : raw;
  }

  function csv(inst, rows, scope) {
    var names = columnsOf(rows);
    var lines = ["# " + csvCell(scope).replace(/^"|"$/g, "")];
    lines.push(names.map(csvCell).join(","));
    rows.forEach(function (row) {
      lines.push(
        names
          .map(function (name) {
            return csvCell(cellOf(row, name));
          })
          .join(",")
      );
    });
    return lines.join("\n") + "\n";
  }

  function json(inst, rows, scope, state) {
    return (
      JSON.stringify(
        {
          list: inst.id,
          title: inst.title(),
          generated: nowIso(),
          scope: scope,
          filter: state.query
            ? { query: state.query, mode: state.regex ? "regex" : "plain-text", flags: state.regex ? state.flags : null }
            : null,
          count: rows.length,
          items: rows.map(function (row) {
            return { key: row.key, label: row.label, fields: row.fields || {} };
          }),
        },
        null,
        2
      ) + "\n"
    );
  }

  // ------------------------------------------------------------ filter read
  /* The search state is read from the real controls rather than from a copy of
   * it, so an export can never describe a filter the page is not applying. */
  function filterState(inst) {
    var config = inst.search;
    if (!config) return { query: "", regex: false, flags: "" };
    var input = document.getElementById(config.input);
    var toggle = document.getElementById("regex-" + config.name + "-toggle");
    var flags = document.getElementById("regex-" + config.name + "-flags");
    return {
      query: input ? String(input.value || "") : "",
      regex: !!(toggle && toggle.checked),
      flags: flags ? String(flags.value) : "i",
    };
  }

  function filterSentence(inst) {
    var state = filterState(inst);
    if (!state.query) return t("filter: none", "篩選：無");
    var mode = state.regex
      ? t("regex, flags " + (state.flags || "(none)"), "regex，flags " + (state.flags || "（無）"))
      : t("plain text", "純文字");
    return t('filter: "' + state.query + '" (' + mode + ")", "篩選：“" + state.query + "”（" + mode + "）");
  }

  function scopeSentence(inst, rows) {
    return (
      t(
        rows.length + " of " + inst.items.length + " items in " + inst.title(),
        inst.title() + " 入面 " + inst.items.length + " 項之中嘅 " + rows.length + " 項"
      ) +
      " · " +
      filterSentence(inst) +
      " · " +
      t("UTF-8, LF line endings", "UTF-8、LF 換行") +
      " · " +
      nowIso()
    );
  }

  // ------------------------------------------------------------- item state
  function isShown(node, container) {
    var walk = node;
    while (walk && walk !== container) {
      if (walk.hidden) return false;
      if (walk.getAttribute && walk.getAttribute("aria-hidden") === "true") return false;
      walk = walk.parentNode;
    }
    return !container.hidden;
  }

  function ignored(node) {
    if (!node || node.nodeType !== 1) return true;
    if (node.classList.contains("bulk-bar")) return true;
    if (node.classList.contains("empty-state")) return true;
    if (node.hasAttribute("data-bulk-ignore")) return true;
    var role = node.getAttribute("role");
    return role === "status" || role === "alert";
  }

  function resolveSelector(inst) {
    var candidates = inst.itemSelector;
    if (typeof candidates === "string") return candidates;
    for (var i = 0; i < candidates.length; i++) {
      try {
        if (inst.container.querySelector(candidates[i])) return candidates[i];
      } catch (error) {
        /* a candidate this browser cannot parse is simply not the one */
      }
    }
    return null;
  }

  function fallbackDescribe(node, index) {
    var key =
      node.getAttribute("data-id") ||
      node.getAttribute("data-key") ||
      node.getAttribute("data-slug") ||
      node.getAttribute("data-version") ||
      node.getAttribute("data-index") ||
      node.id ||
      "row-" + index;
    var head = node.querySelector("h1,h2,h3,h4,strong,.card-title,[class$='-title']");
    var label = textOf(head) || clip(textOf(node), 90) || "row " + (index + 1);
    var when = node.querySelector("time[datetime]");
    var code = node.querySelector("code,.mono");
    var fields = { Detail: clip(textOf(node), 300) };
    if (when) fields.Date = when.getAttribute("datetime") || textOf(when);
    if (code) fields.Reference = textOf(code);
    return { key: key, label: label, fields: fields };
  }

  // ------------------------------------------------------------------ index
  function indexItems(inst) {
    var selector = resolveSelector(inst);
    var nodes = selector ? inst.container.querySelectorAll(selector) : [];
    var items = [];
    for (var i = 0; i < nodes.length; i++) {
      var node = nodes[i];
      if (ignored(node)) continue;
      var meta = null;
      try {
        meta = inst.describe(node, items.length);
      } catch (error) {
        meta = null;
      }
      if (!meta) meta = fallbackDescribe(node, items.length);
      var key = String(meta.key == null ? "row-" + items.length : meta.key);
      items.push({
        node: node,
        key: key,
        label: String(meta.label == null ? key : meta.label) || key,
        fields: meta.fields || {},
        shown: isShown(node, inst.container),
      });
    }
    inst.items = items;
  }

  function findItem(inst, key) {
    for (var i = 0; i < inst.items.length; i++) {
      if (inst.items[i].key === key) return inst.items[i];
    }
    return null;
  }

  function shownItems(inst) {
    return inst.items.filter(function (item) {
      return item.shown;
    });
  }

  function selectedKeys(inst) {
    return Object.keys(inst.selection);
  }

  function selectedItems(inst) {
    return inst.items.filter(function (item) {
      return inst.selection[item.key] === true;
    });
  }

  // ------------------------------------------------------------- checkboxes
  function paintItems(inst) {
    inst.items.forEach(function (item) {
      var wrap = item.node.firstChild;
      var box;
      if (!wrap || wrap.nodeType !== 1 || !wrap.classList.contains("bulk-check-wrap")) {
        box = el("input", { type: "checkbox", class: "bulk-check" });
        wrap = el("span", { class: "bulk-check-wrap" }, box);
        item.node.insertBefore(wrap, item.node.firstChild);
      } else {
        box = wrap.querySelector(".bulk-check");
      }
      if (!box) return;
      item.node.setAttribute("data-bulk-key", item.key);
      box.setAttribute("data-bulk-key", item.key);
      box.checked = inst.selection[item.key] === true;
      box.setAttribute(
        "aria-label",
        t("Select " + item.label, "揀「" + item.label + "」")
      );
      item.node.classList.toggle("bulk-selected", box.checked);
    });
  }

  // ------------------------------------------------------------- selection
  function setSelected(inst, key, value) {
    if (value) inst.selection[key] = true;
    else delete inst.selection[key];
  }

  function selectRange(inst, fromKey, toKey, value) {
    var list = shownItems(inst);
    var a = -1;
    var b = -1;
    list.forEach(function (item, index) {
      if (item.key === fromKey) a = index;
      if (item.key === toKey) b = index;
    });
    if (a === -1 || b === -1) {
      setSelected(inst, toKey, value);
      return 1;
    }
    var low = Math.min(a, b);
    var high = Math.max(a, b);
    for (var i = low; i <= high; i++) setSelected(inst, list[i].key, value);
    return high - low + 1;
  }

  function clearSelection(inst) {
    inst.selection = {};
    inst.anchor = null;
  }

  // -------------------------------------------------------------- reporting
  function announce(inst, message) {
    if (!inst.live) return;
    window.clearTimeout(inst.announceTimer);
    inst.announceTimer = window.setTimeout(function () {
      inst.live.textContent = message;
    }, ANNOUNCE_MS);
  }

  function statusLine(inst) {
    var total = inst.items.length;
    var shown = shownItems(inst).length;
    var chosen = selectedItems(inst);
    var hidden = chosen.filter(function (item) {
      return !item.shown;
    }).length;
    var missing = selectedKeys(inst).length - chosen.length;

    var head = t(
      chosen.length + " selected · " + shown + " of " + total + " shown by the current search",
      "已揀 " + chosen.length + " 項 · 現時搜尋顯示緊 " + total + " 項之中嘅 " + shown + " 項"
    );
    var tail = "";
    if (hidden) {
      tail +=
        " · " +
        t(
          hidden + " of the selected are hidden by that search",
          "已揀嘅入面有 " + hidden + " 項俾搜尋收埋咗"
        );
    }
    if (missing > 0) {
      tail +=
        " · " +
        t(
          missing + " selected items are no longer in this list",
          "已揀嘅入面有 " + missing + " 項已經唔喺呢個清單"
        );
    }
    if (!chosen.length && !missing) {
      tail +=
        " · " +
        graded(
          [
            "Select at least one item to enable the actions below.",
            "Pick something and the actions below wake up.",
            "The action buttons are asleep until you tick at least one box.",
          ],
          [
            "揀最少一項，下面啲動作先會開返。",
            "揀返樣嘢，下面啲動作就醒返。",
            "剔最少一個格，下面啲掣先肯做嘢。",
          ]
        );
    }
    return head + tail;
  }

  // ----------------------------------------------------------------- planning
  function buildPlan(inst, action) {
    var targets = [];
    var excluded = [];
    selectedKeys(inst).forEach(function (key) {
      var item = findItem(inst, key);
      if (!item) {
        excluded.push({
          label: key,
          reason: t(
            "no longer in this list — it was removed or the list was rebuilt",
            "已經唔喺呢個清單 — 俾人移走咗或者清單重新畫過"
          ),
        });
        return;
      }
      var verdict = action.eligible ? action.eligible(item, inst) : true;
      if (verdict === true) targets.push(item);
      else excluded.push({ label: item.label, reason: String(verdict) });
    });
    return { targets: targets, excluded: excluded };
  }

  function listNode(entries) {
    var list = el("ul", { class: "bulk-list" });
    entries.forEach(function (entry) {
      list.appendChild(el("li", { text: entry }));
    });
    return list;
  }

  // -------------------------------------------------------------------- arm
  function disarm(inst, reason) {
    if (!inst.pending) return;
    var count = inst.pending.plan.targets.length;
    var action = inst.pending.action;
    inst.pending = null;
    window.clearTimeout(inst.armTimer);
    inst.preview.hidden = true;
    inst.preview.removeAttribute("role");
    while (inst.preview.firstChild) inst.preview.removeChild(inst.preview.firstChild);
    syncActionButtons(inst);
    if (reason === "cancel") {
      report(
        inst,
        t(
          "Cancelled. Nothing ran, and the " + count + " selected items are untouched.",
          "已取消。乜都冇做過，已揀嘅 " + count + " 項原封不動。"
        ),
        false
      );
      focusAction(inst, action.id);
    } else if (reason === "changed") {
      report(
        inst,
        t(
          "The list or the selection changed while the confirmation was open, so " +
            action.label() +
            " did not run.",
          "確認開住嗰陣清單或者選項變咗，所以「" + action.label() + "」冇執行。"
        ),
        false
      );
    } else if (reason === "timeout") {
      report(
        inst,
        t(
          "The confirmation waited " + ARM_MS / 1000 + " seconds and stopped. Nothing ran.",
          "確認等咗 " + ARM_MS / 1000 + " 秒就收工。乜都冇做過。"
        ),
        false
      );
    }
  }

  function fingerprint(inst) {
    return selectedKeys(inst).sort().join("\n") + "||" + inst.items.length;
  }

  function arm(inst, action) {
    if (inst.running) return;
    disarm(inst, null);
    var plan = buildPlan(inst, action);
    var chosen = selectedKeys(inst).length;

    if (!chosen) {
      report(
        inst,
        t(
          "Nothing is selected, so " + action.label() + " has nothing to work on.",
          "乜都未揀，所以「" + action.label() + "」冇嘢可以做。"
        ),
        true
      );
      return;
    }
    if (!plan.targets.length) {
      var lines = plan.excluded.map(function (entry) {
        return entry.label + " — " + entry.reason;
      });
      renderReport(
        inst,
        t(
          "Nothing ran: all " + chosen + " selected items are excluded from " + action.label() + ".",
          "冇執行：已揀嘅 " + chosen + " 項全部都唔適用於「" + action.label() + "」。"
        ),
        lines,
        true
      );
      return;
    }

    inst.pending = { action: action, plan: plan, mark: fingerprint(inst) };

    var head = t(
      chosen + " selected · " + plan.targets.length + " will change · " + plan.excluded.length + " will be skipped",
      "已揀 " + chosen + " 項 · " + plan.targets.length + " 項會改到 · " + plan.excluded.length + " 項會跳過"
    );

    var body = [
      el("h3", { text: action.label() }),
      el("p", { text: head }),
      el("p", { class: "bulk-hint", text: action.help(plan.targets.length) }),
      el(
        "p",
        { class: "bulk-hint", text: action.undoNote ? action.undoNote() : undoAvailability() }
      ),
      el(
        "h3",
        {
          text: t(
            "These " + plan.targets.length + " will be affected",
            "會影響到呢 " + plan.targets.length + " 項"
          ),
        }
      ),
      listNode(
        plan.targets.map(function (item) {
          return item.label;
        })
      ),
    ];

    if (plan.excluded.length) {
      body.push(
        el(
          "h3",
          {
            text: t(
              "These " + plan.excluded.length + " will be skipped, and why",
              "會跳過呢 " + plan.excluded.length + " 項，原因如下"
            ),
          }
        )
      );
      body.push(
        listNode(
          plan.excluded.map(function (entry) {
            return entry.label + " — " + entry.reason;
          })
        )
      );
    }

    var confirm = el("button", {
      type: "button",
      class: action.destructive ? "button button-filled" : "button button-tonal",
      text: action.confirmLabel(plan.targets.length),
      onclick: function () {
        var pending = inst.pending;
        if (!pending) return;
        inst.pending = null;
        window.clearTimeout(inst.armTimer);
        inst.preview.hidden = true;
        inst.preview.removeAttribute("role");
        while (inst.preview.firstChild) inst.preview.removeChild(inst.preview.firstChild);
        run(inst, pending.action, pending.plan);
      },
    });
    var cancel = el("button", {
      type: "button",
      class: "button button-text",
      text: t("Cancel", "取消"),
      onclick: function () {
        disarm(inst, "cancel");
      },
    });
    body.push(el("div", { class: "bulk-line" }, confirm, cancel));

    while (inst.preview.firstChild) inst.preview.removeChild(inst.preview.firstChild);
    inst.preview.setAttribute("data-destructive", String(!!action.destructive));
    // The panel is revealed before its wording is written: an alert announces a
    // change made inside a rendered region, not one made while it was hidden.
    inst.preview.hidden = false;
    if (action.destructive) inst.preview.setAttribute("role", "alert");
    else inst.preview.setAttribute("role", "group");
    body.forEach(function (node) {
      inst.preview.appendChild(node);
    });
    syncActionButtons(inst);
    confirm.focus();

    window.clearTimeout(inst.armTimer);
    inst.armTimer = window.setTimeout(function () {
      disarm(inst, "timeout");
    }, ARM_MS);
  }

  function undoAvailability() {
    return hasHistory()
      ? t(
          "This change is recorded in the local history on this page, and this bar keeps an Undo for it.",
          "呢次改動會記入呢一頁嘅本機歷史，呢條 bar 亦會留一個「還原」畀你。"
        )
      : t(
          "No local history surface is loaded on this page, so nothing is recorded there; this bar keeps an Undo for the last action instead.",
          "呢一頁冇載入本機歷史，所以唔會記錄喺嗰度；呢條 bar 會為最後一個動作留一個「還原」。"
        );
  }

  function hasHistory() {
    return !!(site.history && typeof site.history.record === "function");
  }

  /* The contract this file calls: record({action, label, detail, undo}). A
   * history module that exposes something else gets nothing rather than a
   * guessed call, and the report says so instead of claiming a recording. */
  function recordHistory(entry) {
    if (!hasHistory()) return false;
    try {
      site.history.record(entry);
      return true;
    } catch (error) {
      return false;
    }
  }

  // -------------------------------------------------------------------- run
  function run(inst, action, plan) {
    var ctx = {
      inst: inst,
      action: action,
      targets: plan.targets.slice(),
      keys: plan.targets.map(function (item) {
        return item.key;
      }),
      excluded: plan.excluded.slice(),
      done: 0,
      failed: [],
      skipped: [],
      undo: [],
      cancelled: false,
    };
    inst.running = ctx;
    syncActionButtons(inst);
    // A Cancel control that cannot stop anything is exactly the decorative
    // button this site refuses to draw, so the panel that carries it appears
    // only for a run that actually has steps left to interrupt.
    if (action.step && ctx.keys.length > 1) showProgress(inst, ctx);

    var index = 0;
    var chunk = action.chunk || DEFAULT_CHUNK;

    function finishUp() {
      // Cancelling before the closing step means the closing step does not run:
      // a cancelled copy must not still reach the clipboard.
      if (ctx.cancelled || !action.finish) {
        complete(inst, ctx, { ok: true, message: "" });
        return;
      }
      action.finish(ctx, function (outcome) {
        complete(inst, ctx, outcome || { ok: true, message: "" });
      });
    }

    function step() {
      if (ctx.cancelled) {
        finishUp();
        return;
      }
      if (!action.step || index >= ctx.keys.length) {
        finishUp();
        return;
      }
      var end = Math.min(index + chunk, ctx.keys.length);
      for (; index < end; index++) {
        // A step can rebuild the list under us, so the node is resolved from
        // the key each time rather than from the snapshot taken at arm time.
        if (action.refresh) reindex(inst, true);
        var item = findItem(inst, ctx.keys[index]);
        if (!item) {
          ctx.skipped.push({
            label: ctx.keys[index],
            reason: t(
              "left the list before its turn came",
              "未輪到佢就已經離開咗個清單"
            ),
          });
          continue;
        }
        try {
          var verdict = action.step(item, ctx);
          if (typeof verdict === "string") ctx.skipped.push({ label: item.label, reason: verdict });
          else ctx.done++;
        } catch (error) {
          ctx.failed.push({
            label: item.label,
            reason: String((error && error.message) || error),
          });
        }
      }
      updateProgress(inst, ctx, index);
      if (index >= ctx.keys.length) {
        finishUp();
        return;
      }
      window.setTimeout(step, 0);
    }

    window.setTimeout(step, 0);
  }

  function showProgress(inst, ctx) {
    while (inst.progress.firstChild) inst.progress.removeChild(inst.progress.firstChild);
    inst.progressText = el("p", { "aria-hidden": "true" });
    inst.progressFill = el("span", { class: "bulk-fill" });
    var cancel = el("button", {
      type: "button",
      class: "button button-outlined",
      text: t("Cancel", "取消"),
      onclick: function () {
        ctx.cancelled = true;
        cancel.disabled = true;
        cancel.textContent = t("Cancelling…", "取消緊…");
      },
    });
    inst.progress.appendChild(
      el("h3", {
        text: t("Running " + ctx.action.label(), "執行緊「" + ctx.action.label() + "」"),
      })
    );
    inst.progress.appendChild(el("div", { class: "bulk-track" }, inst.progressFill));
    inst.progress.appendChild(inst.progressText);
    inst.progress.appendChild(el("div", { class: "bulk-line" }, cancel));
    inst.progress.hidden = false;
    updateProgress(inst, ctx, 0);
    cancel.focus();
  }

  function updateProgress(inst, ctx, seen) {
    var total = ctx.keys.length || 1;
    var percent = Math.round((seen / total) * 100);
    if (inst.progressFill) inst.progressFill.style.width = percent + "%";
    if (inst.progressText) {
      inst.progressText.textContent = t(
        seen +
          " of " +
          ctx.keys.length +
          " processed · " +
          ctx.done +
          " changed · " +
          ctx.skipped.length +
          " skipped · " +
          ctx.failed.length +
          " failed",
        "處理咗 " +
          ctx.keys.length +
          " 項之中嘅 " +
          seen +
          " 項 · 改到 " +
          ctx.done +
          " 項 · 跳過 " +
          ctx.skipped.length +
          " 項 · 失敗 " +
          ctx.failed.length +
          " 項"
      );
    }
  }

  function complete(inst, ctx, outcome) {
    inst.running = null;
    inst.progress.hidden = true;
    while (inst.progress.firstChild) inst.progress.removeChild(inst.progress.firstChild);
    inst.progressFill = null;
    inst.progressText = null;

    var action = ctx.action;
    var ok = outcome.ok !== false;
    var lines = [];
    ctx.excluded.forEach(function (entry) {
      lines.push(
        t("Skipped before it ran: ", "開跑前就跳過：") + entry.label + " — " + entry.reason
      );
    });
    ctx.skipped.forEach(function (entry) {
      lines.push(t("Skipped: ", "跳過：") + entry.label + " — " + entry.reason);
    });
    ctx.failed.forEach(function (entry) {
      lines.push(t("Failed: ", "失敗：") + entry.label + " — " + entry.reason);
    });

    var headline;
    if (!ok) {
      headline = t(
        action.label() + " did not complete: " + outcome.message,
        "「" + action.label() + "」未完成：" + outcome.message
      );
    } else if (ctx.cancelled) {
      headline = t(
        "Cancelled part way through " +
          action.label() +
          ". " +
          ctx.done +
          " of " +
          ctx.keys.length +
          " were done; the remaining " +
          (ctx.keys.length - ctx.done - ctx.skipped.length - ctx.failed.length) +
          " were not touched.",
        "「" + action.label() + "」做到一半俾人取消。" +
          ctx.keys.length + " 項入面做咗 " + ctx.done + " 項；" +
          "餘下 " + (ctx.keys.length - ctx.done - ctx.skipped.length - ctx.failed.length) + " 項未郁過。"
      );
    } else {
      headline =
        (outcome.message ||
          t(
            action.label() + ": " + ctx.done + " of " + ctx.keys.length + " done.",
            "「" + action.label() + "」：" + ctx.keys.length + " 項入面完成咗 " + ctx.done + " 項。"
          )) +
        (ctx.skipped.length || ctx.failed.length || ctx.excluded.length
          ? " " +
            t(
              ctx.excluded.length + ctx.skipped.length + " skipped, " + ctx.failed.length + " failed — each one is named below.",
              "跳過咗 " + (ctx.excluded.length + ctx.skipped.length) + " 項，失敗 " + ctx.failed.length + " 項 — 下面逐項有名有姓。"
            )
          : "");
    }

    if (ok && action.destructive && ctx.done) {
      // A destructive run must not leave the processed keys ticked, or the next
      // action would arm against rows that are already gone.
      ctx.keys.slice(0, ctx.done + ctx.skipped.length + ctx.failed.length).forEach(function (key) {
        delete inst.selection[key];
      });
    }

    var recorded = false;
    if (ok && ctx.done) {
      recorded = recordHistory({
        action: action.historyAction || action.id,
        label: t(action.label(), action.label()),
        detail: headline,
        undo: ctx.undo.length
          ? function () {
              runUndo(inst, ctx);
            }
          : null,
      });
    }

    if (ctx.undo.length && ok) {
      inst.undoState = { ctx: ctx, label: action.label() };
      inst.undo.hidden = false;
      inst.undo.textContent = t(
        "Undo — restore " + ctx.undo.length + " items changed by " + action.label(),
        "還原 — 回復「" + action.label() + "」改咗嘅 " + ctx.undo.length + " 項"
      );
    } else if (ok && ctx.done && !ctx.undo.length) {
      lines.push(
        action.undoNote
          ? action.undoNote()
          : t(
              "This action recorded no undo step.",
              "呢個動作冇留低任何還原步驟。"
            )
      );
    }

    if (recorded) {
      lines.push(
        t(
          "Recorded in the local history on this page.",
          "已經記入呢一頁嘅本機歷史。"
        )
      );
    } else if (ok && ctx.done && !hasHistory()) {
      lines.push(
        t(
          "No local history surface is loaded on this page, so nothing was recorded there.",
          "呢一頁冇載入本機歷史，所以嗰邊冇任何記錄。"
        )
      );
    }

    renderReport(inst, headline, lines, !ok || !!ctx.failed.length);
    if (typeof site.notify === "function") {
      site.notify(
        lang.emoji(ok && !ctx.failed.length ? "✅" : "⚠️") + inst.title(),
        headline,
        ok && !ctx.failed.length ? "success" : "warning"
      );
    }
    reindex(inst);
    focusAction(inst, action.id);
  }

  function runUndo(inst, ctx) {
    var restored = 0;
    var failed = [];
    for (var i = ctx.undo.length - 1; i >= 0; i--) {
      try {
        ctx.undo[i]();
        restored++;
      } catch (error) {
        failed.push(String((error && error.message) || error));
      }
    }
    var headline = t(
      "Undone: " + restored + " of " + ctx.undo.length + " items restored" + (failed.length ? ", " + failed.length + " could not be" : "") + ".",
      "已還原：" + ctx.undo.length + " 項入面回復咗 " + restored + " 項" + (failed.length ? "，有 " + failed.length + " 項唔得" : "") + "。"
    );
    recordHistory({
      action: "undo",
      label: t("Undo " + ctx.action.label(), "還原「" + ctx.action.label() + "」"),
      detail: headline,
      undo: null,
    });
    inst.undoState = null;
    inst.undo.hidden = true;
    renderReport(inst, headline, failed, failed.length > 0);
    if (typeof site.notify === "function") {
      site.notify(lang.emoji("↩️") + inst.title(), headline, failed.length ? "warning" : "success");
    }
    reindex(inst);
  }

  // ----------------------------------------------------------------- report
  function report(inst, message, isError) {
    renderReport(inst, message, [], isError);
  }

  function renderReport(inst, message, lines, isError) {
    while (inst.report.firstChild) inst.report.removeChild(inst.report.firstChild);
    inst.report.hidden = false;
    inst.report.appendChild(
      el("p", { class: "bulk-note", "data-state": isError ? "error" : null, text: message })
    );
    if (lines && lines.length) inst.report.appendChild(listNode(lines));
    announce(inst, message);
  }

  // ------------------------------------------------------------------- bar
  function focusAction(inst, id) {
    var button = inst.actionButtons[id];
    if (button && !button.disabled) button.focus();
    else if (inst.clearButton) inst.clearButton.focus();
  }

  function syncActionButtons(inst) {
    var chosen = selectedKeys(inst).length;
    var busy = !!inst.running || !!inst.pending;
    Object.keys(inst.actionButtons).forEach(function (id) {
      var button = inst.actionButtons[id];
      var reason = "";
      if (!chosen) {
        reason = t(
          "Nothing is selected yet. Tick at least one item to enable this.",
          "而家乜都未揀。剔最少一項先可以用。"
        );
      } else if (inst.running) {
        reason = t("Another bulk action is running.", "另一個批次動作行緊。");
      } else if (inst.pending) {
        reason = t("A confirmation is open. Confirm or cancel it first.", "有個確認開住。先確認或者取消佢。");
      }
      button.disabled = !chosen || busy;
      if (reason) button.setAttribute("title", reason);
      else button.removeAttribute("title");
    });
  }

  function render(inst) {
    var total = inst.items.length;
    inst.bar.hidden = total === 0;
    if (!total) return;

    var shown = shownItems(inst).length;
    inst.status.textContent = statusLine(inst);
    announce(inst, inst.status.textContent);

    inst.selectShown.textContent = t("Select the " + shown + " shown", "揀晒顯示緊嘅 " + shown + " 項");
    inst.selectShown.setAttribute(
      "title",
      t(
        "Selects only what the current search shows: " + shown + " of " + total + " items.",
        "只揀現時搜尋顯示緊嘅嘢：" + total + " 項之中嘅 " + shown + " 項。"
      )
    );
    inst.selectAll.textContent = t("Select all " + total + " in this list", "揀晒呢個清單全部 " + total + " 項");
    if (shown === total) {
      inst.selectAll.disabled = true;
      inst.selectAll.setAttribute(
        "title",
        t(
          "No search filter is hiding anything, so " + shown + " shown is already all " + total + ".",
          "而家冇搜尋收埋任何嘢，所以顯示緊嘅 " + shown + " 項已經係全部 " + total + " 項。"
        )
      );
    } else {
      inst.selectAll.disabled = false;
      inst.selectAll.setAttribute(
        "title",
        t(
          "Includes the " + (total - shown) + " items the current search hides.",
          "包埋現時搜尋收埋咗嘅 " + (total - shown) + " 項。"
        )
      );
    }
    inst.invert.textContent = t("Invert the " + shown + " shown", "反轉顯示緊嘅 " + shown + " 項");
    inst.invert.setAttribute(
      "title",
      t(
        "Ticks every shown item that is not selected and unticks the ones that are. Hidden items keep their state.",
        "將顯示緊而未揀嘅剔晒，已揀嘅取消晒。收埋咗嘅嘢維持原狀。"
      )
    );
    inst.clearButton.textContent = t("Clear selection", "清除選擇");
    inst.clearButton.disabled = selectedKeys(inst).length === 0;
    if (inst.clearButton.disabled) {
      inst.clearButton.setAttribute("title", t("Nothing is selected.", "而家乜都未揀。"));
    } else {
      inst.clearButton.removeAttribute("title");
    }

    Object.keys(inst.actionButtons).forEach(function (id) {
      var action = inst.actionsById[id];
      inst.actionButtons[id].textContent = action.label();
    });
    syncActionButtons(inst);

    inst.heading.textContent = t("Bulk actions", "批次動作");
    inst.hint.textContent = graded(
      [
        "Click an item to select it, shift-click for a range, or use the checkboxes. Arrow keys move between them, shift+space extends a range, ctrl+a takes everything shown.",
        "Click to select, shift-click for a run of them, checkboxes if you prefer. Arrows walk the list, shift+space grabs a range, ctrl+a takes the lot that is showing.",
        "Point and click, shift-click to sweep a whole run, or tick the boxes like a sensible person. Arrows walk, shift+space sweeps, ctrl+a takes everything on show.",
      ],
      [
        "撳一下就揀，shift+撳揀一段，或者用啲剔格。方向鍵行嚟行去，shift+space 揀一段，ctrl+a 攞晒顯示緊嗰啲。",
        "撳一下揀一件，shift+撳掃一段，鍾意用剔格都得。方向鍵行、shift+space 掃一段、ctrl+a 攞晒睇得見嗰啲。",
        "撳落去就揀，shift+撳一嘢掃一整段，剔格都一樣咁快。方向鍵行、shift+space 掃、ctrl+a 一次過攞晒睇得見嗰啲。",
      ]
    );
    inst.disclose.textContent = inst.open
      ? t("Hide", "收埋")
      : t("Show", "打開");
    inst.disclose.setAttribute("aria-expanded", String(inst.open));
    inst.disclose.setAttribute(
      "aria-label",
      inst.open
        ? t("Hide the bulk actions for " + inst.title(), "收埋「" + inst.title() + "」嘅批次動作")
        : t(
            "Show the bulk actions for " + inst.title() + (selectedKeys(inst).length ? ", " + selectedKeys(inst).length + " still selected" : ""),
            "打開「" + inst.title() + "」嘅批次動作" + (selectedKeys(inst).length ? "，仲有 " + selectedKeys(inst).length + " 項揀住" : "")
          )
    );
    inst.body.hidden = !inst.open;
    inst.container.setAttribute("data-bulk-collapsed", String(!inst.open));
    inst.bar.setAttribute(
      "aria-label",
      t("Bulk actions for " + inst.title(), "「" + inst.title() + "」嘅批次動作")
    );
  }

  function buildBar(inst) {
    var heading = el("h2");
    var disclose = el("button", {
      type: "button",
      class: "button button-text bulk-disclose",
      onclick: function () {
        inst.open = !inst.open;
        site.store.set(STORE_PREFIX + inst.id, inst.open);
        if (!inst.open) disarm(inst, null);
        render(inst);
      },
    });
    var status = el("p", { class: "bulk-status" });
    var live = el("span", { class: "bulk-sr", role: "status", "aria-live": "polite" });

    var selectShown = el("button", {
      type: "button",
      class: "button button-tonal",
      onclick: function () {
        shownItems(inst).forEach(function (item) {
          setSelected(inst, item.key, true);
        });
        afterSelectionChange(inst);
      },
    });
    var selectAll = el("button", {
      type: "button",
      class: "button button-outlined",
      onclick: function () {
        inst.items.forEach(function (item) {
          setSelected(inst, item.key, true);
        });
        afterSelectionChange(inst);
      },
    });
    var invert = el("button", {
      type: "button",
      class: "button button-outlined",
      onclick: function () {
        shownItems(inst).forEach(function (item) {
          setSelected(inst, item.key, inst.selection[item.key] !== true);
        });
        afterSelectionChange(inst);
      },
    });
    var clear = el("button", {
      type: "button",
      class: "button button-text",
      onclick: function () {
        clearSelection(inst);
        afterSelectionChange(inst);
      },
    });

    var actionsRow = el("div", { class: "bulk-line" });
    inst.actionButtons = {};
    inst.actionsById = {};
    inst.actions.forEach(function (action) {
      inst.actionsById[action.id] = action;
      var button = el("button", {
        type: "button",
        class: action.destructive ? "button button-outlined" : "button button-tonal",
        onclick: function () {
          arm(inst, action);
        },
      });
      inst.actionButtons[action.id] = button;
      actionsRow.appendChild(button);
    });

    var undo = el("button", {
      type: "button",
      class: "button button-outlined",
      hidden: true,
      onclick: function () {
        if (inst.undoState) runUndo(inst, inst.undoState.ctx);
      },
    });

    var preview = el("div", { class: "bulk-panel", hidden: true });
    var progress = el("div", { class: "bulk-panel", role: "status", hidden: true });
    var reportPanel = el("div", { class: "bulk-panel", hidden: true });
    var hint = el("p", { class: "bulk-hint" });

    var body = el(
      "div",
      { class: "bulk-body" },
      el("div", { class: "bulk-line" }, selectShown, selectAll, invert, clear),
      status,
      hint,
      actionsRow,
      preview,
      progress,
      reportPanel,
      el("div", { class: "bulk-line" }, undo)
    );

    var bar = el(
      "section",
      { class: "bulk-bar", role: "group", "data-bulk": inst.id, hidden: true },
      el("div", { class: "bulk-head" }, heading, disclose),
      live,
      body
    );

    bar.addEventListener("keydown", function (event) {
      if (event.key !== "Escape") return;
      if (inst.pending) {
        event.stopPropagation();
        event.preventDefault();
        disarm(inst, "cancel");
      }
    });

    inst.bar = bar;
    inst.heading = heading;
    inst.disclose = disclose;
    inst.status = status;
    inst.live = live;
    inst.hint = hint;
    inst.body = body;
    inst.selectShown = selectShown;
    inst.selectAll = selectAll;
    inst.invert = invert;
    inst.clearButton = clear;
    inst.preview = preview;
    inst.progress = progress;
    inst.report = reportPanel;
    inst.undo = undo;
  }

  function mountBar(inst) {
    if (inst.bar.parentNode) return;
    if (inst.mount === "prepend") inst.container.insertBefore(inst.bar, inst.container.firstChild);
    else if (inst.container.parentNode) inst.container.parentNode.insertBefore(inst.bar, inst.container);
  }

  function afterSelectionChange(inst) {
    if (inst.pending) disarm(inst, "changed");
    paintItems(inst);
    render(inst);
  }

  // ----------------------------------------------------------------- events
  function checkboxOf(node) {
    return node && node.classList && node.classList.contains("bulk-check") ? node : null;
  }

  function itemFromNode(inst, node) {
    var walk = node;
    while (walk && walk !== inst.container) {
      if (walk.nodeType === 1 && walk.hasAttribute("data-bulk-key")) {
        return findItem(inst, walk.getAttribute("data-bulk-key"));
      }
      walk = walk.parentNode;
    }
    return null;
  }

  function textIsSelected(node) {
    try {
      var selection = window.getSelection();
      return !!(selection && !selection.isCollapsed && selection.toString().length > 1);
    } catch (error) {
      return false;
    }
  }

  function toggleFromEvent(inst, item, value, event) {
    if (event && event.shiftKey && inst.anchor && inst.anchor !== item.key) {
      selectRange(inst, inst.anchor, item.key, value);
    } else {
      setSelected(inst, item.key, value);
      inst.anchor = item.key;
    }
    afterSelectionChange(inst);
  }

  function shownIndex(inst, key) {
    var list = shownItems(inst);
    for (var i = 0; i < list.length; i++) {
      if (list[i].key === key) return i;
    }
    return -1;
  }

  function focusShown(inst, index) {
    var list = shownItems(inst);
    if (!list.length) return;
    var bounded = Math.max(0, Math.min(index, list.length - 1));
    var box = list[bounded].node.querySelector(".bulk-check");
    if (box) box.focus();
  }

  function wireEvents(inst) {
    inst.container.addEventListener("click", function (event) {
      if (!inst.open || inst.running) return;
      var box = checkboxOf(event.target);
      if (box) {
        var boxItem = findItem(inst, box.getAttribute("data-bulk-key"));
        if (!boxItem) return;
        toggleFromEvent(inst, boxItem, box.checked, event);
        return;
      }
      if (event.target.closest && event.target.closest(INTERACTIVE)) return;
      if (event.target.closest && event.target.closest(".bulk-bar")) return;
      if (textIsSelected(event.target)) return;
      var item = itemFromNode(inst, event.target);
      if (!item) return;
      toggleFromEvent(inst, item, inst.selection[item.key] !== true, event);
    });

    inst.container.addEventListener("keydown", function (event) {
      var box = checkboxOf(event.target);
      if (!box || !inst.open) return;
      var key = box.getAttribute("data-bulk-key");
      var item = findItem(inst, key);
      if (!item) return;
      var index = shownIndex(inst, key);

      if (event.key === "ArrowDown" || event.key === "ArrowRight") {
        event.preventDefault();
        focusShown(inst, index + 1);
      } else if (event.key === "ArrowUp" || event.key === "ArrowLeft") {
        event.preventDefault();
        focusShown(inst, index - 1);
      } else if (event.key === "Home") {
        event.preventDefault();
        focusShown(inst, 0);
      } else if (event.key === "End") {
        event.preventDefault();
        focusShown(inst, shownItems(inst).length - 1);
      } else if (event.key === " " && event.shiftKey) {
        // The keyboard equivalent of shift-click: extend from the anchor rather
        // than toggling this one box on its own.
        event.preventDefault();
        var value = inst.selection[item.key] !== true;
        if (inst.anchor && inst.anchor !== item.key) selectRange(inst, inst.anchor, item.key, value);
        else {
          setSelected(inst, item.key, value);
          inst.anchor = item.key;
        }
        afterSelectionChange(inst);
        var again = item.node.querySelector(".bulk-check");
        if (again) again.focus();
      } else if ((event.key === "a" || event.key === "A") && (event.ctrlKey || event.metaKey)) {
        event.preventDefault();
        shownItems(inst).forEach(function (row) {
          setSelected(inst, row.key, true);
        });
        afterSelectionChange(inst);
        var refocus = item.node.querySelector(".bulk-check");
        if (refocus) refocus.focus();
      }
    });

    inst.container.addEventListener("contextmenu", function (event) {
      if (!inst.open || typeof site.contextMenu !== "function") return;
      var item = itemFromNode(inst, event.target);
      if (!item) return;
      if (event.target.closest && event.target.closest(INTERACTIVE)) return;
      var chosen = selectedKeys(inst).length;
      var menu = [
        {
          label: inst.selection[item.key]
            ? t("Deselect " + clip(item.label, 40), "取消揀「" + clip(item.label, 40) + "」")
            : t("Select " + clip(item.label, 40), "揀「" + clip(item.label, 40) + "」"),
          run: function () {
            setSelected(inst, item.key, inst.selection[item.key] !== true);
            inst.anchor = item.key;
            afterSelectionChange(inst);
          },
        },
        {
          label: t("Select the " + shownItems(inst).length + " shown", "揀晒顯示緊嘅 " + shownItems(inst).length + " 項"),
          shortcut: "Ctrl+A",
          run: function () {
            shownItems(inst).forEach(function (row) {
              setSelected(inst, row.key, true);
            });
            afterSelectionChange(inst);
          },
        },
        {
          label: t("Clear selection", "清除選擇"),
          disabled: chosen === 0,
          reason: t("Nothing is selected.", "而家乜都未揀。"),
          run: chosen
            ? function () {
                clearSelection(inst);
                afterSelectionChange(inst);
              }
            : null,
        },
        "-",
      ];
      inst.actions.forEach(function (action) {
        menu.push({
          label: action.label(),
          disabled: chosen === 0 || !!inst.running,
          reason: inst.running
            ? t("Another bulk action is running.", "另一個批次動作行緊。")
            : t("Nothing is selected yet.", "而家乜都未揀。"),
          run:
            chosen && !inst.running
              ? function () {
                  arm(inst, action);
                }
              : null,
        });
      });
      site.contextMenu(menu, event, t("Bulk actions for " + inst.title(), "「" + inst.title() + "」嘅批次動作"));
    });
  }

  // ------------------------------------------------------------- re-indexing
  function reindex(inst, quiet) {
    if (inst.observer) inst.observer.disconnect();
    indexItems(inst);
    mountBar(inst);
    paintItems(inst);
    if (inst.observer) {
      // Our own writes queued records while we worked; dropping them is what
      // stops the observer from re-triggering itself for ever.
      inst.observer.takeRecords();
      observe(inst);
    }
    if (!quiet) render(inst);
  }

  function observe(inst) {
    inst.observer.observe(inst.container, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["hidden", "aria-hidden"],
    });
  }

  function schedule(inst) {
    if (inst.scheduled) return;
    inst.scheduled = true;
    var runner = function () {
      inst.scheduled = false;
      if (inst.running) {
        // A run resolves its own nodes step by step; re-indexing under it would
        // only fight with that, and must never disarm a batch in flight.
        reindex(inst, true);
        return;
      }
      if (inst.pending && inst.pending.mark !== fingerprint(inst)) disarm(inst, "changed");
      reindex(inst);
    };
    if (window.requestAnimationFrame) window.requestAnimationFrame(runner);
    else window.setTimeout(runner, 16);
  }

  // ----------------------------------------------------------------- attach
  function attach(config) {
    var options = config || {};
    var container =
      typeof options.container === "string"
        ? document.getElementById(options.container)
        : options.container;
    if (!container || container.nodeType !== 1) {
      // No container means no working surface, and a bar that cannot select
      // anything is exactly the decorative control this site refuses to draw.
      return {
        ok: false,
        refresh: function () {},
        selection: function () {
          return [];
        },
      };
    }

    seq += 1;
    var inst = {
      id: String(options.id || options.container || "list-" + seq),
      container: container,
      itemSelector: options.itemSelector || ":scope > *",
      mount: options.mount === "prepend" ? "prepend" : "before",
      describe: typeof options.describe === "function" ? options.describe : fallbackDescribe,
      titleParts: options.title || ["this list", "呢個清單"],
      search: options.search || null,
      tab: options.tab || null,
      actions: [],
      actionButtons: {},
      actionsById: {},
      items: [],
      selection: {},
      anchor: null,
      pending: null,
      running: null,
      undoState: null,
      armTimer: 0,
      announceTimer: 0,
      scheduled: false,
      open: site.store.get(STORE_PREFIX + String(options.id || options.container || "list-" + seq), true) !== false,
    };

    inst.title = function () {
      return t(inst.titleParts[0], inst.titleParts[1]);
    };

    inst.actions = (options.actions || []).concat(
      options.skipDefaults ? [] : exportActions(inst)
    );

    installStyle();
    buildBar(inst);
    wireEvents(inst);

    if (window.MutationObserver) {
      inst.observer = new window.MutationObserver(function () {
        schedule(inst);
      });
    }

    reindex(inst);
    instances.push(inst);

    return {
      ok: true,
      id: inst.id,
      refresh: function () {
        reindex(inst);
      },
      selection: function () {
        return selectedItems(inst).map(function (item) {
          return { key: item.key, label: item.label, fields: item.fields };
        });
      },
      selectShown: function () {
        shownItems(inst).forEach(function (item) {
          setSelected(inst, item.key, true);
        });
        afterSelectionChange(inst);
      },
      clear: function () {
        clearSelection(inst);
        afterSelectionChange(inst);
      },
    };
  }

  // -------------------------------------------------------- shared actions
  function exportActions(inst) {
    function copier(id, labelPair, format, build) {
      return {
        id: id,
        destructive: false,
        label: function () {
          return t(labelPair[0], labelPair[1]);
        },
        help: function (count) {
          return t(
            "Copies " + count + " items to the clipboard as " + format + ". Nothing in this page changes.",
            "將 " + count + " 項複製到剪貼板，格式係 " + format + "。呢一頁乜都唔會改到。"
          );
        },
        undoNote: function () {
          return t(
            "Nothing on this page changes, so there is nothing to undo. Your clipboard's previous contents are replaced and this page cannot restore them.",
            "呢一頁乜都唔會改，所以冇嘢需要還原。剪貼板原本嘅內容會俾覆蓋，呢一頁救唔返。"
          );
        },
        confirmLabel: function (count) {
          return t("Copy " + count + " as " + format, "複製 " + count + " 項做 " + format);
        },
        finish: function (ctx, done) {
          var state = filterState(inst);
          var rows = ctx.targets.map(function (item) {
            return { key: item.key, label: item.label, fields: item.fields };
          });
          var scope = scopeSentence(inst, rows);
          copyText(build(inst, rows, scope, state), function (ok, reason) {
            if (!ok) {
              done({
                ok: false,
                message: t(
                  "The clipboard refused the copy, so nothing was copied: " + reason,
                  "剪貼板拒絕咗，所以乜都冇複製到：" + reason
                ),
              });
              return;
            }
            ctx.done = rows.length;
            done({
              ok: true,
              message: t(
                "Copied " + rows.length + " items as " + format + " · " + scope,
                "已複製 " + rows.length + " 項做 " + format + " · " + scope
              ),
            });
          });
        },
      };
    }

    return [
      copier("copy-md", ["Copy as Markdown", "複製做 Markdown"], "Markdown", function (i, rows, scope) {
        return markdown(i, rows, scope);
      }),
      copier("copy-csv", ["Copy as CSV", "複製做 CSV"], "CSV", function (i, rows, scope) {
        return csv(i, rows, scope);
      }),
      copier("copy-json", ["Copy as JSON", "複製做 JSON"], "JSON", function (i, rows, scope, state) {
        return json(i, rows, scope, state);
      }),
    ];
  }

  // ------------------------------------------------------------- list wiring
  function settingsRegistry() {
    var map = {};
    try {
      settings.registry().forEach(function (entry) {
        map[entry.key] = entry;
      });
    } catch (error) {
      /* an unregistered settings panel simply yields no extra columns */
    }
    return map;
  }

  function resetSettingsAction() {
    var shipped = settings.DEFAULTS || {};
    return {
      id: "reset-settings",
      destructive: true,
      historyAction: "settings reset",
      label: function () {
        return t("Reset selected to shipped defaults", "將已揀嘅重設做出廠預設");
      },
      help: function (count) {
        return t(
          "Writes the shipped default back over " + count + " settings in this browser. Nothing outside this browser is touched.",
          "喺呢個瀏覽器將 " + count + " 項設定改返做出廠預設值。瀏覽器以外嘅嘢一律唔會郁。"
        );
      },
      undoNote: function () {
        return t(
          "Every previous value is captured before it is overwritten, so the Undo in this bar restores all of them.",
          "每個舊值喺覆蓋之前都會留低，所以呢條 bar 嘅「還原」可以全部回復。"
        );
      },
      confirmLabel: function (count) {
        return t("Reset " + count + " settings", "重設 " + count + " 項設定");
      },
      eligible: function (item) {
        if (item.key === "reset") {
          return t(
            "the reset card is an action, not a stored preference",
            "重設卡係一個動作，唔係一項儲存咗嘅偏好"
          );
        }
        if (!Object.prototype.hasOwnProperty.call(shipped, item.key)) {
          return t(
            "no shipped default is declared for this key",
            "呢個 key 冇聲明過出廠預設值"
          );
        }
        if (String(settings.get(item.key)) === String(shipped[item.key])) {
          return t(
            'already equal to its shipped default "' + shipped[item.key] + '", so resetting it would change nothing',
            "已經等於出廠預設值“" + shipped[item.key] + "”，重設都唔會有分別"
          );
        }
        return true;
      },
      step: function (item, ctx) {
        var key = item.key;
        var previous = settings.get(key);
        settings.set(key, shipped[key]);
        ctx.undo.push(function () {
          settings.set(key, previous);
        });
      },
    };
  }

  function dismissNotificationsAction() {
    return {
      id: "dismiss-notifications",
      destructive: true,
      historyAction: "notifications dismissed",
      // Each dismissal goes through the notification centre's own control, so
      // this never forks a second copy of that store's rules.
      refresh: true,
      chunk: 500,
      label: function () {
        return t("Dismiss selected", "清除已揀嘅");
      },
      help: function (count) {
        return t(
          "Dismisses " + count + " messages through the notification centre's own dismiss control, which raises its usual message for each one. Dismissal is permanent.",
          "用通知中心自己嗰個清除掣清走 " + count + " 條訊息，每條都會照樣彈返佢平時嗰句。清除咗就冇得返轉頭。"
        );
      },
      undoNote: function () {
        return t(
          "The notification centre records dismissal as permanent and exposes no restore path, so this cannot be undone from here.",
          "通知中心當清除係永久，冇提供任何回復途徑，所以呢度還原唔到。"
        );
      },
      confirmLabel: function (count) {
        return t("Dismiss " + count + " permanently", "永久清除 " + count + " 條");
      },
      eligible: function (item) {
        if (!item.node.querySelector(".notif-row-dismiss")) {
          return t(
            "this row exposes no dismiss control",
            "呢一行冇提供清除掣"
          );
        }
        return true;
      },
      step: function (item) {
        var button = item.node.querySelector(".notif-row-dismiss");
        if (!button) {
          return t("its dismiss control disappeared", "佢個清除掣唔見咗");
        }
        button.click();
      },
    };
  }

  var LISTS = [
    {
      id: "features",
      container: "feature-grid",
      itemSelector: ".feature-card",
      title: ["the feature grid", "功能一覽"],
      tab: "features",
      search: { name: "feature", input: "feature-search" },
      describe: function (node, index) {
        return {
          key: node.getAttribute("data-feature-index") || "feature-" + index,
          label: textOf(node.querySelector(".card-title")) || "feature " + (index + 1),
          fields: {
            Category: textOf(node.querySelector(".category-pill")),
            Detail: textOf(node.querySelector(".card-copy")),
            Link: (node.querySelector("a.card-link") || { getAttribute: function () { return ""; } }).getAttribute("href") || "",
          },
        };
      },
    },
    {
      id: "docs",
      container: "docs-index",
      itemSelector: [".docs-index-item", "li"],
      mount: "prepend",
      title: ["the documentation index", "文件索引"],
      tab: "docs",
      search: { name: "docs", input: "docs-search" },
      describe: function (node, index) {
        var button = node.querySelector(".docs-link") || node.querySelector("button");
        return {
          key: (button && button.getAttribute("data-slug")) || "doc-" + index,
          label: textOf(button) || "article " + (index + 1),
          fields: {
            Slug: (button && button.getAttribute("data-slug")) || "",
            Summary: textOf(node.querySelector(".docs-index-summary")),
          },
        };
      },
    },
    {
      id: "screenshots",
      container: "shots-grid",
      itemSelector: [".shot", "figure"],
      title: ["the screenshot grid", "截圖一覽"],
      tab: "screenshots",
      search: { name: "shots", input: "shots-search" },
      describe: function (node, index) {
        var image = node.querySelector("img");
        return {
          key: node.getAttribute("data-shot-index") || "shot-" + index,
          label: textOf(node.querySelector(".shot-title")) || "capture " + (index + 1),
          fields: {
            Pixels: textOf(node.querySelector(".shot-px")),
            Provenance: textOf(node.querySelector(".shot-provenance")),
            Boundary: textOf(node.querySelector(".shot-boundary")),
            File: image ? image.getAttribute("src") || "" : "",
          },
        };
      },
    },
    {
      id: "settings",
      container: "settings-grid",
      itemSelector: ".setting-card",
      title: ["the settings grid", "設定一覽"],
      tab: "settings",
      search: { name: "settings", input: "settings-search" },
      actions: [resetSettingsAction()],
      describe: function (node, index) {
        var key = node.getAttribute("data-setting") || "setting-" + index;
        var entry = settingsRegistry()[key];
        var value = "";
        var provenance = "";
        try {
          if (entry && typeof entry.value === "function") value = String(entry.value());
          if (entry && typeof entry.provenance === "function") provenance = String(entry.provenance());
        } catch (error) {
          /* a control that cannot render its own value still lists its key */
        }
        return {
          key: key,
          label:
            (entry && typeof entry.labelNow === "function" ? entry.labelNow() : "") ||
            textOf(node.querySelector("span")) ||
            key,
          fields: {
            Key: key,
            Value: value,
            Provenance: provenance || textOf(node.querySelector(".setting-provenance")),
          },
        };
      },
    },
    {
      id: "notifications",
      container: "notif-list",
      itemSelector: [".notif-row", "article"],
      title: ["the notification history", "通知記錄"],
      search: { name: "notif", input: "notif-search" },
      actions: [dismissNotificationsAction()],
      describe: function (node, index) {
        var when = node.querySelector("time");
        return {
          key: node.getAttribute("data-id") || "notification-" + index,
          label: textOf(node.querySelector(".notif-row-title")) || "message " + (index + 1),
          fields: {
            Time: (when && when.getAttribute("datetime")) || textOf(when),
            Tone: node.getAttribute("data-tone") || "",
            Body: textOf(node.querySelector(".notif-row-body")),
          },
        };
      },
    },
    {
      id: "changelog",
      container: "changelog-list",
      // changelog.js owns this markup; the first candidate that matches wins, so
      // a rename there costs a fallback rather than an empty bar.
      itemSelector: ["[data-release]", "[data-version]", ".changelog-entry", "article", "li", ":scope > *"],
      title: ["the changelog", "更新記錄"],
      tab: "changelog",
      search: { name: "changelog", input: "changelog-search" },
    },
    {
      id: "history",
      container: "history-list",
      itemSelector: ["[data-revision]", "[data-history-id]", ".history-row", ".history-entry", "article", "li", ":scope > *"],
      title: ["the local history", "本機歷史"],
      tab: "history",
      search: { name: "history", input: "history-search" },
    },
  ];

  // ------------------------------------------------------------------- boot
  function boot() {
    LISTS.forEach(function (config) {
      attach(config);
    });

    settings.onChange(function (key) {
      if (key !== null && key !== "language" && key !== "emoji" && key !== "funnyEn" && key !== "funnyYue") return;
      instances.forEach(function (inst) {
        // The wording of an armed confirmation would be half-translated, so it
        // is stood down rather than repainted mid-sentence.
        if (inst.pending) disarm(inst, "changed");
        reindex(inst);
      });
    });

    if (typeof site.onTabChange === "function") {
      site.onTabChange(function () {
        instances.forEach(function (inst) {
          schedule(inst);
        });
      });
    }
  }

  site.ready(boot);

  // ---------------------------------------------------------------- palette
  site.registerPaletteSource(function () {
    var results = [];
    instances.forEach(function (inst) {
      if (!inst.items.length) return;
      var shown = shownItems(inst).length;
      var chosen = selectedKeys(inst).length;

      function command(id, title, detail, action) {
        results.push({
          id: "bulk:" + inst.id + ":" + id,
          kind: "command",
          section: t("Bulk actions", "批次動作"),
          group: t("Bulk actions", "批次動作"),
          tab: inst.tab,
          title: title,
          label: title,
          detail: detail,
          hint: detail,
          subtitle: detail,
          run: action,
          action: action,
        });
      }

      command(
        "select-shown",
        t("Select the " + shown + " shown in " + inst.title(), "揀晒「" + inst.title() + "」顯示緊嘅 " + shown + " 項"),
        t(
          "Only what the current search shows, out of " + inst.items.length + " items. " + filterSentence(inst),
          inst.items.length + " 項之中，只揀現時搜尋顯示緊嘅。" + filterSentence(inst)
        ),
        function () {
          if (inst.tab) site.showTab(inst.tab);
          inst.open = true;
          site.store.set(STORE_PREFIX + inst.id, true);
          shownItems(inst).forEach(function (item) {
            setSelected(inst, item.key, true);
          });
          afterSelectionChange(inst);
          inst.clearButton.focus();
        }
      );

      if (chosen) {
        command(
          "clear",
          t("Clear the selection in " + inst.title(), "清除「" + inst.title() + "」嘅選擇"),
          t(chosen + " items are selected there.", "嗰度揀咗 " + chosen + " 項。"),
          function () {
            if (inst.tab) site.showTab(inst.tab);
            clearSelection(inst);
            afterSelectionChange(inst);
          }
        );
      }
    });
    return results;
  });

  site.bulk = {
    attach: attach,
    instances: function () {
      return instances.map(function (inst) {
        return {
          id: inst.id,
          title: inst.title(),
          items: inst.items.length,
          shown: shownItems(inst).length,
          selected: selectedKeys(inst).length,
        };
      });
    },
  };
})();
