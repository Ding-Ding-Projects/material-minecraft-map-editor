/* Shared runtime for the Material Minecraft World Editor site.
 *
 * Every other script on the page is a classic script that attaches to this one
 * object. There are no ES modules deliberately: the bundle has to render from a
 * file:// preview as readily as from a public host, and a module graph does not.
 *
 * The rules the rest of the site inherits from here:
 *   - plain-text search is the default everywhere; regex is an explicit opt-in
 *   - a pattern is bounded before it reaches the engine, and an invalid one is
 *     reported rather than silently matching everything
 *   - a setting is not a setting until it carries an explanation and an honest
 *     statement of where its current value came from
 */
(function () {
  "use strict";

  var DATA = window.AMULET_SITE_DATA || {
    categories: [],
    features: [],
    commands: [],
    docs: [],
    shots: [],
  };

  var STORE_PREFIX = "mmwe.site.";

  // The design's own shipped defaults. Every provenance line is written against
  // these, so a value that equals its default must never claim to be user-set.
  var DEFAULTS = {
    language: "english",
    funnyEn: 1,
    funnyYue: 1,
    theme: "light",
    density: "comfortable",
    accent: "#4d5f92",
    font: "system-ui",
    scale: 100,
    emoji: true,
    narrator: false,
    reducedMotion: false,
    brand: "Material Minecraft World Editor",
  };

  var SETTINGS_KEY = STORE_PREFIX + "settings";

  // ---------------------------------------------------------------- storage
  var store = {
    get: function (name, fallback) {
      try {
        var raw = localStorage.getItem(STORE_PREFIX + name);
        return raw === null ? fallback : JSON.parse(raw);
      } catch (error) {
        return fallback;
      }
    },
    set: function (name, value) {
      try {
        localStorage.setItem(STORE_PREFIX + name, JSON.stringify(value));
        return true;
      } catch (error) {
        return false;
      }
    },
  };

  // --------------------------------------------------------------- settings
  var current = Object.assign({}, DEFAULTS);
  var stored = {};
  try {
    stored = JSON.parse(localStorage.getItem(SETTINGS_KEY) || "{}") || {};
  } catch (error) {
    stored = {};
  }
  Object.keys(DEFAULTS).forEach(function (key) {
    if (Object.prototype.hasOwnProperty.call(stored, key)) current[key] = stored[key];
  });

  var settingListeners = [];
  var settingDefs = [];

  function persist() {
    try {
      localStorage.setItem(SETTINGS_KEY, JSON.stringify(current));
    } catch (error) {
      /* A browser refusing storage is not a reason to stop rendering. */
    }
  }

  /* A temporary override sits on top of the stored value without replacing it.
   * A scheduled rule that wrote through settings.set would quietly become the
   * user's permanent choice the moment it fired, and the value they actually
   * chose would be gone with no way back. Overrides are memory-only, so they
   * also cannot survive a reload as a mystery setting nobody set. */
  var overrides = {};

  function effective(key) {
    return Object.prototype.hasOwnProperty.call(overrides, key)
      ? overrides[key]
      : current[key];
  }

  var settings = {
    all: function () {
      var out = Object.assign({}, current);
      Object.keys(overrides).forEach(function (key) {
        out[key] = overrides[key];
      });
      return out;
    },
    get: function (key) {
      return effective(key);
    },
    /** The value the user actually chose, ignoring any active override. */
    base: function (key) {
      return current[key];
    },
    isOverridden: function (key) {
      return Object.prototype.hasOwnProperty.call(overrides, key);
    },
    activeOverrides: function () {
      return Object.assign({}, overrides);
    },
    /** Apply a temporary value. Never persisted, never merged into `stored`. */
    override: function (key, value) {
      if (overrides[key] === value) return;
      overrides[key] = value;
      settingListeners.forEach(function (fn) {
        try {
          fn(key, value, settings.all());
        } catch (error) {}
      });
    },
    /** Hand the base value back. Omit `key` to release everything. */
    release: function (key) {
      var keys = key == null ? Object.keys(overrides) : [key];
      var changed = keys.filter(function (name) {
        return Object.prototype.hasOwnProperty.call(overrides, name);
      });
      changed.forEach(function (name) {
        delete overrides[name];
      });
      changed.forEach(function (name) {
        settingListeners.forEach(function (fn) {
          try {
            fn(name, current[name], settings.all());
          } catch (error) {}
        });
      });
      return changed;
    },
    isDefault: function (key) {
      return !Object.prototype.hasOwnProperty.call(stored, key);
    },
    /** Where the current value actually came from, in the user's words. */
    provenance: function (key, render) {
      var shipped = render ? render(DEFAULTS[key]) : String(DEFAULTS[key]);
      if (Object.prototype.hasOwnProperty.call(overrides, key)) {
        var base = render ? render(current[key]) : String(current[key]);
        return (
          "A schedule is overriding this right now. Your own value " +
          base +
          " comes back when the schedule stops applying."
        );
      }
      return settings.isDefault(key)
        ? "Not set here yet, so the shipped value " + shipped + " is in use."
        : "Stored in this browser; the shipped value is " + shipped + ".";
    },
    set: function (key, value) {
      if (current[key] === value) return;
      current[key] = value;
      stored[key] = value;
      persist();
      settingListeners.forEach(function (fn) {
        try {
          fn(key, value, settings.all());
        } catch (error) {
          /* one bad listener must not stop the others */
        }
      });
    },
    reset: function () {
      current = Object.assign({}, DEFAULTS);
      stored = {};
      persist();
      settingListeners.forEach(function (fn) {
        try {
          fn(null, null, settings.all());
        } catch (error) {}
      });
    },
    onChange: function (fn) {
      settingListeners.push(fn);
    },
    /** Modules declare their settings so the palette and guards can see them. */
    register: function (def) {
      settingDefs.push(def);
    },
    registry: function () {
      return settingDefs.slice();
    },
    DEFAULTS: DEFAULTS,
  };

  // --------------------------------------------------------------- language
  /* These read through `effective`, not `current`. A scheduled language rule
   * that changed the stored value but not the rendered copy would be the
   * classic "the setting is saved and nothing reads it" defect - a control
   * that demonstrably does nothing while every test of the store passes. */
  function mode() {
    var value = effective("language");
    return value === "cantonese" || value === "bilingual" ? value : "english";
  }

  var lang = {
    mode: mode,
    /** Bilingual keeps both, because dropping one is not a translation. */
    t: function (en, yue) {
      var m = mode();
      if (m === "cantonese") return yue || en;
      if (m === "bilingual") return yue ? en + " · " + yue : en;
      return en;
    },
    funny: function (which) {
      return (
        Number(which === "yue" ? effective("funnyYue") : effective("funnyEn")) || 1
      );
    },
    /** Emoji decorate; they never carry meaning, so they can always be off. */
    emoji: function (glyph) {
      return effective("emoji") && glyph ? glyph + " " : "";
    },
  };

  // ------------------------------------------------------------------ regex
  var MAX_PATTERN = 256;

  function escapeLiteral(value) {
    return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }

  /**
   * Build a matcher. Plain text is escaped so a stray metacharacter in an
   * ordinary query cannot change the meaning of the search, and a pattern is
   * refused before it reaches the engine rather than after it has run away.
   */
  function matcher(raw, useRegex, flags) {
    var value = String(raw || "");
    if (value.length > MAX_PATTERN) {
      throw new Error("Pattern is limited to " + MAX_PATTERN + " characters.");
    }
    var resolved = String(flags == null ? "i" : flags);
    if (!/^[dgimsuvy]*$/.test(resolved)) {
      throw new Error("Unsupported regular-expression flag.");
    }
    if (useRegex && /\([^()]*[+*][^()]*\)[+*{]/.test(value)) {
      throw new Error("Nested quantifiers are disabled to bound evaluation.");
    }
    return new RegExp(useRegex ? value || "(?:)" : escapeLiteral(value), resolved);
  }

  function describe(count, noun, query) {
    var plural = count === 1 ? noun : noun + "s";
    if (!query) return count + " " + plural;
    if (count === 0) return "No " + noun + " matches “" + query + "”.";
    return count + " " + plural + " match “" + query + "”.";
  }

  // -------------------------------------------------------------------- dom
  function el(tag, props) {
    var node = document.createElement(tag);
    if (props) {
      Object.keys(props).forEach(function (key) {
        var value = props[key];
        if (value == null || value === false) return;
        if (key === "class") node.className = value;
        else if (key === "text") node.textContent = value;
        else if (key === "html") node.innerHTML = value;
        else if (key.slice(0, 2) === "on" && typeof value === "function") {
          node.addEventListener(key.slice(2).toLowerCase(), value);
        } else if (value === true) node.setAttribute(key, "");
        else node.setAttribute(key, String(value));
      });
    }
    for (var i = 2; i < arguments.length; i++) {
      var child = arguments[i];
      if (child == null || child === false) continue;
      if (Array.isArray(child)) {
        child.forEach(function (one) {
          if (one != null && one !== false) {
            node.appendChild(one.nodeType ? one : document.createTextNode(String(one)));
          }
        });
      } else {
        node.appendChild(child.nodeType ? child : document.createTextNode(String(child)));
      }
    }
    return node;
  }

  // ------------------------------------------------------------------- tabs
  // tabs.js owns the strip; everything else only asks it to change page.
  var tabListeners = [];
  var api = {
    version: 1,
    data: DATA,
    store: store,
    settings: settings,
    lang: lang,
    matcher: matcher,
    escapeLiteral: escapeLiteral,
    describe: describe,
    el: el,
    MAX_PATTERN: MAX_PATTERN,

    /** Replaced by tabs.js once the strip exists. */
    showTab: function (id) {
      api._pendingTab = id;
    },
    onTabChange: function (fn) {
      tabListeners.push(fn);
    },
    emitTabChange: function (id) {
      tabListeners.forEach(function (fn) {
        try {
          fn(id);
        } catch (error) {}
      });
    },

    /** Replaced by notifications.js. Queued until then so nothing is lost. */
    _queued: [],
    notify: function (title, body) {
      api._queued.push({ title: title, body: body });
    },
    toast: function () {},

    /** Replaced by app.js once the menu element is wired. */
    contextMenu: function () {},

    /** Palette contributors register themselves; palette.js collects them. */
    _paletteSources: [],
    registerPaletteSource: function (fn) {
      api._paletteSources.push(fn);
    },
    paletteSources: function () {
      return api._paletteSources.slice();
    },

    ready: function (fn) {
      if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", fn);
      } else {
        fn();
      }
    },
  };

  window.AmuletSite = api;
})();
