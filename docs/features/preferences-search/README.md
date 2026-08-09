# Responsive Preferences search

## Behaviour

The native **Preferences** surface uses vertically scrolling, stacked setting
rows so labels and controls remain reachable at narrow window widths and at
high Windows display scales. Flexible action rows stack instead of requiring a
horizontal scrollbar, and date/time fields keep both their typed and native
picker routes in a stacked layout. The dialog remains resizable and rewraps
setting explanations and status text against the current tab width.

The **Search** tab builds a local index across the Language, Appearance, and
Schedule tabs. It searches each setting's visible label, explanation, and live
non-sensitive value. Results identify the owning tab and current value. Opening
a result selects the exact tab, scrolls the setting into view, and returns
keyboard focus to its real control; it never opens a duplicate setting or
changes the value merely because it was found.

Plain text with case-insensitive matching is the default. The search field has
an adjacent **Regex…** button, as do the installed-font and appearance-preset
search fields. Each button opens the same complete bounded Python `re` builder
and synchronizes the pattern, plain/regex mode, and flags back into its owning
field. The builder provides guided literals, character classes, anchors,
groups, alternation, quantifiers, raw editing, ignore-case/multiline/dot-all
flags, sample text, live matches and capture groups, and clipboard copy.

## Configuration and persistence

Search query, builder sample text, result selection, and focus highlighting are
session-only UI state. Searches never overwrite Preferences. Existing language,
appearance, School-mode, scheduled-settings, appearance-preset, and external-
editor persistence continues through the existing **OK** action; **Cancel**
still leaves staged values unchanged.

The searchable-setting inventory and the list of Preferences-owned search
fields are hand-written in `amulet_map_editor.api.settings_search`. This is
intentional: adding a setting or search field requires updating the reviewed
inventory, and the completeness tests fail when wiring is missing instead of
silently shipping an undiscoverable control.

## Failure modes

- An empty query produces an instructional empty state rather than listing
  every setting.
- An invalid or over-limit regex clears results, reports the validation error
  inline, and changes no setting.
- A result whose page is unavailable under the active presentation mode is
  omitted from the index; activating a stale result also fails without changing
  tabs or values.
- Corrupt appearance-preset or schedule storage retains its existing disabled
  controls and inline error state. Search does not attempt to repair or
  overwrite that storage.
- If the clipboard is temporarily unavailable, the regex builder reports the
  failure inline and keeps the pattern intact.

## Security and accessibility

Matching is local and uses the project's bounded `RegexBuilder`; patterns and
indexed text are never transmitted or persisted. Unlock credentials are indexed
by label and explanation only: their current text is deliberately excluded from
both the searchable document and result label. Results are keyboard-operable,
<kbd>Enter</kbd> and double-click activate the selected result, the builder and
all fields have accessible names, and visible focus returns to the exact setting
control. The stacked layout retains native controls, tooltips, and pickers.

## Verification

Run:

```text
python -m pytest -q tests/test_settings_search.py tests/test_preferences_responsive_search_contract.py tests/test_regex_dialog_full_contract.py
python -m pytest -q tests/test_preferences.py tests/test_scheduled_settings_ui_contract.py tests/test_external_editor_ui_contract.py tests/test_appearance_presets_ui_contract.py
```

The first group verifies label/description/current-value search, sensitive-value
exclusion, explicit setting and search-surface inventories, cross-tab teleport
wiring, narrow-layout structure, and the full regex builder. The second group
guards the existing persistence and feature contracts. Runtime evidence uses a
real wx build on a named hidden desktop, never the visible desktop.

## Suggested articles

- [Appearance](../appearance/README.md) covers the values shown on the
  Appearance tab.
- [Scheduled settings](../scheduled-settings/README.md) explains the Schedule
  tab's precedence, sources, and validation.
- [Command palette](../command-palette/README.md) covers global destination and
  command discovery outside Preferences.
