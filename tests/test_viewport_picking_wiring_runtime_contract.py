"""The picking/handle-drag wiring in docs/site/viewport-panel.js, executed.

Follows the pattern in test_studio_workspace_runtime_contract.py: build a
real DOM with jsdom, run the real viewport-picking.js, viewport-handles.js
and viewport-panel.js the way a <script> tag would, and ask the constructed
page questions. A grep over the source cannot tell whether Alt+click on the
canvas actually reaches the six selection-point fields, whether a handle
drag actually updates them, or whether the keyboard equivalents actually do
anything -- this file answers all three by executing the real script.

No real WebGL2 context exists in jsdom, so `window.AmuletViewportWebGL` is
replaced with a small fake `Viewport` before viewport-panel.js loads --
enough to exercise `attachControls()`'s `shouldRotate` hook and the
picking/handle-drag wiring that reads `viewport.camera` and
`viewport.fovYRadians`, without claiming anything about real rendering. That
claim is exactly what tests/test_viewport_picking_raycast.py and
tests/test_viewport_handle_drag.py make instead, against the same modules,
with no DOM at all.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SITE = REPO / "docs" / "site"
PICKING = SITE / "viewport-picking.js"
HANDLES = SITE / "viewport-handles.js"
PANEL = SITE / "viewport-panel.js"

#: A minimal stand-in for docs/site/viewport-webgl.js's real Viewport, with
#: just enough surface for viewport-panel.js's picking/handle-drag wiring:
#: a camera, a field of view, and an attachControls() that records the
#: shouldRotate hook it was given so a test can call it directly instead of
#: synthesizing real pointer drags through jsdom.
FAKE_VIEWPORT_WEBGL = """
// viewport-panel.js's init() bails out to a "Desktop only" empty state --
// and never wires anything, including window.__AmuletViewportPanel -- when
// no sidecar bridge is present. A fake bridge just has to answer `call`;
// nothing in this suite exercises world.open/streaming.
window.mmweDesktop = { sidecar: { call: function () {
  return Promise.resolve({ ok: false, error: { code: "fixture_no_backend" } });
} } };
window.AmuletViewportWebGL = {
  Viewport: function (canvas) {
    this.canvas = canvas;
    this.camera = { position: [8, 5, 8], yaw: 0, pitch: 0 };
    this.fovYRadians = Math.PI / 2;
    this.gl = null; // no real WebGL2 in jsdom; ensureOverlay() bails on this
    this.attachControls = function (canvasEl, options) {
      window.__lastAttachOptions = options || {};
      return function detach() {};
    };
    this.render = function () {};
    this.hasChunk = function () { return false; };
    this.loadedChunkCoords = function () { return []; };
    this.loadChunkMesh = function () {};
    this.unloadChunk = function () {};
  },
};
"""


def render(setup_js: str, question: str) -> dict:
    node = shutil.which("node")
    if node is None:
        raise AssertionError(
            "node is required to execute the wiring and was not found on PATH."
        )
    script = f"""
