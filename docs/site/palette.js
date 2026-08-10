/* Command palette: one searchable index of everything this page can reach.
 *
 * The palette keeps no inventory of its own. Tabs, features, articles,
 * captures, settings and notification commands each register a source with the
 * core, and this file only collects, filters, and runs them. A second
 * hand-maintained list here would be the copy that silently goes stale the day
 * a surface is added, and a palette that cannot find a surface is worse than
 * no palette at all.
 */
(function () {
  "use strict";

  var site = window.AmuletSite;
  if (!site) return;

  // Enough rows to scroll without the list becoming the slow part of a
  // keystroke. Anything past this is reported in the status line, never
  // silently dropped.
  var MAX_RENDERED = 50;

  site.ready(function () {
    var dialog = document.getElementById("command-palette");
    var input = document.getElementById("palette-search");
    var results = document.getElementById("palette-results");
    if (!dialog || !input || !results) return;

    var openButton = document.getElementById("palette-open");
    var closeButton = document.getElementById("palette-close");
    var regexOpen = document.getElementById("palette-regex-open");
    var regexPanel = document.getElementById("palette-regex");
    var empty = document.getElementById("palette-empty");

    var status = site.el("p", {
      class: "palette-status",
      id: "palette-status",
      role: "status",
      style: "margin:0;font-size:.85rem;color:var(--secondary)",
    });
    // Outside the listbox rather than inside it: a listbox whose children are
    // not all options confuses the same assistive technology the count is
    // there to inform.
    results.parentNode.insertBefore(status, results);

    if (openButton) openButton.setAttribute("aria-haspopup", "dialog");

    var entries = [];
    var rendered = [];
    var options = [];
    var activeIndex = 0;
    var restoreFocusTo = null;
    var pressTarget = null;

    // ------------------------------------------------------------- inventory
    function collect() {
      var out = [];
      var sources = typeof site.paletteSources === "function" ? site.paletteSources() : [];
      sources.forEach(function (source) {
        var produced;
        try {
          produced = typeof source === "function" ? source() : source;
        } catch (error) {
          return; // one broken contributor must not empty the whole palette
        }
        if (!produced) return;
        var list = Array.isArray(produced) ? produced : [produced];
        list.forEach(function (entry) {
          // A row that cannot act is not rendered; a dead command in a palette
          // reads as a broken feature rather than as a missing one.
          if (!entry || typeof entry.run !== "function") return;
          var title = String(entry.title == null ? "" : entry.title).trim();
          if (!title) return;
          var subtitle = String(entry.subtitle == null ? "" : entry.subtitle).trim();
          var kind = String(entry.kind == null ? "" : entry.kind).trim();
          out.push({
            kind: kind,
            title: title,
            subtitle: subtitle,
            run: entry.run,
            haystack: title + " " + subtitle + " " + kind,
          });
        });
      });
      return out;
    }

    // ---------------------------------------------------------------- search
    var search = null;
    if (site.regex && typeof site.regex.attach === "function") {
      search = site.regex.attach({
        name: "palette",
        input: input,
        openButton: regexOpen,
        panel: regexPanel,
        sample: "Open the appearance editor",
        onChange: function () {
          activeIndex = 0;
          render();
        },
      });
    }
    if (!search) {
      // regex-builder.js owns the bounded pattern surface. Without it the
      // palette stays a working plain-text search instead of shipping a regex
      // button that looks live and cannot do anything.
      if (regexOpen) regexOpen.hidden = true;
      if (regexPanel) regexPanel.hidden = true;
      input.addEventListener("input", function () {
        activeIndex = 0;
        render();
      });
      search = {
        state: function () {
          return { query: input.value, regex: "", flags: "i", valid: true, feedback: "" };
        },
        matches: function (text) {
          try {
            return site.matcher(input.value, false, "i").test(text);
          } catch (error) {
            return false;
          }
        },
        refresh: function () {},
      };
    }

    // ---------------------------------------------------------------- render
    function reducedMotion() {
      if (site.settings.get("reducedMotion")) return true;
      return typeof window.matchMedia === "function" &&
        window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    }

    function statusText(total, shownCount, state) {
      if (state.valid === false) {
        var reason = state.feedback ? String(state.feedback) : "";
        return site.lang.emoji("⚠️") + site.lang.t(
          "Pattern not run: " + reason,
          "圖案未行到：" + reason
        );
      }
      if (total === 0) return "";
      var line = site.lang.t(
        total + (total === 1 ? " result." : " results."),
        "共 " + total + " 個結果。"
      );
      if (shownCount < total) {
        line += " " + site.lang.t(
          "Showing " + shownCount + " of " + total + " matches — narrow the search to reach the rest.",
          "只顯示 " + shownCount + " 個，總共 " + total + " 個 — 收窄搜尋先睇到其餘嘅。"
        );
      }
      return site.lang.emoji("🔎") + line;
    }

    function buildOption(entry, index) {
      var label = entry.title +
        (entry.subtitle ? ". " + entry.subtitle : "") +
        (entry.kind ? ". " + entry.kind : "");
      return site.el(
        "button",
        {
          type: "button",
          id: "palette-option-" + index,
          class: "palette-result",
          role: "option",
          tabindex: "-1",
          "aria-selected": "false",
          "aria-label": label,
          onclick: function () {
            runEntry(entry);
          },
        },
        site.el(
          "span",
          null,
          site.el("strong", { text: entry.title }),
          entry.subtitle ? site.el("br") : null,
          entry.subtitle ? site.el("small", { text: entry.subtitle }) : null
        ),
        entry.kind
          ? site.el("small", {
              class: "palette-result-kind",
              text: entry.kind,
              style: "opacity:.75;white-space:nowrap",
            })
          : null
      );
    }

    function setActive(index) {
      if (!options.length) {
        activeIndex = 0;
        input.removeAttribute("aria-activedescendant");
        return;
      }
      activeIndex = Math.max(0, Math.min(index, options.length - 1));
      options.forEach(function (option, i) {
        var on = i === activeIndex;
        option.setAttribute("aria-selected", on ? "true" : "false");
        // Focus stays in the combobox, so the active row cannot borrow the
        // sheet's :focus-visible ring and has to carry its own.
        option.style.outline = on ? "3px solid var(--primary)" : "";
        option.style.outlineOffset = on ? "2px" : "";
      });
      input.setAttribute("aria-activedescendant", options[activeIndex].id);
      options[activeIndex].scrollIntoView({
        block: "nearest",
        behavior: reducedMotion() ? "auto" : "smooth",
      });
    }

    function render() {
      // attach() may report an initial state before it has returned, so this
      // can be reached while `search` is still being assigned.
      if (!search) return;
      var state = {};
      try {
        state = search.state() || {};
      } catch (error) {
        state = { valid: false, feedback: error && error.message ? error.message : String(error) };
      }
      var invalid = state.valid === false;

      // Everything is filtered through the matcher, including an empty query:
      // an empty plain query and an empty pattern both match everything, so
      // there is no second code path to disagree with the builder's own state.
      var matched = [];
      if (!invalid) {
        for (var i = 0; i < entries.length; i++) {
          var candidate = entries[i];
          var hit = false;
          try {
            hit = search.matches(candidate.haystack);
          } catch (error) {
            hit = false;
          }
          if (hit) matched.push(candidate);
        }
      }

      rendered = matched.slice(0, MAX_RENDERED);
      options = [];
      var fragment = document.createDocumentFragment();
      rendered.forEach(function (entry, index) {
        var option = buildOption(entry, index);
        options.push(option);
        fragment.appendChild(option);
      });
      results.textContent = "";
      results.appendChild(fragment);

      // The live region stays in the tree even when it has nothing to say:
      // hiding it takes it out of the accessibility tree, and the count it
      // exists to announce would then arrive silently or not at all.
      var line = statusText(matched.length, rendered.length, state);
      if (status.textContent !== line) status.textContent = line;

      // An invalid pattern never ran, so "nothing matches" would be a claim
      // about the data that nothing has actually checked.
      if (empty) empty.hidden = invalid || matched.length > 0;

      input.setAttribute("aria-expanded", options.length ? "true" : "false");
      setActive(activeIndex);
    }

    // ------------------------------------------------------------ open/close
    function isOpen() {
      return dialog.open === true || dialog.hasAttribute("open");
    }

    function afterClose() {
      var target = restoreFocusTo;
      restoreFocusTo = null;
      if (target && document.contains(target) && typeof target.focus === "function") {
        target.focus();
      }
    }

    function openPalette(trigger) {
      if (isOpen()) {
        input.focus();
        input.select();
        return;
      }
      var active = document.activeElement;
      restoreFocusTo = trigger || (active && active !== document.body ? active : null);
      entries = collect();
      activeIndex = 0;
      if (typeof dialog.showModal === "function") {
        try {
          dialog.showModal();
        } catch (error) {
          dialog.setAttribute("open", "");
        }
      } else {
        dialog.setAttribute("open", "");
      }
      render();
      input.focus();
      input.select();
    }

    function closePalette() {
      if (!isOpen()) return;
      if (typeof dialog.close === "function") {
        dialog.close();
        return;
      }
      dialog.removeAttribute("open");
      afterClose();
    }

    function runEntry(entry) {
      if (!entry || typeof entry.run !== "function") return;
      // The surface being teleported to takes focus for itself, so the palette
      // must not hand it back to whatever opened the dialog.
      restoreFocusTo = null;
      closePalette();
      try {
        entry.run();
      } catch (error) {
        site.notify(
          site.lang.t("That command did not run", "呢個指令行唔到"),
          entry.title + " — " + (error && error.message ? error.message : String(error))
        );
      }
    }

    dialog.addEventListener("close", afterClose);

    dialog.addEventListener("mousedown", function (event) {
      pressTarget = event.target;
    });

    dialog.addEventListener("click", function (event) {
      // The card fills the dialog box, so a click landing on the dialog itself
      // is a click on the backdrop -- but only when the press started there
      // too, or a selection dragged out of the card would close it.
      if (event.target === dialog && pressTarget === dialog) closePalette();
      pressTarget = null;
    });

    if (openButton) {
      openButton.addEventListener("click", function () {
        openPalette(openButton);
      });
    }
    if (closeButton) {
      closeButton.addEventListener("click", function () {
        closePalette();
      });
    }

    input.addEventListener("keydown", function (event) {
      if (event.isComposing) return;
      var key = event.key;
      if (key === "Enter") {
        if (!options.length) return;
        event.preventDefault();
        runEntry(rendered[activeIndex]);
        return;
      }
      if (key !== "ArrowDown" && key !== "ArrowUp" && key !== "Home" && key !== "End") return;
      if (!options.length) return;
      event.preventDefault();
      if (key === "ArrowDown") setActive(activeIndex + 1 >= options.length ? 0 : activeIndex + 1);
      else if (key === "ArrowUp") setActive(activeIndex - 1 < 0 ? options.length - 1 : activeIndex - 1);
      else if (key === "Home") setActive(0);
      else setActive(options.length - 1);
    });

    document.addEventListener("keydown", function (event) {
      if (event.defaultPrevented || event.isComposing) return;
      if (event.key === "Escape") {
        if (!isOpen()) return;
        event.preventDefault();
        closePalette();
        return;
      }
      if (!event.ctrlKey || !event.shiftKey || event.altKey || event.metaKey) return;
      // event.code carries the chord on layouts where event.key is not Latin.
      if (event.key !== "F" && event.key !== "f" && event.code !== "KeyF") return;
      // The palette's own field keeps the chord: reopening what is already open
      // would only wipe the query the user is in the middle of typing.
      if (isOpen() && dialog.contains(event.target)) return;
      event.preventDefault();
      openPalette(document.activeElement);
    });

    // Titles and subtitles are built by their sources in the active language,
    // so a language or emoji change has to re-ask them rather than restyle the
    // strings already on screen.
    site.settings.onChange(function () {
      if (!isOpen()) return;
      entries = collect();
      render();
    });
  });
})();
