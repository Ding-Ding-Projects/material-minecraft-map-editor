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

## Configuration

There is no separate user preference for these menus. The command bar builds
them from the existing page menu dictionaries. A callable entry becomes a
command directly; a supported tuple may additionally supply its description
and legacy wx command identifier. `MAX_QUERY_CHARS` and `MAX_RESULTS` in
`amulet_map_editor.api.material_menu` define the fixed search bounds.

## Compatibility

Pages continue extending the existing menu dictionary. The integration layer
converts each callable or supported callback tuple into a `MaterialMenuItem`;
command IDs, descriptions, sections, and callback events remain available.

## Failure modes

- A `MaterialMenuItem` with an empty visible label raises `ValueError`; a
  non-callable callback raises `TypeError`.
- Unsupported or non-callable page entries are omitted instead of creating a
  control that cannot run.
- A search with no matches leaves no command selected. Disabled commands stay
  visible but selection and activation skip them.
- Input beyond 256 characters is truncated and no more than 200 results are
  rendered, so an oversized menu cannot grow the popup without bound.
- Rebuilding the command bar destroys its previous popups before creating the
  new set, preventing stale callbacks from surviving a page change.

## Security and privacy

Filtering is local and does not execute a regular expression, persist the
query, or send command metadata over the network. The wx-independent model
treats callbacks as opaque values. Activation remains at the native wx layer
and emits the existing command event only after an enabled item is selected.

## Verification

Run the focused model and integration contracts from the repository root:

```powershell
py -3 -m pytest -q tests/test_material_menu.py tests/test_m3_completion_contract.py
py -3 scripts/validate-m3-completion.py --repo .
```

The model tests cover mnemonic and shortcut parsing, literal metadata search,
stable ranking, input/result bounds, disabled-item navigation, and invalid
items. The completion contract and validator check that the application uses
the app-owned popup instead of constructing a native command `wx.Menu`. These
are source and automated-test claims; native focus, display clamping, and
rendering remain separate runtime evidence.

## Suggested articles

- [Material application shell](../material-shell/README.md) — the command bar,
  caption controls, and responsive start surface that own these popups.
- [Command palette](../command-palette/README.md) — global command discovery
  through `Ctrl+Shift+F`.
- [Appearance](../appearance/README.md) — the Material roles and persisted
  presentation settings applied to the popup surface.
