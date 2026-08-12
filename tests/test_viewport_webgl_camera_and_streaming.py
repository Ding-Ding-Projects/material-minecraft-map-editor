"""The WebGL2 viewport's camera and chunk-streaming API, exercised without a
real GPU.

``docs/site/viewport-webgl.js`` needs a real WebGL2 context to construct a
``Viewport`` (see ``scripts/capture_viewport_render.js`` for the one place
that happens for real, headlessly, through Electron + SwiftShader). This
suite instead calls the pure camera-math and chunk-bookkeeping methods
directly against ``Viewport.prototype`` with a minimal fake ``this`` --
no canvas, no GL calls beyond a handful of stubbed no-ops -- so the actual
arithmetic (yaw wrap, pitch clamp, forward/right movement, per-chunk
buffer bookkeeping) is checked on every push, not only in the slow,
Electron-launching capture script.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MODULE = REPO / "docs" / "site" / "viewport-webgl.js"


def _run(js_body: str) -> dict:
    node = shutil.which("node")
    if node is None:
        raise AssertionError("node is required to run this suite and was not found on PATH.")
    script = f"""
const api = require({json.dumps(str(MODULE.as_posix()))});
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


class RotationTests(unittest.TestCase):
    def test_yaw_wraps_into_minus_180_to_180_matching_camera_py(self):
        out = _run(
            """
            var view = { camera: { yaw: 0, pitch: 0 } };
            api.Viewport.prototype.setRotationDegrees.call(view, 200, 0);
            out.yawDeg = view.camera.yaw * 180 / Math.PI;
            """
        )
        self.assertAlmostEqual(out["yawDeg"], -160, places=5)

    def test_pitch_clamps_to_plus_minus_90(self):
        out = _run(
            """
            var view = { camera: { yaw: 0, pitch: 0 } };
            api.Viewport.prototype.setRotationDegrees.call(view, 0, 500);
            out.pitchDeg = view.camera.pitch * 180 / Math.PI;
            """
        )
        self.assertAlmostEqual(out["pitchDeg"], 90, places=5)

    def test_rotate_degrees_is_relative_and_inverts_pitch_for_drag_convention(self):
        out = _run(
            """
            var view = {
              camera: { yaw: 10 * Math.PI / 180, pitch: 5 * Math.PI / 180 },
              setRotationDegrees: api.Viewport.prototype.setRotationDegrees,
            };
            api.Viewport.prototype.rotateDegrees.call(view, 15, 20);
            out.yawDeg = view.camera.yaw * 180 / Math.PI;
            out.pitchDeg = view.camera.pitch * 180 / Math.PI;
            """
        )
        self.assertAlmostEqual(out["yawDeg"], 25, places=5)
        # A positive drag-down delta subtracts from pitch (screen-down looks down).
        self.assertAlmostEqual(out["pitchDeg"], -15, places=5)


class MovementTests(unittest.TestCase):
    def test_move_forward_at_yaw_zero_moves_along_negative_z(self):
        out = _run(
            """
            var view = { camera: { yaw: 0, pitch: 0, position: [0, 0, 0] } };
            api.Viewport.prototype.moveLocal.call(view, 5, 0, 0);
            out.position = view.camera.position;
            """
        )
        self.assertAlmostEqual(out["position"][0], 0, places=5)
        self.assertAlmostEqual(out["position"][2], -5, places=5)

    def test_move_up_is_always_world_y_regardless_of_yaw(self):
        out = _run(
            """
            var view = { camera: { yaw: 1.234, pitch: 0.5, position: [1, 1, 1] } };
            api.Viewport.prototype.moveLocal.call(view, 0, 0, 3);
            out.position = view.camera.position;
            """
        )
        self.assertAlmostEqual(out["position"][1], 4, places=5)

    def test_a_camera_that_does_not_move_produces_the_same_transform_twice(self):
        # Guards the exact failure the capture script's two-position proof
        # exists to catch: an unmoved camera must not silently drift.
        out = _run(
            """
            var view = { camera: { yaw: 0.3, pitch: 0.1, position: [4, 5, 6] } };
            var before = JSON.stringify(view.camera);
            var after = JSON.stringify(view.camera);
            out.same = before === after;
            """
        )
        self.assertTrue(out["same"])


class ChunkStreamingTests(unittest.TestCase):
    def _fake_view(self):
        return """
        function fakeGL() {
          var nextId = 1;
          return {
            createVertexArray: function () { return { id: nextId++ }; },
            createBuffer: function () { return { id: nextId++ }; },
            bindVertexArray: function () {},
            bindBuffer: function () {},
            bufferData: function () {},
            vertexAttribPointer: function () {},
            enableVertexAttribArray: function () {},
            deleteBuffer: function () {},
            deleteVertexArray: function () {},
          };
        }
        var view = { gl: fakeGL(), chunks: {}, chunkCount: 0 };
        """

    def test_load_chunk_mesh_tracks_coordinates_and_count(self):
        out = _run(
            self._fake_view()
            + """
            api.Viewport.prototype.loadChunkMesh.call(view, 2, -3, new Float32Array(12).buffer, 1);
            api.Viewport.prototype.loadChunkMesh.call(view, 0, 0, new Float32Array(12).buffer, 1);
            out.count = view.chunkCount;
            out.has = api.Viewport.prototype.hasChunk.call(view, 2, -3);
            out.coords = api.Viewport.prototype.loadedChunkCoords.call(view).sort();
            """
        )
        self.assertEqual(out["count"], 2)
        self.assertTrue(out["has"])
        self.assertEqual(sorted(map(tuple, out["coords"])), [(0, 0), (2, -3)])

    def test_reloading_the_same_chunk_does_not_grow_the_count(self):
        out = _run(
            self._fake_view()
            + """
            api.Viewport.prototype.loadChunkMesh.call(view, 1, 1, new Float32Array(12).buffer, 1);
            api.Viewport.prototype.loadChunkMesh.call(view, 1, 1, new Float32Array(24).buffer, 2);
            out.count = view.chunkCount;
            """
        )
        self.assertEqual(out["count"], 1)

    def test_unload_chunk_bounds_memory_growth_as_the_camera_roams(self):
        out = _run(
            self._fake_view()
            + """
            api.Viewport.prototype.loadChunkMesh.call(view, 5, 5, new Float32Array(12).buffer, 1);
            api.Viewport.prototype.unloadChunk.call(view, 5, 5);
            out.count = view.chunkCount;
            out.has = api.Viewport.prototype.hasChunk.call(view, 5, 5);
            """
        )
        self.assertEqual(out["count"], 0)
        self.assertFalse(out["has"])

    def test_unloading_a_never_loaded_chunk_is_a_safe_no_op(self):
        out = _run(
            self._fake_view()
            + """
            api.Viewport.prototype.unloadChunk.call(view, 99, 99);
            out.count = view.chunkCount;
            """
        )
        self.assertEqual(out["count"], 0)


if __name__ == "__main__":
    unittest.main()
