/* Amulet Studio language and voice settings: the three language modes
 * (English, playful Hong Kong-style Cantonese, bilingual), the two
 * independent per-language funny-level sliders (1-5), the "Show emojis in
 * dialogs and message boxes" toggle, the shared School mode switch with its
 * rename and unlock credential, and the optional TTS narrator.
 *
 * Mounts into `#studio-language`, a sibling of `#studio-workspace` and
 * `#studio-surfaces` -- a separate panel, not a replacement for either.
 *
 * Language mode / both funny-level sliders / the emoji toggle are already
 * real, persisted preference fields (amulet_map_editor.api.preferences) and
 * already round-trip through docs/site/electron-bridge.js's
 * `Site.settings` <-> `preferences.write`/`preferences.read` sync (see the
 * FIELD_MAP in that file: `language`, `funnyEn`, `funnyYue`, `emoji`). This
 * panel is the first-class settings surface for those same fields --
 * reading and writing through `Site.settings`, exactly as every other
 * appearance control in this project does, rather than inventing a second
 * store. It also drives `amulet_map_editor.api.school_mode` and
 * `amulet_map_editor.api.tts_narrator` directly through the sidecar methods
 * this lane added (`school.*`, `narrator.*` in
 * amulet_map_editor/api/sidecar/methods.py), calling
 * `window.mmweDesktop.sidecar.call` directly the same way
 * docs/site/studio-surfaces.js does -- no load-order dependency on
 * electron-bridge.js.
 *
 * School mode is the strict one (school_mode.py's own docstring and rules):
 * while it is enabled, this panel forces English, sets both funny sliders to
 * 1, and hides the Cantonese/bilingual/funny-level/emoji controls entirely
 * rather than merely disabling them -- matching
 * `school_mode.presentation_preferences`. Turning it off requires the
 * locally verified shared credential, checked by the real sidecar method,
 * never by this file re-implementing the PBKDF2 comparison.
 *
 * Outside Electron (no `window.mmweDesktop.sidecar`) this shows the same
 * honest "desktop only" message every other Studio panel uses for the
 * sidecar-backed parts, but the language mode / funny levels / emoji toggle
 * still work through `Site.settings` alone -- those are real local
 * preferences with or without the desktop sidecar, exactly like theme and
 * density.
 */
