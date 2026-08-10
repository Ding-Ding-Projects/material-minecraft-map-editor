# Unsigned Squirrel updates

The Windows app checks the project's exact immutable HTTPS Squirrel feed after startup and on
a bounded six-hour timer. The default `automated` channel selects the highest
numeric `dev` sequence without mixing in stable releases or trusting publish
order. A non-blocking Material 3 banner reports available, ready, failed, and
current states. It carries the exact version and a validated immutable
**Release notes** action through staging. Staging validates feed metadata and
package hashes; installation occurs only after the user chooses **Restart to
install update**. **Later** hides the banner without discarding the staged
state.

## Configuration and failure modes

The feed resolver reads a bounded GitHub release inventory and defaults to the
explicit `automated` channel. Automated package versions use a numeric patch
in the reserved `100000..999999` range, so they rank above the legacy stable
`0.10.76` without asking Squirrel to compare build numbers lexically. Automated
source tags must use patch zero and runs `0..899999`; stable source tags must
stay outside the reserved patch range. The selected release-download route and
release-notes URL must both match the project's immutable GitHub paths and tag.
Tags are accepted only in their canonical forms: `major.minor.patch` for stable
releases and `major.minor.0-dev.run` for automated releases. Prefix, separator,
case, whitespace, and leading-zero aliases are rejected, as are duplicate tags
or version/package-identity collisions. The build normalizer, manual workflow
input, release-event tag, and final publisher all enforce that same contract;
the publisher also requires the tag to reproduce the exact built source and
numeric package identities.

The complete apply-plus-post-check transaction has one documented 900-second
monotonic deadline, sized for the observed approximately 87 MiB full package
plus local filesystem work. The update check likewise gives all REST inventory
pages and the CLI check one shared caller-supplied deadline. Each next operation
receives only the remaining time and fails before starting when none remains,
so pagination or verification cannot multiply the configured budget. Invalid URLs,
offline responses, malformed metadata, hash mismatches, cancellation, timeout,
or unsaved work produce a recoverable failed state and never interrupt active
editing. The app never invokes a signer and every published Windows artifact is
explicitly unsigned.

The process bridge follows the output shape in Squirrel.Windows 2.0.1 source
commit [`eef37460`](https://github.com/Squirrel/Squirrel.Windows/commit/eef37460aef77b2f9de8cd2237c1e55b344a6554).
`--checkForUpdate` may emit zero or more bounded integer progress lines from 0
through 100, followed by one strict JSON line containing exactly `currentVersion`,
`futureVersion`, and `releasesToApply`. An update is available only when that
array is nonempty; an empty array is valid only when current and future versions
are equal. CRLF, LF, and lone CR are the only record separators, so valid raw
NEL or Unicode line-separator characters inside JSON release notes are retained
as content. `--update` may emit progress lines only; its exit code is the
result. A second check must then report no remaining releases, equal current and
future versions, and the exact version selected before the download. Each child
stream is limited to 64 KiB and each result to 4,096 progress lines.

## Security and accessibility

Only `https://github.com/Ding-Ding-Projects/material-minecraft-map-editor/releases/download/<validated-tag>/`
may reach `Update.exe`; generic GitHub, raw-content, API, latest-release, other
owner, and other repository paths are rejected. The inventory resolver uses
only its exact API route, requires HTTP 200 JSON, and rejects redirects on every
page before parsing. It reads at most five 100-item pages, 1 MiB per page and
5 MiB in aggregate, and fails if the fifth page is full rather than silently
truncating the inventory. Release notes must be the matching exact HTTPS project release route
with no query, fragment, credentials, or custom port, and the UI revalidates it
before opening the browser. Updater discovery accepts only the expected
`Update.exe` beside an immediate Squirrel `app-<version>` directory and never
walks arbitrary ancestors. Package hashes are checked before staging. Restart
uses Squirrel's official `--processStartAndWait` command with the installed
executable basename. One generation-guarded close transaction asks every open
page once, preserves the ready state if launch or close fails, and waits 500 ms
for the updater handoff before exiting. If `Update.exe` exits during that
window, the app cancels the preapproval, keeps the ready banner, reports the
exit code, and does not close. The responsive banner stacks its
message above keyboard-operable Material actions, is localized, remains
persistent until dismissed, and records deduplicated history entries.

## Verification

Run `python -m pytest -q tests/test_squirrel_version.py tests/test_updater_banner_contract.py tests/test_updater_surface_contract.py tests/api/framework/test_squirrel_update.py tests/api/framework/test_update_copy.py`.
Then run
`pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/smoke_squirrel_cli_output.ps1`.
The pinned real-CLI fixture verifies the actual 2.0.1 shape and reports its
progress-line count, line ending, terminal-newline state, blank-line count,
versions, release count, and stderr byte count before deleting its bounded
application-data fixture. `-LifecycleSelfTest` proves the probe kills a hung
child before awaiting its two asynchronous output reads within a second bound.
Hosted proof is the Windows workflow's Squirrel artifact and unsigned-signature
contract, not a static source check.

Suggested articles: [local history](../local-history/README.md),
[notification centre](../notification-centre/README.md), and
[offline documentation](../offline-documentation/README.md).
