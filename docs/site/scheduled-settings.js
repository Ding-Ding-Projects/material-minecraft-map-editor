/* Scheduled settings: rules that change how this site looks and speaks at
 * particular times, and hand your own choices back afterwards.
 *
 * The one rule that shapes everything here: a schedule NEVER becomes the
 * user's stored preference. It applies through the core's override layer,
 * which sits on top of the stored value without replacing it, so when a window
 * closes the value the user actually chose comes back on its own. A scheduler
 * that wrote through the ordinary setter would quietly consume the preference
 * it was only supposed to borrow.
 *
 * Times are interpreted in this browser's own timezone, which is named on the
 * surface rather than assumed, because "18:00" means nothing without it. A
 * window whose end time is earlier than its start is read as crossing
 * midnight, which is what somebody typing 22:00-06:00 means.
 */
(function () {
  "use strict";

  var site = window.AmuletSite;
  if (!site) return;

  var RULES_KEY = "schedule.rules";
  var SCHEMA = 1;
  var el = site.el;
  var t = function (en, yue) {
    return site.lang.t(en, yue);
  };

  var DAYS = [
    { index: 0, en: "Sun", yue: "日" },
    { index: 1, en: "Mon", yue: "一" },
    { index: 2, en: "Tue", yue: "二" },
    { index: 3, en: "Wed", yue: "三" },
    { index: 4, en: "Thu", yue: "四" },
    { index: 5, en: "Fri", yue: "五" },
    { index: 6, en: "Sat", yue: "六" },
  ];

  /* Only values with a real reader are offered. Listing something the site
   * cannot actually change would be a control that does nothing. */
  var SCHEDULABLE = [
    { key: "language", en: "Language mode", yue: "語言模式",
      options: ["english", "cantonese", "bilingual"] },
    { key: "theme", en: "Theme", yue: "主題", options: ["light", "dark"] },
    { key: "density", en: "Density", yue: "密度",
      options: ["comfortable", "compact"] },
    { key: "accent", en: "Accent colour", yue: "主色", type: "color" },
    { key: "scale", en: "Text scale", yue: "字級", type: "number",
      min: 80, max: 200 },
    { key: "funnyEn", en: "Funny level (English)", yue: "搞笑程度（英文）",
      type: "number", min: 1, max: 5 },
    { key: "funnyYue", en: "Funny level (Cantonese)", yue: "搞笑程度（廣東話）",
      type: "number", min: 1, max: 5 },
    { key: "emoji", en: "Emoji in dialogs", yue: "對話框 emoji", type: "boolean" },
    { key: "narrator", en: "Narrator", yue: "旁白", type: "boolean" },
    { key: "reducedMotion", en: "Reduced motion", yue: "減少動態", type: "boolean" },
  ];

  var state = { rules: [], applied: [], editing: null, error: "" };
  var nodes = {};
  var timer = null;

  function timezone() {
    try {
      return Intl.DateTimeFormat().resolvedOptions().timeZone || "local time";
    } catch (error) {
      return "local time";
    }
  }

  /* ---------------------------------------------------------------- store */

  function load() {
    var raw = site.store.get(RULES_KEY, null);
    if (!raw || typeof raw !== "object") {
      state.rules = [];
      return;
    }
    /* A newer schema fails closed rather than being read as this one. */
    if (Number(raw.schema) > SCHEMA) {
      state.rules = [];
      state.error = t(
        "These schedules were written by a newer version of this page and are " +
          "not being applied, rather than being guessed at.",
        "呢啲時間表係新版寫嘅，唔會亂咁估，所以而家唔會套用。"
      );
      return;
    }
    state.rules = Array.isArray(raw.rules) ? raw.rules.filter(valid) : [];
  }

  function save() {
    site.store.set(RULES_KEY, { schema: SCHEMA, rules: state.rules });
  }

  function valid(rule) {
    return (
      rule &&
      typeof rule.id === "string" &&
      typeof rule.settings === "object" &&
      rule.settings !== null
    );
  }

  function nextId() {
    var n = 0;
    state.rules.forEach(function (rule) {
      var parsed = parseInt(String(rule.id).replace(/\D/g, ""), 10);
      if (parsed > n) n = parsed;
    });
    return "rule-" + (n + 1);
  }

  /* ------------------------------------------------------------ matching */

  function minutes(value) {
    if (!/^\d{2}:\d{2}$/.test(String(value || ""))) return null;
    var parts = String(value).split(":");
    var h = Number(parts[0]);
    var m = Number(parts[1]);
    if (h > 23 || m > 59) return null;
    return h * 60 + m;
  }

  function withinDates(rule, now) {
    var day = now.getFullYear() + "-" +
      String(now.getMonth() + 1).padStart(2, "0") + "-" +
      String(now.getDate()).padStart(2, "0");
    if (rule.startDate && day < rule.startDate) return false;
    if (rule.endDate && day > rule.endDate) return false;
    return true;
  }

  /* A window whose end is before its start crosses midnight; that is what
   * 22:00-06:00 means to the person typing it. Equal start and end is read as
   * a zero-length window rather than "all day", so a mistyped pair does
   * nothing instead of silently taking over the whole day. */
  function withinTime(rule, now) {
    var start = minutes(rule.startTime);
    var end = minutes(rule.endTime);
    if (start === null || end === null) return start === null && end === null;
    var at = now.getHours() * 60 + now.getMinutes();
    if (start === end) return false;
    if (start < end) return at >= start && at < end;
    return at >= start || at < end;
  }

  function withinDays(rule, now) {
    if (!rule.days || rule.days === "every") return true;
    if (!Array.isArray(rule.days) || !rule.days.length) return true;
    return rule.days.indexOf(now.getDay()) >= 0;
  }

  function matches(rule, now) {
    if (rule.enabled === false) return false;
    return withinDates(rule, now) && withinTime(rule, now) && withinDays(rule, now);
  }

  /* Precedence is documented rather than emergent: later rules in the list win,
   * key by key, so a general rule can sit above a specific one. */
  function evaluate(now) {
    var when = now || new Date();
    var winning = {};
    var applied = [];
    state.rules.forEach(function (rule) {
      if (!matches(rule, when)) return;
      applied.push(rule.id);
      Object.keys(rule.settings).forEach(function (key) {
        winning[key] = rule.settings[key];
      });
    });
    return { values: winning, applied: applied };
  }

  function apply(now) {
    var result = evaluate(now);
    var wanted = Object.keys(result.values);
    var active = Object.keys(site.settings.activeOverrides());
    active.forEach(function (key) {
      if (wanted.indexOf(key) < 0) site.settings.release(key);
    });
    wanted.forEach(function (key) {
      site.settings.override(key, result.values[key]);
    });
    var changed = state.applied.join(",") !== result.applied.join(",");
    state.applied = result.applied;
    if (changed) {
      renderList();
      if (result.applied.length) {
        site.notify(
          site.lang.emoji("🕒") + t("A schedule is applying", "時間表生效緊"),
          t(
            result.applied.length +
              " rule(s) are overriding your settings right now. Your own " +
              "choices come back when they stop.",
            "而家有 " + result.applied.length +
              " 條規則蓋住你嘅設定。完咗之後會自動還返畀你。"
          )
        );
      } else {
        site.notify(
          site.lang.emoji("🕒") + t("Schedule ended", "時間表完咗"),
          t("Your own settings are back.", "你自己嘅設定返晒嚟。")
        );
      }
    }
    return result;
  }

  function start() {
    if (timer) clearInterval(timer);
    apply();
    /* Once a minute is enough for a schedule expressed in minutes, and cheap
     * enough that nothing needs to be clever about it. */
    timer = setInterval(function () {
      apply();
    }, 30000);
  }

  /* ----------------------------------------------------------------- view */

  function styleOnce() {
    if (document.getElementById("schedule-style")) return;
    var css = [
      ".sched-rule{border:1px solid var(--outline-variant,#ccc);border-radius:12px;",
      "  padding:14px;margin:12px 0}",
      ".sched-rule[data-active=\"true\"]{border-color:var(--primary,#4d5f92);border-width:2px}",
      ".sched-days{display:flex;gap:6px;flex-wrap:wrap}",
      ".sched-day{border:1px solid var(--outline,#999);border-radius:999px;padding:4px 10px}",
      ".sched-values{display:grid;gap:8px;grid-template-columns:repeat(auto-fill,minmax(220px,1fr))}",
    ].join("");
    document.head.appendChild(el("style", { id: "schedule-style", text: css }));
  }

  function describeRule(rule) {
    var bits = [];
    if (rule.startTime && rule.endTime) {
      bits.push(rule.startTime + "–" + rule.endTime);
      if (minutes(rule.endTime) !== null &&
          minutes(rule.startTime) !== null &&
          minutes(rule.endTime) < minutes(rule.startTime)) {
        bits.push(t("(crosses midnight)", "（過咗夜晚十二點）"));
      }
    } else {
      bits.push(t("any time", "唔限時間"));
    }
    if (rule.days === "every" || !rule.days || !rule.days.length) {
      bits.push(t("every day", "日日"));
    } else {
      bits.push(
        rule.days
          .map(function (d) {
            var row = DAYS[d];
            return row ? t(row.en, row.yue) : String(d);
          })
          .join(" ")
      );
    }
    if (rule.startDate || rule.endDate) {
      bits.push(
        (rule.startDate || t("no start", "冇開始")) +
          " → " +
          (rule.endDate || t("no end", "冇完結"))
      );
    }
    return bits.join(" · ");
  }

  function renderList() {
    var host = nodes.list;
    if (!host) return;
    host.textContent = "";

    if (nodes.count) {
      nodes.count.textContent = t(
        state.rules.length + " rule(s) · " + state.applied.length +
          " applying now · times in " + timezone(),
        state.rules.length + " 條規則 · 而家 " + state.applied.length +
          " 條生效 · 時間用 " + timezone()
      );
    }

    if (state.error) {
      host.appendChild(el("p", { class: "field-error", text: state.error }));
    }

    if (!state.rules.length) {
      host.appendChild(
        el("p", {
          class: "empty-state",
          text: t(
            "No schedules yet. A schedule borrows a setting for a while and " +
              "gives it back — it never replaces what you chose.",
            "重未有時間表。時間表只係借你個設定用一陣，用完會還返，唔會取代你揀嘅嘢。"
          ),
        })
      );
      return;
    }

    state.rules.forEach(function (rule) {
      var active = state.applied.indexOf(rule.id) >= 0;
      host.appendChild(
        el(
          "div",
          { class: "sched-rule", "data-active": active ? "true" : "false" },
          el(
            "div",
            { class: "row-between" },
            el("strong", { text: rule.label || rule.id }),
            el("span", {
              class: "lock-badge",
              text: active
                ? t("applying now", "而家生效")
                : rule.enabled === false
                ? t("disabled", "停用咗")
                : t("waiting", "等緊"),
            })
          ),
          el("p", { class: "muted", text: describeRule(rule) }),
          el("p", {
            class: "muted",
            text: Object.keys(rule.settings)
              .map(function (key) {
                var spec = SCHEDULABLE.filter(function (row) {
                  return row.key === key;
                })[0];
                return (spec ? t(spec.en, spec.yue) : key) + " = " +
                  String(rule.settings[key]);
              })
              .join(" · "),
          }),
          el(
            "div",
            { class: "row-actions" },
            el("button", {
              class: "button button-text",
              type: "button",
              text: rule.enabled === false
                ? t("Enable", "啟用")
                : t("Disable", "停用"),
              onClick: function () {
                rule.enabled = rule.enabled === false;
                save();
                apply();
                renderList();
              },
            }),
            el("button", {
              class: "button button-text",
              type: "button",
              text: t("Delete", "刪除"),
              onClick: function (event) {
                site.confirmDestructive({
                  title: t("Delete this schedule", "刪除呢條規則"),
                  detail: t(
                    'Deleting "' + (rule.label || rule.id) +
                      '" cannot be undone from here, and any setting it is ' +
                      "currently overriding returns to your own value.",
                    "刪咗「" + (rule.label || rule.id) +
                      "」喺呢度撤銷唔到；佢而家蓋住嘅設定會即刻還返你自己嗰個。"
                  ),
                  anchor: event.target,
                  onConfirm: function () {
                    state.rules = state.rules.filter(function (row) {
                      return row.id !== rule.id;
                    });
                    save();
                    apply();
                    renderList();
                  },
                });
              },
            })
          )
        )
      );
    });
  }

  function renderEditor() {
    var host = nodes.editor;
    if (!host) return;
    host.textContent = "";
    var draft = {
      id: nextId(),
      label: "",
      enabled: true,
      startDate: "",
      endDate: "",
      startTime: "",
      endTime: "",
      days: "every",
      settings: {},
    };
    var error = el("p", { class: "field-error", role: "alert" });

    function field(labelText, control) {
      var id = "sched-" + Math.random().toString(36).slice(2, 8);
      control.id = id;
      return el("p", { class: "field" }, el("label", { for: id, text: labelText }), control);
    }

    var dayBoxes = [];
    var everyDay = el("input", {
      type: "checkbox",
      checked: true,
      onChange: function (e) {
        draft.days = e.target.checked ? "every" : [];
        dayBoxes.forEach(function (box) {
          box.disabled = e.target.checked;
        });
      },
    });

    var dayRow = el("div", { class: "sched-days" });
    DAYS.forEach(function (day) {
      var box = el("input", {
        type: "checkbox",
        disabled: true,
        onChange: function (e) {
          if (!Array.isArray(draft.days)) draft.days = [];
          if (e.target.checked) draft.days.push(day.index);
          else draft.days = draft.days.filter(function (d) {
            return d !== day.index;
          });
        },
      });
      dayBoxes.push(box);
      var id = "sched-day-" + day.index;
      box.id = id;
      dayRow.appendChild(
        el("span", { class: "sched-day" }, box,
          el("label", { for: id, text: t(day.en, day.yue) }))
      );
    });

    var valueHost = el("div", { class: "sched-values" });
    SCHEDULABLE.forEach(function (spec) {
      var enable = el("input", { type: "checkbox" });
      var control;
      if (spec.options) {
        control = el("select", { disabled: true });
        spec.options.forEach(function (option) {
          control.appendChild(el("option", { value: option, text: option }));
        });
      } else if (spec.type === "boolean") {
        control = el("select", { disabled: true });
        control.appendChild(el("option", { value: "true", text: t("on", "開") }));
        control.appendChild(el("option", { value: "false", text: t("off", "關") }));
      } else if (spec.type === "color") {
        control = el("input", { type: "color", value: "#4d5f92", disabled: true });
      } else {
        control = el("input", {
          type: "number",
          min: String(spec.min),
          max: String(spec.max),
          value: String(spec.min),
          disabled: true,
        });
      }
      function sync() {
        if (!enable.checked) {
          delete draft.settings[spec.key];
          return;
        }
        var raw = control.value;
        if (spec.type === "boolean") draft.settings[spec.key] = raw === "true";
        else if (spec.type === "number") draft.settings[spec.key] = Number(raw);
        else draft.settings[spec.key] = raw;
      }
      enable.addEventListener("change", function () {
        control.disabled = !enable.checked;
        sync();
      });
      control.addEventListener("change", sync);
      control.addEventListener("input", sync);
      var id = "sched-v-" + spec.key;
      enable.id = id;
      valueHost.appendChild(
        el("div", null,
          el("span", null, enable, el("label", { for: id, text: t(spec.en, spec.yue) })),
          control)
      );
    });

    host.appendChild(
      el(
        "div",
        { class: "sched-rule" },
        el("h3", { text: t("New schedule", "新時間表") }),
        field(t("Name", "名"), el("input", {
          type: "text",
          onInput: function (e) {
            draft.label = e.target.value;
          },
        })),
        field(t("Start date (optional)", "開始日期（可選）"), el("input", {
          type: "date",
          onChange: function (e) {
            draft.startDate = e.target.value;
          },
        })),
        field(t("End date (optional)", "完結日期（可選）"), el("input", {
          type: "date",
          onChange: function (e) {
            draft.endDate = e.target.value;
          },
        })),
        field(t("Start time", "開始時間"), el("input", {
          type: "time",
          onChange: function (e) {
            draft.startTime = e.target.value;
          },
        })),
        field(t("End time", "完結時間"), el("input", {
          type: "time",
          onChange: function (e) {
            draft.endTime = e.target.value;
          },
        })),
        el("p", {
          class: "muted",
          text: t(
            "Times are read in " + timezone() +
              ". An end earlier than the start crosses midnight. A start equal " +
              "to the end is a zero-length window and does nothing.",
            "時間用 " + timezone() +
              " 計。完結早過開始即係過夜。開始同完結一樣即係零長度，乜都唔會做。"
          ),
        }),
        el("p", { class: "field" },
          el("span", null, everyDay, el("label", { text: t("Every day", "日日") }))),
        dayRow,
        el("h4", { text: t("Values to borrow", "要借用嘅設定") }),
        valueHost,
        error,
        el(
          "div",
          { class: "row-actions" },
          el("button", {
            class: "button button-filled",
            type: "button",
            text: t("Add the schedule", "加入"),
            onClick: function () {
              if (!Object.keys(draft.settings).length) {
                error.textContent = t(
                  "Tick at least one value for this schedule to change.",
                  "起碼揀一個要改嘅設定。"
                );
                return;
              }
              var s = minutes(draft.startTime);
              var e2 = minutes(draft.endTime);
              if ((draft.startTime || draft.endTime) && (s === null || e2 === null)) {
                error.textContent = t(
                  "Give both a start and an end time, or neither.",
                  "開始同完結時間要一齊填，或者兩個都唔填。"
                );
                return;
              }
              if (s !== null && e2 !== null && s === e2) {
                error.textContent = t(
                  "The start and end are the same, so this window has no " +
                    "length and would never apply.",
                  "開始同完結一樣，個窗冇長度，永遠都唔會生效。"
                );
                return;
              }
              if (draft.startDate && draft.endDate &&
                  draft.startDate > draft.endDate) {
                error.textContent = t(
                  "The end date is before the start date.",
                  "完結日期早過開始日期。"
                );
                return;
              }
              state.rules.push(draft);
              save();
              recordHistory(draft);
              apply();
              renderList();
              renderEditor();
            },
          })
        )
      )
    );
  }

  function recordHistory(rule) {
    if (!site.history || typeof site.history.record !== "function") return false;
    try {
      site.history.record({
        action: "schedule-added",
        label: t("Schedule ", "時間表 ") + (rule.label || rule.id),
        detail: describeRule(rule),
      });
      return true;
    } catch (error) {
      return false;
    }
  }

  function mount() {
    var host = document.getElementById("schedule-root");
    if (!host) return;
    styleOnce();
    load();

    nodes.count = el("p", { class: "muted", role: "status" });
    nodes.list = el("div", { id: "schedule-list" });
    nodes.editor = el("div", { id: "schedule-editor" });

    host.appendChild(
      el("p", {
        class: "muted",
        text: t(
          "A schedule borrows a setting for a window of time and gives it back " +
            "afterwards. It is never written over what you chose: your own " +
            "value is still there underneath, and returns on its own.",
          "時間表只係喺一段時間內借用個設定，之後會還返。佢唔會蓋死你揀嘅嘢 —— " +
            "你自己嗰個一直喺下面，時間一到就返嚟。"
        ),
      })
    );
    host.appendChild(nodes.count);
    host.appendChild(
      el("button", {
        class: "button button-text",
        type: "button",
        id: "schedule-release",
        text: t("Give my settings back now", "而家還返我啲設定"),
        onClick: function () {
          var released = site.settings.release();
          site.notify(
            site.lang.emoji("↩️") + t("Overrides released", "已還返"),
            t(
              released.length + " setting(s) returned to your own value. A " +
                "schedule still in its window will apply again shortly.",
              "還咗 " + released.length +
                " 個設定畀你。如果條規則仲喺個時間窗入面，一陣就會再生效。"
            )
          );
          renderList();
        },
      })
    );
    host.appendChild(nodes.list);
    host.appendChild(nodes.editor);

    renderList();
    renderEditor();
    start();

    site.registerPaletteSource(function () {
      return state.rules.map(function (rule) {
        return {
          label: t("Schedule: ", "時間表：") + (rule.label || rule.id),
          hint: describeRule(rule),
          tab: "settings",
          run: function () {
            site.showTab("settings");
          },
        };
      });
    });
  }

  site.ready(mount);
  site.settings.onChange(function (key) {
    if ((key === null || key === "language" || key === "emoji") && nodes.list) {
      renderList();
    }
  });

  window.AmuletSchedule = {
    rules: function () {
      return state.rules.slice();
    },
    evaluate: evaluate,
    apply: apply,
    _matches: matches,
    _minutes: minutes,
    _set: function (rules) {
      state.rules = rules;
    },
  };
})();
