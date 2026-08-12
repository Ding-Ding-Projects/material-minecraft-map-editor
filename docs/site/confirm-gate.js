/* The destructive-action gate: two keys, then a slider.
 *
 * Every irreversible action on this site goes through here. The shape is
 * deliberate rather than decorative: two controls that must each be turned
 * independently, and only then a slider that has to be carried the whole way.
 * None of it can be satisfied by one reflexive click on a button that happened
 * to be under the pointer, which is the failure an ordinary "are you sure?"
 * dialog does nothing about.
 *
 * The playful copy is styled by the funny level like everything else. What is
 * never styled, never softened and never omitted is the sentence naming what
 * is about to be destroyed. A gate whose joke leaves the user unsure what the
 * button does is a broken gate, not a funny one.
 *
 * An emergency exit is always present and always works: Escape, the cancel
 * button, or clicking away. Focus returns to whatever opened the gate.
 */
(function () {
  "use strict";

  var site = window.AmuletSite;
  if (!site) return;

  var el = site.el;
  var t = function (en, yue) {
    return site.lang.t(en, yue);
  };

  var open = null;

  function styleOnce() {
    if (document.getElementById("confirm-gate-style")) return;
    var css = [
      ".gate-backdrop{position:fixed;inset:0;background:rgba(0,0,0,.45);",
      "  display:flex;align-items:center;justify-content:center;z-index:900;padding:16px}",
      ".gate{max-width:520px;width:100%;background:var(--surface-container-high,#fff);",
      "  color:var(--on-surface,#111);border-radius:16px;padding:20px;",
      "  box-shadow:0 16px 48px rgba(0,0,0,.32);max-height:90vh;overflow:auto}",
      ".gate-facts{border-left:4px solid var(--error,#8c2f26);padding:8px 12px;",
      "  margin:12px 0;background:var(--surface-container,transparent)}",
      ".gate-keys{display:flex;gap:16px;flex-wrap:wrap;margin:12px 0}",
      ".gate-key{display:flex;gap:8px;align-items:center;border:1px solid var(--outline,#999);",
      "  border-radius:999px;padding:8px 14px}",
      ".gate-slider{width:100%}",
      ".gate-progress{height:6px;border-radius:3px;background:var(--outline-variant,#ddd);",
      "  overflow:hidden;margin:8px 0}",
      ".gate-progress>span{display:block;height:100%;width:0;background:var(--error,#8c2f26)}",
      ".gate-done{font-weight:700}",
      "@media (prefers-reduced-motion: reduce){.gate-progress>span{transition:none}}",
    ].join("");
    document.head.appendChild(el("style", { id: "confirm-gate-style", text: css }));
  }

  function playful(level, serious, mild, silly) {
    if (level >= 4) return silly;
    if (level >= 2) return mild;
    return serious;
  }

  /**
   * @param {object} options
   *   title    - what the action is called
   *   detail   - EXACTLY what will be destroyed. Never styled, never omitted.
   *   confirm  - label for the finishing action
   *   onConfirm/onCancel
   *   anchor   - element focus returns to
   */
  function destructive(options) {
    var opts = options || {};
    if (open) close();
    styleOnce();

    var level = site.lang.funny("en");
    var keyA = false;
    var keyB = false;
    var finished = false;

    var slider = el("input", {
      type: "range",
      min: "0",
      max: "100",
      value: "0",
      class: "gate-slider",
      disabled: true,
      "aria-label": t(
        "Carry the slider all the way to confirm",
        "將個掣拉到盡先算確認"
      ),
    });
    var bar = el("div", { class: "gate-progress" }, el("span"));
    var status = el("p", { role: "status", class: "muted" });
    var doneLine = el("p", { class: "gate-done" });

    function refresh() {
      var both = keyA && keyB;
      slider.disabled = !both;
      if (!both) {
        slider.value = "0";
        bar.firstChild.style.width = "0%";
      }
      status.textContent = both
        ? t(
            "Both keys are turned. Carry the slider all the way across.",
            "兩條匙都扭咗。而家將個掣拉到最右。"
          )
        : t(
            "Turn both keys to arm the slider. " +
              (keyA || keyB ? "One to go." : "Neither is turned yet."),
            "扭晒兩條匙先開到個掣。" + (keyA || keyB ? "仲爭一條。" : "兩條都未扭。")
          );
    }

    function keyControl(label, onToggle) {
      var box = el("input", { type: "checkbox" });
      var id = "gate-key-" + Math.random().toString(36).slice(2, 8);
      box.id = id;
      box.addEventListener("change", function () {
        onToggle(box.checked);
        refresh();
      });
      return el("span", { class: "gate-key" }, box, el("label", {
        for: id,
        text: label,
      }));
    }

    slider.addEventListener("input", function () {
      var value = Number(slider.value);
      bar.firstChild.style.width = value + "%";
      if (value >= 100 && !finished) {
        finished = true;
        doneLine.textContent = playful(
          level,
          t("Authorized.", "已授權。"),
          t("Authorized. No going back now.", "已授權，冇得返轉頭。"),
          t(
            "Authorized. The deed is done and the deed was yours.",
            "已授權。做咗喇，係你自己㩒㗎。"
          )
        );
        slider.disabled = true;
        window.setTimeout(function () {
          close();
          if (typeof opts.onConfirm === "function") opts.onConfirm();
        }, 350);
      }
    });
    /* A slider released before the end springs back rather than latching, so
     * a half-drag can never be mistaken for consent. */
    slider.addEventListener("change", function () {
      if (!finished && Number(slider.value) < 100) {
        slider.value = "0";
        bar.firstChild.style.width = "0%";
      }
    });

    var gate = el(
      "div",
      {
        class: "gate",
        role: "dialog",
        "aria-modal": "true",
        "aria-labelledby": "gate-title",
        "aria-describedby": "gate-detail",
      },
      el("h2", {
        id: "gate-title",
        text:
          site.lang.emoji("⚠️") +
          (opts.title || t("Destructive action", "破壞性操作")),
      }),
      /* The facts. Not styled by the funny level, at any level. */
      el("div", { class: "gate-facts" }, el("p", {
        id: "gate-detail",
        text: opts.detail || t(
          "This cannot be undone.",
          "呢個操作撤銷唔到。"
        ),
      })),
      el("p", {
        text: playful(
          level,
          t("Turn both keys, then carry the slider across.", "扭兩條匙，再拉個掣。"),
          t(
            "Two keys and a slider. Yes, really.",
            "兩條匙加個掣。係，認真㗎。"
          ),
          t(
            "Two keys and a slider, like a submarine. We do not trust a single " +
              "click and neither should you.",
            "兩條匙加個掣，好似潛水艇咁。撳一下就算？信唔過，你都唔應該信。"
          )
        ),
      }),
      el(
        "div",
        { class: "gate-keys" },
        keyControl(t("Turn key one", "扭第一條匙"), function (on) {
          keyA = on;
        }),
        keyControl(t("Turn key two", "扭第二條匙"), function (on) {
          keyB = on;
        })
      ),
      status,
      slider,
      bar,
      doneLine,
      el(
        "div",
        { class: "row-actions" },
        el("button", {
          class: "button button-text",
          type: "button",
          id: "gate-exit",
          text: t("Emergency exit", "緊急離開"),
          onClick: function () {
            close();
            if (typeof opts.onCancel === "function") opts.onCancel();
          },
        })
      )
    );

    var backdrop = el(
      "div",
      {
        class: "gate-backdrop",
        onClick: function (event) {
          if (event.target === backdrop) {
            close();
            if (typeof opts.onCancel === "function") opts.onCancel();
          }
        },
      },
      gate
    );

    backdrop.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        close();
        if (typeof opts.onCancel === "function") opts.onCancel();
      }
    });

    document.body.appendChild(backdrop);
    open = { backdrop: backdrop, anchor: opts.anchor || document.activeElement };
    refresh();
    var first = gate.querySelector("input[type=checkbox]");
    if (first) first.focus();
  }

  function close() {
    if (!open) return;
    if (open.backdrop.parentNode) {
      open.backdrop.parentNode.removeChild(open.backdrop);
    }
    var anchor = open.anchor;
    open = null;
    if (anchor && typeof anchor.focus === "function") {
      try {
        anchor.focus();
      } catch (error) {
        /* an anchor that has since left the page is not an error */
      }
    }
  }

  site.confirmDestructive = destructive;
  window.AmuletConfirm = { destructive: destructive, close: close, isOpen: function () {
    return !!open;
  } };
})();
