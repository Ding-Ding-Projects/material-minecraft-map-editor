# Native component registration and state anatomy

This is the design registration, not an implemented component library. All implementation paths below are proposed under `native_ui/qml/components/`; all runtime and provenance acceptance is pending. Before a visible runtime shell is accepted, replace each proposal with the actual source path, pinned Qt version/source/license receipt, component tests and rendered audit. No row permits arbitrary generic controls as a fallback.

## First-increment implementation registration

The initial implementation now lives under `native/amulet_native/qml/`. This table supersedes the proposed path for only the named rows. No rendered audit is implied.

| Design identity | Actual source | Foundation and current evidence |
| --- | --- | --- |
| `md.button` | `native/amulet_native/qml/MdButton.qml` | Qt Quick Controls Button, registered custom container/state layer and label; Qt/PySide6 pinned to 6.12.0; runtime/provenance audit pending |
| `md.icon-button` | `native/amulet_native/qml/MdWindowButton.qml` | Qt Quick Controls ToolButton, explicit target/name/tooltip/focus states; native window actions wired; glyph/font and rendered audit pending |
| `md.titlebar` | `native/amulet_native/qml/Main.qml` title region | Frameless Qt Quick window, move/resize, minimize/maximize/restore/close; runtime interaction pending |
| `md.progress` | `native/amulet_native/qml/Main.qml` ProgressBar | Qt Quick Controls Material indeterminate progress, engine-owned busy state; runtime audit pending |
| `md.dialog`, `md.switch`, `md.menu` | `native/amulet_native/qml/Main.qml` dialog/menu regions | Qt Quick Controls Material implementations; accessible text and actions; detailed conformance and complete search obligations remain pending |

The implementation must retain the installed Qt source/version and licensing receipts before acceptance. Pinning a requirement alone is not that receipt. Remaining primitives retain their proposed paths and unfinished states. The first shell does not enable editing controls from the schematic workspace.

### Read-only chunk increment registrations

`native/amulet_native/qml/ChunkWorkspace.qml` owns the Qt Quick Controls Material dimension/section selectors, signed coordinate fields, local-Y stepper, read action and inspector dialog. `ChunkSlice.qml` owns the native categorical data grid, keyboard cell selection, local X/Z steppers and zoom. `BlockInspector.qml` owns exact text/property presentation. Existing `MdButton.qml` supplies action anatomy. The slice's rectangles are data cells, not a substitute for Material chrome. All new runtime/layout/component conformance evidence is pending. The reviewed repair adds MdNumericField, MdSelect, MdSpinBox, MdProgress, MdDialog and MdRegexDialog registrations. See native/COMPONENTS.md for exact installed Qt source hashes, anatomy, states and limits. Owned filtering, a bounded supported regex subset and per-field help/clear are implemented; full regex parity, localization and rendered conformance remain unfinished.

## Sources and provenance

