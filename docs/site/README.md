# Amulet Map Editor site

This directory is the dependency-free Material Design 3 landing page and
documentation source for Amulet Map Editor. It uses only local HTML, CSS,
JavaScript modules, and JSON: no CDN, analytics, tracking, or runtime content
service is required.

## Local preview

From the repository root, serve `docs/site` with a static server, for example:

```powershell
py -3 -m http.server 8000 --directory docs/site
```

Open `http://127.0.0.1:8000`. The site explicitly documents the `0.10`
development line and has six keyboard-accessible tabs,
roving tab focus, four bounded search surfaces with adjacent regex builders,
responsive layouts, visible focus, reduced-motion handling, and a command
palette on <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>F</kbd>.

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
supports arrow/Home/End/Enter operation, and returns focus to the invoking
control when it closes. The article catalog and suggested navigation use real
buttons, and all generated destinations are validated before publication.

Language and funny-level preferences are deliberately honest about their
current boundary: they style the site shell, navigation, actions, and optional
microcopy. Canonical technical article bodies preserve their reviewed source
language until a reviewed translation exists; selecting a shell language does
not pretend those articles were translated.

## Verified Windows installer

The checked-in release manifest identifies the immutable verified release
`0.10.0-dev.424` at commit
`d86e73a2f0746012158cd49774e36887ec92a01d`. It records exact byte sizes and
SHA-256 digests for `Setup.exe`, `RELEASES`, and
`Amulet-0.10.0-dev424-full.nupkg`. The browser only
reveals `Setup.exe` after the manifest passes its exact tag, commit, name, path,
size, and digest contract. The recorded workflow ran from
`2026-08-09T16:16:18Z` to `2026-08-09T16:20:24Z` (`00:04:06`). These unsigned
Squirrel.Windows assets can trigger the
Windows unknown-publisher warning. This release did not produce a delta
package, and the site does not claim otherwise.

## Owner-controlled Docker deployment

The Docker image uses the multi-architecture `nginx:1.27.4-alpine` base pinned
to OCI index digest
`sha256:4ff102c5d78d254a6f0da062b3cf39eaf07f01eec0927fd21e219d0af8bc0591`;
that index includes `linux/arm64/v8`. Nginx runs as its unprivileged user on
container port `8080`. It serves only the public site files, adds CSP and browser
security headers, and exposes `/healthz`. The image health check verifies the JSON health response without an
external dependency.

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
accent seeds, the immutable release manifest, and both Docker and
Sites-compatible builds. It emits the exact static bundle and owner-hosted
image as artifacts. Those transport packages are not a claim that a public
hostname has been configured.
