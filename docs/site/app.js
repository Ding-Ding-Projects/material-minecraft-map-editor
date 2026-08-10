/* Integrator for the Material Minecraft World Editor site.
 *
 * Loads last, and owns only the wiring no single module can: pushing the stored
 * settings onto the document, gating the download behind a verified manifest,
 * driving the shared context menu, and the page-level affordances (skip link,
 * tab links, footer inventory).
 *
 * Nothing here assumes a sibling module loaded. A page missing one script should
 * lose that one feature, not stop rendering, so every lookup is guarded.
 */
(function () {
  "use strict";

  var doc = document;
  var root = doc.documentElement;

  // Enough of the runtime to keep this file working when site-core.js is absent.
  var site = window.AmuletSite || {
    data: window.AMULET_SITE_DATA || {},
    lang: {
      mode: function () {
        return "english";
      },
      t: function (en) {
        return en;
      },
      funny: function () {
        return 1;
      },
      emoji: function () {
        return "";
      },
    },
    settings: {
      all: function () {
        return {};
      },
      get: function () {
        return undefined;
      },
      reset: function () {},
      onChange: function () {},
    },
    showTab: function () {},
    notify: function () {},
    ready: function (fn) {
      if (doc.readyState === "loading") doc.addEventListener("DOMContentLoaded", fn);
      else fn();
    },
  };

  function byId(id) {
    return doc.getElementById(id);
  }

  function t(en, yue) {
    return site.lang.t(en, yue);
  }

  function notify(title, body) {
    try {
      site.notify(title, body);
    } catch (error) {
      /* a refused notification is not a reason to abandon the action */
    }
  }

  // ------------------------------------------------------------------- copy
  // The fact sentence is byte-identical at every funny level and in both
  // languages; only the lead in front of it changes voice.
  var HERO_FACTS_EN =
    "Open Minecraft worlds outside the game to inspect terrain, select precise regions, " +
    "move builds between worlds, run block and biome operations, import or export structures, " +
    "delete or regenerate chunks, and convert world data. Java Edition 1.12+ and Bedrock " +
    "Edition 1.7+, on a Material Design 3 shell.";
  var HERO_FACTS_YUE =
    "喺遊戲以外開啟 Minecraft 世界，檢視地形、精準選取範圍、將建築搬去另一個世界、" +
    "執行方塊同生態系操作、匯入或匯出結構、刪除或重新生成區塊，以及轉換世界資料。" +
    "支援 Java Edition 1.12+ 同 Bedrock Edition 1.7+，行 Material Design 3 外殼。";
  var HERO_LEAD_EN = [
    "",
    "In plain terms: ",
    "No launcher, no guesswork, no mods required. ",
    "Your world, up on the workbench instead of under your feet. ",
    "Pop the world open like a geode, then put every block back exactly where you meant it. ",
  ];
  var HERO_LEAD_YUE = [
    "",
    "簡單講：",
    "唔使開遊戲，唔使估，唔使裝模組。",
    "將個世界搬上工作枱，唔使企喺上面慢慢挖。",
    "好似劈開水晶石咁劈開個世界，再逐粒方塊擺返啱位。",
  ];

  var SETTINGS_FACTS_EN =
    "Preferences persist in this browser and apply immediately. Funny levels style the " +
    "surrounding copy; facts and links stay exact.";
  var SETTINGS_FACTS_YUE =
    "偏好設定會保存喺呢個瀏覽器並即時生效。搞笑程度只影響周圍嘅文字語氣；資料同連結一律保持準確。";
  var SETTINGS_LEAD_EN = [
    "",
    "Every control here is wired to something real. ",
    "Nothing on this page is a painted-on switch. ",
    "Turn every knob you can find; none of them are decorative. ",
    "Twist every dial until the site looks like yours — it will still tell you the truth. ",
  ];
  var SETTINGS_LEAD_YUE = [
    "",
    "呢度每個控制項都真係駁咗線。",
    "呢一頁冇一個掣係擺設。",
    "見到掣就扭，冇一個係畫上去嘅。",
    "扭到成個網站似返你自己，佢照舊照直講事實。",
  ];

  function voiced(leads, facts, level, glyph) {
    var index = Math.max(1, Math.min(5, Number(level) || 1)) - 1;
    var decoration = index >= 3 ? site.lang.emoji(glyph) : "";
    return decoration + (leads[index] || "") + facts;
  }

  function applyVoice() {
    var hero = byId("hero-copy");
    if (hero) {
      hero.textContent = t(
        voiced(HERO_LEAD_EN, HERO_FACTS_EN, site.lang.funny("en"), "🧱"),
        voiced(HERO_LEAD_YUE, HERO_FACTS_YUE, site.lang.funny("yue"), "🧱")
      );
    }
    var settingsCopy = byId("settings-copy");
    if (settingsCopy) {
      settingsCopy.textContent = t(
        voiced(SETTINGS_LEAD_EN, SETTINGS_FACTS_EN, site.lang.funny("en"), "🎛"),
        voiced(SETTINGS_LEAD_YUE, SETTINGS_FACTS_YUE, site.lang.funny("yue"), "🎛")
      );
    }
  }

  // --------------------------------------------------------------- settings
  var THEME_QUERY =
    typeof window.matchMedia === "function"
      ? window.matchMedia("(prefers-color-scheme: dark)")
      : null;

  function resolvedTheme(value) {
    if (value === "dark" || value === "light") return value;
    // "system" is not a third appearance; it is a subscription to the OS one.
    return THEME_QUERY && THEME_QUERY.matches ? "dark" : "light";
  }

  function cssFont(value) {
    var family = String(value == null ? "" : value).trim();
    if (!family) return "system-ui";
    // An unquoted family containing a space is not a valid font-family token, so
    // a stored "Segoe UI" would silently fall through to the next stack entry.
    if (/\s/.test(family) && !/["',]/.test(family)) return '"' + family + '"';
    return family;
  }

  function applyBrand(all) {
    var brand = String(all.brand == null ? "" : all.brand).trim();
    if (!brand) brand = "Material Minecraft World Editor";
    var label = byId("brand-label");
    var footerBrand = byId("footer-brand");
    if (label) label.textContent = brand;
    if (footerBrand) footerBrand.textContent = brand;
    doc.title = brand + " · " + t("Shape worlds, keep the wonder", "塑造世界，保留驚喜");
    var link = label && label.closest ? label.closest(".brand") : null;
    if (link) link.setAttribute("aria-label", t(brand + " home", brand + " 首頁"));
  }

  function applySettings() {
    var all = site.settings.all ? site.settings.all() : {};

    var theme = resolvedTheme(all.theme);
    root.setAttribute("data-theme", theme);
    // The shipped stylesheet still keys its dark palette off a class. The
    // attribute is the contract; the class keeps that stylesheet working.
    if (root.classList) root.classList.toggle("dark", theme === "dark");
    root.style.colorScheme = theme;

    root.setAttribute("data-density", String(all.density || "comfortable"));

    if (/^#[0-9a-fA-F]{6}$/.test(String(all.accent || ""))) {
      root.style.setProperty("--primary", String(all.accent).toLowerCase());
    }

    var scale = Number(all.scale);
    if (isFinite(scale) && scale > 0) {
      root.style.setProperty("--ui-scale", String(scale / 100));
    }

    root.style.setProperty("--site-font", cssFont(all.font));

    if (all.reducedMotion) root.setAttribute("data-reduced-motion", "true");
    else root.removeAttribute("data-reduced-motion");

    root.lang = site.lang.mode() === "cantonese" ? "zh-Hant" : "en";

    applyBrand(all);
    applyVoice();
    applyReleaseCopy();
    applyFooterCount();
  }

  // ------------------------------------------------------------ footer count
  function counted(value, one, many) {
    return value + " " + (value === 1 ? one : many);
  }

  function applyFooterCount() {
    var node = byId("footer-count");
    if (!node) return;
    var data = window.AMULET_SITE_DATA || site.data || {};
    var features = Array.isArray(data.features) ? data.features.length : 0;
    var categories = Array.isArray(data.categories) ? data.categories.length : 0;
    var commands = Array.isArray(data.commands) ? data.commands.length : 0;
    var shots = Array.isArray(data.shots) ? data.shots.length : 0;
    node.textContent = t(
      counted(features, "documented feature", "documented features") +
        " · " +
        counted(categories, "category", "categories") +
        " · " +
        counted(commands, "build command", "build commands") +
        " · " +
        counted(shots, "verified capture", "verified captures"),
      features +
        " 項功能文件 · " +
        categories +
        " 個分類 · " +
        commands +
        " 個建置指令 · " +
        shots +
        " 張已核實截圖"
    );
  }

  // ----------------------------------------------------------- release gate
  // safePublicationUrl and verifiedManifest are carried over unchanged: a
  // committed test asserts both by name, and the whole point of the gate is that
  // its acceptance rule never quietly loosens.
  function safePublicationUrl(value, releaseTag, assetName) {
    try {
      const url = new URL(value);
      if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash) return null;
      if (!url.pathname.endsWith('/' + assetName) || !url.pathname.includes('/download/' + releaseTag + '/')) return null;
      return url.href;
    } catch (_error) {
      return null;
    }
  }

  function verifiedManifest(manifest) {
    if (manifest?.schemaVersion !== 1 || manifest.verified !== true || !/^[0-9a-f]{40}$/i.test(String(manifest.commit || ''))) return false;
    const tag = String(manifest.releaseTag || '');
    if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(tag)) return false;
    return ['Setup.exe','RELEASES','full.nupkg'].every(key => {
      const asset = manifest.assets?.[key];
      if (!asset || typeof asset.sha256 !== 'string' || !/^[0-9a-f]{64}$/i.test(asset.sha256)) return false;
      const name = key === 'full.nupkg' ? String(asset.name || '') : key;
      return key === 'full.nupkg'
        ? name.endsWith('-full.nupkg') && safePublicationUrl(asset.url, tag, name) !== null
        : asset.name === key && safePublicationUrl(asset.url, tag, key) !== null;
    });
  }

  var releaseState = null;

  function revealDownload(button, url, label) {
    if (!button) return;
    button.href = url;
    button.target = "_blank";
    button.rel = "noreferrer";
    // Verified, this button leaves the site; it must stop acting as a tab link.
    button.removeAttribute("data-tab-link");
    button.textContent = label + " ↗";
    button.hidden = false;
  }

  function applyReleaseCopy() {
    var heroButton = byId("hero-download");
    var cardButton = byId("release-download");
    if (!releaseState) {
      if (heroButton) heroButton.hidden = true;
      if (cardButton) cardButton.hidden = true;
      return;
    }

    var tag = releaseState.tag;
    var eyebrow = byId("release-eyebrow");
    var title = byId("release-title");
    var copy = byId("release-copy");
    if (eyebrow) {
      eyebrow.textContent = t(
        "VERIFIED WINDOWS BUILD · " + tag,
        "已核實 WINDOWS 版本 · " + tag
      );
    }
    if (title) {
      title.textContent = t("Verified installer · " + tag, "已核實安裝檔 · " + tag);
    }
    if (copy) {
      copy.textContent = t(
        "The local release manifest records tag " +
          tag +
          " with a SHA-256 digest for Setup.exe, RELEASES, and the full .nupkg. The installer " +
          "is an unsigned Squirrel.Windows package, so Windows may warn about an unknown publisher.",
        "本機發佈清單記錄咗版本 " +
          tag +
          "，連 Setup.exe、RELEASES 同完整 .nupkg 嘅 SHA-256 雜湊值。安裝檔係未簽署嘅 " +
          "Squirrel.Windows 套件，所以 Windows 可能會顯示不明發佈者警告。"
      );
    }
    revealDownload(
      heroButton,
      releaseState.url,
      t("Download " + tag + " · Setup.exe", "下載 " + tag + " · Setup.exe")
    );
    revealDownload(
      cardButton,
      releaseState.url,
      t("Download Setup.exe · " + tag, "下載 Setup.exe · " + tag)
    );
  }

  function loadPublicationManifest() {
    if (typeof window.fetch !== "function") return;
    var options = { cache: "no-store" };
    window
      .fetch(new URL("site-config.json", doc.baseURI), options)
      .then(function (response) {
        if (!response.ok) throw new Error("site config unavailable");
        return response.json();
      })
      .then(function (config) {
        var base = new URL((config && config.baseUrl) || "./", doc.baseURI);
        root.dataset.baseUrl = base.href;
        var manifestUrl = new URL(
          (config && config.releaseManifest) || "./release-manifest.json",
          base
        );
        return window.fetch(manifestUrl, options);
      })
      .then(function (response) {
        if (!response.ok) throw new Error("release manifest unavailable");
        return response.json();
      })
      .then(function (manifest) {
        if (!verifiedManifest(manifest)) throw new Error("release assets are not verified");
        var tag = String(manifest.releaseTag || "");
        var url = safePublicationUrl(manifest.assets["Setup.exe"].url, tag, "Setup.exe");
        if (!url) throw new Error("immutable Setup.exe asset is not verified");
        releaseState = { tag: tag, url: url };
        applyReleaseCopy();
      })
      .catch(function () {
        // Nothing proven, so nothing offered: the authored pending copy stands.
        releaseState = null;
        applyReleaseCopy();
      });
  }

  // ------------------------------------------------------------ context menu
  var menu = null;
  var menuOpener = null;
  var menuPainted = false;
  var menuNeedsOwnPaint = false;

  function menuElement() {
    if (!menu) menu = byId("context-menu");
    return menu;
  }

  function menuItemNodes() {
    if (!menu) return [];
    return Array.prototype.slice.call(menu.querySelectorAll('[role="menuitem"]'));
  }

  function focusItem(index) {
    var nodes = menuItemNodes();
    if (!nodes.length) return;
    var target = nodes[(index + nodes.length) % nodes.length];
    if (target) target.focus();
  }

  function currentItemIndex() {
    var nodes = menuItemNodes();
    for (var i = 0; i < nodes.length; i++) {
      if (nodes[i] === doc.activeElement) return i;
    }
    return -1;
  }

  function onMenuKey(event) {
    if (!menu || menu.hidden) return;
    var key = event.key;
    if (key === "Escape") {
      event.preventDefault();
      closeMenu(true);
      return;
    }
    if (key === "Tab") {
      // Focus is restored first, so Tab continues from the opener as expected.
      closeMenu(true);
      return;
    }
    if (key === "ArrowDown" || key === "ArrowUp" || key === "Home" || key === "End") {
      event.preventDefault();
      var nodes = menuItemNodes();
      if (!nodes.length) return;
      if (key === "Home") focusItem(0);
      else if (key === "End") focusItem(nodes.length - 1);
      else focusItem(currentItemIndex() + (key === "ArrowDown" ? 1 : -1));
    }
  }

  function onOutsidePointer(event) {
    if (!menu || menu.hidden) return;
    if (!menu.contains(event.target)) closeMenu(false);
  }

  function onViewportChange(event) {
    if (!menu || menu.hidden) return;
    if (event && event.target && menu.contains(event.target)) return;
    closeMenu(false);
  }

  function closeMenu(restoreFocus) {
    if (!menu || menu.hidden) return;
    menu.hidden = true;
    while (menu.firstChild) menu.removeChild(menu.firstChild);
    doc.removeEventListener("pointerdown", onOutsidePointer, true);
    doc.removeEventListener("keydown", onMenuKey, true);
    window.removeEventListener("resize", onViewportChange, true);
    window.removeEventListener("scroll", onViewportChange, true);
    var opener = menuOpener;
    menuOpener = null;
    if (restoreFocus !== false && opener && typeof opener.focus === "function") {
      try {
        opener.focus();
      } catch (error) {
        /* a detached opener simply cannot take focus back */
      }
    }
  }

  function normalizeItem(item) {
    if (!item) return null;
    if (item === "-" || item.separator === true || item.type === "separator") {
      return { separator: true };
    }
    var label = item.label || item.text || item.title || item.name;
    var run = item.onSelect || item.action || item.run || item.onClick || item.select;
    if (!label) return null;
    // An enabled item that cannot act is exactly the decorative control this
    // site refuses to ship, so it is dropped rather than drawn.
    if (!item.disabled && typeof run !== "function") return null;
    return {
      label: String(label),
      shortcut: String(item.shortcut || item.keys || item.accelerator || ""),
      disabled: Boolean(item.disabled),
      reason: String(item.disabledReason || item.reason || ""),
      run: typeof run === "function" ? run : null,
    };
  }

  function tidySeparators(items) {
    var out = [];
    items.forEach(function (item) {
      if (item.separator && (!out.length || out[out.length - 1].separator)) return;
      out.push(item);
    });
    while (out.length && out[out.length - 1].separator) out.pop();
    return out;
  }

  function paintItem(node) {
    node.style.display = "flex";
    node.style.alignItems = "center";
    node.style.justifyContent = "space-between";
    node.style.gap = "24px";
    node.style.width = "100%";
    node.style.minHeight = "40px";
    node.style.padding = "0 12px";
    node.style.border = "0";
    node.style.borderRadius = "8px";
    node.style.background = "transparent";
    node.style.color = "inherit";
    node.style.font = "inherit";
    node.style.textAlign = "left";
    node.style.cursor = "pointer";
  }

  function buildItemNode(item) {
    if (item.separator) {
      var rule = doc.createElement("div");
      rule.className = "menu-separator";
      rule.setAttribute("role", "separator");
      if (menuNeedsOwnPaint) {
        rule.style.height = "1px";
        rule.style.margin = "4px 8px";
        rule.style.background = "var(--outline-variant, #c7c6d0)";
      }
      return rule;
    }

    var button = doc.createElement("button");
    button.type = "button";
    button.className = "menu-item";
    button.setAttribute("role", "menuitem");
    button.tabIndex = -1;

    var label = doc.createElement("span");
    label.className = "menu-label";
    label.textContent = item.label;
    button.appendChild(label);

    if (item.shortcut) {
      var keys = doc.createElement("span");
      keys.className = "menu-shortcut";
      // The accessible name below already carries the keys; announcing the
      // visible copy as well would read them out twice.
      keys.setAttribute("aria-hidden", "true");
      keys.textContent = item.shortcut;
      if (menuNeedsOwnPaint) {
        keys.style.marginLeft = "auto";
        keys.style.opacity = ".72";
        keys.style.fontVariantNumeric = "tabular-nums";
      }
      button.appendChild(keys);
    }

    var name = item.label + (item.shortcut ? " (" + item.shortcut + ")" : "");
    if (item.disabled) {
      // Kept focusable so keyboard users can read why it is unavailable.
      button.setAttribute("aria-disabled", "true");
      if (item.reason) {
        name += " — " + item.reason;
        button.title = item.reason;
      }
      if (menuNeedsOwnPaint) button.style.opacity = ".55";
    }
    button.setAttribute("aria-label", name);

    if (menuNeedsOwnPaint) paintItem(button);

    button.addEventListener("click", function () {
      if (item.disabled) return;
      closeMenu(true);
      try {
        item.run();
      } catch (error) {
        notify(
          t("That action failed", "呢個動作失敗咗"),
          String((error && error.message) || error)
        );
      }
    });
    return button;
  }

  function ensureMenuSurface() {
    if (menuPainted) return;
    menuPainted = true;
    var computed = window.getComputedStyle ? window.getComputedStyle(menu) : null;
    var painted = computed ? computed.backgroundColor : "";
    menuNeedsOwnPaint =
      !painted || painted === "transparent" || /rgba\(\s*0,\s*0,\s*0,\s*0\s*\)/.test(painted);
    // A stylesheet that stacks this menu deliberately knows the rest of the
    // page's layers; only supply a value when it left none.
    if (!computed || !computed.zIndex || computed.zIndex === "auto") menu.style.zIndex = "90";
    if (!menuNeedsOwnPaint) return;
    // An overlay that renders transparent puts the page's own text straight
    // through its labels, so it paints itself when the stylesheet has not.
    menu.style.background = "var(--surface-container-high, #e9e7ee)";
    menu.style.color = "var(--on-surface, #1a1b20)";
    menu.style.border = "1px solid var(--outline-variant, #c7c6d0)";
    menu.style.borderRadius = "12px";
    menu.style.padding = "6px";
    menu.style.minWidth = "240px";
    menu.style.boxShadow = "0 12px 32px rgba(0, 0, 0, .28)";
  }

  function pointerPoint(event) {
    var x = event && typeof event.clientX === "number" ? event.clientX : -1;
    var y = event && typeof event.clientY === "number" ? event.clientY : -1;
    if (x > 0 || y > 0) return { x: x, y: y };
    // The context-menu key reports no pointer, so anchor on the element instead.
    var anchor =
      event && event.target && event.target.getBoundingClientRect ? event.target : menuOpener;
    if (anchor && anchor.getBoundingClientRect) {
      var box = anchor.getBoundingClientRect();
      return { x: box.left, y: box.bottom };
    }
    return { x: 16, y: 16 };
  }

  function boundMenuHeight(margin) {
    menu.style.maxHeight = "";
    menu.style.overflowY = "";
    var limit = window.innerHeight - margin * 2;
    var computed = window.getComputedStyle ? window.getComputedStyle(menu) : null;
    var declared = computed ? parseFloat(computed.maxHeight) : NaN;
    // Never tighten a stylesheet's own cap; only supply one when the overlay
    // would otherwise run off the bottom of the screen with nothing to scroll.
    if (!isFinite(declared) || declared > limit) {
      menu.style.maxHeight = limit + "px";
      menu.style.overflowY = "auto";
    }
  }

  function positionMenu(event) {
    var margin = 8;
    // The offsets below are viewport coordinates from the pointer, which only
    // stay true under fixed positioning once the page has been scrolled.
    menu.style.position = "fixed";
    menu.style.left = "0px";
    menu.style.top = "0px";
    boundMenuHeight(margin);
    var rect = menu.getBoundingClientRect();
    var point = pointerPoint(event);
    var left = Math.min(point.x, window.innerWidth - rect.width - margin);
    var top = Math.min(point.y, window.innerHeight - rect.height - margin);
    menu.style.left = Math.max(margin, left) + "px";
    menu.style.top = Math.max(margin, top) + "px";
  }

  function openerFor(event) {
    var active = doc.activeElement;
    if (active && active !== doc.body && active !== root) return active;
    var target = event && event.target;
    if (target && target.closest) {
      var focusable = target.closest("a[href], button, input, select, textarea, [tabindex]");
      if (focusable) return focusable;
    }
    return null;
  }

  function openContextMenu(items, event, label) {
    // A caller that swaps the arguments should not silently lose its menu.
    if (Array.isArray(event) && !Array.isArray(items)) {
      var swap = items;
      items = event;
      event = swap;
    }
    if (!menuElement() || !Array.isArray(items)) return null;

    var prepared = tidySeparators(
      items
        .map(normalizeItem)
        .filter(function (item) {
          return Boolean(item);
        })
    );
    if (!prepared.length) return null;

    if (event && typeof event.preventDefault === "function") event.preventDefault();
    closeMenu(false);
    menuOpener = openerFor(event);

    menu.hidden = false;
    ensureMenuSurface();
    menu.setAttribute("aria-label", String(label || t("Context menu", "右鍵選單")));
    prepared.forEach(function (item) {
      menu.appendChild(buildItemNode(item));
    });
    positionMenu(event);

    doc.addEventListener("pointerdown", onOutsidePointer, true);
    doc.addEventListener("keydown", onMenuKey, true);
    window.addEventListener("resize", onViewportChange, true);
    window.addEventListener("scroll", onViewportChange, true);
    focusItem(0);

    return {
      close: function () {
        closeMenu(true);
      },
    };
  }

  // ------------------------------------------------- default background menu
  function paletteOpener() {
    if (typeof site.openPalette === "function") {
      return function () {
        site.openPalette();
      };
    }
    var trigger = byId("palette-open");
    if (!trigger) return null;
    return function () {
      trigger.click();
    };
  }

  function resetSiteSettings() {
    var owned = byId("reset-site-settings");
    // The settings surface owns whatever confirmation and history a reset needs,
    // so route through its own control when it exists instead of duplicating it.
    if (owned) {
      owned.click();
      return;
    }
    site.settings.reset();
    notify(
      t("Site settings reset", "網站設定已重設"),
      t(
        "Language, funny levels, theme, density, accent, font, scale, and brand are back to " +
          "the values this site ships with.",
        "語言、搞笑程度、主題、密度、主色、字型、縮放同名稱全部回復到本網站出廠設定。"
      )
    );
  }

  function backgroundMenuItems() {
    var items = [];
    var openPalette = paletteOpener();
    if (openPalette) {
      items.push({
        label: t("Open command palette", "開啟指令面板"),
        shortcut: "Ctrl+Shift+F",
        onSelect: openPalette,
      });
    }
    var bell = byId("notif-open");
    if (bell) {
      items.push({
        label: t("Open notification history", "開啟通知記錄"),
        onSelect: function () {
          bell.click();
        },
      });
    }
    if (byId("settings") && typeof site.showTab === "function") {
      items.push({
        label: t("Go to settings", "前往設定"),
        onSelect: function () {
          site.showTab("settings");
        },
      });
    }
    if (site.settings && typeof site.settings.reset === "function") {
      items.push({ separator: true });
      items.push({
        label: t("Reset site settings", "重設網站設定"),
        onSelect: resetSiteSettings,
      });
    }
    return items;
  }

  function wireBackgroundMenu() {
    doc.addEventListener("contextmenu", function (event) {
      if (event.defaultPrevented) return; // another surface already claimed it
      var target = event.target;
      if (target && target.isContentEditable) return;
      if (target && target.closest && target.closest("input, textarea, select")) return;
      // With text selected the browser's own menu can copy it; this one cannot.
      if (window.getSelection && String(window.getSelection())) return;
      var items = backgroundMenuItems();
      if (!items.length) return;
      openContextMenu(items, event);
    });
  }

  // ------------------------------------------------- page-level affordances
  function wireSkipLink() {
    var link = doc.querySelector(".skip-link");
    var main = byId("main");
    if (!link || !main) return;
    if (!main.hasAttribute("tabindex")) main.setAttribute("tabindex", "-1");
    link.addEventListener("click", function (event) {
      // Default navigation would push #main into the hash the tab strip routes on.
      event.preventDefault();
      main.focus();
    });
  }

  function wireTabLinks() {
    doc.addEventListener("click", function (event) {
      var target = event.target;
      var link = target && target.closest ? target.closest("[data-tab-link]") : null;
      if (!link) return;
      var id = link.getAttribute("data-tab-link");
      if (!id || typeof site.showTab !== "function") return;
      if (link.tagName === "A") event.preventDefault();
      site.showTab(id);
    });
  }

  function wirePaletteShortcut() {
    doc.addEventListener("keydown", function (event) {
      // The palette module owns this key whenever it claims it; this is only the
      // fallback that keeps the advertised shortcut honest when it does not.
      if (event.defaultPrevented) return;
      if (!event.ctrlKey || !event.shiftKey || event.altKey) return;
      if (String(event.key).toLowerCase() !== "f") return;
      var openPalette = paletteOpener();
      if (!openPalette) return;
      event.preventDefault();
      openPalette();
    });
  }

  function wireSystemTheme() {
    if (!THEME_QUERY) return;
    var follow = function () {
      if (String(site.settings.get("theme")) === "system") applySettings();
    };
    if (typeof THEME_QUERY.addEventListener === "function") {
      THEME_QUERY.addEventListener("change", follow);
    } else if (typeof THEME_QUERY.addListener === "function") {
      THEME_QUERY.addListener(follow);
    }
  }

  // Published before ready so a module booting ahead of this one still gets the
  // real menu rather than the core's no-op placeholder.
  if (window.AmuletSite) window.AmuletSite.contextMenu = openContextMenu;

  site.ready(function () {
    menuElement();
    if (typeof site.settings.onChange === "function") site.settings.onChange(applySettings);
    wireSystemTheme();
    applySettings();
    wireSkipLink();
    wireTabLinks();
    wireBackgroundMenu();
    wirePaletteShortcut();
    loadPublicationManifest();
  });
})();
