"""Sidecar methods for selection-driven editing and chunk management.

This is the third write-path module, alongside :mod:`edit_methods` (fill /
replace / undo / redo / save). Where that module edits blocks in place, this
one moves whole regions around: copy, cut, paste, delete a selection, and
create/delete whole chunks -- exactly what the wx application's own
``internal_operations`` (``copy.py``, ``cut.py``, ``delete.py``) and its
``ChunkTool`` (``programs/edit/plugins/tools/chunk.py``) do, called through
the same amulet-core APIs so the sidecar and the wx app cannot disagree
about what "copy" or "prune chunks" mean:

* :func:`_selection_copy` / :func:`_selection_cut` call
  ``BaseLevel.extract_structure`` -- the same call ``internal_operations
  /copy.py`` and ``/cut.py`` make -- and hold the resulting
  ``ImmutableStructure`` in an in-memory clipboard keyed by ``world_id``,
  mirroring ``amulet.api.structure.structure_cache``.
* :func:`_selection_paste` calls ``BaseLevel.paste`` with the clipboard's
  structure, the same call the wx Paste tool makes after
  ``canvas.paste_from_cache()``.
* :func:`_selection_delete` reuses the exact air-fill loop
  ``internal_operations/delete.py`` runs.
* :func:`_chunk_delete` / :func:`_chunk_prune` / :func:`_chunk_create` call
  ``BaseLevel.delete_chunk`` / ``BaseLevel.put_chunk`` -- the same calls
  ``ChunkTool._delete_chunks`` / ``._prune_chunks`` / ``._create_chunks``
  make.

Every rule ``edit_methods`` enforces applies here too, and this module
reuses its helpers rather than re-deriving them: nothing writes without
``confirm: true``, a selection is bounded (:data:`MAX_SELECTION_VOLUME`,
imported from ``edit_methods``), an unresolvable dimension or block string
is a structured error, and nothing reaches disk until ``world.save``.
Chunk-count operations get their own, chunk-scale bound
(:data:`MAX_CHUNK_OPERATION_COUNT`) because a "prune everything outside this
tiny selection" request can otherwise touch every chunk in an enormous
world.
"""

from __future__ import annotations

import os
import threading
from typing import Any, Dict, List, Tuple

from amulet_map_editor.api.sidecar.edit_methods import (
    MAX_SELECTION_VOLUME,
    ERR_BLOCK_UNRESOLVED,
    ERR_CONFIRMATION_REQUIRED,
    ERR_DIMENSION_UNKNOWN,
    ERR_EDIT_BACKEND_UNAVAILABLE,
    ERR_SELECTION_TOO_LARGE,
    _Block,
    _SelectionBox,
    _get_ready_handle,
    _require_block,
    _require_confirm,
    _require_dimension,
    _require_edit_backend,
    _require_point,
    _require_selection_box,
    _slice_volume,
    _clear_block_entities_in_range,
)
from amulet_map_editor.api.sidecar.protocol import ERR_INVALID_PARAMS, ProtocolError

try:  # pragma: no cover - exercised via the "not installed" degrade test
    from amulet.api.selection import SelectionGroup as _SelectionGroup
    from amulet.api.block import UniversalAirBlock as _UniversalAirBlock

    _AMULET_SELECTION_IMPORT_ERROR = None
except Exception as exc:  # noqa: BLE001 - any import-time failure degrades
    _SelectionGroup = None  # type: ignore[assignment]
    _UniversalAirBlock = None  # type: ignore[assignment]
    _AMULET_SELECTION_IMPORT_ERROR = str(exc)

#: Structured error codes specific to selection/chunk editing. Distinct from
#: ``edit_methods``'s own codes so a caller can branch on "the clipboard is
#: empty" versus "the selection was too big" without parsing text.
ERR_CLIPBOARD_EMPTY = "clipboard_empty"
ERR_STRUCTURE_LOAD_FAILED = "structure_load_failed"
ERR_STRUCTURE_WRITE_FAILED = "structure_write_failed"
ERR_DESTINATION_EXISTS = "destination_exists"
ERR_CHUNK_SELECTION_TOO_LARGE = "chunk_selection_too_large"

#: The largest number of chunks a single chunk.delete/chunk.prune/chunk.create
#: request will touch. Same reasoning as ``edit_methods.MAX_SELECTION_VOLUME``:
#: this runs synchronously inside the stdio dispatcher's per-request timeout,
#: and deleting/creating a few thousand chunks finishes quickly while an
#: unbounded "prune everything outside this box" against a huge world would
#: not. 4096 chunks is a 64x64-chunk area (1024x1024 blocks) -- generous for
#: a deliberate cleanup, small enough to stay well inside the timeout.
MAX_CHUNK_OPERATION_COUNT = 4096

