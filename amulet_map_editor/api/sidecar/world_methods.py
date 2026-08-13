"""Sidecar methods for real world access -- the read-only half.

This is deliberately the first slice: opening a world by path, reading back
its identity and dimension bounds, listing the recent-worlds store, and
closing a handle to release it. Nothing here ever writes to a world. Writing
(placing blocks, running an operation, saving) is a separate, later lane's
job, and this module must never grow a method that could commit a chunk.

Two things make this module careful rather than a thin wrapper around
``amulet.load_level``:

* **The path is untrusted.** It arrives from the renderer over the sidecar's
  stdio pipe, so :func:`_validate_world_path` resolves it, rejects anything
  that does not exist, and rejects anything that is not an ordinary
  directory or file (a socket, a device node, a FIFO) before it is ever
  handed to the world-format libraries.
* **Opening a world must not block the whole sidecar.** The dispatcher
  (:mod:`amulet_map_editor.api.sidecar.server`) reads one stdio line at a
  time and runs each request's handler on its own thread with a bounded
  join -- but that join still blocks the *next* line from being read for as
  long as the handler runs. A huge or slow world's ``load_level`` call can
  take far longer than the sidecar's default per-request timeout, so
  ``world.open`` does not run it inline: it hands the load to its own
  background worker thread and returns immediately with a ``pending``
  status. The caller polls ``world.open_status`` (a cheap, near-instant
  call) until the load finishes, fails, or is abandoned. This keeps every
  other request -- including a concurrent ``preferences.read`` or a second
  ``world.open`` -- answerable in milliseconds regardless of how long the
  first world takes to load.

If the world-format libraries (``amulet-core`` / ``PyMCTranslate``) are not
installed in the interpreter running the sidecar, every method in this
module degrades to a structured ``world_backend_unavailable`` error instead
of raising an ``ImportError`` up through the dispatcher.
"""

from __future__ import annotations

import os
import stat
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from amulet_map_editor.api.sidecar.protocol import ERR_INVALID_PARAMS, ProtocolError

try:  # pragma: no cover - exercised via the "not installed" degrade test
    from amulet import load_level as _amulet_load_level
    from amulet.api.errors import LoaderNoneMatched as _LoaderNoneMatched

    _AMULET_IMPORT_ERROR: Optional[str] = None
except Exception as exc:  # noqa: BLE001 - any import-time failure degrades
    _amulet_load_level = None
    _LoaderNoneMatched = Exception  # type: ignore[assignment]
    _AMULET_IMPORT_ERROR = str(exc)

from amulet_map_editor.api.studio import recents as RECENTS

#: Structured error codes specific to world access. Distinct from the
#: generic protocol codes in :mod:`protocol` so a caller can branch on
#: "the world backend is not installed" versus "the path was bad" versus
#: "that handle does not exist" without parsing English message text.
ERR_PATH_NOT_FOUND = "world_path_not_found"
ERR_PATH_UNSUPPORTED = "world_path_unsupported"
ERR_LOAD_FAILED = "world_load_failed"
ERR_NOT_FOUND = "world_not_found"
ERR_NOT_READY = "world_not_ready"
ERR_BACKEND_UNAVAILABLE = "world_backend_unavailable"

#: Longest path this method will accept, matching the recents store's own
#: field-length ceiling so the two bounds agree.
MAX_PATH_LENGTH = 1024


def _require_backend() -> None:
    if _amulet_load_level is None:
        raise ProtocolError(
            ERR_BACKEND_UNAVAILABLE,
            "The world-format libraries (amulet-core / PyMCTranslate) are "
            "not installed in this sidecar's interpreter, so no world can "
            f"be opened. Import failure: {_AMULET_IMPORT_ERROR}",
        )


