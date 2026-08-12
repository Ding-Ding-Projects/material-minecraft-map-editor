"""Ray-cast maths for click-to-pick, exercised with no GPU at all.

``docs/site/viewport-picking.js`` is pure functions -- a cursor position plus
a camera becomes a ray, a ray plus a voxel grid becomes the first solid
block hit and the face it entered through. Both halves are checked here
directly in Node with known camera matrices and known geometry, following
the same pattern as ``test_viewport_webgl_camera_and_streaming.py``: this is
stronger evidence than a screenshot, and it is evidence a screenshot could
never give (a DDA march visiting exactly the right voxels is not something a
human eye can verify from a picture).

Real frame rates, draw calls, and anything else that needs an actual GPU are
out of scope here and are not claimed anywhere in this suite.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MODULE = REPO / "docs" / "site" / "viewport-picking.js"


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


class RayFromCameraTests(unittest.TestCase):
    def test_centre_of_screen_looks_straight_down_forward_at_yaw_pitch_zero(self):
        out = _run(
            """
            var ray = api.rayFromCamera(
              {position: [0, 0, 0], yaw: 0, pitch: 0}, Math.PI / 2, 1, 0, 0
            );
            out.direction = ray.direction;
            out.origin = ray.origin;
            """
        )
        # yaw 0, pitch 0 looks toward -Z (matches viewport-webgl.js's mat4View).
        self.assertAlmostEqual(out["direction"][0], 0, places=6)
        self.assertAlmostEqual(out["direction"][1], 0, places=6)
        self.assertAlmostEqual(out["direction"][2], -1, places=6)
        self.assertEqual(out["origin"], [0, 0, 0])

    def test_positive_ndc_y_looks_up_negative_ndc_y_looks_down(self):
        out = _run(
            """
            var up = api.rayFromCamera(
              {position: [0, 0, 0], yaw: 0, pitch: 0}, Math.PI / 2, 1, 0, 0.5
            );
            var down = api.rayFromCamera(
              {position: [0, 0, 0], yaw: 0, pitch: 0}, Math.PI / 2, 1, 0, -0.5
            );
            out.upY = up.direction[1];
            out.downY = down.direction[1];
            """
        )
        self.assertGreater(out["upY"], 0)
        self.assertLess(out["downY"], 0)

    def test_direction_is_normalized(self):
        out = _run(
            """
            var ray = api.rayFromCamera(
              {position: [3, 4, 5], yaw: 0.7, pitch: -0.3}, 1.1, 1.7, 0.4, -0.2
            );
            var d = ray.direction;
            out.length = Math.sqrt(d[0]*d[0] + d[1]*d[1] + d[2]*d[2]);
            """
        )
        self.assertAlmostEqual(out["length"], 1.0, places=6)

    def test_positive_pitch_looks_down_matching_camera_py_convention(self):
        # amulet_map_editor.api.opengl.camera.Camera: positive pitch is down.
        out = _run(
            """
            var ray = api.rayFromCamera(
              {position: [0, 0, 0], yaw: 0, pitch: 0.6}, Math.PI / 2, 1, 0, 0
            );
            out.y = ray.direction[1];
            """
        )
        self.assertLess(out["y"], 0)


class VoxelRaycastTests(unittest.TestCase):
    def test_axis_aligned_hit_returns_correct_block_and_face(self):
        out = _run(
            """
            function isSolid(x, y, z) { return x === 5 && y === 0 && z === 0; }
            var hit = api.voxelRaycast([0, 0.5, 0.5], [1, 0, 0], isSolid, 32);
            out.hit = hit;
            """
        )
        self.assertIsNotNone(out["hit"])
        self.assertEqual(out["hit"]["block"], [5, 0, 0])
        self.assertEqual(out["hit"]["face"], [-1, 0, 0])
        self.assertAlmostEqual(out["hit"]["distance"], 5.0, places=5)

    def test_diagonal_hit_finds_the_first_block_along_the_march(self):
        out = _run(
            """
            var solids = {"3,3,0": true};
            function isSolid(x, y, z) {
              return Boolean(solids[x + "," + y + "," + z]);
            }
            var hit = api.voxelRaycast([0.5, 0.5, 0.5], [1, 1, 0], isSolid, 32);
            out.hit = hit;
            """
        )
        self.assertIsNotNone(out["hit"])
        self.assertEqual(out["hit"]["block"], [3, 3, 0])

    def test_ray_that_misses_everything_returns_null(self):
        out = _run(
            """
            function isSolid() { return false; }
            var hit = api.voxelRaycast([0, 0, 0], [1, 0, 0], isSolid, 16);
            out.hit = hit;
            """
        )
        self.assertIsNone(out["hit"])

    def test_ray_starting_inside_a_block_hits_immediately_with_no_face(self):
        out = _run(
            """
            function isSolid(x, y, z) { return x === 0 && y === 0 && z === 0; }
            var hit = api.voxelRaycast([0.5, 0.5, 0.5], [1, 0, 0], isSolid, 16);
            out.hit = hit;
            """
        )
        self.assertIsNotNone(out["hit"])
        self.assertEqual(out["hit"]["block"], [0, 0, 0])
        self.assertEqual(out["hit"]["face"], [0, 0, 0])
        self.assertEqual(out["hit"]["distance"], 0)

    def test_grazing_incidence_still_resolves_a_single_axis_step_at_a_time(self):
        out = _run(
            """
            var solids = {"10,0,1": true};
            function isSolid(x, y, z) {
              return Boolean(solids[x + "," + y + "," + z]);
            }
            // Almost purely along +X, a whisper of +Z.
            var hit = api.voxelRaycast([0.5, 0.5, 0.5], [1, 0, 0.1], isSolid, 32);
            out.hit = hit;
            """
        )
        self.assertIsNotNone(out["hit"])
        self.assertEqual(out["hit"]["block"], [10, 0, 1])

    def test_zero_direction_returns_null_rather_than_looping_forever(self):
        out = _run(
            """
            function isSolid() { return false; }
            var hit = api.voxelRaycast([0, 0, 0], [0, 0, 0], isSolid, 16);
            out.hit = hit;
            """
        )
        self.assertIsNone(out["hit"])

    def test_hit_beyond_max_distance_is_not_reported(self):
        out = _run(
            """
            function isSolid(x, y, z) { return x === 50 && y === 0 && z === 0; }
            var hit = api.voxelRaycast([0, 0.5, 0.5], [1, 0, 0], isSolid, 10);
            out.hit = hit;
            """
        )
        self.assertIsNone(out["hit"])

    def test_negative_axis_march_reports_the_entered_face(self):
        out = _run(
            """
            function isSolid(x, y, z) { return x === -4 && y === 0 && z === 0; }
            var hit = api.voxelRaycast([0, 0.5, 0.5], [-1, 0, 0], isSolid, 32);
            out.hit = hit;
            """
        )
        self.assertIsNotNone(out["hit"])
        self.assertEqual(out["hit"]["block"], [-4, 0, 0])
        self.assertEqual(out["hit"]["face"], [1, 0, 0])


if __name__ == "__main__":
    unittest.main()
