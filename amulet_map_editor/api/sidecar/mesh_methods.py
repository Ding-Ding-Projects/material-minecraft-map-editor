"""Sidecar methods that mesh a real chunk for the Electron WebGL2 viewport.

The design this module implements is fixed and documented in
``docs/articles/webgl2-viewport.md`` (see that file for the full rationale):
meshing stays in Python -- the existing Cython mesher in
:mod:`amulet_map_editor.api.opengl.mesh.level.chunk.chunk_builder_cy` already
produces exactly what a GPU wants, an interleaved float32 array of
``position(vec3) texcoord(vec2) texoffset(vec4) tint(vec3)`` -- and only the
camera, draw loop and buffer uploads move to JavaScript.

Two things make this module different from an ordinary sidecar method:

* **No OpenGL context.** :class:`~amulet_map_editor.api.opengl.mesh.level.
  chunk.chunk.RenderChunk` is built for a wx GL canvas, but every step this
  module calls on it -- ``create_geometry()``, the sub-chunk assembly, the
  Cython mesher -- is pure NumPy. The only GL-touching methods on that class
  (``_setup``/``change_verts``) are simply never called here.
* **Vertex data is too big for the newline-delimited JSON wire protocol.**
  A single chunk's mesh is tens of thousands of floats; base64-encoding that
  into a JSON string would be an order of magnitude more bytes on the wire
  for no reason. Instead this module writes the raw float32 bytes (and the
  atlas PNG bytes) to a file under a per-sidecar-process temp directory and
  returns the file path plus enough metadata (vertex count, the fixed
  12-float stride, the opaque/translucent split offset) for the renderer to
  ``fs.readFile`` it as a Buffer and hand the ``ArrayBuffer`` straight to
  ``gl.bufferData``. Electron's main process is the only thing that reads
  that path from the renderer's request (see ``electron/main.js``), and it
  refuses any path outside this module's own temp directory before opening
  it -- the sidecar never becomes a general file-read oracle.
"""

from __future__ import annotations

import os
import tempfile
import threading
import uuid
from typing import Any, Dict, Optional, Tuple

from amulet_map_editor.api.sidecar.protocol import ERR_INVALID_PARAMS, ProtocolError
from amulet_map_editor.api.sidecar.world_methods import (
    ERR_LOAD_FAILED,
    ERR_NOT_FOUND,
    ERR_NOT_READY,
    _REGISTRY,  # the same world-handle registry world_methods.py already owns
)

try:  # pragma: no cover - exercised via the "not installed" degrade test
    from minecraft_model_reader.api.resource_pack import (
        load_resource_pack,
        load_resource_pack_manager,
    )

    from amulet_map_editor.api.opengl.mesh.level.chunk.chunk import RenderChunk
    from amulet_map_editor.api.opengl.resource_pack.resource_pack import (
        OpenGLResourcePack,
    )

    _MESH_IMPORT_ERROR: Optional[str] = None
except Exception as exc:  # noqa: BLE001 - any import-time failure degrades
    RenderChunk = None  # type: ignore[assignment]
    OpenGLResourcePack = None  # type: ignore[assignment]
    load_resource_pack = None  # type: ignore[assignment]
    load_resource_pack_manager = None  # type: ignore[assignment]
    _MESH_IMPORT_ERROR = str(exc)

ERR_MESH_BACKEND_UNAVAILABLE = "mesh_backend_unavailable"
ERR_CHUNK_COORD = "invalid_chunk_coord"

#: The one directory this sidecar process will ever write mesh/atlas binary
#: files into, and the one directory Electron's main process will ever read
#: a "sidecar:readBinary" path from. Namespaced by pid so two concurrent
#: sidecar processes (e.g. two open editor windows) never collide.
_TEMP_ROOT = os.path.join(
    tempfile.gettempdir(), "amulet-viewport-mesh", str(os.getpid())
)


def temp_root() -> str:
    """The bound Electron's main process enforces on binary-file reads."""
    return _TEMP_ROOT


def _ensure_temp_root() -> str:
    os.makedirs(_TEMP_ROOT, exist_ok=True)
    return _TEMP_ROOT


def _require_backend() -> None:
    if RenderChunk is None:
        raise ProtocolError(
            ERR_MESH_BACKEND_UNAVAILABLE,
            "The resource-pack / mesh libraries are not installed in this "
            f"sidecar's interpreter, so no chunk can be meshed. Import "
            f"failure: {_MESH_IMPORT_ERROR}",
        )


def _get_ready_world(world_id: object):
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


