"""The Amulet Studio workspace, executed, not merely read.

Follows the pattern in test_site_runtime_render_contract.py: build a real DOM
with jsdom, run docs/site/studio-workspace.js as a browser would, and ask the
constructed page questions. A source-text grep cannot tell whether the module
throws on load, whether a "wired" ribbon command actually renders enabled, or
whether an "unwired" one carries its disabled reason rather than doing
nothing -- this file answers all three by executing the real script.

docs/site/index.html and docs/site/styles.css are never touched or loaded
here: the workspace is a separate mount point (#studio-workspace) sharing
modules with, not replacing, the published documentation site.
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
SCRIPT = SITE / "studio-workspace.js"


def render(setup_js: str, question: str) -> dict:
    """Build a minimal page with #studio-workspace, run `setup_js` before the
    module loads (e.g. to install a fake sidecar bridge), execute
    studio-workspace.js the way a <script> tag would, then answer `question`.
    """

    node = shutil.which("node")
    if node is None:
        raise AssertionError("node is required to execute the workspace script and was not found on PATH.")
    if not (SITE / "node_modules" / "jsdom").is_dir():
        raise AssertionError(
            "jsdom is required to execute the workspace and is not installed. Run `npm install` "
            f"in {SITE} (declared there as a test-only dependency)."
        )
    script = f"""
