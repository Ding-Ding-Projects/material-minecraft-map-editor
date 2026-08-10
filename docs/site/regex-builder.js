/* The one bounded regex builder that every search bar on this site attaches to.
 *
 * A search field is cheap to add and a per-field builder is cheap to fork, which
 * is how two fields end up with different bounds, different flag sets, and
 * different ideas of what an invalid pattern should do. There is one
 * implementation here and every field is a caller, so the character bound, the
 * flag allowlist and the refusal to let a broken pattern widen a search hold
 * identically everywhere -- including the ones added after this was written.
 */
(function () {
  "use strict";

  var site = window.AmuletSite;
  if (!site) return;

  var el = site.el;
  var lang = site.lang;
  var MAX_PATTERN = site.MAX_PATTERN || 256;
  var SAMPLE_MAX = 512;
  var DEFAULT_SAMPLE = "Material Minecraft World Editor 0.10.0-dev";
  var SAFE_NAME = /^[a-z0-9_-]+$/i;

  var FLAGS = [
    { value: "i", en: "i - Ignore case (default)", yue: "i - 唔理大細楷（預設）" },
    { value: "im", en: "im - Ignore case, ^ and $ match each line", yue: "im - 唔理大細楷，^ 同 $ 逐行計" },
    { value: "imu", en: "imu - Ignore case, each line, full Unicode", yue: "imu - 唔理大細楷、逐行、全 Unicode" },
    { value: "", en: "No flags - case sensitive", yue: "冇 flag - 分大細楷" },
  ];

  /* Each button inserts something that actually runs. Where a construct needs
   * content to be useful, a real placeholder goes in selected, so the next
   * keystroke replaces it instead of landing beside it. */
  var TOKENS = [
    { label: "^", insert: "^", en: "Start of the text, or of each line with the m flag", yue: "文字開頭；開咗 m flag 就係每行開頭" },
    { label: "$", insert: "$", en: "End of the text, or of each line with the m flag", yue: "文字結尾；開咗 m flag 就係每行結尾" },
    { label: ".", insert: ".", en: "Any single character except a line break", yue: "任何一個字元，換行除外" },
    { label: "\\d", insert: "\\d", en: "Any digit from 0 to 9", yue: "任何一個數字，0 至 9" },
    { label: "\\w", insert: "\\w", en: "A word character: a letter, a digit, or an underscore", yue: "字詞字元：字母、數字或者底線" },
    { label: "\\s", insert: "\\s", en: "Any whitespace: a space, a tab, or a line break", yue: "任何空白：空格、tab 或者換行" },
    { label: "[abc]", insert: "[abc]", select: [1, 4], open: "[", close: "]", en: "Any one of the characters inside the brackets", yue: "括號入面任何一個字元" },
    { label: "(a|b)", insert: "(a|b)", select: [1, 4], en: "Either alternative: a or b", yue: "二揀一：a 或者 b" },
    { label: "( )", insert: "()", select: [1, 1], open: "(", close: ")", en: "A capture group; its text is listed in the capture readout below", yue: "Capture group；入面嘅文字會喺下面嘅 capture 行顯示" },
    { label: "*", insert: "*", en: "Zero or more of the item before it", yue: "前面嗰件嘢出現零次或以上" },
    { label: "+", insert: "+", en: "One or more of the item before it", yue: "前面嗰件嘢出現一次或以上" },
    { label: "?", insert: "?", en: "Zero or one of the item before it", yue: "前面嗰件嘢出現零次或者一次" },
    { label: "{n,m}", insert: "{1,3}", select: [1, 4], en: "Between n and m of the item before it; {1,3} is inserted for you to edit", yue: "前面嗰件嘢出現 n 至 m 次；會插入 {1,3} 畀你改" },
    { label: "\\b", insert: "\\b", en: "A word boundary: the edge between a word character and anything else", yue: "字詞邊界：字詞字元同其他嘢之間嗰條線" },
  ];

  var instances = [];

  function fill(template, values) {
    var out = String(template);
    for (var i = 0; i < values.length; i++) {
      out = out.split("{" + i + "}").join(String(values[i]));
    }
    return out;
  }

  /* Funny level 1 is strictly factual and 5 is at its most playful. Each
   * language picks with its own slider, so bilingual mode is not forced to one
   * voice. Only the wording moves -- an engine error is never styled. */
  function graded(en, yue) {
    return lang.t(variant(en, lang.funny("en")), variant(yue, lang.funny("yue")));
  }

  function variant(list, level) {
    var index = level <= 1 ? 0 : level <= 3 ? 1 : 2;
    return list[index] || list[list.length - 1] || "";
  }

  function element(value) {
    return value && value.nodeType === 1 ? value : null;
  }

  function knownFlags(value) {
    for (var i = 0; i < FLAGS.length; i++) {
      if (FLAGS[i].value === value) return true;
    }
    return false;
  }

  /* Plain-text containment so a search bar whose builder markup is absent still
   * filters. A missing panel must not take its search field down with it. */
  function degraded(input) {
    function query() {
      return input && typeof input.value === "string" ? input.value : "";
    }
    return {
      state: function () {
        return {
          query: query(),
          regex: false,
          flags: "i",
          valid: true,
          feedback: graded(
            ["Plain-text mode", "Plain-text mode. Your text is matched literally.", "Plain-text mode - every character is taken at face value."],
            ["純文字模式", "純文字模式，逐個字對。", "純文字模式：打乜對乜，一個字都唔會當 pattern。"]
          ),
          matcher: null,
        };
      },
      matches: function (text) {
        var needle = query();
        if (!needle) return true;
        return String(text == null ? "" : text).toLowerCase().indexOf(needle.toLowerCase()) !== -1;
      },
      refresh: function () {},
    };
  }

  function attach(options) {
    var config = options || {};
    var name = String(config.name || "");
    var input = element(config.input);
    var container = SAFE_NAME.test(name)
      ? document.querySelector('[data-regex-controls="' + name + '"]')
      : null;
    if (!container || !input) return degraded(input);

    var panel = element(config.panel);
    var openButton = element(config.openButton);
    var onChange = typeof config.onChange === "function" ? config.onChange : null;

    var saved = site.store.get("regex." + name, null) || {};
    var startRegex = saved.regex === true;
    var startFlags = knownFlags(saved.flags) ? saved.flags : "i";

    var ids = {
      toggle: "regex-" + name + "-toggle",
      pattern: "regex-" + name + "-pattern",
      flags: "regex-" + name + "-flags",
      sample: "regex-" + name + "-sample",
      feedback: "regex-" + name + "-feedback",
      captures: "regex-" + name + "-captures",
    };

    var toggle = el("input", { type: "checkbox", id: ids.toggle, class: "regex-toggle" });
    toggle.checked = startRegex;
    var toggleLabel = el("label", { class: "regex-caption", for: ids.toggle });

    var patternLabel = el("label", { class: "regex-caption", for: ids.pattern });
    var pattern = el("input", {
      type: "text",
      id: ids.pattern,
      class: "regex-input",
      maxlength: String(MAX_PATTERN),
      spellcheck: "false",
      autocomplete: "off",
      autocapitalize: "off",
      autocorrect: "off",
      "aria-describedby": ids.feedback,
    });
    pattern.value = typeof input.value === "string" ? input.value : "";

    var flagsLabel = el("label", { class: "regex-caption", for: ids.flags });
    var flagSelect = el("select", { id: ids.flags, class: "regex-flags" });
    var flagOptions = FLAGS.map(function (choice) {
      var option = el("option", { value: choice.value });
      flagSelect.appendChild(option);
      return { node: option, choice: choice };
    });
    flagSelect.value = startFlags;

    var insertRow = el("div", { class: "regex-inserts", role: "group" });
    var insertButtons = TOKENS.map(function (token) {
      var button = el("button", { type: "button", class: "regex-insert", text: token.label });
      button.addEventListener("click", function () {
        insertToken(token);
      });
      insertRow.appendChild(button);
      return { node: button, token: token };
    });

    var sampleLabel = el("label", { class: "regex-caption", for: ids.sample });
    var sample = el("input", {
      type: "text",
      id: ids.sample,
      class: "regex-input",
      maxlength: String(SAMPLE_MAX),
      spellcheck: "false",
      autocomplete: "off",
    });
    sample.value = config.sample == null ? DEFAULT_SAMPLE : String(config.sample).slice(0, SAMPLE_MAX);

    var feedbackNode = el("p", { class: "regex-feedback", id: ids.feedback });
    var capturesNode = el("p", { class: "regex-captures", id: ids.captures });

    while (container.firstChild) container.removeChild(container.firstChild);
    container.appendChild(el("div", { class: "regex-row regex-mode" }, toggle, toggleLabel));
    container.appendChild(el("div", { class: "regex-row" }, patternLabel, pattern));
    container.appendChild(el("div", { class: "regex-row" }, flagsLabel, flagSelect));
    container.appendChild(insertRow);
    container.appendChild(el("div", { class: "regex-row" }, sampleLabel, sample));
    container.appendChild(el("div", { class: "regex-status", role: "status" }, feedbackNode, capturesNode));

    var current = {
      query: pattern.value,
      regex: startRegex,
      flags: startFlags,
      valid: true,
      feedback: "",
      matcher: null,
    };

    function publicState() {
      return {
        query: current.query,
        regex: current.regex,
        flags: current.flags,
        valid: current.valid,
        feedback: current.feedback,
        matcher: current.matcher,
      };
    }

    function evaluate(silent) {
      var query = pattern.value;
      var useRegex = toggle.checked;
      var flags = flagSelect.value;
      var built = null;
      var valid = true;
      var message = "";
      try {
        built = site.matcher(query, useRegex, flags);
      } catch (error) {
        built = null;
        valid = false;
        // The engine's own words, unstyled and untranslated: a reader has to be
        // able to search for exactly this text.
        message = error && error.message ? String(error.message) : String(error);
      }
      if (valid) {
        message = useRegex
          ? graded(
              ["Valid regular expression", "Valid regular expression. It compiled without complaint.", "Valid regular expression - the engine took it without a fuss."],
              ["正則表達式有效", "正則表達式有效，順利 compile 咗。", "正則表達式有效 - engine 收貨，冇彈返出嚟嘈。"]
            )
          : graded(
              ["Plain-text mode", "Plain-text mode. Your text is matched literally.", "Plain-text mode - every character is taken at face value."],
              ["純文字模式", "純文字模式，逐個字對。", "純文字模式：打乜對乜，一個字都唔會當 pattern。"]
            );
      }
      current = { query: query, regex: useRegex, flags: flags, valid: valid, feedback: message, matcher: built };
      renderStatus();
      if (!silent && onChange) {
        try {
          onChange(publicState());
        } catch (error) {
          /* a caller that throws must not leave its own search field wedged */
        }
      }
    }

    function renderStatus() {
      var glyph = current.valid ? (current.regex ? "✅" : "🔤") : "⚠️";
      feedbackNode.textContent = lang.emoji(glyph) + current.feedback;
      capturesNode.textContent = captureReadout();
      pattern.setAttribute("aria-invalid", current.valid ? "false" : "true");
    }

    function captureReadout() {
      if (!current.valid || !current.matcher) {
        return lang.t(
          "No capture readout: there is nothing to run until the pattern compiles.",
          "冇 capture 顯示：個 pattern compile 唔到，冇嘢可以跑。"
        );
      }
      current.matcher.lastIndex = 0;
      var found = current.matcher.exec(sample.value);
      if (!found) {
        return graded(
          ["The sample text does not match.", "The sample text does not match.", "The sample text does not match - nothing in it answered to that."],
          ["樣本文字唔 match。", "樣本文字唔 match。", "樣本文字唔 match - 入面冇嘢應到你。"]
        );
      }
      var head = fill(
        lang.t("The sample matches at index {0}.", "樣本喺第 {0} 個字位開始 match。"),
        [found.index]
      );
      if (found.length <= 1) {
        return head + " " + lang.t("This pattern has no capture groups.", "呢個 pattern 冇 capture group。");
      }
      var parts = [];
      for (var i = 1; i < found.length; i++) {
        parts.push(
          found[i] === undefined
            ? fill(lang.t("Group {0}: did not take part", "第 {0} 組：冇參與"), [i])
            : fill(lang.t("Group {0}: “{1}”", "第 {0} 組：“{1}”"), [i, found[i]])
        );
      }
      return head + " " + parts.join("   ");
    }

    function insertToken(token) {
      var value = pattern.value;
      var start = typeof pattern.selectionStart === "number" ? pattern.selectionStart : value.length;
      var end = typeof pattern.selectionEnd === "number" ? pattern.selectionEnd : start;
      var selected = value.slice(start, end);
      var text;
      var from;
      var to;
      if (token.open && selected) {
        text = token.open + selected + token.close;
        from = start + token.open.length;
        to = from + selected.length;
      } else {
        text = token.insert;
        from = start + (token.select ? token.select[0] : text.length);
        to = start + (token.select ? token.select[1] : text.length);
      }
      var next = value.slice(0, start) + text + value.slice(end);
      if (next.length > MAX_PATTERN) {
        site.notify(
          lang.t("Pattern bound reached", "Pattern 到咗上限"),
          fill(
            lang.t(
              "Nothing was inserted: a pattern is limited to {0} characters.",
              "冇插入到嘢：一個 pattern 最多 {0} 個字元。"
            ),
            [MAX_PATTERN]
          )
        );
        return;
      }
      // Reaching for a construct is an unambiguous request for regex, so opting
      // in here saves a user pressing a button that would otherwise be searched
      // for literally. The checkbox flips in plain sight and the choice sticks.
      if (!toggle.checked) {
        toggle.checked = true;
        persistMode();
      }
      pattern.value = next;
      mirror(pattern, input);
      pattern.focus();
      if (pattern.setSelectionRange) pattern.setSelectionRange(from, to);
      evaluate();
    }

    function mirror(from, to) {
      if (to.value !== from.value) to.value = from.value;
    }

    function persistMode() {
      site.store.set("regex." + name, { regex: toggle.checked, flags: flagSelect.value });
    }

    function applyCopy() {
      toggleLabel.textContent = lang.t(
        "Use regular expression - plain text stays the default",
        "用正則表達式 - 預設仍然係純文字"
      );
      patternLabel.textContent = fill(
        lang.t("Pattern - up to {0} characters", "Pattern - 最多 {0} 個字元"),
        [MAX_PATTERN]
      );
      pattern.setAttribute("placeholder", lang.t("Type or build a pattern", "打或者砌一個 pattern"));
      flagsLabel.textContent = lang.t("Flags");
      flagOptions.forEach(function (entry) {
        entry.node.textContent = lang.t(entry.choice.en, entry.choice.yue);
      });
      insertRow.setAttribute(
        "aria-label",
        lang.t(
          "Insert a construct - using one turns regular expressions on",
          "插入 pattern 零件 - 撳咗就會開返正則表達式"
        )
      );
      insertButtons.forEach(function (entry) {
        var explain = lang.t(entry.token.en, entry.token.yue);
        entry.node.setAttribute("title", explain);
        entry.node.setAttribute(
          "aria-label",
          fill(lang.t("Insert {0} - {1}", "插入 {0} - {1}"), [entry.token.label, explain])
        );
      });
      sampleLabel.textContent = fill(
        lang.t("Sample text - up to {0} characters", "樣本文字 - 最多 {0} 個字元"),
        [SAMPLE_MAX]
      );
      sample.setAttribute(
        "placeholder",
        lang.t("Text to test the pattern against", "攞嚟試個 pattern 嘅文字")
      );
    }

    input.addEventListener("input", function () {
      // The visible field and the pattern are two views of one query. Leaving
      // the field inert while regex is on would make a live-looking search box
      // that ignores typing.
      mirror(input, pattern);
      evaluate();
    });

    pattern.addEventListener("input", function () {
      mirror(pattern, input);
      evaluate();
    });

    toggle.addEventListener("change", function () {
      if (toggle.checked) mirror(input, pattern);
      else mirror(pattern, input);
      persistMode();
      evaluate();
    });

    flagSelect.addEventListener("change", function () {
      persistMode();
      evaluate();
    });

    // The sample decides only what the readout reports, never what the search
    // returns, so callers are not asked to re-filter for it.
    sample.addEventListener("input", renderStatus);

    function syncExpanded() {
      openButton.setAttribute("aria-expanded", panel.open ? "true" : "false");
    }

    if (openButton && panel) {
      syncExpanded();
      openButton.addEventListener("click", function (event) {
        // The button sits inside a <label>, whose default action would pull
        // focus back to the search input the moment the panel opens.
        event.preventDefault();
        panel.open = !panel.open;
        // The toggle event arrives a task later; the button must not describe
        // the previous state in the meantime.
        syncExpanded();
        if (panel.open) toggle.focus();
        else if (input.focus) input.focus();
      });
      // Keeps the button truthful when the panel is opened from its summary.
      panel.addEventListener("toggle", syncExpanded);
    }

    applyCopy();
    // Silent: attach() has not returned yet, so a caller's onChange would run
    // before it holds the object it is meant to filter with.
    evaluate(true);

    var instance = {
      state: publicState,
      matches: function (text) {
        if (!current.valid || !current.matcher) return false;
        current.matcher.lastIndex = 0;
        return current.matcher.test(String(text == null ? "" : text));
      },
      /* Re-reads the controls and repaints. Deliberately does not call
       * onChange: a caller may call this from inside its own onChange. */
      refresh: function () {
        applyCopy();
        evaluate(true);
      },
    };

    instances = instances.filter(function (entry) {
      return entry.name !== name;
    });
    instances.push({ name: name, instance: instance });
    return instance;
  }

  site.settings.onChange(function (key) {
    if (key !== null && key !== "language" && key !== "emoji" && key !== "funnyEn" && key !== "funnyYue") return;
    instances.forEach(function (entry) {
      try {
        entry.instance.refresh();
      } catch (error) {
        /* one field failing to re-language must not silence the others */
      }
    });
  });

  site.regex = { attach: attach };
})();