def _validate_world_path(raw_path: object) -> str:
    """Resolve and validate an untrusted path before it reaches amulet.

    Returns the resolved, absolute path on success. Raises
    :class:`ProtocolError` for every other outcome -- never lets a bad path
    reach ``load_level`` unexamined.
    """
    if not isinstance(raw_path, str) or not raw_path:
        raise ProtocolError(ERR_INVALID_PARAMS, "'path' must be a non-empty string")
    if "\x00" in raw_path:
        raise ProtocolError(ERR_INVALID_PARAMS, "'path' must not contain a NUL byte")
    if len(raw_path) > MAX_PATH_LENGTH:
        raise ProtocolError(
            ERR_INVALID_PARAMS,
            f"'path' is {len(raw_path)} characters, over the {MAX_PATH_LENGTH}-character limit",
        )
    if not os.path.isabs(raw_path):
        raise ProtocolError(
            ERR_INVALID_PARAMS,
            "'path' must be an absolute path (a relative path is ambiguous "
            "against the sidecar's own working directory, not the "
            "renderer's)",
        )

    try:
        resolved = os.path.realpath(raw_path, strict=True)
    except OSError as exc:
        raise ProtocolError(ERR_PATH_NOT_FOUND, f"'path' could not be resolved: {exc}")

    if not os.path.exists(resolved):
        raise ProtocolError(ERR_PATH_NOT_FOUND, f"No such path: {resolved!r}")

    try:
        mode = os.stat(resolved).st_mode
    except OSError as exc:
        raise ProtocolError(ERR_PATH_NOT_FOUND, f"'path' could not be inspected: {exc}")

    # Only an ordinary directory (a Java/Bedrock world save folder) or an
    # ordinary file (a structure export) is a world.load_level candidate.
    # A socket, FIFO, character device or block device is refused here,
    # before it is ever handed to the world-format libraries.
    if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
        raise ProtocolError(
            ERR_PATH_UNSUPPORTED,
            f"'path' is neither a directory nor a regular file: {resolved!r}",
        )

    return resolved


@dataclass
class _WorldHandle:
    """One open (or opening, or closing) world, keyed by an opaque id."""

    world_id: str
    path: str
    status: str = "pending"  # pending -> ready | failed ; ready -> closing -> closed
    world: Any = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    opened_at: float = 0.0