const {{ JSDOM }} = require({json.dumps(str((SITE / 'node_modules' / 'jsdom').as_posix()))});
const fs = require("fs");
const SCRIPT = {json.dumps(str(SCRIPT))};
const errors = [];
const dom = new JSDOM('<!doctype html><body><div id="studio-workspace"></div></body>', {{
  runScripts: "dangerously",
  url: "https://example.invalid/",
  pretendToBeVisual: true,
  beforeParse(window) {{
    window.addEventListener("error", e => errors.push("error: " + e.message));
  }},
}});
const {{ window }} = dom;
try {{ {setup_js} }} catch (e) {{ errors.push("setup: " + (e && e.message || e)); }}
try {{
  window.eval(fs.readFileSync(SCRIPT, "utf8"));
}} catch (e) {{
  errors.push("studio-workspace.js: " + (e && e.message || e));
}}
window.document.dispatchEvent(new window.Event("DOMContentLoaded", {{bubbles: true}}));
const q = sel => window.document.querySelector(sel);
const all = sel => [...window.document.querySelectorAll(sel)];
(async function () {{
  let answer;
  try {{
    answer = await (async function () {{ {question} }})();
  }} catch (e) {{
    answer = {{ threw: String(e && e.message || e) }};
  }}
  answer.loadErrors = errors;
  console.log(JSON.stringify(answer));
  try {{ dom.window.close(); }} catch (e) {{}}
  process.exit(0);
}})();
"""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "render.cjs"
        path.write_text(script, encoding="utf-8")
        result = subprocess.run([node, str(path)], capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise AssertionError(f"rendering failed:\n{result.stdout}\n{result.stderr}")
    return json.loads(result.stdout.strip().splitlines()[-1])


#: Installs a fake sidecar bridge that answers every call with a structured
#: "not implemented in this fixture" error -- enough for the module to treat
#: itself as "inside Electron" without a real Python sidecar process.
FAKE_SIDECAR = """
window.mmweDesktop = { sidecar: { call: function (method, params) {
  return Promise.resolve({ ok: false, error: { code: 'fixture_no_backend' } });
} } };
"""


class ThePageExecutesCleanly(unittest.TestCase):
    def test_loads_without_throwing_in_a_plain_browser(self) -> None:
        got = render("", "return {};")
        self.assertEqual(got["loadErrors"], [], "the module threw while loading with no sidecar present")

    def test_loads_without_throwing_with_a_sidecar(self) -> None:
        got = render(FAKE_SIDECAR, "return {};")
        self.assertEqual(got["loadErrors"], [], "the module threw while loading with a fake sidecar present")


class DesktopOnlyDegradeIsHonest(unittest.TestCase):
    """Outside Electron, the workspace says so instead of rendering a dead ribbon."""

    def test_no_sidecar_shows_an_explicit_desktop_only_message(self) -> None:
        got = render(
            "",
            "const root = q('#studio-workspace');"
            "return { text: root.textContent, hasRibbon: !!q('.sw-ribbon-tab') };",
        )
        self.assertIn("Desktop only", got["text"])
        self.assertFalse(got["hasRibbon"], "no ribbon should render when there is no sidecar to drive it")


class TheRibbonRendersAllSeventeenTabs(unittest.TestCase):
    def test_every_ribbon_tab_from_the_design_is_present(self) -> None:
        got = render(
            FAKE_SIDECAR,
            "return { tabs: all('.sw-ribbon-tab').map(b => b.textContent) };",
        )
        expected = [
            "Home", "Selection", "Operations", "Structures", "Chunks", "Terrain", "Build",
            "Entities", "Data", "Analyze", "Redstone", "Worldgen", "View", "Panels", "Extend",
            "Automate",
        ]
        self.assertEqual(got["tabs"], expected)

    def test_clicking_a_tab_selects_it_and_switches_groups(self) -> None:
        got = render(
            FAKE_SIDECAR,
            "const tabs = all('.sw-ribbon-tab');"
            "const home = tabs.find(b => b.textContent === 'Home');"
            "const terrain = tabs.find(b => b.textContent === 'Terrain');"
            "const homeGroupsBefore = all('.sw-ribbon-group-title').map(e => e.textContent);"
            "terrain.click();"
            "const terrainSelected = terrain.getAttribute('aria-selected');"
            "const homeSelected = home.getAttribute('aria-selected');"
            "const terrainGroups = all('.sw-ribbon-group-title').map(e => e.textContent);"
            "return { homeGroupsBefore, terrainSelected, homeSelected, terrainGroups };",
        )
        self.assertIn("Clipboard", got["homeGroupsBefore"])
        self.assertEqual(got["terrainSelected"], "true")
        self.assertEqual(got["homeSelected"], "false")
        self.assertIn("Sculpt", got["terrainGroups"])
        self.assertNotIn("Clipboard", got["terrainGroups"])


class DisabledCommandsAlwaysCarryAReason(unittest.TestCase):
    """The task's central contract: never silently inert, always disabled-with-reason."""

    def test_unwired_commands_are_disabled_with_a_reason_in_their_title(self) -> None:
        got = render(
            FAKE_SIDECAR,
            # 'Clone' is still genuinely unwired -- unlike 'Paste', which the
            # selection.paste sidecar lane wired for real (it is disabled
            # here only because this fixture has no world open).
            "const clone = all('.sw-ribbon-btn').find(b => b.textContent.indexOf('Clone') !== -1);"
            "return { disabled: clone.disabled, title: clone.title };",
        )
        self.assertTrue(got["disabled"])
        self.assertIn("Not yet wired to the desktop sidecar", got["title"])

    def test_undo_is_wired_but_disabled_without_an_open_world(self) -> None:
        got = render(
            FAKE_SIDECAR,
            "const undo = all('.sw-ribbon-btn').find(b => b.textContent.indexOf('Undo') !== -1);"
            "return { disabled: undo.disabled, title: undo.title };",
        )
        self.assertTrue(got["disabled"], "Undo has no open world in this fixture and must stay disabled")
        self.assertIn("Open a world", got["title"])

    def test_undo_is_wired_and_enabled_once_a_world_is_streaming(self) -> None:
        got = render(
            FAKE_SIDECAR
            + """
            window.__undoCalled = false;
            window.__AmuletViewportPanel = {
              isStreaming: () => true,
              runUndo: () => { window.__undoCalled = true; },
              edit: { readPoints: () => null },
            };
            """,
            "const undo = all('.sw-ribbon-btn').find(b => b.textContent.indexOf('Undo') !== -1);"
            "const wasDisabled = undo.disabled;"
            "undo.click();"
            "return { wasDisabled, called: window.__undoCalled };",
        )
        self.assertFalse(got["wasDisabled"], "Undo must render enabled once __AmuletViewportPanel reports streaming")
        self.assertTrue(got["called"], "clicking the wired Undo button must call the real runUndo()")


