# Windows packaging contract

The supported Windows release artifact is an **unsigned Squirrel.Windows
release** built from the PyInstaller bundle by `installer/build-squirrel.ps1`.

CI dev builds use a dotted source tag such as `0.10.0-dev.154`, while older
packages used a lexical prerelease such as `0.10.0-dev154`. That lexical form
can rank below the legacy stable `0.10.76`. The public source tag stays dotted,
but `scripts/normalize_squirrel_version.py` maps the bounded automated run to
the monotonic numeric package version `0.10.100154`. Package patches
`100000..999999` are reserved for automated runs `0..899999`; automated source
tags must keep patch zero, and stable tags entering that range fail closed to
prevent a package-identity collision. Stable versions outside that range and
single-token prereleases are preserved. The resolved package value is used
consistently for the package, `RELEASES`, `Setup.exe` directory, and uploaded
asset names.
Each architecture produces `Setup.exe`, `RELEASES`, and a full `.nupkg`; delta
packages are emitted when a prior feed is safely available. Push and manual
release runs choose the nearest semantically older release within the explicit
`automated` or `stable` channel, then download its `RELEASES` and full package
together. The pair
is accepted only when the index has exactly one matching filename whose SHA-1
and byte size match the local package, and the NuGet archive has the `Amulet`
identity, a filename-matched metadata version, and a version strictly older
than the candidate. GitHub asset sizes are checked before and after download,
and SHA-256 digests are verified when GitHub supplies them.
`build-squirrel.ps1` receives both paths and digest metadata, revalidates the
copied pair, and stages a one-row prior index before releasify. Supplying only
half of the pair fails closed.

After releasify, a selected prior pair makes the current delta mandatory. The
script verifies the current full and delta hashes and sizes against Squirrel's
generated entries, removes the prior package input, uploads the generated
delta beside the full package, and rewrites `RELEASES` to contain only the
current full package. The delta is intentionally not advertised to installed
clients until a three-version update proof passes. A release without a feed
pair may be skipped without weakening the first-release full-package contract;
a selected pair with inconsistent metadata or content, or one that produces no
delta, blocks packaging. CI also checks every generated executable and DLL with
`Get-AuthenticodeSignature`, which must report `NotSigned`.

Candidate discovery requests at most 501 releases, using the final record only
as a truncation sentinel for the selector's 500-release and 1 MiB bounds, and
examines at most eight semantically ordered candidates. Canonical tags are
mandatory and semantic-version collisions fail closed. Each release is limited to 32 assets; `RELEASES` is limited to
256 KiB and the full package to 128 MiB. Archive validation also limits member
count, individual and total extracted sizes, and rejects traversal paths and
symbolic links before Squirrel sees the package.

Run `scripts/smoke_squirrel_delta.ps1` for the disposable two-version fixture.
It requires a generated delta package and exactly one full-package row in the
second release's client-facing `RELEASES`, then removes its bounded temporary
directory.
Run `scripts/smoke_squirrel_cli_output.ps1` to exercise the pinned 2.0.1
`--checkForUpdate` executable itself. Its tiny local feed asserts strict
progress plus final-JSON output and reports line endings, terminal newline,
blank lines, versions, release count, and stderr bytes before cleanup.

New automatic releases are assembled as drafts, then published once. The
workflow reads GitHub's resulting `publishedAt` value before calculating the
duration from the first deploy job. Final notes therefore report actual
publication completion rather than a timestamp sampled before the release API
call. The same notes include the committed line counter's generated, excluded,
project-total, repository-grand-total, and surviving agent/person attribution
rows.

The runtime bridge in
`amulet_map_editor/api/framework/squirrel_update.py` validates an HTTPS feed,
but permits only this project's exact immutable release-download route to reach
`Update.exe`. Its exact release-inventory API rejects redirects, non-200
responses, and non-JSON content, and updater discovery does not walk above the
immediate Squirrel install root. The bridge reports
available/ready/failed/not-installed states and leaves restart under explicit
user control. Its five-page REST inventory, stdout, stderr, progress count,
timeout, and response sizes are explicitly bounded. It parses the official
Squirrel 2.0.1 progress-then-JSON check output separately from the progress-only
update output and proves the exact installed version afterward. Restart uses
`--processStartAndWait`, a basename-only target, and one guarded preapproved
close transaction with a 500 ms handoff. It never invokes signing and always
exposes the unsigned-artifact warning.

Code signing is intentionally disabled. Users may see an unknown-publisher or
SmartScreen warning when installing the unsigned artifact.

## Delivery scope

The active release contract is Windows-only. Debian, macOS, Flatpak, and Docker
release workflows are intentionally not shipped from this checkout; their old
workflow files were historical packaging lanes, not supported deliverables.
