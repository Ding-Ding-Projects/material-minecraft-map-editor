"""Sidecar methods that actually write to a world -- the other half of
:mod:`amulet_map_editor.api.sidecar.world_methods`.

That module opens a world read-only on purpose and says plainly that writing
is a later lane's job. This is that lane. It reuses the same world-handle
registry (:data:`amulet_map_editor.api.sidecar.world_methods._REGISTRY`) so a
``world_id`` returned by ``world.open`` is the same handle every method in
this module operates on -- there is no second "open for editing" call, and no
second registry that could disagree with the first about which worlds are
open.

Every operation here calls the same amulet-core APIs the wx application's own
stock plugins use (see ``amulet_map_editor/programs/edit/plugins/operations/
stock_plugins/operations/fill.py`` and ``.../replace.py``) so the sidecar and
the wx app cannot disagree about what "fill" or "replace" mean: both register
the target block in ``world.block_palette``, both write it into
``chunk.blocks[slices]`` for every chunk the selection touches, and both
route undo/redo through the level's own ``history_manager`` rather than a
second, reimplemented undo stack.

Four rules this module enforces before it ever calls into amulet, none of
them optional:

* **Nothing writes without ``confirm: true``.** ``world.fill``,
  ``world.replace`` and ``world.save`` all require an explicit ``confirm``
  boolean in ``params``. A caller that omits it, or passes a falsy value,
  gets a structured ``confirmation_required`` error and nothing touches the
  world. ``world.undo``/``world.redo`` do not require it -- they only ever
  restore a state the world already held, they never introduce a new change.
* **The selection is bounded.** :data:`MAX_SELECTION_VOLUME` (262,144 blocks
  -- a 64x64x64 cube) is the largest single fill/replace this module will
  attempt inline on the request thread. That number is not arbitrary: every
  write here runs synchronously inside the stdio dispatcher's per-request
  timeout window (see ``protocol.DEFAULT_TIMEOUT_SECONDS``), and a
  chunk-vectorised numpy fill/replace over a few hundred thousand blocks
  finishes in well under a second on ordinary hardware, while a selection
  spanning millions of blocks would not. A caller that wants to edit a
  larger volume issues several bounded requests rather than one unbounded
  one. Going over the limit is refused with a ``selection_too_large`` error
  that states the limit and the selection's actual volume -- never silently
  clamped, never attempted and left to time out.
* **A block string that does not resolve is a structured error.** ``block``,
  ``original_block`` and ``replacement_block`` are Java-style universal
  blockstate strings (``"universal_minecraft:stone"``,
  ``"universal_minecraft:water[level=0]"``) parsed with
  ``amulet.api.block.Block.from_string_blockstate``. A string that does not
  parse is reported as ``block_unresolved`` naming the exact field and
  string; it is never silently swapped for some default block.
* **Nothing reaches disk until ``world.save``.** Fill and replace only ever
  mutate the in-memory ``Chunk`` objects amulet already caches (exactly what
  ``chunk.changed = True`` marks), the same way the wx app's stock plugins
  do. The level's own ``save_iter`` is the only thing that writes those
  chunks to the world's on-disk format, and this module only ever calls it
  from :func:`_world_save`, which itself requires ``confirm``. A crash, a
  refusal, or simply never calling ``world.save`` leaves the on-disk world
  untouched.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from amulet_map_editor.api.sidecar.protocol import ERR_INVALID_PARAMS, ProtocolError
from amulet_map_editor.api.sidecar.world_methods import (
    ERR_LOAD_FAILED,
    ERR_NOT_FOUND,
    ERR_NOT_READY,
    _REGISTRY,
)

try:  # pragma: no cover - exercised via the "not installed" degrade test
    from amulet.api.block import Block as _Block
    from amulet.api.selection import SelectionBox as _SelectionBox

    _AMULET_EDIT_IMPORT_ERROR = None
except Exception as exc:  # noqa: BLE001 - any import-time failure degrades
    _Block = None  # type: ignore[assignment]
    _SelectionBox = None  # type: ignore[assignment]
    _AMULET_EDIT_IMPORT_ERROR = str(exc)

#: Structured error codes specific to editing. Distinct from
#: :mod:`world_methods`'s own codes so a caller can branch on "the selection
#: was too big" versus "that world does not exist" without parsing text.
ERR_CONFIRMATION_REQUIRED = "confirmation_required"
ERR_SELECTION_TOO_LARGE = "selection_too_large"
ERR_BLOCK_UNRESOLVED = "block_unresolved"
ERR_DIMENSION_UNKNOWN = "dimension_unknown"
ERR_NOTHING_TO_UNDO = "nothing_to_undo"
ERR_NOTHING_TO_REDO = "nothing_to_redo"
ERR_EDIT_BACKEND_UNAVAILABLE = "edit_backend_unavailable"

#: The largest single fill/replace this module will attempt inline. See the
#: module docstring for why this specific number.
MAX_SELECTION_VOLUME = 262_144


def _require_edit_backend() -> None:
    if _Block is None:
        raise ProtocolError(
            ERR_EDIT_BACKEND_UNAVAILABLE,
            "The world-format libraries (amulet-core / PyMCTranslate) are "
            "not installed in this sidecar's interpreter, so no edit can be "
            f"performed. Import failure: {_AMULET_EDIT_IMPORT_ERROR}",
        )


def _get_ready_handle(params: Dict[str, Any]):
    """Look up a world handle by id and require it to be fully open.

    Shared by every method below so "unknown handle", "still opening" and
    "failed to open" are reported identically here as they already are by
    :mod:`world_methods` -- one set of structured errors, not two that could
    drift apart.
    """
    world_id = params.get("world_id")
    if not isinstance(world_id, str) or not world_id:
        raise ProtocolError(ERR_INVALID_PARAMS, "'world_id' must be a non-empty string")
    handle = _REGISTRY.get(world_id)
    if handle is None:
        raise ProtocolError(ERR_NOT_FOUND, f"No open (or opening) world with id {world_id!r}")
    if handle.status == "pending":
        raise ProtocolError(ERR_NOT_READY, "That world is still opening")
    if handle.status == "failed":
        raise ProtocolError(
            ERR_LOAD_FAILED, handle.error_message or "That world failed to open"
        )
    return handle


def _require_confirm(params: Dict[str, Any], action: str) -> None:
    if params.get("confirm") is not True:
        raise ProtocolError(
            ERR_CONFIRMATION_REQUIRED,
            f"'{action}' writes to the world and requires 'confirm': true. "
            "Nothing was changed.",
        )


def _require_dimension(params: Dict[str, Any], handle) -> str:
    dimension = params.get("dimension")
    if not isinstance(dimension, str) or not dimension:
        raise ProtocolError(ERR_INVALID_PARAMS, "'dimension' must be a non-empty string")
    if dimension not in handle.world.dimensions:
        raise ProtocolError(
            ERR_DIMENSION_UNKNOWN,
            f"{dimension!r} is not a dimension of this world; known dimensions "
            f"are {list(handle.world.dimensions)}",
        )
    return dimension


def _require_point(params: Dict[str, Any], field: str) -> Tuple[int, int, int]:
    value = params.get(field)
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 3
        or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value)
    ):
        raise ProtocolError(
            ERR_INVALID_PARAMS, f"'{field}' must be a [x, y, z] array of numbers"
        )
    return (int(value[0]), int(value[1]), int(value[2]))


def _require_selection_box(params: Dict[str, Any]):
    point_1 = _require_point(params, "min")
    point_2 = _require_point(params, "max")
    box = _SelectionBox(point_1, point_2)
    if box.volume <= 0:
        raise ProtocolError(
            ERR_INVALID_PARAMS,
            "The selection between 'min' and 'max' contains no blocks",
        )
    if box.volume > MAX_SELECTION_VOLUME:
        raise ProtocolError(
            ERR_SELECTION_TOO_LARGE,
            f"The selection is {box.volume} blocks, over the "
            f"{MAX_SELECTION_VOLUME}-block limit for a single fill/replace. "
            "Split it into smaller requests.",
        )
    return box


def _require_block(params: Dict[str, Any], field: str):
    raw = params.get(field)
    if not isinstance(raw, str) or not raw:
        raise ProtocolError(ERR_INVALID_PARAMS, f"'{field}' must be a non-empty string")
    try:
        return _Block.from_string_blockstate(raw)
    except Exception as exc:  # noqa: BLE001 - any parse failure is reported, never swallowed
        raise ProtocolError(
            ERR_BLOCK_UNRESOLVED, f"'{field}' ({raw!r}) did not resolve to a block: {exc}"
        )


def _slice_volume(slices: Tuple[slice, slice, slice]) -> int:
    return (
        (slices[0].stop - slices[0].start)
        * (slices[1].stop - slices[1].start)
        * (slices[2].stop - slices[2].start)
    )


def _clear_block_entities_in_range(chunk, x_min, x_max, y_min, y_max, z_min, z_max) -> None:
    for x, y, z in list(chunk.block_entities.keys()):
        if x_min <= x < x_max and y_min <= y < y_max and z_min <= z < z_max:
            chunk.block_entities.pop((x, y, z))


def _world_fill(params: Dict[str, Any]) -> Dict[str, Any]:
    _require_edit_backend()
    handle = _get_ready_handle(params)
    _require_confirm(params, "world.fill")
    dimension = _require_dimension(params, handle)
    box = _require_selection_box(params)
    block = _require_block(params, "block")

    world = handle.world
    internal_id = world.block_palette.get_add_block(block)

    blocks_changed = 0
    try:
        for chunk, slices, _box in world.get_chunk_slice_box(
            dimension, box, create_missing_chunks=True
        ):
            chunk.blocks[slices] = internal_id

            chunk_x, chunk_z = chunk.coordinates
            chunk_x *= 16
            chunk_z *= 16
            x_min = chunk_x + slices[0].start
            y_min = slices[1].start
            z_min = chunk_z + slices[2].start
            x_max = chunk_x + slices[0].stop
            y_max = slices[1].stop
            z_max = chunk_z + slices[2].stop
            _clear_block_entities_in_range(chunk, x_min, x_max, y_min, y_max, z_min, z_max)

            chunk.changed = True
            blocks_changed += _slice_volume(slices)
    except Exception:
        world.restore_last_undo_point()
        raise

    # Record the change we just made as an undo point *after* making it --
    # exactly the order the wx app's own ``run_operation`` uses (see
    # ``edit_canvas.py``). ``create_undo_point`` snapshots "what changed
    # since the last undo point", so calling it before the edit would find
    # nothing to snapshot and undo would have nothing to undo.
    world.create_undo_point()

    return {
        "world_id": handle.world_id,
        "dimension": dimension,
        "blocks_changed": blocks_changed,
        "selection_volume": box.volume,
    }


def _world_replace(params: Dict[str, Any]) -> Dict[str, Any]:
    _require_edit_backend()
    handle = _get_ready_handle(params)
    _require_confirm(params, "world.replace")
    dimension = _require_dimension(params, handle)
    box = _require_selection_box(params)
    original_block = _require_block(params, "original_block")
    replacement_block = _require_block(params, "replacement_block")

    world = handle.world
    replacement_id = world.block_palette.get_add_block(replacement_block)

    # ``world.block_palette`` is populated lazily: a freshly opened world's
    # palette holds only what has already been touched, and it grows as
    # ``get_chunk_slice_box`` below loads each chunk for the first time. So
    # this cannot be a one-shot scan taken before the loop starts -- it has
    # to re-check for newly registered universal blocks after every chunk,
    # exactly the incremental refresh the wx Replace operation uses.
    original_matches: List[int] = []
    checked_up_to = 0

    def _refresh_matches() -> None:
        nonlocal checked_up_to
        if checked_up_to >= len(world.block_palette):
            return
        for internal_id in range(checked_up_to, len(world.block_palette)):
            palette_block = world.block_palette[internal_id]
            if (
                palette_block.namespace == original_block.namespace
                and palette_block.base_name == original_block.base_name
                and dict(palette_block.properties) == dict(original_block.properties)
            ):
                original_matches.append(internal_id)
        checked_up_to = len(world.block_palette)

    blocks_changed = 0
    try:
        import numpy

        for chunk, slices, _box in world.get_chunk_slice_box(dimension, box):
            _refresh_matches()
            if not original_matches:
                continue
            blocks = chunk.blocks[slices]
            replace_mask = numpy.isin(blocks, original_matches)
            matched = int(replace_mask.sum())
            if matched:
                blocks[replace_mask] = replacement_id
                chunk.blocks[slices] = blocks
                chunk.changed = True
                blocks_changed += matched
    except Exception:
        world.restore_last_undo_point()
        raise

    # Same ordering as world.fill: snapshot after the edit, not before.
    world.create_undo_point()

    return {
        "world_id": handle.world_id,
        "dimension": dimension,
        "blocks_changed": blocks_changed,
        "selection_volume": box.volume,
    }


def _world_undo(params: Dict[str, Any]) -> Dict[str, Any]:
    _require_edit_backend()
    handle = _get_ready_handle(params)
    world = handle.world
    if world.history_manager.undo_count <= 0:
        raise ProtocolError(ERR_NOTHING_TO_UNDO, "There is nothing to undo")
    world.undo()
    return {"world_id": handle.world_id, "status": "undone"}


def _world_redo(params: Dict[str, Any]) -> Dict[str, Any]:
    _require_edit_backend()
    handle = _get_ready_handle(params)
    world = handle.world
    if world.history_manager.redo_count <= 0:
        raise ProtocolError(ERR_NOTHING_TO_REDO, "There is nothing to redo")
    world.redo()
    return {"world_id": handle.world_id, "status": "redone"}


def _world_save(params: Dict[str, Any]) -> Dict[str, Any]:
    _require_edit_backend()
    handle = _get_ready_handle(params)
    _require_confirm(params, "world.save")
    world = handle.world

    chunks_saved = 0
    for _chunk_index, chunk_count in world.save_iter():
        chunks_saved = chunk_count
    return {"world_id": handle.world_id, "status": "saved", "chunks_saved": chunks_saved}


#: Method name -> handler, merged into the sidecar's dispatch table by
#: :mod:`amulet_map_editor.api.sidecar.methods`.
EDIT_METHODS: Dict[str, Any] = {
    "world.fill": _world_fill,
    "world.replace": _world_replace,
    "world.undo": _world_undo,
    "world.redo": _world_redo,
    "world.save": _world_save,
}
