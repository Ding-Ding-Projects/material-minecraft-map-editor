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
order. Each record carries reviewed English and Hong Kong Cantonese titles,
summaries, and Markdown bodies; both source paths and SHA-256 digests; and two
or three valid suggested-article destinations.
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

The complete site and article inventory is localized in English and natural
Hong Kong Cantonese: headings, navigation, controls, status/error messages,
release copy, settings, feature cards, full article bodies, suggested links,
article chrome, and accessible names. Bilingual mode renders separate
`lang="en"` and `lang="zh-Hant"` article sections while retaining one semantic
article title and one accessible control per action. The generator fails when
any of the 18 routes lacks either language or when a translation changes a
fenced code block, inline technical token, or link destination. The two
persisted funny-level controls style complete factual shell messages
independently at every level.

Each of the four search bars opens its own attached full JavaScript RegExp
builder with guided literals, character classes, anchors, groups, alternation,
quantifiers, raw pattern and flags, bounded sample text, live matches and
capture groups, copy, and JSON export. Plain text stays in-process and is the
default. Explicit regex work runs only in a locally bundled module Worker after
a 120 ms debounce. Each query has generation cancellation and a 900 ms hard
budget that includes Worker startup; timeout terminates that Worker so an
adversarial expression cannot freeze the page or deliver a stale result after
navigation or closure.

## Verified Windows installer source snapshot

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
package, and the checked-in source snapshot does not claim otherwise. It is a
reproducible validation fixture, not a promise that `0.10.0-dev.426` remains
the newest release after another source change.

## Exact post-release staging

`Build Windows` publishes a tiny `site-release-handoff.json` artifact only
after the release is non-draft and its API tag, target commit, immutable URLs,
byte sizes, and SHA-256 digests match the locally built artifacts. The
`Material 3 site` workflow listens for the completed build through
`workflow_run`. It accepts only a successful `push` run from this repository
whose head branch is the repository's current default branch, downloads the
handoff by the triggering run id, checks out the exact head SHA without stored
write credentials, and compares the handoff with a fresh release API response.

The post-release job serializes without cancellation. It treats an older
successful run as an explicit no-op, checks the newest successful build again
after HTTP and Chromium verification, and refuses to archive an out-of-order
result. Validation writes only to `build/` through atomic file replacement;
the workflow has read-only repository permissions and contains no commit,
push, release, deployment, or host-mutation command. A failed run therefore
cannot replace a previously deployed site.

The resulting owner-hosted image, static archive, and Sites-compatible archive
all include `site-staging.json` with the exact source SHA, release tag, release
id, and Build Windows run id. A deployment must recheck that run against the
newest successful default-branch build before promotion. This avoids a source
commit solely to refresh the release manifest, which would otherwise create
another release and repeat the same race forever.

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

The builder accepts `--site` for an already validated ephemeral staging tree.
It rejects a stale article catalog, validates the site configuration,
release assets, and suggested-article graph. It also refuses to replace an
existing output directory unless that directory carries the builder's ownership
marker, so an accidental `--output` value cannot erase unrelated files. It then
writes:

- `dist/client/` — the exact static site;
- `dist/server/index.js` — an ESM Worker that delegates to the static `ASSETS`
  binding, adds the same security headers, and serves `/healthz`; and
- `dist/build-manifest.json` — deterministic paths, byte sizes, and SHA-256
  digests for every payload file.

That structure is compatible with the Sites packaging helper. The archive must
be committed to the separately controlled Sites source repository at the
staging SHA before publication; it must not be committed back into this source
repository. Creating a Sites project, assigning its returned `project_id`, and
promoting the archive remain publication operations; this source tree does not
guess any of those values.

## Static publication contract

`site-config.json` carries the deployment base URL, release-manifest path, and
article-catalog path. The base defaults to `./`, which works at a domain root or
relative preview. The publication workflow accepts an explicit HTTPS base URL
and writes it into the generated bundle. Absolute values must use HTTPS, end in
`/`, and contain no credentials, query, or fragment.

Both staging builders refuse to replace an existing directory they did not
create. Their small ownership markers make repeat builds deterministic without
turning a mistyped output path into a recursive deletion request.

The `Material 3 site` workflow checks JavaScript syntax, bilingual article
freshness, HTML/link/accessibility contracts, computed contrast across
representative accent seeds, the exact staged manifest against live release API
asset digests and sizes, and both Docker and Sites-compatible builds. It builds
and starts the actual image, asserts JavaScript MIME, the 18-card catalog, deep
article route, palette, and parameterized verified release link, then runs the
Chromium focus, visibility, Worker-timeout, and narrow overflow matrix with a
small device-pixel-ratio tolerance for CDP fractional noise. The runtime job
bootstraps pinned Chrome for Testing 151.0.7922.47, Docker Engine 29.6.2, and
Buildx 0.36.1 from versioned upstream paths instead of trusting the runner
image. A hand-written two-job dependency inventory proves cache-miss coverage.
Safe evidence collection runs even after failure and records the run id, commit
SHA, job status, and runner context in a bounded artifact. The exact static
bundle and owner-hosted image are transport packages, not a claim that a public
hostname has been configured.
