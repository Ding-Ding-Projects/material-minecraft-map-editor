"""Pure-function tests for the WebGL2 viewport's frustum culling and
translucent back-to-front chunk ordering (docs/site/viewport-webgl.js).

No GPU is launched anywhere in this file -- frustum plane extraction, the
box-vs-frustum test, and the distance sort are ordinary arithmetic over plain
arrays, so they are exercised directly through Node exactly like
tests/test_viewport_webgl_camera_and_streaming.py already does for the
camera math. This is stronger evidence than a screenshot: the exact camera
position/orientation that FAILS to cull or mis-orders chunks is pinned down
here, rather than hoped to be visible in whatever frame a capture happened to
land on.
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
        raise AssertionError(
            "node is required to run this suite and was not found on PATH."
        )
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


class FrustumPlaneExtractionTests(unittest.TestCase):
    def test_identity_view_projection_yields_the_canonical_clip_cube_planes(self):
        # With M = identity, ax+by+cz+d>=0 for each plane reduces to the six
        # faces of the NDC cube [-1,1]^3 -- a point exactly on an axis at
        # distance 1 should sit ON the boundary (>= 0), and a point just past
        # it should fail every plane it crosses.
        out = _run("""
            var m = api._mat4Identity();
            var planes = api.frustumPlanesFromViewProjection(m);
            out.count = planes.length;
            out.insideOrigin = api.boxIntersectsFrustum(planes, [-0.1, -0.1, -0.1], [0.1, 0.1, 0.1]);
            out.insideUnitBox = api.boxIntersectsFrustum(planes, [-1, -1, -1], [1, 1, 1]);
            out.outsideFarRight = api.boxIntersectsFrustum(planes, [2, -0.1, -0.1], [3, 0.1, 0.1]);
            """)
        self.assertEqual(out["count"], 6)
        self.assertTrue(out["insideOrigin"])
        self.assertTrue(out["insideUnitBox"])
        self.assertFalse(out["outsideFarRight"])


class ChunkCullingTests(unittest.TestCase):
    def _cull(self, camera_x, camera_z, yaw_deg, chunks):
        return _run(f"""
            var view = api._mat4View([{camera_x}, 20, {camera_z}], {yaw_deg} * Math.PI / 180, 0);
            var proj = api._mat4Perspective(70 * Math.PI / 180, 16 / 9, 0.1, 1000);
            var vp = api._mat4Multiply(proj, view);
            var planes = api.frustumPlanesFromViewProjection(vp);
            out.visible = [];
            var chunks = {json.dumps(chunks)};
            for (var i = 0; i < chunks.length; i++) {{
                var c = chunks[i];
                var bounds = api.chunkWorldBounds(c[0], c[1], api.DEFAULT_WORLD_MIN_Y, api.DEFAULT_WORLD_MAX_Y);
                if (api.boxIntersectsFrustum(planes, bounds.min, bounds.max)) {{
                    out.visible.push(c);
                }}
            }}
            """)

    def test_chunk_directly_ahead_is_visible_chunk_far_behind_is_not(self):
        # Camera at chunk (0,0)'s southwest corner looking toward -Z (yaw 0,
        # matching mat4View's documented convention). Chunk (0,-2) is ahead
        # of the camera; chunk (0,3) is behind it.
        out = self._cull(8, 8, 0, [[0, -2], [0, 3]])
        self.assertIn([0, -2], out["visible"])
        self.assertNotIn([0, 3], out["visible"])

    def test_chunk_directly_behind_camera_is_culled_when_looking_forward(self):
        out = self._cull(8, 8, 0, [[0, 5]])
        self.assertEqual(out["visible"], [])

    def test_huge_chunk_straddling_a_plane_is_kept_never_falsely_culled(self):
        # An oversized AABB whose near face is behind the camera and whose
        # far face is far ahead must still test as visible: the box-corner
        # test picks the farthest-along-normal corner per plane, so
        # straddling boxes are always kept.
        out = _run("""
            var view = api._mat4View([8, 20, 8], 0, 0);
            var proj = api._mat4Perspective(70 * Math.PI / 180, 16 / 9, 0.1, 1000);
            var vp = api._mat4Multiply(proj, view);
            var planes = api.frustumPlanesFromViewProjection(vp);
            out.visible = api.boxIntersectsFrustum(planes, [-500, -500, -600], [500, 500, 400]);
            """)
        self.assertTrue(out["visible"])

    def test_chunk_just_inside_and_just_outside_the_side_plane(self):
        # Narrow-ish FOV (50 deg) so the left/right planes are easy to reason
        # about: a chunk hugging the camera's forward axis stays inside,
        # a chunk far off to the side at the same depth is culled.
        out = _run("""
            var view = api._mat4View([8, 20, 8], 0, 0);
            var proj = api._mat4Perspective(50 * Math.PI / 180, 1, 0.1, 1000);
            var vp = api._mat4Multiply(proj, view);
            var planes = api.frustumPlanesFromViewProjection(vp);
            var nearAxis = api.chunkWorldBounds(0, -2, api.DEFAULT_WORLD_MIN_Y, api.DEFAULT_WORLD_MAX_Y);
            var farOffToSide = api.chunkWorldBounds(400, -2, api.DEFAULT_WORLD_MIN_Y, api.DEFAULT_WORLD_MAX_Y);
            out.nearAxis = api.boxIntersectsFrustum(planes, nearAxis.min, nearAxis.max);
            out.farOffToSide = api.boxIntersectsFrustum(planes, farOffToSide.min, farOffToSide.max);
            """)
        self.assertTrue(out["nearAxis"])
        self.assertFalse(out["farOffToSide"])


class BackToFrontSortTests(unittest.TestCase):
    def test_sorts_farthest_chunk_first(self):
        out = _run("""
            var entries = [
                { cx: 0, cz: 0 },
                { cx: 5, cz: 0 },
                { cx: -3, cz: 0 },
            ];
            var ordered = api.sortChunksBackToFront(entries, [8, 0, 8]);
            out.order = ordered.map(function (e) { return [e.cx, e.cz]; });
            """)
        # Camera near chunk (0,0). Farthest of the three by centre distance
        # should be chunk (5,0), nearest chunk (0,0).
        self.assertEqual(out["order"][0], [5, 0])
        self.assertEqual(out["order"][-1], [0, 0])

    def test_does_not_mutate_the_input_array(self):
        out = _run("""
            var entries = [{ cx: 5, cz: 0 }, { cx: 0, cz: 0 }];
            var before = entries.map(function (e) { return [e.cx, e.cz]; });
            api.sortChunksBackToFront(entries, [8, 0, 8]);
            var after = entries.map(function (e) { return [e.cx, e.cz]; });
            out.same = JSON.stringify(before) === JSON.stringify(after);
            """)
        self.assertTrue(out["same"])

    def test_equidistant_chunks_keep_stable_relative_order(self):
        out = _run("""
            var entries = [
                { cx: 1, cz: 0, tag: "a" },
                { cx: -1, cz: 0, tag: "b" },
                { cx: 0, cz: 1, tag: "c" },
                { cx: 0, cz: -1, tag: "d" },
            ];
            // Camera at chunk-grid origin: all four chunk centres are
            // equidistant, so a stable sort must preserve input order.
            var ordered = api.sortChunksBackToFront(entries, [8, 0, 8]);
            out.tags = ordered.map(function (e) { return e.tag; });
            """)
        self.assertEqual(out["tags"], ["a", "b", "c", "d"])

    def test_empty_and_single_entry_lists(self):
        out = _run("""
            out.empty = api.sortChunksBackToFront([], [0, 0, 0]);
            out.single = api.sortChunksBackToFront([{ cx: 2, cz: 2 }], [0, 0, 0]).map(
                function (e) { return [e.cx, e.cz]; }
            );
            """)
        self.assertEqual(out["empty"], [])
        self.assertEqual(out["single"], [[2, 2]])


class ChunkWorldBoundsTests(unittest.TestCase):
    def test_bounds_cover_the_full_16x16_footprint_and_given_height_span(self):
        out = _run("""
            out.bounds = api.chunkWorldBounds(2, -3, -64, 320);
            """)
        self.assertEqual(out["bounds"]["min"], [32, -64, -48])
        self.assertEqual(out["bounds"]["max"], [48, 320, -32])


if __name__ == "__main__":
    unittest.main()
