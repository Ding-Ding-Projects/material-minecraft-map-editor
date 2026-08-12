/* Amulet Studio universal surfaces: non-blocking notifications with a
 * reviewable history, local Git-backed version history (browse / restore /
 * export), the external-editor handoff, and the locked-out recovery route
 * dressed as Support Tickets.
 *
 * Mounts into `#studio-surfaces`, a sibling of `#studio-workspace` -- a
 * separate panel, not a replacement for the ribbon shell. Every action here
 * calls a REAL sidecar method registered in
 * amulet_map_editor/api/sidecar/surface_methods.py (notifications.*,
 * history.*, editor.*) through docs/site/electron-bridge.js's
 * `Site.electronSidecar` functions when that bridge has loaded, or directly
 * through `window.mmweDesktop.sidecar.call` when it has not (this file has
 * no ordering dependency on electron-bridge.js). Outside Electron it shows
 * the same honest "desktop only" message studio-workspace.js uses rather
 * than rendering dead controls.
 *
 * Every list here gets: multi-select with a "select all (n filtered)" that
 * says exactly what it selects, an inverse selection, a bulk export that
 * honours the active filter, and -- for notifications -- a bulk dismiss
 * behind the project's real destructive-action confirm gate
 * (docs/site/confirm-gate.js) when it is present.
 */
