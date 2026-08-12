# The Python sidecar

The migration plan's Phase 2 is "a process boundary, not a rewrite": the
Python core keeps running exactly as it does in the wx application, but as a
child process an Electron main process (or any other host) supervises and
talks to over stdin/stdout. This article documents that boundary --
`amulet_map_editor/api/sidecar/`.

## Why a process boundary instead of a rewrite

`docs/site/` is already a complete Material 3 renderer. The migration is
about giving it real data, not drawing an interface a second time. The
cheapest way to reuse the Python core untouched is to run it as a separate
process and speak a small protocol to it -- the same pattern this repository
already uses for the converter's own sandbox
(`amulet_map_editor/api/converter/sandbox.py`), which spawns a bounded child
process to run one adapter call. The sidecar is that idea applied to the
whole core rather than to one conversion.

## The wire protocol

One line of UTF-8 JSON in on stdin, one line of UTF-8 JSON out on stdout.
Nothing else may share stdout -- a stray `print()` anywhere in a handler
would corrupt the line-delimited stream a host is reading, so unexpected
output goes to stderr instead (see `server.dispatch`).

A **request**:

```json
{"id": 7, "method": "preferences.read", "params": {}, "protocol_version": 1}
```

A successful **response**:

```json
{"id": 7, "protocol_version": 1, "result": {"display_name": "Amulet", "...": "..."}}
```

An **error response** -- structured, never a bare string and never a raw
Python traceback:

```json
{"id": 7, "protocol_version": 1, "error": {"code": "unknown_method", "message": "No such method: 'not.a.method'"}}
```

Error codes: `invalid_message`, `message_too_large`, `version_mismatch`,
`unknown_method`, `invalid_params`, `timeout`, `internal_error`. A caller can
branch on the code without parsing the (English-only, deliberately internal)
message text.

## Versioning

Every request and response carries `protocol_version`. The sidecar reports
`version_mismatch` rather than guessing when a caller's version differs from
`amulet_map_editor.api.sidecar.protocol.PROTOCOL_VERSION`; bump that constant
on any breaking change to the shape of a request or response.

## Bounds

- **Message size**: a line over `MAX_MESSAGE_BYTES` (8 MiB) is rejected
  before it is ever handed to `json.loads`, so an oversized or hostile line
  cannot force an unbounded parse.
- **Per-request timeout**: each handler runs on a daemon thread the
  dispatcher joins with a timeout (`DEFAULT_TIMEOUT_SECONDS`, 10s by
  default). A handler that does not finish in time is reported as `timeout`;
  the sidecar itself keeps serving later requests rather than hanging.

## The method catalog

Only real methods, over real implementations already exercised by the wx
application:

| Method | Backs onto |
| --- | --- |
| `protocol.ping` | a cheap liveness check |
| `preferences.read` | `amulet_map_editor.api.preferences.load()` |
| `preferences.write` | `amulet_map_editor.api.preferences.update(**params)`, allowlisted field-by-field |
| `language.get` / `language.set` / `language.list` | `amulet_map_editor.api.lang` |
| `converter.formats` | `amulet_map_editor.api.converter.registry.ADAPTERS` |
| `changelog.entries` | `amulet_map_editor.api.changelog.load_bundled_catalog()`, optionally filtered by `start_date`/`end_date`/`actions`/`text` through `ChangelogQuery` |
| `docs.articles` | `amulet_map_editor.api.docs_browser.load_bundled_articles()`, all articles or one by `slug` |
| `dimsum.draw` | `amulet_map_editor.api.dim_sum_surprise` -- the real `should_show()` 10% gate and the real public-catalog fetch, honoured exactly (never reimplemented in JavaScript) |
| `world.open` / `world.open_status` / `world.dimensions` / `world.close` / `recents.list` | real, read-only world access -- see `docs/features/electron-world-access/README.md` |

### `language.*` and the site's three language modes

`language.get`/`set`/`list` are honest about a real mismatch: `lang.py` deals
in RFC 1766 language IDs (`en`, `zh-Hant`, whatever `.lang` files exist on
disk), while `docs/site/`'s own `Site.settings` language concept is the
three fixed modes these shared instructions require everywhere --
`english`, `cantonese`, `bilingual`. Those are not the same axis: the
site's mode is "which of three voices renders", while `lang.py`'s ID is
"which translated string table is active". `electron-bridge.js` maps the
sidecar's `language_mode` *preference* field (a site-shaped three-mode
value stored via `preferences.write`) onto the site's `language` setting
the same way it maps every other preference; it deliberately does not
attempt to collapse `lang.py`'s open-ended language ID list into the
site's three-mode control, because doing so would either invent a mapping
the wx application does not have or silently drop every non-English,
non-Cantonese `.lang` file the desktop app ships.

