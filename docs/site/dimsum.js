/* The startup dim sum surprise.
 *
 * One draw per page load, ten percent, never twice, never blocking. The draw is
 * taken once whether or not the dish can be shown, so a suppressed load spends
 * its chance rather than saving it up for a second attempt later.
 *
 * There is no photograph here and that is deliberate, not a broken image. This
 * bundle may fetch nothing from another origin (scripts/verify_site_offline_assets.py
 * fails the build on it) and this project may not vendor or generate dim sum
 * photographs, so the card names the dish in both languages and links to the
 * public catalogue where the pictures actually live. The card says as much in
 * one line, because a reader who is told nothing assumes an image failed.
 *
 * Nothing here is persisted and no setting turns it off: the draw is fresh each
 * load, so there is no state worth keeping between them.
 */
(function () {
  "use strict";

  var site = window.AmuletSite;
  if (!site) return;

  var el = site.el;
  var lang = site.lang;
  var settings = site.settings;

  var CATALOGUE_URL = "https://github.com/Ding-Ding-Projects/dim-sum-photos";
  var CHANCE = 0.1;
  var DWELL_MS = 11000; // long enough to read the name, the line, and reach the link
  var START_DELAY_MS = 1600;
  var LEAVE_MS = 180;

  /* Real dishes with their real Traditional Chinese names. Bundled rather than
   * fetched: the catalogue is remote, and a dish invented offline would be a
   * fact this page got wrong for the sake of a decoration. */
  var DISHES = [
    {
      en: "Shrimp dumpling",
      zh: "蝦餃",
      roman: "har gow",
      note: {
        en: "Pleated wheat-starch skin around whole prawns, steamed.",
        yue: "澄麵皮包住原隻蝦，蒸熟。",
      },
    },
    {
      en: "Pork and shrimp dumpling",
      zh: "燒賣",
      roman: "siu mai",
      note: {
        en: "Open-topped pork and prawn dumpling, usually crowned with roe.",
        yue: "無蓋嘅豬肉蝦肉餃，面頭通常擺蟹籽。",
      },
    },
    {
      en: "Barbecue pork bun",
      zh: "叉燒包",
      roman: "char siu bao",
      note: {
        en: "Steamed bun that splits open over sweet roast pork.",
        yue: "蒸到爆口嘅包，入面係甜叉燒。",
      },
    },
    {
      en: "Baked barbecue pork bun",
      zh: "焗叉燒包",
      note: {
        en: "The baked cousin, with a crisp sugared top over the same roast pork.",
        yue: "焗版嘅叉燒包，面頭一層脆糖。",
      },
    },
    {
      en: "Rice noodle roll",
      zh: "腸粉",
      roman: "cheung fun",
      note: {
        en: "Silky rice sheets rolled around prawn, beef or roast pork, with sweet soy.",
        yue: "滑米漿皮捲住蝦、牛肉或者叉燒，淋豉油。",
      },
    },
    {
      en: "Steamed pork ribs in black bean sauce",
      zh: "豉汁蒸排骨",
      note: {
        en: "Bite-sized ribs steamed with fermented black bean and garlic.",
        yue: "細件排骨用豆豉同蒜蒸。",
      },
    },
    {
      en: "Chicken feet in black bean sauce",
      zh: "鳳爪",
      note: {
        en: "Fried, braised, then steamed. Eaten with your fingers.",
        yue: "先炸後炆再蒸，用手拎住食。",
      },
    },
    {
      en: "Egg tart",
      zh: "蛋撻",
      roman: "dan tat",
      note: {
        en: "Custard set in pastry, best while the tin is still warm.",
        yue: "蛋漿焗成，趁熱食最好。",
      },
    },
    {
      en: "Custard bun",
      zh: "奶黃包",
      roman: "nai wong bao",
      note: {
        en: "Steamed bun with a sweet salted-egg-yolk custard centre.",
        yue: "蒸包，入面係咸蛋黃奶黃餡。",
      },
    },
    {
      en: "Sticky rice in lotus leaf",
      zh: "糯米雞",
      roman: "lo mai gai",
      note: {
        en: "Glutinous rice, chicken and mushroom steamed inside a lotus leaf.",
        yue: "糯米、雞肉同冬菇用荷葉包住蒸。",
      },
    },
    {
      en: "Turnip cake",
      zh: "蘿蔔糕",
      roman: "lo bak gou",
      note: {
        en: "Steamed daikon cake, pan-fried until the edges crisp.",
        yue: "白蘿蔔蒸成糕，再煎到四邊金黃。",
      },
    },
    {
      en: "Deep-fried taro dumpling",
      zh: "芋角",
      roman: "wu gok",
      note: {
        en: "Mashed taro fried into a lacy shell around minced pork.",
        yue: "芋泥炸出蜂巢皮，入面係豬肉餡。",
      },
    },
    {
      en: "Spring roll",
      zh: "春卷",
      roman: "chun kuen",
      note: {
        en: "Thin pastry rolled around a savoury filling and deep-fried.",
        yue: "薄皮捲住餡料，落鑊炸到金黃。",
      },
    },
    {
      en: "Fried glutinous rice dumpling",
      zh: "鹹水角",
      roman: "ham sui gok",
      note: {
        en: "Chewy glutinous-rice dough, deep-fried, with a savoury pork filling.",
        yue: "糯米皮炸香，入面係鹹豬肉餡。",
      },
    },
    {
      en: "Malay sponge cake",
      zh: "馬拉糕",
      roman: "ma lai gou",
      note: {
        en: "Steamed brown-sugar sponge, airy the whole way through.",
        yue: "黃糖蒸糕，鬆軟通透。",
      },
    },
    {
      en: "Steamed beef ball",
      zh: "山竹牛肉球",
      note: {
        en: "Beef balls steamed on bean-curd skin, eaten with Worcestershire sauce.",
        yue: "牛肉球墊住腐皮蒸，點喼汁食。",
      },
    },
    {
      en: "Bean-curd skin roll",
      zh: "鮮竹卷",
      roman: "sin juk kuen",
      note: {
        en: "Bean-curd skin wrapped around pork and steamed in oyster sauce.",
        yue: "腐皮捲住豬肉餡，蠔油汁蒸。",
      },
    },
    {
      en: "Chiu Chow dumpling",
      zh: "潮州粉果",
      roman: "fun gor",
      note: {
        en: "Translucent skin over peanut, pork and garlic chives.",
        yue: "半透明嘅粉果皮，入面有花生、豬肉同韭菜。",
      },
    },
    {
      en: "Water chestnut cake",
      zh: "馬蹄糕",
      roman: "ma tai gou",
      note: {
        en: "Translucent sweet cake, crunchy with water chestnut.",
        yue: "透明嘅甜糕，咬落有馬蹄嘅爽脆。",
      },
    },
    {
      en: "Sesame ball",
      zh: "煎堆",
      roman: "jin deui",
      note: {
        en: "Sesame-crusted glutinous ball, hollow and chewy, deep-fried.",
        yue: "芝麻裹住嘅糯米球，炸到脆，中間空心。",
      },
    },
    {
      en: "Mango pudding",
      zh: "芒果布甸",
      note: {
        en: "Cold set mango pudding, usually poured with evaporated milk.",
        yue: "凍身芒果布甸，通常淋淡奶。",
      },
    },
  ];

  // ------------------------------------------------------------------- copy
  function t(en, yue) {
    return lang.t(en, yue);
  }

  function variant(list, level) {
    var index = level <= 1 ? 0 : level <= 3 ? 1 : 2;
    return list[index] || list[list.length - 1] || "";
  }

  /* Voice only. The dish names, the count and the reason there is no photograph
   * read identically at every level. */
  function graded(en, yue) {
    return lang.t(variant(en, lang.funny("en")), variant(yue, lang.funny("yue")));
  }

  function headline() {
    return graded(
      [
        "Dim sum surprise",
        "Dim sum surprise — one dish, drawn at random.",
        "Dim sum surprise — the trolley stopped at your table.",
      ],
      [
        "點心驚喜",
        "點心驚喜 — 隨機抽咗一款。",
        "點心驚喜 — 架點心車啱啱停咗喺你檯邊。",
      ]
    );
  }

  function dishName(dish) {
    return dish.en + " · " + dish.zh;
  }

  // ----------------------------------------------------------- school mode
  /* school-mode.js owns the switch; this only reads it. Settings are the source
   * of truth and both shapes the flag could reasonably take are accepted, so a
   * page without that module simply reads as off.
   *
   * The store is consulted only when settings say nothing at all, and that
   * fallback is not defensive padding: site-core.js hydrates a stored settings
   * key only when it appears in its own DEFAULTS, so a school-mode flag written
   * through settings.set is dropped on the next load. Suppression that depended
   * on that would look correct in a live session and quietly never fire again
   * after a reload -- the one failure this surface must not have. */
  var SCHOOL_KEYS = ["schoolMode", "school", "school-mode", "schoolModeEnabled"];

  function flagged(value) {
    if (value === true) return true;
    return !!(value && typeof value === "object" && value.enabled === true);
  }

  function readFlag(read) {
    var known = false;
    for (var i = 0; i < SCHOOL_KEYS.length; i++) {
      var value = read(SCHOOL_KEYS[i]);
      if (value === undefined || value === null) continue;
      known = true;
      if (flagged(value)) return { known: true, on: true };
    }
    return { known: known, on: false };
  }

  function schoolModeOn() {
    var live = readFlag(function (key) {
      return settings.get(key);
    });
    // An explicit off in settings is an answer, and outranks a stale store.
    if (live.on || live.known) return live.on;
    return readFlag(function (key) {
      return site.store.get(key, null);
    }).on;
  }

  // ---------------------------------------------------------------- motion
  function reducedMotion() {
    if (settings.get("reducedMotion") === true) return true;
    try {
      return !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
    } catch (error) {
      return false;
    }
  }

  // ----------------------------------------------------------------- style
  var STYLE_ID = "dimsum-style";
  var CSS = [
    "#dimsum-region{position:fixed;left:16px;bottom:16px;z-index:70;display:grid;gap:10px;",
    "width:min(360px,calc(100vw - 32px));pointer-events:none}",
    ".dimsum-card{position:relative;display:grid;gap:6px;padding:14px 46px 14px 14px;",
    "border:1px solid var(--outline);border-left:4px solid var(--primary);border-radius:var(--r-md,16px);",
    "background:var(--surface-bright);color:var(--on-surface);box-shadow:var(--shadow-3);pointer-events:auto}",
    '.dimsum-card[data-motion="animate"]{animation:dimsum-in var(--motion-slow,240ms) var(--ease,ease) both}',
    ".dimsum-card.is-leaving{opacity:0;transition:opacity 160ms var(--ease,ease)}",
    ".dimsum-eyebrow{margin:0;color:var(--secondary);font-size:.78rem;font-weight:650}",
    ".dimsum-glyph{margin-right:6px}",
    ".dimsum-name{margin:0;font-size:1.02rem;line-height:1.35;overflow-wrap:anywhere}",
    ".dimsum-name strong{font-weight:700}",
    ".dimsum-roman{color:var(--on-surface-variant);font-size:.82rem;font-weight:400}",
    ".dimsum-note,.dimsum-why{margin:0;color:var(--on-surface-variant);font-size:.85rem;overflow-wrap:anywhere}",
    ".dimsum-why{font-size:.79rem}",
    ".dimsum-link{justify-self:start;min-height:40px;padding:0 12px;font-size:.85rem;text-decoration:none}",
    ".dimsum-dismiss{position:absolute;top:8px;right:8px}",
    ".dimsum-card :focus-visible{outline:3px solid var(--primary);outline-offset:2px}",
    "@keyframes dimsum-in{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}",
    "@media (max-width:520px){#dimsum-region{left:16px;right:16px;width:auto}}",
  ].join("");

  function installStyle() {
    if (document.getElementById(STYLE_ID)) return;
    var style = el("style", { id: STYLE_ID });
    style.textContent = CSS;
    (document.head || document.documentElement).appendChild(style);
  }

  // ---------------------------------------------------------------- surface
  var state = { dish: null, card: null, nodes: null, timer: 0, returnFocus: null };

  function region() {
    var found = document.getElementById("dimsum-region");
    if (found) return found;
    if (!document.body) return null;
    found = el("div", {
      id: "dimsum-region",
      role: "status",
      "aria-live": "polite",
      "aria-atomic": "true",
      "aria-label": t("Dim sum surprise", "點心驚喜"),
    });
    document.body.appendChild(found);
    return found;
  }

  function clearTimer() {
    if (!state.timer) return;
    clearTimeout(state.timer);
    state.timer = 0;
  }

  /* Reading is not idling: the countdown stops while the card is hovered or
   * holds focus, so a card cannot vanish mid-sentence or out from under a
   * keyboard user on their way to the link. */
  function arm() {
    clearTimer();
    state.timer = window.setTimeout(function () {
      dismiss(false);
    }, DWELL_MS);
  }

  function dismiss(immediate) {
    var card = state.card;
    if (!card) return;
    clearTimer();
    var back = state.returnFocus;
    var hadFocus = card.contains(document.activeElement);
    state.card = null;
    state.nodes = null;
    state.dish = null;
    state.returnFocus = null;

    var drop = function () {
      if (card.parentNode) card.parentNode.removeChild(card);
    };
    if (immediate || reducedMotion()) drop();
    else {
      card.classList.add("is-leaving");
      window.setTimeout(drop, LEAVE_MS);
    }

    // Removing the focused element drops focus to the document body, which
    // strands a keyboard user wherever the card used to be.
    if (hadFocus && back && document.contains(back) && typeof back.focus === "function") {
      back.focus();
    }
  }

  /** Somewhere focus can be sent back to. The body is not one. */
  function returnable(node) {
    if (!node || node.nodeType !== 1 || node === document.body) return null;
    return typeof node.focus === "function" ? node : null;
  }

  function nameChildren(dish) {
    var kids = [
      el("strong", { text: dish.en }),
      document.createTextNode(" · "),
      el("span", { lang: "zh-Hant", text: dish.zh }),
    ];
    if (dish.roman) {
      kids.push(el("small", { class: "dimsum-roman", text: " · " + dish.roman }));
    }
    return kids;
  }

  function paint() {
    var dish = state.dish;
    var nodes = state.nodes;
    if (!dish || !nodes) return;

    var host = document.getElementById("dimsum-region");
    if (host) host.setAttribute("aria-label", t("Dim sum surprise", "點心驚喜"));

    var glyph = lang.emoji("🥟").trim();
    var eyebrow = [];
    if (glyph) eyebrow.push(el("span", { class: "dimsum-glyph", "aria-hidden": "true", text: glyph }));
    eyebrow.push(document.createTextNode(headline()));
    nodes.eyebrow.replaceChildren.apply(nodes.eyebrow, eyebrow);

    // Both names, in every language mode: the dish is a fact, not a translation.
    nodes.name.replaceChildren.apply(nodes.name, nameChildren(dish));
    nodes.note.textContent = t(dish.note.en, dish.note.yue);
    nodes.why.textContent = t(
      "No photo here: this page loads nothing from another origin, and this project does not vendor dim sum photographs. The pictures live in the public catalogue.",
      "呢度冇相：呢一版唔會載入其他網站嘅嘢，呢個專案亦唔會自己收藏點心相。啲相喺公開目錄度。"
    );
    nodes.link.textContent = t("Open the public dim sum catalogue", "開啟公開點心目錄") + " ↗";
    nodes.link.setAttribute(
      "aria-label",
      t(
        "Open the public dim sum catalogue for " + dishName(dish) + ", in a new tab",
        "喺新分頁開啟公開點心目錄，睇" + dishName(dish)
      )
    );
    nodes.dismiss.setAttribute(
      "aria-label",
      t("Dismiss the dim sum surprise: " + dishName(dish), "關閉呢個點心驚喜：" + dishName(dish))
    );
  }

  function show(dish) {
    if (!dish || schoolModeOn()) return;
    var host = region();
    if (!host) return;
    // One surprise at a time. Sweeping the region rather than only the tracked
    // card matters: a dismissed card lingers for the length of its leave
    // animation, so a second one summoned inside that window would stack beside
    // a card the user has already closed.
    dismiss(true);
    var leftovers = host.querySelectorAll(".dimsum-card");
    for (var i = 0; i < leftovers.length; i++) {
      if (leftovers[i].parentNode) leftovers[i].parentNode.removeChild(leftovers[i]);
    }

    var eyebrow = el("p", { class: "dimsum-eyebrow" });
    var name = el("p", { class: "dimsum-name" });
    var note = el("p", { class: "dimsum-note" });
    var why = el("p", { class: "dimsum-why" });
    var link = el("a", {
      class: "button button-text dimsum-link",
      href: CATALOGUE_URL,
      target: "_blank",
      rel: "noreferrer",
    });
    var dismissButton = el("button", {
      class: "icon-button dimsum-dismiss",
      type: "button",
      text: "×",
      onclick: function () {
        dismiss(false);
      },
    });

    var card = el("div", { class: "dimsum-card" }, eyebrow, name, note, why, link, dismissButton);

    card.addEventListener("mouseenter", clearTimer);
    card.addEventListener("mouseleave", function () {
      if (state.card === card && !card.contains(document.activeElement)) arm();
    });
    card.addEventListener("focusin", function (event) {
      clearTimer();
      // relatedTarget is the better answer when the browser supplies one, but it
      // is not always populated, so the target captured at show time stands
      // rather than being overwritten with nothing.
      if (!card.contains(event.relatedTarget)) {
        state.returnFocus = returnable(event.relatedTarget) || state.returnFocus;
      }
    });
    card.addEventListener("focusout", function (event) {
      if (state.card === card && !card.contains(event.relatedTarget)) arm();
    });
    card.addEventListener("keydown", function (event) {
      if (event.key !== "Escape") return;
      // Focus is inside the card for this to fire, so nothing else on the page
      // should read this Escape as its own.
      event.stopPropagation();
      dismiss(false);
    });

    state.dish = dish;
    state.card = card;
    state.returnFocus = returnable(document.activeElement);
    state.nodes = {
      eyebrow: eyebrow,
      name: name,
      note: note,
      why: why,
      link: link,
      dismiss: dismissButton,
    };
    paint();
    if (!reducedMotion()) card.setAttribute("data-motion", "animate");
    host.appendChild(card);
    // Never focused on arrival: a surprise that grabs the caret interrupts
    // exactly the task it is not allowed to interrupt.
    arm();
  }

  // ------------------------------------------------------------------- draw
  var lastIndex = -1;

  function pick() {
    if (DISHES.length === 1) return DISHES[0];
    var index = Math.floor(Math.random() * DISHES.length);
    if (index === lastIndex) index = (index + 1) % DISHES.length;
    lastIndex = index;
    return DISHES[index];
  }

  function once(fn) {
    var spent = false;
    return function () {
      if (spent) return;
      spent = true;
      fn();
    };
  }

  /* A card shown behind a modal, or into a hidden tab, is a card nobody sees.
   * Waiting for the real event is bounded: no polling, and the caller is
   * spent-once so no path can present twice. */
  function whenPresentable(run) {
    if (document.hidden) {
      var onVisible = function () {
        document.removeEventListener("visibilitychange", onVisible);
        whenPresentable(run);
      };
      document.addEventListener("visibilitychange", onVisible);
      return;
    }
    var modal = document.querySelector("dialog[open]");
    if (modal) {
      var onClose = function () {
        modal.removeEventListener("close", onClose);
        whenPresentable(run);
      };
      modal.addEventListener("close", onClose);
      return;
    }
    run();
  }

  var drawn = false;

  function drawOnce() {
    if (drawn) return;
    // Spent whether or not it wins and whether or not it can be shown: a draw
    // held back would make the next one better than one in ten.
    drawn = true;
    if (schoolModeOn()) return;
    if (Math.random() >= CHANCE) return;
    var dish = pick();
    window.setTimeout(
      once(function () {
        whenPresentable(
          once(function () {
            if (schoolModeOn()) return; // it may have been switched on while we waited
            show(dish);
          })
        );
      }),
      START_DELAY_MS
    );
  }

  // ------------------------------------------------------------------- boot
  site.ready(function () {
    installStyle();
    region();
    drawOnce();
  });

  settings.onChange(function (key) {
    if (schoolModeOn()) {
      dismiss(true);
      return;
    }
    if (
      key === null ||
      key === "language" ||
      key === "emoji" ||
      key === "funnyEn" ||
      key === "funnyYue"
    ) {
      paint();
    }
  });

  // ---------------------------------------------------------------- palette
  /* One in ten is untestable by hand, so the palette can summon a dish on
   * demand. It is a second route to the same surface, not a second draw. */
  site.registerPaletteSource(function () {
    if (schoolModeOn()) return [];
    var title = t("Show a dim sum dish", "即刻顯示一款點心");
    var detail = t(
      DISHES.length +
        " dishes ship with this page, and one page load in ten shows one on its own. This shows one now.",
      "呢一版夾帶咗 " + DISHES.length + " 款點心，每十次載入會自己彈一次。撳呢度即刻睇一款。"
    );
    var run = function () {
      show(pick());
    };
    return [
      {
        id: "dimsum:show",
        kind: "command",
        section: t("Dim sum", "點心"),
        group: t("Dim sum", "點心"),
        title: title,
        label: title,
        subtitle: detail,
        detail: detail,
        hint: detail,
        run: run,
        action: run,
      },
    ];
  });
})();