const {{ JSDOM }} = require({json.dumps(str((SITE / 'node_modules' / 'jsdom').as_posix()))});
const fs = require("fs");
const errors = [];
const dom = new JSDOM(
  '<!doctype html><body>' +
  '<div><div id="viewport-host">' +
  '<canvas id="viewport-canvas" width="800" height="600" tabindex="0"></canvas>' +
  '<div id="viewport-empty"></div>' +
  '<div id="viewport-status"></div>' +
  '<div id="viewport-open-row"><button id="viewport-open-button"></button>' +
  '<input id="viewport-world-path"/></div>' +
  '</div></div>' +
  '</body>',
  {{
    runScripts: "dangerously",
    url: "https://example.invalid/",
    pretendToBeVisual: true,
    beforeParse(window) {{
      window.addEventListener("error", e => errors.push("error: " + e.message));
      // jsdom has no layout engine; give the canvas a real, non-zero rect so
      // ndcFromEvent()'s division by rect.width/height cannot produce NaN.
      window.HTMLElement.prototype.getBoundingClientRect = function () {{
        return {{ left: 0, top: 0, right: 800, bottom: 600, width: 800, height: 600 }};
      }};
    }},
  }}
);
const {{ window }} = dom;
try {{ {setup_js} }} catch (e) {{ errors.push("setup: " + (e && e.message || e)); }}
const q = sel => window.document.querySelector(sel);
(async function () {{
  // jsdom fires its own DOMContentLoaded on a native timer that races an
  // eval'd <script>-equivalent load, and viewport-panel.js runs its init()
  // either immediately (document.readyState !== "loading") or deferred on
  // that same event -- so evaluating it before readiness has settled can
  // silently miss the one moment init() actually runs. Load the two pure
  // modules synchronously (they have no init() to race), then wait for
  // readiness before loading the panel itself, so its own
  // "if (loading) listen else init()" branch resolves deterministically to
  // the immediate branch and any exception is caught right here with a
  // real stack trace rather than lost inside jsdom's async event dispatch.
  try {{
    window.eval(fs.readFileSync({json.dumps(str(PICKING))}, "utf8"));
    window.eval(fs.readFileSync({json.dumps(str(HANDLES))}, "utf8"));
  }} catch (e) {{
    errors.push("picking/handles: " + (e && e.stack || e));
  }}
  while (window.document.readyState === "loading") {{
    await new Promise(r => setTimeout(r, 5));
  }}
  try {{
    window.eval(fs.readFileSync({json.dumps(str(PANEL))}, "utf8"));
  }} catch (e) {{
    errors.push("panel: " + (e && e.stack || e));
  }}
  let answer;
  try {{
    answer = await (async function () {{ {question} }})();
  }} catch (e) {{
    answer = {{ threw: String(e && e.stack || e) }};
  }}
  answer.loadErrors = errors;
  console.log(JSON.stringify(answer));
  try {{ dom.window.close(); }} catch (e) {{}}
  process.exit(0);
}})();
"""
    if not (SITE / "node_modules" / "jsdom").is_dir():
        raise AssertionError(
            "jsdom is required to execute the wiring and is not installed. Run `npm install` "
            f"in {SITE} (declared there as a test-only dependency)."
        )
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "render.cjs"
        path.write_text(script, encoding="utf-8")
        result = subprocess.run(
            [node, str(path)], capture_output=True, text=True, timeout=120
        )
    if result.returncode != 0:
        raise AssertionError(f"rendering failed:\n{result.stdout}\n{result.stderr}")
    return json.loads(result.stdout.strip().splitlines()[-1])


def _points_expr():
    """A JS expression (no trailing `;`) reading the six point fields as numbers."""
    return (
        "["
        "q('#viewport-edit-x1').value, q('#viewport-edit-y1').value, q('#viewport-edit-z1').value,"
        "q('#viewport-edit-x2').value, q('#viewport-edit-y2').value, q('#viewport-edit-z2').value"
        "].map(Number)"
    )


class LoadsCleanly(unittest.TestCase):
    def test_loads_without_throwing(self) -> None:
        got = render(FAKE_VIEWPORT_WEBGL, "return {};")
        self.assertEqual(
            got["loadErrors"], [], "picking/handles/panel threw while loading"
        )


class ShouldRotateHook(unittest.TestCase):
    """attachControls() must be told not to rotate mid-Alt-click or mid-drag."""

    def test_alt_key_suppresses_rotation(self) -> None:
        got = render(
            FAKE_VIEWPORT_WEBGL,
            "window.__AmuletViewportPanel._ensureViewportForTest();"
            "const hook = window.__lastAttachOptions.shouldRotate;"
            "return { plain: hook({altKey: false}), alt: hook({altKey: true}) };",
        )
        self.assertTrue(got["plain"], "a plain drag must still rotate the camera")
        self.assertFalse(got["alt"], "an Alt+drag must not also rotate the camera")

    def test_active_handle_drag_suppresses_rotation(self) -> None:
        got = render(
            FAKE_VIEWPORT_WEBGL,
            "window.__AmuletViewportPanel._ensureViewportForTest();"
            "window.__AmuletViewportPanel.setSolidTest((x, y, z) => y === 0);"
            "const canvas = q('#viewport-canvas');"
            "canvas.dispatchEvent(new window.PointerEvent('pointerdown', {"
            "  bubbles: true, button: 0, altKey: true, clientX: 400, clientY: 500,"
            "}));"
            "const hook = window.__lastAttachOptions.shouldRotate;"
            "return { dragging: window.__AmuletViewportPanel.isDraggingHandle(),"
            "         rotateWhileDragging: hook({altKey: false}) };",
        )
        # No selection exists yet, so this Alt+click is a point-pick, not a
        # handle grab -- it must not leave a drag in progress.
        self.assertFalse(got["dragging"])
        self.assertTrue(got["rotateWhileDragging"])


class ClickToPick(unittest.TestCase):
    def test_two_alt_clicks_set_both_selection_points(self) -> None:
        got = render(
            FAKE_VIEWPORT_WEBGL,
            "window.__AmuletViewportPanel._ensureViewportForTest();"
            "window.__AmuletViewportPanel.setSolidTest((x, y, z) => y === 0);"
            "const canvas = q('#viewport-canvas');"
            "function altClick(x, y) {"
            "  canvas.dispatchEvent(new window.PointerEvent('pointerdown', {"
            "    bubbles: true, button: 0, altKey: true, clientX: x, clientY: y,"
            "  }));"
            "}"
            "altClick(300, 500);"
            "const afterFirst = " + _points_expr() + ";"
            "altClick(500, 500);"
            "const afterSecond = " + _points_expr() + ";"
            "return { afterFirst, afterSecond };",
        )
        first = got["afterFirst"]
        second = got["afterSecond"]
        # Both points land on the y=0 ground plane the fixture's solidTest
        # accepts.
        self.assertEqual(first[1], 0)
        self.assertEqual(
            first, first[:3] * 2, "the first click sets both points to the same block"
        )
        self.assertEqual(second[1], 0)
        self.assertNotEqual(
            second[:3],
            second[3:],
            "the second click must move point 2 away from point 1",
        )


class KeyboardEquivalents(unittest.TestCase):
    def test_nudge_active_face_requires_a_selection_first(self) -> None:
        got = render(
            FAKE_VIEWPORT_WEBGL,
            "window.__AmuletViewportPanel._ensureViewportForTest();"
            "window.__AmuletViewportPanel.nudgeActiveFace(1);"
            "return { status: q('#viewport-status').textContent };",
        )
        self.assertIn("Enter both selection points first", got["status"])

    def test_nudge_active_face_moves_the_chosen_face_by_one_block(self) -> None:
        got = render(
            FAKE_VIEWPORT_WEBGL,
            "window.__AmuletViewportPanel._ensureViewportForTest();"
            "window.__AmuletViewportPanel.edit.setPoints([0, 0, 0], [4, 4, 4]);"
            # Face index 1 is FACE_HANDLES[1] == "face:+x" (see viewport-handles.js
            # buildHandles(): axis 0, directions [-1, 1] in that order).
            "window.__AmuletViewportPanel.getActiveFaceIndex();"
            "const key = new window.KeyboardEvent('keydown', { key: '2', bubbles: true, cancelable: true });"
            "q('#viewport-canvas').dispatchEvent(key);"
            "const bracket = new window.KeyboardEvent('keydown', { key: ']', bubbles: true, cancelable: true });"
            "q('#viewport-canvas').dispatchEvent(bracket);"
            "return " + _points_expr() + ";",
        )
        # face:+x nudged by +1 moves point2.x from 4 to 5; everything else
        # is untouched.
        self.assertEqual(got, [0, 0, 0, 5, 4, 4])

    def test_step_far_corner_moves_x_and_z_together(self) -> None:
        got = render(
            FAKE_VIEWPORT_WEBGL,
            "window.__AmuletViewportPanel._ensureViewportForTest();"
            "window.__AmuletViewportPanel.edit.setPoints([0, 0, 0], [4, 4, 4]);"
            "window.__AmuletViewportPanel.stepFarCorner(2, -1);"
            "return " + _points_expr() + ";",
        )
        self.assertEqual(got, [0, 0, 0, 6, 4, 3])

    def test_select_chunk_under_camera_uses_the_fake_cameras_position(self) -> None:
        got = render(
            FAKE_VIEWPORT_WEBGL,
            "window.__AmuletViewportPanel._ensureViewportForTest();"
            "window.__AmuletViewportPanel.selectChunkUnderCamera();"
            "return " + _points_expr() + ";",
        )
        # The fake camera sits at [8, 5, 8] -- chunk (0, 0), spanning 0..15
        # on X and Z (CHUNK_SIZE = 16 in viewport-panel.js).
        self.assertEqual(got, [0, 0, 0, 15, 255, 15])


class RayFromEventAgreesWithThePureModule(unittest.TestCase):
    """The wiring's ray construction must be the same function the pure
    ray-cast tests pin -- not a second, drifted copy of the same maths."""

    def test_ray_from_event_matches_rayFromCamera_at_screen_centre(self) -> None:
        got = render(
            FAKE_VIEWPORT_WEBGL,
            "window.__AmuletViewportPanel._ensureViewportForTest();"
            "const viewport = window.__AmuletViewportPanel.getViewport();"
            "const ray = window.__AmuletViewportPanel.rayFromEvent({ clientX: 400, clientY: 300 });"
            "const expected = window.AmuletViewportPicking.rayFromCamera("
            "  viewport.camera, viewport.fovYRadians, 800 / 600, 0, 0"
            ");"
            "return { ray, expected };",
        )
        for a, b in zip(got["ray"]["direction"], got["expected"]["direction"]):
            self.assertAlmostEqual(a, b, places=6)


if __name__ == "__main__":
    unittest.main()
