"""Standalone (no pytest) benchmark for the mesh boundary, run with real numbers.

Not part of the test suite -- this is meant to be run by hand (``python -m
amulet_map_editor.api.sidecar.benchmark_mesh``) whenever the streaming radius
or the batching strategy in ``mesh_methods.py`` is under review, so a change
is justified by a fresh before/after number rather than a guess. It builds a
real Java world on disk, fills a block of chunks with a checkerboard of solid
blocks (dense enough that every sub-chunk actually meshes real faces, unlike
an empty superflat world which would report near-zero vertices and hide the
real cost), then times:

* meshing a single chunk through the same code path ``viewport.chunk_mesh``
  uses (``_sub_chunks_for`` + ``create_lod0_chunk``);
* writing that chunk's vertex buffer to disk and reading it back, the exact
  round trip the Electron renderer performs today (one file per chunk);
* the same total work batched into one buffer/one file, for comparison.

No GPU, no OpenGL context, no Electron -- pure Python/NumPy timing, which is
the honest evidence this repository's rules ask for. Frame rates and real
draw-call counts stay unmeasured; this only measures the sidecar-side cost
this lane owns.
"""

from __future__ import annotations

import os
import shutil
import statistics
import tempfile
import time

CHECKER_BLOCK = "minecraft:stone"


def _build_world(root: str, radius: int):
    from amulet.level.formats.anvil_world import AnvilFormat
    from amulet.api.level import World

    world_path = os.path.join(root, "bench-world")
    fmt = AnvilFormat(world_path)
    fmt.create_and_open("java", (1, 20, 4), overwrite=True)
    fmt.close()

    from amulet.api.block import Block

    world = World(world_path, AnvilFormat(world_path))
    dimension = "minecraft:overworld"
    span = radius * 16 + 16
    block = Block("minecraft", "stone")
    # A checkerboard rather than a solid fill: a fully solid volume would
    # mesh only its outer faces (culled interior), which understates the
    # real vertex cost of a natural, cavity-riddled world.
    for x in range(-span, span, 2):
        for z in range(-span, span, 2):
            for y in range(60, 70):
                world.set_version_block(
                    x, y, z, dimension, ("java", (1, 20, 4)), block
                )
    world.save()
    world.close()
    return world_path


def _timed(label: str, fn, repeats: int = 3):
    samples = []
    result = None
    for _ in range(repeats):
        start = time.perf_counter()
        result = fn()
        samples.append(time.perf_counter() - start)
    mean = statistics.mean(samples)
    print(f"{label}: mean={mean * 1000:.2f}ms samples={[f'{s * 1000:.2f}ms' for s in samples]}")
    return result, mean


def main() -> None:
    from amulet.level.formats.anvil_world import AnvilFormat
    from amulet.api.level import World

    from amulet_map_editor.api.sidecar.mesh_methods import (
        _PACKS,
        _sub_chunks_for,
    )
    from amulet_map_editor.api.opengl.mesh.level.chunk.chunk_builder_cy import (
        create_lod0_chunk,
    )
    import numpy

    radius = int(os.environ.get("BENCH_RADIUS", "2"))
    tmp_root = tempfile.mkdtemp(prefix="amulet-mesh-bench-")
    try:
        print(f"Building a {radius * 2 + 1}x{radius * 2 + 1}-chunk checkerboard world...")
        world_path = _build_world(tmp_root, radius)

        world = World(world_path, AnvilFormat(world_path))
        dimension = "minecraft:overworld"

        status = _PACKS.ensure_building(world_path, world)
        deadline = time.time() + 60
        while status not in ("ready", "failed") and time.time() < deadline:
            time.sleep(0.1)
            status = _PACKS.status(world_path)
        if status != "ready":
            print(f"resource pack failed to build: {_PACKS.error(world_path)}")
            return
        gl_pack = _PACKS.get_ready(world_path)

        vert_len = 12
        offset = numpy.array([0, 0, 0], dtype=numpy.int_)

        def mesh_one(cx: int, cz: int):
            chunk = world.get_chunk(cx, cz, dimension)
            sub_chunks = _sub_chunks_for(world, dimension, cx, cz, chunk.blocks)
            opaque, translucent = create_lod0_chunk(
                gl_pack, offset, sub_chunks, chunk.block_palette, vert_len
            )
            parts = [p for p in (opaque + translucent) if p is not None]
            if not parts:
                return numpy.zeros(0, dtype=numpy.float32)
            return numpy.concatenate(parts, None).astype("<f4", copy=False)

        verts, mesh_mean = _timed("mesh one chunk (0,0)", lambda: mesh_one(0, 0))
        vertex_count = int(verts.size // vert_len)
        byte_count = verts.nbytes
        print(f"  -> {vertex_count} vertices, {byte_count} bytes")

        # Per-chunk file round trip (today's behaviour).
        def write_and_read_one():
            path = os.path.join(tmp_root, "one.bin")
            verts.tofile(path)
            with open(path, "rb") as fh:
                fh.read()
            os.remove(path)

        _timed("write+read one chunk (per-file, today)", write_and_read_one)

        # Batched: mesh every chunk in the requested radius, concatenate
        # into one buffer, one file.
        chunk_coords = [
            (cx, cz)
            for cx in range(-radius, radius + 1)
            for cz in range(-radius, radius + 1)
        ]
        print(f"\nBatching {len(chunk_coords)} chunks (radius={radius}):")

        def mesh_all():
            return [mesh_one(cx, cz) for cx, cz in chunk_coords]

        all_verts, mesh_all_mean = _timed("mesh all chunks in radius", mesh_all, repeats=1)
        total_bytes = sum(v.nbytes for v in all_verts)
        total_vertices = sum(int(v.size // vert_len) for v in all_verts)
        print(f"  -> {total_vertices} total vertices, {total_bytes} total bytes")
        print(f"  -> extrapolated per-chunk cost: {mesh_all_mean / len(chunk_coords) * 1000:.2f}ms/chunk")

        def write_and_read_batched():
            combined = numpy.concatenate(all_verts) if all_verts else numpy.zeros(0, dtype=numpy.float32)
            path = os.path.join(tmp_root, "batch.bin")
            combined.tofile(path)
            with open(path, "rb") as fh:
                fh.read()
            os.remove(path)

        _timed("write+read ALL chunks (one batched file)", write_and_read_batched, repeats=3)

        def write_and_read_per_file_all():
            paths = []
            for i, v in enumerate(all_verts):
                path = os.path.join(tmp_root, f"perfile-{i}.bin")
                v.tofile(path)
                paths.append(path)
            for path in paths:
                with open(path, "rb") as fh:
                    fh.read()
                os.remove(path)

        _timed("write+read ALL chunks (one file per chunk, today)", write_and_read_per_file_all, repeats=3)

        world.close()
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


if __name__ == "__main__":
    main()
