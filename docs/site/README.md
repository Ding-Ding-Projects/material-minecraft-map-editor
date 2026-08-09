# Amulet Map Editor site

This directory is the Material Design 3 landing and documentation source for Amulet Map Editor. It is a dependency-free static site: `index.html`, `styles.css`, and `app.js` are served as-is, with no CDN, tracking, or remote asset dependency.

## Local preview

From the repository root, run a local static server (for example `python -m http.server 8000 --directory docs/site`) and open `http://localhost:8000`. The site has four keyboard-accessible tabs, a feature search field, responsive layouts, focus states, and reduced-motion support.

## GitHub Pages publication

Publish the `docs/site` directory from the repository's Pages settings (Settings → Pages → Deploy from a branch → `main` → `/docs/site`). If a Pages workflow is added later, it must copy this directory unchanged and publish only after the repository's checks pass. The release button intentionally links to the repository Releases page until a verified immutable installer URL exists.

## Content boundary

The feature inventory links to the repository's source, Releases, Actions, wiki, issues, discussions, and contributing guide. It does not claim capabilities that cannot be verified from this repository. Update the inventory when a feature or supported platform changes.
