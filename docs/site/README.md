# Amulet Map Editor site

This directory is the dependency-free Material Design 3 landing page and
documentation source for Amulet Map Editor. It uses only local HTML, CSS,
JavaScript modules, and JSON: no CDN, analytics, tracking, or runtime content
service is required.

## Local preview

From the repository root, use the production-like preview server so JavaScript
modules, including the regex Worker, have the same MIME types and security
headers as the owner-hosted image:

```powershell
py -3 scripts/serve_site_preview.py --port 8000
```

Open `http://127.0.0.1:8000`. The site explicitly documents the `0.10`
development line and has six keyboard-accessible tabs,
roving tab focus, four independently stateful search surfaces with adjacent
full regex builders, responsive layouts, visible focus, reduced-motion
handling, and a command palette on
<kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>F</kbd>.

## Complete on-site feature manual

`scripts/generate_site_articles.py` discovers every
`docs/features/*/README.md` file and writes `articles.json` in stable slug
order. Each record carries the canonical title, summary, Markdown body, source
path, source SHA-256, and two or three valid suggested-article destinations.
The generated catalog currently contains all 18 feature articles. Article
links within that set stay inside this site; no feature card sends the reader
to a repository blob page.

The browser renders the local Markdown through a bounded DOM renderer. It does
not inject source HTML. Fenced code, headings, paragraphs, lists, emphasis,
inline code, HTTPS links, and feature-to-feature links remain readable. A
repository-relative reference that is outside the bundled feature set remains
visible as text instead of becoming a confidently broken link.

Run the freshness gate before packaging:

```powershell
py -3 scripts/generate_site_articles.py --check
```

## Material Design 3 and accessibility

Every card, overlay, field, navigation state, and article surface resolves
through semantic Material Design 3 surface and content roles. Light and dark
themes set the browser `color-scheme` explicitly. The accent picker stores a
seed colour, then derives an accessible primary, on-primary, primary-container,
and on-primary-container role for the active theme. The settings readout reports
the computed primary/surface and on-primary/primary contrast ratios.

The command palette keeps focus in its labelled combobox, exposes the active
option through `aria-activedescendant`, gives the active row a visible state,
and supports arrow/Home/End/Enter operation. Escape or cancel returns focus to
the invoking control. Activating a result instead closes the palette, reveals
the exact destination even when an earlier filter hid it, then focuses its real
page, feature-card control, setting, or article heading. The article catalog
and suggested navigation use real buttons, and all generated destinations are
validated before publication.

The complete site chrome inventory is localized in English and natural Hong
Kong Cantonese: headings, navigation, controls, status/error messages, release
copy, settings, feature cards, article chrome, and accessible names. Bilingual
mode renders separate `lang="en"` and `lang="zh-Hant"` nodes. The two persisted
funny-level controls style complete factual messages independently at every
level. Canonical technical article bodies preserve their reviewed English
source language until reviewed translations exist, and the article surface
discloses that boundary instead of claiming a full body translation.

Each of the four search bars opens its own attached full JavaScript RegExp
builder with guided literals, character classes, anchors, groups, alternation,
quantifiers, raw pattern and flags, bounded sample text, live matches and
capture groups, copy, and JSON export. Plain text stays in-process and is the
default. Explicit regex work runs only in a locally bundled module Worker after
a 120 ms debounce. Each query has generation cancellation and a 900 ms hard
budget that includes Worker startup; timeout terminates that Worker so an
adversarial expression cannot freeze the page or deliver a stale result after
navigation or closure.

## Verified Windows installer

