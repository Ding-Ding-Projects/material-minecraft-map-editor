/* The built-in authenticator.
 *
 * The site listed a two-factor authenticator among its features and shipped no
 * authenticator, which is the decorative-control problem one level up: a page
 * claiming a capability nobody can use. This is the surface.
 *
 * Two honesty rules run through the whole file.
 *
 * A browser has no operating-system credential vault. The desktop contract
 * stores secrets in one; a static page cannot, and pretending otherwise would
 * be the more comfortable lie. Secrets live in this browser's local storage in
 * the clear, the surface says so in plain words wherever it matters, and the
 * reset route is named rather than implied.
 *
 * And the codes come from this device's clock. Nothing here can tell whether
 * that clock is right - there is no server to ask, by design - so the surface
 * shows the time it is using and explains what a rejected code usually means,
 * instead of inventing a skew warning it has no way to earn.
 */
(function () {
  "use strict";

  var site = window.AmuletSite;
  var TOTP = window.AmuletTOTP;
  var QR = window.AmuletQR;
  if (!site || !TOTP || !QR) return;

  var ENTRIES_KEY = "auth.entries";
  var el = site.el;
  var t = function (en, yue) {
    return site.lang.t(en, yue);
  };

  var state = {
    entries: [],
    query: "",
    matcher: null,
    selected: {},
    pairing: null,
    revealed: {},
  };

  var nodes = {};
  var ticking = null;

  /* ------------------------------------------------------------- storage */

  function load() {
    var raw = site.store.get(ENTRIES_KEY, []);
    if (!Array.isArray(raw)) raw = [];
    state.entries = raw.filter(function (entry) {
      return entry && typeof entry.secret === "string" && entry.secret.length;
    });
  }

  function save() {
    site.store.set(ENTRIES_KEY, state.entries);
  }

  function nextId() {
    var highest = 0;
    state.entries.forEach(function (entry) {
      var n = parseInt(String(entry.id || "").replace(/\D/g, ""), 10);
      if (n > highest) highest = n;
    });
    return "entry-" + (highest + 1);
  }

  /* --------------------------------------------------------------- codes */

  function nowSeconds() {
    return Math.floor(Date.now() / 1000);
  }

  function codeFor(entry, offsetPeriods) {
    try {
      return TOTP.totp({
        secret: entry.secret,
        algorithm: entry.algorithm || "SHA1",
        digits: entry.digits || 6,
        period: entry.period || 30,
        seconds: nowSeconds() + (offsetPeriods || 0) * (entry.period || 30),
      });
    } catch (error) {
      return null;
    }
  }

  function grouped(code) {
    if (!code) return "";
    if (code.length === 6) return code.slice(0, 3) + " " + code.slice(3);
    if (code.length === 8) return code.slice(0, 4) + " " + code.slice(4);
    return code.slice(0, Math.ceil(code.length / 2)) +
      " " + code.slice(Math.ceil(code.length / 2));
  }

  function secondsLeft(entry) {
    var period = entry.period || 30;
    return period - (nowSeconds() % period);
  }

  /* ------------------------------------------------------------ matching */

  function visibleEntries() {
    if (!state.matcher) return state.entries.slice();
    return state.entries.filter(function (entry) {
      var haystack = [entry.issuer, entry.account, entry.algorithm].join(" ");
      state.matcher.lastIndex = 0;
      return state.matcher.test(haystack);
    });
  }

  /* --------------------------------------------------------------- pairing */

  function randomSecret(bytes) {
    var out = new Uint8Array(bytes || 20);
    if (window.crypto && window.crypto.getRandomValues) {
      window.crypto.getRandomValues(out);
    } else {
      /* Refuse rather than invent a secret from Math.random: a predictable
       * factor is worse than no factor, because it looks like protection. */
      throw new Error(
        "This browser exposes no cryptographic random source, so a secret " +
          "cannot be generated safely here. Paste one from your own " +
          "authenticator instead."
      );
    }
    return TOTP.encodeBase32(Array.prototype.slice.call(out));
  }

  function beginPairing(seed) {
    state.pairing = Object.assign(
      {
        issuer: "Material Minecraft World Editor",
        account: "",
        secret: "",
        algorithm: "SHA1",
        digits: 6,
        period: 30,
        confirm: "",
        error: "",
        revealed: false,
      },
      seed || {}
    );
    renderPairing();
  }

  function pairingUri() {
    if (!state.pairing || !state.pairing.secret) return "";
    return TOTP.buildUri(state.pairing);
  }

  /* ----------------------------------------------------------------- view */

  function styleOnce() {
    if (document.getElementById("authenticator-style")) return;
    var css = [
      ".auth-grid{display:grid;gap:16px;grid-template-columns:repeat(auto-fill,minmax(280px,1fr))}",
      ".auth-card{border:1px solid var(--outline-variant,#ccc);border-radius:12px;padding:14px;",
      "  background:var(--surface-container-low,transparent);display:flex;flex-direction:column;gap:8px}",
      ".auth-code{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;",
      "  font-size:2rem;letter-spacing:.08em;font-variant-numeric:tabular-nums;user-select:all}",
      ".auth-next{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;",
      "  font-variant-numeric:tabular-nums;opacity:.7}",
      ".auth-meter{height:4px;border-radius:2px;background:var(--outline-variant,#ddd);overflow:hidden}",
      ".auth-meter>span{display:block;height:100%;background:var(--primary,#4d5f92)}",
      ".auth-qr{background:#fff;padding:8px;border-radius:8px;display:inline-block}",
      ".auth-secret{font-family:ui-monospace,monospace;word-break:break-all;user-select:all}",
      ".auth-warn{border-left:4px solid var(--primary,#4d5f92);padding:8px 12px;",
      "  background:var(--surface-container,transparent);border-radius:0 8px 8px 0}",
    ].join("");
    document.head.appendChild(
      el("style", { id: "authenticator-style", text: css })
    );
  }

  function renderPairing() {
    var host = nodes.pairing;
    if (!host) return;
    host.textContent = "";
    if (!state.pairing) return;
    var p = state.pairing;

    var canvas = el("canvas", {
      class: "auth-qr",
      role: "img",
      "aria-label": t(
        "QR code pairing " + (p.account || "this account") + " with " +
          (p.issuer || "this site"),
        "配對 " + (p.account || "呢個帳戶") + " 嘅二維碼"
      ),
    });

    var manual = el("p", { class: "auth-secret", id: "auth-manual-secret" });
    var params = el("p", { class: "muted" });

    function refreshCode() {
      var uri = pairingUri();
      if (!uri) return;
      try {
        var code = QR.draw(canvas, uri, { scale: 4, quiet: 4 });
        params.textContent = t(
          "QR version " + code.version + ", mask " + code.mask + ". " +
            p.algorithm + ", " + p.digits + " digits, every " + p.period + "s.",
          "二維碼版本 " + code.version + "，遮罩 " + code.mask + "。" +
            p.algorithm + "，" + p.digits + " 位，每 " + p.period + " 秒。"
        );
      } catch (error) {
        params.textContent = t(
          "That pairing is too long to encode: " + error.message,
          "呢個配對太長，encode 唔到：" + error.message
        );
      }
      manual.textContent = p.revealed
        ? p.secret.replace(/(.{4})/g, "$1 ").trim()
        : t("Hidden. Reveal it only if you cannot scan.", "已收埋。掃唔到先顯示。");
    }

    var fields = el(
      "div",
      { class: "field-grid" },
      labelled(
        t("Issuer", "發行者"),
        el("input", {
          type: "text",
          value: p.issuer,
          onInput: function (e) {
            p.issuer = e.target.value;
            refreshCode();
          },
        })
      ),
      labelled(
        t("Account", "帳戶"),
        el("input", {
          type: "text",
          value: p.account,
          placeholder: t("you@example.com", "you@example.com"),
          onInput: function (e) {
            p.account = e.target.value;
            refreshCode();
          },
        })
      ),
      labelled(
        t("Algorithm", "演算法"),
        select(TOTP.algorithms, p.algorithm, function (value) {
          p.algorithm = value;
          refreshCode();
        })
      ),
      labelled(
        t("Digits", "位數"),
        select(["6", "7", "8"], String(p.digits), function (value) {
          p.digits = parseInt(value, 10);
          refreshCode();
        })
      ),
      labelled(
        t("Period (seconds)", "週期（秒）"),
        el("input", {
          type: "number",
          min: "10",
          max: "300",
          value: String(p.period),
          onInput: function (e) {
            var n = parseInt(e.target.value, 10);
            if (n >= 10 && n <= 300) {
              p.period = n;
              refreshCode();
            }
          },
        })
      )
    );

    var confirmError = el("p", { class: "field-error", role: "alert" });
    var confirmInput = el("input", {
      type: "text",
      inputmode: "numeric",
      autocomplete: "one-time-code",
      "aria-describedby": "auth-confirm-help",
      placeholder: t("Code from your app", "你 app 顯示嘅碼"),
      onInput: function (e) {
        p.confirm = e.target.value.replace(/\s/g, "");
        confirmError.textContent = "";
      },
    });

    host.appendChild(
      el(
        "div",
        { class: "auth-card" },
        el("h3", { text: t("Pair an authenticator", "配對驗證器") }),
        el("p", {
          class: "muted",
          text: t(
            "The QR is drawn here, in this page, from local code. Nothing is " +
              "requested from any server — a remote QR service would be handed " +
              "the secret on the way to drawing it.",
            "二維碼喺呢一版本機畫出嚟，冇問過任何伺服器。用外面嘅 QR 服務，" +
              "等於將個 secret 交咗畀人。"
          ),
        }),
        canvas,
        el(
          "p",
          null,
          el("button", {
            class: "button button-text",
            type: "button",
            text: p.revealed
              ? t("Hide the secret", "收埋 secret")
              : t("Reveal the secret to type it in", "顯示 secret 手動輸入"),
            onClick: function () {
              p.revealed = !p.revealed;
              renderPairing();
            },
          })
        ),
        manual,
        params,
        fields,
        el("hr"),
        el("h4", { text: t("Confirm the pairing", "確認配對") }),
        el("p", {
          class: "muted",
          id: "auth-confirm-help",
          text: t(
            "Type one current code back. Without this step a mistyped or " +
              "mis-scanned secret is only discovered the day you need it.",
            "打返一個而家嘅碼。冇呢步，掃錯咗要等到你真係要用嗰日先知。"
          ),
        }),
        confirmInput,
        confirmError,
        el(
          "div",
          { class: "row-actions" },
          el("button", {
            class: "button button-filled",
            type: "button",
            text: t("Confirm and save", "確認並儲存"),
            onClick: function () {
              if (!p.account.trim()) {
                confirmError.textContent = t(
                  "Give the entry an account name so you can tell it apart later.",
                  "填個帳戶名，第日先分得出邊個係邊個。"
                );
                return;
              }
              var expected = codeFor(p, 0);
              var previous = codeFor(p, -1);
              if (p.confirm !== expected && p.confirm !== previous) {
                confirmError.textContent = t(
                  "That code does not match. Check the secret was entered " +
                    "exactly, and that this device's clock is right.",
                  "個碼唔啱。睇下 secret 有冇打錯，同埋部機時間啱唔啱。"
                );
                return;
              }
              state.entries.push({
                id: nextId(),
                issuer: p.issuer.trim(),
                account: p.account.trim(),
                secret: p.secret,
                algorithm: p.algorithm,
                digits: p.digits,
                period: p.period,
              });
              save();
              state.pairing = null;
              renderPairing();
              renderList();
              site.notify(
                site.lang.emoji("🔐") +
                  t("Authenticator paired", "驗證器已配對"),
                t(
                  "Saved in this browser. It is not encrypted and not synced.",
                  "存喺呢個瀏覽器度，冇加密，亦都唔會同步。"
                )
              );
            },
          }),
          el("button", {
            class: "button button-text",
            type: "button",
            text: t("Cancel", "取消"),
            onClick: function () {
              state.pairing = null;
              renderPairing();
            },
          })
        )
      )
    );
    refreshCode();
  }

  function labelled(text, control) {
    var id = "auth-f-" + Math.abs(hash(text));
    control.id = id;
    return el(
      "p",
      { class: "field" },
      el("label", { for: id, text: text }),
      control
    );
  }

  function hash(value) {
    var h = 0;
    for (var i = 0; i < value.length; i++) {
      h = (h * 31 + value.charCodeAt(i)) | 0;
    }
    return h;
  }

  function select(values, chosen, onChange) {
    var node = el("select", {
      onChange: function (e) {
        onChange(e.target.value);
      },
    });
    values.forEach(function (value) {
      node.appendChild(
        el("option", { value: value, selected: value === chosen, text: value })
      );
    });
    return node;
  }

  function renderList() {
    var host = nodes.list;
    if (!host) return;
    host.textContent = "";
    var entries = visibleEntries();

    if (nodes.count) {
      nodes.count.textContent = state.query
        ? site.describe(entries.length, "entry", state.query)
        : site.describe(state.entries.length, "entry", "");
    }

    if (!entries.length) {
      host.appendChild(
        el("p", {
          class: "empty-state",
          text: state.entries.length
            ? t(
                "No entry matches that search.",
                "冇 entry 啱呢個搜尋。"
              )
            : t(
                "No authenticator entries yet. Pair one above, or paste an " +
                  "otpauth:// URI.",
                "重未有 entry。喺上面配對一個，或者貼一條 otpauth:// URI。"
              ),
        })
      );
      return;
    }

    entries.forEach(function (entry) {
      host.appendChild(renderEntry(entry));
    });
  }

  function renderEntry(entry) {
    var code = codeFor(entry, 0);
    var next = codeFor(entry, 1);
    var left = secondsLeft(entry);
    var period = entry.period || 30;

    var codeNode = el("div", {
      class: "auth-code",
      "aria-live": "polite",
      "aria-atomic": "true",
      text: code ? grouped(code) : t("unreadable", "讀唔到"),
    });
    var meter = el("div", { class: "auth-meter" }, el("span"));
    meter.firstChild.style.width =
      Math.round((left / period) * 100) + "%";

    var countdown = el("span", {
      class: "muted",
      text: t(left + "s left", "仲有 " + left + " 秒"),
    });

    var card = el(
      "div",
      { class: "auth-card", "data-entry": entry.id },
      el(
        "div",
        { class: "row-between" },
        el("input", {
          type: "checkbox",
          "aria-label": t(
            "Select " + (entry.account || entry.issuer),
            "揀 " + (entry.account || entry.issuer)
          ),
          checked: !!state.selected[entry.id],
          onChange: function (e) {
            state.selected[entry.id] = e.target.checked;
            renderBulk();
          },
        }),
        el("strong", { text: entry.issuer || t("(no issuer)", "（冇發行者）") })
      ),
      el("p", { class: "muted", text: entry.account }),
      codeNode,
      meter,
      el(
        "p",
        { class: "row-between" },
        countdown,
        el("span", {
          class: "auth-next",
          text: next ? t("next " + grouped(next), "下一個 " + grouped(next)) : "",
        })
      ),
      el("p", {
        class: "muted",
        text:
          (entry.algorithm || "SHA1") +
          " · " +
          (entry.digits || 6) +
          t(" digits", " 位") +
          " · " +
          period +
          "s",
      }),
      el(
        "div",
        { class: "row-actions" },
        el("button", {
          class: "button button-tonal",
          type: "button",
          text: t("Copy code", "複製個碼"),
          onClick: function () {
            var value = codeFor(entry, 0);
            if (!value) return;
            copy(value);
          },
        }),
        el("button", {
          class: "button button-text",
          type: "button",
          text: t("Move up", "上移"),
          "aria-label": t(
            "Move " + (entry.account || entry.issuer) + " earlier",
            "將 " + (entry.account || entry.issuer) + " 移前"
          ),
          onClick: function () {
            reorder(entry.id, -1);
          },
        }),
        el("button", {
          class: "button button-text",
          type: "button",
          text: t("Move down", "下移"),
          "aria-label": t(
            "Move " + (entry.account || entry.issuer) + " later",
            "將 " + (entry.account || entry.issuer) + " 移後"
          ),
          onClick: function () {
            reorder(entry.id, 1);
          },
        }),
        el("button", {
          class: "button button-text",
          type: "button",
          text: t("Remove", "刪除"),
          onClick: function () {
            removeEntries([entry.id]);
          },
        })
      )
    );
    card._refresh = function () {
      var live = codeFor(entry, 0);
      var ahead = codeFor(entry, 1);
      var remaining = secondsLeft(entry);
      if (live && codeNode.textContent !== grouped(live)) {
        codeNode.textContent = grouped(live);
      }
      meter.firstChild.style.width =
        Math.round((remaining / period) * 100) + "%";
      countdown.textContent = t(remaining + "s left", "仲有 " + remaining + " 秒");
      var nextText = ahead
        ? t("next " + grouped(ahead), "下一個 " + grouped(ahead))
        : "";
      var nextNode = card.querySelector(".auth-next");
      if (nextNode && nextNode.textContent !== nextText) {
        nextNode.textContent = nextText;
      }
    };
    return card;
  }

  function copy(value) {
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(value);
      } else {
        var area = el("textarea", { value: value });
        document.body.appendChild(area);
        area.select();
        document.execCommand("copy");
        document.body.removeChild(area);
      }
      site.toast(t("Code copied", "個碼複製咗"));
    } catch (error) {
      site.notify(
        t("Could not copy", "複製唔到"),
        t("Select the digits and copy them by hand.", "自己揀住啲數字複製啦。")
      );
    }
  }

  /* Reordering moves the entry within the real list, not within the filtered
   * view: moving something "up" past a row that a search is currently hiding
   * would otherwise look like nothing happened. */
  function reorder(id, direction) {
    var index = state.entries.findIndex(function (entry) {
      return entry.id === id;
    });
    var target = index + direction;
    if (index < 0 || target < 0 || target >= state.entries.length) return;
    var moved = state.entries.splice(index, 1)[0];
    state.entries.splice(target, 0, moved);
    save();
    renderList();
  }

  function removeEntries(ids) {
    var before = state.entries.length;
    state.entries = state.entries.filter(function (entry) {
      return ids.indexOf(entry.id) < 0;
    });
    ids.forEach(function (id) {
      delete state.selected[id];
    });
    save();
    renderList();
    renderBulk();
    site.notify(
      site.lang.emoji("🗑️") + t("Entries removed", "已刪除"),
      t(
        before - state.entries.length + " removed from this browser.",
        "喺呢個瀏覽器度刪咗 " + (before - state.entries.length) + " 個。"
      )
    );
  }

  function renderBulk() {
    var host = nodes.bulk;
    if (!host) return;
    var chosen = Object.keys(state.selected).filter(function (id) {
      return state.selected[id];
    });
    host.textContent = "";
    host.appendChild(
      el("span", {
        class: "muted",
        text: t(chosen.length + " selected", "揀咗 " + chosen.length + " 個"),
      })
    );
    host.appendChild(
      el("button", {
        class: "button button-text",
        type: "button",
        disabled: !chosen.length,
        text: t("Remove selected", "刪除已揀"),
        onClick: function () {
          removeEntries(chosen);
        },
      })
    );
    host.appendChild(
      el("button", {
        class: "button button-text",
        type: "button",
        text: t("Select all shown", "全選"),
        onClick: function () {
          visibleEntries().forEach(function (entry) {
            state.selected[entry.id] = true;
          });
          renderList();
          renderBulk();
        },
      })
    );
    host.appendChild(
      el("button", {
        class: "button button-text",
        type: "button",
        text: t("Export entries", "匯出"),
        onClick: exportEntries,
      })
    );
  }

  /* An ordinary export must not carry usable secrets, and it must say that it
   * left them out rather than quietly producing a file that looks complete. */
  function exportEntries() {
    var rows = state.entries.map(function (entry) {
      return {
        issuer: entry.issuer,
        account: entry.account,
        algorithm: entry.algorithm,
        digits: entry.digits,
        period: entry.period,
        secret: null,
      };
    });
    var payload = {
      exported: new Date().toISOString(),
      note:
        "Secrets are deliberately omitted from this export. Without them " +
        "these rows cannot generate codes, and re-pairing is required.",
      entries: rows,
    };
    var blob = new Blob([JSON.stringify(payload, null, 2)], {
      type: "application/json",
    });
    var url = URL.createObjectURL(blob);
    var link = el("a", { href: url, download: "authenticator-entries.json" });
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    setTimeout(function () {
      URL.revokeObjectURL(url);
    }, 1000);
    site.notify(
      site.lang.emoji("📤") + t("Entries exported", "已匯出"),
      t(
        "Secrets were left out of that file, so it cannot generate codes.",
        "個檔冇 secret，所以出唔到碼。"
      )
    );
  }

  /* --------------------------------------------------------------- import */

  function importUri(text, report) {
    var parsed;
    try {
      parsed = TOTP.parseUri(text);
    } catch (error) {
      report(String(error.message));
      return;
    }
    state.entries.push(Object.assign({ id: nextId() }, parsed));
    save();
    renderList();
    report("");
    site.notify(
      site.lang.emoji("🔐") + t("Entry added", "已加入"),
      t(
        "Added " + (parsed.account || parsed.issuer) + " from its URI.",
        "由 URI 加咗 " + (parsed.account || parsed.issuer) + "。"
      )
    );
  }

  /* A QR *decoder* is not implemented here. Where the browser provides one,
   * use it; where it does not, say so plainly instead of shipping a button
   * that quietly does nothing. */
  function scanSupported() {
    return typeof window.BarcodeDetector === "function";
  }

  /* Camera scanning, where the platform actually has both a camera and a
   * decoder. Everything stays on the device: the video never leaves the page
   * and the stream is stopped the moment a code is read or the user cancels. */
  function scanCamera(report, host) {
    if (!scanSupported() || !navigator.mediaDevices) {
      report(
        t(
          "This browser has no built-in QR reader or no camera access, so " +
            "scanning is unavailable. Paste the otpauth:// URI instead.",
          "呢個瀏覽器冇內建 QR 讀取或者攞唔到鏡頭，掃唔到。改為貼 URI 啦。"
        )
      );
      return;
    }
    var video = el("video", {
      autoplay: true,
      playsinline: true,
      "aria-label": t("Camera preview", "鏡頭預覽"),
    });
    video.style.maxWidth = "320px";
    var stop = el("button", {
      class: "button button-text",
      type: "button",
      text: t("Stop the camera", "熄鏡頭"),
    });
    host.appendChild(video);
    host.appendChild(stop);

    var stream = null;
    var timer = null;
    function shutdown() {
      if (timer) clearInterval(timer);
      if (stream) {
        stream.getTracks().forEach(function (track) {
          track.stop();
        });
      }
      if (video.parentNode) video.parentNode.removeChild(video);
      if (stop.parentNode) stop.parentNode.removeChild(stop);
    }
    stop.addEventListener("click", shutdown);

    navigator.mediaDevices
      .getUserMedia({ video: { facingMode: "environment" } })
      .then(function (got) {
        stream = got;
        video.srcObject = stream;
        var detector = new window.BarcodeDetector({ formats: ["qr_code"] });
        timer = setInterval(function () {
          detector
            .detect(video)
            .then(function (found) {
              if (found && found.length) {
                importUri(found[0].rawValue, report);
                shutdown();
              }
            })
            .catch(function () {
              /* a frame that cannot be read is normal; keep looking */
            });
        }, 400);
      })
      .catch(function (error) {
        shutdown();
        report(
          t("The camera could not be opened: ", "開唔到鏡頭：") + error.message
        );
      });
  }

  function scanImage(file, report) {
    if (!scanSupported()) {
      report(
        t(
          "This browser has no built-in QR reader, so an image cannot be " +
            "scanned here. Paste the otpauth:// URI instead.",
          "呢個瀏覽器冇內建 QR 讀取，掃唔到圖。改為貼 otpauth:// URI 啦。"
        )
      );
      return;
    }
    var detector = new window.BarcodeDetector({ formats: ["qr_code"] });
    createImageBitmap(file)
      .then(function (bitmap) {
        return detector.detect(bitmap);
      })
      .then(function (found) {
        if (!found || !found.length) {
          report(t("No QR code found in that image.", "張圖搵唔到二維碼。"));
          return;
        }
        importUri(found[0].rawValue, report);
      })
      .catch(function (error) {
        report(t("That image could not be read: ", "讀唔到張圖：") + error.message);
      });
  }

  /* ----------------------------------------------------------------- mount */

  function mount() {
    var host = document.getElementById("authenticator-root");
    if (!host) return;
    styleOnce();
    load();

    var importError = el("p", { class: "field-error", role: "alert" });
    var uriInput = el("input", {
      type: "text",
      id: "auth-uri",
      placeholder: "otpauth://totp/Issuer:you?secret=…",
      "aria-label": t("Paste an otpauth URI", "貼 otpauth URI"),
    });
    var fileInput = el("input", {
      type: "file",
      accept: "image/*",
      id: "auth-file",
      onChange: function (e) {
        if (e.target.files && e.target.files[0]) {
          scanImage(e.target.files[0], function (message) {
            importError.textContent = message;
          });
        }
      },
    });

    nodes.count = el("p", { class: "muted", id: "auth-count", role: "status" });
    nodes.bulk = el("div", { class: "row-actions", id: "auth-bulk" });
    nodes.list = el("div", { class: "auth-grid", id: "auth-list" });
    nodes.pairing = el("div", { id: "auth-pairing" });

    host.appendChild(
      el(
        "div",
        { class: "auth-warn" },
        el("p", {
          text: t(
            "Secrets are stored in this browser's local storage, in the clear. " +
              "A web page has no operating-system credential vault to put them " +
              "in. Clearing this site's storage removes every entry, and that " +
              "is also how you reset if something goes wrong.",
            "啲 secret 直接存喺呢個瀏覽器嘅 local storage，冇加密。網頁根本冇 OS " +
              "credential vault 用。清咗呢個網站嘅儲存，全部 entry 就冇晒 —— " +
              "出事嗰陣都係咁 reset。"
          ),
        }),
        el("p", {
          class: "muted",
          text: t(
            "Nothing here is sent anywhere. No account, no sync, no network.",
            "呢度乜都唔會傳去邊。冇帳戶、冇同步、冇網絡。"
          ),
        })
      )
    );

    host.appendChild(
      el(
        "div",
        { class: "auth-card" },
        el("h3", { text: t("Add an entry", "加入 entry") }),
        el("p", {
          class: "field",
          },
          el("label", { for: "auth-uri", text: t("Paste an otpauth:// URI", "貼 otpauth:// URI") })
        ),
        uriInput,
        el(
          "div",
          { class: "row-actions" },
          el("button", {
            class: "button button-filled",
            type: "button",
            text: t("Add from URI", "由 URI 加入"),
            onClick: function () {
              importUri(uriInput.value, function (message) {
                importError.textContent = message;
                if (!message) uriInput.value = "";
              });
            },
          }),
          el("button", {
            class: "button button-tonal",
            type: "button",
            text: t("Generate a new secret", "產生新 secret"),
            onClick: function () {
              try {
                beginPairing({ secret: randomSecret(20) });
              } catch (error) {
                importError.textContent = String(error.message);
              }
            },
          })
        ),
        el("p", { class: "field" },
          el("label", { for: "auth-file", text: t("…or read a QR from an image", "…或者由圖片讀二維碼") })
        ),
        fileInput,
        el("button", {
          class: "button button-tonal",
          type: "button",
          text: t("…or scan with the camera", "…或者用鏡頭掃"),
          onClick: function (event) {
            scanCamera(function (message) {
              importError.textContent = message;
            }, event.target.parentNode);
          },
        }),
        el("p", {
          class: "muted",
          text: scanSupported()
            ? t(
                "This browser can read a QR from an image locally.",
                "呢個瀏覽器可以喺本機讀圖入面嘅二維碼。"
              )
            : t(
                "This browser has no built-in QR reader, so image scanning is " +
                  "unavailable here. Pasting the URI always works.",
                "呢個瀏覽器冇內建 QR 讀取，所以掃圖用唔到。貼 URI 就一定得。"
              ),
        }),
        importError
      )
    );

    host.appendChild(nodes.pairing);
    host.appendChild(nodes.count);
    host.appendChild(nodes.bulk);
    host.appendChild(nodes.list);

    host.appendChild(
      el("p", {
        class: "muted",
        text: t(
          "Codes are derived from this device's clock, currently reading " +
            new Date().toString() +
            ". If a server keeps rejecting a correct-looking code, that clock " +
            "is the usual reason — nothing here can check it for you.",
          "啲碼係跟住部機個鐘計，而家係 " +
            new Date().toString() +
            "。如果個碼睇落啱但係老被拒絕，多數就係個鐘唔準 —— 呢度冇得幫你查。"
        ),
      })
    );

    wireSearch();
    renderList();
    renderBulk();

    if (ticking) clearInterval(ticking);
    ticking = setInterval(function () {
      var cards = nodes.list ? nodes.list.children : [];
      for (var i = 0; i < cards.length; i++) {
        if (typeof cards[i]._refresh === "function") cards[i]._refresh();
      }
    }, 1000);

    site.registerPaletteSource(function () {
      return state.entries.map(function (entry) {
        return {
          label: t("Authenticator: ", "驗證器：") + (entry.account || entry.issuer),
          hint: entry.issuer,
          tab: "security",
          run: function () {
            site.showTab("security");
          },
        };
      });
    });
  }

  function wireSearch() {
    var input = document.getElementById("auth-search");
    if (!input) return;
    var feedback = document.getElementById("auth-search-feedback");
    var instance = site.regex.attach({
      name: "auth",
      input: input,
      panel: document.getElementById("auth-regex"),
      openButton: document.getElementById("auth-regex-open"),
      onChange: apply,
    });

    function apply() {
      state.query = input.value;
      try {
        state.matcher = state.query
          ? instance && instance.matcher
            ? instance.matcher()
            : site.matcher(state.query, false, "i")
          : null;
        if (feedback) feedback.textContent = "";
      } catch (error) {
        state.matcher = null;
        if (feedback) feedback.textContent = String(error.message);
      }
      renderList();
    }

    input.addEventListener("input", apply);
    apply();
  }

  site.ready(mount);
  site.settings.onChange(function (key) {
    if (key === null || key === "language" || key === "emoji") {
      if (nodes.list) {
        renderList();
        renderBulk();
        renderPairing();
      }
    }
  });

  window.AmuletAuthenticator = {
    entries: function () {
      return state.entries.slice();
    },
    _state: state,
  };
})();
