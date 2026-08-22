/* The one searchable right-click menu for the Amulet Studio workspace shell.
 *
 * Every surface that wants a context menu registers the same shape of item
 * list here rather than building its own popup, so anchoring, keyboard
 * operation, plain-text-first filtering, and the shared bounded regex builder
 * behave identically everywhere -- including on the surfaces added after this
 * was written. A menu whose items are all filtered out still opens: an honest
 * no-match line beats a right-click that does nothing.
 *
 * This is studio.html's own menu (the #context-menu host div). It never
 * reaches into app.js's index.html menu; the two shells stay separate.
 */
(function () {
  "use strict";

  var site = window.AmuletSite;
  if (!site) return;

  var lang = site.lang;
  var el = site.el;

  function t(en, yue) {
    return lang.t(en, yue);
  }

  var host = document.getElementById("context-menu");

  var opener = null;
  var searchInput = null;
  var regexButton = null;
  var listNode = null;
  var emptyNode = null;
  var search = null;
  var items = [];
  var visibleItems = [];
  var activeIndex = 0;

  /* ------------------------------------------------------------- helpers */

  function normalizeItem(item) {
    if (!item || item === "-" || item.separator === true || item.type === "separator") {
      return { separator: true };
    }
    var label = String(item.label || item.text || item.title || "").trim();
    var run = typeof item.run === "function" ? item.run : null;
    // An enabled row that cannot act is a dead control; drop it rather than
    // draw it. Disabled rows keep their reason so keyboard users can read it.
    if (!label) return null;
    if (!item.disabled && !run) return null;
    return {
      label: label,
      shortcut: String(item.shortcut || ""),
      disabled: Boolean(item.disabled),
      reason: String(item.reason || ""),
      run: run,
    };
  }

  function tidySeparators(list) {
    var out = [];
    list.forEach(function (item) {
      if (item.separator && (!out.length || out[out.length - 1].separator)) return;
      out.push(item);
    });
    while (out.length && out[out.length - 1].separator) out.pop();
    return out;
  }

  function itemNodes() {
    if (!listNode) return [];
    return Array.prototype.slice.call(listNode.querySelectorAll('[role="menuitem"]'));
  }

  function focusItem(index) {
    var nodes = itemNodes();
    if (!nodes.length) return;
    activeIndex = (index + nodes.length) % nodes.length;
    nodes[activeIndex].focus();
  }

  function currentItemIndex() {
    var nodes = itemNodes();
    for (var i = 0; i < nodes.length; i++) {
      if (nodes[i] === document.activeElement) return i;
    }
    return -1;
  }

  /* ------------------------------------------------------------ painting */

  function buildItemNode(item) {
    if (item.separator) {
      var rule = document.createElement("div");
      rule.className = "sw-menu-separator";
      rule.setAttribute("role", "separator");
      rule.style.height = "1px";
      rule.style.margin = "4px 8px";
      rule.style.background = "var(--sw-olv, #BFC9C7)";
      return rule;
    }

    var button = document.createElement("button");
    button.type = "button";
    button.className = "sw-menu-item";
    button.setAttribute("role", "menuitem");
    button.tabIndex = -1;

    var labelSpan = document.createElement("span");
    labelSpan.className = "sw-menu-item-label";
    labelSpan.textContent = item.label;
    button.appendChild(labelSpan);

    if (item.shortcut) {
      var keys = document.createElement("span");
      keys.className = "sw-menu-shortcut";
      keys.setAttribute("aria-hidden", "true");
      keys.textContent = item.shortcut;
      button.appendChild(keys);
    }

    var name = item.label + (item.shortcut ? " (" + item.shortcut + ")" : "");
    if (item.disabled) {
      button.setAttribute("aria-disabled", "true");
      if (item.reason) {
        name += " — " + item.reason;
        button.title = item.reason;
      }
    }
    button.setAttribute("aria-label", name);

    button.addEventListener("click", function () {
      if (item.disabled) return;
      close(true);
      try {
        item.run();
      } catch (error) {
        if (site.notify) {
          site.notify(t("That action failed", "呢個動作失敗咗"), String((error && error.message) || error));
        } else {
          throw error;
        }
      }
    });
    return button;
  }

  function renderList(queryState) {
    if (!listNode || !emptyNode) return;
    listNode.innerHTML = "";
    emptyNode.hidden = true;
    activeIndex = 0;
    if (queryState && queryState.valid === false) {
      // The engine's own refusal is the fact; running nothing is safer than
      // silently widening the filter to "everything matches".
      emptyNode.textContent = t(
        "Pattern not run: " + (queryState.feedback || "invalid pattern"),
        "圖案未行到：" + (queryState.feedback || "無效 pattern")
      );
      emptyNode.hidden = false;
      visibleItems = [];
      return;
    }

    var painted = [];
    items.forEach(function (item) {
      if (item.separator) return;
      var matched = !search || search.matches(item.label);
      if (matched) painted.push(item);
    });
    visibleItems = painted;
    if (!visibleItems.length) {
      emptyNode.textContent = t("No command matches.", "冇指令 match。");
      emptyNode.hidden = false;
      return;
    }
    visibleItems.forEach(function (item, index) {
      void index;
      listNode.appendChild(buildItemNode(item));
    });
    focusItem(0);
  }

  /* --------------------------------------------------------- positioning */

  function pointerPoint(event) {
    var x = event && typeof event.clientX === "number" ? event.clientX : -1;
    var y = event && typeof event.clientY === "number" ? event.clientY : -1;
    if (x > 0 || y > 0) return { x: x, y: y };
    // The context-menu key reports no pointer, so anchor on the element.
    var anchor =
      event && event.target && event.target.getBoundingClientRect ? event.target : opener;
    if (anchor && anchor.getBoundingClientRect) {
      var box = anchor.getBoundingClientRect();
      return { x: box.left, y: box.bottom };
    }
    return { x: 16, y: 16 };
  }

  function position(event) {
    if (!host) return;
    var margin = 8;
    host.style.position = "fixed";
    host.style.left = "0px";
    host.style.top = "0px";
    host.style.maxHeight = "";
    var rect = host.getBoundingClientRect();
    var limit = Math.max(120, window.innerHeight - margin * 2);
    host.style.maxHeight = Math.min(limit, rect.height || limit) + "px";
    var point = pointerPoint(event);
    var left = Math.max(margin, Math.min(point.x, window.innerWidth - rect.width - margin));
    var top = Math.max(margin, Math.min(point.y, window.innerHeight - Math.min(rect.height, limit) - margin));
    host.style.left = left + "px";
    host.style.top = top + "px";
  }

  /* ------------------------------------------------------------ lifecycle */

  function onOutsidePointer(event) {
    if (!host || host.hidden) return;
    if (!host.contains(event.target)) close(false);
  }

  function onKeydown(event) {
    if (!host || host.hidden) return;
    var key = event.key;
    if (key === "Escape") {
      event.preventDefault();
      close(true);
      return;
    }
    if (key === "Tab") {
      close(true);
      return;
    }
    if (key === "ArrowDown" || key === "ArrowUp" || key === "Home" || key === "End") {
      event.preventDefault();
      var nodes = itemNodes();
      if (!nodes.length) return;
      var current = currentItemIndex();
      if (current === -1) current = activeIndex;
      if (key === "Home") focusItem(0);
      else if (key === "End") focusItem(nodes.length - 1);
      else focusItem(current + (key === "ArrowDown" ? 1 : -1));
    }
  }

  function onViewportChange() {
    if (!host || host.hidden) return;
    close(false);
  }

  function close(restoreFocus) {
    if (!host || host.hidden) return;
    host.hidden = true;
    while (host.firstChild) host.removeChild(host.firstChild);
    searchInput = null;
    regexButton = null;
    listNode = null;
    emptyNode = null;
    search = null;
    items = [];
    visibleItems = [];
    document.removeEventListener("pointerdown", onOutsidePointer, true);
    document.removeEventListener("keydown", onKeydown, true);
    window.removeEventListener("resize", onViewportChange, true);
    window.removeEventListener("scroll", onViewportChange, true);
    var origin = opener;
    opener = null;
    if (restoreFocus !== false && origin && typeof origin.focus === "function") {
      try {
        origin.focus();
      } catch (error) {
        /* a detached opener cannot take focus back */
      }
    }
  }

  function open(menuItems, event, label) {
    if (!host || !Array.isArray(menuItems)) return null;
    if (event && Array.isArray(event) && !Array.isArray(menuItems)) {
      var swap = menuItems;
      menuItems = event;
      event = swap;
    }

    var prepared = tidySeparators(
      menuItems
        .map(normalizeItem)
        .filter(function (item) {
          return Boolean(item);
        })
    );

    if (event && typeof event.preventDefault === "function") event.preventDefault();
    close(false);
    var active = document.activeElement;
    opener =
      active && active !== document.body ? active : event && event.target instanceof Element ? event.target : null;

    items = prepared;
    host.className = "context-menu sw-context-menu";
    host.hidden = false;
    host.setAttribute("aria-label", String(label || t("Context menu", "右鍵選單")));

    var searchWrap = el("div", { class: "sw-menu-search" });
    searchInput = el("input", {
      type: "search",
      placeholder: t("Search this menu", "搜尋呢個選單"),
      "aria-label": t("Search this menu", "搜尋呢個選單"),
      autocomplete: "off",
      maxlength: "256",
    });
    regexButton = el("button", {
      type: "button",
      class: "sw-regex-btn",
      title: t("Regex builder for this menu", "呢個選單嘅正則表達式 builder"),
      "aria-label": t("Regex builder for this menu", "呢個選單嘅正則表達式 builder"),
      "aria-expanded": "false",
      "aria-controls": "context-menu-regex",
    }, [".*"]);
    searchWrap.appendChild(searchInput);
    searchWrap.appendChild(regexButton);
    host.appendChild(searchWrap);

    var regexDetails = el("details", {
      id: "context-menu-regex",
      class: "regex-builder sw-context-regex",
    }, [el("summary", {}, [t("Regex builder · menu search", "正則表達式 builder · 選單搜尋")])]);
    var regexControls = el("div", { class: "regex-controls", "data-regex-controls": "studio-context-menu" });
    regexDetails.appendChild(regexControls);
    host.appendChild(regexDetails);

    listNode = el("div", { role: "group", class: "sw-context-list" });
    emptyNode = el("p", { class: "sw-menu-empty", hidden: "" }, []);
    emptyNode.style.margin = "4px 10px 6px";
    emptyNode.style.fontSize = "12px";
    emptyNode.style.color = "var(--sw-onv, #3F4948)";
    host.appendChild(listNode);
    host.appendChild(emptyNode);

    if (site.regex && typeof site.regex.attach === "function") {
      search = site.regex.attach({
        name: "studio-context-menu",
        input: searchInput,
        openButton: regexButton,
        panel: regexDetails,
        sample: "Undo Copy Paste",
        onChange: renderList,
      });
    }
    if (!search) {
      regexButton.hidden = true;
      search = {
        state: function () {
          return { valid: true, feedback: "" };
        },
        matches: function (text) {
          try {
            return site.matcher(String(searchInput.value), false, "i").test(text);
          } catch (error) {
            return false;
          }
        },
        refresh: function () {},
      };
    }

    searchInput.addEventListener("input", function () {
      if (search && typeof search.refresh === "function") search.refresh();
      renderList(search.state());
    });
    regexButton.addEventListener("click", function () {
      var expanded = regexButton.getAttribute("aria-expanded") === "true";
      regexButton.setAttribute("aria-expanded", expanded ? "false" : "true");
    });
    regexDetails.addEventListener("toggle", function () {
      regexButton.setAttribute("aria-expanded", regexDetails.open ? "true" : "false");
    });

    renderList(search.state());
    position(event);

    document.addEventListener("pointerdown", onOutsidePointer, true);
    document.addEventListener("keydown", onKeydown, true);
    window.addEventListener("resize", onViewportChange, true);
    window.addEventListener("scroll", onViewportChange, true);
    if (!visibleItems.length) searchInput.focus();
    else focusItem(0);

    return {
      close: function () {
        close(true);
      },
    };
  }

  site.contextMenu = open;
})();
