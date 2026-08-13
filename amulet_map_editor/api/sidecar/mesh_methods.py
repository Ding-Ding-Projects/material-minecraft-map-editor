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

#: Base names (namespace stripped) that a picking ray must pass THROUGH
#: rather than stop at. Air is the obvious one; water and lava are the less
#: obvious ones -- a picker that treats a lake's surface as solid can never
#: select the lakebed under it, which is exactly as wrong as a picker that
#: treats air as ground. Anything else in a palette (stone, logs, leaves,
#: fences, torches, ...) is treated as solid. This is a coarse per-block-type
#: rule, not a per-voxel collision shape -- a torch occupies its whole voxel
#: for picking purposes even though its visual model does not, which matches
#: how the wx app's own selection tools already treat blocks.
_NON_SOLID_BASE_NAMES = frozenset(
    {
        "air",
        "cave_air",
        "void_air",
        "water",
        "flowing_water",
        "lava",
        "flowing_lava",
        "bubble_column",
    }
)

#: Occupancy is packed one bit per block, 16(x) x 16(y) x 16(z) = 4096 bits
#: = 512 bytes per sub-chunk. Documented once, here, because an off-by-one
#: in bit order makes picking miss by one block everywhere -- it reads as
#: "the ray is slightly wrong" rather than as a packing bug, and costs a day
#: to find if it is not written down.
#:
#: For local (in-sub-chunk) coordinates lx, ly, lz each in [0, 16):
#:     bit_index = (ly * 16 + lz) * 16 + lx
#:     byte_index = bit_index // 8
#:     bit_in_byte = bit_index % 8          (bit 0 = least-significant bit)
#:     solid = (byte[byte_index] >> bit_in_byte) & 1 == 1
#: i.e. numpy.packbits(bits, bitorder="little") over a (16, 16, 16) boolean
#: array whose axes are (y, z, x) in that order, C-contiguous, flattened.
OCCUPANCY_DIM = 16
OCCUPANCY_BITS_PER_SUB_CHUNK = OCCUPANCY_DIM * OCCUPANCY_DIM * OCCUPANCY_DIM
OCCUPANCY_BYTES_PER_SUB_CHUNK = OCCUPANCY_BITS_PER_SUB_CHUNK // 8

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
        raise ProtocolError(
            ERR_NOT_FOUND, f"No open (or opening) world with id {world_id!r}"
        )
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

    def atlas_path(
        self, world_id: str, gl_pack: "OpenGLResourcePack"
    ) -> Tuple[str, int, int]:
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

#: Bounds how many mesh files a single world's chunk streaming keeps on disk
#: at once. The WebGL2 viewport streams chunks around a moving camera (see
#: docs/site/viewport-panel.js) and re-requests "viewport.chunk_mesh" as the
#: camera roams, each call writing a fresh temp file -- without a cap those
#: files would accumulate for the lifetime of the sidecar process. Keyed
#: per-world so two open worlds don't evict each other's chunks.
_MESH_FILE_CACHE_LIMIT = 256
_mesh_file_lock = threading.Lock()
_mesh_files_by_world: Dict[str, "OrderedDict[Tuple[int, int], str]"] = {}


def _remember_mesh_file(world_id: str, cx: int, cz: int, path: str) -> None:
    from collections import OrderedDict

    with _mesh_file_lock:
        files = _mesh_files_by_world.setdefault(world_id, OrderedDict())
        key = (cx, cz)
        old_path = files.pop(key, None)
        files[key] = path
        if old_path and old_path != path and os.path.exists(old_path):
            try:
                os.remove(old_path)
            except OSError:
                pass
        while len(files) > _MESH_FILE_CACHE_LIMIT:
            _, evicted_path = files.popitem(last=False)
            try:
                os.remove(evicted_path)
            except OSError:
                pass


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
        larger_blocks = numpy.zeros(
            sub_chunk.shape + numpy.array((2, 2, 2)), sub_chunk.dtype
        )
        larger_blocks[1:-1, 1:-1, 1:-1] = sub_chunk
        for chunk_offset, neighbour_blocks in neighbour_chunks.items():
            if cy not in neighbour_blocks:
                continue
            if chunk_offset == (-1, 0):
                larger_blocks[0, 1:-1, 1:-1] = neighbour_blocks.get_sub_chunk(cy)[
                    -1, :, :
                ]
            elif chunk_offset == (1, 0):
                larger_blocks[-1, 1:-1, 1:-1] = neighbour_blocks.get_sub_chunk(cy)[
                    0, :, :
                ]
            elif chunk_offset == (0, -1):
                larger_blocks[1:-1, 1:-1, 0] = neighbour_blocks.get_sub_chunk(cy)[
                    :, :, -1
                ]
            elif chunk_offset == (0, 1):
                larger_blocks[1:-1, 1:-1, -1] = neighbour_blocks.get_sub_chunk(cy)[
                    :, :, 0
                ]
        if cy - 1 in blocks:
            larger_blocks[1:-1, 0, 1:-1] = blocks.get_sub_chunk(cy - 1)[:, -1, :]
        if cy + 1 in blocks:
            larger_blocks[1:-1, -1, 1:-1] = blocks.get_sub_chunk(cy + 1)[:, 0, :]
        sub_chunks.append((larger_blocks, cy * 16))
    return sub_chunks


