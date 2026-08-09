# Command palette

Press `Ctrl+Shift+F` on Windows to open the native command palette. Results
cover commands, feature destinations, settings, appearance controls, and
documentation articles. Selecting a result opens its owning surface, selects
the relevant tab or group, reveals the target, focuses it, and preserves the
rest of the user's state.

## Search and failure modes

Plain text is the default. The attached regex builder supports bounded Python
`re` patterns, flags, samples, validation, and capture feedback. Invalid or
oversized patterns fail locally with an actionable message and never freeze the
UI. An empty result is explicit rather than a blank panel.

## Accessibility and security

The palette is keyboard navigable with roving selection, visible focus, and
screen-reader listbox roles. Search values remain local to the process and are
not transmitted or persisted as telemetry. School mode removes inapplicable
destinations from the result set.

## Verification

Run `python -m pytest -q tests/test_preferences.py tests/test_docs_browser_ui_contract.py`.
Runtime shortcut proof requires the hidden-desktop Windows route because the
local host may not have wx installed.

Suggested articles: [offline documentation](../offline-documentation/README.md),
[tab groups](../tab-groups/README.md), and
[appearance editor](../appearance/README.md).
