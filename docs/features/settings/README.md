# Settings and appearance

Ten surfaces under **Settings** in the surface index, covering everything the
user can change about how the application looks, speaks, and behaves.

## Behaviour

| Surface | What it does |
| --- | --- |
| **Options** (`prefs`) | The tabbed preferences window: appearance, language and voice, schedule, and a search over every setting. |
| **Appearance presets** (`presets`) | Named appearance sets, saved, loaded, exported, and imported. |
| **Element appearance** (`elementAppearance`) | The per-element editor, opened on whatever control has focus. |
| **Key configuration** (`controls`) | Every keyboard binding, editable. |
| **Language Select** (`languageSelect`) | The language mode. |
| **Narrator** (`narrator`) | The optional spoken narrator, off by default. |
| **School mode** (`schoolUnlock`) | The shared presentation lock and its unlock. |
| **External editor** (`externalEditor`) | The editor an export opens in. |
| **Tabs and groups** (`tabManager`) | Tab order, pinning, grouping, and docking. |
| **Destructive-action gate** (`confirm`) | The two-key gate every irreversible action passes through. |

Several of these are the dialogs that predate this shell and are still the real
implementation. The Studio routes their keys to those windows rather than
opening a second, subtly different copy — a surface key never tells the caller
which of the two it is asking for.

**Every settings surface is searchable.** Its own search field reads the option
labels, the descriptions, and the current values, carries the regex opt-in and
the `.*` builder, and says plainly when a match sits on a different tab.

**Every settings surface is tabbed**, following the same tab contract as the
rest of the product: an overflow surface when the tabs exceed the width,
reordering, and persistence of that order.

## Configuration

Everything here writes to one shared preference profile, read everywhere through
the School-mode projection. The appearance roles the Studio paints with —
theme, density, accent, interface font, interface scale — are the same values
the legacy dialogs read, so the two halves of the application cannot drift into
two different themes.

A scheduled rule can override the language mode, theme, density, or accent for a
window of time; the base preference is retained and returns when the rule ends.

## Failure modes

An invalid persisted value normalises to the shipped default rather than
preventing startup, and the fact that a value came from a default rather than
from something the user set is stated beside the control rather than left to be
guessed.

A customisation surface never silently drops a value it cannot represent: it
says so and keeps what the user entered.

School mode omits the language, tone, and dim-sum controls rather than disabling
them, and turning it off requires the shared locally verified credential. It is
a presentation lock, not a security boundary, and it says so.

## Security and accessibility

No setting is transmitted. Credential material for the School-mode unlock never
enters an export, a preset, a log, or a capture. External-editor discovery reads
local installation paths only.

Every control is keyboard reachable with a visible focus ring and an accessible
name, every settings element carries its full explanation behind progressive
disclosure, and the colour controls are continuous pickers with hex, RGB, and
HSL entry plus a live contrast readout rather than a fixed palette of swatches.

## Verification

```powershell
py -3 -m pytest tests/test_preferences.py tests/test_appearance_editor.py tests/test_scheduled_settings.py tests/test_studio_tokens.py -q
```

Those cover the persisted profile, the appearance editor and its presets, the
scheduled rule engine, and the Studio's own token values including that a
reseeded accent still produces readable inks.

Suggested articles: [appearance](../appearance/README.md),
[language modes and funny levels](../language-modes/README.md),
[scheduled settings](../scheduled-settings/README.md), and
[school mode](../school-mode/README.md).
