/* Amulet Studio's backstage: the start screen from design/Amulet Studio.dc.html
 * (see design/HANDOFF.md, "Backstage"). This is what the desktop shell opens
 * on and returns to when a project is closed -- Home with a template gallery
 * and a searchable, filterable recent table; Open; Project info; Convert; All
 * surfaces; and a route into the workspace.
 *
 * This module owns none of docs/site/index.html or styles.css -- the
 * published documentation site keeps its own marketing landing page exactly
 * as it is. It mounts into a container the desktop shell provides, by id
 * "studio-backstage" unless the shell names a different one via
 * window.AmuletSite.studioBackstage.mountId before this script runs.
 *
 * Real data only:
 *  - The recent table reads Site.electronSidecar's bridge directly
 *    (sidecar method "recents.list"), never a fixture.
 *  - Opening a world calls the real "world.open" / "world.open_status" pair
 *    the viewport panel already uses (docs/site/viewport-panel.js), the same
 *    background-load-then-poll contract documented in
 *    amulet_map_editor/api/sidecar/world_methods.py.
 *  - Project info renders the identity the sidecar returned for the
 *    currently open world -- nothing here invents a platform, a version, or
 *    a dimension list.
 *
 * Honest empty states throughout: no sidecar reachable is a distinct,
 * labelled "desktop only" state (never a blank panel or a dead grey
 * rectangle); a sidecar call that fails says what failed; an empty recent
 * list says how to start instead of showing nothing.
 */
