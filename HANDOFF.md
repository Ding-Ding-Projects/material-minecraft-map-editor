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
live site hosting remain external verification gates. The tab manager and
element editor are currently the persisted organisation/discovery surface; the
notebook's visual edge/group projection and full Word-depth typography remain
explicit follow-ups. The site remains an incomplete landing shell and has no
claimed public URL until its local article system, settings parity, and an
owner-controlled host are actually verified.

## Release contract repair

The Windows workflow now downloads a prior `RELEASES` index and full package as
one matched pair on pushes and release events. It checks filename, SHA-1, byte
size, NuGet identity, metadata version, and strict version ordering before
Squirrel receives a single-row staging feed. Candidate selection is bounded,
semantic, and channel-specific; downloaded size and GitHub SHA-256 metadata are
validated when available. A selected pair makes the current delta mandatory
and uploads it, while the published index intentionally advertises only the
verified current full package until a three-version installed-client proof
supports delta delivery. Automatic-release
completion still comes from GitHub's post-publication `publishedAt` value.
These delta changes are local source, fixture, and contract-test claims until
the integrated SHA completes its hosted release run.

Automated source tags now resolve to monotonic numeric Squirrel package
versions in reserved patch range `100000..999999`, above legacy stable
`0.10.76`; stable tags in that range and automated runs above `899999` fail
closed. The updater defaults to an explicit automated channel, selects live
inventory numerically, rejects redirected/non-JSON/non-200 inventory responses,
and sends only the exact immutable project release route to the immediate
Squirrel install root. It allows 900 seconds for the observed approximately 87
MiB package plus filesystem staging, preserves the selected version and
matching immutable release-notes URL through the ready state, and exposes that
validated URL from the responsive Material banner. These are local tests until
the integration build and installed-client path are proven.

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
