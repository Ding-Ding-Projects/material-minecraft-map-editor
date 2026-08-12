/* Named appearance presets, user-saved themes, and file export/import.
 *
 * The blank-slate rule: an editor that opens to nothing hands the user an empty
 * canvas and calls it a feature. So the appearance surface offers real starting
 * points, and one of them is explicitly the shipped defaults rather than
 * something invented to look like a default.
 *
 * Every preset is derived from values this site actually reads. A preset that
 * set a key nothing consumes would be a control that does nothing, and the
 * whole point of showing what each one changes is that the claim can be
 * checked. Each preset states exactly which values it sets before it is
 * applied, and applying one is an ordinary recorded change that the local
 * history can undo like any other.
 */
(function () {
  "use strict";

  var site = window.AmuletSite;
  if (!site) return;

  var el = site.el;
  var SAVED_KEY = "appearance.saved";
  var t = function (en, yue) {
    return site.lang.t(en, yue);
  };

  /* The shipped defaults are read from the core rather than copied, so this
   * list and the reset path can never disagree about what "default" means. */
  function shipped() {
    var d = site.settings.DEFAULTS;
    return {
      theme: d.theme,
      density: d.density,
      accent: d.accent,
      scale: d.scale,
      font: d.font,
    };
  }

  var BUILT_IN = [
    {
      id: "shipped",
      en: "As it ships",
      yue: "出廠設定",
      describeEn: "Exactly the values this site was published with.",
      describeYue: "同呢個網站出街嗰陣一模一樣。",
      values: shipped,
    },
    {
      id: "night",
      en: "Night shift",
      yue: "夜更",
      describeEn: "Dark theme, comfortable density, a cooler accent.",
      describeYue: "深色主題、鬆啲嘅密度、凍少少嘅主色。",
      values: function () {
        return { theme: "dark", density: "comfortable", accent: "#8fa8ff", scale: 100 };
      },
    },
    {
      id: "dense",
      en: "Dense reading",
      yue: "密集閱讀",
      describeEn: "Compact density and slightly larger text, for long documents.",
      describeYue: "密啲嘅排版加大少少字，睇長文用。",
      values: function () {
        return { density: "compact", scale: 110, theme: "light" };
      },
    },
    {
      id: "large",
      en: "Larger type",
      yue: "大字",
      describeEn: "150% text with comfortable spacing; nothing else changes.",
      describeYue: "字大到 150%，行距鬆返啲；其他唔郁。",
      values: function () {
        return { scale: 150, density: "comfortable" };
      },
    },
  ];

  var nodes = {};

  function savedThemes() {
    var raw = site.store.get(SAVED_KEY, []);
    return Array.isArray(raw) ? raw : [];
  }

  function persistSaved(list) {
    site.store.set(SAVED_KEY, list);
  }

  function describeValues(values) {
    return Object.keys(values)
      .map(function (key) {
        return key + " = " + String(values[key]);
      })
      .join(" · ");
  }

  function applyValues(values, label) {
    Object.keys(values).forEach(function (key) {
      site.settings.set(key, values[key]);
    });
    if (site.history && typeof site.history.record === "function") {
      try {
        site.history.record({
          action: "appearance-preset",
          label: t("Applied ", "套用咗 ") + label,
          detail: describeValues(values),
        });
      } catch (error) {
        /* history is a convenience, never a precondition */
      }
    }
    site.notify(
      site.lang.emoji("🎨") + t("Appearance applied", "外觀已套用"),
      t(
        label + " — " + describeValues(values),
        label + " —— " + describeValues(values)
      )
    );
    render();
  }

  function currentValues() {
    return {
      theme: site.settings.get("theme"),
      density: site.settings.get("density"),
      accent: site.settings.get("accent"),
      scale: site.settings.get("scale"),
      font: site.settings.get("font"),
    };
  }

  function exportTheme() {
    var payload = {
      kind: "mmwe-site-appearance",
      version: 1,
      exported: new Date().toISOString(),
      values: currentValues(),
    };
    var blob = new Blob([JSON.stringify(payload, null, 2)], {
      type: "application/json",
    });
    var url = URL.createObjectURL(blob);
    var link = el("a", { href: url, download: "appearance.json" });
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    setTimeout(function () {
      URL.revokeObjectURL(url);
    }, 1000);
    site.notify(
      site.lang.emoji("📤") + t("Appearance exported", "外觀已匯出"),
      t(
        "A file you can keep or share; it carries appearance values only.",
        "個檔可以留住或者畀人；入面淨係外觀設定。"
      )
    );
  }

  function importTheme(file, report) {
    var reader = new FileReader();
    reader.onload = function () {
      var parsed;
      try {
        parsed = JSON.parse(String(reader.result));
      } catch (error) {
        report(t("That file is not valid JSON.", "個檔唔係正常 JSON。"));
        return;
      }
      if (!parsed || parsed.kind !== "mmwe-site-appearance") {
        report(
          t(
            "That file is not an appearance export from this site.",
            "個檔唔係呢個網站匯出嘅外觀檔。"
          )
        );
        return;
      }
      if (Number(parsed.version) > 1) {
        report(
          t(
            "That file was written by a newer version and is not being guessed at.",
            "個檔係新版寫嘅，唔會亂估，所以唔會套用。"
          )
        );
        return;
      }
      var values = parsed.values || {};
      /* Only keys this site actually reads are applied; anything else is
       * reported rather than silently dropped. */
      var known = Object.keys(shipped());
      var accepted = {};
      var ignored = [];
      Object.keys(values).forEach(function (key) {
        if (known.indexOf(key) >= 0) accepted[key] = values[key];
        else ignored.push(key);
      });
      if (!Object.keys(accepted).length) {
        report(t("That file set nothing this site reads.", "個檔冇一樣嘢係呢度用得着。"));
        return;
      }
      applyValues(accepted, t("an imported appearance", "匯入嘅外觀"));
      report(
        ignored.length
          ? t(
              "Applied. These keys were ignored because nothing reads them: " +
                ignored.join(", "),
              "已套用。呢啲 key 冇人用到，所以略過咗：" + ignored.join("、")
            )
          : ""
      );
    };
    reader.readAsText(file);
  }

  function render() {
    var host = nodes.list;
    if (!host) return;
    host.textContent = "";
    var saved = savedThemes();

    BUILT_IN.forEach(function (preset) {
      var values = preset.values();
      host.appendChild(
        el(
          "div",
          { class: "sched-rule" },
          el("strong", { text: t(preset.en, preset.yue) }),
          el("p", { class: "muted", text: t(preset.describeEn, preset.describeYue) }),
          el("p", { class: "muted", text: describeValues(values) }),
          el("button", {
            class: "button button-tonal",
            type: "button",
            text: t("Start from this", "由呢個開始"),
            onClick: function () {
              applyValues(values, t(preset.en, preset.yue));
            },
          })
        )
      );
    });

    saved.forEach(function (theme, index) {
      host.appendChild(
        el(
          "div",
          { class: "sched-rule" },
          el("strong", { text: theme.name }),
          el("p", { class: "muted", text: describeValues(theme.values) }),
          el(
            "div",
            { class: "row-actions" },
            el("button", {
              class: "button button-tonal",
              type: "button",
              text: t("Apply", "套用"),
              onClick: function () {
                applyValues(theme.values, theme.name);
              },
            }),
            el("button", {
              class: "button button-text",
              type: "button",
              text: t("Delete", "刪除"),
              onClick: function (event) {
                site.confirmDestructive({
                  title: t("Delete this saved theme", "刪除呢個儲存咗嘅外觀"),
                  detail: t(
                    'Deleting "' + theme.name + '" cannot be undone from here.',
                    "刪咗「" + theme.name + "」喺呢度撤銷唔到。"
                  ),
                  anchor: event.target,
                  onConfirm: function () {
                    var list = savedThemes();
                    list.splice(index, 1);
                    persistSaved(list);
                    render();
                  },
                });
              },
            })
          )
        )
      );
    });
  }

  function mount() {
    var host = document.getElementById("presets-root");
    if (!host) return;
    nodes.list = el("div", { id: "presets-list" });
    var report = el("p", { class: "field-error", role: "alert" });
    var nameInput = el("input", {
      type: "text",
      id: "preset-name",
      placeholder: t("Name this appearance", "改個名"),
    });
    var fileInput = el("input", {
      type: "file",
      accept: "application/json,.json",
      id: "preset-file",
      onChange: function (e) {
        if (e.target.files && e.target.files[0]) {
          importTheme(e.target.files[0], function (message) {
            report.textContent = message;
          });
        }
      },
    });

    host.appendChild(
      el("p", {
        class: "muted",
        text: t(
          "Starting points, including the values this site actually shipped " +
            "with. Each says exactly what it sets before you apply it, and " +
            "applying one is an ordinary change you can undo.",
          "幾個起手點，包括呢個網站出廠嗰套。撳之前會講明改邊幾樣，" +
            "而且撳完照樣可以 undo。"
        ),
      })
    );
    host.appendChild(nodes.list);
    host.appendChild(
      el(
        "div",
        { class: "row-actions" },
        nameInput,
        el("button", {
          class: "button button-filled",
          type: "button",
          text: t("Save the current appearance", "儲存而家個樣"),
          onClick: function () {
            var name = nameInput.value.trim();
            if (!name) {
              report.textContent = t(
                "Give it a name so you can find it later.",
                "改個名，第日搵返容易啲。"
              );
              return;
            }
            var list = savedThemes();
            list.push({ name: name, values: currentValues() });
            persistSaved(list);
            nameInput.value = "";
            report.textContent = "";
            render();
          },
        }),
        el("button", {
          class: "button button-tonal",
          type: "button",
          text: t("Export to a file", "匯出做檔案"),
          onClick: exportTheme,
        })
      )
    );
    host.appendChild(
      el("p", { class: "field" },
        el("label", { for: "preset-file", text: t("Import an appearance file", "匯入外觀檔") }))
    );
    host.appendChild(fileInput);
    host.appendChild(report);

    render();

    site.registerPaletteSource(function () {
      return BUILT_IN.map(function (preset) {
        return {
          label: t("Appearance: ", "外觀：") + t(preset.en, preset.yue),
          hint: describeValues(preset.values()),
          tab: "settings",
          run: function () {
            applyValues(preset.values(), t(preset.en, preset.yue));
          },
        };
      });
    });
  }

  site.ready(mount);
  site.settings.onChange(function (key) {
    if ((key === null || key === "language" || key === "emoji") && nodes.list) {
      render();
    }
  });

  window.AmuletPresets = {
    builtIn: BUILT_IN,
    shipped: shipped,
    _apply: applyValues,
  };
})();
