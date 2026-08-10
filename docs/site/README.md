# Amulet Map Editor site

This directory is the Material Design 3 landing and documentation source for Amulet Map Editor. It is a dependency-free static site: `index.html`, `styles.css`, and `app.js` are served as-is, with no CDN, tracking, or remote asset dependency.

## Local preview

From the repository root, run a local static server (for example `python -m http.server 8000 --directory docs/site`) and open `http://localhost:8000`. For an owner-controlled deployment, run `docker compose up -d --build` in this directory and place HTTPS in front of port `8080`. The site has four keyboard-accessible tabs, a feature search field, responsive layouts, focus states, and reduced-motion support.

## Owner-controlled static publication

The canonical source is a complete static bundle containing `index.html`,
`styles.css`, `app.js`, `site-config.json`, `release-manifest.json`, and the
`assets/` directory. Copy the bundle to a web root without rewriting asset
paths and enable HTTPS.

Two publication routes share that one bundle, and both build it with
`scripts/prepare_site_bundle.py` so the published files and the archived ones
are the same artifact rather than two that resemble each other:

- **GitHub Pages.** The `Pages` workflow publishes `docs/site` on every push to
  `main` that touches the site or its packaging scripts, and on manual
  dispatch. Every asset reference in the site is relative, so a project-site
  subpath needs no base rewriting and `./` stays correct at any root. The
  deployment is deliberately non-cancelling: a newer push queues behind a
  publish already in flight instead of interrupting it.
- **Owner-controlled static host.** The `Material 3 site` workflow emits the
  exact static bundle and an Nginx image as artifacts for anyone hosting it
  elsewhere. `Dockerfile` and `docker-compose.yml` describe that route and are
  dropped from the Pages bundle, because they are not served content.

`site-config.json` carries the deployment base URL. It defaults to `./`, which
works at a domain root and at a relative static preview. The publication
workflow accepts an explicit HTTPS base URL through its `workflow_dispatch`
input and writes that value into the generated bundle. A base URL must be
root-relative (`./`) or an owner-verified HTTPS URL ending in `/`; it cannot
contain credentials, a query, or a fragment.

`release-manifest.json` decides whether the page offers a download at all. Only
a release whose exact immutable tag, commit, asset URLs, and SHA-256 digests
have been verified may set `verified` to `true`. A verified manifest must
include `Setup.exe`, `RELEASES`, and the full Squirrel package; the browser
rejects URLs with query strings, fragments, credentials, or a non-release path.
Never replace this contract with a guessed or candidate URL.

The checked-in manifest currently records the published `0.10.0-dev.414`
release, whose assets target commit
`f95695f7cbadecd3272370a1fa694e9b601ab124`. Its SHA-256 digests are the ones
GitHub reports for the stored release assets; they have not been recomputed by
downloading each file locally, and that distinction is worth keeping in mind
when the digests are used as evidence.

`tests/test_site_publication_contract.py` enforces the rule in the direction
that matters: an unverified manifest may offer nothing, and a verified one must
name immutable digest-bearing URLs plus a commit that is genuinely an object in
this repository. A well-formed but invented SHA fails the suite.

`scripts/verify_site_offline_assets.py` keeps the bundle dependency-free: no
script, stylesheet, font, or image may be fetched from another origin, so the
page renders identically from a `file://` preview, an air-gapped host, and a
public one. Links the reader clicks are untouched — a link is not an asset.
Both CI workflows run this over the source tree and the built bundle. An
imported design that carries a font CDN link therefore cannot ship as written;
bundle the face locally instead.

The `Material 3 site` workflow validates `index.html`, `app.js`, the settings
and regex-builder accessibility contract, and the release manifest on every
branch push and manual dispatch. It emits both an Nginx image and the exact
static bundle as artifacts. These are transport packages, not proof that a
public hostname has been configured; the repository makes no live-host claim
until an owner supplies and verifies that endpoint.

The feature, settings, and command-palette searches treat ordinary input as
literal text (metacharacters are escaped), cap all patterns at 256 characters,
and reserve JavaScript regular-expression evaluation for the explicit regex
toggle. Primary navigation is a real horizontal tablist with roving focus and
Home/End/arrow-key movement. The command palette is a labelled listbox with
ArrowUp/ArrowDown/Home/End navigation and Enter activation. Language mode
updates the navigation, principal actions, release heading, reset/close actions,
document language, and the settings explanation; bilingual mode keeps both
labels visible while retaining the factual English copy.

All cards, search fields, and dark-mode surfaces resolve through the shared
Material 3 `surface-card` role; theme changes therefore do not leave legacy
white or near-black panels behind. The accent editor keeps its continuous hue
control, HEX/RGB/HSL translators, and live contrast readout.

## Content boundary

The feature inventory links to the repository's source, Releases, Actions, wiki, issues, discussions, and contributing guide. It documents the current Windows-only delivery inventory: the appearance editor, browser-style tabs, safe updater, offline documentation, local history, external editor, optional narrator, Squirrel packaging, and command palette. Update the inventory when a feature or supported platform changes.