class TheNavigatorReflectsSidecarDimensions(unittest.TestCase):
    def test_empty_state_before_any_world_is_open(self) -> None:
        got = render(FAKE_SIDECAR, "return { text: q('.sw-navigator').textContent };")
        self.assertIn("No world open yet", got["text"])

    def test_opening_a_world_populates_the_navigator_from_world_dimensions(self) -> None:
        fake_dimension_flow = """
            window.mmweDesktop = { sidecar: { call: function (method, params) {
              if (method === 'world.open') {
                return Promise.resolve({ ok: true, result: { world_id: 'w1', status: 'pending' } });
              }
              if (method === 'world.open_status') {
                return Promise.resolve({ ok: true, result: { status: 'ready', world_id: 'w1' } });
              }
              if (method === 'world.dimensions') {
                return Promise.resolve({ ok: true, result: { dimensions: [
                  { dimension: 'overworld', bounds: { min: [0,0,0], max: [15,255,15] } },
                  { dimension: 'the_nether', bounds: { min: [0,0,0], max: [15,127,15] } },
                ] } });
              }
              return Promise.resolve({ ok: false, error: { code: 'unhandled' } });
            } } };
        """
        got = render(
            fake_dimension_flow,
            "window.document.getElementById('viewport-world-path').value = '/tmp/a-world';"
            "window.document.getElementById('viewport-open-button').click();"
            "await new Promise(resolve => setTimeout(resolve, 300));"
            "return { text: q('.sw-navigator').textContent };",
        )
        self.assertIn("overworld", got["text"])
        self.assertIn("the_nether", got["text"])


class ThePropertiesPaneAndStatusBarRender(unittest.TestCase):
    def test_pane_toggles_closed_and_reopens(self) -> None:
        got = render(
            FAKE_SIDECAR,
            "const before = !!q('.sw-pane .sw-pane-header');"
            "const closeBtn = all('.sw-pane-icon-btn').find(b => b.textContent === '×');"
            "closeBtn.click();"
            "const afterClose = !!q('.sw-pane .sw-pane-header');"
            "const properties = all('.sw-ribbon-btn').find(b => b.textContent.indexOf('Properties') !== -1);"
            "properties.click();"
            "const afterReopen = !!q('.sw-pane .sw-pane-header');"
            "return { before, afterClose, afterReopen };",
        )
        self.assertTrue(got["before"])
        self.assertFalse(got["afterClose"])
        self.assertTrue(got["afterReopen"])

    def test_status_bar_and_viewport_host_ids_are_present_for_viewport_panel_js(self) -> None:
        got = render(
            FAKE_SIDECAR,
            "return {"
            "  status: !!q('#viewport-status'),"
            "  host: !!q('#viewport-host'),"
            "  canvas: !!q('#viewport-canvas'),"
            "  empty: !!q('#viewport-empty'),"
            "  openRow: !!q('#viewport-open-row'),"
            "  openButton: !!q('#viewport-open-button'),"
            "  pathInput: !!q('#viewport-world-path'),"
            "};",
        )
        self.assertTrue(all([
            got["status"], got["host"], got["canvas"], got["empty"], got["openRow"],
            got["openButton"], got["pathInput"],
        ]))


