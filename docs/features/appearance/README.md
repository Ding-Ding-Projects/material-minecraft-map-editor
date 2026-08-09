# Appearance editor

The native Preferences Appearance tab applies the persisted Material 3 theme,
density, accent, UI scale, and selected installed font to the live wx surface.
It also exposes bounded HEX/RGB/HSL translation, a contrast readout, a live
type preview, named presets, per-property reset, and a global appearance reset.

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

Run `python -m pytest -q tests/test_appearance_editor.py tests/test_appearance_presets.py tests/test_appearance_editor_ui_contract.py`.
The native wx surface additionally requires the Windows runtime capture path.

Suggested articles: [scheduled settings](../scheduled-settings/README.md),
[tab groups](../tab-groups/README.md), and
[offline documentation](../offline-documentation/README.md).
