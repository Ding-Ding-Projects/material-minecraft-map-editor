/* Data-driven panels: the home grids, the feature inventory, the offline
 * documentation browser, and the screenshot wall.
 *
 * Everything below renders from window.AMULET_SITE_DATA. Copy that arrived with
 * the data -- feature details, article bodies, capture provenance, command
 * text -- is rendered exactly as recorded in every language mode, because each
 * one is a verified claim about a repository and a paraphrased fact is a
 * different fact. Only the chrome written here is put through lang.t().
 */
(function () {
  "use strict";

  var Site = window.AmuletSite;
  if (!Site) return;

  var el = Site.el;
  var DATA = Site.data || window.AMULET_SITE_DATA || {};

  var FEATURES = Array.isArray(DATA.features) ? DATA.features : [];
  var CATEGORIES = Array.isArray(DATA.categories) ? DATA.categories : [];
  var COMMANDS = Array.isArray(DATA.commands) ? DATA.commands : [];
  var SHOTS = Array.isArray(DATA.shots) ? DATA.shots : [];

  var ALL = "all";
  var HIGHLIGHT_MS = 1600;

  function t(en, yue) {
    return Site.lang.t(en, yue);
  }

  /** Voice styles the sentence; the caller still writes every fact in it. */
  function voice(en, enPlayful, yue, yuePlayful) {
    var english = Site.lang.funny("en") >= 4 && enPlayful ? enPlayful : en;
    var cantonese = Site.lang.funny("yue") >= 4 && yuePlayful ? yuePlayful : yue;
    return t(english, cantonese);
  }

  function byId(id) {
    return document.getElementById(id);
  }

  function motionSafe() {
    if (Site.settings.get("reducedMotion")) return false;
    try {
      return !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    } catch (error) {
      return true;
    }
  }

  /* Backtick spans in the source copy become real <code> nodes. Built as text
   * nodes rather than markup so nothing in the data can inject an element. */
  function inlineNodes(text) {
    var chunks = String(text == null ? "" : text).split("`");
    var nodes = [];
    chunks.forEach(function (chunk, index) {
      if (chunk === "") return;
      nodes.push(index % 2 ? el("code", { text: chunk }) : document.createTextNode(chunk));
    });
    return nodes.length ? nodes : [document.createTextNode("")];
  }

  function paragraph(text, className) {
    return el("p", { class: className || null }, inlineNodes(text));
  }

  // ------------------------------------------------------------- highlighting
  var highlighted = null;
  var highlightTimer = 0;

  function clearHighlight() {
    if (!highlighted) return;
    highlighted.node.classList.remove("is-highlighted");
    highlighted.node.style.outline = highlighted.outline;
    highlighted.node.style.outlineOffset = highlighted.offset;
    highlighted = null;
  }

  /* The inline outline is set as well as the class: a palette result that
   * teleports somewhere invisible has not actually shown the user anything. */
  function highlight(node) {
    if (!node || !node.style) return;
    clearHighlight();
    window.clearTimeout(highlightTimer);
    highlighted = { node: node, outline: node.style.outline, offset: node.style.outlineOffset };
    node.classList.add("is-highlighted");
    node.style.outline = "3px solid var(--primary)";
    node.style.outlineOffset = "4px";
    highlightTimer = window.setTimeout(clearHighlight, HIGHLIGHT_MS);
  }

  function reveal(tabId, node) {
    Site.showTab(tabId);
    if (!node) return;
    try {
      node.scrollIntoView({ block: "center", behavior: motionSafe() ? "smooth" : "auto" });
    } catch (error) {
      node.scrollIntoView();
    }
    if (typeof node.focus === "function") node.focus({ preventScroll: true });
    highlight(node);
  }

  // ------------------------------------------------------------------ search
  /* regex-builder.js owns every search field's builder. If it is missing the
   * field still has to search, so fall back to the plain-text default rather
   * than leaving an input that looks live and filters nothing. */
  function attachSearch(options) {
    if (Site.regex && typeof Site.regex.attach === "function") return Site.regex.attach(options);
    var handle = {
      state: function () {
        return {
          query: options.input ? options.input.value : "",
          regex: false,
          flags: "i",
          valid: true,
          feedback: "Plain text",
          matcher: null,
        };
      },
      matches: function (text) {
        var query = options.input ? options.input.value : "";
        if (!query) return true;
        try {
          return Site.matcher(query, false, "i").test(String(text));
        } catch (error) {
          return false;
        }
      },
      refresh: function () {
        if (options.onChange) options.onChange(handle.state());
      },
    };
    if (options.input) options.input.addEventListener("input", handle.refresh);
    return handle;
  }

  function liveCount(node) {
    if (!node) return;
    node.setAttribute("role", "status");
    node.setAttribute("aria-live", "polite");
  }

  function reportCount(node, state, count, noun) {
    if (!node) return;
    node.textContent = state.valid
      ? Site.describe(count, noun, state.query)
      : state.feedback || "Invalid pattern.";
  }

  // ============================================================ home: grids
  var CAPABILITIES = [
    [
      "World access",
      "Discover Java and Bedrock worlds, open a world from another folder, keep several worlds open in tabs, and switch between dimensions.",
    ],
    [
      "2D and 3D editing",
      "Navigate rendered terrain, inspect blocks, change projection, and create one or more selection boxes with direct coordinate controls.",
    ],
    [
      "Selection workflow",
      "Copy, cut, delete, paste, translate, rotate, scale, mirror, and move selected structures. Copied data can move between simultaneously open worlds.",
    ],
    [
      "Stock operations",
      "Clone, fill, replace, set biome, and waterlog selected regions; the operation framework also supports project-specific Python extensions.",
    ],
    [
      "Structure files",
      "Import supported structures and export `.construction`, `.mcstructure`, legacy `.schematic`, and Sponge `.schem` data through format-specific handlers.",
    ],
    [
      "Chunk tools",
      "Select chunks, delete selected chunks, or delete everything outside the selected area so Minecraft can regenerate it.",
    ],
    [
      "World conversion",
      "Merge source-world chunks into a chosen destination world through Amulet's format translation layer. Destination chunks at matching coordinates are overwritten.",
    ],
    [
      "Editing history",
      "Undo, redo, and explicitly save editor changes; close protection remains part of each open-world page.",
    ],
    [
      "Delivery",
      "Build PyInstaller bundles and produce unsigned Squirrel.Windows `Setup.exe`, `RELEASES`, and full `.nupkg` assets.",
    ],
  ];

  function renderCapabilities() {
    var grid = byId("capability-grid");
    if (!grid) return;
    grid.replaceChildren.apply(
      grid,
      CAPABILITIES.map(function (entry) {
        return el(
          "article",
          { class: "feature-card capability-card" },
          el("h3", { class: "card-title", text: entry[0] }),
          paragraph(entry[1], "card-copy")
        );
      })
    );
  }

  var DELIVERY = [
    {
      label: "BUILD",
      glyph: "🧱",
      title: ["Bootstrap, then package.", "先裝依賴，再打包。"],
      body:
        "build.bat /s checks for the Python launcher, installs user-scoped Python 3.11 when it is absent, resolves the declared dependencies, and installs the editable package without prompting. build-installer.bat /s repeats that bootstrap, builds installer/Amulet.spec, and invokes the same unsigned Squirrel.Windows packaging path CI uses.",
    },
    {
      label: "VERIFY",
      glyph: "🔍",
      title: ["Unsigned by design.", "刻意唔簽署。"],
      body:
        "Windows CI builds and verifies unsigned Setup.exe, RELEASES, full packages, and deltas where a previous package exists. Code signing is permanently disabled, so Windows may warn about an unknown publisher. Nothing here claims a signature.",
    },
    {
      label: "PUBLISH",
      glyph: "📦",
      title: ["Immutable assets only.", "淨係發永不改嘅檔案。"],
      body:
        "An installer link appears on this page only after the release manifest records a verified tag, commit, URL, and SHA-256 digest. The published 0.10.0-dev.414 assets target commit f95695f7cbadecd3272370a1fa694e9b601ab124.",
    },
  ];

  function renderDelivery() {
    var grid = byId("delivery-grid");
    if (!grid) return;
    grid.replaceChildren.apply(
      grid,
      DELIVERY.map(function (entry) {
        var glyph = Site.lang.emoji(entry.glyph);
        return el(
          "article",
          { class: "delivery-card" },
          el(
            "p",
            { class: "eyebrow" },
            glyph ? el("span", { "aria-hidden": "true", text: glyph }) : null,
            document.createTextNode(entry.label)
          ),
          el("h3", { class: "card-title", text: t(entry.title[0], entry.title[1]) }),
          paragraph(entry.body, "card-copy")
        );
      })
    );
  }

  // --------------------------------------------------------- install commands
  var copyTimers = [];

  function setCopyState(button, status, mode, command) {
    var label =
      mode === "done"
        ? t("Copied", "複製咗")
        : mode === "failed"
        ? t("Copy failed", "複製失敗")
        : t("Copy", "複製");
    button.textContent = label;
    // The visible label stays a prefix of the accessible name in every mode, so
    // "click Copy" still names a control a speech user can actually reach.
    button.setAttribute("aria-label", label + ": " + command);
    if (!status) return;
    if (mode === "done") {
      status.textContent = voice(
        "Copied to the clipboard.",
        "Copied to the clipboard. Go on, paste it somewhere useful.",
        "已經複製到剪貼簿。",
        "已經複製到剪貼簿，快啲貼去終端機啦。"
      );
    } else if (mode === "failed") {
      status.textContent = t(
        "The browser refused clipboard access. Select the command above and press Ctrl+C.",
        "瀏覽器唔俾用剪貼簿，請自己揀上面嘅指令再撳 Ctrl+C。"
      );
    } else {
      status.textContent = "";
    }
  }

  /* execCommand is deprecated but is the only clipboard route a file:// preview
   * has, and this page is meant to render identically from one. */
  function legacyCopy(text) {
    var field = document.createElement("textarea");
    field.value = text;
    field.setAttribute("readonly", "");
    field.style.position = "fixed";
    field.style.top = "-1000px";
    field.style.opacity = "0";
    document.body.appendChild(field);
    var copied = false;
    try {
      field.select();
      copied = document.execCommand("copy");
    } catch (error) {
      copied = false;
    }
    document.body.removeChild(field);
    return copied === true;
  }

  function writeClipboard(text) {
    if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
      try {
        return navigator.clipboard.writeText(text).then(
          function () {
            return true;
          },
          function () {
            return legacyCopy(text);
          }
        );
      } catch (error) {
        return Promise.resolve(legacyCopy(text));
      }
    }
    return Promise.resolve(legacyCopy(text));
  }

  function commandCard(entry, index) {
    var command = String(entry.command || "");
    var status = el("p", { class: "copy-status", role: "status" });
    var button = el("button", { type: "button", class: "button button-tonal copy-button" });
    setCopyState(button, status, "idle", command);
    button.addEventListener("click", function () {
      window.clearTimeout(copyTimers[index]);
      writeClipboard(command).then(function (copied) {
        setCopyState(button, status, copied ? "done" : "failed", command);
        if (!copied) {
          Site.notify(
            t("Copy failed", "複製失敗"),
            t("The browser refused clipboard access for: ", "瀏覽器拒絕咗剪貼簿存取：") + command
          );
        }
        copyTimers[index] = window.setTimeout(function () {
          setCopyState(button, status, "idle", command);
        }, 6000);
      });
    });

    return el(
      "article",
      { class: "feature-card command-card" },
      el("h3", { class: "card-title", text: String(entry.title || command) }),
      entry.note ? paragraph(entry.note, "card-copy") : null,
      el("pre", { class: "command-block" }, el("code", { text: command })),
      el("div", { class: "card-actions" }, button, status)
    );
  }

  function renderCommands() {
    var grid = byId("install-grid");
    if (!grid) return;
    copyTimers.forEach(function (timer) {
      window.clearTimeout(timer);
    });
    copyTimers = [];
    grid.replaceChildren.apply(
      grid,
      COMMANDS.filter(function (entry) {
        return entry && entry.command;
      }).map(commandCard)
    );
  }

  // ========================================================= features tab
  var featureCards = [];
  var featureSearch = null;
  var activeCategory = ALL;

  function featureCard(entry, index) {
    var haystack = [entry.category, entry.title, entry.detail, entry.href].join(" ");
    var title = String(entry.title || "");
    // A hundred links reading "Read the contract" are a hundred identical
    // accessible names, so each one names its own feature.
    var link = el("a", {
      class: "card-link",
      href: String(entry.href || ""),
      target: "_blank",
      rel: "noreferrer",
      "aria-label": t("Read the contract for " + title, "睇「" + title + "」嘅規格文件"),
    });
    link.appendChild(document.createTextNode(t("Read the contract", "睇規格文件")));
    link.appendChild(el("span", { "aria-hidden": "true", text: " ↗" }));

    var node = el(
      "article",
      {
        class: "feature-card",
        tabindex: "-1",
        "data-feature-index": String(index),
        "data-category": String(entry.category || ""),
      },
      el("p", { class: "pill category-pill", text: String(entry.category || "") }),
      el("h2", { class: "card-title", text: title }),
      paragraph(entry.detail, "card-copy"),
      entry.href ? link : null
    );

    return { node: node, data: entry, haystack: haystack };
  }

  function categoryChip(value, label, count) {
    var chip = el(
      "button",
      {
        type: "button",
        class: "chip category-chip",
        "data-category": value === ALL ? "" : value,
        "aria-pressed": String(activeCategory === value),
      },
      el("span", { class: "chip-label", text: label }),
      el("span", { class: "chip-count", text: String(count) })
    );
    chip.addEventListener("click", function () {
      activeCategory = value;
      syncChips();
      applyFeatureFilter();
    });
    return chip;
  }

  var chipNodes = [];

  function syncChips() {
    chipNodes.forEach(function (entry) {
      entry.node.setAttribute("aria-pressed", String(entry.value === activeCategory));
    });
  }

  function renderCategories() {
    var row = byId("feature-categories");
    if (!row) return;
    chipNodes = [];
    var counts = {};
    FEATURES.forEach(function (entry) {
      counts[entry.category] = (counts[entry.category] || 0) + 1;
    });
    var known = CATEGORIES.slice();
    Object.keys(counts).forEach(function (name) {
      if (known.indexOf(name) === -1) known.push(name);
    });
    if (known.indexOf(activeCategory) === -1 && activeCategory !== ALL) activeCategory = ALL;

    var chips = [categoryChip(ALL, t("All", "全部"), FEATURES.length)];
    known.forEach(function (name) {
      chips.push(categoryChip(name, name, counts[name] || 0));
    });
    chips.forEach(function (node, index) {
      chipNodes.push({ node: node, value: index === 0 ? ALL : known[index - 1] });
    });
    row.replaceChildren.apply(row, chips);
  }

  function applyFeatureFilter() {
    var state = featureSearch ? featureSearch.state() : { query: "", valid: true };
    var visible = 0;
    featureCards.forEach(function (entry) {
      var inCategory = activeCategory === ALL || entry.data.category === activeCategory;
      var matched = inCategory && (!featureSearch || featureSearch.matches(entry.haystack));
      entry.node.hidden = !matched;
      if (matched) visible++;
    });
    reportCount(byId("feature-count"), state, visible, "feature");
    var empty = byId("feature-empty");
    if (empty) empty.hidden = visible !== 0;
  }

  function renderFeatures() {
    var grid = byId("feature-grid");
    if (!grid) return;
    featureCards = FEATURES.map(featureCard);
    grid.replaceChildren.apply(
      grid,
      featureCards.map(function (entry) {
        return entry.node;
      })
    );
    renderCategories();
    applyFeatureFilter();
  }

  /* A palette result has to land on something the user can see, so a filter
   * that would hide the target is cleared -- and said out loud, because a
   * filter that changes without explanation reads as the page losing state. */
  function revealFeature(index) {
    var entry = featureCards[index];
    if (!entry) return;
    var cleared = false;
    if (entry.node.hidden) {
      if (activeCategory !== ALL && entry.data.category !== activeCategory) {
        activeCategory = ALL;
        cleared = true;
      }
      var input = byId("feature-search");
      if (input && input.value) {
        input.value = "";
        cleared = true;
        if (featureSearch && featureSearch.refresh) featureSearch.refresh();
      }
      syncChips();
      applyFeatureFilter();
    }
    if (cleared) {
      Site.notify(
        t("Feature filter cleared", "已經清咗篩選"),
        t("Cleared the feature filter so this stays visible: ", "清咗篩選，等你見到：") +
          entry.data.title
      );
    }
    if (entry.node.hidden) {
      Site.notify(
        t("Still filtered out", "仲係俾篩選遮住"),
        t("The active search still hides: ", "而家嘅搜尋仲係遮住咗：") + entry.data.title
      );
      Site.showTab("features");
      return;
    }
    reveal("features", entry.node);
  }

  // ============================================================== docs tab
  var docEntries = [];
  var docSearch = null;
  var selectedSlug = null;
  var docsEmptyDefault = "";

  function normaliseDoc(entry, index) {
    var source = entry && typeof entry === "object" ? entry : {};
    var body = String(source.body || source.markdown || "");
    var title = String(source.title || source.slug || "");
    var slug = String(source.slug || (title ? title.toLowerCase().replace(/[^a-z0-9]+/g, "-") : "article-" + (index + 1)));
    var summary = String(source.summary || "");
    if (!summary && body) summary = firstParagraph(body);
    if (!title && !body) return null;
    return {
      slug: slug,
      title: title || slug,
      summary: summary,
      body: body,
      haystack: [title, summary, body].join("\n"),
    };
  }

  function firstParagraph(body) {
    var lines = String(body).replace(/\r\n?/g, "\n").split("\n");
    for (var i = 0; i < lines.length; i++) {
      var line = lines[i].trim();
      if (!line || line.charAt(0) === "#" || line.slice(0, 3) === "```") continue;
      if (line.charAt(0) === "-" || line.charAt(0) === "*") continue;
      return line.length > 200 ? line.slice(0, 197).replace(/\s+\S*$/, "") + "..." : line;
    }
    return "";
  }

  /* Markdown-ish, rendered as nodes. The bodies are provider-authored text, so
   * printing them raw would show the source and parsing them into markup would
   * hand the data a way to inject elements. */
  function renderBody(body, container) {
    var lines = String(body || "").replace(/\r\n?/g, "\n").split("\n");
    var buffer = [];
    var items = null;
    var fence = null;

    function flushParagraph() {
      if (!buffer.length) return;
      container.appendChild(paragraph(buffer.join(" ")));
      buffer = [];
    }

    function flushList() {
      if (!items) return;
      container.appendChild(el("ul", { class: "docs-list-block" }, items));
      items = null;
    }

    lines.forEach(function (raw) {
      var line = raw.replace(/\s+$/, "");
      var trimmed = line.trim();

      if (fence !== null) {
        if (trimmed.slice(0, 3) === "```") {
          container.appendChild(el("pre", { class: "docs-code" }, el("code", { text: fence.join("\n") })));
          fence = null;
        } else {
          fence.push(line);
        }
        return;
      }
      if (trimmed.slice(0, 3) === "```") {
        flushParagraph();
        flushList();
        fence = [];
        return;
      }
      if (!trimmed) {
        flushParagraph();
        flushList();
        return;
      }
      var heading = /^(#{1,6})\s+(.*)$/.exec(trimmed);
      if (heading) {
        flushParagraph();
        flushList();
        var level = Math.min(6, heading[1].length + 2);
        container.appendChild(el("h" + level, {}, inlineNodes(heading[2])));
        return;
      }
      var item = /^[-*]\s+(.*)$/.exec(trimmed);
      if (item) {
        flushParagraph();
        if (!items) items = [];
        items.push(el("li", {}, inlineNodes(item[1])));
        return;
      }
      flushList();
      buffer.push(trimmed);
    });

    if (fence !== null && fence.length) {
      container.appendChild(el("pre", { class: "docs-code" }, el("code", { text: fence.join("\n") })));
    }
    flushParagraph();
    flushList();
  }

  function renderArticle(entry, focus) {
    var article = byId("docs-article");
    if (!article) return;
    article.replaceChildren();
    if (!entry) {
      article.appendChild(
        el("p", {
          class: "empty-state",
          text: voice(
            "Choose an article from the list to read it here.",
            "Pick an article from the list and it lands right here, no network required.",
            "喺左邊揀一篇文章，就會喺呢度打開。",
            "喺左邊撳一篇，即刻喺呢度開，唔使上網。"
          ),
        })
      );
      article.setAttribute("aria-label", t("Documentation article", "文件內容"));
      return;
    }
    article.setAttribute("aria-label", entry.title);
    article.appendChild(el("h2", { class: "docs-title", text: entry.title }));
    if (entry.summary) article.appendChild(paragraph(entry.summary, "docs-summary"));
    renderBody(entry.body, article);
    if (focus && typeof article.focus === "function") article.focus({ preventScroll: true });
  }

  function syncDocIndex() {
    docEntries.forEach(function (entry) {
      if (!entry.button) return;
      var active = entry.slug === selectedSlug;
      entry.button.setAttribute("aria-current", active ? "true" : "false");
      entry.button.classList.toggle("is-active", active);
    });
  }

  function selectDoc(slug, focus) {
    var found = null;
    docEntries.forEach(function (entry) {
      if (entry.slug === slug) found = entry;
    });
    if (!found) return null;
    selectedSlug = found.slug;
    syncDocIndex();
    renderArticle(found, focus === true);
    return found;
  }

  function docsKeydown(event) {
    var keys = ["ArrowDown", "ArrowUp", "Home", "End"];
    if (keys.indexOf(event.key) === -1) return;
    var buttons = docEntries
      .filter(function (entry) {
        return entry.item && !entry.item.hidden;
      })
      .map(function (entry) {
        return entry.button;
      });
    var index = buttons.indexOf(event.target);
    if (index === -1 || !buttons.length) return;
    event.preventDefault();
    var next = index;
    if (event.key === "ArrowDown") next = (index + 1) % buttons.length;
    if (event.key === "ArrowUp") next = (index + buttons.length - 1) % buttons.length;
    if (event.key === "Home") next = 0;
    if (event.key === "End") next = buttons.length - 1;
    buttons[next].focus();
  }

  function applyDocsFilter() {
    var state = docSearch ? docSearch.state() : { query: "", valid: true };
    var visible = 0;
    docEntries.forEach(function (entry) {
      var matched = !docSearch || docSearch.matches(entry.haystack);
      entry.item.hidden = !matched;
      if (matched) visible++;
    });
    reportCount(byId("docs-count"), state, visible, "article");
    var empty = byId("docs-empty");
    if (empty) {
      if (!docEntries.length) {
        empty.textContent = t(
          "No article is bundled with this page yet.",
          "呢一頁暫時未打包任何文章。"
        );
        empty.hidden = false;
      } else {
        if (docsEmptyDefault) empty.textContent = docsEmptyDefault;
        empty.hidden = visible !== 0;
      }
    }
  }

  function renderDocs() {
    var index = byId("docs-index");
    if (!index) return;
    var previous = selectedSlug;
    var raw = Array.isArray(DATA.docs) ? DATA.docs : [];
    docEntries = raw
      .map(normaliseDoc)
      .filter(function (entry) {
        return entry !== null;
      });

    var list = el("ul", { class: "docs-index-list" });
    docEntries.forEach(function (entry) {
      var button = el("button", {
        type: "button",
        class: "docs-link",
        "data-slug": entry.slug,
        text: entry.title,
      });
      button.addEventListener("click", function () {
        selectDoc(entry.slug, true);
      });
      button.addEventListener("keydown", docsKeydown);
      var item = el("li", { class: "docs-index-item" }, button);
      if (entry.summary) item.appendChild(el("p", { class: "docs-index-summary", text: entry.summary }));
      entry.button = button;
      entry.item = item;
      list.appendChild(item);
    });
    index.replaceChildren(list);

    var keep = null;
    docEntries.forEach(function (entry) {
      if (entry.slug === previous) keep = entry;
    });
    selectedSlug = keep ? keep.slug : docEntries.length ? docEntries[0].slug : null;
    syncDocIndex();
    renderArticle(keep || docEntries[0] || null, false);
    applyDocsFilter();
  }

  // ======================================================== screenshots tab
  var shotFigures = [];
  var shotSearch = null;

  function dimensions(px) {
    var match = /(\d+)\D+(\d+)/.exec(String(px || ""));
    return match ? { width: match[1], height: match[2] } : null;
  }

  function shotFigure(entry, index) {
    var title = String(entry.title || "");
    var boundary = String(entry.boundary || "");
    var provenance = String(entry.provenance || "");
    var px = String(entry.px || "");
    var size = dimensions(px);
    var image = el("img", {
      src: String(entry.src || ""),
      alt: boundary ? title + " — " + boundary : title,
      loading: "lazy",
      decoding: "async",
      width: size ? size.width : null,
      height: size ? size.height : null,
    });

    var caption = el("figcaption", { class: "shot-caption" }, el("strong", { class: "shot-title", text: title }));
    if (px) caption.appendChild(el("span", { class: "shot-px mono", text: px }));
    if (provenance) caption.appendChild(el("span", { class: "shot-provenance", text: provenance }));
    if (boundary) caption.appendChild(el("span", { class: "shot-boundary", text: boundary }));

    var node = el("figure", { class: "shot", tabindex: "-1", "data-shot-index": String(index) }, image, caption);
    return {
      node: node,
      haystack: [title, px, provenance, boundary].join(" "),
    };
  }

  function applyShotsFilter() {
    var state = shotSearch ? shotSearch.state() : { query: "", valid: true };
    var visible = 0;
    shotFigures.forEach(function (entry) {
      var matched = !shotSearch || shotSearch.matches(entry.haystack);
      entry.node.hidden = !matched;
      if (matched) visible++;
    });
    reportCount(byId("shots-count"), state, visible, "capture");
    var empty = byId("shots-empty");
    if (empty) empty.hidden = visible !== 0;
  }

  function renderShots() {
    var grid = byId("shots-grid");
    if (!grid) return;
    shotFigures = SHOTS.filter(function (entry) {
      return entry && entry.src;
    }).map(shotFigure);
    grid.replaceChildren.apply(
      grid,
      shotFigures.map(function (entry) {
        return entry.node;
      })
    );
    applyShotsFilter();
  }

  // ============================================================== palette
  Site.registerPaletteSource(function () {
    var items = [];
    FEATURES.forEach(function (entry, index) {
      items.push({
        kind: "Feature",
        title: String(entry.title || ""),
        subtitle: String(entry.category || "") + " · " + String(entry.detail || ""),
        run: function () {
          revealFeature(index);
        },
      });
    });
    docEntries.forEach(function (entry) {
      items.push({
        kind: "Article",
        title: entry.title,
        subtitle: entry.summary || entry.slug,
        run: function () {
          Site.showTab("docs");
          var found = selectDoc(entry.slug, true);
          var article = byId("docs-article");
          if (found && article) {
            try {
              article.scrollIntoView({ block: "center", behavior: motionSafe() ? "smooth" : "auto" });
            } catch (error) {
              article.scrollIntoView();
            }
            highlight(article);
          }
        },
      });
    });
    SHOTS.forEach(function (entry, index) {
      if (!entry || !entry.src) return;
      items.push({
        kind: "Capture",
        title: String(entry.title || ""),
        subtitle: String(entry.px || "") + " · " + String(entry.provenance || ""),
        run: function () {
          var node = document.querySelector('#shots-grid [data-shot-index="' + index + '"]');
          reveal("screenshots", node);
        },
      });
    });
    return items;
  });

  // ================================================================= wiring
  function renderAuthoredCopy() {
    renderCapabilities();
    renderDelivery();
    renderCommands();
    renderFeatures();
    renderDocs();
    renderShots();
  }

  Site.ready(function () {
    var docsEmpty = byId("docs-empty");
    if (docsEmpty) docsEmptyDefault = docsEmpty.textContent;

    liveCount(byId("feature-count"));
    liveCount(byId("docs-count"));
    liveCount(byId("shots-count"));

    featureSearch = attachSearch({
      name: "feature",
      input: byId("feature-search"),
      openButton: byId("feature-regex-open"),
      panel: byId("feature-regex"),
      sample: "Regex builder - Editor - bounded builder attached to every search bar",
      onChange: applyFeatureFilter,
    });
    docSearch = attachSearch({
      name: "docs",
      input: byId("docs-search"),
      openButton: byId("docs-regex-open"),
      panel: byId("docs-regex"),
      sample: "Offline documentation - every article is bundled with this page",
      onChange: applyDocsFilter,
    });
    shotSearch = attachSearch({
      name: "shots",
      input: byId("shots-search"),
      openButton: byId("shots-regex-open"),
      panel: byId("shots-regex"),
      // Samples mirror the shape of the text each field really searches, so a
      // pattern that works against the sample works against the content.
      sample: "Current Material shell · 2250×1395 · Captured 2026-08-09 from commit b3cbec1c",
      onChange: applyShotsFilter,
    });

    renderAuthoredCopy();

    // Language, voice level, and emoji all change rendered copy, so the panels
    // are rebuilt rather than left describing the previous mode.
    Site.settings.onChange(function (key) {
      if (key === null || key === "language" || key === "funnyEn" || key === "funnyYue" || key === "emoji") {
        renderAuthoredCopy();
      }
    });
  });
})();
