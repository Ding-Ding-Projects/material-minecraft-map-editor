/* Panels that resize, floating panels that also drag, and filter rows that fold.
 *
 * Two exported capabilities, one file, because they answer the same question:
 * how much of the window is a surface allowed to occupy, and who decides.
 *
 *   AmuletSite.panel.enhance({element, storageKey, floating})
 *   AmuletSite.panel.collapsible({element, storageKey, startCollapsed})
 *
 * Three rules run through everything below:
 *
 *   - A panel is bounded by the viewport at all times. Size is clamped to the
 *     window and the offset is clamped so the panel stays fully inside it; a
 *     panel too large to fit keeps a grabbable strip on screen. A panel parked
 *     where the pointer cannot reach it is a panel the user has lost.
 *   - The stored geometry is what the user asked for, never what the current
 *     window happened to allow. Clamping is applied on the way to the screen,
 *     so a narrow window borrows space rather than confiscating it.
 *   - A collapsed filter row that is quietly excluding rows says so on its own
 *     summary. Hiding the control while its effect keeps running is how a user
 *     concludes their data has gone missing.
 */
(function () {
  "use strict";

  var site = window.AmuletSite;
  if (!site) return;

  var el = site.el;
  var lang = site.lang;
  var store = site.store;
  var settings = site.settings;

  var GEO_PREFIX = "panel.geometry.";
  var COLLAPSE_PREFIX = "panel.collapse.";

  var MIN_VISIBLE = 56; // px of a too-large panel that must stay reachable
  var STEP = 8;
  var BIG_STEP = 32;
  var ALL_EDGES = ["n", "e", "s", "w", "ne", "se", "sw", "nw"];
  var FLOW_EDGES = ["e", "s", "se"]; // an in-flow panel may only grow right and down
  var DOCS_BREAKPOINT = "(max-width: 900px)"; // mirrors the .docs-layout rule in styles.css
  var DOCS_GAP = 16;
  var DOCS_ARTICLE_MIN = 320;

  var instances = [];
  var collapsibles = [];
  var enhanced = new WeakMap();
  var folded = new WeakMap();

  function t(en, yue) {
    return lang.t(en, yue);
  }

  // ----------------------------------------------------------------- helpers
  function resolve(value) {
    if (!value) return null;
    if (value.nodeType === 1) return value;
    if (typeof value === "string") {
      try {
        return document.querySelector(value);
      } catch (error) {
        return null;
      }
    }
    return null;
  }

  function toLabel(value) {
    if (typeof value === "function") return value;
    if (Array.isArray(value)) {
      return function () {
        return t(value[0], value[1]);
      };
    }
    var text = String(value == null ? "" : value);
    return function () {
      return text;
    };
  }

  function clampNumber(value, low, high) {
    if (high < low) return high > 0 ? high : low;
    return value < low ? low : value > high ? high : value;
  }

  function viewportWidth() {
    return Math.max(320, document.documentElement.clientWidth || window.innerWidth || 0);
  }

  function viewportHeight() {
    return Math.max(240, document.documentElement.clientHeight || window.innerHeight || 0);
  }

  /**
   * Where an offset may sit so the box stays inside the viewport. `natural` is
   * the box edge with no offset applied, so the returned value is always
   * relative to the panel's own untouched position.
   */
  function clampOffset(natural, size, offset, viewport) {
    var low;
    var high;
    if (size <= viewport) {
      low = -natural;
      high = viewport - size - natural;
    } else {
      // Too big to fit: keep a strip of it on screen at both ends instead.
      low = MIN_VISIBLE - size - natural;
      high = viewport - MIN_VISIBLE - natural;
    }
    return offset < low ? low : offset > high ? high : offset;
  }

  function laidOut(node) {
    return !!(node.getClientRects && node.getClientRects().length);
  }

  function ensureId(node, fallback) {
    if (!node.id) node.id = fallback;
    return node.id;
  }

  function slug(value) {
    return String(value).replace(/[^a-z0-9]+/gi, "-").replace(/^-|-$/g, "").toLowerCase();
  }

  // -------------------------------------------------------------------- css
  var STYLE_ID = "panel-resize-style";
  var CSS = [
    ".panel-relative{position:relative}",
    // A drag that animates lags the pointer, and a resize that eases reads as a
    // stuck panel. Neither is ever wanted, so both are refused outright.
    ".panel-interacting{transition:none !important;animation:none !important;user-select:none}",
    ".panel-live{position:fixed;top:0;left:0;width:1px;height:1px;margin:-1px;padding:0;overflow:hidden;clip-path:inset(50%);white-space:nowrap;border:0}",

    ".panel-resize-handle{position:absolute;box-sizing:border-box;margin:0;padding:0;border:0;background:transparent;color:var(--on-surface,inherit);font:inherit;line-height:0;touch-action:none;z-index:6}",
    ".panel-resize-handle[hidden]{display:none}",
    '.panel-resize-handle[data-edge="n"],.panel-resize-handle[data-edge="s"]{left:18px;right:18px;height:10px;cursor:ns-resize}',
    '.panel-resize-handle[data-edge="n"]{top:0}',
    '.panel-resize-handle[data-edge="s"]{bottom:0}',
    '.panel-resize-handle[data-edge="e"],.panel-resize-handle[data-edge="w"]{top:var(--panel-handle-top,18px);bottom:18px;width:10px;cursor:ew-resize}',
    '.panel-resize-handle[data-edge="e"]{right:0}',
    '.panel-resize-handle[data-edge="w"]{left:0}',
    '.panel-resize-handle[data-edge="ne"],.panel-resize-handle[data-edge="se"],.panel-resize-handle[data-edge="sw"],.panel-resize-handle[data-edge="nw"]{width:20px;height:20px;z-index:7}',
    '.panel-resize-handle[data-edge="ne"]{top:0;right:0;cursor:nesw-resize}',
    '.panel-resize-handle[data-edge="se"]{bottom:0;right:0;cursor:nwse-resize}',
    '.panel-resize-handle[data-edge="sw"]{bottom:0;left:0;cursor:nesw-resize}',
    '.panel-resize-handle[data-edge="nw"]{top:0;left:0;cursor:nwse-resize}',
    ".panel-resize-handle.panel-handle-free{top:0;bottom:0;left:0;right:auto;width:14px;cursor:ew-resize}",
    // The tint is the hover/active state; the grip below is the resting one.
    '.panel-resize-handle::after{content:"";position:absolute;inset:2px;border-radius:5px;background:currentColor;opacity:0}',
    ".panel-resize-handle:hover::after{opacity:.22}",
    ".panel-resize-handle:active::after{opacity:.34}",
    '.panel-resize-handle[data-primary="true"]::before{content:"";position:absolute;background:currentColor;opacity:.42;border-radius:2px}',
    '.panel-resize-handle[data-primary="true"][data-edge="e"]::before,.panel-resize-handle[data-primary="true"][data-edge="w"]::before{top:50%;left:50%;width:3px;height:34px;transform:translate(-50%,-50%)}',
    '.panel-resize-handle[data-primary="true"][data-edge="n"]::before,.panel-resize-handle[data-primary="true"][data-edge="s"]::before{top:50%;left:50%;width:34px;height:3px;transform:translate(-50%,-50%)}',
    '.panel-resize-handle[data-primary="true"][data-edge="se"]::before,.panel-resize-handle[data-primary="true"][data-edge="ne"]::before,.panel-resize-handle[data-primary="true"][data-edge="sw"]::before,.panel-resize-handle[data-primary="true"][data-edge="nw"]::before{inset:5px;border-radius:0;background:none;border-bottom:2px solid currentColor;border-right:2px solid currentColor}',
    ".panel-resize-handle:focus-visible{outline:3px solid var(--primary,#4d5f92);outline-offset:1px;border-radius:6px}",
    ".panel-resize-handle:focus-visible::after{opacity:.3}",

    ".panel-move-handle{display:inline-flex;align-items:center;justify-content:center;width:32px;height:32px;flex:0 0 auto;margin:0;padding:0;border:0;border-radius:8px;background:transparent;color:inherit;font-size:1rem;line-height:1;cursor:move;touch-action:none}",
    ".panel-move-handle:hover{background:var(--state-layer,rgba(120,120,140,.14))}",
    ".panel-move-handle:focus-visible{outline:3px solid var(--primary,#4d5f92);outline-offset:2px}",
    ".panel-move-handle.panel-move-corner{position:absolute;top:4px;left:4px;z-index:7}",
    ".panel-drag-header{cursor:move;touch-action:none}",

    ".panel-collapse-toggle{display:flex;align-items:center;gap:8px;width:100%;min-height:36px;margin:6px 0 2px;padding:4px 8px;border:1px solid transparent;border-radius:10px;background:transparent;color:var(--on-surface-variant,inherit);font:inherit;font-size:.82rem;font-weight:650;text-align:left;cursor:pointer}",
    ".panel-collapse-toggle[hidden]{display:none}",
    ".panel-collapse-toggle:hover{background:var(--state-layer,rgba(120,120,140,.14))}",
    ".panel-collapse-toggle:focus-visible{outline:3px solid var(--primary,#4d5f92);outline-offset:2px}",
    ".panel-collapse-chevron{display:inline-block;width:1em;flex:0 0 auto}",
    ".panel-collapse-active{margin-left:auto;padding:2px 8px;border-radius:999px;background:var(--primary,#4d5f92);color:var(--on-primary,#fff);font-size:.74rem;font-weight:700}",
    ".panel-collapse-active:empty{display:none}",
    // Inline display is what a rendering module writes, so beating it needs
    // !important rather than more specificity.
    ".panel-collapsed{display:none !important}",

    "@media (prefers-reduced-motion: reduce){.panel-resize-handle,.panel-move-handle,.panel-collapse-toggle{transition:none !important}}",
    ':root[data-reduced-motion="true"] .panel-resize-handle,:root[data-reduced-motion="true"] .panel-move-handle,:root[data-reduced-motion="true"] .panel-collapse-toggle{transition:none !important}',
    "@media (forced-colors: active){.panel-resize-handle[data-primary=\"true\"]::before{border-color:CanvasText}.panel-collapse-active{border:1px solid CanvasText}}",
  ].join("");

  function installStyle() {
    if (document.getElementById(STYLE_ID)) return;
    var style = el("style", { id: STYLE_ID });
    style.textContent = CSS;
    (document.head || document.documentElement).appendChild(style);
  }

  // ----------------------------------------------------------- announcements
  var liveRegion = null;

  function ensureLive() {
    if (liveRegion && liveRegion.parentNode) return liveRegion;
    liveRegion = el("p", {
      id: "panel-live",
      class: "panel-live",
      role: "status",
      "aria-live": "polite",
    });
    document.body.appendChild(liveRegion);
    return liveRegion;
  }

  var announceFrame = 0;

  function announce(text) {
    var region = ensureLive();
    var message = String(text);
    // A live region that is assigned the same string twice announces once, and
    // every keyboard step has to be heard. Clearing in one frame and writing in
    // the next is what makes the second announcement a new one.
    region.textContent = "";
    if (announceFrame) window.cancelAnimationFrame(announceFrame);
    announceFrame = window.requestAnimationFrame(function () {
      announceFrame = 0;
      region.textContent = message;
    });
  }

  // ------------------------------------------------------------- persistence
  function readGeometry(key) {
    var geo = { w: null, h: null, x: 0, y: 0 };
    var raw = store.get(GEO_PREFIX + key, null);
    if (!raw || typeof raw !== "object") return geo;
    if (isFinite(raw.w) && Number(raw.w) > 0) geo.w = Number(raw.w);
    if (isFinite(raw.h) && Number(raw.h) > 0) geo.h = Number(raw.h);
    if (isFinite(raw.x)) geo.x = Number(raw.x);
    if (isFinite(raw.y)) geo.y = Number(raw.y);
    return geo;
  }

  function writeGeometry(key, geo) {
    store.set(GEO_PREFIX + key, { w: geo.w, h: geo.h, x: geo.x, y: geo.y });
  }

  // =========================================================== resize engine
  function enhance(options) {
    var config = options || {};
    var node = resolve(config.element);
    if (!node || node.nodeType !== 1) return null;
    if (enhanced.has(node)) return enhanced.get(node);

    var key = String(config.storageKey || "");
    if (!key) return null;

    var floating = config.floating === true;
    var edges = Array.isArray(config.edges) && config.edges.length
      ? config.edges.filter(function (edge) {
          return ALL_EDGES.indexOf(edge) !== -1;
        })
      : floating
      ? ALL_EDGES.slice()
      : FLOW_EDGES.slice();
    if (!edges.length) return null;

    var minWidth = config.min && config.min.width ? Number(config.min.width) : 200;
    var minHeight = config.min && config.min.height ? Number(config.min.height) : 88;
    var labelOf = toLabel(config.label || node.getAttribute("aria-label") || "Panel");
    var isActive = typeof config.active === "function" ? config.active : function () {
      return true;
    };
    var mirrorOf = typeof config.mirror === "function" ? config.mirror : function () {
      return null;
    };
    var placeHandles = typeof config.placeHandles === "function" ? config.placeHandles : null;

    var geo = readGeometry(key);
    var appliedX = 0;
    var appliedY = 0;
    var handles = [];
    var moveHandle = null;
    var moveParent = null;
    var drag = null;
    var frame = 0;
    var pending = null;
    var keyboardOrigin = null;

    var instance = {
      element: node,
      storageKey: key,
      floating: floating,
      label: labelOf,
      reset: reset,
      apply: apply,
      hasStored: hasStored,
    };

    // ------------------------------------------------------------- geometry
    function defaultSize() {
      var rect = node.getBoundingClientRect();
      return { width: rect.width, height: rect.height };
    }

    var getSize = typeof config.getSize === "function" ? config.getSize : defaultSize;

    function defaultApplySize(width, height) {
      if (width != null) {
        node.style.width = width + "px";
        node.style.maxWidth = "none";
        var mirror = mirrorOf(node);
        if (mirror) {
          mirror.style.width = width + "px";
          mirror.style.maxWidth = "none";
        }
      }
      if (height != null) {
        node.style.height = height + "px";
        node.style.maxHeight = "none";
        // A fixed height on a box that does not scroll simply deletes whatever
        // no longer fits, with no scrollbar to admit it.
        var overflow = "";
        try {
          overflow = window.getComputedStyle(node).overflowY;
        } catch (error) {
          overflow = "";
        }
        if (overflow === "visible" || overflow === "hidden") node.style.overflow = "auto";
      }
    }

    function defaultClearSize() {
      node.style.width = "";
      node.style.height = "";
      node.style.maxWidth = "";
      node.style.maxHeight = "";
      node.style.overflow = "";
      var mirror = mirrorOf(node);
      if (mirror) {
        mirror.style.width = "";
        mirror.style.maxWidth = "";
      }
    }

    var applySize = typeof config.applySize === "function" ? config.applySize : defaultApplySize;
    var clearSize = typeof config.clearSize === "function" ? config.clearSize : defaultClearSize;

    function limits() {
      var maxWidth = viewportWidth();
      var maxHeight = viewportHeight();
      if (!floating) {
        var parent = node.parentElement;
        if (parent && parent.clientWidth) maxWidth = Math.min(maxWidth, parent.clientWidth);
      }
      if (typeof config.limits === "function") {
        var extra = config.limits(node) || {};
        if (isFinite(extra.maxWidth)) maxWidth = Math.min(maxWidth, Number(extra.maxWidth));
        if (isFinite(extra.maxHeight)) maxHeight = Math.min(maxHeight, Number(extra.maxHeight));
      }
      return { maxWidth: Math.max(maxWidth, 1), maxHeight: Math.max(maxHeight, 1) };
    }

    function setOffset(x, y) {
      appliedX = x;
      appliedY = y;
      // Nothing else on this page transforms these elements, so owning the
      // property outright is safe and keeps the maths one subtraction long.
      node.style.transform = x || y ? "translate(" + x + "px, " + y + "px)" : "";
    }

    function hasStored() {
      return geo.w != null || geo.h != null || geo.x !== 0 || geo.y !== 0;
    }

    function showHandles(visible) {
      handles.forEach(function (entry) {
        entry.node.hidden = !visible;
      });
      if (moveHandle) moveHandle.hidden = !visible;
    }

    function apply() {
      if (!isActive()) {
        clearSize();
        setOffset(0, 0);
        showHandles(false);
        return;
      }
      showHandles(true);

      var bounds = limits();
      var width = geo.w == null ? null : clampNumber(geo.w, minWidth, bounds.maxWidth);
      var height = geo.h == null ? null : clampNumber(geo.h, minHeight, bounds.maxHeight);
      if (width == null && height == null) clearSize();
      else applySize(width, height);

      if (floating) {
        if (!laidOut(node)) {
          // A hidden panel measures zero; clamping against that would move it
          // somewhere arbitrary. Its geometry is reapplied when it is shown.
          setOffset(appliedX, appliedY);
        } else {
          var rect = node.getBoundingClientRect();
          var naturalLeft = rect.left - appliedX;
          var naturalTop = rect.top - appliedY;
          setOffset(
            clampOffset(naturalLeft, rect.width, geo.x, viewportWidth()),
            clampOffset(naturalTop, rect.height, geo.y, viewportHeight())
          );
        }
      }

      if (placeHandles) placeHandles(node, handles);
    }

    function sizeSentence() {
      var size = getSize();
      var name = labelOf();
      var width = Math.round(size.width);
      var height = Math.round(size.height);
      var tracksWidth = geo.w != null || edgeTracks("x");
      var tracksHeight = geo.h != null || edgeTracks("y");
      if (tracksWidth && !tracksHeight) {
        return t(name + ": width " + width + " pixels.", name + "：闊 " + width + " 像素。");
      }
      if (tracksHeight && !tracksWidth) {
        return t(name + ": height " + height + " pixels.", name + "：高 " + height + " 像素。");
      }
      return t(
        name + ": width " + width + " pixels, height " + height + " pixels.",
        name + "：闊 " + width + " 像素，高 " + height + " 像素。"
      );
    }

    function edgeTracks(axis) {
      return edges.some(function (edge) {
        return axis === "x"
          ? edge.indexOf("e") !== -1 || edge.indexOf("w") !== -1
          : edge.indexOf("n") !== -1 || edge.indexOf("s") !== -1;
      });
    }

    function positionSentence() {
      var rect = node.getBoundingClientRect();
      return t(
        labelOf() + " is " + Math.round(rect.left) + " pixels from the left and " +
          Math.round(rect.top) + " pixels from the top of the window.",
        labelOf() + " 距離視窗左邊 " + Math.round(rect.left) + " 像素、上邊 " +
          Math.round(rect.top) + " 像素。"
      );
    }

    function snapshot() {
      return { w: geo.w, h: geo.h, x: geo.x, y: geo.y };
    }

    function unchanged(state) {
      return state.w === geo.w && state.h === geo.h && state.x === geo.x && state.y === geo.y;
    }

    function restore(state) {
      geo.w = state.w;
      geo.h = state.h;
      geo.x = state.x;
      geo.y = state.y;
      apply();
    }

    function commit() {
      writeGeometry(key, geo);
    }

    function reset(quiet) {
      geo.w = null;
      geo.h = null;
      geo.x = 0;
      geo.y = 0;
      setOffset(0, 0);
      commit();
      apply();
      if (quiet !== true) {
        announce(
          t(
            labelOf() + " is back to its default size and position.",
            labelOf() + " 已經返回預設大細同位置。"
          )
        );
      }
    }

    // --------------------------------------------------------------- resize
    function resizeBy(edge, dx, dy) {
      var bounds = limits();
      var west = edge.indexOf("w") !== -1;
      var east = edge.indexOf("e") !== -1;
      var north = edge.indexOf("n") !== -1;
      var south = edge.indexOf("s") !== -1;
      var base = drag ? drag.size : getSize();
      var startRect = drag ? drag.rect : node.getBoundingClientRect();

      if (east || west) {
        geo.w = clampNumber(base.width + (east ? dx : -dx), minWidth, bounds.maxWidth);
      }
      if (north || south) {
        geo.h = clampNumber(base.height + (south ? dy : -dy), minHeight, bounds.maxHeight);
      }

      applySize(geo.w, geo.h);

      if (floating && laidOut(node)) {
        // Anchoring is a property of the panel's own CSS, which this file does
        // not know, so the edge that must stay put is measured rather than
        // assumed: apply the size, look at where the box actually landed, and
        // move it back by the difference.
        var rect = node.getBoundingClientRect();
        var naturalLeft = rect.left - appliedX;
        var naturalTop = rect.top - appliedY;
        var desiredLeft = west ? startRect.right - rect.width : startRect.left;
        var desiredTop = north ? startRect.bottom - rect.height : startRect.top;
        geo.x = clampOffset(naturalLeft, rect.width, desiredLeft - naturalLeft, viewportWidth());
        geo.y = clampOffset(naturalTop, rect.height, desiredTop - naturalTop, viewportHeight());
        setOffset(geo.x, geo.y);
      }

      if (placeHandles) placeHandles(node, handles);
    }

    function moveBy(dx, dy) {
      if (!floating || !laidOut(node)) return;
      var base = drag ? { x: drag.x, y: drag.y } : { x: geo.x, y: geo.y };
      var rect = node.getBoundingClientRect();
      var naturalLeft = rect.left - appliedX;
      var naturalTop = rect.top - appliedY;
      geo.x = clampOffset(naturalLeft, rect.width, base.x + dx, viewportWidth());
      geo.y = clampOffset(naturalTop, rect.height, base.y + dy, viewportHeight());
      setOffset(geo.x, geo.y);
      if (placeHandles) placeHandles(node, handles);
    }

    // -------------------------------------------------------------- pointer
    function beginDrag(mode, edge, event, target) {
      if (event.pointerType === "mouse" && event.button !== 0) return;
      if (!isActive()) return;
      drag = {
        mode: mode,
        edge: edge,
        target: target,
        pointerId: event.pointerId,
        startX: event.clientX,
        startY: event.clientY,
        size: getSize(),
        rect: node.getBoundingClientRect(),
        x: geo.x,
        y: geo.y,
        origin: snapshot(),
      };
      node.classList.add("panel-interacting");
      try {
        if (target.setPointerCapture) target.setPointerCapture(event.pointerId);
      } catch (error) {
        /* a browser refusing capture still delivers events to the target */
      }
      target.addEventListener("pointermove", onPointerMove);
      target.addEventListener("pointerup", onPointerUp);
      target.addEventListener("pointercancel", onPointerCancel);
    }

    function onPointerMove(event) {
      if (!drag || event.pointerId !== drag.pointerId) return;
      pending = { x: event.clientX, y: event.clientY };
      if (frame) return;
      frame = window.requestAnimationFrame(function () {
        frame = 0;
        if (!drag || !pending) return;
        var dx = pending.x - drag.startX;
        var dy = pending.y - drag.startY;
        if (drag.mode === "move") moveBy(dx, dy);
        else resizeBy(drag.edge, dx, dy);
      });
    }

    function endDrag() {
      if (!drag) return null;
      var finished = drag;
      drag = null;
      pending = null;
      if (frame) {
        window.cancelAnimationFrame(frame);
        frame = 0;
      }
      node.classList.remove("panel-interacting");
      finished.target.removeEventListener("pointermove", onPointerMove);
      finished.target.removeEventListener("pointerup", onPointerUp);
      finished.target.removeEventListener("pointercancel", onPointerCancel);
      try {
        if (finished.target.releasePointerCapture) {
          finished.target.releasePointerCapture(finished.pointerId);
        }
      } catch (error) {
        /* capture may already have been lost with the pointer */
      }
      return finished;
    }

    function onPointerUp(event) {
      if (!drag || event.pointerId !== drag.pointerId) return;
      var finished = endDrag();
      commit();
      announce(finished.mode === "move" ? positionSentence() : sizeSentence());
    }

    function onPointerCancel(event) {
      if (!drag || event.pointerId !== drag.pointerId) return;
      var finished = endDrag();
      restore(finished.origin);
    }

    // ------------------------------------------------------------- keyboard
    function stepFor(event) {
      return event.shiftKey ? BIG_STEP : STEP;
    }

    function onKeyDown(mode, edge, event) {
      if (!isActive()) return;
      var step = stepFor(event);
      var dx = 0;
      var dy = 0;
      if (event.key === "ArrowLeft") dx = -step;
      else if (event.key === "ArrowRight") dx = step;
      else if (event.key === "ArrowUp") dy = -step;
      else if (event.key === "ArrowDown") dy = step;
      else if (event.key === "Home") {
        event.preventDefault();
        reset();
        return;
      } else if (event.key === "Escape") {
        // With nothing to undo, Escape belongs to whatever surrounds the panel:
        // swallowing it here would leave a drawer that refuses to close.
        if (!keyboardOrigin || unchanged(keyboardOrigin)) return;
        event.preventDefault();
        event.stopPropagation(); // a drawer's own Escape must not close it mid-adjust
        restore(keyboardOrigin);
        commit();
        announce(
          t(
            labelOf() + " restored to the size and position it had before this adjustment.",
            labelOf() + " 已經復原到今次調整之前嘅大細同位置。"
          )
        );
        return;
      } else if (event.key === "Enter" || event.key === " " || event.key === "Spacebar") {
        event.preventDefault();
        commit();
        keyboardOrigin = snapshot();
        announce(
          (mode === "move" ? positionSentence() : sizeSentence()) + " " + t("Kept.", "已保留。")
        );
        return;
      } else {
        return;
      }

      event.preventDefault();
      if (mode === "move") {
        moveBy(dx, dy);
        announce(positionSentence());
      } else {
        // Arrow keys on a corner grow the panel from its top-left, which is what
        // the one focusable handle sits on, so no anchor juggling is needed.
        resizeBy(edge.indexOf("w") !== -1 || edge.indexOf("n") !== -1 ? "se" : edge, dx, dy);
        announce(sizeSentence());
      }
    }

    // -------------------------------------------------------------- handles
    function resizeLabel() {
      return t(
        "Resize " + labelOf() +
          ". Drag it, or press the arrow keys; Shift takes larger steps, Home restores the default size and position, Enter keeps the change, Escape undoes it.",
        "調整" + labelOf() +
          "嘅大細。可以拖，或者撳方向鍵；Shift 行大步，Home 還原預設大細同位置，Enter 保留，Escape 復原。"
      );
    }

    function moveLabel() {
      return t(
        "Move " + labelOf() +
          ". Drag it, or press the arrow keys; Shift takes larger steps, Home restores the default size and position, Enter keeps the change, Escape undoes it.",
        "移動" + labelOf() +
          "。可以拖，或者撳方向鍵；Shift 行大步，Home 還原預設大細同位置，Enter 保留，Escape 復原。"
      );
    }

    function buildHandles() {
      var primary = edges.indexOf("se") !== -1 ? "se"
        : edges.indexOf("e") !== -1 ? "e"
        : edges.indexOf("s") !== -1 ? "s"
        : edges[0];

      edges.forEach(function (edge) {
        var isPrimary = edge === primary;
        var classes = "panel-resize-handle" + (config.freeHandles ? " panel-handle-free" : "");
        // Eight focusable buttons per panel would bury the page in tab stops, so
        // exactly one handle carries the keyboard path and the rest are pointer
        // affordances with no accessible presence of their own.
        var handleNode = isPrimary
          ? el("button", {
              type: "button",
              class: classes,
              "data-edge": edge,
              "data-primary": "true",
            })
          : el("div", { class: classes, "data-edge": edge, "aria-hidden": "true" });

        handleNode.addEventListener("pointerdown", function (event) {
          event.preventDefault();
          if (isPrimary && handleNode.focus) handleNode.focus();
          beginDrag("resize", edge, event, handleNode);
        });
        handleNode.addEventListener("dblclick", function (event) {
          event.preventDefault();
          reset();
        });
        if (isPrimary) {
          handleNode.addEventListener("focus", function () {
            keyboardOrigin = snapshot();
          });
          handleNode.addEventListener("keydown", function (event) {
            onKeyDown("resize", edge, event);
          });
        }
        node.appendChild(handleNode);
        handles.push({ node: handleNode, edge: edge, primary: isPrimary });
      });
    }

    function buildMoveHandle() {
      if (!floating) return;
      var header = config.handle ? node.querySelector(config.handle) : null;
      moveHandle = el(
        "button",
        {
          type: "button",
          class: "panel-move-handle" + (header ? "" : " panel-move-corner"),
        },
        el("span", { "aria-hidden": "true", text: "⠿" })
      );
      moveHandle.addEventListener("pointerdown", function (event) {
        event.preventDefault();
        moveHandle.focus();
        beginDrag("move", null, event, moveHandle);
      });
      moveHandle.addEventListener("dblclick", function (event) {
        event.preventDefault();
        reset();
      });
      moveHandle.addEventListener("focus", function () {
        keyboardOrigin = snapshot();
      });
      moveHandle.addEventListener("keydown", function (event) {
        onKeyDown("move", null, event);
      });

      if (header) {
        header.classList.add("panel-drag-header");
        header.insertBefore(moveHandle, header.firstChild);
        moveParent = header;
        header.addEventListener("pointerdown", function (event) {
          if (event.target === moveHandle || moveHandle.contains(event.target)) return;
          // A header carries real controls; dragging must never swallow them.
          if (
            event.target.closest &&
            event.target.closest("button, a, input, select, textarea, [contenteditable], summary")
          ) {
            return;
          }
          event.preventDefault();
          beginDrag("move", null, event, header);
        });
      } else {
        node.appendChild(moveHandle);
        moveParent = node;
      }
    }

    function relabel() {
      handles.forEach(function (entry) {
        if (!entry.primary) return;
        entry.node.setAttribute("aria-label", resizeLabel());
        entry.node.title = resizeLabel();
      });
      if (moveHandle) {
        moveHandle.setAttribute("aria-label", moveLabel());
        moveHandle.title = moveLabel();
      }
    }

    // A rendering module that replaces its panel's children takes the handles
    // with it (the documentation index does exactly that), so they are put back
    // rather than silently lost.
    function ensureHandles() {
      handles.forEach(function (entry) {
        if (entry.node.parentNode !== node) node.appendChild(entry.node);
      });
      if (moveHandle && moveParent && moveHandle.parentNode !== moveParent) {
        if (moveParent === node) moveParent.appendChild(moveHandle);
        else moveParent.insertBefore(moveHandle, moveParent.firstChild);
      }
    }

    // ----------------------------------------------------------------- boot
    var position = "";
    try {
      position = window.getComputedStyle(node).position;
    } catch (error) {
      position = "";
    }
    if (position === "static" || !position) node.classList.add("panel-relative");
    if (config.handleTop) node.style.setProperty("--panel-handle-top", config.handleTop + "px");

    buildHandles();
    buildMoveHandle();
    relabel();
    apply();

    if (node.tagName === "DETAILS") node.addEventListener("toggle", apply);

    node.addEventListener("contextmenu", function (event) {
      if (typeof site.contextMenu !== "function") return;
      // A nested panel claims the event first; reopening here would replace its
      // menu with this one halfway through the same right-click.
      if (event.defaultPrevented) return;
      if (event.target.closest && event.target.closest("input, textarea, select")) return;
      site.contextMenu(menuItems(), event, labelOf());
    });

    function menuItems() {
      var stored = hasStored();
      return [
        {
          label: t("Reset size and position", "還原大細同位置"),
          shortcut: t("Home on the handle", "喺手掣撳 Home"),
          disabled: !stored,
          reason: stored
            ? ""
            : t(
                "This panel is already at its shipped size and position, so there is nothing to reset.",
                "呢個面板已經係出廠大細同位置，冇嘢可以還原。"
              ),
          run: function () {
            reset();
            toastReset(labelOf());
          },
        },
        {
          label: t("Reset every panel on this page", "還原呢一頁所有面板"),
          disabled: !instances.some(function (entry) {
            return entry.hasStored();
          }),
          reason: t(
            "No panel on this page has a stored size or position.",
            "呢一頁冇任何面板儲存過大細或者位置。"
          ),
          run: resetAll,
        },
      ];
    }

    var observer = new MutationObserver(function (records) {
      var structural = records.some(function (record) {
        return record.type === "childList";
      });
      if (structural) ensureHandles();
      apply();
    });
    observer.observe(node, {
      childList: true,
      attributes: true,
      attributeFilter: ["hidden", "open"],
    });
    // A panel inside a dialog gains its layout box only when the dialog opens,
    // and nothing on the panel itself changes at that moment.
    var host = node.closest ? node.closest("dialog") : null;
    if (host) observer.observe(host, { attributes: true, attributeFilter: ["open"] });

    instance.relabel = relabel;
    instance.ensureHandles = ensureHandles;
    enhanced.set(node, instance);
    instances.push(instance);
    return instance;
  }

  function toastReset(name) {
    if (typeof site.toast !== "function") return;
    site.toast(
      t(
        name + " is back to its default size and position.",
        name + " 已經返回預設大細同位置。"
      ),
      "info"
    );
  }

  function resetAll() {
    var count = 0;
    instances.forEach(function (entry) {
      if (!entry.hasStored()) return;
      entry.reset(true);
      count++;
    });
    var text = count
      ? t(
          count + " panels are back to their default size and position.",
          count + " 個面板已經返回預設大細同位置。"
        )
      : t(
          "No panel had a stored size or position, so nothing changed.",
          "冇面板儲存過大細或者位置，所以乜都冇改。"
        );
    announce(text);
    if (typeof site.toast === "function") site.toast(text, "info");
    return count;
  }

  // ============================================================ collapsibles
  function controlName(node) {
    var label = node.getAttribute("aria-label");
    if (label) return label.trim();
    var labelledBy = node.getAttribute("aria-labelledby");
    if (labelledBy) {
      var owner = document.getElementById(labelledBy.split(/\s+/)[0]);
      if (owner && owner.textContent.trim()) return owner.textContent.trim();
    }
    if (node.id) {
      var tag = document.querySelector('label[for="' + node.id + '"]');
      if (tag && tag.textContent.trim()) return tag.textContent.trim();
    }
    var wrapper = node.closest ? node.closest("label") : null;
    if (wrapper && wrapper.textContent.trim()) return wrapper.textContent.trim();
    var text = String(node.textContent || "").trim();
    if (text) return text.replace(/\s+/g, " ").slice(0, 40);
    return node.getAttribute("placeholder") || node.getAttribute("name") || "filter";
  }

  var TEXTUAL = {
    text: 1,
    search: 1,
    number: 1,
    date: 1,
    month: 1,
    week: 1,
    time: 1,
    "datetime-local": 1,
    email: 1,
    url: 1,
    tel: 1,
  };

  /**
   * Which controls inside a filter row are currently narrowing the collection.
   * Deliberately conservative: a control this cannot read is reported as
   * inactive rather than guessed at, and a caller that knows better passes its
   * own isActive.
   */
  function defaultActiveControls(root) {
    var found = [];
    var nodes = root.querySelectorAll(
      "input, select, [aria-pressed], [aria-checked], [data-filter-active]"
    );
    Array.prototype.forEach.call(nodes, function (node) {
      if (node.disabled || node.hidden) return;
      var active = false;
      if (node.tagName === "INPUT") {
        var type = String(node.type || "text").toLowerCase();
        if (type === "checkbox" || type === "radio") active = node.checked === true;
        else if (TEXTUAL[type]) active = String(node.value || "").trim() !== "";
      } else if (node.tagName === "SELECT") {
        var fallback = node.querySelector("option[selected]");
        var defaultIndex = fallback ? fallback.index : 0;
        active = node.selectedIndex !== defaultIndex;
      }
      if (!active && node.getAttribute("aria-pressed") === "true") active = true;
      if (!active && node.getAttribute("aria-checked") === "true") active = true;
      if (!active && node.getAttribute("data-filter-active") === "true") active = true;
      if (active) found.push(controlName(node));
    });
    var unique = [];
    found.forEach(function (name) {
      if (unique.indexOf(name) === -1) unique.push(name);
    });
    return unique;
  }

  function collapsible(options) {
    var config = options || {};
    var node = resolve(config.element);
    if (!node || node.nodeType !== 1) return null;
    if (folded.has(node)) return folded.get(node);

    var key = String(config.storageKey || "");
    if (!key) return null;

    ensureId(node, "panel-fold-" + slug(key));
    var labelOf = toLabel(config.label || node.getAttribute("aria-label") || ["Filters", "篩選"]);
    var activeControls = typeof config.isActive === "function" ? config.isActive : defaultActiveControls;
    var collapsed = store.get(COLLAPSE_PREFIX + key, config.startCollapsed === true) === true;

    var chevron = el("span", { class: "panel-collapse-chevron", "aria-hidden": "true" });
    var text = el("span", { class: "panel-collapse-label" });
    var note = el("span", { class: "panel-collapse-active" });
    var toggle = el(
      "button",
      { type: "button", class: "panel-collapse-toggle", "aria-controls": node.id },
      chevron,
      text,
      note
    );

    if (!node.parentNode) return null;
    node.parentNode.insertBefore(toggle, node);

    function hasContent() {
      return node.children.length > 0 || String(node.textContent || "").trim() !== "";
    }

    function activeSentence(names) {
      var listed = names.slice(0, 3).join(", ");
      var extra = names.length - 3;
      if (extra > 0) {
        listed = t(listed + " and " + extra + " more", listed + " 同另外 " + extra + " 個");
      }
      return t(
        names.length + " still applied: " + listed,
        "仲有 " + names.length + " 個生效：" + listed
      );
    }

    function render() {
      var names = activeControls(node) || [];
      toggle.hidden = !hasContent();
      toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
      node.classList.toggle("panel-collapsed", collapsed);
      chevron.textContent = collapsed ? "▸" : "▾";
      text.textContent = labelOf();
      // Only while hidden: an expanded row shows its own state, and a badge
      // repeating it would just be noise.
      note.textContent = collapsed && names.length ? activeSentence(names) : "";
      toggle.title = collapsed
        ? t("Show " + labelOf(), "顯示" + labelOf())
        : t("Hide " + labelOf(), "收埋" + labelOf());
      return names;
    }

    toggle.addEventListener("click", function () {
      collapsed = !collapsed;
      store.set(COLLAPSE_PREFIX + key, collapsed);
      var names = render();
      if (collapsed && names.length && typeof site.toast === "function") {
        // The row is out of sight but still excluding rows, which is exactly the
        // state a user mistakes for missing data.
        site.toast(
          t(
            labelOf() + " is hidden, but " + activeSentence(names) + ". Results are still filtered.",
            labelOf() + " 收埋咗，但係" + activeSentence(names) + "。結果仍然有篩選。"
          ),
          "warning"
        );
      }
    });

    var observer = new MutationObserver(function () {
      render();
    });
    observer.observe(node, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["aria-pressed", "aria-checked", "data-filter-active", "value", "hidden", "disabled", "selected"],
    });
    // Typing and toggling change no attribute, so the events carry what the
    // observer cannot see.
    node.addEventListener("input", render);
    node.addEventListener("change", render);
    node.addEventListener("click", function () {
      window.setTimeout(render, 0); // after the row's own click handler has run
    });

    render();

    var handle = {
      element: node,
      storageKey: key,
      label: labelOf,
      isCollapsed: function () {
        return collapsed;
      },
      activeNames: function () {
        return activeControls(node) || [];
      },
      toggle: function () {
        toggle.click();
      },
      set: function (next) {
        if (collapsed === (next === true)) return;
        toggle.click();
      },
      refresh: render,
    };
    folded.set(node, handle);
    collapsibles.push(handle);
    return handle;
  }

  // ========================================================= known surfaces
  function queryEach(root, selector, build) {
    var found;
    try {
      found = root.querySelectorAll(selector);
    } catch (error) {
      return;
    }
    Array.prototype.forEach.call(found, build);
  }

  function each(selector, build) {
    queryEach(document, selector, build);
  }

  var anonymous = 0;

  /** A storage key must identify one surface, so an id-less row gets its own. */
  function keyFor(node, prefix) {
    if (node.id) return prefix + node.id;
    if (!node.getAttribute("data-panel-key")) {
      anonymous += 1;
      node.setAttribute("data-panel-key", prefix + anonymous);
    }
    return node.getAttribute("data-panel-key");
  }

  function docsTwoColumn() {
    try {
      if (window.matchMedia) return !window.matchMedia(DOCS_BREAKPOINT).matches;
    } catch (error) {
      /* fall through to the width check */
    }
    return viewportWidth() > 900;
  }

  function docsIndexWidth() {
    var index = document.getElementById("docs-index");
    return index ? index.getBoundingClientRect().width : 0;
  }

  function applyKnownPanels() {
    var drawer = document.getElementById("notifications");
    if (drawer) {
      enhance({
        element: drawer,
        storageKey: "notifications",
        floating: true,
        handle: ".drawer-head",
        label: ["Notification history", "通知記錄"],
        min: { width: 280, height: 200 },
      });
    }

    var palette = document.querySelector("#command-palette .palette-card");
    if (palette) {
      enhance({
        element: palette,
        storageKey: "palette",
        floating: true,
        handle: ".drawer-head",
        label: ["Command palette", "指令面板"],
        min: { width: 300, height: 220 },
        // The dialog is the box the browser centres, so it follows the card's
        // width; otherwise a resized card drifts off to one side of it.
        mirror: function (node) {
          return node.parentElement;
        },
      });
    }

    each(".regex-builder", function (node) {
      var summary = node.querySelector("summary");
      var name = summary ? String(summary.textContent || "").trim() : "";
      enhance({
        element: node,
        storageKey: "regex." + (node.id || slug(name) || "builder"),
        floating: false,
        edges: ["e", "s", "se"],
        label: name || ["Regex builder", "Regex builder"],
        min: { width: 260, height: 120 },
        // A closed accordion sized to a stored height would be a tall empty box.
        active: function () {
          return node.open === true;
        },
        handleTop: 46, // clear of the summary row, which stays fully clickable
      });
    });

    var docs = document.querySelector(".docs-layout");
    if (docs) {
      enhance({
        element: docs,
        storageKey: "docs-split",
        floating: false,
        edges: ["e"],
        freeHandles: true,
        label: ["Documentation index column", "文件索引欄"],
        min: { width: 180 },
        active: docsTwoColumn,
        getSize: function () {
          return { width: docsIndexWidth(), height: docs.getBoundingClientRect().height };
        },
        applySize: function (width) {
          if (width == null) return;
          docs.style.gridTemplateColumns = width + "px minmax(0, 1fr)";
        },
        clearSize: function () {
          docs.style.gridTemplateColumns = "";
        },
        limits: function () {
          return {
            maxWidth: Math.max(180, (docs.clientWidth || 0) - DOCS_ARTICLE_MIN - DOCS_GAP),
            maxHeight: Infinity,
          };
        },
        placeHandles: function (node, handles) {
          var left = docsIndexWidth() + DOCS_GAP / 2 - 7;
          handles.forEach(function (entry) {
            entry.node.style.left = Math.max(0, left) + "px";
          });
        },
      });
    }

    // The move-into-group picker is created by whichever surface owns tab
    // groups. It is enhanced when it exists and skipped in silence when it does
    // not, rather than reserving a handle for a panel that was never built.
    ["#group-picker", ".group-picker", '[data-panel="group-picker"]'].forEach(function (selector) {
      each(selector, function (node) {
        enhance({
          element: node,
          storageKey: "group-picker" + (node.id ? "." + node.id : ""),
          floating: true,
          handle: ".picker-head, .drawer-head, header",
          label: ["Move into group", "移入群組"],
          min: { width: 260, height: 180 },
        });
      });
    });
  }

  var FILTER_LABELS = {
    "changelog-filters": ["Changelog filters", "更新日誌篩選"],
    "history-filters": ["History filters", "記錄篩選"],
    "feature-categories": ["Category filters", "分類篩選"],
  };

  function applyKnownCollapsibles() {
    each(".filter-row", function (node) {
      collapsible({
        element: node,
        storageKey: keyFor(node, "filters."),
        label: FILTER_LABELS[node.id] || ["Filters", "篩選"],
        startCollapsed: false,
      });
    });

    var categories = document.getElementById("feature-categories");
    if (categories) {
      collapsible({
        element: categories,
        storageKey: "filters.feature-categories",
        label: FILTER_LABELS["feature-categories"],
        startCollapsed: false,
        // The leading chip is the un-narrowed "All" and carries an empty
        // data-category, so pressing it is not a filter and must not be
        // reported as one.
        isActive: function (root) {
          var names = [];
          queryEach(root, '.chip[aria-pressed="true"]', function (chip) {
            if (chip.getAttribute("data-category")) names.push(controlName(chip));
          });
          return names;
        },
      });
    }

    // Anything that only describes the collection starts folded away.
    ["[data-stats]", ".stats-row", ".stats-block", "#history-stats", "#changelog-stats"].forEach(
      function (selector) {
        each(selector, function (node) {
          collapsible({
            element: node,
            storageKey: keyFor(node, "stats."),
            label: ["Statistics", "統計"],
            startCollapsed: true,
          });
        });
      }
    );
  }

  function applyKnown() {
    applyKnownPanels();
    applyKnownCollapsibles();
    // Any surface built later can opt in by markup alone.
    each("[data-panel-resize]", function (node) {
      enhance({
        element: node,
        storageKey: node.getAttribute("data-panel-resize"),
        floating: node.hasAttribute("data-panel-floating"),
        handle: node.getAttribute("data-panel-handle") || ".drawer-head",
        label: node.getAttribute("aria-label") || ["Panel", "面板"],
      });
    });
    each("[data-panel-collapse]", function (node) {
      collapsible({
        element: node,
        storageKey: node.getAttribute("data-panel-collapse"),
        startCollapsed: node.getAttribute("data-panel-collapsed") === "true",
        label: node.getAttribute("aria-label") || ["Filters", "篩選"],
      });
    });
  }

  // ------------------------------------------------------------------- boot
  var reflowFrame = 0;

  function scheduleReflow() {
    if (reflowFrame) return;
    reflowFrame = window.requestAnimationFrame(function () {
      reflowFrame = 0;
      instances.forEach(function (entry) {
        try {
          entry.ensureHandles();
          entry.apply();
        } catch (error) {
          /* one panel failing to re-clamp must not freeze the others */
        }
      });
    });
  }

  function relanguage() {
    instances.forEach(function (entry) {
      try {
        entry.relabel();
      } catch (error) {}
    });
    collapsibles.forEach(function (entry) {
      try {
        entry.refresh();
      } catch (error) {}
    });
  }

  function paletteEntries() {
    var rows = [];
    instances.forEach(function (entry) {
      if (!entry.hasStored()) return;
      rows.push({
        kind: "command",
        title: t(
          "Reset " + entry.label() + " size and position",
          "還原" + entry.label() + "嘅大細同位置"
        ),
        subtitle: t(
          "Returns this panel to the size and position the site ships with.",
          "令呢個面板返回網站出廠嘅大細同位置。"
        ),
        run: function () {
          entry.reset();
          toastReset(entry.label());
        },
      });
    });
    if (rows.length > 1) {
      rows.push({
        kind: "command",
        title: t("Reset every panel size and position", "還原所有面板嘅大細同位置"),
        subtitle: t(
          rows.length + " panels have a stored size or position in this browser.",
          "呢個瀏覽器有 " + rows.length + " 個面板儲存咗大細或者位置。"
        ),
        run: resetAll,
      });
    }
    collapsibles.forEach(function (entry) {
      var names = entry.activeNames();
      var hidden = entry.isCollapsed();
      rows.push({
        kind: "command",
        title: hidden
          ? t("Show " + entry.label(), "顯示" + entry.label())
          : t("Hide " + entry.label(), "收埋" + entry.label()),
        subtitle: names.length
          ? t(
              names.length + " filters are applied right now: " + names.join(", "),
              "而家有 " + names.length + " 個篩選生效：" + names.join("、")
            )
          : t("No filter in this row is applied right now.", "呢行而家冇任何篩選生效。"),
        run: function () {
          entry.toggle();
        },
      });
    });
    return rows;
  }

  function boot() {
    installStyle();
    ensureLive();
    applyKnown();

    // A surface built after this ran still gets its panel behaviour, without
    // this file having to be reloaded or the other module having to know it.
    // Rendering a results list fires hundreds of these, and enhancing is itself
    // a DOM write, so the rescan is debounced rather than run per record.
    var scanTimer = 0;
    var watcher = new MutationObserver(function (records) {
      if (scanTimer) return;
      var added = records.some(function (record) {
        return record.addedNodes && record.addedNodes.length;
      });
      if (!added) return;
      scanTimer = window.setTimeout(function () {
        scanTimer = 0;
        applyKnown();
      }, 250);
    });
    watcher.observe(document.body, { childList: true, subtree: true });

    window.addEventListener("resize", scheduleReflow);
    if (window.visualViewport) window.visualViewport.addEventListener("resize", scheduleReflow);
    if (typeof site.onTabChange === "function") site.onTabChange(scheduleReflow);

    settings.onChange(function (key) {
      if (
        key === null ||
        key === "language" ||
        key === "emoji" ||
        key === "funnyEn" ||
        key === "funnyYue"
      ) {
        relanguage();
      }
      if (key === null || key === "density" || key === "scale" || key === "font") scheduleReflow();
    });

    site.registerPaletteSource(paletteEntries);
  }

  site.panel = {
    enhance: enhance,
    collapsible: collapsible,
    resetAll: resetAll,
    panels: function () {
      return instances.slice();
    },
    rows: function () {
      return collapsibles.slice();
    },
  };

  site.ready(boot);
})();
