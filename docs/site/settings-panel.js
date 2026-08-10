/* The settings grid.
 *
 * Every card here owns three obligations, in this order: a label, the real
 * control, and two <small> lines -- what the setting does, and where its
 * current value actually came from. A card that renders a control without
 * those lines is a control nobody can reason about, so the builders below
 * cannot produce one.
 *
 * This file also applies the settings it stores. Application is idempotent
 * (same class, same custom property, same text), so it is safe for another
 * module to apply them too; what is not safe is for nobody to.
 */
(function () {
  "use strict";

  var Site = window.AmuletSite;
  if (!Site) return;

  var el = Site.el;
  var settings = Site.settings;
  var lang = Site.lang;
  var root = document.documentElement;

  var SHIPPED = settings.DEFAULTS || {};
  var KEYS = Object.keys(SHIPPED);
  var DEFAULT_ACCENT = SHIPPED.accent || "#4d5f92";
  var SHIPPED_BRAND = SHIPPED.brand || "Material Minecraft World Editor";
  var ORIGINAL_TITLE = document.title;

  // Every stack ends in a CJK-capable family: the Cantonese copy has to stay
  // legible when the leading family carries no Chinese glyphs.
  var FONT_STACKS = {
    "system-ui": 'system-ui, "Segoe UI", "PingFang HK", "Microsoft JhengHei", "Noto Sans CJK HK"',
    segoe: '"Segoe UI", Tahoma, "Microsoft JhengHei", "PingFang HK", "Noto Sans CJK HK"',
    georgia: 'Georgia, "Times New Roman", "PMingLiU", "Songti HK", "Noto Serif CJK HK", serif',
    mono: '"Cascadia Code", "Cascadia Mono", Consolas, ui-monospace, "Noto Sans Mono CJK HK", monospace',
  };

  var SPEECH_AVAILABLE =
    typeof window.speechSynthesis !== "undefined" &&
    typeof window.SpeechSynthesisUtterance === "function";

  // ------------------------------------------------------------------ copy
  function t(en, yue) {
    return lang.t(en, yue);
  }

  function pick(value) {
    return typeof value === "string" ? value : t(value[0], value[1]);
  }

  function english(value) {
    return typeof value === "string" ? value : value[0];
  }

  // Levels 4 and 5 are the playful half of the slider. Both variants of a line
  // state the same facts; only the voice moves.
  function helpText(def) {
    var en = def.help.en[lang.funny("en") >= 4 ? 1 : 0];
    var yue = def.help.yue[lang.funny("yue") >= 4 ? 1 : 0];
    var line = t(en, yue);
    return def.helpSuffix ? line + " " + def.helpSuffix() : line;
  }

  // ---------------------------------------------------------------- colour
  function clamp(value, low, high) {
    return value < low ? low : value > high ? high : value;
  }

  function normaliseHex(value) {
    var raw = String(value == null ? "" : value).trim();
    if (/^#[0-9a-f]{3}$/i.test(raw)) {
      raw =
        "#" +
        raw.charAt(1) + raw.charAt(1) +
        raw.charAt(2) + raw.charAt(2) +
        raw.charAt(3) + raw.charAt(3);
    }
    return /^#[0-9a-f]{6}$/i.test(raw) ? raw.toLowerCase() : null;
  }

  function hexToRgb(hex) {
    var raw = hex.slice(1);
    return [0, 2, 4].map(function (index) {
      return parseInt(raw.slice(index, index + 2), 16);
    });
  }

  function rgbToHex(rgb) {
    return (
      "#" +
      rgb
        .map(function (channel) {
          var byte = clamp(Math.round(channel), 0, 255).toString(16);
          return byte.length === 1 ? "0" + byte : byte;
        })
        .join("")
    );
  }

  function rgbToHsl(rgb) {
    var values = rgb.map(function (channel) {
      return channel / 255;
    });
    var max = Math.max(values[0], values[1], values[2]);
    var min = Math.min(values[0], values[1], values[2]);
    var delta = max - min;
    var light = (max + min) / 2;
    var hue = 0;
    var saturation = 0;
    if (delta) {
      saturation = delta / (1 - Math.abs(2 * light - 1));
      if (max === values[0]) hue = 60 * (((values[1] - values[2]) / delta) % 6);
      else if (max === values[1]) hue = 60 * ((values[2] - values[0]) / delta + 2);
      else hue = 60 * ((values[0] - values[1]) / delta + 4);
    }
    return [
      Math.round((hue + 360) % 360),
      Math.round(saturation * 100),
      Math.round(light * 100),
    ];
  }

  function hslToRgb(hsl) {
    var h = ((hsl[0] % 360) + 360) % 360 / 360;
    var s = clamp(hsl[1], 0, 100) / 100;
    var l = clamp(hsl[2], 0, 100) / 100;
    var chroma = (1 - Math.abs(2 * l - 1)) * s;
    var x = chroma * (1 - Math.abs(((h * 6) % 2) - 1));
    var m = l - chroma / 2;
    var sectors =
      h < 1 / 6 ? [chroma, x, 0]
      : h < 2 / 6 ? [x, chroma, 0]
      : h < 3 / 6 ? [0, chroma, x]
      : h < 4 / 6 ? [0, x, chroma]
      : h < 5 / 6 ? [x, 0, chroma]
      : [chroma, 0, x];
    return sectors.map(function (channel) {
      return (channel + m) * 255;
    });
  }

  function luminance(rgb) {
    var channels = rgb.map(function (channel) {
      var value = channel / 255;
      return value <= 0.03928 ? value / 12.92 : Math.pow((value + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
  }

  function contrastRatio(a, b) {
    var first = luminance(a);
    var second = luminance(b);
    return (Math.max(first, second) + 0.05) / (Math.min(first, second) + 0.05);
  }

  function parseTriple(value, prefix) {
    var raw = String(value == null ? "" : value).trim().toLowerCase();
    var open = raw.indexOf("(");
    if (open !== -1) {
      if (raw.slice(0, open).replace(/a$/, "") !== prefix) return null;
      if (raw.charAt(raw.length - 1) !== ")") return null;
      raw = raw.slice(open + 1, -1);
    }
    var parts = raw.split(/[\s,/]+/).filter(function (part) {
      return part !== "";
    });
    if (parts.length !== 3) return null;
    var numbers = [];
    for (var i = 0; i < 3; i++) {
      var part = parts[i];
      var percent = part.charAt(part.length - 1) === "%";
      if (percent) part = part.slice(0, -1);
      if (!/^\d+(\.\d+)?$/.test(part)) return null;
      if (prefix === "hsl" && i > 0 && !percent) return null;
      numbers.push(Number(part));
    }
    if (prefix === "rgb") {
      if (numbers.some(function (n) { return n > 255; })) return null;
      return numbers.map(Math.round);
    }
    if (numbers[0] > 360 || numbers[1] > 100 || numbers[2] > 100) return null;
    return numbers;
  }

  function surfaceHex() {
    try {
      return normaliseHex(window.getComputedStyle(root).getPropertyValue("--surface"));
    } catch (error) {
      return null;
    }
  }

  // ------------------------------------------------------------ application
  var colourMedia = window.matchMedia
    ? window.matchMedia("(prefers-color-scheme: dark)")
    : null;

  function applyLanguage() {
    root.setAttribute("lang", lang.mode() === "cantonese" ? "zh-HK" : "en");
  }

  function applyTheme() {
    var choice = settings.get("theme");
    var dark = choice === "dark" || (choice === "system" && !!(colourMedia && colourMedia.matches));
    root.classList.toggle("dark", dark);
    root.style.colorScheme = dark ? "dark" : "light";
  }

  function applyDensity() {
    root.setAttribute("data-density", String(settings.get("density")));
  }

  function applyAccent() {
    var hex = normaliseHex(settings.get("accent")) || DEFAULT_ACCENT;
    root.style.setProperty("--primary", hex);
    root.style.setProperty("--accent", hex);
    // A user-chosen accent can land anywhere on the ramp, so the text that sits
    // on top of it is chosen by measurement rather than assumed to be white.
    var rgb = hexToRgb(hex);
    var onPrimary =
      contrastRatio(rgb, [255, 255, 255]) >= contrastRatio(rgb, [0, 0, 0])
        ? "#ffffff"
        : "#000000";
    root.style.setProperty("--on-primary", onPrimary);
  }

  function applyFont() {
    var key = String(settings.get("font"));
    root.style.setProperty("--site-font", FONT_STACKS[key] || FONT_STACKS["system-ui"]);
  }

  function applyScale() {
    var percent = clamp(Number(settings.get("scale")) || 100, 80, 200);
    root.style.setProperty("--ui-scale", String(percent / 100));
  }

  function applyMotion() {
    var forced = settings.get("reducedMotion") === true;
    if (forced) {
      root.setAttribute("data-reduced-motion", "true");
      root.style.scrollBehavior = "auto";
    } else {
      root.removeAttribute("data-reduced-motion");
      root.style.scrollBehavior = "";
    }
  }

  function applyBrand() {
    var name = String(settings.get("brand") == null ? "" : settings.get("brand")).trim() || SHIPPED_BRAND;
    var label = document.getElementById("brand-label");
    var footer = document.getElementById("footer-brand");
    if (label) label.textContent = name;
    if (footer) footer.textContent = name;
    var anchor = document.querySelector(".brand");
    // The visible name must be part of the accessible name, or the two disagree.
    if (anchor && anchor.hasAttribute("aria-label")) anchor.setAttribute("aria-label", name + " home");
    document.title =
      ORIGINAL_TITLE.indexOf(SHIPPED_BRAND) === 0
        ? name + ORIGINAL_TITLE.slice(SHIPPED_BRAND.length)
        : name;
  }

  function applyNarrator() {
    if (SPEECH_AVAILABLE && settings.get("narrator") !== true) {
      try {
        window.speechSynthesis.cancel();
      } catch (error) {
        /* a refused speech engine is not a reason to stop rendering */
      }
    }
  }

  function applyAll() {
    applyLanguage();
    applyTheme();
    applyDensity();
    applyAccent();
    applyFont();
    applyScale();
    applyMotion();
    applyBrand();
    applyNarrator();
  }

  function reducedMotion() {
    if (settings.get("reducedMotion") === true) return true;
    try {
      return !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
    } catch (error) {
      return false;
    }
  }

  function speak(text) {
    if (!SPEECH_AVAILABLE || settings.get("narrator") !== true || !text) return;
    try {
      var synth = window.speechSynthesis;
      synth.cancel(); // one utterance at a time; a queue would talk over itself
      var utterance = new window.SpeechSynthesisUtterance(text);
      utterance.lang = lang.mode() === "cantonese" ? "zh-HK" : "en-US";
      synth.speak(utterance);
    } catch (error) {
      /* speech is decoration; a browser refusing it changes nothing else */
    }
  }

  // ----------------------------------------------------------------- style
  var STYLE_ID = "settings-panel-style";
  var PANEL_CSS = [
    ".setting-card{scroll-margin-top:120px}",
    // styles.css gives these elements a display value, and an author rule beats
    // the user-agent [hidden] rule outright, so hiding one needs saying twice.
    ".setting-card[hidden]{display:none}",
    ".setting-card .button[hidden]{display:none}",
    ".setting-control{display:grid;gap:8px}",
    ".setting-row{display:flex;align-items:center;gap:10px;flex-wrap:wrap}",
    ".setting-row>label{font-size:.78rem;font-weight:650;color:var(--secondary);min-width:3.4rem}",
    ".setting-row>input[type=text]{flex:1;min-width:9rem;border:1px solid var(--outline-variant);border-radius:10px;padding:0 10px;background:transparent;color:inherit}",
    ".setting-slider{display:flex;align-items:center;gap:12px}",
    ".setting-slider input[type=range]{flex:1;min-width:8rem;accent-color:var(--primary)}",
    ".setting-readout{font-variant-numeric:tabular-nums;white-space:nowrap}",
    ".setting-note{color:var(--secondary);font-size:.78rem}",
    '.setting-note[data-state="error"]{color:#8c1d18;font-weight:700}',
    '.dark .setting-note[data-state="error"]{color:#ffb4ab}',
    ".setting-card .setting-check{display:flex;align-items:center;gap:10px}",
    ".setting-card .setting-check input[type=checkbox]{width:22px;height:22px;min-height:0;margin:0;accent-color:var(--primary)}",
    ".setting-card .setting-check label{font-weight:600}",
    ".setting-card input[type=text],.setting-card input[type=search]{border:1px solid var(--outline-variant);border-radius:10px;padding:0 12px;background:transparent;color:inherit}",
    ".setting-actions{display:flex;gap:10px;flex-wrap:wrap;align-items:center}",
    ".setting-card :focus-visible{outline:3px solid var(--primary);outline-offset:2px}",
    ".setting-card [disabled]{opacity:.62;cursor:not-allowed}",
    '.setting-danger[data-armed="true"]{background:#8c1d18;color:#fff}',
    // Comfortable is the shipped middle; the other two levels have to differ
    // visibly or the control is decoration.
    ':root[data-density="spacious"] .page-section{padding-top:112px;padding-bottom:140px}',
    ':root[data-density="spacious"] .feature-card,:root[data-density="spacious"] .community-card,:root[data-density="spacious"] .setting-card{padding:34px}',
    ':root[data-density="spacious"] .settings-grid,:root[data-density="spacious"] .card-grid{gap:24px}',
    ':root[data-density="compact"] .settings-grid,:root[data-density="compact"] .card-grid{gap:10px}',
    ':root[data-reduced-motion="true"] *,:root[data-reduced-motion="true"] *::before,:root[data-reduced-motion="true"] *::after{animation-duration:1ms !important;animation-iteration-count:1 !important;transition-duration:1ms !important;scroll-behavior:auto !important}',
  ].join("");

  function installStyle() {
    if (document.getElementById(STYLE_ID)) return;
    var style = el("style", { id: STYLE_ID });
    style.textContent = PANEL_CSS;
    (document.head || root).appendChild(style);
  }

  // -------------------------------------------------------------- controls
  function labelledRow(labelPair, control) {
    var node = el("label", { for: control.id });
    return { node: el("div", { class: "setting-row" }, node, control), label: node, text: labelPair };
  }

  function repairUnknown(key, value, allowed) {
    // Storage can be edited by hand. A control must never display one value
    // while another is stored, so an unrecognised value is written back.
    if (allowed.indexOf(String(value)) !== -1) return String(value);
    var fallback = String(SHIPPED[key]);
    settings.set(key, SHIPPED[key]);
    return fallback;
  }

  function buildSelect(def, id) {
    var options = def.options.map(function (option) {
      return { value: option[0], label: option[1], node: el("option", { value: option[0] }) };
    });
    var values = options.map(function (option) {
      return option.value;
    });
    var select = el("select", {
      id: id,
      "aria-labelledby": id + "-label",
      "aria-describedby": id + "-help",
      onchange: function () {
        settings.set(def.key, select.value);
      },
    });
    options.forEach(function (option) {
      select.appendChild(option.node);
    });
    return {
      node: select,
      focus: select,
      copy: function () {
        options.forEach(function (option) {
          option.node.textContent = pick(option.label);
        });
      },
      sync: function () {
        var value = repairUnknown(def.key, settings.get(def.key), values);
        if (select.value !== value) select.value = value;
      },
      value: function () {
        var current = String(settings.get(def.key));
        var match = options.filter(function (option) {
          return option.value === current;
        })[0];
        return match ? english(match.label) + " (" + current + ")" : current;
      },
    };
  }

  function buildRange(def, id) {
    var input = el("input", {
      type: "range",
      id: id,
      min: String(def.min),
      max: String(def.max),
      step: String(def.step || 1),
      "aria-labelledby": id + "-label",
      "aria-describedby": id + "-help",
      oninput: function () {
        settings.set(def.key, Number(input.value));
      },
    });
    // The slider announces its own value, so the visible readout is duplicate
    // noise for assistive technology; aria-valuetext carries the unit instead.
    var readout = el("span", { class: "setting-readout", "aria-hidden": "true" });
    return {
      node: el("div", { class: "setting-control" }, el("div", { class: "setting-slider" }, input, readout)),
      focus: input,
      sync: function () {
        var step = def.step || 1;
        var raw = clamp(Number(settings.get(def.key)) || def.min, def.min, def.max);
        // A range input snaps an off-step value on assignment; snapping first
        // keeps the readout and the thumb from disagreeing.
        var value = def.min + Math.round((raw - def.min) / step) * step;
        if (input.value !== String(value)) input.value = String(value);
        readout.textContent = def.readout(value);
        input.setAttribute("aria-valuetext", def.valueText(value));
      },
      value: function () {
        return def.readout(Number(settings.get(def.key)));
      },
    };
  }

  function buildCheckbox(def, id) {
    var input = el("input", {
      type: "checkbox",
      id: id,
      "aria-describedby": id + "-help",
      onchange: function () {
        settings.set(def.key, input.checked);
      },
    });
    var label = el("label", { for: id });
    if (def.unavailable) input.disabled = true;
    return {
      node: el("div", { class: "setting-check" }, input, label),
      focus: input,
      copy: function () {
        label.textContent = pick(def.action);
      },
      sync: function () {
        input.checked = settings.get(def.key) === true;
      },
      value: function () {
        return settings.get(def.key) === true ? "on enabled" : "off disabled";
      },
    };
  }

  function buildText(def, id) {
    var input = el("input", {
      type: "text",
      id: id,
      maxlength: "80",
      autocomplete: "off",
      spellcheck: "false",
      "aria-labelledby": id + "-label",
      "aria-describedby": id + "-help",
      oninput: function () {
        settings.set(def.key, input.value);
      },
    });
    return {
      node: input,
      focus: input,
      sync: function () {
        var value = String(settings.get(def.key) == null ? "" : settings.get(def.key));
        if (input.value !== value) input.value = value;
      },
      value: function () {
        return String(settings.get(def.key) || "");
      },
    };
  }

  function buildAccent(def, id) {
    var origin = null; // the field the user is editing, so it is never rewritten

    var colour = el("input", { type: "color", id: id, "aria-describedby": id + "-help " + id + "-contrast" });
    var hue = el("input", { type: "range", id: id + "-hue", min: "0", max: "359", step: "1" });
    var hex = el("input", { type: "text", id: id + "-hex", maxlength: "7", autocomplete: "off", spellcheck: "false" });
    var rgb = el("input", { type: "text", id: id + "-rgb", maxlength: "24", autocomplete: "off", spellcheck: "false" });
    var hsl = el("input", { type: "text", id: id + "-hsl", maxlength: "24", autocomplete: "off", spellcheck: "false" });
    var note = el("small", { class: "setting-note", id: id + "-note", "aria-live": "polite" });
    var contrast = el("small", { class: "setting-note", id: id + "-contrast" });

    var rows = [
      labelledRow(["Picker", "選色"], colour),
      labelledRow(["Hue", "色相"], hue),
      labelledRow(["HEX", "HEX"], hex),
      labelledRow(["RGB", "RGB"], rgb),
      labelledRow(["HSL", "HSL"], hsl),
    ];

    function setNote(text, isError) {
      if (note.textContent === text && note.getAttribute("data-state") === (isError ? "error" : null)) return;
      note.textContent = text;
      if (isError) note.setAttribute("data-state", "error");
      else note.removeAttribute("data-state");
    }

    function updateContrast(value) {
      var surface = surfaceHex();
      if (!surface) {
        contrast.textContent = t(
          "The page surface colour could not be read, so no contrast ratio is shown.",
          "讀唔到頁面底色，所以唔顯示對比度。"
        );
        return;
      }
      var ratio = contrastRatio(hexToRgb(value), hexToRgb(surface));
      var shown = ratio.toFixed(2);
      var en =
        "Contrast " + shown + ":1 against the page surface " + surface + " — " +
        (ratio >= 4.5
          ? "meets WCAG AA for body text (4.5:1)."
          : ratio >= 3
          ? "meets WCAG AA for large text (3:1) only, and is below 4.5:1 for body text."
          : "below the 3:1 minimum even for large text.");
      var yue =
        "同頁面底色 " + surface + " 嘅對比度係 " + shown + ":1 — " +
        (ratio >= 4.5
          ? "達到 WCAG AA 正文標準（4.5:1）。"
          : ratio >= 3
          ? "只達到大字 AA（3:1），未夠正文嘅 4.5:1。"
          : "連大字最低嘅 3:1 都未夠。");
      contrast.textContent = t(en, yue);
    }

    function write(value, skip) {
      var channels = hexToRgb(value);
      var wheel = rgbToHsl(channels);
      var assign = function (node, next) {
        if (node !== skip && node.value !== next) node.value = next;
      };
      assign(colour, value);
      assign(hex, value);
      assign(rgb, "rgb(" + channels.join(", ") + ")");
      assign(hsl, "hsl(" + wheel[0] + ", " + wheel[1] + "%, " + wheel[2] + "%)");
      assign(hue, String(wheel[0]));
      hue.setAttribute("aria-valuetext", t(hue.value + " degrees", hue.value + " 度"));
      updateContrast(value);
    }

    function commit(value, source) {
      origin = source;
      settings.set(def.key, value);
      origin = null;
      write(value, source); // settings.set is a no-op when unchanged; the fields still need syncing
    }

    function current() {
      return normaliseHex(settings.get(def.key)) || DEFAULT_ACCENT;
    }

    colour.addEventListener("input", function () {
      var value = normaliseHex(colour.value);
      if (!value) return;
      setNote("", false);
      commit(value, colour);
    });

    hue.addEventListener("input", function () {
      var wheel = rgbToHsl(hexToRgb(current()));
      wheel[0] = Number(hue.value);
      var value = rgbToHex(hslToRgb(wheel));
      if (wheel[1] === 0) {
        setNote(
          t(
            "Saturation is 0%, so hue has no visible effect until you raise it.",
            "飽和度係 0%，未加返之前轉色相都唔會見到分別。"
          ),
          false
        );
      } else {
        setNote("", false);
      }
      commit(value, hue);
    });

    hex.addEventListener("input", function () {
      var value = normaliseHex(hex.value);
      if (value) {
        setNote("", false);
        commit(value, hex);
      } else {
        setNote(
          t(
            "Not a hex colour yet: use #rgb or #rrggbb. Nothing was changed.",
            "而家仲未係有效嘅 hex 色：要用 #rgb 或者 #rrggbb。冇改到任何嘢。"
          ),
          true
        );
      }
    });

    rgb.addEventListener("input", function () {
      var parsed = parseTriple(rgb.value, "rgb");
      if (parsed) {
        setNote("", false);
        commit(rgbToHex(parsed), rgb);
      } else {
        setNote(
          t(
            "Not an RGB colour yet: use rgb(77, 95, 146) with each channel 0-255. Nothing was changed.",
            "而家仲未係有效嘅 RGB 色：要用 rgb(77, 95, 146)，每個通道 0-255。冇改到任何嘢。"
          ),
          true
        );
      }
    });

    hsl.addEventListener("input", function () {
      var parsed = parseTriple(hsl.value, "hsl");
      if (parsed) {
        setNote("", false);
        commit(rgbToHex(hslToRgb(parsed)), hsl);
      } else {
        setNote(
          t(
            "Not an HSL colour yet: use hsl(226, 31%, 44%) with both percentages 0-100%. Nothing was changed.",
            "而家仲未係有效嘅 HSL 色：要用 hsl(226, 31%, 44%)，兩個百分比都係 0-100%。冇改到任何嘢。"
          ),
          true
        );
      }
    });

    var children = rows.map(function (row) {
      return row.node;
    });
    children.push(note, contrast);

    return {
      node: el(
        "div",
        { class: "setting-control", role: "group", "aria-labelledby": id + "-label" },
        children
      ),
      focus: colour,
      copy: function () {
        rows.forEach(function (row) {
          row.label.textContent = pick(row.text);
        });
        updateContrast(current());
      },
      sync: function () {
        write(current(), origin);
      },
      value: function () {
        var value = current();
        var channels = hexToRgb(value);
        var wheel = rgbToHsl(channels);
        return (
          value +
          " rgb(" + channels.join(", ") + ")" +
          " hsl(" + wheel[0] + ", " + wheel[1] + "%, " + wheel[2] + "%)"
        );
      },
    };
  }

  // ------------------------------------------------------- the settings set
  var DEFS = [
    {
      key: "language",
      type: "select",
      label: ["Language mode", "語言模式"],
      options: [
        ["english", "English"],
        ["cantonese", "香港粵語"],
        ["bilingual", "Bilingual · 雙語"],
      ],
      help: {
        en: [
          "Chooses which language this site writes its own copy in. Every fact, identifier, digest, dimension and link stays identical in all three modes.",
          "Picks the language the site talks to you in. The jokes get translated; the SHA-256 digests absolutely do not.",
        ],
        yue: [
          "揀呢個網站用邊種語言寫自己嘅文字。三種模式入面，所有事實、識別碼、雜湊值、尺寸同連結都完全一樣。",
          "揀網站用邊種語言同你傾偈。笑話會跟住轉，SHA-256 就死都唔會轉。",
        ],
      },
    },
    {
      key: "funnyEn",
      type: "range",
      min: 1,
      max: 5,
      label: ["Funny level · English", "搞笑程度 · 英文"],
      help: {
        en: [
          "Sets how playful the English copy is, from 1 (fully serious) to 5. It moves the voice only: a warning still names exactly what it is about to do.",
          "How much the English half is allowed to lark about, 1 to 5. Voice only — even at 5 a warning still tells you precisely what it will break.",
        ],
        yue: [
          "設定英文文字有幾玩得，1（完全認真）到 5。只係改語氣：警告一樣會照直講會發生咩事。",
          "英文嗰邊可以玩幾大，1 到 5。淨係改語氣啫，去到 5 級警告都一樣講得清清楚楚。",
        ],
      },
    },
    {
      key: "funnyYue",
      type: "range",
      min: 1,
      max: 5,
      label: ["Funny level · Cantonese", "搞笑程度 · 粵語"],
      help: {
        en: [
          "Sets how playful the Cantonese copy is, from 1 (fully serious) to 5, independently of the English slider. Facts are untouched at every level.",
          "How cheeky the Cantonese half gets, 1 to 5, on its own dial. The facts underneath never move an inch.",
        ],
        yue: [
          "設定粵語文字有幾玩得，1（完全認真）到 5，同英文嗰條掣分開計。任何級數都唔會改事實。",
          "粵語嗰邊可以幾串，1 到 5，自己一條掣。下面啲事實一個字都唔會郁。",
        ],
      },
    },
    {
      key: "theme",
      type: "select",
      label: ["Theme", "主題"],
      options: [
        ["light", ["Light", "淺色"]],
        ["dark", ["Dark", "深色"]],
        ["system", ["Match system", "跟系統"]],
      ],
      help: {
        en: [
          "Light, dark, or match system. Match system reads this browser's colour-scheme preference and keeps following it for as long as it stays selected, switching the moment the system does.",
          "Bright, cosy, or whatever the operating system feels like today. The last one keeps watching and flips with it rather than reading the preference once and forgetting.",
        ],
        yue: [
          "淺色、深色，或者跟系統。揀咗跟系統之後，佢會一直跟住瀏覽器嘅色彩偏好，系統一轉佢就即刻轉。",
          "光、暗，或者「跟住個系統做」。揀最後嗰個佢會一路盯住，唔係睇一次就當睇完。",
        ],
      },
    },
    {
      key: "density",
      type: "select",
      label: ["Density", "密度"],
      options: [
        ["compact", ["Compact", "緊湊"]],
        ["comfortable", ["Comfortable", "適中"]],
        ["spacious", ["Spacious", "寬鬆"]],
      ],
      help: {
        en: [
          "Sets the padding and gaps every card and section uses. Compact fits more on one screen; spacious gives each card more room to breathe.",
          "How much elbow room the cards get. Compact packs them in, spacious lets them sprawl, comfortable is the shipped middle nobody argues about.",
        ],
        yue: [
          "設定每張卡同每段之間嘅留白同間距。緊湊一個畫面睇得多啲；寬鬆就俾每張卡多啲空間。",
          "啲卡有幾多位伸個懶腰。緊湊就迫實佢，寬鬆就任佢攤，適中就係出廠嗰個冇人拗嘅中間值。",
        ],
      },
    },
    {
      key: "accent",
      type: "accent",
      label: ["Accent colour", "主色"],
      help: {
        en: [
          "Sets the accent behind buttons, links, headings and focus rings. The picker is continuous rather than a fixed swatch list, HEX, RGB and HSL all round-trip, and the readout reports the measured contrast against the current page surface.",
          "The one colour the whole page leans on. Pick it anywhere in the spectrum, type it in whichever notation you think in, and the readout tells you the real contrast ratio rather than reassuring you.",
        ],
        yue: [
          "設定按鈕、連結、標題同焦點框嘅主色。個選色器係連續嘅，唔係一堆固定色塊；HEX、RGB、HSL 三種寫法可以互轉，下面會報同現時頁面底色量出嚟嘅對比度。",
          "成版嘢靠嘅就係呢隻色。喺整個色譜任揀，用你慣嘅寫法打入去，下面報嘅係真對比度，唔係安慰你嗰句。",
        ],
      },
    },
    {
      key: "font",
      type: "select",
      label: ["Interface font", "介面字體"],
      options: [
        ["system-ui", ["System UI", "系統介面字體"]],
        ["segoe", ["Segoe UI", "Segoe UI"]],
        ["georgia", ["Georgia (serif)", "Georgia（襯線）"]],
        ["mono", ["Cascadia Code (monospace)", "Cascadia Code（等寬）"]],
      ],
      help: {
        en: [
          "Chooses the font stack the whole page renders in. Every stack ends in a CJK-capable fallback, so Cantonese copy stays legible when the leading family carries no Chinese glyphs.",
          "Which typeface the page wears. Each choice keeps a CJK family on the end of the queue, because a font with no Chinese glyphs turns half this page into empty boxes.",
        ],
        yue: [
          "揀成版嘢用邊個字體組合。每個組合最後都有支援中日韓嘅後備字體，所以就算頭嗰隻字體冇中文字，粵語文字一樣睇得清楚。",
          "成版着邊套字。每個選擇最尾都留咗隻中文字體，因為冇中文字模嘅字體會令半版嘢變晒豆腐格。",
        ],
      },
    },
    {
      key: "scale",
      type: "range",
      min: 80,
      max: 200,
      step: 5,
      label: ["Interface scale", "介面縮放"],
      help: {
        en: [
          "Scales the whole interface between 80% and 200% by changing the root font size, so the layout reflows instead of clipping. It is independent of the browser's own zoom.",
          "Makes everything bigger or smaller, 80% to 200%. It moves the root font size, so the layout reflows properly rather than sliding off the edge.",
        ],
        yue: [
          "改根字體大細，令成個介面喺 80% 到 200% 之間縮放，版面會重新排而唔係俾切走。同瀏覽器本身嘅縮放係兩回事。",
          "將所有嘢放大縮細，80% 到 200%。佢郁嘅係根字體大細，所以版面會乖乖重排，唔會標出畫面外。",
        ],
      },
    },
    {
      key: "emoji",
      type: "checkbox",
      label: ["Emoji in messages", "訊息用 emoji"],
      action: ["Show decorative emoji", "顯示裝飾用 emoji"],
      help: {
        en: [
          "Decorative emoji appear in notifications and status copy only. Turning this off removes every one of them; no button, control label or accessible name has ever carried one.",
          "The little pictures in notifications. Switch it off and they all leave quietly. They were never allowed in buttons or accessible names in the first place.",
        ],
        yue: [
          "裝飾用 emoji 只會出現喺通知同狀態文字。閂咗就全部唔見；按鈕、控制項標籤同無障礙名稱從來都冇放過。",
          "通知入面嗰啲小圖案。閂咗佢哋就靜靜雞走。反正按鈕同無障礙名稱一開始就唔准佢哋入去。",
        ],
      },
    },
    {
      key: "narrator",
      type: "checkbox",
      label: ["Spoken narrator", "語音旁白"],
      action: ["Speak notifications aloud", "讀出通知"],
      help: {
        en: [
          "Off unless you switch it on. When on, each notification is spoken by this browser's own speech engine, one utterance at a time, in zh-HK while Cantonese is selected and en-US otherwise. No audio and no text leaves this page.",
          "Off until you say otherwise. Turn it on and the browser reads your notifications out, one at a time, in zh-HK for Cantonese and en-US for everything else. Nothing leaves the page — it is your own machine talking to you.",
        ],
        yue: [
          "預設係閂。開咗之後，每個通知都會由瀏覽器自己嘅語音引擎讀出，一次讀一句；揀咗粵語就用 zh-HK，其他情況用 en-US。冇任何聲音或文字離開呢一頁。",
          "預設閂住，你叫佢先開。開咗瀏覽器就會逐句讀你嘅通知，粵語用 zh-HK，其餘用 en-US。冇嘢會離開呢一頁，係你部機自己同你講嘢。",
        ],
      },
    },
    {
      key: "reducedMotion",
      type: "checkbox",
      label: ["Reduced motion", "減少動態"],
      action: ["Force reduced motion on", "強制開啟減少動態"],
      help: {
        en: [
          "Forces the reduced-motion path on even when the operating system does not ask for it: transitions and animations are cut to nothing and scrolling jumps instead of gliding. Off returns to whatever the system asks for.",
          "Nails motion shut regardless of what the operating system thinks. Transitions stop, animations stop, scrolling jumps straight there. Switch it off and the system gets its opinion back.",
        ],
        yue: [
          "就算作業系統冇要求，都強制行減少動態：過場同動畫全部收埋，捲動係跳過去而唔係滑過去。閂返就跟返系統嘅設定。",
          "唔理作業系統點諗，直接將動態封死。過場停、動畫停、捲動一下跳到位。閂返就還返個決定權俾系統。",
        ],
      },
    },
    {
      key: "brand",
      type: "text",
      label: ["Displayed name", "顯示名稱"],
      help: {
        en: [
          "Renames what this site calls itself in the header, the footer and the browser tab. It changes the displayed name only: the real product name is Material Minecraft World Editor, and that is the name a bug report, a release note or a URL has to carry. Clear the field to go back to it.",
          "Call the site whatever you like — header, footer and tab will play along. It is a display name and nothing more: a bug report or a URL still has to say Material Minecraft World Editor, or nobody will know what software you mean. Empty the box to get it back.",
        ],
        yue: [
          "改呢個網站喺頁首、頁尾同瀏覽器分頁顯示嘅名。淨係改顯示名：真正嘅產品名係 Material Minecraft World Editor，報 bug、發佈說明同網址都一定要用返個真名。清空個欄就還原。",
          "想叫佢做咩就叫咩，頁首、頁尾、分頁都會配合你。不過純粹係個顯示名：報 bug 或者寫網址一樣要用 Material Minecraft World Editor，唔係冇人知你講緊邊套軟件。清空個欄就還原。",
        ],
      },
    },
  ];

  var RENDERERS = {
    language: function (value) {
      return optionEnglish("language", value);
    },
    funnyEn: function (value) {
      return "level " + value;
    },
    funnyYue: function (value) {
      return "level " + value;
    },
    theme: function (value) {
      return optionEnglish("theme", value);
    },
    density: function (value) {
      return optionEnglish("density", value);
    },
    accent: function (value) {
      return String(value);
    },
    font: function (value) {
      return optionEnglish("font", value);
    },
    scale: function (value) {
      return value + "%";
    },
    emoji: function (value) {
      return value === true ? "on" : "off";
    },
    narrator: function (value) {
      return value === true ? "on" : "off";
    },
    reducedMotion: function (value) {
      return value === true ? "on" : "off";
    },
    brand: function (value) {
      return "“" + value + "”";
    },
  };

  function optionEnglish(key, value) {
    var def = DEFS.filter(function (candidate) {
      return candidate.key === key;
    })[0];
    if (!def || !def.options) return String(value);
    var match = def.options.filter(function (option) {
      return option[0] === String(value);
    })[0];
    return match ? english(match[1]) : String(value);
  }

  DEFS.forEach(function (def) {
    if (def.type !== "range") return;
    def.readout = def.key === "scale"
      ? function (value) { return value + "%"; }
      : function (value) { return value + " / 5"; };
    def.valueText = def.key === "scale"
      ? function (value) { return t(value + " percent", value + " 百分比"); }
      : function (value) { return t("level " + value + " of 5", "5 級之中嘅第 " + value + " 級"); };
  });

  // ------------------------------------------------------------------ cards
  var records = [];
  var resetRecord = null;

  function buildCard(def) {
    var id = "setting-" + def.key;
    var labelNode = el("span", { id: id + "-label" });
    var helpNode = el("small", { class: "setting-help", id: id + "-help" });
    var provenanceNode = el("small", { class: "setting-provenance" });

    if (def.key === "narrator" && !SPEECH_AVAILABLE) {
      def.unavailable = true;
      def.helpSuffix = function () {
        return t(
          "This browser exposes no speechSynthesis engine, so nothing can be spoken here and the control is disabled rather than left to look usable.",
          "呢個瀏覽器冇提供 speechSynthesis 語音引擎，所以呢度冇嘢讀得出；個控制項已經停用，唔會扮到好似用得咁。"
        );
      };
    }

    var built =
      def.type === "select" ? buildSelect(def, id)
      : def.type === "range" ? buildRange(def, id)
      : def.type === "checkbox" ? buildCheckbox(def, id)
      : def.type === "accent" ? buildAccent(def, id)
      : buildText(def, id);

    var card = el(
      "div",
      { class: "setting-card", id: id + "-card", "data-setting": def.key },
      labelNode,
      built.node,
      helpNode,
      provenanceNode
    );

    var record = {
      key: def.key,
      def: def,
      node: card,
      built: built,
      label: function () {
        return pick(def.label);
      },
      help: function () {
        return helpText(def);
      },
      value: function () {
        return built.value();
      },
      refresh: function () {
        labelNode.textContent = pick(def.label);
        helpNode.textContent = helpText(def);
        provenanceNode.textContent = settings.provenance(def.key, RENDERERS[def.key]);
        if (built.copy) built.copy();
        if (built.sync) built.sync();
      },
      search: function () {
        return [
          def.key,
          english(def.label),
          typeof def.label === "string" ? "" : def.label[1],
          helpNode.textContent,
          built.value(),
        ].join(" ");
      },
      focus: function () {
        if (built.focus) built.focus.focus();
      },
    };

    settings.register({
      key: def.key,
      type: def.type,
      tab: "settings",
      cardId: card.id,
      controlId: built.focus ? built.focus.id : null,
      label: english(def.label),
      help: def.help.en[0],
      labelNow: record.label,
      helpNow: record.help,
      value: record.value,
      isDefault: function () {
        return settings.isDefault(def.key);
      },
      provenance: function () {
        return settings.provenance(def.key, RENDERERS[def.key]);
      },
      focus: record.focus,
      node: card,
    });

    return record;
  }

  // --------------------------------------------------------- the reset card
  function storedKeys() {
    return KEYS.filter(function (key) {
      return !settings.isDefault(key);
    });
  }

  function buildResetCard() {
    var labelNode = el("span", { id: "setting-reset-label" });
    var helpNode = el("small", { class: "setting-help", id: "setting-reset-help" });
    var provenanceNode = el("small", { class: "setting-provenance" });
    var status = el("small", { class: "setting-note", id: "setting-reset-status", role: "status" });
    var armed = false;

    var confirm = el("button", {
      type: "button",
      class: "button button-tonal setting-danger",
      id: "setting-reset",
      "aria-describedby": "setting-reset-help setting-reset-status",
    });
    var cancel = el("button", {
      type: "button",
      class: "button button-text",
      id: "setting-reset-cancel",
    });

    function disarm() {
      if (!armed) return;
      armed = false;
      render();
    }

    function render() {
      var keys = storedKeys();
      var list = keys.join(", ");
      confirm.disabled = keys.length === 0;
      confirm.setAttribute("data-armed", String(armed));
      cancel.hidden = !armed;
      confirm.textContent = armed
        ? t(
            "Confirm — discard " + keys.length + " stored preferences: " + list,
            "確認 — 刪除 " + keys.length + " 項已儲存偏好：" + list
          )
        : t("Reset site settings", "重設網站設定");
      cancel.textContent = t("Cancel", "取消");
      status.textContent = armed
        ? t(
            "Armed. The next press discards " + list + " and returns every setting to its shipped default. Press Cancel or Escape to stop.",
            "已解鎖。再撳一次就會刪除 " + list + "，令所有設定返回出廠預設值。撳「取消」或者 Escape 就可以停手。"
          )
        : "";
      labelNode.textContent = t("Reset site settings", "重設網站設定");
      helpNode.textContent = t(
        "Discards every preference stored in this browser and returns each setting to its shipped default. Nothing outside this browser is touched. The button arms first, states exactly what will be lost, and needs a second deliberate press.",
        "刪除呢個瀏覽器儲存嘅所有偏好，令每項設定返回出廠預設值。瀏覽器以外嘅嘢一律唔會郁。個掣要先解鎖，講清楚會失去咩，再撳多一次先會執行。"
      );
      provenanceNode.textContent =
        keys.length === 0
          ? t(
              "Nothing is stored in this browser yet, so all " + KEYS.length + " settings are on their shipped defaults and there is nothing to discard.",
              "呢個瀏覽器暫時未儲存過任何嘢，所以全部 " + KEYS.length + " 項設定都係出廠預設值，冇嘢可以刪。"
            )
          : t(
              "Stored in this browser: " + list + " (" + keys.length + " of " + KEYS.length + "). The remaining " + (KEYS.length - keys.length) + " are on their shipped defaults.",
              "呢個瀏覽器儲存咗：" + list + "（" + KEYS.length + " 項之中嘅 " + keys.length + " 項）。其餘 " + (KEYS.length - keys.length) + " 項仍然係出廠預設值。"
            );
    }

    confirm.addEventListener("click", function () {
      if (confirm.disabled) return;
      if (!armed) {
        armed = true;
        render();
        return;
      }
      var count = storedKeys().length;
      armed = false;
      settings.reset();
      render();
      confirm.focus();
      Site.notify(
        lang.emoji("🔄") + t("Site settings reset", "網站設定已重設"),
        t(
          count + " stored preferences were discarded. All " + KEYS.length + " settings are back on their shipped defaults in this browser.",
          "已刪除 " + count + " 項已儲存偏好。呢個瀏覽器入面全部 " + KEYS.length + " 項設定已經返回出廠預設值。"
        )
      );
    });

    cancel.addEventListener("click", disarm);

    var card = el(
      "div",
      { class: "setting-card", id: "setting-reset-card", "data-setting": "reset" },
      labelNode,
      el("div", { class: "setting-control" }, el("div", { class: "setting-actions" }, confirm, cancel), status),
      helpNode,
      provenanceNode
    );

    card.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && armed) {
        event.stopPropagation();
        disarm();
        confirm.focus();
      }
    });
    // Leaving the card is as clear a "no" as pressing Cancel.
    card.addEventListener("focusout", function (event) {
      if (armed && !card.contains(event.relatedTarget)) disarm();
    });

    return {
      key: "reset",
      node: card,
      refresh: render,
      label: function () {
        return t("Reset site settings", "重設網站設定");
      },
      help: function () {
        return helpNode.textContent;
      },
      value: function () {
        return storedKeys().join(" ");
      },
      // Deliberately not the stored key names: searching for one setting should
      // land on that setting, not drag the reset card along because it happens
      // to list the key.
      search: function () {
        return "reset default defaults restore " + labelNode.textContent + " " + helpNode.textContent;
      },
      focus: function () {
        confirm.focus();
      },
      disarm: disarm,
    };
  }

  // ----------------------------------------------------------------- search
  function init() {
    var grid = document.getElementById("settings-grid");
    if (!grid) return;

    installStyle();

    var searchInput = document.getElementById("settings-search");
    var openButton = document.getElementById("settings-regex-open");
    var panel = document.getElementById("settings-regex");
    var countNode = document.getElementById("settings-count");
    var emptyNode = document.getElementById("settings-empty");

    records = DEFS.map(buildCard);
    resetRecord = buildResetCard();
    var all = records.concat([resetRecord]);

    grid.replaceChildren.apply(
      grid,
      all.map(function (record) {
        return record.node;
      })
    );

    applyAll();
    all.forEach(function (record) {
      record.refresh();
    });

    // Every card is refreshed on every change: copy, control value and
    // provenance can each depend on a different key, and a stale provenance
    // line is worse than no line at all.
    settings.onChange(function (key) {
      if (key === null) applyAll();
      else if (key === "theme") applyTheme();
      else if (key === "language") applyLanguage();
      else if (key === "density") applyDensity();
      else if (key === "accent") applyAccent();
      else if (key === "font") applyFont();
      else if (key === "scale") applyScale();
      else if (key === "reducedMotion") applyMotion();
      else if (key === "brand") applyBrand();
      else if (key === "narrator") applyNarrator();
      all.forEach(function (record) {
        record.refresh();
      });
    });

    if (colourMedia) {
      var followSystem = function () {
        applyTheme();
        all.forEach(function (record) {
          record.refresh(); // the surface moved, so the contrast readout has too
        });
      };
      if (colourMedia.addEventListener) colourMedia.addEventListener("change", followSystem);
      else if (colourMedia.addListener) colourMedia.addListener(followSystem);
    }

    var handle = null;

    function hit(text, query) {
      if (!query) return true;
      if (handle) return handle.matches(text);
      try {
        return Site.matcher(query, false, "i").test(text);
      } catch (error) {
        return false;
      }
    }

    function filter(state) {
      var query = state && state.query ? String(state.query) : "";
      var count = 0;
      all.forEach(function (record) {
        var match = hit(record.search(), query);
        record.node.hidden = !match;
        if (match) count++;
      });
      if (countNode) countNode.textContent = Site.describe(count, "setting", query);
      if (emptyNode) emptyNode.hidden = count !== 0;
    }

    if (Site.regex && typeof Site.regex.attach === "function" && searchInput && openButton && panel) {
      handle = Site.regex.attach({
        name: "settings",
        input: searchInput,
        openButton: openButton,
        panel: panel,
        sample: "theme dark · accent #4d5f92 · scale 150%",
        onChange: filter,
      });
      // attach() degrades to a plain-text handle when the builder markup is
      // missing, and that fallback wires no listener of its own. Filtering from
      // the field here as well costs one redundant pass and is the difference
      // between a search box and a search box that does nothing.
      searchInput.addEventListener("input", function () {
        filter(handle.state ? handle.state() : { query: searchInput.value });
      });
      filter(handle.state ? handle.state() : { query: searchInput.value });
    } else {
      // No builder on the page: the search still has to work, and the button
      // that would open the builder still has to do something real.
      if (searchInput) {
        searchInput.addEventListener("input", function () {
          filter({ query: searchInput.value });
        });
      }
      if (panel && openButton) {
        openButton.addEventListener("click", function () {
          panel.open = !panel.open;
        });
        panel.addEventListener("toggle", function () {
          openButton.setAttribute("aria-expanded", String(panel.open));
        });
        var controls = panel.querySelector('[data-regex-controls="settings"]');
        if (controls && !controls.firstChild) {
          controls.appendChild(
            el(
              "p",
              { class: "setting-note" },
              t(
                "The regex builder script is not loaded on this page, so this search is plain text only.",
                "呢一頁冇載入 regex builder，所以呢個搜尋只支援純文字。"
              )
            )
          );
        }
      }
      filter({ query: searchInput ? searchInput.value : "" });
    }

    function jump(record) {
      Site.showTab("settings");
      // A card hidden by an active query cannot be jumped to, so the query goes
      // before the destination does. Assigning .value fires nothing, and the
      // builder's pattern field is the other half of this one query -- so the
      // clear is announced the way a keystroke would announce it, or the box
      // reads empty while the grid stays filtered by a query nobody can see.
      if (searchInput && searchInput.value) {
        searchInput.value = "";
        if (typeof window.Event === "function") {
          searchInput.dispatchEvent(new window.Event("input", { bubbles: true }));
        }
        filter(handle && handle.state ? handle.state() : { query: "" });
      }
      record.node.hidden = false;
      try {
        record.node.scrollIntoView({
          block: "center",
          behavior: reducedMotion() ? "auto" : "smooth",
        });
      } catch (error) {
        record.node.scrollIntoView(false);
      }
      record.focus();
      record.node.style.outline = "3px solid var(--primary)";
      record.node.style.outlineOffset = "3px";
      window.setTimeout(function () {
        record.node.style.outline = "";
        record.node.style.outlineOffset = "";
      }, 1600);
    }

    Site.registerPaletteSource(function () {
      return all.map(function (record) {
        var run = function () {
          jump(record);
        };
        var detail =
          record.key === "reset"
            ? record.help()
            : record.help() + " " + t("Currently: ", "而家係：") + record.value();
        return {
          id: "setting:" + record.key,
          kind: "setting",
          group: t("Settings", "設定"),
          tab: "settings",
          title: record.label(),
          label: record.label(),
          detail: detail,
          subtitle: detail,
          value: record.value(),
          keywords: record.search(),
          run: run,
          action: run,
        };
      });
    });

    // Installed at ready() so it wraps whatever notifications.js put in place
    // rather than being overwritten by it.
    if (typeof Site.notify === "function") {
      var deliver = Site.notify;
      Site.notify = function (title, body) {
        speak([title, body].filter(Boolean).join(". "));
        return deliver.apply(Site, arguments);
      };
    }

    // Turning the narrator on should prove it works, not promise that it does.
    settings.onChange(function (key) {
      if (key !== "narrator" || settings.get("narrator") !== true) return;
      Site.notify(
        lang.emoji("🔊") + t("Narrator on", "語音旁白已開啟"),
        t(
          "Notifications are now spoken by this browser, one at a time.",
          "由而家開始，通知會由呢個瀏覽器逐句讀出。"
        )
      );
    });
  }

  Site.ready(init);
})();