(function () {
  "use strict";

  var NO_SIDECAR_REASON =
    "Desktop only: School mode and the spoken narrator both need the desktop app's sidecar.";

  function hasSidecar() {
    var b = window.mmweDesktop && window.mmweDesktop.sidecar;
    return !!(b && typeof b.call === "function");
  }

  // Calls straight into window.mmweDesktop.sidecar.call rather than through
  // docs/site/electron-bridge.js's higher-level Site.electronSidecar --
  // matching docs/site/studio-surfaces.js, this file has no ordering
  // dependency on electron-bridge.js having loaded first.
  function sidecarCall(method, params) {
    var b = window.mmweDesktop && window.mmweDesktop.sidecar;
    if (!b || typeof b.call !== "function") {
      return Promise.reject(new Error("sidecar unavailable"));
    }
    return b.call(method, params || {}).then(function (response) {
      if (!response || !response.ok) {
        throw new Error((response && response.error && response.error.message) || method + " failed");
      }
      return response.result;
    });
  }

  var school = {
    status: function () {
      return sidecarCall("school.status");
    },
    setModeName: function (modeName) {
      return sidecarCall("school.set_mode_name", { mode_name: modeName });
    },
    resetModeName: function () {
      return sidecarCall("school.reset_mode_name");
    },
    setCredential: function (credential) {
      return sidecarCall("school.set_credential", { credential: credential });
    },
    enable: function () {
      return sidecarCall("school.enable");
    },
    unlock: function (credential) {
      return sidecarCall("school.unlock", { credential: credential });
    },
  };

  var narrator = {
    read: function () {
      return sidecarCall("narrator.read");
    },
    write: function (changes) {
      return sidecarCall("narrator.write", changes || {});
    },
  };

  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    attrs = attrs || {};
    Object.keys(attrs).forEach(function (key) {
      var value = attrs[key];
      if (value === null || value === undefined || value === false) return;
      if (key === "className") node.className = value;
      else if (key === "text") node.textContent = value;
      else if (key.indexOf("on") === 0 && typeof value === "function") {
        node.addEventListener(key.slice(2).toLowerCase(), value);
      } else if (key === "checked" || key === "disabled" || key === "value") {
        node[key] = value;
      } else {
        node.setAttribute(key, value);
      }
    });
    (children || []).forEach(function (child) {
      if (child === null || child === undefined) return;
      node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
    });
    return node;
  }

  function settings() {
    return window.AmuletSite && window.AmuletSite.settings;
  }

  // ------------------------------------------------------- language panel

  var LANGUAGE_MODES = ["english", "cantonese", "bilingual"];

  function LanguagePanel(root) {
    var siteSettings = settings();
    var schoolOn = false; // refreshed by refreshSchoolState() below

    var status = el("p", { className: "lang-status", role: "status" });

    var modeSelect = el(
      "select",
      { "aria-label": "Language mode" },
      LANGUAGE_MODES.map(function (mode) {
        return el("option", { value: mode }, [mode]);
      })
    );

    var funnyEnLabel = el("label", {}, ["Funny level (English)"]);
    var funnyEnInput = el("input", {
      type: "range",
      min: "1",
      max: "5",
      "aria-label": "Funny level (English)",
    });
    var funnyYueLabel = el("label", {}, ["Funny level (Cantonese)"]);
    var funnyYueInput = el("input", {
      type: "range",
      min: "1",
      max: "5",
      "aria-label": "Funny level (Cantonese)",
    });
    var emojiInput = el("input", {
      type: "checkbox",
      "aria-label": "Show emojis in dialogs and message boxes",
    });

    var cantoneseRow = el("div", { className: "lang-row lang-cantonese-only" }, [
      funnyYueLabel,
      funnyYueInput,
    ]);
    var funnyEnRow = el("div", { className: "lang-row" }, [funnyEnLabel, funnyEnInput]);
    var emojiRow = el("div", { className: "lang-row" }, [
      el("label", {}, ["Show emojis in dialogs and message boxes"]),
      emojiInput,
    ]);

    function applyFromSettings() {
      if (!siteSettings) return;
      modeSelect.value = siteSettings.get("language") || "english";
      funnyEnInput.value = String(siteSettings.get("funnyEn") || 1);
      funnyYueInput.value = String(siteSettings.get("funnyYue") || 1);
      emojiInput.checked = siteSettings.get("emoji") !== false;
      renderSchoolGate();
    }

    function renderSchoolGate() {
      // School mode forces English and hides Cantonese/bilingual, both funny
      // sliders pinned at 1, and the emoji toggle -- never merely disabled.
      modeSelect.disabled = schoolOn;
      if (schoolOn) {
        modeSelect.value = "english";
      }
      Array.prototype.forEach.call(modeSelect.options, function (opt) {
        opt.hidden = schoolOn && opt.value !== "english";
      });
      cantoneseRow.hidden = schoolOn;
      funnyYueInput.disabled = schoolOn;
      funnyEnInput.disabled = schoolOn;
      emojiInput.disabled = schoolOn;
      if (schoolOn) {
        funnyEnInput.value = "1";
        funnyYueInput.value = "1";
      }
    }

    modeSelect.addEventListener("change", function () {
      if (schoolOn || !siteSettings) return;
      siteSettings.set("language", modeSelect.value);
    });
    funnyEnInput.addEventListener("input", function () {
      if (schoolOn || !siteSettings) return;
      siteSettings.set("funnyEn", Number(funnyEnInput.value));
    });
    funnyYueInput.addEventListener("input", function () {
      if (schoolOn || !siteSettings) return;
      siteSettings.set("funnyYue", Number(funnyYueInput.value));
    });
    emojiInput.addEventListener("change", function () {
      if (schoolOn || !siteSettings) return;
      siteSettings.set("emoji", emojiInput.checked);
    });

    root.appendChild(status);
    root.appendChild(el("div", { className: "lang-row" }, [
      el("label", {}, ["Language mode"]),
      modeSelect,
    ]));
    root.appendChild(funnyEnRow);
    root.appendChild(cantoneseRow);
    root.appendChild(emojiRow);

    if (siteSettings && typeof siteSettings.onChange === "function") {
      siteSettings.onChange(function (key) {
        if (key === "language" || key === "funnyEn" || key === "funnyYue" || key === "emoji") {
          applyFromSettings();
        }
      });
    }

    applyFromSettings();

    return {
      setSchoolOn: function (on) {
        schoolOn = !!on;
        renderSchoolGate();
      },
    };
  }

  // ---------------------------------------------------------- school panel

  function SchoolPanel(root, onStateChange) {
    if (!hasSidecar()) {
      root.appendChild(el("p", { className: "lang-empty" }, [NO_SIDECAR_REASON]));
      onStateChange(false);
      return;
    }

    var status = el("p", { className: "school-status", role: "status" });
    var nameInput = el("input", { type: "text", "aria-label": "School mode name" });
    var renameButton = el("button", { type: "button" }, ["Rename"]);
    var resetNameButton = el("button", { type: "button" }, ["Reset name"]);
    var credentialInput = el("input", {
      type: "password",
      "aria-label": "New unlock credential",
    });
    var setCredentialButton = el("button", { type: "button" }, ["Set unlock credential"]);
    var enableButton = el("button", { type: "button" }, ["Enable"]);
    var unlockInput = el("input", { type: "password", "aria-label": "Unlock credential" });
    var unlockButton = el("button", { type: "button" }, ["Turn off"]);

    var currentState = { enabled: false, mode_name: "School mode", has_unlock_credential: false };

    function render() {
      status.textContent =
        currentState.mode_name +
        ": " +
        (currentState.enabled ? "on" : "off") +
        (currentState.has_unlock_credential ? "" : " (no unlock credential set yet)");
      nameInput.value = currentState.mode_name;
      enableButton.disabled = currentState.enabled || !currentState.has_unlock_credential;
      unlockButton.disabled = !currentState.enabled;
      onStateChange(currentState.enabled);
    }

    function refresh() {
      return school.status().then(function (result) {
        currentState = result;
        render();
        return result;
      });
    }

    renameButton.addEventListener("click", function () {
      school.setModeName(nameInput.value).then(function (result) {
        currentState = result;
        render();
      });
    });
    resetNameButton.addEventListener("click", function () {
      school.resetModeName().then(function (result) {
        currentState = result;
        render();
      });
    });
    setCredentialButton.addEventListener("click", function () {
      school.setCredential(credentialInput.value).then(function (result) {
        credentialInput.value = "";
        currentState = result;
        render();
      });
    });
    enableButton.addEventListener("click", function () {
      school.enable().then(function (result) {
        currentState = result;
        render();
      });
    });
    unlockButton.addEventListener("click", function () {
      school.unlock(unlockInput.value).then(function (result) {
        unlockInput.value = "";
        currentState = result;
        render();
      });
    });

    root.appendChild(status);
    root.appendChild(el("div", { className: "school-row" }, [nameInput, renameButton, resetNameButton]));
    root.appendChild(el("div", { className: "school-row" }, [credentialInput, setCredentialButton]));
    root.appendChild(el("div", { className: "school-row" }, [enableButton]));
    root.appendChild(el("div", { className: "school-row" }, [unlockInput, unlockButton]));

    refresh();
  }

  // -------------------------------------------------------- narrator panel

  var NARRATOR_LANGUAGES = ["english", "cantonese", "both"];

  function NarratorPanel(root) {
    if (!hasSidecar()) {
      root.appendChild(el("p", { className: "lang-empty" }, [NO_SIDECAR_REASON]));
      return;
    }

    var status = el("p", { className: "narrator-status", role: "status" });
    var enabledInput = el("input", { type: "checkbox", "aria-label": "Enable spoken narrator" });
    var languageSelect = el(
      "select",
      { "aria-label": "Narrator language" },
      NARRATOR_LANGUAGES.map(function (lang) {
        return el("option", { value: lang }, [lang]);
      })
    );

    function render(settingsValue) {
      enabledInput.checked = !!settingsValue.enabled;
      languageSelect.value = settingsValue.language;
      status.textContent = "Narrator: " + (settingsValue.enabled ? "on" : "off (default)");
    }

    narrator.read().then(render);

    enabledInput.addEventListener("change", function () {
      narrator.write({ enabled: enabledInput.checked }).then(render);
    });
    languageSelect.addEventListener("change", function () {
      narrator.write({ language: languageSelect.value }).then(render);
    });

    root.appendChild(status);
    root.appendChild(el("div", { className: "narrator-row" }, [
      el("label", {}, ["Enable spoken narrator"]),
      enabledInput,
    ]));
    root.appendChild(el("div", { className: "narrator-row" }, [
      el("label", {}, ["Narrator language"]),
      languageSelect,
    ]));
  }

  // ------------------------------------------------------------- mount

  function mount() {
    var root = document.getElementById("studio-language");
    if (!root) return;
    root.innerHTML = "";

    var languageSection = el("section", { className: "lang-panel", "aria-label": "Language and voice" });
    var schoolSection = el("section", { className: "lang-panel", "aria-label": "School mode" });
    var narratorSection = el("section", { className: "lang-panel", "aria-label": "Narrator" });

    root.appendChild(languageSection);
    root.appendChild(schoolSection);
    root.appendChild(narratorSection);

    var language = LanguagePanel(languageSection);
    SchoolPanel(schoolSection, function (schoolOn) {
      language.setSchoolOn(schoolOn);
    });
    NarratorPanel(narratorSection);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mount);
  } else {
    mount();
  }

  // Exposed for tests and for a host page that wants to remount after the
  // sidecar becomes available.
  window.__AmuletStudioLanguage = { mount: mount };
})();