class _WorldRegistry:
    """Tracks open world handles across the sidecar's lifetime.

    A dict guarded by a lock rather than anything fancier -- the number of
    concurrently open worlds in a single desktop session is small, and the
    lock is only ever held for the handful of dict operations below, never
    across a call into amulet itself.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._handles: Dict[str, _WorldHandle] = {}

    def create_pending(self, path: str) -> _WorldHandle:
        handle = _WorldHandle(world_id=str(uuid.uuid4()), path=path)
        with self._lock:
            self._handles[handle.world_id] = handle
        return handle

    def get(self, world_id: str) -> Optional[_WorldHandle]:
        with self._lock:
            return self._handles.get(world_id)

    def drop(self, world_id: str) -> Optional[_WorldHandle]:
        with self._lock:
            return self._handles.pop(world_id, None)

    def list(self) -> List[_WorldHandle]:
        with self._lock:
            return list(self._handles.values())


#: Module-level registry. The sidecar is a single child process per editor
#: session, so a module-level registry is the whole of the process's world
#: state -- there is nothing above it to own this instead.
_REGISTRY = _WorldRegistry()


def _load_worker(handle: _WorldHandle) -> None:
    """Runs on its own background thread; never touches the stdio pipe."""
    try:
        world = _amulet_load_level(handle.path)
    except _LoaderNoneMatched as exc:
        handle.status = "failed"
        handle.error_code = ERR_LOAD_FAILED
        handle.error_message = f"No world-format loader matched this path: {exc}"
        return
    except Exception as exc:  # noqa: BLE001 - reported, never raised on this thread
        handle.status = "failed"
        handle.error_code = ERR_LOAD_FAILED
        handle.error_message = f"Failed to open world: {exc}"
        return
    handle.world = world
    handle.opened_at = time.time()
    handle.status = "ready"


def _identity(handle: _WorldHandle) -> Dict[str, Any]:
    world = handle.world
    level_wrapper = world.level_wrapper
    version = level_wrapper.version
    return {
        "world_id": handle.world_id,
        "path": handle.path,
        "name": level_wrapper.level_name,
        "platform": level_wrapper.platform,
        "version": list(version) if isinstance(version, tuple) else version,
        "dimensions": list(world.dimensions),
    }


def _world_open(params: Dict[str, Any]) -> Dict[str, Any]:
    _require_backend()
    resolved_path = _validate_world_path(params.get("path"))
    handle = _REGISTRY.create_pending(resolved_path)
    thread = threading.Thread(target=_load_worker, args=(handle,), daemon=True)
    thread.start()
    return {"world_id": handle.world_id, "status": "pending"}


def _world_open_status(params: Dict[str, Any]) -> Dict[str, Any]:
    world_id = params.get("world_id")
    if not isinstance(world_id, str) or not world_id:
        raise ProtocolError(ERR_INVALID_PARAMS, "'world_id' must be a non-empty string")
    handle = _REGISTRY.get(world_id)
    if handle is None:
        raise ProtocolError(
            ERR_NOT_FOUND, f"No open (or opening) world with id {world_id!r}"
        )
    if handle.status == "pending":
        return {"world_id": world_id, "status": "pending"}
    if handle.status == "failed":
        return {
            "world_id": world_id,
            "status": "failed",
            "error": {"code": handle.error_code, "message": handle.error_message},
        }
    return {"status": "ready", **_identity(handle)}


def _world_dimensions(params: Dict[str, Any]) -> Dict[str, Any]:
    world_id = params.get("world_id")
    if not isinstance(world_id, str) or not world_id:
        raise ProtocolError(ERR_INVALID_PARAMS, "'world_id' must be a non-empty string")
    handle = _REGISTRY.get(world_id)
    if handle is None:
        raise ProtocolError(
            ERR_NOT_FOUND, f"No open (or opening) world with id {world_id!r}"
        )
    if handle.status == "pending":
        raise ProtocolError(ERR_NOT_READY, "That world is still opening")
    if handle.status == "failed":
        raise ProtocolError(
            ERR_LOAD_FAILED, handle.error_message or "That world failed to open"
        )

    world = handle.world
    dimensions = []
    for dimension in world.dimensions:
        try:
            bounds = world.bounds(dimension)
            min_point = list(bounds.min)
            max_point = list(bounds.max)
        except Exception as exc:  # noqa: BLE001 - reported per-dimension, not fatal
            dimensions.append(
                {
                    "dimension": dimension,
                    "bounds": None,
                    "error": str(exc),
                }
            )
            continue
        dimensions.append(
            {
                "dimension": dimension,
                "bounds": {"min": min_point, "max": max_point},
            }
        )
    return {"world_id": world_id, "dimensions": dimensions}


def _close_worker(handle: _WorldHandle) -> None:
    try:
        handle.world.close()
    except (
        Exception
    ):  # noqa: BLE001 - closing best-effort; handle is dropped regardless
        pass


def _world_close(params: Dict[str, Any]) -> Dict[str, Any]:
    world_id = params.get("world_id")
    if not isinstance(world_id, str) or not world_id:
        raise ProtocolError(ERR_INVALID_PARAMS, "'world_id' must be a non-empty string")
    handle = _REGISTRY.drop(world_id)
    if handle is None:
        raise ProtocolError(
            ERR_NOT_FOUND, f"No open (or opening) world with id {world_id!r}"
        )
    if handle.status == "ready" and handle.world is not None:
        # Closing (flushing any read caches, releasing file locks) can take
        # a moment on a large world; run it off the stdio thread exactly as
        # opening does, rather than making the caller wait on this request.
        thread = threading.Thread(target=_close_worker, args=(handle,), daemon=True)
        thread.start()
    return {"world_id": world_id, "status": "closed"}


def _recents_list(_params: Dict[str, Any]) -> Dict[str, Any]:
    entries = RECENTS.list_entries()
    return {"entries": [entry.to_dict() for entry in entries]}


#: Method name -> handler, merged into the sidecar's dispatch table by
#: :mod:`amulet_map_editor.api.sidecar.methods`.
WORLD_METHODS: Dict[str, Any] = {
    "world.open": _world_open,
    "world.open_status": _world_open_status,
    "world.dimensions": _world_dimensions,
    "world.close": _world_close,
    "recents.list": _recents_list,
}
