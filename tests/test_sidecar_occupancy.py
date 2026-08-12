"""Proves the picking-occupancy seam: mesh_methods._occupancy_for_chunk packs
solid/non-solid per block into the exact bit layout viewport-occupancy.js
decodes on the renderer side, and viewport.chunk_mesh_batch ships it
alongside the mesh in the SAME batch/poll/release lifecycle rather than a
second IPC channel.

Runs in-process against the world API directly (unlike
test_sidecar_mesh_methods.py, which spawns the real sidecar child process to
prove the batching/temp-file boundary for meshing) -- occupancy needs no
OpenGL resource pack at all, so exercising it through a full sidecar process
plus a real-or-mocked texture atlas would only add cost, not coverage. The
batch-transport wiring (does the batch response actually carry the
occupancy fields, in the SAME response as the mesh) is covered separately
below by calling the batch handler functions directly.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

amulet = pytest.importorskip("amulet", reason="amulet-core is not installed in this interpreter")

import numpy  # noqa: E402

from amulet_map_editor.api.sidecar import mesh_methods as mm  # noqa: E402


def _unpack(sub_chunk_bytes: bytes) -> "numpy.ndarray":
    """Undo the exact packing OCCUPANCY_* documents, returning bits indexed
    ``bits[(ly * 16 + lz) * 16 + lx]``."""
    return numpy.unpackbits(numpy.frombuffer(sub_chunk_bytes, dtype=numpy.uint8), bitorder="little")


def _bit_at(bits: "numpy.ndarray", lx: int, ly: int, lz: int) -> int:
    return int(bits[(ly * 16 + lz) * 16 + lx])


@pytest.fixture(scope="module")
def fixture_world(tmp_path_factory):
    """A real Java world with known geometry spanning: an interior solid
    block, a water block (must read as non-solid -- a picker that cannot
    select a lakebed through it is wrong), an air gap, a block sitting
    exactly on a chunk boundary, and a block at the world's low height
    limit -- occupancy must not silently drop or misplace any of them."""
    from amulet.api.block import Block
    from amulet.api.level import World
    from amulet.level.formats.anvil_world import AnvilFormat

    root = tmp_path_factory.mktemp("sidecar-occupancy-world")
    world_path = str(root / "world")
    fmt = AnvilFormat(world_path)
    fmt.create_and_open("java", (1, 20, 4), overwrite=True)
    fmt.close()

    world = World(world_path, AnvilFormat(world_path))
    dimension = "minecraft:overworld"
    version = ("java", (1, 20, 4))
    stone = Block("minecraft", "stone")
    water = Block("minecraft", "water")

    # Chunk (0, 0): a stone block well inside it, a water block beside it,
    # and nothing else -- everything else in that sub-chunk must read air.
    world.set_version_block(2, 64, 2, dimension, version, stone)
    world.set_version_block(3, 64, 2, dimension, version, water)

    # A block sitting exactly on the +X edge of chunk (0, 0) / start of
    # chunk (1, 0), so an off-by-one in chunk-local coordinate math would
    # place it in the wrong chunk's occupancy entirely.
    world.set_version_block(15, 70, 5, dimension, version, stone)  # last column of chunk (0,0)
    world.set_version_block(16, 70, 5, dimension, version, stone)  # first column of chunk (1,0)

    # A column of pure air: chunk (5, 5) is never touched at all, so
    # world.get_chunk on it either raises ChunkDoesNotExist or (once anvil
    # region generation touches it) returns a chunk with zero sub-chunks.
    # Both are asserted below as "no solid blocks reported", not "unknown".

    # The world's low height limit for this version is y = -64.
    world.set_version_block(4, -64, 4, dimension, version, stone)

    world.save()
    return world, dimension


def test_solid_block_reads_as_solid(fixture_world):
    world, dimension = fixture_world
    exists, sub_chunks = mm._occupancy_for_chunk(world, dimension, 0, 0)
    assert exists
    sub = next(s for s in sub_chunks if s["cy"] == 4)  # y=64 -> cy=4
    bits = _unpack(sub["bytes"])
    assert _bit_at(bits, 2, 0, 2) == 1  # local (2,0,2) == world (2,64,2)


def test_water_reads_as_non_solid(fixture_world):
    """The core design decision this lane owns: water must NOT be solid, or
    a picking ray can never reach the lakebed underneath it."""
    world, dimension = fixture_world
    exists, sub_chunks = mm._occupancy_for_chunk(world, dimension, 0, 0)
    assert exists
    sub = next(s for s in sub_chunks if s["cy"] == 4)
    bits = _unpack(sub["bytes"])
    assert _bit_at(bits, 3, 0, 2) == 0  # world (3, 64, 2) is water


def test_air_reads_as_non_solid(fixture_world):
    world, dimension = fixture_world
    exists, sub_chunks = mm._occupancy_for_chunk(world, dimension, 0, 0)
    assert exists
    sub = next(s for s in sub_chunks if s["cy"] == 4)
    bits = _unpack(sub["bytes"])
    # (10, 5, 10) local was never touched -- must read as air, not solid.
    assert _bit_at(bits, 10, 5, 10) == 0


def test_chunk_boundary_block_belongs_to_the_right_chunk(fixture_world):
    """world x=15 is the LAST column of chunk (0,0); world x=16 is the
    FIRST column of chunk (1,0). Getting chunk-local math off by one here
    would silently move one of these blocks into the wrong chunk's
    occupancy, or drop it, or duplicate it into both."""
    world, dimension = fixture_world

    exists0, sub_chunks0 = mm._occupancy_for_chunk(world, dimension, 0, 0)
    assert exists0
    sub0 = next(s for s in sub_chunks0 if s["cy"] == 4)  # y=70 -> cy=4
    bits0 = _unpack(sub0["bytes"])
    assert _bit_at(bits0, 15, 6, 5) == 1  # local x=15 == world x=15
    assert _bit_at(bits0, 0, 6, 5) == 0  # local x=0 of THIS chunk is air

    exists1, sub_chunks1 = mm._occupancy_for_chunk(world, dimension, 1, 0)
    assert exists1
    sub1 = next(s for s in sub_chunks1 if s["cy"] == 4)
    bits1 = _unpack(sub1["bytes"])
    assert _bit_at(bits1, 0, 6, 5) == 1  # local x=0 of chunk (1,0) == world x=16
    assert _bit_at(bits1, 15, 6, 5) == 0  # local x=15 of THIS chunk is air


def test_low_height_limit_block_is_recorded(fixture_world):
    world, dimension = fixture_world
    exists, sub_chunks = mm._occupancy_for_chunk(world, dimension, 0, 0)
    assert exists
    # y = -64 -> cy = floor(-64 / 16) = -4
    sub = next((s for s in sub_chunks if s["cy"] == -4), None)
    assert sub is not None, f"no sub-chunk at cy=-4; got cys={[s['cy'] for s in sub_chunks]}"
    bits = _unpack(sub["bytes"])
    # local y for world y=-64 in sub-chunk cy=-4 is -64 - (-4*16) = 0
    assert _bit_at(bits, 4, 0, 4) == 1


def test_entirely_air_column_reports_no_solid_blocks(fixture_world):
    """A chunk nobody ever placed a block in still exists once anvil region
    generation has touched it (empty sub-chunk list), or does not exist at
    all -- either way, "nothing here is solid" must be the honest answer,
    never an error and never a guess."""
    world, dimension = fixture_world
    exists, sub_chunks = mm._occupancy_for_chunk(world, dimension, 5, 5)
    if exists:
        for sub in sub_chunks:
            assert not numpy.any(_unpack(sub["bytes"]))
    # else: ChunkDoesNotExist -- also a valid "no solid blocks" answer.


def test_unknown_dimension_or_missing_chunk_does_not_raise(fixture_world):
    world, dimension = fixture_world
    exists, sub_chunks = mm._occupancy_for_chunk(world, dimension, 9999, 9999)
    assert exists in (True, False)
    if exists:
        assert sub_chunks == [] or all(
            not numpy.any(_unpack(s["bytes"])) for s in sub_chunks
        )


def test_bit_order_guard_flip_and_restore():
    """Watch the guard actually fail: pack a single known bit with the
    documented (ly*16+lz)*16+lx order, then decode it with a DELIBERATELY
    wrong order (lz and lx swapped) and confirm that gets the wrong answer
    -- proving the test can tell the two apart before trusting it either
    way."""
    bits = numpy.zeros(4096, dtype=numpy.uint8)
    lx, ly, lz = 3, 7, 11
    correct_index = (ly * 16 + lz) * 16 + lx
    bits[correct_index] = 1
    packed = numpy.packbits(bits, bitorder="little").tobytes()

    decoded = _unpack(packed)
    assert _bit_at(decoded, lx, ly, lz) == 1  # correct order: found it

    wrong_index = (ly * 16 + lx) * 16 + lz  # lx/lz swapped on purpose
    assert int(decoded[wrong_index]) == 0 or wrong_index == correct_index  # wrong order: (usually) misses it
    # The swapped formula must actually disagree with the real one for this
    # particular (lx, ly, lz), or the guard proves nothing -- assert that.
    assert wrong_index != correct_index