class _ResourcePackCache:
    """One lazily-built :class:`OpenGLResourcePack` per open world.

    Building it (loading the bundled pack, running ``setup()`` to generate
    the texture atlas) is real work -- seconds, not milliseconds -- so it
    happens once per ``world_id`` and is reused by every subsequent
    ``viewport.chunk_mesh`` call, guarded by a lock so two concurrent first
    requests for the same world don't both pay to build it.

    Deliberately uses only the resource pack bundled with this repository
    (``amulet_map_editor/amulet_resource_pack/java``) rather than also
    downloading the vanilla Java resource pack the wx canvas fetches over
    the network -- that download is slow, needs network access this sidecar
    should not require, and is out of scope for this first pass. Blocks
    therefore render with whatever texture the bundled pack has for them,
    falling back to the pack's own "missing texture" placeholder -- the
    geometry and atlas pipeline is real, the *texture art* is incomplete.
    See the "what's missing" section of the article for the honest list.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._packs: Dict[str, "OpenGLResourcePack"] = {}
        self._atlas_paths: Dict[str, str] = {}
        #: world_id -> "building" | "ready" | "failed". Building a resource
        #: pack (downloading vanilla textures on first run, packing a
        #: 4096x4096 atlas every run) routinely takes far longer than the
        #: sidecar dispatcher's per-request timeout, so it never runs
        #: inline on the request thread -- it runs on its own background
        #: thread exactly the way ``world.open`` defers a slow
        #: ``load_level`` call, and callers poll ``viewport.prepare``
        #: (cheap, near-instant) the same way they poll
        #: ``world.open_status``.
        self._status: Dict[str, str] = {}
        self._errors: Dict[str, str] = {}

    def status(self, world_id: str) -> str:
        with self._lock:
            return self._status.get(world_id, "unstarted")

    def ensure_building(self, world_id: str, world) -> str:
        """Kick off the background build if it hasn't started; idempotent."""
        with self._lock:
            current = self._status.get(world_id)
            if current is not None:
                return current
            self._status[world_id] = "building"
        thread = threading.Thread(
            target=self._build_worker, args=(world_id, world), daemon=True
        )
        thread.start()
        return "building"

    def _build_worker(self, world_id: str, world) -> None:
        try:
            gl_pack = self._build(world)
        except Exception as exc:  # noqa: BLE001 - reported, never raised on this thread
            with self._lock:
                self._status[world_id] = "failed"
                self._errors[world_id] = str(exc)
            return
        with self._lock:
            self._packs[world_id] = gl_pack
            self._status[world_id] = "ready"

    def error(self, world_id: str) -> str:
        with self._lock:
            return self._errors.get(world_id, "unknown error")

    def get_ready(self, world_id: str) -> "OpenGLResourcePack":
        with self._lock:
            pack = self._packs.get(world_id)
        if pack is None:
            raise ProtocolError(ERR_NOT_READY, "The resource pack is not ready yet")
        return pack

    def _build(self, world) -> "OpenGLResourcePack":
        import amulet_map_editor.programs.edit as _edit_pkg

        platform = "bedrock" if world.level_wrapper.platform == "bedrock" else "java"
        bundled_dir = os.path.join(
            os.path.dirname(_edit_pkg.__file__), "amulet_resource_pack", platform
        )
        # The bundled "amulet_resource_pack" only carries the editor's own
        # UI textures (selection box, missing-texture placeholder) -- it
        # has no block models at all, so meshing against it alone produces
        # zero faces for every real block. The wx canvas's
        # ``base_edit_canvas.py`` solves this by downloading the real
        # vanilla Java resource pack (block models + textures) from
        # Mojang's own launcher manifest and layering the bundled pack's
        # "fix" pack on top for the handful of blocks vanilla's JSON
        # models get wrong for a flat renderer. Do the same here -- this is
        # the one place this module reaches the network, and it is the
        # same official Mojang download path a Minecraft launcher itself
        # uses, cached under CACHE_DIR exactly as the wx canvas caches it.
        if platform == "java":
            from minecraft_model_reader.api.resource_pack.java.download_resources import (
                get_java_vanilla_fix,
                get_java_vanilla_latest,
            )

            packs = [
                load_resource_pack(bundled_dir),
                get_java_vanilla_latest(),
                get_java_vanilla_fix(),
            ]
        else:
            from minecraft_model_reader.api.resource_pack.bedrock.download_resources import (
                get_bedrock_vanilla_fix,
                get_bedrock_vanilla_latest,
            )

            packs = [
                load_resource_pack(bundled_dir),
                get_bedrock_vanilla_latest(),
                get_bedrock_vanilla_fix(),
            ]
        manager = load_resource_pack_manager(packs, load=False)
        for _ in manager.reload():
            pass

        translator = world.translation_manager.get_version(platform, (999, 0, 0))
        gl_pack = OpenGLResourcePack(manager, translator)
        for _ in gl_pack.setup():
            pass
        return gl_pack

    def atlas_path(self, world_id: str, gl_pack: "OpenGLResourcePack") -> Tuple[str, int, int]:
        with self._lock:
            existing = self._atlas_paths.get(world_id)
            if existing is not None and os.path.exists(existing):
                return existing, gl_pack._image_width, gl_pack._image_height

            _ensure_temp_root()
            path = os.path.join(_TEMP_ROOT, f"atlas-{world_id}.png")
            image = gl_pack._image
            if image is None:
                raise ProtocolError(
                    ERR_MESH_BACKEND_UNAVAILABLE, "The texture atlas failed to build"
                )
            # ``_image`` is whatever OpenGLResourcePack.setup() stored -- a
            # PIL Image on some builds, a raw numpy RGBA array on others
            # (it is fed straight to glTexImage2D either way). Normalise to
            # a PIL Image only for this PNG export.
            if hasattr(image, "convert"):
                pil_image = image.convert("RGBA")
            else:
                from PIL import Image as _PILImage

                width, height = gl_pack._image_width, gl_pack._image_height
                pil_image = _PILImage.fromarray(
                    image.reshape((height, width, 4)), mode="RGBA"
                )
            pil_image.save(path, format="PNG")
            self._atlas_paths[world_id] = path
            return path, gl_pack._image_width, gl_pack._image_height


