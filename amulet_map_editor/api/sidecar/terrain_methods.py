"""Sidecar methods for the Terrain ribbon tab's column-shaping commands.

amulet-core has no terrain *generator*: no seeded noise field, no erosion
simulation, no biome-driven regrowth pass. Every ribbon command that would
need one -- Raise, Lower, Smooth, Erode, Noise, Regenerate, Snow line, Grass
fix -- stays disabled in the ribbon with that exact reason (see
``docs/site/studio-workspace.js``); this module only wires the commands
amulet-core's own chunk/block API can genuinely perform: flattening a
selection to a target height, raising or draining the water table across a
selection, and repainting the topmost non-air block of every column.

Every operation here reuses the shared confirm/bounds/undo contract from
:mod:`amulet_map_editor.api.sidecar.edit_methods` -- the same
``_get_ready_handle``, ``_require_confirm``, ``_require_dimension``,
``_require_selection_box`` and ``_require_block`` helpers ``world.fill`` and
``world.replace`` use -- so this module cannot disagree with the write path
about what a confirmed, bounded, resolvable edit looks like. Nothing here
writes without ``confirm: true``, nothing exceeds
:data:`amulet_map_editor.api.sidecar.edit_methods.MAX_SELECTION_VOLUME`, and
every change is recorded as one undo point via the same
``world.create_undo_point`` / ``world.restore_last_undo_point`` pair the
write path already uses -- so ``world.undo`` undoes a flatten, a sea-level
change or a repaint exactly the way it undoes a fill.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from amulet_map_editor.api.sidecar.edit_methods import (
    _get_ready_handle,
    _require_block,
    _require_confirm,
    _require_dimension,
    _require_edit_backend,
    _require_selection_box,
    _slice_volume,
)
from amulet_map_editor.api.sidecar.protocol import ERR_INVALID_PARAMS, ProtocolError

try:  # pragma: no cover - exercised via the "not installed" degrade test
    from amulet.api.block import Block as _Block

    _AMULET_TERRAIN_IMPORT_ERROR: Optional[str] = None
except Exception as exc:  # noqa: BLE001 - any import-time failure degrades
    _Block = None  # type: ignore[assignment]
    _AMULET_TERRAIN_IMPORT_ERROR = str(exc)

#: Structured error codes specific to terrain shaping. Distinct from
#: :mod:`edit_methods`'s own codes for the same reason those are distinct
#: from :mod:`world_methods`'s: a caller branches on the code, never on
#: parsed English text.
ERR_SEA_LEVEL_MODE_UNKNOWN = "sea_level_mode_unknown"

_AIR_BLOCKSTATE = "universal_minecraft:air"
_WATER_BLOCKSTATE = "universal_minecraft:water"


def _air_block():
    return _Block.from_string_blockstate(_AIR_BLOCKSTATE)


def _water_block():
    return _Block.from_string_blockstate(_WATER_BLOCKSTATE)


def _require_int(params: Dict[str, Any], field: str) -> int:
    value = params.get(field)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ProtocolError(ERR_INVALID_PARAMS, f"'{field}' must be a number")
    return int(value)


def _topmost_non_air_index(column, air_id) -> Optional[int]:
    """Index of the highest ``y`` in ``column`` that is not air, or ``None``."""
    import numpy

    non_air = numpy.nonzero(column != air_id)[0]
    if non_air.size == 0:
        return None
    return int(non_air[-1])


def _terrain_flatten(params: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten every column of the selection to a single target height.

    Every block below ``height`` becomes ``block``; every block at or above
    ``height`` becomes air. ``height`` is a world Y coordinate, not an offset
    into the selection, so a caller can flatten a box that does not start at
    the target height.
    """
    _require_edit_backend()
    handle = _get_ready_handle(params)
    _require_confirm(params, "terrain.flatten")
    dimension = _require_dimension(params, handle)
    box = _require_selection_box(params)
    block = _require_block(params, "block")
    height = _require_int(params, "height")

    world = handle.world
    fill_id = world.block_palette.get_add_block(block)
    air_id = world.block_palette.get_add_block(_air_block())

    import numpy

    blocks_changed = 0
    try:
        for chunk, slices, _box in world.get_chunk_slice_box(
            dimension, box, create_missing_chunks=True
        ):
            blocks = chunk.blocks[slices]
            # ``blocks`` is a live view into the chunk's own partial-3D array
            # (see amulet.api.partial_3d_array), which only accepts a full
            # elementwise boolean mask on assignment -- not a 3-tuple index
            # with a shorter array in the middle slot. Build the mask at the
            # full shape before ever indexing into ``blocks`` with it, the
            # same way world.replace already does with numpy.isin's result.
            y_values = numpy.arange(slices[1].start, slices[1].stop)
            below_mask = numpy.zeros(blocks.shape, dtype=bool)
            below_mask[:, y_values < height, :] = True
            blocks[below_mask] = fill_id
            blocks[~below_mask] = air_id
            chunk.blocks[slices] = blocks
            chunk.changed = True
            blocks_changed += _slice_volume(slices)
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
        "height": height,
    }


