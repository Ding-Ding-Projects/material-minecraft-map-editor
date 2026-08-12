# Per-surface locks

Any tab, tab group, or single appearance value can be locked shut behind a
password or a TOTP code. **This is a toy, not security** — it never claims to
encrypt or protect anything, and every prompt says so plainly.

## Behaviour

A lock is created from the item's own context menu — the "Lock…" row sits
beside "Edit tab appearance…" — and opens an anchored, non-modal popover
beside the item rather than a detached dialog. Choosing "Password" prompts for
one; choosing "TOTP code" generates a fresh secret and shows it once for a
manual authenticator entry (this app also ships a full built-in authenticator
at `amulet_map_editor/api/authenticator.py` that can hold the same secret).

Once locked, activating the item opens the same kind of anchored unlock
prompt instead of teleporting past the lock. A correct answer unlocks it for
the duration chosen when the lock was created — this surface only, until the
app closes, or a number of minutes — after which it locks itself again. The
context menu's row becomes "Lock again" while unlocked, and "Remove lock…" is
always available.

Every lock is independent. There is no master password: unlocking one lock
never unlocks another, and a locked appearance value inside a locked tab is
two separate locks with two separate answers. Every lock the app holds is
enumerable and searchable through **Preferences → Locks**
(`amulet_map_editor.api.wx.ui.item_locks.ManageLocksDialog`), which carries
the project's regex-wired search bar and a bulk remove action.

## Recovery

Forgetting a lock's password or losing its TOTP secret is a normal outcome
for a toy lock. Recovery is deleting the application's local profile folder —
every prompt this feature shows names the exact folder
(`amulet_map_editor.api.item_locks.profile_directory_hint()`), so nobody has
to go looking for it.

## Storage

- **Metadata only** (lock id, scope, target id, label, method, creation time,
  unlock duration, failed-attempt count) lives in the ordinary local settings
  record `amulet_item_locks`, read through
  `amulet_map_editor.api.config`.
- **The credential never leaves the operating system's credential vault.** A
  password is verified against a stored PBKDF2-SHA256 hash, never a stored
  password. A TOTP secret is stored in the vault and used only to compute the
  current code. Both reuse the same Windows Credential Manager binding
  `amulet_map_editor.api.forge_accounts.credential_store()` already provides
  for forge sign-in tokens, under the key prefix
  `AmuletMapEditor/itemlock/<lock id>`.
- Removing a lock deletes its vault entry before its metadata record, so a
  failed delete can never orphan a secret with no code path left to remove
  it.
- Unlock sessions (how long a lock stays open after a correct answer) are
  kept in memory only and are never written to disk.

## Failure modes

- No credential vault on this platform: every action that would touch a
  secret raises `CredentialStoreUnavailable` and the prompt shows its
  explanation instead of silently pretending to work.
- A wrong password or TOTP code: the attempt is recorded, the field is
  cleared, and the recovery line is shown again. Attempts are never rate
  limited to the point of denial — this is a toy — but every failure is
  counted on the lock's own record.
- TOTP is checked with RFC 6238's one-step clock-skew window either side of
  the current time, so a slightly slow clock still unlocks.

## Verification

- `tests/test_item_locks.py` — the credential logic: no lock by default, a
  password verified against its hash rather than stored raw, RFC 6238's
  published SHA-1/SHA-256/SHA-512 test vectors, unlock-duration expiry,
  relock, locked-on-launch, independent per-lock credentials, and that
  removing a lock never orphans its vault entry.
- `tests/test_item_lock_ui_contract.py` — builds the real "Lock…" popover,
  the real unlock popover, and the real manage-locks dialog in a real
  `wx.Frame` against a fake credential store, and reads the composited PNG.
- `tests/test_feature_completeness_inventory.py` — the desktop surface no
  longer regresses to "the documentation site has it and the app does not".

## Suggested articles

- [Appearance editors](../appearance/README.md) — the per-element appearance
  values a lock can guard
- [Tab groups](../tab-groups/README.md) — the tab and group model a lock
  attaches to
