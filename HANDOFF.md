# Handoff

The integration branch contains the shared Material 3 wxPython foundation,
persisted preferences and regex builder, non-blocking Squirrel update checks,
the versioned scheduled-settings editor with native date/time pickers,
the searchable local-history browser, persisted tab/group manager, and bounded
per-element appearance editor,
an unsigned Squirrel.Windows packaging workflow, the owned Material 3 site
source, and README screenshot evidence. The main shell now uses compact
owner-drawn caption controls, an app-owned command bar, a single responsive
start card, and an immediately usable startup path with no acknowledgement or
purchase gate. Local syntax and diff checks pass.
Hosted Windows CI and release publication are proven for earlier integrated
SHAs; the newest workflow may still be running. wxPython runtime capture and
live site publication remain external verification gates. The tab manager and
element editor are currently the persisted organisation/discovery surface; the
notebook's visual edge/group projection and full Word-depth typography remain
explicit follow-ups. The site source is now a complete, dependency-free landing
page and feature manual with 18 reviewed English/Cantonese articles, localized
controls, deterministic Docker and Sites staging, and loopback HTTP/Chromium
proof. It still has no claimed public URL because no owner-controlled hostname,
HTTPS route, or authenticated Sites project has been supplied.

## Exact post-release site staging

`Build Windows` now publishes a tiny API-verified handoff after each successful
default-branch push release. The read-only `Material 3 site` workflow consumes
that exact run artifact through `workflow_run`, checks out its head SHA,
validates the non-draft release and every asset digest/size against a fresh API
response, and writes the release manifest only into ephemeral staging. It
serializes without cancellation, rejects older successful runs, rechecks the
newest run before archiving, and never commits repository source or deploys a
host. The owner archive and Sites archive carry `site-staging.json`; a separate
Sites source repository or owner-host promotion must recheck that run before
publication. This avoids the release-manifest commit loop.

The source and loopback runtime gates cover all 54 article/language route
combinations, 12 narrow viewport/scale/device-pixel-ratio combinations, the
four palette destination kinds, regex timeout cancellation, JavaScript/Worker
MIME, deep-route fallback, and verified/unverified release visibility. Docker
was installed locally but its daemon was unavailable, so an actual image build
is deliberately left to the pinned fresh-environment CI path rather than being
claimed from static inspection.

## Release contract repair

The Windows workflow now searches safe prior full packages on pushes as well as
release events, validates delta bases before Squirrel receives them, and derives
automatic-release completion from GitHub's post-publication `publishedAt`
value. `scripts/count_lines.py` reports explicit generated and excluded rows,
project and repository totals, and internally checked surviving agent/person/
unattributed attribution. These are local source and contract-test claims until
the integration SHA completes its hosted release run.

## Offline documentation browser

The offline-docs integration commit adds a deterministic bundle generated from every
`docs/features/*/README.md` article. `amulet_map_editor.api.docs_browser` loads
the strict JSON resource without importing wx, provides literal-first search
with explicit bounded regex mode, and resolves internal article links locally.
`DocumentationDialog` is exposed from the View menu and command palette; it
renders only the bundled Markdown subset and never fetches remote content.
`tests/test_docs_browser.py` proves completeness, search, link resolution, and
wx-independent loading. Record the final integrated SHA here when this lane
lands.