def _terrain_sea_level(params: Dict[str, Any]) -> Dict[str, Any]:
    """Raise or drain the water table across a selection.

    ``mode: "raise"`` turns every air block at or below ``sea_level`` within
    the selection into water. ``mode: "drain"`` turns every water block
    anywhere in the selection into air. Neither mode touches any other
    block -- stone, dirt and everything else in the selection is untouched.
    """
    _require_edit_backend()
    handle = _get_ready_handle(params)
    _require_confirm(params, "terrain.sea_level")
    dimension = _require_dimension(params, handle)
    box = _require_selection_box(params)
    sea_level = _require_int(params, "sea_level")

    mode = params.get("mode")
    if mode not in ("raise", "drain"):
        raise ProtocolError(
            ERR_SEA_LEVEL_MODE_UNKNOWN, "'mode' must be 'raise' or 'drain'"
        )

    world = handle.world
    air_id = world.block_palette.get_add_block(_air_block())
    water_id = world.block_palette.get_add_block(_water_block())

    import numpy

    blocks_changed = 0
    try:
        for chunk, slices, _box in world.get_chunk_slice_box(dimension, box):
            blocks = chunk.blocks[slices]
            raw = numpy.array(blocks)  # a real ndarray copy, safe to read freely
            if mode == "raise":
                y_values = numpy.arange(slices[1].start, slices[1].stop)
                eligible = numpy.zeros(raw.shape, dtype=bool)
                eligible[:, y_values <= sea_level, :] = True
                mask = eligible & (raw == air_id)
                replacement = water_id
            else:
                mask = raw == water_id
                replacement = air_id
            matched = int(mask.sum())
            if matched:
                blocks[mask] = replacement
                chunk.blocks[slices] = blocks
                chunk.changed = True
                blocks_changed += matched
    except Exception:
        world.restore_last_undo_point()
        raise

    world.create_undo_point()

    return {
        "world_id": handle.world_id,
        "dimension": dimension,
        "blocks_changed": blocks_changed,
        "sea_level": sea_level,
        "mode": mode,
    }


def _terrain_repaint(params: Dict[str, Any]) -> Dict[str, Any]:
    """Repaint the topmost non-air block of every column in the selection.

    This is a block-level surface repaint (there is no biome-paint backend
    here -- see the ``Repaint`` ribbon hint), so it changes exactly the one
    highest non-air block per (x, z) column within the selection, leaving
    everything beneath it untouched. A column that is entirely air within
    the selection's Y range is left alone.
    """
    _require_edit_backend()
    handle = _get_ready_handle(params)
    _require_confirm(params, "terrain.repaint")
    dimension = _require_dimension(params, handle)
    box = _require_selection_box(params)
    block = _require_block(params, "block")

    world = handle.world
    paint_id = world.block_palette.get_add_block(block)
    air_id = world.block_palette.get_add_block(_air_block())

    import numpy

    blocks_changed = 0
    try:
        for chunk, slices, _box in world.get_chunk_slice_box(dimension, box):
            blocks = chunk.blocks[slices]
            raw = numpy.array(blocks)  # a real ndarray copy, safe to read freely
            x_span, _y_span, z_span = raw.shape
            change_mask = numpy.zeros(raw.shape, dtype=bool)
            touched = False
            for local_x in range(x_span):
                for local_z in range(z_span):
                    column = raw[local_x, :, local_z]
                    top = _topmost_non_air_index(column, air_id)
                    if top is None or column[top] == paint_id:
                        continue
                    change_mask[local_x, top, local_z] = True
                    touched = True
                    blocks_changed += 1
            if touched:
                blocks[change_mask] = paint_id
                chunk.blocks[slices] = blocks
                chunk.changed = True
    except Exception:
        world.restore_last_undo_point()
        raise

    world.create_undo_point()

    return {
        "world_id": handle.world_id,
        "dimension": dimension,
        "blocks_changed": blocks_changed,
        "selection_volume": box.volume,
    }


#: Method name -> handler, merged into the sidecar's dispatch table by
#: :mod:`amulet_map_editor.api.sidecar.methods`.
TERRAIN_METHODS: Dict[str, Any] = {
    "terrain.flatten": _terrain_flatten,
    "terrain.sea_level": _terrain_sea_level,
    "terrain.repaint": _terrain_repaint,
}
