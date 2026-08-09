# Handoff

The default `0.10` jer contains the shared Material 3 wxPython foundation,
persisted preferences and regex builder, non-blocking Squirrel update checks,
the versioned scheduled-settings editor with native date/time pickers,
the searchable local-history browser, persisted tab/group manager, and bounded
per-element appearance editor,
an unsigned Squirrel.Windows packaging workflow, the owned Material 3 site
source, and README screenshot evidence. Local syntax and diff checks pass.
Hosted Windows CI and release publication are proven for earlier integrated
SHAs; the newest workflow may still be running. wxPython runtime capture and
live site hosting remain external verification gates. The tab manager and
element editor are currently the persisted organisation/discovery surface; the
notebook's visual edge/group projection and full Word-depth typography remain
explicit follow-ups. The site is
source-complete but has no claimed public URL until an owner-controlled host is
actually configured.

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