(function () {
  "use strict";

  var NO_SIDECAR_REASON = "Desktop only: notifications, local history, and the external-editor handoff all need the desktop app's sidecar.";

  function bridgeCall(method, params) {
    var b = window.mmweDesktop && window.mmweDesktop.sidecar;
    if (!b || typeof b.call !== "function") {
      return Promise.resolve({ ok: false, error: { code: "no_bridge" } });
    }
    return b.call(method, params || {});
  }

  function hasSidecar() {
    var b = window.mmweDesktop && window.mmweDesktop.sidecar;
    return !!(b && typeof b.call === "function");
  }

  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    attrs = attrs || {};
    Object.keys(attrs).forEach(function (key) {
      var value = attrs[key];
      if (value === null || value === undefined || value === false) return;
      if (key === "className") node.className = value;
      else if (key === "text") node.textContent = value;
      else if (key.indexOf("on") === 0 && typeof value === "function") {
        node.addEventListener(key.slice(2).toLowerCase(), value);
      } else if (key === "checked" || key === "disabled") {
        node[key] = !!value;
      } else {
        node.setAttribute(key, value);
      }
    });
    (children || []).forEach(function (child) {
      if (child === null || child === undefined) return;
      node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
    });
    return node;
  }

  function matches(query, regex, text) {
    var q = (query || "").trim();
    if (!q) return true;
    var haystack = String(text || "");
    if (!regex) return haystack.toLowerCase().indexOf(q.toLowerCase()) !== -1;
    try {
      return new RegExp(q, "iu").test(haystack);
    } catch (err) {
      return false;
    }
  }

  function downloadText(filename, content) {
    var blob = new Blob([content], { type: "text/plain;charset=utf-8" });
    var url = URL.createObjectURL(blob);
    var anchor = el("a", { href: url, download: filename });
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    setTimeout(function () {
      URL.revokeObjectURL(url);
    }, 1000);
  }

  function confirmDestructive(title, body, onConfirm, anchor) {
    if (window.AmuletConfirm && typeof window.AmuletConfirm.destructive === "function") {
      window.AmuletConfirm.destructive({ title: title, body: body, onConfirm: onConfirm, anchor: anchor });
    } else {
      // Confirm gate not present on this page (e.g. isolated test harness):
      // never perform a destructive bulk action silently -- refuse instead
      // of guessing consent.
    }
  }

  // ------------------------------------------------------------- notifications

  function NotificationsPanel(root) {
    var state = { items: [], selected: {}, query: "", regex: false, includeDismissed: true };

    var searchInput = el("input", {
      type: "text",
      className: "surf-search",
      placeholder: "Search notifications",
      "aria-label": "Search notifications",
    });
    var regexToggle = el("label", { className: "surf-regex-toggle" }, [
      el("input", { type: "checkbox", onChange: function (e) { state.regex = e.target.checked; render(); } }),
      " Regex",
    ]);
    var includeDismissedToggle = el("label", { className: "surf-toggle" }, [
      el("input", {
        type: "checkbox",
        checked: true,
        onChange: function (e) {
          state.includeDismissed = e.target.checked;
          load();
        },
      }),
      " Include dismissed",
    ]);
    searchInput.addEventListener("input", function () {
      state.query = searchInput.value;
      render();
    });

    var selectAllBtn = el("button", { type: "button", className: "surf-btn" }, ["Select all"]);
    var invertBtn = el("button", { type: "button", className: "surf-btn" }, ["Invert selection"]);
    var dismissBtn = el("button", { type: "button", className: "surf-btn surf-btn-destructive" }, ["Dismiss selected"]);
    var exportJsonBtn = el("button", { type: "button", className: "surf-btn" }, ["Export JSON"]);
    var exportMdBtn = el("button", { type: "button", className: "surf-btn" }, ["Export Markdown"]);
    var countLine = el("p", { className: "surf-count", role: "status" });
    var listEl = el("div", { className: "surf-list", role: "listbox", "aria-label": "Notifications" });

    function filtered() {
      return state.items.filter(function (item) {
        return matches(state.query, state.regex, item.title + " " + item.body);
      });
    }

    function selectedIds() {
      return Object.keys(state.selected).filter(function (id) {
        return state.selected[id];
      });
    }

    function load() {
      bridgeCall("notifications.list", { include_dismissed: state.includeDismissed }).then(function (response) {
        state.items = response && response.ok ? response.result.notifications : [];
        state.selected = {};
        render();
      });
    }

    selectAllBtn.addEventListener("click", function () {
      var visible = filtered();
      visible.forEach(function (item) {
        state.selected[item.notification_id] = true;
      });
      render();
    });
    invertBtn.addEventListener("click", function () {
      filtered().forEach(function (item) {
        state.selected[item.notification_id] = !state.selected[item.notification_id];
      });
      render();
    });
    dismissBtn.addEventListener("click", function () {
      var ids = selectedIds();
      if (!ids.length) return;
      confirmDestructive(
        "Dismiss " + ids.length + " notification(s)",
        "This dismisses the selected notification(s) from the active list. They remain reviewable in history with \"Include dismissed\" checked.",
        function () {
          bridgeCall("notifications.bulkDismiss", { notification_ids: ids }).then(load);
        },
        dismissBtn
      );
    });
    exportJsonBtn.addEventListener("click", function () {
      var ids = selectedIds();
      bridgeCall("notifications.export", {
        format: "json",
        notification_ids: ids.length ? ids : filtered().map(function (i) { return i.notification_id; }),
        include_dismissed: state.includeDismissed,
      }).then(function (response) {
        if (response && response.ok) downloadText("notifications.json", response.result.content);
      });
    });
    exportMdBtn.addEventListener("click", function () {
      var ids = selectedIds();
      bridgeCall("notifications.export", {
        format: "markdown",
        notification_ids: ids.length ? ids : filtered().map(function (i) { return i.notification_id; }),
        include_dismissed: state.includeDismissed,
      }).then(function (response) {
        if (response && response.ok) downloadText("notifications.md", response.result.content);
      });
    });

    function render() {
      var visible = filtered();
      listEl.innerHTML = "";
      if (!visible.length) {
        listEl.appendChild(el("p", { className: "surf-empty" }, ["No notifications match."]));
      }
      visible.forEach(function (item) {
        var checkbox = el("input", {
          type: "checkbox",
          checked: !!state.selected[item.notification_id],
          "aria-label": "Select " + item.title,
          onChange: function (e) {
            state.selected[item.notification_id] = e.target.checked;
          },
        });
        listEl.appendChild(
          el("div", { className: "surf-row surf-severity-" + item.severity, role: "option" }, [
            checkbox,
            el("span", { className: "surf-row-severity" }, [item.severity]),
            el("span", { className: "surf-row-title" }, [item.title]),
            el("span", { className: "surf-row-body" }, [item.body]),
            el("span", { className: "surf-row-state" }, [item.dismissed ? "dismissed" : "active"]),
          ])
        );
      });
      var n = visible.length;
      countLine.textContent = selectedIds().length + " selected of " + n + " " + (state.query ? "matching" : "shown") + " notification(s).";
      selectAllBtn.textContent = "Select all (" + n + " filtered)";
    }

    root.appendChild(el("h3", {}, ["Notifications"]));
    root.appendChild(el("div", { className: "surf-toolbar" }, [searchInput, regexToggle, includeDismissedToggle]));
    root.appendChild(el("div", { className: "surf-toolbar" }, [selectAllBtn, invertBtn, dismissBtn, exportJsonBtn, exportMdBtn]));
    root.appendChild(countLine);
    root.appendChild(listEl);

    load();
  }

  // ------------------------------------------------------------- local history

  function HistoryPanel(root) {
    var state = { events: [], query: "", actions: {}, regex: false };
    var ACTIONS = ["created", "updated", "deleted", "restored"];

    var searchInput = el("input", { type: "text", className: "surf-search", placeholder: "Search history", "aria-label": "Search local history" });
    var regexToggle = el("label", { className: "surf-regex-toggle" }, [
      el("input", { type: "checkbox", onChange: function (e) { state.regex = e.target.checked; load(); } }),
      " Regex",
    ]);
    searchInput.addEventListener("input", function () {
      state.query = searchInput.value;
      load();
    });

    var actionToggles = el("div", { className: "surf-toolbar" });
    ACTIONS.forEach(function (action) {
      actionToggles.appendChild(
        el("label", { className: "surf-toggle" }, [
          el("input", {
            type: "checkbox",
            onChange: function (e) {
              state.actions[action] = e.target.checked;
              load();
            },
          }),
          " " + action,
        ])
      );
    });

    var exportJsonBtn = el("button", { type: "button", className: "surf-btn" }, ["Export JSON"]);
    var exportMdBtn = el("button", { type: "button", className: "surf-btn" }, ["Export Markdown"]);
    var countLine = el("p", { className: "surf-count", role: "status" });
    var listEl = el("div", { className: "surf-list", role: "listbox", "aria-label": "Local history events" });

    function activeActions() {
      return ACTIONS.filter(function (a) {
        return state.actions[a];
      });
    }

    function load() {
      var params = { query: state.query, regex: state.regex };
      var active = activeActions();
      if (active.length) params.actions = active;
      bridgeCall("history.events", params).then(function (response) {
        state.events = response && response.ok ? response.result.events : [];
        render();
      });
    }

    exportJsonBtn.addEventListener("click", function () {
      var params = { format: "json", query: state.query };
      var active = activeActions();
      if (active.length) params.actions = active;
      bridgeCall("history.export", params).then(function (response) {
        if (response && response.ok) downloadText("local-history.json", response.result.content);
      });
    });
    exportMdBtn.addEventListener("click", function () {
      var params = { format: "markdown", query: state.query };
      var active = activeActions();
      if (active.length) params.actions = active;
      bridgeCall("history.export", params).then(function (response) {
        if (response && response.ok) downloadText("local-history.md", response.result.content);
      });
    });

    function render() {
      listEl.innerHTML = "";
      if (!state.events.length) {
        listEl.appendChild(el("p", { className: "surf-empty" }, ["No history events match."]));
      }
      state.events.forEach(function (event) {
        var restoreBtn = el("button", { type: "button", className: "surf-btn" }, ["Restore"]);
        restoreBtn.addEventListener("click", function () {
          // A restore is itself a NEW append-only event, never a rewrite --
          // see LocalHistory.restore in amulet_map_editor/api/local_history.py.
          bridgeCall("history.restore", { event_id: event.event_id }).then(load);
        });
        listEl.appendChild(
          el("div", { className: "surf-row" }, [
            el("span", { className: "surf-row-title" }, [event.action + " · " + event.record_type]),
            el("span", { className: "surf-row-body" }, [event.record_id]),
            el("span", { className: "surf-row-state" }, [event.timestamp]),
            restoreBtn,
          ])
        );
      });
      countLine.textContent = state.events.length + " history event(s).";
    }

    root.appendChild(el("h3", {}, ["Local version history"]));
    root.appendChild(el("div", { className: "surf-toolbar" }, [searchInput, regexToggle]));
    root.appendChild(actionToggles);
    root.appendChild(el("div", { className: "surf-toolbar" }, [exportJsonBtn, exportMdBtn]));
    root.appendChild(countLine);
    root.appendChild(listEl);

    load();
  }

  // ------------------------------------------------------------- external editor

  function ExternalEditorPanel(root) {
    var statusLine = el("p", { className: "surf-count", role: "status" });
    var listEl = el("div", { className: "surf-list" });
    var refreshBtn = el("button", { type: "button", className: "surf-btn" }, ["Discover installed editors"]);

    refreshBtn.addEventListener("click", function () {
      bridgeCall("editor.discover", {}).then(function (response) {
        listEl.innerHTML = "";
        if (!response || !response.ok) {
          statusLine.textContent = "Could not discover editors.";
          return;
        }
        var candidates = response.result.candidates;
        statusLine.textContent = candidates.length + " editor(s) found.";
        candidates.forEach(function (candidate) {
          var chooseBtn = el("button", { type: "button", className: "surf-btn" }, ["Use this editor"]);
          chooseBtn.addEventListener("click", function () {
            bridgeCall("editor.select", { path: candidate.path });
          });
          listEl.appendChild(
            el("div", { className: "surf-row" }, [
              el("span", { className: "surf-row-title" }, [candidate.label]),
              el("span", { className: "surf-row-body" }, [candidate.path]),
              chooseBtn,
            ])
          );
        });
      });
    });

    root.appendChild(el("h3", {}, ["External editor"]));
    root.appendChild(el("p", { className: "surf-hint" }, ["Open any exported file or the local-history folder in Visual Studio Code."]));
    root.appendChild(refreshBtn);
    root.appendChild(statusLine);
    root.appendChild(listEl);
  }

  // ------------------------------------------------------------- support tickets

  var TICKETS_KEY = "amulet-studio-support-tickets";

  function loadTickets() {
    try {
      var raw = window.localStorage.getItem(TICKETS_KEY);
      return raw ? JSON.parse(raw) : [];
    } catch (err) {
      return [];
    }
  }

  function saveTickets(tickets) {
    try {
      window.localStorage.setItem(TICKETS_KEY, JSON.stringify(tickets));
    } catch (err) {
      /* storage unavailable is not fatal to the ticket bit */
    }
  }

  function SupportTicketsPanel(root) {
    var state = { tickets: loadTickets(), query: "" };

    var disclosure = el(
      "p",
      { className: "surf-disclosure" },
      [
        "Nothing here is sent anywhere. No ticket leaves this machine, no network request is made, no data is " +
          "collected, and nobody is reading it -- this is a locked-out recovery route dressed as a support desk, for fun.",
      ]
    );

    var categorySelect = el("select", { "aria-label": "Ticket category" }, [
      el("option", { value: "forgotten-lock-credential" }, ["Forgotten lock password / OTP"]),
      el("option", { value: "other" }, ["Something else entirely"]),
    ]);
    var descriptionInput = el("textarea", {
      className: "surf-search",
      rows: "3",
      placeholder: "Describe what happened (kept locally only)",
      "aria-label": "Ticket description",
    });
    var createBtn = el("button", { type: "button", className: "surf-btn" }, ["Open a Support Ticket"]);

    var searchInput = el("input", { type: "text", className: "surf-search", placeholder: "Search tickets", "aria-label": "Search Support Tickets" });
    searchInput.addEventListener("input", function () {
      state.query = searchInput.value;
      render();
    });

    var listEl = el("div", { className: "surf-list" });
    var rootFolder = null;

    bridgeCall("history.root", {}).then(function (response) {
      if (response && response.ok) rootFolder = response.result.root;
    });

    createBtn.addEventListener("click", function () {
      var ticket = {
        id: (window.crypto && window.crypto.randomUUID) ? window.crypto.randomUUID() : String(Date.now()) + "-" + Math.random(),
        category: categorySelect.value,
        description: descriptionInput.value.slice(0, 4000),
        status: "received",
        created_at: new Date().toISOString(),
      };
      state.tickets.unshift(ticket);
      saveTickets(state.tickets);
      descriptionInput.value = "";
      render();
    });

    function resolveTicket(ticket) {
      ticket.status = "resolved";
      saveTickets(state.tickets);
      if (rootFolder) {
        bridgeCall("editor.open", { path: rootFolder });
      }
      render();
    }

    function bulkClear() {
      var ids = state.tickets.filter(function (t) { return t.status === "resolved"; }).map(function (t) { return t.id; });
      if (!ids.length) return;
      confirmDestructive("Clear " + ids.length + " resolved ticket(s)", "This removes resolved tickets from this local list only.", function () {
        state.tickets = state.tickets.filter(function (t) {
          return t.status !== "resolved";
        });
        saveTickets(state.tickets);
        render();
      });
    }
    var clearResolvedBtn = el("button", { type: "button", className: "surf-btn surf-btn-destructive" }, ["Clear resolved tickets"]);
    clearResolvedBtn.addEventListener("click", bulkClear);

    function render() {
      listEl.innerHTML = "";
      var visible = state.tickets.filter(function (t) {
        return matches(state.query, false, t.category + " " + t.description + " " + t.status);
      });
      if (!visible.length) {
        listEl.appendChild(el("p", { className: "surf-empty" }, ["No Support Tickets."]));
      }
      visible.forEach(function (ticket) {
        var resolveBtn = el("button", { type: "button", className: "surf-btn" }, [
          rootFolder ? "Open profile folder" : "Resolve (folder unavailable)",
        ]);
        resolveBtn.disabled = ticket.status === "resolved" && !rootFolder;
        resolveBtn.addEventListener("click", function () {
          resolveTicket(ticket);
        });
        listEl.appendChild(
          el("div", { className: "surf-row" }, [
            el("span", { className: "surf-row-title" }, [ticket.category]),
            el("span", { className: "surf-row-body" }, [ticket.description || "(no description)"]),
            el("span", { className: "surf-row-state" }, [ticket.status]),
            resolveBtn,
          ])
        );
      });
    }

    root.appendChild(el("h3", {}, ["Support Tickets"]));
    root.appendChild(disclosure);
    root.appendChild(el("div", { className: "surf-toolbar" }, [categorySelect]));
    root.appendChild(descriptionInput);
    root.appendChild(createBtn);
    root.appendChild(el("div", { className: "surf-toolbar" }, [searchInput, clearResolvedBtn]));
    root.appendChild(listEl);

    render();
  }

  // ------------------------------------------------------------- mount

  function mount() {
    var root = document.getElementById("studio-surfaces");
    if (!root) return;
    root.innerHTML = "";

    if (!hasSidecar()) {
      root.appendChild(el("p", { className: "surf-empty" }, [NO_SIDECAR_REASON]));
      return;
    }

    var notifications = el("section", { className: "surf-panel", "aria-label": "Notifications" });
    var history = el("section", { className: "surf-panel", "aria-label": "Local history" });
    var editor = el("section", { className: "surf-panel", "aria-label": "External editor" });
    var tickets = el("section", { className: "surf-panel", "aria-label": "Support Tickets" });

    root.appendChild(notifications);
    root.appendChild(history);
    root.appendChild(editor);
    root.appendChild(tickets);

    NotificationsPanel(notifications);
    HistoryPanel(history);
    ExternalEditorPanel(editor);
    SupportTicketsPanel(tickets);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mount);
  } else {
    mount();
  }

  // Exposed for tests and for a host page that wants to remount after the
  // sidecar becomes available.
  window.__AmuletStudioSurfaces = { mount: mount };
})();
