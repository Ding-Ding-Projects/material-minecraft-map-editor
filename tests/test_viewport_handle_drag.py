"""Selection-box handle geometry and drag arithmetic, checked with no GPU.

``docs/site/viewport-handles.js`` is a mechanical port of
``amulet_map_editor/api/opengl/mesh/selection/box/handles.py`` -- the wx
editor's own selection-box grab-and-resize maths -- kept function-for-
function so the Electron editor cannot disagree with the wx one about how a
box resizes. Every case here mirrors a case the Python module's own
docstrings call out: axis-aligned face drags, corner drags in a
camera-facing plane, a face handle withheld when it is stared straight down,
and the nearest-handle tie-break when two handles overlap on screen.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MODULE = REPO / "docs" / "site" / "viewport-handles.js"


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


class HandleInventoryTests(unittest.TestCase):
    def test_fourteen_handles_six_face_eight_corner(self):
        out = _run("""
            out.total = api.BOX_HANDLES.length;
            out.faces = api.FACE_HANDLES.length;
            out.corners = api.CORNER_HANDLES.length;
            """)
        self.assertEqual(out["total"], 14)
        self.assertEqual(out["faces"], 6)
        self.assertEqual(out["corners"], 8)

    def test_handle_centre_face_sits_at_face_midpoint(self):
        out = _run("""
            var handle = api.FACE_HANDLES.filter(h => h.name === "face:+x")[0];
            out.centre = api.handleCentre(handle, [0, 0, 0], [4, 2, 2]);
            """)
        self.assertEqual(out["centre"], [4, 1, 1])

    def test_handle_centre_corner_sits_at_the_corner(self):
        out = _run("""
            var handle = api.CORNER_HANDLES.filter(h => h.name === "corner:+x-y+z")[0];
            out.centre = api.handleCentre(handle, [0, 0, 0], [4, 2, 2]);
            """)
        self.assertEqual(out["centre"], [4, 0, 2])

    def test_handle_half_size_clamps_between_min_and_max(self):
        out = _run("""
            out.tiny = api.handleHalfSize([0, 0, 0], [1, 1, 1]);
            out.huge = api.handleHalfSize([0, 0, 0], [300, 300, 300]);
            """)
        self.assertAlmostEqual(out["tiny"], max(1 / 6, 0.15), places=6)
        self.assertAlmostEqual(out["huge"], 0.75, places=6)


class RayBoxDistanceTests(unittest.TestCase):
    def test_hits_report_distance_zero_from_inside(self):
        out = _run("""
            out.distance = api.rayBoxDistance([0.5, 0.5, 0.5], [1, 0, 0], [0, 0, 0], [1, 1, 1]);
            """)
        self.assertEqual(out["distance"], 0)

    def test_miss_returns_null(self):
        out = _run("""
            out.distance = api.rayBoxDistance([0, 10, 0], [1, 0, 0], [0, 0, 0], [1, 1, 1]);
            """)
        self.assertIsNone(out["distance"])

    def test_hit_handle_picks_the_nearest_of_two_overlapping_bounds(self):
        out = _run("""
            var near = { name: "near", offset: [1, 0, 0], axis: 0 };
            var far = { name: "far", offset: [-1, 0, 0], axis: 0 };
            // Two 1-wide boxes on the ray from x=0 looking +X.
            var handles = [near, far];
            // Fake handleBounds by using a big box so both handles' cubes are hit;
            // instead exercise hitHandle end-to-end with the real box handles.
            var picked = api.hitHandle([0, 0, 0], [10, 10, 10], [-5, 5, 5], [1, 0, 0]);
            out.picked = picked ? picked.name : null;
            """)
        self.assertEqual(out["picked"], "face:-x")


class FaceAlignmentTests(unittest.TestCase):
    def test_face_handle_withheld_when_stared_straight_down_its_axis(self):
        out = _run("""
            var handle = api.FACE_HANDLES.filter(h => h.name === "face:+x")[0];
            out.usable_straight_on = api.faceHandleIsUsable(handle, [1, 0, 0]);
            out.usable_side_on = api.faceHandleIsUsable(handle, [0, 0, 1]);
            """)
        self.assertFalse(out["usable_straight_on"])
        self.assertTrue(out["usable_side_on"])

    def test_corner_handles_are_always_usable(self):
        out = _run("""
            var handle = api.CORNER_HANDLES[0];
            out.usable = api.faceHandleIsUsable(handle, [1, 0, 0]);
            """)
        self.assertTrue(out["usable"])


class DragTests(unittest.TestCase):
    def test_face_drag_moves_only_its_own_axis(self):
        out = _run("""
            var handle = api.FACE_HANDLES.filter(h => h.name === "face:+x")[0];
            var min = [0, 0, 0], max = [4, 4, 4];
            // Camera looking down -Z at the +X face, cursor ray along -Z hitting
            // the face plane offset along X by dragging the ray origin.
            var drag = api.beginDrag(handle, min, max, [4, 2, 10], [0, 0, -1]);
            out.began = drag !== null;
            // Move the ray origin's X by +3 blocks -- closest point on the face's
            // X axis line should shift by roughly 3.
            var offset = api.dragBlockOffset(drag, [7, 2, 10], [0, 0, -1]);
            out.offset = offset;
            var box = api.applyDragOffset(drag, offset);
            out.box = box;
            """)
        self.assertTrue(out["began"])
        self.assertEqual(out["offset"], [3, 0, 0])
        self.assertEqual(out["box"][0], [0, 0, 0])
        self.assertEqual(out["box"][1], [7, 4, 4])

    def test_face_drag_returns_null_when_looking_straight_down_axis(self):
        out = _run("""
            var handle = api.FACE_HANDLES.filter(h => h.name === "face:+x")[0];
            var drag = api.beginDrag(handle, [0, 0, 0], [4, 4, 4], [10, 2, 2], [-1, 0, 0]);
            out.began = drag !== null;
            """)
        # The cursor ray runs parallel to the face handle's own axis line --
        # closestParameterOnLine has no single answer for that, matching
        # handles.py's begin_drag, which also refuses to start here.
        self.assertFalse(out["began"])

    def test_corner_drag_moves_in_the_camera_facing_plane(self):
        out = _run("""
            var handle = api.CORNER_HANDLES.filter(h => h.name === "corner:+x+y+z")[0];
            var min = [0, 0, 0], max = [4, 4, 4];
            // Camera looking along -Z, so the dominant axis of the view is Z ->
            // the drag plane's normal is Z, movement happens in the X/Y plane.
            var origin = [4, 4, 10];
            var direction = [0, 0, -1];
            var drag = api.beginDrag(handle, min, max, origin, direction);
            out.began = drag !== null;
            var offset = api.dragBlockOffset(drag, [6, 5, 10], direction);
            out.offset = offset;
            """)
        self.assertTrue(out["began"])
        self.assertEqual(out["offset"][2], 0)
        self.assertEqual(out["offset"][0], 2)
        self.assertEqual(out["offset"][1], 1)

    def test_dominant_axis_picks_the_largest_component(self):
        out = _run("""
            out.a = api.dominantAxis([0.1, 0.9, 0.2]);
            out.b = api.dominantAxis([5, 1, 1]);
            """)
        self.assertEqual(out["a"], 1)
        self.assertEqual(out["b"], 0)


if __name__ == "__main__":
    unittest.main()
