# Focused bug audit

This audit separates defects fixed in the supplied code from risks that still require the repository's supported native runtime. It deliberately avoids claiming that static source inspection proves every world format, plugin, renderer, or operating-system path.

## Fixed in the supplied implementation

| ID | Defect | Fix | Regression gate |
|---|---|---|---|
| M3-01 | The recursive theme helper reloaded preferences and scheduled values for descendant controls. | Resolve one `MaterialThemeContext` per complete pass. | Source contract counts one load of each input. |
| M3-02 | Element-appearance configuration was reread during descendant styling. | Load the bounded override map once and pass it through the traversal. | Source contract counts one `load_overrides()` call. |
| M3-03 | Recursive restyling repeatedly laid out descendants and amplified large-page work. | Use an iterative stack and one root `Layout()`/refresh. | Static validator rejects recursive application. |
| M3-04 | A custom button best-size calculation could re-enter itself through `_control_min_height(self)`. | Pass the already measured natural text height. | Contract rejects the recursive call form. |
| M3-05 | The persisted `system` theme value was silently coerced to light. | Resolve `wx.SystemSettings.GetAppearance().IsDark()` with an older-wx palette fallback and bind top-level surfaces to system-colour changes. | Contract checks system appearance resolution and the live refresh binding. |
| M3-06 | Holding Return or Space could repeatedly activate owner-drawn buttons on key auto-repeat. | Arm on key-down and emit once on matching key-up. | Contract checks key-up and one-shot state. |
| M3-07 | Mouse capture loss could leave buttons visually or logically pressed. | Capture on press and clear state on `EVT_MOUSE_CAPTURE_LOST`. | Contract checks capture-loss handling. |
| M3-08 | Updating a button label could overwrite a deliberately stable accessible name. | Track whether the accessible name follows the label and preserve explicit names. | Contract checks the name-tracking branch. |
| M3-09 | The application command bar still opened native `wx.Menu` surfaces. | Convert the existing menu dictionary into a searchable owner-drawn `MaterialMenu`. | Patcher and validator reject native menu construction in `create_menu`. |
| M3-10 | Popup dismissal did not explicitly restore focus for Escape/activation. | Restore the live anchor after explicit dismissal while leaving click-away focus alone. | Contract checks the focus restoration path. |
| M3-11 | Scheduled-settings timers could start overlapping worker threads. | Retain one worker reference and skip while it is alive. | Integration validator checks the overlap guard. |
| M3-12 | Notebook page-change code had identical `if` and `else` bodies. | Collapse it to one operation. | Fail-closed integration patch. |
| M3-13 | A pinned source-contract test still demanded old direct `CallAfter`/`CallLater` calls even though `app.py` already used the safer deferred helper. | Update only those two assertions to require `apply_material3_deferred` and its call. | Synthetic patch applies once and is idempotent. |

## Native/runtime risks Codex must close

These are acceptance gates, not hidden claims of completion:

- Windows wxPython paint, focus, popup, high-DPI, and multi-monitor behavior.
- A real world open/edit/save/close cycle and OpenGL/editor-canvas colour preservation.
- Dynamic plugin/page menu dictionaries, callback IDs, disabled commands, and exceptions.
- All remaining visibly legacy dialogs and editor pages named by the checked-in `ROADMAP.md` and surface inventory.
- Repeated open/close and theme/density switching for destroyed-wrapper, orphan-popup, capture, or memory regressions.
- Full repository tests and the supported packaging/build workflow.

## Scope rule

Do not rewrite map data, chunk operations, loaders, rendering, persistence, updater transport, or tab-state architecture without a concrete failing test or runtime trace. Finish the visible M3 contract one bounded surface at a time and preserve existing controllers, setting keys, validation, and callbacks.
