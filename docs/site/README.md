# Amulet Map Editor site

This directory is the Material Design 3 landing and documentation source for Amulet Map Editor. It is a dependency-free static site: `index.html`, `styles.css`, and `app.js` are served as-is, with no CDN, tracking, or remote asset dependency.

## Local preview

From the repository root, run a local static server (for example `python -m http.server 8000 --directory docs/site`) and open `http://localhost:8000`. For an owner-controlled deployment, run `docker compose up -d --build` in this directory and place HTTPS in front of port `8080`. The site has four keyboard-accessible tabs, a feature search field, responsive layouts, focus states, and reduced-motion support.

## Self-hosted publication

This site is designed to be served from an owner-controlled static host. Copy
the complete `docs/site` directory to the web root without rewriting asset
paths, enable HTTPS, and set the repository homepage to the resulting URL.
No GitHub Pages workflow is used; the Nginx container and static-copy contract
are the canonical publication routes. The release button intentionally
opens the install guide until a verified immutable installer URL exists.

The `Material 3 site` workflow validates `index.html` and `app.js` on every
branch push and manual dispatch, then publishes a Docker image artifact for an
owner-controlled host. The artifact is a transport package, not proof that a
public hostname has been configured; this repository makes no live-host claim
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

## Content boundary

The feature inventory links to the repository's source, Releases, Actions, wiki, issues, discussions, and contributing guide. It does not claim capabilities that cannot be verified from this repository. Update the inventory when a feature or supported platform changes.