The normative design family is [Material Design 3 components](https://m3.material.io/components), including the [buttons reference](https://m3.material.io/components/buttons/overview). The official page requires JavaScript in the text retrieval route, so detailed current anatomy has not been independently retrieved through that route. Full official-spec comparison remains a required review step; these author-defined anatomy contracts cannot masquerade as that evidence.

[Qt Quick Controls Material documentation](https://doc.qt.io/qt-6/qtquickcontrols-material.html) describes its implementation and customization. The retrieved document identifies Qt 6.12.0, not the project's installed/pinned Qt version. Do not infer runtime support or exact Material Design 3 parity from that document. Each actual implementation must retain its own version-specific provenance. Public component source/license references must be recorded before reuse; none are claimed vendored by this design.

## Registered primitives

All actionable controls have enabled/default, hover, keyboard-focus, pressed and disabled states. Selectable controls also have selected and selected-hover/focus/pressed states. Focus is visible independently of selection. Disabled state suppresses invocation but retains an accessible reason. Progress does not replace the label or accessible name. The listed anatomy must exist as actual registered component internals, not painted labels that imitate controls.

| ID / proposed file | Anatomy and use | Additional explicit states |
| --- | --- | --- |
| `md.titlebar` / `MdTitleBar.qml` | Semantic title; drag-only empty region; independent icon buttons for minimize, maximize/restore, close; native resize edges | active, inactive, maximized, restored, full-screen, close-decision-pending |
| `md.search` / `MdSearchBar.qml` | Container; leading search icon; editable query; clear action; separate adjacent Regex builder button; supporting validation | empty, editing, populated, invalid, searching, result-count, canceled |
| `md.button` / `MdButton.qml` | Filled/tonal/text variants; container; optional icon; label; state layer; focus outline; separate progress indicator | idle, loading, disabled-with-reason; fixed name while loading |
| `md.icon-button` / `MdIconButton.qml` | 48-unit hit area; official glyph; accessible name; tooltip; state layer; focus outline | toggled where applicable; tooltip-open |
| `md.segmented` / `MdSegmentedButton.qml` | Shared outlined container; distinct segment boundaries; per-segment hit area and label; selection indicator | exactly one camera mode selected; no ambiguous multiple selection |
| `md.tabs` / `MdTabBar.qml` | Tab list; individual named tabs; selected indicator; close control; overflow action; focus ring | selected, dirty, pinned, grouped, overflow, close-decision-pending |
| `md.navigation` / `MdNavigationItem.qml` | Destination icon/name; supporting detail; selected tonal container; optional count | selected, unavailable, loading, expanded, collapsed |
| `md.list` / `MdListItem.qml` | Leading visual; headline; optional supporting text; trailing action; independent accessible action | selected, multiline, read-only, unavailable |
| `md.chip` / `MdFilterChip.qml` | Label; optional leading icon; outline/container; selected indicator | selected, unselected, unavailable |
| `md.field` / `MdOutlinedField.qml` | Persistent/floating label; outlined container; editable value; optional suffix; independent clear action where clearing is valid; guidance info button opening contextual help; supporting/validation text | empty, populated, editing, invalid, read-only, help-open, cleared; each coordinate axis independent |
| `md.dropdown` / `MdDropdown.qml` | Named anchor field; expansion indicator; opaque bounded popup; local search plus own regex action | collapsed, expanded, selected, no-result, invalid-search |
| `md.checkbox` / `MdCheckbox.qml` | Box; check/mixed mark; associated label; hit area | unchecked, checked, indeterminate |
| `md.radio` / `MdRadio.qml` | Ring; selected center; associated label; group semantics | selected, unselected |
| `md.switch` / `MdSwitch.qml` | Track; thumb; optional state icon; associated label | on, off; pending persistence cannot falsely settle |
| `md.slider` / `MdSlider.qml` | Track; thumb; value label; accessible min/max/value; exact numeric alternative | dragging, keyboard-adjusting, bound-reached |
| `md.menu` / `MdMenu.qml` | Opaque elevated container; named items and shortcuts; local search with independent regex | open, filtered, no-result, nested, disabled-item |
| `md.dialog` / `MdDialog.qml` | Opaque container; title; scrollable content; fixed actions; focus boundary | open, validating, invalid, committing, canceled |
| `md.side-sheet` / `MdSideSheet.qml` | Title; close action; owned scroll area; contextual footer; optional scrim | docked, temporary, open, closed, constrained-height |
| `md.bottom-sheet` / `MdBottomSheet.qml` | Summary/handle; title; content; expand/collapse control | collapsed, expanded, full-panel fallback |
| `md.tooltip` / `MdTooltip.qml` | Opaque named text surface; associated origin; no hidden mandatory facts | delayed-open, keyboard-open, dismissed |
| `md.snackbar` / `MdSnackbar.qml` | Opaque message surface; optional action; dismiss; polite status | queued, visible, acted, dismissed; no focus theft |
| `md.progress` / `MdProgress.qml` | Linear/circular track and indicator; textual status; optional cancel | indeterminate, determinate, cancel-requested, completed, failed |
| `md.state-layer` / `MdStateLayer.qml` | Bounded hover/pressed overlay and independent focus ring, composed inside registered controls | default, hover, focus, pressed, disabled; reduced-motion |

## Individual workspace control registration

| Control | Component and interaction | Explicit individual states |
| --- | --- | --- |
| Select | `md.button`, toggle active selection tool | inactive, active, hover, focus, pressed, unavailable-world |
| Move | `md.button`, activate selection transform | inactive, active, no-selection-disabled, read-only-disabled, drag-preview, invalid-transform |
| Brush | `md.button`, activate supported brush only | inactive, active, unsupported-disabled, no-block-disabled, stroke-preview, applying |
| Inspect | `md.button`, activate block inspection | inactive, active, hit, no-hit, chunk-unavailable |
| More | `md.icon-button` plus `md.menu` | closed, open, filtered, no-results, context-disabled-item |
| Perspective | segment in `md.segmented` | unselected, selected, hover, focus, pressed, renderer-unavailable |
| Top | segment in `md.segmented` | unselected, selected, hover, focus, pressed, renderer-unavailable |
| Slice | segment in `md.segmented` plus bounded Y field | unselected, selected, hover, focus, pressed, invalid-Y, renderer-unavailable |
| Camera navigation | terrain input controller plus accessible numeric fields | idle, pointer-captured, panning, orbiting, flying, keyboard-moving, Escape-released, bounds-reached |
| Preview fill | `md.button` | no-selection-disabled, invalid-block-disabled, ready, previewing, cancel-requested, preview-ready, failed |
| Save world | `md.button` | clean-disabled, dirty-ready, read-only-disabled, writing, conflict, succeeded, failed |
| Minimum X/Y/Z | three `md.field` instances | valid, focused, editing, invalid-number, out-of-bounds, exceeds-maximum, read-only |
| Maximum X/Y/Z | three `md.field` instances | valid, focused, editing, invalid-number, out-of-bounds, below-minimum, read-only |
| Block choice | `md.list` plus real picker | selected, picker-open, no-match, unsupported-version, invalid-property |

Coordinate labels identify axis and minimum/maximum in accessible names. Each value is separately focusable and validatable. In the narrow inspector, fields stack when a full signed coordinate would not fit; do not shrink numeric type below 13/20. Block identifiers are at least 13/20 and receive their own full-width line, wrapping at identifier separators only when needed without changing the underlying value.

Field help explains meaning, valid bounds, default and recovery without replacing the persistent label. Guidance and clear controls each have their own accessible name, focus and hit area. Clearing returns a field to explicit empty validation, never silently substitutes zero or applies an operation. Read-only fields retain help and omit an inapplicable clear action. Closing help restores focus to its opener.
