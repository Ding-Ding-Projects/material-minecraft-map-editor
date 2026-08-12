# Built-in authenticator

A local TOTP authenticator. It holds arbitrary two-factor secrets for whatever
accounts you like — not only this application's own per-surface locks — and
shows live codes for them. There is no account, no sync, and no network: the
codes are computed from the secret and the system clock, on this machine.

## Behaviour

Open it from the command palette or from **Preferences → Authenticator**
(`amulet_map_editor.api.wx.ui.authenticator_dialog.AuthenticatorDialog`). Each
entry lists its issuer and account, its current code in large grouped digits
with a copy action, the seconds remaining in the period, and a peek at the
next code so nobody starts typing one with two seconds left on it. The list
carries the project's regex-wired search bar like every other list.

Registering an entry (`RegisterEntryDialog`) accepts either a pasted
`otpauth://totp/` URI or manual base32 entry with its parameters. Parameters
carried by a URI are honoured rather than overwritten with defaults. The
dialog shows a QR code **drawn locally, in-process** alongside the grouped
base32 secret and its algorithm, digit count and period, so the entry can be
paired by camera from a phone or typed by hand on the device already showing
it. Registration is modal and completes as a whole because a half-registered
factor is one that cannot be used and cannot be recovered from.

**The pairing is confirmed before the factor arms.** One current code is typed
back, and only a match completes registration. Without that step a mistyped
secret locks you out of something you have just set up, and the first you
learn of it is when you need it.

## Standards

RFC 6238 TOTP over RFC 4226 HOTP: SHA-1, SHA-256 and SHA-512, 6 to 8 digits,
arbitrary period, defaulting to SHA-1/6/30 because that is what the rest of
the world issues. The implementation is checked against **the RFC's own
published test vectors** for all three algorithms at 6 and 8 digits — an
authenticator that is subtly wrong produces codes rejected everywhere with no
error to read, so a self-consistent implementation proves nothing.

Codes come from the system clock. When it is skewed far enough that codes will
be refused, `clock_warning()` says so on the surface rather than emitting
confidently wrong digits — this is the failure nobody diagnoses.

## Storage

Entry **metadata** (issuer, account, label, algorithm, digits, period) lives in
the application's config record. **Secrets live only in the operating system's
credential vault**, under a stable per-entry key, and never in settings files,
presets, logs, screenshots, history entries or Git.

`export_entries()` omits secrets **and says that it omitted them**, because an
export that silently drops a field is worse than one that refuses.
`export_entries_with_secrets()` is a separate, distinctly named function that a
caller must place behind the two-key super-confirmation gate; it writes usable
secrets in the clear and its caller must say so first.

Beyond the one-time reveal at registration, the application never displays,
hints at, or characterises a stored secret's value, length or composition.

## Failure modes

- **No credential vault** — registration refuses rather than falling back to a
  file. A secret in a settings file is not a secret.
- **Skewed clock** — reported on the surface; codes are still shown, because a
  refusing authenticator is useless and the user may only be a second out.
- **Malformed URI** — rejected with the exact reason, keeping what was typed.
- **Missing secret for a listed entry** — the row reports that the vault no
  longer holds it instead of showing a code computed from nothing.

## Verification

- `tests/test_authenticator.py` — every published RFC 6238 vector (3 algorithms
  × 6 and 8 digits), RFC 4226 vectors, URI round-trip, period rollover, clock
  skew, and a static proof that **no network import** exists anywhere in the
  registration or code path.
- `tests/test_authenticator_entries.py` — entry lifecycle against the real
  credential vault, and that `export_entries()` omits secrets.
- `tests/test_authenticator_ui_contract.py` — both dialogs built for real and
  their composited PNGs read back and checked for non-trivial content.

## Suggested articles

- [Per-surface locks](../item-locks/README.md) — the locks this authenticator
  can hold the codes for. Note that holding a lock's own secret inside the
  application that lock guards makes the lock ornamental; it is a toy lock, so
  that is allowed and worth knowing.
- [Search and regex](../search-and-regex/README.md) — the search bar on the
  entry list.
- [Exports](../exports/README.md) — what an ordinary export carries and what it
  deliberately does not.
