# Offline documentation browser

The desktop app bundles the feature articles from `docs/features` as a
deterministic UTF-8 resource. The native Documentation entry opens those
articles without network access, so help remains available when a world is
offline or a release host is unreachable.

## Behaviour

- Articles are discovered in stable slug order and each bundle entry carries
  its source path and SHA-256 digest.
- The browser searches titles and Markdown body text with plain text as the
  default. A bounded `RegexBuilder` pattern and flags are opt-in.
- Article links within the feature set resolve to another bundled article and
  stay inside the browser. External links are not fetched by the browser.
- Search results are keyboard-selectable and the article view is scrollable.

## Configuration and failure modes

The bundle is regenerated from the repository root with:

```powershell
py -3 scripts/build_docs_bundle.py
```

The build guard compares every source article's slug and digest with the
bundled resource. A missing, stale, malformed, or unknown article fails closed
with a `DocumentationBundleError`; the app does not silently show an incomplete
help set. Query patterns are bounded by the shared regex builder and invalid
explicit patterns are reported in the search surface.

## Security and privacy

Article content is shipped locally and is not sent to a server. The browser
does not execute Markdown, does not load remote images or scripts, and only
turns validated local article links into internal navigation events. The
documentation model is wx-independent so tests can exercise these boundaries
without opening a window.

## Verification

`tests/test_docs_browser.py` covers deterministic discovery, bundle
completeness, literal and explicit-regex search, internal-link resolution, and
loading without importing wx. These checks prove the data and security
contract; a native runtime screenshot is separate evidence.

### Suggested articles

- [Changelog](../changelog/README.md) — browse every release while offline.
- [Notification centre](../notification-centre/README.md) — review non-blocking
  status messages and export them.
- [Scheduled settings](../scheduled-settings/README.md) — understand persisted
  language and appearance rules.
