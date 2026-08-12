/* Amulet Studio shell -- view switch, title bar wiring, and theme/density
 * application for docs/site/studio.html.
 *
 * This file owns exactly three things:
 *   1. Switching between the backstage view and the workspace view.
 *   2. Wiring the frameless title bar's window controls to
 *      window.mmweDesktop.window (exposed by electron/preload.js), and
 *      degrading honestly to a labelled desktop-only state in a plain
 *      browser where that bridge does not exist.
 *   3. Applying theme and density from the real persisted preferences
 *      (docs/site/site-core.js's `Site.settings`, which electron-bridge.js
 *      keeps synchronized with the Python sidecar) as CSS custom properties
 *      on the document root, so studio-tokens.css repaints in place.
 *
 * Ctrl+Shift+F opening the command palette is already handled globally by
 * palette.js's own document-level keydown listener (see docs/site/palette.js)
 * -- including this shell script after it is what wires that shortcut into
 * the studio page; there is nothing additional to bind here.
 */
(function () {
  "use strict";

  var root = document.documentElement;
  var studioRoot = document.getElementById("studio-root");

  // --------------------------------------------------------------- view switch
  var VIEWS = ["backstage", "workspace"];

  function showView(name) {
    if (VIEWS.indexOf(name) === -1) name = "backstage";
    VIEWS.forEach(function (view) {
      var el = document.getElementById(view + "-view");
      if (!el) return;
      if (view === name) {
        el.hidden = false;
      } else {
        el.hidden = true;
      }
    });
    if (studioRoot) studioRoot.setAttribute("data-active-view", name);
    window.dispatchEvent(new CustomEvent("studio:view-changed", { detail: { view: name } }));
  }

  // --------------------------------------------------------------- theme / density
  function applyAppearance() {
    var site = window.Site;
    var theme = site && site.settings ? site.settings.get("theme") : "light";
    var density = site && site.settings ? site.settings.get("density") : "comfortable";
    if (theme !== "light" && theme !== "dark" && theme !== "system") theme = "light";
    if (["compact", "comfortable", "spacious"].indexOf(density) === -1) density = "comfortable";

    if (theme === "system") {
      root.removeAttribute("data-theme");
    } else {
      root.setAttribute("data-theme", theme);
    }
    root.setAttribute("data-density", density);
    if (studioRoot) {
      if (theme === "system") studioRoot.removeAttribute("data-theme");
      else studioRoot.setAttribute("data-theme", theme);
      studioRoot.setAttribute("data-density", density);
    }
  }

  if (window.Site && window.Site.settings) {
    applyAppearance();
    window.Site.settings.onChange(function (key) {
      if (key === null || key === "theme" || key === "density") applyAppearance();
    });
  } else {
    // No Site global (a script failed to load, or this file loaded out of
    // order): fall back to the token defaults already baked into
    // studio-tokens.css rather than throwing.
    applyAppearance();
  }

  // --------------------------------------------------------------- title bar
  var desktop = window.mmweDesktop && window.mmweDesktop.window;
  var minimizeBtn = document.getElementById("studio-window-minimize");
  var maximizeBtn = document.getElementById("studio-window-maximize");
  var closeBtn = document.getElementById("studio-window-close");

  function setDesktopOnlyState() {
    // Honest degradation: in a plain browser (no Electron bridge) these
    // controls cannot do anything real, so they are disabled and say why,
    // rather than rendering as a dead, unexplained control.
    [minimizeBtn, maximizeBtn, closeBtn].forEach(function (btn) {
      if (!btn) return;
      btn.disabled = true;
      btn.setAttribute(
        "title",
        "Window controls are only available in the Amulet Studio desktop app"
      );
      btn.setAttribute("aria-disabled", "true");
    });
  }

  if (desktop) {
    if (minimizeBtn) {
      minimizeBtn.addEventListener("click", function () {
        desktop.minimize();
      });
    }
    if (maximizeBtn) {
      maximizeBtn.addEventListener("click", function () {
        desktop.maximizeOrRestore().then(function (state) {
          maximizeBtn.setAttribute(
            "aria-label",
            state && state.maximized ? "Restore window" : "Maximize window"
          );
        });
      });
    }
    if (closeBtn) {
      closeBtn.addEventListener("click", function () {
        desktop.close();
      });
    }
    if (typeof desktop.onStateChanged === "function") {
      desktop.onStateChanged(function (state) {
        if (!maximizeBtn) return;
        maximizeBtn.setAttribute(
          "aria-label",
          state && state.maximized ? "Restore window" : "Maximize window"
        );
      });
    }
  } else {
    setDesktopOnlyState();
  }

  // --------------------------------------------------------------- public surface
  window.AmuletStudio = {
    showView: showView,
    currentView: function () {
      return studioRoot ? studioRoot.getAttribute("data-active-view") : "backstage";
    },
    applyAppearance: applyAppearance,
  };

  showView("backstage");
})();
