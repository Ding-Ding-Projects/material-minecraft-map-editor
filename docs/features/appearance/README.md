# Appearance editor

The native Preferences Appearance tab applies the persisted Material 3 theme,
density, accent, UI scale, and selected installed font to the live wx surface.
It also exposes bounded HEX/RGB/HSL translation, a contrast readout, a live
type preview, named presets, per-property reset, and a global appearance reset.

## What the Studio shell reads from it

The Amulet Studio shell resolves its own palette from the same profile through
`amulet_map_editor/api/studio/tokens.py`, so one appearance choice reaches both
halves of the application:

- **Theme** selects the light or the dark palette; `system` resolves from the
  platform's own appearance and falls back to light where that cannot be asked.
- **Density** sets the minimum control height directly — compact 32,
  comfortable 36, spacious 44 — multiplied by the interface scale.
- **Accent** reseeds the whole primary family rather than one button colour:
  the primary, both readable inks, the container, and the surface tint all
  follow it, so a chosen accent never leaves half the shell on the shipped
  teal. The inks are recomputed for contrast, so every seed leaves the label on
  top of it legible.
- **Interface font** and **scale** feed the shell's font resolution, which falls
  back through a local candidate list ending in faces that carry Traditional
  Chinese, so bilingual copy still renders when nothing earlier is installed.
  Nothing is ever downloaded.

`refresh_theme()` re-resolves the tokens and repaints the whole shell, so a
change lands live rather than at the next launch. An active scheduled rule
overrides the persisted theme, accent, or density for as long as it applies.

## Configuration and failure modes

Values are versioned in the shared preferences profile and normalized on load.
Invalid colors, scales, or font values fall back to shipped values without
breaking startup. Unsupported typography capabilities remain visible as
platform-limited rather than being silently discarded.

## Security and accessibility

The editor accepts bounded local values only; it does not fetch fonts or colors
from the network. Controls retain keyboard names, focus, contrast, and minimum
touch sizes. School mode removes inapplicable language and funny-level controls
while preserving recoverable prior preferences.

## Verification

Run `python -m pytest -q tests/test_appearance_editor.py tests/test_appearance_presets.py tests/test_appearance_editor_ui_contract.py tests/test_studio_tokens.py`.
The last of those asserts the Studio's light and dark palettes are the design's
exact values, that the three density heights are 32, 36, and 44, and that
reseeding from any accent still produces readable inks. The native wx surface
additionally requires the Windows runtime capture path.

Suggested articles: [settings and appearance](../settings/README.md),
[scheduled settings](../scheduled-settings/README.md),
[tab groups](../tab-groups/README.md), and
[project shell](../project-shell/README.md).

## Per-element appearance editing

Every native Material 3 control receives an **Edit appearance…** entry in its
keyboard-accessible context menu. The editor uses a bounded stable role key
(accessible name, or control class when unnamed) and persists portable M3
background/foreground HEX colours, font size, normal/medium/bold weight,
italic, underline, strikethrough, and bounded letter spacing.
Blank colours and font size `0` inherit the active role. **Reset element
appearance** removes only that role override. Changes are saved in the bounded
`amulet_element_appearance` profile and recorded through non-blocking local
history. Unsupported Word-only typography axes remain visible as
platform-limited rather than being silently discarded.

Keys are limited to 160 characters and profiles to 512 entries. Malformed
colours or font sizes fail closed to the inherited role; no network or
arbitrary class loading is involved. `tests/test_element_appearance_contract.py`
guards the route, bounds, live application, reset, capability disclosure, and
history recording. Italic, underline, and strikethrough apply live to the
edited native control. Letter spacing is retained for a backend that supports
it, while this wx backend reports the capability limitation explicitly;
pixel-level wx runtime capture remains a Windows-only gate.
