# Recommended file-by-file changes

## Already supplied as complete code

### `amulet_map_editor/api/material_menu.py` — new

Use as supplied. It is deliberately wx-free and is the source of truth for command normalisation, bounded filtering, ranking, and roving selection.

Do not move filtering into paint/event handlers. Do not use regex for command search.

### `amulet_map_editor/api/wx/material3.py` — replacement

Use as supplied. Preserve these compatibility points because current repository tests and modules rely on them:

- `Material3Tokens`, `TOKENS`
- `_ignore_destroyed_window`
- `_blend_colour`, `_on_colour`, `_active_palette`
- `_font_for`, `_control_min_height`, `_children`
- `_ensure_material_dialog_chrome`, `_ensure_material_frame_chrome`
- `apply_material3`, `apply_material3_deferred`

Do not restore recursive `apply_material3(child)` calls. Do not load preferences inside `_font_for` or `_control_min_height`, and do not call `load_overrides()` per control.

### `amulet_map_editor/api/wx/components.py` — replacement

Use as supplied. Preserve the event contract: callers continue binding `wx.EVT_BUTTON`; command callbacks continue receiving a `wx.CommandEvent`.

The important bug fixes are `EVT_MOUSE_CAPTURE_LOST`, `EVT_KEY_UP`, one-shot keyboard arming, stable explicit accessible names, dynamic parent relayout, and popup dismissal/focus handling.

### `tests/test_material_menu.py` — new

Keep all tests. Extend them only for concrete newly discovered cases. Especially preserve the literal metacharacter, query/result bound, stable ranking, and disabled-selection tests.

### `tests/test_m3_completion_contract.py` — new

Keep the performance-contract checks. They intentionally prevent accidental reintroduction of per-control preference I/O or recursion.

### `scripts/validate-m3-completion.py` — new

Keep as a fast static gate. It does not replace runtime testing.

### `docs/features/material-menu/README.md` — new

Update only when the user-visible menu contract changes.

## Applied structurally by `patches/apply_completion.py`

### `amulet_map_editor/api/framework/amulet_ui.py`

The patch must remain small:

1. Import `MaterialMenuItem` and `MaterialMenu`.
2. Change `_command_menus` from `list[wx.Menu]` to `list[MaterialMenu]`.
3. Add `_scheduled_refresh_thread` state.
4. Replace only `create_menu` with the custom M3 popup integration.
5. Add the overlapping-worker guard.
6. Collapse the duplicate notebook page-change branch.
7. Correct only the two stale direct-deferred assertions in `tests/test_material3_global_contract.py`; keep all other assertions intact.

Do not replace `extend_menu`, page callbacks, world open/close, update actions, or command-palette logic.

## Optional follow-up only after runtime evidence

- Add a dedicated two-column menu row if real screenshots show shortcut text needs stronger alignment. Do not do this pre-emptively.
- Adjust the supplied explicit focus-restoration timing only if native screen-reader testing demonstrates a concrete conflict.
- Add per-monitor DPI recreation only if Windows testing shows wx does not rescale an existing popup after moving between monitors.
- Convert remaining visually legacy dialogs one surface at a time, preserving every controller, validation path, setting key, default, and test contract.