#: world_id -> {"structure": ImmutableStructure, "dimension": str,
#: "blocks": int}. A real, if simple, clipboard: one pending copy/cut per
#: open world, exactly what ``amulet.api.structure.structure_cache`` offers
#: the wx app (a single most-recent structure), scoped per world instead of
#: process-global so two open worlds cannot silently share a clipboard.
_CLIPBOARD: Dict[str, Dict[str, Any]] = {}
_CLIPBOARD_LOCK = threading.Lock()


def _require_selection_group(params: Dict[str, Any]) -> Tuple[Any, Any]:
    """Returns (SelectionBox, SelectionGroup) -- most callers need both."""
    box = _require_selection_box(params)
    group = _SelectionGroup([box])
    return box, group


def _selection_copy(params: Dict[str, Any]) -> Dict[str, Any]:
    _require_edit_backend()
    handle = _get_ready_handle(params)
    dimension = _require_dimension(params, handle)
    box, group = _require_selection_group(params)

    structure = handle.world.extract_structure(group, dimension)
    with _CLIPBOARD_LOCK:
        _CLIPBOARD[handle.world_id] = {
            "structure": structure,
            "dimension": dimension,
            "blocks": box.volume,
        }
    return {
        "world_id": handle.world_id,
        "dimension": dimension,
        "blocks_copied": box.volume,
    }


def _delete_region(world, dimension: str, box, group) -> int:
    """The exact air-fill loop ``internal_operations/delete.py`` runs, shared
    by ``selection.cut`` and ``selection.delete`` so the two cannot silently
    diverge on what "delete this selection" means."""
    internal_id = world.block_palette.get_add_block(_UniversalAirBlock)
    blocks_changed = 0
    for chunk, slices, _box in world.get_chunk_slice_box(dimension, group, False):
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
    return blocks_changed


def _selection_delete(params: Dict[str, Any]) -> Dict[str, Any]:
    _require_edit_backend()
    handle = _get_ready_handle(params)
    _require_confirm(params, "selection.delete")
    dimension = _require_dimension(params, handle)
    box, group = _require_selection_group(params)

    world = handle.world
    try:
        blocks_changed = _delete_region(world, dimension, box, group)
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


def _selection_cut(params: Dict[str, Any]) -> Dict[str, Any]:
    _require_edit_backend()
    handle = _get_ready_handle(params)
    _require_confirm(params, "selection.cut")
    dimension = _require_dimension(params, handle)
    box, group = _require_selection_group(params)

    world = handle.world
    structure = world.extract_structure(group, dimension)
    try:
        blocks_changed = _delete_region(world, dimension, box, group)
    except Exception:
        world.restore_last_undo_point()
        raise
    world.create_undo_point()

    with _CLIPBOARD_LOCK:
        _CLIPBOARD[handle.world_id] = {
            "structure": structure,
            "dimension": dimension,
            "blocks": box.volume,
        }
    return {
        "world_id": handle.world_id,
        "dimension": dimension,
        "blocks_changed": blocks_changed,
        "selection_volume": box.volume,
    }


def _selection_paste(params: Dict[str, Any]) -> Dict[str, Any]:
    _require_edit_backend()
    handle = _get_ready_handle(params)
    _require_confirm(params, "selection.paste")
    dimension = _require_dimension(params, handle)
    location = _require_point(params, "location")

    with _CLIPBOARD_LOCK:
        entry = _CLIPBOARD.get(handle.world_id)
    if entry is None:
        raise ProtocolError(
            ERR_CLIPBOARD_EMPTY,
            "Nothing has been copied or cut for this world yet. Run "
            "'selection.copy' or 'selection.cut' first.",
        )

    structure = entry["structure"]
    src_dimension = structure.dimensions[0]
    world = handle.world
    try:
        world.paste(
            structure,
            src_dimension,
            structure.bounds(src_dimension),
            dimension,
            location,
        )
    except Exception:
        world.restore_last_undo_point()
        raise
    world.create_undo_point()
    return {
        "world_id": handle.world_id,
        "dimension": dimension,
        "location": list(location),
        "blocks_pasted": entry["blocks"],
    }


def _clipboard_status(params: Dict[str, Any]) -> Dict[str, Any]:
    world_id = params.get("world_id")
    if not isinstance(world_id, str) or not world_id:
        raise ProtocolError(ERR_INVALID_PARAMS, "'world_id' must be a non-empty string")
    with _CLIPBOARD_LOCK:
        entry = _CLIPBOARD.get(world_id)
    if entry is None:
        return {"world_id": world_id, "has_content": False}
    return {
        "world_id": world_id,
        "has_content": True,
        "dimension": entry["dimension"],
        "blocks": entry["blocks"],
    }


