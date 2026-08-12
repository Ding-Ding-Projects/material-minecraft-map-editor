# Electron world editing -- the write half

`docs/features/electron-world-access/README.md` opens a world read-only on
purpose and says plainly that writing is a separate, later lane's job. This
is that lane. The implementation is
`amulet_map_editor/api/sidecar/edit_methods.py`, registered into the
sidecar's dispatch table by `amulet_map_editor/api/sidecar/methods.py`, and
it reuses the exact same world-handle registry `world_methods.py` already
owns -- a `world_id` returned by `world.open` is the only handle every
`world.*` method (read or write) ever operates on.

Every operation here calls the same amulet-core APIs the wx application's
own stock plugins use -- see
`amulet_map_editor/programs/edit/plugins/operations/stock_plugins/operations/fill.py`
and `.../replace.py` -- so the sidecar and the wx app cannot disagree about
what "fill" or "replace" mean: both register the target block in
`world.block_palette`, both write it into `chunk.blocks[slices]` for every
chunk the selection touches, and both route undo/redo through the level's
own `history_manager` rather than a second, reimplemented undo stack.

## The method catalog

| Method | Params | Result |
| --- | --- | --- |
| `world.fill` | `{"world_id", "dimension", "min": [x,y,z], "max": [x,y,z], "block": "<universal blockstate>", "confirm": true}` | `{"world_id", "dimension", "blocks_changed", "selection_volume"}` |
| `world.replace` | `{"world_id", "dimension", "min": [x,y,z], "max": [x,y,z], "original_block": "<universal blockstate>", "replacement_block": "<universal blockstate>", "confirm": true}` | `{"world_id", "dimension", "blocks_changed", "selection_volume"}` |
| `world.undo` | `{"world_id"}` | `{"world_id", "status": "undone"}` |
| `world.redo` | `{"world_id"}` | `{"world_id", "status": "redone"}` |
| `world.save` | `{"world_id", "confirm": true}` | `{"world_id", "status": "saved", "chunks_saved"}` |

`min`/`max` are two corner points of a selection box, in world-block
coordinates, using the same half-open convention amulet's own
`SelectionBox` uses everywhere else in the codebase (`create_chunk_box`,
`bounds`): `max` is **exclusive**. A one-block selection at the origin is
`{"min": [0, 0, 0], "max": [1, 1, 1]}`.

`block`, `original_block` and `replacement_block` are Java-style
**universal** blockstate strings -- `"universal_minecraft:stone"`,
`"universal_minecraft:water[level=0]"` -- parsed with
`amulet.api.block.Block.from_string_blockstate`. This is the same universal
namespace `world.get_block(...)` already returns blocks in and the fixture
worlds in this repository's own tests are built with (see
`scripts/make_viewport_fixture_world.py`), so a block read back from one
`world.*` method is always a valid `block` argument to another.

## Nothing writes without `confirm: true`

`world.fill`, `world.replace` and `world.save` all require `params.confirm`
to be exactly `true`. Anything else -- missing, `false`, `0`, `"yes"` --
gets a structured `confirmation_required` error and the world is untouched.
There is no default that lets a write through; the caller must say so every
time. `world.undo`/`world.redo` do not require it: they only ever restore a
state the world already held, and never introduce a new change of their
own.

## The selection is bounded

`MAX_SELECTION_VOLUME` (262,144 blocks -- a 64x64x64 cube) is the largest
single fill/replace this module will attempt. Both `world.fill` and
`world.replace` run synchronously on the stdio dispatcher's own
per-request thread, inside its timeout window
(`amulet_map_editor.api.sidecar.protocol.DEFAULT_TIMEOUT_SECONDS`, 10
seconds). A chunk-vectorised numpy fill/replace over a few hundred thousand
blocks finishes in well under a second on ordinary hardware; a selection
spanning millions of blocks would not, and would either time out or stall
every other in-flight request behind it -- there is no background-thread
escape hatch here the way `world.open` has one, because an edit inside the
bound is meant to be fast rather than merely eventually finished.

A selection over the limit is refused with a `selection_too_large` error
naming both the limit and the selection's actual volume. It is never
silently clamped to the limit, and never attempted anyway. A caller that
wants to edit a larger volume issues several smaller requests.

## A block string that does not resolve is a structured error

`Block.from_string_blockstate` is given exactly what the caller sent, and if
it does not parse (wrong case, stray punctuation, an empty string) this
module reports `block_unresolved`, naming the field and the exact string
that failed. There is no fallback block: an edit that cannot resolve its
target block does not write anything, rather than silently placing whatever
block happens to be default.

## `world.replace`'s matching rule

`world.replace` treats every universal block currently registered in
`world.block_palette` that has the same namespace, base name, and exact
property mapping as `original_block` as a candidate to replace -- the same
matching rule the wx `Replace` operation uses, minus its `"*"`
wildcard-property convenience (a sidecar caller supplies an exact block
string, so there is no UI wildcard to express).

One thing this module has to account for that a naive port would miss:
**`world.block_palette` is populated lazily.** A freshly opened world's
palette starts with only whatever has already been touched (often just
`air`), and it grows as `world.get_chunk_slice_box` loads each chunk in the
selection for the first time. So the set of matching internal block ids
cannot be computed once before the loop starts -- it is refreshed after
every chunk, exactly the incremental check the wx `Replace` operation
performs (`if universal_block_count < len(world.block_palette): ...`).
Skipping this would silently match nothing on a freshly opened world, which
is exactly the failure this module's own tests caught during development.