_PACKS = _ResourcePackCache()


def _viewport_temp_root(_params: Dict[str, Any]) -> Dict[str, Any]:
    """The one directory this process will ever write mesh/atlas files
    into. Electron's main process calls this once and refuses to read any
    ``viewport.chunk_mesh``/``viewport.atlas`` path that does not resolve
    inside it -- see the "sidecar:readBinary" handler in electron/main.js.
    """
    return {"path": _ensure_temp_root()}


def _viewport_prepare(params: Dict[str, Any]) -> Dict[str, Any]:
    """Kick off (or poll) building the resource pack for a world.

    Idempotent and cheap: the first call starts the real work (possibly a
    vanilla-texture download plus packing a 4096x4096 atlas) on a
    background thread and returns ``{"status": "building"}`` immediately;
    every call after that -- including the first -- is a near-instant
    status read. Callers poll this exactly the way ``world.open`` callers
    poll ``world.open_status``. ``viewport.atlas`` and
    ``viewport.chunk_mesh`` both also call this internally so a caller that
    skips straight to them still gets a clean ``resource_pack_not_ready``
    error rather than a request that silently blocks on the wire.
    """
    _require_backend()
    handle = _get_ready_world(params.get("world_id"))
    status = _PACKS.ensure_building(handle.world_id, handle.world)
    if status == "failed":
        raise ProtocolError(ERR_MESH_BACKEND_UNAVAILABLE, _PACKS.error(handle.world_id))
    return {"world_id": handle.world_id, "status": status}


def _viewport_atlas(params: Dict[str, Any]) -> Dict[str, Any]:
    _require_backend()
    handle = _get_ready_world(params.get("world_id"))
    status = _PACKS.ensure_building(handle.world_id, handle.world)
    if status == "failed":
        raise ProtocolError(ERR_MESH_BACKEND_UNAVAILABLE, _PACKS.error(handle.world_id))
    if status != "ready":
        raise ProtocolError(ERR_NOT_READY, "The resource pack is still building")
    gl_pack = _PACKS.get_ready(handle.world_id)
    path, width, height = _PACKS.atlas_path(handle.world_id, gl_pack)
    return {"path": path, "width": width, "height": height, "format": "rgba8"}


def _sub_chunks_for(world, dimension: str, cx: int, cz: int, blocks):
    """The same neighbour-aware sub-chunk assembly RenderChunk._sub_chunks
    does, reimplemented here as a free function so it can run against a
    world without an OpenGL-context-carrying RenderChunk instance having to
    exist first. Kept byte-for-byte equivalent to that method."""
    import numpy
    from amulet.api.errors import ChunkLoadError
    from amulet.api.selection import SelectionBox

    sub_chunks = []
    neighbour_chunks = {}
    for dx, dz in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        try:
            neighbour_chunks[(dx, dz)] = world.get_chunk(
                cx + dx, cz + dz, dimension
            ).blocks
        except ChunkLoadError:
            continue

    for cy in blocks.sub_chunks:
        sub_chunk = blocks.get_sub_chunk(cy)
        larger_blocks = numpy.zeros(sub_chunk.shape + numpy.array((2, 2, 2)), sub_chunk.dtype)
        larger_blocks[1:-1, 1:-1, 1:-1] = sub_chunk
        for chunk_offset, neighbour_blocks in neighbour_chunks.items():
            if cy not in neighbour_blocks:
                continue
            if chunk_offset == (-1, 0):
                larger_blocks[0, 1:-1, 1:-1] = neighbour_blocks.get_sub_chunk(cy)[-1, :, :]
            elif chunk_offset == (1, 0):
                larger_blocks[-1, 1:-1, 1:-1] = neighbour_blocks.get_sub_chunk(cy)[0, :, :]
            elif chunk_offset == (0, -1):
                larger_blocks[1:-1, 1:-1, 0] = neighbour_blocks.get_sub_chunk(cy)[:, :, -1]
            elif chunk_offset == (0, 1):
                larger_blocks[1:-1, 1:-1, -1] = neighbour_blocks.get_sub_chunk(cy)[:, :, 0]
        if cy - 1 in blocks:
            larger_blocks[1:-1, 0, 1:-1] = blocks.get_sub_chunk(cy - 1)[:, -1, :]
        if cy + 1 in blocks:
            larger_blocks[1:-1, -1, 1:-1] = blocks.get_sub_chunk(cy + 1)[:, 0, :]
        sub_chunks.append((larger_blocks, cy * 16))
    return sub_chunks


