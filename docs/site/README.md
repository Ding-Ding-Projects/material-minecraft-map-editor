# Amulet Map Editor site

This directory is the Material Design 3 landing and documentation source for Amulet Map Editor. It is a dependency-free static site: `index.html`, `styles.css`, and `app.js` are served as-is, with no CDN, tracking, or remote asset dependency.

## Local preview

From the repository root, run a local static server (for example `python -m http.server 8000 --directory docs/site`) and open `http://localhost:8000`. The site has four keyboard-accessible tabs, a feature search field, responsive layouts, focus states, and reduced-motion support.

## Self-hosted publication

This site is designed to be served from an owner-controlled static host. Copy
the complete `docs/site` directory to the web root without rewriting asset
paths, enable HTTPS, and set the repository homepage to the resulting URL.
The repository's Pages workflow is retained only as an optional preview path;
it is not the canonical publication route. The release button intentionally
opens the install guide until a verified immutable installer URL exists.

## Content boundary

The feature inventory links to the repository's source, Releases, Actions, wiki, issues, discussions, and contributing guide. It does not claim capabilities that cannot be verified from this repository. Update the inventory when a feature or supported platform changes.
