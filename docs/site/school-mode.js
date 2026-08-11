/* The renamable presentation lock.
 *
 * While it is on the site presents in English only and several optional
 * capabilities behave as though they were never installed: their cards are
 * detached from the settings grid, their palette rows are dropped before the
 * palette ever sees them, and their surfaces are removed if another module
 * paints one. Omission rather than disabling is the whole point -- a greyed-out
 * control still tells the reader the feature exists and is being withheld.
 *
 * Two things are deliberately not stored: the credential (only a salted hash
 * of it is), and the user's language and funny-level choices (those stay in the
 * ordinary settings blob untouched, so turning the lock off returns them
 * exactly as they were rather than approximately).
 *
 * The name belongs to the user. Once renamed, the shipped name appears in no
 * label, help line, provenance line, palette row, notification or accessible
 * name -- which is why the DOM ids, the store key and the search keywords here
 * are all deliberately neutral.
 */
(function () {
  "use strict";

  var Site = window.AmuletSite;
  if (!Site) return;

  var el = Site.el;
  var settings = Site.settings;
  var lang = Site.lang;
  var store = Site.store;

  var STORE_KEY = "modeLock";
  var SHIPPED_NAME = "School mode";
  var MIN_SECRET = 4;
  var MAX_NAME = 60;
  var MAX_SECRET = 128;

  var PBKDF2 = "pbkdf2-sha256";
  var LOCAL = "local-fallback-v1";
  var PBKDF2_ROUNDS = 150000;
  var LOCAL_ROUNDS = 50000;
  var DIGEST_BITS = 256;

  var CARD_ID = "setting-mode-lock-card";
  var LABEL_ID = "setting-mode-lock-label";
  var HELP_ID = "setting-mode-lock-help";
  var STATUS_ID = "setting-mode-lock-status";
  var NAME_ID = "setting-mode-lock-name";
  var SECRET_ID = "setting-mode-lock-secret";
  var CONFIRM_ID = "setting-mode-lock-confirm";

  // The settings cards the lock detaches. Both spellings are queried: the id is
  // what settings-panel.js builds today, the data attribute is what it means.
  var OMITTED_CARDS =
    '[data-setting="language"],[data-setting="funnyEn"],[data-setting="funnyYue"],' +
    "#setting-language-card,#setting-funnyEn-card,#setting-funnyYue-card";

  // The dim sum surprise lives in its own file and can paint at any moment, so
  // the lock removes anything explicitly marked as one instead of trusting that
  // module to have asked. Only explicit markers are matched: a broad selector
  // here would eat unrelated content.
  var OMITTED_SURFACES =
    '[data-dimsum],[data-dim-sum],[data-surprise="dimsum"],[data-surprise="dim-sum"],' +
    ".dimsum,.dim-sum,#dimsum,#dim-sum";

  var OMITTED_KEYS = { language: 1, funnyEn: 1, funnyYue: 1 };
  var DIMSUM_TEXT = /dim[\s._-]*sum|點心/i;

  // ------------------------------------------------------------------ record
  function cleanName(value) {
    var text = String(value == null ? "" : value).replace(/\s+/g, " ").trim().slice(0, MAX_NAME);
    return text || SHIPPED_NAME;
  }

  function cleanCredential(value) {
    if (!value || typeof value !== "object") return null;
    var algorithm = String(value.algorithm);
    if (algorithm !== PBKDF2 && algorithm !== LOCAL) return null;
    var salt = String(value.salt || "");
    var digest = String(value.digest || "");
    if (!/^[0-9a-f]{16,256}$/.test(salt) || !/^[0-9a-f]{16,256}$/.test(digest)) return null;
    var rounds = Number(value.iterations);
    if (!isFinite(rounds) || rounds < 1 || rounds > 5000000) return null;
    return {
      algorithm: algorithm,
      salt: salt,
      digest: digest,
      iterations: Math.round(rounds),
      strongSalt: value.strongSalt !== false,
      createdAt: typeof value.createdAt === "string" ? value.createdAt : null,
    };
  }

  var repaired = false;

  function readRecord() {
    var raw = store.get(STORE_KEY, null);
    var out = {
      version: 1,
      configured: false,
      on: false,
      name: SHIPPED_NAME,
      credential: null,
      since: null,
    };
    if (!raw || typeof raw !== "object") return out;
    out.configured = true;
    out.name = cleanName(raw.name);
    out.credential = cleanCredential(raw.credential);
    out.since = typeof raw.since === "string" ? raw.since : null;
    out.on = raw.on === true && !!out.credential;
    // On with no usable credential would be a state nobody could ever leave, so
    // it is repaired rather than honoured, and the repair is reported.
    if (raw.on === true && !out.on) repaired = true;
    return out;
  }

  var record = readRecord();

  function persist() {
    return store.set(STORE_KEY, {
      version: 1,
      on: record.on,
      name: record.name,
      credential: record.credential,
      since: record.since,
    });
  }

  function locked() {
    return record.on === true && !!record.credential;
  }

  function modeName() {
    return record.name || SHIPPED_NAME;
  }

  function renamed() {
    return modeName() !== SHIPPED_NAME;
  }

  function quoted() {
    return "“" + modeName() + "”";
  }

  // ------------------------------------------------------------------- masks
  // Every module reads presentation through these two objects rather than from
  // storage, so replacing the methods (never the objects, which are already
  // captured by reference elsewhere) forces English without touching a single
  // stored preference.
  var baseMode = lang.mode;
  var baseT = lang.t;
  var baseFunny = lang.funny;

  lang.mode = function () {
    return locked() ? "english" : baseMode.apply(lang, arguments);
  };
  lang.t = function (en, yue) {
    return locked() ? String(en == null ? "" : en) : baseT.call(lang, en, yue);
  };
  lang.funny = function () {
    return locked() ? 1 : baseFunny.apply(lang, arguments);
  };

  var baseGet = settings.get;
  var baseAll = settings.all;
  var baseRegistry = settings.registry;
  var FORCED = { language: "english", funnyEn: 1, funnyYue: 1 };

  settings.get = function (key) {
    if (locked() && Object.prototype.hasOwnProperty.call(FORCED, key)) return FORCED[key];
    return baseGet.call(settings, key);
  };
  settings.all = function () {
    var out = baseAll.call(settings);
    if (locked()) {
      Object.keys(FORCED).forEach(function (key) {
        out[key] = FORCED[key];
      });
    }
    return out;
  };
  settings.registry = function () {
    var defs = baseRegistry.call(settings);
    if (!locked()) return defs;
    return defs.filter(function (def) {
      var key = def && def.key ? String(def.key) : "";
      return OMITTED_KEYS[key] !== 1 && !DIMSUM_TEXT.test(key);
    });
  };

  /** The unmasked value, for copy that has to state what is actually stored. */
  function storedValue(key) {
    return baseGet.call(settings, key);
  }

  // --------------------------------------------------------------- palette
  var basePaletteSources = Site.paletteSources;
  if (typeof basePaletteSources === "function") {
    Site.paletteSources = function () {
      var sources = basePaletteSources.call(Site);
      if (!locked()) return sources;
      return sources.map(function (source) {
        return function () {
          var produced = typeof source === "function" ? source() : source;
          if (!produced) return produced;
          var list = Array.isArray(produced) ? produced : [produced];
          return list.filter(function (entry) {
            return !omittedRow(entry);
          });
        };
      });
    };
  }

  function omittedRow(entry) {
    if (!entry || typeof entry !== "object") return false;
    var id = String(entry.id == null ? "" : entry.id);
    if (/^setting:(language|funnyEn|funnyYue)$/.test(id)) return true;
    // The dim sum module names its own rows, so the scan covers the fields a
    // contributor uses to title and group one rather than guessing at its ids.
    return DIMSUM_TEXT.test(
      [id, entry.kind, entry.group, entry.section, entry.title, entry.label].join(" ")
    );
  }

  // ------------------------------------------------------------- omission
  function removeAll(selector) {
    var nodes = document.querySelectorAll(selector);
    for (var i = 0; i < nodes.length; i++) {
      if (nodes[i].parentNode) nodes[i].parentNode.removeChild(nodes[i]);
    }
  }

  function applyOmission() {
    if (!locked()) return;
    removeAll(OMITTED_CARDS);
    removeAll(OMITTED_SURFACES);
  }

  function watchOmittedSurfaces() {
    if (!locked() || typeof window.MutationObserver !== "function") return;
    var observer = new window.MutationObserver(function (records) {
      for (var i = 0; i < records.length; i++) {
        var added = records[i].addedNodes;
        for (var j = 0; j < added.length; j++) {
          var node = added[j];
          if (!node || node.nodeType !== 1) continue;
          if (node.matches && node.matches(OMITTED_SURFACES)) {
            if (node.parentNode) node.parentNode.removeChild(node);
          } else if (node.querySelector && node.querySelector(OMITTED_SURFACES)) {
            removeAll(OMITTED_SURFACES);
          }
        }
      }
    });
    observer.observe(document.documentElement, { childList: true, subtree: true });
  }

  watchOmittedSurfaces();

  // ------------------------------------------------------------- credential
  function subtleCrypto() {
    try {
      var c = window.crypto;
      if (!c || !c.subtle) return null;
      if (typeof c.subtle.importKey !== "function" || typeof c.subtle.deriveBits !== "function") {
        return null;
      }
      return typeof window.TextEncoder === "function" ? c.subtle : null;
    } catch (error) {
      return null;
    }
  }

  function hexOf(bytes) {
    var out = "";
    for (var i = 0; i < bytes.length; i++) {
      var part = bytes[i].toString(16);
      out += part.length === 1 ? "0" + part : part;
    }
    return out;
  }

  function bytesOf(hex) {
    var out = new Uint8Array(Math.floor(hex.length / 2));
    for (var i = 0; i < out.length; i++) out[i] = parseInt(hex.slice(i * 2, i * 2 + 2), 16);
    return out;
  }

  function makeSalt() {
    var bytes = new Uint8Array(16);
    try {
      if (window.crypto && typeof window.crypto.getRandomValues === "function") {
        window.crypto.getRandomValues(bytes);
        return { hex: hexOf(bytes), strong: true };
      }
    } catch (error) {
      /* fall through to the weaker source, which is reported rather than hidden */
    }
    for (var i = 0; i < bytes.length; i++) bytes[i] = Math.floor(Math.random() * 256);
    return { hex: hexOf(bytes), strong: false };
  }

  function word32Hex(value) {
    var out = (value >>> 0).toString(16);
    while (out.length < 8) out = "0" + out;
    return out;
  }

  /* The fallback, used only where SubtleCrypto is absent. It is an iterated mix,
   * not a reviewed KDF, and every surface that mentions it says so. */
  function fallbackDigest(secret, saltHex, rounds) {
    var text = saltHex + " " + secret;
    var a = 0x811c9dc5;
    var b = 0x01000193;
    var c = 0x9e3779b9;
    var d = 0x85ebca6b;
    for (var r = 0; r < rounds; r++) {
      for (var i = 0; i < text.length; i++) {
        var code = text.charCodeAt(i);
        a = Math.imul(a ^ (code + r), 16777619) >>> 0;
        b = (b + Math.imul(a ^ code, 2654435761)) >>> 0;
        c = ((c << 5) | (c >>> 27)) >>> 0;
        c = (c ^ b) >>> 0;
        d = (d + Math.imul(c ^ ((code << 3) >>> 0), 40503)) >>> 0;
      }
      a = (a ^ (d >>> 7)) >>> 0;
      b = (b ^ (a >>> 11)) >>> 0;
      c = (c ^ (b >>> 5)) >>> 0;
      d = (d ^ (c >>> 13)) >>> 0;
    }
    return word32Hex(a) + word32Hex(b) + word32Hex(c) + word32Hex(d);
  }

  function derive(secret, saltHex, algorithm, rounds) {
    if (algorithm === PBKDF2) {
      var api = subtleCrypto();
      if (!api) {
        return Promise.reject(
          new Error("crypto.subtle is not available in this browsing context")
        );
      }
      var encoded = new window.TextEncoder().encode(secret);
      return api
        .importKey("raw", encoded, { name: "PBKDF2" }, false, ["deriveBits"])
        .then(function (key) {
          return api.deriveBits(
            { name: "PBKDF2", salt: bytesOf(saltHex), iterations: rounds, hash: "SHA-256" },
            key,
            DIGEST_BITS
          );
        })
        .then(function (bits) {
          return hexOf(new Uint8Array(bits));
        });
    }
    return new Promise(function (resolve) {
      resolve(fallbackDigest(secret, saltHex, rounds));
    });
  }

  function sameDigest(a, b) {
    if (typeof a !== "string" || typeof b !== "string" || a.length !== b.length) return false;
    var diff = 0;
    for (var i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
    return diff === 0;
  }

  function algorithmNow() {
    return subtleCrypto() ? PBKDF2 : LOCAL;
  }

  function roundsFor(algorithm) {
    return algorithm === PBKDF2 ? PBKDF2_ROUNDS : LOCAL_ROUNDS;
  }

  /* Identifiers and counts only. Every message below interpolates this into its
   * own English and Cantonese wording rather than nesting one translated string
   * inside another, which in bilingual mode would print both halves twice. */
  function algorithmId(algorithm, rounds) {
    return (algorithm === PBKDF2 ? "PBKDF2-HMAC-SHA-256" : LOCAL) + " x" + rounds;
  }

  /** Says plainly, where it applies, that the weaker route is in use and why. */
  function weakerTail(algorithm) {
    if (algorithm !== LOCAL) return "";
    return (
      " " +
      t(
        LOCAL + " is a weaker in-page hash rather than a reviewed key-derivation function. It is in use because this browsing context exposes no crypto.subtle: Web Crypto's SubtleCrypto is unavailable outside a secure context, which includes a page opened from a file:// path.",
        LOCAL + " 係頁面內較弱嘅雜湊，唔係經審視嘅金鑰導出函數。行佢係因為呢個瀏覽環境冇 crypto.subtle：Web Crypto 嘅 SubtleCrypto 喺非安全內容（包括用 file:// 開嘅頁）用唔到。"
      )
    );
  }

  // ------------------------------------------------------------------- copy
  function t(en, yue) {
    return lang.t(en, yue);
  }

  function clearDataRoute() {
    return t(
      "Clearing this site's stored data in your browser — the padlock or tune icon at the left of the address bar → Site settings → Delete data, or Settings → Privacy → Clear browsing data → Cookies and other site data — removes it, along with every other preference this page has saved.",
      "喺瀏覽器清走呢個網站嘅儲存資料 — 網址列左邊嗰個鎖頭或者調較圖示 → 網站設定 → 刪除資料，又或者 設定 → 私隱 → 清除瀏覽資料 → Cookie 同其他網站資料 — 就會連同呢一頁儲存過嘅所有偏好一齊移走。"
    );
  }

  function notASecurityBoundary() {
    return (
      t(
        "This is a presentation lock, not a security boundary.",
        "呢個係顯示鎖，唔係保安界線。"
      ) +
      " " +
      clearDataRoute()
    );
  }

  function helpCopy() {
    if (locked()) {
      return (
        t(
          quoted() + " is on. This page is presenting in English only, and some optional capabilities are not offered while it is on. To turn it off, enter the credential set when it was turned on — the same credential, in this browser. Only a salted hash of it was stored, so a forgotten credential cannot be recovered or reset from here.",
          quoted() + " 而家開咗。呢一頁淨係用英文顯示，開住嘅時候有部分選用功能唔會提供。想閂返，就要輸入開嗰陣設定嘅憑證 — 同一個憑證，同一個瀏覽器。只係存咗加鹽雜湊，所以忘記咗喺呢度冇得復原或者重設。"
        ) +
        " " +
        notASecurityBoundary()
      );
    }
    return (
      t(
        "Turns this page into an English-only presentation and withholds several optional capabilities until it is turned off. While it is on, the Cantonese and bilingual language modes, both funny-level sliders and the dim sum surprise are removed from the settings grid, the command palette and every search on this page rather than greyed out; your stored choices are kept untouched and come back when it is turned off. Turning it on asks for a name and a credential; turning it off asks for that credential again, and only a salted hash of it is ever stored.",
        "將呢一頁變成淨係英文顯示，並且喺閂返之前收起幾項選用功能。開住嗰陣，粵語同雙語模式、兩條搞笑程度掣同點心驚喜會喺設定格、指令面板同呢一頁每個搜尋度直接移走，唔係變灰；你儲存咗嘅選擇原封不動，閂返就會返嚟。開嗰陣要改個名同設定憑證；閂嗰陣要再輸入同一個憑證，而系統由頭到尾只存加鹽雜湊。"
      ) +
      " " +
      notASecurityBoundary()
    );
  }

  function provenanceCopy() {
    if (!record.configured) {
      return t(
        "Not set here yet, so the shipped state is in use: off, named " + quoted() + ".",
        "呢度未設定過，所以行緊出廠狀態：閂咗，名叫" + quoted() + "。"
      );
    }
    var credential = record.credential;
    if (!locked()) {
      return (
        t(
          "Stored in this browser: off, named " + quoted() + ". The shipped state is off.",
          "存喺呢個瀏覽器：閂咗，名叫" + quoted() + "。出廠狀態係閂。"
        ) +
        " " +
        (credential
          ? t(
              "A credential hash is stored from an earlier session.",
              "仲存住之前一次設定嘅憑證雜湊。"
            )
          : t(
              "No credential is stored; turning it on will ask you to set one.",
              "而家冇存憑證；開嗰陣會叫你設定一個。"
            ))
      );
    }
    var digest = algorithmId(credential.algorithm, credential.iterations);
    var line = record.since
      ? t(
          "Stored in this browser: on since " + record.since + ", named " + quoted() +
            ". The shipped state is off. The credential itself is not stored — only a " +
            digest + " digest over a 16-byte salt.",
          "存喺呢個瀏覽器：由 " + record.since + " 開始開住，名叫" + quoted() +
            "。出廠狀態係閂。憑證本身冇存 — 只係存咗用 16 bytes 鹽值行 " + digest + " 出嚟嘅摘要。"
        )
      : t(
          "Stored in this browser: on, with no start time recorded, named " + quoted() +
            ". The shipped state is off. The credential itself is not stored — only a " +
            digest + " digest over a 16-byte salt.",
          "存喺呢個瀏覽器：開住，但冇記低開始時間，名叫" + quoted() +
            "。出廠狀態係閂。憑證本身冇存 — 只係存咗用 16 bytes 鹽值行 " + digest + " 出嚟嘅摘要。"
        );
    line += weakerTail(credential.algorithm);
    if (credential.strongSalt === false) {
      line +=
        " " +
        t(
          "The salt came from Math.random because this browser exposed no crypto.getRandomValues when it was set.",
          "設定嗰陣呢個瀏覽器冇 crypto.getRandomValues，所以鹽值係用 Math.random 攞。"
        );
    }
    return line;
  }

  // ----------------------------------------------------------------- state
  var armed = false;
  var busy = false;
  var statusRender = null;

  function setStatus(render, isError) {
    statusRender = render ? { render: render, error: !!isError } : null;
    paintStatus();
  }

  function paintStatus() {
    if (!statusNode) return;
    statusNode.textContent = statusRender ? statusRender.render() : "";
    if (statusRender && statusRender.error) statusNode.setAttribute("data-state", "error");
    else statusNode.removeAttribute("data-state");
  }

  function reducedMotion() {
    if (settings.get("reducedMotion") === true) return true;
    try {
      return !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
    } catch (error) {
      return false;
    }
  }

  // ------------------------------------------------------------------ nodes
  var card = null;
  var labelNode = null;
  var helpNode = null;
  var provenanceNode = null;
  var statusNode = null;
  var controlNode = null;
  var nameField = null;
  var nameCaption = null;
  var nameInput = null;
  var secretField = null;
  var secretCaption = null;
  var secretInput = null;
  var confirmField = null;
  var confirmCaption = null;
  var confirmInput = null;
  var primaryButton = null;
  var cancelButton = null;
  var renameButton = null;
  var primaryRow = null;
  var renameRow = null;
  var laidOutLocked = null;

  var STYLE_ID = "mode-lock-style";
  var STYLE_CSS = [
    "#" + CARD_ID + "{scroll-margin-top:120px}",
    "#" + CARD_ID + " .setting-control{display:grid;gap:10px}",
    "#" + CARD_ID + " label{display:grid;gap:6px}",
    "#" + CARD_ID + " .setting-actions{display:flex;gap:10px;flex-wrap:wrap}",
    "#" + CARD_ID + " .setting-note{color:var(--secondary);font-size:.78rem}",
    "#" + CARD_ID + ' .setting-note[data-state="error"]{color:#8c1d18;font-weight:700}',
    ".dark #" + CARD_ID + ' .setting-note[data-state="error"]{color:#ffb4ab}',
    "#" + CARD_ID + " [disabled]{opacity:.62;cursor:not-allowed}",
    "#" + CARD_ID + " :focus-visible{outline:3px solid var(--primary);outline-offset:2px}",
    "#" + CARD_ID + ' .setting-danger[data-armed="true"]{background:#8c1d18;color:#fff}',
  ].join("");

  function installStyle() {
    if (document.getElementById(STYLE_ID)) return;
    var style = el("style", { id: STYLE_ID });
    style.textContent = STYLE_CSS;
    (document.head || document.documentElement).appendChild(style);
  }

  function field(id, type, autocompleteValue) {
    var caption = el("span");
    var input = el("input", {
      type: type,
      id: id,
      maxlength: String(type === "text" ? MAX_NAME : MAX_SECRET),
      autocomplete: autocompleteValue,
      autocapitalize: "off",
      autocorrect: "off",
      spellcheck: "false",
      "aria-describedby": HELP_ID + " " + STATUS_ID,
    });
    return { node: el("label", { for: id }, caption, input), caption: caption, input: input };
  }

  function buildCard() {
    labelNode = el("span", { id: LABEL_ID });
    helpNode = el("small", { class: "setting-help", id: HELP_ID });
    provenanceNode = el("small", { class: "setting-provenance" });
    statusNode = el("small", { class: "setting-note", id: STATUS_ID, role: "status" });

    var name = field(NAME_ID, "text", "off");
    nameField = name.node;
    nameCaption = name.caption;
    nameInput = name.input;

    var secret = field(SECRET_ID, "password", "off");
    secretField = secret.node;
    secretCaption = secret.caption;
    secretInput = secret.input;

    var confirm = field(CONFIRM_ID, "password", "off");
    confirmField = confirm.node;
    confirmCaption = confirm.caption;
    confirmInput = confirm.input;

    primaryButton = el("button", {
      type: "button",
      class: "button button-tonal setting-danger",
      id: "setting-mode-lock-primary",
      "aria-describedby": HELP_ID + " " + STATUS_ID,
    });
    cancelButton = el("button", {
      type: "button",
      class: "button button-text",
      id: "setting-mode-lock-cancel",
      hidden: true,
    });
    renameButton = el("button", {
      type: "button",
      class: "button button-outlined",
      id: "setting-mode-lock-rename",
      "aria-describedby": STATUS_ID,
    });

    primaryRow = el("div", { class: "setting-actions" }, primaryButton, cancelButton);
    renameRow = el("div", { class: "setting-actions" }, renameButton);

    controlNode = el("div", {
      class: "setting-control",
      role: "group",
      "aria-labelledby": LABEL_ID,
    });

    card = el(
      "div",
      { class: "setting-card", id: CARD_ID, "data-setting": "modeLock" },
      labelNode,
      controlNode,
      helpNode,
      provenanceNode
    );

    primaryButton.addEventListener("click", onPrimary);
    cancelButton.addEventListener("click", function () {
      disarm(true);
    });
    renameButton.addEventListener("click", onRename);

    // Editing any field after arming would leave the armed sentence describing
    // values that are no longer the ones about to be used.
    [nameInput, secretInput, confirmInput].forEach(function (input) {
      input.addEventListener("input", function () {
        if (armed) disarm(false);
      });
      input.addEventListener("keydown", function (event) {
        if (event.key !== "Enter" || event.isComposing) return;
        event.preventDefault();
        // Enter commits the field it was pressed in, not whichever action the
        // card considers primary -- the name field is not a submit button for
        // turning the mode on.
        if (input === nameInput) onRename();
        else onPrimary();
      });
    });

    card.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && armed) {
        event.stopPropagation();
        disarm(true);
      }
    });
    card.addEventListener("focusout", function (event) {
      if (armed && !card.contains(event.relatedTarget)) disarm(false);
    });
  }

  function layout() {
    var want = locked();
    if (laidOutLocked === want) return;
    laidOutLocked = want;
    var order = want
      ? [secretField, primaryRow, nameField, renameRow, statusNode]
      : [nameField, secretField, confirmField, primaryRow, renameRow, statusNode];
    controlNode.replaceChildren.apply(controlNode, order);
  }

  function refresh() {
    if (!card) return;
    layout();
    labelNode.textContent = modeName();
    helpNode.textContent = helpCopy();
    provenanceNode.textContent = provenanceCopy();

    nameCaption.textContent = t("Name for this mode", "呢個模式嘅名");
    nameInput.setAttribute(
      "placeholder",
      t("A name of your own", "改個你自己嘅名")
    );
    if (document.activeElement !== nameInput && nameInput.value === "") {
      nameInput.value = modeName();
    }

    if (locked()) {
      secretCaption.textContent = t(
        "Credential set when " + quoted() + " was turned on",
        "開" + quoted() + "嗰陣設定嘅憑證"
      );
      primaryButton.textContent = t("Turn off " + quoted(), "閂返" + quoted());
      primaryButton.removeAttribute("data-armed");
    } else {
      secretCaption.textContent = t(
        "Credential to set, at least " + MIN_SECRET + " characters",
        "要設定嘅憑證，最少 " + MIN_SECRET + " 個字元"
      );
      confirmCaption.textContent = t("Type the credential again", "再輸入一次憑證");
      primaryButton.textContent = armed
        ? t("Confirm — turn on " + quoted(), "確認 — 開" + quoted())
        : t("Turn on " + quoted(), "開" + quoted());
      primaryButton.setAttribute("data-armed", String(armed));
    }
    primaryButton.disabled = busy;
    cancelButton.hidden = !armed;
    cancelButton.textContent = t("Cancel", "取消");
    renameButton.textContent = t("Save this name", "儲存呢個名");
    renameButton.disabled = busy;
    card.setAttribute("aria-busy", String(busy));
    paintStatus();
  }

  // --------------------------------------------------------------- actions
  function disarm(report) {
    if (!armed) return;
    armed = false;
    if (report) {
      setStatus(function () {
        return t(
          "Nothing was turned on. Every capability is still offered.",
          "冇開到任何嘢，所有功能一樣照樣提供。"
        );
      }, false);
      primaryButton.focus();
    } else {
      setStatus(null, false);
    }
    refresh();
  }

  function armedSentence() {
    var typed = cleanName(nameInput.value);
    var rename =
      typed === modeName()
        ? ""
        : " " +
          t(
            "It will be named “" + typed + "” from then on.",
            "由嗰陣開始佢會叫做“" + typed + "”。"
          );
    var kept =
      "language=" + String(storedValue("language")) +
      ", funnyEn=" + String(storedValue("funnyEn")) +
      ", funnyYue=" + String(storedValue("funnyYue"));
    var algorithm = algorithmNow();
    var digest = algorithmId(algorithm, roundsFor(algorithm));
    return (
      t(
        "Armed. The next press turns it on. The Cantonese and bilingual language modes, both funny-level sliders and the dim sum surprise are then removed from the settings grid, the command palette and every search on this page — removed, not greyed out. Your stored choices (" +
          kept +
          ") stay saved and stop being used until it is turned off. Turning it off will need the credential typed above; only a " +
          digest +
          " digest of it is stored, so it cannot be recovered from here. The page reloads once so every surface starts in the mode.",
        "已解鎖。再撳一次就會開。粵語同雙語模式、兩條搞笑程度掣同點心驚喜會即刻由設定格、指令面板同呢一頁每個搜尋度移走 — 係移走，唔係變灰。你儲存咗嘅選擇（" +
          kept +
          "）會照樣留住，閂返之前唔會用。想閂返就要用上面打嗰個憑證；系統只存佢嘅 " +
          digest +
          " 摘要，所以喺呢度冇得復原。頁面會重載一次，令每個介面都由呢個模式開始。"
      ) +
      rename +
      weakerTail(algorithm) +
      " " +
      t("Press Cancel or Escape to stop.", "撳「取消」或者 Escape 就可以停手。")
    );
  }

  function onPrimary() {
    if (busy) return;
    if (locked()) unlockAttempt();
    else enableAttempt();
  }

  function enableAttempt() {
    var secret = secretInput.value;
    var confirm = confirmInput.value;
    if (secret.length < MIN_SECRET) {
      armed = false;
      setStatus(function () {
        return t(
          "Nothing was turned on: the credential needs at least " + MIN_SECRET +
            " characters and this one has " + secret.length + ".",
          "冇開到：憑證最少要 " + MIN_SECRET + " 個字元，而家得 " + secret.length + " 個。"
        );
      }, true);
      refresh();
      secretInput.focus();
      return;
    }
    if (secret !== confirm) {
      armed = false;
      setStatus(function () {
        return t(
          "Nothing was turned on: the two credential fields do not match.",
          "冇開到：兩個憑證欄唔一樣。"
        );
      }, true);
      refresh();
      confirmInput.focus();
      confirmInput.select();
      return;
    }
    if (!armed) {
      armed = true;
      setStatus(armedSentence, false);
      refresh();
      primaryButton.focus();
      return;
    }

    var chosenName = cleanName(nameInput.value);
    var algorithm = algorithmNow();
    var rounds = roundsFor(algorithm);
    var salt = makeSalt();
    armed = false;
    busy = true;
    setStatus(function () {
      return t(
        "Checking — deriving the credential digest with " + algorithmId(algorithm, rounds) + ".",
        "處理緊 — 用 " + algorithmId(algorithm, rounds) + " 導出憑證摘要。"
      );
    }, false);
    refresh();

    derive(secret, salt.hex, algorithm, rounds).then(
      function (digest) {
        busy = false;
        record.configured = true;
        record.on = true;
        record.name = chosenName;
        record.since = timestamp();
        record.credential = {
          algorithm: algorithm,
          salt: salt.hex,
          digest: digest,
          iterations: rounds,
          strongSalt: salt.strong,
          createdAt: timestamp(),
        };
        var written = persist();
        secretInput.value = "";
        confirmInput.value = "";
        if (!written) {
          record.on = false;
          record.credential = null;
          setStatus(function () {
            return t(
              "Nothing was turned on: this browser refused to store the setting, so the state could not be recorded.",
              "冇開到：呢個瀏覽器唔肯儲存呢項設定，所以個狀態記唔到。"
            );
          }, true);
          refresh();
          return;
        }
        applyOmission();
        syncCard();
        recount(); // the grid just lost cards; the count beside the search must follow
        // The status still holds the "checking" line, which stops being true the
        // moment the digest lands.
        setStatus(function () {
          return t(
            quoted() + " is on. Reloading so every surface starts in the mode.",
            quoted() + "開咗。而家重載頁面，令每個介面都由呢個模式開始。"
          );
        }, false);
        refresh();
        Site.notify(
          lang.emoji("🔒") + t(quoted() + " is on", quoted() + "已經開咗"),
          t(
            "This page presents in English only from now on. Turning it off needs the credential you set, in this browser. Reloading now so every surface starts in the mode.",
            "由而家開始呢一頁淨係用英文顯示。想閂返就要喺呢個瀏覽器輸入你設定嗰個憑證。而家重載頁面，令每個介面都由呢個模式開始。"
          )
        );
        reload();
      },
      function (error) {
        busy = false;
        var reason = error && error.message ? String(error.message) : String(error);
        setStatus(function () {
          return t(
            "Nothing was turned on: the credential hash could not be derived — " + reason,
            "冇開到：導唔到憑證雜湊 — " + reason
          );
        }, true);
        refresh();
        primaryButton.focus();
      }
    );
  }

  function unlockAttempt() {
    var secret = secretInput.value;
    var credential = record.credential;
    if (!secret) {
      setStatus(function () {
        return t(
          quoted() + " is still on: no credential was entered.",
          quoted() + "仲開住：冇輸入過憑證。"
        );
      }, true);
      secretInput.focus();
      return;
    }
    busy = true;
    setStatus(function () {
      return t(
        "Checking the credential with " + algorithmId(credential.algorithm, credential.iterations) + ".",
        "用 " + algorithmId(credential.algorithm, credential.iterations) + " 檢查緊個憑證。"
      );
    }, false);
    refresh();

    derive(secret, credential.salt, credential.algorithm, credential.iterations).then(
      function (digest) {
        busy = false;
        if (!sameDigest(digest, credential.digest)) {
          setStatus(function () {
            return t(
              quoted() + " is still on: that credential does not match the stored hash. Nothing was changed.",
              quoted() + "仲開住：呢個憑證同存住嘅雜湊唔夾。乜都冇改到。"
            );
          }, true);
          refresh();
          secretInput.focus();
          secretInput.select();
          return;
        }
        var name = modeName();
        record.on = false;
        record.since = null;
        // The next enable sets a fresh credential rather than silently reusing
        // one the user may have chosen a long time ago for a different reason.
        record.credential = null;
        var written = persist();
        secretInput.value = "";
        if (!written) {
          record.on = true;
          record.credential = credential;
          setStatus(function () {
            return t(
              "The credential was correct, but this browser refused to store the change, so nothing was turned off.",
              "憑證啱，不過呢個瀏覽器唔肯儲存呢個改動，所以乜都冇閂到。"
            );
          }, true);
          refresh();
          return;
        }
        setStatus(function () {
          return t(
            "“" + name + "” is off. Reloading so every surface starts without it.",
            "“" + name + "”閂咗。而家重載頁面，令每個介面都唔再受佢影響。"
          );
        }, false);
        refresh();
        Site.notify(
          lang.emoji("🔓") + t(
            "“" + name + "” is off",
            "“" + name + "”已經閂咗"
          ),
          t(
            "The credential was verified in this browser. Your stored language mode, funny levels and the dim sum surprise are in use again. The stored credential was cleared, so turning it on again will ask for a new one. Reloading now.",
            "個憑證喺呢個瀏覽器驗證咗。你儲存嘅語言模式、搞笑程度同點心驚喜返返嚟。存住嘅憑證已經清走，下次開要重新設定一個。而家重載頁面。"
          )
        );
        reload();
      },
      function (error) {
        busy = false;
        var reason = error && error.message ? String(error.message) : String(error);
        setStatus(function () {
          return t(
            quoted() + " is still on: the credential could not be checked — " + reason,
            quoted() + "仲開住：檢查唔到個憑證 — " + reason
          );
        }, true);
        refresh();
      }
    );
  }

  function onRename() {
    if (busy) return;
    var typed = String(nameInput.value == null ? "" : nameInput.value).trim();
    if (!typed) {
      setStatus(function () {
        return t(
          "The name was not changed: a name is required.",
          "個名冇改到：一定要有個名。"
        );
      }, true);
      nameInput.focus();
      return;
    }
    var next = cleanName(typed);
    if (next === modeName()) {
      setStatus(function () {
        return t("The name was already " + quoted() + ".", "個名本身已經係" + quoted() + "。");
      }, false);
      return;
    }
    record.name = next;
    record.configured = true;
    if (!persist()) {
      setStatus(function () {
        return t(
          "The name was not changed: this browser refused to store it.",
          "個名冇改到：呢個瀏覽器唔肯儲存。"
        );
      }, true);
      record = readRecord();
      refresh();
      return;
    }
    if (armed) armed = false;
    setStatus(function () {
      return t(
        "Renamed. Every label, help line, palette result and message here now uses " + quoted() + ".",
        "改咗名。呢度每個標籤、說明、指令面板結果同訊息而家都用" + quoted() + "。"
      );
    }, false);
    refresh();
    Site.notify(
      lang.emoji("✏️") + t("Renamed to " + quoted(), "改咗名做" + quoted()),
      t(
        "Every surface on this page now uses " + quoted() + ". The name is stored in this browser only.",
        "呢一頁每個介面而家都用" + quoted() + "。個名只存喺呢個瀏覽器。"
      )
    );
  }

  function timestamp() {
    try {
      return new Date().toISOString();
    } catch (error) {
      return String(Date.now());
    }
  }

  function reload() {
    // Modules read the presentation mode once, at load. A reload is what makes
    // an unseen module start in the new mode rather than half-repainted.
    window.setTimeout(function () {
      try {
        window.location.reload();
      } catch (error) {
        setStatus(function () {
          return t(
            "The page could not reload itself, so reload it to apply " + quoted() + " everywhere: " +
              (error && error.message ? error.message : String(error)),
            "頁面自己重載唔到，請自行重載，令" + quoted() + "喺所有地方生效：" +
              (error && error.message ? error.message : String(error))
          );
        }, true);
      }
    }, 500);
  }

  // ------------------------------------------------- settings-grid plumbing
  /* The settings search is owned by settings-panel.js, which knows nothing
   * about this card. Attaching a second builder under the same name would tear
   * down the first one's controls, so the mode and flags are read back from the
   * store the shared builder persists them in, and the query from the field the
   * builder mirrors into. One matcher, one set of bounds, two readers. */
  function searchState() {
    var input = document.getElementById("settings-search");
    var saved = store.get("regex.settings", null) || {};
    return {
      query: input ? String(input.value || "") : "",
      regex: saved.regex === true,
      flags: typeof saved.flags === "string" ? saved.flags : "i",
    };
  }

  function haystack() {
    var words = [
      modeName(),
      "mode lock presentation english credential unlock rename reload",
      helpNode ? helpNode.textContent : "",
      locked() ? "on" : "off",
    ];
    if (!locked()) words.push("模式 鎖 顯示 英文 憑證 解鎖 改名");
    return words.join(" ");
  }

  function setHidden(node, value) {
    // Only writing on a real change keeps the grid observer below from being
    // re-entered by its own repair pass.
    if (node.hidden !== value) node.hidden = value;
  }

  function syncCard() {
    if (!card || !card.parentNode) return;
    var state = searchState();
    if (!state.query) {
      setHidden(card, false);
      return;
    }
    var match = false;
    try {
      match = Site.matcher(state.query, state.regex, state.flags).test(haystack());
    } catch (error) {
      match = false; // an invalid pattern never ran, so it never matched
    }
    setHidden(card, !match);
  }

  /* settings-panel.js counts its own records, so its count knows nothing about
   * this card and still counts the cards this mode detached. Recounting from
   * what is actually in the grid is the only figure that matches the screen. */
  function recount() {
    var grid = document.getElementById("settings-grid");
    if (!grid) return;
    var shown = 0;
    var children = grid.children;
    for (var i = 0; i < children.length; i++) {
      var node = children[i];
      if (!node.classList || !node.classList.contains("setting-card")) continue;
      if (!node.hidden) shown++;
    }
    var countNode = document.getElementById("settings-count");
    var emptyNode = document.getElementById("settings-empty");
    var query = searchState().query;
    if (countNode) {
      var line = Site.describe(shown, "setting", query);
      if (countNode.textContent !== line) countNode.textContent = line;
    }
    if (emptyNode) emptyNode.hidden = shown !== 0;
  }

  function watchGrid() {
    var grid = document.getElementById("settings-grid");
    if (!grid) return;
    var input = document.getElementById("settings-search");
    if (input) {
      input.addEventListener("input", function () {
        syncCard();
        recount();
      });
    }
    if (typeof window.MutationObserver !== "function") return;
    // The builder's own controls filter through settings-panel rather than
    // through the field, so the grid itself is the only reliable signal that a
    // filter pass has run.
    var observer = new window.MutationObserver(function () {
      syncCard();
      recount();
    });
    // subtree, because the attribute that matters is on the grid's children.
    observer.observe(grid, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["hidden"],
    });
  }

  function flash() {
    card.style.outline = "3px solid var(--primary)";
    card.style.outlineOffset = "3px";
    window.setTimeout(function () {
      card.style.outline = "";
      card.style.outlineOffset = "";
    }, 1600);
  }

  function jump(target) {
    Site.showTab("settings");
    var input = document.getElementById("settings-search");
    if (input && input.value) {
      input.value = "";
      if (typeof window.Event === "function") {
        input.dispatchEvent(new window.Event("input", { bubbles: true }));
      }
      syncCard();
      recount();
    }
    setHidden(card, false);
    try {
      card.scrollIntoView({ block: "center", behavior: reducedMotion() ? "auto" : "smooth" });
    } catch (error) {
      card.scrollIntoView(false);
    }
    var focusTarget = target || (locked() ? secretInput : nameInput);
    if (focusTarget && typeof focusTarget.focus === "function") focusTarget.focus();
    flash();
  }

  // ------------------------------------------------------------------- boot
  Site.ready(function () {
    var grid = document.getElementById("settings-grid");
    installStyle();
    applyOmission();
    if (!grid) return;

    buildCard();
    var resetCard = document.getElementById("setting-reset-card");
    if (resetCard && resetCard.parentNode === grid) grid.insertBefore(card, resetCard);
    else grid.appendChild(card);

    refresh();

    var def = {
      key: "modeLock",
      type: "mode-lock",
      tab: "settings",
      cardId: CARD_ID,
      controlId: SECRET_ID,
      labelNow: modeName,
      helpNow: helpCopy,
      value: function () {
        return locked() ? "on" : "off";
      },
      isDefault: function () {
        return !record.configured;
      },
      provenance: provenanceCopy,
      focus: function () {
        jump();
      },
      node: card,
    };
    // Live getters rather than snapshots: a registry consumer that reads
    // def.label after a rename must never be handed the shipped name.
    Object.defineProperty(def, "label", {
      enumerable: true,
      get: modeName,
    });
    Object.defineProperty(def, "help", {
      enumerable: true,
      get: helpCopy,
    });
    settings.register(def);

    watchGrid();
    syncCard();
    recount();

    settings.onChange(function () {
      refresh();
      syncCard();
      recount();
    });

    if (repaired) {
      repaired = false;
      persist();
      Site.notify(
        lang.emoji("⚠️") + t("Stored mode state repaired", "已修復儲存嘅模式狀態"),
        t(
          "The stored record said the mode was on but carried no usable credential, which nobody could have turned off. It has been recorded as off; the setting card can turn it on again.",
          "存住嘅記錄話個模式開咗，但係冇可用嘅憑證，咁樣冇人閂得返。而家已經記錄為閂咗；喺設定卡可以再開返。"
        )
      );
    }
  });

  Site.registerPaletteSource(function () {
    if (!card) return [];
    var rows = [];
    var group = t("Presentation lock", "顯示鎖");

    function row(id, title, detail, target) {
      var run = function () {
        jump(target);
      };
      return {
        id: "mode-lock:" + id,
        kind: "setting",
        group: group,
        section: group,
        tab: "settings",
        title: title,
        label: title,
        detail: detail,
        subtitle: detail,
        value: locked() ? "on" : "off",
        keywords: haystack(),
        run: run,
        action: run,
      };
    }

    if (locked()) {
      rows.push(
        row(
          "unlock",
          t("Turn off " + quoted(), "閂返" + quoted()),
          t(
            "Opens the setting and focuses the credential field. Turning it off needs the credential set when it was turned on.",
            "開返個設定並將游標放喺憑證欄。想閂返要用開嗰陣設定嘅憑證。"
          ),
          secretInput
        )
      );
    } else {
      rows.push(
        row(
          "enable",
          t("Turn on " + quoted(), "開" + quoted()),
          t(
            "Opens the setting and focuses the name field. Turning it on asks for a name and a credential, and states exactly what stops being offered before it applies.",
            "開返個設定並將游標放喺名稱欄。開之前要改名同設定憑證，亦會講清楚有咩會唔再提供。"
          ),
          nameInput
        )
      );
    }

    rows.push(
      row(
        "rename",
        t("Rename " + quoted(), "改" + quoted() + "個名"),
        t(
          "Opens the setting and focuses the name field. Every label, help line, palette result and message here uses the name you choose.",
          "開返個設定並將游標放喺名稱欄。呢度每個標籤、說明、指令面板結果同訊息都會用你揀嘅名。"
        ),
        nameInput
      )
    );
    return rows;
  });

  // Published before the modules that need to ask, so a cooperating one can
  // check the mode at load instead of painting and being removed afterwards.
  var lockApi = {
    active: locked,
    name: modeName,
    renamed: renamed,
  };
  Site.schoolMode = lockApi;
  Site.modeLock = lockApi;
})();
