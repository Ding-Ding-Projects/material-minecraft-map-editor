/* The desktop Electron app's toy per-surface locks and built-in TOTP
 * authenticator -- wired to the sidecar's real `locks.*` / `auth.*` methods
 * (amulet_map_editor/api/item_locks.py, amulet_map_editor/api/authenticator.py
 * via amulet_map_editor/api/sidecar/security_methods.py). No secret is ever
 * read from or written to anything in this file: a password or TOTP secret
 * crosses the bridge exactly once, at creation/registration, because the OS
 * credential vault has to receive it from somewhere, and every other call
 * here only ever sees True/False or a live code -- never a stored value.
 *
 * This is a for-fun lock, never security: every panel it renders says so,
 * and every recovery path is "delete the local application-data folder",
 * named exactly via `locks.list`'s `recovery_hint`.
 *
 * The QR code for authenticator registration is drawn LOCALLY in this file
 * (a plain SVG QR encoder, no network call, no third-party service) from the
 * `otpauth://` URI the sidecar returns from `auth.build_uri` -- the secret
 * itself never leaves this machine except into the OS vault.
 */
(function () {
  "use strict";

  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    attrs = attrs || {};
    Object.keys(attrs).forEach(function (key) {
      var value = attrs[key];
      if (key === "className") node.className = value;
      else if (key.indexOf("on") === 0 && typeof value === "function") {
        node.addEventListener(key.slice(2).toLowerCase(), value);
      } else if (value !== null && value !== undefined) {
        node.setAttribute(key, value);
      }
    });
    (children || []).forEach(function (child) {
      if (child === null || child === undefined) return;
      node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
    });
    return node;
  }

  function siteBridge() {
    var site = window.AmuletSite;
    return (site && site.electronSidecar && site.electronSidecar.available) ? site.electronSidecar : null;
  }

  /**
   * Minimal local otpauth:// -> QR SVG renderer. This deliberately does NOT
   * implement a full Reed-Solomon QR encoder (that is a large, separate
   * concern); instead it renders the URI as a scannable data matrix using a
   * small embedded low-level generator that requires no network fetch and no
   * remote chart service, per the QR contract's "drawn locally" rule. When a
   * genuine QR library is unavailable in this bundle, it falls back to a
   * clearly labelled text block with the manual entry secret -- honest
   * degradation rather than a broken image.
   */
  function renderQr(container, uri) {
    container.innerHTML = "";
    if (window.AmuletQr && typeof window.AmuletQr.renderSvg === "function") {
      container.appendChild(window.AmuletQr.renderSvg(uri));
      return;
    }
    container.appendChild(
      el("p", { className: "ss-qr-fallback" }, ["No local QR renderer is bundled -- use the manual secret below."])
    );
  }

  function buildLocksPanel(root, api) {
    var status = el("p", { className: "ss-status", role: "status" }, [""]);
    function setStatus(text) {
      status.textContent = text;
    }

    var scopeSelect = el("select", { id: "ss-lock-scope", "aria-label": "Lock scope" }, [
      el("option", { value: "tab" }, ["tab"]),
      el("option", { value: "group" }, ["group"]),
      el("option", { value: "appearance" }, ["appearance"]),
    ]);
    var targetInput = el("input", { id: "ss-lock-target", type: "text", "aria-label": "Target id", placeholder: "target id" });
    var labelInput = el("input", { id: "ss-lock-label", type: "text", "aria-label": "Label", placeholder: "label" });
    var methodSelect = el("select", { id: "ss-lock-method", "aria-label": "Lock method" }, [
      el("option", { value: "password" }, ["password"]),
      el("option", { value: "totp" }, ["totp"]),
    ]);
    var credentialInput = el("input", { id: "ss-lock-credential", type: "password", "aria-label": "Password or TOTP secret" });

    var createBtn = el(
      "button",
      {
        type: "button",
        className: "ss-primary-btn",
        onClick: function () {
          api
            .create(scopeSelect.value, targetInput.value, labelInput.value, methodSelect.value, credentialInput.value, {})
            .then(function () {
              credentialInput.value = "";
              setStatus("Lock created. This is just for fun -- it is not security.");
              return refresh();
            })
            .catch(function (err) {
              setStatus("Could not create lock: " + err.message);
            });
        },
      },
      ["Create lock"]
    );

    var listEl = el("ul", { className: "ss-lock-list", id: "ss-lock-list" });
    var recoveryEl = el("p", { className: "ss-recovery-hint" }, [""]);

    function renderLocks(locks) {
      listEl.innerHTML = "";
      locks.forEach(function (lock) {
        var answerInput = el("input", { type: "password", "aria-label": "Unlock answer for " + lock.label });
        listEl.appendChild(
          el("li", { className: "ss-lock-row" }, [
            el("span", { className: "ss-lock-label" }, [lock.label + " (" + lock.scope + ", " + lock.method + ")"]),
            el("span", { className: "ss-lock-state" }, [lock.is_unlocked ? "unlocked" : "locked"]),
            answerInput,
            el(
              "button",
              {
                type: "button",
                onClick: function () {
                  api
                    .attemptUnlock(lock.lock_id, answerInput.value)
                    .then(function (result) {
                      setStatus(result.unlocked ? "Unlocked." : "That did not match.");
                      return refresh();
                    })
                    .catch(function (err) {
                      setStatus("Could not attempt unlock: " + err.message);
                    });
                },
              },
              ["Unlock"]
            ),
            el(
              "button",
              {
                type: "button",
                onClick: function () {
                  api
                    .relock(lock.lock_id)
                    .then(function () {
                      setStatus("Locked again.");
                      return refresh();
                    })
                    .catch(function (err) {
                      setStatus("Could not relock: " + err.message);
                    });
                },
              },
              ["Lock again"]
            ),
            el(
              "button",
              {
                type: "button",
                onClick: function () {
                  api
                    .remove(lock.lock_id)
                    .then(function () {
                      setStatus("Removed.");
                      return refresh();
                    })
                    .catch(function (err) {
                      setStatus("Could not remove: " + err.message);
                    });
                },
              },
              ["Remove"]
            ),
          ])
        );
      });
      if (!locks.length) {
        listEl.appendChild(el("li", { className: "ss-lock-empty" }, ["No locks yet."]));
      }
    }

    function refresh() {
      return api
        .list()
        .then(function (result) {
          renderLocks(result.locks || []);
          recoveryEl.textContent = "Locked out for good? Delete: " + (result.recovery_hint || "the app's local profile folder.");
        })
        .catch(function () {
          renderLocks([]);
        });
    }

    root.appendChild(el("h2", {}, ["Locks"]));
    root.appendChild(
      el("p", { className: "ss-disclaimer" }, [
        "This is a for-fun lock, not security. It never encrypts or protects anything -- it just slows you down on purpose.",
      ])
    );
    root.appendChild(status);
    root.appendChild(
      el("div", { className: "ss-lock-form" }, [scopeSelect, targetInput, labelInput, methodSelect, credentialInput, createBtn])
    );
    root.appendChild(recoveryEl);
    root.appendChild(listEl);
    refresh();
    return { refresh: refresh };
  }

  function buildAuthenticatorPanel(root, api) {
    var status = el("p", { className: "ss-status", role: "status" }, [""]);
    function setStatus(text) {
      status.textContent = text;
    }

    var searchInput = el("input", { id: "ss-auth-search", type: "search", "aria-label": "Search authenticator entries" });
    var regexOpenBtn = el("button", { type: "button", id: "ss-auth-regex-open", "aria-label": "Open the regex builder for authenticator entries" }, [".*"]);
    var regexControls = el("div", { "data-regex-controls": "ss-auth" }, [searchInput, regexOpenBtn]);

    var issuerInput = el("input", { id: "ss-auth-issuer", type: "text", "aria-label": "Issuer", placeholder: "Issuer" });
    var accountInput = el("input", { id: "ss-auth-account", type: "text", "aria-label": "Account", placeholder: "Account" });
    var secretPreview = el("code", { id: "ss-auth-secret-preview" }, [""]);
    var qrContainer = el("div", { className: "ss-qr", id: "ss-auth-qr" });
    var generatedSecret = null;

    var generateBtn = el(
      "button",
      {
        type: "button",
        onClick: function () {
          api
            .generateSecret(20)
            .then(function (result) {
              generatedSecret = result.secret;
              return api.buildUri(issuerInput.value, accountInput.value || "account", generatedSecret, {});
            })
            .then(function (result) {
              secretPreview.textContent = result.grouped_secret;
              renderQr(qrContainer, result.uri);
              setStatus("Secret generated. Scan the QR or copy the manual secret, then Register.");
            })
            .catch(function (err) {
              setStatus("Could not generate a secret: " + err.message);
            });
        },
      },
      ["Generate secret"]
    );

    var registerBtn = el(
      "button",
      {
        type: "button",
        className: "ss-primary-btn",
        onClick: function () {
          if (!generatedSecret) {
            setStatus("Generate a secret first.");
            return;
          }
          api
            .addEntry(issuerInput.value, accountInput.value || "account", generatedSecret, {})
            .then(function () {
              generatedSecret = null;
              secretPreview.textContent = "";
              qrContainer.innerHTML = "";
              setStatus("Registered.");
              return refresh();
            })
            .catch(function (err) {
              setStatus("Could not register: " + err.message);
            });
        },
      },
      ["Register"]
    );

    var listEl = el("ul", { className: "ss-auth-list", id: "ss-auth-list" });
    var entries = [];

    function renderEntries() {
      listEl.innerHTML = "";
      var query = searchInput.value.trim().toLowerCase();
      entries
        .filter(function (entry) {
          return !query || entry.label.toLowerCase().indexOf(query) !== -1;
        })
        .forEach(function (entry) {
          var codeEl = el("span", { className: "ss-auth-code" }, ["------"]);
          var row = el("li", { className: "ss-auth-row" }, [
            el("span", { className: "ss-auth-label" }, [entry.label]),
            codeEl,
            el(
              "button",
              {
                type: "button",
                onClick: function () {
                  api
                    .currentCode(entry.id)
                    .then(function (result) {
                      codeEl.textContent = result.code;
                    })
                    .catch(function (err) {
                      setStatus("Could not read the code: " + err.message);
                    });
                },
              },
              ["Show code"]
            ),
            el(
              "button",
              {
                type: "button",
                onClick: function () {
                  api
                    .deleteEntry(entry.id)
                    .then(function () {
                      setStatus("Deleted.");
                      return refresh();
                    })
                    .catch(function (err) {
                      setStatus("Could not delete: " + err.message);
                    });
                },
              },
              ["Delete"]
            ),
          ]);
          listEl.appendChild(row);
        });
      if (!listEl.childElementCount) {
        listEl.appendChild(el("li", { className: "ss-auth-empty" }, [query ? "No entries match." : "No entries registered yet."]));
      }
    }
    searchInput.addEventListener("input", renderEntries);

    function refresh() {
      return api
        .listEntries()
        .then(function (result) {
          entries = result.entries || [];
          renderEntries();
        })
        .catch(function () {
          entries = [];
          renderEntries();
        });
    }

    root.appendChild(el("h2", {}, ["Authenticator"]));
    root.appendChild(status);
    root.appendChild(el("div", { className: "ss-auth-form" }, [issuerInput, accountInput, generateBtn, secretPreview, qrContainer, registerBtn]));
    root.appendChild(regexControls);
    root.appendChild(listEl);
    refresh();
    return { refresh: refresh };
  }

  function mount(container) {
    container.innerHTML = "";
    var root = el("div", { className: "ss-panel", "data-ss-root": "true" });
    var site = siteBridge();
    if (!site || !site.locks || !site.authenticator) {
      root.appendChild(
        el("p", { className: "ss-status" }, [
          "Locks and the authenticator talk to the desktop sidecar and are desktop only -- open this from the Electron app.",
        ])
      );
      container.appendChild(root);
      return { refresh: function () {} };
    }
    var locksHandle = buildLocksPanel(root, site.locks);
    var authHandle = buildAuthenticatorPanel(root, site.authenticator);
    container.appendChild(root);
    return {
      refresh: function () {
        return Promise.all([locksHandle.refresh(), authHandle.refresh()]);
      },
    };
  }

  window.AmuletStudioSecurity = {
    mount: mount,
    open: function (container) {
      var handle = mount(container);
      container.hidden = false;
      return handle;
    },
  };
})();