class TheAnalyzeTabCallsTheRealBridge(unittest.TestCase):
    """Histogram/Chunk inspector/Validate must call
    Site.electronSidecar.analyze.*, never a dead ``run: null`` -- and the
    still-unbuilt commands (Biome map, Relight, Compare, Measure, Slice)
    must keep their honest disabled-with-reason state."""

    ANALYZE_FIXTURE = """
    window.AmuletSite = { electronSidecar: { analyze: {
      blockHistogram: function () {
        window.__analyzeCalledWith = Array.prototype.slice.call(arguments);
        return Promise.resolve({
          blocks_scanned: 10, distinct_blocks: 2,
          histogram: [{ block: 'universal_minecraft:stone', count: 8, percentage: 80 }],
        });
      },
      chunkInventory: function () { return Promise.resolve({ chunks_in_range: 1, chunks_present: 1, chunks: [] }); },
      blockAudit: function () { return Promise.resolve({ blocks_scanned: 10, flagged_count: 0, flagged_blocks: [] }); },
    } } };
    window.__AmuletViewportPanel = {
      isStreaming: () => true,
      getWorldId: () => "fixture-world-id",
      getDimension: () => "minecraft:overworld",
      edit: { readPoints: () => ({ point1: [0, 0, 0], point2: [3, 3, 3] }) },
    };
    """

    def test_histogram_is_enabled_and_calls_the_bridge(self) -> None:
        got = render(
            FAKE_SIDECAR + self.ANALYZE_FIXTURE,
            "const tabs = all('.sw-ribbon-tab');"
            "tabs.find(b => b.textContent === 'Analyze').click();"
            "const histo = all('.sw-ribbon-btn').find(b => b.textContent.indexOf('Histogram') !== -1);"
            "const wasDisabled = histo.disabled;"
            "histo.click();"
            "await new Promise(r => setTimeout(r, 20));"
            "const section = [...all('.sw-pane-section-title')].map(e => e.textContent).join('|');"
            "return { wasDisabled, calledWith: window.__analyzeCalledWith, section };",
        )
        self.assertFalse(got["wasDisabled"], "Histogram must render enabled with a sidecar, a streaming world, and a selection")
        self.assertIsNotNone(got["calledWith"], "clicking Histogram must call Site.electronSidecar.analyze.blockHistogram")
        self.assertIn("Analysis", got["section"])

    def test_chunk_inspector_and_validate_are_also_wired(self) -> None:
        got = render(
            FAKE_SIDECAR + self.ANALYZE_FIXTURE,
            "all('.sw-ribbon-tab').find(b => b.textContent === 'Analyze').click();"
            "const inspector = all('.sw-ribbon-btn').find(b => b.textContent.indexOf('Chunk inspector') !== -1);"
            "const validate = all('.sw-ribbon-btn').find(b => b.textContent.indexOf('Validate') !== -1);"
            "return { foundInspector: !!inspector, foundValidate: !!validate, inspectorDisabled: !!(inspector && inspector.disabled), validateDisabled: !!(validate && validate.disabled) };",
        )
        self.assertTrue(got["foundInspector"])
        self.assertTrue(got["foundValidate"])
        self.assertFalse(got["inspectorDisabled"])
        self.assertFalse(got["validateDisabled"])

    def test_analyze_without_a_selection_reports_an_honest_error_not_a_crash(self) -> None:
        got = render(
            FAKE_SIDECAR
            + """
            window.AmuletSite = { electronSidecar: { analyze: {
              blockHistogram: function () { return Promise.resolve({ blocks_scanned: 0, distinct_blocks: 0, histogram: [] }); },
            } } };
            window.__AmuletViewportPanel = { isStreaming: () => true, edit: { readPoints: () => null } };
            """,
            "all('.sw-ribbon-tab').find(b => b.textContent === 'Analyze').click();"
            "const histo = all('.sw-ribbon-btn').find(b => b.textContent.indexOf('Histogram') !== -1);"
            "histo.click();"
            "const errorRow = [...all('.sw-pane-row-value')].map(e => e.textContent).find(t => t.indexOf('point 1') !== -1);"
            "return { errorRow, threw: !!errorRow === false };",
        )
        self.assertIsNotNone(got["errorRow"], "clicking Histogram with no selection must report an honest error, not silently do nothing")

    def test_biome_map_is_still_honestly_unwired(self) -> None:
        got = render(
            FAKE_SIDECAR + self.ANALYZE_FIXTURE,
            "all('.sw-ribbon-tab').find(b => b.textContent === 'Analyze').click();"
            "const biome = all('.sw-ribbon-btn').find(b => b.textContent.indexOf('Biome map') !== -1);"
            "return { disabled: biome.disabled, title: biome.title };",
        )
        self.assertTrue(got["disabled"])
        self.assertIn("Not yet wired to the desktop sidecar", got["title"])


if __name__ == "__main__":
    unittest.main()
