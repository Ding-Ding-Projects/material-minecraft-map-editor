# Changelog and offline documentation foundation

## Status and scope

The `amulet_map_editor.api.changelog` module is a wx-independent data
foundation used by the native `ChangelogDialog`. The desktop View menu and
`Ctrl+Shift+F` command palette expose the browser with local filters and
Markdown export. The repository still makes no live wx screenshot claim.

The bundled `changelog_catalog.json` is generated from every release tag whose
peeled commit is reachable from the source revision recorded in that file,
including a tag that points at the source revision itself when that tag already
exists. An automatic release tag created after the source snapshot is absent
from that immutable snapshot and enters the next generated catalog. Each
release entry uses the tag name, tagged commit date, full commit SHA, and
unedited Git commit subject. The catalog therefore does not invent release
prose or claim that a tag-tip subject is a complete set of historical release
notes.

## Behavior

- `load_bundled_catalog()` validates schema version 1 and rejects unknown
  fields, malformed dates, incomplete SHAs, duplicate versions, and invalid
  repository links.
- `filter_changelog()` composes inclusive start/end dates, action categories,
  and text matching. Literal case-insensitive text is the default; a caller may
  inject the project's bounded `RegexBuilder` matcher for explicit regex mode.
- `available_actions()` derives the action-picker values and counts from the
  loaded history instead of maintaining a drifting hard-coded picker.
- `export_markdown()` exports the supplied view, so an already-filtered result
  stays filtered. It retains versions, dates, full commit destinations, and the
  catalog source revision.
- `validate_commit_links()` accepts a resolver hook. Tests use local Git object
  lookup; a future privileged application boundary may supply a bounded forge
  resolver without putting network access in the presentation layer.
- `ChangelogDialog` presents the catalog offline, accepts plain text or explicit
  bounded regex search, pairs typed ISO start/end dates with nullable native
  calendar pickers, reports invalid filters inline, and exports the current
  filtered view through a native file picker.

## Regenerating the catalog

From the repository root, run:

```powershell
py -3 scripts/generate_changelog.py
```

The generator walks tags reachable from `HEAD`, peels annotated tags to
commits, preserves their subjects unchanged, and writes deterministic UTF-8
JSON. Its action categories are intentionally mechanical and documented:

- subjects beginning with add/enable/implement/introduce map to `added`;
- fix/repair/correct map to `fixed`;
- remove/delete/drop/disable map to `removed`; and
- every other subject maps to the neutral `changed` category.

The original subject remains the displayed and exported fact. The category is
only a filter hook.

## Failure modes

- A new tag reachable from the catalog's recorded source revision makes the
  completeness test fail until the catalog is regenerated and reviewed.
- A missing or non-commit object makes commit-link validation fail.
- A newer schema fails closed with `UnsupportedChangelogVersion`; it is not
  silently interpreted as schema 1.
- Invalid date ranges, unknown fields, invalid SHAs, and oversized query or
  summary values raise `ChangelogValidationError`.
- An empty filtered view exports an explicit no-match statement rather than an
  empty document that could be mistaken for a loading failure.

## Security and privacy

Catalog loading and filtering are local and wx-independent. The module performs
no network requests, executes no Git commands, and writes no user data. The
generator is a maintainer tool and invokes Git with argument arrays rather than
a shell. Markdown export escapes Git-authored text before rendering it and
constructs commit links only from validated HTTPS GitHub repository URLs and
full lowercase SHAs.

## Verification

Run the focused suite:

```powershell
py -3 -m unittest -v tests.test_changelog
```

It checks source-snapshot tag completeness, local commit-object resolution,
composed date/action/text filters, bounded regex integration, derived action
counts, Markdown export, explicit empty results, and strict schema rejection.
These are source and unit-test claims only; no wx runtime or screenshot claim
is made.

## Suggested articles

- [Scheduled settings](../scheduled-settings/README.md) — another versioned,
  wx-independent model with strict validation and deterministic precedence.
- [Project documentation](../../../amulet_map_editor/readme.md) — current
  desktop workflows and safety guidance.
- [Modernization roadmap](../../../ROADMAP.md) — distinguishes implemented
  foundations from presentation and runtime work still pending.
