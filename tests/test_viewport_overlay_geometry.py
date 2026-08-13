"""The viewport's selection-box/grid overlay geometry, checked as arithmetic.

Without a selection box the viewport can display a world but cannot be used
to edit one, so the vertex data this module produces matters. The geometry
generation in docs/site/viewport-overlays.js is deliberately pure -- no GL
call anywhere in it -- so it is checked here the same way the box-render
math in amulet_map_editor's Python module would be: known bounds in, known
vertices out, no GPU required.

Node runs the checks because the code under test is JavaScript. A missing
Node is a hard failure rather than a skip, for the same reason as the site's
TOTP/QR contract test: skipping here would leave the suite green while the
overlay geometry went unverified.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OVERLAYS_JS = REPO / "docs" / "site" / "viewport-overlays.js"


def run_node(body: str) -> dict:
    node = shutil.which("node")
    if node is None:
        raise AssertionError(
            "node is required to check the viewport overlay geometry and was not "
            "found on PATH. This is not skipped, because skipping would leave the "
            "suite green while the overlay math went unverified."
        )
    script = (
        "const fs = require('fs');\n"
        "global.window = {};\n"
        f"eval(fs.readFileSync(String.raw`{OVERLAYS_JS.as_posix()}`, 'utf8'));\n"
        "const overlays = global.window.AmuletViewportOverlays;\n"
        "const out = (function(){\n"
        + body
        + "\n})();\nprocess.stdout.write(JSON.stringify(out));\n"
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "check.cjs"
        path.write_text(script, encoding="utf-8")
        result = subprocess.run(
            [node, str(path)], capture_output=True, text=True, timeout=60
        )
    if result.returncode != 0:
        raise AssertionError(
            f"the node harness failed:\n{result.stdout}\n{result.stderr}"
        )
    return json.loads(result.stdout)


class ModuleLoadsAndExportsWhatIntegrationNeeds(unittest.TestCase):
    def test_file_exists(self) -> None:
        self.assertTrue(OVERLAYS_JS.is_file(), OVERLAYS_JS)

    def test_expected_exports_present(self) -> None:
        out = run_node(
            "return {"
            "hasOverlay: typeof overlays.SelectionOverlay === 'function',"
            "hasEdges: typeof overlays._buildBoxEdgeVertices === 'function',"
            "hasFaces: typeof overlays._buildBoxFaceVertices === 'function',"
            "hasGrid: typeof overlays._buildGridVertices === 'function',"
            "hasMarker: typeof overlays._buildMarkerCube === 'function',"
            "};"
        )
        self.assertEqual(
            out,
            {
                "hasOverlay": True,
                "hasEdges": True,
                "hasFaces": True,
                "hasGrid": True,
                "hasMarker": True,
            },
        )


class BoxEdgeVertices(unittest.TestCase):
    """A wireframe cube has exactly 12 edges, 2 vertices each."""

    def test_edge_count_and_shape(self) -> None:
        out = run_node(
            "const v = overlays._buildBoxEdgeVertices([0,0,0],[2,3,4]);"
            "return {length: v.length};"
        )
        self.assertEqual(out["length"], 12 * 2 * 3)

    def test_edges_span_exactly_min_to_max_on_each_axis(self) -> None:
        out = run_node(
            "const v = Array.from(overlays._buildBoxEdgeVertices([1,2,3],[5,6,7]));"
            "const xs = [], ys = [], zs = [];"
            "for (let i = 0; i < v.length; i += 3) { xs.push(v[i]); ys.push(v[i+1]); zs.push(v[i+2]); }"
            "return {"
            "minX: Math.min(...xs), maxX: Math.max(...xs),"
            "minY: Math.min(...ys), maxY: Math.max(...ys),"
            "minZ: Math.min(...zs), maxZ: Math.max(...zs),"
            "};"
        )
        self.assertEqual(
            out, {"minX": 1, "maxX": 5, "minY": 2, "maxY": 6, "minZ": 3, "maxZ": 7}
        )

    def test_every_vertex_is_a_real_box_corner(self) -> None:
        out = run_node(
            "const v = Array.from(overlays._buildBoxEdgeVertices([0,0,0],[1,1,1]));"
            "let ok = true;"
            "for (let i = 0; i < v.length; i += 3) {"
            "  const x = v[i], y = v[i+1], z = v[i+2];"
            "  if (![0,1].includes(x) || ![0,1].includes(y) || ![0,1].includes(z)) ok = false;"
            "}"
            "return {ok};"
        )
        self.assertTrue(out["ok"])


class BoxFaceVertices(unittest.TestCase):
    """A cuboid has 6 faces, 2 triangles each, 3 vertices per triangle."""

    def test_face_count_and_shape(self) -> None:
        out = run_node(
            "const v = overlays._buildBoxFaceVertices([0,0,0],[2,3,4]);"
            "return {length: v.length};"
        )
        self.assertEqual(out["length"], 6 * 2 * 3 * 3)

    def test_faces_stay_within_bounds(self) -> None:
        out = run_node(
            "const v = Array.from(overlays._buildBoxFaceVertices([1,2,3],[5,6,7]));"
            "let ok = true;"
            "for (let i = 0; i < v.length; i += 3) {"
            "  const x = v[i], y = v[i+1], z = v[i+2];"
            "  if (x < 1 || x > 5 || y < 2 || y > 6 || z < 3 || z > 7) ok = false;"
            "}"
            "return {ok};"
        )
        self.assertTrue(out["ok"])

    def test_zero_size_box_is_still_well_formed(self) -> None:
        # A degenerate box (point1 == point2) must not throw or produce NaN --
        # it should just render as a flat, invisible sliver rather than crash
        # the caller mid-frame.
        out = run_node(
            "const v = Array.from(overlays._buildBoxFaceVertices([5,5,5],[5,5,5]));"
            "return {allEqualFive: v.every((n) => n === 5), length: v.length};"
        )
        self.assertTrue(out["allEqualFive"])
        self.assertEqual(out["length"], 6 * 2 * 3 * 3)


class GridVertices(unittest.TestCase):
    def test_grid_lines_lie_on_the_requested_plane(self) -> None:
        out = run_node(
            "const v = Array.from(overlays._buildGridVertices(0, 0, 12, 8, 2));"
            "let ok = true;"
            "for (let i = 1; i < v.length; i += 3) { if (v[i] !== 12) ok = false; }"
            "return {ok, count: v.length / 3};"
        )
        self.assertTrue(out["ok"])
        self.assertGreater(out["count"], 0)

    def test_grid_is_a_multiple_of_a_full_line_pair(self) -> None:
        out = run_node(
            "const v = overlays._buildGridVertices(3, -5, 0, 16, 1);"
            "return {length: v.length};"
        )
        # Each grid line is 2 vertices * 3 floats = 6 floats.
        self.assertEqual(out["length"] % 6, 0)


class MarkerCube(unittest.TestCase):
    def test_marker_is_centred_on_the_given_point(self) -> None:
        out = run_node(
            "const m = overlays._buildMarkerCube([10, 20, 30], 0.5);"
            "const edges = Array.from(m.edges);"
            "const xs = [], ys = [], zs = [];"
            "for (let i = 0; i < edges.length; i += 3) { xs.push(edges[i]); ys.push(edges[i+1]); zs.push(edges[i+2]); }"
            "return {"
            "cx: (Math.min(...xs) + Math.max(...xs)) / 2,"
            "cy: (Math.min(...ys) + Math.max(...ys)) / 2,"
            "cz: (Math.min(...zs) + Math.max(...zs)) / 2,"
            "halfX: (Math.max(...xs) - Math.min(...xs)) / 2,"
            "};"
        )
        self.assertAlmostEqual(out["cx"], 10)
        self.assertAlmostEqual(out["cy"], 20)
        self.assertAlmostEqual(out["cz"], 30)
        self.assertAlmostEqual(out["halfX"], 0.5)


class SortedBoundsAndPointInBox(unittest.TestCase):
    def test_bounds_sort_regardless_of_which_point_is_which(self) -> None:
        out = run_node("return overlays._sortedBounds([5,1,9],[2,7,3]);")
        self.assertEqual(out, {"min": [2, 1, 3], "max": [5, 7, 9]})

    def test_point_in_box(self) -> None:
        out = run_node(
            "return {"
            "inside: overlays._pointInBox([1,1,1],[0,0,0],[2,2,2]),"
            "outside: overlays._pointInBox([5,1,1],[0,0,0],[2,2,2]),"
            "nullPoint: overlays._pointInBox(null,[0,0,0],[2,2,2]),"
            "};"
        )
        self.assertEqual(out, {"inside": True, "outside": False, "nullPoint": False})


class SelectionOverlayApiShape(unittest.TestCase):
    """Construction needs a real GL context, so this only checks the shape
    of the public API that the module's docstring promises to callers --
    the actual GL draw path is proven headlessly in
    scripts/capture_viewport_overlays_render.js against a real canvas."""

    def test_prototype_has_the_documented_methods(self) -> None:
        out = run_node(
            "const proto = overlays.SelectionOverlay.prototype;"
            "return {"
            "setSelection: typeof proto.setSelection === 'function',"
            "clearSelection: typeof proto.clearSelection === 'function',"
            "hasSelection: typeof proto.hasSelection === 'function',"
            "setGrid: typeof proto.setGrid === 'function',"
            "clearGrid: typeof proto.clearGrid === 'function',"
            "render: typeof proto.render === 'function',"
            "};"
        )
        self.assertEqual(
            out,
            {
                "setSelection": True,
                "clearSelection": True,
                "hasSelection": True,
                "setGrid": True,
                "clearGrid": True,
                "render": True,
            },
        )


if __name__ == "__main__":
    unittest.main()
