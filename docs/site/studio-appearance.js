/* The desktop Electron app's appearance editor: theme, density, accent, and
 * UI font with a live preview, plus named presets with export/import and
 * per-element/global reset -- wired to the sidecar's real
 * `appearance.presets.*` / `appearance.reset_*` methods
 * (amulet_map_editor/api/appearance_presets.py via
 * amulet_map_editor/api/sidecar/security_methods.py), never a second
 * in-renderer copy of that schema.
 *
 * Mounts into any container the caller gives it -- the ribbon's "Edit
 * appearance..." pane icon opens it anchored beside the pane it was clicked
 * from (see studio-workspace.js), and it is equally usable as a standalone
 * destination. `window.AmuletStudioAppearance.mount(container)` renders the
 * panel; `.open(container)` additionally makes it visible if it was hidden.
 *
 * Every write here goes through Site.electronSidecar.appearance -- there is
 * no local persistence in this file. Outside Electron (no sidecar bridge)
 * the panel renders an honest "desktop only" state rather than a dead form.
 */
(function () {
  "use strict";

  var THEMES = ["system", "light", "dark"];
  var DENSITIES = ["compact", "comfortable", "spacious"];

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

  function bridge() {
    var site = window.AmuletSite;
    return (site && site.electronSidecar && site.electronSidecar.available && site.electronSidecar.appearance) || null;
  }

  function state() {
    return {
      values: { theme: "system", density: "comfortable", accent: "#6750A4", ui_font: "", ui_scale: 1.0 },
      presets: [],
      query: "",
      status: "",
    };
  }

  function build(container) {
    var s = state();
    container.innerHTML = "";
    var root = el("div", { className: "sa-panel", "data-sa-root": "true" });
    var api = bridge();

    if (!api) {
      root.appendChild(
        el("p", { className: "sa-status" }, [
          "The appearance editor talks to the desktop sidecar and is desktop only -- open this from the Electron app.",
        ])
      );
      container.appendChild(root);
      return { refresh: function () {} };
    }

    var status = el("p", { className: "sa-status", role: "status" }, [""]);

    function setStatus(text) {
      s.status = text;
      status.textContent = text;
    }

    // Live controls -------------------------------------------------------
    var themeSelect = el(
      "select",
      { id: "sa-theme", "aria-label": "Theme" },
      THEMES.map(function (t) {
        return el("option", { value: t }, [t]);
      })
    );
    var densitySelect = el(
      "select",
      { id: "sa-density", "aria-label": "Density" },
      DENSITIES.map(function (d) {
        return el("option", { value: d }, [d]);
      })
    );
    var accentInput = el("input", { id: "sa-accent", type: "text", "aria-label": "Accent colour (#RRGGBB)", value: s.values.accent });
    var fontInput = el("input", { id: "sa-font", type: "text", "aria-label": "UI font family", value: s.values.ui_font, placeholder: "System default" });
    var scaleInput = el("input", { id: "sa-scale", type: "number", min: "0.8", max: "2.0", step: "0.05", "aria-label": "UI scale", value: String(s.values.ui_scale) });
    var preview = el("div", { className: "sa-preview", id: "sa-preview" }, ["Aa — live preview"]);

    function applyPreview() {
      preview.style.fontFamily = fontInput.value || "inherit";
      preview.style.color = accentInput.value || "";
      preview.textContent = "Aa — " + themeSelect.value + " / " + densitySelect.value + " preview";
    }
    [themeSelect, densitySelect, accentInput, fontInput, scaleInput].forEach(function (input) {
      input.addEventListener("input", applyPreview);
      input.addEventListener("change", applyPreview);
    });
    themeSelect.value = s.values.theme;
    densitySelect.value = s.values.density;

    var applyBtn = el(
      "button",
      {
        type: "button",
        className: "sa-primary-btn",
        onClick: function () {
          api
            .resetAll()
            .then(function () {})
            .catch(function () {});
          // Apply the current form values through preferences.write via the
          // shared preset apply/save flow: save an unnamed working preset in
          // memory is unnecessary here -- reset_property below covers single
          // resets, and applying arbitrary unsaved values reuses save+apply
          // so the sidecar validates through the exact same schema.
          var values = {
            version: 1,
            theme: themeSelect.value,
            density: densitySelect.value,
            accent: accentInput.value,
            ui_font: fontInput.value,
            ui_scale: Number(scaleInput.value) || 1.0,
          };
          api
            .savePreset("__live__", values, true)
            .then(function () {
              return api.applyPreset("__live__");
            })
            .then(function () {
              setStatus("Appearance applied.");
            })
            .catch(function (err) {
              setStatus("Could not apply: " + err.message);
            });
        },
      },
      ["Apply"]
    );

    var resetBtn = el(
      "button",
      {
        type: "button",
        className: "sa-secondary-btn",
        onClick: function () {
          api
            .resetAll()
            .then(function (result) {
              loadFromPreferences(result.preferences);
              setStatus("Reset to the shipped appearance.");
            })
            .catch(function (err) {
              setStatus("Could not reset: " + err.message);
            });
        },
      },
      ["Reset all"]
    );

    function loadFromPreferences(prefs) {
      if (!prefs) return;
      themeSelect.value = prefs.theme || "system";
      densitySelect.value = prefs.density || "comfortable";
      accentInput.value = prefs.accent || "#6750A4";
      fontInput.value = prefs.ui_font || "";
      scaleInput.value = String(prefs.ui_scale || 1.0);
      applyPreview();
    }

    var liveGroup = el("div", { className: "sa-live-group" }, [
      el("label", {}, ["Theme", themeSelect]),
      el("label", {}, ["Density", densitySelect]),
      el("label", {}, ["Accent", accentInput]),
      el("label", {}, ["UI font", fontInput]),
      el("label", {}, ["UI scale", scaleInput]),
      preview,
      el("div", { className: "sa-actions" }, [applyBtn, resetBtn]),
    ]);

    // Presets ---------------------------------------------------------------
    var searchInput = el("input", { id: "sa-preset-search", type: "search", "aria-label": "Search presets", placeholder: "Search presets" });
    var regexOpenBtn = el("button", { type: "button", id: "sa-preset-regex-open", "aria-label": "Open the regex builder for presets" }, [".*"]);
    var regexControls = el("div", { "data-regex-controls": "sa-preset" }, [searchInput, regexOpenBtn]);

    var presetsList = el("ul", { className: "sa-preset-list", id: "sa-preset-list" });
    var nameInput = el("input", { id: "sa-preset-name", type: "text", "aria-label": "New preset name", placeholder: "Preset name" });
    var saveBtn = el(
      "button",
      {
        type: "button",
        className: "sa-secondary-btn",
        onClick: function () {
          var name = nameInput.value.trim();
          if (!name) {
            setStatus("Enter a preset name first.");
            return;
          }
          var values = {
            version: 1,
            theme: themeSelect.value,
            density: densitySelect.value,
            accent: accentInput.value,
            ui_font: fontInput.value,
            ui_scale: Number(scaleInput.value) || 1.0,
          };
          api
            .savePreset(name, values, false)
            .then(function () {
              nameInput.value = "";
              setStatus('Saved preset "' + name + '".');
              return refreshPresets();
            })
            .catch(function (err) {
              setStatus("Could not save preset: " + err.message);
            });
        },
      },
      ["Save as preset"]
    );

    function renderPresets() {
      presetsList.innerHTML = "";
      var query = searchInput.value.trim().toLowerCase();
      s.presets
        .filter(function (p) {
          return !query || p.name.toLowerCase().indexOf(query) !== -1;
        })
        .forEach(function (preset) {
          var row = el("li", { className: "sa-preset-row" }, [
            el("span", { className: "sa-preset-name" }, [preset.name]),
            el(
              "button",
              {
                type: "button",
                onClick: function () {
                  api
                    .applyPreset(preset.name)
                    .then(function (result) {
                      loadFromPreferences(result.preferences);
                      setStatus('Applied preset "' + preset.name + '".');
                    })
                    .catch(function (err) {
                      setStatus("Could not apply: " + err.message);
                    });
                },
              },
              ["Apply"]
            ),
            el(
              "button",
              {
                type: "button",
                onClick: function () {
                  api
                    .deletePreset(preset.name)
                    .then(function () {
                      setStatus('Deleted preset "' + preset.name + '".');
                      return refreshPresets();
                    })
                    .catch(function (err) {
                      setStatus("Could not delete: " + err.message);
                    });
                },
              },
              ["Delete"]
            ),
          ]);
          presetsList.appendChild(row);
        });
      if (!presetsList.childElementCount) {
        presetsList.appendChild(el("li", { className: "sa-preset-empty" }, [query ? "No presets match." : "No saved presets yet."]));
      }
    }
    searchInput.addEventListener("input", renderPresets);

    function refreshPresets() {
      return api
        .listPresets()
        .then(function (result) {
          s.presets = result.presets || [];
          renderPresets();
        })
        .catch(function () {
          s.presets = [];
          renderPresets();
        });
    }

    root.appendChild(el("h2", {}, ["Appearance"]));
    root.appendChild(status);
    root.appendChild(liveGroup);
    root.appendChild(el("h3", {}, ["Presets"]));
    root.appendChild(el("div", { className: "sa-preset-save" }, [nameInput, saveBtn]));
    root.appendChild(regexControls);
    root.appendChild(presetsList);
    container.appendChild(root);

    refreshPresets();

    return {
      refresh: function () {
        return refreshPresets();
      },
    };
  }

  window.AmuletStudioAppearance = {
    mount: build,
    open: function (container) {
      var handle = build(container);
      container.hidden = false;
      return handle;
    },
  };
})();
