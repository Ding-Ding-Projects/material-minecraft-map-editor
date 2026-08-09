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

The download/apply command has a documented 900-second ceiling, sized for the
observed approximately 87 MiB full package plus local filesystem work; the
post-stage verification command has the same bounded ceiling. Invalid URLs,
offline responses, malformed metadata, hash mismatches, cancellation, timeout,
or unsaved work produce a recoverable failed state and never interrupt active
editing. The app never invokes a signer and every published Windows artifact is
explicitly unsigned.

## Security and accessibility

Only `https://github.com/Ding-Ding-Projects/material-minecraft-map-editor/releases/download/<validated-tag>/`
may reach `Update.exe`; generic GitHub, raw-content, API, latest-release, other
owner, and other repository paths are rejected. The inventory resolver uses
only its exact API route, requires HTTP 200 JSON, and rejects redirects before
parsing. Release notes must be the matching exact HTTPS project release route
with no query, fragment, credentials, or custom port, and the UI revalidates it
before opening the browser. Updater discovery accepts only the expected
`Update.exe` beside an immediate Squirrel `app-<version>` directory and never
walks arbitrary ancestors. Package hashes are checked before staging. Restart
preserves unsaved-work protection and focus. The responsive banner stacks its
message above keyboard-operable Material actions, is localized, remains
persistent until dismissed, and records deduplicated history entries.

## Verification

Run `python -m pytest -q tests/test_squirrel_version.py tests/test_updater_banner_contract.py tests/api/framework/test_squirrel_update.py tests/api/framework/test_update_copy.py`.
Hosted proof is the Windows workflow's Squirrel artifact and unsigned-signature
contract, not a static source check.

Suggested articles: [local history](../local-history/README.md),
[notification centre](../notification-centre/README.md), and
[offline documentation](../offline-documentation/README.md).
