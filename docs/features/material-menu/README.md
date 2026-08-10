# Material command menu contract

The application command bar uses an app-owned Material 3 popup instead of a native `wx.Menu`.

## Behaviour

- Opening a top-level command button shows a rounded surface below that button.
- The search field receives focus without a modal dialog.
- Matching is literal, Unicode-normalised, case-insensitive, and bounded.
- Labels, descriptions, section names, and explicit keywords are searchable.
- Up/Down moves through enabled commands; Home/End goes to the first/last enabled command.
- Enter activates the selected command from search; Escape dismisses and returns focus to the opening control.
- Mouse and keyboard activation produce the same legacy `wx.CommandEvent` callback contract.
- Click-away dismissal leaves focus on the clicked target.
- Popups are clamped to the active display's client area and use a bounded scrolling region.
- Disabled commands remain visible but cannot be selected or activated.

## Safety and performance

- Query input is capped at 256 characters.
- Results are capped at 200 commands.
- No regular expression is compiled from user input.
- Filtering is implemented in the wx-free `amulet_map_editor.api.material_menu` model and is covered by headless tests.
- A popup owns its child controls and is destroyed/rebuilt with the command bar, avoiding detached native menu state.

## Compatibility

Pages continue extending the existing menu dictionary. The integration layer converts each callable or supported callback tuple into a `MaterialMenuItem`; command IDs, descriptions, sections, and callback events remain available.
