# Unsigned Squirrel updates

The Windows app checks an allowlisted HTTPS Squirrel feed after startup and on
a bounded six-hour timer. A non-blocking banner reports available, ready,
failed, and current states. Staging validates feed metadata and package hashes;
installation occurs only after the user chooses **Restart to install update**.
**Later** hides the banner without discarding the staged state.

## Configuration and failure modes

The feed defaults to the project's immutable release-download route. Invalid
URLs, offline responses, malformed metadata, hash mismatches, cancellation, or
unsaved work produce a recoverable failed state and never interrupt active
editing. The app never invokes a signer and every published Windows artifact is
explicitly unsigned.

## Security and accessibility

Hosts are allowlisted, redirects and embedded credentials are rejected, and
package hashes are checked before staging. Restart preserves unsaved-work
protection and focus. The banner is keyboard reachable, localized, persistent
until dismissed, and records deduplicated history entries.

## Verification

Run `python -m pytest -q tests/test_updater_banner_contract.py tests/api/framework/test_squirrel_update.py tests/api/framework/test_update_copy.py`.
Hosted proof is the Windows workflow's Squirrel artifact and unsigned-signature
contract, not a static source check.

Suggested articles: [local history](../local-history/README.md),
[notification centre](../notification-centre/README.md), and
[offline documentation](../offline-documentation/README.md).