def _occupancy_for_chunk(world, dimension: str, cx: int, cz: int):
    """Compute the per-sub-chunk solid/non-solid occupancy bitset for one
    chunk, entirely from the block palette this chunk already carries --
    no neighbour chunks needed (unlike meshing, occupancy for picking never
    looks across a chunk boundary; a ray that crosses one just asks again).

    Returns ``(exists, sub_chunks)`` where ``sub_chunks`` is a list of
    ``{"cy": int, "bytes": bytes}`` in ascending ``cy`` order, one entry per
    sub-chunk that actually exists in this chunk (an entirely-air column has
    no sub-chunks at all, and that is a valid, common answer: it means
    "nothing here is solid", not "unknown").
    """
    import numpy
    from amulet.api.errors import ChunkDoesNotExist, ChunkLoadError

    try:
        chunk = world.get_chunk(cx, cz, dimension)
    except (ChunkDoesNotExist, ChunkLoadError):
        return False, []

    palette = chunk.block_palette
    solid_lut = numpy.ones(len(palette), dtype=bool)
    for index, block in enumerate(palette):
        base_name = getattr(block, "base_name", None)
        if base_name in _NON_SOLID_BASE_NAMES:
            solid_lut[index] = False

    sub_chunks = []
    for cy in sorted(chunk.blocks.sub_chunks):
        # get_sub_chunk(cy) is (x, y, z)-shaped, values = palette index --
        # see _sub_chunks_for's neighbour-padding above, which relies on the
        # exact same axis order.
        sub = chunk.blocks.get_sub_chunk(cy)
        solid = solid_lut[sub]
        ordered = numpy.transpose(solid, (1, 2, 0))  # (x,y,z) -> (y,z,x)
        packed = numpy.packbits(
            numpy.ascontiguousarray(ordered).reshape(-1), bitorder="little"
        )
        sub_chunks.append({"cy": int(cy), "bytes": packed.tobytes()})
    return True, sub_chunks


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
        raise ProtocolError(
            ERR_INVALID_PARAMS, "'dimension' must be a non-empty string"
        )
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
        raise ProtocolError(
            ERR_LOAD_FAILED, f"Failed to load chunk ({cx}, {cz}): {exc}"
        )

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
    _remember_mesh_file(handle.world_id, cx, cz, path)

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


