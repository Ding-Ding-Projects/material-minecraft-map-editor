# Windows release delivery contract

## Behaviour

Every successful push or manual dispatch builds the Windows application, runs
the release-gating tests, packages an unsigned Squirrel.Windows release, and
publishes one unique non-draft release. The required assets are `Setup.exe`,
`RELEASES`, and the full `.nupkg`; any generated delta package travels beside
them.

Automated public tags retain the readable `0.10.0-dev.<run>` form, while the
Squirrel package version uses the reserved numeric patch range
`100000..999999`: automated run `0` maps to patch `100000`, and the maximum run
`899999` maps to patch `999999`. This ranks every current automated package
above the legacy stable `0.10.76` and removes lexical prerelease ordering from
installed-client comparisons. Automated source tags must keep patch zero;
stable source tags that enter the reserved range fail closed so their package
identity cannot collide with an automated build.
Only canonical `major.minor.patch` and `major.minor.0-dev.run` tags may enter
packaging or publication. Push fallback, optional manual-dispatch input, and
release-event tags use the same validator. Publication repeats the validation
against the deploy job's exact canonical source tag and numeric package version,
so an alias or collision cannot label assets that installed clients reject.

Push and release builds request a bounded 501-entry inventory: 500 selectable
records plus one truncation sentinel. The selector accepts at most 500 entries
and 1 MiB, then considers at most eight candidates from the build's explicit `automated` or `stable`
channel, ordered by semantic version rather than publication time. A candidate
becomes a delta base only when its `RELEASES` index
contains exactly one row matching the downloaded full package's filename,
SHA-1, and byte size, and the package is a valid `Amulet` NuGet archive with a
strictly older, filename-matched metadata version. The validator writes a
single-row staging index so stale rows cannot make Squirrel select an asset
that was not downloaded. If no safe pair exists, Squirrel produces the
required full release without a delta.

When a pair is selected, packaging fails unless Squirrel emits the current
delta package. Both current packages are verified against Squirrel's generated
hash and size entries and are uploaded as release assets. The client-facing
`RELEASES` feed deliberately contains only the current full package until a
three-version installed-client update proof establishes that the delta path is
safe. The prior package and historical rows remain build inputs only.

Automatic publication starts as a draft carrying the recursion marker, then is
published exactly once. The workflow reads the resulting `publishedAt`
timestamp and calculates elapsed time from the first deploy job. Final notes
include that verified interval and the committed line-count table.

## Configuration

The workflow lives at `.github/workflows/build-windows.yml`. Release API calls
use `RELEASE_TOKEN`, then `ORG_TOKEN`, then the workflow token. Packaging stays
Windows-only and code signing stays disabled. `scripts/count_lines.py` counts
tracked line-oriented text and reports hand-written project rows, generated and
excluded rows, project and repository totals, and surviving agent/person/
unattributed `git blame` lines.

## Failure modes

- A failed test or package build prevents publication.
- A release without a Squirrel pair is not compatible and the next semantically
  older release in the same explicit channel is considered.
- A selected pair with mismatched names, versions, hashes, sizes, index rows, or
  asset metadata fails closed instead of falling back to a less trustworthy
  candidate.
- A stable tag in patch range `100000..999999`, an automated tag with a nonzero
  source patch, or an automated run above `899999` fails closed.
- A noncanonical build, manual, or release-event tag alias; a source/package
  identity mismatch; a repeated semantic version; or inventory beyond the
  500-record selector ceiling fails closed.
- Once a safe pair is selected, a missing current delta, hash/size mismatch, or
  delta row in the client feed fails packaging.
- A missing first-job or publication timestamp fails release-note publication
  instead of inventing a duration.
- Existing immutable asset names are never overwritten.
- An attribution or total arithmetic mismatch makes the committed counter fail.

## Security

Release tokens remain in the workflow credential environment and are never
printed. Event and manual tag data is strictly validated before it reaches the
CLI. Each inspected
release is limited to 32 assets. Prior indexes are limited to 256 KiB; prior
package downloads are limited to 128 MiB, 20,000 archive members, 512 MiB per
member, and 1 GiB extracted content. The workflow validates GitHub's SHA-256
asset digest when the API supplies it, then validates the strict UTF-8 index,
local basename, SHA-1, byte size, NuGet identity, metadata version, archive
paths, and semantic ordering. Executables and DLLs must report `NotSigned`;
the workflow never requests or invokes signing.

## Verification

Run:

```powershell
py -3 -m unittest -v tests.test_windows_workflow_contract tests.test_release_timing tests.test_squirrel_delta_base tests.test_squirrel_delta_selection tests.test_count_lines
actionlint -shellcheck= .github/workflows/build-windows.yml
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/smoke_squirrel_delta.ps1
py -3 scripts/count_lines.py
```

The `actionlint` command above is the structural Windows-host check. The hosted
Linux workflow remains responsible for shellcheck of shell bodies.

## Suggested articles

- [Release code name](../release-code-name/README.md)
- [Updater](../updater/README.md)
- [Build scripts](../build-scripts/README.md)
- [Squirrel packaging](../../../installer/PACKAGING.md)