# ------------------------------------------------------------- structures


def _require_writable_destination(path: object, overwrite: bool) -> str:
    if not isinstance(path, str) or not path.strip():
        raise ProtocolError(ERR_INVALID_PARAMS, "'destination_path' must be a non-empty string")
    if "\x00" in path:
        raise ProtocolError(ERR_INVALID_PARAMS, "'destination_path' must not contain a NUL byte")
    if os.path.exists(path) and not overwrite:
        raise ProtocolError(
            ERR_DESTINATION_EXISTS,
            f"{path!r} already exists. Pass 'overwrite_confirmed': true to replace it.",
        )
    return path


def _structure_export(params: Dict[str, Any]) -> Dict[str, Any]:
    """Export a selection to a real ``.construction`` file, the same
    format+call the wx ``ExportConstruction`` operation writes with
    ``amulet.level.formats.construction.ConstructionFormatWrapper``.

    This does not write to the open world, so it is not gated behind
    ``confirm`` the way ``selection.delete``/``selection.paste`` are --
    but it can overwrite an existing file on disk, so that is gated behind
    its own explicit ``overwrite_confirmed`` flag, exactly like
    ``converter.convert``'s ``overwrite_confirmed``.
    """
    _require_edit_backend()
    handle = _get_ready_handle(params)
    dimension = _require_dimension(params, handle)
    box, group = _require_selection_group(params)
    destination = _require_writable_destination(
        params.get("destination_path"), bool(params.get("overwrite_confirmed", False))
    )

    from amulet.api.errors import ChunkLoadError
    from amulet.level.formats.construction import ConstructionFormatWrapper

    world = handle.world
    platform = params.get("platform") or world.level_wrapper.platform
    version = params.get("version") or world.level_wrapper.version
    if isinstance(version, list):
        version = tuple(version)

    try:
        wrapper = ConstructionFormatWrapper(destination)
        wrapper.create_and_open(platform, version, group, True)
        wrapper.translation_manager = world.translation_manager
        wrapper_dimension = wrapper.dimensions[0]
        chunk_count = 0
        for cx, cz in group.chunk_locations():
            try:
                chunk = world.get_chunk(cx, cz, dimension)
                wrapper.commit_chunk(chunk, wrapper_dimension)
                chunk_count += 1
            except ChunkLoadError:
                continue
        wrapper.save()
        wrapper.close()
    except ProtocolError:
        raise
    except Exception as exc:  # noqa: BLE001 - reported, never left to crash the sidecar
        raise ProtocolError(
            ERR_STRUCTURE_WRITE_FAILED, f"Could not write {destination!r}: {exc}"
        )

    return {
        "world_id": handle.world_id,
        "dimension": dimension,
        "destination_path": destination,
        "chunks_exported": chunk_count,
        "selection_volume": box.volume,
    }


def _structure_import(params: Dict[str, Any]) -> Dict[str, Any]:
    """Load a ``.construction``/``.mcstructure``/``.schematic``/``.schem``
    file with ``amulet.load_level`` (the same call the wx ``ImportTool``
    makes) and paste it into the open world, the same ``BaseLevel.paste``
    call ``selection.paste`` above uses.
    """
    _require_edit_backend()
    handle = _get_ready_handle(params)
    _require_confirm(params, "structure.import")
    dimension = _require_dimension(params, handle)
    location = _require_point(params, "location")

    source = params.get("source_path")
    if not isinstance(source, str) or not source.strip():
        raise ProtocolError(ERR_INVALID_PARAMS, "'source_path' must be a non-empty string")
    if "\x00" in source:
        raise ProtocolError(ERR_INVALID_PARAMS, "'source_path' must not contain a NUL byte")
    if not os.path.exists(source):
        raise ProtocolError(ERR_INVALID_PARAMS, f"No such path: {source!r}")

    import amulet
    from amulet.api.errors import LoaderNoneMatched

    try:
        src_level = amulet.load_level(source)
    except LoaderNoneMatched as exc:
        raise ProtocolError(
            ERR_STRUCTURE_LOAD_FAILED, f"No loader matched {source!r}: {exc}"
        )
    except Exception as exc:  # noqa: BLE001 - reported, never left to crash the sidecar
        raise ProtocolError(ERR_STRUCTURE_LOAD_FAILED, f"Could not load {source!r}: {exc}")

    try:
        src_dimension = src_level.dimensions[0]
        world = handle.world
        try:
            world.paste(
                src_level,
                src_dimension,
                src_level.bounds(src_dimension),
                dimension,
                location,
            )
        except Exception:
            world.restore_last_undo_point()
            raise
        world.create_undo_point()
    finally:
        try:
            src_level.close()
        except Exception:  # noqa: BLE001 - closing best-effort
            pass

    return {
        "world_id": handle.world_id,
        "dimension": dimension,
        "source_path": source,
        "location": list(location),
    }