## Undo, redo, and the order `create_undo_point` runs in

Both `world.fill` and `world.replace` call `world.create_undo_point()`
**after** making their change, never before. This matches the wx
application's own `EditCanvas.run_operation`, and the ordering is not
cosmetic: `create_undo_point()` snapshots "what has changed since the last
undo point" -- calling it before the edit finds nothing to snapshot yet, and
an undo immediately afterwards would have nothing to undo. `world.undo`
and `world.redo` call straight into the same `history_manager.undo()` /
`.redo()` the wx canvas uses; there is no second, sidecar-only undo stack
that could drift from it.

`world.undo` and `world.redo` both check `history_manager.undo_count` /
`.redo_count` before acting, and report a structured `nothing_to_undo` /
`nothing_to_redo` error rather than silently no-op-ing when there is
nothing to do.

If a fill or replace raises partway through (a malformed chunk, an
interrupted process), the handler calls `world.restore_last_undo_point()`
before re-raising, so a partial write does not leave the in-memory world in
a half-edited state with no way back to the last known-good snapshot.

## `world.save` is the only thing that reaches disk

Fill and replace only ever mutate the in-memory `Chunk` objects amulet
already caches for an open world -- exactly what `chunk.changed = True`
marks -- the same way the wx app's stock plugins do. `world.save` is the
only method in this module that calls `world.save_iter()`, the level's own
save path, and it requires `confirm: true` exactly like fill and replace.
Closing a world handle (`world.close`) without calling `world.save` first
discards every unsaved change; there is no autosave and no implicit save
anywhere in this module. `world.save`'s result reports `chunks_saved`, the
real number of changed chunks the save actually wrote, not a bare `ok`.

## Error codes

| Code | Meaning |
| --- | --- |
| `invalid_params` | (from the shared protocol) a malformed `world_id`, `dimension`, `min`/`max`, or an empty selection |
| `world_not_found` | `world_id` does not name an open, opening, or recently-failed handle (shared with `world_methods.py`) |
| `world_not_ready` | the handle is still `pending` (shared with `world_methods.py`) |
| `world_load_failed` | the handle failed to open (shared with `world_methods.py`) |
| `dimension_unknown` | `dimension` is not one of the open world's real dimensions |
| `confirmation_required` | `world.fill` / `world.replace` / `world.save` was called without `confirm: true` |
| `selection_too_large` | the `min`/`max` selection is over `MAX_SELECTION_VOLUME` (262,144) blocks |
| `block_unresolved` | `block` / `original_block` / `replacement_block` did not parse as a blockstate string |
| `nothing_to_undo` | `world.undo` was called with an empty undo history |
| `nothing_to_redo` | `world.redo` was called with an empty redo history |
| `edit_backend_unavailable` | `amulet` / `PyMCTranslate` are not importable in this interpreter |

## When the world-format libraries are not installed

Exactly like `world_methods.py`, this module imports `amulet.api.block.Block`
and `amulet.api.selection.SelectionBox` once at module load time inside a
`try`/`except`. If that import fails, every method in this module reports a
structured `edit_backend_unavailable` error (carrying the real import
failure text) instead of letting an `ImportError` propagate up through the
dispatcher as an opaque `internal_error`.

## Testing

`tests/test_sidecar_edit_methods.py` spawns the **real** sidecar child
process (`python -m amulet_map_editor.api.sidecar`) and talks to it over its
actual stdin/stdout pipes, against a genuine Java world built through
amulet-core -- the same fixture shape
`scripts/make_viewport_fixture_world.py` builds. It never trusts the
sidecar's own report of what changed: every test that claims a write
happened (or, just as importantly, did not happen) closes the sidecar's
handle -- discarding any unsaved in-memory change exactly as a crash or a
user simply not saving would -- and re-opens the world file **directly**
with `amulet.load_level` in the test process to read the real on-disk
blocks back. Covered:

- a fill refused without `confirm` (both missing and explicitly `false`);
- a fill that works, verified by re-reading the real saved blocks;
- **a fill without a following `world.save` never reaching disk** -- the
  most important case in this lane, and the one this module's own
  development caught failing when a stray `world.save()` call was
  temporarily added to `world.fill` on purpose to prove the test actually
  detects it;
- undo restoring the pre-fill state, and redo reapplying it, both verified
  by re-reading real saved blocks after each step;
- `world.undo` / `world.redo` against an empty history reporting
  `nothing_to_undo` / `nothing_to_redo`;
- `world.replace` only touching the blocks that actually match, leaving an
  adjacent different block alone;
- a selection over `MAX_SELECTION_VOLUME` refused as `selection_too_large`,
  naming the limit;
- an unresolvable block string refused as `block_unresolved`, with the
  sidecar recovering to serve the next request and the world left
  unchanged;
- every write method against an unknown `world_id` reporting
  `world_not_found`.

Run just this lane's tests with:

```
py -3.11 -m pytest tests/test_sidecar_edit_methods.py -q
```

## Related reading

- `docs/features/electron-world-access/README.md` -- the read-only half
  this module completes: opening a world, reading its identity and
  dimensions, and closing it.
- `docs/features/sidecar/README.md` -- the wire protocol, versioning, and
  the rest of the method catalog this module's methods join.
- `amulet_map_editor/programs/edit/plugins/operations/stock_plugins/operations/fill.py`
  and `.../replace.py` -- the wx application's own implementations of the
  same two operations, which this module deliberately mirrors rather than
  reinvents.