def _mesh_one_chunk(
    world, dimension: str, cx: int, cz: int, gl_pack: "OpenGLResourcePack"
) -> Tuple[bool, "numpy.ndarray", int]:
    """The pure meshing step ``_viewport_chunk_mesh`` runs for one chunk,
    pulled out so the batch path below can call it in a loop without paying
    for a second copy of the same logic. Returns
    ``(exists, verts, opaque_vertex_count)``.
    """
    import numpy

    from amulet.api.errors import ChunkDoesNotExist, ChunkLoadError
    from amulet_map_editor.api.opengl.mesh.level.chunk.chunk_builder_cy import (
        create_lod0_chunk,
    )

    try:
        chunk = world.get_chunk(cx, cz, dimension)
    except ChunkDoesNotExist:
        return False, numpy.zeros(0, dtype=numpy.float32), 0
    except ChunkLoadError:
        return False, numpy.zeros(0, dtype=numpy.float32), 0

    vert_len = 12
    offset = numpy.array([0, 0, 0], dtype=numpy.int_)
    sub_chunks = _sub_chunks_for(world, dimension, cx, cz, chunk.blocks)
    opaque_parts, translucent_parts = create_lod0_chunk(
        gl_pack, offset, sub_chunks, chunk.block_palette, vert_len
    )
    if opaque_parts:
        verts = numpy.concatenate(opaque_parts, None)
        opaque_count = int(verts.size // vert_len)
    else:
        verts = numpy.zeros(0, dtype=numpy.float32)
        opaque_count = 0
    if translucent_parts:
        verts = numpy.concatenate([verts, *translucent_parts], None)
    return True, verts.astype("<f4", copy=False), opaque_count


#: How many chunks a single ``viewport.chunk_mesh_batch`` call accepts. The
#: benchmark in ``benchmark_mesh.py`` measured a 9x9 (radius 4, 81-chunk)
#: batch at ~415ms of meshing plus ~155ms of combined-file I/O against a
#: dense checkerboard world -- real work, but far short of the sidecar's
#: request timeout. A cap keeps one runaway request from blocking the stdio
#: loop for an unbounded time; a caller that wants a bigger area sends more
#: than one batch.
_MAX_BATCH_CHUNKS = 128

#: Bounds how many *batches'* worth of combined mesh files stay on disk at
#: once, independent of the per-chunk cache above -- a batch that is
#: requested and never polled to completion (a stale streaming tick, an
#: aborted camera move) must not leak a file forever.
_BATCH_FILE_CACHE_LIMIT = 16
_batch_lock = threading.Lock()
_batches: Dict[str, Dict[str, Any]] = {}
_batch_order: "list[str]" = []


def _evict_batches_locked() -> None:
    while len(_batch_order) > _BATCH_FILE_CACHE_LIMIT:
        oldest = _batch_order.pop(0)
        entry = _batches.pop(oldest, None)
        if not entry:
            continue
        for key in ("path", "occupancy_path"):
            file_path = entry.get(key)
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except OSError:
                    pass


def _run_batch_worker(batch_id: str, world, dimension: str, chunks) -> None:
    try:
        results = []
        buffers = []
        cursor = 0
        occ_buffers = []
        occ_cursor = 0
        gl_pack = _PACKS.get_ready(_batches[batch_id]["world_id"])
        for cx, cz in chunks:
            exists, verts, opaque_count = _mesh_one_chunk(
                world, dimension, cx, cz, gl_pack
            )
            vertex_count = int(verts.size // 12)
            if exists and vertex_count:
                buffers.append(verts)
                byte_length = int(verts.nbytes)
            else:
                byte_length = 0

            # Occupancy rides this same batch/poll/release lifecycle rather
            # than a second IPC channel -- it is computed alongside the mesh
            # for every chunk in the batch and shipped in the same response,
            # just via its own combined buffer (occupancy is orders of
            # magnitude smaller than the interleaved vertex data, so it is
            # kept separate rather than interleaved into one file).
            occ_exists, occ_sub_chunks = _occupancy_for_chunk(world, dimension, cx, cz)
            occ_meta = []
            for sub in occ_sub_chunks:
                data = sub["bytes"]
                occ_buffers.append(data)
                occ_meta.append(
                    {
                        "cy": sub["cy"],
                        "byte_offset": occ_cursor,
                        "byte_length": len(data),
                    }
                )
                occ_cursor += len(data)

            results.append(
                {
                    "cx": cx,
                    "cz": cz,
                    "exists": exists,
                    "vertex_count": vertex_count,
                    "opaque_vertex_count": opaque_count if exists else 0,
                    "translucent_vertex_count": (
                        (vertex_count - opaque_count) if exists else 0
                    ),
                    "byte_offset": cursor,
                    "byte_length": byte_length,
                    "occupancy_exists": occ_exists,
                    "occupancy_sub_chunks": occ_meta,
                }
            )
            cursor += byte_length

        import numpy

        combined = (
            numpy.concatenate(buffers)
            if buffers
            else numpy.zeros(0, dtype=numpy.float32)
        )
        _ensure_temp_root()
        path = os.path.join(_TEMP_ROOT, f"mesh-batch-{batch_id}.bin")
        combined.tofile(path)

        occ_combined = b"".join(occ_buffers)
        occ_path = os.path.join(_TEMP_ROOT, f"occupancy-batch-{batch_id}.bin")
        with open(occ_path, "wb") as fh:
            fh.write(occ_combined)

        with _batch_lock:
            entry = _batches.get(batch_id)
            if entry is None:
                # Released/evicted while we were working -- clean up and stop.
                for stale_path in (path, occ_path):
                    try:
                        os.remove(stale_path)
                    except OSError:
                        pass
                return
            entry["status"] = "ready"
            entry["path"] = path
            entry["occupancy_path"] = occ_path
            entry["chunks"] = results
    except Exception as exc:  # noqa: BLE001 - reported, never raised on this thread
        with _batch_lock:
            entry = _batches.get(batch_id)
            if entry is not None:
                entry["status"] = "failed"
                entry["error"] = str(exc)


def _viewport_chunk_mesh_batch(params: Dict[str, Any]) -> Dict[str, Any]:
    """Kick off meshing a batch of chunks in the background and return
    immediately, following the same "background thread + poll" pattern
    ``world.open``/``viewport.prepare`` already use -- a batch big enough to
    be worth batching (see the benchmark) is also big enough to be worth
    keeping off the synchronous stdio-dispatch path, so it never delays an
    unrelated ``preferences.*``/``world.fill`` call sitting behind it in the
    pipe.
    """
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
        raise ProtocolError(
            ERR_INVALID_PARAMS, "'dimension' must be a non-empty string"
        )
    if dimension not in world.dimensions:
        raise ProtocolError(ERR_INVALID_PARAMS, f"Unknown dimension: {dimension!r}")

    raw_chunks = params.get("chunks")
    if not isinstance(raw_chunks, list) or not raw_chunks:
        raise ProtocolError(ERR_INVALID_PARAMS, "'chunks' must be a non-empty list")
    if len(raw_chunks) > _MAX_BATCH_CHUNKS:
        raise ProtocolError(
            ERR_INVALID_PARAMS,
            f"'chunks' may contain at most {_MAX_BATCH_CHUNKS} entries per batch, got {len(raw_chunks)}",
        )
    chunks = []
    for entry in raw_chunks:
        if (
            not isinstance(entry, (list, tuple))
            or len(entry) != 2
            or not isinstance(entry[0], int)
            or not isinstance(entry[1], int)
        ):
            raise ProtocolError(
                ERR_CHUNK_COORD, "Each entry in 'chunks' must be [cx, cz] integers"
            )
        chunks.append((entry[0], entry[1]))

    batch_id = uuid.uuid4().hex
    with _batch_lock:
        _batches[batch_id] = {
            "status": "pending",
            "world_id": handle.world_id,
            "path": None,
            "occupancy_path": None,
            "chunks": None,
            "error": None,
        }
        _batch_order.append(batch_id)
        _evict_batches_locked()

    thread = threading.Thread(
        target=_run_batch_worker, args=(batch_id, world, dimension, chunks), daemon=True
    )
    thread.start()
    return {"batch_id": batch_id, "status": "pending"}


def _viewport_chunk_mesh_batch_status(params: Dict[str, Any]) -> Dict[str, Any]:
    batch_id = params.get("batch_id")
    if not isinstance(batch_id, str) or not batch_id:
        raise ProtocolError(ERR_INVALID_PARAMS, "'batch_id' must be a non-empty string")
    with _batch_lock:
        entry = _batches.get(batch_id)
        if entry is None:
            raise ProtocolError(ERR_NOT_FOUND, f"No such mesh batch: {batch_id!r}")
        status = entry["status"]
        if status == "ready":
            return {
                "batch_id": batch_id,
                "status": "ready",
                "path": entry["path"],
                "vertex_stride_floats": 12,
                "occupancy_path": entry["occupancy_path"],
                "occupancy_dim": OCCUPANCY_DIM,
                "occupancy_bytes_per_sub_chunk": OCCUPANCY_BYTES_PER_SUB_CHUNK,
                "chunks": entry["chunks"],
            }
        if status == "failed":
            return {"batch_id": batch_id, "status": "failed", "error": entry["error"]}
        return {"batch_id": batch_id, "status": "pending"}


def _viewport_chunk_mesh_batch_release(params: Dict[str, Any]) -> Dict[str, Any]:
    """Free a batch's combined mesh file once the caller has read it, rather
    than waiting for the LRU cap in :func:`_evict_batches_locked` to get
    around to it. Idempotent: releasing an unknown/already-released id is
    not an error, since a caller racing eviction is expected, not a bug."""
    batch_id = params.get("batch_id")
    if not isinstance(batch_id, str) or not batch_id:
        raise ProtocolError(ERR_INVALID_PARAMS, "'batch_id' must be a non-empty string")
    with _batch_lock:
        entry = _batches.pop(batch_id, None)
        if batch_id in _batch_order:
            _batch_order.remove(batch_id)
    if entry:
        for key in ("path", "occupancy_path"):
            file_path = entry.get(key)
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except OSError:
                    pass
    return {"batch_id": batch_id, "released": entry is not None}


#: Method name -> handler, merged into the sidecar's dispatch table by
#: :mod:`amulet_map_editor.api.sidecar.methods`.
MESH_METHODS: Dict[str, Any] = {
    "viewport.temp_root": _viewport_temp_root,
    "viewport.prepare": _viewport_prepare,
    "viewport.atlas": _viewport_atlas,
    "viewport.chunk_mesh": _viewport_chunk_mesh,
    "viewport.chunk_mesh_batch": _viewport_chunk_mesh_batch,
    "viewport.chunk_mesh_batch_status": _viewport_chunk_mesh_batch_status,
    "viewport.chunk_mesh_batch_release": _viewport_chunk_mesh_batch_release,
}
