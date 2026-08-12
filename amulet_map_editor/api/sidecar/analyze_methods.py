"""Sidecar methods for the Analyze ribbon tab -- read-only reporting over an
already-open world.

Every method here is strictly read-only: none of them call
``chunk.changed = True``, none of them call ``world.create_undo_point()``,
and none of them can reach ``world.save``. They reuse the same world-handle
registry as :mod:`world_methods` and :mod:`edit_methods` (a ``world_id``
returned by ``world.open`` is the same handle every method here operates on)
and the same bounded-selection discipline ``edit_methods.py`` already
established -- a selection over
:data:`amulet_map_editor.api.sidecar.edit_methods.MAX_SELECTION_VOLUME`
blocks is refused with the limit named, never attempted and left to time
out.

Four methods, all genuinely answerable from amulet-core's own portable
``Chunk``/``World`` API (see ``amulet_map_editor/api/core_boundary.py`` --
none of this reaches past what that boundary already lists as available):

* ``analyze.block_histogram`` -- block counts and percentages across a
  selection, using ``world.get_chunk_slice_box`` exactly like
  ``edit_methods._world_fill`` reads (never writes) chunk data.
* ``analyze.chunk_inventory`` -- per-chunk status, entity/block-entity
  counts and last-changed time for every chunk that exists in a selection's
  chunk range, via ``world.get_chunk_boxes`` with
  ``create_missing_chunks=False`` so a sparse selection is reported as
  sparse rather than silently materialising chunks as a side effect of
  inspecting them.
* ``analyze.entity_counts`` -- entities actually inside the selection box
  (not merely inside a chunk that overlaps it), counted by their real
  ``namespaced_name``.
* ``analyze.block_audit`` -- blocks in the selection whose palette entry is
  outside the ``universal_minecraft`` namespace that every other block in
  this build's translated worlds lives in. amulet translates every loaded
  block to its universal form on the way into the block palette, so a
  non-``universal_minecraft`` namespace surviving into
  ``world.block_palette`` is exactly the deprecated-or-unknown-block signal
  the wx app's own block-palette inspector already treats as worth
  flagging -- this reports it structurally instead of a human scanning a
  palette dump by eye.

What stays out of this module, and why, per this project's "a command you
cannot genuinely wire stays disabled with a reason" rule:

* **Biome map** -- amulet's ``Biomes``/``BiomeManager`` API returns indices
  into a per-chunk biome palette whose entries are raw ``Biome`` objects
  with no guaranteed stable id<->name table exposed portably across every
  installed version of PyMCTranslate; decoding that safely is a real task
  this lane did not have time to get right, so the ribbon button stays
  disabled rather than shipping a biome report that might silently name the
  wrong biome.
* **Validate / Relight / Compare** -- validating and repairing chunk data,
  recomputing block/sky light, and diffing two worlds chunk-by-chunk are
  not read operations amulet-core exposes as a single portable call; each
  would mean reimplementing real repair/lighting logic that does not exist
  in this codebase today. Faking a "validate" that only reads is worse than
  admitting it is unbuilt.
* **Measure / Slice** -- pure UI affordances (a live viewport ruler, a Y
  slice clip plane) that belong to the renderer's own viewport overlay code
  (``docs/site/viewport-overlays.js``), not to the sidecar; wiring them is
  legitimately a viewport lane's job, not this one's.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict

from amulet_map_editor.api.sidecar.edit_methods import MAX_SELECTION_VOLUME
from amulet_map_editor.api.sidecar.protocol import ERR_INVALID_PARAMS, ProtocolError
from amulet_map_editor.api.sidecar.world_methods import (
    ERR_LOAD_FAILED,
    ERR_NOT_FOUND,
    ERR_NOT_READY,
    _REGISTRY,
)

try:  # pragma: no cover - exercised via the "not installed" degrade test
    from amulet.api.selection import SelectionBox as _SelectionBox

    _AMULET_ANALYZE_IMPORT_ERROR = None
except Exception as exc:  # noqa: BLE001 - any import-time failure degrades
    _SelectionBox = None  # type: ignore[assignment]
    _AMULET_ANALYZE_IMPORT_ERROR = str(exc)

#: Structured error codes specific to analysis. Distinct from
#: :mod:`world_methods`'s and :mod:`edit_methods`'s own codes so a caller can
#: branch without parsing text.
ERR_SELECTION_TOO_LARGE = "selection_too_large"
ERR_DIMENSION_UNKNOWN = "dimension_unknown"
ERR_ANALYZE_BACKEND_UNAVAILABLE = "analyze_backend_unavailable"

#: The largest single chunk_inventory scan this module will attempt inline
#: -- a straight chunk count rather than a block volume, since chunk
#: inventory never touches ``chunk.blocks``. 256 chunks (a 16x16 chunk grid,
#: 256x256 blocks) comfortably finishes inside one request on ordinary
#: hardware.
MAX_CHUNK_COUNT = 256

#: The universal namespace every block that translated cleanly lives under.
#: Anything else surviving into ``world.block_palette`` is the audit signal.
_UNIVERSAL_NAMESPACE = "universal_minecraft"


def _require_analyze_backend() -> None:
    if _SelectionBox is None:
        raise ProtocolError(
            ERR_ANALYZE_BACKEND_UNAVAILABLE,
            "The world-format libraries (amulet-core / PyMCTranslate) are "
            "not installed in this sidecar's interpreter, so no analysis "
            f"can be performed. Import failure: {_AMULET_ANALYZE_IMPORT_ERROR}",
        )


def _get_ready_handle(params: Dict[str, Any]):
    """Shared with :mod:`edit_methods`'s own lookup: identical handling of
    an unknown, still-opening, or failed-to-open handle."""
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


def _require_point(params: Dict[str, Any], field: str):
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
            f"{MAX_SELECTION_VOLUME}-block limit for a single analysis pass. "
            "Split it into smaller requests.",
        )
    return box


def _analyze_block_histogram(params: Dict[str, Any]) -> Dict[str, Any]:
    _require_analyze_backend()
    handle = _get_ready_handle(params)
    dimension = _require_dimension(params, handle)
    box = _require_selection_box(params)

    world = handle.world
    counts: Counter = Counter()
    total = 0
    for chunk, slices, _box in world.get_chunk_slice_box(dimension, box):
        block_ids = chunk.blocks[slices]
        for internal_id, count in zip(*_unique_counts(block_ids)):
            block = world.block_palette[int(internal_id)]
            counts[f"{block.namespace}:{block.base_name}"] += int(count)
            total += int(count)

    entries = [
        {
            "block": name,
            "count": count,
            "percentage": round((count / total) * 100, 4) if total else 0.0,
        }
        for name, count in counts.most_common()
    ]
    return {
        "world_id": handle.world_id,
        "dimension": dimension,
        "selection_volume": box.volume,
        "blocks_scanned": total,
        "distinct_blocks": len(counts),
        "histogram": entries,
    }


def _unique_counts(array):
    """``numpy.unique(array, return_counts=True)`` without a hard top-level
    numpy import for every caller of this module -- amulet already depends
    on numpy, so this simply defers the import to call time, matching how
    ``edit_methods._world_replace`` imports numpy lazily."""
    import numpy

    return numpy.unique(array, return_counts=True)


def _analyze_chunk_inventory(params: Dict[str, Any]) -> Dict[str, Any]:
    _require_analyze_backend()
    handle = _get_ready_handle(params)
    dimension = _require_dimension(params, handle)
    box = _require_selection_box(params)

    min_cx, min_cz = box.min_x >> 4, box.min_z >> 4
    max_cx, max_cz = (box.max_x - 1) >> 4, (box.max_z - 1) >> 4
    chunk_count = (max_cx - min_cx + 1) * (max_cz - min_cz + 1)
    if chunk_count > MAX_CHUNK_COUNT:
        raise ProtocolError(
            ERR_SELECTION_TOO_LARGE,
            f"That selection spans {chunk_count} chunks, over the "
            f"{MAX_CHUNK_COUNT}-chunk limit for a single chunk inventory. "
            "Split it into smaller requests.",
        )

    world = handle.world
    chunks = []
    for chunk, _cbox in world.get_chunk_boxes(dimension, box, create_missing_chunks=False):
        chunks.append(
            {
                "cx": chunk.cx,
                "cz": chunk.cz,
                "status": str(chunk.status),
                "changed": bool(chunk.changed),
                "changed_time": chunk.changed_time,
                "entity_count": len(chunk.entities),
                "block_entity_count": len(chunk.block_entities),
            }
        )

    return {
        "world_id": handle.world_id,
        "dimension": dimension,
        "chunk_range": {"min": [min_cx, min_cz], "max": [max_cx, max_cz]},
        "chunks_in_range": chunk_count,
        "chunks_present": len(chunks),
        "chunks": chunks,
    }


def _analyze_entity_counts(params: Dict[str, Any]) -> Dict[str, Any]:
    _require_analyze_backend()
    handle = _get_ready_handle(params)
    dimension = _require_dimension(params, handle)
    box = _require_selection_box(params)

    world = handle.world
    counts: Counter = Counter()
    total = 0
    for chunk, _cbox in world.get_chunk_boxes(dimension, box, create_missing_chunks=False):
        for entity in chunk.entities:
            if (entity.x, entity.y, entity.z) not in box:
                continue
            counts[entity.namespaced_name] += 1
            total += 1

    entries = [{"entity": name, "count": count} for name, count in counts.most_common()]
    return {
        "world_id": handle.world_id,
        "dimension": dimension,
        "selection_volume": box.volume,
        "entities_found": total,
        "distinct_entity_types": len(counts),
        "entities": entries,
    }


def _analyze_block_audit(params: Dict[str, Any]) -> Dict[str, Any]:
    _require_analyze_backend()
    handle = _get_ready_handle(params)
    dimension = _require_dimension(params, handle)
    box = _require_selection_box(params)

    world = handle.world
    flagged: Counter = Counter()
    total = 0
    for chunk, slices, _box in world.get_chunk_slice_box(dimension, box):
        block_ids = chunk.blocks[slices]
        for internal_id, count in zip(*_unique_counts(block_ids)):
            total += int(count)
            block = world.block_palette[int(internal_id)]
            if block.namespace != _UNIVERSAL_NAMESPACE:
                flagged[f"{block.namespace}:{block.base_name}"] += int(count)

    entries = [{"block": name, "count": count} for name, count in flagged.most_common()]
    return {
        "world_id": handle.world_id,
        "dimension": dimension,
        "selection_volume": box.volume,
        "blocks_scanned": total,
        "flagged_blocks": entries,
        "flagged_count": sum(flagged.values()),
    }


#: Method name -> handler, merged into the sidecar's dispatch table by
#: :mod:`amulet_map_editor.api.sidecar.methods`.
ANALYZE_METHODS: Dict[str, Any] = {
    "analyze.block_histogram": _analyze_block_histogram,
    "analyze.chunk_inventory": _analyze_chunk_inventory,
    "analyze.entity_counts": _analyze_entity_counts,
    "analyze.block_audit": _analyze_block_audit,
}