(function () {
  "use strict";

  var Site = window.AmuletSite;
  if (!Site) return;

  var el = Site.el;
  var lang = Site.lang;

  function t(en, yue) {
    return lang ? lang.t(en, yue) : en;
  }

  function bridge() {
    return window.mmweDesktop && window.mmweDesktop.sidecar;
  }

  function sidecarCall(method, params) {
    var b = bridge();
    if (!b || typeof b.call !== "function") {
      return Promise.resolve({ ok: false, error: { code: "no_bridge" } });
    }
    return b.call(method, params || {});
  }

  function sleep(ms) {
    return new Promise(function (resolve) {
      setTimeout(resolve, ms);
    });
  }

  // -------------------------------------------------------------- templates
  // Traced to the template gallery in design/Amulet Studio.dc.html (backNav /
  // `templates`). Only "Blank world project" and "Conversion job" reach a
  // real flow this lane can drive (opening a world, or the convert page);
  // the rest route to the closest real destination and say so in their hint
  // rather than pretending to run a flow that does not exist yet.
  var TEMPLATES = [
    {
      glyph: "▢",
      title: function () {
        return t("Blank world project", "空白世界項目");
      },
      hint: function () {
        return t(
          "Open a world and start with one empty selection box.",
          "打開一個世界，由一個空白嘅揀選箱開始。"
        );
      },
      tab: "open",
    },
    {
      glyph: "❖",
      title: function () {
        return t("Structure library", "結構庫");
      },
      hint: function () {
        return t(
          "Import and stage .construction, .schem, and .mcstructure files. Not wired into this backstage build yet -- opens Open instead.",
          "匯入同準備 .construction、.schem 同 .mcstructure 檔案。呢個 backstage 版本重未駁通－先開 Open。"
        );
      },
      tab: "open",
    },
    {
      glyph: "⇄",
      title: function () {
        return t("Conversion job", "轉換工作");
      },
      hint: function () {
        return t(
          "Pair a source and destination world before merging chunks.",
          "揀好來源同目標世界，先至可以合併 chunk。"
        );
      },
      tab: "convert",
    },
    {
      glyph: "▦",
      title: function () {
        return t("Chunk repair", "區塊修復");
      },
      hint: function () {
        return t(
          "Prune, regenerate, or restore chunks from a backup world. Not wired into this backstage build yet -- opens Open instead.",
          "由備份世界修剪、重新生成或者還原 chunk。呢個 backstage 版本重未駁通－先開 Open。"
        );
      },
      tab: "open",
    },
    {
      glyph: "✎",
      title: function () {
        return t("Classroom kit", "課堂套件");
      },
      hint: function () {
        return t(
          "School-mode presentation lock with English-only copy. Turn School mode on from Options.",
          "校園模式簡報鎖定，淨係用英文。可以喺 Options 度開校園模式。"
        );
      },
      tab: "home",
    },
  ];

  // ------------------------------------------------------------- surfaces
  // The readable form of the same feature inventory design/HANDOFF.md lists
  // under "Feature inventory". Grouped exactly as the design groups it. A
  // handful (Project shell) route to a real backstage tab; everything else
  // is outside this lane's scope and says so plainly when activated, rather
  // than pretending to open a surface that is not built yet.
  var SURFACE_GROUPS = [
    {
      title: function () {
        return t("Project shell", "項目框架");
      },
      items: [
        { label: "Home", hint: "Template gallery and recent projects", tab: "home" },
        { label: "Open", hint: "World folders, .mcworld files, saved projects", tab: "open" },
        { label: "Project info", hint: "Paths, revisions, and project actions", tab: "info" },
        { label: "Convert", hint: "Input, output, and overwrite warning", tab: "convert" },
      ],
    },
    {
      title: function () {
        return t("Editing", "編輯");
      },
      items: [
        { label: "Selection tool", hint: "Selection tool and boxes" },
        { label: "Paste tool", hint: "Paste tool" },
        { label: "Operations", hint: "Operations" },
        { label: "Chunk tool", hint: "Import / export chunks" },
        { label: "Block picker", hint: "Block, biome, and version pickers" },
      ],
    },
    {
      title: function () {
        return t("Terrain", "地形");
      },
      items: [
        { label: "Sculpt brush", hint: "Sculpt, smooth, flatten" },
        { label: "Erosion", hint: "Erosion and noise fill" },
        { label: "Sea level", hint: "Sea level and regenerate" },
      ],
    },
    {
      title: function () {
        return t("Panels and views", "面板同視圖");
      },
      items: [
        { label: "Inspector", hint: "Inspector panel" },
        { label: "Undo history", hint: "Undo history and jump-to-point" },
        { label: "Log", hint: "Application log" },
      ],
    },
    {
      title: function () {
        return t("Global", "全域");
      },
      items: [
        { label: "Command palette", hint: "Ctrl+Shift+F over every command" },
        { label: "Regex builder", hint: "Pattern, flags, sample, live captures" },
        { label: "Memory Console", hint: "Sync, skills, docs, security" },
      ],
    },
  ];

  // ---------------------------------------------------------------- state
  var state = {
    tab: "home",
    recentQuery: "",
    recentFilter: "All",
    recents: null, // null = not yet loaded; array once resolved
    recentsError: null,
    openPath: "",
    openBusy: false,
    openMessage: "",
    world: null, // identity of the last world this session opened
    featureQuery: "",
  };

  var refreshers = [];
  function refresh() {
    refreshers.forEach(function (fn) {
      try {
        fn();
      } catch (error) {
        /* one broken panel must not blank the rest of the backstage */
      }
    });
  }
  function setState(patch) {
    Object.assign(state, patch);
    refresh();
  }

  // ------------------------------------------------------------------ home
  function buildTemplates(container, goTab) {
    TEMPLATES.forEach(function (tpl) {
      var card = el(
        "button",
        { type: "button", class: "sb-template", onClick: function () { goTab(tpl.tab); } },
        el("div", { class: "sb-template-glyph" }, tpl.glyph),
        el(
          "div",
          { class: "sb-template-body" },
          el("b", { class: "sb-template-title", text: tpl.title() }),
          el("small", { class: "sb-template-hint", text: tpl.hint() })
        )
      );
      container.appendChild(card);
    });
  }

  function recentHaystack(entry) {
    return [entry.name, entry.kind, entry.platform, entry.path, entry.tag]
      .filter(Boolean)
      .join(" ");
  }

  function filteredRecents() {
    var all = state.recents || [];
    var filter = state.recentFilter;
    var matcher = state.recentMatcher;
    return all.filter(function (entry) {
      if (filter !== "All" && entry.tag !== filter) return false;
      if (matcher) return matcher(recentHaystack(entry));
      return true;
    });
  }

  function loadRecents() {
    if (!bridge()) {
      setState({ recents: null, recentsError: "desktop_only" });
      return;
    }
    setState({ recentsError: null });
    sidecarCall("recents.list", {}).then(function (response) {
      if (response && response.ok && response.result) {
        setState({ recents: response.result.entries || [], recentsError: null });
      } else {
        setState({
          recents: null,
          recentsError: (response && response.error && response.error.code) || "unknown_error",
        });
      }
    });
  }

  // ------------------------------------------------------------------ open
  function validatePath(raw) {
    var path = String(raw == null ? "" : raw).trim();
    if (!path) {
      return { ok: false, message: t("Enter a world folder path first.", "先輸入世界資料夾路徑。") };
    }
    if (path.length > 4096) {
      return { ok: false, message: t("That path is too long.", "呢條路徑太長。") };
    }
    return { ok: true, path: path };
  }

  async function pollWorldOpen(id) {
    for (var i = 0; i < 600; i++) {
      var response = await sidecarCall("world.open_status", { world_id: id });
      if (!response.ok) {
        throw new Error("world.open_status failed: " + JSON.stringify(response.error));
      }
      if (response.result.status !== "pending") return response.result;
      await sleep(100);
    }
    throw new Error("world.open_status stayed pending");
  }

  function showWorkspaceView() {
    // The shell owns the view state; this is only a request. A shell that
    // has not loaded yet, or one hosting the backstage on its own, simply
    // stays put rather than inventing a workspace out of nothing.
    if (window.AmuletStudio && typeof window.AmuletStudio.showView === "function") {
      window.AmuletStudio.showView("workspace");
    }
  }

  async function openWorldAtPath(rawPath) {
    var validated = validatePath(rawPath);
    if (!validated.ok) {
      setState({ openMessage: validated.message });
      return;
    }
    if (!bridge()) {
      setState({
        openMessage: t(
          "Opening a world needs the desktop app -- there is no sidecar to talk to from a browser tab.",
          "開世界要用桌面版程式－瀏覽器分頁冇 sidecar 可以傾。"
        ),
      });
      return;
    }
    setState({ openBusy: true, openMessage: t("Opening world…", "開緊世界…") });
    try {
      var opened = await sidecarCall("world.open", { path: validated.path });
      if (!opened.ok) {
        setState({
          openBusy: false,
          openMessage: t("Could not open that world: ", "打唔開嗰個世界：") + JSON.stringify(opened.error),
        });
        return;
      }
      var result = await pollWorldOpen(opened.result.world_id);
      if (result.status !== "ready") {
        setState({
          openBusy: false,
          openMessage: t("World failed to open: ", "世界打唔開：") + JSON.stringify(result.error || result),
        });
        return;
      }
      setState({
        openBusy: false,
        openMessage: t("Opened ", "已經打開 ") + result.name + ".",
        world: result,
        tab: "info",
      });
      if (Site.studioBackstage && typeof Site.studioBackstage.onWorldOpened === "function") {
        try {
          Site.studioBackstage.onWorldOpened(result);
        } catch (error) {
          /* a shell hook that throws must not break the backstage */
        }
      }
      showWorkspaceView();
    } catch (error) {
      setState({ openBusy: false, openMessage: t("Could not open that world: ", "打唔開嗰個世界：") + String(error) });
    }
  }

  function browseAvailable() {
    var b = bridge();
    return !!(b && b.dialog && typeof b.dialog.chooseFolder === "function");
  }

  // --------------------------------------------------------------- render
  function panelHidden(root, key, current) {
    var node = root.querySelector('[data-sb-panel="' + key + '"]');
    if (node) node.hidden = key !== current;
  }

  function mount(root) {
    root.classList.add("studio-backstage");
    root.innerHTML = "";

    // ------------------------------------------------------------- nav rail
    var nav = el("div", { class: "sb-nav", role: "navigation", "aria-label": t("Backstage", "後台") });
    var brand = el("div", { class: "sb-brand", text: "Amulet Studio" });
    nav.appendChild(brand);

    var NAV_ITEMS = [
      { key: "home", glyph: "⌂", label: function () { return t("Home", "主頁"); } },
      { key: "open", glyph: "▸", label: function () { return t("Open", "開啟"); } },
      { key: "info", glyph: "ⓘ", label: function () { return t("Project info", "項目資訊"); } },
      { key: "convert", glyph: "⇄", label: function () { return t("Convert", "轉換"); } },
      { key: "features", glyph: "▦", label: function () { return t("All surfaces", "全部介面"); } },
    ];
    var navButtons = NAV_ITEMS.map(function (item) {
      var button = el(
        "button",
        {
          type: "button",
          class: "sb-nav-item",
          "aria-current": item.key === state.tab ? "page" : null,
          onClick: function () { setState({ tab: item.key }); },
        },
        el("span", { class: "sb-nav-glyph", "aria-hidden": "true" }, item.glyph),
        el("span", { class: "sb-nav-label", text: item.label() })
      );
      nav.appendChild(button);
      return { key: item.key, node: button, label: item.label };
    });
    // Last so callers that look for the backstage "Open" tab by label still
    // reach that tab rather than this workspace route.
    nav.appendChild(el(
      "button",
      {
        type: "button",
        class: "sb-nav-item sb-nav-item--workspace",
        "aria-label": t("Open workspace", "打開工作區"),
        onClick: showWorkspaceView,
      },
      el("span", { class: "sb-nav-glyph", "aria-hidden": "true" }, "→"),
      el("span", { class: "sb-nav-label", text: t("Open workspace", "打開工作區") })
    ));
    root.appendChild(nav);

    // ---------------------------------------------------------------- body
    var body = el("div", { class: "sb-body" });
    root.appendChild(body);

    // ==================================================================
    // Home
    // ==================================================================
    var home = el("div", { class: "sb-page", "data-sb-panel": "home" });
    home.appendChild(el("h1", { class: "sb-heading", text: t("Good to see you", "見到你真好") }));
    home.appendChild(
      el("p", {
        class: "sb-lede",
        text: t(
          "Start a project from a template, or pick up a world you were editing. Every project stays local to this machine.",
          "由範本開始一個項目，或者揸返之前編輯緊嘅世界。每個項目都留喺呢部機度，唔會走出去。"
        ),
      })
    );
    home.appendChild(el("div", { class: "sb-eyebrow", text: t("New", "新項目") }));
    var templateGrid = el("div", { class: "sb-template-grid" });
    buildTemplates(templateGrid, function (tab) { setState({ tab: tab }); });
    home.appendChild(templateGrid);

    var recentHeader = el("div", { class: "sb-recent-header" });
    recentHeader.appendChild(el("div", { class: "sb-eyebrow", text: t("Recent", "最近") }));
    var chipRow = el("div", { class: "sb-chip-row" });
    ["All", "Projects", "Worlds"].forEach(function (filterKey) {
      var chip = el("button", {
        type: "button",
        class: "sb-chip",
        "aria-pressed": String(state.recentFilter === filterKey),
        onClick: function () { setState({ recentFilter: filterKey }); },
        text: filterKey === "All" ? t("All", "全部") : filterKey === "Projects" ? t("Projects", "項目") : t("Worlds", "世界"),
      });
      chipRow.appendChild(chip);
    });
    recentHeader.appendChild(chipRow);
    recentHeader.appendChild(el("div", { class: "sb-spacer" }));

    var recentSearchInput = el("input", {
      type: "text",
      id: "backstage-recent-search",
      class: "sb-search-input",
      placeholder: t("Search recent projects and worlds", "搜尋最近嘅項目同世界"),
    });
    var recentRegexOpen = el("button", {
      type: "button",
      id: "backstage-recent-regex-open",
      class: "sb-regex-open",
      title: t("Regex builder", "正則表達式產生器"),
      text: ".*",
    });
    var recentRegexPanel = el(
      "details",
      { id: "backstage-recent-regex", class: "sb-regex-panel" },
      el("summary", { class: "sb-regex-summary", text: t("Search options", "搜尋選項") }),
      el("div", { "data-regex-controls": "backstage-recent" })
    );
    recentHeader.appendChild(recentSearchInput);
    recentHeader.appendChild(recentRegexOpen);
    home.appendChild(recentHeader);
    home.appendChild(recentRegexPanel);

    var recentStatus = el("div", { class: "sb-status", role: "status" });
    home.appendChild(recentStatus);

    var recentTableWrap = el("div", { class: "sb-table-wrap" });
    var recentTable = el(
      "div",
      { class: "sb-table", role: "table", "aria-label": t("Recent projects and worlds", "最近嘅項目同世界") },
      el(
        "div",
        { class: "sb-table-head", role: "row" },
        el("span", { role: "columnheader" }),
        el("span", { role: "columnheader", text: t("Name", "名稱") }),
        el("span", { role: "columnheader", text: t("Platform", "平台") }),
        el("span", { role: "columnheader", text: t("Location", "位置") }),
        el("span", { role: "columnheader", text: t("Opened", "開啟時間") })
      )
    );
    recentTableWrap.appendChild(recentTable);
    home.appendChild(recentTableWrap);
    body.appendChild(home);

    function renderRecent() {
      recentTable.querySelectorAll('[data-row="1"]').forEach(function (node) {
        node.remove();
      });
      var rows = filteredRecents();

      if (state.recentsError === "desktop_only") {
        recentStatus.textContent = t(
          "Recent projects need the desktop app. Running from a browser tab has no sidecar to read them from.",
          "最近項目要用桌面版程式先睇到。喺瀏覽器分頁度冇 sidecar 讀得到。"
        );
        recentTableWrap.hidden = true;
        return;
      }
      if (state.recentsError) {
        recentStatus.textContent = t(
          "Could not read recent projects: ",
          "讀唔到最近嘅項目："
        ) + state.recentsError;
        recentTableWrap.hidden = true;
        return;
      }
      if (state.recents === null) {
        recentStatus.textContent = t("Loading recent projects…", "載入緊最近嘅項目…");
        recentTableWrap.hidden = true;
        return;
      }
      if (state.recents.length === 0) {
        recentStatus.textContent = t(
          "No recent projects yet. Start from a template above, or open a world folder.",
          "重未有最近嘅項目。可以由上面嘅範本開始，或者開一個世界資料夾。"
        );
        recentTableWrap.hidden = true;
        return;
      }
      if (rows.length === 0) {
        recentStatus.textContent = Site.describe
          ? Site.describe(0, "project", state.recentQuery)
          : t("No matches.", "冇搵到。");
        recentTableWrap.hidden = true;
        return;
      }
      recentStatus.textContent = Site.describe
        ? Site.describe(rows.length, "project", state.recentQuery)
        : rows.length + " projects";
      recentTableWrap.hidden = false;
      rows.forEach(function (entry) {
        var row = el(
          "button",
          {
            type: "button",
            class: "sb-table-row",
            "data-row": "1",
            role: "row",
            onClick: function () { openWorldAtPath(entry.path); },
          },
          el("span", { role: "cell", class: "sb-pin" }, entry.pinned ? "★" : "☆"),
          el(
            "span",
            { role: "cell" },
            el("b", { class: "sb-row-name", text: entry.name }),
            el("small", { class: "sb-row-kind", text: entry.kind || "" })
          ),
          el("span", { role: "cell", class: "sb-row-platform", text: entry.platform || "" }),
          el("span", { role: "cell", class: "sb-row-path mono", text: entry.path || "" }),
          el("span", { role: "cell", class: "sb-row-opened", text: entry.opened_label || entry.opened_iso || "" })
        );
        recentTable.appendChild(row);
      });
    }
    refreshers.push(renderRecent);

    function wireRecentSearch() {
      var handle = null;
      function filter(q) {
        state.recentQuery = q ? q.query : recentSearchInput.value;
        if (handle && handle.matches) {
          state.recentMatcher = function (hay) { return handle.matches(hay); };
        } else {
          var needle = recentSearchInput.value.trim().toLowerCase();
          state.recentMatcher = needle
            ? function (hay) { return hay.toLowerCase().indexOf(needle) !== -1; }
            : null;
        }
        renderRecent();
      }
      if (Site.regex && typeof Site.regex.attach === "function") {
        handle = Site.regex.attach({
          name: "backstage-recent",
          input: recentSearchInput,
          openButton: recentRegexOpen,
          panel: recentRegexPanel,
          sample: "1.17 Height · Bedrock 1.17.0.1",
          onChange: filter,
        });
      }
      recentSearchInput.addEventListener("input", function () {
        filter(handle && handle.state ? handle.state() : null);
      });
      if (!handle || !handle.state) {
        // attach() degraded (or Site.regex is absent): it wires no listener of
        // its own for the open button, so the button still has to do
        // something real rather than sit there inert.
        recentRegexOpen.addEventListener("click", function () {
          recentRegexPanel.open = !recentRegexPanel.open;
        });
      }
    }
    wireRecentSearch();
    loadRecents();

    // ==================================================================
    // Open
    // ==================================================================
    var openPage = el("div", { class: "sb-page", "data-sb-panel": "open", hidden: "" });
    openPage.appendChild(el("h1", { class: "sb-heading", text: t("Open", "開啟") }));
    openPage.appendChild(
      el("p", {
        class: "sb-lede",
        text: t(
          "Close the world in game and other tools before opening it here. Amulet edits the files on disk.",
          "打開之前，先喺遊戲同其他工具入面閂咗嗰個世界。Amulet 直接改硬碟上面嘅檔案。"
        ),
      })
    );

    var pathRow = el("div", { class: "sb-path-row" });
    var pathInput = el("input", {
      type: "text",
      class: "sb-path-input",
      placeholder: t("World folder path", "世界資料夾路徑"),
      "aria-label": t("World folder path", "世界資料夾路徑"),
    });
    var browseButton = el("button", {
      type: "button",
      class: "sb-secondary-btn",
      text: t("Browse…", "瀏覽…"),
      disabled: browseAvailable() ? null : "",
      title: browseAvailable()
        ? t("Choose a folder", "選擇資料夾")
        : t("Folder browsing is not wired into this build yet -- paste the path instead.", "呢個版本重未駁通瀏覽資料夾－請直接貼路徑。"),
      onClick: function () {
        var b = bridge();
        if (!b || !b.dialog || typeof b.dialog.chooseFolder !== "function") return;
        b.dialog.chooseFolder().then(function (chosen) {
          if (chosen && chosen.path) {
            pathInput.value = chosen.path;
          }
        });
      },
    });
    var openGoButton = el("button", {
      type: "button",
      class: "sb-primary-btn",
      text: t("Open world", "開啟世界"),
      onClick: function () { openWorldAtPath(pathInput.value); },
    });
    pathRow.appendChild(pathInput);
    pathRow.appendChild(browseButton);
    pathRow.appendChild(openGoButton);
    openPage.appendChild(pathRow);

    var openStatusNode = el("div", { class: "sb-status", role: "status" });
    openPage.appendChild(openStatusNode);

    var openSources = [
      {
        glyph: "▸",
        title: function () { return t("Browse for a world folder", "瀏覽世界資料夾"); },
        hint: function () { return t("Java saves, Bedrock minecraftWorlds, or any world directory.", "Java saves、Bedrock minecraftWorlds，或者任何世界資料夾。"); },
      },
      {
        glyph: "⏳",
        title: function () { return t("Recover from local history", "由本機歷史還原"); },
        hint: function () { return t("Restore a revision as a new, undoable revision.", "將某個修訂版還原做一個新、可以撤銷嘅修訂版。"); },
      },
    ];
    var sourcesGrid = el("div", { class: "sb-sources" });
    openSources.forEach(function (src) {
      sourcesGrid.appendChild(
        el(
          "div",
          { class: "sb-source-card" },
          el("span", { class: "sb-source-glyph", "aria-hidden": "true" }, src.glyph),
          el(
            "span",
            { class: "sb-source-body" },
            el("b", { text: src.title() }),
            el("small", { text: src.hint() })
          )
        )
      );
    });
    openPage.appendChild(sourcesGrid);
    openPage.appendChild(
      el("div", {
        class: "sb-warning",
        text: t(
          "Back up every world before editing it. Conversion overwrites destination chunks at matching coordinates.",
          "編輯之前，記得幫每個世界備份。轉換會喺相同座標覆蓋目標世界嘅 chunk。"
        ),
      })
    );
    body.appendChild(openPage);

    function renderOpen() {
      openGoButton.disabled = state.openBusy;
      openStatusNode.textContent = state.openMessage || "";
    }
    refreshers.push(renderOpen);

    // ==================================================================
    // Project info
    // ==================================================================
    var infoPage = el("div", { class: "sb-page", "data-sb-panel": "info", hidden: "" });
    var infoHeading = el("h1", { class: "sb-heading", text: t("Project info", "項目資訊") });
    var infoSub = el("p", { class: "sb-lede" });
    var infoRowsWrap = el("div", { class: "sb-info-rows" });
    var infoEmpty = el("div", {
      class: "sb-empty",
      text: t(
        "No project is open yet. Open a world from the Open page, or start from a template on Home.",
        "重未打開任何項目。可以喺 Open 頁開一個世界，或者喺 Home 揀個範本開始。"
      ),
    });
    infoPage.appendChild(infoHeading);
    infoPage.appendChild(infoSub);
    infoPage.appendChild(infoEmpty);
    infoPage.appendChild(infoRowsWrap);
    body.appendChild(infoPage);

    function renderInfo() {
      infoRowsWrap.innerHTML = "";
      if (!state.world) {
        infoEmpty.hidden = false;
        infoSub.hidden = true;
        return;
      }
      infoEmpty.hidden = true;
      infoSub.hidden = false;
      infoSub.textContent = state.world.name;
      var rows = [
        { label: t("Project", "項目"), value: state.world.name },
        { label: t("Platform", "平台"), value: state.world.platform },
        { label: t("Version", "版本"), value: Array.isArray(state.world.version) ? state.world.version.join(".") : String(state.world.version) },
        { label: t("Dimensions", "維度"), value: (state.world.dimensions || []).join(", ") },
        { label: t("Path", "路徑"), value: state.world.path },
        { label: t("World ID", "世界編號"), value: state.world.world_id },
      ];
      rows.forEach(function (row) {
        infoRowsWrap.appendChild(
          el(
            "div",
            { class: "sb-info-row" },
            el("span", { class: "sb-info-label", text: row.label }),
            el("span", { class: "sb-info-value mono", text: row.value || "" })
          )
        );
      });
    }
    refreshers.push(renderInfo);

    // ==================================================================
    // Convert
    // ==================================================================
    var convertPage = el("div", { class: "sb-page", "data-sb-panel": "convert", hidden: "" });
    convertPage.appendChild(el("h1", { class: "sb-heading", text: t("Convert", "轉換") }));
    convertPage.appendChild(
      el("p", {
        class: "sb-lede",
        text: t(
          "Merge source-world chunks into a destination world through the format translation layer.",
          "透過格式轉換層，將來源世界嘅 chunk 合併去目標世界。"
        ),
      })
    );
    var convertNote = el("div", { class: "sb-note" });
    convertPage.appendChild(convertNote);
    body.appendChild(convertPage);

    function renderConvert() {
      var formats = Site.electronSidecar && Site.electronSidecar.converterFormats;
      if (!bridge()) {
        convertNote.textContent = t(
          "Conversion needs the desktop app. Running from a browser tab has no sidecar to convert with.",
          "轉換要用桌面版程式。喺瀏覽器分頁度冇 sidecar 可以做轉換。"
        );
      } else if (!formats) {
        convertNote.textContent = t(
          "Loading available formats from the sidecar…",
          "由 sidecar 載入緊可用嘅格式…"
        );
      } else if (formats.length === 0) {
        convertNote.textContent = t(
          "The sidecar reported no available conversion adapters.",
          "Sidecar 話冇任何可用嘅轉換 adapter。"
        );
      } else {
        convertNote.textContent = t(
          formats.length + " conversion adapters available. Select a source world from Open, then choose a destination here.",
          "有 " + formats.length + " 個轉換 adapter 可用。喺 Open 揀個來源世界，然後喺呢度揀目標。"
        );
      }
    }
    refreshers.push(renderConvert);

    // ==================================================================
    // All surfaces
    // ==================================================================
    var featuresPage = el("div", { class: "sb-page", "data-sb-panel": "features", hidden: "" });
    featuresPage.appendChild(el("h1", { class: "sb-heading", text: t("All surfaces", "全部介面") }));
    featuresPage.appendChild(
      el("p", {
        class: "sb-lede",
        text: t(
          "Every window, dialog, tool, and pane in the application. Project-shell surfaces open here; the rest are reachable from the ribbon and the command palette once a project is open.",
          "程式入面嘅每一個視窗、對話盒、工具同面板。項目框架介面喺呢度開；其餘要等開咗項目之後，先可以喺 ribbon 同命令面板搵到。"
        ),
      })
    );
    var featureHeader = el("div", { class: "sb-recent-header" });
    var featureSearchInput = el("input", {
      type: "text",
      id: "backstage-features-search",
      class: "sb-search-input",
      placeholder: t("Search all surfaces", "搜尋全部介面"),
    });
    var featureRegexOpen = el("button", {
      type: "button",
      id: "backstage-features-regex-open",
      class: "sb-regex-open",
      title: t("Regex builder", "正則表達式產生器"),
      text: ".*",
    });
    var featureCount = el("span", { class: "sb-count" });
    featureHeader.appendChild(featureSearchInput);
    featureHeader.appendChild(featureRegexOpen);
    featureHeader.appendChild(featureCount);
    featuresPage.appendChild(featureHeader);
    var featureRegexPanel = el(
      "details",
      { id: "backstage-features-regex", class: "sb-regex-panel" },
      el("summary", { class: "sb-regex-summary", text: t("Search options", "搜尋選項") }),
      el("div", { "data-regex-controls": "backstage-features" })
    );
    featuresPage.appendChild(featureRegexPanel);

    var allFeatures = [];
    var groupsWrap = el("div", { class: "sb-feature-groups" });
    SURFACE_GROUPS.forEach(function (group) {
      var groupNode = el("div", { class: "sb-feature-group" });
      groupNode.appendChild(el("div", { class: "sb-eyebrow", text: group.title() }));
      var grid = el("div", { class: "sb-feature-grid" });
      group.items.forEach(function (item) {
        var record = {
          label: item.label,
          hint: item.hint,
          haystack: (item.label + " " + item.hint + " " + group.title()).toLowerCase(),
          node: null,
        };
        var button = el(
          "button",
          {
            type: "button",
            class: "sb-feature-tile",
            onClick: function () {
              if (item.tab) setState({ tab: item.tab });
              else if (Site.notify) {
                Site.notify(
                  item.label,
                  t(
                    "This surface opens once a project is open; it is not reachable from the backstage yet.",
                    "呢個介面要開咗項目先開得到；backstage 度重未駁通。"
                  )
                );
              }
            },
          },
          el("b", { class: "sb-feature-label", text: item.label }),
          el("small", { class: "sb-feature-hint", text: item.hint })
        );
        record.node = button;
        grid.appendChild(button);
        allFeatures.push(record);
      });
      groupNode.appendChild(grid);
      groupsWrap.appendChild(groupNode);
    });
    featuresPage.appendChild(groupsWrap);
    body.appendChild(featuresPage);

    function renderFeatures() {
      var matcher = state.featureMatcher;
      var visible = 0;
      allFeatures.forEach(function (record) {
        var match = matcher ? matcher(record.haystack) : true;
        record.node.hidden = !match;
        if (match) visible++;
      });
      groupsWrap.querySelectorAll(".sb-feature-group").forEach(function (groupNode, i) {
        var anyVisible = SURFACE_GROUPS[i].items.some(function (_, idx) {
          var flatIndex = 0;
          for (var g = 0; g < i; g++) flatIndex += SURFACE_GROUPS[g].items.length;
          return !allFeatures[flatIndex + idx].node.hidden;
        });
        groupNode.hidden = !anyVisible;
      });
      featureCount.textContent = Site.describe
        ? Site.describe(visible, "surface", state.featureQuery)
        : visible + " of " + allFeatures.length + " surfaces";
    }
    refreshers.push(renderFeatures);

    function wireFeatureSearch() {
      var handle = null;
      function filter() {
        state.featureQuery = featureSearchInput.value;
        if (handle && handle.matches) {
          state.featureMatcher = function (hay) { return handle.matches(hay); };
        } else {
          var needle = featureSearchInput.value.trim().toLowerCase();
          state.featureMatcher = needle ? function (hay) { return hay.indexOf(needle) !== -1; } : null;
        }
        renderFeatures();
      }
      if (Site.regex && typeof Site.regex.attach === "function") {
        handle = Site.regex.attach({
          name: "backstage-features",
          input: featureSearchInput,
          openButton: featureRegexOpen,
          panel: featureRegexPanel,
          sample: "Selection tool · Undo history",
          onChange: filter,
        });
      }
      featureSearchInput.addEventListener("input", filter);
      if (!handle || !handle.state) {
        featureRegexOpen.addEventListener("click", function () {
          featureRegexPanel.open = !featureRegexPanel.open;
        });
      }
    }
    wireFeatureSearch();

    // -------------------------------------------------------------- switch
    function renderTab() {
      navButtons.forEach(function (item) {
        item.node.setAttribute("aria-current", item.key === state.tab ? "page" : "false");
        item.node.classList.toggle("sb-nav-item--active", item.key === state.tab);
      });
      ["home", "open", "info", "convert", "features"].forEach(function (key) {
        panelHidden(body, key, state.tab);
      });
    }
    refreshers.push(renderTab);

    refresh();
  }

  function resolveMountId() {
    // The workspace shell (docs/site/studio.html / studio-shell.js) mounts
    // this lane's view inside "#backstage-view". A shell may override that
    // explicitly; failing either, fall back to a bare "#studio-backstage"
    // container so this module still mounts something real when tested or
    // hosted on its own.
    if (Site.studioBackstage && Site.studioBackstage.mountId) return Site.studioBackstage.mountId;
    if (document.getElementById("backstage-view")) return "backstage-view";
    return "studio-backstage";
  }

  function boot() {
    var id = resolveMountId();
    var root = document.getElementById(id);
    if (!root) return;
    mount(root);
  }

  Site.studioBackstage = Site.studioBackstage || {};
  Site.studioBackstage._state = state;
  Site.studioBackstage._setState = setState;

  Site.ready(boot);
})();