The checked-in release manifest identifies the immutable verified release
`0.10.0-dev.426` at commit
`d47031726b5b1de67ebb9987f211c7d28e6f94c8`. It records exact byte sizes and
SHA-256 digests for `Setup.exe`, `RELEASES`, and
`Amulet-0.10.0-dev426-full.nupkg`. The browser only
reveals `Setup.exe` after the manifest passes its exact tag, commit, name, path,
size, and digest contract. The recorded workflow ran from
`2026-08-09T16:38:49Z` to `2026-08-09T16:42:50Z` (`00:04:01`). Its code name is
`Black Sesame Bao · 芝麻包`, linked to the public catalog photo. These unsigned
Squirrel.Windows assets can trigger the
Windows unknown-publisher warning. This release did not produce a delta
package, and the site does not claim otherwise.

## Owner-controlled Docker deployment

The Docker image uses the multi-architecture `nginx:1.27.4-alpine` base pinned
to OCI index digest
`sha256:4ff102c5d78d254a6f0da062b3cf39eaf07f01eec0927fd21e219d0af8bc0591`;
that index includes `linux/arm64/v8`. Nginx runs as its unprivileged user on
container port `8080`. It serves only the public site files, serves every `.mjs`
module as `application/javascript` under `nosniff`, adds CSP and browser
security headers, and exposes `/healthz`. The image health check verifies the
JSON health response without an external dependency.

The Compose service is read-only, drops all Linux capabilities, disallows new
privileges, bounds processes/CPU/memory, and uses a small writable `/tmp` mount.
It binds to loopback port `8095` by default:

```powershell
Set-Location docs/site
docker compose up -d --build
```

Override the bind address and port without editing the file:

```powershell
$env:AMULET_SITE_BIND = "127.0.0.1"
$env:AMULET_SITE_PORT = "8095"
docker compose up -d --build
```

Put an owner-controlled HTTPS reverse proxy in front of that loopback service.
No public hostname, certificate, DNS record, or live deployment target is
invented or committed here. A healthy container proves the bundle is ready to
serve; it does not prove that a public endpoint exists.

## Sites-compatible deterministic output

The repository root carries a minimal `.openai/hosting.json` with no invented
project identifier and no D1 or R2 requirement. Build the static/Worker output
with:

```powershell
py -3 scripts/build_sites_bundle.py
```

The builder rejects a stale article catalog, validates the site configuration,
release assets, and suggested-article graph. It also refuses to replace an
existing output directory unless that directory carries the builder's ownership
marker, so an accidental `--output` value cannot erase unrelated files. It then
writes:

- `dist/client/` — the exact static site;
- `dist/server/index.js` — an ESM Worker that delegates to the static `ASSETS`
  binding, adds the same security headers, and serves `/healthz`; and
- `dist/build-manifest.json` — deterministic paths, byte sizes, and SHA-256
  digests for every payload file.

That structure is compatible with the Sites packaging helper. Creating a Sites
project and assigning its returned `project_id` remain publication operations;
the source tree does not guess either value.

## Static publication contract

`site-config.json` carries the deployment base URL, release-manifest path, and
article-catalog path. The base defaults to `./`, which works at a domain root or
relative preview. The publication workflow accepts an explicit HTTPS base URL
and writes it into the generated bundle. Absolute values must use HTTPS, end in
`/`, and contain no credentials, query, or fragment.

Both staging builders refuse to replace an existing directory they did not
create. Their small ownership markers make repeat builds deterministic without
turning a mistyped output path into a recursive deletion request.

The `Material 3 site` workflow checks JavaScript syntax, article freshness,
HTML/link/accessibility contracts, computed contrast across representative
accent seeds, the immutable release manifest against GitHub API asset digests
and sizes, and both Docker and Sites-compatible builds. It builds and starts the
actual image, asserts JavaScript MIME, the 18-card catalog, deep article route,
palette, and verified release link, then runs the Chromium focus, visibility,
Worker-timeout, and narrow overflow matrix. A hand-written job/dependency
inventory proves bootstrap coverage. Safe evidence collection runs even after
failure and records the run id, commit SHA, job status, and runner context in a
bounded artifact. The exact static bundle and owner-hosted image are transport
packages, not a claim that a public hostname has been configured.
