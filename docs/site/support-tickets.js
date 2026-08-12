/* Support Tickets: the recovery route, dressed as a service desk.
 *
 * The joke is the point, and so is the disclosure. A locked-out user opens a
 * ticket, gets a ticket number, a severity nobody will honour, and a canned
 * first response written with the gravity of a desk that has read the manual
 * once. Then the "resolution" does the only thing that actually works: it tells
 * them exactly which storage to clear, and clears it for them if they ask.
 *
 * One plain line, never styled by the funny level, states that nothing is sent
 * anywhere and nobody is reading it. A user must never sit waiting for a reply
 * that was never coming - that is the difference between a joke and a lie.
 *
 * The desk is this page's own fictional one. It never borrows a real company's
 * support branding, never invents a named human agent, and never quotes a
 * response time that implies one.
 */
(function () {
  "use strict";

  var site = window.AmuletSite;
  if (!site) return;

  var TICKETS_KEY = "support.tickets";
  var el = site.el;
  var t = function (en, yue) {
    return site.lang.t(en, yue);
  };

  var tickets = [];
  var nodes = {};

  var CATEGORIES = [
    { id: "lock", en: "Locked out of a tab or setting", yue: "俾分頁或者設定鎖咗" },
    { id: "authenticator", en: "Authenticator entry lost", yue: "驗證器 entry 唔見咗" },
    { id: "appearance", en: "Appearance will not reset", yue: "外觀 reset 唔到" },
    { id: "other", en: "Something else entirely", yue: "第啲嘢" },
  ];

  var SEVERITIES = [
    { id: "low", en: "Low", yue: "低" },
    { id: "normal", en: "Normal", yue: "普通" },
    { id: "high", en: "High", yue: "高" },
    { id: "critical", en: "Critical", yue: "緊急" },
  ];

  function load() {
    var raw = site.store.get(TICKETS_KEY, []);
    tickets = Array.isArray(raw) ? raw : [];
  }

  function save() {
    site.store.set(TICKETS_KEY, tickets);
  }

  function ticketNumber() {
    var year = new Date().getFullYear();
    var n = tickets.length + 1;
    return "MMWE-" + year + "-" + String(n).padStart(5, "0");
  }

  /* The desk's voice scales with the funny level; the ticket's facts do not. */
  function cannedResponse(severity) {
    var level = site.lang.funny("en");
    if (level >= 4) {
      return t(
        "Thank you for contacting Support. Your ticket has been assigned a " +
          "number, a severity of " + severity + ", and a place in a queue that " +
          "is one item long and not moving. Our records show the responsible " +
          "engineer is you.",
        "多謝聯絡客戶服務。你張飛有編號、嚴重程度 " + severity + "，" +
          "同埋喺一條得一個人、又唔郁嘅隊入面排緊。紀錄顯示負責工程師係你自己。"
      );
    }
    if (level >= 2) {
      return t(
        "Thank you for contacting Support. Your ticket has been logged with " +
          "severity " + severity + ". A resolution is already available below.",
        "多謝聯絡客戶服務。張飛已記錄，嚴重程度 " + severity + "。" +
          "下面已經有解決方法。"
      );
    }
    return t(
      "Ticket logged with severity " + severity + ". The resolution is below.",
      "已記錄，嚴重程度 " + severity + "。解決方法喺下面。"
    );
  }

  function storageDescription() {
    /* Name the actual thing to clear rather than gesturing at "site data". */
    var origin = "";
    try {
      origin = window.location.origin === "null"
        ? t("this local file", "呢個本機檔案")
        : window.location.origin;
    } catch (error) {
      origin = t("this page", "呢一版");
    }
    return origin;
  }

  function create(category, severity, description, aboutLabel) {
    var ticket = {
      number: ticketNumber(),
      category: category,
      severity: severity,
      description: String(description || "").slice(0, 4000),
      about: aboutLabel || "",
      opened: new Date().toISOString(),
      status: "open",
      response: cannedResponse(severity),
    };
    tickets.unshift(ticket);
    save();
    return ticket;
  }

  function advance(ticket) {
    ticket.status =
      ticket.status === "open"
        ? "triaged"
        : ticket.status === "triaged"
        ? "resolved"
        : "resolved";
    save();
    render();
  }

  /* This never deletes anything on the user's behalf without the two-key gate
   * the rest of the site uses for an irreversible action. The ordinary route
   * is that the user clears the storage themselves. */
  function clearEverything(onDone) {
    if (
      window.AmuletConfirm &&
      typeof window.AmuletConfirm.destructive === "function"
    ) {
      window.AmuletConfirm.destructive({
        title: t("Clear this site's stored data", "清除呢個網站嘅資料"),
        detail: t(
          "This removes every setting, lock, authenticator entry, ticket and " +
            "history record this page has stored in this browser. It cannot " +
            "be undone from here.",
          "會刪走呢一版喺瀏覽器度存嘅所有設定、鎖、驗證器 entry、飛同歷史。" +
            "喺呢度撤銷唔到。"
        ),
        onConfirm: function () {
          wipe();
          if (onDone) onDone();
        },
      });
      return;
    }
    /* No gate available means no deletion. Tell the user how to do it. */
    site.notify(
      t("Clear it yourself", "自己清"),
      t(
        "Open this browser's settings and clear stored site data for " +
          storageDescription() + ".",
        "去瀏覽器設定，清除 " + storageDescription() + " 嘅網站資料。"
      )
    );
  }

  function wipe() {
    try {
      var doomed = [];
      for (var i = 0; i < localStorage.length; i++) {
        var key = localStorage.key(i);
        if (key && key.indexOf("mmwe.site.") === 0) doomed.push(key);
      }
      doomed.forEach(function (key) {
        localStorage.removeItem(key);
      });
    } catch (error) {
      /* A browser refusing storage access has already reset it in effect. */
    }
    window.location.reload();
  }

  /* ----------------------------------------------------------------- view */

  function styleOnce() {
    if (document.getElementById("support-style")) return;
    var css = [
      ".ticket{border:1px solid var(--outline-variant,#ccc);border-radius:12px;",
      "  padding:14px;margin:12px 0}",
      ".ticket-number{font-family:ui-monospace,monospace}",
      ".ticket-status{font-size:.75rem;border:1px solid var(--outline,#999);",
      "  border-radius:999px;padding:2px 8px}",
      ".ticket-truth{border:2px solid var(--outline,#999);border-radius:8px;",
      "  padding:10px 12px;margin:12px 0;font-weight:600}",
    ].join("");
    document.head.appendChild(el("style", { id: "support-style", text: css }));
  }

  function render() {
    var host = nodes.list;
    if (!host) return;
    host.textContent = "";
    if (nodes.count) {
      nodes.count.textContent = t(
        tickets.length + " ticket" + (tickets.length === 1 ? "" : "s"),
        tickets.length + " 張飛"
      );
    }
    if (!tickets.length) {
      host.appendChild(
        el("p", {
          class: "empty-state",
          text: t("No tickets yet.", "重未有飛。"),
        })
      );
      return;
    }
    tickets.forEach(function (ticket) {
      host.appendChild(renderTicket(ticket));
    });
  }

  function renderTicket(ticket) {
    return el(
      "div",
      { class: "ticket" },
      el(
        "div",
        { class: "row-between" },
        el("span", { class: "ticket-number", text: ticket.number }),
        el("span", {
          class: "ticket-status",
          text:
            ticket.status === "open"
              ? t("Open", "開緊")
              : ticket.status === "triaged"
              ? t("Triaged", "已分類")
              : t("Resolved", "已解決"),
        })
      ),
      el("p", { text: ticket.about || ticket.category }),
      ticket.description ? el("p", { class: "muted", text: ticket.description }) : null,
      el("p", { text: ticket.response }),
      ticket.status === "resolved"
        ? el(
            "div",
            null,
            el("h4", { text: t("Resolution", "解決方法") }),
            el("p", {
              text: t(
                "Clear the stored data for " + storageDescription() +
                  ". That removes every lock, and everything else this page " +
                  "has saved, which is the only reset there is.",
                "清除 " + storageDescription() + " 嘅儲存資料。" +
                  "所有鎖同呢一版存過嘅嘢都會冇 —— 得呢個 reset。"
              ),
            }),
            el(
              "div",
              { class: "row-actions" },
              el("button", {
                class: "button button-filled",
                type: "button",
                text: t("Clear it now", "而家清"),
                onClick: function () {
                  clearEverything();
                },
              }),
              el("button", {
                class: "button button-text",
                type: "button",
                text: t("Copy the storage name", "複製儲存名稱"),
                onClick: function () {
                  try {
                    navigator.clipboard.writeText(storageDescription());
                    site.toast(t("Copied", "複製咗"));
                  } catch (error) {
                    /* nothing to recover from; the name is on screen anyway */
                  }
                },
              })
            )
          )
        : el("button", {
            class: "button button-tonal",
            type: "button",
            text:
              ticket.status === "open"
                ? t("Escalate to triage", "升級處理")
                : t("Request a resolution", "要求解決"),
            onClick: function () {
              advance(ticket);
            },
          })
    );
  }

  function open(aboutLabel) {
    site.showTab("security");
    var host = document.getElementById("support-root");
    if (host && host.scrollIntoView) host.scrollIntoView({ block: "nearest" });
    if (nodes.about) nodes.about.value = aboutLabel || "";
    if (nodes.description) nodes.description.focus();
  }

  function mount() {
    var host = document.getElementById("support-root");
    if (!host) return;
    styleOnce();
    load();

    nodes.about = el("input", { type: "hidden" });
    nodes.description = el("textarea", {
      id: "support-description",
      rows: "3",
      placeholder: t(
        "What happened? Nobody will read this.",
        "發生咩事？冇人會睇。"
      ),
    });

    var category = el("select", { id: "support-category" });
    CATEGORIES.forEach(function (row) {
      category.appendChild(
        el("option", { value: row.id, text: t(row.en, row.yue) })
      );
    });
    var severity = el("select", { id: "support-severity" });
    SEVERITIES.forEach(function (row) {
      severity.appendChild(
        el("option", { value: row.id, text: t(row.en, row.yue) })
      );
    });

    nodes.count = el("p", { class: "muted", role: "status" });
    nodes.list = el("div", { id: "support-list" });

    host.appendChild(
      el("p", {
        class: "muted",
        text: t(
          "Locked out? Open a ticket. The desk is fictional; the resolution is " +
            "real.",
          "俾鎖咗入唔到？開張飛啦。個服務台係堆砌嘅，但係解決方法係真嘅。"
        ),
      })
    );

    /* Not styled by the funny level, not softened, and never removed. */
    host.appendChild(
      el("p", {
        class: "ticket-truth",
        text:
          "Nothing here is sent anywhere. No ticket exists outside this " +
          "machine, no network request is made, no data is collected, and " +
          "nobody is reading it.",
      })
    );

    host.appendChild(
      el(
        "div",
        { class: "field-grid" },
        el("p", { class: "field" },
          el("label", { for: "support-category", text: t("Category", "分類") }),
          category),
        el("p", { class: "field" },
          el("label", { for: "support-severity", text: t("Severity", "嚴重程度") }),
          severity)
      )
    );
    host.appendChild(
      el("p", { class: "field" },
        el("label", { for: "support-description", text: t("Description", "描述") }))
    );
    host.appendChild(nodes.description);
    host.appendChild(nodes.about);
    host.appendChild(
      el(
        "div",
        { class: "row-actions" },
        el("button", {
          class: "button button-filled",
          type: "button",
          text: t("Open a ticket", "開飛"),
          onClick: function () {
            var chosen = SEVERITIES.filter(function (row) {
              return row.id === severity.value;
            })[0];
            var ticket = create(
              category.value,
              t(chosen.en, chosen.yue),
              nodes.description.value,
              nodes.about.value
            );
            nodes.description.value = "";
            render();
            site.notify(
              site.lang.emoji("🎫") + t("Ticket opened", "開咗飛"),
              t(
                ticket.number + " — and still nobody is reading it.",
                ticket.number + " —— 一樣冇人會睇。"
              )
            );
          },
        })
      )
    );
    host.appendChild(nodes.count);
    host.appendChild(nodes.list);

    render();

    site.registerPaletteSource(function () {
      return [
        {
          label: t("Support Tickets", "客戶服務飛"),
          hint: t("the way back in after a forgotten lock", "唔記得個鎖點入返"),
          tab: "security",
          run: function () {
            open("");
          },
        },
      ];
    });
  }

  site.ready(mount);
  site.settings.onChange(function (key) {
    if ((key === null || key === "language" || key === "emoji" ||
         key === "funnyEn" || key === "funnyYue") && nodes.list) {
      render();
    }
  });

  window.AmuletSupportTickets = { open: open, all: function () { return tickets.slice(); } };
})();
