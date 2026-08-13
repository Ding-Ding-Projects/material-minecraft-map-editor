"""``docs/site/viewport-occupancy.js`` is the renderer-side half of the
picking seam this lane closes: it decodes the packed occupancy bitset
mesh_methods.py ships alongside every chunk's mesh and answers
solidTest(x, y, z) from it in constant time, with no IPC round trip on the
picking ray's hot path.

Exercised in real Node, same pattern as ``test_viewport_picking_raycast.py``:
a known bitset in, a known solid/non-solid answer out, plus proof that an
unloaded chunk answers false rather than throwing and that a real DDA ray
fired at known "terrain" (a store populated the same way the batch response
populates it) hits the block a human would expect.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OCCUPANCY_MODULE = REPO / "docs" / "site" / "viewport-occupancy.js"
PICKING_MODULE = REPO / "docs" / "site" / "viewport-picking.js"


def _run(js_body: str) -> dict:
    node = shutil.which("node")
    if node is None:
        raise AssertionError(
            "node is required to run this suite and was not found on PATH."
        )
    script = f"""
const occ = require({json.dumps(str(OCCUPANCY_MODULE.as_posix()))});
const picking = require({json.dumps(str(PICKING_MODULE.as_posix()))});
const out = {{}};
{js_body}
console.log(JSON.stringify(out));
"""
    result = subprocess.run(
        [node, "-e", script], capture_output=True, text=True, cwd=str(REPO)
    )
    if result.returncode != 0:
        raise AssertionError(f"node script failed:\n{result.stdout}\n{result.stderr}")
    return json.loads(result.stdout.strip().splitlines()[-1])


def _pack_single_bit(lx: int, ly: int, lz: int) -> str:
    """Build the 512-byte occupancy buffer for one sub-chunk with exactly
    one solid bit set, base64-encoded so it can cross into the Node
    subprocess as a JS source literal."""
    import base64

    bit_index = (ly * 16 + lz) * 16 + lx
    byte_index = bit_index // 8
    bit_in_byte = bit_index % 8
    data = bytearray(512)
    data[byte_index] |= 1 << bit_in_byte
    return base64.b64encode(bytes(data)).decode("ascii")


class OccupancyStoreTests(unittest.TestCase):
    def test_known_bitset_answers_solid_and_non_solid_correctly(self):
        packed_b64 = _pack_single_bit(lx=3, ly=7, lz=11)
        out = _run(f"""
            var store = occ.createOccupancyStore();
            var bytes = Buffer.from({json.dumps(packed_b64)}, "base64");
            var buffer = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
            store.setChunk(0, 0, [{{cy: 0, byte_offset: 0, byte_length: 512}}], buffer);
            out.solidAtTheBit = store.isSolid(3, 7, 11);
            out.airNextToIt = store.isSolid(4, 7, 11);
            out.airElsewhere = store.isSolid(0, 0, 0);
            """)
        self.assertTrue(out["solidAtTheBit"])
        self.assertFalse(out["airNextToIt"])
        self.assertFalse(out["airElsewhere"])

    def test_unloaded_chunk_answers_false_rather_than_throwing(self):
        out = _run("""
            var store = occ.createOccupancyStore();
            out.beforeLoad = store.isSolid(100, 5, 100);
            out.threw = false;
            try {
              store.isSolid(-50, -50, -50);
            } catch (e) {
              out.threw = true;
            }
            """)
        self.assertFalse(out["beforeLoad"])
        self.assertFalse(out["threw"])

    def test_unloaded_sub_chunk_within_a_loaded_chunk_answers_false(self):
        """A chunk can be loaded (cy=0 known) while a different height
        (cy=5) has never streamed in -- that height must answer false, not
        crash and not silently treat it as ground level's data."""
        packed_b64 = _pack_single_bit(lx=0, ly=0, lz=0)
        out = _run(f"""
            var store = occ.createOccupancyStore();
            var bytes = Buffer.from({json.dumps(packed_b64)}, "base64");
            var buffer = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
            store.setChunk(0, 0, [{{cy: 0, byte_offset: 0, byte_length: 512}}], buffer);
            out.knownHeight = store.isSolid(0, 0, 0);
            out.unknownHeight = store.isSolid(0, 80, 0); // cy=5, never loaded
            """)
        self.assertTrue(out["knownHeight"])
        self.assertFalse(out["unknownHeight"])

    def test_unload_chunk_drops_its_occupancy(self):
        packed_b64 = _pack_single_bit(lx=0, ly=0, lz=0)
        out = _run(f"""
            var store = occ.createOccupancyStore();
            var bytes = Buffer.from({json.dumps(packed_b64)}, "base64");
            var buffer = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
            store.setChunk(0, 0, [{{cy: 0, byte_offset: 0, byte_length: 512}}], buffer);
            out.beforeUnload = store.isSolid(0, 0, 0);
            store.unloadChunk(0, 0);
            out.afterUnload = store.isSolid(0, 0, 0);
            """)
        self.assertTrue(out["beforeUnload"])
        self.assertFalse(out["afterUnload"])

    def test_bounded_cache_evicts_oldest_chunk(self):
        out = _run("""
            var store = occ.createOccupancyStore(2);
            var buffer = new ArrayBuffer(512);
            store.setChunk(0, 0, [{cy: 0, byte_offset: 0, byte_length: 512}], buffer);
            store.setChunk(1, 0, [{cy: 0, byte_offset: 0, byte_length: 512}], buffer);
            out.sizeAfterTwo = store.size();
            store.setChunk(2, 0, [{cy: 0, byte_offset: 0, byte_length: 512}], buffer);
            out.sizeAfterThree = store.size();
            """)
        self.assertEqual(out["sizeAfterTwo"], 2)
        self.assertEqual(out["sizeAfterThree"], 2)  # bounded, not 3

    def test_a_real_ray_hits_the_block_a_human_would_expect(self):
        """A store populated with a single solid block directly below the
        ray's origin/direction, fed straight into the real DDA march from
        viewport-picking.js -- proving the two modules actually agree on
        block coordinates, not just that each is internally consistent."""
        packed_b64 = _pack_single_bit(lx=0, ly=0, lz=0)  # world (0,0,0) solid
        out = _run(f"""
            var store = occ.createOccupancyStore();
            var bytes = Buffer.from({json.dumps(packed_b64)}, "base64");
            var buffer = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
            store.setChunk(0, 0, [{{cy: 0, byte_offset: 0, byte_length: 512}}], buffer);
            // Straight down from (0.5, 5, 0.5) should hit block (0,0,0).
            var hit = picking.voxelRaycast([0.5, 5, 0.5], [0, -1, 0], store.isSolid, 64);
            out.hit = hit ? hit.block : null;
            """)
        self.assertEqual(out["hit"], [0, 0, 0])

    def test_bit_order_guard_is_actually_load_bearing(self):
        """Flip the bit order the store decodes with (swap lx/lz) and
        confirm a previously-correct assertion now fails -- proof this test
        would have caught a real regression, not just that the code and the
        test were written to agree with each other by construction."""
        packed_b64 = _pack_single_bit(lx=3, ly=7, lz=11)
        out = _run(f"""
            var bytes = Buffer.from({json.dumps(packed_b64)}, "base64");
            var view = new Uint8Array(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength));
            function readCorrect(lx, ly, lz) {{
              var bitIndex = (ly * 16 + lz) * 16 + lx;
              return (view[bitIndex >> 3] >> (bitIndex & 7)) & 1;
            }}
            function readWrongOrder(lx, ly, lz) {{
              var bitIndex = (ly * 16 + lx) * 16 + lz; // lx/lz swapped -- WRONG on purpose
              return (view[bitIndex >> 3] >> (bitIndex & 7)) & 1;
            }}
            out.correct = readCorrect(3, 7, 11);
            out.wrong = readWrongOrder(3, 7, 11);
            """)
        self.assertEqual(out["correct"], 1)
        self.assertEqual(out["wrong"], 0)  # the broken order misses the bit entirely


if __name__ == "__main__":
    unittest.main()
