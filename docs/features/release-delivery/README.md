# Windows release delivery contract

## Behaviour

Every successful push or manual dispatch builds the Windows application, runs
the release-gating tests, packages an unsigned Squirrel.Windows release, and
publishes one unique non-draft release. The required assets are `Setup.exe`,
`RELEASES`, and the full `.nupkg`; any generated delta package travels beside
them.

Push and release builds search the published release inventory for a prior full
package. A candidate becomes a delta base only after its archive, NuGet package
identity, filename/metadata version agreement, and strictly older version are
validated. If no safe candidate exists, Squirrel produces the required full
release without a delta.

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
- A missing or unsafe prior package skips only delta generation; required full
  assets remain mandatory.
- A missing first-job or publication timestamp fails release-note publication
  instead of inventing a duration.
- Existing immutable asset names are never overwritten.
- An attribution or total arithmetic mismatch makes the committed counter fail.

## Security

Release tokens remain in the workflow credential environment and are never
printed. Event tag data is normalized before it reaches the CLI. Prior packages
must be valid NuGet ZIP archives for the `Amulet` package and strictly older
than the candidate. Executables and DLLs must report `NotSigned`; the workflow
never requests or invokes signing.

## Verification

Run:

```powershell
py -3 -m unittest -v tests.test_windows_workflow_contract tests.test_release_timing tests.test_squirrel_delta_base tests.test_count_lines
actionlint -shellcheck= .github/workflows/build-windows.yml
py -3 scripts/count_lines.py
```

The `actionlint` command above is the structural Windows-host check. The hosted
Linux workflow remains responsible for shellcheck of shell bodies.

## Suggested articles

- [Release code name](../release-code-name/README.md)
- [Updater](../updater/README.md)
- [Build scripts](../build-scripts/README.md)
- [Squirrel packaging](../../../installer/PACKAGING.md)
