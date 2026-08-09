# Shared School mode

School mode is a shared local presentation switch for user-facing Amulet
surfaces. It has a user-renamable label, persists independently of ordinary
appearance preferences, and can be disabled only after the locally configured
unlock credential is verified.

## Behaviour

- Enabling requires an unlock credential of 4–128 characters.
- The credential is stored only as a salted PBKDF2-HMAC-SHA256 verifier in the
  shared local configuration record `shared_school_mode`; the original value is
  never written to preferences, exports, logs, or source.
- While enabled, `presentation_preferences()` forces English, serious copy
  levels (1/1), and no dialog emojis. The user's prior choices remain stored
  and are returned when the mode is unlocked.
- The user-facing mode label is bounded to 64 Unicode characters and rejects
  control characters. Resetting it restores the shipped label.

## Failure and security boundaries

Malformed or hand-edited state falls back to the shipped label and disabled
mode. A missing, malformed, or incorrect credential never unlocks the mode.
This is a local experience lock, not a security boundary: deleting the shared
configuration record resets it, and the UI must state that plainly when the
settings surface is wired.

## Native settings surface

The Material 3 Preferences dialog exposes the mode name, enabled state, and a
password-style credential field in its Appearance tab. Saving a new credential
stores only its verifier; leaving an enabled mode requires the current
credential, while ordinary language and appearance choices remain recoverable
behind the mode.

## Verification

`tests/test_preferences.py` covers persistence, name and credential bounds,
salted verification, wrong-credential rejection, and the English-only forced
presentation. Native control runtime interaction still requires wx on the
verification host; compile and domain tests cover the shipped wiring.

Related: [appearance presets](../appearance-presets/README.md) and
[scheduled settings](../scheduled-settings/README.md).