def _viewport_chunk_mesh(params: Dict[str, Any]) -> Dict[str, Any]:
    _require_backend()
    handle = _get_ready_world(params.get("world_id"))
    world = handle.world

    pack_status = _PACKS.ensure_building(handle.world_id, world)
    if pack_status == "failed":
        raise ProtocolError(ERR_MESH_BACKEND_UNAVAILABLE, _PACKS.error(handle.world_id))
    if pack_status != "ready":
        raise ProtocolError(ERR_NOT_READY, "The resource pack is still building")

    dimension = params.get("dimension")
    if not isinstance(dimension, str) or not dimension:
        raise ProtocolError(ERR_INVALID_PARAMS, "'dimension' must be a non-empty string")
    if dimension not in world.dimensions:
        raise ProtocolError(ERR_INVALID_PARAMS, f"Unknown dimension: {dimension!r}")

    cx, cz = params.get("cx"), params.get("cz")
    if not isinstance(cx, int) or not isinstance(cz, int):
        raise ProtocolError(ERR_CHUNK_COORD, "'cx' and 'cz' must be integers")

    from amulet.api.errors import ChunkDoesNotExist, ChunkLoadError

    try:
        chunk = world.get_chunk(cx, cz, dimension)
    except ChunkDoesNotExist:
        return {"exists": False, "path": None, "vertex_count": 0}
    except ChunkLoadError as exc:
        raise ProtocolError(ERR_LOAD_FAILED, f"Failed to load chunk ({cx}, {cz}): {exc}")

    gl_pack = _PACKS.get_ready(handle.world_id)

    import numpy

    from amulet_map_editor.api.opengl.mesh.level.chunk.chunk_builder_cy import (
        create_lod0_chunk,
    )

    sub_chunks = _sub_chunks_for(world, dimension, cx, cz, chunk.blocks)
    vert_len = 12  # position(3) + texcoord(2) + texoffset(4) + tint(3)
    # Matches RenderChunk.offset's dtype exactly -- the Cython mesher
    # expects a C ``long`` buffer here, not a float array. Vertices come
    # out chunk-local (0..16 in x/z); (cx, cz) placement is the renderer's
    # job at draw time, same division of labour RenderChunk/RenderRegion
    # already use.
    offset = numpy.array([0, 0, 0], dtype=numpy.int_)
    opaque_parts, translucent_parts = create_lod0_chunk(
        gl_pack, offset, sub_chunks, chunk.block_palette, vert_len
    )

    if opaque_parts:
        verts = numpy.concatenate(opaque_parts, None)
        translucent_offset = int(verts.size // vert_len)
    else:
        verts = numpy.zeros(0, dtype=numpy.float32)
        translucent_offset = 0
    if translucent_parts:
        verts = numpy.concatenate([verts, *translucent_parts], None)

    verts = verts.astype("<f4", copy=False)

    _ensure_temp_root()
    mesh_id = uuid.uuid4().hex
    path = os.path.join(_TEMP_ROOT, f"mesh-{mesh_id}.bin")
    verts.tofile(path)

    vertex_count = int(verts.size // vert_len)
    return {
        "exists": True,
        "path": path,
        "vertex_stride_floats": vert_len,
        "vertex_count": vertex_count,
        "opaque_vertex_count": translucent_offset,
        "translucent_vertex_count": vertex_count - translucent_offset,
        "cx": cx,
        "cz": cz,
    }


#: Method name -> handler, merged into the sidecar's dispatch table by
#: :mod:`amulet_map_editor.api.sidecar.methods`.
MESH_METHODS: Dict[str, Any] = {
    "viewport.temp_root": _viewport_temp_root,
    "viewport.prepare": _viewport_prepare,
    "viewport.atlas": _viewport_atlas,
    "viewport.chunk_mesh": _viewport_chunk_mesh,
}
