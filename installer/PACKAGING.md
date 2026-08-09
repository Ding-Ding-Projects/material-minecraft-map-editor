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
packages are emitted when a prior full package is safely available. Push and
manual release runs both search prior published releases, validate the NuGet
archive, package identity, metadata version, and strictly older version before
passing a base to Squirrel. An absent, corrupt, mismatched, or newer package is
skipped without weakening the required full-package contract. CI verifies the
release index and checks every generated executable and DLL with
`Get-AuthenticodeSignature`, which must report `NotSigned`.

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
