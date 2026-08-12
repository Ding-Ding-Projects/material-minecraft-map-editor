# The GitHub Pages site

The published site in `docs/site/` is a user-facing surface, so it carries the
universal feature contracts rather than treating itself as "only docs". This
article records what it implements, how that is verified, and the one contract
that genuinely cannot apply to a static page.

## What the site implements

Every one of these is a working surface, not a description of one:

| Contract | Where |
| --- | --- |
| Three language modes, two funny-level sliders, emoji switch | `site-core.js`, `settings-panel.js` |
| Browser-style tabs: docking, overflow, reorder, pin, group, four searches, bulk close | `tabs.js` |
| Search everywhere, each with its own anchored regex builder | `regex-builder.js` and every panel |
| Command palette on `Ctrl+Shift+F` | `palette.js` |
| Non-blocking notifications with a reviewable centre | `notifications.js` |
| Local version history | `history.js` |
| Changelog viewer with date filter and commit links | `changelog.js`, `changelog-data.js` |
| Exports in several formats | `exporters.js` |
| Bulk actions on every list | `bulk-actions.js` |
| School mode | `school-mode.js` |
| Dim sum surprise | `dimsum.js` |
| Resizable and draggable panels | `panel-resize.js` |
| Destructive-action super confirmation: two keys, then a slider | `confirm-gate.js` |
| Two-factor authenticator, locally drawn QR, RFC 6238 codes | `authenticator.js`, `totp.js`, `qr.js` |
| Locked tabs and locked appearance values, each with its own credential | `locks.js` |
| Support Tickets recovery desk | `support-tickets.js` |
| Scheduled settings with an override layer | `scheduled-settings.js` |
| Appearance presets, saved themes, export and import | `appearance-presets.js` |

## Where the site's storage differs from the desktop app

The desktop contracts assume an operating-system credential vault and an
application-data directory. A web page has neither, and pretending otherwise
would be the more comfortable lie.

- Authenticator secrets and lock credentials live in this browser's local
  storage, in the clear. Every surface that stores one says so in plain words.
- The reset route is "clear this site's stored data", named on the surfaces
  that need it and offered through the Support Tickets desk.
- Locks are explicitly a for-fun speed bump. They are never described as
  security, and never as encryption.

## The one contract that cannot apply

**External editor integration** (`docs/features/external-editor/README.md`) does
not apply to the published site. That contract is for an app that owns files or
projects on disk and can hand one to a locally installed editor. A static page
owns no files: its exports are downloads that land wherever the browser puts
them, and a page cannot launch a local process. The site therefore implements
the half that is meaningful — every surface that renders data can export it —
and does not ship a button that would be guaranteed to fail.

Nothing else in the universal contracts is skipped. Where a desktop mechanism
has no web equivalent, the site ships the closest honest thing and says which
mechanism it is standing in for.

## Verification

Source-text guards check structure:

```powershell
py -3 -m pytest tests/test_site_publication_contract.py tests/test_site_offline_assets_contract.py tests/test_site_m3_surface_tokens_contract.py tests/test_site_palette_inventory_contract.py
```

Those cannot see a module that throws on load and leaves its surface blank, so
two further suites execute the real page and check behaviour:

```powershell
py -3 -m pytest tests/test_site_totp_contract.py tests/test_site_runtime_render_contract.py
```

`test_site_runtime_render_contract.py` loads `index.html` in a DOM, runs every
script in document order, and asserts behaviour rather than appearance: that a
lock rejects the wrong password, that an unlock grant expires, that the
destructive gate needs both keys and a full slider, that a scheduled override
never becomes the user's stored value, and that a window crossing midnight
matches on both sides of it. Each of those has been broken on purpose and
watched go red; a guard nobody has seen fail proves nothing.

The runtime suite needs Node and jsdom, declared in `docs/site/package.json` as
a test-only dependency:

```powershell
cd docs/site; npm install
```

The published site itself bundles nothing at all. Every script is a classic
browser script that runs from a `file://` preview with no install, no module
graph, no CDN, and no network request of any kind.

## Failure modes

- A newer stored schema for schedules or an imported appearance file fails
  closed and says so, rather than being read as the current version.
- An imported appearance file that sets keys nothing reads applies the rest and
  reports the ignored keys instead of dropping them silently.
- A schedule whose start equals its end is a zero-length window and never
  applies, so a mistyped pair does nothing rather than owning the whole day.
- Where the browser has no QR reader or no camera, scanning says so plainly and
  the paste-a-URI route remains.

## Suggested articles

- [Destructive gate](../destructive-gate/README.md) — the two-key confirmation
  this site shares with the desktop app.
- [Appearance presets](../appearance-presets/README.md) — the preset contract
  these surfaces implement.
- [Language modes](../language-modes/README.md) — the three modes and both
  funny-level controls.
- [External editor](../external-editor/README.md) — the contract this surface
  documents as not applicable, and why.
