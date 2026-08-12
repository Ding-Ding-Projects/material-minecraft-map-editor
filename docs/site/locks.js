/* Locked tabs and locked appearance properties, plus the Support Tickets desk
 * that unlocks you when you forget.
 *
 * This is a for-fun lock and the surface says so every single time. It is not
 * encryption, it does not protect anything from anyone else who has this
 * machine, and clearing this site's storage removes every lock at once. Saying
 * that plainly is not a disclaimer bolted on afterwards - it is the feature.
 * A toy lock described as security is worse than no lock, because somebody
 * might rely on it.
 *
 * Each lock carries its own credential. There is no master password and no
 * inheritance: locking a tab does not lock the properties inside it, and
 * unlocking one never unlocks another. A user who wants one credential
 * everywhere gets there by deliberately reusing it.
 *
 * Passwords are stored as a salted SHA-256 digest rather than as passwords,
 * using the hash already implemented for the authenticator - which is also why
 * this works from a file:// preview, where crypto.subtle does not exist.
 */
(function () {
  "use strict";

  var site = window.AmuletSite;
  var TOTP = window.AmuletTOTP;
  if (!site || !TOTP) return;

  var LOCKS_KEY = "locks.records";
  var el = site.el;
  var t = function (en, yue) {
    return site.lang.t(en, yue);
  };

  var locks = {};

  /* Unlock grants live in memory only, which is what makes locked-on-launch
   * the default: a reload starts with everything locked again, and no code had
   * to be written to make that happen. A grant is {until: epoch-ms}, where null
   * means "until this page goes away" and 0 means a single use. */
  var unlocked = {};

  var DURATIONS = [
    { id: "surface", minutes: 0, en: "This surface only", yue: "淨係今次" },
    { id: "5", minutes: 5, en: "For 5 minutes", yue: "5 分鐘" },
    { id: "30", minutes: 30, en: "For 30 minutes", yue: "30 分鐘" },
    {
      id: "session",
      minutes: -1,
      en: "Until this page is closed",
      yue: "直到閂咗呢版",
    },
  ];

  var chosenDuration = "surface";

  function grant(target, duration) {
    var spec =
      DURATIONS.filter(function (row) {
        return row.id === duration;
      })[0] || DURATIONS[0];
    if (spec.minutes === 0) unlocked[target] = { until: 0 };
    else if (spec.minutes < 0) unlocked[target] = { until: null };
    else unlocked[target] = { until: Date.now() + spec.minutes * 60000 };
  }

  function granted(target) {
    var held = unlocked[target];
    if (!held) return false;
    if (held.until === null) return true;
    if (held.until === 0) {
      delete unlocked[target]; // one-shot: spend it so the next attempt asks
      return true;
    }
    if (Date.now() > held.until) {
      delete unlocked[target];
      return false;
    }
    return true;
  }

  function relock(target) {
    if (target) delete unlocked[target];
    else unlocked = {};
  }

  function load() {
    var raw = site.store.get(LOCKS_KEY, {});
    locks = raw && typeof raw === "object" ? raw : {};
  }

  function save() {
    site.store.set(LOCKS_KEY, locks);
  }

  function bytes(text) {
    var out = [];
    for (var i = 0; i < text.length; i++) {
      var c = text.charCodeAt(i);
      if (c < 0x80) out.push(c);
      else if (c < 0x800) out.push(0xc0 | (c >> 6), 0x80 | (c & 63));
      else out.push(0xe0 | (c >> 12), 0x80 | ((c >> 6) & 63), 0x80 | (c & 63));
    }
    return out;
  }

  function hex(list) {
    return list
      .map(function (b) {
        return ("0" + b.toString(16)).slice(-2);
      })
      .join("");
  }

  function salt() {
    var out = new Uint8Array(16);
    if (window.crypto && window.crypto.getRandomValues) {
      window.crypto.getRandomValues(out);
      return hex(Array.prototype.slice.call(out));
    }
    /* Without a real random source a salt is decoration. Say so rather than
     * generating one from Math.random and implying it is doing something. */
    return "";
  }

  function digest(password, saltHex) {
    return hex(TOTP.sha256(bytes(saltHex + "\u0000" + password)));
  }

  /* ------------------------------------------------------------- records */

  function get(target) {
    return locks[target] || null;
  }

  function isLocked(target) {
    return !!locks[target] && !granted(target);
  }

  function lockWithPassword(target, label, password) {
    var s = salt();
    locks[target] = {
      kind: "password",
      label: label,
      salt: s,
      digest: digest(password, s),
      created: new Date().toISOString(),
    };
    save();
    record("locked", target, label);
  }

  function lockWithOtp(target, label, secret) {
    TOTP.decodeBase32(secret); // refuse a malformed secret up front
    locks[target] = {
      kind: "otp",
      label: label,
      secret: secret,
      created: new Date().toISOString(),
    };
    save();
    record("locked", target, label);
  }

  function unlock(target, attempt) {
    var lock = get(target);
    if (!lock) return true;
    if (lock.kind === "password") {
      return digest(attempt, lock.salt) === lock.digest;
    }
    /* A small skew window, because a phone's clock and this one rarely agree
     * to the second. */
    for (var drift = -1; drift <= 1; drift++) {
      var expected = TOTP.totp({
        secret: lock.secret,
        seconds: Math.floor(Date.now() / 1000) + drift * 30,
      });
      if (attempt === expected) return true;
    }
    return false;
  }

  function remove(target) {
    var lock = get(target);
    delete locks[target];
    delete unlocked[target];
    save();
    if (lock) record("unlocked-permanently", target, lock.label);
  }

  function record(action, target, label) {
    if (window.AmuletHistory && typeof window.AmuletHistory.record === "function") {
      try {
        window.AmuletHistory.record({
          action: action,
          summary: t("Lock on ", "鎖 ") + (label || target),
        });
      } catch (error) {
        /* history is a convenience here, never a precondition */
      }
    }
  }

  /* ------------------------------------------------------------- prompting */

  var openPrompt = null;

  function promptFor(target, label, onSuccess, anchor) {
    if (openPrompt) closePrompt();
    var lock = get(target);
    if (!lock) {
      onSuccess();
      return;
    }
    var error = el("p", { class: "field-error", role: "alert" });
    var input = el("input", {
      type: lock.kind === "password" ? "password" : "text",
      inputmode: lock.kind === "otp" ? "numeric" : undefined,
      autocomplete: lock.kind === "otp" ? "one-time-code" : "current-password",
      id: "lock-prompt-input",
    });

    var attempts = 0;
    var panel = el(
      "div",
      {
        class: "lock-prompt",
        role: "dialog",
        "aria-modal": "false",
        "aria-labelledby": "lock-prompt-title",
      },
      el("h3", {
        id: "lock-prompt-title",
        text: t("Unlock ", "解鎖 ") + (lock.label || label || target),
      }),
      el("p", {
        class: "muted",
        text:
          lock.kind === "password"
            ? t("This one is behind a password.", "呢個要密碼。")
            : t(
                "This one is behind a one-time code.",
                "呢個要一次性驗證碼。"
              ),
      }),
      el("p", { class: "field" }, el("label", {
        for: "lock-prompt-input",
        text: lock.kind === "password" ? t("Password", "密碼") : t("Code", "驗證碼"),
      })),
      input,
      el(
        "p",
        { class: "field" },
        el("label", { for: "lock-duration", text: t("Stay unlocked", "解鎖幾耐") }),
        (function () {
          var choose = el("select", {
            id: "lock-duration",
            onChange: function (e) {
              chosenDuration = e.target.value;
            },
          });
          DURATIONS.forEach(function (row) {
            choose.appendChild(
              el("option", {
                value: row.id,
                selected: row.id === chosenDuration,
                text: t(row.en, row.yue),
              })
            );
          });
          return choose;
        })()
      ),
      el("p", {
        class: "muted",
        text: t(
          "Reloading this page locks everything again, whichever you pick.",
          "無論揀邊個，重新載入呢版之後全部都會鎖返。"
        ),
      }),
      error,
      el(
        "div",
        { class: "row-actions" },
        el("button", {
          class: "button button-filled",
          type: "button",
          text: t("Unlock", "解鎖"),
          onClick: function () {
            attempts++;
            if (unlock(target, input.value)) {
              grant(target, chosenDuration);
              closePrompt();
              onSuccess();
              return;
            }
            error.textContent =
              attempts >= 3
                ? t(
                    "Still no match. If you have forgotten it, open Support " +
                      "Tickets below — it is the only way back in, and it works.",
                    "都係唔啱。唔記得咗就撳下面嘅 Support Tickets —— " +
                      "得嗰條路，但係真係得。"
                  )
                : t(
                    "That does not match. Nothing has been changed.",
                    "唔啱。乜都冇改到。"
                  );
          },
        }),
        el("button", {
          class: "button button-text",
          type: "button",
          text: t("Cancel", "取消"),
          onClick: function () {
            closePrompt();
            if (anchor && anchor.focus) anchor.focus();
          },
        }),
        el("button", {
          class: "button button-text",
          type: "button",
          text: t("Forgotten your password?", "唔記得咗密碼？"),
          onClick: function () {
            closePrompt();
            if (window.AmuletSupportTickets) {
              window.AmuletSupportTickets.open(lock.label || label || target);
            } else {
              site.showTab("security");
            }
          },
        })
      ),
      el("p", {
        class: "muted",
        text: t(
          "This is a for-fun lock, not security. It does not encrypt anything " +
            "and it will not stop anyone else using this computer.",
          "呢個鎖係娛樂性質，唔係保安。冇加密，亦都攔唔住其他用呢部機嘅人。"
        ),
      })
    );

    (anchor && anchor.parentNode ? anchor.parentNode : document.body).appendChild(
      panel
    );
    openPrompt = panel;
    input.focus();
    panel.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        closePrompt();
        if (anchor && anchor.focus) anchor.focus();
      }
      if (event.key === "Enter") {
        var button = panel.querySelector(".button-filled");
        if (button) button.click();
      }
    });
  }

  function closePrompt() {
    if (openPrompt && openPrompt.parentNode) {
      openPrompt.parentNode.removeChild(openPrompt);
    }
    openPrompt = null;
  }

  /* ---------------------------------------------------------------- view */

  var nodes = {};

  function styleOnce() {
    if (document.getElementById("locks-style")) return;
    var css = [
      ".lock-prompt{border:1px solid var(--outline,#999);border-radius:12px;padding:14px;",
      "  background:var(--surface-container-high,#fff);max-width:420px;",
      "  box-shadow:0 8px 24px rgba(0,0,0,.18);margin-top:8px}",
      ".lock-row{display:flex;gap:12px;align-items:center;justify-content:space-between;",
      "  padding:10px 0;border-bottom:1px solid var(--outline-variant,#ddd)}",
      ".lock-badge{font-size:.75rem;border:1px solid var(--outline,#999);border-radius:999px;",
      "  padding:2px 8px}",
    ].join("");
    document.head.appendChild(el("style", { id: "locks-style", text: css }));
  }

  /* Everything the site can lock, named rather than guessed, so a target that
   * disappears from the page cannot leave an unreachable lock behind. */
  function lockableTargets() {
    var targets = [
      { id: "tab:home", label: t("Home tab", "首頁分頁") },
      { id: "tab:features", label: t("Features tab", "功能分頁") },
      { id: "tab:docs", label: t("Docs tab", "文件分頁") },
      { id: "tab:screenshots", label: t("Screenshots tab", "截圖分頁") },
      { id: "tab:guides", label: t("Guides tab", "指南分頁") },
      { id: "tab:community", label: t("Community tab", "社群分頁") },
      { id: "tab:changelog", label: t("Changelog tab", "變更記錄分頁") },
      { id: "tab:history", label: t("History tab", "歷史分頁") },
      { id: "tab:settings", label: t("Settings tab", "設定分頁") },
      { id: "tab:security", label: t("Security tab", "保安分頁") },
    ];
    [
      ["theme", t("Theme", "主題")],
      ["density", t("Density", "密度")],
      ["accent", t("Accent colour", "主色")],
      ["font", t("Font family", "字型")],
      ["scale", t("Text scale", "字級")],
      ["language", t("Language mode", "語言模式")],
      ["funnyEn", t("Funny level (English)", "搞笑程度（英文）")],
      ["funnyYue", t("Funny level (Cantonese)", "搞笑程度（廣東話）")],
      ["emoji", t("Emoji in dialogs", "對話框 emoji")],
      ["narrator", t("Narrator", "旁白")],
      ["brand", t("Display name", "顯示名稱")],
    ].forEach(function (pair) {
      targets.push({
        id: "appearance:" + pair[0],
        label: t("Appearance: ", "外觀：") + pair[1],
      });
    });
    return targets;
  }

  function renderList() {
    var host = nodes.list;
    if (!host) return;
    host.textContent = "";
    var targets = lockableTargets();
    var query = nodes.search ? nodes.search.value : "";
    var matcher = null;
    try {
      matcher = query ? site.matcher(query, false, "i") : null;
    } catch (error) {
      matcher = null;
    }
    var shown = targets.filter(function (target) {
      if (!matcher) return true;
      matcher.lastIndex = 0;
      return matcher.test(target.label);
    });

    if (nodes.count) {
      var count = Object.keys(locks).length;
      nodes.count.textContent = t(
        count + " lock" + (count === 1 ? "" : "s") + " set · " +
          shown.length + " target" + (shown.length === 1 ? "" : "s") + " shown",
        "設咗 " + count + " 個鎖 · 顯示緊 " + shown.length + " 個目標"
      );
    }

    if (!shown.length) {
      host.appendChild(
        el("p", {
          class: "empty-state",
          text: t("Nothing matches that search.", "冇嘢啱呢個搜尋。"),
        })
      );
      return;
    }

    shown.forEach(function (target) {
      var lock = get(target.id);
      host.appendChild(
        el(
          "div",
          { class: "lock-row" },
          el(
            "div",
            null,
            el("strong", { text: target.label }),
            lock
              ? el("span", {
                  class: "lock-badge",
                  text:
                    lock.kind === "password"
                      ? t(" password", " 密碼")
                      : t(" one-time code", " 一次性碼"),
                })
              : null
          ),
          el(
            "div",
            { class: "row-actions" },
            lock
              ? el("button", {
                  class: "button button-text",
                  type: "button",
                  text: t("Remove lock", "移除鎖"),
                  onClick: function (event) {
                    promptFor(
                      target.id,
                      target.label,
                      function () {
                        remove(target.id);
                        renderList();
                      },
                      event.target
                    );
                  },
                })
              : el("button", {
                  class: "button button-tonal",
                  type: "button",
                  text: t("Lock this", "鎖住佢"),
                  onClick: function (event) {
                    offerLock(target, event.target);
                  },
                })
          )
        )
      );
    });
  }

  function offerLock(target, anchor) {
    if (openPrompt) closePrompt();
    var error = el("p", { class: "field-error", role: "alert" });
    var kind = "password";
    var secretInput = el("input", {
      type: "text",
      id: "lock-new-secret",
      placeholder: t("base32 secret", "base32 secret"),
      hidden: true,
    });
    var passwordInput = el("input", {
      type: "password",
      id: "lock-new-password",
      autocomplete: "new-password",
    });

    var panel = el(
      "div",
      { class: "lock-prompt", role: "dialog", "aria-modal": "false" },
      el("h3", { text: t("Lock ", "鎖住 ") + target.label }),
      el("p", {
        class: "muted",
        text: t(
          "This lock gets its own credential. It is not shared with any other " +
            "lock, and there is no master password.",
          "呢個鎖有自己嘅憑證，唔會同其他鎖共用，亦都冇萬能密碼。"
        ),
      }),
      el(
        "p",
        { class: "field" },
        el("label", { text: t("Method", "方式") }),
        (function () {
          var choose = el("select", {
            onChange: function (e) {
              kind = e.target.value;
              passwordInput.hidden = kind !== "password";
              secretInput.hidden = kind !== "otp";
            },
          });
          choose.appendChild(
            el("option", { value: "password", text: t("Password", "密碼") })
          );
          choose.appendChild(
            el("option", { value: "otp", text: t("One-time code", "一次性碼") })
          );
          return choose;
        })()
      ),
      passwordInput,
      secretInput,
      error,
      el(
        "div",
        { class: "row-actions" },
        el("button", {
          class: "button button-filled",
          type: "button",
          text: t("Set the lock", "設定"),
          onClick: function () {
            try {
              if (kind === "password") {
                if (!passwordInput.value) {
                  error.textContent = t(
                    "Type a password first.",
                    "先打個密碼。"
                  );
                  return;
                }
                lockWithPassword(target.id, target.label, passwordInput.value);
              } else {
                lockWithOtp(target.id, target.label, secretInput.value);
              }
            } catch (err) {
              error.textContent = String(err.message);
              return;
            }
            closePrompt();
            renderList();
            site.notify(
              site.lang.emoji("🔒") + t("Lock set", "已上鎖"),
              t(
                target.label +
                  " is locked. Clearing this site's storage removes it.",
                target.label + " 鎖咗。清咗網站儲存就會冇。"
              )
            );
          },
        }),
        el("button", {
          class: "button button-text",
          type: "button",
          text: t("Cancel", "取消"),
          onClick: function () {
            closePrompt();
            if (anchor && anchor.focus) anchor.focus();
          },
        })
      ),
      el("p", {
        class: "muted",
        text: t(
          "For fun only. Not encryption, not protection from anyone else with " +
            "this computer.",
          "純娛樂。唔係加密，亦都唔擋到其他用呢部機嘅人。"
        ),
      })
    );
    (anchor && anchor.parentNode ? anchor.parentNode : document.body).appendChild(
      panel
    );
    openPrompt = panel;
    passwordInput.focus();
  }

  function mount() {
    var host = document.getElementById("locks-root");
    if (!host) return;
    styleOnce();
    load();

    nodes.count = el("p", { class: "muted", role: "status" });
    nodes.list = el("div", { id: "locks-list" });
    nodes.search = document.getElementById("locks-search");

    host.appendChild(
      el("p", {
        class: "muted",
        text: t(
          "Lock a tab or an appearance value behind a password or a one-time " +
            "code. Every lock has its own credential — unlocking one never " +
            "unlocks another.",
          "可以用密碼或者一次性碼鎖住分頁同外觀設定。每個鎖有自己嘅憑證 —— " +
            "解鎖一個唔會解到另一個。"
        ),
      })
    );
    host.appendChild(
      el(
        "div",
        { class: "row-actions" },
        nodes.count,
        el("button", {
          class: "button button-text",
          type: "button",
          id: "locks-relock",
          text: t("Lock everything again now", "而家全部鎖返"),
          onClick: function () {
            relock();
            renderList();
            site.notify(
              site.lang.emoji("🔒") + t("Locked again", "已鎖返"),
              t(
                "Every unlock granted on this page has been given back.",
                "呢一版攞過嘅解鎖全部收返。"
              )
            );
          },
        })
      )
    );
    host.appendChild(nodes.list);
    host.appendChild(
      el("p", {
        class: "muted",
        text: t(
          "Forgotten a credential? Support Tickets below opens the route back " +
            "in. Nothing here can be recovered any other way, and that is on " +
            "purpose — it is a toy.",
          "唔記得咗憑證？下面嘅 Support Tickets 有返入去嘅方法。冇其他路，" +
            "係特登嘅 —— 呢個係玩具嚟㗎。"
        ),
      })
    );

    if (nodes.search) {
      site.regex.attach({
        name: "locks",
        input: nodes.search,
        panel: document.getElementById("locks-regex"),
        openButton: document.getElementById("locks-regex-open"),
        onChange: renderList,
      });
      nodes.search.addEventListener("input", renderList);
    }

    renderList();

    site.registerPaletteSource(function () {
      return lockableTargets().map(function (target) {
        return {
          label: t("Lock: ", "鎖：") + target.label,
          hint: get(target.id)
            ? t("locked", "已鎖")
            : t("not locked", "未鎖"),
          tab: "security",
          run: function () {
            site.showTab("security");
          },
        };
      });
    });
  }

  site.ready(mount);
  site.settings.onChange(function (key) {
    if ((key === null || key === "language" || key === "emoji") && nodes.list) {
      renderList();
    }
  });

  window.AmuletLocks = {
    isLocked: isLocked,
    promptFor: promptFor,
    relock: relock,
    get: get,
    targets: lockableTargets,
    _digest: digest,
    _unlock: unlock,
    /* Exercises the grant bookkeeping for the test suite. A grant that never
     * expires is indistinguishable from no lock at all, and reading the code
     * cannot tell you which you have - only running the clock can. The expired
     * case moves the deadline into the past rather than sleeping, so the test
     * stays fast and does not depend on wall-clock timing. */
    _grantProbe: function (kind) {
      var target = "__probe__";
      delete unlocked[target];
      var first;
      var second;
      if (kind === "expired") {
        grant(target, "5");
        first = granted(target);
        if (unlocked[target]) unlocked[target].until = Date.now() - 1;
        second = granted(target);
      } else {
        grant(target, kind === "session" ? "session" : "surface");
        first = granted(target);
        second = granted(target);
      }
      delete unlocked[target];
      return { first: first, second: second };
    },
  };
})();
