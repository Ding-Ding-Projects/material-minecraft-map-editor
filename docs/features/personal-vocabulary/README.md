# Personal vocabulary

A per-user, opt-in overlay that rewrites the application's own display text
and accessible names to whatever words the user privately supplies -- and
does absolutely nothing until they do.

## What this is, and is not

This feature exists **only** to run a user-supplied `PERSONAL_VOCABULARY.json`
file against the application's own screen. It is not a translation feature
(that is [Language modes](../language-modes/README.md)), and it does not ship any
vocabulary, term, mapping, or example of its own. Nothing in this repository
-- source, tests, or documentation -- names what a real vocabulary file might
contain, because the whole point of the contract is that only the user's own
private data ever does.

The implementation is the generic, content-agnostic overlay mechanism in
[`amulet_map_editor/api/text_overlay.py`](../../../amulet_map_editor/api/text_overlay.py),
wired into the application at the one place every localised, user-facing
string already passes through:
[`amulet_map_editor/api/lang.py`](../../../amulet_map_editor/api/lang.py)'s
`get()` function. Every call site in the application that shows translated
copy -- labels, menu items, tooltips, dialog titles, accessible names built
from those same strings -- already routes through `lang.get()`, so wiring the
substitution boundary there is what makes the overlay reach the real,
running interface rather than being an unused library function.

## How it works

1. **Nothing is loaded by default.** With no overlay file ever chosen, every
   function in `text_overlay` is a no-op and `lang.get()` returns the shipped
   wording completely unchanged. There is no bundled vocabulary and no
   default file path.
2. **The user supplies a file, from their own machine, through Preferences.**
   The "Display-text overlay" row on the Language tab of Preferences
   (`amulet_map_editor/api/wx/ui/preferences.py`) has a path field with a
   native Browse control beside it, plus Load, Reload, and Remove actions.
   Loading takes effect immediately -- it never waits for the dialog's
   Save/OK -- and a refusal is reported in place without disturbing whatever
   overlay was already active.
3. **The file is validated against a small, bounded schema** before anything
   in it is trusted: a top-level object with exactly `version` (must be `1`),
   `replacements` (a JSON object of string to string, at most 500 entries,
   each key and value at most 300 characters, no control characters), and
   `required_phrases` (a JSON array of strings that must never be rewritten,
   even when they appear inside a sentence that otherwise matches). The whole
   file is capped at 64 KiB. Any violation is refused with a message naming
   the exact limit, never a partial or best-effort application.
4. **The validated overlay is cached in the application's own profile
   directory**, through the same `config` module every other setting uses --
   never inside a user's opened project, never inside this repository, and
   never logged. That cache is what lets the overlay survive a restart
   without the user re-choosing the file every launch.
5. **Every subsequent call to `lang.get()` applies the active overlay** to
   the string it is about to return, using longest-match-first literal
   substitution so a longer key always wins over a shorter key that happens
   to be one of its prefixes. A replacement is skipped anywhere it overlaps a
   protected `required_phrases` span, so a technical fragment embedded inside
   an otherwise-rewritten sentence stays exact.

## What is substituted, and what never is

`text_overlay.substitute_text()` (aliased as `substitute_accessible_name()`
for call sites that want to say what they mean) is the one substitution
boundary in this codebase. It is safe to call on **display copy only**:
translated labels, menu text, tooltips, dialog titles, status messages, and
the accessible names built from that same copy.

It must never be called on a command, a URL, a file path, an identifier, a
version string, a commit SHA, error text surfaced from another system, or any
other factual external record -- `lang.get()` only ever returns translated
display strings, which is exactly why wiring the boundary there, rather than
at every individual call site, keeps technical values out of its reach by
construction.

## Privacy

- The overlay file is never logged, never cached anywhere but the
  application's own profile directory, and never bundled, defaulted, or
  committed.
- The Preferences status line shows only the replacement **count** and the
  **source path** the file was loaded from -- never the mapping's contents in
  bulk.
- Nothing in this repository (source, tests, fixtures, or documentation)
  contains a real personal-vocabulary term, mapping, or example. Every
  fixture used by this feature's tests is an obviously invented word pair
  (`"widget"` -> `"gadget"`) chosen specifically to demonstrate the mechanism
  without describing what a real file might say.
- A personal-vocabulary file is never copied into documentation, an issue, a
  release, a log, an export, a prompt, an analytics payload, or any other
  public record. A private local cache in the application's own profile
  directory is the one place it is allowed to persist.

## Failure modes

| Situation | Behaviour |
| --- | --- |
| No file ever loaded | `lang.get()` returns shipped wording unchanged; Preferences reports "No overlay is loaded." |
| File too large, not UTF-8, not JSON, wrong top-level keys, wrong `version`, an entry over its length limit, too many entries, or a control character in a key or value | Refused with a message naming the exact rule and limit violated; nothing is cached, and any overlay that was already active is left untouched. |
| A previously good overlay's file is edited into an invalid state and Reload is pressed | The refusal is reported; the overlay that was already active and cached keeps working exactly as it did before the reload attempt. |
| Remove is pressed | The cache is cleared immediately -- no restart required -- and the interface returns to shipped wording on the very next `lang.get()` call. |
| The cached entry itself is foreign or corrupted (for example, a profile directory shared with an incompatible build) | Treated exactly like no overlay ever having been loaded, rather than surfacing a cache-internal error as a defect in the user's file. |

## Verification

- [`tests/test_text_overlay.py`](../../../tests/test_text_overlay.py) --
  the mechanism itself: schema validation, the bounded limits, longest-match
  substitution, and `required_phrases` protection, entirely with synthetic
  fixtures.
- [`tests/test_display_text_overlay_ui_contract.py`](../../../tests/test_display_text_overlay_ui_contract.py)
  -- the Preferences upload surface: the controls exist with an accessible
  Browse control, loading and removal are live and never wait for Save, a
  refusal is shown and never clobbers a good overlay, the dialog never shows
  the loaded mapping in bulk, and the Language tab actually paints something
  captured through the project's real screenshot harness.
- [`tests/test_personal_vocabulary.py`](../../../tests/test_personal_vocabulary.py)
  -- the wiring this article documents: that `lang.get()` is a complete
  no-op with nothing loaded, that a loaded overlay reaches a real shipped
  translation's text, that removing the overlay returns `lang.get()` to the
  shipped wording, and that an unmatched key passes through unchanged.

## Suggested articles

- [Language modes](../language-modes/README.md) -- the three required
  language modes and both funny-level sliders that personal vocabulary layers
  on top of, never replaces.
- [Item locks](../item-locks/README.md) -- another per-user, opt-in,
  off-by-default surface with the same "nothing happens until the user acts"
  default posture.