# ------------------------------------------------------------------ chunks


def _require_chunk_area(params: Dict[str, Any], handle) -> Tuple[str, List[Tuple[int, int]], Any]:
    """A block-coordinate min/max, projected down to the chunk coordinates it
    covers -- and bounded by :data:`MAX_CHUNK_OPERATION_COUNT`, refused
    (never silently clamped) when it is not.
    """
    dimension = _require_dimension(params, handle)
    box, group = _require_selection_group(params)
    chunks = sorted(group.chunk_locations())
    if len(chunks) > MAX_CHUNK_OPERATION_COUNT:
        raise ProtocolError(
            ERR_CHUNK_SELECTION_TOO_LARGE,
            f"That area covers {len(chunks)} chunks, over the "
            f"{MAX_CHUNK_OPERATION_COUNT}-chunk limit for a single chunk "
            "operation. Split it into smaller requests.",
        )
    return dimension, chunks, group


def _chunk_create(params: Dict[str, Any]) -> Dict[str, Any]:
    """Create every chunk in the area that does not already exist -- never
    overwrites an existing chunk, so this is not gated behind ``confirm``
    the same way delete/prune are (nothing that already exists is touched).
    """
    _require_edit_backend()
    handle = _get_ready_handle(params)
    dimension, chunks, _group = _require_chunk_area(params, handle)

    from amulet.api.chunk import Chunk

    world = handle.world
    created = 0
    for cx, cz in chunks:
        if not world.has_chunk(cx, cz, dimension):
            world.put_chunk(Chunk(cx, cz), dimension)
            created += 1
    return {
        "world_id": handle.world_id,
        "dimension": dimension,
        "chunks_examined": len(chunks),
        "chunks_created": created,
    }


def _chunk_delete(params: Dict[str, Any]) -> Dict[str, Any]:
    """Delete every chunk within the area -- the same call ``ChunkTool.
    _delete_chunks`` makes for its "delete selected chunks" button."""
    _require_edit_backend()
    handle = _get_ready_handle(params)
    _require_confirm(params, "chunk.delete")
    dimension, chunks, _group = _require_chunk_area(params, handle)

    world = handle.world
    deleted = 0
    for cx, cz in chunks:
        if world.has_chunk(cx, cz, dimension):
            world.delete_chunk(cx, cz, dimension)
            deleted += 1
    return {
        "world_id": handle.world_id,
        "dimension": dimension,
        "chunks_examined": len(chunks),
        "chunks_deleted": deleted,
    }


def _chunk_prune(params: Dict[str, Any]) -> Dict[str, Any]:
    """Delete every chunk in the dimension that is NOT within the area --
    ``ChunkTool._prune_chunks`` / ``internal_operations/prune_chunks.py``'s
    "delete unselected" button. Bounded by the number of chunks it would
    actually remove, not by the (much smaller) kept area, since that is the
    number of ``delete_chunk`` calls this makes.
    """
    _require_edit_backend()
    handle = _get_ready_handle(params)
    _require_confirm(params, "chunk.prune")
    dimension = _require_dimension(params, handle)
    box, group = _require_selection_group(params)
    keep = group.chunk_locations()

    world = handle.world
    all_chunks = world.all_chunk_coords(dimension)
    to_delete = sorted(all_chunks.difference(keep))
    if len(to_delete) > MAX_CHUNK_OPERATION_COUNT:
        raise ProtocolError(
            ERR_CHUNK_SELECTION_TOO_LARGE,
            f"Pruning here would delete {len(to_delete)} chunks, over the "
            f"{MAX_CHUNK_OPERATION_COUNT}-chunk limit for a single chunk "
            "operation. Narrow the kept area or prune in smaller passes.",
        )

    deleted = 0
    for cx, cz in to_delete:
        world.delete_chunk(cx, cz, dimension)
        deleted += 1
    return {
        "world_id": handle.world_id,
        "dimension": dimension,
        "chunks_kept": len(all_chunks) - deleted,
        "chunks_deleted": deleted,
    }


#: Method name -> handler, merged into the sidecar's dispatch table by
#: :mod:`amulet_map_editor.api.sidecar.methods`.
SELECTION_METHODS: Dict[str, Any] = {
    "selection.copy": _selection_copy,
    "selection.cut": _selection_cut,
    "selection.paste": _selection_paste,
    "selection.delete": _selection_delete,
    "selection.clipboard_status": _clipboard_status,
    "structure.export": _structure_export,
    "structure.import": _structure_import,
    "chunk.create": _chunk_create,
    "chunk.delete": _chunk_delete,
    "chunk.prune": _chunk_prune,
}
