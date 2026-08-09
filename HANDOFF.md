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

The latest local correction follows the pinned Squirrel.Windows 2.0.1 command
shape: check output is bounded progress followed by strict final JSON, update
output is bounded progress only, and post-update verification must report the
exact selected installed version with no releases left to apply. Restart uses
the official process-start-and-wait argument and executable basename through a
single generation-guarded, preapproved close transaction with a 500 ms handoff;
failure leaves the ready state intact. Application inventory discovery validates
up to five exact REST pages with per-page and aggregate limits. Workflow delta
selection accepts 500 records plus a 501st truncation sentinel, so a compatible
predecessor after the first 100 releases is no longer hidden. Canonical tags and
unique semantic/package identities are mandatory. This correction remains
local-only until independent review and integration.

Local verification for this correction completed with 338 pytest cases and
439 subtests passing, PowerShell parsing passing, and structural `actionlint`
passing with shellcheck disabled on the Windows host. The two-version Squirrel
smoke produced a 4,999-byte delta with SHA-256
`854744bf8d803014f7efc1b232ab84ec0ca7be8ea5cf2819376434d4efc00cf8`
while retaining one advertised full-package row. The pinned real 2.0.1 CLI
probe exited 0 with three numeric progress lines, CRLF, one terminal newline,
zero blank lines, one release to apply, and zero stderr bytes. Hosted and
installed-client verification remain separate integration gates.

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
