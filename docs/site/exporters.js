/* The one export surface every list on this site borrows.
 *
 * Nine writers live here rather than one per panel, because an export written
 * beside the list it exports is an export that quietly disagrees with its
 * neighbours: one escapes a comma and one does not, one states its encoding and
 * one leaves the reader guessing, one drops a nested field without saying so.
 * A file that leaves this page has to be readable by something other than the
 * page that wrote it, so every writer here states its schema, its encoding and
 * its line endings inside the file itself.
 *
 * The rule that shapes the rest of this file: a format is never offered as
 * though it were faithful when it is not. Losses are computed from the actual
 * rows, named before the export runs, and written into the exported file so the
 * warning survives the download.
 *
 * Public surface:
 *   AmuletSite.exporters.formats(shape)          -> descriptors, losses included
 *   AmuletSite.exporters.export(rows, id, meta)  -> { ok, text, filename, ... }
 *   AmuletSite.exporters.register(id, source)    -> a panel offers its own rows
 *   AmuletSite.exporters.mount(options)          -> the shared "Export..." button
 *
 * A source is { title(), shape(), rows(), total(), filter() }. rows() returns
 * what the user is looking at right now -- the caller's active search and
 * filter, not the whole collection -- and filter() describes why.
 */
(function () {
  "use strict";

  var site = window.AmuletSite;
  if (!site) return;

  var el = site.el;
  var lang = site.lang;
  var settings = site.settings;

  var SCHEMA = "mmwe.export/1";
  var GENERATOR = "Material Minecraft World Editor site exporter";
  var NL = "\n";
  var NEWLINE_LABEL = "LF (U+000A)";
  var PREVIEW_CHARS = 2000;
  var MAX_DEPTH = 8;

  function t(en, yue) {
    return lang.t(en, yue);
  }

  // ------------------------------------------------------------------ values
  function classify(value) {
    if (value === null || value === undefined) return "null";
    var kind = typeof value;
    if (kind === "string") return "string";
    if (kind === "boolean") return "boolean";
    if (kind === "number") return isFinite(value) ? "number" : "nonfinite";
    if (kind === "function") return "function";
    if (kind === "bigint" || kind === "symbol") return "exotic";
    if (value instanceof Date) return "date";
    if (Array.isArray(value)) return "array";
    return "object";
  }

  /** Collects a loss once, however many rows trip it, with its own count. */
  function noteBook() {
    var order = [];
    var byKey = {};
    return {
      add: function (key, en, yue) {
        if (byKey[key]) {
          byKey[key].count += 1;
          return;
        }
        byKey[key] = { key: key, en: en, yue: yue, count: 1 };
        order.push(key);
      },
      list: function () {
        return order.map(function (key) {
          return byKey[key];
        });
      },
    };
  }

  /**
   * Everything a writer sees is a string, a finite number, a boolean, null, an
   * array or a plain object. Anything else is converted here once, in the open,
   * so no writer has to guess and no conversion happens twice with two answers.
   */
  function normaliseValue(value, depth, seen, notes, path) {
    var kind = classify(value);
    if (kind === "string" || kind === "boolean" || kind === "number" || kind === "null") {
      return kind === "null" ? null : value;
    }
    if (kind === "date") {
      notes.add(
        "date:" + path,
        "Field " + path + " holds a Date; it is written as an ISO-8601 string in UTC.",
        "欄位 " + path + " 係 Date；會寫成 UTC 嘅 ISO-8601 字串。"
      );
      var iso = null;
      try {
        iso = isNaN(value.getTime()) ? null : value.toISOString();
      } catch (error) {
        iso = null;
      }
      return iso;
    }
    if (kind === "nonfinite") {
      notes.add(
        "nonfinite:" + path,
        "Field " + path + " holds " + String(value) + ", which no text format carries as a number; it is written as text.",
        "欄位 " + path + " 係 " + String(value) + "，冇一種文字格式當佢係數字，所以會寫成文字。"
      );
      return String(value);
    }
    if (kind === "exotic") {
      notes.add(
        "exotic:" + path,
        "Field " + path + " holds a " + typeof value + ", which is written as text.",
        "欄位 " + path + " 係 " + typeof value + "，會寫成文字。"
      );
      return String(value);
    }
    if (kind === "function") {
      notes.add(
        "function:" + path,
        "Field " + path + " holds a function, which no file format can carry; it is written as null.",
        "欄位 " + path + " 係一個 function，冇檔案格式載得到，會寫成 null。"
      );
      return null;
    }
    if (depth >= MAX_DEPTH) {
      notes.add(
        "depth:" + path,
        "Field " + path + " nests deeper than " + MAX_DEPTH + " levels; the remainder is written as the text below.",
        "欄位 " + path + " 巢狀深過 " + MAX_DEPTH + " 層，餘下嘅部分會寫成下面嗰段文字。"
      );
      return "[nested beyond depth " + MAX_DEPTH + "]";
    }
    if (seen.indexOf(value) !== -1) {
      notes.add(
        "circular:" + path,
        "Field " + path + " refers back to a value that already contains it; the repeat is written as text.",
        "欄位 " + path + " 指返去一個已經包住佢嘅值，重複嗰段會寫成文字。"
      );
      return "[circular reference]";
    }
    seen.push(value);
    var out;
    if (kind === "array") {
      out = value.map(function (item, index) {
        return normaliseValue(item, depth + 1, seen, notes, path + "[" + index + "]");
      });
    } else {
      out = {};
      Object.keys(value).forEach(function (key) {
        out[key] = normaliseValue(value[key], depth + 1, seen, notes, path + "." + key);
      });
    }
    seen.pop();
    return out;
  }

  /**
   * Projects rows onto the shape's declared field order. A key the shape never
   * declared is appended rather than dropped: an export that silently loses a
   * column is the exact failure this whole file exists to prevent.
   */
  function normaliseRows(rows, shape, notes) {
    var declared = [];
    var labels = {};
    (shape && Array.isArray(shape.fields) ? shape.fields : []).forEach(function (field) {
      var name = typeof field === "string" ? field : field && field.name;
      if (!name || declared.indexOf(name) !== -1) return;
      declared.push(String(name));
      if (field && field.label) labels[String(name)] = field.label;
    });

    var columns = declared.slice();
    var extras = [];
    var prepared = [];

    (Array.isArray(rows) ? rows : []).forEach(function (row, index) {
      var source = row;
      if (classify(row) !== "object") {
        notes.add(
          "wrapped",
          "Some rows are single values rather than records; each is written under the field name \"value\".",
          "有啲列係單一個值而唔係一筆記錄，會寫入「value」呢個欄位。"
        );
        source = { value: row };
      }
      Object.keys(source).forEach(function (key) {
        if (columns.indexOf(key) === -1) {
          columns.push(key);
          if (declared.length) extras.push(key);
        }
      });
      var clean = {};
      columns.forEach(function (key) {
        if (Object.prototype.hasOwnProperty.call(source, key)) {
          clean[key] = normaliseValue(source[key], 0, [], notes, "row[" + index + "]." + key);
        }
      });
      // A key first seen on a later row must still land in the earlier rows'
      // column order, so the object is rebuilt once the column list is final.
      prepared.push(clean);
    });

    if (extras.length) {
      notes.add(
        "extras",
        extras.length + " field" + (extras.length === 1 ? " was" : "s were") +
          " not declared by the panel but are present in the data, so they are exported too: " +
          joinNames(extras) + ".",
        "有 " + extras.length + " 個欄位個面板冇宣告過，但係數據入面有，所以一樣會匯出：" +
          joinNames(extras) + "。"
      );
    }

    var ordered = prepared.map(function (row) {
      var out = {};
      columns.forEach(function (key) {
        if (Object.prototype.hasOwnProperty.call(row, key)) out[key] = row[key];
      });
      return out;
    });

    return { rows: ordered, columns: columns, labels: labels };
  }

  // ------------------------------------------------------------- inspection
  function scalarKind(kind) {
    return kind === "string" || kind === "number" || kind === "boolean";
  }

  /**
   * Two notions of "nested" live here on purpose. A row-and-column file
   * flattens an array as readily as an object, while TOML writes an array of
   * scalars natively and falls back to JSON text only for the rest. Collapsing
   * the two would make one format declare a loss it never actually takes, which
   * is as misleading as taking one without declaring it.
   */
  function inspect(rows, columns) {
    var flags = {
      nested: [],
      tomlNested: [],
      nulls: [],
      newlines: [],
      tabs: [],
      control: [],
      formulaic: 0,
      empties: 0,
      typed: false,
      timestamps: false,
    };
    function remember(list, column) {
      if (list.indexOf(column) === -1) list.push(column);
    }
    rows.forEach(function (row) {
      columns.forEach(function (column) {
        var value = Object.prototype.hasOwnProperty.call(row, column) ? row[column] : null;
        var kind = classify(value);
        if (kind === "array" || kind === "object") {
          remember(flags.nested, column);
          var native =
            kind === "array" &&
            value.every(function (item) {
              return scalarKind(classify(item));
            });
          if (!native) remember(flags.tomlNested, column);
          return;
        }
        if (kind === "null") {
          remember(flags.nulls, column);
          return;
        }
        if (kind !== "string") {
          flags.typed = true;
          return;
        }
        if (value === "") flags.empties += 1;
        if (/^\d{4}-\d{2}-\d{2}T/.test(value)) flags.timestamps = true;
        if (/[\n\r]/.test(value)) remember(flags.newlines, column);
        if (value.indexOf("\t") !== -1) remember(flags.tabs, column);
        if (/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(value)) remember(flags.control, column);
        if (/^[=+\-@]/.test(value)) flags.formulaic += 1;
      });
    });
    return flags;
  }

  function joinNames(list) {
    return list.join(", ");
  }

  /** Per-format losses, stated in both languages and counted from real rows. */
  function lossesFor(formatId, flags, rowCount) {
    var out = [];
    function add(en, yue) {
      out.push({ en: en, yue: yue });
    }
    var nested = flags.nested.length;
    var nulls = flags.nulls.length;

    if (formatId === "csv" || formatId === "tsv") {
      if (nested) {
        add(
          nested + " field" + (nested === 1 ? "" : "s") + " hold nested values (" + joinNames(flags.nested) +
            "); a row-and-column file has no nesting, so each is written as JSON text inside its cell.",
          "有 " + nested + " 個欄位係巢狀值（" + joinNames(flags.nested) +
            "）；行列式檔案冇巢狀結構，所以每個都會喺格入面寫成 JSON 文字。"
        );
      }
      if (nulls) {
        add(
          "An empty cell cannot say whether the value was empty text or absent; " + nulls +
            " field" + (nulls === 1 ? " holds" : "s hold") + " no value in at least one row (" + joinNames(flags.nulls) + ").",
          "空格分唔到係空字串定係冇值；有 " + nulls + " 個欄位喺至少一列冇值（" + joinNames(flags.nulls) + "）。"
        );
      }
      if (formatId === "tsv" && (flags.tabs.length || flags.newlines.length)) {
        add(
          "Tab-separated files have no quoting, so tabs, newlines and backslashes are written as \\t, \\n and \\\\ and must be unescaped when read back.",
          "Tab 分隔檔案冇引號機制，所以 tab、換行同反斜線會寫成 \\t、\\n 同 \\\\，讀返嘅時候要解返。"
        );
      }
      if (formatId === "csv" && flags.formulaic) {
        add(
          flags.formulaic + " value" + (flags.formulaic === 1 ? "" : "s") + " begin with = + - or @; they are data, and a spreadsheet that evaluates formulas on open will misread them.",
          "有 " + flags.formulaic + " 個值係 = + - 或者 @ 開頭；佢哋係數據，開檔就自動計公式嘅試算表會讀錯。"
        );
      }
      add(
        "Every value is written as text; a reader has to decide for itself which columns are numbers or dates.",
        "所有值都寫成文字；邊啲欄位係數字或者日期，要讀嗰邊自己決定。"
      );
    }

    if (formatId === "toml") {
      if (nulls) {
        add(
          "TOML has no null, so a key with no value is omitted from that row entirely; " + nulls +
            " field" + (nulls === 1 ? " is" : "s are") + " affected (" + joinNames(flags.nulls) + ").",
          "TOML 冇 null，所以冇值嘅 key 會喺嗰列直接略去；受影響嘅有 " + nulls + " 個欄位（" + joinNames(flags.nulls) + "）。"
        );
      }
      if (nested) {
        add(
          nested + " field" + (nested === 1 ? "" : "s") + " nest beyond a flat table (" + joinNames(flags.nested) +
            "); each is written as JSON text rather than a sub-table, so row tables stay uniform.",
          "有 " + nested + " 個欄位巢狀過一層平表（" + joinNames(flags.nested) +
            "）；每個都會寫成 JSON 文字而唔係子表，令每列嘅表結構保持一致。"
        );
      }
      add(
        "Timestamps are written as quoted ISO-8601 strings rather than TOML datetimes, so no value is reinterpreted by a parser.",
        "時間戳會寫成加引號嘅 ISO-8601 字串而唔係 TOML datetime，咁就冇任何值會俾 parser 重新詮釋。"
      );
    }

    if (formatId === "xml" && flags.control.length) {
      add(
        "XML 1.0 cannot carry control characters; " + flags.control.length + " field" +
          (flags.control.length === 1 ? "" : "s") + " contain them (" + joinNames(flags.control) +
          ") and they are written as \\uXXXX escape text.",
        "XML 1.0 載唔到控制字元；有 " + flags.control.length + " 個欄位含有（" + joinNames(flags.control) +
          "），會寫成 \\uXXXX 逃逸文字。"
      );
    }

    if (formatId === "md") {
      add(
        "Markdown is a presentation format: reading these " + rowCount + " rows back into records means parsing the document, not loading it.",
        "Markdown 係展示格式：想將呢 " + rowCount + " 列讀返做記錄，要 parse 份文件，唔係直接載入。"
      );
      if (flags.newlines.length) {
        add(
          "Line breaks inside " + flags.newlines.length + " field" + (flags.newlines.length === 1 ? "" : "s") +
            " (" + joinNames(flags.newlines) + ") become <br> inside a table cell.",
          "有 " + flags.newlines.length + " 個欄位入面嘅換行（" + joinNames(flags.newlines) + "）喺表格格仔入面會變成 <br>。"
        );
      }
    }

    if (formatId === "html") {
      add(
        "HTML is a presentation format: reading these " + rowCount + " rows back into records means parsing the document, not loading it.",
        "HTML 係展示格式：想將呢 " + rowCount + " 列讀返做記錄，要 parse 份文件，唔係直接載入。"
      );
    }

    return out;
  }

  // ------------------------------------------------------------ text escapes
  function cellText(value) {
    var kind = classify(value);
    if (kind === "null") return "";
    if (kind === "array" || kind === "object") return JSON.stringify(value);
    return String(value);
  }

  function oneLine(value) {
    return cellText(value).replace(/\s*[\r\n]+\s*/g, " / ");
  }

  function csvCell(text) {
    var raw = String(text);
    var risky =
      /[",\n\r]/.test(raw) ||
      /^[\s#]/.test(raw) ||
      /\s$/.test(raw) ||
      /^[=+\-@]/.test(raw);
    return risky ? '"' + raw.split('"').join('""') + '"' : raw;
  }

  function tsvCell(text) {
    return String(text)
      .split("\\").join("\\\\")
      .split("\t").join("\\t")
      .split("\r").join("\\r")
      .split("\n").join("\\n");
  }

  function escapeControl(text, prefix) {
    return String(text).replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, function (ch) {
      return prefix + ("000" + ch.charCodeAt(0).toString(16)).slice(-4);
    });
  }

  function xmlText(text) {
    return escapeControl(
      String(text).split("&").join("&amp;").split("<").join("&lt;").split(">").join("&gt;"),
      "\\u"
    );
  }

  function xmlAttr(text) {
    return xmlText(text).split('"').join("&quot;");
  }

  function htmlText(text) {
    return String(text)
      .split("&").join("&amp;")
      .split("<").join("&lt;")
      .split(">").join("&gt;")
      .split('"').join("&quot;");
  }

  function mdCell(text) {
    return String(text)
      .split("\\").join("\\\\")
      .split("|").join("\\|")
      .replace(/\r\n|\r|\n/g, "<br>");
  }

  function tomlString(text) {
    var out = String(text)
      .split("\\").join("\\\\")
      .split('"').join('\\"')
      .split("\n").join("\\n")
      .split("\r").join("\\r")
      .split("\t").join("\\t");
    return '"' + escapeControl(out, "\\u") + '"';
  }

  function tomlKey(name) {
    return /^[A-Za-z0-9_-]+$/.test(name) ? name : tomlString(name);
  }

  function yamlKey(name) {
    return /^[A-Za-z_][A-Za-z0-9_.-]*$/.test(name) ? name : JSON.stringify(name);
  }

  function yamlScalar(value) {
    var kind = classify(value);
    if (kind === "null") return "null";
    if (kind === "boolean") return value ? "true" : "false";
    if (kind === "number") return String(value);
    // YAML 1.2 is a superset of JSON, so a JSON string literal is a valid
    // double-quoted scalar -- and quoting always keeps "no", "on" and "1.0"
    // from being read back as something other than the text that was written.
    return JSON.stringify(String(value));
  }

  function indent(depth) {
    var pad = "";
    for (var i = 0; i < depth; i++) pad += "  ";
    return pad;
  }

  function yamlBlock(value, depth) {
    var kind = classify(value);
    var pad = indent(depth);
    if (kind === "array") {
      if (!value.length) return " []";
      return value
        .map(function (item) {
          return NL + pad + "-" + yamlBlock(item, depth + 1);
        })
        .join("");
    }
    if (kind === "object") {
      var keys = Object.keys(value);
      if (!keys.length) return " {}";
      return keys
        .map(function (key) {
          return NL + pad + yamlKey(key) + ":" + yamlBlock(value[key], depth + 1);
        })
        .join("");
    }
    return " " + yamlScalar(value);
  }

  function tomlValue(value) {
    var kind = classify(value);
    if (kind === "null") return null;
    if (kind === "boolean") return value ? "true" : "false";
    if (kind === "number") return String(value);
    if (kind === "array") {
      var scalar = value.every(function (item) {
        var k = classify(item);
        return k === "string" || k === "number" || k === "boolean";
      });
      if (scalar) {
        return (
          "[" +
          value
            .map(function (item) {
              return classify(item) === "string" ? tomlString(item) : String(item);
            })
            .join(", ") +
          "]"
        );
      }
      return tomlString(JSON.stringify(value));
    }
    if (kind === "object") return tomlString(JSON.stringify(value));
    return tomlString(String(value));
  }

  function tomlPairs(source) {
    var out = "";
    Object.keys(source).forEach(function (key) {
      var written = tomlValue(source[key]);
      if (written === null) return; // TOML has no null; the loss is declared above
      out += tomlKey(key) + " = " + written + NL;
    });
    return out;
  }

  // ------------------------------------------------------------------- meta
  function flattenMeta(source, prefix) {
    var out = [];
    Object.keys(source).forEach(function (key) {
      var value = source[key];
      var path = prefix ? prefix + "." + key : key;
      var kind = classify(value);
      if (kind === "object") {
        out = out.concat(flattenMeta(value, path));
      } else if (kind === "array") {
        if (!value.length) {
          out.push([path, ""]);
        } else {
          value.forEach(function (item, index) {
            var label = path + "." + (index + 1);
            if (classify(item) === "object") out = out.concat(flattenMeta(item, label));
            else out.push([label, cellText(item)]);
          });
        }
      } else {
        out.push([path, cellText(value)]);
      }
    });
    return out;
  }

  function commentHeader(meta, marker) {
    return (
      flattenMeta(meta, "")
        .map(function (pair) {
          return marker + " " + pair[0] + ": " + oneLine(pair[1]);
        })
        .join(NL) + NL
    );
  }

  // -------------------------------------------------------------- xml writer
  function xmlValueNode(name, value, depth) {
    var pad = indent(depth);
    var kind = classify(value);
    var attr = ' name="' + xmlAttr(name) + '"';
    if (kind === "null") return pad + "<field" + attr + ' type="null"/>' + NL;
    if (kind === "array") {
      var items = value
        .map(function (item, index) {
          return xmlItemNode(index + 1, item, depth + 1);
        })
        .join("");
      return pad + "<field" + attr + ' type="array">' + NL + items + pad + "</field>" + NL;
    }
    if (kind === "object") {
      var keys = Object.keys(value)
        .map(function (key) {
          return xmlValueNode(key, value[key], depth + 1);
        })
        .join("");
      return pad + "<field" + attr + ' type="object">' + NL + keys + pad + "</field>" + NL;
    }
    return pad + "<field" + attr + ' type="' + kind + '">' + xmlText(String(value)) + "</field>" + NL;
  }

  function xmlItemNode(index, value, depth) {
    var pad = indent(depth);
    var kind = classify(value);
    var attr = ' index="' + index + '"';
    if (kind === "null") return pad + "<item" + attr + ' type="null"/>' + NL;
    if (kind === "array" || kind === "object") {
      var inner =
        kind === "array"
          ? value
              .map(function (item, i) {
                return xmlItemNode(i + 1, item, depth + 1);
              })
              .join("")
          : Object.keys(value)
              .map(function (key) {
                return xmlValueNode(key, value[key], depth + 1);
              })
              .join("");
      return pad + "<item" + attr + ' type="' + kind + '">' + NL + inner + pad + "</item>" + NL;
    }
    return pad + "<item" + attr + ' type="' + kind + '">' + xmlText(String(value)) + "</item>" + NL;
  }

  // ---------------------------------------------------------------- writers
  function writeJson(ctx) {
    return JSON.stringify({ $schema: SCHEMA, meta: ctx.meta, rows: ctx.rows }, null, 2) + NL;
  }

  function writeJsonl(ctx) {
    var head = { $schema: SCHEMA, $meta: true };
    Object.keys(ctx.meta).forEach(function (key) {
      head[key] = ctx.meta[key];
    });
    head.$note = "Every line after this one is exactly one record.";
    var lines = [JSON.stringify(head)];
    ctx.rows.forEach(function (row) {
      lines.push(JSON.stringify(row));
    });
    return lines.join(NL) + NL;
  }

  function writeYaml(ctx) {
    var out = "# " + SCHEMA + NL;
    out += "# Encoding: UTF-8. Line endings: " + NEWLINE_LABEL + "." + NL;
    out += "meta:" + yamlBlock(ctx.meta, 1) + NL;
    out += "rows:" + (ctx.rows.length ? yamlBlock(ctx.rows, 1) : " []") + NL;
    return out;
  }

  function writeToml(ctx) {
    var out = "# " + SCHEMA + NL;
    out += "# Encoding: UTF-8. Line endings: " + NEWLINE_LABEL + "." + NL + NL;
    out += "[meta]" + NL;
    var scalars = {};
    var tables = {};
    Object.keys(ctx.meta).forEach(function (key) {
      if (classify(ctx.meta[key]) === "object") tables[key] = ctx.meta[key];
      else scalars[key] = ctx.meta[key];
    });
    out += tomlPairs(scalars);
    Object.keys(tables).forEach(function (key) {
      out += NL + "[meta." + tomlKey(key) + "]" + NL + tomlPairs(tables[key]);
    });
    ctx.rows.forEach(function (row) {
      out += NL + "[[rows]]" + NL + tomlPairs(row);
    });
    return out;
  }

  function writeXml(ctx) {
    var out = '<?xml version="1.0" encoding="UTF-8"?>' + NL;
    out +=
      "<export schema=\"" + xmlAttr(SCHEMA) + "\" encoding=\"UTF-8\" newline=\"LF\">" + NL;
    out += "  <meta>" + NL;
    Object.keys(ctx.meta).forEach(function (key) {
      out += xmlValueNode(key, ctx.meta[key], 2);
    });
    out += "  </meta>" + NL;
    out += '  <rows count="' + ctx.rows.length + '">' + NL;
    ctx.rows.forEach(function (row, index) {
      out += '    <row index="' + (index + 1) + '">' + NL;
      Object.keys(row).forEach(function (key) {
        out += xmlValueNode(key, row[key], 3);
      });
      out += "    </row>" + NL;
    });
    out += "  </rows>" + NL + "</export>" + NL;
    return out;
  }

  function writeDelimited(ctx, separator, escape) {
    var out = commentHeader(ctx.meta, "#");
    out += "# Every line above starts with # and is metadata, not data." + NL;
    out += ctx.columns.map(escape).join(separator) + NL;
    ctx.rows.forEach(function (row) {
      out +=
        ctx.columns
          .map(function (column) {
            return escape(cellText(Object.prototype.hasOwnProperty.call(row, column) ? row[column] : null));
          })
          .join(separator) + NL;
    });
    return out;
  }

  function writeCsv(ctx) {
    return writeDelimited(ctx, ",", csvCell);
  }

  function writeTsv(ctx) {
    return writeDelimited(ctx, "\t", tsvCell);
  }

  function writeMarkdown(ctx) {
    var out = "# " + ctx.meta.title + NL + NL;
    flattenMeta(ctx.meta, "").forEach(function (pair) {
      out += "- **" + pair[0] + "**: " + mdCell(oneLine(pair[1])) + NL;
    });
    out += NL;
    if (!ctx.rows.length) {
      out += "_No row matched the filter in force when this file was written._" + NL;
      return out;
    }
    if (ctx.prose) {
      ctx.rows.forEach(function (row, index) {
        var keys = Object.keys(row);
        var headKey = keys[0];
        out += "## " + (index + 1) + ". " + mdCell(oneLine(row[headKey])) + NL + NL;
        keys.slice(1).forEach(function (key) {
          out += "**" + key + "**" + NL + NL + cellText(row[key]) + NL + NL;
        });
      });
      return out;
    }
    out += "| " + ctx.columns.map(mdCell).join(" | ") + " |" + NL;
    out +=
      "| " +
      ctx.columns
        .map(function () {
          return "---";
        })
        .join(" | ") +
      " |" + NL;
    ctx.rows.forEach(function (row) {
      out +=
        "| " +
        ctx.columns
          .map(function (column) {
            return mdCell(cellText(Object.prototype.hasOwnProperty.call(row, column) ? row[column] : null));
          })
          .join(" | ") +
        " |" + NL;
    });
    return out;
  }

  var HTML_STYLE = [
    "body{font-family:system-ui,'Segoe UI','PingFang HK','Noto Sans CJK HK',sans-serif;",
    "margin:32px;line-height:1.5;color:#1a1b20;background:#faf8ff}",
    "h1{font-size:1.5rem}dl.meta{display:grid;grid-template-columns:max-content 1fr;gap:4px 16px;",
    "font-size:.85rem;background:#efedf4;padding:16px;border-radius:12px}",
    "dt{font-weight:700}dd{margin:0}",
    "table{border-collapse:collapse;width:100%;margin-top:24px;font-size:.9rem}",
    "th,td{border:1px solid #c4c6d0;padding:8px 10px;text-align:left;vertical-align:top;white-space:pre-wrap}",
    "th{background:#e9e7ef}",
    "article{border-top:1px solid #c4c6d0;padding-top:16px;margin-top:24px}",
    "@media(prefers-color-scheme:dark){body{color:#e4e1e9;background:#111318}",
    "dl.meta{background:#1d1f25}th{background:#2a2831}th,td,article{border-color:#44464f}}",
  ].join("");

  function writeHtml(ctx) {
    var out = "<!doctype html>" + NL + '<html lang="en">' + NL + "<head>" + NL;
    out += '<meta charset="utf-8">' + NL;
    out += '<meta name="viewport" content="width=device-width,initial-scale=1">' + NL;
    out += "<title>" + htmlText(ctx.meta.title) + "</title>" + NL;
    out += "<style>" + HTML_STYLE + "</style>" + NL;
    out += "</head>" + NL + "<body>" + NL;
    out += "<h1>" + htmlText(ctx.meta.title) + "</h1>" + NL;
    out += '<dl class="meta">' + NL;
    flattenMeta(ctx.meta, "").forEach(function (pair) {
      out += "<dt>" + htmlText(pair[0]) + "</dt><dd>" + htmlText(oneLine(pair[1])) + "</dd>" + NL;
    });
    out += "</dl>" + NL;

    if (!ctx.rows.length) {
      out += "<p>No row matched the filter in force when this file was written.</p>" + NL;
    } else if (ctx.prose) {
      ctx.rows.forEach(function (row, index) {
        var keys = Object.keys(row);
        out += "<article>" + NL + "<h2>" + (index + 1) + ". " + htmlText(oneLine(row[keys[0]])) + "</h2>" + NL;
        keys.slice(1).forEach(function (key) {
          out += "<h3>" + htmlText(key) + "</h3>" + NL;
          out += "<p style=\"white-space:pre-wrap\">" + htmlText(cellText(row[key])) + "</p>" + NL;
        });
        out += "</article>" + NL;
      });
    } else {
      out += "<table>" + NL + "<thead><tr>";
      ctx.columns.forEach(function (column) {
        out += "<th scope=\"col\">" + htmlText(column) + "</th>";
      });
      out += "</tr></thead>" + NL + "<tbody>" + NL;
      ctx.rows.forEach(function (row) {
        out += "<tr>";
        ctx.columns.forEach(function (column) {
          out +=
            "<td>" +
            htmlText(cellText(Object.prototype.hasOwnProperty.call(row, column) ? row[column] : null)) +
            "</td>";
        });
        out += "</tr>" + NL;
      });
      out += "</tbody>" + NL + "</table>" + NL;
    }
    out += "</body>" + NL + "</html>" + NL;
    return out;
  }

  // ---------------------------------------------------------------- catalogue
  var FORMATS = [
    {
      id: "json",
      label: "JSON",
      extension: "json",
      mime: "application/json",
      family: "structured",
      reimportable: true,
      write: writeJson,
      en: "One object with its metadata and every record. Loads straight back into any language.",
      yue: "一個 object，入面有元資料同每一筆記錄。任何語言都可以直接載返入去。",
    },
    {
      id: "jsonl",
      label: "JSONL / NDJSON",
      extension: "jsonl",
      mime: "application/x-ndjson",
      family: "structured",
      reimportable: true,
      write: writeJsonl,
      en: "A metadata line, then exactly one record per line. Streams and appends without reparsing the file.",
      yue: "第一行係元資料，之後每行一筆記錄。可以串流同續寫，唔使成份檔案重新 parse。",
    },
    {
      id: "yaml",
      label: "YAML",
      extension: "yaml",
      mime: "application/yaml",
      family: "structured",
      reimportable: true,
      write: writeYaml,
      en: "Indented and commented, with every string quoted so nothing is read back as a different type.",
      yue: "有縮排同註解，所有字串都加引號，讀返嘅時候唔會變成第二種型別。",
    },
    {
      id: "toml",
      label: "TOML",
      extension: "toml",
      mime: "application/toml",
      family: "structured",
      reimportable: true,
      write: writeToml,
      en: "A [meta] table and one [[rows]] table per record. Flat by design, which costs it nested values and nulls.",
      yue: "一個 [meta] 表，每筆記錄一個 [[rows]] 表。設計上係平嘅，所以載唔到巢狀值同 null。",
    },
    {
      id: "xml",
      label: "XML",
      extension: "xml",
      mime: "application/xml",
      family: "structured",
      reimportable: true,
      write: writeXml,
      en: "Uniform <field name= type=> elements, so nesting and types survive whatever a field is called.",
      yue: "統一用 <field name= type=> 元素，無論欄位叫咩名，巢狀同型別都保得住。",
    },
    {
      id: "csv",
      label: "CSV",
      extension: "csv",
      mime: "text/csv",
      family: "tabular",
      reimportable: true,
      write: writeCsv,
      en: "RFC 4180 rows and columns, with the metadata on # comment lines above the header row.",
      yue: "RFC 4180 行列格式，元資料寫喺標題行上面嘅 # 註解行。",
    },
    {
      id: "tsv",
      label: "TSV",
      extension: "tsv",
      mime: "text/tab-separated-values",
      family: "tabular",
      reimportable: true,
      write: writeTsv,
      en: "Tab separated, with tabs and newlines escaped rather than quoted. Pastes cleanly into a spreadsheet.",
      yue: "用 tab 分隔，tab 同換行用逃逸字元而唔係引號。貼落試算表好乾淨。",
    },
    {
      id: "md",
      label: "Markdown",
      extension: "md",
      mime: "text/markdown",
      family: "prose",
      reimportable: false,
      write: writeMarkdown,
      en: "For reading and pasting into an issue or a document. Presentation only, not a record format.",
      yue: "俾人睇，或者貼落 issue 同文件。純展示，唔係記錄格式。",
    },
    {
      id: "html",
      label: "HTML",
      extension: "html",
      mime: "text/html",
      family: "prose",
      reimportable: false,
      write: writeHtml,
      en: "A standalone page with its styling inside it. No network, no remote asset, opens anywhere.",
      yue: "一版獨立網頁，樣式包埋喺入面。唔使網絡、冇外部資源，去邊度都開得。",
    },
  ];

  var FORMAT_BY_ID = {};
  FORMATS.forEach(function (format) {
    FORMAT_BY_ID[format.id] = format;
  });

  var RECOMMENDED = {
    tabular: ["csv", "tsv", "json", "jsonl"],
    records: ["json", "jsonl", "yaml", "toml", "xml"],
    prose: ["md", "html", "json", "yaml"],
  };

  function shapeKind(shape) {
    var kind = shape && shape.kind;
    return kind === "tabular" || kind === "prose" ? kind : "records";
  }

  /**
   * Descriptors for one datum. Losses are real when rows are supplied, so the
   * picker can name them before anything is written rather than after.
   */
  function formatsFor(shape) {
    var record = shape || {};
    var rows = Array.isArray(record.rows) ? record.rows : [];
    var notes = noteBook();
    var normalised = normaliseRows(rows, record, notes);
    var flags = inspect(normalised.rows, normalised.columns);
    var kind = shapeKind(record);
    var preferred = RECOMMENDED[kind] || [];

    return FORMATS.map(function (format) {
      var losses = lossesFor(format.id, flags, normalised.rows.length);
      return {
        id: format.id,
        label: format.label,
        extension: format.extension,
        mime: format.mime,
        family: format.family,
        reimportable: format.reimportable,
        recommended: preferred.indexOf(format.id) !== -1,
        summary: t(format.en, format.yue),
        lossy: losses.length > 0,
        losses: losses.map(function (loss) {
          return { en: loss.en, yue: loss.yue, text: t(loss.en, loss.yue) };
        }),
      };
    }).sort(function (a, b) {
      if (a.recommended !== b.recommended) return a.recommended ? -1 : 1;
      return preferred.indexOf(a.id) - preferred.indexOf(b.id) ||
        FORMATS.indexOf(FORMAT_BY_ID[a.id]) - FORMATS.indexOf(FORMAT_BY_ID[b.id]);
    });
  }

  // ------------------------------------------------------------- the export
  function slug(value) {
    var out = String(value == null ? "export" : value)
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "");
    return out || "export";
  }

  function stamp(date) {
    function pad(value) {
      return (value < 10 ? "0" : "") + value;
    }
    return (
      date.getFullYear() +
      pad(date.getMonth() + 1) +
      pad(date.getDate()) +
      "-" +
      pad(date.getHours()) +
      pad(date.getMinutes()) +
      pad(date.getSeconds())
    );
  }

  function byteLength(text) {
    try {
      if (typeof Blob === "function") return new Blob([text]).size;
    } catch (error) {
      /* fall through to the arithmetic estimate below */
    }
    // UTF-8 byte count without a Blob: surrogate pairs count as four bytes.
    var bytes = 0;
    for (var i = 0; i < text.length; i++) {
      var code = text.charCodeAt(i);
      if (code < 0x80) bytes += 1;
      else if (code < 0x800) bytes += 2;
      else if (code >= 0xd800 && code <= 0xdbff) {
        bytes += 4;
        i += 1;
      } else bytes += 3;
    }
    return bytes;
  }

  function humanBytes(bytes) {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(2) + " MB";
  }

  function filterBlock(filter) {
    var extra = (filter && filter.description) || "";
    if (!filter || !filter.query) {
      return {
        mode: extra ? "filter only" : "none",
        query: "",
        flags: "",
        description: extra || "No search or filter was active.",
      };
    }
    return {
      mode: filter.regex ? "regular expression" : "plain text",
      query: String(filter.query),
      flags: filter.regex ? String(filter.flags || "i") : "",
      description: extra,
    };
  }

  function buildMeta(options) {
    var meta = {
      schema: SCHEMA,
      generator: GENERATOR,
      generatedAt: options.at.toISOString(),
      encoding: "UTF-8",
      newline: NEWLINE_LABEL,
      format: options.format.id,
      reimportable: options.format.reimportable,
      dataset: options.dataset,
      title: options.title,
      // The language the surrounding page was in when this ran. Every value
      // above and below is written in English and is identical in every mode.
      pageLanguage: lang.mode(),
      rowsExported: options.rows.length,
      rowsAvailable: options.total,
      range: options.range,
      filter: filterBlock(options.filter),
      fields: options.columns,
    };
    if (options.notes.length) meta.notes = options.notes;
    if (options.extra && classify(options.extra) === "object") meta.source = options.extra;
    return meta;
  }

  function failure(en, yue) {
    return { ok: false, error: t(en, yue), errorEnglish: en };
  }

  /**
   * rows   -- exactly what the caller's filter left visible
   * format -- a format id, or a descriptor carrying one
   * meta   -- { dataset, title, shape, total, filter, range, source, deliver }
   */
  function runExport(rows, format, meta) {
    var id = typeof format === "string" ? format : format && format.id;
    var def = FORMAT_BY_ID[id];
    if (!def) {
      return failure(
        "No writer is registered for the format \"" + String(id) + "\", so nothing was written.",
        "「" + String(id) + "」呢個格式冇對應嘅寫入器，所以乜都冇寫。"
      );
    }
    var options = meta || {};
    var shape = options.shape || {};
    var list = Array.isArray(rows) ? rows : [];
    if (!list.length) {
      return failure(
        "Nothing matches the filter in force, so there is nothing to export.",
        "冇嘢符合而家嘅篩選，所以冇嘢可以匯出。"
      );
    }

    var notes = noteBook();
    var normalised = normaliseRows(list, shape, notes);
    if (!normalised.columns.length) {
      return failure(
        "These " + list.length + " rows carry no fields, so no file format can represent them.",
        "呢 " + list.length + " 列冇任何欄位，所以冇檔案格式表達得到。"
      );
    }
    var flags = inspect(normalised.rows, normalised.columns);
    var losses = lossesFor(def.id, flags, normalised.rows.length);
    var conversions = notes.list();

    var at = new Date();
    var total = typeof options.total === "number" ? options.total : list.length;
    var built = buildMeta({
      at: at,
      format: def,
      dataset: options.dataset || shape.id || "export",
      title: options.title || options.dataset || "Export",
      rows: normalised.rows,
      columns: normalised.columns,
      total: total,
      range: options.range || normalised.rows.length + " of " + total + " rows",
      filter: options.filter,
      extra: options.source,
      notes: conversions
        .map(function (note) {
          return note.en;
        })
        .concat(
          losses.map(function (loss) {
            return loss.en;
          })
        ),
    });

    var text;
    try {
      text = def.write({
        meta: built,
        rows: normalised.rows,
        columns: normalised.columns,
        prose: shapeKind(shape) === "prose",
      });
    } catch (error) {
      var reason = (error && error.message) || String(error);
      return failure(
        "The " + def.label + " writer failed and nothing was written: " + reason,
        def.label + " 寫入器出錯，乜都冇寫低：" + reason
      );
    }

    var result = {
      ok: true,
      format: def.id,
      label: def.label,
      mime: def.mime,
      text: text,
      bytes: byteLength(text),
      rowCount: normalised.rows.length,
      total: total,
      columns: normalised.columns,
      meta: built,
      losses: losses.map(function (loss) {
        return { en: loss.en, yue: loss.yue, text: t(loss.en, loss.yue) };
      }),
      conversions: conversions,
      filename:
        "mmwe-" + slug(built.dataset) + "-" + stamp(at) + "." + def.extension,
      delivered: "none",
    };

    var deliver = options.deliver === undefined ? "download" : options.deliver;
    if (deliver === "download") {
      var sent = download(result);
      result.delivered = sent.ok ? "download" : "none";
      if (!sent.ok) {
        result.deliveryError = sent.error;
        result.deliveryErrorEnglish = sent.errorEnglish;
      } else {
        recordExport(result, "download");
      }
    } else if (deliver === "clipboard") {
      result.delivered = "clipboard-pending";
      copyText(result.text).then(
        function () {
          recordExport(result, "clipboard");
        },
        function () {
          /* the caller reports the refusal; nothing is recorded that did not happen */
        }
      );
    }
    return result;
  }

  // ------------------------------------------------------------- delivery
  function download(result) {
    var anchor;
    try {
      anchor = document.createElement("a");
    } catch (error) {
      return failure(
        "This browser refused to build a download link, so nothing was saved.",
        "呢個瀏覽器唔肯整下載連結，所以乜都冇儲低。"
      );
    }
    if (!("download" in anchor)) {
      return failure(
        "This browser does not support the download attribute, so the file cannot be saved from the page. Copy it instead.",
        "呢個瀏覽器唔支援 download 屬性，喺頁面度儲唔到檔。改用複製。"
      );
    }

    var url = null;
    var revoke = false;
    try {
      if (typeof URL !== "undefined" && typeof URL.createObjectURL === "function" && typeof Blob === "function") {
        // charset is stated in the type as well as in the file, because a
        // browser that guesses the encoding of a downloaded file guesses wrong.
        url = URL.createObjectURL(new Blob([result.text], { type: result.mime + ";charset=utf-8" }));
        revoke = true;
      }
    } catch (error) {
      url = null;
    }
    if (!url) {
      try {
        url = "data:" + result.mime + ";charset=utf-8," + encodeURIComponent(result.text);
      } catch (error) {
        return failure(
          "The file could not be turned into a downloadable link, so nothing was saved.",
          "份檔轉唔到做下載連結，所以乜都冇儲低。"
        );
      }
    }

    anchor.href = url;
    anchor.download = result.filename;
    anchor.rel = "noopener";
    anchor.style.position = "fixed";
    anchor.style.left = "-9999px";
    document.body.appendChild(anchor);
    var thrown = null;
    try {
      anchor.click();
    } catch (error) {
      thrown = error;
    }
    if (anchor.parentNode) anchor.parentNode.removeChild(anchor);
    if (revoke) {
      // Revoking in the same tick can cancel the download that was just asked
      // for, so the handle is released on the next one instead of leaking.
      setTimeout(function () {
        try {
          URL.revokeObjectURL(url);
        } catch (error) {
          /* an already-released handle is not a failure worth reporting */
        }
      }, 60000);
    }
    if (thrown) {
      return failure(
        "The browser refused the download: " + ((thrown && thrown.message) || String(thrown)),
        "瀏覽器拒絕咗下載：" + ((thrown && thrown.message) || String(thrown))
      );
    }
    return { ok: true };
  }

  /** file:// previews and older browsers can refuse the async clipboard. */
  function legacyCopy(text) {
    var returnTo = document.activeElement;
    var field = el("textarea", {
      tabindex: "-1",
      readonly: true,
      "aria-hidden": "true",
    });
    field.value = text;
    field.style.position = "fixed";
    field.style.top = "-1000px";
    field.style.opacity = "0";
    document.body.appendChild(field);
    var copied = false;
    try {
      field.select();
      copied = document.execCommand("copy") === true;
    } catch (error) {
      copied = false;
    }
    document.body.removeChild(field);
    if (returnTo && typeof returnTo.focus === "function") returnTo.focus();
    return copied;
  }

  function copyText(text) {
    return new Promise(function (resolve, reject) {
      var clipboard = navigator.clipboard;
      if (clipboard && typeof clipboard.writeText === "function") {
        clipboard.writeText(text).then(resolve, function (error) {
          if (legacyCopy(text)) resolve();
          else reject(new Error((error && error.message) || "the clipboard refused the write"));
        });
        return;
      }
      if (legacyCopy(text)) resolve();
      else reject(new Error("this browser exposes no clipboard write"));
    });
  }

  // -------------------------------------------------------------- history
  function recordExport(result, route) {
    var history = site.history;
    if (!history || typeof history.record !== "function") return false;
    var label =
      "Exported " + result.rowCount + " of " + result.total + " " + result.meta.dataset +
      " rows as " + result.label;
    var detail =
      result.filename + " · " + humanBytes(result.bytes) + " · " + result.meta.range +
      " · filter: " + (result.meta.filter.query || "none") +
      " · delivered by " + route +
      (result.losses.length ? " · " + result.losses.length + " stated losses" : "");
    var entry = {
      action: "exported",
      kind: "export",
      dataset: result.meta.dataset,
      title: label,
      label: label,
      summary: detail,
      detail: detail,
      format: result.format,
      rows: result.rowCount,
      bytes: result.bytes,
      filename: result.filename,
      at: Date.now(),
    };
    try {
      history.record(entry);
      return true;
    } catch (error) {
      // A history that wants positional arguments should still get the event
      // rather than lose it to a signature guess made in the wrong file.
      try {
        history.record("exported", label, detail);
        return true;
      } catch (second) {
        return false;
      }
    }
  }

  // ----------------------------------------------------------------- style
  var STYLE_ID = "exporters-style";
  var PANEL_CSS = [
    ".exporter-panel{position:fixed;z-index:60;width:min(420px,calc(100vw - 24px));",
    "display:flex;flex-direction:column;gap:12px;padding:16px;box-sizing:border-box;",
    "background:var(--surface-bright);color:var(--on-surface);border:1px solid var(--outline-variant);",
    "border-radius:var(--r-md,16px);box-shadow:var(--shadow-3);overflow:auto}",
    ".exporter-panel[hidden]{display:none}",
    ".exporter-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}",
    ".exporter-head h2{font-size:1rem;margin:0}",
    ".exporter-range{margin:0;font-size:.8rem;color:var(--secondary)}",
    ".exporter-formats{border:0;margin:0;padding:0;display:grid;gap:2px}",
    ".exporter-formats legend{font-size:.78rem;font-weight:700;color:var(--secondary);padding:0 0 6px}",
    ".exporter-choice{display:grid;grid-template-columns:auto 1fr;gap:2px 10px;align-items:start;",
    "padding:8px 10px;border-radius:10px;cursor:pointer}",
    ".exporter-choice:hover{background:var(--surface-container)}",
    ".exporter-choice input{margin:0;width:20px;height:20px;min-height:0;accent-color:var(--primary);grid-row:1/3}",
    ".exporter-choice-name{font-weight:650;font-size:.9rem}",
    ".exporter-choice-note{font-size:.76rem;color:var(--secondary)}",
    ".exporter-tag{font-size:.68rem;font-weight:700;text-transform:uppercase;letter-spacing:.04em;",
    "border-radius:999px;padding:1px 7px;margin-left:6px;background:var(--primary-container);color:var(--on-primary-container)}",
    '.exporter-tag[data-kind="lossy"]{background:#ffdad6;color:#410002}',
    '.dark .exporter-tag[data-kind="lossy"]{background:#93000a;color:#ffdad6}',
    ".exporter-loss{margin:0;font-size:.78rem;border-radius:10px;padding:10px 12px;",
    "background:var(--surface-container);color:var(--on-surface)}",
    '.exporter-loss[data-state="lossy"]{background:#ffdad6;color:#410002}',
    '.dark .exporter-loss[data-state="lossy"]{background:#5c0006;color:#ffdad6}',
    ".exporter-loss ul{margin:6px 0 0;padding-left:18px}",
    ".exporter-preview>summary{font-size:.78rem;cursor:pointer;color:var(--secondary)}",
    ".exporter-preview pre{margin:8px 0 0;max-height:180px;overflow:auto;font-size:.72rem;",
    "background:var(--surface-container);padding:10px;border-radius:10px;white-space:pre;",
    "font-family:'Cascadia Mono',Consolas,ui-monospace,monospace}",
    ".exporter-actions{display:flex;gap:8px;flex-wrap:wrap}",
    ".exporter-status{margin:0;font-size:.78rem;color:var(--secondary)}",
    '.exporter-status[data-state="error"]{color:#8c1d18;font-weight:700}',
    '.dark .exporter-status[data-state="error"]{color:#ffb4ab}',
    ".exporter-panel :focus-visible{outline:3px solid var(--primary);outline-offset:2px}",
    ".exporter-panel [disabled]{opacity:.62;cursor:not-allowed}",
    // No entrance animation is declared anywhere above, so there is nothing for
    // a reduced-motion rule to switch off: the panel simply appears.
  ].join("");

  function installStyle() {
    if (document.getElementById(STYLE_ID)) return;
    var style = el("style", { id: STYLE_ID });
    style.textContent = PANEL_CSS;
    (document.head || document.documentElement).appendChild(style);
  }

  // ------------------------------------------------------------- the control
  var seq = 0;

  function asText(value) {
    if (typeof value === "function") return String(value());
    return String(value == null ? "" : value);
  }

  function mount(options) {
    var config = options || {};
    var id = String(config.id || "export");
    var source = config.source || SOURCES[id];
    if (!source || typeof source.rows !== "function") return null;

    var host = typeof config.mountTo === "function" ? config.mountTo() : config.mountTo;
    if (!host || !host.appendChild) return null;

    installStyle();
    seq += 1;
    var uid = "exporter-" + slug(id) + "-" + seq;

    var button = el("button", {
      type: "button",
      class: config.buttonClass || "button button-outlined exporter-open",
      id: uid + "-open",
      "aria-haspopup": "dialog",
      "aria-expanded": "false",
      "aria-controls": uid + "-panel",
    });

    var titleNode = el("h2", { id: uid + "-title" });
    var closeButton = el("button", {
      class: "icon-button",
      type: "button",
      text: "×",
    });
    var rangeNode = el("p", { class: "exporter-range", id: uid + "-range" });
    var legend = el("legend");
    var group = el("fieldset", { class: "exporter-formats" }, legend);
    var lossNode = el("p", {
      class: "exporter-loss",
      id: uid + "-loss",
      role: "status",
      "aria-live": "polite",
    });
    var previewSummary = el("summary");
    // Focusable so a keyboard can scroll it, and named so the focus stop says
    // what it landed on rather than announcing a wall of unlabelled text.
    var previewPre = el("pre", { tabindex: "0", role: "region" });
    var preview = el("details", { class: "exporter-preview" }, previewSummary, previewPre);
    var downloadButton = el("button", { class: "button button-filled", type: "button" });
    var copyButton = el("button", { class: "button button-outlined", type: "button" });
    var statusNode = el("p", { class: "exporter-status", role: "status", "aria-live": "polite" });

    var panel = el(
      "div",
      {
        class: "exporter-panel",
        id: uid + "-panel",
        role: "dialog",
        "aria-modal": "false",
        "aria-labelledby": uid + "-title",
        hidden: true,
      },
      el("div", { class: "exporter-head" }, titleNode, closeButton),
      rangeNode,
      group,
      lossNode,
      preview,
      el("div", { class: "exporter-actions" }, downloadButton, copyButton),
      statusNode
    );

    var choices = [];
    var chosen = String(site.store.get("export.format." + id, "") || "");
    var snapshot = null;
    var open = false;

    function readSource() {
      var rows;
      var shape;
      try {
        rows = source.rows() || [];
        shape = (typeof source.shape === "function" ? source.shape() : source.shape) || {};
      } catch (error) {
        return {
          rows: [],
          shape: {},
          total: 0,
          filter: null,
          title: asText(config.title || id),
          broken: (error && error.message) || String(error),
        };
      }
      var total = rows.length;
      if (typeof source.total === "function") {
        try {
          total = Number(source.total());
        } catch (error) {
          total = rows.length;
        }
      }
      var filter = null;
      if (typeof source.filter === "function") {
        try {
          filter = source.filter();
        } catch (error) {
          filter = null;
        }
      }
      return {
        rows: rows,
        shape: shape,
        total: isFinite(total) ? total : rows.length,
        filter: filter,
        title: typeof source.title === "function" ? source.title() : asText(config.title || id),
        broken: null,
      };
    }

    function rangeSentence(state) {
      var scope = state.rows.length + " / " + state.total;
      var extra = (state.filter && state.filter.description) || "";
      var tail = extra
        ? " " + t("Also filtered by " + extra + ".", "另外仲按 " + extra + " 篩緊。")
        : "";
      if (!state.filter || !state.filter.query) {
        return extra
          ? t(
              scope + " rows." + tail + " The export covers exactly what is on screen.",
              scope + " 列。" + tail + "匯出嘅就係畫面上見到嗰啲。"
            )
          : t(
              scope + " rows. No search or filter is active, so this is the whole collection.",
              scope + " 列。冇搜尋亦冇篩選，所以係全部。"
            );
      }
      var mode = state.filter.regex
        ? t("regular expression, flags " + (state.filter.flags || "i"), "正則表達式，flags " + (state.filter.flags || "i"))
        : t("plain text", "純文字");
      return t(
        scope + " rows match “" + state.filter.query + "” (" + mode + ")." + tail +
          " The export covers exactly what is on screen.",
        scope + " 列符合“" + state.filter.query + "”（" + mode + "）。" + tail + "匯出嘅就係畫面上見到嗰啲。"
      );
    }

    function buildChoices(descriptors) {
      choices.forEach(function (choice) {
        if (choice.node.parentNode) choice.node.parentNode.removeChild(choice.node);
      });
      choices = [];
      descriptors.forEach(function (descriptor) {
        var inputId = uid + "-format-" + descriptor.id;
        var noteId = inputId + "-note";
        var input = el("input", {
          type: "radio",
          name: uid + "-format",
          id: inputId,
          value: descriptor.id,
          "aria-describedby": noteId,
        });
        var name = el("span", { class: "exporter-choice-name" });
        name.appendChild(document.createTextNode(descriptor.label));
        if (descriptor.recommended) {
          name.appendChild(
            el("span", {
              class: "exporter-tag",
              "data-kind": "fit",
              text: t("Best fit", "最啱"),
            })
          );
        }
        if (descriptor.lossy) {
          name.appendChild(
            el("span", {
              class: "exporter-tag",
              "data-kind": "lossy",
              text: t("Changes the data", "會改變數據"),
            })
          );
        }
        var note = el("span", {
          class: "exporter-choice-note",
          id: noteId,
          text:
            descriptor.summary +
            " " +
            (descriptor.reimportable
              ? t("Reads back into records.", "可以讀返做記錄。")
              : t("Presentation only.", "純展示。")),
        });
        var label = el("label", { class: "exporter-choice", for: inputId }, input, name, note);
        input.addEventListener("change", function () {
          if (!input.checked) return;
          chosen = descriptor.id;
          site.store.set("export.format." + id, chosen);
          repaintSelection();
        });
        group.appendChild(label);
        choices.push({ node: label, input: input, descriptor: descriptor });
      });
    }

    function selected() {
      for (var i = 0; i < choices.length; i++) {
        if (choices[i].input.checked) return choices[i].descriptor;
      }
      return choices.length ? choices[0].descriptor : null;
    }

    function setStatus(text, isError) {
      statusNode.textContent = text;
      if (isError) statusNode.setAttribute("data-state", "error");
      else statusNode.removeAttribute("data-state");
    }

    function repaintSelection() {
      var descriptor = selected();
      if (!descriptor || !snapshot) return;
      lossNode.replaceChildren();
      if (descriptor.losses.length) {
        lossNode.setAttribute("data-state", "lossy");
        lossNode.appendChild(
          document.createTextNode(
            t(
              descriptor.label + " cannot carry this data unchanged. Before you export, here is exactly what moves:",
              descriptor.label + " 載唔到原封不動嘅呢啲數據。匯出之前，以下就係會變嘅嘢："
            )
          )
        );
        var list = el("ul");
        descriptor.losses.forEach(function (loss) {
          list.appendChild(el("li", { text: loss.text }));
        });
        lossNode.appendChild(list);
      } else {
        lossNode.removeAttribute("data-state");
        lossNode.textContent = t(
          descriptor.label + " carries every field of every row exactly as it stands. Nothing is dropped or reshaped.",
          descriptor.label + " 會原原本本載住每一列嘅每一個欄位。冇嘢會漏，亦冇嘢會變形。"
        );
      }

      var built = runExport(snapshot.rows, descriptor.id, {
        dataset: id,
        title: snapshot.title,
        shape: snapshot.shape,
        total: snapshot.total,
        filter: snapshot.filter,
        range: rangeSentenceEnglish(snapshot),
        deliver: "none",
      });

      if (!built.ok) {
        previewSummary.textContent = t("Preview unavailable", "冇得預覽");
        previewPre.textContent = built.error;
        downloadButton.disabled = true;
        copyButton.disabled = true;
        downloadButton.textContent = t("Download", "下載");
        copyButton.textContent = t("Copy", "複製");
        setStatus(built.error, true);
        return;
      }

      downloadButton.disabled = false;
      copyButton.disabled = false;
      downloadButton.textContent = t(
        "Download " + built.filename,
        "下載 " + built.filename
      );
      copyButton.textContent = t("Copy to clipboard", "複製到剪貼板");
      previewSummary.textContent = t(
        "Preview the first " + Math.min(PREVIEW_CHARS, built.text.length) + " characters of " +
          humanBytes(built.bytes),
        "預覽 " + humanBytes(built.bytes) + " 入面頭 " + Math.min(PREVIEW_CHARS, built.text.length) + " 個字元"
      );
      previewPre.setAttribute(
        "aria-label",
        t("Preview of " + built.filename, built.filename + " 嘅預覽")
      );
      previewPre.textContent =
        built.text.slice(0, PREVIEW_CHARS) +
        (built.text.length > PREVIEW_CHARS ? NL + "..." : "");
      setStatus(
        t(
          built.rowCount + " rows, " + built.columns.length + " fields, " + humanBytes(built.bytes) +
            ", UTF-8, LF line endings, schema " + SCHEMA + ".",
          built.rowCount + " 列、" + built.columns.length + " 個欄位、" + humanBytes(built.bytes) +
            "、UTF-8、LF 換行、schema " + SCHEMA + "。"
        ),
        false
      );
    }

    // The file records the range in English so a reader outside this page can
    // read it; the panel above says the same thing in the page's language.
    function rangeSentenceEnglish(state) {
      var scope = state.rows.length + " of " + state.total + " rows";
      var extra = (state.filter && state.filter.description) || "";
      var tail = extra ? " Also filtered by " + extra + "." : "";
      if (!state.filter || !state.filter.query) {
        return extra ? scope + "." + tail : scope + "; no search or filter was active.";
      }
      return (
        scope +
        " matching “" + state.filter.query + "” as " +
        (state.filter.regex ? "a regular expression with flags " + (state.filter.flags || "i") : "plain text") +
        "." + tail
      );
    }

    /* The button alone. Building the panel serializes the whole export once for
     * its preview, which is the right price on open and the wrong one on load
     * for every mounted list at once. */
    function labelOnly() {
      snapshot = readSource();
      button.textContent = t("Export…", "匯出…");
      button.setAttribute("aria-label", t("Export " + snapshot.title, "匯出" + snapshot.title));
    }

    function refresh() {
      snapshot = readSource();
      titleNode.textContent = t("Export " + snapshot.title, "匯出" + snapshot.title);
      button.textContent = t("Export…", "匯出…");
      button.setAttribute(
        "aria-label",
        t("Export " + snapshot.title, "匯出" + snapshot.title)
      );
      closeButton.setAttribute("aria-label", t("Close the export panel", "關閉匯出面板"));
      legend.textContent = t("File format", "檔案格式");
      rangeNode.textContent = rangeSentence(snapshot);

      if (snapshot.broken) {
        buildChoices([]);
        lossNode.setAttribute("data-state", "lossy");
        lossNode.textContent = t(
          "This panel could not hand over its rows, so nothing can be exported: " + snapshot.broken,
          "呢個面板交唔到啲列出嚟，所以匯出唔到：" + snapshot.broken
        );
        downloadButton.disabled = true;
        copyButton.disabled = true;
        downloadButton.textContent = t("Download", "下載");
        copyButton.textContent = t("Copy", "複製");
        previewSummary.textContent = t("Preview unavailable", "冇得預覽");
        previewPre.textContent = "";
        setStatus("", false);
        return;
      }

      if (!snapshot.rows.length) {
        buildChoices([]);
        lossNode.removeAttribute("data-state");
        lossNode.textContent = t(
          "Nothing matches the filter in force, so there is nothing to export. Clear the search and open this again.",
          "冇嘢符合而家嘅篩選，所以冇嘢可以匯出。清咗個搜尋再開多次。"
        );
        downloadButton.disabled = true;
        copyButton.disabled = true;
        downloadButton.textContent = t("Download", "下載");
        copyButton.textContent = t("Copy", "複製");
        previewSummary.textContent = t("Preview unavailable", "冇得預覽");
        previewPre.textContent = "";
        setStatus("", false);
        return;
      }

      var descriptors = formatsFor({
        kind: snapshot.shape.kind,
        fields: snapshot.shape.fields,
        rows: snapshot.rows,
      });
      buildChoices(descriptors);
      var wanted = null;
      choices.forEach(function (choice) {
        if (choice.descriptor.id === chosen) wanted = choice;
      });
      if (!wanted) wanted = choices[0];
      if (wanted) {
        wanted.input.checked = true;
        chosen = wanted.descriptor.id;
      }
      repaintSelection();
    }

    function place() {
      if (!open) return;
      var rect = button.getBoundingClientRect();
      var margin = 12;
      var width = panel.offsetWidth || 380;
      var below = window.innerHeight - rect.bottom - margin * 2;
      var above = rect.top - margin * 2;
      // The panel never covers the control that opened it: it takes whichever
      // side has more room and bounds itself to that, scrolling inside.
      var useBelow = below >= above;
      var room = Math.max(160, useBelow ? below : above);
      panel.style.maxHeight = Math.min(room, Math.round(window.innerHeight * 0.8)) + "px";
      var left = Math.min(Math.max(margin, rect.left), window.innerWidth - width - margin);
      panel.style.left = Math.max(margin, left) + "px";
      if (useBelow) {
        panel.style.top = rect.bottom + 8 + "px";
        panel.style.bottom = "auto";
      } else {
        panel.style.top = "auto";
        panel.style.bottom = window.innerHeight - rect.top + 8 + "px";
      }
    }

    function onDocumentPointer(event) {
      if (!open) return;
      if (panel.contains(event.target) || button.contains(event.target)) return;
      closePanel(false);
    }

    function onDocumentKey(event) {
      if (!open || event.key !== "Escape") return;
      event.stopPropagation();
      event.preventDefault();
      closePanel(true);
    }

    function onViewportChange() {
      place();
    }

    function openPanel() {
      if (open) return;
      if (!panel.parentNode) document.body.appendChild(panel);
      open = true;
      panel.hidden = false;
      button.setAttribute("aria-expanded", "true");
      refresh();
      place();
      document.addEventListener("pointerdown", onDocumentPointer, true);
      document.addEventListener("keydown", onDocumentKey, true);
      window.addEventListener("resize", onViewportChange, true);
      window.addEventListener("scroll", onViewportChange, true);
      var first = choices.filter(function (choice) {
        return choice.input.checked;
      })[0];
      if (first) first.input.focus();
      else closeButton.focus();
    }

    function closePanel(returnFocus) {
      if (!open) return;
      open = false;
      panel.hidden = true;
      button.setAttribute("aria-expanded", "false");
      document.removeEventListener("pointerdown", onDocumentPointer, true);
      document.removeEventListener("keydown", onDocumentKey, true);
      window.removeEventListener("resize", onViewportChange, true);
      window.removeEventListener("scroll", onViewportChange, true);
      if (returnFocus) button.focus();
    }

    function deliver(route) {
      var descriptor = selected();
      if (!descriptor || !snapshot) return;
      var built = runExport(snapshot.rows, descriptor.id, {
        dataset: id,
        title: snapshot.title,
        shape: snapshot.shape,
        total: snapshot.total,
        filter: snapshot.filter,
        range: rangeSentenceEnglish(snapshot),
        source: config.sourceMeta || null,
        deliver: "none",
      });
      if (!built.ok) {
        setStatus(built.error, true);
        site.notify(
          lang.emoji("⛔") + t("Export failed", "匯出失敗"),
          built.error,
          "error"
        );
        return;
      }

      var lossTail = built.losses.length
        ? " " + t(
            built.losses.length + " stated change" + (built.losses.length === 1 ? "" : "s") + " applied.",
            "已套用 " + built.losses.length + " 項已講明嘅改動。"
          )
        : "";

      if (route === "download") {
        var sent = download(built);
        if (!sent.ok) {
          setStatus(sent.error, true);
          site.notify(
            lang.emoji("⛔") + t("Download refused", "下載被拒"),
            sent.error,
            "error"
          );
          return;
        }
        recordExport(built, "download");
        setStatus(
          t(
            "Saved " + built.filename + " (" + humanBytes(built.bytes) + ")." + lossTail,
            "已儲存 " + built.filename + "（" + humanBytes(built.bytes) + "）。" + lossTail
          ),
          false
        );
        site.notify(
          lang.emoji("⬇️") + t("Exported " + snapshot.title, "已匯出" + snapshot.title),
          t(
            built.filename + " · " + built.rowCount + " of " + built.total + " rows · " +
              humanBytes(built.bytes) + " · UTF-8 · " + SCHEMA + "." + lossTail,
            built.filename + " · " + built.total + " 列之中嘅 " + built.rowCount + " 列 · " +
              humanBytes(built.bytes) + " · UTF-8 · " + SCHEMA + "。" + lossTail
          ),
          "success"
        );
        return;
      }

      copyText(built.text).then(
        function () {
          recordExport(built, "clipboard");
          setStatus(
            t(
              "Copied " + built.rowCount + " rows as " + built.label + " (" + humanBytes(built.bytes) + ")." + lossTail,
              "已複製 " + built.rowCount + " 列做 " + built.label + "（" + humanBytes(built.bytes) + "）。" + lossTail
            ),
            false
          );
          site.notify(
            lang.emoji("📋") + t("Copied " + snapshot.title, "已複製" + snapshot.title),
            t(
              built.rowCount + " of " + built.total + " rows as " + built.label + ", " + humanBytes(built.bytes) + ".",
              built.total + " 列之中嘅 " + built.rowCount + " 列，格式 " + built.label + "，" + humanBytes(built.bytes) + "。"
            ),
            "success"
          );
        },
        function (error) {
          var reason = (error && error.message) || String(error);
          setStatus(
            t(
              "The clipboard refused the copy, so nothing was copied: " + reason,
              "剪貼板拒絕咗複製，所以乜都冇複製到：" + reason
            ),
            true
          );
        }
      );
    }

    button.addEventListener("click", function () {
      if (open) closePanel(true);
      else openPanel();
    });
    closeButton.addEventListener("click", function () {
      closePanel(true);
    });
    downloadButton.addEventListener("click", function () {
      deliver("download");
    });
    copyButton.addEventListener("click", function () {
      deliver("clipboard");
    });

    host.appendChild(button);
    labelOnly();

    var handle = {
      id: id,
      button: button,
      open: openPanel,
      close: function () {
        closePanel(false);
      },
      refresh: function () {
        if (open) refresh();
        else labelOnly();
      },
      title: function () {
        return snapshot ? snapshot.title : id;
      },
    };
    MOUNTED.push(handle);
    return handle;
  }

  // ------------------------------------------------------------- the sources
  var SOURCES = {};
  var MOUNTED = [];

  function register(id, source) {
    if (!id || !source || typeof source.rows !== "function") return false;
    SOURCES[String(id)] = source;
    return true;
  }

  function byId(id) {
    return document.getElementById(id);
  }

  /** The regex builder persists each field's mode, so this is read, not guessed. */
  function activeFilter(inputId, regexName, extra) {
    var input = byId(inputId);
    var query = input && typeof input.value === "string" ? input.value : "";
    var saved = site.store.get("regex." + regexName, null) || {};
    // The query stays exactly what the user typed. A second filter alongside it
    // is described, never folded into the query string -- a file that reports a
    // search nobody ran is worse than one that reports none.
    return {
      query: query,
      regex: saved.regex === true,
      flags: saved.regex === true ? String(saved.flags == null ? "i" : saved.flags) : "",
      description: extra || "",
    };
  }

  function visibleIndexes(selector, attribute) {
    var out = [];
    var nodes = document.querySelectorAll(selector);
    Array.prototype.forEach.call(nodes, function (node) {
      // Only the hidden attribute counts. A card on a tab that is not currently
      // open is invisible on screen and has not been filtered out by anybody, so
      // measuring visibility here would export nothing from every closed tab.
      if (node.hidden) return;
      var raw = node.getAttribute(attribute);
      var index = Number(raw);
      if (isFinite(index)) out.push(index);
    });
    return out;
  }

  function dataRows(list, selector, attribute) {
    var source = Array.isArray(list) ? list : [];
    return visibleIndexes(selector, attribute)
      .map(function (index) {
        return source[index];
      })
      .filter(function (row) {
        return row != null;
      });
  }

  function activeCategory() {
    var pressed = document.querySelector('#feature-categories .chip[aria-pressed="true"]');
    if (!pressed) return null;
    var value = pressed.getAttribute("data-category");
    if (!value) return null;
    return "category: " + value;
  }

  function builtInSources() {
    var data = site.data || {};

    register("features", {
      title: function () {
        return t("the feature inventory", "功能清單");
      },
      shape: function () {
        return {
          id: "features",
          kind: "records",
          fields: [
            { name: "category" },
            { name: "title" },
            { name: "detail" },
            { name: "href" },
          ],
        };
      },
      rows: function () {
        return dataRows(data.features, "#feature-grid [data-feature-index]", "data-feature-index");
      },
      total: function () {
        return (data.features || []).length;
      },
      filter: function () {
        return activeFilter("feature-search", "feature", activeCategory());
      },
    });

    register("docs", {
      title: function () {
        return t("the documentation articles", "說明文章");
      },
      shape: function () {
        return {
          id: "docs",
          kind: "prose",
          fields: [
            { name: "title" },
            { name: "slug" },
            { name: "source" },
            { name: "summary" },
            { name: "body" },
            { name: "sections" },
            { name: "related" },
          ],
        };
      },
      rows: function () {
        var slugs = [];
        var nodes = document.querySelectorAll("#docs-index .docs-index-item");
        Array.prototype.forEach.call(nodes, function (item) {
          if (item.hidden) return;
          var link = item.querySelector(".docs-link[data-slug]");
          if (link) slugs.push(link.getAttribute("data-slug"));
        });
        var articles = Array.isArray(data.docs) ? data.docs : [];
        if (!nodes.length) return articles.slice();
        return articles.filter(function (article) {
          return slugs.indexOf(article.slug) !== -1;
        });
      },
      total: function () {
        return (data.docs || []).length;
      },
      filter: function () {
        return activeFilter("docs-search", "docs");
      },
    });

    register("screenshots", {
      title: function () {
        return t("the capture list", "截圖清單");
      },
      shape: function () {
        return {
          id: "screenshots",
          kind: "tabular",
          fields: [
            { name: "title" },
            { name: "src" },
            { name: "px" },
            { name: "provenance" },
            { name: "boundary" },
          ],
        };
      },
      rows: function () {
        return dataRows(data.shots, "#shots-grid [data-shot-index]", "data-shot-index");
      },
      total: function () {
        return (data.shots || []).length;
      },
      filter: function () {
        return activeFilter("shots-search", "shots");
      },
    });

    register("settings", {
      title: function () {
        return t("this site's settings", "呢個網站嘅設定");
      },
      shape: function () {
        return {
          id: "settings",
          kind: "tabular",
          fields: [
            { name: "key" },
            { name: "label" },
            { name: "type" },
            { name: "value" },
            { name: "isDefault" },
            { name: "provenance" },
            { name: "help" },
          ],
        };
      },
      rows: function () {
        var registry = typeof settings.registry === "function" ? settings.registry() : [];
        return registry
          .filter(function (def) {
            return !def.node || !def.node.hidden;
          })
          .map(function (def) {
            function safely(fn, fallback) {
              try {
                return fn ? fn() : fallback;
              } catch (error) {
                return fallback;
              }
            }
            return {
              key: def.key,
              label: def.label,
              type: def.type,
              value: safely(def.value, null),
              isDefault: safely(def.isDefault, null),
              provenance: safely(def.provenance, null),
              help: def.help,
            };
          });
      },
      total: function () {
        return typeof settings.registry === "function" ? settings.registry().length : 0;
      },
      filter: function () {
        return activeFilter("settings-search", "settings");
      },
    });

    register("notifications", {
      title: function () {
        return t("the notification history", "通知記錄");
      },
      shape: function () {
        return {
          id: "notifications",
          kind: "tabular",
          fields: [
            { name: "id" },
            { name: "at" },
            { name: "tone" },
            { name: "title" },
            { name: "body" },
          ],
        };
      },
      // notifications.js keeps its entries private, so the visible rows are read
      // from the drawer itself. That is also exactly what the filter left behind.
      rows: function () {
        var out = [];
        var nodes = document.querySelectorAll("#notif-list .notif-row");
        Array.prototype.forEach.call(nodes, function (node) {
          if (node.hidden) return;
          var time = node.querySelector(".notif-row-time");
          var title = node.querySelector(".notif-row-title");
          var body = node.querySelector(".notif-row-body");
          out.push({
            id: node.getAttribute("data-id") || "",
            at: time ? time.getAttribute("datetime") || time.textContent : "",
            tone: node.getAttribute("data-tone") || "info",
            title: title ? title.textContent : "",
            body: body ? body.textContent : "",
          });
        });
        return out;
      },
      total: function () {
        var count = byId("notif-count");
        var value = count ? Number(count.textContent) : NaN;
        if (isFinite(value)) return value;
        return document.querySelectorAll("#notif-list .notif-row").length;
      },
      filter: function () {
        return activeFilter("notif-search", "notif");
      },
    });
  }

  /**
   * A panel that has not registered a record shape still gets a working export:
   * its rendered rows are harvested as text, and the file says plainly that is
   * where they came from. Guessing at fields nobody declared would be worse.
   */
  function domFallbackSource(config) {
    return {
      title: config.title,
      shape: function () {
        var probe = document.querySelector(config.selector + "[data-export-row]");
        if (probe) {
          var fields = [];
          Array.prototype.forEach.call(probe.attributes, function (attribute) {
            if (attribute.name.indexOf("data-export-") !== 0) return;
            if (attribute.name === "data-export-row") return;
            fields.push({ name: attribute.name.slice("data-export-".length) });
          });
          if (fields.length) return { id: config.id, kind: "tabular", fields: fields };
        }
        return { id: config.id, kind: "prose", fields: [{ name: "index" }, { name: "text" }] };
      },
      rows: function () {
        var out = [];
        var nodes = document.querySelectorAll(config.selector);
        Array.prototype.forEach.call(nodes, function (node, index) {
          if (node.hidden) return;
          if (node.hasAttribute("data-export-row")) {
            var row = {};
            Array.prototype.forEach.call(node.attributes, function (attribute) {
              if (attribute.name.indexOf("data-export-") !== 0) return;
              if (attribute.name === "data-export-row") return;
              row[attribute.name.slice("data-export-".length)] = attribute.value;
            });
            out.push(row);
            return;
          }
          var text = String(node.textContent == null ? "" : node.textContent).replace(/[ \t]+/g, " ").trim();
          if (text) out.push({ index: index + 1, text: text });
        });
        return out;
      },
      total: function () {
        return document.querySelectorAll(config.selector).length;
      },
      filter: function () {
        return activeFilter(config.searchId, config.regexName);
      },
    };
  }

  // ------------------------------------------------------------------- boot
  var MOUNTS = [
    { id: "features", host: "#features .search-stack" },
    { id: "docs", host: "#docs .search-stack" },
    { id: "screenshots", host: "#screenshots .search-stack" },
    { id: "settings", host: "#settings .search-stack" },
    { id: "changelog", host: "#changelog .search-stack" },
    { id: "history", host: "#history .search-stack" },
    { id: "notifications", host: "#notifications .drawer-actions" },
  ];

  function boot() {
    installStyle();
    builtInSources();

    // changelog.js and history.js own their own records. They are given the
    // chance to register first; these fallbacks only run if they did not, and
    // only when the container they read actually holds rendered rows.
    if (!SOURCES.changelog) {
      register(
        "changelog",
        domFallbackSource({
          id: "changelog",
          title: function () {
            return t("the changelog", "更新日誌");
          },
          selector: "#changelog-list > *",
          searchId: "changelog-search",
          regexName: "changelog",
        })
      );
    }
    if (!SOURCES.history) {
      register(
        "history",
        domFallbackSource({
          id: "history",
          title: function () {
            return t("the local version history", "本機版本記錄");
          },
          selector: "#history-list > *",
          searchId: "history-search",
          regexName: "history",
        })
      );
    }

    MOUNTS.forEach(function (entry) {
      var host = document.querySelector(entry.host);
      if (!host) return;
      var source = SOURCES[entry.id];
      if (!source) return;
      // An export button beside an empty container would be a control that can
      // never do anything, so it is not rendered at all until rows exist.
      var rows;
      try {
        rows = source.rows();
      } catch (error) {
        rows = [];
      }
      var total = 0;
      try {
        total = Number(source.total());
      } catch (error) {
        total = rows.length;
      }
      if (!rows.length && !total) return;
      mount({ id: entry.id, mountTo: host });
    });

    settings.onChange(function (key) {
      if (
        key !== null &&
        key !== "language" &&
        key !== "emoji" &&
        key !== "funnyEn" &&
        key !== "funnyYue"
      ) {
        return;
      }
      MOUNTED.forEach(function (handle) {
        try {
          handle.refresh();
        } catch (error) {
          /* one control failing to re-language must not silence the others */
        }
      });
    });
  }

  site.ready(boot);

  // ---------------------------------------------------------------- palette
  site.registerPaletteSource(function () {
    return MOUNTED.map(function (handle) {
      var title = handle.title();
      var label = t("Export " + title + "…", "匯出" + title + "…");
      var detail = t(
        "Opens the export panel beside the list: nine formats, each one stating what it changes before it writes.",
        "喺個清單旁邊開匯出面板：九種格式，每種喺寫之前都會講明佢會改啲乜。"
      );
      var run = function () {
        handle.open();
      };
      return {
        id: "export:" + handle.id,
        kind: "command",
        section: t("Export", "匯出"),
        group: t("Export", "匯出"),
        title: label,
        label: label,
        detail: detail,
        hint: detail,
        subtitle: detail,
        run: run,
        action: run,
      };
    });
  });

  site.exporters = {
    formats: formatsFor,
    "export": runExport,
    register: register,
    mount: mount,
    sources: function () {
      return Object.keys(SOURCES);
    },
    SCHEMA: SCHEMA,
  };
})();
