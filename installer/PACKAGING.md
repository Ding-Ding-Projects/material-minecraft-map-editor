# Windows packaging contract

The supported Windows release artifact is an **unsigned Squirrel.Windows
release** built from the PyInstaller bundle by `installer/build-squirrel.ps1`.

CI dev builds use a dotted source version such as `0.10.0-dev.154`, but
Squirrel.Windows 2.0.1 reads package metadata with the older NuGet semantic
version parser.  `scripts/normalize_squirrel_version.py` maps that bounded CI
shape to `0.10.0-dev154` before packaging; stable release versions and
single-token prereleases are preserved.  The normalized value is used
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

Candidate discovery reads at most 100 releases and eight semantically ordered
candidates. Each release is limited to 32 assets; `RELEASES` is limited to
256 KiB and the full package to 128 MiB. Archive validation also limits member
count, individual and total extracted sizes, and rejects traversal paths and
symbolic links before Squirrel sees the package.

Run `scripts/smoke_squirrel_delta.ps1` for the disposable two-version fixture.
It requires a generated delta package and exactly one full-package row in the
second release's client-facing `RELEASES`, then removes its bounded temporary
directory.

New automatic releases are assembled as drafts, then published once. The
workflow reads GitHub's resulting `publishedAt` value before calculating the
duration from the first deploy job. Final notes therefore report actual
publication completion rather than a timestamp sampled before the release API
call. The same notes include the committed line counter's generated, excluded,
project-total, repository-grand-total, and surviving agent/person attribution
rows.

The runtime bridge in
`amulet_map_editor/api/framework/squirrel_update.py` validates an HTTPS feed,
reports available/ready/failed/not-installed states, and leaves restart under
explicit user control. It never invokes signing and always exposes the
unsigned-artifact warning.

Code signing is intentionally disabled. Users may see an unknown-publisher or
SmartScreen warning when installing the unsigned artifact.

## Delivery scope

The active release contract is Windows-only. Debian, macOS, Flatpak, and Docker
release workflows are intentionally not shipped from this checkout; their old
workflow files were historical packaging lanes, not supported deliverables.