### `changelog.entries` and `docs.articles` in the renderer

`electron-bridge.js` fetches both once at startup (alongside
`converter.formats`) and publishes the real results on
`Site.electronSidecar.changelogEntries` / `.docsArticles`. For the
changelog specifically, the bridge also overwrites `window.AMULET_CHANGELOG`
with the sidecar's real catalog in the exact shape `docs/site/changelog.js`'s
own `catalogueSource()` already reads (`repository_url`, `source_revision`,
`entries[]`), so the real commit-linked catalog -- not the one
`changelog-data.js` bundles for the standalone GitHub Pages site -- is what
a consuming surface sees once the fetch has landed. `dimsum.draw` is
exposed as a callable, `Site.electronSidecar.drawDimSum(languageMode)`,
returning the sidecar's own three-way honest status (`not_drawn` -- the
10% draw did not win; `unavailable` -- it won but the public catalog could
not be reached; `ready` -- a real dish). None of the three overrides the
plain-browser build's existing bundled behaviour: every bridge call is
skipped outright when `window.mmweDesktop.sidecar` is absent, exactly as
the other preference wiring already does.

`preferences.write` only accepts the fields listed in
`methods._WRITABLE_PREFERENCE_FIELDS` -- a new preference field is opt-in to
remote mutation, never automatically exposed the day it is added. An unknown
field, or a value `Preferences.normalised()` cannot make sense of, is
reported as `invalid_params` rather than silently discarded (a genuinely
out-of-range value such as an unrecognised theme name is *normalised*, the
same as it would be for a directly-edited profile file, and the response
reports the normalised value rather than erroring).

## What the sidecar does not expose, and why

The authenticator (`amulet_map_editor.api.authenticator`) and the forge/OAuth
account store both keep their secrets in the OS credential vault. Neither is
on the method table above: the shared instructions are explicit that a
secret must never cross a file, a log, or -- new here -- a pipe without a
lane deliberately built and tested for exactly that. Giving those their own
bounded, tested sidecar methods is later work for whichever lane owns those
surfaces, not something this protocol lane should improvise.

## Running it

```
python -m amulet_map_editor.api.sidecar
```

reads requests from stdin and writes responses to stdout until stdin closes.
`amulet_map_editor.api.sidecar.server.main()` wraps the process's raw stdio
in UTF-8, `\n`-normalised text streams itself, rather than trusting the host
platform's console code page -- Windows in particular can default a child
process's stdio to a legacy code page that would mangle Cantonese copy or a
non-ASCII display name on the way through.

## Testing

`tests/test_sidecar_protocol.py` spawns the real child process with
`subprocess.Popen` and talks to it over its actual pipes, rather than calling
`server.dispatch` in-process -- an in-process call proves the handler logic
and nothing about the boundary itself (the newline framing, the UTF-8 round
trip, a genuinely separate process actually enforcing the timeout). It
covers: a normal round trip, an unknown method, a version mismatch, malformed
JSON, an oversized message, preferences read/write and normalisation, the
writable-field allowlist, language get/set/list, the converter format list,
the changelog catalog (including its date/action/text filtering and its
`invalid_params` reporting for a malformed date), the docs article bundle
(including fetching a single article by `slug` and rejecting an unknown
one), the dim-sum draw's real status contract, and a guard that nothing
this lane's methods touch ever writes a secret-shaped word to stdout or
stderr.

`tests/test_electron_sidecar_bridge.py` adds static wiring guards proving
`electron-bridge.js` carries a real `bridge.call(...)` site for each of
`changelog.entries`, `docs.articles` and `dimsum.draw`, and that the
changelog call site actually overwrites `window.AMULET_CHANGELOG` rather
than merely stashing the response somewhere unused.
`scripts/capture_electron_sidecar_roundtrip.js` drives all three against the
real built Electron shell: a direct sidecar call for each, plus a check
that `Site.electronSidecar`'s published values (and, for the changelog,
`window.AMULET_CHANGELOG` itself) match what the direct call returned --
proving the renderer's state came from the real Python catalog, not the
site-bundled one.

## Related reading

- [The core/wx boundary](../core-boundary/README.md) -- the hand-written list
  of modules the sidecar is allowed to import
- [File converter](../file-converter/README.md) -- the sandboxed
  child-process pattern the sidecar's own process boundary is modelled on
